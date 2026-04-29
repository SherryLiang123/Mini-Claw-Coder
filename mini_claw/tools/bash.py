from __future__ import annotations

import shlex
import subprocess
from pathlib import Path
from typing import Any

from mini_claw.context.workspace import ensure_inside_workspace
from mini_claw.tools.base import ToolResult


BLOCKED_INTERACTIVE_COMMANDS = {
    "vim",
    "vi",
    "nano",
    "less",
    "more",
    "top",
    "htop",
    "watch",
    "tmux",
    "screen",
}
BLOCKED_NETWORK_COMMANDS = {
    "curl",
    "wget",
    "ssh",
    "scp",
    "sftp",
    "ftp",
    "invoke-webrequest",
    "invoke-restmethod",
    "iwr",
    "irm",
}
BLOCKED_PRIVILEGED_COMMANDS = {
    "sudo",
    "su",
    "doas",
    "mkfs",
    "fdisk",
    "dd",
    "shutdown",
    "reboot",
    "poweroff",
    "halt",
}
BLOCKED_READ_ONLY_COMMANDS = {
    "ls",
    "dir",
    "cat",
    "type",
    "head",
    "tail",
    "grep",
    "rg",
    "findstr",
    "select-string",
    "get-content",
    "gc",
}
BLOCKED_WORKSPACE_MUTATION_COMMANDS = {
    "mkdir",
    "md",
    "touch",
    "cp",
    "copy",
    "mv",
    "move",
    "ren",
    "rename",
    "del",
    "erase",
    "rd",
    "rmdir",
}
COMMAND_WRAPPERS = {"command", "builtin", "env", "time"}
SEPARATORS = {";", "&", "&&", "||", "|", "(", ")"}


class BashTool:
    name = "bash"

    def __init__(self, workspace: Path, timeout_seconds: int = 30) -> None:
        self.workspace = workspace.resolve()
        self.timeout_seconds = timeout_seconds

    def run(self, args: dict[str, Any]) -> ToolResult:
        command = str(args.get("command", "")).strip()
        directory = str(args.get("directory", ".")).strip() or "."
        if not command:
            return ToolResult(ok=False, output="Missing bash command.")

        try:
            target = ensure_inside_workspace(self.workspace, directory)
        except ValueError as exc:
            return ToolResult(ok=False, output=str(exc))
        if not target.exists() or not target.is_dir():
            return ToolResult(ok=False, output=f"Invalid bash directory: {directory}")

        validation_error = self._validate_command(command)
        if validation_error:
            return ToolResult(ok=False, output=validation_error)

        try:
            completed = subprocess.run(
                command,
                shell=True,
                cwd=target,
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
        return ToolResult(
            ok=completed.returncode == 0,
            output=output,
            metadata={
                "command": command,
                "directory": str(target.relative_to(self.workspace)).replace("\\", "/") or ".",
                "exit_code": completed.returncode,
                "stdout_chars": len(completed.stdout or ""),
                "stderr_chars": len(completed.stderr or ""),
            },
        )

    def _validate_command(self, command: str) -> str:
        normalized = " ".join(command.split()).lower()
        if normalized in {"rm -rf /", "rm -rf /*"}:
            return "COMMAND_BLOCKED: destructive delete commands are not allowed."

        for word in self._command_words(command):
            lower = word.lower()
            if lower == "cd":
                return (
                    "COMMAND_BLOCKED: use the bash directory argument instead of running cd inside "
                    "the command."
                )
            if lower in BLOCKED_INTERACTIVE_COMMANDS:
                return "COMMAND_BLOCKED: interactive commands are not allowed in bash."
            if lower in BLOCKED_NETWORK_COMMANDS:
                return "COMMAND_BLOCKED: network commands are not allowed in bash."
            if lower in BLOCKED_PRIVILEGED_COMMANDS:
                return "COMMAND_BLOCKED: privileged or destructive system commands are blocked."
            if lower in BLOCKED_READ_ONLY_COMMANDS:
                return (
                    "COMMAND_BLOCKED: use ls / glob / grep / read tools for repo inspection "
                    "instead of bash."
                )
            if lower in BLOCKED_WORKSPACE_MUTATION_COMMANDS:
                return (
                    "COMMAND_BLOCKED: use structured workspace mutation tools such as "
                    "mkdir / edit / write instead of bash."
                )
        return ""

    def _command_words(self, command: str) -> list[str]:
        try:
            lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|()")
            lexer.whitespace_split = True
            tokens = list(lexer)
        except ValueError:
            return []

        command_words: list[str] = []
        expecting_command = True
        for token in tokens:
            if token in SEPARATORS:
                expecting_command = True
                continue
            if not expecting_command:
                continue
            if "=" in token and not token.startswith(("'", '"')) and token.split("=", 1)[0].isidentifier():
                continue
            if token.lower() in COMMAND_WRAPPERS:
                continue
            command_words.append(token)
            expecting_command = False
        return command_words
