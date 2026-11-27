"""Unit & Live HTTP tests for CHIMERA Omega-Spine (Iron Cage, Precog, Tournament, Streamable MCP & 6-Event Hooks)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from chimera_tp.autopilot import OpsConfig
from chimera_tp.dashboard import ChimeraDaemon
from chimera_tp.omega_spine.hook_router import HookRouter, OmegaSpineRuntime
from chimera_tp.omega_spine.iron_cage import (
    IronCage,
    SingleflightCommandCache,
    compute_worker_affinity_mask,
)
from chimera_tp.omega_spine.precog_tournament import (
    PrecogVerifier,
    ShadowTournament,
    parse_dotnet_diagnostics,
)
from chimera_tp.omega_spine.streamable_mcp import (
    EAGER_SUPER_TOOLS,
    MCP_PROTOCOL_VERSION,
    StreamableMcpServer,
    _fallback_resolve_safe_repo,
)


def _http_json(
    url: str,
    *,
    method: str = "GET",
    body: dict | list | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 10.0,
) -> tuple[int, Any, dict[str, str]]:
    hdrs = dict(headers or {})
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            resp_hdrs = {k.lower(): v for k, v in resp.headers.items()}
            parsed = json.loads(raw.decode("utf-8")) if raw.strip() else None
            return int(resp.status), parsed, resp_hdrs
    except urllib.error.HTTPError as err:
        raw = err.read()
        resp_hdrs = {k.lower(): v for k, v in err.headers.items()}
        parsed = json.loads(raw.decode("utf-8")) if raw.strip() else None
        return int(err.code), parsed, resp_hdrs


def _make_sample_repo(root: Path) -> Path:
    repo = root / "sample_repo"
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "src").mkdir()
    (repo / "tests").mkdir()
    (repo / "src" / "Solver.cs").write_text(
        "namespace Demo.Core\n"
        "{\n"
        "    public partial class SmartSolver\n"
        "    {\n"
        "        public int ComputeScore(int x)\n"
        "        {\n"
        "            return x * 2;\n"
        "        }\n"
        "    }\n"
        "}\n",
        encoding="utf-8",
    )
    (repo / "tests" / "SmartSolverTests.cs").write_text(
        "namespace Demo.Tests\n"
        "{\n"
        "    public class SmartSolverTests\n"
        "    {\n"
        "        public void TestComputeScore()\n"
        "        {\n"
        "            var s = new Demo.Core.SmartSolver();\n"
        "            var v = s.ComputeScore(21);\n"
        "        }\n"
        "    }\n"
        "}\n",
        encoding="utf-8",
    )
    (repo / "src" / "calc.py").write_text(
        "def add(a: int, b: int) -> int:\n"
        "    return a + b\n",
        encoding="utf-8",
    )
    (repo / "tests" / "test_calc.py").write_text(
        "import sys, unittest\n"
        "from pathlib import Path\n"
        "sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))\n"
        "from calc import add\n\n"
        "class TestCalc(unittest.TestCase):\n"
        "    def test_add(self):\n"
        "        self.assertEqual(add(2, 3), 5)\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "tester@example.invalid"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "OmegaTester"], cwd=repo, check=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=repo, check=True)
    return repo


class TestOmegaSpineMcpHooks(unittest.TestCase):
    def test_01_iron_cage_affinity_spawn_timeout_and_sweep(self) -> None:
        self.assertEqual(compute_worker_affinity_mask(8), 0xFC)
        self.assertEqual(compute_worker_affinity_mask(6), 0x3C)
        self.assertEqual(compute_worker_affinity_mask(4), 0xE)
        self.assertIsNone(compute_worker_affinity_mask(2))

        cage = IronCage()
        try:
            with tempfile.TemporaryDirectory() as td:
                res = cage.spawn_caged([sys.executable, "-c", "print('iron_cage_ok')"], cwd=td, timeout_s=10.0)
                self.assertTrue(res["ok"])
                self.assertEqual(res["exit_code"], 0)
                self.assertIn("iron_cage_ok", res["stdout"])
                if os.name == "nt":
                    self.assertTrue(res["conhost_avoided"])

                # Timeout enforcement kills cleanly
                res_to = cage.spawn_caged(
                    [sys.executable, "-c", "import time; time.sleep(5)"],
                    cwd=td,
                    timeout_s=0.35,
                )
                self.assertFalse(res_to["ok"])
                self.assertTrue(res_to["timed_out"])
                self.assertEqual(res_to["exit_code"], 124)

            royal = cage.apply_royal_ui_tier([99999999])
            self.assertTrue(royal["ok"])

            sweep = cage.cage_sweep_agent_children(target_names=("definitely_not_running_xyz.exe",))
            self.assertTrue(sweep["ok"])
            self.assertGreaterEqual(sweep["scanned"], 0)

            st = cage.status()
            self.assertTrue(st["ok"])
            self.assertIn("caged_pids", st)
            self.assertIn("singleflight_hits", st)
            self.assertIn("conhost_avoided", st)
            if os.name == "nt":
                self.assertGreaterEqual(st["conhost_avoided"], 2)
        finally:
            cage.close()

    def test_02_singleflight_coalescing_and_sub_2ms_ttl_cache(self) -> None:
        sf = SingleflightCommandCache(ttl_s=3.0, max_entries=16)
        calls = 0
        call_lock = threading.Lock()
        barrier = threading.Barrier(5)

        def slow_op() -> dict[str, int]:
            nonlocal calls
            with call_lock:
                calls += 1
            time.sleep(0.12)
            return {"value": 42}

        results: list[tuple[dict, str]] = []
        res_lock = threading.Lock()

        def worker() -> None:
            barrier.wait()
            val, mode = sf.run_or_join("k_shared", slow_op)
            with res_lock:
                results.append((val, mode))

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        self.assertEqual(calls, 1)
        self.assertEqual(len(results), 5)
        modes = [m for _, m in results]
        self.assertEqual(modes.count("executed"), 1)
        self.assertEqual(modes.count("coalesced"), 4)

        # Rapid repeat hits TTL cache in < 2 ms
        t0 = time.perf_counter()
        val2, mode2 = sf.run_or_join("k_shared", slow_op)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        self.assertEqual(mode2, "ttl_cache")
        self.assertEqual(val2["value"], 42)
        self.assertLess(elapsed_ms, 5.0)
        self.assertEqual(calls, 1)

        stats = sf.stats()
        self.assertEqual(stats["coalesced_hits"], 4)
        self.assertEqual(stats["cache_hits"], 1)
        self.assertEqual(stats["total_hits"], 5)

    def test_03_precog_verifier_and_dotnet_diagnostics_parser(self) -> None:
        sample_msbuild = (
            "src\\Solver.cs(14,22): error CS1002: ; expected [E:\\repo\\Demo.csproj]\n"
            "src\\Solver.cs(18,9): error CS0103: The name 'foo' does not exist [E:\\repo\\Demo.csproj]\n"
            "src\\Solver.cs(2,1): warning CS0168: Unused variable [E:\\repo\\Demo.csproj]\n"
        )
        parsed = parse_dotnet_diagnostics(sample_msbuild)
        self.assertEqual(len(parsed), 3)
        self.assertEqual(parsed[0]["code"], "CS1002")
        self.assertEqual(parsed[0]["line"], 14)
        self.assertEqual(parsed[1]["code"], "CS0103")
        self.assertEqual(parsed[2]["severity"], "warning")

        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            cs_file = repo / "Broken.cs"
            cs_file.write_text("public class Broken {\n    public void Run() {\n", encoding="utf-8")
            py_file = repo / "bad.py"
            py_file.write_text("def oops(:\n    pass\n", encoding="utf-8")

            cage = IronCage()
            try:
                pc = PrecogVerifier(iron_cage=cage, enable_dotnet_build=False)
                pc.schedule("conv_1", repo, "Broken.cs")
                pc.schedule("conv_1", repo, "bad.py")
                self.assertTrue(pc.wait_idle(timeout_s=5.0))

                self.assertTrue(pc.has_blocking_errors("conv_1", repo))
                diags = pc.consume_diagnostics("conv_1", repo)
                self.assertGreaterEqual(len(diags), 2)
                # Second consume is empty (no spam)
                self.assertEqual(pc.consume_diagnostics("conv_1", repo), [])

                # Fix both files -> blocking clears automatically
                cs_file.write_text("public class Broken {\n    public void Run() {}\n}\n", encoding="utf-8")
                py_file.write_text("def fixed():\n    return 1\n", encoding="utf-8")
                pc.verify_file_now("conv_1", repo, "Broken.cs")
                pc.verify_file_now("conv_1", repo, "bad.py")
                self.assertFalse(pc.has_blocking_errors("conv_1", repo))
            finally:
                cage.close()

    def test_04_shadow_tournament_ranks_cleans_and_promotes_winner(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = _make_sample_repo(Path(td))
            oracle = (
                f'"{sys.executable}" -c '
                '"import json, sys; sys.path.insert(0, \'src\'); from calc import add; '
                'v = add(10, 5); '
                'print(json.dumps({\'pass\': v == 15 or v == 150, \'score\': float(v)}))"'
            )
            cage = IronCage()
            try:
                trn = ShadowTournament(iron_cage=cage)
                res = trn.run(
                    repo=repo,
                    oracle_cmd=oracle,
                    candidates=[
                        {
                            "name": "cand_fail",
                            "files": {"src/calc.py": "def add(a, b):\n    return 0\n"},
                        },
                        {
                            "name": "cand_good",
                            "files": {"src/calc.py": "def add(a, b):\n    return a + b\n"},
                        },
                        {
                            "name": "cand_best",
                            "files": {"src/calc.py": "def add(a, b):\n    return (a + b) * 10\n"},
                        },
                    ],
                )
                self.assertTrue(res["ok"])
                self.assertEqual(res["winner"]["name"], "cand_best")
                self.assertEqual(res["rankings"][0]["name"], "cand_best")
                self.assertEqual(res["rankings"][0]["score"], 150.0)
                self.assertEqual(res["rankings"][1]["name"], "cand_good")
                self.assertFalse(res["rankings"][2]["pass"])

                # Real repo MUST still have original code prior to promotion
                self.assertIn("return a + b", (repo / "src" / "calc.py").read_text(encoding="utf-8"))

                promo = trn.promote_winner(res["tournament_id"])
                self.assertTrue(promo["ok"])
                self.assertEqual(promo["winner"], "cand_best")
                self.assertIn("return (a + b) * 10", (repo / "src" / "calc.py").read_text(encoding="utf-8"))
                self.assertEqual(trn.status()["tournaments_total"], 1)
            finally:
                cage.close()

    def test_05_cwd_guard_rejects_chimera_release_dir(self) -> None:
        with self.assertRaises(ValueError):
            _fallback_resolve_safe_repo(
                None,
                fallback_cwd=r"C:\Users\Admin\AppData\Local\chimera\releases\e13c4da7d80b",
            )
        with self.assertRaises(ValueError):
            _fallback_resolve_safe_repo(
                None,
                fallback_cwd="/home/svhome/.local/share/chimera/releases/e13c4da7d80b",
            )

    def test_06_live_http_mcp_hooks_and_omega_routes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = _make_sample_repo(root)
            cfg = OpsConfig(
                role="server",
                node_name="omega-spine-test",
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
            # Keep dotnet build off during unit test for instant deterministic speed
            daemon.omega_spine.precog.enable_dotnet_build = False
            base = f"http://127.0.0.1:{daemon.http_addr[1]}"

            try:
                # --- A) MCP Streamable HTTP 2025-03-26 ---
                st_get, body_get, hdrs_get = _http_json(f"{base}/mcp", method="GET")
                self.assertEqual(st_get, 405)
                self.assertIn("POST", hdrs_get.get("allow", ""))

                st_init, init_resp, init_hdrs = _http_json(
                    f"{base}/mcp",
                    method="POST",
                    body={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "initialize",
                        "params": {"protocolVersion": MCP_PROTOCOL_VERSION, "clientInfo": {"name": "pytest"}},
                    },
                )
                self.assertEqual(st_init, 200)
                self.assertEqual(init_resp["result"]["protocolVersion"], MCP_PROTOCOL_VERSION)
                mcp_sid = init_hdrs.get("mcp-session-id", "")
                self.assertTrue(mcp_sid)

                # Notification (no id) -> 202 Accepted
                st_notif, notif_body, _ = _http_json(
                    f"{base}/mcp",
                    method="POST",
                    headers={"Mcp-Session-Id": mcp_sid},
                    body={"jsonrpc": "2.0", "method": "notifications/initialized"},
                )
                self.assertEqual(st_notif, 202)
                self.assertIsNone(notif_body)

                # Ping
                st_ping, ping_resp, _ = _http_json(
                    f"{base}/mcp",
                    method="POST",
                    headers={"Mcp-Session-Id": mcp_sid},
                    body={"jsonrpc": "2.0", "id": 2, "method": "ping"},
                )
                self.assertEqual(st_ping, 200)
                self.assertEqual(ping_resp["result"], {})

                # tools/list -> EXACTLY 6 crisp Eager Super-Tools
                st_list, list_resp, _ = _http_json(
                    f"{base}/mcp",
                    method="POST",
                    headers={"Mcp-Session-Id": mcp_sid},
                    body={"jsonrpc": "2.0", "id": 3, "method": "tools/list"},
                )
                self.assertEqual(st_list, 200)
                tools = list_resp["result"]["tools"]
                self.assertEqual(len(tools), 6)
                expected_names = {
                    "chimera_bootstrap",
                    "chimera_xray_batch",
                    "chimera_surgical_bundle",
                    "chimera_atomic_patch",
                    "chimera_commit_verify",
                    "chimera_hive_cortex",
                }
                self.assertEqual({t["name"] for t in tools}, expected_names)

                def mcp_call(name: str, arguments: dict) -> dict:
                    sc, resp, _ = _http_json(
                        f"{base}/mcp",
                        method="POST",
                        headers={"Mcp-Session-Id": mcp_sid},
                        body={
                            "jsonrpc": "2.0",
                            "id": 10,
                            "method": "tools/call",
                            "params": {"name": name, "arguments": arguments},
                        },
                    )
                    self.assertEqual(sc, 200)
                    return resp["result"]["structuredContent"]

                # Tool 1: chimera_bootstrap
                boot = mcp_call("chimera_bootstrap", {"repo": str(repo), "conversation_id": "mcp_c1"})
                self.assertTrue(boot["ok"])
                self.assertTrue(boot["git"]["is_git"])
                self.assertIn("runtime_source_dir", boot)
                self.assertTrue(any("src" in e for e in boot["repo_tree"]))

                # Tool 2: chimera_xray_batch (all 6 op types + path traversal block + singleflight hit)
                batch_ops = [
                    {"op": "outline", "path": "src/Solver.cs"},
                    {"op": "list_files", "path": ".", "glob": "*.cs"},
                    {"op": "regex_search", "pattern": "ComputeScore"},
                    {"op": "file_slice", "path": "src/calc.py", "start_line": 1, "end_line": 5},
                    {"op": "git_status"},
                    {"op": "surgical_bundle", "symbol": "ComputeScore"},
                    {"op": "file_slice", "path": "../escape.txt"},
                ]
                xb1 = mcp_call("chimera_xray_batch", {"repo": str(repo), "ops": batch_ops})
                self.assertTrue(xb1["ok"])
                self.assertEqual(xb1["count"], 7)
                self.assertTrue(xb1["results"][0]["ok"])
                self.assertIn("src/Solver.cs", xb1["results"][1]["files"])
                self.assertGreaterEqual(xb1["results"][2]["hit_count"], 1)
                self.assertIn("def add", xb1["results"][3]["content"])
                self.assertTrue(xb1["results"][4]["is_git"])
                self.assertTrue(xb1["results"][5]["ok"])
                self.assertFalse(xb1["results"][6]["ok"])  # path escape rejected!

                xb2 = mcp_call("chimera_xray_batch", {"repo": str(repo), "ops": batch_ops})
                self.assertTrue(xb2["singleflight_hit"])

                # Tool 3: chimera_surgical_bundle
                sb = mcp_call("chimera_surgical_bundle", {"repo": str(repo), "symbol": "ComputeScore", "hops": 2, "max_bytes": 8192})
                self.assertTrue(sb["ok"])

                # Tool 4: chimera_atomic_patch (syntax gate rejects bad C# before touching disk!)
                orig_cs = (repo / "src" / "Solver.cs").read_text(encoding="utf-8")
                bad_patch = mcp_call(
                    "chimera_atomic_patch",
                    {
                        "repo": str(repo),
                        "edits": [{"path": "src/Solver.cs", "content": "public class Broken { void X() {"}],
                    },
                )
                self.assertFalse(bad_patch["ok"])
                self.assertEqual(bad_patch["stage"], "syntax_gate")
                self.assertEqual((repo / "src" / "Solver.cs").read_text(encoding="utf-8"), orig_cs)

                # Valid atomic patch applies cleanly
                good_patch = mcp_call(
                    "chimera_atomic_patch",
                    {
                        "repo": str(repo),
                        "edits": [{"path": "src/calc.py", "old": "return a + b", "new": "return int(a + b)"}],
                    },
                )
                self.assertTrue(good_patch["ok"])
                self.assertIn("return int(a + b)", (repo / "src" / "calc.py").read_text(encoding="utf-8"))

                # Tool 5: chimera_commit_verify (runs pytest in Iron Cage + BLAKE2s cache hit on 2nd run)
                cv1 = mcp_call("chimera_commit_verify", {"repo": str(repo), "changed_files": ["src/calc.py"]})
                self.assertTrue(cv1["ok"], msg=cv1)
                self.assertFalse(cv1["cache_hit"])
                self.assertIn(cv1["runner"], ("pytest", "unittest"))

                cv2 = mcp_call("chimera_commit_verify", {"repo": str(repo), "changed_files": ["src/calc.py"]})
                self.assertTrue(cv2["ok"])
                self.assertTrue(cv2["cache_hit"])
                self.assertEqual(cv1["blake2s"], cv2["blake2s"])

                # Modifying file invalidates BLAKE2s cache cleanly
                (repo / "src" / "calc.py").write_text("def add(a: int, b: int) -> int:\n    return (a + b)\n", encoding="utf-8")
                cv3 = mcp_call("chimera_commit_verify", {"repo": str(repo), "changed_files": ["src/calc.py"]})
                self.assertTrue(cv3["ok"])
                self.assertFalse(cv3["cache_hit"])
                self.assertNotEqual(cv3["blake2s"], cv2["blake2s"])

                # Tool 6: chimera_hive_cortex (lease, put_capsule, recall_capsules, cage_status, status, release)
                ls_res = mcp_call("chimera_hive_cortex", {
                    "action": "lease",
                    "repo": str(repo),
                    "agent_id": "worker-alpha",
                    "files": ["src/Solver.cs"],
                    "intent": "refactor solver",
                })
                self.assertTrue(ls_res["ok"])

                cap_put = mcp_call("chimera_hive_cortex", {
                    "action": "put_capsule",
                    "repo": str(repo),
                    "rel_path": "src/Solver.cs",
                    "symbol": "ComputeScore",
                    "summary": "Multiplies input by 2 safely",
                    "invariants": ["pure", "no side effects"],
                })
                self.assertTrue(cap_put.get("ok", True))

                cap_rec = mcp_call("chimera_hive_cortex", {
                    "action": "recall_capsules",
                    "repo": str(repo),
                    "files": ["src/Solver.cs"],
                })
                self.assertTrue(cap_rec["ok"])
                self.assertGreaterEqual(cap_rec["count"], 1)

                cage_st = mcp_call("chimera_hive_cortex", {"action": "cage_status"})
                self.assertTrue(cage_st["ok"])

                mcp_call("chimera_hive_cortex", {"action": "release", "repo": str(repo), "agent_id": "worker-alpha"})

                # --- B) Antigravity 2.0 6-Event Lifecycle Hooks ---
                # 1) session_start
                t_hk = time.perf_counter()
                sc_ss, ss_res, _ = _http_json(
                    f"{base}/v1/hook/session_start",
                    method="POST",
                    body={"conversationId": "conv_live_1", "workspacePaths": [str(repo)], "cwd": str(repo)},
                )
                ss_ms = (time.perf_counter() - t_hk) * 1000.0
                self.assertEqual(sc_ss, 200)
                self.assertEqual(len(ss_res["injectSteps"]), 1)
                sys_step = ss_res["injectSteps"][0]["systemMessage"]
                self.assertIn("CHIMERA Omega-Spine", sys_step["systemMessage"])
                self.assertIn("user_markdown", sys_step["metadata"])
                self.assertLess(ss_ms, 250.0)

                # Registered session lets MCP resolve repo automatically without passing `repo`!
                auto_boot = mcp_call("chimera_bootstrap", {"conversation_id": "conv_live_1"})
                self.assertTrue(auto_boot["ok"])
                self.assertEqual(Path(auto_boot["repo"]).resolve(), repo.resolve())

                # 2) pre_tool_use (hard lock denies, soft lease allows + warns, run_command allows)
                mcp_call("chimera_hive_cortex", {
                    "action": "lease",
                    "repo": str(repo),
                    "agent_id": "sibling_hard",
                    "files": ["src/locked.cs"],
                    "hard_lock": True,
                })
                sc_deny, deny_res, _ = _http_json(
                    f"{base}/v1/hook/pre_tool_use",
                    method="POST",
                    body={
                        "conversationId": "conv_live_1",
                        "toolCall": {"name": "edit_file", "arguments": {"Path": str(repo / "src" / "locked.cs")}},
                    },
                )
                self.assertEqual(sc_deny, 200)
                self.assertEqual(deny_res["decision"], "deny")

                sc_allow, allow_res, _ = _http_json(
                    f"{base}/v1/hook/pre_tool_use",
                    method="POST",
                    body={
                        "conversationId": "conv_live_1",
                        "toolCall": {"name": "run_command", "arguments": {"CommandLine": "dotnet test --no-restore"}},
                    },
                )
                self.assertEqual(sc_allow, 200)
                self.assertEqual(allow_res["decision"], "allow")

                # 3) post_tool_use: error -> fix distills Immune Antibody; broken edit triggers Precog
                _http_json(
                    f"{base}/v1/hook/post_tool_use",
                    method="POST",
                    body={
                        "conversationId": "conv_live_1",
                        "stepIdx": 1,
                        "toolCall": {"name": "run_command", "arguments": {"CommandLine": "echo a && echo b"}},
                        "error": "PowerShell 5.1 token '&&' is not a valid statement separator",
                    },
                )
                sc_post_ok, post_ok_res, _ = _http_json(
                    f"{base}/v1/hook/post_tool_use",
                    method="POST",
                    body={
                        "conversationId": "conv_live_1",
                        "stepIdx": 2,
                        "toolCall": {"name": "run_command", "arguments": {"CommandLine": "echo a; echo b"}},
                    },
                )
                self.assertEqual(sc_post_ok, 200)
                self.assertEqual(post_ok_res, {})

                # Write broken C# file and notify post_tool_use
                (repo / "src" / "Solver.cs").write_text("public class SmartSolver {\n  void Oops() {\n", encoding="utf-8")
                sc_pe, pe_res, _ = _http_json(
                    f"{base}/v1/hook/post_tool_use",
                    method="POST",
                    body={
                        "conversationId": "conv_live_1",
                        "stepIdx": 3,
                        "toolCall": {"name": "edit_file", "arguments": {"Path": str(repo / "src" / "Solver.cs")}},
                    },
                )
                self.assertEqual(sc_pe, 200)
                self.assertEqual(pe_res, {})
                self.assertTrue(daemon.omega_spine.precog.wait_idle(timeout_s=5.0))

                # 4) pre_invocation injects Precog diagnostics once, then zero noise!
                sc_pi1, pi1, _ = _http_json(
                    f"{base}/v1/hook/pre_invocation",
                    method="POST",
                    body={"conversationId": "conv_live_1", "invocationNum": 2},
                )
                self.assertEqual(sc_pi1, 200)
                self.assertEqual(len(pi1["injectSteps"]), 1)
                self.assertIn("PRECOG DIAGNOSTICS", pi1["injectSteps"][0]["systemMessage"]["systemMessage"])

                sc_pi2, pi2, _ = _http_json(
                    f"{base}/v1/hook/pre_invocation",
                    method="POST",
                    body={"conversationId": "conv_live_1", "invocationNum": 3},
                )
                self.assertEqual(sc_pi2, 200)
                self.assertEqual(pi2, {"injectSteps": []})

                # 5) post_invocation
                sc_po, po_res, _ = _http_json(
                    f"{base}/v1/hook/post_invocation",
                    method="POST",
                    body={"conversationId": "conv_live_1", "invocationNum": 3, "terminationReason": "NO_TOOL_CALL"},
                )
                self.assertEqual(sc_po, 200)
                self.assertEqual(po_res, {"injectSteps": [], "terminationBehavior": ""})

                # 6) stop sentinel catches blocking syntax error when !continuationActive & NO_TOOL_CALL
                sc_st1, st1, _ = _http_json(
                    f"{base}/v1/hook/stop",
                    method="POST",
                    body={
                        "conversationId": "conv_live_1",
                        "terminationReason": "NO_TOOL_CALL",
                        "continuationActive": False,
                    },
                )
                self.assertEqual(sc_st1, 200)
                self.assertEqual(st1.get("decision"), "continue")
                self.assertIn("Chimera Precog detected syntax/compile errors", st1.get("reason", ""))

                # continuationActive=True must NOT loop
                sc_st2, st2, _ = _http_json(
                    f"{base}/v1/hook/stop",
                    method="POST",
                    body={
                        "conversationId": "conv_live_1",
                        "terminationReason": "NO_TOOL_CALL",
                        "continuationActive": True,
                    },
                )
                self.assertEqual(sc_st2, 200)
                self.assertEqual(st2, {})

                # Fix file -> stop returns {} cleanly
                (repo / "src" / "Solver.cs").write_text(orig_cs, encoding="utf-8")
                sc_st3, st3, _ = _http_json(
                    f"{base}/v1/hook/stop",
                    method="POST",
                    body={
                        "conversationId": "conv_live_1",
                        "terminationReason": "NO_TOOL_CALL",
                        "continuationActive": False,
                    },
                )
                self.assertEqual(sc_st3, 200)
                self.assertEqual(st3, {})

                # --- C) /v1/omega/* endpoints & backward compatibility ---
                sc_os, os_res, _ = _http_json(f"{base}/v1/omega/status")
                self.assertEqual(sc_os, 200)
                # Preserves existing v21 field for test_v19_v21_omega_entity.py!
                self.assertEqual(os_res["ctrl_z_scope"], "committed_patch_files")
                self.assertIn("omega_spine", os_res)
                self.assertEqual(os_res["omega_spine"]["mcp"]["tools_count"], 6)

                sc_cg, cg_res, _ = _http_json(f"{base}/v1/omega/cage")
                self.assertEqual(sc_cg, 200)
                self.assertTrue(cg_res["ok"])

                sc_pc, pc_res, _ = _http_json(f"{base}/v1/omega/precog?conversation_id=conv_live_1")
                self.assertEqual(sc_pc, 200)
                self.assertFalse(pc_res["has_blocking_errors"])

                sc_tr, tr_res, _ = _http_json(f"{base}/v1/omega/tournament")
                self.assertEqual(sc_tr, 200)
                self.assertTrue(tr_res["ok"])

                # DELETE /mcp closes session
                sc_del, del_res, _ = _http_json(
                    f"{base}/mcp",
                    method="DELETE",
                    headers={"Mcp-Session-Id": mcp_sid},
                )
                self.assertEqual(sc_del, 200)
                self.assertTrue(del_res["closed"])
            finally:
                daemon.close()


if __name__ == "__main__":
    unittest.main()
