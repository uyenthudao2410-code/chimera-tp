"""Local receiver fixture for the guarded CAS fault matrix. The job journal and CAS workers are real."""

from __future__ import annotations

from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import sqlite3
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch
from uuid import uuid4

from chimera_tp.platform import build_snapshot, build_worker, guarded_build
from chimera_tp.platform.cosmos_entity import ZeroEnvCasStore
from chimera_tp.platform.exile_handoff import CheckpointedExileCoordinator, _GuardedCasTransport
from chimera_tp.platform.immortal_jobs import ImmortalJobEngine
from chimera_tp.platform.phantom_silicon import AgentExileEngine
from scripts.exile_fault_cases import FAULT_POINTS, reference_output, trial_inputs


PEER = "cas-recovery-fixture.invalid"


class ClientReplyLost(ConnectionError):
    """One missing client acknowledgement after a successful journal transaction."""


class LocalReceiver:
    """Replace the SSH launch and Linux admission; execute the staged cas_work.py in a fresh process."""

    def __init__(self, root: Path, fault: str):
        self.root = root
        self.cas = root / "receiver-cas"
        self.fault = fault
        self.fired = False
        self.events: list[dict] = []
        self.executed_generations: list[int] = []
        self.delayed: dict | None = None

    def _drop(self, point: str) -> bool:
        if point != self.fault or self.fired:
            return False
        self.fired = True
        return True

    def drop_client_reply(self, commit: dict):
        if self._drop("post_commit_pre_client_reply"):
            if not commit.get("ok"):
                raise AssertionError("The fixture must drop a successful commit acknowledgement")
            raise ClientReplyLost()

    def submit(self, command: str, *, cwd: Path, peer: str, reuse: bool, sync: bool,
               artifacts: list[str], timeout_s: float, admission_policy=None) -> dict:
        if peer != PEER or reuse or not sync or command != "python3 -I -B -S cas_work.py":
            raise AssertionError("Unexpected launch contract in the guarded local fixture")
        payload = json.loads((cwd / "request.json").read_bytes())
        if Path(payload["cas_dir"]) != self.cas:
            raise AssertionError("The receiver must store every object in the temporary fixture")
        action = payload["action"]
        snapshot = build_snapshot.capture(cwd)
        event = {"action": action, "blocks": payload.get("blocks", {}), "received": False,
                 "snapshot_bytes": len(snapshot["wire"])}
        self.events.append(event)
        interrupted = {"ok": False, "state": "indeterminate", "retryable": False,
                       "error": f"fixture_receipt_lost:{self.fault}"}
        if (action == "push" and self._drop("pre_receive")) or (
                action == "execute" and self._drop("post_receive_pre_compute")):
            return interrupted

        with tempfile.TemporaryDirectory(prefix="worker-", dir=self.root) as stage:
            where = build_snapshot.materialize(snapshot["wire"], snapshot["digest"], Path(stage) / "tree")
            launched = subprocess.run(
                [sys.executable, "-I", "-B", "-S", "cas_work.py"], cwd=where, capture_output=True,
                timeout=timeout_s, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if launched.returncode:
                raise AssertionError(launched.stderr.decode("utf-8", "replace"))
            event["received"] = True
            returned = build_worker._artifacts(where, artifacts)
            if action == "execute":
                self.executed_generations.append(payload["generation"])
                if self._drop("post_compute_pre_ack"):
                    self.delayed = json.loads((where / "response.json").read_bytes())
                    return interrupted
        return {
            "ok": True, "delivery": "executed", "target": platform.node(),
            "attempt_id": uuid4().hex, "snapshot": snapshot["digest"],
            "admission": {"limits_verified": True}, "runtime_guard": "local fixture",
            "artifacts": returned, "ssh_request_bytes": 0,
        }

    def coordinator(self, jobs: ImmortalJobEngine) -> CheckpointedExileCoordinator:
        transport = _GuardedCasTransport(AgentExileEngine(ssh_host=PEER), str(self.cas))
        return CheckpointedExileCoordinator(
            jobs, ZeroEnvCasStore(self.root / "sender-cas"), worker_transport=transport,
            node_name="fixture-controller", remote_target=PEER, max_retries=0,
        )


def _watch_receipt_writes(path: Path) -> None:
    # A primary key alone cannot distinguish an idempotent read from a repeated INSERT OR REPLACE.
    with closing(ImmortalJobEngine(path)), closing(sqlite3.connect(path)) as audit:
        audit.executescript("""
            CREATE TABLE fixture_receipt_writes (job_id TEXT, step_key TEXT, generation INTEGER);
            CREATE TRIGGER fixture_receipt_insert AFTER INSERT ON step_receipts BEGIN
                INSERT INTO fixture_receipt_writes VALUES (NEW.job_id, NEW.step_key, NEW.generation);
            END;
            CREATE TRIGGER fixture_receipt_update AFTER UPDATE ON step_receipts BEGIN
                INSERT INTO fixture_receipt_writes VALUES (NEW.job_id, NEW.step_key, NEW.generation);
            END;
        """)


def _object(cas: Path, digest: str) -> Path:
    return cas / "objects" / digest[:2] / digest


def _trial(root: Path, db: Path, index: int, fault: str) -> dict:
    peer = LocalReceiver(root, fault)
    op, params, blocks = trial_inputs(index, fault)
    job = f"guarded-fault-{index:03d}"
    step = dict(job_id=job, step_key="transform", blocks=blocks, op=op, params=params)
    inputs = {hashlib.blake2s(data, digest_size=16).hexdigest(): data for data in blocks.values()}
    initially_missing = {key for key in inputs if not _object(peer.cas, key).is_file()}
    expected_input, expected = reference_output(op, params, blocks)
    expected_sha = hashlib.sha256(expected).hexdigest()
    expected_cas = hashlib.blake2s(expected, digest_size=16).hexdigest()
    after_commit = fault == "post_commit_pre_client_reply"
    after_compute = fault == "post_compute_pre_ack"
    started = time.perf_counter()

    with patch.object(guarded_build, "submit_isolated", peer.submit):
        with closing(ImmortalJobEngine(db)) as initial:
            try:
                first = peer.coordinator(initial).handoff_step(**step, post_commit_hook=peer.drop_client_reply)
                first_outcome = first.get("state") or ("completed" if first.get("ok") else "failed")
            except ClientReplyLost:
                first_outcome = "client_reply_lost"
            receipts_at_cut = initial.get_receipts(job)

        missing_at_cut = {key for key in inputs if not _object(peer.cas, key).is_file()}
        expected_generation = 1 if after_commit else 2
        calls_at_cut = len(peer.events)
        with closing(ImmortalJobEngine(db)) as reopened:
            coordinator = peer.coordinator(reopened)
            recovered = coordinator.handoff_step(**step)
            first_replay_calls = len(peer.events) - calls_at_cut
            stale_reason = None
            if peer.delayed is not None:
                late = coordinator.submit_receipt(peer.delayed["receipt"], result=peer.delayed["result"])
                if not late.get("ok") and late.get("rejected"):
                    stale_reason = late.get("reason")

        # The last client replay uses new CAS, adapter, journal and coordinator instances again.
        calls_before_replay = len(peer.events)
        with closing(ImmortalJobEngine(db)) as reopened:
            final = peer.coordinator(reopened).handoff_step(**step)
            receipts = reopened.get_receipts(job)
        replay_calls = len(peer.events) - calls_before_replay

    with closing(sqlite3.connect(db)) as audit:
        writes = audit.execute(
            "SELECT generation FROM fixture_receipt_writes WHERE job_id=? AND step_key=?", (job, "transform")
        ).fetchall()
        status = audit.execute("SELECT status FROM jobs WHERE job_id=?", (job,)).fetchone()
    receipt = receipts[0] if len(receipts) == 1 else {}
    counts, delivered = Counter(), Counter()
    for event in peer.events:
        if event["action"] == "push":
            counts.update(event["blocks"].keys())
            if event["received"]:
                delivered.update(event["blocks"].keys())
    expected_pushes = 2 if fault == "pre_receive" else 1
    artifacts = [_object(root / "sender-cas", expected_cas), _object(peer.cas, expected_cas)]
    checks = {
        "cut": peer.fired and first_outcome == ("client_reply_lost" if after_commit else "indeterminate"),
        "at_cut": len(receipts_at_cut) == int(after_commit)
                  and missing_at_cut == (initially_missing if fault == "pre_receive" else set()),
        "completed": recovered.get("ok") is True and final.get("ok") is True and status == ("completed",),
        "journal": writes == [(expected_generation,)] and receipt.get("status") == "committed",
        "generation": receipt.get("generation") == recovered.get("generation") == expected_generation,
        "worker": peer.executed_generations == ([1] if after_commit else [1, 2] if after_compute else [2]),
        "receipt": receipt.get("input_digest") == expected_input and receipt.get("node_id") == platform.node()
                   and receipt.get("output_digest") == expected_sha and receipt.get("output_cas_hash") == expected_cas,
        "artifacts": all(path.is_file() and path.read_bytes() == expected for path in artifacts),
        "remote_inputs": all(_object(peer.cas, key).read_bytes() == data for key, data in inputs.items()
                             if _object(peer.cas, key).is_file()) and all(_object(peer.cas, k).is_file() for k in inputs),
        "delta": bool(initially_missing)
                 and counts == Counter({key: expected_pushes for key in initially_missing})
                 and delivered == Counter(initially_missing),
        "recovery_calls": (first_replay_calls == 0) if after_commit else (first_replay_calls > 0),
        "replay": final.get("idempotent_resume") is True and replay_calls == 0
                  and recovered.get("result") == final.get("result") and final.get("output_digest") == expected_sha,
        "fence": (stale_reason == "stale_generation") if after_compute else peer.delayed is None,
    }
    return {
        "job": job, "fault": fault, "operation": op, "first_outcome": first_outcome,
        "receipt_rows_at_cut": len(receipts_at_cut), "receipt_writes": len(writes),
        "generation": receipt.get("generation"), "executed_generations": peer.executed_generations,
        "input_sha256": receipt.get("input_digest"), "output_sha256": receipt.get("output_digest"),
        "output_cas": receipt.get("output_cas_hash"), "stale_rejection": stale_reason,
        "recovery_receiver_calls": first_replay_calls, "completed_replay_receiver_calls": replay_calls,
        "block_payload_accepted_bytes": sum(len(inputs[key]) * n for key, n in delivered.items()),
        "block_payload_reattempted_bytes": sum(len(inputs[key]) * (n - 1) for key, n in counts.items()),
        "snapshot_bytes_received": sum(e["snapshot_bytes"] for e in peer.events if e["received"]),
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
        "failed_checks": [name for name, passed in checks.items() if not passed],
    }


def run_guarded_trials(ops_dir: Path | None, output_path: Path | None, trials_per_fault: int) -> dict:
    if ops_dir is not None:
        Path(ops_dir).mkdir(parents=True, exist_ok=True)
    start = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="chimera-guarded-trials-", dir=ops_dir) as fixture:
        root = Path(fixture).resolve()
        journal = root / "jobs.db"
        _watch_receipt_writes(journal)
        rows = [_trial(root, journal, i, FAULT_POINTS[i % len(FAULT_POINTS)])
                for i in range(trials_per_fault * len(FAULT_POINTS))]
        with closing(sqlite3.connect(journal)) as audit:
            integrity = audit.execute("PRAGMA integrity_check").fetchone()[0]
    passed = sum(not row["failed_checks"] for row in rows)
    report = {
        "schema": "chimera.exile-guard-fault-trials/1", "measured_at_utc": datetime.now(timezone.utc).isoformat(),
        "ok": passed == len(rows) and integrity == "ok", "host": platform.node(),
        "python": platform.python_version(), "total_trials": len(rows), "passed_trials": passed,
        "trials_per_fault": trials_per_fault, "fault_counts": dict(Counter(row["fault"] for row in rows)),
        "scope": {
            "real": "Coordinator.handoff_step, guarded_cas.dispatch, build snapshots, isolated cas_work.py, "
                    "artifact checks, two filesystem CAS stores, reopened SQLite journal and write triggers",
            "simulated": "submit_isolated supplies the SSH/admission response. All workers execute locally. "
                         "Recovery resubmits the original step with its job ID. No queue delivery is exercised.",
            "bytes": "Block counters are uncompressed input bytes. Snapshot bytes are ZIP bodies delivered "
                     "to the local worker. No network bytes are measured.",
        },
        "oracle_byte_matches_both_stores": sum("artifacts" not in row["failed_checks"] for row in rows),
        "single_committed_receipt_per_step": sum("journal" not in row["failed_checks"] for row in rows),
        "delayed_stale_receipts_rejected": sum(row["stale_rejection"] == "stale_generation" for row in rows),
        "post_commit_zero_receiver_calls": sum(row["recovery_receiver_calls"] == 0 for row in rows
                                               if row["fault"] == "post_commit_pre_client_reply"),
        "completed_replays_zero_receiver_calls": sum(row["completed_replay_receiver_calls"] == 0 for row in rows),
        "block_payload_reattempted_by_fault": {
            fault: sum(row["block_payload_reattempted_bytes"] for row in rows if row["fault"] == fault)
            for fault in FAULT_POINTS
        },
        "sqlite_integrity": integrity, "elapsed_s": round(time.perf_counter() - start, 2), "trials": rows,
    }
    if output_path is not None:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report
