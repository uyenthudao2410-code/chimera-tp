"""Measure Linux heap reclamation after a private daemon replays a real Tquota export.

Only the parent reads the two live inputs, once. The export, SQLite copies and
child homes stay in tmpfs. The result contains sizes, hashes and OS counters.
"""

import argparse
from contextlib import closing
import ctypes
import gc
import hashlib
import http.client
import http.server
import json
import os
from pathlib import Path
import shutil
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import threading
import time


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rss():
    fields = {}
    for line in Path("/proc/self/status").read_text().splitlines():
        key, _, value = line.partition(":")
        if key in {"VmHWM", "VmRSS", "RssAnon"}:
            fields[key] = int(value.split()[0]) * 1024
    return fields


def replay_trial(args):
    root = args.root.resolve(strict=True)
    home = Path.home()
    sys.path.insert(0, str(root))
    from chimera_tp.autopilot import OpsConfig
    from chimera_tp.dashboard import ChimeraDaemon
    from scripts.measure_daemon_cli import request

    ops = home / "ops"
    ops.mkdir()
    shutil.copyfile(args.seed, ops / "vsa_memory.db")
    config = OpsConfig(node_name="heap-trial", role="server", dashboard_bind="127.0.0.1:0",
                       beam_port=0, rpc_v4_port=0, rpc_v6_port=-1, query_port=0,
                       immortal_v4_port=0, immortal_v6_port=-1, warp_port=-1, edge_proxy_port=-1,
                       nat_punch_port=0, phantom_enabled=False, peer_ipv4="", peer_ipv6="",
                       allowed_query_roots=[str(home)], search_roots=[], edge_targets={},
                       tquota_admin_url=f"http://127.0.0.1:{args.port}", daily_time="99:99")
    trim = ctypes.CDLL(None).malloc_trim
    trim.argtypes, trim.restype = [ctypes.c_size_t], ctypes.c_int
    daemon = ChimeraDaemon(config=config, ops_dir=ops, auto_seed_on_empty=False).start()
    try:
        port = daemon.http_addr[1]
        beacon = request(port, "/.well-known/chimera.json")
        if beacon["node_name"] != "heap-trial" or beacon["pid"] != os.getpid():
            raise RuntimeError("not the private daemon")
        if not request(port, "/api/health").get("ok"):
            raise RuntimeError("private daemon health")
        baseline = rss()
        passes = []
        for _ in range(2):
            report = request(port, "/api/overmind/hippocampus/ingest-tquota",
                             {"tquota_admin_url": config.tquota_admin_url, "limit": 300})
            if not report.get("ok") or not 0 < report["stored_count"] <= 300:
                raise RuntimeError("private ingest failed")
            before = rss()
            started = time.perf_counter()
            gc.collect()
            after_gc = rss()
            trim_start = time.perf_counter()
            released = trim(0) if args.arm == "gc_and_trim" else None
            elapsed_trim = (time.perf_counter() - trim_start) * 1000
            elapsed_total = (time.perf_counter() - started) * 1000
            after = rss()
            time.sleep(.25)
            quiet = rss()
            passes.append({"stored": report["stored_count"], "changed": report["changed_count"],
                           "items": report["total_items"], "ingest_ms": report["elapsed_ms"],
                           "before": before, "after_gc": after_gc, "after": after, "quiet": quiet,
                           "trim_result": released, "trim_ms": round(elapsed_trim, 3),
                           "collection_ms": round(elapsed_total, 3)})
        if passes[1]["changed"] or passes[1]["stored"] != passes[0]["stored"]:
            raise RuntimeError("unstable private export")
        return {"arm": args.arm, "pid": os.getpid(), "baseline": baseline, "passes": passes}
    finally:
        daemon.close()


def measure(args):
    root = args.root.resolve(strict=True)
    db_file = Path.home() / ".chimera_ops/vsa_memory.db"
    live = http.client.HTTPConnection("127.0.0.1", 12504, timeout=5)
    try:
        live.request("GET", "/api/thought-briefs/export?limit=300")
        response = live.getresponse()
        raw = response.read(8 * 1024**2 + 1)
        if response.status != 200 or len(raw) > 8 * 1024**2 or not json.loads(raw).get("items"):
            raise RuntimeError("export unavailable, empty or too large")
    finally:
        live.close()

    class Replay(http.server.BaseHTTPRequestHandler):
        calls = 0

        def do_GET(self):
            if self.path != "/api/thought-briefs/export?limit=300":
                self.send_error(404)
                return
            type(self).calls += 1
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *_):
            pass

    trials = []
    with tempfile.TemporaryDirectory(dir="/dev/shm", prefix="chimera-vsa-heap-") as folder:
        temporary = Path(folder)
        seed = temporary / "snapshot.sqlite"
        with closing(sqlite3.connect(db_file.as_uri() + "?mode=ro", uri=True, timeout=2)) as src:
            src.execute("PRAGMA query_only=ON")
            with closing(sqlite3.connect(seed)) as dst:
                src.backup(dst, pages=128)
        seed_hash = sha(seed)
        with http.server.HTTPServer(("127.0.0.1", 0), Replay) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                for pair in range(args.pairs):
                    arms = ("gc_only", "gc_and_trim") if pair % 2 == 0 else ("gc_and_trim", "gc_only")
                    for arm in arms:
                        with tempfile.TemporaryDirectory(dir=folder) as child_home:
                            keys = ("HOME", "TMPDIR", "XDG_STATE_HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME",
                                    "XDG_CACHE_HOME")
                            env = {**os.environ, **dict.fromkeys(keys, child_home), "MALLOC_ARENA_MAX": "2"}
                            cmd = [sys.executable, "-I", "-B", "-S", str(Path(__file__).resolve()),
                                   "--root", str(root), "--seed", str(seed), "--arm", arm,
                                   "--port", str(server.server_port)]
                            completed = subprocess.run(cmd, cwd=child_home, env=env, capture_output=True,
                                                       text=True, timeout=45)
                            if completed.returncode:
                                raise RuntimeError(completed.stderr[-2000:])
                            trials.append({"pair": pair + 1, **json.loads(completed.stdout)})
            finally:
                server.shutdown()
                thread.join(3)
        if Replay.calls != len(trials) * 2 or sha(seed) != seed_hash:
            raise RuntimeError("unexpected fixture reads or seed changed")

    if len({(p["stored"], p["items"]) for t in trials for p in t["passes"]}) != 1:
        raise RuntimeError("the two arms did not ingest equivalent inputs")
    summary = {}
    for arm in ("gc_only", "gc_and_trim"):
        repeats = [t["passes"][1] for t in trials if t["arm"] == arm]
        summary[arm] = {"repeat_quiet_rss_bytes_median": statistics.median(p["quiet"]["VmRSS"] for p in repeats),
                        "repeat_kernel_peak_bytes_max": max(p["quiet"]["VmHWM"] for p in repeats),
                        "repeat_trim_ms_median": statistics.median(p["trim_ms"] for p in repeats)}
    return {"schema": "chimera.linux-vsa-ingest-heap/1", "scope": "ephemeral daemons in tmpfs, no peer sync",
            "source_root": str(root), "collector_sha256": sha(Path(__file__)),
            "vsa_sha256": sha(root / "chimera_tp/vsa_memory_service.py"),
            "database_sha256": seed_hash, "export_sha256": hashlib.sha256(raw).hexdigest(),
            "export_bytes": len(raw), "python": sys.version.split()[0], "libc": os.confstr("CS_GNU_LIBC_VERSION"),
            "malloc_arena_max": 2, "replay_requests": Replay.calls, "trials": trials, "summary": summary}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--pairs", type=int, default=3, choices=range(1, 6))
    parser.add_argument("--arm", choices=("gc_only", "gc_and_trim"))
    parser.add_argument("--seed", type=Path)
    parser.add_argument("--port", type=int)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if not sys.platform.startswith("linux"):
        parser.error("the allocator probe requires Linux with glibc")
    if args.arm and (not args.seed or not args.port):
        parser.error("the private trial needs a database snapshot and replay port")
    result = replay_trial(args) if args.arm else measure(args)
    if args.out:
        with args.out.open("x", encoding="utf-8") as stream:
            json.dump(result, stream, indent=2)
            stream.write("\n")
    else:
        print(json.dumps(result))
