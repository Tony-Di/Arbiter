"""OpenAI-compatible adapter — reused for any OpenAI-compatible provider
(DeepSeek, OpenAI, Qwen, ...). One call -> a raw dict; validation lives in core.

Fill in the two methods (spec: plan Task 4).
Check:  python -m pytest tests/classify/test_adapter_openai_compat.py -v   (goal: 2 passed)
"""
import json

from openai import OpenAI  # keep this import here — the test patches this name
from pydantic import BaseModel

from .base import AdapterError


class OpenAICompatAdapter:
    def __init__(self, base_url: str, api_key: str, model: str):
        self.client = OpenAI(base_url=base_url, api_key=api_key)
        self.model = model
        

    def complete(self, prompt: str, schema: type[BaseModel]) -> dict:
        # 🔨 TODO (wrap the whole thing in try/except):
        #   1. resp = self.client.chat.completions.create(
        #          model=self.model,
        #          messages=[{"role": "user", "content": prompt}],
        #          response_format={"type": "json_object"},
        #          temperature=0,
        #      )
        #   2. content = resp.choices[0].message.content      # a JSON string
        #   3. return json.loads(content)                     # raw dict, UNvalidated
        #   4. except Exception as e: raise AdapterError(str(e)) from e
        # (don't validate against `schema` here — core does that.)
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