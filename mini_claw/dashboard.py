from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from mini_claw.background.jobs import BackgroundRunManager, BackgroundRunRecord
from mini_claw.memory.store import MemoryStore
from mini_claw.sessions.replay import SessionReplaySummary, replay_session
from mini_claw.sessions.store import SessionManager
from mini_claw.task_graph.graph import TaskGraph, TaskNode
from mini_claw.tracing.replay import ReplaySummary, replay_trace


@dataclass(frozen=True)
class RuntimeDashboard:
    workspace: str
    generated_at: str
    trace_summary: ReplaySummary | None
    session_count: int
    latest_session_id: str = ""
    latest_session_name: str = ""
    latest_session_turns: int = 0
    latest_session_replay: SessionReplaySummary | None = None
    task_status_counts: dict[str, int] = field(default_factory=dict)
    ready_tasks: list[TaskNode] = field(default_factory=list)
    background_status_counts: dict[str, int] = field(default_factory=dict)
    latest_background_runs: list[BackgroundRunRecord] = field(default_factory=list)
    tool_output_count: int = 0
    truncated_tool_output_count: int = 0
    latest_tool_outputs: list[dict[str, object]] = field(default_factory=list)
    memory_candidate_status_counts: dict[str, int] = field(default_factory=dict)
    skill_patch_eval_counts: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "workspace": self.workspace,
            "generated_at": self.generated_at,
            "trace_summary": self.trace_summary.to_dict() if self.trace_summary is not None else None,
            "session_count": self.session_count,
            "latest_session_id": self.latest_session_id,
            "latest_session_name": self.latest_session_name,
            "latest_session_turns": self.latest_session_turns,
            "latest_session_replay": self.latest_session_replay.to_dict()
            if self.latest_session_replay is not None
            else None,
            "task_status_counts": dict(self.task_status_counts),
            "ready_tasks": [asdict(node) for node in self.ready_tasks],
            "background_status_counts": dict(self.background_status_counts),
            "latest_background_runs": [run.to_dict() for run in self.latest_background_runs],
            "tool_output_count": self.tool_output_count,
            "truncated_tool_output_count": self.truncated_tool_output_count,
            "latest_tool_outputs": [_compact_tool_output(record) for record in self.latest_tool_outputs],
            "memory_candidate_status_counts": dict(self.memory_candidate_status_counts),
            "skill_patch_eval_counts": dict(self.skill_patch_eval_counts),
        }

    def to_markdown(self) -> str:
        lines = [
            "# Mini Claw Runtime Dashboard",
            "",
            f"- workspace: {self.workspace}",
            f"- generated_at: {self.generated_at}",
            "",
            "## Trace",
        ]
        if self.trace_summary is None:
            lines.append("- trace: (none)")
        else:
            lines.extend(
                [
                    f"- total_events: {self.trace_summary.total_events}",
                    f"- context_builds: {self.trace_summary.context_builds}",
                    f"- tool_calls: {self.trace_summary.tool_calls}",
                    f"- failed_tool_calls: {self.trace_summary.failed_tool_calls}",
                    f"- lookup_policy_blocks: {self.trace_summary.lookup_policy_blocks}",
                    f"- context_compactions: {self.trace_summary.context_compactions}",
                ]
            )

        lines.extend(["", "## Sessions", f"- total_sessions: {self.session_count}"])
        if self.latest_session_id:
            lines.extend(
                [
                    f"- latest_session: {self.latest_session_id}",
                    f"- latest_session_name: {self.latest_session_name or '(unnamed)'}",
                    f"- latest_session_turns: {self.latest_session_turns}",
                ]
            )
            if self.latest_session_replay is not None:
                lines.extend(
                    [
                        f"- latest_session_successful_turns: {self.latest_session_replay.successful_turns}",
                        f"- latest_session_failed_turns: {self.latest_session_replay.failed_turns}",
                        f"- latest_session_tool_calls: {self.latest_session_replay.tool_calls}",
                    ]
                )
        else:
            lines.append("- latest_session: (none)")

        lines.extend(["", "## Tasks"])
        if not self.task_status_counts:
            lines.append("- task_graph: (none)")
        else:
            for status, count in sorted(self.task_status_counts.items()):
                lines.append(f"- {status}: {count}")
            if self.ready_tasks:
                lines.append("- ready_tasks:")
                for node in self.ready_tasks:
                    lines.append(f"  - {node.task_id}: {node.objective}")

        lines.extend(["", "## Background Runs"])
        if not self.background_status_counts:
            lines.append("- background_runs: (none)")
        else:
            for status, count in sorted(self.background_status_counts.items()):
                lines.append(f"- {status}: {count}")
            for run in self.latest_background_runs:
                lines.append(
                    f"- latest_run {run.run_id}: status={run.status}; "
                    f"task={run.task_id or '-'}; label={run.label or '-'}"
                )

        lines.extend(
            [
                "",
                "## Tool Outputs",
                f"- total_tool_outputs: {self.tool_output_count}",
                f"- truncated_tool_outputs: {self.truncated_tool_output_count}",
            ]
        )
        for record in self.latest_tool_outputs:
            lines.append(
                f"- latest_output {record.get('output_id')}: tool={record.get('tool')}; "
                f"ok={record.get('ok')}; chars={record.get('output_chars')}"
            )

        lines.extend(["", "## Memory"])
        if self.memory_candidate_status_counts:
            for status, count in sorted(self.memory_candidate_status_counts.items()):
                lines.append(f"- candidates_{status}: {count}")
        else:
            lines.append("- candidates: (none)")
        if self.skill_patch_eval_counts:
            for status, count in sorted(self.skill_patch_eval_counts.items()):
                lines.append(f"- skill_patch_eval_{status}: {count}")
        else:
            lines.append("- skill_patches: (none)")
        return "\n".join(lines)


def build_runtime_dashboard(
    workspace: Path,
    *,
    session_ref: str = "",
    session_turn_limit: int = 20,
    background_limit: int = 5,
    tool_output_limit: int = 5,
) -> RuntimeDashboard:
    workspace = workspace.resolve()
    memory = MemoryStore(workspace / ".mini_claw" / "memory")
    session_manager = SessionManager(workspace)
    background_manager = BackgroundRunManager(workspace, memory=memory)

    trace_summary = replay_trace(memory.trace_path) if memory.trace_path.exists() else None

    sessions = session_manager.list_sessions(limit=50)
    latest_session_id = ""
    latest_session_name = ""
    latest_session_turns = 0
    latest_session_replay = None
    if sessions:
        selected = session_manager.read_session(session_ref) if session_ref.strip() else sessions[0]
        latest_session_id = selected.session_id
        latest_session_name = selected.name
        latest_session_turns = selected.turn_count
        latest_session_replay = replay_session(
            session_manager,
            selected.session_id,
            turn_limit=session_turn_limit,
        )

    graph_path = workspace / ".mini_claw" / "task_graph.json"
    graph = TaskGraph.load(graph_path)
    task_status_counts = _count_task_statuses(graph)
    ready_tasks = graph.ready()[:5] if graph.nodes else []

    background_runs = background_manager.list_runs(limit=100)
    background_status_counts = _count_background_statuses(background_runs)
    latest_background_runs = background_runs[:background_limit]

    all_tool_outputs = memory.list_tool_outputs(limit=10_000)
    latest_tool_outputs = all_tool_outputs[:tool_output_limit]
    truncated_tool_output_count = sum(
        1
        for record in all_tool_outputs
        if record.get("truncated") or record.get("store_truncated")
    )

    memory_candidates = memory.read_memory_candidates(limit=None)
    memory_candidate_status_counts = _count_by_key(memory_candidates, "status")
    skill_patch_artifacts = memory.read_skill_patch_artifacts(limit=None)
    skill_patch_eval_counts = _count_skill_patch_eval_status(skill_patch_artifacts)

    return RuntimeDashboard(
        workspace=str(workspace),
        generated_at=_utcnow(),
        trace_summary=trace_summary,
        session_count=len(sessions),
        latest_session_id=latest_session_id,
        latest_session_name=latest_session_name,
        latest_session_turns=latest_session_turns,
        latest_session_replay=latest_session_replay,
        task_status_counts=task_status_counts,
        ready_tasks=ready_tasks,
        background_status_counts=background_status_counts,
        latest_background_runs=latest_background_runs,
        tool_output_count=len(all_tool_outputs),
        truncated_tool_output_count=truncated_tool_output_count,
        latest_tool_outputs=latest_tool_outputs,
        memory_candidate_status_counts=memory_candidate_status_counts,
        skill_patch_eval_counts=skill_patch_eval_counts,
    )


def summarize_dashboard_changes(
    previous: RuntimeDashboard,
    current: RuntimeDashboard,
) -> list[str]:
    changes: list[str] = []

    changes.extend(
        _diff_scalar(
            "trace.total_events",
            _trace_metric(previous.trace_summary, "total_events"),
            _trace_metric(current.trace_summary, "total_events"),
        )
    )
    changes.extend(
        _diff_scalar(
            "trace.tool_calls",
            _trace_metric(previous.trace_summary, "tool_calls"),
            _trace_metric(current.trace_summary, "tool_calls"),
        )
    )
    changes.extend(
        _diff_scalar(
            "trace.failed_tool_calls",
            _trace_metric(previous.trace_summary, "failed_tool_calls"),
            _trace_metric(current.trace_summary, "failed_tool_calls"),
        )
    )
    changes.extend(
        _diff_scalar(
            "sessions.total",
            previous.session_count,
            current.session_count,
        )
    )
    changes.extend(
        _diff_scalar(
            "sessions.latest_turns",
            previous.latest_session_turns,
            current.latest_session_turns,
        )
    )
    if previous.latest_session_id != current.latest_session_id:
        changes.append(
            f"- sessions.latest_session: {previous.latest_session_id or '(none)'} -> "
            f"{current.latest_session_id or '(none)'}"
        )

    changes.extend(_diff_counts("tasks", previous.task_status_counts, current.task_status_counts))
    previous_ready = [node.task_id for node in previous.ready_tasks]
    current_ready = [node.task_id for node in current.ready_tasks]
    if previous_ready != current_ready:
        changes.append(
            f"- tasks.ready: {', '.join(previous_ready) or '(none)'} -> "
            f"{', '.join(current_ready) or '(none)'}"
        )

    changes.extend(
        _diff_counts(
            "background",
            previous.background_status_counts,
            current.background_status_counts,
        )
    )
    previous_run_ids = [run.run_id for run in previous.latest_background_runs]
    current_run_ids = [run.run_id for run in current.latest_background_runs]
    if previous_run_ids != current_run_ids:
        changes.append(
            f"- background.latest_runs: {', '.join(previous_run_ids) or '(none)'} -> "
            f"{', '.join(current_run_ids) or '(none)'}"
        )

    changes.extend(
        _diff_scalar(
            "tool_outputs.total",
            previous.tool_output_count,
            current.tool_output_count,
        )
    )
    changes.extend(
        _diff_scalar(
            "tool_outputs.truncated",
            previous.truncated_tool_output_count,
            current.truncated_tool_output_count,
        )
    )
    changes.extend(
        _diff_counts(
            "memory.candidates",
            previous.memory_candidate_status_counts,
            current.memory_candidate_status_counts,
        )
    )
    changes.extend(
        _diff_counts(
            "memory.skill_patch_eval",
            previous.skill_patch_eval_counts,
            current.skill_patch_eval_counts,
        )
    )
    return changes


def _compact_tool_output(record: dict[str, object]) -> dict[str, object]:
    compact = {
        "output_id": record.get("output_id", ""),
        "created_at": record.get("created_at", ""),
        "tool": record.get("tool", ""),
        "ok": record.get("ok", False),
        "output_chars": record.get("output_chars", 0),
        "stored_output_chars": record.get("stored_output_chars", 0),
        "preview_chars": record.get("preview_chars", 0),
        "truncated": record.get("truncated", False),
        "store_truncated": record.get("store_truncated", False),
        "lookup_hint": record.get("lookup_hint", ""),
        "preview": record.get("preview", ""),
        "modified_files": list(record.get("modified_files", []))
        if isinstance(record.get("modified_files"), list)
        else [],
    }
    if isinstance(record.get("args"), dict):
        compact["args"] = dict(record["args"])
    if isinstance(record.get("metadata"), dict):
        compact["metadata"] = dict(record["metadata"])
    if isinstance(record.get("lookup_plan"), dict):
        compact["lookup_plan"] = dict(record["lookup_plan"])
    return compact


def _count_task_statuses(graph: TaskGraph) -> dict[str, int]:
    counts: dict[str, int] = {}
    for node in graph.nodes.values():
        counts[node.status] = counts.get(node.status, 0) + 1
    return counts


def _count_background_statuses(runs: list[BackgroundRunRecord]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for run in runs:
        counts[run.status] = counts.get(run.status, 0) + 1
    return counts


def _count_by_key(records: list[dict[str, object]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        value = str(record.get(key, "")).strip() or "(unknown)"
        counts[value] = counts.get(value, 0) + 1
    return counts


def _count_skill_patch_eval_status(records: list[dict[str, object]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        value = str(record.get("eval_status", "")).strip() or "pending"
        counts[value] = counts.get(value, 0) + 1
    return counts


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _trace_metric(summary: ReplaySummary | None, field_name: str) -> int:
    if summary is None:
        return 0
    return int(getattr(summary, field_name, 0) or 0)


def _diff_scalar(label: str, previous: int, current: int) -> list[str]:
    if previous == current:
        return []
    delta = current - previous
    sign = "+" if delta >= 0 else ""
    return [f"- {label}: {previous} -> {current} ({sign}{delta})"]


def _diff_counts(
    label: str,
    previous: dict[str, int],
    current: dict[str, int],
) -> list[str]:
    changes: list[str] = []
    for key in sorted(set(previous) | set(current)):
        old = int(previous.get(key, 0))
        new = int(current.get(key, 0))
        if old == new:
            continue
        delta = new - old
        sign = "+" if delta >= 0 else ""
        changes.append(f"- {label}.{key}: {old} -> {new} ({sign}{delta})")
    return changes
