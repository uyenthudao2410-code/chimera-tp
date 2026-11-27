"""Replay one frozen Sentinel input on private Linux daemons with an alternating A/B order.

Both source roots must contain the complete package and native backend. Snapshots,
daemon state and changed logs live in tmpfs. The result includes counts and hashes.
"""

import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import time


TAIL_BYTES = 2 * 1024 * 1024
PASSES = ("cold", "unchanged", "one_changed")
SOURCES = ("chimera_tp/active_pipe.py", "chimera_tp/sentinel.py")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def fingerprint(value):
    return digest(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


def snapshot(db_path, destination):
    with closing(sqlite3.connect(db_path.resolve(strict=True).as_uri() + "?mode=ro", uri=True, timeout=2)) as db:
        row = db.execute("SELECT ts_local, summary_json FROM scans ORDER BY id DESC LIMIT 1").fetchone()
    if not row:
        raise ValueError("no completed Sentinel scan")
    records = json.loads(row[1])["logs_scanned"]
    if not 1 <= len(records) <= 12:
        raise ValueError("expected one to twelve scanned files")
    files = []
    for index, record in enumerate(records):
        with Path(record["path"]).open("rb") as stream:
            end = os.fstat(stream.fileno()).st_size
            count = min(end, TAIL_BYTES + 1)
            stream.seek(end - count)
            data = stream.read(count)
            if len(data) != count:
                raise ValueError("log truncated during capture")
        path = destination / f"{index:02d}.log"
        path.write_bytes(data)
        # Reproduce discovery order on every filesystem and in both arms.
        stamp = (1700000000 - index) * 10**9
        os.utime(path, ns=(stamp, stamp))
        files.append({"name": path.name, "bytes": len(data), "sha256": digest(data)})
    return {"source_scan_local": row[0], "files": files, "sha256": fingerprint(files)}


def prepare_imports(source, destination):
    """Give both daemons compiled top-level package modules without touching either checkout."""
    import py_compile

    package = destination / "chimera_tp"
    package.mkdir(parents=True)
    for entry in (source / "chimera_tp").iterdir():
        if entry.name == "__pycache__":
            continue
        local = package / entry.name
        local.symlink_to(entry.resolve(strict=True))
        if entry.is_file() and entry.suffix == ".py":
            py_compile.compile(str(local), doraise=True)
    for name in ("scripts", "native", "plugins", "bin"):
        (destination / name).symlink_to((source / name).resolve(strict=True))
    return sum(1 for _ in (package / "__pycache__").glob("*.pyc"))


def trial(root, fixture):
    sys.path.insert(0, str(root))
    from chimera_tp.autopilot import OpsConfig
    from chimera_tp.dashboard import ChimeraDaemon
    from scripts.measure_daemon_cli import request
    from scripts.measure_vsa_heap import rss

    home = Path.home()
    logs = home / "logs"
    shutil.copytree(fixture, logs)
    config = OpsConfig(node_name="sentinel-replay", role="server", dashboard_bind="127.0.0.1:0",
                       beam_port=0, rpc_v4_port=0, rpc_v6_port=-1, query_port=0,
                       immortal_v4_port=0, immortal_v6_port=-1, warp_port=-1, edge_proxy_port=-1,
                       nat_punch_port=0, phantom_enabled=False, peer_ipv4="", peer_ipv6="",
                       allowed_query_roots=[str(logs)], search_roots=[], edge_targets={},
                       watched_query_file="@synthetic", sentinel_webhook_url="", daily_time="99:99")
    daemon = ChimeraDaemon(config=config, ops_dir=home / "ops", auto_seed_on_empty=False).start()
    try:
        port = daemon.http_addr[1]
        beacon = request(port, "/.well-known/chimera.json")
        if beacon["pid"] != os.getpid() or beacon["node_name"] != config.node_name:
            raise RuntimeError("wrong daemon for replay")
        if not request(port, "/api/health").get("ok"):
            raise RuntimeError("private health check failed")
        idle = rss()
        samples = []
        for kind in PASSES:
            if kind == "one_changed":
                largest = max(logs.glob("*.log"), key=lambda p: p.stat().st_size)
                with largest.open("ab") as stream:
                    stream.write(b"\nCHIMERA sentinel-replay WARN revised fixture\n")
            start_cpu, start = time.process_time_ns(), time.perf_counter_ns()
            summary = daemon.sentinel.scan(config, tail_bytes=TAIL_BYTES)
            elapsed = (time.perf_counter_ns() - start) / 1e6
            cpu = (time.process_time_ns() - start_cpu) / 1e6
            stable = {
                "logs": [{k: v for k, v in r.items() if k != "path"} for r in summary["logs_scanned"]],
                "alerts": summary["alerts"],
                "suppressed": summary["suppressed_repeats"], "alert_count": summary["alert_count"],
                "status": summary["status"],
            }
            if len(stable["logs"]) != len(list(fixture.glob("*.log"))):
                raise RuntimeError("incomplete private scan")
            samples.append({"pass": kind, "ms": round(elapsed, 3), "cpu_ms": round(cpu, 3),
                            "memory_bytes": rss(), "lines": sum(r["lines"] for r in stable["logs"]),
                            "reports_sha256": fingerprint(stable)})
        return {"idle_bytes": idle, "samples": samples}
    finally:
        daemon.close()


def run(args):
    roots = {"baseline": args.baseline.resolve(strict=True), "candidate": args.candidate.resolve(strict=True)}
    if roots["baseline"] == roots["candidate"]:
        raise ValueError("A/B requires two distinct source roots")
    source_hashes = {arm: {n: digest((root / n).read_bytes()) for n in SOURCES} for arm, root in roots.items()}
    with tempfile.TemporaryDirectory(prefix="chimera-sentinel-ab-", dir="/dev/shm") as directory:
        folder = Path(directory)
        prepared = {arm: folder / arm for arm in roots}
        pyc_counts = {arm: prepare_imports(root, prepared[arm]) for arm, root in roots.items()}
        if len(set(pyc_counts.values())) != 1:
            raise RuntimeError("different precompiled package module counts")
        fixture = folder / "snapshot"
        fixture.mkdir()
        captured = snapshot(args.sentinel_db, fixture)
        trials = []
        for pair in range(args.pairs):
            for arm in (("baseline", "candidate") if pair % 2 == 0 else ("candidate", "baseline")):
                with tempfile.TemporaryDirectory(dir=folder) as home:
                    keys = ("HOME", "TMPDIR", "XDG_STATE_HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME")
                    env = {**os.environ, **dict.fromkeys(keys, home), "MALLOC_ARENA_MAX": "2"}
                    child = subprocess.run(
                        [sys.executable, "-I", "-B", "-S", str(Path(__file__).resolve()), "--trial-root",
                         str(prepared[arm]), "--fixture", str(fixture)], cwd=home, env=env,
                        capture_output=True, text=True, timeout=45,
                    )
                    if child.returncode:
                        raise RuntimeError(child.stderr[-1800:] or f"trial exited {child.returncode}")
                    trials.append({"pair": pair + 1, "arm": arm, **json.loads(child.stdout)})
        for item in captured["files"]:
            if digest((fixture / item["name"]).read_bytes()) != item["sha256"]:
                raise RuntimeError("snapshot changed during replay")

    summary = {}
    for index, name in enumerate(PASSES):
        if len({entry["samples"][index]["reports_sha256"] for entry in trials}) != 1:
            raise RuntimeError(f"different logs, alerts or suppression counts on {name}")
        summary[name] = {}
        for arm in roots:
            rows = [t["samples"][index] for t in trials if t["arm"] == arm]
            summary[name][arm] = {
                "wall_ms_median": statistics.median(s["ms"] for s in rows),
                "cpu_ms_median": statistics.median(s["cpu_ms"] for s in rows),
                "rss_bytes_median": statistics.median(s["memory_bytes"]["VmRSS"] for s in rows),
                "peak_bytes_max": max(s["memory_bytes"]["VmHWM"] for s in rows),
            }
    return {"schema": "chimera.sentinel-scan-replay/1", "utc": datetime.now(timezone.utc).isoformat(),
            "scope": "private Linux daemons with frozen log tails; no service or webhook probes",
            "python": sys.version.split()[0], "source_sha256": source_hashes, "snapshot": captured,
            "collector_sha256": digest(Path(__file__).read_bytes()), "pairs": args.pairs,
            "private_pyc_counts": pyc_counts,
            "trials": trials, "summary": summary}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--sentinel-db", type=Path)
    parser.add_argument("--pairs", type=int, choices=range(1, 6), default=3)
    parser.add_argument("--trial-root", type=Path)
    parser.add_argument("--fixture", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if not sys.platform.startswith("linux"):
        parser.error("measurement requires Linux /proc and tmpfs")
    if args.trial_root and args.fixture:
        result = trial(args.trial_root.resolve(strict=True), args.fixture.resolve(strict=True))
    elif args.baseline and args.candidate and args.sentinel_db:
        result = run(args)
    else:
        parser.error("supply both source roots and the live sentinel database")
    if args.out:
        with args.out.open("x", encoding="utf-8") as output:
            json.dump(result, output, indent=2)
            output.write("\n")
    else:
        print(json.dumps(result))
