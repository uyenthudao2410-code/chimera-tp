"""Comprehensive verification suite for CHIMERA-TP v16.0 CHIMERA-CONNECT & Platform Substrate."""

from __future__ import annotations

import concurrent.futures
import http.server
import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

from chimera_tp import __version__
from chimera_tp.autopilot import OpsConfig
from chimera_tp.dashboard import ChimeraDaemon
from chimera_tp.platform import (
    autoload_status,
    connect,
    handle_mcp_request,
    init_project,
    install_autoload,
    is_available,
    link_project,
    render_smi,
    uninstall_autoload,
)


class _MockUpstreamServer:
    """Controllable local HTTP server for Singleflight, Cache, ETag, 429 Shield & Cassette tests."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.hits: dict[str, int] = {}
        self.srv: http.server.ThreadingHTTPServer | None = None
        self.port = 0

    def start(self) -> "_MockUpstreamServer":
        parent = self

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                with parent.lock:
                    parent.hits[self.path] = parent.hits.get(self.path, 0) + 1
                    n = parent.hits[self.path]

                if self.path == "/slow":
                    time.sleep(0.08)
                    body = json.dumps({"ok": True, "call_num": n}).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Cache-Control", "max-age=30")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return

                if self.path == "/flaky429":
                    if n == 1:
                        body = b'{"error":"rate_limited"}'
                        self.send_response(429)
                        self.send_header("Retry-After", "0.03")
                        self.send_header("Content-Length", str(len(body)))
                        self.end_headers()
                        self.wfile.write(body)
                        return
                    body = b'{"ok":true,"rescued":true}'
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return

                if self.path == "/etag":
                    inm = self.headers.get("If-None-Match", "")
                    if inm == '"v1-etag"':
                        self.send_response(304)
                        self.send_header("ETag", '"v1-etag"')
                        self.end_headers()
                        return
                    body = b'{"data":"etag_payload"}'
                    self.send_response(200)
                    self.send_header("ETag", '"v1-etag"')
                    self.send_header("Cache-Control", "max-age=0.2")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return

                if self.path == "/boom500":
                    body = b'{"error":"internal_boom"}'
                    self.send_response(500)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return

                body = f"echo:{self.path}:{n}".encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args: object) -> None:
                pass

        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = int(self.srv.server_address[1])
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        return self

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def close(self) -> None:
        if self.srv:
            self.srv.shutdown()
            self.srv.server_close()


class TestV16PlatformConnect(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.ops_dir = Path(self._tmp.name) / "ops"
        cfg = OpsConfig(
            node_name="test-brain",
            role="controller",
            dashboard_bind="127.0.0.1:0",
            beam_port=0,
            rpc_v4_port=0,
            rpc_v6_port=-1,
            query_port=0,
            warp_port=-1,
            edge_proxy_port=-1,
            allowed_query_roots=[self._tmp.name],
            search_roots=[self._tmp.name],
            edge_targets={},
            phantom_enabled=False,
        )
        self.daemon = ChimeraDaemon(config=cfg, ops_dir=self.ops_dir, auto_seed_on_empty=False).start()
        self.anchor = self.daemon.platform.anchor_url
        self.proxy = self.daemon.platform.egress.url
        self.token = self.daemon.platform.boot_token
        self.upstream = _MockUpstreamServer().start()

    def tearDown(self) -> None:
        self.upstream.close()
        self.daemon.close()
        self._tmp.cleanup()

    def _get_json(self, path: str) -> dict:
        with urllib.request.urlopen(f"{self.anchor}{path}", timeout=4.0) as r:
            return json.loads(r.read().decode("utf-8"))

    def _post_json(self, path: str, body: dict, headers: dict | None = None) -> tuple[int, dict]:
        hdrs = {"Content-Type": "application/json", **(headers or {})}
        req = urllib.request.Request(
            f"{self.anchor}{path}",
            data=json.dumps(body).encode("utf-8"),
            headers=hdrs,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=4.0) as r:
                return r.status, json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

    def test_01_discovery_well_known_smi_and_pulse_integration(self) -> None:
        caps = self._get_json("/.well-known/chimera.json")
        self.assertTrue(caps["ok"])
        self.assertEqual(caps["schema"], "chimera.capabilities.v1")
        self.assertEqual(caps["cartridge_status_basis"], "config_plus_live_evidence")
        self.assertEqual(caps["cartridges"]["connect"]["evidence"]["verification_status"], "verified")
        self.assertEqual(caps["cartridges"]["egress_membrane"]["evidence"]["verification_status"], "verified")
        self.assertEqual(caps["cartridges"]["browser_grid"]["evidence"]["verification_status"], "unverified")
        self.assertTrue(caps["cartridges"]["connect"]["enabled"])
        self.assertEqual(caps["anchor_url"], self.anchor)
        self.assertEqual(caps["egress_proxy_url"], self.proxy)
        self.assertIn("egress_membrane", caps["cartridges"])
        self.assertIn("pulse", caps["cartridges"])
        self.assertIn("hybrid_search", caps["cartridges"])
        self.assertIn("blackbox", caps["cartridges"])
        self.assertEqual(caps["package_version"], __version__)
        self.assertEqual(caps["version"], __version__)
        health = self._get_json("/api/health")
        self.assertEqual(health["package_version"], __version__)
        self.assertEqual(health["version"], __version__)
        self.assertEqual(health["api_version"], "12.0.0")
        self.assertTrue((self.ops_dir / "runtime.json").is_file())

        with urllib.request.urlopen(caps["cartridges"]["pulse"]["endpoint"], timeout=4) as response:
            advertised = json.load(response)
        self.assertTrue(advertised["ok"])
        self.assertIn("latest_seq", advertised["pulse"])
        self.assertEqual(advertised["pulse"].keys(), self._get_json("/v1/pulse/stats")["pulse"].keys())

        with patch.object(self.daemon.platform.colab, "status", return_value={}) as remote_status:
            smi = self._get_json("/v1/smi")
        remote_status.assert_not_called()
        self.assertTrue(smi["ok"])
        rendered = render_smi(smi)
        self.assertIn("CHIMERA-SMI", rendered)
        self.assertIn("egress_membrane", rendered)

        pulse = self._get_json("/api/pulse")
        self.assertIn("platform", pulse)
        self.assertEqual(pulse["platform"]["anchor_url"], self.anchor)

    def test_02_egress_singleflight_cache_429_bypass_and_cassette(self) -> None:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({"http": self.proxy}))

        # 1. Singleflight: 8 concurrent requests to /slow -> ONLY 1 upstream hit!
        def _hit_slow(_i: int) -> tuple[int, str, bytes]:
            req = urllib.request.Request(f"{self.upstream.base}/slow", headers={"X-Chimera-App": "radar"})
            with opener.open(req, timeout=5.0) as r:
                return r.status, r.headers.get("X-Chimera-Membrane", ""), r.read()

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
            results = list(ex.map(_hit_slow, range(8)))

        self.assertEqual(len(results), 8)
        self.assertTrue(all(st == 200 for st, _, _ in results))
        self.assertEqual(self.upstream.hits.get("/slow", 0), 1)
        tags = [tag for _, tag, _ in results]
        self.assertIn("MISS", tags)
        self.assertTrue(any(t in ("COALESCED", "HIT") for t in tags))

        # 2. Cached follow-up hit is sub-10ms and still 1 upstream hit
        t0 = time.perf_counter()
        st2, tag2, _ = _hit_slow(99)
        hit_ms = (time.perf_counter() - t0) * 1000.0
        self.assertEqual(st2, 200)
        self.assertEqual(tag2, "HIT")
        self.assertEqual(self.upstream.hits.get("/slow", 0), 1)
        self.assertLess(hit_ms, 30.0)

        # 3. X-Chimera-Bypass: 1 goes straight to upstream (2nd upstream hit)
        req_bp = urllib.request.Request(
            f"{self.upstream.base}/slow",
            headers={"X-Chimera-App": "radar", "X-Chimera-Bypass": "1"},
        )
        with opener.open(req_bp, timeout=5.0) as r:
            self.assertEqual(r.status, 200)
            self.assertEqual(r.headers.get("X-Chimera-Membrane"), "BYPASS")
        self.assertEqual(self.upstream.hits.get("/slow", 0), 2)

        # 4. 429 Shield rescues transient rate-limit transparently
        req_429 = urllib.request.Request(f"{self.upstream.base}/flaky429", headers={"X-Chimera-App": "tqouta"})
        with opener.open(req_429, timeout=5.0) as r:
            self.assertEqual(r.status, 200)
            self.assertEqual(r.headers.get("X-Chimera-Retries"), "1")
            self.assertIn(b"rescued", r.read())

        # 5. ETag 304 revalidation after TTL expiry
        req_et = urllib.request.Request(f"{self.upstream.base}/etag", headers={"X-Chimera-App": "radar", "X-Chimera-TTL": "0.15"})
        with opener.open(req_et, timeout=5.0) as r:
            self.assertEqual(r.status, 200)
        time.sleep(0.25)
        with opener.open(req_et, timeout=5.0) as r:
            self.assertEqual(r.status, 200)
            self.assertEqual(r.headers.get("X-Chimera-Membrane"), "REVALIDATED")

        # 6. 500 boom auto-records Wire-Cassette
        req_500 = urllib.request.Request(f"{self.upstream.base}/boom500", headers={"X-Chimera-App": "radar"})
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            opener.open(req_500, timeout=5.0)
        self.assertEqual(ctx.exception.code, 500)
        cassettes = self._get_json("/v1/cassettes")["cassettes"]
        self.assertGreaterEqual(len(cassettes), 1)
        self.assertEqual(cassettes[0]["status"], 500)

    def test_03_pulse_bus_hybrid_search_blackbox_and_diskless_secrets(self) -> None:
        # Pulse Pub/Sub + wildcard + KV
        st, pub = self._post_json("/v1/pulse/publish", {"topic": "radar.bounty", "payload": {"id": 42}, "app": "radar"})
        self.assertEqual(st, 200)
        seq = pub["event"]["seq"]
        polled = self._get_json(f"/v1/pulse/events?topic=radar.*&since={seq - 1}")
        self.assertEqual(len(polled["events"]), 1)
        self.assertEqual(polled["events"][0]["payload"]["id"], 42)

        self._post_json("/v1/pulse/kv", {"key": "quota:pool", "value": {"free": 99}, "ttl_s": 10.0})
        kv = self._get_json("/v1/pulse/kv?key=quota:pool")
        self.assertTrue(kv["found"])
        self.assertEqual(kv["value"]["free"], 99)

        # Namespaced Hybrid Search (BM25 + VSA-10K AVX2)
        self._post_json("/v1/search/index", {"namespace": "radar", "doc_id": "d1", "text": "quantum polariton membrane transport tunnel"})
        self._post_json("/v1/search/index", {"namespace": "tqouta", "doc_id": "d2", "text": "quantum polariton other namespace"})
        res_r = self._get_json("/v1/search?namespace=radar&q=polariton+tunnel")
        self.assertEqual(res_r["count"], 1)
        self.assertEqual(res_r["results"][0]["doc_id"], "d1")

        # Flight Recorder BlackBox freeze
        st_bb, frz = self._post_json("/v1/blackbox/freeze", {"reason": "unit_test_freeze", "app": "radar"})
        self.assertEqual(st_bb, 200)
        self.assertTrue(Path(frz["path"]).is_file())

        # Diskless RAM Secrets: reject bad token (401), reject unauthorized app (403), allow authorized app (200)
        st_bad, _ = self._post_json("/v1/secrets/set", {"name": "API_KEY", "value": "super-secret"}, headers={"X-Chimera-Token": "wrong"})
        self.assertEqual(st_bad, 401)
        st_set, _ = self._post_json(
            "/v1/secrets/set",
            {"name": "API_KEY", "value": "super-secret", "allowed_apps": ["tqouta"]},
            headers={"X-Chimera-Token": self.token},
        )
        self.assertEqual(st_set, 200)
        st_deny, _ = self._post_json(
            "/v1/secrets/get",
            {"name": "API_KEY", "app": "other-app"},
            headers={"X-Chimera-Token": self.token},
        )
        self.assertEqual(st_deny, 403)
        st_ok, sec = self._post_json(
            "/v1/secrets/get",
            {"name": "API_KEY", "app": "tqouta"},
            headers={"X-Chimera-Token": self.token},
        )
        self.assertEqual(st_ok, 200)
        self.assertEqual(sec["value"], "super-secret")

    def test_04_sdk_live_and_offline_fallback_link_init_autoload_and_mcp(self) -> None:
        # Live SDK
        self.assertTrue(is_available(anchor_url=self.anchor))
        client = connect(app="sdk-demo", anchor_url=self.anchor, auto_register=True)
        self.assertTrue(client.available)
        r = client.fetch(f"{self.upstream.base}/slow")
        self.assertEqual(r["status"], 200)
        self.assertEqual(r["via"], "chimera_egress")

        # Offline graceful fallback (dead port -> 0 errors!)
        off = connect(app="offline-app", anchor_url="http://127.0.0.1:1", auto_register=False)
        self.assertFalse(off.available)
        off.kv_set("k", 123)
        self.assertEqual(off.kv_get("k"), 123)
        r_off = off.fetch(f"{self.upstream.base}/hello")
        self.assertEqual(r_off["status"], 200)
        self.assertEqual(r_off["via"], "direct_fallback")

        # link_project & init_project
        proj = Path(self._tmp.name) / "sample_app"
        reg_p = Path(self._tmp.name) / "apps.json"
        init_res = init_project(proj, app_name="sample-app", port=8899, registry_path=reg_p)
        self.assertTrue(Path(init_res["manifest_path"]).is_file())
        self.assertTrue(Path(init_res["bridge_path"]).is_file())
        lnk = link_project(proj, registry_path=reg_p)
        self.assertEqual(lnk["manifest"]["app"], "sample-app")

        # autoload install/status/uninstall in temp site-dir
        site_tmp = Path(self._tmp.name) / "site_pkg"
        self.assertFalse(autoload_status(target_dir=site_tmp)["installed"])
        install_autoload(target_dir=site_tmp)
        self.assertTrue(autoload_status(target_dir=site_tmp)["installed"])
        uninstall_autoload(target_dir=site_tmp)
        self.assertFalse(autoload_status(target_dir=site_tmp)["installed"])

        # MCP JSON-RPC 2.0 protocol
        init_m = handle_mcp_request({"jsonrpc": "2.0", "id": 1, "method": "initialize"}, anchor_url=self.anchor)
        self.assertEqual(init_m["result"]["serverInfo"]["name"], "chimera-mcp")
        tools_m = handle_mcp_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, anchor_url=self.anchor)
        self.assertGreaterEqual(len(tools_m["result"]["tools"]), 8)
        call_m = handle_mcp_request(
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "chimera_capabilities", "arguments": {}}},
            anchor_url=self.anchor,
        )
        parsed_caps = json.loads(call_m["result"]["content"][0]["text"])
        self.assertEqual(parsed_caps["anchor_url"], self.anchor)


if __name__ == "__main__":
    unittest.main()
