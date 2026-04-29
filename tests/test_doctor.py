import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from mini_claw.agent.state import AgentResult
from mini_claw.background.jobs import BackgroundRunRecord
from mini_claw.dashboard import build_runtime_dashboard
from mini_claw.doctor import run_runtime_doctor, summarize_doctor_changes
from mini_claw.memory.candidates import MemoryCandidate
from mini_claw.memory.store import MemoryStore
from mini_claw.sessions.store import SessionManager
from mini_claw.task_graph.graph import TaskGraph, TaskNode
from mini_claw.tools.base import ToolResult
from mini_claw.tracing.events import RuntimeEvent


class RuntimeDoctorTest(unittest.TestCase):
    def test_doctor_reports_fail_warn_and_info_findings(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            memory = MemoryStore(root / ".mini_claw" / "memory")
            memory.append_event(RuntimeEvent("task_started", {"task": "inspect repository"}))
            memory.append_event(RuntimeEvent("tool_call", {"tool": "shell", "ok": False, "metadata": {}}))
            memory.append_event(RuntimeEvent("task_finished", {"success": False}))
            memory.store_tool_result(
                "shell",
                {"command": "python -m pytest"},
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
            graph.add(TaskNode(task_id="task-1", objective="inspect repo", status="blocked"))
            graph.save(root / ".mini_claw" / "task_graph.json")

            session_manager = SessionManager(root)
            session = session_manager.create(name="doctor-demo")
            turn = session_manager.begin_turn(session.session_id, "inspect repository")
            session_manager.complete_turn(
                session.session_id,
                turn.turn_id,
                result=AgentResult(
                    success=False,
                    final_answer="failed",
                    steps=[],
                ),
                trace_lines=[
                    '{"event":"task_started","payload":{"task":"inspect repository"}}\n',
                    '{"event":"task_finished","payload":{"success":false,"failure_report":{"root_cause":"test","suggested_action":"retry"}}}\n',
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
                        status="failed",
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
            report = run_runtime_doctor(dashboard)

            self.assertEqual(report.status, "fail")
            self.assertTrue(any(f.code == "tool_failures" for f in report.findings))
            self.assertTrue(any(f.code == "background_failed" for f in report.findings))
            self.assertTrue(any(f.code == "tasks_blocked" for f in report.findings))
            self.assertTrue(any(f.code == "session_failed_turns" for f in report.findings))
            self.assertTrue(any(f.code == "tool_output_truncated" for f in report.findings))
            self.assertTrue(any(f.code == "memory_pending" for f in report.findings))
            self.assertEqual(report.exit_code(), 1)

    def test_doctor_reports_clean_runtime_when_no_issues_exist(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            memory = MemoryStore(root / ".mini_claw" / "memory")
            memory.append_event(RuntimeEvent("task_started", {"task": "inspect repository"}))
            memory.append_event(RuntimeEvent("task_finished", {"success": True}))

            dashboard = build_runtime_dashboard(root)
            report = run_runtime_doctor(dashboard)

            self.assertEqual(report.status, "ok")
            self.assertEqual(report.exit_code(), 0)
            self.assertTrue(any(f.code == "session_missing" for f in report.findings))

    def test_doctor_change_summary_surfaces_state_deltas(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            first = run_runtime_doctor(build_runtime_dashboard(root))

            memory = MemoryStore(root / ".mini_claw" / "memory")
            memory.append_event(RuntimeEvent("tool_call", {"tool": "shell", "ok": False, "metadata": {}}))
            second = run_runtime_doctor(build_runtime_dashboard(root))

            changes = summarize_doctor_changes(first, second)

            self.assertTrue(any("status:" in line for line in changes))
            self.assertTrue(any("finding_added[tool_failures]" in line for line in changes))


if __name__ == "__main__":
    unittest.main()
