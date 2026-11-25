"""CHIMERA-HYPER v2.0 Autopilot: Darwinian UCB1 Genome Auto-Tuner, SQLite Store & Live Suite."""

from __future__ import annotations

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
)
from .impairment import ImpairedUdpBridge, transfer_tcp_cubic_over_udp
from .native import WormholeChannel, cpu_caps, gf256_decode_matrix, gf256_encode_block, has_native

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
    peer_name: str = ""
    peer_ipv4: str = ""
    peer_ipv6: str = ""
    peer_beam_port: int = 9700
    peer_rpc_v4_port: int = 9702
    peer_rpc_v6_port: int = 9703
    peer_query_port: int = 9704
    peer_dashboard_port: int = 9780
    active_profile: str = "auto-darwin"
    daily_time: str = "08:00"
    watched_query_file: str = "@synthetic"
    allowed_query_roots: list[str] = field(default_factory=list)

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
    """Thread-safe SQLite store for daily telemetry runs, Darwinian genomes, and live events."""

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
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts_local TEXT NOT NULL,
                    level TEXT NOT NULL,
                    category TEXT NOT NULL,
                    message TEXT NOT NULL
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
            self._conn.commit()

    def select_genome(self, profile: str) -> tuple[str, dict[str, Any]]:
        if profile == "max-speed":
            return "G3_TURBO_BULK", dict(GENOMES["G3_TURBO_BULK"])
        if profile == "lossy-armor":
            return "G2_LOSSY_ARMOR", dict(GENOMES["G2_LOSSY_ARMOR"])
        if profile == "exotic-v05":
            return "G0_BALANCED", dict(GENOMES["G0_BALANCED"])

        # Darwinian UCB1 bandit selection
        with self._lock:
            rows = self._conn.execute(
                "SELECT genome_id, pulls, avg_reward FROM genomes ORDER BY genome_id"
            ).fetchall()
        total_pulls = sum(int(r["pulls"]) for r in rows)
        for r in rows:
            if int(r["pulls"]) == 0:
                gid = str(r["genome_id"])
                return gid, dict(GENOMES[gid])
        best_gid = "G0_BALANCED"
        best_score = -1.0
        for r in rows:
            gid = str(r["genome_id"])
            pulls = max(1, int(r["pulls"]))
            avg_r = float(r["avg_reward"])
            ucb = avg_r + 1.2 * math.sqrt(math.log(max(2, total_pulls)) / pulls)
            if ucb > best_score:
                best_score = ucb
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
                    float(summary["local"]["wan_5pct_speedup"]),
                    1 if summary["peer"]["reachable"] else 0,
                    float(summary["peer"].get("rtt_p50_ms", 0.0)),
                    float(summary["peer"].get("hedged_p99_ms", 0.0)),
                    float(summary["peer"].get("single_p99_ms", 0.0)),
                    float(summary["peer"].get("beam_speedup", 0.0)),
                    float(summary["peer"].get("beam_saved_pct", 0.0)),
                    float(summary["peer"].get("query_speedup", 0.0)),
                    float(summary["peer"].get("query_saved_pct", 0.0)),
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
            self._conn.commit()
            return run_id

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
        return {
            "total_runs": len(history),
            "latest": latest_full,
            "history": history,
            "avg_7d": avg_7d,
            "genomes": genomes,
            "events": events,
        }

    def close(self) -> None:
        with self._lock:
            self._conn.close()


def _http_get_json(url: str, timeout_s: float = 3.0) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout_s) as resp:
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
    # Insert/mutate deterministic 3% slice around midpoint so FastCDC preserves ~95% chunks
    rng = random.Random(version_seed)
    patch_len = max(1024, int(size_bytes * 0.03))
    mid = size_bytes // 2
    buf[mid : mid + patch_len] = rng.randbytes(patch_len)
    return bytes(b"/*DELTA-V*/" + buf[: size_bytes - 11])


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

    # TCP loopback 16 MiB
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
    if config.peer_ipv6:
        targets.append((config.peer_ipv6, config.peer_rpc_v6_port))

    rpc_ok = False
    single_lats: list[float] = []
    hedged_lats: list[float] = []
    try:
        c_single = HedgedRpcClient([targets[0]], retry_after_ms=220.0)
        try:
            for i in range(15):
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
            for i in range(15):
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

    # Prime vault on cold first run so subsequent live run tests real incremental delta sync
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

    # Before: real TCP upload of all 1 MiB over Tailscale
    t_tcp0 = time.perf_counter()
    tcp_up = _http_post_bytes(f"{base_url}/api/tcp_sink", v2, timeout_s=25.0)
    tcp_up_ms = (time.perf_counter() - t_tcp0) * 1000.0
    tcp_up_mbps = (len(v2) * 8.0) / max(tcp_up_ms * 1000.0, 0.001)

    # After: CHIMERA DNA Beam over UDP Tailscale
    brep = beam_send(
        (config.peer_ipv4, config.peer_beam_port),
        bundle_file,
        vault_dir=tx_vault_dir,
        est_loss=loss_h,
        timeout_s=25.0,
    )
    beam_ok = brep.sha256 == v2_sha and bool(brep.wire_report.get("sha256_match"))
    beam_speedup = tcp_up_ms / max(brep.elapsed_ms, 0.01)

    # 3) Live Remote Active Compute-in-Transit Query on Peer
    q_file = config.watched_query_file or "@synthetic"
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
        plan=ComputePlan(op="filter_lines", needle="ERROR"),
        est_loss=loss_h,
        timeout_s=20.0,
    )
    q_ok = q_res.matched_records == local_cnt
    q_speedup = tcp_q_ms / max(q_res.total_ms, 0.01)

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
        "query_matched": q_res.matched_records,
        "query_p0_ms": q_res.preview_first_ms,
        "query_chimera_ms": q_res.total_ms,
        "query_tcp_ms": round(tcp_q_ms, 2),
        "query_speedup": round(q_speedup, 2),
        "query_server_exec_ms": q_meta.get("server_exec_ms", 0.0),
    }


def run_daily_autopilot(
    config: OpsConfig,
    store: TelemetryStore,
    trigger: str = "manual",
    ops_dir: Path | None = None,
) -> dict[str, Any]:
    """Execute full daily health, Before-vs-After evaluation, and Darwinian UCB1 update."""
    base_dir = Path(ops_dir) if ops_dir else default_ops_dir()
    genome_id, genome_params = store.select_genome(config.active_profile)

    local_res = _bench_local_checks(genome_params, base_dir)
    peer_res = _bench_live_peer(config, genome_params, base_dir)

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

    # Compare vs 7-day rolling baseline
    state_before = store.get_dashboard_state(limit=7)
    avg_7d = state_before.get("avg_7d", {})
    if avg_7d.get("wan_5pct_speedup", 0.0) > 0:
        if local_res["wan_5pct_speedup"] < avg_7d["wan_5pct_speedup"] * 0.55:
            score -= 10
            anomalies.append("REGRESSION_VS_7D_WAN")

    score = max(0, min(100, score))

    # Darwinian UCB1 Reward (normalized ~0..10 scale)
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
        "node_name": config.node_name,
        "role": config.role,
        "ts_utc": now_utc,
        "ts_local": now_local,
        "trigger": trigger,
        "profile": config.active_profile,
        "genome_id": genome_id,
        "genome_params": genome_params,
        "health_score": score,
        "reward": round(reward, 3),
        "anomalies": anomalies,
        "local": local_res,
        "peer": peer_res,
    }
    run_id = store.record_run(summary, genome_id=genome_id, reward=reward)
    summary["run_id"] = run_id

    level = "WARN" if anomalies else "INFO"
    msg = (
        f"Run #{run_id} [{trigger}] score={score} genome={genome_id} "
        f"WAN_5pct={local_res['wan_5pct_speedup']}x SHM={local_res['wormhole_gbps']}Gbps"
    )
    if peer_res.get("reachable"):
        msg += (
            f" PeerBeam={peer_res['beam_speedup']}x({peer_res['beam_saved_pct']}%) "
            f"PeerQuery={peer_res['query_speedup']}x"
        )
    if anomalies:
        msg += f" Alerts={','.join(anomalies)}"
    store.log_event(level, "AUTOPILOT", msg)

    report_path = base_dir / "latest_report.json"
    tmp = base_dir / "latest_report.json.tmp"
    tmp.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, report_path)
    return summary
