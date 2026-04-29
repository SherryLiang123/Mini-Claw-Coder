from __future__ import annotations

import re
from typing import Any

ERROR_KEYWORDS = (
    "traceback",
    "error",
    "exception",
    "failed",
    "assert",
    "modulenotfounderror",
    "importerror",
    "syntaxerror",
    "nameerror",
    "valueerror",
    "keyerror",
    "filenotfounderror",
)

UPPER_TOKEN_PATTERN = re.compile(r"\b[A-Z][A-Z0-9_]{5,}\b")
QUOTED_PATTERN = re.compile(r"['\"]([^'\"]{4,80})['\"]")
PATH_PATTERN = re.compile(
    r"(?:[A-Za-z]:)?[\w./\\-]+\.(?:py|js|ts|tsx|jsx|json|jsonl|md|txt|yaml|yml|toml|ini|cfg)"
)
WORD_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_/-]{3,}")
INTENT_KIND_MAP = {
    "error": {"error_token", "traceback"},
    "path": {"path"},
    "symbol": {"symbol"},
    "task": {"task_term"},
    "fallback": {"fallback"},
}


def build_lookup_plan(
    output: str,
    task: str = "",
    tool: str = "",
    args: dict[str, Any] | None = None,
    limit: int = 5,
) -> dict[str, Any]:
    text = output or ""
    if not text.strip():
        return {"tool": tool, "hints": []}

    lines = text.splitlines() or [text]
    task_terms = _task_terms(task)
    hints: list[dict[str, Any]] = []
    seen_queries: set[str] = set()

    for index, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("...["):
            continue
        lower = stripped.lower()
        score = 0
        reasons: list[str] = []

        if any(keyword in lower for keyword in ERROR_KEYWORDS):
            score += 12
            reasons.append("error_signal")
        if "traceback" in lower:
            score += 6
            reasons.append("traceback")

        upper_tokens = UPPER_TOKEN_PATTERN.findall(stripped)
        if upper_tokens:
            score += 8
            reasons.append("high_signal_token")

        quoted_values = [
            value.strip()
            for value in QUOTED_PATTERN.findall(stripped)
            if _is_useful_query(value)
        ]
        if quoted_values:
            score += 5
            reasons.append("quoted_value")

        path_values = [
            match.group(0).replace("\\", "/")
            for match in PATH_PATTERN.finditer(stripped)
        ]
        if path_values:
            score += 5
            reasons.append("path_or_file")

        task_hits = [term for term in task_terms if term in lower]
        if task_hits:
            score += min(6, len(task_hits) * 2)
            reasons.append("task_overlap")

        if score <= 0:
            continue

        query = _pick_query(
            upper_tokens=upper_tokens,
            quoted_values=quoted_values,
            path_values=path_values,
            task_hits=task_hits,
            fallback=stripped,
        )
        if not query:
            continue
        dedupe_key = query.lower()
        if dedupe_key in seen_queries:
            continue
        seen_queries.add(dedupe_key)

        hints.append(
            {
                "query": query,
                "kind": _classify_hint(
                    lower=lower,
                    upper_tokens=upper_tokens,
                    quoted_values=quoted_values,
                    path_values=path_values,
                    task_hits=task_hits,
                ),
                "line_start": max(1, index - 2),
                "line_end": min(len(lines), index + 2),
                "reason": ",".join(reasons),
                "preview": stripped[:120],
                "score": score,
            }
        )

    hints.sort(key=lambda item: (-int(item.get("score", 0)), str(item.get("query", ""))))
    if not hints:
        fallback = _fallback_hint(lines)
        return {"tool": tool, "hints": [fallback] if fallback else []}

    return {"tool": tool, "hints": hints[:limit]}


def summarize_lookup_queries(plan: dict[str, Any], limit: int = 3) -> list[str]:
    queries: list[str] = []
    raw_hints = plan.get("hints", [])
    if not isinstance(raw_hints, list):
        return queries
    for hint in raw_hints:
        if not isinstance(hint, dict):
            continue
        query = str(hint.get("query", "")).strip()
        if not query or query in queries:
            continue
        queries.append(query)
        if len(queries) >= limit:
            break
    return queries


def select_lookup_hint(
    plan: dict[str, Any],
    intent: str = "",
    exclude_queries: list[str] | None = None,
    hint_index: int | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    raw_hints = plan.get("hints", [])
    hints = [hint for hint in raw_hints if isinstance(hint, dict)]
    if not hints:
        return None, {
            "intent": intent.strip().lower(),
            "hint_index": None,
            "remaining_hints": 0,
            "selection_reason": "no_lookup_plan",
        }

    normalized_intent = intent.strip().lower()
    excluded = {
        query.strip().lower()
        for query in (exclude_queries or [])
        if query and query.strip()
    }
    selection_reason: list[str] = []

    filtered = [
        hint
        for hint in hints
        if str(hint.get("query", "")).strip().lower() not in excluded
    ]
    if excluded and len(filtered) != len(hints):
        selection_reason.append("exclude_queries_applied")
    if not filtered:
        filtered = hints
        if excluded:
            selection_reason.append("exclude_queries_exhausted")

    if normalized_intent:
        allowed_kinds = INTENT_KIND_MAP.get(normalized_intent, {normalized_intent})
        intent_filtered = [
            hint
            for hint in filtered
            if str(hint.get("kind", "")).strip().lower() in allowed_kinds
        ]
        if intent_filtered:
            filtered = intent_filtered
            selection_reason.append(f"intent={normalized_intent}")
        else:
            selection_reason.append(f"intent_fallback={normalized_intent}")

    index = max(1, int(hint_index or 1))
    if index > len(filtered):
        selection_reason.append("hint_index_clamped")
        index = len(filtered)

    selected = filtered[index - 1]
    reason_parts = [str(selected.get("reason", "")).strip()] + selection_reason
    return selected, {
        "intent": normalized_intent,
        "hint_index": index,
        "remaining_hints": max(0, len(filtered) - index),
        "selection_reason": ",".join(part for part in reason_parts if part),
        "excluded_count": len(excluded),
        "hint_kind": str(selected.get("kind", "")).strip(),
    }


def _task_terms(task: str) -> set[str]:
    return {
        token.lower()
        for token in WORD_PATTERN.findall(task)
        if len(token) >= 4
    }


def _pick_query(
    upper_tokens: list[str],
    quoted_values: list[str],
    path_values: list[str],
    task_hits: list[str],
    fallback: str,
) -> str:
    if path_values:
        return path_values[0]
    if upper_tokens:
        return upper_tokens[0]
    if quoted_values:
        return quoted_values[0]
    if task_hits:
        return task_hits[0]
    trimmed = fallback[:80].strip()
    return trimmed if _is_useful_query(trimmed) else ""


def _classify_hint(
    lower: str,
    upper_tokens: list[str],
    quoted_values: list[str],
    path_values: list[str],
    task_hits: list[str],
) -> str:
    if "traceback" in lower:
        return "traceback"
    if any(keyword in lower for keyword in ERROR_KEYWORDS) and quoted_values:
        return "error_token"
    if path_values:
        return "path"
    if upper_tokens:
        return "symbol"
    if task_hits:
        return "task_term"
    return "fallback"


def _fallback_hint(lines: list[str]) -> dict[str, Any] | None:
    for index, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped:
            continue
        query = stripped[:80]
        if not _is_useful_query(query):
            continue
        return {
            "query": query,
            "line_start": max(1, index - 1),
            "line_end": min(len(lines), index + 1),
            "reason": "fallback",
            "preview": stripped[:120],
            "score": 1,
        }
    return None


def _is_useful_query(value: str) -> bool:
    stripped = value.strip()
    if len(stripped) < 4:
        return False
    if stripped.startswith("...[") and stripped.endswith("]..."):
        return False
    return True
