"""Comprehensive test suite for CHIMERA-HYPER v5.0 PHANTOM-5MS."""

from __future__ import annotations

import base64
import hashlib
import http.server
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from chimera_tp.autopilot import OpsConfig
from chimera_tp.code_search import CodeSearchIndex
from chimera_tp.dashboard import ChimeraDaemon
from chimera_tp.drop_portal import DropPortalStore, pack_ai_context
from chimera_tp.edge_proxy import LocalEdgeProxy
from chimera_tp.ghost_fs import GhostFsEngine
from chimera_tp.ghost_pty import GhostPtyManager
from chimera_tp.medic import MedicEngine
from chimera_tp.phantom_tunnel import (
    PhantomTunnelClient,
    PhantomTunnelServer,
    open_packet,
    seal_packet,
)
from chimera_tp.sentinel import SentinelEngine


class TestV5Phantom(unittest.TestCase):
    def test_phantom_aead_crypto_and_loopback_multiport_tunnel(self) -> None:
        key = os.urandom(32)
        nonce = (1 << 63 | 42).to_bytes(8, "big")
        wire = seal_packet(key, 777, nonce, b"hello-phantom-5ms-ssh-stream")
        opened = open_packet(key, wire)
        self.assertIsNotNone(opened)
        self.assertEqual(opened[0], 777)
        self.assertEqual(opened[2], b"hello-phantom-5ms-ssh-stream")

        # Tampering 1 bit must reject authentication
        bad = bytearray(wire)
        bad[-1] ^= 0x01
        self.assertIsNone(open_packet(key, bytes(bad)))

        # Boot mock HTTP backend + echo server behind PhantomTunnelServer
        class EchoTcp(threading.Thread):
            def __init__(self) -> None:
                super().__init__(daemon=True)
                self.srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.srv.bind(("127.0.0.1", 0))
                self.srv.listen(8)
                self.port = self.srv.getsockname()[1]

            def run(self) -> None:
                while True:
                    try:
                        c, _ = self.srv.accept()
                    except OSError:
                        break
                    data = c.recv(4096)
                    c.sendall(b"PH5_ECHO:" + data)
                    c.close()

            def close(self) -> None:
                self.srv.close()

        echo = EchoTcp()
        echo.start()
        pt_srv = PhantomTunnelServer(fallback_port=0, allowed_forward_ports=[echo.port]).start()

        class OfferHttp(http.server.BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                if self.path == "/api/phantom/offer":
                    cl = int(self.headers.get("Content-Length", "0"))
                    offer = json.loads(self.rfile.read(cl).decode("utf-8"))
                    ack = pt_srv.accept_offer(offer)
                    body = json.dumps(ack).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)

            def log_message(self, *_args: object) -> None:
                pass

        hsrv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), OfferHttp)
        threading.Thread(target=hsrv.serve_forever, daemon=True).start()
        pt_cli = PhantomTunnelClient(
            peer_http_base=f"http://127.0.0.1:{hsrv.server_address[1]}",
            peer_udp_ip="127.0.0.1",
            peer_fallback_port=pt_srv.fallback_port,
            forwards={0: echo.port},
            local_test_mode=True,
        ).start_listeners()
        try:
            st = pt_cli.connect(local_test_mode=True, num_sockets=16, spray_count=64, timeout_s=2.0)
            self.assertTrue(st["connected"])
            self.assertEqual(st["mode"], "PHANTOM_5MS_DIRECT")
            loc_port = pt_cli.bound_ports[echo.port]
            with socket.create_connection(("127.0.0.1", loc_port), timeout=4.0) as s:
                s.sendall(b"tunnel-ok")
                s.shutdown(socket.SHUT_WR)
                chunks = []
                while True:
                    b = s.recv(4096)
                    if not b:
                        break
                    chunks.append(b)
            self.assertEqual(b"".join(chunks), b"PH5_ECHO:tunnel-ok")
        finally:
            pt_cli.close()
            pt_srv.close()
            hsrv.shutdown()
            hsrv.server_close()
            echo.close()

    def test_ghost_pty_persistence_and_cursor_reattach(self) -> None:
        mgr = GhostPtyManager()
        try:
            cmd = [sys.executable, "-c", "import sys; print('PTY_READY', flush=True); line=sys.stdin.readline(); print('GOT:'+line.strip(), flush=True)"]
            meta = mgr.create_session(cmd=cmd)
            sid = meta["session_id"]

            def _read_until(needle: str, start_cur: int) -> tuple[str, int]:
                cur = start_cur
                acc = ""
                deadline = time.perf_counter() + 3.0
                while time.perf_counter() < deadline:
                    r = mgr.read_output(sid, cursor=cur, wait_ms=300)
                    acc += r["text"]
                    cur = r["next_cursor"]
                    if needle in acc:
                        break
                return acc, cur

            t1, cur = _read_until("PTY_READY", 0)
            self.assertIn("PTY_READY", t1)

            mgr.write_input(sid, b"chimera_persist\n")
            t2, cur = _read_until("GOT:chimera_persist", cur)
            self.assertIn("GOT:chimera_persist", t2)

            # Re-attach from cursor 0 recovers complete session transcript
            full = mgr.read_output(sid, cursor=0, wait_ms=100)
            self.assertIn("PTY_READY", full["text"])
            self.assertIn("GOT:chimera_persist", full["text"])
            self.assertTrue(mgr.close_session(sid))
        finally:
            mgr.close_all()

    def test_ghost_fs_containment_etag_conflict_and_webdav(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "dev"
            (root / "repo_a").mkdir(parents=True)
            (root / "repo_a" / "hello.txt").write_bytes(b"initial_v5_text\n")

            fs = GhostFsEngine(root)
            with self.assertRaises(PermissionError):
                fs.read_file("../outside.txt")
            with self.assertRaises(PermissionError):
                fs.write_file("repo_a/.git/HEAD", b"bad")

            lst = fs.list_dir("repo_a")
            self.assertEqual(lst["count"], 1)
            rd = fs.read_file("repo_a/hello.txt")
            self.assertEqual(rd["text"], "initial_v5_text\n")

            w1 = fs.write_file("repo_a/hello.txt", b"updated_v5_text\n", expected_etag=rd["etag"])
            self.assertTrue(w1["ok"])
            with self.assertRaises(FileExistsError):
                fs.write_file("repo_a/hello.txt", b"stale_write\n", expected_etag=rd["etag"])

            # Verify RFC 4918 WebDAV PROPFIND + GET via LocalEdgeProxy backed by ChimeraDaemon
            cfg = OpsConfig(
                node_name="fs-hub",
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
            )
            daemon = ChimeraDaemon(config=cfg, ops_dir=Path(td) / "ops", auto_seed_on_empty=False).start()
            proxy = LocalEdgeProxy(
                listen_host="127.0.0.1",
                listen_port=0,
                peer_http_base=f"http://127.0.0.1:{daemon.http_addr[1]}",
            ).start()
            try:
                pbase = f"http://127.0.0.1:{proxy.addr[1]}"
                req_pf = urllib.request.Request(f"{pbase}/dav/repo_a/", method="PROPFIND", headers={"Depth": "1"})
                with urllib.request.urlopen(req_pf, timeout=5.0) as rpf:
                    self.assertEqual(rpf.status, 207)
                    xml_body = rpf.read().decode("utf-8")
                self.assertIn("hello.txt", xml_body)

                with urllib.request.urlopen(f"{pbase}/dav/repo_a/hello.txt", timeout=5.0) as rg:
                    self.assertEqual(rg.read(), b"updated_v5_text\n")
            finally:
                proxy.close()
                daemon.close()

    def test_medic_forensic_dossier_and_safe_playbook_with_holo_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ops_dir = Path(td) / "ops"
            log_f = Path(td) / "sync.log"
            log_f.write_text(
                "2026-11-25T10:00:00Z INFO start\n"
                "2026-11-25T10:01:00Z MAIL_FAIL_502 gateway timeout\n"
                "2026-11-25T10:02:00Z IMPORTED 2 / 2 mail ok\n",
                encoding="utf-8",
            )
            cfg = OpsConfig(
                node_name="med-test",
                role="server",
                watched_query_file=str(log_f),
                allowed_query_roots=[str(td)],
                backup_targets=[str(log_f)],
                edge_targets={},
            )
            med = MedicEngine(ops_dir)
            with self.assertRaises(ValueError):
                med.run_playbook("rm_rf_everything", cfg)

            inv = med.investigate(cfg, pattern="MAIL_FAIL_502")
            self.assertEqual(inv["matched_count"], 1)
            self.assertIn("MAIL_FAIL_502", inv["context_samples"][0])

            r_tail = med.run_playbook("verify_email_log_tail", cfg, params={"file_path": str(log_f)})
            self.assertTrue(r_tail["ok"])

            # Mutating log rotation must create pre-heal GF(256) snapshot and truncate clean log
            broot = ops_dir / "holo_backups"
            r_rot = med.run_playbook("rotate_large_log", cfg, params={"file_path": str(log_f), "dry_run": False}, backup_root=broot)
            self.assertTrue(r_rot["ok"])
            self.assertTrue(r_rot["pre_snapshot_id"].startswith("pre_rot_"))
            self.assertEqual(log_f.read_text(encoding="utf-8"), "")
            self.assertTrue(Path(r_rot["result"]["rotated_to"]).is_file())

    def test_drop_portal_ttl_and_ai_context_teleporter(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            portal = DropPortalStore(Path(td) / "portal", default_ttl_s=60)
            item = portal.put_item("snippet", b"hello_portal_5ms\n" * 100)
            self.assertGreater(item["saved_pct"], 50.0)
            self.assertEqual(len(portal.list_items()), 1)
            _, raw = portal.get_item(item["item_id"])
            self.assertEqual(raw, b"hello_portal_5ms\n" * 100)
            self.assertTrue(portal.delete_item(item["item_id"]))
            self.assertEqual(len(portal.list_items()), 0)

            root = Path(td) / "repos"
            (root / "proj").mkdir(parents=True)
            (root / "proj" / "mailer.py").write_text(
                "def send_batch():\n    # retry on MAIL_FAIL_502 error\n    return 'MAIL_FAIL_502'\n",
                encoding="utf-8",
            )
            cs = CodeSearchIndex(Path(td) / "code_index.db")
            sent = SentinelEngine(Path(td) / "ops")
            try:
                cs.incremental_index([root])
                pack = pack_ai_context("MAIL_FAIL_502", cs, sentinel=sent, allowed_roots=[root])
                self.assertTrue(pack["ok"])
                self.assertEqual(pack["hits_used"], 1)
                self.assertLess(pack["chars"], 8000)
                self.assertIn("mailer.py", pack["markdown"])
                self.assertIn("retry on MAIL_FAIL_502", pack["markdown"])
            finally:
                cs.close()
                sent.close()

    def test_daemon_v5_endpoints_and_zero_weight_rss(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ops_dir = Path(td) / "ops"
            dev_dir = Path(td) / "dev"
            (dev_dir / "demo").mkdir(parents=True)
            (dev_dir / "demo" / "app.py").write_text("PHANTOM_TOKEN = 'v5_ok'\n", encoding="utf-8")

            cfg = OpsConfig(
                node_name="v5-unit",
                role="server",
                dashboard_bind="127.0.0.1:0",
                beam_port=0,
                rpc_v4_port=0,
                rpc_v6_port=-1,
                query_port=0,
                warp_port=-1,
                edge_proxy_port=-1,
                allowed_query_roots=[str(dev_dir)],
                search_roots=[str(dev_dir)],
                edge_targets={},
                phantom_enabled=True,
            )
            daemon = ChimeraDaemon(config=cfg, ops_dir=ops_dir, auto_seed_on_empty=False).start()
            base = f"http://127.0.0.1:{daemon.http_addr[1]}"
            try:
                h = json.loads(urllib.request.urlopen(f"{base}/api/health", timeout=4.0).read().decode("utf-8"))
                self.assertEqual(h["version"], "5.0.0")

                # FS + Portal + Context Pack + Medic HTTP checks
                fs_l = json.loads(urllib.request.urlopen(f"{base}/api/fs/list?path=demo", timeout=4.0).read().decode("utf-8"))
                self.assertEqual(fs_l["count"], 1)

                req_idx = urllib.request.Request(f"{base}/api/search/reindex", data=b"{}", headers={"Content-Type": "application/json"}, method="POST")
                urllib.request.urlopen(req_idx, timeout=5.0).read()

                req_ctx = urllib.request.Request(
                    f"{base}/api/context/pack",
                    data=json.dumps({"query": "PHANTOM_TOKEN"}).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                ctx = json.loads(urllib.request.urlopen(req_ctx, timeout=5.0).read().decode("utf-8"))
                self.assertIn("PHANTOM_TOKEN", ctx["markdown"])

                req_drop = urllib.request.Request(
                    f"{base}/api/portal/drop",
                    data=json.dumps({"title": "test", "text": "clip_5ms"}).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                dr = json.loads(urllib.request.urlopen(req_drop, timeout=5.0).read().decode("utf-8"))
                self.assertEqual(dr["raw_bytes"], 8)
            finally:
                daemon.close()

        code = (
            "import tempfile, json; from pathlib import Path; "
            "from chimera_tp.autopilot import OpsConfig, get_zero_weight_status; "
            "from chimera_tp.dashboard import ChimeraDaemon; "
            "td=tempfile.TemporaryDirectory(); "
            "cfg=OpsConfig(node_name='zw5', role='controller', dashboard_bind='127.0.0.1:0', beam_port=0, rpc_v4_port=0, rpc_v6_port=-1, query_port=0, warp_port=-1, edge_proxy_port=0, phantom_enabled=False); "
            "d=ChimeraDaemon(cfg, ops_dir=Path(td.name), auto_seed_on_empty=False).start(); "
            "print(json.dumps(get_zero_weight_status())); d.close(); td.cleanup()"
        )
        proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
        zw = json.loads(proc.stdout.strip().splitlines()[-1])
        self.assertTrue(zw["zero_weight_ok"], f"RSS exceeded 80 MB budget: {zw}")


if __name__ == "__main__":
    unittest.main()
