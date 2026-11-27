"""CHIMERA-IMMORTAL-JOB: Lightweight Durable Execution Engine (<3 MB RAM, SQLite WAL, idempotent step resume)."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class ImmortalJobEngine:
    """Durable workflow journal: survives crashes/reboots/quota limits and resumes at exact incomplete step."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA synchronous=NORMAL;")
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                job_id TEXT PRIMARY KEY,
                app TEXT NOT NULL,
                name TEXT NOT NULL,
                total_steps INTEGER NOT NULL,
                status TEXT NOT NULL,
                meta_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS job_steps (
                job_id TEXT NOT NULL,
                step_key TEXT NOT NULL,
                step_index INTEGER NOT NULL,
                status TEXT NOT NULL,
                result_json TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 1,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (job_id, step_key)
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS step_leases (
                job_id TEXT NOT NULL,
                step_key TEXT NOT NULL,
                step_index INTEGER NOT NULL,
                generation INTEGER NOT NULL,
                input_digest TEXT NOT NULL,
                target_node TEXT NOT NULL,
                leased_at TEXT NOT NULL,
                PRIMARY KEY (job_id, step_key)
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS step_receipts (
                job_id TEXT NOT NULL,
                step_key TEXT NOT NULL,
                generation INTEGER NOT NULL,
                node_id TEXT NOT NULL,
                input_digest TEXT NOT NULL,
                output_digest TEXT NOT NULL,
                output_cas_hash TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL,
                committed_at TEXT NOT NULL,
                PRIMARY KEY (job_id, step_key)
            )
            """
        )
        self._conn.commit()
        self._skipped_duplicates = 0
        self._stale_receipts_rejected = 0

    def create_job(
        self,
        job_id: str | None = None,
        app: str = "system",
        name: str = "workflow",
        total_steps: int = 1,
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        jid = (job_id or f"job-{uuid.uuid4().hex[:12]}").strip()
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        with self._lock:
            row = self._conn.execute(
                "SELECT job_id, app, name, total_steps, status, meta_json, created_at, updated_at FROM jobs WHERE job_id=?",
                (jid,),
            ).fetchone()
            if row is not None:
                return self._format_job_locked(row, resumed=True)
            self._conn.execute(
                "INSERT INTO jobs(job_id, app, name, total_steps, status, meta_json, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?)",
                (jid, str(app), str(name), max(1, int(total_steps)), "running", json.dumps(meta or {}, ensure_ascii=False), now, now),
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT job_id, app, name, total_steps, status, meta_json, created_at, updated_at FROM jobs WHERE job_id=?",
                (jid,),
            ).fetchone()
            return self._format_job_locked(row, resumed=False)

    def checkpoint_step(
        self,
        job_id: str,
        step_key: str,
        step_index: int = 0,
        status: str = "completed",
        result: Any = None,
    ) -> dict[str, Any]:
        jid = str(job_id).strip()
        skey = str(step_key).strip()
        if not jid or not skey:
            raise ValueError("job_id and step_key are required")
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        with self._lock:
            jrow = self._conn.execute("SELECT total_steps FROM jobs WHERE job_id=?", (jid,)).fetchone()
            if jrow is None:
                self._conn.execute(
                    "INSERT INTO jobs(job_id, app, name, total_steps, status, meta_json, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?)",
                    (jid, "auto", jid, max(1, int(step_index) + 1), "running", "{}", now, now),
                )
                total_steps = max(1, int(step_index) + 1)
            else:
                total_steps = int(jrow[0])

            existing = self._conn.execute(
                "SELECT status, result_json, attempts FROM job_steps WHERE job_id=? AND step_key=?",
                (jid, skey),
            ).fetchone()
            if existing is not None and existing[0] == "completed" and status == "completed":
                self._skipped_duplicates += 1
                return {
                    "ok": True,
                    "job_id": jid,
                    "step_key": skey,
                    "already_completed": True,
                    "cached_result": json.loads(existing[1]),
                    "attempts": int(existing[2]),
                }

            attempts = (int(existing[2]) + 1) if existing is not None else 1
            self._conn.execute(
                """
                INSERT OR REPLACE INTO job_steps(job_id, step_key, step_index, status, result_json, attempts, updated_at)
                VALUES(?,?,?,?,?,?,?)
                """,
                (jid, skey, int(step_index), str(status), json.dumps(result, ensure_ascii=False), attempts, now),
            )

            done_cnt = self._conn.execute(
                "SELECT COUNT(*) FROM job_steps WHERE job_id=? AND status='completed'",
                (jid,),
            ).fetchone()[0]
            new_job_status = "completed" if done_cnt >= total_steps else ("failed" if status == "failed" else "running")
            self._conn.execute(
                "UPDATE jobs SET status=?, updated_at=? WHERE job_id=?",
                (new_job_status, now, jid),
            )
            self._conn.commit()
            return {
                "ok": True,
                "job_id": jid,
                "step_key": skey,
                "already_completed": False,
                "status": status,
                "job_status": new_job_status,
                "completed_steps": int(done_cnt),
                "total_steps": total_steps,
                "attempts": attempts,
            }

    def _format_receipt_row(self, row: tuple[Any, ...]) -> dict[str, Any]:
        return {
            "job_id": str(row[0]),
            "step_key": str(row[1]),
            "generation": int(row[2]),
            "node_id": str(row[3]),
            "input_digest": str(row[4]),
            "output_digest": str(row[5]),
            "output_cas_hash": str(row[6]),
            "status": str(row[7]),
            "committed_at": str(row[8]),
        }

    def acquire_step_lease(
        self,
        job_id: str,
        step_key: str,
        step_index: int = 0,
        input_digest: str = "",
        target_node: str = "local",
    ) -> dict[str, Any]:
        """Atomically acquire or bump a generation-fenced execution lease for a job step."""
        jid = str(job_id).strip()
        skey = str(step_key).strip()
        if not jid or not skey:
            raise ValueError("job_id and step_key are required")
        now_local = datetime.now().astimezone().isoformat(timespec="seconds")
        now_utc = datetime.now(timezone.utc).isoformat()
        with self._lock:
            if not self._conn.in_transaction:
                self._conn.execute("BEGIN IMMEDIATE")
            try:
                jrow = self._conn.execute("SELECT total_steps FROM jobs WHERE job_id=?", (jid,)).fetchone()
                if jrow is None:
                    self._conn.execute(
                        "INSERT INTO jobs(job_id, app, name, total_steps, status, meta_json, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?)",
                        (jid, "auto", jid, max(1, int(step_index) + 1), "running", "{}", now_local, now_local),
                    )
                existing_step = self._conn.execute(
                    "SELECT status, step_index, result_json FROM job_steps WHERE job_id=? AND step_key=?",
                    (jid, skey),
                ).fetchone()
                lease_row = self._conn.execute(
                    "SELECT generation, input_digest, target_node FROM step_leases WHERE job_id=? AND step_key=?",
                    (jid, skey),
                ).fetchone()
                if existing_step is not None and existing_step[0] == "completed":
                    rrow = self._conn.execute(
                        "SELECT job_id, step_key, generation, node_id, input_digest, output_digest, output_cas_hash, status, committed_at "
                        "FROM step_receipts WHERE job_id=? AND step_key=?",
                        (jid, skey),
                    ).fetchone()
                    self._conn.commit()
                    return {
                        "ok": True,
                        "already_completed": True,
                        "job_id": jid,
                        "step_key": skey,
                        "step_index": int(existing_step[1]),
                        "generation": int(lease_row[0]) if lease_row is not None else 0,
                        "input_digest": str(lease_row[1]) if lease_row is not None else str(input_digest),
                        "target_node": str(lease_row[2]) if lease_row is not None else str(target_node),
                        "receipt": self._format_receipt_row(rrow) if rrow is not None else None,
                        "cached_result": json.loads(existing_step[2]),
                    }

                new_gen = (int(lease_row[0]) + 1) if lease_row is not None else 1
                self._conn.execute(
                    """
                    INSERT OR REPLACE INTO step_leases(job_id, step_key, step_index, generation, input_digest, target_node, leased_at)
                    VALUES(?,?,?,?,?,?,?)
                    """,
                    (jid, skey, int(step_index), new_gen, str(input_digest), str(target_node), now_utc),
                )
                self._conn.commit()
                return {
                    "ok": True,
                    "already_completed": False,
                    "job_id": jid,
                    "step_key": skey,
                    "step_index": int(step_index),
                    "generation": new_gen,
                    "input_digest": str(input_digest),
                    "target_node": str(target_node),
                    "leased_at": now_utc,
                }
            except Exception:
                self._conn.rollback()
                raise

    def commit_step_receipt(
        self,
        job_id: str,
        step_key: str,
        step_index: int,
        generation: int,
        node_id: str,
        input_digest: str,
        output_digest: str,
        result: Any,
        output_cas_hash: str = "",
    ) -> dict[str, Any]:
        """Single Commit Authority: verify lease generation + input_digest and atomically commit step + durable receipt."""
        jid = str(job_id).strip()
        skey = str(step_key).strip()
        if not jid or not skey:
            raise ValueError("job_id and step_key are required")
        gen = int(generation)
        in_dig = str(input_digest)
        out_dig = str(output_digest)
        cas_h = str(output_cas_hash or "")
        nid = str(node_id)
        now_local = datetime.now().astimezone().isoformat(timespec="seconds")
        now_utc = datetime.now(timezone.utc).isoformat()

        with self._lock:
            if not self._conn.in_transaction:
                self._conn.execute("BEGIN IMMEDIATE")
            try:
                lease_row = self._conn.execute(
                    "SELECT generation, input_digest FROM step_leases WHERE job_id=? AND step_key=?",
                    (jid, skey),
                ).fetchone()
                if lease_row is None:
                    self._conn.rollback()
                    self._stale_receipts_rejected += 1
                    return {
                        "ok": False,
                        "rejected": True,
                        "reason": "stale_generation",
                        "detail": "missing_lease",
                        "job_id": jid,
                        "step_key": skey,
                        "expected_generation": None,
                        "got_generation": gen,
                    }
                expected_gen = int(lease_row[0])
                expected_in_dig = str(lease_row[1])
                if expected_gen != gen:
                    self._conn.rollback()
                    self._stale_receipts_rejected += 1
                    return {
                        "ok": False,
                        "rejected": True,
                        "reason": "stale_generation",
                        "job_id": jid,
                        "step_key": skey,
                        "expected_generation": expected_gen,
                        "got_generation": gen,
                    }
                if expected_in_dig != in_dig:
                    self._conn.rollback()
                    self._stale_receipts_rejected += 1
                    return {
                        "ok": False,
                        "rejected": True,
                        "reason": "input_digest_mismatch",
                        "job_id": jid,
                        "step_key": skey,
                        "expected_generation": expected_gen,
                        "got_generation": gen,
                        "expected_input_digest": expected_in_dig,
                        "got_input_digest": in_dig,
                    }

                existing_step = self._conn.execute(
                    "SELECT status, result_json, attempts FROM job_steps WHERE job_id=? AND step_key=?",
                    (jid, skey),
                ).fetchone()
                existing_rrow = self._conn.execute(
                    "SELECT job_id, step_key, generation, node_id, input_digest, output_digest, output_cas_hash, status, committed_at "
                    "FROM step_receipts WHERE job_id=? AND step_key=?",
                    (jid, skey),
                ).fetchone()
                if existing_step is not None and existing_step[0] == "completed":
                    existing_receipt = self._format_receipt_row(existing_rrow) if existing_rrow is not None else None
                    if existing_receipt is not None and int(existing_receipt["generation"]) != gen:
                        self._conn.rollback()
                        self._stale_receipts_rejected += 1
                        return {
                            "ok": False,
                            "rejected": True,
                            "reason": "stale_generation",
                            "job_id": jid,
                            "step_key": skey,
                            "expected_generation": int(existing_receipt["generation"]),
                            "got_generation": gen,
                        }
                    self._skipped_duplicates += 1
                    self._conn.commit()
                    return {
                        "ok": True,
                        "job_id": jid,
                        "step_key": skey,
                        "already_completed": True,
                        "idempotent": True,
                        "receipt": existing_receipt,
                        "cached_result": json.loads(existing_step[1]),
                    }

                jrow = self._conn.execute("SELECT total_steps FROM jobs WHERE job_id=?", (jid,)).fetchone()
                if jrow is None:
                    total_steps = max(1, int(step_index) + 1)
                    self._conn.execute(
                        "INSERT INTO jobs(job_id, app, name, total_steps, status, meta_json, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?)",
                        (jid, "auto", jid, total_steps, "running", "{}", now_local, now_local),
                    )
                else:
                    total_steps = int(jrow[0])

                attempts = max(gen, (int(existing_step[2]) + 1) if existing_step is not None else 1)
                self._conn.execute(
                    """
                    INSERT OR REPLACE INTO job_steps(job_id, step_key, step_index, status, result_json, attempts, updated_at)
                    VALUES(?,?,?,?,?,?,?)
                    """,
                    (jid, skey, int(step_index), "completed", json.dumps(result, ensure_ascii=False), attempts, now_local),
                )
                self._conn.execute(
                    """
                    INSERT OR REPLACE INTO step_receipts(job_id, step_key, generation, node_id, input_digest, output_digest, output_cas_hash, status, committed_at)
                    VALUES(?,?,?,?,?,?,?,?,?)
                    """,
                    (jid, skey, gen, nid, in_dig, out_dig, cas_h, "committed", now_utc),
                )
                done_cnt = self._conn.execute(
                    "SELECT COUNT(*) FROM job_steps WHERE job_id=? AND status='completed'",
                    (jid,),
                ).fetchone()[0]
                new_job_status = "completed" if done_cnt >= total_steps else "running"
                self._conn.execute(
                    "UPDATE jobs SET status=?, updated_at=? WHERE job_id=?",
                    (new_job_status, now_local, jid),
                )
                self._conn.commit()
                receipt = {
                    "job_id": jid,
                    "step_key": skey,
                    "generation": gen,
                    "node_id": nid,
                    "input_digest": in_dig,
                    "output_digest": out_dig,
                    "output_cas_hash": cas_h,
                    "status": "committed",
                    "committed_at": now_utc,
                }
                return {
                    "ok": True,
                    "job_id": jid,
                    "step_key": skey,
                    "step_index": int(step_index),
                    "already_completed": False,
                    "idempotent": False,
                    "status": "completed",
                    "job_status": new_job_status,
                    "completed_steps": int(done_cnt),
                    "total_steps": total_steps,
                    "attempts": attempts,
                    "receipt": receipt,
                }
            except Exception:
                self._conn.rollback()
                raise

    def get_receipts(self, job_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        lim = max(1, int(limit))
        with self._lock:
            if job_id is not None and str(job_id).strip():
                rows = self._conn.execute(
                    "SELECT job_id, step_key, generation, node_id, input_digest, output_digest, output_cas_hash, status, committed_at "
                    "FROM step_receipts WHERE job_id=? ORDER BY committed_at DESC, step_key ASC LIMIT ?",
                    (str(job_id).strip(), lim),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT job_id, step_key, generation, node_id, input_digest, output_digest, output_cas_hash, status, committed_at "
                    "FROM step_receipts ORDER BY committed_at DESC, job_id ASC, step_key ASC LIMIT ?",
                    (lim,),
                ).fetchall()
            return [self._format_receipt_row(r) for r in rows]

    def resume_job(self, job_id: str) -> dict[str, Any] | None:
        jid = str(job_id).strip()
        with self._lock:
            row = self._conn.execute(
                "SELECT job_id, app, name, total_steps, status, meta_json, created_at, updated_at FROM jobs WHERE job_id=?",
                (jid,),
            ).fetchone()
            if row is None:
                return None
            return self._format_job_locked(row, resumed=True)

    def _format_job_locked(self, row: tuple[Any, ...], resumed: bool) -> dict[str, Any]:
        jid = row[0]
        steps_rows = self._conn.execute(
            "SELECT step_key, step_index, status, result_json, attempts, updated_at FROM job_steps WHERE job_id=? ORDER BY step_index ASC, step_key ASC",
            (jid,),
        ).fetchall()
        completed: dict[str, Any] = {}
        steps: list[dict[str, Any]] = []
        # The journal is ordered by index. A later worker may finish before an earlier one.
        next_step_index = 0
        for sk, sidx, sst, rjson, att, uts in steps_rows:
            parsed_r = json.loads(rjson)
            steps.append(
                {
                    "step_key": sk,
                    "step_index": int(sidx),
                    "status": sst,
                    "result": parsed_r,
                    "attempts": int(att),
                    "updated_at": uts,
                }
            )
            if sst == "completed":
                completed[sk] = parsed_r
                if int(sidx) == next_step_index:
                    next_step_index += 1
        return {
            "ok": True,
            "job_id": jid,
            "app": row[1],
            "name": row[2],
            "total_steps": int(row[3]),
            "status": row[4],
            "resumed": resumed,
            "next_step_index": next_step_index,
            "completed_count": len(completed),
            "completed_outputs": completed,
            "steps": steps,
            "meta": json.loads(row[5]),
            "created_at": row[6],
            "updated_at": row[7],
        }

    def list_jobs(self, app: str | None = None, limit: int = 30) -> list[dict[str, Any]]:
        with self._lock:
            if app:
                rows = self._conn.execute(
                    "SELECT job_id, app, name, total_steps, status, meta_json, created_at, updated_at FROM jobs WHERE app=? ORDER BY updated_at DESC LIMIT ?",
                    (app, max(1, int(limit))),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT job_id, app, name, total_steps, status, meta_json, created_at, updated_at FROM jobs ORDER BY updated_at DESC LIMIT ?",
                    (max(1, int(limit)),),
                ).fetchall()
            return [self._format_job_locked(r, resumed=False) for r in rows]

    def stats(self) -> dict[str, Any]:
        with self._lock:
            total = self._conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
            running = self._conn.execute("SELECT COUNT(*) FROM jobs WHERE status='running'").fetchone()[0]
            completed = self._conn.execute("SELECT COUNT(*) FROM jobs WHERE status='completed'").fetchone()[0]
            steps_done = self._conn.execute("SELECT COUNT(*) FROM job_steps WHERE status='completed'").fetchone()[0]
            durable_receipts = self._conn.execute("SELECT COUNT(*) FROM step_receipts").fetchone()[0]
            return {
                "total_jobs": int(total),
                "running_jobs": int(running),
                "completed_jobs": int(completed),
                "completed_steps": int(steps_done),
                "duplicate_steps_skipped": int(self._skipped_duplicates),
                "durable_receipts": int(durable_receipts),
                "stale_receipts_rejected": int(self._stale_receipts_rejected),
            }

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass
