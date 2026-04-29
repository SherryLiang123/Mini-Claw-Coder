from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from mini_claw.agent.state import AgentStep, TaskState


@dataclass(frozen=True)
class CompactionUpdate:
    compacted_steps: int
    kept_steps: int
    summary_chars: int
    tool_counts: dict[str, int]


def refresh_compact_summary(
    state: TaskState,
    keep_last_steps: int = 3,
    trigger_steps: int = 5,
    max_summary_chars: int = 1_600,
) -> CompactionUpdate | None:
    if len(state.steps) < trigger_steps:
        return None
    compacted = state.steps[:-keep_last_steps] if len(state.steps) > keep_last_steps else []
    if len(compacted) <= 0 or len(compacted) <= state.compacted_steps:
        return None

    tool_counts = Counter(
        step.action.tool
        for step in compacted
        if step.action and step.action.tool.strip()
    )
    summary = _build_summary(
        compacted_steps=compacted,
        tool_counts=dict(tool_counts),
        modified_files=sorted(state.modified_files),
        pending_lookup=state.pending_lookup.output_id if state.pending_lookup else "",
        max_chars=max_summary_chars,
    )
    state.compact_summary = summary
    state.compacted_steps = len(compacted)
    state.compaction_count += 1
    return CompactionUpdate(
        compacted_steps=len(compacted),
        kept_steps=min(keep_last_steps, len(state.steps)),
        summary_chars=len(summary),
        tool_counts=dict(tool_counts),
    )


def _build_summary(
    compacted_steps: list[AgentStep],
    tool_counts: dict[str, int],
    modified_files: list[str],
    pending_lookup: str,
    max_chars: int,
) -> str:
    lines = [
        f"- compacted_steps: {len(compacted_steps)}",
        (
            "- tool_counts: "
            + (", ".join(f"{tool}={count}" for tool, count in sorted(tool_counts.items())) or "(none)")
        ),
        (
            "- modified_files_so_far: "
            + (", ".join(modified_files) or "(none)")
        ),
        f"- pending_lookup: {pending_lookup or '(none)'}",
        "",
        "### Older Step Highlights",
    ]
    for step in compacted_steps[-6:]:
        lines.append(_render_step_highlight(step))
    summary = "\n".join(lines).strip()
    if len(summary) <= max_chars:
        return summary
    half = max(1, max_chars // 2)
    return summary[:half] + "\n...[compacted summary truncated]...\n" + summary[-half:]


def _render_step_highlight(step: AgentStep) -> str:
    tool = step.action.tool if step.action else "(none)"
    observation = _compact_text(step.observation or step.thought or "(none)", limit=180)
    return f"- step {step.index} [{step.role}/{step.model}] tool={tool}: {observation}"


def _compact_text(text: str, limit: int) -> str:
    normalized = " ".join(part.strip() for part in text.splitlines() if part.strip())
    if len(normalized) <= limit:
        return normalized
    head = max(1, limit // 2)
    tail = max(1, limit - head - 7)
    return normalized[:head] + " ... " + normalized[-tail:]
