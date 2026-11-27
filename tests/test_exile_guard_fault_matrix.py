from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import exile_guard_fault_fixture as fixture
from scripts.bench_exile_handoff import run_fault_injection_benchmark
from scripts.exile_fault_cases import FAULT_POINTS, reference_output


class GuardedExileRecoveryTests(unittest.TestCase):
    def test_all_cut_points_survive_reopening_journal(self):
        report = run_fault_injection_benchmark(trials_per_fault=1, transport_mode="guarded-local")
        for row in report["trials"]:
            with self.subTest(fault=row["fault"]):
                self.assertEqual([], row["failed_checks"])
                self.assertEqual(1, row["receipt_writes"])
                self.assertEqual(0, row["completed_replay_receiver_calls"])
        self.assertTrue(report["ok"])
        self.assertEqual(dict.fromkeys(FAULT_POINTS, 1), report["fault_counts"])
        self.assertEqual(1, report["delayed_stale_receipts_rejected"])
        self.assertEqual(1, report["post_commit_zero_receiver_calls"])

    def test_byte_oracle_disagrees_even_when_journal_and_worker_agree(self):
        def bad_expected_bytes(op, params, blocks):
            digest, expected = reference_output(op, params, blocks)
            return digest, expected + b"!"

        with tempfile.TemporaryDirectory() as workspace:
            root = Path(workspace).resolve()
            journal = root / "jobs.db"
            fixture._watch_receipt_writes(journal)
            with patch.object(fixture, "reference_output", bad_expected_bytes):
                row = fixture._trial(root, journal, 0, "post_commit_pre_client_reply")
        self.assertEqual(1, row["receipt_writes"])
        self.assertIn("receipt", row["failed_checks"])
        self.assertIn("artifacts", row["failed_checks"])
