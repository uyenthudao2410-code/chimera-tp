"""Explicit per-user result reuse scoped to an exact inference context."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from contextlib import closing
from pathlib import Path


def _context(context):
    required = ("workspace", "principal", "provider", "model", "revision", "parameters")
    if any(not isinstance(context.get(k), str) or not context[k].strip() for k in required[:-1]):
        raise ValueError("provide workspace, principal, provider, model and immutable input revision")
    if not isinstance(context.get("parameters"), dict):
        raise ValueError("provide the complete parameters object")
    raw = json.dumps(context, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode()).hexdigest()


class ResultReuse:
    def __init__(self, database: Path):
        database.parent.mkdir(parents=True, exist_ok=True)
        self.database = database
        with closing(self._open()) as db, db:
            db.execute("""CREATE TABLE IF NOT EXISTS entries
                       (scope TEXT, question TEXT, result BLOB NOT NULL, expiry REAL NOT NULL,
                        PRIMARY KEY(scope,question))""")
            db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS hints USING fts5(scope UNINDEXED, question)")

    def _open(self):
        return sqlite3.connect(self.database, timeout=5)

    def put(self, context, question, result, ttl=3600):
        if not question or not 0 < ttl <= 86400 or len(result) > 8 * 1024 * 1024:
            raise ValueError("expected a question, 1..86400 seconds and a result up to 8 MiB")
        scope = _context(context)
        expiry = time.time() + ttl
        with closing(self._open()) as db, db:
            db.execute("INSERT OR REPLACE INTO entries VALUES(?,?,?,?)", (scope, question, result, expiry))
            db.execute("DELETE FROM hints WHERE scope=? AND question=?", (scope, question))
            db.execute("INSERT INTO hints VALUES(?,?)", (scope, question))
        return {"bytes": len(result), "expires": expiry}

    def get(self, context, question):
        with closing(self._open()) as db:
            row = db.execute("SELECT result FROM entries WHERE scope=? AND question=? AND expiry>?",
                             (_context(context), question, time.time())).fetchone()
        return None if row is None else row[0]

    def suggest(self, context, phrase):
        scope = _context(context)
        with closing(self._open()) as db:
            rows = db.execute("""SELECT h.question FROM hints AS h JOIN entries AS e
                              ON e.scope=h.scope AND e.question=h.question
                              WHERE hints MATCH ? AND h.scope=? AND e.expiry>? ORDER BY rank LIMIT 8""",
                              ('"' + phrase.replace('"', '""') + '"', scope, time.time()))
            return [q for q, in rows]
