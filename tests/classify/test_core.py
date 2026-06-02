from unittest.mock import patch

import pytest

from arbiter.classify.core import classify
from arbiter.classify.schema import ClassifyResult, Severity


class _ScriptedAdapter:
    """Returns queued payloads in order; an Exception payload is raised."""

    def __init__(self, *payloads):
        self._q = list(payloads)

    def complete(self, prompt, schema):
        item = self._q.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


GOOD = {"verdicts": {"toxic": {"severity": 2, "reason": "rude", "span": "idiot"}}}
BAD = {"verdicts": {"toxic": {"severity": 99, "reason": "x", "span": None}}}


def test_classify_returns_validated_result():
    with patch("arbiter.classify.core.get_adapter", return_value=_ScriptedAdapter(GOOD)):
        r = classify("deepseek-chat", "you idiot", ["toxic"])
    assert isinstance(r, ClassifyResult) and r.verdicts["toxic"].severity == Severity.medium


def test_classify_retries_once_then_succeeds():
    with patch("arbiter.classify.core.get_adapter", return_value=_ScriptedAdapter(BAD, GOOD)):
        r = classify("deepseek-chat", "you idiot", ["toxic"])
    assert r.verdicts["toxic"].severity == Severity.medium


def test_classify_raises_after_two_failures():
    with patch("arbiter.classify.core.get_adapter", return_value=_ScriptedAdapter(BAD, BAD)):
        with pytest.raises(Exception):
            classify("deepseek-chat", "you idiot", ["toxic"])
