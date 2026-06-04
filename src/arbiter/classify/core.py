"""classify() — the shared primitive. Ties prompt + adapter + schema together.

Check:  python -m pytest tests/classify/test_core.py -v   (goal: 3 passed)
"""
from .prompt import build_prompt
from .registry import get_adapter
from .schema import ALL_6, ClassifyResult


def classify(model: str, comment: str, categories: list[str] = ALL_6) -> ClassifyResult:
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