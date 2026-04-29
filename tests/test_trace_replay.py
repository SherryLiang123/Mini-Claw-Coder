import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from mini_claw.memory.store import MemoryStore
from mini_claw.tracing.events import RuntimeEvent
from mini_claw.tracing.replay import replay_trace


class TraceReplayTest(unittest.TestCase):
    def test_replay_trace_summarizes_events(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            memory = MemoryStore(root / ".mini_claw" / "memory")
            memory.append_event(RuntimeEvent("task_started", {"task": "fix"}))
            memory.append_event(
                RuntimeEvent(
                    "context_build",
                    {
                        "route_reason": "new_context_compaction",
                        "budget": {"used_chars": 10, "max_chars": 100},
                    },
                )
            )
            memory.append_event(
                RuntimeEvent(
                    "tool_call",
                    {
                        "tool": "apply_patch",
                        "ok": False,
                        "metadata": {"transaction_id": "tx-1"},
                    },
                )
            )
            memory.append_event(
                RuntimeEvent(
                    "tool_call",
                    {
                        "tool": "tool_output_lookup",
                        "ok": True,
                        "metadata": {
                            "focus": "auto",
                            "intent": "error",
                            "exclude_queries_count": 1,
                            "hint_index": 1,
                        },
                    },
                )
            )
            memory.append_event(
                RuntimeEvent(
                    "evidence_selected",
                    {
                        "query": "demo_pkg",
                        "intent": "error",
                        "source_output_id": "tool-1",
                    },
                )
            )
            memory.append_event(
                RuntimeEvent(
                    "lookup_policy_blocked",
                    {"attempted_tool": "shell", "pending_output_id": "tool-1"},
                )
            )
            memory.append_event(
                RuntimeEvent(
                    "memory_candidate_created",
                    {
                        "kind": "skill_patch_candidate",
                        "source": "agent_skill_evolution",
                        "confidence": 0.66,
                        "tags": ["skill", "patch", "candidate"],
                    },
                )
            )
            memory.append_event(
                RuntimeEvent(
                    "skill_patch_artifact_created",
                    {
                        "artifact_id": "skill-patch-1",
                        "candidate_id": "skill-1",
                        "target_skill": "repo-onboarding",
                    },
                )
            )
            memory.append_event(
                RuntimeEvent(
                    "skill_patch_eval_recorded",
                    {
                        "eval_id": "skill-patch-eval-1",
                        "artifact_id": "skill-patch-1",
                        "candidate_id": "skill-1",
                        "status": "passed",
                        "exit_code": 0,
                    },
                )
            )
            memory.append_event(
                RuntimeEvent(
                    "skill_patch_apply_previewed",
                    {
                        "artifact_id": "skill-patch-1",
                        "candidate_id": "skill-1",
                        "target_skill": "repo-onboarding",
                    },
                )
            )
            memory.append_event(
                RuntimeEvent(
                    "context_compacted",
                    {
                        "step": 4,
                        "compacted_steps": 2,
                        "kept_steps": 3,
                        "summary_chars": 240,
                        "tool_counts": {"shell": 2},
                    },
                )
            )
            memory.append_event(
                RuntimeEvent(
                    "multi_agent_handoff",
                    {
                        "type": "handoff",
                        "sender": "planner",
                        "receiver": "coder",
                        "content": {"task": "fix"},
                    },
                )
            )
            memory.append_event(
                RuntimeEvent(
                    "orchestration_step",
                    {
                        "role": "planner",
                        "task_id": "task-1",
                        "status": "ok",
                        "detail": "selected ready task",
                    },
                )
            )
            memory.append_event(
                RuntimeEvent(
                    "orchestration_step",
                    {
                        "role": "tester",
                        "task_id": "task-1",
                        "status": "failed",
                        "detail": "exit_code=2",
                    },
                )
            )
            memory.append_event(
                RuntimeEvent(
                    "orchestration_step",
                    {
                        "role": "integrator",
                        "task_id": "task-2",
                        "status": "ok",
                        "detail": "merged task-2",
                    },
                )
            )
            memory.append_event(
                RuntimeEvent(
                    "orchestration_step",
                    {
                        "role": "integrator",
                        "task_id": "task-3",
                        "status": "failed",
                        "detail": "conflict",
                    },
                )
            )
            memory.append_event(
                RuntimeEvent(
                    "task_finished",
                    {
                        "success": False,
                        "failure_report": {
                            "root_cause": "PATCH_CONFLICT",
                            "suggested_action": "Re-read target file.",
                        },
                        "evidence_summary": {
                            "lookups": 1,
                            "refinements": 1,
                            "queries": ["demo_pkg"],
                        },
                    },
                )
            )

            report = replay_trace(memory.trace_path)

            self.assertEqual(report.total_events, 17)
            self.assertEqual(report.context_builds, 1)
            self.assertEqual(report.route_reason_counts, {"new_context_compaction": 1})
            self.assertEqual(report.tool_calls, 2)
            self.assertEqual(report.failed_tool_calls, 1)
            self.assertEqual(report.truncated_tool_outputs, 0)
            self.assertEqual(report.lookup_auto_focus_calls, 1)
            self.assertEqual(report.lookup_refinement_calls, 1)
            self.assertEqual(report.evidence_selected_events, 1)
            self.assertEqual(report.tasks_with_evidence_summary, 1)
            self.assertEqual(report.distinct_evidence_queries, 1)
            self.assertEqual(report.skill_patch_candidates, 1)
            self.assertEqual(report.skill_patch_artifacts_created, 1)
            self.assertEqual(report.skill_patch_eval_runs, 1)
            self.assertEqual(report.skill_patch_eval_passed, 1)
            self.assertEqual(report.skill_patch_apply_previews, 1)
            self.assertEqual(report.context_compactions, 1)
            self.assertEqual(report.lookup_policy_blocks, 1)
            self.assertEqual(report.agent_step_failures, 0)
            self.assertEqual(report.multi_agent_handoffs, 1)
            self.assertEqual(report.orchestration_steps, 4)
            self.assertEqual(
                report.orchestration_role_counts,
                {"integrator": 2, "planner": 1, "tester": 1},
            )
            self.assertEqual(report.tester_failures, 1)
            self.assertEqual(report.integrator_merges, 1)
            self.assertEqual(report.integrator_failures, 1)
            self.assertEqual(report.patch_transactions, ["tx-1"])
            self.assertEqual(report.failure_reports[0]["root_cause"], "PATCH_CONFLICT")


if __name__ == "__main__":
    unittest.main()
