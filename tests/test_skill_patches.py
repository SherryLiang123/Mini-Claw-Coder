import unittest
from pathlib import Path

from mini_claw.skills.patches import (
    build_skill_patch_apply_preview,
    parse_skill_patch_candidate_content,
    render_skill_patch_artifact,
)


class SkillPatchArtifactTest(unittest.TestCase):
    def test_skill_patch_candidate_content_is_parsed_and_rendered(self) -> None:
        candidate = {
            "candidate_id": "skill-1",
            "content": (
                "## Skill Patch Candidate\n"
                "- target_skill: repo-onboarding\n"
                "- skill_path: examples/sample_skill/SKILL.md\n"
                "\n"
                "### Suggested Contract Patch\n"
                "- triggers += lookup\n"
                "\n"
                "### Suggested Instruction Patch\n"
                "1. Use `tool_output_lookup` with `focus='auto'`.\n"
            ),
            "confidence": 0.66,
            "source": "test",
        }

        proposal = parse_skill_patch_candidate_content(str(candidate["content"]))
        artifact = render_skill_patch_artifact(
            artifact_id="skill-patch-1",
            candidate=candidate,
            promote_reason="reviewed",
            created_at="2026-04-19T00:00:00+00:00",
            artifact_path=Path(".mini_claw/skill_patches/skill-patch-1.md"),
        )

        self.assertEqual(proposal.target_skill, "repo-onboarding")
        self.assertEqual(proposal.skill_path, "examples/sample_skill/SKILL.md")
        self.assertEqual(proposal.contract_patch, ["- triggers += lookup"])
        self.assertIn("# Skill Patch Artifact", artifact)
        self.assertIn("Use `tool_output_lookup`", artifact)

    def test_skill_patch_apply_preview_generates_unified_diff(self) -> None:
        artifact = {
            "artifact_id": "skill-patch-1",
            "candidate_id": "skill-1",
            "target_skill": "repo-onboarding",
            "skill_path": "examples/sample_skill/SKILL.md",
            "content": (
                "# Skill Patch Artifact\n"
                "- artifact_id: skill-patch-1\n"
                "- candidate_id: skill-1\n"
                "- target_skill: repo-onboarding\n"
                "- skill_path: examples/sample_skill/SKILL.md\n"
                "\n"
                "## Proposed Contract Patch\n"
                "- allowed_tools += tool_output_lookup\n"
                "\n"
                "## Proposed Instruction Patch\n"
                "1. Use focus='auto' after truncated shell output.\n"
                "\n"
                "## Review Checklist\n"
                "1. Review it.\n"
            ),
        }

        preview = build_skill_patch_apply_preview(
            current_content="# Skill\n\nExisting instructions.\n",
            artifact=artifact,
        )

        self.assertIn("--- examples/sample_skill/SKILL.md", preview.diff)
        self.assertIn("+++ examples/sample_skill/SKILL.md (skill patch preview)", preview.diff)
        self.assertIn("+## Runtime Learning Proposal", preview.diff)
        self.assertIn("+1. Use focus='auto' after truncated shell output.", preview.diff)
        self.assertIn("Runtime Learning Proposal", preview.proposed_content)


if __name__ == "__main__":
    unittest.main()
