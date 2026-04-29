from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from mini_claw.agent.loop import AgentLoop
from mini_claw.config import AppConfig, ModelConfig, RuntimeConfig
from mini_claw.llm.factory import create_model_client
from mini_claw.memory.store import MemoryStore
from mini_claw.routing.router import ModelRouter
from mini_claw.skills.loader import SkillLoader
from mini_claw.tools.runtime import build_runtime_tools


@dataclass(frozen=True)
class EvalReport:
    total: int
    passed: int
    failed: int

    def to_markdown(self) -> str:
        return "\n".join(
            [
                "# Mini Claw Eval Report",
                "",
                f"- total: {self.total}",
                f"- passed: {self.passed}",
                f"- failed: {self.failed}",
            ]
        )


def run_eval_file(
    path: Path,
    workspace: Path,
    provider: str = "mock",
    routing_policy: str = "signal-aware",
) -> EvalReport:
    tasks = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    passed = 0
    for item in tasks:
        task = str(item["task"])
        agent = _build_agent(
            workspace=workspace,
            provider=provider,
            routing_policy=routing_policy,
        )
        result = agent.run(task)
        passed += int(result.success)
    return EvalReport(total=len(tasks), passed=passed, failed=len(tasks) - passed)


def _build_agent(workspace: Path, provider: str, routing_policy: str) -> AgentLoop:
    runtime = RuntimeConfig(workspace=workspace)
    models = ModelConfig(provider=provider)
    memory = MemoryStore(workspace / ".mini_claw" / "memory")
    skills = SkillLoader([workspace / ".mini_claw" / "skills"]).load()
    return AgentLoop(
        config=AppConfig(runtime=runtime, models=models),
        client=create_model_client(provider, workspace=workspace),
        router=ModelRouter(models, policy=routing_policy),
        tools=build_runtime_tools(
            workspace=workspace,
            memory=memory,
            timeout_seconds=runtime.command_timeout_seconds,
            dry_run=runtime.dry_run,
            require_read_snapshot=False,
        ),
        memory=memory,
        skills=skills,
    )
