import pytest
from pydantic import ValidationError

from arbiter.classify.schema import (
    ALL_6,
    SCHEMA_VERSION,
    CategoryVerdict,
    ClassifyResult,
    Severity,
)


def test_all_6_is_the_jigsaw_label_set():
    assert ALL_6 == ["toxic", "severe_toxic", "obscene", "threat", "insult", "identity_hate"]


def test_severity_is_ordinal_0_to_3():
    assert int(Severity.none) == 0 and int(Severity.high) == 3


def test_category_verdict_accepts_nullable_span():
    assert CategoryVerdict(severity=Severity.low, reason="mild", span=None).span is None


def test_classify_result_round_trips_from_dict():
    raw = {"verdicts": {"toxic": {"severity": 2, "reason": "rude", "span": "you idiot"}}}
    assert ClassifyResult.model_validate(raw).verdicts["toxic"].severity == Severity.medium


def test_invalid_severity_is_rejected():
    with pytest.raises(ValidationError):
        CategoryVerdict(severity=9, reason="x", span=None)


def test_schema_version_is_present():
    assert isinstance(SCHEMA_VERSION, str) and SCHEMA_VERSION
