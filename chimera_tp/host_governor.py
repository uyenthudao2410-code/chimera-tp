"""HostYieldGovernor — protects Windows workstation interactivity while allowing Sovereign 24/7 autonomy on svhome."""

from __future__ import annotations

import ctypes
from datetime import datetime, timezone
import os
import sys
import threading
import time
from typing import Any


class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]


class _MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


class _FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", ctypes.c_ulong), ("dwHighDateTime", ctypes.c_ulong)]


def _ft_int(ft: _FILETIME) -> int:
    return (int(ft.dwHighDateTime) << 32) | int(ft.dwLowDateTime)


VALID_POLICIES = ("work_first", "shared_pool", "sovereign_only", "turbo_force")


class HostYieldGovernor:
    """Monitors user input idle, CPU load, and free RAM with <5ms Instant Preempt checks."""

    def __init__(self, *, role: str = "controller", policy: str = "work_first") -> None:
        self.role = str(role or "controller").lower()
        self._policy = policy if policy in VALID_POLICIES else "work_first"
        self._lock = threading.Lock()
        self._last_sys_times: tuple[int, int, int] | None = None
        self._last_cpu_pct: float = 0.0
        self._preempt_count: int = 0
        self._last_state: dict[str, Any] | None = None

    def get_policy(self) -> str:
        with self._lock:
            return self._policy

    def set_policy(self, policy: str) -> str:
        clean = str(policy or "").strip().lower()
        if clean not in VALID_POLICIES:
            raise ValueError(f"Unsupported governor policy {policy!r}; expected one of {VALID_POLICIES}")
        with self._lock:
            self._policy = clean
        return clean

    def get_idle_seconds(self) -> float | None:
        if sys.platform != "win32" or self.role != "controller":
            return None
        try:
            lii = _LASTINPUTINFO()
            lii.cbSize = ctypes.sizeof(_LASTINPUTINFO)
            if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii)):
                return None
            tick_now = int(ctypes.windll.kernel32.GetTickCount64()) & 0xFFFFFFFF
            elapsed_ms = (tick_now - int(lii.dwTime)) & 0xFFFFFFFF
            return round(elapsed_ms / 1000.0, 2)
        except Exception:
            return None

    def _read_win_cpu_pct(self) -> float:
        try:
            idle, kernel, user = _FILETIME(), _FILETIME(), _FILETIME()
            if not ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
                return self._last_cpu_pct
            cur = (_ft_int(idle), _ft_int(kernel), _ft_int(user))
            with self._lock:
                prev = self._last_sys_times
                self._last_sys_times = cur
                if prev is None:
                    return self._last_cpu_pct
                di = cur[0] - prev[0]
                dk = cur[1] - prev[1]
                du = cur[2] - prev[2]
                tot = max(1, dk + du)
                pct = max(0.0, min(100.0, (1.0 - (di / float(tot))) * 100.0))
                self._last_cpu_pct = round(pct, 1)
                return self._last_cpu_pct
        except Exception:
            return self._last_cpu_pct

    def get_host_metrics(self) -> dict[str, Any]:
        idle_sec = self.get_idle_seconds()
        free_gb = 8.0
        total_gb = 16.0
        cpu_pct = 0.0
        if sys.platform == "win32":
            try:
                mem = _MEMORYSTATUSEX()
                mem.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
                if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(mem)):
                    free_gb = round(mem.ullAvailPhys / (1024.0 ** 3), 2)
                    total_gb = round(mem.ullTotalPhys / (1024.0 ** 3), 2)
            except Exception:
                pass
            cpu_pct = self._read_win_cpu_pct()
        else:
            try:
                with open("/proc/meminfo", "r", encoding="utf-8") as fh:
                    info = {}
                    for ln in fh:
                        parts = ln.split(":", 1)
                        if len(parts) == 2:
                            val = parts[1].strip().split()[0]
                            if val.isdigit():
                                info[parts[0]] = int(val)
                if "MemAvailable" in info and "MemTotal" in info:
                    free_gb = round(info["MemAvailable"] / (1024.0 * 1024.0), 2)
                    total_gb = round(info["MemTotal"] / (1024.0 * 1024.0), 2)
            except Exception:
                pass
            try:
                cpus = max(1, os.cpu_count() or 1)
                load1 = os.getloadavg()[0]
                cpu_pct = round(min(100.0, (load1 / float(cpus)) * 100.0), 1)
            except Exception:
                pass
        return {
            "idle_sec": idle_sec,
            "cpu_pct": cpu_pct,
            "free_ram_gb": free_gb,
            "total_ram_gb": total_gb,
        }

    def evaluate_state(self, override_metrics: dict[str, Any] | None = None) -> dict[str, Any]:
        metrics = dict(self.get_host_metrics())
        if override_metrics:
            metrics.update({k: v for k, v in override_metrics.items() if v is not None})

        policy = self.get_policy()
        idle_sec = metrics.get("idle_sec")
        cpu_pct = float(metrics.get("cpu_pct") or 0.0)
        free_gb = float(metrics.get("free_ram_gb") or 0.0)
        total_gb = float(metrics.get("total_ram_gb") or 0.0)

        reason = "sovereign_autonomous_24x7"
        if self.role != "controller":
            mode = "SOVEREIGN_LOCAL"
            accept_heavy = False
            preempt = False
        elif policy == "sovereign_only":
            mode = "SOVEREIGN_LOCAL"
            accept_heavy = False
            preempt = True
            reason = "policy_sovereign_only"
        elif policy == "turbo_force":
            mode = "TURBO_IDLE"
            accept_heavy = True
            preempt = False
            reason = "policy_turbo_force"
        else:
            active_input = idle_sec is not None and float(idle_sec) < 300.0
            high_cpu = cpu_pct > 35.0
            low_ram = free_gb < 6.0
            idle_ready = (idle_sec is None or float(idle_sec) >= 300.0) and cpu_pct < 15.0 and free_gb >= 8.0
            if active_input or high_cpu or low_ram:
                mode = "USER_ACTIVE"
                accept_heavy = False
                preempt = True
                reason = "input_active" if active_input else ("cpu_busy" if high_cpu else "low_free_ram")
            elif idle_ready:
                mode = "TURBO_IDLE"
                accept_heavy = True
                preempt = False
                reason = "workstation_idle_turbo_ready"
            else:
                if policy == "work_first":
                    mode = "USER_ACTIVE"
                    accept_heavy = False
                    preempt = True
                    reason = "work_first_guard"
                else:
                    mode = "TURBO_IDLE"
                    accept_heavy = True
                    preempt = False
                    reason = "shared_pool_headroom"

        state = {
            "ok": True,
            "role": self.role,
            "mode": mode,
            "policy": policy,
            "accept_heavy_jobs": accept_heavy,
            "preempt_yield": preempt,
            "reason": reason,
            "idle_sec": idle_sec,
            "cpu_pct": round(cpu_pct, 1),
            "free_ram_gb": round(free_gb, 2),
            "total_ram_gb": round(total_gb, 2),
            "preempt_count": self._preempt_count,
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
        }
        with self._lock:
            self._last_state = state
        return state

    def check_preempt(self, override_metrics: dict[str, Any] | None = None) -> dict[str, Any]:
        t0 = time.perf_counter()
        st = self.evaluate_state(override_metrics=override_metrics)
        if st["preempt_yield"]:
            with self._lock:
                self._preempt_count += 1
                st["preempt_count"] = self._preempt_count
        return {
            "ok": True,
            "preempt": bool(st["preempt_yield"]),
            "mode": st["mode"],
            "accept_heavy_jobs": bool(st["accept_heavy_jobs"]),
            "reason": st["reason"],
            "check_ms": round((time.perf_counter() - t0) * 1000.0, 3),
        }
