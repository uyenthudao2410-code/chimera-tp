"""Place new, explicit batch jobs without changing the desktop power policy."""

from __future__ import annotations

import ast
import ctypes
import datetime as dt
import json
import math
import os
import re
import shlex
import sqlite3
import subprocess
import time
import tokenize
from contextlib import closing
from pathlib import Path

from ..merkle_sync import DEFAULT_IGNORE_DIRS
from . import peer_guard


def idle_seconds() -> float | None:
    if os.name != "nt":
        return None
    from ctypes import wintypes

    class LastInput(ctypes.Structure):
        _fields_ = [("size", wintypes.UINT), ("tick", wintypes.DWORD)]

    sample = LastInput()
    sample.size = ctypes.sizeof(sample)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(sample)):
        return None
    current = ctypes.windll.kernel32.GetTickCount() & 0xffffffff
    return ((current - sample.tick) & 0xffffffff) / 1000


def gpu_temperature() -> float | None:
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader,nounits"],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            text=True, capture_output=True, check=True, timeout=3)
        return max(float(x) for x in result.stdout.splitlines())
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def cpu_temperature() -> float | None:
    """Use a package/core sensor published by an already running hardware monitor."""
    if os.name != "nt":
        return None
    ps = """
foreach ($ns in 'root/LibreHardwareMonitor','root/OpenHardwareMonitor') {
    $v = Get-CimInstance -Namespace $ns -ClassName Sensor -Filter "SensorType='Temperature'" -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match '^CPU (Package|Core)' -and $_.Value -gt 0 -and $_.Value -lt 150 } |
        Measure-Object -Property Value -Maximum
    if ($null -ne $v.Maximum) { $v.Maximum.ToString([CultureInfo]::InvariantCulture); break }
}
"""
    try:
        r = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps], text=True,
                           creationflags=subprocess.CREATE_NO_WINDOW, capture_output=True, timeout=5)
        return float(r.stdout.strip())
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def _sensors():
    gpu, cpu = gpu_temperature(), cpu_temperature()
    known = [t for t in (gpu, cpu) if t is not None and math.isfinite(t)]
    return gpu, cpu, max(known) if known else None


def observe(db_path: Path, now: float, temperature: float | None) -> dict:
    """Require consecutive samples. A discontinuity invalidates the hot interval."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(db_path, timeout=5)) as db, db:
        db.execute("CREATE TABLE IF NOT EXISTS therm (id INTEGER PRIMARY KEY, last REAL, hot_since REAL)")
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT last,hot_since FROM therm WHERE id=1").fetchone()
        since = None
        if temperature is not None and math.isfinite(temperature) and temperature >= 75:
            if row and row[1] is not None and 0 <= now - row[0] <= 30:
                since = row[1]
            else:
                since = now
        db.execute("INSERT OR REPLACE INTO therm VALUES(1,?,?)", (now, since))
    return {"temp_c": temperature, "continuous_hot_s": now - since if since is not None else 0}


def decide(*, hot_s, temp_c, hour, idle_s, peer_online):
    if hot_s >= 60:
        return ("peer", "sustained_heat") if peer_online else ("defer", "hot_without_peer")
    night = hour >= 22 or hour < 6
    cool = temp_c is not None and math.isfinite(temp_c) and temp_c < 75
    if night and cool and idle_s is not None and idle_s >= 1800:
        return "local", "night_idle"
    return ("peer", "protect_interaction") if peer_online else ("defer", "waiting_for_capacity")


def peer_ssh_route(peer: str) -> tuple[list[str], str]:
    """Prefer a live local forward while retaining the configured OpenSSH host identity."""
    import http.client
    import ipaddress

    if not isinstance(peer, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.@-]{0,200}", peer):
        raise ValueError("invalid_ssh_host")
    options = ["ssh", "-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=4",
               "-o", "StrictHostKeyChecking=yes", "-o", "UpdateHostKeys=no",
               "-o", "ClearAllForwardings=yes"]
    fallback = ([*options, peer], "ssh_alias")
    if os.name != "nt" or peer != "svhome":
        return fallback

    def local_status(path):
        with closing(http.client.HTTPConnection("127.0.0.1", 9780, timeout=0.8)) as connection:
            connection.request("GET", path)
            response = connection.getresponse()
            if response.status != 200:
                raise ValueError("local_status_unavailable")
            data = response.read(65537)
            if len(data) > 65536:
                raise ValueError("local_status_too_large")
            return json.loads(data)

    try:
        state = local_status("/api/phantom/status")["client"]
        if (state["connected"] is not True or state["pong_stale"] is not False
                or state["mode"] != "PHANTOM_5MS_DIRECT"):
            return fallback
        port = state["listeners"]["22"]
        beacon = local_status("/.well-known/chimera.json")
        if type(port) is not int or not 1 <= port <= 65535 or beacon["peer_name"] != peer:
            return fallback
        profile = subprocess.run(["ssh", "-G", peer], check=True, capture_output=True, text=True,
                                 timeout=2, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        config = dict(line.split(" ", 1) for line in profile.stdout.splitlines() if " " in line)
        address = str(ipaddress.ip_address(config["hostname"]))
        if address != beacon["peer_ipv4"] or config.get("port") != "22":
            return fallback
        key_alias = config.get("hostkeyalias", address)
        return ([*options, "-o", "HostName=127.0.0.1", "-o", "HostKeyAlias=" + key_alias,
                 "-p", str(port), peer], "phantom_ssh")
    except (AttributeError, KeyError, OSError, TypeError, ValueError,
            http.client.HTTPException, subprocess.SubprocessError):
        return fallback
_SYNTAX_POLICY = {"job_memory_mib": 256, "job_disk_mib": 16, "runtime_seconds": 110}


def _remote_guard(entry, argv, policy, *, execute, timeout, peer="svhome"):
    source = Path(peer_guard.__file__).read_text(encoding="utf-8") + "\n" + entry
    command = ["python3", "-I", "-B", "-S", "-", json.dumps(policy), *argv]
    if execute:
        command = peer_guard.limited_command(command, policy)
    try:
        ssh, route = peer_ssh_route(peer)
        result = subprocess.run([*ssh, shlex.join(command)], input=source, capture_output=True,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                                text=True, encoding="utf-8", timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"accepted": False, "decision": "defer", "reason": "ssh_timeout",
                "transport_ok": False, "state": "indeterminate" if execute else "deferred"}
    except OSError as exc:
        return {"accepted": False, "decision": "defer", "reason": "ssh_unavailable",
                "transport_ok": False, "detail": type(exc).__name__, "state": "deferred"}
    except ValueError as exc:
        return {"accepted": False, "decision": "defer", "reason": str(exc),
                "transport_ok": False, "state": "deferred"}
    if result.returncode != 0:
        manager_error = result.stderr.lower()
        if (execute and result.returncode != 255 and "chimera-peer-guest.service" in manager_error
                and any(msg in manager_error for msg in ("already loaded", "already exists"))):
            return {"accepted": False, "decision": "defer", "reason": "guest_slot_busy",
                    "transport_ok": True, "state": "deferred"}
        return {"accepted": False, "decision": "defer", "reason": "receiver_command_failed",
                "transport_ok": result.returncode != 255, "exit_code": result.returncode,
                "detail": result.stderr.strip()[-400:], "state": "indeterminate" if execute else "deferred"}
    try:
        payload = json.loads(result.stdout)
        if not isinstance(payload, dict):
            raise ValueError("receiver result is not an object")
    except ValueError:
        return {"accepted": False, "decision": "defer", "reason": "invalid_receiver_response",
                "transport_ok": True, "state": "indeterminate" if execute else "deferred"}
    return {**payload, "transport_ok": True, "ssh_route": route}


def peer_assessment(policy=None, *, peer="svhome"):
    script = "print(json.dumps({**assess(json.loads(sys.argv[1])), 'cpu': os.cpu_count()}))"
    return _remote_guard(script, [], {**_SYNTAX_POLICY, **(policy or {})}, execute=False, timeout=14,
                         peer=peer)


def peer_available() -> bool:
    return peer_assessment().get("accepted") is True


def plan(db: Path, observe_seconds: int = 0, *, policy=None):
    if not 0 <= observe_seconds <= 120:
        raise ValueError("observe between 0 and 120 seconds")
    deadline = time.monotonic() + observe_seconds
    while True:
        gpu, cpu, hottest = _sensors()
        sample = observe(db, time.time(), hottest)
        sample.update(gpu_c=gpu, cpu_c=cpu)
        left = deadline - time.monotonic()
        if left <= 0:
            break
        time.sleep(min(10, left))
    peer = peer_assessment(policy)
    idle, hour = idle_seconds(), dt.datetime.now().hour
    target, reason = decide(hot_s=sample["continuous_hot_s"], temp_c=sample["temp_c"], hour=hour,
                            idle_s=idle, peer_online=peer.get("accepted") is True)
    return {"target": target, "reason": reason, "hour": hour, "idle_s": idle,
            "peer_online": peer.get("transport_ok") is True, "peer_guard": peer, **sample}


def _night_available():
    hour = dt.datetime.now().hour
    idle = idle_seconds()
    return (hour >= 22 or hour < 6) and idle is not None and idle >= 1800


def run_batch(decision, repo: Path, remote_root: str | None, *, policy=None):
    """Check the selected workspace or an explicitly named existing peer tree."""
    if decision["target"] == "defer":
        return {"state": "deferred", "reason": decision.get("peer_guard", {}).get("reason", decision.get("reason"))}
    if decision["target"] == "peer":
        if remote_root is None:
            return _check_submitted_sources(repo, policy)
        if not remote_root.startswith("/") or "\0" in remote_root:
            raise ValueError("supply an absolute, existing project path on svhome")
        observed = decision.get("peer_guard", {}).get("effective_policy", {})
        guard_policy = {**_SYNTAX_POLICY, **(policy or {}), **observed, "disk_path": remote_root}
        result = _remote_guard(_REMOTE_SYNTAX, [remote_root, *sorted(DEFAULT_IGNORE_DIRS)],
                               guard_policy, execute=True, timeout=guard_policy["runtime_seconds"] + 15)
        return {**result, "source_mode": "existing_peer_tree", "source_path": remote_root}
    if not repo.is_dir():
        raise ValueError("expected a local project directory")
    count, errors = 0, []
    next_thermal = 0.0
    for directory, dirs, names in os.walk(repo):
        dirs[:] = sorted(d for d in dirs if d not in DEFAULT_IGNORE_DIRS and not Path(directory, d).is_symlink())
        for name in sorted(names):
            path = Path(directory, name)
            if path.suffix != ".py" or path.is_symlink():
                continue
            if not _night_available():
                return {"state": "yielded_to_user", "files": count, "errors": errors}
            if time.monotonic() >= next_thermal:
                _, _, temp = _sensors()
                if temp is None or temp >= 75:
                    return {"state": "yielded_to_temperature", "files": count, "errors": errors}
                next_thermal = time.monotonic() + 5
            try:
                with tokenize.open(path) as stream:
                    ast.parse(stream.read(), filename=str(path))
            except (OSError, SyntaxError, UnicodeError) as exc:
                errors.append({"file": str(path.relative_to(repo)), "type": type(exc).__name__})
            count += 1
    return {"state": "finished", "entry": "syntax_check", "files": count, "errors": errors}


def _check_submitted_sources(repo, policy):
    """Keep the verified input and receiver budgets on the same build request."""
    import base64
    from .guarded_build import submit

    report_name = ".chimera-syntax-report.json"
    suffix = 0
    while (Path(repo) / report_name).exists():
        suffix += 1
        report_name = f".chimera-syntax-report-{suffix}.json"
    ignored = json.dumps(sorted(DEFAULT_IGNORE_DIRS))
    entry = _SYNTAX_CHECK + (
        f"\ndata = syntax_check(Path.cwd(), set({ignored}))\n"
        f"with open({report_name!r}, 'x', encoding='utf-8') as out:\n"
        "    json.dump(data, out, ensure_ascii=True)\n"
    )
    command = shlex.join(["python3", "-I", "-B", "-S", "-c", entry])
    limits = {**_SYNTAX_POLICY, **(policy or {})}
    receipt = submit(command, cwd=repo, target="svhome", sync=True, reuse=True,
                     environment_id="chimera-stdlib-python-syntax-v1", artifacts=[report_name],
                     admission_policy=limits, timeout_s=min(limits["runtime_seconds"], 300))
    evidence = {k: receipt[k] for k in ("snapshot", "request_id", "attempt_id", "queue",
                "delivery", "source_delivery", "runtime_guard", "client_timing_ms") if k in receipt}
    evidence["source_mode"] = "submitted_workspace"
    if not receipt.get("ok"):
        state = receipt.get("state") or "failed"
        return {**evidence, "state": state, "reason": receipt.get("error", state)}
    raw = base64.b64decode(receipt["artifacts"][report_name]["base64"], validate=True)
    return {**json.loads(raw), **evidence, "peer_guard": receipt["admission"]}


_SYNTAX_CHECK = """
import ast, json, os, tokenize
from pathlib import Path

def syntax_check(root, ignored, monitor=None):
    if not root.is_dir():
        raise ValueError('expected an existing project directory on svhome')
    errors, count = [], 0
    for directory, dirs, names in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in ignored and not Path(directory, d).is_symlink())
        for name in sorted(names):
            if monitor:
                monitor()
            path = Path(directory, name)
            if path.suffix != '.py' or path.is_symlink():
                continue
            try:
                with tokenize.open(path) as stream:
                    ast.parse(stream.read(), filename=str(path))
            except (OSError, SyntaxError, UnicodeError) as exc:
                errors.append({'file': str(path.relative_to(root)), 'type': type(exc).__name__})
            count += 1
    return {'state': 'finished', 'entry': 'syntax_check', 'files': count, 'errors': errors}

"""

_REMOTE_SYNTAX = _SYNTAX_CHECK + """
try:
    with reserve(DEFAULT_ROOT, json.loads(sys.argv[1])) as guard:
        next_probe = time.monotonic() + 0.5
        def monitor():
            global next_probe
            if time.monotonic() >= next_probe:
                recheck_running(DEFAULT_ROOT, guard["effective_policy"])
                next_probe = time.monotonic() + 0.5
        result = syntax_check(Path(sys.argv[2]).resolve(strict=True), set(sys.argv[3:]), monitor)
        result['peer_guard'] = guard
except AdmissionDeferred as exc:
    result = {'state': 'deferred', **exc.as_dict()}
except (OSError, ValueError) as exc:
    result = {'state': 'failed', 'reason': type(exc).__name__, 'detail': str(exc)}
print(json.dumps(result))
"""
