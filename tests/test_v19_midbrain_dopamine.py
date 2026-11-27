"""Unit tests for CHIMERA MIDBRAIN DOPAMINE v19 (RPE-Pivots, 1% Immune Vault, Value/RPE Critic, Live API)."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
import urllib.request

from chimera_tp.autopilot import OpsConfig
from chimera_tp.dashboard import ChimeraDaemon
from chimera_tp.midbrain_dopamine import (
    N_STRUCT_FEATURES,
    N_VSA_BUCKETS,
    MidbrainDopamineEngine,
    extract_rpe_pivots,
)
from chimera_tp.vsa_memory_service import SharedVsaMemoryService


class TestV19MidbrainDopamine(unittest.TestCase):
    def test_01_rpe_pivot_distillation_and_dlp(self) -> None:
        trace = (
            "Analyzing test_math_engine.py failure\n"
            "FAILED tests/test_math_engine.py::test_round_builtin - assert 2 == 3\n"
            "Root cause fixed: implement half-away-from-zero rounding cleanly passed test_rc=0\n"
            "leaked=owner.secret@gmail.com Authorization: Bearer secret_token_abcdef123456\n"
        )
        pivots = extract_rpe_pivots(trace, outcome="win", max_pivots=4)
        kinds = {p["kind"] for p in pivots}
        self.assertIn("POS_BREAKTHROUGH", kinds)
        self.assertIn("NEG_TRAP", kinds)
        joined = "\n".join(p["pivot_text"] for p in pivots)
        self.assertNotIn("owner.secret@gmail.com", joined)
        self.assertNotIn("secret_token_abcdef123456", joined)

    def test_02_immune_vault_pin_and_prune_protection(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            vsa = SharedVsaMemoryService(db_path=Path(td) / "vsa.db")
            try:
                items = [
                    {
                        "item_id": f"mem_{i}",
                        "domain": "tquota_thought",
                        "text": f"pytest conftest fixture rule {i} verified passed",
                        "payload": {"brief_text": f"Fix fixture {i} with clean scope passed", "verified": True},
                        "reward": 2.0 if i == 0 else 1.0,
                    }
                    for i in range(12)
                ]
                vsa.store_batch(items)
                fb = vsa.record_causal_feedback(["mem_0"], success=True, rpe_delta=0.45)
                self.assertGreaterEqual(fb["pinned_count"], 1)
                summary = vsa.immune_vault_summary()
                pinned_ids = {row["item_id"] for row in summary["items"]}
                self.assertIn("mem_0", pinned_ids)

                # Prune down to 5 items: mem_0 MUST survive in Immune Vault
                pruned = vsa.prune_low_value(max_items=5)
                self.assertEqual(pruned["total_items"], 5)
                cap = vsa.build_memory_capsule("pytest conftest fixture rule 0", top_k=5, min_sim=0.0)
                self.assertIn("mem_0", cap["used_item_ids"])
                self.assertIn("1%-IMMUNE", cap["capsule"])

                piv_res = vsa.distill_rpe_pivots(limit=10)
                self.assertGreaterEqual(piv_res["pivots_stored"], 1)
            finally:
                vsa.close()

    def test_03_midbrain_scoring_rpe_spike_trough_and_probe_install(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            eng = MidbrainDopamineEngine(td)
            self.assertEqual(eng.status()["probe_mode"], "heuristic_prior")

            flaw_text = "FAILED tests/test_optimizer.py AssertionError codex_rc=124 timed out no_diff_produced"
            pass_text = "diff --git a/math.py b/math.py\n+return x\nRoot cause fixed: 12 passed, 0 failed test_rc=0 verified"
            r_flaw = eng.score(flaw_text, task_id="issue_998")
            r_pass = eng.score(pass_text, prev_text=flaw_text, task_id="issue_998")

            self.assertLess(r_flaw["value_v"], 0.45)
            self.assertGreater(r_pass["value_v"], r_flaw["value_v"])
            self.assertGreater(r_pass["rpe_delta"], 0.12)
            self.assertEqual(r_pass["signal"], "SPIKE")
            self.assertEqual(r_flaw["signal"], "TROUGH")

            probe = {
                "probe_mode": "whitebox_distilled_1pct",
                "student_vsa_weights": [0.05] * N_VSA_BUCKETS,
                "student_feat_weights": [0.25] * N_STRUCT_FEATURES,
                "student_bias": 0.1,
                "probe_meta": {"model_id": "test-qwen", "best_layer": 14, "val_auc": 0.91},
            }
            inst = eng.install_probe(probe)
            self.assertTrue(inst["ok"])
            reloaded = MidbrainDopamineEngine(td)
            self.assertEqual(reloaded.status()["probe_mode"], "whitebox_distilled_1pct")
            self.assertEqual(reloaded.status()["probe_meta"]["best_layer"], 14)

    def test_04_live_daemon_midbrain_http_endpoints(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = OpsConfig(
                role="server",
                node_name="midbrain-test",
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
                def post(path: str, data: dict) -> dict:
                    req = urllib.request.Request(
                        f"{base}{path}",
                        data=json.dumps(data).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    with urllib.request.urlopen(req, timeout=4.0) as r:
                        return json.loads(r.read().decode("utf-8"))

                s_res = post(
                    "/api/vsa/store",
                    {"item_id": "cry_1", "domain": "patch_crystal", "text": "pytest async fixture fix passed", "reward": 2.0},
                )
                self.assertTrue(s_res["ok"])
                d_res = post("/api/midbrain/distill-pivots", {"limit": 20})
                self.assertGreaterEqual(d_res["pivots_stored"], 1)

                fb_res = post("/api/midbrain/feedback", {"item_ids": ["cry_1"], "success": True, "rpe_delta": 0.3})
                self.assertTrue(fb_res["ok"])
                self.assertGreaterEqual(fb_res["pinned_count"], 1)

                sc_res = post(
                    "/api/midbrain/score",
                    {"text": "diff --git a/a.py b/a.py\n+fix\n10 passed, 0 failed test_rc=0", "task_id": "t1"},
                )
                self.assertTrue(sc_res["ok"])
                self.assertIn(sc_res["signal"], ("SPIKE", "STEADY", "TROUGH"))

                with urllib.request.urlopen(f"{base}/api/midbrain/status", timeout=4.0) as r:
                    st = json.loads(r.read().decode("utf-8"))
                self.assertTrue(st["ok"])
                self.assertGreaterEqual(st["scores_served"], 1)
                self.assertGreaterEqual(st["immune_vault"]["pinned_count"], 1)
            finally:
                daemon.close()
