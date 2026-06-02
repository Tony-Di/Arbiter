"""classify() — the shared primitive. Ties prompt + adapter + schema together.

Fill in classify (spec: plan Task 6).
Check:  python -m pytest tests/classify/test_core.py -v   (goal: 3 passed)
"""
from .prompt import build_prompt
from .registry import get_adapter
from .schema import ALL_6, ClassifyResult


def classify(model: str, comment: str, categories: list[str] = ALL_6) -> ClassifyResult:
    # 🔨 TODO:
    #   1. adapter = get_adapter(model)
    #   2. prompt = build_prompt(comment, categories)
    #   3. Try up to TWICE (retry once):
    #        raw = adapter.complete(prompt, ClassifyResult)
    #        return ClassifyResult.model_validate(raw)   # success -> return immediately
    #      If it raises (adapter failure OR validation failure), try once more.
    #      If the SECOND attempt also raises, let that error propagate (don't swallow it).
    #
    #   Hint for the retry: a `for _ in range(2):` loop with try/except inside —
    #   `return` on success; in `except`, remember the error and continue; after the
    #   loop, `raise` the remembered error.
    
    adapter = get_adapter(model)
    prompt = build_prompt(comment, categories)
    error = None
    for _ in range(2):
        try:
            raw = adapter.complete(prompt, ClassifyResult)
            return ClassifyResult.model_validate(raw)
        except Exception as e:
            error = e
            continue
    if error:
        raise error