"""Unit tests for CHIMERA OVERMIND CORTEX v18 (CRDT, DLP, Hippocampus, Sentinel Dedup, Flight Recorder, Split-Brain)."""

from __future__ import annotations

import base64
import http.server
import json
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.request

from chimera_tp.autopilot import OpsConfig
from chimera_tp.dashboard import ChimeraDaemon
from chimera_tp.overmind_cortex import (
    BrainStateCRDT,
    EgressDlpGuard,
    FlightRecorderRing,
    TriTierWorkStealingPlanner,
)
from chimera_tp.sentinel import SentinelEngine
from chimera_tp.vsa_memory_service import SharedVsaMemoryService


class TestV18OvermindCortex(unittest.TestCase):
    def test_01_brain_state_crdt_convergence_and_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p1 = Path(td) / "node_a"
            p2 = Path(td) / "node_b"
            c1 = BrainStateCRDT(p1, node_id="win-desktop")
            c2 = BrainStateCRDT(p2, node_id="svhome")

            s1 = c1.mutate({"kill_switch_active": True, "kill_switch_reason": "burn_cap"}, source="win")
            s2 = c2.mutate({"kill_switch_active": False, "kill_switch_reason": "resume"}, source="svhome")
            # Force s2 (and c2 internal HLC state) strictly newer and merge out-of-order on both nodes
            s2 = c2.merge({**s2, "hlc_ts_ms": int(s1["hlc_ts_ms"]) + 50})["state"]
            m1 = c1.merge(s2)
            m2 = c2.merge(s1)
            self.assertTrue(m1["merged"])
            self.assertFalse(m2["merged"])
            self.assertEqual(c1.snapshot()["kill_switch_active"], c2.snapshot()["kill_switch_active"])
            self.assertFalse(c1.snapshot()["kill_switch_active"])

            # Persistence across restart
            s3 = c1.mutate({"kill_switch_active": True, "kill_switch_reason": "persisted_halt"}, source="win")
            reloaded = BrainStateCRDT(p1, node_id="win-desktop")
            self.assertTrue(reloaded.snapshot()["kill_switch_active"])
            self.assertEqual(reloaded.snapshot()["hlc_ts_ms"], s3["hlc_ts_ms"])

    def test_02_egress_dlp_guard_catches_plain_and_base64_secrets(self) -> None:
        b64_tok = base64.b64encode(b"ghp_SuperSecretTokenValue1234567890").decode("ascii")
        sample = (
            f"contact=alice.dev@gmail.com ip=14.177.197.12 "
            f"oauth=ya29.AbCdEfGhIjKlMnOpQrStUvWxYz Authorization: Bearer secret_token_abcdef123456 "
            f"pat=ghp_1234567890abcdef1234 sk-abcdefgh1234567890 blob={b64_tok}"
        )
        scan = EgressDlpGuard.scan_text(sample)
        self.assertTrue(scan["blocked"])
        for expected in ("email", "non_loopback_ip", "oauth_ya29", "bearer_token", "github_pat", "api_sk", "base64_secret"):
            self.assertIn(expected, scan["categories"])

        redacted = EgressDlpGuard.redact_text(sample)
        self.assertTrue(EgressDlpGuard.scan_text(redacted)["ok"])

        clean = EgressDlpGuard.scan_text("status=ok loopback=127.0.0.1 bind=0.0.0.0 tests=52/52")
        self.assertTrue(clean["ok"])
        self.assertEqual(clean["finding_count"], 0)

    def test_03_vsa_hippocampus_ingest_tquota_and_capsule(self) -> None:
        class _MockTquotaHandler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                if self.path.startswith("/api/thought-briefs/export"):
                    payload = json.dumps(
                        {
                            "ok": True,
                            "count": 2,
                            "items": [
                                {
                                    "item_id": "tb_1",
                                    "domain": "tquota_thought",
                                    "text": "python pytest conftest fixture min_makefun_pool_usd 100",
                                    "payload": {"brief_text": "Pin guardrails.min_makefun_pool_usd=100 for fixture tests and keep alice@gmail.com secret out"},
                                    "reward": 2.0,
                                },
                                {
                                    "item_id": "tb_2",
                                    "domain": "tquota_thought",
                                    "text": "node colab dev shm noexec chmod 755 vitest jest",
                                    "payload": {"brief_text": "Run Node tests from /tmp/chimera_verify_node to eliminate rc=126"},
                                    "reward": 2.0,
                                },
                            ],
                        }
                    ).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                else:
                    self.send_response(404)
                    self.end_headers()

            def log_message(self, *_args: object) -> None:
                pass

        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _MockTquotaHandler)
        srv.daemon_threads = True
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            with tempfile.TemporaryDirectory() as td:
                vsa = SharedVsaMemoryService(db_path=Path(td) / "vsa.db")
                try:
                    ing = vsa.ingest_tquota_thought_briefs(f"http://127.0.0.1:{srv.server_address[1]}", limit=50)
                    self.assertTrue(ing["ok"])
                    self.assertEqual(ing["stored_count"], 2)
                    cap = vsa.build_memory_capsule("node vitest jest rc=126 colab", domains=["tquota_thought"], top_k=2, min_sim=0.45)
                    self.assertTrue(cap["ok"])
                    self.assertGreaterEqual(cap["hits"], 1)
                    self.assertIn("tquota_thought", cap["capsule"])
                    self.assertGreaterEqual(vsa.stats()["queries_served"], 1)
                    # Verify DLP redaction on ingested capsule text
                    cap_email = vsa.build_memory_capsule("python pytest conftest fixture", min_sim=0.45)
                    self.assertNotIn("alice@gmail.com", cap_email["capsule"])
                finally:
                    vsa.close()
        finally:
            srv.shutdown()
            srv.server_close()

    def test_04_sentinel_alert_dedup_and_root_cause_diagnosis(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            log_file = root / "nhac_lich_email.log"
            log_file.write_text("\n".join(["ERROR MAIL_FAIL_502 upstream SMTP gateway timeout" for _ in range(40)]) + "\n", encoding="utf-8")
            cfg = OpsConfig(
                role="server",
                node_name="svhome_test",
                dashboard_bind="127.0.0.1:0",
                beam_port=0,
                rpc_v4_port=0,
                rpc_v6_port=-1,
                query_port=0,
                warp_port=-1,
                edge_proxy_port=-1,
                allowed_query_roots=[str(root)],
                search_roots=[str(root)],
                watched_query_file=str(log_file),
                edge_targets={},
                phantom_enabled=False,
            )
            sent = SentinelEngine(root / "ops")
            try:
                spikes: list[dict] = []
                r1 = sent.scan(cfg, alert_dedup_window_s=1800.0, on_spike_callback=spikes.append)
                self.assertEqual(r1["alert_count"], len(r1["alerts"]))
                log_alerts = [a for a in r1["alerts"] if a["category"] == "LOG_SPIKE"]
                self.assertEqual([a["source"] for a in log_alerts], [log_file.name])
                self.assertEqual(r1["suppressed_repeats"], 0)
                self.assertIn("502", log_alerts[0]["diagnosis"])
                self.assertEqual(len(spikes), 1)

                r2 = sent.scan(cfg, alert_dedup_window_s=1800.0, on_spike_callback=spikes.append)
                self.assertEqual(r2["alert_count"], len(r2["alerts"]))
                self.assertFalse(any(a["category"] == "LOG_SPIKE" for a in r2["alerts"]))
                self.assertEqual(r2["suppressed_repeats"], 1)
                self.assertEqual(len(spikes), 1)
            finally:
                sent.close()

    def test_05_flight_recorder_ring_anomaly_freeze_and_tri_tier_planner(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fr = FlightRecorderRing(Path(td) / "ops")
            fr.record_sample({"daemon_ram_mb": 26.0, "tx_bytes": 1000, "phantom_rtt_ms": 5.0, "phantom_conns": 1})
            anom = fr.record_sample({"daemon_ram_mb": 31.0, "phantom_tx_bps": 4_500_000.0, "phantom_rtt_ms": 190.0, "email": "leak@gmail.com"})
            self.assertEqual(anom["trigger_reason"], "phantom_tx_storm")
            self.assertIsNotNone(anom["frozen_cassette"])
            self.assertTrue(anom["frozen_cassette"]["dlp_clean"])
            c_text = Path(anom["frozen_cassette"]["path"]).read_text(encoding="utf-8")
            self.assertNotIn("leak@gmail.com", c_text)

            p_active = TriTierWorkStealingPlanner.plan("build", win_governor={"mode": "USER_ACTIVE", "accept_heavy_jobs": False}, colab_cu=2000.0)
            self.assertEqual(p_active["executor"], "svhome_sovereign_24x7")
            p_idle = TriTierWorkStealingPlanner.plan("build", win_governor={"mode": "TURBO_IDLE", "accept_heavy_jobs": True}, colab_cu=2000.0)
            self.assertEqual(p_idle["executor"], "win_12t_turbo_idle")
            p_colab = TriTierWorkStealingPlanner.plan("verify_patch", stack=["node"], colab_cu=2000.0)
            self.assertEqual(p_colab["executor"], "colab_cpu_high_mem")
            self.assertFalse(p_colab["allow_heavy_gpu"])

    def test_06_live_daemon_overmind_endpoints_and_split_brain_heal(self) -> None:
        radar_state = {"paused": True, "pause_source": "chimera_kill_switch", "calls": []}

        class _MockRadarHandler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                if self.path == "/api/godmode/status":
                    payload = json.dumps(
                        {
                            "ok": True,
                            "learned_rules_count": 5,
                            "patch_crystals_count": 10,
                            "sovereign": {
                                "ok": True,
                                "paused": radar_state["paused"],
                                "pause_source": radar_state["pause_source"],
                            },
                            "colab": {"queued_count": 0, "completed_count": 8},
                            "salvage": {"salvageable_count": 3},
                            "engines": ["grpo", "mcts"],
                        }
                    ).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                    return
                self.send_response(404)
                self.end_headers()

            def do_POST(self) -> None:
                if self.path == "/api/godmode/control":
                    ln = int(self.headers.get("Content-Length") or 0)
                    body = json.loads(self.rfile.read(ln).decode("utf-8") or "{}")
                    radar_state["paused"] = bool(body.get("paused", False))
                    radar_state["calls"].append(body)
                    resp = json.dumps({"ok": True, "paused": radar_state["paused"]}).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(resp)))
                    self.end_headers()
                    self.wfile.write(resp)
                    return
                self.send_response(404)
                self.end_headers()

            def log_message(self, *_args: object) -> None:
                pass

        mock_srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _MockRadarHandler)
        mock_srv.daemon_threads = True
        threading.Thread(target=mock_srv.serve_forever, daemon=True).start()
        try:
            with tempfile.TemporaryDirectory() as td:
                root = Path(td)
                cfg = OpsConfig(
                    role="server",
                    node_name="overmind_unit",
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
                    radar_url=f"http://127.0.0.1:{mock_srv.server_address[1]}",
                )
                daemon = ChimeraDaemon(config=cfg, ops_dir=root / "ops", auto_seed_on_empty=False).start()
                base = f"http://127.0.0.1:{daemon.http_addr[1]}"
                try:
                    # Authoritative CRDT says kill-switch is FALSE, while stale mock Radar says paused=True (split-brain)
                    daemon.overmind.crdt.mutate({"kill_switch_active": False, "kill_switch_reason": "resumed_crdt"}, source="chimera_kill_switch")
                    daemon.trinity._poll_worker()
                    self.assertFalse(radar_state["paused"], "Split-brain heal must push CRDT state to paused Radar")

                    # Check HTTP Overmind endpoints
                    st = json.loads(urllib.request.urlopen(f"{base}/api/overmind/state", timeout=3.0).read().decode())
                    self.assertTrue(st["ok"])
                    self.assertFalse(st["crdt"]["kill_switch_active"])

                    dlp_req = urllib.request.Request(
                        f"{base}/api/overmind/dlp-scan",
                        data=json.dumps({"text": "ip=14.177.197.12"}).encode(),
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    dlp_res = json.loads(urllib.request.urlopen(dlp_req, timeout=3.0).read().decode())
                    self.assertTrue(dlp_res["blocked"])

                    sched_req = urllib.request.Request(
                        f"{base}/api/overmind/schedule",
                        data=json.dumps({"task_type": "codex_patch"}).encode(),
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    sched_res = json.loads(urllib.request.urlopen(sched_req, timeout=3.0).read().decode())
                    self.assertEqual(sched_res["executor"], "tquota_codex_phantom_5ms")
                finally:
                    daemon.close()
        finally:
            mock_srv.shutdown()
            mock_srv.server_close()


if __name__ == "__main__":
    unittest.main()
