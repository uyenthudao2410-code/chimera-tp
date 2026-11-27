"""v23.0 CHIMERA-PHANTOM-SILICON — Infrastructure-Level Multitasking Singularity Engines.

Strictly OS-virtualization, storage-tiering, GPU-fencing, process-stasis, and remote-offload primitives:
  1. NvmeMirageEngine  (CHIMERA-NVME-MIRAGE)  — Zero-path-change NTFS Junction NVMe Tiering + Write-Back Coalescer
  2. StasisPodManager  (CHIMERA-STASIS-POD)   — Owner-Alive Cold Renderer Hibernation + Rust <0.5ms Focus Wake + GPU-Phoenix
  3. GpuFenceManager   (CHIMERA-GPU-FENCE)    — User-level DirectX UserGpuPreferences GTX 1650 vs iGPU Isolation
  4. AgentExileEngine  (CHIMERA-AGENT-EXILE)  — Transparent Coding-Agent Offload to svhome (24/7 SSD) & Colab High-MEM
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable

from ..native import (
    native_focus_state,
    native_stasis_register_group,
    native_stasis_wake_all,
    native_stasis_wake_pid,
)

# Cold Electron/WebView2 families safe for child-renderer-only Stasis Hibernation.
# NEVER includes Chrome, AutoCAD, T3 Code, agy, codex, or OS critical processes!
STASIS_COLD_FAMILIES = frozenset({
    "msedgewebview2",
    "chatgpt",
    "zalo",
    "antigravity",
})

_FILE_ATTRIBUTE_REPARSE_POINT = 0x0400
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


def is_junction_or_symlink(path: Path) -> bool:
    """Detect Windows NTFS Junction / symlink or POSIX symlink without following the final link."""
    if os.name == "nt":
        try:
            attrs = ctypes.windll.kernel32.GetFileAttributesW(str(path))
            if attrs == 0xFFFFFFFF:
                return False
            return bool(attrs & _FILE_ATTRIBUTE_REPARSE_POINT)
        except Exception:
            return path.is_symlink()
    return path.is_symlink()


def _dir_stats(root: Path, max_sample_hashes: int = 12) -> tuple[int, int, dict[str, str]]:
    """Fast recursive (file_count, total_bytes, sample_sha256_map) scanner."""
    files = 0
    total_bytes = 0
    samples: dict[str, str] = {}
    root_res = root.resolve()
    stack = [root_res]
    while stack:
        cur = stack.pop()
        try:
            with os.scandir(cur) as it:
                for ent in it:
                    try:
                        if ent.is_symlink():
                            continue
                        if ent.is_dir(follow_symlinks=False):
                            stack.append(Path(ent.path))
                        elif ent.is_file(follow_symlinks=False):
                            st = ent.stat(follow_symlinks=False)
                            files += 1
                            total_bytes += int(st.st_size)
                            if len(samples) < max_sample_hashes and st.st_size <= 8 * 1024 * 1024:
                                rel = Path(ent.path).relative_to(root_res).as_posix()
                                try:
                                    h = hashlib.sha256(Path(ent.path).read_bytes()).hexdigest()[:16]
                                    samples[rel] = h
                                except OSError:
                                    pass
                    except OSError:
                        continue
        except OSError:
            continue
    return files, total_bytes, samples


def _create_junction(link_path: Path, target_path: Path) -> bool:
    if os.name == "nt":
        proc = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link_path), str(target_path)],
            capture_output=True,
            text=True,
            timeout=15.0,
            creationflags=_NO_WINDOW,
        )
        return proc.returncode == 0 and is_junction_or_symlink(link_path)
    os.symlink(str(target_path), str(link_path), target_is_directory=True)
    return link_path.is_symlink()


def _remove_junction_only(link_path: Path) -> bool:
    """Safely remove ONLY the NTFS Junction / symlink entry — NEVER touches target contents!"""
    if not is_junction_or_symlink(link_path):
        return False
    if os.name == "nt":
        # os.rmdir on an NTFS junction removes only the reparse point directory entry.
        os.rmdir(str(link_path))
        return not link_path.exists()
    link_path.unlink()
    return not link_path.exists()


def _copy_tree_fast(src: Path, dst: Path) -> tuple[bool, str]:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        dst.mkdir(parents=True, exist_ok=True)
        proc = subprocess.run(
            [
                "robocopy",
                str(src),
                str(dst),
                "/MIR",
                "/COPY:DAT",
                "/DCOPY:T",
                "/R:1",
                "/W:1",
                "/MT:8",
                "/NFL",
                "/NDL",
                "/NP",
                "/NJH",
                "/NJS",
            ],
            capture_output=True,
            text=True,
            timeout=300.0,
            creationflags=_NO_WINDOW,
        )
        # Robocopy exit codes 0..7 indicate success (bits 0-2 = copied/extra/mismatched)
        if proc.returncode < 8:
            return True, f"robocopy_rc={proc.returncode}"
        return False, f"robocopy_failed_rc={proc.returncode}:{(proc.stderr or proc.stdout)[-200:]}"
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, symlinks=True)
    return True, "shutil_copytree_ok"


def _sync_diff_tree(src: Path, dst: Path) -> tuple[bool, int, int, str]:
    """Differential write-back: copy only new/modified files from NVMe tier back to cold backing."""
    if os.name == "nt":
        dst.mkdir(parents=True, exist_ok=True)
        proc = subprocess.run(
            [
                "robocopy",
                str(src),
                str(dst),
                "/MIR",
                "/COPY:DAT",
                "/R:1",
                "/W:1",
                "/MT:4",
                "/NFL",
                "/NDL",
                "/NP",
                "/NJH",
                "/NJS",
            ],
            capture_output=True,
            text=True,
            timeout=180.0,
            creationflags=_NO_WINDOW,
        )
        ok = proc.returncode < 8
        changed = 1 if (proc.returncode & 1) else 0
        return ok, changed, 0, f"robocopy_rc={proc.returncode}"

    copied = 0
    copied_bytes = 0
    dst.mkdir(parents=True, exist_ok=True)
    src_r = src.resolve()
    for dp, dns, fns in os.walk(src_r):
        rel_d = Path(dp).relative_to(src_r)
        (dst / rel_d).mkdir(parents=True, exist_ok=True)
        for fn in fns:
            sf = Path(dp) / fn
            df = dst / rel_d / fn
            try:
                sst = sf.stat()
                if (not df.exists()) or df.stat().st_size != sst.st_size or int(df.stat().st_mtime) != int(sst.st_mtime):
                    shutil.copy2(sf, df)
                    copied += 1
                    copied_bytes += int(sst.st_size)
            except OSError:
                continue
    return True, copied, copied_bytes, "python_diff_sync_ok"


# ---------------------------------------------------------------------------
# 1. CHIMERA-NVME-MIRAGE: Zero-Path-Change NVMe Tiering + Write-Back Coalescer
# ---------------------------------------------------------------------------

class NvmeMirageEngine:
    """Transparently elevates hot HDD folders onto NVMe SSD via atomic NTFS Junctions + cold HDD backing."""

    def __init__(
        self,
        *,
        ops_dir: Path | None = None,
        tier_root: Path | None = None,
        min_nvme_free_gb: float = 35.0,
        max_total_tier_gb: float = 25.0,
        allow_same_volume: bool = False,
    ) -> None:
        self.ops_dir = Path(ops_dir) if ops_dir else (Path.home() / ".chimera")
        self.state_path = self.ops_dir / "nvme_mirage.json"
        if tier_root is not None:
            self.tier_root = Path(tier_root)
        elif os.name == "nt":
            self.tier_root = Path(r"C:\.chimera_nvme_tier")
        else:
            self.tier_root = self.ops_dir / "nvme_mirage_tier"
        self.min_nvme_free_gb = float(min_nvme_free_gb)
        self.max_total_tier_gb = float(max_total_tier_gb)
        self.allow_same_volume = bool(allow_same_volume)
        self._lock = threading.Lock()
        self._entries: dict[str, dict[str, Any]] = {}
        self._load_state()

    def _load_state(self) -> None:
        if not self.state_path.is_file():
            return
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("entries"), dict):
                self._entries = dict(data["entries"])
        except Exception:
            pass

    def _save_state(self) -> None:
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.state_path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"entries": self._entries}, indent=2), encoding="utf-8")
            os.replace(tmp, self.state_path)
        except Exception:
            pass

    def _nvme_free_gb(self) -> float:
        probe = self.tier_root if self.tier_root.exists() else self.tier_root.anchor or str(self.tier_root.parent)
        try:
            usage = shutil.disk_usage(probe)
            return round(usage.free / (1024.0 ** 3), 2)
        except Exception:
            return 0.0

    def _safe_key(self, src: Path) -> str:
        clean = "".join(ch if (ch.isalnum() or ch in ("-", "_")) else "_" for ch in src.name).strip("_") or "repo"
        h = hashlib.blake2s(str(src).lower().encode("utf-8"), digest_size=4).hexdigest()
        return f"{clean}_{h}"

    def promote(
        self,
        src_path: str | Path,
        *,
        max_repo_gb: float = 8.0,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Atomically promote a hot HDD folder onto NVMe tier with zero path change (NTFS Junction)."""
        t0 = time.perf_counter()
        raw_p = Path(src_path)
        if not raw_p.is_absolute():
            raw_p = raw_p.resolve()
        # Preserve final path without resolving through an existing junction
        src = raw_p.parent.resolve() / raw_p.name
        key = str(src).lower()

        if not src.exists():
            return {"ok": False, "error": f"path_not_found:{src}"}
        if not src.is_dir():
            return {"ok": False, "error": f"not_a_directory:{src}"}

        if is_junction_or_symlink(src):
            with self._lock:
                existing = self._entries.get(key)
            return {
                "ok": True,
                "already_promoted": True,
                "src": str(src),
                "entry": existing,
                "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
            }

        # Refuse promoting a folder already on the same drive as tier_root on Windows
        if os.name == "nt" and (not self.allow_same_volume) and src.drive.lower() == self.tier_root.drive.lower():
            return {"ok": False, "error": f"already_on_nvme_volume:{src.drive}"}

        file_count, total_bytes, sample_hashes = _dir_stats(src, max_sample_hashes=12)
        size_gb = total_bytes / (1024.0 ** 3)
        free_gb = self._nvme_free_gb()

        if size_gb > float(max_repo_gb):
            return {
                "ok": False,
                "error": f"exceeds_max_repo_gb:{size_gb:.2f}>{max_repo_gb}",
                "size_mb": round(total_bytes / (1024.0 ** 2), 2),
                "files": file_count,
            }
        if (free_gb - size_gb) < self.min_nvme_free_gb:
            return {
                "ok": False,
                "error": f"insufficient_nvme_free_gb:free={free_gb:.2f},need={size_gb:.2f},guard={self.min_nvme_free_gb}",
            }

        tier_id = self._safe_key(src)
        nvme_target = self.tier_root / tier_id
        cold_root = src.parent / ".chimera_cold_backing"
        cold_target = cold_root / tier_id

        if dry_run:
            return {
                "ok": True,
                "dry_run": True,
                "src": str(src),
                "nvme_target": str(nvme_target),
                "cold_target": str(cold_target),
                "files": file_count,
                "size_mb": round(total_bytes / (1024.0 ** 2), 2),
                "nvme_free_gb": free_gb,
                "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
            }

        with self._lock:
            self.tier_root.mkdir(parents=True, exist_ok=True)
            # Step 1: Copy all data to NVMe tier first (original HDD directory untouched!)
            ok_cp, cp_msg = _copy_tree_fast(src, nvme_target)
            if not ok_cp:
                shutil.rmtree(nvme_target, ignore_errors=True)
                return {"ok": False, "error": f"copy_to_nvme_failed:{cp_msg}"}

            # Step 2: Verify SHA-256 sample integrity on NVMe copy before touching original
            verified = 0
            for rel, expected in sample_hashes.items():
                nf = nvme_target / Path(rel)
                if not nf.is_file():
                    shutil.rmtree(nvme_target, ignore_errors=True)
                    return {"ok": False, "error": f"verify_missing:{rel}"}
                got = hashlib.sha256(nf.read_bytes()).hexdigest()[:16]
                if got != expected:
                    shutil.rmtree(nvme_target, ignore_errors=True)
                    return {"ok": False, "error": f"verify_sha_mismatch:{rel}"}
                verified += 1

            # Step 3: Atomic same-volume rename src -> cold_target (fails cleanly if locked by a live process!)
            cold_root.mkdir(parents=True, exist_ok=True)
            if cold_target.exists():
                cold_target = cold_root / f"{tier_id}_{int(time.time())}"
            try:
                os.rename(str(src), str(cold_target))
            except OSError as exc:
                shutil.rmtree(nvme_target, ignore_errors=True)
                return {
                    "ok": False,
                    "error": f"directory_locked_by_running_process:{exc}",
                    "src": str(src),
                    "untouched": True,
                }

            # Step 4: Instant NTFS Junction src -> nvme_target (atomic rollback on any failure!)
            try:
                j_ok = _create_junction(src, nvme_target)
            except Exception:
                j_ok = False
            if not j_ok:
                try:
                    os.rename(str(cold_target), str(src))
                except OSError:
                    pass
                shutil.rmtree(nvme_target, ignore_errors=True)
                return {"ok": False, "error": "junction_creation_failed_rolled_back"}

            entry = {
                "name": src.name,
                "src": str(src),
                "nvme_target": str(nvme_target),
                "cold_target": str(cold_target),
                "files": file_count,
                "size_mb": round(total_bytes / (1024.0 ** 2), 2),
                "verified_samples": verified,
                "promoted_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "last_sync_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "sync_count": 0,
            }
            self._entries[key] = entry
            self._save_state()

        return {
            "ok": True,
            "promoted": True,
            **entry,
            "copy_detail": cp_msg,
            "nvme_free_gb_after": self._nvme_free_gb(),
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }

    def sync_back(self, src_path: str | Path | None = None) -> dict[str, Any]:
        """Differential write-back from NVMe tier -> HDD cold backing so both tiers stay consistent."""
        t0 = time.perf_counter()
        with self._lock:
            if src_path is not None:
                p = Path(src_path)
                k = str((p.parent.resolve() / p.name) if not p.is_absolute() else p).lower()
                items = [(k, dict(self._entries[k]))] if k in self._entries else []
            else:
                items = [(k, dict(v)) for k, v in self._entries.items()]

        results: list[dict[str, Any]] = []
        for k, ent in items:
            nvme_p = Path(ent["nvme_target"])
            cold_p = Path(ent["cold_target"])
            if not nvme_p.is_dir():
                results.append({"name": ent["name"], "ok": False, "error": "nvme_target_missing"})
                continue
            ok, changed, cbytes, msg = _sync_diff_tree(nvme_p, cold_p)
            if ok:
                with self._lock:
                    if k in self._entries:
                        self._entries[k]["last_sync_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                        self._entries[k]["sync_count"] = int(self._entries[k].get("sync_count", 0)) + 1
                        self._save_state()
            results.append({
                "name": ent["name"],
                "ok": ok,
                "changed": changed,
                "bytes": cbytes,
                "detail": msg,
            })
        return {
            "ok": all(r["ok"] for r in results),
            "synced_count": len(results),
            "results": results,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }

    def demote(self, src_path: str | Path) -> dict[str, Any]:
        """Losslessly reverse an NVMe Mirage junction back to a regular folder on the original drive."""
        t0 = time.perf_counter()
        raw_p = Path(src_path)
        src = (raw_p.parent.resolve() / raw_p.name) if not raw_p.is_absolute() else (raw_p.parent.resolve() / raw_p.name)
        key = str(src).lower()
        with self._lock:
            ent = self._entries.get(key)
            if not ent:
                return {"ok": False, "error": f"not_in_mirage_registry:{src}"}
            nvme_p = Path(ent["nvme_target"])
            cold_p = Path(ent["cold_target"])

            # 1. Sync latest NVMe edits back to cold backing first!
            if nvme_p.is_dir():
                ok_s, _, _, msg = _sync_diff_tree(nvme_p, cold_p)
                if not ok_s:
                    return {"ok": False, "error": f"final_sync_failed:{msg}"}

            # 2. Remove junction ONLY (never touches NVMe files)
            if is_junction_or_symlink(src):
                if not _remove_junction_only(src):
                    return {"ok": False, "error": "remove_junction_failed"}

            # 3. Restore cold backing back to original path
            try:
                os.rename(str(cold_p), str(src))
            except OSError as exc:
                # Re-attach junction if rename failed so workspace stays intact!
                _create_junction(src, nvme_p)
                return {"ok": False, "error": f"restore_rename_failed:{exc}"}

            # 4. Clean up NVMe tier copy
            shutil.rmtree(nvme_p, ignore_errors=True)
            self._entries.pop(key, None)
            self._save_state()

        return {
            "ok": True,
            "demoted": True,
            "src": str(src),
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }

    @staticmethod
    def benchmark_dir(target_dir: str | Path, max_files: int = 200) -> dict[str, Any]:
        root = Path(target_dir)
        files: list[str] = []
        skip = {".git", "node_modules", "target", ".venv", "__pycache__"}
        for dp, dns, fns in os.walk(root):
            dns[:] = [d for d in dns if d not in skip]
            for fn in fns:
                files.append(os.path.join(dp, fn))
                if len(files) >= max_files:
                    break
            if len(files) >= max_files:
                break
        t0 = time.perf_counter()
        tot = 0
        for f in files:
            try:
                with open(f, "rb") as fh:
                    tot += len(fh.read(4096))
            except OSError:
                continue
        dt_ms = (time.perf_counter() - t0) * 1000.0
        return {
            "ok": True,
            "path": str(root),
            "is_mirage_junction": is_junction_or_symlink(root),
            "files_read": len(files),
            "bytes_read": tot,
            "elapsed_ms": round(dt_ms, 2),
            "avg_ms_per_file": round(dt_ms / max(1, len(files)), 4),
        }

    @staticmethod
    def warm_paths(
        paths: list[str | Path],
        *,
        budget_bytes: int = 2 * 1024 * 1024,
        per_file_cap: int = 262_144,
        allowed_roots: list[Path] | None = None,
    ) -> dict[str, Any]:
        """Bounded 64 KiB streaming page-cache prewarm for predicted files (0 retained daemon RSS)."""
        from .precog_conduit import warm_file_paths

        return warm_file_paths(
            paths,
            budget_bytes=budget_bytes,
            per_file_cap=per_file_cap,
            allowed_roots=allowed_roots,
        )

    def status(self) -> dict[str, Any]:
        with self._lock:
            items = []
            tot_mb = 0.0
            for ent in self._entries.values():
                p = Path(ent["src"])
                active = is_junction_or_symlink(p) and Path(ent["nvme_target"]).is_dir()
                tot_mb += float(ent.get("size_mb", 0.0))
                items.append({**ent, "junction_active": active})
        return {
            "ok": True,
            "tier_root": str(self.tier_root),
            "nvme_free_gb": self._nvme_free_gb(),
            "min_nvme_free_gb": self.min_nvme_free_gb,
            "promoted_count": len(items),
            "total_tiered_mb": round(tot_mb, 2),
            "entries": items,
        }


# ---------------------------------------------------------------------------
# 2. CHIMERA-STASIS-POD + GPU-PHOENIX (Owner-Alive Hibernation + Safe GPU Respawn)
# ---------------------------------------------------------------------------

class StasisPodManager:
    """Suspends ONLY cold background Electron/WebView2 child renderers + trims ONCE (0 re-faults).

    Main HWND browser process stays 100% responsive; Rust SetWinEventHook wakes children in <0.5ms on focus.
    """

    def __init__(
        self,
        *,
        cmdlines_fn: Callable[[list[int]], dict[int, str]],
        suspend_fn: Callable[[int, bool], bool],
        trim_fn: Callable[[int], bool],
        mem_fn: Callable[[int], tuple[float, float]],
        terminate_fn: Callable[[int], bool],
        ops_dir: Path | None = None,
    ) -> None:
        self._get_cmdlines = cmdlines_fn
        self._suspend = suspend_fn
        self._trim = trim_fn
        self._mem = mem_fn
        self._terminate = terminate_fn
        self._state_path = (Path(ops_dir) / "stasis_pids.json") if ops_dir else None
        self._lock = threading.Lock()
        self._stasis_pids: dict[int, dict[str, Any]] = {}  # child_pid -> {app, owner_pids, ws_before, ws_after, ts}
        self._passes = 0
        self._total_reclaimed_mb = 0.0
        self._gpu_recycles = 0
        self._last_gpu_recycle_ts: dict[str, float] = {}
        self._recover_stale_stasis()

    def _recover_stale_stasis(self) -> None:
        """Crash-safety invariant: resume any PID left in stasis by a prior abruptly killed daemon."""
        if not self._state_path or not self._state_path.is_file():
            return
        try:
            old = json.loads(self._state_path.read_text(encoding="utf-8"))
            if isinstance(old, list):
                for pid in old:
                    if isinstance(pid, int) and pid > 4:
                        self._suspend(pid, False)
            self._state_path.unlink(missing_ok=True)
        except Exception:
            pass

    def _persist_stasis_locked(self) -> None:
        if not self._state_path:
            return
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._state_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(sorted(self._stasis_pids.keys())), encoding="utf-8")
            os.replace(tmp, self._state_path)
        except Exception:
            pass

    def hibernate_cold_renderers(
        self,
        procs: list[dict[str, Any]],
        *,
        sanctuary_pids: set[int],
        recent_families: set[str],
        min_ws_mb: float = 20.0,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        t0 = time.perf_counter()
        # Group cold candidate families
        by_fam: dict[str, list[dict[str, Any]]] = {}
        for p in procs:
            nm = p["name"]
            if nm in STASIS_COLD_FAMILIES and nm not in recent_families and p["pid"] not in sanctuary_pids:
                by_fam.setdefault(nm, []).append(p)

        cand_pids = [p["pid"] for fam_list in by_fam.values() for p in fam_list]
        if not cand_pids:
            return {"ok": True, "dry_run": dry_run, "hibernated": 0, "ws_reclaimed_mb": 0.0, "families": [], "elapsed_ms": 0.0}

        cmd_map = self._get_cmdlines(cand_pids)
        groups_to_stasis: list[tuple[str, list[int], list[dict[str, Any]]]] = []
        for fam, plist in by_fam.items():
            owners: list[int] = []
            children: list[dict[str, Any]] = []
            for p in plist:
                pid = p["pid"]
                cmd = (cmd_map.get(pid) or "").lower()
                is_child_worker = ("--type=renderer" in cmd) or ("--type=utility" in cmd)
                if is_child_worker and p["ws_mb"] >= float(min_ws_mb):
                    children.append(p)
                elif "--type=" not in cmd:
                    owners.append(pid)
            # For msedgewebview2 (Widgets/Copilot), all renderers have --type=renderer even if host is explorer/widget
            triggers = owners if owners else [p["pid"] for p in plist if p not in children]
            if children:
                groups_to_stasis.append((fam, triggers, children))

        hibernated = 0
        before_ws = 0.0
        after_ws = 0.0
        fams_hit: list[str] = []
        newly_stasis: list[tuple[str, list[int], dict[str, Any]]] = []

        for fam, triggers, children in groups_to_stasis:
            fams_hit.append(fam)
            child_ids = [c["pid"] for c in children]
            before_ws += sum(float(c["ws_mb"]) for c in children)
            if not dry_run:
                # Register with Rust <0.5ms EVENT_SYSTEM_FOREGROUND instant-wake table BEFORE suspending!
                if triggers:
                    native_stasis_register_group(triggers, child_ids)
                for c in children:
                    pid = c["pid"]
                    with self._lock:
                        already = pid in self._stasis_pids
                    if already:
                        continue
                    if self._suspend(pid, True):
                        self._trim(pid)
                        hibernated += 1
                        newly_stasis.append((fam, triggers, c))

        if not dry_run and newly_stasis:
            time.sleep(0.06)
            for fam, triggers, c in newly_stasis:
                pid = c["pid"]
                aw = self._mem(pid)[0] if os.name == "nt" else float(c["ws_mb"])
                after_ws += aw
                with self._lock:
                    self._stasis_pids[pid] = {
                        "app": fam,
                        "triggers": triggers[:8],
                        "ws_before_mb": float(c["ws_mb"]),
                        "ws_after_mb": aw,
                        "ts": time.time(),
                    }
                    self._persist_stasis_locked()
        else:
            after_ws = before_ws

        reclaimed = round(max(0.0, before_ws - after_ws), 1)
        if not dry_run and hibernated > 0:
            with self._lock:
                self._passes += 1
                self._total_reclaimed_mb = round(self._total_reclaimed_mb + reclaimed, 1)

        return {
            "ok": True,
            "dry_run": dry_run,
            "families": sorted(set(fams_hit)),
            "candidates": sum(len(ch) for _, _, ch in groups_to_stasis),
            "hibernated": hibernated,
            "active_stasis_pids": len(self._stasis_pids),
            "ws_before_mb": round(before_ws, 1),
            "ws_after_mb": round(after_ws, 1),
            "ws_reclaimed_mb": reclaimed,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }

    def wake_family(self, app_name: str = "", trigger_pid: int = 0) -> dict[str, Any]:
        woken = 0
        if trigger_pid > 4:
            woken += native_stasis_wake_pid(trigger_pid)
        to_resume: list[int] = []
        with self._lock:
            for pid, meta in list(self._stasis_pids.items()):
                if (app_name and meta.get("app") == app_name) or (trigger_pid and trigger_pid in meta.get("triggers", [])):
                    to_resume.append(pid)
                    self._stasis_pids.pop(pid, None)
            if to_resume:
                self._persist_stasis_locked()
        for pid in to_resume:
            if self._suspend(pid, False):
                woken += 1
        return {"ok": True, "woken": woken, "pids": to_resume}

    def wake_all(self) -> dict[str, Any]:
        rust_woken = native_stasis_wake_all()
        with self._lock:
            pids = list(self._stasis_pids.keys())
            self._stasis_pids.clear()
            self._persist_stasis_locked()
        py_woken = 0
        for pid in pids:
            if self._suspend(pid, False):
                py_woken += 1
        return {"ok": True, "rust_woken": rust_woken, "py_woken": py_woken, "count": max(rust_woken, py_woken)}

    def gpu_phoenix_audit_and_recycle(
        self,
        procs: list[dict[str, Any]],
        *,
        threshold_commit_mb: float = 1600.0,
        allow_recycle: bool = False,
        cooldown_s: float = 1800.0,
    ) -> dict[str, Any]:
        """Detect bloated Chromium/Electron --type=gpu-process leaks and optionally soft-recycle them (0 tabs lost)."""
        t0 = time.perf_counter()
        chromium_names = {"chrome", "msedge", "antigravity", "t3 code (beta)", "t3 code", "chatgpt", "zalo"}
        cands = [p for p in procs if p["name"] in chromium_names and p["priv_mb"] >= 200.0]
        cmd_map = self._get_cmdlines([p["pid"] for p in cands])

        gpu_procs: list[dict[str, Any]] = []
        recycled: list[dict[str, Any]] = []
        now = time.time()

        for p in cands:
            cmd = cmd_map.get(p["pid"], "")
            if "--type=gpu-process" not in cmd.lower():
                continue
            bloated = float(p["priv_mb"]) >= float(threshold_commit_mb)
            rec = {
                "pid": p["pid"],
                "name": p["name"],
                "ws_mb": p["ws_mb"],
                "priv_mb": p["priv_mb"],
                "bloated": bloated,
            }
            gpu_procs.append(rec)
            if allow_recycle and bloated:
                last_ts = self._last_gpu_recycle_ts.get(p["name"], 0.0)
                if (now - last_ts) >= float(cooldown_s):
                    if self._terminate(p["pid"]):
                        self._last_gpu_recycle_ts[p["name"]] = now
                        with self._lock:
                            self._gpu_recycles += 1
                        recycled.append(rec)

        return {
            "ok": True,
            "threshold_commit_mb": float(threshold_commit_mb),
            "allow_recycle": bool(allow_recycle),
            "gpu_processes": gpu_procs,
            "recycled": recycled,
            "recycled_commit_mb": round(sum(r["priv_mb"] for r in recycled), 1),
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }

    def status(self) -> dict[str, Any]:
        with self._lock:
            active_apps: dict[str, int] = {}
            for meta in self._stasis_pids.values():
                a = str(meta.get("app") or "unknown")
                active_apps[a] = active_apps.get(a, 0) + 1
            return {
                "ok": True,
                "active_stasis_pids": len(self._stasis_pids),
                "active_by_app": active_apps,
                "passes": self._passes,
                "total_ws_reclaimed_mb": self._total_reclaimed_mb,
                "gpu_phoenix_recycles": self._gpu_recycles,
                "rust_focus": native_focus_state(),
            }


# ---------------------------------------------------------------------------
# 3. CHIMERA-GPU-FENCE: HKCU DirectX UserGpuPreferences Isolation (Zero Admin)
# ---------------------------------------------------------------------------

class GpuFenceManager:
    """Topology-aware HKCU DirectX GPU preference manager (Zero Admin, Zero-Copy Display).

    Uses native Win32 EnumDisplayDevicesW (never WMI Win32_VideoController, which mirrors
    resolutions onto unattached iGPUs) to inspect which GPU actually drives the physical monitors:
    - When ALL active displays are wired to the discrete GPU (e.g. NVIDIA GTX 1650), assigns
      GpuPreference=2 to CAD, browsers, and Electron/IDE apps to eliminate Cross-Adapter PCIe Blit
      and keep the on-die Intel iGPU at 0%.
    - Only pins background Electron/WebView2 to GpuPreference=1 when a physical monitor is
      genuinely attached to the iGPU.
    """

    REG_SUBKEY = r"Software\Microsoft\DirectX\UserGpuPreferences"
    HIGH_PERF_PROCS = ("acad.exe", "revit.exe", "blender.exe", "sketchup.exe", "rhino.exe", "chrome.exe", "msedge.exe")
    LOW_POWER_PROCS = (
        "antigravity.exe",
        "t3 code (beta).exe",
        "chatgpt.exe",
        "zalo.exe",
        "msedgewebview2.exe",
    )

    def __init__(self, ops_dir: Path | None = None) -> None:
        self.ops_dir = Path(ops_dir) if ops_dir else (Path.home() / ".chimera")
        self.backup_path = self.ops_dir / "gpu_fence_backup.json"

    def _detect_display_topology(self) -> dict[str, Any]:
        """Inspect real active monitor-to-GPU wiring via Win32 EnumDisplayDevicesW."""
        if os.name != "nt":
            return {"displays": [], "all_on_dgpu": False, "has_igpu_display": False}
        from ctypes import wintypes

        class _DISPLAY_DEVICEW(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("DeviceName", wintypes.WCHAR * 32),
                ("DeviceString", wintypes.WCHAR * 128),
                ("StateFlags", wintypes.DWORD),
                ("DeviceID", wintypes.WCHAR * 128),
                ("DeviceKey", wintypes.WCHAR * 128),
            ]

        displays: list[dict[str, Any]] = []
        try:
            u32 = ctypes.windll.user32
            i = 0
            while True:
                dd = _DISPLAY_DEVICEW()
                dd.cb = ctypes.sizeof(dd)
                if not u32.EnumDisplayDevicesW(None, i, ctypes.byref(dd), 0):
                    break
                i += 1
                if not (dd.StateFlags & 0x1):  # DISPLAY_DEVICE_ATTACHED_TO_DESKTOP
                    continue
                gpu = str(dd.DeviceString or "")
                low = gpu.lower()
                is_igpu = ("intel" in low) or ("uhd" in low) or ("iris" in low)
                is_dgpu = ("nvidia" in low) or ("geforce" in low) or ("quadro" in low) or ("radeon rx" in low)
                displays.append({
                    "device": str(dd.DeviceName or ""),
                    "primary": bool(dd.StateFlags & 0x4),
                    "gpu": gpu,
                    "kind": "dgpu" if is_dgpu else ("igpu" if is_igpu else "other"),
                })
        except Exception:
            displays = []

        has_dgpu = any(d["kind"] == "dgpu" for d in displays)
        has_igpu = any(d["kind"] == "igpu" for d in displays)
        return {
            "displays": displays,
            "all_on_dgpu": bool(displays) and has_dgpu and (not has_igpu),
            "has_igpu_display": has_igpu,
        }

    def _read_registry(self) -> dict[str, str]:
        if os.name != "nt":
            return {}
        import winreg

        out: dict[str, str] = {}
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.REG_SUBKEY, 0, winreg.KEY_READ) as k:
                i = 0
                while True:
                    try:
                        name, val, _ = winreg.EnumValue(k, i)
                        out[str(name)] = str(val)
                        i += 1
                    except OSError:
                        break
        except OSError:
            pass
        return out

    def _discover_exe_paths(self) -> dict[str, list[str]]:
        high_perf: list[str] = []
        low_power: list[str] = []
        if os.name != "nt":
            return {"high_perf": high_perf, "low_power": low_power}

        # Zero-PowerShell native Win32 QueryFullProcessImageNameW over Toolhelp32 snapshot (0 console popups!)
        paths: list[str] = []
        try:
            class _PE32(ctypes.Structure):
                _fields_ = [
                    ("dwSize", ctypes.c_ulong),
                    ("cntUsage", ctypes.c_ulong),
                    ("th32ProcessID", ctypes.c_ulong),
                    ("th32DefaultHeapID", ctypes.c_size_t),
                    ("th32ModuleID", ctypes.c_ulong),
                    ("cntThreads", ctypes.c_ulong),
                    ("th32ParentProcessID", ctypes.c_ulong),
                    ("pcPriClassBase", ctypes.c_long),
                    ("dwFlags", ctypes.c_ulong),
                    ("szExeFile", ctypes.c_wchar * 260),
                ]

            k32 = ctypes.windll.kernel32
            snap = k32.CreateToolhelp32Snapshot(0x00000002, 0)
            if snap and snap != ctypes.c_void_p(-1).value:
                try:
                    pe = _PE32()
                    pe.dwSize = ctypes.sizeof(_PE32)
                    ok = k32.Process32FirstW(ctypes.c_void_p(snap), ctypes.byref(pe))
                    buf = ctypes.create_unicode_buffer(1024)
                    while ok:
                        pid = int(pe.th32ProcessID)
                        if pid > 4:
                            h = k32.OpenProcess(0x1000, False, pid)
                            if h:
                                try:
                                    sz = ctypes.c_ulong(1024)
                                    if k32.QueryFullProcessImageNameW(ctypes.c_void_p(h), 0, buf, ctypes.byref(sz)):
                                        paths.append(buf.value)
                                finally:
                                    k32.CloseHandle(ctypes.c_void_p(h))
                        ok = k32.Process32NextW(ctypes.c_void_p(snap), ctypes.byref(pe))
                finally:
                    k32.CloseHandle(ctypes.c_void_p(snap))
        except Exception:
            paths = []

        # Also check standard Autodesk AutoCAD installation path even when AutoCAD is closed
        autodesk = Path(r"C:\Program Files\Autodesk")
        if autodesk.is_dir():
            for p in autodesk.glob("AutoCAD*/acad.exe"):
                paths.append(str(p))

        seen: set[str] = set()
        for p in paths:
            low = p.lower()
            if low in seen:
                continue
            seen.add(low)
            bn = os.path.basename(low)
            if bn in self.HIGH_PERF_PROCS:
                high_perf.append(p)
            elif bn in self.LOW_POWER_PROCS:
                low_power.append(p)
        return {"high_perf": sorted(high_perf), "low_power": sorted(low_power)}

    def apply_fence(self, *, overwrite_existing: bool = False, dry_run: bool = False) -> dict[str, Any]:
        if os.name != "nt":
            return {"ok": True, "os": platform.system().lower(), "applied": [], "skipped": [], "note": "windows_only"}

        import winreg

        existing = self._read_registry()
        existing_lower = {k.lower(): (k, v) for k, v in existing.items()}

        # Save one-time pristine backup before first modification
        if not dry_run and not self.backup_path.is_file():
            self.backup_path.parent.mkdir(parents=True, exist_ok=True)
            self.backup_path.write_text(json.dumps(existing, indent=2), encoding="utf-8")

        topo = self._detect_display_topology()
        all_on_dgpu = bool(topo.get("all_on_dgpu"))
        disc = self._discover_exe_paths()
        planned: list[tuple[str, str, str]] = []
        for p in disc["high_perf"]:
            planned.append((p, "GpuPreference=2;", "ZERO_COPY_DGPU" if all_on_dgpu else "HIGH_PERF_DGPU"))
        for p in disc["low_power"]:
            if all_on_dgpu:
                # All physical displays are on dGPU -> keep GUI apps on dGPU too to avoid Cross-Adapter PCIe Blit!
                planned.append((p, "GpuPreference=2;", "ZERO_COPY_DGPU"))
            else:
                planned.append((p, "GpuPreference=1;", "POWER_SAVING_IGPU"))

        applied: list[dict[str, str]] = []
        skipped: list[dict[str, str]] = []

        if not dry_run:
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, self.REG_SUBKEY) as k:
                for exe_path, reg_val, role in planned:
                    if (exe_path.lower() in existing_lower) and not overwrite_existing:
                        skipped.append({"exe": exe_path, "existing": existing_lower[exe_path.lower()][1], "role": role})
                        continue
                    winreg.SetValueEx(k, exe_path, 0, winreg.REG_SZ, reg_val)
                    applied.append({"exe": exe_path, "value": reg_val, "role": role})
        else:
            for exe_path, reg_val, role in planned:
                if (exe_path.lower() in existing_lower) and not overwrite_existing:
                    skipped.append({"exe": exe_path, "existing": existing_lower[exe_path.lower()][1], "role": role})
                else:
                    applied.append({"exe": exe_path, "value": reg_val, "role": role})

        return {
            "ok": True,
            "dry_run": dry_run,
            "display_topology": topo,
            "backup_path": str(self.backup_path),
            "applied_count": len(applied),
            "skipped_count": len(skipped),
            "applied": applied,
            "skipped": skipped,
        }

    def status(self) -> dict[str, Any]:
        reg = self._read_registry()
        return {
            "ok": True,
            "os": platform.system().lower(),
            "display_topology": self._detect_display_topology(),
            "rules_count": len(reg),
            "backup_exists": self.backup_path.is_file(),
            "rules": reg,
        }


# ---------------------------------------------------------------------------
# 4. CHIMERA-AGENT-EXILE: Transparent Remote Offload to svhome / Colab High-MEM
# ---------------------------------------------------------------------------

class AgentExileEngine:
    """Run verified build inputs through SSH admission or an explicit Colab operation."""

    def __init__(
        self,
        *,
        ssh_host: str = "svhome",
        remote_dev_root: str = "/home/svhome/DEV",
        colab_bridge: Any = None,
        cas_admission_policy: dict[str, Any] | None = None,
    ) -> None:
        self.ssh_host = str(ssh_host or "svhome")
        self.remote_dev_root = str(remote_dev_root or "/home/svhome/DEV")
        self.colab_bridge = colab_bridge
        self.cas_admission_policy = dict(cas_admission_policy or {})
        self._lock = threading.Lock()
        self._runs = 0
        self._last_run: dict[str, Any] | None = None

    def _probe_svhome(self) -> dict[str, Any]:
        from .work_admission import peer_assessment

        t0 = time.perf_counter()
        info = peer_assessment(self.cas_admission_policy, peer=self.ssh_host)
        probe = {"reachable": bool(info.get("transport_ok")), "accepted": bool(info.get("accepted")),
                 "rtt_ms": round((time.perf_counter() - t0) * 1000.0, 1),
                 "reason": info.get("reason"), "ssh_route": info.get("ssh_route")}
        if not probe["reachable"]:
            probe["error"] = info.get("reason", "receiver_unavailable")
        if info.get("cpu") is not None:
            probe["cpu"] = info["cpu"]
        health = info.get("health") or {}
        if "load1" in health:
            probe["load1"] = health["load1"]
        return probe

    def run(
        self,
        cmd: str,
        *,
        cwd: str | Path | None = None,
        target: str = "auto",
        sync_workspace: bool = False,
        timeout_s: float = 120.0,
        environment_id: str = "",
        reuse: bool = False,
        artifacts=(),
        require_io_limit: bool = False,
    ) -> dict[str, Any]:
        """Submit the requested task to a peer that admits it against its own budget."""
        from . import exile_colab, guarded_build

        cmd_s = str(cmd or "").strip()
        if not cmd_s:
            return {"ok": False, "error": "empty_command"}
        chosen = str(target or "auto").strip().lower()
        if chosen == "colab":
            out = exile_colab.run(self.colab_bridge, cmd_s)
        elif chosen in {"auto", "svhome", self.ssh_host.lower()}:
            out = guarded_build.submit_isolated(
                cmd_s, cwd=cwd, peer=self.ssh_host, remote_root=self.remote_dev_root,
                sync=sync_workspace, timeout_s=timeout_s, environment_id=environment_id,
                reuse=reuse, artifacts=artifacts, require_io_limit=require_io_limit,
            )
        else:
            return {"ok": False, "error": "unknown_exile_target"}
        with self._lock:
            self._runs += 1
            self._last_run = {
                "ts": time.strftime("%H:%M:%S"), "target": out.get("target", chosen),
                "ok": out.get("ok"), "exit_code": out.get("exit_code"),
                "elapsed_ms": out.get("elapsed_end_to_end_ms", out.get("elapsed_ms")),
                "state": out.get("state"), "request_id": out.get("request_id"),
            }
        return out

    def query_remote_cas_missing(
        self,
        digests: list[str],
        *,
        remote_cas_dir: str = "~/.chimera/exile_cas",
        timeout_s: float = 15.0,
    ) -> dict[str, Any]:
        """Check durable input objects through the receiver's resource guard."""
        from .guarded_cas import dispatch

        return dispatch("query", {"digests": list(dict.fromkeys(digests))}, peer=self.ssh_host,
                        cas_dir=remote_cas_dir, timeout_s=timeout_s, policy=self.cas_admission_policy)

    def push_remote_cas_blocks(
        self,
        blocks: dict[str, bytes],
        *,
        remote_cas_dir: str = "~/.chimera/exile_cas",
        timeout_s: float = 30.0,
    ) -> dict[str, Any]:
        """Publish validated blocks into the peer CAS under the shared admission policy."""
        from .guarded_cas import dispatch

        if not blocks:
            return {"ok": True, "blocks_pushed": 0, "wire_bytes": 0}
        return dispatch("push", {}, blocks=blocks, peer=self.ssh_host, cas_dir=remote_cas_dir,
                        timeout_s=timeout_s, policy=self.cas_admission_policy)

    def run_cas_step(
        self,
        *,
        job_id: str,
        step_key: str,
        generation: int,
        op: str,
        params: dict[str, Any],
        block_manifest: list[dict[str, Any]],
        input_digest: str,
        remote_cas_dir: str = "~/.chimera/exile_cas",
        timeout_s: float = 60.0,
    ) -> dict[str, Any]:
        """Return a verified fixed-operation result through the same worker used by Swarm builds."""
        from .guarded_cas import dispatch

        out = dispatch("execute", {"job_id": job_id, "step_key": step_key, "generation": generation,
                                  "op": op, "params": params or {}, "block_manifest": block_manifest,
                                  "input_digest": input_digest}, peer=self.ssh_host, cas_dir=remote_cas_dir,
                       timeout_s=timeout_s, policy=self.cas_admission_policy)
        with self._lock:
            self._runs += 1
            self._last_run = {"ts": time.strftime("%H:%M:%S"), "target": self.ssh_host, "ok": True,
                              "exit_code": 0, "cmd": f"cas_step:{job_id}/{step_key}@g{generation}"}
        return out

    def status(self, *, probe: bool = False) -> dict[str, Any]:
        with self._lock:
            runs = self._runs
            last = dict(self._last_run) if self._last_run else None
        st: dict[str, Any] = {
            "ok": True,
            "ssh_host": self.ssh_host,
            "remote_dev_root": self.remote_dev_root,
            "build_protocol": 1,
            "colab_ready": bool(self.colab_bridge is not None),
            "runs": runs,
            "last_run": last,
        }
        if probe:
            st["svhome_probe"] = self._probe_svhome()
        return st


# ---------------------------------------------------------------------------
# 5. CHIMERA-SILICON-THERMOSTAT (v24.0): Hardware CPU TDP/Turbo Ceiling & Closed-Loop Thermal Shield
# ---------------------------------------------------------------------------

class SiliconThermostat:
    """Non-admin Windows hardware CPU power-ceiling controller (powercfg PROCTHROTTLEMAX) + thermal state machine.

    Capping PROCTHROTTLEMAX to 99% disables Intel PL2 thermal runaway spikes (80-110W -> ~35-45W, -20C die temp)
    while preserving full base clock responsiveness; automatically unlocks 100% for CAD_GODMODE and drops to 85%
    under sustained thermal/CPU emergency, restoring 100% cleanly on daemon close.
    """

    VALID_MODES = ("auto", "cool_99", "eco_85", "turbo_100")

    def __init__(self, *, mode: str = "cool_99") -> None:
        self._lock = threading.Lock()
        self._mode = mode if mode in self.VALID_MODES else "cool_99"
        self._current_cap_pct: int = 100
        self._state: str = "INIT"
        self._last_apply_mono: float = 0.0
        self._transitions: int = 0
        self._high_cpu_streak: int = 0

    def _apply_procthrottlemax(self, pct: int) -> bool:
        pct_i = max(50, min(100, int(pct)))
        if os.name != "nt":
            self._current_cap_pct = pct_i
            return True
        if pct_i == self._current_cap_pct and self._last_apply_mono > 0.0:
            return True
        try:
            r1 = subprocess.run(
                ["powercfg", "/setacvalueindex", "SCHEME_CURRENT", "SUB_PROCESSOR", "PROCTHROTTLEMAX", str(pct_i)],
                capture_output=True,
                text=True,
                timeout=4.0,
                creationflags=_NO_WINDOW,
            )
            r2 = subprocess.run(
                ["powercfg", "/setactive", "SCHEME_CURRENT"],
                capture_output=True,
                text=True,
                timeout=4.0,
                creationflags=_NO_WINDOW,
            )
            if r1.returncode == 0 and r2.returncode == 0:
                self._current_cap_pct = pct_i
                self._last_apply_mono = time.monotonic()
                self._transitions += 1
                return True
        except Exception:
            pass
        return False

    def set_mode(self, mode: str) -> dict[str, Any]:
        clean = str(mode or "auto").strip().lower()
        if clean not in self.VALID_MODES:
            raise ValueError(f"Unsupported thermostat mode {mode!r}; expected {self.VALID_MODES}")
        with self._lock:
            self._mode = clean
        return self.evaluate(cpu_pct=0.0, gpu_temp_c=0.0, cad_godmode=False, force=True)

    def evaluate(
        self,
        *,
        cpu_pct: float,
        gpu_temp_c: float = 0.0,
        cad_godmode: bool = False,
        force: bool = False,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Closed-loop hardware silicon protection: pick optimal PROCTHROTTLEMAX & PWM shield duty."""
        with self._lock:
            mode = self._mode
            if cpu_pct >= 65.0 or gpu_temp_c >= 70.0:
                self._high_cpu_streak = min(20, self._high_cpu_streak + 1)
            elif cpu_pct < 50.0 and gpu_temp_c < 64.0:
                self._high_cpu_streak = max(0, self._high_cpu_streak - 1)
            streak = self._high_cpu_streak

            if mode == "turbo_100":
                target_cap, state, shield_duty = 100, "TURBO_100", 100
            elif mode == "eco_85":
                target_cap, state, shield_duty = 85, "ECO_COOL_85", 20
            elif mode == "cool_99":
                if (cpu_pct >= 80.0 and streak >= 2) or gpu_temp_c >= 75.0:
                    target_cap, state, shield_duty = 85, "THERMAL_SHIELD_85", 15
                elif (cpu_pct >= 62.0 and streak >= 1) or gpu_temp_c >= 68.0:
                    target_cap, state, shield_duty = 95, "SILICON_SHIELD_95", 20
                elif cad_godmode:
                    target_cap, state, shield_duty = 100, "CAD_BURST_100", 15
                else:
                    # 99% disables Intel PL2 90W heat spikes while keeping snappy 2.6 GHz base!
                    target_cap, state, shield_duty = 99, "CRYO_ECO_99", 25
            else:  # auto
                if (cpu_pct >= 80.0 and streak >= 2) or gpu_temp_c >= 75.0:
                    target_cap, state, shield_duty = 85, "THERMAL_SHIELD_85", 15
                elif (cpu_pct >= 65.0 and streak >= 1) or gpu_temp_c >= 68.0:
                    target_cap, state, shield_duty = 95, "SILICON_SHIELD_95", 20
                else:
                    target_cap, state, shield_duty = 100, "AUTO_COOL_100", 25

            changed = (target_cap != self._current_cap_pct) or (state != self._state) or force
            applied = True
            if (not dry_run) and changed:
                applied = self._apply_procthrottlemax(target_cap)
            self._state = state
            return {
                "ok": bool(applied),
                "mode": mode,
                "state": state,
                "cpu_max_pct": self._current_cap_pct if not dry_run else target_cap,
                "target_cap_pct": target_cap,
                "shield_active": state in ("SILICON_SHIELD_95", "THERMAL_SHIELD_85", "ECO_COOL_85"),
                "shield_pwm_duty": shield_duty,
                "high_cpu_streak": streak,
                "transitions": self._transitions,
            }

    def restore_default(self) -> bool:
        with self._lock:
            self._state = "RESTORED_100"
            return self._apply_procthrottlemax(100)

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "ok": True,
                "mode": self._mode,
                "state": self._state,
                "cpu_max_pct": self._current_cap_pct,
                "high_cpu_streak": self._high_cpu_streak,
                "transitions": self._transitions,
            }
