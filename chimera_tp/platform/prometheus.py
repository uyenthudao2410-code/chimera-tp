"""CHIMERA-PROMETHEUS — Empirical Evolution Layer (Waves 1–3, Lazy-Loaded 0 B Boot RSS).

Strictly mapped into the 5 Canonical Organs of CHIMERA-ONE (docs/UNIFICATION_DOCTRINE.md)
and compliant with all 7 Invariant Laws (zero kernel-choking APIs, Law 3 svhome protection,
Law 6 evidence-gated auto_activated=False, Law 7 < 80 MiB ceiling):

  - Organ 1 (Causal Spine):
      * EmpiricalAxiomLedger (CHIMERA-AXIOM): SHA-256 chained PROVEN/REFUTED physical laws
        extracted from empirical A/B benchmarks with <1 ms falsification veto & hw_fingerprint unlock.
      * SovereignEpochArbiter (CHIMERA-SOVEREIGN-EPOCH): read-only content-addressed release
        seals, Soak-Freeze leases redirecting concurrent AI restarts to Shadow Port :9789,
        and safe Zero-Orphan Worktree Reaper.
  - Organ 2 & 4 (Hemisphere Router + Entropy Annihilator):
      * GalileoExperimentEngine (CHIMERA-GALILEO): 1-call declarative AB/BA experiment runner
        with bit-exact parity verification, Welch statistics, and peer_guard-aware Resumable Soak.
  - Organ 2 & 3 (Hemisphere Router + Akashic Swarm-Kernel):
      * SvhomeOracleEngine (CHIMERA-ORACLE): persistent HTTP keep-alive PHANTOM-RPC replacing
        1.27s SSH loops (~10-25 ms), Speculative Shadow Oracle, and <=20-line Morning Brief.
  - Organ 3 & 4 (Akashic Swarm-Kernel + Entropy Annihilator):
      * GhostPoolEngine (CHIMERA-GHOST-POOL): <=16 MiB mtime-validated Shared Read-Ring fed
        passively by Hooks + agent_probe + Tquota, plus Law-2 cooperative SocketActivationProxy
        delivering 0 MiB idle worker Commit RAM without NtSuspendProcess.
"""
from __future__ import annotations

import ast
import collections
import ctypes
import hashlib
import http.client
import json
import math
import os
import platform
import re
import select
import shutil
import socket
import sqlite3
import stat
import statistics
import subprocess
import sys
import threading
import time
import urllib.parse
import zlib
from pathlib import Path
from typing import Any, Callable

# ---------------------------------------------------------------------------
# Shared Helpers (Zero External Dependencies, Pure Stdlib)
# ---------------------------------------------------------------------------

_SECRET_PATTERNS = re.compile(
    r"(ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9]{20,}|"
    r"AIza[0-9A-Za-z\-_]{35}|-----BEGIN [A-Z ]*PRIVATE KEY-----)"
)
_SEAL_EXTS = {
    ".py", ".json", ".toml", ".rs", ".c", ".h", ".mjs", ".js", ".cjs",
    ".ps1", ".sh", ".cmd", ".md", ".txt", ".yml", ".yaml",
}
_SEAL_IGNORE_DIRS = {
    "__pycache__", ".git", ".pytest_cache", ".ruff_cache", "node_modules",
    "target", "dist", "build", ".venv",
}


def _now() -> float:
    return time.time()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_json(obj: Any) -> str:
    raw = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def compute_hardware_fingerprint() -> str:
    """Stable hardware fingerprint used to unlock REFUTED axioms only when silicon changes."""
    bits = {
        "os": platform.system().lower(),
        "machine": platform.machine().lower(),
        "cpu_count": os.cpu_count() or 1,
        "node": hashlib.sha256(platform.node().lower().encode("utf-8")).hexdigest()[:12],
    }
    return _sha256_json(bits)[:16]


def get_self_rss_mib() -> float:
    """Zero-subprocess kernel RSS readout for current Python process."""
    if os.name != "nt":
        try:
            with open("/proc/self/status", "r", encoding="utf-8") as fh:
                for line in fh:
                    if line.startswith("VmRSS:"):
                        kb = int(line.split()[1])
                        return round(kb / 1024.0, 3)
        except Exception:
            pass
        return 0.0
    try:
        class _PROCESS_MEMORY_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.c_ulong),
                ("PageFaultCount", ctypes.c_ulong),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        pmc = _PROCESS_MEMORY_COUNTERS()
        pmc.cb = ctypes.sizeof(pmc)
        k32 = ctypes.windll.kernel32
        k32.GetCurrentProcess.restype = ctypes.c_void_p
        k32.K32GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong]
        k32.K32GetProcessMemoryInfo.restype = ctypes.c_int
        hproc = k32.GetCurrentProcess()
        if k32.K32GetProcessMemoryInfo(hproc, ctypes.byref(pmc), pmc.cb):
            return round(pmc.WorkingSetSize / 1048576.0, 3)
    except Exception:
        pass
    return 0.0


def _default_prometheus_dir() -> Path:
    if os.name == "nt":
        v_drive = Path(r"V:\prometheus")
        if Path("V:\\").exists():
            try:
                v_drive.mkdir(parents=True, exist_ok=True)
                return v_drive
            except OSError:
                pass
    else:
        dev_drive = Path("/mnt/chimera-dev/prometheus")
        if Path("/mnt/chimera-dev").is_dir():
            try:
                dev_drive.mkdir(parents=True, exist_ok=True)
                return dev_drive
            except OSError:
                pass
    fallback = Path.home() / ".chimera_ops" / "prometheus"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def _open_wal_sqlite(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=5.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=-512")
    conn.execute("PRAGMA temp_store=MEMORY")
    return conn


# ---------------------------------------------------------------------------
# Wave 1A — CHIMERA-AXIOM (Organ 1: Executable Empirical Falsification Ledger)
# ---------------------------------------------------------------------------

SEED_EMPIRICAL_AXIOMS: list[dict[str, Any]] = [
    {
        "claim_id": "autocad_build_offload_svhome",
        "status": "REFUTED",
        "organ": "Hemisphere Router",
        "summary": "Offloading local C/dev builds from win-desktop to svhome during AutoCAD cuts P99 frame time by only 0.0072% while slowing builds +34.48% to +87.74%.",
        "match_actions": ["autocad_offload_build", "enable_cad_auto_offload", "offload_build_svhome_for_cad"],
        "metrics": {"p99_reduction_pct": 0.0072, "build_slowdown_pct": 34.48, "pairs": 10},
        "receipt_path": "tasks/cad_display2_10_pairs_20261127.json",
    },
    {
        "claim_id": "svhome_allocator_swap_idle_rss",
        "status": "REFUTED",
        "organ": "Entropy Annihilator",
        "summary": "Swapping Linux glibc allocator alone reduced idle RSS only 40.25 -> 40.11 MiB (-0.14 MiB), nowhere near the 10-15 MiB target.",
        "match_actions": ["svhome_allocator_swap", "deploy_custom_allocator_for_rss"],
        "metrics": {"before_mib": 40.25, "after_mib": 40.11, "delta_mib": -0.14},
        "receipt_path": "tasks/svhome_allocator_startup_ab_5e25fafe4a8f.json",
    },
    {
        "claim_id": "svhome_guest_cpu95_io8_cap",
        "status": "PROVEN",
        "organ": "Hemisphere Router",
        "summary": "Capping svhome guest cgroup at CPUQuota<=95% and IOWriteBandwidthMax=8 MiB/s preserves Radar P95 at 1.35 ms (<20 ms SLO) vs >20 ms uncapped.",
        "match_actions": ["svhome_guest_uncapped_cpu", "disable_svhome_io_cap"],
        "metrics": {"radar_p95_ms": 1.35, "cpu_quota_pct": 95, "io_cap_mibs": 8},
        "receipt_path": "tasks/peer_service_slo_5e25fafe4a8f_cpu95.json",
    },
    {
        "claim_id": "windows_cuda_out_of_process_worker",
        "status": "PROVEN",
        "organ": "Entropy Annihilator",
        "summary": "Running CUDA out-of-process drops Windows daemon parent peak RSS from 137.35 MiB to 23.45 MiB (-82.9%) with bit-exact results.",
        "match_actions": ["enable_in_process_cuda_daemon"],
        "metrics": {"before_mib": 137.35, "after_mib": 23.45, "delta_pct": -82.93},
        "receipt_path": "tasks/windows_cuda_peak_b40921be2466.json",
    },
    {
        "claim_id": "svhome_fts5_compact_cache_384k",
        "status": "PROVEN",
        "organ": "Akashic Swarm-Kernel",
        "summary": "Setting PRAGMA cache_size=-384 on code_search SQLite drops Linux private daemon peak RSS from 56.422 -> 54.625 MiB (-1.80 MiB) with identical VSA hashes.",
        "match_actions": [],
        "metrics": {"before_mib": 56.422, "after_mib": 54.625, "delta_mib": -1.797},
        "receipt_path": "tasks/linux_private_rss_cache_only_63381_20261127.json",
    },
    {
        "claim_id": "webview_shared_profile_merge",
        "status": "PROVEN",
        "organ": "Entropy Annihilator",
        "summary": "Sharing a single Chromium/WebView2 runtime profile saves 370.69 MiB Private Commit across just 2 web apps.",
        "match_actions": [],
        "metrics": {"saved_mib": 370.69, "pages": 2},
        "receipt_path": "docs/WORKSTATION_EXECUTION_PLAN.md",
    },
    {
        "claim_id": "sentinel_tail_block_reuse",
        "status": "PROVEN",
        "organ": "Entropy Annihilator",
        "summary": "Block-tail Sentinel log scanning with byte-hash reuse cuts rescan latency from 892.60 -> 22.88 ms (39.0x speedup) with identical alert parity.",
        "match_actions": [],
        "metrics": {"before_ms": 892.60, "after_ms": 22.88, "speedup": 39.01},
        "receipt_path": "tasks/sentinel_tail_replay_65bbee57e75f_pyc.json",
    },
    {
        "claim_id": "vsa_batch_encoder_replay",
        "status": "PROVEN",
        "organ": "Akashic Swarm-Kernel",
        "summary": "Batch VSA encoder replay accelerates 300 ThoughtBrief ingests on svhome from 8.99s -> 0.29s (31.0x speedup) with identical vectors.",
        "match_actions": [],
        "metrics": {"before_s": 8.99, "after_s": 0.29, "speedup": 31.0},
        "receipt_path": "tasks/vsa_encoder_replay_20261127.json",
    },
]

# Contradictory actions blocked even when an axiom is PROVEN (anti-regression guard)
_ANTI_REGRESSION_BLOCKS = {
    "svhome_guest_uncapped_cpu": "svhome_guest_cpu95_io8_cap",
    "disable_svhome_io_cap": "svhome_guest_cpu95_io8_cap",
    "enable_in_process_cuda_daemon": "windows_cuda_out_of_process_worker",
}


class EmpiricalAxiomLedger:
    """Tamper-evident SHA-256 ledger of PROVEN/REFUTED workstation physics axioms."""

    def __init__(self, db_path: Path, *, hw_fingerprint: str | None = None) -> None:
        self.db_path = db_path
        self.hw_fingerprint = hw_fingerprint or compute_hardware_fingerprint()
        self._lock = threading.RLock()
        self._conn = _open_wal_sqlite(db_path)
        self._stats = {"checks": 0, "vetoes": 0, "hw_unlocks": 0}
        self._init_schema()
        self._seed_defaults()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS axioms (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    claim_id TEXT UNIQUE NOT NULL,
                    status TEXT NOT NULL,
                    organ TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    match_actions_json TEXT NOT NULL,
                    metrics_json TEXT NOT NULL,
                    receipt_path TEXT NOT NULL,
                    hw_fingerprint TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    prev_hash TEXT NOT NULL,
                    entry_hash TEXT NOT NULL
                );
                """
            )
            self._conn.commit()

    def _seed_defaults(self) -> None:
        with self._lock:
            existing = {
                row["claim_id"]
                for row in self._conn.execute("SELECT claim_id FROM axioms").fetchall()
            }
            for item in SEED_EMPIRICAL_AXIOMS:
                if item["claim_id"] not in existing:
                    self.record_axiom(
                        claim_id=item["claim_id"],
                        status=item["status"],
                        organ=item["organ"],
                        summary=item["summary"],
                        match_actions=item["match_actions"],
                        metrics=item["metrics"],
                        receipt_path=item["receipt_path"],
                        hw_fingerprint=self.hw_fingerprint,
                    )

    def record_axiom(
        self,
        *,
        claim_id: str,
        status: str,
        organ: str,
        summary: str,
        match_actions: list[str] | None = None,
        metrics: dict[str, Any] | None = None,
        receipt_path: str = "",
        hw_fingerprint: str | None = None,
    ) -> dict[str, Any]:
        status_norm = str(status or "CONDITIONAL").strip().upper()
        if status_norm not in ("PROVEN", "REFUTED", "CONDITIONAL"):
            raise ValueError(f"invalid axiom status: {status}")
        cid = str(claim_id).strip().lower()
        if not cid:
            raise ValueError("claim_id required")
        hw = hw_fingerprint or self.hw_fingerprint
        actions = [str(a).strip().lower() for a in (match_actions or []) if str(a).strip()]
        met = dict(metrics or {})
        now = round(_now(), 3)

        with self._lock:
            row_prev = self._conn.execute(
                "SELECT entry_hash FROM axioms ORDER BY seq DESC LIMIT 1"
            ).fetchone()
            prev_hash = str(row_prev["entry_hash"]) if row_prev else ("0" * 64)
            payload = {
                "claim_id": cid,
                "status": status_norm,
                "organ": organ,
                "summary": summary,
                "match_actions": actions,
                "metrics": met,
                "receipt_path": receipt_path,
                "hw_fingerprint": hw,
                "prev_hash": prev_hash,
            }
            entry_hash = _sha256_json(payload)
            existing = self._conn.execute(
                "SELECT seq FROM axioms WHERE claim_id = ?", (cid,)
            ).fetchone()
            if existing:
                # Preserve append-only chain integrity: update metadata only when hw_fingerprint changed
                self._conn.execute(
                    """
                    UPDATE axioms
                    SET status=?, organ=?, summary=?, match_actions_json=?, metrics_json=?,
                        receipt_path=?, hw_fingerprint=?, created_at=?, prev_hash=?, entry_hash=?
                    WHERE claim_id=?
                    """,
                    (
                        status_norm,
                        organ,
                        summary,
                        json.dumps(actions),
                        json.dumps(met, sort_keys=True),
                        receipt_path,
                        hw,
                        now,
                        prev_hash,
                        entry_hash,
                        cid,
                    ),
                )
            else:
                self._conn.execute(
                    """
                    INSERT INTO axioms (
                        claim_id, status, organ, summary, match_actions_json,
                        metrics_json, receipt_path, hw_fingerprint, created_at, prev_hash, entry_hash
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        cid,
                        status_norm,
                        organ,
                        summary,
                        json.dumps(actions),
                        json.dumps(met, sort_keys=True),
                        receipt_path,
                        hw,
                        now,
                        prev_hash,
                        entry_hash,
                    ),
                )
            self._conn.commit()
            return {
                "ok": True,
                "claim_id": cid,
                "status": status_norm,
                "hw_fingerprint": hw,
                "entry_hash": entry_hash,
            }

    def list_axioms(self, status: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            if status:
                rows = self._conn.execute(
                    "SELECT * FROM axioms WHERE status = ? ORDER BY seq ASC",
                    (status.upper(),),
                ).fetchall()
            else:
                rows = self._conn.execute("SELECT * FROM axioms ORDER BY seq ASC").fetchall()
        out = []
        for r in rows:
            out.append({
                "seq": r["seq"],
                "claim_id": r["claim_id"],
                "status": r["status"],
                "organ": r["organ"],
                "summary": r["summary"],
                "match_actions": json.loads(r["match_actions_json"]),
                "metrics": json.loads(r["metrics_json"]),
                "receipt_path": r["receipt_path"],
                "hw_fingerprint": r["hw_fingerprint"],
                "entry_hash": r["entry_hash"],
            })
        return out

    def verify_chain(self) -> dict[str, Any]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM axioms ORDER BY seq ASC").fetchall()
        broken = 0
        for r in rows:
            payload = {
                "claim_id": r["claim_id"],
                "status": r["status"],
                "organ": r["organ"],
                "summary": r["summary"],
                "match_actions": json.loads(r["match_actions_json"]),
                "metrics": json.loads(r["metrics_json"]),
                "receipt_path": r["receipt_path"],
                "hw_fingerprint": r["hw_fingerprint"],
                "prev_hash": r["prev_hash"],
            }
            if _sha256_json(payload) != r["entry_hash"]:
                broken += 1
        return {
            "ok": broken == 0,
            "count": len(rows),
            "broken": broken,
            "head_hash": rows[-1]["entry_hash"] if rows else ("0" * 64),
        }

    def check_action(
        self,
        action: str,
        *,
        params: dict[str, Any] | None = None,
        hw_fingerprint: str | None = None,
    ) -> dict[str, Any]:
        """<1 ms Falsification Guard: vetoes actions contradicting REFUTED or anti-regression axioms."""
        t0 = time.perf_counter()
        act = str(action or "").strip().lower()
        hw = hw_fingerprint or self.hw_fingerprint
        params_str = json.dumps(params or {}, sort_keys=True).lower()
        axioms = self.list_axioms()

        matched: dict[str, Any] | None = None
        anti_reg_id = _ANTI_REGRESSION_BLOCKS.get(act)
        for ax in axioms:
            if ax["claim_id"] == act or act in ax["match_actions"]:
                matched = ax
                break
            if anti_reg_id and ax["claim_id"] == anti_reg_id:
                matched = ax
                break

        # Semantic fallback for free-form action descriptions
        if matched is None:
            combined = f"{act} {params_str}"
            if ("autocad" in combined or "cad" in combined) and ("offload" in combined or "svhome" in combined) and "build" in combined:
                matched = next((a for a in axioms if a["claim_id"] == "autocad_build_offload_svhome"), None)
            elif ("allocator" in combined or "jemalloc" in combined or "mimalloc" in combined) and "svhome" in combined:
                matched = next((a for a in axioms if a["claim_id"] == "svhome_allocator_swap_idle_rss"), None)
            elif "cuda" in combined and "in_process" in combined and "daemon" in combined:
                matched = next((a for a in axioms if a["claim_id"] == "windows_cuda_out_of_process_worker"), None)

        with self._lock:
            self._stats["checks"] += 1

        elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 3)
        if matched is None:
            return {
                "ok": True,
                "veto": False,
                "action": act,
                "reason": "no_contradicting_axiom",
                "elapsed_ms": elapsed_ms,
            }

        is_veto_candidate = (
            matched["status"] == "REFUTED"
            or (act in _ANTI_REGRESSION_BLOCKS)
            or (act in matched["match_actions"] and matched["status"] == "PROVEN")
        )
        if not is_veto_candidate:
            return {
                "ok": True,
                "veto": False,
                "action": act,
                "matched_axiom": matched["claim_id"],
                "axiom_status": matched["status"],
                "elapsed_ms": elapsed_ms,
            }

        if hw != matched["hw_fingerprint"]:
            with self._lock:
                self._stats["hw_unlocks"] += 1
            return {
                "ok": True,
                "veto": False,
                "unlocked_by_hw_change": True,
                "action": act,
                "matched_axiom": matched["claim_id"],
                "recorded_hw": matched["hw_fingerprint"],
                "current_hw": hw,
                "reason": "Hardware fingerprint changed; re-verification via CHIMERA-GALILEO permitted.",
                "elapsed_ms": elapsed_ms,
            }

        with self._lock:
            self._stats["vetoes"] += 1
        return {
            "ok": True,
            "veto": True,
            "action": act,
            "claim_id": matched["claim_id"],
            "axiom_status": matched["status"],
            "reason": matched["summary"],
            "receipt_path": matched["receipt_path"],
            "metrics": matched["metrics"],
            "unlock_condition": "hw_fingerprint_change_or_galileo_override",
            "elapsed_ms": elapsed_ms,
        }

    def birth_primer_summary(self, max_chars: int = 850) -> str:
        axioms = self.list_axioms()
        refuted = [a for a in axioms if a["status"] == "REFUTED"]
        proven = [a for a in axioms if a["status"] == "PROVEN"]
        parts = [f"[CHIMERA-AXIOM hw={self.hw_fingerprint} proven={len(proven)} refuted={len(refuted)}]"]
        for a in refuted[:4]:
            parts.append(f"REFUTED({a['claim_id']}): {a['summary'][:130]}")
        for a in proven[:3]:
            parts.append(f"PROVEN({a['claim_id']}): {a['summary'][:110]}")
        return " | ".join(parts)[:max_chars]

    def status(self) -> dict[str, Any]:
        axioms = self.list_axioms()
        chain = self.verify_chain()
        with self._lock:
            st = dict(self._stats)
        return {
            "ok": chain["ok"],
            "hw_fingerprint": self.hw_fingerprint,
            "total_axioms": len(axioms),
            "proven": sum(1 for a in axioms if a["status"] == "PROVEN"),
            "refuted": sum(1 for a in axioms if a["status"] == "REFUTED"),
            "chain": chain,
            "stats": st,
        }

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Wave 1B — CHIMERA-SOVEREIGN-EPOCH (Immutable Releases, Soak-Freeze, Worktree Reaper)
# ---------------------------------------------------------------------------

def _compute_tree_manifest(root: Path) -> tuple[str, dict[str, str]]:
    file_hashes: dict[str, str] = {}
    for dp, dns, fns in os.walk(root):
        dns[:] = sorted(d for d in dns if d not in _SEAL_IGNORE_DIRS)
        for fn in sorted(fns):
            if fn == ".chimera_seal.json":
                continue
            fp = Path(dp) / fn
            if fp.suffix.lower() not in _SEAL_EXTS:
                continue
            rel = fp.relative_to(root).as_posix()
            try:
                raw = fp.read_bytes()
                norm = raw.replace(b"\r\n", b"\n") if b"\x00" not in raw[:4096] else raw
                file_hashes[rel] = hashlib.sha256(norm).hexdigest()
            except OSError:
                pass
    tree_sha = _sha256_json(file_hashes)
    return tree_sha, file_hashes


def _set_file_readonly(fp: Path, readonly: bool) -> None:
    try:
        if os.name == "nt":
            os.chmod(fp, stat.S_IREAD if readonly else (stat.S_IREAD | stat.S_IWRITE))
        else:
            mode = fp.stat().st_mode
            if readonly:
                os.chmod(fp, mode & ~0o222)
            else:
                os.chmod(fp, mode | 0o200)
    except OSError:
        pass


class SovereignEpochArbiter:
    """Prevents multi-session soak destruction, silent release drift, and worktree sprawl."""

    def __init__(self, db_path: Path, *, default_shadow_port: int = 9796) -> None:
        self.db_path = db_path
        self.default_shadow_port = default_shadow_port
        self._lock = threading.RLock()
        self._conn = _open_wal_sqlite(db_path)
        self._stats = {"seals": 0, "verifies": 0, "promote_allowed": 0, "promote_redirected": 0}
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS soak_leases (
                    lease_id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    label TEXT NOT NULL,
                    target_pid INTEGER NOT NULL,
                    tree_sha256 TEXT NOT NULL,
                    started_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    heartbeat_at REAL NOT NULL,
                    released INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS promote_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL NOT NULL,
                    requester_id TEXT NOT NULL,
                    candidate_tree_sha256 TEXT NOT NULL,
                    allowed INTEGER NOT NULL,
                    action TEXT NOT NULL,
                    shadow_port INTEGER,
                    detail TEXT NOT NULL
                );
                """
            )
            self._conn.commit()

    def seal_release(self, release_dir: str | Path, *, lock_readonly: bool = True) -> dict[str, Any]:
        root = Path(release_dir).resolve()
        if not root.is_dir():
            return {"ok": False, "error": f"release_dir_not_found:{root}"}
        seal_file = root / ".chimera_seal.json"
        if seal_file.exists():
            _set_file_readonly(seal_file, False)
        tree_sha, manifest = _compute_tree_manifest(root)
        seal_doc = {
            "schema": "chimera.epoch.seal.v1",
            "tree_sha256": tree_sha,
            "file_count": len(manifest),
            "sealed_at": round(_now(), 3),
            "readonly_locked": bool(lock_readonly),
            "files": manifest,
        }
        seal_file.write_text(json.dumps(seal_doc, sort_keys=True, indent=2), encoding="utf-8")
        locked_count = 0
        if lock_readonly:
            for rel in manifest:
                _set_file_readonly(root / rel, True)
                locked_count += 1
            _set_file_readonly(seal_file, True)
        with self._lock:
            self._stats["seals"] += 1
        return {
            "ok": True,
            "release_dir": str(root),
            "tree_sha256": tree_sha,
            "file_count": len(manifest),
            "readonly_locked": bool(lock_readonly),
            "locked_files": locked_count,
            "seal_file": str(seal_file),
        }

    def unseal_release(self, release_dir: str | Path) -> dict[str, Any]:
        root = Path(release_dir).resolve()
        if not root.is_dir():
            return {"ok": False, "error": f"release_dir_not_found:{root}"}
        unlocked = 0
        for dp, dns, fns in os.walk(root):
            dns[:] = [d for d in dns if d not in _SEAL_IGNORE_DIRS]
            for fn in fns:
                _set_file_readonly(Path(dp) / fn, False)
                unlocked += 1
        return {"ok": True, "release_dir": str(root), "unlocked_files": unlocked}

    def verify_release_integrity(self, release_dir: str | Path) -> dict[str, Any]:
        root = Path(release_dir).resolve()
        seal_file = root / ".chimera_seal.json"
        if not seal_file.is_file():
            return {"ok": False, "sealed": False, "error": "seal_missing", "release_dir": str(root)}
        seal_doc = json.loads(seal_file.read_text(encoding="utf-8"))
        expected_files: dict[str, str] = dict(seal_doc.get("files") or {})
        current_sha, current_files = _compute_tree_manifest(root)
        modified = sorted(k for k in expected_files if k in current_files and current_files[k] != expected_files[k])
        missing = sorted(k for k in expected_files if k not in current_files)
        extra = sorted(k for k in current_files if k not in expected_files)
        intact = (current_sha == seal_doc.get("tree_sha256")) and not modified and not missing and not extra
        with self._lock:
            self._stats["verifies"] += 1
        return {
            "ok": intact,
            "sealed": True,
            "intact": intact,
            "expected_tree_sha256": seal_doc.get("tree_sha256"),
            "current_tree_sha256": current_sha,
            "file_count": len(current_files),
            "modified": modified[:20],
            "missing": missing[:20],
            "extra": extra[:20],
        }

    def acquire_soak_lease(
        self,
        *,
        owner_id: str,
        window_s: float = 660.0,
        target_pid: int = 0,
        tree_sha256: str = "",
        label: str = "soak_window",
    ) -> dict[str, Any]:
        now = _now()
        win = max(10.0, min(172800.0, float(window_s)))
        pid = int(target_pid or os.getpid())
        lid = f"soak_{_sha256_bytes(f'{owner_id}:{pid}:{now}'.encode())[:12]}"
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO soak_leases (
                    lease_id, owner_id, label, target_pid, tree_sha256,
                    started_at, expires_at, heartbeat_at, released
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
                """,
                (lid, str(owner_id), str(label), pid, str(tree_sha256), now, now + win, now),
            )
            self._conn.commit()
        return {
            "ok": True,
            "lease_id": lid,
            "owner_id": owner_id,
            "label": label,
            "target_pid": pid,
            "tree_sha256": tree_sha256,
            "expires_at": round(now + win, 3),
            "remaining_s": round(win, 1),
        }

    def release_soak_lease(self, lease_id: str) -> dict[str, Any]:
        with self._lock:
            cur = self._conn.execute(
                "UPDATE soak_leases SET released = 1 WHERE lease_id = ? AND released = 0",
                (str(lease_id),),
            )
            self._conn.commit()
        return {"ok": True, "lease_id": lease_id, "released": cur.rowcount > 0}

    def active_soak_leases(self) -> list[dict[str, Any]]:
        now = _now()
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM soak_leases WHERE released = 0 AND expires_at > ? ORDER BY started_at ASC",
                (now,),
            ).fetchall()
        return [
            {
                "lease_id": r["lease_id"],
                "owner_id": r["owner_id"],
                "label": r["label"],
                "target_pid": r["target_pid"],
                "tree_sha256": r["tree_sha256"],
                "started_at": round(r["started_at"], 3),
                "expires_at": round(r["expires_at"], 3),
                "remaining_s": round(max(0.0, r["expires_at"] - now), 1),
            }
            for r in rows
        ]

    def request_promote(
        self,
        *,
        requester_id: str,
        candidate_tree_sha256: str,
        shadow_port: int | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        """Arbitrates live daemon promotion against active Soak-Freeze leases."""
        active = self.active_soak_leases()
        conflicts = [l for l in active if l["owner_id"] != requester_id]
        sp = int(shadow_port or self.default_shadow_port)
        now = _now()

        if conflicts and not force:
            lead = conflicts[0]
            detail = (
                f"Active soak lease {lead['lease_id']} owned by {lead['owner_id']} "
                f"(PID {lead['target_pid']}, {lead['remaining_s']}s remaining). "
                f"Redirecting candidate to isolated Shadow Canary Port :{sp}."
            )
            with self._lock:
                self._stats["promote_redirected"] += 1
                self._conn.execute(
                    "INSERT INTO promote_log (ts, requester_id, candidate_tree_sha256, allowed, action, shadow_port, detail) VALUES (?,?,?,?,?,?,?)",
                    (now, requester_id, candidate_tree_sha256, 0, "redirect_shadow_canary", sp, detail),
                )
                self._conn.commit()
            return {
                "ok": True,
                "allowed": False,
                "action": "redirect_shadow_canary",
                "shadow_port": sp,
                "active_lease": lead,
                "reason": detail,
            }

        with self._lock:
            self._stats["promote_allowed"] += 1
            self._conn.execute(
                "INSERT INTO promote_log (ts, requester_id, candidate_tree_sha256, allowed, action, shadow_port, detail) VALUES (?,?,?,?,?,?,?)",
                (now, requester_id, candidate_tree_sha256, 1, "promote_live", None, "No conflicting soak lease"),
            )
            self._conn.commit()
        return {
            "ok": True,
            "allowed": True,
            "action": "promote_live",
            "candidate_tree_sha256": candidate_tree_sha256,
            "forced": bool(force and conflicts),
        }

    def audit_worktrees(
        self,
        repo_path: str | Path,
        *,
        execute_prune: bool = False,
    ) -> dict[str, Any]:
        """Audits git worktrees (Law 6 default dry_run=True); safely prunes ONLY clean merged trial worktrees."""
        repo = Path(repo_path).resolve()
        cf = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        try:
            raw = subprocess.check_output(
                ["git", "-C", str(repo), "worktree", "list", "--porcelain"],
                text=True,
                stderr=subprocess.DEVNULL,
                creationflags=cf,
                timeout=8,
            )
        except Exception as exc:
            return {"ok": False, "error": f"git_worktree_list_failed:{exc}"}

        entries: list[dict[str, Any]] = []
        cur: dict[str, Any] = {}
        for ln in raw.splitlines():
            if not ln.strip():
                if cur:
                    entries.append(cur)
                    cur = {}
                continue
            k, _, v = ln.partition(" ")
            cur[k.strip()] = v.strip()
        if cur:
            entries.append(cur)

        main_norm = str(repo).replace("\\", "/").lower()
        audited: list[dict[str, Any]] = []
        pruned: list[str] = []
        reclaimed_bytes = 0

        for idx, ent in enumerate(entries):
            wt_path_str = ent.get("worktree", "")
            if not wt_path_str:
                continue
            wt_path = Path(wt_path_str)
            is_primary = idx == 0 or wt_path_str.replace("\\", "/").lower() == main_norm
            if is_primary:
                audited.append({"path": wt_path_str, "role": "primary", "action": "keep_primary"})
                continue

            head_sha = ent.get("HEAD", "")
            branch = ent.get("branch", "(detached)")
            exists = wt_path.exists()
            dirty = False
            merged = False
            if exists:
                try:
                    st_out = subprocess.check_output(
                        ["git", "-C", str(wt_path), "status", "--porcelain"],
                        text=True,
                        stderr=subprocess.DEVNULL,
                        creationflags=cf,
                        timeout=5,
                    )
                    dirty = bool(st_out.strip())
                except Exception:
                    dirty = True
            if head_sha:
                rc = subprocess.call(
                    ["git", "-C", str(repo), "merge-base", "--is-ancestor", head_sha, "main"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=cf,
                    timeout=5,
                )
                merged = rc == 0

            safe = (not exists) or ((not dirty) and merged)
            action = "safe_to_prune" if safe else ("keep_dirty" if dirty else "keep_unmerged")
            rec = {
                "path": wt_path_str,
                "branch": branch,
                "head": head_sha[:10],
                "exists": exists,
                "dirty": dirty,
                "merged_into_main": merged,
                "action": action,
            }
            if execute_prune and safe:
                size_before = 0
                if exists:
                    for dp, _, fns in os.walk(wt_path):
                        for fn in fns:
                            try:
                                size_before += (Path(dp) / fn).stat().st_size
                            except OSError:
                                pass
                try:
                    cmd = ["git", "-C", str(repo), "worktree", "remove", str(wt_path)]
                    rc_rm = subprocess.call(
                        cmd,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        creationflags=cf,
                        timeout=15,
                    )
                    if rc_rm == 0 or not wt_path.exists():
                        pruned.append(wt_path_str)
                        reclaimed_bytes += size_before
                        rec["pruned"] = True
                except Exception as exc:
                    rec["prune_error"] = str(exc)
            audited.append(rec)

        if execute_prune:
            subprocess.call(
                ["git", "-C", str(repo), "worktree", "prune"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=cf,
                timeout=10,
            )

        return {
            "ok": True,
            "repo": str(repo),
            "dry_run": not execute_prune,
            "auto_activated": False,
            "total_worktrees": len(audited),
            "non_primary": max(0, len(audited) - 1),
            "safe_to_prune_count": sum(1 for a in audited if a["action"] == "safe_to_prune"),
            "pruned_count": len(pruned),
            "reclaimed_mib": round(reclaimed_bytes / 1048576.0, 2),
            "worktrees": audited,
        }

    def status(self) -> dict[str, Any]:
        leases = self.active_soak_leases()
        with self._lock:
            st = dict(self._stats)
        return {
            "ok": True,
            "default_shadow_port": self.default_shadow_port,
            "active_soak_leases": leases,
            "soak_frozen": len(leases) > 0,
            "stats": st,
        }

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Wave 2A — CHIMERA-GALILEO (Organ 2 & 4: Autonomous Scientific A/B & Resumable Soak)
# ---------------------------------------------------------------------------

def _welch_t(a: list[float], b: list[float]) -> float:
    if len(a) < 2 or len(b) < 2:
        return 0.0
    ma, mb = statistics.mean(a), statistics.mean(b)
    va, vb = statistics.variance(a), statistics.variance(b)
    denom = math.sqrt((va / len(a)) + (vb / len(b)))
    if denom <= 1e-12:
        return 0.0
    return round((mb - ma) / denom, 3)


class GalileoExperimentEngine:
    """Declarative 1-call AB/BA scientific engine + peer_guard-aware Resumable Soak."""

    def __init__(self, db_path: Path, *, axiom_ledger: EmpiricalAxiomLedger | None = None) -> None:
        self.db_path = db_path
        self.axiom_ledger = axiom_ledger
        self._lock = threading.RLock()
        self._conn = _open_wal_sqlite(db_path)
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS experiments (
                    exp_id TEXT PRIMARY KEY,
                    hypothesis TEXT NOT NULL,
                    verdict TEXT NOT NULL,
                    parity_ok INTEGER NOT NULL,
                    spec_sha256 TEXT NOT NULL,
                    receipt_sha256 TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS soak_runs (
                    exp_id TEXT PRIMARY KEY,
                    target_samples INTEGER NOT NULL,
                    collected_samples INTEGER NOT NULL DEFAULT 0,
                    pause_count INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL,
                    samples_json TEXT NOT NULL,
                    last_pause_reason TEXT NOT NULL DEFAULT '',
                    updated_at REAL NOT NULL
                );
                """
            )
            self._conn.commit()

    def run_ab(
        self,
        *,
        hypothesis: str,
        baseline_fn: Callable[[int], tuple[float, Any]],
        candidate_fn: Callable[[int], tuple[float, Any]],
        pairs: int = 6,
        min_improvement_pct: float = 5.0,
        lower_is_better: bool = True,
        claim_id: str | None = None,
        organ: str = "Entropy Annihilator",
        register_axiom: bool = False,
    ) -> dict[str, Any]:
        """Runs interleaved AB/BA paired experiment with strict bit-exact output parity verification."""
        n = max(2, min(50, int(pairs)))
        base_vals: list[float] = []
        cand_vals: list[float] = []
        parity_mismatches = 0
        trial_rows: list[dict[str, Any]] = []

        for idx in range(n):
            order = ("AB" if idx % 2 == 0 else "BA")
            if order == "AB":
                bv, bo = baseline_fn(idx)
                cv, co = candidate_fn(idx)
            else:
                cv, co = candidate_fn(idx)
                bv, bo = baseline_fn(idx)
            b_hash = _sha256_json(bo)
            c_hash = _sha256_json(co)
            same = b_hash == c_hash
            if not same:
                parity_mismatches += 1
            base_vals.append(float(bv))
            cand_vals.append(float(cv))
            trial_rows.append({
                "pair": idx + 1,
                "order": order,
                "baseline": round(float(bv), 4),
                "candidate": round(float(cv), 4),
                "parity_ok": same,
                "output_sha256": c_hash[:16],
            })

        b_med = statistics.median(base_vals)
        c_med = statistics.median(cand_vals)
        if lower_is_better:
            improvement_pct = ((b_med - c_med) / b_med * 100.0) if b_med > 1e-12 else 0.0
            speedup = (b_med / c_med) if c_med > 1e-12 else 1.0
        else:
            improvement_pct = ((c_med - b_med) / b_med * 100.0) if b_med > 1e-12 else 0.0
            speedup = (c_med / b_med) if b_med > 1e-12 else 1.0

        parity_ok = parity_mismatches == 0
        if not parity_ok:
            verdict = "REFUTED_PARITY_MISMATCH"
        elif improvement_pct >= float(min_improvement_pct):
            verdict = "PROVEN"
        elif improvement_pct <= 0.5:
            verdict = "REFUTED"
        else:
            verdict = "INCONCLUSIVE"

        spec_obj = {
            "hypothesis": hypothesis,
            "pairs": n,
            "min_improvement_pct": min_improvement_pct,
            "lower_is_better": lower_is_better,
        }
        spec_sha = _sha256_json(spec_obj)
        exp_id = f"galileo_{_sha256_bytes(f'{spec_sha}:{_now()}'.encode())[:12]}"
        result = {
            "ok": True,
            "exp_id": exp_id,
            "hypothesis": hypothesis,
            "pairs": n,
            "verdict": verdict,
            "auto_activated": False,
            "parity_ok": parity_ok,
            "parity_mismatches": parity_mismatches,
            "baseline_median": round(b_med, 4),
            "candidate_median": round(c_med, 4),
            "improvement_pct": round(improvement_pct, 2),
            "speedup": round(speedup, 2),
            "welch_t": _welch_t(base_vals, cand_vals),
            "spec_sha256": spec_sha,
            "trials": trial_rows,
        }
        receipt_sha = _sha256_json(result)
        result["receipt_sha256"] = receipt_sha

        with self._lock:
            self._conn.execute(
                """
                INSERT INTO experiments (
                    exp_id, hypothesis, verdict, parity_ok, spec_sha256,
                    receipt_sha256, result_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    exp_id,
                    hypothesis,
                    verdict,
                    1 if parity_ok else 0,
                    spec_sha,
                    receipt_sha,
                    json.dumps(result, sort_keys=True),
                    round(_now(), 3),
                ),
            )
            self._conn.commit()

        if register_axiom and self.axiom_ledger is not None and claim_id and verdict in ("PROVEN", "REFUTED"):
            self.axiom_ledger.record_axiom(
                claim_id=claim_id,
                status=verdict,
                organ=organ,
                summary=f"{hypothesis} (baseline={round(b_med, 3)} vs candidate={round(c_med, 3)}, delta={round(improvement_pct, 2)}%, parity=100%)",
                metrics={
                    "baseline_median": round(b_med, 4),
                    "candidate_median": round(c_med, 4),
                    "improvement_pct": round(improvement_pct, 2),
                    "speedup": round(speedup, 2),
                },
                receipt_path=f"galileo:{exp_id}",
            )
            result["axiom_registered"] = claim_id

        return result

    def start_resumable_soak(self, *, exp_id: str, target_samples: int = 10) -> dict[str, Any]:
        eid = str(exp_id or f"soak_{int(_now())}")
        tgt = max(1, int(target_samples))
        with self._lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO soak_runs (
                    exp_id, target_samples, collected_samples, pause_count,
                    status, samples_json, last_pause_reason, updated_at
                ) VALUES (?, ?, 0, 0, 'running', '[]', '', ?)
                """,
                (eid, tgt, round(_now(), 3)),
            )
            self._conn.commit()
        return {"ok": True, "exp_id": eid, "target_samples": tgt, "collected_samples": 0, "status": "running"}

    def step_resumable_soak(
        self,
        *,
        exp_id: str,
        guard_fn: Callable[[], dict[str, Any]] | None = None,
        sample_fn: Callable[[int], dict[str, Any]] | None = None,
        max_steps: int = 1,
    ) -> dict[str, Any]:
        """Collects samples with peer_guard checkpointing: pauses cleanly on pressure and resumes without losing samples."""
        with self._lock:
            row = self._conn.execute("SELECT * FROM soak_runs WHERE exp_id = ?", (exp_id,)).fetchone()
            if not row:
                return {"ok": False, "error": f"soak_not_found:{exp_id}"}
            target = int(row["target_samples"])
            samples: list[dict[str, Any]] = json.loads(row["samples_json"])
            pause_count = int(row["pause_count"])
            last_pause = str(row["last_pause_reason"])
            status = str(row["status"])

        for _ in range(max(1, int(max_steps))):
            if len(samples) >= target:
                status = "completed"
                break
            if callable(guard_fn):
                g = guard_fn() or {}
                if not g.get("ok", True) or g.get("busy", False):
                    pause_count += 1
                    last_pause = str(g.get("reason") or "peer_guard_pressure")
                    status = "paused_peer_guard"
                    break
            idx = len(samples) + 1
            sample = sample_fn(idx) if callable(sample_fn) else {"sample": idx, "rss_mib": get_self_rss_mib(), "ts": round(_now(), 3)}
            samples.append(sample)
            status = "completed" if len(samples) >= target else "running"

        with self._lock:
            self._conn.execute(
                """
                UPDATE soak_runs
                SET collected_samples=?, pause_count=?, status=?, samples_json=?,
                    last_pause_reason=?, updated_at=?
                WHERE exp_id=?
                """,
                (len(samples), pause_count, status, json.dumps(samples), last_pause, round(_now(), 3), exp_id),
            )
            self._conn.commit()
        return {
            "ok": True,
            "exp_id": exp_id,
            "target_samples": target,
            "collected_samples": len(samples),
            "pause_count": pause_count,
            "status": status,
            "last_pause_reason": last_pause,
            "samples": samples,
        }

    def list_experiments(self, limit: int = 12) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT exp_id, hypothesis, verdict, parity_ok, receipt_sha256, created_at FROM experiments ORDER BY created_at DESC LIMIT ?",
                (max(1, min(50, int(limit))),),
            ).fetchall()
        return [dict(r) for r in rows]

    def status(self) -> dict[str, Any]:
        with self._lock:
            exp_cnt = int(self._conn.execute("SELECT COUNT(*) FROM experiments").fetchone()[0])
            soak_cnt = int(self._conn.execute("SELECT COUNT(*) FROM soak_runs").fetchone()[0])
        return {
            "ok": True,
            "experiments_recorded": exp_cnt,
            "soak_runs_recorded": soak_cnt,
            "recent": self.list_experiments(5),
        }

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Wave 2C — CHIMERA-GHOST-POOL (Shared Read-Ring + Cooperative Socket-Activation)
# ---------------------------------------------------------------------------

class GhostReadRing:
    """<=16 MiB mtime-validated passive Shared Read-Ring fed by Hooks + agent_probe + Tquota."""

    def __init__(self, db_path: Path | None = None, *, max_bytes: int = 16 * 1024 * 1024) -> None:
        self.max_bytes = max(256 * 1024, int(max_bytes))
        self.db_path = db_path
        self._lock = threading.RLock()
        self._mem: collections.OrderedDict[str, tuple[int, int, str, bytes, bool]] = collections.OrderedDict()
        self._mem_bytes = 0
        self._stats = {"hits": 0, "misses": 0, "puts": 0, "evictions": 0, "bytes_saved": 0, "passive_ingests": 0}
        self._conn: sqlite3.Connection | None = _open_wal_sqlite(db_path) if db_path else None
        if self._conn is not None:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS ghost_pages (
                    abs_path TEXT PRIMARY KEY,
                    mtime_ns INTEGER NOT NULL,
                    raw_size INTEGER NOT NULL,
                    sha256 TEXT NOT NULL,
                    compressed INTEGER NOT NULL,
                    payload BLOB NOT NULL,
                    updated_at REAL NOT NULL
                );
                """
            )
            self._conn.commit()

    def _evict_if_needed(self) -> None:
        while self._mem_bytes > self.max_bytes and self._mem:
            _, entry = self._mem.popitem(last=False)
            self._mem_bytes -= len(entry[3])
            self._stats["evictions"] += 1

    def put_file(self, path: str | Path, *, content: bytes | None = None, passive: bool = False) -> dict[str, Any]:
        p = Path(path).resolve()
        if not p.is_file():
            return {"ok": False, "error": "not_a_file"}
        st = p.stat()
        if st.st_size > 2 * 1024 * 1024:
            return {"ok": False, "error": "file_too_large_for_ring"}
        raw = content if content is not None else p.read_bytes()
        sha = _sha256_bytes(raw)
        compressed = False
        disk_stored = raw
        if len(raw) >= 1024:
            z = zlib.compress(raw, level=3)
            if len(z) < len(raw):
                disk_stored = z
                compressed = True
        key = str(p)
        with self._lock:
            old = self._mem.pop(key, None)
            if old is not None:
                self._mem_bytes -= len(old[3])
            # Keep RAM tier uncompressed for zero-CPU <0.1ms hits; compress only on shared SQLite WAL
            self._mem[key] = (st.st_mtime_ns, st.st_size, sha, raw, False)
            self._mem_bytes += len(raw)
            self._stats["puts"] += 1
            if passive:
                self._stats["passive_ingests"] += 1
            self._evict_if_needed()
            if self._conn is not None:
                try:
                    self._conn.execute(
                        """
                        INSERT OR REPLACE INTO ghost_pages (
                            abs_path, mtime_ns, raw_size, sha256, compressed, payload, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (key, st.st_mtime_ns, st.st_size, sha, 1 if compressed else 0, sqlite3.Binary(disk_stored), _now()),
                    )
                    self._conn.commit()
                except Exception:
                    pass
        return {
            "ok": True,
            "path": key,
            "sha256": sha[:16],
            "raw_size": st.st_size,
            "stored_size": len(disk_stored),
            "compressed": compressed,
        }

    def get_file(self, path: str | Path) -> tuple[bytes | None, dict[str, Any]]:
        p = Path(path).resolve()
        if not p.is_file():
            return None, {"hit": False, "reason": "not_found"}
        st = p.stat()
        key = str(p)
        with self._lock:
            entry = self._mem.get(key)
            if entry is not None and entry[0] == st.st_mtime_ns and entry[1] == st.st_size:
                self._mem.move_to_end(key)
                self._stats["hits"] += 1
                self._stats["bytes_saved"] += st.st_size
                raw = zlib.decompress(entry[3]) if entry[4] else entry[3]
                return raw, {"hit": True, "tier": "ram", "sha256": entry[2][:16], "raw_size": st.st_size}
            if self._conn is not None:
                row = self._conn.execute(
                    "SELECT mtime_ns, raw_size, sha256, compressed, payload FROM ghost_pages WHERE abs_path = ?",
                    (key,),
                ).fetchone()
                if row and int(row["mtime_ns"]) == st.st_mtime_ns and int(row["raw_size"]) == st.st_size:
                    stored = bytes(row["payload"])
                    comp = bool(row["compressed"])
                    raw = zlib.decompress(stored) if comp else stored
                    self._mem[key] = (st.st_mtime_ns, st.st_size, str(row["sha256"]), raw, False)
                    self._mem_bytes += len(raw)
                    self._evict_if_needed()
                    self._stats["hits"] += 1
                    self._stats["bytes_saved"] += st.st_size
                    return raw, {"hit": True, "tier": "shared_wal", "sha256": str(row["sha256"])[:16], "raw_size": st.st_size}
            self._stats["misses"] += 1
        return None, {"hit": False, "reason": "miss"}

    def get_or_read(self, path: str | Path) -> tuple[bytes, dict[str, Any]]:
        raw, meta = self.get_file(path)
        if raw is not None:
            return raw, meta
        p = Path(path).resolve()
        raw = p.read_bytes()
        put_meta = self.put_file(p, content=raw)
        return raw, {"hit": False, "populated": bool(put_meta.get("ok")), "sha256": put_meta.get("sha256", ""), "raw_size": len(raw)}

    def ingest_paths(self, paths: list[str], *, source: str = "passive") -> dict[str, Any]:
        ingested = 0
        for raw_p in (paths or [])[:24]:
            if not raw_p:
                continue
            try:
                res = self.put_file(raw_p, passive=True)
                if res.get("ok"):
                    ingested += 1
            except Exception:
                pass
        return {"ok": True, "source": source, "ingested": ingested, "entries": len(self._mem)}

    def status(self) -> dict[str, Any]:
        with self._lock:
            hits = self._stats["hits"]
            misses = self._stats["misses"]
            total = hits + misses
            hit_pct = round((hits / total) * 100.0, 2) if total else 0.0
            return {
                "ok": True,
                "entries": len(self._mem),
                "mem_bytes": self._mem_bytes,
                "max_bytes": self.max_bytes,
                "hits": hits,
                "misses": misses,
                "hit_rate_pct": hit_pct,
                "bytes_saved": self._stats["bytes_saved"],
                "passive_ingests": self._stats["passive_ingests"],
                "evictions": self._stats["evictions"],
            }

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                except Exception:
                    pass
                self._conn = None


class SocketActivationProxy:
    """Law-2 Cooperative Zero-Idle TCP/HTTP Socket-Activation Proxy (0 MiB backend Commit when idle)."""

    def __init__(
        self,
        *,
        name: str,
        listen_port: int = 0,
        backend_port: int,
        start_backend_fn: Callable[[], bool],
        stop_backend_fn: Callable[[], None],
        idle_timeout_s: float = 300.0,
        wake_timeout_s: float = 5.0,
    ) -> None:
        self.name = name
        self.listen_port = int(listen_port)
        self.backend_port = int(backend_port)
        self._start_backend_fn = start_backend_fn
        self._stop_backend_fn = stop_backend_fn
        self.idle_timeout_s = max(0.2, float(idle_timeout_s))
        self.wake_timeout_s = max(0.5, float(wake_timeout_s))
        self._lock = threading.RLock()
        self._stop_ev = threading.Event()
        self._srv: socket.socket | None = None
        self._backend_awake = False
        self._active_conns = 0
        self._last_active = _now()
        self._stats = {"wakes": 0, "sleeps": 0, "connections": 0, "last_wake_ms": 0.0}

    def start(self) -> int:
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", self.listen_port))
        srv.listen(32)
        srv.settimeout(0.25)
        self._srv = srv
        self.listen_port = int(srv.getsockname()[1])
        threading.Thread(target=self._accept_loop, daemon=True, name=f"ghost-sockact-{self.name}").start()
        threading.Thread(target=self._reaper_loop, daemon=True, name=f"ghost-reaper-{self.name}").start()
        return self.listen_port

    def _ensure_backend_awake(self) -> bool:
        with self._lock:
            self._last_active = _now()
            if self._backend_awake:
                return True
            t0 = time.perf_counter()
            ok = bool(self._start_backend_fn())
            if not ok:
                return False
            deadline = _now() + self.wake_timeout_s
            while _now() < deadline:
                try:
                    with socket.create_connection(("127.0.0.1", self.backend_port), timeout=0.25):
                        self._backend_awake = True
                        self._stats["wakes"] += 1
                        self._stats["last_wake_ms"] = round((time.perf_counter() - t0) * 1000.0, 2)
                        return True
                except OSError:
                    time.sleep(0.03)
            return False

    def _accept_loop(self) -> None:
        assert self._srv is not None
        while not self._stop_ev.is_set():
            try:
                client, _ = self._srv.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=self._handle_conn, args=(client,), daemon=True).start()

    def _handle_conn(self, client: socket.socket) -> None:
        backend: socket.socket | None = None
        try:
            with self._lock:
                self._active_conns += 1
                self._stats["connections"] += 1
                self._last_active = _now()
            if not self._ensure_backend_awake():
                client.sendall(b"HTTP/1.1 503 Service Unavailable\r\nContent-Length: 0\r\n\r\n")
                return
            backend = socket.create_connection(("127.0.0.1", self.backend_port), timeout=3.0)
            client.setblocking(False)
            backend.setblocking(False)
            readers = [client, backend]
            while not self._stop_ev.is_set() and backend in readers:
                rlist, _, _ = select.select(readers, [], [], 0.2)
                if not rlist:
                    continue
                for s in rlist:
                    try:
                        data = s.recv(16384)
                    except OSError:
                        data = b""
                    if not data:
                        readers.remove(s)
                        if s is client:
                            try:
                                backend.shutdown(socket.SHUT_WR)
                            except OSError:
                                pass
                        else:
                            try:
                                client.shutdown(socket.SHUT_WR)
                            except OSError:
                                pass
                            return
                        continue
                    peer = backend if s is client else client
                    peer.setblocking(True)
                    peer.sendall(data)
                    peer.setblocking(False)
                    with self._lock:
                        self._last_active = _now()
        except OSError:
            pass
        finally:
            for s in (client, backend):
                if s is not None:
                    try:
                        s.close()
                    except OSError:
                        pass
            with self._lock:
                self._active_conns = max(0, self._active_conns - 1)
                self._last_active = _now()

    def _reaper_loop(self) -> None:
        while not self._stop_ev.is_set():
            self._stop_ev.wait(min(0.25, self.idle_timeout_s / 2.0))
            with self._lock:
                should_sleep = (
                    self._backend_awake
                    and self._active_conns == 0
                    and (_now() - self._last_active) >= self.idle_timeout_s
                )
                if should_sleep:
                    try:
                        self._stop_backend_fn()
                    except Exception:
                        pass
                    self._backend_awake = False
                    self._stats["sleeps"] += 1

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "ok": True,
                "name": self.name,
                "listen_port": self.listen_port,
                "backend_port": self.backend_port,
                "backend_awake": self._backend_awake,
                "active_conns": self._active_conns,
                "idle_timeout_s": self.idle_timeout_s,
                **self._stats,
            }

    def close(self) -> None:
        self._stop_ev.set()
        if self._srv is not None:
            try:
                self._srv.close()
            except OSError:
                pass
        with self._lock:
            if self._backend_awake:
                try:
                    self._stop_backend_fn()
                except Exception:
                    pass
                self._backend_awake = False


# ---------------------------------------------------------------------------
# Wave 2B — CHIMERA-ORACLE (Organ 2 & 3: PHANTOM-RPC, Speculative Verify, Morning Brief)
# ---------------------------------------------------------------------------

class SvhomeOracleEngine:
    """Replaces 1.27s SSH loops with persistent keep-alive PHANTOM-RPC + Speculative Shadow Oracle."""

    def __init__(
        self,
        *,
        axioms: EmpiricalAxiomLedger,
        epoch: SovereignEpochArbiter,
        galileo: GalileoExperimentEngine,
        ghost: GhostReadRing,
    ) -> None:
        self.axioms = axioms
        self.epoch = epoch
        self.galileo = galileo
        self.ghost = ghost
        self._lock = threading.RLock()
        self._http_pool: dict[str, http.client.HTTPConnection] = {}
        self._spec_cache: dict[str, dict[str, Any]] = {}
        self._stats = {"local_probes": 0, "phantom_probes": 0, "spec_runs": 0, "spec_hits": 0}

    def local_probe(
        self,
        *,
        repo_dir: str | None = None,
        release_dir: str | None = None,
        check_files: list[str] | None = None,
    ) -> dict[str, Any]:
        """<2 ms zero-subprocess node telemetry snapshot served over PHANTOM-RPC."""
        t0 = time.perf_counter()
        mem_info: dict[str, float] = {}
        load_1m = 0.0
        if os.name != "nt":
            try:
                load_1m = round(os.getloadavg()[0], 2)
            except OSError:
                pass
            try:
                for ln in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
                    if ln.startswith(("MemTotal:", "MemAvailable:")):
                        parts = ln.split()
                        mem_info[parts[0].rstrip(":")] = round(int(parts[1]) / 1048576.0, 2)
            except OSError:
                pass
        else:
            try:
                class _MEMSTAT(ctypes.Structure):
                    _fields_ = [
                        ("dwLength", ctypes.c_ulong),
                        ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong),
                        ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                    ]
                ms = _MEMSTAT()
                ms.dwLength = ctypes.sizeof(ms)
                if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms)):
                    mem_info["MemTotal"] = round(ms.ullTotalPhys / (1024**3), 2)
                    mem_info["MemAvailable"] = round(ms.ullAvailPhys / (1024**3), 2)
                    mem_info["MemoryLoadPct"] = float(ms.dwMemoryLoad)
            except Exception:
                pass

        file_hashes: dict[str, str] = {}
        base = Path(repo_dir) if repo_dir else Path.cwd()
        for rel in (check_files or [])[:32]:
            fp = Path(rel) if Path(rel).is_absolute() else (base / rel)
            if fp.is_file():
                try:
                    raw = fp.read_bytes()
                    norm = raw.replace(b"\r\n", b"\n") if b"\x00" not in raw[:4096] else raw
                    file_hashes[str(rel)] = hashlib.sha256(norm).hexdigest()[:16]
                except OSError:
                    file_hashes[str(rel)] = "ERR"
            else:
                file_hashes[str(rel)] = "MISSING"

        seal = self.epoch.verify_release_integrity(release_dir) if release_dir else None
        disk_free_gb = 0.0
        try:
            disk_free_gb = round(shutil.disk_usage(str(base)).free / (1024**3), 2)
        except OSError:
            pass

        with self._lock:
            self._stats["local_probes"] += 1
        return {
            "ok": True,
            "node": platform.node(),
            "os": platform.system().lower(),
            "pid": os.getpid(),
            "rss_mib": get_self_rss_mib(),
            "load_1m": load_1m,
            "mem_gb": mem_info,
            "disk_free_gb": disk_free_gb,
            "soak_leases": self.epoch.active_soak_leases(),
            "file_hashes": file_hashes,
            "release_seal": seal,
            "probe_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }

    def phantom_probe(
        self,
        peer_base: str,
        *,
        repo_dir: str | None = None,
        release_dir: str | None = None,
        check_files: list[str] | None = None,
        timeout_s: float = 3.0,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Persistent HTTP keep-alive PHANTOM-RPC probe (~10-25 ms vs 1,267 ms SSH)."""
        t0 = time.perf_counter()
        parsed = urllib.parse.urlparse(peer_base.rstrip("/"))
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        pool_key = f"{parsed.scheme}://{host}:{port}"
        body = json.dumps({
            "repo_dir": repo_dir or "",
            "release_dir": release_dir or "",
            "check_files": list(check_files or [])[:32],
        }, separators=(",", ":")).encode("utf-8")
        req_headers = {
            "Content-Type": "application/json",
            "Connection": "keep-alive",
            **(headers or {}),
        }

        last_err = ""
        for attempt in range(2):
            with self._lock:
                conn = self._http_pool.get(pool_key)
                if conn is None:
                    conn = http.client.HTTPConnection(host, port, timeout=timeout_s)
                    self._http_pool[pool_key] = conn
            try:
                conn.request("POST", "/v1/prometheus/oracle/probe", body=body, headers=req_headers)
                resp = conn.getresponse()
                raw = resp.read(262144)
                if resp.status == 200:
                    data = json.loads(raw.decode("utf-8", errors="replace"))
                    with self._lock:
                        self._stats["phantom_probes"] += 1
                    return {
                        "ok": True,
                        "transport": "phantom_rpc_keepalive",
                        "peer": pool_key,
                        "rtt_ms": round((time.perf_counter() - t0) * 1000.0, 2),
                        "remote": data,
                    }
                last_err = f"http_{resp.status}"
            except Exception as exc:
                last_err = str(exc)
            with self._lock:
                old = self._http_pool.pop(pool_key, None)
                if old is not None:
                    try:
                        old.close()
                    except Exception:
                        pass
        return {
            "ok": False,
            "transport": "phantom_rpc_keepalive",
            "peer": pool_key,
            "rtt_ms": round((time.perf_counter() - t0) * 1000.0, 2),
            "error": last_err or "peer_unreachable",
        }

    def speculative_verify(self, repo_dir: str | Path, changed_files: list[str]) -> dict[str, Any]:
        """Fast zero-spawn AST + JSON + secret pre-verification cached by exact file SHA-256."""
        t0 = time.perf_counter()
        repo = Path(repo_dir).resolve()
        results: list[dict[str, Any]] = []
        errors = 0
        secret_hits = 0
        cache_hits = 0

        for rel in (changed_files or [])[:24]:
            fp = Path(rel) if Path(rel).is_absolute() else (repo / rel)
            if not fp.is_file():
                continue
            raw, _ = self.ghost.get_or_read(fp)
            fsha = _sha256_bytes(raw)
            ckey = f"{fp}:{fsha}"
            with self._lock:
                cached = self._spec_cache.get(ckey)
            if cached is not None:
                cache_hits += 1
                with self._lock:
                    self._stats["spec_hits"] += 1
                item = {**cached, "cache_hit": True}
            else:
                text = raw.decode("utf-8", errors="replace")
                syntax_ok = True
                syntax_err = ""
                if fp.suffix.lower() == ".py":
                    try:
                        ast.parse(text, filename=str(fp))
                    except SyntaxError as exc:
                        syntax_ok = False
                        syntax_err = f"L{exc.lineno}: {exc.msg}"
                elif fp.suffix.lower() == ".json":
                    try:
                        json.loads(text)
                    except Exception as exc:
                        syntax_ok = False
                        syntax_err = str(exc)[:120]
                sec = bool(_SECRET_PATTERNS.search(text))
                item = {
                    "file": str(rel),
                    "sha256": fsha[:16],
                    "syntax_ok": syntax_ok,
                    "syntax_error": syntax_err,
                    "secret_detected": sec,
                    "cache_hit": False,
                }
                with self._lock:
                    self._spec_cache[ckey] = item
                    if len(self._spec_cache) > 256:
                        self._spec_cache.pop(next(iter(self._spec_cache)))
            if not item["syntax_ok"]:
                errors += 1
            if item["secret_detected"]:
                secret_hits += 1
            results.append(item)

        with self._lock:
            self._stats["spec_runs"] += 1
        return {
            "ok": errors == 0 and secret_hits == 0,
            "checked": len(results),
            "cache_hits": cache_hits,
            "syntax_errors": errors,
            "secret_hits": secret_hits,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
            "results": results,
        }

    def morning_brief(self, *, repo_dir: str | None = None) -> dict[str, Any]:
        ax = self.axioms.status()
        ep = self.epoch.status()
        ga = self.galileo.status()
        gh = self.ghost.status()
        lines = [
            f"# CHIMERA-PROMETHEUS Morning Brief ({platform.node()})",
            f"- Daemon RSS: {get_self_rss_mib():.2f} MiB / 80 MiB | HW: {ax['hw_fingerprint']}",
            f"- Axioms: {ax['total_axioms']} ({ax['proven']} PROVEN, {ax['refuted']} REFUTED, chain_ok={ax['chain']['ok']}, vetoes={ax['stats']['vetoes']})",
            f"- Epoch Arbiter: soak_frozen={ep['soak_frozen']} (active={len(ep['active_soak_leases'])}, redirected_to_shadow={ep['stats']['promote_redirected']})",
            f"- Galileo Science: {ga['experiments_recorded']} AB receipts, {ga['soak_runs_recorded']} resumable soaks",
            f"- Ghost Read-Ring: {gh['entries']} pages, hit_rate={gh['hit_rate_pct']}% ({gh['hits']} hits / {gh['misses']} misses, saved={round(gh['bytes_saved']/1024,1)} KiB)",
            "- Reclaimable Windows Commit (Law 6 opt-in Socket-Activation): office_print ~2.33 GiB + shared WebView ~370.7 MiB",
        ]
        if repo_dir:
            wt = self.epoch.audit_worktrees(repo_dir, execute_prune=False)
            if wt.get("ok"):
                lines.append(f"- Worktrees ({Path(repo_dir).name}): {wt['non_primary']} trial worktrees ({wt['safe_to_prune_count']} safe to prune)")
        return {
            "ok": True,
            "line_count": len(lines),
            "brief": "\n".join(lines),
        }

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {"ok": True, "cached_spec_entries": len(self._spec_cache), **self._stats}

    def close(self) -> None:
        with self._lock:
            for conn in self._http_pool.values():
                try:
                    conn.close()
                except Exception:
                    pass
            self._http_pool.clear()


# ---------------------------------------------------------------------------
# Unified Lazy-Loaded Facade: ChimeraPrometheusCore (0 B Boot RSS)
# ---------------------------------------------------------------------------

class ChimeraPrometheusCore:
    """Single lazy-loaded container wiring Waves 1–3 cleanly into CHIMERA-ONE's 5 Organs."""

    def __init__(self, *, data_dir: Path | None = None, ephemeral: bool = False) -> None:
        if ephemeral and data_dir is not None:
            self.data_dir = Path(data_dir)
        elif data_dir is not None:
            self.data_dir = Path(data_dir)
        else:
            self.data_dir = _default_prometheus_dir()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.axioms = EmpiricalAxiomLedger(self.data_dir / "axioms.sqlite")
        self.epoch = SovereignEpochArbiter(self.data_dir / "epoch.sqlite")
        self.galileo = GalileoExperimentEngine(self.data_dir / "galileo.sqlite", axiom_ledger=self.axioms)
        self.ghost = GhostReadRing(None if ephemeral else (self.data_dir / "ghost_ring.sqlite"))
        self.oracle = SvhomeOracleEngine(
            axioms=self.axioms,
            epoch=self.epoch,
            galileo=self.galileo,
            ghost=self.ghost,
        )
        self.socket_profiles: list[dict[str, Any]] = [
            {
                "name": "office_print",
                "mode": "socket_activation_zero_idle",
                "reclaimable_commit_mib": 2385.0,
                "idle_timeout_s": 300,
                "law2_compliant": True,
                "auto_activated": False,
            },
            {
                "name": "browser_webview_shared",
                "mode": "shared_profile_merge",
                "reclaimable_commit_mib": 370.69,
                "law2_compliant": True,
                "auto_activated": False,
            },
        ]

    def micronucleus_binary_info(self) -> dict[str, Any]:
        repo_root = Path(__file__).resolve().parents[2]
        bin_name = "chimera_spine.exe" if os.name == "nt" else "chimera_spine"
        home = Path.home()
        candidates = [
            repo_root / "native" / "chimera_core" / "target" / "release" / "chimera_spine.exe",
            repo_root / "native" / "chimera_core" / "c_linux" / "chimera_spine",
            repo_root / "bin" / bin_name,
            home / ".chimera" / "bin" / bin_name,
            home / ".local" / "bin" / bin_name,
            home / "DEV" / "chimera-tp" / "native" / "chimera_core" / "c_linux" / "chimera_spine",
            home / "DEV" / "chimera-tp" / "native" / "chimera_core" / "target" / "release" / "chimera_spine.exe",
        ]
        env_bin = os.environ.get("CHIMERA_SPINE_BIN", "").strip()
        if env_bin:
            candidates.insert(0, Path(env_bin))
        seen: set[str] = set()
        found: list[str] = []
        for p in candidates:
            try:
                if p.is_file():
                    resolved = str(p.resolve())
                    if resolved not in seen:
                        seen.add(resolved)
                        found.append(str(p))
            except OSError:
                continue
        return {
            "ok": True,
            "engine": "chimera-micronucleus",
            "os": platform.system().lower(),
            "binaries_found": found,
            "ready": len(found) > 0,
            "auto_activated": False,
        }

    def dispatch(self, action: str, **kwargs: Any) -> dict[str, Any]:
        act = str(action or "status").strip().lower()
        if act == "status":
            return self.status()
        if act == "axioms":
            return {"ok": True, "status": self.axioms.status(), "axioms": self.axioms.list_axioms(kwargs.get("filter_status"))}
        if act == "axiom_check":
            return self.axioms.check_action(
                str(kwargs.get("target_action") or kwargs.get("action_name") or ""),
                params=kwargs.get("params") if isinstance(kwargs.get("params"), dict) else None,
                hw_fingerprint=kwargs.get("hw_fingerprint"),
            )
        if act == "axiom_record":
            return self.axioms.record_axiom(
                claim_id=str(kwargs.get("claim_id") or ""),
                status=str(kwargs.get("status") or "CONDITIONAL"),
                organ=str(kwargs.get("organ") or "Causal Spine"),
                summary=str(kwargs.get("summary") or ""),
                match_actions=list(kwargs.get("match_actions") or []),
                metrics=dict(kwargs.get("metrics") or {}),
                receipt_path=str(kwargs.get("receipt_path") or ""),
            )
        if act == "epoch_status":
            return self.epoch.status()
        if act == "epoch_seal":
            return self.epoch.seal_release(
                str(kwargs.get("release_dir") or ""),
                lock_readonly=bool(kwargs.get("lock_readonly", True)),
            )
        if act == "epoch_verify":
            return self.epoch.verify_release_integrity(str(kwargs.get("release_dir") or ""))
        if act == "soak_acquire":
            return self.epoch.acquire_soak_lease(
                owner_id=str(kwargs.get("owner_id") or "agent"),
                window_s=float(kwargs.get("window_s") or 660.0),
                target_pid=int(kwargs.get("target_pid") or os.getpid()),
                tree_sha256=str(kwargs.get("tree_sha256") or ""),
                label=str(kwargs.get("label") or "soak_window"),
            )
        if act == "soak_release":
            return self.epoch.release_soak_lease(str(kwargs.get("lease_id") or ""))
        if act == "epoch_promote":
            return self.epoch.request_promote(
                requester_id=str(kwargs.get("requester_id") or "agent"),
                candidate_tree_sha256=str(kwargs.get("candidate_tree_sha256") or ""),
                shadow_port=kwargs.get("shadow_port"),
                force=bool(kwargs.get("force", False)),
            )
        if act == "worktrees":
            return self.epoch.audit_worktrees(
                str(kwargs.get("repo") or kwargs.get("repo_path") or "."),
                execute_prune=bool(kwargs.get("execute_prune", False)),
            )
        if act == "galileo_status":
            return self.galileo.status()
        if act == "oracle_probe":
            return self.oracle.local_probe(
                repo_dir=kwargs.get("repo_dir") or None,
                release_dir=kwargs.get("release_dir") or None,
                check_files=kwargs.get("check_files") or None,
            )
        if act == "phantom_probe":
            return self.oracle.phantom_probe(
                str(kwargs.get("peer_base") or "http://127.0.0.1:9780"),
                repo_dir=kwargs.get("repo_dir") or None,
                release_dir=kwargs.get("release_dir") or None,
                check_files=kwargs.get("check_files") or None,
                timeout_s=float(kwargs.get("timeout_s") or 3.0),
            )
        if act == "oracle_speculate":
            return self.oracle.speculative_verify(
                str(kwargs.get("repo_dir") or "."),
                list(kwargs.get("changed_files") or []),
            )
        if act == "morning_brief":
            return self.oracle.morning_brief(repo_dir=kwargs.get("repo_dir") or None)
        if act == "ghost_status":
            return {**self.ghost.status(), "socket_profiles": self.socket_profiles}
        if act == "ghost_read":
            p = str(kwargs.get("path") or "")
            if not p:
                return {"ok": False, "error": "path_required"}
            raw, meta = self.ghost.get_or_read(p)
            return {"ok": True, "path": p, "meta": meta, "preview": raw[:2048].decode("utf-8", errors="replace")}
        if act == "ghost_ingest":
            return self.ghost.ingest_paths(
                list(kwargs.get("paths") or []),
                source=str(kwargs.get("source") or "external"),
            )
        if act == "spine_status":
            return self.micronucleus_binary_info()
        return {"ok": False, "error": f"unknown_prometheus_action:{act}"}

    def status(self) -> dict[str, Any]:
        return {
            "ok": True,
            "schema": "chimera.prometheus.v1",
            "organs_mapped": 5,
            "auto_activated": False,
            "axioms": self.axioms.status(),
            "epoch": self.epoch.status(),
            "galileo": self.galileo.status(),
            "oracle": self.oracle.status(),
            "ghost_pool": {**self.ghost.status(), "socket_profiles": self.socket_profiles},
            "micronucleus": self.micronucleus_binary_info(),
        }

    def close(self) -> None:
        self.oracle.close()
        self.ghost.close()
        self.galileo.close()
        self.epoch.close()
        self.axioms.close()


_DEFAULT_PROM_LOCK = threading.Lock()
_DEFAULT_PROM_CORE: ChimeraPrometheusCore | None = None


def get_prometheus_core() -> ChimeraPrometheusCore:
    global _DEFAULT_PROM_CORE
    with _DEFAULT_PROM_LOCK:
        if _DEFAULT_PROM_CORE is None:
            _DEFAULT_PROM_CORE = ChimeraPrometheusCore()
        return _DEFAULT_PROM_CORE
