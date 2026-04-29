from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]


class ModelClient(Protocol):
    def complete(self, model: str, messages: list[dict[str, Any]]) -> str:
        """Return a JSON decision string for the agent loop."""


@runtime_checkable
class NativeToolCallingClient(Protocol):
    def complete_with_tools(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[ToolSpec],
    ) -> dict[str, Any]:
        """Return a normalized decision using the provider's native tool-calling API."""
