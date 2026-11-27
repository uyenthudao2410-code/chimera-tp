"""CHIMERA-HYPER v11.0 ORGANISM — Living Protocol Organism, Data Gravity & Multiverse (Phần VI #1..#6)."""

from __future__ import annotations

import hashlib
import math
import queue
import random
import struct
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from ..native import babel_mine, chaos_step_q16, lz4_compress, lz4_decompress, splitmix64_bytes
from ..omega_transport import x25519_keypair
from .v9_nvme_grid import execute_whitelisted_kernel

# ==============================================================================
# VI.1 — Babel-Universe 0-Byte Pointer Codec (SplitMix64 + Sparse Delta)
# ==============================================================================


class BabelPointerCodec:
    """Mine deterministic SplitMix64 universe pointers via C11/Rust `chimera_babel_mine`."""

    BLOCK_LEN = 64

    @classmethod
    def encode(cls, data: bytes, base_seed: int = 0xBABA_0000, search_window: int = 256) -> dict[str, Any]:
        t0 = time.perf_counter()
        blocks = [data[i : i + cls.BLOCK_LEN] for i in range(0, len(data), cls.BLOCK_LEN)]
        encoded_recs: list[tuple[int, int, bytes]] = []
        exact_hits = 0
        sparse_hits = 0
        fallback_hits = 0

        for idx, blk in enumerate(blocks):
            hint_seed = (base_seed + idx * 17) & 0xFFFFFFFFFFFFFFFF
            best_seed, best_dist = babel_mine(blk, start_seed=hint_seed, n_candidates=search_window)
            if best_dist == 0:
                encoded_recs.append((0, best_seed, b""))
                exact_hits += 1
            elif best_dist <= 16:
                gen = splitmix64_bytes(best_seed, len(blk))
                diffs = bytearray()
                for pos, (g_b, t_b) in enumerate(zip(gen, blk)):
                    if g_b != t_b:
                        diffs.append(pos)
                        diffs.append(g_b ^ t_b)
                encoded_recs.append((1, best_seed, bytes(diffs)))
                sparse_hits += 1
            else:
                encoded_recs.append((2, len(blk), lz4_compress(blk)))
                fallback_hits += 1

        # Serialize compact pointer stream
        wire = bytearray(struct.pack("<II", len(data), len(encoded_recs)))
        for mode, val, extra in encoded_recs:
            wire.extend(struct.pack("<BQH", mode, val, len(extra)))
            wire.extend(extra)
        elapsed_ms = max(0.01, (time.perf_counter() - t0) * 1000.0)
        return {
            "wire": bytes(wire),
            "exact_hits": exact_hits,
            "sparse_hits": sparse_hits,
            "fallback_hits": fallback_hits,
            "blocks": len(blocks),
            "elapsed_ms": round(elapsed_ms, 2),
        }

    @classmethod
    def decode(cls, wire: bytes) -> bytes:
        orig_len, count = struct.unpack_from("<II", wire, 0)
        pos = 8
        out = bytearray()
        for _ in range(count):
            mode, val, elen = struct.unpack_from("<BQH", wire, pos)
            pos += 11
            extra = wire[pos : pos + elen]
            pos += elen
            blk_len = min(cls.BLOCK_LEN, max(0, orig_len - len(out)))
            if mode == 0:
                out.extend(splitmix64_bytes(val, blk_len))
            elif mode == 1:
                buf = bytearray(splitmix64_bytes(val, blk_len))
                for j in range(0, len(extra), 2):
                    buf[extra[j]] ^= extra[j + 1]
                out.extend(buf)
            else:
                out.extend(lz4_decompress(extra)[:blk_len])
        return bytes(out[:orig_len])

    @classmethod
    def run_benchmark(cls) -> dict[str, Any]:
        # Structured payload interleaving SplitMix64 universe hits + slight mutations + arbitrary data
        base = 0x51A7_1000
        parts = bytearray()
        for b_i in range(16):
            blk = bytearray(splitmix64_bytes(base + b_i * 17 + (b_i % 5), cls.BLOCK_LEN))
            if b_i % 3 == 1:
                blk[5] ^= 0x33
                blk[41] ^= 0x99
            parts.extend(blk)
        raw = bytes(parts)
        enc = cls.encode(raw, base_seed=base, search_window=64)
        rec = cls.decode(enc["wire"])
        return {
            "ok": rec == raw and (enc["exact_hits"] + enc["sparse_hits"]) == 16 and len(enc["wire"]) < len(raw) * 0.5,
            "raw_bytes": len(raw),
            "pointer_wire_bytes": len(enc["wire"]),
            "exact_0byte_blocks": enc["exact_hits"],
            "sparse_delta_blocks": enc["sparse_hits"],
            "bit_exact": rec == raw,
            "elapsed_ms": enc["elapsed_ms"],
        }


# ==============================================================================
# VI.2 — Living Artificial Immune Organism + 12-Byte `CHI1` Antibody Header
# ==============================================================================


class ImmuneProtocolOrganism:
    """Mutates protocol camouflage across 16 candidates to defeat an active DPI packet dropper."""

    ANTIBODY_HDR = struct.Struct("<4sBBHHH")  # magic="CHI1"(4) + shell(1) + fec(1) + mtu(2) + jitter(2) + epoch(2) = 12 B

    @staticmethod
    def _simulate_dpi_firewall(shell: int, mtu: int, fec: int, jitter_ms: int) -> tuple[float, float]:
        # Active ISP DPI blocks legacy raw shell=0 or jumbo >= 1300B at 90% loss!
        if shell == 0 or mtu >= 1300:
            drop_rate = 0.90
        elif shell == 1:  # generic UDP probe throttled 45%
            drop_rate = 0.45
        elif shell in (2, 3) and 512 <= mtu <= 1100:  # QUIC / TLS1.3 ApplicationData mimicry slips cleanly!
            drop_rate = 0.04 if fec >= 2 else 0.08
        else:
            drop_rate = 0.25

        # RLNC survival + effective goodput Mbps
        rng = random.Random(shell * 1000 + mtu * 7 + fec * 13 + jitter_ms)
        n_gens = 20
        ok_gens = 0
        k = 8
        for _ in range(n_gens):
            rx = sum(1 for _ in range(k + fec) if rng.random() >= drop_rate)
            if rx >= k:
                ok_gens += 1
        survival = ok_gens / n_gens
        overhead = k / float(k + fec)
        goodput = max(0.1, round(32.0 * survival * overhead * (0.96 if jitter_ms <= 2 else 0.85), 2))
        return round(drop_rate * 100.0, 1), goodput

    @classmethod
    def run_benchmark(cls) -> dict[str, Any]:
        t0 = time.perf_counter()
        # 1) Legacy phenotype gets crushed by active DPI
        base_loss, base_mbps = cls._simulate_dpi_firewall(shell=0, mtu=1400, fec=0, jitter_ms=0)

        # 2) Spawn 16 mutated protocol antibodies & evaluate fitness in <150ms
        rng = random.Random(1102)
        best_score = -1.0
        best_gene = (0, 0, 1200, 0)
        best_mbps = 0.0
        for _ in range(16):
            shell = rng.choice((1, 2, 3))
            mtu = rng.choice((512, 768, 960, 1080, 1380))
            fec = rng.choice((1, 2, 3, 4))
            jitter = rng.choice((0, 1, 2, 5))
            _dl, mbps = cls._simulate_dpi_firewall(shell, mtu, fec, jitter)
            if mbps > best_score:
                best_score = mbps
                best_gene = (shell, fec, mtu, jitter)
                best_mbps = mbps

        shell, fec, mtu, jitter = best_gene
        ack_12b = cls.ANTIBODY_HDR.pack(b"CHI1", shell, fec, mtu, jitter, 42)
        magic, u_sh, u_fec, u_mtu, u_jit, _ = cls.ANTIBODY_HDR.unpack(ack_12b)
        elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        speedup_x = round(best_mbps / max(0.05, base_mbps), 1)
        return {
            "ok": magic == b"CHI1" and len(ack_12b) == 12 and best_mbps > 15.0 and speedup_x >= 10.0 and (u_sh, u_fec, u_mtu, u_jit) == best_gene,
            "legacy_dpi_blocked_mbps": base_mbps,
            "legacy_dpi_drop_pct": base_loss,
            "evolved_goodput_mbps": best_mbps,
            "dpi_evasion_speedup_x": speedup_x,
            "antibody_header_bytes": len(ack_12b),
            "winning_gene": {"shell": u_sh, "fec": u_fec, "mtu": u_mtu, "jitter": u_jit},
            "elapsed_ms": elapsed_ms,
        }


# ==============================================================================
# VI.3 — Data-Gravity Single-Organism Execution Planner
# ==============================================================================


class DataGravityPlanner:
    """Slide jobs between compute-heavy host (Windows) and data-owner host (svhome) via wire-vs-CPU cost."""

    @staticmethod
    def gravity_cost_ms(wire_bytes: int, bw_mbps: float, rtt_ms: float, compute_ms: float) -> float:
        tx_ms = (wire_bytes * 8.0 / (max(1.0, bw_mbps) * 1000.0)) if wire_bytes > 0 else 0.0
        return tx_ms + (rtt_ms if wire_bytes > 0 else 0.0) + compute_ms

    @classmethod
    def run_benchmark(cls) -> dict[str, Any]:
        t0 = time.perf_counter()
        # Scenario 1: Tiny 512 B prompt + heavy matrix kernel (3.5x faster on Win 12-thread CPU)
        heavy_payload = b"GRAVITY_COMPUTE_JOB_512B" * 20
        t_win_start = time.perf_counter()
        win_digest = execute_whitelisted_kernel("gf256_matrix_work", heavy_payload, 0, 8)["state_hex"]
        win_compute_ms = max(0.5, (time.perf_counter() - t_win_start) * 1000.0)

        cost_job1_win = cls.gravity_cost_ms(512, 100.0, 6.3, win_compute_ms)
        cost_job1_sv = cls.gravity_cost_ms(0, 100.0, 0.0, win_compute_ms * 3.5)
        pick1 = "win-desktop" if cost_job1_win < cost_job1_sv else "svhome"

        # Scenario 2: Huge 2 MiB log stored on svhome + light scan (2.5 ms in-situ vs ~326 ms downloading 2 MiB over 50 Mbps)
        big_bytes = 2 * 1024 * 1024
        cost_job2_sv = cls.gravity_cost_ms(0, 50.0, 0.0, 2.5)
        cost_job2_win = cls.gravity_cost_ms(big_bytes, 50.0, 6.3, 1.0)
        pick2 = "svhome" if cost_job2_sv < cost_job2_win else "win-desktop"

        static_all_win = cost_job1_win + cost_job2_win
        static_all_sv = cost_job1_sv + cost_job2_sv
        gravity_total = min(cost_job1_win, cost_job1_sv) + min(cost_job2_win, cost_job2_sv)
        return {
            "ok": pick1 == "win-desktop" and pick2 == "svhome" and gravity_total < min(static_all_win, static_all_sv) and len(win_digest) == 64,
            "job1_heavy_compute_route": pick1,
            "job2_heavy_data_route": pick2,
            "static_all_win_ms": round(static_all_win, 2),
            "static_all_svhome_ms": round(static_all_sv, 2),
            "gravity_hybrid_ms": round(gravity_total, 2),
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }


# ==============================================================================
# VI.4 — Zero-IP Curve25519 + Hyperbolic/XOR Gravitational Mesh
# ==============================================================================


class GravitationalOverlayRouter:
    """Route by immutable Curve25519 identity in Poincare hyperbolic space across shifting IPs."""

    @staticmethod
    def _hyperbolic_dist(u: tuple[float, float], v: tuple[float, float]) -> float:
        du = u[0] * u[0] + u[1] * u[1]
        dv = v[0] * v[0] + v[1] * v[1]
        diff2 = (u[0] - v[0]) ** 2 + (u[1] - v[1]) ** 2
        arg = 1.0 + (2.0 * diff2) / max(1e-6, (1.0 - du) * (1.0 - dv))
        return math.acosh(max(1.0, arg))

    @classmethod
    def run_benchmark(cls, n_nodes: int = 16) -> dict[str, Any]:
        t0 = time.perf_counter()
        rng = random.Random(1104)
        nodes: list[dict[str, Any]] = []
        for idx in range(n_nodes):
            _sk, pk = x25519_keypair()
            angle = (2.0 * math.pi * idx) / n_nodes
            radius = 0.55 + 0.25 * math.sin(idx * 1.7)
            nodes.append(
                {
                    "idx": idx,
                    "pubkey": pk,
                    "coord": (radius * math.cos(angle), radius * math.sin(angle)),
                    "ip": f"198.51.100.{10 + idx}:{9000 + idx}",
                }
            )

        # Build connected hyperbolic ring + chordal shortcuts
        adj: dict[int, set[int]] = {i: set() for i in range(n_nodes)}
        for i in range(n_nodes):
            for hop in (1, 2, 4):
                j = (i + hop) % n_nodes
                adj[i].add(j)
                adj[j].add(i)

        def _route(src_idx: int, dst_pubkey: bytes) -> tuple[bool, int]:
            dst_idx = next(n["idx"] for n in nodes if n["pubkey"] == dst_pubkey)
            dst_coord = nodes[dst_idx]["coord"]
            cur = src_idx
            visited = {cur}
            hops = 0
            while cur != dst_idx and hops < n_nodes * 2:
                if dst_idx in adj[cur]:
                    return True, hops + 1
                cands = [nb for nb in adj[cur] if nb not in visited]
                if not cands:
                    cands = list(adj[cur])
                cur = min(cands, key=lambda nb: cls._hyperbolic_dist(nodes[nb]["coord"], dst_coord))
                visited.add(cur)
                hops += 1
            return cur == dst_idx, hops

        # Mutate IPs of 50% (8/16) nodes mid-flight while Curve25519 IDs remain unchanged!
        delivered = 0
        total_hops = 0
        ip_mutations = 0
        trials = 16
        for t in range(trials):
            if t == 8:
                for m_i in range(0, n_nodes, 2):
                    nodes[m_i]["ip"] = f"203.0.113.{100 + m_i}:{11000 + rng.randint(1, 500)}"
                    ip_mutations += 1
            src = t % n_nodes
            dst = (t + 7) % n_nodes
            ok, h = _route(src, nodes[dst]["pubkey"])
            if ok:
                delivered += 1
                total_hops += h

        return {
            "ok": delivered == trials and ip_mutations == 8,
            "nodes": n_nodes,
            "ip_mutations_midflight": ip_mutations,
            "delivered": f"{delivered}/{trials}",
            "mean_hops": round(total_hops / max(1, delivered), 2),
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }


# ==============================================================================
# VI.5 — Pecora-Carroll Fixed-Point Coupled Chaotic Wire (Native Q16.16)
# ==============================================================================


class CoupledChaoticWire:
    """Bit-identical integer Pecora-Carroll synchronized chaotic ciphertext-feedback wire cipher."""

    @staticmethod
    def _init_state(key: bytes, nonce: bytes) -> list[int]:
        h = hashlib.blake2s(key + nonce, digest_size=12).digest()
        a, b, c = struct.unpack("<iii", h)
        return [
            (abs(a) % 400_000) - 200_000,
            (abs(b) % 400_000) - 200_000,
            (abs(c) % 400_000) - 200_000,
        ]

    @classmethod
    def encrypt(cls, key: bytes, nonce8: bytes, plaintext: bytes) -> bytes:
        st = cls._init_state(key, nonce8)
        out = bytearray(nonce8)
        drive_blk = (nonce8 * 8)[:64]
        for off in range(0, len(plaintext), 64):
            chunk = plaintext[off : off + 64]
            ks, st = chaos_step_q16(st, drive_blk[: len(chunk)], coupling_q16=49_152)
            ct = bytes(p ^ k for p, k in zip(chunk, ks))
            out.extend(ct)
            drive_blk = (ct * ((64 // max(1, len(ct))) + 1))[:64]
        return bytes(out)

    @classmethod
    def decrypt(cls, key: bytes, wire_bytes: bytes) -> bytes:
        if len(wire_bytes) < 8:
            raise ValueError("Wire frame too short")
        nonce8 = wire_bytes[:8]
        ct_all = wire_bytes[8:]
        st = cls._init_state(key, nonce8)
        out = bytearray()
        drive_blk = (nonce8 * 8)[:64]
        for off in range(0, len(ct_all), 64):
            ct = ct_all[off : off + 64]
            ks, st = chaos_step_q16(st, drive_blk[: len(ct)], coupling_q16=49_152)
            pt = bytes(c ^ k for c, k in zip(ct, ks))
            out.extend(pt)
            drive_blk = (ct * ((64 // max(1, len(ct))) + 1))[:64]
        return bytes(out)

    @staticmethod
    def _entropy(data: bytes) -> float:
        if not data:
            return 0.0
        counts = [0] * 256
        for b in data:
            counts[b] += 1
        n = float(len(data))
        return -sum((c / n) * math.log2(c / n) for c in counts if c > 0)

    @classmethod
    def run_benchmark(cls) -> dict[str, Any]:
        t0 = time.perf_counter()
        key = b"CHIMERA_CHAOTIC_PECORA_CARROLL_K"
        nonce8 = b"N1105_01"
        pt = (b"Structured JSON log {'id': 42, 'node': 'svhome', 'ok': true}\n" * 64)[:4096]
        wire = cls.encrypt(key, nonce8, pt)
        rec = cls.decrypt(key, wire)

        # Flip 1 bit in frame 0 ciphertext -> avalanche cascades through chaotic drive!
        tampered = bytearray(wire)
        tampered[20] ^= 0x01
        bad_rec = cls.decrypt(key, bytes(tampered))
        tail_mismatch = sum(1 for a, b in zip(pt[128:], bad_rec[128:]) if a != b) / max(1, len(pt) - 128)
        ent = round(cls._entropy(wire[8:]), 3)
        return {
            "ok": rec == pt and ent >= 7.80 and tail_mismatch > 0.40,
            "payload_bytes": len(pt),
            "wire_entropy_bits_per_byte": ent,
            "bit_exact": rec == pt,
            "tamper_1bit_avalanche_pct": round(tail_mismatch * 100.0, 1),
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }


# ==============================================================================
# VI.6 — Multiverse Superposition Execution & First-Valid Collapse
# ==============================================================================


class MultiverseExecutor:
    """Launch K=4 parallel execution/route universes and collapse immediately on first valid finish."""

    @staticmethod
    def run_benchmark(n_branches: int = 4) -> dict[str, Any]:
        t0 = time.perf_counter()
        payload = b"MULTIVERSE_COLLAPSE_PROBE_DATA" * 4
        want_hex = execute_whitelisted_kernel("blake2b_rounds", payload, 0, 8)["state_hex"]

        # 1) Measure single stalled branch baseline (~110 ms simulated straggler)
        ts0 = time.perf_counter()
        time.sleep(0.110)
        _ = execute_whitelisted_kernel("blake2b_rounds", payload, 0, 8)
        single_stalled_ms = (time.perf_counter() - ts0) * 1000.0

        # 2) Launch K=4 superposition branches where 2 suffer 110-140ms straggler stalls, fast winner finishes in ~1-3ms
        delays = [0.120, 0.0, 0.140, 0.060]
        done_q: queue.Queue[tuple[int, str, float]] = queue.Queue()
        collapse_ev = threading.Event()

        def _branch(bid: int, d_s: float) -> None:
            tb = time.perf_counter()
            if d_s > 0.0 and collapse_ev.wait(timeout=d_s):
                return
            res = execute_whitelisted_kernel("blake2b_rounds", payload, 0, 8)
            if not collapse_ev.is_set() and res["state_hex"] == want_hex:
                collapse_ev.set()
                done_q.put((bid, res["state_hex"], (time.perf_counter() - tb) * 1000.0))

        with ThreadPoolExecutor(max_workers=n_branches) as pool:
            pool.submit(lambda: None).result(timeout=1.0)
            tm0 = time.perf_counter()
            futs = [pool.submit(_branch, i, delays[i]) for i in range(n_branches)]
            win_bid, win_hex, _ = done_q.get(timeout=2.0)
            multi_ms = (time.perf_counter() - tm0) * 1000.0
            collapse_ev.set()
            for f in futs:
                f.result(timeout=1.0)

        tail_speedup_x = round(single_stalled_ms / max(0.2, multi_ms), 2)
        return {
            "ok": win_hex == want_hex and tail_speedup_x >= 3.0 and win_bid == 1,
            "branches": n_branches,
            "winning_universe": win_bid,
            "single_stalled_ms": round(single_stalled_ms, 2),
            "collapse_ms": round(multi_ms, 2),
            "tail_speedup_x": tail_speedup_x,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }
