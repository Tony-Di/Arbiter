"""Real on-disk SQLite + checkpoints, with all provider calls replaced by fakes."""
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event

import pytest
from fastapi import HTTPException
from langgraph.checkpoint.sqlite import SqliteSaver
from sqlalchemy import text

from arbiter.api import reviews
from arbiter.api.db import (Precedent, PrecedentOutbox, ReviewCase, Submission, Verdict,
                           init_db, make_engine, make_session_factory)
from arbiter.api.outbox import drain_outbox
from arbiter.api.reviews import resolve_case, utcnow
from arbiter.classify import ALL_6
from arbiter.classify.schema import ClassifyResult
from arbiter.precedents import PrecedentStore
from arbiter.product.context import ContextFlags
from arbiter.product.graph import build_graph
from arbiter.product.state import initial_state

DECISION = {"action": "remove", "note": "human confirmed severe abuse"}


@pytest.fixture
def local(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'app.db'}")
    init_db(engine)
    sessions = make_session_factory(engine)
    connections = []
    def graph():
        conn = sqlite3.connect(tmp_path / "checkpoints.db", check_same_thread=False)
        connections.append(conn)
        def classify(model, comment, categories):
            return ClassifyResult(verdicts={c: {"severity": 2 if c == "insult" else 0,
                "reason": "test", "span": None} for c in categories})
        def forbidden(*_):
            raise AssertionError("Clear medium case does not need adjudication")
        return build_graph({c: {"model": "fake", "threshold": 1} for c in ALL_6},
            classify_fn=classify, detect_fn=lambda _: ContextFlags(), adjudicate_fn=forbidden,
            checkpointer=SqliteSaver(conn))
    g = graph()
    result = g.invoke(initial_state("you idiot"), {"configurable": {"thread_id": "case-1"}})
    with sessions() as db:
        db.add(ReviewCase(case_id="case-1", comment_text="you idiot",
                          recommendation=result["__interrupt__"][0].value))
        db.commit()
    yield sessions, graph, g, engine
    for conn in connections:
        conn.close()
    engine.dispose()


def test_pending_case_can_be_resumed_by_new_graph_after_restart(local):
    sessions, restart, _, _ = local
    with sessions() as db:
        final = resolve_case(db, restart(), "case-1", DECISION)
        assert final["action"] == "remove" and final["overall_severity"] == 3
        assert db.query(Verdict).one().audit["policy_version"]
        assert db.query(PrecedentOutbox).count() == 1
        assert db.query(ReviewCase).one().status == "resolved"


def test_repeated_identical_request_returns_result_without_duplicate_rows(local):
    sessions, _, graph, _ = local
    with sessions() as db:
        first = resolve_case(db, graph, "case-1", DECISION)
    with sessions() as db:
        assert resolve_case(db, graph, "case-1", DECISION) == first
        assert db.query(Submission).count() == db.query(Verdict).count() == db.query(PrecedentOutbox).count() == 1
        with pytest.raises(HTTPException) as exc:
            resolve_case(db, graph, "case-1", {"action": "allow", "note": None})
        assert exc.value.status_code == 409


def test_failure_after_checkpoint_resume_rolls_back_and_recovers_without_resuming_twice(local, monkeypatch):
    sessions, restart, graph, _ = local
    real_save = reviews.save_verdict
    def fail_after_flush(*args, **kwargs):
        real_save(*args, **kwargs)
        raise RuntimeError("crash after partial SQL work")
    monkeypatch.setattr(reviews, "save_verdict", fail_after_flush)
    with sessions() as db:
        with pytest.raises(RuntimeError):
            resolve_case(db, graph, "case-1", DECISION)
    with sessions() as db:
        assert db.query(Submission).count() == db.query(Verdict).count() == db.query(PrecedentOutbox).count() == 0
        case = db.query(ReviewCase).one()
        assert case.status == "resolving" and case.decision == DECISION
    monkeypatch.setattr(reviews, "save_verdict", real_save)
    restarted = restart()
    def forbidden(*_, **__):
        raise AssertionError("Completed checkpoint must be reused, not resumed again")
    monkeypatch.setattr(restarted, "invoke", forbidden)
    with sessions() as db:
        assert resolve_case(db, restarted, "case-1", DECISION)["action"] == "remove"
        assert db.query(Verdict).count() == db.query(PrecedentOutbox).count() == 1


def test_expired_resolution_lease_recovers_after_process_crash(local):
    sessions, restart, _, _ = local
    with sessions() as db:
        case = db.query(ReviewCase).one()
        case.status, case.decision, case.lease_token = "resolving", DECISION, "dead-worker"
        case.lease_until = utcnow() - timedelta(seconds=1)
        db.commit()
    with sessions() as db:
        assert resolve_case(db, restart(), "case-1", DECISION)["action"] == "remove"


def test_simultaneous_review_requests_have_one_owner(local):
    sessions, _, graph, _ = local
    entered, release = Event(), Event()
    class SlowGraph:
        def get_state(self, cfg):
            return graph.get_state(cfg)
        def invoke(self, command, config):
            entered.set()
            assert release.wait(10)
            return graph.invoke(command, config=config)
    def first():
        with sessions() as db:
            return resolve_case(db, SlowGraph(), "case-1", DECISION)
    with ThreadPoolExecutor(max_workers=2) as pool:
        future = pool.submit(first)
        try:
            assert entered.wait(10)
            with sessions() as db:
                with pytest.raises(HTTPException) as exc:
                    resolve_case(db, graph, "case-1", DECISION)
                assert exc.value.status_code == 409
        finally:
            release.set()
        assert future.result()["action"] == "remove"
    with sessions() as db:
        assert db.query(Verdict).count() == 1


def test_embedding_failure_keeps_verdict_and_retries_once_without_duplicates(local):
    sessions, _, graph, _ = local
    with sessions() as db:
        resolve_case(db, graph, "case-1", DECISION)
    def unavailable(_):
        raise TimeoutError("private provider details must not be persisted")
    bad_store = PrecedentStore(sessions, embed_fn=unavailable)
    assert drain_outbox(sessions, bad_store) == {"completed": 0, "failed": 1}
    with sessions() as db:
        assert db.query(Verdict).count() == 1
        assert db.query(ReviewCase).one().status == "resolved"
        item = db.query(PrecedentOutbox).one()
        assert item.status == "pending" and item.attempts == 1 and item.last_error == "TimeoutError"
        item.next_attempt_at = utcnow() - timedelta(seconds=1)
        db.commit()
    store = PrecedentStore(sessions, embed_fn=lambda _: [[1.0, 0.0]])
    assert drain_outbox(sessions, store) == {"completed": 1, "failed": 0}
    assert drain_outbox(sessions, store) == {"completed": 0, "failed": 0}
    with sessions() as db:
        assert db.query(Precedent).one().review_case_id == "case-1"
        assert db.query(PrecedentOutbox).one().attempts == 2


def test_expired_embedding_lease_is_reclaimed(local):
    sessions, _, graph, _ = local
    with sessions() as db:
        resolve_case(db, graph, "case-1", DECISION)
        item = db.query(PrecedentOutbox).one()
        item.status, item.lease_token = "processing", "dead-worker"
        item.lease_until = utcnow() - timedelta(seconds=1)
        db.commit()
    store = PrecedentStore(sessions, embed_fn=lambda _: [[0.0, 1.0]])
    assert drain_outbox(sessions, store)["completed"] == 1


def test_cannot_confirm_a_review_recommendation(local):
    sessions, _, graph, _ = local
    with sessions() as db:
        with pytest.raises(HTTPException) as exc:
            resolve_case(db, graph, "case-1", {"action": "confirm", "note": None})
        assert exc.value.status_code == 422
        assert db.query(ReviewCase).one().status == "pending"


def test_additive_migration_preserves_legacy_data(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE review_cases (id INTEGER PRIMARY KEY, case_id VARCHAR UNIQUE, comment_text VARCHAR, recommendation JSON, status VARCHAR, created_at TIMESTAMP, resolved_at TIMESTAMP)"))
        conn.execute(text("INSERT INTO review_cases VALUES (1, 'legacy', 'old comment', '{}', 'pending', CURRENT_TIMESTAMP, NULL)"))
        conn.execute(text("CREATE TABLE precedents (id INTEGER PRIMARY KEY, comment_text VARCHAR, embedding JSON, action VARCHAR, overall_severity INTEGER, note VARCHAR, source VARCHAR, created_at TIMESTAMP)"))
        conn.execute(text("INSERT INTO precedents VALUES (1, 'old human case', '[1,0]', 'allow', 1, 'reviewed', 'human', CURRENT_TIMESTAMP)"))
    init_db(engine)
    init_db(engine)  # restart is safe and does not reapply columns
    with make_session_factory(engine)() as db:
        assert db.query(ReviewCase).one().comment_text == "old comment"
        assert db.query(ReviewCase).one().decision is None
        assert db.query(Precedent).one().review_case_id is None
    engine.dispose()
