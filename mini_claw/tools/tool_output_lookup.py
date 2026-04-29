from __future__ import annotations

from typing import Any

from mini_claw.memory.lookup_plan import select_lookup_hint
from mini_claw.memory.store import MemoryStore
from mini_claw.tools.base import ToolResult


class ToolOutputLookupTool:
    name = "tool_output_lookup"

    def __init__(self, memory: MemoryStore) -> None:
        self.memory = memory

    def run(self, args: dict[str, Any]) -> ToolResult:
        ref = str(args.get("ref", "")).strip()
        if not ref:
            return ToolResult(ok=False, output="Missing tool output ref.")

        try:
            record = self.memory.read_tool_output(ref)
        except ValueError as exc:
            return ToolResult(ok=False, output=str(exc))

        max_chars = max(200, int(args.get("max_chars", 2_000)))
        selected, selection = self._select_output(record=record, args=args, max_chars=max_chars)
        query = str(selection.get("query", "")).strip()
        line_start = self._optional_int(selection.get("line_start"))
        line_end = self._optional_int(selection.get("line_end"))
        focus = str(selection.get("focus", "")).strip()
        intent = str(selection.get("intent", "")).strip()
        hint_kind = str(selection.get("hint_kind", "")).strip()
        hint_index = self._optional_int(selection.get("hint_index"))
        remaining_hints = self._optional_int(selection.get("remaining_hints"))

        lines = [
            (
                "[tool_output_lookup] "
                f"source_id={record.get('output_id')} "
                f"source_tool={record.get('tool')} "
                f"chars={record.get('output_chars')} "
                f"selected_chars={len(selected)}"
            )
        ]
        if query:
            lines.append(f"query={query}")
        if focus:
            lines.append(f"focus={focus}")
        if intent:
            lines.append(f"intent={intent}")
        if hint_kind:
            lines.append(f"hint_kind={hint_kind}")
        if hint_index is not None:
            lines.append(f"hint_index={hint_index}")
        if remaining_hints is not None:
            lines.append(f"remaining_hints={remaining_hints}")
        if line_start is not None or line_end is not None:
            lines.append(f"line_range={line_start or 1}:{line_end or 'end'}")
        if selection.get("reason"):
            lines.append(f"reason={selection.get('reason')}")
        lines.extend(["", selected])
        return ToolResult(
            ok=True,
            output="\n".join(lines),
            metadata={
                "source_output_id": record.get("output_id"),
                "source_tool": record.get("tool"),
                "focus": focus,
                "intent": intent,
                "reason": selection.get("reason", ""),
                "query": query,
                "line_start": line_start,
                "line_end": line_end,
                "hint_kind": hint_kind,
                "hint_index": hint_index,
                "remaining_hints": remaining_hints,
                "exclude_queries_count": int(selection.get("exclude_queries_count", 0)),
            },
        )

    def _select_output(
        self,
        record: dict[str, Any],
        args: dict[str, Any],
        max_chars: int,
    ) -> tuple[str, dict[str, Any]]:
        output = str(record.get("output", ""))
        line_start = self._optional_int(args.get("line_start"))
        line_end = self._optional_int(args.get("line_end"))
        if line_start is not None or line_end is not None:
            return (
                self._select_by_line_range(output, line_start, line_end, max_chars),
                {
                    "query": "",
                    "focus": "",
                    "reason": "",
                    "line_start": line_start,
                    "line_end": line_end,
                },
            )

        query = str(args.get("query", "")).strip()
        if query:
            return (
                self._select_by_query(output, query, max_chars),
                {
                    "query": query,
                    "focus": "",
                    "reason": "",
                    "line_start": None,
                    "line_end": None,
                },
            )

        focus = str(args.get("focus", "")).strip().lower()
        if focus == "auto":
            return self._select_auto(
                record=record,
                max_chars=max_chars,
                hint_index=args.get("hint_index"),
                intent=args.get("intent"),
                exclude_queries=args.get("exclude_queries"),
            )

        return (
            self._truncate(output, max_chars, "...[lookup result truncated]..."),
            {
                "query": "",
                "focus": "",
                "reason": "",
                "line_start": None,
                "line_end": None,
            },
        )

    def _select_auto(
        self,
        record: dict[str, Any],
        max_chars: int,
        hint_index: Any,
        intent: Any,
        exclude_queries: Any,
    ) -> tuple[str, dict[str, Any]]:
        plan = record.get("lookup_plan", {})
        output = str(record.get("output", ""))
        parsed_excludes = self._string_list(exclude_queries)
        selected_hint, selection = select_lookup_hint(
            plan if isinstance(plan, dict) else {},
            intent=str(intent or ""),
            exclude_queries=parsed_excludes,
            hint_index=self._optional_int(hint_index),
        )
        if not selected_hint:
            return (
                self._truncate(output, max_chars, "...[lookup result truncated]..."),
                {
                    "query": "",
                    "focus": "auto",
                    "intent": str(intent or "").strip().lower(),
                    "reason": str(selection.get("selection_reason", "no_lookup_plan")),
                    "line_start": None,
                    "line_end": None,
                    "hint_kind": "",
                    "hint_index": None,
                    "remaining_hints": 0,
                    "exclude_queries_count": len(parsed_excludes),
                },
            )

        query = str(selected_hint.get("query", "")).strip()
        line_start = self._optional_int(selected_hint.get("line_start"))
        line_end = self._optional_int(selected_hint.get("line_end"))
        if query:
            selected = self._select_by_query(output, query, max_chars)
        else:
            selected = self._select_by_line_range(output, line_start, line_end, max_chars)
        return (
            selected,
            {
                "query": query,
                "focus": "auto",
                "intent": str(selection.get("intent", "")),
                "reason": str(selection.get("selection_reason", "")),
                "line_start": line_start,
                "line_end": line_end,
                "hint_kind": str(selection.get("hint_kind", "")),
                "hint_index": self._optional_int(selection.get("hint_index")),
                "remaining_hints": self._optional_int(selection.get("remaining_hints")),
                "exclude_queries_count": int(selection.get("excluded_count", 0)),
            },
        )

    def _select_by_line_range(
        self,
        output: str,
        line_start: int | None,
        line_end: int | None,
        max_chars: int,
    ) -> str:
        lines = output.splitlines()
        start = max(1, line_start or 1)
        end = min(len(lines), line_end or len(lines))
        if start > end:
            return "(empty line range)"
        selected = "\n".join(lines[start - 1 : end])
        return self._truncate(selected, max_chars, "...[lookup line range truncated]...")

    def _select_by_query(self, output: str, query: str, max_chars: int) -> str:
        lower_output = output.lower()
        lower_query = query.lower()
        index = lower_output.find(lower_query)
        if index < 0:
            return self._truncate(
                f"Query not found: {query}\n\n" + output,
                max_chars,
                "...[lookup result truncated]...",
            )
        radius = max(120, max_chars // 2)
        start = max(0, index - radius)
        end = min(len(output), index + len(query) + radius)
        excerpt = output[start:end]
        if start > 0:
            excerpt = "...[lookup excerpt truncated before match]...\n" + excerpt
        if end < len(output):
            excerpt = excerpt + "\n...[lookup excerpt truncated after match]..."
        return excerpt

    def _truncate(self, content: str, max_chars: int, marker: str) -> str:
        if len(content) <= max_chars:
            return content
        half = max(1, max_chars // 2)
        return content[:half] + "\n\n" + marker + "\n\n" + content[-half:]

    def _optional_int(self, value: Any) -> int | None:
        if value in (None, ""):
            return None
        return int(value)

    def _string_list(self, value: Any) -> list[str]:
        if value in (None, ""):
            return []
        if isinstance(value, str):
            parts = [item.strip() for item in value.split(",")]
            return [item for item in parts if item]
        if isinstance(value, list):
            return [
                str(item).strip()
                for item in value
                if str(item).strip()
            ]
        return [str(value).strip()] if str(value).strip() else []
