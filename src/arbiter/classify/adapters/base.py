from typing import Protocol

from pydantic import BaseModel


class AdapterError(RuntimeError):
    """Raised when a provider call fails or returns unparseable output."""


class Adapter(Protocol):
    """One provider's calling convention. Returns a raw dict (unvalidated).

    Validation + retry live in core.classify so they stay provider-agnostic.
    """

    def complete(self, prompt: str, schema: type[BaseModel]) -> dict: ...
