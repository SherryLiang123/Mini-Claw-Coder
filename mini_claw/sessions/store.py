from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from mini_claw.agent.state import AgentResult


@dataclass(frozen=True)
class SessionRecord:
    session_id: str
    name: str
    workspace: str
    created_at: str
    updated_at: str
    turn_count: int = 0
    last_turn_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "name": self.name,
            "workspace": self.workspace,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "turn_count": self.turn_count,
            "last_turn_id": self.last_turn_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SessionRecord":
        return cls(
            session_id=str(data.get("session_id", "")),
            name=str(data.get("name", "")),
            workspace=str(data.get("workspace", "")),
            created_at=str(data.get("created_at", "")),
            updated_at=str(data.get("updated_at", "")),
            turn_count=int(data.get("turn_count", 0) or 0),
            last_turn_id=str(data.get("last_turn_id", "")),
        )


@dataclass(frozen=True)
class SessionTurnRecord:
    session_id: str
    turn_id: str
    turn_index: int
    task: str
    status: str
    started_at: str
    finished_at: str = ""
    success: bool = False
    final_answer: str = ""
    modified_files: list[str] | None = None
    failure_report: dict[str, Any] | None = None
    trace_path: str = ""
    trace_event_count: int = 0
    execution_mode: str = "main"
    execution_workspace: str = ""
    execution_task_id: str = ""
    merge_back_status: str = ""
    merge_back_output: str = ""
    merge_back_files: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "turn_index": self.turn_index,
            "task": self.task,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "success": self.success,
            "final_answer": self.final_answer,
            "modified_files": list(self.modified_files or []),
            "failure_report": self.failure_report,
            "trace_path": self.trace_path,
            "trace_event_count": self.trace_event_count,
            "execution_mode": self.execution_mode,
            "execution_workspace": self.execution_workspace,
            "execution_task_id": self.execution_task_id,
            "merge_back_status": self.merge_back_status,
            "merge_back_output": self.merge_back_output,
            "merge_back_files": list(self.merge_back_files or []),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SessionTurnRecord":
        return cls(
            session_id=str(data.get("session_id", "")),
            turn_id=str(data.get("turn_id", "")),
            turn_index=int(data.get("turn_index", 0) or 0),
            task=str(data.get("task", "")),
            status=str(data.get("status", "")),
            started_at=str(data.get("started_at", "")),
            finished_at=str(data.get("finished_at", "")),
            success=bool(data.get("success", False)),
            final_answer=str(data.get("final_answer", "")),
            modified_files=[str(item) for item in data.get("modified_files", [])],
            failure_report=data.get("failure_report")
            if isinstance(data.get("failure_report"), dict)
            else None,
            trace_path=str(data.get("trace_path", "")),
            trace_event_count=int(data.get("trace_event_count", 0) or 0),
            execution_mode=str(data.get("execution_mode", "main") or "main"),
            execution_workspace=str(data.get("execution_workspace", "")),
            execution_task_id=str(data.get("execution_task_id", "")),
            merge_back_status=str(data.get("merge_back_status", "")),
            merge_back_output=str(data.get("merge_back_output", "")),
            merge_back_files=[str(item) for item in data.get("merge_back_files", [])],
        )


class SessionManager:
    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.resolve()
        self.root = self.workspace / ".mini_claw" / "sessions"
        self.trace_path = self.workspace / ".mini_claw" / "memory" / "task_trace.jsonl"

    def create(self, name: str = "") -> SessionRecord:
        created_at = _utcnow()
        session_id = f"session-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}-{uuid4().hex[:8]}"
        record = SessionRecord(
            session_id=session_id,
            name=name.strip(),
            workspace=str(self.workspace),
            created_at=created_at,
            updated_at=created_at,
            turn_count=0,
            last_turn_id="",
        )
        self._session_dir(session_id).mkdir(parents=True, exist_ok=True)
        self._turns_dir(session_id).mkdir(parents=True, exist_ok=True)
        self._traces_dir(session_id).mkdir(parents=True, exist_ok=True)
        self._write_json(self._session_path(session_id), record.to_dict())
        return record

    def list_sessions(self, limit: int = 20) -> list[SessionRecord]:
        if not self.root.exists():
            return []
        sessions: list[SessionRecord] = []
        for path in sorted(self.root.glob("*/session.json"), reverse=True):
            sessions.append(SessionRecord.from_dict(self._read_json(path)))
            if len(sessions) >= limit:
                break
        return sessions

    def read_session(self, ref: str) -> SessionRecord:
        ref = ref.strip()
        if not ref:
            raise ValueError("Session reference cannot be empty.")
        if ref.isdigit():
            index = int(ref)
            records = self.list_sessions(limit=max(index, 20))
            if index < 1 or index > len(records):
                raise ValueError(f"Session index out of range: {ref}")
            return records[index - 1]
        path = self._session_path(ref)
        if not path.exists():
            raise ValueError(f"Unknown session: {ref}")
        return SessionRecord.from_dict(self._read_json(path))

    def list_turns(self, session_ref: str, limit: int = 20) -> list[SessionTurnRecord]:
        session = self.read_session(session_ref)
        turns_dir = self._turns_dir(session.session_id)
        turns: list[SessionTurnRecord] = []
        if not turns_dir.exists():
            return turns
        for path in sorted(turns_dir.glob("*.json"), reverse=True):
            turns.append(SessionTurnRecord.from_dict(self._read_json(path)))
            if len(turns) >= limit:
                break
        return turns

    def recent_modified_paths(
        self,
        session_ref: str,
        *,
        max_turns: int = 3,
        limit: int = 10,
    ) -> list[str]:
        session = self.read_session(session_ref)
        paths: list[str] = []
        seen: set[str] = set()
        for turn in self.list_turns(session.session_id, limit=max(max_turns, 1)):
            if turn.status != "completed":
                continue
            for raw_path in list(turn.merge_back_files or []) + list(turn.modified_files or []):
                normalized = str(raw_path).replace("\\", "/").strip()
                dedupe_key = normalized.rstrip("/") or normalized
                if not normalized or dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                paths.append(normalized)
                if len(paths) >= limit:
                    return paths
        return paths

    def begin_turn(self, session_ref: str, task: str) -> SessionTurnRecord:
        session = self.read_session(session_ref)
        turn_index = session.turn_count + 1
        turn_id = f"turn-{turn_index:03d}-{uuid4().hex[:8]}"
        record = SessionTurnRecord(
            session_id=session.session_id,
            turn_id=turn_id,
            turn_index=turn_index,
            task=task.strip(),
            status="running",
            started_at=_utcnow(),
            modified_files=[],
        )
        self._write_json(self._turn_path(session.session_id, turn_id), record.to_dict())
        self._write_session(
            SessionRecord(
                session_id=session.session_id,
                name=session.name,
                workspace=session.workspace,
                created_at=session.created_at,
                updated_at=record.started_at,
                turn_count=turn_index,
                last_turn_id=turn_id,
            )
        )
        return record

    def complete_turn(
        self,
        session_ref: str,
        turn_id: str,
        *,
        result: AgentResult,
        trace_lines: list[str],
        execution_mode: str = "main",
        execution_workspace: str = "",
        execution_task_id: str = "",
        merge_back_status: str = "",
        merge_back_output: str = "",
        merge_back_files: list[str] | None = None,
    ) -> SessionTurnRecord:
        session = self.read_session(session_ref)
        turn = self.read_turn(session.session_id, turn_id)
        trace_path = self._trace_slice_path(session.session_id, turn_id)
        trace_path.parent.mkdir(parents=True, exist_ok=True)
        trace_path.write_text("".join(trace_lines), encoding="utf-8")
        updated = SessionTurnRecord(
            session_id=turn.session_id,
            turn_id=turn.turn_id,
            turn_index=turn.turn_index,
            task=turn.task,
            status="completed",
            started_at=turn.started_at,
            finished_at=_utcnow(),
            success=result.success,
            final_answer=result.final_answer,
            modified_files=list(result.modified_files),
            failure_report=result.failure_report,
            trace_path=str(trace_path),
            trace_event_count=len(trace_lines),
            execution_mode=execution_mode,
            execution_workspace=execution_workspace,
            execution_task_id=execution_task_id,
            merge_back_status=merge_back_status,
            merge_back_output=merge_back_output,
            merge_back_files=list(merge_back_files or []),
        )
        self._write_json(self._turn_path(session.session_id, turn_id), updated.to_dict())
        self._write_session(
            SessionRecord(
                session_id=session.session_id,
                name=session.name,
                workspace=session.workspace,
                created_at=session.created_at,
                updated_at=updated.finished_at,
                turn_count=session.turn_count,
                last_turn_id=updated.turn_id,
            )
        )
        return updated

    def read_turn(self, session_ref: str, turn_ref: str) -> SessionTurnRecord:
        session = self.read_session(session_ref)
        turns = self.list_turns(session.session_id, limit=max(20, session.turn_count))
        if turn_ref.isdigit():
            index = int(turn_ref)
            if index < 1 or index > len(turns):
                raise ValueError(f"Session turn index out of range: {turn_ref}")
            return turns[index - 1]
        path = self._turn_path(session.session_id, turn_ref)
        if not path.exists():
            raise ValueError(f"Unknown session turn: {turn_ref}")
        return SessionTurnRecord.from_dict(self._read_json(path))

    def build_context(
        self,
        session_ref: str,
        *,
        max_turns: int = 3,
        max_chars: int = 4_000,
    ) -> str:
        session = self.read_session(session_ref)
        turns = [
            turn
            for turn in reversed(self.list_turns(session.session_id, limit=max_turns))
            if turn.status == "completed"
        ]
        if not turns:
            return (
                f"Session {session.session_id}\n"
                f"name: {session.name or '(unnamed)'}\n"
                "No previous turns yet."
            )
        lines = [
            f"Session {session.session_id}",
            f"name: {session.name or '(unnamed)'}",
            f"previous_turns: {session.turn_count}",
            "",
        ]
        for turn in turns:
            status = "success" if turn.success else "failed"
            lines.extend(
                [
                    f"Turn {turn.turn_index} [{status}]",
                    f"task: {turn.task}",
                    "modified_paths: "
                    + (", ".join(turn.modified_files or []) if turn.modified_files else "(none)"),
                    "final: " + _single_line(turn.final_answer, 320),
                ]
            )
            if turn.execution_mode != "main":
                lines.append(f"execution_mode: {turn.execution_mode}")
                if turn.execution_task_id:
                    lines.append(f"execution_task_id: {turn.execution_task_id}")
                if turn.execution_workspace:
                    lines.append(f"execution_workspace: {turn.execution_workspace}")
            if turn.merge_back_status:
                lines.append(f"merge_back_status: {turn.merge_back_status}")
                if turn.merge_back_files:
                    lines.append("merge_back_files: " + ", ".join(turn.merge_back_files))
                if turn.merge_back_output:
                    lines.append("merge_back_output: " + _single_line(turn.merge_back_output, 240))
            if turn.failure_report:
                lines.append(
                    "failure_root_cause: "
                    + str(turn.failure_report.get("root_cause", "") or "(none)")
                )
            lines.append("")
        content = "\n".join(lines).strip()
        if len(content) <= max_chars:
            return content
        return content[: max_chars - 40] + "\n...[session context truncated]..."

    def trace_line_count(self) -> int:
        if not self.trace_path.exists():
            return 0
        return len(self.trace_path.read_text(encoding="utf-8").splitlines())

    def read_trace_slice(self, start_line: int) -> list[str]:
        if not self.trace_path.exists():
            return []
        rows = self.trace_path.read_text(encoding="utf-8").splitlines(keepends=True)
        return rows[start_line:]

    def _write_session(self, record: SessionRecord) -> None:
        self._write_json(self._session_path(record.session_id), record.to_dict())

    def _session_dir(self, session_id: str) -> Path:
        return self.root / session_id

    def _session_path(self, session_id: str) -> Path:
        return self._session_dir(session_id) / "session.json"

    def _turns_dir(self, session_id: str) -> Path:
        return self._session_dir(session_id) / "turns"

    def _traces_dir(self, session_id: str) -> Path:
        return self._session_dir(session_id) / "traces"

    def _turn_path(self, session_id: str, turn_id: str) -> Path:
        return self._turns_dir(session_id) / f"{turn_id}.json"

    def _trace_slice_path(self, session_id: str, turn_id: str) -> Path:
        return self._traces_dir(session_id) / f"{turn_id}.jsonl"

    def _read_json(self, path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(path.suffix + ".tmp")
        temp_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
        temp_path.replace(path)


def _single_line(text: str, max_chars: int) -> str:
    compact = " ".join(text.split())
    if not compact:
        return "(none)"
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 3] + "..."


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()
