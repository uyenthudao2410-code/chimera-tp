"""Scheduled telemetry must perform the transport workload and UCB update only once per day."""

from contextlib import ExitStack, closing
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.request import Request

from chimera_tp import autopilot
from chimera_tp.platform import peer_guard


SCHEDULED = """
import json, sys, time
from pathlib import Path
repo, root, name = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
sys.path.insert(0, str(repo))
from chimera_tp.autopilot import OpsConfig, TelemetryStore, run_daily_autopilot
store = TelemetryStore(root / "telemetry.db")
try:
    config = OpsConfig(node_name="daily-proof", peer_ipv4="", peer_ipv6="")
    (root / (name + ".ready")).touch()
    deadline = time.monotonic() + 20
    while not (root / "start").is_file():
        if time.monotonic() > deadline:
            raise TimeoutError("test coordinator did not release both callers")
        time.sleep(0.02)
    result = run_daily_autopilot(config, store, trigger=name, ops_dir=root)
    print(json.dumps(result))
finally:
    store.close()
"""


class DailyAutopilotTests(unittest.TestCase):
    def test_peer_http_uses_installed_origin_and_never_relays_credentials(self):
        received = []
        marker = "test-only-peer"

        class Endpoint(BaseHTTPRequestHandler):
            def do_GET(self):
                received.append((self.server.server_port, self.path, self.headers.get("X-Chimera-Peer-Auth")))
                if self.path == "/redirect":
                    self.send_response(302)
                    self.send_header("Location", other_url + "/arrival")
                    self.end_headers()
                    return
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"ok":true}')

            do_POST = do_GET

            def log_message(self, *args):
                pass

        with ExitStack() as stack:
            hosts = []
            for _ in range(2):
                server = stack.enter_context(HTTPServer(("127.0.0.1", 0), Endpoint))
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                stack.callback(thread.join)
                stack.callback(server.shutdown)
                hosts.append(server)
            a, b = hosts
            trusted = f"http://127.0.0.1:{a.server_port}"
            other_url = f"http://127.0.0.1:{b.server_port}"
            config = autopilot.OpsConfig(peer_ipv4="127.0.0.1", peer_dashboard_port=a.server_port)
            stack.enter_context(patch.object(autopilot.OpsConfig, "load", return_value=config))
            stack.enter_context(patch.object(peer_guard, "load_peer_secret", return_value=marker))
            self.assertTrue(autopilot._http_get_json(trusted + "/health")["ok"])
            self.assertTrue(autopilot._http_post_bytes(trusted + "/sink", b"sample")["ok"])
            self.assertTrue(autopilot._http_post_json(trusted + "/report", {"test": True})["ok"])
            with autopilot._open_peer_http(Request(trusted + "/redirect"), 3) as resp:
                self.assertEqual(resp.status, 200)
            self.assertTrue(autopilot._http_get_json(other_url + "/trial")["ok"])
            self.assertEqual([secret for port, _, secret in received if port == a.server_port], [marker] * 4)
            self.assertEqual([secret for port, _, secret in received if port == b.server_port], [None, None])

    def test_peer_outage_is_recorded_once_and_does_not_repeat_local_benchmark(self):
        with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
            root = Path(folder)
            store = autopilot.TelemetryStore(root / "telemetry.db")
            stack.callback(store.close)
            config = autopilot.OpsConfig(peer_ipv4="127.0.0.1", peer_dashboard_port=1)
            peer = stack.enter_context(patch.object(autopilot, "_bench_live_peer", side_effect=OSError("peer unavailable")))
            stack.enter_context(patch.object(autopilot, "_http_post_json", side_effect=OSError("hub unavailable")))
            result = autopilot.run_daily_autopilot(config, store, "daily", root)
            self.assertEqual(result, autopilot.run_daily_autopilot(config, store, "daemon_daily", root))
            self.assertFalse(result["peer"]["probe_completed"])
            self.assertFalse(result["pushed_to_hub"])
            self.assertEqual(result["local"]["tcp_loopback_verified_bytes"], 16 * 1024**2)
            self.assertEqual(store.daily_result(root), result)
            peer.assert_called_once()

    def test_real_timer_and_daemon_join_and_recover_current_result(self):
        with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
            root = Path(folder)
            database = root / "telemetry.db"
            store = autopilot.TelemetryStore(database)
            stack.callback(store.close)
            jobs = []
            for name in ("daily", "daemon_daily"):
                proc = subprocess.Popen(
                    [sys.executable, "-I", "-B", "-S", "-c", SCHEDULED,
                     str(Path(autopilot.__file__).resolve().parents[1]), folder, name],
                    env=dict(os.environ, HOME=folder, USERPROFILE=folder, LOCALAPPDATA=folder, APPDATA=folder),
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                stack.enter_context(proc)
                stack.callback(lambda p=proc: p.kill() if p.poll() is None else None)
                jobs.append(proc)
            deadline = time.monotonic() + 20
            while len(list(root.glob("*.ready"))) < 2:
                if time.monotonic() >= deadline or any(p.poll() is not None for p in jobs):
                    self.fail("both scheduled callers must start")
                time.sleep(0.02)
            (root / "start").touch()
            receipts = []
            for proc in jobs:
                out, err = proc.communicate(timeout=100)
                self.assertEqual(proc.returncode, 0, err[-1800:])
                receipts.append(json.loads(out))
            self.assertEqual(receipts[0], receipts[1])
            result = receipts[0]
            self.assertIn(result["trigger"], ("daily", "daemon_daily"))
            self.assertEqual(result["local"]["tcp_loopback_verified_bytes"], 16 * 1024**2)
            if result["local"]["cpu_caps"]["native"]:
                self.assertTrue(result["local"]["wormhole_ok"])
                self.assertEqual(result["local"]["wormhole_transfer_bytes"], 16 * 1024**2)
            self.assertEqual(json.loads((root / "latest_report.json").read_bytes()), result)
            with closing(sqlite3.connect(database)) as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0], 1)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM cluster_reports").fetchone()[0], 1)
                # A later manual report cannot displace today's stored scheduled result.
                (root / "latest_report.json").write_text('{"trigger":"manual","run_id":9999}', encoding="utf-8")
                self.assertEqual(store.daily_result(root), result)
                # Previous schema versions stored the final delivery flag only in latest_report.json.
                old = {k: v for k, v in result.items() if k not in ("run_id", "pushed_to_hub")}
                conn.execute("UPDATE runs SET summary_json=?", (json.dumps(old),))
                conn.commit()
                self.assertIsNone(store.daily_result(root)["pushed_to_hub"])
                (root / "latest_report.json").write_text(json.dumps(result), encoding="utf-8")
                self.assertEqual(store.daily_result(root), result)
                conn.execute("UPDATE runs SET ts_local='2000-01-01 00:00:00'")
                conn.commit()
                self.assertIsNone(store.daily_result(root))

    def test_failed_owner_releases_lease_and_manual_runs_are_independent(self):
        with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
            root = Path(folder)
            store = autopilot.TelemetryStore(root / "telemetry.db")
            stack.callback(store.close)
            outcomes = [OSError("cancelled cycle"), {"ok": True}, {"manual": 1}, {"manual": 2}]
            config = autopilot.OpsConfig()
            with patch.object(autopilot, "_run_autopilot_cycle", side_effect=outcomes) as cycle:
                with self.assertRaisesRegex(OSError, "cancelled"):
                    autopilot.run_daily_autopilot(config, store, "daily", root)
                self.assertEqual(autopilot.run_daily_autopilot(config, store, "daemon_daily", root), {"ok": True})
                for index in (1, 2):
                    self.assertEqual(autopilot.run_daily_autopilot(config, store, "manual", root), {"manual": index})
                self.assertEqual(cycle.call_count, 4)
