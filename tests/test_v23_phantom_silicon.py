"""End-to-end verification suite for v23.0 CHIMERA-PHANTOM-SILICON (all 6 infrastructure breakthroughs)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path

from chimera_tp.autopilot import OpsConfig
from chimera_tp.dashboard import ChimeraDaemon
from chimera_tp.native import (
    has_native_pwm,
    native_focus_hook_start,
    native_focus_hook_stop,
    native_pwm_set_targets,
    native_pwm_start,
    native_pwm_stats,
    native_pwm_stop,
)
from chimera_tp.platform import (
    GpuFenceManager,
    NvmeMirageEngine,
    StasisPodManager,
    handle_mcp_request,
    install_autoload,
)
from chimera_tp.platform.hyper_desk import _win_proc_cpu_io


class TestV23PhantomSilicon(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.ops_dir = self.root / "ops"
        cfg = OpsConfig(
            node_name="v23-phantom-test",
            role="controller",
            dashboard_bind="127.0.0.1:0",
            beam_port=0,
            rpc_v4_port=0,
            rpc_v6_port=-1,
            query_port=0,
            warp_port=-1,
            edge_proxy_port=-1,
            allowed_query_roots=[self._tmp.name],
            search_roots=[self._tmp.name],
            edge_targets={},
            phantom_enabled=False,
        )
        self.daemon = ChimeraDaemon(config=cfg, ops_dir=self.ops_dir, auto_seed_on_empty=False).start()
        self.anchor = self.daemon.platform.anchor_url

    def tearDown(self) -> None:
        self.daemon.close()
        self._tmp.cleanup()

    def _get(self, path: str) -> dict:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f"{self.anchor}{path}", timeout=15.0) as r:
            return json.loads(r.read().decode("utf-8"))

    def _post(self, path: str, body: dict) -> tuple[int, dict]:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        req = urllib.request.Request(
            f"{self.anchor}{path}",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with opener.open(req, timeout=20.0) as r:
            return r.status, json.loads(r.read().decode("utf-8"))

    def test_01_nvme_mirage_atomic_promote_sync_demote_roundtrip(self) -> None:
        src = self.root / "hdd_sim" / "demo_repo"
        (src / "sub").mkdir(parents=True)
        (src / "main.py").write_text("print('v1')\n", encoding="utf-8")
        (src / "sub" / "data.bin").write_bytes(b"CHIMERA_MIRAGE_DATA_" * 512)

        tier_root = self.root / "nvme_tier"
        mirage = NvmeMirageEngine(
            ops_dir=self.ops_dir,
            tier_root=tier_root,
            min_nvme_free_gb=0.0,
            allow_same_volume=True,
        )

        # Dry run first
        dry = mirage.promote(src, dry_run=True)
        self.assertTrue(dry["ok"])
        self.assertTrue(dry["dry_run"])
        self.assertEqual(dry["files"], 2)

        # Real atomic promote -> NTFS Junction (Win) / symlink (Linux)
        res = mirage.promote(src)
        self.assertTrue(res["ok"], msg=res)
        self.assertTrue(res["promoted"])
        self.assertEqual(res["verified_samples"], 2)

        # Verify transparent read + write through original path
        self.assertEqual((src / "main.py").read_text(encoding="utf-8"), "print('v1')\n")
        (src / "main.py").write_text("print('v2_nvme_edit')\n", encoding="utf-8")
        (src / "new_file.txt").write_text("created_on_nvme", encoding="utf-8")

        # Differential write-back sync to cold backing
        sync_res = mirage.sync_back(src)
        self.assertTrue(sync_res["ok"])
        cold_p = Path(res["cold_target"])
        self.assertEqual((cold_p / "main.py").read_text(encoding="utf-8"), "print('v2_nvme_edit')\n")
        self.assertEqual((cold_p / "new_file.txt").read_text(encoding="utf-8"), "created_on_nvme")

        # Benchmark works transparently through junction
        bm = mirage.benchmark_dir(src, max_files=20)
        self.assertTrue(bm["ok"])
        self.assertTrue(bm["is_mirage_junction"])
        self.assertEqual(bm["files_read"], 3)

        # Lossless demote restores regular directory with latest edits intact
        dem = mirage.demote(src)
        self.assertTrue(dem["ok"], msg=dem)
        self.assertTrue(src.is_dir())
        self.assertEqual((src / "main.py").read_text(encoding="utf-8"), "print('v2_nvme_edit')\n")
        self.assertEqual((src / "new_file.txt").read_text(encoding="utf-8"), "created_on_nvme")
        self.assertFalse(Path(res["nvme_target"]).exists())

    def test_02_rust_pwm_crusher_clamps_real_cpu_burner(self) -> None:
        if os.name != "nt" or not has_native_pwm():
            # Cross-platform Linux check: safe no-op returns cleanly
            st = native_pwm_stats()
            self.assertIn("duty_pct", st)
            return

        self.assertTrue(native_focus_hook_start())
        proc = subprocess.Popen([sys.executable, "-c", "x=0\nwhile True: x+=1"])
        try:
            time.sleep(0.25)
            c0, _ = _win_proc_cpu_io(proc.pid)
            time.sleep(0.5)
            c1, _ = _win_proc_cpu_io(proc.pid)
            raw_rate = (c1 - c0) / 0.5

            self.assertTrue(native_pwm_start(50, 25))
            self.assertEqual(native_pwm_set_targets([proc.pid], 25), 1)
            c2, _ = _win_proc_cpu_io(proc.pid)
            time.sleep(0.9)
            c3, _ = _win_proc_cpu_io(proc.pid)
            pwm_rate = (c3 - c2) / 0.9
            stats = native_pwm_stats()
            native_pwm_stop()
            native_focus_hook_stop()

            self.assertGreater(raw_rate, 0.65)
            self.assertLess(pwm_rate, 0.50)
            self.assertGreaterEqual(stats["cycles"], 5)
            self.assertGreaterEqual(stats["resumes"], stats["cycles"])
        finally:
            proc.terminate()
            proc.wait(timeout=3)

    def test_03_stasis_pod_owner_alive_and_gpu_phoenix(self) -> None:
        suspended: set[int] = set()
        trimmed: list[int] = []
        terminated: list[int] = []

        def fake_cmds(pids: list[int]) -> dict[int, str]:
            return {
                1001: "ChatGPT.exe",
                1002: "ChatGPT.exe --type=renderer",
                1003: "ChatGPT.exe --type=gpu-process",
                2001: "T3 Code (Beta).exe --type=renderer",
                3001: "chrome.exe --type=gpu-process",
            }

        def fake_susp(pid: int, susp: bool) -> bool:
            if susp:
                suspended.add(pid)
            else:
                suspended.discard(pid)
            return True

        def fake_trim(pid: int) -> bool:
            trimmed.append(pid)
            return True

        def fake_mem(pid: int) -> tuple[float, float]:
            return (12.0, 200.0) if pid in trimmed else (250.0, 400.0)

        def fake_term(pid: int) -> bool:
            terminated.append(pid)
            return True

        stasis = StasisPodManager(
            cmdlines_fn=fake_cmds,
            suspend_fn=fake_susp,
            trim_fn=fake_trim,
            mem_fn=fake_mem,
            terminate_fn=fake_term,
        )
        procs = [
            {"pid": 1001, "ppid": 4, "name": "chatgpt", "ws_mb": 90.0, "priv_mb": 150.0},
            {"pid": 1002, "ppid": 1001, "name": "chatgpt", "ws_mb": 380.0, "priv_mb": 430.0},
            {"pid": 1003, "ppid": 1001, "name": "chatgpt", "ws_mb": 120.0, "priv_mb": 220.0},
            {"pid": 2001, "ppid": 4, "name": "t3 code (beta)", "ws_mb": 450.0, "priv_mb": 700.0},
            {"pid": 3001, "ppid": 4, "name": "chrome", "ws_mb": 600.0, "priv_mb": 2850.0},
        ]

        # Owner (1001), GPU (1003), and T3 Code (2001) MUST NOT be suspended; ONLY cold renderer 1002!
        hib = stasis.hibernate_cold_renderers(procs, sanctuary_pids=set(), recent_families=set())
        self.assertTrue(hib["ok"])
        self.assertEqual(hib["hibernated"], 1)
        self.assertEqual(suspended, {1002})
        self.assertEqual(trimmed, [1002])

        # Wake family immediately resumes 1002
        wk = stasis.wake_family(app_name="chatgpt")
        self.assertEqual(suspended, set())
        self.assertGreaterEqual(wk["woken"], 1)

        # GPU-Phoenix detects Chrome 2850 MB bloated GPU process; dry audit does not kill; recycle does!
        audit = stasis.gpu_phoenix_audit_and_recycle(procs, threshold_commit_mb=1600.0, allow_recycle=False)
        self.assertEqual(len(audit["recycled"]), 0)
        self.assertEqual(sum(1 for g in audit["gpu_processes"] if g["bloated"]), 1)

        rec = stasis.gpu_phoenix_audit_and_recycle(procs, threshold_commit_mb=1600.0, allow_recycle=True)
        self.assertEqual(terminated, [3001])
        self.assertEqual(rec["recycled_commit_mb"], 2850.0)

    def test_04_zygote_interceptor_and_v23_http_mcp_routes(self) -> None:
        # Install autoload into isolated temp dir and verify Elastic Pool Shaper hook is present
        site_tmp = self.root / "site_tmp"
        res = install_autoload(target_dir=site_tmp)
        self.assertTrue(res["ok"])
        hook_txt = Path(res["hook_py"]).read_text(encoding="utf-8")
        self.assertIn("_install_win_elastic_pool_shaper", hook_txt)
        self.assertIn("CHIMERA_ELASTIC_POOL", hook_txt)

        # Verify all v23 HTTP endpoints
        self.assertTrue(self._get("/v1/hyperdesk/mirage/status")["ok"])
        self.assertTrue(self._get("/v1/hyperdesk/stasis/status")["ok"])
        self.assertTrue(self._get("/v1/hyperdesk/pwm/status")["ok"])
        self.assertTrue(self._get("/v1/hyperdesk/gpu-fence")["ok"])
        self.assertTrue(self._get("/v1/exile/status")["ok"])

        st_gf, gf = self._post("/v1/hyperdesk/gpu-fence", {"dry_run": True})
        self.assertEqual(st_gf, 200)
        self.assertTrue(gf["ok"])

        # Verify v23 MCP tools are advertised
        tools_resp = handle_mcp_request({"jsonrpc": "2.0", "id": 23, "method": "tools/list"}, anchor_url=self.anchor)
        names = {t["name"] for t in tools_resp["result"]["tools"]}
        self.assertIn("chimera_nvme_mirage", names)
        self.assertIn("chimera_agent_exile", names)

    def test_05_zero_powershell_native_cmdline_and_gpu_discovery(self) -> None:
        from unittest.mock import patch
        from chimera_tp.platform.hyper_desk import _win_get_cmdlines_for_pids

        # Must read current process cmdline & GPU paths via native Win32/procfs with ZERO subprocess/PowerShell spawns!
        with patch("subprocess.check_output", side_effect=AssertionError("Must never spawn PowerShell!")):
            cmds = _win_get_cmdlines_for_pids([os.getpid()])
            self.assertIn(os.getpid(), cmds)
            self.assertTrue(len(cmds[os.getpid()]) > 0)
            gf = GpuFenceManager(ops_dir=self.ops_dir)
            disc = gf._discover_exe_paths()
            self.assertIn("high_perf", disc)
            self.assertIn("low_power", disc)
            self.assertIn("chrome.exe", GpuFenceManager.HIGH_PERF_PROCS)

    def test_06_v24_silicon_thermostat_and_fast_pulse_cache(self) -> None:
        from chimera_tp.host_governor import HostYieldGovernor
        from chimera_tp.platform.phantom_silicon import SiliconThermostat

        # 1. SiliconThermostat decision curve (dry mock without touching host power plan in unit test)
        applied: list[int] = []
        th = SiliconThermostat(mode="cool_99")
        th._apply_procthrottlemax = lambda pct: (applied.append(pct) or setattr(th, "_current_cap_pct", pct) or True)  # type: ignore[method-assign]
        r_idle = th.evaluate(cpu_pct=15.0, gpu_temp_c=48.0, cad_godmode=False)
        self.assertEqual(r_idle["target_cap_pct"], 99)
        self.assertEqual(r_idle["state"], "CRYO_ECO_99")

        r_warm = th.evaluate(cpu_pct=70.0, gpu_temp_c=60.0, cad_godmode=False)
        self.assertEqual(r_warm["target_cap_pct"], 95)
        self.assertEqual(r_warm["state"], "SILICON_SHIELD_95")
        self.assertTrue(r_warm["shield_active"])
        self.assertEqual(r_warm["shield_pwm_duty"], 20)

        r_hot = th.evaluate(cpu_pct=84.0, gpu_temp_c=65.0, cad_godmode=False)
        self.assertEqual(r_hot["target_cap_pct"], 85)
        self.assertEqual(r_hot["state"], "THERMAL_SHIELD_85")
        self.assertTrue(r_hot["shield_active"])
        self.assertEqual(r_hot["shield_pwm_duty"], 15)

        r_cad = th.evaluate(cpu_pct=30.0, gpu_temp_c=52.0, cad_godmode=True)
        self.assertEqual(r_cad["target_cap_pct"], 100)
        self.assertEqual(r_cad["state"], "CAD_BURST_100")
        self.assertEqual(applied, [99, 95, 85, 100])

        # 2. HTTP /v1/hyperdesk/thermostat GET + POST validation
        st0 = self._get("/v1/hyperdesk/thermostat")
        self.assertTrue(st0["ok"])
        self.assertIn("mode", st0)

        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._post("/v1/hyperdesk/thermostat", {"mode": "invalid_mode"})
        self.assertIn(ctx.exception.code, (400, 409))

        # 3. HostYieldGovernor rapid sub-50ms reads must NOT report false 100% spike
        gov = HostYieldGovernor()
        _ = gov.get_host_metrics()
        s2 = gov.get_host_metrics()
        self.assertLess(float(s2["cpu_pct"]), 99.9)

        # 4. Cached pulse_summary() must respond in < 15 ms on warm hit
        _ = self.daemon.platform.pulse_summary()
        t0 = time.perf_counter()
        ps = self.daemon.platform.pulse_summary()
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        self.assertLess(elapsed_ms, 15.0)
        self.assertIn("thermostat_state", ps["hyper_desk"])
        self.assertIn("cpu_cap_pct", ps["hyper_desk"])


if __name__ == "__main__":
    unittest.main()
