"""Tests for Zero-Shell Self-Converging Release Conductor & Swarm Dead-Man's Switch."""

from __future__ import annotations

import base64
import hashlib
import http.server
import io
import json
import tarfile
import tempfile
import threading
import unittest
from pathlib import Path

from chimera_tp.omega_spine.hook_router import HookRouter, OmegaSpineRuntime
from chimera_tp.omega_spine.release_conductor import ReleaseConductor, context_hygiene_audit


def _make_fake_chimera_src(base: Path, *, bad_syntax: bool = False) -> Path:
    src = base / "dev_repo"
    osp = src / "chimera_tp" / "omega_spine"
    osp.mkdir(parents=True, exist_ok=True)
    (src / "chimera_tp" / "__init__.py").write_text('__version__ = "18.0.0"\n', encoding="utf-8")
    (osp / "__init__.py").write_text("OK = True\n", encoding="utf-8")
    (osp / "streamable_mcp.py").write_text("MCP = True\n", encoding="utf-8")
    (osp / "hook_router.py").write_text("HOOKS = True\n", encoding="utf-8")
    if bad_syntax:
        (osp / "release_conductor.py").write_text("def broken(:\n    pass\n", encoding="utf-8")
    else:
        (osp / "release_conductor.py").write_text("RC = True\n", encoding="utf-8")
    return src


class TestReleaseConductorAndDeadMan(unittest.TestCase):
    def test_01_stage_verify_and_two_phase_desired_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            rel_root = root / "releases"
            src_ok = _make_fake_chimera_src(root / "good")
            rc = ReleaseConductor(releases_root=rel_root)

            staged = rc.stage_release(src_ok, epoch="bios_test_001", verify=True, write_desired=True)
            self.assertTrue(staged["ok"], staged)
            self.assertEqual(staged["epoch"], "bios_test_001")
            self.assertEqual(staged["py_files"], 5)
            self.assertTrue((rel_root / "bios_test_001" / "RELEASE_MANIFEST.json").is_file())
            self.assertTrue(rc.desired_manifest_path.is_file())

            # Corrupt release MUST be rejected BEFORE touching DESIRED_RELEASE.json
            src_bad = _make_fake_chimera_src(root / "bad", bad_syntax=True)
            bad_res = rc.stage_release(src_bad, epoch="bios_bad_002", verify=True, write_desired=True)
            self.assertFalse(bad_res["ok"])
            self.assertEqual(bad_res["error"], "py_compile_failed")
            desired = json.loads(rc.desired_manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(desired["epoch"], "bios_test_001")

    def test_02_push_over_http_replication_and_tamper_traversal_guards(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src_ok = _make_fake_chimera_src(root / "src")
            win_rel = root / "win_releases"
            sv_rel = root / "sv_releases"

            # Pre-seed an existing release on peer with a platform-native binary to verify preservation
            donor = sv_rel / "prev_epoch" / "chimera_tp"
            donor.mkdir(parents=True, exist_ok=True)
            native_fn = "_chimera_core.dll" if (Path.cwd().drive) else "_chimera_core.so"
            (donor / native_fn).write_bytes(b"NATIVE_BIN_PAYLOAD")

            win_rc = ReleaseConductor(releases_root=win_rel)
            sv_rc = ReleaseConductor(releases_root=sv_rel, active_release_dir=sv_rel / "prev_epoch")
            win_rc.stage_release(src_ok, epoch="bios_sync_99", verify=True)

            # Spin ephemeral HTTP peer receiving /v1/omega/release/receive
            class Handler(http.server.BaseHTTPRequestHandler):
                def do_POST(self):
                    ln = int(self.headers.get("Content-Length", "0"))
                    body = json.loads(self.rfile.read(ln).decode("utf-8"))
                    res = sv_rc.receive_release(body)
                    raw = json.dumps(res).encode("utf-8")
                    self.send_response(200 if res.get("ok") else 400)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)

                def log_message(self, *_args):
                    pass

            srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            port = srv.server_address[1]
            th = threading.Thread(target=srv.serve_forever, daemon=True)
            th.start()
            try:
                rep = win_rc.replicate_to_peer("bios_sync_99", f"http://127.0.0.1:{port}", write_desired=True)
                self.assertTrue(rep["ok"], rep)
                peer_res = rep["peer_response"]
                self.assertTrue(peer_res["ok"])
                self.assertIn(f"chimera_tp/{native_fn}", peer_res["preserved_binaries"])
                desired = json.loads(sv_rc.desired_manifest_path.read_text(encoding="utf-8"))
                self.assertEqual(desired["epoch"], "bios_sync_99")
                self.assertEqual(desired["rollback_epoch"], "prev_epoch")

                # Security check 1: tampered SHA-256 rejected
                bad_wire = win_rc.pack_release_payload("bios_sync_99")
                bad_wire["archive_sha256"] = "0" * 64
                self.assertFalse(sv_rc.receive_release(bad_wire)["ok"])

                # Security check 2: tar path traversal rejected
                tbuf = io.BytesIO()
                with tarfile.open(fileobj=tbuf, mode="w:gz") as tf:
                    ti = tarfile.TarInfo("../escape.py")
                    data = b"print('escape')\n"
                    ti.size = len(data)
                    tf.addfile(ti, io.BytesIO(data))
                tb = tbuf.getvalue()
                trav = sv_rc.receive_release({
                    "epoch": "evil_trav_1",
                    "archive_sha256": hashlib.sha256(tb).hexdigest(),
                    "archive_b64": base64.b64encode(tb).decode("ascii"),
                })
                self.assertFalse(trav["ok"])
                self.assertIn("Unsafe tar member", trav["error"])
            finally:
                srv.shutdown()
                srv.server_close()

    def test_03_swarm_dead_man_switch_releases_lease_and_alerts_coordinator(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ws = str(Path(td).resolve())
            rt = OmegaSpineRuntime(ops_dir=Path(td), ephemeral=True, enable_dotnet_build=False)
            try:
                # Worker acquires Hive lease on SmartEditSolver.cs
                rt.hooks.handle_event("session_start", {"conversationId": "worker-release-ops", "cwd": ws})
                rt.hooks.handle_event("pre_tool_use", {
                    "conversationId": "worker-release-ops",
                    "cwd": ws,
                    "toolCall": {"name": "edit_file", "args": {"Path": "chimera_tp/dashboard.py"}},
                })
                self.assertEqual(len(rt.hive.list_leases(repo=ws)), 1)

                # Worker gets blocked by pre-tool security policy hook
                rt.hooks.handle_event("post_tool_use", {
                    "conversationId": "worker-release-ops",
                    "cwd": ws,
                    "toolCall": {"name": "run_command", "args": {"CommandLine": "Start-ScheduledTask"}},
                    "error": "tool call denied by pre-tool hook: This tool call was blocked due to potential violation of a security policy. All further execution must stop immediately.",
                })

                # Lease must be auto-released immediately so sibling workers are never deadlocked!
                self.assertEqual(len(rt.hive.list_leases(repo=ws)), 0)

                # Coordinator's very next pre_invocation receives out-of-band SWARM BLOCKER + 0-token HUD badge!
                pre = rt.hooks.handle_event("pre_invocation", {"conversationId": "coordinator-1", "cwd": ws})
                steps = pre.get("injectSteps") or []
                self.assertEqual(len(steps), 1)
                msg = steps[0]["systemMessage"]["systemMessage"]
                badge = steps[0]["systemMessage"]["metadata"]["user_markdown"]
                self.assertIn("SWARM BLOCKER", msg)
                self.assertIn("worker-release-ops", msg)
                self.assertIn("BLOCKED: 1", badge)
            finally:
                rt.close()

    def test_04_context_hygiene_audit_flags_bloated_trigger_file_readonly(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            gem = ws / "GEMINI.md"
            gem.write_text("# Policy\nOperating Policy reverse shell exploit " + ("x" * 17000), encoding="utf-8")
            res = context_hygiene_audit([str(ws)])
            self.assertTrue(res["ok"])
            self.assertFalse(res["clean"])
            hit = next(f for f in res["findings"] if Path(f["path"]).resolve() == gem.resolve())
            self.assertTrue(hit["bloated"])
            self.assertIn("reverse shell", hit["trigger_hits"])


if __name__ == "__main__":
    unittest.main()
