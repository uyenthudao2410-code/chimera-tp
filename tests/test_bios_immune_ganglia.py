"""Thorough test suite for CHIMERA-BIOS Ideas #4, #5, and #6:
- Idea #4: CHIMERA-PARASITE (Red-Queen Adversarial Self-Play Arena)
- Idea #5: CHIMERA-OCTOPUS (Autonomous Peripheral Reflex Ganglia & Merkle-CRDT Reconciler)
- Idea #6: CHIMERA-STIGMERGY & EPIGENOME (Invisible Pheromone Skin & Methylation)
"""
from __future__ import annotations

import hashlib
import random
import tempfile
import time
import unittest
from pathlib import Path

from chimera_tp.platform.bios.octopus import (
    BinaryReflexTable,
    HookGanglion,
    OctopusNervousSystem,
    PeerSurvivalGanglion,
    SocketGanglion,
    SynapticReconciler,
)
from chimera_tp.platform.bios.parasite import (
    PARASITE_SCENARIOS,
    RedQueenParasiteArena,
)
from chimera_tp.platform.bios.stigmergy import StigmergicEpigenome


class TestChimeraParasiteArena(unittest.TestCase):
    def test_all_six_scenarios_defined(self) -> None:
        expected = {
            "packet_loss_storm",
            "steer_503_race",
            "file_lease_deadlock",
            "prefix_cache_cliff",
            "rss_ceiling_squeeze",
            "secret_egress_smuggle",
        }
        self.assertEqual(set(PARASITE_SCENARIOS.keys()), expected)

    def test_red_queen_arena_sandbox_and_law6_vaccines_ephemeral(self) -> None:
        with RedQueenParasiteArena(ephemeral=True) as arena:
            res = arena.run_arena(rounds=6, seed=42)
            self.assertTrue(res["ok"])
            self.assertTrue(res["sandbox_isolated"])
            self.assertFalse(res["auto_activated"])
            self.assertTrue(res["requires_human_approval"])
            self.assertEqual(res["rounds_executed"], 6)
            self.assertEqual(res["generation"], 6)
            self.assertGreaterEqual(res["vaccines_synthesized"], 3)

            # Every synthesized vaccine must strictly enforce Law 6 and pass SHA-256 + replay verification
            for vac in res["vaccines"]:
                self.assertFalse(vac["auto_activated"])
                self.assertTrue(vac["requires_human_approval"])
                self.assertEqual(len(vac["sha256"]), 64)
                ab = vac["immune_antibody"]
                self.assertTrue(ab["error_sig"])
                self.assertTrue(ab["fix_hint"])
                self.assertIn(ab["severity"], ("low", "medium", "high", "critical"))
                self.assertIn("def test_vaccine_", vac["regression_test_snippet"])
                self.assertTrue(vac["host_hardening_delta"])

                check = arena.verify_vaccine(vac)
                self.assertTrue(check["signature_valid"], f"Invalid signature for {vac['scenario']}")
                self.assertTrue(check["law6_compliant"], f"Law 6 violated for {vac['scenario']}")
                self.assertTrue(check["valid"], f"Vaccine failed sandbox mitigation: {vac['scenario']} -> {check}")

            # Tampering with vaccine receipt must fail SHA-256 signature verification
            tampered = dict(res["vaccines"][0])
            tampered["auto_activated"] = True
            t_check = arena.verify_vaccine(tampered)
            self.assertFalse(t_check["valid"])
            self.assertFalse(t_check["signature_valid"])
            self.assertFalse(t_check["law6_compliant"])

            # Red-Queen adaptation: later round survival should recover vs initial breach round
            self.assertGreaterEqual(res["final_host_survival_rate"], res["rounds"][0]["host_survival_rate"])

            st = arena.status()
            self.assertEqual(st["generation"], 6)
            self.assertEqual(st["vaccines_synthesized"], len(arena.list_vaccines()))
            self.assertGreater(len(arena.list_antibodies()), 0)

    def test_red_queen_sqlite_wal_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ops = Path(td)
            with RedQueenParasiteArena(ops_dir=ops, ephemeral=False) as arena1:
                r1 = arena1.run_arena(rounds=3, seed=7)
                v_count = r1["vaccines_synthesized"]
                self.assertGreater(v_count, 0)

            with RedQueenParasiteArena(ops_dir=ops, ephemeral=False) as arena2:
                st = arena2.status()
                self.assertEqual(st["generation"], 3)
                self.assertEqual(st["vaccines_synthesized"], v_count)
                r2 = arena2.run_arena(rounds=2, seed=8)
                self.assertEqual(r2["generation"], 5)


class TestChimeraOctopusGanglia(unittest.TestCase):
    def test_binary_reflex_table_sub_ms_offline_lookup_and_size_bound(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            table_path = Path(td) / "octopus_reflex.bin"
            # Writer (daemon online) populates antibodies, endpoints, and hormone snapshot, then closes (daemon offline!)
            with BinaryReflexTable(table_path, ephemeral=False) as writer:
                sync_res = writer.sync(
                    antibodies=[
                        {
                            "pattern": "secret_egress_bypass",
                            "fix_hint": "Block obfuscated token before outbound socket",
                            "severity": "critical",
                            "action": "block",
                        },
                        {
                            "pattern": "prefix_cache_cliff",
                            "fix_hint": "Hoist volatile timestamp to tail",
                            "severity": "high",
                            "action": "warn",
                        },
                    ],
                    endpoints=[
                        {"name": "immortal_local", "host": "127.0.0.1", "port": 12500, "role": "primary", "state": "healthy"},
                        {"name": "svhome_peer", "host": "svhome.local", "port": 9780, "role": "peer_svhome", "state": "healthy"},
                    ],
                    hormones={
                        "adrenaline": 0.42,
                        "cortisol": 0.25,
                        "dopamine": 0.71,
                        "melatonin": 0.10,
                        "cytokine": 0.30,
                        "oxytocin": 0.88,
                    },
                    flags=0,  # daemon offline
                )
                self.assertTrue(sync_res["ok"])
                self.assertLess(writer.byte_size(), 16384)
                self.assertLess(sync_res["used_bytes"], 16384)

            # External process opens BinaryReflexTable read-only with ZERO HTTP while daemon is dead
            with BinaryReflexTable(table_path, ephemeral=False, read_only=True) as reader:
                self.assertLess(reader.byte_size(), 16384)
                hook = HookGanglion(reader)
                # Warm once, then benchmark 50 offline reflex lookups to prove < 1 ms latency
                r_block = hook.evaluate("egress_send", "payload triggers secret_egress_bypass", daemon_online=False)
                self.assertEqual(r_block["decision"], "block")
                self.assertFalse(r_block["allowed"])
                self.assertTrue(r_block["offline_autonomous"])
                self.assertAlmostEqual(r_block["hormone_context"]["dopamine"], 0.71, places=3)

                dummy_gh_tok = "ghp_" + "1234567890" + "ABCDEFGHIJKLMN"
                r_spinal = hook.evaluate_pre_write("src/auth.py", f"token = '{dummy_gh_tok}'", daemon_online=False)
                self.assertEqual(r_spinal["decision"], "block")
                self.assertEqual(r_spinal["matched_rule"], "spinal:secret_raw_leak")

                t0 = time.perf_counter()
                for _ in range(50):
                    ev = hook.evaluate("edit_file", "safe routine edit payload", target_path="src/app.py", daemon_online=False)
                    self.assertEqual(ev["decision"], "allow")
                avg_ms = ((time.perf_counter() - t0) * 1000.0) / 50.0
                self.assertLess(avg_ms, 1.0, f"Offline HookGanglion lookup exceeded 1 ms: {avg_ms:.4f} ms")

    def test_socket_ganglion_autonomous_failover_and_keepalive(self) -> None:
        table = BinaryReflexTable(ephemeral=True)
        sg = SocketGanglion(table, fail_threshold=2, keepalive_interval_s=10.0)

        r0 = sg.select_route("immortal_local")
        self.assertEqual(r0["selected"], "immortal_local")
        self.assertFalse(r0["failover_active"])

        # Two consecutive failures trip primary -> autonomous failover to svhome_peer
        sg.record_probe("immortal_local", False, error="ConnectionRefusedError")
        sg.record_probe("immortal_local", False, error="ConnectionRefusedError")
        r1 = sg.select_route("immortal_local")
        self.assertTrue(r1["ok"])
        self.assertEqual(r1["selected"], "svhome_peer")
        self.assertTrue(r1["failover_active"])

        # Table automatically updated for external offline processes
        ep = table.get_active_endpoint(("primary", "peer_svhome"))
        self.assertIsNotNone(ep)
        assert ep is not None
        self.assertIn(ep["name"], ("egress_local", "svhome_peer"))

        # SSE keepalive cadence
        k1 = sg.keepalive_tick(now_ts=1000.0)
        self.assertTrue(k1["due"])
        self.assertIn(": keepalive", k1["frame"])
        k2 = sg.keepalive_tick(now_ts=1005.0)
        self.assertFalse(k2["due"])
        k3 = sg.keepalive_tick(now_ts=1011.0)
        self.assertTrue(k3["due"])

    def test_peer_survival_ganglion_island_mode_and_law3_fuses(self) -> None:
        pg = PeerSurvivalGanglion(node_name="svhome", peer_name="win-desktop", heartbeat_timeout_s=30.0)
        pg.record_peer_heartbeat("win-desktop", rtt_ms=5.2, now_ts=1000.0)
        c_ok = pg.check_link(now_ts=1010.0)
        self.assertFalse(c_ok["island_mode"])
        self.assertEqual(c_ok["budget_mode"], "symbiotic_connected")

        # Link loss after 45s -> autonomous island mode
        c_lost = pg.check_link(now_ts=1045.0)
        self.assertTrue(c_lost["island_mode"])
        self.assertEqual(c_lost["budget_mode"], "law3_island_protected")
        self.assertGreaterEqual(c_lost["buffered_events"], 1)

        # Law 3 hard fuses: light local task allowed when healthy, heavy job rejected in island mode
        adm_light = pg.admit_work(ram_free_gib=5.5, load1=0.6, cpu_temp_c=48.0, disk_free_gb=30.0, job_class="light")
        self.assertTrue(adm_light["admitted"])
        adm_heavy = pg.admit_work(ram_free_gib=5.5, load1=0.6, cpu_temp_c=48.0, disk_free_gb=30.0, job_class="heavy")
        self.assertFalse(adm_heavy["admitted"])
        self.assertIn("island_mode_rejects_heavy_job", adm_heavy["violations"])

        # Thermal/RAM fuse trips even for light jobs
        adm_hot = pg.admit_work(ram_free_gib=2.0, load1=2.1, cpu_temp_c=73.0, disk_free_gb=10.0, job_class="light")
        self.assertFalse(adm_hot["admitted"])
        self.assertEqual(len(adm_hot["violations"]), 4)

        # Buffer events during partition
        pg.append_event("health_tick", {"temp": 47.2}, key="svhome:temp", now_ts=1050.0)
        pg.append_event("antibody_seen", {"sig": "prefix_cliff"}, key="ab:prefix", now_ts=1055.0)
        self.assertGreaterEqual(len(pg.export_events()), 3)

    def test_synaptic_reconciler_order_independent_merkle_crdt(self) -> None:
        rec = SynapticReconciler()
        win_events = [
            rec.make_event("win-desktop", "state", {"v": 1}, hlc=(1700000001000, 0, "win-desktop"), key="route:egress"),
            rec.make_event("win-desktop", "vaccine", {"id": "vac-1"}, hlc=(1700000002000, 1, "win-desktop"), key="vac:1"),
            rec.make_event("win-desktop", "state", {"v": "win-new"}, hlc=(1700000005000, 0, "win-desktop"), key="shared:mode"),
        ]
        svh_events = [
            rec.make_event("svhome", "island", {"ok": True}, hlc=(1700000001500, 0, "svhome"), key="svhome:island"),
            rec.make_event("svhome", "state", {"v": "svh-newer"}, hlc=(1700000006000, 0, "svhome"), key="shared:mode"),
            win_events[0],  # duplicate shared event
        ]
        third_events = [
            rec.make_event("colab", "burst", {"cu": 1.2}, hlc=(1700000004000, 0, "colab"), key="colab:job1"),
        ]

        # Commutativity: reconcile(A, B) == reconcile(B, A)
        ab = rec.reconcile(win_events, svh_events)
        ba = rec.reconcile(svh_events, win_events)
        self.assertEqual(ab["root_hash"], ba["root_hash"])
        self.assertEqual(ab["merged_events"], ba["merged_events"])
        self.assertEqual(ab["resolved_kv"], ba["resolved_kv"])
        self.assertEqual(ab["total_events"], 5)  # 3 + 3 - 1 duplicate = 5, zero data loss!
        self.assertEqual(ab["common_count"], 1)
        self.assertEqual(ab["conflicts_resolved"], 1)
        # Higher HLC wins on conflicted key `shared:mode`
        self.assertEqual(ab["resolved_kv"]["shared:mode"]["payload"]["v"], "svh-newer")

        # Random input permutation invariance
        shuf_a = list(win_events)
        shuf_b = list(svh_events)
        rng = random.Random(99)
        rng.shuffle(shuf_a)
        rng.shuffle(shuf_b)
        shuf_merge = rec.reconcile(shuf_b, shuf_a)
        self.assertEqual(shuf_merge["root_hash"], ab["root_hash"])

        # Associativity: reconcile(reconcile(A, B), C) == reconcile(A, reconcile(B, C))
        ab_c = rec.reconcile(ab["merged_events"], third_events)
        bc = rec.reconcile(svh_events, third_events)
        a_bc = rec.reconcile(win_events, bc["merged_events"])
        self.assertEqual(ab_c["root_hash"], a_bc["root_hash"])
        self.assertEqual(ab_c["merged_events"], a_bc["merged_events"])

        # Idempotency: reconcile(M, M) == M
        idem = rec.reconcile(ab_c["merged_events"], ab_c["merged_events"])
        self.assertEqual(idem["root_hash"], ab_c["root_hash"])
        self.assertEqual(idem["total_events"], ab_c["total_events"])

    def test_octopus_unified_facade_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            with OctopusNervousSystem(ops_dir=td, node_name="win-desktop", ephemeral=False) as octo:
                octo.sync_reflexes(
                    antibodies=[{"pattern": "bad_op", "fix_hint": "stop", "severity": "high", "action": "block"}],
                    hormones={"adrenaline": 0.2, "cytokine": 0.1},
                    daemon_online=True,
                )
                ev = octo.evaluate_hook("shell", "run bad_op now")
                self.assertEqual(ev["decision"], "block")
                octo.peer_ganglion.append_event("local_note", {"n": 1}, key="k1")
                peer_ev = SynapticReconciler.make_event("svhome", "peer_note", {"n": 2}, key="k2")
                merged = octo.reconcile(peer_events=[peer_ev])
                self.assertEqual(merged["total_events"], 2)
                st = octo.status()
                self.assertEqual(st["organ"], "CHIMERA-OCTOPUS")
                self.assertLess(st["reflex_table"]["max_bytes"], 16384)


class TestChimeraStigmergicEpigenome(unittest.TestCase):
    def test_alarm_trail_methylation_and_zero_repo_file_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo_dir = Path(td) / "sample_repo"
            ops_dir = Path(td) / "ops"
            repo_dir.mkdir()
            target_file = repo_dir / "substrate.py"
            original_content = "# untouched repository file\nVALUE = 1\n"
            target_file.write_text(original_content, encoding="utf-8")
            orig_sha = hashlib.sha256(target_file.read_bytes()).hexdigest()

            t0 = 1_700_000_000.0
            with StigmergicEpigenome(ops_dir=ops_dir, ephemeral=False) as epi:
                # 1. Alarm pheromones (reinforcing noisy-OR)
                a1 = epi.deposit_alarm(str(repo_dir), "substrate.py", "regression", severity=0.5, reason="route timeout", agent_id="a1", now_ts=t0)
                a2 = epi.deposit_alarm(str(repo_dir), "substrate.py", "regression", severity=0.5, reason="repeat failure", agent_id="a2", now_ts=t0 + 10)
                self.assertAlmostEqual(a1["intensity"], 0.5, places=3)
                self.assertGreater(a2["intensity"], 0.70)
                self.assertEqual(a2["hit_count"], 2)

                # 2. Bidirectional Co-Edit Trail Graph
                epi.record_coedit(str(repo_dir), ["substrate.py", "client.py", "tests/test_substrate.py"], now_ts=t0)
                epi.record_coedit(str(repo_dir), ["substrate.py", "tests/test_substrate.py"], now_ts=t0 + 60)
                prefetch = epi.predict_trail_prefetch(str(repo_dir), "substrate.py", top_k=5, now_ts=t0 + 120)
                self.assertEqual(len(prefetch), 2)
                # Test file was co-edited twice, so it ranks #1 and is tagged is_test=True
                self.assertEqual(prefetch[0]["path"], "tests/test_substrate.py")
                self.assertTrue(prefetch[0]["is_test"])
                self.assertEqual(prefetch[1]["path"], "client.py")

                # Symmetry check: querying from client.py finds substrate.py
                rev_prefetch = epi.predict_trail_prefetch(str(repo_dir), "client.py", top_k=5, now_ts=t0 + 120)
                self.assertIn("substrate.py", [p["path"] for p in rev_prefetch])

                # 3. Epigenetic Methylation (file + directory prefix inheritance)
                epi.methylate(str(repo_dir), "substrate.py", "hard_lease", strength=0.9, half_life_days=7.0, reason="concurrent edit race", now_ts=t0)
                epi.methylate(str(repo_dir), "*", "extra_verify", strength=0.6, half_life_days=7.0, reason="release freeze", now_ts=t0)

                # 4. Smell-Card strictly < 40 tokens and < 5 ms
                card = epi.smell(str(repo_dir), "substrate.py", max_tokens=40, now_ts=t0 + 120)
                self.assertGreater(card["alarm_level"], 0.7)
                self.assertIn("hard_lease", card["methylation_flags"])
                self.assertIn("extra_verify", card["methylation_flags"])
                self.assertGreater(len(card["trail_companions"]), 0)
                self.assertTrue(card["advisory"])
                self.assertLess(card["token_est"], 40, f"Smell card exceeded 40 tokens: {card}")
                self.assertLess(card["elapsed_ms"], 5.0)

                # Tighter custom token cap (e.g. max_tokens=18) still respected strictly
                tight = epi.smell(str(repo_dir), "substrate.py", max_tokens=18, now_ts=t0 + 120)
                self.assertLess(tight["token_est"], 18)

                # Verify repository file remained 100% UNTOUCHED (zero modification!)
                self.assertEqual(hashlib.sha256(target_file.read_bytes()).hexdigest(), orig_sha)
                self.assertEqual(epi.status()["repo_files_modified"], 0)

    def test_exponential_half_life_evaporation_and_demethylation(self) -> None:
        t0 = 1_700_000_000.0
        with StigmergicEpigenome(ephemeral=True) as epi:
            epi.deposit_alarm("repo", "hot.py", "deadlock", severity=0.8, half_life_hours=24.0, now_ts=t0)
            epi.record_coedit("repo", ["hot.py", "peer.py"], weight=1.0, half_life_days=7.0, now_ts=t0)
            epi.methylate("repo", "hot.py", "require_ghost_bubble", strength=0.8, half_life_days=7.0, now_ts=t0)

            # After exactly 1 alarm half-life (24h): alarm ~ 0.40
            ev1 = epi.evaporate(now_ts=t0 + 24.0 * 3600.0)
            self.assertEqual(ev1["alarms_decayed"], 1)
            self.assertEqual(ev1["alarms_pruned"], 0)
            mid_card = epi.smell("repo", "hot.py", now_ts=t0 + 24.0 * 3600.0)
            self.assertAlmostEqual(mid_card["alarm_level"], 0.40, places=2)
            self.assertIn("require_ghost_bubble", mid_card["methylation_flags"])

            # After 60 calm days: alarms pruned, trails pruned, methylation marks cleanly demethylated
            ev2 = epi.evaporate(now_ts=t0 + 60.0 * 86400.0)
            self.assertEqual(ev2["alarms_pruned"], 1)
            self.assertEqual(ev2["trails_pruned"], 1)
            self.assertEqual(ev2["marks_demethylated"], 1)

            healed = epi.smell("repo", "hot.py", now_ts=t0 + 60.0 * 86400.0)
            self.assertEqual(healed["alarm_level"], 0.0)
            self.assertEqual(healed["methylation_flags"], [])
            self.assertEqual(healed["trail_companions"], [])
            self.assertEqual(healed["advisory"], "clear")

    def test_directory_prefix_methylation_and_crc_tamper_and_loopback_probe(self) -> None:
        import socket

        # 1. Directory prefix methylation inheritance in Stigmergy
        with StigmergicEpigenome(ephemeral=True) as epi:
            epi.methylate("repo", "chimera_tp/platform/", "require_ghost_bubble", strength=0.85)
            epi.methylate("repo", "chimera_tp/platform/substrate.py", "hard_lease", strength=0.9)
            card = epi.smell("repo", "chimera_tp/platform/substrate.py", max_tokens=40)
            self.assertIn("require_ghost_bubble", card["methylation_flags"])
            self.assertIn("hard_lease", card["methylation_flags"])
            self.assertLess(card["token_est"], 40)

        # 2. BinaryReflexTable CRC32 corruption detection
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "corrupt_reflex.bin"
            with BinaryReflexTable(p, ephemeral=False) as tbl:
                tbl.sync(antibodies=[{"pattern": "x", "fix_hint": "y", "severity": "high", "action": "block"}])
            raw = bytearray(p.read_bytes())
            raw[68] ^= 0xFF  # flip payload byte
            p.write_bytes(bytes(raw))
            with BinaryReflexTable(p, ephemeral=False, read_only=True) as rdr:
                with self.assertRaises(ValueError):
                    rdr.read_snapshot()

        # 3. Non-destructive real loopback TCP probe in SocketGanglion
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]
        try:
            with OctopusNervousSystem(ephemeral=True) as octo:
                octo.socket_ganglion.register_slot("loop_probe", "127.0.0.1", port, role="primary")
                p_ok = octo.socket_ganglion.probe_tcp("loop_probe", timeout_s=0.1)
                self.assertEqual(p_ok["state"], "healthy")
                srv.close()
                p_fail = octo.socket_ganglion.probe_tcp("loop_probe", timeout_s=0.1)
                self.assertIn(p_fail["state"], ("degraded", "down"))
        finally:
            try:
                srv.close()
            except Exception:
                pass

    def test_multi_seed_parasite_vaccine_mitigation(self) -> None:
        for seed in (1, 7, 19, 42, 99, 2026):
            with RedQueenParasiteArena(ephemeral=True) as arena:
                res = arena.run_arena(rounds=4, seed=seed)
                self.assertFalse(res["auto_activated"])
                self.assertGreaterEqual(res["vaccines_synthesized"], 1)
                for vac in res["vaccines"]:
                    chk = arena.verify_vaccine(vac)
                    self.assertTrue(chk["valid"], f"seed={seed} scenario={vac['scenario']} chk={chk}")


if __name__ == "__main__":
    unittest.main()
