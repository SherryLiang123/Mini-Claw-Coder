import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from mini_claw.agent.state import AgentResult
from mini_claw.background.jobs import BackgroundRunRecord
from mini_claw.dashboard import build_runtime_dashboard, summarize_dashboard_changes
from mini_claw.memory.candidates import MemoryCandidate
from mini_claw.memory.store import MemoryStore
from mini_claw.sessions.store import SessionManager
from mini_claw.task_graph.graph import TaskGraph, TaskNode
from mini_claw.tools.base import ToolResult
from mini_claw.tracing.events import RuntimeEvent


class RuntimeDashboardTest(unittest.TestCase):
    def test_dashboard_aggregates_runtime_state(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            memory = MemoryStore(root / ".mini_claw" / "memory")
            memory.append_event(RuntimeEvent("task_started", {"task": "inspect repository"}))
            memory.append_event(
                RuntimeEvent(
                    "context_build",
                    {"route_reason": "initial_planning", "budget": {"used_chars": 100}},
                )
            )
            memory.append_event(
                RuntimeEvent(
                    "tool_call",
                    {"tool": "shell", "ok": True, "metadata": {}},
                )
            )
            memory.append_event(RuntimeEvent("task_finished", {"success": True}))
            memory.store_tool_result(
                "shell",
                {"command": "echo hi"},
                ToolResult(ok=True, output=("A" * 2_200)),
                task="inspect repository",
            )
            memory.append_memory_candidate(
                MemoryCandidate(
                    candidate_id="fact-1",
                    kind="verified_task_outcome",
                    content="## Verified Task Outcome\n- task: inspect repository",
                    source="test",
                    confidence=0.7,
                    evidence="completed",
                    tags=["success"],
                )
            )

            graph = TaskGraph()
            graph.add(TaskNode(task_id="task-1", objective="inspect repo"))
            graph.add(TaskNode(task_id="task-2", objective="patch app", status="blocked"))
            graph.save(root / ".mini_claw" / "task_graph.json")

            session_manager = SessionManager(root)
            session = session_manager.create(name="dashboard-demo")
            turn = session_manager.begin_turn(session.session_id, "inspect repository")
            session_manager.complete_turn(
                session.session_id,
                turn.turn_id,
                result=AgentResult(
                    success=True,
                    final_answer="inspection complete",
                    steps=[],
                    modified_files=["README.md"],
                ),
                trace_lines=[
                    '{"event":"task_started","payload":{"task":"inspect repository"}}\n',
                    '{"event":"context_build","payload":{"route_reason":"initial_planning"}}\n',
                    '{"event":"tool_call","payload":{"tool":"shell","ok":true,"metadata":{}}}\n',
                    '{"event":"task_finished","payload":{"success":true}}\n',
                ],
            )

            background_path = root / ".mini_claw" / "background" / "runs" / "bg-1.json"
            background_path.parent.mkdir(parents=True, exist_ok=True)
            background_path.write_text(
                json.dumps(
                    BackgroundRunRecord(
                        run_id="bg-1",
                        command="python -m unittest",
                        workspace=str(root),
                        status="succeeded",
                        created_at="2026-01-01T00:00:00+00:00",
                        label="tests",
                        task_id="task-1",
                    ).to_dict(),
                    ensure_ascii=True,
                    indent=2,
                ),
                encoding="utf-8",
            )

            dashboard = build_runtime_dashboard(root, session_turn_limit=10)

            self.assertEqual(dashboard.trace_summary.total_events, 4)
            self.assertEqual(dashboard.session_count, 1)
            self.assertEqual(dashboard.latest_session_replay.successful_turns, 1)
            self.assertEqual(dashboard.task_status_counts, {"blocked": 1, "pending": 1})
            self.assertEqual(len(dashboard.ready_tasks), 1)
            self.assertEqual(dashboard.background_status_counts, {"succeeded": 1})
            self.assertEqual(dashboard.tool_output_count, 1)
            self.assertEqual(dashboard.truncated_tool_output_count, 1)
            self.assertEqual(dashboard.memory_candidate_status_counts, {"pending": 1})
            rendered = dashboard.to_markdown()
            self.assertIn("# Mini Claw Runtime Dashboard", rendered)
            self.assertIn("latest_session:", rendered)
            self.assertIn("ready_tasks:", rendered)
            self.assertIn("latest_run bg-1", rendered)

    def test_dashboard_change_summary_surfaces_state_deltas(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            memory = MemoryStore(root / ".mini_claw" / "memory")
            memory.append_event(RuntimeEvent("task_started", {"task": "inspect repository"}))
            first = build_runtime_dashboard(root)

            memory.append_event(RuntimeEvent("tool_call", {"tool": "shell", "ok": True, "metadata": {}}))
            graph = TaskGraph()
            graph.add(TaskNode(task_id="task-1", objective="inspect repo", status="blocked"))
            graph.save(root / ".mini_claw" / "task_graph.json")
            second = build_runtime_dashboard(root)

            changes = summarize_dashboard_changes(first, second)

            self.assertTrue(any("trace.total_events" in line for line in changes))
            self.assertTrue(any("trace.tool_calls" in line for line in changes))
            self.assertTrue(any("tasks.blocked" in line for line in changes))


if __name__ == "__main__":
    unittest.main()
