from arbiter.product.aggregator import (
    adjust_severities,
    decide_action,
    overall_severity,
    aggregate,
)

NO_FLAGS = {"sarcasm": False, "quotation": False, "reclaimed_slur": False,
            "direct_threat": False, "ambiguity": False, "note": None}


def _sev(**kw):
    base = {"toxic": 0, "severe_toxic": 0, "obscene": 0, "threat": 0, "insult": 0, "identity_hate": 0}
    base.update(kw)
    return base


# --- adjust_severities ---

def test_sarcasm_alone_does_not_downgrade_any_category():
    raw = _sev(toxic=2, obscene=2, insult=2, identity_hate=2, severe_toxic=2, threat=2)
    eff = adjust_severities(raw, {**NO_FLAGS, "sarcasm": True})
    assert eff == raw
    assert eff["severe_toxic"] == 2  # NOT in the downgrade set
    assert eff["threat"] == 2        # NOT in the downgrade set


def test_downgrade_floors_at_zero():
    raw = _sev(toxic=0)
    eff = adjust_severities(raw, {**NO_FLAGS, "quotation": True})
    assert eff["toxic"] == 0


def test_direct_threat_upgrades_threat_to_high():
    raw = _sev(threat=1)
    eff = adjust_severities(raw, {**NO_FLAGS, "direct_threat": True})
    assert eff["threat"] == 3


def test_no_flags_leaves_severities_unchanged():
    raw = _sev(toxic=2, threat=1)
    assert adjust_severities(raw, NO_FLAGS) == raw


# --- decide_action ---

def test_action_remove_when_any_high():
    assert decide_action(_sev(threat=3), NO_FLAGS) == "remove"


def test_action_human_review_when_max_medium():
    assert decide_action(_sev(insult=2), NO_FLAGS) == "human-review"


def test_action_allow_when_all_low_or_none():
    assert decide_action(_sev(toxic=1), NO_FLAGS) == "allow"


def test_ambiguity_override_escalates_allow_to_human_review():
    # toxic=1 -> would be "allow"; ambiguity set + a flagged (>=low) category -> escalate
    assert decide_action(_sev(toxic=1), {**NO_FLAGS, "ambiguity": True}) == "human-review"


def test_ambiguity_override_does_not_fire_when_nothing_flagged():
    assert decide_action(_sev(), {**NO_FLAGS, "ambiguity": True}) == "allow"


# --- overall_severity ---

def test_overall_is_max():
    assert overall_severity(_sev(toxic=1, threat=3, insult=2)) == 3


def test_overall_empty_is_zero():
    assert overall_severity({}) == 0


# --- aggregate (end-to-end of the deterministic policy) ---

def test_aggregate_sarcastic_insult_still_requires_review():
    raw_verdicts = {
        "insult": {"severity": 2, "reason": "name-calling", "span": "idiot"},
        "toxic": {"severity": 1, "reason": "rude", "span": None},
    }
    out = aggregate(raw_verdicts, {**NO_FLAGS, "sarcasm": True})
    assert out["effective_verdicts"]["insult"] == 2
    assert out["overall_severity"] == 2
    assert out["action"] == "human-review"


def test_aggregate_direct_threat_forces_remove():
    raw_verdicts = {"threat": {"severity": 1, "reason": "maybe hyperbole", "span": "kill"}}
    out = aggregate(raw_verdicts, {**NO_FLAGS, "direct_threat": True})
    assert out["effective_verdicts"]["threat"] == 3
    assert out["action"] == "remove"
