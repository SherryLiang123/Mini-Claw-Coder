from __future__ import annotations

from pathlib import Path

from mini_claw.memory.store import MemoryStore
from mini_claw.tools.base import Tool
from mini_claw.tools.bash import BashTool
from mini_claw.tools.patch import PatchTool
from mini_claw.tools.repo_tools import (
    EditTool,
    GlobTool,
    GrepTool,
    ListFilesTool,
    MkdirTool,
    ReadTool,
    WriteTool,
)
from mini_claw.tools.shell import ShellTool
from mini_claw.tools.tool_output_lookup import ToolOutputLookupTool


def build_runtime_tools(
    *,
    workspace: Path,
    memory: MemoryStore,
    timeout_seconds: int,
    dry_run: bool = False,
    require_read_snapshot: bool = False,
) -> dict[str, Tool]:
    return {
        "ls": ListFilesTool(workspace),
        "glob": GlobTool(workspace),
        "grep": GrepTool(workspace),
        "read": ReadTool(workspace, memory=memory),
        "mkdir": MkdirTool(workspace),
        "edit": EditTool(
            workspace,
            memory=memory,
            dry_run=dry_run,
            require_read_snapshot=require_read_snapshot,
        ),
        "write": WriteTool(
            workspace,
            memory=memory,
            dry_run=dry_run,
            require_read_snapshot=require_read_snapshot,
        ),
        "bash": BashTool(workspace, timeout_seconds=timeout_seconds),
        "shell": ShellTool(
            workspace,
            timeout_seconds=timeout_seconds,
            memory=memory,
        ),
        "apply_patch": PatchTool(
            workspace,
            dry_run=dry_run,
            memory=memory,
            require_read_snapshot=require_read_snapshot,
        ),
        "tool_output_lookup": ToolOutputLookupTool(memory),
    }
