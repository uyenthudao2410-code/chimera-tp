"""Tests for CHIMERA-HYPER v2.0 Autopilot, Dual-Stack RPC, ActiveQueryServer & Dashboard."""

from __future__ import annotations

import json
import socket
import tempfile
import unittest
import urllib.request
from pathlib import Path

from chimera_tp.active_pipe import ActiveQueryServer, ComputePlan, remote_active_query
from chimera_tp.autopilot import GENOMES, OpsConfig, TelemetryStore
from chimera_tp.dashboard import ChimeraDaemon
from chimera_tp.hyper_wire import HedgedRpcClient, HedgedRpcServer
from chimera_tp.native import chunk_superfeatures, delta_decode, delta_encode, fastcdc_split
from chimera_tp.probe import probe_environment


class TestChimeraV2Autopilot(unittest.TestCase):
    def test_probe_cross_platform_profile(self) -> None:
        env = probe_environment()
        self.assertEqual(len(env.topology_fingerprint), 64)
        self.assertGreaterEqual(len(env.realms), 2)

    def test_dual_stack_hedged_rpc_and_active_query_server(self) -> None:
        binds: list[tuple[str, int]] = [("127.0.0.1", 0)]
        try:
            probe_s = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
            probe_s.bind(("::1", 0))
            probe_s.close()
            binds.append(("::1", 0))
        except OSError:
            pass

        rpc_srv = HedgedRpcServer(binds, handler=lambda b: b"ECHO:" + b).start()
        try:
            cli = HedgedRpcClient(rpc_srv.addrs, hedge_delay_ms=0.0, retry_after_ms=100.0)
            try:
                body, ms, win = cli.call(b"dual-stack-test", timeout_s=3.0)
                self.assertEqual(body, b"ECHO:dual-stack-test")
                self.assertGreaterEqual(ms, 0.0)
                self.assertGreaterEqual(win, 0)
            finally:
                cli.close()
        finally:
            rpc_srv.close()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "allowed"
            root.mkdir()
            secret = Path(tmp) / "outside.log"
            secret.write_text("SECRET ERROR\n", encoding="utf-8")
            good = root / "app.log"
            lines = [f"2026 INFO ok {i}\n" for i in range(1500)]
            lines[10] = "2026 ERROR critical failure A\n"
            lines[500] = "2026 ERROR critical failure B\n"
            good.write_text("".join(lines), encoding="utf-8")

            qsrv = ActiveQueryServer("127.0.0.1", 0, allowed_roots=[root]).start()
            try:
                res, meta = remote_active_query(
                    qsrv.addr,
                    str(good),
                    ComputePlan(op="filter_lines", needle="ERROR"),
                )
                self.assertEqual(res.matched_records, 2)
                self.assertGreater(res.wire_reduction_pct, 95.0)
                self.assertIsNotNone(res.preview_first_ms)
                self.assertIn("critical failure", res.output_bytes.decode("utf-8"))

                with self.assertRaises(RuntimeError):
                    remote_active_query(
                        qsrv.addr,
                        str(secret),
                        ComputePlan(op="filter_lines", needle="ERROR"),
                    )
            finally:
                qsrv.close()

    def test_darwinian_ucb1_and_sqlite_store(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = TelemetryStore(Path(tmp) / "t.db")
            try:
                seen_genomes: set[str] = set()
                for idx in range(len(GENOMES)):
                    gid, params = store.select_genome("auto-darwin")
                    self.assertIn("gen_k", params)
                    seen_genomes.add(gid)
                    summary = {
                        "ts_utc": f"2026-11-25T08:00:0{idx}+00:00",
                        "ts_local": f"2026-11-25 08:00:0{idx}",
                        "trigger": "daily",
                        "profile": "auto-darwin",
                        "health_score": 96,
                        "anomalies": [],
                        "local": {"gfni_speedup": 50.0, "wormhole_gbps": 12.0, "wan_5pct_speedup": 40.0},
                        "peer": {"reachable": False},
                    }
                    reward = 9.0 if gid == "G2_LOSSY_ARMOR" else 5.0
                    store.record_run(summary, genome_id=gid, reward=reward)
                self.assertEqual(seen_genomes, set(GENOMES.keys()))

                # Fixed profile override check
                self.assertEqual(store.select_genome("max-speed")[0], "G3_TURBO_BULK")
                self.assertEqual(store.select_genome("lossy-armor")[0], "G2_LOSSY_ARMOR")

                # UCB1 should prefer high-reward G2_LOSSY_ARMOR after exploration
                picked_best, _ = store.select_genome("auto-darwin")
                self.assertEqual(picked_best, "G2_LOSSY_ARMOR")

                st = store.get_dashboard_state()
                self.assertEqual(st["total_runs"], len(GENOMES))
                self.assertIn("avg_7d", st)
            finally:
                store.close()

    def test_autopilot_run_and_dashboard_rest_api(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ops = Path(tmp) / "ops"
            cfg = OpsConfig(
                node_name="test-loop-node",
                role="controller",
                dashboard_bind="127.0.0.1:0",
                beam_port=0,
                rpc_v4_port=0,
                rpc_v6_port=-1,
                query_port=0,
                warp_port=0,
                peer_name="self-loop",
                peer_ipv4="127.0.0.1",
                watched_query_file="@synthetic",
            )
            daemon = ChimeraDaemon(config=cfg, ops_dir=ops, auto_seed_on_empty=False).start()
            # Point peer ports directly to daemon's own ephemeral ports for full loopback REST+UDP test
            daemon.config.peer_beam_port = daemon.config.beam_port
            daemon.config.peer_rpc_v4_port = daemon.config.rpc_v4_port
            daemon.config.peer_query_port = daemon.config.query_port
            daemon.config.peer_dashboard_port = daemon.http_addr[1]
            base = f"http://127.0.0.1:{daemon.http_addr[1]}"

            try:
                html = urllib.request.urlopen(f"{base}/", timeout=5.0).read().decode("utf-8")
                self.assertIn("CHIMERA-HYPER v2.0", html)

                # Switch profile
                req_prof = urllib.request.Request(
                    f"{base}/api/profile",
                    data=json.dumps({"active_profile": "max-speed"}).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                prof_res = json.loads(urllib.request.urlopen(req_prof, timeout=5.0).read().decode())
                self.assertEqual(prof_res["active_profile"], "max-speed")

                # Trigger live query
                req_q = urllib.request.Request(
                    f"{base}/api/live-query",
                    data=json.dumps({"needle": "ERROR", "file_path": "@synthetic"}).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                q_res = json.loads(urllib.request.urlopen(req_q, timeout=10.0).read().decode())
                self.assertGreater(q_res["matched_records"], 0)
                self.assertGreater(q_res["wire_reduction_pct"], 90.0)

                # Trigger full sync daily cycle via REST
                req_run = urllib.request.Request(f"{base}/api/run?sync=1", data=b"", method="POST")
                run_res = json.loads(urllib.request.urlopen(req_run, timeout=25.0).read().decode())
                self.assertGreaterEqual(run_res["health_score"], 85)
                self.assertTrue(run_res["peer"]["reachable"])
                self.assertTrue(run_res["peer"]["beam_ok"])
                self.assertTrue(run_res["peer"]["query_ok"])

                st = json.loads(urllib.request.urlopen(f"{base}/api/status", timeout=5.0).read().decode())
                self.assertGreaterEqual(st["telemetry"]["total_runs"], 1)
            finally:
                daemon.close()

    def test_cross_core_determinism_fastcdc_and_delta(self) -> None:
        import random

        raw = random.Random(20261125).randbytes(256 * 1024)
        spans = fastcdc_split(raw, 4096, 16384, 65536)
        self.assertGreater(len(spans), 5)
        self.assertEqual(spans[0][0], 0)
        self.assertEqual(spans[-1][1], len(raw))
        sfs = chunk_superfeatures(raw[:16384])
        self.assertEqual(len(sfs), 4)
        self.assertTrue(all(x > 0 for x in sfs))
        edited = b"X" * 33 + raw[33:]
        patch = delta_encode(raw, edited)
        self.assertIsNotNone(patch)
        self.assertEqual(delta_decode(raw, patch, len(edited)), edited)
