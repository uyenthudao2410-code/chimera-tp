"""Gate the Windows CUDA worker through the real CLI and loopback HTTP routes."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import subprocess
import sys
import tempfile
import threading

sys.path.insert(0, str(Path(__file__).resolve().parent))
from measure_daemon_cli import request
from verify_node_source_parity import inventory, windows_runtime_root


def still_running(pid):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x00100000, False, pid)
    if not handle:
        if ctypes.get_last_error() == 87:
            return False
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        status = kernel.WaitForSingleObject(handle, 0)
        if status not in (0, 258):
            raise ctypes.WinError()
        return status == 258
    finally:
        kernel.CloseHandle(handle)


def driver_loaded(pid):
    # PowerShell reads the OS module list outside the measured daemon.
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
         "$ErrorActionPreference='Stop'; $m=(Get-Process -Id " + str(pid) + ").Modules; "
         "if (!$m.Count) {throw 'module enumeration failed'}; "
         "if ($m.ModuleName -contains 'nvcuda.dll') {'true'} else {'false'}"],
        capture_output=True, text=True, check=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
    return json.loads(completed.stdout)


def read_port(child):
    mailbox = queue.Queue()

    def listen():
        for line in child.stdout:
            match = re.search(rb"Daemon listening at http://127\.0\.0\.1:(\d+)", line)
            if match:
                mailbox.put(int(match[1]))
                return
        mailbox.put(None)

    threading.Thread(target=listen, daemon=True).start()
    port = mailbox.get(timeout=25)
    if not port or port == 9780:
        raise RuntimeError("private daemon did not bind an ephemeral loopback port")
    return port


def measure(root, rows, n):
    root = root.resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix="chimera-ptx-gate-") as tmp:
        home = Path(tmp)
        cfg = dict(node_name="cuda-private-gate", role="server", dashboard_bind="127.0.0.1:0",
                   beam_port=0, rpc_v4_port=0, rpc_v6_port=-1, query_port=0, immortal_v4_port=0,
                   immortal_v6_port=-1, warp_port=-1, edge_proxy_port=-1, nat_punch_port=0,
                   phantom_enabled=False, peer_ipv4="", peer_ipv6="", search_roots=[],
                   allowed_query_roots=[tmp], edge_targets={})
        (home / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
        env = {**os.environ, **dict.fromkeys(("HOME", "APPDATA", "LOCALAPPDATA", "USERPROFILE"), tmp)}
        executable = Path(__file__).with_name("measure_daemon_cli.py").resolve(strict=True)
        cmd = [sys.executable, "-I", "-B", "-S", str(executable), "--service", str(root), tmp]
        with tempfile.TemporaryFile() as err, subprocess.Popen(
                cmd, env=env, cwd=root, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=err,
                creationflags=subprocess.CREATE_NO_WINDOW) as child:
            try:
                port = read_port(child)
                samples = []
                workers = []

                def sample(label):
                    b = request(port, "/.well-known/chimera.json")
                    if b["node_name"] != cfg["node_name"] or b["pid"] != child.pid:
                        raise RuntimeError("beacon PID or identity mismatch")
                    z = b["zero_weight"]
                    samples.append({"stage": label, "rss": z["daemon_rss_bytes"], "peak": z["daemon_peak_rss_bytes"]})

                def worker(label, result):
                    w = result["worker"]
                    if (result["execution"] != "windows_cuda_worker" or not w["exited"]
                            or w["pid"] == child.pid or w["peak_bytes"] <= 0 or still_running(w["pid"])):
                        raise RuntimeError("worker did not exit or reported invalid counters: " + label)
                    workers.append({"operation": label, **w})

                sample("boot")
                if windows_runtime_root(child.pid) != root:
                    raise RuntimeError("trial daemon loaded native library from a different release")
                status = request(port, "/v1/vgpu/status")
                caps = status["ptx_jit"]
                if not caps["available"]:
                    raise RuntimeError("no CUDA device reported by private daemon")
                worker("driver discovery", caps)
                sample("status")
                reference = sum((i % 13 - 6) * (i % 7 - 3) for i in range(n))
                dot = request(port, "/v1/vgpu/ptx-bench", {"n": n, "force": True})
                if dot["engine"] != "win_nvcuda_ptx" or dot["n"] != n or dot["dot"] != reference:
                    raise RuntimeError(f"dot product GPU gate: engine={dot['engine']}, reason={dot.get('yield_reason')}")
                worker("dot", dot)
                sample("dot")
                vsa = request(port, "/v1/aeon/evolve", {"action": "green_ptx_bench", "rows": rows})
                gpu = vsa["green_ptx_gpu"]
                if not gpu.get("available") or not gpu["bit_exact_match_vs_cpu"] or gpu["vram_retained_mb"] != 0.0:
                    raise RuntimeError("VSA worker did not match native CPU or release VRAM: " + str(gpu))
                worker("VSA", vsa)
                sample("vsa")
                with ThreadPoolExecutor(max_workers=2) as pool:
                    simultaneous = list(pool.map(lambda _: request(port, "/v1/vgpu/ptx-bench",
                                                                    {"n": 64, "force": True}), range(2)))
                small_reference = sum((i % 13 - 6) * (i % 7 - 3) for i in range(64))
                for item in simultaneous:
                    if item["dot"] != small_reference:
                        raise RuntimeError("wrong concurrent result")
                    worker("concurrent dot", item)
                sample("concurrent")
                mapped = driver_loaded(child.pid)
                if mapped or max(stage["peak"] for stage in samples) >= 80 * 1024**2:
                    raise RuntimeError(f"parent memory/driver gate: {samples}, driver={mapped}")
                return {"daemon_pid": child.pid, "device": caps["device"], "sm": caps["sm"],
                        "n": n, "dot": dot["dot"], "cpu_dot": reference, "rows": rows,
                        "vsa": gpu, "samples": samples, "workers": workers, "driver_in_daemon": mapped}
            finally:
                child.stdin.close()
                try:
                    child.wait(timeout=12)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=5)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--trials", type=int, choices=range(1, 6), default=3)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("requires the Windows NVIDIA workstation")
    files = inventory(args.root)
    trials = [measure(args.root, rows, n) for rows, n in [(64, 4096), (2048, 65536), (32768, 262144),
                                                            (1024, 32768), (256, 8192)][:args.trials]]
    if inventory(args.root) != files:
        raise RuntimeError("trial source changed during measurement")
    receipt = {"schema": "chimera.windows-cuda-worker-api/1", "root": str(args.root.resolve()),
               "tree": hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
               "collector_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), "trials": trials}
    if args.out:
        with args.out.open("x", encoding="utf-8", newline="\n") as out:
            json.dump(receipt, out, indent=2)
            out.write("\n")
    print(json.dumps([{"pid": t["daemon_pid"], "rows": t["rows"], "n": t["n"],
                       "daemon_peak": max(s["peak"] for s in t["samples"]),
                       "worker_peak": max(w["peak_bytes"] for w in t["workers"])} for t in trials]))
