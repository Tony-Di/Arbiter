"""Shared prompt for classify — identical across providers (fair comparison).

Fill in build_prompt (spec: plan Task 2).
Check:  python -m pytest tests/classify/test_prompt.py -v   (goal: 3 passed)
"""
from .schema import ALL_6

PROMPT_VERSION = "1"

# Approved rubric (design spec §5) — embed this verbatim so every model scores
# against ONE scale. You may keep it as-is; bump PROMPT_VERSION if you reword it.
RUBRIC = """\
Severity scale (per category):
- none (0): no policy-relevant harm for this category.
- low (1): mild or ambiguous - borderline, weak/uncertain, plausibly-but-not-clearly harmful.
- medium (2): clear harmful content; a likely human-review candidate.
- high (3): severe - a credible direct threat, an explicit identity attack, or severe abuse; a removal candidate."""


def build_prompt(comment: str, categories: list[str] = ALL_6) -> str:
    # 🔨 TODO: return ONE string that contains all four of these:
    #   1. instructions — you are a content-moderation rater; judge ONLY the listed
    #      categories; for each return severity 0-3, a short reason, and span (the
    #      verbatim offending substring, or null); detection only, no overall action;
    #      output JSON like:
    #        {"verdicts": {"<category>": {"severity": <0-3>, "reason": "...", "span": <string|null>}}}
    #   2. the RUBRIC above
    #   3. the requested category names (join `categories`)
    #   4. the COMMENT text
    # NOTE: the word "json" MUST appear in the prompt (DeepSeek json_object mode needs it).

    return f"""
    You are a content-moderation rater.
    You are given a comment and a list of categories.
    You need to judge the comment for each category.
    The severity scale is:
    - none (0): no policy-relevant harm for this category.
    - low (1): mild or ambiguous - borderline, weak/uncertain, plausibly-but-not-clearly harmful.
    - medium (2): clear harmful content; a likely human-review candidate.
    - high (3): severe - a credible direct threat, an explicit identity attack, or severe abuse; a removal candidate.
    The output should be a JSON object with the following structure:
    {{
        "verdicts": {{
            "<category>": {{
                "severity": <0-3>,
                "reason": "...",
                "span": "<string|null>"
            }}
        }}
    }}
    The categories are: {categories}
    The comment is: {comment}
    """
