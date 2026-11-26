"""CHIMERA-TP v15.0 TRINITY-CORTEX Tests (HostYieldGovernor, TrinityCommandBridge, ROI Kill-Switch)."""

from __future__ import annotations

import gzip
import http.server
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
import urllib.request

from chimera_tp.autopilot import OpsConfig
from chimera_tp.dashboard import ChimeraDaemon
from chimera_tp.host_governor import HostYieldGovernor
from chimera_tp.phantom_tunnel import PhantomTunnelClient, PhantomTunnelServer
from chimera_tp.universe_ui import build_kolmogorov_packed_html
from chimera_tp.vsa_memory_service import SharedVsaMemoryService


class TestV15TrinityCortex(unittest.TestCase):
    def test_01_host_yield_governor_states_and_instant_preempt(self) -> None:
        win_gov = HostYieldGovernor(role="controller", policy="work_first")

        # Case 1: Active typing/mouse -> must yield and refuse heavy jobs
        active_st = win_gov.evaluate_state({"idle_sec": 12.0, "cpu_pct": 18.0, "free_ram_gb": 14.0, "total_ram_gb": 31.0})
        self.assertEqual(active_st["mode"], "USER_ACTIVE")
        self.assertFalse(active_st["accept_heavy_jobs"])
        self.assertTrue(active_st["preempt_yield"])

        # Case 2: Workstation idle >=5m, low CPU, free RAM >=8GB -> TURBO_IDLE unlocked
        idle_st = win_gov.evaluate_state({"idle_sec": 420.0, "cpu_pct": 5.2, "free_ram_gb": 16.5, "total_ram_gb": 31.0})
        self.assertEqual(idle_st["mode"], "TURBO_IDLE")
        self.assertTrue(idle_st["accept_heavy_jobs"])
        self.assertFalse(idle_st["preempt_yield"])

        # Case 3: Instant preempt check well under 200ms budget
        p = win_gov.check_preempt({"idle_sec": 0.5, "cpu_pct": 45.0, "free_ram_gb": 10.0, "total_ram_gb": 31.0})
        self.assertTrue(p["preempt"])
        self.assertLess(p["check_ms"], 200.0)

        # Case 4: Linux server runs autonomously in SOVEREIGN_LOCAL mode
        sv_gov = HostYieldGovernor(role="server")
        sv_st = sv_gov.evaluate_state({"idle_sec": None, "cpu_pct": 12.0, "free_ram_gb": 6.0, "total_ram_gb": 10.0})
        self.assertEqual(sv_st["mode"], "SOVEREIGN_LOCAL")
        self.assertFalse(sv_st["accept_heavy_jobs"])

    def test_02_trinity_bridge_endpoints_and_roi_kill_switch(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = OpsConfig(
                role="controller",
                node_name="trinity_unit",
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
                st = json.loads(urllib.request.urlopen(f"{base}/api/trinity/status", timeout=4.0).read().decode())
                self.assertTrue(st["ok"])
                self.assertEqual(st["version"], "15.0-trinity")
                self.assertIn("governor", st)
                self.assertFalse(st["kill_switch"]["active"])

                # Trigger Auto ROI Kill-Switch on high burn + 0 outputs >= 2h
                req_auto = urllib.request.Request(
                    f"{base}/api/trinity/kill-switch",
                    data=json.dumps(
                        {"evaluate_auto": True, "burn_rate_pct_hr": 18.5, "recent_outputs": 0, "zero_output_hours": 2.5}
                    ).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                ks_auto = json.loads(urllib.request.urlopen(req_auto, timeout=4.0).read().decode())
                self.assertTrue(ks_auto["kill_switch"]["active"])
                self.assertTrue(ks_auto["kill_switch"]["auto_triggered"])

                # Pulse carries live trinity summary + flow ring entry
                pulse = json.loads(urllib.request.urlopen(f"{base}/api/pulse", timeout=4.0).read().decode())
                self.assertTrue(pulse["trinity"]["kill_switch"])
                self.assertIn("ROI_KILL_SWITCH", {f["op"] for f in pulse.get("flows", [])})

                # Clear kill switch & change policy to sovereign_only
                req_clr = urllib.request.Request(
                    f"{base}/api/trinity/kill-switch",
                    data=json.dumps({"active": False, "reason": "verified_ok"}).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                self.assertFalse(json.loads(urllib.request.urlopen(req_clr, timeout=4.0).read().decode())["kill_switch"]["active"])

                req_pol = urllib.request.Request(
                    f"{base}/api/trinity/governor",
                    data=json.dumps({"policy": "sovereign_only"}).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                pol_res = json.loads(urllib.request.urlopen(req_pol, timeout=4.0).read().decode())
                self.assertEqual(pol_res["mode"], "SOVEREIGN_LOCAL")
            finally:
                daemon.close()

    def test_03_shared_vsa_avx2_memory_service(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            svc = SharedVsaMemoryService(db_path=Path(td) / "vsa_memory.db")
            try:
                batch_res = svc.store_batch(
                    [
                        {
                            "item_id": "cry_npm_slicer",
                            "domain": "github_bounty",
                            "text": "npm test timed out after 120 seconds vitest jest watch",
                            "payload": {"hint": "slice vitest paths"},
                            "reward": 2.0,
                        },
                        {
                            "item_id": "cry_env_firewall",
                            "domain": "security",
                            "text": "Forbidden file .env modified lockfile diff blocked",
                            "payload": {"hint": "chmod read-only"},
                            "reward": 2.5,
                        },
                    ]
                )
                self.assertTrue(batch_res["ok"])
                self.assertEqual(batch_res["stored_count"], 2)
                rec = svc.recall("vitest jest npm test timeout 120 seconds", top_k=2)
                self.assertTrue(rec["ok"])
                self.assertEqual(rec["matches"][0]["item_id"], "cry_npm_slicer")
                self.assertGreater(rec["matches"][0]["similarity"], rec["matches"][1]["similarity"])
                st = svc.stats()
                self.assertEqual(st["item_count"], 2)
                self.assertEqual(st["queries_served"], 1)
            finally:
                svc.close()

    def test_04_kill_switch_actuates_radar_control_endpoint(self) -> None:
        received: list[dict[str, object]] = []

        class _MockRadarHandler(http.server.BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                received.append({"path": self.path, **body})
                resp = json.dumps({"ok": True, "paused": bool(body.get("paused"))}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(resp)))
                self.end_headers()
                self.wfile.write(resp)

            def log_message(self, *_args: object) -> None:
                pass

        mock_srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _MockRadarHandler)
        mock_srv.daemon_threads = True
        th = threading.Thread(target=mock_srv.serve_forever, daemon=True)
        th.start()
        mock_port = mock_srv.server_address[1]
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = OpsConfig(
                role="controller",
                node_name="trinity_actuate_unit",
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
                daemon.trinity.radar_url = f"http://127.0.0.1:{mock_port}"
                ks = daemon.trinity.set_kill_switch(True, "test_actuation_halt", actuate=True)
                self.assertTrue(ks["active"])
                self.assertTrue(ks["actuation"]["ok"])
                self.assertEqual(received[-1]["path"], "/api/godmode/control")
                self.assertTrue(received[-1]["paused"])

                # Also verify HTTP VSA store & recall endpoints live on ChimeraDaemon
                s_req = urllib.request.Request(
                    f"{base}/api/vsa/store",
                    data=json.dumps({"item_id": "k1", "domain": "codex", "text": "responses api prompt cache warm"}).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                s_res = json.loads(urllib.request.urlopen(s_req, timeout=4.0).read().decode())
                self.assertTrue(s_res["ok"])
                r_req = urllib.request.Request(
                    f"{base}/api/vsa/recall",
                    data=json.dumps({"query_text": "prompt cache warm", "top_k": 1}).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                r_res = json.loads(urllib.request.urlopen(r_req, timeout=4.0).read().decode())
                self.assertEqual(r_res["matches"][0]["item_id"], "k1")
            finally:
                daemon.close()
                mock_srv.shutdown()
                mock_srv.server_close()

    def test_05_reverse_phantom_bidirectional_loopback_and_vsa_peer_sync(self) -> None:
        packed_html = build_kolmogorov_packed_html()
        self.assertLess(len(gzip.compress(packed_html)), 16500)

        class _EchoHandler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                payload = json.dumps({"ok": True, "path": self.path, "dir": "reverse_or_fwd"}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *_args: object) -> None:
                pass

        fwd_backend = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _EchoHandler)
        rev_backend = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _EchoHandler)
        fwd_backend.daemon_threads = True
        rev_backend.daemon_threads = True
        threading.Thread(target=fwd_backend.serve_forever, daemon=True).start()
        threading.Thread(target=rev_backend.serve_forever, daemon=True).start()
        fwd_p = int(fwd_backend.server_address[1])
        rev_p = int(rev_backend.server_address[1])

        srv_tunnel = PhantomTunnelServer(
            fallback_port=0,
            allowed_forward_ports=[fwd_p],
            reverse_forwards={0: rev_p},
        ).start()

        class _OfferHandler(http.server.BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                resp = json.dumps(srv_tunnel.accept_offer(body)).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(resp)))
                self.end_headers()
                self.wfile.write(resp)

            def log_message(self, *_args: object) -> None:
                pass

        offer_srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _OfferHandler)
        offer_srv.daemon_threads = True
        threading.Thread(target=offer_srv.serve_forever, daemon=True).start()
        offer_port = int(offer_srv.server_address[1])

        cli_tunnel = PhantomTunnelClient(
            peer_http_base=f"http://127.0.0.1:{offer_port}",
            peer_udp_ip="127.0.0.1",
            peer_fallback_port=srv_tunnel.fallback_port,
            forwards={0: fwd_p},
            local_test_mode=True,
            allowed_reverse_ports=[rev_p],
        ).start_listeners()
        try:
            conn_res = cli_tunnel.connect(local_test_mode=True, num_sockets=8, spray_count=64, timeout_s=2.0)
            self.assertTrue(conn_res["connected"])

            # Forward direction (client listener -> server allowed port)
            fwd_local = cli_tunnel.bound_ports[fwd_p]
            r_fwd = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{fwd_local}/fwd-ping", timeout=3.0).read().decode())
            self.assertEqual(r_fwd["path"], "/fwd-ping")

            # Reverse direction (server listener -> client allowed reverse port)
            rev_local = srv_tunnel.reverse_bound_ports[rev_p]
            r_rev = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{rev_local}/rev-ping", timeout=3.0).read().decode())
            self.assertEqual(r_rev["path"], "/rev-ping")
        finally:
            cli_tunnel.close()
            srv_tunnel.close()
            offer_srv.shutdown()
            offer_srv.server_close()
            fwd_backend.shutdown()
            fwd_backend.server_close()
            rev_backend.shutdown()
            rev_backend.server_close()

        # Verify bidirectional VSA sync across two live daemons
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            d1 = ChimeraDaemon(
                config=OpsConfig(
                    role="server",
                    node_name="vsa_peer_a",
                    dashboard_bind="127.0.0.1:0",
                    beam_port=0,
                    rpc_v4_port=0,
                    rpc_v6_port=-1,
                    query_port=0,
                    warp_port=-1,
                    edge_proxy_port=-1,
                    allowed_query_roots=[str(root / "a")],
                    search_roots=[str(root / "a")],
                    edge_targets={},
                    phantom_enabled=False,
                ),
                ops_dir=root / "ops_a",
                auto_seed_on_empty=False,
            ).start()
            d2 = ChimeraDaemon(
                config=OpsConfig(
                    role="controller",
                    node_name="vsa_peer_b",
                    dashboard_bind="127.0.0.1:0",
                    beam_port=0,
                    rpc_v4_port=0,
                    rpc_v6_port=-1,
                    query_port=0,
                    warp_port=-1,
                    edge_proxy_port=-1,
                    allowed_query_roots=[str(root / "b")],
                    search_roots=[str(root / "b")],
                    edge_targets={},
                    phantom_enabled=False,
                ),
                ops_dir=root / "ops_b",
                auto_seed_on_empty=False,
            ).start()
            b1 = f"http://127.0.0.1:{d1.http_addr[1]}"
            b2 = f"http://127.0.0.1:{d2.http_addr[1]}"
            try:
                d1.vsa_memory.store("c_svhome_1", domain="crew_run", text="pytest missing conftest fix", reward=2.0)
                d2.vsa_memory.store("c_win_1", domain="codex", text="vitest parallel thread pool limit", reward=1.8)
                sync_req = urllib.request.Request(
                    f"{b2}/api/vsa/sync-peer",
                    data=json.dumps({"peer_base": b1, "bidirectional": True}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                sync_res = json.loads(urllib.request.urlopen(sync_req, timeout=4.0).read().decode())
                self.assertTrue(sync_res["ok"])
                self.assertEqual(sync_res["local_total"], sync_res["peer_total"])
                self.assertEqual(sync_res["local_total"], 2)
            finally:
                d2.close()
                d1.close()

    def test_06_phantom_client_auto_reconnects_after_server_restart(self) -> None:
        class _EchoHandler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                payload = json.dumps({"ok": True, "path": self.path}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *_args: object) -> None:
                pass

        backend = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _EchoHandler)
        backend.daemon_threads = True
        threading.Thread(target=backend.serve_forever, daemon=True).start()
        back_p = int(backend.server_address[1])

        srv1 = PhantomTunnelServer(fallback_port=0, allowed_forward_ports=[back_p]).start()
        srv2 = PhantomTunnelServer(fallback_port=0, allowed_forward_ports=[back_p]).start()
        active_srv = [srv1]

        class _OfferHandler(http.server.BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                resp = json.dumps(active_srv[0].accept_offer(body)).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(resp)))
                self.end_headers()
                self.wfile.write(resp)

            def log_message(self, *_args: object) -> None:
                pass

        offer_srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _OfferHandler)
        offer_srv.daemon_threads = True
        threading.Thread(target=offer_srv.serve_forever, daemon=True).start()
        offer_port = int(offer_srv.server_address[1])

        cli_tunnel = PhantomTunnelClient(
            peer_http_base=f"http://127.0.0.1:{offer_port}",
            peer_udp_ip="127.0.0.1",
            peer_fallback_port=srv2.fallback_port,
            forwards={0: back_p},
            local_test_mode=True,
            keepalive_interval_s=0.15,
            pong_stale_s=0.45,
            reconnect_cooldown_s=0.2,
            auto_reconnect=True,
        ).start_listeners()
        try:
            conn_res = cli_tunnel.connect(local_test_mode=True, num_sockets=8, spray_count=64, timeout_s=2.0)
            self.assertTrue(conn_res["connected"])
            loc_p = cli_tunnel.bound_ports[back_p]
            r1 = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{loc_p}/before", timeout=3.0).read().decode())
            self.assertEqual(r1["path"], "/before")

            # Simulate remote server restart: switch offer endpoint to srv2 and terminate srv1
            active_srv[0] = srv2
            srv1.close()

            deadline = time.monotonic() + 5.0
            reconnected = False
            while time.monotonic() < deadline:
                st = cli_tunnel.status()
                if st.get("reconnect_count", 0) >= 1 and st.get("connected") and not st.get("reconnecting"):
                    reconnected = True
                    break
                time.sleep(0.1)
            self.assertTrue(reconnected, f"Expected auto-reconnect, status={cli_tunnel.status()}")
            r2 = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{loc_p}/after-restart", timeout=3.0).read().decode())
            self.assertEqual(r2["path"], "/after-restart")
        finally:
            cli_tunnel.close()
            srv1.close()
            srv2.close()
            offer_srv.shutdown()
            offer_srv.server_close()
            backend.shutdown()
            backend.server_close()


if __name__ == "__main__":
    unittest.main()
