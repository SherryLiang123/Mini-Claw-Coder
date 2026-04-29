import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from mini_claw.agent.loop import AgentLoop
from mini_claw.config import AppConfig, ModelConfig, RuntimeConfig
from mini_claw.memory.store import MemoryStore
from mini_claw.routing.router import ModelRouter
from mini_claw.tools.patch import PatchTool
from mini_claw.tools.shell import ShellTool
from mini_claw.tools.tool_output_lookup import ToolOutputLookupTool


class RecordingScriptedModelClient:
    def __init__(self, decisions: list[dict[str, Any]]) -> None:
        self.decisions = decisions
        self.calls = 0
        self.prompts: list[str] = []

    def complete(self, model: str, messages: list[dict[str, str]]) -> str:
        self.prompts.append(messages[-1]["content"])
        if self.calls < len(self.decisions):
            decision = self.decisions[self.calls]
        else:
            decision = {
                "thought": "Scripted actions exhausted.",
                "action": None,
                "final": None,
            }
        self.calls += 1
        return json.dumps(decision)


class AgentCompactionTest(unittest.TestCase):
    def test_agent_loop_emits_context_compaction_and_injects_working_summary(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            memory = MemoryStore(root / ".mini_claw" / "memory")
            client = RecordingScriptedModelClient(
                [
                    {
                        "thought": "Inspect step 0.",
                        "action": {"tool": "shell", "args": {"command": "python -c \"print('STEP0')\""}},
                        "final": None,
                    },
                    {
                        "thought": "Inspect step 1.",
                        "action": {"tool": "shell", "args": {"command": "python -c \"print('STEP1')\""}},
                        "final": None,
                    },
                    {
                        "thought": "Inspect step 2.",
                        "action": {"tool": "shell", "args": {"command": "python -c \"print('STEP2')\""}},
                        "final": None,
                    },
                    {
                        "thought": "Inspect step 3.",
                        "action": {"tool": "shell", "args": {"command": "python -c \"print('STEP3')\""}},
                        "final": None,
                    },
                    {
                        "thought": "Inspect step 4.",
                        "action": {"tool": "shell", "args": {"command": "python -c \"print('STEP4')\""}},
                        "final": None,
                    },
                    {
                        "thought": "Done.",
                        "action": None,
                        "final": "Finished after repeated repository inspection.",
                    },
                ]
            )
            config = AppConfig(
                runtime=RuntimeConfig(workspace=root, max_steps=6),
                models=ModelConfig(provider="scripted", default_model="scripted"),
            )
            agent = AgentLoop(
                config=config,
                client=client,
                router=ModelRouter(config.models),
                tools={
                    "shell": ShellTool(root),
                    "apply_patch": PatchTool(root),
                    "tool_output_lookup": ToolOutputLookupTool(memory),
                },
                memory=memory,
                skills=[],
            )

            result = agent.run("inspect repository state over several steps")

            self.assertTrue(result.success)
            self.assertTrue(any("## Working Summary" in prompt for prompt in client.prompts))
            self.assertTrue(
                any(
                    "Older steps compacted:" in prompt and "tool_counts:" in prompt
                    for prompt in client.prompts
                    if "## Working Summary" in prompt
                )
            )
            trace_rows = [
                json.loads(line)
                for line in memory.trace_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            compactions = [row for row in trace_rows if row.get("event") == "context_compacted"]
            self.assertTrue(compactions)
            self.assertGreaterEqual(compactions[-1]["payload"].get("compacted_steps", 0), 2)
            self.assertTrue(
                any(
                    row.get("event") == "context_build"
                    and row.get("payload", {}).get("role") == "summarizer"
                    and row.get("payload", {}).get("route_reason") == "new_context_compaction"
                    for row in trace_rows
                )
            )


if __name__ == "__main__":
    unittest.main()
