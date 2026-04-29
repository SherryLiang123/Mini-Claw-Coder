from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from mini_claw.agent.evidence import EvidenceSelection


@dataclass
class ToolCall:
    tool: str
    args: dict[str, Any]


@dataclass
class PendingToolOutputLookup:
    output_id: str
    source_tool: str
    source_args: dict[str, Any]
    lookup_hint: str


@dataclass
class AgentStep:
    index: int
    role: str
    model: str
    thought: str
    action: ToolCall | None = None
    observation: str | None = None
    tool_output_handle: dict[str, Any] | None = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class AgentResult:
    success: bool
    final_answer: str
    steps: list[AgentStep]
    modified_files: list[str] = field(default_factory=list)
    failure_report: dict[str, Any] | None = None


@dataclass
class TaskState:
    task: str
    session_context: str = ""
    steps: list[AgentStep] = field(default_factory=list)
    modified_files: set[str] = field(default_factory=set)
    failure_count: int = 0
    pending_lookup: PendingToolOutputLookup | None = None
    evidence_history: list[EvidenceSelection] = field(default_factory=list)
    compact_summary: str = ""
    compacted_steps: int = 0
    compaction_count: int = 0
    last_summarized_compacted_steps: int = 0
    last_context_compressed: bool = False
    last_context_used_chars: int = 0
    last_context_max_chars: int = 0

    def last_observation(self) -> str:
        for step in reversed(self.steps):
            if step.observation:
                return step.observation
        return ""
