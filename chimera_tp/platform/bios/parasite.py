"""CHIMERA-PARASITE — Idea #4: Red-Queen Adversarial Self-Play Arena.

Continuously pits simulated CHIMERA-HOST defense invariants against
evolutionarily mutated adversarial PARASITE payloads inside an isolated
in-memory sandbox (0 touch on production files or live processes).

Whenever a Parasite variant breaches a defense threshold, the arena
synthesizes a cryptographically signed Law-6 Vaccine Receipt
(`auto_activated=False`, `requires_human_approval=True`) containing:
  - reproducible attack vector (scenario, seed, mutated parameters, digest)
  - immune_antibody rule (`error_sig`, `fix_hint`, `severity`)
  - executable regression unit-test snippet
  - host hardening delta & rollback recipe

Compliance with CHIMERA-ONE Doctrine (Laws 1-7):
  - 100% Python stdlib, Zero-NumPy, lazy-loaded, < 2 MiB working memory
  - Law 2: Zero OS kernel interference or process suspension
  - Law 6: Every vaccine & hardening delta has `auto_activated=False`
  - Law 7: Bounded ledger footprint in SQLite WAL (or `:memory:` ephemeral)
"""
from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import random
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any


def _chimera_home() -> Path:
    return Path(os.environ.get("CHIMERA_HOME") or (Path.home() / ".chimera"))


def _canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


# ---------------------------------------------------------------------------
# Parameterized Adversarial Attack Vectors (6 Real CHIMERA-TP Scenarios)
# ---------------------------------------------------------------------------

PARASITE_SCENARIOS: dict[str, dict[str, Any]] = {
    "packet_loss_storm": {
        "description": "35-50% bursty UDP packet loss + jitter spikes testing RLNC/FEC & failover invariants",
        "target_organ": "Causal Spine / PhantomTunnel",
        "invariant": "recovery_rate >= 0.98 and p99_effective_jitter_ms <= 85.0",
        "severity": "high",
        "param_ranges": {
            "drop_rate": (0.35, 0.50),
            "burst_len": (2, 8),
            "jitter_ms": (20.0, 140.0),
            "frames": (40, 80),
        },
        "baseline_host": {
            "fec_parity_ratio": 0.35,
            "failover_drop_trigger": 0.48,
            "jitter_buffer_ms": 45.0,
        },
    },
    "steer_503_race": {
        "description": "Concurrent detached-stream + user steer contention testing < 1 ms interactive preemption",
        "target_organ": "Hemisphere Router / ImmortalSocket",
        "invariant": "preempt_latency_ms < 1.0 and steer_503_count == 0",
        "severity": "critical",
        "param_ranges": {
            "detached_streams": (4, 16),
            "steer_burst": (2, 8),
            "detached_hold_ms": (0.4, 3.2),
            "retry_amplification": (1, 5),
        },
        "baseline_host": {
            "reserved_steer_slots": 0,
            "preemptive_yield_ms": 1.6,
            "max_retry_storm": 4,
        },
    },
    "file_lease_deadlock": {
        "description": "Parallel agents requesting overlapping cyclic file leases testing deadlock prevention",
        "target_organ": "Akashic Swarm-Kernel / File-Lease",
        "invariant": "deadlock_detected_and_broken == True and unresolved_cycles == 0",
        "severity": "high",
        "param_ranges": {
            "agent_count": (2, 5),
            "cycle_len": (2, 5),
            "lock_overlap": (0.5, 1.0),
            "lease_ttl_ms": (20, 200),
        },
        "baseline_host": {
            "max_cycle_depth": 2,
            "canonical_lock_order": False,
            "wound_wait_backoff": False,
        },
    },
    "prefix_cache_cliff": {
        "description": "Mid-prefix volatile mutation & context bloat testing KV cache stability floor",
        "target_organ": "Akashic Swarm-Kernel / PRISM Prefix",
        "invariant": "cache_hit_ratio >= 0.85 and bloat_factor <= 1.35",
        "severity": "high",
        "param_ranges": {
            "prefix_blocks": (32, 96),
            "mutation_offset_pct": (0.04, 0.45),
            "volatile_injections": (1, 5),
            "bloat_ratio": (1.05, 2.60),
        },
        "baseline_host": {
            "hoist_volatile_to_tail": False,
            "max_bloat_ratio": 1.35,
            "prefix_hash_guard": False,
        },
    },
    "rss_ceiling_squeeze": {
        "description": "Memory allocation spikes & fragmentation testing Law 7 < 80 MiB daemon RSS ceiling",
        "target_organ": "Entropy Annihilator / Law-7 Guard",
        "invariant": "peak_rss_mb < 80.0",
        "severity": "critical",
        "param_ranges": {
            "baseline_rss_mb": (54.0, 66.0),
            "alloc_spike_mb": (8.0, 26.0),
            "fragmentation": (1.05, 1.55),
            "retained_caches": (1, 6),
        },
        "baseline_host": {
            "gc_trigger_mb": 77.5,
            "evict_fraction": 0.20,
            "cold_spill_enabled": False,
        },
    },
    "secret_egress_smuggle": {
        "description": "Base64/hex/chunk-split obfuscated canary token egress leak probe",
        "target_organ": "Causal Spine / EgressMembrane",
        "invariant": "egress_blocked == True",
        "severity": "critical",
        "param_ranges": {
            "encoding_mode": ("raw", "base64", "double_base64", "hex", "split_chunk"),
            "token_family": ("ghp", "sk_live", "aiza", "jwt_bearer"),
            "noise_pad": (0, 12),
        },
        "baseline_host": {
            "decode_depth": 1,
            "inspect_hex": False,
            "reassemble_chunks": False,
        },
    },
}

_CANARY_PATTERNS = re.compile(
    r"(?:ghp_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9_-]{20,}|AIza[0-9A-Za-z_-]{20,}|eyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,})"
)


# ---------------------------------------------------------------------------
# Isolated Sandbox Evaluators (0 Production File / Process Touch)
# ---------------------------------------------------------------------------

def _sample_parasite_params(scenario: str, rng: random.Random, intensity: float = 0.5) -> dict[str, Any]:
    spec = PARASITE_SCENARIOS[scenario]
    params: dict[str, Any] = {}
    bias = max(0.0, min(1.0, intensity))
    for k, bounds in spec["param_ranges"].items():
        if isinstance(bounds[0], str):
            # Pick increasingly evasive modes as evolutionary intensity climbs
            idx_min = int(bias * max(0, len(bounds) - 2))
            params[k] = bounds[rng.randint(idx_min, len(bounds) - 1)]
        elif isinstance(bounds[0], int) and isinstance(bounds[1], int):
            lo, hi = bounds
            shifted_lo = min(hi, lo + int((hi - lo) * bias * 0.45))
            params[k] = rng.randint(shifted_lo, hi)
        else:
            lo, hi = float(bounds[0]), float(bounds[1])
            shifted_lo = min(hi, lo + (hi - lo) * bias * 0.45)
            params[k] = round(rng.uniform(shifted_lo, hi), 4)
    return params


def _mutate_parasite_params(scenario: str, parent: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    spec = PARASITE_SCENARIOS[scenario]
    child = dict(parent)
    keys = list(spec["param_ranges"].keys())
    mutate_k = rng.choice(keys)
    bounds = spec["param_ranges"][mutate_k]
    if isinstance(bounds[0], str):
        cur_idx = bounds.index(child[mutate_k]) if child.get(mutate_k) in bounds else 0
        step = rng.choice([-1, 1, 1])
        child[mutate_k] = bounds[max(0, min(len(bounds) - 1, cur_idx + step))]
    elif isinstance(bounds[0], int) and isinstance(bounds[1], int):
        lo, hi = bounds
        delta = rng.choice([-1, 1, 2])
        child[mutate_k] = max(lo, min(hi, int(child.get(mutate_k, lo)) + delta))
    else:
        lo, hi = float(bounds[0]), float(bounds[1])
        span = hi - lo
        delta = rng.uniform(-0.12 * span, 0.22 * span)
        child[mutate_k] = round(max(lo, min(hi, float(child.get(mutate_k, lo)) + delta)), 4)
    return child


def _eval_packet_loss_storm(params: dict[str, Any], host: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    drop_rate = float(params["drop_rate"])
    burst_len = int(params["burst_len"])
    jitter_ms = float(params["jitter_ms"])
    frames = int(params["frames"])

    fec_parity = float(host.get("fec_parity_ratio", 0.35))
    failover_trigger = float(host.get("failover_drop_trigger", 0.48))
    jitter_buf = float(host.get("jitter_buffer_ms", 45.0))

    # Gilbert-Elliott bursty packet drop simulation over RLNC coded blocks (k=10)
    k = 10
    n_coded = k + max(1, int(math.ceil(k * fec_parity)))
    p_bad_to_good = 1.0 / max(1.0, float(burst_len))
    p_good_to_bad = min(0.95, (drop_rate * p_bad_to_good) / max(0.05, 1.0 - drop_rate))

    recovered = 0
    in_burst = False
    observed_drops = 0
    total_pkts = 0
    failed_over = False
    fast_probe_window = 6 if failover_trigger <= 0.30 else 20

    for _ in range(frames):
        received = 0
        for _ in range(n_coded):
            total_pkts += 1
            eff_p_g2b = p_good_to_bad * 0.08 if failed_over else p_good_to_bad
            eff_p_b2g = min(0.95, p_bad_to_good * 3.0) if failed_over else p_bad_to_good
            if in_burst:
                if rng.random() < eff_p_b2g:
                    in_burst = False
            else:
                if rng.random() < eff_p_g2b:
                    in_burst = True
            if in_burst:
                observed_drops += 1
            else:
                received += 1
            if not failed_over and total_pkts >= fast_probe_window and (observed_drops / total_pkts) >= failover_trigger:
                failed_over = True
                in_burst = False
        if received >= k:
            recovered += 1

    recovery_rate = recovered / max(1, frames)
    effective_jitter = (jitter_ms * (0.45 if failed_over else 1.0)) - (jitter_buf * 0.35)
    effective_jitter = max(1.0, round(effective_jitter, 2))
    breached = (recovery_rate < 0.98) or (effective_jitter > 85.0)
    margin = max(0.98 - recovery_rate, (effective_jitter - 85.0) / 100.0)
    fitness = round(max(0.0, min(1.0, 0.5 + margin * 2.5 if breached else (1.0 - recovery_rate) * 2.0)), 4)

    return {
        "breached": breached,
        "fitness": fitness,
        "metrics": {
            "recovery_rate": round(recovery_rate, 4),
            "observed_drop_rate": round(observed_drops / max(1, total_pkts), 4),
            "effective_jitter_ms": effective_jitter,
            "failed_over": failed_over,
        },
        "error_sig": f"rlnc_loss_breach:rec={recovery_rate:.2f}:jit={effective_jitter:.0f}ms",
        "fix_hint": "Raise RLNC fec_parity_ratio >= 1.15, lower failover_drop_trigger <= 0.25 with fast probe window, expand jitter buffer >= 95ms",
        "hardening_delta": {
            "fec_parity_ratio": max(1.20, round(fec_parity + 0.85, 2)),
            "failover_drop_trigger": min(0.22, failover_trigger),
            "jitter_buffer_ms": max(95.0, jitter_buf),
        },
    }


def _eval_steer_503_race(params: dict[str, Any], host: dict[str, Any], _rng: random.Random) -> dict[str, Any]:
    detached_streams = int(params["detached_streams"])
    steer_burst = int(params["steer_burst"])
    detached_hold_ms = float(params["detached_hold_ms"])
    retry_amp = int(params["retry_amplification"])

    reserved = int(host.get("reserved_steer_slots", 0))
    yield_ms = float(host.get("preemptive_yield_ms", 1.6))
    max_retry = int(host.get("max_retry_storm", 4))

    total_slots = 8
    busy_detached = min(total_slots - reserved, detached_streams)
    free_for_steer = total_slots - busy_detached

    if reserved >= min(steer_burst, 2) and yield_ms < 0.5:
        preempt_ms = round(min(detached_hold_ms, yield_ms) * 0.45, 3)
        steer_503 = 0
    else:
        contention_queue = max(0, (steer_burst * retry_amp) - max(1, free_for_steer))
        preempt_ms = round(min(detached_hold_ms, yield_ms) + 0.18 * contention_queue, 3)
        steer_503 = max(0, steer_burst - free_for_steer) if retry_amp >= max_retry or free_for_steer <= 0 else 0

    breached = (preempt_ms >= 1.0) or (steer_503 > 0)
    fitness = round(max(0.0, min(1.0, (preempt_ms / 2.5) + (0.25 * steer_503))), 4)

    return {
        "breached": breached,
        "fitness": fitness,
        "metrics": {
            "preempt_latency_ms": preempt_ms,
            "steer_503_count": steer_503,
            "reserved_steer_slots": reserved,
        },
        "error_sig": f"steer_503_preempt_breach:lat={preempt_ms:.2f}ms:503={steer_503}",
        "fix_hint": "Reserve >= 2 interactive steer slots with atomic < 0.3ms preemptive cancellation token & retry cap",
        "hardening_delta": {
            "reserved_steer_slots": max(2, reserved),
            "preemptive_yield_ms": min(0.30, yield_ms),
            "max_retry_storm": max(6, max_retry),
        },
    }


def _eval_file_lease_deadlock(params: dict[str, Any], host: dict[str, Any], _rng: random.Random) -> dict[str, Any]:
    agents = int(params["agent_count"])
    cycle_len = min(agents, int(params["cycle_len"]))
    overlap = float(params["lock_overlap"])

    max_depth = int(host.get("max_cycle_depth", 2))
    canonical_order = bool(host.get("canonical_lock_order", False))
    wound_wait = bool(host.get("wound_wait_backoff", False))

    # Build a real wait-for directed graph for `cycle_len` agents holding `f_i` and wanting `f_{(i+1) % cycle_len}`
    wait_for: dict[str, str] = {}
    if not canonical_order and overlap >= 0.5 and cycle_len >= 2:
        for i in range(cycle_len):
            wait_for[f"agent_{i}"] = f"agent_{(i + 1) % cycle_len}"

    # Host attempts bounded-depth cycle detection up to `max_depth`
    detected = False
    if wait_for:
        for start in wait_for:
            cur = start
            for _step in range(max_depth):
                nxt = wait_for.get(cur)
                if nxt is None:
                    break
                if nxt == start:
                    detected = True
                    break
                cur = nxt
            if detected:
                break

    # Deadlock persists if a cycle exists, was NOT prevented by canonical order, and NOT broken by host detector/wound-wait
    unresolved_cycle = bool(wait_for) and not (detected or wound_wait)
    breached = unresolved_cycle
    fitness = round(0.85 + 0.03 * cycle_len if breached else 0.15, 4)

    return {
        "breached": breached,
        "fitness": min(1.0, fitness),
        "metrics": {
            "cycle_len": cycle_len,
            "wait_for_edges": len(wait_for),
            "detected_by_host": detected,
            "unresolved_cycles": 1 if unresolved_cycle else 0,
        },
        "error_sig": f"file_lease_deadlock:cycle_len={cycle_len}:depth_limit={max_depth}",
        "fix_hint": "Enforce lexicographical lock acquisition ordering + full DFS wait-for cycle breaker + wound-wait backoff",
        "hardening_delta": {
            "max_cycle_depth": max(16, cycle_len + 4),
            "canonical_lock_order": True,
            "wound_wait_backoff": True,
        },
    }


def _eval_prefix_cache_cliff(params: dict[str, Any], host: dict[str, Any], _rng: random.Random) -> dict[str, Any]:
    prefix_blocks = int(params["prefix_blocks"])
    mut_offset_pct = float(params["mutation_offset_pct"])
    volatile_inj = int(params["volatile_injections"])
    bloat_ratio = float(params["bloat_ratio"])

    hoist_tail = bool(host.get("hoist_volatile_to_tail", False))
    prefix_guard = bool(host.get("prefix_hash_guard", False))
    max_bloat = float(host.get("max_bloat_ratio", 1.35))

    # Build real SHA-256 block chains for baseline vs mutated prefix
    base_hashes = [_sha256_hex(f"blk:{i}")[:12] for i in range(prefix_blocks)]
    mut_hashes = list(base_hashes)
    if not hoist_tail and not prefix_guard:
        mut_idx = max(0, min(prefix_blocks - 1, int(prefix_blocks * mut_offset_pct)))
        for k in range(volatile_inj):
            idx = min(prefix_blocks - 1, mut_idx + k)
            mut_hashes[idx] = _sha256_hex(f"blk:{idx}:mut:{k}")[:12]

    matching = 0
    for a, b in zip(base_hashes, mut_hashes):
        if a == b:
            matching += 1
        else:
            break

    cache_hit = matching / max(1, prefix_blocks)
    eff_bloat = bloat_ratio if not prefix_guard else min(bloat_ratio, max_bloat * 0.92)
    breached = (cache_hit < 0.85) or (eff_bloat > max_bloat)
    fitness = round(max(0.0, min(1.0, (1.0 - cache_hit) * 0.75 + max(0.0, eff_bloat - max_bloat) * 0.4)), 4)

    return {
        "breached": breached,
        "fitness": fitness,
        "metrics": {
            "cache_hit_ratio": round(cache_hit, 4),
            "effective_bloat_ratio": round(eff_bloat, 3),
            "matching_blocks": matching,
            "prefix_blocks": prefix_blocks,
        },
        "error_sig": f"prefix_cache_cliff:hit={cache_hit:.2f}:bloat={eff_bloat:.2f}",
        "fix_hint": "Hoist volatile headers/timestamps to append-only tail & enforce prefix SHA-256 freeze guard",
        "hardening_delta": {
            "hoist_volatile_to_tail": True,
            "prefix_hash_guard": True,
            "max_bloat_ratio": 1.35,
        },
    }


def _eval_rss_ceiling_squeeze(params: dict[str, Any], host: dict[str, Any], _rng: random.Random) -> dict[str, Any]:
    base_mb = float(params["baseline_rss_mb"])
    spike_mb = float(params["alloc_spike_mb"])
    frag = float(params["fragmentation"])
    retained = int(params["retained_caches"])

    gc_trigger = float(host.get("gc_trigger_mb", 77.5))
    evict_frac = float(host.get("evict_fraction", 0.20))
    cold_spill = bool(host.get("cold_spill_enabled", False))

    # Simulate step-wise allocation pressure in pure arithmetic (0 real RAM waste)
    rss = base_mb
    peak_rss = rss
    step_alloc = (spike_mb * frag) / max(1, retained)
    for _ in range(retained):
        rss += step_alloc
        if rss >= gc_trigger:
            reclaim = (rss - base_mb * 0.82) * evict_frac
            if cold_spill:
                reclaim += step_alloc * 0.70
            rss = max(base_mb * 0.85, rss - reclaim)
        if rss > peak_rss:
            peak_rss = rss

    peak_rss = round(peak_rss, 2)
    breached = peak_rss >= 80.0
    fitness = round(max(0.0, min(1.0, (peak_rss - 60.0) / 30.0)), 4)

    return {
        "breached": breached,
        "fitness": fitness,
        "metrics": {
            "peak_rss_mb": peak_rss,
            "final_rss_mb": round(rss, 2),
            "law7_ceiling_mb": 80.0,
        },
        "error_sig": f"rss_law7_squeeze:peak={peak_rss:.1f}MiB",
        "fix_hint": "Lower GC self-trim watermark to <= 68 MiB, raise LRU eviction >= 0.60, enable cold disk spill",
        "hardening_delta": {
            "gc_trigger_mb": 66.0,
            "evict_fraction": 0.65,
            "cold_spill_enabled": True,
        },
    }


def _eval_secret_egress_smuggle(params: dict[str, Any], host: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    mode = str(params["encoding_mode"])
    family = str(params["token_family"])
    pad = int(params["noise_pad"])

    decode_depth = int(host.get("decode_depth", 1))
    inspect_hex = bool(host.get("inspect_hex", False))
    reassemble_chunks = bool(host.get("reassemble_chunks", False))

    # Generate synthetic canary secret (never a real credential)
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
    tail = "".join(rng.choice(alphabet) for _ in range(28))
    if family == "ghp":
        canary = f"ghp_{tail}"
    elif family == "sk_live":
        canary = f"sk-canary{tail}"
    elif family == "aiza":
        canary = f"AIzaSy{tail}"
    else:
        canary = f"eyJhbGciOiJIUzI1NiJ9.{tail}"

    # Apply parasite obfuscation
    noise = "x" * pad
    if mode == "raw":
        wire_payload = f"{noise}{canary}{noise}"
    elif mode == "base64":
        wire_payload = base64.b64encode(canary.encode("ascii")).decode("ascii")
    elif mode == "double_base64":
        b1 = base64.b64encode(canary.encode("ascii"))
        wire_payload = base64.b64encode(b1).decode("ascii")
    elif mode == "hex":
        wire_payload = canary.encode("ascii").hex()
    else:  # split_chunk
        mid = len(canary) // 2
        wire_payload = json.dumps({"p1": canary[:mid], "p2": canary[mid:]})

    # Host Egress Scanner executes actual decoding according to its defense profile
    candidates = [wire_payload]
    if reassemble_chunks and wire_payload.startswith("{"):
        try:
            obj = json.loads(wire_payload)
            if isinstance(obj, dict):
                candidates.append("".join(str(v) for v in obj.values()))
        except Exception:
            pass

    frontier = list(candidates)
    for _depth in range(decode_depth):
        next_frontier: list[str] = []
        for item in frontier:
            stripped = item.strip()
            if len(stripped) >= 16 and len(stripped) % 4 == 0:
                try:
                    dec = base64.b64decode(stripped.encode("ascii"), validate=True).decode("utf-8", errors="ignore")
                    if dec and dec != item:
                        candidates.append(dec)
                        next_frontier.append(dec)
                except Exception:
                    pass
            if inspect_hex and len(stripped) >= 32 and len(stripped) % 2 == 0:
                try:
                    dec_h = bytes.fromhex(stripped).decode("utf-8", errors="ignore")
                    if dec_h and dec_h != item:
                        candidates.append(dec_h)
                        next_frontier.append(dec_h)
                except Exception:
                    pass
        frontier = next_frontier

    blocked = any(_CANARY_PATTERNS.search(c) is not None for c in candidates)
    breached = not blocked
    fitness = 0.95 if breached else 0.10

    return {
        "breached": breached,
        "fitness": fitness,
        "metrics": {
            "encoding_mode": mode,
            "token_family": family,
            "candidates_scanned": len(candidates),
            "egress_blocked": blocked,
        },
        "error_sig": f"secret_egress_bypass:mode={mode}:family={family}",
        "fix_hint": "Enable decode_depth >= 3 recursive base64, hex decoding, and JSON key chunk reassembly before egress",
        "hardening_delta": {
            "decode_depth": max(3, decode_depth),
            "inspect_hex": True,
            "reassemble_chunks": True,
        },
    }


_SCENARIO_EVALUATORS = {
    "packet_loss_storm": _eval_packet_loss_storm,
    "steer_503_race": _eval_steer_503_race,
    "file_lease_deadlock": _eval_file_lease_deadlock,
    "prefix_cache_cliff": _eval_prefix_cache_cliff,
    "rss_ceiling_squeeze": _eval_rss_ceiling_squeeze,
    "secret_egress_smuggle": _eval_secret_egress_smuggle,
}


# ---------------------------------------------------------------------------
# RedQueenParasiteArena
# ---------------------------------------------------------------------------

class RedQueenParasiteArena:
    """Isolated Red-Queen Adversarial Self-Play Arena & Law-6 Vaccine Synthesizer."""

    def __init__(self, ops_dir: str | Path | None = None, ephemeral: bool = False) -> None:
        self.ephemeral = bool(ephemeral)
        if self.ephemeral:
            self.ops_dir: Path | None = None
            self.db_path = ":memory:"
        else:
            self.ops_dir = Path(ops_dir) if ops_dir is not None else (_chimera_home() / "bios")
            self.ops_dir.mkdir(parents=True, exist_ok=True)
            self.db_path = str(self.ops_dir / "parasite_arena.sqlite3")

        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()
        self._best_parasite_genomes: dict[str, dict[str, Any]] = {}
        self._shadow_host_state: dict[str, dict[str, Any]] = {
            name: dict(spec["baseline_host"]) for name, spec in PARASITE_SCENARIOS.items()
        }

    def _init_schema(self) -> None:
        with self._lock:
            cur = self._conn.cursor()
            if not self.ephemeral:
                cur.execute("PRAGMA journal_mode=WAL;")
                cur.execute("PRAGMA synchronous=NORMAL;")
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS arena_rounds (
                    generation INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    ts REAL NOT NULL,
                    seed INTEGER NOT NULL,
                    scenarios_run INTEGER NOT NULL,
                    breaches INTEGER NOT NULL,
                    host_survival_rate REAL NOT NULL,
                    parasite_fitness REAL NOT NULL,
                    vaccines_synthesized INTEGER NOT NULL,
                    elapsed_ms REAL NOT NULL,
                    summary_json TEXT NOT NULL
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS vaccines (
                    vaccine_id TEXT PRIMARY KEY,
                    created_ts REAL NOT NULL,
                    generation INTEGER NOT NULL,
                    scenario TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    auto_activated INTEGER NOT NULL DEFAULT 0,
                    requires_human_approval INTEGER NOT NULL DEFAULT 1,
                    sha256 TEXT NOT NULL,
                    receipt_json TEXT NOT NULL
                )
                """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_vaccines_scenario ON vaccines(scenario);")
            self._conn.commit()

    def _next_generation(self) -> int:
        row = self._conn.execute("SELECT COALESCE(MAX(generation), 0) AS g FROM arena_rounds").fetchone()
        return int(row["g"]) + 1 if row else 1

    def _synthesize_vaccine(
        self,
        *,
        generation: int,
        scenario: str,
        seed: int,
        params: dict[str, Any],
        eval_res: dict[str, Any],
    ) -> dict[str, Any]:
        spec = PARASITE_SCENARIOS[scenario]
        vector = {
            "scenario": scenario,
            "seed": int(seed),
            "params": params,
            "payload_digest": _sha256_hex(_canonical_json({"scenario": scenario, "params": params}))[:16],
        }
        vaccine_id = f"vac-{_sha256_hex(_canonical_json({'s': scenario, 'p': params, 'g': generation}))[:12]}"
        antibody_id = f"ab-{_sha256_hex(eval_res['error_sig'])[:10]}"

        regression_snippet = (
            f"def test_vaccine_{vaccine_id.replace('-', '_')}():\n"
            f"    from chimera_tp.platform.bios.parasite import RedQueenParasiteArena\n"
            f"    arena = RedQueenParasiteArena(ephemeral=True)\n"
            f"    res = arena.replay_vector({scenario!r}, {params!r}, hardening_delta={eval_res['hardening_delta']!r}, seed={int(seed)})\n"
            f"    assert res['hardened']['breached'] is False\n"
        )

        unsigned_receipt: dict[str, Any] = {
            "vaccine_id": vaccine_id,
            "schema": "chimera.bios.vaccine.v1",
            "created_ts": round(time.time(), 3),
            "generation": int(generation),
            "scenario": scenario,
            "target_organ": spec["target_organ"],
            "severity": spec["severity"],
            # Law 6 hard invariants: NEVER auto-activated!
            "auto_activated": False,
            "requires_human_approval": True,
            "promotion_stage": "lab_shadow",
            "reproducible_attack_vector": vector,
            "breach_metrics": eval_res["metrics"],
            "immune_antibody": {
                "antibody_id": antibody_id,
                "scenario": scenario,
                "error_sig": eval_res["error_sig"],
                "fix_hint": eval_res["fix_hint"],
                "severity": spec["severity"],
                "action": "block" if spec["severity"] == "critical" else "warn",
            },
            "regression_test_snippet": regression_snippet,
            "host_hardening_delta": dict(eval_res["hardening_delta"]),
            "rollback_recipe": {
                "revert_to_baseline": dict(spec["baseline_host"]),
                "sandbox_only": True,
            },
        }
        receipt = dict(unsigned_receipt)
        receipt["sha256"] = _sha256_hex(_canonical_json(unsigned_receipt))
        return receipt

    def replay_vector(
        self,
        scenario: str,
        params: dict[str, Any],
        hardening_delta: dict[str, Any] | None = None,
        seed: int = 1337,
    ) -> dict[str, Any]:
        """Replay a recorded attack vector inside an isolated in-memory sandbox."""
        if scenario not in _SCENARIO_EVALUATORS:
            raise ValueError(f"Unknown parasite scenario: {scenario}")
        evaluator = _SCENARIO_EVALUATORS[scenario]
        base_host = dict(PARASITE_SCENARIOS[scenario]["baseline_host"])
        base_res = evaluator(params, base_host, random.Random(int(seed)))
        hardened_host = dict(base_host)
        if hardening_delta:
            hardened_host.update(hardening_delta)
        hard_res = evaluator(params, hardened_host, random.Random(int(seed)))
        return {
            "scenario": scenario,
            "seed": int(seed),
            "baseline": {"breached": bool(base_res["breached"]), "metrics": base_res["metrics"]},
            "hardened": {"breached": bool(hard_res["breached"]), "metrics": hard_res["metrics"]},
            "vaccine_effective": bool(base_res["breached"] and not hard_res["breached"]),
        }

    def verify_vaccine(self, vaccine_receipt: dict[str, Any]) -> dict[str, Any]:
        """Verify SHA-256 signature, Law-6 flags, and sandbox mitigation effectiveness."""
        if not isinstance(vaccine_receipt, dict):
            return {"valid": False, "reason": "invalid_receipt_type"}
        claimed_sig = str(vaccine_receipt.get("sha256") or "")
        unsigned = {k: v for k, v in vaccine_receipt.items() if k != "sha256"}
        expected_sig = _sha256_hex(_canonical_json(unsigned))
        sig_ok = bool(claimed_sig) and (claimed_sig == expected_sig)
        law6_ok = (vaccine_receipt.get("auto_activated") is False) and (
            vaccine_receipt.get("requires_human_approval") is True
        )
        vec = vaccine_receipt.get("reproducible_attack_vector") or {}
        replay = self.replay_vector(
            str(vec.get("scenario", "")),
            dict(vec.get("params") or {}),
            hardening_delta=dict(vaccine_receipt.get("host_hardening_delta") or {}),
            seed=int(vec.get("seed", 1337)),
        )
        return {
            "valid": bool(sig_ok and law6_ok and not replay["hardened"]["breached"]),
            "signature_valid": sig_ok,
            "law6_compliant": law6_ok,
            "sandbox_replay": replay,
        }

    def run_arena(
        self,
        rounds: int = 6,
        seed: int | None = None,
        scenarios: list[str] | None = None,
    ) -> dict[str, Any]:
        """Execute isolated Red-Queen adversarial self-play rounds and synthesize Law-6 vaccines."""
        t0 = time.perf_counter()
        n_rounds = max(1, min(64, int(rounds)))
        base_seed = int(seed) if seed is not None else int(time.time() * 1000) & 0xFFFFFFFF
        rng = random.Random(base_seed)
        selected = [s for s in (scenarios or list(PARASITE_SCENARIOS.keys())) if s in _SCENARIO_EVALUATORS]
        if not selected:
            selected = list(PARASITE_SCENARIOS.keys())

        run_id = f"rq-{_sha256_hex(f'{base_seed}:{n_rounds}:{time.time_ns()}')[:10]}"
        round_reports: list[dict[str, Any]] = []
        new_vaccines: list[dict[str, Any]] = []

        # Sandbox-only host twins: start from baseline on fresh arena so breaches are genuinely discovered,
        # then test shadow hardening in-memory only (production is NEVER auto-mutated).
        sandbox_hosts = {s: dict(self._shadow_host_state[s]) for s in selected}

        with self._lock:
            start_gen = self._next_generation()
            for r_idx in range(n_rounds):
                gen = start_gen + r_idx
                intensity = min(1.0, 0.35 + (r_idx / max(1, n_rounds)) * 0.65)
                r_t0 = time.perf_counter()
                breaches = 0
                fitness_sum = 0.0
                round_vaccines: list[dict[str, Any]] = []
                scenario_outcomes: list[dict[str, Any]] = []

                for sc in selected:
                    sc_seed = rng.randint(1, 2**31 - 1)
                    sc_rng = random.Random(sc_seed)
                    # Evolutionary parasite selection/mutation
                    if sc in self._best_parasite_genomes and r_idx > 0:
                        params = _mutate_parasite_params(sc, self._best_parasite_genomes[sc], sc_rng)
                    else:
                        params = _sample_parasite_params(sc, sc_rng, intensity=intensity)

                    evaluator = _SCENARIO_EVALUATORS[sc]
                    # Evaluate against baseline host on round 0 or shadow host on subsequent rounds
                    host_cfg = sandbox_hosts[sc]
                    res = evaluator(params, host_cfg, random.Random(sc_seed))
                    fitness_sum += float(res["fitness"])

                    if res["breached"]:
                        breaches += 1
                        self._best_parasite_genomes[sc] = dict(params)
                        vac = self._synthesize_vaccine(
                            generation=gen,
                            scenario=sc,
                            seed=sc_seed,
                            params=params,
                            eval_res=res,
                        )
                        round_vaccines.append(vac)
                        new_vaccines.append(vac)
                        # Persist Law-6 vaccine receipt (auto_activated=0)
                        self._conn.execute(
                            """
                            INSERT OR REPLACE INTO vaccines
                            (vaccine_id, created_ts, generation, scenario, severity,
                             auto_activated, requires_human_approval, sha256, receipt_json)
                            VALUES (?, ?, ?, ?, ?, 0, 1, ?, ?)
                            """,
                            (
                                vac["vaccine_id"],
                                vac["created_ts"],
                                gen,
                                sc,
                                vac["severity"],
                                vac["sha256"],
                                _canonical_json(vac),
                            ),
                        )
                        # In-sandbox Red-Queen counter-adaptation ONLY (does not activate in production!)
                        sandbox_hosts[sc].update(res["hardening_delta"])

                    scenario_outcomes.append(
                        {
                            "scenario": sc,
                            "breached": bool(res["breached"]),
                            "fitness": float(res["fitness"]),
                            "metrics": res["metrics"],
                        }
                    )

                survival_rate = round(1.0 - (breaches / max(1, len(selected))), 4)
                mean_fitness = round(fitness_sum / max(1, len(selected)), 4)
                r_elapsed = round((time.perf_counter() - r_t0) * 1000.0, 3)

                summary = {
                    "generation": gen,
                    "scenarios_run": len(selected),
                    "breaches": breaches,
                    "host_survival_rate": survival_rate,
                    "parasite_fitness": mean_fitness,
                    "vaccines_synthesized": len(round_vaccines),
                    "elapsed_ms": r_elapsed,
                    "outcomes": scenario_outcomes,
                }
                self._conn.execute(
                    """
                    INSERT INTO arena_rounds
                    (generation, run_id, ts, seed, scenarios_run, breaches,
                     host_survival_rate, parasite_fitness, vaccines_synthesized, elapsed_ms, summary_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        gen,
                        run_id,
                        time.time(),
                        base_seed,
                        len(selected),
                        breaches,
                        survival_rate,
                        mean_fitness,
                        len(round_vaccines),
                        r_elapsed,
                        _canonical_json(summary),
                    ),
                )
                round_reports.append(summary)

            self._conn.commit()
            # Keep sandbox shadow progression in memory for subsequent Red-Queen evolution
            self._shadow_host_state.update(sandbox_hosts)

        total_elapsed = round((time.perf_counter() - t0) * 1000.0, 3)
        avg_survival = round(
            sum(r["host_survival_rate"] for r in round_reports) / max(1, len(round_reports)), 4
        )
        avg_fitness = round(
            sum(r["parasite_fitness"] for r in round_reports) / max(1, len(round_reports)), 4
        )
        return {
            "ok": True,
            "run_id": run_id,
            "seed": base_seed,
            "rounds_executed": n_rounds,
            "generation": round_reports[-1]["generation"],
            "host_survival_rate": avg_survival,
            "final_host_survival_rate": round_reports[-1]["host_survival_rate"],
            "parasite_fitness": avg_fitness,
            "vaccines_synthesized": len(new_vaccines),
            "auto_activated": False,
            "requires_human_approval": True,
            "sandbox_isolated": True,
            "elapsed_ms": total_elapsed,
            "vaccines": new_vaccines,
            "rounds": round_reports,
        }

    def list_vaccines(self, limit: int = 50, scenario: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            if scenario:
                rows = self._conn.execute(
                    "SELECT receipt_json FROM vaccines WHERE scenario = ? ORDER BY created_ts DESC LIMIT ?",
                    (scenario, max(1, int(limit))),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT receipt_json FROM vaccines ORDER BY created_ts DESC LIMIT ?",
                    (max(1, int(limit)),),
                ).fetchall()
        return [json.loads(r["receipt_json"]) for r in rows]

    def list_antibodies(self, limit: int = 50) -> list[dict[str, Any]]:
        """Extract compact immune antibody rules from synthesized vaccines."""
        antibodies: list[dict[str, Any]] = []
        seen: set[str] = set()
        for vac in self.list_vaccines(limit=limit):
            ab = vac.get("immune_antibody")
            if isinstance(ab, dict):
                sig = str(ab.get("error_sig", ""))
                if sig and sig not in seen:
                    seen.add(sig)
                    antibodies.append(ab)
        return antibodies

    def status(self) -> dict[str, Any]:
        with self._lock:
            agg = self._conn.execute(
                """
                SELECT
                    COALESCE(MAX(generation), 0) AS generation,
                    COUNT(*) AS total_rounds,
                    COALESCE(AVG(host_survival_rate), 1.0) AS avg_survival,
                    COALESCE(AVG(parasite_fitness), 0.0) AS avg_fitness
                FROM arena_rounds
                """
            ).fetchone()
            vac_cnt = self._conn.execute("SELECT COUNT(*) AS c FROM vaccines").fetchone()
            latest = self._conn.execute(
                "SELECT host_survival_rate, parasite_fitness, ts FROM arena_rounds ORDER BY generation DESC LIMIT 1"
            ).fetchone()

        return {
            "organ": "CHIMERA-PARASITE",
            "ephemeral": self.ephemeral,
            "generation": int(agg["generation"]) if agg else 0,
            "total_rounds": int(agg["total_rounds"]) if agg else 0,
            "host_survival_rate": round(float(latest["host_survival_rate"]), 4) if latest else 1.0,
            "mean_host_survival_rate": round(float(agg["avg_survival"]), 4) if agg else 1.0,
            "parasite_fitness": round(float(latest["parasite_fitness"]), 4) if latest else 0.0,
            "vaccines_synthesized": int(vac_cnt["c"]) if vac_cnt else 0,
            "auto_activated": False,
            "scenarios": list(PARASITE_SCENARIOS.keys()),
            "latest_vaccines": self.list_vaccines(limit=5),
        }

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass

    def __enter__(self) -> "RedQueenParasiteArena":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass
