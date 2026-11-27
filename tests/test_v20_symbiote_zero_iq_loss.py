"""Unit & Live HTTP tests for CHIMERA v20 ZERO-IQ-LOSS SYMBIOTE."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import urllib.request

from chimera_tp.autopilot import OpsConfig
from chimera_tp.dashboard import ChimeraDaemon
from chimera_tp.overmind_cortex import PulseEventBus
from chimera_tp.symbiote_engine import ChimeraSymbioteEngine


class TestV20SymbioteZeroIqLoss(unittest.TestCase):
    def test_01_bone_marrow_lz4_bit_exact_and_lru_cap(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            eng = ChimeraSymbioteEngine(td, max_blob_bytes=80 * 1024, max_entries=3)
            # 256 KB synthetic encrypted_reasoning payload (repetitive JSON structure, high compression ratio)
            payload = json.dumps(
                {
                    "type": "reasoning",
                    "id": "rs_01",
                    "encrypted_content": ("gAAAAABk" + "A1B2C3D4E5F6" * 32) * 650,
                    "meta": {"effort": "max", "zero_iq_loss": True},
                }
            ).encode("utf-8")
            self.assertGreater(len(payload), 250_000)

            put_res = eng.put_blob(payload, key="rs_256k")
            self.assertTrue(put_res["ok"])
            self.assertLess(put_res["compressed_bytes"], len(payload) * 0.5)
            recovered = eng.get_blob("rs_256k")
            self.assertEqual(recovered, payload)
            self.assertEqual(hashlib.sha256(recovered).hexdigest(), hashlib.sha256(payload).hexdigest())

            # Fill 4 entries of ~25 KB raw / compressible to test max_entries=3 LRU eviction
            for idx in range(4):
                p = (f"block-{idx}-" + ("xyz123" * 4000)).encode("utf-8")
                eng.put_blob(p, key=f"k_{idx}")
            st = eng.status()["bone_marrow"]
            self.assertLessEqual(st["entries"], 3)
            self.assertLessEqual(st["current_compressed_bytes"], 80 * 1024)
            self.assertGreaterEqual(st["evictions"], 1)

    def test_02_immortal_360s_registry_bit_exact_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            eng = ChimeraSymbioteEngine(td)
            reg = eng.register_immortal("turn_360_1", vault_key="vault_abc", meta={"model": "gpt-6.2-astra", "effort": "max"})
            self.assertTrue(reg["ok"])
            self.assertEqual(reg["status"], "inflight")

            pending = eng.lookup_immortal("turn_360_1", include_bytes=True)
            self.assertTrue(pending["found"])
            self.assertEqual(pending["status"], "inflight")

            sse_bytes = (
                b'event: response.created\ndata: {"type":"response.created"}\n\n'
                b'event: response.output_text.delta\ndata: {"type":"response.output_text.delta","delta":"zero iq loss"}\n\n'
                b'event: response.completed\ndata: {"type":"response.completed","response":{"status":"completed"}}\n\n'
            )
            comp = eng.complete_immortal(
                "turn_360_1",
                sse_bytes,
                vault_key="vault_abc",
                cut="autocut-collab-done",
                model="gpt-6.2-astra",
                effort="max",
            )
            self.assertTrue(comp["ok"])

            rec = eng.lookup_immortal("turn_360_1", include_bytes=True)
            self.assertTrue(rec["found"])
            self.assertEqual(rec["status"], "completed")
            self.assertEqual(rec["cut"], "autocut-collab-done")
            self.assertEqual(base64.b64decode(rec["sse_b64"]), sse_bytes)

    def test_03_merkle_prefix_auditor_and_stale_read_sha256(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            pulse = PulseEventBus(node_id="symbiote-test")
            eng = ChimeraSymbioteEngine(td, pulse_bus=pulse)

            # Turn 1 -> clean initial
            r1 = eng.audit_prefix("sess_kv", ["d0", "d1", "d2"], account_id="acct_alpha")
            self.assertFalse(r1["mid_prefix_break"])
            self.assertEqual(r1["affinity_account_id"], "acct_alpha")

            # Turn 2 -> strict append-only -> clean KV-cache preserved
            r2 = eng.audit_prefix("sess_kv", ["d0", "d1", "d2", "d3"])
            self.assertFalse(r2["mid_prefix_break"])
            self.assertEqual(r2["matched_prefix_len"], 3)
            self.assertEqual(eng.get_kv_affinity("sess_kv")["account_id"], "acct_alpha")

            # Turn 3 -> mid-prefix mutation at index 1 -> flagged + Pulse emitted
            r3 = eng.audit_prefix("sess_kv", ["d0", "MUTATED", "d2", "d3", "d4"])
            self.assertTrue(r3["mid_prefix_break"])
            self.assertEqual(r3["break_index"], 1)
            events = pulse.poll(since_seq=0, limit=20)["events"]
            self.assertTrue(any(ev.get("topic") == "SYMBIOTE_PREFIX_BREAK" for ev in events))

            # Deterministic SHA-256 stale file-read detector
            body_a = "def calculate_tax(amount):\n    return round(amount * 0.08, 2)\n" * 4
            sr = eng.detect_stale_file_reads(
                [
                    {"path": "tax.py", "content": body_a, "turn_index": 0},
                    {"path": "tax.py", "content": body_a, "turn_index": 3},
                ]
            )
            self.assertEqual(sr["duplicate_count"], 1)
            self.assertGreater(sr["reclaimable_bytes"], 100)

    def test_04_zero_completed_vaccine_and_pulse_alert(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            pulse = PulseEventBus(node_id="vaccine-test")
            eng = ChimeraSymbioteEngine(td, pulse_bus=pulse)

            r_ok = eng.observe_usage({"cut": "autocut-collab-done", "status": 200, "scalpel_immediate": True})
            self.assertFalse(r_ok["leak_recorded"])
            self.assertEqual(eng.status()["vaccine"]["scalpel_immediate_cuts"], 1)

            r_leak = eng.observe_usage(
                {
                    "cut": "completed",
                    "status": 200,
                    "model": "gpt-6.2-astra",
                    "effort": "max",
                    "auto_cut_miss_reason": "reserved_collaboration_tool_same_chunk",
                    "tool_names": ["collaboration.spawn_agent"],
                    "payload_bytes": 1048576,
                    "cache_ratio": 0.94,
                }
            )
            self.assertTrue(r_leak["leak_recorded"])
            st = eng.status()["vaccine"]
            self.assertEqual(st["completed_count"], 1)
            self.assertEqual(len(st["recent_completed_leaks"]), 1)
            events = pulse.poll(since_seq=0, limit=20)["events"]
            self.assertTrue(any(ev.get("topic") == "SYMBIOTE_COMPLETED_LEAK" for ev in events))

    def test_05_precog_verify_and_live_http_routes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "Tester"], cwd=repo, check=True)
            main_py = repo / "main.py"
            main_py.write_text("def ok():\n    return 1\n", encoding="utf-8")
            subprocess.run(["git", "add", "main.py"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)

            # Create untracked broken helper file
            helper = repo / "_rounding.py"
            helper.write_text("def broken(:\n    return 0\n", encoding="utf-8")

            eng = ChimeraSymbioteEngine(root / "ops")
            bad = eng.precog_verify(str(repo), changed_files=["main.py"])
            self.assertFalse(bad["ok"])
            self.assertIn("_rounding.py", bad["untracked_code_files"])
            self.assertEqual(bad["syntax_errors"][0]["file"], "_rounding.py")
            self.assertIn("<chimera_ground_truth_verify>", bad["ground_truth_block"])

            # Fix syntax -> precog passes
            helper.write_text("def round_half(x):\n    return int(x + 0.5)\n", encoding="utf-8")
            good = eng.precog_verify(str(repo), changed_files=["main.py"])
            self.assertTrue(good["ok"])
            self.assertEqual(good["syntax_errors"], [])

            # Live ChimeraDaemon HTTP API verification
            cfg = OpsConfig(
                role="server",
                node_name="symbiote-http-test",
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
                phantom_enabled=False,
            )
            daemon = ChimeraDaemon(config=cfg, ops_dir=root / "daemon_ops", auto_seed_on_empty=False).start()
            base = f"http://127.0.0.1:{daemon.http_addr[1]}"
            try:
                def post(path: str, data: dict) -> dict:
                    req = urllib.request.Request(
                        f"{base}{path}",
                        data=json.dumps(data).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    with urllib.request.urlopen(req, timeout=4.0) as r:
                        return json.loads(r.read().decode("utf-8"))

                blob_in = ("Symbiote HTTP test payload " * 600).encode("utf-8")
                bp = post("/api/symbiote/blob/put", {"data_b64": base64.b64encode(blob_in).decode("ascii")})
                self.assertTrue(bp["ok"])
                with urllib.request.urlopen(f"{base}/api/symbiote/blob/get?key={bp['key']}", timeout=4.0) as r:
                    bg = json.loads(r.read().decode("utf-8"))
                self.assertTrue(bg["ok"])
                self.assertEqual(base64.b64decode(bg["data_b64"]), blob_in)

                pa = post("/api/symbiote/prefix/audit", {"session_id": "http_s1", "item_digests": ["a", "b"], "account_id": "acc_1"})
                self.assertTrue(pa["ok"])
                with urllib.request.urlopen(f"{base}/api/symbiote/kv-affinity?session_id=http_s1", timeout=4.0) as r:
                    kva = json.loads(r.read().decode("utf-8"))
                self.assertEqual(kva["account_id"], "acc_1")

                ou = post("/api/symbiote/observe-usage", {"cut": "completed", "model": "gpt-6.2-astra", "auto_cut_miss_reason": "test"})
                self.assertTrue(ou["leak_recorded"])

                with urllib.request.urlopen(f"{base}/api/symbiote/status", timeout=4.0) as r:
                    st = json.loads(r.read().decode("utf-8"))
                self.assertTrue(st["ok"])
                self.assertTrue(st["zero_iq_loss_axiom"])
                self.assertGreaterEqual(st["bone_marrow"]["blobs_stored"], 1)
                self.assertGreaterEqual(st["vaccine"]["completed_count"], 1)
            finally:
                daemon.close()

    def test_06_immortal_step_sig_isolation_and_detached_guard(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            eng = ChimeraSymbioteEngine(td)
            sse_step1 = (
                b'event: response.output_item.done\n'
                b'data: {"type":"response.output_item.done","item":{"type":"custom_tool_call","call_id":"call_step1","name":"exec","input":"echo 1"}}\n\n'
                b'event: response.completed\n'
                b'data: {"type":"response.completed","response":{"status":"completed"}}\n\n'
            )

            # Non-detached 200 OK completions must NEVER enter the Immortal remote cache.
            refused = eng.complete_immortal(
                "turn_iso_1",
                sse_step1,
                vault_key="v_step1",
                step_sig="sig_step1",
                detached_harvest=False,
            )
            self.assertFalse(refused["ok"])
            self.assertEqual(refused["error"], "not_detached_harvest")

            # Detached harvest for step 1 is stored strictly under (turn_key, step_sig).
            ok_put = eng.complete_immortal(
                "turn_iso_1",
                sse_step1,
                vault_key="v_step1",
                step_sig="sig_step1",
                detached_harvest=True,
                cut="autocut-toolpad",
            )
            self.assertTrue(ok_put["ok"])

            hit1 = eng.lookup_immortal("turn_iso_1", step_sig="sig_step1", require_detached=True, include_bytes=True)
            self.assertTrue(hit1["found"])
            self.assertTrue(hit1["detached_harvest"])
            self.assertEqual(hit1["step_sig"], "sig_step1")
            self.assertEqual(base64.b64decode(hit1["sse_b64"]), sse_step1)

            # Next step on the same turn_id with a different step_sig must NEVER replay step 1!
            miss2 = eng.lookup_immortal("turn_iso_1", step_sig="sig_step2", require_detached=True, include_bytes=True)
            self.assertFalse(miss2["found"])

    def test_07_codex_surgeon_atomic_heal_and_backup(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            sess_dir = root / "sessions" / "2026" / "11" / "27"
            sess_dir.mkdir(parents=True)
            sid = "01a29999-b392-7ca1-9609-1a6bffb93a30"
            rollout = sess_dir / f"rollout-2026-11-27T00-00-00-{sid}.jsonl"
            call_payload = {
                "type": "custom_tool_call",
                "status": "completed",
                "call_id": "call_dup_1",
                "name": "exec",
                "input": "echo hello",
                "id": "ctc_dup_1",
            }
            lines = [
                json.dumps({"timestamp": "2026-11-27T00:00:00Z", "type": "session_meta", "payload": {"id": sid}}),
                json.dumps({"timestamp": "2026-11-27T00:00:01Z", "type": "response_item", "payload": call_payload}),
                json.dumps({"timestamp": "2026-11-27T00:00:02Z", "type": "response_item", "payload": {"type": "custom_tool_call_output", "call_id": "call_dup_1", "output": "ok1", "id": "ctco_1"}}),
                json.dumps({"timestamp": "2026-11-27T00:00:03Z", "type": "response_item", "payload": dict(call_payload)}),
                json.dumps({"timestamp": "2026-11-27T00:00:04Z", "type": "response_item", "payload": {"type": "custom_tool_call_output", "call_id": "call_dup_1", "output": "ok2", "id": "ctco_2"}}),
                json.dumps({"timestamp": "2026-11-27T00:00:05Z", "type": "response_item", "payload": dict(call_payload)}),
                json.dumps({"timestamp": "2026-11-27T00:00:06Z", "type": "response_item", "payload": {"type": "custom_tool_call_output", "call_id": "call_dup_1", "output": "ok3", "id": "ctco_3"}}),
            ]
            orig_text = "\n".join(lines) + "\n"
            rollout.write_text(orig_text, encoding="utf-8")

            pulse = PulseEventBus(node_id="surgeon-test")
            eng = ChimeraSymbioteEngine(root / "ops", pulse_bus=pulse)

            # Invalid session id must be rejected (path traversal guard)
            with self.assertRaises(ValueError):
                eng.heal_codex_rollout_jsonl("../evil", sessions_dir=root / "sessions")

            # Active recent write must be skipped when min_idle_sec=60
            skipped = eng.heal_codex_rollout_jsonl(sid, sessions_dir=root / "sessions", min_idle_sec=60.0)
            self.assertFalse(skipped["ok"])
            self.assertTrue(skipped["skipped"])
            self.assertEqual(skipped["reason"], "file_recently_modified")

            # Heal atomically with min_idle_sec=0
            res = eng.heal_codex_rollout_jsonl(sid, sessions_dir=root / "sessions", min_idle_sec=0.0)
            self.assertTrue(res["ok"])
            self.assertTrue(res["changed"])
            self.assertEqual(res["healed_calls"], 2)
            self.assertEqual(res["healed_outputs"], 2)
            self.assertEqual(res["duplicates_remaining"], 0)
            bak = Path(res["backup_path"])
            self.assertTrue(bak.is_file())
            self.assertEqual(bak.read_text(encoding="utf-8"), orig_text)

            healed_objs = [json.loads(x) for x in rollout.read_text(encoding="utf-8").splitlines()]
            calls = [o["payload"] for o in healed_objs if o["type"] == "response_item" and o["payload"]["type"] == "custom_tool_call"]
            outs = [o["payload"] for o in healed_objs if o["type"] == "response_item" and o["payload"]["type"] == "custom_tool_call_output"]
            self.assertEqual([c["call_id"] for c in calls], ["call_dup_1", "call_dup_1_r2", "call_dup_1_r3"])
            self.assertEqual([o["call_id"] for o in outs], ["call_dup_1", "call_dup_1_r2", "call_dup_1_r3"])
            self.assertEqual(len({c["id"] for c in calls}), 3)

            # Idempotent re-run reports changed=False
            res2 = eng.heal_codex_rollout_jsonl(sid, sessions_dir=root / "sessions", min_idle_sec=0.0)
            self.assertTrue(res2["ok"])
            self.assertFalse(res2["changed"])
            self.assertGreaterEqual(eng.status()["surgeon"]["heals"], 1)

    def test_08_codex_surgeon_time_travel_clean_fork_and_http(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            sess_dir = root / "sessions" / "2026" / "11" / "27"
            sess_dir.mkdir(parents=True)
            sid = "01a28888-b392-7ca1-9609-1a6bffb93a30"
            rollout = sess_dir / f"rollout-2026-11-27T00-00-00-{sid}.jsonl"
            lines = [
                json.dumps({"timestamp": "2026-11-27T00:00:00Z", "type": "session_meta", "payload": {"id": sid}}),
                json.dumps({"timestamp": "2026-11-27T00:00:01Z", "type": "turn_context", "payload": {"turn_id": "t1"}}),
                json.dumps({"timestamp": "2026-11-27T00:00:02Z", "type": "response_item", "payload": {"type": "function_call", "call_id": "call_clean_1", "name": "read", "arguments": "{}"}}),
                json.dumps({"timestamp": "2026-11-27T00:00:03Z", "type": "response_item", "payload": {"type": "function_call_output", "call_id": "call_clean_1", "output": "ok"}}),
                json.dumps({"timestamp": "2026-11-27T00:00:04Z", "type": "response_item", "payload": {"type": "function_call", "call_id": "call_clean_1", "name": "read", "arguments": "{}"}}),
                "{CORRUPT_TAIL",
            ]
            rollout.write_text("\n".join(lines) + "\n", encoding="utf-8")

            cfg = OpsConfig(
                role="server",
                node_name="surgeon-http-test",
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
                phantom_enabled=False,
            )
            daemon = ChimeraDaemon(config=cfg, ops_dir=root / "daemon_ops", auto_seed_on_empty=False).start()
            base = f"http://127.0.0.1:{daemon.http_addr[1]}"
            try:
                req = urllib.request.Request(
                    f"{base}/api/symbiote/surgeon/fork",
                    data=json.dumps({"session_id": sid, "sessions_dir": str(root / "sessions")}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=4.0) as r:
                    fork_res = json.loads(r.read().decode("utf-8"))
                self.assertTrue(fork_res["ok"])
                self.assertEqual(fork_res["kept_lines"], 4)
                self.assertEqual(fork_res["dropped_lines"], 2)
                fork_file = Path(fork_res["fork_path"])
                self.assertTrue(fork_file.is_file())
                fork_objs = [json.loads(x) for x in fork_file.read_text(encoding="utf-8").splitlines()]
                self.assertEqual(len(fork_objs), 4)
                self.assertEqual(fork_objs[0]["payload"]["id"], fork_res["new_session_id"])

                # Also verify HTTP /api/symbiote/surgeon/heal dry_run route works cleanly
                req_h = urllib.request.Request(
                    f"{base}/api/symbiote/surgeon/heal",
                    data=json.dumps({"session_id": sid, "sessions_dir": str(root / "sessions"), "min_idle_sec": 0.0, "dry_run": True}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req_h, timeout=4.0) as r:
                    dry_res = json.loads(r.read().decode("utf-8"))
                self.assertTrue(dry_res["ok"])
                self.assertTrue(dry_res["dry_run"])
                self.assertEqual(dry_res["healed_calls"], 1)
            finally:
                daemon.close()
