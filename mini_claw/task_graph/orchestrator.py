from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from mini_claw.memory.store import MemoryStore
from mini_claw.protocol.acp import HandoffPacket
from mini_claw.task_graph.graph import TaskGraph, TaskNode
from mini_claw.task_graph.workspace import TaskWorkspaceManager, WorkspaceMergeResult
from mini_claw.tracing.events import RuntimeEvent


@dataclass(frozen=True)
class RoleStep:
    role: str
    task_id: str
    status: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {
            "role": self.role,
            "task_id": self.task_id,
            "status": self.status,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class OrchestrationReport:
    processed: int
    passed: int
    failed: int
    steps: list[RoleStep] = field(default_factory=list)

    def to_markdown(self) -> str:
        lines = [
            "# Mini Claw Multi-Agent Orchestration",
            "",
            f"- processed: {self.processed}",
            f"- passed: {self.passed}",
            f"- failed: {self.failed}",
            "",
            "## Steps",
        ]
        for step in self.steps:
            lines.append(f"- {step.task_id} [{step.role}] {step.status}: {step.detail}")
        return "\n".join(lines)


@dataclass(frozen=True)
class CoderRunResult:
    ok: bool
    detail: str
    modified_files: list[str] = field(default_factory=list)


CoderRunner = Callable[[TaskNode, Path], CoderRunResult]


def run_task_graph_orchestration(
    *,
    workspace: Path,
    graph: TaskGraph,
    workspace_manager: TaskWorkspaceManager,
    memory: MemoryStore,
    mode: str = "copy",
    limit: int = 1,
    dry_run: bool = False,
    rollback_on_verification_failure: bool = False,
    coder_runner: CoderRunner | None = None,
) -> OrchestrationReport:
    steps: list[RoleStep] = []
    passed = 0
    failed = 0
    ready = graph.ready()[:limit]

    for node in ready:
        _append_step(memory, steps, "planner", node, "ok", "selected ready task")
        graph.set_status(node.task_id, "in_progress")
        node.owner_role = "coder"
        _handoff(memory, "planner", "coder", node)

        if not node.workspace_path:
            task_workspace = workspace_manager.create(node.task_id, mode=mode)
            graph.attach_workspace(node.task_id, task_workspace.path)
            node.workspace_path = task_workspace.path
            _append_step(
                memory,
                steps,
                "coder",
                node,
                "ok",
                f"workspace ready mode={task_workspace.mode}",
            )
        else:
            _append_step(memory, steps, "coder", node, "ok", "using existing workspace")
        if coder_runner is not None:
            coder_result = coder_runner(node, Path(node.workspace_path))
            detail = coder_result.detail
            if coder_result.modified_files:
                detail += f" modified_files={', '.join(coder_result.modified_files)}"
            _append_step(
                memory,
                steps,
                "coder",
                node,
                "ok" if coder_result.ok else "failed",
                detail,
            )
            if not coder_result.ok:
                graph.set_status(node.task_id, "failed")
                failed += 1
                continue
        _handoff(memory, "coder", "tester", node)

        verification_ok = True
        if node.verification_command:
            verification_ok, detail = _run_verification(
                command=node.verification_command,
                cwd=Path(node.workspace_path),
            )
            _append_step(
                memory,
                steps,
                "tester",
                node,
                "ok" if verification_ok else "failed",
                detail,
            )
        else:
            _append_step(memory, steps, "tester", node, "skipped", "no verification command")

        if not verification_ok:
            graph.set_status(node.task_id, "failed")
            failed += 1
            continue
        _handoff(memory, "tester", "integrator", node)

        merge_result = workspace_manager.merge(
            node.task_id,
            verification_commands=([node.verification_command] if node.verification_command else []),
            rollback_on_verification_failure=rollback_on_verification_failure,
            dry_run=dry_run,
        )
        _append_merge_step(memory, steps, node, merge_result)
        if merge_result.ok:
            graph.set_status(node.task_id, "done" if not dry_run else "in_progress")
            passed += 1
        else:
            graph.set_status(node.task_id, "blocked" if merge_result.conflicts else "failed")
            failed += 1

    return OrchestrationReport(
        processed=len(ready),
        passed=passed,
        failed=failed,
        steps=steps,
    )


def _run_verification(command: str, cwd: Path) -> tuple[bool, str]:
    completed = subprocess.run(
        command,
        cwd=cwd,
        shell=True,
        text=True,
        capture_output=True,
        timeout=60,
    )
    output = "\n".join(
        part for part in [completed.stdout.strip(), completed.stderr.strip()] if part
    )
    detail = f"command={command} exit_code={completed.returncode}"
    if output:
        detail += f" output={output[:500]}"
    return completed.returncode == 0, detail


def _handoff(memory: MemoryStore, source: str, target: str, node: TaskNode) -> None:
    packet = HandoffPacket(
        source_role=source,
        target_role=target,
        task=node.objective,
        constraints=[],
        context_refs=node.context_refs,
    )
    memory.append_event(RuntimeEvent("multi_agent_handoff", packet.to_acp().to_dict()))


def _append_step(
    memory: MemoryStore,
    steps: list[RoleStep],
    role: str,
    node: TaskNode,
    status: str,
    detail: str,
) -> None:
    step = RoleStep(role=role, task_id=node.task_id, status=status, detail=detail)
    steps.append(step)
    memory.append_event(RuntimeEvent("orchestration_step", step.to_dict()))


def _append_merge_step(
    memory: MemoryStore,
    steps: list[RoleStep],
    node: TaskNode,
    merge_result: WorkspaceMergeResult,
) -> None:
    detail = merge_result.output
    if merge_result.conflicts:
        detail += f" conflicts={len(merge_result.conflicts)}"
    _append_step(
        memory,
        steps,
        "integrator",
        node,
        "ok" if merge_result.ok else "failed",
        detail,
    )
