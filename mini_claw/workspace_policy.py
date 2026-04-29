from __future__ import annotations

from pathlib import Path


CORE_IGNORED_PARTS = {
    ".git",
    ".mini_claw",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
}

# Keep reference snapshots and sibling experiments out of default discovery so
# repository inspection stays focused on the main coding workspace.
REFERENCE_IGNORED_PARTS = {
    ".external",
    "sibling-project",
}

DEFAULT_DISCOVERY_IGNORED_PARTS = CORE_IGNORED_PARTS | REFERENCE_IGNORED_PARTS


def is_hidden_path(path: Path) -> bool:
    return any(part.startswith(".") for part in path.parts if part not in {".", ""})


def is_ignored_path(
    path: Path,
    *,
    include_hidden: bool = False,
    ignored_parts: set[str] | None = None,
) -> bool:
    normalized = Path(path)
    if not include_hidden and is_hidden_path(normalized):
        return True
    active_ignored_parts = ignored_parts or DEFAULT_DISCOVERY_IGNORED_PARTS
    return any(part in active_ignored_parts for part in normalized.parts)


def render_discovery_ignore_hint() -> str:
    focused = ", ".join(sorted(REFERENCE_IGNORED_PARTS))
    return f"Ignore reference or sibling-project roots by default: {focused}."
