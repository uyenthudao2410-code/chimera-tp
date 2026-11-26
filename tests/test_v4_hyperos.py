"""Comprehensive test suite for CHIMERA-HYPER v4.0 Zero-Weight HyperOS."""

from __future__ import annotations

import http.server
import json
import os
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from chimera_tp.autopilot import OpsConfig
from chimera_tp.code_search import CodeSearchIndex, sanitize_fts_query
from chimera_tp.dashboard import ChimeraDaemon
from chimera_tp.edge_proxy import EdgeGateway, LocalEdgeProxy
from chimera_tp.holo_backup import (
    create_holo_backup,
    restore_holo_backup,
    shannon_entropy,
)
from chimera_tp.nat_buster import (
    NatPunchResponder,
    attempt_direct_punch,
    parse_stun_xor_mapped,
)
from chimera_tp.sentinel import SentinelEngine


class TestV4HyperOS(unittest.TestCase):
    def test_nat_buster_stun_parser_and_loopback_punch(self) -> None:
        tid = b"0123456789ab"
        cookie = 0x2112A442
        ip_raw = int.from_bytes(socket.inet_aton("198.51.100.42"), "big")
        port_raw = 51234
        xor_port = port_raw ^ 0x2112
        xor_ip = ip_raw ^ cookie
        attr = struct.pack("!HHBBHI", 0x0020, 8, 0, 1, xor_port, xor_ip)
        pkt = struct.pack("!HHI", 0x0101, len(attr), cookie) + tid + attr
        self.assertEqual(parse_stun_xor_mapped(pkt, expected_tid=tid), ("198.51.100.42", 51234))
        self.assertIsNone(parse_stun_xor_mapped(pkt, expected_tid=b"wrongtid0000"))

        responder = NatPunchResponder()

        class NatMockHandler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                if self.path == "/api/health":
                    body = json.dumps({"ok": True, "version": "4.0.0"}).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)

            def do_POST(self) -> None:
                if self.path == "/api/nat/punch-offer":
                    clen = int(self.headers.get("Content-Length", "0"))
                    offer = json.loads(self.rfile.read(clen).decode("utf-8"))
                    ack = responder.start_session(offer)
                    body = json.dumps(ack).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)

            def log_message(self, *_args: object) -> None:
                pass

        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), NatMockHandler)
        th = threading.Thread(target=srv.serve_forever, daemon=True)
        th.start()
        try:
            res = attempt_direct_punch(
                f"http://127.0.0.1:{srv.server_address[1]}",
                num_sockets=16,
                spray_count=64,
                timeout_s=2.0,
                local_test_mode=True,
            )
            self.assertTrue(res["punched"])
            self.assertEqual(res["fallback_mode"], "DIRECT_P2P_UDP")
            self.assertGreater(res["direct_rtt_p50_ms"], 0.0)
        finally:
            srv.shutdown()
            srv.server_close()

    def test_edge_gateway_telepathic_prefetch_and_ssrf_guard(self) -> None:
        with self.assertRaises(PermissionError):
            EdgeGateway(targets={"bad": {"url": "http://example.com:80", "prefetch": []}})

        backend_hits = {"root": 0, "metrics": 0}
        html_doc = (
            "<!doctype html><html><head><title>App</title></head><body>"
            + ("<div class='row'>telepathic-edge-row status=OK node=backend</div>\n" * 80)
            + "<script>fetch('/api/metrics').then(r=>r.json())</script></body></html>"
        ).encode("utf-8")
        metrics_json = json.dumps({"ok": True, "qps": 4242, "items": ["alpha"] * 40}).encode("utf-8")

        class BackendHandler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                if self.path == "/":
                    backend_hits["root"] += 1
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(html_doc)))
                    self.end_headers()
                    self.wfile.write(html_doc)
                elif self.path == "/api/metrics":
                    backend_hits["metrics"] += 1
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(metrics_json)))
                    self.end_headers()
                    self.wfile.write(metrics_json)
                else:
                    self.send_response(404)
                    self.end_headers()

            def log_message(self, *_args: object) -> None:
                pass

        backend = http.server.ThreadingHTTPServer(("127.0.0.1", 0), BackendHandler)
        bport = backend.server_address[1]
        threading.Thread(target=backend.serve_forever, daemon=True).start()

        targets = {
            "demo": {
                "url": f"http://127.0.0.1:{bport}",
                "prefetch": ["/api/metrics"],
                "label": "Demo App",
            }
        }
        gw = EdgeGateway(targets=targets)

        class GatewayHandler(http.server.BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                if self.path == "/api/edge/fetch":
                    clen = int(self.headers.get("Content-Length", "0"))
                    req_obj = json.loads(self.rfile.read(clen).decode("utf-8"))
                    res = gw.fetch(**req_obj)
                    body = json.dumps(res).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)

            def log_message(self, *_args: object) -> None:
                pass

        gwsrv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), GatewayHandler)
        threading.Thread(target=gwsrv.serve_forever, daemon=True).start()
        proxy = LocalEdgeProxy(
            listen_host="127.0.0.1",
            listen_port=0,
            peer_http_base=f"http://127.0.0.1:{gwsrv.server_address[1]}",
            targets=targets,
        ).start()
        try:
            pbase = f"http://127.0.0.1:{proxy.addr[1]}"
            with urllib.request.urlopen(f"{pbase}/demo/", timeout=5.0) as r1:
                body1 = r1.read()
                hdr1 = r1.headers.get("X-Chimera-Edge", "")
            self.assertEqual(body1, html_doc)
            self.assertIn("TELEPATHY", hdr1)
            self.assertEqual(backend_hits["root"], 1)
            self.assertEqual(backend_hits["metrics"], 1)

            # Follow-up API request must hit speculative 0-RTT cache with ZERO backend call!
            with urllib.request.urlopen(f"{pbase}/demo/api/metrics", timeout=5.0) as r2:
                body2 = r2.read()
                hdr2 = r2.headers.get("X-Chimera-Edge", "")
            self.assertEqual(body2, metrics_json)
            self.assertEqual(hdr2, "PREFETCH-HIT-0RTT")
            self.assertEqual(backend_hits["metrics"], 1)

            pst = proxy.stats()
            self.assertGreater(pst["saved_pct"], 85.0)
            self.assertEqual(pst["prefetch_hits"], 1)
        finally:
            proxy.close()
            gwsrv.shutdown()
            gwsrv.server_close()
            backend.shutdown()
            backend.server_close()

    def test_sentinel_log_spike_and_service_probes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ops_dir = Path(td) / "ops"
            log_path = Path(td) / "auto-pull.log"
            lines = ["2026-11-25T10:00:00Z INFO ok\n"] * 20 + [
                "2026-11-25T10:01:00Z [HR] ERROR: git fetch failed: fatal: couldn't find remote ref V_Finance\n"
                for _ in range(40)
            ]
            log_path.write_text("".join(lines), encoding="utf-8")

            # Reserve an unused port so probe sees DOWN cleanly
            tmp_s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            tmp_s.bind(("127.0.0.1", 0))
            dead_port = tmp_s.getsockname()[1]
            tmp_s.close()

            cfg = OpsConfig(
                node_name="test-sv",
                role="server",
                watched_query_file=str(log_path),
                allowed_query_roots=[str(td)],
                edge_targets={
                    "dead_svc": {"url": f"http://127.0.0.1:{dead_port}", "prefetch": [], "label": "Dead Svc"}
                },
            )
            eng = SentinelEngine(ops_dir)
            try:
                rep = eng.scan(cfg, probe_timeout_s=0.4)
                self.assertEqual(rep["status"], "ALERT")
                cats = {a["category"] for a in rep["alerts"]}
                self.assertIn("SERVICE_DOWN", cats)
                self.assertIn("LOG_SPIKE", cats)
                spike_alerts = [a for a in rep["alerts"] if a["category"] == "LOG_SPIKE"]
                self.assertTrue(any("git remote prune" in a["diagnosis"] for a in spike_alerts))
            finally:
                eng.close()

    def test_code_search_fts5_merkle_incremental_and_sanitization(self) -> None:
        self.assertEqual(sanitize_fts_query("[HR] ERROR: git/fetch"), '"HR" AND "ERROR" AND "git" AND "fetch"')
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "repos"
            (root / "alpha").mkdir(parents=True)
            (root / "beta").mkdir(parents=True)
            (root / "alpha" / "worker.py").write_text(
                "def hyper_sync_merkle():\n    return 'immortal_v4_ok'\n", encoding="utf-8"
            )
            (root / "beta" / "pull.log").write_text(
                "[HR] ERROR: couldn't find remote ref V_Finance\n", encoding="utf-8"
            )

            idx = CodeSearchIndex(Path(td) / "code_index.db")
            try:
                r1 = idx.incremental_index([root])
                self.assertEqual(r1["total_files"], 2)
                self.assertEqual(r1["updated"], 2)

                r2 = idx.incremental_index([root])
                self.assertEqual(r2["updated"], 0)
                self.assertEqual(r2["skipped_unchanged"], 2)

                res = idx.search("V_Finance")
                self.assertEqual(res["total_hits"], 1)
                self.assertEqual(res["hits"][0]["repo"], "beta")

                res_special = idx.search("[HR] ERROR: remote/ref")
                self.assertGreaterEqual(res_special["total_hits"], 1)

                # Modify 1 file and delete the other
                f_mut = root / "alpha" / "worker.py"
                f_mut.write_text("def updated_fn():\n    return 'quartz_beacon_42'\n", encoding="utf-8")
                (root / "beta" / "pull.log").unlink()
                r3 = idx.incremental_index([root])
                self.assertEqual(r3["updated"], 1)
                self.assertEqual(r3["removed"], 1)
                self.assertEqual(idx.search("V_Finance")["total_hits"], 0)
                self.assertEqual(idx.search("quartz_beacon_42")["total_hits"], 1)

                # Verify SEARCH_IGNORE_DIRS & per-repo quota fairness
                (root / "alpha" / "archive").mkdir()
                (root / "alpha" / "archive" / "ignored.py").write_text("secret_ignored_blob_xyz\n", encoding="utf-8")
                (root / "alpha" / "bundle.min.js").write_text("minified_ignored_xyz\n", encoding="utf-8")
                (root / "zeta").mkdir()
                for j in range(5):
                    (root / "alpha" / f"extra_{j}.py").write_text(f"alpha_{j}\n", encoding="utf-8")
                (root / "zeta" / "needle.py").write_text("def zeta_fair_hit():\n    pass\n", encoding="utf-8")
                idx.incremental_index([root], max_files=20, max_files_per_repo=2)
                self.assertEqual(idx.search("secret_ignored_blob_xyz")["total_hits"], 0)
                self.assertEqual(idx.search("minified_ignored_xyz")["total_hits"], 0)
                self.assertEqual(idx.search("zeta_fair_hit")["total_hits"], 1)
            finally:
                idx.close()

    def test_holo_backup_gf256_2of3_entropy_all_pairs_and_tamper(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            src_dir = Path(td) / "secret_cfg"
            src_dir.mkdir()
            secret_a = src_dir / "config.json"
            secret_b = src_dir / "notes.txt"
            secret_token = b"TOP_SECRET_CHIMERA_KEY_987654321"
            secret_a.write_bytes(b'{"api":"' + secret_token + b'","mode":"hyper"}\n' * 120)
            # Varied realistic content ensures post-compression shard > 1 KiB for asymptotic entropy ~7.9 bits/byte
            secret_b.write_bytes(
                b"\n".join(f"cfg_row_{i:04d}={os.urandom(8).hex()}".encode("ascii") for i in range(180))
            )

            broot = Path(td) / "backups"
            rep = create_holo_backup([secret_a, secret_b], backup_root=broot, backup_id="unit_bk")
            self.assertTrue(rep["ok"])
            self.assertEqual(len(rep["entropies"]), 3)
            for ent in rep["entropies"]:
                self.assertGreater(ent, 7.6)

            bdir = broot / "unit_bk"
            p0 = bdir / "shard_0.chshard"
            p1 = bdir / "shard_1.chshard"
            p2 = bdir / "export_shard_2.chshard"

            # Zero plaintext leakage inside any individual shard
            for sp in (p0, p1, p2):
                self.assertNotIn(secret_token, sp.read_bytes())

            # Every 2-of-3 pair must reconstruct bit-exact files
            for tag, pair in [("01", [p0, p1]), ("02", [p0, p2]), ("12", [p1, p2])]:
                out_dir = Path(td) / f"restore_{tag}"
                r = restore_holo_backup(pair, out_dir=out_dir)
                self.assertTrue(r["sha256_match"])
                self.assertEqual((out_dir / "config.json").read_bytes(), secret_a.read_bytes())
                self.assertEqual((out_dir / "notes.txt").read_bytes(), secret_b.read_bytes())

            # Corrupt 1 byte of shard_2 payload -> integrity verification must reject it
            raw2 = bytearray(p2.read_bytes())
            raw2[-1] ^= 0xFF
            bad_p2 = bdir / "bad_shard_2.chshard"
            bad_p2.write_bytes(bytes(raw2))
            with self.assertRaises(ValueError):
                restore_holo_backup([p0, bad_p2], out_dir=Path(td) / "restore_bad")

    def test_daemon_v4_endpoints_and_zero_weight_rss(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ops_dir = Path(td) / "ops"
            docs_dir = Path(td) / "dev"
            docs_dir.mkdir()
            sample_py = docs_dir / "demo.py"
            sample_py.write_text("def chimera_hyper_v4():\n    return 'v4_ready'\n", encoding="utf-8")

            cfg = OpsConfig(
                node_name="v4-unit",
                role="server",
                dashboard_bind="127.0.0.1:0",
                beam_port=0,
                rpc_v4_port=0,
                rpc_v6_port=-1,
                query_port=0,
                warp_port=-1,
                edge_proxy_port=-1,
                allowed_query_roots=[str(docs_dir)],
                search_roots=[str(docs_dir)],
                edge_targets={},
                backup_targets=[str(sample_py)],
            )
            daemon = ChimeraDaemon(config=cfg, ops_dir=ops_dir, auto_seed_on_empty=False).start()
            base = f"http://127.0.0.1:{daemon.http_addr[1]}"
            try:
                with urllib.request.urlopen(f"{base}/api/health", timeout=4.0) as r:
                    h = json.loads(r.read().decode("utf-8"))
                self.assertIn(h["version"], ("4.0.0", "5.0.0", "6.0.0", "7.0.0", "8.0.0", "9.0.0", "10.0.0", "11.0.0", "12.0.0"))

                # Reindex & search via daemon HTTP
                req_idx = urllib.request.Request(
                    f"{base}/api/search/reindex", data=b"{}", headers={"Content-Type": "application/json"}, method="POST"
                )
                with urllib.request.urlopen(req_idx, timeout=5.0) as r:
                    idx_res = json.loads(r.read().decode("utf-8"))
                self.assertEqual(idx_res["total_files"], 1)

                req_s = urllib.request.Request(
                    f"{base}/api/search",
                    data=json.dumps({"query": "chimera_hyper_v4"}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req_s, timeout=5.0) as r:
                    s_res = json.loads(r.read().decode("utf-8"))
                self.assertEqual(s_res["total_hits"], 1)

                # Sentinel scan
                req_sent = urllib.request.Request(
                    f"{base}/api/sentinel/scan", data=b"{}", headers={"Content-Type": "application/json"}, method="POST"
                )
                with urllib.request.urlopen(req_sent, timeout=5.0) as r:
                    sent_res = json.loads(r.read().decode("utf-8"))
                self.assertIn(sent_res["status"], ("OK", "WARN", "ALERT"))

                # Holo backup create + restore
                req_bk = urllib.request.Request(
                    f"{base}/api/backup/create",
                    data=json.dumps({"backup_id": "daemon_test"}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req_bk, timeout=5.0) as r:
                    bk = json.loads(r.read().decode("utf-8"))
                self.assertTrue(bk["ok"])

                bdir = ops_dir / "holo_backups" / "daemon_test"
                req_rst = urllib.request.Request(
                    f"{base}/api/backup/restore",
                    data=json.dumps(
                        {
                            "backup_id": "daemon_test",
                            "shard_paths": [
                                str(bdir / "shard_1.chshard"),
                                str(bdir / "export_shard_2.chshard"),
                            ],
                        }
                    ).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req_rst, timeout=5.0) as r:
                    rst = json.loads(r.read().decode("utf-8"))
                self.assertTrue(rst["sha256_match"])
            finally:
                daemon.close()

        # Verify fresh ChimeraDaemon process stays well within Zero-Weight 80 MB budget
        code = (
            "import tempfile, json; from pathlib import Path; "
            "from chimera_tp.autopilot import OpsConfig, get_zero_weight_status; "
            "from chimera_tp.dashboard import ChimeraDaemon; "
            "td=tempfile.TemporaryDirectory(); "
            "cfg=OpsConfig(node_name='zw', role='controller', dashboard_bind='127.0.0.1:0', beam_port=0, rpc_v4_port=0, rpc_v6_port=-1, query_port=0, warp_port=-1, edge_proxy_port=0); "
            "d=ChimeraDaemon(cfg, ops_dir=Path(td.name), auto_seed_on_empty=False).start(); "
            "print(json.dumps(get_zero_weight_status())); d.close(); td.cleanup()"
        )
        proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
        zw = json.loads(proc.stdout.strip().splitlines()[-1])
        self.assertTrue(zw["zero_weight_ok"], f"RSS exceeded budget: {zw}")


if __name__ == "__main__":
    unittest.main()
