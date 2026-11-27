"""Cross-process single-flight and bounded result storage for declared repeatable work."""

from __future__ import annotations

import json
from pathlib import Path
import re
import sqlite3
import time
import zlib
from contextlib import closing

from .agent_workspace import LeaseBusy, _lock


RESULT_TTL = 3600
MAX_CACHE_BYTES = 32 * 1024 * 1024


def _load(database, key):
    with closing(sqlite3.connect(database, timeout=15)) as db:
        db.execute("CREATE TABLE IF NOT EXISTS result (key TEXT PRIMARY KEY, finished_ns INTEGER,"
                   " successful INTEGER, payload BLOB)")
        return db.execute("SELECT finished_ns, successful, payload FROM result WHERE key=?", (key,)).fetchone()


def _publish(database, key, result):
    data = zlib.compress(json.dumps(result, ensure_ascii=True).encode(), 1)
    if len(data) > MAX_CACHE_BYTES:
        raise ValueError("result_exceeds_cache_budget")
    finished = time.time_ns()
    with closing(sqlite3.connect(database, timeout=15)) as db, db:
        db.execute("INSERT OR REPLACE INTO result VALUES (?,?,?,?)",
                   (key, finished, int(bool(result.get("ok"))), data))
        db.execute("DELETE FROM result WHERE finished_ns < ?", (finished - RESULT_TTL * 10**9,))
        # Retain the newest receipts within both row and byte budgets.
        used = 0
        for n, (oldkey, size) in enumerate(db.execute(
                "SELECT key,length(payload) FROM result ORDER BY finished_ns DESC").fetchall()):
            used += size
            if used > MAX_CACHE_BYTES or n >= 256:
                db.execute("DELETE FROM result WHERE key=?", (oldkey,))


def execute_once(root: Path, key: str, operation, *, persist: bool, wait_s: float):
    """A caller that overlapped even a failed attempt sees that same receipt.

    After an unsuccessful attempt a new caller may retry. OS locks die with their
    owner. Callers must only use this facility for explicitly repeatable jobs.
    """
    if not re.fullmatch(r"[0-9a-f]{64}", key):
        raise ValueError("invalid_action_key")
    root.mkdir(mode=0o700, exist_ok=True, parents=True)
    database = root / "results.sqlite"
    lockfile = root / (key[:2] + ".lock")
    arrival = time.time_ns()
    deadline = time.monotonic() + wait_s
    while True:
        try:
            with _lock(lockfile):
                row = _load(database, key)
                if row:
                    finished, success, encoded = row
                    overlaps = finished >= arrival
                    fresh = 0 <= time.time_ns() - finished <= RESULT_TTL * 10**9
                    if overlaps or (persist and success and fresh):
                        return json.loads(zlib.decompress(encoded)), "joined" if overlaps else "cached"
                result = operation()
                _publish(database, key, result)
                return result, "executed"
        except LeaseBusy:
            if time.monotonic() >= deadline:
                return {"ok": False, "state": "deferred", "error": "active_build_wait_timeout",
                        "retryable": True}, "waiting"
            time.sleep(0.05)
