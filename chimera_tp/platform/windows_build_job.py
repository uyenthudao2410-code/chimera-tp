"""Own a Windows build process tree before allowing its shell to start."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import subprocess
import sys
import threading
import time

from .build_worker import STREAM_LIMITS, _tail


class _BasicLimits(ctypes.Structure):
    _fields_ = [
        ("process_time", ctypes.c_int64), ("job_time", ctypes.c_int64), ("flags", wintypes.DWORD),
        ("min_working_set", ctypes.c_size_t), ("max_working_set", ctypes.c_size_t),
        ("active_process_limit", wintypes.DWORD), ("affinity", ctypes.c_size_t),
        ("priority", wintypes.DWORD), ("scheduling", wintypes.DWORD),
    ]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [
        ("basic", _BasicLimits), ("io_counters", ctypes.c_uint64 * 6),
        ("process_memory", ctypes.c_size_t), ("job_memory", ctypes.c_size_t),
        ("peak_process_memory", ctypes.c_size_t), ("peak_job_memory", ctypes.c_size_t),
    ]


class _Accounting(ctypes.Structure):
    _fields_ = [
        ("time_counters", ctypes.c_int64 * 4), ("page_faults", wintypes.DWORD),
        ("total_processes", wintypes.DWORD), ("active_processes", wintypes.DWORD),
        ("terminated_processes", wintypes.DWORD),
    ]


def _checked(value):
    if not value:
        raise ctypes.WinError(ctypes.get_last_error())
    return value


class _Job:
    def __init__(self):
        api = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = wintypes.HANDLE
        dword = wintypes.DWORD
        for name, result, args in (
            ("CreateJobObjectW", handle, [ctypes.c_void_p, wintypes.LPCWSTR]),
            ("SetInformationJobObject", wintypes.BOOL, [handle, ctypes.c_int, ctypes.c_void_p, dword]),
            ("QueryInformationJobObject", wintypes.BOOL, [handle, ctypes.c_int, ctypes.c_void_p, dword,
                                                          ctypes.POINTER(dword)]),
            ("OpenProcess", handle, [dword, wintypes.BOOL, dword]),
            ("AssignProcessToJobObject", wintypes.BOOL, [handle, handle]),
            ("TerminateJobObject", wintypes.BOOL, [handle, wintypes.UINT]),
            ("CloseHandle", wintypes.BOOL, [handle]),
        ):
            fn = getattr(api, name)
            fn.argtypes, fn.restype = args, result
        self.api = api
        self.handle = None

    def __enter__(self):
        self.handle = _checked(self.api.CreateJobObjectW(None, None))
        try:
            limits = _ExtendedLimits()
            limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            _checked(self.api.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)))
            return self
        except BaseException:
            self.api.CloseHandle(self.handle)
            raise

    def __exit__(self, *exc):
        self.api.CloseHandle(self.handle)

    def attach(self, pid):
        # PROCESS_SET_QUOTA | PROCESS_TERMINATE are required by AssignProcessToJobObject.
        proc = _checked(self.api.OpenProcess(0x0101, False, pid))
        try:
            _checked(self.api.AssignProcessToJobObject(self.handle, proc))
        finally:
            self.api.CloseHandle(proc)

    def stop_and_drain(self):
        _checked(self.api.TerminateJobObject(self.handle, 124))
        stats = _Accounting()
        deadline = time.monotonic() + 5
        while True:
            _checked(self.api.QueryInformationJobObject(self.handle, 1, ctypes.byref(stats), ctypes.sizeof(stats), None))
            if not stats.active_processes:
                return
            if time.monotonic() >= deadline:
                raise OSError("local_build_process_tree_did_not_exit")
            time.sleep(0.01)


# This isolated interpreter has no workspace code on its import path. An empty
# pipe means the parent exited before assignment. The user's command is only
# sent after the job owns this process, so its earliest child is covered.
_LAUNCHER = """\
import json
import subprocess
import sys

payload = sys.stdin.buffer.read()
if not payload:
    raise SystemExit(125)
shell, command = json.loads(payload)
line = subprocess.list2cmdline([shell]) + ' /d /s /c "' + command + '"'
raise SystemExit(subprocess.call(line, executable=shell, stdin=subprocess.DEVNULL))
"""


def run(command, where, timeout, env, shell):
    tails = ["", ""]
    timed_out = False
    with _Job() as job:
        proc = subprocess.Popen([sys.executable, "-I", "-B", "-S", "-c", _LAUNCHER],
                                cwd=where, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW)
        attached = False
        readers = []
        try:
            job.attach(proc.pid)
            attached = True
            for i, (stream, limit) in enumerate(zip((proc.stdout, proc.stderr), STREAM_LIMITS)):
                reader = threading.Thread(target=_tail, args=(stream, limit, tails, i), daemon=True)
                reader.start()
                readers.append(reader)
            proc.stdin.write(json.dumps([str(shell), command], ensure_ascii=True).encode("ascii"))
            proc.stdin.close()
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
        finally:
            try:
                if attached:
                    job.stop_and_drain()
                else:
                    proc.kill()
            finally:
                if not proc.stdin.closed:
                    proc.stdin.close()
                proc.wait(timeout=5)
                for reader in readers:
                    reader.join(timeout=3)
                if any(reader.is_alive() for reader in readers):
                    raise OSError("local_build_output_did_not_close")
                proc.stdout.close()
                proc.stderr.close()
    result = {"ok": not timed_out and proc.returncode == 0, "exit_code": proc.returncode,
              "stdout": tails[0], "stderr": tails[1]}
    if timed_out:
        result["error"] = "timeout"
    return result
