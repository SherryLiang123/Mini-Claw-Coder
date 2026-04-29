import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from mini_claw.agent.loop import AgentLoop
from mini_claw.config import AppConfig, ModelConfig, RuntimeConfig
from mini_claw.llm.base import ToolSpec
from mini_claw.llm.mock import MockModelClient
from mini_claw.llm.scripted import ScriptedModelClient
from mini_claw.memory.store import MemoryStore
from mini_claw.routing.router import ModelRouter
from mini_claw.skills.loader import Skill, SkillContract
from mini_claw.tools.patch import PatchTool
from mini_claw.tools.shell import ShellTool
from mini_claw.tools.tool_output_lookup import ToolOutputLookupTool


class NativeToolCallingScriptedClient:
    def __init__(self, decisions: list[dict[str, object]]) -> None:
        self.decisions = decisions
        self.calls = 0
        self.text_calls = 0
        self.tool_batches: list[list[ToolSpec]] = []

    def complete(self, model: str, messages: list[dict[str, str]]) -> str:
        self.text_calls += 1
        raise AssertionError("complete() should not be used when native tool calling succeeds")

    def complete_with_tools(
        self,
        model: str,
        messages: list[dict[str, str]],
        tools: list[ToolSpec],
    ) -> dict[str, object]:
        self.tool_batches.append(list(tools))
        if self.calls < len(self.decisions):
            decision = self.decisions[self.calls]
        else:
            decision = {"thought": "", "action": None, "final": "done"}
        self.calls += 1
        return decision


class HybridFallbackClient:
    def __init__(
        self,
        *,
        native_decisions: list[dict[str, object]],
        text_decisions: list[dict[str, object]],
    ) -> None:
        self.native_decisions = native_decisions
        self.text_decisions = text_decisions
        self.native_calls = 0
        self.text_calls = 0

    def complete(self, model: str, messages: list[dict[str, str]]) -> str:
        if self.text_calls < len(self.text_decisions):
            decision = self.text_decisions[self.text_calls]
        else:
            decision = {"thought": "done", "action": None, "final": "fallback"}
        self.text_calls += 1
        return json.dumps(decision)

    def complete_with_tools(
        self,
        model: str,
        messages: list[dict[str, str]],
        tools: list[ToolSpec],
    ) -> dict[str, object]:
        if self.native_calls < len(self.native_decisions):
            decision = self.native_decisions[self.native_calls]
        else:
            decision = {"thought": "", "action": None, "final": None}
        self.native_calls += 1
        return decision


class AgentToolOutputTest(unittest.TestCase):
    def test_agent_loop_persists_tool_output_protocol(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "app.py").write_text("print('hello')\n", encoding="utf-8")
            memory = MemoryStore(root / ".mini_claw" / "memory")
            config = AppConfig(
                runtime=RuntimeConfig(workspace=root, max_steps=3),
                models=ModelConfig(provider="mock"),
            )
            agent = AgentLoop(
                config=config,
                client=MockModelClient(),
                router=ModelRouter(config.models),
                tools={
                    "shell": ShellTool(root),
                    "apply_patch": PatchTool(root),
                    "tool_output_lookup": ToolOutputLookupTool(memory),
                },
                memory=memory,
                skills=[],
            )

            result = agent.run("inspect this repository")

            self.assertTrue(result.success)
            records = memory.list_tool_outputs()
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["tool"], "shell")
            self.assertIn("tool-output show", result.steps[0].observation or "")

            trace_rows = [
                json.loads(line)
                for line in memory.trace_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            tool_call = next(row for row in trace_rows if row.get("event") == "tool_call")
            handle = tool_call["payload"].get("output_handle", {})
            self.assertEqual(handle.get("tool"), "shell")
            self.assertTrue(str(handle.get("output_id", "")).startswith("tool-"))

    def test_agent_can_lookup_truncated_tool_output(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            memory = MemoryStore(root / ".mini_claw" / "memory")
            config = AppConfig(
                runtime=RuntimeConfig(workspace=root, max_steps=4),
                models=ModelConfig(provider="scripted", default_model="scripted"),
            )
            agent = AgentLoop(
                config=config,
                client=ScriptedModelClient(
                    [
                        {
                            "thought": "Generate a long command output first.",
                            "action": {
                                "tool": "shell",
                                "args": {
                                    "command": (
                                        "python -c \"print('A'*2400); "
                                        "print('SPECIAL_LOOKUP_TARGET')\""
                                    )
                                },
                            },
                            "final": None,
                        },
                        {
                            "thought": "Lookup the truncated output around the target.",
                            "action": {
                                "tool": "tool_output_lookup",
                                "args": {
                                    "ref": "1",
                                    "query": "SPECIAL_LOOKUP_TARGET",
                                    "max_chars": 240,
                                },
                            },
                            "final": None,
                        },
                        {
                            "thought": "The lookup returned the needed excerpt.",
                            "action": None,
                            "final": "Found the target through tool output lookup.",
                        },
                    ]
                ),
                router=ModelRouter(config.models),
                tools={
                    "shell": ShellTool(root),
                    "apply_patch": PatchTool(root),
                    "tool_output_lookup": ToolOutputLookupTool(memory),
                },
                memory=memory,
                skills=[],
            )

            result = agent.run("inspect the long output and find the target")

            self.assertTrue(result.success)
            self.assertEqual(len(memory.list_tool_outputs()), 2)
            self.assertIn("tool_output_lookup", result.steps[1].action.tool if result.steps[1].action else "")
            self.assertIn("SPECIAL_LOOKUP_TARGET", result.steps[1].observation or "")

    def test_agent_blocks_repeated_shell_inspection_until_lookup(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            memory = MemoryStore(root / ".mini_claw" / "memory")
            config = AppConfig(
                runtime=RuntimeConfig(workspace=root, max_steps=5),
                models=ModelConfig(provider="scripted", default_model="scripted"),
            )
            long_command = "python -c \"print('A'*2400); print('SPECIAL_LOOKUP_TARGET')\""
            agent = AgentLoop(
                config=config,
                client=ScriptedModelClient(
                    [
                        {
                            "thought": "Generate a long shell output first.",
                            "action": {
                                "tool": "shell",
                                "args": {"command": long_command},
                            },
                            "final": None,
                        },
                        {
                            "thought": "Retry the same shell inspection command.",
                            "action": {
                                "tool": "shell",
                                "args": {"command": long_command},
                            },
                            "final": None,
                        },
                        {
                            "thought": "Use runtime lookup after the policy block.",
                            "action": {
                                "tool": "tool_output_lookup",
                                "args": {
                                    "ref": "latest_truncated",
                                    "query": "SPECIAL_LOOKUP_TARGET",
                                    "max_chars": 240,
                                },
                            },
                            "final": None,
                        },
                        {
                            "thought": "Lookup succeeded.",
                            "action": None,
                            "final": "Recovered the truncated shell output through runtime lookup.",
                        },
                    ]
                ),
                router=ModelRouter(config.models),
                tools={
                    "shell": ShellTool(root),
                    "apply_patch": PatchTool(root),
                    "tool_output_lookup": ToolOutputLookupTool(memory),
                },
                memory=memory,
                skills=[],
            )

            result = agent.run("inspect the long output without repeating shell")

            self.assertTrue(result.success)
            self.assertIn("tool_output_lookup required", result.steps[1].observation or "")
            self.assertEqual(len(memory.list_tool_outputs()), 2)
            trace_rows = [
                json.loads(line)
                for line in memory.trace_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertTrue(
                any(row.get("event") == "lookup_policy_blocked" for row in trace_rows)
            )

    def test_agent_can_use_auto_lookup_focus(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            memory = MemoryStore(root / ".mini_claw" / "memory")
            config = AppConfig(
                runtime=RuntimeConfig(workspace=root, max_steps=4),
                models=ModelConfig(provider="scripted", default_model="scripted"),
            )
            agent = AgentLoop(
                config=config,
                client=ScriptedModelClient(
                    [
                        {
                            "thought": "Generate a long shell output first.",
                            "action": {
                                "tool": "shell",
                                "args": {
                                    "command": (
                                        "python -c \"print('A'*2400); "
                                        "print('SPECIAL_LOOKUP_TARGET')\""
                                    )
                                },
                            },
                            "final": None,
                        },
                        {
                            "thought": "Use auto lookup focus.",
                            "action": {
                                "tool": "tool_output_lookup",
                                "args": {
                                    "ref": "latest_truncated",
                                    "focus": "auto",
                                    "max_chars": 240,
                                },
                            },
                            "final": None,
                        },
                        {
                            "thought": "Auto lookup found the needed excerpt.",
                            "action": None,
                            "final": "Recovered the relevant excerpt through auto lookup focus.",
                        },
                    ]
                ),
                router=ModelRouter(config.models),
                tools={
                    "shell": ShellTool(root),
                    "apply_patch": PatchTool(root),
                    "tool_output_lookup": ToolOutputLookupTool(memory),
                },
                memory=memory,
                skills=[],
            )

            result = agent.run("inspect the long output and use auto lookup focus")

            self.assertTrue(result.success)
            self.assertIn("focus=auto", result.steps[1].observation or "")
            self.assertIn("SPECIAL_LOOKUP_TARGET", result.steps[1].observation or "")

    def test_agent_can_refine_auto_lookup_with_intent(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            memory = MemoryStore(root / ".mini_claw" / "memory")
            config = AppConfig(
                runtime=RuntimeConfig(workspace=root, max_steps=5),
                models=ModelConfig(provider="scripted", default_model="scripted"),
            )
            agent = AgentLoop(
                config=config,
                client=ScriptedModelClient(
                    [
                        {
                            "thought": "Generate a long shell output with both path and error evidence.",
                            "action": {
                                "tool": "shell",
                                "args": {
                                    "command": (
                                        "python -c \"print('A'*2400); "
                                        "print('README.md'); "
                                        "print('Traceback (most recent call last):'); "
                                        "print(\\\"ModuleNotFoundError: No module named 'demo_pkg'\\\")\""
                                    )
                                },
                            },
                            "final": None,
                        },
                        {
                            "thought": "Look up the path-oriented hint first.",
                            "action": {
                                "tool": "tool_output_lookup",
                                "args": {
                                    "ref": "latest_truncated",
                                    "focus": "auto",
                                    "intent": "path",
                                    "max_chars": 220,
                                },
                            },
                            "final": None,
                        },
                        {
                            "thought": "Refine to the error-oriented hint next.",
                            "action": {
                                "tool": "tool_output_lookup",
                                "args": {
                                    "ref": "latest_truncated",
                                    "focus": "auto",
                                    "intent": "error",
                                    "exclude_queries": ["README.md"],
                                    "max_chars": 220,
                                },
                            },
                            "final": None,
                        },
                        {
                            "thought": "The refined lookup surfaced the import failure.",
                            "action": None,
                            "final": "Recovered both the path clue and the import error through refined auto lookup.",
                        },
                    ]
                ),
                router=ModelRouter(config.models),
                tools={
                    "shell": ShellTool(root),
                    "apply_patch": PatchTool(root),
                    "tool_output_lookup": ToolOutputLookupTool(memory),
                },
                memory=memory,
                skills=[],
            )

            result = agent.run("inspect both path and import error evidence from the long output")

            self.assertTrue(result.success)
            self.assertIn("intent=path", result.steps[1].observation or "")
            self.assertIn("README.md", result.steps[1].observation or "")
            self.assertIn("intent=error", result.steps[2].observation or "")
            self.assertIn("demo_pkg", result.steps[2].observation or "")

    def test_successful_evidence_lookup_creates_strategy_candidate(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            memory = MemoryStore(root / ".mini_claw" / "memory")
            config = AppConfig(
                runtime=RuntimeConfig(workspace=root, max_steps=5),
                models=ModelConfig(provider="scripted", default_model="scripted"),
            )
            agent = AgentLoop(
                config=config,
                client=ScriptedModelClient(
                    [
                        {
                            "thought": "Generate a long shell output with both path and error evidence.",
                            "action": {
                                "tool": "shell",
                                "args": {
                                    "command": (
                                        "python -c \"print('A'*2400); "
                                        "print('README.md'); "
                                        "print('Traceback (most recent call last):'); "
                                        "print(\\\"ModuleNotFoundError: No module named 'demo_pkg'\\\")\""
                                    )
                                },
                            },
                            "final": None,
                        },
                        {
                            "thought": "Inspect the path-oriented hint first.",
                            "action": {
                                "tool": "tool_output_lookup",
                                "args": {
                                    "ref": "latest_truncated",
                                    "focus": "auto",
                                    "intent": "path",
                                    "max_chars": 220,
                                },
                            },
                            "final": None,
                        },
                        {
                            "thought": "Refine toward the error-oriented hint.",
                            "action": {
                                "tool": "tool_output_lookup",
                                "args": {
                                    "ref": "latest_truncated",
                                    "focus": "auto",
                                    "intent": "error",
                                    "exclude_queries": ["README.md"],
                                    "max_chars": 220,
                                },
                            },
                            "final": None,
                        },
                        {
                            "thought": "Done.",
                            "action": None,
                            "final": "Recovered the path clue and the import error through evidence lookup.",
                        },
                    ]
                ),
                router=ModelRouter(config.models),
                tools={
                    "shell": ShellTool(root),
                    "apply_patch": PatchTool(root),
                    "tool_output_lookup": ToolOutputLookupTool(memory),
                },
                memory=memory,
                skills=[],
            )

            result = agent.run("inspect both path and import error evidence from the long output")

            self.assertTrue(result.success)
            candidates = memory.read_memory_candidates()
            self.assertEqual(len(candidates), 2)
            kinds = {candidate["kind"] for candidate in candidates}
            self.assertEqual(kinds, {"verified_task_outcome", "evidence_lookup_strategy"})
            evidence_candidate = next(
                candidate
                for candidate in candidates
                if candidate["kind"] == "evidence_lookup_strategy"
            )
            self.assertIn("lookups: 2", evidence_candidate["content"])
            self.assertIn("refinements: 2", evidence_candidate["content"])
            self.assertIn("README.md", evidence_candidate["content"])
            self.assertIn("demo_pkg", evidence_candidate["content"])
            trace_rows = [
                json.loads(line)
                for line in memory.trace_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            task_finished = next(
                row for row in reversed(trace_rows) if row.get("event") == "task_finished"
            )
            summary = task_finished["payload"].get("evidence_summary", {})
            self.assertEqual(summary.get("lookups"), 2)
            self.assertEqual(summary.get("refinements"), 2)
            self.assertEqual(summary.get("queries"), ["README.md", "demo_pkg"])

    def test_successful_evidence_lookup_suggests_skill_patch_candidate(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            memory = MemoryStore(root / ".mini_claw" / "memory")
            skill = Skill(
                name="repo-onboarding",
                body="Read files carefully and summarize supported facts.",
                path=root / ".mini_claw" / "skills" / "repo-onboarding" / "SKILL.md",
                contract=SkillContract(
                    name="repo-onboarding",
                    description="inspect repository and summarize facts",
                    triggers=["inspect", "repository"],
                    allowed_tools=["shell", "tool_output_lookup"],
                    verification=["cite observed files or command output"],
                ),
            )
            config = AppConfig(
                runtime=RuntimeConfig(workspace=root, max_steps=5),
                models=ModelConfig(provider="scripted", default_model="scripted"),
            )
            agent = AgentLoop(
                config=config,
                client=ScriptedModelClient(
                    [
                        {
                            "thought": "Generate a long shell output with path and error evidence.",
                            "action": {
                                "tool": "shell",
                                "args": {
                                    "command": (
                                        "python -c \"print('A'*2400); "
                                        "print('README.md'); "
                                        "print('Traceback (most recent call last):'); "
                                        "print(\\\"ModuleNotFoundError: No module named 'demo_pkg'\\\")\""
                                    )
                                },
                            },
                            "final": None,
                        },
                        {
                            "thought": "Inspect the path-oriented hint first.",
                            "action": {
                                "tool": "tool_output_lookup",
                                "args": {
                                    "ref": "latest_truncated",
                                    "focus": "auto",
                                    "intent": "path",
                                    "max_chars": 220,
                                },
                            },
                            "final": None,
                        },
                        {
                            "thought": "Refine toward the error-oriented hint.",
                            "action": {
                                "tool": "tool_output_lookup",
                                "args": {
                                    "ref": "latest_truncated",
                                    "focus": "auto",
                                    "intent": "error",
                                    "exclude_queries": ["README.md"],
                                    "max_chars": 220,
                                },
                            },
                            "final": None,
                        },
                        {
                            "thought": "Done.",
                            "action": None,
                            "final": "Recovered the path clue and the import error through evidence lookup.",
                        },
                    ]
                ),
                router=ModelRouter(config.models),
                tools={
                    "shell": ShellTool(root),
                    "apply_patch": PatchTool(root),
                    "tool_output_lookup": ToolOutputLookupTool(memory),
                },
                memory=memory,
                skills=[skill],
            )

            result = agent.run("inspect repository import error evidence from truncated output")

            self.assertTrue(result.success)
            candidates = memory.read_memory_candidates()
            self.assertEqual(len(candidates), 3)
            kinds = {candidate["kind"] for candidate in candidates}
            self.assertEqual(
                kinds,
                {
                    "verified_task_outcome",
                    "evidence_lookup_strategy",
                    "skill_patch_candidate",
                },
            )
            skill_candidate = next(
                candidate
                for candidate in candidates
                if candidate["kind"] == "skill_patch_candidate"
            )
            self.assertIn("target_skill: repo-onboarding", skill_candidate["content"])
            self.assertIn("tool_output_lookup", skill_candidate["content"])
            self.assertIn("focus='auto'", skill_candidate["content"])
            self.assertIn("intent='path' | 'error'", skill_candidate["content"])

            trace_rows = [
                json.loads(line)
                for line in memory.trace_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertTrue(
                any(
                    row.get("event") == "skill_patch_candidate_suggested"
                    and row.get("payload", {}).get("target_skill") == "repo-onboarding"
                    for row in trace_rows
                )
            )

    def test_agent_repairs_plain_text_final_into_runtime_json(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            memory = MemoryStore(root / ".mini_claw" / "memory")
            config = AppConfig(
                runtime=RuntimeConfig(workspace=root, max_steps=3),
                models=ModelConfig(provider="scripted", default_model="scripted"),
            )
            agent = AgentLoop(
                config=config,
                client=ScriptedModelClient(
                    [
                        {
                            "thought": "Inspect the workspace first.",
                            "action": {
                                "tool": "shell",
                                "args": {"command": "python -c \"print('READY')\""},
                            },
                            "final": None,
                        },
                        "The inspection is complete. READY is present in the observed output.",
                        {
                            "thought": "Wrap the previous text into the runtime JSON contract.",
                            "action": None,
                            "final": "The inspection is complete. READY is present in the observed output.",
                        },
                    ]
                ),
                router=ModelRouter(config.models),
                tools={
                    "shell": ShellTool(root),
                    "apply_patch": PatchTool(root),
                    "tool_output_lookup": ToolOutputLookupTool(memory),
                },
                memory=memory,
                skills=[],
            )

            result = agent.run("inspect the workspace and summarize what you found")

            self.assertTrue(result.success)
            self.assertEqual(
                result.final_answer,
                "The inspection is complete. READY is present in the observed output.",
            )
            trace_rows = [
                json.loads(line)
                for line in memory.trace_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertTrue(any(row.get("event") == "decision_repaired" for row in trace_rows))

    def test_agent_forces_finalization_after_step_budget_exhaustion(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            memory = MemoryStore(root / ".mini_claw" / "memory")
            config = AppConfig(
                runtime=RuntimeConfig(workspace=root, max_steps=1),
                models=ModelConfig(provider="scripted", default_model="scripted"),
            )
            agent = AgentLoop(
                config=config,
                client=ScriptedModelClient(
                    [
                        {
                            "thought": "Inspect the workspace once.",
                            "action": {
                                "tool": "shell",
                                "args": {"command": "python -c \"print('READY')\""},
                            },
                            "final": None,
                        },
                        {
                            "thought": "Enough evidence exists to close the run.",
                            "action": None,
                            "final": "Inspected the workspace and confirmed READY.",
                            "status": "completed",
                        },
                    ]
                ),
                router=ModelRouter(config.models),
                tools={
                    "shell": ShellTool(root),
                    "apply_patch": PatchTool(root),
                    "tool_output_lookup": ToolOutputLookupTool(memory),
                },
                memory=memory,
                skills=[],
            )

            result = agent.run("inspect the workspace and report the result")

            self.assertTrue(result.success)
            self.assertEqual(result.final_answer, "Inspected the workspace and confirmed READY.")
            trace_rows = [
                json.loads(line)
                for line in memory.trace_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertTrue(
                any(row.get("event") == "forced_finalization_succeeded" for row in trace_rows)
            )

    def test_agent_prefers_native_tool_calling_when_available(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            memory = MemoryStore(root / ".mini_claw" / "memory")
            client = NativeToolCallingScriptedClient(
                [
                    {
                        "thought": "Inspect the workspace through a native tool call.",
                        "action": {"tool": "shell", "args": {"command": "python -c \"print('READY')\""}},
                        "final": None,
                    },
                    {
                        "thought": "",
                        "action": None,
                        "final": "Native tool calling inspected the workspace successfully.",
                    },
                ]
            )
            config = AppConfig(
                runtime=RuntimeConfig(workspace=root, max_steps=3),
                models=ModelConfig(provider="openai-compatible", default_model="demo-model"),
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

            result = agent.run("inspect the workspace")

            self.assertTrue(result.success)
            self.assertEqual(
                result.final_answer,
                "Native tool calling inspected the workspace successfully.",
            )
            self.assertEqual(client.text_calls, 0)
            self.assertTrue(client.tool_batches)
            self.assertEqual([tool.name for tool in client.tool_batches[0]], ["shell", "apply_patch", "tool_output_lookup"])
            trace_rows = [
                json.loads(line)
                for line in memory.trace_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertTrue(
                any(row.get("event") == "native_tool_calling_result" for row in trace_rows)
            )

    def test_agent_can_chain_native_tool_calls_within_one_context_build(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            memory = MemoryStore(root / ".mini_claw" / "memory")
            client = NativeToolCallingScriptedClient(
                [
                    {
                        "thought": "First inspect the long shell output.",
                        "tool_calls": [
                            {
                                "id": "call-shell-1",
                                "tool": "shell",
                                "args": {
                                    "command": (
                                        "python -c \"print('A'*2400); "
                                        "print('SPECIAL_LOOKUP_TARGET')\""
                                    )
                                },
                            }
                        ],
                        "final": None,
                    },
                    {
                        "thought": "Now inspect the stored truncated output.",
                        "tool_calls": [
                            {
                                "id": "call-lookup-1",
                                "tool": "tool_output_lookup",
                                "args": {
                                    "ref": "latest_truncated",
                                    "query": "SPECIAL_LOOKUP_TARGET",
                                    "max_chars": 240,
                                },
                            }
                        ],
                        "final": None,
                    },
                    {
                        "thought": "",
                        "action": None,
                        "final": "Native tool calling chained shell inspection and lookup in one context build.",
                    },
                ]
            )
            config = AppConfig(
                runtime=RuntimeConfig(workspace=root, max_steps=5),
                models=ModelConfig(provider="openai-compatible", default_model="demo-model"),
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

            result = agent.run("inspect the long output and recover the target")

            self.assertTrue(result.success)
            self.assertEqual(
                result.final_answer,
                "Native tool calling chained shell inspection and lookup in one context build.",
            )
            trace_rows = [
                json.loads(line)
                for line in memory.trace_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertEqual(len([row for row in trace_rows if row.get("event") == "context_build"]), 1)
            self.assertEqual(len([row for row in trace_rows if row.get("event") == "tool_call"]), 2)

    def test_agent_falls_back_from_native_tool_calling_to_text_decision(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            memory = MemoryStore(root / ".mini_claw" / "memory")
            client = HybridFallbackClient(
                native_decisions=[
                    {"thought": "", "action": None, "final": None},
                ],
                text_decisions=[
                    {
                        "thought": "Fallback text decision should still run the tool.",
                        "action": {"tool": "shell", "args": {"command": "python -c \"print('READY')\""}},
                        "final": None,
                    },
                    {
                        "thought": "done",
                        "action": None,
                        "final": "Fallback text decision completed the run.",
                    },
                ],
            )
            config = AppConfig(
                runtime=RuntimeConfig(workspace=root, max_steps=3),
                models=ModelConfig(provider="openai-compatible", default_model="demo-model"),
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

            result = agent.run("inspect the workspace")

            self.assertTrue(result.success)
            self.assertEqual(result.final_answer, "Fallback text decision completed the run.")
            self.assertGreaterEqual(client.native_calls, 1)
            self.assertGreaterEqual(client.text_calls, 1)


if __name__ == "__main__":
    unittest.main()
