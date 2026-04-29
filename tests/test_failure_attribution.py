import unittest

from mini_claw.agent.state import AgentStep, TaskState
from mini_claw.reliability.failure import attribute_failure


class FailureAttributionTest(unittest.TestCase):
    def test_unknown_tool_is_bad_tool_use(self) -> None:
        state = TaskState(task="fix bug")
        state.steps.append(
            AgentStep(
                index=0,
                role="coder",
                model="mock",
                thought="use tool",
                observation="Unknown tool: read_file",
            )
        )

        report = attribute_failure(state)

        self.assertEqual(report.root_cause, "BAD_TOOL_USE")

    def test_patch_conflict_is_detected(self) -> None:
        state = TaskState(task="fix bug")
        state.steps.append(
            AgentStep(
                index=0,
                role="coder",
                model="mock",
                thought="patch",
                observation="Patch transaction failed: old text not found in app.py",
            )
        )

        report = attribute_failure(state)

        self.assertEqual(report.root_cause, "PATCH_CONFLICT")

    def test_read_before_write_required_is_detected(self) -> None:
        state = TaskState(task="fix bug")
        state.steps.append(
            AgentStep(
                index=0,
                role="coder",
                model="mock",
                thought="patch",
                observation="READ_BEFORE_WRITE_REQUIRED: app.py must be read before patching.",
            )
        )

        report = attribute_failure(state)

        self.assertEqual(report.root_cause, "READ_BEFORE_WRITE_REQUIRED")

    def test_stale_read_snapshot_is_detected(self) -> None:
        state = TaskState(task="fix bug")
        state.steps.append(
            AgentStep(
                index=0,
                role="coder",
                model="mock",
                thought="patch",
                observation="STALE_READ_SNAPSHOT: app.py changed after it was read.",
            )
        )

        report = attribute_failure(state)

        self.assertEqual(report.root_cause, "STALE_READ_SNAPSHOT")


if __name__ == "__main__":
    unittest.main()
