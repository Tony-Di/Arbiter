"""Deterministic aggregator — policy in code, NO LLM (spec §9c).

Turns raw per-category severities + context flags into effective severities,
an overall severity, and an action. Pure functions -> trivially testable +
fully auditable (this is the policy deliberately kept OUT of classify, so the
product never silently diverges from the eval numbers).

Check:  python -m pytest tests/product/test_aggregator.py -v   (goal: 13 passed)
"""

# Sarcasm / quotation / reclaimed-slur downgrade applies to EXACTLY these four.
# Note: severe_toxic and threat are deliberately NOT in this set (spec §9c).
DOWNGRADE_CATS = {"toxic", "obscene", "insult", "identity_hate"}


def adjust_severities(raw_sev: dict, flags: dict) -> dict:
    eff = dict(raw_sev)
    if flags.get("sarcasm") or flags.get("quotation") or flags.get("reclaimed_slur"):
        for cat in DOWNGRADE_CATS:
            if cat in eff: eff[cat] = max(0, eff[cat] - 1)
    if flags.get("direct_threat"):
        eff["threat"] = max(eff.get("threat", 0), 3)
    return eff


def decide_action(effective: dict, flags: dict) -> str:
    sevs = list(effective.values())
    action = "remove" if any(s >= 3 for s in sevs) \
             else "human-review" if any(s >= 2 for s in sevs) \
             else "allow"
    # safety override: never auto-allow a flagged gray case
    if flags.get("ambiguity") and any(s >= 1 for s in sevs) and action == "allow":
        action = "human-review"
    return action

def overall_severity(effective: dict) -> int:
    return max(effective.values(), default=0)


def aggregate(raw_verdicts: dict, flags: dict) -> dict:
    raw_sev = {cat: v["severity"] for cat, v in raw_verdicts.items()}
    eff = adjust_severities(raw_sev, flags)
    return {"effective_verdicts": eff,
            "overall_severity": overall_severity(eff),
            "action": decide_action(eff, flags)}
