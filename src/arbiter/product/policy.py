"""The policy lookup the adjudicator agent calls as a tool (escalation spec §5).

A plain local dict, NOT RAG / vectors -- deterministic, auditable, offline. Each of
the 6 Jigsaw categories maps to a short written policy + decision guidance the
adjudicator grounds its ruling in. `get_policy` is the function exposed as the
`get_policy(category)` tool.

Check:  python -m pytest tests/product/test_policy.py -v
"""
from arbiter.classify import ALL_6

# category -> written policy + decision guidance.
#
# Keep each entry short and decision-oriented: what IS a violation, what is NOT,
# and the gray-case rule. The identity_hate entry below is the TEMPLATE (filled
# from the spec example) -- match its shape for the other five.
POLICIES: dict[str, str] = {
    "identity_hate": (
        "Attacks or dehumanization targeting a protected group (race, religion, "
        "nationality, gender, sexual orientation, disability). NOT a violation: "
        "quoting or reporting a slur to condemn abuse, in-group reclaimed use, or "
        "merely mentioning an identity. Remove only when the text itself attacks a "
        "protected identity; when it is a report/quotation, do not remove."
    ),
    # TODO(you): write the remaining five, same shape (violation / not-a-violation / gray rule).
    "toxic": ( "Rude, disrespectful, or hostile language aimed at a person or group, likely "
        "to make them leave the conversation. NOT a violation: blunt criticism of an "
        "idea or someone's work, strong disagreement, or profanity not aimed at anyone. "
        "Gray rule: judge the target — hostility directed at a person counts; heat aimed "
        "at an argument does not. Sarcasm/quotation softens it."
    ),
    "severe_toxic":  (
        "An extreme form of toxicity: hateful, aggressive, or demeaning well beyond "
        "ordinary rudeness. NOT a violation: everyday insults or toxicity that are "
        "hostile but not extreme. Gray rule: set this only when the intensity is clearly "
        "severe; if it is merely 'toxic', leave severe_toxic off. Do not soften a "
        "genuinely extreme attack just because it is phrased as a joke."
    ),
    "obscene":  (
        "Vulgar, profane, or sexually explicit language in the text itself. NOT a "
        "violation: mild slang, or profanity quoted to report/condemn it. Gray rule: "
        "obscene tracks the LANGUAGE, not the target — profanity used as emphasis still "
        "counts; absence of profanity means no violation even if the comment is hostile."
    ),
    "threat": (
        "A credible expression of intent to harm a person or group — direct or "
        "conditional ('if you come back I'll hurt you'). NOT a violation: obvious "
        "hyperbole between friends ('I'll kill you lol'), fiction, or quoting a threat to "
        "report it. Gray rule: if a threat is ambiguous or could be real, prefer "
        "human-review over allow — missing a real threat is the costly error. A credible "
        "direct threat is NOT softened by sarcasm or quotation."
    ),
    "insult":  (
        "Name-calling or demeaning, contemptuous language targeting a PERSON. NOT a "
        "violation: criticism of an idea, work, or argument; self-deprecation; or "
        "reclaimed banter between consenting parties. Gray rule: an insult needs a "
        "personal target (general profanity with no target is 'obscene', not 'insult'). "
        "Sarcasm/quotation softens it."
    ),
}

_UNKNOWN = "No policy exists for that category. Valid categories: " + ", ".join(ALL_6) + "."


def get_policy(category: str) -> str:
    """Return the written policy for one category, or a defined 'unknown' string.

    Never raises -- the adjudicator may pass an arbitrary string; a bad lookup must
    degrade to guidance, not crash the loop.
    """
    return POLICIES.get(category, _UNKNOWN)
