"""Tests for CHIMERA-HYPERDESK controlled alternating A/B experiment & telemetry."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_BENCH_PATH = _REPO_ROOT / "scripts" / "bench_hyperdesk_ab.py"
_SPEC = importlib.util.spec_from_file_location("bench_hyperdesk_ab", _BENCH_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_BENCH = importlib.util.module_from_spec(_SPEC)
sys.modules["bench_hyperdesk_ab"] = _BENCH
_SPEC.loader.exec_module(_BENCH)


class TestV24HyperDeskAB(unittest.TestCase):
    def test_01_alternating_ab_ba_schedule_generation(self) -> None:
        sched = _BENCH.generate_ab_schedule(10)
        self.assertEqual(len(sched), 10)
        expected = [("A", "B") if i % 2 == 0 else ("B", "A") for i in range(10)]
        self.assertEqual(sched, expected)
        self.assertEqual(["".join(p) for p in sched], ["AB", "BA"] * 5)

    def test_02_summary_stats_and_decision_classifier(self) -> None:
        self.assertEqual(_BENCH.classify_ab_outcome(20.0, 10.0), "PROMOTE_RECOMMENDED")
        self.assertEqual(_BENCH.classify_ab_outcome(35.0, 4.2), "PROMOTE_RECOMMENDED")
        self.assertEqual(_BENCH.classify_ab_outcome(19.99, 5.0), "MIXED_KEEP_OPT_IN")
        self.assertEqual(_BENCH.classify_ab_outcome(45.0, 10.01), "MIXED_KEEP_OPT_IN")

        # Build 4 synthetic pairs: 3 with strong p99 reduction & low build overhead -> PROMOTE_RECOMMENDED
        def _mk_pair(idx: int, order: str, p99_a: float, p99_b: float, b_a: float, b_b: float) -> dict:
            run_a = {
                "fg": {"p50_ms": 5.0, "p95_ms": 15.0, "p99_ms": p99_a, "dropped_frames_pct": 4.0},
                "bg": {"build_time_s": b_a},
                "memory": {"working_set_mb": 320.0, "private_commit_mb": 340.0, "total_page_fault_count": 50000},
                "faults": {"hard_page_faults_per_s": 2.0, "pages_input_per_s": 4.0, "soft_page_faults_per_s": 8000.0},
            }
            run_b = {
                "fg": {"p50_ms": 4.0, "p95_ms": 10.0, "p99_ms": p99_b, "dropped_frames_pct": 0.5},
                "bg": {"build_time_s": b_b},
                "memory": {"working_set_mb": 310.0, "private_commit_mb": 335.0, "total_page_fault_count": 49000},
                "faults": {"hard_page_faults_per_s": 1.5, "pages_input_per_s": 3.0, "soft_page_faults_per_s": 7800.0},
            }
            return {"pair": idx, "order": order, "run_a": run_a, "run_b": run_b, "deltas": _BENCH.compute_pair_deltas(run_a, run_b)}

        promote_pairs = [
            _mk_pair(1, "AB", 40.0, 20.0, 10.0, 10.5),   # +50% p99 red, +5% build
            _mk_pair(2, "BA", 50.0, 25.0, 10.0, 10.8),   # +50% p99 red, +8% build
            _mk_pair(3, "AB", 30.0, 21.0, 10.0, 10.9),   # +30% p99 red, +9% build
            _mk_pair(4, "BA", 25.0, 22.0, 10.0, 12.0),   # +12% p99 red, +20% build
        ]
        res_ok = _BENCH.summarize_pairs(promote_pairs)
        self.assertEqual(res_ok["decision"], "PROMOTE_RECOMMENDED")
        self.assertGreaterEqual(res_ok["summary"]["p99_reduction_pct"]["median"], 20.0)
        self.assertLessEqual(res_ok["summary"]["build_time_delta_pct"]["median"], 10.0)
        for stat_k in ("mean", "median", "p25", "p75", "min", "max"):
            self.assertIn(stat_k, res_ok["summary"]["p99_reduction_pct"])
            self.assertIn(stat_k, res_ok["summary"]["build_time_delta_pct"])

        # Failing build-overhead case -> MIXED_KEEP_OPT_IN
        mixed_pairs = [
            _mk_pair(1, "AB", 40.0, 16.0, 5.0, 9.0),     # +60% p99 red, +80% build
            _mk_pair(2, "BA", 45.0, 18.0, 5.0, 10.0),    # +60% p99 red, +100% build
        ]
        res_mix = _BENCH.summarize_pairs(mixed_pairs)
        self.assertEqual(res_mix["decision"], "MIXED_KEEP_OPT_IN")

    def test_03_one_pair_smoke_benchmark_and_schema(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out_file = Path(td) / "ab_smoke.json"
            report = _BENCH.run_ab_experiment(
                pairs=1,
                frames=24,
                target_fps=60.0,
                vertices=1200,
                workers=3,
                jobs_per_worker=18,
                cooldown_s=0.05,
                isolate_live_daemon=False,
                include_vram_check=False,
                out_path=out_file,
            )
            self.assertTrue(out_file.is_file())
            self.assertEqual(report["config"]["pairs"], 1)
            self.assertEqual(report["config"]["schedule_orders"], ["AB"])
            self.assertIn(report["decision"], ("PROMOTE_RECOMMENDED", "MIXED_KEEP_OPT_IN"))
            self.assertEqual(len(report["pairs"]), 1)

            pair = report["pairs"][0]
            for cond_key in ("run_a", "run_b"):
                run = pair[cond_key]
                for k in ("p50_ms", "p95_ms", "p99_ms", "dropped_frames_pct"):
                    self.assertIn(k, run["fg"])
                self.assertIn("build_time_s", run["bg"])
                self.assertGreater(run["bg"]["build_time_s"], 0.0)
                for k in ("working_set_mb", "private_commit_mb", "total_page_fault_count"):
                    self.assertIn(k, run["memory"])
                    self.assertGreaterEqual(run["memory"][k], 0.0)
                for k in ("hard_page_faults_per_s", "pages_input_per_s", "soft_page_faults_per_s"):
                    self.assertIn(k, run["faults"])
                    self.assertGreaterEqual(run["faults"][k], 0.0)


if __name__ == "__main__":
    unittest.main()
