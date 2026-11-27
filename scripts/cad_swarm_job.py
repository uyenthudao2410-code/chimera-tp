"""Submit two equivalent agent builds and check the receiver's attempt and returned artifact."""

import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import textwrap
import threading
import uuid

from cad_build_job import stable_bytes
from measure_build_location import WORKER

ROOT = Path(__file__).resolve().parents[1]

PLACEMENT_WORKER = """
bundle = json.load(sys.stdin)
source = json.dumps(bundle["files"], ensure_ascii=True, separators=(",", ":")).encode("ascii")
assert bundle["rounds"] >= 1 and bundle["files"]
started, cpu_started = time.perf_counter(), time.process_time()
units = 0
compiled = {}
for round_number in range(bundle["rounds"]):
    for name, contents in bundle["files"]:
        code = compile(contents, name, "exec", dont_inherit=True, optimize=0)
        units += 1
        if round_number + 1 == bundle["rounds"]:
            compiled[name] = hashlib.sha256(marshal.dumps(code)).hexdigest()
print(json.dumps({"digest": hashlib.sha256(source).hexdigest(), "units": units,
                  "bytecode_sha256": compiled, "cpu_s": time.process_time() - cpu_started,
                  "work_s": time.perf_counter() - started, "python": sys.version.split()[0]}))
"""


def compile_program(placement=False):
    # The reference and Swarm paths compile the same input using the same loop.
    setup = """import contextlib, hashlib, io, json, marshal, os, sys, time, uuid
from pathlib import Path
raw = Path('input.json').read_bytes()
sys.stdin = io.StringIO(raw.decode('ascii'))
output = io.StringIO()
window_begin = time.perf_counter_ns()
with contextlib.redirect_stdout(output):
"""
    collect = """
window_end = time.perf_counter_ns()
record = json.loads(output.getvalue())
product = [record["digest"], record["units"]]
if "bytecode_sha256" in record:
    product.append(record["bytecode_sha256"])
artifact = json.dumps(product, separators=(",", ":")).encode("ascii")
Path(sys.argv[1]).write_bytes(artifact)
record["input_sha256"] = hashlib.sha256(raw).hexdigest()
record["result_sha256"] = hashlib.sha256(artifact).hexdigest()
record["window_ms"] = [window_begin / 1_000_000, window_end / 1_000_000]
record["compiler_instance"] = uuid.uuid4().hex
record["compiler_pid"] = os.getpid()
marker = Path("measurement-counters.json")
if marker.exists():
    directory = Path(json.loads(marker.read_text("utf-8"))["windows" if os.name == "nt" else "linux"])
    with (directory / (record["compiler_instance"] + ".json")).open("x", encoding="utf-8") as output:
        json.dump({"instance": record["compiler_instance"], "pid": record["compiler_pid"],
                   "cpu_s": record["cpu_s"], "result_sha256": record["result_sha256"]}, output)
print(json.dumps(record))
"""
    worker = PLACEMENT_WORKER if placement else WORKER
    return setup + textwrap.indent(worker.strip(), "    ") + "\n" + collect


def prepare(payload: Path, *, placement=False, counters=None):
    stage = payload.parent / "guarded-inputs"
    stage.mkdir()
    subprocess.run(["git", "init", "--quiet", "--template=", str(stage)], check=True, capture_output=True)
    (stage / "input.json").write_bytes(payload.read_bytes())
    (stage / "compile.py").write_bytes(compile_program(placement).encode("ascii"))
    if counters is not None:
        (stage / "measurement-counters.json").write_bytes(stable_bytes(counters))
    return {"staged": True}


def local(stage, timeout, compiler):
    with tempfile.TemporaryDirectory(prefix="cad-compile-artifact-") as folder:
        artifact = Path(folder) / "result.json"
        p = subprocess.run([compiler, "-I", "-B", "-S", "compile.py", str(artifact)], cwd=stage,
                           capture_output=True, timeout=timeout, check=True)
        report = json.loads(p.stdout)
        return report, artifact.read_bytes(), {"attempt_id": uuid.uuid4().hex, "delivery": "executed"}


def submit_compiler(site, stage, timeout, peer, key, snapshot_digest, compiler, wait_s,
                    state_dir, cpu_quota_pct):
    """Child entry point for one independent sender. Both sites use the same Swarm API."""
    sys.path.insert(0, str(ROOT))
    from chimera_tp.platform.guarded_build import submit

    if site not in ("local-shared", "remote") or (site != "remote" and cpu_quota_pct is not None):
        raise ValueError("Expected a guarded compiler and a CPU budget for the peer only")
    local_site = site == "local-shared"
    command = (subprocess.list2cmdline([compiler, "-I", "-B", "-S", "compile.py", "result.json"])
               if local_site else "python3 -I -B -S compile.py result.json")
    policy = {"cpu_quota_pct": cpu_quota_pct} if cpu_quota_pct is not None else None
    return submit(command, cwd=stage, peer=peer, target="local" if local_site else "svhome",
                  environment_id=key, reuse=True, artifacts=["result.json"], timeout_s=timeout,
                  wait_s=wait_s, admission_policy=policy, expected_snapshot=snapshot_digest, state_dir=state_dir)


def verified_admission(receipt, requested):
    admission = receipt.get("admission") or {}
    limits = (admission.get("health") or {}).get("limits") or {}
    actual = limits.get("cpu_quota_pct")
    effective = (admission.get("effective_policy") or {}).get("cpu_quota_pct")
    if (admission.get("accepted") is not True or admission.get("limits_verified") is not True
            or type(effective) is not int or type(actual) not in (float, int)
            or not 0 < actual <= effective or (requested is not None and effective > requested)):
        raise ValueError("Missing or inconsistent receiver CPU quota in the admitted build receipt")
    return {"accepted": True, "limits_verified": True, "requested_cpu_quota_pct": requested,
            "effective_cpu_quota_pct": effective, "kernel_cpu_quota_pct": actual}


def shared(site, stage, timeout, peer, key, snapshot_digest, compiler, wait_s, state_dir, cpu_quota_pct):
    spec = {"site": site, "stage": str(stage), "timeout": timeout, "peer": peer, "key": key,
            "snapshot_digest": snapshot_digest, "compiler": str(compiler), "wait_s": wait_s,
            "state_dir": state_dir, "cpu_quota_pct": cpu_quota_pct}
    args = [sys.executable, "-E", "-B", "-S", str(Path(__file__).resolve()), "submit-compiler"]
    with subprocess.Popen(args, cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)) as p:
        try:
            stdout, stderr = p.communicate(input=stable_bytes(spec), timeout=timeout + wait_s + 50)
        except subprocess.TimeoutExpired:
            p.kill()
            p.communicate()
            raise
    if p.returncode or not stdout.strip():
        raise RuntimeError("Swarm client returned no receipt: " + stderr.decode(errors="replace")[-400:])
    receipt = json.loads(stdout)
    if not receipt.get("ok") or receipt.get("state") != "completed":
        raise RuntimeError("Swarm " + str(receipt.get("state")) + ": " + str(receipt.get("error")))
    if receipt.get("snapshot") != snapshot_digest:
        raise ValueError("The Swarm snapshot differs from the selected build workspace")
    identity = {k: receipt[k] for k in
                ("request_id", "attempt_id", "source_delivery", "delivery", "snapshot", "target", "ssh_route",
                 "timing", "timings", "process_wall_ms", "reaped_child_cpu_ms", "elapsed_end_to_end_ms") if k in receipt}
    identity["client_pid"] = p.pid
    if site == "remote":
        identity["admission"] = verified_admission(receipt, cpu_quota_pct)
    item = receipt["artifacts"]["result.json"]
    body = base64.b64decode(item["base64"], validate=True)
    if len(body) != item["bytes"] or hashlib.sha256(body).hexdigest() != item["sha256"]:
        raise ValueError("Peer returned a corrupt artifact")
    return json.loads(receipt["stdout"]), body, identity


def measure(site, payload, peer, timeout, *, compiler=None, bytecode_oracle=None, cpu_quota_pct=None):
    if cpu_quota_pct is not None and (site != "remote" or type(cpu_quota_pct) is not int or not 1 <= cpu_quota_pct <= 100):
        raise ValueError("The peer CPU quota must be an integer from 1 to 100 for a remote build")
    compiler = compiler or sys.executable
    stage = payload.parent / "guarded-inputs"
    raw = payload.read_bytes()
    if raw != (stage / "input.json").read_bytes():
        raise ValueError("The staged input changed")
    data = json.loads(raw)
    source_hash = hashlib.sha256(stable_bytes(data["files"])).hexdigest()
    units = data["rounds"] * len(data["files"])
    product = [source_hash, units]
    if bytecode_oracle is not None:
        product.append(bytecode_oracle)
    expected_body = stable_bytes(product)
    expected_result = hashlib.sha256(expected_body).hexdigest()
    expected_input = hashlib.sha256(raw).hexdigest()
    nonce = "cad-measured-cold-pair-" + uuid.uuid4().hex
    snapshot_digest = None
    if site != "local":
        sys.path.insert(0, str(ROOT))
        from chimera_tp.platform.build_snapshot import capture
        snapshot_digest = capture(stage, include_data=False)["digest"]
    barrier = threading.Barrier(2, timeout=8)

    def request(state_dir):
        barrier.wait()
        if site == "local":
            return local(stage, timeout, compiler)
        return shared(site, stage, timeout, peer, nonce, snapshot_digest, compiler,
                      30 if bytecode_oracle else 0, state_dir, cpu_quota_pct)

    # Share one cold sender registry. A deferred fixture ticket expires with this measurement.
    with tempfile.TemporaryDirectory(prefix="cad-swarm-state-") as state_dir, ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(request, state_dir) for _ in range(2)]
        replies = [f.result() for f in futures]
    for report, body, _ in replies:
        if (body != expected_body or report["result_sha256"] != expected_result or
            report["input_sha256"] != expected_input or report["digest"] != source_hash or report["units"] != units):
            raise ValueError("Compiled result or input did not match the reference")
    receipts = [identity for _, _, identity in replies]
    attempts = {r["attempt_id"] for r in receipts}
    distinct = {r[0]["compiler_instance"]: r[0] for r in replies}
    if (len(distinct) != (2 if site == "local" else 1)
            or not all(re.fullmatch(r"[a-f0-9]{32}", k) for k in distinct)
            or len({r["compiler_pid"] for r in distinct.values()}) != len(distinct)):
        raise ValueError("Compiler process identities disagree with the chosen placement")
    if site != "local":
        if (len(attempts) != 1 or not all(re.fullmatch(r"[a-f0-9]{32}", r.get(field) or "")
                                          for r in receipts for field in ("attempt_id", "request_id")) or
                len({r["request_id"] for r in receipts}) != 2 or
                len({r["client_pid"] for r in receipts}) != 2 or
                sorted(r.get("source_delivery", "") for r in receipts) != ["executed", "joined"] or
                not any(r.get("delivery") == "executed" for r in receipts) or
                any(r.get("target") != ("local" if site == "local-shared" else peer) for r in receipts)):
            raise ValueError("Two cold agent requests did not overlap and share one fresh build on the selected host")
        if site == "remote" and receipts[0]["admission"] != receipts[1]["admission"]:
            raise ValueError("Senders received different CPU admission for the same build")
    return {"input_sha256": expected_input, "result_sha256": expected_result, "units_per_agent": units,
            "snapshot": snapshot_digest, "requests": len(receipts), "distinct_attempts": len(attempts),
            "compiler_windows_ms": [r[0]["window_ms"] for r in replies],
            "compiler_clock": "linux_monotonic" if site == "remote" else "windows_qpc",
            "compiler_instances": [{"id": k, "pid": r["compiler_pid"], "cpu_s": r["cpu_s"],
                                    "wall_s": r["work_s"], "python": r["python"]} for k, r in distinct.items()],
            "compiler_cpu_s": sum(r["cpu_s"] for r in distinct.values()), "cold_environment_id": nonce,
            "effective_worker_seconds": [r[0]["work_s"] for r in replies], "receipts": receipts}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "local", "local-shared", "remote"))
    parser.add_argument("payload", type=Path)
    parser.add_argument("--peer", default="svhome")
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--compiler", type=Path, help="Use this Windows interpreter for the build")
    parser.add_argument("--verify-bytecode", action="store_true", help="Stage the bytecode-verifying workload")
    parser.add_argument("--cpu-quota-pct", type=int, help="Maximum percent of one CPU for the admitted peer compiler")
    parser.add_argument("--counter-paths", type=Path, help="Private marker directory names for the two hosts")
    parser.add_argument("--bytecode-oracle", type=Path, help="Expected per-module marshal digests")
    args = parser.parse_args()
    if not 1 <= args.timeout <= 300:
        parser.error("Swarm supports timeouts of 1..300 seconds")
    if args.cpu_quota_pct is not None and (args.mode != "remote" or not 1 <= args.cpu_quota_pct <= 100):
        parser.error("--cpu-quota-pct requires a remote build and an integer from 1 to 100")
    expected = json.loads(args.bytecode_oracle.read_text("utf-8")) if args.bytecode_oracle else None
    counters = json.loads(args.counter_paths.read_text("utf-8")) if args.counter_paths else None
    result = (prepare(args.payload, placement=args.verify_bytecode, counters=counters) if args.mode == "prepare" else
              measure(args.mode, args.payload, args.peer, args.timeout, compiler=args.compiler,
                      bytecode_oracle=expected, cpu_quota_pct=args.cpu_quota_pct))
    print(json.dumps(result, ensure_ascii=True))


if __name__ == "__main__":
    if sys.argv[1:] == ["submit-compiler"]:
        print(json.dumps(submit_compiler(**json.load(sys.stdin)), ensure_ascii=True))
    else:
        main()
