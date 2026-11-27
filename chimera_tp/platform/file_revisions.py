"""Transactional content-defined revisions for explicitly selected files."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
import time
import zipfile
import zlib
from contextlib import closing
from pathlib import Path

from ..native import fastcdc_split


def _chunks(stream):
    pending = b""
    while block := stream.read(1024 * 1024):
        data = pending + block
        spans = fastcdc_split(data)
        for start, end in spans[:-1]:
            yield data[start:end]
        pending = data[spans[-1][0]:]
    if pending:
        yield pending


def _identity(stat):
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns


class FileRevisions:
    def __init__(self, database: Path):
        self.database = Path(database).resolve()
        self.database.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as db, db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS chunks (id TEXT PRIMARY KEY, data BLOB NOT NULL);
                CREATE TABLE IF NOT EXISTS revisions (
                    id TEXT PRIMARY KEY, size INTEGER NOT NULL, parts TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS saves (
                    seq INTEGER PRIMARY KEY, source TEXT NOT NULL, revision TEXT NOT NULL,
                    saved_utc TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
            """)

    def connect(self):
        return sqlite3.connect(self.database, timeout=15)

    def capture(self, source: Path) -> dict:
        source = Path(source).resolve(strict=True)
        if source == self.database or not source.is_file():
            raise ValueError("select a regular input file distinct from the revision database")
        with closing(self.connect()) as db, db, source.open("rb") as stream:
            before = _identity(os.fstat(stream.fileno()))
            digest = hashlib.sha256()
            parts, added, size = [], 0, 0
            for part in _chunks(stream):
                digest.update(part)
                size += len(part)
                cid = hashlib.sha256(part).hexdigest()
                parts.append(cid)
                inserted = db.execute("INSERT OR IGNORE INTO chunks VALUES(?,?)", (cid, part))
                added += inserted.rowcount * len(part)
            if before != _identity(source.stat()) or before != _identity(os.fstat(stream.fileno())):
                raise OSError("input changed during capture; retry after the application finishes saving")
            revision = digest.hexdigest()
            db.execute("INSERT OR IGNORE INTO revisions VALUES(?,?,?)", (revision, size, json.dumps(parts)))
            seq = db.execute("INSERT INTO saves(source,revision) VALUES(?,?)", (str(source), revision)).lastrowid
        return {"revision": revision, "save": seq, "bytes": size, "added_bytes": added, "chunks": len(parts)}

    @staticmethod
    def _manifest(db, revision):
        row = db.execute("SELECT size,parts FROM revisions WHERE id=?", (revision,)).fetchone()
        if row is None:
            raise ValueError("revision missing from this store")
        return row[0], json.loads(row[1])

    def history(self, source: Path) -> list:
        with closing(self.connect()) as db:
            rows = db.execute("SELECT seq,revision,saved_utc FROM saves WHERE source=? ORDER BY seq DESC",
                              (str(Path(source).resolve()),))
            return [{"save": s, "revision": r, "saved_utc": t} for s, r, t in rows]

    def watch(self, source: Path, seconds: int):
        """Watch the containing directory to catch replace-on-save as well as in-place writes."""
        import ctypes
        from ctypes import wintypes

        if os.name != "nt" or not 1 <= seconds <= 86400:
            raise ValueError("event watching requires Windows and a duration of 1..86400 seconds")
        source = source.resolve(strict=True)
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.FindFirstChangeNotificationW.argtypes = [wintypes.LPCWSTR, wintypes.BOOL, wintypes.DWORD]
        k.FindFirstChangeNotificationW.restype = wintypes.HANDLE
        k.FindNextChangeNotification.argtypes = [wintypes.HANDLE]
        k.FindCloseChangeNotification.argtypes = [wintypes.HANDLE]
        k.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        handle = k.FindFirstChangeNotificationW(str(source.parent), False, 0x1 | 0x8 | 0x10)
        if handle in (None, ctypes.c_void_p(-1).value):
            raise ctypes.WinError(ctypes.get_last_error())
        until = time.monotonic() + seconds
        saves, missed = 0, 0
        previous = None
        try:
            while time.monotonic() < until:
                retry = False
                try:
                    current = _identity(source.stat())
                    if current != previous:
                        self.capture(source)
                        previous, saves = current, saves + 1
                except OSError:
                    missed += 1
                    retry = True
                remaining = max(0, int((until - time.monotonic()) * 1000))
                status = k.WaitForSingleObject(handle, min(250, remaining) if retry else remaining)
                if status == 258:
                    if time.monotonic() + 0.002 >= until:
                        break
                    continue
                if status or not k.FindNextChangeNotification(handle):
                    raise ctypes.WinError(ctypes.get_last_error())
        finally:
            k.FindCloseChangeNotification(handle)
        return {"captured": saves, "transient_read_errors": missed}

    def prewarm(self, source: Path, budget: int = 8 * 1024 * 1024):
        """Read a bounded sample of files previously saved close together in this project."""
        if not 0 < budget <= 64 * 1024 * 1024:
            raise ValueError("budget must be between 1 and 64 MiB in bytes")
        source = source.resolve(strict=True)
        with closing(self.connect()) as db:
            candidates = db.execute("""SELECT b.source, count(*) AS weight FROM saves a JOIN saves b
                ON b.seq BETWEEN a.seq-4 AND a.seq+4 AND b.source != a.source
                WHERE a.source=? AND abs(unixepoch(a.saved_utc)-unixepoch(b.saved_utc)) <= 300
                GROUP BY b.source ORDER BY weight DESC LIMIT 8""", (str(source),)).fetchall()
        read, files = 0, []
        for name, _ in candidates:
            path = Path(name).resolve()
            if path.parent != source.parent or not path.is_file() or path == self.database:
                continue
            with path.open("rb") as stream:
                while read < budget:
                    data = stream.read(min(65536, budget - read))
                    if not data:
                        break
                    read += len(data)
            files.append(str(path))
            if read >= budget:
                break
        return {"files": files, "bytes_read": read}

    def restore(self, revision: str, output: Path) -> dict:
        output = Path(output)
        with closing(self.connect()) as db:
            size, parts = self._manifest(db, revision)
            with tempfile.NamedTemporaryFile(dir=output.parent, delete=False) as tmp:
                temp = Path(tmp.name)
            try:
                digest = hashlib.sha256()
                with temp.open("wb") as stream:
                    for cid in parts:
                        part = db.execute("SELECT data FROM chunks WHERE id=?", (cid,)).fetchone()[0]
                        digest.update(part)
                        stream.write(part)
                if digest.hexdigest() != revision or temp.stat().st_size != size:
                    raise ValueError("restored content failed integrity check")
                os.link(temp, output)
            finally:
                temp.unlink(missing_ok=True)
        return {"revision": revision, "bytes": size, "output": str(output)}

    def export(self, revision: str, output: Path, base: str | None = None, *, force_delta=False) -> dict:
        """Write the smaller valid package, keeping full and delta .zip formats interoperable."""
        if force_delta and not base:
            raise ValueError("a forced delta requires a known base")
        with closing(self.connect()) as db, tempfile.TemporaryDirectory(
                dir=output.parent, prefix=".revision-export-") as temp:
            size, parts = self._manifest(db, revision)
            full = {"sha256": revision, "bytes": size, "parts": parts}
            all_chunks = set(parts)

            def write(mode, manifest, chunks):
                stage = Path(temp) / (mode + ".zip")
                with zipfile.ZipFile(stage, "w") as bundle:
                    bundle.writestr("revision.json", json.dumps(manifest), compress_type=zipfile.ZIP_DEFLATED)
                    for cid in sorted(chunks):
                        data = db.execute("SELECT data FROM chunks WHERE id=?", (cid,)).fetchone()[0]
                        bundle.writestr(cid, data)
                return stage

            def manifest_cost(manifest):
                encoder = zlib.compressobj(wbits=-15)
                return len(encoder.compress(json.dumps(manifest).encode()) + encoder.flush())

            mode, manifest, selected = "full", full, all_chunks
            stage = None
            if base:
                _, previous = self._manifest(db, base)
                common = min(len(previous), len(parts))
                prefix = suffix = 0
                while prefix < common and parts[prefix] == previous[prefix]:
                    prefix += 1
                while suffix < common - prefix and parts[-suffix - 1] == previous[-suffix - 1]:
                    suffix += 1
                delta = {**full, "base": base, "prefix": prefix, "suffix": suffix,
                         "parts": parts[prefix:len(parts) - suffix]}
                missing = all_chunks.difference(previous)
                delta_size, full_size = manifest_cost(delta), manifest_cost(full)
                if force_delta or delta_size < full_size or (delta_size == full_size and missing != all_chunks):
                    mode, manifest, selected = "delta", delta, missing
                elif missing != all_chunks:
                    # The smaller manifest and smaller chunk set belong to opposite
                    # candidates. Measure finished ZIPs including their ZIP64 metadata.
                    a, b = write("delta", delta, missing), write("full", full, all_chunks)
                    if a.stat().st_size < b.stat().st_size:
                        mode, manifest, selected, stage = "delta", delta, missing, a
                    else:
                        stage = b
            stage = stage or write(mode, manifest, selected)
            os.link(stage, output)
            return {"archive_bytes": output.stat().st_size, "included_chunks": len(selected),
                    "base": base if mode == "delta" else None, "mode": mode}

    @classmethod
    def _read_bundle(cls, bundle, db, expected_full):
        if bundle.getinfo("revision.json").file_size > 8 * 1024 * 1024:
            raise ValueError("manifest too large")
        manifest = json.loads(bundle.read("revision.json"))
        if not isinstance(manifest, dict) or not isinstance(manifest.get("parts"), list):
            raise ValueError("invalid chunk list")
        parts = manifest["parts"]
        if expected_full is not None:
            if "base" in manifest or (manifest["sha256"], manifest["bytes"]) != expected_full:
                raise ValueError("workspace_revision_mismatch")
        elif "base" in manifest:
            _, previous = cls._manifest(db, manifest["base"])
            prefix, suffix = manifest["prefix"], manifest["suffix"]
            if not (type(prefix) is int and type(suffix) is int and min(prefix, suffix) >= 0
                    and prefix + suffix <= len(previous)):
                raise ValueError("invalid base range")
            parts = previous[:prefix] + parts + previous[len(previous) - suffix:]
        if any(not isinstance(cid, str) or len(cid) != 64 or
               any(c not in "0123456789abcdef" for c in cid) for cid in parts):
            raise ValueError("invalid chunk identity")
        if expected_full is not None:
            members = {"revision.json", *parts}
            if len(bundle.infolist()) != len(members) or set(bundle.namelist()) != members:
                raise ValueError("workspace_revision_inventory_mismatch")
        digest, size = hashlib.sha256(), 0
        for cid in parts:
            # A portable full revision must prove its own chunks on every receiver,
            # even if this receiver already has those bytes in its local store.
            cached = None
            if db is not None and expected_full is None:
                cached = db.execute("SELECT data FROM chunks WHERE id=?", (cid,)).fetchone()
            if cached is not None:
                part = cached[0]
            else:
                if bundle.getinfo(cid).file_size > 65536:
                    raise ValueError("chunk too large")
                part = bundle.read(cid)
                if hashlib.sha256(part).hexdigest() != cid:
                    raise ValueError("chunk digest mismatch")
                if db is not None:
                    db.execute("INSERT OR IGNORE INTO chunks VALUES(?,?)", (cid, part))
            size += len(part)
            if expected_full is not None and size > expected_full[1]:
                raise ValueError("workspace_revision_size_mismatch")
            digest.update(part)
        revision = digest.hexdigest()
        if revision != manifest["sha256"] or size != manifest["bytes"]:
            raise ValueError("revision identity mismatch")
        return revision, size, parts

    @classmethod
    def verify_full(cls, archive, *, revision: str, size: int):
        """Validate every byte of a portable revision without populating a store."""
        with zipfile.ZipFile(archive) as bundle:
            cls._read_bundle(bundle, None, (revision, size))

    def receive(self, archive, *, expected_full=None) -> dict:
        with zipfile.ZipFile(archive) as bundle, closing(self.connect()) as db, db:
            revision, size, parts = self._read_bundle(bundle, db, expected_full)
            db.execute("INSERT OR IGNORE INTO revisions VALUES(?,?,?)", (revision, size, json.dumps(parts)))
        return {"revision": revision, "bytes": size}
