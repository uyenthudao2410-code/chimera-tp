"""End-to-end verification suite for CHIMERA-ONE Organ 3 Zero-Spawn Agent Hyper-Bus."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

from chimera_tp.autopilot import OpsConfig
from chimera_tp.dashboard import ChimeraDaemon
from chimera_tp.platform.agent_probe import AgentHyperBus, TokenDietCompactor
from chimera_tp.platform.client import connect
from chimera_tp.platform.mcp_server import handle_mcp_request


class TestAgentHyperBus(unittest.TestCase):
    def test_sparse_file_slices_match_splitlines_and_reject_a_replaced_file(self):
        from chimera_tp.platform.agent_probe import _SparseTextLines

        # Cross 64 KiB boundaries inside CRLF and both multibyte Unicode separators.
        data = bytearray()
        for separator in (b"\r\n", b"\xc2\x85", b"\xe2\x80\xa8", b"\xe2\x80\xa9"):
            data.extend(b"x" * (65535 - len(data) % 65536))
            data.extend(separator + b"a\r\vb\x1f\xc2\n")
        data.extend(b"line\r\n" * 720)
        data.extend(b"\x1c\x1d\x1e\x0b\x0cfinal invalid byte \xff")
        path = self.repo / "build.log"
        path.write_bytes(data)
        reference = data.decode("utf-8", errors="replace").splitlines()
        index = _SparseTextLines(path)
        self.assertEqual(index.count, len(reference))
        self.assertEqual(index.digest, hashlib.blake2s(data, digest_size=12).hexdigest())
        for start, end in [(1, 2), (4, 30), (255, 257), (511, 513), (len(reference) - 8, len(reference))]:
            self.assertEqual(index.read_range(start, end), reference[start - 1:end])
        self.assertEqual(index.read_range(2000, 1999), [])
        replacement = self.repo / "replacement.log"
        replacement.write_bytes(b"new file")
        replacement.replace(path)
        with self.assertRaisesRegex(OSError, "file_changed_during_read"):
            index.read_range(1, 2)

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.ops_dir = self.root / "ops"
        self.repo = self.root / "demo_repo"
        (self.repo / "src").mkdir(parents=True)
        (self.repo / "tests").mkdir(parents=True)

        # Sample JS multi-file callgraph (reproducing Screenshot #1 pattern)
        (self.repo / "src" / "catalog.js").write_text(
            "export function normalizeModelId(raw) {\n"
            "  return String(raw || '').trim().toLowerCase();\n"
            "}\n",
            encoding="utf-8",
        )
        (self.repo / "src" / "entitlement.js").write_text(
            "import { normalizeModelId } from './catalog.js';\n"
            "export function resolveDesktopBareModelAlias(alias, pool) {\n"
            "  const norm = normalizeModelId(alias);\n"
            "  return pool[norm] || norm;\n"
            "}\n",
            encoding="utf-8",
        )
        (self.repo / "src" / "server.js").write_text(
            "import { resolveDesktopBareModelAlias } from './entitlement.js';\n"
            "export function handleModelRoute(req, pool) {\n"
            "  return resolveDesktopBareModelAlias(req.model, pool);\n"
            "}\n",
            encoding="utf-8",
        )
        (self.repo / "tests" / "test_entitlement.js").write_text(
            "function test_resolve_alias() {\n"
            "  return resolveDesktopBareModelAlias('gemini-4-neon', {});\n"
            "}\n",
            encoding="utf-8",
        )

        # Sample Python package + impacted & unrelated tests
        (self.repo / "src" / "__init__.py").write_text("", encoding="utf-8")
        (self.repo / "src" / "math_core.py").write_text(
            "def add_scaled(a: int, b: int, factor: int = 2) -> int:\n"
            "    return (a + b) * factor\n\n"
            "def compute_total(xs: list[int]) -> int:\n"
            "    total = 0\n"
            "    for v in xs:\n"
            "        total = add_scaled(total, v, factor=1)\n"
            "    return total\n",
            encoding="utf-8",
        )
        (self.repo / "tests" / "test_math_core.py").write_text(
            "import unittest\n"
            "from src.math_core import add_scaled, compute_total\n\n"
            "class TestMathCore(unittest.TestCase):\n"
            "    def test_add_scaled(self):\n"
            "        self.assertEqual(add_scaled(2, 3, 4), 20)\n"
            "    def test_compute_total(self):\n"
            "        self.assertEqual(compute_total([1, 2, 3]), 6)\n",
            encoding="utf-8",
        )
        (self.repo / "tests" / "test_unrelated.py").write_text(
            "import unittest\n"
            "class TestUnrelated(unittest.TestCase):\n"
            "    def test_noop(self):\n"
            "        self.assertTrue(True)\n",
            encoding="utf-8",
        )

        # Sample JSON config & SQLite DB
        (self.repo / "config.json").write_text(
            json.dumps({"models": [{"id": "gemini-4-neon"}, {"id": "gpt-5.4"}], "quota": {"active": 2}}),
            encoding="utf-8",
        )
        db_path = self.repo / "state.db"
        con = sqlite3.connect(str(db_path))
        con.execute("CREATE TABLE accounts (id TEXT, status TEXT)")
        con.execute("INSERT INTO accounts VALUES ('acc-1', 'active'), ('acc-2', 'cooldown')")
        con.commit()
        con.close()

        cfg = OpsConfig(
            node_name="agent-bus-unit",
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
        with opener.open(req, timeout=25.0) as r:
            return r.status, json.loads(r.read().decode("utf-8"))

    def test_01_token_diet_compactor_preserves_failures_and_raw_ref(self) -> None:
        comp = TokenDietCompactor()
        verbose_lines = [f"test_case_{i:03d} (tests.test_suite.Suite) ... ok" for i in range(140)]
        verbose_lines.extend([
            "======================================================================",
            "FAIL: test_critical_invariant (tests.test_suite.Suite)",
            "Traceback (most recent call last):",
            "  File 'demo.py', line 42, in test_critical_invariant",
            "AssertionError: 99 != 100",
            "Ran 141 tests in 1.23s",
            "FAILED (failures=1)",
        ])
        raw = "\n".join(verbose_lines)
        res = comp.compact(raw, max_lines=35, max_chars=1800)
        self.assertTrue(res["compacted"])
        self.assertGreaterEqual(res["saved_pct"], 55.0)
        self.assertIn("AssertionError: 99 != 100", res["text"])
        self.assertIn("FAILED (failures=1)", res["text"])
        self.assertIsNotNone(res["ref_id"])

        restored = comp.get_raw(res["ref_id"], start_line=1, max_lines=5)
        self.assertTrue(restored["ok"])
        self.assertIn("test_case_000", restored["text"])

    def test_02_xray_batch_zero_powershell_mixed_ops(self) -> None:
        ops = [
            {"id": "s1", "op": "file_slice", "path": "src/math_core.py", "skip": 0, "first": 4},
            {"id": "s2", "op": "file_slice", "path": "src/math_core.py", "ranges": [[1, 2], [4, 7]]},
            {"id": "rg1", "op": "regex_search", "path": "src", "pattern": "resolveDesktopBareModelAlias"},
            {"id": "ls1", "op": "list_files", "path": ".", "glob": "*.js"},
            {"id": "js1", "op": "json_query", "path": "config.json", "jpath": "models[].id"},
            {"id": "http1", "op": "http_get", "url": f"{self.anchor}/api/pulse", "jpath": "ok"},
            {"id": "sql1", "op": "sqlite_ro", "db": "state.db", "sql": "SELECT id, status FROM accounts ORDER BY id"},
            {"id": "sql_bad", "op": "sqlite_ro", "db": "state.db", "sql": "DELETE FROM accounts"},
        ]
        # Prove ZERO subprocess/PowerShell spawns occur for all 8 ops!
        with patch("subprocess.run", side_effect=AssertionError("Must never spawn subprocess for read-only xray ops!")):
            code, out = self._post("/v1/agent/xray-batch", {"ops": ops, "cwd": str(self.repo)})

        self.assertEqual(code, 200)
        self.assertEqual(out["powershell_spawns"], 0)
        self.assertEqual(out["ops_count"], 8)
        self.assertEqual(out["ok_count"], 7)  # 7 valid + 1 safely rejected write SQL
        by_id = {r["id"]: r for r in out["results"]}
        self.assertIn("def add_scaled", by_id["s1"]["text"])
        self.assertEqual(len(by_id["s2"]["ranges"]), 2)
        self.assertGreaterEqual(by_id["rg1"]["count"], 2)
        self.assertEqual(by_id["js1"]["value"], ["gemini-4-neon", "gpt-5.4"])
        self.assertTrue(by_id["http1"]["json"])
        self.assertEqual(len(by_id["sql1"]["rows"]), 2)
        self.assertFalse(by_id["sql_bad"]["ok"])
        self.assertEqual(by_id["sql_bad"]["error"], "readonly_sql_only")

    def test_completed_batches_supply_scoped_evidence_without_read_side_effects(self):
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

        def evidence():
            with opener.open(f"{self.anchor}/v1/truth-matrix", timeout=5) as response:
                return json.load(response)["capabilities"]["agent_hyper_bus"]

        before = evidence()
        read = {"op": "file_slice", "path": "src/math_core.py", "first": 1}
        request = {"ops": [read], "cwd": str(self.repo)}
        code, result = self._post("/v1/agent/xray-batch", request)
        self.assertEqual((code, result["ok_count"]), (200, 1))
        passed = evidence()
        self.assertEqual(passed["basis"], "fixture_traffic")
        self.assertEqual(passed["sample_count"], before["sample_count"] + 1)
        self.assertEqual(passed["execution_node"], "agent-bus-unit")
        self.assertEqual(passed["metrics"], {
            "operation": "agent.xray_batch", "successful": True, "operations": 1,
        })
        self.assertEqual(evidence(), passed)

        request["ops"] = [read, {**read, "path": "missing.py"}]
        _, partial = self._post("/v1/agent/xray-batch", request)
        self.assertEqual((partial["ok"], partial["ok_count"]), (False, 1))
        failed = evidence()
        self.assertEqual(failed["basis"], "unverified")
        self.assertEqual(failed["sample_count"], passed["sample_count"] + 1)
        self.assertEqual(failed["last_verified_at"], passed["last_verified_at"])
        self.assertEqual(failed["metrics"], {
            "operation": "agent.xray_batch", "successful": False, "operations": 2,
        })
        with self.assertRaises(urllib.error.HTTPError) as rejection:
            self._post("/v1/agent/xray-batch", {"ops": []})
        self.assertEqual(rejection.exception.code, 400)
        rejection.exception.close()
        self.assertEqual(evidence(), failed)

    def test_03_callgraph_telepathy_js_and_python_2hop(self) -> None:
        code_js, js_res = self._post(
            "/v1/agent/callgraph-slice",
            {"repo": str(self.repo), "symbol": "resolveDesktopBareModelAlias", "depth": 2, "max_chars": 4000},
        )
        self.assertEqual(code_js, 200)
        self.assertTrue(js_res["ok"])
        self.assertTrue(any(d["file"].endswith("entitlement.js") for d in js_res["definitions"]))
        self.assertTrue(any(c["qualname"] == "normalizeModelId" for c in js_res["callees"]))
        self.assertTrue(any(c["qualname"] == "handleModelRoute" for c in js_res["callers"]))
        self.assertTrue(any(t["file"].endswith("test_entitlement.js") for t in js_res["related_tests"]))
        self.assertLessEqual(js_res["chars_used"], 4000)

        code_py, py_res = self._post(
            "/v1/agent/callgraph-slice",
            {"repo": str(self.repo), "symbol": "add_scaled", "depth": 2},
        )
        self.assertEqual(code_py, 200)
        self.assertTrue(any(c["qualname"] == "compute_total" for c in py_res["callers"]))
        self.assertTrue(any("test_math_core.py" in t["file"] for t in py_res["related_tests"]))

    def test_04_atomic_commit_verify_impacted_tests_and_blake2s_cache(self) -> None:
        request = {"repo": str(self.repo), "files": ["src/math_core.py"], "run_tests": True}
        if sys.platform.startswith("linux"):
            with self.assertRaises(urllib.error.HTTPError) as error:
                self._post("/v1/agent/commit-verify", request)
            with error.exception as response:
                self.assertEqual(response.code, 409)
                result = json.load(response)
            self.assertEqual(result["error"], "guarded_build_required")
            self.assertEqual(result["state"], "deferred")
            self.assertEqual(result["queue"], {"stored": False})
            return

        code1, r1 = self._post("/v1/agent/commit-verify", request)
        self.assertEqual(code1, 200)
        self.assertTrue(r1["ok"], r1)
        self.assertFalse(r1["cache_hit"])
        self.assertEqual(r1["powershell_spawns"], 0)
        self.assertEqual(r1["tests"]["tests"], ["tests/test_math_core.py"])

        # Second identical call hits BLAKE2s memoization cache in milliseconds!
        code2, r2 = self._post(
            "/v1/agent/commit-verify",
            {"repo": str(self.repo), "files": ["src/math_core.py"], "run_tests": True},
        )
        self.assertEqual(code2, 200)
        self.assertTrue(r2["ok"])
        self.assertTrue(r2["cache_hit"])
        self.assertEqual(r2["fingerprint"], r1["fingerprint"])

        # Breaking syntax busts fingerprint and reports syntax error without running tests
        (self.repo / "src" / "math_core.py").write_text("def broken(:\n    pass\n", encoding="utf-8")
        code3, r3 = self._post(
            "/v1/agent/commit-verify",
            {"repo": str(self.repo), "files": ["src/math_core.py"], "run_tests": True},
        )
        self.assertEqual(code3, 200)
        self.assertFalse(r3["ok"])
        self.assertFalse(r3["cache_hit"])
        self.assertEqual(len(r3["syntax_errors"]), 1)

    def test_05_mcp_jsonrpc_and_offline_fallback(self) -> None:
        # 1. Verify all 3 MCP tools are advertised
        tools = handle_mcp_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, anchor_url=self.anchor)
        names = {t["name"] for t in tools["result"]["tools"]}
        self.assertTrue({"chimera_xray_batch", "chimera_callgraph_slice", "chimera_commit_verify"}.issubset(names))

        # 2. Live MCP call to chimera_xray_batch
        resp = handle_mcp_request(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "chimera_xray_batch",
                    "arguments": {
                        "cwd": str(self.repo),
                        "ops": [{"id": "j", "op": "json_query", "path": "config.json", "jpath": "quota.active"}],
                    },
                },
            },
            anchor_url=self.anchor,
        )
        payload = json.loads(resp["result"]["content"][0]["text"])
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["results"][0]["value"], 2)

        # 3. Offline client fallback (zero lock-in when daemon unreachable)
        offline_cli = connect(app="offline-test", anchor_url="http://127.0.0.1:1", auto_register=False)
        fb = offline_cli.callgraph_slice(str(self.repo), "compute_total", depth=1)
        self.assertTrue(fb["ok"])
        self.assertEqual(fb["via"], "in_process_fallback")

        # 4. Stats endpoint live
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f"{self.anchor}/v1/agent/probe-stats", timeout=5.0) as r:
            st = json.loads(r.read().decode("utf-8"))
        self.assertTrue(st["ok"])
        self.assertGreaterEqual(st["probe"]["batches_run"], 1)

    def test_06_codex_real_world_ergonomics_coalescing_and_compact_wire(self) -> None:
        # 1. Verify list_files honors `pattern` alias (regression from Codex live run!)
        # 2. Verify regex_search honors `limit` alias
        # 3. Verify json_query & http_get support multi-`jpaths` AND coalesce duplicate reads in one batch
        ops = [
            {"id": "ls_pat", "op": "list_files", "path": "src", "pattern": "*entitlement*"},
            {"id": "rg_lim", "op": "regex_search", "path": "src", "pattern": "export|def", "limit": 2},
            {"id": "s_a", "op": "file_slice", "path": "src/math_core.py", "start_line": 1, "end_line": 2},
            {"id": "s_b", "op": "file_slice", "path": "src/math_core.py", "start_line": 4, "end_line": 7},
            {"id": "jq_multi", "op": "json_query", "path": "config.json", "jpaths": ["models[].id", "quota.active"]},
            {"id": "h1", "op": "http_get", "url": f"{self.anchor}/api/pulse", "jpath": "ok"},
            {"id": "h2", "op": "http_get", "url": f"{self.anchor}/api/pulse", "jpaths": ["ok", "node"]},
        ]
        code, out = self._post("/v1/agent/xray-batch", {"ops": ops, "cwd": str(self.repo), "max_workers": 1})
        self.assertEqual(code, 200)
        self.assertTrue(out["ok"], out)
        # Duplicate file_slice on math_core.py + duplicate http_get on /api/pulse MUST coalesce!
        self.assertGreaterEqual(out["coalesced_hits"], 2)
        by_id = {r["id"]: r for r in out["results"]}
        self.assertEqual([f["path"] for f in by_id["ls_pat"]["files"]], ["entitlement.js"])
        self.assertEqual(by_id["ls_pat"]["glob"], "*entitlement*")
        self.assertEqual(by_id["rg_lim"]["count"], 2)
        self.assertEqual(by_id["jq_multi"]["values"]["quota.active"], 2)
        self.assertTrue(by_id["h2"]["values"]["ok"])

        # 4. Verify MCP server emits compact wire JSON (no indent=2 whitespace bloat)
        resp = handle_mcp_request(
            {
                "jsonrpc": "2.0",
                "id": 9,
                "method": "tools/call",
                "params": {
                    "name": "chimera_xray_batch",
                    "arguments": {"cwd": str(self.repo), "ops": [{"op": "list_files", "path": "src", "pattern": "*.js"}]},
                },
            },
            anchor_url=self.anchor,
        )
        wire_text = resp["result"]["content"][0]["text"]
        self.assertNotIn("\n  ", wire_text)
        parsed = json.loads(wire_text)
        self.assertTrue(parsed["ok"])
        self.assertEqual(len(parsed["results"][0]["files"]), 3)


if __name__ == "__main__":
    unittest.main()
