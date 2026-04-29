from __future__ import annotations

from dataclasses import dataclass

from mini_claw.agent.state import PendingToolOutputLookup, TaskState, ToolCall
from mini_claw.tools.base import ToolOutputHandle, ToolResult


@dataclass(frozen=True)
class LookupPolicyDecision:
    ok: bool
    reason: str = ""
    pending_output_id: str = ""
    source_tool: str = ""


class ToolOutputLookupPolicy:
    """Keep truncated tool evidence out of the main context while preserving access."""

    def validate(self, state: TaskState, call: ToolCall) -> LookupPolicyDecision:
        pending = state.pending_lookup
        if pending is None:
            return LookupPolicyDecision(ok=True)
        if call.tool == "tool_output_lookup":
            return LookupPolicyDecision(
                ok=True,
                pending_output_id=pending.output_id,
                source_tool=pending.source_tool,
            )
        if pending.source_tool not in {"shell", "bash"} or call.tool != pending.source_tool:
            return LookupPolicyDecision(
                ok=True,
                pending_output_id=pending.output_id,
                source_tool=pending.source_tool,
            )
        if not self._requires_lookup(call, pending):
            return LookupPolicyDecision(
                ok=True,
                pending_output_id=pending.output_id,
                source_tool=pending.source_tool,
            )
        return LookupPolicyDecision(
            ok=False,
            reason=(
                "tool_output_lookup required before another shell/bash inspection step. "
                f"Pending truncated output id={pending.output_id} from {pending.source_tool}. "
                "Use tool_output_lookup with ref='latest_truncated' and focus='auto' first, "
                "then refine with intent='error' or intent='path' / exclude_queries if needed, "
                f"or target ref='{pending.output_id}' directly. "
                f"Hint: {pending.lookup_hint}"
            ),
            pending_output_id=pending.output_id,
            source_tool=pending.source_tool,
        )

    def observe_result(
        self,
        state: TaskState,
        call: ToolCall,
        result: ToolResult,
        output_handle: ToolOutputHandle,
    ) -> None:
        if call.tool == "tool_output_lookup":
            self._complete_lookup(state, result)
            return
        if output_handle.truncated or output_handle.store_truncated:
            state.pending_lookup = PendingToolOutputLookup(
                output_id=output_handle.output_id,
                source_tool=call.tool,
                source_args=dict(call.args),
                lookup_hint=output_handle.lookup_hint,
            )
            return
        if state.pending_lookup is not None:
            state.pending_lookup = None

    def _complete_lookup(self, state: TaskState, result: ToolResult) -> None:
        pending = state.pending_lookup
        if pending is None or not result.ok:
            return
        source_output_id = str(result.metadata.get("source_output_id", "")).strip()
        if source_output_id == pending.output_id:
            state.pending_lookup = None

    def _requires_lookup(
        self,
        call: ToolCall,
        pending: PendingToolOutputLookup,
    ) -> bool:
        command = str(call.args.get("command", "")).strip().lower()
        source_command = str(pending.source_args.get("command", "")).strip().lower()
        if not command:
            return False
        if command == source_command:
            return True
        if pending.source_tool == "bash":
            tokens = (
                "pytest",
                "python -m unittest",
                "git diff",
                "git show",
                "git status",
                "npm test",
                "cargo test",
                "go test",
            )
            return any(token in command for token in tokens)
        contains_tokens = (
            "get-content",
            "cat ",
            "type ",
            "more ",
            "rg ",
            "grep ",
            "findstr ",
            "select-string",
            "git diff",
            "git show",
            "git status",
        )
        if any(token in command for token in contains_tokens):
            return True
        return command == "ls" or command.startswith("ls ") or command == "dir" or command.startswith("dir ")
