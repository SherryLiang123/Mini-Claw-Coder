from __future__ import annotations

import shutil
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class FileSnapshot:
    path: str
    exists: bool
    sha256: str | None
    content: str | None
    entry_type: str = "file"

    @classmethod
    def capture(cls, workspace: Path, target: Path) -> "FileSnapshot":
        rel_path = str(target.resolve().relative_to(workspace.resolve()))
        if not target.exists():
            return cls(path=rel_path, exists=False, entry_type="missing", sha256=None, content=None)
        if target.is_dir():
            return cls(path=rel_path, exists=True, entry_type="dir", sha256=None, content=None)
        content = target.read_text(encoding="utf-8")
        digest = sha256(content.encode("utf-8")).hexdigest()
        return cls(path=rel_path, exists=True, entry_type="file", sha256=digest, content=content)

    def restore(self, workspace: Path) -> None:
        target = workspace / self.path
        if not self.exists:
            if target.exists():
                if target.is_dir():
                    shutil.rmtree(target)
                else:
                    target.unlink()
            return
        if self.entry_type == "dir":
            if target.exists() and not target.is_dir():
                target.unlink()
            target.mkdir(parents=True, exist_ok=True)
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self.content or "", encoding="utf-8")

    def without_content(self) -> dict[str, Any]:
        data = asdict(self)
        data["content"] = None if self.content is None else f"<{len(self.content)} chars>"
        return data

    def to_journal(self) -> dict[str, Any]:
        return asdict(self)
