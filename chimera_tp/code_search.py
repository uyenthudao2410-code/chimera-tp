"""CHIMERA v4.0 Breakthrough #4: 0-Download SQLite FTS5 + Merkle Instant Code & Log Search."""

from __future__ import annotations

import os
import re
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from .merkle_sync import DEFAULT_IGNORE_DIRS

SEARCH_IGNORE_DIRS: frozenset[str] = DEFAULT_IGNORE_DIRS | frozenset(
    {
        "archive",
        "cas",
        "workspaces",
        "makefun_work",
        "backups",
        "cache",
        "tmp",
        "vendor",
        "out",
        "coverage",
        "storybook-static",
        "public",
        "assets",
    }
)
_IGNORE_SUFFIXES = (".min.js", ".min.css", ".lock", "-lock.json", ".map")

TEXT_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".py",
        ".rs",
        ".c",
        ".h",
        ".cpp",
        ".hpp",
        ".js",
        ".ts",
        ".tsx",
        ".jsx",
        ".html",
        ".css",
        ".json",
        ".toml",
        ".yaml",
        ".yml",
        ".md",
        ".txt",
        ".sh",
        ".ps1",
        ".sql",
        ".log",
        ".cfg",
        ".ini",
    }
)

_TOKEN_RE = re.compile(r"[\w]+", re.UNICODE)


def sanitize_fts_query(raw_query: str) -> str:
    """Convert arbitrary user query text into safe FTS5 quoted AND tokens."""
    tokens = _TOKEN_RE.findall(str(raw_query or "").strip())
    if not tokens:
        return ""
    return " AND ".join(f'"{tok}"' for tok in tokens[:12])


def _read_indexable_text(path: Path, max_file_bytes: int) -> str | None:
    try:
        sz = int(path.stat().st_size)
        if sz == 0:
            return ""
        if path.suffix.lower() == ".log" and sz > max_file_bytes:
            tail_cap = min(max_file_bytes, 48 * 1024)
            with path.open("rb") as f:
                f.seek(max(0, sz - tail_cap))
                raw = f.read(tail_cap)
        elif sz > max_file_bytes:
            return None
        else:
            raw = path.read_bytes()
    except OSError:
        return None
    if b"\x00" in raw[:4096]:
        return None
    return raw.decode("utf-8", errors="replace")


class CodeSearchIndex:
    """Incremental SQLite FTS5 + stat-cache BM25 code and log search index."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        # Only this connection is affected. Other SQLite users in the daemon
        # keep their own page budgets and the database header is unchanged.
        if os.environ.get("CHIMERA_COMPACT_INDEX_CACHE") == "1":
            self._conn.execute("PRAGMA cache_size=-384")
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.executescript(
                """
                PRAGMA journal_mode=WAL;
                PRAGMA synchronous=NORMAL;
                CREATE TABLE IF NOT EXISTS files (
                    rel_path TEXT PRIMARY KEY,
                    root_path TEXT NOT NULL,
                    repo TEXT NOT NULL,
                    size INTEGER NOT NULL,
                    mtime_ns INTEGER NOT NULL,
                    indexed_at TEXT NOT NULL
                );
                CREATE VIRTUAL TABLE IF NOT EXISTS code_fts USING fts5(
                    rel_path,
                    repo,
                    content,
                    tokenize='unicode61'
                );
                CREATE TABLE IF NOT EXISTS meta (
                    k TEXT PRIMARY KEY,
                    v TEXT NOT NULL
                );
                """
            )
            self._conn.commit()

    def incremental_index(
        self,
        roots: list[Path],
        max_files: int = 8000,
        max_file_bytes: int = 48 * 1024,
        max_files_per_repo: int = 250,
    ) -> dict[str, Any]:
        t0 = time.perf_counter()
        now_local = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
        disk_entries: dict[str, tuple[Path, str, str, int, int]] = {}
        repo_counts: dict[str, int] = {}
        seen_count = 0

        for r_raw in roots:
            root = Path(r_raw).resolve()
            if not root.exists():
                continue
            for dirpath, dirnames, filenames in os.walk(root):
                directory = Path(dirpath)
                relative_dir = directory.relative_to(root)
                repo = relative_dir.parts[0] if relative_dir.parts else root.name
                prefix = relative_dir.as_posix() + "/" if relative_dir.parts else ""
                dirnames[:] = sorted(
                    d for d in dirnames if d not in SEARCH_IGNORE_DIRS and not d.startswith(".")
                )
                for fn in sorted(filenames):
                    if repo_counts.get(repo, 0) >= max_files_per_repo:
                        # Descendants share the top-level repo. The root's children do not.
                        if relative_dir.parts:
                            dirnames.clear()
                        break
                    fp = directory / fn
                    if fn.endswith(_IGNORE_SUFFIXES) or fp.suffix.lower() not in TEXT_EXTENSIONS:
                        continue
                    try:
                        st = fp.stat()
                    except OSError:
                        continue
                    rel = prefix + fn
                    disk_key = f"{root.name}/{rel}" if len(roots) > 1 else rel
                    disk_entries[disk_key] = (root, rel, repo, st.st_size, st.st_mtime_ns)
                    repo_counts[repo] = repo_counts.get(repo, 0) + 1
                    seen_count += 1
                    if seen_count >= max_files:
                        break
                if seen_count >= max_files:
                    break
            if seen_count >= max_files:
                break

        updated = 0
        skipped_unchanged = 0
        skipped_binary_or_large = 0
        removed = 0

        with self._lock:
            cur = self._conn.cursor()
            with self._conn:
                # Keep FTS rowids stable even when another connection writes this index.
                cur.execute("BEGIN IMMEDIATE")
                old_rows: dict[str, list[int]] = {}
                for key, size, mtime_ns in cur.execute("SELECT rel_path, size, mtime_ns FROM files"):
                    entry = disk_entries.get(key)
                    if entry is not None and entry[3] == size and entry[4] == mtime_ns:
                        del disk_entries[key]
                        skipped_unchanged += 1
                    else:
                        old_rows[key] = []

                # An existing database may have different metadata/FTS rowids or duplicate
                # documents. Read the virtual table once for the entire batch of paths.
                if old_rows:
                    for rowid, key in cur.execute("SELECT rowid, rel_path FROM code_fts"):
                        rowids = old_rows.get(key)
                        if rowids is not None:
                            rowids.append(rowid)
                delete_document = "DELETE FROM code_fts WHERE rowid = ?"
                for key, rowids in old_rows.items():
                    if key not in disk_entries:
                        cur.executemany(delete_document, ((rowid,) for rowid in rowids))
                        cur.execute("DELETE FROM files WHERE rel_path = ?", (key,))
                        removed += 1

                for key, (root, rel, repo, size, mtime_ns) in disk_entries.items():
                    text = _read_indexable_text(root / rel, max_file_bytes=max_file_bytes)
                    if text is None:
                        skipped_binary_or_large += 1
                        continue
                    cur.executemany(delete_document, ((rowid,) for rowid in old_rows.get(key, ())))
                    cur.execute(
                        """
                        INSERT INTO files (rel_path, root_path, repo, size, mtime_ns, indexed_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                        ON CONFLICT(rel_path) DO UPDATE SET
                            root_path = excluded.root_path,
                            repo = excluded.repo,
                            size = excluded.size,
                            mtime_ns = excluded.mtime_ns,
                            indexed_at = excluded.indexed_at
                        """,
                        (key, str(root), repo, size, mtime_ns, now_local),
                    )
                    cur.execute(
                        "INSERT INTO code_fts (rel_path, repo, content) VALUES (?, ?, ?)",
                        (key, repo, text),
                    )
                    updated += 1

                cur.execute(
                    "INSERT INTO meta (k, v) VALUES ('last_indexed_at', ?) "
                    "ON CONFLICT(k) DO UPDATE SET v = excluded.v",
                    (now_local,),
                )
            if removed >= 100:
                self._conn.execute("VACUUM")
                self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            total_indexed = int(cur.execute("SELECT COUNT(*) FROM files").fetchone()[0])

        db_size_kb = round(self.db_path.stat().st_size / 1024.0, 2) if self.db_path.exists() else 0.0
        return {
            "ok": True,
            "total_files": total_indexed,
            "updated": updated,
            "skipped_unchanged": skipped_unchanged,
            "skipped_binary_or_large": skipped_binary_or_large,
            "removed": removed,
            "db_size_kb": db_size_kb,
            "last_indexed_at": now_local,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }

    def search(self, query: str, limit: int = 10, repo: str = "") -> dict[str, Any]:
        t0 = time.perf_counter()
        limit = max(1, min(50, int(limit)))
        fts_q = sanitize_fts_query(query)
        repo_clean = str(repo or "").strip()

        with self._lock:
            indexed_files = int(self._conn.execute("SELECT COUNT(*) FROM files").fetchone()[0])
            if not fts_q:
                return {
                    "query": query,
                    "fts_query": "",
                    "repo_filter": repo_clean,
                    "hits": [],
                    "total_hits": 0,
                    "indexed_files": indexed_files,
                    "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
                }

            sql = """
                SELECT rel_path, repo,
                       bm25(code_fts, 4.0, 2.0, 1.0) AS score,
                       snippet(code_fts, 2, '[[', ']]', ' ... ', 20) AS snippet
                FROM code_fts
                WHERE code_fts MATCH ?
            """
            params: list[Any] = [fts_q]
            if repo_clean:
                sql += " AND repo = ?"
                params.append(repo_clean)
            sql += " ORDER BY score ASC LIMIT ?"
            params.append(limit)
            rows = self._conn.execute(sql, tuple(params)).fetchall()

        hits = [
            {
                "repo": str(r["repo"]),
                "rel_path": str(r["rel_path"]),
                "score": round(-float(r["score"]), 3),
                "snippet": str(r["snippet"]).replace("\r", "").replace("\n", " "),
            }
            for r in rows
        ]
        return {
            "query": query,
            "fts_query": fts_q,
            "repo_filter": repo_clean,
            "hits": hits,
            "total_hits": len(hits),
            "indexed_files": indexed_files,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }

    def stats(self) -> dict[str, Any]:
        with self._lock:
            total = int(self._conn.execute("SELECT COUNT(*) FROM files").fetchone()[0])
            repos_count = int(self._conn.execute("SELECT COUNT(DISTINCT repo) FROM files").fetchone()[0])
            repo_rows = self._conn.execute(
                "SELECT repo, COUNT(*) AS cnt FROM files GROUP BY repo ORDER BY cnt DESC, repo ASC LIMIT 30"
            ).fetchall()
            last_row = self._conn.execute(
                "SELECT v FROM meta WHERE k = 'last_indexed_at'"
            ).fetchone()
        db_size_kb = round(self.db_path.stat().st_size / 1024.0, 2) if self.db_path.exists() else 0.0
        return {
            "indexed_files": total,
            "repos_count": repos_count,
            "repos": [{"repo": str(r["repo"]), "files": int(r["cnt"])} for r in repo_rows],
            "db_size_kb": db_size_kb,
            "last_indexed_at": str(last_row["v"]) if last_row is not None else "",
        }

    def close(self) -> None:
        with self._lock:
            self._conn.close()
