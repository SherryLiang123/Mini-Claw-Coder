from __future__ import annotations

from dataclasses import dataclass

from mini_claw.agent.state import TaskState
from mini_claw.config import ModelConfig


@dataclass(frozen=True)
class RouteDecision:
    role: str
    model: str
    reason: str
    signals: dict[str, object]
    guidance: str


class ModelRouter:
    """Simple policy router that can be replaced by learned routing later."""

    def __init__(self, config: ModelConfig, policy: str = "signal-aware") -> None:
        if policy not in {"basic", "signal-aware"}:
            raise ValueError(f"Unsupported routing policy: {policy}")
        self.config = config
        self.policy = policy

    def select(self, state: TaskState) -> RouteDecision:
        signals = self._signals(state)
        role, reason = self._role_and_reason(state)
        return RouteDecision(
            role=role,
            model=self.select_model(role, state),
            reason=reason,
            signals=signals,
            guidance=self.role_guidance(role),
        )

    def select_role(self, state: TaskState) -> str:
        return self.select(state).role

    def select_model(self, role: str, state: TaskState) -> str:
        if state.failure_count >= self.config.max_retries:
            return self.config.planner_model
        if role == "planner":
            return self.config.planner_model
        if role == "reviewer":
            return self.config.reviewer_model
        if role == "summarizer":
            return self.config.summarizer_model
        return self.config.coder_model

    def role_guidance(self, role: str) -> str:
        if role == "planner":
            return "Front-load discovery, identify the smallest next action, and avoid speculative edits."
        if role == "reviewer":
            return "Reassess recent evidence, avoid repeating failed broad inspection, and verify the next move carefully."
        if role == "summarizer":
            return "Restate compacted history, preserve key evidence, and tee up the next minimal action without restarting from scratch."
        return "Continue focused execution and prefer the smallest concrete action that advances the task."

    def _role_and_reason(self, state: TaskState) -> tuple[str, str]:
        if self.policy == "basic":
            if state.failure_count > 0:
                return "reviewer", "recent_failure"
            if not state.steps:
                return "planner", "initial_planning"
            return "coder", "continue_execution"
        if state.pending_lookup is not None:
            return "reviewer", "pending_tool_output_lookup"
        if state.failure_count > 0:
            return "reviewer", "recent_failure"
        if not state.steps:
            return "planner", "initial_planning"
        if state.compacted_steps > state.last_summarized_compacted_steps:
            return "summarizer", "new_context_compaction"
        return "coder", "continue_execution"

    def _signals(self, state: TaskState) -> dict[str, object]:
        return {
            "failure_count": state.failure_count,
            "step_count": len(state.steps),
            "pending_lookup": state.pending_lookup is not None,
            "compaction_count": state.compaction_count,
            "compacted_steps": state.compacted_steps,
            "last_context_compressed": state.last_context_compressed,
            "last_context_used_chars": state.last_context_used_chars,
            "last_context_max_chars": state.last_context_max_chars,
        }
