"""Immutable, explicitly selected source passages and a local FTS5 index."""

from __future__ import annotations

import codecs
import hashlib
import io
import json
import os
import sqlite3
import stat
import unicodedata
from contextlib import closing, contextmanager
from pathlib import Path
from urllib.parse import parse_qsl, quote, unquote, urlsplit, urlunsplit

from ..code_search import sanitize_fts_query


_SCHEMA = """
CREATE TABLE IF NOT EXISTS passages (
    id TEXT NOT NULL UNIQUE, scope TEXT NOT NULL, kind TEXT NOT NULL,
    source TEXT NOT NULL, locator TEXT NOT NULL, page INTEGER, line INTEGER,
    text TEXT NOT NULL, context TEXT NOT NULL, excerpt TEXT NOT NULL, sha256 TEXT,
    saved_utc TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE VIRTUAL TABLE IF NOT EXISTS passage_fts USING fts5(
    text, context, locator, source, content='', tokenize='unicode61 remove_diacritics 2'
);
"""
_SELECT = """
SELECT p.id, p.scope, p.kind, p.source, p.locator, p.page, p.line, p.text,
       p.context, p.excerpt, p.sha256, p.saved_utc
FROM passages p
"""


def _fold(value):
    value = unicodedata.normalize("NFD", value.casefold()).replace("đ", "d")
    return "".join(char for char in value if not unicodedata.combining(char))


def https_source(value):
    if not value or any(char.isspace() or ord(char) < 32 or char == "\\" for char in value):
        raise ValueError("provide an absolute HTTPS URL with URL-encoded spaces")
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username is not None:
        raise ValueError("provide an HTTPS URL without embedded credentials")
    if parsed.port == 0:
        raise ValueError("invalid HTTPS port")
    return parsed


def _local_path(path):
    path = Path(path).expanduser().absolute()
    if os.name == "nt":
        import ctypes

        if str(path).startswith("\\\\") or ctypes.windll.kernel32.GetDriveTypeW(path.anchor) == 4:
            raise ValueError("select a local document or supply an HTTPS URL")
    return path


def _selected_path(file):
    path = _local_path(file)
    # Reject redirections before following them, including junctions targeting a network share.
    for part in (*reversed(path.parents), path):
        info = part.lstat()
        redirected = stat.S_ISLNK(info.st_mode)
        if os.name == "nt":
            redirected |= info.st_reparse_tag in {stat.IO_REPARSE_TAG_SYMLINK, stat.IO_REPARSE_TAG_MOUNT_POINT}
        if redirected:
            raise ValueError("a path component redirects this document; select its actual local path")
    return path.resolve(strict=True)


def _line_at(stream, number):
    stream.seek(0)
    prefix = stream.read(4)
    encoding = "utf-8-sig"
    if prefix.startswith((codecs.BOM_UTF32_LE, codecs.BOM_UTF32_BE)):
        encoding = "utf-32"
    elif prefix.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        encoding = "utf-16"
    stream.seek(0)
    reader = io.TextIOWrapper(stream, encoding=encoding)
    try:
        for current in range(1, number + 1):
            # A single long source line (e.g. a generated file) must not consume all memory.
            chunk = reader.readline(65537)
            if not chunk:
                raise ValueError("line is beyond the end of the selected source")
            if current == number:
                if len(chunk) > 65536 or "\x00" in chunk:
                    raise ValueError("select a plain text line of at most 65536 characters")
                return chunk.rstrip("\r\n")
            while len(chunk) == 65537 and not chunk.endswith("\n"):
                chunk = reader.readline(65537)
    except UnicodeDecodeError as exc:
        raise ValueError("line selection requires UTF-8 or Unicode text with a BOM") from exc
    finally:
        reader.detach()


def _snapshot(path, line=None):
    if not stat.S_ISREG(path.stat().st_mode):
        raise ValueError("select a regular local document")
    with path.open("rb") as stream:
        before = os.fstat(stream.fileno())
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
        excerpt = _line_at(stream, line) if line is not None else ""
        after = path.stat()
        if (not os.path.samestat(before, after) or before.st_size != after.st_size
                or before.st_mtime_ns != after.st_mtime_ns or before.st_ctime_ns != after.st_ctime_ns):
            raise OSError("selected source changed while reading")
    return digest, excerpt


def _target(record):
    page, line, locator = record["page"], record["line"], record["locator"]
    if record["kind"] == "file":
        path = Path(record["source"])
        if page and path.suffix.lower() == ".pdf":
            return path.as_uri() + f"#page={page}"
        return str(path)
    parsed = https_source(record["source"])
    fragment = parsed.fragment
    if page:
        pairs = parse_qsl(fragment, keep_blank_values=True)
        pages = [v for k, v in pairs if k.lower() == "page"]
        if (pages and pages != [str(page)]) or (fragment and "=" not in fragment):
            raise ValueError("the URL fragment conflicts with the selected page")
        if not pages:
            fragment = (fragment + "&" if fragment else "") + f"page={page}"
    elif line:
        if fragment and fragment != f"L{line}":
            raise ValueError("the URL fragment conflicts with the selected line")
        fragment = f"L{line}"
    else:
        if not fragment and locator:
            fragment = quote(locator.removeprefix("#"), safe="")
        if record["excerpt"]:
            base, _, parameters = fragment.partition(":~:")
            encoded = quote(record["excerpt"], safe="").replace("-", "%2D")
            existing = [p.removeprefix("text=") for p in parameters.split("&") if p.startswith("text=")]
            if existing and [unquote(v) for v in existing] != [record["excerpt"]]:
                raise ValueError("the URL text fragment conflicts with the selected quote")
            if not existing:
                params = (parameters + "&" if parameters else "") + "text=" + encoded
                fragment = base + ":~:" + params
    return urlunsplit(parsed._replace(fragment=fragment))


@contextmanager
def _read_db(database):
    path = Path(database)
    if not path.exists():
        yield None
        return
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=10)) as db:
        db.row_factory = sqlite3.Row
        # During the very first concurrent save, the database file may already exist while its
        # initial transaction, including its schema and first complete passage, is still private.
        ready = db.execute("SELECT 1 FROM sqlite_schema WHERE type='table' AND name='passages'").fetchone()
        yield db if ready else None


def save(database, *, file=None, url=None, text=None, context="", locator="", page=None,
         line=None, scope="default", quote_text=None):
    """Save a note or selected passage. Retries of the same capture reuse its identity."""
    if (file is None) == (url is None):
        raise ValueError("select exactly one source with --file or --url")
    if not scope.strip():
        raise ValueError("scope must contain a name")
    if page is not None and line is not None:
        raise ValueError("select either a page or a line")
    if any(n is not None and (type(n) is not int or not 1 <= n < 2**63) for n in (page, line)):
        raise ValueError("page and line are positive integers")
    digest, excerpt = None, ""
    if quote_text is not None and (file is not None or line or page or not quote_text.strip()):
        raise ValueError("use a nonempty --quote with an HTTPS passage and without a page or line")
    if file is not None:
        path = _selected_path(file)
        source, kind = str(path), "file"
        digest, excerpt = _snapshot(path, line)
    else:
        https_source(url)
        source, kind = url, "https"
        excerpt = quote_text or ""
    text = excerpt if text is None else text
    if not text.strip():
        raise ValueError("supply --text, --quote or a nonempty local text line")
    record = dict(scope=scope, kind=kind, source=source, locator=locator, page=page,
                  line=line, text=text, context=context, excerpt=excerpt, sha256=digest)
    target = _target(record)
    identity = hashlib.sha256(json.dumps(record, ensure_ascii=False, sort_keys=True,
                                         separators=(",", ":")).encode()).hexdigest()
    record["id"] = identity
    database = Path(database)
    database.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(database, timeout=10)) as db, db:
        db.executescript("BEGIN IMMEDIATE;\n" + _SCHEMA)
        added = db.execute("""
            INSERT INTO passages(id,scope,kind,source,locator,page,line,text,context,excerpt,sha256)
            VALUES(:id,:scope,:kind,:source,:locator,:page,:line,:text,:context,:excerpt,:sha256)
            ON CONFLICT(id) DO NOTHING
        """, record)
        if added.rowcount:
            terms = (text, context + ("\n" + excerpt if excerpt != text else ""), locator, source)
            db.execute("INSERT INTO passage_fts(rowid,text,context,locator,source) VALUES(?,?,?,?,?)",
                       (added.lastrowid, *map(_fold, terms)))
    return {"id": identity, "scope": scope, "source": source, "target": target, "inserted": bool(added.rowcount)}


def find(database, query, *, scope="default", limit=10):
    """Search the index alone, returning the original spelling and location for every hit."""
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    match = sanitize_fts_query(_fold(query))
    if not match:
        return []
    with _read_db(database) as db:
        if db is None:
            return []
        rows = db.execute(_SELECT + """
            JOIN passage_fts ON passage_fts.rowid = p.rowid
            WHERE passage_fts MATCH ? AND p.scope = ?
            ORDER BY bm25(passage_fts, 5, 3, 2, 1), p.rowid DESC LIMIT ?
        """, (match, scope, limit))
        return [dict(row) for row in rows]


def show(database, identity, *, scope="default"):
    """Resolve one saved passage and check the bytes of only its selected local source."""
    row = None
    with _read_db(database) as db:
        if db is not None:
            row = db.execute(_SELECT + " WHERE p.id = ? AND p.scope = ?", (identity, scope)).fetchone()
    if row is None:
        raise LookupError("no saved passage with that ID in the selected scope")
    result = dict(row)
    result["target"] = _target(result)
    status = "unverified_https"
    if result["kind"] == "file":
        try:
            selected = _selected_path(result["source"])
            current, _ = _snapshot(selected)
            status = "verified" if current == result["sha256"] else "changed"
        except (FileNotFoundError, NotADirectoryError):
            status = "missing"
        except (OSError, ValueError, RuntimeError):
            status = "unavailable"
    result["continuity"] = status
    return result
