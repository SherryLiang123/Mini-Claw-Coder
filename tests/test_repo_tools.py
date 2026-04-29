from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from mini_claw.memory.store import MemoryStore
from mini_claw.tools.bash import BashTool
from mini_claw.tools.repo_tools import EditTool, GlobTool, GrepTool, ListFilesTool, MkdirTool, ReadTool, WriteTool
from mini_claw.tools.runtime import build_runtime_tools


class RepoToolsTest(unittest.TestCase):
    def test_list_glob_grep_and_read_tools(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "src").mkdir()
            (root / "src" / "app.py").write_text("print('hello')\nVALUE = 1\n", encoding="utf-8")
            (root / "README.md").write_text("# Demo\n", encoding="utf-8")
            memory = MemoryStore(root / ".mini_claw" / "memory")

            ls_result = ListFilesTool(root).run({"path": ".", "limit": 10})
            glob_result = GlobTool(root).run({"path": ".", "pattern": "**/*.py", "limit": 10})
            grep_result = GrepTool(root).run({"path": ".", "pattern": "VALUE", "limit": 10})
            read_result = ReadTool(root, memory=memory).run({"path": "src/app.py", "limit": 20})

            self.assertTrue(ls_result.ok)
            self.assertIn("src/", ls_result.output)
            self.assertTrue(glob_result.ok)
            self.assertIn("src/app.py", glob_result.output)
            self.assertTrue(grep_result.ok)
            self.assertIn("src/app.py:2: VALUE = 1", grep_result.output)
            self.assertTrue(read_result.ok)
            self.assertIn("1 | print('hello')", read_result.output)
            self.assertIsNotNone(memory.latest_read_snapshot("src/app.py"))

    def test_edit_requires_read_snapshot_when_enabled(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "app.py"
            target.write_text("name = 'old'\n", encoding="utf-8")
            memory = MemoryStore(root / ".mini_claw" / "memory")

            edit = EditTool(root, memory=memory, require_read_snapshot=True)
            blocked = edit.run({"path": "app.py", "old": "old", "new": "new"})
            self.assertFalse(blocked.ok)
            self.assertIn("READ_BEFORE_WRITE_REQUIRED", blocked.output)

            read = ReadTool(root, memory=memory).run({"path": "app.py"})
            allowed = edit.run({"path": "app.py", "old": "old", "new": "new"})

            self.assertTrue(read.ok)
            self.assertTrue(allowed.ok)
            self.assertEqual(target.read_text(encoding="utf-8"), "name = 'new'\n")

    def test_write_existing_file_uses_read_lock(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "app.py"
            target.write_text("VALUE = 1\n", encoding="utf-8")
            memory = MemoryStore(root / ".mini_claw" / "memory")

            write = WriteTool(root, memory=memory, require_read_snapshot=True)
            blocked = write.run({"path": "app.py", "content": "VALUE = 2\n"})
            self.assertFalse(blocked.ok)
            self.assertIn("READ_BEFORE_WRITE_REQUIRED", blocked.output)

            ReadTool(root, memory=memory).run({"path": "app.py"})
            allowed = write.run({"path": "app.py", "content": "VALUE = 2\n"})

            self.assertTrue(allowed.ok)
            self.assertEqual(target.read_text(encoding="utf-8"), "VALUE = 2\n")

    def test_mkdir_creates_directory_and_reports_modified_path(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            mkdir = MkdirTool(root)

            result = mkdir.run({"path": "cheshi"})

            self.assertTrue(result.ok)
            self.assertTrue((root / "cheshi").is_dir())
            self.assertEqual(result.modified_files, ["cheshi/"])
            self.assertEqual(result.metadata["entry_type"], "dir")

    def test_bash_blocks_repo_inspection_commands_and_runs_tests(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "app.py").write_text("print('ok')\n", encoding="utf-8")
            bash = BashTool(root, timeout_seconds=5)

            blocked = bash.run({"command": "dir"})
            allowed = bash.run({"command": "python -c \"print('OK')\""})
            blocked_mkdir = bash.run({"command": "mkdir cheshi"})

            self.assertFalse(blocked.ok)
            self.assertIn("COMMAND_BLOCKED", blocked.output)
            self.assertFalse(blocked_mkdir.ok)
            self.assertIn("structured workspace mutation tools", blocked_mkdir.output)
            self.assertTrue(allowed.ok)
            self.assertIn("OK", allowed.output)

    def test_runtime_tool_builder_registers_structured_tools(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            memory = MemoryStore(root / ".mini_claw" / "memory")

            tools = build_runtime_tools(
                workspace=root,
                memory=memory,
                timeout_seconds=30,
                dry_run=False,
                require_read_snapshot=True,
            )

            for name in [
                "ls",
                "glob",
                "grep",
                "read",
                "mkdir",
                "edit",
                "write",
                "bash",
                "shell",
                "apply_patch",
                "tool_output_lookup",
            ]:
                self.assertIn(name, tools)


if __name__ == "__main__":
    unittest.main()
