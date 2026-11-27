from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, redirect_stdout
import copy
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest import mock

from chimera_tp.platform import build_queue, guarded_build
from chimera_tp.platform.immortal_jobs import ImmortalJobEngine
from scripts.exile_fault_cases import reference_output
from scripts.exile_guard_fault_fixture import LocalReceiver, PEER


DENIED = {"ok": False, "state": "deferred", "error": "guest_slots_busy", "retryable": False}


class ExileQueueTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="chimera-exile-outbox-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.peer = LocalReceiver(self.root, fault="")
        self.journal = self.root / "jobs.sqlite"
        self.jobs = ImmortalJobEngine(self.journal)
        self.addCleanup(self.jobs.close)
        self.coord = self.peer.coordinator(self.jobs)
        self.queue = self.coord.queue_dir
        self.steps = [
            {"step_key": "a", "op": "xor_scale", "params": {"mask": 17},
             "blocks": {"first": b"one", "shared": b"unchanged"}},
            {"step_key": "b", "op": "xor_scale", "params": {"mask": 23},
             "blocks": {"next": b"two", "shared": b"unchanged"}},
            {"step_key": "c", "op": "zlib_compress", "params": {"level": 2},
             "blocks": {"later": b"three", "shared": b"unchanged"}},
        ]

    def test_resume_multistep_from_frozen_job_and_list_via_cli(self):
        frozen = copy.deepcopy(self.steps)
        job_id = "defer-second"

        def deny_after_commit(*args, **kwargs):
            if self.jobs.get_receipts(job_id):
                return DENIED
            return self.peer.submit(*args, **kwargs)

        with mock.patch.object(guarded_build, "submit_isolated", side_effect=deny_after_commit):
            deferred = self.coord.handoff_job(self.steps, job_id=job_id)
        self.assertEqual(deferred["state"], "deferred")
        self.assertTrue(deferred["retryable"])
        self.assertEqual(len(self.jobs.get_receipts(job_id)), 1)
        ticket = deferred["queue"]["id"]

        from chimera_tp.cli import main

        captured = io.StringIO()
        with redirect_stdout(captured):
            self.assertEqual(main(["swarm-queue", "--state-dir", str(self.queue), "list"]), 0)
        pending, = json.loads(captured.getvalue())["pending"]
        self.assertEqual((pending["id"], pending["job_id"], pending["kind"]),
                         (ticket, job_id, "exile_handoff"))
        self.assertEqual(pending["wire_bytes"], sum(map(len, (b"one", b"two", b"three", b"unchanged"))))

        self.steps[-1]["blocks"]["later"] = b"changed by caller"
        with mock.patch.object(guarded_build, "submit_isolated", return_value=DENIED) as guard:
            changed = self.coord.handoff_job(self.steps, job_id=job_id)
            guard.assert_not_called()
            self.assertEqual(changed["error"], "queued_exile_inputs_changed")
            retained = guarded_build.retry_queued(ticket, state_dir=self.queue)
            self.assertEqual(retained["queue"], {"stored": True, "id": ticket})
            guard.assert_called_once()

        captured = io.StringIO()
        with mock.patch.object(guarded_build, "submit_isolated", side_effect=self.peer.submit), redirect_stdout(captured):
            self.assertEqual(main(["swarm-queue", "--state-dir", str(self.queue), "retry", ticket]), 0)
        finished = json.loads(captured.getvalue())
        self.assertTrue(finished["steps"][0]["idempotent_resume"])
        for index, step in enumerate(frozen):
            input_sha, output = reference_output(step["op"], step["params"], step["blocks"])
            result = finished["steps"][index]
            self.assertEqual(result["input_digest"], input_sha)
            self.assertEqual(result["output_digest"], hashlib.sha256(output).hexdigest())
        self.assertEqual(len(self.peer.executed_generations), 3)
        self.assertEqual(len(self.jobs.get_receipts(job_id)), 3)
        self.assertEqual(build_queue.list_pending(self.queue), [])
        with mock.patch.object(guarded_build, "submit_isolated") as transport:
            replay = self.coord.handoff_job(frozen, job_id=job_id)
            self.assertTrue(replay["ok"])
            transport.assert_not_called()

    def test_lost_compute_reply_and_competing_retries_commit_once(self):
        self.peer.fault = "post_compute_pre_ack"
        with mock.patch.object(guarded_build, "submit_isolated", side_effect=self.peer.submit):
            deferred = self.coord.handoff_job(self.steps[:1], job_id="lost")
        self.assertEqual(deferred["state"], "indeterminate")
        self.assertEqual(self.jobs.get_receipts("lost"), [])
        self.assertEqual(self.peer.executed_generations, [1])
        ticket = deferred["queue"]["id"]
        entered = threading.Event()
        release = threading.Event()

        def resume(*args, **kwargs):
            self.assertEqual(kwargs["peer"], PEER)
            entered.set()
            self.assertTrue(release.wait(timeout=6))
            return self.peer.submit(*args, **kwargs)

        with mock.patch.object(guarded_build, "submit_isolated", side_effect=resume), ThreadPoolExecutor(1) as pool:
            future = pool.submit(guarded_build.retry_queued, ticket, state_dir=self.queue)
            try:
                self.assertTrue(entered.wait(timeout=6))
                second = guarded_build.retry_queued(ticket, state_dir=self.queue)
                self.assertEqual(second["error"], "exile_replay_in_progress")
            finally:
                release.set()
            result = future.result(timeout=12)
        self.assertTrue(result["ok"], result)
        self.assertEqual(self.peer.executed_generations, [1, 2])
        receipt, = self.jobs.get_receipts("lost")
        self.assertEqual(receipt["generation"], 2)
        self.assertEqual(build_queue.list_pending(self.queue), [])

    def test_outbox_limit_and_tampered_job_do_not_dispatch(self):
        with mock.patch.object(guarded_build, "submit_isolated", return_value=DENIED):
            with mock.patch.object(build_queue, "MAX_PENDING_BYTES", 10):
                full = self.coord.handoff_job(self.steps[:1], job_id="full")
            self.assertEqual(full["queue"], {"stored": False, "reason": "outbox_capacity"})
            self.assertFalse(full["retryable"])
            stored = self.coord.handoff_job(self.steps[:1], job_id="corrupt")
        ticket = stored["queue"]["id"]
        with closing(sqlite3.connect(self.queue / "outbox.sqlite")) as db, db:
            db.execute("UPDATE pending SET wire=zeroblob(length(wire)) WHERE id=?", (ticket,))
        with mock.patch.object(guarded_build, "submit_isolated") as dispatch:
            failure = guarded_build.retry_queued(ticket, state_dir=self.queue)
            self.assertEqual(failure["error"], "queued_exile_input_corrupt")
            self.assertEqual(failure["queue"]["id"], ticket)
            dispatch.assert_not_called()
        self.assertEqual(self.jobs.get_receipts("corrupt"), [])
