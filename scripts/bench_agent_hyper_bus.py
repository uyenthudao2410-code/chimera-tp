"""Reproducible A/B benchmark: Legacy Sequential PowerShell Agent Probes vs CHIMERA Zero-Spawn Agent Hyper-Bus."""

from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.request
from pathlib import Path
from typing import Any

REPO = Path(r"E:\DEV\chimera-tp")
ANCHOR = "http://127.0.0.1:9780"
NO_WIN = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


def _http_post(url: str, body: dict[str, Any], timeout: float = 60.0) -> dict[str, Any]:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with opener.open(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _http_get(url: str, timeout: float = 10.0) -> dict[str, Any]:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def run_benchmark() -> dict[str, Any]:
    # 12 real operations modeled directly after the Codex/Antigravity screenshots
    legacy_ps_cmds = [
        "Get-Content -Encoding UTF8 chimera_tp/native.py | Select-Object -Skip 636 -First 46",
        "Get-Content -Encoding UTF8 chimera_tp/autopilot.py | Select-Object -Skip 1000 -First 20",
        "$s=Get-Content -Encoding UTF8 chimera_tp/dashboard.py; $s[594..645]; $s[1133..1174]",
        "Get-Content -Encoding UTF8 chimera_tp/platform/work_admission.py | Select-Object -Skip 37 -First 35",
        "Get-Content -Encoding UTF8 chimera_tp/platform/substrate.py | Select-Object -Skip 496 -First 20",
        "Select-String -Path chimera_tp/dashboard.py -Pattern 'def handle_|def do_GET|def do_POST' | Select-Object -First 20",
        "Select-String -Path chimera_tp/platform/vault_sql.py -Pattern 'def (snapshot|export|query)' | Select-Object -First 20",
        "Select-String -Path chimera_tp/platform/substrate.py -Pattern 'capability_version|package_version' | Select-Object -First 20",
        "Select-String -Path chimera_tp/platform/mcp_server.py -Pattern 'chimera_xray_batch|chimera_callgraph_slice' | Select-Object -First 20",
        "Get-ChildItem chimera_tp -Recurse -File -Filter *.py | Select-Object -ExpandProperty FullName",
        "(Invoke-RestMethod 'http://127.0.0.1:9780/.well-known/chimera.json' -TimeoutSec 4).cartridges | ConvertTo-Json -Compress",
        "git status --porcelain=v1 -b | Select-Object -First 30",
    ]

    xray_ops = [
        {"id": "native_slice", "op": "file_slice", "path": "chimera_tp/native.py", "skip": 636, "first": 46},
        {"id": "autopilot_slice", "op": "file_slice", "path": "chimera_tp/autopilot.py", "skip": 1000, "first": 20},
        {"id": "dash_ranges", "op": "file_slice", "path": "chimera_tp/dashboard.py", "ranges": [[595, 646], [1134, 1175]]},
        {"id": "admit_slice", "op": "file_slice", "path": "chimera_tp/platform/work_admission.py", "skip": 37, "first": 35},
        {"id": "sub_slice", "op": "file_slice", "path": "chimera_tp/platform/substrate.py", "skip": 496, "first": 20},
        {"id": "rg_dash", "op": "regex_search", "path": "chimera_tp/dashboard.py", "pattern": r"def handle_|def do_GET|def do_POST", "max_hits": 20},
        {"id": "rg_vault", "op": "regex_search", "path": "chimera_tp/platform/vault_sql.py", "pattern": r"def (snapshot|export|query)", "max_hits": 20},
        {"id": "rg_ver", "op": "regex_search", "path": "chimera_tp/platform/substrate.py", "pattern": r"capability_version|package_version", "max_hits": 20},
        {"id": "rg_mcp", "op": "regex_search", "path": "chimera_tp/platform/mcp_server.py", "pattern": r"chimera_xray_batch|chimera_callgraph_slice", "max_hits": 20},
        {"id": "ls_py", "op": "list_files", "path": "chimera_tp", "glob": "*.py", "limit": 200},
        {"id": "http_beacon", "op": "http_get", "url": f"{ANCHOR}/.well-known/chimera.json", "jpath": "cartridges"},
        {"id": "git_st", "op": "git_status", "path": ".", "limit": 30},
    ]

    # A. Legacy Sequential PowerShell Execution (12 separate shells)
    ps_times: list[float] = []
    ps_raw_bytes = 0
    ps_ok = 0
    t_ps0 = time.perf_counter()
    for cmd in legacy_ps_cmds:
        ts = time.perf_counter()
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd],
            cwd=str(REPO),
            capture_output=True,
            text=True,
            timeout=20.0,
            creationflags=NO_WIN,
        )
        ps_times.append(round((time.perf_counter() - ts) * 1000.0, 2))
        ps_raw_bytes += len((proc.stdout or "").encode("utf-8", errors="replace"))
        if proc.returncode == 0:
            ps_ok += 1
    ps_total_ms = round((time.perf_counter() - t_ps0) * 1000.0, 2)

    # B. CHIMERA-HYPER-AGENT-BUS Single-Shot X-Ray Batch (0 PowerShell spawns)
    t_xb0 = time.perf_counter()
    xb = _http_post(f"{ANCHOR}/v1/agent/xray-batch", {"ops": xray_ops, "cwd": str(REPO), "max_workers": 8, "compact": True})
    xb_http_ms = round((time.perf_counter() - t_xb0) * 1000.0, 2)
    xb_bytes = len(json.dumps(xb).encode("utf-8"))

    # C. Callgraph Telepathy across entire 108-module codebase (cold + warm)
    t_cg1 = time.perf_counter()
    cg_cold = _http_post(
        f"{ANCHOR}/v1/agent/callgraph-slice",
        {"repo": str(REPO), "symbol": "handle_mcp_request", "depth": 2, "include_tests": True, "max_chars": 4200},
    )
    cg_cold_ms = round((time.perf_counter() - t_cg1) * 1000.0, 2)

    t_cg2 = time.perf_counter()
    cg_warm = _http_post(
        f"{ANCHOR}/v1/agent/callgraph-slice",
        {"repo": str(REPO), "symbol": "handle_mcp_request", "depth": 2, "include_tests": True, "max_chars": 4200},
    )
    cg_warm_ms = round((time.perf_counter() - t_cg2) * 1000.0, 2)

    # D. Atomic Commit-Verify (cold vs BLAKE2s memoized cache hit)
    t_v1 = time.perf_counter()
    v_cold = _http_post(
        f"{ANCHOR}/v1/agent/commit-verify",
        {"repo": str(REPO), "files": ["chimera_tp/platform/agent_probe.py"], "run_tests": True, "max_tests": 1},
    )
    v_cold_ms = round((time.perf_counter() - t_v1) * 1000.0, 2)

    t_v2 = time.perf_counter()
    v_warm = _http_post(
        f"{ANCHOR}/v1/agent/commit-verify",
        {"repo": str(REPO), "files": ["chimera_tp/platform/agent_probe.py"], "run_tests": True, "max_tests": 1},
    )
    v_warm_ms = round((time.perf_counter() - t_v2) * 1000.0, 2)

    pulse = _http_get(f"{ANCHOR}/api/pulse")
    stats = _http_get(f"{ANCHOR}/v1/agent/probe-stats")

    report = {
        "benchmark": "CHIMERA_AGENT_HYPER_BUS_AB",
        "ops_compared": len(xray_ops),
        "legacy_powershell": {
            "total_ms": ps_total_ms,
            "per_cmd_ms": ps_times,
            "powershell_spawns": len(legacy_ps_cmds),
            "llm_turns_needed_serial": len(legacy_ps_cmds),
            "ok_count": ps_ok,
            "stdout_bytes": ps_raw_bytes,
        },
        "chimera_xray_batch": {
            "http_roundtrip_ms": xb_http_ms,
            "engine_elapsed_ms": xb.get("elapsed_ms"),
            "powershell_spawns": xb.get("powershell_spawns", 0),
            "llm_turns_needed": 1,
            "ok_count": xb.get("ok_count"),
            "payload_bytes": xb_bytes,
            "speedup_x": round(ps_total_ms / max(0.5, xb_http_ms), 1),
        },
        "callgraph_telepathy": {
            "symbol": "handle_mcp_request",
            "files_indexed": cg_cold.get("files_indexed"),
            "cold_ms": cg_cold_ms,
            "warm_ms": cg_warm_ms,
            "callees": len(cg_warm.get("callees") or []),
            "callers": len(cg_warm.get("callers") or []),
            "related_tests": len(cg_warm.get("related_tests") or []),
            "chars_used": cg_warm.get("chars_used"),
        },
        "commit_verify": {
            "cold_ms": v_cold_ms,
            "warm_cache_hit_ms": v_warm_ms,
            "cache_hit": v_warm.get("cache_hit"),
            "cache_speedup_x": round(v_cold_ms / max(0.5, v_warm_ms), 1),
            "tests_ran": (v_cold.get("tests") or {}).get("tests"),
            "ok": v_cold.get("ok"),
            "token_diet": (v_cold.get("tests") or {}).get("token_diet"),
        },
        "daemon_ram_mb": (pulse.get("zero_weight") or {}).get("daemon_ram_mb"),
        "probe_stats": stats,
    }

    out_path = REPO / "tasks" / "agent_hyper_bus_ab.json"
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return report


if __name__ == "__main__":
    run_benchmark()
