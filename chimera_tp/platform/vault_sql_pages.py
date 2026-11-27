"""Version 2 SQLite replica protocol. Each reply carries a bounded set of complete pages."""

from __future__ import annotations

import base64
from contextlib import closing, contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import struct
import tempfile
import time
import zlib

from .agent_workspace import LeaseBusy, _lock


FRAME_BYTES = 1024 * 1024
DATABASE_BYTES = 8 * 1024 ** 3
HASH = re.compile(r"[0-9a-f]{64}")
RETAIN_IMAGES = 3
U32 = struct.Struct(">I")


class BaseMismatch(ValueError):
    """The receiver lacks the exact committed base for this response."""


class SnapshotExpired(ValueError):
    """An immutable image required for the next part is no longer available."""


@contextmanager
def exclusive(path):
    """Reuse the crash-released file lock also used by workspace leases."""
    deadline = time.monotonic() + 60
    while True:
        cm = _lock(path)
        try:
            cm.__enter__()
        except LeaseBusy:
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Vault-SQL busy: {path.name}")
            time.sleep(0.025)
            continue
        break
    try:
        yield
    finally:
        cm.__exit__(None, None, None)


def file_digest(path, legacy=False):
    with path.open("rb") as stream:
        algorithm = (lambda: hashlib.blake2s(digest_size=16)) if legacy else "sha256"
        return hashlib.file_digest(stream, algorithm).hexdigest()


def page_width(path):
    with path.open("rb") as stream:
        header = stream.read(100)
    if len(header) != 100 or header[:16] != b"SQLite format 3\0":
        raise ValueError("invalid SQLite file header")
    field = int.from_bytes(header[16:18], "big")
    width = 65536 if field == 1 else field
    if not 512 <= width <= 65536 or width & (width - 1):
        raise ValueError("invalid SQLite page size")
    return width


def online_copy(source, destination):
    """Pin one committed read transaction, including WAL pages, for the entire backup."""
    uri = source.resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, timeout=5)) as src, closing(sqlite3.connect(destination)) as dst:
        src.execute("BEGIN")
        count = src.execute("PRAGMA page_count").fetchone()[0]
        width = src.execute("PRAGMA page_size").fetchone()[0]
        if count * width > DATABASE_BYTES:
            raise ValueError("Vault-SQL database exceeds snapshot budget")
        # Only the completed image leaves this unique staging directory.
        dst.execute("PRAGMA journal_mode=OFF")
        dst.execute("PRAGMA synchronous=OFF")
        src.backup(dst, pages=256)


def _stamps(paths):
    result = []
    for path in paths:
        try:
            st = path.stat()
            result.append((st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns))
        except FileNotFoundError:
            result.append(None)
    return result


def _witness(source):
    # The absence of a write-ahead or rollback journal is part of the identity.
    paths = (source, Path(str(source) + "-wal"), Path(str(source) + "-journal"))
    stamps = _stamps(paths)
    try:
        digests = [file_digest(path) if present else None for path, present in zip(paths, stamps)]
    except FileNotFoundError:
        return paths, None, None
    if stamps != _stamps(paths):
        return paths, None, None
    return paths, stamps, digests


def _current(cache, source):
    sidecar = cache / "source.json"
    paths, stamps, witness = _witness(source)
    try:
        saved = json.loads(sidecar.read_text("utf-8"))
        previous = saved["snapshot"]
        if (witness is not None and witness == saved["files"] and HASH.fullmatch(previous)
                and file_digest(cache / (previous + ".sqlite")) == previous):
            return previous, False
    except (OSError, KeyError, ValueError, TypeError):
        pass
    with tempfile.TemporaryDirectory(prefix="copy-", dir=cache) as name:
        fresh = Path(name) / "backup.db"
        online_copy(source, fresh)
        identity = file_digest(fresh)
        path = cache / (identity + ".sqlite")
        if not path.exists() or file_digest(path) != identity:
            os.replace(fresh, path)
        else:
            path.touch()
        if witness is not None and _stamps(paths) == stamps:
            private = Path(name) / "witness.json"
            private.write_text(json.dumps({"snapshot": identity, "files": witness}), encoding="utf-8")
            os.replace(private, sidecar)
        return identity, True


def export_part(cache, source, since="", target="", start=0):
    if not isinstance(since, str) or not isinstance(target, str):
        raise ValueError("invalid snapshot identity")
    if target and not HASH.fullmatch(target):
        raise ValueError("invalid pinned snapshot SHA-256")
    if type(start) is not int or start < 0 or (start and not target):
        raise ValueError("invalid initial page offset")
    cache.mkdir(parents=True, exist_ok=True)
    with exclusive(cache / "export.lock"):
        identity, materialized = (target, False) if target else _current(cache, source)
        image = cache / (identity + ".sqlite")
        if not image.is_file():
            raise SnapshotExpired("pinned SQLite image expired")
        width, size = page_width(image), image.stat().st_size
        if size % width or not 0 < size <= DATABASE_BYTES or start >= size // width:
            raise ValueError("invalid snapshot geometry or cursor")
        base = cache / (since + ".sqlite") if HASH.fullmatch(since) else None
        if base and (not base.is_file() or page_width(base) != width):
            base = None
        if target and since and base is None:
            raise SnapshotExpired("pinned SQLite delta base expired")
        mode = "unchanged" if since == identity else ("delta" if base else "full")
        part = {"protocol": 2, "mode": mode, "sha256": identity, "base_sha256": since if base else "",
                "raw_bytes": size, "page_size": width, "start_page": start, "end_page": size // width,
                "changed_pages": 0, "compressed_bytes": 0, "wire_bytes": 0, "unchanged": mode == "unchanged",
                "source_backup_created": materialized}
        if mode != "unchanged":
            records, end = _read_pages(image, base, start, width, size // width)
            encoded = zlib.compress(records, 1)
            data = base64.b64encode(encoded).decode("ascii")
            part.update(data_b64=data, end_page=end, changed_pages=len(records) // (width + U32.size),
                        compressed_bytes=len(encoded), wire_bytes=len(data))
        keep = {image, base}
        for path in sorted(cache.glob("*.sqlite"), key=lambda p: p.stat().st_mtime_ns, reverse=True):
            if path in keep or len(keep - {None}) < RETAIN_IMAGES:
                keep.add(path)
            else:
                path.unlink()
        return part


def _read_pages(image, base, start, width, count):
    records = bytearray()
    with image.open("rb") as src, (base or image).open("rb") as prev:
        src.seek(start * width)
        prev.seek(start * width)
        for page_id in range(start, count):
            page = src.read(width)
            if len(page) != width:
                raise ValueError("short immutable SQLite image")
            if base and prev.read(width) == page:
                continue
            if len(records) + width + U32.size > FRAME_BYTES:
                return records, page_id
            records.extend(U32.pack(page_id))
            records.extend(page)
    return records, count


def inflate(data, expected):
    if not isinstance(data, str) or len(data) > (FRAME_BYTES + 4096) * 4 // 3 + 4:
        raise ValueError("oversize SQLite page frame")
    compressed = base64.b64decode(data, validate=True)
    decoder = zlib.decompressobj()
    raw = decoder.decompress(compressed, expected + 1)
    if len(raw) != expected or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
        raise ValueError("invalid compressed SQLite page frame")
    return raw, len(compressed)


def geometry(part):
    if type(part.get("protocol")) is not int or part["protocol"] != 2:
        raise ValueError("invalid SQLite snapshot protocol")
    width, size = part.get("page_size"), part.get("raw_bytes")
    if (type(width) is not int or not 512 <= width <= 65536 or width & (width - 1)
            or type(size) is not int or not 0 < size <= DATABASE_BYTES or size % width):
        raise ValueError("invalid SQLite page geometry")
    target, base, mode = part.get("sha256"), part.get("base_sha256"), part.get("mode")
    if not isinstance(target, str) or not HASH.fullmatch(target) or mode not in ("unchanged", "delta", "full"):
        raise ValueError("invalid SQLite snapshot identity or mode")
    if not isinstance(base, str) or (mode == "full" and base) or (mode != "full" and not HASH.fullmatch(base)):
        raise ValueError("invalid SQLite base identity")
    if (mode == "unchanged") != (base == target) or part.get("unchanged") is not (mode == "unchanged"):
        raise ValueError("inconsistent SQLite snapshot identities")
    return target, base, mode, width, size


def apply_part(stream, part, expected_geometry, start):
    if geometry(part) != expected_geometry or part.get("start_page") != start:
        raise ValueError("SQLite page response changed generation or cursor")
    _, _, mode, width, size = expected_geometry
    end, changed = part.get("end_page"), part.get("changed_pages")
    if (type(part["start_page"]) is not int or type(end) is not int or not start < end <= size // width
            or type(changed) is not int or not 0 <= changed <= end-start or changed*(U32.size+width) > FRAME_BYTES):
        raise ValueError("invalid SQLite page frame boundaries")
    if mode == "full" and changed != end - start:
        raise ValueError("full SQLite snapshot omitted pages")
    data = part.get("data_b64")
    raw, compressed = inflate(data, changed * (U32.size + width))
    if part.get("compressed_bytes") != compressed or part.get("wire_bytes") != len(data):
        raise ValueError("incorrect SQLite frame byte counts")
    view = memoryview(raw)
    previous = start - 1
    for offset in range(0, len(raw), width + U32.size):
        number = U32.unpack_from(raw, offset)[0]
        if not previous < number < end:
            raise ValueError("unordered or out-of-range SQLite page")
        stream.seek(number * width)
        stream.write(view[offset + U32.size:offset + U32.size + width])
        previous = number
    return end
