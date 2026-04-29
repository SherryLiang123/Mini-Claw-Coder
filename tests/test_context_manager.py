import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from mini_claw.agent.state import AgentStep, TaskState, ToolCall
from mini_claw.context.manager import ContextManager
from mini_claw.memory.candidates import MemoryCandidate
from mini_claw.memory.store import MemoryStore


class ContextManagerTest(unittest.TestCase):
    def test_context_packet_includes_relevant_evidence_strategies(self) -> None:
        with TemporaryDirectory() as directory:
            workspace = Path(directory) / "workspace"
            workspace.mkdir()
            memory = MemoryStore(Path(directory) / ".mini_claw" / "memory")
            memory.append_memory_candidate(
                MemoryCandidate(
                    candidate_id="evidence-demo",
                    kind="evidence_lookup_strategy",
                    content=(
                        "## Evidence Lookup Strategy\n"
                        "- task: fix demo_pkg import failure\n"
                        "- queries: demo_pkg, traceback\n"
                    ),
                    source="test",
                    confidence=0.68,
                    evidence="lookup strategy succeeded",
                    tags=["evidence", "lookup", "intent:error"],
                )
            )
            memory.append_memory_candidate(
                MemoryCandidate(
                    candidate_id="evidence-irrelevant",
                    kind="evidence_lookup_strategy",
                    content=(
                        "## Evidence Lookup Strategy\n"
                        "- task: inspect vite config\n"
                        "- queries: vite.config.ts\n"
                    ),
                    source="test",
                    confidence=0.62,
                    evidence="lookup strategy succeeded",
                    tags=["evidence", "lookup", "intent:path"],
                )
            )
            memory.promote_memory_candidate("evidence-demo", reason="verified")
            memory.promote_memory_candidate("evidence-irrelevant", reason="verified")

            manager = ContextManager(
                workspace=workspace,
                memory=memory,
                skills=[],
                max_chars=10_000,
            )

            packet = manager.build_packet(
                "Follow repository rules.",
                TaskState(task="fix demo_pkg import failure"),
            )
            rendered = packet.render()

            self.assertIn("## Evidence Strategies", rendered)
            self.assertIn("candidate_id: evidence-demo", rendered)
            self.assertIn("demo_pkg", rendered)
            self.assertNotIn("candidate_id: evidence-irrelevant", rendered)

    def test_context_packet_includes_working_summary_when_steps_are_compacted(self) -> None:
        with TemporaryDirectory() as directory:
            workspace = Path(directory) / "workspace"
            workspace.mkdir()
            memory = MemoryStore(Path(directory) / ".mini_claw" / "memory")
            manager = ContextManager(
                workspace=workspace,
                memory=memory,
                skills=[],
                max_chars=10_000,
            )
            state = TaskState(
                task="inspect repository history",
                compact_summary=(
                    "- compacted_steps: 3\n"
                    "- tool_counts: shell=3\n"
                    "- modified_files_so_far: app.py\n"
                    "\n"
                    "### Older Step Highlights\n"
                    "- step 0 [planner/mock] tool=shell: STEP0\n"
                    "- step 1 [coder/mock] tool=shell: STEP1\n"
                ),
                compacted_steps=3,
                compaction_count=1,
                steps=[
                    AgentStep(
                        index=2,
                        role="coder",
                        model="mock",
                        thought="Inspect recent state.",
                        action=ToolCall(tool="shell", args={"command": "echo STEP2"}),
                        observation="STEP2",
                    ),
                    AgentStep(
                        index=3,
                        role="coder",
                        model="mock",
                        thought="Inspect current files.",
                        action=ToolCall(tool="shell", args={"command": "echo STEP3"}),
                        observation="STEP3",
                    ),
                ],
            )

            rendered = manager.build_packet("Follow repository rules.", state).render()

            self.assertIn("## Working Summary", rendered)
            self.assertIn("Older steps compacted: 3", rendered)
            self.assertIn("STEP0", rendered)
            self.assertIn("STEP3", rendered)

    def test_context_packet_includes_session_context_without_changing_task(self) -> None:
        with TemporaryDirectory() as directory:
            workspace = Path(directory) / "workspace"
            workspace.mkdir()
            memory = MemoryStore(Path(directory) / ".mini_claw" / "memory")
            manager = ContextManager(
                workspace=workspace,
                memory=memory,
                skills=[],
                max_chars=10_000,
            )

            rendered = manager.build_packet(
                "Follow repository rules.",
                TaskState(
                    task="fix failing import",
                    session_context=(
                        "Session session-123\n"
                        "Turn 1 [success]\n"
                        "task: inspect repository\n"
                    ),
                ),
            ).render()

            self.assertIn("## Task", rendered)
            self.assertIn("fix failing import", rendered)
            self.assertIn("## Session Context", rendered)
            self.assertIn("session-123", rendered)

    def test_context_packet_keeps_reference_roots_out_of_workspace_overview(self) -> None:
        with TemporaryDirectory() as directory:
            workspace = Path(directory) / "workspace"
            workspace.mkdir()
            (workspace / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            (workspace / ".external").mkdir()
            (workspace / ".external" / "reference.py").write_text("VALUE = 2\n", encoding="utf-8")
            (workspace / "pico-main").mkdir()
            (workspace / "pico-main" / "alt.py").write_text("VALUE = 3\n", encoding="utf-8")
            memory = MemoryStore(Path(directory) / ".mini_claw" / "memory")
            manager = ContextManager(
                workspace=workspace,
                memory=memory,
                skills=[],
                max_chars=10_000,
            )

            rendered = manager.build_packet(
                "Follow repository rules.",
                TaskState(task="inspect the main app entrypoint"),
            ).render()

            self.assertIn("app.py", rendered)
            self.assertNotIn(".external", rendered)
            self.assertNotIn("pico-main", rendered)


if __name__ == "__main__":
    unittest.main()
