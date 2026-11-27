"""Comprehensive tests for CHIMERA-IMMORTAL-RELAY + CHIMERA-EIDOLON + Moonshot #2-#5."""
from __future__ import annotations

import json
import sqlite3
import tempfile
import threading
import time
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from chimera_tp.platform.agent_probe import AgentHyperBus
from chimera_tp.platform.immortal_relay import (
    CrossThreadPanopticon,
    ImmortalSocketShield,
    SwarmMaintenanceLock,
)
from chimera_tp.platform.mcp_server import _TOOLS, handle_mcp_request


def _start_mock_backend(label: str, *, sse_delay_s: float = 0.0) -> tuple[ThreadingHTTPServer, str]:
    class _H(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            return

        def do_GET(self):
            if self.path == "/healthz":
                body = json.dumps({"ok": True, "slot": label}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if self.path == "/stream":
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.end_headers()
                self.wfile.write(f"data: {label}-chunk-1\n\n".encode("utf-8"))
                self.wfile.flush()
                if sse_delay_s > 0:
                    time.sleep(sse_delay_s)
                self.wfile.write(f"data: {label}-chunk-2\n\n".encode("utf-8"))
                self.wfile.flush()
                return
            body = json.dumps({"slot": label, "path": self.path}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), _H)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


class TestEidolonImmortalAndMoonshot(unittest.TestCase):
    def test_01_immortal_socket_blue_green_graceful_drain_and_phoenix_failover(self) -> None:
        blue_srv, blue_url = _start_mock_backend("blue", sse_delay_s=0.25)
        green_srv, green_url = _start_mock_backend("green")
        sv_srv, sv_url = _start_mock_backend("svhome-phoenix")
        shield = ImmortalSocketShield(bind_port=0, blue_url=blue_url, green_url=green_url, failover_url=sv_url)
        try:
            front = shield.start()
            # Start an active SSE stream on BLUE, flip to GREEN mid-stream!
            stream_out: list[str] = []

            def _read_sse():
                with urllib.request.urlopen(f"{front}/stream", timeout=5.0) as r:
                    stream_out.append(r.read().decode("utf-8"))

            t = threading.Thread(target=_read_sse)
            t.start()
            time.sleep(0.08)  # Wait until BLUE stream is actively in flight

            flip = shield.flip_active("green", verify_health=True)
            self.assertTrue(flip["ok"])
            self.assertEqual(flip["active_slot"], "green")
            self.assertGreaterEqual(flip["draining_on_previous"], 1)

            # New request immediately goes to GREEN while BLUE stream still drains intact!
            with urllib.request.urlopen(f"{front}/ping", timeout=3.0) as r2:
                d2 = json.loads(r2.read().decode("utf-8"))
                self.assertEqual(d2["slot"], "green")
                self.assertEqual(r2.headers.get("X-Chimera-Shield-Slot"), "green")

            t.join(timeout=3.0)
            self.assertEqual(len(stream_out), 1)
            self.assertIn("blue-chunk-1", stream_out[0])
            self.assertIn("blue-chunk-2", stream_out[0])

            # Kill GREEN -> Phoenix Failover seamlessly routes to svhome!
            green_srv.shutdown()
            green_srv.server_close()
            with urllib.request.urlopen(f"{front}/after-crash", timeout=3.0) as r3:
                d3 = json.loads(r3.read().decode("utf-8"))
                self.assertEqual(d3["slot"], "svhome-phoenix")
                self.assertEqual(r3.headers.get("X-Chimera-Shield-Slot"), "failover")
            self.assertGreaterEqual(shield.status()["failover_hits"], 1)
        finally:
            shield.close()
            for s in (blue_srv, green_srv, sv_srv):
                try:
                    s.shutdown()
                    s.server_close()
                except Exception:
                    pass

    def test_02_swarm_maintenance_lock_and_cross_thread_panopticon(self) -> None:
        bus = AgentHyperBus(ephemeral=True)
        try:
            lock = SwarmMaintenanceLock(workspace=bus.symbiont.noosphere.workspace)
            # Active stream present -> MUST block force-kill and recommend blue-green!
            busy = lock.check(service="tquota", override_active_streams=2)
            self.assertFalse(busy["force_kill_allowed"])
            self.assertEqual(busy["recommended_strategy"], "use_blue_green_hotswap")
            # Idle -> safe
            idle = lock.check(service="tquota", override_active_streams=0)
            self.assertTrue(idle["force_kill_allowed"])

            # CrossThreadPanopticon against realistic temp SQLite WAL DBs
            with tempfile.TemporaryDirectory(prefix="panopticon_") as td:
                udb = Path(td) / "local-usage.sqlite"
                cdb = Path(td) / "logs_2.sqlite"
                now_ms = int(time.time() * 1000)
                now_s = int(time.time())
                c1 = sqlite3.connect(udb)
                c1.execute("CREATE TABLE usage (id INTEGER PRIMARY KEY, event_id TEXT, ts INTEGER, payload TEXT)")
                for i, pid in enumerate((1001, 1002, 1003, 1003, 1003)):
                    payload = json.dumps({"pid": pid, "status": 503, "errorCode": "tool_generation_timeout_retry_blocked"})
                    c1.execute("INSERT INTO usage (event_id, ts, payload) VALUES (?, ?, ?)", (f"e{i}", now_ms, payload))
                c1.commit()
                c1.close()

                c2 = sqlite3.connect(cdb)
                c2.execute("CREATE TABLE logs (id INTEGER PRIMARY KEY, ts INTEGER, target TEXT, feedback_log_body TEXT)")
                c2.execute(
                    "INSERT INTO logs (ts, target, feedback_log_body) VALUES (?, ?, ?)",
                    (now_s, "codex_core::responses_retry", "Request failed http://127.0.0.1:12500/v1/responses is_connect=true"),
                )
                c2.commit()
                c2.close()

                pano = CrossThreadPanopticon(usage_db_path=udb, codex_db_path=cdb).scan(window_s=600.0)
                self.assertTrue(pano["ok"])
                self.assertEqual(pano["steer_503_blocks"], 5)
                self.assertEqual(pano["pid_churn"], 2)
                self.assertEqual(pano["codex_connect_drops"], 1)
                self.assertTrue(pano["blue_green_recommended"])
                self.assertTrue(any("STEER_LOCK_STORM" in a for a in pano["alerts"]))
                self.assertTrue(any("FRIENDLY_FIRE_PID_CHURN" in a for a in pano["alerts"]))
        finally:
            bus.close()

    def test_03_eidolon_scout_silent_fuzzer_and_counterfactual_simulator(self) -> None:
        bus = AgentHyperBus(ephemeral=True)
        try:
            eid = bus.symbiont.eidolon
            with tempfile.TemporaryDirectory(prefix="eidolon_repo_") as td:
                root = Path(td)
                for i in range(12):
                    (root / f"mod_{i}.py").write_text(
                        "\n".join(f"def helper_{i}_{j}(x): return x + {j}  # boilerplate line" for j in range(60)),
                        encoding="utf-8",
                    )
                (root / "target_core.py").write_text(
                    "def steer_preempt_hook(sig_a, sig_b):\n    return sig_a != sig_b\n",
                    encoding="utf-8",
                )
                broken = root / "broken.py"
                broken.write_text("def oops(:\n    pass\n", encoding="utf-8")

                # 1. SHA-256 Verified Scout: >95% bloat reduction, 0 Google tokens
                sc = eid.dispatch("scout", repo=str(root), pattern="steer_preempt_hook", max_tokens=400)
                self.assertTrue(sc["ok"])
                self.assertEqual(sc["google_tokens_used"], 0)
                self.assertGreater(sc["bloat_reduction_pct"], 95.0)
                self.assertEqual(len(sc["verified_hits"]), 1)
                self.assertEqual(sc["verified_hits"][0]["file"], "target_core.py")

                # 2. Silent Adversarial Fuzzer: 0 tokens on PASS, compact alert on FAIL
                fz_ok = eid.dispatch("fuzz", file_paths=[str(root / "target_core.py")])
                self.assertTrue(fz_ok["passed"])
                self.assertTrue(fz_ok["silent"])
                self.assertEqual(fz_ok["emitted_to_google_tokens"], 0)

                fz_bad = eid.dispatch("fuzz", file_paths=[str(broken)])
                self.assertFalse(fz_bad["passed"])
                self.assertFalse(fz_bad["silent"])
                self.assertLess(fz_bad["emitted_to_google_tokens"], 120)

                # 3. Counterfactual Reality Simulator: parallel A vs B race picks passing winner
                cf = eid.dispatch(
                    "counterfactual",
                    variants=[
                        {"name": "A_broken", "filename": "algo.py", "code": "def solve(n): return n - 1\n"},
                        {"name": "B_fast_correct", "filename": "algo.py", "code": "def solve(n): return n * 2\n"},
                    ],
                    oracle_code="import algo\nassert algo.solve(21) == 42\n",
                )
                self.assertTrue(cf["ok"])
                self.assertEqual(cf["winner"], "B_fast_correct")
                self.assertEqual(cf["google_tokens_used"], 0)
        finally:
            bus.close()

    def test_04_moonshot_precog_twin_zero_cliff_autopoiesis_synesthesia_and_mcp43(self) -> None:
        bus = AgentHyperBus(ephemeral=True)
        try:
            eid = bus.symbiont.eidolon
            # Moonshot #3: PrecogShadowTwin verifies delta & serves < 5ms cache hit
            v1 = eid.dispatch("precog_verify", rel_path="demo.py", content="def ok(x):\n    return x + 1\n")
            self.assertTrue(v1["passed"])
            self.assertFalse(v1["cache_hit"])
            v2 = eid.dispatch("precog_verify", rel_path="demo.py", content="def ok(x):\n    return x + 1\n")
            self.assertTrue(v2["cache_hit"])
            self.assertLess(v2["elapsed_ms"], 10.0)

            # Moonshot #4: PreCompactionCrystalBridge triggers at >= 220K tokens
            zc_skip = eid.dispatch("zero_cliff", session_id="s-warm", prompt_tokens=150_000, repo=".")
            self.assertFalse(zc_skip["staged"])
            zc_hit = eid.dispatch("zero_cliff", session_id="s-warm", prompt_tokens=260_000, repo=".")
            self.assertTrue(zc_hit["staged"])
            self.assertLessEqual(zc_hit["crystal_tokens"], 520)

            # Moonshot #2: AutopoiesisNightlyHealer (strict Law 6 shadow_only, auto_activated=False)
            ap = eid.dispatch("autopoiesis")
            self.assertTrue(ap["ok"])
            self.assertEqual(ap["mode"], "shadow_only")
            self.assertFalse(ap["auto_activated"])
            self.assertFalse(ap["effort_mutation_allowed"])

            # Moonshot #5: EcosystemSynesthesiaGraph cross-project episodic memory
            with tempfile.TemporaryDirectory(prefix="syn_") as td:
                p1 = Path(td) / "proj_alpha"
                p2 = Path(td) / "proj_beta"
                (p1 / "tasks").mkdir(parents=True)
                (p2 / "tasks").mkdir(parents=True)
                (p1 / "tasks" / "lessons.md").write_text("- Never mutate frozen Gemini prefix entries in contents array\n", encoding="utf-8")
                (p2 / "tasks" / "lessons.md").write_text("- Always use Blue-Green graceful drain on port 12500 reload\n", encoding="utf-8")
                ix = eid.dispatch("synesthesia_index", repo_paths=[str(p1), str(p2)])
                self.assertEqual(len(ix["projects_indexed"]), 2)
                rc = eid.dispatch("synesthesia_recall", query="Blue-Green graceful drain port 12500", top_k=3)
                self.assertGreaterEqual(len(rc["hits"]), 1)
                self.assertEqual(rc["hits"][0]["project"], "proj_beta")

            # MCP 43rd tool `chimera_eidolon`
            names = [t["name"] for t in _TOOLS]
            self.assertGreaterEqual(len(names), 43)
            self.assertIn("chimera_eidolon", names)
            resp = handle_mcp_request(
                {
                    "jsonrpc": "2.0",
                    "id": 143,
                    "method": "tools/call",
                    "params": {"name": "chimera_eidolon", "arguments": {"action": "status"}},
                }
            )
            self.assertIsNotNone(resp)
            assert resp is not None
            body = json.loads(resp["result"]["content"][0]["text"])
            self.assertTrue(body["ok"])
            self.assertFalse(body["effort_mutation_allowed"])
        finally:
            bus.close()


if __name__ == "__main__":
    unittest.main()
