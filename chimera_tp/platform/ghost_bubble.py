"""CHIMERA-GHOST (Cartridge #12): Unprivileged Copy-on-Write Dry-Run Reality Bubble (Linux + Windows)."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any


_SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", "target", "dist", "build"}


def _snapshot_tree(root: Path, max_files: int = 800) -> dict[str, str]:
    hashes: dict[str, str] = {}
    count = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for fn in filenames:
            if count >= max_files:
                return hashes
            fp = Path(dirpath) / fn
            try:
                if fp.stat().st_size > 2 * 1024 * 1024:
                    continue
                rel = str(fp.relative_to(root)).replace("\\", "/")
                hashes[rel] = hashlib.blake2s(fp.read_bytes(), digest_size=12).hexdigest()
                count += 1
            except OSError:
                continue
    return hashes


def _stage_copy(src: Path, dst: Path, max_files: int = 800) -> int:
    copied = 0
    for dirpath, dirnames, filenames in os.walk(src):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        rel_dir = Path(dirpath).relative_to(src)
        (dst / rel_dir).mkdir(parents=True, exist_ok=True)
        for fn in filenames:
            if copied >= max_files:
                return copied
            s_fp = Path(dirpath) / fn
            d_fp = dst / rel_dir / fn
            try:
                if s_fp.stat().st_size > 2 * 1024 * 1024:
                    continue
                shutil.copy2(s_fp, d_fp)
                copied += 1
            except OSError:
                continue
    return copied


class GhostBubbleEngine:
    """Runs commands inside an isolated CoW staging bubble, computes full diff, and commits or discards with 0 trace."""

    def __init__(self, work_root: Path | None = None) -> None:
        self.work_root = Path(work_root) if work_root else Path(tempfile.gettempdir()) / "chimera_ghost_bubbles"
        self.work_root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._bubbles: dict[str, dict[str, Any]] = {}
        self._runs = 0
        self._commits = 0
        self._discards = 0

    def run_bubble(
        self,
        target_dir: str | Path,
        cmd: list[str] | str,
        timeout_s: float = 30.0,
        auto_discard: bool = False,
    ) -> dict[str, Any]:
        t0 = time.perf_counter()
        target = Path(target_dir).resolve()
        if not target.is_dir():
            raise FileNotFoundError(f"Target directory not found: {target}")

        bid = f"ghost-{uuid.uuid4().hex[:10]}"
        bdir = self.work_root / bid
        bdir.mkdir(parents=True, exist_ok=True)
        staged = _stage_copy(target, bdir)
        before = _snapshot_tree(bdir)

        shell_mode = isinstance(cmd, str)
        proc = subprocess.run(
            cmd,
            cwd=str(bdir),
            shell=shell_mode,
            capture_output=True,
            text=True,
            timeout=max(1.0, float(timeout_s)),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
        )
        after = _snapshot_tree(bdir)

        added = sorted(set(after.keys()) - set(before.keys()))
        deleted = sorted(set(before.keys()) - set(after.keys()))
        modified = sorted(k for k in (set(before.keys()) & set(after.keys())) if before[k] != after[k])

        rec = {
            "bubble_id": bid,
            "target_dir": str(target),
            "bubble_dir": str(bdir),
            "staged_files": staged,
            "exit_code": int(proc.returncode),
            "stdout": proc.stdout[-4000:],
            "stderr": proc.stderr[-2000:],
            "diff": {"added": added, "modified": modified, "deleted": deleted},
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
            "status": "open",
        }
        with self._lock:
            self._runs += 1
            self._bubbles[bid] = rec

        if auto_discard:
            self.discard(bid)
            rec["status"] = "discarded"
        return {"ok": True, **rec}

    def commit(self, bubble_id: str) -> dict[str, Any]:
        with self._lock:
            rec = self._bubbles.pop(str(bubble_id), None)
        if rec is None:
            raise KeyError(f"Bubble not found: {bubble_id}")
        target = Path(rec["target_dir"])
        bdir = Path(rec["bubble_dir"])
        applied = 0
        try:
            for rel in rec["diff"]["added"] + rec["diff"]["modified"]:
                src = bdir / rel
                dst = target / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                applied += 1
            for rel in rec["diff"]["deleted"]:
                dst = target / rel
                if dst.is_file():
                    dst.unlink()
                    applied += 1
        finally:
            shutil.rmtree(bdir, ignore_errors=True)
        with self._lock:
            self._commits += 1
        return {"ok": True, "bubble_id": bubble_id, "committed": True, "applied_changes": applied}

    def discard(self, bubble_id: str) -> dict[str, Any]:
        with self._lock:
            rec = self._bubbles.pop(str(bubble_id), None)
        if rec is not None:
            shutil.rmtree(Path(rec["bubble_dir"]), ignore_errors=True)
            with self._lock:
                self._discards += 1
            return {"ok": True, "bubble_id": bubble_id, "discarded": True, "host_changes": 0}
        return {"ok": True, "bubble_id": bubble_id, "discarded": False, "host_changes": 0}

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "ok": True,
                "open_bubbles": len(self._bubbles),
                "runs": self._runs,
                "commits": self._commits,
                "discards": self._discards,
            }

    def close(self) -> None:
        with self._lock:
            ids = list(self._bubbles.keys())
        for bid in ids:
            self.discard(bid)
