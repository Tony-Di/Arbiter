"""Request/response models for the moderate endpoint + the state->response mapper.

Per-category `severity` = the EFFECTIVE (post-adjustment) severity; `reason`/`span`
come from the RAW specialist verdict (spec §5.1/§9). The DB keeps raw + effective
+ flags side by side, so nothing is lost.

Fill the TODOs (spec: plan Task 1).
Check:  python -m pytest tests/api/test_schemas.py -v   (goal: 3 passed)
"""
from pydantic import BaseModel, Field

from arbiter.classify import ALL_6


class ModerateRequest(BaseModel):
    comment: str = Field(min_length=1)


class CategoryOut(BaseModel):
    # 🔨 TODO: name: str ; severity: int ; reason: str ; span: str | None
    name: str
    severity: int
    reason: str
    span: str | None


class ModerateResponse(BaseModel):
    # 🔨 TODO: overall_severity: int ; action: str ;
    #          categories: list[CategoryOut] ; context_flags: dict
    overall_severity: int
    action: str
    categories: list[CategoryOut]
    context_flags: dict


def to_response(state: dict) -> ModerateResponse:
    # 🔨 TODO:
    #   categories = [CategoryOut(name=c,
    #                             severity=state["effective_verdicts"][c],
    #                             reason=state["raw_verdicts"][c]["reason"],
    #                             span=state["raw_verdicts"][c]["span"]) for c in ALL_6]
    #   return ModerateResponse(overall_severity=state["overall_severity"],
    #                           action=state["action"],
    #                           categories=categories,
    #                           context_flags=state["context_flags"])
    categories = [CategoryOut(name=c,
                              severity=state["effective_verdicts"][c],
                              reason=state["raw_verdicts"][c]["reason"],
                              span=state["raw_verdicts"][c]["span"]) for c in ALL_6]
    return ModerateResponse(overall_severity=state["overall_severity"],
                            action=state["action"],
                            categories=categories,
                            context_flags=state["context_flags"])
