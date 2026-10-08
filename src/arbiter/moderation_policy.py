"""Versioned action contract shared by prompts, code and annotation validation."""
POLICY_VERSION = "2026-09-22.2"
CONTEXT_PROMPT_VERSION = "3"
ADJUDICATOR_PROMPT_VERSION = "3"

ACTION_SEVERITIES = {"allow": frozenset({0, 1}), "human-review": frozenset({1, 2, 3}),
                     "remove": frozenset({3})}
MITIGATABLE_CATEGORIES = frozenset({"toxic", "obscene", "insult", "identity_hate"})
MITIGATING_USES = frozenset({"reporting", "condemning", "reclaimed", "non_targeted"})

SEVERITY_RUBRIC = """Severity scale (per category):
First check the defining criteria of the requested category. Return 0 if absent,
even when a DIFFERENT category is harmful. Do not copy an overall harm rating into every category.
- none (0): no policy-relevant harm.
- low (1): mild or weak harm, without clear targeted abuse.
- medium (2): clear ordinary targeted abuse or insult; human-review, not automatic removal.
- high (3): severe abuse, an explicit protected-identity attack, or a credible direct threat; removal when unambiguous."""

ACTION_GUIDE = f"""Moderation policy {POLICY_VERSION}
{SEVERITY_RUBRIC}
Action rules: allow only at overall severity 0 or 1 without unresolved harmful ambiguity.
Human-review at severity 2, or when potentially harmful intent cannot be resolved from the text.
Remove only at severity 3 with clear evidence. Ordinary insults must not be removed at severity 2.
Judge the author's intent across the whole comment. Quotation and sarcasm are not exemptions.
Reporting or condemning abuse can mitigate only the affected categories, with an exact evidence span.
Endorsing a quoted attack, or using irony to attack someone, does not mitigate it.
Never downgrade a credible direct threat or extreme abuse through a context discount.
Unspecified negative consequences do not by themselves establish credible physical violence.
If threatening intent is plausible but the consequence or referent is missing, use human-review.
If the evidence cannot justify a change, keep human-review. Confidence is not proof."""

CATEGORY_RULES = {
    "toxic": "Hostile or disrespectful language directed at people. Civil disagreement and criticism of an idea alone do not qualify.",
    "severe_toxic": "Extreme hateful or demeaning abuse well beyond ordinary rudeness. Everyday insults alone do not qualify.",
    "obscene": "Vulgar, profane or sexually explicit wording. Hostility or a threat without such wording does not qualify.",
    "threat": "Expression of intent to physically harm someone, including credible conditional threats. Reporting or condemning a threat is not making one. Vague adverse consequences require review when violent intent is unresolved; do not invent violence or credibility. A joke marker alone does not establish harmlessness.",
    "insult": "Name-calling or demeaning language targeting a person. Mere disagreement, criticism of an idea, or a threat without demeaning language does not qualify. Ordinary targeted insults are severity 2.",
    "identity_hate": "Attacks targeting a protected identity such as race, religion, nationality, gender, sexual orientation or disability. Generic abuse of an unspecified person and merely mentioning a group do not qualify. Distinguish endorsing a quoted attack from reporting or condemning it.",
}


def action_for_severity(severity: int, *, ambiguous: bool = False) -> str:
    if ambiguous and severity > 0:
        return "human-review"
    return "remove" if severity >= 3 else "human-review" if severity == 2 else "allow"


def validate_action_severity(action: str, severity: int) -> None:
    if action not in ACTION_SEVERITIES or severity not in ACTION_SEVERITIES[action]:
        raise ValueError(f"action {action!r} is inconsistent with severity {severity!r}")


def mitigation_categories(flags: dict) -> set[str]:
    """Booleans alone, legacy flags and unsupported intent never authorize a discount."""
    if (flags.get("language_use") not in MITIGATING_USES or flags.get("ambiguity")
            or not flags.get("evidence_span") or not flags.get("note")):
        return set()
    return set(flags.get("mitigation_categories") or []) & MITIGATABLE_CATEGORIES


def unresolved_context(flags: dict) -> bool:
    return bool(flags.get("ambiguity") or flags.get("language_use") == "unclear")
