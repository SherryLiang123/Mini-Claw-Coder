import io
import json
import unittest
from argparse import Namespace
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

from mini_claw.agent.state import AgentResult
from mini_claw.cli import cmd_dashboard
from mini_claw.memory.store import MemoryStore
from mini_claw.sessions.store import SessionManager
from mini_claw.task_graph.graph import TaskGraph, TaskNode
from mini_claw.tracing.events import RuntimeEvent


class DashboardCliTest(unittest.TestCase):
    def test_dashboard_cli_prints_unified_runtime_summary(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            memory = MemoryStore(root / ".mini_claw" / "memory")
            memory.append_event(RuntimeEvent("task_started", {"task": "inspect repository"}))
            memory.append_event(RuntimeEvent("task_finished", {"success": True}))

            graph = TaskGraph()
            graph.add(TaskNode(task_id="task-1", objective="inspect repo"))
            graph.save(root / ".mini_claw" / "task_graph.json")

            session_manager = SessionManager(root)
            session = session_manager.create(name="cli-dashboard")
            turn = session_manager.begin_turn(session.session_id, "inspect repository")
            session_manager.complete_turn(
                session.session_id,
                turn.turn_id,
                result=AgentResult(
                    success=True,
                    final_answer="done",
                    steps=[],
                ),
                trace_lines=[
                    '{"event":"task_started","payload":{"task":"inspect repository"}}\n',
                    '{"event":"task_finished","payload":{"success":true}}\n',
                ],
            )

            args = Namespace(
                workspace=str(root),
                session="",
                session_turn_limit=10,
                background_limit=5,
                tool_output_limit=5,
                watch=False,
                interval=2.0,
                iterations=0,
                no_clear=False,
                changes_only=False,
                output_file="",
                json=False,
            )
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                exit_code = cmd_dashboard(args)

            self.assertEqual(exit_code, 0)
            output = buffer.getvalue()
            self.assertIn("# Mini Claw Runtime Dashboard", output)
            self.assertIn("## Sessions", output)
            self.assertIn("latest_session_name: cli-dashboard", output)
            self.assertIn("## Tasks", output)
            self.assertIn("pending: 1", output)

    def test_dashboard_cli_watch_mode_runs_multiple_iterations(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            memory = MemoryStore(root / ".mini_claw" / "memory")
            memory.append_event(RuntimeEvent("task_started", {"task": "inspect repository"}))
            memory.append_event(RuntimeEvent("task_finished", {"success": True}))

            args = Namespace(
                workspace=str(root),
                session="",
                session_turn_limit=10,
                background_limit=5,
                tool_output_limit=5,
                watch=True,
                interval=0.0,
                iterations=2,
                no_clear=True,
                changes_only=False,
                output_file="",
                json=False,
            )
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                exit_code = cmd_dashboard(args)

            self.assertEqual(exit_code, 0)
            output = buffer.getvalue()
            self.assertIn("# Dashboard Watch 1", output)
            self.assertIn("# Dashboard Watch 2", output)
            self.assertIn("## Changes Since Last Refresh", output)
            self.assertIn("- no runtime state changes detected", output)
            self.assertGreaterEqual(output.count("# Mini Claw Runtime Dashboard"), 2)

    def test_dashboard_cli_watch_changes_only_hides_full_dashboard_after_first_refresh(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            memory = MemoryStore(root / ".mini_claw" / "memory")
            memory.append_event(RuntimeEvent("task_started", {"task": "inspect repository"}))
            memory.append_event(RuntimeEvent("task_finished", {"success": True}))

            args = Namespace(
                workspace=str(root),
                session="",
                session_turn_limit=10,
                background_limit=5,
                tool_output_limit=5,
                watch=True,
                interval=0.0,
                iterations=2,
                no_clear=True,
                changes_only=True,
                output_file="",
                json=False,
            )
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                exit_code = cmd_dashboard(args)

            self.assertEqual(exit_code, 0)
            output = buffer.getvalue()
            self.assertIn("# Dashboard Watch 1", output)
            self.assertIn("# Dashboard Watch 2", output)
            self.assertIn("(no dashboard changes to display)", output)
            self.assertEqual(output.count("# Mini Claw Runtime Dashboard"), 1)

    def test_dashboard_cli_supports_json_output(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            memory = MemoryStore(root / ".mini_claw" / "memory")
            memory.append_event(RuntimeEvent("task_started", {"task": "inspect repository"}))
            memory.append_event(RuntimeEvent("task_finished", {"success": True}))

            args = Namespace(
                workspace=str(root),
                session="",
                session_turn_limit=10,
                background_limit=5,
                tool_output_limit=5,
                watch=False,
                interval=2.0,
                iterations=0,
                no_clear=False,
                changes_only=False,
                output_file="",
                json=True,
            )
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                exit_code = cmd_dashboard(args)

            self.assertEqual(exit_code, 0)
            payload = json.loads(buffer.getvalue())
            self.assertEqual(payload["trace_summary"]["total_events"], 2)
            self.assertEqual(payload["session_count"], 0)
            self.assertIn("latest_tool_outputs", payload)
            if payload["latest_tool_outputs"]:
                self.assertNotIn("output", payload["latest_tool_outputs"][0])
                self.assertIn("preview", payload["latest_tool_outputs"][0])

    def test_dashboard_cli_watch_json_outputs_one_object_per_iteration(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            memory = MemoryStore(root / ".mini_claw" / "memory")
            memory.append_event(RuntimeEvent("task_started", {"task": "inspect repository"}))
            memory.append_event(RuntimeEvent("task_finished", {"success": True}))

            args = Namespace(
                workspace=str(root),
                session="",
                session_turn_limit=10,
                background_limit=5,
                tool_output_limit=5,
                watch=True,
                interval=0.0,
                iterations=2,
                no_clear=True,
                changes_only=False,
                output_file="",
                json=True,
            )
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                exit_code = cmd_dashboard(args)

            self.assertEqual(exit_code, 0)
            rows = [json.loads(line) for line in buffer.getvalue().splitlines() if line.strip()]
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["iteration"], 1)
            self.assertEqual(rows[1]["iteration"], 2)
            self.assertIn("dashboard", rows[0])
            self.assertEqual(rows[1]["changes"], [])

    def test_dashboard_cli_json_can_write_output_file(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            memory = MemoryStore(root / ".mini_claw" / "memory")
            memory.append_event(RuntimeEvent("task_started", {"task": "inspect repository"}))
            output_path = root / "dashboard.json"

            args = Namespace(
                workspace=str(root),
                session="",
                session_turn_limit=10,
                background_limit=5,
                tool_output_limit=5,
                watch=False,
                interval=2.0,
                iterations=0,
                no_clear=False,
                changes_only=False,
                output_file=str(output_path),
                json=True,
            )
            with redirect_stdout(io.StringIO()):
                exit_code = cmd_dashboard(args)

            self.assertEqual(exit_code, 0)
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertIn("trace_summary", payload)

    def test_dashboard_cli_watch_json_can_append_ndjson_output_file(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            memory = MemoryStore(root / ".mini_claw" / "memory")
            memory.append_event(RuntimeEvent("task_started", {"task": "inspect repository"}))
            output_path = root / "dashboard.ndjson"

            args = Namespace(
                workspace=str(root),
                session="",
                session_turn_limit=10,
                background_limit=5,
                tool_output_limit=5,
                watch=True,
                interval=0.0,
                iterations=2,
                no_clear=True,
                changes_only=False,
                output_file=str(output_path),
                json=True,
            )
            with redirect_stdout(io.StringIO()):
                exit_code = cmd_dashboard(args)

            self.assertEqual(exit_code, 0)
            rows = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["iteration"], 1)
            self.assertEqual(rows[1]["iteration"], 2)


if __name__ == "__main__":
    unittest.main()
