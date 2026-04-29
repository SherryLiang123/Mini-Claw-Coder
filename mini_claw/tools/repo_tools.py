from __future__ import annotations

import re
import shutil
import subprocess
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

from mini_claw.context.workspace import ensure_inside_workspace
from mini_claw.memory.store import MemoryStore
from mini_claw.safety.snapshot import FileSnapshot
from mini_claw.tools.base import ToolResult
from mini_claw.workspace_policy import (
    DEFAULT_DISCOVERY_IGNORED_PARTS,
    is_hidden_path,
    is_ignored_path,
)

TEXT_READ_BLOCK_BYTES = 8192


class _WorkspaceTool:
    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.resolve()

    def _resolve_target(self, raw_path: str) -> tuple[Path, str]:
        user_path = raw_path.strip() or "."
        target = ensure_inside_workspace(self.workspace, user_path)
        rel = str(target.relative_to(self.workspace)).replace("\\", "/")
        return target, rel or "."

    def _is_hidden(self, path: Path) -> bool:
        return is_hidden_path(path)

    def _is_ignored(self, path: Path, include_hidden: bool = False) -> bool:
        return is_ignored_path(path, include_hidden=include_hidden)

    def _format_entry(self, rel: Path, target: Path) -> str:
        suffix = "/" if target.is_dir() else ""
        return rel.as_posix() + suffix


class ListFilesTool(_WorkspaceTool):
    name = "ls"

    def run(self, args: dict[str, Any]) -> ToolResult:
        raw_path = str(args.get("path", "."))
        limit = max(1, min(200, int(args.get("limit", 100))))
        offset = max(0, int(args.get("offset", 0)))
        include_hidden = bool(args.get("include_hidden", False))

        try:
            target, rel = self._resolve_target(raw_path)
        except ValueError as exc:
            return ToolResult(ok=False, output=str(exc))
        if not target.exists():
            return ToolResult(ok=False, output=f"Path not found: {raw_path}")

        if target.is_file():
            entries = [rel]
        else:
            children = sorted(
                [
                    child
                    for child in target.iterdir()
                    if not self._is_ignored(child.relative_to(self.workspace), include_hidden)
                ],
                key=lambda child: (0 if child.is_dir() else 1, child.name.lower()),
            )
            entries = [
                self._format_entry(child.relative_to(self.workspace), child)
                for child in children
            ]

        selected = entries[offset : offset + limit]
        truncated = offset > 0 or offset + len(selected) < len(entries)
        lines = [
            f"[ls] path={rel} total={len(entries)} returned={len(selected)} truncated={truncated}",
        ]
        if selected:
            lines.extend(["", "\n".join(selected)])
        return ToolResult(
            ok=True,
            output="\n".join(lines),
            metadata={
                "path": rel,
                "total_entries": len(entries),
                "returned_entries": len(selected),
                "truncated": truncated,
            },
        )


class GlobTool(_WorkspaceTool):
    name = "glob"

    def run(self, args: dict[str, Any]) -> ToolResult:
        pattern = str(args.get("pattern", "")).strip()
        raw_path = str(args.get("path", "."))
        limit = max(1, min(200, int(args.get("limit", 100))))
        include_hidden = bool(args.get("include_hidden", False))
        if not pattern:
            return ToolResult(ok=False, output="Missing glob pattern.")

        try:
            root, rel = self._resolve_target(raw_path)
        except ValueError as exc:
            return ToolResult(ok=False, output=str(exc))
        if not root.exists():
            return ToolResult(ok=False, output=f"Path not found: {raw_path}")
        if not root.is_dir():
            return ToolResult(ok=False, output=f"Glob requires a directory: {rel}")

        matches: list[str] = []
        truncated = False
        for item in sorted(root.rglob("*")):
            relative_to_workspace = item.relative_to(self.workspace)
            if self._is_ignored(relative_to_workspace, include_hidden):
                continue
            relative_to_root = item.relative_to(root).as_posix()
            if not self._glob_matches(relative_to_root, pattern):
                continue
            matches.append(self._format_entry(relative_to_workspace, item))
            if len(matches) >= limit:
                truncated = True
                break

        lines = [
            f"[glob] path={rel} pattern={pattern} matched={len(matches)} truncated={truncated}",
        ]
        if matches:
            lines.extend(["", "\n".join(matches)])
        return ToolResult(
            ok=True,
            output="\n".join(lines),
            metadata={
                "path": rel,
                "pattern": pattern,
                "matched": len(matches),
                "truncated": truncated,
            },
        )

    def _glob_matches(self, relative_path: str, pattern: str) -> bool:
        return fnmatch(relative_path, pattern) or (
            pattern.startswith("**/") and fnmatch(relative_path, pattern[3:])
        )


class GrepTool(_WorkspaceTool):
    name = "grep"

    def run(self, args: dict[str, Any]) -> ToolResult:
        pattern = str(args.get("pattern", "")).strip()
        raw_path = str(args.get("path", "."))
        include = str(args.get("include", "")).strip()
        case_sensitive = bool(args.get("case_sensitive", False))
        limit = max(1, min(200, int(args.get("limit", 100))))
        if not pattern:
            return ToolResult(ok=False, output="Missing grep pattern.")

        try:
            root, rel = self._resolve_target(raw_path)
        except ValueError as exc:
            return ToolResult(ok=False, output=str(exc))
        if not root.exists():
            return ToolResult(ok=False, output=f"Path not found: {raw_path}")
        if not root.is_dir():
            return ToolResult(ok=False, output=f"Grep requires a directory: {rel}")

        try:
            if shutil.which("rg"):
                matches = self._grep_with_rg(
                    pattern=pattern,
                    root=root,
                    include=include or None,
                    case_sensitive=case_sensitive,
                    limit=limit,
                )
            else:
                matches = self._grep_with_python(
                    pattern=pattern,
                    root=root,
                    include=include or None,
                    case_sensitive=case_sensitive,
                    limit=limit,
                )
        except (OSError, re.error, RuntimeError) as exc:
            return ToolResult(ok=False, output=f"grep failed: {exc}")

        truncated = len(matches) >= limit
        rendered = "\n".join(
            f"{match['path']}:{match['line']}: {match['text']}" for match in matches[:limit]
        )
        lines = [
            (
                f"[grep] path={rel} pattern={pattern} matched={min(len(matches), limit)} "
                f"truncated={truncated}"
            )
        ]
        if include:
            lines.append(f"include={include}")
        if rendered:
            lines.extend(["", rendered])
        return ToolResult(
            ok=True,
            output="\n".join(lines),
            metadata={
                "path": rel,
                "pattern": pattern,
                "matched": min(len(matches), limit),
                "truncated": truncated,
                "include": include,
            },
        )

    def _grep_with_rg(
        self,
        *,
        pattern: str,
        root: Path,
        include: str | None,
        case_sensitive: bool,
        limit: int,
    ) -> list[dict[str, Any]]:
        command = ["rg", "--line-number", "--no-heading", "--color", "never", "--max-count", str(limit)]
        if not case_sensitive:
            command.append("-i")
        if include:
            command.extend(["-g", include])
        for ignored in sorted(DEFAULT_DISCOVERY_IGNORED_PARTS):
            command.extend(["-g", f"!{ignored}/**"])
        command.extend([pattern, str(root.relative_to(self.workspace)) if root != self.workspace else "."])

        completed = subprocess.run(
            command,
            cwd=self.workspace,
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode == 1:
            return []
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or "rg search failed")

        matches: list[dict[str, Any]] = []
        for line in completed.stdout.splitlines():
            file_part, line_part, text_part = line.split(":", 2)
            matches.append(
                {
                    "path": Path(file_part).as_posix(),
                    "line": int(line_part),
                    "text": text_part,
                }
            )
        return matches

    def _grep_with_python(
        self,
        *,
        pattern: str,
        root: Path,
        include: str | None,
        case_sensitive: bool,
        limit: int,
    ) -> list[dict[str, Any]]:
        regex = re.compile(pattern, 0 if case_sensitive else re.IGNORECASE)
        matches: list[dict[str, Any]] = []
        for item in sorted(root.rglob("*")):
            if not item.is_file():
                continue
            relative_to_workspace = item.relative_to(self.workspace)
            if self._is_ignored(relative_to_workspace):
                continue
            if include and not fnmatch(item.relative_to(root).as_posix(), include):
                continue
            if self._looks_binary(item):
                continue
            try:
                content = item.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for index, line in enumerate(content.splitlines(), start=1):
                if regex.search(line):
                    matches.append(
                        {
                            "path": relative_to_workspace.as_posix(),
                            "line": index,
                            "text": line,
                        }
                    )
                    if len(matches) >= limit:
                        return matches
        return matches

    def _looks_binary(self, path: Path) -> bool:
        try:
            return b"\x00" in path.read_bytes()[:TEXT_READ_BLOCK_BYTES]
        except OSError:
            return True


class ReadTool(_WorkspaceTool):
    name = "read"

    def __init__(self, workspace: Path, memory: MemoryStore | None = None) -> None:
        super().__init__(workspace)
        self.memory = memory

    def run(self, args: dict[str, Any]) -> ToolResult:
        raw_path = str(args.get("path", "")).strip()
        start_line = max(1, int(args.get("start_line", 1)))
        limit = max(1, min(2_000, int(args.get("limit", 400))))
        if not raw_path:
            return ToolResult(ok=False, output="Missing read path.")

        try:
            target, rel = self._resolve_target(raw_path)
        except ValueError as exc:
            return ToolResult(ok=False, output=str(exc))
        if not target.exists():
            return ToolResult(ok=False, output=f"Path not found: {raw_path}")
        if target.is_dir():
            return ToolResult(ok=False, output=f"Read requires a file path: {rel}")
        if self._looks_binary(target):
            return ToolResult(ok=False, output=f"Binary files are not supported by read: {rel}")

        try:
            content = target.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return ToolResult(ok=False, output=f"Read supports UTF-8 text files only: {rel}")
        except OSError as exc:
            return ToolResult(ok=False, output=f"Read failed for {rel}: {exc}")

        lines = content.splitlines()
        if lines and start_line > len(lines):
            return ToolResult(
                ok=False,
                output=f"start_line out of range for {rel}: total_lines={len(lines)}",
            )

        start_index = start_line - 1
        selected_lines = lines[start_index : start_index + limit]
        numbered = "\n".join(
            f"{index:4d} | {line}"
            for index, line in enumerate(selected_lines, start=start_line)
        )
        end_line = start_line + len(selected_lines) - 1 if selected_lines else 0
        truncated = start_index + len(selected_lines) < len(lines)
        snapshot = FileSnapshot.capture(self.workspace, target)
        if self.memory is not None:
            self.memory.record_read_snapshot(rel, snapshot, source="read")

        output_lines = [
            (
                f"[read] path={rel} lines={len(lines)} returned={len(selected_lines)} "
                f"range={start_line}:{end_line or start_line} truncated={truncated}"
            ),
            f"sha256={snapshot.sha256}",
        ]
        if numbered:
            output_lines.extend(["", numbered])
        return ToolResult(
            ok=True,
            output="\n".join(output_lines),
            metadata={
                "path": rel,
                "start_line": start_line,
                "end_line": end_line,
                "total_lines": len(lines),
                "truncated": truncated,
                "sha256": snapshot.sha256,
            },
        )

    def _looks_binary(self, path: Path) -> bool:
        try:
            return b"\x00" in path.read_bytes()[:TEXT_READ_BLOCK_BYTES]
        except OSError:
            return True


class MkdirTool(_WorkspaceTool):
    name = "mkdir"

    def run(self, args: dict[str, Any]) -> ToolResult:
        raw_path = str(args.get("path", "")).strip()
        if not raw_path or raw_path == ".":
            return ToolResult(ok=False, output="Missing directory path.")

        try:
            target, rel = self._resolve_target(raw_path)
        except ValueError as exc:
            return ToolResult(ok=False, output=str(exc))

        if target.exists():
            if target.is_dir():
                return ToolResult(
                    ok=True,
                    output=f"[mkdir] path={rel} operation=existing",
                    metadata={"path": rel, "operation": "existing", "entry_type": "dir"},
                )
            return ToolResult(ok=False, output=f"mkdir target is an existing file: {rel}")

        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return ToolResult(ok=False, output=f"mkdir failed for {rel}: {exc}")
        return ToolResult(
            ok=True,
            output=f"[mkdir] path={rel} operation=create",
            modified_files=[f"{rel}/"],
            metadata={"path": rel, "operation": "create", "entry_type": "dir"},
        )


class _MutationTool(_WorkspaceTool):
    def __init__(
        self,
        workspace: Path,
        *,
        memory: MemoryStore | None = None,
        dry_run: bool = False,
        require_read_snapshot: bool = False,
    ) -> None:
        super().__init__(workspace)
        self.memory = memory
        self.dry_run = dry_run
        self.require_read_snapshot = require_read_snapshot

    def _capture_snapshot(self, target: Path) -> FileSnapshot:
        try:
            return FileSnapshot.capture(self.workspace, target)
        except UnicodeDecodeError as exc:
            raise ValueError(f"Only UTF-8 text files are supported: {target.name}") from exc

    def _resolve_expected_sha(self, rel: str, args: dict[str, Any]) -> tuple[str | None, bool]:
        raw = str(args.get("expected_sha256", "")).strip()
        if raw:
            return raw, False
        if self.memory is None:
            return None, False
        snapshot = self.memory.latest_read_snapshot(rel)
        if snapshot and snapshot.get("sha256"):
            return str(snapshot["sha256"]), True
        return None, False

    def _require_fresh_snapshot(
        self,
        rel: str,
        target: Path,
        args: dict[str, Any],
        *,
        for_overwrite: bool = True,
    ) -> FileSnapshot:
        current = self._capture_snapshot(target)
        expected_sha, from_memory = self._resolve_expected_sha(rel, args)
        if not current.exists:
            return current
        if expected_sha is None:
            if self.require_read_snapshot:
                raise ValueError(
                    f"READ_BEFORE_WRITE_REQUIRED: {rel} must be read before writing. "
                    "Use the read tool first, then retry."
                )
            if for_overwrite and not bool(args.get("allow_overwrite", False)):
                raise ValueError(
                    f"OVERWRITE_LOCK_REQUIRED: {rel} exists already. "
                    "Read the file first or pass allow_overwrite=true."
                )
            return current
        if current.sha256 != expected_sha:
            prefix = "STALE_READ_SNAPSHOT" if from_memory else "HASH_PRECONDITION_FAILED"
            raise ValueError(
                f"{prefix}: {rel} changed after it was read. "
                f"expected {expected_sha}, current {current.sha256}."
            )
        return current

    def _record_written_snapshot(self, rel: str, target: Path, source: str) -> FileSnapshot:
        snapshot = self._capture_snapshot(target)
        if self.memory is not None:
            self.memory.record_read_snapshot(rel, snapshot, source=source)
        return snapshot


class EditTool(_MutationTool):
    name = "edit"

    def run(self, args: dict[str, Any]) -> ToolResult:
        raw_path = str(args.get("path", "")).strip()
        old = str(args.get("old", args.get("old_string", "")))
        new = str(args.get("new", args.get("new_string", "")))
        if not raw_path:
            return ToolResult(ok=False, output="Missing edit path.")
        if not old:
            return ToolResult(ok=False, output="Edit requires a non-empty old string.")

        try:
            target, rel = self._resolve_target(raw_path)
            if not target.exists():
                return ToolResult(ok=False, output=f"Path not found: {raw_path}")
            if target.is_dir():
                return ToolResult(ok=False, output=f"Edit requires a file path: {rel}")
            current = self._require_fresh_snapshot(rel, target, args, for_overwrite=False)
            content = current.content or ""
            occurrences = content.count(old)
            if occurrences == 0:
                return ToolResult(ok=False, output=f"old text not found in {rel}")
            if occurrences > 1:
                return ToolResult(
                    ok=False,
                    output=f"old text is ambiguous in {rel}; refine the edit context",
                )
            updated = content.replace(old, new, 1)
            if not self.dry_run:
                target.write_text(updated, encoding="utf-8")
                written = self._record_written_snapshot(rel, target, source="edit")
                digest = written.sha256
            else:
                digest = current.sha256
            prefix = "dry-run: " if self.dry_run else ""
            return ToolResult(
                ok=True,
                output=f"{prefix}[edit] path={rel} replacements=1",
                modified_files=[rel],
                metadata={"path": rel, "replacements": 1, "sha256": digest},
            )
        except ValueError as exc:
            return ToolResult(ok=False, output=str(exc))
        except OSError as exc:
            return ToolResult(ok=False, output=f"Edit failed for {raw_path}: {exc}")


class WriteTool(_MutationTool):
    name = "write"

    def run(self, args: dict[str, Any]) -> ToolResult:
        raw_path = str(args.get("path", "")).strip()
        content = str(args.get("content", ""))
        if not raw_path:
            return ToolResult(ok=False, output="Missing write path.")

        try:
            target, rel = self._resolve_target(raw_path)
            existed = target.exists()
            if existed and target.is_dir():
                return ToolResult(ok=False, output=f"Write requires a file path: {rel}")
            if existed:
                self._require_fresh_snapshot(rel, target, args, for_overwrite=True)
            if not self.dry_run:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
                written = self._record_written_snapshot(rel, target, source="write")
                digest = written.sha256
            else:
                digest = self._capture_snapshot(target).sha256 if existed else None
            prefix = "dry-run: " if self.dry_run else ""
            operation = "overwrite" if existed else "create"
            return ToolResult(
                ok=True,
                output=f"{prefix}[write] path={rel} operation={operation}",
                modified_files=[rel],
                metadata={"path": rel, "operation": operation, "sha256": digest},
            )
        except ValueError as exc:
            return ToolResult(ok=False, output=str(exc))
        except OSError as exc:
            return ToolResult(ok=False, output=f"Write failed for {raw_path}: {exc}")
