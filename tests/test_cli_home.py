import io
import json
import unittest
from argparse import Namespace
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

from mini_claw.agent.state import AgentResult
from mini_claw.cli import cmd_home
from mini_claw.home import render_terminal_home_tui
from mini_claw.memory.store import MemoryStore
from mini_claw.sessions.store import SessionManager
from mini_claw.task_graph.graph import TaskGraph, TaskNode
from mini_claw.tracing.events import RuntimeEvent


class HomeCliTest(unittest.TestCase):
    def test_home_cli_renders_terminal_first_summary(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            memory = MemoryStore(root / ".mini_claw" / "memory")
            memory.append_event(RuntimeEvent("task_started", {"task": "home screen"}))
            memory.append_event(RuntimeEvent("task_finished", {"success": True}))

            graph = TaskGraph()
            graph.add(TaskNode(task_id="task-1", objective="ready task"))
            graph.save(root / ".mini_claw" / "task_graph.json")

            session_manager = SessionManager(root)
            session = session_manager.create(name="cli-home")
            turn = session_manager.begin_turn(session.session_id, "render home")
            session_manager.complete_turn(
                session.session_id,
                turn.turn_id,
                result=AgentResult(success=True, final_answer="done", steps=[]),
                trace_lines=[
                    '{"event":"task_started","payload":{"task":"home screen"}}\n',
                    '{"event":"task_finished","payload":{"success":true}}\n',
                ],
            )

            args = Namespace(
                workspace=str(root),
                session="",
                session_turn_limit=20,
                background_limit=5,
                tool_output_limit=5,
                watch=False,
                interval=2.0,
                iterations=0,
                no_clear=False,
                changes_only=False,
                ignore="",
                category="",
                severity_at_least="info",
                sort_by="default",
                output_file="",
                json=False,
            )
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = cmd_home(args)

            self.assertEqual(exit_code, 0)
            text = output.getvalue()
            self.assertIn("# Mini Claw Home", text)
            self.assertIn("## Operator Guide", text)
            self.assertIn("## Team Queue", text)
            self.assertIn("## Runtime Health", text)
            self.assertIn("## Runtime Counts", text)
            self.assertIn("## Latest Session", text)
            self.assertIn("python -S -m mini_claw run", text)
            self.assertIn(".mini_claw/sessions", text)
            self.assertIn("latest_session: session-", text)

    def test_home_cli_watch_json_outputs_home_payload_and_deltas(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            graph = TaskGraph()
            graph.add(TaskNode(task_id="task-1", objective="ready task"))
            graph.save(root / ".mini_claw" / "task_graph.json")

            args = Namespace(
                workspace=str(root),
                session="",
                session_turn_limit=20,
                background_limit=5,
                tool_output_limit=5,
                watch=True,
                interval=0.0,
                iterations=2,
                no_clear=True,
                changes_only=False,
                ignore="",
                category="",
                severity_at_least="info",
                sort_by="default",
                output_file="",
                json=True,
            )
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = cmd_home(args)

            self.assertEqual(exit_code, 0)
            lines = [line for line in output.getvalue().splitlines() if line.strip()]
            self.assertEqual(len(lines), 2)
            self.assertIn('"iteration": 1', lines[0])
            self.assertIn('"changes": []', lines[0])
            self.assertIn('"changes_by_section"', lines[0])
            self.assertIn('"changes_by_section_delta"', lines[0])
            self.assertIn('"home"', lines[0])
            self.assertIn('"team_board"', lines[1])

    def test_home_cli_can_write_json_output_file(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            graph = TaskGraph()
            graph.add(TaskNode(task_id="task-1", objective="ready task"))
            graph.save(root / ".mini_claw" / "task_graph.json")

            args = Namespace(
                workspace=str(root),
                session="",
                session_turn_limit=20,
                background_limit=5,
                tool_output_limit=5,
                watch=False,
                interval=0.0,
                iterations=0,
                no_clear=True,
                changes_only=False,
                ignore="",
                category="",
                severity_at_least="info",
                sort_by="default",
                output_file=".mini_claw/home.json",
                json=True,
            )
            with redirect_stdout(io.StringIO()):
                exit_code = cmd_home(args)

            self.assertEqual(exit_code, 0)
            payload = json.loads((root / ".mini_claw" / "home.json").read_text(encoding="utf-8"))
            self.assertIn("headline", payload)
            self.assertIn("bundle", payload)
            self.assertIn("team_board", payload["bundle"])

    def test_home_cli_can_render_tui_style_with_focus(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            memory = MemoryStore(root / ".mini_claw" / "memory")
            memory.append_event(RuntimeEvent("task_started", {"task": "tui home"}))

            graph = TaskGraph()
            graph.add(TaskNode(task_id="task-1", objective="ready task"))
            graph.save(root / ".mini_claw" / "task_graph.json")

            args = Namespace(
                workspace=str(root),
                session="",
                session_turn_limit=20,
                background_limit=5,
                tool_output_limit=5,
                watch=False,
                interval=0.0,
                iterations=0,
                no_clear=True,
                changes_only=False,
                style="tui",
                focus="team",
                width=96,
                ignore="",
                category="",
                severity_at_least="info",
                sort_by="default",
                output_file="",
                json=False,
            )
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = cmd_home(args)

            self.assertEqual(exit_code, 0)
            text = output.getvalue()
            self.assertIn("Mini Claw TUI", text)
            self.assertIn("Operator Guide", text)
            self.assertIn("focus: team", text)
            self.assertIn("Team Queue", text)
            self.assertIn("Runtime Health", text)
            self.assertIn("+", text)

    def test_home_cli_surfaces_local_runtime_profile(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            mini_claw_dir = root / ".mini_claw"
            mini_claw_dir.mkdir(parents=True, exist_ok=True)
            (mini_claw_dir / "openai_compatible.local.json").write_text(
                json.dumps(
                    {
                        "api_key": "demo-key",
                        "base_url": "https://open.bigmodel.cn/api/paas/v4",
                    }
                ),
                encoding="utf-8",
            )

            args = Namespace(
                workspace=str(root),
                session="",
                session_turn_limit=20,
                background_limit=5,
                tool_output_limit=5,
                watch=False,
                interval=0.0,
                iterations=0,
                no_clear=True,
                changes_only=False,
                ignore="",
                category="",
                severity_at_least="info",
                sort_by="default",
                output_file="",
                json=False,
            )
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = cmd_home(args)

            self.assertEqual(exit_code, 0)
            text = output.getvalue()
            self.assertIn("real-model-ready (openai-compatible local config)", text)
            self.assertIn("https://open.bigmodel.cn/api/paas/v4", text)
            self.assertIn("--model glm-4.5-air", text)

    def test_home_tui_can_mark_changed_panels(self) -> None:
        home = {
            "workspace": "demo",
            "generated_at": "2026-04-21T00:00:00+00:00",
            "headline": {
                "team_health": "warn",
                "runtime_health": "fail",
                "trace_events": 12,
                "tool_calls": 3,
                "failed_tool_calls": 1,
                "ready_tasks": 1,
                "background_runs": 0,
                "sessions": 1,
                "latest_session_id": "session-1",
                "replay_turns": 2,
            },
            "bundle": {
                "dashboard": {"tool_output_count": 0, "truncated_tool_output_count": 0, "memory_candidate_status_counts": {}},
                "doctor": {"summary": "FAIL", "findings": [], "summary_by_category": {}},
                "team_board": {
                    "team_status": {"status_counts": {"pending": 1}, "ready_tasks": [{"task_id": "task-1"}], "active_tasks": []},
                    "runtime_health": {"summary": "FAIL", "finding_count": 1},
                    "runtime_counts": {"context_builds": 2},
                    "background_runs": {"recent": []},
                },
                "session_replay": None,
            },
            "latest_session": {"session_id": "session-1", "name": "demo", "turn_count": 2},
            "latest_session_replay": {"completed_turns": 2, "successful_turns": 1, "failed_turns": 1, "tool_calls": 3},
        }
        text = render_terminal_home_tui(
            home,
            width=96,
            focus="runtime",
            changes=["- dashboard.trace.total_events: 10 -> 12"],
            changes_by_section={
                "dashboard": ["- trace.total_events: 10 -> 12"],
                "doctor": [],
                "team_board": ["- runtime_counts.trace_events: 10 -> 12"],
                "session_replay": [],
            },
            changes_by_section_delta={
                "dashboard": {"trace": {"total_events": {"previous": 10, "current": 12, "delta": 2}}},
                "doctor": {},
                "team_board": {"runtime_counts": {"trace_events": {"previous": 10, "current": 12, "delta": 2}}},
                "session_replay": {},
            },
            changes_only=False,
        )

        self.assertIn("Changes Since Last Refresh", text)
        self.assertIn("Runtime Counts *", text)
        self.assertIn("dashboard: 1 change(s)", text)

    def test_home_cli_watch_changes_only_can_render_tui_delta_view(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            graph = TaskGraph()
            graph.add(TaskNode(task_id="task-1", objective="ready task"))
            graph.save(root / ".mini_claw" / "task_graph.json")

            args = Namespace(
                workspace=str(root),
                session="",
                session_turn_limit=20,
                background_limit=5,
                tool_output_limit=5,
                watch=True,
                interval=0.0,
                iterations=2,
                no_clear=True,
                changes_only=True,
                style="tui",
                focus="runtime",
                width=96,
                ignore="",
                category="",
                severity_at_least="info",
                sort_by="default",
                output_file="",
                json=False,
            )
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = cmd_home(args)

            self.assertEqual(exit_code, 0)
            text = output.getvalue()
            self.assertIn("# Home Watch 2", text)
            self.assertIn("Changes Since Last Refresh", text)
            self.assertIn("(no home state changes detected)", text)
            self.assertEqual(text.count("Team Queue"), 1)

    def test_home_cli_can_collapse_tui_sections(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            graph = TaskGraph()
            graph.add(TaskNode(task_id="task-1", objective="ready task"))
            graph.save(root / ".mini_claw" / "task_graph.json")

            args = Namespace(
                workspace=str(root),
                session="",
                session_turn_limit=20,
                background_limit=5,
                tool_output_limit=5,
                watch=False,
                interval=0.0,
                iterations=0,
                no_clear=True,
                changes_only=False,
                style="tui",
                focus="runtime",
                width=96,
                collapse="team,background",
                ignore="",
                category="",
                severity_at_least="info",
                sort_by="default",
                output_file="",
                json=False,
            )
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = cmd_home(args)

            self.assertEqual(exit_code, 0)
            text = output.getvalue()
            self.assertIn("Team Queue [collapsed]", text)
            self.assertIn("Background Runs [collapsed]", text)
            self.assertIn("pending=1", text)

    def test_home_cli_can_apply_compact_preset(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            graph = TaskGraph()
            graph.add(TaskNode(task_id="task-1", objective="ready task"))
            graph.save(root / ".mini_claw" / "task_graph.json")

            args = Namespace(
                workspace=str(root),
                session="",
                session_turn_limit=20,
                background_limit=5,
                tool_output_limit=5,
                watch=False,
                interval=0.0,
                iterations=0,
                no_clear=True,
                changes_only=False,
                style="tui",
                preset="compact",
                focus="auto",
                width=108,
                collapse="",
                ignore="",
                category="",
                severity_at_least="info",
                sort_by="default",
                output_file="",
                json=False,
            )
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = cmd_home(args)

            self.assertEqual(exit_code, 0)
            text = output.getvalue()
            self.assertIn("preset: compact", text)
            self.assertIn("focus: runtime", text)
            self.assertIn("Team Queue [collapsed]", text)
            self.assertIn("Background Runs [collapsed]", text)

    def test_home_cli_explicit_focus_can_override_preset(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            graph = TaskGraph()
            graph.add(TaskNode(task_id="task-1", objective="ready task"))
            graph.save(root / ".mini_claw" / "task_graph.json")

            args = Namespace(
                workspace=str(root),
                session="",
                session_turn_limit=20,
                background_limit=5,
                tool_output_limit=5,
                watch=False,
                interval=0.0,
                iterations=0,
                no_clear=True,
                changes_only=False,
                style="tui",
                preset="compact",
                focus="team",
                width=108,
                collapse="",
                ignore="",
                category="",
                severity_at_least="info",
                sort_by="default",
                output_file="",
                json=False,
            )
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = cmd_home(args)

            self.assertEqual(exit_code, 0)
            text = output.getvalue()
            self.assertIn("preset: compact", text)
            self.assertIn("focus: team", text)

    def test_home_cli_compact_preset_defaults_to_delta_watch_layout(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            graph = TaskGraph()
            graph.add(TaskNode(task_id="task-1", objective="ready task"))
            graph.save(root / ".mini_claw" / "task_graph.json")

            args = Namespace(
                workspace=str(root),
                session="",
                session_turn_limit=20,
                background_limit=5,
                tool_output_limit=5,
                watch=True,
                interval=0.0,
                iterations=2,
                no_clear=True,
                changes_only=False,
                style="tui",
                preset="compact",
                watch_layout="default",
                focus="auto",
                width=108,
                collapse="",
                ignore="",
                category="",
                severity_at_least="info",
                sort_by="default",
                output_file="",
                json=False,
            )
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = cmd_home(args)

            self.assertEqual(exit_code, 0)
            text = output.getvalue()
            self.assertIn("# Home Watch 2", text)
            self.assertIn("Changes Since Last Refresh", text)
            self.assertEqual(text.count("Team Queue"), 1)

    def test_home_cli_watch_layout_full_can_override_compact_preset(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            graph = TaskGraph()
            graph.add(TaskNode(task_id="task-1", objective="ready task"))
            graph.save(root / ".mini_claw" / "task_graph.json")

            args = Namespace(
                workspace=str(root),
                session="",
                session_turn_limit=20,
                background_limit=5,
                tool_output_limit=5,
                watch=True,
                interval=0.0,
                iterations=2,
                no_clear=True,
                changes_only=False,
                style="tui",
                preset="compact",
                watch_layout="full",
                focus="auto",
                width=108,
                collapse="",
                ignore="",
                category="",
                severity_at_least="info",
                sort_by="default",
                output_file="",
                json=False,
            )
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = cmd_home(args)

            self.assertEqual(exit_code, 0)
            text = output.getvalue()
            self.assertIn("# Home Watch 2", text)
            self.assertGreaterEqual(text.count("Team Queue"), 2)

    def test_home_cli_ops_preset_defaults_to_full_watch_layout(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            graph = TaskGraph()
            graph.add(TaskNode(task_id="task-1", objective="ready task"))
            graph.save(root / ".mini_claw" / "task_graph.json")

            args = Namespace(
                workspace=str(root),
                session="",
                session_turn_limit=20,
                background_limit=5,
                tool_output_limit=5,
                watch=True,
                interval=0.0,
                iterations=2,
                no_clear=True,
                changes_only=False,
                style="tui",
                preset="ops",
                watch_layout="default",
                focus="auto",
                width=108,
                collapse="",
                ignore="",
                category="",
                severity_at_least="info",
                sort_by="default",
                output_file="",
                json=False,
            )
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = cmd_home(args)

            self.assertEqual(exit_code, 0)
            text = output.getvalue()
            self.assertIn("preset: ops", text)
            self.assertIn("# Home Watch 2", text)
            self.assertGreaterEqual(text.count("Runtime Health"), 2)

    def test_home_cli_interview_preset_collapses_changes_panel_in_watch(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            graph = TaskGraph()
            graph.add(TaskNode(task_id="task-1", objective="ready task"))
            graph.save(root / ".mini_claw" / "task_graph.json")

            args = Namespace(
                workspace=str(root),
                session="",
                session_turn_limit=20,
                background_limit=5,
                tool_output_limit=5,
                watch=True,
                interval=0.0,
                iterations=2,
                no_clear=True,
                changes_only=False,
                style="tui",
                preset="interview",
                watch_layout="default",
                focus="auto",
                width=108,
                collapse="",
                ignore="",
                category="",
                severity_at_least="info",
                sort_by="default",
                output_file="",
                json=False,
            )
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = cmd_home(args)

            self.assertEqual(exit_code, 0)
            text = output.getvalue()
            self.assertIn("preset: interview", text)
            self.assertIn("Changes Since Last Refresh [collapsed]", text)
            self.assertGreaterEqual(text.count("Team Queue"), 2)

    def test_home_cli_can_render_tui_demo_track(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            graph = TaskGraph()
            graph.add(TaskNode(task_id="task-1", objective="ready task"))
            graph.save(root / ".mini_claw" / "task_graph.json")

            args = Namespace(
                workspace=str(root),
                session="",
                session_turn_limit=20,
                background_limit=5,
                tool_output_limit=5,
                watch=False,
                interval=0.0,
                iterations=0,
                no_clear=True,
                changes_only=False,
                style="tui",
                preset="interview",
                watch_layout="default",
                focus="auto",
                width=108,
                collapse="",
                demo_mode=True,
                demo_language="en",
                demo_focus="auto",
                demo_script="short",
                ignore="",
                category="",
                severity_at_least="info",
                sort_by="default",
                output_file="",
                json=False,
            )
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = cmd_home(args)

            self.assertEqual(exit_code, 0)
            text = output.getvalue()
            self.assertIn("Demo Track", text)
            self.assertIn("This first screen is centered on the team control surface", text)
            self.assertIn("Right now the queue shows 1 ready tasks", text)

    def test_home_cli_can_render_tui_demo_track_in_zh(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            graph = TaskGraph()
            graph.add(TaskNode(task_id="task-1", objective="ready task"))
            graph.save(root / ".mini_claw" / "task_graph.json")

            args = Namespace(
                workspace=str(root),
                session="",
                session_turn_limit=20,
                background_limit=5,
                tool_output_limit=5,
                watch=False,
                interval=0.0,
                iterations=0,
                no_clear=True,
                changes_only=False,
                style="tui",
                preset="interview",
                watch_layout="default",
                focus="auto",
                width=108,
                collapse="",
                demo_mode=True,
                demo_language="zh",
                demo_focus="auto",
                demo_script="short",
                ignore="",
                category="",
                severity_at_least="info",
                sort_by="default",
                output_file="",
                json=False,
            )
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = cmd_home(args)

            self.assertEqual(exit_code, 0)
            text = output.getvalue()
            self.assertIn("Demo Track", text)
            self.assertIn("这个首页聚焦的是 team control surface", text)
            self.assertIn("当前队列里有 1 个 ready task", text)

    def test_home_cli_demo_focus_can_override_layout_focus(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            graph = TaskGraph()
            graph.add(TaskNode(task_id="task-1", objective="ready task"))
            graph.save(root / ".mini_claw" / "task_graph.json")

            args = Namespace(
                workspace=str(root),
                session="",
                session_turn_limit=20,
                background_limit=5,
                tool_output_limit=5,
                watch=False,
                interval=0.0,
                iterations=0,
                no_clear=True,
                changes_only=False,
                style="tui",
                preset="interview",
                watch_layout="default",
                focus="team",
                width=108,
                collapse="",
                demo_mode=True,
                demo_language="en",
                demo_focus="runtime",
                demo_script="short",
                ignore="",
                category="",
                severity_at_least="info",
                sort_by="default",
                output_file="",
                json=False,
            )
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = cmd_home(args)

            self.assertEqual(exit_code, 0)
            text = output.getvalue()
            self.assertIn("focus: team", text)
            self.assertIn("This first screen is centered on the runtime system", text)
