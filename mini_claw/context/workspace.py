from __future__ import annotations

from pathlib import Path

from mini_claw.workspace_policy import is_ignored_path


def ensure_inside_workspace(workspace: Path, user_path: str) -> Path:
    root = workspace.resolve()
    target = (root / user_path).resolve()
    if target != root and root not in target.parents:
        raise ValueError(f"Path escapes workspace: {user_path}")
    return target


def snapshot_tree(workspace: Path, limit: int = 80) -> str:
    rows: list[str] = []
    for path in sorted(workspace.rglob("*")):
        rel = path.relative_to(workspace)
        if is_ignored_path(rel):
            continue
        rows.append(str(rel) + ("/" if path.is_dir() else ""))
        if len(rows) >= limit:
            rows.append("...")
            break
    return "\n".join(rows) if rows else "(empty workspace)"
