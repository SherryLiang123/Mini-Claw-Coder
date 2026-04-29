from __future__ import annotations

from typing import Any

from mini_claw.llm.base import ToolSpec


def build_tool_specs(tool_names: list[str]) -> list[ToolSpec]:
    specs: list[ToolSpec] = []
    for name in tool_names:
        specs.append(_SPEC_BUILDERS.get(name, _generic_spec)(name))
    return specs


def _generic_spec(name: str) -> ToolSpec:
    return ToolSpec(
        name=name,
        description=f"Run the {name} tool with JSON object arguments.",
        parameters={
            "type": "object",
            "properties": {},
            "additionalProperties": True,
        },
    )


def _ls_spec(name: str) -> ToolSpec:
    return ToolSpec(
        name=name,
        description="List files or directories inside the workspace.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Workspace-relative path to inspect."},
                "limit": {"type": "integer", "description": "Maximum entries to return."},
                "offset": {"type": "integer", "description": "Pagination offset for directory entries."},
                "include_hidden": {"type": "boolean", "description": "Whether hidden paths may be included."},
            },
            "additionalProperties": False,
        },
    )


def _glob_spec(name: str) -> ToolSpec:
    return ToolSpec(
        name=name,
        description="Find files or directories by glob pattern inside the workspace.",
        parameters={
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Glob pattern such as **/*.py."},
                "path": {"type": "string", "description": "Workspace-relative root directory."},
                "limit": {"type": "integer", "description": "Maximum matches to return."},
                "include_hidden": {"type": "boolean", "description": "Whether hidden paths may be included."},
            },
            "required": ["pattern"],
            "additionalProperties": False,
        },
    )


def _grep_spec(name: str) -> ToolSpec:
    return ToolSpec(
        name=name,
        description="Search workspace text files for a regex or string pattern.",
        parameters={
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Pattern to search for."},
                "path": {"type": "string", "description": "Workspace-relative directory root."},
                "include": {"type": "string", "description": "Optional glob filter such as *.py."},
                "case_sensitive": {"type": "boolean", "description": "Whether the pattern match is case sensitive."},
                "limit": {"type": "integer", "description": "Maximum matches to return."},
            },
            "required": ["pattern"],
            "additionalProperties": False,
        },
    )


def _read_spec(name: str) -> ToolSpec:
    return ToolSpec(
        name=name,
        description="Read a UTF-8 text file with line numbers.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Workspace-relative file path."},
                "start_line": {"type": "integer", "description": "1-based starting line number."},
                "limit": {"type": "integer", "description": "Maximum number of lines to return."},
            },
            "required": ["path"],
            "additionalProperties": False,
        },
        )


def _mkdir_spec(name: str) -> ToolSpec:
    return ToolSpec(
        name=name,
        description="Create a directory inside the workspace.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Workspace-relative directory path."},
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    )


def _edit_spec(name: str) -> ToolSpec:
    return ToolSpec(
        name=name,
        description="Replace one unique text snippet inside an existing file.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Workspace-relative file path."},
                "old": {"type": "string", "description": "Exact old text to replace."},
                "new": {"type": "string", "description": "Replacement text."},
                "expected_sha256": {"type": "string", "description": "Optional read snapshot hash precondition."},
                "allow_overwrite": {"type": "boolean", "description": "Allow overwrite when no read snapshot exists."},
            },
            "required": ["path", "old", "new"],
            "additionalProperties": False,
        },
    )


def _write_spec(name: str) -> ToolSpec:
    return ToolSpec(
        name=name,
        description="Create or overwrite a UTF-8 text file.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Workspace-relative file path."},
                "content": {"type": "string", "description": "Full file content to write."},
                "expected_sha256": {"type": "string", "description": "Optional read snapshot hash precondition."},
                "allow_overwrite": {"type": "boolean", "description": "Allow overwrite when no read snapshot exists."},
            },
            "required": ["path", "content"],
            "additionalProperties": False,
        },
    )


def _bash_spec(name: str) -> ToolSpec:
    return ToolSpec(
        name=name,
        description="Run a non-interactive local command in a workspace directory.",
        parameters={
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command to execute."},
                "directory": {"type": "string", "description": "Workspace-relative working directory."},
            },
            "required": ["command"],
            "additionalProperties": False,
        },
    )


def _shell_spec(name: str) -> ToolSpec:
    return ToolSpec(
        name=name,
        description="Run a legacy shell command in the workspace.",
        parameters={
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command to execute."},
            },
            "required": ["command"],
            "additionalProperties": False,
        },
    )


def _apply_patch_spec(name: str) -> ToolSpec:
    operation_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "op": {
                "type": "string",
                "enum": ["write", "replace", "delete", "mkdir", "rmdir"],
                "description": "Patch operation type.",
            },
            "path": {"type": "string", "description": "Workspace-relative file path."},
            "content": {"type": "string", "description": "Full file content for write operations."},
            "old": {"type": "string", "description": "Existing text for replace operations."},
            "new": {"type": "string", "description": "Replacement text for replace operations."},
        },
        "required": ["op", "path"],
        "additionalProperties": False,
    }
    return ToolSpec(
        name=name,
        description="Apply a structured multi-file patch transaction.",
        parameters={
            "type": "object",
            "properties": {
                "operations": {
                    "type": "array",
                    "description": "Patch operations to execute in order.",
                    "items": operation_schema,
                },
                "verify": {
                    "type": "array",
                    "description": "Optional verification commands to run after patching.",
                    "items": {"type": "string"},
                },
                "rollback_on_verification_failure": {
                    "type": "boolean",
                    "description": "Rollback the patch when verification fails.",
                },
                "verification_timeout_seconds": {
                    "type": "integer",
                    "description": "Timeout for each verification command.",
                },
            },
            "required": ["operations"],
            "additionalProperties": False,
        },
    )


def _tool_output_lookup_spec(name: str) -> ToolSpec:
    return ToolSpec(
        name=name,
        description="Inspect a stored tool result by id, line range, query, or auto-focus hint.",
        parameters={
            "type": "object",
            "properties": {
                "ref": {"type": "string", "description": "Tool output id, numeric index, latest, or latest_truncated."},
                "query": {"type": "string", "description": "Optional substring to center the excerpt around."},
                "line_start": {"type": "integer", "description": "Optional 1-based starting line number."},
                "line_end": {"type": "integer", "description": "Optional 1-based ending line number."},
                "focus": {"type": "string", "description": "Use auto to follow lookup hints."},
                "intent": {"type": "string", "description": "Optional auto-focus intent such as error or path."},
                "hint_index": {"type": "integer", "description": "Specific auto hint index to inspect."},
                "exclude_queries": {
                    "type": "array",
                    "description": "Queries already inspected and should be skipped during auto focus.",
                    "items": {"type": "string"},
                },
                "max_chars": {"type": "integer", "description": "Maximum excerpt length in characters."},
            },
            "required": ["ref"],
            "additionalProperties": False,
        },
    )


_SPEC_BUILDERS = {
    "ls": _ls_spec,
    "glob": _glob_spec,
    "grep": _grep_spec,
    "read": _read_spec,
    "mkdir": _mkdir_spec,
    "edit": _edit_spec,
    "write": _write_spec,
    "bash": _bash_spec,
    "shell": _shell_spec,
    "apply_patch": _apply_patch_spec,
    "tool_output_lookup": _tool_output_lookup_spec,
}
