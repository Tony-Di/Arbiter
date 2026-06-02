import pytest

from arbiter.classify.adapters.openai_compat import OpenAICompatAdapter
from arbiter.classify.registry import REGISTRY, get_adapter


def test_deepseek_and_openai_are_registered():
    assert "deepseek-chat" in REGISTRY and "gpt-4o-mini" in REGISTRY


def test_get_adapter_builds_openai_compat_for_deepseek(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    assert isinstance(get_adapter("deepseek-chat"), OpenAICompatAdapter)


def test_unknown_model_raises():
    with pytest.raises(KeyError):
        get_adapter("no-such-model")


def test_missing_api_key_raises(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        get_adapter("deepseek-chat")
