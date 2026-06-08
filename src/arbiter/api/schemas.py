"""Request/response models for the moderate endpoint + the state->response mapper.

Per-category `severity` = the EFFECTIVE (post-adjustment) severity; `reason`/`span`
come from the RAW specialist verdict (spec §5.1/§9). The DB keeps raw + effective
+ flags side by side, so nothing is lost.

Check:  python -m pytest tests/api/test_schemas.py -v   (goal: 3 passed)
"""
from pydantic import BaseModel, Field

from arbiter.classify import ALL_6


class ModerateRequest(BaseModel):
    comment: str = Field(min_length=1)


class CategoryOut(BaseModel):
    name: str
    severity: int
    reason: str
    span: str | None


class ModerateResponse(BaseModel):
    overall_severity: int
    action: str
    categories: list[CategoryOut]
    context_flags: dict
    # escalation (spec 2026-06-08 §7): default-safe so the non-escalated path
    # serializes exactly as before, plus escalated:false.
    escalated: bool = False
    adjudication: dict | None = None


def to_response(state: dict) -> ModerateResponse:
    categories = [CategoryOut(name=c,
                              severity=state["effective_verdicts"][c],
                              reason=state["raw_verdicts"][c]["reason"],
                              span=state["raw_verdicts"][c]["span"]) for c in ALL_6]
    return ModerateResponse(overall_severity=state["overall_severity"],
                            action=state["action"],
                            categories=categories,
                            context_flags=state["context_flags"],
                            escalated=state.get("escalated", False),
                            adjudication=state.get("adjudication"))
