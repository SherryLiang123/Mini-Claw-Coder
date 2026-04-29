from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path

from mini_claw.workspace_policy import is_ignored_path

TEXT_SUFFIXES = {
    ".cfg",
    ".css",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".jsx",
    ".md",
    ".py",
    ".rst",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".yaml",
    ".yml",
}

LANGUAGE_BY_SUFFIX = {
    ".css": "css",
    ".html": "html",
    ".js": "javascript",
    ".json": "json",
    ".jsx": "javascript",
    ".md": "markdown",
    ".py": "python",
    ".toml": "toml",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".yaml": "yaml",
    ".yml": "yaml",
}


@dataclass(frozen=True)
class FileIndexEntry:
    path: str
    size_bytes: int
    language: str
    symbols: list[str]
    preview: str
    score: int = 0

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def build_file_index(
    workspace: Path,
    query: str = "",
    limit: int = 60,
    preview_lines: int = 3,
    max_preview_bytes: int = 80_000,
) -> list[FileIndexEntry]:
    root = workspace.resolve()
    entries: list[FileIndexEntry] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if _is_ignored(rel):
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            size = path.stat().st_size
        except OSError:
            continue
        preview = ""
        symbols: list[str] = []
        if size <= max_preview_bytes:
            content = _read_text(path)
            preview = _preview(content, preview_lines)
            symbols = _symbols(path, content)
        entries.append(
            FileIndexEntry(
                path=rel.as_posix(),
                size_bytes=size,
                language=LANGUAGE_BY_SUFFIX.get(path.suffix.lower(), "text"),
                symbols=symbols[:8],
                preview=preview,
            )
        )

    scored = [_with_score(entry, query) for entry in entries]
    return sorted(scored, key=lambda entry: (-entry.score, entry.path))[:limit]


def render_file_index(
    workspace: Path,
    query: str = "",
    limit: int = 40,
    preview_lines: int = 2,
) -> str:
    entries = build_file_index(
        workspace=workspace,
        query=query,
        limit=limit,
        preview_lines=preview_lines,
    )
    if not entries:
        return "(no indexed text files)"

    lines = [
        "Progressive disclosure: this is a file preview index, not full file content.",
        "Use read to inspect full file contents only when needed.",
        "",
    ]
    for entry in entries:
        symbol_text = ", ".join(entry.symbols) if entry.symbols else "-"
        lines.append(
            f"- {entry.path} [{entry.language}, {entry.size_bytes} bytes, score={entry.score}]"
        )
        lines.append(f"  symbols: {symbol_text}")
        if entry.preview:
            preview = entry.preview.replace("\n", " | ")
            lines.append(f"  preview: {preview}")
    return "\n".join(lines)


def _is_ignored(path: Path) -> bool:
    return is_ignored_path(path)


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _preview(content: str, preview_lines: int) -> str:
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    return "\n".join(lines[:preview_lines])


def _symbols(path: Path, content: str) -> list[str]:
    suffix = path.suffix.lower()
    symbols: list[str] = []
    if suffix == ".py":
        patterns = [
            r"^\s*class\s+([A-Za-z_][A-Za-z0-9_]*)",
            r"^\s*def\s+([A-Za-z_][A-Za-z0-9_]*)",
        ]
    elif suffix in {".js", ".jsx", ".ts", ".tsx"}:
        patterns = [
            r"^\s*class\s+([A-Za-z_][A-Za-z0-9_]*)",
            r"^\s*function\s+([A-Za-z_][A-Za-z0-9_]*)",
            r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_][A-Za-z0-9_]*)",
        ]
    elif suffix == ".md":
        patterns = [r"^#{1,3}\s+(.+)"]
    else:
        patterns = []

    for line in content.splitlines():
        for pattern in patterns:
            match = re.match(pattern, line)
            if match:
                symbol = match.group(1).strip()
                if symbol not in symbols:
                    symbols.append(symbol)
                break
        if len(symbols) >= 12:
            break
    return symbols


def _with_score(entry: FileIndexEntry, query: str) -> FileIndexEntry:
    terms = {
        token.lower()
        for token in re.split(r"[^A-Za-z0-9_]+", query)
        if len(token) >= 3
    }
    if not terms:
        return entry
    haystack = " ".join([entry.path, entry.language, " ".join(entry.symbols), entry.preview]).lower()
    score = sum(3 if term in entry.path.lower() else 1 for term in terms if term in haystack)
    return FileIndexEntry(
        path=entry.path,
        size_bytes=entry.size_bytes,
        language=entry.language,
        symbols=entry.symbols,
        preview=entry.preview,
        score=score,
    )
