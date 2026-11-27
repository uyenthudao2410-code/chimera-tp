"""Verification suite for v25.0 CHIMERA-HYDRA-STREAM (All 3 Pillars).

Covers:
1. Pillar 1 (EgressMembraneProxy):
   - RFC 1035 DNS Type-A packet build & compressed-pointer parse
   - Per-(host, ip) UCB1 Bandit + circuit-breaker cooldown + Hedged TCP Race
   - Standby pre-warmed socket pool hit & cleanup
   - Peer-egress failover rescue when direct PoPs fail
2. Pillar 2 (OpenAI Hydra SSE Conduit + Symbiote):
   - Declarative multi-gateway AppRegistry discovery & model routing
   - Zero-IQ-Loss verbatim payload forwarding (never mutates reasoning_effort / tools)
   - Chunked SSE pass-through with 16ms frame coalescing & 0ms TTFT first-chunk flush
   - Detached Immortal Harvest on mid-stream client abort -> instant LZ4 replay HIT
   - Merkle Prefix-Cache break detection & PulseBus alert
3. Pillar 3 (HyperDesk Kernel Socket-Owner Immunity):
   - Zero-subprocess Win32 GetExtendedTcpTable real scan on Windows
   - Listening local gateways + VIP loopback peer PIDs strictly immune from caging
"""

from __future__ import annotations

import http.client
import http.server
import json
import os
import socket
import struct
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from chimera_tp.autopilot import OpsConfig
from chimera_tp.dashboard import ChimeraDaemon
from chimera_tp.platform.egress_membrane import (
    EgressMembraneProxy,
    _PopBandit,
    _build_dns_a_query,
    _parse_dns_a_response,
)
from chimera_tp.platform.hyper_desk import HyperDeskEngine, _win_tcp_socket_immunity


class _FakeOpenAIServer:
    """Controllable local OpenAI-compatible SSE server recording verbatim payloads."""

    def __init__(self) -> None:
        self.received_bodies: list[dict] = []
        self.received_raw: list[bytes] = []
        self.call_count = 0
        self.slow_mid_stream = False
        self.chunk_count = 12
        self.chunk_delay_s = 0.002
        self.models = [{"id": "deepseek-v4.1-flash-sg", "object": "model", "owned_by": "test-gw"}]

        srv_ref = self

        class _H(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_args):
                pass

            def do_GET(self):
                if self.path == "/v1/models":
                    b = json.dumps({"object": "list", "data": srv_ref.models}).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(b)))
                    self.end_headers()
                    self.wfile.write(b)
                    return
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def do_POST(self):
                cl = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(cl) if cl > 0 else b""
                srv_ref.call_count += 1
                srv_ref.received_raw.append(raw)
                body = json.loads(raw.decode("utf-8") or "{}")
                srv_ref.received_bodies.append(body)

                if not body.get("stream"):
                    resp_b = json.dumps({
                        "id": "chatcmpl-test",
                        "object": "chat.completion",
                        "model": body.get("model"),
                        "echo_effort": body.get("reasoning_effort"),
                    }).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(resp_b)))
                    self.end_headers()
                    self.wfile.write(resp_b)
                    return

                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "close")
                self.end_headers()
                try:
                    for i in range(srv_ref.chunk_count):
                        evt = f'data: {{"choices":[{{"delta":{{"content":"tok{i} "}}}}]}}\n\n'.encode("utf-8")
                        self.wfile.write(evt)
                        self.wfile.flush()
                        if srv_ref.slow_mid_stream and i == 1:
                            time.sleep(0.18)
                        elif srv_ref.chunk_delay_s > 0:
                            time.sleep(srv_ref.chunk_delay_s)
                    self.wfile.write(b"data: [DONE]\n\n")
                    self.wfile.flush()
                except OSError:
                    pass

        self._httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _H)
        self.port = int(self._httpd.server_address[1])
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()


class TestV25HydraStream(unittest.TestCase):
    def test_01_dns_packet_build_and_compressed_response_parse(self) -> None:
        txid = 0x42A1
        q = _build_dns_a_query("www.example.com", txid)
        self.assertEqual(struct.unpack("!H", q[:2])[0], txid)
        self.assertIn(b"\x03www\x07example\x03com\x00", q)

        # Construct a valid compressed DNS A response with two IPv4 answers
        q_section = q[12:]
        hdr = struct.pack("!HHHHHH", txid, 0x8180, 1, 2, 0, 0)
        ans1 = b"\xc0\x0c" + struct.pack("!HHIH", 1, 1, 120, 4) + socket.inet_aton("43.174.162.158")
        ans2 = b"\xc0\x0c" + struct.pack("!HHIH", 1, 1, 60, 4) + socket.inet_aton("43.169.32.91")
        ips, ttl = _parse_dns_a_response(hdr + q_section + ans1 + ans2, txid)
        self.assertEqual(ips, ["43.174.162.158", "43.169.32.91"])
        self.assertEqual(ttl, 60)
        # Wrong txid rejected
        self.assertEqual(_parse_dns_a_response(hdr + q_section + ans1, txid + 1), ([], 0))

    def test_02_pop_bandit_ucb1_cooldown_and_hedged_connect_rescue(self) -> None:
        bandit = _PopBandit()
        bandit.record("api.test", "10.0.0.1", False, 2500.0)
        bandit.record("api.test", "10.0.0.2", True, 5.0)
        ranked = bandit.rank("api.test", ["10.0.0.1", "10.0.0.2"])
        self.assertEqual(ranked[0], "10.0.0.2")
        snap = bandit.snapshot()
        by_ip = {row["ip"]: row for row in snap}
        self.assertEqual(by_ip["10.0.0.1"]["circuit"], "OPEN")
        self.assertEqual(by_ip["10.0.0.2"]["circuit"], "CLOSED")

        # Live hedged CONNECT test: candidate 0 is unreachable/stalled, candidate 1 is a live TCP echo server
        echo_srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        echo_srv.bind(("127.0.0.1", 0))
        echo_srv.listen(16)
        echo_port = echo_srv.getsockname()[1]
        stop_echo = threading.Event()

        def _accept_loop():
            echo_srv.settimeout(0.2)
            while not stop_echo.is_set():
                try:
                    c, _ = echo_srv.accept()
                    data = c.recv(1024)
                    if data:
                        c.sendall(b"ECHO:" + data)
                    c.close()
                except OSError:
                    continue

        t = threading.Thread(target=_accept_loop, daemon=True)
        t.start()

        # First IP simulates slow/failing PoP (127.0.0.2 on unused or refused / TEST-NET-1 blackhole),
        # second IP is live 127.0.0.1
        real_create = socket.create_connection

        def _mock_create(addr, timeout=None, *args, **kwargs):
            ip, port = addr
            if ip == "198.51.100.1":
                time.sleep(0.35)
                raise TimeoutError("simulated SYN drop on bad PoP")
            return real_create(addr, timeout=timeout, *args, **kwargs)

        proxy = EgressMembraneProxy(
            listen_host="127.0.0.1",
            listen_port=0,
            custom_resolver=lambda _h: ["198.51.100.1", "127.0.0.1"],
            hedge_delay_ms=40.0,
            connect_attempt_timeout_s=0.6,
            enable_standby_pool=True,
        ).start()

        try:
            with mock.patch("chimera_tp.platform.egress_membrane.socket.create_connection", side_effect=_mock_create):
                # Call #1: primary 198.51.100.1 stalls -> hedged race rescues via 127.0.0.1 in ~45ms!
                t0 = time.perf_counter()
                s = real_create(("127.0.0.1", proxy.addr[1]), timeout=3.0)
                s.sendall(f"CONNECT api.anycast.test:{echo_port} HTTP/1.1\r\nHost: api.anycast.test:{echo_port}\r\n\r\n".encode())
                hdr = s.recv(4096)
                elapsed_ms = (time.perf_counter() - t0) * 1000.0
                self.assertIn(b"200 Connection Established", hdr)
                self.assertIn(b"X-Chimera-PoP: 127.0.0.1", hdr)
                self.assertIn(b"X-Chimera-Route: hedged", hdr)
                self.assertLess(elapsed_ms, 280.0)
                s.sendall(b"ping-hydra")
                self.assertEqual(s.recv(1024), b"ECHO:ping-hydra")
                s.close()

                # Wait for failing background attempt to finish & cool down 198.51.100.1
                time.sleep(0.45)

                # Call #2: UCB1 bandit now picks 127.0.0.1 IMMEDIATELY at t=0 (route=direct, <30ms!)
                t1 = time.perf_counter()
                s2 = real_create(("127.0.0.1", proxy.addr[1]), timeout=3.0)
                s2.sendall(f"CONNECT api.anycast.test:{echo_port} HTTP/1.1\r\nHost: api.anycast.test:{echo_port}\r\n\r\n".encode())
                hdr2 = s2.recv(4096)
                elapsed2_ms = (time.perf_counter() - t1) * 1000.0
                self.assertIn(b"200 Connection Established", hdr2)
                self.assertIn(b"X-Chimera-PoP: 127.0.0.1", hdr2)
                self.assertIn(b"X-Chimera-Route: direct", hdr2)
                self.assertLess(elapsed2_ms, 100.0)
                s2.sendall(b"ping-2")
                self.assertEqual(s2.recv(1024), b"ECHO:ping-2")
                s2.close()

                # Allow standby pre-warm to settle (host is now hot >= 2 hits), then Call #3 hits standby!
                time.sleep(0.15)
                s3 = real_create(("127.0.0.1", proxy.addr[1]), timeout=3.0)
                s3.sendall(f"CONNECT api.anycast.test:{echo_port} HTTP/1.1\r\nHost: api.anycast.test:{echo_port}\r\n\r\n".encode())
                hdr3 = s3.recv(4096)
                self.assertIn(b"200 Connection Established", hdr3)
                self.assertIn(b"X-Chimera-Route: standby", hdr3)
                s3.sendall(b"ping-3")
                self.assertEqual(s3.recv(1024), b"ECHO:ping-3")
                s3.close()

            st = proxy.stats()
            self.assertGreaterEqual(st["hedged_rescues"], 1)
            self.assertGreaterEqual(st["standby_hits"], 1)
            pops = proxy.pop_bandit_stats()
            pop_map = {p["ip"]: p for p in pops}
            self.assertEqual(pop_map["198.51.100.1"]["circuit"], "OPEN")
            self.assertEqual(pop_map["127.0.0.1"]["circuit"], "CLOSED")
        finally:
            stop_echo.set()
            proxy.close()
            echo_srv.close()

    def test_03_peer_egress_failover_rescue(self) -> None:
        # Upstream TCP echo server
        echo_srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        echo_srv.bind(("127.0.0.1", 0))
        echo_srv.listen(8)
        echo_port = echo_srv.getsockname()[1]
        stop_echo = threading.Event()

        def _accept_loop():
            echo_srv.settimeout(0.2)
            while not stop_echo.is_set():
                try:
                    c, _ = echo_srv.accept()
                    d = c.recv(1024)
                    if d:
                        c.sendall(b"PEER:" + d)
                    c.close()
                except OSError:
                    continue

        threading.Thread(target=_accept_loop, daemon=True).start()

        # Peer proxy CAN reach 127.0.0.1; primary proxy fails all direct IPs and fails over to peer proxy!
        peer_proxy = EgressMembraneProxy(
            listen_host="127.0.0.1",
            listen_port=0,
            custom_resolver=lambda _h: ["127.0.0.1"],
            enable_standby_pool=False,
            allow_private_peer_hop=True,
        ).start()
        primary_proxy = EgressMembraneProxy(
            listen_host="127.0.0.1",
            listen_port=0,
            custom_resolver=lambda _h: ["198.51.100.99"],
            connect_attempt_timeout_s=0.15,
            peer_proxy_resolver=lambda: peer_proxy.url,
            enable_standby_pool=False,
        ).start()

        real_create = socket.create_connection

        def _mock_create(addr, timeout=None, *args, **kwargs):
            if addr[0] == "198.51.100.99":
                raise OSError("direct route down")
            return real_create(addr, timeout=timeout, *args, **kwargs)

        try:
            with mock.patch("chimera_tp.platform.egress_membrane.socket.create_connection", side_effect=_mock_create):
                s = real_create(("127.0.0.1", primary_proxy.addr[1]), timeout=3.0)
                s.sendall(f"CONNECT remote.api.test:{echo_port} HTTP/1.1\r\nHost: remote.api.test:{echo_port}\r\n\r\n".encode())
                hdr = s.recv(4096)
                self.assertIn(b"200 Connection Established", hdr)
                self.assertIn(b"X-Chimera-Route: peer", hdr)
                s.sendall(b"hello")
                self.assertEqual(s.recv(1024), b"PEER:hello")
                s.close()
            self.assertEqual(primary_proxy.stats()["peer_egress_rescues"], 1)
        finally:
            stop_echo.set()
            primary_proxy.close()
            peer_proxy.close()
            echo_srv.close()

    def test_04_kernel_socket_owner_immunity_zero_subprocess(self) -> None:
        # 1. Verify real Win32 GetExtendedTcpTable detects our own listening socket with 0 subprocesses
        if os.name == "nt":
            srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            srv.bind(("127.0.0.1", 0))
            srv.listen(4)
            my_port = srv.getsockname()[1]
            try:
                with mock.patch.object(subprocess, "check_output", side_effect=AssertionError("must not spawn subprocess")), \
                     mock.patch.object(subprocess, "run", side_effect=AssertionError("must not spawn subprocess")):
                    res = _win_tcp_socket_immunity({os.getpid()})
                self.assertIn(os.getpid(), res["listening_pids"])
                self.assertIn(my_port, res["listening_ports"].get(os.getpid(), []))
                self.assertLess(res["scan_ms"], 50.0)
            finally:
                srv.close()

        # 2. Verify HyperDeskEngine strictly excludes listening & VIP-peer PIDs from caging
        with tempfile.TemporaryDirectory() as td:
            hd = HyperDeskEngine(ops_dir=Path(td))
            try:
                hd._tcp_immunity_fn = lambda vip: {
                    "listening_pids": {8888},
                    "vip_peer_pids": {9999} if vip and 7777 in vip else set(),
                    "listening_ports": {8888: [8788]},
                    "scan_ms": 0.15,
                }
                procs = [
                    {"pid": 7777, "ppid": 100, "name": "deepseek harness", "ws_mb": 200.0, "priv_mb": 200.0},
                    {"pid": 8888, "ppid": 50, "name": "pythonw", "ws_mb": 40.0, "priv_mb": 40.0},
                    {"pid": 9999, "ppid": 50, "name": "pythonw", "ws_mb": 40.0, "priv_mb": 40.0},
                    {"pid": 5555, "ppid": 50, "name": "pythonw", "ws_mb": 40.0, "priv_mb": 40.0},
                ]
                protected = hd._protected_pid_set(procs, fg_pid=7777, vip_pids={7777})
                self.assertIn(8888, protected)
                self.assertIn(9999, protected)
                self.assertNotIn(5555, protected)
                # Direct _cage_background_pid guard must refuse immune PIDs
                self.assertEqual(hd._cage_background_pid(8888, 0xF00), (False, False))
                self.assertEqual(hd._cage_background_pid(9999, 0xF00), (False, False))
            finally:
                hd.close()

    def test_05_hydra_sse_conduit_coalescing_immortal_harvest_and_prefix_audit(self) -> None:
        fake_llm = _FakeOpenAIServer()
        with tempfile.TemporaryDirectory() as td:
            cfg = OpsConfig(
                node_name="test-hydra",
                role="controller",
                dashboard_bind="127.0.0.1:0",
                beam_port=0,
                rpc_v4_port=0,
                rpc_v6_port=-1,
                query_port=0,
                warp_port=-1,
                edge_proxy_port=-1,
                allowed_query_roots=[td],
                search_roots=[td],
                edge_targets={},
                phantom_enabled=False,
                tquota_relay_url="http://127.0.0.1:1",  # unreachable default -> forces AppRegistry federation
            )
            daemon = ChimeraDaemon(config=cfg, ops_dir=Path(td) / "ops", auto_seed_on_empty=False).start()
            try:
                # Register fake LLM gateway declaratively via AppRegistry (zero vendor hardcoding!)
                daemon.platform.registry.register_live({
                    "app": "local-llm-gw",
                    "pid": os.getpid(),
                    "cwd": td,
                    "port": fake_llm.port,
                    "needs": ["openai", "egress"],
                })
                anchor_port = daemon.http_addr[1]

                # A. /v1/openai/v1/models discovers fake_llm declaratively and caches route
                c = http.client.HTTPConnection("127.0.0.1", anchor_port, timeout=5.0)
                c.request("GET", "/v1/openai/v1/models")
                r = c.getresponse()
                models_data = json.loads(r.read().decode("utf-8"))
                c.close()
                mids = [m["id"] for m in models_data.get("data", [])]
                self.assertIn("deepseek-v4.1-flash-sg", mids)

                # B. Zero-IQ-Loss SSE streaming + 16ms Frame Coalescer
                payload = {
                    "model": "deepseek-v4.1-flash-sg",
                    "stream": True,
                    "reasoning_effort": "high",
                    "tools": [{"type": "function", "function": {"name": "read_file"}}],
                    "messages": [
                        {"role": "system", "content": "sys-prompt-v1"},
                        {"role": "user", "content": "hello world"},
                    ],
                }
                raw_payload = json.dumps(payload).encode("utf-8")
                c = http.client.HTTPConnection("127.0.0.1", anchor_port, timeout=5.0)
                c.request(
                    "POST",
                    "/v1/openai/v1/chat/completions",
                    body=raw_payload,
                    headers={
                        "Content-Type": "application/json",
                        "X-Chimera-Session": "sess-1",
                        "X-Chimera-Coalesce-Ms": "20",
                    },
                )
                r = c.getresponse()
                self.assertEqual(r.status, 200)
                self.assertEqual(r.getheader("X-Chimera-Conduit"), "hydra-sse")
                self.assertEqual(r.getheader("X-Chimera-Prefix-Clean"), "1")
                stream_bytes = r.read()
                c.close()
                self.assertIn(b"tok0 ", stream_bytes)
                self.assertIn(b"tok11 ", stream_bytes)
                self.assertIn(b"[DONE]", stream_bytes)
                # Zero-IQ-Loss invariant: exact bytes forwarded verbatim!
                self.assertEqual(fake_llm.received_raw[-1], raw_payload)
                self.assertEqual(fake_llm.received_bodies[-1]["reasoning_effort"], "high")

                # Coalescing reduced flush count compared to 12 raw upstream chunks
                st = daemon.platform.openai_conduit_stats()
                self.assertGreaterEqual(st["sse_chunks_in"], 4)
                self.assertLessEqual(st["sse_flushes_out"], st["sse_chunks_in"])

                # C. Merkle Prefix-Cache Break Detection
                broken_payload = {
                    "model": "deepseek-v4.1-flash-sg",
                    "stream": False,
                    "reasoning_effort": "high",
                    "messages": [
                        {"role": "system", "content": "MUTATED-sys-prompt"},
                        {"role": "user", "content": "hello world"},
                    ],
                }
                c = http.client.HTTPConnection("127.0.0.1", anchor_port, timeout=5.0)
                c.request(
                    "POST",
                    "/v1/openai/v1/chat/completions",
                    body=json.dumps(broken_payload).encode("utf-8"),
                    headers={"Content-Type": "application/json", "X-Chimera-Session": "sess-1"},
                )
                r = c.getresponse()
                j = json.loads(r.read().decode("utf-8"))
                c.close()
                self.assertEqual(r.status, 200)
                self.assertEqual(r.getheader("X-Chimera-Prefix-Clean"), "0")
                self.assertEqual(j["echo_effort"], "high")
                self.assertGreaterEqual(daemon.platform.openai_conduit_stats()["prefix_breaks"], 1)

                # D. Detached Immortal Harvest: client aborts mid-stream -> retry replays from LZ4 RAM (0 upstream calls!)
                fake_llm.slow_mid_stream = True
                fake_llm.chunk_count = 6
                abort_payload = {
                    "model": "deepseek-v4.1-flash-sg",
                    "stream": True,
                    "reasoning_effort": "high",
                    "messages": [
                        {"role": "system", "content": "immortal-sys"},
                        {"role": "user", "content": "long-turn-abort-test"},
                    ],
                }
                abort_raw = json.dumps(abort_payload).encode("utf-8")
                calls_before = fake_llm.call_count

                # Open raw socket, read headers + first chunk, then hard-close mid-stream!
                raw_s = socket.create_connection(("127.0.0.1", anchor_port), timeout=5.0)
                req_wire = (
                    f"POST /v1/openai/v1/chat/completions HTTP/1.1\r\n"
                    f"Host: 127.0.0.1:{anchor_port}\r\n"
                    f"Content-Type: application/json\r\n"
                    f"Content-Length: {len(abort_raw)}\r\n"
                    f"X-Chimera-Session: sess-imm\r\n"
                    f"X-Chimera-Coalesce-Ms: 0\r\n\r\n"
                ).encode("ascii") + abort_raw
                raw_s.sendall(req_wire)
                first_part = raw_s.recv(4096)
                self.assertIn(b"200 OK", first_part)
                # Simulate abrupt client drop (RST/close before [DONE])
                raw_s.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
                raw_s.close()

                # Wait briefly for detached background harvester to finish draining upstream into LZ4
                deadline = time.monotonic() + 3.0
                while time.monotonic() < deadline:
                    if daemon.platform.openai_conduit_stats()["immortal_completed"] >= 1:
                        break
                    time.sleep(0.05)
                self.assertGreaterEqual(daemon.platform.openai_conduit_stats()["immortal_completed"], 1)
                self.assertEqual(fake_llm.call_count, calls_before + 1)

                # Retry exact same turn -> MUST replay 100% of SSE bytes from RAM with 0 new upstream calls!
                c = http.client.HTTPConnection("127.0.0.1", anchor_port, timeout=5.0)
                c.request(
                    "POST",
                    "/v1/openai/v1/chat/completions",
                    body=abort_raw,
                    headers={"Content-Type": "application/json", "X-Chimera-Session": "sess-imm"},
                )
                r = c.getresponse()
                self.assertEqual(r.status, 200)
                self.assertEqual(r.getheader("X-Chimera-Immortal"), "HIT")
                replayed = r.read()
                c.close()
                self.assertIn(b"tok0 ", replayed)
                self.assertIn(b"tok5 ", replayed)
                self.assertIn(b"[DONE]", replayed)
                self.assertEqual(fake_llm.call_count, calls_before + 1)
                self.assertGreaterEqual(daemon.platform.openai_conduit_stats()["immortal_replays"], 1)

                # E. New telemetry endpoints respond 200
                for ep in ("/v1/egress/pops", "/v1/openai/conduit/stats"):
                    c = http.client.HTTPConnection("127.0.0.1", anchor_port, timeout=5.0)
                    c.request("GET", ep)
                    r = c.getresponse()
                    d = json.loads(r.read().decode("utf-8"))
                    c.close()
                    self.assertEqual(r.status, 200)
                    self.assertTrue(d.get("ok"))
            finally:
                daemon.close()
                fake_llm.close()


if __name__ == "__main__":
    unittest.main()
