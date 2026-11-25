"""CHIMERA-HYPER v3.0 Autopilot: Contextual 24h Link-Weather UCB1 Bandit & Zero-Weight Guard."""

from __future__ import annotations

import ctypes
import hashlib
import json
import math
import os
import random
import socket
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .active_pipe import (
    ComputePlan,
    execute_operator,
    make_synthetic_logs,
    remote_active_query,
)
from .dna_vault import DnaVault
from .fabric import beam_send
from .gf256 import RLNCDecoder, RLNCEncoder, coeff_vector
from .hyper_wire import (
    HedgedRpcClient,
    HyperWireReceiver,
    HyperWireSender,
    ImmortalMultiPathSender,
)
from .impairment import ImpairedUdpBridge, transfer_tcp_cubic_over_udp
from .merkle_sync import merkle_beam_sync
from .native import WormholeChannel, cpu_caps, gf256_decode_matrix, gf256_encode_block, has_native
from .telepathy import (
    DomainDictionary,
    TelepathicStore,
    benchmark_compression,
    train_domain_dictionary,
)

GENOMES: dict[str, dict[str, Any]] = {
    "G0_BALANCED": {
        "label": "Balanced Zero-Bloat",
        "gen_k": 32,
        "max_inflight_gens": 24,
        "loss_hint": 0.00,
        "hedge_delay_ms": 15.0,
        "est_warp_loss": 0.02,
    },
    "G1_DUAL_RACE": {
        "label": "Dual-Stack Hedged Race",
        "gen_k": 32,
        "max_inflight_gens": 28,
        "loss_hint": 0.02,
        "hedge_delay_ms": 0.0,
        "est_warp_loss": 0.05,
    },
    "G2_LOSSY_ARMOR": {
        "label": "Lossy WAN Proactive GFNI Armor",
        "gen_k": 32,
        "max_inflight_gens": 32,
        "loss_hint": 0.06,
        "hedge_delay_ms": 0.0,
        "est_warp_loss": 0.08,
    },
    "G3_TURBO_BULK": {
        "label": "Turbo Deep Pipeline",
        "gen_k": 32,
        "max_inflight_gens": 36,
        "loss_hint": 0.01,
        "hedge_delay_ms": 25.0,
        "est_warp_loss": 0.03,
    },
    "G4_LOW_JITTER_V6": {
        "label": "Compact Gen-24 Fast Recovery",
        "gen_k": 24,
        "max_inflight_gens": 24,
        "loss_hint": 0.03,
        "hedge_delay_ms": 5.0,
        "est_warp_loss": 0.04,
    },
}

VALID_PROFILES = ("auto-darwin", "max-speed", "lossy-armor", "exotic-v05")
TIME_BUCKETS = ("NIGHT_CLEAN", "MORNING", "AFTERNOON", "PEAK_EVENING")


def time_bucket_for_hour(hour: int | None = None) -> str:
    h = datetime.now().astimezone().hour if hour is None else int(hour) % 24
    if h < 7:
        return "NIGHT_CLEAN"
    if h < 12:
        return "MORNING"
    if h < 19:
        return "AFTERNOON"
    return "PEAK_EVENING"


def _bucket_from_ts(ts_local: str) -> str:
    try:
        dt = datetime.strptime(ts_local[:19], "%Y-%m-%d %H:%M:%S")
        return time_bucket_for_hour(dt.hour)
    except Exception:
        return time_bucket_for_hour()


def get_zero_weight_status(budget_mb: float = 80.0) -> dict[str, Any]:
    """Read current process RSS & host free RAM using pure OS APIs (zero heavy deps)."""
    rss_mb = 0.0
    free_gb = 0.0
    total_gb = 0.0

    if os.name == "nt":
        try:
            class _PMC_EX(ctypes.Structure):
                _fields_ = [
                    ("cb", ctypes.c_uint32),
                    ("PageFaultCount", ctypes.c_uint32),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                    ("PrivateUsage", ctypes.c_size_t),
                ]

            class _MEMSTAT(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_uint32),
                    ("dwMemoryLoad", ctypes.c_uint32),
                    ("ullTotalPhys", ctypes.c_uint64),
                    ("ullAvailPhys", ctypes.c_uint64),
                    ("ullTotalPageFile", ctypes.c_uint64),
                    ("ullAvailPageFile", ctypes.c_uint64),
                    ("ullTotalVirtual", ctypes.c_uint64),
                    ("ullAvailVirtual", ctypes.c_uint64),
                    ("ullAvailExtendedVirtual", ctypes.c_uint64),
                ]

            k32 = ctypes.windll.kernel32
            k32.GetCurrentProcess.restype = ctypes.c_void_p
            pmc = _PMC_EX()
            pmc.cb = ctypes.sizeof(pmc)
            hproc = k32.GetCurrentProcess()
            get_pmi = getattr(k32, "K32GetProcessMemoryInfo", None)
            if get_pmi is None:
                get_pmi = ctypes.windll.psapi.GetProcessMemoryInfo
            get_pmi.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32]
            get_pmi.restype = ctypes.c_int
            if get_pmi(hproc, ctypes.byref(pmc), pmc.cb):
                rss_mb = pmc.WorkingSetSize / (1024.0 * 1024.0)
            ms = _MEMSTAT()
            ms.dwLength = ctypes.sizeof(ms)
            k32.GlobalMemoryStatusEx.argtypes = [ctypes.c_void_p]
            k32.GlobalMemoryStatusEx.restype = ctypes.c_int
            if k32.GlobalMemoryStatusEx(ctypes.byref(ms)):
                total_gb = ms.ullTotalPhys / (1024.0 ** 3)
                free_gb = ms.ullAvailPhys / (1024.0 ** 3)
        except Exception:
            pass
    else:
        try:
            for ln in Path("/proc/self/status").read_text(encoding="utf-8").splitlines():
                if ln.startswith("VmRSS:"):
                    kb = float(ln.split()[1])
                    rss_mb = kb / 1024.0
                    break
            for ln in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
                if ln.startswith("MemTotal:"):
                    total_gb = float(ln.split()[1]) / (1024.0 * 1024.0)
                elif ln.startswith("MemAvailable:"):
                    free_gb = float(ln.split()[1]) / (1024.0 * 1024.0)
        except Exception:
            pass

    return {
        "daemon_ram_mb": round(rss_mb, 2),
        "host_free_ram_gb": round(free_gb, 2),
        "host_total_ram_gb": round(total_gb, 2),
        "cpu_threads": os.cpu_count() or 1,
        "ram_budget_mb": budget_mb,
        "zero_weight_ok": bool(rss_mb <= budget_mb),
    }


def default_ops_dir() -> Path:
    return Path.home() / ".chimera_ops"


@dataclass
class OpsConfig:
    node_name: str = ""
    role: str = "controller"
    dashboard_bind: str = "127.0.0.1:9780"
    beam_port: int = 9700
    rpc_v4_port: int = 9702
    rpc_v6_port: int = 9703
    query_port: int = 9704
    warp_port: int = 9705
    immortal_v4_port: int = 9706
    immortal_v6_port: int = 9707
    peer_name: str = ""
    peer_ipv4: str = ""
    peer_ipv6: str = ""
    peer_beam_port: int = 9700
    peer_rpc_v4_port: int = 9702
    peer_rpc_v6_port: int = 9703
    peer_query_port: int = 9704
    peer_immortal_v4_port: int = 9706
    peer_immortal_v6_port: int = 9707
    peer_dashboard_port: int = 9780
    active_profile: str = "auto-darwin"
    daily_time: str = "08:00"
    watched_query_file: str = "@synthetic"
    allowed_query_roots: list[str] = field(default_factory=list)
    nat_punch_port: int = 9708
    edge_proxy_port: int = -1
    edge_targets: dict[str, dict[str, Any]] = field(
        default_factory=lambda: {
            "chimera": {
                "url": "http://127.0.0.1:9780",
                "prefetch": ["/api/status", "/api/health"],
                "label": "CHIMERA Cockpit",
            },
            "radar": {
                "url": "http://127.0.0.1:8787",
                "prefetch": [],
                "label": "Radar Dashboard",
            },
            "tqouta": {
                "url": "http://127.0.0.1:12504",
                "prefetch": [],
                "label": "Tqouta Admin",
            },
        }
    )
    search_roots: list[str] = field(default_factory=list)
    sentinel_interval_s: int = 300
    sentinel_webhook_url: str = ""
    backup_targets: list[str] = field(default_factory=list)
    phantom_enabled: bool = False
    phantom_fallback_port: int = 9710
    phantom_ssh_port: int = 2222
    phantom_http_port: int = 9789
    phantom_allowed_ports: list[int] = field(default_factory=lambda: [22, 8787, 9780, 12504])
    drop_ttl_s: int = 600

    def __post_init__(self) -> None:
        if not self.node_name:
            self.node_name = socket.gethostname()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OpsConfig":
        allowed = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in allowed}
        return cls(**filtered)

    def save(self, ops_dir: Path | None = None) -> Path:
        base = Path(ops_dir) if ops_dir else default_ops_dir()
        base.mkdir(parents=True, exist_ok=True)
        target = base / "config.json"
        tmp = base / "config.json.tmp"
        tmp.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, target)
        return target

    @classmethod
    def load(cls, ops_dir: Path | None = None) -> "OpsConfig":
        base = Path(ops_dir) if ops_dir else default_ops_dir()
        target = base / "config.json"
        if not target.exists():
            cfg = cls()
            return cfg
        return cls.from_dict(json.loads(target.read_text(encoding="utf-8")))


class TelemetryStore:
    """Thread-safe SQLite store for telemetry, Contextual 24h Link-Weather & UCB1 genomes."""

    def __init__(self, db_path: Path | None = None) -> None:
        base = default_ops_dir()
        base.mkdir(parents=True, exist_ok=True)
        self.db_path = Path(db_path) if db_path else (base / "telemetry.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            cur = self._conn.cursor()
            cur.executescript(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts_utc TEXT NOT NULL,
                    ts_local TEXT NOT NULL,
                    trigger TEXT NOT NULL,
                    profile TEXT NOT NULL,
                    genome_id TEXT NOT NULL,
                    health_score INTEGER NOT NULL,
                    gfni_speedup REAL NOT NULL,
                    wormhole_gbps REAL NOT NULL,
                    wan_5pct_speedup REAL NOT NULL,
                    peer_reachable INTEGER NOT NULL,
                    peer_rtt_ms REAL NOT NULL,
                    peer_hedged_p99_ms REAL NOT NULL,
                    peer_single_p99_ms REAL NOT NULL,
                    beam_speedup REAL NOT NULL,
                    beam_saved_pct REAL NOT NULL,
                    query_speedup REAL NOT NULL,
                    query_saved_pct REAL NOT NULL,
                    anomaly_flags TEXT NOT NULL,
                    summary_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS genomes (
                    genome_id TEXT PRIMARY KEY,
                    pulls INTEGER NOT NULL DEFAULT 0,
                    total_reward REAL NOT NULL DEFAULT 0.0,
                    avg_reward REAL NOT NULL DEFAULT 0.0,
                    last_used TEXT NOT NULL DEFAULT '',
                    params_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS context_genomes (
                    bucket TEXT NOT NULL,
                    genome_id TEXT NOT NULL,
                    pulls INTEGER NOT NULL DEFAULT 0,
                    total_reward REAL NOT NULL DEFAULT 0.0,
                    avg_reward REAL NOT NULL DEFAULT 0.0,
                    last_used TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (bucket, genome_id)
                );
                CREATE TABLE IF NOT EXISTS link_weather (
                    bucket TEXT PRIMARY KEY,
                    samples INTEGER NOT NULL DEFAULT 0,
                    ema_rtt_ms REAL NOT NULL DEFAULT 0.0,
                    ema_wan_speedup REAL NOT NULL DEFAULT 0.0,
                    ema_beam_speedup REAL NOT NULL DEFAULT 0.0,
                    ema_query_speedup REAL NOT NULL DEFAULT 0.0,
                    best_genome TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts_local TEXT NOT NULL,
                    level TEXT NOT NULL,
                    category TEXT NOT NULL,
                    message TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS cluster_reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    node_name TEXT NOT NULL,
                    role TEXT NOT NULL,
                    version TEXT NOT NULL,
                    ts_utc TEXT NOT NULL,
                    ts_local TEXT NOT NULL,
                    health_score INTEGER NOT NULL,
                    daemon_ram_mb REAL NOT NULL,
                    wan_5pct_speedup REAL NOT NULL,
                    beam_speedup REAL NOT NULL,
                    query_speedup REAL NOT NULL,
                    query_saved_pct REAL NOT NULL,
                    merkle_saved_pct REAL NOT NULL,
                    immortal_ok INTEGER NOT NULL,
                    summary_json TEXT NOT NULL
                );
                """
            )
            for gid, params in GENOMES.items():
                cur.execute(
                    """
                    INSERT INTO genomes (genome_id, pulls, total_reward, avg_reward, last_used, params_json)
                    VALUES (?, 0, 0.0, 0.0, '', ?)
                    ON CONFLICT(genome_id) DO UPDATE SET params_json = excluded.params_json
                    """,
                    (gid, json.dumps(params)),
                )
                for b in TIME_BUCKETS:
                    cur.execute(
                        """
                        INSERT INTO context_genomes (bucket, genome_id, pulls, total_reward, avg_reward, last_used)
                        VALUES (?, ?, 0, 0.0, 0.0, '')
                        ON CONFLICT(bucket, genome_id) DO NOTHING
                        """,
                        (b, gid),
                    )
            for b in TIME_BUCKETS:
                cur.execute(
                    """
                    INSERT INTO link_weather (bucket, samples, ema_rtt_ms, ema_wan_speedup, ema_beam_speedup, ema_query_speedup, best_genome, updated_at)
                    VALUES (?, 0, 0.0, 0.0, 0.0, 0.0, '', '')
                    ON CONFLICT(bucket) DO NOTHING
                    """,
                    (b,),
                )
            self._conn.commit()

    def select_genome(self, profile: str, hour: int | None = None) -> tuple[str, dict[str, Any]]:
        if profile == "max-speed":
            return "G3_TURBO_BULK", dict(GENOMES["G3_TURBO_BULK"])
        if profile == "lossy-armor":
            return "G2_LOSSY_ARMOR", dict(GENOMES["G2_LOSSY_ARMOR"])
        if profile == "exotic-v05":
            return "G0_BALANCED", dict(GENOMES["G0_BALANCED"])

        bucket = time_bucket_for_hour(hour)
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT g.genome_id, g.pulls AS g_pulls, g.avg_reward AS g_avg,
                       COALESCE(c.pulls, 0) AS c_pulls, COALESCE(c.avg_reward, 0.0) AS c_avg
                FROM genomes g
                LEFT JOIN context_genomes c
                  ON c.genome_id = g.genome_id AND c.bucket = ?
                ORDER BY g.genome_id
                """,
                (bucket,),
            ).fetchall()

        # Phase 1: global cold-start exploration covers all 5 genomes first
        for r in rows:
            if int(r["g_pulls"]) == 0:
                gid = str(r["genome_id"])
                return gid, dict(GENOMES[gid])

        ctx_total = sum(int(r["c_pulls"]) for r in rows)
        global_total = sum(int(r["g_pulls"]) for r in rows)
        best_gid = "G0_BALANCED"
        best_score = -1.0

        # If this time bucket has not been sampled yet, blend cleanly from global empirical posterior
        if ctx_total == 0:
            for r in rows:
                gid = str(r["genome_id"])
                pulls = max(1, int(r["g_pulls"]))
                avg_r = float(r["g_avg"])
                ucb = avg_r + 1.2 * math.sqrt(math.log(max(2, global_total)) / pulls)
                if ucb > best_score:
                    best_score = ucb
                    best_gid = gid
            return best_gid, dict(GENOMES[best_gid])

        # Contextual UCB1 within active time-of-day weather bucket + global prior
        for r in rows:
            gid = str(r["genome_id"])
            c_pulls = int(r["c_pulls"])
            g_pulls = max(1, int(r["g_pulls"]))
            c_avg = float(r["c_avg"])
            g_avg = float(r["g_avg"])
            if c_pulls == 0:
                prior = g_avg + 0.65 * math.sqrt(math.log(max(2, ctx_total)) / 1.0)
                score = prior
            else:
                blended = 0.75 * c_avg + 0.25 * g_avg
                score = blended + 1.2 * math.sqrt(math.log(max(2, ctx_total + 1)) / c_pulls)
            if score > best_score:
                best_score = score
                best_gid = gid
        return best_gid, dict(GENOMES[best_gid])

    def log_event(self, level: str, category: str, message: str) -> None:
        ts_local = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
        with self._lock:
            self._conn.execute(
                "INSERT INTO events (ts_local, level, category, message) VALUES (?, ?, ?, ?)",
                (ts_local, level, category, message),
            )
            self._conn.commit()

    def record_run(self, summary: dict[str, Any], genome_id: str, reward: float) -> int:
        bucket = str(summary.get("time_bucket") or _bucket_from_ts(summary["ts_local"]))
        wan_sp = float(summary["local"]["wan_5pct_speedup"])
        peer = summary.get("peer", {})
        peer_ok = bool(peer.get("reachable"))
        rtt_ms = float(peer.get("rtt_p50_ms", 0.0)) if peer_ok else 0.0
        beam_sp = float(peer.get("beam_speedup", 0.0)) if peer_ok else 0.0
        query_sp = float(peer.get("query_speedup", 0.0)) if peer_ok else 0.0

        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                INSERT INTO runs (
                    ts_utc, ts_local, trigger, profile, genome_id, health_score,
                    gfni_speedup, wormhole_gbps, wan_5pct_speedup,
                    peer_reachable, peer_rtt_ms, peer_hedged_p99_ms, peer_single_p99_ms,
                    beam_speedup, beam_saved_pct, query_speedup, query_saved_pct,
                    anomaly_flags, summary_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    summary["ts_utc"],
                    summary["ts_local"],
                    summary["trigger"],
                    summary["profile"],
                    genome_id,
                    int(summary["health_score"]),
                    float(summary["local"]["gfni_speedup"]),
                    float(summary["local"]["wormhole_gbps"]),
                    wan_sp,
                    1 if peer_ok else 0,
                    float(peer.get("rtt_p50_ms", 0.0)),
                    float(peer.get("hedged_p99_ms", 0.0)),
                    float(peer.get("single_p99_ms", 0.0)),
                    float(peer.get("beam_speedup", 0.0)),
                    float(peer.get("beam_saved_pct", 0.0)),
                    float(peer.get("query_speedup", 0.0)),
                    float(peer.get("query_saved_pct", 0.0)),
                    json.dumps(summary["anomalies"], ensure_ascii=False),
                    json.dumps(summary, ensure_ascii=False),
                ),
            )
            run_id = int(cur.lastrowid or 0)

            row = cur.execute(
                "SELECT pulls, total_reward FROM genomes WHERE genome_id = ?",
                (genome_id,),
            ).fetchone()
            if row is not None:
                new_pulls = int(row["pulls"]) + 1
                new_total = float(row["total_reward"]) + float(reward)
                cur.execute(
                    """
                    UPDATE genomes SET pulls = ?, total_reward = ?, avg_reward = ?, last_used = ?
                    WHERE genome_id = ?
                    """,
                    (new_pulls, new_total, new_total / new_pulls, summary["ts_local"], genome_id),
                )

            crow = cur.execute(
                "SELECT pulls, total_reward FROM context_genomes WHERE bucket = ? AND genome_id = ?",
                (bucket, genome_id),
            ).fetchone()
            if crow is not None:
                c_pulls = int(crow["pulls"]) + 1
                c_total = float(crow["total_reward"]) + float(reward)
                cur.execute(
                    """
                    UPDATE context_genomes SET pulls = ?, total_reward = ?, avg_reward = ?, last_used = ?
                    WHERE bucket = ? AND genome_id = ?
                    """,
                    (c_pulls, c_total, c_total / c_pulls, summary["ts_local"], bucket, genome_id),
                )

            best_row = cur.execute(
                """
                SELECT genome_id FROM context_genomes
                WHERE bucket = ? AND pulls > 0
                ORDER BY avg_reward DESC, pulls DESC LIMIT 1
                """,
                (bucket,),
            ).fetchone()
            best_g = str(best_row["genome_id"]) if best_row else genome_id

            wrow = cur.execute("SELECT * FROM link_weather WHERE bucket = ?", (bucket,)).fetchone()
            if wrow is not None:
                samples = int(wrow["samples"]) + 1
                alpha = 0.3 if int(wrow["samples"]) > 0 else 1.0
                prev_wan = float(wrow["ema_wan_speedup"])
                ema_wan = (1.0 - alpha) * prev_wan + alpha * wan_sp
                ema_rtt = float(wrow["ema_rtt_ms"])
                ema_beam = float(wrow["ema_beam_speedup"])
                ema_query = float(wrow["ema_query_speedup"])
                if peer_ok:
                    a_p = 0.3 if ema_beam > 0 or ema_rtt > 0 else 1.0
                    ema_rtt = (1.0 - a_p) * ema_rtt + a_p * rtt_ms
                    ema_beam = (1.0 - a_p) * ema_beam + a_p * beam_sp
                    ema_query = (1.0 - a_p) * ema_query + a_p * query_sp
                cur.execute(
                    """
                    UPDATE link_weather
                    SET samples = ?, ema_rtt_ms = ?, ema_wan_speedup = ?,
                        ema_beam_speedup = ?, ema_query_speedup = ?,
                        best_genome = ?, updated_at = ?
                    WHERE bucket = ?
                    """,
                    (
                        samples,
                        round(ema_rtt, 2),
                        round(ema_wan, 2),
                        round(ema_beam, 2),
                        round(ema_query, 2),
                        best_g,
                        summary["ts_local"],
                        bucket,
                    ),
                )

            self._conn.commit()
            return run_id

    def record_cluster_report(self, summary: dict[str, Any]) -> int:
        node_name = str(summary.get("node_name") or "unknown")
        role = str(summary.get("role") or "node")
        version = str(summary.get("version") or "3.0.0")
        ts_utc = str(summary.get("ts_utc") or "")
        ts_local = str(summary.get("ts_local") or "")
        health_score = int(summary.get("health_score", 0))
        zw = summary.get("zero_weight", {}) or {}
        daemon_ram_mb = float(zw.get("daemon_ram_mb", 0.0))
        loc = summary.get("local", {}) or {}
        wan_sp = float(loc.get("wan_5pct_speedup", 0.0))
        peer = summary.get("peer", {}) or {}
        beam_sp = float(peer.get("beam_speedup", 0.0)) if peer.get("reachable") else 0.0
        query_sp = float(peer.get("query_speedup", 0.0)) if peer.get("reachable") else 0.0
        query_saved = float(peer.get("query_saved_pct", 0.0)) if peer.get("reachable") else 0.0
        merkle = peer.get("merkle", {}) or {}
        merkle_saved = float(merkle.get("total_reduction_pct", 0.0)) if peer.get("reachable") else 0.0
        immortal_ok = 1 if (peer.get("reachable") and peer.get("immortal_ok")) else 0

        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                INSERT INTO cluster_reports (
                    node_name, role, version, ts_utc, ts_local, health_score,
                    daemon_ram_mb, wan_5pct_speedup, beam_speedup, query_speedup,
                    query_saved_pct, merkle_saved_pct, immortal_ok, summary_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    node_name,
                    role,
                    version,
                    ts_utc,
                    ts_local,
                    health_score,
                    daemon_ram_mb,
                    wan_sp,
                    beam_sp,
                    query_sp,
                    query_saved,
                    merkle_saved,
                    immortal_ok,
                    json.dumps(summary, ensure_ascii=False),
                ),
            )
            rid = int(cur.lastrowid or 0)
            self._conn.commit()
            return rid

    def get_cluster_overview(self, limit: int = 30) -> dict[str, Any]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM cluster_reports ORDER BY id DESC LIMIT ?", (limit * 4,)
            ).fetchall()

        latest_by_node: dict[str, dict[str, Any]] = {}
        latest_cross_host: dict[str, Any] | None = None

        for r in rows:
            nname = str(r["node_name"])
            try:
                parsed = json.loads(r["summary_json"])
            except Exception:
                parsed = {}
            if latest_cross_host is None and (parsed.get("peer", {}) or {}).get("reachable"):
                latest_cross_host = parsed
            if nname not in latest_by_node:
                loc = parsed.get("local", {}) or {}
                peer = parsed.get("peer", {}) or {}
                zw = parsed.get("zero_weight", {}) or {}
                latest_by_node[nname] = {
                    "id": int(r["id"]),
                    "node_name": nname,
                    "role": str(r["role"]),
                    "version": str(r["version"]),
                    "ts_utc": str(r["ts_utc"]),
                    "ts_local": str(r["ts_local"]),
                    "health_score": int(r["health_score"]),
                    "daemon_ram_mb": float(r["daemon_ram_mb"]),
                    "host_free_ram_gb": float(zw.get("host_free_ram_gb", 0.0)),
                    "host_total_ram_gb": float(zw.get("host_total_ram_gb", 0.0)),
                    "hardware": loc.get("cpu_caps", {}),
                    "gfni_speedup": float(loc.get("gfni_speedup", 0.0)),
                    "wormhole_gbps": float(loc.get("wormhole_gbps", 0.0)),
                    "wan_5pct_speedup": float(r["wan_5pct_speedup"]),
                    "beam_speedup": float(r["beam_speedup"]),
                    "query_speedup": float(r["query_speedup"]),
                    "query_saved_pct": float(r["query_saved_pct"]),
                    "merkle_saved_pct": float(r["merkle_saved_pct"]),
                    "immortal_ok": bool(r["immortal_ok"]),
                    "genome_id": str(parsed.get("genome_id", "")),
                    "trigger": str(parsed.get("trigger", "")),
                    "anomalies": list(parsed.get("anomalies", [])),
                    "peer_reachable": bool(peer.get("reachable")),
                }

        nodes = sorted(
            latest_by_node.values(),
            key=lambda x: (0 if x["role"] == "server" else 1, x["node_name"]),
        )

        # Fallback: also inspect local runs table if cluster_reports has no cross-host entry yet
        if latest_cross_host is None:
            with self._lock:
                rrow = self._conn.execute(
                    "SELECT summary_json FROM runs WHERE peer_reachable = 1 ORDER BY id DESC LIMIT 1"
                ).fetchone()
            if rrow is not None:
                try:
                    latest_cross_host = json.loads(rrow["summary_json"])
                except Exception:
                    latest_cross_host = None

        avg_health = (
            round(sum(n["health_score"] for n in nodes) / len(nodes), 1) if nodes else 0.0
        )
        all_zw_ok = all(n["daemon_ram_mb"] <= 80.0 for n in nodes) if nodes else True
        cross_ok = bool(
            latest_cross_host
            and (latest_cross_host.get("peer", {}) or {}).get("beam_ok")
            and (latest_cross_host.get("peer", {}) or {}).get("query_ok")
        )
        if not nodes:
            grade = "PENDING"
        elif avg_health >= 95.0 and all_zw_ok and (cross_ok or len(nodes) == 1):
            grade = "A+"
        elif avg_health >= 85.0:
            grade = "A"
        elif avg_health >= 70.0:
            grade = "B"
        else:
            grade = "WARN"

        highlights: list[str] = []
        if nodes:
            highlights.append(
                f"{len(nodes)} node báo cáo | Sức khỏe TB {avg_health}/100 | Zero-Weight {'ĐẠT' if all_zw_ok else 'CẦN XEM'}"
            )
        if latest_cross_host:
            pr = latest_cross_host.get("peer", {}) or {}
            mk = pr.get("merkle", {}) or {}
            highlights.append(
                f"Cross-Host ({latest_cross_host.get('node_name')} ↔ {pr.get('peer_name')}): "
                f"Query -{pr.get('query_saved_pct', 0)}% ({pr.get('query_speedup', 0)}x), "
                f"Beam -{pr.get('beam_saved_pct', 0)}% ({pr.get('beam_speedup', 0)}x)"
                + (f", Merkle -{mk.get('total_reduction_pct', 0)}%" if mk.get("verified_root_match") else "")
                + (", Immortal 0-reconnect OK" if pr.get("immortal_ok") else "")
            )

        return {
            "total_ingested": len(rows),
            "nodes": nodes,
            "latest_cross_host": latest_cross_host,
            "evaluation_verdict": {
                "grade": grade,
                "avg_health_score": avg_health,
                "zero_weight_ok": all_zw_ok,
                "cross_host_verified": cross_ok,
                "highlights": highlights,
            },
        }

    def has_daily_run_today(self) -> bool:
        today_prefix = datetime.now().astimezone().strftime("%Y-%m-%d")
        with self._lock:
            row = self._conn.execute(
                """
                SELECT COUNT(*) AS c FROM runs
                WHERE ts_local LIKE ? AND trigger IN ('daily', 'daemon_daily')
                """,
                (f"{today_prefix}%",),
            ).fetchone()
        return bool(row and int(row["c"]) > 0)

    def get_dashboard_state(self, limit: int = 30) -> dict[str, Any]:
        with self._lock:
            run_rows = self._conn.execute(
                "SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
            genome_rows = self._conn.execute(
                "SELECT * FROM genomes ORDER BY avg_reward DESC, pulls DESC, genome_id ASC"
            ).fetchall()
            event_rows = self._conn.execute(
                "SELECT * FROM events ORDER BY id DESC LIMIT 25"
            ).fetchall()
            weather_rows = self._conn.execute(
                "SELECT * FROM link_weather"
            ).fetchall()

        history: list[dict[str, Any]] = []
        for r in reversed(run_rows):
            history.append(
                {
                    "id": int(r["id"]),
                    "ts_local": r["ts_local"],
                    "trigger": r["trigger"],
                    "profile": r["profile"],
                    "genome_id": r["genome_id"],
                    "health_score": int(r["health_score"]),
                    "gfni_speedup": float(r["gfni_speedup"]),
                    "wormhole_gbps": float(r["wormhole_gbps"]),
                    "wan_5pct_speedup": float(r["wan_5pct_speedup"]),
                    "peer_reachable": bool(r["peer_reachable"]),
                    "peer_rtt_ms": float(r["peer_rtt_ms"]),
                    "peer_hedged_p99_ms": float(r["peer_hedged_p99_ms"]),
                    "peer_single_p99_ms": float(r["peer_single_p99_ms"]),
                    "beam_speedup": float(r["beam_speedup"]),
                    "beam_saved_pct": float(r["beam_saved_pct"]),
                    "query_speedup": float(r["query_speedup"]),
                    "query_saved_pct": float(r["query_saved_pct"]),
                    "anomalies": json.loads(r["anomaly_flags"]),
                }
            )

        latest_full = json.loads(run_rows[0]["summary_json"]) if run_rows else None
        recent_7 = history[-7:]
        avg_7d: dict[str, float] = {}
        if recent_7:
            for key in (
                "health_score",
                "gfni_speedup",
                "wormhole_gbps",
                "wan_5pct_speedup",
                "peer_rtt_ms",
                "beam_speedup",
                "query_speedup",
            ):
                avg_7d[key] = round(sum(float(x[key]) for x in recent_7) / len(recent_7), 2)

        genomes = [
            {
                "genome_id": g["genome_id"],
                "pulls": int(g["pulls"]),
                "total_reward": round(float(g["total_reward"]), 2),
                "avg_reward": round(float(g["avg_reward"]), 3),
                "last_used": g["last_used"],
                "params": json.loads(g["params_json"]),
            }
            for g in genome_rows
        ]
        events = [
            {
                "id": int(e["id"]),
                "ts_local": e["ts_local"],
                "level": e["level"],
                "category": e["category"],
                "message": e["message"],
            }
            for e in event_rows
        ]

        weather_map = {str(w["bucket"]): dict(w) for w in weather_rows}
        link_weather = [
            {
                "bucket": b,
                "samples": int(weather_map.get(b, {}).get("samples", 0)),
                "ema_rtt_ms": float(weather_map.get(b, {}).get("ema_rtt_ms", 0.0)),
                "ema_wan_speedup": float(weather_map.get(b, {}).get("ema_wan_speedup", 0.0)),
                "ema_beam_speedup": float(weather_map.get(b, {}).get("ema_beam_speedup", 0.0)),
                "ema_query_speedup": float(weather_map.get(b, {}).get("ema_query_speedup", 0.0)),
                "best_genome": str(weather_map.get(b, {}).get("best_genome", "")),
                "updated_at": str(weather_map.get(b, {}).get("updated_at", "")),
            }
            for b in TIME_BUCKETS
        ]
        sampled = [w for w in link_weather if w["samples"] > 0]
        if sampled:
            best_w = max(
                sampled,
                key=lambda w: w["ema_wan_speedup"] + w["ema_beam_speedup"] * 4.0 - w["ema_rtt_ms"] * 0.05,
            )
            recommended_window = best_w["bucket"]
        else:
            recommended_window = "NIGHT_CLEAN"

        return {
            "total_runs": len(history),
            "latest": latest_full,
            "history": history,
            "avg_7d": avg_7d,
            "genomes": genomes,
            "events": events,
            "active_bucket": time_bucket_for_hour(),
            "link_weather": link_weather,
            "recommended_sync_window": recommended_window,
        }

    def close(self) -> None:
        with self._lock:
            self._conn.close()


def _http_get_json(url: str, timeout_s: float = 4.0) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout_s) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _http_post_json(url: str, obj: dict[str, Any], timeout_s: float = 10.0) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        data=json.dumps(obj, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _http_post_bytes(url: str, data: bytes, timeout_s: float = 20.0) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/octet-stream"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _build_incremental_sample(size_bytes: int, version_seed: int) -> bytes:
    """Create deterministic 1 MiB corpus where >95% chunks match across versions."""
    unit_parts = [
        f"REC-{i:04d}|MOD={i%32}|PAY={(i*2654435761 & 0xFFFFFFFF):08x}|DATA=CHIMERA_VAULT_STABLE_BLOCK\n".encode(
            "ascii"
        )
        for i in range(600)
    ]
    base = b"".join(unit_parts)
    reps = (size_bytes // len(base)) + 2
    buf = bytearray((base * reps)[:size_bytes])
    rng = random.Random(version_seed)
    patch_len = max(1024, int(size_bytes * 0.03))
    mid = size_bytes // 2
    buf[mid : mid + patch_len] = rng.randbytes(patch_len)
    return bytes(b"/*DELTA-V*/" + buf[: size_bytes - 11])


def prepare_merkle_demo_workspace(ops_dir: Path, mut_seed: int | None = None) -> Path:
    """Create deterministic 16-file ~160 KiB demo workspace with 15 immutable files + 1 mutable status file."""
    ws_dir = Path(ops_dir) / "merkle_demo"
    ws_dir.mkdir(parents=True, exist_ok=True)
    for i in range(15):
        mod_dir = ws_dir / ("core" if i < 8 else "logs")
        mod_dir.mkdir(parents=True, exist_ok=True)
        fp = mod_dir / f"module_{i:02d}.txt"
        if not fp.exists():
            lines = [f"chimera-merkle-stable module={i} line={ln:04d} hash_anchor=cafe{i:04x}\n" for ln in range(160)]
            fp.write_text("".join(lines), encoding="utf-8")
    seed_val = int(time.time()) if mut_seed is None else int(mut_seed)
    mut_file = ws_dir / "live_delta.txt"
    mut_file.write_text(
        f"merkle-heartbeat seed={seed_val} utc={datetime.now(timezone.utc).isoformat()}\n",
        encoding="utf-8",
    )
    return ws_dir


def _bench_local_checks(genome_params: dict[str, Any], ops_dir: Path) -> dict[str, Any]:
    caps = cpu_caps()
    # 1) GF(256) 32x1180 matrix speedup
    k, bl = 32, 1180
    blocks = [os.urandom(bl) for _ in range(k)]
    flat = b"".join(blocks)
    seed = b"auto-gf-seed-001"
    t0 = time.perf_counter()
    enc_py = RLNCEncoder(blocks, seed)
    dec_py = RLNCDecoder(k=k, block_size=bl, seed=seed)
    for did in range(k):
        dec_py.add_droplet(enc_py.generate_droplet(did))
    _ = dec_py.solve()
    py_ms = (time.perf_counter() - t0) * 1000.0

    t1 = time.perf_counter()
    coeffs = b"".join(bytes(coeff_vector(seed, did, k)) for did in range(k))
    coded = b"".join(
        gf256_encode_block(flat, coeffs[r * k : (r + 1) * k], k, bl) for r in range(k)
    )
    rec_nat = gf256_decode_matrix(coded, coeffs, k, bl)
    nat_ms = (time.perf_counter() - t1) * 1000.0
    gfni_ok = rec_nat == flat
    gfni_speedup = py_ms / max(nat_ms, 0.001)

    # 2) 16 MiB Shared-Memory Wormhole vs TCP loopback
    sz16 = 16 * 1024 * 1024
    p16 = (b"WH16-AUTO-" + os.urandom(54)) * (sz16 // 64)
    exp_sha = hashlib.sha256(p16).hexdigest()

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    tcp_hash = hashlib.sha256()

    def _tcp_rx() -> None:
        conn, _ = srv.accept()
        with conn:
            while True:
                b = conn.recv(65536)
                if not b:
                    break
                tcp_hash.update(b)

    th_t = threading.Thread(target=_tcp_rx, daemon=True)
    th_t.start()
    cli = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    t_tcp0 = time.perf_counter()
    try:
        cli.connect(("127.0.0.1", srv.getsockname()[1]))
        cli.sendall(p16)
        cli.shutdown(socket.SHUT_WR)
        th_t.join(timeout=10.0)
    finally:
        cli.close()
        srv.close()
    tcp_lo_ms = (time.perf_counter() - t_tcp0) * 1000.0
    tcp_lo_gbps = (sz16 * 8.0) / max(tcp_lo_ms * 1e6, 0.001)

    wh_gbps = 0.0
    wh_ms = 0.0
    wh_ok = False
    if has_native():
        wh_name = f"AUTO_{os.getpid()}_{time.monotonic_ns()}"
        chunk_buf = bytearray(4 * 1024 * 1024)
        wh_hash = hashlib.sha256()
        ready = threading.Event()
        with WormholeChannel.create(wh_name, capacity_mb=8) as wh_tx:
            def _wh_rx() -> None:
                with WormholeChannel.open(wh_name) as wh_r:
                    mv = memoryview(chunk_buf)
                    ready.set()
                    while True:
                        n = wh_r.read_into(mv)
                        if n == 0:
                            break
                        wh_hash.update(mv[:n])

            th_w = threading.Thread(target=_wh_rx, daemon=True)
            th_w.start()
            ready.wait(timeout=3.0)
            tw0 = time.perf_counter()
            wh_tx.write_all(p16)
            wh_tx.mark_eof()
            th_w.join(timeout=10.0)
            wh_ms = (time.perf_counter() - tw0) * 1000.0
        wh_ok = wh_hash.hexdigest() == exp_sha
        wh_gbps = (sz16 * 8.0) / max(wh_ms * 1e6, 0.001)

    # 3) Simulated 5% loss WAN resilience check (512 KiB @ 80 Mbps, 40 ms RTT)
    p512 = os.urandom(512 * 1024)
    tcp_udp_srv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    tcp_udp_srv.bind(("127.0.0.1", 0))
    bt = ImpairedUdpBridge(tcp_udp_srv.getsockname(), 80.0, 20.0, loss_rate=0.05, seed=705).start()
    try:
        _, tcp_wan_rep = transfer_tcp_cubic_over_udp(p512, bt, tcp_udp_srv, mss=1180, timeout_s=12.0)
    finally:
        bt.close()
        tcp_udp_srv.close()

    rx_hw = HyperWireReceiver(
        gen_k=int(genome_params["gen_k"]),
        sym_size=1180,
    ).start()
    bh = ImpairedUdpBridge(rx_hw.addr, 80.0, 20.0, loss_rate=0.05, seed=705).start()
    try:
        sender = HyperWireSender(
            bh.a_addr,
            gen_k=int(genome_params["gen_k"]),
            max_inflight_gens=int(genome_params["max_inflight_gens"]),
            initial_loss_hint=float(genome_params["loss_hint"]),
        )
        hw_rep = sender.send_stream(p512, stream_id=31, timeout_s=12.0)
        rec_w, solves_w = rx_hw.wait_stream(31, timeout_s=12.0)
        wan_ok = hw_rep.sha256_match and rec_w == p512
    finally:
        bh.close()
        rx_hw.close()

    wan_speedup = tcp_wan_rep.elapsed_ms / max(hw_rep.elapsed_ms, 0.01)

    # 4) Telepathic local dictionary benchmark (Zero-Weight <5 ms)
    sample_logs = make_synthetic_logs(128 * 1024)
    t_dict = train_domain_dictionary([sample_logs[:65536]], domain="synthetic_eval")
    tele_b = benchmark_compression(sample_logs[:65536], t_dict)

    return {
        "cpu_caps": caps,
        "gfni_ok": gfni_ok,
        "gfni_py_ms": round(py_ms, 2),
        "gfni_native_ms": round(nat_ms, 2),
        "gfni_speedup": round(gfni_speedup, 2),
        "wormhole_ok": wh_ok,
        "wormhole_ms": round(wh_ms, 2),
        "wormhole_gbps": round(wh_gbps, 2),
        "tcp_loopback_gbps": round(tcp_lo_gbps, 2),
        "wan_5pct_ok": wan_ok,
        "wan_5pct_tcp_ms": tcp_wan_rep.elapsed_ms,
        "wan_5pct_tcp_mbps": tcp_wan_rep.throughput_mbps,
        "wan_5pct_chimera_ms": hw_rep.elapsed_ms,
        "wan_5pct_chimera_mbps": hw_rep.throughput_mbps,
        "wan_5pct_solves": solves_w,
        "wan_5pct_speedup": round(wan_speedup, 2),
        "telepathy_ok": tele_b["lossless_ok"],
        "telepathy_raw_bytes": tele_b["raw_bytes"],
        "telepathy_zlib_bytes": tele_b["plain_zlib_bytes"],
        "telepathy_wire_bytes": tele_b["telepathic_bytes"],
        "telepathy_vs_raw_pct": tele_b["vs_raw_saved_pct"],
        "telepathy_vs_zlib_pct": tele_b["vs_zlib_saved_pct"],
    }


def _bench_live_peer(
    config: OpsConfig, genome_params: dict[str, Any], ops_dir: Path
) -> dict[str, Any]:
    if not config.peer_ipv4:
        return {"reachable": False, "reason": "No peer_ipv4 configured"}

    base_url = f"http://{config.peer_ipv4}:{config.peer_dashboard_port}"
    try:
        peer_info = _http_get_json(f"{base_url}/api/health", timeout_s=3.5)
    except Exception as exc:
        return {"reachable": False, "reason": f"Peer HTTP unreachable: {exc}"}

    # 1) Live Hedged RPC Race: Single Tailscale IPv4 vs Dual-Stack IPv4 + IPv6
    targets = [(config.peer_ipv4, config.peer_rpc_v4_port)]
    if config.peer_ipv6 and config.peer_rpc_v6_port > 0:
        targets.append((config.peer_ipv6, config.peer_rpc_v6_port))

    rpc_ok = False
    single_lats: list[float] = []
    hedged_lats: list[float] = []
    try:
        c_single = HedgedRpcClient([targets[0]], retry_after_ms=220.0)
        try:
            for i in range(12):
                resp, ms, _ = c_single.call(f"ping-{i}".encode(), timeout_s=2.5)
                if resp:
                    single_lats.append(ms)
        finally:
            c_single.close()

        c_hedged = HedgedRpcClient(
            targets,
            hedge_delay_ms=float(genome_params["hedge_delay_ms"]),
            retry_after_ms=220.0,
        )
        try:
            for i in range(12):
                resp, ms, _ = c_hedged.call(f"hping-{i}".encode(), timeout_s=2.5)
                if resp:
                    hedged_lats.append(ms)
        finally:
            c_hedged.close()
        rpc_ok = bool(single_lats and hedged_lats)
    except Exception as exc:
        return {"reachable": False, "reason": f"Live UDP RPC failed: {exc}", "peer_info": peer_info}

    def pct(arr: list[float], p: float) -> float:
        s = sorted(arr)
        return round(s[min(len(s) - 1, int(p * len(s)))], 2)

    s_p50, s_p99 = pct(single_lats, 0.50), pct(single_lats, 0.99)
    h_p50, h_p99 = pct(hedged_lats, 0.50), pct(hedged_lats, 0.99)

    # 2) Live Cross-Host 1 MiB Incremental DNA Beam vs Live TCP HTTP POST
    tx_vault_dir = ops_dir / "tx_vault"
    work_dir = ops_dir / "beam_work"
    work_dir.mkdir(parents=True, exist_ok=True)
    bundle_file = work_dir / "daily_sync_1mb.bin"
    size_1m = 1024 * 1024

    tx_vault = DnaVault(vault_dir=tx_vault_dir)
    loss_h = max(0.01, float(genome_params["loss_hint"]))
    if tx_vault.chunk_count < 8:
        v1 = _build_incremental_sample(size_1m, version_seed=100)
        bundle_file.write_bytes(v1)
        beam_send(
            (config.peer_ipv4, config.peer_beam_port),
            bundle_file,
            vault_dir=tx_vault_dir,
            est_loss=loss_h,
            timeout_s=20.0,
        )

    v2 = _build_incremental_sample(size_1m, version_seed=int(time.time()) % 10000 + 200)
    bundle_file.write_bytes(v2)
    v2_sha = hashlib.sha256(v2).hexdigest()

    t_tcp0 = time.perf_counter()
    tcp_up = _http_post_bytes(f"{base_url}/api/tcp_sink", v2, timeout_s=25.0)
    tcp_up_ms = (time.perf_counter() - t_tcp0) * 1000.0
    tcp_up_mbps = (len(v2) * 8.0) / max(tcp_up_ms * 1000.0, 0.001)

    brep = beam_send(
        (config.peer_ipv4, config.peer_beam_port),
        bundle_file,
        vault_dir=tx_vault_dir,
        est_loss=loss_h,
        timeout_s=25.0,
    )
    beam_ok = brep.sha256 == v2_sha and bool(brep.wire_report.get("sha256_match"))
    beam_speedup = tcp_up_ms / max(brep.elapsed_ms, 0.01)

    # 3) Train/Sync Telepathic Dictionary + Live Telepathic Active Query & Fluid log_analytics
    q_file = config.watched_query_file or "@synthetic"
    tele_store = TelepathicStore(ops_dir / "dicts")
    domain_dict: DomainDictionary | None = None
    try:
        train_resp = _http_post_json(
            f"{base_url}/api/telepathy/train",
            {"file_path": q_file, "domain": "watched_log"},
            timeout_s=10.0,
        )
        if train_resp.get("zdict_b64"):
            domain_dict = DomainDictionary.from_wire_dict(train_resp)
            tele_store.put(domain_dict)
    except Exception:
        domain_dict = tele_store.latest_for_domain("watched_log")

    t_qt0 = time.perf_counter()
    with urllib.request.urlopen(
        f"{base_url}/api/raw_query_file?path={urllib.parse.quote(q_file)}", timeout=20.0
    ) as resp:
        raw_q = resp.read()
    local_filt, local_cnt, _ = execute_operator(
        raw_q, ComputePlan(op="filter_lines", needle="ERROR")
    )
    tcp_q_ms = (time.perf_counter() - t_qt0) * 1000.0

    q_res, q_meta = remote_active_query(
        (config.peer_ipv4, config.peer_query_port),
        file_path=q_file,
        plan=ComputePlan(
            op="filter_lines",
            needle="ERROR",
            use_telepathy=True,
            dict_id=domain_dict.dict_id if domain_dict else "",
        ),
        est_loss=loss_h,
        timeout_s=20.0,
        telepathy_store=tele_store,
        domain_dict=domain_dict,
    )
    q_ok = q_res.matched_records == local_cnt
    q_speedup = tcp_q_ms / max(q_res.total_ms, 0.01)

    # Fluid Compute Pushdown: log_analytics summary right on peer
    analytics_ok = False
    analytics_ms = 0.0
    analytics_templates = 0
    try:
        a_res, _ = remote_active_query(
            (config.peer_ipv4, config.peer_query_port),
            file_path=q_file,
            plan=ComputePlan(op="log_analytics", use_telepathy=True),
            est_loss=loss_h,
            timeout_s=15.0,
        )
        a_obj = json.loads(a_res.output_bytes.decode("utf-8"))
        analytics_ok = a_obj.get("total_lines", 0) > 0
        analytics_ms = a_res.total_ms
        analytics_templates = int(a_obj.get("unique_templates", 0))
    except Exception:
        pass

    # 4) Live Merkle Directory Delta Sync (16 files, 1 changed)
    merkle_ok = False
    merkle_res: dict[str, Any] = {}
    try:
        ws_dir = prepare_merkle_demo_workspace(ops_dir)
        merkle_res = merkle_beam_sync(
            peer_http_base=base_url,
            peer_beam_addr=(config.peer_ipv4, config.peer_beam_port),
            local_dir=ws_dir,
            workspace_id="autopilot_demo",
            vault_dir=tx_vault_dir,
            shadow_dir=ops_dir / "merkle_shadows",
            est_loss=loss_h,
            timeout_s=20.0,
        )
        merkle_ok = bool(merkle_res.get("verified_root_match"))
    except Exception as exc:
        merkle_res = {"error": str(exc)}

    # 5) Live Immortal Multi-Path Chaos Survival (v4 + v6, kill Lane 0 after 1 gen)
    immortal_ok = False
    immortal_res: dict[str, Any] = {}
    if config.peer_ipv6 and config.peer_immortal_v4_port > 0 and config.peer_immortal_v6_port > 0:
        try:
            imm_targets = [
                (config.peer_ipv4, config.peer_immortal_v4_port),
                (config.peer_ipv6, config.peer_immortal_v6_port),
            ]
            sid_imm = (int(time.time()) % 200) + 10
            payload_imm = os.urandom(128 * 1024)
            irep = ImmortalMultiPathSender(
                imm_targets, gen_k=32, initial_loss_hint=max(0.02, loss_h)
            ).send_stream(
                payload_imm,
                stream_id=sid_imm,
                timeout_s=12.0,
                chaos_kill_lane=0,
                chaos_kill_after_gens=1,
            )
            rx_check: dict[str, Any] = {}
            for _ in range(5):
                try:
                    rx_check = _http_get_json(
                        f"{base_url}/api/immortal/result?stream_id={sid_imm}", timeout_s=2.0
                    )
                    if rx_check.get("found"):
                        break
                except Exception:
                    pass
                time.sleep(0.05)
            immortal_ok = bool(
                irep.survived_blackout
                and irep.sha256_match
                and rx_check.get("sha256") == irep.sha256
            )
            immortal_res = {
                "ok": immortal_ok,
                "elapsed_ms": irep.elapsed_ms,
                "lane_tx": irep.lane_tx_counts,
                "lane_rx": rx_check.get("lane_rx_counts", []),
                "survived_blackout": irep.survived_blackout,
                "reconnects": irep.reconnects,
            }
        except Exception as exc:
            immortal_res = {"ok": False, "error": str(exc)}

    return {
        "reachable": True,
        "peer_name": config.peer_name or peer_info.get("node_name", "peer"),
        "peer_hardware": peer_info.get("hardware", {}),
        "dual_stack_targets": len(targets),
        "rtt_p50_ms": h_p50,
        "single_p50_ms": s_p50,
        "single_p99_ms": s_p99,
        "hedged_p99_ms": h_p99,
        "rpc_ok": rpc_ok,
        "beam_ok": beam_ok,
        "beam_raw_bytes": len(v2),
        "beam_wire_bytes": brep.udp_wire_bytes,
        "beam_saved_pct": brep.reduction_pct,
        "beam_elapsed_ms": brep.elapsed_ms,
        "beam_eff_mbps": brep.effective_mbps,
        "tcp_upload_ms": round(tcp_up_ms, 2),
        "tcp_upload_mbps": round(tcp_up_mbps, 2),
        "tcp_upload_sha_ok": tcp_up.get("sha256") == v2_sha,
        "beam_speedup": round(beam_speedup, 2),
        "query_ok": q_ok,
        "query_file": q_file,
        "query_raw_bytes": q_res.raw_bytes,
        "query_wire_bytes": q_res.wire_bytes,
        "query_saved_pct": q_res.wire_reduction_pct,
        "query_codec_mode": q_meta.get("codec_mode", "raw"),
        "query_matched": q_res.matched_records,
        "query_p0_ms": q_res.preview_first_ms,
        "query_chimera_ms": q_res.total_ms,
        "query_tcp_ms": round(tcp_q_ms, 2),
        "query_speedup": round(q_speedup, 2),
        "query_server_exec_ms": q_meta.get("server_exec_ms", 0.0),
        "fluid_analytics_ok": analytics_ok,
        "fluid_analytics_ms": analytics_ms,
        "fluid_analytics_templates": analytics_templates,
        "merkle_ok": merkle_ok,
        "merkle": merkle_res,
        "immortal_ok": immortal_ok,
        "immortal": immortal_res,
    }


def format_cluster_markdown_report(status_payload: dict[str, Any]) -> str:
    """Format human-readable Markdown cluster evaluation report for Tailscale Hub."""
    cluster = status_payload.get("cluster", {}) or {}
    verdict = cluster.get("evaluation_verdict", {}) or {}
    nodes = cluster.get("nodes", []) or []
    cross = cluster.get("latest_cross_host") or (status_payload.get("telemetry", {}) or {}).get("latest")
    zw = status_payload.get("zero_weight", {}) or {}
    tel = status_payload.get("telemetry", {}) or {}
    now_str = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")

    lines: list[str] = [
        f"# CHIMERA-HYPER v{status_payload.get('version', '5.0.0')} — Báo Cáo Đánh Giá Cụm",
        "",
        f"- **Thời điểm xuất:** `{now_str}`",
        f"- **Xếp hạng cụm:** **{verdict.get('grade', 'N/A')}** (Sức khỏe TB: `{verdict.get('avg_health_score', 0)}/100`, Zero-Weight: `{verdict.get('zero_weight_ok', True)}`)",
        f"- **Hub hiện tại:** `{status_payload.get('config', {}).get('node_name', 'svhome')}` (RAM daemon `{zw.get('daemon_ram_mb', 0)} MB` / trống `{zw.get('host_free_ram_gb', 0)} GB`)",
        f"- **Khung giờ đề xuất đồng bộ nặng:** `{tel.get('recommended_sync_window', 'NIGHT_CLEAN')}` (hiện tại `{tel.get('active_bucket', '')}`)",
        "",
        "## 1. Sức khỏe từng Node",
        "",
        "| Node | Vai trò | RAM Daemon | GF(256) Speedup | WAN 5% Drop | Beam | Query (-wire) | Cập nhật |",
        "| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :--- |",
    ]
    for n in nodes:
        lines.append(
            f"| `{n.get('node_name')}` | {n.get('role')} | {n.get('daemon_ram_mb', 0)} MB | "
            f"{n.get('gfni_speedup', 0)}x | **{n.get('wan_5pct_speedup', 0)}x** | "
            f"{n.get('beam_speedup', 0)}x | {n.get('query_speedup', 0)}x (-{n.get('query_saved_pct', 0)}%) | {n.get('ts_local', '')} |"
        )
    if not nodes:
        lines.append("| _(Chưa có node nào gửi báo cáo)_ | - | - | - | - | - | - | - |")

    if cross:
        loc = cross.get("local", {}) or {}
        pr = cross.get("peer", {}) or {}
        lines.extend(
            [
                "",
                f"## 2. Đối chiếu Trước vs Sau mới nhất (`{cross.get('node_name')}` -> `{pr.get('peer_name', 'local')}`)",
                "",
                "| Tác vụ | Trước (TCP chuẩn) | Sau (CHIMERA v3.0) | Hiệu quả |",
                "| :--- | :--- | :--- | :--- |",
                f"| Lõi GF(256) 1 MB | {loc.get('gfni_py_ms', 0)} ms | {loc.get('gfni_native_ms', 0)} ms | **{loc.get('gfni_speedup', 0)}x** |",
                f"| WAN 5% Rớt Gói | {loc.get('wan_5pct_tcp_mbps', 0)} Mbps | {loc.get('wan_5pct_chimera_mbps', 0)} Mbps | **{loc.get('wan_5pct_speedup', 0)}x** |",
                f"| Telepathic Local | Zlib {loc.get('telepathy_zlib_bytes', 0)} B | {loc.get('telepathy_wire_bytes', 0)} B | **-{loc.get('telepathy_vs_raw_pct', 0)}%** |",
            ]
        )
        if pr.get("reachable"):
            mk = pr.get("merkle", {}) or {}
            imm = pr.get("immortal", {}) or {}
            lines.extend(
                [
                    f"| DNA Beam 1 MiB (Tailscale) | {pr.get('tcp_upload_ms', 0)} ms ({pr.get('tcp_upload_mbps', 0)} Mbps) | {pr.get('beam_elapsed_ms', 0)} ms ({pr.get('beam_wire_bytes', 0)} B) | **-{pr.get('beam_saved_pct', 0)}% ({pr.get('beam_speedup', 0)}x)** |",
                    f"| Remote Log Query ({pr.get('query_codec_mode', '')}) | {pr.get('query_tcp_ms', 0)} ms ({pr.get('query_raw_bytes', 0)} B) | {pr.get('query_chimera_ms', 0)} ms ({pr.get('query_wire_bytes', 0)} B) | **-{pr.get('query_saved_pct', 0)}% ({pr.get('query_speedup', 0)}x)** |",
                ]
            )
            if mk.get("verified_root_match"):
                lines.append(
                    f"| Merkle Sync 16 file | {mk.get('total_bytes', 0)} B | {mk.get('udp_wire_bytes', 0)} B (`scan {mk.get('scan_ms', 0)} ms`) | **-{mk.get('total_reduction_pct', 0)}%** |"
                )
            if imm.get("ok"):
                lines.append(
                    f"| Immortal Cắt IPv4 giữa dòng | Đứt phiên TCP | TX `{imm.get('lane_tx', [])}` / RX `{imm.get('lane_rx', [])}` ({imm.get('elapsed_ms', 0)} ms) | **0 reconnect** |"
                )

    lines.extend(["", "## 3. Khuyến nghị theo Link Weather 24h", ""])
    for w in tel.get("link_weather", []) or []:
        if int(w.get("samples", 0)) > 0:
            lines.append(
                f"- `{w['bucket']}`: `{w['samples']}` mẫu | RTT `{w['ema_rtt_ms']} ms` | WAN `{w['ema_wan_speedup']}x` | Genome tốt nhất: `{w['best_genome']}`"
            )

    sent = status_payload.get("sentinel") or {}
    cs = status_payload.get("code_search") or {}
    edge = status_payload.get("edge") or {}
    bks = status_payload.get("holo_backups") or []
    nat_last = status_payload.get("nat_last") or {}
    lines.extend(["", "## 4. CHIMERA-HYPER v4.0 Zero-Weight HyperOS", ""])
    if sent:
        lines.append(
            f"- **Sentinel:** `{sent.get('status', 'PENDING')}` | Cảnh báo gần nhất: `{sent.get('alert_count', 0)}` | Scan lúc `{sent.get('ts_local', '-')}`"
        )
    if cs:
        lines.append(
            f"- **Code Search FTS5:** `{cs.get('indexed_files', 0)}` files / `{cs.get('repos_count', 0)}` repos (`{cs.get('db_size_kb', 0)} KB` SQLite WAL)"
        )
    if edge:
        gw = edge.get("gateway", {}) or {}
        lines.append(
            f"- **Edge Accelerator:** `{gw.get('requests', 0)}` reqs | Giảm dây `{gw.get('saved_pct', 0)}%` | Prefetch items `{gw.get('prefetched_items', 0)}`"
        )
    if bks:
        lines.append(
            f"- **Holographic GF(256) (2/3) Backups:** `{len(bks)}` snapshots"
        )
    if nat_last:
        lines.append(
            f"- **NAT Buster lần cuối:** `{nat_last.get('fallback_mode', '-')}` | {nat_last.get('diagnosis', '')}"
        )
    ph = status_payload.get("phantom") or {}
    if ph:
        cl = ph.get("client") or {}
        if cl:
            lines.extend(
                [
                    "",
                    "## 5. CHIMERA-HYPER v5.0 PHANTOM-5MS",
                    f"- **Tunnel Mode:** `{cl.get('mode', 'DISCONNECTED')}` | RTT trực tiếp: `{cl.get('direct_rtt_ms', 0)} ms` | Forwards: `{cl.get('listeners', {})}`",
                ]
            )
    return "\n".join(lines) + "\n"


def run_daily_autopilot(
    config: OpsConfig,
    store: TelemetryStore,
    trigger: str = "manual",
    ops_dir: Path | None = None,
) -> dict[str, Any]:
    """Execute full daily health, Before-vs-After evaluation, and Contextual UCB1 update."""
    base_dir = Path(ops_dir) if ops_dir else default_ops_dir()
    active_bucket = time_bucket_for_hour()
    genome_id, genome_params = store.select_genome(config.active_profile)

    local_res = _bench_local_checks(genome_params, base_dir)
    peer_res = _bench_live_peer(config, genome_params, base_dir)
    zw = get_zero_weight_status()

    anomalies: list[str] = []
    score = 100
    if not local_res["gfni_ok"] or not local_res["cpu_caps"].get("native"):
        score -= 25
        anomalies.append("NATIVE_CORE_UNAVAILABLE")
    if has_native() and not local_res["wormhole_ok"]:
        score -= 15
        anomalies.append("WORMHOLE_SHM_FAILED")
    if not local_res["wan_5pct_ok"]:
        score -= 25
        anomalies.append("WAN_GFNI_RECOVERY_FAILED")
    elif local_res["wan_5pct_speedup"] < 5.0:
        score -= 10
        anomalies.append("LOW_WAN_SPEEDUP")
    if not zw["zero_weight_ok"]:
        score -= 5
        anomalies.append(f"HIGH_DAEMON_RAM_{zw['daemon_ram_mb']}MB")

    if config.peer_ipv4:
        if not peer_res.get("reachable"):
            score -= 20
            anomalies.append(f"PEER_UNREACHABLE: {peer_res.get('reason', '')}")
        else:
            if not peer_res.get("beam_ok"):
                score -= 20
                anomalies.append("PEER_BEAM_SHA_MISMATCH")
            if not peer_res.get("query_ok"):
                score -= 10
                anomalies.append("PEER_QUERY_MISMATCH")

    state_before = store.get_dashboard_state(limit=7)
    avg_7d = state_before.get("avg_7d", {})
    if avg_7d.get("wan_5pct_speedup", 0.0) > 0:
        if local_res["wan_5pct_speedup"] < avg_7d["wan_5pct_speedup"] * 0.55:
            score -= 10
            anomalies.append("REGRESSION_VS_7D_WAN")

    score = max(0, min(100, score))

    reward = (
        min(4.0, local_res["wan_5pct_speedup"] / 10.0)
        + min(2.0, local_res["wormhole_gbps"] / 8.0)
        + (
            min(2.5, float(peer_res.get("beam_speedup", 0.0)))
            + min(1.5, float(peer_res.get("query_speedup", 0.0)) / 3.0)
            if peer_res.get("reachable")
            else 1.5
        )
    )
    if anomalies:
        reward = max(0.0, reward - 2.0 * len(anomalies))

    now_utc = datetime.now(timezone.utc).isoformat(timespec="seconds")
    now_local = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
    summary = {
        "version": "5.0.0",
        "node_name": config.node_name,
        "role": config.role,
        "ts_utc": now_utc,
        "ts_local": now_local,
        "time_bucket": active_bucket,
        "trigger": trigger,
        "profile": config.active_profile,
        "genome_id": genome_id,
        "genome_params": genome_params,
        "health_score": score,
        "reward": round(reward, 3),
        "anomalies": anomalies,
        "zero_weight": zw,
        "local": local_res,
        "peer": peer_res,
    }
    run_id = store.record_run(summary, genome_id=genome_id, reward=reward)
    summary["run_id"] = run_id
    store.record_cluster_report(summary)

    pushed_to_hub = False
    if config.peer_ipv4:
        try:
            hub_url = f"http://{config.peer_ipv4}:{config.peer_dashboard_port}/api/cluster/ingest"
            ingest_res = _http_post_json(hub_url, summary, timeout_s=5.0)
            pushed_to_hub = bool(ingest_res.get("ok"))
        except Exception:
            pushed_to_hub = False
    summary["pushed_to_hub"] = pushed_to_hub

    level = "WARN" if anomalies else "INFO"
    msg = (
        f"Run #{run_id} [{trigger}|{active_bucket}] score={score} RAM={zw['daemon_ram_mb']}MB genome={genome_id} "
        f"WAN_5pct={local_res['wan_5pct_speedup']}x Telepathy=-{local_res['telepathy_vs_raw_pct']}%"
    )
    if peer_res.get("reachable"):
        msg += (
            f" Beam={peer_res['beam_speedup']}x Query={peer_res['query_speedup']}x(-{peer_res['query_saved_pct']}%)"
        )
        if peer_res.get("merkle_ok"):
            msg += f" Merkle=-{peer_res['merkle'].get('total_reduction_pct', 0)}%"
    if anomalies:
        msg += f" Alerts={','.join(anomalies)}"
    store.log_event(level, "AUTOPILOT", msg)

    report_path = base_dir / "latest_report.json"
    tmp = base_dir / "latest_report.json.tmp"
    tmp.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, report_path)
    return summary
