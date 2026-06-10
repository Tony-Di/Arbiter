"""Request/response models for the moderate endpoint + the state->response mapper.

Per-category `severity` = the EFFECTIVE (post-adjustment) severity; `reason`/`span`
come from the RAW specialist verdict (spec §5.1/§9). The DB keeps raw + effective
+ flags side by side, so nothing is lost.

Check:  python -m pytest tests/api/test_schemas.py -v   (goal: 3 passed)
"""
from datetime import datetime
from typing import Literal

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
    # HITL (spec 2026-06-09 §7): default-safe -- old clients see status:"final".
    status: Literal["final"] = "final"
    case_id: str | None = None


class PendingOut(BaseModel):
    """Returned by /api/moderate when the case paused for human review."""
    status: Literal["pending"] = "pending"
    case_id: str
    comment: str
    recommendation: dict


class ReviewCaseOut(BaseModel):
    case_id: str
    comment: str
    recommendation: dict
    created_at: datetime


class ReviewDecision(BaseModel):
    action: Literal["allow", "remove", "confirm"]
    note: str | None = None


def to_response(state: dict, case_id: str | None = None) -> ModerateResponse:
    categories = [CategoryOut(name=c,
                              severity=state["effective_verdicts"][c],
                              reason=state["raw_verdicts"][c]["reason"],
                              span=state["raw_verdicts"][c]["span"]) for c in ALL_6]
    return ModerateResponse(overall_severity=state["overall_severity"],
                            action=state["action"],
                            categories=categories,
                            context_flags=state["context_flags"],
                            escalated=state.get("escalated", False),
                            adjudication=state.get("adjudication"),
                            case_id=case_id)
