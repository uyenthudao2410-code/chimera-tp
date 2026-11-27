"""Undo the filesystem delta of one accepted workspace trial."""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any


def _member(root: Path, relative: str) -> Path:
    path = root / relative
    if not path.is_relative_to(root) or path.resolve() != path or path.is_symlink():
        raise ValueError(f"Workspace path changed or is indirect: {relative}")
    if path.exists() and not path.is_file():
        raise ValueError(f"Expected a file at {relative}")
    return path


def _digest(path: Path) -> str | None:
    try:
        with path.open("rb") as stream:
            return hashlib.file_digest(stream, "sha256").hexdigest()
    except FileNotFoundError:
        return None


class WorkspaceUndo:
    def __init__(self, root: Path, staged: Path, diff: dict[str, list[str]]) -> None:
        self.root = root.resolve()
        staged = staged.resolve()
        self.snap_id = f"ctrlz-{uuid.uuid4().hex[:12]}"
        self._directory = tempfile.TemporaryDirectory(prefix="chimera-undo-")
        self._files: dict[str, tuple[str | None, str | None]] = {}
        self._created_parents: set[Path] = set()
        try:
            for relative in (*diff["added"], *diff["modified"], *diff["deleted"]):
                original = _member(self.root, relative)
                for parent in original.parents:
                    if parent == self.root or parent.exists():
                        break
                    self._created_parents.add(parent.relative_to(self.root))
                backup = Path(self._directory.name) / relative
                if original.is_file():
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(original, backup)
                before = _digest(backup)
                after = _digest(_member(staged, relative))
                self._files[relative] = (before, after)
        except (OSError, ValueError):
            self.close()
            raise

    def restore(self) -> dict[str, Any]:
        changes: list[str] = []
        conflicts: list[str] = []
        for relative, (before, after) in self._files.items():
            try:
                current = _digest(_member(self.root, relative))
            except (ValueError, NotADirectoryError, IsADirectoryError):
                conflicts.append(relative)
                continue
            if current != before:
                if current == after:
                    changes.append(relative)
                else:
                    conflicts.append(relative)
        if conflicts:
            return {"ok": False, "error": "workspace_changed", "conflicts": conflicts, "snap_id": self.snap_id}

        restored = removed = 0
        for relative in changes:
            dest = _member(self.root, relative)
            before, after = self._files[relative]
            if _digest(dest) != after:
                return {"ok": False, "error": "workspace_changed", "conflicts": [relative], "snap_id": self.snap_id}
            if before is None:
                dest.unlink()
                removed += 1
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(dir=dest.parent, delete=False) as handle:
                    temp = Path(handle.name)
                try:
                    shutil.copy2(Path(self._directory.name) / relative, temp)
                    os.replace(temp, dest)
                finally:
                    temp.unlink(missing_ok=True)
                restored += 1
        for relative in sorted(self._created_parents, key=lambda path: len(path.parts), reverse=True):
            directory = self.root / relative
            if directory.resolve() == directory:
                try:
                    directory.rmdir()
                except OSError:
                    # Newly created directories can contain unrelated files by the time of undo.
                    pass
        return {"ok": True, "rewound_snap_id": self.snap_id, "restored_files": restored, "removed_files": removed}

    def close(self) -> None:
        self._directory.cleanup()
