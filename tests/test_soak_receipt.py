import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from scripts.check_daemon_soak import BUDGET, DAY, SVHOME_RSS_TARGET, check


class SoakReceiptTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.report_file = Path(temp.name) / "soak.json"
        self.release_file = Path(temp.name) / "release.json"
        self.start = datetime(2026, 11, 20, tzinfo=timezone.utc)
        self.nodes = {
            name: {"pid": pid, "started_at": self.start.isoformat(), "version": "test",
                   "rss_bytes": 30 * 1024**2, "peak_bytes": 44 * 1024**2}
            for name, pid in (("win-desktop", 1001), ("svhome", 1002))
        }
        release = {"schema": "chimera.workstation-rollout/1", "release": "test",
                   "nodes": self.nodes, "live": self.nodes}
        raw = json.dumps(release).encode()
        self.release_file.write_bytes(raw)
        self.rollout_sha = hashlib.sha256(raw).hexdigest()

    def receipt(self, end=DAY, *, state="passed", skip=(), miss=(), remove_check=()):
        rows = []
        for seconds in range(0, end + 1, 300):
            if seconds in skip:
                continue
            row = {"utc": (self.start + timedelta(seconds=seconds)).isoformat(), "nodes": self.nodes}
            if seconds in miss:
                row["error"] = "source probe timed out"
            elif seconds % 3600 == 0 and seconds not in remove_check:
                row["release_sources_verified"] = True
            rows.append(row)
        with self.report_file.with_suffix(".jsonl").open("w", encoding="utf-8") as journal:
            for row in rows:
                journal.write(json.dumps(row) + "\n")
        info = {"schema": "chimera.live-daemon-soak/1", "release": "test", "journal": "soak.jsonl",
                "started_utc": rows[0]["utc"], "updated_utc": rows[-1]["utc"], "interval_seconds": 300,
                "source_check_interval_seconds": 3600, "required_seconds": DAY, "exclusive_limit_bytes": BUDGET,
                "rollout_receipt": self.release_file.name, "rollout_sha256": self.rollout_sha,
                "expected_pids": {k: v["pid"] for k, v in self.nodes.items()},
                "maximum_bytes": {k: v["peak_bytes"] for k, v in self.nodes.items()},
                "samples": len(rows), "source_checks": sum(bool(r.get("release_sources_verified")) for r in rows),
                "missed": len(miss), "observed_seconds": end, "state": state}
        self.report_file.write_text(json.dumps(info), encoding="utf-8")

    def inspect(self, age=0):
        return check(self.report_file, None, now=self.start + timedelta(seconds=age))

    def test_pass_requires_full_day_and_hourly_and_final_checks(self):
        self.receipt()
        self.assertEqual(self.inspect()["state"], "passed")
        for options, reason in [
            ({"end":3600}, "incomplete_final_attestation"),
            ({"remove_check":[DAY]}, "incomplete_final_attestation"),
            ({"remove_check":[3600]}, "hourly_source_check_missing"),
            ({"skip":[300,600]}, "observation_gap_in_journal"),
        ]:
            with self.subTest(options=options):
                self.receipt(**options)
                with self.assertRaisesRegex(ValueError, reason):
                    self.inspect()

    def test_stale_and_valid_current_samples(self):
        self.receipt(900, state="running", miss=[300])
        self.assertEqual(self.inspect(920)["state"], "running")
        self.assertEqual(self.inspect(2000)["state"], "stale")

    def test_linux_rss_target_uses_each_sample_in_bytes(self):
        self.nodes["svhome"]["peak_bytes"] = 72 * 1024**2
        self.receipt(600, state="running")
        path = self.report_file.with_suffix(".jsonl")
        rows = [json.loads(line) for line in path.read_bytes().splitlines()]
        values = (SVHOME_RSS_TARGET + 1, SVHOME_RSS_TARGET, SVHOME_RSS_TARGET - 1)
        for row, rss in zip(rows, values):
            row["nodes"]["svhome"]["rss_bytes"] = rss
        path.write_bytes(b"".join(json.dumps(row).encode() + b"\n" for row in rows))
        result = self.inspect(605)
        self.assertEqual(result["state"], "running")
        self.assertEqual(result["svhome_sampled_rss"], {
            "exclusive_target_bytes": SVHOME_RSS_TARGET, "samples": 3,
            "at_or_above_target": 2, "last_bytes": values[-1], "max_bytes": max(values),
        })
        self.assertEqual(result["peak_mib"]["svhome"], 72.0)

    def test_changed_rollout_or_kernel_budget_is_never_accepted(self):
        self.nodes["svhome"]["peak_bytes"] = BUDGET
        self.receipt()
        with self.assertRaisesRegex(ValueError, "invalid_kernel_peak"):
            self.inspect()
        self.release_file.write_bytes(self.release_file.read_bytes() + b" ")
        with self.assertRaisesRegex(ValueError, "rollout_digest_changed"):
            self.inspect()

    def test_ignore_next_sample_until_its_summary_is_published(self):
        self.receipt(600, state="running")
        with self.report_file.with_suffix(".jsonl").open("ab") as stream:
            stream.write(b'{"utc":')
        self.assertEqual(self.inspect(605)["samples"], 3)
