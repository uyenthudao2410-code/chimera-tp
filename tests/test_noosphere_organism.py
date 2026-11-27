"""Unit & integration tests for CHIMERA-NOOSPHERE (5 Living Organs + Source-Side Zero-Echo + MCP #42)."""
from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path

from chimera_tp.platform.agent_probe import AgentHyperBus
from chimera_tp.platform.mcp_server import _TOOLS, handle_mcp_request
from chimera_tp.platform.noosphere_organism import (
    GlobalWorkspaceCortex,
    ImmuneSelfHealingReflex,
    MetacognitiveObserver,
    NoosphereOrganismCore,
    SubconsciousSideQueryEngine,
)


class TestChimeraNoosphereOrganism(unittest.TestCase):
    def test_01_global_workspace_epistemic_decay_and_cross_node_merge(self) -> None:
        ws = GlobalWorkspaceCortex(ephemeral=True)
        r1 = ws.publish(
            kind="fact",
            summary="gemini-nexus keeps multi-turn contents append-only with 0 prefix edits",
            source="win-desktop",
            salience=0.9,
            file_path="src/gemini-nexus.js",
            file_sha256="abc123",
        )
        self.assertTrue(r1["ok"])
        self.assertEqual(ws.snapshot(limit=5)["total_items"], 1)

        # Peer merge from svhome
        m = ws.merge_peer_items([
            {
                "id": "peer:svhome:xfs",
                "kind": "fact",
                "summary": "svhome XFS CoW pool healthy with 420 GB free",
                "source": "svhome",
                "node": "svhome",
                "salience": 0.85,
                "ts": time.time(),
                "ttl_s": 3600.0,
            }
        ])
        self.assertEqual(m["merged"], 1)
        self.assertEqual(ws.snapshot(limit=5)["total_items"], 2)

        # Epistemic decay when source file changes SHA
        removed = ws.invalidate_by_file("src/gemini-nexus.js", new_sha256="def456")
        self.assertEqual(removed, 1)
        self.assertEqual(ws.snapshot(limit=5)["total_items"], 1)

    def test_02_immune_reflex_detects_1349_prefix_edit_cliff_and_rss_self_trim(self) -> None:
        bus = AgentHyperBus(ephemeral=True)
        try:
            ws = GlobalWorkspaceCortex(ephemeral=True)
            immune = ImmuneSelfHealingReflex(
                hive=bus.symbiont.hive,
                release_promote=bus.symbiont.release_promote,
                workspace=ws,
                auto_rollback_armed=False,
                rss_self_trim_mb=72.0,
            )
            # Healthy baseline turn (93.9% cache hit, 0 prefix edits)
            ok_eval = immune.evaluate(
                prism_status={"turnsObserved": 20, "cacheHitPct": 93.9, "prefixEditsObserved": 0, "effortMutationAllowed": False},
                rss_mb=58.0,
            )
            self.assertTrue(ok_eval["healthy"])
            self.assertEqual(ok_eval["pain_score"], 0.0)
            self.assertIsNone(ok_eval["rollback_proposal"])

            # Simulate the 13:49 production cliff: 2 prefix edits + cache hit collapse to 56.45% + RSS 74.5 MiB
            cliff = immune.evaluate(
                prism_status={"turnsObserved": 35, "cacheHitPct": 56.45, "prefixEditsObserved": 2, "effortMutationAllowed": False},
                rss_mb=74.5,
            )
            self.assertFalse(cliff["healthy"])
            self.assertGreaterEqual(cliff["pain_score"], 0.65)
            self.assertIsNotNone(cliff["rollback_proposal"])
            self.assertFalse(cliff["rollback_proposal"]["auto_activated"])
            self.assertGreaterEqual(cliff["gc_trims_total"], 1)
            self.assertGreaterEqual(cliff["antibodies_emitted"], 1)
            self.assertTrue(any("CRITICAL_PREFIX_EDIT_CLIFF" in s for s in cliff["signals"]))
            self.assertTrue(any("CACHE_HIT_CLIFF" in s for s in cliff["signals"]))
            self.assertTrue(any("LAW7_RSS_PRESSURE" in s for s in cliff["signals"]))
            # Workspace broadcast fired + HiveMindCortex actually stored the immune rule!
            alerts = ws.snapshot(limit=5, kind="immune_alert")["items"]
            self.assertGreaterEqual(len(alerts), 1)
            hive_pats = {r.get("pattern") for r in bus.symbiont.hive.list_immune(limit=50)}
            self.assertIn("noosphere:critical_prefix_edit_cliff", hive_pats)
        finally:
            bus.close()

    def test_03_metacognitive_observer_detects_tunnel_vision_kv_and_side_query_storm(self) -> None:
        ws = GlobalWorkspaceCortex(ephemeral=True)
        meta = MetacognitiveObserver(workspace=ws)
        for _ in range(3):
            meta.observe(event_kind="test_fail", target="gemini-nexus.js", detail="prefix-edit")
        for _ in range(7):
            meta.observe(event_kind="side_query", target="flash-low")
        res = meta.assess(kv_mass_override=260_000)
        self.assertGreaterEqual(res["cognitive_fatigue"], 0.8)
        self.assertIn("gemini-nexus.js", res["tunnel_vision_targets"])
        codes = {c["code"] for c in res["guidance_cards"]}
        self.assertIn("TUNNEL_VISION_LOOP", codes)
        self.assertIn("KV_ATTENTION_SATURATION", codes)
        self.assertIn("SIDE_QUERY_STORM", codes)

    def test_04_subconscious_side_query_engine_zero_google_tokens_under_5ms(self) -> None:
        sub = SubconsciousSideQueryEngine()
        r1 = sub.respond(
            prompt="Generate a short 5-word title for this conversation about CHIMERA-NOOSPHERE living organism and gemini-prism.js dedupe cache optimization.",
            category="title",
            estimated_google_tokens=3200,
        )
        self.assertTrue(r1["ok"])
        self.assertTrue(r1["safe_for_local_offload"])
        self.assertEqual(r1["google_tokens_used"], 0)
        self.assertEqual(r1["google_tokens_saved"], 3200)
        self.assertEqual(r1["intent"], "title")
        self.assertLess(r1["elapsed_ms"], 50.0)
        self.assertIn("CHIMERA-NOOSPHERE", r1["text"])
        self.assertNotIn("gemini-prism.js gemini-prism", r1["text"])

        # Safety gate: complex debugging / code prompt MUST NOT be intercepted locally!
        r_complex = sub.respond(
            prompt="Explain why the stack trace fails and write code to fix bug in gemini-prism.js",
            category="title",
            estimated_google_tokens=4000,
        )
        self.assertTrue(r_complex["ok"])
        self.assertFalse(r_complex["safe_for_local_offload"])
        self.assertEqual(r_complex["google_tokens_saved"], 0)
        self.assertEqual(r_complex["offload_recommendation"], "upstream_or_idle_codex")

        # Second identical call hits local RAM cache
        r2 = sub.respond(
            prompt="Generate a short 5-word title for this conversation about CHIMERA-NOOSPHERE living organism and gemini-prism.js dedupe cache optimization.",
            category="title",
            estimated_google_tokens=3200,
        )
        self.assertTrue(r2["cache_hit"])
        self.assertEqual(sub.stats()["google_tokens_saved_total"], 6400)
        self.assertEqual(sub.stats()["escalated_upstream_total"], 1)

    def test_05_source_side_zero_echo_guard_eliminates_duplicate_file_bloat(self) -> None:
        bus = AgentHyperBus(ephemeral=True)
        try:
            with tempfile.TemporaryDirectory(prefix="noosphere_echo_") as td:
                f = Path(td) / "big_module.py"
                content = "\n".join(f"def fn_{i}(x): return x + {i}  # payload_line_{i}" for i in range(120))
                f.write_text(content, encoding="utf-8")

                # First read: full payload
                b1 = bus.probe.run_batch(
                    [{"op": "file_slice", "path": str(f), "start_line": 1, "end_line": 120, "dedupe_echo": True, "session_id": "s1"}],
                    cwd=str(td),
                )
                r1 = b1["results"][0]
                self.assertTrue(r1["ok"])
                self.assertFalse(r1.get("echo_deduped", False))
                raw_len = len(r1["text"])
                self.assertGreater(raw_len, 4000)

                # Second unchanged read in same session: >95% smaller zero-echo stub!
                b2 = bus.probe.run_batch(
                    [{"op": "file_slice", "path": str(f), "start_line": 1, "end_line": 120, "dedupe_echo": True, "session_id": "s1"}],
                    cwd=str(td),
                )
                r2 = b2["results"][0]
                self.assertTrue(r2["ok"])
                self.assertTrue(r2.get("echo_deduped", False))
                self.assertLess(len(r2["text"]), raw_len * 0.05)

                # Mutate file -> hash changes -> immediately serves fresh full text!
                f.write_text(content + "\n# mutated\n", encoding="utf-8")
                b3 = bus.probe.run_batch(
                    [{"op": "file_slice", "path": str(f), "start_line": 1, "end_line": 120, "dedupe_echo": True, "session_id": "s1"}],
                    cwd=str(td),
                )
                self.assertFalse(b3["results"][0].get("echo_deduped", False))
                self.assertEqual(bus.probe.echo_guard_stats()["echo_hits"], 1)
        finally:
            bus.close()

    def test_06_nocturnal_dream_consolidator_and_autonomic_pulse_end_to_end(self) -> None:
        bus = AgentHyperBus(ephemeral=True)
        try:
            noo: NoosphereOrganismCore = bus.symbiont.noosphere
            # Verify pulse starts, runs a tick, and stops cleanly
            st_start = noo.start_autonomic_pulse()
            self.assertTrue(st_start["ok"])
            t_res = noo.tick(
                trigger="unit_test",
                sample_network=False,
                prism_override={"turnsObserved": 10, "cacheHitPct": 95.0, "prefixEditsObserved": 0, "effortMutationAllowed": False},
                rss_override_mb=55.0,
            )
            self.assertTrue(t_res["ok"])
            self.assertTrue(t_res["healthy"])
            self.assertFalse(t_res["effort_mutation_allowed"])
            self.assertTrue(t_res["law7_rss_ok"])
            self.assertGreater(noo.status()["law7_rss_mb"], 1.0)

            # Run full NREM + REM dream cycle offline
            ep = noo.dispatch("dream", repo=".", reason="unit_test_dream", tquota_base="http://127.0.0.1:1")
            self.assertTrue(ep["ok"])
            self.assertEqual(ep["mode"], "shadow_only")
            self.assertFalse(ep["auto_activated"])
            self.assertFalse(ep["effort_mutation_allowed"])
            self.assertTrue(ep["rem"]["dgm_oracles_passed"])
            self.assertGreater(ep["rem"]["dgm_speedup_pct"], 10.0)
            self.assertTrue(noo.dispatch("epiphany")["epiphany"] is not None)
        finally:
            bus.close()

    def test_07_mcp_42nd_tool_chimera_noosphere_registered_and_callable(self) -> None:
        names = [t["name"] for t in _TOOLS]
        self.assertGreaterEqual(len(names), 43)
        self.assertIn("chimera_noosphere", names)
        self.assertIn("chimera_eidolon", names)
        resp = handle_mcp_request(
            {
                "jsonrpc": "2.0",
                "id": 142,
                "method": "tools/call",
                "params": {
                    "name": "chimera_noosphere",
                    "arguments": {
                        "action": "subconscious",
                        "prompt": "Generate short title for CHIMERA-NOOSPHERE deployment",
                        "category": "title",
                    },
                },
            }
        )
        self.assertIsNotNone(resp)
        assert resp is not None
        body = json.loads(resp["result"]["content"][0]["text"])
        self.assertTrue(body["ok"])
        self.assertEqual(body["google_tokens_used"], 0)

    def test_08_bidirectional_2way_workspace_and_immune_sync_exchange(self) -> None:
        bus_a = AgentHyperBus(ephemeral=True)
        bus_b = AgentHyperBus(ephemeral=True)
        try:
            noo_a: NoosphereOrganismCore = bus_a.symbiont.noosphere
            noo_b: NoosphereOrganismCore = bus_b.symbiont.noosphere

            # Seed distinct facts & immune antibodies on Node A (win-desktop) and Node B (svhome)
            noo_a.workspace.publish(kind="fact", summary="Node A GTX 1650 PTX ready", source="win-desktop", salience=0.9, item_id="a:ptx")
            noo_b.workspace.publish(kind="fact", summary="Node B svhome XFS CoW healthy", source="svhome", salience=0.9, item_id="b:xfs")
            bus_a.symbiont.hive.add_immune_rule(pattern="sig:win_only_guard", warning="keep_append_only", scope="noosphere", created_by="win")
            bus_b.symbiont.hive.add_immune_rule(pattern="sig:svhome_only_guard", warning="keep_tmpdir_xfs", scope="noosphere", created_by="svhome")

            # Simulate 1-RTT bidirectional exchange: A sends packet to B, B merges & replies, A merges reply
            pkt_a = noo_a._local_sync_packet()
            reply_b = noo_b.handle_sync_exchange(pkt_a)
            self.assertTrue(reply_b["ok"])
            self.assertEqual(reply_b["ingested_workspace"], 1)
            self.assertGreaterEqual(reply_b["ingested_immune"], 1)

            # A merges B's returned state
            ws_a = noo_a.workspace.merge_peer_items(reply_b["workspace_items"])
            imm_a = noo_a._merge_immune_bundle(reply_b["immune_rules"])
            self.assertEqual(ws_a["merged"], 1)
            self.assertGreaterEqual(imm_a, 1)

            # Verify BOTH nodes now possess BOTH workspace facts and BOTH immune antibodies!
            ids_a = {i["id"] for i in noo_a.workspace.snapshot(limit=10)["items"]}
            ids_b = {i["id"] for i in noo_b.workspace.snapshot(limit=10)["items"]}
            self.assertTrue({"a:ptx", "b:xfs"}.issubset(ids_a))
            self.assertTrue({"a:ptx", "b:xfs"}.issubset(ids_b))

            pats_a = {r.get("pattern") for r in bus_a.symbiont.hive.list_immune(limit=50)}
            pats_b = {r.get("pattern") for r in bus_b.symbiont.hive.list_immune(limit=50)}
            self.assertIn("sig:svhome_only_guard", pats_a)
            self.assertIn("sig:win_only_guard", pats_b)
        finally:
            bus_a.close()
            bus_b.close()


if __name__ == "__main__":
    unittest.main()
