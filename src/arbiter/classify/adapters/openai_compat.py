"""OpenAI-compatible adapter — reused for any OpenAI-compatible provider
(DeepSeek, OpenAI, Qwen, ...). One call -> a raw dict; validation lives in core.

Check:  python -m pytest tests/classify/test_adapter_openai_compat.py -v   (goal: 2 passed)
"""
import json

from openai import OpenAI  # keep this import here — the test patches this name
from pydantic import BaseModel

from .base import AdapterError


class OpenAICompatAdapter:
    def __init__(self, base_url: str, api_key: str, model: str):
        # timeout + max_retries: never let one slow call hang the eval OR an API
        # request (the SDK default is a 600s timeout). Retries back off on 429/503.
        self.client = OpenAI(base_url=base_url, api_key=api_key, timeout=30.0, max_retries=2)
        self.model = model
        

    def complete(self, prompt: str, schema: type[BaseModel]) -> dict:
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0,
            )
            content = resp.choices[0].message.content
            return json.loads(content)
        except Exception as e:
            raise AdapterError(str(e)) from e