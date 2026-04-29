from __future__ import annotations

import json
from typing import Any


class ScriptedModelClient:
    """Deterministic model client for offline EvalBench cases."""

    def __init__(self, decisions: list[dict[str, Any] | str]) -> None:
        self.decisions = decisions
        self.calls = 0

    def complete(self, model: str, messages: list[dict[str, object]]) -> str:
        if self.calls < len(self.decisions):
            decision = self.decisions[self.calls]
        else:
            decision = {
                "thought": "Scripted actions exhausted.",
                "action": None,
                "final": None,
            }
        self.calls += 1
        if isinstance(decision, str):
            return decision
        return json.dumps(decision)
