"""Adversarial & stress verification suite for CHIMERA-HYPER v8.0.0 SINGULARITY (all 7 frontier ideas)."""

from __future__ import annotations

import json
import os
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import unittest
import urllib.request

from chimera_tp.autopilot import OpsConfig
from chimera_tp.dashboard import ChimeraDaemon
from chimera_tp.native import fsk_demod_bits, pir_xor_query, v8_native_caps
from chimera_tp.singularity_airgap_crypto import (
    AirGapFountainBridge,
    PlausibleDeniabilityVault,
    PrivateInfoRetrievalEngine,
    build_deterministic_pir_db,
)
from chimera_tp.singularity_bench import format_singularity_markdown, run_singularity_benchmark
from chimera_tp.singularity_kolmogorov_swarm import KolmogorovGrammarCodec, SwarmAnycastMesh
from chimera_tp.singularity_time_crdt import MerkleCrdtShadowTwin, SpeculativeTimeWarpEngine


class TestSingularityV8Protocol(unittest.TestCase):
    def test_native_v8_pir_xor_and_fsk_demod_exactness(self) -> None:
        caps = v8_native_caps()
        self.assertIn("pir_xor", caps)
        self.assertIn("fsk_demod", caps)

        # Verify pir_xor_query against reference bit-by-bit selection on 256 x 128 B DB
        n_rec, rec_len = 256, 128
        db = build_deterministic_pir_db(n_rec, rec_len)
        target = 173
        qa = bytearray(os.urandom((n_rec + 7) // 8))
        qb = bytearray(qa)
        qb[target >> 3] ^= 1 << (target & 7)
        r_a = pir_xor_query(db, n_rec, rec_len, qa)
        r_b = pir_xor_query(db, n_rec, rec_len, qb)
        rec = (int.from_bytes(r_a, "little") ^ int.from_bytes(r_b, "little")).to_bytes(rec_len, "little")
        self.assertEqual(rec, db[target * rec_len : (target + 1) * rec_len])

        # Verify Q15 FSK demodulator exactness over clean 18/19.2 kHz PCM bits
        msg = b"CHIMERA8_FSK"
        pcm = AirGapFountainBridge.packets_to_pcm([msg])
        bits = fsk_demod_bits(pcm)
        self.assertEqual(len(bits), len(msg) * 8)
        rebuilt = bytes(
            sum((bits[i * 8 + k] << (7 - k)) for k in range(8)) for i in range(len(msg))
        )
        self.assertEqual(rebuilt, msg)

    def test_idea1_speculative_timewarp_stale_invalidation_and_random_throttle(self) -> None:
        res = SpeculativeTimeWarpEngine.run_benchmark()
        self.assertTrue(res["ok"])
        self.assertEqual(res["stale_reads"], 0)
        self.assertTrue(res["adversarial_throttled"])
        self.assertLess(res["warm_hit_mean_ms"], res["cold_mean_ms"])

    def test_idea2_merkle_crdt_20_shuffled_orders_and_conflict_audit(self) -> None:
        res = MerkleCrdtShadowTwin.run_benchmark()
        self.assertTrue(res["ok"])
        self.assertEqual(res["permutations_tested"], 20)
        self.assertEqual(res["unique_merkle_roots"], 1)
        self.assertGreaterEqual(res["conflicts_audited"], 1)

    def test_idea3_airgap_6db_awgn_burst_and_optical_30pct_loss(self) -> None:
        res = AirGapFountainBridge.run_benchmark()
        self.assertTrue(res["ok"])
        self.assertEqual(res["audio_awgn_snr_db"], 6.0)

    def test_idea4_pir_1mib_wire_savings_and_statistical_blindness(self) -> None:
        res = PrivateInfoRetrievalEngine.run_benchmark()
        self.assertTrue(res["ok"])
        self.assertEqual(res["db_bytes"], 1048576)
        self.assertGreater(res["wire_saved_pct"], 99.8)

    def test_idea5_dual_vault_10vs10_forensic_indistinguishability(self) -> None:
        res = PlausibleDeniabilityVault.run_benchmark()
        self.assertTrue(res["ok"])
        self.assertTrue(res["shard_bytes_equal"])
        self.assertGreater(res["single_mean_entropy"], 7.98)
        self.assertGreater(res["dual_mean_entropy"], 7.98)
        self.assertLess(res["max_lag1_autocorr"], 0.03)

    def test_idea6_kolmogorov_3_corpora_beats_zlib9_lzma_and_no_random_bloat(self) -> None:
        res = KolmogorovGrammarCodec.run_benchmark()
        self.assertTrue(res["ok"])
        j = res["corpora"]["jsonl_1000"]
        self.assertLess(j["v8_kolmogorov_bytes"], j["zlib9_bytes"])
        self.assertLess(j["v8_kolmogorov_bytes"], j["lzma_bytes"])
        self.assertLess(j["v8_kolmogorov_bytes"], j["v7_ppm_bytes"])
        self.assertLess(res["random_overhead_pct"], 0.5)

        # Edge-case mixed prose must remain bit-exact via fallback
        prose = b"Arbitrary mixed text 123 and non-matching lines!\nDifferent line 2\n" * 40
        comp_p = KolmogorovGrammarCodec.compress(prose)
        self.assertEqual(KolmogorovGrammarCodec.decompress(comp_p), prose)

    def test_idea7_swarm_3node_recoding_and_k3_rehydration(self) -> None:
        res = SwarmAnycastMesh.run_benchmark()
        self.assertTrue(res["ok"])
        self.assertFalse(res["relay_saw_plaintext"])
        self.assertTrue(res["standby_rehydration_ok"])

    def test_daemon_singularity_endpoints_and_isolated_zero_weight_rss(self) -> None:
        full = run_singularity_benchmark()
        self.assertTrue(full["ok"])
        self.assertEqual(full["ideas_verified"], 7)
        self.assertIn("CHIMERA-HYPER v8.0.0", format_singularity_markdown(full))

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = OpsConfig(
                role="server",
                node_name="singularity_unit",
                dashboard_bind="127.0.0.1:0",
                beam_port=0,
                rpc_v4_port=0,
                rpc_v6_port=-1,
                query_port=0,
                warp_port=-1,
                edge_proxy_port=-1,
                allowed_query_roots=[str(root)],
                search_roots=[str(root)],
                edge_targets={},
                phantom_enabled=False,
            )
            daemon = ChimeraDaemon(config=cfg, ops_dir=root / "ops", auto_seed_on_empty=False).start()
            base = f"http://127.0.0.1:{daemon.http_addr[1]}"
            try:
                h = json.loads(urllib.request.urlopen(f"{base}/api/health", timeout=4.0).read().decode())
                self.assertIn(h["version"], ("8.0.0", "9.0.0", "10.0.0", "11.0.0", "12.0.0"))

                st = json.loads(urllib.request.urlopen(f"{base}/api/singularity/status", timeout=4.0).read().decode())
                self.assertTrue(st["ok"])
                self.assertEqual(st["version"], "8.0.0")

                for ep in ("pir-shard", "crdt-merge", "dual-vault", "kolmogorov", "airgap", "swarm"):
                    req = urllib.request.Request(
                        f"{base}/api/singularity/{ep}",
                        data=b"{}",
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    res = json.loads(urllib.request.urlopen(req, timeout=15.0).read().decode())
                    self.assertTrue(res["ok"], f"{ep} failed: {res}")

                req_b = urllib.request.Request(
                    f"{base}/api/singularity/benchmark",
                    data=json.dumps({"local_only": True}).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                b_res = json.loads(urllib.request.urlopen(req_b, timeout=20.0).read().decode())
                self.assertTrue(b_res["ok"])
                self.assertEqual(b_res["ideas_verified"], 7)
            finally:
                daemon.close()

            # Fresh subprocess Zero-Weight RSS check (< 80 MB)
            probe_code = (
                "import json; from pathlib import Path; "
                "from chimera_tp.autopilot import OpsConfig; "
                "from chimera_tp.dashboard import ChimeraDaemon; "
                f"cfg=OpsConfig(role='server',node_name='zw8',dashboard_bind='127.0.0.1:0',beam_port=0,rpc_v4_port=0,rpc_v6_port=-1,query_port=0,warp_port=-1,edge_proxy_port=-1,"
                f"allowed_query_roots=[{str(root)!r}],search_roots=[{str(root)!r}],phantom_enabled=False); "
                f"d=ChimeraDaemon(config=cfg,ops_dir=Path({str(root/'o2')!r}),auto_seed_on_empty=False).start(); "
                "st=d.status_payload(); d.close(); print(json.dumps(st['zero_weight']))"
            )
            proc = subprocess.run([sys.executable, "-c", probe_code], capture_output=True, text=True, check=True)
            zw = json.loads(proc.stdout.strip().splitlines()[-1])
            self.assertTrue(zw["zero_weight_ok"], f"RSS exceeded 80MB: {zw}")


if __name__ == "__main__":
    unittest.main()
