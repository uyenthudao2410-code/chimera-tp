"""Receiver for authenticated SSH build requests. Uses a private directory per execution."""

from __future__ import annotations

import base64
import contextlib
import json
import os
from pathlib import Path
import platform
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid

from . import build_snapshot as snapshots
from .build_registry import execute_once


PROTOCOL = 1
ARTIFACT_LIMIT = 4 * 1024 * 1024
STREAM_LIMITS = (12000, 4000)


def guard_policy(require_io_cap, requested=None):
    if requested is not None and not isinstance(requested, dict):
        raise ValueError("invalid_peer_guard_request")
    policy = {**(requested or {}), "disk_path": str(Path.home())}
    if require_io_cap:
        policy["require_io_cap"] = True
    return policy


def _tail(stream, limit, result, slot):
    tail = bytearray()
    with stream:
        for chunk in iter(lambda: stream.read(16384), b""):
            tail.extend(chunk)
            del tail[:-limit]
    result[slot] = tail.decode("utf-8", "replace")


def _run(command, where, timeout, *, env, monitor, repeatable):
    import resource

    from .peer_guard import AdmissionDeferred

    # Capture bounded tails continuously even for verbose builds.
    before_cpu = resource.getrusage(resource.RUSAGE_CHILDREN)
    process_started = time.monotonic()
    vector = ["/bin/sh", "-c", command]
    proc = subprocess.Popen(vector, cwd=where, env=env, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    tails = ["", ""]
    readers = [threading.Thread(target=_tail, args=(s, limit, tails, i), daemon=True)
               for i, (s, limit) in enumerate(zip((proc.stdout, proc.stderr), STREAM_LIMITS))]
    for reader in readers:
        reader.start()
    timeout_hit = False
    guard_trip = None
    samples = 0
    worst_service = {}
    start = time.monotonic()
    deadline = start + timeout
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timeout_hit = True
                break
            try:
                proc.wait(timeout=min(0.5, remaining))
                break
            except subprocess.TimeoutExpired:
                if proc.poll() is not None:
                    break
            try:
                health = monitor()
            except AdmissionDeferred as exc:
                guard_trip = exc.as_dict()
                break
            samples += 1
            for name, duration in health["service_p95_ms"].items():
                worst_service[name] = max(worst_service.get(name, 0), duration)
    finally:
        # Also release descendant processes holding pipes after their driver exits.
        with contextlib.suppress(ProcessLookupError):
            os.killpg(proc.pid, signal.SIGKILL)
        proc.wait()
        for reader in readers:
            reader.join(timeout=2)
    after_cpu = resource.getrusage(resource.RUSAGE_CHILDREN)
    result = {"ok": proc.returncode == 0 and not timeout_hit and not guard_trip,
              "exit_code": proc.returncode, "stdout": tails[0], "stderr": tails[1],
              "process_wall_ms": round((time.monotonic() - process_started) * 1000, 3),
              "reaped_child_cpu_ms": round(1000 * (after_cpu.ru_utime + after_cpu.ru_stime
                                                   - before_cpu.ru_utime - before_cpu.ru_stime), 3),
              "runtime_guard": {"completed_samples": samples, "worst_service_p95_ms": worst_service}}
    if timeout_hit:
        result["error"] = "timeout"
    if guard_trip:
        result.update(state="deferred" if repeatable else "interrupted",
                      retryable=repeatable, error="running_guard_" + guard_trip["reason"],
                      guard_trip=guard_trip)
    return result


def _artifacts(root, names):
    items, total = {}, 0
    for name in names:
        file = root / snapshots.portable_path(name)
        if file.resolve(strict=True) != file or not file.is_file():
            raise ValueError(f"invalid_artifact:{name}")
        with file.open("rb") as stream:
            data = stream.read(ARTIFACT_LIMIT - total + 1)
        total += len(data)
        if total > ARTIFACT_LIMIT:
            raise ValueError("artifact_return_limit")
        items[name] = {"bytes": len(data), "sha256": snapshots.sha(data),
                       "base64": base64.b64encode(data).decode("ascii")}
    return items


def read_request(stream):
    size = int.from_bytes(stream.read(4), "big")
    if not 1 <= size <= 128 * 1024:
        raise ValueError("invalid_request_size")
    request = json.loads(stream.read(size))
    wire_len = request["wire_bytes"]
    if type(wire_len) is not int or not 0 <= wire_len <= snapshots.MAX_WIRE_BYTES:
        raise ValueError("snapshot_wire_limit")
    wire = stream.read(wire_len)
    if len(wire) != wire_len or stream.read(1):
        raise ValueError("invalid_request_frame")
    return request, wire


def coordinate(archive, require_io):
    """Join concurrent senders before asking systemd for the one shared guest unit."""
    from .peer_guard import AdmissionDeferred, DEFAULT_ROOT, launch_policy, limited_command

    request, wire = read_request(sys.stdin.buffer)
    if bool(request.get("require_io_limit")) != require_io:
        raise ValueError("receiver_policy_frame_mismatch")
    timeout = float(request["timeout_s"])
    if not 1 <= timeout <= 300:
        raise ValueError("invalid_build_timeout")
    if snapshots.sha(Path(archive).read_bytes()) != request["worker_version"]:
        raise ValueError("worker_package_digest_mismatch")
    header = snapshots.canonical(request)

    def launch():
        try:
            requested = guard_policy(require_io, request.get("admission_policy"))
            policy = launch_policy(DEFAULT_ROOT, requested)
            if policy["require_io_cap"]:
                from .peer_guard import assess
                decision = assess(requested)
                if not decision["accepted"]:
                    return {"ok": False, "protocol": PROTOCOL, "state": "deferred", "retryable": True,
                            "error": decision["reason"], "admission": decision}
            entry = ("import sys;sys.path.insert(0,sys.argv[1]);"
                     "from chimera_tp.platform.build_worker import main;main()")
            command = limited_command([sys.executable, "-I", "-B", "-S", "-c", entry, str(archive)], policy)
            result = subprocess.run(command, input=len(header).to_bytes(4, "big") + header + wire,
                                    capture_output=True, timeout=timeout + 25)
            if result.returncode == 0:
                return json.loads(result.stdout)
            message = result.stderr.decode("utf-8", "replace").strip()
            busy = "chimera-peer-guest.service" in message and (
                "already exists" in message or "already loaded" in message)
            return {"ok": False, "protocol": PROTOCOL, "state": "deferred" if busy else "indeterminate",
                    "retryable": busy or bool(request.get("reuse")),
                    "error": "guest_slot_busy" if busy else "guest_unit_failed", "detail": message[-480:]}
        except AdmissionDeferred as exc:
            return {"ok": False, "protocol": PROTOCOL, "state": "deferred", "retryable": True,
                    "error": exc.reason, "admission": exc.as_dict()}

    if request.get("reuse"):
        key = snapshots.sha(snapshots.canonical(request))
        registry = Path.home() / ".chimera" / "guarded-builds" / "incoming"
        res, delivery = execute_once(registry, key, launch, persist=False, wait_s=timeout + 30)
        return {**res, "protocol": PROTOCOL, "receiver_delivery": delivery}
    return launch()


def receive(request, wire, *, root=None):
    from .peer_guard import AdmissionDeferred, DEFAULT_ROOT, recheck_running, reserve

    if request.get("protocol") != PROTOCOL:
        raise ValueError("incompatible_build_protocol")
    root = (root or Path.home() / ".chimera" / "guarded-builds").resolve()
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    timeout = float(request["timeout_s"])
    cmd = request["command"]
    if not (1 <= timeout <= 300) or not isinstance(cmd, str) or not cmd.strip() or len(cmd) > 32000:
        raise ValueError("invalid_command_or_timeout")
    paths = request.get("artifacts", [])
    if not isinstance(paths, list) or len(paths) > 32:
        raise ValueError("invalid_artifact_list")
    names = sorted({snapshots.portable_path(p) for p in paths})
    digest, environment_id = request.get("snapshot"), request.get("environment_id")
    reuse = bool(request.get("reuse"))
    if reuse and (not digest or not isinstance(environment_id, str) or not environment_id.strip()):
        raise ValueError("repeatable_build_requires_snapshot_and_environment_id")
    job_env = os.environ.copy()
    agent_version = request["worker_version"]
    target = platform.node()
    executable = Path(sys.executable).resolve()
    interpreter = {"platform": platform.platform(), "machine": platform.machine(),
                   "python": sys.version, "path": str(executable), "stat": executable.stat().st_mtime_ns}
    if reuse:
        # Run repeatable commands with a stable environment. The caller pins other
        # tool/dependency versions and external inputs with environment_id.
        names_to_keep = {"PATH", "HOME", "USER", "LANG", "TZ", "SHELL", "TMPDIR",
                         "VIRTUAL_ENV", "JAVA_HOME", "CARGO_HOME", "RUSTUP_HOME"}
        job_env = {k: v for k, v in job_env.items() if k in names_to_keep or k.startswith("LC_")}
        semantic_env = job_env
    else:
        semantic_env = {}
    key = snapshots.sha(snapshots.canonical([PROTOCOL, agent_version, target, os.getuid(), digest,
                                             request.get("scope"), cmd, interpreter, environment_id,
                                             snapshots.sha(snapshots.canonical(semantic_env)), names,
                                             bool(request.get("require_io_limit")),
                                             request.get("admission_policy", {}), timeout]))
    admitted_at = time.monotonic()

    def perform():
        attempt = uuid.uuid4().hex
        receipt = {"attempt_id": attempt, "target": target, "snapshot": digest, "key": key,
                   "toolchain": interpreter, "state": "failed", "local_windows_cpu_used_pct": None}
        began = time.monotonic()
        last = began
        stage = "admission_ms"
        phases = {}

        def advance(next_stage):
            nonlocal stage, last
            now = time.monotonic()
            phases[stage] = round((now - last) * 1000, 3)
            stage, last = next_stage, now

        try:
            # Policy belongs to the peer. Senders may request a stronger I/O bound.
            policy = guard_policy(request.get("require_io_limit"), request.get("admission_policy"))
            with reserve(DEFAULT_ROOT, policy) as admission:
                advance("workspace_ms")
                with tempfile.TemporaryDirectory(prefix="job-", dir=root) as raw:
                    directory = Path(raw).resolve()
                    if digest:
                        existing = None if request.get("sync_workspace") else Path(request["remote_cwd"])
                        where = snapshots.materialize(wire, digest, directory, existing)
                    else:
                        where = Path(request["remote_cwd"]).resolve(strict=True)
                        if not where.is_dir():
                            raise ValueError("remote_workspace_missing")
                    def monitor():
                        return recheck_running(DEFAULT_ROOT, admission["effective_policy"])

                    advance("command_ms")
                    result = _run(cmd, where, timeout, env=job_env, monitor=monitor, repeatable=reuse)
                    advance("outputs_ms")
                    receipt.update(result, admission=admission, remote_cwd=str(where))
                    if result["ok"]:
                        receipt["artifacts"] = _artifacts(where, names)
                        receipt["state"] = "completed"
                    advance("cleanup_ms")
        except AdmissionDeferred as exc:
            receipt.update(ok=False, state="deferred", retryable=True, error=str(exc),
                           admission=getattr(exc, "details", {}))
        except (ValueError, KeyError, OSError, subprocess.SubprocessError) as exc:
            receipt.update(ok=False, error=str(exc))
        advance(None)
        receipt["attempt_timing_ms"] = {**phases, "total_ms": round((last - began) * 1000, 3)}
        receipt["elapsed_ms"] = round((time.monotonic() - admitted_at) * 1000, 2)
        return receipt

    if reuse:
        result, delivery = execute_once(root / "actions", key, perform, persist=True, wait_s=timeout + 20)
    else:
        result, delivery = perform(), "executed"
    return {**result, "protocol": PROTOCOL, "delivery": delivery}


def main():
    try:
        request, wire = read_request(sys.stdin.buffer)
        result = receive(request, wire)
    except Exception as exc:
        result = {"ok": False, "protocol": PROTOCOL, "state": "failed",
                  "error": f"{type(exc).__name__}: {exc}"}
    print(json.dumps(result, ensure_ascii=True))
