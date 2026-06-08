"""Graph state for the product pipeline + the reducer parallel writers need.

The 6 specialist nodes all write `raw_verdicts` and `routing_snapshot` IN PARALLEL,
so those two channels need a reducer or LangGraph raises InvalidUpdateError.

Check:  python -m pytest tests/product/test_state.py -v   (goal: 5 passed)
"""
from typing import Annotated, TypedDict


def merge_verdicts(a: dict, b: dict) -> dict:
    return {**a, **b}


class ModerationState(TypedDict, total=False):
    comment: str
    raw_verdicts: Annotated[dict, merge_verdicts]
    routing_snapshot: Annotated[dict, merge_verdicts]
    context_flags: dict
    effective_verdicts: dict
    overall_severity: int
    action: str
    # --- escalation channels (spec 2026-06-08 §6) ---
    # Written by the single-threaded adjudicate / policy_tool nodes (NOT the
    # parallel fan-out), so no reducer is needed.
    escalated: bool             # did the adjudicator run? (durable -> response/UI)
    adj_messages: list          # the ReAct transcript -- the loop's working memory
    adj_steps: int              # tool-iteration counter -> drives the recursion cap
    adjudication: dict          # {final_action, note, policies_consulted: [...]} -> UI trace


def initial_state(comment: str) -> dict:
    return {"comment": comment, "raw_verdicts": {}, "routing_snapshot": {},
            "escalated": False, "adj_messages": [], "adj_steps": 0}
