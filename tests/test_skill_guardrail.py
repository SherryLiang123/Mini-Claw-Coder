import unittest
from pathlib import Path

from mini_claw.agent.guardrails import SkillGuardrail
from mini_claw.agent.state import ToolCall
from mini_claw.skills.loader import Skill, SkillContract


class SkillGuardrailTest(unittest.TestCase):
    def test_blocks_disallowed_tool_for_active_skill(self) -> None:
        skill = Skill(
            name="repo-onboarding",
            body="Inspect repository.",
            path=Path("SKILL.md"),
            contract=SkillContract(
                name="repo-onboarding",
                triggers=["inspect", "repository"],
                allowed_tools=["shell"],
            ),
        )
        guardrail = SkillGuardrail([skill])

        decision = guardrail.validate(
            "inspect this repository",
            ToolCall(tool="apply_patch", args={"operations": []}),
        )

        self.assertFalse(decision.ok)
        self.assertIn("not allowed", decision.reason)

    def test_allows_unrelated_task(self) -> None:
        skill = Skill(
            name="repo-onboarding",
            body="Inspect repository.",
            path=Path("SKILL.md"),
            contract=SkillContract(
                name="repo-onboarding",
                triggers=["inspect", "repository"],
                allowed_tools=["shell"],
            ),
        )
        guardrail = SkillGuardrail([skill])

        decision = guardrail.validate(
            "fix pytest failure",
            ToolCall(tool="apply_patch", args={"operations": []}),
        )

        self.assertTrue(decision.ok)

    def test_blocks_forbidden_path_reference(self) -> None:
        skill = Skill(
            name="repo-onboarding",
            body="Inspect repository.",
            path=Path("SKILL.md"),
            contract=SkillContract(
                name="repo-onboarding",
                triggers=["inspect"],
                allowed_tools=["shell"],
                forbidden_paths=[".mini_claw"],
            ),
        )
        guardrail = SkillGuardrail([skill])

        decision = guardrail.validate(
            "inspect repo",
            ToolCall(tool="shell", args={"command": "Get-Content .mini_claw/memory/task_trace.jsonl"}),
        )

        self.assertFalse(decision.ok)
        self.assertIn(".mini_claw", decision.reason)


if __name__ == "__main__":
    unittest.main()

