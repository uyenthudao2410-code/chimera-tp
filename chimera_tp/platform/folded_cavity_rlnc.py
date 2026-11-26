"""Cristae Folded-Cavity Spatially-Coupled GF(256) RLNC: L2-cache (<64 KB) burst-loss wave recovery."""

from __future__ import annotations

import hashlib
import random
import time
from typing import Any

from ..gf256 import EXP as GF_EXP, LOG as GF_LOG, gf_inv, gf_mul


def _gf_row_add_mul(dst: bytearray, src: bytes | bytearray, factor: int) -> None:
    if factor == 0:
        return
    if factor == 1:
        for i in range(len(dst)):
            dst[i] ^= src[i]
        return
    log_f = GF_LOG[factor]
    for i in range(len(dst)):
        v = src[i]
        if v:
            dst[i] ^= GF_EXP[GF_LOG[v] + log_f]


def _gf_row_scale(row: bytearray, factor: int) -> None:
    if factor == 1:
        return
    if factor == 0:
        for i in range(len(row)):
            row[i] = 0
        return
    log_f = GF_LOG[factor]
    for i in range(len(row)):
        v = row[i]
        if v:
            row[i] = GF_EXP[GF_LOG[v] + log_f]


class CristaeFoldedCavityRLNC:
    """Folds small L2-cache chunks into overlapping coupled windows (w=3) for domino-wave recovery under 35% loss."""

    def __init__(self, chunk_size: int = 512, window_w: int = 3) -> None:
        self.chunk_size = max(64, int(chunk_size))
        self.window_w = max(2, min(6, int(window_w)))

    def encode_stream(self, data: bytes, redundancy: float = 0.55, seed: int = 71071) -> dict[str, Any]:
        orig_len = len(data)
        cs = self.chunk_size
        n_src = max(1, (orig_len + cs - 1) // cs)
        padded = data + b"\x00" * (n_src * cs - orig_len)
        src_blocks = [padded[i * cs : (i + 1) * cs] for i in range(n_src)]

        rng = random.Random(seed)
        packets: list[dict[str, Any]] = []
        # 1. Systematic boundary seeds (initiate wave-like Gaussian cascade from both ends)
        for idx in range(n_src):
            packets.append({"id": len(packets), "coeffs": {idx: 1}, "payload": src_blocks[idx], "kind": "sys"})

        # 2. Spatially-coupled folded-cavity parity packets across overlapping sliding windows
        n_par = max(2, int(round(n_src * float(redundancy))))
        for p_idx in range(n_par):
            center = int((p_idx / max(1, n_par - 1)) * max(0, n_src - 1)) if n_par > 1 else 0
            lo = max(0, center - (self.window_w // 2))
            hi = min(n_src, lo + self.window_w)
            lo = max(0, hi - self.window_w)
            coeffs: dict[int, int] = {}
            acc = bytearray(cs)
            for s_idx in range(lo, hi):
                c = rng.randint(1, 255)
                coeffs[s_idx] = c
                _gf_row_add_mul(acc, src_blocks[s_idx], c)
            # Couple boundary fold across ends (closed resonant cavity)
            if p_idx % 3 == 0 and n_src > self.window_w:
                fold_idx = (n_src - 1 - center) % n_src
                if fold_idx not in coeffs:
                    c = rng.randint(1, 255)
                    coeffs[fold_idx] = c
                    _gf_row_add_mul(acc, src_blocks[fold_idx], c)
            packets.append({"id": len(packets), "coeffs": coeffs, "payload": bytes(acc), "kind": "coupled"})

        return {
            "orig_len": orig_len,
            "chunk_size": cs,
            "n_src": n_src,
            "window_w": self.window_w,
            "l2_buffer_bytes": n_src * cs,
            "packets": packets,
        }

    def decode_wave(self, packets: list[dict[str, Any]], n_src: int, orig_len: int, chunk_size: int) -> tuple[bytes | None, dict[str, Any]]:
        """Sparse wave-peeling + banded Gaussian elimination in GF(256)."""
        t0 = time.perf_counter()
        solved: dict[int, bytearray] = {}
        eqs: list[tuple[dict[int, int], bytearray]] = [
            (dict(p["coeffs"]), bytearray(p["payload"])) for p in packets
        ]
        peeled_waves = 0

        # Phase 1: Fast O(N) wave-peeling domino cascade
        changed = True
        while changed and len(solved) < n_src:
            changed = False
            next_eqs: list[tuple[dict[int, int], bytearray]] = []
            for coeffs, pay in eqs:
                for k in list(coeffs.keys()):
                    if k in solved:
                        c = coeffs.pop(k)
                        _gf_row_add_mul(pay, solved[k], c)
                if len(coeffs) == 1:
                    k, c = next(iter(coeffs.items()))
                    if k not in solved:
                        if c != 1:
                            _gf_row_scale(pay, gf_inv(c))
                        solved[k] = pay
                        peeled_waves += 1
                        changed = True
                elif len(coeffs) > 1:
                    next_eqs.append((coeffs, pay))
            eqs = next_eqs

        # Phase 2: Compact GF(256) Gaussian elimination ONLY on remaining unresolved core
        unsolved_cols = [i for i in range(n_src) if i not in solved]
        if unsolved_cols and len(eqs) >= len(unsolved_cols):
            col_map = {c: idx for idx, c in enumerate(unsolved_cols)}
            m = len(unsolved_cols)
            mat: list[tuple[list[int], bytearray]] = []
            for coeffs, pay in eqs:
                row = [0] * m
                for k, v in coeffs.items():
                    if k in col_map:
                        row[col_map[k]] = v
                if any(row):
                    mat.append((row, bytearray(pay)))

            pivots: list[int] = []
            r_idx = 0
            for c_idx in range(m):
                piv = -1
                for rr in range(r_idx, len(mat)):
                    if mat[rr][0][c_idx] != 0:
                        piv = rr
                        break
                if piv == -1:
                    continue
                mat[r_idx], mat[piv] = mat[piv], mat[r_idx]
                inv_p = gf_inv(mat[r_idx][0][c_idx])
                if inv_p != 1:
                    mat[r_idx] = ([gf_mul(x, inv_p) for x in mat[r_idx][0]], mat[r_idx][1])
                    _gf_row_scale(mat[r_idx][1], inv_p)
                for rr in range(len(mat)):
                    if rr != r_idx and mat[rr][0][c_idx] != 0:
                        fac = mat[rr][0][c_idx]
                        r0 = mat[r_idx][0]
                        r1 = mat[rr][0]
                        for cc in range(c_idx, m):
                            if r0[cc]:
                                r1[cc] ^= gf_mul(r0[cc], fac)
                        _gf_row_add_mul(mat[rr][1], mat[r_idx][1], fac)
                pivots.append(c_idx)
                r_idx += 1
                if r_idx == m:
                    break

            if len(pivots) == m:
                for idx, orig_col in enumerate(unsolved_cols):
                    solved[orig_col] = mat[idx][1]

        elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 3)
        if len(solved) < n_src:
            return None, {"ok": False, "solved": len(solved), "n_src": n_src, "peeled_waves": peeled_waves, "elapsed_ms": elapsed_ms}
        rebuilt = b"".join(bytes(solved[i]) for i in range(n_src))[:orig_len]
        return rebuilt, {"ok": True, "solved": n_src, "n_src": n_src, "peeled_waves": peeled_waves, "elapsed_ms": elapsed_ms}

    @classmethod
    def run_benchmark(cls, payload_bytes: int = 16384, loss_rate: float = 0.32) -> dict[str, Any]:
        rng = random.Random(20261126)
        raw = rng.randbytes(payload_bytes)
        want_sha = hashlib.sha256(raw).hexdigest()
        codec = cls(chunk_size=512, window_w=3)
        t_enc = time.perf_counter()
        enc = codec.encode_stream(raw, redundancy=0.60, seed=71071)
        enc_ms = round((time.perf_counter() - t_enc) * 1000.0, 3)

        # Simulate severe WAN burst+random packet loss (~32%)
        pkts = enc["packets"]
        drop_n = int(len(pkts) * loss_rate)
        drop_ids = set(rng.sample(range(len(pkts)), drop_n))
        rx = [p for i, p in enumerate(pkts) if i not in drop_ids]

        rec, dec_info = codec.decode_wave(rx, enc["n_src"], enc["orig_len"], enc["chunk_size"])
        exact = rec is not None and hashlib.sha256(rec).hexdigest() == want_sha
        return {
            "ok": exact,
            "algorithm": "cristae_folded_cavity_sc_rlnc",
            "payload_bytes": payload_bytes,
            "l2_buffer_bytes": enc["l2_buffer_bytes"],
            "within_64kb_l2": enc["l2_buffer_bytes"] <= 65536,
            "sent_packets": len(pkts),
            "dropped_packets": drop_n,
            "loss_rate_pct": round((drop_n / max(1, len(pkts))) * 100.0, 1),
            "received_packets": len(rx),
            "encode_ms": enc_ms,
            "decode_ms": dec_info["elapsed_ms"],
            "peeled_waves": dec_info["peeled_waves"],
            "sha256_exact": exact,
        }
