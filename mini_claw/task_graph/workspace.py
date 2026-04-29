from __future__ import annotations

import filecmp
import json
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from mini_claw.safety.diff import FileDiffSummary, build_diff_summaries
from mini_claw.safety.patch_transaction import PatchTransaction
from mini_claw.safety.snapshot import FileSnapshot


IGNORED_PARTS = {
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

TEXT_FILE_SUFFIXES = {".py", ".md", ".txt", ".json", ".toml", ".yaml", ".yml"}


@dataclass(frozen=True)
class TaskWorkspace:
    task_id: str
    path: str
    mode: str = "copy"

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class WorkspaceManifestEntry:
    exists: bool
    sha256: str | None
    entry_type: str = "file"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_snapshot(cls, snapshot: FileSnapshot) -> "WorkspaceManifestEntry":
        return cls(exists=snapshot.exists, sha256=snapshot.sha256, entry_type=snapshot.entry_type)

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "WorkspaceManifestEntry":
        return cls(
            exists=bool(data.get("exists", False)),
            sha256=str(data["sha256"]) if data.get("sha256") is not None else None,
            entry_type=str(data.get("entry_type", "file") or "file"),
        )


@dataclass(frozen=True)
class WorkspaceMergeConflict:
    path: str
    reason: str
    base_sha256: str | None
    main_sha256: str | None
    task_sha256: str | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class WorkspaceMergeResult:
    ok: bool
    output: str
    merged_files: list[str] = field(default_factory=list)
    conflicts: list[WorkspaceMergeConflict] = field(default_factory=list)
    diff_summary: list[FileDiffSummary] = field(default_factory=list)
    transaction_id: str = ""
    journal_path: str | None = None


class TaskWorkspaceManager:
    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.resolve()
        self.root = self.workspace / ".mini_claw" / "task_workspaces"
        self.git_worktree_root = self.workspace / ".mini_claw" / "task_worktrees"

    def create(self, task_id: str, mode: str = "copy") -> TaskWorkspace:
        if mode not in {"copy", "git-worktree"}:
            raise ValueError(f"Unknown task workspace mode: {mode}")
        if mode == "git-worktree":
            target = self._git_worktree_path(task_id)
            self._create_git_worktree(task_id, target)
        else:
            target = self._task_path(task_id)
            target.mkdir(parents=True, exist_ok=True)
            self._copy_workspace(target)
        self._write_manifest(task_id, self._capture_manifest(self.workspace), mode=mode)
        return TaskWorkspace(task_id=task_id, path=str(target), mode=mode)

    def list(self) -> list[TaskWorkspace]:
        entries: list[TaskWorkspace] = []
        if self.root.exists():
            entries.extend(
                TaskWorkspace(task_id=path.name, path=str(path), mode="copy")
                for path in sorted(self.root.iterdir())
                if path.is_dir()
            )
        if self.git_worktree_root.exists():
            entries.extend(
                TaskWorkspace(task_id=path.name, path=str(path), mode="git-worktree")
                for path in sorted(self.git_worktree_root.iterdir())
                if path.is_dir()
            )
        return entries

    def diff(self, task_id: str, max_diff_chars: int = 4_000) -> list[FileDiffSummary]:
        task_path = self._workspace_path(task_id)
        if not task_path.exists():
            raise ValueError(f"Task workspace does not exist: {task_id}")
        before: dict[str, FileSnapshot] = {}
        after: dict[str, FileSnapshot] = {}
        for rel in sorted(set(self._tracked_paths(self.workspace)) | set(self._tracked_paths(task_path))):
            before[rel] = FileSnapshot.capture(self.workspace, self.workspace / rel)
            after[rel] = FileSnapshot.capture(task_path, task_path / rel)
        return build_diff_summaries(before, after, max_diff_chars=max_diff_chars)

    def merge(
        self,
        task_id: str,
        verification_commands: list[str] | None = None,
        rollback_on_verification_failure: bool = False,
        dry_run: bool = False,
    ) -> WorkspaceMergeResult:
        task_path = self._workspace_path(task_id)
        if not task_path.exists():
            raise ValueError(f"Task workspace does not exist: {task_id}")
        manifest = self._read_manifest(task_id)
        current_main: dict[str, FileSnapshot] = {}
        task_state: dict[str, FileSnapshot] = {}
        operations: list[dict[str, object]] = []
        conflicts: list[WorkspaceMergeConflict] = []
        candidate_paths = sorted(set(manifest) | set(self._tracked_paths(task_path)))

        for rel in candidate_paths:
            base = manifest.get(
                rel,
                WorkspaceManifestEntry(exists=False, sha256=None, entry_type="missing"),
            )
            main_snapshot = FileSnapshot.capture(self.workspace, self.workspace / rel)
            task_snapshot = FileSnapshot.capture(task_path, task_path / rel)
            task_changed = (
                task_snapshot.exists != base.exists
                or task_snapshot.sha256 != base.sha256
                or task_snapshot.entry_type != base.entry_type
            )
            if not task_changed:
                continue

            current_main[rel] = main_snapshot
            task_state[rel] = task_snapshot
            main_changed = (
                main_snapshot.exists != base.exists
                or main_snapshot.sha256 != base.sha256
                or main_snapshot.entry_type != base.entry_type
            )
            if main_changed:
                conflicts.append(
                    WorkspaceMergeConflict(
                        path=rel,
                        reason="main workspace changed since task workspace creation",
                        base_sha256=base.sha256,
                        main_sha256=main_snapshot.sha256,
                        task_sha256=task_snapshot.sha256,
                    )
                )
                continue

            operation = self._merge_operation(rel, main_snapshot, task_snapshot)
            if operation is not None:
                operations.append(operation)

        diff_summary = build_diff_summaries(current_main, task_state)
        if conflicts:
            return WorkspaceMergeResult(
                ok=False,
                output=f"workspace merge blocked for {task_id}: {len(conflicts)} conflict(s)",
                conflicts=conflicts,
                diff_summary=diff_summary,
            )
        if not operations:
            return WorkspaceMergeResult(
                ok=True,
                output=f"workspace {task_id} has no pending text changes to merge",
                diff_summary=diff_summary,
            )

        transaction = PatchTransaction(
            workspace=self.workspace,
            operations=operations,
            verification_commands=verification_commands or [],
            rollback_on_verification_failure=rollback_on_verification_failure,
            dry_run=dry_run,
        )
        result = transaction.run()
        if result.ok and not dry_run:
            self._write_manifest(task_id, self._capture_manifest(task_path))
        status = "dry-run merged" if dry_run else "merged"
        return WorkspaceMergeResult(
            ok=result.ok,
            output=f"{status} {task_id}: {result.output}" if result.ok else result.output,
            merged_files=result.modified_files,
            conflicts=[],
            diff_summary=diff_summary or result.diff_summary,
            transaction_id=result.transaction_id,
            journal_path=result.journal_path,
        )

    def _task_path(self, task_id: str) -> Path:
        safe = self._safe_task_id(task_id)
        if not safe:
            raise ValueError("task_id cannot be empty")
        return self.root / safe

    def _git_worktree_path(self, task_id: str) -> Path:
        safe = self._safe_task_id(task_id)
        if not safe:
            raise ValueError("task_id cannot be empty")
        return self.git_worktree_root / safe

    def _workspace_path(self, task_id: str) -> Path:
        copy_path = self._task_path(task_id)
        git_path = self._git_worktree_path(task_id)
        if copy_path.exists():
            return copy_path
        return git_path

    def _manifest_path(self, task_id: str) -> Path:
        safe = self._safe_task_id(task_id)
        if not safe:
            raise ValueError("task_id cannot be empty")
        return self.root / f"{safe}.manifest.json"

    def _safe_task_id(self, task_id: str) -> str:
        return "".join(char if char.isalnum() or char in "-_" else "_" for char in task_id)[:80]

    def _copy_workspace(self, target: Path) -> None:
        for item in self.workspace.iterdir():
            if item.name in IGNORED_PARTS:
                continue
            destination = target / item.name
            if item.is_dir():
                self._copy_tree(item, destination)
            elif item.is_file():
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, destination)

    def _copy_tree(self, source: Path, target: Path) -> None:
        for item in source.rglob("*"):
            rel = item.relative_to(source)
            if self._ignored(rel):
                continue
            destination = target / rel
            if item.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
            elif item.is_file():
                destination.parent.mkdir(parents=True, exist_ok=True)
                if not destination.exists() or not filecmp.cmp(item, destination, shallow=False):
                    shutil.copy2(item, destination)

    def _capture_manifest(self, root: Path) -> dict[str, WorkspaceManifestEntry]:
        manifest: dict[str, WorkspaceManifestEntry] = {}
        for rel in sorted(self._tracked_paths(root)):
            snapshot = FileSnapshot.capture(root, root / rel)
            manifest[rel] = WorkspaceManifestEntry.from_snapshot(snapshot)
        return manifest

    def _read_manifest(self, task_id: str) -> dict[str, WorkspaceManifestEntry]:
        path = self._manifest_path(task_id)
        if not path.exists():
            raise ValueError(
                f"Task workspace manifest missing for {task_id}. "
                f"Run `workspace create {task_id}` again."
            )
        payload = json.loads(path.read_text(encoding="utf-8"))
        raw_files = payload.get("files", {})
        if not isinstance(raw_files, dict):
            raise ValueError(f"Invalid task workspace manifest for {task_id}")
        return {
            str(rel): WorkspaceManifestEntry.from_dict(entry)
            for rel, entry in raw_files.items()
            if isinstance(entry, dict)
        }

    def _write_manifest(
        self,
        task_id: str,
        manifest: dict[str, WorkspaceManifestEntry],
        mode: str = "copy",
    ) -> None:
        path = self._manifest_path(task_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "task_id": task_id,
            "mode": mode,
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "files": {rel: entry.to_dict() for rel, entry in manifest.items()},
        }
        path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")

    def _create_git_worktree(self, task_id: str, target: Path) -> None:
        if not self._is_git_repo():
            raise ValueError("git-worktree mode requires the workspace to be a git repository.")
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and any(target.iterdir()):
            return
        branch = f"mini-claw/{self._safe_task_id(task_id)}"
        command = [
            "git",
            "worktree",
            "add",
            "-B",
            branch,
            str(target),
            "HEAD",
        ]
        completed = subprocess.run(
            command,
            cwd=self.workspace,
            text=True,
            capture_output=True,
        )
        if completed.returncode != 0:
            output = "\n".join(
                part for part in [completed.stdout.strip(), completed.stderr.strip()] if part
            )
            raise ValueError(f"git worktree create failed for {task_id}: {output}")

    def _is_git_repo(self) -> bool:
        completed = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=self.workspace,
            text=True,
            capture_output=True,
        )
        return completed.returncode == 0 and completed.stdout.strip() == "true"

    def _merge_operation(
        self,
        rel: str,
        main_snapshot: FileSnapshot,
        task_snapshot: FileSnapshot,
    ) -> dict[str, object] | None:
        if task_snapshot.entry_type == "dir":
            if not task_snapshot.exists:
                if not main_snapshot.exists:
                    return None
                if main_snapshot.entry_type != "dir":
                    return None
                return {
                    "op": "rmdir",
                    "path": rel,
                }
            if main_snapshot.exists:
                return None
            return {
                "op": "mkdir",
                "path": rel,
            }
        if not task_snapshot.exists:
            if not main_snapshot.exists:
                return None
            return {
                "op": "delete",
                "path": rel,
                "expected_sha256": main_snapshot.sha256,
            }
        operation: dict[str, object] = {
            "op": "write",
            "path": rel,
            "content": task_snapshot.content or "",
        }
        if main_snapshot.exists:
            operation["expected_sha256"] = main_snapshot.sha256
        return operation

    def _tracked_paths(self, root: Path) -> set[str]:
        paths: set[str] = set()
        if not root.exists():
            return paths
        for item in root.rglob("*"):
            rel = item.relative_to(root)
            if self._ignored(rel):
                continue
            if item.is_dir():
                paths.add(rel.as_posix())
                continue
            if item.is_file() and item.suffix.lower() in TEXT_FILE_SUFFIXES:
                paths.add(rel.as_posix())
        return paths

    def _ignored(self, path: Path) -> bool:
        return any(part in IGNORED_PARTS for part in path.parts)
