from __future__ import annotations

import difflib
from dataclasses import asdict, dataclass

from mini_claw.safety.snapshot import FileSnapshot


@dataclass(frozen=True)
class FileDiffSummary:
    path: str
    status: str
    added_lines: int
    removed_lines: int
    unified_diff: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def build_diff_summaries(
    before: dict[str, FileSnapshot],
    after: dict[str, FileSnapshot],
    max_diff_chars: int = 4_000,
) -> list[FileDiffSummary]:
    summaries: list[FileDiffSummary] = []
    for path in sorted(set(before) | set(after)):
        old = before.get(path)
        new = after.get(path)
        old_content = old.content if old and old.content is not None else ""
        new_content = new.content if new and new.content is not None else ""
        if old_content == new_content and (old and old.exists) == (new and new.exists):
            continue

        old_exists = bool(old and old.exists)
        new_exists = bool(new and new.exists)
        if old_exists and new_exists:
            status = "modified"
        elif new_exists:
            status = "added"
        else:
            status = "deleted"

        diff_lines = list(
            difflib.unified_diff(
                old_content.splitlines(),
                new_content.splitlines(),
                fromfile=f"a/{path}",
                tofile=f"b/{path}",
                lineterm="",
            )
        )
        added = sum(1 for line in diff_lines if line.startswith("+") and not line.startswith("+++"))
        removed = sum(1 for line in diff_lines if line.startswith("-") and not line.startswith("---"))
        unified = "\n".join(diff_lines)
        if len(unified) > max_diff_chars:
            unified = unified[:max_diff_chars] + "\n...[diff truncated]..."

        summaries.append(
            FileDiffSummary(
                path=path,
                status=status,
                added_lines=added,
                removed_lines=removed,
                unified_diff=unified,
            )
        )
    return summaries

