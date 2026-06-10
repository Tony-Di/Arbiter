"""FastAPI app — wraps the LangGraph pipeline (spec §12).

Graph + routing table are built ONCE at startup (lifespan). The graph and DB
session are dependencies so tests override them (fakes + in-memory DB, no network).

Check:  python -m pytest tests/api/test_api.py -v   (goal: 4 passed)
"""
import os
import sqlite3
from contextlib import asynccontextmanager
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from arbiter.precedents import PrecedentStore
from arbiter.product.adjudicator import default_adjudicate_fn
from arbiter.product.graph import build_graph
from arbiter.product.routing import load_routing_table
from arbiter.product.state import initial_state
from arbiter.api.db import ReviewCase, SessionLocal, init_db, save_verdict
from arbiter.api.schemas import (
    ModerateRequest,
    ModerateResponse,
    PendingOut,
    ReviewCaseOut,
    ReviewDecision,
    to_response,
)
from datetime import datetime
# Load .env so registry.py sees DEEPSEEK_API_KEY. The import above does NOTHING
# without this call -- this is the line that was missing.
load_dotenv()

_graph = None
_store = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _graph, _store
    init_db()
    _store = PrecedentStore(SessionLocal)
    # ROUTING_TABLE lets local/dev point at a deepseek-only table (run on one key);
    # default stays the real eval-derived table.
    table_path = os.environ.get("ROUTING_TABLE", "routing_table.json")
    # checkpoints.db: the graph's pause/resume state (gitignored, like arbiter.db).
    # check_same_thread=False: FastAPI sync endpoints run on a thread pool.
    conn = sqlite3.connect("checkpoints.db", check_same_thread=False)
    _graph = build_graph(load_routing_table(table_path),
                         adjudicate_fn=default_adjudicate_fn,
                         store=_store, checkpointer=SqliteSaver(conn))
    yield


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
    """TODO(author):
    1. case_id = str(uuid4()); cfg = {"configurable": {"thread_id": case_id}}
    2. state = graph.invoke(initial_state(req.comment), config=cfg)
    3. if "__interrupt__" in state: persist ReviewCase(case_id=case_id,
       comment_text=req.comment, recommendation=state["__interrupt__"][0].value),
       commit, return PendingOut(case_id=..., comment=..., recommendation=...)
    4. else: save_verdict + to_response as today (to_response gains case_id=case_id).
    """
    case_id = str(uuid4())
    cfg = {"configurable": {"thread_id": case_id}}
    state = graph.invoke(initial_state(req.comment), config=cfg)
    if "__interrupt__" in state:
        db.add(ReviewCase(case_id=case_id, comment_text=req.comment, recommendation=state["__interrupt__"][0].value))
        db.commit()
        return PendingOut(case_id=case_id, comment=req.comment, recommendation=state["__interrupt__"][0].value)
    else:
        save_verdict(db, req.comment, state)
        return to_response(state, case_id=case_id)


@app.get("/api/review-queue", response_model=list[ReviewCaseOut])
def review_queue(db=Depends(get_db)):
    """TODO(author): pending ReviewCase rows, newest first, mapped to ReviewCaseOut
    (case_id / comment=comment_text / recommendation / created_at)."""
    case_id = db.query(ReviewCase).filter_by(status="pending").order_by(ReviewCase.created_at.desc()).all()
    return [ReviewCaseOut(case_id=case.case_id, comment=case.comment_text, recommendation=case.recommendation, created_at=case.created_at) for case in case_id]


@app.post("/api/review/{case_id}", response_model=ModerateResponse)
def resolve_review(case_id: str, decision: ReviewDecision,
                   graph=Depends(get_graph), db=Depends(get_db),
                   store=Depends(get_store)):
    """TODO(author):
    1. case = db.query(ReviewCase).filter_by(case_id=case_id).first()
       -> None: raise HTTPException(404); status=="resolved": raise HTTPException(409)
    2. final = graph.invoke(Command(resume={"action": decision.action,
                                            "note": decision.note}),
                            config={"configurable": {"thread_id": case_id}})
    3. one transaction: save_verdict(db, case.comment_text, final);
       store.add(case.comment_text, final["action"], final["overall_severity"],
                 decision.note or final["adjudication"]["note"], source="human");
       case.status = "resolved"; case.resolved_at = datetime.now(); db.commit()
    4. return to_response(final, case_id=case_id)
    """
    case = db.query(ReviewCase).filter_by(case_id=case_id).first()
    if case is None:
        raise HTTPException(404)
    if case.status == "resolved":
        raise HTTPException(409)
    final = graph.invoke(Command(resume={"action": decision.action, "note": decision.note}), config={"configurable": {"thread_id": case_id}})
    save_verdict(db, case.comment_text, final)
    store.add(case.comment_text, final["action"], final["overall_severity"], decision.note or final["adjudication"]["note"], source="human")
    case.status = "resolved"; case.resolved_at = datetime.now(); db.commit()
    return to_response(final, case_id=case_id)