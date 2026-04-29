from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class ACPMessage:
    type: str
    sender: str
    receiver: str
    content: dict[str, Any]
    context_refs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class HandoffPacket:
    source_role: str
    target_role: str
    task: str
    constraints: list[str]
    context_refs: list[str]

    def to_acp(self) -> ACPMessage:
        return ACPMessage(
            type="handoff",
            sender=self.source_role,
            receiver=self.target_role,
            content={"task": self.task, "constraints": self.constraints},
            context_refs=self.context_refs,
        )

