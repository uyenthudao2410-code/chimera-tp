"""Compare Linux allocator policies on identical private Chimera daemons and a frozen VSA input.

Only the parent reads the production SQLite snapshot and Tquota export. Each daemon
opens its own tmpfs copy and loopback HTTP port. Results contain counters and hashes.
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
import shlex
import shutil
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import threading
import time


POLICIES = {
    "current": {},
    "glibc_raw": {"GLIBC_TUNABLES": "glibc.malloc.arena_max=1:glibc.malloc.mmap_threshold=32768:glibc.malloc.trim_threshold=32768",
                  "MALLOC_ARENA_MAX": "1"},
    "glibc_index_cache": {
        "GLIBC_TUNABLES": "glibc.malloc.arena_max=1:glibc.malloc.mmap_threshold=32768:glibc.malloc.trim_threshold=32768",
        "MALLOC_ARENA_MAX": "1",
    },
    "glibc_compact": {
        "GLIBC_TUNABLES": ("glibc.malloc.arena_max=1:glibc.malloc.mmap_threshold=16384:"
                           "glibc.malloc.trim_threshold=32768:glibc.malloc.tcache_count=2"),
        "MALLOC_ARENA_MAX": "1",
    },
    "glibc_no_tcache": {
        "GLIBC_TUNABLES": ("glibc.malloc.arena_max=1:glibc.malloc.mmap_threshold=8192:"
                           "glibc.malloc.trim_threshold=16384:glibc.malloc.tcache_count=0"),
        "MALLOC_ARENA_MAX": "1",
    },
    "jemalloc_raw": {"LD_PRELOAD": "/usr/lib/x86_64-linux-gnu/libjemalloc.so.2",
                     "MALLOC_CONF": "narenas:1,dirty_decay_ms:0,muzzy_decay_ms:0"},
    "mimalloc": {"PYTHONMALLOC": "mimalloc", "MIMALLOC_PURGE_DELAY": "0"},
    "glibc": {"PYTHONMALLOC": "malloc", "GLIBC_TUNABLES": "glibc.malloc.tcache_count=0:glibc.malloc.trim_threshold=65536"},
    "jemalloc": {"PYTHONMALLOC": "malloc", "LD_PRELOAD": "/usr/lib/x86_64-linux-gnu/libjemalloc.so.2",
                 "MALLOC_CONF": "narenas:1,tcache:false,dirty_decay_ms:0,muzzy_decay_ms:0"},
}


POLICIES["glibc_candidate"] = {**POLICIES["glibc_raw"], "CHIMERA_COMPACT_INDEX_CACHE": "1"}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def memory():
    return {key: int(value.split()[0]) * 1024 for row in Path("/proc/self/status").read_text().splitlines()
            for key, _, value in [row.partition(":")] if key in ("VmRSS", "VmHWM", "RssAnon", "VmSwap")}


def export_input():
    conn = http.client.HTTPConnection("127.0.0.1", 12504, timeout=5)
    try:
        conn.request("GET", "/api/thought-briefs/export?limit=300")
        res = conn.getresponse()
        raw = res.read(8 * 1024**2 + 1)
        if res.status != 200 or len(raw) > 8 * 1024**2 or not json.loads(raw).get("items"):
            raise RuntimeError("invalid Tquota export")
        return raw
    finally:
        conn.close()


def snapshot_serving(ops, target, *, freeze_roots=False):
    """Freeze the previous Sentinel scan's tails and an online copy of the FTS database."""
    logs = target / "logs"
    logs.mkdir()
    with closing(sqlite3.connect((ops / "sentinel.db").resolve(strict=True).as_uri() + "?mode=ro", uri=True)) as db:
        summary = json.loads(db.execute("SELECT summary_json FROM scans ORDER BY id DESC LIMIT 1").fetchone()[0])
    sources = summary["logs_scanned"]
    if not 1 <= len(sources) <= 12:
        raise ValueError("empty or oversized serving log inventory")
    fingerprints = []
    for index, item in enumerate(sources):
        with Path(item["path"]).open("rb") as reader:
            reader.seek(max(0, os.fstat(reader.fileno()).st_size - (2 * 1024**2 + 1)))
            data = reader.read(2 * 1024**2 + 1)
        name = logs / f"{index:02}.log"
        name.write_bytes(data)
        fingerprints.append(digest(data))
    index_db = target / "code_index.db"
    with closing(sqlite3.connect((ops / index_db.name).resolve(strict=True).as_uri() + "?mode=ro", uri=True)) as db:
        with closing(sqlite3.connect(index_db)) as dest:
            db.backup(dest, pages=128)
    roots = json.loads((ops / "config.json").read_text())["search_roots"]
    if not roots or not all(Path(p).is_absolute() and Path(p).is_dir() for p in roots):
        raise ValueError("serving index roots unavailable")
    replay_roots = roots
    frozen_tree = None
    if freeze_roots:
        from linux_rss_replay import freeze_index_roots
        replay_roots, frozen_tree = freeze_index_roots(index_db, roots, target)
    (target / "roots.json").write_text(json.dumps(replay_roots))
    return {"index_sha256": digest(index_db.read_bytes()), "log_tail_sha256": fingerprints,
            "roots": roots, "index_bytes": index_db.stat().st_size, "frozen_tree": frozen_tree}


def trial(args):
    sys.path.insert(0, str(args.root))
    from chimera_tp.autopilot import OpsConfig
    from chimera_tp.dashboard import ChimeraDaemon
    # A package-only serving release has no scripts/ directory. Stage the
    # companion HTTP probe alongside this collector, independently of the SUT.
    sys.path.insert(1, str(Path(__file__).resolve().parent))
    from measure_daemon_cli import request

    home = Path.home()
    ops = home / "ops"
    ops.mkdir()
    shutil.copyfile(args.db, ops / "vsa_memory.db")
    if args.replay_dir:
        shutil.copyfile(args.replay_dir / "code_index.db", ops / "code_index.db")
    # All measured daemons bind private ports and never start guest builds.
    cfg = OpsConfig(node_name="rss-profile", role="server", dashboard_bind="127.0.0.1:0",
                    beam_port=0, rpc_v4_port=0, rpc_v6_port=-1, query_port=0,
                    immortal_v4_port=0, immortal_v6_port=-1, warp_port=-1, edge_proxy_port=-1,
                    nat_punch_port=0, phantom_enabled=False, peer_ipv4="", peer_ipv6="",
                    allowed_query_roots=[str(home)], search_roots=[], edge_targets={},
                    tquota_admin_url=f"http://127.0.0.1:{args.port}", daily_time="99:99")
    daemon = ChimeraDaemon(config=cfg, ops_dir=ops, auto_seed_on_empty=False).start()
    stages = {}
    try:
        port = daemon.http_addr[1]
        beacon = request(port, "/.well-known/chimera.json")
        if (beacon["node_name"], beacon["pid"]) != (cfg.node_name, os.getpid()):
            raise RuntimeError("wrong daemon for test")
        if not request(port, "/api/health").get("ok"):
            raise RuntimeError("private health check failed")
        stages["beacon"] = memory()
        # The persistent daemon initializes this state on startup. Construct it in
        # the private HOME without starting its autonomous background loop.
        daemon.platform.agent_bus.symbiont.noosphere
        request(port, "/v1/truth-matrix")
        stages["services_loaded"] = memory()
        replay_counts = None
        replay_timings = {}
        if args.arm == "glibc_index_cache":
            # Model a connection-local page budget on the private index only.
            daemon.code_search._conn.execute("PRAGMA cache_size=-384")
        if args.replay_dir:
            roots = [Path(p) for p in json.loads((args.replay_dir / "roots.json").read_text())]
            index = daemon.code_search.incremental_index(roots)
            replay_timings["index_ms"] = index["elapsed_ms"]
            stages["indexed"] = memory()
            searches = [daemon.code_search.search(query, limit=5)
                        for query in ("sqlite", "chimera", "sentinel", "select")]
            if any(not result["hits"] for result in searches):
                raise RuntimeError("FTS replay returned no results")
            replay_timings["four_searches_ms"] = sum(hit["elapsed_ms"] for hit in searches)
            ranked_hash = digest(json.dumps([result["hits"] for result in searches], sort_keys=True).encode())
            stages["searched"] = memory()
            cfg.allowed_query_roots = [str(args.replay_dir / "logs")]
            scan = daemon.sentinel.scan(cfg)
            stages["sentinel"] = memory()
            hook = request(port, "/v1/hook/status")
            if not hook.get("ok"):
                raise RuntimeError("serving hook status failed")
            daemon.platform.agent_bus.symbiont.noosphere.tick(trigger="rss_probe", sample_network=False)
            stages["hook_and_pulse"] = memory()
            replay_counts = {"index_files": index["total_files"], "updated": index["updated"],
                             "ranked_hits_sha256": ranked_hash,
                             "log_lines": [r["lines"] for r in scan["logs_scanned"]]}
            if not index["ok"] or replay_counts["index_files"] < 1 or not replay_counts["log_lines"]:
                raise RuntimeError("private Sentinel did not process the frozen input")
        checks = []
        packets = cycle = cache_kib = None
        cpu_start = time.process_time()
        if args.packet_replay:
            import chimera_tp.native as native
            from linux_rss_replay import packet_replay
            if Path(native.__file__).resolve().parents[1] != args.root:
                raise RuntimeError("trial imported a different release")
            cache_kib = daemon.code_search._conn.execute("PRAGMA cache_size").fetchone()[0]
            if args.arm == "glibc_candidate" and cache_kib != -384:
                raise RuntimeError("candidate connection did not apply its configured FTS cache")
            packets = packet_replay(cfg.rpc_v4_port)
            stages["transport"] = memory()
        for _ in range(3):
            resp = request(port, "/api/overmind/hippocampus/ingest-tquota",
                           {"tquota_admin_url": cfg.tquota_admin_url, "limit": 300})
            if not resp.get("ok") or not 0 < resp["stored_count"] <= 300:
                raise RuntimeError("failed private VSA ingest")
            checks.append([resp["stored_count"], resp["changed_count"], resp["total_items"]])
            request(port, "/api/vsa/stats")
            request(port, "/api/health")
        if checks[1][1] or checks[2] != checks[1]:
            raise RuntimeError("repeated input changed the database")
        stages["ingest"] = memory()
        gc.collect()
        trim = ctypes.CDLL(None).malloc_trim
        trim.argtypes, trim.restype = [ctypes.c_size_t], ctypes.c_int
        trim(0)
        time.sleep(.35)
        stages["quiet"] = memory()
        latencies = []
        for _ in range(15):
            start = time.perf_counter()
            if not request(port, "/api/health")["ok"]:
                raise RuntimeError("health did not recover")
            latencies.append((time.perf_counter() - start) * 1000)
        stages["after_health"] = memory()
        if args.observe_cycle:
            from linux_rss_replay import observe_cycle
            cycle = observe_cycle(daemon, request, memory, checks[-1], replay_counts["log_lines"])
            stages["after_cycle"] = memory()
        return {"pid": os.getpid(), "source_root": str(args.root), "policy": args.arm,
                "checks": checks, "stages": stages, "serving_counts": replay_counts,
                "packets": packets, "cycle": cycle, "fts_cache_pragma": cache_kib,
                "replay_timings_ms": replay_timings,
                "cpu_s": round(time.process_time() - cpu_start, 4),
                "health_p95_ms": round(sorted(latencies)[14], 3),
                "jemalloc_mapped": "libjemalloc.so" in Path("/proc/self/maps").read_text(),
                "allocator_env": {k: os.environ.get(k) for k in POLICIES[args.arm]}}
    finally:
        daemon.close()
        stages["closed"] = memory()


def logical_vsa_hash(path):
    """Compare stored values in the parent, excluding ingestion timestamps."""
    check = hashlib.sha256()
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        query = "SELECT item_id,domain,text,payload_json,hex(vsa_blob),reward FROM vsa_items ORDER BY item_id"
        for row in db.execute(query):
            check.update(json.dumps(row, separators=(",", ":")).encode() + b"\n")
    return check.hexdigest()


def run(args):
    if len(set(args.policies)) != len(args.policies):
        raise ValueError("allocator policies must be distinct")
    identity = None
    if args.candidate_root:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from linux_rss_replay import source_identity
        identity = source_identity(args.root, args.candidate_root)
    raw = export_input()

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

    rows = []
    with tempfile.TemporaryDirectory(dir="/dev/shm", prefix="chimera-rss-") as folder:
        db = Path(folder) / "snapshot.sqlite"
        baseline, candidate = args.root, args.candidate_root
        bytecode_files = None
        if args.precompile:
            from linux_rss_replay import compile_private_copy
            baseline, candidate = Path(folder) / "baseline", Path(folder) / "candidate"
            bytecode_files = {"baseline": compile_private_copy(args.root, baseline),
                              "candidate": compile_private_copy(args.candidate_root, candidate)}
            if source_identity(baseline, candidate) != identity:
                raise RuntimeError("compiled copy has different source files")
        serving = snapshot_serving(args.serving_ops, Path(folder), freeze_roots=bool(identity)) if args.serving_ops else None
        with closing(sqlite3.connect(args.db.resolve(strict=True).as_uri() + "?mode=ro", uri=True)) as source:
            with closing(sqlite3.connect(db)) as destination:
                source.backup(destination, pages=128)
        seed_hash = digest(db.read_bytes())
        with http.server.HTTPServer(("127.0.0.1", 0), Replay) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                for repeat in range(args.repeats):
                    order = args.policies if repeat % 2 == 0 else list(reversed(args.policies))
                    for arm in order:
                        with tempfile.TemporaryDirectory(dir=folder) as private:
                            env = {k: v for k, v in os.environ.items() if not k.startswith(("PYTHON", "LD_", "MALLOC_", "MIMALLOC_", "GLIBC_"))}
                            keys = ("HOME", "TMPDIR", "XDG_STATE_HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME")
                            env.update(dict.fromkeys(keys, private))
                            env.pop("CHIMERA_COMPACT_INDEX_CACHE", None)
                            env.update({"MALLOC_ARENA_MAX": "2", **POLICIES[arm]})
                            source_root = candidate if arm == "glibc_candidate" else baseline
                            cmd = [sys.executable, "-P", "-s", "-B", "-S", str(Path(__file__).resolve()),
                                   "--arm", arm, "--root", str(source_root), "--db", str(db),
                                   "--port", str(server.server_port)]
                            if serving:
                                cmd.extend(["--replay-dir", folder])
                            if identity:
                                cmd.append("--packet-replay")
                            if args.observe_cycle:
                                cmd.append("--observe-cycle")
                            p = subprocess.run(cmd, cwd=private, env=env, capture_output=True, text=True,
                                               timeout=750 if args.observe_cycle else 50)
                            if p.returncode:
                                raise RuntimeError(f"{arm}: {p.stderr[-1000:]}")
                            row = json.loads(p.stdout)
                            if identity:
                                row["vsa_content_sha256"] = logical_vsa_hash(Path(private) / "ops" / "vsa_memory.db")
                            if row["jemalloc_mapped"] != arm.startswith("jemalloc"):
                                raise RuntimeError("dynamic library policy mismatch")
                            rows.append({"repeat": repeat + 1, **row})
            finally:
                server.shutdown()
                thread.join(3)
        if digest(db.read_bytes()) != seed_hash or Replay.calls != len(rows) * (4 if args.observe_cycle else 3):
            raise RuntimeError("replay fixture changed")
    if len({json.dumps((row["checks"], row["serving_counts"])) for row in rows}) != 1:
        raise RuntimeError("different ingest results across trials")
    if identity:
        if source_identity(args.root, args.candidate_root) != identity:
            raise RuntimeError("private package copies changed")
        if len({(r["vsa_content_sha256"], r["packets"]["payload_sha256"], r["packets"]["rpc_sha256"])
                for r in rows}) != 1:
            raise RuntimeError("stored VSA values or transport bytes differ across trials")
    summary = {}
    for arm in args.policies:
        picked = [r for r in rows if r["policy"] == arm]
        summary[arm] = {
            "rss_bytes_median": statistics.median(r["stages"]["after_health"]["VmRSS"] for r in picked),
            "peak_bytes_max": max(s["VmHWM"] for r in picked for s in r["stages"].values()),
            "stage_rss_bytes_max": max(s["VmRSS"] for r in picked for s in r["stages"].values()),
            "cpu_s_median": statistics.median(r["cpu_s"] for r in picked),
            "health_p95_ms_max": max(r["health_p95_ms"] for r in picked),
        }
    return {"schema": "chimera.linux-daemon-allocator/1", "source_root": str(args.root),
            "collector_sha256": digest(Path(__file__).read_bytes()), "snapshot_sha256": seed_hash,
            "source_identity": identity, "verified_checked_hash_pyc": bytecode_files,
            "workload_sha256": digest(Path(__file__).with_name("linux_rss_replay.py").read_bytes()) if identity else None,
            "export_sha256": digest(raw), "export_bytes": len(raw), "replay_requests": Replay.calls,
            "python": sys.version, "policies": {a: POLICIES[a] for a in args.policies},
            "serving_input": serving, "summary": summary, "trials": rows}


def guarded(args):
    """Run the whole comparison in the receiver's single, monitored guest slot."""
    sys.path.insert(0, str(args.root))
    from chimera_tp.platform import build_worker, peer_guard

    policy = peer_guard.launch_policy(peer_guard.DEFAULT_ROOT, build_worker.guard_policy(True, {
        "cpu_quota_pct": 95, "service_urls": ["http://127.0.0.1:8787/api/health"],
    }))
    command = [sys.executable, "-I", "-B", "-S", str(Path(__file__).resolve()),
               "--root", str(args.root), "--db", str(args.db), "--policies", *args.policies,
               "--repeats", str(args.repeats)]
    if args.serving_ops:
        command.extend(["--serving-ops", str(args.serving_ops)])
    if args.candidate_root:
        command.extend(["--candidate-root", str(args.candidate_root)])
    if args.precompile:
        command.append("--precompile")
    if args.observe_cycle:
        command.append("--observe-cycle")
    if not args.within_guard:
        child = subprocess.run(peer_guard.limited_command(command + ["--within-guard"], policy),
                               check=True, stdout=subprocess.PIPE, text=True)
        return json.loads(child.stdout)

    with peer_guard.reserve(peer_guard.DEFAULT_ROOT, policy) as admission:
        effective = admission["effective_policy"]
        with tempfile.TemporaryDirectory(dir="/dev/shm", prefix="chimera-allocator-receipt-") as folder:
            receipt = Path(folder) / "result.json"
            execution = build_worker._run(
                shlex.join(command + ["--collect-to", str(receipt)]), folder,
                min(790 if args.observe_cycle else 420, effective["runtime_seconds"] - 5), env=os.environ.copy(),
                monitor=lambda: peer_guard.recheck_running(peer_guard.DEFAULT_ROOT, effective),
                repeatable=True,
            )
            if not execution["ok"]:
                raise RuntimeError(f"guarded comparison failed: {execution['stderr'][-1400:]} "
                                   f"{execution.get('error', '')}")
            result = json.loads(receipt.read_text())
        result["peer_guard"] = {"limits_verified": admission["limits_verified"],
                                "policy": effective, "runtime": execution["runtime_guard"],
                                "limits": admission["health"].get("limits")}
        return result


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--db", type=Path, required=True)
    p.add_argument("--candidate-root", type=Path, help="Private release with the native and FTS changes")
    p.add_argument("--observe-cycle", action="store_true", help="Observe one private candidate for 660 seconds")
    p.add_argument("--precompile", action="store_true", help="Prepare checked-hash bytecode in new private copies")
    p.add_argument("--packet-replay", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--policies", nargs="+", choices=POLICIES, default=["current", "mimalloc", "glibc", "jemalloc"])
    p.add_argument("--repeats", type=int, choices=(1, 2, 3), default=2)
    p.add_argument("--arm", choices=POLICIES)
    p.add_argument("--port", type=int)
    p.add_argument("--serving-ops", type=Path, help="Profile FTS, Sentinel, hooks and Noosphere on private copies")
    p.add_argument("--replay-dir", type=Path, help=argparse.SUPPRESS)
    p.add_argument("--within-guard", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--collect-to", type=Path, help=argparse.SUPPRESS)
    args = p.parse_args()
    args.root = args.root.resolve(strict=True)
    if args.candidate_root:
        args.candidate_root = args.candidate_root.resolve(strict=True)
    if not args.arm:
        if ("glibc_candidate" in args.policies) != bool(args.candidate_root):
            p.error("--candidate-root and the glibc_candidate policy must be supplied together")
        if args.precompile and not args.candidate_root:
            p.error("--precompile requires private candidate comparison")
        if args.candidate_root and (args.root == args.candidate_root or not args.serving_ops):
            p.error("candidate comparison requires two separate source trees and --serving-ops")
        if args.observe_cycle and (args.policies != ["glibc_candidate"] or args.repeats != 1):
            p.error("--observe-cycle requires one glibc_candidate trial")
    if args.collect_to:
        with args.collect_to.open("x", encoding="utf-8") as output:
            json.dump(run(args), output)
    else:
        print(json.dumps(trial(args) if args.arm else guarded(args)))
