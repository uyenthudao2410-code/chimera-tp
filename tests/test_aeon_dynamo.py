"""Unit & real-silicon tests for CHIMERA-DYNAMO / AEON Unified Fabric."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from chimera_tp.platform import aeon_dynamo as aeon
from chimera_tp.platform.agent_probe import AgentHyperBus
from chimera_tp.platform.mcp_server import _TOOLS, handle_mcp_request
from chimera_tp.platform.nvcuda_ptx import NvCudaPtxEngine


class TestAeonDynamoUnified(unittest.TestCase):
    def test_01_titans_surprise_compactor_folds_noise_keeps_100pct_errors(self) -> None:
        comp = aeon.TitansSurpriseCompactor()
        lines = [f"test_unit_{i:04d} (tests.mod.Suite) ... ok" for i in range(600)]
        lines[212] = "Traceback (most recent call last):"
        lines[213] = '  File "chimera_tp/platform/substrate.py", line 901, in handle'
        lines[214] = "AssertionError: expected effortFlipsObserved == 0, got 3"
        lines[488] = "ERROR: HTTP 409 Conflict on svhome peer_guard"
        raw = "\n".join(lines)

        res = comp.compact(raw, max_chars=2400, max_lines=36)
        self.assertTrue(res["ok"])
        self.assertTrue(res["compacted"])
        self.assertGreater(res["saved_pct"], 80.0)
        self.assertLessEqual(res["compacted_bytes"], 2400)
        self.assertIn("AssertionError: expected effortFlipsObserved == 0, got 3", res["text"])
        self.assertIn("HTTP 409 Conflict on svhome peer_guard", res["text"])
        self.assertEqual(comp.stats()["spills_prevented"], 1)

    def test_02_chrono_synapse_sha256_auto_invalidation_and_turn0_cheatsheet(self) -> None:
        syn = aeon.ChronoSynapseEngine(ephemeral=True)
        with tempfile.TemporaryDirectory(prefix="chimera_syn_") as td:
            repo = Path(td)
            fp = repo / "router.py"
            fp.write_text("def route(): return 'v1'\n", encoding="utf-8")

            rec = syn.record_fact(
                repo=repo,
                file_path="router.py",
                symbol="route",
                fact_text="route() enforces monotonic effort lock without mid-session flips.",
                agent_id="codex",
                surprise_score=8.5,
            )
            self.assertTrue(rec["ok"])
            self.assertTrue(len(rec["file_sha256"]) == 16)

            q1 = syn.query_file_facts(repo, ["router.py"])
            self.assertEqual(len(q1["facts"]), 1)
            self.assertEqual(q1["stale_invalidated"], 0)

            cs = syn.compile_turn0_cheatsheet(repo, max_bytes=420)
            self.assertTrue(cs["ok"])
            self.assertLessEqual(cs["bytes"], 420)
            self.assertEqual(cs["facts_included"], 1)

            # Mutate the underlying file -> SHA-256 mismatch MUST auto-invalidate stale fact!
            fp.write_text("def route(): return 'v2_mutated'\n", encoding="utf-8")
            q2 = syn.query_file_facts(repo, ["router.py"])
            self.assertEqual(len(q2["facts"]), 0)
            self.assertEqual(q2["stale_invalidated"], 1)

    def test_02b_nixl_mmap_signal_ring_and_epistemic_decay_reflex(self) -> None:
        with tempfile.TemporaryDirectory(prefix="chimera_nixl_") as td:
            ring_p = Path(td) / "ring.bin"
            ring = aeon.NixlSignalRing(ring_path=ring_p, ephemeral=False)
            try:
                pub = ring.publish("sptc", {"tool_name": "read_file", "partial_args": '{"Path":"foo.py"'})
                self.assertTrue(pub["ok"])
                self.assertEqual(pub["seq"], 1)
                drained = ring.drain(limit=8)
                self.assertEqual(len(drained), 1)
                self.assertEqual(drained[0]["kind"], "sptc")
                self.assertEqual(drained[0]["payload"]["tool_name"], "read_file")

                # Epistemic Decay reflex emits into NIXL ring on SHA-256 drift
                syn = aeon.ChronoSynapseEngine(ephemeral=True, nixl_ring=ring)
                fp = Path(td) / "target.py"
                fp.write_text("x = 1\n", encoding="utf-8")
                syn.record_fact(repo=td, file_path="target.py", fact_text="x is 1")
                fp.write_text("x = 2\n", encoding="utf-8")
                q = syn.query_file_facts(td, ["target.py"])
                self.assertEqual(q["stale_invalidated"], 1)
                self.assertTrue(q["epistemic_decay_emitted"])
                decay_evs = ring.drain(limit=8)
                self.assertEqual(len(decay_evs), 1)
                self.assertEqual(decay_evs[0]["kind"], "epistemic_decay")
            finally:
                ring.close()

    def test_02c_zero_numpy_native_simd_vsa_bit_exact_and_supervisor_radar(self) -> None:
        from chimera_tp import native as _native
        from chimera_tp.platform.agent_symbiont import ReleasePromoteEngine

        # Bit-exact parity between native SIMD POPCNT encoder/batch and pure-Python fallback
        sample = "chimera dynamo kv prefill router effort invariant svhome"
        v_fast = _native.vsa_encode_10k_fast(sample, out_bytes=1252)
        v_py = _native._vsa_encode_10k_py(sample, out_bytes=1252)
        self.assertEqual(len(v_fast), 1252)
        self.assertEqual(v_fast, v_py)

        v2 = _native.vsa_encode_10k_fast("another document about autocad gpu lease", out_bytes=1252)
        mat = v_fast + v2
        dists = _native.vsa_hamming_batch_fast(v_fast, mat, rows=2, bytes_per_row=1252)
        self.assertEqual(dists[0], 0)
        self.assertGreater(dists[1], 1000)

        # Supervisor-Truth Radar returns None or a real directory without spawning errors
        sup = ReleasePromoteEngine.detect_supervisor_target_dir()
        if sup is not None:
            self.assertTrue(Path(sup).is_dir())

    def test_03_fractal_recall_ingests_thought_briefs_and_ranks_correctly(self) -> None:
        syn = aeon.ChronoSynapseEngine(ephemeral=True)
        with tempfile.TemporaryDirectory(prefix="chimera_tb_") as td:
            db = Path(td) / "thought-briefs.sqlite"
            con = sqlite3.connect(str(db))
            con.execute(
                "CREATE TABLE thought_briefs ("
                "id TEXT PRIMARY KEY, topic_key TEXT, brief_text TEXT, "
                "duration_ms INTEGER, reasoning_bytes INTEGER, created_at REAL)"
            )
            con.execute(
                "INSERT INTO thought_briefs VALUES (?, ?, ?, ?, ?, ?)",
                ("b1", "kv_cache", "Never mutate reasoning.effort mid-session or OpenAI KV prefix resets", 120000, 180000, 100.0),
            )
            con.execute(
                "INSERT INTO thought_briefs VALUES (?, ?, ?, ?, ?, ?)",
                ("b2", "svhome_tmp", "Always pass TMPDIR=/mnt/chimera-dev/tmp on svhome to avoid /tmp EDQUOT", 45000, 90000, 101.0),
            )
            con.commit()
            con.close()

            ing = syn.ingest_tquota_thought_briefs(db_paths=[db], max_rows=50)
            self.assertTrue(ing["ok"])
            self.assertEqual(ing["ingested"], 2)

            rec = syn.fractal_recall("svhome EDQUOT TMPDIR disk quota", top_k=2, use_gpu=False)
            self.assertTrue(rec["ok"])
            self.assertEqual(rec["memories_scanned"], 2)
            self.assertGreaterEqual(len(rec["hits"]), 1)
            self.assertEqual(rec["hits"][0]["mem_id"], "tb_b2")

    def test_04_green_ptx_real_gtx1650_vsa_popc_and_es_axpy_bit_exact(self) -> None:
        ptx = NvCudaPtxEngine()
        probe = ptx.probe()
        if not probe.get("available"):
            self.skipTest("No NVIDIA CUDA driver on this host (CPU-only node)")

        # 1) Hardware xor.b32 + popc.b32 10K-bit VSA Hamming batch + 5s Focus-Hooked Green-Context Micro-Lease
        core = aeon.AeonDynamoCore(ephemeral=True)
        try:
            bench = core.benchmark_green_ptx_vsa(rows=2048)
            self.assertTrue(bench["ok"])
            self.assertTrue(bench["zero_numpy_daemon"])
            gpu = bench["green_ptx_gpu"]
            self.assertTrue(gpu["available"])
            self.assertTrue(gpu["bit_exact_match_vs_cpu"])
            self.assertTrue(gpu["lease_reused"])
            self.assertGreater(gpu["lease_total_speedup"], 2.0)
            self.assertEqual(gpu["vram_retained_mb"], 0.0)
            self.assertGreater(gpu["kernel_ms"], 0.0)
        finally:
            core.close()

        # 2) Hardware fma.rn.f32 ES AXPY kernel parity vs CPU
        theta = [0.5 * i - 10.0 for i in range(1024)]
        eps = [((i * 17) % 13 - 6) * 0.1 for i in range(1024)]
        scale = 0.08
        ax = ptx.run_es_axpy_kernel(theta, eps, scale)
        self.assertTrue(ax["ok"])
        self.assertEqual(ax["vram_retained_mb"], 0.0)
        self.assertEqual(len(ax["out"]), 1024)
        for i in range(0, 1024, 31):
            expected = theta[i] + scale * eps[i]
            self.assertAlmostEqual(ax["out"][i], expected, places=4)

    def test_05_eagle_action_paste_markov_and_sptc_partial_preexec(self) -> None:
        eagle = aeon.EagleActionSpeculator()
        eagle.observe_action("codex", "atomic_patch", "foo.py")
        eagle.observe_action("codex", "commit_verify", "foo.py")
        preds = eagle.predict_next("atomic_patch", "bar.py", top_k=2)
        self.assertGreaterEqual(len(preds), 1)
        self.assertGreater(preds[0]["prob"], 0.0)

        with tempfile.TemporaryDirectory(prefix="chimera_sptc_") as td:
            repo = Path(td)
            fp = repo / "sample.py"
            fp.write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
            partial = f'{{"Path":"{fp.as_posix()}","StartLine":1'  # Deliberately truncated streaming JSON!
            sp = eagle.speculate_from_partial_args(repo=repo, tool_name="read_file", partial_args=partial)
            self.assertTrue(sp["ok"])
            self.assertEqual(sp["paths_detected"], 1)
            self.assertTrue(sp["precomputed"][0]["syntax_ok"])

            ckey = sp["precomputed"][0]["cache_key"]
            hit = eagle.lookup(ckey)
            self.assertIsNotNone(hit)
            assert hit is not None
            self.assertTrue(hit["speculative_exec_hit"])
            self.assertTrue(hit["syntax_ok"])

    def test_06_homeostasis_8d_and_dgm_4_oracle_rejects_broken_promotes_fast(self) -> None:
        core = aeon.AeonDynamoCore(ephemeral=True)
        # Use unreachable dummy port so test is 100% deterministic offline without external deps
        h = core.homeostasis.sample(tquota_base="http://127.0.0.1:1")
        self.assertTrue(h["ok"])
        self.assertEqual(len(h["vector_8d"]), 8)
        self.assertFalse(h["controls"]["effort_mutation_allowed"])
        self.assertTrue(h["law7_rss_ok"])

        dgm = core.dgm.run_evolution_step(min_speedup_pct=10.0, tquota_base="http://127.0.0.1:1")
        self.assertTrue(dgm["ok"])
        self.assertEqual(dgm["mode"], "shadow_only")
        self.assertFalse(dgm["auto_activated"])
        broken = next(e for e in dgm["evaluated"] if e["variant"] == "mutant_broken_shortcut")
        fast = next(e for e in dgm["evaluated"] if e["variant"] == "mutant_fast_reject_precompile")
        self.assertFalse(broken["oracles"]["o1_tests_100pct"])
        self.assertFalse(broken["all_4_oracles_passed"])
        self.assertTrue(fast["oracles"]["o1_tests_100pct"])
        self.assertTrue(fast["oracles"]["o2_quota_invariant"])
        self.assertTrue(fast["oracles"]["o3_law7_rss_lt80mb"])
        self.assertGreater(fast["speedup_pct"], 10.0)
        self.assertTrue(fast["all_4_oracles_passed"])
        self.assertIsNotNone(dgm["shadow_winner"])

    def test_07_lazy_load_zero_boot_ram_and_mcp_41_tools(self) -> None:
        bus = AgentHyperBus(ephemeral=True)
        try:
            self.assertIsNone(bus.symbiont._aeon)
            st = bus.symbiont.aeon.status()
            self.assertTrue(st["ok"])
            self.assertTrue(st["lazy_loaded"])
            self.assertFalse(st["effort_mutation_allowed"])
            self.assertIsNotNone(bus.symbiont._aeon)
        finally:
            bus.verifier.close()

        names = [t["name"] for t in _TOOLS]
        self.assertGreaterEqual(len(names), 43)
        self.assertIn("chimera_aeon", names)
        self.assertIn("chimera_noosphere", names)
        self.assertIn("chimera_eidolon", names)

        resp = handle_mcp_request(
            {
                "jsonrpc": "2.0",
                "id": 141,
                "method": "tools/call",
                "params": {"name": "chimera_aeon", "arguments": {"action": "status"}},
            }
        )
        self.assertIsNotNone(resp)
        assert resp is not None
        body = json.loads(resp["result"]["content"][0]["text"])
        self.assertTrue(body["ok"])

    def test_08_gemini_prism_homeostasis_and_quota_oracle(self) -> None:
        core = aeon.AeonDynamoCore(ephemeral=True)
        try:
            h = core.homeostasis.sample(tquota_base="http://127.0.0.1:1")
            self.assertIn("gemini_prism", h)
            self.assertFalse(h["gemini_prism"]["effort_mutation_allowed"])
            self.assertIn("gemini_keepalive_allowed", h["controls"])

            oracle = core.dispatch(
                "prism_quota_oracle",
                prompt_tokens=200_000,
                prev_cached_tokens=190_000,
                idle_ms=280_000,
            )
            self.assertTrue(oracle["ok"])
            self.assertFalse(oracle["effort_mutation_allowed"])
            self.assertEqual(oracle["predicted_uncached_tokens"], 10_000)
            self.assertFalse(oracle["cache_cold"])
            self.assertAlmostEqual(oracle["predicted_weekly_pct"], round((10_000 / 3_700_000.0) * 100.0, 4), places=4)

            pstatus = core.dispatch("prism_status", tquota_base="http://127.0.0.1:1")
            self.assertTrue(pstatus["ok"])
            self.assertFalse(pstatus["effort_mutation_allowed"])
        finally:
            core.close()

    def test_09_chimera_nexus_hippo_ppr_turn0_crystal_chrono_fork_and_reality_twin(self) -> None:
        core = aeon.AeonDynamoCore(ephemeral=True)
        try:
            with tempfile.TemporaryDirectory(prefix="chimera_nexus_") as td:
                repo = Path(td)
                helper = repo / "helper.py"
                entry = repo / "entry.py"
                helper.write_text("def compute_kv_budget(n):\n    return n * 2\n", encoding="utf-8")
                entry.write_text("from .helper import compute_kv_budget\ndef main():\n    return compute_kv_budget(10)\n", encoding="utf-8")

                # 1. Seed 2 connected facts + 1 thought brief linked via shared entity `phantom_prefix`
                core.synapse.record_fact(
                    repo=repo,
                    file_path="entry.py",
                    symbol="main",
                    fact_text="entry.py triggers phantom_prefix reconciliation on warm sessions.",
                    surprise_score=8.0,
                )
                core.synapse.record_fact(
                    repo=repo,
                    file_path="helper.py",
                    symbol="compute_kv_budget",
                    fact_text="phantom_prefix relies on svhome_xfs_cow snapshot budget.",
                    surprise_score=8.5,
                )

                # HippoRAG 2 PPR multi-hop recall: querying `entry.py` bridges via `phantom_prefix` to `svhome_xfs_cow`!
                ppr = core.dispatch("hippo_ppr_recall", query="entry.py main warm sessions", top_k=5)
                self.assertTrue(ppr["ok"])
                self.assertGreater(ppr["graph_edges"], 0)
                self.assertGreaterEqual(len(ppr["hits"]), 2)

                # Turn-0 Immortal Seed Crystal
                crys = core.dispatch("turn0_crystal", repo=str(repo), query="phantom_prefix svhome_xfs_cow", max_tokens=500)
                self.assertTrue(crys["ok"])
                self.assertIn("<chimera_turn0_crystal>", crys["crystal"])
                self.assertGreaterEqual(crys["facts_included"], 2)
                self.assertLessEqual(crys["estimated_tokens"], 520)

                # Chrono-Fork 2-hop bundle
                cf = core.dispatch("chrono_fork", repo=str(repo), file_path="entry.py", symbol="main")
                self.assertTrue(cf["ok"])
                self.assertEqual(cf["siblings_indexed"], 1)
                self.assertIn("compute_kv_budget", cf["bundle"])

                # Reality Twin zero-token mechanical syntax healer (JSON trailing comma + Python missing colon)
                bad_json = core.dispatch("reality_twin_check", repo=str(repo), file_path="cfg.json", text='{"a": 1, "b": 2,}')
                self.assertTrue(bad_json["ok"])
                self.assertFalse(bad_json["clean"])
                self.assertTrue(bad_json["zero_token_fix_available"])
                self.assertFalse(bad_json["auto_applied"])

                bad_py = core.dispatch("reality_twin_check", repo=str(repo), file_path="broken.py", text="def broken(x)\n    return x + 1\n")
                self.assertTrue(bad_py["ok"])
                self.assertFalse(bad_py["clean"])
                self.assertTrue(bad_py["zero_token_fix_available"])

                # Nexus status & Homeostasis integration
                ns = core.dispatch("nexus_status", tquota_base="http://127.0.0.1:1")
                self.assertTrue(ns["ok"])
                self.assertFalse(ns["effort_mutation_allowed"])
                self.assertEqual(ns["reality_twin"]["mechanical_fixes_found"], 2)
        finally:
            core.close()


if __name__ == "__main__":
    unittest.main()
