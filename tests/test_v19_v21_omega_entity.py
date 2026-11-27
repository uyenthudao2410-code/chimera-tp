"""End-to-end verification suite for CHIMERA-OMEGA ENTITY v19.0-v21.0 (all 25 breakthroughs across 3 new cartridges)."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock, patch

from chimera_tp import __version__
from chimera_tp.autopilot import OpsConfig
from chimera_tp.dashboard import ChimeraDaemon
from chimera_tp.platform import (
    handle_mcp_request,
    render_smi,
)


class TestV19ToV21OmegaEntity(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.ops_dir = Path(self._tmp.name) / "ops"
        cfg = OpsConfig(
            node_name="v21-omega-test",
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
        try:
            with opener.open(req, timeout=20.0) as r:
                return r.status, json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

    def test_01_v19_hyperdesk_all_7_breakthroughs_and_vram_swap(self) -> None:
        caps = self._get("/.well-known/chimera.json")
        self.assertEqual(caps["version"], __version__)
        self.assertEqual(caps["capability_version"], "21.0.0")
        for c in ("hyper_desk", "cosmos_entity", "omega_entity"):
            self.assertEqual(caps["cartridges"][c]["status"], "active")

        diag = self._get("/v1/hyperdesk/diagnose")
        self.assertTrue(diag["ok"])
        self.assertGreater(diag["total_procs"], 1)
        self.assertIn("urban_hex", diag["silicon_wall_masks"])

        # Dry-run coordinated HyperDesk optimization (safe across all 7 features)
        st, opt = self._post("/v1/hyperdesk/optimize", {"dry_run": True})
        self.assertEqual(st, 200)
        self.assertTrue(opt["ok"])
        for k in ("zombie_reaper", "silicon_wall", "sync_dam", "cryo", "hydra"):
            self.assertIn(k, opt)
            self.assertTrue(opt[k]["ok"])

        # Real GTX 1650 VRAM Compressed Swap benchmark (or lossless host LZ4 on CPU-only Linux)
        st_v, vres = self._post("/v1/hyperdesk/vram/bench", {"payload_mb": 2.0})
        self.assertEqual(st_v, 200)
        self.assertTrue(vres["ok"])
        self.assertTrue(vres["sha256_exact"])
        self.assertEqual(vres["vram_retained_mb"], 0.0)
        self.assertGreater(vres["compression_ratio"], 2.0)

        # Unified Cortex incremental file watcher
        wdir = Path(self._tmp.name) / "watch_proj"
        wdir.mkdir()
        (wdir / "a.py").write_text("x = 1\n", encoding="utf-8")
        st_w1, w1 = self._post("/v1/hyperdesk/cortex/watch", {"dir": str(wdir)})
        self.assertEqual(st_w1, 200)
        self.assertTrue(w1["initial"])
        (wdir / "b.py").write_text("y = 2\n", encoding="utf-8")
        st_w2, w2 = self._post("/v1/hyperdesk/cortex/watch", {"dir": str(wdir)})
        self.assertEqual(st_w2, 200)
        self.assertEqual(w2["added"], ["b.py"])

    def test_02_v20_cosmos_entity_all_9_engines(self) -> None:
        # 1. Placement and local state checkpoint report their execution scope.
        st1, p1 = self._post("/v1/cosmos/ssi/place", {"task_id": "job_ssi_1", "work_kind": "python_fork", "data_locality": "peer"})
        self.assertEqual(st1, 200)
        self.assertTrue(p1["ok"])
        self.assertEqual(p1["mode"], "placement_plan")
        st2, p2 = self._post("/v1/cosmos/ssi/place", {"task_id": "job_ssi_1", "levitate_to": "svhome"})
        self.assertEqual(st2, 200)
        self.assertEqual(p2["action"], "levitated")
        self.assertEqual(p2["mode"], "local_metadata_only")
        self.assertGreater(p2["checkpoint_lz4_bytes"], 0)
        self.assertFalse(p2["remote_acknowledged"])
        self.assertFalse(p2["socket_preserved"])

        # 2. Zero-Env CAS + 0-byte hardlink materialization
        z_out = Path(self._tmp.name) / "zero_env_ws"
        self.daemon.platform.cosmos.zero_env.register_env("py_env", {"mod.py": b"A" * 4096, "dup.py": b"A" * 4096})
        mat = self.daemon.platform.cosmos.zero_env.materialize("py_env", z_out)
        self.assertTrue(mat["ok"])
        self.assertEqual(mat["hardlinked"], 2)
        self.assertGreater(self.daemon.platform.cosmos.zero_env.stats()["dedup_saved_pct"], 40.0)

        # 3. Omni-Memory: 1 log -> KV + SQL + VSA Search + Time-Travel AS-OF + GF(256) Self-Heal
        _, put1 = self._post("/v1/cosmos/omni/put", {"key": "cfg/core", "value": {"ver": 1, "note": "alpha quantum"}, "namespace": "ns1"})
        _, put2 = self._post("/v1/cosmos/omni/put", {"key": "cfg/core", "value": {"ver": 2, "note": "beta omega"}, "namespace": "ns1"})
        latest = self._get("/v1/cosmos/omni/get?key=cfg/core&namespace=ns1")
        asof1 = self._get(f"/v1/cosmos/omni/get?key=cfg/core&namespace=ns1&as_of_seq={put1['seq']}")
        self.assertEqual(latest["value"]["ver"], 2)
        self.assertEqual(asof1["value"]["ver"], 1)
        st_sql, sql_res = self._post("/v1/cosmos/omni/sql", {"sql": "SELECT key, seq FROM omni_latest WHERE namespace='ns1'"})
        self.assertEqual(st_sql, 200)
        self.assertEqual(sql_res["count"], 1)
        srch = self._get("/v1/cosmos/omni/search?q=omega&namespace=ns1")
        self.assertGreaterEqual(len(srch["hits"]), 1)
        st_h, hres = self._post("/v1/cosmos/omni/heal", {"seq": put1["seq"]})
        self.assertEqual(st_h, 200)
        self.assertTrue(hres["sha256_exact"])

        # 4. Immortal-Net capability URI resolution
        st_u, ures = self._post("/v1/cosmos/net/resolve", {"uri": "gpu://gtx1650"})
        self.assertEqual(st_u, 200)
        self.assertIn("ML-KEM", ures["pq_suite"])

        # 5. Immune-OS Ghost-Token secret proxy & Anti-Ransomware <5ms kill-switch
        _, gt = self._post("/v1/cosmos/immune/ghost-issue", {"secret_name": "OPENAI_KEY", "real_value": "sk-real-987654", "allowed_domains": ["api.openai.com"]})
        _, ok_r = self._post("/v1/cosmos/immune/ghost-resolve", {"ghost_token": gt["ghost_token"], "target_domain": "api.openai.com"})
        _, bad_r = self._post("/v1/cosmos/immune/ghost-resolve", {"ghost_token": gt["ghost_token"], "target_domain": "evil.exfil.invalid"})
        self.assertTrue(ok_r["allowed"])
        self.assertEqual(ok_r["value"], "sk-real-987654")
        self.assertFalse(bad_r["allowed"])

        # 6. Autogen-Ops SRE dry-prove cycle
        st_sre, sre = self._post("/v1/cosmos/autogen/sre", {"execute": False})
        self.assertEqual(st_sre, 200)
        self.assertTrue(sre["ghost_proof"]["proved"])

        # 7. Swarm-Hypervisor AI CoW fork + Burn-Loop circuit breaker
        sw_src = Path(self._tmp.name) / "swarm_repo"
        sw_src.mkdir()
        (sw_src / "app.py").write_text("print('ok')\n", encoding="utf-8")
        st_sp, sp = self._post("/v1/cosmos/swarm/spawn", {"agent_id": "agent_a", "target_dir": str(sw_src), "max_cost_usd": 0.1})
        self.assertEqual(st_sp, 200)
        for _ in range(3):
            _, bl = self._post("/v1/cosmos/swarm/burn-check", {"agent_id": "agent_a", "error_trace": "SyntaxError line 42"})
        self.assertTrue(bl["circuit_broken"])

        # 8. Thermodynamic Zero-Wear SSD Write Barrier
        for i in range(10):
            self.daemon.platform.cosmos.thermo.buffered_write(f"k{i % 2}", f"v{i}".encode())
        st_f, fl = self._post("/v1/cosmos/thermo/flush", {})
        self.assertEqual(st_f, 200)
        self.assertGreaterEqual(fl["ssd_write_reduction_pct"], 80.0)

        # 9. Genesis Seed (<10KB, DLP clean) & Bare-Metal Assimilation
        seed = self._get("/v1/cosmos/genesis/seed")
        self.assertTrue(seed["ok"])
        self.assertTrue(seed["dlp_clean"])
        self.assertTrue(seed["under_10kb"])
        assim = self._get("/v1/cosmos/genesis/assimilate")
        self.assertTrue(assim["ok"])
        self.assertGreater(assim["cpu_threads"], 0)

    def test_03_v21_omega_entity_all_9_engines_multiverse_and_mcp(self) -> None:
        # Full 25-capability self-benchmark
        st_b, bench = self._post("/v1/omega/benchmark", {})
        self.assertEqual(st_b, 200)
        self.assertTrue(bench["ok"], msg=json.dumps(bench, indent=2))
        self.assertEqual(bench["passed"], bench["total"])

        # Multiverse OS: race 2 realities (one failing, one passing) -> atomic collapse -> Global Ctrl+Z rewind!
        mv_dir = Path(self._tmp.name) / "mv_proj"
        mv_dir.mkdir()
        (mv_dir / "state.txt").write_text("PRIME_V0", encoding="utf-8")
        st_m, mv = self._post(
            "/v1/omega/multiverse/race",
            {
                "target_dir": str(mv_dir),
                "candidates": [
                    {"name": "broken_patch", "cmd": [sys.executable, "-c", "import sys; open('state.txt','w').write('BAD'); sys.exit(1)"]},
                    {"name": "winner_patch", "cmd": [sys.executable, "-c", "open('state.txt','w').write('PRIME_V1')"]},
                ],
                "collapse_winner": True,
            },
        )
        self.assertEqual(st_m, 200)
        self.assertTrue(mv["collapsed_to_prime_reality"])
        self.assertEqual(mv["winner"]["name"], "winner_patch")
        self.assertEqual((mv_dir / "state.txt").read_text(encoding="utf-8"), "PRIME_V1")

        # Global Ctrl+Z restores PRIME_V0 bit-exactly!
        st_z, cz = self._post("/v1/omega/multiverse/ctrl-z", {"snap_id": mv["ctrl_z_snap_id"]})
        self.assertEqual(st_z, 200)
        self.assertTrue(cz["ok"])
        self.assertEqual((mv_dir / "state.txt").read_text(encoding="utf-8"), "PRIME_V0")

        # SMI renders all 15 cartridges cleanly
        smi = self._get("/v1/smi")
        txt = render_smi(smi)
        self.assertIn("hyper_desk", txt)
        self.assertIn("cosmos_entity", txt)
        self.assertIn("omega_entity", txt)

        # Hot cartridge toggle disables omega_entity -> 503
        self._post("/v1/cartridges", {"name": "omega_entity", "enabled": False})
        st_off, _ = self._post("/v1/omega/autopoietic/evolve", {})
        self.assertEqual(st_off, 503)
        self._post("/v1/cartridges", {"name": "omega_entity", "enabled": True})

        # MCP tools include new v19-v21 tools
        tools_resp = handle_mcp_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, anchor_url=self.anchor)
        names = {t["name"] for t in tools_resp["result"]["tools"]}
        self.assertIn("chimera_hyperdesk_optimize", names)
        self.assertIn("chimera_omega_intent", names)
        self.assertIn("chimera_omega_benchmark", names)

    def test_ctrl_z_restores_only_winner_delta_and_preserves_later_edits(self) -> None:
        self.assertEqual(self._get("/v1/omega/status")["ctrl_z_scope"], "committed_patch_files")
        work = self.ops_dir / "undo-case"
        work.mkdir()
        original = b"A" * (600 * 1024)
        (work / "block.bin").write_bytes(original)
        (work / "untouched.bin").write_bytes(original)
        (work / "removed.txt").write_text("restore me", encoding="utf-8")
        invalid, _ = self._post("/v1/omega/multiverse/race", {
            "target_dir": str(work), "candidates": [{"name": "missing command"}],
        })
        self.assertEqual(invalid, 400)
        code = (
            "from pathlib import Path\n"
            "Path('block.bin').write_bytes(b'B' * (600 * 1024))\n"
            "Path('removed.txt').unlink()\n"
            "Path('generated.txt').write_text('output')\n"
            "Path('new-dir/subdir').mkdir(parents=True)\n"
            "Path('new-dir/subdir/nested').write_text('output')"
        )
        status, race = self._post("/v1/omega/multiverse/race", {
            "target_dir": str(work),
            "candidates": [{"name": "patch", "cmd": [sys.executable, "-c", code]}],
            "collapse_winner": True,
        })
        self.assertEqual(status, 200)
        self.assertTrue(race["collapsed_to_prime_reality"])
        self.assertFalse((work / "removed.txt").exists())
        request = {"snap_id": race["ctrl_z_snap_id"]}
        (work / "later.txt").write_text("unrelated", encoding="utf-8")
        (work / "generated.txt").write_text("user edit", encoding="utf-8")
        _, conflict = self._post("/v1/omega/multiverse/ctrl-z", request)
        self.assertFalse(conflict["ok"])
        self.assertEqual(conflict["conflicts"], ["generated.txt"])
        self.assertEqual((work / "generated.txt").read_text(), "user edit")
        self.assertEqual((work / "block.bin").read_bytes(), b"B" * len(original))

        (work / "generated.txt").write_text("output", encoding="utf-8")
        _, undo = self._post("/v1/omega/multiverse/ctrl-z", request)
        self.assertTrue(undo["ok"])
        self.assertEqual((work / "block.bin").read_bytes(), original)
        self.assertEqual((work / "untouched.bin").read_bytes(), original)
        self.assertEqual((work / "later.txt").read_text(), "unrelated")
        self.assertEqual((work / "removed.txt").read_text(), "restore me")
        self.assertFalse((work / "generated.txt").exists())
        self.assertFalse((work / "new-dir").exists())

    def test_intent_plan_distinguishes_observations_from_requested_bounds(self) -> None:
        route = "/v1/omega/intent/compile"
        request = {"service": "audit", "invariants": {"p99_ms": 1, "host_ram_mb": 80}}
        for sample, status in ((None, "unverified"), (32, "unverified"), (120, "violated")):
            with self.subTest(sample=sample), patch.object(
                self.daemon.platform, "capabilities", return_value={"zero_weight": {"daemon_ram_mb": sample}}
            ):
                code, plan = self._post(route, request)
                self.assertEqual(code, 200)
                self.assertEqual(plan["mode"], "topology_plan")
                self.assertEqual(plan["verification_status"], status)
                self.assertEqual(plan["observations"]["daemon_rss_mb"], sample)
                self.assertEqual(plan["ok"], status != "violated")
                evidence = plan["invariants_satisfied"]
                for key in ("p99_latency_ok", "zero_cost_ok", "zero_data_loss_gf256_ok", "zero_secret_egress_dlp_ok"):
                    self.assertIsNone(evidence[key])
                self.assertIs(evidence["host_ram_budget_ok"], False if status == "violated" else None)
        self.assertEqual(self._post(route, {"invariants": {"p99_ms": -1}})[0], 400)

    @patch("chimera_tp.platform.hyper_desk._win_foreground_pid", new=lambda: 0)
    @patch("chimera_tp.platform.hyper_desk._snapshot_processes", new=lambda: [])
    def test_04_autonomic_self_living_reflex_brain(self) -> None:
        # Verify autonomic status, dry-run tick, policy persistence, and safe on/off lifecycle
        st0 = self._get("/v1/hyperdesk/autonomic")
        self.assertTrue(st0["ok"])
        self.assertIn("recent_focus_guard_s", st0["policy"])
        self.assertIn("pid_trim_cooldown_s", st0["policy"])

        # Force dry-run autonomic tick
        code, tick = self._post("/v1/hyperdesk/autonomic", {"action": "tick", "force_patrol": True, "force_orphan": True, "dry_run": True})
        self.assertEqual(code, 200)
        self.assertTrue(tick["ok"])
        self.assertGreaterEqual(tick["tick"], 1)

        # Update policy & verify persistence on disk
        code_p, pol_res = self._post("/v1/hyperdesk/autonomic", {"policy": {"fast_tick_s": 2.0, "idle_release_s": 30.0, "enabled": True}})
        self.assertEqual(code_p, 200)
        self.assertTrue(pol_res["running"])
        self.assertEqual(pol_res["policy"]["fast_tick_s"], 2.0)
        self.assertTrue((self.ops_dir / "autonomic_policy.json").is_file())

        # Turn off cleanly and restore defaults
        code_off, off_res = self._post("/v1/hyperdesk/autonomic", {"action": "off", "restore_defaults": True})
        self.assertEqual(code_off, 200)
        self.assertFalse(off_res["running"])

    def test_05_v22_zero_stutter_hard_cage_family_sanctuary_and_no_thrash(self) -> None:
        hd = self.daemon.platform.hyper_desk
        # Verify the advertised v22 threshold.
        self.assertLessEqual(float(hd._autonomic_policy["ram_pressure_free_gb"]), 5.0)
        self.assertIn("hard_cage_cap_pct", hd._autonomic_policy)
        # Verify process-tree family expansion groups parent + child renderers + GPU helper together
        fake_procs = [
            {"pid": 100, "ppid": 4, "name": "explorer"},
            {"pid": 200, "ppid": 100, "name": "chrome"},
            {"pid": 201, "ppid": 200, "name": "chrome"},
            {"pid": 202, "ppid": 200, "name": "chrome"},
            {"pid": 300, "ppid": 100, "name": "language_server"},
        ]
        app_nm, fam = hd._expand_app_family(fake_procs, 201)
        self.assertEqual(app_nm, "chrome")
        self.assertEqual(fam, {200, 201, 202})
        self.assertNotIn(300, fam)
        # Verify Win32 Hard CPU Cage initializes cleanly on Windows (or safe no-op on Linux)
        cage_st = hd._hard_cage.status()
        if os.name == "nt":
            self.assertTrue(cage_st["active"])
            self.assertTrue(hd._hard_cage.set_cap_pct(25))
            self.assertEqual(hd._hard_cage.status()["hard_cap_pct"], 25)
            self.assertTrue(hd._hard_cage.set_cap_pct(35))

    def test_06_background_trim_requires_measured_ram_pressure(self) -> None:
        from chimera_tp.platform import hyper_desk

        hd = self.daemon.platform.hyper_desk
        hd._autonomic_policy["interactive_profile"] = "legacy"
        procs = [
            {"pid": 901001, "ppid": 0, "name": "chrome", "ws_mb": 7500.0, "priv_mb": 7800.0},
            {"pid": 901002, "ppid": 0, "name": "onedrive", "ws_mb": 100.0, "priv_mb": 120.0},
        ]
        with ExitStack() as stack:
            governor = stack.enter_context(patch.object(hd, "host_governor", Mock()))
            stack.enter_context(patch.object(hyper_desk, "_snapshot_processes", return_value=procs))
            stack.enter_context(patch.object(hyper_desk.urllib.request, "urlopen", side_effect=OSError))
            stack.enter_context(patch.object(hd, "_protected_pid_set", return_value=set()))
            stack.enter_context(patch.object(hd, "_self_preserve_daemon_ram", return_value=None))
            stack.enter_context(patch.object(hd, "reap_orphans", return_value={}))
            stack.enter_context(patch.object(hyper_desk, "_win_proc_cpu_io", return_value=(0.0, 0)))
            stack.enter_context(patch.object(hyper_desk, "_win_foreground_pid", return_value=0))
            stack.enter_context(patch.object(hyper_desk, "_win_proc_memory_mb", return_value=(100.0, 120.0)))
            for name in ("_win_set_eco_qos", "_win_set_memory_priority", "_win_set_affinity", "_win_set_priority"):
                stack.enter_context(patch.object(hyper_desk, name))
            trim = stack.enter_context(patch.object(hyper_desk, "_win_trim_working_set", return_value=True))
            for metrics, expected in (
                ({"free_ram_gb": 9.0}, False),
                ({"free_ram_gb": 4.5}, False),
                ({"free_ram_gb": 4.49}, True),
                ({"free_ram_gb": 0.0}, True),
                ({"free_ram_gb": 1.0, "ram_measured": False}, False),
                ({}, False),
            ):
                with self.subTest(metrics=metrics):
                    governor.get_host_metrics.return_value = {**metrics, "idle_sec": 0.0}
                    tick = hd.autonomic_tick_once(dry_run=True, force_patrol=True)
                    decisions = [entry["kind"] for entry in tick["actions"]]
                    self.assertEqual("EMERGENCY_CRYO_TRIM" in decisions, expected and os.name == "nt")
                    for operation in (hd.apply_cryo, hd.collapse_hydra, hd.apply_sync_dam):
                        trim.reset_mock()
                        operation()
                        self.assertEqual(trim.called, expected, operation.__name__)


    def test_aether_leaves_other_processes_and_power_policy_to_windows(self) -> None:
        from chimera_tp.platform import hyper_desk

        hd = self.daemon.platform.hyper_desk
        self.assertTrue(hd.aether_active)
        with patch.object(hyper_desk, "_snapshot_processes", side_effect=AssertionError), patch.object(
            hd, "_ensure_rust_engines", side_effect=AssertionError
        ), patch.object(hd.thermostat, "set_mode", side_effect=AssertionError):
            tick = hd.autonomic_tick_once(force_patrol=True, force_orphan=True)
            self.assertEqual(tick["actions"], [])
            self.assertEqual(hd.apply_cryo()["working_set_trimmed"], 0)
            self.assertEqual(hd.collapse_hydra()["trimmed_procs"], 0)
            self.assertEqual(hd.apply_sync_dam()["suspended"], 0)
            self.assertEqual(hd.apply_silicon_wall()["pinned_procs"], 0)
            self.assertEqual(hd.stasis_hibernate()["hibernated"], 0)
            self.assertEqual(hd.reap_orphans()["reaped_count"], 0)
            self.assertEqual(self._post("/v1/hyperdesk/thermostat", {"mode": "cool_99"})[0], 409)


if __name__ == "__main__":
    unittest.main()
