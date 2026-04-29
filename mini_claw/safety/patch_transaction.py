from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from mini_claw.context.workspace import ensure_inside_workspace
from mini_claw.safety.diff import FileDiffSummary, build_diff_summaries
from mini_claw.safety.snapshot import FileSnapshot


@dataclass
class VerificationResult:
    command: str
    ok: bool
    exit_code: int
    output: str

    def to_dict(self) -> dict[str, object]:
        return {
            "command": self.command,
            "ok": self.ok,
            "exit_code": self.exit_code,
            "output": self.output,
        }


@dataclass
class PatchTransactionResult:
    ok: bool
    output: str
    modified_files: list[str] = field(default_factory=list)
    transaction_id: str = ""
    journal_path: str | None = None
    diff_summary: list[FileDiffSummary] = field(default_factory=list)
    verification_results: list[VerificationResult] = field(default_factory=list)


class PatchTransaction:
    def __init__(
        self,
        workspace: Path,
        operations: list[dict[str, Any]],
        verification_commands: list[str] | None = None,
        rollback_on_verification_failure: bool = False,
        verification_timeout_seconds: int = 60,
        dry_run: bool = False,
    ) -> None:
        self.workspace = workspace
        self.operations = operations
        self.verification_commands = verification_commands or []
        self.rollback_on_verification_failure = rollback_on_verification_failure
        self.verification_timeout_seconds = verification_timeout_seconds
        self.dry_run = dry_run
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        self.transaction_id = f"{stamp}-{uuid4().hex[:8]}"
        self.journal_dir = workspace / ".mini_claw" / "patch_journal"

    def run(self) -> PatchTransactionResult:
        before: dict[str, FileSnapshot] = {}
        modified: list[str] = []
        messages: list[str] = []
        error: str | None = None
        rolled_back = False
        verification_results: list[VerificationResult] = []
        diff_summary: list[FileDiffSummary] = []

        try:
            for operation in self.operations:
                if not isinstance(operation, dict):
                    raise ValueError("Each operation must be an object.")
                op = str(operation.get("op", ""))
                raw_path = str(operation.get("path", ""))
                target = ensure_inside_workspace(self.workspace, raw_path)
                rel = str(target.relative_to(self.workspace.resolve()))
                if rel not in before:
                    before[rel] = FileSnapshot.capture(self.workspace, target)

                self._check_hash_precondition(operation, target)

                if op == "write":
                    self._write(operation, target, before[rel])
                    messages.append(f"wrote {rel}")
                elif op == "mkdir":
                    self._mkdir(target)
                    messages.append(f"created directory {rel}")
                elif op == "replace":
                    self._replace(operation, target)
                    messages.append(f"replaced text in {rel}")
                elif op == "delete":
                    self._delete(operation, target, before[rel])
                    messages.append(f"deleted {rel}")
                elif op == "rmdir":
                    self._rmdir(target)
                    messages.append(f"deleted directory {rel}")
                else:
                    raise ValueError(f"Unknown patch operation: {op}")

                if rel not in modified:
                    modified.append(rel)
        except Exception as exc:
            error = str(exc)
            if not self.dry_run:
                self._rollback(before)
                rolled_back = True

        after_patch = {
            rel: FileSnapshot.capture(self.workspace, self.workspace / rel)
            for rel in sorted(before)
        }
        diff_summary = build_diff_summaries(before, after_patch)

        if error is None and self.verification_commands:
            verification_results = self._run_verification()
            if any(not result.ok for result in verification_results):
                error = "verification failed"
                if self.rollback_on_verification_failure and not self.dry_run:
                    self._rollback(before)
                    rolled_back = True

        after = {
            rel: FileSnapshot.capture(self.workspace, self.workspace / rel)
            for rel in sorted(before)
        }
        journal_path = self._write_journal(
            before=before,
            after_patch=after_patch,
            after=after,
            error=error,
            rolled_back=rolled_back,
            diff_summary=diff_summary,
            verification_results=verification_results,
        )

        if error:
            failed_verification = next(
                (result for result in verification_results if not result.ok),
                None,
            )
            verification_note = (
                f"; failed_verification={failed_verification.command}"
                if failed_verification
                else ""
            )
            return PatchTransactionResult(
                ok=False,
                output=(
                    f"Patch transaction {self.transaction_id} failed: {error}; "
                    f"rolled_back={rolled_back}; journal={journal_path}{verification_note}"
                ),
                modified_files=[] if rolled_back else modified,
                transaction_id=self.transaction_id,
                journal_path=journal_path,
                diff_summary=diff_summary,
                verification_results=verification_results,
            )

        prefix = "dry-run: " if self.dry_run else ""
        diff_note = self._format_diff_note(diff_summary)
        verify_note = (
            f"; verification_passed={len(verification_results)}"
            if verification_results
            else ""
        )
        return PatchTransactionResult(
            ok=True,
            output=(
                f"{prefix}transaction_id={self.transaction_id}; "
                f"journal={journal_path}; "
                + "; ".join(messages)
                + diff_note
                + verify_note
            ),
            modified_files=modified,
            transaction_id=self.transaction_id,
            journal_path=journal_path,
            diff_summary=diff_summary,
            verification_results=verification_results,
        )

    def _check_hash_precondition(self, operation: dict[str, Any], target: Path) -> None:
        expected = operation.get("expected_sha256")
        if expected is None:
            return
        current = FileSnapshot.capture(self.workspace, target)
        if current.sha256 != expected:
            raise ValueError(
                f"hash precondition failed for {current.path}: "
                f"expected {expected}, got {current.sha256}"
            )

    def _write(
        self,
        operation: dict[str, Any],
        target: Path,
        initial_snapshot: FileSnapshot,
    ) -> None:
        content = str(operation.get("content", ""))
        overwrites_existing_file = initial_snapshot.exists and target.exists()
        has_lock = operation.get("expected_sha256") is not None
        allow_overwrite = bool(operation.get("allow_overwrite", False))
        if overwrites_existing_file and not has_lock and not allow_overwrite:
            raise ValueError(
                f"write would overwrite {initial_snapshot.path} without expected_sha256 "
                "or allow_overwrite=true"
            )
        if self.dry_run:
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def _replace(self, operation: dict[str, Any], target: Path) -> None:
        old = str(operation.get("old", ""))
        new = str(operation.get("new", ""))
        if not old:
            raise ValueError("replace operation requires non-empty old text")
        if not target.exists():
            raise FileNotFoundError(str(target.relative_to(self.workspace)))
        content = target.read_text(encoding="utf-8")
        if old not in content:
            raise ValueError(f"old text not found in {target.relative_to(self.workspace)}")
        if self.dry_run:
            return
        target.write_text(content.replace(old, new, 1), encoding="utf-8")

    def _mkdir(self, target: Path) -> None:
        if target.exists() and not target.is_dir():
            raise ValueError(f"mkdir target is an existing file: {target.relative_to(self.workspace)}")
        if self.dry_run:
            return
        target.mkdir(parents=True, exist_ok=True)

    def _delete(
        self,
        operation: dict[str, Any],
        target: Path,
        initial_snapshot: FileSnapshot,
    ) -> None:
        deleting_existing_file = initial_snapshot.exists and target.exists()
        has_lock = operation.get("expected_sha256") is not None
        allow_delete = bool(operation.get("allow_delete", False))
        if deleting_existing_file and not has_lock and not allow_delete:
            raise ValueError(
                f"delete would remove {initial_snapshot.path} without expected_sha256 "
                "or allow_delete=true"
            )
        if target.exists() and not self.dry_run:
            target.unlink()

    def _rmdir(self, target: Path) -> None:
        if not target.exists():
            return
        if not target.is_dir():
            raise ValueError(f"rmdir target is not a directory: {target.relative_to(self.workspace)}")
        if any(target.iterdir()):
            raise ValueError(f"rmdir requires an empty directory: {target.relative_to(self.workspace)}")
        if self.dry_run:
            return
        target.rmdir()

    def _rollback(self, before: dict[str, FileSnapshot]) -> None:
        for snapshot in reversed(list(before.values())):
            snapshot.restore(self.workspace)

    def _run_verification(self) -> list[VerificationResult]:
        results: list[VerificationResult] = []
        verification_env = os.environ.copy()
        verification_env.setdefault("PYTHONUTF8", "1")
        verification_env.setdefault("PYTHONIOENCODING", "utf-8")
        for command in self.verification_commands:
            try:
                completed = subprocess.run(
                    command,
                    shell=True,
                    cwd=self.workspace,
                    text=True,
                    capture_output=True,
                    timeout=self.verification_timeout_seconds,
                    env=verification_env,
                )
                output = "\n".join(
                    part
                    for part in [completed.stdout.strip(), completed.stderr.strip()]
                    if part
                )
                results.append(
                    VerificationResult(
                        command=command,
                        ok=completed.returncode == 0,
                        exit_code=completed.returncode,
                        output=output[:8_000],
                    )
                )
            except subprocess.TimeoutExpired:
                results.append(
                    VerificationResult(
                        command=command,
                        ok=False,
                        exit_code=-1,
                        output=f"Command timed out after {self.verification_timeout_seconds}s.",
                    )
                )
        return results

    def _format_diff_note(self, summaries: list[FileDiffSummary]) -> str:
        if not summaries:
            return "; diff=no changes"
        added = sum(item.added_lines for item in summaries)
        removed = sum(item.removed_lines for item in summaries)
        files = ", ".join(item.path for item in summaries)
        return f"; diff=files[{files}] +{added}/-{removed}"

    def _write_journal(
        self,
        before: dict[str, FileSnapshot],
        after_patch: dict[str, FileSnapshot],
        after: dict[str, FileSnapshot],
        error: str | None,
        rolled_back: bool,
        diff_summary: list[FileDiffSummary],
        verification_results: list[VerificationResult],
    ) -> str:
        self.journal_dir.mkdir(parents=True, exist_ok=True)
        path = self.journal_dir / f"{self.transaction_id}.json"
        payload = {
            "transaction_id": self.transaction_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "dry_run": self.dry_run,
            "ok": error is None,
            "error": error,
            "rolled_back": rolled_back,
            "operations": self.operations,
            "verification_commands": self.verification_commands,
            "rollback_on_verification_failure": self.rollback_on_verification_failure,
            "diff_summary": [item.to_dict() for item in diff_summary],
            "verification_results": [item.to_dict() for item in verification_results],
            "before": {rel: snapshot.to_journal() for rel, snapshot in before.items()},
            "after_patch": {rel: snapshot.to_journal() for rel, snapshot in after_patch.items()},
            "after": {rel: snapshot.to_journal() for rel, snapshot in after.items()},
            "before_summary": {rel: snapshot.without_content() for rel, snapshot in before.items()},
            "after_patch_summary": {
                rel: snapshot.without_content() for rel, snapshot in after_patch.items()
            },
            "after_summary": {rel: snapshot.without_content() for rel, snapshot in after.items()},
        }
        path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
        return str(path.relative_to(self.workspace))
