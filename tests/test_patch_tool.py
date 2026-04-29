from pathlib import Path
from tempfile import TemporaryDirectory
from hashlib import sha256
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from mini_claw.memory.store import MemoryStore
from mini_claw.tools.patch import PatchTool
from mini_claw.tools.shell import ShellTool


class PatchToolTest(unittest.TestCase):
    def test_patch_tool_write_and_replace(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            tool = PatchTool(root)
            result = tool.run(
                {
                    "operations": [
                        {"op": "write", "path": "src/app.py", "content": "name = 'old'\n"},
                        {"op": "replace", "path": "src/app.py", "old": "old", "new": "new"},
                    ]
                }
            )

            self.assertTrue(result.ok)
            self.assertIn("transaction_id=", result.output)
            self.assertIn("journal_path", result.metadata)
            self.assertTrue(result.metadata["diff_summary"])
            self.assertEqual(
                (root / "src" / "app.py").read_text(encoding="utf-8"),
                "name = 'new'\n",
            )
            journal = root / str(result.metadata["journal_path"])
            self.assertTrue(journal.exists())

    def test_patch_tool_blocks_path_escape(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            tool = PatchTool(root)
            result = tool.run(
                {"operations": [{"op": "write", "path": "../escape.txt", "content": "x"}]}
            )

            self.assertFalse(result.ok)

    def test_patch_tool_rolls_back_failed_transaction(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "app.py"
            target.write_text("name = 'old'\n", encoding="utf-8")
            tool = PatchTool(root)

            result = tool.run(
                {
                    "operations": [
                        {"op": "replace", "path": "app.py", "old": "old", "new": "new"},
                        {"op": "replace", "path": "app.py", "old": "missing", "new": "x"},
                    ]
                }
            )

            self.assertFalse(result.ok)
            self.assertIn("rolled_back=True", result.output)
            self.assertEqual(target.read_text(encoding="utf-8"), "name = 'old'\n")

    def test_patch_tool_checks_expected_hash_for_overwrite(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "app.py"
            target.write_text("old\n", encoding="utf-8")
            digest = sha256("old\n".encode("utf-8")).hexdigest()
            tool = PatchTool(root)

            result = tool.run(
                {
                    "operations": [
                        {
                            "op": "write",
                            "path": "app.py",
                            "content": "new\n",
                            "expected_sha256": digest,
                        }
                    ]
                }
            )

            self.assertTrue(result.ok)
            self.assertEqual(target.read_text(encoding="utf-8"), "new\n")

    def test_patch_tool_rejects_unlocked_overwrite(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "app.py"
            target.write_text("old\n", encoding="utf-8")
            tool = PatchTool(root)

            result = tool.run(
                {"operations": [{"op": "write", "path": "app.py", "content": "new\n"}]}
            )

            self.assertFalse(result.ok)
            self.assertEqual(target.read_text(encoding="utf-8"), "old\n")
            journal = root / str(result.metadata["journal_path"])
            payload = json.loads(journal.read_text(encoding="utf-8"))
            self.assertTrue(payload["rolled_back"])

    def test_patch_tool_runs_bound_verification(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            tool = PatchTool(root)

            result = tool.run(
                {
                    "operations": [
                        {"op": "write", "path": "app.py", "content": "print('ok')\n"}
                    ],
                    "verify": ["python -c \"raise SystemExit(0)\""],
                }
            )

            self.assertTrue(result.ok)
            self.assertEqual(len(result.metadata["verification_results"]), 1)
            self.assertTrue(result.metadata["verification_results"][0]["ok"])

    def test_patch_tool_can_roll_back_failed_verification(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "app.py"
            target.write_text("name = 'old'\n", encoding="utf-8")
            tool = PatchTool(root)

            result = tool.run(
                {
                    "operations": [
                        {"op": "replace", "path": "app.py", "old": "old", "new": "new"}
                    ],
                    "verify": ["python -c \"raise SystemExit(2)\""],
                    "rollback_on_verification_failure": True,
                }
            )

            self.assertFalse(result.ok)
            self.assertIn("verification failed", result.output)
            self.assertEqual(target.read_text(encoding="utf-8"), "name = 'old'\n")
            self.assertEqual(result.modified_files, [])
            self.assertFalse(result.metadata["verification_results"][0]["ok"])

    def test_patch_tool_verification_runs_with_utf8_environment(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            tool = PatchTool(root)

            with patch(
                "mini_claw.safety.patch_transaction.subprocess.run",
                return_value=SimpleNamespace(returncode=0, stdout="", stderr=""),
            ) as mocked_run:
                result = tool.run(
                    {
                        "operations": [
                            {"op": "write", "path": "app.py", "content": "print('ok')\n"}
                        ],
                        "verify": ["python -c \"raise SystemExit(0)\""],
                    }
                )

            self.assertTrue(result.ok)
            env = mocked_run.call_args.kwargs["env"]
            self.assertEqual(env["PYTHONUTF8"], "1")
            self.assertEqual(env["PYTHONIOENCODING"], "utf-8")

    def test_patch_tool_requires_read_snapshot_when_enabled(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "app.py"
            target.write_text("name = 'old'\n", encoding="utf-8")
            memory = MemoryStore(root / ".mini_claw" / "memory")
            tool = PatchTool(root, memory=memory, require_read_snapshot=True)

            result = tool.run(
                {
                    "operations": [
                        {"op": "replace", "path": "app.py", "old": "old", "new": "new"}
                    ]
                }
            )

            self.assertFalse(result.ok)
            self.assertIn("READ_BEFORE_WRITE_REQUIRED", result.output)
            self.assertEqual(target.read_text(encoding="utf-8"), "name = 'old'\n")

    def test_shell_read_snapshot_unlocks_patch(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "app.py"
            target.write_text("name = 'old'\n", encoding="utf-8")
            memory = MemoryStore(root / ".mini_claw" / "memory")
            shell = ShellTool(root, memory=memory)
            patch = PatchTool(root, memory=memory, require_read_snapshot=True)

            read = shell.run({"command": "type app.py"})
            result = patch.run(
                {
                    "operations": [
                        {"op": "replace", "path": "app.py", "old": "old", "new": "new"}
                    ]
                }
            )

            self.assertTrue(read.ok)
            self.assertEqual(read.metadata["read_snapshots"][0]["path"], "app.py")
            self.assertTrue(result.ok)
            self.assertEqual(target.read_text(encoding="utf-8"), "name = 'new'\n")

    def test_patch_tool_blocks_stale_read_snapshot(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "app.py"
            target.write_text("name = 'old'\n", encoding="utf-8")
            memory = MemoryStore(root / ".mini_claw" / "memory")
            shell = ShellTool(root, memory=memory)
            patch = PatchTool(root, memory=memory, require_read_snapshot=True)

            shell.run({"command": "type app.py"})
            target.write_text("name = 'drifted'\n", encoding="utf-8")
            result = patch.run(
                {
                    "operations": [
                        {"op": "replace", "path": "app.py", "old": "drifted", "new": "new"}
                    ]
                }
            )

            self.assertFalse(result.ok)
            self.assertIn("STALE_READ_SNAPSHOT", result.output)
            self.assertEqual(target.read_text(encoding="utf-8"), "name = 'drifted'\n")


if __name__ == "__main__":
    unittest.main()
