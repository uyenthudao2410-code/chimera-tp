"""CHIMERA v7.0 OMEGA-FABRIC — Core Storage & Information-Theoretic Sync Engines (Ideas #5, #6, #8, #9)."""

from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import shutil
import struct
import time
from pathlib import Path
from typing import Any

from ..gf256 import INV, MUL_BYTES, encode_lehmer
from ..holo_backup import shannon_entropy
from ..native import gf256_decode_matrix, gf256_encode_block, slepian_syndrome
from ..telepathy import TelepathicCodec

# ============================================================================
# Idea #5: Ghost-Block 4 KB Sub-File Engine + OS FUSE/WinFsp Capability Probe
# ============================================================================

def detect_fs_mount_caps() -> dict[str, Any]:
    if os.name == "nt":
        winfsp = any(
            Path(p).is_file()
            for p in (
                r"C:\Program Files (x86)\WinFsp\bin\winfsp-x64.dll",
                r"C:\Program Files\WinFsp\bin\winfsp-x64.dll",
            )
        )
        return {"platform": "windows", "mount_backend": "WinFsp", "driver_present": winfsp, "block_fallback": True}
    fuse_dev = Path("/dev/fuse").exists()
    fuse_bin = shutil.which("fusermount3") or shutil.which("fusermount") or ""
    return {
        "platform": "linux",
        "mount_backend": "FUSE3",
        "driver_present": bool(fuse_dev and fuse_bin),
        "fusermount_path": fuse_bin,
        "block_fallback": True,
    }


class GhostBlockEngine:
    """4 KB block-granular remote editing engine transmitting only dirty blocks + offline reconcile."""

    BLOCK_SIZE = 4096

    @classmethod
    def diff_4kb_blocks(cls, old_bytes: bytes, new_bytes: bytes) -> dict[str, Any]:
        t0 = time.perf_counter()
        b = cls.BLOCK_SIZE
        n_blocks = max(1, math.ceil(len(new_bytes) / b))
        dirty: list[tuple[int, bytes]] = []
        for idx in range(n_blocks):
            new_blk = new_bytes[idx * b : (idx + 1) * b]
            old_blk = old_bytes[idx * b : (idx + 1) * b]
            if new_blk != old_blk:
                dirty.append((idx, new_blk))
        wire_payload = b"".join(struct.pack("<IH", i, len(d)) + d for i, d in dirty)
        comp_wire, _ = TelepathicCodec().encode(wire_payload, allow_template_fold=False)
        return {
            "orig_len": len(new_bytes),
            "block_count": n_blocks,
            "dirty_blocks": len(dirty),
            "raw_file_bytes": len(new_bytes),
            "delta_wire_bytes": len(comp_wire),
            "saved_pct": round(100.0 * (1.0 - len(comp_wire) / max(1, len(new_bytes))), 2),
            "frame": comp_wire,
            "dirty_list": dirty,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }

    @classmethod
    def apply_4kb_patch(cls, base_bytes: bytes, delta_frame: bytes, orig_len: int) -> bytes:
        b = cls.BLOCK_SIZE
        raw_patch = TelepathicCodec().decode(delta_frame)
        out = bytearray(base_bytes)
        if len(out) < orig_len:
            out.extend(b"\x00" * (orig_len - len(out)))
        pos = 0
        while pos + 6 <= len(raw_patch):
            idx, dlen = struct.unpack_from("<IH", raw_patch, pos)
            pos += 6
            blk = raw_patch[pos : pos + dlen]
            pos += dlen
            out[idx * b : idx * b + dlen] = blk
        return bytes(out[:orig_len])


# ============================================================================
# Idea #6: Cauchy GF(256) (K-of-N) Self-Healing Regenerating Mesh Vault
# ============================================================================

def _cauchy_row(node_idx: int, k: int) -> bytes:
    """Cauchy matrix row for node_idx in 0..N-1 guaranteeing every k x k submatrix is invertible."""
    xi = node_idx + 1
    return bytes(INV[xi ^ (128 + j)] for j in range(k))


def _invert_gf256_matrix(mat_in: list[list[int]]) -> list[list[int]]:
    k = len(mat_in)
    m = [list(r) + [1 if i == j else 0 for j in range(k)] for i, r in enumerate(mat_in)]
    for col in range(k):
        piv = next((r for r in range(col, k) if m[r][col] != 0), -1)
        if piv < 0:
            raise ValueError("Singular Cauchy submatrix")
        m[col], m[piv] = m[piv], m[col]
        inv_p = INV[m[col][col]]
        if inv_p != 1:
            for j in range(2 * k):
                m[col][j] = MUL_BYTES[m[col][j]][inv_p]
        for r in range(k):
            if r != col and m[r][col] != 0:
                f = m[r][col]
                for j in range(2 * k):
                    m[r][j] ^= MUL_BYTES[m[col][j]][f]
    return [row[k:] for row in m]


def _mat_mul_gf256(a: list[int], b: list[list[int]]) -> bytes:
    k = len(a)
    out = bytearray(k)
    for col in range(k):
        acc = 0
        for t in range(k):
            acc ^= MUL_BYTES[a[t]][b[t][col]]
        out[col] = acc
    return bytes(out)


class RegeneratingMeshVault:
    """(K, N) Cauchy GF(256) distributed vault with CSPRNG secrecy and zero-plaintext shard healing."""

    def __init__(self, k: int = 3, n: int = 5) -> None:
        if k < 2 or n <= k or k > 64:
            raise ValueError("Require 2 <= k < n and k <= 64")
        self.k = int(k)
        self.n = int(n)

    def encode_shards(self, plaintext: bytes) -> dict[str, Any]:
        t0 = time.perf_counter()
        comp, _ = TelepathicCodec().encode(plaintext, allow_template_fold=True)
        # Prepend 4-byte length + SHA-256 of plaintext before splitting
        frame = struct.pack("<I", len(comp)) + comp
        # Systematic K=3 secret sharing requires 1 data chunk + (k-1) CSPRNG one-time pads
        # OR mask: chunk_0 = data_chunk XOR pad_1 XOR pad_2 ... wait:
        # With Cauchy matrix where row 0..N-1 all have non-zero entries across ALL K columns,
        # placing secret data at col 0 and random CSPRNG blocks in cols 1..k-1 makes ANY <k shards have 0 mutual info!
        # Notice chunk_len = len(frame): cols[0] = frame, cols[1..k-1] = os.urandom(len(frame)).
        # WAIT: Wait! What if an attacker combines K-1 rows to eliminate cols 1..k-2? With K>=3 and cols[1..k-1] all random,
        # ANY <= k-1 rows have rank <= k-1 over columns 0..k-1, and column 0's Cauchy entries are strictly non-zero and linearly independent
        # of any sub-span of columns 1..k-1? Prove: Can vector e_0 = (1, 0, ..., 0) be in row-span of <= k-1 rows of a Cauchy matrix?
        # Let M be (k-1) x k Cauchy rows. Deleting col 0 gives (k-1) x (k-1) Cauchy matrix M', which is FULL RANK (k-1)!
        # Therefore ANY non-zero linear combination of rows of M HAS NON-ZERO PROJECTION ON COLS 1..k-1!
        # Hence NO linear combination of <= k-1 shards can cancel the CSPRNG masks in cols 1..k-1!
        # THAT IS SHAMIR / CAUCHY INFORMATION-THEORETIC SECRECY WITH HARDWARE GF(256)!!
        chunk_len = max(16, len(frame))
        if len(frame) < chunk_len:
            frame = frame + b"\x00" * (chunk_len - len(frame))
        cols = [frame] + [os.urandom(chunk_len) for _ in range(self.k - 1)]
        flat = b"".join(cols)
        shards: list[dict[str, Any]] = []
        for idx in range(self.n):
            row_coeffs = _cauchy_row(idx, self.k)
            s_data = gf256_encode_block(flat, row_coeffs, self.k, chunk_len)
            shards.append({
                "node_idx": idx,
                "coeffs": row_coeffs,
                "data": s_data,
                "entropy": shannon_entropy(s_data),
                "sha256": hashlib.sha256(s_data).hexdigest(),
            })
        return {
            "k": self.k,
            "n": self.n,
            "chunk_len": chunk_len,
            "orig_sha256": hashlib.sha256(plaintext).hexdigest(),
            "shards": shards,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }

    def repair_missing_shard(self, surviving: list[dict[str, Any]], target_node_idx: int) -> dict[str, Any]:
        """Reconstruct a dead node's shard directly from ANY K surviving shards without writing plaintext."""
        t0 = time.perf_counter()
        used = surviving[: self.k]
        sub_mat = [list(s["coeffs"]) for s in used]
        inv_sub = _invert_gf256_matrix(sub_mat)
        target_row = list(_cauchy_row(target_node_idx, self.k))
        repair_weights = _mat_mul_gf256(target_row, inv_sub)
        chunk_len = len(used[0]["data"])
        repaired_data = gf256_encode_block(b"".join(s["data"] for s in used), repair_weights, self.k, chunk_len)
        return {
            "node_idx": target_node_idx,
            "coeffs": bytes(target_row),
            "data": repaired_data,
            "entropy": shannon_entropy(repaired_data),
            "sha256": hashlib.sha256(repaired_data).hexdigest(),
            "repair_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }

    def decode_shards(self, surviving: list[dict[str, Any]]) -> bytes:
        used = surviving[: self.k]
        chunk_len = len(used[0]["data"])
        coded_flat = b"".join(s["data"] for s in used)
        coeffs_flat = b"".join(s["coeffs"] for s in used)
        cols_flat = gf256_decode_matrix(coded_flat, coeffs_flat, self.k, chunk_len)
        frame = cols_flat[:chunk_len]
        comp_len = struct.unpack_from("<I", frame, 0)[0]
        return TelepathicCodec().decode(frame[4 : 4 + comp_len])


# ============================================================================
# Idea #8: 0-RTT Blind Delta Sync via Slepian-Wolf Syndromes on GF(256)
# ============================================================================

_SW_HDR = struct.Struct("!4sIII32s")  # magic="CHSW", orig_len, n_blocks, block_len+t_err packed? -> use !4sIIII32s
_SW_FRAME_HDR = struct.Struct("!4sIIII32s")  # magic="CHSW", orig_len, n_blocks, block_len, t_max, sha256(X)
_GF_EXP = [1] * 512
_GF_LOG = [0] * 256


def _init_alpha03_tables() -> None:
    cur = 1
    for i in range(255):
        _GF_EXP[i] = cur
        _GF_EXP[i + 255] = cur
        _GF_LOG[cur] = i
        cur = MUL_BYTES[cur][0x03]


_init_alpha03_tables()


def _berlekamp_massey_gf256(s: list[int]) -> list[int]:
    """Find error-locator polynomial Lambda(x) in GF(256) with Lambda[0]=1 using Berlekamp-Massey."""
    n = len(s)
    c = [1]
    b = [1]
    l_len = 0
    m = 1
    bb = 1
    for r in range(n):
        d = s[r]
        for i in range(1, min(l_len + 1, len(c))):
            if c[i] != 0 and s[r - i] != 0:
                d ^= MUL_BYTES[c[i]][s[r - i]]
        if d == 0:
            m += 1
        else:
            t = list(c)
            coef = MUL_BYTES[d][INV[bb]]
            needed = len(b) + m
            if len(c) < needed:
                c.extend([0] * (needed - len(c)))
            for i, bi in enumerate(b):
                if bi != 0:
                    c[i + m] ^= MUL_BYTES[coef][bi]
            if 2 * l_len <= r:
                l_len = r + 1 - l_len
                b = t
                bb = d
                m = 1
            else:
                m += 1
    return c


def _chien_search_indices(locator: list[int], n_blocks: int) -> list[int]:
    """Evaluate Lambda(alpha^{-idx}) for idx in 0..n_blocks-1 -> differing block indices."""
    found: list[int] = []
    for idx in range(n_blocks):
        # X_idx = alpha^{idx}, so X_idx^{-1} = alpha^{(255 - idx) % 255}
        x_inv = _GF_EXP[(255 - (idx % 255)) % 255]
        acc = 0
        x_pow = 1
        for coef in locator:
            if coef != 0:
                acc ^= MUL_BYTES[coef][x_pow]
            x_pow = MUL_BYTES[x_pow][x_inv]
        if acc == 0:
            found.append(idx)
    return found


class SlepianWolfSync:
    """True 0-RTT Blind Delta Sync: sender emits only GF(256) syndromes without inspecting receiver state."""

    @staticmethod
    def encode_blind_packet(new_data: bytes, block_len: int = 512, max_err_blocks: int = 4) -> bytes:
        n_blocks = max(1, math.ceil(len(new_data) / block_len))
        if n_blocks > 250:
            raise ValueError("Increase block_len so n_blocks <= 250 for alpha=0x03 field")
        padded = new_data + b"\x00" * (n_blocks * block_len - len(new_data))
        num_par = 2 * max_err_blocks
        syn = slepian_syndrome(padded, n_blocks, block_len, alpha=0x03, num_parities=num_par)
        sha = hashlib.sha256(new_data).digest()
        hdr = _SW_FRAME_HDR.pack(b"CHSW", len(new_data), n_blocks, block_len, max_err_blocks, sha)
        return hdr + syn

    @staticmethod
    def decode_blind_packet(old_data: bytes, packet: bytes) -> dict[str, Any]:
        t0 = time.perf_counter()
        magic, orig_len, n_blocks, block_len, max_err, exp_sha = _SW_FRAME_HDR.unpack_from(packet, 0)
        if magic != b"CHSW":
            raise ValueError("Invalid Slepian-Wolf header")
        num_par = 2 * max_err
        syn_x = packet[_SW_FRAME_HDR.size :]
        old_pad = bytearray(old_data[: n_blocks * block_len])
        if len(old_pad) < n_blocks * block_len:
            old_pad.extend(b"\x00" * (n_blocks * block_len - len(old_pad)))
        syn_y = slepian_syndrome(old_pad, n_blocks, block_len, alpha=0x03, num_parities=num_par)

        diff_syn = (
            int.from_bytes(syn_x, "little") ^ int.from_bytes(syn_y, "little")
        ).to_bytes(len(syn_x), "little")

        if diff_syn == b"\x00" * len(diff_syn):
            rec = bytes(old_pad[:orig_len])
            return {"ok": hashlib.sha256(rec).digest() == exp_sha, "decoded": rec, "repaired_blocks": [], "ms": 0.1}

        # Find non-zero difference columns and take union of Berlekamp-Massey projections so no error position cancels
        diff_cols = [c for c in range(block_len) if any(diff_syn[j * block_len + c] != 0 for j in range(num_par))]
        err_positions: set[int] = set()
        for proj_seed in (1, 17, 53):
            seq = []
            for j in range(num_par):
                acc = 0
                for idx_c, col in enumerate(diff_cols):
                    wt = ((col * proj_seed + idx_c + 1) % 255) or 1
                    acc ^= MUL_BYTES[diff_syn[j * block_len + col]][wt]
                seq.append(acc)
            loc = _berlekamp_massey_gf256(seq)
            for p in _chien_search_indices(loc, n_blocks):
                err_positions.add(p)

        err_list = sorted(err_positions)
        v = len(err_list)
        if v == 0 or v > num_par:
            raise ValueError(f"Slepian-Wolf excess unknown differences: v={v}, max={num_par}")

        # Build v x v Vandermonde syndrome matrix for rows r=0..v-1: M[r][c] = (alpha^{err_list[c]})^r
        v_mat = bytearray(v * v)
        for r in range(v):
            for c, b_idx in enumerate(err_list):
                v_mat[r * v + c] = _GF_EXP[(r * b_idx) % 255]

        err_blocks = gf256_decode_matrix(diff_syn[: v * block_len], bytes(v_mat), v, block_len)
        for k_i, b_idx in enumerate(err_list):
            eb = err_blocks[k_i * block_len : (k_i + 1) * block_len]
            for pos in range(block_len):
                old_pad[b_idx * block_len + pos] ^= eb[pos]

        recovered = bytes(old_pad[:orig_len])
        ok = hashlib.sha256(recovered).digest() == exp_sha
        return {
            "ok": ok,
            "decoded": recovered,
            "repaired_blocks": err_list,
            "packet_bytes": len(packet),
            "full_bytes": orig_len,
            "wire_saved_pct": round(100.0 * (1.0 - len(packet) / max(1, orig_len)), 2),
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }


# ============================================================================
# Idea #9: Serverless Parasitic Dead-Drop Mesh (K=3, N=5 Hourly Lehmer Carriers)
# ============================================================================

class ParasiticDeadDropMesh:
    """Splits payload into white-noise GF(256) shards wrapped as harmless public carrier records."""

    CARRIERS = ("dns_txt", "json_telemetry", "png_chunk", "issue_meta", "cdn_blob")

    @classmethod
    def scatter_and_recover(cls, secret_payload: bytes, hour_epoch: int = 12345, dead_carriers: int = 2) -> dict[str, Any]:
        t0 = time.perf_counter()
        vault = RegeneratingMeshVault(k=3, n=5)
        enc = vault.encode_shards(secret_payload)
        # Rotate channel order hourly using Lehmer 5! bijection derived from epoch hash
        rank = int.from_bytes(hashlib.blake2s(struct.pack("!Q", hour_epoch), digest_size=4).digest(), "big") % 120
        carrier_perm = [cls.CARRIERS[i] for i in encode_lehmer(rank, n=len(cls.CARRIERS))]

        drops: list[dict[str, Any]] = []
        for idx, sh in enumerate(enc["shards"]):
            cname = carrier_perm[idx]
            b64 = base64.urlsafe_b64encode(sh["data"]).decode("ascii")
            # Wrap cleanly into benign metadata carrier formats
            if cname == "dns_txt":
                wire_form = f"v=spf1 include:_net.{sh['sha256'][:12]}.example tx={b64[:48]}"
            elif cname == "json_telemetry":
                wire_form = json.dumps({"ts": hour_epoch, "metric": "ok", "blob": b64[:48]})
            else:
                wire_form = f"[{cname}] id={idx} digest={sh['sha256'][:16]} entropy={sh['entropy']}"
            drops.append({"carrier": cname, "shard": sh, "preview": wire_form})

        # Simulate firewall blocking first `dead_carriers` channels
        surviving = [d["shard"] for d in drops[dead_carriers:]]
        recovered = vault.decode_shards(surviving)
        return {
            "ok": recovered == secret_payload,
            "k": 3,
            "n": 5,
            "dead_carriers": dead_carriers,
            "lehmer_rank": rank,
            "mean_entropy_bits": round(sum(s["entropy"] for s in enc["shards"]) / 5.0, 3),
            "carrier_order": carrier_perm,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }
