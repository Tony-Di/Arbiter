from typing import Protocol

from pydantic import BaseModel


class AdapterError(RuntimeError):
    """Raised when a provider call fails or returns unparseable output."""


class Adapter(Protocol):
    """One provider's calling convention. Returns a raw dict (unvalidated).

    Validation + retry live in core.classify so they stay provider-agnostic.
    """

    def complete(self, prompt: str, schema: type[BaseModel]) -> dict: ...

    def complete_with_tools(self, messages: list, tools: list) -> dict:
        """Multi-turn tool-calling call (used by the adjudicator agent). Sends the full
        message list + tool defs and returns the raw assistant message (API-shaped:
        {role, content, tool_calls}), appendable straight back onto `messages`."""
        ...
