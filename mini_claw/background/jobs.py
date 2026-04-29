from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from mini_claw.memory.store import MemoryStore
from mini_claw.tracing.events import RuntimeEvent


VALID_BACKGROUND_STATUSES = {"running", "succeeded", "failed"}


@dataclass(frozen=True)
class BackgroundRunRecord:
    run_id: str
    command: str
    workspace: str
    status: str
    created_at: str
    label: str = ""
    task_id: str = ""
    started_at: str = ""
    finished_at: str = ""
    exit_code: int | None = None
    runner_pid: int | None = None
    stdout_path: str = ""
    stderr_path: str = ""
    trace_path: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "command": self.command,
            "workspace": self.workspace,
            "status": self.status,
            "created_at": self.created_at,
            "label": self.label,
            "task_id": self.task_id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "exit_code": self.exit_code,
            "runner_pid": self.runner_pid,
            "stdout_path": self.stdout_path,
            "stderr_path": self.stderr_path,
            "trace_path": self.trace_path,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BackgroundRunRecord":
        status = str(data.get("status", "running"))
        if status not in VALID_BACKGROUND_STATUSES:
            raise ValueError(f"Invalid background status: {status}")
        exit_code = data.get("exit_code")
        runner_pid = data.get("runner_pid")
        return cls(
            run_id=str(data.get("run_id", "")),
            command=str(data.get("command", "")),
            workspace=str(data.get("workspace", "")),
            status=status,
            created_at=str(data.get("created_at", "")),
            label=str(data.get("label", "")),
            task_id=str(data.get("task_id", "")),
            started_at=str(data.get("started_at", "")),
            finished_at=str(data.get("finished_at", "")),
            exit_code=int(exit_code) if isinstance(exit_code, int) else None,
            runner_pid=int(runner_pid) if isinstance(runner_pid, int) else None,
            stdout_path=str(data.get("stdout_path", "")),
            stderr_path=str(data.get("stderr_path", "")),
            trace_path=str(data.get("trace_path", "")),
            error=str(data.get("error", "")),
        )


class BackgroundRunManager:
    def __init__(
        self,
        workspace: Path,
        memory: MemoryStore | None = None,
    ) -> None:
        self.workspace = workspace.resolve()
        self.memory = memory
        self.root = self.workspace / ".mini_claw" / "background"
        self.runs_dir = self.root / "runs"
        self.logs_dir = self.root / "logs"
        self.trace_path = (
            str(memory.trace_path)
            if memory is not None
            else str(self.workspace / ".mini_claw" / "memory" / "task_trace.jsonl")
        )

    def start(
        self,
        command: str,
        *,
        label: str = "",
        task_id: str = "",
    ) -> BackgroundRunRecord:
        cleaned = command.strip()
        if not cleaned:
            raise ValueError("Background command cannot be empty.")

        created_at = _utcnow()
        run_id = f"bg-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}-{uuid4().hex[:8]}"
        record_path = self._record_path(run_id)
        stdout_path = self.logs_dir / f"{run_id}.stdout.log"
        stderr_path = self.logs_dir / f"{run_id}.stderr.log"

        record = BackgroundRunRecord(
            run_id=run_id,
            command=cleaned,
            workspace=str(self.workspace),
            status="running",
            created_at=created_at,
            label=label.strip(),
            task_id=task_id.strip(),
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
            trace_path=self.trace_path,
        )
        self._write_record(record_path, record.to_dict())

        runner = Path(__file__).with_name("runner.py")
        runner_command = [
            sys.executable,
            str(runner),
            "--record",
            str(record_path),
            "--stdout",
            str(stdout_path),
            "--stderr",
            str(stderr_path),
            "--cwd",
            str(self.workspace),
            "--command",
            cleaned,
            "--trace-path",
            self.trace_path,
        ]
        runner_pid = self._spawn_runner(runner_command)

        payload = self._read_json(record_path)
        if runner_pid is not None:
            payload["runner_pid"] = runner_pid
        self._write_record(record_path, payload)

        if self.memory is not None:
            self.memory.append_event(
                RuntimeEvent(
                    "background_run_requested",
                    {
                        "run_id": run_id,
                        "command": cleaned,
                        "label": label.strip(),
                        "task_id": task_id.strip(),
                        "runner_pid": runner_pid,
                    },
                )
            )

        return self.read_run(run_id)

    def list_runs(
        self,
        *,
        limit: int = 20,
        status_filter: str = "",
    ) -> list[BackgroundRunRecord]:
        records: list[BackgroundRunRecord] = []
        if not self.runs_dir.exists():
            return records
        for path in sorted(self.runs_dir.glob("*.json"), reverse=True):
            record = BackgroundRunRecord.from_dict(self._read_json(path))
            if status_filter and record.status != status_filter:
                continue
            records.append(record)
            if len(records) >= limit:
                break
        return records

    def read_run(self, ref: str) -> BackgroundRunRecord:
        ref = ref.strip()
        if not ref:
            raise ValueError("Background run reference cannot be empty.")
        if ref.isdigit():
            index = int(ref)
            records = self.list_runs(limit=max(index, 20))
            if index < 1 or index > len(records):
                raise ValueError(f"Background run index out of range: {ref}")
            return records[index - 1]
        path = self._record_path(ref)
        if not path.exists():
            raise ValueError(f"Unknown background run: {ref}")
        return BackgroundRunRecord.from_dict(self._read_json(path))

    def wait(
        self,
        ref: str,
        *,
        timeout_seconds: float = 30.0,
        poll_interval: float = 0.2,
    ) -> BackgroundRunRecord:
        deadline = time.monotonic() + max(timeout_seconds, 0.0)
        while True:
            record = self.read_run(ref)
            if record.status != "running":
                time.sleep(0.1)
                return record
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"Background run {record.run_id} did not finish within {timeout_seconds}s."
                )
            time.sleep(max(poll_interval, 0.05))

    def output_tail(
        self,
        ref: str,
        *,
        max_chars: int = 2_000,
    ) -> dict[str, str]:
        record = self.read_run(ref)
        return {
            "stdout": self._tail_text(Path(record.stdout_path), max_chars=max_chars),
            "stderr": self._tail_text(Path(record.stderr_path), max_chars=max_chars),
        }

    def _record_path(self, run_id: str) -> Path:
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        return self.runs_dir / f"{run_id}.json"

    def _tail_text(self, path: Path, *, max_chars: int) -> str:
        if not path.exists():
            return ""
        content = path.read_text(encoding="utf-8")
        if len(content) <= max_chars:
            return content
        return content[-max_chars:]

    def _read_json(self, path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    def _write_record(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(path.suffix + ".tmp")
        temp_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
        temp_path.replace(path)

    def _detach_kwargs(self) -> dict[str, Any]:
        if os.name == "nt":
            flags = 0
            flags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            flags |= getattr(subprocess, "DETACHED_PROCESS", 0)
            return {"creationflags": flags}
        return {"start_new_session": True}

    def _spawn_runner(self, command: list[str]) -> int | None:
        if os.name == "nt":
            commandline = subprocess.list2cmdline(command)
            completed = subprocess.run(
                f'start "" /b {commandline}',
                cwd=self.workspace,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
                shell=True,
            )
            if completed.returncode != 0:
                raise ValueError(
                    f"Failed to start background runner for command: {' '.join(command)}"
                )
            return None
        process = subprocess.Popen(
            command,
            cwd=self.workspace,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **self._detach_kwargs(),
        )
        return process.pid


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()
