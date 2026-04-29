from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
    temp_path.replace(path)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _append_trace(path: Path | None, event: str, payload: dict[str, Any]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"event": event, "payload": payload, "ts": _utcnow()}
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(record, ensure_ascii=True) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(prog="mini_claw.background.runner")
    parser.add_argument("--record", required=True)
    parser.add_argument("--stdout", required=True)
    parser.add_argument("--stderr", required=True)
    parser.add_argument("--cwd", required=True)
    parser.add_argument("--command", required=True)
    parser.add_argument("--trace-path", default="")
    args = parser.parse_args()

    record_path = Path(args.record)
    stdout_path = Path(args.stdout)
    stderr_path = Path(args.stderr)
    cwd = Path(args.cwd)
    trace_path = Path(args.trace_path) if args.trace_path.strip() else None

    payload = _read_json(record_path)
    payload["runner_pid"] = os.getpid()
    payload["started_at"] = _utcnow()
    payload["status"] = "running"
    _write_json(record_path, payload)
    _append_trace(
        trace_path,
        "background_run_started",
        {
            "run_id": payload.get("run_id", ""),
            "command": payload.get("command", ""),
            "task_id": payload.get("task_id", ""),
            "label": payload.get("label", ""),
            "runner_pid": payload.get("runner_pid"),
        },
    )

    try:
        stdout_path.parent.mkdir(parents=True, exist_ok=True)
        stderr_path.parent.mkdir(parents=True, exist_ok=True)
        with stdout_path.open("a", encoding="utf-8", buffering=1) as stdout_file:
            with stderr_path.open("a", encoding="utf-8", buffering=1) as stderr_file:
                stdout_file.write(f"$ {args.command}\n")
                completed = subprocess.run(
                    args.command,
                    shell=True,
                    cwd=cwd,
                    text=True,
                    stdout=stdout_file,
                    stderr=stderr_file,
                )
        payload["status"] = "succeeded" if completed.returncode == 0 else "failed"
        payload["exit_code"] = completed.returncode
    except Exception as exc:  # pragma: no cover - defensive runner path
        payload["status"] = "failed"
        payload["exit_code"] = -1
        payload["error"] = f"{type(exc).__name__}: {exc}"
        with stderr_path.open("a", encoding="utf-8", buffering=1) as stderr_file:
            stderr_file.write(payload["error"] + "\n")
    finally:
        payload["finished_at"] = _utcnow()
        _write_json(record_path, payload)
        _append_trace(
            trace_path,
            "background_run_finished",
            {
                "run_id": payload.get("run_id", ""),
                "task_id": payload.get("task_id", ""),
                "status": payload.get("status", ""),
                "exit_code": payload.get("exit_code"),
                "error": payload.get("error", ""),
            },
        )


if __name__ == "__main__":
    main()
