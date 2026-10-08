"""Deterministic aggregator — policy in code, NO LLM (spec §9c).

Turns raw per-category severities + context flags into effective severities,
an overall severity, and an action. Pure functions -> trivially testable +
fully auditable (this is the policy deliberately kept OUT of classify, so the
product never silently diverges from the eval numbers).

Check:  python -m pytest tests/product/test_aggregator.py -v   (goal: 13 passed)
"""

# Evidence-grounded mitigation applies only to explicitly named categories.
# Threat and severe_toxic cannot be discounted through the context branch.
from arbiter.moderation_policy import MITIGATABLE_CATEGORIES, action_for_severity, mitigation_categories, unresolved_context

DOWNGRADE_CATS = MITIGATABLE_CATEGORIES


def adjust_severities(raw_sev: dict, flags: dict) -> dict:
    eff = dict(raw_sev)
    for cat in mitigation_categories(flags):
        if cat in eff:
            eff[cat] = max(0, eff[cat] - 1)
    if flags.get("direct_threat"):
        eff["threat"] = max(eff.get("threat", 0), 3)
    return eff


def decide_action(effective: dict, flags: dict) -> str:
    return action_for_severity(max(effective.values(), default=0), ambiguous=unresolved_context(flags))

def overall_severity(effective: dict) -> int:
    return max(effective.values(), default=0)


def aggregate(raw_verdicts: dict, flags: dict) -> dict:
    raw_sev = {cat: v["severity"] for cat, v in raw_verdicts.items()}
    eff = adjust_severities(raw_sev, flags)
    return {"effective_verdicts": eff,
            "overall_severity": overall_severity(eff),
            "action": decide_action(eff, flags)}
