"""Breakthrough #7: Zero-Weight Merkle Directory DNA Sync & 0-RTT Shadow Index."""

from __future__ import annotations

import hashlib
import json
import os
import re
import struct
import time
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

_MERKLE_PATCH_MAGIC = b"CHMRK1"

DEFAULT_IGNORE_DIRS = frozenset(
    {
        ".git",
        "__pycache__",
        "node_modules",
        "target",
        ".venv",
        "venv",
        ".chimera_vault",
        ".pytest_cache",
        "dist",
        "build",
        ".mypy_cache",
    }
)
DEFAULT_IGNORE_EXTS = frozenset({".pyc", ".pyo", ".dll", ".so", ".pdb", ".lib", ".exp", ".tmp"})


def sanitize_workspace_id(ws_id: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9._-]", "_", str(ws_id or "default")).strip("._")
    if not clean or ".." in clean:
        clean = "default"
    return clean[:64]


def _hash_file_blake2b(path: Path) -> str:
    h = hashlib.blake2b(digest_size=16)
    with path.open("rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


@dataclass
class MerkleSnapshot:
    root_hash: str
    dir_hashes: dict[str, str]
    files: dict[str, dict[str, Any]]
    total_files: int
    total_bytes: int
    scan_ms: float
    rehashed_files: int

    def to_manifest(self) -> dict[str, Any]:
        return {
            "root_hash": self.root_hash,
            "total_files": self.total_files,
            "total_bytes": self.total_bytes,
            "scan_ms": self.scan_ms,
            "rehashed_files": self.rehashed_files,
            "files": self.files,
        }


class ShadowMerkleIndex:
    """Zero-polling on-demand stat cache + Merkle tree avoiding reading unchanged files."""

    def __init__(self, shadow_path: Path | None = None) -> None:
        self.shadow_path = Path(shadow_path) if shadow_path is not None else None
        self._cached: dict[str, dict[str, Any]] = {}
        if self.shadow_path is not None and self.shadow_path.exists():
            try:
                raw = json.loads(self.shadow_path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    self._cached = raw.get("files", {})
            except Exception:
                self._cached = {}

    def scan(
        self,
        root: Path,
        ignore_dirs: frozenset[str] = DEFAULT_IGNORE_DIRS,
        ignore_exts: frozenset[str] = DEFAULT_IGNORE_EXTS,
        max_files: int = 5000,
    ) -> MerkleSnapshot:
        t0 = time.perf_counter()
        root = Path(root).resolve()
        if not root.exists():
            root.mkdir(parents=True, exist_ok=True)

        files: dict[str, dict[str, Any]] = {}
        total_bytes = 0
        rehashed = 0

        candidates: list[Path] = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(d for d in dirnames if d not in ignore_dirs)
            for fn in sorted(filenames):
                p = Path(dirpath) / fn
                if p.suffix.lower() in ignore_exts:
                    continue
                candidates.append(p)
                if len(candidates) >= max_files:
                    break
            if len(candidates) >= max_files:
                break

        for fp in candidates:
            rel = fp.relative_to(root).as_posix()
            st = fp.stat()
            size = int(st.st_size)
            mtime_ns = int(st.st_mtime_ns)
            prev = self._cached.get(rel)
            if (
                prev is not None
                and int(prev.get("size", -1)) == size
                and int(prev.get("mtime_ns", -1)) == mtime_ns
                and prev.get("hash")
            ):
                fhash = str(prev["hash"])
            else:
                fhash = _hash_file_blake2b(fp)
                rehashed += 1
            files[rel] = {"size": size, "mtime_ns": mtime_ns, "hash": fhash}
            total_bytes += size

        # Build deterministic bottom-up directory hashes
        dir_entries: dict[str, list[str]] = {"": []}
        for rel in sorted(files):
            meta = files[rel]
            parent = str(Path(rel).parent.as_posix())
            if parent == ".":
                parent = ""
            parts = Path(rel).parts[:-1]
            cur = ""
            for part in parts:
                nxt = f"{cur}/{part}" if cur else part
                dir_entries.setdefault(cur, []).append(f"D:{part}")
                dir_entries.setdefault(nxt, [])
                cur = nxt
            dir_entries.setdefault(parent, []).append(f"F:{Path(rel).name}:{meta['size']}:{meta['hash']}")

        dir_hashes: dict[str, str] = {}
        for d in sorted(dir_entries.keys(), key=lambda s: (-s.count("/"), -len(s), s)):
            h = hashlib.blake2b(digest_size=16)
            seen = sorted(set(dir_entries[d]))
            for entry in seen:
                if entry.startswith("D:"):
                    sub_name = entry[2:]
                    sub_path = f"{d}/{sub_name}" if d else sub_name
                    h.update(f"D:{sub_name}:{dir_hashes.get(sub_path, '')}\n".encode("utf-8"))
                else:
                    h.update(f"{entry}\n".encode("utf-8"))
            dir_hashes[d] = h.hexdigest()

        root_hash = dir_hashes.get("", hashlib.blake2b(b"empty", digest_size=16).hexdigest())
        self._cached = files
        scan_ms = round((time.perf_counter() - t0) * 1000.0, 2)

        if self.shadow_path is not None:
            self.shadow_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.shadow_path.with_suffix(".json.tmp")
            tmp.write_text(
                json.dumps({"root_hash": root_hash, "files": files}, ensure_ascii=False),
                encoding="utf-8",
            )
            os.replace(tmp, self.shadow_path)

        return MerkleSnapshot(
            root_hash=root_hash,
            dir_hashes=dir_hashes,
            files=files,
            total_files=len(files),
            total_bytes=total_bytes,
            scan_ms=scan_ms,
            rehashed_files=rehashed,
        )


def diff_manifests(local_files: dict[str, dict[str, Any]], local_root: str, remote_files: dict[str, dict[str, Any]], remote_root: str) -> dict[str, Any]:
    """Compare local vs remote Merkle manifests using size+hash (cross-OS clock independent)."""
    total_bytes = sum(int(v["size"]) for v in local_files.values())
    if local_root == remote_root and len(local_files) == len(remote_files):
        return {
            "identical": True,
            "changed_files": [],
            "deleted_files": [],
            "unchanged_files": len(local_files),
            "changed_bytes": 0,
            "total_bytes": total_bytes,
        }

    changed: list[str] = []
    unchanged = 0
    changed_bytes = 0
    for rel in sorted(local_files):
        lm = local_files[rel]
        rm = remote_files.get(rel)
        if rm is not None and int(rm.get("size", -1)) == int(lm["size"]) and rm.get("hash") == lm["hash"]:
            unchanged += 1
        else:
            changed.append(rel)
            changed_bytes += int(lm["size"])

    deleted = sorted(rel for rel in remote_files if rel not in local_files)
    identical = (not changed) and (not deleted)
    return {
        "identical": identical,
        "changed_files": changed,
        "deleted_files": deleted,
        "unchanged_files": unchanged,
        "changed_bytes": changed_bytes,
        "total_bytes": total_bytes,
    }


def pack_merkle_patch(root: Path, changed_files: list[str], deleted_files: list[str]) -> bytes:
    """Serialize ONLY changed files + delete tombstones into b'CHMRK1' bundle."""
    root = Path(root).resolve()
    hdr_json = json.dumps(
        {"deleted": list(deleted_files), "count": len(changed_files)},
        ensure_ascii=False,
    ).encode("utf-8")

    out = bytearray(_MERKLE_PATCH_MAGIC)
    out.extend(struct.pack("<I", len(hdr_json)))
    out.extend(hdr_json)

    for rel in changed_files:
        fp = (root / rel).resolve()
        if root not in fp.parents:
            raise ValueError(f"Path traversal rejected while packing: {rel}")
        data = fp.read_bytes()
        rel_b = rel.encode("utf-8")
        sha = hashlib.sha256(data).digest()
        out.extend(struct.pack("<HQ", len(rel_b), len(data)))
        out.extend(rel_b)
        out.extend(sha)
        out.extend(data)
    return bytes(out)


def unpack_merkle_patch(bundle: bytes, out_dir: Path) -> dict[str, Any]:
    """Apply b'CHMRK1' sparse delta bundle into out_dir safely and return new Merkle root."""
    if not bundle.startswith(_MERKLE_PATCH_MAGIC):
        raise ValueError("Invalid CHMRK1 Merkle patch magic")
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    pos = len(_MERKLE_PATCH_MAGIC)
    (hdr_len,) = struct.unpack_from("<I", bundle, pos)
    pos += 4
    meta = json.loads(bundle[pos : pos + hdr_len].decode("utf-8"))
    pos += hdr_len

    deleted_done: list[str] = []
    for rel_del in meta.get("deleted", []):
        target_del = (out_dir / str(rel_del)).resolve()
        if out_dir not in target_del.parents:
            raise ValueError(f"Path traversal rejected on delete: {rel_del}")
        if target_del.is_file():
            target_del.unlink()
            deleted_done.append(str(rel_del))

    mv = memoryview(bundle)
    count = int(meta.get("count", 0))
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
            raise ValueError(f"SHA-256 mismatch unpacking {rel_str}")
        target = (out_dir / rel_str).resolve()
        if out_dir not in target.parents:
            raise ValueError(f"Path traversal rejected on unpack: {rel_str}")
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(f".{target.name}.tmp")
        tmp.write_bytes(data)
        os.replace(tmp, target)
        written.append(rel_str)

    snap = ShadowMerkleIndex().scan(out_dir)
    return {
        "written": written,
        "deleted": deleted_done,
        "root_hash": snap.root_hash,
        "total_files": snap.total_files,
        "total_bytes": snap.total_bytes,
    }


def _post_json(url: str, obj: dict[str, Any], timeout_s: float = 8.0) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        data=json.dumps(obj, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        return json.loads(resp.read().decode("utf-8"))


def merkle_beam_sync(
    peer_http_base: str,
    peer_beam_addr: tuple[str, int],
    local_dir: Path,
    workspace_id: str,
    vault_dir: Path,
    shadow_dir: Path,
    est_loss: float = 0.02,
    timeout_s: float = 25.0,
) -> dict[str, Any]:
    """Perform 0-RTT hash check + sparse FastCDC/Odess Merkle directory sync to remote BeamServer."""
    from .fabric import beam_send_merkle_patch

    t0 = time.perf_counter()
    ws = sanitize_workspace_id(workspace_id)
    local_dir = Path(local_dir).resolve()
    shadow = ShadowMerkleIndex(Path(shadow_dir) / f"{ws}.json")
    snap = shadow.scan(local_dir)

    diff_resp = _post_json(
        f"{peer_http_base.rstrip('/')}/api/merkle/diff",
        {"workspace_id": ws, "root_hash": snap.root_hash, "files": snap.files},
        timeout_s=min(10.0, timeout_s),
    )

    if diff_resp.get("identical"):
        elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        return {
            "workspace_id": ws,
            "noop": True,
            "scan_ms": snap.scan_ms,
            "rehashed_files": snap.rehashed_files,
            "total_files": snap.total_files,
            "total_bytes": snap.total_bytes,
            "changed_files": 0,
            "deleted_files": 0,
            "patch_raw_bytes": 0,
            "udp_wire_bytes": 0,
            "total_reduction_pct": 100.0,
            "elapsed_ms": elapsed_ms,
            "local_root_hash": snap.root_hash,
            "remote_root_hash": diff_resp.get("remote_root_hash", snap.root_hash),
            "verified_root_match": True,
        }

    changed_list = list(diff_resp.get("changed_files", []))
    deleted_list = list(diff_resp.get("deleted_files", []))
    patch_bytes = pack_merkle_patch(local_dir, changed_list, deleted_list)

    brep = beam_send_merkle_patch(
        peer_beam_addr,
        workspace_id=ws,
        patch_bytes=patch_bytes,
        vault_dir=vault_dir,
        est_loss=est_loss,
        timeout_s=timeout_s,
    )

    verify_resp = _post_json(
        f"{peer_http_base.rstrip('/')}/api/merkle/diff",
        {"workspace_id": ws, "root_hash": snap.root_hash, "files": snap.files},
        timeout_s=min(10.0, timeout_s),
    )
    elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
    red_pct = (
        max(0.0, 100.0 * (1.0 - (brep.udp_wire_bytes / snap.total_bytes)))
        if snap.total_bytes > 0
        else 100.0
    )
    return {
        "workspace_id": ws,
        "noop": False,
        "scan_ms": snap.scan_ms,
        "rehashed_files": snap.rehashed_files,
        "total_files": snap.total_files,
        "total_bytes": snap.total_bytes,
        "changed_files": len(changed_list),
        "deleted_files": len(deleted_list),
        "unchanged_files": int(diff_resp.get("unchanged_files", 0)),
        "patch_raw_bytes": len(patch_bytes),
        "dna_wire_bytes": brep.dna_wire_bytes,
        "udp_wire_bytes": brep.udp_wire_bytes,
        "total_reduction_pct": round(red_pct, 2),
        "elapsed_ms": elapsed_ms,
        "local_root_hash": snap.root_hash,
        "remote_root_hash": verify_resp.get("remote_root_hash", ""),
        "verified_root_match": bool(verify_resp.get("identical")),
    }
