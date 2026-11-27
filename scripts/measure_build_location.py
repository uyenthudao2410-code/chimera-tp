"""Compare an unchanged CPython compile workload on this host and an SSH peer."""

import argparse
import ast
import base64
import hashlib
import json
from pathlib import Path
import re
import statistics
import subprocess
import sys
import time
import zlib


WORKER = """
import hashlib, json, sys, time
bundle = json.load(sys.stdin)
files = bundle["files"]
expected = hashlib.sha256(json.dumps(files, ensure_ascii=True, separators=(",",":")).encode()).hexdigest()
start = time.perf_counter()
cpu_start = time.process_time()
units = 0
for _ in range(bundle["rounds"]):
    for filename, source in files:
        compile(source, filename, "exec", dont_inherit=True)
        units += 1
print(json.dumps({"digest":expected,"units":units,"cpu_s":time.process_time()-cpu_start,
                  "work_s":time.perf_counter()-start,"python":sys.version.split()[0]}))
"""


def timed(command: list[str], data: bytes, checkout: Path) -> dict:
    # GetProcessTimes reads the completed local process (Python or ssh.exe). It
    # excludes the orchestrator, the SSH server and unrelated desktop processes.
    start = time.perf_counter()
    result = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, cwd=checkout)
    stdout, stderr = result.communicate(data, timeout=75)
    wall = time.perf_counter() - start
    if result.returncode:
        raise RuntimeError(stderr.decode(errors="replace")[-600:])
    import ctypes
    from ctypes import wintypes
    times = [wintypes.FILETIME() for _ in range(4)]
    get_times = ctypes.windll.kernel32.GetProcessTimes
    get_times.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    if not get_times(wintypes.HANDLE(int(result._handle)), *(ctypes.byref(t) for t in times)):
        raise ctypes.WinError()
    local_cpu = sum((t.dwHighDateTime << 32) + t.dwLowDateTime for t in times[2:]) / 10_000_000
    return {**json.loads(stdout), "wall_s": round(wall, 4), "windows_child_cpu_s": round(local_cpu, 4)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--peer", default="svhome")
    parser.add_argument("--pairs", type=int, default=5)
    parser.add_argument("--rounds", type=int, default=50)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", args.peer):
        parser.error("expected an SSH hostname")
    if not (1 <= args.pairs <= 15 and 1 <= args.rounds <= 100):
        parser.error("pairs 1..15, rounds 1..100")
    checkout = Path(__file__).resolve().parents[1]
    paths = ["chimera_tp/native.py", "chimera_tp/platform/hyper_desk.py",
             "chimera_tp/platform/phantom_silicon.py", "chimera_tp/platform/substrate.py"]
    files = [[p, (checkout / p).read_text(encoding="utf8")] for p in paths]
    for path, body in files:
        ast.parse(body, filename=path)
    encoded = json.dumps({"files": files, "rounds": args.rounds}, ensure_ascii=True).encode()
    digest = hashlib.sha256(json.dumps(files, ensure_ascii=True, separators=(",", ":")).encode()).hexdigest()
    # Source arrives on SSH stdin. It is compiled as data and never executed.
    worker = base64.b64encode(zlib.compress(WORKER.encode())).decode()
    remote = f"""python3 -I -S -c "import zlib,base64;exec(zlib.decompress(base64.b64decode('{worker}')))" """
    commands = {"local": [sys.executable, "-I", "-S", "-c", WORKER],
                "remote": ["ssh", "-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", args.peer, remote]}
    rows = []
    for pair in range(args.pairs):
        for site in (("local", "remote") if pair % 2 == 0 else ("remote", "local")):
            metric = timed(commands[site], encoded, checkout)
            assert metric["digest"] == digest and metric["units"] == len(files) * args.rounds
            rows.append({"pair": pair + 1, "site": site, **metric})
    summary = {site: {key: round(statistics.median(r[key] for r in rows if r["site"] == site), 4)
                      for key in ("wall_s", "work_s", "cpu_s", "windows_child_cpu_s")} for site in commands}
    print(json.dumps({"files": paths, "bytes_per_run": len(encoded), "summary": summary, "rows": rows}))


if __name__ == "__main__":
    main()
