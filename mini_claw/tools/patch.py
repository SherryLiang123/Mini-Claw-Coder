from __future__ import annotations

from pathlib import Path
from typing import Any

from mini_claw.context.workspace import ensure_inside_workspace
from mini_claw.memory.store import MemoryStore
from mini_claw.safety.patch_transaction import PatchTransaction
from mini_claw.safety.snapshot import FileSnapshot
from mini_claw.tools.base import ToolResult


class PatchTool:
    """Structured patch tool.

    Expected args:
    {
      "operations": [
        {"op": "write", "path": "src/a.py", "content": "..."},
        {"op": "replace", "path": "src/a.py", "old": "...", "new": "..."},
        {"op": "delete", "path": "src/old.py"}
      ],
      "verify": ["python -m unittest discover -s tests -q"],
      "rollback_on_verification_failure": false
    }
    """

    name = "apply_patch"

    def __init__(
        self,
        workspace: Path,
        dry_run: bool = False,
        memory: MemoryStore | None = None,
        require_read_snapshot: bool = False,
    ) -> None:
        self.workspace = workspace
        self.dry_run = dry_run
        self.memory = memory
        self.require_read_snapshot = require_read_snapshot

    def run(self, args: dict[str, Any]) -> ToolResult:
        operations = args.get("operations", [])
        if not isinstance(operations, list) or not operations:
            return ToolResult(ok=False, output="Missing operations list.")
        guard_result = self._check_read_before_write(operations)
        if guard_result is not None:
            return guard_result

        transaction = PatchTransaction(
            workspace=self.workspace,
            operations=operations,
            verification_commands=self._verification_commands(args),
            rollback_on_verification_failure=bool(
                args.get("rollback_on_verification_failure", False)
            ),
            verification_timeout_seconds=int(args.get("verification_timeout_seconds", 60)),
            dry_run=self.dry_run,
        )
        result = transaction.run()
        return ToolResult(
            ok=result.ok,
            output=result.output,
            modified_files=result.modified_files,
            metadata={
                "transaction_id": result.transaction_id,
                "journal_path": result.journal_path,
                "diff_summary": [item.to_dict() for item in result.diff_summary],
                "verification_results": [
                    item.to_dict() for item in result.verification_results
                ],
            },
        )

    def _verification_commands(self, args: dict[str, Any]) -> list[str]:
        raw = args.get("verify", args.get("verification_commands", []))
        if isinstance(raw, str):
            return [raw]
        if isinstance(raw, list):
            return [str(command) for command in raw]
        return []

    def _check_read_before_write(self, operations: list[Any]) -> ToolResult | None:
        if not self.require_read_snapshot:
            return None
        if self.memory is None:
            return ToolResult(
                ok=False,
                output="READ_BEFORE_WRITE_REQUIRED: PatchTool has no MemoryStore for read snapshot validation.",
                metadata={"root_cause": "READ_BEFORE_WRITE_REQUIRED"},
            )

        latest = self.memory.latest_read_snapshots()
        for operation in operations:
            if not isinstance(operation, dict):
                continue
            op = str(operation.get("op", ""))
            if op not in {"write", "replace", "delete"}:
                continue
            raw_path = str(operation.get("path", ""))
            try:
                target = ensure_inside_workspace(self.workspace, raw_path)
            except ValueError as exc:
                return ToolResult(ok=False, output=str(exc))
            rel = str(target.relative_to(self.workspace.resolve())).replace("\\", "/")
            current = FileSnapshot.capture(self.workspace, target)
            if not current.exists:
                continue
            snapshot = latest.get(rel)
            if not snapshot:
                return ToolResult(
                    ok=False,
                    output=(
                        f"READ_BEFORE_WRITE_REQUIRED: {rel} must be read before patching. "
                        "Use shell read command such as `Get-Content` or `cat`, then retry."
                    ),
                    metadata={
                        "root_cause": "READ_BEFORE_WRITE_REQUIRED",
                        "path": rel,
                    },
                )
            if str(snapshot.get("sha256", "")) != current.sha256:
                return ToolResult(
                    ok=False,
                    output=(
                        f"STALE_READ_SNAPSHOT: {rel} changed after it was read. "
                        f"expected {snapshot.get('sha256', '')}, current {current.sha256}. "
                        "Re-read the file and rebuild the patch."
                    ),
                    metadata={
                        "root_cause": "STALE_READ_SNAPSHOT",
                        "path": rel,
                        "read_sha256": snapshot.get("sha256", ""),
                        "current_sha256": current.sha256,
                    },
                )
        return None
