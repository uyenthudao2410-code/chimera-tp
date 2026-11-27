"""Bounded sender outbox for frozen builds and checkpointed CAS jobs."""

from __future__ import annotations

from contextlib import closing
import json
from pathlib import Path
import sqlite3
import time

from .build_snapshot import canonical, sha


MAX_PENDING_BYTES = 128 * 1024 * 1024
MAX_PENDING_JOBS = 32


def outgoing(root=None):
    return Path(root or Path.home() / ".chimera" / "guarded-builds" / "outgoing")


def _open(root: Path):
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    db = sqlite3.connect(root / "outbox.sqlite", timeout=15)
    db.execute("CREATE TABLE IF NOT EXISTS pending("
               "id TEXT PRIMARY KEY, peer TEXT, specification BLOB, wire BLOB, added REAL, reason TEXT)")
    return db


def ticket(peer, request):
    return sha(canonical([peer, request]))


def _find_exile(db, journal, job_id):
    # Cast the original BLOB explicitly. Existing build specifications are also JSON.
    return db.execute(
        "SELECT id, json_extract(CAST(specification AS TEXT), '$.inputs_sha256') FROM pending "
        "WHERE json_extract(CAST(specification AS TEXT), '$.kind')='exile_handoff' "
        "AND json_extract(CAST(specification AS TEXT), '$.journal')=? "
        "AND json_extract(CAST(specification AS TEXT), '$.job_id')=?",
        (journal, job_id),
    ).fetchone()


def find_exile(root, journal, job_id):
    if not (root / "outbox.sqlite").is_file():
        return None
    with closing(_open(root)) as db:
        return _find_exile(db, journal, job_id)


def put(root, peer, request, wire, reason):
    key = ticket(peer, request)
    spec = canonical(request)
    with closing(_open(root)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        known = db.execute("SELECT 1 FROM pending WHERE id=?", (key,)).fetchone()
        if known:
            db.execute("UPDATE pending SET reason=? WHERE id=?", (reason, key))
        else:
            if request.get("kind") == "exile_handoff":
                existing = _find_exile(db, request["journal"], request["job_id"])
                if existing:
                    if existing[1] == request["inputs_sha256"]:
                        return {"stored": True, "id": existing[0]}
                    return {"stored": False, "reason": "queued_exile_inputs_changed"}
            count, used = db.execute("SELECT count(*),coalesce(sum(length(specification)+length(wire)),0) "
                                     "FROM pending").fetchone()
            if count >= MAX_PENDING_JOBS or used + len(spec) + len(wire) > MAX_PENDING_BYTES:
                return {"stored": False, "reason": "outbox_capacity"}
            db.execute("INSERT INTO pending VALUES (?,?,?,?,?,?)",
                       (key, peer, spec, wire, time.time(), reason))
    return {"stored": True, "id": key}


def list_pending(root):
    with closing(_open(root)) as db:
        rows = db.execute(
            "SELECT id,peer,added,reason,length(wire), "
            "json_extract(CAST(specification AS TEXT), '$.kind'), "
            "json_extract(CAST(specification AS TEXT), '$.job_id') "
            "FROM pending ORDER BY added"
        ).fetchall()
    result = []
    for key, peer, added, reason, size, kind, jid in rows:
        item = {"id": key, "peer": peer, "added_epoch": added, "reason": reason, "wire_bytes": size}
        if kind == "exile_handoff":
            item.update(kind=kind, job_id=jid)
        result.append(item)
    return result


def update_reason(root, key, reason):
    with closing(_open(root)) as db, db:
        return db.execute("UPDATE pending SET reason=? WHERE id=?", (reason, key)).rowcount == 1


def get(root, key):
    with closing(_open(root)) as db:
        row = db.execute("SELECT peer,specification,wire FROM pending WHERE id=?", (key,)).fetchone()
    if row is None:
        raise ValueError("queued_build_not_found")
    peer, spec, wire = row
    request = json.loads(spec)
    if ticket(peer, request) != key or len(wire) != request["wire_bytes"]:
        raise ValueError("queued_build_integrity_failure")
    return peer, request, wire


def refresh_worker(root, key, peer, request, current_digest):
    """Update code for the same protocol atomically while retaining the frozen source bytes."""
    refreshed = {**request, "worker_version": current_digest}
    new_key = ticket(peer, refreshed)
    with closing(_open(root)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        if db.execute("SELECT 1 FROM pending WHERE id=?", (new_key,)).fetchone():
            db.execute("DELETE FROM pending WHERE id=?", (key,))
        else:
            changed = db.execute("UPDATE pending SET id=?,specification=? WHERE id=?",
                                 (new_key, canonical(refreshed), key))
            if changed.rowcount != 1:
                raise ValueError("queued_build_moved_or_completed")
    return refreshed


def finish(root, key):
    if not (root / "outbox.sqlite").is_file():
        return
    with closing(_open(root)) as db, db:
        db.execute("DELETE FROM pending WHERE id=?", (key,))
