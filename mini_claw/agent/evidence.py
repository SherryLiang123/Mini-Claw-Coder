from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class EvidenceSelection:
    source_output_id: str
    source_tool: str
    query: str
    focus: str
    intent: str
    hint_kind: str
    hint_index: int | None = None
    remaining_hints: int | None = None
    exclude_queries_count: int = 0
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def is_refinement(self) -> bool:
        return bool(
            self.intent
            or self.exclude_queries_count > 0
            or (self.hint_index is not None and self.hint_index > 1)
        )


def build_evidence_selection(metadata: dict[str, Any]) -> EvidenceSelection | None:
    source_output_id = str(metadata.get("source_output_id", "")).strip()
    if not source_output_id:
        return None
    return EvidenceSelection(
        source_output_id=source_output_id,
        source_tool=str(metadata.get("source_tool", "")).strip(),
        query=str(metadata.get("query", "")).strip(),
        focus=str(metadata.get("focus", "")).strip(),
        intent=str(metadata.get("intent", "")).strip(),
        hint_kind=str(metadata.get("hint_kind", "")).strip(),
        hint_index=_optional_int(metadata.get("hint_index")),
        remaining_hints=_optional_int(metadata.get("remaining_hints")),
        exclude_queries_count=max(0, int(metadata.get("exclude_queries_count", 0) or 0)),
        reason=str(metadata.get("reason", "")).strip(),
    )


def summarize_evidence(records: list[EvidenceSelection]) -> dict[str, Any]:
    if not records:
        return {
            "lookups": 0,
            "refinements": 0,
            "queries": [],
            "intents": [],
            "hint_kinds": [],
            "source_output_ids": [],
        }

    return {
        "lookups": len(records),
        "refinements": sum(1 for record in records if record.is_refinement()),
        "queries": _unique(record.query for record in records if record.query),
        "intents": _unique(record.intent for record in records if record.intent),
        "hint_kinds": _unique(record.hint_kind for record in records if record.hint_kind),
        "source_output_ids": _unique(
            record.source_output_id for record in records if record.source_output_id
        ),
    }


def _unique(values: Any) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return ordered


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return int(value)
