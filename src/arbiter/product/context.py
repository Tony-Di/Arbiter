"""Context/sarcasm node — emits MODIFIER FLAGS only, never re-scores (spec §9b).

Mirrors classify's shape: get_adapter -> complete(prompt, ContextFlags) -> validate,
retry once. The deterministic aggregator is what ACTS on these flags; this node
only reads context and reports it.

Fill the TODOs (spec: plan Task 4).
Check:  python -m pytest tests/product/test_context.py -v   (goal: 5 passed)
"""
from pydantic import BaseModel

from arbiter.classify.registry import get_adapter  # patched in tests

# The model that judges context. Single-model MVP -> DeepSeek (the only paid model);
# a stronger reasoning model can be swapped in later with this one line.
CONTEXT_MODEL = "deepseek-chat"


class ContextFlags(BaseModel):
    # 🔨 TODO: 5 bool fields (each default False) + an optional note:
    #   sarcasm: bool = False         # harmful-looking text is a joke / not literal
    #   quotation: bool = False       # the slur/threat is quoted, not asserted
    #   reclaimed_slur: bool = False  # in-group reclaimed term, not an attack
    #   direct_threat: bool = False   # credible, directed threat (not hyperbole)
    #   ambiguity: bool = False       # genuinely unclear; needs a human
    #   note: str | None = None       # optional one-line explanation
    
    sarcasm: bool = False
    quotation: bool = False
    reclaimed_slur: bool = False
    direct_threat: bool = False
    ambiguity: bool = False
    note: str | None = None

def build_context_prompt(comment: str) -> str:
    # 🔨 TODO: return ONE string that (1) explains each of the 5 flags VERBATIM
    #   (definitions above), (2) says to output JSON shaped like ContextFlags,
    #   (3) includes the comment text. The word "json" MUST appear (DeepSeek's
    #   json_object mode requires it). Example JSON to show the model:
    #     {"sarcasm": false, "quotation": false, "reclaimed_slur": false,
    #      "direct_threat": false, "ambiguity": false, "note": null}
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
        "sarcasm": <bool>,
        "quotation": <bool>,
        "reclaimed_slur": <bool>,
        "direct_threat": <bool>,
        "ambiguity": <bool>,
        "note": <string|null>
    }}
    The comment is: {comment}
    """
def detect_context(comment: str, model: str = CONTEXT_MODEL) -> ContextFlags:
    # 🔨 TODO: same retry-once shape as classify:
    #   adapter = get_adapter(model); prompt = build_context_prompt(comment)
    #   error = None
    #   for _ in range(2):
    #       try: return ContextFlags.model_validate(adapter.complete(prompt, ContextFlags))
    #       except Exception as e: error = e
    #   raise error
    
    adapter = get_adapter(model)
    prompt = build_context_prompt(comment)
    error = None
    for _ in range(2):
        try: return ContextFlags.model_validate(adapter.complete(prompt, ContextFlags))
        except Exception as e: error = e
    raise error