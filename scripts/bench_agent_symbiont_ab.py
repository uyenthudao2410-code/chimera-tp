"""Reproducible End-to-End A/B Benchmark for CHIMERA-SYMBIONT + Agent Hyper-Bus.

Measures the REAL slow-command coding-agent pain point across all 5 dimensions:
  A. 12-Op Forensic Workload: Legacy Sequential PowerShell vs HTTP xray_batch vs Persistent MCP Stdio
     (including real MCP stdio startup overhead vs warm persistent JSON-RPC round-trip!).
  B. Outline + Targeted Read vs Blind Full-File Read (token & byte savings).
  C. Cold Callgraph (234 files) vs Warm Callgraph vs `<2 ms` Incremental Single-File Precog AST update.
  D. Synchronous `commit_verify` Wall vs `Precog-Runner` Background Shadow-Test (`precog_hit` ms).
  E. `Surgeon` RAM Format Gate (broken TOML/PY blocked before disk) + `Telepathy Capsule` + `Bootstrap`
     + Spill-Shield verification + live daemon RAM (`< 80 MiB` Law 7).
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

REPO = Path(r"E:\DEV\chimera-tp")
ANCHOR = "http://127.0.0.1:9780"
OUT_JSON = REPO / "tasks" / "agent_symbiont_ab.json"
NO_WIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _post(path: str, body: dict, timeout: float = 45.0) -> tuple[float, dict]:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    req = urllib.request.Request(
        f"{ANCHOR}{path}",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    t0 = time.perf_counter()
    with opener.open(req, timeout=timeout) as r:
        data = json.loads(r.read().decode("utf-8"))
    return round((time.perf_counter() - t0) * 1000.0, 2), data


def _get(path: str) -> dict:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(f"{ANCHOR}{path}", timeout=5.0) as r:
        return json.loads(r.read().decode("utf-8"))


def main() -> int:
    # --- STAGE A: 12-Op Slow Command Benchmark (PowerShell vs HTTP xray_batch vs Persistent MCP Stdio) ---
    ps_cmds = [
        "Get-Content -Encoding UTF8 chimera_tp/platform/agent_probe.py | Select-Object -First 40",
        "Get-Content -Encoding UTF8 chimera_tp/platform/agent_symbiont.py | Select-Object -First 40",
        "Get-Content -Encoding UTF8 chimera_tp/platform/substrate.py | Select-Object -Skip 1670 -First 40",
        "Get-Content -Encoding UTF8 chimera_tp/platform/mcp_server.py | Select-Object -Skip 330 -First 45",
        "Get-Content -Encoding UTF8 chimera_tp/platform/unify.py | Select-Object -Skip 240 -First 40",
        "Select-String -Path chimera_tp/platform/substrate.py -Pattern '/v1/agent/' | Select-Object -First 15",
        "Select-String -Path chimera_tp/platform/mcp_server.py -Pattern 'chimera_' | Select-Object -First 15",
        "Get-ChildItem -Path chimera_tp/platform -Filter '*.py' | Select-Object -ExpandProperty Name",
        "Get-ChildItem -Path tests -Filter '*agent*' | Select-Object -ExpandProperty Name",
        "(Invoke-RestMethod 'http://127.0.0.1:9780/.well-known/chimera.json' -TimeoutSec 4).pid",
        "(Invoke-RestMethod 'http://127.0.0.1:9780/v1/agent/probe-stats' -TimeoutSec 4).organ",
        "git status --short | Select-Object -First 20",
    ]
    ps_times: list[float] = []
    ps_bytes = 0
    ps_ok = 0
    t_ps0 = time.perf_counter()
    for cmd in ps_cmds:
        c0 = time.perf_counter()
        p = subprocess.run(
            ["powershell", "-NoProfile", "-Command", cmd],
            cwd=str(REPO),
            capture_output=True,
            text=True,
            timeout=15.0,
            creationflags=NO_WIN,
        )
        ps_times.append(round((time.perf_counter() - c0) * 1000.0, 2))
        ps_bytes += len((p.stdout or "").encode("utf-8", errors="replace"))
        if p.returncode == 0:
            ps_ok += 1
    ps_total_ms = round((time.perf_counter() - t_ps0) * 1000.0, 2)

    xray_ops = [
        {"id": "f1", "op": "file_slice", "path": "chimera_tp/platform/agent_probe.py", "start_line": 1, "end_line": 40},
        {"id": "f2", "op": "file_slice", "path": "chimera_tp/platform/agent_symbiont.py", "start_line": 1, "end_line": 40},
        {"id": "f3", "op": "file_slice", "path": "chimera_tp/platform/substrate.py", "start_line": 1671, "end_line": 1710},
        {"id": "f4", "op": "file_slice", "path": "chimera_tp/platform/mcp_server.py", "start_line": 331, "end_line": 375},
        {"id": "f5", "op": "file_slice", "path": "chimera_tp/platform/unify.py", "start_line": 241, "end_line": 280},
        {"id": "r1", "op": "regex_search", "path": "chimera_tp/platform/substrate.py", "pattern": "/v1/agent/", "limit": 15},
        {"id": "r2", "op": "regex_search", "path": "chimera_tp/platform/mcp_server.py", "pattern": "chimera_", "limit": 15},
        {"id": "l1", "op": "list_files", "path": "chimera_tp/platform", "pattern": "*.py", "limit": 60},
        {"id": "l2", "op": "list_files", "path": "tests", "pattern": "*agent*", "limit": 20},
        {"id": "h1", "op": "http_get", "url": f"{ANCHOR}/.well-known/chimera.json", "jpath": "pid"},
        {"id": "h2", "op": "http_get", "url": f"{ANCHOR}/v1/agent/probe-stats", "jpath": "organ"},
        {"id": "g1", "op": "git_status", "path": ".", "limit": 20, "max_chars": 1200},
    ]
    http_ms, http_res = _post("/v1/agent/xray-batch", {"ops": xray_ops, "cwd": str(REPO), "compact": True})

    # Persistent MCP stdio server benchmark (measures real MCP cold boot + warm JSON-RPC round-trip + Spill-Shield!)
    t_mcp_boot0 = time.perf_counter()
    mcp_proc = subprocess.Popen(
        [sys.executable, "-m", "chimera_tp", "mcp"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(REPO),
        creationflags=NO_WIN,
    )
    assert mcp_proc.stdin and mcp_proc.stdout
    try:
        mcp_proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}) + "\n")
        mcp_proc.stdin.flush()
        _ = mcp_proc.stdout.readline()
        mcp_cold_init_ms = round((time.perf_counter() - t_mcp_boot0) * 1000.0, 2)

        t_m1 = time.perf_counter()
        mcp_proc.stdin.write(
            json.dumps({
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "chimera_xray_batch", "arguments": {"cwd": str(REPO), "ops": xray_ops, "compact": True}},
            })
            + "\n"
        )
        mcp_proc.stdin.flush()
        mcp_line = mcp_proc.stdout.readline()
        mcp_warm_12op_ms = round((time.perf_counter() - t_m1) * 1000.0, 2)
        mcp_msg = json.loads(mcp_line)
        mcp_wire_bytes = len(mcp_msg["result"]["content"][0]["text"].encode("utf-8"))
        mcp_spill_safe = mcp_wire_bytes <= 8600
    finally:
        mcp_proc.terminate()
        try:
            mcp_proc.wait(timeout=3.0)
        except Exception:
            mcp_proc.kill()

    # --- STAGE B: Outline vs Blind Full-File Read ---
    full_bytes = sum((REPO / f).stat().st_size for f in ("chimera_tp/platform/substrate.py", "chimera_tp/platform/agent_probe.py", "chimera_tp/platform/agent_symbiont.py"))
    out_ms, out_res = _post(
        "/v1/agent/xray-batch",
        {
            "cwd": str(REPO),
            "ops": [
                {"op": "outline", "path": "chimera_tp/platform/substrate.py"},
                {"op": "outline", "path": "chimera_tp/platform/agent_probe.py"},
                {"op": "outline", "path": "chimera_tp/platform/agent_symbiont.py"},
            ],
        },
    )
    outline_bytes = len(json.dumps(out_res, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))

    # --- STAGE C: Callgraph Cold/Warm vs Incremental Single-File Precog AST ---
    cg_cold_ms, cg_cold = _post("/v1/agent/callgraph-slice", {"repo": str(REPO), "symbol": "atomic_patch", "depth": 2})
    cg_warm_ms, _ = _post("/v1/agent/callgraph-slice", {"repo": str(REPO), "symbol": "atomic_patch", "depth": 2})
    inc_ms, inc_res = _post(
        "/v1/agent/precog",
        {"action": "notify_save", "repo": str(REPO), "files": ["chimera_tp/platform/agent_symbiont.py"], "run_shadow_test": False},
    )

    # --- STAGE D & E: Isolated Temp Repo Proof of Precog Shadow Test + Surgeon Gate + Capsule + Bootstrap ---
    with tempfile.TemporaryDirectory(prefix="chimera_ab_sym_") as td:
        trepo = Path(td)
        (trepo / "pkg").mkdir()
        (trepo / "tests").mkdir()
        (trepo / "pkg" / "__init__.py").write_text("", encoding="utf-8")
        (trepo / "pkg" / "m.py").write_text("def add(a: int, b: int) -> int:\n    return a + b\n", encoding="utf-8")
        (trepo / "tests" / "test_m.py").write_text(
            "import time, unittest\nfrom pkg.m import add\nclass T(unittest.TestCase):\n"
            "    def test_add(self):\n        time.sleep(0.6)\n        self.assertEqual(add(2, 3), 5)\n",
            encoding="utf-8",
        )
        (trepo / "cfg.toml").write_text('cmd = "C:\\\\Python311\\\\python.exe"\n', encoding="utf-8")

        # 1. Baseline synchronous commit_verify (cold, no precog)
        sync_v_ms, sync_v = _post("/v1/agent/commit-verify", {"repo": str(trepo), "files": ["pkg/m.py"], "run_tests": True, "use_cache": False})

        # 2. Mutate file + trigger Precog while LLM "thinks" for 1.2s -> then commit_verify hits precog_hit!
        (trepo / "pkg" / "m.py").write_text("def add(a: int, b: int) -> int:\n    return a + b\n\ndef sub(a: int, b: int) -> int:\n    return a - b\n", encoding="utf-8")
        _, p_trig = _post("/v1/agent/precog", {"action": "notify_save", "repo": str(trepo), "files": ["pkg/m.py"], "run_shadow_test": True})
        time.sleep(1.4)  # Simulated LLM thinking/streaming window
        precog_v_ms, precog_v = _post("/v1/agent/commit-verify", {"repo": str(trepo), "files": ["pkg/m.py"], "run_tests": True, "use_cache": True})

        # 3. Surgeon RAM Format Gate blocking broken TOML before touching disk
        gate_ms, gate_res = _post(
            "/v1/agent/atomic-patch",
            {
                "repo": str(trepo),
                "edits": [{"path": "cfg.toml", "target": 'cmd = "C:\\\\Python311\\\\python.exe"', "replacement": 'cmd = "C:\\Program Files\\py.exe"'}],
                "run_tests": False,
            },
        )

        # 4. Telepathy Capsule & Live Bootstrap
        cap_ms, cap_res = _post(
            "/v1/agent/capsule",
            {"action": "create", "repo": str(trepo), "agent_id": "antigravity", "summary": "Bench verified", "focus_files": ["pkg/m.py"], "focus_symbols": ["add"], "include_git": False},
        )
        cap_load_ms, _ = _post("/v1/agent/capsule", {"action": "load", "capsule_id": cap_res["capsule_id"]})
        bs_ms, bs_res = _post("/v1/agent/bootstrap", {"repo": str(REPO), "agent_id": "antigravity"})

    beacon = _get("/.well-known/chimera.json")
    stats = _get("/v1/agent/probe-stats")

    report = {
        "benchmark": "CHIMERA_SYMBIONT_END_TO_END_AB",
        "stage_a_slow_commands_12ops": {
            "legacy_powershell_ms": ps_total_ms,
            "legacy_ps_per_cmd_ms": ps_times,
            "legacy_ps_spawns": 12,
            "legacy_ok": ps_ok,
            "legacy_stdout_bytes": ps_bytes,
            "http_xray_batch_ms": http_ms,
            "http_engine_ms": http_res.get("elapsed_ms"),
            "http_ok": http_res.get("ok_count"),
            "http_speedup_x": round(ps_total_ms / max(0.1, http_ms), 1),
            "mcp_stdio_cold_init_ms": mcp_cold_init_ms,
            "mcp_stdio_warm_12op_ms": mcp_warm_12op_ms,
            "mcp_warm_speedup_x": round(ps_total_ms / max(0.1, mcp_warm_12op_ms), 1),
            "mcp_wire_bytes": mcp_wire_bytes,
            "mcp_spill_shield_ok_under_8600B": mcp_spill_safe,
        },
        "stage_b_outline_vs_full_read": {
            "three_large_files_raw_bytes": full_bytes,
            "outline_batch_bytes": outline_bytes,
            "outline_batch_ms": out_ms,
            "bytes_reduction_pct": round((1.0 - outline_bytes / max(1, full_bytes)) * 100.0, 1),
        },
        "stage_c_ast_index_speed": {
            "files_indexed": cg_cold.get("files_indexed"),
            "callgraph_cold_ms": cg_cold_ms,
            "callgraph_warm_ms": cg_warm_ms,
            "incremental_single_file_ast_ms": inc_ms,
            "incremental_vs_cold_x": round(cg_cold_ms / max(0.1, inc_ms), 1),
        },
        "stage_d_precog_shadow_verify": {
            "sync_commit_verify_ms": sync_v_ms,
            "precog_shadow_scheduled": p_trig.get("shadow_scheduled"),
            "precog_commit_verify_ms": precog_v_ms,
            "precog_hit": bool(precog_v.get("precog_hit")),
            "verify_wait_speedup_x": round(sync_v_ms / max(0.1, precog_v_ms), 1),
        },
        "stage_e_surgeon_capsule_bootstrap": {
            "ram_toml_gate_ms": gate_ms,
            "ram_toml_gate_blocked": bool(gate_res.get("gate_rejected")),
            "ram_toml_disk_touched": bool(gate_res.get("disk_touched")),
            "capsule_create_ms": cap_ms,
            "capsule_load_ms": cap_load_ms,
            "capsule_est_tokens": cap_res.get("est_tokens"),
            "repo_bootstrap_ms": bs_ms,
            "repo_bootstrap_bytes": bs_res.get("bytes"),
        },
        "daemon_health": {
            "pid": beacon.get("pid"),
            "ram_mb": (beacon.get("zero_weight") or {}).get("daemon_ram_mb"),
            "zero_weight_ok": (beacon.get("zero_weight") or {}).get("zero_weight_ok"),
            "probe_stats": stats,
        },
    }
    OUT_JSON.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
