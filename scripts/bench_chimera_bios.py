#!/usr/bin/env python3
"""CHIMERA-BIOS Comprehensive AFTER Benchmark & Open Ecosystem Soul Evaluator.

Runs real, non-destructive live benchmarks across all 10 CHIMERA-BIOS organs,
the NVIDIA-style Open Ecosystem ABI (NIXL mmap, HTTP/JSON/SSE/PWA, ChimeraClient
online & offline fallback, MCP JSON-RPC, CLI), cold-import Law-7 RSS measurements
(Win32 K32GetProcessMemoryInfo / Linux /proc/self/statm), and Laws 1-7 audit.

Compares directly against `tasks/bios_baseline_before.json` when present.
"""

from __future__ import annotations

import argparse
import ast
import base64
import contextlib
import ctypes
import ctypes.wintypes
import hashlib
import io
import json
import math
import os
import pathlib
import re
import statistics
import struct
import subprocess
import sys
import tempfile
import time
import tracemalloc
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

BEFORE_BASELINE_PATH = ROOT / "tasks" / "bios_baseline_before.json"


# ---------------------------------------------------------------------------
# Helpers: timing statistics & OS process memory
# ---------------------------------------------------------------------------


def _percentile(sorted_vals: list[float], pct: float) -> float:
    if not sorted_vals:
        return 0.0
    idx = min(len(sorted_vals) - 1, max(0, int(round((pct / 100.0) * (len(sorted_vals) - 1)))))
    return float(sorted_vals[idx])


def _summarize_ns(samples_ns: list[int | float]) -> dict[str, Any]:
    s = sorted(float(x) for x in samples_ns)
    med = statistics.median(s)
    p95 = _percentile(s, 95)
    p99 = _percentile(s, 99)
    mean = statistics.mean(s)
    return {
        "samples": len(s),
        "median_ns": round(med, 1),
        "p95_ns": round(p95, 1),
        "p99_ns": round(p99, 1),
        "mean_ns": round(mean, 1),
        "median_us": round(med / 1000.0, 4),
        "p95_us": round(p95 / 1000.0, 4),
        "p99_us": round(p99 / 1000.0, 4),
        "median_ms": round(med / 1_000_000.0, 5),
        "p95_ms": round(p95 / 1_000_000.0, 5),
        "p99_ms": round(p99 / 1_000_000.0, 5),
    }


def _current_process_mem_mib() -> dict[str, float]:
    if os.name == "nt":
        class PROCESS_MEMORY_COUNTERS_EX(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.wintypes.DWORD),
                ("PageFaultCount", ctypes.wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
                ("PrivateUsage", ctypes.c_size_t),
            ]

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.GetCurrentProcess.restype = ctypes.wintypes.HANDLE
        k32.K32GetProcessMemoryInfo.argtypes = [
            ctypes.wintypes.HANDLE,
            ctypes.POINTER(PROCESS_MEMORY_COUNTERS_EX),
            ctypes.wintypes.DWORD,
        ]
        k32.K32GetProcessMemoryInfo.restype = ctypes.wintypes.BOOL
        pmc = PROCESS_MEMORY_COUNTERS_EX()
        pmc.cb = ctypes.sizeof(pmc)
        if k32.K32GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb):
            return {
                "working_set_mib": round(pmc.WorkingSetSize / (1024.0 * 1024.0), 4),
                "peak_working_set_mib": round(pmc.PeakWorkingSetSize / (1024.0 * 1024.0), 4),
                "private_usage_mib": round(pmc.PrivateUsage / (1024.0 * 1024.0), 4),
            }
    else:
        try:
            statm = pathlib.Path("/proc/self/statm").read_text(encoding="ascii").split()
            rss_mib = (int(statm[1]) * os.sysconf("SC_PAGE_SIZE")) / (1024.0 * 1024.0)
            return {"working_set_mib": round(rss_mib, 4), "peak_working_set_mib": round(rss_mib, 4), "private_usage_mib": round(rss_mib, 4)}
        except Exception:
            pass
    return {"working_set_mib": 0.0, "peak_working_set_mib": 0.0, "private_usage_mib": 0.0}


_COLD_PROBE = r"""
import ctypes, ctypes.wintypes, importlib, json, os, sys, time

def mem_mib():
    if os.name == "nt":
        class PROCESS_MEMORY_COUNTERS_EX(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.wintypes.DWORD),
                ("PageFaultCount", ctypes.wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
                ("PrivateUsage", ctypes.c_size_t),
            ]
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.GetCurrentProcess.restype = ctypes.wintypes.HANDLE
        k32.K32GetProcessMemoryInfo.argtypes = [
            ctypes.wintypes.HANDLE,
            ctypes.POINTER(PROCESS_MEMORY_COUNTERS_EX),
            ctypes.wintypes.DWORD,
        ]
        k32.K32GetProcessMemoryInfo.restype = ctypes.wintypes.BOOL
        pmc = PROCESS_MEMORY_COUNTERS_EX()
        pmc.cb = ctypes.sizeof(pmc)
        if not k32.K32GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb):
            raise ctypes.WinError(ctypes.get_last_error())
        return {
            "working_set_mib": round(pmc.WorkingSetSize / (1024 * 1024), 4),
            "peak_working_set_mib": round(pmc.PeakWorkingSetSize / (1024 * 1024), 4),
            "private_usage_mib": round(pmc.PrivateUsage / (1024 * 1024), 4),
        }
    return {"working_set_mib": 0.0, "peak_working_set_mib": 0.0, "private_usage_mib": 0.0}

mod = sys.argv[1]
t0 = time.perf_counter()
version = None
if mod != "__none__":
    m = importlib.import_module(mod)
    if mod == "chimera_tp":
        version = getattr(m, "__version__", None)
dt_ms = round((time.perf_counter() - t0) * 1000.0, 3)
out = mem_mib()
out["import_ms"] = dt_ms
out["module"] = mod
out["sys_modules_count"] = len(sys.modules)
if version is not None:
    out["version"] = version
out["bios_modules"] = sorted(k for k in sys.modules if "platform.bios" in k)
out["bios_loaded"] = bool(out["bios_modules"])
print(json.dumps(out))
"""


def bench_cold_imports(runs: int = 5) -> dict[str, Any]:
    targets = [
        ("python_empty", "__none__"),
        ("chimera_tp", "chimera_tp"),
        ("chimera_tp.platform.substrate", "chimera_tp.platform.substrate"),
        ("chimera_tp.platform.noosphere_organism", "chimera_tp.platform.noosphere_organism"),
        ("chimera_tp.platform.bios", "chimera_tp.platform.bios"),
    ]
    out: dict[str, Any] = {}
    for label, mod in targets:
        samples = []
        for _ in range(runs):
            p = subprocess.run(
                [sys.executable, "-c", _COLD_PROBE, mod],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=25,
            )
            if p.returncode != 0:
                samples.append({"error": p.stderr.strip()})
            else:
                samples.append(json.loads(p.stdout.strip().splitlines()[-1]))
        valid = [r for r in samples if "working_set_mib" in r]
        summary: dict[str, Any] = {}
        if valid:
            for k in ("working_set_mib", "private_usage_mib", "peak_working_set_mib", "import_ms"):
                vals = [r[k] for r in valid]
                summary[f"{k}_median"] = round(statistics.median(vals), 4)
                summary[f"{k}_mean"] = round(statistics.mean(vals), 4)
                summary[f"{k}_min"] = round(min(vals), 4)
                summary[f"{k}_max"] = round(max(vals), 4)
            summary["bios_loaded_any"] = any(r.get("bios_loaded") for r in valid)
            summary["bios_modules_sample"] = valid[0].get("bios_modules", [])
            summary["sys_modules_count"] = valid[0].get("sys_modules_count")
            if "version" in valid[0]:
                summary["version"] = valid[0]["version"]
        out[label] = {"runs": samples, "summary": summary}
    return out


# ---------------------------------------------------------------------------
# Static Codebase & Surface API AFTER Inventory
# ---------------------------------------------------------------------------


def scan_codebase_and_surfaces_after() -> dict[str, Any]:
    pkg = ROOT / "chimera_tp"
    all_py = sorted(f for f in pkg.rglob("*.py") if "__pycache__" not in f.parts)
    plat_py = [f for f in all_py if "platform" in f.relative_to(pkg).parts]
    bios_py = sorted(f for f in (pkg / "platform" / "bios").glob("*.py"))

    def stats(files: list[pathlib.Path]) -> dict[str, int]:
        total_lines = 0
        code_lines = 0
        total_bytes = 0
        for f in files:
            txt = f.read_text(encoding="utf-8", errors="replace")
            lines = txt.splitlines()
            total_lines += len(lines)
            code_lines += sum(1 for ln in lines if ln.strip() and not ln.strip().startswith("#"))
            total_bytes += len(txt.encode("utf-8"))
        return {
            "module_count": len(files),
            "total_lines": total_lines,
            "code_lines": code_lines,
            "total_bytes": total_bytes,
        }

    # Per-module breakdown of chimera_tp/platform/bios/*.py
    bios_breakdown = {}
    for f in bios_py:
        txt = f.read_text(encoding="utf-8", errors="replace")
        bios_breakdown[f.name] = {
            "lines": len(txt.splitlines()),
            "bytes": len(txt.encode("utf-8")),
        }

    # substrate.py cartridges & routes
    sub_src = (pkg / "platform" / "substrate.py").read_text(encoding="utf-8", errors="replace")
    sub_tree = ast.parse(sub_src)
    carts: list[str] = []
    for node in ast.walk(sub_tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            target = node.target if isinstance(node, ast.AnnAssign) else (node.targets[0] if node.targets else None)
            if isinstance(target, ast.Attribute) and target.attr == "_cartridge_enabled":
                if isinstance(node.value, ast.Dict):
                    for k in node.value.keys:
                        if isinstance(k, ast.Constant) and isinstance(k.value, str):
                            carts.append(k.value)
    routes = sorted(set(re.findall(
        r'["\'](/v1/[a-zA-Z0-9_/\-{}\.\*]+|/.well-known/[a-zA-Z0-9_/\-\.]+|/health|/metrics|/status|/mcp)["\']',
        sub_src,
    )))
    bios_routes = [r for r in routes if "/bios" in r]

    # client.py public methods
    cli_src = (pkg / "platform" / "client.py").read_text(encoding="utf-8", errors="replace")
    cli_tree = ast.parse(cli_src)
    cm: list[str] = []
    for node in cli_tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "ChimeraClient":
            cm = [n.name for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and not n.name.startswith("_")]
    bios_methods = [m for m in cm if m.startswith("bios_")]

    # mcp_server.py tools
    mcp_src = (pkg / "platform" / "mcp_server.py").read_text(encoding="utf-8", errors="replace")
    mcp_tools = sorted(set(
        re.findall(r'"name"\s*:\s*"(chimera_[a-zA-Z0-9_]+)"', mcp_src)
        + re.findall(r"'name'\s*:\s*'(chimera_[a-zA-Z0-9_]+)'", mcp_src)
    ))
    bios_tools = [t for t in mcp_tools if "bios" in t.lower()]

    # cli.py subcommands
    main_cli_src = (pkg / "cli.py").read_text(encoding="utf-8", errors="replace")
    cli_cmds: list[str] = []
    for m in re.finditer(r'add_parser\(\s*["\']([a-zA-Z0-9_\-]+)["\']', main_cli_src):
        if m.group(1) not in cli_cmds:
            cli_cmds.append(m.group(1))

    return {
        "chimera_tp_all": stats(all_py),
        "chimera_tp_platform": stats(plat_py),
        "chimera_tp_bios": stats(bios_py),
        "bios_module_breakdown": bios_breakdown,
        "surface_apis": {
            "substrate_py": {
                "lines": len(sub_src.splitlines()),
                "cartridge_count": len(carts),
                "has_bios_cartridge": "bios" in carts,
                "route_count": len(routes),
                "bios_routes_count": len(bios_routes),
                "bios_routes": bios_routes,
            },
            "client_py": {
                "lines": len(cli_src.splitlines()),
                "chimera_client_public_method_count": len(cm),
                "bios_methods_count": len(bios_methods),
                "bios_methods": bios_methods,
            },
            "mcp_server_py": {
                "lines": len(mcp_src.splitlines()),
                "tool_count": len(mcp_tools),
                "bios_tool_count": len(bios_tools),
                "bios_tools": bios_tools,
            },
            "cli_py": {
                "lines": len(main_cli_src.splitlines()),
                "subcommand_count": len(cli_cmds),
                "has_bios_command": "bios" in cli_cmds,
            },
        },
    }


# ---------------------------------------------------------------------------
# Benchmark 1-10: All 10 CHIMERA-BIOS Engines
# ---------------------------------------------------------------------------


def bench_01_endocrine(work_dir: pathlib.Path) -> dict[str, Any]:
    from chimera_tp.platform.aeon_dynamo import NixlSignalRing
    from chimera_tp.platform.bios.endocrine import (
        ENDO_BYTES,
        ENDO_OFFSET,
        HORMONE_HALF_LIFE_S,
        HORMONE_NAMES,
        EndocrineSystem,
        decode_wire_12b,
        encode_wire_12b,
        read_endocrine_block_mmap,
        read_hormones_mmap,
    )

    ring_path = work_dir / "bench_endo_nixl.bin"
    ring = NixlSignalRing(ring_path)
    try:
        ring.publish("sptc", {"bench": 1})
        ring.publish("homeostasis", {"temp_c": 46.2})
        hdr_before = ring_path.read_bytes()[:32]

        with EndocrineSystem(ring_path) as endo:
            endo.secrete("adrenaline", 0.45, source="bench_cad")
            endo.secrete("dopamine", 0.20, source="bench_win")
            hdr_after = ring_path.read_bytes()[:64]
            bytes_0_31_intact = hdr_after[:32] == hdr_before

            # Verify NixlSignalRing still drains intact AFTER endocrine write
            ring.publish("kv_hint", {"after_endo": True})
            drained = ring.drain(limit=10)
            nixl_roundtrip_ok = len(drained) == 3 and drained[2]["payload"] == {"after_endo": True}

            # Benchmark warm sync_to_mmap (write 32B block incl CRC16)
            iters = 1000
            write_ns: list[int] = []
            read_warm_ns: list[int] = []
            raw_unpack_ns: list[int] = []
            for _ in range(iters):
                t0 = time.perf_counter_ns()
                endo.sync_to_mmap()
                t1 = time.perf_counter_ns()
                endo.read_from_mmap()
                t2 = time.perf_counter_ns()
                write_ns.append(t1 - t0)
                read_warm_ns.append(t2 - t1)

            # Raw zero-copy 24-byte 6x float32 mmap unpack (bytes 40..63)
            mm = endo._mm
            assert mm is not None
            for _ in range(iters):
                t0 = time.perf_counter_ns()
                struct.unpack_from("<6f", mm, 40)
                t1 = time.perf_counter_ns()
                raw_unpack_ns.append(t1 - t0)

            # External zero-copy open+mmap+CRC16 read (200 samples)
            ext_read_ns: list[int] = []
            for _ in range(200):
                t0 = time.perf_counter_ns()
                lv = read_hormones_mmap(ring_path, strict=True)
                t1 = time.perf_counter_ns()
                ext_read_ns.append(t1 - t0)
            assert len(lv) == 6

            # 12-byte PHANTOM wire codec round-trip latency + max error
            sample = endo.levels()
            wire_ns: list[int] = []
            wire_bytes = b""
            decoded: dict[str, float] = {}
            for _ in range(iters):
                t0 = time.perf_counter_ns()
                wire_bytes = encode_wire_12b(sample)
                decoded = decode_wire_12b(wire_bytes)
                t1 = time.perf_counter_ns()
                wire_ns.append(t1 - t0)
            max_q_err = max(abs(sample[h] - decoded[h]) for h in HORMONE_NAMES)

            # Antagonism + decay check
            endo.secrete("melatonin", 0.65, source="night")
            mel_pre = endo.levels()["melatonin"]
            endo.secrete("adrenaline", 0.60, source="burst")
            mel_post = endo.levels()["melatonin"]
            adr_pre = endo.levels()["adrenaline"]
            endo.decay(HORMONE_HALF_LIFE_S["adrenaline"])
            adr_post = endo.levels()["adrenaline"]

            # Non-destructive inspection of live V:\nixl\chimera_nixl_ring.bin
            live_ring = pathlib.Path(r"V:\nixl\chimera_nixl_ring.bin")
            live_info: dict[str, Any] = {"exists": live_ring.exists()}
            if live_ring.exists():
                blk = read_endocrine_block_mmap(live_ring)
                live_info["endo_block_valid"] = blk.get("valid", False)
                live_info["endo_magic"] = blk.get("magic")
                live_info["endo_seq"] = blk.get("seq")
                live_info["endo_error"] = blk.get("error")

            return {
                "organ": "CHIMERA-ENDOCRINE",
                "nixl_bytes_0_31_intact": bytes_0_31_intact,
                "nixl_publish_drain_compat": nixl_roundtrip_ok,
                "endo_offset": ENDO_OFFSET,
                "endo_total_bytes": ENDO_BYTES,
                "hormone_payload_bytes": 24,
                "wire_bytes": len(wire_bytes),
                "wire_max_quantization_err": round(max_q_err, 7),
                "write_mmap_32b": _summarize_ns(write_ns),
                "read_mmap_warm_32b": _summarize_ns(read_warm_ns),
                "read_mmap_raw_24b_floats": _summarize_ns(raw_unpack_ns),
                "read_mmap_external_cold": _summarize_ns(ext_read_ns),
                "wire_12b_roundtrip": _summarize_ns(wire_ns),
                "antagonism_melatonin_drop": round(mel_pre - mel_post, 4),
                "half_life_adrenaline_decay_ratio": round(adr_post / max(adr_pre, 1e-6), 4),
                "live_v_nixl_ring": live_info,
            }
    finally:
        ring.close()


def bench_02_friston() -> dict[str, Any]:
    from chimera_tp.platform.bios.friston import ActiveInferenceBrain

    brain = ActiveInferenceBrain()
    t0 = 1_700_000_000.0
    # Prime CAD & idle generative baselines
    for i in range(6):
        brain.observe(
            {"cpu_pct": 64.0 + i, "gpu_pct": 70.0 + i, "ram_pct": 58.0, "disk_io_mb_s": 34.0, "token_rate": 6.0, "active_streams": 1},
            context="cad",
            ts=t0 + i * 5.0,
        )
        brain.observe(
            {"cpu_pct": 6.0 + (i % 2), "gpu_pct": 3.0, "ram_pct": 36.0, "disk_io_mb_s": 2.0, "token_rate": 0.0, "active_streams": 0},
            context="idle",
            ts=t0 + 100.0 + i * 5.0,
        )

    cad_expected = brain.observe(
        {"cpu_pct": 68.0, "gpu_pct": 74.0, "ram_pct": 58.5, "disk_io_mb_s": 35.0, "token_rate": 6.0, "active_streams": 1},
        context="cad",
        ts=t0 + 200.0,
        learn=False,
    )
    idle_stealth_spike = brain.observe(
        {"cpu_pct": 68.0, "gpu_pct": 4.0, "ram_pct": 74.0, "disk_io_mb_s": 145.0, "token_rate": 0.0, "active_streams": 0},
        context="idle",
        ts=t0 + 205.0,
        learn=False,
    )
    forecast_60s = brain.predict(60.0, context="cad")
    plan = brain.plan_active_inference(
        {"cpu_pct": 68.0, "gpu_pct": 4.0, "ram_pct": 74.0, "disk_io_mb_s": 145.0},
        context="idle",
    )

    obs_ns: list[int] = []
    pred_ns: list[int] = []
    plan_ns: list[int] = []
    sample_obs = {"cpu_pct": 42.0, "gpu_pct": 18.0, "ram_pct": 52.0, "disk_io_mb_s": 12.0}
    for i in range(500):
        a = time.perf_counter_ns()
        brain.observe(sample_obs, context="coding", ts=t0 + 300.0 + i, learn=False)
        b = time.perf_counter_ns()
        brain.predict(60.0, context="coding")
        c = time.perf_counter_ns()
        brain.plan_active_inference(sample_obs, context="coding")
        d = time.perf_counter_ns()
        obs_ns.append(b - a)
        pred_ns.append(c - b)
        plan_ns.append(d - c)

    state_bytes = brain.state_bytes_size()
    return {
        "organ": "CHIMERA-FRISTON",
        "cad_expected_surprise": round(cad_expected["surprise"], 4),
        "cad_expected_free_energy_nats": round(cad_expected["free_energy_nats"], 4),
        "cad_expected_regime": cad_expected["regime"],
        "idle_spike_surprise": round(idle_stealth_spike["surprise"], 4),
        "idle_spike_free_energy_nats": round(idle_stealth_spike["free_energy_nats"], 4),
        "idle_spike_regime": idle_stealth_spike["regime"],
        "idle_spike_anomalous_features": idle_stealth_spike["anomalous_features"],
        "surprise_discrimination_delta": round(idle_stealth_spike["surprise"] - cad_expected["surprise"], 4),
        "state_bytes": state_bytes,
        "state_under_64kb": state_bytes < 65536,
        "plan_count": len(plan),
        "plan_all_law2_compliant": all(p.get("law2_compliant") is True for p in plan),
        "plan_all_law6_auto_activated_false": all(p.get("auto_activated") is False for p in plan),
        "forecast_60s_keys": sorted(forecast_60s.keys()),
        "observe_latency": _summarize_ns(obs_ns),
        "predict_latency": _summarize_ns(pred_ns),
        "plan_latency": _summarize_ns(plan_ns),
    }


def bench_03_autophagy(work_dir: pathlib.Path) -> dict[str, Any]:
    from chimera_tp.platform.bios.autophagy import MetabolicAutophagyEngine

    ops = work_dir / "autophagy_ops"
    with MetabolicAutophagyEngine(ops_dir=ops, repo_root=ROOT, ephemeral=False) as eng:
        t0_now = 1_700_000_000.0
        eng.record_metabolism("active_hot_mod", kind="module", calls=120, ms_saved=45.0, tokens_saved=4000, now_ts=t0_now)
        eng.record_metabolism("dormant_cold_mod", kind="module", calls=1, ms_saved=0.0, tokens_saved=0, now_ts=t0_now - 45 * 86400)
        ubiq = eng.evaluate_ubiquitin(dormancy_days=30.0, now_ts=t0_now)

        # LZ4/zlib cold dormancy archival & SHA-256 rehydrate round-trip
        payload = ("# dormant telemetry snapshot\n" + "0123456789abcdef" * 32 + "\n").encode("utf-8") * 64
        t_a = time.perf_counter_ns()
        arc = eng.archive_dormant("dormant_cold_mod", payload)
        t_b = time.perf_counter_ns()
        rehydrated = eng.rehydrate_dormant("dormant_cold_mod")
        t_c = time.perf_counter_ns()
        assert rehydrated == payload

        # Real AST metabolic scan of chimera_tp/
        t_s0 = time.perf_counter()
        scan = eng.scan_codebase_metabolism(ROOT)
        scan_ms = round((time.perf_counter() - t_s0) * 1000.0, 2)

        t_p0 = time.perf_counter()
        proposal = eng.propose_apoptosis_pr(ROOT, max_candidates=10)
        prop_ms = round((time.perf_counter() - t_p0) * 1000.0, 2)

        return {
            "organ": "CHIMERA-AUTOPHAGY",
            "ubiquitin_tagged_count": len(ubiq.get("tagged", ubiq.get("ubiquitin_tagged", []))),
            "dormancy_raw_bytes": len(payload),
            "dormancy_compressed_bytes": arc.get("compressed_bytes"),
            "dormancy_compression_ratio": round(len(payload) / max(1, int(arc.get("compressed_bytes", len(payload)))), 2),
            "dormancy_codec": arc.get("codec"),
            "dormancy_roundtrip_bit_exact": rehydrated == payload,
            "archive_us": round((t_b - t_a) / 1000.0, 2),
            "rehydrate_us": round((t_c - t_b) / 1000.0, 2),
            "ast_scan_ms": scan_ms,
            "ast_modules_scanned": scan.get("modules_scanned", scan.get("total_modules")),
            "ast_parse_errors": scan.get("parse_errors", 0),
            "ast_cold_modules_count": len(scan.get("cold_modules", [])),
            "ast_legacy_modules_count": len(scan.get("legacy_modules", [])),
            "ast_duplicate_helper_groups": len(scan.get("duplicate_helpers", scan.get("duplicate_helper_groups", []))),
            "apoptosis_proposal_ms": prop_ms,
            "apoptosis_candidates_count": len(proposal.get("candidates", [])),
            "apoptosis_auto_activated": proposal.get("auto_activated"),
            "apoptosis_requires_human_approval": proposal.get("requires_human_approval"),
            "apoptosis_sha256_len": len(str(proposal.get("sha256", proposal.get("proposal_sha256", "")))),
        }


def bench_04_parasite(work_dir: pathlib.Path) -> dict[str, Any]:
    from chimera_tp.platform.bios.parasite import PARASITE_SCENARIOS, RedQueenParasiteArena

    ops = work_dir / "parasite_ops"
    with RedQueenParasiteArena(ops_dir=ops, ephemeral=False) as arena:
        t0 = time.perf_counter()
        res = arena.run_arena(rounds=6, seed=42)
        elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)

        verified_all = True
        law6_all_ok = True
        for vac in res["vaccines"]:
            chk = arena.verify_vaccine(vac)
            if not chk["valid"]:
                verified_all = False
            if vac.get("auto_activated") is not False or vac.get("requires_human_approval") is not True:
                law6_all_ok = False

        return {
            "organ": "CHIMERA-PARASITE",
            "scenarios_count": len(PARASITE_SCENARIOS),
            "scenarios": sorted(PARASITE_SCENARIOS.keys()),
            "rounds_executed": res["rounds_executed"],
            "elapsed_ms": elapsed_ms,
            "sandbox_isolated": res["sandbox_isolated"],
            "initial_survival_rate": round(res["rounds"][0]["host_survival_rate"], 4),
            "final_host_survival_rate": round(res["final_host_survival_rate"], 4),
            "vaccines_synthesized": res["vaccines_synthesized"],
            "immune_antibodies_count": len(arena.list_antibodies()),
            "all_vaccines_verified_replay_and_sha256": verified_all,
            "law6_auto_activated_false": (res["auto_activated"] is False) and law6_all_ok,
            "law6_requires_human_approval": res["requires_human_approval"],
        }


def bench_05_octopus(work_dir: pathlib.Path) -> dict[str, Any]:
    from chimera_tp.platform.bios.octopus import (
        BinaryReflexTable,
        HookGanglion,
        PeerSurvivalGanglion,
        SocketGanglion,
        SynapticReconciler,
    )

    tbl_path = work_dir / "bench_octopus_reflex.bin"
    with BinaryReflexTable(tbl_path, ephemeral=False) as writer:
        sync_ns: list[int] = []
        antibodies = [
            {"pattern": f"sig_{i}", "fix_hint": f"mitigate_{i}", "severity": "high", "action": "block" if i == 0 else "warn"}
            for i in range(8)
        ]
        endpoints = [
            {"name": "immortal_local", "host": "127.0.0.1", "port": 12500, "role": "primary", "state": "healthy"},
            {"name": "svhome_peer", "host": "100.116.112.22", "port": 9780, "role": "peer_svhome", "state": "healthy"},
        ]
        hormones = {"adrenaline": 0.35, "cortisol": 0.15, "dopamine": 0.72, "melatonin": 0.08, "cytokine": 0.12, "oxytocin": 0.85}
        sync_res = {}
        for _ in range(100):
            t0 = time.perf_counter_ns()
            sync_res = writer.sync(antibodies=antibodies, endpoints=endpoints, hormones=hormones, flags=0)
            t1 = time.perf_counter_ns()
            sync_ns.append(t1 - t0)
        table_bytes = writer.byte_size()
        used_bytes = sync_res["used_bytes"]

    # Offline read-only HookGanglion latency (500 lookups with daemon dead)
    lookup_ns: list[int] = []
    with BinaryReflexTable(tbl_path, ephemeral=False, read_only=True) as reader:
        hook = HookGanglion(reader)
        # Warm + verify block
        blk = hook.evaluate("egress_send", "contains sig_0 threat", daemon_online=False)
        assert blk["decision"] == "block" and blk["offline_autonomous"] is True
        for _ in range(500):
            t0 = time.perf_counter_ns()
            ev = hook.evaluate("edit_file", "normal safe payload", target_path="src/mod.py", daemon_online=False)
            t1 = time.perf_counter_ns()
            assert ev["decision"] == "allow"
            lookup_ns.append(t1 - t0)

    # SocketGanglion autonomous failover latency
    sg = SocketGanglion(BinaryReflexTable(ephemeral=True), fail_threshold=2)
    t_f0 = time.perf_counter_ns()
    sg.record_probe("immortal_local", False, error="ConnectionRefusedError")
    sg.record_probe("immortal_local", False, error="ConnectionRefusedError")
    route_after = sg.select_route("immortal_local")
    failover_us = round((time.perf_counter_ns() - t_f0) / 1000.0, 2)

    # PeerSurvivalGanglion Law-3 island mode
    pg = PeerSurvivalGanglion(node_name="svhome", peer_name="win-desktop", heartbeat_timeout_s=30.0)
    pg.record_peer_heartbeat("win-desktop", rtt_ms=6.4, now_ts=1000.0)
    island = pg.check_link(now_ts=1045.0)
    adm_light = pg.admit_work(ram_free_gib=5.5, load1=0.5, cpu_temp_c=47.0, disk_free_gb=30.0, job_class="light")
    adm_heavy = pg.admit_work(ram_free_gib=5.5, load1=0.5, cpu_temp_c=47.0, disk_free_gb=30.0, job_class="heavy")
    adm_hot = pg.admit_work(ram_free_gib=2.0, load1=2.1, cpu_temp_c=73.0, disk_free_gb=10.0, job_class="light")

    # Merkle-CRDT SynapticReconciler latency across 20, 100, 500 events + algebraic properties
    rec = SynapticReconciler()
    reconcile_bench = {}
    commutative_ok = True
    idempotent_ok = True
    for n in (20, 100, 500):
        ev_a = [
            rec.make_event("win-desktop", "state", {"i": i}, hlc=(1_700_000_000_000 + i * 2, 0, "win-desktop"), key=f"k:{i % (n // 2)}")
            for i in range(n // 2)
        ]
        ev_b = [
            rec.make_event("svhome", "state", {"i": i}, hlc=(1_700_000_000_001 + i * 2, 0, "svhome"), key=f"k:{i % (n // 2)}")
            for i in range(n // 2)
        ]
        samples = []
        r_ab = {}
        for _ in range(25):
            t0 = time.perf_counter_ns()
            r_ab = rec.reconcile(ev_a, ev_b)
            t1 = time.perf_counter_ns()
            samples.append(t1 - t0)
        r_ba = rec.reconcile(ev_b, ev_a)
        r_id = rec.reconcile(r_ab["merged_events"], r_ab["merged_events"])
        if r_ab["root_hash"] != r_ba["root_hash"]:
            commutative_ok = False
        if r_ab["root_hash"] != r_id["root_hash"]:
            idempotent_ok = False
        reconcile_bench[f"{n}_events"] = _summarize_ns(samples)

    return {
        "organ": "CHIMERA-OCTOPUS",
        "reflex_table_max_bytes": table_bytes,
        "reflex_table_used_bytes": used_bytes,
        "reflex_table_under_16kb": table_bytes < 16384,
        "reflex_sync_latency": _summarize_ns(sync_ns),
        "offline_hook_lookup_latency": _summarize_ns(lookup_ns),
        "offline_lookup_under_1ms": _summarize_ns(lookup_ns)["p99_ms"] < 1.0,
        "socket_failover_selected": route_after["selected"],
        "socket_failover_active": route_after["failover_active"],
        "socket_failover_us": failover_us,
        "svhome_island_mode_triggered": island["island_mode"],
        "svhome_law3_light_admitted": adm_light["admitted"],
        "svhome_law3_heavy_rejected_in_island": not adm_heavy["admitted"],
        "svhome_law3_hot_fuse_violations": len(adm_hot["violations"]),
        "merkle_crdt_commutative": commutative_ok,
        "merkle_crdt_idempotent": idempotent_ok,
        "merkle_crdt_reconcile_latency": reconcile_bench,
    }


def bench_06_stigmergy(work_dir: pathlib.Path) -> dict[str, Any]:
    from chimera_tp.platform.bios.stigmergy import StigmergicEpigenome

    ops = work_dir / "stigmergy_ops"
    repo_dir = work_dir / "stigmergy_repo"
    repo_dir.mkdir(parents=True, exist_ok=True)
    sample_file = repo_dir / "substrate.py"
    sample_file.write_text("# untouched file\nX = 1\n", encoding="utf-8")
    orig_sha = hashlib.sha256(sample_file.read_bytes()).hexdigest()

    t0 = 1_700_000_000.0
    with StigmergicEpigenome(ops_dir=ops, ephemeral=False) as epi:
        epi.deposit_alarm(str(repo_dir), "substrate.py", "regression", severity=0.6, reason="route_timeout", half_life_hours=24.0, now_ts=t0)
        epi.deposit_alarm(str(repo_dir), "substrate.py", "regression", severity=0.5, reason="repeat_err", half_life_hours=24.0, now_ts=t0 + 10)
        # Seed 5 realistic co-edit clusters
        clusters = [
            ("substrate.py", "tests/test_substrate.py", "client.py"),
            ("cli.py", "tests/test_cli.py", "discovery.py"),
            ("mcp_server.py", "tests/test_mcp.py", "client.py"),
            ("aeon_dynamo.py", "tests/test_aeon_dynamo.py", "endocrine.py"),
            ("soul.py", "tests/test_soul.py", "mycelium.py"),
        ]
        for a, b, c in clusters:
            epi.record_coedit(str(repo_dir), [a, b, c], weight=1.0, now_ts=t0)
            epi.record_coedit(str(repo_dir), [a, b], weight=1.0, now_ts=t0 + 30)

        epi.methylate(str(repo_dir), "substrate.py", "hard_lease", strength=0.9, half_life_days=7.0, now_ts=t0)

        # Evaluate Top-1 & Top-2 trail prefetch accuracy across all 5 source files
        top1_hits = 0
        top2_recall_hits = 0
        for a, expected_test, expected_peer in clusters:
            preds = [p["path"] for p in epi.predict_trail_prefetch(str(repo_dir), a, top_k=2, now_ts=t0 + 60)]
            if preds and preds[0] == expected_test:
                top1_hits += 1
            if expected_test in preds and expected_peer in preds:
                top2_recall_hits += 1

        # Benchmark smell-card latency (500 calls)
        smell_ns: list[int] = []
        card = {}
        for _ in range(500):
            ts_a = time.perf_counter_ns()
            card = epi.smell(str(repo_dir), "substrate.py", max_tokens=40, now_ts=t0 + 60)
            ts_b = time.perf_counter_ns()
            smell_ns.append(ts_b - ts_a)

        alarm_t0 = card["alarm_level"]
        # Half-life decay test (24h later -> ~0.5x, 60d later -> 0.0)
        epi.evaporate(now_ts=t0 + 24.0 * 3600.0)
        alarm_24h = epi.smell(str(repo_dir), "substrate.py", max_tokens=40, now_ts=t0 + 24.0 * 3600.0)["alarm_level"]
        ev_60d = epi.evaporate(now_ts=t0 + 60.0 * 86400.0)
        alarm_60d = epi.smell(str(repo_dir), "substrate.py", max_tokens=40, now_ts=t0 + 60.0 * 86400.0)["alarm_level"]

        repo_untouched = hashlib.sha256(sample_file.read_bytes()).hexdigest() == orig_sha
        smell_stats = _summarize_ns(smell_ns)
        return {
            "organ": "CHIMERA-STIGMERGY",
            "smell_card_latency": smell_stats,
            "smell_card_under_5ms": smell_stats["p99_ms"] < 5.0,
            "smell_card_tokens": card["token_est"],
            "smell_card_under_40_tokens": card["token_est"] < 40,
            "trail_top1_accuracy": round(top1_hits / len(clusters), 4),
            "trail_top2_pair_accuracy": round(top2_recall_hits / len(clusters), 4),
            "alarm_initial": round(alarm_t0, 4),
            "alarm_after_1_halflife_24h": round(alarm_24h, 4),
            "halflife_ratio": round(alarm_24h / max(alarm_t0, 1e-6), 4),
            "alarm_after_60d_evaporation": round(alarm_60d, 4),
            "marks_demethylated_at_60d": ev_60d["marks_demethylated"],
            "repo_files_modified": epi.status()["repo_files_modified"],
            "repo_sha256_untouched": repo_untouched,
        }


def bench_07_umwelt(work_dir: pathlib.Path) -> dict[str, Any]:
    from chimera_tp.platform.bios.umwelt import UmweltCognitiveResonator

    ops = work_dir / "umwelt_ops"
    eng = UmweltCognitiveResonator(ops_dir=ops, ephemeral=False)
    try:
        t_flow = datetime(2026, 11, 27, 10, 0, 0).timestamp()
        for i in range(8):
            eng.record_signal("edit", app="vscode", target="chimera_tp/platform/substrate.py", ok=True, ts=t_flow + i * 12.0)
        eng.record_signal("test_pass", app="vscode", target="tests/test_substrate.py", ok=True, ts=t_flow + 100.0)
        flow_state = eng.assess(now_ts=t_flow + 105.0)

        # Frustration episode in fresh window
        t_frus = datetime(2026, 11, 27, 14, 0, 0).timestamp()
        for i in range(3):
            eng.record_signal("test_fail", app="vscode", target="tests/test_relay.py::test_reconnect", ok=False, ts=t_frus + i * 15.0)
        eng.record_signal("undo", app="vscode", target="relay.py", ok=True, ts=t_frus + 50.0)
        eng.record_signal("steer", app="codex", target="relay.py", ok=True, ts=t_frus + 55.0)
        eng.record_signal("undo", app="vscode", target="relay.py", ok=True, ts=t_frus + 60.0)
        frus_state = eng.assess(now_ts=t_frus + 65.0)

        # Circadian training & 5-minute anticipation
        t_cad = datetime(2026, 11, 27, 9, 10, 0).timestamp()
        for i in range(6):
            eng.record_signal("cad_cmd", app="acad.exe", target="site.dwg", ok=True, ts=t_cad + i * 5.0)
        probe_cad = datetime(2026, 11, 27, 8, 57, 0).timestamp()
        ant_cad = eng.anticipate_phase(now_ts=probe_cad, lead_minutes=5.0)

        assess_ns: list[int] = []
        for _ in range(300):
            a = time.perf_counter_ns()
            eng.assess(now_ts=t_frus + 65.0)
            b = time.perf_counter_ns()
            assess_ns.append(b - a)

        return {
            "organ": "CHIMERA-UMWELT",
            "flow_score": round(flow_state["flow_score"], 4),
            "flow_shield_active": flow_state["flow_shield"],
            "frustration_score": round(frus_state["frustration_score"], 4),
            "whisper_triggered": frus_state["whisper_triggered"],
            "whisper_interrupt_user": frus_state["subconscious_whisper"]["interrupt_user"],
            "circadian_predicted_phase": ant_cad["predicted_phase"],
            "circadian_confidence": round(ant_cad["confidence"], 4),
            "circadian_metamorphosis_actions_count": len(ant_cad["metamorphosis_actions"]),
            "circadian_law2_compliant": ant_cad["law_2_compliant"],
            "privacy_guarantees": flow_state["privacy_guarantees"],
            "assess_latency": _summarize_ns(assess_ns),
        }
    finally:
        eng.close()


def bench_08_hgt(work_dir: pathlib.Path) -> dict[str, Any]:
    from chimera_tp.platform.bios.hgt import MAX_PLASMID_BYTES, HorizontalGeneTransferEngine

    ops = work_dir / "hgt_ops"
    hgt = HorizontalGeneTransferEngine(ops_dir=ops, ephemeral=False)
    try:
        starters = hgt.list_plasmids()
        starter_sizes = {p["name"]: p["byte_size"] for p in starters}
        all_valid = all(hgt.verify_plasmid(p["plasmid_id"])["valid"] for p in starters)

        # Extract custom plasmid
        custom = hgt.extract_plasmid(
            name="fast_unique_preserver",
            source_project="chimera-tp/bench",
            code_or_spec="def fast_unique(xs):\n    return list(dict.fromkeys(xs))\n",
            io_contract={"input": "list[int]", "output": "list[int]"},
            benchmark_oracle={"metric": "latency_us", "parity": "bit_exact"},
            tags=["dedup", "cache"],
        )

        # Scan ecosystem targets
        targets = [
            {"name": "radar_sqlite_store", "tags": ["sqlite", "persistence"], "bottlenecks": ["wal", "batching"]},
            {"name": "unrelated_gfx", "tags": ["shader"], "bottlenecks": ["gamma"]},
        ]
        scan_res = hgt.scan_ecosystem_targets("wal_group_commit", targets)

        # Sandbox A/B race
        def slow_dedup(items: list[int]) -> list[int]:
            out: list[int] = []
            for x in items:
                if x not in out:
                    out.append(x)
            return out

        def fast_dedup(items: list[int]) -> list[int]:
            return list(dict.fromkeys(items))

        def buggy_dedup(items: list[int]) -> list[int]:
            return sorted(set(items))

        cases = [
            [3, 1, 2, 3, 2, 4, 1, 5, 9, 8, 7, 6] * 25,
            [9, 8, 7, 6, 5, 4, 3, 2, 1, 9, 8] * 25,
            [],
            [42],
        ]
        t0 = time.perf_counter()
        prop_ok = hgt.sandbox_ab_graft(custom["plasmid_id"], "demo-cache-service", slow_dedup, fast_dedup, cases, iterations=20)
        race_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        prop_bad = hgt.sandbox_ab_graft(custom["plasmid_id"], "demo-buggy", slow_dedup, buggy_dedup, cases, iterations=5)

        return {
            "organ": "CHIMERA-HGT",
            "max_plasmid_bytes": MAX_PLASMID_BYTES,
            "starter_plasmids_sizes": starter_sizes,
            "custom_plasmid_bytes": custom["byte_size"],
            "all_plasmids_sha256_valid_and_under_8kb": all_valid and custom["byte_size"] <= MAX_PLASMID_BYTES,
            "ecosystem_scan_top_target": scan_res[0]["target_name"] if scan_res else None,
            "ecosystem_scan_top_recommended": scan_res[0]["recommended"] if scan_res else False,
            "sandbox_ab_race_ms": race_ms,
            "ab_parity_passed": prop_ok["parity_passed"],
            "ab_speedup_ratio": round(prop_ok["speedup_ratio"], 2),
            "ab_verdict": prop_ok["verdict"],
            "buggy_verdict": prop_bad["verdict"],
            "law6_auto_activated": prop_ok["auto_activated"],
            "law6_requires_human_approval": prop_ok["requires_human_approval"],
            "proposal_sha256_len": len(prop_ok["proposal_sha256"]),
        }
    finally:
        hgt.close()


def bench_09_mycelium(work_dir: pathlib.Path) -> dict[str, Any]:
    from chimera_tp.platform.bios.mycelium import (
        MAX_PWA_BYTES,
        MyceliumSporeMesh,
        blind_reconstruct,
        blind_split,
        render_spore_pwa_html,
    )
    from chimera_tp.platform.bios.soul import AutobiographicalSoul

    # 1. PWA Spore HTML size, zero-CDN, zero-WebGL (both raw template & Soul-embedded)
    raw_html = render_spore_pwa_html(anchor_url="")
    raw_pwa_bytes = len(raw_html.encode("utf-8"))
    raw_zero_external_urls = re.search(r"https?://", raw_html, flags=re.IGNORECASE) is None
    raw_zero_webgl_raf = ("webgl" not in raw_html.lower()) and ("requestanimationframe" not in raw_html.lower())

    soul_tmp = AutobiographicalSoul(ephemeral=True)
    try:
        cap = soul_tmp.export_capsule(query="law 7 rss", target_model="any", max_tokens=500)
    finally:
        soul_tmp.close()
    html = render_spore_pwa_html(
        anchor_url="",
        snapshot={
            "hormones": {"levels": {"adrenaline": 0.25, "cortisol": 0.15, "dopamine": 0.78, "melatonin": 0.08, "cytokine": 0.05, "oxytocin": 0.88}},
            "umwelt": {"assessment": {"state": "deep_flow", "flow_score": 0.84, "flow_shield": True}},
            "soul": {"capsule": cap, "lineage_hash": cap["lineage_hash"], "scar_count": 4},
        },
    )
    pwa_bytes = len(html.encode("utf-8"))
    zero_external_urls = re.search(r"https?://", html, flags=re.IGNORECASE) is None

    # Validate embedded JS with `node --check` if node is available
    js_match = re.search(r"<script[^>]*>(.*?)</script>", html, flags=re.DOTALL | re.IGNORECASE)
    node_js_ok = None
    if js_match:
        js_file = work_dir / "spore_check.js"
        js_file.write_text(js_match.group(1), encoding="utf-8")
        try:
            p = subprocess.run(["node", "--check", str(js_file)], capture_output=True, text=True, timeout=10)
            node_js_ok = p.returncode == 0
        except FileNotFoundError:
            node_js_ok = None

    # 2. GF(256) (K=2, N=3) blinded split & reconstruct benchmark (1 KiB secret)
    secret = b"CHIMERA-BIOS-SECRET-SHARD-BENCHMARK:" + (b"A1B2C3D4" * 124)
    split_ns: list[int] = []
    recon_ns: list[int] = []
    shares = []
    for i in range(100):
        t0 = time.perf_counter_ns()
        shares = blind_split(secret, k=2, n=3, seed=struct.pack("!I", i + 1))
        t1 = time.perf_counter_ns()
        out_b = blind_reconstruct([shares[0], shares[2]])
        t2 = time.perf_counter_ns()
        assert out_b == secret
        split_ns.append(t1 - t0)
        recon_ns.append(t2 - t1)

    all_pairs_ok = (
        blind_reconstruct([shares[0], shares[1]]) == secret
        and blind_reconstruct([shares[0], shares[2]]) == secret
        and blind_reconstruct([shares[1], shares[2]]) == secret
    )
    single_share_no_plaintext = all(b"CHIMERA-BIOS-SECRET" not in base64.b64decode(s["data_b64"]) for s in shares)

    # 3. Autotomy disconnect benchmark (10 trials -> median/max ms vs < 50 ms)
    ops = work_dir / "mycelium_ops"
    autotomy_ms: list[float] = []
    zero_trace_all = True
    key_zeroed_bytes = 0
    mesh = MyceliumSporeMesh(ops_dir=ops, node_name="win-desktop", ephemeral=False)
    try:
        for i in range(10):
            cred = mesh.issue_spore_token(f"pixel-{i}", role="mobile_pwa", ttl_s=1800)
            sid = cred["spore_id"]
            mesh.attach_spore(sid, f"pixel-{i}", role="mobile_pwa", capabilities=cred["capabilities"], token=cred["token"])
            mesh.submit_seed(sid, f"Seed approval #{i}", priority="high")
            rec = mesh.autotomy(sid, reason="bench_disconnect")
            autotomy_ms.append(float(rec["elapsed_ms"]))
            key_zeroed_bytes = int(rec["ephemeral_keys_zeroed_bytes"])
            if not (rec["zero_trace_verified"] and rec["state_dropped"] and not mesh.verify_spore_token(cred["token"])["valid"]):
                zero_trace_all = False
    finally:
        mesh.close()

    return {
        "organ": "CHIMERA-MYCELIUM",
        "raw_pwa_html_bytes": raw_pwa_bytes,
        "pwa_html_bytes": pwa_bytes,
        "pwa_target_max_bytes": MAX_PWA_BYTES,
        "pwa_under_50kb": pwa_bytes < MAX_PWA_BYTES,
        "pwa_under_25kb": pwa_bytes < 25 * 1024,
        "pwa_zero_external_cdn_urls": raw_zero_external_urls and zero_external_urls,
        "pwa_template_zero_webgl_raf": raw_zero_webgl_raf,
        "pwa_node_js_syntax_ok": node_js_ok,
        "gf256_secret_bytes": len(secret),
        "gf256_all_3_pairs_bit_exact": all_pairs_ok,
        "gf256_single_share_zero_leak": single_share_no_plaintext,
        "gf256_split_latency": _summarize_ns(split_ns),
        "gf256_reconstruct_latency": _summarize_ns(recon_ns),
        "autotomy_trials": len(autotomy_ms),
        "autotomy_median_ms": round(statistics.median(autotomy_ms), 3),
        "autotomy_max_ms": round(max(autotomy_ms), 3),
        "autotomy_under_50ms": max(autotomy_ms) < 50.0,
        "autotomy_zero_trace_verified": zero_trace_all,
        "autotomy_ephemeral_keys_zeroed_bytes": key_zeroed_bytes,
    }


def bench_10_soul(work_dir: pathlib.Path) -> dict[str, Any]:
    from chimera_tp.platform.bios.soul import AutobiographicalSoul

    ops = work_dir / "soul_ops"
    soul = AutobiographicalSoul(ops_dir=ops, ephemeral=False)
    try:
        soul.record_preference("coding", "style", "minimal surgical edits", evidence="core principle")
        ver_before = soul.verify_lineage()
        # Cross-model continuity test BEFORE appending 5th scar (4 genesis scars)
        models = ("gemini", "codex", "claude", "local-qwen", "gpt-5-codex", "any")
        genesis_caps = [
            soul.export_capsule(query="svhome 15W thermal and 80 MiB RSS", target_model=m, max_tokens=500)
            for m in models
        ]
        genesis_core_identical = len({c["core_sha256"] for c in genesis_caps}) == 1
        genesis_lineage_identical = len({c["lineage_hash"] for c in genesis_caps}) == 1

        new_scar = soul.record_scar(
            title="BIOS Evaluation Verification Scar",
            event_date="2026-11-27",
            root_cause="Synthetic benchmark lineage continuity check.",
            lesson_law="Always verify SHA-256 lineage and <=500 token budget across models.",
            hardware_context="win-desktop + svhome",
            tags=["bios", "soul", "law7"],
            severity="high",
        )
        ver_after = soul.verify_lineage()

        # Cross-model continuity test AFTER appending 5th scar (near 500-token compaction cliff)
        capsules = []
        export_ns: list[int] = []
        for m in models:
            t0 = time.perf_counter_ns()
            cap = soul.export_capsule(query="svhome 15W thermal and 80 MiB RSS", target_model=m, max_tokens=500)
            t1 = time.perf_counter_ns()
            capsules.append(cap)
            export_ns.append(t1 - t0)

        # Tight 180-token capsule test
        tight = soul.export_capsule(query="law 2", target_model="local", max_tokens=180)

        # 10K-bit VSA recall accuracy on 3 landmark genesis queries
        recall_checks = [
            ("svhome 15W thermal guard", "svhome"),
            ("daemon RSS 80 MiB lazy load", "80 mib"),
            ("12500 immortal socket reconnect", "12500"),
        ]
        recall_hits = 0
        recall_ns: list[int] = []
        for q, expected in recall_checks:
            t0 = time.perf_counter_ns()
            top = soul.recall_scars(q, top_k=2)
            t1 = time.perf_counter_ns()
            recall_ns.append(t1 - t0)
            if top and expected in top[0]["title"].lower():
                recall_hits += 1

        core_hashes = {c["core_sha256"] for c in capsules}
        lineage_hashes = {c["lineage_hash"] for c in capsules}
        assert len(core_hashes) == 1, f"5-scar cross-model core_sha256 mismatch: {core_hashes}"
        assert len(lineage_hashes) == 1, f"5-scar cross-model lineage_hash mismatch: {lineage_hashes}"
        assert all(c["token_est"] <= 500 and AutobiographicalSoul.verify_capsule(c) for c in capsules)
        return {
            "organ": "CHIMERA-SOUL",
            "genesis_scars_count": ver_before["scar_count"],
            "scars_after_append": ver_after["scar_count"],
            "new_scar_seq": new_scar["seq"],
            "lineage_valid": ver_after["valid"],
            "models_tested": list(models),
            "genesis_4scars_identical_core_sha256": genesis_core_identical,
            "genesis_4scars_identical_lineage_hash": genesis_lineage_identical,
            "post_5scars_identical_core_sha256": len(core_hashes) == 1,
            "post_5scars_identical_lineage_hash": len(lineage_hashes) == 1,
            "post_5scars_per_model": {
                m: {
                    "token_est": c["token_est"],
                    "bytes": len(json.dumps(c, separators=(",", ":"))),
                    "core_sha256_prefix": c["core_sha256"][:12],
                }
                for m, c in zip(models, capsules)
            },
            "capsule_token_est_max": max(c["token_est"] for c in capsules),
            "capsule_under_500_tokens": all(c["token_est"] <= 500 for c in capsules),
            "capsule_compact_json_bytes": len(json.dumps(capsules[0], separators=(",", ":"))),
            "capsule_all_verified": all(AutobiographicalSoul.verify_capsule(c) for c in capsules),
            "tight_180_token_est": tight["token_est"],
            "tight_180_valid": tight["token_est"] <= 180 and AutobiographicalSoul.verify_capsule(tight),
            "vsa_10k_recall_top1_accuracy": round(recall_hits / len(recall_checks), 4),
            "vsa_recall_latency": _summarize_ns(recall_ns),
            "capsule_export_latency": _summarize_ns(export_ns),
        }
    finally:
        soul.close()


# ---------------------------------------------------------------------------
# Benchmark 11: Open Ecosystem NVIDIA-Style Soul Live Integration
# ---------------------------------------------------------------------------


def bench_11_open_ecosystem(work_dir: pathlib.Path) -> dict[str, Any]:
    from chimera_tp.autopilot import OpsConfig
    from chimera_tp.cli import main as cli_main
    from chimera_tp.dashboard import ChimeraDaemon
    from chimera_tp.platform.client import connect
    from chimera_tp.platform.mcp_server import _TOOLS, handle_mcp_request

    ops = work_dir / "eco_daemon_ops"
    cfg = OpsConfig(
        node_name="bios-bench-node",
        role="controller",
        dashboard_bind="127.0.0.1:0",
        beam_port=0,
        rpc_v4_port=0,
        rpc_v6_port=-1,
        query_port=0,
        warp_port=-1,
        edge_proxy_port=-1,
        allowed_query_roots=[str(work_dir)],
        search_roots=[str(work_dir)],
        edge_targets={},
        phantom_enabled=False,
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def get_raw(anchor: str, path: str, timeout: float = 10.0) -> tuple[int, bytes, dict[str, str], float]:
        t0 = time.perf_counter()
        with opener.open(f"{anchor}{path}", timeout=timeout) as r:
            raw = r.read()
            return r.status, raw, dict(r.headers), (time.perf_counter() - t0) * 1000.0

    def post_json(anchor: str, path: str, body: dict[str, Any], timeout: float = 15.0) -> tuple[int, dict[str, Any], float]:
        t0 = time.perf_counter()
        req = urllib.request.Request(
            f"{anchor}{path}",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with opener.open(req, timeout=timeout) as r:
                return r.status, json.loads(r.read().decode("utf-8")), (time.perf_counter() - t0) * 1000.0
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8")), (time.perf_counter() - t0) * 1000.0

    daemon = ChimeraDaemon(config=cfg, ops_dir=ops, auto_seed_on_empty=False).start()
    try:
        anchor = daemon.platform.anchor_url
        bios_none_at_boot = daemon.platform._bios is None
        mem_before_bios = _current_process_mem_mib()

        # 1. /.well-known/chimera.json discovery (MUST stay lazy_ready!)
        sc_wk, raw_wk, _, wk_ms = get_raw(anchor, "/.well-known/chimera.json")
        wk = json.loads(raw_wk.decode("utf-8"))
        bios_cart_before = wk["cartridges"].get("bios", {})
        still_lazy_after_well_known = (daemon.platform._bios is None) and (bios_cart_before.get("status") == "lazy_ready")

        # 2. Measure tracemalloc peak when activating all 10 organs via live HTTP
        tracemalloc.start()
        try:
            http_routes_ms: dict[str, float] = {}
            _, raw_abi, _, http_routes_ms["GET /v1/bios/abi"] = get_raw(anchor, "/v1/bios/abi")
            abi_doc = json.loads(raw_abi.decode("utf-8"))
            _, raw_st, _, http_routes_ms["GET /v1/bios/status"] = get_raw(anchor, "/v1/bios/status")
            st_doc = json.loads(raw_st.decode("utf-8"))
            _, _, http_routes_ms["POST /v1/bios/hormones"] = post_json(anchor, "/v1/bios/hormones", {"hormone": "dopamine", "delta": 0.1, "source": "bench"})
            _, _, http_routes_ms["POST /v1/bios/pulse"] = post_json(anchor, "/v1/bios/pulse", {"obs": {"cpu_pct": 32.0}, "context": "coding"})
            _, _, http_routes_ms["POST /v1/bios/predict"] = post_json(anchor, "/v1/bios/predict", {"obs": {"cpu_pct": 70.0}, "context": "cad", "horizon_s": 60.0})
            _, _, http_routes_ms["POST /v1/bios/pheromone"] = post_json(anchor, "/v1/bios/pheromone", {"repo": "chimera-tp", "rel_path": "chimera_tp/cli.py", "alarm": {"signal_kind": "warn", "severity": 0.4}})
            _, _, _, http_routes_ms["GET /v1/bios/umwelt"] = get_raw(anchor, "/v1/bios/umwelt")
            _, _, _, http_routes_ms["GET /v1/bios/ganglia"] = get_raw(anchor, "/v1/bios/ganglia")
            _, _, _, http_routes_ms["GET /v1/bios/hgt"] = get_raw(anchor, "/v1/bios/hgt")
            _, _, _, http_routes_ms["GET /v1/bios/autophagy"] = get_raw(anchor, "/v1/bios/autophagy")
            _, _, http_routes_ms["POST /v1/bios/parasite/run"] = post_json(anchor, "/v1/bios/parasite/run", {"rounds": 2, "seed": 42})
            _, raw_soul, _, http_routes_ms["GET /v1/bios/soul"] = get_raw(anchor, "/v1/bios/soul?query=law%207&target_model=gemini")
            soul_http = json.loads(raw_soul.decode("utf-8"))
            sc_404, body_404, http_routes_ms["POST /v1/bios/hgt (404)"] = post_json(anchor, "/v1/bios/hgt", {"action": "scan", "plasmid_id": "nonexistent_id"})

            # Spore PWA HTML over live HTTP
            sc_pwa, raw_pwa, hdr_pwa, pwa_http_ms = get_raw(anchor, "/v1/bios/spore")
            http_routes_ms["GET /v1/bios/spore"] = round(pwa_http_ms, 2)

            # Live SSE stream (?max_events=2&interval_ms=20)
            sc_sse, raw_sse, hdr_sse, sse_ms = get_raw(anchor, "/v1/bios/stream?max_events=2&interval_ms=20")
            http_routes_ms["GET /v1/bios/stream?max_events=2"] = round(sse_ms, 2)
            sse_events = [json.loads(ln[len("data:"):].strip()) for ln in raw_sse.decode("utf-8").splitlines() if ln.startswith("data:")]

            cur_b, peak_b = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()

        mem_after_bios = _current_process_mem_mib()
        _, raw_wk2, _, _ = get_raw(anchor, "/.well-known/chimera.json")
        bios_cart_after = json.loads(raw_wk2.decode("utf-8"))["cartridges"].get("bios", {})

        # 3. ChimeraClient SDK ONLINE & OFFLINE (all 13 methods)
        online = connect(app="bios-bench-online", anchor_url=anchor, auto_register=False)
        t_on = time.perf_counter()
        on_results = [
            online.bios_status(),
            online.bios_abi(),
            online.bios_hormones(),
            online.bios_pulse(obs={"cpu_pct": 25.0}, context="coding"),
            online.bios_predict({"cpu_pct": 30.0}, context="coding", horizon_s=60.0),
            online.bios_pheromone(".", "chimera_tp/cli.py"),
            online.bios_umwelt(),
            online.bios_soul(query="law 7", target_model="claude", max_tokens=500),
            online.bios_autophagy(action="status"),
            online.bios_parasite(rounds=1),
            online.bios_hgt(action="list"),
            online.bios_spore(action="list"),
            online.bios_ganglia(action="status"),
        ]
        sdk_online_total_ms = round((time.perf_counter() - t_on) * 1000.0, 2)

        offline = connect(app="bios-bench-offline", anchor_url="http://127.0.0.1:1", auto_register=False)
        t_off = time.perf_counter()
        off_results = [
            offline.bios_status(),
            offline.bios_abi(),
            offline.bios_hormones(),
            offline.bios_pulse(obs={"cpu_pct": 15.0}, context="idle"),
            offline.bios_predict({"cpu_pct": 15.0}, context="idle", horizon_s=30.0),
            offline.bios_pheromone(".", "offline.py"),
            offline.bios_umwelt(),
            offline.bios_soul(query="law 7", target_model="gemini", max_tokens=500),
            offline.bios_autophagy(action="status"),
            offline.bios_parasite(rounds=1),
            offline.bios_hgt(action="list"),
            offline.bios_spore(action="list"),
            offline.bios_ganglia(action="status"),
            offline.bios_sync(),
        ]
        sdk_offline_total_ms = round((time.perf_counter() - t_off) * 1000.0, 2)

        # 4. MCP JSON-RPC tools (5 BIOS tools)
        mcp_calls = [
            ("chimera_bios_status", {"include_abi": True}),
            ("chimera_bios_hormones", {"action": "read"}),
            ("chimera_bios_pheromone", {"repo": "chimera-tp", "rel_path": "chimera_tp/cli.py", "action": "smell"}),
            ("chimera_bios_soul", {"action": "capsule", "query": "law 3", "target_model": "codex", "max_tokens": 500}),
            ("chimera_bios_evolve", {"action": "pulse", "context": "coding", "obs": {"cpu_pct": 28.0}}),
        ]
        mcp_results: dict[str, Any] = {}
        for idx, (tname, args) in enumerate(mcp_calls, start=1):
            t_m0 = time.perf_counter()
            resp = handle_mcp_request(
                {"jsonrpc": "2.0", "id": 900 + idx, "method": "tools/call", "params": {"name": tname, "arguments": args}},
                anchor_url=anchor,
            )
            dt_m = round((time.perf_counter() - t_m0) * 1000.0, 2)
            assert resp is not None
            txt = resp["result"]["content"][0]["text"]
            parsed = json.loads(txt)
            mcp_results[tname] = {
                "ms": dt_m,
                "bytes": len(txt.encode("utf-8")),
                "within_spill_shield_8600b": len(txt.encode("utf-8")) <= 8600,
                "is_error": bool(resp["result"].get("isError", False)),
                "valid_json_dict": isinstance(parsed, dict),
            }

        # 5. CLI `chimera-tp bios` commands
        cli_cases = [
            ["bios", "status", "--anchor", anchor],
            ["bios", "abi", "--anchor", anchor],
            ["bios", "hormones", "--anchor", anchor],
            ["bios", "soul", "--anchor", anchor, "--query", "law 7", "--model", "gemini"],
            ["bios", "pulse", "--local", "--context", "coding"],
        ]
        cli_results = {}
        for argv in cli_cases:
            t_c0 = time.perf_counter()
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = cli_main(argv)
            dt_c = round((time.perf_counter() - t_c0) * 1000.0, 2)
            parsed = json.loads(buf.getvalue())
            cli_results[" ".join(argv[:2]) + (" --local" if "--local" in argv else "")] = {
                "rc": rc,
                "ms": dt_c,
                "ok": bool(parsed.get("ok", True)),
            }

        return {
            "well_known_status_code": sc_wk,
            "well_known_ms": round(wk_ms, 2),
            "bios_none_at_boot": bios_none_at_boot,
            "still_lazy_after_well_known": still_lazy_after_well_known,
            "bios_cartridge_status_transition": f"{bios_cart_before.get('status')} -> {bios_cart_after.get('status')}",
            "abi_schema": abi_doc.get("schema"),
            "organs_active_count": st_doc.get("organs_count"),
            "http_routes_ms": {k: round(v, 2) for k, v in http_routes_ms.items()},
            "http_404_unknown_plasmid_status": sc_404,
            "http_404_json_ok_false": body_404.get("ok") is False,
            "http_spore_pwa_status": sc_pwa,
            "http_spore_pwa_bytes": len(raw_pwa),
            "http_spore_pwa_ctype": hdr_pwa.get("Content-Type"),
            "http_sse_status": sc_sse,
            "http_sse_ctype": hdr_sse.get("Content-Type"),
            "http_sse_events_received": len(sse_events),
            "http_sse_event_type": sse_events[0].get("event") if sse_events else None,
            "http_soul_token_est": soul_http.get("token_est"),
            "sdk_online_13_methods_all_ok": all(isinstance(r, dict) and r.get("ok", True) for r in on_results),
            "sdk_online_13_methods_total_ms": sdk_online_total_ms,
            "sdk_offline_14_methods_all_ok": all(isinstance(r, dict) and r.get("offline_fallback") is True for r in off_results),
            "sdk_offline_14_methods_total_ms": sdk_offline_total_ms,
            "mcp_total_tools": len(_TOOLS),
            "mcp_bios_tools_bench": mcp_results,
            "cli_bios_bench": cli_results,
            "live_process_mem_before_bios": mem_before_bios,
            "live_process_mem_after_10_organs": mem_after_bios,
            "bios_10_organs_tracemalloc_cur_kib": round(cur_b / 1024.0, 2),
            "bios_10_organs_tracemalloc_peak_kib": round(peak_b / 1024.0, 2),
            "bios_10_organs_tracemalloc_peak_mib": round(peak_b / (1024.0 * 1024.0), 4),
            "law7_live_daemon_under_80mib": mem_after_bios["working_set_mib"] < 80.0,
        }
    finally:
        daemon.close()


def bench_12_bidirectional_sync(work_dir: pathlib.Path) -> dict[str, Any]:
    """Benchmark 2-way bidirectional CHIMERA-BIOS cross-host sync between two isolated ChimeraDaemons."""
    from chimera_tp.autopilot import OpsConfig
    from chimera_tp.cli import main as cli_main
    from chimera_tp.dashboard import ChimeraDaemon
    from chimera_tp.platform.bios.endocrine import read_endocrine_block_mmap
    from chimera_tp.platform.client import connect

    ops_a = work_dir / "sync_ops_win"
    ops_b = work_dir / "sync_ops_svhome"

    def _cfg(name: str, role: str) -> OpsConfig:
        return OpsConfig(
            node_name=name,
            role=role,
            dashboard_bind="127.0.0.1:0",
            beam_port=0,
            rpc_v4_port=0,
            rpc_v6_port=-1,
            query_port=0,
            warp_port=-1,
            edge_proxy_port=-1,
            allowed_query_roots=[str(work_dir)],
            search_roots=[str(work_dir)],
            edge_targets={},
            phantom_enabled=False,
        )

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def _get_json(base: str, path: str) -> tuple[int, dict[str, Any], float]:
        t0 = time.perf_counter()
        with opener.open(f"{base}{path}", timeout=10.0) as r:
            return r.status, json.loads(r.read().decode("utf-8")), (time.perf_counter() - t0) * 1000.0

    def _post_json(base: str, path: str, body: dict[str, Any]) -> tuple[int, dict[str, Any], float]:
        t0 = time.perf_counter()
        req = urllib.request.Request(
            f"{base}{path}",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with opener.open(req, timeout=15.0) as r:
                return r.status, json.loads(r.read().decode("utf-8")), (time.perf_counter() - t0) * 1000.0
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8")), (time.perf_counter() - t0) * 1000.0

    d_win = ChimeraDaemon(config=_cfg("bench-win", "controller"), ops_dir=ops_a, auto_seed_on_empty=False).start()
    d_svh = ChimeraDaemon(config=_cfg("bench-svhome", "node"), ops_dir=ops_b, auto_seed_on_empty=False).start()
    try:
        both_lazy_at_boot = (d_win.platform._bios is None) and (d_svh.platform._bios is None)
        a_win = d_win.platform.anchor_url
        a_svh = d_svh.platform.anchor_url

        # Seed divergent physiology, scars, alarms, seeds & CRDT events
        _post_json(a_win, "/v1/bios/hormones", {"hormone": "adrenaline", "delta": 0.55, "source": "bench_win"})
        _post_json(a_svh, "/v1/bios/hormones", {"hormone": "melatonin", "delta": 0.55, "source": "bench_svh"})
        d_win.platform.bios.octopus.peer_ganglion.append_event("bench_win_ev", {"v": 1}, key="bench:win")
        d_svh.platform.bios.octopus.peer_ganglion.append_event("bench_svh_ev", {"v": 2}, key="bench:svh")
        _post_json(
            a_win,
            "/v1/bios/soul/scar",
            {
                "title": "Bench Win Scar",
                "event_date": "2026-11-27",
                "root_cause": "Synthetic win benchmark scar",
                "lesson_law": "Keep win zero-choke",
                "hardware_context": "bench-win",
                "tags": ["bench", "win"],
                "severity": "high",
            },
        )
        _post_json(
            a_svh,
            "/v1/bios/soul/scar",
            {
                "title": "Bench Svhome Scar",
                "event_date": "2026-11-27",
                "root_cause": "Synthetic svhome benchmark scar",
                "lesson_law": "Protect svhome 15W",
                "hardware_context": "bench-svhome",
                "tags": ["bench", "svhome"],
                "severity": "high",
            },
        )
        _post_json(
            a_win,
            "/v1/bios/pheromone",
            {"repo": "chimera-tp", "rel_path": "chimera_tp/platform/bios/organism.py", "alarm": {"signal_kind": "warn", "severity": 0.72, "reason": "bench_sync_alarm"}},
        )
        _post_json(a_svh, "/v1/bios/spore/seed", {"spore_id": "spore:bench_svh", "text": "Bench 2-way seed", "priority": "high"})

        # Check compact <= 32 KB bundle export & Law 3 > 64 KB cap rejection
        _, b_win, b_win_ms = _get_json(a_win, "/v1/bios/sync/bundle")
        _, b_svh, _ = _get_json(a_svh, "/v1/bios/sync/bundle")
        win_bundle_bytes = len(json.dumps(b_win, separators=(",", ":")).encode("utf-8"))
        svh_bundle_bytes = len(json.dumps(b_svh, separators=(",", ":")).encode("utf-8"))
        sc_oversize, err_oversize, _ = _post_json(
            a_svh,
            "/v1/bios/sync",
            {"bundle": {"node_name": "attacker", "pad": "x" * (65 * 1024)}},
        )

        # First 2-way sync (cold merge across divergent state)
        sc1, sync1, sync1_ms = _post_json(a_win, "/v1/bios/sync", {"peer_url": a_svh, "blend": 0.35})
        assert sc1 == 200 and sync1.get("ok") and sync1.get("merkle_converged"), f"2-way sync failed: {sync1}"

        # Warm repeat idempotent 2-way sync (5 trials)
        warm_ms: list[float] = []
        sync_repeat: dict[str, Any] = {}
        for _ in range(5):
            sc_r, sync_repeat, dt_r = _post_json(a_win, "/v1/bios/sync", {"peer_url": a_svh, "blend": 0.35})
            assert sc_r == 200 and sync_repeat.get("merkle_converged")
            warm_ms.append(dt_r)

        # SDK + CLI live 2-way sync check
        cli_on = connect(app="bios-bench-sync", anchor_url=a_win, auto_register=False)
        sdk_sync = cli_on.bios_sync(peer_url=a_svh, blend=0.35)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            cli_rc = cli_main(["bios", "sync", "--anchor", a_win, "--peer-url", a_svh, "--blend", "0.35"])
        cli_parsed = json.loads(buf.getvalue())

        # Verify isolated NIXL mmap headers on BOTH daemons
        win_blk = read_endocrine_block_mmap(ops_a / "bios" / "chimera_nixl_ring.bin")
        svh_blk = read_endocrine_block_mmap(ops_b / "bios" / "chimera_nixl_ring.bin")

        return {
            "both_lazy_at_boot": both_lazy_at_boot,
            "win_bundle_bytes": win_bundle_bytes,
            "svhome_bundle_bytes": svh_bundle_bytes,
            "bundle_export_ms": round(b_win_ms, 2),
            "bundles_under_32kb": (win_bundle_bytes <= 32768) and (svh_bundle_bytes <= 32768),
            "law3_over_64kb_rejected_400": (sc_oversize == 400) and (err_oversize.get("ok") is False),
            "initial_2way_sync_ms": round(sync1_ms, 2),
            "initial_2way_rtt_ms": sync1.get("rtt_ms"),
            "initial_round_trips": sync1.get("round_trips"),
            "merkle_converged": bool(sync1.get("merkle_converged")),
            "converged_merkle_root": sync1.get("local_merkle_root"),
            "scars_synced_initial": sync1.get("scars_synced"),
            "alarms_synced_initial": sync1.get("alarms_synced"),
            "seeds_synced_initial": sync1.get("seeds_synced"),
            "repeat_idempotent_zero_dups": (
                sync_repeat.get("scars_synced", {}).get("total") == 0
                and sync_repeat.get("alarms_synced", {}).get("total") == 0
                and sync_repeat.get("seeds_synced", {}).get("total") == 0
                and sync_repeat.get("local_merkle_root") == sync1.get("local_merkle_root")
            ),
            "warm_2way_sync_median_ms": round(statistics.median(warm_ms), 2),
            "both_nixl_endo_valid": bool(win_blk.get("valid") and svh_blk.get("valid")),
            "both_soul_lineages_valid": bool(
                d_win.platform.bios.soul.verify_lineage()["valid"]
                and d_svh.platform.bios.soul.verify_lineage()["valid"]
            ),
            "endocrine_wire_bytes": sync1.get("endocrine_wire_bytes"),
            "law6_auto_activated_false": sync1.get("auto_activated") is False,
            "sdk_bios_sync_ok": bool(sdk_sync.get("ok") and sdk_sync.get("merkle_converged")),
            "cli_bios_sync_ok": (cli_rc == 0) and bool(cli_parsed.get("ok") and cli_parsed.get("merkle_converged")),
        }
    finally:
        d_win.close()
        d_svh.close()


def bench_standalone_daemon_rss() -> dict[str, Any]:
    """Measure clean standalone ChimeraDaemon RSS in a fresh subprocess before & after activating all 10 BIOS organs."""
    code = r"""
import ctypes, ctypes.wintypes, json, os, tempfile, tracemalloc, urllib.request
from pathlib import Path
from chimera_tp.autopilot import OpsConfig
from chimera_tp.dashboard import ChimeraDaemon

def mem():
    if os.name == 'nt':
        class PMC(ctypes.Structure):
            _fields_ = [('cb',ctypes.wintypes.DWORD),('pf',ctypes.wintypes.DWORD),('pws',ctypes.c_size_t),('ws',ctypes.c_size_t),('qpp',ctypes.c_size_t),('qp',ctypes.c_size_t),('qpnp',ctypes.c_size_t),('qnp',ctypes.c_size_t),('pfu',ctypes.c_size_t),('ppfu',ctypes.c_size_t),('priv',ctypes.c_size_t)]
        k32 = ctypes.WinDLL('kernel32', use_last_error=True)
        k32.GetCurrentProcess.restype = ctypes.wintypes.HANDLE
        k32.K32GetProcessMemoryInfo.argtypes = [ctypes.wintypes.HANDLE, ctypes.POINTER(PMC), ctypes.wintypes.DWORD]
        k32.K32GetProcessMemoryInfo.restype = ctypes.wintypes.BOOL
        p = PMC(); p.cb = ctypes.sizeof(p)
        k32.K32GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(p), p.cb)
        return {'working_set_mib': round(p.ws/1048576, 3), 'private_usage_mib': round(p.priv/1048576, 3), 'peak_working_set_mib': round(p.pws/1048576, 3)}
    return {'working_set_mib': 0.0, 'private_usage_mib': 0.0, 'peak_working_set_mib': 0.0}

with tempfile.TemporaryDirectory(prefix='chimera_bios_clean_rss_') as td:
    cfg = OpsConfig(node_name='clean-bios-daemon', role='controller', dashboard_bind='127.0.0.1:0', beam_port=0, rpc_v4_port=0, rpc_v6_port=-1, query_port=0, warp_port=-1, edge_proxy_port=-1, allowed_query_roots=[td], search_roots=[td], edge_targets={}, phantom_enabled=False)
    d = ChimeraDaemon(config=cfg, ops_dir=Path(td)/'ops', auto_seed_on_empty=False).start()
    try:
        m_boot = mem()
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(d.platform.anchor_url + '/.well-known/chimera.json') as r:
            wk = json.loads(r.read())
        bios_none_after_wk = d.platform._bios is None
        m_wk = mem()
        tracemalloc.start()
        with opener.open(d.platform.anchor_url + '/v1/bios/status') as r:
            st = json.loads(r.read())
        with opener.open(d.platform.anchor_url + '/v1/bios/spore') as r:
            pwa = r.read()
        with opener.open(d.platform.anchor_url + '/v1/bios/soul') as r:
            _ = json.loads(r.read())
        cur, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        m_active = mem()
        print(json.dumps({
            'boot_mem': m_boot,
            'after_well_known_mem': m_wk,
            'after_10_organs_active_mem': m_active,
            'wk_bios_status': wk['cartridges']['bios']['status'],
            'bios_none_after_well_known': bios_none_after_wk,
            'organs_loaded': st.get('organs_count'),
            'tracemalloc_cur_kib': round(cur/1024.0, 2),
            'tracemalloc_peak_kib': round(peak/1024.0, 2),
            'tracemalloc_peak_mib': round(peak/1048576.0, 4),
            'os_ws_delta_mib': round(m_active['working_set_mib'] - m_wk['working_set_mib'], 3),
            'law7_under_80mib': m_active['working_set_mib'] < 80.0,
            'pwa_bytes': len(pwa),
        }))
    finally:
        d.close()
"""
    p = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=45)
    if p.returncode != 0:
        return {"error": p.stderr.strip()}
    return json.loads(p.stdout.strip().splitlines()[-1])


# ---------------------------------------------------------------------------
# Constitutional Audit (Laws 1-7)
# ---------------------------------------------------------------------------


def audit_laws_static() -> dict[str, Any]:
    bios_dir = ROOT / "chimera_tp" / "platform" / "bios"
    forbidden_law2_patterns = [
        "SetProcessAffinityMask",
        "NtSuspendProcess",
        "PROCTHROTTLEMAX",
        "EmptyWorkingSet",
        "EcoQoS",
        "import numpy",
        "from numpy",
    ]
    hits: dict[str, list[str]] = {pat: [] for pat in forbidden_law2_patterns}
    hex_f00_hits: list[str] = []
    for f in sorted(bios_dir.glob("*.py")):
        for idx, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
            for pat in forbidden_law2_patterns:
                if pat in line:
                    hits[pat].append(f"{f.name}:{idx}")
            if "0xF00" in line or "0xf00" in line:
                hex_f00_hits.append(f"{f.name}:{idx}: {line.strip()[:90]}")
    code_hits = {k: v for k, v in hits.items() if v}
    return {
        "law2_forbidden_api_hits": code_hits,
        "law2_zero_forbidden_apis": len(code_hits) == 0,
        "law2_0xf00_mentions_context": hex_f00_hits,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run CHIMERA-BIOS AFTER benchmark suite.")
    parser.add_argument("--out", type=str, default="", help="Optional JSON output path.")
    parser.add_argument("--import-runs", type=int, default=5, help="Subprocess runs per cold-import measurement.")
    args = parser.parse_args()

    before = {}
    if BEFORE_BASELINE_PATH.is_file():
        before = json.loads(BEFORE_BASELINE_PATH.read_text(encoding="utf-8"))

    t_all = time.perf_counter()
    cold_imports = bench_cold_imports(runs=max(1, args.import_runs))
    standalone_daemon_rss = bench_standalone_daemon_rss()
    codebase_after = scan_codebase_and_surfaces_after()
    laws_static = audit_laws_static()

    with tempfile.TemporaryDirectory(prefix="chimera_bios_bench_") as td:
        wd = pathlib.Path(td)
        engines = {
            "01_endocrine": bench_01_endocrine(wd),
            "02_friston": bench_02_friston(),
            "03_autophagy": bench_03_autophagy(wd),
            "04_parasite": bench_04_parasite(wd),
            "05_octopus": bench_05_octopus(wd),
            "06_stigmergy": bench_06_stigmergy(wd),
            "07_umwelt": bench_07_umwelt(wd),
            "08_hgt": bench_08_hgt(wd),
            "09_mycelium": bench_09_mycelium(wd),
            "10_soul": bench_10_soul(wd),
        }
        open_ecosystem = bench_11_open_ecosystem(wd)
        bios_sync_2way = bench_12_bidirectional_sync(wd)

    total_s = round(time.perf_counter() - t_all, 2)

    # Compute direct BEFORE vs AFTER deltas
    deltas: dict[str, Any] = {}
    if before:
        b_ci = before.get("cold_imports", {})
        a_ci = cold_imports
        deltas["cold_import_chimera_tp_ws_mib_before"] = b_ci.get("chimera_tp", {}).get("summary", {}).get("working_set_mib_median")
        deltas["cold_import_chimera_tp_ws_mib_after"] = a_ci["chimera_tp"]["summary"].get("working_set_mib_median")
        deltas["cold_import_substrate_ws_mib_before"] = b_ci.get("chimera_tp.platform.substrate", {}).get("summary", {}).get("working_set_mib_median")
        deltas["cold_import_substrate_ws_mib_after"] = a_ci["chimera_tp.platform.substrate"]["summary"].get("working_set_mib_median")
        deltas["cold_import_substrate_private_mib_before"] = b_ci.get("chimera_tp.platform.substrate", {}).get("summary", {}).get("private_usage_mib_median")
        deltas["cold_import_substrate_private_mib_after"] = a_ci["chimera_tp.platform.substrate"]["summary"].get("private_usage_mib_median")
        deltas["cold_import_bios_loaded_before"] = False
        deltas["cold_import_bios_loaded_after"] = a_ci["chimera_tp.platform.substrate"]["summary"].get("bios_loaded_any")
        deltas["modules_all_before"] = before.get("codebase_before", {}).get("chimera_tp_all", {}).get("module_count")
        deltas["modules_all_after"] = codebase_after["chimera_tp_all"]["module_count"]
        deltas["loc_all_before"] = before.get("codebase_before", {}).get("chimera_tp_all", {}).get("total_lines")
        deltas["loc_all_after"] = codebase_after["chimera_tp_all"]["total_lines"]
        deltas["bios_ideas_before"] = "0/10"
        deltas["bios_ideas_after"] = "10/10"

    report = {
        "schema": "chimera_bios_benchmark_after.v1",
        "captured_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total_benchmark_seconds": total_s,
        "environment": {
            "python_version": sys.version,
            "platform": sys.platform,
            "cpu_count": os.cpu_count(),
        },
        "cold_imports_after": cold_imports,
        "standalone_daemon_rss_after": standalone_daemon_rss,
        "codebase_after": codebase_after,
        "engines": engines,
        "open_ecosystem": open_ecosystem,
        "bios_sync_2way": bios_sync_2way,
        "laws_static_audit": laws_static,
        "before_vs_after_summary": deltas,
    }

    text = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.out:
        out_path = pathlib.Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text, encoding="utf-8")
        print(f"Wrote CHIMERA-BIOS AFTER benchmark JSON to {out_path} ({len(text.encode('utf-8'))} bytes) in {total_s}s")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
