"""Execute verified Windows build inputs locally with cross-process result sharing."""

from __future__ import annotations

from importlib.resources import files
import os
from pathlib import Path
import platform
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid

from . import build_snapshot as snapshots
from .build_registry import execute_once
from .build_worker import PROTOCOL, _artifacts
from .windows_build_job import run


def _toolchain(env):
    # Use the system shell regardless of PATH and the temporary working directory.
    shell = (Path(env["SYSTEMROOT"]) / "System32" / "cmd.exe").resolve(strict=True)
    python = Path(sys.executable).resolve(strict=True)

    def identity(path):
        stat = path.stat()
        return {"path": str(path), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}

    info = {"host": platform.node(), "machine": platform.machine(), "os": platform.platform(),
            "python": sys.version, "interpreter": identity(python), "shell": identity(shell)}
    return shell, info


def run_snapshot(command, source, *, names, environment_id, reuse, timeout_s, state_dir, wait_s):
    env = dict(os.environ)
    shell, toolchain = _toolchain(env)
    registry = Path(state_dir or Path.home() / ".chimera" / "guarded-builds") / "local-actions"
    runner = files(__package__)
    relevant = ("build_snapshot.py", "build_worker.py", "local_build.py", "windows_build_job.py")
    version = {name: snapshots.sha(runner.joinpath(name).read_bytes()) for name in relevant}
    # Preserve Windows tool environments (PATH, INCLUDE, LIB, SDK, virtualenv,
    # locale, etc.). Only a digest of their contents enters the persisted key.
    key = snapshots.sha(snapshots.canonical([
        "windows-build", PROTOCOL, version, toolchain, str(Path.home()), source["scope"], source["digest"],
        command, names, float(timeout_s), environment_id, snapshots.sha(snapshots.canonical(env)),
    ]))

    def perform():
        begin = time.monotonic()
        receipt = {"protocol": PROTOCOL, "target": "local", "snapshot": source["digest"], "key": key,
                   "state": "failed", "ok": False, "attempt_id": uuid.uuid4().hex, "toolchain": toolchain}
        try:
            with tempfile.TemporaryDirectory(prefix="chimera-local-build-") as tmp:
                where = snapshots.materialize(source["wire"], source["digest"], Path(tmp).resolve())
                result = run(command, where, timeout_s, env, shell)
                if result["ok"]:
                    result["artifacts"] = _artifacts(where, names)
            receipt.update(result)
            if receipt["ok"]:
                receipt["state"] = "completed"
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            receipt["error"] = str(exc)
        receipt["elapsed_ms"] = round((time.monotonic() - begin) * 1000, 2)
        return receipt

    if not reuse:
        return {**perform(), "delivery": "executed"}
    try:
        receipt, delivery = execute_once(registry, key, perform, persist=True, wait_s=timeout_s + wait_s + 30)
    except sqlite3.DatabaseError as exc:
        return {"protocol": PROTOCOL, "ok": False, "state": "indeterminate", "target": "local",
                "error": f"local_result_registry:{exc}", "key": key, "delivery": "unknown"}
    return {**receipt, "target": "local", "protocol": PROTOCOL, "delivery": delivery}
