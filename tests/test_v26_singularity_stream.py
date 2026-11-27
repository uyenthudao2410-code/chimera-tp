"""v26.0 CHIMERA-SINGULARITY-STREAM verification suite.

Covers all 4 breakthroughs under CHIMERA-ONE Invariant Laws (Zero-IQ-Loss, <80 MiB RSS, Zero-Subprocess-Popup):
  1. Precognition Stream Tap + 64 KiB OS Page-Cache Warmup + Strict Read-Only Command Guard
  2. O(log N) Merkle KV-Cache Forensic Diff + FlightRecorder Forensics + Prefix-to-PoP Sticky Pinning
  3. Dual-Hemisphere Egress (Peer Auth, Lock-Free peer_guard Fuse, Anti-SSRF, Dual Hedge, Adaptive XOR FEC)
  4. Turn-Atomic Workspace Time-Machine (FileRevisions + Conflict-Checked os.replace) + 5 Akashic MCP Tools
"""

from __future__ import annotations

import http.client
import http.server
import json
import os
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path

from chimera_tp.autopilot import OpsConfig
from chimera_tp.dashboard import ChimeraDaemon
from chimera_tp.phantom_tunnel import _TunnelEndpointMixin
from chimera_tp.platform.egress_membrane import EgressMembraneProxy
from chimera_tp.platform.mcp_server import handle_mcp_request
from chimera_tp.platform.peer_guard import fast_egress_fuse
from chimera_tp.platform.precog_conduit import (
    PrecognitionStreamTap,
    PrecogWarmupPool,
    TurnTimeMachine,
    validate_readonly_command,
    warm_file_paths,
)
from chimera_tp.symbiote_engine import ChimeraSymbioteEngine


def _start_tcp_echo(reply: bytes = b"OK-POP") -> tuple[socket.socket, int, threading.Event]:
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(16)
    port = int(srv.getsockname()[1])
    stop = threading.Event()

    def _serve() -> None:
        srv.settimeout(0.2)
        while not stop.is_set():
            try:
                conn, _ = srv.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                _ = conn.recv(1024)
                conn.sendall(reply)
            except OSError:
                pass
            finally:
                conn.close()

    threading.Thread(target=_serve, daemon=True).start()
    return srv, port, stop


class TestV26SingularityStream(unittest.TestCase):
    def test_01_precognition_stream_tap_and_readonly_guard(self) -> None:
        # 1. Read-only command allowlist must accept safe RO commands and block mutators/metacharacters
        ok1, argv1, _ = validate_readonly_command("git status --short")
        self.assertTrue(ok1)
        self.assertEqual(argv1[:3], ["git", "--no-optional-locks", "status"])

        ok2, _, _ = validate_readonly_command("pytest --collect-only tests/")
        self.assertTrue(ok2)

        for bad in (
            "git status && rm -rf /",
            "rm -rf /tmp/x",
            "pytest tests/",
            "ruff check --fix .",
            "git branch -D main",
            "python -c 'import os'",
        ):
            ok_bad, _, _ = validate_readonly_command(bad)
            self.assertFalse(ok_bad, f"Expected mutating/unsafe command to be blocked: {bad}")

        # 2. Passive SSE Precognition tap extracts split JSON tool_calls before [DONE] and warms file
        with tempfile.TemporaryDirectory() as td:
            target_file = Path(td) / "hot_module.py"
            target_file.write_text("# precog sample\n" * 400, encoding="utf-8")

            hints: list[tuple[str, dict]] = []
            pool = PrecogWarmupPool()
            try:
                tap = PrecognitionStreamTap(
                    pool,
                    turn_id="turn-precog-1",
                    session_id="sess-p1",
                    workspace_root=td,
                    pulse_fn=lambda topic, payload: hints.append((topic, payload)),
                )
                # Split tool_calls JSON across multiple small SSE chunks (OpenAI Chat Completions format)
                arg_json = json.dumps({"path": str(target_file), "command": "git diff --stat"})
                c1 = f'data: {json.dumps({"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call_1", "function": {"name": "read_file", "arguments": arg_json[:25]}}]}}]})}\n\n'.encode()
                c2 = f'data: {json.dumps({"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": arg_json[25:]}}]}}]})}\n\n'.encode()
                c3 = b"data: [DONE]\n\n"
                tap.feed(c1[:30])
                tap.feed(c1[30:])
                tap.feed(c2)
                tap.feed(c3)
                tap.close()

                # Wait briefly for single bounded worker to finish warming
                deadline = time.monotonic() + 3.0
                while time.monotonic() < deadline and pool.stats()["files_warmed"] < 1:
                    time.sleep(0.02)

                st = pool.stats()
                self.assertGreaterEqual(st["files_warmed"], 1)
                self.assertGreater(st["bytes_warmed"], 0)
                self.assertGreaterEqual(st["readonly_checks_run"], 1)
                self.assertGreaterEqual(len(hints), 2)
                self.assertTrue(any(h[1]["hint_kind"] == "path" for h in hints))
                self.assertTrue(any(h[1]["hint_kind"] == "readonly_cmd" for h in hints))
            finally:
                pool.close()

            # Direct bounded warm_file_paths check
            w = warm_file_paths([target_file], budget_bytes=256 * 1024)
            self.assertTrue(w["ok"])
            self.assertEqual(w["warmed_files"], 1)

    def test_02_kv_forensic_diff_and_prefix_sticky_pop_pinning(self) -> None:
        # 1. Symbiote O(log N) Merkle forensic diff pinpoints exact mutated message & field
        with tempfile.TemporaryDirectory() as sym_td:
            sym = ChimeraSymbioteEngine(ops_dir=Path(sym_td))
            m1 = [
                {"role": "system", "content": "You are Chimera."},
                {"role": "user", "content": "Explain kernel scheduling." * 50},
                {"role": "assistant", "content": "Here is the full analysis." * 50},
                {"role": "user", "content": "Now optimize it."},
            ]

            def _prep(msgs: list[dict]) -> tuple[list[str], list[dict]]:
                from chimera_tp.platform.substrate import PlatformSubstrate

                return PlatformSubstrate._hash_prompt_items(msgs)

            d1, meta1 = _prep(m1)
            a1 = sym.audit_prefix("sess-kv", d1, item_metas=meta1)
            self.assertFalse(a1["mid_prefix_break"])
            self.assertEqual(a1["forensic_diff"]["break_kind"], "clean")

            # Clean append preserves 100% cache survival and keeps sticky_key valid
            m2 = m1 + [{"role": "assistant", "content": "Done."}]
            d2, meta2 = _prep(m2)
            a2 = sym.audit_prefix("sess-kv", d2, item_metas=meta2)
            self.assertFalse(a2["mid_prefix_break"])
            self.assertEqual(a2["forensic_diff"]["cache_survival_pct"], 100.0)
            self.assertTrue(bool(a2["sticky_key"]))

            # Mutate message #1 content -> exact break_index=1, mutated_fields=['content'], lost_tokens_est > 0
            m3 = list(m2)
            m3[1] = {"role": "user", "content": "MUTATED TIMESTAMP INJECTED" + ("x" * 100)}
            d3, meta3 = _prep(m3)
            a3 = sym.audit_prefix("sess-kv", d3, item_metas=meta3)
            self.assertTrue(a3["mid_prefix_break"])
            self.assertEqual(a3["break_index"], 1)
            fdiff = a3["forensic_diff"]
            self.assertEqual(fdiff["break_kind"], "mutation")
            self.assertEqual(fdiff["mutated_fields"], ["content"])
            self.assertGreater(fdiff["lost_tokens_est"], 100)
            self.assertLess(fdiff["cache_survival_pct"], 50.0)

        # 2. Live Conduit Zero-IQ-Loss wire parity + forensic recording + Turn/Sticky headers
        seen_upstream: list[tuple[bytes, dict]] = []

        class _MockLLM(http.server.BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                n = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(n)
                seen_upstream.append((raw, {k.lower(): v for k, v in self.headers.items()}))
                sse = (
                    b'data: {"choices":[{"delta":{"content":"ok"}}]}\n\n'
                    b"data: [DONE]\n\n"
                )
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Content-Length", str(len(sse)))
                self.end_headers()
                self.wfile.write(sse)

            def log_message(self, *_args: object) -> None:
                pass

        llm_srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _MockLLM)
        llm_port = int(llm_srv.server_address[1])
        threading.Thread(target=llm_srv.serve_forever, daemon=True).start()

        with tempfile.TemporaryDirectory() as td:
            cfg = OpsConfig(
                node_name="test-v26",
                dashboard_bind="127.0.0.1:0",
                beam_port=0,
                rpc_v4_port=0,
                rpc_v6_port=0,
                query_port=0,
                warp_port=0,
                immortal_v4_port=0,
                immortal_v6_port=0,
                nat_punch_port=0,
                edge_proxy_port=-1,
            )
            daemon = ChimeraDaemon(config=cfg, ops_dir=Path(td), auto_seed_on_empty=False).start()
            try:
                base_port = int(daemon.http_addr[1])

                def _post_chat(messages: list[dict], turn_id: str) -> tuple[int, dict, bytes]:
                    raw = json.dumps({"model": "deepseek-v4.1-flash-sg", "stream": True, "reasoning_effort": "high", "messages": messages}).encode()
                    conn = http.client.HTTPConnection("127.0.0.1", base_port, timeout=10.0)
                    conn.request(
                        "POST",
                        "/v1/openai/v1/chat/completions",
                        body=raw,
                        headers={
                            "Content-Type": "application/json",
                            "X-Chimera-Upstream": f"http://127.0.0.1:{llm_port}",
                            "X-Chimera-Session": "live-kv-sess",
                            "X-Chimera-Turn-Id": turn_id,
                        },
                    )
                    resp = conn.getresponse()
                    hdrs = {k.lower(): v for k, v in resp.getheaders()}
                    data = resp.read()
                    conn.close()
                    return resp.status, hdrs, data

                st1, h1, _ = _post_chat(m1, "turn-kv-1")
                self.assertEqual(st1, 200)
                self.assertEqual(h1.get("x-chimera-turn-id"), "turn-kv-1")
                self.assertEqual(h1.get("x-chimera-prefix-clean"), "1")
                self.assertTrue(bool(h1.get("x-chimera-prefix-sticky")))

                # Trigger mid-prefix break on turn 2
                st2, h2, _ = _post_chat(m3, "turn-kv-2")
                self.assertEqual(st2, 200)
                self.assertEqual(h2.get("x-chimera-prefix-clean"), "0")

                # Verify Zero-IQ-Loss: raw_body arrived verbatim including reasoning_effort=high
                self.assertEqual(len(seen_upstream), 2)
                self.assertIn(b'"reasoning_effort": "high"', seen_upstream[0][0])
                self.assertEqual(seen_upstream[0][1].get("x-chimera-turn-id"), "turn-kv-1")
                self.assertTrue(bool(seen_upstream[0][1].get("x-chimera-prefix-sticky")))

                # Verify /v1/openai/forensics & /v1/openai/turns endpoints
                c = http.client.HTTPConnection("127.0.0.1", base_port, timeout=5.0)
                c.request("GET", "/v1/openai/forensics")
                f_data = json.loads(c.getresponse().read().decode())
                self.assertGreaterEqual(len(f_data["forensics"]), 1)
                self.assertEqual(f_data["forensics"][0]["break_index"], 1)
                self.assertEqual(f_data["forensics"][0]["mutated_fields"], ["content"])

                c.request("GET", "/v1/openai/turns")
                t_data = json.loads(c.getresponse().read().decode())
                turn_ids = [t["turn_id"] for t in t_data["turns"]]
                self.assertIn("turn-kv-1", turn_ids)
                self.assertIn("turn-kv-2", turn_ids)
                c.close()
            finally:
                daemon.close()
                llm_srv.shutdown()
                llm_srv.server_close()

        # 3. EgressMembraneProxy Prefix-to-PoP Sticky Pinning (SET -> HIT -> FAILOVER)
        echo_srv, echo_port, echo_stop = _start_tcp_echo(b"STICKY-OK")
        proxy = EgressMembraneProxy(
            listen_port=0,
            custom_resolver=lambda h: ["127.0.0.1", "127.0.0.2"] if h == "sticky.example" else ["127.0.0.1"],
            hedge_delay_ms=40.0,
            enable_standby_pool=True,
        ).start()
        try:
            def _connect_sticky(skey: str) -> dict[str, str]:
                s = socket.create_connection(proxy.addr, timeout=5.0)
                try:
                    req = (
                        f"CONNECT sticky.example:{echo_port} HTTP/1.1\r\n"
                        f"Host: sticky.example:{echo_port}\r\n"
                        f"X-Chimera-Sticky-Key: {skey}\r\n\r\n"
                    ).encode("ascii")
                    s.sendall(req)
                    raw = b""
                    while b"\r\n\r\n" not in raw:
                        raw += s.recv(4096)
                    hdrs = {}
                    for line in raw.split(b"\r\n")[1:]:
                        if b":" in line:
                            k, _, v = line.decode("ascii", errors="ignore").partition(":")
                            hdrs[k.strip().lower()] = v.strip()
                    s.sendall(b"ping")
                    self.assertEqual(s.recv(64), b"STICKY-OK")
                    return hdrs
                finally:
                    s.close()

            h_set = _connect_sticky("prefix-root-alpha")
            self.assertEqual(h_set.get("x-chimera-pop-pin"), "SET")
            pinned_ip = h_set.get("x-chimera-pop")
            self.assertEqual(pinned_ip, "127.0.0.1")

            h_hit = _connect_sticky("prefix-root-alpha")
            self.assertEqual(h_hit.get("x-chimera-pop-pin"), "HIT")
            self.assertEqual(h_hit.get("x-chimera-pop"), pinned_ip)
            self.assertGreaterEqual(len(proxy.sticky_pin_stats()), 1)
        finally:
            proxy.close()
            echo_stop.set()
            echo_srv.close()

    def test_03_dual_hemisphere_egress_security_fuse_and_fec(self) -> None:
        # 1. Lock-free fast_egress_fuse runs fast and returns (bool, str)
        ok_fuse, reason_fuse = fast_egress_fuse(force_refresh=True)
        self.assertIsInstance(ok_fuse, bool)
        self.assertIsInstance(reason_fuse, str)

        # 2. Peer-hop Auth + Fuse + Anti-SSRF + Dual-Hemisphere Rescue
        echo_srv, echo_port, echo_stop = _start_tcp_echo(b"SVHOME-RESCUE")
        fuse_state = {"ok": True, "reason": "ok"}

        peer_proxy = EgressMembraneProxy(
            listen_port=0,
            custom_resolver=lambda _h: ["127.0.0.1"],
            peer_hop_fuse=lambda: (fuse_state["ok"], fuse_state["reason"]),
            peer_auth_secret="top-secret-cluster-key",
            allow_private_peer_hop=True,
            enable_standby_pool=False,
        ).start()
        ssrf_proxy = EgressMembraneProxy(
            listen_port=0,
            custom_resolver=lambda _h: ["127.0.0.1"],
            peer_auth_secret="top-secret-cluster-key",
            allow_private_peer_hop=False,  # Production default: blocks RFC1918/loopback!
        ).start()

        # Primary proxy resolves target to unreachable RFC 5737 blackhole port so local fails -> peer rescues!
        dead_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        dead_sock.bind(("127.0.0.1", 0))
        dead_port = int(dead_sock.getsockname()[1])
        dead_sock.close()

        local_proxy = EgressMembraneProxy(
            listen_port=0,
            custom_resolver=lambda _h: ["198.51.100.1"],
            connect_attempt_timeout_s=0.15,
            hedge_delay_ms=40.0,
            peer_hedge_delay_ms=60.0,
            peer_proxy_resolver=lambda: peer_proxy.url,
            peer_auth_secret="top-secret-cluster-key",
            enable_standby_pool=False,
        ).start()
        try:
            def _raw_connect(addr: tuple[str, int], target: str, extra_hdrs: dict[str, str]) -> tuple[bytes, socket.socket]:
                s = socket.create_connection(addr, timeout=5.0)
                lines = [f"CONNECT {target} HTTP/1.1", f"Host: {target}"]
                for k, v in extra_hdrs.items():
                    lines.append(f"{k}: {v}")
                s.sendall(("\r\n".join(lines) + "\r\n\r\n").encode("ascii"))
                raw = b""
                while b"\r\n\r\n" not in raw:
                    part = s.recv(4096)
                    if not part:
                        break
                    raw += part
                return raw, s

            # (a) Wrong peer auth -> 403 AUTH_DENIED
            raw_403, s403 = _raw_connect(
                peer_proxy.addr,
                f"remote.example:{echo_port}",
                {"X-Chimera-Peer-Hop": "1", "X-Chimera-Peer-Auth": "wrong"},
            )
            s403.close()
            self.assertIn(b"403", raw_403.split(b"\r\n", 1)[0])
            self.assertIn(b"AUTH_DENIED", raw_403)

            # (b) Tripped peer_guard fuse -> 503 OPEN
            fuse_state["ok"], fuse_state["reason"] = False, "host_load:2.5"
            raw_503, s503 = _raw_connect(
                peer_proxy.addr,
                f"remote.example:{echo_port}",
                {"X-Chimera-Peer-Hop": "1", "X-Chimera-Peer-Auth": "top-secret-cluster-key"},
            )
            s503.close()
            self.assertIn(b"503", raw_503.split(b"\r\n", 1)[0])
            self.assertIn(b"X-Chimera-Peer-Fuse: OPEN", raw_503)
            self.assertIn(b"host_load:2.5", raw_503)

            # (c) Anti-SSRF blocks private/loopback IP when allow_private_peer_hop=False
            raw_ssrf, sssrf = _raw_connect(
                ssrf_proxy.addr,
                f"internal.example:{echo_port}",
                {"X-Chimera-Peer-Hop": "1", "X-Chimera-Peer-Auth": "top-secret-cluster-key"},
            )
            sssrf.close()
            self.assertIn(b"403", raw_ssrf.split(b"\r\n", 1)[0])
            self.assertIn(b"SSRF_BLOCKED", raw_ssrf)

            # (d) Restore fuse -> Dual-Hemisphere failover & dual-hedge rescue through authenticated peer proxy!
            fuse_state["ok"], fuse_state["reason"] = True, "ok"
            from unittest import mock

            real_create = socket.create_connection

            def _fail_blackhole(addr, timeout=None, *a, **kw):
                if addr[0] == "198.51.100.1":
                    raise OSError("local ISP route down")
                return real_create(addr, timeout=timeout, *a, **kw)

            with mock.patch("chimera_tp.platform.egress_membrane.socket.create_connection", side_effect=_fail_blackhole):
                raw_ok, sok = _raw_connect(
                    local_proxy.addr,
                    f"rescued.example:{echo_port}",
                    {"X-Chimera-Hemisphere": "failover"},
                )
                try:
                    self.assertIn(b"200", raw_ok.split(b"\r\n", 1)[0])
                    self.assertIn(b"X-Chimera-Route: peer", raw_ok)
                    sok.sendall(b"hi")
                    self.assertEqual(sok.recv(64), b"SVHOME-RESCUE")
                finally:
                    sok.close()

                # Also verify opt-in Dual-Hemisphere concurrent hedge (X-Chimera-Hemisphere: dual)
                raw_dual, sdual = _raw_connect(
                    local_proxy.addr,
                    f"dual.example:{echo_port}",
                    {"X-Chimera-Hemisphere": "dual"},
                )
                try:
                    self.assertIn(b"200", raw_dual.split(b"\r\n", 1)[0])
                    self.assertIn(b"X-Chimera-Route: peer-hedge", raw_dual)
                    sdual.sendall(b"hi2")
                    self.assertEqual(sdual.recv(64), b"SVHOME-RESCUE")
                finally:
                    sdual.close()
        finally:
            local_proxy.close()
            peer_proxy.close()
            ssrf_proxy.close()
            echo_stop.set()
            echo_srv.close()

        # 3. Phantom adaptive XOR FEC 0-RTT single-packet loss recovery
        group = [b"chunk-zero-alpha", b"chunk-one-beta-longer-payload", b"c2", b"chunk-three-omega"]
        parity = _TunnelEndpointMixin._fec_xor_pack(group)
        for drop_idx in range(len(group)):
            known = [g for i, g in enumerate(group) if i != drop_idx]
            recovered = _TunnelEndpointMixin._fec_xor_recover(parity, known)
            self.assertEqual(recovered, group[drop_idx])

    def test_04_turn_atomic_timemachine_and_conflict_abort(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "repo"
            state = Path(td) / "tm_state"
            root.mkdir()
            f_exist = root / "app.py"
            f_exist.write_text("v1 = True\n", encoding="utf-8")

            tm = TurnTimeMachine(state_dir=state)
            cp = tm.checkpoint_turn("turn-42", root, ["app.py", "sub/new_file.py"], meta={"model": "deepseek"})
            self.assertTrue(cp["ok"])
            self.assertEqual(cp["files_tracked"], 2)

            # Simulate agent turn mutating app.py & creating sub/new_file.py
            f_exist.write_text("v2_hallucinated = True\n", encoding="utf-8")
            (root / "sub").mkdir()
            (root / "sub" / "new_file.py").write_text("bad = 1\n", encoding="utf-8")
            fin = tm.finalize_turn("turn-42")
            self.assertTrue(fin["ok"])

            # Atomic rollback restores app.py and removes sub/new_file.py + empty sub/
            rb = tm.rollback_turn("turn-42")
            self.assertTrue(rb["ok"])
            self.assertEqual(rb["restored_files"], 1)
            self.assertEqual(rb["removed_files"], 1)
            self.assertEqual(f_exist.read_text(encoding="utf-8"), "v1 = True\n")
            self.assertFalse((root / "sub" / "new_file.py").exists())

            # Conflict check: external modification after finalize aborts with zero overwrites
            cp2 = tm.checkpoint_turn("turn-43", root, ["app.py"])
            self.assertTrue(cp2["ok"])
            f_exist.write_text("turn43_edit\n", encoding="utf-8")
            tm.finalize_turn("turn-43")
            f_exist.write_text("USER_MANUAL_EDIT\n", encoding="utf-8")
            rb_conflict = tm.rollback_turn("turn-43")
            self.assertFalse(rb_conflict["ok"])
            self.assertEqual(rb_conflict["error"], "workspace_changed")
            self.assertEqual(rb_conflict["conflicts"], ["app.py"])
            self.assertEqual(f_exist.read_text(encoding="utf-8"), "USER_MANUAL_EDIT\n")

    def test_05_akashic_mcp_tools_zero_daemon_rss(self) -> None:
        listed = handle_mcp_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        names = {t["name"] for t in listed["result"]["tools"]}
        for expected in (
            "chimera_akashic_symbols",
            "chimera_akashic_recall",
            "chimera_timemachine",
            "chimera_forensics",
            "chimera_speculative_warm",
        ):
            self.assertIn(expected, names)

        # 1. chimera_akashic_symbols on a self-contained git worktree (works on non-git deploy nodes too!)
        import subprocess as _sp

        with tempfile.TemporaryDirectory() as git_td:
            gt = Path(git_td)
            (gt / "sample_mod.py").write_text("class TurnTimeMachine:\n    def rollback(self):\n        return True\n", encoding="utf-8")
            cflags = getattr(_sp, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
            _sp.run(["git", "init", "-q"], cwd=str(gt), check=True, creationflags=cflags)
            _sp.run(["git", "config", "user.email", "chimera@local"], cwd=str(gt), check=True, creationflags=cflags)
            _sp.run(["git", "config", "user.name", "Chimera"], cwd=str(gt), check=True, creationflags=cflags)
            _sp.run(["git", "add", "sample_mod.py"], cwd=str(gt), check=True, creationflags=cflags)
            _sp.run(["git", "commit", "-q", "-m", "init"], cwd=str(gt), check=True, creationflags=cflags)

            sym_resp = handle_mcp_request(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {
                        "name": "chimera_akashic_symbols",
                        "arguments": {"action": "find", "repo": str(gt), "symbol": "TurnTimeMachine"},
                    },
                }
            )
            sym_out = json.loads(sym_resp["result"]["content"][0]["text"])
            self.assertTrue(sym_out.get("ok"), sym_out)
            self.assertEqual(sym_out.get("parsed_files"), 0)
            self.assertTrue(
                any(m.get("qualified_name") == "TurnTimeMachine" for m in sym_out.get("matches", [])),
                sym_out,
            )

        # 2. chimera_akashic_recall (Vietnamese diacritic-aware recall + ResultReuse)
        save_resp = handle_mcp_request(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "chimera_akashic_recall",
                    "arguments": {
                        "action": "save",
                        "url": "https://chimera.local/docs/v26",
                        "text": "Đột phá điên rồ Precognition Stream Tap tăng tốc đọc đĩa",
                        "scope": "v26-test",
                    },
                },
            }
        )
        self.assertTrue(json.loads(save_resp["result"]["content"][0]["text"]).get("id"))
        find_resp = handle_mcp_request(
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {
                    "name": "chimera_akashic_recall",
                    "arguments": {"action": "find", "query": "dot pha Precognition", "scope": "v26-test"},
                },
            }
        )
        find_out = json.loads(find_resp["result"]["content"][0]["text"])
        self.assertGreaterEqual(find_out.get("count", 0), 1)

        # 3. chimera_speculative_warm (path warm + RO command validator)
        warm_resp = handle_mcp_request(
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {
                    "name": "chimera_speculative_warm",
                    "arguments": {"paths": [__file__], "command": "git status --short"},
                },
            }
        )
        warm_out = json.loads(warm_resp["result"]["content"][0]["text"])
        self.assertEqual(warm_out["page_cache"]["warmed_files"], 1)
        self.assertTrue(warm_out["command_validation"]["ok"])


if __name__ == "__main__":
    unittest.main()
