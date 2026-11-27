"""Run a build on the selected SSH peer from the worktree the agent actually sees."""

from __future__ import annotations

import argparse
import io
import json
from pathlib import Path, PurePosixPath
import re
import shlex
import subprocess
import sys
import time
import uuid
import zipfile

from . import build_queue, build_snapshot as snapshot
from .build_registry import execute_once
from .build_worker import PROTOCOL, ARTIFACT_LIMIT


SSH_ROUTES = frozenset({"ssh_alias", "phantom_ssh"})

# Leave stdin at the exact start of the request for systemd-run. Buffered reads
# here could consume part of the following frame, especially on short messages.
_BOOT = """
import json, os, pathlib, sys, tempfile
def take(n):
    chunks = bytearray()
    while len(chunks) < n:
        block = os.read(0, n-len(chunks))
        if not block:
            raise EOFError("incomplete worker package")
        chunks.extend(block)
    return chunks
try:
    length = int.from_bytes(take(4), "big")
    if not 1 <= length <= 200000:
        raise ValueError("worker package size")
    with tempfile.TemporaryDirectory(prefix="chimera-worker-") as tmp:
        archive = pathlib.Path(tmp, "worker.zip")
        archive.write_bytes(take(length))
        sys.path.insert(0, str(archive))
        from chimera_tp.platform.build_worker import coordinate
        print(json.dumps(coordinate(archive, sys.argv[1] == "1"), ensure_ascii=True))
except Exception as exc:
    print(json.dumps({"ok":False,"protocol":1,"state":"indeterminate","error":str(exc)}))
"""


def _package():
    files = ["agent_workspace", "build_snapshot", "build_registry", "build_worker", "peer_guard"]
    parent = Path(__file__).resolve().parent
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        for path in ("chimera_tp/__init__.py", "chimera_tp/platform/__init__.py"):
            archive.writestr(zipfile.ZipInfo(path), b"")
        for name in files:
            path = parent / (name + ".py")
            info = zipfile.ZipInfo("chimera_tp/platform/" + path.name)
            archive.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED)
    return stream.getvalue()


def _verify(result, request):
    if not isinstance(result, dict) or result.get("protocol") != PROTOCOL:
        raise ValueError("invalid_worker_receipt")
    if not result.get("ok"):
        return
    if result.get("state") != "completed" or result.get("snapshot") != request["snapshot"]:
        raise ValueError("worker_input_receipt_mismatch")
    outputs = result.get("artifacts", {})
    if set(outputs) != set(request["artifacts"]) or not result.get("attempt_id"):
        raise ValueError("incomplete_worker_receipt")
    total = 0
    for name, item in outputs.items():
        snapshot.portable_path(name)
        total += len(snapshot.artifact_bytes(item, ARTIFACT_LIMIT - total))


def _dispatch(peer, package, request, wire):
    from .work_admission import peer_ssh_route

    ssh, route = peer_ssh_route(peer)
    expected = request.get("expected_ssh_route")
    if expected is not None and route != expected:
        return {"ok": False, "protocol": PROTOCOL, "state": "deferred",
                "error": "placement_ssh_route_changed", "expected_ssh_route": expected,
                "available_ssh_route": route, "ssh_request_bytes": 0, "retryable": bool(request["reuse"])}
    metadata = snapshot.canonical(request)
    data = len(package).to_bytes(4, "big") + package + len(metadata).to_bytes(4, "big") + metadata + wire
    remote = shlex.join(["python3", "-I", "-B", "-S", "-c", _BOOT, "1" if request["require_io_limit"] else "0"])
    command = [*ssh, remote]
    dispatched_at = time.monotonic()
    try:
        result = subprocess.run(command, input=data, capture_output=True,
                                timeout=request["timeout_s"] + 45,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if result.returncode:
            raise OSError(result.stderr.decode("utf-8", "replace")[-900:] or f"ssh_exit_{result.returncode}")
        receipt = json.loads(result.stdout)
        _verify(receipt, request)
        return {**receipt, "ssh_route": route,
                "ssh_exchange_ms": round((time.monotonic() - dispatched_at) * 1000, 3),
                "ssh_request_bytes": len(data)}
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        return {"ok": False, "protocol": PROTOCOL, "state": "indeterminate", "retryable": bool(request["reuse"]),
                "ssh_exchange_ms": round((time.monotonic() - dispatched_at) * 1000, 3),
                "ssh_request_bytes": len(data),
                "error": f"remote_receipt_unavailable:{exc}"}


def _outgoing(root=None):
    return build_queue.outgoing(root)


def _send_repeatable(root, peer, package, request, wire, wait_s):
    key = build_queue.ticket(peer, request)
    deadline = time.monotonic() + wait_s

    def send():
        delay = 1.0
        while True:
            response = _dispatch(peer, package, request, wire)
            recoverable = (response.get("state") == "deferred" or
                           (response.get("state") == "indeterminate" and response.get("retryable")))
            if not recoverable:
                if response.get("state") in {"completed", "failed"}:
                    build_queue.finish(root, key)
                return response
            response["queue"] = build_queue.put(root, peer, request, wire, response.get("error", "deferred"))
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not response["queue"]["stored"] or response.get("error") in {
                "io_cap_unavailable", "receiver_policy_invalid", "job_budget_exceeds_receiver_policy",
                "placement_ssh_route_changed",
            }:
                return response
            time.sleep(min(delay, remaining))
            delay = min(delay * 2, 8)

    return execute_once(root, key, send, persist=False, wait_s=request["timeout_s"] + wait_s + 50)


def retry_queued(key, *, wait_s=0, state_dir=None):
    root = _outgoing(state_dir)
    try:
        if not 0 <= wait_s <= 300:
            raise ValueError("capacity_wait_must_be_0_to_300_seconds")
        peer, request, wire = build_queue.get(root, key)
        if request.get("kind") == "exile_handoff":
            from . import exile_queue

            try:
                return exile_queue.retry(root, key, peer, request, wire, wait_s)
            except (ValueError, OSError) as exc:
                return {"ok": False, "state": "rejected", "error": str(exc),
                        "job_id": request["job_id"], "queue": {"stored": True, "id": key}}
        package = _package()
        if request["protocol"] != PROTOCOL:
            return {"ok": False, "state": "rejected", "error": "queued_protocol_unsupported",
                    "queue": {"id": key, "stored": True}}
        current_digest = snapshot.sha(package)
        if request["worker_version"] != current_digest:
            request = build_queue.refresh_worker(root, key, peer, request, current_digest)
        receipt, delivery = _send_repeatable(root, peer, package, request, wire, wait_s)
        return {**receipt, "request_id": uuid.uuid4().hex, "source_delivery": delivery}
    except (ValueError, OSError) as exc:
        return {"ok": False, "state": "rejected", "error": str(exc)}


def submit(command, *, cwd=None, peer="svhome", target="svhome", remote_root="/home/svhome/DEV", sync=True,
           environment_id="", reuse=False, artifacts=(), timeout_s=120, require_io_limit=False,
           state_dir=None, wait_s=0, admission_policy=None, expected_snapshot=None, expected_ssh_route=None):
    """Run a build in a private snapshot locally or through the authenticated SSH peer."""
    start = time.monotonic()
    ticket = uuid.uuid4().hex
    try:
        if target not in {"svhome", "local"}:
            raise ValueError("unknown_build_target")
        if expected_ssh_route is not None and (target == "local" or expected_ssh_route not in SSH_ROUTES):
            raise ValueError("invalid_expected_ssh_route")
        if target != "local" and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.@-]{0,200}", peer):
            raise ValueError("invalid_ssh_host")
        if not isinstance(command, str) or not command.strip() or len(command) > 32000:
            raise ValueError("invalid_build_command")
        if not 1 <= float(timeout_s) <= 300:
            raise ValueError("timeout_must_be_between_1_and_300_seconds")
        if not 0 <= wait_s <= 300:
            raise ValueError("capacity_wait_must_be_0_to_300_seconds")
        if admission_policy is not None:
            from . import peer_guard
            if not isinstance(admission_policy, dict):
                raise ValueError("invalid_peer_guard_request")
            peer_guard._config(admission_policy)
            if target == "local" and admission_policy:
                return {"ok": False, "state": "deferred", "target": "local", "request_id": ticket,
                        "error": "linux_guard_policy_requires_peer"}
        if reuse and (not cwd or not isinstance(environment_id, str) or not environment_id.strip()):
            raise ValueError("repeatable_build_requires_workspace_and_environment_id")
        if not isinstance(artifacts, (tuple, list)) or len(artifacts) > 32:
            raise ValueError("invalid_artifact_list")
        names = sorted({snapshot.portable_path(p) for p in artifacts})
        if target == "local":
            if sys.platform != "win32" or require_io_limit:
                return {"ok": False, "state": "deferred", "target": "local", "request_id": ticket,
                        "error": "io_cap_unavailable" if require_io_limit else "local_build_requires_windows"}
            from .local_build import run_snapshot

            directory = Path(cwd or Path.cwd()).resolve(strict=True)
            snapshot_started = time.monotonic()
            source = snapshot.capture(directory)
            snapshot_ended = time.monotonic()
            if expected_snapshot is not None and source["digest"] != expected_snapshot:
                return {"ok": False, "state": "deferred", "target": "local", "request_id": ticket,
                        "error": "placement_inputs_changed"}
            if reuse:
                root = directory
                for _ in Path(source["cwd"]).parts:
                    root = root.parent
                cache = Path(state_dir or Path.home() / ".chimera" / "guarded-builds").resolve()
                if cache.is_relative_to(root):
                    raise ValueError("local_result_registry_inside_workspace")
            receipt = run_snapshot(command, source, names=names, environment_id=environment_id, reuse=reuse,
                                   timeout_s=float(timeout_s), state_dir=state_dir, wait_s=wait_s)
            _verify(receipt, {"snapshot": source["digest"], "artifacts": names})
            end = time.monotonic()
            return {**receipt, "request_id": ticket, "source_delivery": receipt["delivery"],
                    "sync": {k: source[k] for k in ("digest", "files", "bytes", "cwd")},
                    "client_timing_ms": {"setup": round((snapshot_started - start) * 1000, 3),
                                         "snapshot": round((snapshot_ended - snapshot_started) * 1000, 3),
                                         "dispatch_or_join": round((end - snapshot_ended) * 1000, 3)},
                    "elapsed_end_to_end_ms": round((end - start) * 1000, 2)}
        if not PurePosixPath(remote_root).is_absolute():
            raise ValueError("remote_root_must_be_absolute")
        package = _package()
        snapshot_started = time.monotonic()
        source = snapshot.capture(Path(cwd), include_data=sync) if cwd else None
        snapshot_ended = time.monotonic()
        if expected_snapshot is not None and (not source or source["digest"] != expected_snapshot):
            return {"ok": False, "state": "deferred", "target": peer, "request_id": ticket,
                    "error": "placement_inputs_changed"}
        base = str(PurePosixPath(remote_root) / source["name"]) if source else remote_root
        if source and sync:
            base = None
        scope = source["scope"] if source else ""
        wire = source["wire"] if source else b""
        request = {"protocol": PROTOCOL, "worker_version": snapshot.sha(package), "command": command,
                   "timeout_s": float(timeout_s), "sync_workspace": bool(sync), "remote_cwd": base,
                   "scope": scope, "snapshot": source["digest"] if source else None,
                   "wire_bytes": len(wire), "environment_id": environment_id, "reuse": bool(reuse),
                   "require_io_limit": bool(require_io_limit),
                   "artifacts": names}

        if expected_ssh_route is not None:
            request["expected_ssh_route"] = expected_ssh_route
        if admission_policy:
            request["admission_policy"] = admission_policy
        if reuse:
            receipt, source_delivery = _send_repeatable(_outgoing(state_dir), peer, package, request, wire, wait_s)
        else:
            receipt, source_delivery = _dispatch(peer, package, request, wire), "executed"
        manifest = {k: source[k] for k in ("digest", "files", "bytes", "cwd")} if source else None
        end = time.monotonic()
        return {**receipt, "request_id": ticket, "source_delivery": source_delivery, "sync": manifest,
                "client_timing_ms": {"setup": round((snapshot_started - start) * 1000, 3),
                                     "snapshot": round((snapshot_ended - snapshot_started) * 1000, 3),
                                     "dispatch_or_join": round((end - snapshot_ended) * 1000, 3)},
                "elapsed_end_to_end_ms": round((end - start) * 1000, 2)}
    except (ValueError, TypeError, OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "state": "rejected", "error": str(exc), "request_id": ticket}


def configure(parser: argparse.ArgumentParser):
    parser.add_argument("cmd", help="Build command interpreted by the selected target's shell")
    parser.add_argument("--cwd", type=Path, default=Path.cwd(), help="Workspace whose current files are inputs")
    parser.add_argument("--peer", default="svhome", help="Configured SSH host")
    parser.add_argument("--target", choices=("svhome", "local"), default="svhome",
                        help="Use the guarded SSH peer (default) or run in a private snapshot on Windows")
    parser.add_argument("--reuse", metavar="ENVIRONMENT_ID",
                        help="Declare repeatable work and identify all external tools, dependencies and data")
    parser.add_argument("--artifact", action="append", default=[], help="Return a workspace-relative output file")
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--wait", type=int, default=0, help="Seconds to wait for a deferred repeatable build")
    parser.add_argument("--require-io-cap", action="store_true", help="Defer unless a hard SSD write limit applies")


def cli(args):
    result = submit(args.cmd, cwd=args.cwd, peer=args.peer, target=args.target, environment_id=args.reuse or "",
                    reuse=bool(args.reuse), artifacts=args.artifact, timeout_s=args.timeout,
                    require_io_limit=args.require_io_cap, wait_s=args.wait)
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0 if result.get("ok") else (75 if result.get("state") == "deferred" else 1)


def submit_isolated(command, **kwargs):
    """Keep snapshot compression, SSH I/O and the job's peak memory outside the daemon."""
    here = str(Path(__file__).resolve().parents[2])
    entry = ("import json,sys;sys.path.insert(0,sys.argv[1]);"
             "from chimera_tp.platform.guarded_build import submit;"
             "print(json.dumps(submit(**json.load(sys.stdin)),ensure_ascii=True))")
    try:
        payload = json.dumps({"command": command, **kwargs}, ensure_ascii=True, default=str).encode()
        result = subprocess.run([sys.executable, "-I", "-B", "-S", "-c", entry, here],
                                input=payload, capture_output=True,
                                timeout=float(kwargs.get("timeout_s", 120)) + float(kwargs.get("wait_s", 0)) + 90,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if result.returncode:
            raise OSError("isolated_submitter_terminated")
        return json.loads(result.stdout)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        return {"ok": False, "state": "indeterminate", "error": str(exc),
                "retryable": bool(kwargs.get("reuse"))}


def configure_queue(parser):
    parser.add_argument("--state-dir", type=Path, help="Directory containing the sender outbox")
    actions = parser.add_subparsers(dest="queue_action", required=True)
    actions.add_parser("list", help="List locally retained inputs")
    retry = actions.add_parser("retry", help="Retry the same snapshot after capacity returns")
    retry.add_argument("id")
    retry.add_argument("--wait", type=int, default=0)
    cancel = actions.add_parser("cancel", help="Discard the specified retained input")
    cancel.add_argument("id")


def queue_cli(args):
    root = _outgoing(getattr(args, "state_dir", None))
    if args.queue_action == "list":
        result = {"ok": True, "pending": build_queue.list_pending(root)}
    elif args.queue_action == "cancel":
        try:
            build_queue.get(root, args.id)
        except ValueError as exc:
            result = {"ok": False, "error": str(exc)}
        else:
            build_queue.finish(root, args.id)
            result = {"ok": True, "cancelled": args.id}
    else:
        result = retry_queued(args.id, wait_s=args.wait, state_dir=root)
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0 if result.get("ok") else (75 if result.get("state") == "deferred" else 1)
