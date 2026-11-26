"""CHIMERA-HYPER v12.0 OMEGA-GALACTIC — 5 Physics/Info-Theory Frontier Engines (Phần VIII #1..#5)."""

from __future__ import annotations

import hashlib
import json
import math
import os
import random
import struct
import time
from typing import Any

from .native import lz4_compress, lz4_decompress, splitmix64_bytes, vsa_bind_xor, vsa_hamming

# ==============================================================================
# VIII.1 — Causal-Origin Teleportation (Deterministic Generator + Tiny Entropy Tape)
# ==============================================================================


class CausalOriginTeleporter:
    """Transmit tiny generator recipe + sparse noise tape instead of 1 MiB effect stream."""

    @staticmethod
    def _synthesize_effect(seed: int, n_rows: int, overrides: list[tuple[int, int, int]]) -> bytes:
        base_b = splitmix64_bytes(seed, 32)
        ov_map = {r: (dt, code) for r, dt, code in overrides}
        lines = bytearray()
        ts = 1_700_000_000
        for r in range(n_rows):
            dt, code = ov_map.get(r, (10, 200))
            ts += dt
            lines.extend(
                f'{{"seq":{r},"ts":{ts},"node":"svhome","op":"PH9N","code":{code},"hash":"{base_b[r % 24]:02x}"}}\n'.encode("ascii")
            )
        return bytes(lines)

    @classmethod
    def run_benchmark(cls) -> dict[str, Any]:
        t0 = time.perf_counter()
        seed = 0xC405A1_01
        n_rows = 12_500  # ~1 MiB deterministic structured artifact
        overrides = [(412, 87, 503), (5800, 142, 429), (11200, 19, 201)]
        effect = cls._synthesize_effect(seed, n_rows, overrides)
        want_sha = hashlib.sha256(effect).hexdigest()

        # Serialize strictly Causal Origin: (mode, seed, n_rows, sparse_overrides)
        origin_pkt = bytearray(struct.pack("<BQQI", 1, seed, n_rows, len(overrides)))
        for r, dt, code in overrides:
            origin_pkt.extend(struct.pack("<IHH", r, dt, code))

        # Decode on destination purely from Causal Origin -> verify bit-exact SHA-256!
        mode, r_seed, r_rows, n_ov = struct.unpack_from("<BQQI", origin_pkt, 0)
        pos = 21
        r_ov = []
        for _ in range(n_ov):
            r_ov.append(struct.unpack_from("<IHH", origin_pkt, pos))
            pos += 8
        replayed = cls._synthesize_effect(r_seed, r_rows, r_ov)
        got_sha = hashlib.sha256(replayed).hexdigest()

        # Honest entropy fallback check on irreducible 4 KB random stream
        rnd_blob = os.urandom(4096)
        comp_rnd = lz4_compress(rnd_blob)
        rnd_fallback_raw = len(comp_rnd) >= len(rnd_blob)

        saved_pct = round((1.0 - (len(origin_pkt) / max(1, len(effect)))) * 100.0, 4)
        return {
            "ok": mode == 1 and got_sha == want_sha and len(origin_pkt) < 128 and len(effect) >= 900_000 and rnd_fallback_raw,
            "effect_bytes": len(effect),
            "causal_origin_bytes": len(origin_pkt),
            "wire_saved_pct": saved_pct,
            "sha256_exact": got_sha == want_sha,
            "random_entropy_fallback_clean": rnd_fallback_raw,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }


# ==============================================================================
# VIII.2 — Reversible-Physics Time-Symmetric VM (Zero-Snapshot Reverse + O(sqrt(N)) MitM)
# ==============================================================================


class ReversibleBennettVM:
    """Strictly bijective 1-to-1 reversible VM running backward with 0 history & Meet-in-the-Middle."""

    MASK32 = 0xFFFFFFFF
    # Opcodes: (op, dst, src_or_imm)
    OP_ADD_REG = 0
    OP_XOR_IMM = 1
    OP_ROTL = 2
    OP_SWAP = 3
    OP_ADD_IMM = 4

    @classmethod
    def step_fwd(cls, regs: list[int], op: int, a: int, b: int) -> None:
        m = cls.MASK32
        if op == cls.OP_ADD_REG:
            regs[a] = (regs[a] + regs[b]) & m
        elif op == cls.OP_XOR_IMM:
            regs[a] = (regs[a] ^ b) & m
        elif op == cls.OP_ROTL:
            k = b & 31
            v = regs[a]
            regs[a] = ((v << k) | (v >> ((32 - k) & 31))) & m if k else v
        elif op == cls.OP_SWAP:
            regs[a], regs[b] = regs[b], regs[a]
        elif op == cls.OP_ADD_IMM:
            regs[a] = (regs[a] + b) & m

    @classmethod
    def step_rev(cls, regs: list[int], op: int, a: int, b: int) -> None:
        m = cls.MASK32
        if op == cls.OP_ADD_REG:
            regs[a] = (regs[a] - regs[b]) & m
        elif op == cls.OP_XOR_IMM:
            regs[a] = (regs[a] ^ b) & m
        elif op == cls.OP_ROTL:
            k = b & 31
            v = regs[a]
            regs[a] = ((v >> k) | (v << ((32 - k) & 31))) & m if k else v
        elif op == cls.OP_SWAP:
            regs[a], regs[b] = regs[b], regs[a]
        elif op == cls.OP_ADD_IMM:
            regs[a] = (regs[a] - b) & m

    @classmethod
    def _stage_mix(cls, state: tuple[int, int, int, int], key8: int, forward: bool = True) -> tuple[int, int, int, int]:
        r = list(state)
        prog = [
            (cls.OP_XOR_IMM, 0, (key8 * 0x0101_0101) & cls.MASK32),
            (cls.OP_ADD_REG, 1, 0),
            (cls.OP_ROTL, 1, 7),
            (cls.OP_XOR_IMM, 2, ((key8 ^ 0x5A) * 0x9E37_79B1) & cls.MASK32),
            (cls.OP_ADD_REG, 3, 2),
            (cls.OP_ADD_REG, 0, 3),
            (cls.OP_ROTL, 0, 13),
        ]
        if forward:
            for op, a, b in prog:
                cls.step_fwd(r, op, a, b)
        else:
            for op, a, b in reversed(prog):
                cls.step_rev(r, op, a, b)
        return (r[0], r[1], r[2], r[3])

    @classmethod
    def run_benchmark(cls) -> dict[str, Any]:
        t0 = time.perf_counter()
        # 1) Bijective 1,000-step Forward -> 1,000-step Backward with ZERO intermediate snapshots!
        rng = random.Random(1202)
        init_regs = [0x1234_5678, 0x9ABC_DEF0, 0xCAFE_BABE, 0x0D15_EA5E]
        regs = list(init_regs)
        tape: list[tuple[int, int, int]] = []
        for _ in range(1000):
            op = rng.randint(0, 4)
            a = rng.randint(0, 3)
            if op in (cls.OP_ADD_REG, cls.OP_SWAP):
                b = (a + rng.randint(1, 3)) & 3
            elif op == cls.OP_ROTL:
                b = rng.randint(1, 31)
            else:
                b = rng.getrandbits(32)
            tape.append((op, a, b))
            cls.step_fwd(regs, op, a, b)

        forward_changed = regs != init_regs
        for op, a, b in reversed(tape):
            cls.step_rev(regs, op, a, b)
        reversed_exact = regs == init_regs

        # 2) Bidirectional Meet-in-the-Middle over 2^16 = 65,536 key space in O(sqrt(N)) = 512 evals!
        secret_k1, secret_k2 = 0xA7, 0x4E
        s0 = (0x1111_2222, 0x3333_4444, 0x5555_6666, 0x7777_8888)
        s_mid_true = cls._stage_mix(s0, secret_k1, forward=True)
        s_target = cls._stage_mix(s_mid_true, secret_k2, forward=True)

        fwd_table: dict[tuple[int, int, int, int], int] = {}
        evals = 0
        for k1 in range(256):
            fwd_table[cls._stage_mix(s0, k1, forward=True)] = k1
            evals += 1
        found_pair = None
        for k2 in range(256):
            cand_mid = cls._stage_mix(s_target, k2, forward=False)
            evals += 1
            if cand_mid in fwd_table:
                found_pair = (fwd_table[cand_mid], k2)
                break

        mitm_speedup_x = round(65536.0 / max(1, evals), 1)
        return {
            "ok": forward_changed and reversed_exact and found_pair == (secret_k1, secret_k2) and evals <= 512,
            "steps_forward_backward": 1000,
            "zero_snapshot_reverse_exact": reversed_exact,
            "mitm_key_space": 65536,
            "mitm_evals": evals,
            "mitm_speedup_x": mitm_speedup_x,
            "mitm_recovered_key": list(found_pair) if found_pair else None,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }


# ==============================================================================
# VIII.3 — Zero-Decompress Holographic SLP Grammar + Homomorphic LtHash
# ==============================================================================


class HolographicSlpEngine:
    """O(height) random access & substring count directly on compressed SLPs + additive GF(256) LtHash."""

    @staticmethod
    def lthash(data: bytes) -> list[int]:
        """64-lane uint16 additive homomorphic hash (each lane mod 65536)."""
        d1 = hashlib.blake2b(data + b"|LTH1", digest_size=64).digest()
        d2 = hashlib.blake2b(data + b"|LTH2", digest_size=64).digest()
        return list(struct.unpack("<64H", d1 + d2))

    @staticmethod
    def lthash_add(a: list[int], b: list[int]) -> list[int]:
        return [(x + y) & 0xFFFF for x, y in zip(a, b)]

    @staticmethod
    def lthash_sub(a: list[int], b: list[int]) -> list[int]:
        return [(x - y) & 0xFFFF for x, y in zip(a, b)]

    @classmethod
    def run_benchmark(cls) -> dict[str, Any]:
        t0 = time.perf_counter()
        # 1) Build SLP power-of-2 tree grammar for structured 512 KiB string WITHOUT keeping 512 KiB uncompressed during query
        atom = b"[LOG|svhome|PH9N|OK=1|DELTA=0.4ms]\n"  # 36 B
        # Rules: (length, is_leaf, bytes_or_left, right_id)
        rules: list[tuple[int, bool, Any, int]] = [(len(atom), True, atom, -1)]
        # Build binary doubling DAG up to 14 levels: 36 * 2^14 = 589,824 B (> 512 KiB!) using ONLY 15 grammar rules!
        for lvl in range(14):
            prev_id = lvl
            rules.append((rules[prev_id][0] * 2, False, prev_id, prev_id))
        root_id = len(rules) - 1
        total_len = rules[root_id][0]

        def _slp_char_at(rid: int, idx: int) -> int:
            cur = rid
            pos = idx
            while True:
                rlen, is_leaf, val, right_id = rules[cur]
                if is_leaf:
                    return val[pos]
                left_len = rules[val][0]
                if pos < left_len:
                    cur = val
                else:
                    pos -= left_len
                    cur = right_id

        # Sample boundary/interior offsets verified against modular index into atom
        probe_idxs = [0, 35, 36, 1000, 123456, total_len - 7, total_len - 1]
        char_exact = all(_slp_char_at(root_id, ix) == atom[ix % len(atom)] for ix in probe_idxs)

        # Zero-decompress exact pattern counting over grammar DAG (`O(|grammar|)`!)
        pattern = b"PH9N"
        m = len(pattern)
        memo_cnt: dict[int, tuple[int, bytes, bytes]] = {}  # rid -> (count, prefix(m-1), suffix(m-1))

        def _slp_count(rid: int) -> tuple[int, bytes, bytes]:
            if rid in memo_cnt:
                return memo_cnt[rid]
            rlen, is_leaf, val, right_id = rules[rid]
            if is_leaf:
                cnt = val.count(pattern)
                res = (cnt, val[: m - 1], val[-(m - 1) :])
                memo_cnt[rid] = res
                return res
            cl, pl, sl = _slp_count(val)
            cr, pr, sr = _slp_count(right_id)
            bridge = sl + pr
            cross = bridge.count(pattern)
            pref = pl if len(pl) >= m - 1 else (pl + pr)[: m - 1]
            suff = sr if len(sr) >= m - 1 else (sl + sr)[-(m - 1) :]
            res = (cl + cr + cross, pref, suff)
            memo_cnt[rid] = res
            return res

        slp_matches = _slp_count(root_id)[0]
        # Exact mathematical count for 16384 concatenated copies (no split crosses `"PH9N"` since atom has it only once internally)
        want_matches = 16384 * atom.count(pattern)

        # 2) Homomorphic LtHash across 8 chunks (`A` + `B`) + O(1) incremental chunk mutation update!
        chunks = [f"WAVE_CHUNK_{i}_DATA_".encode() * 32 for i in range(8)]
        h_chunks = [cls.lthash(c) for c in chunks]
        h_all = [0] * 64
        for hc in h_chunks:
            h_all = cls.lthash_add(h_all, hc)

        part_a = [0] * 64
        for hc in h_chunks[:4]:
            part_a = cls.lthash_add(part_a, hc)
        part_b = [0] * 64
        for hc in h_chunks[4:]:
            part_b = cls.lthash_add(part_b, hc)
        homomorphic_merge_ok = cls.lthash_add(part_a, part_b) == h_all

        # Mutate chunk 3 only -> compute updated hash in O(1) vs full re-sum!
        new_c3 = b"MUTATED_CHUNK_3_" * 36
        h_inc = cls.lthash_add(cls.lthash_sub(h_all, h_chunks[3]), cls.lthash(new_c3))
        h_recalc = [0] * 64
        for idx, c in enumerate(chunks):
            h_recalc = cls.lthash_add(h_recalc, cls.lthash(new_c3 if idx == 3 else c))
        inc_ok = h_inc == h_recalc

        return {
            "ok": char_exact and slp_matches == want_matches and homomorphic_merge_ok and inc_ok,
            "virtual_uncompressed_bytes": total_len,
            "slp_grammar_rules": len(rules),
            "char_at_probes_exact": char_exact,
            "slp_pattern_count": slp_matches,
            "lthash_homomorphic_exact": homomorphic_merge_ok and inc_ok,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }


# ==============================================================================
# VIII.4 — Emergent Zero-Human-Spec Alien Dialect (Lewis Signaling + Ephemeral Shred)
# ==============================================================================


class AlienDialectEngine:
    """Co-evolves a private binary dialect purely from shared seed + MDL stats; shreds on close."""

    def __init__(self, session_seed: bytes) -> None:
        self._seed = hashlib.blake2s(session_seed, digest_size=32).digest()
        self.vocab: dict[tuple[int, int, int], int] = {}
        self.rev_vocab: dict[int, tuple[int, int, int]] = {}
        self.closed = False

    def coevolve(self, sample_events: list[tuple[int, int, int]]) -> None:
        """Both endpoints deterministically rank event symbols + permute opcodes via shared PRNG."""
        freq: dict[tuple[int, int, int], int] = {}
        for ev in sample_events:
            freq[ev] = freq.get(ev, 0) + 1
        ranked = sorted(freq.keys(), key=lambda k: (-freq[k], k))
        # Permute the frequent 4-bit opcode alphabet [0..14] & tail alphabet using session seed!
        rng = random.Random(int.from_bytes(self._seed[:8], "little"))
        short_codes = list(range(15))
        rng.shuffle(short_codes)
        tail_codes = list(range(15, max(len(ranked) + 15, 32)))
        rng.shuffle(tail_codes)
        codes = short_codes + tail_codes
        self.vocab = {sym: codes[i] for i, sym in enumerate(ranked)}
        self.rev_vocab = {code: sym for sym, code in self.vocab.items()}

    def encode_stream(self, events: list[tuple[int, int, int]]) -> bytes:
        if self.closed:
            raise RuntimeError("Alien dialect already shredded")
        nibbles: list[int] = []
        for ev in events:
            code = self.vocab[ev]
            if code < 15:
                nibbles.append(code)
            else:
                nibbles.append(15)
                extra = code - 15
                nibbles.append((extra >> 4) & 0xF)
                nibbles.append(extra & 0xF)
        out = bytearray(struct.pack("<I", len(events)))
        for i in range(0, len(nibbles), 2):
            hi = nibbles[i]
            lo = nibbles[i + 1] if (i + 1) < len(nibbles) else 0xF
            out.append((hi << 4) | lo)
        return bytes(out)

    def decode_stream(self, wire: bytes) -> list[tuple[int, int, int]]:
        if self.closed or not self.vocab:
            raise RuntimeError("Alien dialect uninitialized or shredded")
        n_ev = struct.unpack_from("<I", wire, 0)[0]
        nibbles: list[int] = []
        for b in wire[4:]:
            nibbles.append((b >> 4) & 0xF)
            nibbles.append(b & 0xF)
        res: list[tuple[int, int, int]] = []
        idx = 0
        while len(res) < n_ev and idx < len(nibbles):
            n = nibbles[idx]
            idx += 1
            if n < 15:
                if n not in self.rev_vocab:
                    raise ValueError(f"Unknown alien opcode: {n}")
                res.append(self.rev_vocab[n])
            else:
                if idx + 1 >= len(nibbles):
                    raise ValueError("Truncated alien escape opcode")
                code = 15 + ((nibbles[idx] << 4) | nibbles[idx + 1])
                idx += 2
                if code not in self.rev_vocab:
                    raise ValueError(f"Unknown alien opcode: {code}")
                res.append(self.rev_vocab[code])
        return res

    def close_and_shred(self) -> None:
        self.vocab.clear()
        self.rev_vocab.clear()
        self._seed = b"\x00" * 32
        self.closed = True

    @classmethod
    def run_benchmark(cls) -> dict[str, Any]:
        t0 = time.perf_counter()
        events = [((i * 3) % 4, (i * 7) % 3, (i % 2)) for i in range(240)]
        json_wire = json.dumps(events, separators=(",", ":")).encode("ascii")

        tx = cls(b"ALIEN_SESSION_A_2026")
        rx = cls(b"ALIEN_SESSION_A_2026")
        tx.coevolve(events)
        rx.coevolve(events)
        wire = tx.encode_stream(events)
        decoded = rx.decode_stream(wire)

        # Foreign session B with different seed gets mismatched vocabulary / errors!
        b_sess = cls(b"FOREIGN_SESSION_B_2026")
        b_sess.coevolve(sorted(set(events), reverse=True))
        try:
            foreign_decoded = b_sess.decode_stream(wire)
            foreign_rejected = foreign_decoded != events
        except ValueError:
            foreign_rejected = True

        tx.close_and_shred()
        rx.close_and_shred()
        post_close_blocked = False
        try:
            rx.decode_stream(wire)
        except RuntimeError:
            post_close_blocked = True

        saved_pct = round((1.0 - (len(wire) / len(json_wire))) * 100.0, 2)
        return {
            "ok": decoded == events and foreign_rejected and post_close_blocked and saved_pct >= 80.0,
            "json_bytes": len(json_wire),
            "alien_wire_bytes": len(wire),
            "wire_saved_pct": saved_pct,
            "foreign_dialect_mismatch": foreign_rejected,
            "ephemeral_shred_enforced": post_close_blocked,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }


# ==============================================================================
# VIII.5 — 10,000-Dim Hyperdimensional Associative Mesh (Native AVX2 VSA)
# ==============================================================================


class HyperdimensionalVsaMesh:
    """10,000-bit (1,250 B) Kanerva VSA associative memory surviving 40% bit destruction."""

    HV_BYTES = 1250  # 1,250 * 8 = 10,000 bits!
    HV_BITS = 10_000

    @classmethod
    def make_atom(cls, tag: str) -> bytes:
        out = bytearray()
        ctr = 0
        while len(out) < cls.HV_BYTES:
            out.extend(hashlib.blake2b(f"{tag}|{ctr}".encode("utf-8"), digest_size=64).digest())
            ctr += 1
        return bytes(out[: cls.HV_BYTES])

    @classmethod
    def bundle_majority(cls, vectors: list[bytes]) -> bytes:
        n = len(vectors)
        thresh = n / 2.0
        counts = [0] * cls.HV_BITS
        for vec in vectors:
            for b_i, byte_val in enumerate(vec):
                if byte_val == 0:
                    continue
                base = b_i * 8
                for bit in range(8):
                    if (byte_val >> bit) & 1:
                        counts[base + bit] += 1
        out = bytearray(cls.HV_BYTES)
        for bit_i, cnt in enumerate(counts):
            if cnt > thresh or (cnt == thresh and (bit_i & 1) == 0):
                out[bit_i >> 3] |= 1 << (bit_i & 7)
        return bytes(out)

    @classmethod
    def run_benchmark(cls, trials: int = 100, corrupt_pct: float = 0.40) -> dict[str, Any]:
        t0 = time.perf_counter()
        nodes = [cls.make_atom(f"CLUSTER_NODE_{i}") for i in range(9)]
        states = [cls.make_atom(f"HEALTH_STATE_{j}") for j in range(32)]

        # Superpose 9 node->state associations into ONE 10,000-bit (1,250 B) holographic memory vector!
        bound_pairs = [vsa_bind_xor(nodes[i], states[(i * 5 + 3) % 32]) for i in range(9)]
        memory_hv = cls.bundle_majority(bound_pairs)

        rng = random.Random(1205)
        n_corrupt = int(cls.HV_BITS * corrupt_pct)  # 4,000 random bit flips out of 10,000 bits!
        all_bit_indices = list(range(cls.HV_BITS))

        # Pre-generate corrupted probes outside query timer so mean_query_ms measures native AVX2 lookup only
        corrupted_probes: list[tuple[int, bytes]] = []
        for tr in range(trials):
            corrupted = bytearray(memory_hv)
            for bpos in rng.sample(all_bit_indices, n_corrupt):
                corrupted[bpos >> 3] ^= 1 << (bpos & 7)
            corrupted_probes.append((tr % 9, bytes(corrupted)))

        # Verify native AVX2 lookup speed cleanly + adversarial 40% bit destruction over all trials
        t_q0 = time.perf_counter()
        correct = 0
        for node_idx, probe_hv in corrupted_probes:
            want_state_idx = (node_idx * 5 + 3) % 32
            unbound = vsa_bind_xor(probe_hv, nodes[node_idx])
            best_idx = min(range(32), key=lambda sj: vsa_hamming(unbound, states[sj]))
            if best_idx == want_state_idx:
                correct += 1
        query_ms = round(((time.perf_counter() - t_q0) * 1000.0) / max(1, trials), 3)
        recall_pct = round((correct / trials) * 100.0, 2)
        return {
            "ok": recall_pct == 100.0 and query_ms < 2.0,
            "hypervector_bits": cls.HV_BITS,
            "memory_bytes": cls.HV_BYTES,
            "bundled_associations": 9,
            "codebook_states": 32,
            "destroyed_bits_pct": round(corrupt_pct * 100.0, 1),
            "trials": trials,
            "recall_pct": recall_pct,
            "mean_query_ms": query_ms,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }
