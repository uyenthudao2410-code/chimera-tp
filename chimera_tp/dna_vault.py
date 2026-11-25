"""Breakthrough #1: Zero-Byte DNA Vault, FastCDC Content-Defined Chunking & Delta Codec."""

from __future__ import annotations

import hashlib
import os
import struct
import time
import zlib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .native import chunk_superfeatures, delta_decode, delta_encode, fastcdc_split

_DNA_MAGIC = b"CHDNA1"
_VAULT_MAGIC = b"CHVAULT1"
_DIR_MAGIC = b"CHDIR1"

_OP_REF = 1
_OP_DELTA = 2
_OP_RAW = 3


def compute_cid(chunk: bytes | bytearray | memoryview) -> bytes:
    """16-byte BLAKE2s content DNA identifier."""
    return hashlib.blake2s(chunk, digest_size=16).digest()


def _maybe_compress(data: bytes) -> tuple[int, bytes]:
    """Compress with zlib level 1 when beneficial; skip incompressible chunks automatically."""
    if len(data) < 64:
        return 0, data
    if len(data) >= 8192:
        sample = data[:4096]
        if len(zlib.compress(sample, 1)) > int(len(sample) * 0.96):
            return 0, data
    comp = zlib.compress(data, 1)
    if len(comp) < int(len(data) * 0.97):
        return 1, comp
    return 0, data


@dataclass
class DnaStats:
    raw_bytes: int
    wire_bytes: int
    total_chunks: int
    ref_hits: int
    ref_bytes_saved: int
    delta_hits: int
    delta_bytes_saved: int
    raw_misses: int
    elapsed_ms: float

    @property
    def reduction_pct(self) -> float:
        if self.raw_bytes <= 0:
            return 0.0
        return max(0.0, 100.0 * (1.0 - (self.wire_bytes / self.raw_bytes)))

    @property
    def effective_multiplier(self) -> float:
        if self.raw_bytes <= 0:
            return 1.0
        return self.raw_bytes / max(1, self.wire_bytes)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["reduction_pct"] = round(self.reduction_pct, 2)
        d["effective_multiplier"] = round(self.effective_multiplier, 2)
        return d


class DnaVault:
    """Persistent content-addressed DNA chunk vault with O(1) Odess Super-Feature index."""

    def __init__(self, vault_dir: Path | None = None, max_bytes: int = 512 * 1024 * 1024) -> None:
        self.vault_dir = Path(vault_dir) if vault_dir is not None else None
        self.max_bytes = max_bytes
        self._chunks: dict[bytes, bytes] = {}
        self._sfs: dict[bytes, tuple[int, int, int, int]] = {}
        self._sf_index: dict[int, bytes] = {}
        self._total_bytes = 0
        if self.vault_dir is not None:
            self.load()

    @property
    def chunk_count(self) -> int:
        return len(self._chunks)

    @property
    def total_bytes(self) -> int:
        return self._total_bytes

    def known_cids(self) -> set[bytes]:
        return set(self._chunks.keys())

    def get(self, cid: bytes) -> bytes | None:
        return self._chunks.get(cid)

    def put(
        self,
        cid: bytes,
        data: bytes,
        sfs: tuple[int, int, int, int] | None = None,
    ) -> None:
        if cid in self._chunks:
            return
        while self._total_bytes + len(data) > self.max_bytes and self._chunks:
            oldest_cid = next(iter(self._chunks))
            old_data = self._chunks.pop(oldest_cid)
            self._total_bytes -= len(old_data)
            old_sfs = self._sfs.pop(oldest_cid, ())
            for sf in old_sfs:
                if self._sf_index.get(sf) == oldest_cid:
                    del self._sf_index[sf]

        self._chunks[cid] = data
        self._total_bytes += len(data)
        if sfs is None:
            sfs = chunk_superfeatures(data)
        self._sfs[cid] = sfs
        for sf in sfs:
            if sf and sf not in self._sf_index:
                self._sf_index[sf] = cid

    def find_sibling(
        self, sfs: tuple[int, int, int, int], sf_map: dict[int, bytes] | None = None
    ) -> tuple[bytes, bytes] | None:
        lookup = sf_map if sf_map is not None else self._sf_index
        for sf in sfs:
            if not sf:
                continue
            base_cid = lookup.get(sf)
            if base_cid is not None:
                base_data = self._chunks.get(base_cid)
                if base_data is not None:
                    return base_cid, base_data
        return None

    def export_sketch(self) -> bytes:
        """Compact sketch of all known CIDs and 4x64-bit super-features (48 B/chunk)."""
        out = bytearray()
        out.extend(struct.pack("<I", len(self._chunks)))
        for cid in self._chunks:
            sfs = self._sfs.get(cid, (0, 0, 0, 0))
            out.extend(cid)
            out.extend(struct.pack("<4Q", *sfs))
        return bytes(out)

    @staticmethod
    def import_sketch(sketch: bytes) -> tuple[set[bytes], dict[int, bytes]]:
        if not sketch:
            return set(), {}
        (count,) = struct.unpack_from("<I", sketch, 0)
        pos = 4
        cids: set[bytes] = set()
        sf_map: dict[int, bytes] = {}
        for _ in range(count):
            cid = bytes(sketch[pos : pos + 16])
            pos += 16
            sfs = struct.unpack_from("<4Q", sketch, pos)
            pos += 32
            cids.add(cid)
            for sf in sfs:
                if sf and sf not in sf_map:
                    sf_map[sf] = cid
        return cids, sf_map

    def save(self) -> None:
        if self.vault_dir is None:
            return
        self.vault_dir.mkdir(parents=True, exist_ok=True)
        target = self.vault_dir / "vault.bin"
        tmp = self.vault_dir / "vault.bin.tmp"
        buf = bytearray()
        buf.extend(_VAULT_MAGIC)
        buf.extend(struct.pack("<I", len(self._chunks)))
        for cid, chunk in self._chunks.items():
            sfs = self._sfs.get(cid, (0, 0, 0, 0))
            buf.extend(cid)
            buf.extend(struct.pack("<4QI", *sfs, len(chunk)))
            buf.extend(chunk)
        tmp.write_bytes(bytes(buf))
        os.replace(tmp, target)

    def load(self) -> None:
        if self.vault_dir is None:
            return
        path = self.vault_dir / "vault.bin"
        if not path.exists():
            return
        raw = path.read_bytes()
        if not raw.startswith(_VAULT_MAGIC):
            return
        pos = len(_VAULT_MAGIC)
        (count,) = struct.unpack_from("<I", raw, pos)
        pos += 4
        mv = memoryview(raw)
        for _ in range(count):
            cid = bytes(mv[pos : pos + 16])
            pos += 16
            sf0, sf1, sf2, sf3, clen = struct.unpack_from("<4QI", mv, pos)
            pos += 36
            chunk = bytes(mv[pos : pos + clen])
            pos += clen
            self.put(cid, chunk, sfs=(sf0, sf1, sf2, sf3))


class DnaCodec:
    """Content-defined Zero-Byte Reference + Delta Recipe Encoder/Decoder."""

    def __init__(
        self, min_chunk: int = 4096, avg_chunk: int = 16384, max_chunk: int = 65536
    ) -> None:
        self.min_chunk = min_chunk
        self.avg_chunk = avg_chunk
        self.max_chunk = max_chunk

    def encode_stream(
        self,
        data: bytes,
        receiver_cids: set[bytes],
        receiver_sf_map: dict[int, bytes],
        sender_vault: DnaVault,
    ) -> tuple[bytes, DnaStats]:
        t0 = time.perf_counter()
        spans = fastcdc_split(data, self.min_chunk, self.avg_chunk, self.max_chunk)
        mv = memoryview(data)

        out = bytearray()
        out.extend(_DNA_MAGIC)
        out.extend(struct.pack("<II", len(data), len(spans)))

        ref_hits = 0
        ref_saved = 0
        delta_hits = 0
        delta_saved = 0
        raw_misses = 0

        # Track newly materialized chunks in this same stream too (intra-stream dedup!)
        local_cids = set(receiver_cids)
        local_sf_map = dict(receiver_sf_map)

        for start, end in spans:
            chunk = bytes(mv[start:end])
            cid = compute_cid(chunk)

            if cid in local_cids:
                out.append(_OP_REF)
                out.extend(cid)
                ref_hits += 1
                ref_saved += len(chunk)
                continue

            sfs = chunk_superfeatures(chunk)
            sibling = sender_vault.find_sibling(sfs, sf_map=local_sf_map)
            raw_flag, raw_body = _maybe_compress(chunk)

            used_delta = False
            if sibling is not None:
                base_cid, base_data = sibling
                patch = delta_encode(base_data, chunk)
                if patch is not None:
                    d_flag, d_body = _maybe_compress(patch)
                    # Record overhead of OP_DELTA is 41B vs OP_RAW 22B
                    if len(d_body) + 19 < len(raw_body):
                        out.append(_OP_DELTA)
                        out.extend(base_cid)
                        out.extend(cid)
                        out.extend(struct.pack("<IBI", len(chunk), d_flag, len(d_body)))
                        out.extend(d_body)
                        delta_hits += 1
                        delta_saved += max(0, len(chunk) - (42 + len(d_body)))
                        used_delta = True

            if not used_delta:
                out.append(_OP_RAW)
                out.extend(cid)
                out.extend(struct.pack("<BI", raw_flag, len(raw_body)))
                out.extend(raw_body)
                raw_misses += 1

            sender_vault.put(cid, chunk, sfs=sfs)
            local_cids.add(cid)
            for sf in sfs:
                if sf and sf not in local_sf_map:
                    local_sf_map[sf] = cid

        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        wire = bytes(out)
        stats = DnaStats(
            raw_bytes=len(data),
            wire_bytes=len(wire),
            total_chunks=len(spans),
            ref_hits=ref_hits,
            ref_bytes_saved=ref_saved,
            delta_hits=delta_hits,
            delta_bytes_saved=delta_saved,
            raw_misses=raw_misses,
            elapsed_ms=round(elapsed_ms, 2),
        )
        return wire, stats

    def decode_stream(
        self, recipe_bytes: bytes, receiver_vault: DnaVault
    ) -> tuple[bytes, DnaStats]:
        t0 = time.perf_counter()
        if not recipe_bytes.startswith(_DNA_MAGIC):
            raise ValueError("Invalid CHIMERA DNA recipe magic")
        pos = len(_DNA_MAGIC)
        raw_len, num_chunks = struct.unpack_from("<II", recipe_bytes, pos)
        pos += 8
        mv = memoryview(recipe_bytes)

        out = bytearray()
        ref_hits = 0
        ref_saved = 0
        delta_hits = 0
        delta_saved = 0
        raw_misses = 0

        for _ in range(num_chunks):
            op = mv[pos]
            pos += 1
            if op == _OP_REF:
                cid = bytes(mv[pos : pos + 16])
                pos += 16
                chunk = receiver_vault.get(cid)
                if chunk is None:
                    raise KeyError(f"DNA vault miss for referenced CID {cid.hex()}")
                out.extend(chunk)
                ref_hits += 1
                ref_saved += len(chunk)
            elif op == _OP_DELTA:
                base_cid = bytes(mv[pos : pos + 16])
                cid = bytes(mv[pos + 16 : pos + 32])
                orig_len, d_flag, d_len = struct.unpack_from("<IBI", mv, pos + 32)
                pos += 41
                body = bytes(mv[pos : pos + d_len])
                pos += d_len
                base = receiver_vault.get(base_cid)
                if base is None:
                    raise KeyError(f"DNA vault miss for delta base {base_cid.hex()}")
                patch = zlib.decompress(body) if d_flag == 1 else body
                chunk = delta_decode(base, patch, orig_len)
                if compute_cid(chunk) != cid:
                    raise ValueError("Delta-reconstructed chunk CID mismatch")
                receiver_vault.put(cid, chunk)
                out.extend(chunk)
                delta_hits += 1
                delta_saved += max(0, len(chunk) - (42 + d_len))
            elif op == _OP_RAW:
                cid = bytes(mv[pos : pos + 16])
                r_flag, r_len = struct.unpack_from("<BI", mv, pos + 16)
                pos += 21
                body = bytes(mv[pos : pos + r_len])
                pos += r_len
                chunk = zlib.decompress(body) if r_flag == 1 else body
                if compute_cid(chunk) != cid:
                    raise ValueError("Raw chunk CID mismatch")
                receiver_vault.put(cid, chunk)
                out.extend(chunk)
                raw_misses += 1
            else:
                raise ValueError(f"Unknown DNA recipe opcode: {op}")

        if len(out) != raw_len:
            raise ValueError(f"Decoded stream length mismatch: {len(out)} != {raw_len}")

        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        stats = DnaStats(
            raw_bytes=raw_len,
            wire_bytes=len(recipe_bytes),
            total_chunks=num_chunks,
            ref_hits=ref_hits,
            ref_bytes_saved=ref_saved,
            delta_hits=delta_hits,
            delta_bytes_saved=delta_saved,
            raw_misses=raw_misses,
            elapsed_ms=round(elapsed_ms, 2),
        )
        return bytes(out), stats


# ---------------------------------------------------------------------------
# Directory Pack / Unpack (per-file framing + per-file SHA-256 verification)
# ---------------------------------------------------------------------------


def pack_directory(root: Path) -> bytes:
    """Serialize all files under `root` in deterministic sorted relative-path order."""
    root = Path(root).resolve()
    if not root.is_dir():
        raise NotADirectoryError(f"Not a directory: {root}")
    files = sorted(
        (p for p in root.rglob("*") if p.is_file() and ".chimera_vault" not in p.parts),
        key=lambda p: p.relative_to(root).as_posix(),
    )
    out = bytearray()
    out.extend(_DIR_MAGIC)
    out.extend(struct.pack("<I", len(files)))
    for fp in files:
        rel = fp.relative_to(root).as_posix().encode("utf-8")
        data = fp.read_bytes()
        sha = hashlib.sha256(data).digest()
        out.extend(struct.pack("<HQ", len(rel), len(data)))
        out.extend(rel)
        out.extend(sha)
        out.extend(data)
    return bytes(out)


def unpack_directory(bundle: bytes, out_dir: Path) -> list[str]:
    """Extract a packed directory bundle into `out_dir`, validating every file SHA-256."""
    if not bundle.startswith(_DIR_MAGIC):
        raise ValueError("Invalid directory bundle magic")
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    pos = len(_DIR_MAGIC)
    (count,) = struct.unpack_from("<I", bundle, pos)
    pos += 4
    mv = memoryview(bundle)
    written: list[str] = []
    for _ in range(count):
        rel_len, file_len = struct.unpack_from("<HQ", mv, pos)
        pos += 10
        rel_str = bytes(mv[pos : pos + rel_len]).decode("utf-8")
        pos += rel_len
        expected_sha = bytes(mv[pos : pos + 32])
        pos += 32
        data = bytes(mv[pos : pos + file_len])
        pos += file_len
        if hashlib.sha256(data).digest() != expected_sha:
            raise ValueError(f"SHA-256 mismatch extracting {rel_str}")
        target = (out_dir / rel_str).resolve()
        if out_dir not in target.parents and target != out_dir:
            raise ValueError(f"Path traversal rejected: {rel_str}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        written.append(rel_str)
    return written
