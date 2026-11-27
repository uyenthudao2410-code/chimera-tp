"""Dispatch explicit Colab compute operations through the supported one-shot bridge."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import subprocess
import time
import uuid

from .colab_cli_bridge import ColabCliBridge, RUNTIME_PROFILES


def run_local(command, state_dir: Path):
    """Use the installed CLI when a loopback anchor predates verified Exile.

    Independent SDK processes share the CLI session file. Its OS lock is
    released automatically if a client exits while the provider is busy.
    """
    from .agent_workspace import LeaseBusy, _lock

    state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        with _lock(state_dir / "client.lock"):
            return run(ColabCliBridge(state_dir), command)
    except LeaseBusy:
        return {"ok": False, "state": "deferred", "error": "local_colab_client_busy"}


def run(bridge, command):
    if bridge is None:
        return {"ok": False, "error": "colab_bridge_unavailable"}
    if not isinstance(command, str) or len(command.encode("utf-8")) > 128 * 1024:
        return {"ok": False, "error": "colab_payload_limit"}
    try:
        spec = json.loads(command)
    except (ValueError, TypeError):
        spec = {"task": command}
    if not isinstance(spec, dict):
        return {"ok": False, "error": "colab_task_object_required"}
    kind = spec.get("task")
    profiles = {"probe": "CPU", "python_compile": "CPU", "cuda_matmul": "T4", "cuda_embed": "T4"}
    if not isinstance(kind, str) or kind not in profiles:
        return {"ok": False, "error": "unsupported_colab_task", "supported": sorted(profiles)}
    payload = spec.get("payload", {})
    allowed = {"probe": set(), "python_compile": {"files"}, "cuda_matmul": {"n"}, "cuda_embed": {"texts", "dim"}}
    if not isinstance(payload, dict) or set(payload) - allowed[kind]:
        return {"ok": False, "error": "invalid_colab_task_payload"}
    if kind == "python_compile" and (not isinstance(payload.get("files"), dict)
                                     or not 1 <= len(payload["files"]) <= 1000
                                     or not all(path and isinstance(v, str)
                                                for path, v in payload["files"].items())):
        return {"ok": False, "error": "python_sources_required"}
    if kind == "cuda_embed" and (not isinstance(payload.get("texts"), list) or not payload["texts"]
                                  or not all(isinstance(v, str) for v in payload["texts"])):
        return {"ok": False, "error": "texts_required"}
    if kind == "cuda_embed" and "dim" in payload and (
            type(payload["dim"]) is not int or not 32 <= payload["dim"] <= 1024):
        return {"ok": False, "error": "embedding_dimension_must_be_32_to_1024"}
    if kind == "cuda_matmul" and (type(payload.get("n")) is not int or not 64 <= payload["n"] <= 4096):
        return {"ok": False, "error": "matrix_size_must_be_64_to_4096"}
    # Estimate covers provisioning, the bridge's five minute job and stop. A hard
    # account-wide spending limit must be implemented by the billing provider.
    profile = profiles[kind]
    estimate = round(RUNTIME_PROFILES[profile]["est_cu_hr"] * (10 / 60), 4)
    cap = spec.get("max_estimated_cu")
    if (type(cap) not in (int, float) or not math.isfinite(cap) or cap < estimate
            or "hard_cu_limit" in spec):
        return {"ok": False, "state": "deferred", "error": "colab_budget_required_or_insufficient",
                "estimated_cu": estimate, "profile": profile, "hard_cu_limit_supported": False}
    start = time.monotonic()
    session = None
    try:
        usage = bridge.status(refresh=True).get("usage", {})
        balance = usage.get("balance_cu")
        if not usage.get("available") or type(balance) not in (int, float) or not math.isfinite(balance) or balance < estimate:
            return {"ok": False, "state": "deferred", "error": "colab_balance_unavailable_or_insufficient"}
        session = "chimera_exile_" + uuid.uuid4().hex[:14]
        result = bridge.exec_task(kind, payload, profile=profile, require_gpu=profile == "T4",
                                  session_name=session, keep_session=False)
        actual = result.get("result") or {}
        finished = bool(result.get("ok") and actual.get("ok") and actual.get("task_kind") == kind)
        if kind == "python_compile":
            expected = {p: hashlib.sha256(s.encode("utf-8")).hexdigest() for p, s in payload["files"].items()}
            finished = finished and actual.get("files") == expected
        if profile == "T4":
            finished = finished and actual.get("device") == "cuda"
        stopped = bool(result.get("auto_stopped_cu_guard"))
        state = "indeterminate" if not stopped else ("completed" if finished else "failed")
        return {"ok": finished and stopped, "target": "colab", "task": kind, "result": result,
                "state": state, "session": session, "session_stop_confirmed": stopped,
                "error": None if finished and stopped else "colab_task_or_session_stop_unconfirmed",
                "estimated_cu": estimate, "elapsed_ms": round((time.monotonic() - start) * 1000, 2)}
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, KeyError) as exc:
        return {"ok": False, "target": "colab", "state": "indeterminate", "session": session, "error": str(exc)}
