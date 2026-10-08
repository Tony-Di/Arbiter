"""Exercise real startup/shutdown, migrations and the local indexing worker."""
import time

from fastapi.testclient import TestClient

from arbiter.api import main
from arbiter.api.db import Precedent, PrecedentOutbox, init_db, make_engine, make_session_factory
from arbiter.precedents import PrecedentStore


def test_lifespan_indexes_durable_work_and_releases_checkpoint_connection(tmp_path, monkeypatch):
    engine = make_engine(f"sqlite:///{tmp_path / 'local.db'}")
    init_db(engine)
    sessions = make_session_factory(engine)
    with sessions() as db:
        db.add(PrecedentOutbox(case_id="human-case", payload={"comment_text": "confirmed example",
            "action": "allow", "overall_severity": 0, "note": "human reviewed", "source": "human"}))
        db.commit()
    monkeypatch.setattr(main, "init_db", lambda: init_db(engine))
    monkeypatch.setattr(main, "SessionLocal", sessions)
    monkeypatch.setattr(main, "PrecedentStore", lambda factory: PrecedentStore(factory, embed_fn=lambda _: [[1.0, 0.0]]))
    monkeypatch.setenv("CHECKPOINT_DB", str(tmp_path / "checkpoints.db"))
    checkpoint = None
    try:
        with TestClient(main.app) as client:
            assert client.get("/api/health").json() == {"status": "ok"}
            assert main._runtime_audit["providers"]
            assert all("api_key" not in config for config in main._runtime_audit["providers"].values())
            checkpoint = main._graph.checkpointer.conn
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                with sessions() as db:
                    if db.query(Precedent).count() == 1:
                        break
                time.sleep(0.02)
            with sessions() as db:
                assert db.query(Precedent).one().review_case_id == "human-case"
                assert db.query(PrecedentOutbox).one().status == "done"
        assert main._graph is None and main._runtime_audit == {}
        import sqlite3
        import pytest
        with pytest.raises(sqlite3.ProgrammingError):
            checkpoint.execute("SELECT 1")
    finally:
        engine.dispose()
