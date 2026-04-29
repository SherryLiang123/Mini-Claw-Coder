import io
import unittest
from argparse import Namespace
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

from mini_claw.cli import cmd_viewer
from mini_claw.memory.store import MemoryStore
from mini_claw.tracing.events import RuntimeEvent


class ViewerCliTest(unittest.TestCase):
    def test_viewer_builds_html_from_bundle_json(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            bundle_path = root / ".mini_claw" / "runtime_bundle.json"
            bundle_path.parent.mkdir(parents=True, exist_ok=True)
            bundle_path.write_text(
                """
{
  "dashboard": {
    "workspace": "demo",
    "trace_summary": {"total_events": 3, "tool_calls": 1},
    "session_count": 0,
    "ready_tasks": []
  },
  "doctor": {
    "status": "ok",
    "summary": "OK with 0 fail, 0 warn, and 1 info finding(s).",
    "summary_by_category": {},
    "findings": []
  },
  "team_board": {
    "team_status": {"ready_tasks": [], "active_tasks": [], "task_count": 0},
    "runtime_health": {"status": "ok", "summary": "OK", "finding_count": 0, "summary_by_category": {}},
    "runtime_counts": {"trace_events": 3, "tool_calls": 1, "failed_tool_calls": 0, "context_builds": 0},
    "background_runs": {"total": 0, "recent": []}
  },
  "session_replay": null
}
                """.strip(),
                encoding="utf-8",
            )
            output_path = root / ".mini_claw" / "runtime_viewer.html"
            args = Namespace(
                workspace=str(root),
                from_workspace=False,
                source_target="bundle",
                input_file=str(bundle_path),
                output_file=str(output_path),
                title="Interview Demo Viewer",
                refresh_seconds=0.0,
                demo_mode=True,
                demo_language="zh",
                demo_focus="runtime",
                demo_script="short",
                session="",
                session_turn_limit=20,
                background_limit=5,
                tool_output_limit=5,
                ignore="",
                category="",
                severity_at_least="info",
                sort_by="default",
            )
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                exit_code = cmd_viewer(args)

            self.assertEqual(exit_code, 0)
            html = output_path.read_text(encoding="utf-8")
            self.assertIn("Interview Demo Viewer", html)
            self.assertIn("Mini Claw Runtime Demo", html)
            self.assertIn("Raw Data", html)
            self.assertIn("Demo mode: first screen tuned for interview walkthroughs.", html)
            self.assertIn("这个页面不是只看模型最后说了什么", html)
            self.assertIn('"dashboard"', html)
            self.assertIn('"team_board"', html)
            self.assertIn('const demoFocus = "runtime";', html)
            self.assertIn('const demoScript = "short";', html)
            self.assertIn("wrote", buffer.getvalue())

    def test_viewer_can_render_directly_from_workspace(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            memory = MemoryStore(root / ".mini_claw" / "memory")
            memory.append_event(RuntimeEvent("task_started", {"task": "workspace viewer"}))

            output_path = root / ".mini_claw" / "runtime_viewer.html"
            args = Namespace(
                workspace=str(root),
                from_workspace=True,
                source_target="bundle",
                input_file="",
                output_file=str(output_path),
                title="Workspace Viewer",
                refresh_seconds=1.5,
                demo_mode=False,
                demo_language="bilingual",
                demo_focus="auto",
                demo_script="full",
                session="",
                session_turn_limit=20,
                background_limit=5,
                tool_output_limit=5,
                ignore="",
                category="",
                severity_at_least="info",
                sort_by="default",
            )
            with redirect_stdout(io.StringIO()):
                exit_code = cmd_viewer(args)

            self.assertEqual(exit_code, 0)
            html = output_path.read_text(encoding="utf-8")
            self.assertIn("Workspace Viewer", html)
            self.assertIn('"mode":"snapshot"', html.replace(" ", ""))
            self.assertIn('"source_path":"workspace:', html.replace(" ", ""))
            self.assertIn('"team_board"', html)
            self.assertIn('http-equiv="refresh"', html)
            self.assertIn('content="1.5"', html)

    def test_viewer_builds_html_from_team_board_json(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            board_path = root / ".mini_claw" / "team_board.json"
            board_path.parent.mkdir(parents=True, exist_ok=True)
            board_path.write_text(
                """
{
  "workspace": "demo",
  "team_status": {
    "task_count": 2,
    "ready_tasks": [{"task_id": "task-1", "objective": "demo"}],
    "active_tasks": [{"task_id": "task-2", "status": "in_progress"}],
    "status_counts": {"pending": 1, "in_progress": 1}
  },
  "runtime_health": {
    "status": "warn",
    "summary": "WARN with 0 fail, 1 warn, and 0 info finding(s).",
    "finding_count": 1,
    "summary_by_category": {"trace": {"fail": 0, "warn": 1, "info": 0}}
  },
  "runtime_counts": {
    "trace_events": 8,
    "tool_calls": 3,
    "failed_tool_calls": 1,
    "context_builds": 2
  },
  "latest_session": null,
  "latest_session_replay": null,
  "background_runs": {"total": 1, "recent": []}
}
                """.strip(),
                encoding="utf-8",
            )
            output_path = root / ".mini_claw" / "team_board_viewer.html"
            args = Namespace(
                workspace=str(root),
                from_workspace=False,
                source_target="team-board",
                input_file=str(board_path),
                output_file=str(output_path),
                title="Team Board Viewer",
                refresh_seconds=0.0,
                demo_mode=True,
                demo_language="en",
                demo_focus="team",
                demo_script="full",
                session="",
                session_turn_limit=20,
                background_limit=5,
                tool_output_limit=5,
                ignore="",
                category="",
                severity_at_least="info",
                sort_by="default",
            )
            with redirect_stdout(io.StringIO()):
                exit_code = cmd_viewer(args)

            self.assertEqual(exit_code, 0)
            html = output_path.read_text(encoding="utf-8")
            self.assertIn("Team Board Viewer", html)
            self.assertIn('"team_status"', html)
            self.assertIn("Open with the control surface, not the final answer.", html)
            self.assertIn('const demoFocus = "team";', html)
            self.assertIn('const demoScript = "full";', html)

    def test_viewer_can_render_team_board_directly_from_workspace(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            memory = MemoryStore(root / ".mini_claw" / "memory")
            memory.append_event(RuntimeEvent("task_started", {"task": "team board viewer"}))

            output_path = root / ".mini_claw" / "team_board_viewer.html"
            args = Namespace(
                workspace=str(root),
                from_workspace=True,
                source_target="team-board",
                input_file="",
                output_file=str(output_path),
                title="Workspace Team Board Viewer",
                refresh_seconds=0.0,
                demo_mode=False,
                demo_language="bilingual",
                demo_focus="auto",
                demo_script="full",
                session="",
                session_turn_limit=20,
                background_limit=5,
                tool_output_limit=5,
                ignore="",
                category="",
                severity_at_least="info",
                sort_by="default",
            )
            with redirect_stdout(io.StringIO()):
                exit_code = cmd_viewer(args)

            self.assertEqual(exit_code, 0)
            html = output_path.read_text(encoding="utf-8")
            self.assertIn("Workspace Team Board Viewer", html)
            self.assertIn('"team_status"', html)
            self.assertIn('"team-board"', html)


if __name__ == "__main__":
    unittest.main()
