"""Read both application trees, live beacons and OS process RSS without changing either service."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import urllib.error
import urllib.request


def inventory(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((root / "chimera_tp").rglob("*.py")) if p.is_file()}


def windows_runtime_root(pid):
    """Locate the service's mapped package DLL even when its release is outside the worktree."""
    import ctypes as ct
    from ctypes import wintypes as w

    k32 = ct.WinDLL("kernel32", use_last_error=True)
    psapi = ct.WinDLL("psapi", use_last_error=True)
    k32.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    k32.OpenProcess.restype = w.HANDLE
    k32.CloseHandle.argtypes = [w.HANDLE]
    psapi.EnumProcessModulesEx.argtypes = [w.HANDLE, ct.POINTER(w.HMODULE), w.DWORD,
                                          ct.POINTER(w.DWORD), w.DWORD]
    psapi.GetModuleFileNameExW.argtypes = [w.HANDLE, w.HMODULE, w.LPWSTR, w.DWORD]
    handle = k32.OpenProcess(0x0400 | 0x0010, False, pid)
    if not handle:
        raise OSError(ct.get_last_error(), "OpenProcess")
    try:
        capacity = 128
        while True:
            modules = (w.HMODULE * capacity)()
            used = w.DWORD()
            if not psapi.EnumProcessModulesEx(handle, modules, ct.sizeof(modules), ct.byref(used), 3):
                raise OSError(ct.get_last_error(), "EnumProcessModulesEx")
            count = used.value // ct.sizeof(w.HMODULE)
            if count <= capacity:
                break
            capacity = count + 32
        buf = ct.create_unicode_buffer(32768)
        for module in modules[:count]:
            if psapi.GetModuleFileNameExW(handle, module, buf, len(buf)):
                path = Path(buf.value)
                if path.name.lower() == "_chimera_core.dll" and path.parent.name.lower() == "chimera_tp":
                    return path.resolve(strict=True).parent.parent
    finally:
        k32.CloseHandle(handle)
    raise OSError("no mapped CHIMERA native library in the serving PID")


READ_PEER = """
import hashlib,json,pathlib,urllib.request
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
b=json.load(opener.open("http://127.0.0.1:9780/.well-known/chimera.json",timeout=4))
pid=b["pid"]
root=pathlib.Path(f"/proc/{pid}/cwd").resolve(strict=True)
if not (root/"chimera_tp/__init__.py").is_file():
    raise SystemExit("service process working directory does not contain expected package")
files={p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
       for p in sorted((root/"chimera_tp").rglob("*.py")) if p.is_file()}
native=root/"chimera_tp/_chimera_core.so"
mapped=any(line.endswith(" "+str(native)) for line in pathlib.Path(f"/proc/{pid}/maps").read_text().splitlines())
status=pathlib.Path(f"/proc/{pid}/status").read_text().splitlines()
memory={s.split(":")[0]: int(s.split()[1])*1024 for s in status if s.startswith(("VmRSS:", "VmHWM:"))}
print(json.dumps({"files":files,"pid":pid,"node":b["node_name"],"version":b["version"],
                  "package_version":b["package_version"],"root":str(root),"process_memory_bytes":memory,
                   "mapped_native_sha256":hashlib.sha256(native.read_bytes()).hexdigest() if mapped else None,
                  "evidence_summary":b.get("evidence_summary",{})}))
"""


def evidence_counts(summary):
    # Early beacons nested these counters. Current ones place them directly in the summary.
    counters = summary.get("counts", summary)
    return {key: counters[key] for key in ("verified", "unverified", "violated", "disabled")
            if type(counters.get(key)) is int}


def read_peer(peer):
    result = subprocess.run(
        ["ssh", "-T", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
         "-o", "ConnectTimeout=5", peer, "python3 -I -B -S -"],
        input=READ_PEER.encode(), capture_output=True, timeout=20, check=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return json.loads(result.stdout)


def run(peer):
    repo = Path(__file__).resolve().parents[1]
    linux = read_peer(peer)
    linux["evidence_counts"] = evidence_counts(linux.pop("evidence_summary"))
    their_files = linux.pop("files")
    loopback = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    # File inventory remains valid while a service is offline. A cached beacon is not a live response.
    win = {"reachable": False}
    for attempt in range(3):
        try:
            with loopback.open("http://127.0.0.1:9780/.well-known/chimera.json", timeout=3) as response:
                win = {**json.load(response), "reachable": True}
            break
        except (OSError, urllib.error.URLError) as exc:
            win["last_error"] = str(exc)
            if attempt < 2:
                time.sleep(1)
    windows_root, windows_basis = repo, "workspace_on_disk_only"
    if sys.platform == "win32" and win.get("pid"):
        try:
            windows_root = windows_runtime_root(win["pid"])
            windows_basis = "directory_of_native_library_mapped_by_serving_pid"
        except OSError as exc:
            win["root_error"] = str(exc)
    own_files = inventory(windows_root)
    win_memory = None
    win_http = {}
    if win["reachable"]:
        for route in ("/api/health", "/v1/truth-matrix"):
            try:
                with loopback.open("http://127.0.0.1:9780" + route, timeout=4) as response:
                    win_http[route] = response.status
            except urllib.error.HTTPError as exc:
                win_http[route] = exc.code
            except OSError as exc:
                win_http[route] = str(exc)
    if sys.platform == "win32" and win.get("pid"):
        if str(repo) not in sys.path:
            sys.path.insert(0, str(repo))
        from scripts.bench_hyperdesk_ab import query_process_memory

        memory = query_process_memory(win["pid"])
        if memory is not None:
            win_memory = {"current": memory["working_set_mb"], "process_peak": memory["peak_working_set_mb"]}

    def compare(prefix):
        ours = {k for k in own_files if k.startswith(prefix)}
        theirs = {k for k in their_files if k.startswith(prefix)}
        changed = sorted(k for k in ours & theirs if own_files[k] != their_files[k])
        return {"windows_files": len(ours), "linux_files": len(theirs), "windows_only": sorted(ours-theirs),
                "linux_only": sorted(theirs-ours), "identical": len(ours & theirs)-len(changed),
                "different": {k: {"windows": own_files[k], "linux": their_files[k]} for k in changed}}

    return {"schema":"chimera.node-source-parity/1","measured_utc":datetime.now(timezone.utc).isoformat(),
            "scope":"Hashes of saved Python files on disk. A running interpreter may still hold older modules.",
            "windows":{"root":str(windows_root),"root_basis":windows_basis,"root_error":win.get("root_error"),
                       "pid":win.get("pid"),"node":win.get("node_name"),"version":win.get("version"),
                       "reachable":win["reachable"],"last_error":win.get("last_error"),
                       "package_version":win.get("package_version"),"started_at":win.get("started_at"),
                       "route_status":win_http,"process_working_set_mib":win_memory,
                       "evidence_counts":evidence_counts(win.get("evidence_summary",{}))},
            "linux":linux,"platform":compare("chimera_tp/platform/"),"package":compare("chimera_tp/")}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--peer", default="svhome")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    report = run(args.peer)
    if args.out:
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: {f: len(v) if isinstance(v, (dict, list)) else v for f, v in report[k].items()}
                      for k in ("platform", "package")}))
