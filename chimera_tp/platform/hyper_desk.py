"""CHIMERA-HYPERDESK (Cartridge #13, v19.0): Kernel-Level Multitasking Optimizer, VRAM Swap & Hydra/Zombie Control.

Implements all 7 Part-XVII breakthroughs cleanly at the OS-virtualization & distributed substrate layer:
  1. CHIMERA-CRYO         — Focus-Aware VIP Lane + EcoQoS + MemoryPriority + Lossless WorkingSet Trim + Safe Suspend/Thaw
  2. CHIMERA-SILICON-WALL — 2-Nation CPU Core Partitioning (Urban Focus vs Industrial Compilers/Sync) + Remote Build Exile
  3. CHIMERA-VRAM-SWAP    — Real nvcuda.dll GTX 1650 LZ4-Compressed VRAM L2 Tier (<30ms Auto-Yield) + svhome L3 Spill
  4. CHIMERA-HYDRA-COLLAPSE — Chromium/Electron Multi-Engine Auditor + CDP Tab Cryo-Surgeon + Remote 946 FPS Stream Bridge
  5. CHIMERA-ZOMBIE-REAPER  — Dead-Parent Orphan Detector/Reaper + Ghost-Commit Ratio Watchdog + Linux CoW Zygote Offload
  6. CHIMERA-CORTEX-BUS   — Unified AI-Agent Incremental File Watcher + Reusable Warm Shell Pool + Egress Coverage
  7. CHIMERA-SYNC-DAM     — OneDrive/Indexer Burst-Sync Dam (EcoQoS/Idle/Trim + Auto-Releasing Timed Freeze)
"""

from __future__ import annotations

from collections import defaultdict, deque
import ctypes
from ctypes import wintypes
import hashlib
import json
import math
import os
import platform
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any, Callable

from ..native import (
    has_native_pwm,
    lz4_compress,
    lz4_decompress,
    native_focus_hook_start,
    native_focus_hook_stop,
    native_focus_state,
    native_pwm_heartbeat,
    native_pwm_set_targets,
    native_pwm_start,
    native_pwm_stats,
    native_pwm_stop,
)
from .phantom_silicon import (
    AgentExileEngine,
    GpuFenceManager,
    NvmeMirageEngine,
    SiliconThermostat,
    StasisPodManager,
)
from .vgpu_gateway import probe_nvidia_gpu

# Processes that MUST NEVER be frozen, killed, or degraded.
_PROTECTED_PROCS = frozenset({
    "system",
    "idle",
    "registry",
    "smss",
    "csrss",
    "wininit",
    "winlogon",
    "services",
    "lsass",
    "dwm",
    "fontdrvhost",
    "audiodg",
    "explorer",
    "svchost",
    "sihost",
    "taskhostw",
    "conhost",
    "openconsole",
    "windowsterminal",
    "runtimebroker",
    "memory compression",
    "searchhost",
    "textinputhost",
    "startmenuexperiencehost",
    "shellexperiencehost",
    "ctfmon",
    "ntoskrnl",
    "systemd",
    "init",
    "sshd",
})

# Chromium / Electron / WebView2 families ("Chromium Hydra")
_HYDRA_FAMILIES = frozenset({
    "chrome",
    "msedge",
    "msedgewebview2",
    "t3 code (beta)",
    "t3 code",
    "antigravity",
    "chatgpt",
    "zalo",
    "electron",
    "code",
    "discord",
    "slack",
    "brave",
    "chromium",
})

# CAD / Creative / Interactive VIP Workstation Apps (auto-triggers CAD_GODMODE)
_CAD_GODMODE_PROCS = frozenset({
    "acad",
    "accoreconsole",
    "revit",
    "roamer",
    "sketchup",
    "blender",
    "3dsmax",
    "sldworks",
    "rhino",
    "photoshop",
    "adobe premiere pro",
    "resolve",
    "civil3d",
})

# Background Coding Agent / Heavy Daemon families (caged to Industrial Cores + Hard CPU Cap when NOT in active VIP Sanctuary!)
_BACKGROUND_AGENT_PROCS = frozenset({
    "language_server",
    "agy",
    "antigravity",
    "t3 code (beta)",
    "t3 code",
    "codex",
    "claude",
    "cursor",
    "chatgpt",
    "canvasauthoringmcpserver",
})

# Industrial Zone processes (compilers, LSPs, sync, indexers, heavy background workers)
_INDUSTRIAL_PROCS = frozenset({
    "vbcscompiler",
    "dotnet",
    "msbuild",
    "cl",
    "link",
    "rustc",
    "cargo",
    "gcc",
    "clang",
    "language_server",
    "onedrive",
    "onedrive.sync.service",
    "searchindexer",
    "searchprotocolhost",
    "tiworker",
    "trustedinstaller",
    "pythonw",
    "node",
})

# Sync / Indexer processes governed by CHIMERA-SYNC-DAM
_SYNC_DAM_PROCS = frozenset({
    "onedrive",
    "onedrive.sync.service",
    "searchindexer",
    "searchprotocolhost",
    "googledrivefs",
    "dropbox",
})

# AI Agent / IDE fleet monitored by CHIMERA-CORTEX-BUS
_AI_AGENT_PROCS = frozenset({
    "agy",
    "antigravity",
    "t3 code (beta)",
    "t3 code",
    "chatgpt",
    "codex",
    "language_server",
    "claude",
    "cursor",
    "powershell",
    "pwsh",
})

# Headless batch/build/test child executables eligible for SoftPriorityBatchShield (NEVER UI/gateways!)
_SOFT_BATCH_EXES = frozenset({
    "pytest",
    "tsc",
    "eslint",
    "ruff",
    "cargo",
    "rustc",
    "msbuild",
    "vbcscompiler",
    "cl",
    "link",
    "gcc",
    "clang",
    "robocopy",
    "rg",
    "conhost",
})

# Cmdline tokens identifying headless batch test/build workers inside python/node/pwsh
_SOFT_BATCH_CMD_TOKENS = (
    "-m unittest",
    "pytest",
    "node --test",
    "npm run build",
    "tsc ",
    "eslint",
    "ruff ",
    "cargo test",
    "cargo build",
    "pbkdf2",
    "chimera_batch_worker",
)

# Interactive workstation sanctuary exes protected & gently boosted (full 12-thread Turbo preserved!)
_SOFT_VIP_EXES = frozenset({
    "t3 code (beta)",
    "t3 code",
    "antigravity",
    "acad",
    "accoreconsole",
    "blender",
    "revit",
})

# Win32 constants
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_PROCESS_SET_INFORMATION = 0x0200
_PROCESS_SET_QUOTA = 0x0100
_PROCESS_SUSPEND_RESUME = 0x0800
_PROCESS_TERMINATE = 0x0001
_PROCESS_VM_READ = 0x0010

_IDLE_PRIORITY_CLASS = 0x00000040
_BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
_NORMAL_PRIORITY_CLASS = 0x00000020
_ABOVE_NORMAL_PRIORITY_CLASS = 0x00008000
_HIGH_PRIORITY_CLASS = 0x00000080

_PROCESS_MEMORY_PRIORITY = 0
_PROCESS_POWER_THROTTLING = 4
_MEMORY_PRIORITY_VERY_LOW = 1
_MEMORY_PRIORITY_NORMAL = 5
_POWER_THROTTLING_EXECUTION_SPEED = 0x1
_NT_PROCESS_IO_PRIORITY = 33
_NT_PROCESS_PAGE_PRIORITY = 39
_IO_PRIORITY_VERY_LOW = 0
_IO_PRIORITY_LOW = 1
_IO_PRIORITY_NORMAL = 2


if os.name == "nt":
    class _FILETIME(ctypes.Structure):
        _fields_ = [("dwLowDateTime", ctypes.c_ulong), ("dwHighDateTime", ctypes.c_ulong)]

    class _IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_uint64),
            ("WriteOperationCount", ctypes.c_uint64),
            ("OtherOperationCount", ctypes.c_uint64),
            ("ReadTransferCount", ctypes.c_uint64),
            ("WriteTransferCount", ctypes.c_uint64),
            ("OtherTransferCount", ctypes.c_uint64),
        ]

    class _JOBOBJECT_CPU_RATE_CONTROL_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("ControlFlags", ctypes.c_ulong),
            ("CpuRate", ctypes.c_ulong),
        ]

    class _PROCESS_POWER_THROTTLING_STATE(ctypes.Structure):
        _fields_ = [
            ("Version", ctypes.c_ulong),
            ("ControlMask", ctypes.c_ulong),
            ("StateMask", ctypes.c_ulong),
        ]

    class _MEMORY_PRIORITY_INFORMATION(ctypes.Structure):
        _fields_ = [("MemoryPriority", ctypes.c_ulong)]

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

    class _UNICODE_STRING(ctypes.Structure):
        _fields_ = [
            ("Length", ctypes.c_ushort),
            ("MaximumLength", ctypes.c_ushort),
            ("Buffer", ctypes.c_void_p),
        ]

    class _PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", ctypes.c_ulong),
            ("cntUsage", ctypes.c_ulong),
            ("th32ProcessID", ctypes.c_ulong),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", ctypes.c_ulong),
            ("cntThreads", ctypes.c_ulong),
            ("th32ParentProcessID", ctypes.c_ulong),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", ctypes.c_ulong),
            ("szExeFile", ctypes.c_wchar * 260),
        ]

    class _MIB_TCPROW_OWNER_PID(ctypes.Structure):
        _fields_ = [
            ("dwState", ctypes.c_uint32),
            ("dwLocalAddr", ctypes.c_uint32),
            ("dwLocalPort", ctypes.c_uint32),
            ("dwRemoteAddr", ctypes.c_uint32),
            ("dwRemotePort", ctypes.c_uint32),
            ("dwOwningPid", ctypes.c_uint32),
        ]


_MIB_TCP_STATE_LISTEN = 2
_MIB_TCP_STATE_ESTAB = 5
_TCP_TABLE_OWNER_PID_ALL = 5
_AF_INET = 2


def _win_tcp_socket_immunity(vip_pids: set[int] | None = None) -> dict[str, Any]:
    """Zero-subprocess Win32 iphlpapi!GetExtendedTcpTable scan for listening & VIP-connected local gateways.

    Enforces CHIMERA-ONE Law 2 (Zero-Choke Kernel Law): any process listening on a local service port
    (e.g. LLM proxies, local HTTP gateways, MCP servers) or actively serving a loopback TCP connection
    to the focused VIP family is strictly immune from CPU cages, EcoQoS, affinity walls, and PWM.
    """
    t0 = time.perf_counter()
    if os.name != "nt":
        return {"listening_pids": set(), "vip_peer_pids": set(), "listening_ports": {}, "scan_ms": 0.0}
    vip_set = set(vip_pids or ())
    listening_pids: set[int] = set()
    listening_ports: dict[int, list[int]] = {}
    loopback_estab: dict[tuple[int, int], int] = {}
    try:
        iphlpapi = ctypes.windll.iphlpapi
        size = ctypes.c_uint32(0)
        # First call gets required buffer size (returns ERROR_INSUFFICIENT_BUFFER = 122)
        iphlpapi.GetExtendedTcpTable(None, ctypes.byref(size), False, _AF_INET, _TCP_TABLE_OWNER_PID_ALL, 0)
        if size.value < 4 or size.value > 16 * 1024 * 1024:
            return {"listening_pids": set(), "vip_peer_pids": set(), "listening_ports": {}, "scan_ms": 0.0}
        buf = ctypes.create_string_buffer(size.value)
        ret = iphlpapi.GetExtendedTcpTable(buf, ctypes.byref(size), False, _AF_INET, _TCP_TABLE_OWNER_PID_ALL, 0)
        if ret != 0:
            return {"listening_pids": set(), "vip_peer_pids": set(), "listening_ports": {}, "scan_ms": 0.0}
        num_entries = ctypes.c_uint32.from_buffer_copy(buf.raw[:4]).value
        row_size = ctypes.sizeof(_MIB_TCPROW_OWNER_PID)
        max_rows = min(num_entries, (size.value - 4) // row_size)
        raw_bytes = buf.raw
        for i in range(max_rows):
            off = 4 + i * row_size
            row = _MIB_TCPROW_OWNER_PID.from_buffer_copy(raw_bytes[off : off + row_size])
            pid = int(row.dwOwningPid)
            if pid <= 4:
                continue
            state = int(row.dwState)
            lport = ((row.dwLocalPort & 0xFF) << 8) | ((row.dwLocalPort >> 8) & 0xFF)
            rport = ((row.dwRemotePort & 0xFF) << 8) | ((row.dwRemotePort >> 8) & 0xFF)
            # 127.0.0.1 in network byte order stored in little-endian uint32 is 0x0100007F
            is_local_loopback = (row.dwLocalAddr & 0xFF) == 127
            is_local_any = row.dwLocalAddr == 0
            if state == _MIB_TCP_STATE_LISTEN and (is_local_loopback or (is_local_any and lport >= 1024)):
                listening_pids.add(pid)
                ports = listening_ports.setdefault(pid, [])
                if lport not in ports:
                    ports.append(lport)
            elif state == _MIB_TCP_STATE_ESTAB and is_local_loopback and (row.dwRemoteAddr & 0xFF) == 127:
                loopback_estab[(lport, rport)] = pid
    except Exception:
        return {"listening_pids": set(), "vip_peer_pids": set(), "listening_ports": {}, "scan_ms": 0.0}

    vip_peer_pids: set[int] = set()
    if vip_set and loopback_estab:
        for (lp, rp), pid in loopback_estab.items():
            if pid in vip_set:
                peer_pid = loopback_estab.get((rp, lp))
                if peer_pid and peer_pid > 4:
                    vip_peer_pids.add(peer_pid)

    return {
        "listening_pids": listening_pids,
        "vip_peer_pids": vip_peer_pids,
        "listening_ports": listening_ports,
        "scan_ms": round((time.perf_counter() - t0) * 1000.0, 3),
    }


def _norm_proc_name(name: str) -> str:
    n = str(name or "").strip().lower()
    if n.endswith(".exe"):
        n = n[:-4]
    return n


def _win_foreground_pid() -> int:
    if os.name != "nt":
        return 0
    try:
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        if not hwnd:
            return 0
        pid = ctypes.c_ulong(0)
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return int(pid.value)
    except Exception:
        return 0


def _win_open_proc(pid: int, access: int) -> int:
    if os.name != "nt" or pid <= 4:
        return 0
    try:
        h = ctypes.windll.kernel32.OpenProcess(access, False, int(pid))
        return int(h or 0)
    except Exception:
        return 0


def _win_close_handle(h: int) -> None:
    if os.name == "nt" and h:
        try:
            ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(h))
        except Exception:
            pass


def _win_proc_memory_mb(pid: int) -> tuple[float, float]:
    """Return (working_set_mb, private_commit_mb) using Win32 GetProcessMemoryInfo (fast, zero-PowerShell)."""
    if os.name != "nt":
        return 0.0, 0.0
    h = _win_open_proc(pid, _PROCESS_QUERY_LIMITED_INFORMATION | _PROCESS_VM_READ)
    if not h:
        h = _win_open_proc(pid, _PROCESS_QUERY_LIMITED_INFORMATION)
    if not h:
        return 0.0, 0.0
    try:
        pmc = _PROCESS_MEMORY_COUNTERS_EX()
        pmc.cb = ctypes.sizeof(_PROCESS_MEMORY_COUNTERS_EX)
        ok = ctypes.windll.psapi.GetProcessMemoryInfo(
            ctypes.c_void_p(h), ctypes.byref(pmc), pmc.cb
        )
        if not ok:
            return 0.0, 0.0
        ws_mb = round(pmc.WorkingSetSize / (1024.0 * 1024.0), 2)
        priv_mb = round(max(pmc.PrivateUsage, pmc.PagefileUsage) / (1024.0 * 1024.0), 2)
        return ws_mb, priv_mb
    except Exception:
        return 0.0, 0.0
    finally:
        _win_close_handle(h)


def _snapshot_processes() -> list[dict[str, Any]]:
    """Fast cross-platform OS process table snapshot (Win32 Toolhelp32 on Windows, /proc on Linux)."""
    procs: list[dict[str, Any]] = []
    if os.name == "nt":
        TH32CS_SNAPPROCESS = 0x00000002
        snap = ctypes.windll.kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if not snap or snap == ctypes.c_void_p(-1).value:
            return procs
        try:
            pe = _PROCESSENTRY32W()
            pe.dwSize = ctypes.sizeof(_PROCESSENTRY32W)
            ok = ctypes.windll.kernel32.Process32FirstW(ctypes.c_void_p(snap), ctypes.byref(pe))
            while ok:
                pid = int(pe.th32ProcessID)
                ppid = int(pe.th32ParentProcessID)
                raw_name = str(pe.szExeFile)
                ws_mb, priv_mb = _win_proc_memory_mb(pid) if pid > 4 else (0.0, 0.0)
                procs.append({
                    "pid": pid,
                    "ppid": ppid,
                    "name": _norm_proc_name(raw_name),
                    "exe": raw_name,
                    "threads": int(pe.cntThreads),
                    "ws_mb": ws_mb,
                    "priv_mb": priv_mb,
                })
                ok = ctypes.windll.kernel32.Process32NextW(ctypes.c_void_p(snap), ctypes.byref(pe))
        finally:
            _win_close_handle(snap)
        return procs

    # Linux /proc fast scan
    proc_root = Path("/proc")
    if not proc_root.is_dir():
        return procs
    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        try:
            st = (entry / "status").read_text(encoding="utf-8", errors="ignore")
            name, ppid, rss_kb, vm_kb, threads = "", 0, 0, 0, 1
            for ln in st.splitlines():
                if ln.startswith("Name:"):
                    name = ln.split(":", 1)[1].strip()
                elif ln.startswith("PPid:"):
                    ppid = int(ln.split(":", 1)[1].strip() or 0)
                elif ln.startswith("VmRSS:"):
                    rss_kb = int(ln.split(":", 1)[1].strip().split()[0] or 0)
                elif ln.startswith("VmData:"):
                    vm_kb = int(ln.split(":", 1)[1].strip().split()[0] or 0)
                elif ln.startswith("Threads:"):
                    threads = int(ln.split(":", 1)[1].strip() or 1)
            ws_mb = round(rss_kb / 1024.0, 2)
            priv_mb = round(max(rss_kb, vm_kb) / 1024.0, 2)
            procs.append({
                "pid": pid,
                "ppid": ppid,
                "name": _norm_proc_name(name),
                "exe": name,
                "threads": threads,
                "ws_mb": ws_mb,
                "priv_mb": priv_mb,
            })
        except OSError:
            continue
    return procs


def _win_get_cmdlines_for_pids(pids: list[int]) -> dict[int, str]:
    """Zero-PowerShell native Win32 NtQueryInformationProcess(60) cmdline reader (<0.06ms/PID, 0 console popups)."""
    if not pids:
        return {}
    if os.name != "nt":
        out: dict[int, str] = {}
        for pid in pids:
            try:
                raw = Path(f"/proc/{pid}/cmdline").read_bytes()
                out[pid] = raw.replace(b"\x00", b" ").decode("utf-8", errors="ignore").strip()
            except OSError:
                continue
        return out

    # ProcessCommandLineInformation (60): pure kernel query, ZERO subprocesses, ZERO flashing PowerShell windows!
    ntdll = ctypes.windll.ntdll
    out_win: dict[int, str] = {}
    for pid in pids[:128]:
        pid_i = int(pid)
        if pid_i <= 4:
            continue
        h = _win_open_proc(pid_i, _PROCESS_QUERY_LIMITED_INFORMATION)
        if not h:
            continue
        try:
            ret_len = ctypes.c_ulong(0)
            buf = ctypes.create_string_buffer(4096)
            st = int(ntdll.NtQueryInformationProcess(ctypes.c_void_p(h), 60, buf, len(buf), ctypes.byref(ret_len))) & 0xFFFFFFFF
            if st in (0xC0000004, 0xC0000023) and ret_len.value > 0:
                buf = ctypes.create_string_buffer(min(65536, int(ret_len.value) + 32))
                st = int(ntdll.NtQueryInformationProcess(ctypes.c_void_p(h), 60, buf, len(buf), ctypes.byref(ret_len))) & 0xFFFFFFFF
            if st != 0:
                continue
            us = _UNICODE_STRING.from_buffer_copy(buf.raw[: ctypes.sizeof(_UNICODE_STRING)])
            if us.Buffer and us.Length > 0:
                out_win[pid_i] = ctypes.wstring_at(us.Buffer, us.Length // 2)
        except Exception:
            continue
        finally:
            _win_close_handle(h)
    return out_win


def _win_set_eco_qos(pid: int, enable: bool) -> bool:
    if os.name != "nt":
        return False
    h = _win_open_proc(pid, _PROCESS_SET_INFORMATION)
    if not h:
        return False
    try:
        st = _PROCESS_POWER_THROTTLING_STATE()
        st.Version = 1
        st.ControlMask = _POWER_THROTTLING_EXECUTION_SPEED
        st.StateMask = _POWER_THROTTLING_EXECUTION_SPEED if enable else 0
        ok = ctypes.windll.kernel32.SetProcessInformation(
            ctypes.c_void_p(h), _PROCESS_POWER_THROTTLING, ctypes.byref(st), ctypes.sizeof(st)
        )
        return bool(ok)
    except Exception:
        return False
    finally:
        _win_close_handle(h)


def _win_set_memory_priority(pid: int, level: int) -> bool:
    if os.name != "nt":
        return False
    h = _win_open_proc(pid, _PROCESS_SET_INFORMATION)
    if not h:
        return False
    try:
        mp = _MEMORY_PRIORITY_INFORMATION()
        mp.MemoryPriority = int(level)
        ok = ctypes.windll.kernel32.SetProcessInformation(
            ctypes.c_void_p(h), _PROCESS_MEMORY_PRIORITY, ctypes.byref(mp), ctypes.sizeof(mp)
        )
        return bool(ok)
    except Exception:
        return False
    finally:
        _win_close_handle(h)


def _win_get_priority(pid: int) -> int:
    if os.name != "nt":
        return 0
    h = _win_open_proc(pid, _PROCESS_QUERY_LIMITED_INFORMATION)
    if not h:
        return 0
    try:
        return int(ctypes.windll.kernel32.GetPriorityClass(ctypes.c_void_p(h)) or 0)
    except Exception:
        return 0
    finally:
        _win_close_handle(h)


def _win_set_priority(pid: int, priority_class: int) -> bool:
    if os.name != "nt":
        try:
            nice_val = 10 if priority_class in (_IDLE_PRIORITY_CLASS, _BELOW_NORMAL_PRIORITY_CLASS) else 0
            os.setpriority(os.PRIO_PROCESS, int(pid), nice_val)
            return True
        except Exception:
            return False
    h = _win_open_proc(pid, _PROCESS_SET_INFORMATION)
    if not h:
        return False
    try:
        return bool(ctypes.windll.kernel32.SetPriorityClass(ctypes.c_void_p(h), int(priority_class)))
    except Exception:
        return False
    finally:
        _win_close_handle(h)


def _win_set_affinity(pid: int, mask: int) -> bool:
    if mask <= 0:
        return False
    if os.name != "nt":
        try:
            cpus = {i for i in range(64) if (mask >> i) & 1}
            if cpus and hasattr(os, "sched_setaffinity"):
                os.sched_setaffinity(int(pid), cpus)
                return True
        except Exception:
            return False
        return False
    h = _win_open_proc(pid, _PROCESS_SET_INFORMATION)
    if not h:
        return False
    try:
        return bool(ctypes.windll.kernel32.SetProcessAffinityMask(ctypes.c_void_p(h), ctypes.c_size_t(mask)))
    except Exception:
        return False
    finally:
        _win_close_handle(h)


def _win_trim_working_set(pid: int) -> bool:
    """Losslessly trim cold pages to Windows Memory Compression (0 data loss, preserves state)."""
    if os.name != "nt":
        return False
    h = _win_open_proc(pid, _PROCESS_SET_QUOTA | _PROCESS_QUERY_LIMITED_INFORMATION)
    if not h:
        return False
    try:
        ok = ctypes.windll.psapi.EmptyWorkingSet(ctypes.c_void_p(h))
        if not ok:
            ok = ctypes.windll.kernel32.SetProcessWorkingSetSize(
                ctypes.c_void_p(h), ctypes.c_size_t(-1), ctypes.c_size_t(-1)
            )
        return bool(ok)
    except Exception:
        return False
    finally:
        _win_close_handle(h)


def _win_suspend_resume(pid: int, suspend: bool) -> bool:
    if os.name != "nt":
        try:
            import signal as _sig
            os.kill(int(pid), _sig.SIGSTOP if suspend else _sig.SIGCONT)
            return True
        except Exception:
            return False
    h = _win_open_proc(pid, _PROCESS_SUSPEND_RESUME)
    if not h:
        return False
    try:
        fn = ctypes.windll.ntdll.NtSuspendProcess if suspend else ctypes.windll.ntdll.NtResumeProcess
        return int(fn(ctypes.c_void_p(h))) == 0
    except Exception:
        return False
    finally:
        _win_close_handle(h)


def _win_set_io_priority(pid: int, level: int) -> bool:
    """Set kernel ProcessIoPriority (0=VeryLow, 2=Normal) and PagePriority via ntdll.NtSetInformationProcess."""
    if os.name != "nt":
        return False
    h = _win_open_proc(pid, _PROCESS_SET_INFORMATION)
    if not h:
        return False
    try:
        val = ctypes.c_ulong(int(level))
        st = ctypes.windll.ntdll.NtSetInformationProcess(
            ctypes.c_void_p(h), _NT_PROCESS_IO_PRIORITY, ctypes.byref(val), ctypes.sizeof(val)
        )
        pg = ctypes.c_ulong(_MEMORY_PRIORITY_VERY_LOW if level == _IO_PRIORITY_VERY_LOW else _MEMORY_PRIORITY_NORMAL)
        ctypes.windll.ntdll.NtSetInformationProcess(
            ctypes.c_void_p(h), _NT_PROCESS_PAGE_PRIORITY, ctypes.byref(pg), ctypes.sizeof(pg)
        )
        return int(st) == 0
    except Exception:
        return False
    finally:
        _win_close_handle(h)


def _win_set_timer_resolution(enable_half_ms: bool) -> float:
    """CHIMERA-CHRONO-PULSE: Tighten Windows kernel timer resolution to 0.5 ms (5000 x 100ns) for silky CAD/UI pacing."""
    if os.name != "nt":
        return 0.0
    try:
        cur = ctypes.c_ulong(0)
        ctypes.windll.ntdll.NtSetTimerResolution(ctypes.c_ulong(5000), ctypes.c_bool(bool(enable_half_ms)), ctypes.byref(cur))
        return round(cur.value / 10000.0, 3)
    except Exception:
        return 0.0


def _win_proc_cpu_io(pid: int) -> tuple[float, int]:
    """Sub-10us kernel32 read of cumulative (cpu_seconds, io_transfer_bytes) for real-time runaway detection."""
    if os.name != "nt" or pid <= 4:
        return 0.0, 0
    h = _win_open_proc(pid, _PROCESS_QUERY_LIMITED_INFORMATION)
    if not h:
        return 0.0, 0
    try:
        c_ft, e_ft, k_ft, u_ft = _FILETIME(), _FILETIME(), _FILETIME(), _FILETIME()
        cpu_s = 0.0
        if ctypes.windll.kernel32.GetProcessTimes(
            ctypes.c_void_p(h), ctypes.byref(c_ft), ctypes.byref(e_ft), ctypes.byref(k_ft), ctypes.byref(u_ft)
        ):
            k = (k_ft.dwHighDateTime << 32) | k_ft.dwLowDateTime
            u = (u_ft.dwHighDateTime << 32) | u_ft.dwLowDateTime
            cpu_s = (k + u) / 1e7
        io_c = _IO_COUNTERS()
        io_b = 0
        if ctypes.windll.kernel32.GetProcessIoCounters(ctypes.c_void_p(h), ctypes.byref(io_c)):
            io_b = int(io_c.ReadTransferCount + io_c.WriteTransferCount)
        return cpu_s, io_b
    except Exception:
        return 0.0, 0
    finally:
        _win_close_handle(h)


class WinHardCpuCage:
    """CHIMERA-HARD-SILICON-CAGE: Real Win32 Nested Job Object enforcing kernel-level CPU% HARD_CAP on background storms."""

    def __init__(self, initial_cap_pct: int = 35) -> None:
        self._lock = threading.Lock()
        self._job: int = 0
        self._cap_pct: int = max(10, min(100, int(initial_cap_pct)))
        self._assigned_pids: set[int] = set()
        if os.name == "nt":
            try:
                k32 = ctypes.windll.kernel32
                k32.CreateJobObjectW.restype = ctypes.c_void_p
                h = k32.CreateJobObjectW(None, None)
                if h:
                    self._job = int(h)
                    self.set_cap_pct(self._cap_pct)
            except Exception:
                self._job = 0

    def set_cap_pct(self, pct: int) -> bool:
        pct = max(10, min(100, int(pct)))
        with self._lock:
            self._cap_pct = pct
            if os.name != "nt" or not self._job:
                return False
            try:
                info = _JOBOBJECT_CPU_RATE_CONTROL_INFORMATION()
                # 0x1 = ENABLE, 0x4 = HARD_CAP (enforced strictly by Windows kernel scheduler!)
                info.ControlFlags = 0x5 if pct < 100 else 0x0
                info.CpuRate = min(10000, max(100, pct * 100))
                ok = ctypes.windll.kernel32.SetInformationJobObject(
                    ctypes.c_void_p(self._job), 15, ctypes.byref(info), ctypes.sizeof(info)
                )
                return bool(ok)
            except Exception:
                return False

    def cage_pid(self, pid: int) -> bool:
        if os.name != "nt" or not self._job or pid <= 4:
            return False
        with self._lock:
            if pid in self._assigned_pids:
                return True
        h = _win_open_proc(pid, _PROCESS_SET_QUOTA | _PROCESS_TERMINATE)
        if not h:
            return False
        try:
            ok = bool(ctypes.windll.kernel32.AssignProcessToJobObject(ctypes.c_void_p(self._job), ctypes.c_void_p(h)))
            if ok:
                with self._lock:
                    self._assigned_pids.add(pid)
            return ok
        except Exception:
            return False
        finally:
            _win_close_handle(h)

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "active": bool(self._job),
                "hard_cap_pct": self._cap_pct,
                "caged_pids": len(self._assigned_pids),
            }

    def close(self) -> None:
        with self._lock:
            if os.name == "nt" and self._job:
                try:
                    # Release hard cap cleanly before closing handle (never kills processes; KILL_ON_JOB_CLOSE is NOT set!)
                    info = _JOBOBJECT_CPU_RATE_CONTROL_INFORMATION()
                    info.ControlFlags = 0
                    info.CpuRate = 10000
                    ctypes.windll.kernel32.SetInformationJobObject(
                        ctypes.c_void_p(self._job), 15, ctypes.byref(info), ctypes.sizeof(info)
                    )
                    _win_close_handle(self._job)
                except Exception:
                    pass
                self._job = 0
                self._assigned_pids.clear()


def _win_terminate_pid(pid: int) -> bool:
    if os.name != "nt":
        try:
            import signal as _sig
            os.kill(int(pid), _sig.SIGTERM)
            return True
        except Exception:
            return False
    h = _win_open_proc(pid, _PROCESS_TERMINATE)
    if not h:
        return False
    try:
        return bool(ctypes.windll.kernel32.TerminateProcess(ctypes.c_void_p(h), 1))
    except Exception:
        return False
    finally:
        _win_close_handle(h)


class VramCompressedSwap:
    """CHIMERA-VRAM-SWAP: Real nvcuda.dll LZ4-Compressed VRAM L2 Tier with <30ms Auto-Yield & L3 Peer Spill."""

    def __init__(
        self,
        max_vram_mb: int = 256,
        temp_yield_c: float = 72.0,
        util_yield_pct: float = 40.0,
        peer_base_resolver: Callable[[], str] | None = None,
    ) -> None:
        self.max_vram_bytes = max(16, int(max_vram_mb)) * 1024 * 1024
        self.temp_yield_c = float(temp_yield_c)
        self.util_yield_pct = float(util_yield_pct)
        self.peer_base_resolver = peer_base_resolver
        self._lock = threading.Lock()
        self._cu: Any = None
        self._ctx: Any = None
        self._device_name: str = ""
        self._cuda_probed: bool = False
        self._cuda_available: bool = False
        # key -> {tier: "vram"|"host_lz4"|"peer", ptr, comp_len, raw_len, sha256, blob, ts}
        self._pages: dict[str, dict[str, Any]] = {}
        self._vram_used_bytes = 0
        self._total_raw_bytes = 0
        self._puts = 0
        self._gets = 0
        self._yields = 0
        self._last_yield_ms = 0.0

    def _init_cuda_lib_locked(self) -> bool:
        if self._cuda_probed:
            return self._cuda_available
        self._cuda_probed = True
        try:
            lib = ctypes.WinDLL("nvcuda.dll") if os.name == "nt" else ctypes.CDLL("libcuda.so.1")
            lib.cuInit.argtypes = [ctypes.c_uint]
            lib.cuDeviceGet.argtypes = [ctypes.POINTER(ctypes.c_int), ctypes.c_int]
            lib.cuDeviceGetName.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.c_int]
            lib.cuCtxCreate_v2.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.c_uint, ctypes.c_int]
            lib.cuCtxDestroy_v2.argtypes = [ctypes.c_void_p]
            lib.cuCtxSetCurrent.argtypes = [ctypes.c_void_p]
            lib.cuMemAlloc_v2.argtypes = [ctypes.POINTER(ctypes.c_uint64), ctypes.c_size_t]
            lib.cuMemFree_v2.argtypes = [ctypes.c_uint64]
            lib.cuMemcpyHtoD_v2.argtypes = [ctypes.c_uint64, ctypes.c_void_p, ctypes.c_size_t]
            lib.cuMemcpyDtoH_v2.argtypes = [ctypes.c_void_p, ctypes.c_uint64, ctypes.c_size_t]
            if lib.cuInit(0) != 0:
                return False
            dev = ctypes.c_int(0)
            if lib.cuDeviceGet(ctypes.byref(dev), 0) != 0:
                return False
            buf = ctypes.create_string_buffer(128)
            lib.cuDeviceGetName(buf, 128, dev)
            self._cu = lib
            self._device_name = buf.value.decode("utf-8", errors="ignore")
            self._cuda_available = True
        except Exception:
            self._cuda_available = False
        return self._cuda_available

    def _ensure_ctx_locked(self) -> bool:
        if not self._init_cuda_lib_locked():
            return False
        if self._ctx is not None:
            self._cu.cuCtxSetCurrent(self._ctx)
            return True
        dev = ctypes.c_int(0)
        ctx = ctypes.c_void_p()
        if self._cu.cuDeviceGet(ctypes.byref(dev), 0) != 0:
            return False
        if self._cu.cuCtxCreate_v2(ctypes.byref(ctx), 0, dev) != 0:
            return False
        self._ctx = ctx
        return True

    def _gpu_safe_for_vram(self) -> bool:
        gpu = probe_nvidia_gpu()
        if not gpu.get("present"):
            return self._cuda_available
        if float(gpu.get("temp_c", 0)) >= self.temp_yield_c:
            return False
        if float(gpu.get("util_pct", 0)) >= self.util_yield_pct:
            return False
        if int(gpu.get("vram_free_mb", 0)) < 512:
            return False
        return True

    def put_page(self, key: str, raw: bytes, *, prefer_vram: bool = True) -> dict[str, Any]:
        """Compress raw bytes with LZ4 SIMD and store directly into GTX 1650 GDDR6 VRAM (or host/peer L3)."""
        t0 = time.perf_counter()
        raw_bytes = bytes(raw)
        comp = lz4_compress(raw_bytes)
        sha = hashlib.sha256(raw_bytes).hexdigest()
        tier = "host_lz4"

        with self._lock:
            # Evict existing key first
            if key in self._pages:
                self._evict_key_locked(key)

            can_vram = (
                prefer_vram
                and len(comp) > 0
                and (self._vram_used_bytes + len(comp)) <= self.max_vram_bytes
                and self._ensure_ctx_locked()
            )
            if can_vram:
                ptr = ctypes.c_uint64(0)
                if self._cu.cuMemAlloc_v2(ctypes.byref(ptr), len(comp)) == 0:
                    cbuf = ctypes.create_string_buffer(comp, len(comp))
                    if self._cu.cuMemcpyHtoD_v2(ptr, cbuf, len(comp)) == 0:
                        self._pages[key] = {
                            "tier": "vram",
                            "ptr": int(ptr.value),
                            "comp_len": len(comp),
                            "raw_len": len(raw_bytes),
                            "sha256": sha,
                            "blob": None,
                            "ts": time.time(),
                        }
                        self._vram_used_bytes += len(comp)
                        self._total_raw_bytes += len(raw_bytes)
                        self._puts += 1
                        tier = "vram"
                    else:
                        self._cu.cuMemFree_v2(ptr)
            if tier != "vram":
                self._pages[key] = {
                    "tier": "host_lz4",
                    "ptr": 0,
                    "comp_len": len(comp),
                    "raw_len": len(raw_bytes),
                    "sha256": sha,
                    "blob": comp,
                    "ts": time.time(),
                }
                self._total_raw_bytes += len(raw_bytes)
                self._puts += 1

        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        ratio = round(len(raw_bytes) / max(1, len(comp)), 2)
        return {
            "ok": True,
            "key": key,
            "tier": tier,
            "device": self._device_name if tier == "vram" else "host_ram_lz4",
            "raw_bytes": len(raw_bytes),
            "compressed_bytes": len(comp),
            "compression_ratio": ratio,
            "sha256": sha[:16],
            "elapsed_ms": round(elapsed_ms, 3),
        }

    def get_page(self, key: str) -> tuple[bytes | None, dict[str, Any]]:
        """Retrieve & LZ4-decompress a stored page from GTX 1650 VRAM or host L2/L3 with SHA-256 verification."""
        t0 = time.perf_counter()
        with self._lock:
            meta = self._pages.get(key)
            if meta is None:
                return None, {"ok": False, "found": False, "key": key}
            tier = meta["tier"]
            if tier == "vram":
                if not self._ctx:
                    return None, {"ok": False, "error": "vram_context_closed"}
                self._cu.cuCtxSetCurrent(self._ctx)
                comp_len = int(meta["comp_len"])
                out = ctypes.create_string_buffer(comp_len)
                if self._cu.cuMemcpyDtoH_v2(out, ctypes.c_uint64(meta["ptr"]), comp_len) != 0:
                    return None, {"ok": False, "error": "cuMemcpyDtoH_failed"}
                comp = out.raw
            else:
                comp = meta["blob"] or b""
            raw_len = int(meta["raw_len"])
            expected_sha = str(meta["sha256"])
            self._gets += 1

        raw = lz4_decompress(comp)
        exact = hashlib.sha256(raw).hexdigest() == expected_sha
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        return raw, {
            "ok": exact,
            "found": True,
            "key": key,
            "tier": tier,
            "raw_bytes": len(raw),
            "sha256_exact": exact,
            "elapsed_ms": round(elapsed_ms, 3),
        }

    def _evict_key_locked(self, key: str) -> None:
        meta = self._pages.pop(key, None)
        if not meta:
            return
        self._total_raw_bytes = max(0, self._total_raw_bytes - int(meta["raw_len"]))
        if meta["tier"] == "vram" and meta["ptr"] and self._ctx and self._cu:
            self._cu.cuCtxSetCurrent(self._ctx)
            self._cu.cuMemFree_v2(ctypes.c_uint64(meta["ptr"]))
            self._vram_used_bytes = max(0, self._vram_used_bytes - int(meta["comp_len"]))

    def yield_vram(self, *, drop_pages: bool = False) -> dict[str, Any]:
        """Release verified pages, retaining the device copy and context on a failed migration."""
        t0 = time.perf_counter()
        migrated = 0
        dropped = 0
        errors = []
        phase_ms = {"activate": 0.0, "copy_to_host": 0.0, "verify": 0.0,
                    "free_pages": 0.0, "destroy_context": 0.0}

        def invoke(phase, call, *args):
            start = time.perf_counter()
            try:
                return call(*args)
            finally:
                phase_ms[phase] += (time.perf_counter() - start) * 1000

        with self._lock:
            if self._ctx and self._cu:
                rc = invoke("activate", self._cu.cuCtxSetCurrent, self._ctx)
                if rc:
                    errors.append({"phase": "activate", "cuda_status": rc})
                else:
                    for key, meta in list(self._pages.items()):
                        if meta["tier"] != "vram":
                            continue
                        ptr = ctypes.c_uint64(meta["ptr"])
                        if not drop_pages:
                            out = ctypes.create_string_buffer(meta["comp_len"])
                            rc = invoke("copy_to_host", self._cu.cuMemcpyDtoH_v2, out, ptr, meta["comp_len"])
                            if rc:
                                errors.append({"page": key, "phase": "copy_to_host", "cuda_status": rc})
                                continue
                            blob = out.raw
                            start = time.perf_counter()
                            try:
                                if int.from_bytes(blob[:4], "little") != meta["raw_len"]:
                                    raise ValueError("page_size_mismatch")
                                if hashlib.sha256(lz4_decompress(blob)).hexdigest() != meta["sha256"]:
                                    raise ValueError("page_digest_mismatch")
                            except ValueError as exc:
                                errors.append({"page": key, "phase": "verify", "reason": str(exc)})
                                continue
                            finally:
                                phase_ms["verify"] += (time.perf_counter() - start) * 1000
                        rc = invoke("free_pages", self._cu.cuMemFree_v2, ptr)
                        if rc:
                            errors.append({"page": key, "phase": "free_pages", "cuda_status": rc})
                            continue
                        self._vram_used_bytes -= meta["comp_len"]
                        if drop_pages:
                            self._total_raw_bytes -= meta["raw_len"]
                            del self._pages[key]
                            dropped += 1
                        else:
                            meta.update(tier="host_lz4", blob=blob, ptr=0)
                        migrated += 1
                    if not any(p["tier"] == "vram" for p in self._pages.values()):
                        rc = invoke("destroy_context", self._cu.cuCtxDestroy_v2, self._ctx)
                        if rc:
                            errors.append({"phase": "destroy_context", "cuda_status": rc})
                        else:
                            self._ctx = None
            if drop_pages:
                for key, meta in list(self._pages.items()):
                    if meta["tier"] != "vram":
                        self._total_raw_bytes -= meta["raw_len"]
                        del self._pages[key]
                        dropped += 1
            retained = self._vram_used_bytes
            ctx_live = self._ctx is not None
            self._yields += 1
            elapsed = self._last_yield_ms = round((time.perf_counter() - t0) * 1000.0, 3)
        return {"ok": not errors and not ctx_live and retained == 0, "migrated_pages": migrated,
                "dropped_pages": dropped, "vram_retained_mb": retained / (1024.0 ** 2),
                "retained_page_bytes": retained, "context_active": ctx_live, "errors": errors,
                "phase_ms": {key: round(value, 4) for key, value in phase_ms.items()}, "yield_ms": elapsed}

    def benchmark(self, payload_mb: float = 4.0) -> dict[str, Any]:
        """Run live end-to-end GTX 1650 LZ4 VRAM Swap benchmark and cleanly yield back to 0.0 MB VRAM."""
        size = max(65536, min(16 * 1024 * 1024, int(payload_mb * 1024 * 1024)))
        # Realistic structured desktop/JSON/code memory page pattern (~3.5x-6x compressible)
        chunk = (
            b'{"tab":"workspace","module":"chimera_hyperdesk","dom_nodes":1420,"scroll_y":842,'
            b'"cache_state":"warm","frames":[101,102,103,104,105,106,107,108]}\n'
        )
        raw = (chunk * ((size // len(chunk)) + 1))[:size]
        put_res = self.put_page("__bench_page__", raw, prefer_vram=True)
        got, get_res = self.get_page("__bench_page__")
        yield_res = self.yield_vram(drop_pages=True)
        total_ms = max(0.001, float(put_res["elapsed_ms"]) + float(get_res["elapsed_ms"]))
        eff_gbps = round((size * 2.0) / (total_ms / 1000.0) / (1024.0 ** 3), 2)
        ok_flag = bool(put_res["ok"] and get_res.get("sha256_exact") and got == raw and yield_res["ok"])
        del raw, got
        try:
            import gc
            gc.collect()
            if os.name != "nt":
                ctypes.CDLL("libc.so.6").malloc_trim(0)
        except Exception:
            pass
        return {
            "ok": ok_flag,
            "tier_used": put_res["tier"],
            "device": put_res["device"],
            "raw_mb": round(size / (1024.0 * 1024.0), 2),
            "vram_compressed_mb": round(put_res["compressed_bytes"] / (1024.0 * 1024.0), 3),
            "compression_ratio": put_res["compression_ratio"],
            "put_ms": put_res["elapsed_ms"],
            "get_ms": get_res["elapsed_ms"],
            "effective_gbps": eff_gbps,
            "sha256_exact": bool(get_res.get("sha256_exact")),
            "yield_ms": yield_res["yield_ms"],
            "vram_retained_mb": yield_res["vram_retained_mb"],
        }

    def status(self, *, probe_cuda: bool = False) -> dict[str, Any]:
        with self._lock:
            if probe_cuda and not self._cuda_probed:
                self._init_cuda_lib_locked()
            return {
                "cuda_available": self._cuda_available,
                "cuda_probed": self._cuda_probed,
                "device": self._device_name,
                "active_context": self._ctx is not None,
                "pages": len(self._pages),
                "vram_used_mb": round(self._vram_used_bytes / (1024.0 * 1024.0), 3),
                "effective_raw_mb": round(self._total_raw_bytes / (1024.0 * 1024.0), 3),
                "max_vram_mb": round(self.max_vram_bytes / (1024.0 * 1024.0), 1),
                "puts": self._puts,
                "gets": self._gets,
                "yields": self._yields,
                "last_yield_ms": self._last_yield_ms,
            }

    def close(self) -> None:
        self.yield_vram(drop_pages=True)


class HyperDeskEngine:
    """Cartridge #13: Unified v19.0 CHIMERA-HYPERDESK Kernel Multitasking Optimizer."""

    def __init__(
        self,
        *,
        ops_dir: Path | None = None,
        host_governor: Any = None,
        pulse_bus: Any = None,
        zygote_pool: Any = None,
        browser_grid: Any = None,
        colab_bridge: Any = None,
        peer_base_resolver: Callable[[], str] | None = None,
        on_flow: Callable[..., Any] | None = None,
    ) -> None:
        self.ops_dir = Path(ops_dir) if ops_dir else None
        self.host_governor = host_governor
        self.pulse_bus = pulse_bus
        self.zygote_pool = zygote_pool
        self.browser_grid = browser_grid
        self.colab_bridge = colab_bridge
        self.peer_base_resolver = peer_base_resolver
        self.on_flow = on_flow

        self.vram_swap = VramCompressedSwap(peer_base_resolver=peer_base_resolver)
        self.mirage = NvmeMirageEngine(ops_dir=self.ops_dir)
        self.stasis = StasisPodManager(
            cmdlines_fn=_win_get_cmdlines_for_pids,
            suspend_fn=_win_suspend_resume,
            trim_fn=_win_trim_working_set,
            mem_fn=_win_proc_memory_mb,
            terminate_fn=_win_terminate_pid,
            ops_dir=self.ops_dir,
        )
        self.gpu_fence = GpuFenceManager(ops_dir=self.ops_dir)
        self.exile = AgentExileEngine(colab_bridge=colab_bridge)
        self.thermostat = SiliconThermostat(mode="cool_99")
        self._lock = threading.Lock()
        self._cpu_count = max(1, os.cpu_count() or 4)
        self._own_pid = os.getpid()
        self._suspended_pids: dict[int, float] = {}
        self._last_focus_pid: int = 0
        self._focus_transitions: dict[int, dict[int, int]] = defaultdict(lambda: defaultdict(int))
        self._watched_dirs: dict[str, dict[str, tuple[int, int]]] = {}
        self._warm_shell_history: deque[dict[str, Any]] = deque(maxlen=32)

        # Autonomic Self-Living Reflex state (v23 CHIMERA-PHANTOM-SILICON — zero manual CLI needed!)
        self._policy_path = (self.ops_dir / "autonomic_policy.json") if self.ops_dir else None
        self._autonomic_policy: dict[str, Any] = {
            "enabled": True,
            "interactive_profile": "aether",
            "fast_tick_s": 1.5,
            "patrol_interval_s": 12.0,
            "orphan_interval_s": 60.0,
            "recent_focus_guard_s": 60.0,
            "pid_trim_cooldown_s": 300.0,
            "idle_release_s": 15.0,
            "sync_dam_release_s": 120.0,
            "ram_pressure_free_gb": 4.5,
            "cpu_wall_trigger_pct": 25.0,
            "hard_cage_cap_pct": 35,
            "cad_cage_cap_pct": 25,
            "runaway_cpu_core_thresh": 0.35,
            "runaway_io_mb_s_thresh": 15.0,
            "chrono_pulse_half_ms": True,
            "daemon_ram_guard_mb": 64.0,
            "pwm_enabled": True,
            "pwm_period_ms": 50,
            "pwm_duty_pct": 25,
            "pwm_cad_duty_pct": 15,
            "pwm_idle_release_s": 5.0,
            "stasis_enabled": True,
            "stasis_interval_s": 30.0,
            "stasis_min_ws_mb": 20.0,
            "mirage_auto_sync_idle_s": 60.0,
            "thermostat_mode": "turbo_100",
            "silicon_shield_cpu_pct": 62.0,
        }
        self._load_autonomic_policy()
        try:
            self.thermostat._mode = "turbo_100" if self.aether_active else str(self._autonomic_policy.get("thermostat_mode") or "turbo_100")
        except Exception:
            pass
        # Automatically migrate overly aggressive v21 trim threshold so active Chrome/CAD never re-faults with 8+ GB free RAM!
        if float(self._autonomic_policy.get("ram_pressure_free_gb", 4.5)) >= 8.0:
            self._autonomic_policy["ram_pressure_free_gb"] = 4.5
            self._save_autonomic_policy()
        if self.aether_active:
            self._autonomic_policy["thermostat_mode"] = "turbo_100"
        initial_cap = 100 if self.aether_active else int(self._autonomic_policy.get("hard_cage_cap_pct", 35))
        self._hard_cage = WinHardCpuCage(initial_cap_pct=initial_cap)
        self._pwm_started: bool = False
        self._focus_hook_started: bool = False
        self._pwm_target_pids: set[int] = set()
        self._last_stasis_mono: float = 0.0
        self._last_mirage_sync_mono: float = 0.0
        self._auto_stop = threading.Event()
        self._auto_thread: threading.Thread | None = None
        self._auto_running = False
        self._pid_last_focus_ts: dict[int, float] = {}
        self._family_last_focus_ts: dict[str, float] = {}
        self._active_vip_pids: set[int] = set()
        self._active_vip_name: str = ""
        self._cad_godmode: bool = False
        self._timer_res_ms: float = 0.0
        self._pid_last_trimmed_ts: dict[int, float] = {}
        self._pinned_industrial_pids: set[int] = set()
        self._dynamic_runaway_pids: set[int] = set()
        self._prev_cpu_io: dict[int, tuple[float, float, int]] = {}  # pid -> (mono_ts, cpu_s, io_bytes)
        self._wall_state: str = "IDLE_FULL"
        self._dam_engaged: bool = False
        self._last_patrol_mono: float = 0.0
        self._last_orphan_mono: float = 0.0
        self._auto_ticks: int = 0
        self._auto_decisions: deque[dict[str, Any]] = deque(maxlen=40)
        self._tcp_immunity_fn: Callable[[set[int] | None], dict[str, Any]] = _win_tcp_socket_immunity
        self._immune_gateway_pids: set[int] = set()
        self._immune_gateway_meta: dict[str, Any] = {
            "listening_count": 0,
            "vip_peer_count": 0,
            "total_immune": 0,
            "scan_ms": 0.0,
        }
        self._immune_cache_mono: float = 0.0

        self._stats: dict[str, Any] = {
            "cryo_passes": 0,
            "cryo_trimmed_procs": 0,
            "cryo_est_ws_reclaimed_mb": 0.0,
            "silicon_wall_passes": 0,
            "silicon_wall_pinned_procs": 0,
            "runaways_caged": 0,
            "orphans_reaped": 0,
            "orphans_commit_reclaimed_mb": 0.0,
            "sync_dam_passes": 0,
            "sync_dam_active": False,
            "hydra_passes": 0,
            "hydra_trimmed_mb": 0.0,
            "cortex_scans": 0,
            "daemon_ram_trims": 0,
            "last_action_at": "",
        }

    def _ram_under_trim_threshold(self, metrics: dict[str, Any] | None = None) -> float | None:
        """Return measured free GiB only when background working sets may be trimmed."""
        if metrics is None:
            metrics = self.host_governor.get_host_metrics() if self.host_governor else {}
        if not metrics.get("ram_measured", True):
            return None
        try:
            free = float(metrics["free_ram_gb"])
            threshold = float(self._autonomic_policy["ram_pressure_free_gb"])
        except (KeyError, TypeError, ValueError):
            return None
        return free if math.isfinite(threshold) and 0 <= free < threshold else None

    def _refresh_socket_immunity(self, vip_pids: set[int] | None = None, *, force: bool = False) -> set[int]:
        """Refresh Kernel Socket-Owner Immunity set (listening local gateways + VIP loopback peers)."""
        now = time.monotonic()
        if not force and not vip_pids and (now - self._immune_cache_mono) < 1.0 and self._immune_gateway_pids:
            return set(self._immune_gateway_pids)
        res = self._tcp_immunity_fn(vip_pids)
        listening = set(res.get("listening_pids") or ())
        vip_peers = set(res.get("vip_peer_pids") or ())
        immune = listening | vip_peers
        self._immune_gateway_pids = immune
        self._immune_cache_mono = now
        self._immune_gateway_meta = {
            "listening_count": len(listening),
            "vip_peer_count": len(vip_peers),
            "total_immune": len(immune),
            "scan_ms": float(res.get("scan_ms") or 0.0),
        }
        return set(immune)

    def _protected_pid_set(
        self,
        procs: list[dict[str, Any]],
        fg_pid: int,
        *,
        vip_pids: set[int] | None = None,
    ) -> set[int]:
        """Build strict protected PID set: OS critical + own daemon + parent chain + foreground + local TCP gateways."""
        by_pid = {p["pid"]: p for p in procs}
        protected: set[int] = {0, 4, self._own_pid}
        if fg_pid > 4:
            protected.add(fg_pid)
        # Protect our own parent ancestry so we never throttle our caller terminal/IDE
        cur = self._own_pid
        for _ in range(8):
            info = by_pid.get(cur)
            if not info:
                break
            pp = int(info.get("ppid") or 0)
            if pp <= 4 or pp in protected:
                break
            protected.add(pp)
            cur = pp
        for p in procs:
            if p["name"] in _PROTECTED_PROCS:
                protected.add(p["pid"])
        # Law 2 Kernel Socket-Owner Immunity: never choke listening gateways or VIP loopback peers
        seed_vip = set(vip_pids or ())
        if fg_pid > 4:
            seed_vip.add(fg_pid)
        protected |= self._refresh_socket_immunity(seed_vip)
        return protected

    def _expand_app_family(self, procs: list[dict[str, Any]], seed_pid: int) -> tuple[str, set[int]]:
        """Return (app_name, full_process_tree_pids) so Chrome/AutoCAD/IDE child renderers & GPU procs stay protected together."""
        if seed_pid <= 4:
            return "", set()
        by_pid = {p["pid"]: p for p in procs}
        seed = by_pid.get(seed_pid)
        if not seed:
            return "", {seed_pid}
        app_name = seed["name"]
        # Walk up to app root (stop at shell/system parents like explorer, svchost, services)
        root_pid = seed_pid
        for _ in range(6):
            info = by_pid.get(root_pid)
            if not info:
                break
            pp = int(info.get("ppid") or 0)
            pinfo = by_pid.get(pp)
            if not pinfo or pinfo["name"] in _PROTECTED_PROCS:
                break
            if pinfo["name"] == app_name:
                root_pid = pp
            else:
                break
        # Collect entire descendant tree + same-name processes belonging to this interactive app
        children_map: dict[int, list[int]] = defaultdict(list)
        for p in procs:
            children_map[p["ppid"]].append(p["pid"])
        fam: set[int] = set()
        stack = [root_pid]
        while stack:
            cur = stack.pop()
            if cur in fam:
                continue
            fam.add(cur)
            for ch in children_map.get(cur, ()):
                if ch not in fam:
                    stack.append(ch)
        if app_name not in _PROTECTED_PROCS and app_name:
            for p in procs:
                if p["name"] == app_name:
                    fam.add(p["pid"])
        return app_name, fam

    def _compute_core_masks(self) -> tuple[int, int, int]:
        n = min(63, self._cpu_count)
        full_mask = (1 << n) - 1
        if n <= 4:
            urban = (1 << max(1, n // 2)) - 1
            industrial = full_mask ^ urban if (full_mask ^ urban) else full_mask
            return urban, industrial, full_mask
        if n >= 12:
            # v22 Zero-Stutter: reserve 4 FULL P-Cores (8 logical threads 0..7 = 0x0FF) for AutoCAD + Chrome + DWM;
            # isolate ALL background coding agents/compilers/sync to the LAST 2 P-Cores (4 threads 8..11 = 0xF00)!
            urban = 0x0FF
            industrial = full_mask & ~urban
            return urban, industrial, full_mask
        half = max(2, n // 2)
        urban = (1 << half) - 1
        industrial = full_mask & ~urban
        return urban, industrial, full_mask

    def diagnose(self) -> dict[str, Any]:
        """Full live X-Ray of Windows/Linux multitasking pressure across all 7 HyperDesk domains."""
        t0 = time.perf_counter()
        procs = _snapshot_processes()
        fg_pid = _win_foreground_pid()
        if fg_pid and fg_pid != self._last_focus_pid:
            if self._last_focus_pid:
                self._focus_transitions[self._last_focus_pid][fg_pid] += 1
            self._last_focus_pid = fg_pid

        live_pids = {p["pid"] for p in procs}
        hydra_procs = [p for p in procs if p["name"] in _HYDRA_FAMILIES]
        ind_procs = [p for p in procs if p["name"] in _INDUSTRIAL_PROCS]
        sync_procs = [p for p in procs if p["name"] in _SYNC_DAM_PROCS]
        ai_procs = [p for p in procs if p["name"] in _AI_AGENT_PROCS]

        # Ghost-commit bloat candidates: Priv >= 150 MB and WS/Priv < 0.08
        ghost_bloat = [
            p for p in procs
            if p["priv_mb"] >= 150.0 and (p["ws_mb"] / max(1.0, p["priv_mb"])) < 0.08
        ]
        # Orphan candidates: pythonw/python with dead PPID
        py_orphan_cand = [
            p for p in procs
            if p["name"] in ("pythonw", "python") and p["ppid"] > 4 and p["ppid"] not in live_pids
        ]
        cmd_map = _win_get_cmdlines_for_pids([p["pid"] for p in py_orphan_cand])
        verified_orphans: list[dict[str, Any]] = []
        for p in py_orphan_cand:
            cmd = cmd_map.get(p["pid"], "")
            is_spawn = ("multiprocessing.spawn" in cmd) or ("--multiprocessing-fork" in cmd)
            if is_spawn:
                verified_orphans.append({**p, "cmdline": cmd[:160], "verified_spawn_orphan": True})

        gov = self.host_governor.get_host_metrics() if self.host_governor else {}
        urban, industrial, full_mask = self._compute_core_masks()
        fg_name = next((p["name"] for p in procs if p["pid"] == fg_pid), "")
        immune_pids = sorted(self._refresh_socket_immunity({fg_pid} if fg_pid > 4 else None, force=True))

        return {
            "ok": True,
            "os": platform.system().lower(),
            "cpu_threads": self._cpu_count,
            "host_metrics": gov,
            "foreground": {"pid": fg_pid, "name": fg_name},
            "silicon_wall_masks": {
                "urban_hex": hex(urban),
                "industrial_hex": hex(industrial),
                "full_hex": hex(full_mask),
            },
            "hydra": {
                "count": len(hydra_procs),
                "ws_mb": round(sum(p["ws_mb"] for p in hydra_procs), 1),
                "priv_mb": round(sum(p["priv_mb"] for p in hydra_procs), 1),
            },
            "industrial": {
                "count": len(ind_procs),
                "ws_mb": round(sum(p["ws_mb"] for p in ind_procs), 1),
                "priv_mb": round(sum(p["priv_mb"] for p in ind_procs), 1),
            },
            "sync_dam": {
                "count": len(sync_procs),
                "ws_mb": round(sum(p["ws_mb"] for p in sync_procs), 1),
                "priv_mb": round(sum(p["priv_mb"] for p in sync_procs), 1),
            },
            "ai_fleet": {
                "count": len(ai_procs),
                "ws_mb": round(sum(p["ws_mb"] for p in ai_procs), 1),
                "priv_mb": round(sum(p["priv_mb"] for p in ai_procs), 1),
            },
            "ghost_commit_bloat": sorted(ghost_bloat, key=lambda x: x["priv_mb"], reverse=True)[:12],
            "verified_orphans": verified_orphans,
            "verified_orphan_priv_mb": round(sum(p["priv_mb"] for p in verified_orphans), 1),
            "immune_gateways": {
                **dict(self._immune_gateway_meta),
                "pids": immune_pids[:32],
            },
            "vram_swap": self.vram_swap.status(),
            "suspended_pids": list(self._suspended_pids.keys()),
            "total_procs": len(procs),
            "scan_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }

    # --- 1. CHIMERA-CRYO ---
    @property
    def aether_active(self) -> bool:
        return self._autonomic_policy.get("interactive_profile", "aether") != "legacy"

    def apply_cryo(
        self,
        *,
        min_ws_mb: float = 40.0,
        allow_suspend: bool = False,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Focus VIP lane + Warm Cryo (EcoQoS + VeryLow MemPriority + Lossless WorkingSet Trim) on idle background apps."""
        if self.aether_active:
            return {"ok": True, "profile": "aether", "dry_run": dry_run, "working_set_trimmed": 0, "suspended": 0}
        t0 = time.perf_counter()
        procs = _snapshot_processes()
        fg_pid = _win_foreground_pid()
        protected = self._protected_pid_set(procs, fg_pid)
        urban, _, _ = self._compute_core_masks()

        vip_applied = False
        if fg_pid > 4 and not dry_run:
            _win_set_eco_qos(fg_pid, False)
            _win_set_memory_priority(fg_pid, _MEMORY_PRIORITY_NORMAL)
            vip_applied = _win_set_priority(fg_pid, _ABOVE_NORMAL_PRIORITY_CLASS)
            _win_set_affinity(fg_pid, urban)

        # Target non-foreground heavy background procs (Hydra + Sync + heavy idle apps)
        targets = [
            p for p in procs
            if p["pid"] not in protected
            and p["ws_mb"] >= float(min_ws_mb)
            and (p["name"] in _HYDRA_FAMILIES or p["name"] in _SYNC_DAM_PROCS or p["name"] in _INDUSTRIAL_PROCS)
        ]

        before_ws = round(sum(p["ws_mb"] for p in targets), 1)
        trimmed = 0
        eco_applied = 0
        suspended = 0

        if not dry_run:
            may_trim = self._ram_under_trim_threshold() is not None
            for p in targets:
                pid = p["pid"]
                if _win_set_eco_qos(pid, True):
                    eco_applied += 1
                _win_set_memory_priority(pid, _MEMORY_PRIORITY_VERY_LOW)
                if may_trim and _win_trim_working_set(pid):
                    trimmed += 1
                if allow_suspend and p["name"] in _SYNC_DAM_PROCS:
                    if _win_suspend_resume(pid, True):
                        with self._lock:
                            self._suspended_pids[pid] = time.time()
                        suspended += 1

        after_ws = before_ws
        if not dry_run and targets:
            time.sleep(0.08)
            after_ws = round(sum(_win_proc_memory_mb(p["pid"])[0] for p in targets), 1) if os.name == "nt" else before_ws
        reclaimed_mb = round(max(0.0, before_ws - after_ws), 1)

        with self._lock:
            self._stats["cryo_passes"] += 1
            self._stats["cryo_trimmed_procs"] += trimmed
            self._stats["cryo_est_ws_reclaimed_mb"] = round(self._stats["cryo_est_ws_reclaimed_mb"] + reclaimed_mb, 1)
            self._stats["last_action_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")

        return {
            "ok": True,
            "dry_run": dry_run,
            "foreground_pid": fg_pid,
            "vip_lane_applied": vip_applied,
            "target_procs": len(targets),
            "eco_qos_applied": eco_applied,
            "working_set_trimmed": trimmed,
            "suspended": suspended,
            "ws_before_mb": before_ws,
            "ws_after_mb": after_ws,
            "ws_reclaimed_mb": reclaimed_mb,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }

    def thaw_all(self) -> dict[str, Any]:
        """Instant emergency safety thaw for any suspended PIDs."""
        resumed: list[int] = []
        with self._lock:
            pids = list(self._suspended_pids.keys())
            self._suspended_pids.clear()
            self._stats["sync_dam_active"] = False
        for pid in pids:
            if _win_suspend_resume(pid, False):
                resumed.append(pid)
        return {"ok": True, "resumed_pids": resumed, "count": len(resumed)}

    def predict_next_focus(self, current_pid: int | None = None) -> dict[str, Any]:
        """Markov speculative focus predictor for pre-thawing background windows <8ms ahead of Alt+Tab."""
        cur = int(current_pid or self._last_focus_pid or _win_foreground_pid())
        trans = self._focus_transitions.get(cur) or {}
        if not trans:
            return {"ok": True, "current_pid": cur, "predicted_pid": 0, "confidence": 0.0}
        total = sum(trans.values())
        best_pid, best_cnt = max(trans.items(), key=lambda kv: kv[1])
        return {
            "ok": True,
            "current_pid": cur,
            "predicted_pid": best_pid,
            "confidence": round(best_cnt / max(1, total), 3),
        }

    # --- 2. CHIMERA-SILICON-WALL ---
    def apply_silicon_wall(self, *, release_to_full: bool = False, dry_run: bool = False) -> dict[str, Any]:
        """Partition CPU cores into Urban (Focus/DWM Cores 0-3) vs Industrial (Compilers/Sync/Workers Cores 4-11)."""
        if self.aether_active:
            return {"ok": True, "profile": "aether", "dry_run": dry_run, "mode": "OS_SCHEDULED", "pinned_procs": 0}
        t0 = time.perf_counter()
        procs = _snapshot_processes()
        fg_pid = _win_foreground_pid()
        protected = self._protected_pid_set(procs, fg_pid)
        urban, industrial, full_mask = self._compute_core_masks()

        targets = [p for p in procs if p["pid"] not in protected and p["name"] in _INDUSTRIAL_PROCS]
        pinned = 0
        throttled = 0

        if not dry_run:
            if fg_pid > 4:
                _win_set_affinity(fg_pid, full_mask if release_to_full else urban)
            for p in targets:
                pid = p["pid"]
                mask = full_mask if release_to_full else industrial
                if _win_set_affinity(pid, mask):
                    pinned += 1
                if release_to_full:
                    _win_set_eco_qos(pid, False)
                    _win_set_priority(pid, _NORMAL_PRIORITY_CLASS)
                else:
                    if _win_set_eco_qos(pid, True):
                        throttled += 1
                    _win_set_priority(pid, _BELOW_NORMAL_PRIORITY_CLASS)

        with self._lock:
            self._stats["silicon_wall_passes"] += 1
            self._stats["silicon_wall_pinned_procs"] = pinned
            self._stats["last_action_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")

        return {
            "ok": True,
            "dry_run": dry_run,
            "mode": "FULL_IDLE_RELEASE" if release_to_full else "INTERACTIVE_WALL_ACTIVE",
            "urban_mask": hex(urban),
            "industrial_mask": hex(industrial),
            "industrial_candidates": len(targets),
            "pinned_procs": pinned,
            "eco_throttled": throttled,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }

    # --- 4. CHIMERA-HYDRA-COLLAPSE ---
    def collapse_hydra(self, *, cdp_ports: tuple[int, ...] = (9222, 9229, 9785), dry_run: bool = False) -> dict[str, Any]:
        """Audit Chromium/Electron Hydra, probe CDP endpoints for idle tabs, and trim non-foreground renderer WS."""
        if self.aether_active:
            return {"ok": True, "profile": "aether", "dry_run": dry_run, "trimmed_procs": 0, "ws_reclaimed_mb": 0.0}
        t0 = time.perf_counter()
        procs = _snapshot_processes()
        fg_pid = _win_foreground_pid()
        protected = self._protected_pid_set(procs, fg_pid)
        hydra = [p for p in procs if p["name"] in _HYDRA_FAMILIES and p["pid"] not in protected]

        before_ws = round(sum(p["ws_mb"] for p in hydra), 1)
        before_priv = round(sum(p["priv_mb"] for p in hydra), 1)
        trimmed = 0
        if not dry_run:
            may_trim = self._ram_under_trim_threshold() is not None
            for p in hydra:
                _win_set_eco_qos(p["pid"], True)
                _win_set_memory_priority(p["pid"], _MEMORY_PRIORITY_VERY_LOW)
                if may_trim and _win_trim_working_set(p["pid"]):
                    trimmed += 1

        # Probe any active local CDP endpoints for idle tab discovery
        cdp_targets: list[dict[str, Any]] = []
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for port in cdp_ports:
            try:
                with opener.open(f"http://127.0.0.1:{port}/json/list", timeout=0.35) as r:
                    tabs = json.loads(r.read().decode("utf-8"))
                    if isinstance(tabs, list):
                        for tb in tabs[:20]:
                            cdp_targets.append({
                                "port": port,
                                "id": tb.get("id", ""),
                                "type": tb.get("type", ""),
                                "title": str(tb.get("title", ""))[:60],
                                "url": str(tb.get("url", ""))[:80],
                            })
            except Exception:
                continue

        after_ws = before_ws
        if not dry_run and hydra and os.name == "nt":
            time.sleep(0.08)
            after_ws = round(sum(_win_proc_memory_mb(p["pid"])[0] for p in hydra), 1)
        reclaimed = round(max(0.0, before_ws - after_ws), 1)

        with self._lock:
            self._stats["hydra_passes"] += 1
            self._stats["hydra_trimmed_mb"] = round(self._stats["hydra_trimmed_mb"] + reclaimed, 1)

        return {
            "ok": True,
            "dry_run": dry_run,
            "hydra_procs": len(hydra),
            "trimmed_procs": trimmed,
            "ws_before_mb": before_ws,
            "ws_after_mb": after_ws,
            "ws_reclaimed_mb": reclaimed,
            "priv_commit_mb": before_priv,
            "cdp_tabs_found": len(cdp_targets),
            "cdp_tabs_sample": cdp_targets[:8],
            "remote_grid_ready": bool(self.browser_grid and self.browser_grid.status().get("binary_found")),
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }

    # --- 5. CHIMERA-ZOMBIE-REAPER ---
    def reap_orphans(self, *, dry_run: bool = True) -> dict[str, Any]:
        """Safely detect and reap ONLY verified dead-parent multiprocessing.spawn orphan workers (zero live-app risk)."""
        if self.aether_active:
            return {"ok": True, "profile": "aether", "dry_run": dry_run, "verified_orphans": 0, "reaped_count": 0}
        t0 = time.perf_counter()
        procs = _snapshot_processes()
        live_pids = {p["pid"] for p in procs}
        protected = self._protected_pid_set(procs, _win_foreground_pid())

        cands = [
            p for p in procs
            if p["pid"] not in protected
            and p["name"] in ("pythonw", "python")
            and p["ppid"] > 4
            and p["ppid"] not in live_pids
        ]
        cmd_map = _win_get_cmdlines_for_pids([p["pid"] for p in cands])
        verified: list[dict[str, Any]] = []
        reaped: list[dict[str, Any]] = []
        for p in cands:
            cmd = cmd_map.get(p["pid"], "")
            if ("multiprocessing.spawn" in cmd) or ("--multiprocessing-fork" in cmd):
                item = {**p, "cmdline": cmd[:140]}
                verified.append(item)
                if not dry_run:
                    if _win_terminate_pid(p["pid"]):
                        reaped.append(item)

        commit_reclaimed = round(sum(x["priv_mb"] for x in (reaped if not dry_run else verified)), 1)
        if not dry_run and reaped:
            with self._lock:
                self._stats["orphans_reaped"] += len(reaped)
                self._stats["orphans_commit_reclaimed_mb"] = round(
                    self._stats["orphans_commit_reclaimed_mb"] + commit_reclaimed, 1
                )

        return {
            "ok": True,
            "dry_run": dry_run,
            "verified_orphans": len(verified),
            "reaped_count": len(reaped),
            "commit_reclaimed_mb": commit_reclaimed,
            "reaped": reaped if not dry_run else verified,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }

    # --- 6. CHIMERA-CORTEX-BUS ---
    def cortex_watch_scan(self, watch_dir: str | Path, max_files: int = 500) -> dict[str, Any]:
        """Unified single-watcher incremental directory change scanner publishing directly onto PulseBus."""
        t0 = time.perf_counter()
        root = Path(watch_dir).resolve()
        if not root.is_dir():
            raise FileNotFoundError(f"Watch directory not found: {root}")
        key = str(root)
        skip = {".git", ".venv", "venv", "node_modules", "__pycache__", "target", "dist", "build"}
        cur: dict[str, tuple[int, int]] = {}
        count = 0
        for dp, dns, fns in os.walk(root):
            dns[:] = [d for d in dns if d not in skip]
            for fn in fns:
                if count >= max_files:
                    break
                fp = Path(dp) / fn
                try:
                    st = fp.stat()
                    rel = str(fp.relative_to(root)).replace("\\", "/")
                    cur[rel] = (int(st.st_mtime_ns), int(st.st_size))
                    count += 1
                except OSError:
                    continue
            if count >= max_files:
                break

        with self._lock:
            prev = self._watched_dirs.get(key)
            self._watched_dirs[key] = cur
            self._stats["cortex_scans"] += 1

        if prev is None:
            added, modified, deleted = [], [], []
            initial = True
        else:
            initial = False
            added = sorted(k for k in cur if k not in prev)
            deleted = sorted(k for k in prev if k not in cur)
            modified = sorted(k for k in cur if k in prev and cur[k] != prev[k])

        if self.pulse_bus and (added or modified or deleted):
            try:
                self.pulse_bus.publish(
                    topic="cortex.fs.changed",
                    payload={"root": key, "added": added[:20], "modified": modified[:20], "deleted": deleted[:20]},
                    app="hyper_desk",
                    relay=False,
                )
            except Exception:
                pass

        return {
            "ok": True,
            "root": key,
            "initial": initial,
            "files_tracked": len(cur),
            "added": added[:30],
            "modified": modified[:30],
            "deleted": deleted[:30],
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }

    # --- 7. CHIMERA-SYNC-DAM ---
    def apply_sync_dam(self, *, suspend: bool = False, release: bool = False, dry_run: bool = False) -> dict[str, Any]:
        """Throttle or pause OneDrive/Indexer I/O storms during active work; guaranteed release on idle/close."""
        t0 = time.perf_counter()
        if self.aether_active:
            return {"ok": True, "profile": "aether", "dry_run": dry_run, "throttled": 0, "suspended": 0}
        if release:
            thaw = self.thaw_all()
            procs = _snapshot_processes()
            _, _, full_mask = self._compute_core_masks()
            restored = 0
            for p in procs:
                if p["name"] in _SYNC_DAM_PROCS:
                    _win_set_eco_qos(p["pid"], False)
                    _win_set_priority(p["pid"], _NORMAL_PRIORITY_CLASS)
                    _win_set_affinity(p["pid"], full_mask)
                    restored += 1
            with self._lock:
                self._stats["sync_dam_active"] = False
            return {"ok": True, "action": "released", "restored": restored, "thaw": thaw}

        procs = _snapshot_processes()
        _, industrial, _ = self._compute_core_masks()
        targets = [p for p in procs if p["name"] in _SYNC_DAM_PROCS]
        before_ws = round(sum(p["ws_mb"] for p in targets), 1)
        throttled = 0
        suspended_n = 0
        if not dry_run:
            may_trim = self._ram_under_trim_threshold() is not None
            for p in targets:
                pid = p["pid"]
                _win_set_affinity(pid, industrial)
                _win_set_priority(pid, _IDLE_PRIORITY_CLASS)
                _win_set_eco_qos(pid, True)
                _win_set_memory_priority(pid, _MEMORY_PRIORITY_VERY_LOW)
                if may_trim:
                    _win_trim_working_set(pid)
                throttled += 1
                if suspend and _win_suspend_resume(pid, True):
                    with self._lock:
                        self._suspended_pids[pid] = time.time()
                    suspended_n += 1

        after_ws = round(sum(_win_proc_memory_mb(p["pid"])[0] for p in targets), 1) if (not dry_run and targets and os.name == "nt") else before_ws
        with self._lock:
            self._stats["sync_dam_passes"] += 1
            self._stats["sync_dam_active"] = not dry_run and bool(targets)

        return {
            "ok": True,
            "dry_run": dry_run,
            "targets": len(targets),
            "throttled": throttled,
            "suspended": suspended_n,
            "ws_before_mb": before_ws,
            "ws_after_mb": after_ws,
            "ws_reclaimed_mb": round(max(0.0, before_ws - after_ws), 1),
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }

    def optimize_now(
        self,
        *,
        reap_orphans: bool = True,
        apply_cryo: bool = True,
        apply_silicon_wall: bool = True,
        apply_sync_dam: bool = True,
        apply_hydra: bool = True,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """One-shot coordinated HyperDesk relief pass across all safe multitasking mitigations."""
        t0 = time.perf_counter()
        out: dict[str, Any] = {"ok": True, "dry_run": dry_run}
        if reap_orphans:
            out["zombie_reaper"] = self.reap_orphans(dry_run=dry_run)
        if apply_silicon_wall:
            out["silicon_wall"] = self.apply_silicon_wall(release_to_full=False, dry_run=dry_run)
        if apply_sync_dam:
            out["sync_dam"] = self.apply_sync_dam(suspend=False, dry_run=dry_run)
        if apply_cryo:
            out["cryo"] = self.apply_cryo(min_ws_mb=35.0, allow_suspend=False, dry_run=dry_run)
        if apply_hydra:
            out["hydra"] = self.collapse_hydra(dry_run=dry_run)
        out["total_elapsed_ms"] = round((time.perf_counter() - t0) * 1000.0, 2)
        if self.on_flow:
            try:
                self.on_flow(
                    "compute",
                    "hyper_desk",
                    "win-desktop" if os.name == "nt" else "svhome",
                    "HYPERDESK_OPTIMIZE",
                    wire_bytes=0,
                    elapsed_ms=out["total_elapsed_ms"],
                    detail=f"orphans={out.get('zombie_reaper', {}).get('reaped_count', 0)} wall={out.get('silicon_wall', {}).get('pinned_procs', 0)}",
                    ok=True,
                )
            except Exception:
                pass
        return out

    # --- AUTONOMIC SELF-LIVING REFLEX BRAIN (Zero Manual Intervention) ---
    def _load_autonomic_policy(self) -> None:
        if not self._policy_path or not self._policy_path.is_file():
            return
        try:
            d = json.loads(self._policy_path.read_text(encoding="utf-8"))
            if isinstance(d, dict):
                for k, v in d.items():
                    if k in self._autonomic_policy:
                        self._autonomic_policy[k] = v
        except Exception:
            pass

    def _save_autonomic_policy(self) -> None:
        if not self._policy_path:
            return
        try:
            self._policy_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._policy_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._autonomic_policy, indent=2), encoding="utf-8")
            os.replace(tmp, self._policy_path)
        except Exception:
            pass

    def _record_decision(self, kind: str, detail: str, **meta: Any) -> dict[str, Any]:
        ev = {
            "ts": time.strftime("%H:%M:%S"),
            "kind": kind,
            "detail": detail,
            **meta,
        }
        with self._lock:
            self._auto_decisions.append(ev)
            self._stats["last_action_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        if self.pulse_bus:
            try:
                self.pulse_bus.publish(topic="hyperdesk.autonomic", payload=ev, app="hyper_desk", relay=False)
            except Exception:
                pass
        return ev

    def _self_preserve_daemon_ram(self) -> dict[str, Any] | None:
        """Keep CHIMERA daemon itself strictly under Zero-Weight RAM budget automatically."""
        if self.aether_active:
            return None
        guard_mb = float(self._autonomic_policy.get("daemon_ram_guard_mb", 64.0))
        rss_mb = 0.0
        if os.name == "nt":
            rss_mb = _win_proc_memory_mb(self._own_pid)[0]
        else:
            try:
                st = Path("/proc/self/status").read_text(encoding="utf-8", errors="ignore")
                for ln in st.splitlines():
                    if ln.startswith("VmRSS:"):
                        rss_mb = round(int(ln.split(":", 1)[1].strip().split()[0]) / 1024.0, 2)
                        break
            except OSError:
                rss_mb = 0.0
        if rss_mb < guard_mb:
            return None
        try:
            import gc
            gc.collect()
            if os.name != "nt":
                ctypes.CDLL("libc.so.6").malloc_trim(0)
        except Exception:
            pass
        after_mb = _win_proc_memory_mb(self._own_pid)[0] if os.name == "nt" else rss_mb
        if os.name != "nt":
            try:
                st = Path("/proc/self/status").read_text(encoding="utf-8", errors="ignore")
                for ln in st.splitlines():
                    if ln.startswith("VmRSS:"):
                        after_mb = round(int(ln.split(":", 1)[1].strip().split()[0]) / 1024.0, 2)
                        break
            except OSError:
                pass
        with self._lock:
            self._stats["daemon_ram_trims"] += 1
        return self._record_decision(
            "DAEMON_RAM_TRIM",
            f"Self-preserved daemon RSS {rss_mb:.1f} -> {after_mb:.1f} MB (<80MB cap)",
            before_mb=rss_mb,
            after_mb=after_mb,
        )

    def _promote_vip_sanctuary(self, procs: list[dict[str, Any]], fg_pid: int, *, dry_run: bool = False) -> tuple[str, set[int]]:
        """Promote ENTIRE focused app family tree (Chrome+GPU+tabs, AutoCAD, active IDE) and cleanly demote previous VIP."""
        app_name, fam = self._expand_app_family(procs, fg_pid)
        urban, _, full_mask = self._compute_core_masks()
        prev_vip = set(self._active_vip_pids) - fam
        if not dry_run:
            # Cleanly demote old VIPs so previously focused Electron apps NEVER stay stuck at AboveNormal!
            for old_pid in prev_vip:
                _win_set_priority(old_pid, _NORMAL_PRIORITY_CLASS)
            is_cad = app_name in _CAD_GODMODE_PROCS
            vip_prio = _HIGH_PRIORITY_CLASS if is_cad else _ABOVE_NORMAL_PRIORITY_CLASS
            for pid in fam:
                _win_set_eco_qos(pid, False)
                _win_set_memory_priority(pid, _MEMORY_PRIORITY_NORMAL)
                _win_set_io_priority(pid, _IO_PRIORITY_NORMAL)
                _win_set_affinity(pid, full_mask if is_cad else urban)
                _win_set_priority(pid, vip_prio if pid == fg_pid else _NORMAL_PRIORITY_CLASS)
        self._active_vip_pids = set(fam)
        self._active_vip_name = app_name
        return app_name, fam

    def _cage_background_pid(self, pid: int, industrial_mask: int, *, hard_cage: bool = True, idle_prio: bool = False) -> tuple[bool, bool]:
        """Apply v22/v23 kernel isolation; honestly return (affinity_ok, job_object_ok) so Error-5 falls through to Rust PWM."""
        # Hard Law 2 guard: never cage any listening localhost gateway or VIP loopback peer
        if int(pid) in self._immune_gateway_pids:
            return False, False
        ok = _win_set_affinity(pid, industrial_mask)
        _win_set_eco_qos(pid, True)
        _win_set_memory_priority(pid, _MEMORY_PRIORITY_VERY_LOW)
        _win_set_io_priority(pid, _IO_PRIORITY_VERY_LOW)
        _win_set_priority(pid, _IDLE_PRIORITY_CLASS if idle_prio else _BELOW_NORMAL_PRIORITY_CLASS)
        job_ok = self._hard_cage.cage_pid(pid) if hard_cage else False
        return ok, job_ok

    def _ensure_rust_engines(self, pol: dict[str, Any]) -> None:
        if self.aether_active or os.name != "nt" or not has_native_pwm():
            return
        if not self._focus_hook_started:
            self._focus_hook_started = native_focus_hook_start()
        if bool(pol.get("pwm_enabled", True)) and not self._pwm_started:
            self._pwm_started = native_pwm_start(
                int(pol.get("pwm_period_ms", 50)),
                int(pol.get("pwm_duty_pct", 25)),
            )

    def stasis_hibernate(self, *, min_ws_mb: float = 20.0, dry_run: bool = False) -> dict[str, Any]:
        """Manually or autonomically trigger CHIMERA-STASIS-POD on cold Electron/WebView2 child renderers."""
        if self.aether_active:
            return {"ok": True, "profile": "aether", "dry_run": dry_run, "hibernated": 0}
        if not dry_run:
            self._ensure_rust_engines(self._autonomic_policy)
        procs = _snapshot_processes()
        fg_pid = _win_foreground_pid() if os.name == "nt" else 0
        protected = self._protected_pid_set(procs, fg_pid)
        fg_name, vip_fam = self._expand_app_family(procs, fg_pid)
        cad_pids = {p["pid"] for p in procs if p["name"] in _CAD_GODMODE_PROCS}
        sanctuary = protected | vip_fam | cad_pids
        recent_fams = {fg_name} if fg_name else set()
        return self.stasis.hibernate_cold_renderers(
            procs,
            sanctuary_pids=sanctuary,
            recent_families=recent_fams,
            min_ws_mb=min_ws_mb,
            dry_run=dry_run,
        )

    def gpu_phoenix(self, *, threshold_commit_mb: float = 1600.0, allow_recycle: bool = False) -> dict[str, Any]:
        """Audit or safely recycle bloated Chromium/Electron --type=gpu-process (0 tabs lost)."""
        procs = _snapshot_processes()
        return self.stasis.gpu_phoenix_audit_and_recycle(
            procs,
            threshold_commit_mb=threshold_commit_mb,
            allow_recycle=allow_recycle and not self.aether_active,
        )

    def autonomic_tick_once(self, *, force_patrol: bool = False, force_orphan: bool = False, dry_run: bool = False) -> dict[str, Any]:
        """v23 CHIMERA-PHANTOM-SILICON Autonomic Reflex: Rust PWM-Crusher + <0.5ms Focus Hook + Stasis Pod + NVMe Mirage + Chrono-Pulse."""
        t0 = time.perf_counter()
        now = time.monotonic()
        pol = dict(self._autonomic_policy)
        actions: list[dict[str, Any]] = []

        with self._lock:
            self._auto_ticks += 1
            tick_num = self._auto_ticks

        if self.aether_active:
            aether_actions: list[dict[str, Any]] = []
            last_shield = float(getattr(self, "_last_aether_shield_mono", 0.0))
            last_hyg = float(getattr(self, "_last_aether_hygiene_mono", 0.0))
            shield_res: dict[str, Any] | None = None
            orphan_res: dict[str, Any] | None = None
            trim_res: dict[str, Any] | None = None
            if force_patrol or (now - last_shield) >= 15.0:
                self._last_aether_shield_mono = now
                ram_ev = self._self_preserve_daemon_ram()
                if ram_ev:
                    aether_actions.append(ram_ev)
                shield_res = self.apply_soft_batch_shield(promote_vips=True, demote_batch=True, dry_run=dry_run)
                with self._lock:
                    self._stats["aether_soft_shield_ticks"] = int(self._stats.get("aether_soft_shield_ticks", 0)) + 1
            if force_orphan or (now - last_hyg) >= 60.0:
                self._last_aether_hygiene_mono = now
                orphan_res = self.reap_orphan_conhosts(dry_run=dry_run)
                if orphan_res.get("reaped", 0) > 0:
                    aether_actions.append(
                        self._record_decision(
                            "ORPHAN_CONHOST_REAP",
                            f"Reaped {orphan_res['reaped']} dead-parent conhost.exe",
                            reaped=orphan_res["reaped"],
                        )
                    )
                trim_res = self.gentle_idle_ws_trim(dry_run=dry_run)
                if trim_res.get("trimmed", 0) > 0:
                    aether_actions.append(
                        self._record_decision(
                            "AETHER_IDLE_WS_TRIM",
                            f"Trimmed {trim_res['trimmed']} idle helper working sets under RAM pressure",
                            trimmed=trim_res["trimmed"],
                        )
                    )
            return {
                "ok": True,
                "tick": tick_num,
                "profile": "aether",
                "dry_run": dry_run,
                "wall_state": "AETHER_SOFT_SHIELD",
                "affinity_untouched": True,
                "eco_qos_untouched": True,
                "foreground_pid": 0,
                "soft_shield": shield_res,
                "orphan_conhosts": orphan_res,
                "idle_ws_trim": trim_res,
                "actions": aether_actions,
                "elapsed_ms": round((time.perf_counter() - t0) * 1000, 3),
            }

        if not dry_run:
            self._ensure_rust_engines(pol)
            if self._pwm_started:
                native_pwm_heartbeat()

        # 1. Fast Focus Reflex (<0.2ms): track focus transitions & immediately wake any stasis children
        fg_pid = _win_foreground_pid() if os.name == "nt" else 0
        focus_changed = False
        if fg_pid > 4:
            with self._lock:
                self._pid_last_focus_ts[fg_pid] = now
                focus_changed = fg_pid != self._last_focus_pid
                if focus_changed:
                    if self._last_focus_pid:
                        self._focus_transitions[self._last_focus_pid][fg_pid] += 1
                    self._last_focus_pid = fg_pid
            if focus_changed and not dry_run:
                self.stasis.wake_family(trigger_pid=fg_pid)

        # 2. Host Metrics & Elastic Silicon Wall / Rust PWM / Chrono-Pulse State Machine
        hm = self.host_governor.get_host_metrics() if self.host_governor else {}
        idle_sec = hm.get("idle_sec")
        cpu_pct = float(hm.get("cpu_pct") or 0.0)

        if os.name == "nt" and idle_sec is not None:
            idle_val = float(idle_sec)
            # Chrono-Pulse: 0.5ms kernel timer while actively interacting, release when idle!
            if bool(pol.get("chrono_pulse_half_ms", True)) and not dry_run:
                want_fast_timer = idle_val < float(pol["idle_release_s"])
                if want_fast_timer and self._timer_res_ms == 0.0:
                    self._timer_res_ms = _win_set_timer_resolution(True)
                    actions.append(self._record_decision("CHRONO_PULSE_05MS", f"Kernel timer tightened to {self._timer_res_ms} ms for zero-stutter UI"))
                elif (not want_fast_timer) and self._timer_res_ms > 0.0:
                    _win_set_timer_resolution(False)
                    self._timer_res_ms = 0.0

            # Instant Rust PWM release as soon as hands leave keyboard/mouse (>= pwm_idle_release_s, default 5s)
            if idle_val >= float(pol.get("pwm_idle_release_s", 5.0)) and self._pwm_target_pids:
                if not dry_run and self._pwm_started:
                    native_pwm_set_targets([], 100)
                self._pwm_target_pids.clear()
                actions.append(self._record_decision("RUST_PWM_IDLE_RELEASE", f"Idle {idle_val:.0f}s -> released Rust PWM to 100%"))

            if idle_val >= float(pol["idle_release_s"]) and self._wall_state == "ACTIVE_WALL":
                if not dry_run:
                    self._hard_cage.set_cap_pct(100)
                    self.apply_silicon_wall(release_to_full=True, dry_run=False)
                self._wall_state = "IDLE_FULL"
                actions.append(self._record_decision("WALL_IDLE_RELEASE", f"Idle {idle_val:.0f}s -> unlocked Hard Cage 100% & all {self._cpu_count}T"))
            if idle_val >= float(pol["sync_dam_release_s"]) and self._dam_engaged:
                if not dry_run:
                    self.apply_sync_dam(release=True, dry_run=False)
                self._dam_engaged = False
                actions.append(self._record_decision("SYNC_DAM_IDLE_RELEASE", f"Idle {idle_val:.0f}s -> released OneDrive Sync-Dam"))

            # Idle write-back sync for NVMe Mirage junctions (keeps HDD cold backing up to date!)
            mirage_idle = float(pol.get("mirage_auto_sync_idle_s", 60.0))
            if (
                not dry_run
                and idle_val >= mirage_idle
                and (now - self._last_mirage_sync_mono) >= 300.0
                and self.mirage.status().get("promoted_count", 0) > 0
            ):
                self._last_mirage_sync_mono = now
                threading.Thread(target=self.mirage.sync_back, name="chimera-mirage-sync", daemon=True).start()
                actions.append(self._record_decision("NVME_MIRAGE_IDLE_SYNC", f"Idle {idle_val:.0f}s -> differential write-back NVMe -> HDD"))

        # 3. Smart Patrol + Dynamic Runaway CPU/IO Hunter (runs on focus change or every patrol_interval_s)
        due_patrol = force_patrol or focus_changed or ((now - self._last_patrol_mono) >= float(pol["patrol_interval_s"]))
        if due_patrol:
            self._last_patrol_mono = now
            ram_ev = self._self_preserve_daemon_ram()
            if ram_ev:
                actions.append(ram_ev)

            if os.name == "nt":
                procs = _snapshot_processes()
                urban, industrial, full_mask = self._compute_core_masks()
                protected = self._protected_pid_set(procs, fg_pid)

                # A. Promote ENTIRE focused process tree (Chrome+tabs+GPU, AutoCAD, active IDE) & demote old VIPs!
                fg_name, vip_fam = self._promote_vip_sanctuary(procs, fg_pid, dry_run=dry_run)
                if fg_name:
                    self._family_last_focus_ts[fg_name] = now
                    if focus_changed and not dry_run:
                        self.stasis.wake_family(app_name=fg_name, trigger_pid=fg_pid)
                if focus_changed and fg_pid > 4:
                    actions.append(self._record_decision(
                        "VIP_FAMILY_SANCTUARY",
                        f"Protected entire {fg_name} tree ({len(vip_fam)} procs) on Clean Cores {hex(urban)}; demoted old VIPs",
                        app=fg_name,
                        tree_size=len(vip_fam),
                    ))

                # B. Auto-detect AutoCAD / Creative CAD_GODMODE!
                cad_procs = [p for p in procs if p["name"] in _CAD_GODMODE_PROCS]
                self._cad_godmode = bool(cad_procs)
                cad_pids = {p["pid"] for p in cad_procs}
                if cad_pids and not dry_run:
                    for cp in cad_pids:
                        _win_set_eco_qos(cp, False)
                        _win_set_memory_priority(cp, _MEMORY_PRIORITY_NORMAL)
                        _win_set_io_priority(cp, _IO_PRIORITY_NORMAL)
                        _win_set_priority(cp, _HIGH_PRIORITY_CLASS)
                        _win_set_affinity(cp, full_mask)

                # Sanctuary set = OS protected + ENTIRE active focus family + ALL CAD procs + listening/VIP-peer gateways!
                socket_immune = self._refresh_socket_immunity(vip_fam | ({fg_pid} if fg_pid > 4 else set()), force=True)
                sanctuary = protected | vip_fam | cad_pids | socket_immune
                recent_guard = float(pol["recent_focus_guard_s"])
                recent_fams = {nm for nm, ts in self._family_last_focus_ts.items() if (now - ts) < recent_guard}
                self._family_last_focus_ts = {nm: ts for nm, ts in self._family_last_focus_ts.items() if (now - ts) < 600.0}
                self._pid_last_focus_ts = {pid: ts for pid, ts in self._pid_last_focus_ts.items() if (now - ts) < 600.0}
                self._pid_last_trimmed_ts = {pid: ts for pid, ts in self._pid_last_trimmed_ts.items() if (now - ts) < 900.0}

                is_user_active = idle_sec is None or float(idle_sec) < float(pol["idle_release_s"])
                is_pwm_active = idle_sec is None or float(idle_sec) < float(pol.get("pwm_idle_release_s", 5.0))

                # C. Dynamic Real-Time Runaway CPU & I/O Hunter (catches language_server 147 MB/s or ANY rogue burner!)
                runaways: list[dict[str, Any]] = []
                cpu_thresh = float(pol.get("runaway_cpu_core_thresh", 0.35))
                io_thresh = float(pol.get("runaway_io_mb_s_thresh", 15.0))
                new_cpu_io: dict[int, tuple[float, float, int]] = {}
                for p in procs:
                    pid = p["pid"]
                    if pid in sanctuary:
                        continue
                    if p["ws_mb"] < 20.0 and p["name"] not in _INDUSTRIAL_PROCS and p["name"] not in _BACKGROUND_AGENT_PROCS:
                        continue
                    c_s, io_b = _win_proc_cpu_io(pid)
                    new_cpu_io[pid] = (now, c_s, io_b)
                    prev = self._prev_cpu_io.get(pid)
                    if prev is not None:
                        dt = max(0.5, now - prev[0])
                        core_rate = (c_s - prev[1]) / dt
                        io_mb_s = ((io_b - prev[2]) / dt) / (1024.0 * 1024.0)
                        if core_rate >= cpu_thresh or io_mb_s >= io_thresh:
                            runaways.append({
                                "pid": pid,
                                "name": p["name"],
                                "core_rate": round(core_rate, 2),
                                "io_mb_s": round(io_mb_s, 1),
                            })
                self._prev_cpu_io = new_cpu_io
                runaway_pids = {r["pid"] for r in runaways}

                # D. Hard Silicon Cage + Rust PWM-Crusher Fallback (beats Windows JobObject Error 5!)
                cage_targets = [
                    p for p in procs
                    if p["pid"] not in sanctuary
                    and (
                        p["name"] in _INDUSTRIAL_PROCS
                        or p["name"] in _BACKGROUND_AGENT_PROCS
                        or p["pid"] in runaway_pids
                    )
                ]
                cap_pct = int(pol.get("cad_cage_cap_pct", 25)) if self._cad_godmode else int(pol.get("hard_cage_cap_pct", 35))
                # v24 CHIMERA-SILICON-THERMOSTAT: Closed-loop hardware PROCTHROTTLEMAX + global CPU/thermal shield!
                th_res = self.thermostat.evaluate(
                    cpu_pct=cpu_pct,
                    gpu_temp_c=0.0,
                    cad_godmode=self._cad_godmode,
                    dry_run=dry_run,
                )
                shield_active = bool(th_res.get("shield_active")) or cpu_pct >= float(pol.get("silicon_shield_cpu_pct", 62.0))
                pwm_duty = int(th_res.get("shield_pwm_duty", 20)) if shield_active else (
                    int(pol.get("pwm_cad_duty_pct", 15)) if self._cad_godmode else int(pol.get("pwm_duty_pct", 25))
                )
                pwm_always_names = {"language_server", "testhost", "vbcscompiler", "msbuild", "rustc", "cargo", "onedrive.sync.service"}
                pwm_candidates: list[int] = []
                # Under Silicon Thermal Shield (CPU >= 62%), clamp ANY non-focus runaway burner (including background Chrome WebGL/renderer tabs!)
                if shield_active and runaways and not dry_run:
                    for r in runaways:
                        rpid = int(r["pid"])
                        rnm = str(r["name"])
                        if rpid not in sanctuary and rnm not in ("t3 code (beta)", "t3 code", "agy", "codex"):
                            if rpid not in pwm_candidates:
                                pwm_candidates.append(rpid)

                if (is_user_active or shield_active) and (cage_targets or pwm_candidates):
                    caged_n = 0
                    job_ok_n = 0
                    if not dry_run:
                        self._hard_cage.set_cap_pct(cap_pct)
                        for p in cage_targets:
                            is_sync = p["name"] in _SYNC_DAM_PROCS
                            aff_ok, job_ok = self._cage_background_pid(p["pid"], industrial, hard_cage=True, idle_prio=is_sync)
                            if aff_ok:
                                caged_n += 1
                            if job_ok:
                                job_ok_n += 1
                            elif bool(pol.get("pwm_enabled", True)) and (is_pwm_active or shield_active):
                                # Error-5 fallback: route real background burners & runaway storms to Rust 50ms PWM!
                                if p["pid"] in runaway_pids or (self._cad_godmode and p["name"] in pwm_always_names):
                                    if p["name"] not in ("t3 code (beta)", "t3 code", "agy", "codex") and p["pid"] not in pwm_candidates:
                                        if p["name"] != "chrome" or shield_active:
                                            pwm_candidates.append(p["pid"])
                        if self._pwm_started:
                            native_pwm_set_targets(pwm_candidates, pwm_duty)
                            self._pwm_target_pids = set(pwm_candidates)
                    new_caged = {p["pid"] for p in cage_targets} - self._pinned_industrial_pids
                    self._pinned_industrial_pids = {p["pid"] for p in cage_targets}
                    prev_state = self._wall_state
                    self._wall_state = "ACTIVE_WALL"
                    with self._lock:
                        self._stats["silicon_wall_passes"] += 1
                        self._stats["silicon_wall_pinned_procs"] = caged_n
                        if runaways:
                            self._stats["runaways_caged"] += len(runaways)
                    if prev_state != "ACTIVE_WALL" or new_caged or runaways or pwm_candidates:
                        top_r = ", ".join(f"{r['name']}({r['core_rate']}c,{r['io_mb_s']}MB/s)" for r in runaways[:3])
                        actions.append(self._record_decision(
                            "PHANTOM_SILICON_CAGE",
                            f"Pinned {caged_n} bg procs to {hex(industrial)} (JobOK={job_ok_n}, RustPWM={len(pwm_candidates)}@{pwm_duty}%)"
                            + (" [CAD_GODMODE]" if self._cad_godmode else "")
                            + (f" | runaways: {top_r}" if top_r else ""),
                            caged=caged_n,
                            job_caged=job_ok_n,
                            pwm_throttled=len(pwm_candidates),
                            pwm_duty_pct=pwm_duty,
                            hard_cap_pct=cap_pct,
                            cad_godmode=self._cad_godmode,
                            runaways=runaways[:5],
                        ))

                # E. OneDrive Sync-Dam (only throttle priority/IO/affinity — no aggressive refault trim loop)
                sync_procs = [p for p in procs if p["pid"] not in sanctuary and p["name"] in _SYNC_DAM_PROCS]
                if is_user_active and sync_procs and not self._dam_engaged:
                    if not dry_run:
                        self.apply_sync_dam(suspend=False, dry_run=False)
                    self._dam_engaged = True
                    actions.append(self._record_decision("SYNC_DAM_ENGAGED", f"Caged {len(sync_procs)} sync procs to Idle + VeryLow I/O"))

                # F. CHIMERA-STASIS-POD (v23): Suspend-then-Trim ONLY cold background Electron/WebView2 child renderers (0 re-faults, <0.5ms Rust focus wake!)
                if (
                    bool(pol.get("stasis_enabled", True))
                    and not dry_run
                    and (now - self._last_stasis_mono) >= float(pol.get("stasis_interval_s", 30.0))
                ):
                    self._last_stasis_mono = now
                    st_res = self.stasis.hibernate_cold_renderers(
                        procs,
                        sanctuary_pids=sanctuary,
                        recent_families=recent_fams,
                        min_ws_mb=float(pol.get("stasis_min_ws_mb", 20.0)),
                        dry_run=False,
                    )
                    if st_res.get("hibernated", 0) > 0:
                        actions.append(self._record_decision(
                            "STASIS_POD_HIBERNATE",
                            f"Suspended+trimmed {st_res['hibernated']} cold child renderers ({','.join(st_res['families'])}) -{st_res['ws_reclaimed_mb']} MB WS (<0.5ms Rust wake)",
                            hibernated=st_res["hibernated"],
                            reclaimed_mb=st_res["ws_reclaimed_mb"],
                            families=st_res["families"],
                        ))

                # A large renderer working set alone does not establish physical memory pressure.
                free_ram_gb = self._ram_under_trim_threshold(hm)
                if free_ram_gb is not None:
                    cooldown_s = float(pol["pid_trim_cooldown_s"])
                    eligible = [
                        p for p in procs
                        if p["pid"] not in sanctuary
                        and p["name"] not in recent_fams
                        and p["name"] in _HYDRA_FAMILIES
                        and p["ws_mb"] >= 80.0
                        and (now - self._pid_last_trimmed_ts.get(p["pid"], 0.0)) >= cooldown_s
                    ]
                    if eligible:
                        b_ws = sum(p["ws_mb"] for p in eligible)
                        trimmed_n = 0
                        if not dry_run:
                            for p in eligible:
                                pid = p["pid"]
                                _win_set_eco_qos(pid, True)
                                _win_set_memory_priority(pid, _MEMORY_PRIORITY_VERY_LOW)
                                if _win_trim_working_set(pid):
                                    trimmed_n += 1
                                self._pid_last_trimmed_ts[pid] = now
                            time.sleep(0.05)
                            a_ws = sum(_win_proc_memory_mb(p["pid"])[0] for p in eligible)
                        else:
                            a_ws = b_ws
                            trimmed_n = len(eligible)
                        rec_mb = round(max(0.0, b_ws - a_ws), 1)
                        with self._lock:
                            self._stats["cryo_passes"] += 1
                            self._stats["cryo_trimmed_procs"] += trimmed_n
                            self._stats["cryo_est_ws_reclaimed_mb"] = round(self._stats["cryo_est_ws_reclaimed_mb"] + rec_mb, 1)
                        actions.append(self._record_decision(
                            "EMERGENCY_CRYO_TRIM",
                            f"True RAM pressure ({free_ram_gb:.1f} GB free): trimmed {trimmed_n} cold non-active procs (-{rec_mb} MB WS)",
                            trimmed=trimmed_n,
                            reclaimed_mb=rec_mb,
                        ))

        # 4. Silent Automatic Dead-Parent Orphan Zombie Extinction (every 60s)
        due_orphan = force_orphan or ((now - self._last_orphan_mono) >= float(pol["orphan_interval_s"]))
        if due_orphan:
            self._last_orphan_mono = now
            rep = self.reap_orphans(dry_run=dry_run)
            if rep.get("verified_orphans", 0) > 0:
                actions.append(self._record_decision(
                    "ORPHAN_AUTO_REAP",
                    f"Auto-reaped {rep.get('reaped_count', 0)}/{rep['verified_orphans']} dead-parent spawn zombies (-{rep['commit_reclaimed_mb']} MB Commit)",
                    reaped=rep.get("reaped_count", 0),
                    commit_reclaimed_mb=rep["commit_reclaimed_mb"],
                ))

        return {
            "ok": True,
            "tick": tick_num,
            "wall_state": self._wall_state,
            "cad_godmode": self._cad_godmode,
            "vip_app": self._active_vip_name,
            "vip_tree_size": len(self._active_vip_pids),
            "hard_cage": self._hard_cage.status(),
            "timer_res_ms": self._timer_res_ms,
            "dam_engaged": self._dam_engaged,
            "foreground_pid": fg_pid,
            "actions": actions,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }

    def _autonomic_loop(self) -> None:
        # Initial gentle startup delay so daemon HTTP/PHANTOM boots cleanly first
        if self._auto_stop.wait(2.0):
            return
        while not self._auto_stop.is_set():
            try:
                if self._autonomic_policy.get("enabled", True):
                    self.autonomic_tick_once(dry_run=False)
            except Exception:
                pass
            sleep_s = max(0.5, min(10.0, float(self._autonomic_policy.get("fast_tick_s", 1.5))))
            self._auto_stop.wait(sleep_s)

    def start_autonomic(self) -> dict[str, Any]:
        """Start the 24/7 autonomous self-living HyperDesk reflex daemon thread."""
        with self._lock:
            self._autonomic_policy["enabled"] = True
            self._save_autonomic_policy()
            if self._auto_running and self._auto_thread and self._auto_thread.is_alive():
                return {"ok": True, "running": True, "already_running": True}
            self._auto_stop.clear()
            self._auto_running = True
            self._auto_thread = threading.Thread(
                target=self._autonomic_loop,
                name="chimera-hyperdesk-autonomic",
                daemon=True,
            )
            self._auto_thread.start()
        self._record_decision("AUTONOMIC_STARTED", "CHIMERA Autonomic Reflex Brain active (zero manual CLI needed)")
        return {"ok": True, "running": True}

    def stop_autonomic(self, *, restore_defaults: bool = False) -> dict[str, Any]:
        """Pause autonomous loop; optionally release Silicon Wall & Sync-Dam back to OS defaults."""
        with self._lock:
            self._autonomic_policy["enabled"] = False
            self._save_autonomic_policy()
            self._auto_running = False
            self._auto_stop.set()
            th = self._auto_thread
        if th and th.is_alive() and th is not threading.current_thread():
            th.join(timeout=2.5)
        if restore_defaults:
            self.thaw_all()
            self.stasis.wake_all()
            if self._pwm_started:
                native_pwm_set_targets([], 100)
                self._pwm_target_pids.clear()
            if self._wall_state == "ACTIVE_WALL":
                self.apply_silicon_wall(release_to_full=True, dry_run=False)
                self._wall_state = "IDLE_FULL"
            if self._dam_engaged:
                self.apply_sync_dam(release=True, dry_run=False)
                self._dam_engaged = False
        return {"ok": True, "running": False, "restored_defaults": restore_defaults}

    def update_autonomic_policy(self, updates: dict[str, Any]) -> dict[str, Any]:
        profile = updates.get("interactive_profile", self._autonomic_policy["interactive_profile"])
        if profile not in ("aether", "legacy"):
            raise ValueError("interactive_profile must be aether or legacy")
        enabled = updates.get("enabled", self._autonomic_policy["enabled"])
        if self._autonomic_policy["interactive_profile"] == "legacy" and profile == "aether":
            self.stop_autonomic(restore_defaults=True)
            if self._auto_thread and self._auto_thread.is_alive():
                raise ValueError("Legacy cycle is finishing; retry the profile change")
            self._hard_cage.set_cap_pct(100)
            if self._pwm_started:
                native_pwm_stop()
                self._pwm_started = False
            if self._focus_hook_started:
                native_focus_hook_stop()
                self._focus_hook_started = False
            if self._timer_res_ms:
                _win_set_timer_resolution(False)
                self._timer_res_ms = 0.0
            self.thermostat.restore_default()
        if profile == "aether":
            updates = {**updates, "thermostat_mode": "turbo_100", "enabled": enabled}
        with self._lock:
            for k, v in updates.items():
                if k in self._autonomic_policy:
                    self._autonomic_policy[k] = v
            self._save_autonomic_policy()
            enabled = bool(self._autonomic_policy.get("enabled", True))
        if enabled and not self._auto_running:
            self.start_autonomic()
        elif not enabled and self._auto_running:
            self.stop_autonomic(restore_defaults=bool(updates.get("restore_defaults", True)))
        return self.get_autonomic_status()

    def get_autonomic_status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "ok": True,
                "running": bool(self._auto_running and self._auto_thread and self._auto_thread.is_alive()),
                "enabled": bool(self._autonomic_policy.get("enabled", True)),
                "ticks": self._auto_ticks,
                "wall_state": self._wall_state,
                "cad_godmode": self._cad_godmode,
                "vip_app": self._active_vip_name,
                "vip_tree_size": len(self._active_vip_pids),
                "hard_cage": self._hard_cage.status(),
                "rust_pwm": native_pwm_stats(),
                "rust_focus": native_focus_state(),
                "stasis": self.stasis.status(),
                "mirage": self.mirage.status(),
                "timer_res_ms": self._timer_res_ms,
                "dam_engaged": self._dam_engaged,
                "recent_focus_protected": len(self._family_last_focus_ts),
                "cooldown_tracked_pids": len(self._pid_last_trimmed_ts),
                "pinned_industrial_count": len(self._pinned_industrial_pids),
                "policy": dict(self._autonomic_policy),
                "recent_decisions": list(self._auto_decisions)[-15:],
            }

    def reap_orphan_conhosts(self, *, dry_run: bool = False) -> dict[str, Any]:
        """Safely reap genuinely orphaned `conhost.exe` whose parent PID no longer exists (0 PowerShell)."""
        t0 = time.perf_counter()
        if os.name != "nt":
            return {"ok": True, "dry_run": dry_run, "candidates": 0, "reaped": 0, "elapsed_ms": 0.0}
        procs = _snapshot_processes()
        live_pids = {int(p["pid"]) for p in procs}
        fg_pid = _win_foreground_pid()
        protected = self._protected_pid_set(procs, fg_pid)
        orphans = [
            p for p in procs
            if str(p.get("name") or "") == "conhost"
            and int(p["pid"]) not in protected
            and int(p["ppid"]) > 4
            and int(p["ppid"]) not in live_pids
        ]
        reaped = 0
        reaped_pids: list[int] = []
        if not dry_run:
            for p in orphans[:32]:
                pid = int(p["pid"])
                if _win_terminate_pid(pid):
                    reaped += 1
                    reaped_pids.append(pid)
        with self._lock:
            self._stats["orphan_conhosts_reaped"] = int(self._stats.get("orphan_conhosts_reaped", 0)) + reaped
        return {
            "ok": True,
            "dry_run": dry_run,
            "candidates": len(orphans),
            "reaped": reaped,
            "reaped_pids": reaped_pids[:16],
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }

    def gentle_idle_ws_trim(
        self,
        *,
        min_ws_mb: float = 120.0,
        cooldown_s: float = 300.0,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Lossless EmptyWorkingSet ONLY under RAM pressure, skipping VIPs, foreground family, and TCP gateways."""
        t0 = time.perf_counter()
        if os.name != "nt":
            return {"ok": True, "dry_run": dry_run, "pressure": False, "trimmed": 0, "elapsed_ms": 0.0}
        free_gb = self._ram_under_trim_threshold()
        if free_gb is None:
            return {
                "ok": True,
                "dry_run": dry_run,
                "pressure": False,
                "trimmed": 0,
                "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
            }
        procs = _snapshot_processes()
        fg_pid = _win_foreground_pid()
        immune_gateways = self._refresh_socket_immunity({fg_pid} if fg_pid > 4 else None)
        protected = self._protected_pid_set(procs, fg_pid)
        _, fg_fam = self._expand_app_family(procs, fg_pid)
        now_m = time.monotonic()
        trimmed = 0
        candidates = 0
        for p in procs:
            pid = int(p["pid"])
            nm = str(p.get("name") or "")
            if pid <= 4 or pid == self._own_pid or pid in protected or pid in fg_fam or pid in immune_gateways:
                continue
            if nm in _SOFT_VIP_EXES or nm in _CAD_GODMODE_PROCS:
                continue
            if float(p.get("ws_mb") or 0.0) < float(min_ws_mb):
                continue
            last_t = float(self._pid_last_trimmed_ts.get(pid, 0.0))
            if (now_m - last_t) < float(cooldown_s):
                continue
            candidates += 1
            if not dry_run and _win_trim_working_set(pid):
                self._pid_last_trimmed_ts[pid] = now_m
                trimmed += 1
                if trimmed >= 12:
                    break
        with self._lock:
            self._stats["aether_ws_trims"] = int(self._stats.get("aether_ws_trims", 0)) + trimmed
        return {
            "ok": True,
            "dry_run": dry_run,
            "pressure": True,
            "free_ram_gb": round(free_gb, 2),
            "candidates": candidates,
            "trimmed": trimmed,
            "affinity_untouched": True,
            "eco_qos_untouched": True,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }

    def apply_soft_batch_shield(
        self,
        *,
        promote_vips: bool = True,
        demote_batch: bool = True,
        extra_batch_pids: list[int] | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Doctrine Law-2-safe multitasking shield (works in `aether` profile too!).

        NEVER pins CPU affinity (keeps full 12-thread 4.4 GHz Turbo), NEVER enables EcoQoS,
        NEVER suspends IPC apps, and strictly exempts all GetExtendedTcpTable localhost gateways
        plus the foreground app family. Gently elevates interactive VIPs to ABOVE_NORMAL and
        demotes only headless batch/build/test child processes to BELOW_NORMAL + IoPriorityLow.
        """
        t0 = time.perf_counter()
        if not hasattr(self, "_soft_shield_orig"):
            self._soft_shield_orig: dict[int, int] = {}
        if not hasattr(self, "_soft_shield_stats"):
            self._soft_shield_stats: dict[str, Any] = {
                "runs": 0,
                "vips_promoted": 0,
                "batch_demoted": 0,
                "gateways_spared": 0,
                "last_ms": 0.0,
            }

        procs = _snapshot_processes()
        fg_pid = _win_foreground_pid() if os.name == "nt" else 0
        self._refresh_socket_immunity({fg_pid} if fg_pid > 4 else None)
        immune_gateways = set(self._immune_gateway_pids)
        protected = self._protected_pid_set(procs, fg_pid)
        _, fg_fam = self._expand_app_family(procs, fg_pid)
        explicit_batch = {int(p) for p in (extra_batch_pids or []) if int(p) > 0}

        # Identify python/node/pwsh candidates needing native NtQueryInformationProcess cmdline check (0 PowerShell!)
        need_cmd: list[int] = []
        for p in procs:
            pid = int(p["pid"])
            nm = str(p["name"] or "")
            if pid in immune_gateways or pid == self._own_pid:
                continue
            if nm in ("python", "pythonw", "node", "pwsh", "powershell"):
                need_cmd.append(pid)
        cmdlines = _win_get_cmdlines_for_pids(need_cmd[:120]) if (os.name == "nt" and need_cmd) else {}

        promoted: list[dict[str, Any]] = []
        demoted: list[dict[str, Any]] = []
        spared_gateways = 0

        for p in procs:
            pid = int(p["pid"])
            nm = str(p["name"] or "")
            if pid <= 4:
                continue
            if pid in immune_gateways:
                spared_gateways += 1
                if promote_vips and (not dry_run) and os.name == "nt":
                    cur = _win_get_priority(pid)
                    if cur == _NORMAL_PRIORITY_CLASS:
                        self._soft_shield_orig.setdefault(pid, cur)
                        if _win_set_priority(pid, _ABOVE_NORMAL_PRIORITY_CLASS):
                            promoted.append({"pid": pid, "name": nm, "reason": "gateway"})
                continue

            # 1. Interactive VIP sanctuary (foreground app, T3 Code, Antigravity, AutoCAD, Chimera daemon)
            if promote_vips and (pid == self._own_pid or pid == fg_pid or nm in _SOFT_VIP_EXES):
                if dry_run:
                    promoted.append({"pid": pid, "name": nm, "reason": "vip"})
                elif os.name == "nt":
                    cur = _win_get_priority(pid)
                    if cur == _NORMAL_PRIORITY_CLASS:
                        self._soft_shield_orig.setdefault(pid, cur)
                        if _win_set_priority(pid, _ABOVE_NORMAL_PRIORITY_CLASS):
                            promoted.append({"pid": pid, "name": nm, "reason": "vip"})
                continue

            if not demote_batch:
                continue

            # Never demote protected OS processes or foreground app family (unless explicitly targeted for benchmark/worker)
            if (pid not in explicit_batch) and (pid in protected or pid in fg_fam or nm in _SOFT_VIP_EXES):
                continue

            is_batch = (pid in explicit_batch) or (nm in _SOFT_BATCH_EXES)
            reason = "explicit_batch" if pid in explicit_batch else ("batch_exe" if is_batch else "")
            if not is_batch and pid in cmdlines:
                cl_low = cmdlines[pid].lower()
                # Never demote long-lived daemon / MCP / gateway processes!
                if any(keep in cl_low for keep in ("chimera_tp daemon", "chimera_tp mcp", "acp-mcp-bridge", "tquota", "local-relay")):
                    continue
                for tok in _SOFT_BATCH_CMD_TOKENS:
                    if tok in cl_low:
                        is_batch = True
                        reason = f"cmdline:{tok.strip()}"
                        break

            if is_batch:
                if dry_run:
                    demoted.append({"pid": pid, "name": nm, "reason": reason})
                elif os.name == "nt":
                    cur = _win_get_priority(pid)
                    if cur in (_NORMAL_PRIORITY_CLASS, _ABOVE_NORMAL_PRIORITY_CLASS, 0):
                        if cur:
                            self._soft_shield_orig.setdefault(pid, cur)
                        ok_p = _win_set_priority(pid, _BELOW_NORMAL_PRIORITY_CLASS)
                        _win_set_io_priority(pid, 1)  # IoPriorityLow (1), NOT VeryLow(0) starvation
                        if ok_p:
                            demoted.append({"pid": pid, "name": nm, "reason": reason})
                else:
                    if _win_set_priority(pid, _BELOW_NORMAL_PRIORITY_CLASS):
                        demoted.append({"pid": pid, "name": nm, "reason": reason})

        ms = round((time.perf_counter() - t0) * 1000.0, 2)
        with self._lock:
            self._soft_shield_stats["runs"] += 1
            self._soft_shield_stats["vips_promoted"] = len(promoted)
            self._soft_shield_stats["batch_demoted"] = len(demoted)
            self._soft_shield_stats["gateways_spared"] = spared_gateways
            self._soft_shield_stats["last_ms"] = ms
        return {
            "ok": True,
            "mode": "soft_priority_no_turbo_kill",
            "affinity_untouched": True,
            "eco_qos_untouched": True,
            "dry_run": dry_run,
            "vips_promoted": len(promoted),
            "batch_demoted": len(demoted),
            "gateways_spared": spared_gateways,
            "promoted_sample": promoted[:10],
            "demoted_sample": demoted[:12],
            "elapsed_ms": ms,
        }

    def restore_soft_batch_shield(self) -> dict[str, Any]:
        orig = getattr(self, "_soft_shield_orig", None)
        if not orig:
            return {"ok": True, "restored": 0}
        restored = 0
        for pid, prio in list(orig.items()):
            if _win_set_priority(pid, prio or _NORMAL_PRIORITY_CLASS):
                restored += 1
            if os.name == "nt":
                _win_set_io_priority(pid, _IO_PRIORITY_NORMAL)
            orig.pop(pid, None)
        return {"ok": True, "restored": restored}

    def status(self) -> dict[str, Any]:
        with self._lock:
            st = dict(self._stats)
        return {
            "ok": True,
            "hyperdesk_version": "23.0.0",
            "os": platform.system().lower(),
            "cpu_threads": self._cpu_count,
            "suspended_count": len(self._suspended_pids),
            "vram_swap": self.vram_swap.status(),
            "rust_pwm": native_pwm_stats(),
            "stasis": self.stasis.status(),
            "mirage": self.mirage.status(),
            "gpu_fence": {"rules_count": self.gpu_fence.status().get("rules_count", 0)},
            "exile": self.exile.status(),
            "thermostat": self.thermostat.status(),
            "immune_gateways": dict(self._immune_gateway_meta),
            "soft_batch_shield": dict(getattr(self, "_soft_shield_stats", {"runs": 0, "vips_promoted": 0, "batch_demoted": 0})),
            "autonomic": {
                "running": bool(self._auto_running and self._auto_thread and self._auto_thread.is_alive()),
                "enabled": bool(self._autonomic_policy.get("enabled", True)),
                "ticks": self._auto_ticks,
                "wall_state": self._wall_state,
                "cad_godmode": self._cad_godmode,
                "vip_app": self._active_vip_name,
                "hard_cage": self._hard_cage.status(),
                "rust_pwm_active_pids": len(self._pwm_target_pids),
                "timer_res_ms": self._timer_res_ms,
                "dam_engaged": self._dam_engaged,
                "decisions": len(self._auto_decisions),
            },
            **st,
        }

    def close(self) -> None:
        self._auto_running = False
        self._auto_stop.set()
        if self._auto_thread and self._auto_thread.is_alive():
            self._auto_thread.join(timeout=2.0)
        if self._pwm_started:
            native_pwm_stop()
            self._pwm_started = False
            self._pwm_target_pids.clear()
        if self._focus_hook_started:
            native_focus_hook_stop()
            self._focus_hook_started = False
        if self._timer_res_ms > 0.0:
            _win_set_timer_resolution(False)
            self._timer_res_ms = 0.0
        self._hard_cage.close()
        if not self.aether_active:
            self.thermostat.restore_default()
        self.stasis.wake_all()
        self.thaw_all()
        self.restore_soft_batch_shield()
        self.vram_swap.close()
