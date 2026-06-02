import json
from unittest.mock import MagicMock, patch

import pytest

from arbiter.classify.adapters.base import AdapterError
from arbiter.classify.adapters.openai_compat import OpenAICompatAdapter
from arbiter.classify.schema import ClassifyResult


def _resp(content):
    m = MagicMock()
    m.choices = [MagicMock(message=MagicMock(content=content))]
    return m


@patch("arbiter.classify.adapters.openai_compat.OpenAI")
def test_complete_returns_parsed_dict(mock_openai):
    client = mock_openai.return_value
    payload = {"verdicts": {"toxic": {"severity": 1, "reason": "mild", "span": None}}}
    client.chat.completions.create.return_value = _resp(json.dumps(payload))

    a = OpenAICompatAdapter(base_url="https://x", api_key="k", model="deepseek-chat")
    out = a.complete("prompt", ClassifyResult)

    assert out == payload
    _, kw = client.chat.completions.create.call_args
    assert kw["model"] == "deepseek-chat" and kw["temperature"] == 0
    assert kw["response_format"] == {"type": "json_object"}


@patch("arbiter.classify.adapters.openai_compat.OpenAI")
def test_complete_wraps_bad_json_in_adapter_error(mock_openai):
    mock_openai.return_value.chat.completions.create.return_value = _resp("not json{{")
    a = OpenAICompatAdapter(base_url="https://x", api_key="k", model="deepseek-chat")
    with pytest.raises(AdapterError):
        a.complete("prompt", ClassifyResult)
