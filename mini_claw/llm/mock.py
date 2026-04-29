from __future__ import annotations

import json


class MockModelClient:
    """Deterministic offline client for demos and smoke tests."""

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, model: str, messages: list[dict[str, object]]) -> str:
        self.calls += 1
        if self.calls == 1:
            return json.dumps(
                {
                    "thought": "Inspect the workspace before proposing changes.",
                    "action": {
                        "tool": "shell",
                        "args": {
                            "command": (
                                "python -c \"from itertools import islice; "
                                "from pathlib import Path; "
                                "files=(x for x in Path('.').rglob('*') if x.is_file()); "
                                "print(chr(10).join(str(p) for p in islice(files, 40)))\""
                            )
                        },
                    },
                    "final": None,
                }
            )
        return json.dumps(
            {
                "thought": "The mock client only demonstrates the runtime loop.",
                "action": None,
                "final": (
                    "Mock run completed. Connect an OpenAI-compatible provider to let the "
                    "agent plan patches and run verification on real tasks."
                ),
            }
        )
