from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from mini_claw.agent.state import ToolCall
from mini_claw.skills.loader import Skill


@dataclass(frozen=True)
class GuardrailDecision:
    ok: bool
    reason: str = ""
    active_skills: list[str] = field(default_factory=list)


class SkillGuardrail:
    """Enforce hard constraints declared by relevant Skill contracts."""

    def __init__(self, skills: list[Skill], relevance_threshold: int = 1) -> None:
        self.skills = skills
        self.relevance_threshold = relevance_threshold

    def validate(self, task: str, call: ToolCall) -> GuardrailDecision:
        active = [
            skill
            for skill in self.skills
            if skill.relevance_score(task) >= self.relevance_threshold
        ]
        if not active:
            return GuardrailDecision(ok=True)

        active_names = [skill.name for skill in active]
        allowed_tools = {
            tool.lower()
            for skill in active
            for tool in skill.contract.allowed_tools
            if tool.strip()
        }
        if allowed_tools and call.tool.lower() not in allowed_tools:
            return GuardrailDecision(
                ok=False,
                reason=(
                    f"tool '{call.tool}' is not allowed by active skill contracts "
                    f"{active_names}; allowed_tools={sorted(allowed_tools)}"
                ),
                active_skills=active_names,
            )

        forbidden_paths = [
            path
            for skill in active
            for path in skill.contract.forbidden_paths
            if path.strip()
        ]
        forbidden_hit = _find_forbidden_path(call.args, forbidden_paths)
        if forbidden_hit:
            return GuardrailDecision(
                ok=False,
                reason=(
                    f"tool call references forbidden path '{forbidden_hit}' from "
                    f"active skill contracts {active_names}"
                ),
                active_skills=active_names,
            )

        return GuardrailDecision(ok=True, active_skills=active_names)


def _find_forbidden_path(value: Any, forbidden_paths: list[str]) -> str:
    if not forbidden_paths:
        return ""
    if isinstance(value, dict):
        for item in value.values():
            hit = _find_forbidden_path(item, forbidden_paths)
            if hit:
                return hit
        return ""
    if isinstance(value, list):
        for item in value:
            hit = _find_forbidden_path(item, forbidden_paths)
            if hit:
                return hit
        return ""
    if not isinstance(value, str):
        return ""

    normalized = value.replace("\\", "/").lower()
    for raw_path in forbidden_paths:
        forbidden = raw_path.replace("\\", "/").lower().strip("/")
        if not forbidden:
            continue
        if forbidden in normalized:
            return raw_path
    return ""

