import io
import json
import unittest
from argparse import Namespace
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

from mini_claw.cli import cmd_orchestrate, cmd_team, cmd_workspace
from mini_claw.task_graph.graph import TaskGraph, TaskNode


class WorkspaceCliTest(unittest.TestCase):
    def test_workspace_create_attaches_to_task_graph(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            graph_path = root / ".mini_claw" / "task_graph.json"
            graph = TaskGraph()
            graph.add(TaskNode(task_id="task-1", objective="demo"))
            graph.save(graph_path)

            args = Namespace(
                workspace=str(root),
                workspace_command="create",
                task_id="task-1",
            )

            with redirect_stdout(io.StringIO()):
                exit_code = cmd_workspace(args)

            self.assertEqual(exit_code, 0)
            loaded = TaskGraph.load(graph_path)
            self.assertTrue(loaded.nodes["task-1"].workspace_path.endswith("task-1"))

    def test_workspace_merge_uses_task_verification_command(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            graph_path = root / ".mini_claw" / "task_graph.json"
            graph = TaskGraph()
            graph.add(
                TaskNode(
                    task_id="task-1",
                    objective="demo",
                    verification_command="python -c \"raise SystemExit(0)\"",
                )
            )
            graph.save(graph_path)

            create_args = Namespace(
                workspace=str(root),
                workspace_command="create",
                task_id="task-1",
            )
            with redirect_stdout(io.StringIO()):
                self.assertEqual(cmd_workspace(create_args), 0)

            task_root = root / ".mini_claw" / "task_workspaces" / "task-1"
            (task_root / "app.py").write_text("VALUE = 2\n", encoding="utf-8")

            merge_args = Namespace(
                workspace=str(root),
                workspace_command="merge",
                task_id="task-1",
                verify=[],
                skip_task_verify=False,
                rollback_on_verification_failure=False,
                dry_run=False,
                show_diff=False,
            )

            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = cmd_workspace(merge_args)

            self.assertEqual(exit_code, 0)
            self.assertIn("verification_passed=1", output.getvalue())
            self.assertEqual((root / "app.py").read_text(encoding="utf-8"), "VALUE = 2\n")

    def test_orchestrate_cli_runs_minimal_role_flow(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            graph_path = root / ".mini_claw" / "task_graph.json"
            graph = TaskGraph()
            graph.add(
                TaskNode(
                    task_id="task-1",
                    objective="demo",
                    verification_command="python -c \"raise SystemExit(0)\"",
                )
            )
            graph.save(graph_path)

            create_args = Namespace(
                workspace=str(root),
                workspace_command="create",
                task_id="task-1",
                mode="copy",
            )
            with redirect_stdout(io.StringIO()):
                self.assertEqual(cmd_workspace(create_args), 0)

            task_root = root / ".mini_claw" / "task_workspaces" / "task-1"
            (task_root / "app.py").write_text("VALUE = 3\n", encoding="utf-8")

            args = Namespace(
                workspace=str(root),
                mode="copy",
                limit=1,
                dry_run=False,
                rollback_on_verification_failure=False,
                run_coder_agent=False,
            )
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = cmd_orchestrate(args)

            self.assertEqual(exit_code, 0)
            text = output.getvalue()
            self.assertIn("[planner] ok", text)
            self.assertIn("[coder] ok", text)
            self.assertIn("[tester] ok", text)
            self.assertIn("[integrator] ok", text)
            loaded = TaskGraph.load(graph_path)
            self.assertEqual(loaded.nodes["task-1"].status, "done")
            self.assertEqual((root / "app.py").read_text(encoding="utf-8"), "VALUE = 3\n")

    def test_orchestrate_cli_can_run_mock_coder_agent(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            graph_path = root / ".mini_claw" / "task_graph.json"
            graph = TaskGraph()
            graph.add(
                TaskNode(
                    task_id="task-1",
                    objective="inspect workspace",
                    verification_command="python -c \"raise SystemExit(0)\"",
                )
            )
            graph.save(graph_path)

            args = Namespace(
                workspace=str(root),
                mode="copy",
                limit=1,
                dry_run=False,
                rollback_on_verification_failure=False,
                run_coder_agent=True,
                provider="mock",
                model="mock-coder",
                routing_policy="signal-aware",
                max_steps=3,
                timeout=30,
                enforce_read_before_write=False,
            )
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = cmd_orchestrate(args)

            self.assertEqual(exit_code, 0)
            text = output.getvalue()
            self.assertIn("Mock run completed", text)
            loaded = TaskGraph.load(graph_path)
            self.assertEqual(loaded.nodes["task-1"].status, "done")

    def test_team_status_cli_summarizes_ready_and_blocked_tasks(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            graph_path = root / ".mini_claw" / "task_graph.json"
            graph = TaskGraph()
            graph.add(TaskNode(task_id="task-1", objective="ready task"))
            graph.add(
                TaskNode(
                    task_id="task-2",
                    objective="blocked task",
                    status="blocked",
                    dependencies=["task-1"],
                    notes="waiting for review",
                )
            )
            graph.save(graph_path)

            args = Namespace(
                workspace=str(root),
                team_command="status",
                json=False,
            )
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = cmd_team(args)

            self.assertEqual(exit_code, 0)
            text = output.getvalue()
            self.assertIn("# Mini Claw Team Status", text)
            self.assertIn("task-1: ready task", text)
            self.assertIn("task-2 deps=task-1 notes=waiting for review", text)

    def test_team_board_cli_renders_combined_control_surface(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            graph_path = root / ".mini_claw" / "task_graph.json"
            graph = TaskGraph()
            graph.add(TaskNode(task_id="task-1", objective="ready task"))
            graph.save(graph_path)

            args = Namespace(
                workspace=str(root),
                team_command="board",
                session="",
                session_turn_limit=20,
                background_limit=5,
                tool_output_limit=5,
                json=False,
            )
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = cmd_team(args)

            self.assertEqual(exit_code, 0)
            text = output.getvalue()
            self.assertIn("# Mini Claw Team Board", text)
            self.assertIn("## Team Queue", text)
            self.assertIn("## Runtime Health", text)
            self.assertIn("## Latest Session", text)

    def test_team_board_cli_can_emit_json(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            graph_path = root / ".mini_claw" / "task_graph.json"
            graph = TaskGraph()
            graph.add(TaskNode(task_id="task-1", objective="ready task"))
            graph.save(graph_path)

            args = Namespace(
                workspace=str(root),
                team_command="board",
                session="",
                session_turn_limit=20,
                background_limit=5,
                tool_output_limit=5,
                json=True,
            )
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = cmd_team(args)

            self.assertEqual(exit_code, 0)
            payload = output.getvalue()
            self.assertIn("\"team_status\"", payload)
            self.assertIn("\"runtime_health\"", payload)
            self.assertIn("\"background_runs\"", payload)

    def test_team_board_watch_cli_supports_changes_only_text_mode(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            graph_path = root / ".mini_claw" / "task_graph.json"
            graph = TaskGraph()
            graph.add(TaskNode(task_id="task-1", objective="ready task"))
            graph.save(graph_path)

            args = Namespace(
                workspace=str(root),
                team_command="board",
                session="",
                session_turn_limit=20,
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
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = cmd_team(args)

            self.assertEqual(exit_code, 0)
            text = output.getvalue()
            self.assertIn("# Team Board Watch 1", text)
            self.assertIn("# Team Board Watch 2", text)
            self.assertIn("(no team board changes to display)", text)

    def test_team_board_watch_cli_supports_json_mode(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            graph_path = root / ".mini_claw" / "task_graph.json"
            graph = TaskGraph()
            graph.add(TaskNode(task_id="task-1", objective="ready task"))
            graph.save(graph_path)

            args = Namespace(
                workspace=str(root),
                team_command="board",
                session="",
                session_turn_limit=20,
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
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = cmd_team(args)

            self.assertEqual(exit_code, 0)
            lines = [line for line in output.getvalue().splitlines() if line.strip()]
            self.assertEqual(len(lines), 2)
            self.assertIn("\"iteration\": 1", lines[0])
            self.assertIn("\"changes\": []", lines[0])
            self.assertIn("\"changes_by_section\"", lines[0])
            self.assertIn("\"changes_by_section_delta\"", lines[0])
            self.assertIn("\"iteration\": 2", lines[1])
            self.assertIn("\"board\"", lines[1])
            self.assertIn("\"team_status\"", lines[1])

    def test_team_board_cli_can_write_json_output_file(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            graph_path = root / ".mini_claw" / "task_graph.json"
            graph = TaskGraph()
            graph.add(TaskNode(task_id="task-1", objective="ready task"))
            graph.save(graph_path)

            args = Namespace(
                workspace=str(root),
                team_command="board",
                session="",
                session_turn_limit=20,
                background_limit=5,
                tool_output_limit=5,
                watch=False,
                interval=0.0,
                iterations=0,
                no_clear=True,
                changes_only=False,
                output_file=".mini_claw/team_board.json",
                json=True,
            )
            with redirect_stdout(io.StringIO()):
                exit_code = cmd_team(args)

            self.assertEqual(exit_code, 0)
            payload = json.loads((root / ".mini_claw" / "team_board.json").read_text(encoding="utf-8"))
            self.assertIn("team_status", payload)
            self.assertIn("runtime_health", payload)

    def test_team_board_watch_cli_can_write_ndjson_output_file(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            graph_path = root / ".mini_claw" / "task_graph.json"
            graph = TaskGraph()
            graph.add(TaskNode(task_id="task-1", objective="ready task"))
            graph.save(graph_path)

            args = Namespace(
                workspace=str(root),
                team_command="board",
                session="",
                session_turn_limit=20,
                background_limit=5,
                tool_output_limit=5,
                watch=True,
                interval=0.0,
                iterations=2,
                no_clear=True,
                changes_only=False,
                output_file=".mini_claw/team_board.ndjson",
                json=True,
            )
            with redirect_stdout(io.StringIO()):
                exit_code = cmd_team(args)

            self.assertEqual(exit_code, 0)
            lines = [
                line
                for line in (root / ".mini_claw" / "team_board.ndjson").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertEqual(len(lines), 2)
            first = json.loads(lines[0])
            second = json.loads(lines[1])
            self.assertEqual(first["iteration"], 1)
            self.assertEqual(second["iteration"], 2)

    def test_team_run_cli_renders_user_facing_team_summary(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            graph_path = root / ".mini_claw" / "task_graph.json"
            graph = TaskGraph()
            graph.add(
                TaskNode(
                    task_id="task-1",
                    objective="demo",
                    verification_command="python -c \"raise SystemExit(0)\"",
                )
            )
            graph.save(graph_path)

            create_args = Namespace(
                workspace=str(root),
                workspace_command="create",
                task_id="task-1",
                mode="copy",
            )
            with redirect_stdout(io.StringIO()):
                self.assertEqual(cmd_workspace(create_args), 0)

            task_root = root / ".mini_claw" / "task_workspaces" / "task-1"
            (task_root / "app.py").write_text("VALUE = 4\n", encoding="utf-8")

            args = Namespace(
                workspace=str(root),
                team_command="run",
                mode="copy",
                limit=1,
                dry_run=False,
                rollback_on_verification_failure=False,
                run_coder_agent=False,
                provider="mock",
                model="mock-coder",
                routing_policy="signal-aware",
                max_steps=3,
                timeout=30,
                enforce_read_before_write=False,
                json=False,
            )
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = cmd_team(args)

            self.assertEqual(exit_code, 0)
            text = output.getvalue()
            self.assertIn("# Mini Claw Team Run", text)
            self.assertIn("## Handoff Flow", text)
            self.assertIn("ready_before: task-1", text)
            loaded = TaskGraph.load(graph_path)
            self.assertEqual(loaded.nodes["task-1"].status, "done")


if __name__ == "__main__":
    unittest.main()
