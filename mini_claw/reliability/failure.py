from __future__ import annotations

from dataclasses import asdict, dataclass

from mini_claw.agent.state import TaskState


@dataclass(frozen=True)
class FailureReport:
    root_cause: str
    evidence: str
    suggested_action: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)

    def to_markdown(self) -> str:
        return "\n".join(
            [
                "Failure attribution:",
                f"- root_cause: {self.root_cause}",
                f"- evidence: {self.evidence}",
                f"- suggested_action: {self.suggested_action}",
            ]
        )


def attribute_failure(state: TaskState) -> FailureReport:
    observation = state.last_observation()
    evidence = _recent_observations(state)
    lowered = evidence.lower()

    if "unknown tool" in lowered:
        return FailureReport(
            root_cause="BAD_TOOL_USE",
            evidence=evidence[:500],
            suggested_action="Constrain tool names in the prompt or add a tool-name repair step.",
        )
    if "skill guardrail blocked" in lowered:
        return FailureReport(
            root_cause="SKILL_GUARDRAIL_BLOCKED",
            evidence=evidence[:500],
            suggested_action="Select a compatible skill, revise the action, or adjust the skill contract.",
        )
    if "tool_output_lookup required" in lowered:
        return FailureReport(
            root_cause="TOOL_OUTPUT_LOOKUP_REQUIRED",
            evidence=evidence[:500],
            suggested_action=(
                "Read the stored tool result through tool_output_lookup before retrying "
                "another shell or bash inspection command."
            ),
        )
    if "read_before_write_required" in lowered:
        return FailureReport(
            root_cause="READ_BEFORE_WRITE_REQUIRED",
            evidence=evidence[:500],
            suggested_action="Read the target file first so the runtime can capture a fresh file snapshot.",
        )
    if "overwrite_lock_required" in lowered:
        return FailureReport(
            root_cause="OVERWRITE_LOCK_REQUIRED",
            evidence=evidence[:500],
            suggested_action="Read the file first or use an explicit overwrite lock before rewriting it.",
        )
    if "command_blocked" in lowered:
        return FailureReport(
            root_cause="COMMAND_BLOCKED",
            evidence=evidence[:500],
            suggested_action=(
                "Use the structured repo tools for inspection, or choose a narrower non-interactive "
                "verification command."
            ),
        )
    if "stale_read_snapshot" in lowered:
        return FailureReport(
            root_cause="STALE_READ_SNAPSHOT",
            evidence=evidence[:500],
            suggested_action="Re-read the changed file and rebuild the patch from the latest snapshot.",
        )
    if "no action and no final answer" in lowered or "invalid model output" in lowered:
        return FailureReport(
            root_cause="MODEL_OUTPUT_INVALID",
            evidence=evidence[:500],
            suggested_action="Strengthen JSON output validation and retry with a repair prompt.",
        )
    if "old text not found" in lowered or "hash precondition failed" in lowered:
        return FailureReport(
            root_cause="PATCH_CONFLICT",
            evidence=evidence[:500],
            suggested_action="Re-read the target file, rebuild the patch from the latest snapshot, and retry.",
        )
    if "timed out" in lowered:
        return FailureReport(
            root_cause="COMMAND_TIMEOUT",
            evidence=evidence[:500],
            suggested_action="Use a narrower command, increase timeout, or split verification into smaller steps.",
        )
    if "no module named" in lowered or "modulenotfounderror" in lowered:
        return FailureReport(
            root_cause="DEPENDENCY_OR_ENVIRONMENT",
            evidence=evidence[:500],
            suggested_action="Inspect project setup and dependency files before changing source code.",
        )
    if "test failed" in lowered or "assert" in lowered or "traceback" in lowered:
        return FailureReport(
            root_cause="VERIFICATION_FAILED",
            evidence=evidence[:500],
            suggested_action="Use the failing test output as the next context focus and reduce patch scope.",
        )
    return FailureReport(
        root_cause="UNKNOWN",
        evidence=evidence[:500] or "(no observation)",
        suggested_action="Replay the trace and inspect context_build plus tool_call events.",
    )


def _recent_observations(state: TaskState, limit: int = 6) -> str:
    observations = [
        step.observation
        for step in state.steps[-limit:]
        if step.observation
    ]
    return "\n".join(observations)
