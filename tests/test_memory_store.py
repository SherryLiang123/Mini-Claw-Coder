import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from mini_claw.memory.store import MemoryStore
from mini_claw.memory.candidates import MemoryCandidate
from mini_claw.tools.base import ToolResult


class MemoryStoreTest(unittest.TestCase):
    def test_project_memory_retrieves_relevant_sections_under_budget(self) -> None:
        with TemporaryDirectory() as directory:
            store = MemoryStore(Path(directory) / ".mini_claw" / "memory")
            store.update_project_memory(
                "\n\n".join(
                    [
                        "# Project Memory\nGeneral notes.",
                        "## Commands\nUse python -m unittest discover -s tests -q.",
                        "## Database\nMigration files are generated.",
                        "## Frontend\nReact components live under web/src.",
                    ]
                )
            )

            memory = store.read_project_memory(query="fix unittest command", max_chars=120)

            self.assertIn("Memory retrieval", memory)
            self.assertIn("unittest", memory)
            self.assertNotIn("React components", memory)

    def test_project_memory_truncates_unstructured_memory(self) -> None:
        with TemporaryDirectory() as directory:
            store = MemoryStore(Path(directory) / ".mini_claw" / "memory")
            store.update_project_memory("x" * 5000)

            memory = store.read_project_memory(query="anything", max_chars=100)

            self.assertIn("project memory truncated", memory)
            self.assertLess(len(memory), 220)

    def test_memory_candidates_are_persisted(self) -> None:
        with TemporaryDirectory() as directory:
            store = MemoryStore(Path(directory) / ".mini_claw" / "memory")
            store.append_memory_candidate(
                MemoryCandidate(
                    kind="verified_task_outcome",
                    content="task succeeded",
                    source="test",
                    confidence=0.8,
                    evidence="unit test",
                    tags=["success"],
                )
            )

            candidates = store.read_memory_candidates()

            self.assertEqual(len(candidates), 1)
            self.assertEqual(candidates[0]["kind"], "verified_task_outcome")
            self.assertEqual(candidates[0]["tags"], ["success"])
            self.assertEqual(candidates[0]["status"], "pending")

    def test_memory_candidate_can_be_promoted(self) -> None:
        with TemporaryDirectory() as directory:
            store = MemoryStore(Path(directory) / ".mini_claw" / "memory")
            store.append_memory_candidate(
                MemoryCandidate(
                    candidate_id="mem-test",
                    kind="verified_task_outcome",
                    content="## Useful Fact\nUse unittest.",
                    source="test",
                    confidence=0.9,
                    evidence="unit test passed",
                    tags=["success"],
                )
            )

            promoted = store.promote_memory_candidate("mem-test", reason="verified in test")

            self.assertEqual(promoted["status"], "promoted")
            project_memory = store.read_project_memory()
            self.assertIn("candidate_id: mem-test", project_memory)
            self.assertIn("Use unittest.", project_memory)

    def test_promoted_evidence_strategy_stays_out_of_project_memory(self) -> None:
        with TemporaryDirectory() as directory:
            store = MemoryStore(Path(directory) / ".mini_claw" / "memory")
            store.append_memory_candidate(
                MemoryCandidate(
                    candidate_id="evidence-test",
                    kind="evidence_lookup_strategy",
                    content=(
                        "## Evidence Lookup Strategy\n"
                        "- task: fix demo_pkg import failure\n"
                        "- queries: demo_pkg, traceback\n"
                    ),
                    source="test",
                    confidence=0.68,
                    evidence="tool_output_lookup resolved the import failure",
                    tags=["evidence", "lookup", "intent:error"],
                )
            )

            promoted = store.promote_memory_candidate("evidence-test", reason="verified in test")

            self.assertEqual(promoted["status"], "promoted")
            self.assertEqual(store.read_project_memory(), "(none)")
            strategies = store.read_evidence_strategies(query="demo_pkg import", limit=3)
            self.assertEqual(len(strategies), 1)
            self.assertEqual(strategies[0]["candidate_id"], "evidence-test")

    def test_memory_candidate_can_be_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            store = MemoryStore(Path(directory) / ".mini_claw" / "memory")
            store.append_memory_candidate(
                MemoryCandidate(
                    candidate_id="mem-reject",
                    kind="verified_task_outcome",
                    content="bad fact",
                    source="test",
                    confidence=0.1,
                    evidence="not enough evidence",
                )
            )

            rejected = store.reject_memory_candidate("1", reason="low confidence")

            self.assertEqual(rejected["status"], "rejected")
            self.assertEqual(store.read_project_memory(), "(none)")

    def test_promoted_skill_patch_candidate_stays_out_of_project_memory(self) -> None:
        with TemporaryDirectory() as directory:
            store = MemoryStore(Path(directory) / ".mini_claw" / "memory")
            store.append_memory_candidate(
                MemoryCandidate(
                    candidate_id="skill-patch-test",
                    kind="skill_patch_candidate",
                    content=(
                        "## Skill Patch Candidate\n"
                        "- target_skill: repo-onboarding\n"
                        "- recommended_allowed_tools_addition: tool_output_lookup\n"
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

            promoted = store.promote_memory_candidate("skill-patch-test", reason="reviewed")

            self.assertEqual(promoted["status"], "promoted")
            self.assertTrue(promoted["artifact_id"].startswith("skill-patch-"))
            self.assertIn("skill_patches", promoted["artifact_path"])
            self.assertEqual(store.read_project_memory(), "(none)")

            artifact_path = Path(promoted["artifact_path"])
            self.assertTrue(artifact_path.exists())
            artifact_content = artifact_path.read_text(encoding="utf-8")
            self.assertIn("# Skill Patch Artifact", artifact_content)
            self.assertIn("candidate_id: skill-patch-test", artifact_content)
            self.assertIn("allowed_tools += tool_output_lookup", artifact_content)

            artifacts = store.read_skill_patch_artifacts()
            self.assertEqual(len(artifacts), 1)
            self.assertEqual(artifacts[0]["candidate_id"], "skill-patch-test")
            loaded = store.read_skill_patch_artifact("skill-patch-test")
            self.assertEqual(loaded["artifact_id"], promoted["artifact_id"])

            eval_result = store.record_skill_patch_eval_result(
                promoted["artifact_id"],
                command="python -m unittest discover -s tests -q",
                ok=True,
                exit_code=0,
                output="64 tests passed",
            )

            self.assertEqual(eval_result["status"], "passed")
            artifacts = store.read_skill_patch_artifacts()
            self.assertEqual(artifacts[0]["eval_status"], "passed")
            loaded = store.read_skill_patch_artifact("skill-patch-test")
            self.assertIn("## Eval Gate Result", loaded["content"])
            self.assertIn("64 tests passed", loaded["content"])

    def test_tool_results_are_persisted_with_lookup_handle(self) -> None:
        with TemporaryDirectory() as directory:
            store = MemoryStore(Path(directory) / ".mini_claw" / "memory")

            handle = store.store_tool_result(
                "shell",
                {"command": "echo hello"},
                ToolResult(ok=True, output="hello\n", metadata={"exit_code": 0}),
            )

            self.assertEqual(handle.tool, "shell")
            self.assertIn("tool-output show", handle.lookup_hint)
            records = store.list_tool_outputs()
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["output_id"], handle.output_id)
            loaded = store.read_tool_output(handle.output_id)
            self.assertEqual(loaded["tool"], "shell")
            self.assertEqual(loaded["output"], "hello\n")

    def test_tool_result_preview_is_truncated_but_full_record_is_lookupable(self) -> None:
        with TemporaryDirectory() as directory:
            store = MemoryStore(Path(directory) / ".mini_claw" / "memory")
            long_output = "A" * 3000

            handle = store.store_tool_result(
                "shell",
                {"command": "python -c print('x')"},
                ToolResult(ok=True, output=long_output),
                preview_chars=200,
            )

            self.assertTrue(handle.truncated)
            self.assertIn("tool output preview truncated", handle.preview)
            loaded = store.read_tool_output("1")
            self.assertEqual(loaded["output_chars"], 3000)
            self.assertEqual(len(loaded["output"]), 3000)

    def test_tool_result_persists_lookup_plan(self) -> None:
        with TemporaryDirectory() as directory:
            store = MemoryStore(Path(directory) / ".mini_claw" / "memory")
            handle = store.store_tool_result(
                "shell",
                {"command": "python -m pytest", "task": "fix demo_pkg import failure"},
                ToolResult(
                    ok=False,
                    output=(
                        "Traceback (most recent call last):\n"
                        "ModuleNotFoundError: No module named 'demo_pkg'\n"
                    ),
                ),
                task="fix demo_pkg import failure",
            )

            loaded = store.read_tool_output("1")

            self.assertIn("demo_pkg", handle.lookup_queries)
            self.assertIn("lookup_plan", loaded)
            hints = loaded["lookup_plan"]["hints"]
            self.assertTrue(any(hint.get("kind") == "error_token" for hint in hints))
            self.assertTrue(any(hint.get("query") == "demo_pkg" for hint in hints))


if __name__ == "__main__":
    unittest.main()
