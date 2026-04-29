import unittest
import json
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from mini_claw.task_graph.workspace import TaskWorkspaceManager


class TaskWorkspaceManagerTest(unittest.TestCase):
    def test_create_copies_workspace_without_internal_dirs(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "app.py").write_text("VALUE = 'old'\n", encoding="utf-8")
            (root / ".mini_claw" / "memory").mkdir(parents=True)
            (root / ".mini_claw" / "memory" / "trace.jsonl").write_text("x\n", encoding="utf-8")
            (root / "__pycache__").mkdir()
            (root / "__pycache__" / "app.pyc").write_text("x\n", encoding="utf-8")

            manager = TaskWorkspaceManager(root)
            task_workspace = manager.create("task-1")
            task_root = Path(task_workspace.path)

            self.assertTrue((task_root / "app.py").exists())
            self.assertEqual(task_workspace.mode, "copy")
            self.assertFalse((task_root / ".mini_claw").exists())
            self.assertFalse((task_root / "__pycache__").exists())
            manifest = root / ".mini_claw" / "task_workspaces" / "task-1.manifest.json"
            self.assertTrue(manifest.exists())
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertIn("app.py", payload["files"])
            self.assertEqual(payload["mode"], "copy")

    def test_create_git_worktree_workspace_when_git_repo_is_available(self) -> None:
        if shutil.which("git") is None:
            self.skipTest("git is not available")
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "app.py").write_text("VALUE = 'old'\n", encoding="utf-8")
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

            manager = TaskWorkspaceManager(root)
            task_workspace = manager.create("task-1", mode="git-worktree")
            task_root = Path(task_workspace.path)

            self.assertEqual(task_workspace.mode, "git-worktree")
            self.assertTrue((task_root / "app.py").exists())
            self.assertTrue(str(task_root).endswith(str(Path(".mini_claw") / "task_worktrees" / "task-1")))
            manifest = root / ".mini_claw" / "task_workspaces" / "task-1.manifest.json"
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(payload["mode"], "git-worktree")
            listed = manager.list()
            self.assertEqual(listed[0].mode, "git-worktree")
            (task_root / "app.py").write_text("VALUE = 'new'\n", encoding="utf-8")
            summaries = manager.diff("task-1")
            self.assertEqual(summaries[0].path, "app.py")
            self.assertEqual(summaries[0].status, "modified")

    def test_diff_reports_task_workspace_changes(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "app.py").write_text("VALUE = 'old'\n", encoding="utf-8")
            manager = TaskWorkspaceManager(root)
            task_workspace = manager.create("task-1")
            task_root = Path(task_workspace.path)
            (task_root / "cheshi").mkdir()
            (task_root / "app.py").write_text("VALUE = 'new'\n", encoding="utf-8")
            (task_root / "new.txt").write_text("hello\n", encoding="utf-8")

            summaries = manager.diff("task-1")

            by_path = {summary.path: summary for summary in summaries}
            self.assertEqual(by_path["cheshi"].status, "added")
            self.assertEqual(by_path["app.py"].status, "modified")
            self.assertEqual(by_path["new.txt"].status, "added")

    def test_merge_applies_task_changes_back_to_main_workspace(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "app.py").write_text("VALUE = 'old'\n", encoding="utf-8")
            (root / "remove.txt").write_text("remove me\n", encoding="utf-8")
            manager = TaskWorkspaceManager(root)
            task_workspace = manager.create("task-1")
            task_root = Path(task_workspace.path)
            (task_root / "cheshi").mkdir()
            (task_root / "app.py").write_text("VALUE = 'new'\n", encoding="utf-8")
            (task_root / "new.txt").write_text("hello\n", encoding="utf-8")
            (task_root / "remove.txt").unlink()

            result = manager.merge("task-1")

            self.assertTrue(result.ok)
            self.assertTrue((root / "cheshi").is_dir())
            self.assertEqual((root / "app.py").read_text(encoding="utf-8"), "VALUE = 'new'\n")
            self.assertEqual((root / "new.txt").read_text(encoding="utf-8"), "hello\n")
            self.assertFalse((root / "remove.txt").exists())
            self.assertTrue(result.journal_path)
            by_path = {summary.path: summary for summary in result.diff_summary}
            self.assertEqual(by_path["cheshi"].status, "added")
            self.assertEqual(by_path["app.py"].status, "modified")
            self.assertEqual(by_path["new.txt"].status, "added")
            self.assertEqual(by_path["remove.txt"].status, "deleted")

    def test_merge_blocks_when_main_workspace_has_conflict(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "app.py").write_text("VALUE = 'old'\n", encoding="utf-8")
            manager = TaskWorkspaceManager(root)
            task_workspace = manager.create("task-1")
            task_root = Path(task_workspace.path)
            (task_root / "app.py").write_text("VALUE = 'task'\n", encoding="utf-8")
            (root / "app.py").write_text("VALUE = 'main'\n", encoding="utf-8")

            result = manager.merge("task-1")

            self.assertFalse(result.ok)
            self.assertEqual(len(result.conflicts), 1)
            self.assertEqual(result.conflicts[0].path, "app.py")
            self.assertEqual((root / "app.py").read_text(encoding="utf-8"), "VALUE = 'main'\n")


if __name__ == "__main__":
    unittest.main()
