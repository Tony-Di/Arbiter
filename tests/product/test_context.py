from unittest.mock import patch

import pytest

from arbiter.product.context import ContextFlags, build_context_prompt, detect_context


class _ScriptedAdapter:
    def __init__(self, *payloads):
        self._q = list(payloads)

    def complete(self, prompt, schema):
        item = self._q.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def test_prompt_mentions_json_and_the_comment():
    p = build_context_prompt("I'll kill you 😂")
    assert "json" in p.lower()
    assert "I'll kill you 😂" in p


def test_context_flags_defaults_are_false_none():
    f = ContextFlags()
    assert f.sarcasm is False and f.ambiguity is False and f.note is None


def test_detect_context_returns_validated_flags():
    payload = {"sarcasm": True, "quotation": False, "reclaimed_slur": False,
               "direct_threat": False, "ambiguity": False, "note": "joke between friends"}
    with patch("arbiter.product.context.get_adapter", return_value=_ScriptedAdapter(payload)):
        f = detect_context("I'll kill you 😂")
    assert isinstance(f, ContextFlags) and f.sarcasm is True and f.note == "joke between friends"


def test_detect_context_retries_once_then_succeeds():
    bad = {"sarcasm": "not-a-bool"}  # fails validation
    good = {"sarcasm": True}
    with patch("arbiter.product.context.get_adapter", return_value=_ScriptedAdapter(bad, good)):
        f = detect_context("whatever")
    assert f.sarcasm is True


def test_detect_context_raises_after_two_failures():
    bad = {"sarcasm": "not-a-bool"}
    with patch("arbiter.product.context.get_adapter", return_value=_ScriptedAdapter(bad, bad)):
        with pytest.raises(Exception):
            detect_context("whatever")
