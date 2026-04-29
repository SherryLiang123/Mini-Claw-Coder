from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path


VALID_STATUSES = {"pending", "in_progress", "blocked", "done", "failed"}


@dataclass
class TaskNode:
    task_id: str
    objective: str
    status: str = "pending"
    owner_role: str = "planner"
    dependencies: list[str] = field(default_factory=list)
    context_refs: list[str] = field(default_factory=list)
    verification_command: str = ""
    workspace_path: str = ""
    notes: str = ""
    background_run_ids: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.status not in VALID_STATUSES:
            raise ValueError(f"Invalid task status: {self.status}")


@dataclass
class TaskGraph:
    nodes: dict[str, TaskNode] = field(default_factory=dict)

    def add(self, node: TaskNode) -> None:
        if node.task_id in self.nodes:
            raise ValueError(f"Duplicate task_id: {node.task_id}")
        self.nodes[node.task_id] = node

    def set_status(self, task_id: str, status: str) -> None:
        if status not in VALID_STATUSES:
            raise ValueError(f"Invalid task status: {status}")
        self.nodes[task_id].status = status

    def attach_workspace(self, task_id: str, workspace_path: str) -> None:
        self.nodes[task_id].workspace_path = workspace_path

    def attach_background_run(self, task_id: str, run_id: str) -> None:
        node = self.nodes[task_id]
        if run_id not in node.background_run_ids:
            node.background_run_ids.append(run_id)

    def append_note(
        self,
        task_id: str,
        note: str,
        created_at: str | None = None,
    ) -> None:
        cleaned = note.strip()
        if not cleaned:
            raise ValueError("Task note cannot be empty.")
        stamp = created_at or datetime.now(timezone.utc).isoformat()
        entry = f"[{stamp}] {cleaned}"
        node = self.nodes[task_id]
        node.notes = f"{node.notes.rstrip()}\n{entry}".strip() if node.notes.strip() else entry

    def ready(self) -> list[TaskNode]:
        ready_nodes: list[TaskNode] = []
        for node in self.nodes.values():
            if node.status != "pending":
                continue
            if all(self.nodes[dep].status == "done" for dep in node.dependencies):
                ready_nodes.append(node)
        return sorted(ready_nodes, key=lambda item: item.task_id)

    def to_dict(self) -> dict[str, object]:
        return {"nodes": [asdict(node) for node in self.nodes.values()]}

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "TaskGraph":
        graph = cls()
        for item in data.get("nodes", []):
            if not isinstance(item, dict):
                raise ValueError("Task graph node must be an object.")
            graph.add(TaskNode(**item))
        return graph

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=True, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "TaskGraph":
        if not path.exists():
            return cls()
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))
