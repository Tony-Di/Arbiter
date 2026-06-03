from fastapi.testclient import TestClient

from arbiter.classify import ALL_6
from arbiter.classify.schema import ClassifyResult, Severity
from arbiter.product.context import ContextFlags
from arbiter.product.graph import build_graph
from arbiter.api.main import app, get_graph, get_db
from arbiter.api.db import Base, make_engine, make_session_factory, Submission

TABLE = {c: {"model": "deepseek-chat", "threshold": 1} for c in ALL_6}


def _fake_classify(model, comment, categories):
    cat = categories[0]
    sev = Severity.medium if cat == "insult" else Severity.none
    return ClassifyResult(verdicts={cat: {"severity": sev, "reason": "r", "span": None}})


def _fake_detect(comment):
    return ContextFlags()


def _client():
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    TestSession = make_session_factory(engine)
    fake_graph = build_graph(TABLE, classify_fn=_fake_classify, detect_fn=_fake_detect)

    def _get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_graph] = lambda: fake_graph
    app.dependency_overrides[get_db] = _get_db
    return TestClient(app), TestSession


def test_health():
    client, _ = _client()
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_moderate_returns_verdict():
    client, _ = _client()
    r = client.post("/api/moderate", json={"comment": "you idiot"})
    assert r.status_code == 200
    body = r.json()
    assert body["action"] == "human-review"
    assert body["overall_severity"] == 2
    insult = next(c for c in body["categories"] if c["name"] == "insult")
    assert insult["severity"] == 2
    assert len(body["categories"]) == 6


def test_moderate_persists_a_submission():
    client, TestSession = _client()
    client.post("/api/moderate", json={"comment": "you idiot"})
    db = TestSession()
    assert db.query(Submission).count() == 1


def test_empty_comment_is_422():
    client, _ = _client()
    r = client.post("/api/moderate", json={"comment": ""})
    assert r.status_code == 422


def teardown_function():
    app.dependency_overrides.clear()
