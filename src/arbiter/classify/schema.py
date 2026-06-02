"""Shared schema for classify — the data contract the whole project sits on.

Fill in the TODOs below (spec: plan Task 1).
Check your work:  python -m pytest tests/classify/test_schema.py -v   (goal: 6 passed)
"""
from enum import IntEnum

from pydantic import BaseModel

SCHEMA_VERSION = "1"

# 🔨 TODO: the 6 Jigsaw labels, in this order:
#   toxic, severe_toxic, obscene, threat, insult, identity_hate
ALL_6 = ["toxic", "severe_toxic", "obscene", "threat", "insult", "identity_hate"]


class Severity(IntEnum):
    # 🔨 TODO: none=0, low=1, medium=2, high=3
    none = 0
    low = 1
    medium = 2
    high = 3


class CategoryVerdict(BaseModel):
    # 🔨 TODO: severity (Severity), reason (str), span (str | None, default None)
    severity: Severity
    reason: str
    span: str | None = None


class ClassifyResult(BaseModel):
    # 🔨 TODO: verdicts -> dict[str, CategoryVerdict]
    verdicts: dict[str, CategoryVerdict]
