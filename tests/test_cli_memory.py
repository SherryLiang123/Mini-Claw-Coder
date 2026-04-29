import io
import unittest
from argparse import Namespace
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

from mini_claw.cli import cmd_memory
from mini_claw.memory.candidates import MemoryCandidate
from mini_claw.memory.store import MemoryStore


class MemoryCliTest(unittest.TestCase):
    def test_memory_candidates_support_kind_and_query_filters(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            memory = MemoryStore(root / ".mini_claw" / "memory")
            memory.append_memory_candidate(
                MemoryCandidate(
                    candidate_id="fact-1",
                    kind="verified_task_outcome",
                    content="## Verified Task Outcome\n- task: inspect repository",
                    source="test",
                    confidence=0.7,
                    evidence="completed task",
                    tags=["success"],
                )
            )
            memory.append_memory_candidate(
                MemoryCandidate(
                    candidate_id="skill-1",
                    kind="skill_patch_candidate",
                    content=(
                        "## Skill Patch Candidate\n"
                        "- target_skill: repo-onboarding\n"
                        "- recommended_allowed_tools_addition: tool_output_lookup\n"
                    ),
                    source="test",
                    confidence=0.66,
                    evidence="successful task used tool_output_lookup",
                    tags=["skill", "patch", "candidate"],
                )
            )

            args = Namespace(
                workspace=str(root),
                memory_command="candidates",
                kind="skill_patch_candidate",
                status="",
                query="repo onboarding lookup",
                limit=10,
            )
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                exit_code = cmd_memory(args)

            self.assertEqual(exit_code, 0)
            output = buffer.getvalue()
            self.assertIn("skill-1", output)
            self.assertIn("skill_patch_candidate", output)
            self.assertNotIn("fact-1", output)

    def test_skill_patch_artifacts_can_be_promoted_listed_and_shown(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            memory = MemoryStore(root / ".mini_claw" / "memory")
            skill_path = root / "examples" / "sample_skill" / "SKILL.md"
            skill_path.parent.mkdir(parents=True)
            skill_path.write_text("# Repo Onboarding\n\nExisting instructions.\n", encoding="utf-8")
            memory.append_memory_candidate(
                MemoryCandidate(
                    candidate_id="skill-1",
                    kind="skill_patch_candidate",
                    content=(
                        "## Skill Patch Candidate\n"
                        "- target_skill: repo-onboarding\n"
                        "- skill_path: examples/sample_skill/SKILL.md\n"
                        "\n"
                        "### Suggested Contract Patch\n"
                        "- allowed_tools += tool_output_lookup\n"
                        "\n"
                        "### Suggested Instruction Patch\n"
                        "1. Use focus='auto' after truncated shell output.\n"
                    ),
                    source="test",
                    confidence=0.66,
                    evidence="successful task used tool_output_lookup",
                    tags=["skill", "patch", "candidate"],
                )
            )

            promote_args = Namespace(
                workspace=str(root),
                memory_command="promote",
                ref="skill-1",
                reason="reviewed",
            )
            promote_buffer = io.StringIO()
            with redirect_stdout(promote_buffer):
                exit_code = cmd_memory(promote_args)
            self.assertEqual(exit_code, 0)
            self.assertIn("skill_patch_artifact:", promote_buffer.getvalue())

            list_args = Namespace(
                workspace=str(root),
                memory_command="skill-patches",
                query="repo onboarding lookup",
                limit=10,
            )
            list_buffer = io.StringIO()
            with redirect_stdout(list_buffer):
                exit_code = cmd_memory(list_args)
            self.assertEqual(exit_code, 0)
            list_output = list_buffer.getvalue()
            self.assertIn("skill-1", list_output)
            self.assertIn("repo-onboarding", list_output)
            self.assertIn("eval_status=pending", list_output)

            verify_args = Namespace(
                workspace=str(root),
                memory_command="skill-patch-verify",
                ref="skill-1",
                command="python --version",
                timeout=30,
            )
            verify_buffer = io.StringIO()
            with redirect_stdout(verify_buffer):
                exit_code = cmd_memory(verify_args)
            self.assertEqual(exit_code, 0)
            self.assertIn("status=passed", verify_buffer.getvalue())

            show_args = Namespace(
                workspace=str(root),
                memory_command="skill-patch-show",
                ref="skill-1",
            )
            show_buffer = io.StringIO()
            with redirect_stdout(show_buffer):
                exit_code = cmd_memory(show_args)
            self.assertEqual(exit_code, 0)
            show_output = show_buffer.getvalue()
            self.assertIn("# Skill Patch Artifact", show_output)
            self.assertIn("allowed_tools += tool_output_lookup", show_output)
            self.assertIn("## Eval Gate Result", show_output)

            preview_args = Namespace(
                workspace=str(root),
                memory_command="skill-patch-preview",
                ref="skill-1",
            )
            preview_buffer = io.StringIO()
            with redirect_stdout(preview_buffer):
                exit_code = cmd_memory(preview_args)
            self.assertEqual(exit_code, 0)
            preview_output = preview_buffer.getvalue()
            self.assertIn("--- examples/sample_skill/SKILL.md", preview_output)
            self.assertIn("+## Runtime Learning Proposal", preview_output)
            self.assertEqual(
                skill_path.read_text(encoding="utf-8"),
                "# Repo Onboarding\n\nExisting instructions.\n",
            )


if __name__ == "__main__":
    unittest.main()
