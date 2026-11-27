"""Compare two independent C builds over fresh SSH sessions and one finite session.

The controller sends only the generated sources to the configured svhome peer.
Both arms use the installed build protocol and the same receiving worker package.
The paired receiver accepts exactly two compiler fixtures and exits.
"""

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shlex
import statistics
import subprocess
import sys
import tempfile
import time


COMMAND = 'TMPDIR="$PWD" cc -std=c11 -Wall -Werror main.c -o program && ./program > answer.txt'
OUTPUTS = ["answer.txt", "program"]
POLICY = {"job_memory_mib": 192, "job_disk_mib": 16, "runtime_seconds": 35}
PEER = "svhome"

# Each frame is fed to the unmodified one-job receiver with its own EOF and
# systemd reservation. A disconnected controller is never retried here.
PAIR = """
import hashlib, json, os, pathlib, subprocess, sys, time
boot, command = sys.argv[1:]
connection = hashlib.sha256(os.environ["SSH_CONNECTION"].encode()).hexdigest()
for ordinal in (1, 2):
    length = int.from_bytes(sys.stdin.buffer.read(4), "big")
    if not 1 <= length <= 524288:
        raise ValueError("fixture frame length")
    frame = sys.stdin.buffer.read(length)
    archive_end = 4 + int.from_bytes(frame[:4], "big")
    size = int.from_bytes(frame[archive_end:archive_end+4], "big")
    start = archive_end + 4
    header = json.loads(frame[start:start+size])
    if (len(frame) != length or header["command"] != command or header["reuse"]
            or not header["sync_workspace"] or header["remote_cwd"] is not None
            or header["artifacts"] != ["answer.txt", "program"]):
        raise ValueError("incorrect compiler fixture")
    began = time.monotonic()
    child = subprocess.run([sys.executable, "-I", "-B", "-S", "-c", boot, "0"],
                           input=frame, capture_output=True, check=True, timeout=55)
    receipt = json.loads(child.stdout)
    idle = subprocess.run(["systemctl", "--user", "show", "chimera-peer-guest.service",
                           "-p", "ActiveState", "--value"], capture_output=True, timeout=5)
    state = idle.stdout.decode().strip()
    print(json.dumps({"index":ordinal,"connection":connection,"receiver_pid":os.getpid(),
                      "worker_ms":(time.monotonic()-began)*1000,"guest_state_after":state,
                      "receipt":receipt}), flush=True)
    if not receipt.get("ok") or idle.returncode or state != "inactive":
        sys.exit(1)
if sys.stdin.buffer.read(1):
    raise ValueError("trailing fixture bytes")
"""


def digest(data):
    return hashlib.sha256(data).hexdigest()


def fixture(root, value):
    root.mkdir()
    text = '#include <stdio.h>\nint main(void) { puts("%d"); return 0; }\n' % value
    (root / "main.c").write_bytes(text.encode("ascii"))
    return root, ("%d\n" % value).encode("ascii")


def request(build, root, package):
    source = build.snapshot.capture(root)
    header = {
        "protocol": build.PROTOCOL,
        "worker_version": digest(package),
        "command": COMMAND,
        "timeout_s": 20.0,
        "sync_workspace": True,
        "remote_cwd": None,
        "scope": source["scope"],
        "snapshot": source["digest"],
        "wire_bytes": len(source["wire"]),
        "environment_id": "",
        "reuse": False,
        "require_io_limit": False,
        "artifacts": OUTPUTS,
        "admission_policy": POLICY,
    }
    meta = build.snapshot.canonical(header)
    frame = (
        len(package).to_bytes(4, "big") + package + len(meta).to_bytes(4, "big") + meta + source["wire"]
    )
    return header, frame


def evidence(build, receipt, header, answer):
    build._verify(receipt, header)
    if not receipt.get("ok"):
        raise RuntimeError(
            f"build {receipt.get('state')}: {receipt.get('error') or receipt.get('stderr', '')[:240]}"
        )
    if (
        receipt.get("target") != PEER
        or receipt["delivery"] != "executed"
        or not receipt["admission"]["limits_verified"]
        or receipt["exit_code"] != 0
    ):
        raise ValueError("missing independent admitted build")
    outputs = receipt["artifacts"]
    binary = base64.b64decode(outputs["program"]["base64"], validate=True)
    actual = base64.b64decode(outputs["answer.txt"]["base64"], validate=True)
    if actual != answer or not binary.startswith(b"\x7fELF"):
        raise ValueError("compiler output or executable result mismatch")
    info = receipt["admission"]["health"]
    return {
        "attempt": receipt["attempt_id"],
        "snapshot": receipt["snapshot"],
        "binary_sha256": digest(binary),
        "answer_sha256": digest(actual),
        "compiler_ms": receipt["process_wall_ms"],
        "limits": info["limits"],
        "service_p95_ms": info["service_p95_ms"],
        "cgroup": info["cgroup"],
    }


def cold(build, jobs):
    began = time.monotonic()
    rows = []
    for root, answer in jobs:
        res = build.submit(
            COMMAND,
            cwd=root,
            peer=PEER,
            sync=True,
            reuse=False,
            artifacts=OUTPUTS,
            timeout_s=20,
            admission_policy=POLICY,
        )
        if res.get("ssh_route") != "phantom_ssh":
            raise RuntimeError("fresh SSH arm did not use the direct route: " + str(res.get("error")))
        rows.append(
            evidence(build, res, {"snapshot": res["sync"]["digest"], "artifacts": OUTPUTS}, answer)
        )
    return {"wall_ms": (time.monotonic() - began) * 1000, "connections": 2, "jobs": rows}


def shared(build, route, jobs):
    began = time.monotonic()
    ssh, label = route(PEER)
    if label != "phantom_ssh" or "StrictHostKeyChecking=yes" not in ssh:
        raise ValueError("direct authenticated PHANTOM SSH route required")
    package = build._package()
    frames = [request(build, root, package) for root, _ in jobs]
    wire = b"".join(len(frame).to_bytes(4, "big") + frame for _, frame in frames)
    remote = shlex.join(["python3", "-I", "-B", "-S", "-c", PAIR, build._BOOT, COMMAND])
    proc = subprocess.run(
        [*ssh, remote],
        input=wire,
        capture_output=True,
        timeout=120,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    results = [json.loads(line) for line in proc.stdout.splitlines()]
    if proc.returncode or len(results) != 2:
        states = [
            (r["receipt"].get("state"), r["receipt"].get("error"), r.get("guest_state_after"))
            for r in results
        ]
        raise RuntimeError(
            f"paired compiler run failed: {states} {proc.stderr.decode(errors='replace')[-240:]}"
        )
    if (
        [r["index"] for r in results] != [1, 2]
        or len({r["connection"] for r in results}) != 1
        or len({r["receiver_pid"] for r in results}) != 1
    ):
        raise ValueError("the pair did not share one authenticated SSH connection")
    rows = []
    for result, (header, _), (_, answer) in zip(results, frames, jobs, strict=True):
        row = evidence(build, result["receipt"], header, answer)
        row.update(guest_state_after=result["guest_state_after"], worker_ms=result["worker_ms"])
        rows.append(row)
    return {
        "wall_ms": (time.monotonic() - began) * 1000,
        "connections": 1,
        "ssh_connection_sha256": results[0]["connection"],
        "receiver_pid": results[0]["receiver_pid"],
        "jobs": rows,
    }


def measure(source_root, pairs):
    sys.path.insert(0, str(source_root.resolve(strict=True)))
    from chimera_tp.platform import guarded_build as build
    from chimera_tp.platform.work_admission import peer_ssh_route

    if not Path(build.__file__).resolve().is_relative_to(source_root.resolve()):
        raise RuntimeError("unexpected source package")
    rows = []
    with tempfile.TemporaryDirectory(prefix="chimera-c-pairs-") as directory:
        root = Path(directory)
        for i in range(pairs):
            jobs = [fixture(root / f"p{i}-{j}", 1000 + 2 * i + j) for j in range(2)]
            order = ("fresh", "shared") if i % 2 == 0 else ("shared", "fresh")
            trial = {"pair": i + 1, "order": order}
            for arm in order:
                trial[arm] = cold(build, jobs) if arm == "fresh" else shared(build, peer_ssh_route, jobs)
            for a, b in zip(trial["fresh"]["jobs"], trial["shared"]["jobs"], strict=True):
                if any(a[k] != b[k] for k in ("snapshot", "binary_sha256", "answer_sha256")):
                    raise ValueError("different inputs or artifacts in paired arms")
            rows.append(trial)
    attempts = [j["attempt"] for row in rows for arm in ("fresh", "shared") for j in row[arm]["jobs"]]
    if len(set(attempts)) != 4 * pairs or root.exists():
        raise RuntimeError("unexpected reuse or fixture cleanup failure")
    medians = {arm: statistics.median(row[arm]["wall_ms"] for row in rows) for arm in ("fresh", "shared")}
    return {
        "schema": "chimera.guarded-compiler-ssh-pair/1",
        "utc": datetime.now(timezone.utc).isoformat(),
        "source_root": str(source_root.resolve()),
        "worker_sha256": digest(build._package()),
        "peer": PEER,
        "command": COMMAND,
        "policy": POLICY,
        "pairs": rows,
        "medians_ms": medians,
        "unique_build_attempts": len(set(attempts)),
        "temporary_source_removed": True,
        "scope": "Shadow. Two serial C builds with empty result caches. Shared wall time includes "
        "opening and closing the SSH connection and two post-job systemd checks. "
        "No reusable service or live routing policy was installed.",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--pairs", type=int, choices=range(1, 9), default=4)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("output already exists")
    report = measure(args.source_root, args.pairs)
    with args.out.open("x", encoding="utf-8") as output:
        json.dump(report, output, indent=2)
        output.write("\n")
    print(json.dumps({"builds": report["unique_build_attempts"], "median_ms": report["medians_ms"]}))
