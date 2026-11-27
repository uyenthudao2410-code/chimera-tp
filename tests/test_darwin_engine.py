"""Comprehensive tests for CHIMERA-DARWIN (All 6 Evolutionary Subsystems + Mirror-Race 2.0 + MCP 40 tools)."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from chimera_tp.platform import darwin_engine as de
from chimera_tp.platform.agent_probe import AgentHyperBus
from chimera_tp.platform.mcp_server import _TOOLS, handle_mcp_request


class TestChimeraDarwin(unittest.TestCase):
    def test_01_bit_exact_deterministic_gaussian_numpy_vs_pure_python(self) -> None:
        v_fast = de.deterministic_gaussian(257, genome_id="g_parity", generation=3, seed=991, tag="es")
        with mock.patch.object(de, "_np", None):
            v_pure = de.deterministic_gaussian(257, genome_id="g_parity", generation=3, seed=991, tag="es")
        self.assertEqual(len(v_fast), 257)
        self.assertEqual(len(v_pure), 257)
        max_diff = max(abs(a - b) for a, b in zip(v_fast, v_pure))
        self.assertLess(max_diff, 1e-12)

    def test_02_genome_ledger_128_byte_wire_pack_and_teleport_roundtrip(self) -> None:
        packed = de.GenomeLedger.pack_step_compact(
            generation=1,
            sigma=0.05,
            alpha=0.12,
            seeds=[11, 22, 33, 44, 55, 66, 77, 88],
            antithetic_deltas=[0.4, -0.2, 0.1, 0.0, -0.5, 0.3, 0.2, -0.1],
        )
        # 14-byte header + 8 * 8 bytes = 78 bytes per generation!
        self.assertEqual(len(packed), 78)

        src_ledger = de.GenomeLedger(ephemeral=True)
        src_ledger.register_genome(
            genome_id="tele_test",
            kind="neural_seed_es",
            model_family="test_mlp",
            base_seed=777,
            base_sha256="abc123",
            param_count=500_000,
        )
        wb = src_ledger.record_step(
            genome_id="tele_test",
            generation=1,
            sigma=0.05,
            alpha=0.12,
            pop_size=16,
            mean_fitness=0.5,
            best_fitness=0.8,
            oracle_digest="deadbeef",
            seeds=[11, 22, 33, 44, 55, 66, 77, 88],
            antithetic_deltas=[0.4, -0.2, 0.1, 0.0, -0.5, 0.3, 0.2, -0.1],
        )
        self.assertEqual(wb, 78)
        exp = src_ledger.export_genome("tele_test")
        self.assertTrue(exp["ok"])
        self.assertEqual(exp["stats"]["svhome_weight_bytes_stored"], 0)
        self.assertGreater(exp["stats"]["compression_ratio_vs_fp16"], 1000.0)

        dst_ledger = de.GenomeLedger(ephemeral=True)
        imp = dst_ledger.import_genome(exp["genome"])
        self.assertTrue(imp["ok"])
        self.assertEqual(imp["steps_imported"], 1)
        exp2 = dst_ledger.export_genome("tele_test")
        self.assertEqual(exp["genome"]["steps"], exp2["genome"]["steps"])

    def test_03_seed_es_neural_foundry_zero_backprop_and_weightless_replay(self) -> None:
        ledger_win = de.GenomeLedger(ephemeral=True)
        foundry_win = de.SeedEsNeuralFoundry(ledger_win)

        res = foundry_win.evolve(
            genome_id="reflex_unit_test",
            generations=50,
            pop_size=32,
            sigma=0.12,
            alpha=0.08,
            base_seed=1337,
            in_dim=64,
            hidden_dim=20,
        )
        self.assertTrue(res["ok"])
        self.assertTrue(res["zero_backprop"])
        self.assertGreater(res["evolved"]["accuracy"], res["baseline"]["accuracy"])
        self.assertGreaterEqual(res["evolved"]["accuracy"], 0.85)
        self.assertGreater(res["fitness_gain"], 0.8)
        self.assertEqual(res["memory_comparison"]["vram_reduction_ratio"], 6.0)
        self.assertLess(res["genome_sync"]["binary_wire_bytes"], 15_000)

        # Teleport ONLY `.genome.json` to an independent remote node ledger & reconstruct bit-identically
        exported = ledger_win.export_genome("reflex_unit_test")
        self.assertTrue(exported["ok"])

        ledger_svhome = de.GenomeLedger(ephemeral=True)
        ledger_svhome.import_genome(exported["genome"])
        foundry_svhome = de.SeedEsNeuralFoundry(ledger_svhome)
        replayed = foundry_svhome.reconstruct_from_genome(exported["genome"])
        self.assertTrue(replayed["ok"])
        self.assertEqual(replayed["reconstructed_weights_sha256"], res["final_weights_sha256"])
        self.assertEqual(replayed["evaluation"]["accuracy"], res["evolved"]["accuracy"])

        pred = foundry_svhome.predict_tool(
            exported["genome"],
            "race 3 competing patch candidates in isolated cow shadow directory",
        )
        self.assertTrue(pred["ok"])
        self.assertEqual(pred["tool"], "chimera_mirror_race")

    def test_04_es_param_optimizer_real_traces_and_doctrine_invariants(self) -> None:
        # Verify hard Law 3 safety rail rejects illegal policies with -1e9
        ok_bad, viols = de.check_doctrine_invariants(
            {
                "peer_ram_reserve_mib": 1024.0,
                "peer_max_load1": 3.5,
                "peer_max_temp_c": 85.0,
                "peer_cpu_quota_pct": 120.0,
                "tquota_first_byte_hedge_ms": 1000.0,
                "tquota_idle_rss_threshold_mb": 100.0,
            }
        )
        self.assertFalse(ok_bad)
        self.assertGreaterEqual(len(viols), 5)

        ledger = de.GenomeLedger(ephemeral=True)
        opt = de.EsParamOptimizer(ledger)
        repo_root = Path(__file__).resolve().parents[1]
        res = opt.optimize(repo_path=repo_root, generations=18, pop_size=12, base_seed=2026)
        self.assertTrue(res["ok"])
        self.assertEqual(res["mode"], "shadow_only")
        self.assertTrue(res["doctrine_law6_compliant"])
        self.assertGreaterEqual(res["evolved_shadow"]["fitness"], res["baseline"]["fitness"])
        self.assertGreater(res["fitness_gain"], 0.0)
        ok_shadow, shadow_viols = de.check_doctrine_invariants(res["shadow_policy"])
        self.assertTrue(ok_shadow, f"Shadow policy violated Doctrine invariants: {shadow_viols}")

    def test_05_prompt_es_evolver_anti_reward_hacking_and_immune_seeding(self) -> None:
        bus = AgentHyperBus(ephemeral=True)
        ledger = de.GenomeLedger(ephemeral=True)
        evolver = de.PromptEsEvolver(ledger, hive=bus.symbiont.hive, coroner=bus.symbiont.coroner)

        # Direct anti-reward-hacking check
        sc = de._PROMPT_FOSSIL_SCENARIOS[0]
        short_hack = evolver.score_rule("chimera_xray_batch", sc)
        self.assertFalse(short_hack["valid"])
        self.assertEqual(short_hack["rejected_reason"], "degenerate_too_short")

        rep_hack = evolver.score_rule(
            "use chimera_xray_batch chimera_xray_batch chimera_xray_batch chimera_xray_batch batch batch batch batch",
            sc,
        )
        self.assertFalse(rep_hack["valid"])
        self.assertEqual(rep_hack["rejected_reason"], "keyword_repetition_hacking")

        res = evolver.evolve(generations=3, apply_immune=True)
        self.assertTrue(res["ok"])
        self.assertGreater(res["prompt_token_reduction_pct"], 25.0)
        self.assertGreaterEqual(res["evolved_mean_fitness"], res["baseline_mean_fitness"])
        self.assertGreaterEqual(res["reward_hacking_mutants_rejected"], 10)
        self.assertEqual(res["immune_rules_seeded"], res["scenarios_evolved"])
        bus.verifier.close()

    def test_06_mirror_race_v2_multi_generation_crossover_breeding(self) -> None:
        bus = AgentHyperBus(ephemeral=True)
        try:
            with tempfile.TemporaryDirectory(prefix="chimera_mr2_") as td:
                repo = Path(td)
                (repo / "calc.py").write_text(
                    "def add(a, b):\n"
                    "    return a - b  # BUG 1\n\n"
                    "def mul(a, b):\n"
                    "    return a + b  # BUG 2\n",
                    encoding="utf-8",
                )
                (repo / "test_calc.py").write_text(
                    "import unittest\n"
                    "import calc\n\n"
                    "class T(unittest.TestCase):\n"
                    "    def test_add(self):\n"
                    "        self.assertEqual(calc.add(2, 3), 5)\n\n"
                    "    def test_mul(self):\n"
                    "        self.assertEqual(calc.mul(3, 4), 12)\n",
                    encoding="utf-8",
                )
                candidates = [
                    {
                        "id": "cand_fix_add",
                        "edits": [{"path": "calc.py", "target": "return a - b  # BUG 1", "replacement": "return a + b"}],
                    },
                    {
                        "id": "cand_fix_mul",
                        "edits": [{"path": "calc.py", "target": "return a + b  # BUG 2", "replacement": "return a * b"}],
                    },
                ]

                # Classic Gen-1 race: neither partial fix passes 100% alone
                r1 = bus.symbiont.mirror_race.race(
                    repo,
                    candidates,
                    explicit_tests=["test_calc.py"],
                    commit_winner=False,
                    generations=1,
                )
                self.assertFalse(r1["ok"])
                self.assertEqual(r1["generations_run"], 1)
                self.assertGreater(r1["best_fitness"], 40.0)
                self.assertLess(r1["best_fitness"], 60.0)

                # Mirror-Race 2.0 (generations=2): breeds non-conflicting hunk crossover -> 100% PASS!
                r2 = bus.symbiont.mirror_race.race(
                    repo,
                    candidates,
                    explicit_tests=["test_calc.py"],
                    commit_winner=True,
                    generations=2,
                )
                self.assertTrue(r2["ok"])
                self.assertTrue(r2["committed"])
                self.assertEqual(r2["winner_generation"], 2)
                self.assertEqual(r2["generations_run"], 2)
                self.assertGreaterEqual(r2["crossover_offspring_tested"], 1)
                self.assertGreaterEqual(r2["best_fitness"], 99.0)
                final_src = (repo / "calc.py").read_text(encoding="utf-8")
                self.assertIn("return a + b", final_src)
                self.assertIn("return a * b", final_src)
        finally:
            bus.verifier.close()

    def test_07_darwin_sleep_cycle_shadow_card_and_zero_auto_activate(self) -> None:
        engine = de.DarwinEngine(ephemeral=True)
        with tempfile.TemporaryDirectory(prefix="chimera_sleep_") as td:
            receipt_file = Path(td) / "sleep_card.json"
            out = engine.sleep_cycle.run_once(
                repo_path=Path(__file__).resolve().parents[1],
                receipt_path=receipt_file,
                force=True,
                run_neural=True,
                neural_generations=8,
                param_generations=10,
            )
            self.assertTrue(out["ok"])
            self.assertTrue(receipt_file.is_file())
            card = json.loads(receipt_file.read_text(encoding="utf-8"))
            self.assertEqual(card["status"], "shadow_ready_for_approval")
            self.assertFalse(card["auto_activated"])
            self.assertTrue(card["doctrine_law6_compliant"])
            self.assertEqual(card["colab_cu_spent"], 0.0)
            self.assertGreaterEqual(card["es_param_shadow"]["fitness_gain"], 0.0)

    def test_08_lazy_load_and_mcp_40_tools(self) -> None:
        bus = AgentHyperBus(ephemeral=True)
        try:
            # Verify 100% lazy instantiation (0 bytes daemon startup RAM!)
            self.assertIsNone(bus.symbiont._darwin)
            st = bus.symbiont.darwin.status()
            self.assertTrue(st["ok"])
            self.assertTrue(st["lazy_loaded"])
            self.assertEqual(st["svhome_weight_bytes"], 0)
            self.assertIsNotNone(bus.symbiont._darwin)
        finally:
            bus.verifier.close()

        names = [t["name"] for t in _TOOLS]
        self.assertGreaterEqual(len(names), 41)
        self.assertIn("chimera_darwin", names)
        self.assertIn("chimera_aeon", names)
        mr_tool = next(t for t in _TOOLS if t["name"] == "chimera_mirror_race")
        self.assertIn("generations", mr_tool["inputSchema"]["properties"])

        resp = handle_mcp_request(
            {
                "jsonrpc": "2.0",
                "id": 99,
                "method": "tools/call",
                "params": {"name": "chimera_darwin", "arguments": {"action": "status"}},
            }
        )
        self.assertIsNotNone(resp)
        payload = json.loads(resp["result"]["content"][0]["text"])
        self.assertTrue(payload["ok"])


if __name__ == "__main__":
    unittest.main()
