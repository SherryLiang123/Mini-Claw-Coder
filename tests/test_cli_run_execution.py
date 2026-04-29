import io
import json
import shutil
import subprocess
import unittest
from argparse import Namespace
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

from mini_claw.cli import cmd_run
from mini_claw.cli import make_parser
from mini_claw.sessions.store import SessionManager


class RunExecutionCliTest(unittest.TestCase):
    def test_run_parser_defaults_to_copy_execution_mode(self) -> None:
        parser = make_parser()
        args = parser.parse_args(["run", "inspect this repository"])

        self.assertEqual(args.execution_mode, "copy")

    def test_run_can_use_copy_execution_workspace_and_persist_session_metadata(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")

            session_manager = SessionManager(root)
            session = session_manager.create(name="copy-run")

            args = Namespace(
                task="inspect this repository",
                workspace=str(root),
                provider="mock",
                model="mock-coder",
                routing_policy="signal-aware",
                max_steps=3,
                timeout=30,
                dry_run=False,
                enforce_read_before_write=False,
                session=session.session_id,
                execution_mode="copy",
                execution_id="run-copy",
            )
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = cmd_run(args)

            self.assertEqual(exit_code, 0)
            text = output.getvalue()
            self.assertIn("[execution] mode=copy task_id=run-copy", text)
            self.assertIn("Mock run completed", text)
            self.assertTrue((root / ".mini_claw" / "task_workspaces" / "run-copy" / "app.py").exists())

            turns = session_manager.list_turns(session.session_id, limit=5)
            self.assertEqual(len(turns), 1)
            self.assertEqual(turns[0].execution_mode, "copy")
            self.assertEqual(turns[0].execution_task_id, "run-copy")
            self.assertTrue(turns[0].execution_workspace.endswith("run-copy"))

            context_preview = session_manager.build_context(session.session_id)
            self.assertIn("execution_mode: copy", context_preview)
            self.assertIn("execution_task_id: run-copy", context_preview)

            trace_rows = [
                json.loads(line)
                for line in (root / ".mini_claw" / "memory" / "task_trace.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            task_started = next(row for row in trace_rows if row.get("event") == "task_started")
            self.assertEqual(task_started["payload"]["execution_mode"], "copy")
            self.assertEqual(task_started["payload"]["execution_task_id"], "run-copy")

    def test_run_prints_follow_up_commands_for_unmerged_isolated_changes(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")

            args = Namespace(
                task="inspect this repository",
                workspace=str(root),
                provider="mock",
                model="mock-coder",
                routing_policy="signal-aware",
                max_steps=3,
                timeout=30,
                dry_run=False,
                enforce_read_before_write=False,
                session="",
                execution_mode="copy",
                execution_id="run-copy",
                show_execution_diff=False,
                merge_back=False,
                merge_verify=[],
                rollback_on_merge_verification_failure=False,
            )
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = cmd_run(args)

            self.assertEqual(exit_code, 0)
            text = output.getvalue()
            self.assertIn(
                "[execution-next] review diff: python -m mini_claw workspace diff run-copy",
                text,
            )
            self.assertIn(
                "[execution-next] merge approved changes: python -m mini_claw workspace merge run-copy",
                text,
            )

    def test_run_git_worktree_mode_reports_clear_error_when_workspace_is_not_git(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            args = Namespace(
                task="inspect this repository",
                workspace=str(root),
                provider="mock",
                model="mock-coder",
                routing_policy="signal-aware",
                max_steps=3,
                timeout=30,
                dry_run=False,
                enforce_read_before_write=False,
                session="",
                execution_mode="git-worktree",
                execution_id="run-worktree",
            )

            stdout = io.StringIO()
            stderr = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                exit_code = cmd_run(args)

            self.assertEqual(exit_code, 1)
            self.assertIn("git repository", stderr.getvalue())

    def test_run_can_use_git_worktree_execution_workspace_when_git_repo_exists(self) -> None:
        if shutil.which("git") is None:
            self.skipTest("git is not available")
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True, text=True)
            subprocess.run(["git", "add", "app.py"], cwd=root, check=True, capture_output=True, text=True)
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=Mini Claw",
                    "-c",
                    "user.email=mini@example.com",
                    "commit",
                    "-m",
                    "init",
                ],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            )

            args = Namespace(
                task="inspect this repository",
                workspace=str(root),
                provider="mock",
                model="mock-coder",
                routing_policy="signal-aware",
                max_steps=3,
                timeout=30,
                dry_run=False,
                enforce_read_before_write=False,
                session="",
                execution_mode="git-worktree",
                execution_id="run-worktree",
            )
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = cmd_run(args)

            self.assertEqual(exit_code, 0)
            self.assertIn("[execution] mode=git-worktree task_id=run-worktree", output.getvalue())
            self.assertTrue((root / ".mini_claw" / "task_worktrees" / "run-worktree" / "app.py").exists())

    def test_run_can_show_execution_diff_for_isolated_workspace(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")

            isolated = root / ".mini_claw" / "task_workspaces" / "run-copy"
            isolated.mkdir(parents=True, exist_ok=True)
            manager = SessionManager(root)
            manager.create(name="diff-run")

            from mini_claw.task_graph.workspace import TaskWorkspaceManager

            workspace_manager = TaskWorkspaceManager(root)
            workspace_manager.create("run-copy", mode="copy")
            (isolated / "app.py").write_text("VALUE = 2\n", encoding="utf-8")

            args = Namespace(
                task="inspect this repository",
                workspace=str(root),
                provider="mock",
                model="mock-coder",
                routing_policy="signal-aware",
                max_steps=3,
                timeout=30,
                dry_run=False,
                enforce_read_before_write=False,
                session="",
                execution_mode="copy",
                execution_id="run-copy",
                show_execution_diff=True,
                merge_back=False,
                merge_verify=[],
                rollback_on_merge_verification_failure=False,
            )
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = cmd_run(args)

            self.assertEqual(exit_code, 0)
            self.assertIn("[execution-diff] app.py [modified] +1/-1", output.getvalue())

    def test_run_can_merge_back_isolated_changes(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")

            from mini_claw.task_graph.workspace import TaskWorkspaceManager

            workspace_manager = TaskWorkspaceManager(root)
            workspace_manager.create("run-copy", mode="copy")
            isolated = root / ".mini_claw" / "task_workspaces" / "run-copy"
            (isolated / "app.py").write_text("VALUE = 2\n", encoding="utf-8")

            args = Namespace(
                task="inspect this repository",
                workspace=str(root),
                provider="mock",
                model="mock-coder",
                routing_policy="signal-aware",
                max_steps=3,
                timeout=30,
                dry_run=False,
                enforce_read_before_write=False,
                session="",
                execution_mode="copy",
                execution_id="run-copy",
                show_execution_diff=False,
                merge_back=True,
                merge_verify=[],
                rollback_on_merge_verification_failure=False,
            )
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = cmd_run(args)

            self.assertEqual(exit_code, 0)
            self.assertIn("[merge-back] merged run-copy:", output.getvalue())
            self.assertIn("[merge-back-files] app.py", output.getvalue())
            self.assertEqual((root / "app.py").read_text(encoding="utf-8"), "VALUE = 2\n")

    def test_run_reports_merge_back_failure_in_final_answer(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")

            from mini_claw.task_graph.workspace import TaskWorkspaceManager

            workspace_manager = TaskWorkspaceManager(root)
            workspace_manager.create("run-copy", mode="copy")
            isolated = root / ".mini_claw" / "task_workspaces" / "run-copy"
            (isolated / "app.py").write_text("VALUE = 2\n", encoding="utf-8")

            args = Namespace(
                task="inspect this repository",
                workspace=str(root),
                provider="mock",
                model="mock-coder",
                routing_policy="signal-aware",
                max_steps=3,
                timeout=30,
                dry_run=False,
                enforce_read_before_write=False,
                session="",
                execution_mode="copy",
                execution_id="run-copy",
                show_execution_diff=False,
                merge_back=True,
                merge_verify=["python -c \"raise SystemExit(2)\""],
                rollback_on_merge_verification_failure=True,
            )
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = cmd_run(args)

            self.assertEqual(exit_code, 1)
            rendered = output.getvalue()
            self.assertIn("[merge-back] Patch transaction", rendered)
            self.assertIn("merge-back did not succeed", rendered)
            self.assertIn("execution_workspace:", rendered)
            self.assertIn("agent_summary_before_merge:", rendered)
            self.assertEqual((root / "app.py").read_text(encoding="utf-8"), "VALUE = 1\n")

    def test_run_rejects_merge_back_for_main_execution_mode(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            args = Namespace(
                task="inspect this repository",
                workspace=str(root),
                provider="mock",
                model="mock-coder",
                routing_policy="signal-aware",
                max_steps=3,
                timeout=30,
                dry_run=False,
                enforce_read_before_write=False,
                session="",
                execution_mode="main",
                execution_id="",
                show_execution_diff=False,
                merge_back=True,
                merge_verify=[],
                rollback_on_merge_verification_failure=False,
            )

            stdout = io.StringIO()
            stderr = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                exit_code = cmd_run(args)

            self.assertEqual(exit_code, 1)
            self.assertIn("merge-back requires an isolated execution mode", stderr.getvalue())

    def test_run_without_explicit_execution_mode_still_uses_copy_isolation(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")

            args = Namespace(
                task="inspect this repository",
                workspace=str(root),
                provider="mock",
                model="mock-coder",
                routing_policy="signal-aware",
                max_steps=3,
                timeout=30,
                dry_run=False,
                enforce_read_before_write=False,
                session="",
            )
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = cmd_run(args)

            self.assertEqual(exit_code, 0)
            self.assertIn("[execution] mode=copy", output.getvalue())
            workspaces = list((root / ".mini_claw" / "task_workspaces").glob("*"))
            self.assertTrue(any(path.is_dir() for path in workspaces))


if __name__ == "__main__":
    unittest.main()
