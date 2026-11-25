"""CHIMERA v4.0 Breakthrough #5: Holographic GF(256) (K=2, N=3) Information-Theoretic Backup."""

from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import re
import struct
import time
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .merkle_sync import DEFAULT_IGNORE_DIRS, sanitize_workspace_id
from .native import gf256_decode_matrix, gf256_encode_block
from .telepathy import TelepathicCodec

_ARCHIVE_MAGIC = b"CHHB1"
_SHARD_MAGIC = b"CHSH1"

# Every 2x2 submatrix is full rank in GF(256) and column-2 coeffs {1, 2, 3} are all nonzero,
# guaranteeing perfect 1-shard information-theoretic secrecy with os.urandom(L) mask.
SHARD_COEFFS: tuple[bytes, bytes, bytes] = (
    bytes((1, 1)),
    bytes((1, 2)),
    bytes((1, 3)),
)


def sanitize_backup_id(raw_id: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9._-]", "_", str(raw_id or "")).strip("._")
    if not clean or ".." in clean:
        clean = f"bk_{datetime.now().astimezone().strftime('%Y%m%d_%H%M%S')}"
    return clean[:64]


def shannon_entropy(data: bytes) -> float:
    """Compute Shannon entropy in bits per byte in [0.0, 8.0]."""
    n = len(data)
    if n == 0:
        return 0.0
    counts = Counter(data)
    return round(-sum((c / n) * math.log2(c / n) for c in counts.values()), 4)


def pack_files_archive(paths: list[Path], max_total_bytes: int = 32 * 1024 * 1024) -> tuple[bytes, int, list[str]]:
    """Deterministically pack files/directories into CHHB1 binary capsule with per-file SHA-256."""
    items: list[tuple[str, bytes]] = []
    total_raw = 0
    used_names: set[str] = set()

    for raw_p in paths:
        p = Path(raw_p).resolve()
        if not p.exists():
            raise FileNotFoundError(f"Backup target not found: {raw_p}")
        if p.is_file():
            rel = p.name
            if rel in used_names:
                rel = f"{len(used_names)}_{p.name}"
            used_names.add(rel)
            data = p.read_bytes()
            total_raw += len(data)
            if total_raw > max_total_bytes:
                raise ValueError(f"Backup raw payload exceeds {max_total_bytes} bytes")
            items.append((rel, data))
        elif p.is_dir():
            for dirpath, dirnames, filenames in os.walk(p):
                dirnames[:] = sorted(d for d in dirnames if d not in DEFAULT_IGNORE_DIRS)
                for fn in sorted(filenames):
                    fp = Path(dirpath) / fn
                    rel = f"{p.name}/{fp.relative_to(p).as_posix()}"
                    if rel in used_names:
                        continue
                    used_names.add(rel)
                    data = fp.read_bytes()
                    total_raw += len(data)
                    if total_raw > max_total_bytes:
                        raise ValueError(f"Backup raw payload exceeds {max_total_bytes} bytes")
                    items.append((rel, data))

    if not items:
        raise ValueError("No files found to pack into holographic backup")

    out = bytearray(_ARCHIVE_MAGIC)
    out.extend(struct.pack("<I", len(items)))
    file_list: list[str] = []
    for rel, data in sorted(items, key=lambda x: x[0]):
        rel_b = rel.encode("utf-8")
        sha = hashlib.sha256(data).digest()
        out.extend(struct.pack("<HQ", len(rel_b), len(data)))
        out.extend(rel_b)
        out.extend(sha)
        out.extend(data)
        file_list.append(rel)
    return bytes(out), total_raw, file_list


def unpack_files_archive(blob: bytes, out_dir: Path) -> list[str]:
    """Verify SHA-256 of every entry and safely extract CHHB1 capsule to `out_dir`."""
    if not blob.startswith(_ARCHIVE_MAGIC):
        raise ValueError("Invalid CHHB1 archive magic")
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    pos = len(_ARCHIVE_MAGIC)
    (count,) = struct.unpack_from("<I", blob, pos)
    pos += 4

    mv = memoryview(blob)
    restored: list[str] = []
    for _ in range(count):
        rel_len, file_len = struct.unpack_from("<HQ", mv, pos)
        pos += 10
        rel = bytes(mv[pos : pos + rel_len]).decode("utf-8")
        pos += rel_len
        expected_sha = bytes(mv[pos : pos + 32])
        pos += 32
        data = bytes(mv[pos : pos + file_len])
        pos += file_len
        if hashlib.sha256(data).digest() != expected_sha:
            raise ValueError(f"Per-file SHA-256 mismatch restoring {rel}")
        target = (out_dir / rel).resolve()
        if out_dir not in target.parents:
            raise ValueError(f"Path traversal rejected restoring: {rel}")
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(f".{target.name}.tmp")
        tmp.write_bytes(data)
        os.replace(tmp, target)
        restored.append(rel)
    return restored


def split_secret_gf256_2of3(payload: bytes) -> list[tuple[int, bytes, bytes]]:
    """Split `payload` into 3 secret-shared GF(256) shards via native GFNI/AVX2 linear coding."""
    if not payload:
        raise ValueError("Empty payload cannot be split")
    block_len = len(payload)
    rand_mask = os.urandom(block_len)
    blocks_flat = payload + rand_mask
    shards: list[tuple[int, bytes, bytes]] = []
    for idx in range(3):
        c = SHARD_COEFFS[idx]
        s_data = gf256_encode_block(blocks_flat, c, 2, block_len)
        shards.append((idx, c, s_data))
    return shards


def reconstruct_secret_gf256_2of3(
    shard_a: tuple[int, bytes, bytes],
    shard_b: tuple[int, bytes, bytes],
) -> bytes:
    """Invert 2x2 GF(256) matrix from any 2 distinct shards to recover exact original payload."""
    idx_a, coeffs_a, data_a = shard_a
    idx_b, coeffs_b, data_b = shard_b
    if idx_a == idx_b:
        raise ValueError("Two distinct shards are required for (2,3) reconstruction")
    if len(data_a) != len(data_b) or not data_a:
        raise ValueError("Shard payload lengths do not match")
    block_len = len(data_a)
    recovered = gf256_decode_matrix(data_a + data_b, coeffs_a + coeffs_b, 2, block_len)
    return recovered[:block_len]


def serialize_shard(
    backup_id: str,
    shard_idx: int,
    coeffs: bytes,
    shard_data: bytes,
    orig_sha256: str,
    created_utc: str,
) -> bytes:
    hdr = json.dumps(
        {
            "backup_id": backup_id,
            "shard_idx": shard_idx,
            "k": 2,
            "n": 3,
            "coeffs_hex": coeffs.hex(),
            "payload_len": len(shard_data),
            "shard_sha256": hashlib.sha256(shard_data).hexdigest(),
            "orig_sha256": orig_sha256,
            "created_utc": created_utc,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    return _SHARD_MAGIC + struct.pack("<I", len(hdr)) + hdr + shard_data


def parse_shard_bytes(raw: bytes) -> tuple[dict[str, Any], bytes]:
    if not raw.startswith(_SHARD_MAGIC) or len(raw) < len(_SHARD_MAGIC) + 4:
        raise ValueError("Invalid CHSH1 shard magic")
    pos = len(_SHARD_MAGIC)
    (hdr_len,) = struct.unpack_from("<I", raw, pos)
    pos += 4
    meta = json.loads(raw[pos : pos + hdr_len].decode("utf-8"))
    data = raw[pos + hdr_len :]
    if len(data) != int(meta["payload_len"]):
        raise ValueError("Truncated CHSH1 shard payload")
    if hashlib.sha256(data).hexdigest() != str(meta["shard_sha256"]):
        raise ValueError(f"Corrupted shard #{meta.get('shard_idx')} (SHA-256 mismatch)")
    return meta, data


def store_received_shard(raw_shard: bytes, backup_root: Path) -> dict[str, Any]:
    """Validate and store a remote CHSH1 shard on peer under `backup_root / backup_id`."""
    meta, _ = parse_shard_bytes(raw_shard)
    bid = sanitize_workspace_id(str(meta["backup_id"]))
    idx = int(meta["shard_idx"])
    if idx not in (0, 1, 2):
        raise ValueError(f"Invalid shard index: {idx}")
    bdir = Path(backup_root).resolve() / bid
    bdir.mkdir(parents=True, exist_ok=True)
    dest = bdir / f"shard_{idx}.chshard"
    tmp = dest.with_name(f".{dest.name}.tmp")
    tmp.write_bytes(raw_shard)
    os.replace(tmp, dest)
    return {
        "ok": True,
        "backup_id": bid,
        "shard_idx": idx,
        "bytes": len(raw_shard),
        "path": str(dest),
    }


def create_holo_backup(
    paths: list[Path],
    backup_root: Path,
    backup_id: str = "",
    peer_http_base: str = "",
) -> dict[str, Any]:
    """Compress via Telepathy, GF(256)-split (K=2, N=3), store local/export shards, sync Shard 1."""
    t0 = time.perf_counter()
    bid = sanitize_backup_id(backup_id)
    backup_root = Path(backup_root).resolve()
    bdir = backup_root / bid
    bdir.mkdir(parents=True, exist_ok=True)

    archive_bytes, raw_bytes, file_list = pack_files_archive(paths)
    orig_sha = hashlib.sha256(archive_bytes).hexdigest()
    created_utc = datetime.now(timezone.utc).isoformat(timespec="seconds")

    # Self-contained lossless compression so any 2 shards restore offline with zero external state
    compressed_bytes, comp_stats = TelepathicCodec().encode(
        archive_bytes, domain_dict=None, allow_template_fold=True
    )
    shards = split_secret_gf256_2of3(compressed_bytes)
    entropies = [shannon_entropy(s_data) for _, _, s_data in shards]
    serialized = [
        serialize_shard(bid, idx, coeffs, s_data, orig_sha, created_utc)
        for idx, coeffs, s_data in shards
    ]

    p0 = bdir / "shard_0.chshard"
    p2 = bdir / "export_shard_2.chshard"
    p0.write_bytes(serialized[0])
    p2.write_bytes(serialized[2])
    local_shards = [str(p0), str(p2)]

    peer_synced = False
    peer_error = ""
    if peer_http_base:
        try:
            body = json.dumps(
                {"shard_b64": base64.b64encode(serialized[1]).decode("ascii")}
            ).encode("utf-8")
            req = urllib.request.Request(
                f"{peer_http_base.rstrip('/')}/api/backup/store-shard",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=8.0) as resp:
                ack = json.loads(resp.read().decode("utf-8"))
                peer_synced = bool(ack.get("ok"))
        except Exception as exc:
            peer_error = str(exc)

    if not peer_synced:
        p1 = bdir / "shard_1.chshard"
        p1.write_bytes(serialized[1])
        local_shards.insert(1, str(p1))

    meta_info = {
        "backup_id": bid,
        "created_utc": created_utc,
        "files": file_list,
        "raw_bytes": raw_bytes,
        "compressed_bytes": len(compressed_bytes),
        "shard_bytes": len(serialized[0]),
        "compression_mode": comp_stats["mode_name"],
        "orig_sha256": orig_sha,
        "entropies": entropies,
        "peer_synced": peer_synced,
        "peer_error": peer_error,
        "local_shards": local_shards,
    }
    (bdir / "manifest.json").write_text(
        json.dumps(meta_info, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    meta_info["ok"] = True
    meta_info["elapsed_ms"] = round((time.perf_counter() - t0) * 1000.0, 2)
    return meta_info


def restore_holo_backup(shard_paths: list[Path], out_dir: Path) -> dict[str, Any]:
    """Reconstruct secret-shared (K=2, N=3) backup from any 2 valid shards and verify SHA-256."""
    t0 = time.perf_counter()
    if len(shard_paths) < 2:
        raise ValueError("Need at least 2 shards to reconstruct (K=2, N=3) backup")

    parsed: list[tuple[dict[str, Any], bytes]] = []
    for sp in shard_paths[:2]:
        raw = Path(sp).read_bytes()
        parsed.append(parse_shard_bytes(raw))

    m0, d0 = parsed[0]
    m1, d1 = parsed[1]
    if str(m0["backup_id"]) != str(m1["backup_id"]):
        raise ValueError(f"Mismatched backup IDs: {m0['backup_id']} vs {m1['backup_id']}")
    if str(m0["orig_sha256"]) != str(m1["orig_sha256"]):
        raise ValueError("Mismatched original archive SHA-256 between shards")

    c0 = bytes.fromhex(str(m0["coeffs_hex"]))
    c1 = bytes.fromhex(str(m1["coeffs_hex"]))
    compressed = reconstruct_secret_gf256_2of3(
        (int(m0["shard_idx"]), c0, d0),
        (int(m1["shard_idx"]), c1, d1),
    )
    archive_bytes = TelepathicCodec().decode(compressed)
    got_sha = hashlib.sha256(archive_bytes).hexdigest()
    if got_sha != str(m0["orig_sha256"]):
        raise ValueError(f"Archive SHA-256 mismatch after decode: {got_sha} != {m0['orig_sha256']}")

    files_restored = unpack_files_archive(archive_bytes, Path(out_dir))
    return {
        "ok": True,
        "backup_id": str(m0["backup_id"]),
        "used_shards": [int(m0["shard_idx"]), int(m1["shard_idx"])],
        "files_restored": files_restored,
        "orig_sha256": got_sha,
        "sha256_match": True,
        "out_dir": str(Path(out_dir).resolve()),
        "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
    }


def list_holo_backups(backup_root: Path) -> list[dict[str, Any]]:
    backup_root = Path(backup_root)
    if not backup_root.exists():
        return []
    out: list[dict[str, Any]] = []
    for sub in sorted(backup_root.iterdir(), key=lambda p: p.name, reverse=True):
        if not sub.is_dir() or sub.name == "restored":
            continue
        mf = sub / "manifest.json"
        if mf.is_file():
            try:
                out.append(json.loads(mf.read_text(encoding="utf-8")))
                continue
            except Exception:
                pass
        shards = sorted(p.name for p in sub.glob("*.chshard"))
        if shards:
            out.append({"backup_id": sub.name, "shards_present": shards, "peer_synced": False})
    return out
