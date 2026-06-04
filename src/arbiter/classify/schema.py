"""Shared schema for classify — the data contract the whole project sits on.

Check your work:  python -m pytest tests/classify/test_schema.py -v   (goal: 6 passed)
"""
from enum import IntEnum

from pydantic import BaseModel

SCHEMA_VERSION = "1"

ALL_6 = ["toxic", "severe_toxic", "obscene", "threat", "insult", "identity_hate"]


class Severity(IntEnum):
    none = 0
    low = 1
    medium = 2
    high = 3


class CategoryVerdict(BaseModel):
    severity: Severity
    reason: str
    span: str | None = None


class ClassifyResult(BaseModel):
    verdicts: dict[str, CategoryVerdict]
