import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from mini_claw.cli import cmd_smoke
from mini_claw.llm.mock import MockModelClient
from mini_claw.llm.base import ToolSpec


class NativeSmokeClient:
    def __init__(self) -> None:
        self.calls = 0
        self.tool_batches: list[list[ToolSpec]] = []

    def complete_with_tools(
        self,
        model: str,
        messages: list[dict[str, object]],
        tools: list[ToolSpec],
    ) -> dict[str, object]:
        self.tool_batches.append(list(tools))
        self.calls += 1
        if self.calls == 1:
            return {
                "tool_calls": [
                    {
                        "id": "smoke-shell-1",
                        "tool": "shell",
                        "args": {"command": "python -c \"print('NATIVE_SMOKE_READY')\""},
                    }
                ],
                "final": None,
            }
        return {"final": "NATIVE_SMOKE_OK"}


class CliSmokeTest(unittest.TestCase):
    def test_cmd_smoke_runs_native_tool_calling_probe(self) -> None:
        with TemporaryDirectory() as directory:
            workspace = Path(directory)
            args = SimpleNamespace(
                workspace=str(workspace),
                provider="openai-compatible",
                model="demo-model",
                timeout=30,
                max_rounds=4,
                expected_final="NATIVE_SMOKE_OK",
                json=True,
            )
            stdout = io.StringIO()
            with patch("mini_claw.cli.create_model_client", return_value=NativeSmokeClient()):
                with redirect_stdout(stdout):
                    rc = cmd_smoke(args)

            self.assertEqual(rc, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["status"], "ok")
            self.assertEqual(payload["actual_final"], "NATIVE_SMOKE_OK")
            self.assertEqual(payload["tool_calls"], 1)

    def test_cmd_smoke_requires_native_tool_calling_provider(self) -> None:
        with TemporaryDirectory() as directory:
            workspace = Path(directory)
            args = SimpleNamespace(
                workspace=str(workspace),
                provider="mock",
                model="mock-coder",
                timeout=30,
                max_rounds=2,
                expected_final="NATIVE_SMOKE_OK",
                json=False,
            )
            stderr = io.StringIO()
            with patch("mini_claw.cli.create_model_client", return_value=MockModelClient()):
                with redirect_stderr(stderr):
                    rc = cmd_smoke(args)

            self.assertEqual(rc, 1)
            self.assertIn("supports native tool calling", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
