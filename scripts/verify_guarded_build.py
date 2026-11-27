"""Exercise live CLI/MCP build coalescing against the configured svhome SSH peer.

Only fixture code and synthetic source leave the controller. Each invocation
writes a fresh random marker in a private disposable receiver-side directory,
independent of the shared action cache, so duplicate work can be counted.
"""

import argparse
import base64
import concurrent.futures
import datetime as dt
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import threading
import time
import zipfile


ROOT = Path(__file__).resolve().parents[1]
PEER = "svhome"
ENV = "cpython-stdlib-v1"
COMMAND = "python3 -I -B -S build_fixture.py"
ARTIFACT = "bundle.zip"
BASE = b"def area(w, h):\n    return w * h\n"
CHANGED = BASE + b"\nunit = 'mm2'\n"
MODULES = ("guarded_build", "build_snapshot", "build_registry", "build_worker", "peer_guard")
sys.path.insert(0, str(ROOT))


PEER_COUNTER = """
import json, os, pathlib, re, stat, subprocess, sys, tempfile
base = pathlib.Path(tempfile.gettempdir()).resolve()
op = sys.argv[1]
if op == "start":
    folder = pathlib.Path(tempfile.mkdtemp(prefix="chimera-build-proof-", dir=base))
    group = subprocess.check_output(["systemctl","--user","show","-p","ControlGroup","--value"],text=True).strip()
    controllers = (pathlib.Path("/sys/fs/cgroup") / group.lstrip("/") / "cgroup.controllers").read_text().split()
    print(json.dumps({"directory":str(folder),"controllers":sorted(controllers)}))
else:
    path = pathlib.Path(sys.argv[2])
    if path.parent != base or not re.fullmatch(r"chimera-build-proof-[A-Za-z0-9_-]+", path.name):
        raise RuntimeError("unexpected counter path")
    st = path.lstat()
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077:
        raise RuntimeError("unexpected counter ownership")
    rows = []
    for node in path.iterdir():
        if not node.is_file() or node.is_symlink() or not re.fullmatch(r"(?:[0-9a-f]{32}[.]json|retry-once)",node.name):
            raise RuntimeError("unexpected fixture directory entry")
        if node.suffix == ".json":
            rows.append(json.loads(node.read_bytes()))
        if op == "finish":
            node.unlink()
    if op == "finish":
        path.rmdir()
    print(json.dumps(rows))
"""

WORKLOAD = """
import hashlib, json, os, pathlib, sys, time, uuid, zipfile
source = pathlib.Path("package.py").read_bytes()
compile(source, "package.py", "exec", dont_inherit=True)
counter = pathlib.Path("counter-path").read_text(encoding="utf-8")
ledger = pathlib.Path(counter)
mode = "retry" if "--fail-first" in sys.argv else "build"
instance = uuid.uuid4().hex
data = {"instance":instance,"mode":mode,"source_sha256":hashlib.sha256(source).hexdigest()}
with (ledger / (instance + ".json")).open("x", encoding="utf-8") as out:
    json.dump(data, out)
print(json.dumps(data), flush=True)
if mode == "retry":
    try:
        with (ledger / "retry-once").open("x"):
            pass
    except FileExistsError:
        pass
    else:
        sys.exit(23)
time.sleep(1.5)
info = zipfile.ZipInfo("package.py", (1980, 1, 1, 0, 0, 0))
info.create_system = 3
info.external_attr = 0o100644 << 16
with zipfile.ZipFile("bundle.zip", "w", zipfile.ZIP_STORED) as z:
    z.writestr(info, source)
"""


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(body):
    return hashlib.sha256(body).hexdigest()


def reference(source):
    """Generate the expected bytes locally and require byte-for-byte agreement."""
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        info = zipfile.ZipInfo("package.py")
        info.create_system = 3
        info.external_attr = 0o100644 << 16
        archive.writestr(info, source)
    return stream.getvalue()


def counter(op, directory=None):
    remote = shlex.join(["python3", "-I", "-B", "-S", "-", op, *([directory] if directory else [])])
    cmd = ["ssh", "-T", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes", "-o",
           "UpdateHostKeys=no", "-o", "ConnectTimeout=5", PEER, remote]
    result = subprocess.run(cmd, input=PEER_COUNTER, capture_output=True, text=True, timeout=15, check=True)
    return json.loads(result.stdout)


def init_fixture(path, directory):
    env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")

    def git(*args):
        p = subprocess.run(["git", "-c", "core.autocrlf=false", "-c", "user.name=Fixture",
                            "-c", "user.email=fixture@invalid.local", "-C", str(path), *args],
                           capture_output=True, check=True, env=env)
        return p.stdout.strip()

    git("init", "--quiet", "--template=")
    (path / "counter-path").write_text(directory, encoding="utf-8")
    (path / "build_fixture.py").write_bytes(WORKLOAD.encode())
    (path / "package.py").write_bytes(BASE)
    git("add", "--", "package.py", "build_fixture.py", "counter-path")
    git("commit", "--quiet", "-m", "Synthetic input for build protocol acceptance")
    return git


def invoke(entry, path, *, command=COMMAND, environment=ENV, hard_io=False, barrier=None):
    run = [sys.executable, "-B", "-m", "chimera_tp", entry]
    args = {"cmd": command, "cwd": str(path), "sync_workspace": True, "reuse": True,
            "target": "auto", "environment_id": environment, "artifacts": [ARTIFACT],
            "timeout_s": 30, "require_io_limit": hard_io}
    stdin = None
    if entry == "mcp":
        call = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                "params": {"name": "chimera_agent_exile", "arguments": args}}
        stdin = json.dumps(call).encode() + b"\n"
    else:
        run += ["--cwd", str(path), "--reuse", environment, "--artifact", ARTIFACT, "--timeout", "30"]
        if hard_io:
            run.append("--require-io-cap")
        run.append(command)
    if barrier:
        barrier.wait(timeout=10)
    started = time.monotonic()
    sub = subprocess.run(run, cwd=ROOT, input=stdin, capture_output=True, timeout=95)
    require(bool(sub.stdout), f"{entry}_returned_no_receipt_rc_{sub.returncode}")
    raw = json.loads(sub.stdout)
    if entry == "mcp":
        require(raw.get("id") == 1 and not raw.get("result", {}).get("isError"), "mcp_tool_error")
        raw = json.loads(raw["result"]["content"][0]["text"])
    else:
        require((sub.returncode == 0) == bool(raw.get("ok")), "cli_status_inconsistent")
    raw["client_ms"] = round((time.monotonic() - started) * 1000, 1)
    return raw


def evidence(entry, response, source=None):
    fields = ("ok", "request_id", "attempt_id", "key", "state", "target", "delivery",
              "source_delivery", "exit_code", "snapshot", "client_ms", "via")
    row = {key: response[key] for key in fields if key in response}
    row["entry"] = entry
    runtime = response.get("runtime_guard") or {}
    if runtime:
        row["runtime_health_samples"] = runtime["completed_samples"]
        row["max_protected_service_p95_ms"] = max(runtime["worst_service_p95_ms"].values(), default=None)
    if not response.get("ok"):
        # Remote command output is never copied to persistent evidence.
        row["error"] = str(response.get("error", "" )).split(":")[0][:70]
    stdout = response.get("stdout")
    if stdout:
        parsed = json.loads(stdout)
        require(bool(re.fullmatch(r"[a-f0-9]{32}", parsed["instance"])), "invalid_invocation_id")
        row["instance"] = parsed["instance"]
    if source is not None:
        require(row.get("ok"), f"{entry}_build_refused_{row.get('error')}")
        item = response["artifacts"][ARTIFACT]
        blob = base64.b64decode(item["base64"], validate=True)
        require(blob == reference(source), "binary_output_differs_from_local_oracle")
        require(item["sha256"] == sha(blob) and item["bytes"] == len(blob), "artifact_receipt_mismatch")
        require(parsed["source_sha256"] == sha(source), "executed_source_digest_mismatch")
        require(response["admission"]["limits_verified"], "job_ran_without_verified_limits")
        phases = response["attempt_timing_ms"]
        stage_keys = ("admission_ms", "workspace_ms", "command_ms", "outputs_ms", "cleanup_ms")
        require(all(phases[k] >= 0 for k in stage_keys), "negative_worker_duration")
        require(abs(phases["total_ms"] - sum(phases[k] for k in stage_keys)) < 0.02,
                "worker_total_does_not_match_stages")
        require(0 <= response["process_wall_ms"] <= phases["command_ms"] + 1, "bad_command_duration")
        require(response["reaped_child_cpu_ms"] >= 0, "bad_worker_cpu_counter")
        require(response["ssh_exchange_ms"] > 0 and response["ssh_request_bytes"] > 0, "missing_ssh_measurement")
        row["origin_attempt_timing_ms"] = phases
        row["origin_attempt_child_cpu_ms"] = response["reaped_child_cpu_ms"]
        row["origin_ssh_exchange_ms"] = response["ssh_exchange_ms"]
        row["ssh_request_bytes"] = response["ssh_request_bytes"]
        row["client_timing_ms"] = response.get("client_timing_ms")
        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            require(archive.namelist() == ["package.py"] and archive.read("package.py") == source,
                    "wrong_zip_member")
        row.update(artifact_sha256=sha(blob), artifact_bytes=len(blob), input_file_sha256=sha(source))
    return row


def snapshot_failures(fixture, scratch):
    from chimera_tp.platform import build_snapshot as snapshot

    snap = snapshot.capture(fixture)
    original = zipfile.ZipFile(io.BytesIO(snap["wire"]))
    changed = io.BytesIO()
    with original, zipfile.ZipFile(changed, "w") as archive:
        for member in original.namelist():
            data = original.read(member)
            if member == "files/package.py":
                data = bytes([data[0] ^ 1]) + data[1:]
            archive.writestr(member, data)
    scratch.mkdir()
    try:
        snapshot.materialize(changed.getvalue(), snap["digest"], scratch)
    except ValueError as exc:
        require(str(exc).startswith("snapshot_digest_mismatch:"), "incorrect_corruption_diagnostic")
        return {"case":"same_size_content_tamper", "error":"snapshot_digest_mismatch"}
    raise ValueError("corrupt_input_accepted")


def exercise(path, report):
    opened = counter("start")
    directory = opened["directory"]
    report["receiver_user_controllers"] = opened["controllers"]
    rows = report["receipts"]
    try:
        git = init_fixture(path, directory)
        head = git("rev-parse", "HEAD")
        start = threading.Barrier(2)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as workers:
            requests = [(entry, workers.submit(invoke, entry, path, barrier=start)) for entry in ("swarm", "mcp")]
            for entry, handle in requests:
                rows.append(evidence(entry, handle.result(), BASE))
        a, b = rows
        require(a["attempt_id"] == b["attempt_id"] and a["instance"] == b["instance"], "duplicate_execution")
        require(a["request_id"] != b["request_id"] and a["key"] == b["key"], "request_key_or_ticket_mismatch")
        require(len(counter("read", directory)) == 1, "two_entries_launched_multiple_builds")
        cache = evidence("swarm", invoke("swarm", path), BASE)
        rows.append(cache)
        require(cache["delivery"] == "cached" and cache["instance"] == a["instance"], "cache_miss")
        (path / "package.py").write_bytes(CHANGED)
        require(git("diff", "--name-only") == b"package.py" and git("rev-parse", "HEAD") == head,
                "fixture_not_an_uncommitted_edit")
        modified = evidence("mcp", invoke("mcp", path), CHANGED)
        rows.append(modified)
        require(modified["snapshot"] != a["snapshot"] and modified["instance"] != a["instance"], "stale_snapshot")
        tools = evidence("swarm", invoke("swarm", path, environment=ENV+"-tools2"), CHANGED)
        rows.append(tools)
        require(tools["key"] != modified["key"] and tools["instance"] != modified["instance"], "stale_toolchain")
        trial = COMMAND + " --fail-first"
        failure = evidence("swarm", invoke("swarm", path, command=trial))
        rows.append(failure)
        require(not failure["ok"] and failure["exit_code"] == 23, "expected_first_failure")
        retry = evidence("mcp", invoke("mcp", path, command=trial), CHANGED)
        rows.append(retry)
        require(retry["key"] == failure["key"] and retry["instance"] != failure["instance"], "failed_result_reused")
        io_result = invoke("swarm", path, hard_io=True)
        io_row = evidence("swarm", io_result, CHANGED if io_result.get("ok") else None)
        rows.append(io_row)
        if io_row["ok"]:
            health = io_result["admission"]["health"]
            require("io" in opened["controllers"] and 0 < health["limits"]["io_write_bps"] <= 8*1024**2,
                    "hard_io_request_ran_without_enforced_cap")
        else:
            require(io_row["state"] == "deferred", "io_unavailable_should_defer")
            retained = io_result.get("queue") or {}
            require(retained.get("stored") and retained.get("id"), "deferred_build_not_retained")
            cancellation = subprocess.run(
                [sys.executable, "-B", "-m", "chimera_tp", "swarm-queue", "cancel", retained["id"]],
                cwd=ROOT, capture_output=True, timeout=15, check=True)
            require(json.loads(cancellation.stdout).get("cancelled") == retained["id"], "fixture_outbox_not_clean")
            io_row["outbox_round_trip_verified"] = True
        report["input_rejections"].append(snapshot_failures(path, path.parent / "verify-input"))
        from chimera_tp.platform.build_snapshot import MAX_INPUT_BYTES
        with (path / "over-budget.bin").open("xb") as file:
            file.truncate(MAX_INPUT_BYTES + 1)
        excess = invoke("mcp", path)
        require(excess.get("state") == "rejected" and "snapshot_byte_limit" in excess.get("error", ""),
                "oversize_input_not_rejected_at_source")
        report["input_rejections"].append({"case":"oversize_workspace","error":"snapshot_byte_limit"})
        markers = counter("read", directory)
        seen = {r["instance"] for r in rows if "instance" in r}
        require(len(markers) == len(seen) and {m["instance"] for m in markers} == seen, "unused_or_missing_execution")
        report["receiver_invocations"] = len(markers)
    finally:
        counter("finish", directory)
        report["receiver_fixture_cleaned"] = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, help="Write sanitized receipts and verification outcome as JSON")
    args = parser.parse_args()
    report = {"schema":"chimera.guarded_build.acceptance.v1", "node":PEER, "ok":False,
              "started_utc":dt.datetime.now(dt.timezone.utc).isoformat(), "receipts":[], "input_rejections":[]}
    report["worker_sources_sha256"] = {
        name: sha((ROOT / "chimera_tp/platform" / (name + ".py")).read_bytes()) for name in MODULES
    }
    with tempfile.TemporaryDirectory(prefix="chimera-build-acceptance-") as temp:
        repo = Path(temp, "fixture")
        repo.mkdir()
        try:
            exercise(repo, report)
            report["ok"] = True
        except (ValueError, OSError, KeyError, subprocess.SubprocessError) as exc:
            report["failure"] = type(exc).__name__ + ":" + str(exc).split("\n")[0][:120]
    report["finished_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
    output = json.dumps(report, indent=2, sort_keys=True)
    if args.out:
        temp_report = args.out.with_suffix(".acceptance.tmp")
        with temp_report.open("x", encoding="utf-8", newline="\n") as target:
            target.write(output + "\n")
        os.replace(temp_report, args.out)
    print(output)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
