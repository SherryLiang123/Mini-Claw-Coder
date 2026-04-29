from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

from mini_claw.sessions.store import SessionManager, SessionTurnRecord
from mini_claw.tracing.replay import ReplaySummary, replay_trace


@dataclass(frozen=True)
class SessionTurnReplay:
    turn_id: str
    turn_index: int
    task: str
    success: bool
    started_at: str
    finished_at: str
    trace_path: str
    replay: ReplaySummary | None = None
    modified_files: list[str] = field(default_factory=list)
    failure_root_cause: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    def to_markdown(self) -> str:
        lines = [
            f"## Turn {self.turn_index}",
            f"- turn_id: {self.turn_id}",
            f"- task: {self.task}",
            f"- success: {self.success}",
            f"- started_at: {self.started_at}",
            f"- finished_at: {self.finished_at or '(running)'}",
            f"- modified_files: {', '.join(self.modified_files) or '(none)'}",
            f"- failure_root_cause: {self.failure_root_cause or '(none)'}",
            f"- trace_path: {self.trace_path or '(none)'}",
        ]
        if self.replay is not None:
            lines.extend(
                [
                    "- replay:",
                    f"  total_events={self.replay.total_events}",
                    f"  context_builds={self.replay.context_builds}",
                    f"  tool_calls={self.replay.tool_calls}",
                    f"  failed_tool_calls={self.replay.failed_tool_calls}",
                    f"  truncated_tool_outputs={self.replay.truncated_tool_outputs}",
                    f"  lookup_policy_blocks={self.replay.lookup_policy_blocks}",
                    f"  context_compactions={self.replay.context_compactions}",
                ]
            )
        return "\n".join(lines)


@dataclass(frozen=True)
class SessionReplaySummary:
    session_id: str
    session_name: str
    total_turns: int
    completed_turns: int
    successful_turns: int
    failed_turns: int
    total_events: int
    tool_calls: int
    failed_tool_calls: int
    truncated_tool_outputs: int
    context_builds: int
    lookup_policy_blocks: int
    context_compactions: int
    multi_agent_handoffs: int
    orchestration_steps: int
    event_counts: dict[str, int] = field(default_factory=dict)
    route_reason_counts: dict[str, int] = field(default_factory=dict)
    failure_root_causes: dict[str, int] = field(default_factory=dict)
    distinct_modified_files: list[str] = field(default_factory=list)
    turns: list[SessionTurnReplay] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    def to_markdown(self) -> str:
        lines = [
            "# Mini Claw Session Replay",
            "",
            f"- session_id: {self.session_id}",
            f"- name: {self.session_name or '(unnamed)'}",
            f"- total_turns: {self.total_turns}",
            f"- completed_turns: {self.completed_turns}",
            f"- successful_turns: {self.successful_turns}",
            f"- failed_turns: {self.failed_turns}",
            f"- total_events: {self.total_events}",
            f"- context_builds: {self.context_builds}",
            f"- tool_calls: {self.tool_calls}",
            f"- failed_tool_calls: {self.failed_tool_calls}",
            f"- truncated_tool_outputs: {self.truncated_tool_outputs}",
            f"- lookup_policy_blocks: {self.lookup_policy_blocks}",
            f"- context_compactions: {self.context_compactions}",
            f"- multi_agent_handoffs: {self.multi_agent_handoffs}",
            f"- orchestration_steps: {self.orchestration_steps}",
            f"- distinct_modified_files: {len(self.distinct_modified_files)}",
            "",
            "## Turns",
        ]
        if not self.turns:
            lines.append("- (no completed turns)")
        else:
            for turn in self.turns:
                lines.append(
                    f"- turn {turn.turn_index}: success={turn.success}; "
                    f"events={turn.replay.total_events if turn.replay else 0}; "
                    f"tool_calls={turn.replay.tool_calls if turn.replay else 0}; "
                    f"task={turn.task}"
                )
        if self.distinct_modified_files:
            lines.extend(["", "## Modified Files"])
            for path in self.distinct_modified_files:
                lines.append(f"- {path}")
        if self.failure_root_causes:
            lines.extend(["", "## Failure Root Causes"])
            for root_cause, count in sorted(self.failure_root_causes.items()):
                lines.append(f"- {root_cause}: {count}")
        if self.route_reason_counts:
            lines.extend(["", "## Route Reasons"])
            for reason, count in sorted(self.route_reason_counts.items()):
                lines.append(f"- {reason}: {count}")
        if self.event_counts:
            lines.extend(["", "## Event Counts"])
            for name, count in sorted(self.event_counts.items()):
                lines.append(f"- {name}: {count}")
        return "\n".join(lines)


def replay_session(
    manager: SessionManager,
    session_ref: str,
    *,
    turn_limit: int = 20,
) -> SessionReplaySummary:
    session = manager.read_session(session_ref)
    turns = list(reversed(manager.list_turns(session.session_id, limit=turn_limit)))
    turn_replays: list[SessionTurnReplay] = []
    event_counts: dict[str, int] = {}
    route_reason_counts: dict[str, int] = {}
    failure_root_causes: dict[str, int] = {}
    modified_files: set[str] = set()
    total_events = 0
    tool_calls = 0
    failed_tool_calls = 0
    truncated_tool_outputs = 0
    context_builds = 0
    lookup_policy_blocks = 0
    context_compactions = 0
    multi_agent_handoffs = 0
    orchestration_steps = 0
    completed_turns = 0
    successful_turns = 0
    failed_turns = 0

    for turn in turns:
        if turn.status != "completed":
            continue
        completed_turns += 1
        if turn.success:
            successful_turns += 1
        else:
            failed_turns += 1
        modified_files.update(turn.modified_files or [])
        root_cause = str((turn.failure_report or {}).get("root_cause", "")).strip()
        if root_cause:
            failure_root_causes[root_cause] = failure_root_causes.get(root_cause, 0) + 1
        replay = _replay_turn_trace(turn)
        if replay is not None:
            total_events += replay.total_events
            tool_calls += replay.tool_calls
            failed_tool_calls += replay.failed_tool_calls
            truncated_tool_outputs += replay.truncated_tool_outputs
            context_builds += replay.context_builds
            lookup_policy_blocks += replay.lookup_policy_blocks
            context_compactions += replay.context_compactions
            multi_agent_handoffs += replay.multi_agent_handoffs
            orchestration_steps += replay.orchestration_steps
            _merge_counts(event_counts, replay.event_counts)
            _merge_counts(route_reason_counts, replay.route_reason_counts)
        turn_replays.append(
            SessionTurnReplay(
                turn_id=turn.turn_id,
                turn_index=turn.turn_index,
                task=turn.task,
                success=turn.success,
                started_at=turn.started_at,
                finished_at=turn.finished_at,
                trace_path=turn.trace_path,
                replay=replay,
                modified_files=list(turn.modified_files or []),
                failure_root_cause=root_cause,
            )
        )

    return SessionReplaySummary(
        session_id=session.session_id,
        session_name=session.name,
        total_turns=session.turn_count,
        completed_turns=completed_turns,
        successful_turns=successful_turns,
        failed_turns=failed_turns,
        total_events=total_events,
        tool_calls=tool_calls,
        failed_tool_calls=failed_tool_calls,
        truncated_tool_outputs=truncated_tool_outputs,
        context_builds=context_builds,
        lookup_policy_blocks=lookup_policy_blocks,
        context_compactions=context_compactions,
        multi_agent_handoffs=multi_agent_handoffs,
        orchestration_steps=orchestration_steps,
        event_counts=event_counts,
        route_reason_counts=route_reason_counts,
        failure_root_causes=failure_root_causes,
        distinct_modified_files=sorted(modified_files),
        turns=turn_replays,
    )


def replay_session_turn(
    manager: SessionManager,
    session_ref: str,
    turn_ref: str,
) -> SessionTurnReplay:
    turn = manager.read_turn(session_ref, turn_ref)
    root_cause = str((turn.failure_report or {}).get("root_cause", "")).strip()
    return SessionTurnReplay(
        turn_id=turn.turn_id,
        turn_index=turn.turn_index,
        task=turn.task,
        success=turn.success,
        started_at=turn.started_at,
        finished_at=turn.finished_at,
        trace_path=turn.trace_path,
        replay=_replay_turn_trace(turn),
        modified_files=list(turn.modified_files or []),
        failure_root_cause=root_cause,
    )


def _replay_turn_trace(turn: SessionTurnRecord) -> ReplaySummary | None:
    trace_path = Path(turn.trace_path)
    if not turn.trace_path or not trace_path.exists():
        return None
    return replay_trace(trace_path)


def _merge_counts(target: dict[str, int], incoming: dict[str, int]) -> None:
    for name, count in incoming.items():
        target[name] = target.get(name, 0) + count
