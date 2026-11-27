"""Measure interactive app process trees over a bounded, read-only Windows observation."""

import argparse
from collections import defaultdict
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
from statistics import median
import time

import psutil


MIB = 1024 ** 2


class PerformanceInfo(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        *((name, ctypes.c_size_t) for name in (
            "commit_total", "commit_limit", "commit_peak", "physical_total", "physical_available",
            "system_cache", "kernel_total", "kernel_paged", "kernel_nonpaged", "page_size")),
        ("handle_count", wintypes.DWORD), ("process_count", wintypes.DWORD), ("thread_count", wintypes.DWORD),
    ]


def memory_state():
    info = PerformanceInfo()
    info.cb = ctypes.sizeof(info)
    psapi = ctypes.WinDLL("psapi.dll", use_last_error=True)
    get_info = psapi.GetPerformanceInfo
    get_info.argtypes = [ctypes.POINTER(PerformanceInfo), wintypes.DWORD]
    get_info.restype = wintypes.BOOL
    if not get_info(ctypes.byref(info), info.cb):
        raise ctypes.WinError(ctypes.get_last_error())
    return {
        label + "_mib": round(getattr(info, label) * info.page_size / MIB, 2)
        for label in ("commit_total", "commit_limit", "physical_total", "physical_available")
    }


def enumerate_processes():
    snapshot = {}
    denied = 0
    attributes = ["pid", "ppid", "name", "create_time", "memory_info", "cpu_times", "io_counters"]
    for proc in psutil.process_iter(attributes):
        try:
            meta = proc.info
            if meta["pid"] in {0, 4}:
                continue
            if not meta["name"] or any(meta[k] is None for k in attributes):
                denied += 1
                continue
            cpu = meta["cpu_times"]
            snapshot[meta["pid"]] = {
                "name": meta["name"].lower(), "ppid": meta["ppid"], "created": meta["create_time"],
                "private": meta["memory_info"].private, "cpu": cpu.user + cpu.system,
                "written": meta["io_counters"].write_bytes,
            }
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            denied += 1
    return snapshot, denied


def image_family(pid, snapshot, families):
    path = []
    current = pid
    while current in snapshot and current not in families:
        if current in path:
            break
        info = snapshot[current]
        path.append(current)
        parent = snapshot.get(info["ppid"])
        # Parent PIDs can be recycled while old children continue to run.
        if parent is None or parent["created"] > info["created"]:
            break
        # Windows shells and process managers are boundaries between user apps.
        if parent["name"] in {
            "explorer.exe", "services.exe", "svchost.exe", "wininit.exe", "winlogon.exe",
            "smss.exe", "csrss.exe", "wmiprvse.exe", "taskhostw.exe", "userinit.exe",
        }:
            break
        current = info["ppid"]
    family = families.get(current) or snapshot[path[-1]]["name"]
    for visited in path:
        families[visited] = family
    return family


def fold(current, previous):
    families = {}
    totals = defaultdict(lambda: {"private_mib": 0, "processes": 0, "cpu_seconds": 0,
                                  "process_write_mib": 0, "matched_processes": 0})
    for pid, info in current.items():
        group = totals[image_family(pid, current, families)]
        group["private_mib"] += info["private"] / MIB
        group["processes"] += 1
        old = previous.get(pid)
        if old and old["created"] == info["created"]:
            group["matched_processes"] += 1
            group["cpu_seconds"] += max(0, info["cpu"] - old["cpu"])
            group["process_write_mib"] += max(0, info["written"] - old["written"]) / MIB
    return {name: {k: round(n, 4) for k, n in v.items()} for name, v in totals.items()}


def sample(seconds, interval):
    start_utc = datetime.now(timezone.utc).isoformat()
    started = time.monotonic()
    rows = []
    previous = {}
    baseline = None
    planned = 1 + math.ceil(seconds / interval)
    for i in range(planned):
        if baseline is not None:
            due = baseline + min(seconds, i * interval)
            time.sleep(max(0, due - time.monotonic()))
        scan_start = time.monotonic()
        current, denied = enumerate_processes()
        machine = memory_state()
        stamp = time.monotonic()
        if baseline is None:
            baseline = stamp
        rows.append({
            "elapsed_s": round(stamp - baseline, 3), "scan_s": round(stamp - scan_start, 3),
            "readable_processes": len(current), "unavailable_or_exited": denied, "machine": machine,
            "families": fold(current, previous),
        })
        previous = current
    summary = []
    for name in sorted({k for row in rows for k in row["families"]}):
        groups = [r["families"].get(name, {}) for r in rows]
        summary.append({
            "image_family": name, "private_mib_median": round(median(g.get("private_mib", 0) for g in groups), 2),
            "private_mib_peak": round(max(g.get("private_mib", 0) for g in groups), 2),
            "processes_peak": max(g.get("processes", 0) for g in groups),
            "cpu_seconds_observed": round(sum(g.get("cpu_seconds", 0) for g in groups), 3),
            "process_write_mib_observed": round(sum(g.get("process_write_mib", 0) for g in groups), 3),
        })
    return {
        "schema": "chimera.windows.app-observation/1", "started_utc": start_utc,
        "finished_utc": datetime.now(timezone.utc).isoformat(), "interval_s": interval,
        "observation_seconds": rows[-1]["elapsed_s"], "recorder_wall_seconds": round(time.monotonic() - started, 3),
        "samples": rows, "summary": sorted(summary, key=lambda r: -r["private_mib_median"]),
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "scope": [
            "Live workstation. Group by the highest recorded ancestor below a Windows shell or service manager.",
            "Identically named executable families combine. A missing or recycled parent creates a new root.",
            "Private commit and machine commit are different counters. Per-process CPU and logical I/O deltas "
            "cover only identities present in consecutive samples. Hardware writes and energy are unmeasured.",
            "A short observation does not measure per-day savings, equivalence of workflows or CAD smoothness.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=60)
    parser.add_argument("--interval", type=float, default=5)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if (os.name != "nt" or not 1 <= args.seconds <= 86400 or not 0.5 <= args.interval <= args.seconds
            or args.seconds / args.interval > 1440):
        parser.error("requires Windows, 1 s to 24 h duration and at most 1441 snapshots")
    report = sample(args.seconds, args.interval)
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"samples": len(report["samples"]), "top": report["summary"][:8]}, indent=2))


if __name__ == "__main__":
    main()
