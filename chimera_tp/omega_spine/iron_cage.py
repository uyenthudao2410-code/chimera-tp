"""CHIMERA Omega-Spine: Kernel Iron Cage + Singleflight Command Deduplicator.

Provides zero-conhost, CPU/QoS-governed subprocess execution and process-level
isolation so heavy agent builds/tests never starve interactive UI/DWM/T3/Tquota
threads, plus cross-agent singleflight coalescing & TTL caching (< 2 ms hits).

100% Python stdlib; graceful no-op fallbacks on permission errors or non-Windows.
"""

from __future__ import annotations

import collections
import copy
import ctypes
from ctypes import wintypes
import hashlib
import os
import shlex
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable


_IS_WIN = os.name == "nt"
_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) if _IS_WIN else 0

# Win32 constants
_PROCESS_TERMINATE = 0x0001
_PROCESS_SET_QUOTA = 0x0100
_PROCESS_SET_INFORMATION = 0x0200
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
_ABOVE_NORMAL_PRIORITY_CLASS = 0x00008000
_NORMAL_PRIORITY_CLASS = 0x00000020

_PROCESS_POWER_THROTTLING_CURRENT_VERSION = 1
_PROCESS_POWER_THROTTLING_EXECUTION_SPEED = 0x1
_PROCESS_INFORMATION_POWER_THROTTLING = 4

_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
_JOB_OBJECT_CPU_RATE_CONTROL_INFORMATION = 15
_JOB_OBJECT_CPU_RATE_CONTROL_ENABLE = 0x1
_JOB_OBJECT_CPU_RATE_CONTROL_HARD_CAP = 0x4

_TH32CS_SNAPPROCESS = 0x00000002
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

_ROYAL_UI_NAMES = frozenset({
    "dwm.exe",
    "explorer.exe",
    "csrss.exe",
    "winlogon.exe",
    "t3.exe",
    "tquota.exe",
    "antigravity.exe",
    "code.exe",
    "electron.exe",
    "cursor.exe",
    "chrome.exe",
    "msedge.exe",
    "firefox.exe",
    "windowsterminal.exe",
})

_DEFAULT_WORKER_TARGETS = (
    "dotnet.exe",
    "msbuild.exe",
    "vbcscompiler.exe",
    "csc.exe",
    "cargo.exe",
    "rustc.exe",
    "cl.exe",
    "link.exe",
    "pytest.exe",
    "mypy.exe",
    "ruff.exe",
)


if _IS_WIN:
    class _ProcessPowerThrottlingState(ctypes.Structure):
        _fields_ = [
            ("Version", wintypes.DWORD),
            ("ControlMask", wintypes.DWORD),
            ("StateMask", wintypes.DWORD),
        ]

    class _JobBasicLimitInfo(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _JobExtendedLimitInfo(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _JobBasicLimitInfo),
            ("IoInfo", ctypes.c_uint64 * 6),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    class _JobCpuRateControlInfo(ctypes.Structure):
        _fields_ = [
            ("ControlFlags", wintypes.DWORD),
            ("CpuRate", wintypes.DWORD),
        ]

    class _ProcessEntry32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]


def _load_kernel32() -> Any:
    if not _IS_WIN:
        return None
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = wintypes.HANDLE
    dword = wintypes.DWORD
    sigs = (
        ("OpenProcess", handle, [dword, wintypes.BOOL, dword]),
        ("CloseHandle", wintypes.BOOL, [handle]),
        ("SetPriorityClass", wintypes.BOOL, [handle, dword]),
        ("SetProcessAffinityMask", wintypes.BOOL, [handle, ctypes.c_size_t]),
        ("SetProcessInformation", wintypes.BOOL, [handle, ctypes.c_int, ctypes.c_void_p, dword]),
        ("CreateJobObjectW", handle, [ctypes.c_void_p, wintypes.LPCWSTR]),
        ("SetInformationJobObject", wintypes.BOOL, [handle, ctypes.c_int, ctypes.c_void_p, dword]),
        ("AssignProcessToJobObject", wintypes.BOOL, [handle, handle]),
        ("TerminateJobObject", wintypes.BOOL, [handle, wintypes.UINT]),
        ("CreateToolhelp32Snapshot", handle, [dword, dword]),
        ("Process32FirstW", wintypes.BOOL, [handle, ctypes.POINTER(_ProcessEntry32W)]),
        ("Process32NextW", wintypes.BOOL, [handle, ctypes.POINTER(_ProcessEntry32W)]),
        ("GetExitCodeProcess", wintypes.BOOL, [handle, ctypes.POINTER(dword)]),
    )
    for fn_name, restype, argtypes in sigs:
        fn = getattr(api, fn_name, None)
        if fn is not None:
            fn.restype = restype
            fn.argtypes = argtypes
    return api


_KERNEL32 = _load_kernel32()


def compute_worker_affinity_mask(cpu_count: int | None = None) -> int | None:
    """Return bitmask pinning background build workers away from UI cores.

    When cpu_count >= 6, reserves Cores 0..1 exclusively for UI/DWM/T3/Tquota
    by returning cores 2..N-1. Returns None on small hosts (< 4 cores).
    """
    n = int(cpu_count if cpu_count is not None else (os.cpu_count() or 1))
    n = min(n, 64)
    if n >= 6:
        return ((1 << n) - 1) & ~0x3
    if n >= 4:
        return ((1 << n) - 1) & ~0x1
    return None


def compute_workspace_fingerprint(cwd: str | Path, extra_files: list[str] | None = None) -> str:
    """O(1) stat-based workspace fingerprint (< 1 ms, 0 subprocess spawns)."""
    root = Path(cwd)
    h = hashlib.blake2s(digest_size=10)
    try:
        resolved = root.resolve()
    except OSError:
        resolved = root
    h.update(str(resolved).lower().encode("utf-8", errors="replace"))
    try:
        st = resolved.stat()
        h.update(f"|dir:{st.st_mtime_ns}:{st.st_size}".encode("ascii"))
    except OSError:
        pass

    git_dir = resolved / ".git"
    if git_dir.is_file():
        try:
            raw = git_dir.read_text(encoding="utf-8", errors="ignore").strip()
            if raw.lower().startswith("gitdir:"):
                gd = Path(raw.split(":", 1)[1].strip())
                git_dir = gd if gd.is_absolute() else (resolved / gd)
        except OSError:
            pass
    if git_dir.is_dir():
        head_p = git_dir / "HEAD"
        try:
            head_txt = head_p.read_text(encoding="utf-8", errors="ignore").strip()
            h.update(f"|head:{head_txt}".encode("utf-8", errors="replace"))
            if head_txt.startswith("ref:"):
                ref_rel = head_txt.split(":", 1)[1].strip()
                ref_p = git_dir / ref_rel
                if ref_p.is_file():
                    h.update(f"|ref:{ref_p.read_text(encoding='utf-8', errors='ignore').strip()}".encode("utf-8"))
        except OSError:
            pass
        idx_p = git_dir / "index"
        try:
            ist = idx_p.stat()
            h.update(f"|idx:{ist.st_mtime_ns}:{ist.st_size}".encode("ascii"))
        except OSError:
            pass

    if extra_files:
        for rf in sorted(set(extra_files))[:32]:
            fp = Path(rf) if Path(rf).is_absolute() else (resolved / rf)
            try:
                fst = fp.stat()
                h.update(f"|f:{rf}:{fst.st_mtime_ns}:{fst.st_size}".encode("utf-8", errors="replace"))
            except OSError:
                h.update(f"|f:{rf}:missing".encode("utf-8", errors="replace"))
    return h.hexdigest()


class _InFlight:
    __slots__ = ("event", "result", "error")

    def __init__(self) -> None:
        self.event = threading.Event()
        self.result: Any = None
        self.error: BaseException | None = None


class SingleflightCommandCache:
    """Coalesces identical concurrent runs and caches rapid repeats (< 2 ms hit)."""

    def __init__(self, ttl_s: float = 3.0, max_entries: int = 64) -> None:
        self.ttl_s = max(0.05, float(ttl_s))
        self.max_entries = max(4, int(max_entries))
        self._lock = threading.Lock()
        self._cache: collections.OrderedDict[str, tuple[float, Any]] = collections.OrderedDict()
        self._inflight: dict[str, _InFlight] = {}
        self._stats = {
            "cache_hits": 0,
            "coalesced_hits": 0,
            "misses": 0,
            "evictions": 0,
        }

    @staticmethod
    def make_key(cwd: str | Path, cmd: str | list[str] | tuple[str, ...], fp: str = "") -> str:
        norm_cwd = str(Path(cwd)).replace("\\", "/").lower()
        if isinstance(cmd, (list, tuple)):
            norm_cmd = "\x00".join(str(x) for x in cmd)
        else:
            norm_cmd = str(cmd)
        raw = f"{norm_cwd}\x1f{norm_cmd}\x1f{fp}".encode("utf-8", errors="replace")
        return hashlib.blake2s(raw, digest_size=16).hexdigest()

    def get(self, key: str) -> Any | None:
        now = time.monotonic()
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            ts, val = entry
            if (now - ts) > self.ttl_s:
                self._cache.pop(key, None)
                return None
            self._cache.move_to_end(key)
            self._stats["cache_hits"] += 1
            return copy.deepcopy(val)

    def put(self, key: str, value: Any) -> None:
        now = time.monotonic()
        with self._lock:
            self._cache[key] = (now, copy.deepcopy(value))
            self._cache.move_to_end(key)
            while len(self._cache) > self.max_entries:
                self._cache.popitem(last=False)
                self._stats["evictions"] += 1

    def invalidate(self, key: str | None = None) -> None:
        with self._lock:
            if key is None:
                self._cache.clear()
            else:
                self._cache.pop(key, None)

    def run_or_join(self, key: str, fn: Callable[[], Any], *, bypass_cache: bool = False) -> tuple[Any, str]:
        """Execute `fn` once for `key`, coalescing concurrent callers and caching result.

        Returns `(result, mode)` where `mode` is `"ttl_cache"`, `"coalesced"`, or `"executed"`.
        """
        now = time.monotonic()
        flight: _InFlight | None = None
        is_owner = False

        with self._lock:
            if not bypass_cache:
                entry = self._cache.get(key)
                if entry is not None:
                    ts, val = entry
                    if (now - ts) <= self.ttl_s:
                        self._cache.move_to_end(key)
                        self._stats["cache_hits"] += 1
                        return copy.deepcopy(val), "ttl_cache"
                    self._cache.pop(key, None)

            existing = self._inflight.get(key)
            if existing is not None:
                flight = existing
            else:
                flight = _InFlight()
                self._inflight[key] = flight
                self._stats["misses"] += 1
                is_owner = True

        if not is_owner:
            flight.event.wait()
            if flight.error is not None:
                raise flight.error
            with self._lock:
                self._stats["coalesced_hits"] += 1
            return copy.deepcopy(flight.result), "coalesced"

        try:
            res = fn()
            flight.result = res
            self.put(key, res)
            return copy.deepcopy(res), "executed"
        except BaseException as exc:
            flight.error = exc
            raise
        finally:
            with self._lock:
                self._inflight.pop(key, None)
            flight.event.set()

    def stats(self) -> dict[str, Any]:
        now = time.monotonic()
        with self._lock:
            expired = [k for k, (ts, _) in self._cache.items() if (now - ts) > self.ttl_s]
            for k in expired:
                self._cache.pop(k, None)
            hits = int(self._stats["cache_hits"])
            coal = int(self._stats["coalesced_hits"])
            return {
                "ttl_s": self.ttl_s,
                "max_entries": self.max_entries,
                "entries": len(self._cache),
                "inflight": len(self._inflight),
                "cache_hits": hits,
                "coalesced_hits": coal,
                "total_hits": hits + coal,
                "misses": int(self._stats["misses"]),
                "evictions": int(self._stats["evictions"]),
            }


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if _IS_WIN and _KERNEL32 is not None:
        h = _KERNEL32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not h:
            return False
        try:
            code = wintypes.DWORD(0)
            ok = _KERNEL32.GetExitCodeProcess(h, ctypes.byref(code))
            return bool(ok and code.value == 259)  # STILL_ACTIVE
        finally:
            _KERNEL32.CloseHandle(h)
    try:
        os.kill(int(pid), 0)
        return True
    except OSError:
        return False


def _create_cpu_rate_job(cpu_rate_pct: int, *, kill_on_close: bool = False) -> Any:
    """Create a Win32 Job Object with hard CPU rate cap (and optional kill-on-close)."""
    if not _IS_WIN or _KERNEL32 is None:
        return None
    pct = max(5, min(100, int(cpu_rate_pct)))
    job = _KERNEL32.CreateJobObjectW(None, None)
    if not job:
        return None
    try:
        if kill_on_close:
            ext = _JobExtendedLimitInfo()
            ext.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            _KERNEL32.SetInformationJobObject(
                job,
                _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
                ctypes.byref(ext),
                ctypes.sizeof(ext),
            )
        if pct < 100:
            rate = _JobCpuRateControlInfo()
            rate.ControlFlags = _JOB_OBJECT_CPU_RATE_CONTROL_ENABLE | _JOB_OBJECT_CPU_RATE_CONTROL_HARD_CAP
            rate.CpuRate = pct * 100  # Win32 expects 1..10000 (percentage * 100)
            _KERNEL32.SetInformationJobObject(
                job,
                _JOB_OBJECT_CPU_RATE_CONTROL_INFORMATION,
                ctypes.byref(rate),
                ctypes.sizeof(rate),
            )
        return job
    except Exception:
        try:
            _KERNEL32.CloseHandle(job)
        except Exception:
            pass
        return None


class IronCage:
    """OS-level Kernel Iron Cage + Singleflight Deduplicator."""

    def __init__(self, *, singleflight_ttl_s: float = 3.0, singleflight_max_entries: int = 64) -> None:
        self._lock = threading.Lock()
        self.singleflight = SingleflightCommandCache(ttl_s=singleflight_ttl_s, max_entries=singleflight_max_entries)
        self._shared_jobs: dict[int, Any] = {}
        self._caged: dict[int, dict[str, Any]] = {}
        self._royal_pids: set[int] = set()
        self._caged_total: int = 0
        self._conhost_avoided: int = 0
        self._last_sweep_at: float = 0.0
        self._sweep_count: int = 0

    def _get_shared_job(self, cpu_rate_pct: int) -> Any:
        if not _IS_WIN or _KERNEL32 is None:
            return None
        bucket = max(10, min(100, int(cpu_rate_pct)))
        with self._lock:
            job = self._shared_jobs.get(bucket)
            if job:
                return job
        new_job = _create_cpu_rate_job(bucket, kill_on_close=False)
        if not new_job:
            return None
        with self._lock:
            existing = self._shared_jobs.get(bucket)
            if existing:
                try:
                    _KERNEL32.CloseHandle(new_job)
                except Exception:
                    pass
                return existing
            self._shared_jobs[bucket] = new_job
            return new_job

    def apply_royal_ui_tier(self, pids: list[int] | set[int] | tuple[int, ...] | None = None) -> dict[str, Any]:
        """Protect interactive UI/DWM/T3/Tquota processes with Above-Normal priority & full core mask."""
        target_pids = [int(p) for p in (pids or []) if int(p) > 0]
        applied: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        ncpu = min(os.cpu_count() or 1, 64)
        full_mask = (1 << ncpu) - 1

        for pid in target_pids:
            if _IS_WIN and _KERNEL32 is not None:
                h = _KERNEL32.OpenProcess(
                    _PROCESS_SET_INFORMATION | _PROCESS_QUERY_LIMITED_INFORMATION,
                    False,
                    pid,
                )
                if not h:
                    errors.append({"pid": pid, "error": f"open_failed:{ctypes.get_last_error()}"})
                    continue
                try:
                    prio_ok = bool(_KERNEL32.SetPriorityClass(h, _ABOVE_NORMAL_PRIORITY_CLASS))
                    aff_ok = bool(_KERNEL32.SetProcessAffinityMask(h, ctypes.c_size_t(full_mask)))
                    eco = _ProcessPowerThrottlingState(
                        Version=_PROCESS_POWER_THROTTLING_CURRENT_VERSION,
                        ControlMask=_PROCESS_POWER_THROTTLING_EXECUTION_SPEED,
                        StateMask=0,  # Disable EcoQoS for interactive UI
                    )
                    eco_ok = bool(
                        _KERNEL32.SetProcessInformation(
                            h,
                            _PROCESS_INFORMATION_POWER_THROTTLING,
                            ctypes.byref(eco),
                            ctypes.sizeof(eco),
                        )
                    )
                    applied.append({
                        "pid": pid,
                        "priority_above_normal": prio_ok,
                        "affinity_full": aff_ok,
                        "eco_qos_disabled": eco_ok,
                    })
                    with self._lock:
                        self._royal_pids.add(pid)
                finally:
                    _KERNEL32.CloseHandle(h)
            else:
                try:
                    if hasattr(os, "sched_setaffinity"):
                        os.sched_setaffinity(pid, set(range(ncpu)))
                    applied.append({"pid": pid, "posix_affinity_full": True})
                    with self._lock:
                        self._royal_pids.add(pid)
                except OSError as exc:
                    errors.append({"pid": pid, "error": str(exc)})

        return {
            "ok": True,
            "platform": os.name,
            "requested": len(target_pids),
            "applied": applied,
            "errors": errors,
        }

    def cage_worker_pid(
        self,
        pid: int,
        max_cores_mask: int | None = None,
        cpu_rate_pct: int = 75,
        *,
        job_handle: Any = None,
        attach_job: bool = True,
    ) -> dict[str, Any]:
        """Cage a worker PID: Below-Normal priority, core affinity (2..N-1), EcoQoS & CPU rate Job."""
        pid = int(pid)
        if pid <= 0:
            return {"ok": False, "pid": pid, "error": "invalid_pid"}

        mask = max_cores_mask if max_cores_mask is not None else compute_worker_affinity_mask()
        res: dict[str, Any] = {
            "ok": False,
            "pid": pid,
            "platform": os.name,
            "cpu_rate_pct": int(cpu_rate_pct),
            "affinity_mask": mask,
            "priority_applied": False,
            "affinity_applied": False,
            "eco_qos_applied": False,
            "job_attached": False,
            "fallback_noop": False,
        }

        if _IS_WIN and _KERNEL32 is not None:
            access = (
                _PROCESS_SET_INFORMATION
                | _PROCESS_SET_QUOTA
                | _PROCESS_TERMINATE
                | _PROCESS_QUERY_LIMITED_INFORMATION
            )
            h = _KERNEL32.OpenProcess(access, False, pid)
            if not h:
                h = _KERNEL32.OpenProcess(_PROCESS_SET_INFORMATION | _PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not h:
                res["fallback_noop"] = True
                res["error"] = f"open_process_denied:{ctypes.get_last_error()}"
                return res
            try:
                res["priority_applied"] = bool(_KERNEL32.SetPriorityClass(h, _BELOW_NORMAL_PRIORITY_CLASS))
                if mask is not None and mask > 0:
                    res["affinity_applied"] = bool(_KERNEL32.SetProcessAffinityMask(h, ctypes.c_size_t(mask)))
                eco = _ProcessPowerThrottlingState(
                    Version=_PROCESS_POWER_THROTTLING_CURRENT_VERSION,
                    ControlMask=_PROCESS_POWER_THROTTLING_EXECUTION_SPEED,
                    StateMask=_PROCESS_POWER_THROTTLING_EXECUTION_SPEED,
                )
                res["eco_qos_applied"] = bool(
                    _KERNEL32.SetProcessInformation(
                        h,
                        _PROCESS_INFORMATION_POWER_THROTTLING,
                        ctypes.byref(eco),
                        ctypes.sizeof(eco),
                    )
                )
                if attach_job:
                    jh = job_handle if job_handle else self._get_shared_job(cpu_rate_pct)
                    if jh:
                        res["job_attached"] = bool(_KERNEL32.AssignProcessToJobObject(jh, h))
                res["ok"] = bool(
                    res["priority_applied"]
                    or res["affinity_applied"]
                    or res["eco_qos_applied"]
                    or res["job_attached"]
                )
            finally:
                _KERNEL32.CloseHandle(h)
        else:
            # Linux / POSIX graceful iron-cage via nice + sched_setaffinity
            try:
                if hasattr(os, "setpriority") and hasattr(os, "PRIO_PROCESS"):
                    os.setpriority(os.PRIO_PROCESS, pid, 10)
                    res["priority_applied"] = True
            except OSError:
                pass
            if mask is not None and hasattr(os, "sched_setaffinity"):
                try:
                    cores = {i for i in range(64) if (mask >> i) & 1}
                    if cores:
                        os.sched_setaffinity(pid, cores)
                        res["affinity_applied"] = True
                except OSError:
                    pass
            res["ok"] = bool(res["priority_applied"] or res["affinity_applied"])
            if not res["ok"]:
                res["fallback_noop"] = True

        if res["ok"]:
            with self._lock:
                self._caged[pid] = {
                    "pid": pid,
                    "affinity_mask": mask,
                    "cpu_rate_pct": int(cpu_rate_pct),
                    "job_attached": res["job_attached"],
                    "caged_at": round(time.time(), 3),
                }
                self._caged_total += 1
                if len(self._caged) > 256:
                    oldest = min(self._caged.items(), key=lambda kv: kv[1].get("caged_at", 0.0))[0]
                    self._caged.pop(oldest, None)
        return res

    def spawn_caged(
        self,
        cmd: str | list[str] | tuple[str, ...],
        cwd: str | Path | None = None,
        timeout_s: float = 60.0,
        *,
        env: dict[str, str] | None = None,
        cpu_rate_pct: int = 75,
        max_cores_mask: int | None = None,
        use_singleflight: bool = False,
        singleflight_cache: SingleflightCommandCache | None = None,
        fingerprint: str | None = None,
        bypass_cache: bool = False,
    ) -> dict[str, Any]:
        """Spawn subprocess with 0 conhost (Windows) or nice/taskset (Linux) inside Iron Cage."""
        work_dir = Path(cwd) if cwd is not None else Path.cwd()

        if use_singleflight:
            sf = singleflight_cache or self.singleflight
            fp = fingerprint if fingerprint is not None else compute_workspace_fingerprint(work_dir)
            key = sf.make_key(work_dir, cmd, fp)
            t_sf = time.perf_counter()
            res, mode = sf.run_or_join(
                key,
                lambda: self._spawn_caged_direct(
                    cmd,
                    work_dir,
                    timeout_s=timeout_s,
                    env=env,
                    cpu_rate_pct=cpu_rate_pct,
                    max_cores_mask=max_cores_mask,
                ),
                bypass_cache=bypass_cache,
            )
            if mode != "executed":
                res["singleflight_hit"] = True
                res["singleflight_mode"] = mode
                res["lookup_ms"] = round((time.perf_counter() - t_sf) * 1000.0, 3)
            else:
                res["singleflight_hit"] = False
                res["singleflight_mode"] = "executed"
            return res

        return self._spawn_caged_direct(
            cmd,
            work_dir,
            timeout_s=timeout_s,
            env=env,
            cpu_rate_pct=cpu_rate_pct,
            max_cores_mask=max_cores_mask,
        )

    def _spawn_caged_direct(
        self,
        cmd: str | list[str] | tuple[str, ...],
        work_dir: Path,
        *,
        timeout_s: float = 60.0,
        env: dict[str, str] | None = None,
        cpu_rate_pct: int = 75,
        max_cores_mask: int | None = None,
    ) -> dict[str, Any]:
        t0 = time.perf_counter()
        use_shell = isinstance(cmd, str)
        popen_cmd: Any = cmd if use_shell else [str(x) for x in cmd]
        kwargs: dict[str, Any] = {
            "cwd": str(work_dir),
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "stdin": subprocess.DEVNULL,
            "env": env,
            "shell": use_shell,
        }
        conhost_avoided = False
        per_spawn_job = None

        if _IS_WIN:
            kwargs["creationflags"] = _CREATE_NO_WINDOW
            conhost_avoided = True
            per_spawn_job = _create_cpu_rate_job(cpu_rate_pct, kill_on_close=True)
        else:
            # On Linux (e.g. svhome), apply nice + taskset where available
            if not use_shell and isinstance(popen_cmd, list):
                prefix: list[str] = []
                mask = max_cores_mask if max_cores_mask is not None else compute_worker_affinity_mask()
                if mask is not None and shutil.which("taskset"):
                    prefix.extend(["taskset", hex(mask)])
                if shutil.which("nice"):
                    prefix.extend(["nice", "-n", "10"])
                if prefix:
                    popen_cmd = prefix + popen_cmd
            else:
                def _posix_preexec() -> None:
                    try:
                        os.nice(10)
                    except OSError:
                        pass
                kwargs["preexec_fn"] = _posix_preexec

        timed_out = False
        stdout_b = b""
        stderr_b = b""
        rc = -1
        pid = 0
        cage_res: dict[str, Any] = {}

        try:
            proc = subprocess.Popen(popen_cmd, **kwargs)
            pid = int(proc.pid)
            if conhost_avoided:
                with self._lock:
                    self._conhost_avoided += 1
            cage_res = self.cage_worker_pid(
                pid,
                max_cores_mask=max_cores_mask,
                cpu_rate_pct=cpu_rate_pct,
                job_handle=per_spawn_job,
                attach_job=True,
            )
            try:
                stdout_b, stderr_b = proc.communicate(timeout=max(0.1, float(timeout_s)))
                rc = int(proc.returncode if proc.returncode is not None else -1)
            except subprocess.TimeoutExpired:
                timed_out = True
                if _IS_WIN and _KERNEL32 is not None and per_spawn_job and cage_res.get("job_attached"):
                    try:
                        _KERNEL32.TerminateJobObject(per_spawn_job, 124)
                    except Exception:
                        pass
                try:
                    proc.kill()
                except Exception:
                    pass
                try:
                    out_p, err_p = proc.communicate(timeout=2.0)
                    stdout_b = out_p or b""
                    stderr_b = err_p or b""
                except Exception:
                    pass
                rc = 124
        except FileNotFoundError as exc:
            stderr_b = str(exc).encode("utf-8", errors="replace")
            rc = 127
        except OSError as exc:
            stderr_b = str(exc).encode("utf-8", errors="replace")
            rc = 126
        finally:
            if _IS_WIN and _KERNEL32 is not None and per_spawn_job:
                try:
                    _KERNEL32.CloseHandle(per_spawn_job)
                except Exception:
                    pass

        elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        return {
            "ok": (rc == 0) and (not timed_out),
            "exit_code": rc,
            "stdout": stdout_b.decode("utf-8", errors="replace"),
            "stderr": stderr_b.decode("utf-8", errors="replace"),
            "timed_out": timed_out,
            "elapsed_ms": elapsed_ms,
            "pid": pid,
            "caged": cage_res,
            "conhost_avoided": conhost_avoided,
            "singleflight_hit": False,
        }

    def cage_sweep_agent_children(
        self,
        target_names: tuple[str, ...] | list[str] | None = None,
        cpu_rate_pct: int = 75,
    ) -> dict[str, Any]:
        """Zero-spawn sweep finding heavy compiler/test children and caging them."""
        targets = {str(x).lower() for x in (target_names or _DEFAULT_WORKER_TARGETS)}
        self_pid = os.getpid()
        scanned = 0
        caged_now: list[dict[str, Any]] = []
        already_caged = 0
        skipped = 0

        if _IS_WIN and _KERNEL32 is not None:
            snap = _KERNEL32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
            if snap and snap != _INVALID_HANDLE_VALUE:
                try:
                    entry = _ProcessEntry32W()
                    entry.dwSize = ctypes.sizeof(_ProcessEntry32W)
                    ok = bool(_KERNEL32.Process32FirstW(snap, ctypes.byref(entry)))
                    while ok:
                        scanned += 1
                        pid = int(entry.th32ProcessID)
                        ppid = int(entry.th32ParentProcessID)
                        exe = str(entry.szExeFile or "").lower()
                        if pid <= 4 or pid == self_pid or exe in _ROYAL_UI_NAMES:
                            skipped += 1
                        elif exe in targets or ppid == self_pid:
                            with self._lock:
                                is_known = pid in self._caged
                            if is_known:
                                already_caged += 1
                            else:
                                cr = self.cage_worker_pid(pid, cpu_rate_pct=cpu_rate_pct)
                                if cr.get("ok"):
                                    caged_now.append({"pid": pid, "exe": exe, "ppid": ppid})
                                else:
                                    skipped += 1
                        ok = bool(_KERNEL32.Process32NextW(snap, ctypes.byref(entry)))
                finally:
                    _KERNEL32.CloseHandle(snap)
        else:
            proc_root = Path("/proc")
            if proc_root.is_dir():
                for child in proc_root.iterdir():
                    if not child.name.isdigit():
                        continue
                    scanned += 1
                    pid = int(child.name)
                    if pid == self_pid:
                        skipped += 1
                        continue
                    try:
                        comm = (child / "comm").read_text(encoding="utf-8", errors="ignore").strip().lower()
                    except OSError:
                        continue
                    if comm in targets or f"{comm}.exe" in targets:
                        with self._lock:
                            is_known = pid in self._caged
                        if is_known:
                            already_caged += 1
                        else:
                            cr = self.cage_worker_pid(pid, cpu_rate_pct=cpu_rate_pct)
                            if cr.get("ok"):
                                caged_now.append({"pid": pid, "exe": comm})

        with self._lock:
            self._last_sweep_at = round(time.time(), 3)
            self._sweep_count += 1

        return {
            "ok": True,
            "platform": os.name,
            "scanned": scanned,
            "caged_now": caged_now,
            "caged_now_count": len(caged_now),
            "already_caged": already_caged,
            "skipped": skipped,
        }

    def status(self) -> dict[str, Any]:
        mask = compute_worker_affinity_mask()
        with self._lock:
            dead = [p for p in list(self._caged.keys()) if not _pid_alive(p)]
            for p in dead:
                self._caged.pop(p, None)
            caged_list = list(self._caged.values())
            royal = sorted(self._royal_pids)
            caged_total = self._caged_total
            conhost_avoided = self._conhost_avoided
            last_sweep_at = self._last_sweep_at
            sweep_count = self._sweep_count

        sf = self.singleflight.stats()
        return {
            "ok": True,
            "platform": os.name,
            "cpu_count": os.cpu_count() or 1,
            "worker_affinity_mask": mask,
            "worker_affinity_hex": hex(mask) if mask is not None else None,
            "caged_pids": [int(c["pid"]) for c in caged_list],
            "caged_entries": caged_list[-32:],
            "caged_count": len(caged_list),
            "caged_total": caged_total,
            "royal_pids": royal,
            "conhost_avoided": conhost_avoided,
            "singleflight": sf,
            "singleflight_hits": sf["total_hits"],
            "sweep_count": sweep_count,
            "last_sweep_at": last_sweep_at,
        }

    def close(self) -> None:
        if _IS_WIN and _KERNEL32 is not None:
            with self._lock:
                jobs = list(self._shared_jobs.values())
                self._shared_jobs.clear()
            for jh in jobs:
                try:
                    _KERNEL32.CloseHandle(jh)
                except Exception:
                    pass


_DEFAULT_CAGE_LOCK = threading.Lock()
_DEFAULT_CAGE: IronCage | None = None


def get_iron_cage() -> IronCage:
    global _DEFAULT_CAGE
    with _DEFAULT_CAGE_LOCK:
        if _DEFAULT_CAGE is None:
            _DEFAULT_CAGE = IronCage()
        return _DEFAULT_CAGE


def apply_royal_ui_tier(pids: list[int] | set[int] | tuple[int, ...] | None = None) -> dict[str, Any]:
    return get_iron_cage().apply_royal_ui_tier(pids)


def cage_worker_pid(pid: int, max_cores_mask: int | None = None, cpu_rate_pct: int = 75) -> dict[str, Any]:
    return get_iron_cage().cage_worker_pid(pid, max_cores_mask=max_cores_mask, cpu_rate_pct=cpu_rate_pct)


def spawn_caged(
    cmd: str | list[str] | tuple[str, ...],
    cwd: str | Path | None = None,
    timeout_s: float = 60.0,
    **kwargs: Any,
) -> dict[str, Any]:
    return get_iron_cage().spawn_caged(cmd, cwd=cwd, timeout_s=timeout_s, **kwargs)


def cage_sweep_agent_children(
    target_names: tuple[str, ...] | list[str] | None = None,
    cpu_rate_pct: int = 75,
) -> dict[str, Any]:
    return get_iron_cage().cage_sweep_agent_children(target_names=target_names, cpu_rate_pct=cpu_rate_pct)


def status() -> dict[str, Any]:
    return get_iron_cage().status()
