"""Graph state for the product pipeline + the reducer parallel writers need.

The 6 specialist nodes all write `raw_verdicts` and `routing_snapshot` IN PARALLEL,
so those two channels need a reducer or LangGraph raises InvalidUpdateError.

Fill the TODOs (spec: plan Task 1).
Check:  python -m pytest tests/product/test_state.py -v   (goal: 5 passed)
"""
from typing import Annotated, TypedDict


def merge_verdicts(a: dict, b: dict) -> dict:
    # 🔨 TODO: return a NEW dict merging a and b; b wins on key conflicts.
    #   Hint: {**a, **b}  (do NOT mutate a or b)
    return {**a, **b}


class ModerationState(TypedDict, total=False):
    # 🔨 TODO: declare the fields. The two written by parallel specialist nodes
    #   MUST use the reducer; the rest are plain:
    #     comment: str
    #     raw_verdicts: Annotated[dict, merge_verdicts]
    #     routing_snapshot: Annotated[dict, merge_verdicts]
    #     context_flags: dict
    #     effective_verdicts: dict
    #     overall_severity: int
    #     action: str
    comment: str
    raw_verdicts: Annotated[dict, merge_verdicts]
    routing_snapshot: Annotated[dict, merge_verdicts]
    context_flags: dict
    effective_verdicts: dict
    overall_severity: int
    action: str


def initial_state(comment: str) -> dict:
    # 🔨 TODO: seed the reducer channels so callers don't have to:
    #   return {"comment": comment, "raw_verdicts": {}, "routing_snapshot": {}}
    return {"comment": comment, "raw_verdicts": {}, "routing_snapshot": {}}
