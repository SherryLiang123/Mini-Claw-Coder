import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from mini_claw.memory.store import MemoryStore
from mini_claw.tools.base import ToolResult
from mini_claw.tools.tool_output_lookup import ToolOutputLookupTool


class ToolOutputLookupToolTest(unittest.TestCase):
    def test_lookup_can_find_query_excerpt(self) -> None:
        with TemporaryDirectory() as directory:
            memory = MemoryStore(Path(directory) / ".mini_claw" / "memory")
            memory.store_tool_result(
                "shell",
                {"command": "echo"},
                ToolResult(
                    ok=True,
                    output="\n".join(["alpha", "beta", "SPECIAL_TARGET", "gamma"]),
                ),
            )
            tool = ToolOutputLookupTool(memory)

            result = tool.run({"ref": "1", "query": "SPECIAL_TARGET", "max_chars": 120})

            self.assertTrue(result.ok)
            self.assertIn("SPECIAL_TARGET", result.output)
            self.assertIn("source_id=", result.output)

    def test_lookup_supports_latest_truncated_ref(self) -> None:
        with TemporaryDirectory() as directory:
            memory = MemoryStore(Path(directory) / ".mini_claw" / "memory")
            memory.store_tool_result(
                "shell",
                {"command": "echo short"},
                ToolResult(ok=True, output="short"),
            )
            memory.store_tool_result(
                "shell",
                {"command": "echo long"},
                ToolResult(ok=True, output="X" * 4000),
                preview_chars=200,
            )
            tool = ToolOutputLookupTool(memory)

            result = tool.run({"ref": "latest_truncated", "max_chars": 100})

            self.assertTrue(result.ok)
            self.assertIn("source_tool=shell", result.output)

    def test_lookup_focus_auto_uses_planned_hint(self) -> None:
        with TemporaryDirectory() as directory:
            memory = MemoryStore(Path(directory) / ".mini_claw" / "memory")
            memory.store_tool_result(
                "shell",
                {"command": "python -c", "task": "find the special target"},
                ToolResult(
                    ok=True,
                    output="\n".join(["alpha", "beta", "SPECIAL_LOOKUP_TARGET", "gamma"]),
                ),
                task="find the special target",
            )
            tool = ToolOutputLookupTool(memory)

            result = tool.run({"ref": "1", "focus": "auto", "max_chars": 120})

            self.assertTrue(result.ok)
            self.assertIn("SPECIAL_LOOKUP_TARGET", result.output)
            self.assertIn("focus=auto", result.output)

    def test_lookup_focus_auto_can_filter_by_intent(self) -> None:
        with TemporaryDirectory() as directory:
            memory = MemoryStore(Path(directory) / ".mini_claw" / "memory")
            memory.store_tool_result(
                "shell",
                {"command": "python -c", "task": "inspect path and error"},
                ToolResult(
                    ok=False,
                    output=(
                        "README.md\n"
                        "Traceback (most recent call last):\n"
                        "ModuleNotFoundError: No module named 'demo_pkg'\n"
                    ),
                ),
                task="inspect path and error",
            )
            tool = ToolOutputLookupTool(memory)

            result = tool.run({"ref": "1", "focus": "auto", "intent": "path", "max_chars": 160})

            self.assertTrue(result.ok)
            self.assertIn("README.md", result.output)
            self.assertIn("intent=path", result.output)
            self.assertIn("hint_kind=path", result.output)

    def test_lookup_focus_auto_can_skip_seen_queries(self) -> None:
        with TemporaryDirectory() as directory:
            memory = MemoryStore(Path(directory) / ".mini_claw" / "memory")
            memory.store_tool_result(
                "shell",
                {"command": "python -c", "task": "inspect multiple files"},
                ToolResult(
                    ok=True,
                    output="\n".join(["README.md", "app.py", "docs/guide.md"]),
                ),
                task="inspect multiple files",
            )
            tool = ToolOutputLookupTool(memory)

            result = tool.run(
                {
                    "ref": "1",
                    "focus": "auto",
                    "intent": "path",
                    "exclude_queries": ["README.md"],
                    "max_chars": 160,
                }
            )

            self.assertTrue(result.ok)
            self.assertNotIn("query=README.md", result.output)
            self.assertIn("query=app.py", result.output)
            self.assertIn("remaining_hints=1", result.output)


if __name__ == "__main__":
    unittest.main()
