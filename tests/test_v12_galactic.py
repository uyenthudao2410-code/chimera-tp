"""CHIMERA-HYPER v12.0 OMEGA-GALACTIC Adversarial, Daemon API, CLI & Zero-Weight Tests."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
import urllib.request
from pathlib import Path

from chimera_tp.autopilot import OpsConfig
from chimera_tp.dashboard import ChimeraDaemon
from chimera_tp.native import v12_native_caps
from chimera_tp.v10_sovereign_crypto import FrostThreshold2of3
from chimera_tp.v10_sovereign_runtime import WasmLiveTeleportEngine
from chimera_tp.v12_bench import format_galactic_markdown, run_galactic_benchmark
from chimera_tp.v12_galactic_engines import (
    AlienDialectEngine,
    CausalOriginTeleporter,
    HolographicSlpEngine,
    HyperdimensionalVsaMesh,
    ReversibleBennettVM,
)


class TestV12Galactic(unittest.TestCase):
    def test_01_native_v12_capabilities(self) -> None:
        caps = v12_native_caps()
        self.assertTrue(all(caps.values()), caps)

    def test_02_causal_origin_and_bennett_reversible_mitm(self) -> None:
        co = CausalOriginTeleporter.run_benchmark()
        self.assertTrue(co["ok"], co)
        self.assertGreater(co["wire_saved_pct"], 99.0)

        rb = ReversibleBennettVM.run_benchmark()
        self.assertTrue(rb["ok"], rb)
        self.assertTrue(rb["zero_snapshot_reverse_exact"])
        self.assertLessEqual(rb["mitm_evals"], 512)

    def test_03_holographic_slp_and_homomorphic_lthash(self) -> None:
        slp = HolographicSlpEngine.run_benchmark()
        self.assertTrue(slp["ok"], slp)
        self.assertTrue(slp["char_at_probes_exact"])
        self.assertTrue(slp["lthash_homomorphic_exact"])

        # Direct additive homomorphism test
        h_a = HolographicSlpEngine.lthash(b"LEFT_SLICE")
        h_b = HolographicSlpEngine.lthash(b"RIGHT_SLICE")
        h_sum = HolographicSlpEngine.lthash_add(h_a, h_b)
        self.assertEqual(HolographicSlpEngine.lthash_sub(h_sum, h_b), h_a)

    def test_04_alien_dialect_mismatch_and_shred(self) -> None:
        al = AlienDialectEngine.run_benchmark()
        self.assertTrue(al["ok"], al)
        self.assertTrue(al["foreign_dialect_mismatch"])
        self.assertTrue(al["ephemeral_shred_enforced"])

    def test_05_vsa_10000_bit_40pct_destruction(self) -> None:
        vsa = HyperdimensionalVsaMesh.run_benchmark(trials=100, corrupt_pct=0.40)
        self.assertTrue(vsa["ok"], vsa)
        self.assertEqual(vsa["recall_pct"], 100.0)
        self.assertLess(vsa["mean_query_ms"], 2.0)

    def test_06_full_29_galactic_benchmark_and_markdown(self) -> None:
        rep = run_galactic_benchmark(wave="all")
        self.assertTrue(rep["ok"], rep)
        self.assertEqual(rep["ideas_verified"], 29)
        self.assertEqual(rep["ideas_total"], 29)
        md = format_galactic_markdown(rep)
        self.assertIn("`29/29`", md)
        self.assertIn("CHIMERA-HYPER v12.0.0", md)

    def test_07_live_daemon_galactic_apis_tarpit_peer_and_ui(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            work = root / "work"
            work.mkdir()
            (work / "sample.py").write_text("def galactic_marker_v12(): return 29\n", encoding="utf-8")

            cfg = OpsConfig(
                role="server",
                node_name="galactic_unit",
                dashboard_bind="127.0.0.1:0",
                beam_port=0,
                rpc_v4_port=0,
                rpc_v6_port=-1,
                query_port=0,
                warp_port=-1,
                edge_proxy_port=-1,
                allowed_query_roots=[str(work)],
                search_roots=[str(work)],
                edge_targets={},
                phantom_enabled=False,
            )
            daemon = ChimeraDaemon(config=cfg, ops_dir=root / "ops", auto_seed_on_empty=False).start()
            base = f"http://127.0.0.1:{daemon.http_addr[1]}"
            try:
                h = json.loads(urllib.request.urlopen(f"{base}/api/health", timeout=4.0).read().decode())
                self.assertEqual(h["version"], "12.0.0")
                self.assertTrue(all(h["native_v12"].values()))

                gs = json.loads(urllib.request.urlopen(f"{base}/api/galactic/status", timeout=4.0).read().decode())
                self.assertTrue(gs["ok"])
                self.assertEqual(gs["version"], "12.0.0")

                # Stateless 0-KB Tarpit determinism + zero disk artifacts in work/
                before_work = sorted(os.listdir(work))
                t1 = json.loads(urllib.request.urlopen(f"{base}/api/galactic/tarpit/env/prod/secrets.yml", timeout=4.0).read().decode())
                t2 = json.loads(urllib.request.urlopen(f"{base}/api/galactic/tarpit/env/prod/secrets.yml", timeout=4.0).read().decode())
                self.assertTrue(t1["ok"])
                self.assertTrue(t1["stateless"])
                self.assertEqual(t1["content"], t2["content"])
                self.assertEqual(sorted(os.listdir(work)), before_work)

                # Live FROST 2-of-3 partial sign & live WASM checkpoint teleport against peer base URL
                fr = FrostThreshold2of3.run_benchmark(peer_http_base=base)
                self.assertTrue(fr["ok"], fr)
                self.assertTrue(fr["peer_signed_live"], fr)

                wt = WasmLiveTeleportEngine.run_benchmark(peer_http_base=base)
                self.assertTrue(wt["ok"], wt)
                self.assertTrue(wt["resumed_on_peer"], wt)

                # POST /api/galactic/vsa-query and POST /api/galactic/benchmark
                req_vsa = urllib.request.Request(
                    f"{base}/api/galactic/vsa-query",
                    data=json.dumps({"trials": 25, "corrupt_pct": 0.40}).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                vr = json.loads(urllib.request.urlopen(req_vsa, timeout=10.0).read().decode())
                self.assertTrue(vr["ok"], vr)

                req_b = urllib.request.Request(
                    f"{base}/api/galactic/benchmark",
                    data=json.dumps({"wave": "v12", "local_only": True}).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                br = json.loads(urllib.request.urlopen(req_b, timeout=20.0).read().decode())
                self.assertTrue(br["ok"], br)
                self.assertEqual(br["ideas_verified"], 5)

                # Web UI check
                ui_html = urllib.request.urlopen(f"{base}/", timeout=4.0).read().decode("utf-8")
                self.assertIn("CHIMERA-HYPER v12.0 OMEGA-GALACTIC", ui_html)
                self.assertIn("pane-hyperdrive", ui_html)
                self.assertIn("pane-galactic", ui_html)
                self.assertIn("spotlight-modal", ui_html)
            finally:
                daemon.close()

    def test_08_cli_galactic_local_and_zero_weight_rss(self) -> None:
        for action in ("status", "tarpit", "bennett", "slp"):
            proc = subprocess.run(
                [sys.executable, "-m", "chimera_tp", "galactic", action, "--local"],
                capture_output=True,
                text=True,
                check=True,
            )
            data = json.loads(proc.stdout)
            self.assertTrue(data["ok"], f"{action}: {data}")

        # Subprocess Zero-Weight RSS (< 80.0 MB) after running all 29 galactic breakthroughs!
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            probe = (
                "import json; from pathlib import Path; "
                "from chimera_tp.autopilot import OpsConfig; "
                "from chimera_tp.dashboard import ChimeraDaemon; "
                "from chimera_tp.v12_bench import run_galactic_benchmark; "
                "r = run_galactic_benchmark(); assert r['ideas_verified'] == 29; "
                f"cfg=OpsConfig(role='server',node_name='zw12',dashboard_bind='127.0.0.1:0',beam_port=0,rpc_v4_port=0,rpc_v6_port=-1,query_port=0,warp_port=-1,edge_proxy_port=-1,allowed_query_roots=[{str(root)!r}],search_roots=[{str(root)!r}],phantom_enabled=False); "
                f"d=ChimeraDaemon(config=cfg,ops_dir=Path({str(root/'ops')!r}),auto_seed_on_empty=False).start(); "
                "st=d.status_payload(); d.close(); print(json.dumps(st['zero_weight']))"
            )
            proc = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, check=True)
            zw = json.loads(proc.stdout.strip().splitlines()[-1])
            self.assertTrue(zw["zero_weight_ok"], f"RSS exceeded 80MB: {zw}")
            self.assertLess(zw["daemon_ram_mb"], 80.0)


if __name__ == "__main__":
    unittest.main()
