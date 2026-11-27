"""A bounded SHA-256-only stdio workload for comparing existing routes to svhome."""

import argparse
import base64
import contextlib
import ctypes
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import shlex
import sys
import time
import zipfile


REQUEST_BYTES = 400
MAX_FRAMES = 4
POLICY = {
    "job_disk_mib": 16, "job_memory_mib": 128, "cpu_quota_pct": 50,
    "max_tasks": 24, "runtime_seconds": 25, "service_samples": 5,
    "service_urls": ["http://127.0.0.1:8787/api/health"],
}

# Read the archive before systemd inherits stdin. The controller waits for a
# ready event before writing its first hash frame, so buffered readers cannot
# consume bytes intended for the worker.
BOOTSTRAP = """
import base64, json, pathlib, subprocess, sys, tempfile
with tempfile.TemporaryDirectory(prefix="chimera-hash-trial-") as root:
    line = sys.stdin.buffer.readline(65537)
    if not line.endswith(b"\\n") or len(line) > 65536:
        raise ValueError("bad_archive_frame")
    package = pathlib.Path(root, "trial.zip")
    package.write_bytes(base64.b64decode(line.strip(), validate=True))
    sys.path.insert(0, str(package))
    from peer_guard import AdmissionDeferred, DEFAULT_ROOT, launch_policy, limited_command
    try:
        cfg = launch_policy(DEFAULT_ROOT, json.loads(sys.argv[1]))
        args = limited_command([sys.executable, "-I", "-B", "-S", "-u", str(package), "--guarded"], cfg)
        outcome = subprocess.run(args, stderr=subprocess.PIPE, timeout=35)
        if outcome.returncode:
            err = outcome.stderr.decode(errors="replace")
            busy = "chimera-peer-guest.service" in err and ("already exists" in err or "already loaded" in err)
            print(json.dumps({"type":"failed","reason":"guest_slot_busy" if busy else "guest_exit",
                              "detail":err[-260:]}), flush=True)
            sys.exit(75 if busy else 1)
    except AdmissionDeferred as exc:
        print(json.dumps({"type":"failed","reason":exc.reason}), flush=True)
        sys.exit(75)
"""


def rss_bytes():
    if os.name == "nt":
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD)] + [
                (name, ctypes.c_size_t) for name in (
                    "peak_ws", "ws", "peak_paged", "paged", "peak_nonpaged",
                    "nonpaged", "pagefile", "peak_pagefile")]

        value = Counters()
        value.cb = ctypes.sizeof(value)
        kernel = ctypes.windll.kernel32
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        query = ctypes.windll.psapi.GetProcessMemoryInfo
        query.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
        if not query(kernel.GetCurrentProcess(), ctypes.byref(value), value.cb):
            raise OSError("GetProcessMemoryInfo failed")
        return {"current": value.ws, "peak": value.peak_ws}
    rows = {k: v.strip().split() for k, v in
            (l.split(":", 1) for l in Path("/proc/self/status").read_text().splitlines())}
    if rows["VmRSS"][1] != "kB" or rows["VmHWM"][1] != "kB":
        raise ValueError("unknown /proc units")
    return {"current": int(rows["VmRSS"][0]) * 1024, "peak": int(rows["VmHWM"][0]) * 1024}


def tell(**event):
    print(json.dumps(event, separators=(",", ":"), allow_nan=False), flush=True)


def serve(use_guard):
    if use_guard:
        from peer_guard import DEFAULT_ROOT, reserve, recheck_running
        slot = reserve(DEFAULT_ROOT, POLICY)
    elif os.name == "nt":
        slot = contextlib.nullcontext(None)
    else:
        raise ValueError("unguarded_computation_is_windows_only")

    with slot as admission:
        if admission is not None:
            if not admission["limits_verified"]:
                raise RuntimeError("unverified_cgroup")
            import select
        confirmed = None if admission is None else {
            "limits_verified": True, "cgroup": admission["health"]["cgroup"],
            "memory_max": admission["health"]["limits"]["memory_max"],
            "ram_reserve_mib": admission["effective_policy"]["ram_reserve_mib"],
            "disk_reserve_mib": admission["effective_policy"]["disk_reserve_mib"],
            "services": sorted(admission["health"]["service_p95_ms"]),
        }
        tell(type="ready", host=platform.node(), os=platform.system(), pid=os.getpid(),
             python=platform.python_version(), guard=confirmed, rss_bytes=rss_bytes())
        for position in range(MAX_FRAMES):
            if admission is not None and not select.select([sys.stdin], [], [], 4.0)[0]:
                raise ValueError("idle_deadline")
            raw = sys.stdin.buffer.readline(2049)
            if not raw:
                break
            if len(raw) > 2048 or not raw.endswith(b"\n"):
                raise ValueError("oversized_or_incomplete_frame")
            frame = json.loads(raw)
            if set(frame) != {"id", "payload"} or not isinstance(frame["id"], str) or len(frame["id"]) != 24:
                raise ValueError("invalid_hash_frame")
            bytes.fromhex(frame["id"])
            data = base64.b64decode(frame["payload"], validate=True)
            if len(data) != REQUEST_BYTES:
                raise ValueError("expected_exactly_400_bytes")
            entry = time.perf_counter_ns()
            if admission is not None:
                health = recheck_running(DEFAULT_ROOT, admission["effective_policy"])
                service_p95 = health["service_p95_ms"]
            else:
                service_p95 = {}
            work = time.perf_counter_ns()
            digest = hashlib.sha256(data).hexdigest()
            stop = time.perf_counter_ns()
            tell(type="digest", id=frame["id"], position=position, sha256=digest,
                 check_us=(work-entry)/1000, sha_us=(stop-work)/1000, service_ms=service_p95)
        tell(type="tail", pid=os.getpid(), rss_bytes=rss_bytes())


def bundle():
    me = Path(__file__).resolve()
    guard = me.parents[1] / "chimera_tp" / "platform" / "peer_guard.py"
    data = io.BytesIO()
    files = {"__main__.py": me.read_bytes(), "peer_guard.py": guard.read_bytes()}
    with zipfile.ZipFile(data, "w") as archive:
        for name, contents in files.items():
            archive.writestr(zipfile.ZipInfo(name), contents, compress_type=zipfile.ZIP_DEFLATED)
    raw = data.getvalue()
    cmd = shlex.join(["python3", "-I", "-B", "-S", "-u", "-c", BOOTSTRAP,
                      json.dumps(POLICY, separators=(",", ":"))])
    tell(shell=cmd, base64=base64.b64encode(raw).decode("ascii"),
         package_sha256=hashlib.sha256(raw).hexdigest(), package_bytes=len(raw),
         sources={k: hashlib.sha256(v).hexdigest() for k, v in files.items()})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    for flag in ("bundle", "guarded", "local"):
        mode.add_argument("--" + flag, action="store_true")
    options = parser.parse_args()
    if options.bundle:
        bundle()
    elif options.guarded:
        from peer_guard import AdmissionDeferred
        try:
            serve(True)
        except AdmissionDeferred as exc:
            tell(type="failed", reason=exc.reason)
            sys.exit(75)
    else:
        serve(False)
