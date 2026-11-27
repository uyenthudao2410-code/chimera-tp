"""Comprehensive tests for CHIMERA-MNEMOSYNE (Unified Zero-Loss Raw-Memory & Zero-Shell Execution)."""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import threading
import time
import unittest
import urllib.request
import zipfile
from pathlib import Path

from chimera_tp.autopilot import OpsConfig
from chimera_tp.dashboard import ChimeraDaemon
from chimera_tp.platform.mnemosyne import (
    AkashicRawStore,
    MnemosyneCore,
    WarmPythonReplPool,
    audit_system_entropy,
    run_raw_arena_benchmark,
)


def _http_json(url: str, *, method: str = "GET", body: dict | None = None, timeout: float = 10.0) -> tuple[int, dict]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    hdrs = {"Content-Type": "application/json"} if body is not None else {}
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=timeout) as resp:
        return int(resp.status), json.loads(resp.read().decode("utf-8"))


class TestChimeraMnemosyneUnified(unittest.TestCase):
    def test_01_akashic_raw_append_only_causal_cascade_and_reality_stamp(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "demo_repo"
            repo.mkdir()
            target_file = repo / "substrate.py"
            target_file.write_text("def start():\n    return True\n", encoding="utf-8")
            old_ts = target_file.stat().st_mtime - 600.0

            store = AkashicRawStore(db_path=root / "raw.sqlite")
            try:
                # Multi-hop causal chain A -> B -> C where C does NOT mention A's keyword!
                store.append_raw_turn(
                    source_kind="codex_raw",
                    source_path="codex.sqlite",
                    source_locator="rowid:1",
                    thread_id="th_1",
                    turn_idx=1,
                    repo=str(repo),
                    ts=old_ts,
                    text=f"Root decision: edited {target_file} to call attach_bios before start_autonomic_pulse in release 65bbee57e75f.",
                )
                store.append_raw_turn(
                    source_kind="antigravity_raw",
                    source_path="agy.jsonl",
                    source_locator="byte:120",
                    thread_id="th_2",
                    turn_idx=2,
                    repo=str(repo),
                    ts=old_ts + 120.0,
                    text=f"Symptom observed: AttributeError in {target_file} caused pulse_alive false with zero ticks.",
                )

                # Query ONLY mentions AttributeError & pulse_alive (step B), CAUSAL-RAW-RAG must pull step A chronologically!
                rec = store.recall("AttributeError pulse_alive", repo=str(repo), top_k=2, causal_hops=1, reality_stamp=True)
                self.assertTrue(rec["ok"])
                self.assertTrue(rec["append_only_zero_mutation"])
                self.assertTrue(rec["chronological"])
                self.assertGreaterEqual(rec["count"], 2)
                joined = "\n".join(it["text"] for it in rec["items"])
                self.assertIn("65bbee57e75f", joined)
                self.assertIn("AttributeError", joined)
                # Chronological order: step 1 before step 2
                self.assertLessEqual(rec["items"][0]["ts"], rec["items"][-1]["ts"])
                # Live Reality Stamp detects substrate.py was modified AFTER old_ts!
                stamps = [(it.get("reality") or {}).get("stamp") for it in rec["items"]]
                self.assertIn("HISTORICAL_FILE_CHANGED", stamps)

                # Now append a fresh turn AFTER current file mtime -> CURRENT_ON_DISK!
                store.append_raw_turn(
                    source_kind="antigravity_raw",
                    source_path="agy.jsonl",
                    source_locator="byte:400",
                    thread_id="th_3",
                    turn_idx=3,
                    repo=str(repo),
                    ts=time.time() + 10.0,
                    text=f"Verified live fix on {target_file} with hasattr guard.",
                )
                rec2 = store.recall("hasattr guard", repo=str(repo), top_k=2, causal_hops=0, reality_stamp=True)
                self.assertEqual(rec2["items"][0]["reality"]["stamp"], "CURRENT_ON_DISK")
            finally:
                store.close()

    def test_02_lossless_docx_and_markdown_page_store(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            # Create a real minimal .docx ZIP archive (word/document.xml)
            docx_p = repo / "spec.docx"
            with zipfile.ZipFile(docx_p, "w") as zf:
                zf.writestr(
                    "word/document.xml",
                    '<?xml version="1.0" encoding="UTF-8"?>'
                    '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                    "<w:body><w:p><w:r><w:t>CHIMERA-MNEMOSYNE lossless spec page one exact verbatim content.</w:t></w:r></w:p></w:body>"
                    "</w:document>",
                )
            store = AkashicRawStore(ephemeral=True)
            try:
                p1 = store.read_document_page(repo, "spec.docx", page=1)
                self.assertTrue(p1["ok"], msg=p1)
                self.assertEqual(p1["page"], 1)
                self.assertIn("verbatim content", p1["text"])
                # Second call hits SHA-256 cache cleanly
                dig2 = store.digest_document_pages(repo, "spec.docx")
                self.assertTrue(dig2["cached"])
            finally:
                store.close()

    def test_03_shell_shortcircuit_swarm_replay_and_dual_channel_capture(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            mn = MnemosyneCore(ephemeral=True)
            try:
                cmd = "Get-ChildItem -Name"
                # First call: no cache hit
                pre1 = mn.shell_guard.check_pre_command(repo=str(repo), cmd=cmd, cid="worker-1")
                self.assertTrue(pre1["readonly"])
                self.assertFalse(pre1["short_circuit"])

                # PostToolUse captures huge >5KB output verbatim (Channel 1) + compact <=1.2KB view (Channel 2)
                huge_out = "\n".join(
                    [f"line_{i}: ok" for i in range(250)]
                    + ["ERROR: critical_sentinel_token_xyz failed on line 251"]
                )
                cap = mn.shell_guard.record_post_command(
                    repo=str(repo), cmd=cmd, output_text=huge_out, cid="worker-1", exit_code=0
                )
                self.assertTrue(cap["distilled"])
                self.assertLessEqual(cap["summary_bytes"], 1300)
                self.assertIn("critical_sentinel_token_xyz", cap["summary"])

                # Sibling worker-2 runs same read-only command within 30s -> RAM short-circuit HIT!
                pre2 = mn.shell_guard.check_pre_command(repo=str(repo), cmd="get-childitem   -name", cid="worker-2")
                self.assertTrue(pre2["short_circuit"])
                self.assertTrue(pre2["sibling_hit"])
                self.assertEqual(pre2["raw_ref_id"], cap["raw_ref_id"])

                # Exact verbatim drill-down recovers 100% of raw lines!
                sl = mn.raw.get_raw_slice(cap["raw_ref_id"], start_line=248, max_lines=10)
                self.assertTrue(sl["ok"])
                self.assertIn("critical_sentinel_token_xyz", sl["text"])

                # Mutating commands NEVER short-circuit
                mut = mn.shell_guard.check_pre_command(repo=str(repo), cmd="git commit -m test", cid="worker-2")
                self.assertFalse(mut["readonly"])
                self.assertFalse(mut["short_circuit"])
            finally:
                mn.close()

    def test_04_birth_primer_swarm_pacing_and_zero_token_watchdog(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            (repo / "Docs").mkdir()
            (repo / "Docs" / "manual.docx").write_bytes(b"placeholder")
            mn = MnemosyneCore(ephemeral=True)
            try:
                for i in range(4):
                    pr = mn.primer.prime(repo, cid=f"swarm-w{i}")
                self.assertTrue(pr["ok"])
                self.assertEqual(pr["active_workers"], 4)
                self.assertIn("SWARM_PACING", pr["pacing_warning"])
                self.assertIn("Docs/manual.docx", pr["docs"])
                wd = mn.primer.watchdog_snapshot()
                self.assertTrue(wd["zero_token_monitor"])
                self.assertTrue(wd["over_subscribed"])
                self.assertEqual(wd["active_workers"], 4)
            finally:
                mn.close()

    def test_05_warm_python_repl_pool_and_singleflight(self) -> None:
        pool = WarmPythonReplPool()
        try:
            r1 = pool.run("print('warm_ok', 21 * 2)")
            self.assertTrue(r1["ok"], msg=r1)
            self.assertIn("warm_ok 42", r1["stdout"])
            # Second call reuses the ALREADY-BOOTED warm worker (boots == 1!)
            r2 = pool.run("print(hashlib.sha256(b'abc').hexdigest()[:8])")
            self.assertTrue(r2["ok"])
            self.assertIn("ba7816bf", r2["stdout"])
            self.assertEqual(pool.status()["stats"]["boots"], 1)

            # Singleflight test across 3 concurrent identical Swarm requests
            barrier = threading.Barrier(3)
            outs: list[dict] = []
            lock = threading.Lock()

            def _worker() -> None:
                barrier.wait()
                res = pool.run("time.sleep(0.12); print('sf_ok')", singleflight=True)
                with lock:
                    outs.append(res)

            ts = [threading.Thread(target=_worker) for _ in range(3)]
            for t in ts:
                t.start()
            for t in ts:
                t.join(timeout=10.0)
            self.assertEqual(len(outs), 3)
            self.assertTrue(all(o["ok"] and "sf_ok" in o["stdout"] for o in outs))
            self.assertGreaterEqual(sum(1 for o in outs if o.get("singleflight_hit")), 2)
        finally:
            pool.close()

    def test_06_entropy_audit_and_nocturnal_raw_arena(self) -> None:
        ent = audit_system_entropy()
        self.assertTrue(ent["ok"])
        self.assertTrue(ent["law2_zero_choke"])
        self.assertFalse(ent["law6_auto_activated"])

        store = AkashicRawStore(ephemeral=True)
        try:
            for i in range(6):
                store.append_raw_turn(
                    source_kind="codex_raw",
                    source_path="demo.sqlite",
                    source_locator=f"rowid:{i}",
                    thread_id=f"t{i}",
                    turn_idx=i,
                    text=(
                        f"Debugged module_{i}.py fixing Error503_{i} and verifying SwarmKvPacer_{i} "
                        f"with sha256 verification and full chronological trace for turn {i} across win-desktop and svhome."
                    ),
                )
            arena = run_raw_arena_benchmark(store, thought_briefs_db=Path("__missing__.sqlite"), sample_n=5)
            self.assertTrue(arena["ok"])
            self.assertGreaterEqual(arena["queries_evaluated"], 3)
            self.assertGreaterEqual(arena["causal_raw_rag"]["evidence_hit_pct"], 80.0)
            self.assertFalse(arena["autophagy_proposal"]["auto_activated"])
        finally:
            store.close()

    def test_07_live_daemon_http_mnemosyne_nerve_rpc_and_hooks(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "ws"
            repo.mkdir()
            f1 = repo / "hello.py"
            f1.write_text("def greet():\n    return 'hi'\n", encoding="utf-8")

            cfg = OpsConfig(
                role="server",
                node_name="mnemosyne-test",
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
            daemon = ChimeraDaemon(config=cfg, ops_dir=root / "ops", auto_seed_on_empty=False).start()
            base = f"http://127.0.0.1:{daemon.http_addr[1]}"
            try:
                # 1. /v1/agent/prime & /v1/mnemosyne/status
                sc, st = _http_json(f"{base}/v1/mnemosyne/status")
                self.assertEqual(sc, 200)
                self.assertEqual(st["engine"], "chimera-mnemosyne-v1")

                sc_p, pr = _http_json(f"{base}/v1/agent/prime", method="POST", body={"repo": str(repo), "cid": "c1"})
                self.assertEqual(sc_p, 200)
                self.assertIn("hello.py", pr["tree"])

                # 2. Nerve-RPC new ops via /v1/agent/xray-batch (file_hash, win_probe, watch_until)
                sc_x, xr = _http_json(
                    f"{base}/v1/agent/xray-batch",
                    method="POST",
                    body={
                        "cwd": str(repo),
                        "ops": [
                            {"op": "file_hash", "paths": ["hello.py"]},
                            {"op": "win_probe"},
                            {"op": "watch_until", "condition": "file_exists", "path": "hello.py", "timeout_s": 1.0},
                        ],
                    },
                )
                self.assertEqual(sc_x, 200)
                self.assertTrue(xr["ok"])
                self.assertEqual(len(xr["results"][0]["hashes"]["hello.py"]["sha256"]), 64)
                self.assertTrue(xr["results"][1]["ok"])
                self.assertTrue(xr["results"][2]["matched"])

                # 3. Warm REPL via /v1/agent/warm-repl
                sc_r, rr = _http_json(f"{base}/v1/agent/warm-repl", method="POST", body={"code": "print('repl_http_ok')"})
                self.assertEqual(sc_r, 200)
                self.assertIn("repl_http_ok", rr["stdout"])

                # 4. PreToolUse + PostToolUse Shell Short-Circuit via live /v1/hook/*
                _http_json(
                    f"{base}/v1/hook/session_start",
                    method="POST",
                    body={"conversationId": "hk_a", "cwd": str(repo)},
                )
                _http_json(
                    f"{base}/v1/hook/post_tool_use",
                    method="POST",
                    body={
                        "conversationId": "hk_a",
                        "toolCall": {"name": "run_command", "arguments": {"CommandLine": "Get-ChildItem"}},
                        "output": "hello.py\n",
                    },
                )
                sc_sc, sc_res = _http_json(
                    f"{base}/v1/hook/pre_tool_use",
                    method="POST",
                    body={
                        "conversationId": "hk_b",
                        "cwd": str(repo),
                        "toolCall": {"name": "run_command", "arguments": {"CommandLine": "get-childitem"}},
                    },
                )
                self.assertEqual(sc_sc, 200)
                self.assertEqual(sc_res["decision"], "deny")
                self.assertTrue(sc_res.get("short_circuited"))
                self.assertIn("hello.py", sc_res["reason"])
            finally:
                daemon.close()


if __name__ == "__main__":
    unittest.main()
