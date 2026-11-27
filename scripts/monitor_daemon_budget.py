"""Record a 24-hour, same-PID kernel high-water test on the two serving nodes."""

import argparse
from datetime import datetime, timezone
import hashlib
import http.client
import json
import os
from pathlib import Path
import subprocess
import sys
import time

if __package__:
    from . import verify_node_source_parity as parity
else:
    # Isolated Python excludes the script directory; keep the sibling verifier resolvable.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import verify_node_source_parity as parity


DAY = 24 * 60 * 60
LIMIT = 80 * 1024**2
DISCOVERY = "/.well-known/chimera.json"
SOURCE_INTERVAL = 3600


def local_json(port, path):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=4)
    try:
        connection.request("GET", path)
        reply = connection.getresponse()
        if reply.status != 200:
            raise OSError(f"{path}: HTTP {reply.status}")
        return json.loads(reply.read(256 * 1024))
    finally:
        connection.close()


def peer_beacon():
    try:
        client = local_json(9780, "/api/phantom/status")["client"]
        port = client["listeners"]["9780"]
        if client["connected"] and not client["pong_stale"] and type(port) is int and 0 < port < 65536:
            peer = local_json(port, DISCOVERY)
            if peer.get("node_name") == "svhome":
                return peer, "phantom"
    except (KeyError, ValueError, OSError, http.client.HTTPException):
        pass
    # The management alias remains usable across a reconnect of the data tunnel.
    code = ("import urllib.request as u; "
            "r=u.build_opener(u.ProxyHandler({})).open("
            "'http://127.0.0.1:9780/.well-known/chimera.json',timeout=4); "
            "import sys; sys.stdout.buffer.write(r.read(262144))")
    proc = subprocess.run(
        ["ssh", "-T", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
         "-o", "ConnectTimeout=4", "svhome", "python3 -I -B -S -"],
        input=code.encode(), capture_output=True, check=True, timeout=12,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return json.loads(proc.stdout), "ssh"


def readings():
    local = local_json(9780, DISCOVERY)
    remote, route = peer_beacon()
    result = {}
    for expected, info in (("win-desktop", local), ("svhome", remote)):
        memory = info["zero_weight"]
        if info["node_name"] != expected or not info["ok"] or not info["started_at"]:
            raise ValueError("node identity or health mismatch")
        rss, peak = memory["daemon_rss_bytes"], memory["daemon_peak_rss_bytes"]
        if not 0 < rss <= peak:
            raise ValueError(f"{expected}: invalid kernel memory counters")
        result[expected] = {
            "pid": info["pid"], "started_at": info["started_at"], "version": info["package_version"],
            "rss_bytes": rss, "peak_bytes": peak, "verified": info["evidence_summary"]["verified"],
        }
    return result, route


def verify_release_sources(rollout, nodes):
    """Compare disk bytes in the serving PIDs' mapped roots with the accepted release."""
    windows_root = parity.windows_runtime_root(nodes["win-desktop"]["pid"])
    linux = parity.read_peer("svhome")
    expected = rollout["source_sha256"]
    linux_node = rollout["nodes"]["svhome"]
    windows_node = rollout["nodes"]["win-desktop"]
    if windows_root != Path(windows_node["root"]) or linux["root"] != linux_node["root"]:
        raise ValueError("serving release directory changed")
    if linux["pid"] != nodes["svhome"]["pid"] or linux["node"] != "svhome":
        raise ValueError("Linux PID changed during source verification")
    for host, actual in (("win-desktop", parity.inventory(windows_root)), ("svhome", linux["files"])):
        if actual != expected:
            changed = sorted(p for p in actual.keys() | expected.keys() if actual.get(p) != expected.get(p))
            raise ValueError(f"{host}: release source changed: {', '.join(changed[:3])}")
    native = rollout["native_sha256"]
    dll = windows_root / "chimera_tp" / "_chimera_core.dll"
    if hashlib.sha256(dll.read_bytes()).hexdigest() != native["win-desktop"]:
        raise ValueError("Windows native library changed")
    if linux["mapped_native_sha256"] != native["svhome"]:
        raise ValueError("Linux native library changed")


def run(args):
    path = args.out.resolve()
    journal = path.with_suffix(".jsonl")
    if path.exists():
        raise FileExistsError(path)
    required = {"win-desktop": args.windows_pid, "svhome": args.linux_pid}
    rollout = None
    next_source_check = 0
    reattach = args.reattach
    if reattach and not args.rollout:
        raise ValueError("reattachment requires a rollout receipt")
    if args.rollout:
        content = args.rollout.read_bytes()
        rollout = json.loads(content)
        if (rollout["schema"] != "chimera.workstation-rollout/1" or rollout["release"] != args.release
                or not rollout["source_sha256"] or not all(rollout["native_sha256"].get(k) for k in required)
                or (not reattach and any(rollout["nodes"][k]["pid"] != pid for k, pid in required.items()))):
            raise ValueError("rollout receipt does not match the requested soak")
    identities = {}
    previous_peaks = {}
    last_success = start = time.monotonic()
    next_tick = start
    first_sample = None
    report = {
        "schema": "chimera.live-daemon-soak/1", "release": args.release, "expected_pids": required,
        "monitor_pid": os.getpid(), "started_utc": datetime.now(timezone.utc).isoformat(),
        "required_seconds": DAY, "interval_seconds": args.interval, "exclusive_limit_bytes": LIMIT,
        "samples": 0, "missed": 0, "state": "running", "journal": journal.name,
    }
    if rollout:
        report.update(rollout_receipt=args.rollout.name, rollout_sha256=hashlib.sha256(content).hexdigest(),
                      source_check_interval_seconds=SOURCE_INTERVAL, source_checks=0)
        report["new_window_after_restart"] = reattach
    # The exclusive journal creation prevents a second observer overwriting this run.
    with journal.open("x", encoding="utf-8", buffering=1) as stream:
        while True:
            stamp = datetime.now(timezone.utc).isoformat()
            row = {"utc": stamp}
            try:
                nodes, route = readings()
                row.update(nodes=nodes, peer_transport=route)
                tick = time.monotonic()
                if tick - last_success > 2 * args.interval + 20:
                    raise ValueError("observation_gap")
                for name, node in nodes.items():
                    ident = (node["pid"], node["started_at"])
                    if node["pid"] != required[name] or identities.setdefault(name, ident) != ident:
                        raise ValueError(f"{name}: PID or start time changed")
                    if rollout and node["version"] != rollout["live"][name]["version"]:
                        raise ValueError(f"{name}: package version differs from rollout receipt")
                    if rollout and not reattach and node["started_at"] != rollout["nodes"][name]["started_at"]:
                        raise ValueError(f"{name}: start time differs from rollout receipt")
                    if node["peak_bytes"] < previous_peaks.get(name, 0):
                        raise ValueError(f"{name}: kernel high-water counter decreased")
                    previous_peaks[name] = node["peak_bytes"]
                report["samples"] += 1
                report["latest"] = nodes
                if max(previous_peaks.values()) >= LIMIT:
                    raise ValueError("kernel_peak_reached_budget")
                complete = first_sample is not None and tick - first_sample >= DAY
                if rollout and (tick >= next_source_check or complete):
                    verify_release_sources(rollout, nodes)
                    next_source_check = tick + SOURCE_INTERVAL
                    report["source_checks"] += 1
                    row["release_sources_verified"] = True
                last_success = tick
                if first_sample is None:
                    first_sample = tick
                if complete:
                    report["state"] = "passed"
            except (OSError, subprocess.SubprocessError, http.client.HTTPException) as exc:
                report["missed"] += 1
                row["error"] = str(exc)[:240]
                if time.monotonic() - last_success > 2 * args.interval + 20:
                    report.update(state="failed", reason="observation_gap")
            except (KeyError, ValueError, TypeError) as exc:
                report.update(state="failed", reason=str(exc))
                row["error"] = str(exc)
            stream.write(json.dumps(row, ensure_ascii=True) + "\n")
            stream.flush()
            report.update(updated_utc=stamp, observed_seconds=round(last_success - first_sample, 3)
                          if first_sample is not None else 0, maximum_bytes=dict(previous_peaks))
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            os.replace(tmp, path)
            if report["state"] != "running":
                return 0 if report["state"] == "passed" else 1
            next_tick += args.interval
            time.sleep(max(0, next_tick - time.monotonic()))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--release", required=True)
    parser.add_argument("--rollout", type=Path, help="Accepted rollout receipt for hourly and final source checks")
    parser.add_argument("--reattach", action="store_true",
                        help="Start a fresh 24-hour window after a restart of the verified release")
    parser.add_argument("--windows-pid", type=int, required=True)
    parser.add_argument("--linux-pid", type=int, required=True)
    parser.add_argument("--interval", type=int, choices=range(15, 301), metavar="15..300", default=120)
    raise SystemExit(run(parser.parse_args()))
