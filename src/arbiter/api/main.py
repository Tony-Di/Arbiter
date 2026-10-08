"""FastAPI app — wraps the LangGraph pipeline (spec §12).

Graph + routing table are built ONCE at startup (lifespan). The graph and DB
session are dependencies so tests override them (fakes + in-memory DB, no network).

Check:  python -m pytest tests/api/test_api.py -v   (goal: 4 passed)
"""
import asyncio
import os
import sqlite3
from contextlib import asynccontextmanager
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException
from langgraph.checkpoint.sqlite import SqliteSaver

from arbiter.precedents import PrecedentStore
from arbiter.classify.registry import REGISTRY
from arbiter.product.adjudicator import ADJUDICATOR_MODEL, default_adjudicate_fn
from arbiter.product.context import CONTEXT_MODEL
from arbiter.product.graph import build_graph
from arbiter.product.routing import load_routing_table
from arbiter.product.state import initial_state
from arbiter.api.db import ReviewCase, SessionLocal, init_db, save_verdict
from arbiter.api.outbox import run_outbox_worker
from arbiter.api.reviews import resolve_case
from arbiter.api.schemas import (
    ModerateRequest,
    ModerateResponse,
    PendingOut,
    ReviewCaseOut,
    ReviewDecision,
    to_response,
)
# Load .env so registry.py sees DEEPSEEK_API_KEY. The import above does NOTHING
# without this call -- this is the line that was missing.
load_dotenv()

_graph = None
_store = None
_runtime_audit = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _graph, _store, _runtime_audit
    init_db()
    _store = PrecedentStore(SessionLocal)
    # ROUTING_TABLE lets local/dev point at a deepseek-only table (run on one key);
    # default stays the real eval-derived table.
    table_path = os.environ.get("ROUTING_TABLE", "routing_table.json")
    # checkpoints.db: the graph's pause/resume state (gitignored, like arbiter.db).
    # check_same_thread=False: FastAPI sync endpoints run on a thread pool.
    conn = sqlite3.connect(os.environ.get("CHECKPOINT_DB", "checkpoints.db"), check_same_thread=False)
    table = load_routing_table(table_path)
    model_ids = {entry["model"] for entry in table.values()} | {CONTEXT_MODEL, ADJUDICATOR_MODEL}
    _runtime_audit = {"context_model": CONTEXT_MODEL, "adjudicator_model": ADJUDICATOR_MODEL,
                      "routing_table": table,
                      "providers": {m: {k: REGISTRY[m][k] for k in ("base_url", "model")} for m in sorted(model_ids)}}
    _graph = build_graph(table,
                         adjudicate_fn=default_adjudicate_fn,
                         store=_store, checkpointer=SqliteSaver(conn))
    stop = asyncio.Event()
    worker = asyncio.create_task(run_outbox_worker(SessionLocal, _store, stop))
    try:
        yield
    finally:
        stop.set()
        await worker
        conn.close()
        _graph, _store, _runtime_audit = None, None, {}


app = FastAPI(title="Arbiter", lifespan=lifespan)


def get_graph():
    return _graph


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_store():
    return _store


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/moderate", response_model=ModerateResponse | PendingOut)
def moderate(req: ModerateRequest, graph=Depends(get_graph), db=Depends(get_db)):
    """Persist a final verdict or expose the checkpointed human review."""
    case_id = str(uuid4())
    cfg = {"configurable": {"thread_id": case_id}}
    start = initial_state(req.comment)
    start["audit"].update(_runtime_audit)
    state = graph.invoke(start, config=cfg)
    if "__interrupt__" in state:
        db.add(ReviewCase(case_id=case_id, comment_text=req.comment, recommendation=state["__interrupt__"][0].value))
        db.commit()
        return PendingOut(case_id=case_id, comment=req.comment, recommendation=state["__interrupt__"][0].value)
    else:
        save_verdict(db, req.comment, state)
        return to_response(state, case_id=case_id)


@app.get("/api/review-queue", response_model=list[ReviewCaseOut])
def review_queue(db=Depends(get_db)):
    cases = db.query(ReviewCase).filter(ReviewCase.status.in_(["pending", "resolving"])).order_by(ReviewCase.created_at.desc()).all()
    return [ReviewCaseOut(case_id=case.case_id, comment=case.comment_text,
                          recommendation=case.recommendation, created_at=case.created_at,
                          status=case.status, decision=case.decision) for case in cases]


@app.post("/api/review/{case_id}", response_model=ModerateResponse)
def resolve_review(case_id: str, decision: ReviewDecision,
                   graph=Depends(get_graph), db=Depends(get_db)):
    try:
        final = resolve_case(db, graph, case_id, decision.model_dump())
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(503, "Could not finish saving; retry the same action and note") from exc
    return to_response(final, case_id=case_id)
