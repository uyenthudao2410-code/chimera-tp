"""Sentinel suffix parity, content-based invalidation and bounded report retention."""

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from chimera_tp import sentinel
from chimera_tp.active_pipe import ComputePlan, execute_operator
from chimera_tp.autopilot import OpsConfig


def reference_report(data, limit):
    if len(data) > limit:
        suffix = data[len(data) - limit:]
        index = suffix.find(b"\n")
        data = suffix[index + 1:] if 0 <= index < len(suffix) - 1 else suffix
    payload, _, _ = execute_operator(data, ComputePlan(op="log_analytics"))
    return json.loads(payload)


class SentinelTailTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.engine = sentinel.SentinelEngine(self.root / "ops")
        self.addCleanup(self.engine.close)
        self.path = self.root / "work.log"

    def test_suffix_matches_wire_operator_at_cutoffs_and_line_boundaries(self):
        long_record = b"X" * 65537
        cases = [
            b"", b"INFO\nERROR", b"A\nB\n", b"\r\n", b"\xff\x80\nWARN\r",
            "kÃ½\rhiá»‡u\u0085dÃ²ng\u2028káº¿\u2029tiáº¿p\r\n".encode(),
            long_record + b"\n", long_record + b"\r\nA\nB",
        ]
        for data in cases:
            self.path.write_bytes(data)
            for limit in sorted({0, 1, 2, 8, 65536, max(0, len(data) - 1), len(data)}):
                with self.subTest(size=len(data), limit=limit):
                    self.assertEqual(self.engine._log_report(self.path, limit),
                                     reference_report(data, limit))

    def test_equal_size_and_timestamp_still_detect_rewrite_and_rotation(self):
        self.path.write_bytes(b"INFO A\n")
        original = self.path.stat()
        with patch.object(sentinel, "analyze_log_lines", wraps=sentinel.analyze_log_lines) as analyze:
            first = self.engine._log_report(self.path, 512)
            self.assertEqual(self.engine._log_report(self.path, 512), first)
            self.assertEqual(analyze.call_count, 1)
            for rotate, data in ((False, b"WARN A\n"), (True, b"FAIL A\n")):
                destination = self.root / "next" if rotate else self.path
                destination.write_bytes(data)
                os.utime(destination, ns=(original.st_atime_ns, original.st_mtime_ns))
                if rotate:
                    destination.replace(self.path)
                self.assertEqual(self.engine._log_report(self.path, 512), reference_report(data, 512))
            self.assertEqual(analyze.call_count, 3)
        self.path.write_bytes(b"")
        self.assertEqual(self.engine._log_report(self.path, 512)["total_lines"], 0)

    def test_changed_bytes_between_comparison_and_parse_use_the_parsed_digest(self):
        self.path.write_bytes(b"INFO A\n")
        self.engine._log_report(self.path, 128)
        self.path.write_bytes(b"WARN B\n")
        original = sentinel._tail_lines

        def change_open_file(stream, remaining, digest):
            with self.path.open("r+b") as output:
                output.write(b"FAIL C\n")
            return original(stream, remaining, digest)

        with patch.object(sentinel, "_tail_lines", side_effect=change_open_file):
            report = self.engine._log_report(self.path, 128)
        # A buffered file can supply either coherent suffix. Restore the second
        # version and validate that cache reuse always agrees with its actual bytes.
        self.assertEqual(report["total_lines"], 1)
        for data in (b"WARN B\n", b"FAIL C\n"):
            self.path.write_bytes(data)
            self.assertEqual(self.engine._log_report(self.path, 128), reference_report(data, 128))

    def test_small_cache_preserves_alert_dedup_and_retires_missing_logs(self):
        self.path.write_bytes(b"ERROR fixed\n" * 32)
        config = OpsConfig(role="server", node_name="unit", watched_query_file=str(self.path),
                           allowed_query_roots=[], edge_targets={})
        with patch.object(sentinel, "analyze_log_lines", wraps=sentinel.analyze_log_lines) as analyze:
            first = self.engine.scan(config)
            second = self.engine.scan(config)
            self.assertEqual(analyze.call_count, 1)
        self.assertEqual(first["logs_scanned"], second["logs_scanned"])
        self.assertTrue(any(a["category"] == "LOG_SPIKE" for a in first["alerts"]))
        self.assertEqual(second["suppressed_repeats"], 1)
        self.path.rename(self.root / "retired")
        self.engine.scan(config)
        self.assertFalse(self.engine._log_reports)
        for index in range(20):
            path = self.root / str(index)
            path.write_bytes(b"OK\n")
            self.engine._log_report(path, 512)
        self.assertEqual(len(self.engine._log_reports), 12)

    def test_large_template_is_reported_without_retention(self):
        self.path.write_bytes(b"Z" * 8000)
        actual = self.engine._log_report(self.path, 8000)
        self.assertEqual(len(actual["top_templates"][0]["template"]), 8000)
        self.assertNotIn(self.path, self.engine._log_reports)
