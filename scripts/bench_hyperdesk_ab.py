"""Controlled alternating A/B experiment evaluating CHIMERA-HYPERDESK governance.

Runs strictly alternating paired workloads (AB, BA, AB, BA, ...) comparing:
  - Condition A ("baseline"): unmanaged background build workers + foreground CAD loop
  - Condition B ("hyperdesk"): Focus/VIP affinity & AboveNormal priority for the
    foreground CAD process plus HyperDesk Industrial core pinning, EcoQoS, VeryLow
    memory priority, BelowNormal priority, and WinHardCpuCage governance on background
    build workers.

Telemetry uses native Win32 APIs (psapi!GetProcessMemoryInfo and pdh.dll memory
counters) with zero PowerShell invocations and CREATE_NO_WINDOW on all child processes.
"""

from __future__ import annotations

import argparse
import ast
import ctypes
from datetime import datetime, timezone
import hashlib
import json
import marshal
import math
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from typing import Any
import urllib.request
import zlib

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from chimera_tp.platform.hyper_desk import (  # noqa: E402
    HyperDeskEngine,
    VramCompressedSwap,
    WinHardCpuCage,
    _ABOVE_NORMAL_PRIORITY_CLASS,
    _BELOW_NORMAL_PRIORITY_CLASS,
    _IO_PRIORITY_NORMAL,
    _IO_PRIORITY_VERY_LOW,
    _MEMORY_PRIORITY_NORMAL,
    _MEMORY_PRIORITY_VERY_LOW,
    _NORMAL_PRIORITY_CLASS,
    _PROCESS_QUERY_LIMITED_INFORMATION,
    _PROCESS_VM_READ,
    _win_close_handle,
    _win_open_proc,
    _win_set_affinity,
    _win_set_eco_qos,
    _win_set_io_priority,
    _win_set_memory_priority,
    _win_set_priority,
    _win_set_timer_resolution,
)

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
_FRAME_BUDGET_MS = 1000.0 / 60.0  # 16.6667 ms (60 Hz)


if os.name == "nt":
    class _PROCESS_MEMORY_COUNTERS_EX(ctypes.Structure):
        _fields_ = [
            ("cb", ctypes.c_ulong),
            ("PageFaultCount", ctypes.c_ulong),
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

    class _PDH_FMT_COUNTERVALUE_DOUBLE(ctypes.Structure):
        _fields_ = [
            ("CStatus", ctypes.c_ulong),
            ("doubleValue", ctypes.c_double),
        ]


def query_process_memory(pid: int) -> dict[str, Any] | None:
    """Read Working Set MB, Peak WS MB, Private Commit MB, and PageFaultCount via Win32 GetProcessMemoryInfo."""
    if os.name != "nt":
        if pid == os.getpid():
            try:
                import resource
                ru = resource.getrusage(resource.RUSAGE_SELF)
                rss_mb = round(ru.ru_maxrss / 1024.0, 3)
                return {
                    "working_set_mb": rss_mb,
                    "peak_working_set_mb": rss_mb,
                    "private_commit_mb": rss_mb,
                    "page_fault_count": int(ru.ru_minflt + ru.ru_majflt),
                }
            except Exception:
                return None
        try:
            st = Path(f"/proc/{pid}/status").read_text(encoding="utf-8", errors="ignore")
            rss_kb, vm_kb = 0, 0
            for ln in st.splitlines():
                if ln.startswith("VmRSS:"):
                    rss_kb = int(ln.split(":", 1)[1].strip().split()[0] or 0)
                elif ln.startswith("VmData:"):
                    vm_kb = int(ln.split(":", 1)[1].strip().split()[0] or 0)
            ws_mb = round(rss_kb / 1024.0, 3)
            priv_mb = round(max(rss_kb, vm_kb) / 1024.0, 3)
            return {
                "working_set_mb": ws_mb,
                "peak_working_set_mb": ws_mb,
                "private_commit_mb": priv_mb,
                "page_fault_count": 0,
            }
        except OSError:
            return None

    h = _win_open_proc(pid, _PROCESS_QUERY_LIMITED_INFORMATION | _PROCESS_VM_READ)
    if not h:
        h = _win_open_proc(pid, _PROCESS_QUERY_LIMITED_INFORMATION)
    if not h:
        return None
    try:
        pmc = _PROCESS_MEMORY_COUNTERS_EX()
        pmc.cb = ctypes.sizeof(_PROCESS_MEMORY_COUNTERS_EX)
        ok = ctypes.windll.psapi.GetProcessMemoryInfo(
            ctypes.c_void_p(h), ctypes.byref(pmc), pmc.cb
        )
        if not ok:
            return None
        mib = 1024.0 * 1024.0
        return {
            "working_set_mb": round(pmc.WorkingSetSize / mib, 3),
            "peak_working_set_mb": round(pmc.PeakWorkingSetSize / mib, 3),
            "private_commit_mb": round(max(pmc.PrivateUsage, pmc.PagefileUsage) / mib, 3),
            "page_fault_count": int(pmc.PageFaultCount),
        }
    except Exception:
        return None
    finally:
        _win_close_handle(h)


class WinPdhFaultSampler:
    """Sample system-wide memory fault counters via Windows pdh.dll (zero PowerShell)."""

    _PDH_FMT_DOUBLE = 0x00000200

    def __init__(self) -> None:
        self._pdh: Any = None
        self._query = ctypes.c_void_p(0)
        self._c_page_reads = ctypes.c_void_p(0)
        self._c_pages_input = ctypes.c_void_p(0)
        self._c_page_faults = ctypes.c_void_p(0)
        self._active = False
        self._samples_reads: list[float] = []
        self._samples_input: list[float] = []
        self._samples_total_faults: list[float] = []

        if os.name != "nt":
            return
        try:
            pdh = ctypes.windll.pdh
            q = ctypes.c_void_p(0)
            if pdh.PdhOpenQueryW(None, 0, ctypes.byref(q)) != 0:
                return
            r1 = pdh.PdhAddEnglishCounterW(q, r"\Memory\Page Reads/sec", 0, ctypes.byref(self._c_page_reads))
            r2 = pdh.PdhAddEnglishCounterW(q, r"\Memory\Pages Input/sec", 0, ctypes.byref(self._c_pages_input))
            r3 = pdh.PdhAddEnglishCounterW(q, r"\Memory\Page Faults/sec", 0, ctypes.byref(self._c_page_faults))
            if r1 != 0 or r2 != 0 or r3 != 0:
                pdh.PdhCloseQuery(q)
                return
            pdh.PdhCollectQueryData(q)
            self._pdh = pdh
            self._query = q
            self._active = True
        except Exception:
            self._active = False

    def sample(self) -> None:
        if not self._active or not self._pdh:
            return
        try:
            if self._pdh.PdhCollectQueryData(self._query) != 0:
                return
            for ctr, dest in (
                (self._c_page_reads, self._samples_reads),
                (self._c_pages_input, self._samples_input),
                (self._c_page_faults, self._samples_total_faults),
            ):
                val = _PDH_FMT_COUNTERVALUE_DOUBLE()
                rc = self._pdh.PdhGetFormattedCounterValue(ctr, self._PDH_FMT_DOUBLE, None, ctypes.byref(val))
                if rc == 0 and val.CStatus == 0 and math.isfinite(val.doubleValue):
                    dest.append(max(0.0, float(val.doubleValue)))
        except Exception:
            pass

    def summary(self) -> dict[str, Any]:
        avg_reads = round(sum(self._samples_reads) / len(self._samples_reads), 3) if self._samples_reads else 0.0
        avg_input = round(sum(self._samples_input) / len(self._samples_input), 3) if self._samples_input else 0.0
        avg_total = (
            round(sum(self._samples_total_faults) / len(self._samples_total_faults), 3)
            if self._samples_total_faults
            else 0.0
        )
        return {
            "pdh_active": self._active,
            "samples": len(self._samples_reads),
            "hard_page_faults_per_s": avg_reads,
            "pages_input_per_s": avg_input,
            "system_total_page_faults_per_s": avg_total,
            "system_soft_page_faults_per_s": round(max(0.0, avg_total - avg_reads), 3),
        }

    def close(self) -> None:
        if self._active and self._pdh and self._query.value:
            try:
                self._pdh.PdhCloseQuery(self._query)
            except Exception:
                pass
        self._active = False
        self._query = ctypes.c_void_p(0)


def percentile(values: list[float], q: float) -> float:
    """Linearly interpolated percentile (0..100)."""
    if not values:
        return 0.0
    s = sorted(float(v) for v in values)
    if len(s) == 1:
        return s[0]
    pos = (max(0.0, min(100.0, float(q))) / 100.0) * (len(s) - 1)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return s[lo]
    frac = pos - lo
    return s[lo] * (1.0 - frac) + s[hi] * frac


def summarize_distribution(values: list[float]) -> dict[str, float]:
    """Return mean, median, p25, p75, min, max rounded to 3 decimals."""
    if not values:
        return {"mean": 0.0, "median": 0.0, "p25": 0.0, "p75": 0.0, "min": 0.0, "max": 0.0}
    s = sorted(float(v) for v in values)
    return {
        "mean": round(sum(s) / len(s), 3),
        "median": round(percentile(s, 50.0), 3),
        "p25": round(percentile(s, 25.0), 3),
        "p75": round(percentile(s, 75.0), 3),
        "min": round(s[0], 3),
        "max": round(s[-1], 3),
    }


def generate_ab_schedule(pairs: int = 10) -> list[tuple[str, str]]:
    """Generate strictly alternating AB, BA, AB, BA, ... pair schedule."""
    n = max(1, int(pairs))
    return [("A", "B") if (i % 2 == 0) else ("B", "A") for i in range(n)]


def classify_ab_outcome(
    median_p99_reduction_pct: float,
    median_build_time_delta_pct: float,
) -> str:
    """Apply exact audit rule: >=20% p99 reduction AND <=10% build time overhead -> PROMOTE_RECOMMENDED."""
    if float(median_p99_reduction_pct) >= 20.0 and float(median_build_time_delta_pct) <= 10.0:
        return "PROMOTE_RECOMMENDED"
    return "MIXED_KEEP_OPT_IN"


def compute_pair_deltas(run_a: dict[str, Any], run_b: dict[str, Any]) -> dict[str, float]:
    """Compute paired A->B deltas for latency and build duration."""
    p99_a = max(0.001, float(run_a["fg"]["p99_ms"]))
    p99_b = float(run_b["fg"]["p99_ms"])
    p95_a = max(0.001, float(run_a["fg"]["p95_ms"]))
    p95_b = float(run_b["fg"]["p95_ms"])
    p50_a = max(0.001, float(run_a["fg"]["p50_ms"]))
    p50_b = float(run_b["fg"]["p50_ms"])
    build_a = max(0.001, float(run_a["bg"]["build_time_s"]))
    build_b = float(run_b["bg"]["build_time_s"])
    drop_a = float(run_a["fg"]["dropped_frames_pct"])
    drop_b = float(run_b["fg"]["dropped_frames_pct"])
    return {
        "p99_reduction_pct": round(((p99_a - p99_b) / p99_a) * 100.0, 3),
        "p95_reduction_pct": round(((p95_a - p95_b) / p95_a) * 100.0, 3),
        "p50_reduction_pct": round(((p50_a - p50_b) / p50_a) * 100.0, 3),
        "dropped_frames_delta_pct": round(drop_b - drop_a, 3),
        "build_time_delta_pct": round(((build_b - build_a) / build_a) * 100.0, 3),
    }


def summarize_pairs(pairs_data: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate 10-pair A/B results into distributions and apply audit decision rule."""
    p99_reds = [float(p["deltas"]["p99_reduction_pct"]) for p in pairs_data]
    build_deltas = [float(p["deltas"]["build_time_delta_pct"]) for p in pairs_data]

    p99_dist = summarize_distribution(p99_reds)
    build_dist = summarize_distribution(build_deltas)
    decision = classify_ab_outcome(p99_dist["median"], build_dist["median"])

    def _cond_summary(key: str) -> dict[str, Any]:
        runs = [p[key] for p in pairs_data]
        return {
            "p50_ms": summarize_distribution([r["fg"]["p50_ms"] for r in runs]),
            "p95_ms": summarize_distribution([r["fg"]["p95_ms"] for r in runs]),
            "p99_ms": summarize_distribution([r["fg"]["p99_ms"] for r in runs]),
            "dropped_frames_pct": summarize_distribution([r["fg"]["dropped_frames_pct"] for r in runs]),
            "build_time_s": summarize_distribution([r["bg"]["build_time_s"] for r in runs]),
            "working_set_mb": summarize_distribution([r["memory"]["working_set_mb"] for r in runs]),
            "private_commit_mb": summarize_distribution([r["memory"]["private_commit_mb"] for r in runs]),
            "total_page_fault_count": summarize_distribution([r["memory"]["total_page_fault_count"] for r in runs]),
            "hard_page_faults_per_s": summarize_distribution([r["faults"]["hard_page_faults_per_s"] for r in runs]),
            "pages_input_per_s": summarize_distribution([r["faults"]["pages_input_per_s"] for r in runs]),
            "soft_page_faults_per_s": summarize_distribution([r["faults"]["soft_page_faults_per_s"] for r in runs]),
        }

    return {
        "decision": decision,
        "decision_rule": {
            "p99_reduction_pct_min": 20.0,
            "build_time_delta_pct_max": 10.0,
            "median_p99_reduction_pct": p99_dist["median"],
            "median_build_time_delta_pct": build_dist["median"],
        },
        "summary": {
            "p99_reduction_pct": p99_dist,
            "build_time_delta_pct": build_dist,
            "condition_a": _cond_summary("run_a"),
            "condition_b": _cond_summary("run_b"),
        },
    }


def _wait_for_go() -> None:
    line = sys.stdin.readline()
    if not line:
        raise RuntimeError("Parent closed stdin before GO signal")


def _worker_fg(frames: int, target_fps: float, vertices: int) -> None:
    """Deterministic 60 Hz CAD-like vector pan-zoom render loop."""
    pts = [(math.sin(i * 0.017) * 500.0, math.cos(i * 0.023) * 500.0) for i in range(max(200, int(vertices)))]
    fb = bytearray(256 * 256)
    period = 1.0 / max(1.0, float(target_fps))

    sys.stdout.write("READY\n")
    sys.stdout.flush()
    _wait_for_go()

    mem_start = query_process_memory(os.getpid()) or {}
    t_start = time.perf_counter()
    next_tick = t_start
    latencies_ms: list[float] = []
    render_ms_list: list[float] = []
    acc = 0

    for f in range(max(1, int(frames))):
        now = time.perf_counter()
        if now < next_tick:
            time.sleep(next_tick - now)
            scheduled_t = next_tick
            next_tick += period
        else:
            scheduled_t = next_tick
            missed = int((now - next_tick) / period) + 1
            next_tick += missed * period

        t_frame_start = time.perf_counter()
        sc = 1.0 + 0.005 * f
        ang = f * 0.02
        ca = math.cos(ang)
        sa = math.sin(ang)
        tx = (f * 3.7) % 128.0
        ty = (f * 2.1) % 128.0
        for x, y in pts:
            rx = x * ca - y * sa
            ry = x * sa + y * ca
            px = int(rx * sc + tx) & 255
            py = int(ry * sc + ty) & 255
            idx = (py << 8) | px
            fb[idx] = (fb[idx] + 1) & 255
            acc ^= idx
        t_done = time.perf_counter()

        lat_ms = (t_done - scheduled_t) * 1000.0
        latencies_ms.append(lat_ms)
        render_ms_list.append((t_done - t_frame_start) * 1000.0)

    total_s = time.perf_counter() - t_start
    mem_end = query_process_memory(os.getpid()) or {}
    dropped = sum(1 for v in latencies_ms if v > _FRAME_BUDGET_MS)
    start_faults = int(mem_start.get("page_fault_count", 0))
    end_faults = int(mem_end.get("page_fault_count", 0))

    payload = {
        "role": "fg",
        "pid": os.getpid(),
        "frames": len(latencies_ms),
        "elapsed_s": round(total_s, 4),
        "p50_ms": round(percentile(latencies_ms, 50.0), 3),
        "p95_ms": round(percentile(latencies_ms, 95.0), 3),
        "p99_ms": round(percentile(latencies_ms, 99.0), 3),
        "mean_ms": round(sum(latencies_ms) / len(latencies_ms), 3),
        "max_ms": round(max(latencies_ms), 3),
        "render_p50_ms": round(percentile(render_ms_list, 50.0), 3),
        "dropped_frames": dropped,
        "dropped_frames_pct": round((dropped / len(latencies_ms)) * 100.0, 3),
        "checksum": acc,
        "working_set_mb": mem_end.get("working_set_mb", 0.0),
        "peak_working_set_mb": mem_end.get("peak_working_set_mb", 0.0),
        "private_commit_mb": mem_end.get("private_commit_mb", 0.0),
        "delta_page_faults": max(0, end_faults - start_faults),
    }
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


def _worker_bg(worker_id: int, jobs: int) -> None:
    """Deterministic Python AST parse + compile + marshal + page alloc + zlib build worker."""
    src = "\n".join(
        f"def fn_{i}(x, y):\n    z = (x * {i + 1} + y) ^ 0x5A5A\n    return [z + k for k in range(16)]\n"
        for i in range(60)
    )
    buf = bytearray(4 * 1024 * 1024)

    sys.stdout.write("READY\n")
    sys.stdout.flush()
    _wait_for_go()

    mem_start = query_process_memory(os.getpid()) or {}
    t_start = time.perf_counter()
    digest_acc = 0

    for j in range(max(1, int(jobs))):
        mod_name = f"build_w{worker_id}_m{j}.py"
        tree = ast.parse(src, filename=mod_name)
        _ = sum(1 for _ in ast.walk(tree))
        code = compile(tree, mod_name, "exec")
        blob = marshal.dumps(code)
        # Touch transient memory across 4 KiB pages to drive genuine page allocations/faults
        page_buf = bytearray(2 * 1024 * 1024)
        for off in range(0, len(page_buf), 4096):
            page_buf[off] = ((off >> 12) ^ j ^ worker_id) & 0xFF
        buf[: len(page_buf)] = page_buf
        comp = zlib.compress(buf[: 512 * 1024], level=6)
        dig = hashlib.sha256(blob + comp).digest()
        digest_acc ^= int.from_bytes(dig[:8], "little")

    total_s = time.perf_counter() - t_start
    mem_end = query_process_memory(os.getpid()) or {}
    start_faults = int(mem_start.get("page_fault_count", 0))
    end_faults = int(mem_end.get("page_fault_count", 0))

    payload = {
        "role": "bg",
        "worker_id": worker_id,
        "pid": os.getpid(),
        "jobs": int(jobs),
        "elapsed_s": round(total_s, 4),
        "checksum": digest_acc,
        "working_set_mb": mem_end.get("working_set_mb", 0.0),
        "peak_working_set_mb": mem_end.get("peak_working_set_mb", 0.0),
        "private_commit_mb": mem_end.get("private_commit_mb", 0.0),
        "delta_page_faults": max(0, end_faults - start_faults),
    }
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


class _LiveDaemonIsolator:
    """Temporarily pauses live daemon autonomic loop on 127.0.0.1:9780 if active, restoring it cleanly."""

    def __init__(self, enabled: bool = True, base_url: str = "http://127.0.0.1:9780") -> None:
        self.enabled = enabled
        self.base_url = base_url
        self._was_running = False
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def __enter__(self) -> "_LiveDaemonIsolator":
        if not self.enabled:
            return self
        try:
            with self._opener.open(f"{self.base_url}/v1/hyperdesk/autonomic", timeout=1.5) as r:
                st = json.loads(r.read().decode("utf-8"))
            if bool(st.get("running")):
                req = urllib.request.Request(
                    f"{self.base_url}/v1/hyperdesk/autonomic",
                    data=json.dumps({"action": "off", "restore_defaults": True}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with self._opener.open(req, timeout=2.5) as r2:
                    _ = r2.read()
                self._was_running = True
        except Exception:
            self._was_running = False
        return self

    def __exit__(self, *_: Any) -> None:
        if not self._was_running:
            return
        try:
            req = urllib.request.Request(
                f"{self.base_url}/v1/hyperdesk/autonomic",
                data=json.dumps({"action": "on"}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with self._opener.open(req, timeout=2.5) as r:
                _ = r.read()
        except Exception:
            pass

    @property
    def isolated(self) -> bool:
        return self._was_running


def _read_json_line(proc: subprocess.Popen[str], holder: dict[str, Any], key: Any, t_go_ref: list[float]) -> None:
    try:
        line = proc.stdout.readline() if proc.stdout else ""
        done_t = time.perf_counter()
        if line:
            data = json.loads(line.strip())
            data["parent_wall_s"] = round(max(0.0, done_t - t_go_ref[0]), 4)
            holder[key] = data
    except Exception as exc:
        holder[key] = {"error": str(exc)}


def run_single_condition(
    condition: str,
    *,
    frames: int = 180,
    target_fps: float = 60.0,
    vertices: int = 3200,
    workers: int = 12,
    jobs_per_worker: int = 210,
    hard_cage_cap_pct: int = 35,
    urban_mask: int = 0x0FF,
    industrial_mask: int = 0xF00,
    full_mask: int = 0xFFF,
) -> dict[str, Any]:
    """Execute one paired run under Condition A ('baseline') or Condition B ('hyperdesk')."""
    if condition not in ("A", "B"):
        raise ValueError(f"Unsupported condition: {condition!r}")

    script_path = str(Path(__file__).resolve())
    fg_proc: subprocess.Popen[str] | None = None
    bg_procs: list[subprocess.Popen[str]] = []
    cage: WinHardCpuCage | None = None
    pdh_sampler = WinPdhFaultSampler()
    timer_set = False
    stop_poll = threading.Event()
    sampled_ws: list[float] = []
    sampled_priv: list[float] = []

    try:
        fg_proc = subprocess.Popen(
            [
                sys.executable,
                script_path,
                "--worker",
                "fg",
                "--frames",
                str(int(frames)),
                "--fps",
                str(float(target_fps)),
                "--vertices",
                str(int(vertices)),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=_NO_WINDOW,
        )
        for wid in range(int(workers)):
            p = subprocess.Popen(
                [
                    sys.executable,
                    script_path,
                    "--worker",
                    "bg",
                    "--worker-id",
                    str(wid),
                    "--jobs",
                    str(int(jobs_per_worker)),
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                creationflags=_NO_WINDOW,
            )
            bg_procs.append(p)

        all_procs = [fg_proc, *bg_procs]
        for proc in all_procs:
            assert proc.stdout is not None
            ready = proc.stdout.readline().strip()
            if ready != "READY":
                err = proc.stderr.read() if proc.stderr else ""
                raise RuntimeError(f"Worker pid={proc.pid} failed startup: got={ready!r} err={err[:300]}")

        gov_meta: dict[str, Any] = {
            "fg_affinity_applied": False,
            "fg_priority_applied": False,
            "bg_affinity_applied_count": 0,
            "bg_eco_qos_count": 0,
            "bg_mem_priority_count": 0,
            "bg_priority_count": 0,
            "bg_hard_caged_count": 0,
            "hard_cage_cap_pct": hard_cage_cap_pct if condition == "B" else 100,
            "timer_res_ms": 0.0,
        }

        if condition == "A":
            for proc in all_procs:
                _win_set_affinity(proc.pid, full_mask)
                _win_set_eco_qos(proc.pid, False)
                _win_set_memory_priority(proc.pid, _MEMORY_PRIORITY_NORMAL)
                _win_set_io_priority(proc.pid, _IO_PRIORITY_NORMAL)
                _win_set_priority(proc.pid, _NORMAL_PRIORITY_CLASS)
        else:
            if os.name == "nt":
                gov_meta["timer_res_ms"] = _win_set_timer_resolution(True)
                timer_set = gov_meta["timer_res_ms"] > 0.0
            gov_meta["fg_affinity_applied"] = _win_set_affinity(fg_proc.pid, urban_mask)
            _win_set_eco_qos(fg_proc.pid, False)
            _win_set_memory_priority(fg_proc.pid, _MEMORY_PRIORITY_NORMAL)
            _win_set_io_priority(fg_proc.pid, _IO_PRIORITY_NORMAL)
            gov_meta["fg_priority_applied"] = _win_set_priority(fg_proc.pid, _ABOVE_NORMAL_PRIORITY_CLASS)

            cage = WinHardCpuCage(initial_cap_pct=hard_cage_cap_pct)
            for bp in bg_procs:
                if _win_set_affinity(bp.pid, industrial_mask):
                    gov_meta["bg_affinity_applied_count"] += 1
                if _win_set_eco_qos(bp.pid, True):
                    gov_meta["bg_eco_qos_count"] += 1
                if _win_set_memory_priority(bp.pid, _MEMORY_PRIORITY_VERY_LOW):
                    gov_meta["bg_mem_priority_count"] += 1
                _win_set_io_priority(bp.pid, _IO_PRIORITY_VERY_LOW)
                if _win_set_priority(bp.pid, _BELOW_NORMAL_PRIORITY_CLASS):
                    gov_meta["bg_priority_count"] += 1
                if cage.cage_pid(bp.pid):
                    gov_meta["bg_hard_caged_count"] += 1

        results: dict[Any, dict[str, Any]] = {}
        t_go_ref = [0.0]
        readers: list[threading.Thread] = [
            threading.Thread(target=_read_json_line, args=(fg_proc, results, "fg", t_go_ref), daemon=True)
        ]
        for idx, bp in enumerate(bg_procs):
            readers.append(threading.Thread(target=_read_json_line, args=(bp, results, idx, t_go_ref), daemon=True))

        def _poll_telemetry() -> None:
            while not stop_poll.is_set():
                pdh_sampler.sample()
                ws_sum = 0.0
                priv_sum = 0.0
                for proc in all_procs:
                    if proc.poll() is None:
                        m = query_process_memory(proc.pid)
                        if m:
                            ws_sum += float(m["working_set_mb"])
                            priv_sum += float(m["private_commit_mb"])
                if ws_sum > 0.0:
                    sampled_ws.append(ws_sum)
                    sampled_priv.append(priv_sum)
                stop_poll.wait(0.15)

        poll_th = threading.Thread(target=_poll_telemetry, daemon=True)
        pdh_sampler.sample()
        t_go_ref[0] = time.perf_counter()
        for th in readers:
            th.start()
        poll_th.start()

        for proc in all_procs:
            assert proc.stdin is not None
            proc.stdin.write("GO\n")
            proc.stdin.flush()
            proc.stdin.close()

        for th in readers:
            th.join(timeout=120.0)
        stop_poll.set()
        poll_th.join(timeout=2.0)
        pdh_sampler.sample()
        run_wall_s = max(0.001, time.perf_counter() - t_go_ref[0])

        for proc in all_procs:
            proc.wait(timeout=10.0)

        fg_res = results.get("fg")
        if not fg_res or "error" in fg_res:
            raise RuntimeError(f"FG worker failed: {fg_res}")
        bg_list = [results.get(i) for i in range(len(bg_procs))]
        if any((not b) or ("error" in b) for b in bg_list):
            raise RuntimeError(f"BG worker failed: {bg_list}")

        bg_build_time_s = round(max(float(b["parent_wall_s"]) for b in bg_list if b is not None), 4)
        bg_ws_end = sum(float(b["working_set_mb"]) for b in bg_list if b is not None)
        bg_peak_ws = sum(float(b["peak_working_set_mb"]) for b in bg_list if b is not None)
        bg_priv_end = sum(float(b["private_commit_mb"]) for b in bg_list if b is not None)
        total_delta_faults = int(fg_res["delta_page_faults"]) + sum(int(b["delta_page_faults"]) for b in bg_list if b is not None)

        live_ws_mean = round(sum(sampled_ws) / len(sampled_ws), 3) if sampled_ws else round(float(fg_res["working_set_mb"]) + bg_ws_end, 3)
        live_priv_mean = round(sum(sampled_priv) / len(sampled_priv), 3) if sampled_priv else round(float(fg_res["private_commit_mb"]) + bg_priv_end, 3)

        pdh_sum = pdh_sampler.summary()
        hard_faults_s = float(pdh_sum["hard_page_faults_per_s"])
        proc_delta_faults_s = round(total_delta_faults / run_wall_s, 3)
        soft_faults_s = round(max(0.0, proc_delta_faults_s - hard_faults_s), 3)

        return {
            "condition": condition,
            "label": "baseline" if condition == "A" else "hyperdesk",
            "run_wall_s": round(run_wall_s, 4),
            "fg": {
                "frames": int(fg_res["frames"]),
                "elapsed_s": float(fg_res["elapsed_s"]),
                "p50_ms": float(fg_res["p50_ms"]),
                "p95_ms": float(fg_res["p95_ms"]),
                "p99_ms": float(fg_res["p99_ms"]),
                "mean_ms": float(fg_res["mean_ms"]),
                "max_ms": float(fg_res["max_ms"]),
                "render_p50_ms": float(fg_res["render_p50_ms"]),
                "dropped_frames": int(fg_res["dropped_frames"]),
                "dropped_frames_pct": float(fg_res["dropped_frames_pct"]),
                "checksum": int(fg_res["checksum"]),
            },
            "bg": {
                "workers": len(bg_list),
                "jobs_per_worker": int(jobs_per_worker),
                "jobs_total": len(bg_list) * int(jobs_per_worker),
                "build_time_s": bg_build_time_s,
                "worker_max_elapsed_s": round(max(float(b["elapsed_s"]) for b in bg_list if b is not None), 4),
                "checksum": int(sum(int(b["checksum"]) for b in bg_list if b is not None)),
            },
            "memory": {
                "working_set_mb": live_ws_mean,
                "end_working_set_mb": round(float(fg_res["working_set_mb"]) + bg_ws_end, 3),
                "peak_working_set_mb": round(float(fg_res["peak_working_set_mb"]) + bg_peak_ws, 3),
                "private_commit_mb": round(max(live_priv_mean, float(fg_res["private_commit_mb"]) + bg_priv_end), 3),
                "fg_working_set_mb": float(fg_res["working_set_mb"]),
                "fg_private_commit_mb": float(fg_res["private_commit_mb"]),
                "bg_working_set_mb": round(bg_ws_end, 3),
                "bg_private_commit_mb": round(bg_priv_end, 3),
                "total_page_fault_count": total_delta_faults,
            },
            "faults": {
                "hard_page_faults_per_s": hard_faults_s,
                "pages_input_per_s": float(pdh_sum["pages_input_per_s"]),
                "system_total_page_faults_per_s": float(pdh_sum["system_total_page_faults_per_s"]),
                "system_soft_page_faults_per_s": float(pdh_sum["system_soft_page_faults_per_s"]),
                "proc_delta_faults_per_s": proc_delta_faults_s,
                "soft_page_faults_per_s": soft_faults_s,
                "pdh_active": bool(pdh_sum["pdh_active"]),
                "pdh_samples": int(pdh_sum["samples"]),
            },
            "governance": gov_meta,
        }
    finally:
        stop_poll.set()
        pdh_sampler.close()
        if timer_set:
            _win_set_timer_resolution(False)
        if cage is not None:
            cage.close()
        for proc in ([fg_proc] if fg_proc else []) + bg_procs:
            try:
                if proc.poll() is None:
                    proc.terminate()
                    proc.wait(timeout=3.0)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
            for pipe in (proc.stdin, proc.stdout, proc.stderr):
                if pipe is not None:
                    try:
                        pipe.close()
                    except Exception:
                        pass


def run_ab_experiment(
    *,
    pairs: int = 10,
    frames: int = 180,
    target_fps: float = 60.0,
    vertices: int = 3200,
    workers: int | None = None,
    jobs_per_worker: int = 210,
    hard_cage_cap_pct: int = 35,
    cooldown_s: float = 0.25,
    isolate_live_daemon: bool = True,
    include_vram_check: bool = True,
    out_path: Path | None = None,
) -> dict[str, Any]:
    """Run the full N-pair strictly alternating HyperDesk A/B experiment and write JSON results."""
    cpu_threads = max(1, os.cpu_count() or 4)
    n_workers = int(workers) if workers is not None else min(12, max(6, cpu_threads))
    hd = HyperDeskEngine()
    try:
        urban_mask, industrial_mask, full_mask = hd._compute_core_masks()
    finally:
        hd.close()

    schedule = generate_ab_schedule(pairs)
    pairs_data: list[dict[str, Any]] = []

    with _LiveDaemonIsolator(enabled=isolate_live_daemon) as iso:
        live_isolated = iso.isolated
        for idx, order_pair in enumerate(schedule, 1):
            order_str = "".join(order_pair)
            pair_runs: dict[str, dict[str, Any]] = {}
            for cond in order_pair:
                pair_runs[cond] = run_single_condition(
                    cond,
                    frames=frames,
                    target_fps=target_fps,
                    vertices=vertices,
                    workers=n_workers,
                    jobs_per_worker=jobs_per_worker,
                    hard_cage_cap_pct=hard_cage_cap_pct,
                    urban_mask=urban_mask,
                    industrial_mask=industrial_mask,
                    full_mask=full_mask,
                )
                if cooldown_s > 0.0:
                    time.sleep(cooldown_s)

            run_a = pair_runs["A"]
            run_b = pair_runs["B"]
            deltas = compute_pair_deltas(run_a, run_b)
            pairs_data.append({
                "pair": idx,
                "order": order_str,
                "run_a": run_a,
                "run_b": run_b,
                "deltas": deltas,
            })
            print(
                f"[pair {idx:02d}/{len(schedule)} {order_str}] "
                f"p99 A={run_a['fg']['p99_ms']:.2f}ms B={run_b['fg']['p99_ms']:.2f}ms "
                f"(red={deltas['p99_reduction_pct']:+.1f}%) | "
                f"build A={run_a['bg']['build_time_s']:.2f}s B={run_b['bg']['build_time_s']:.2f}s "
                f"(delta={deltas['build_time_delta_pct']:+.1f}%)",
                flush=True,
            )

    agg = summarize_pairs(pairs_data)
    vram_check: dict[str, Any] | None = None
    if include_vram_check:
        vram = VramCompressedSwap()
        try:
            vram_check = vram.benchmark(payload_mb=4.0)
        finally:
            vram.close()

    report: dict[str, Any] = {
        "schema": "chimera.hyperdesk_ab.v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "host": {
            "os": os.name,
            "platform": sys.platform,
            "cpu_threads": cpu_threads,
            "urban_mask_hex": hex(urban_mask),
            "industrial_mask_hex": hex(industrial_mask),
            "full_mask_hex": hex(full_mask),
            "hard_cage_cap_pct": int(hard_cage_cap_pct),
            "live_daemon_isolated": live_isolated,
        },
        "config": {
            "pairs": len(schedule),
            "schedule_orders": ["".join(p) for p in schedule],
            "frames": int(frames),
            "target_fps": float(target_fps),
            "frame_budget_ms": round(_FRAME_BUDGET_MS, 4),
            "vertices": int(vertices),
            "workers": n_workers,
            "jobs_per_worker": int(jobs_per_worker),
            "cooldown_s": float(cooldown_s),
        },
        "decision": agg["decision"],
        "decision_rule": agg["decision_rule"],
        "summary": agg["summary"],
        "pairs": pairs_data,
        "vram_swap_check": vram_check,
        "vram_yield_investigation": {
            "target_ms": 30.0,
            "baseline_live_omega_bench_ms": 32.097,
            "root_cause": (
                "cuMemFree_v2 takes ~0.2-0.4 ms, whereas cuCtxDestroy_v2 on Windows WDDM "
                "takes ~32-47 ms to tear down the ~49 MB CUDA driver context allocation. "
                "Keeping a pre-warmed context without cuCtxDestroy_v2 retains ~49 MB VRAM "
                "(violating vram_retained_mb == 0.0), so yield_vram retains cuCtxDestroy_v2."
            ),
        },
    }

    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description="CHIMERA-HYPERDESK controlled alternating A/B benchmark")
    ap.add_argument("--worker", choices=("fg", "bg"), default=None)
    ap.add_argument("--frames", type=int, default=180)
    ap.add_argument("--fps", type=float, default=60.0)
    ap.add_argument("--vertices", type=int, default=3200)
    ap.add_argument("--worker-id", type=int, default=0)
    ap.add_argument("--jobs", type=int, default=210)
    ap.add_argument("--pairs", type=int, default=10)
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--hard-cage-cap", type=int, default=35)
    ap.add_argument("--cooldown-s", type=float, default=0.25)
    ap.add_argument("--no-isolate-daemon", action="store_true")
    ap.add_argument("--no-vram-check", action="store_true")
    ap.add_argument("--out", default=str(_REPO_ROOT / "tasks" / "hyperdesk_ab_results.json"))
    args = ap.parse_args()

    if args.worker == "fg":
        _worker_fg(args.frames, args.fps, args.vertices)
        return 0
    if args.worker == "bg":
        _worker_bg(args.worker_id, args.jobs)
        return 0

    report = run_ab_experiment(
        pairs=args.pairs,
        frames=args.frames,
        target_fps=args.fps,
        vertices=args.vertices,
        workers=args.workers,
        jobs_per_worker=args.jobs,
        hard_cage_cap_pct=args.hard_cage_cap,
        cooldown_s=args.cooldown_s,
        isolate_live_daemon=not args.no_isolate_daemon,
        include_vram_check=not args.no_vram_check,
        out_path=Path(args.out),
    )
    print(json.dumps({
        "decision": report["decision"],
        "decision_rule": report["decision_rule"],
        "p99_reduction_pct": report["summary"]["p99_reduction_pct"],
        "build_time_delta_pct": report["summary"]["build_time_delta_pct"],
        "out": str(args.out),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
