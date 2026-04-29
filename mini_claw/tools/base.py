from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ToolResult:
    ok: bool
    output: str
    modified_files: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolOutputHandle:
    output_id: str
    tool: str
    ok: bool
    preview: str
    lookup_hint: str
    lookup_queries: list[str]
    output_chars: int
    stored_output_chars: int
    truncated: bool
    store_truncated: bool
    modified_files: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def render_for_model(self) -> str:
        truncation = []
        if self.truncated:
            truncation.append("inline")
        if self.store_truncated:
            truncation.append("store")
        truncation_state = ",".join(truncation) if truncation else "none"
        lines = [
            (
                "[tool_result] "
                f"tool={self.tool} ok={self.ok} id={self.output_id} "
                f"chars={self.output_chars} truncated={truncation_state}"
            )
        ]
        if self.modified_files:
            lines.append("modified_files=" + ", ".join(self.modified_files))
        if self.preview:
            lines.extend(["", self.preview])
        if self.lookup_queries:
            lines.append("lookup_queries=" + " | ".join(self.lookup_queries[:3]))
        lines.extend(["", f"lookup: {self.lookup_hint}"])
        return "\n".join(lines)

    def to_trace(self) -> dict[str, Any]:
        return {
            "output_id": self.output_id,
            "tool": self.tool,
            "ok": self.ok,
            "lookup_hint": self.lookup_hint,
            "lookup_queries": self.lookup_queries,
            "output_chars": self.output_chars,
            "stored_output_chars": self.stored_output_chars,
            "truncated": self.truncated,
            "store_truncated": self.store_truncated,
            "modified_files": self.modified_files,
        }


class Tool(Protocol):
    name: str

    def run(self, args: dict[str, Any]) -> ToolResult:
        """Run a tool with JSON-like args."""
