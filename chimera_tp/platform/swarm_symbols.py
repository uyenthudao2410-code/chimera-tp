"""Share Python definition locations for explicit Git worktree snapshots."""

from __future__ import annotations

import argparse
import ast
from contextlib import closing
import io
import json
import os
from pathlib import Path
import sqlite3
import stat
import subprocess
import sys
import tokenize

from .build_snapshot import MAX_FILES, MAX_INPUT_BYTES, _git, _git_root, _stamp, canonical, portable_path, sha


FORMAT = f"py{sys.version_info.major}.{sys.version_info.minor}-definitions-v1"
MAX_FILE_BYTES = 4 * 1024 * 1024
HISTORY = 8
SCHEMA = """
CREATE TABLE IF NOT EXISTS parses(digest TEXT PRIMARY KEY, error TEXT);
CREATE TABLE IF NOT EXISTS defs(
    digest TEXT NOT NULL REFERENCES parses ON DELETE CASCADE,
    name TEXT NOT NULL, qual TEXT NOT NULL, kind TEXT NOT NULL, line INTEGER NOT NULL, last INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS by_name ON defs(name, digest);
CREATE INDEX IF NOT EXISTS by_qual ON defs(qual, digest);
CREATE INDEX IF NOT EXISTS by_digest ON defs(digest);
CREATE TABLE IF NOT EXISTS versions(id TEXT PRIMARY KEY, head TEXT);
CREATE TABLE IF NOT EXISTS members(
    version TEXT NOT NULL REFERENCES versions ON DELETE CASCADE, path TEXT NOT NULL, digest TEXT NOT NULL,
    PRIMARY KEY(version, path)
);
CREATE INDEX IF NOT EXISTS members_by_digest ON members(version, digest);
"""


def _scope(repo: Path, store: Path):
    root = _git_root(repo.resolve(strict=True))
    if root is None:
        raise ValueError("git_worktree_required")
    info = _git(root, "rev-parse", "--absolute-git-dir")
    info.check_returncode()
    git_dir = Path(os.fsdecode(info.stdout.rstrip(b"\r\n"))).resolve(strict=True)
    scope = sha(canonical([os.path.normcase(str(root)), os.path.normcase(str(git_dir))]))
    return root, scope, store.expanduser().resolve() / scope / (FORMAT + ".sqlite3")


def _head(root):
    head = _git(root, "rev-parse", "--verify", "-q", "HEAD")
    if head.returncode == 1:  # No commit exists in a newly initialized repository.
        return None
    head.check_returncode()
    return head.stdout.decode("ascii").strip()


def _candidates(root, paths=None):
    if paths is not None and not paths:
        return set()
    specs = [":(literal)" + p for p in paths] if paths is not None else [":(icase)*.py", ":(icase)*.pyi"]
    entries = set()
    tracked = _git(root, "ls-files", "--stage", "-z", "--", *specs)
    tracked.check_returncode()
    for record in tracked.stdout.split(b"\0"):
        if record:
            metadata, raw = record.split(b"\t", 1)
            mode, _, stage = metadata.split()
            name = portable_path(os.fsdecode(raw))
            if stage != b"0":
                raise ValueError(f"unmerged_python:{name}")
            if mode in {b"100644", b"100755"}:
                entries.add(name)
    others = _git(root, "ls-files", "--others", "--exclude-standard", "-z", "--", *specs)
    others.check_returncode()
    entries.update(portable_path(os.fsdecode(raw)) for raw in others.stdout.split(b"\0") if raw)
    if len(entries) > MAX_FILES:
        raise ValueError("python_file_count_limit")
    return entries


def _safe_stat(root, name):
    path = root / name
    try:
        meta = path.lstat()
        if (not stat.S_ISREG(meta.st_mode) or getattr(meta, "st_file_attributes", 0) & 0x400
                or path.resolve(strict=True) != path):
            return None
        for parent in path.parents:
            if parent == root:
                break
            info = parent.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                return None
        return meta
    except (FileNotFoundError, NotADirectoryError):
        return None


def _inventory(root):
    manifest = {}
    total = 0
    for name in sorted(_candidates(root)):
        meta = _safe_stat(root, name)
        if meta:
            total += meta.st_size
            if meta.st_size > MAX_FILE_BYTES or total > MAX_INPUT_BYTES:
                raise ValueError(f"python_source_byte_limit:{name}")
            manifest[name] = _stamp(meta)
    return manifest


def _read(root, name, stamp):
    path = root / name
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
                 | getattr(os, "O_NONBLOCK", 0))
    with os.fdopen(fd, "rb") as source:
        if _stamp(os.fstat(source.fileno())) != stamp:
            raise ValueError(f"source_changed:{name}")
        data = source.read(stamp[2] + 1)
        if len(data) != stamp[2] or _stamp(os.fstat(source.fileno())) != stamp:
            raise ValueError(f"source_changed:{name}")
    return data


class Definitions(ast.NodeVisitor):
    def __init__(self):
        self.parents = []
        self.rows = []

    def _definition(self, node, kind):
        self.parents.append(node.name)
        self.rows.append((node.name, ".".join(self.parents), kind, node.lineno, node.end_lineno))
        for child in node.body:
            self.visit(child)
        self.parents.pop()

    def visit_ClassDef(self, node):
        self._definition(node, "class")

    def visit_FunctionDef(self, node):
        self._definition(node, "def")

    def visit_AsyncFunctionDef(self, node):
        self._definition(node, "async def")


def _parse(db, digest, data):
    visitor = Definitions()
    try:
        visitor.visit(ast.parse(data))
    except (SyntaxError, ValueError, RecursionError) as exc:
        error = f"{type(exc).__name__} at line {getattr(exc, 'lineno', None)}"
        db.execute("INSERT INTO parses VALUES (?, ?)", (digest, error))
    else:
        db.execute("INSERT INTO parses VALUES (?, NULL)", (digest,))
        db.executemany("INSERT INTO defs VALUES (?, ?, ?, ?, ?, ?)", ((digest, *row) for row in visitor.rows))


def index(repo, store):
    root, scope, db_path = _scope(repo, store)
    db_path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    with closing(sqlite3.connect(db_path, timeout=60)) as db, db:
        db.execute("PRAGMA foreign_keys=ON")
        db.executescript(SCHEMA)
        db.execute("BEGIN IMMEDIATE")  # One writer may parse missing inputs, including across processes.
        head = _head(root)
        manifest = _inventory(root)
        known = {d for d, in db.execute("SELECT digest FROM parses")}
        parsed, members = 0, []
        for path, stamp in manifest.items():
            data = _read(root, path, stamp)
            digest = sha(data)
            members.append((path, digest))
            if digest not in known:
                _parse(db, digest, data)
                known.add(digest)
                parsed += 1
        if head != _head(root) or manifest != _inventory(root):
            raise ValueError("worktree_changed_during_index")
        snapshot = sha(canonical([FORMAT, scope, head, members]))
        if db.execute("INSERT OR IGNORE INTO versions VALUES (?, ?)", (snapshot, head)).rowcount:
            db.executemany("INSERT INTO members VALUES (?, ?, ?)", ((snapshot, *m) for m in members))
            db.execute("DELETE FROM versions WHERE rowid NOT IN (SELECT rowid FROM versions ORDER BY rowid DESC LIMIT ?)",
                       (HISTORY,))
            db.execute("DELETE FROM parses WHERE digest NOT IN (SELECT digest FROM members)")
        errors = db.execute("""SELECT path, error FROM members JOIN parses USING(digest)
                               WHERE version=? AND error IS NOT NULL ORDER BY path""", (snapshot,)).fetchall()
    return {
        "ok": True, "worktree": str(root), "scope": scope, "head": head, "snapshot": snapshot,
        "python_files": len(members), "parsed_files": parsed, "source_bytes_read": sum(s[2] for s in manifest.values()),
        "syntax_error_files": len(errors), "syntax_errors_sample": [dict(path=p, error=e) for p, e in errors[:12]],
    }


def find(repo, store, snapshot, symbol, *, path=None, limit=6, context_bytes=1200):
    """Search a named snapshot and verify only the source files used as evidence."""
    if len(snapshot) != 64 or any(c not in "0123456789abcdef" for c in snapshot):
        raise ValueError("invalid_snapshot_hash")
    if len(symbol) > 512 or not all(piece.isidentifier() for piece in symbol.split(".")):
        raise ValueError("expected_python_identifier_or_qualified_name")
    if not 1 <= limit <= 20 or not 0 <= context_bytes <= 8192:
        raise ValueError("limit_must_be_1_to_20_and_context_bytes_0_to_8192")
    root, scope, db_path = _scope(repo, store)
    if not db_path.is_file():
        raise ValueError("snapshot_unavailable_in_this_worktree")
    column = "qual" if "." in symbol else "name"
    sql = f"""SELECT m.path, m.digest, d.qual, d.kind, d.line, d.last
              FROM defs d JOIN members m USING(digest) WHERE m.version=? AND d.{column}=?"""
    params = [snapshot, symbol]
    if path is not None:
        sql += " AND m.path=?"
        params.append(portable_path(path))
    with closing(sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True, timeout=60)) as db:
        db.execute("BEGIN")
        version = db.execute("SELECT head FROM versions WHERE id=?", (snapshot,)).fetchone()
        if version is None:
            raise ValueError("snapshot_unavailable_in_this_worktree")
        rows = db.execute(sql + " ORDER BY m.path, d.line LIMIT ?", (*params, limit + 1)).fetchall()
        errors = db.execute("""SELECT COUNT(*) FROM members JOIN parses USING(digest)
                               WHERE version=? AND error IS NOT NULL""", (snapshot,)).fetchone()[0]
    matches = []
    remaining, bytes_read = context_bytes, 0
    stamps = {}
    selected_paths = {r[0] for r in rows[:limit]}
    if _candidates(root, selected_paths) != selected_paths:
        raise ValueError("stale_source_membership_refresh_index")
    last_path, text_lines = None, []
    for name, digest, qual, kind, line, last in rows[:limit]:
        if name != last_path:
            meta = _safe_stat(root, name)
            if not meta or meta.st_size > MAX_FILE_BYTES:
                raise ValueError(f"stale_source_refresh_index:{name}")
            stamps[name] = _stamp(meta)
            data = _read(root, name, stamps[name])
            if sha(data) != digest:
                raise ValueError(f"stale_source_refresh_index:{name}")
            encoding, _ = tokenize.detect_encoding(io.BytesIO(data).readline)
            # TextIO recognizes Python's CR/LF/CRLF line endings. str.splitlines also
            # splits form-feed inside valid Python and would shift AST line numbers.
            text_lines = io.StringIO(data.decode(encoding), newline="").readlines()
            bytes_read += len(data)
            last_path = name
        excerpt, used = [], 0
        clipped = False
        for number in range(line - 1, last):
            raw = text_lines[number].encode("utf-8")
            if len(raw) > remaining - used:
                part = raw[:remaining - used].decode("utf-8", errors="ignore")
                excerpt.append(part)
                used += len(part.encode("utf-8"))
                clipped = True
                break
            excerpt.append(text_lines[number])
            used += len(raw)
        remaining -= used
        matches.append({"file": name, "line": line, "end_line": last, "location": f"{name}:{line}",
                        "qualified_name": qual, "kind": kind, "sha256": digest,
                        "context": "".join(excerpt), "context_truncated": clipped})
    if _candidates(root, selected_paths) != selected_paths:
        raise ValueError("stale_source_membership_refresh_index")
    for name, stamp in stamps.items():
        meta = _safe_stat(root, name)
        if not meta or _stamp(meta) != stamp:
            raise ValueError(f"source_changed:{name}")
    return {
        "ok": True, "worktree": str(root), "scope": scope, "head": version[0], "snapshot": snapshot,
        "symbol": symbol, "matches": matches, "more_matches": len(rows) > limit, "syntax_error_files": errors,
        "verified_files": len(stamps), "source_bytes_read": bytes_read, "parsed_files": 0,
        "context_utf8_bytes": context_bytes - remaining, "verification": "selected snapshot members against disk",
    }


def configure(parser: argparse.ArgumentParser):
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="Directory in the Git worktree")
    parser.add_argument("--store", type=Path, default=Path.home() / ".chimera" / "swarm-symbols",
                        help="Private cache directory shared by agents under this account")
    actions = parser.add_subparsers(dest="symbols_action", required=True)
    actions.add_parser("index", help="Refresh the Python snapshot, including saved uncommitted sources")
    lookup = actions.add_parser("find", help="Find a definition and verify its source bytes in this worktree")
    lookup.add_argument("symbol", help="Exact Python name or qualified definition such as Type.method")
    lookup.add_argument("--snapshot", required=True, help="Python snapshot SHA-256 returned by index")
    lookup.add_argument("--path", help="Exact repository-relative POSIX path")
    lookup.add_argument("--limit", type=int, default=6, help="Return at most 1–20 definitions")
    lookup.add_argument("--context-bytes", type=int, default=1200, help="Total UTF-8 excerpt budget, 0–8192 bytes")


def cli(args):
    try:
        if args.symbols_action == "index":
            result = index(args.repo, args.store)
        else:
            result = find(args.repo, args.store, args.snapshot, args.symbol, path=args.path,
                          context_bytes=args.context_bytes, limit=args.limit)
    except (ValueError, OSError, sqlite3.Error, subprocess.SubprocessError) as exc:
        result = {"ok": False, "error": str(exc)}
    print(json.dumps(result, ensure_ascii=True))
    return 0 if result.get("ok") else 1
