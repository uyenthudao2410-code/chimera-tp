"""Regression cases for receiver capacity, enforced budgets and process leases."""

import contextlib
import json
import os
import signal
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from chimera_tp.platform import peer_guard as guard


def healthy(config=None):
    cfg = guard._config(config)
    limits = {
        "memory_high": cfg["job_memory_mib"] * 1024 ** 2 * 4 // 5,
        "memory_max": cfg["job_memory_mib"] * 1024 ** 2, "swap_max": 0,
        "cpu_quota_pct": cfg["cpu_quota_pct"], "tasks_max": cfg["max_tasks"],
        "io_write_bps": None,
    }
    return {"sample_age_s": 0.1, "available_ram_mib": 6000, "available_disk_mib": 30000,
            "load1": 0.5, "temp_c": 50, "psi_some_avg10": {"cpu": 0, "memory": 0, "io": 0},
            "service_p95_ms": {"beacon": 1}, "limits": limits, "user_controllers": ["cpu", "memory", "pids"]}


class TestPeerGuard(unittest.TestCase):
    def test_memory_and_disk_are_reserved_after_counting_the_job(self):
        cfg = guard._config({})
        self.assertGreaterEqual(cfg["disk_reserve_mib"] * 1024 ** 2, 15_000_000_000)
        self.assertLess((cfg["disk_reserve_mib"] - 1) * 1024 ** 2, 15_000_000_000)
        for metric, floor, budget, expected in (
            ("available_ram_mib", "ram_reserve_mib", "job_memory_mib", "ram_reserve"),
            ("available_disk_mib", "disk_reserve_mib", "job_disk_mib", "disk_reserve"),
        ):
            with self.subTest(metric=metric):
                h = healthy()
                h[metric] = cfg[floor] + cfg[budget] - 1
                self.assertEqual(guard._decision(cfg, h, True), expected)
                h[metric] += 1
                self.assertIsNone(guard._decision(cfg, h, True))

    def test_stale_pressure_heat_and_health_refuse(self):
        cfg = guard._config({})
        cases = [
            ({"sample_age_s": 6}, "stale_sample"),
            ({"load1": 1.81}, "host_load"),
            ({"load1": None}, "load_unavailable"),
            ({"load1": float("nan")}, "load_unavailable"),
            ({"temp_c": 70}, "temperature"),
            ({"service_p95_ms": {"api": 151}}, "service_latency"),
        ]
        for kind in ("cpu", "memory", "io"):
            pressure = healthy()["psi_some_avg10"]
            pressure[kind] = cfg[f"psi_{kind}_pct"]
            cases.append(({"psi_some_avg10": pressure}, f"{kind}_pressure"))
        for update, reason in cases:
            with self.subTest(reason=reason):
                self.assertEqual(guard._decision(cfg, {**healthy(), **update}, True), reason)
        self.assertIsNone(guard._decision(cfg, {**healthy(), "load1": 1.8, "temp_c": 69.9}, True))

    def test_planning_may_see_a_controller_but_work_requires_the_actual_cap(self):
        cfg = guard._config({"require_io_cap": True, "disk_path": "/home"})
        h = healthy()
        self.assertEqual(guard._decision(cfg, h, False), "io_cap_unavailable")
        h["user_controllers"].append("io")
        self.assertIsNone(guard._decision(cfg, h, False))
        self.assertEqual(guard._decision(cfg, h, True), "io_cap_unavailable")
        h["limits"]["io_write_bps"] = cfg["io_write_bps"]
        for key in ("cpu_quota_pct", "memory_max", "memory_high", "swap_max", "tasks_max"):
            with self.subTest(key=key):
                broken = {**h, "limits": {**h["limits"], key: None}}
                self.assertEqual(guard._decision(cfg, broken, True), key + "_unbounded")
        self.assertIsNone(guard._decision(cfg, h, True))

    def test_invalid_inputs_and_sandbox_argv(self):
        for policy in ({"service_urls": ["http://9.9.9.9/check"]}, {"psi_cpu_pct": float("nan")},
                       {"job_memory_mib": -1}, {"unknown_limit": 12}, {"service_samples": 0}):
            with self.subTest(policy=policy), self.assertRaises(ValueError):
                guard.limited_command(["true"], policy)
        cmd = guard.limited_command(["python3", "-"], {"require_io_cap": True, "disk_path": "/srv"})
        self.assertIn("--property=CPUQuota=100%", cmd)
        self.assertIn("--property=MemoryMax=536870912", cmd)
        self.assertIn("--property=IOWriteBandwidthMax=/srv 8388608", cmd)
        self.assertEqual(cmd[-3:], ["--", "python3", "-"])

    def test_service_503_and_expired_probe_are_refusals(self):
        class Busy(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(503)
                self.end_headers()

            def log_message(self, *args):
                pass

        cfg = guard._config({})
        with ThreadingHTTPServer(("127.0.0.1", 0), Busy) as server:
            worker = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .02})
            worker.start()
            url = f"http://127.0.0.1:{server.server_port}/health"
            try:
                with self.assertRaises(guard.AdmissionDeferred) as err:
                    guard._service_p95(url, cfg, time.monotonic())
                self.assertEqual(err.exception.reason, "service_unhealthy")
                with self.assertRaises(guard.AdmissionDeferred) as err:
                    guard._service_p95(url, cfg, time.monotonic() - 10)
                self.assertEqual(err.exception.reason, "stale_sample")
            finally:
                server.shutdown()
                worker.join(3)

    def test_fail_closed_telemetry_and_unmodified_application_errors(self):
        with patch.object(guard, "_slot", side_effect=lambda root: contextlib.nullcontext(0)), \
                patch.object(guard, "_receiver_policy", return_value=guard._config({})):
            with patch.object(guard, "_snapshot", side_effect=FileNotFoundError("pressure/io")):
                result = guard.assess({})
                self.assertFalse(result["accepted"])
                self.assertEqual(result["reason"], "telemetry_unavailable")
            with patch.object(guard, "_snapshot", return_value=healthy()):
                with self.assertRaisesRegex(OSError, "write failed"):
                    with guard.reserve(Path("."), {}):
                        raise OSError("write failed")

    @unittest.skipUnless(sys.platform.startswith("linux"), "requires a Linux receiver")
    def test_old_site_policy_cannot_relax_node_hardware_limits(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "policy.json").write_text(json.dumps({
                "ram_reserve_mib": 32, "disk_reserve_mib": 2048, "max_job_memory_mib": 4096,
                "max_load1": 4, "max_temp_c": 90,
            }))
            (root / "policy.json").chmod(0o600)
            policy = guard.launch_policy(root, {"job_memory_mib": 1536})
            self.assertEqual(policy["job_memory_mib"], 1536)
            self.assertEqual(policy["ram_reserve_mib"], 2560)
            self.assertEqual(policy["disk_reserve_mib"], 14306)
            self.assertEqual(policy["max_load1"], 1.8)
            self.assertEqual(policy["max_temp_c"], 70)
            with self.assertRaises(guard.AdmissionDeferred) as refusal:
                guard.launch_policy(root, {"job_memory_mib": 1537})
            self.assertEqual(refusal.exception.reason, "job_budget_exceeds_receiver_policy")
            self.assertEqual(refusal.exception.details["maximum"], 1536)

    @unittest.skipUnless(sys.platform.startswith("linux"), "requires a Linux receiver")
    def test_receiver_policy_cannot_be_weakened_by_a_request(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "policy.json").write_text(json.dumps({
                "ram_reserve_mib": 3072, "require_io_cap": True, "max_job_memory_mib": 768,
                "service_urls": ["http://127.0.0.1:9711/health"],
            }))
            (root / "policy.json").chmod(0o600)
            with guard._slot(root) as directory:
                cfg = guard._receiver_policy(directory, {"ram_reserve_mib": 32, "require_io_cap": False,
                                                         "service_urls": ["http://127.0.0.1:9780/extra"]})
                self.assertEqual(cfg["ram_reserve_mib"], 3072)
                self.assertTrue(cfg["require_io_cap"])
                self.assertIn("http://127.0.0.1:9711/health", cfg["service_urls"])
                with self.assertRaises(guard.AdmissionDeferred) as err:
                    guard._receiver_policy(directory, {"job_memory_mib": 769})
                self.assertEqual(err.exception.reason, "job_budget_exceeds_receiver_policy")

    @unittest.skipUnless(sys.platform.startswith("linux"), "requires a Linux receiver")
    def test_concurrent_guest_blocks_until_kernel_releases_dead_holder(self):
        import select

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            read_end, write_end = os.pipe()
            child = os.fork()
            if child == 0:
                try:
                    os.close(read_end)
                    with guard._slot(root):
                        os.write(write_end, b"1")
                        signal.pause()
                finally:
                    os._exit(0)
            os.close(write_end)
            try:
                self.assertTrue(select.select([read_end], [], [], 4)[0], "holder never acquired the slot")
                self.assertEqual(os.read(read_end, 1), b"1")
                with self.assertRaises(guard.AdmissionDeferred) as err:
                    with guard._slot(root):
                        self.fail("unlimited simultaneous guest jobs")
                self.assertEqual(err.exception.reason, "guest_slot_busy")
            finally:
                os.close(read_end)
                os.kill(child, signal.SIGKILL)
                os.waitpid(child, 0)
            with guard._slot(root):
                self.assertTrue((root / "guest.lock").is_file())
