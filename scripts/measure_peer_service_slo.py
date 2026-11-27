"""Compare a real svhome service at idle and during fresh, single-slot Guard builds."""

import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import http.client
import json
import math
from pathlib import Path
import re
import shlex
import shutil
import socket
import statistics
import subprocess
import sys
import tempfile
import time
import zlib

import peer_service_probe as probe


ROOT = Path(__file__).resolve().parents[1]
PAYLOAD = Path(probe.__file__).resolve()
sys.path.insert(0, str(ROOT))
from chimera_tp.platform.guarded_build import submit


def utc():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def p95(values):
    return sorted(values)[math.ceil(len(values) * 0.95) - 1]


@contextmanager
def observation_channel(peer):
    with socket.socket() as chooser:
        chooser.bind(("127.0.0.1", 0))
        port = chooser.getsockname()[1]
    blob = base64.b64encode(zlib.compress(PAYLOAD.read_bytes())).decode("ascii")
    entry = f"import base64,zlib;exec(zlib.decompress(base64.b64decode('{blob}')))"
    remote = shlex.join(["python3", "-I", "-B", "-S", "-u", "-c", entry, "observe"])
    command = ["ssh", "-T", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
               "-o", "UpdateHostKeys=no", "-o", "ConnectTimeout=5", "-o", "ExitOnForwardFailure=yes",
               "-o", "ServerAliveInterval=3", "-o", "ServerAliveCountMax=2",
               "-L", f"127.0.0.1:{port}:127.0.0.1:{probe.PORT}", peer, remote]
    proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, encoding="utf-8", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        def request(op=None):
            if op:
                proc.stdin.write(op + "\n")
                proc.stdin.flush()
            body = proc.stdout.readline()
            if not body:
                raise RuntimeError("probe_closed: " + proc.stderr.read()[-350:].strip())
            return json.loads(body)
        yield request, port, request()
    finally:
        if proc.poll() is None:
            proc.stdin.close()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=3)
        for stream in (proc.stdin, proc.stdout, proc.stderr):
            stream.close()


class SampleLimitReached(RuntimeError):
    """Preserve the first out-of-budget observation outside the accepted pairs."""

    def __init__(self, reason, row, limits):
        super().__init__(reason)
        self.observation = row
        self.thresholds = {key: limits[key] for key in
                           ("max_temp_c", "ram_reserve_mib", "psi_cpu_pct", "psi_io_pct", "psi_memory_pct")}
        self.thresholds["linux_http_max_ms"] = 100


class GuardStopped(RuntimeError):
    """Keep the receiver's reason and numeric readings without command output or input data."""

    def __init__(self, receipt):
        super().__init__("guard_" + str(receipt.get("error") or receipt.get("state")))
        admission = receipt.get("admission") or {}
        trip = receipt.get("guard_trip") or admission
        health = trip.get("health") or {}
        health = health.get("health", health)
        policy = admission.get("effective_policy") or {}
        self.record = {key: receipt.get(key) for key in ("request_id", "attempt_id", "state", "error")}
        self.record["reason"] = trip.get("reason")
        self.record["limits_verified"] = admission.get("limits_verified")
        self.record["observations"] = {key: health[key] for key in (
            "available_ram_mib", "available_disk_mib", "temp_c", "load1",
            "psi_some_avg10", "service_p95_ms", "limits") if key in health}
        self.record["thresholds"] = {key: policy[key] for key in (
            "ram_reserve_mib", "disk_reserve_mib", "max_temp_c", "max_load1",
            "psi_cpu_pct", "psi_io_pct", "psi_memory_pct", "service_p95_ms") if key in policy}


def sample(request, port, meta, limits):
    row = request("sample")
    # This health GET originates on the workstation and completes after the last body byte.
    # The kernel loopback probe above opened a different connection on the receiver.
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    try:
        tick = time.perf_counter_ns()
        conn.request("GET", meta["health_path"], headers={"Connection": "close"})
        with conn.getresponse() as res:
            body = res.read(2049)
            elapsed = (time.perf_counter_ns() - tick) / 1e6
            if res.status != 200 or len(body) > 2048 or res.headers.get_content_type() != "application/json":
                raise RuntimeError("workstation_http_contract_failed")
    finally:
        conn.close()
    reply = json.loads(body)
    if reply.get("ok") is not True or not isinstance(reply.get("version"), str) or not reply["version"]:
        raise RuntimeError("workstation_health_body_invalid")
    row.update(request("stamp"), windows_http_ms=round(elapsed, 4))
    host = row["host"]
    if host["cpu_temp_c"] >= limits["max_temp_c"] or host["mem_available_mib"] < limits["ram_reserve_mib"]:
        raise SampleLimitReached("host_temperature_or_memory_stop", row, limits)
    if any(field["avg10_pct"] >= limits["psi_" + kind + "_pct"] for kind, field in host["psi"].items()):
        raise SampleLimitReached("host_pressure_stop", row, limits)
    if max(row["linux_http_ms"].values()) > 100:
        raise SampleLimitReached("dashboard_local_response_over_100_ms_stop", row, limits)
    return row


def idle_block(next_sample):
    for attempt in range(4):
        rows = []
        for _ in range(8):
            row = next_sample()
            if row["guest_before"] or row["guest_after"]:
                break
            rows.append(row)
            time.sleep(0.20)
        if len(rows) == 8:
            return rows, attempt
        time.sleep(2 ** (attempt + 1))
    raise RuntimeError("receiver_still_occupied_during_baseline")


def loaded_block(executor, workspace, args, next_sample):
    retries = []
    policy = {"cpu_quota_pct": args.cpu_quota_pct} if args.cpu_quota_pct is not None else None
    for attempt in range(4):
        future = executor.submit(submit, f"python3 -I -B -S fixture.py compile {args.rounds}",
                                 cwd=workspace, peer=args.peer, reuse=False, timeout_s=25,
                                 admission_policy=policy)
        samples = []
        while not future.done():
            samples.append(next_sample())
            time.sleep(0.20)
        receipt = future.result()
        if receipt.get("state") == "deferred" and receipt.get("error") == "guest_slot_busy":
            retries.append(receipt["request_id"])
            time.sleep(2 ** (attempt + 1))
            continue
        if not receipt.get("ok") or not receipt.get("admission", {}).get("limits_verified"):
            raise GuardStopped(receipt)
        work = json.loads(receipt["stdout"])
        selected = [r for r in samples if work["start_ns"] <= r["start_ns"] and r["end_ns"] <= work["end_ns"]]
        if len(selected) < 2 or any(not r["guest_before"] or not r["guest_after"] for r in selected):
            raise RuntimeError("too_few_verified_in_build_reads")
        guard = receipt["admission"]
        info = {"request_id": receipt["request_id"], "attempt_id": receipt["attempt_id"],
                "input_snapshot": receipt["snapshot"], "delivery": receipt["delivery"], "admitted": guard["accepted"],
                "attempts_deferred_busy": retries, "limits_verified": guard["limits_verified"],
                "policy": {k: v for k, v in guard["effective_policy"].items() if k != "service_urls"},
                "service_checks": [{"url": url, "p95_ms": value} for url, value in
                                   receipt["runtime_guard"]["worst_service_p95_ms"].items()],
                "runtime_health_samples": receipt["runtime_guard"]["completed_samples"],
                "cgroup_limits": guard["health"]["limits"], "work": work,
                "samples_outside_compile_window": len(samples) - len(selected)}
        if info["delivery"] != "executed" or not info["admitted"] or info["runtime_health_samples"] < 1:
            raise RuntimeError("expected_fresh_admitted_monitored_build")
        if args.cpu_quota_pct is not None:
            actual = info["cgroup_limits"].get("cpu_quota_pct")
            if actual is None or not 0 < actual <= args.cpu_quota_pct:
                raise RuntimeError("guest_cpu_quota_not_applied")
        return selected, info
    raise RuntimeError("guard_remained_busy")


def latencies(row):
    return {"linux_health_ms": row["linux_http_ms"]["health"],
            "linux_asset_ms": row["linux_http_ms"]["asset"], "windows_health_ms": row["windows_http_ms"]}


def evenly_spaced(rows, count):
    return [rows[round(i * (len(rows) - 1) / (count - 1))] for i in range(count)]


def summarize(pairs, policy, target_pairs):
    sites = ("idle", "build")
    balanced = {s: [] for s in sites}
    paired_deltas = []
    for pair in pairs:
        count = min(len(pair[s]) for s in sites)
        selected = {s: [latencies(r) for r in evenly_spaced(pair[s], count)] for s in sites}
        paired_deltas.append({key: round(p95([r[key] for r in selected["build"]]) -
                                         p95([r[key] for r in selected["idle"]]), 4)
                              for key in selected["build"][0]})
        for s in sites:
            balanced[s].extend(selected[s])
    if not pairs:
        return {"completed_pairs": 0, "eligible_for_gate": False, "experimental_gate_pass": None}
    keys = balanced["idle"][0]
    heads = {s: {k: p95([a[k] for a in balanced[s]]) for k in keys} for s in sites}
    deltas = {k: round(heads["build"][k] - heads["idle"][k], 4) for k in keys}
    host_stats = {}
    for site in sites:
        blocks = [p[site] for p in pairs]
        rows = [row["host"] for block in blocks for row in block]
        host_stats[site] = {"min_mem_available_mib": min(r["mem_available_mib"] for r in rows),
                            "max_cpu_temp_c": max(r["cpu_temp_c"] for r in rows),
                            "max_psi_some_avg10_pct": {k: max(r["psi"][k]["avg10_pct"] for r in rows)
                                                       for k in rows[0]["psi"]},
                            "observed_device_write_bytes": {
                                k: sum(b[-1]["host"]["device_write_bytes"][k] - b[0]["host"]["device_write_bytes"][k]
                                       for b in blocks) for k in rows[0]["device_write_bytes"]}}
    enough = len(pairs) == target_pairs and target_pairs >= 10 and len(balanced["idle"]) >= 20
    gate = all(heads["build"][k] <= policy["linux_absolute_ms"] and deltas[k] <= policy["linux_added_ms"]
               for k in ("linux_health_ms", "linux_asset_ms"))
    return {"completed_pairs": len(pairs), "raw_counts": {s: sum(len(p[s]) for p in pairs) for s in sites},
            "balanced_count_each": len(balanced["idle"]), "p95": heads, "build_minus_idle_p95_ms": deltas,
            "median_paired_p95_difference_ms": {k: round(statistics.median(d[k] for d in paired_deltas), 4)
                                                for k in keys}, "paired_p95_differences_ms": paired_deltas,
            "host": host_stats, "eligible_for_gate": enough, "experimental_gate_pass": gate if enough else None}


def run(args, evidence):
    from chimera_tp.platform.peer_guard import DEFAULTS

    with (observation_channel(args.peer) as (request, port, meta),
          tempfile.TemporaryDirectory(prefix="chimera-service-slo-") as temp,
          ThreadPoolExecutor(max_workers=1) as pool):
        evidence["service"] = meta
        workdir = Path(temp)
        shutil.copyfile(PAYLOAD, workdir / "fixture.py")
        def next_sample():
            return sample(request, port, meta, DEFAULTS)
        next_sample()  # Warm application route caches and the existing SSH channel.
        for i in range(args.pairs):
            order = ["idle", "build"] if i % 2 == 0 else ["build", "idle"]
            pair = {"pair": i + 1, "order": order}
            for phase in order:
                if phase == "idle":
                    pair[phase], pair["baseline_restarts_busy"] = idle_block(next_sample)
                else:
                    pair[phase], pair["guard"] = loaded_block(pool, workdir, args, next_sample)
                time.sleep(0.8)
            if evidence["pairs"]:
                previous = evidence["pairs"][0]["guard"]["work"]
                current = pair["guard"]["work"]
                if any(previous[k] != current[k] for k in ("objects", "source_hashes", "python", "rounds")):
                    raise RuntimeError("compile_inputs_or_bytecode_changed")
            evidence["pairs"].append(pair)
            print(f"Pair {i + 1}/{args.pairs}: idle={len(pair['idle'])}, inside build={len(pair['build'])}", flush=True)
        evidence["service_final"] = request("identity")
        if not evidence["service_final"]["same_service"]:
            raise RuntimeError("dashboard_changed_during_trial")


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--peer", default="svhome")
    cli.add_argument("--pairs", default=10, type=int)
    cli.add_argument("--rounds", default=70, type=int)
    cli.add_argument("--cpu-quota-pct", type=int, choices=range(1, 101), metavar="1..100",
                     help="Optional guest CPU cap as a percentage of one core")
    cli.add_argument("--out", type=Path, default=ROOT / "tasks/peer_service_slo.json")
    args = cli.parse_args()
    if not (sys.platform == "win32" and re.fullmatch(r"[A-Za-z0-9][a-zA-Z0-9_.-]*", args.peer)
            and 1 <= args.pairs <= 15 and 10 <= args.rounds <= 180):
        cli.error("Use the Windows workstation, a configured SSH alias, 1–15 pairs and 10–180 compile rounds")
    evidence = {"schema": 1, "started_utc": utc(), "peer": args.peer, "target_pairs": args.pairs,
                "requested_cpu_quota_pct": args.cpu_quota_pct,
                "probe_sha256": hashlib.sha256(PAYLOAD.read_bytes()).hexdigest(),
                "policy": {"type": "experimental_only", "linux_absolute_ms": 20, "linux_added_ms": 5,
                           "required_http_error_count": 0, "production_slo": None},
                "method": {
                    "linux": "Fresh loopback TCP GET, through last body byte. Health JSON and homepage-linked CSS digest verified.",
                    "windows": "Fresh workstation TCP GET of health JSON through an existing authenticated SSH forward to the same loopback endpoint. Includes network, forward and response bytes, excludes SSH setup.",
                    "time": "Each three-GET row is enclosed by timestamps from the same Linux monotonic clock as the compiler. Fresh jobs only. Idle rows require an unpopulated receiver guest at both ends.",
                    "percentile": "Nearest rank over equal sample counts within each pair, evenly spaced by index. Source-order A/B, B/A, warm-cache, polling pause 200 ms. First/last host counters define each phase window.",
                    "workload": "Four receiver-installed public CPython modules are compiled each round. Four checked-hash pyc files are produced in the isolated job workspace and hash-checked across all jobs.",
                    "attribution": "Block counters cover the host partition and its containing disk; do not add devices. Host page cache/writeback and other services affect these windows. Process write_bytes is kernel accounting within compiler boundaries. An absent cgroup io.stat is null.",
                    "service_scope": "Radar HTTP handling and one static frontend asset. Long-running dashboard operations, external traffic and user-selected production SLO remain unmeasured."},
                "pairs": []}
    try:
        run(args, evidence)
        evidence["status"] = "completed"
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        evidence.update(status="stopped", reason=str(exc))
        if isinstance(exc, SampleLimitReached):
            evidence["stop_observation"] = exc.observation
            evidence["stop_thresholds"] = exc.thresholds
        if isinstance(exc, GuardStopped):
            evidence["stop_guard"] = exc.record
    evidence["finished_utc"] = utc()
    summary = summarize(evidence["pairs"], evidence["policy"], args.pairs)
    if evidence["status"] != "completed":
        summary.update(eligible_for_gate=False, experimental_gate_pass=None)
    evidence["summary"] = summary
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=args.out.parent, delete=False) as tmp:
        json.dump(evidence, tmp, indent=2, ensure_ascii=True, allow_nan=False)
        tmp.write("\n")
    Path(tmp.name).replace(args.out)
    print(json.dumps({"status": evidence["status"], "reason": evidence.get("reason"), "summary": summary,
                      "evidence": str(args.out)}, ensure_ascii=True))
    return int(evidence["status"] != "completed" or summary["experimental_gate_pass"] is False)


if __name__ == "__main__":
    raise SystemExit(main())
