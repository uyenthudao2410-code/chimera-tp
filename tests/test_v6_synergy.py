"""Automated test suite for CHIMERA-HYPER v6.0 APEX-SYNERGY."""

from __future__ import annotations

import http.server
import json
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

from chimera_tp.apex_synergy import ApexSynergyEngine
from chimera_tp.autopilot import OpsConfig
from chimera_tp.dashboard import ChimeraDaemon
from chimera_tp.drop_portal import DropPortalStore
from chimera_tp.holo_backup import restore_holo_backup


class _MockSynergyServers:
    """Starts ephemeral mock Tqouta admin, Tqouta v1 relay, and Radar HTTP servers."""

    def __init__(self, tq_mode: str = "healthy") -> None:
        self.tq_mode = tq_mode
        outer = self

        class AdminHandler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                if outer.tq_mode == "down":
                    self.send_response(503)
                    self.end_headers()
                    return
                if outer.tq_mode == "healthy":
                    accounts = [
                        {"id": f"acc-{i}", "provider": "chatgpt", "email": f"secret{i}@example.com", "label": f"secret{i}@example.com", "enabled": True, "status": "ok"}
                        for i in range(5)
                    ]
                    warnings: list[dict] = []
                    slo_state = "ok"
                else:
                    accounts = [
                        {"id": "acc-0", "provider": "chatgpt", "email": "secret0@example.com", "label": "secret0@example.com", "enabled": True, "status": "needs_reauth"}
                    ]
                    warnings = [{"code": "chatgpt_unknown_pool", "count": 1}]
                    slo_state = "relay_degraded"
                payload = {
                    "accounts": accounts,
                    "fleetHealth": {"warnings": warnings},
                    "accountScheduler": {"accountsInFlight": 1},
                    "stats": {
                        "totalRequests": 1000,
                        "autoCutRequests": 600,
                        "totalInputTokens": 200000,
                        "totalCachedTokens": 150000,
                        "totalOutputTokens": 4000,
                        "trimmedInputChars": 120000,
                    },
                    "dualLayerSlo": {"overallStatus": slo_state},
                    "slo": {"metrics": {"proxyTtftMs": {"p50Ms": 1200}}},
                    "memory": {"rssBytes": 128 * 1024 * 1024},
                }
                raw = json.dumps(payload).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, *_args: object) -> None:
                pass

        class RelayHandler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                raw = json.dumps({"object": "list", "data": [{"id": "gpt-6.2-sol"}]}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, *_args: object) -> None:
                pass

        class RadarHandler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                raw = json.dumps(
                    {
                        "approvals": [{"id": 1}],
                        "crew_runs": [{"id": 1}, {"id": 2}],
                        "breakthrough": {
                            "barbell": {
                                "weights": {"high_conviction": 0.7},
                                "kill_switches": {
                                    "K2_burn_efficiency": {
                                        "alert": False,
                                        "clean_ships_30d": 17,
                                        "api_burn_30d_usd": 0.0,
                                        "realized_usd_30d": 0.0,
                                    }
                                },
                            }
                        },
                    }
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, *_args: object) -> None:
                pass

        self.admin_srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), AdminHandler)
        self.relay_srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), RelayHandler)
        self.radar_srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), RadarHandler)
        self.threads = [
            threading.Thread(target=self.admin_srv.serve_forever, daemon=True),
            threading.Thread(target=self.relay_srv.serve_forever, daemon=True),
            threading.Thread(target=self.radar_srv.serve_forever, daemon=True),
        ]
        for t in self.threads:
            t.start()

    def close(self) -> None:
        for s in (self.admin_srv, self.relay_srv, self.radar_srv):
            s.shutdown()
            s.server_close()


class TestV6Synergy(unittest.TestCase):
    def test_surgical_brief_0token_scan_and_injection(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ws = root / "radar_dashboard" / "workspaces" / "org__repo__issue_1"
            repo = ws / "repo"
            (repo / "src").mkdir(parents=True)
            (repo / "tests").mkdir(parents=True)
            (ws / "AGENT_SOLVER_BRIEF.md").write_text("# Issue Brief\nFix `calc_hyper_flux` bug.\n", encoding="utf-8")
            (repo / "src" / "flux.py").write_text(
                "\n".join([f"# filler {i}" for i in range(40)]) + "\ndef calc_hyper_flux(x):\n    return x * 2\n",
                encoding="utf-8",
            )
            (repo / "src" / "other.py").write_text("unrelated = " + ("12345 " * 200) + "\n", encoding="utf-8")
            (repo / "tests" / "test_flux.py").write_text("def test_calc_hyper_flux(): assert True\n", encoding="utf-8")

            eng = ApexSynergyEngine(ops_dir=root / "ops", allowed_roots=[root])
            with self.assertRaises(PermissionError):
                eng.build_surgical_brief(str(root.parent), issue_title="escape")

            res = eng.build_surgical_brief(
                str(ws),
                issue_title="calc_hyper_flux returns wrong factor",
                issue_body="Inspect `calc_hyper_flux` inside `flux.py`",
                max_chars=5000,
                inject=True,
            )
            self.assertTrue(res["ok"])
            self.assertLessEqual(res["pack_bytes"], 5000)
            self.assertEqual(res["top_files"][0], "src/flux.py")
            self.assertTrue(res["injected_into_brief"])
            self.assertTrue((ws / "CHIMERA_SURGERY_PACK.md").is_file())
            brief_txt = (ws / "AGENT_SOLVER_BRIEF.md").read_text(encoding="utf-8")
            self.assertEqual(brief_txt.count("## CHIMERA 0-Token Surgical Map"), 1)

            # Second inject call must stay idempotent
            res2 = eng.build_surgical_brief(str(ws), inject=True)
            self.assertFalse(res2["injected_into_brief"])
            brief_txt2 = (ws / "AGENT_SOLVER_BRIEF.md").read_text(encoding="utf-8")
            self.assertEqual(brief_txt2.count("## CHIMERA 0-Token Surgical Map"), 1)

    def test_quota_arbiter_regimes_and_email_redaction(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            rr = root / "radar_dashboard"
            (rr / "job_radar" / "data").mkdir(parents=True)
            (rr / "workspaces").mkdir(parents=True)
            mocks = _MockSynergyServers("healthy")
            try:
                eng = ApexSynergyEngine(
                    ops_dir=root / "ops",
                    allowed_roots=[root],
                    tquota_admin_url=f"http://127.0.0.1:{mocks.admin_srv.server_address[1]}",
                    tquota_relay_url=f"http://127.0.0.1:{mocks.relay_srv.server_address[1]}",
                    radar_url=f"http://127.0.0.1:{mocks.radar_srv.server_address[1]}",
                    radar_root=str(rr),
                )
                r1 = eng.evaluate_quota_arbiter(apply_policy=True)
                self.assertEqual(r1["regime"], "TURBO")
                self.assertEqual(r1["policy"]["max_parallel_solvers"], 3)
                self.assertNotIn("@example.com", json.dumps(r1))
                self.assertTrue((rr / "job_radar" / "data" / "CHIMERA_ARBITER_POLICY.json").is_file())

                mocks.tq_mode = "degraded"
                r2 = eng.evaluate_quota_arbiter(apply_policy=True)
                self.assertEqual(r2["regime"], "ECO_SURVIVAL")
                self.assertEqual(r2["policy"]["max_parallel_solvers"], 1)
                self.assertTrue(r2["policy"]["pause_non_makefun"])
            finally:
                mocks.close()

    def test_burn_loop_detector_and_circuit_breaker(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ws_root = root / "radar_dashboard" / "workspaces"
            ws_bad = ws_root / "bad_repo__issue_99"
            ws_good = ws_root / "good_repo__issue_100"
            ws_bad.mkdir(parents=True)
            ws_good.mkdir(parents=True)

            (ws_bad / "agy_solver.log").write_text(
                "2026-11-25T10:00:01Z AssertionError: expected 42 got 0 at line:10\n"
                "2026-11-25T10:01:02Z AssertionError: expected 42 got 0 at line:12\n"
                "2026-11-25T10:02:03Z AssertionError: expected 42 got 0 at line:15\n",
                encoding="utf-8",
            )
            (ws_good / "agy_solver.log").write_text("pytest 12 passed in 0.8s\n", encoding="utf-8")
            (ws_good / "solution.patch").write_text("--- a/x.py\n+++ b/x.py\n+ok\n", encoding="utf-8")

            eng = ApexSynergyEngine(ops_dir=root / "ops", allowed_roots=[root])
            scan = eng.scan_solver_burn_loops(str(ws_root), repeat_threshold=3)
            self.assertEqual(scan["alert_count"], 1)
            self.assertEqual(scan["alerts"][0]["workspace_id"], "bad_repo__issue_99")

            portal = DropPortalStore(root / "ops" / "drop_portal")
            br = eng.trip_circuit_breaker("bad_repo__issue_99", drop_portal=portal, workspaces_root=str(ws_root))
            self.assertTrue(br["ok"])
            self.assertTrue((ws_bad / "CHIMERA_CIRCUIT_BREAK.json").is_file())
            self.assertEqual(len(portal.list_items()), 1)

    def test_ready_bounties_5s_review_and_portal_drop(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ws_root = root / "radar_dashboard" / "workspaces"
            ws = ws_root / "acme__tool__issue_7"
            ws.mkdir(parents=True)
            (ws / "solution.patch").write_text(
                "--- a/app.py\n+++ b/app.py\n@@ -1,2 +1,3 @@\n-old\n+new1\n+new2\n",
                encoding="utf-8",
            )
            (ws / "CREW_REPORT.md").write_text("# PASS\nAll unit tests green.\n", encoding="utf-8")
            (ws / "PR_META.json").write_text(json.dumps({"title": "Fix bug", "bounty_usd": 150}), encoding="utf-8")

            eng = ApexSynergyEngine(ops_dir=root / "ops", allowed_roots=[root])
            res = eng.list_ready_bounties(str(ws_root), dav_base="http://127.0.0.1:9788/dav")
            self.assertEqual(res["total_ready"], 1)
            b = res["bounties"][0]
            self.assertEqual(b["diff_stats"]["files_changed"], 1)
            self.assertEqual(b["diff_stats"]["lines_added"], 2)
            self.assertEqual(b["diff_stats"]["lines_removed"], 1)
            self.assertIn("/dav/radar_dashboard/workspaces/acme__tool__issue_7/solution.patch", b["dav_patch_url"])

            portal = DropPortalStore(root / "ops" / "drop_portal")
            dp = eng.publish_bounty_to_portal("acme__tool__issue_7", drop_portal=portal, workspaces_root=str(ws_root))
            self.assertTrue(dp["ok"])
            self.assertIn("PR Ready: acme__tool__issue_7", portal.list_items()[0]["title"])

    def test_apex_vault_gf256_atomic_sqlite_backup_and_restore(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            tq_dir = root / "Tqouta" / "local-relay" / "data"
            rd_data = root / "radar_dashboard" / "job_radar" / "data"
            tq_dir.mkdir(parents=True)
            rd_data.mkdir(parents=True)
            (tq_dir / "local-state.json").write_text('{"accounts":[{"id":"a1"}]}', encoding="utf-8")
            (rd_data / "alpha_suite_state.json").write_text('{"mode":"active"}', encoding="utf-8")

            db_path = rd_data / "radar.db"
            conn = sqlite3.connect(str(db_path))
            conn.execute("CREATE TABLE ops (id INTEGER PRIMARY KEY, note TEXT)")
            conn.execute("INSERT INTO ops (note) VALUES ('secret_radar_state')")
            conn.commit()
            conn.close()

            eng = ApexSynergyEngine(
                ops_dir=root / "ops",
                allowed_roots=[root],
                radar_root=str(root / "radar_dashboard"),
                tquota_data_dir=str(tq_dir),
            )
            rep = eng.backup_apex_vault(backup_root=root / "ops" / "holo_backups", include_radar_db=True)
            self.assertTrue(rep["ok"])
            self.assertIn("local-state.json", rep["included_files"])
            self.assertIn("radar_db_snapshot.sqlite", rep["included_files"])
            shards = rep["backup"]["local_shards"]
            entropies = rep["backup"]["entropies"]
            self.assertGreater(entropies[0], 7.0)

            out_dir = root / "restored"
            rest = restore_holo_backup([Path(shards[0]), Path(shards[2])], out_dir=out_dir)
            self.assertTrue(rest["sha256_match"])
            r_conn = sqlite3.connect(str(out_dir / "radar_db_snapshot.sqlite"))
            row = r_conn.execute("SELECT note FROM ops WHERE id=1").fetchone()
            r_conn.close()
            self.assertEqual(row[0], "secret_radar_state")

    def test_daemon_v6_synergy_endpoints_and_tquota_tunnel_forward(self) -> None:
        mocks = _MockSynergyServers("healthy")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            rr = root / "radar_dashboard"
            ws = rr / "workspaces" / "demo__proj__issue_2"
            (ws / "proj").mkdir(parents=True)
            (ws / "proj" / "main.py").write_text("def target_v6_fn():\n    return 600\n", encoding="utf-8")
            (ws / "solution.patch").write_text("--- a/main.py\n+++ b/main.py\n+return 600\n", encoding="utf-8")

            cfg = OpsConfig(
                node_name="v6-unit",
                role="server",
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
                phantom_enabled=True,
                phantom_tquota_port=0,
                tquota_admin_url=f"http://127.0.0.1:{mocks.admin_srv.server_address[1]}",
                tquota_relay_url=f"http://127.0.0.1:{mocks.relay_srv.server_address[1]}",
                radar_url=f"http://127.0.0.1:{mocks.radar_srv.server_address[1]}",
                radar_root=str(rr),
            )
            daemon = ChimeraDaemon(config=cfg, ops_dir=root / "ops", auto_seed_on_empty=False).start()
            base = f"http://127.0.0.1:{daemon.http_addr[1]}"
            try:
                h = json.loads(urllib.request.urlopen(f"{base}/api/health", timeout=4.0).read().decode())
                self.assertEqual(h["version"], "6.0.0")
                self.assertGreater(h["zero_weight"]["daemon_ram_mb"], 0.0)

                syn = json.loads(urllib.request.urlopen(f"{base}/api/synergy/status", timeout=5.0).read().decode())
                self.assertEqual(syn["regime"], "TURBO")
                self.assertEqual(syn["tquota"]["accounts_ok"], 5)
                self.assertNotIn("@example.com", json.dumps(syn))

                bnt = json.loads(urllib.request.urlopen(f"{base}/api/synergy/bounties", timeout=5.0).read().decode())
                self.assertEqual(bnt["total_ready"], 1)

                req_b = urllib.request.Request(
                    f"{base}/api/synergy/surgical-brief",
                    data=json.dumps({"workspace_dir": str(ws), "issue_title": "target_v6_fn"}).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                br = json.loads(urllib.request.urlopen(req_b, timeout=5.0).read().decode())
                self.assertTrue(br["ok"])
                self.assertEqual(br["top_files"][0], "main.py")
            finally:
                daemon.close()
                mocks.close()

        zw_code = (
            "import tempfile, json; from pathlib import Path; "
            "from chimera_tp.autopilot import OpsConfig, get_zero_weight_status; "
            "from chimera_tp.dashboard import ChimeraDaemon; "
            "td=tempfile.TemporaryDirectory(); "
            "cfg=OpsConfig(node_name='zw6', role='controller', dashboard_bind='127.0.0.1:0', beam_port=0, rpc_v4_port=0, rpc_v6_port=-1, query_port=0, warp_port=-1, edge_proxy_port=0, phantom_enabled=False, phantom_tquota_port=12550); "
            "d=ChimeraDaemon(cfg, ops_dir=Path(td.name), auto_seed_on_empty=False).start(); "
            "print(json.dumps(get_zero_weight_status())); d.close(); td.cleanup()"
        )
        zw_proc = subprocess.run([sys.executable, "-c", zw_code], capture_output=True, text=True, check=True)
        zw = json.loads(zw_proc.stdout.strip().splitlines()[-1])
        self.assertTrue(zw["zero_weight_ok"], f"RSS exceeded 80 MB budget: {zw}")

        # Verify CLI entrypoint --help executes cleanly on current Python interpreter
        proc = subprocess.run(
            [sys.executable, "-m", "chimera_tp", "synergy", "--help"],
            capture_output=True,
            text=True,
            timeout=8,
        )
        self.assertEqual(proc.returncode, 0)


if __name__ == "__main__":
    unittest.main()
