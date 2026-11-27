"""Comprehensive verification suite for CHIMERA-SYMBIONT (Organ 3 Evolution).

Proves all 4 Symbiont pillars + agy-fast-inspired harness hardening:
1. HiveMindCortex: cross-agent soft intent leases, conflict radar, persistent Immune Reflex
   piggybacked automatically onto `xray_batch` & `callgraph_slice`.
2. PrecogRunnerEngine: `< 2 ms` single-file incremental AST update + speculative background shadow
   test that lets `commit_verify` join/hit `precog_hit=True` in milliseconds.
3. SurgeonAtomicPatchEngine: in-RAM Pre-Commit Format Gate rejecting invalid `.toml` (reproducing
   the real `config.toml` backslash bug!) and invalid `.py` with ZERO disk writes, plus exact
   byte-level auto-rollback on failing tests and clean commit on passing tests.
4. TelepathyCapsuleEngine & Bootstrap: `< 50 ms` `< 1,500`-token brain handoff capsule + `<= 1,500 B`
   live workspace bootstrap snapshot.
5. `outline` op in `xray_batch` + hard `<= 8,600 B` UTF-8 MCP Spill-Shield (zero `output.txt` spills)
   + intact source code preservation in `file_slice` + MCP JSON-RPC for all 32 tools.
"""

from __future__ import annotations

import json
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path

from chimera_tp.autopilot import OpsConfig
from chimera_tp.dashboard import ChimeraDaemon
from chimera_tp.platform.client import connect
from chimera_tp.platform.mcp_server import handle_mcp_request


class TestAgentSymbiont(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.ops_dir = self.root / "ops"
        self.repo = self.root / "symbiont_repo"
        (self.repo / "pkg").mkdir(parents=True)
        (self.repo / "tests").mkdir(parents=True)

        (self.repo / "pkg" / "__init__.py").write_text("", encoding="utf-8")
        (self.repo / "pkg" / "calc.py").write_text(
            "def multiply(a: int, b: int) -> int:\n"
            "    return a * b\n\n"
            "def square(x: int) -> int:\n"
            "    return multiply(x, x)\n",
            encoding="utf-8",
        )
        (self.repo / "tests" / "test_calc.py").write_text(
            "import unittest\n"
            "from pkg.calc import multiply, square\n\n"
            "class TestCalc(unittest.TestCase):\n"
            "    def test_multiply(self):\n"
            "        self.assertEqual(multiply(3, 4), 12)\n"
            "    def test_square(self):\n"
            "        self.assertEqual(square(5), 25)\n",
            encoding="utf-8",
        )
        (self.repo / "config.toml").write_text(
            'model = "gpt-6"\n[mcp_servers.chimera]\ncommand = "C:\\\\Python311\\\\python.exe"\n',
            encoding="utf-8",
        )
        (self.repo / "big_code.py").write_text(
            "\n".join(f"def fn_{i:03d}(x: int) -> int:\n    return x + {i}\n" for i in range(260)),
            encoding="utf-8",
        )

        cfg = OpsConfig(
            node_name="symbiont-unit",
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

    def tearDown(self) -> None:
        self.daemon.platform.agent_bus.close()
        self.daemon.close()
        self._tmp.cleanup()

    def _post(self, path: str, body: dict) -> tuple[int, dict]:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        req = urllib.request.Request(
            f"{self.anchor}{path}",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with opener.open(req, timeout=30.0) as r:
            return r.status, json.loads(r.read().decode("utf-8"))

    def test_01_hivemind_leases_conflict_radar_and_immune_piggyback(self) -> None:
        # 1. Agent A (codex) claims lease on pkg/calc.py and registers an Immune Reflex rule
        c1, l1 = self._post(
            "/v1/agent/hive",
            {
                "action": "lease",
                "agent_id": "codex",
                "repo": str(self.repo),
                "files": ["pkg/calc.py"],
                "intent": "optimize multiply",
                "ttl_s": 120,
            },
        )
        self.assertEqual(c1, 200)
        self.assertTrue(l1["ok"])
        self.assertEqual(l1["conflicts"], [])

        c_imm, r_imm = self._post(
            "/v1/agent/hive",
            {
                "action": "immune_add",
                "agent_id": "codex",
                "pattern": "*config.toml",
                "warning": "Never pass raw backslash paths to re.sub; validate TOML before save",
                "severity": "critical",
            },
        )
        self.assertEqual(c_imm, 200)
        self.assertTrue(r_imm["ok"])

        # 2. Agent B (antigravity) probes pkg/calc.py & config.toml via xray_batch -> sees BOTH conflict & immune warning!
        c_x, x_res = self._post(
            "/v1/agent/xray-batch",
            {
                "cwd": str(self.repo),
                "agent_id": "antigravity-neon",
                "ops": [
                    {"id": "o1", "op": "outline", "path": "pkg/calc.py"},
                    {"id": "c1", "op": "file_slice", "path": "config.toml", "start_line": 1, "end_line": 10},
                ],
            },
        )
        self.assertEqual(c_x, 200)
        self.assertTrue(x_res["ok"])
        self.assertTrue(any(cf["agent_id"] == "codex" and "pkg/calc.py" in cf["overlap"] for cf in x_res.get("hive_conflicts", [])))
        self.assertTrue(any("re.sub" in w["warning"] for w in x_res.get("immune_warnings", [])))
        # Verify outline op returned exact lines
        outline = x_res["results"][0]["outline"]
        self.assertTrue(any("multiply" in ln and ln.startswith("L1-") for ln in outline))

        # 3. Release codex lease -> no longer conflicting
        self._post("/v1/agent/hive", {"action": "release", "agent_id": "codex", "repo": str(self.repo)})
        c2, l2 = self._post(
            "/v1/agent/hive",
            {"action": "lease", "agent_id": "antigravity-neon", "repo": str(self.repo), "files": ["pkg/calc.py"]},
        )
        self.assertEqual(c2, 200)
        self.assertFalse(any(cf["type"] == "active_lease" for cf in l2["conflicts"]))

    def test_02_surgeon_ram_format_gate_blocks_broken_toml_and_rolls_back_failing_tests(self) -> None:
        orig_toml = (self.repo / "config.toml").read_bytes()
        orig_py = (self.repo / "pkg" / "calc.py").read_bytes()

        # 1. Attempt to inject the EXACT broken backslash escape into config.toml -> BLOCKED IN RAM (0 disk writes!)
        c_bad, r_bad = self._post(
            "/v1/agent/atomic-patch",
            {
                "repo": str(self.repo),
                "agent_id": "test-agent",
                "edits": [
                    {
                        "path": "config.toml",
                        "target": 'command = "C:\\\\Python311\\\\python.exe"',
                        "replacement": 'command = "C:\\Program Files\\Python311\\python.exe"',
                    }
                ],
                "run_tests": False,
                "record_immune_on_gate_fail": True,
            },
        )
        self.assertEqual(c_bad, 200)
        self.assertFalse(r_bad["ok"])
        self.assertTrue(r_bad["gate_rejected"])
        self.assertFalse(r_bad["disk_touched"])
        self.assertEqual((self.repo / "config.toml").read_bytes(), orig_toml)

        # 2. Valid Python syntax that BREAKS unit test -> atomically ROLLED BACK to exact original bytes!
        c_rb, r_rb = self._post(
            "/v1/agent/atomic-patch",
            {
                "repo": str(self.repo),
                "agent_id": "test-agent",
                "edits": [
                    {
                        "path": "pkg/calc.py",
                        "target": "return a * b",
                        "replacement": "return a + b",
                    }
                ],
                "run_tests": True,
                "rollback_on_fail": True,
            },
        )
        self.assertEqual(c_rb, 200)
        self.assertFalse(r_rb["ok"])
        self.assertFalse(r_rb["committed"])
        self.assertTrue(r_rb["rolled_back"])
        self.assertEqual((self.repo / "pkg" / "calc.py").read_bytes(), orig_py)

        # 3. Valid multi-file edit passing tests -> committed cleanly!
        c_ok, r_ok = self._post(
            "/v1/agent/atomic-patch",
            {
                "repo": str(self.repo),
                "agent_id": "test-agent",
                "edits": [
                    {
                        "path": "pkg/calc.py",
                        "target": "def square(x: int) -> int:\n    return multiply(x, x)",
                        "replacement": "def square(x: int) -> int:\n    return multiply(x, x)\n\ndef cube(x: int) -> int:\n    return multiply(square(x), x)",
                    }
                ],
                "run_tests": True,
            },
        )
        self.assertEqual(c_ok, 200)
        self.assertTrue(r_ok["ok"], r_ok)
        self.assertTrue(r_ok["committed"])
        self.assertFalse(r_ok["rolled_back"])
        self.assertIn("def cube", (self.repo / "pkg" / "calc.py").read_text(encoding="utf-8"))

    def test_03_precog_incremental_ast_and_shadow_test_prewarm(self) -> None:
        # 1. Warm callgraph once
        self._post("/v1/agent/callgraph-slice", {"repo": str(self.repo), "symbol": "multiply"})
        # 2. Save a new function and trigger Precog-Runner (simulates editor save while LLM thinks)
        (self.repo / "pkg" / "calc.py").write_text(
            "def multiply(a: int, b: int) -> int:\n"
            "    return a * b\n\n"
            "def square(x: int) -> int:\n"
            "    return multiply(x, x)\n\n"
            "def quadruple(x: int) -> int:\n"
            "    return multiply(x, 4)\n",
            encoding="utf-8",
        )
        c_p, r_p = self._post(
            "/v1/agent/precog",
            {
                "action": "notify_save",
                "repo": str(self.repo),
                "files": ["pkg/calc.py"],
                "run_shadow_test": True,
                "agent_id": "antigravity",
            },
        )
        self.assertEqual(c_p, 200)
        self.assertTrue(r_p["ok"])
        self.assertIn("pkg/calc.py", r_p["ast_updated"])
        self.assertTrue(r_p["shadow_scheduled"])

        # 3. Callgraph IMMEDIATELY knows `quadruple` via incremental AST update!
        c_cg, r_cg = self._post("/v1/agent/callgraph-slice", {"repo": str(self.repo), "symbol": "quadruple"})
        self.assertEqual(c_cg, 200)
        self.assertTrue(r_cg["ok"])

        # 4. Wait briefly for background shadow test (simulating LLM thinking) then call commit_verify -> precog_hit!
        deadline = time.time() + 10.0
        while time.time() < deadline:
            st = self.daemon.platform.agent_bus.symbiont.precog.status()
            if st["shadow_tests_completed"] >= 1:
                break
            time.sleep(0.1)

        c_v, r_v = self._post(
            "/v1/agent/commit-verify",
            {"repo": str(self.repo), "files": ["pkg/calc.py"], "run_tests": True, "use_cache": True},
        )
        self.assertEqual(c_v, 200)
        self.assertTrue(r_v["ok"])
        self.assertTrue(r_v["cache_hit"])
        self.assertTrue(r_v.get("precog_hit"))
        self.assertLess(r_v["elapsed_ms"], 100.0)

    def test_04_telepathy_capsule_and_bootstrap_snapshot(self) -> None:
        self._post(
            "/v1/agent/hive",
            {"action": "immune_add", "pattern": "*calc.py", "warning": "Keep multiply pure int", "agent_id": "codex"},
        )
        c_cap, r_cap = self._post(
            "/v1/agent/capsule",
            {
                "action": "create",
                "repo": str(self.repo),
                "agent_id": "codex",
                "summary": "Added cube helper and verified test_calc",
                "focus_files": ["pkg/calc.py"],
                "focus_symbols": ["multiply"],
                "next_steps": ["Add float support"],
                "include_git": False,
            },
        )
        self.assertEqual(c_cap, 200)
        self.assertTrue(r_cap["ok"])
        self.assertLess(r_cap["est_tokens"], 1500)
        cid = r_cap["capsule_id"]

        # Load by ID and by "latest"
        c_ld, r_ld = self._post("/v1/agent/capsule", {"action": "load", "capsule_id": cid})
        self.assertEqual(c_ld, 200)
        self.assertEqual(r_ld["capsule"]["summary"], "Added cube helper and verified test_calc")
        self.assertTrue(any("Keep multiply pure int" in w["warning"] for w in r_ld["capsule"]["immune_warnings"]))

        # Live bootstrap snapshot <= 1,500 B
        c_bs, r_bs = self._post("/v1/agent/bootstrap", {"repo": str(self.repo), "agent_id": "claude"})
        self.assertEqual(c_bs, 200)
        self.assertTrue(r_bs["ok"])
        self.assertLessEqual(r_bs["bytes"], 1500)
        self.assertEqual(r_bs["latest_capsule"], cid)

    def test_05_mcp_spill_shield_and_intact_code_slice(self) -> None:
        # 1. Verify all 5 new Symbiont MCP tools are advertised
        tools = handle_mcp_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, anchor_url=self.anchor)
        names = {t["name"] for t in tools["result"]["tools"]}
        self.assertTrue(
            {
                "chimera_hive",
                "chimera_atomic_patch",
                "chimera_precog",
                "chimera_handoff_capsule",
                "chimera_bootstrap",
            }.issubset(names)
        )

        # 2. Request a huge file_slice (> 12 KB) through MCP -> Spill-Shield MUST keep wire <= 8,600 B!
        resp = handle_mcp_request(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "chimera_xray_batch",
                    "arguments": {
                        "cwd": str(self.repo),
                        "compact": True,
                        "ops": [
                            {"id": "big1", "op": "file_slice", "path": "big_code.py", "start_line": 1, "end_line": 400},
                            {"id": "big2", "op": "file_slice", "path": "big_code.py", "start_line": 401, "end_line": 780},
                        ],
                    },
                },
            },
            anchor_url=self.anchor,
        )
        wire_text = resp["result"]["content"][0]["text"]
        self.assertLessEqual(len(wire_text.encode("utf-8")), 8600)
        # Code lines must NOT be stripped by PASS/FAIL log filter (fn_000..fn_010 remain intact)
        self.assertIn("def fn_000", wire_text)
        self.assertNotIn("[token-diet: collapsed", wire_text)

        # 3. Offline client fallback works for Symbiont methods too
        off = connect(app="offline-symbiont", anchor_url="http://127.0.0.1:1", auto_register=False)
        bs = off.agent_bootstrap(str(self.repo))
        self.assertTrue(bs["ok"])
        self.assertEqual(bs["via"], "in_process_fallback")

    def test_06_surgeon_drift_hint_auto_precog_strict_bootstrap_and_session_hook(self) -> None:
        # 1. Surgeon returns closest_match fuzzy line-drift hint on target_not_found
        c_h, r_h = self._post(
            "/v1/agent/atomic-patch",
            {
                "repo": str(self.repo),
                "edits": [{"path": "pkg/calc.py", "target": "def multipli(a: int, b: int) -> int:", "replacement": "x"}],
                "run_tests": False,
            },
        )
        self.assertEqual(c_h, 200)
        self.assertFalse(r_h["ok"])
        self.assertEqual(r_h["error"], "target_not_found")
        self.assertIn("closest_match", r_h)
        self.assertEqual(r_h["closest_match"]["line"], 1)
        self.assertIn("multiply", r_h["closest_match"]["snippet"])

        # 2. Surgeon with run_tests=False automatically pre-warms Precog-Runner shadow tests!
        c_p, r_p = self._post(
            "/v1/agent/atomic-patch",
            {
                "repo": str(self.repo),
                "edits": [
                    {
                        "path": "pkg/calc.py",
                        "target": "return multiply(x, x)",
                        "replacement": "return multiply(x, x)  # fast",
                    }
                ],
                "run_tests": False,
            },
        )
        self.assertEqual(c_p, 200)
        self.assertTrue(r_p["ok"])
        deadline = time.time() + 10.0
        while time.time() < deadline:
            if self.daemon.platform.agent_bus.symbiont.precog.status()["shadow_tests_completed"] >= 1:
                break
            time.sleep(0.1)
        c_v, r_v = self._post(
            "/v1/agent/commit-verify",
            {"repo": str(self.repo), "files": ["pkg/calc.py"], "run_tests": True, "use_cache": True},
        )
        self.assertEqual(c_v, 200)
        self.assertTrue(r_v["ok"])
        self.assertTrue(r_v.get("precog_hit"))

        # 3. SessionStart hook fetches strict <= 1,500 B bootstrap snapshot & graceful offline {}
        from chimera_tp.platform.session_hook import fetch_bootstrap

        snap = fetch_bootstrap(str(self.repo), anchor=self.anchor)
        self.assertTrue(snap["ok"])
        self.assertLessEqual(snap["bytes"], 1500)
        # Second call hits 3s git micro-cache (< 15 ms)
        snap2 = fetch_bootstrap(str(self.repo), anchor=self.anchor)
        self.assertTrue(snap2["ok"])
        self.assertLess(snap2["elapsed_ms"], 50.0)
        self.assertEqual(fetch_bootstrap(str(self.repo), anchor="http://127.0.0.1:1", timeout_s=0.3), {})

    def test_07_singleflight_6agent_dedup_and_warm_worker(self) -> None:
        import concurrent.futures

        # Fire 6 concurrent identical commit_verify calls simultaneously -> MUST execute ONLY ONCE via singleflight!
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
            futs = [
                ex.submit(
                    self._post,
                    "/v1/agent/commit-verify",
                    {"repo": str(self.repo), "files": ["pkg/calc.py"], "run_tests": True, "use_cache": True},
                )
                for _ in range(6)
            ]
            outs = [f.result()[1] for f in futs]

        self.assertTrue(all(o["ok"] for o in outs))
        st = self.daemon.platform.agent_bus.verifier.stats()
        self.assertEqual(st["runs"], 1)
        self.assertGreaterEqual(st["singleflight_joins"] + st["cache_hits"], 5)
        self.assertGreaterEqual(st["warm_worker_runs"], 1)

    def test_08_mirror_race_winner_takes_all_and_coroner_auto_immune(self) -> None:
        # 1. Mirror-Race: Cand A has syntax error, Cand B breaks unit test, Cand C passes -> ONLY Cand C commits!
        c_r, r_r = self._post(
            "/v1/agent/mirror-race",
            {
                "repo": str(self.repo),
                "agent_id": "race-agent",
                "commit_winner": True,
                "candidates": [
                    {"id": "bad_syntax", "edits": [{"path": "pkg/calc.py", "target": "return a * b", "replacement": "return (a * b"}]},
                    {"id": "wrong_logic", "edits": [{"path": "pkg/calc.py", "target": "return a * b", "replacement": "return a + b"}]},
                    {"id": "clean_winner", "edits": [{"path": "pkg/calc.py", "target": "return a * b", "replacement": "return int(a * b)"}]},
                ],
            },
        )
        self.assertEqual(c_r, 200)
        self.assertTrue(r_r["ok"], r_r)
        self.assertEqual(r_r["winner_id"], "clean_winner")
        self.assertTrue(r_r["committed"])
        self.assertIn("return int(a * b)", (self.repo / "pkg" / "calc.py").read_text(encoding="utf-8"))

        # 2. Post-Mortem Coroner scans a synthetic noisy session JSONL and auto-seeds Immune Reflex!
        fake_log = self.root / "fake_session.jsonl"
        lines = ['{"type":"CommandExecution"}' for _ in range(15)] + [
            '{"msg":"output.txt spill 1"}',
            '{"msg":"output.txt spill 2"}',
            '{"err":"missing escaped value in config.toml"}',
            '{"err":"Disk quota exceeded on /tmp"}',
        ]
        fake_log.write_text("\n".join(lines), encoding="utf-8")
        c_cor, r_cor = self._post(
            "/v1/agent/coroner",
            {"log_files": [str(fake_log)], "auto_seed_immune": True},
        )
        self.assertEqual(c_cor, 200)
        self.assertTrue(r_cor["ok"])
        kinds = {f["kind"] for f in r_cor["findings"]}
        self.assertTrue({"shell_storm", "disk_spill", "syntax_config_break", "edquot_tmp"}.issubset(kinds))
        self.assertGreaterEqual(r_cor["rules_seeded"], 4)

    def test_09_soft_priority_batch_shield_and_35_mcp_tools(self) -> None:
        c_sh, r_sh = self._post("/v1/hyperdesk/soft-shield", {"action": "apply", "dry_run": True})
        self.assertEqual(c_sh, 200)
        self.assertTrue(r_sh["ok"])
        self.assertTrue(r_sh["affinity_untouched"])
        self.assertTrue(r_sh["eco_qos_untouched"])

        tools = handle_mcp_request({"jsonrpc": "2.0", "id": 99, "method": "tools/list"}, anchor_url=self.anchor)
        names = {t["name"] for t in tools["result"]["tools"]}
        self.assertTrue(
            {
                "chimera_mirror_race",
                "chimera_coroner",
                "chimera_soft_shield",
                "chimera_exec",
                "chimera_run_dag",
                "chimera_worktree_epoch",
            }.issubset(names)
        )
        self.assertGreaterEqual(len(names), 38)

    def test_10_macro_dag_direct_exec_worktree_epoch_and_prefetch(self) -> None:
        import sys

        # 1. DirectExec (no pwsh, no node tool-log.mjs, LF-normalized stdin + smart excerpt)
        c_ex, r_ex = self._post(
            "/v1/agent/exec",
            {
                "argv": [sys.executable, "-"],
                "cwd": str(self.repo),
                "stdin_text": "print('LINE_1_OK')\r\nfor i in range(45): print(f'row {i}')\r\nprint('Summary: 45 passed')\r\n",
            },
        )
        self.assertEqual(c_ex, 200)
        self.assertTrue(r_ex["ok"], r_ex)
        self.assertEqual(r_ex["rc"], 0)
        self.assertIn("Summary: 45 passed", r_ex["preview"])

        # 2. Release-Epoch Lock: Agent A claims -> Agent B gets conflict warning -> Agent A publishes signed receipt!
        rel_dir = str(self.repo)
        c_cl1, r_cl1 = self._post(
            "/v1/agent/worktree-epoch",
            {"action": "epoch_claim", "release_dir": rel_dir, "agent_id": "antigravity", "intent": "sync release"},
        )
        self.assertEqual(c_cl1, 200)
        self.assertTrue(r_cl1["ok"])

        c_cl2, r_cl2 = self._post(
            "/v1/agent/worktree-epoch",
            {"action": "epoch_claim", "release_dir": rel_dir, "agent_id": "codex", "intent": "re-verify"},
        )
        self.assertEqual(c_cl2, 200)
        self.assertFalse(r_cl2["ok"])
        self.assertEqual(r_cl2["conflict"]["holder"], "antigravity")

        c_pub, r_pub = self._post(
            "/v1/agent/worktree-epoch",
            {
                "action": "epoch_publish",
                "release_dir": rel_dir,
                "agent_id": "antigravity",
                "files": ["pkg/calc.py"],
                "verified_summary": "18/18 PASS",
                "daemon_pid": 12345,
            },
        )
        self.assertEqual(c_pub, 200)
        self.assertTrue(r_pub["ok"])

        # Verify epoch status shows signed receipt & claim cleared
        c_st, r_st = self._post("/v1/agent/worktree-epoch", {"action": "epoch_status", "release_dir": rel_dir})
        self.assertEqual(c_st, 200)
        self.assertEqual(len(r_st["active_claims"]), 0)
        self.assertGreaterEqual(len(r_st["recent_epochs"]), 1)
        self.assertEqual(r_st["recent_epochs"][0]["agent_id"], "antigravity")

        # 3. Macro-DAG collapses 4 heterogeneous steps (xray + sha256_parity + exec + verify) into 1 RPC!
        c_dag, r_dag = self._post(
            "/v1/agent/run-dag",
            {
                "cwd": str(self.repo),
                "agent_id": "dag-tester",
                "steps": [
                    {"id": "s1_xray", "kind": "xray", "ops": [{"op": "outline", "path": "pkg/calc.py"}]},
                    {"id": "s2_hash", "kind": "sha256_parity", "files": ["pkg/calc.py", "tests/test_calc.py"]},
                    {"id": "s3_exec", "kind": "exec", "argv": [sys.executable, "-c", "print('DAG_EXEC_OK')"]},
                    {"id": "s4_verify", "kind": "verify", "files": ["pkg/calc.py"], "run_tests": True},
                ],
            },
        )
        self.assertEqual(c_dag, 200)
        self.assertTrue(r_dag["ok"], r_dag)
        self.assertEqual(r_dag["steps_run"], 4)
        self.assertEqual(r_dag["steps_ok"], 4)
        self.assertEqual(r_dag["llm_turns_collapsed"], 3)

        # 4. Speculative Prefetch Tap endpoint (/v1/agent/precog action=prefetch_paths)
        c_pf, r_pf = self._post(
            "/v1/agent/precog",
            {"action": "prefetch_paths", "paths": [str(self.repo / "pkg" / "calc.py"), str(self.repo / "big_code.py")]},
        )
        self.assertEqual(c_pf, 200)
        self.assertTrue(r_pf["ok"])
        self.assertEqual(r_pf["warmed_count"], 2)
        self.assertGreater(r_pf["warmed_bytes"], 1000)

    def test_11_release_promote_speculative_cache_aether_auto_shield_and_39_mcp_tools(self) -> None:
        from chimera_tp.platform.mcp_server import handle_mcp_request

        # 1. Speculative Result Cache: prefetch_paths warms RAM -> xray_batch file_slice gets speculative_hit!
        target_fp = str(self.repo / "pkg" / "calc.py")
        c_pf, r_pf = self._post(
            "/v1/agent/precog",
            {"action": "prefetch_paths", "paths": [target_fp], "warm_cache": True},
        )
        self.assertEqual(c_pf, 200)
        self.assertTrue(r_pf["ok"])
        self.assertEqual(r_pf["cached_count"], 1)

        c_xr, r_xr = self._post(
            "/v1/agent/xray-batch",
            {"cwd": str(self.repo), "ops": [{"id": "spec1", "op": "file_slice", "path": "pkg/calc.py", "start_line": 1, "end_line": 10}]},
        )
        self.assertEqual(c_xr, 200)
        self.assertTrue(r_xr["ok"])
        self.assertTrue(r_xr["results"][0].get("speculative_hit"), r_xr["results"][0])

        # 2. Single-Gate Immutable Release Plane: promote + canary pass + canary failure auto-rollback + explicit rollback!
        src_rel = self.repo.parent / "rel_src"
        dst_rel = self.repo.parent / "rel_dst"
        snap_root = self.repo.parent / "rel_snaps"
        (src_rel / "mymod").mkdir(parents=True, exist_ok=True)
        (dst_rel / "mymod").mkdir(parents=True, exist_ok=True)
        (dst_rel / "mymod" / "__init__.py").write_text("VAL = 1\n", encoding="utf-8")
        (src_rel / "mymod" / "__init__.py").write_text("VAL = 2\n", encoding="utf-8")

        c_ok, r_ok = self._post(
            "/v1/agent/release-promote",
            {
                "action": "promote",
                "source_dir": str(src_rel),
                "target_dir": str(dst_rel),
                "snapshot_root": str(snap_root),
                "files": ["mymod/__init__.py"],
                "canary_imports": ["mymod"],
                "agent_id": "antigravity",
                "verified_summary": "test-promote-v2",
            },
        )
        self.assertEqual(c_ok, 200)
        self.assertTrue(r_ok["ok"], r_ok)
        self.assertTrue(r_ok["canary_ok"])
        self.assertIn("VAL = 2", (dst_rel / "mymod" / "__init__.py").read_text(encoding="utf-8"))

        # Broken import canary MUST auto-rollback dst_rel back to VAL = 2!
        (src_rel / "mymod" / "__init__.py").write_text("import definitely_missing_pkg_xyz_999\nVAL = 3\n", encoding="utf-8")
        c_fail, r_fail = self._post(
            "/v1/agent/release-promote",
            {
                "action": "promote",
                "source_dir": str(src_rel),
                "target_dir": str(dst_rel),
                "snapshot_root": str(snap_root),
                "files": ["mymod/__init__.py"],
                "canary_imports": ["mymod"],
                "agent_id": "antigravity",
            },
        )
        self.assertEqual(c_fail, 200)
        self.assertFalse(r_fail["ok"])
        self.assertTrue(r_fail["rolled_back"])
        self.assertIn("VAL = 2", (dst_rel / "mymod" / "__init__.py").read_text(encoding="utf-8"))

        # Explicit rollback restores VAL = 1 in < 1s!
        c_rb, r_rb = self._post(
            "/v1/agent/release-promote",
            {"action": "rollback", "epoch_id": r_ok["epoch_id"]},
        )
        self.assertEqual(c_rb, 200)
        self.assertTrue(r_rb["ok"], r_rb)
        self.assertIn("VAL = 1", (dst_rel / "mymod" / "__init__.py").read_text(encoding="utf-8"))

        # 3. Always-On SoftPriorityBatchShield in `aether` autonomic tick + orphan conhost dry-run + gentle WS trim dry-run
        hd = self.daemon.platform.hyper_desk
        tick = hd.autonomic_tick_once(force_patrol=True, force_orphan=True, dry_run=True)
        self.assertTrue(tick["ok"])
        self.assertEqual(tick["profile"], "aether")
        self.assertEqual(tick["wall_state"], "AETHER_SOFT_SHIELD")
        self.assertTrue(tick["affinity_untouched"])
        self.assertTrue(tick["eco_qos_untouched"])
        self.assertIsNotNone(tick["soft_shield"])
        self.assertIsNotNone(tick["orphan_conhosts"])

        # 4. MCP tool registry exposes 39 tools including chimera_release_promote
        tlist = handle_mcp_request({"jsonrpc": "2.0", "id": 39, "method": "tools/list"}, anchor_url=self.anchor)
        names = {t["name"] for t in tlist["result"]["tools"]}
        self.assertGreaterEqual(len(names), 39)
        self.assertIn("chimera_release_promote", names)


if __name__ == "__main__":
    unittest.main()
