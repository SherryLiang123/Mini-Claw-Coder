from __future__ import annotations

import json
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mini_claw.agent.loop import AgentLoop
from mini_claw.config import AppConfig, ModelConfig, RuntimeConfig
from mini_claw.llm.scripted import ScriptedModelClient
from mini_claw.memory.store import MemoryStore
from mini_claw.routing.router import ModelRouter
from mini_claw.skills.loader import SkillLoader
from mini_claw.tools.runtime import build_runtime_tools
from mini_claw.tracing.replay import replay_trace


@dataclass(frozen=True)
class BenchVerification:
    command: str
    ok: bool
    exit_code: int
    output: str


@dataclass(frozen=True)
class BenchCaseResult:
    name: str
    success: bool
    expected_success: bool
    observed_success: bool
    agent_success: bool
    verification_passed: bool
    elapsed_seconds: float
    tool_calls: int
    context_builds: int
    failed_tool_calls: int
    agent_step_failures: int
    patch_transactions: int
    modified_files: list[str]
    failure_root_cause: str | None
    route_reason_counts: dict[str, int]
    verifications: list[BenchVerification] = field(default_factory=list)


@dataclass(frozen=True)
class BenchReport:
    total: int
    passed: int
    failed: int
    results: list[BenchCaseResult]
    routing_policy: str = "signal-aware"

    def to_markdown(self) -> str:
        success_rate = self.passed / self.total if self.total else 0.0
        avg_tool_calls = _avg(result.tool_calls for result in self.results)
        avg_context_builds = _avg(result.context_builds for result in self.results)
        lines = [
            "# Mini Claw EvalBench Report",
            "",
            f"- routing_policy: {self.routing_policy}",
            f"- total: {self.total}",
            f"- passed: {self.passed}",
            f"- failed: {self.failed}",
            f"- success_rate: {success_rate:.2%}",
            f"- avg_tool_calls: {avg_tool_calls:.2f}",
            f"- avg_context_builds: {avg_context_builds:.2f}",
            "",
            "## Cases",
        ]
        for result in self.results:
            status = "PASS" if result.success else "FAIL"
            root = result.failure_root_cause or "(none)"
            lines.extend(
                [
                    f"### {result.name}: {status}",
                    f"- expected_success: {result.expected_success}",
                    f"- observed_success: {result.observed_success}",
                    f"- agent_success: {result.agent_success}",
                    f"- verification_passed: {result.verification_passed}",
                    f"- elapsed_seconds: {result.elapsed_seconds:.3f}",
                    f"- tool_calls: {result.tool_calls}",
                    f"- context_builds: {result.context_builds}",
                    f"- failed_tool_calls: {result.failed_tool_calls}",
                    f"- agent_step_failures: {result.agent_step_failures}",
                    f"- patch_transactions: {result.patch_transactions}",
                    f"- modified_files: {', '.join(result.modified_files) or '(none)'}",
                    (
                        "- route_reasons: "
                        + (
                            ", ".join(
                                f"{name}={count}"
                                for name, count in sorted(result.route_reason_counts.items())
                            )
                            or "(none)"
                        )
                    ),
                    f"- failure_root_cause: {root}",
                ]
            )
        return "\n".join(lines)


@dataclass(frozen=True)
class BenchRoutingSummary:
    policy: str
    passed: int
    failed: int
    success_rate: float
    avg_tool_calls: float
    avg_context_builds: float
    route_reason_counts: dict[str, int]


@dataclass(frozen=True)
class BenchRoutingComparisonReport:
    total_cases: int
    summaries: list[BenchRoutingSummary]

    def to_markdown(self) -> str:
        lines = [
            "# Mini Claw Routing Comparison",
            "",
            f"- total_cases: {self.total_cases}",
            "",
            "## Policies",
        ]
        for summary in self.summaries:
            lines.extend(
                [
                    f"### {summary.policy}",
                    f"- passed: {summary.passed}",
                    f"- failed: {summary.failed}",
                    f"- success_rate: {summary.success_rate:.2%}",
                    f"- avg_tool_calls: {summary.avg_tool_calls:.2f}",
                    f"- avg_context_builds: {summary.avg_context_builds:.2f}",
                    (
                        "- route_reasons: "
                        + (
                            ", ".join(
                                f"{name}={count}"
                                for name, count in sorted(summary.route_reason_counts.items())
                            )
                            or "(none)"
                        )
                    ),
                ]
            )
        return "\n".join(lines)


def run_bench_file(
    path: Path,
    workspace: Path,
    routing_policy: str = "signal-aware",
    run_label: str = "",
) -> BenchReport:
    cases = _load_cases(path)
    suffix = f"-{_safe_name(run_label)}" if run_label else ""
    run_root = workspace / ".mini_claw" / "bench_runs" / f"{_stamp()}{suffix}"
    results: list[BenchCaseResult] = []
    for case in cases:
        case_workspace = run_root / _safe_name(str(case["name"]))
        case_workspace.mkdir(parents=True, exist_ok=True)
        results.append(_run_case(case, case_workspace, routing_policy=routing_policy))
    passed = sum(1 for result in results if result.success)
    return BenchReport(
        total=len(results),
        passed=passed,
        failed=len(results) - passed,
        results=results,
        routing_policy=routing_policy,
    )


def compare_bench_routing_policies(
    path: Path,
    workspace: Path,
    policies: list[str],
) -> BenchRoutingComparisonReport:
    unique_policies = list(dict.fromkeys(policy for policy in policies if policy.strip()))
    reports = [
        run_bench_file(path, workspace=workspace, routing_policy=policy, run_label=policy)
        for policy in unique_policies
    ]
    summaries: list[BenchRoutingSummary] = []
    for report in reports:
        route_reason_counts: dict[str, int] = {}
        for result in report.results:
            for name, count in result.route_reason_counts.items():
                route_reason_counts[name] = route_reason_counts.get(name, 0) + count
        summaries.append(
            BenchRoutingSummary(
                policy=report.routing_policy,
                passed=report.passed,
                failed=report.failed,
                success_rate=(report.passed / report.total) if report.total else 0.0,
                avg_tool_calls=_avg(result.tool_calls for result in report.results),
                avg_context_builds=_avg(result.context_builds for result in report.results),
                route_reason_counts=route_reason_counts,
            )
        )
    total_cases = reports[0].total if reports else 0
    return BenchRoutingComparisonReport(total_cases=total_cases, summaries=summaries)


def _run_case(case: dict[str, Any], workspace: Path, routing_policy: str) -> BenchCaseResult:
    _setup_case(case, workspace)
    memory = MemoryStore(workspace / ".mini_claw" / "memory")
    if case.get("project_memory"):
        memory.update_project_memory(str(case["project_memory"]))

    actions = list(case.get("scripted_actions", []))
    runtime = RuntimeConfig(workspace=workspace, max_steps=max(2, len(actions) + 2))
    models = ModelConfig(provider="scripted", default_model="scripted")
    agent = AgentLoop(
        config=AppConfig(runtime=runtime, models=models),
        client=ScriptedModelClient(actions),
        router=ModelRouter(models, policy=routing_policy),
        tools=build_runtime_tools(
            workspace=workspace,
            memory=memory,
            timeout_seconds=runtime.command_timeout_seconds,
            dry_run=runtime.dry_run,
            require_read_snapshot=False,
        ),
        memory=memory,
        skills=SkillLoader([workspace / ".mini_claw" / "skills"]).load(),
    )

    start = time.perf_counter()
    result = agent.run(str(case["task"]))
    verifications = _run_verifications(case, workspace)
    elapsed = time.perf_counter() - start
    replay = replay_trace(memory.trace_path)
    verification_passed = all(item.ok for item in verifications)
    observed_success = result.success and verification_passed
    expected_success = bool(case.get("expected_success", True))
    success = observed_success == expected_success
    failure_root_cause = None
    if result.failure_report:
        failure_root_cause = str(result.failure_report.get("root_cause"))
    elif not verification_passed:
        failure_root_cause = "VERIFICATION_FAILED"

    return BenchCaseResult(
        name=str(case["name"]),
        success=success,
        expected_success=expected_success,
        observed_success=observed_success,
        agent_success=result.success,
        verification_passed=verification_passed,
        elapsed_seconds=elapsed,
        tool_calls=replay.tool_calls,
        context_builds=replay.context_builds,
        failed_tool_calls=replay.failed_tool_calls,
        agent_step_failures=replay.agent_step_failures,
        patch_transactions=len(replay.patch_transactions),
        modified_files=result.modified_files,
        failure_root_cause=failure_root_cause,
        route_reason_counts=replay.route_reason_counts,
        verifications=verifications,
    )


def _load_cases(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".jsonl":
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        return list(data.get("cases", []))
    if isinstance(data, list):
        return data
    raise ValueError("Bench file must be JSON array, JSON object with cases, or JSONL.")


def _setup_case(case: dict[str, Any], workspace: Path) -> None:
    files = case.get("setup_files", {})
    if not isinstance(files, dict):
        raise ValueError("setup_files must be an object.")
    for raw_path, content in files.items():
        path = workspace / str(raw_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(content), encoding="utf-8")

    copy_from = case.get("copy_from")
    if copy_from:
        source = Path(str(copy_from)).resolve()
        for item in source.iterdir():
            target = workspace / item.name
            if item.is_dir():
                shutil.copytree(item, target)
            else:
                shutil.copy2(item, target)


def _run_verifications(case: dict[str, Any], workspace: Path) -> list[BenchVerification]:
    commands = case.get("verification_commands", [])
    if isinstance(commands, str):
        commands = [commands]
    results: list[BenchVerification] = []
    for command in commands:
        completed = subprocess.run(
            str(command),
            shell=True,
            cwd=workspace,
            text=True,
            capture_output=True,
            timeout=int(case.get("verification_timeout_seconds", 60)),
        )
        output = "\n".join(
            part for part in [completed.stdout.strip(), completed.stderr.strip()] if part
        )
        results.append(
            BenchVerification(
                command=str(command),
                ok=completed.returncode == 0,
                exit_code=completed.returncode,
                output=output[:8_000],
            )
        )
    return results


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")


def _safe_name(name: str) -> str:
    return "".join(char if char.isalnum() or char in "-_" else "_" for char in name)[:80]


def _avg(values: Any) -> float:
    items = list(values)
    return sum(items) / len(items) if items else 0.0
