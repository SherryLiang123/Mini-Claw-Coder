from __future__ import annotations

import shlex
import subprocess
from pathlib import Path
from typing import Any

from mini_claw.context.workspace import ensure_inside_workspace
from mini_claw.memory.store import MemoryStore
from mini_claw.safety.snapshot import FileSnapshot
from mini_claw.tools.base import ToolResult


class ShellTool:
    name = "shell"

    def __init__(
        self,
        workspace: Path,
        timeout_seconds: int = 30,
        memory: MemoryStore | None = None,
    ) -> None:
        self.workspace = workspace
        self.timeout_seconds = timeout_seconds
        self.memory = memory

    def run(self, args: dict[str, Any]) -> ToolResult:
        command = str(args.get("command", "")).strip()
        if not command:
            return ToolResult(ok=False, output="Missing shell command.")
        try:
            completed = subprocess.run(
                command,
                shell=True,
                cwd=self.workspace,
                text=True,
                capture_output=True,
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            return ToolResult(ok=False, output=f"Command timed out after {self.timeout_seconds}s.")

        output = "\n".join(
            part
            for part in [
                f"$ {command}",
                completed.stdout.strip(),
                completed.stderr.strip(),
                f"exit_code={completed.returncode}",
            ]
            if part
        )
        read_snapshots = self._record_read_snapshots(command, completed.returncode == 0)
        return ToolResult(
            ok=completed.returncode == 0,
            output=output,
            metadata={
                "command": command,
                "exit_code": completed.returncode,
                "stdout_chars": len(completed.stdout or ""),
                "stderr_chars": len(completed.stderr or ""),
                "read_snapshots": read_snapshots,
            },
        )

    def _record_read_snapshots(self, command: str, ok: bool) -> list[dict[str, object]]:
        if not ok or self.memory is None:
            return []
        paths = self._read_paths_from_command(command)
        records: list[dict[str, object]] = []
        for raw_path in paths:
            try:
                target = ensure_inside_workspace(self.workspace, raw_path)
            except ValueError:
                continue
            if target.is_dir():
                continue
            rel = str(target.relative_to(self.workspace.resolve())).replace("\\", "/")
            snapshot = FileSnapshot.capture(self.workspace, target)
            record = self.memory.record_read_snapshot(
                rel,
                snapshot,
                source=f"shell:{self._command_verb(command)}",
            )
            records.append(
                {
                    "path": record["path"],
                    "exists": record["exists"],
                    "sha256": record["sha256"],
                }
            )
        return records

    def _read_paths_from_command(self, command: str) -> list[str]:
        try:
            tokens = shlex.split(command, posix=False)
        except ValueError:
            return []
        if not tokens:
            return []
        verb = tokens[0].lower()
        if verb in {"cat", "type", "gc", "get-content"}:
            return self._positional_file_args(tokens[1:])
        if verb == "powershell" and "get-content" in command.lower():
            lower_tokens = [token.lower() for token in tokens]
            for marker in ("get-content", "gc"):
                if marker in lower_tokens:
                    return self._positional_file_args(tokens[lower_tokens.index(marker) + 1 :])
        return []

    def _positional_file_args(self, tokens: list[str]) -> list[str]:
        paths: list[str] = []
        skip_next = False
        for index, token in enumerate(tokens):
            if skip_next:
                skip_next = False
                continue
            cleaned = token.strip().strip("\"'")
            lower = cleaned.lower()
            if lower in {"-path", "-literalpath"}:
                if index + 1 < len(tokens):
                    paths.append(tokens[index + 1].strip().strip("\"'"))
                    skip_next = True
                continue
            if cleaned.startswith("-"):
                continue
            paths.append(cleaned)
        return paths

    def _command_verb(self, command: str) -> str:
        return command.strip().split(maxsplit=1)[0].lower() if command.strip() else "shell"
