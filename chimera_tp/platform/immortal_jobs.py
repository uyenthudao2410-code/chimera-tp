"""CHIMERA-IMMORTAL-JOB: Lightweight Durable Execution Engine (<3 MB RAM, SQLite WAL, idempotent step resume)."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from datetime import datetime
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
        self._conn.commit()
        self._skipped_duplicates = 0

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
        max_done_idx = -1
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
                max_done_idx = max(max_done_idx, int(sidx))
        return {
            "ok": True,
            "job_id": jid,
            "app": row[1],
            "name": row[2],
            "total_steps": int(row[3]),
            "status": row[4],
            "resumed": resumed,
            "next_step_index": max_done_idx + 1,
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
            return {
                "total_jobs": int(total),
                "running_jobs": int(running),
                "completed_jobs": int(completed),
                "completed_steps": int(steps_done),
                "duplicate_steps_skipped": int(self._skipped_duplicates),
            }

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass
