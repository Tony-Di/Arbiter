from arbiter.classify import ALL_6
from arbiter.api.schemas import to_response, ModerateResponse


def _state():
    raw = {c: {"severity": 0, "reason": f"r-{c}", "span": None} for c in ALL_6}
    raw["insult"] = {"severity": 2, "reason": "name-calling", "span": "idiot"}
    eff = {c: 0 for c in ALL_6}
    eff["insult"] = 2
    return {
        "comment": "you idiot",
        "raw_verdicts": raw,
        "routing_snapshot": {c: "deepseek-chat" for c in ALL_6},
        "context_flags": {"sarcasm": False, "quotation": False, "reclaimed_slur": False,
                          "direct_threat": False, "ambiguity": False, "note": None},
        "effective_verdicts": eff,
        "overall_severity": 2,
        "action": "human-review",
    }


def test_to_response_top_level_fields():
    r = to_response(_state())
    assert isinstance(r, ModerateResponse)
    assert r.overall_severity == 2
    assert r.action == "human-review"
    assert r.context_flags["sarcasm"] is False


def test_to_response_has_all_6_categories_in_order():
    r = to_response(_state())
    assert [c.name for c in r.categories] == ALL_6


def test_to_response_category_uses_effective_severity_and_raw_reason_span():
    by = {c.name: c for c in to_response(_state()).categories}
    assert by["insult"].severity == 2          # EFFECTIVE
    assert by["insult"].reason == "name-calling"  # from RAW
    assert by["insult"].span == "idiot"
    assert by["toxic"].severity == 0
    assert by["toxic"].span is None
