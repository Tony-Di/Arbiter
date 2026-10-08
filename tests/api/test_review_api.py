"""Review-queue API: pending moderate responses, queue listing, resolution +
precedent write-back. Zero-network (fakes + InMemorySaver + in-memory DB).

Check:  python -m pytest tests/api/test_review_api.py -v
"""
import json

from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

from arbiter.classify import ALL_6
from arbiter.classify.schema import ClassifyResult, Severity
from arbiter.product.context import ContextFlags
from arbiter.product.graph import build_graph
from arbiter.api.main import app, get_graph, get_db, get_store
from arbiter.api.db import Base, ReviewCase, Verdict, make_engine, make_session_factory

TABLE = {c: {"model": "deepseek-chat", "threshold": 1} for c in ALL_6}


def _fake_classify(model, comment, categories):
    cat = categories[0]
    sev = Severity.medium if cat == "insult" else Severity.none
    return ClassifyResult(verdicts={cat: {"severity": sev, "reason": "r", "span": None}})


def _fake_detect(comment):
    return ContextFlags(ambiguity=True)


def _submitting(confidence, action="allow"):
    def fn(messages, tools):
        return {"role": "assistant", "content": None, "tool_calls": [
            {"id": "1", "function": {"name": "submit_decision",
                "arguments": json.dumps({"action": action, "overall_severity": 1,
                                         "note": "n", "confidence": confidence,
                                         "policy_category": "insult", "evidence_span": "you idiot"})}}]}
    return fn


class RecordingStore:
    def __init__(self):
        self.added = []

    def add(self, comment_text, action, overall_severity, note, source="human"):
        self.added.append({"comment_text": comment_text, "action": action,
                           "overall_severity": overall_severity, "note": note,
                           "source": source})

    def search(self, query, k=3):
        return []


def _client(confidence=0.3):
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    TestSession = make_session_factory(engine)
    store = RecordingStore()
    fake_graph = build_graph(TABLE, classify_fn=_fake_classify, detect_fn=_fake_detect,
                             adjudicate_fn=_submitting(confidence), store=store,
                             checkpointer=InMemorySaver())

    def _get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_graph] = lambda: fake_graph
    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_store] = lambda: store
    return TestClient(app), TestSession, store


def teardown_function():
    app.dependency_overrides.clear()


def test_low_confidence_moderate_goes_pending():
    client, TestSession, _ = _client(confidence=0.3)
    r = client.post("/api/moderate", json={"comment": "you idiot"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "pending"
    assert body["case_id"]
    assert body["recommendation"]["recommended_action"] == "allow"
    db = TestSession()
    assert db.query(ReviewCase).filter_by(status="pending").count() == 1
    assert db.query(Verdict).count() == 0          # no verdict until a human rules


def test_high_confidence_moderate_stays_final():
    client, TestSession, _ = _client(confidence=0.95)
    r = client.post("/api/moderate", json={"comment": "you idiot"})
    body = r.json()
    assert body["status"] == "final"
    assert body["action"] == "allow"
    assert TestSession().query(Verdict).count() == 1


def test_review_queue_lists_pending_cases():
    client, _, _ = _client()
    client.post("/api/moderate", json={"comment": "you idiot"})
    r = client.get("/api/review-queue")
    assert r.status_code == 200
    cases = r.json()
    assert len(cases) == 1
    assert cases[0]["comment"] == "you idiot"
    assert cases[0]["recommendation"]["confidence"] == 0.3


def test_resolve_finalizes_persists_and_writes_precedent():
    client, TestSession, store = _client()
    case_id = client.post("/api/moderate",
                          json={"comment": "you idiot"}).json()["case_id"]
    r = client.post(f"/api/review/{case_id}",
                    json={"action": "remove", "note": "clear attack"})
    assert r.status_code == 200
    assert r.json()["action"] == "remove"
    db = TestSession()
    assert db.query(Verdict).count() == 1
    assert db.query(ReviewCase).filter_by(status="resolved").count() == 1
    assert store.added == [{"comment_text": "you idiot", "action": "remove",
                            "overall_severity": 3, "note": "clear attack",
                            "source": "human"}]


def test_resolve_unknown_case_is_404():
    client, _, _ = _client()
    assert client.post("/api/review/nope", json={"action": "remove"}).status_code == 404


def test_double_resolve_is_409():
    client, _, _ = _client()
    case_id = client.post("/api/moderate",
                          json={"comment": "you idiot"}).json()["case_id"]
    client.post(f"/api/review/{case_id}", json={"action": "remove"})
    assert client.post(f"/api/review/{case_id}",
                       json={"action": "allow"}).status_code == 409
