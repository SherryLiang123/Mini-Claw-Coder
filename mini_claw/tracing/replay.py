from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ReplaySummary:
    total_events: int
    event_counts: dict[str, int]
    tool_calls: int
    failed_tool_calls: int
    truncated_tool_outputs: int
    lookup_auto_focus_calls: int
    lookup_refinement_calls: int
    evidence_selected_events: int
    tasks_with_evidence_summary: int
    distinct_evidence_queries: int
    skill_patch_candidates: int
    skill_patch_artifacts_created: int
    skill_patch_eval_runs: int
    skill_patch_eval_passed: int
    skill_patch_apply_previews: int
    context_compactions: int
    route_reason_counts: dict[str, int]
    lookup_policy_blocks: int
    agent_step_failures: int
    context_builds: int
    multi_agent_handoffs: int
    orchestration_steps: int
    orchestration_role_counts: dict[str, int]
    tester_failures: int
    integrator_merges: int
    integrator_failures: int
    patch_transactions: list[str] = field(default_factory=list)
    failure_reports: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_markdown(self) -> str:
        lines = [
            "# Mini Claw Trace Replay",
            "",
            f"- total_events: {self.total_events}",
            f"- context_builds: {self.context_builds}",
            f"- tool_calls: {self.tool_calls}",
            f"- failed_tool_calls: {self.failed_tool_calls}",
            f"- truncated_tool_outputs: {self.truncated_tool_outputs}",
            f"- lookup_auto_focus_calls: {self.lookup_auto_focus_calls}",
            f"- lookup_refinement_calls: {self.lookup_refinement_calls}",
            f"- evidence_selected_events: {self.evidence_selected_events}",
            f"- tasks_with_evidence_summary: {self.tasks_with_evidence_summary}",
            f"- distinct_evidence_queries: {self.distinct_evidence_queries}",
            f"- skill_patch_candidates: {self.skill_patch_candidates}",
            f"- skill_patch_artifacts_created: {self.skill_patch_artifacts_created}",
            f"- skill_patch_eval_runs: {self.skill_patch_eval_runs}",
            f"- skill_patch_eval_passed: {self.skill_patch_eval_passed}",
            f"- skill_patch_apply_previews: {self.skill_patch_apply_previews}",
            f"- context_compactions: {self.context_compactions}",
            f"- lookup_policy_blocks: {self.lookup_policy_blocks}",
            f"- agent_step_failures: {self.agent_step_failures}",
            f"- multi_agent_handoffs: {self.multi_agent_handoffs}",
            f"- orchestration_steps: {self.orchestration_steps}",
            f"- tester_failures: {self.tester_failures}",
            f"- integrator_merges: {self.integrator_merges}",
            f"- integrator_failures: {self.integrator_failures}",
            f"- patch_transactions: {len(self.patch_transactions)}",
            f"- failure_reports: {len(self.failure_reports)}",
            "",
            "## Event Counts",
        ]
        for name, count in sorted(self.event_counts.items()):
            lines.append(f"- {name}: {count}")
        if self.route_reason_counts:
            lines.extend(["", "## Route Reasons"])
            for name, count in sorted(self.route_reason_counts.items()):
                lines.append(f"- {name}: {count}")
        if self.orchestration_role_counts:
            lines.extend(["", "## Orchestration Roles"])
            for name, count in sorted(self.orchestration_role_counts.items()):
                lines.append(f"- {name}: {count}")
        if self.patch_transactions:
            lines.extend(["", "## Patch Transactions"])
            for tx in self.patch_transactions:
                lines.append(f"- {tx}")
        if self.failure_reports:
            lines.extend(["", "## Failure Reports"])
            for report in self.failure_reports:
                lines.append(
                    f"- {report.get('root_cause')}: {report.get('suggested_action')}"
                )
        return "\n".join(lines)


def replay_trace(trace_path: Path) -> ReplaySummary:
    events = _read_jsonl(trace_path)
    counts: dict[str, int] = {}
    patch_transactions: list[str] = []
    failure_reports: list[dict[str, Any]] = []
    tool_calls = 0
    failed_tool_calls = 0
    truncated_tool_outputs = 0
    lookup_auto_focus_calls = 0
    lookup_refinement_calls = 0
    evidence_selected_events = 0
    tasks_with_evidence_summary = 0
    evidence_queries: set[str] = set()
    skill_patch_candidates = 0
    skill_patch_artifacts_created = 0
    skill_patch_eval_runs = 0
    skill_patch_eval_passed = 0
    skill_patch_apply_previews = 0
    context_compactions = 0
    route_reason_counts: dict[str, int] = {}
    lookup_policy_blocks = 0
    agent_step_failures = 0
    context_builds = 0
    multi_agent_handoffs = 0
    orchestration_steps = 0
    orchestration_role_counts: dict[str, int] = {}
    tester_failures = 0
    integrator_merges = 0
    integrator_failures = 0

    for event in events:
        name = _event_name(event)
        counts[name] = counts.get(name, 0) + 1
        payload = _payload(event)

        if name == "context_build":
            context_builds += 1
            route_reason = str(payload.get("route_reason", "")).strip()
            if route_reason:
                route_reason_counts[route_reason] = route_reason_counts.get(route_reason, 0) + 1
        if name == "tool_call":
            tool_calls += 1
            if not payload.get("ok", False):
                failed_tool_calls += 1
            metadata = payload.get("metadata")
            if isinstance(metadata, dict):
                tx = metadata.get("transaction_id")
                if tx:
                    patch_transactions.append(str(tx))
                if payload.get("tool") == "tool_output_lookup" and metadata.get("focus") == "auto":
                    lookup_auto_focus_calls += 1
                    if (
                        metadata.get("intent")
                        or int(metadata.get("exclude_queries_count", 0)) > 0
                        or int(metadata.get("hint_index", 1) or 1) > 1
                    ):
                        lookup_refinement_calls += 1
            output_handle = payload.get("output_handle")
            if isinstance(output_handle, dict) and (
                output_handle.get("truncated") or output_handle.get("store_truncated")
            ):
                truncated_tool_outputs += 1
        if name == "task_finished":
            report = payload.get("failure_report")
            if isinstance(report, dict):
                failure_reports.append(report)
            evidence_summary = payload.get("evidence_summary")
            if isinstance(evidence_summary, dict) and int(evidence_summary.get("lookups", 0) or 0) > 0:
                tasks_with_evidence_summary += 1
                for query in evidence_summary.get("queries", []):
                    text = str(query).strip()
                    if text:
                        evidence_queries.add(text)
        if name == "evidence_selected":
            evidence_selected_events += 1
            text = str(payload.get("query", "")).strip()
            if text:
                evidence_queries.add(text)
        if name == "lookup_policy_blocked":
            lookup_policy_blocks += 1
        if name == "agent_step_failed":
            agent_step_failures += 1
        if name == "memory_candidate_created" and payload.get("kind") == "skill_patch_candidate":
            skill_patch_candidates += 1
        if name == "skill_patch_artifact_created":
            skill_patch_artifacts_created += 1
        if name == "skill_patch_eval_recorded":
            skill_patch_eval_runs += 1
            if payload.get("status") == "passed":
                skill_patch_eval_passed += 1
        if name == "skill_patch_apply_previewed":
            skill_patch_apply_previews += 1
        if name == "context_compacted":
            context_compactions += 1
        if name == "multi_agent_handoff":
            multi_agent_handoffs += 1
        if name == "orchestration_step":
            orchestration_steps += 1
            role = str(payload.get("role", "")).strip()
            status = str(payload.get("status", "")).strip()
            detail = str(payload.get("detail", ""))
            if role:
                orchestration_role_counts[role] = orchestration_role_counts.get(role, 0) + 1
            if role == "tester" and status == "failed":
                tester_failures += 1
            if role == "integrator":
                if status == "ok":
                    integrator_merges += 1
                else:
                    integrator_failures += 1

    return ReplaySummary(
        total_events=len(events),
        event_counts=counts,
        tool_calls=tool_calls,
        failed_tool_calls=failed_tool_calls,
        truncated_tool_outputs=truncated_tool_outputs,
        lookup_auto_focus_calls=lookup_auto_focus_calls,
        lookup_refinement_calls=lookup_refinement_calls,
        evidence_selected_events=evidence_selected_events,
        tasks_with_evidence_summary=tasks_with_evidence_summary,
        distinct_evidence_queries=len(evidence_queries),
        skill_patch_candidates=skill_patch_candidates,
        skill_patch_artifacts_created=skill_patch_artifacts_created,
        skill_patch_eval_runs=skill_patch_eval_runs,
        skill_patch_eval_passed=skill_patch_eval_passed,
        skill_patch_apply_previews=skill_patch_apply_previews,
        context_compactions=context_compactions,
        route_reason_counts=route_reason_counts,
        lookup_policy_blocks=lookup_policy_blocks,
        agent_step_failures=agent_step_failures,
        context_builds=context_builds,
        multi_agent_handoffs=multi_agent_handoffs,
        orchestration_steps=orchestration_steps,
        orchestration_role_counts=orchestration_role_counts,
        tester_failures=tester_failures,
        integrator_merges=integrator_merges,
        integrator_failures=integrator_failures,
        patch_transactions=patch_transactions,
        failure_reports=failure_reports,
    )


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rows.append(json.loads(line))
    return rows


def _event_name(event: dict[str, Any]) -> str:
    raw = event.get("event")
    if isinstance(raw, str):
        return raw
    return "unknown"


def _payload(event: dict[str, Any]) -> dict[str, Any]:
    raw = event.get("payload")
    if isinstance(raw, dict):
        return raw
    return event
