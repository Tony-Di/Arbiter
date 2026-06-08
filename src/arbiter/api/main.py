"""FastAPI app — wraps the LangGraph pipeline (spec §12).

Graph + routing table are built ONCE at startup (lifespan). The graph and DB
session are dependencies so tests override them (fakes + in-memory DB, no network).

Check:  python -m pytest tests/api/test_api.py -v   (goal: 4 passed)
"""
import os
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from fastapi import Depends, FastAPI

from arbiter.product.adjudicator import default_adjudicate_fn
from arbiter.product.graph import build_graph
from arbiter.product.routing import load_routing_table
from arbiter.product.state import initial_state
from arbiter.api.db import SessionLocal, init_db, save_verdict
from arbiter.api.schemas import ModerateRequest, ModerateResponse, to_response

# Load .env so registry.py sees DEEPSEEK_API_KEY. The import above does NOTHING
# without this call -- this is the line that was missing.
load_dotenv()

_graph = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _graph
    init_db()
    # ROUTING_TABLE lets local/dev point at a deepseek-only table (run on one key);
    # default stays the real eval-derived table.
    table_path = os.environ.get("ROUTING_TABLE", "routing_table.json")
    _graph = build_graph(load_routing_table(table_path),
                         adjudicate_fn=default_adjudicate_fn)
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


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/moderate", response_model=ModerateResponse)
def moderate(req: ModerateRequest, graph=Depends(get_graph), db=Depends(get_db)):
    state = graph.invoke(initial_state(req.comment))
    save_verdict(db, req.comment, state)
    return to_response(state)
