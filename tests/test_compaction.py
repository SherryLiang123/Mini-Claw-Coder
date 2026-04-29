import unittest

from mini_claw.agent.compaction import refresh_compact_summary
from mini_claw.agent.state import AgentStep, TaskState, ToolCall


class CompactionTest(unittest.TestCase):
    def test_refresh_compact_summary_updates_state_after_threshold(self) -> None:
        state = TaskState(
            task="inspect repository",
            steps=[
                AgentStep(
                    index=0,
                    role="planner",
                    model="mock-planner",
                    thought="Start.",
                    action=ToolCall(tool="shell", args={"command": "echo STEP0"}),
                    observation="STEP0",
                ),
                AgentStep(
                    index=1,
                    role="coder",
                    model="mock-coder",
                    thought="Continue.",
                    action=ToolCall(tool="shell", args={"command": "echo STEP1"}),
                    observation="STEP1",
                ),
                AgentStep(
                    index=2,
                    role="coder",
                    model="mock-coder",
                    thought="Continue.",
                    action=ToolCall(tool="tool_output_lookup", args={"ref": "1"}),
                    observation="Recovered STEP2 through lookup.",
                ),
                AgentStep(
                    index=3,
                    role="reviewer",
                    model="mock-reviewer",
                    thought="Review.",
                    action=ToolCall(tool="shell", args={"command": "echo STEP3"}),
                    observation="STEP3",
                ),
                AgentStep(
                    index=4,
                    role="coder",
                    model="mock-coder",
                    thought="Continue.",
                    action=ToolCall(tool="shell", args={"command": "echo STEP4"}),
                    observation="STEP4",
                ),
            ],
            modified_files={"app.py"},
        )

        update = refresh_compact_summary(state)

        self.assertIsNotNone(update)
        assert update is not None
        self.assertEqual(update.compacted_steps, 2)
        self.assertEqual(update.kept_steps, 3)
        self.assertEqual(state.compacted_steps, 2)
        self.assertEqual(state.compaction_count, 1)
        self.assertIn("tool_counts: shell=2", state.compact_summary)
        self.assertIn("modified_files_so_far: app.py", state.compact_summary)
        self.assertIn("STEP0", state.compact_summary)


if __name__ == "__main__":
    unittest.main()
