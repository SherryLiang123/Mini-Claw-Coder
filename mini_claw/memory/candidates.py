from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from uuid import uuid4


@dataclass(frozen=True)
class MemoryCandidate:
    kind: str
    content: str
    source: str
    confidence: float
    evidence: str
    tags: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    candidate_id: str = field(default_factory=lambda: f"mem-{uuid4().hex[:12]}")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def build_success_memory_candidate(
    task: str,
    final_answer: str,
    modified_files: list[str],
    evidence_summary: dict[str, object] | None = None,
) -> MemoryCandidate:
    files = ", ".join(modified_files) if modified_files else "(none)"
    lines = [
        "## Verified Task Outcome",
        f"- task: {task}",
        f"- modified_files: {files}",
        f"- result: {final_answer[:500]}",
    ]
    if evidence_summary and int(evidence_summary.get("lookups", 0) or 0) > 0:
        queries = ", ".join(str(item) for item in evidence_summary.get("queries", [])) or "(none)"
        lines.extend(
            [
                f"- evidence_lookups: {evidence_summary.get('lookups', 0)}",
                f"- evidence_refinements: {evidence_summary.get('refinements', 0)}",
                f"- evidence_queries: {queries}",
            ]
        )
    content = "\n".join(lines)
    return MemoryCandidate(
        kind="verified_task_outcome",
        content=content,
        source="agent_loop_success",
        confidence=0.7,
        evidence=f"Agent completed task successfully. modified_files={files}",
        tags=["success", "candidate"],
    )


def build_evidence_strategy_candidate(
    task: str,
    evidence_summary: dict[str, object],
) -> MemoryCandidate | None:
    lookups = int(evidence_summary.get("lookups", 0) or 0)
    if lookups <= 0:
        return None
    refinements = int(evidence_summary.get("refinements", 0) or 0)
    queries = [str(item) for item in evidence_summary.get("queries", []) if str(item).strip()]
    intents = [str(item) for item in evidence_summary.get("intents", []) if str(item).strip()]
    hint_kinds = [
        str(item) for item in evidence_summary.get("hint_kinds", []) if str(item).strip()
    ]
    source_outputs = [
        str(item) for item in evidence_summary.get("source_output_ids", []) if str(item).strip()
    ]
    content = "\n".join(
        [
            "## Evidence Lookup Strategy",
            f"- task: {task}",
            f"- lookups: {lookups}",
            f"- refinements: {refinements}",
            f"- intents: {', '.join(intents) or '(none)'}",
            f"- hint_kinds: {', '.join(hint_kinds) or '(none)'}",
            f"- queries: {', '.join(queries) or '(none)'}",
            f"- source_outputs: {', '.join(source_outputs) or '(none)'}",
        ]
    )
    tags = ["evidence", "lookup", "candidate"]
    if refinements > 0:
        tags.append("multi_hop")
    for intent in intents:
        tags.append(f"intent:{intent}")
    return MemoryCandidate(
        kind="evidence_lookup_strategy",
        content=content,
        source="agent_evidence_planner",
        confidence=0.62 if refinements == 0 else 0.68,
        evidence=(
            "Successful task used runtime evidence lookup. "
            f"lookups={lookups} refinements={refinements} queries={', '.join(queries) or '(none)'}"
        ),
        tags=tags,
    )
