"""Receipts must track completed work, remain scoped, and expire without read-side effects."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json
import re
import tempfile
import time
import unittest
from unittest.mock import patch

from chimera_tp.platform.evidence import EvidenceLedger
from chimera_tp.platform.pulse_bus import PulseBus


class TrafficEvidenceTests(unittest.TestCase):
    def test_concurrent_writes_are_coalesced_without_losing_counts(self):
        with tempfile.TemporaryDirectory() as name:
            ledger = EvidenceLedger(name)
            observe = ledger.activity_observer("test-node", synthetic=True)
            with patch.object(ledger, "_save_locked", wraps=ledger._save_locked) as save:
                with ThreadPoolExecutor(max_workers=8) as workers:
                    list(workers.map(lambda n: observe("pulse.publish", True, n), range(1, 257)))
                self.assertEqual(save.call_count, 1)
                result = ledger.evaluate("pulse")
                self.assertEqual(result["sample_count"], 256)
                self.assertEqual(result["evidence_source"], "fixture_traffic")
                self.assertTrue(re.fullmatch("[0-9a-f]{64}", result["receipt_id"]))
                self.assertEqual(ledger.truth_matrix({"pulse": True})["capabilities"]["pulse"]["basis"], "fixture_traffic")
                ledger.flush_traffic()
                self.assertEqual(save.call_count, 2)
                self.assertEqual(json.loads(ledger.path.read_text())["entries"]["pulse"]["sample_count"], 256)
                ledger.flush_traffic()
                self.assertEqual(save.call_count, 2)
            reloaded = EvidenceLedger(name).evaluate("pulse")
            self.assertEqual(reloaded["verification_status"], "unverified")
            self.assertTrue(reloaded["previous_process"])
            self.assertEqual(reloaded["receipt_id"], result["receipt_id"])

    def test_failure_revokes_a_success_and_reads_do_not_refresh_or_write(self):
        with tempfile.TemporaryDirectory() as name:
            ledger = EvidenceLedger(name)
            observe = ledger.activity_observer("node", ttl_s=0.2, flush_interval_s=0.03)
            observe("egress.forward", True, 200)
            original = ledger.evaluate("egress_membrane")
            observe("egress.forward", False, 503)
            failed = ledger.evaluate("egress_membrane")
            self.assertEqual(failed["verification_status"], "unverified")
            self.assertEqual(failed["last_verified_at"], original["last_verified_at"])
            self.assertEqual(failed["metrics"], {"operation": "egress.forward", "successful": False, "http_status": 503})
            self.assertNotEqual(failed["receipt_id"], original["receipt_id"])
            # The previous on-disk success is already stale on a simulated unclean restart.
            self.assertEqual(EvidenceLedger(name).evaluate("egress_membrane")["verification_status"], "unverified")
            before = ledger.path.stat().st_mtime_ns
            for _ in range(20):
                ledger.snapshot()
                self.assertEqual(ledger.truth_matrix({"egress_membrane": True})["capabilities"]["egress_membrane"]["basis"], "unverified")
            self.assertEqual(ledger.path.stat().st_mtime_ns, before)
            self.assertEqual(failed, ledger.evaluate("egress_membrane"))
            observe("egress.forward", True, 201)
            restored = ledger.evaluate("egress_membrane")
            self.assertEqual(restored["evidence_source"], "runtime_traffic")
            self.assertEqual(restored["verification_status"], "verified")
            expires = datetime.fromisoformat(restored["expires_at"]).timestamp()
            self.assertTrue(ledger.evaluate("egress_membrane", now_epoch=expires + 0.000002)["stale"])
            time.sleep(0.22)
            expired = ledger.evaluate("egress_membrane")
            self.assertEqual(expired["verification_status"], "unverified")
            self.assertEqual(expired["receipt_id"], restored["receipt_id"])

    def test_unmeasured_capabilities_startup_receipts_and_manual_records_remain_distinct(self):
        ledger = EvidenceLedger()
        observe = ledger.activity_observer("node")
        ledger.record("connect", execution_node="node", metrics={"startup_self_check": True})
        ledger.record("exile", execution_node="node", receipt_id="external")
        observe("pulse.publish", True, 3)
        observe("pulse.relay", False, 3)
        matrix = ledger.truth_matrix({"connect": True, "pulse": True, "peer_guard": True})
        self.assertEqual({n: value["basis"] for n, value in matrix["capabilities"].items()}, {
            "connect": "startup_check", "pulse": "runtime_traffic", "peer_guard": "unverified",
            "pulse.relay": "unverified", "exile": "recorded_receipt",
        })
        self.assertEqual(ledger.truth_matrix({"pulse": False})["capabilities"]["pulse.relay"]["basis"], "disabled")
        for invalid in [
            ("pulse.publish", "true", 1), ("pulse.publish", True, False),
            ("egress.forward", True, 503), ("egress.forward", False, 200),
            ("egress.forward", True, 700),
        ]:
            with self.subTest(observation=invalid), self.assertRaises(ValueError):
                observe(*invalid)
        with self.assertRaises(KeyError):
            observe("untracked_operation", True, 1)
        self.assertEqual(ledger.evaluate("egress_membrane")["sample_count"], 0)

    def test_old_relay_completion_and_empty_polls_cannot_confirm_delivery(self):
        ledger = EvidenceLedger()
        bus = PulseBus("receiver", on_activity=ledger.activity_observer("receiver", synthetic=True))
        bus._observe("pulse.relay", False, 20)
        bus._observe("pulse.relay", True, 19)
        bus.poll("unseen", wait_ms=1)
        bus.stats()
        row = ledger.evaluate("pulse.relay")
        self.assertEqual(row["verification_status"], "unverified")
        self.assertEqual(row["metrics"]["sequence"], 20)
        self.assertEqual(ledger.evaluate("pulse")["sample_count"], 0)

    def test_leaky_or_unavailable_telemetry_does_not_interrupt_publishing(self):
        def unavailable(*args):
            raise OSError("temporary test ledger is unavailable")

        bus = PulseBus("sender", on_activity=unavailable)
        event = bus.publish("internal/topic", {"private-key": "fixture"}, relay=False)
        self.assertEqual(bus.poll()["events"], [event])


if __name__ == "__main__":
    unittest.main()
