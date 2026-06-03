from arbiter.classify import ALL_6
from arbiter.api.db import Base, make_engine, make_session_factory, save_verdict, Submission, Verdict


def _state():
    raw = {c: {"severity": 0, "reason": "r", "span": None} for c in ALL_6}
    raw["insult"] = {"severity": 2, "reason": "name-calling", "span": "idiot"}
    return {
        "raw_verdicts": raw,
        "routing_snapshot": {c: "deepseek-chat" for c in ALL_6},
        "context_flags": {"sarcasm": False, "ambiguity": False, "note": None},
        "effective_verdicts": {**{c: 0 for c in ALL_6}, "insult": 2},
        "overall_severity": 2,
        "action": "human-review",
    }


def _session():
    engine = make_engine("sqlite://")          # in-memory, StaticPool -> shared
    Base.metadata.create_all(engine)
    return make_session_factory(engine)()


def test_save_verdict_persists_both_rows():
    db = _session()
    sub = save_verdict(db, "you idiot", _state())
    assert sub.id is not None
    assert db.query(Submission).count() == 1
    assert db.query(Submission).one().comment_text == "you idiot"
    v = db.query(Verdict).one()
    assert v.submission_id == sub.id
    assert v.action == "human-review"
    assert v.overall_severity == 2


def test_save_verdict_roundtrips_json_columns():
    db = _session()
    save_verdict(db, "you idiot", _state())
    v = db.query(Verdict).one()
    assert v.raw_verdicts["insult"]["span"] == "idiot"          # JSON column round-trips
    assert v.effective_verdicts["insult"] == 2
    assert v.routing_snapshot["insult"] == "deepseek-chat"
