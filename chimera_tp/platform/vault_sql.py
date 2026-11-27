"""CHIMERA-VAULT-SQL: Single-Writer Cross-Node SQLite Replica Fabric (<0.3 ms local reads, 0 lock errors)."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import zlib
from datetime import datetime
from pathlib import Path
from typing import Any

from . import vault_sql_pages as pages


_SAFE_NAME_RE = re.compile(r"^[a-zA-Z0-9_\-.]{1,48}$")
_READONLY_SQL_RE = re.compile(r"^\s*(SELECT|WITH|EXPLAIN\s+QUERY\s+PLAN|PRAGMA\s+table_info|PRAGMA\s+table_list)\b", re.I)
_FORBIDDEN_SQL_RE = re.compile(r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|REPLACE|ATTACH|DETACH|VACUUM|REINDEX)\b", re.I)
_LEGACY_RAW_LIMIT = 256 * 1024 ** 2


class VaultSqlFabric:
    """Online WAL-safe SQLite snapshot/delta sync (primary -> local read-only replica) with sub-ms queries."""

    def __init__(self, replica_dir: Path, peer_base_resolver: Any = None) -> None:
        self.replica_dir = Path(replica_dir)
        self.replica_dir.mkdir(parents=True, exist_ok=True)
        self.peer_base_resolver = peer_base_resolver
        self._meta_path = self.replica_dir / "registry.json"
        self._lock = threading.Lock()
        self._dbs: dict[str, dict[str, Any]] = {}
        self._queries = 0
        self._syncs = 0
        self._bytes_saved = 0
        self._load()

    def _load(self) -> None:
        try:
            if self._meta_path.is_file():
                d = json.loads(self._meta_path.read_text(encoding="utf-8"))
                if isinstance(d, dict):
                    self._dbs = {str(k): dict(v) for k, v in d.items() if isinstance(v, dict)}
        except Exception:
            self._dbs = {}

    def _save_locked(self) -> None:
        tmp = self._meta_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._dbs, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self._meta_path)

    def _validate_name(self, name: str) -> str:
        n = str(name or "").strip()
        if not _SAFE_NAME_RE.match(n):
            raise ValueError(f"Invalid database name: {name!r}")
        return n

    def register_db(self, name: str, path: str | Path, role: str = "primary") -> dict[str, Any]:
        n = self._validate_name(name)
        p = Path(path).resolve()
        if role == "primary" and not p.is_file():
            raise FileNotFoundError(f"SQLite file not found: {p}")
        with pages.exclusive(self.replica_dir / "registry.lock"), self._lock:
            self._load()
            entry = {
                "name": n,
                "path": str(p),
                "role": "primary" if role == "primary" else "replica",
                "last_sha256": self._dbs.get(n, {}).get("last_sha256", ""),
                "last_sync": self._dbs.get(n, {}).get("last_sync", ""),
                "size_bytes": p.stat().st_size if p.is_file() else 0,
            }
            self._dbs[n] = entry
            self._save_locked()
            return {"ok": True, "db": dict(entry)}

    def export_snapshot(self, name: str, since_sha256: str = "", *, protocol=1,
                        target_sha256: str = "", start_page=0) -> dict[str, Any]:
        """Take an online WAL-safe backup of a registered primary SQLite DB and compress it."""
        t0 = time.perf_counter()
        n = self._validate_name(name)
        with self._lock:
            self._load()
            entry = self._dbs.get(n)
        if not entry:
            raise KeyError(f"Database '{n}' is not registered")
        src_path = Path(entry["path"])
        if not src_path.is_file():
            raise FileNotFoundError(f"SQLite file missing: {src_path}")
        if str(protocol) == "2":
            # Separate names and registered paths. A new primary cannot borrow an old generation.
            key = hashlib.sha256((n + "\0" + str(src_path)).encode()).hexdigest()
            try:
                part = pages.export_part(self.replica_dir / ".page-images" / key, src_path,
                                         since_sha256, target_sha256, int(start_page))
            except pages.SnapshotExpired:
                return {"ok": False, "error": "snapshot_expired", "protocol": 2}
            with self._lock:
                covered = (part["end_page"] - part["start_page"]) * part["page_size"]
                self._bytes_saved += max(0, covered - part["wire_bytes"])
            return {"ok": True, "name": n, **part, "elapsed_ms": round((time.perf_counter() - t0) * 1000, 2)}
        if str(protocol) != "1" or target_sha256 or int(start_page):
            raise ValueError("unsupported SQLite snapshot protocol")
        with tempfile.TemporaryDirectory(prefix="vault-legacy-") as directory:
            tmp_backup = Path(directory) / "copy.sqlite"
            pages.online_copy(src_path, tmp_backup)
            if tmp_backup.stat().st_size > _LEGACY_RAW_LIMIT:
                raise ValueError("legacy snapshot too large: request protocol 2")
            raw = tmp_backup.read_bytes()

        digest = hashlib.blake2s(raw, digest_size=16).hexdigest()
        if since_sha256 and since_sha256 == digest:
            with self._lock:
                self._bytes_saved += len(raw)
            return {
                "ok": True,
                "name": n,
                "unchanged": True,
                "sha256": digest,
                "raw_bytes": len(raw),
                "wire_bytes": 0,
                "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
            }

        comp = zlib.compress(raw, level=6)
        b64 = base64.b64encode(comp).decode("ascii")
        with self._lock:
            self._bytes_saved += max(0, len(raw) - len(comp))
        return {
            "ok": True,
            "name": n,
            "unchanged": False,
            "sha256": digest,
            "raw_bytes": len(raw),
            "compressed_bytes": len(comp),
            "wire_bytes": len(b64),
            "compression_ratio": round(len(raw) / max(1, len(comp)), 2),
            "data_b64": b64,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }

    def _record_replica(self, name, path, digest, unchanged, compressed):
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        size = path.stat().st_size
        with pages.exclusive(self.replica_dir / "registry.lock"), self._lock:
            self._load()
            self._syncs += 1
            self._dbs[name] = {"name": name, "path": str(path), "role": "replica",
                               "last_sha256": digest, "last_sync": now, "size_bytes": size}
            self._save_locked()
        return {"ok": True, "name": name, "path": str(path), "sha256": digest, "unchanged": unchanged,
                "raw_bytes": size, "compressed_bytes": compressed}

    def _install(self, name, snapshot, continuation=None):
        destination = self.replica_dir / f"{name}.replica.db"
        if snapshot.get("ok") is False:
            raise ValueError(snapshot.get("error", "invalid_snapshot"))
        if snapshot.get("protocol") == 2:
            shape = pages.geometry(snapshot)
            digest, base, mode, width, size = shape
            if mode != "full" and (not destination.is_file() or pages.file_digest(destination) != base):
                raise pages.BaseMismatch("SQLite replica no longer matches the requested base")
            if mode == "unchanged":
                if (destination.stat().st_size != size or snapshot.get("start_page") != 0
                        or snapshot.get("end_page") != size // width or snapshot.get("changed_pages") != 0
                        or snapshot.get("compressed_bytes") != 0 or snapshot.get("wire_bytes") != 0):
                    raise ValueError("invalid unchanged SQLite receipt")
                result = self._record_replica(name, destination, digest, True, 0)
                return {**result, "protocol": 2, "mode": mode, "parts": 1, "changed_pages": 0, "wire_bytes": 0,
                        "source_backup_created": snapshot.get("source_backup_created")}
            compressed = wire = changed = chunks = cursor = 0
            backup_created = snapshot.get("source_backup_created")
            with tempfile.TemporaryDirectory(prefix="vault-install-", dir=self.replica_dir) as directory:
                staged = Path(directory) / "next.sqlite"
                if mode == "delta":
                    shutil.copyfile(destination, staged)
                with staged.open("r+b" if mode == "delta" else "w+b") as out:
                    while cursor < size // width:
                        cursor = pages.apply_part(out, snapshot, shape, cursor)
                        compressed += snapshot["compressed_bytes"]
                        wire += snapshot["wire_bytes"]
                        changed += snapshot["changed_pages"]
                        chunks += 1
                        if cursor < size // width:
                            if continuation is None:
                                raise ValueError("incomplete SQLite snapshot: additional parts required")
                            snapshot = continuation(base, digest, cursor)
                    out.truncate(size)
                    out.flush()
                    os.fsync(out.fileno())
                if pages.file_digest(staged) != digest or pages.page_width(staged) != width:
                    raise ValueError("SQLite replica snapshot digest or page size mismatch")
                os.replace(staged, destination)
            result = self._record_replica(name, destination, digest, False, compressed)
            return {**result, "protocol": 2, "mode": mode, "parts": chunks, "changed_pages": changed,
                    "wire_bytes": wire, "source_backup_created": backup_created}
        if snapshot.get("protocol", 1) != 1:
            raise ValueError("unsupported SQLite snapshot protocol")
        digest = snapshot.get("sha256")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{32}", digest):
            raise ValueError("invalid legacy Vault-SQL snapshot digest")
        if snapshot.get("unchanged"):
            if not destination.is_file() or pages.file_digest(destination, legacy=True) != digest:
                raise pages.BaseMismatch("legacy SQLite replica missing or changed")
            return self._record_replica(name, destination, digest, True, 0)
        data = snapshot["data_b64"]
        if not isinstance(data, str) or len(data) > _LEGACY_RAW_LIMIT * 4 // 3 + 1024 ** 2:
            raise ValueError("legacy SQLite snapshot exceeds budget")
        codec = zlib.decompressobj()
        expected = snapshot.get("raw_bytes", _LEGACY_RAW_LIMIT)
        if type(expected) is not int or not 0 <= expected <= _LEGACY_RAW_LIMIT:
            raise ValueError("invalid legacy SQLite snapshot size")
        algorithm = hashlib.blake2s(digest_size=16)
        total = compressed = 0
        with tempfile.TemporaryDirectory(prefix="vault-install-", dir=self.replica_dir) as directory:
            staged = Path(directory) / "legacy.sqlite"
            with staged.open("xb") as out:
                for offset in range(0, len(data), 65536):
                    packed = base64.b64decode(data[offset:offset + 65536], validate=True)
                    compressed += len(packed)
                    if codec.eof and packed:
                        raise ValueError("trailing legacy SQLite frame")
                    while packed:
                        raw = codec.decompress(packed, min(262144, expected - total + 1))
                        packed = codec.unconsumed_tail
                        total += len(raw)
                        if total > expected or codec.unused_data:
                            raise ValueError("oversized or extended legacy SQLite frame")
                        algorithm.update(raw)
                        out.write(raw)
                out.flush()
                os.fsync(out.fileno())
            if (not codec.eof or algorithm.hexdigest() != digest
                    or ("raw_bytes" in snapshot and total != expected)):
                raise ValueError("legacy SQLite replica snapshot digest mismatch")
            os.replace(staged, destination)
        return self._record_replica(name, destination, digest, False, compressed)

    def install_replica_snapshot(self, name: str, snapshot: dict[str, Any]) -> dict[str, Any]:
        n = self._validate_name(name)
        with pages.exclusive(self.replica_dir / (n + ".sync.lock")):
            return self._install(n, snapshot)

    def sync_from_peer(self, name: str, peer_base: str | None = None) -> dict[str, Any]:
        t0 = time.perf_counter()
        n = self._validate_name(name)
        origin = (peer_base or (self.peer_base_resolver() if self.peer_base_resolver else "") or "").rstrip("/")
        if not origin:
            raise RuntimeError("No peer URL configured for Vault-SQL sync")
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

        def fetch(since, target="", start=0):
            qs = urllib.parse.urlencode({"name": n, "protocol": 2, "since_sha256": since,
                                         "target_sha256": target, "start_page": start})
            with opener.open(f"{origin}/v1/vault-sql/snapshot?{qs}", timeout=60.0) as response:
                # New peers use bounded frames. Allow the old endpoint to reply with a single legacy envelope.
                limit = pages.FRAME_BYTES * 2 if target else _LEGACY_RAW_LIMIT * 4 // 3 + 1024 ** 2
                length = response.headers.get("Content-Length")
                if length and int(length) > limit:
                    raise ValueError("oversized Vault-SQL HTTP reply")
                raw = response.read(limit + 1)
                if len(raw) > limit:
                    raise ValueError("oversized Vault-SQL HTTP reply")
                answer = json.loads(raw)
            if not answer.get("ok"):
                if answer.get("error") == "snapshot_expired":
                    raise pages.SnapshotExpired(answer["error"])
                raise RuntimeError(answer.get("error", "peer_snapshot_failed"))
            return answer

        with pages.exclusive(self.replica_dir / (n + ".sync.lock")):
            replica = self.replica_dir / (n + ".replica.db")
            with self._lock:
                self._load()
                old = self._dbs.get(n, {}).get("last_sha256", "")
            # Old peers call a 128-bit BLAKE2s hash SHA-256. Keep their cache working during upgrades.
            legacy = isinstance(old, str) and bool(re.fullmatch(r"[0-9a-f]{32}", old))
            since = pages.file_digest(replica, legacy=legacy) if replica.is_file() else ""
            try:
                result = self._install(n, fetch(since), fetch)
            except (pages.BaseMismatch, pages.SnapshotExpired):
                result = self._install(n, fetch(""), fetch)
                result["restarted_full"] = True
        return {**result, "peer_base": origin, "sync_ms": round((time.perf_counter() - t0) * 1000, 2)}

    def query_readonly(self, name: str, sql: str, params: list[Any] | None = None, limit: int = 200) -> dict[str, Any]:
        t0 = time.perf_counter()
        n = self._validate_name(name)
        q = str(sql or "").strip()
        if not _READONLY_SQL_RE.match(q) or _FORBIDDEN_SQL_RE.search(q) or ";" in q.rstrip(";"):
            raise ValueError("Only single read-only SELECT/WITH/PRAGMA table_info statements are allowed")
        with self._lock:
            entry = self._dbs.get(n)
        if not entry:
            raise KeyError(f"Database '{n}' is not registered")
        db_p = Path(entry["path"])
        if not db_p.is_file():
            raise FileNotFoundError(f"Database file missing: {db_p}")

        owned = entry.get("role") == "replica" and db_p == self.replica_dir / f"{n}.replica.db"
        uri = db_p.resolve().as_uri() + ("?mode=ro&immutable=1" if owned else "?mode=ro")
        conn = sqlite3.connect(uri, uri=True, timeout=2.0)
        conn.row_factory = sqlite3.Row
        try:
            cur = conn.execute(q, list(params or []))
            rows = [dict(r) for r in cur.fetchmany(max(1, min(1000, int(limit))))]
        finally:
            conn.close()
        with self._lock:
            self._queries += 1
        return {
            "ok": True,
            "name": n,
            "role": entry["role"],
            "count": len(rows),
            "rows": rows,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 3),
        }

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "ok": True,
                "databases": [dict(v) for v in self._dbs.values()],
                "db_count": len(self._dbs),
                "queries": self._queries,
                "syncs": self._syncs,
                "bytes_saved": self._bytes_saved,
            }
