import io
import json
import unittest
from argparse import Namespace
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

from mini_claw.cli import cmd_doctor
from mini_claw.dashboard import build_runtime_dashboard
from mini_claw.doctor import run_runtime_doctor, summarize_doctor_category_delta
from mini_claw.memory.store import MemoryStore
from mini_claw.tracing.events import RuntimeEvent


class DoctorCliTest(unittest.TestCase):
    def test_doctor_cli_prints_runtime_health_report(self) -> None:
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
                strict_warnings=False,
                watch=False,
                interval=2.0,
                iterations=0,
                no_clear=False,
                changes_only=False,
                summary_only=False,
                fail_on="",
                ignore="",
                category="",
                severity_at_least="info",
                sort_by="default",
                output_file="",
                json=False,
            )
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                exit_code = cmd_doctor(args)

            self.assertEqual(exit_code, 0)
            output = buffer.getvalue()
            self.assertIn("# Mini Claw Runtime Doctor", output)
            self.assertIn("status: ok", output)
            self.assertIn("session_missing", output)

    def test_doctor_cli_supports_json_output_and_warning_exit_code(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)

            args = Namespace(
                workspace=str(root),
                session="",
                session_turn_limit=10,
                background_limit=5,
                tool_output_limit=5,
                strict_warnings=True,
                watch=False,
                interval=2.0,
                iterations=0,
                no_clear=False,
                changes_only=False,
                summary_only=False,
                fail_on="",
                ignore="",
                category="",
                severity_at_least="info",
                sort_by="default",
                output_file="",
                json=True,
            )
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                exit_code = cmd_doctor(args)

            self.assertEqual(exit_code, 1)
            payload = json.loads(buffer.getvalue())
            self.assertEqual(payload["status"], "warn")
            self.assertTrue(any(item["code"] == "trace_missing" for item in payload["findings"]))
            self.assertTrue(all("category" in item for item in payload["findings"]))
            self.assertIn("summary_by_category", payload)
            self.assertIn("trace", payload["summary_by_category"])

    def test_doctor_cli_watch_mode_runs_multiple_iterations(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)

            args = Namespace(
                workspace=str(root),
                session="",
                session_turn_limit=10,
                background_limit=5,
                tool_output_limit=5,
                strict_warnings=False,
                watch=True,
                interval=0.0,
                iterations=2,
                no_clear=True,
                changes_only=False,
                summary_only=False,
                fail_on="",
                ignore="",
                category="",
                severity_at_least="info",
                sort_by="default",
                output_file="",
                json=False,
            )
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                exit_code = cmd_doctor(args)

            self.assertEqual(exit_code, 0)
            output = buffer.getvalue()
            self.assertIn("# Doctor Watch 1", output)
            self.assertIn("# Doctor Watch 2", output)
            self.assertIn("## Changes Since Last Refresh", output)
            self.assertIn("- no doctor state changes detected", output)

    def test_doctor_cli_watch_json_outputs_one_object_per_iteration(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)

            args = Namespace(
                workspace=str(root),
                session="",
                session_turn_limit=10,
                background_limit=5,
                tool_output_limit=5,
                strict_warnings=True,
                watch=True,
                interval=0.0,
                iterations=2,
                no_clear=True,
                changes_only=False,
                summary_only=False,
                fail_on="",
                ignore="",
                category="",
                severity_at_least="info",
                sort_by="default",
                output_file="",
                json=True,
            )
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                exit_code = cmd_doctor(args)

            self.assertEqual(exit_code, 1)
            rows = [json.loads(line) for line in buffer.getvalue().splitlines() if line.strip()]
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["iteration"], 1)
            self.assertEqual(rows[1]["iteration"], 2)
            self.assertEqual(rows[0]["exit_code"], 1)
            self.assertEqual(rows[1]["changes"], [])
            self.assertIn("summary_by_category_delta", rows[0])
            self.assertEqual(rows[0]["summary_by_category_delta"], {})
            self.assertEqual(rows[1]["summary_by_category_delta"], {})

    def test_doctor_cli_summary_only_prints_summary_line(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)

            args = Namespace(
                workspace=str(root),
                session="",
                session_turn_limit=10,
                background_limit=5,
                tool_output_limit=5,
                strict_warnings=False,
                watch=False,
                interval=2.0,
                iterations=0,
                no_clear=False,
                changes_only=False,
                summary_only=True,
                fail_on="",
                ignore="",
                category="",
                severity_at_least="info",
                sort_by="default",
                output_file="",
                json=False,
            )
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                exit_code = cmd_doctor(args)

            self.assertEqual(exit_code, 0)
            output = buffer.getvalue().strip()
            self.assertTrue(output.startswith("WARN with"))
            self.assertNotIn("# Mini Claw Runtime Doctor", output)

    def test_doctor_cli_watch_changes_only_hides_full_report_after_first_refresh(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)

            args = Namespace(
                workspace=str(root),
                session="",
                session_turn_limit=10,
                background_limit=5,
                tool_output_limit=5,
                strict_warnings=False,
                watch=True,
                interval=0.0,
                iterations=2,
                no_clear=True,
                changes_only=True,
                summary_only=False,
                fail_on="",
                ignore="",
                category="",
                severity_at_least="info",
                sort_by="default",
                output_file="",
                json=False,
            )
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                exit_code = cmd_doctor(args)

            self.assertEqual(exit_code, 0)
            output = buffer.getvalue()
            self.assertIn("# Doctor Watch 1", output)
            self.assertIn("# Doctor Watch 2", output)
            self.assertIn("(no doctor changes to display)", output)
            self.assertEqual(output.count("# Mini Claw Runtime Doctor"), 1)

    def test_doctor_cli_watch_summary_only_prints_summary_each_refresh(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)

            args = Namespace(
                workspace=str(root),
                session="",
                session_turn_limit=10,
                background_limit=5,
                tool_output_limit=5,
                strict_warnings=False,
                watch=True,
                interval=0.0,
                iterations=2,
                no_clear=True,
                changes_only=False,
                summary_only=True,
                fail_on="",
                ignore="",
                category="",
                severity_at_least="info",
                sort_by="default",
                output_file="",
                json=False,
            )
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                exit_code = cmd_doctor(args)

            self.assertEqual(exit_code, 0)
            output = buffer.getvalue()
            self.assertGreaterEqual(output.count("WARN with 0 fail, 1 warn"), 2)
            self.assertNotIn("# Mini Claw Runtime Doctor", output)

    def test_doctor_cli_fail_on_promotes_selected_code_to_failure(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)

            args = Namespace(
                workspace=str(root),
                session="",
                session_turn_limit=10,
                background_limit=5,
                tool_output_limit=5,
                strict_warnings=False,
                watch=False,
                interval=2.0,
                iterations=0,
                no_clear=False,
                changes_only=False,
                summary_only=True,
                fail_on="trace_missing",
                ignore="",
                category="",
                severity_at_least="info",
                sort_by="default",
                output_file="",
                json=False,
            )
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                exit_code = cmd_doctor(args)

            self.assertEqual(exit_code, 1)
            self.assertTrue(buffer.getvalue().strip().startswith("WARN with"))

    def test_doctor_cli_watch_json_includes_fail_on_exit_code(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)

            args = Namespace(
                workspace=str(root),
                session="",
                session_turn_limit=10,
                background_limit=5,
                tool_output_limit=5,
                strict_warnings=False,
                watch=True,
                interval=0.0,
                iterations=2,
                no_clear=True,
                changes_only=False,
                summary_only=False,
                fail_on="trace_missing",
                ignore="",
                category="",
                severity_at_least="info",
                sort_by="default",
                output_file="",
                json=True,
            )
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                exit_code = cmd_doctor(args)

            self.assertEqual(exit_code, 1)
            rows = [json.loads(line) for line in buffer.getvalue().splitlines() if line.strip()]
            self.assertEqual(rows[0]["exit_code"], 1)
            self.assertEqual(rows[1]["exit_code"], 1)

    def test_doctor_cli_ignore_removes_selected_code_from_output_and_exit(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)

            args = Namespace(
                workspace=str(root),
                session="",
                session_turn_limit=10,
                background_limit=5,
                tool_output_limit=5,
                strict_warnings=False,
                watch=False,
                interval=2.0,
                iterations=0,
                no_clear=False,
                changes_only=False,
                summary_only=False,
                fail_on="",
                ignore="trace_missing",
                category="",
                severity_at_least="info",
                sort_by="default",
                output_file="",
                json=False,
            )
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                exit_code = cmd_doctor(args)

            self.assertEqual(exit_code, 0)
            output = buffer.getvalue()
            self.assertNotIn("trace_missing", output)
            self.assertIn("session_missing", output)
            self.assertIn("status: ok", output)

    def test_doctor_cli_ignore_can_neutralize_fail_on_code(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)

            args = Namespace(
                workspace=str(root),
                session="",
                session_turn_limit=10,
                background_limit=5,
                tool_output_limit=5,
                strict_warnings=False,
                watch=False,
                interval=2.0,
                iterations=0,
                no_clear=False,
                changes_only=False,
                summary_only=True,
                fail_on="trace_missing",
                ignore="trace_missing",
                category="",
                severity_at_least="info",
                sort_by="default",
                output_file="",
                json=False,
            )
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                exit_code = cmd_doctor(args)

            self.assertEqual(exit_code, 0)
            self.assertTrue(buffer.getvalue().strip().startswith("OK with"))

    def test_doctor_cli_severity_at_least_filters_lower_severity_findings(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)

            args = Namespace(
                workspace=str(root),
                session="",
                session_turn_limit=10,
                background_limit=5,
                tool_output_limit=5,
                strict_warnings=False,
                watch=False,
                interval=2.0,
                iterations=0,
                no_clear=False,
                changes_only=False,
                summary_only=False,
                fail_on="",
                ignore="",
                category="",
                severity_at_least="fail",
                sort_by="default",
                output_file="",
                json=False,
            )
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                exit_code = cmd_doctor(args)

            self.assertEqual(exit_code, 0)
            output = buffer.getvalue()
            self.assertIn("status: ok", output)
            self.assertIn("## Findings", output)
            self.assertIn("- none", output)

    def test_doctor_cli_severity_at_least_warn_preserves_warning_summary(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)

            args = Namespace(
                workspace=str(root),
                session="",
                session_turn_limit=10,
                background_limit=5,
                tool_output_limit=5,
                strict_warnings=False,
                watch=False,
                interval=2.0,
                iterations=0,
                no_clear=False,
                changes_only=False,
                summary_only=True,
                fail_on="",
                ignore="",
                category="",
                severity_at_least="warn",
                sort_by="default",
                output_file="",
                json=False,
            )
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                exit_code = cmd_doctor(args)

            self.assertEqual(exit_code, 0)
            self.assertEqual(buffer.getvalue().strip(), "WARN with 0 fail, 1 warn, and 0 info finding(s).")

    def test_doctor_cli_category_filter_keeps_only_selected_categories(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)

            args = Namespace(
                workspace=str(root),
                session="",
                session_turn_limit=10,
                background_limit=5,
                tool_output_limit=5,
                strict_warnings=False,
                watch=False,
                interval=2.0,
                iterations=0,
                no_clear=False,
                changes_only=False,
                summary_only=False,
                fail_on="",
                ignore="",
                category="sessions",
                severity_at_least="info",
                sort_by="default",
                output_file="",
                json=False,
            )
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                exit_code = cmd_doctor(args)

            self.assertEqual(exit_code, 0)
            output = buffer.getvalue()
            self.assertIn("sessions/session_missing", output)
            self.assertNotIn("trace/trace_missing", output)
            self.assertIn("- sessions: fail=0 warn=0 info=1", output)

    def test_doctor_cli_category_filter_shapes_json_summary(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)

            args = Namespace(
                workspace=str(root),
                session="",
                session_turn_limit=10,
                background_limit=5,
                tool_output_limit=5,
                strict_warnings=False,
                watch=False,
                interval=2.0,
                iterations=0,
                no_clear=False,
                changes_only=False,
                summary_only=False,
                fail_on="",
                ignore="",
                category="trace",
                severity_at_least="info",
                sort_by="default",
                output_file="",
                json=True,
            )
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                exit_code = cmd_doctor(args)

            self.assertEqual(exit_code, 0)
            payload = json.loads(buffer.getvalue())
            self.assertEqual(set(payload["summary_by_category"].keys()), {"trace"})
            self.assertTrue(all(item["category"] == "trace" for item in payload["findings"]))

    def test_doctor_cli_sort_by_severity_orders_fail_before_info(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            memory = MemoryStore(root / ".mini_claw" / "memory")
            memory.append_event(RuntimeEvent("tool_call", {"tool": "shell", "ok": False, "metadata": {}}))

            args = Namespace(
                workspace=str(root),
                session="",
                session_turn_limit=10,
                background_limit=5,
                tool_output_limit=5,
                strict_warnings=False,
                watch=False,
                interval=2.0,
                iterations=0,
                no_clear=False,
                changes_only=False,
                summary_only=False,
                fail_on="",
                ignore="",
                category="",
                severity_at_least="info",
                sort_by="severity",
                output_file="",
                json=True,
            )
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                exit_code = cmd_doctor(args)

            self.assertEqual(exit_code, 1)
            payload = json.loads(buffer.getvalue())
            self.assertEqual(payload["findings"][0]["severity"], "fail")
            self.assertEqual(payload["findings"][-1]["severity"], "info")

    def test_doctor_cli_sort_by_code_orders_findings_lexicographically(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            memory = MemoryStore(root / ".mini_claw" / "memory")
            memory.append_event(RuntimeEvent("tool_call", {"tool": "shell", "ok": False, "metadata": {}}))

            args = Namespace(
                workspace=str(root),
                session="",
                session_turn_limit=10,
                background_limit=5,
                tool_output_limit=5,
                strict_warnings=False,
                watch=False,
                interval=2.0,
                iterations=0,
                no_clear=False,
                changes_only=False,
                summary_only=False,
                fail_on="",
                ignore="",
                category="",
                severity_at_least="info",
                sort_by="code",
                output_file="",
                json=True,
            )
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                exit_code = cmd_doctor(args)

            self.assertEqual(exit_code, 1)
            payload = json.loads(buffer.getvalue())
            codes = [item["code"] for item in payload["findings"]]
            self.assertEqual(codes, sorted(codes))

    def test_doctor_cli_watch_json_reports_category_delta_when_state_changes(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            memory = MemoryStore(root / ".mini_claw" / "memory")
            memory.append_event(RuntimeEvent("task_finished", {"success": True}))
            first_report = run_runtime_doctor(build_runtime_dashboard(root))

            memory.append_event(RuntimeEvent("tool_call", {"tool": "shell", "ok": False, "metadata": {}}))
            second_report = run_runtime_doctor(build_runtime_dashboard(root))

            delta = summarize_doctor_category_delta(first_report, second_report)

            self.assertIn("trace", delta)
            self.assertEqual(delta["trace"]["fail"], 1)
            self.assertEqual(delta["trace"]["warn"], 0)
            self.assertEqual(delta["trace"]["info"], 0)

    def test_doctor_cli_json_can_write_output_file(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            output_path = root / "doctor.json"

            args = Namespace(
                workspace=str(root),
                session="",
                session_turn_limit=10,
                background_limit=5,
                tool_output_limit=5,
                strict_warnings=True,
                watch=False,
                interval=2.0,
                iterations=0,
                no_clear=False,
                changes_only=False,
                summary_only=False,
                fail_on="",
                ignore="",
                category="",
                severity_at_least="info",
                sort_by="default",
                output_file=str(output_path),
                json=True,
            )
            with redirect_stdout(io.StringIO()):
                exit_code = cmd_doctor(args)

            self.assertEqual(exit_code, 1)
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertIn("status", payload)
            self.assertIn("findings", payload)

    def test_doctor_cli_watch_json_can_append_ndjson_output_file(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            output_path = root / "doctor.ndjson"

            args = Namespace(
                workspace=str(root),
                session="",
                session_turn_limit=10,
                background_limit=5,
                tool_output_limit=5,
                strict_warnings=True,
                watch=True,
                interval=0.0,
                iterations=2,
                no_clear=True,
                changes_only=False,
                summary_only=False,
                fail_on="",
                ignore="",
                category="",
                severity_at_least="info",
                sort_by="default",
                output_file=str(output_path),
                json=True,
            )
            with redirect_stdout(io.StringIO()):
                exit_code = cmd_doctor(args)

            self.assertEqual(exit_code, 1)
            rows = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["iteration"], 1)
            self.assertEqual(rows[1]["iteration"], 2)


if __name__ == "__main__":
    unittest.main()
