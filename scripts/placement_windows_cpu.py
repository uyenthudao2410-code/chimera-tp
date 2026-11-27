"""Record Windows CPU for the complete set of local descendants of one placement trial."""

from __future__ import annotations

import ctypes
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from chimera_tp.platform.windows_build_job import _Accounting, _Job, _checked


# The child waits on the pipe. It cannot start the clients or compiler before
# Windows places it in the accounting job. Descendants inherit that job, even
# when a local shared compiler is also in its own job for lifetime management.
LAUNCH = """import json, subprocess, sys
payload = sys.stdin.buffer.read()
if not payload:
    raise SystemExit(125)
raise SystemExit(subprocess.run(json.loads(payload), stdin=subprocess.DEVNULL).returncode)
"""


def measure(arguments):
    if sys.platform != "win32" or not arguments or arguments[0] not in {"local", "local-shared", "remote"}:
        raise ValueError("expected a Windows placement trial and arguments for cad_swarm_job.py")
    command = [sys.executable, "-B", str(ROOT / "scripts/cad_swarm_job.py"), *arguments]
    accounting = _Accounting()
    with _Job() as job:
        with subprocess.Popen(
            [sys.executable, "-I", "-B", "-S", "-c", LAUNCH],
            cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW,
        ) as child:
            attached = False
            try:
                job.attach(child.pid)
                attached = True
                out, error = child.communicate(json.dumps(command).encode("ascii"), timeout=220)
            finally:
                if attached:
                    job.stop_and_drain()
                else:
                    child.kill()
                child.wait(timeout=5)
        _checked(job.api.QueryInformationJobObject(job.handle, 1, ctypes.byref(accounting),
                                                   ctypes.sizeof(accounting), None))
    if child.returncode:
        raise RuntimeError(error.decode("utf-8", "replace")[-1800:])
    if accounting.active_processes != 0 or accounting.total_processes < 3:
        raise RuntimeError("incomplete Windows process tree at the end of the trial")
    record = json.loads(out)
    ticks = 10_000_000
    user, kernel = accounting.time_counters[:2]
    record["windows_process_tree"] = {
        "processes": accounting.total_processes, "active_at_close": accounting.active_processes,
        "user_cpu_s": user / ticks, "kernel_cpu_s": kernel / ticks, "total_cpu_s": (user + kernel) / ticks,
    }
    return record


if __name__ == "__main__":
    print(json.dumps(measure(sys.argv[1:]), ensure_ascii=True))
