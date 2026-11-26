"""Comprehensive verification suite for CHIMERA-TP v17.0 Stage 3 Silicon Cartridges."""

from __future__ import annotations

import http.server
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from chimera_tp.autopilot import OpsConfig
from chimera_tp.dashboard import ChimeraDaemon
from chimera_tp.platform import connect, handle_mcp_request


def _start_mini_server(payload: dict, status: int = 200) -> tuple[http.server.ThreadingHTTPServer, str]:
    raw = json.dumps(payload).encode("utf-8")

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *_args: object) -> None:
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{port}"


class TestV17SiliconCartridges(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.ops_dir = Path(self._tmp.name) / "ops"
        cfg = OpsConfig(
            node_name="v17-test",
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

    def test_01_vgpu_pareto_router_auto_yield_and_openai_embeddings(self) -> None:
        # 1. Thermal/Utilization Auto-Yield guard (<50ms preempt)
        vgpu = self.daemon.platform.vgpu
        hot = vgpu.evaluate_gpu_eligibility(
            gpu={"present": True, "name": "GTX 1650", "temp_c": 78.0, "util_pct": 12.0, "vram_free_mb": 2000}
        )
        self.assertFalse(hot["gpu_ready"])
        self.assertIn("thermal_guard", hot["reason"])
        self.assertLess(hot["check_ms"], 50.0)

        gaming = vgpu.evaluate_gpu_eligibility(
            gpu={"present": True, "name": "GTX 1650", "temp_c": 58.0, "util_pct": 88.0, "vram_free_mb": 2000}
        )
        self.assertFalse(gaming["gpu_ready"])
        self.assertIn("gpu_busy", gaming["reason"])

        cool = vgpu.evaluate_gpu_eligibility(
            gpu={"present": True, "name": "GTX 1650", "temp_c": 45.0, "util_pct": 2.0, "vram_free_mb": 1400}
        )
        self.assertTrue(cool["gpu_ready"])

        # 2. Pareto 3-way routing ($0 prefers local; frontier with budget picks cloud_api)
        st_zero, r_zero = self._post("/v1/vgpu/route", {"max_ms": 500, "max_cost_usd": 0.0, "min_tier": "standard"})
        self.assertEqual(st_zero, 200)
        self.assertEqual(r_zero["selected"]["est_cost_usd"], 0.0)

        st_fr, r_fr = self._post("/v1/vgpu/route", {"max_ms": 1000, "max_cost_usd": 0.05, "min_tier": "frontier"})
        self.assertEqual(st_fr, 200)
        self.assertEqual(r_fr["selected"]["engine"], "cloud_api")

        # 3. OpenAI-compatible embeddings + micro-batch cache hit
        st_e1, e1 = self._post(
            "/v1/openai/v1/embeddings",
            {"input": ["chimera vgpu embedding", "radar bounty stream"], "dimensions": 128},
        )
        self.assertEqual(st_e1, 200)
        self.assertEqual(len(e1["data"]), 2)
        self.assertEqual(len(e1["data"][0]["embedding"]), 128)
        self.assertEqual(e1["cache_hits"], 0)

        st_e2, e2 = self._post(
            "/v1/openai/v1/embeddings",
            {"input": ["chimera vgpu embedding", "radar bounty stream"], "dimensions": 128},
        )
        self.assertEqual(st_e2, 200)
        self.assertEqual(e2["cache_hits"], 2)
        self.assertEqual(e1["data"][0]["embedding"], e2["data"][0]["embedding"])

    def test_02_immortal_job_durable_checkpoint_and_idempotent_resume(self) -> None:
        st, job = self._post("/v1/jobs/create", {"job_id": "wf-radar-01", "app": "radar", "name": "scan-pipe", "total_steps": 4})
        self.assertEqual(st, 200)
        self.assertEqual(job["status"], "running")

        # Complete steps 0 and 1
        self._post("/v1/jobs/step", {"job_id": "wf-radar-01", "step_key": "fetch", "step_index": 0, "result": {"items": 12}})
        self._post("/v1/jobs/step", {"job_id": "wf-radar-01", "step_key": "dedup", "step_index": 1, "result": {"unique": 7}})

        # Simulate crash & resume -> must point directly at step 2 with cached outputs intact
        resumed = self._get("/v1/jobs/resume?job_id=wf-radar-01")
        self.assertEqual(resumed["next_step_index"], 2)
        self.assertEqual(resumed["completed_outputs"]["fetch"]["items"], 12)

        # Duplicate replay of step 0 -> skipped idempotently!
        _, dup = self._post("/v1/jobs/step", {"job_id": "wf-radar-01", "step_key": "fetch", "step_index": 0, "result": {"items": 999}})
        self.assertTrue(dup["already_completed"])
        self.assertEqual(dup["cached_result"]["items"], 12)

        # Finish steps 2 & 3 -> job marks completed
        self._post("/v1/jobs/step", {"job_id": "wf-radar-01", "step_key": "rank", "step_index": 2, "result": {"top": 3}})
        _, fin = self._post("/v1/jobs/step", {"job_id": "wf-radar-01", "step_key": "notify", "step_index": 3, "result": {"sent": True}})
        self.assertEqual(fin["job_status"], "completed")

    def test_03_browser_grid_lazy_zero_ram_and_cartridge_toggle(self) -> None:
        # Must consume 0 MB when idle (lazy launch)
        st = self._get("/v1/browser/status")
        self.assertTrue(st["ok"])
        self.assertFalse(st["running"])
        self.assertEqual(st["idle_ram_mb"], 0.0)

        # Hot-disable browser_grid cartridge -> 503; re-enable -> 200
        code_dis, res_dis = self._post("/v1/cartridges", {"name": "browser_grid", "enabled": False})
        self.assertEqual(code_dis, 200)
        self.assertFalse(res_dis["enabled"])

        code_blk, _ = self._post("/v1/browser/session", {"app": "radar"})
        self.assertEqual(code_blk, 503)

        code_en, res_en = self._post("/v1/cartridges", {"name": "browser_grid", "enabled": True})
        self.assertEqual(code_en, 200)
        self.assertTrue(res_en["enabled"])

        # If a real browser binary is installed on host, verify live CDP session lease + clean shutdown
        if st["binary_found"]:
            c_sess, sess = self._post("/v1/browser/session", {"app": "radar", "zero_media": True})
            self.assertEqual(c_sess, 200)
            self.assertIn("ws://", sess["ws_debugger_url"])
            self.assertIn("image", sess["block_resource_types"])
            c_rel, rel = self._post("/v1/browser/close", {"session_id": sess["session_id"], "shutdown_if_empty": True})
            self.assertEqual(c_rel, 200)
            self.assertFalse(rel["browser_running"])

    def test_04_zygote_exec_canary_twin_judge_sdk_and_mcp(self) -> None:
        # 1. Zygote execution (Linux CoW fork / Windows warm pool)
        st_z, zres = self._post(
            "/v1/zygote/exec",
            {"kernel": "hash_batch", "payload": {"items": ["alpha", "beta", "gamma"]}},
        )
        self.assertEqual(st_z, 200)
        self.assertEqual(zres["result"]["count"], 3)
        self.assertLess(zres["elapsed_ms"], 100.0)

        # 2. Canary Twin Judge: PROMOTE on identical twin, ROLLBACK on mismatched twin
        s_base, u_base = _start_mini_server({"version": "1", "items": [1, 2, 3], "ts": 100})
        s_good, u_good = _start_mini_server({"version": "1", "items": [1, 2, 3], "ts": 999})
        s_bad, u_bad = _start_mini_server({"version": "1", "items": [1, 2, 999], "ts": 999})
        try:
            st_p, rep_p = self._post("/v1/canary/compare", {"baseline_url": u_base, "canary_url": u_good, "samples": 4})
            self.assertEqual(st_p, 200)
            self.assertEqual(rep_p["verdict"], "PROMOTE")
            self.assertEqual(rep_p["parity_pct"], 100.0)

            st_r, rep_r = self._post("/v1/canary/compare", {"baseline_url": u_base, "canary_url": u_bad, "samples": 4})
            self.assertEqual(st_r, 200)
            self.assertEqual(rep_r["verdict"], "ROLLBACK")
            self.assertEqual(rep_r["parity_pct"], 0.0)
        finally:
            s_base.shutdown(); s_base.server_close()
            s_good.shutdown(); s_good.server_close()
            s_bad.shutdown(); s_bad.server_close()

        # 3. SDK + MCP integration for v17 cartridges
        cli = connect(app="v17-sdk", anchor_url=self.anchor, auto_register=False)
        self.assertTrue(cli.pareto_route()["ok"])
        mcp_r = handle_mcp_request(
            {"jsonrpc": "2.0", "id": 9, "method": "tools/call", "params": {"name": "chimera_vgpu_route", "arguments": {"max_cost_usd": 0.0}}},
            anchor_url=self.anchor,
        )
        self.assertTrue(json.loads(mcp_r["result"]["content"][0]["text"])["ok"])


if __name__ == "__main__":
    unittest.main()
