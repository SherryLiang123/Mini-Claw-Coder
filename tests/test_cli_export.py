import io
import json
import unittest
from argparse import Namespace
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

from mini_claw.agent.state import AgentResult
from mini_claw.cli import cmd_export
from mini_claw.memory.store import MemoryStore
from mini_claw.sessions.store import SessionManager
from mini_claw.tracing.events import RuntimeEvent


class ExportCliTest(unittest.TestCase):
    def test_export_dashboard_prints_json_snapshot(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            memory = MemoryStore(root / ".mini_claw" / "memory")
            memory.append_event(RuntimeEvent("task_started", {"task": "inspect repository"}))

            args = Namespace(
                export_target="dashboard",
                workspace=str(root),
                output_file="",
                session="",
                session_turn_limit=10,
                background_limit=5,
                tool_output_limit=5,
                watch=False,
                interval=2.0,
                iterations=0,
                changes_only=False,
                ignore="",
                category="",
                severity_at_least="info",
                sort_by="default",
            )
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                exit_code = cmd_export(args)

            self.assertEqual(exit_code, 0)
            payload = json.loads(buffer.getvalue())
            self.assertIn("trace_summary", payload)
            self.assertEqual(payload["trace_summary"]["total_events"], 1)

    def test_export_doctor_writes_filtered_json_to_file(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            output_path = root / "doctor-export.json"

            args = Namespace(
                export_target="doctor",
                workspace=str(root),
                output_file=str(output_path),
                session="",
                session_turn_limit=10,
                background_limit=5,
                tool_output_limit=5,
                watch=False,
                interval=2.0,
                iterations=0,
                changes_only=False,
                ignore="trace_missing",
                category="sessions",
                severity_at_least="info",
                sort_by="default",
            )
            with redirect_stdout(io.StringIO()):
                exit_code = cmd_export(args)

            self.assertEqual(exit_code, 0)
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "ok")
            self.assertEqual(set(payload["summary_by_category"].keys()), {"sessions"})
            self.assertTrue(all(item["category"] == "sessions" for item in payload["findings"]))

    def test_export_team_board_prints_team_surface_snapshot(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            args = Namespace(
                export_target="team-board",
                workspace=str(root),
                output_file="",
                session="",
                session_turn_limit=10,
                background_limit=5,
                tool_output_limit=5,
                watch=False,
                interval=2.0,
                iterations=0,
                changes_only=False,
                ignore="",
                category="",
                severity_at_least="info",
                sort_by="default",
            )
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                exit_code = cmd_export(args)

            self.assertEqual(exit_code, 0)
            payload = json.loads(buffer.getvalue())
            self.assertIn("team_status", payload)
            self.assertIn("runtime_health", payload)
            self.assertIn("background_runs", payload)

    def test_export_bundle_includes_dashboard_team_board_doctor_and_optional_session_replay(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            memory = MemoryStore(root / ".mini_claw" / "memory")
            memory.append_event(RuntimeEvent("task_started", {"task": "inspect repository"}))

            manager = SessionManager(root)
            session = manager.create(name="demo")
            turn = manager.begin_turn(session.session_id, "inspect repository")
            manager.complete_turn(
                session.session_id,
                turn.turn_id,
                result=AgentResult(
                    success=True,
                    final_answer="done",
                    steps=[],
                    modified_files=["README.md"],
                ),
                trace_lines=[
                    json.dumps({"event": "task_started", "payload": {"task": "inspect repository"}}, ensure_ascii=False)
                    + "\n"
                ],
            )

            args = Namespace(
                export_target="bundle",
                workspace=str(root),
                output_file="",
                session=session.session_id,
                session_turn_limit=10,
                background_limit=5,
                tool_output_limit=5,
                watch=False,
                interval=2.0,
                iterations=0,
                changes_only=False,
                ignore="",
                category="",
                severity_at_least="info",
                sort_by="default",
            )
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                exit_code = cmd_export(args)

            self.assertEqual(exit_code, 0)
            payload = json.loads(buffer.getvalue())
            self.assertEqual(set(payload.keys()), {"dashboard", "doctor", "team_board", "session_replay"})
            self.assertEqual(payload["dashboard"]["trace_summary"]["total_events"], 1)
            self.assertEqual(payload["doctor"]["status"], "ok")
            self.assertIn("team_status", payload["team_board"])
            self.assertIsNotNone(payload["session_replay"])
            self.assertEqual(payload["session_replay"]["total_turns"], 1)
            self.assertEqual(payload["session_replay"]["completed_turns"], 1)

    def test_export_bundle_watch_outputs_ndjson_snapshots(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            output_path = root / "bundle.ndjson"
            memory = MemoryStore(root / ".mini_claw" / "memory")
            memory.append_event(RuntimeEvent("task_started", {"task": "watch export"}))

            args = Namespace(
                export_target="bundle",
                workspace=str(root),
                output_file=str(output_path),
                session="",
                session_turn_limit=10,
                background_limit=5,
                tool_output_limit=5,
                watch=True,
                interval=0.0,
                iterations=2,
                changes_only=False,
                ignore="",
                category="",
                severity_at_least="info",
                sort_by="default",
            )
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                exit_code = cmd_export(args)

            self.assertEqual(exit_code, 0)
            lines = [line for line in buffer.getvalue().splitlines() if line.strip()]
            self.assertEqual(len(lines), 2)
            payloads = [json.loads(line) for line in lines]
            self.assertEqual([item["iteration"] for item in payloads], [1, 2])
            self.assertTrue(all(item["export_target"] == "bundle" for item in payloads))
            self.assertTrue(all("changes" in item for item in payloads))
            self.assertTrue(all("changes_by_section" in item for item in payloads))
            self.assertTrue(all("changes_by_section_delta" in item for item in payloads))
            self.assertTrue(all(set(item["changes_by_section"].keys()) == {"dashboard", "doctor", "team_board", "session_replay"} for item in payloads))
            self.assertTrue(all(set(item["changes_by_section_delta"].keys()) == {"dashboard", "doctor", "team_board", "session_replay"} for item in payloads))
            self.assertTrue(all("dashboard" in item["snapshot"] for item in payloads))
            self.assertTrue(all("team_board" in item["snapshot"] for item in payloads))
            written = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual(len(written), 2)
            self.assertEqual(written[0]["iteration"], 1)
            self.assertEqual(written[1]["iteration"], 2)

    def test_export_bundle_watch_changes_only_hides_snapshot_after_first_iteration(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            memory = MemoryStore(root / ".mini_claw" / "memory")
            memory.append_event(RuntimeEvent("task_started", {"task": "watch export"}))

            args = Namespace(
                export_target="bundle",
                workspace=str(root),
                output_file="",
                session="",
                session_turn_limit=10,
                background_limit=5,
                tool_output_limit=5,
                watch=True,
                interval=0.0,
                iterations=2,
                changes_only=True,
                ignore="",
                category="",
                severity_at_least="info",
                sort_by="default",
            )
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                exit_code = cmd_export(args)

            self.assertEqual(exit_code, 0)
            payloads = [json.loads(line) for line in buffer.getvalue().splitlines() if line.strip()]
            self.assertEqual(len(payloads), 2)
            self.assertIsNotNone(payloads[0]["snapshot"])
            self.assertIsNone(payloads[1]["snapshot"])
            self.assertEqual(payloads[1]["changes"], [])
            self.assertEqual(
                payloads[1]["changes_by_section"],
                {"dashboard": [], "doctor": [], "team_board": [], "session_replay": []},
            )
            self.assertEqual(
                set(payloads[1]["changes_by_section_delta"].keys()),
                {"dashboard", "doctor", "team_board", "session_replay"},
            )


if __name__ == "__main__":
    unittest.main()
