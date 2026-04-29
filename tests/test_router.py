import unittest

from mini_claw.agent.state import AgentStep, PendingToolOutputLookup, TaskState
from mini_claw.config import ModelConfig
from mini_claw.routing.router import ModelRouter


class ModelRouterTest(unittest.TestCase):
    def test_router_starts_with_planner(self) -> None:
        router = ModelRouter(ModelConfig())

        self.assertEqual(router.select_role(TaskState(task="fix bug")), "planner")

    def test_router_moves_to_reviewer_after_failure(self) -> None:
        router = ModelRouter(ModelConfig())
        state = TaskState(
            task="fix bug",
            steps=[AgentStep(index=0, role="planner", model="m", thought="")],
        )
        state.failure_count = 1

        self.assertEqual(router.select_role(state), "reviewer")

    def test_router_uses_reviewer_when_lookup_is_pending(self) -> None:
        router = ModelRouter(ModelConfig())
        state = TaskState(
            task="inspect long output",
            steps=[AgentStep(index=0, role="coder", model="m", thought="")],
            pending_lookup=PendingToolOutputLookup(
                output_id="tool-1",
                source_tool="shell",
                source_args={"command": "rg TODO"},
                lookup_hint="python -m mini_claw tool-output show tool-1",
            ),
        )

        decision = router.select(state)

        self.assertEqual(decision.role, "reviewer")
        self.assertEqual(decision.reason, "pending_tool_output_lookup")
        self.assertTrue(bool(decision.signals.get("pending_lookup")))

    def test_router_uses_summarizer_after_new_compaction(self) -> None:
        router = ModelRouter(ModelConfig())
        state = TaskState(
            task="continue long task",
            steps=[AgentStep(index=0, role="coder", model="m", thought="")],
            compacted_steps=4,
            compaction_count=1,
            last_summarized_compacted_steps=0,
        )

        decision = router.select(state)

        self.assertEqual(decision.role, "summarizer")
        self.assertEqual(decision.reason, "new_context_compaction")
        self.assertEqual(decision.model, ModelConfig().summarizer_model)

    def test_basic_policy_ignores_compaction_signal(self) -> None:
        router = ModelRouter(ModelConfig(), policy="basic")
        state = TaskState(
            task="continue long task",
            steps=[AgentStep(index=0, role="coder", model="m", thought="")],
            compacted_steps=4,
            compaction_count=1,
            last_summarized_compacted_steps=0,
        )

        decision = router.select(state)

        self.assertEqual(decision.role, "coder")
        self.assertEqual(decision.reason, "continue_execution")


if __name__ == "__main__":
    unittest.main()
