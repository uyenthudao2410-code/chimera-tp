"""Comprehensive tests for CHIMERA-PROMETHEUS (Waves 1–3: Axiom, Sovereign Epoch, Galileo, Oracle, Ghost Pool, Native Micronucleus)."""
from __future__ import annotations

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
import urllib.parse
import urllib.request
from pathlib import Path

from chimera_tp.omega_spine.hook_router import OmegaSpineRuntime
from chimera_tp.platform.agent_probe import AgentHyperBus
from chimera_tp.platform.prometheus import (
    ChimeraPrometheusCore,
    EmpiricalAxiomLedger,
    GalileoExperimentEngine,
    GhostReadRing,
    SocketActivationProxy,
    SovereignEpochArbiter,
)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _http_json(url: str, *, method: str = "GET", body: dict | None = None, timeout: float = 5.0) -> tuple[int, dict]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"} if data is not None else {}
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        raw = err.read().decode("utf-8", errors="replace")
        try:
            return err.code, json.loads(raw)
        except Exception:
            return err.code, {"raw": raw}


class TestChimeraPrometheus(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="chimera_prom_test_")
        self.root = Path(self._tmp.name)
        self.core = ChimeraPrometheusCore(data_dir=self.root / "prom_data", ephemeral=False)

    def tearDown(self) -> None:
        self.core.close()
        try:
            self._tmp.cleanup()
        except Exception:
            pass

    # --- Wave 1A: CHIMERA-AXIOM ---

    def test_01_axiom_ledger_seeds_chain_veto_and_hw_unlock(self) -> None:
        st = self.core.axioms.status()
        self.assertTrue(st["ok"])
        self.assertGreaterEqual(st["total_axioms"], 8)
        self.assertTrue(st["chain"]["ok"])
        self.assertEqual(st["chain"]["broken"], 0)

        # Veto REFUTED AutoCAD offload build (< 10 ms)
        v1 = self.core.axioms.check_action("autocad_offload_build")
        self.assertTrue(v1["veto"])
        self.assertEqual(v1["claim_id"], "autocad_build_offload_svhome")
        self.assertIn("cad_display2_10_pairs", v1["receipt_path"])

        # Semantic veto for svhome allocator swap
        v2 = self.core.axioms.check_action("try jemalloc allocator on svhome")
        self.assertTrue(v2["veto"])
        self.assertEqual(v2["claim_id"], "svhome_allocator_swap_idle_rss")

        # Anti-regression veto on in-process CUDA daemon
        v3 = self.core.axioms.check_action("enable_in_process_cuda_daemon")
        self.assertTrue(v3["veto"])
        self.assertEqual(v3["claim_id"], "windows_cuda_out_of_process_worker")

        # Unlocks cleanly ONLY when hardware fingerprint changes
        v4 = self.core.axioms.check_action("autocad_offload_build", hw_fingerprint="new_silicon_fp_99")
        self.assertFalse(v4["veto"])
        self.assertTrue(v4["unlocked_by_hw_change"])

        # Birth primer summary stays bounded
        primer = self.core.axioms.birth_primer_summary(max_chars=500)
        self.assertIn("[CHIMERA-AXIOM", primer)
        self.assertLessEqual(len(primer), 500)

    # --- Wave 1B: CHIMERA-SOVEREIGN-EPOCH ---

    def test_02_epoch_release_seal_tamper_detection_and_soak_freeze(self) -> None:
        rel_dir = self.root / "release_epoch_1"
        rel_dir.mkdir()
        (rel_dir / "mod_a.py").write_text("X = 1\n", encoding="utf-8")
        (rel_dir / "meta.json").write_text('{"v":1}\n', encoding="utf-8")

        sealed = self.core.epoch.seal_release(rel_dir, lock_readonly=True)
        self.assertTrue(sealed["ok"])
        self.assertEqual(sealed["file_count"], 2)
        self.assertTrue(sealed["readonly_locked"])

        ver_ok = self.core.epoch.verify_release_integrity(rel_dir)
        self.assertTrue(ver_ok["ok"])
        self.assertTrue(ver_ok["intact"])

        # Unseal and mutate -> verify catches tamper immediately
        self.core.epoch.unseal_release(rel_dir)
        (rel_dir / "mod_a.py").write_text("X = 999\n", encoding="utf-8")
        ver_bad = self.core.epoch.verify_release_integrity(rel_dir)
        self.assertFalse(ver_bad["ok"])
        self.assertIn("mod_a.py", ver_bad["modified"])

        # Soak-Freeze Arbiter redirects sibling agent to Shadow Port :9796
        lease = self.core.epoch.acquire_soak_lease(
            owner_id="codex-soak-24h",
            window_s=660.0,
            target_pid=4242,
            tree_sha256=sealed["tree_sha256"],
        )
        self.assertTrue(lease["ok"])
        promo_sib = self.core.epoch.request_promote(
            requester_id="antigravity-agent",
            candidate_tree_sha256="cand_sha_abc",
        )
        self.assertFalse(promo_sib["allowed"])
        self.assertEqual(promo_sib["action"], "redirect_shadow_canary")
        self.assertEqual(promo_sib["shadow_port"], 9796)

        # Owner itself can promote, and releasing lease unblocks everyone
        promo_owner = self.core.epoch.request_promote(
            requester_id="codex-soak-24h",
            candidate_tree_sha256="cand_sha_abc",
        )
        self.assertTrue(promo_owner["allowed"])
        self.core.epoch.release_soak_lease(lease["lease_id"])
        promo_after = self.core.epoch.request_promote(
            requester_id="antigravity-agent",
            candidate_tree_sha256="cand_sha_abc",
        )
        self.assertTrue(promo_after["allowed"])

    # --- Wave 2A: CHIMERA-GALILEO ---

    def test_03_galileo_ab_parity_and_resumable_soak(self) -> None:
        # 1) Proven improvement with 100% bit-exact output parity
        ab_ok = self.core.galileo.run_ab(
            hypothesis="Cache read faster than cold read",
            baseline_fn=lambda i: (12.0 + i * 0.1, {"val": i * 2}),
            candidate_fn=lambda i: (1.5 + i * 0.02, {"val": i * 2}),
            pairs=4,
            min_improvement_pct=20.0,
            claim_id="test_cache_faster_claim",
            register_axiom=True,
        )
        self.assertEqual(ab_ok["verdict"], "PROVEN")
        self.assertTrue(ab_ok["parity_ok"])
        self.assertFalse(ab_ok["auto_activated"])
        self.assertGreater(ab_ok["speedup"], 5.0)
        self.assertEqual(ab_ok["axiom_registered"], "test_cache_faster_claim")

        # 2) Parity mismatch -> REFUTED_PARITY_MISMATCH even if faster
        ab_bad = self.core.galileo.run_ab(
            hypothesis="Broken fast candidate",
            baseline_fn=lambda i: (10.0, {"x": i}),
            candidate_fn=lambda i: (1.0, {"x": i + 1}),
            pairs=2,
        )
        self.assertFalse(ab_bad["parity_ok"])
        self.assertEqual(ab_bad["verdict"], "REFUTED_PARITY_MISMATCH")

        # 3) Resumable Soak survives peer_guard pressure without losing prior samples
        self.core.galileo.start_resumable_soak(exp_id="soak_res_1", target_samples=4)
        s1 = self.core.galileo.step_resumable_soak(
            exp_id="soak_res_1",
            guard_fn=lambda: {"ok": True, "busy": False},
            sample_fn=lambda idx: {"sample": idx, "rss_mib": 48.5},
            max_steps=2,
        )
        self.assertEqual(s1["collected_samples"], 2)
        self.assertEqual(s1["status"], "running")

        # Inject peer_guard busy -> pauses cleanly, retains 2 samples
        s2 = self.core.galileo.step_resumable_soak(
            exp_id="soak_res_1",
            guard_fn=lambda: {"ok": False, "busy": True, "reason": "io_pressure_8.1pct"},
            max_steps=2,
        )
        self.assertEqual(s2["status"], "paused_peer_guard")
        self.assertEqual(s2["collected_samples"], 2)
        self.assertEqual(s2["pause_count"], 1)

        # Pressure clears -> resumes seamlessly to 4/4 completed
        s3 = self.core.galileo.step_resumable_soak(
            exp_id="soak_res_1",
            guard_fn=lambda: {"ok": True, "busy": False},
            sample_fn=lambda idx: {"sample": idx, "rss_mib": 49.0},
            max_steps=5,
        )
        self.assertEqual(s3["status"], "completed")
        self.assertEqual(s3["collected_samples"], 4)
        self.assertEqual(s3["pause_count"], 1)

    # --- Wave 2B: CHIMERA-ORACLE ---

    def test_04_oracle_local_phantom_rpc_speculate_and_brief(self) -> None:
        repo = self.root / "mini_repo"
        repo.mkdir()
        (repo / "good.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
        (repo / "bad.py").write_text("def broken(:\n    pass\n", encoding="utf-8")

        loc = self.core.oracle.local_probe(repo_dir=str(repo), check_files=["good.py"])
        self.assertTrue(loc["ok"])
        self.assertIn("good.py", loc["file_hashes"])
        self.assertEqual(len(loc["file_hashes"]["good.py"]), 16)

        # Speculative verify catches syntax error and caches SHA-256 on 2nd run
        sp1 = self.core.oracle.speculative_verify(repo, ["good.py", "bad.py"])
        self.assertFalse(sp1["ok"])
        self.assertEqual(sp1["syntax_errors"], 1)
        self.assertEqual(sp1["cache_hits"], 0)
        sp2 = self.core.oracle.speculative_verify(repo, ["good.py"])
        self.assertTrue(sp2["ok"])
        self.assertEqual(sp2["cache_hits"], 1)

        # Real HTTP keep-alive PHANTOM-RPC loopback probe
        oracle = self.core.oracle

        class _OracleHandler(http.server.BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                ln = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(ln).decode("utf-8")) if ln else {}
                out = json.dumps(oracle.local_probe(
                    repo_dir=body.get("repo_dir") or str(repo),
                    check_files=body.get("check_files"),
                )).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

            def log_message(self, fmt: str, *args) -> None:
                return

        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _OracleHandler)
        port = srv.server_address[1]
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        try:
            r1 = self.core.oracle.phantom_probe(f"http://127.0.0.1:{port}", repo_dir=str(repo), check_files=["good.py"])
            r2 = self.core.oracle.phantom_probe(f"http://127.0.0.1:{port}", repo_dir=str(repo), check_files=["good.py"])
            self.assertTrue(r1["ok"])
            self.assertTrue(r2["ok"])
            self.assertEqual(r2["remote"]["file_hashes"]["good.py"], loc["file_hashes"]["good.py"])
        finally:
            srv.shutdown()
            srv.server_close()

        brief = self.core.oracle.morning_brief()
        self.assertTrue(brief["ok"])
        self.assertLessEqual(brief["line_count"], 20)
        self.assertIn("CHIMERA-PROMETHEUS Morning Brief", brief["brief"])

    # --- Wave 2C: CHIMERA-GHOST-POOL (Shared Read-Ring + Cooperative Socket-Activation) ---

    def test_05_ghost_read_ring_and_socket_activation_zero_idle(self) -> None:
        sample = self.root / "hot.txt"
        sample.write_text("alpha\nbeta\ngamma\n" * 120, encoding="utf-8")

        raw1, m1 = self.core.ghost.get_or_read(sample)
        self.assertFalse(m1["hit"])
        raw2, m2 = self.core.ghost.get_or_read(sample)
        self.assertTrue(m2["hit"])
        self.assertEqual(m2["tier"], "ram")
        self.assertEqual(raw1, raw2)

        # Second GhostReadRing pointing at the same SQLite WAL hits cross-process!
        ring2 = GhostReadRing(self.root / "prom_data" / "ghost_ring.sqlite")
        try:
            raw3, m3 = ring2.get_or_read(sample)
            self.assertTrue(m3["hit"])
            self.assertEqual(m3["tier"], "shared_wal")
            self.assertEqual(raw3, raw1)
        finally:
            ring2.close()

        # mtime/size change invalidates stale page automatically
        sample.write_text("UPDATED_CONTENT_NEW_SIZE\n", encoding="utf-8")
        raw4, m4 = self.core.ghost.get_or_read(sample)
        self.assertFalse(m4["hit"])
        self.assertEqual(raw4.replace(b"\r\n", b"\n"), b"UPDATED_CONTENT_NEW_SIZE\n")

        # Cooperative Socket-Activation Proxy (0 backend when idle -> wake on request -> sleep back to 0)
        b_port = _free_port()
        holder: dict[str, http.server.ThreadingHTTPServer | None] = {"srv": None}

        class _Backend(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                payload = b'{"ok":true,"worker":"ephemeral_backend"}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, fmt: str, *args) -> None:
                return

        def _start_backend() -> bool:
            s = http.server.ThreadingHTTPServer(("127.0.0.1", b_port), _Backend)
            holder["srv"] = s
            threading.Thread(target=s.serve_forever, daemon=True).start()
            return True

        def _stop_backend() -> None:
            s = holder.get("srv")
            holder["srv"] = None
            if s is not None:
                s.shutdown()
                s.server_close()

        proxy = SocketActivationProxy(
            name="test_worker",
            listen_port=0,
            backend_port=b_port,
            start_backend_fn=_start_backend,
            stop_backend_fn=_stop_backend,
            idle_timeout_s=0.45,
        )
        p_port = proxy.start()
        try:
            self.assertFalse(proxy.status()["backend_awake"])
            code, data = _http_json(f"http://127.0.0.1:{p_port}/ping")
            self.assertEqual(code, 200)
            self.assertEqual(data["worker"], "ephemeral_backend")
            self.assertEqual(proxy.status()["wakes"], 1)
            # Wait for idle sleep
            time.sleep(0.9)
            st_after = proxy.status()
            self.assertFalse(st_after["backend_awake"])
            self.assertGreaterEqual(st_after["sleeps"], 1)
        finally:
            proxy.close()

    # --- Integration: HookRouter + AgentHyperBus + StreamableMcpServer ---

    def test_06_hooks_and_mcp_prometheus_wiring(self) -> None:
        rt = OmegaSpineRuntime(ops_dir=self.root / "omega_ops", ephemeral=True, enable_dotnet_build=False)
        try:
            prom = rt.hooks._get_prometheus()
            self.assertIsNotNone(prom)
            # Acquire soak lease owned by sibling -> verify SessionStart & PreToolUse warn/redirect
            lease = prom.epoch.acquire_soak_lease(owner_id="sibling-soak", window_s=600.0, target_pid=9999)
            ss = rt.hooks.handle_event("SessionStart", {"conversationId": "agent-2", "workspaceRoots": [str(self.root)]})
            msg = ss["injectSteps"][0]["systemMessage"]["systemMessage"]
            self.assertIn("[CHIMERA-AXIOM", msg)
            self.assertIn("SOAK-FREEZE ACTIVE", msg)

            rt.hooks.handle_event(
                "PreToolUse",
                {
                    "conversationId": "agent-2",
                    "toolCall": {
                        "name": "run_command",
                        "arguments": {"CommandLine": "systemctl restart chimera-hyper-daemon"},
                    },
                },
            )
            self.assertGreaterEqual(rt.hooks.status()["stats"]["epoch_soak_redirects"], 1)
            prom.epoch.release_soak_lease(lease["lease_id"])

            # PostToolUse passively feeds Ghost Read-Ring
            f_read = self.root / "doc.py"
            f_read.write_text("VALUE = 42\n", encoding="utf-8")
            rt.hooks.handle_event(
                "PostToolUse",
                {
                    "conversationId": "agent-2",
                    "toolCall": {
                        "name": "read_file",
                        "arguments": {"Path": str(f_read)},
                    },
                },
            )
            self.assertGreaterEqual(rt.hooks.status()["stats"]["ghost_ring_ingests"], 1)
            raw, meta = prom.ghost.get_file(f_read)
            self.assertTrue(meta["hit"])
            self.assertEqual(raw.replace(b"\r\n", b"\n"), b"VALUE = 42\n")

            # AgentHyperBus xray_batch supports axiom_check & ghost_read
            bus = AgentHyperBus(ephemeral=True)
            xr = bus.xray_batch(
                [
                    {"op": "axiom_check", "target_action": "autocad_offload_build"},
                    {"op": "ghost_read", "path": str(f_read)},
                ],
                cwd=str(self.root),
            )
            self.assertTrue(xr["ok"])
            self.assertTrue(xr["results"][0]["veto"])
            self.assertTrue(xr["results"][1]["ok"])
        finally:
            rt.close()

    # --- Wave 3: Native Compiled CHIMERA-MICRONUCLEUS Live E2E ---

    def test_07_native_micronucleus_binary_rss_ghost_and_ephemeral_organ(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        if os.name == "nt":
            bin_path = repo_root / "native" / "chimera_core" / "target" / "release" / "chimera_spine.exe"
        else:
            bin_path = repo_root / "native" / "chimera_core" / "c_linux" / "chimera_spine"
        if not bin_path.is_file():
            self.skipTest(f"Native micronucleus binary not built at {bin_path}")

        spine_port = _free_port()
        organ_port = _free_port()
        nixl_file = self.root / "test_nixl.bin"
        # Write 64B NIXL ring with ENDO at offset 32..63
        import struct
        endo = struct.pack("<4sHH6f", b"ENDO", 7, 1234, 0.25, 0.10, 0.85, 0.05, 0.0, 0.90)
        nixl_file.write_bytes(bytes(32) + endo)

        organ_script = self.root / "mini_organ.py"
        organ_script.write_text(
            "import http.server, json, sys\n"
            "port = int(sys.argv[1])\n"
            "class H(http.server.BaseHTTPRequestHandler):\n"
            "    def do_GET(self):\n"
            "        b = json.dumps({'ok': True, 'organ': 'ephemeral_python', 'path': self.path}).encode()\n"
            "        self.send_response(200); self.send_header('Content-Type','application/json')\n"
            "        self.send_header('Content-Length', str(len(b))); self.end_headers(); self.wfile.write(b)\n"
            "    def log_message(self, *a): pass\n"
            "http.server.HTTPServer(('127.0.0.1', port), H).serve_forever()\n",
            encoding="utf-8",
        )
        sample = self.root / "spine_cached.txt"
        sample.write_text("micronucleus native ghost test\n", encoding="utf-8")

        cf = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        proc = subprocess.Popen(
            [
                str(bin_path),
                "--port", str(spine_port),
                "--organ-port", str(organ_port),
                "--idle-secs", "1",
                "--nixl-path", str(nixl_file),
                "--organ-cmd", sys.executable, str(organ_script), str(organ_port),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=cf,
        )
        try:
            # Wait for spine ready
            ready = False
            for _ in range(50):
                try:
                    c, h = _http_json(f"http://127.0.0.1:{spine_port}/healthz", timeout=1.0)
                    if c == 200 and h.get("ok"):
                        ready = True
                        break
                except Exception:
                    time.sleep(0.05)
            self.assertTrue(ready, "Native chimera_spine did not start in time")

            # 1) Hot path runs with 0 B Python and < 15 MiB native RSS
            c1, h1 = _http_json(f"http://127.0.0.1:{spine_port}/healthz")
            self.assertEqual(c1, 200)
            self.assertEqual(h1["python_organ_state"], "sleeping_0_bytes")
            self.assertLess(h1["rss_mib"], 15.0)

            # 2) Direct 64B NIXL hormone read in native code
            c2, nx = _http_json(f"http://127.0.0.1:{spine_port}/v1/nixl/hormones")
            self.assertEqual(c2, 200)
            self.assertTrue(nx["ok"])
            self.assertEqual(nx["magic"], "ENDO")
            self.assertEqual(nx["seq"], 7)
            self.assertAlmostEqual(nx["hormones"]["dopamine"], 0.85, places=2)

            # 3) Native Ghost Read-Ring miss -> hit
            q = urllib.parse.quote(str(sample))
            _, g1 = _http_json(f"http://127.0.0.1:{spine_port}/v1/ghost/get?path={q}")
            _, g2 = _http_json(f"http://127.0.0.1:{spine_port}/v1/ghost/get?path={q}")
            self.assertFalse(g1["hit"])
            self.assertTrue(g2["hit"])

            # 4) Complex route wakes ephemeral Python organ -> proxies 200 OK
            c3, org = _http_json(f"http://127.0.0.1:{spine_port}/v1/bios/ping")
            self.assertEqual(c3, 200)
            self.assertEqual(org["organ"], "ephemeral_python")

            _, h_awake = _http_json(f"http://127.0.0.1:{spine_port}/healthz")
            self.assertEqual(h_awake["organ_wakes"], 1)
            self.assertEqual(h_awake["requests_proxied"], 1)

            # 5) Wait past 1s idle -> native reaper puts Python organ back to 0 B
            time.sleep(1.8)
            _, h_slept = _http_json(f"http://127.0.0.1:{spine_port}/healthz")
            self.assertEqual(h_slept["python_organ_state"], "sleeping_0_bytes")
            self.assertGreaterEqual(h_slept["organ_sleeps"], 1)
        finally:
            try:
                _http_json(f"http://127.0.0.1:{spine_port}/v1/spine/shutdown", method="POST", body={}, timeout=1.5)
            except Exception:
                pass
            try:
                proc.wait(timeout=3)
            except Exception:
                proc.kill()
                proc.wait(timeout=2)


if __name__ == "__main__":
    unittest.main()
