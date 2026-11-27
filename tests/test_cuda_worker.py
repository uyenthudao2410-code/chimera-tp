"""Numeric parity and the lifecycle of the Windows daemon's on-demand CUDA process."""

import os
import time
import unittest
from unittest.mock import patch

from chimera_tp.platform.vgpu_gateway import VgpuParetoGateway


class CpuBenchmarkTests(unittest.TestCase):
    def test_fallback_preserves_pairwise_and_generated_dot_products(self):
        gateway = VgpuParetoGateway("cpu-test", role="server")
        with patch.object(gateway, "evaluate_gpu_eligibility", return_value={"gpu_ready": False, "reason": "test"}):
            res = gateway.run_ptx_kernel_if_eligible([5., 7.], [-3.])
            self.assertEqual((res["dot"], res["n"], res["engine"]), (-15., 1, "cpu_yield_fallback"))
            for n in (64, 262144):
                expected = sum((i % 13 - 6) * (i % 7 - 3) for i in range(n))
                bench = gateway.run_ptx_benchmark(n)
                self.assertEqual((bench["dot"], bench["n"]), (expected, n))


@unittest.skipUnless(os.name == "nt", "Windows CUDA process boundary")
class CudaWorkerTests(unittest.TestCase):
    def setUp(self):
        from chimera_tp.platform.cuda_worker_client import CudaWorkerEngine
        self.engine = CudaWorkerEngine(lease_ttl_s=1.5)
        self.addCleanup(self.engine.release_lease)
        if not self.engine.probe()["available"]:
            self.skipTest("no CUDA device detected")

    def test_numeric_frames_match_cpu_and_reject_short_input_before_launch(self):
        engine = self.engine
        count = engine.lease_status()["workers_started"]
        with self.assertRaises(ValueError):
            engine.run_vsa_hamming_batch(b"x", b"y", rows=1)
        self.assertEqual(engine.lease_status()["workers_started"], count)
        for a, b, expected in (([], [], 0.), ([2., 5., 90.], [3., -1.], 1.)):
            result = engine.run_vec_dot_kernel(a, b)
            self.assertEqual(result["dot"], expected)
            self.assertTrue(result["worker"]["exited"])
        result = engine.run_es_axpy_kernel([0., 4.], [2., -2.], .25)
        self.assertEqual(result["out"], [.5, 3.5])
        empty = engine.run_vsa_hamming_batch(b"", b"", rows=0)
        self.assertEqual(empty["distances"], [])
        self.assertTrue(empty["worker"]["exited"])

    def test_hamming_lease_expires_or_yields_on_foreground(self):
        q = bytes(1252)
        m = q + b"\xff" * len(q)
        first = self.engine.run_vsa_hamming_batch(q, m, rows=2, use_lease=True)
        second = self.engine.run_vsa_hamming_batch(q, m, rows=2, use_lease=True)
        self.assertEqual(first["distances"], [0, 10016])
        self.assertEqual(second["distances"], first["distances"])
        if first["lease_active"] and second["lease_reused"]:
            self.assertEqual(first["worker"]["pid"], second["worker"]["pid"])
        if not second["lease_active"]:
            self.assertTrue(second["worker"]["exited"])
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline and not self.engine.lease_status()["worker"]["exited"]:
            time.sleep(.08)
        status = self.engine.lease_status()
        self.assertTrue(status["worker"]["exited"])
        self.assertFalse(status["lease_active"])
        self.assertEqual(status["vram_retained_mb"], 0.)
