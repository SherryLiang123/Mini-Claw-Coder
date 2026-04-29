import io
import unittest
from argparse import Namespace
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

from mini_claw.cli import cmd_tool_output
from mini_claw.memory.store import MemoryStore
from mini_claw.tools.base import ToolResult


class ToolOutputCliTest(unittest.TestCase):
    def test_tool_output_list_and_show(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            memory = MemoryStore(root / ".mini_claw" / "memory")
            handle = memory.store_tool_result(
                "shell",
                {"command": "echo hello", "task": "find the special target"},
                ToolResult(
                    ok=True,
                    output="hello\nSPECIAL_LOOKUP_TARGET\n",
                    metadata={"exit_code": 0},
                ),
                task="find the special target",
            )

            list_args = Namespace(
                workspace=str(root),
                tool_output_command="list",
                limit=20,
            )
            list_buffer = io.StringIO()
            with redirect_stdout(list_buffer):
                list_exit = cmd_tool_output(list_args)

            self.assertEqual(list_exit, 0)
            self.assertIn(handle.output_id, list_buffer.getvalue())

            show_args = Namespace(
                workspace=str(root),
                tool_output_command="show",
                ref="1",
            )
            show_buffer = io.StringIO()
            with redirect_stdout(show_buffer):
                show_exit = cmd_tool_output(show_args)

            self.assertEqual(show_exit, 0)
            output = show_buffer.getvalue()
            self.assertIn("lookup_hint", output)
            self.assertIn("lookup_plan", output)
            self.assertIn("kind=", output)
            self.assertIn("SPECIAL_LOOKUP_TARGET", output)
            self.assertIn("echo hello", output)
            self.assertIn("hello", output)


if __name__ == "__main__":
    unittest.main()
