"""Model registry — maps a model-id string to a freshly built adapter.
Adding a model later = one more row. One OpenAI-compatible adapter is reused for
every OpenAI-compatible provider (DeepSeek, OpenAI, Qwen, ...).

Check:  python -m pytest tests/classify/test_registry.py -v   (goal: 4 passed)
"""
import os

from .adapters.base import Adapter
from .adapters.openai_compat import OpenAICompatAdapter
# The factual config is filled in for you (base_urls / env names / real model ids).
REGISTRY = {
    "deepseek-chat": {
        "adapter": OpenAICompatAdapter,
        "base_url": "https://api.siliconflow.cn/v1",
        "api_key_env": "DEEPSEEK_API_KEY",
        "model": "deepseek-ai/DeepSeek-V4-Pro",
    },
    "gpt-4o-mini": {
        "adapter": OpenAICompatAdapter,
        "base_url": "https://api.openai.com/v1",
        "api_key_env": "OPENAI_API_KEY",
        "model": "gpt-4o-mini",
    },
}


def get_adapter(model_id: str) -> Adapter:
    cfg = REGISTRY[model_id]
    api_key = os.environ.get(cfg["api_key_env"])
    if not api_key:
        raise RuntimeError(f"Missing {cfg['api_key_env']} for {model_id}")
    return cfg["adapter"](base_url=cfg["base_url"], api_key=api_key, model=cfg["model"])
