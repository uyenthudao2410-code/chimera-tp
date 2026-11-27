"""Measure one fresh daemon from a selected source tree on loopback and ephemeral ports."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import ctypes
import gzip
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import urllib.request


def check_backup_download(daemon, opener, base, mark):
    """Check both negotiated representations without buffering the fixture in the client."""
    directory = daemon.backup_root / "rss-fixture"
    directory.mkdir(parents=True, exist_ok=False)
    shard = directory / "shard_1.chshard"
    block = os.urandom(64 * 1024)
    expected = hashlib.sha256()
    with shard.open("xb") as target:
        for _ in range(768):
            target.write(block)
            expected.update(block)
    url = base + "/api/backup/shard?backup_id=rss-fixture&idx=1"
    for encoding in ("identity", "gzip"):
        request = urllib.request.Request(url, headers={"Accept-Encoding": encoding})
        digest = hashlib.sha256()
        received = 0
        with opener.open(request, timeout=20) as response:
            if response.headers.get("Content-Encoding", "identity") != encoding:
                raise RuntimeError(f"unexpected_shard_encoding:{encoding}")
            reader = gzip.GzipFile(fileobj=response) if encoding == "gzip" else response
            with reader:
                while part := reader.read(64 * 1024):
                    digest.update(part)
                    received += len(part)
        if received != shard.stat().st_size or digest.digest() != expected.digest():
            raise RuntimeError(f"shard_integrity_failure:{encoding}")
        mark("backup_shard_48mib_" + encoding)


def check_vsa_transfer(daemon, opener, base, mark):
    """Exercise both sides of a populated peer sync in one disposable daemon."""
    def post(route, payload):
        req = urllib.request.Request(base + route, data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json"})
        with opener.open(req, timeout=30) as response:
            return json.load(response)

    seen = hashlib.sha256()
    vec = os.urandom(1250).hex()
    for start in range(0, 800, 16):
        items = [{
            "item_id": f"rss-{i:04d}", "domain": "rss-transfer",
            "text": f"fixture {i} " + "drawing " * 75,
            "payload": {"key": i, "note": "hồ sơ " * 160}, "vsa_hex": vec,
        } for i in range(start, start + 16)]
        if post("/api/vsa/store", {"items": items}).get("stored_count") != len(items):
            raise RuntimeError("vsa_fixture_incomplete")
        for row in items:
            seen.update(row["item_id"].encode())
    mark("vsa_store_800")
    result = post("/api/vsa/sync-peer", {"peer_base": base, "domain": "rss-transfer", "limit": 800})
    if (result.get("pulled"), result.get("pushed")) != (800, 800):
        raise RuntimeError("incomplete_vsa_peer_sync")
    # Verify the logical contents independently using the disposable SQLite ledger.
    import sqlite3
    from contextlib import closing
    actual = hashlib.sha256()
    with closing(sqlite3.connect(daemon.ops_dir / "vsa_memory.db")) as conn:
        for iid, text, payload, raw in conn.execute(
                "SELECT item_id, text, payload_json, vsa_blob FROM vsa_items "
                "WHERE domain='rss-transfer' ORDER BY item_id"):
            index = int(iid.removeprefix("rss-"))
            if (text != f"fixture {index} " + "drawing " * 75 or raw.hex() != vec
                    or json.loads(payload) != {"key": index, "note": "hồ sơ " * 160}):
                raise RuntimeError("vsa_transfer_changed_record")
            actual.update(iid.encode())
    if seen.digest() != actual.digest():
        raise RuntimeError("vsa_transfer_changed_identifiers")
    mark("vsa_bidirectional_800")


def process_memory():
    if sys.platform.startswith("linux"):
        fields = {}
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith(("VmRSS:", "VmHWM:")):
                key, kb, units = line.split()
                if units == "kB":
                    fields[key] = int(kb) * 1024
        return {"rss_bytes": fields["VmRSS:"], "peak_bytes": fields["VmHWM:"]}
    if os.name != "nt":
        raise OSError("this probe supports Windows and Linux")

    class Counters(ctypes.Structure):
        _fields_ = [("cb", ctypes.c_uint32), ("faults", ctypes.c_uint32),
                    ("peak_ws", ctypes.c_size_t), ("working_set", ctypes.c_size_t),
                    ("other", ctypes.c_size_t * 6)]

    counter = Counters()
    counter.cb = ctypes.sizeof(counter)
    if not ctypes.windll.psapi.GetProcessMemoryInfo(
            ctypes.c_void_p(-1), ctypes.byref(counter), counter.cb):
        raise ctypes.WinError()
    return {"rss_bytes": counter.working_set, "peak_bytes": counter.peak_ws}


def imports():
    return sorted(key for key in sys.modules if key == "chimera_tp" or key.startswith("chimera_tp."))


def measure(root, *, profile=False):
    root = root.resolve(strict=True)
    if imports() or not (sys.flags.isolated and sys.flags.no_site):
        raise RuntimeError("start a fresh interpreter with -I -B -S")
    sys.path.insert(0, str(root))
    started = time.perf_counter()
    stages = []

    def mark(name):
        if profile:
            readings = process_memory()
            stages.append({"stage": name, **readings, "elapsed_s": round(time.perf_counter() - started, 3)})

    mark("interpreter")
    import chimera_tp
    import chimera_tp.platform

    if Path(chimera_tp.__file__).resolve().parent != root / "chimera_tp":
        raise RuntimeError("unexpected_package")
    mark("package_import")
    entry = {"rss_bytes": process_memory()["rss_bytes"], "modules": imports(),
             "import_ms": round((time.perf_counter() - started) * 1000, 3)}
    from chimera_tp.autopilot import OpsConfig
    from chimera_tp.dashboard import ChimeraDaemon
    from chimera_tp.native import has_native
    mark("dashboard_import")

    # Keep the disposable 48 MiB shard and SQLite writes off the peer's service disk.
    # tmpfs allocations remain charged to the same memory-limited guest cgroup.
    scratch = None
    if sys.platform.startswith("linux") and os.access("/dev/shm", os.W_OK):
        usage = os.statvfs("/dev/shm")
        if usage.f_bavail * usage.f_frsize >= 128 * 1024**2:
            scratch = "/dev/shm"
    with tempfile.TemporaryDirectory(prefix="chimera-rss-probe-", dir=scratch) as name:
        ops = Path(name)
        cfg = OpsConfig(node_name="rss-trial", role="server", dashboard_bind="127.0.0.1:0",
                        beam_port=0, rpc_v4_port=0, rpc_v6_port=-1, query_port=0,
                        immortal_v4_port=0, immortal_v6_port=-1, warp_port=-1, edge_proxy_port=-1,
                        nat_punch_port=0, phantom_enabled=False, peer_ipv4="", peer_ipv6="",
                        allowed_query_roots=[name], search_roots=[], edge_targets={})
        daemon = ChimeraDaemon(config=cfg, ops_dir=ops, auto_seed_on_empty=False).start()
        try:
            mark("daemon_start")
            base = f"http://127.0.0.1:{daemon.http_addr[1]}"
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

            def get(path):
                with opener.open(base + path, timeout=8) as stream:
                    return json.load(stream)

            beacon = get("/.well-known/chimera.json")
            if beacon["node_name"] != cfg.node_name or beacon["pid"] != os.getpid():
                raise RuntimeError("incorrect_beacon")
            health = get("/api/health")
            if not health.get("ok") or not health.get("version"):
                raise RuntimeError("invalid_health_result")
            pulse = daemon.platform.pulse_summary()
            mark("beacon_health_pulse")
            if "engine_loaded" in pulse["omega"] and (pulse["omega"]["engine_loaded"] or pulse["thermo"]["engine_loaded"]):
                raise RuntimeError("passive_pulse_loaded_an_optional_engine")
            samples = []
            for _ in range(5):
                samples.append(process_memory()["rss_bytes"])
                time.sleep(0.2)
            cold_modules = imports()
            vsa_disk_before = (ops / "vsa_memory.db").is_file()
            stats = get("/api/vsa/stats")
            if not stats.get("ok"):
                raise RuntimeError("vsa_stats_unavailable")
            mark("vsa_stats")
            warm = process_memory()["rss_bytes"]
            vsa_disk_after = (ops / "vsa_memory.db").is_file()
            with ThreadPoolExecutor(max_workers=4) as pool:
                outputs = list(pool.map(get, ["/v1/cosmos/status"] * 2 + ["/v1/omega/status"] * 2))
            if not all(result.get("ok") for result in outputs):
                raise RuntimeError("optional_engine_status_failed")
            mark("cosmos_omega_concurrent")
            with ThreadPoolExecutor(max_workers=4) as pool:
                instances = list(pool.map(lambda _: id(daemon.platform.exile_handoff), range(8)))
            if len(set(instances)) != 1:
                raise RuntimeError("parallel_handoffs_instantiated_different_coordinators")
            mark("exile_coordinator")
            warmed_modules = imports()
            all_loaded = process_memory()["rss_bytes"]
            if profile:
                for path in ("/api/status", "/api/pulse", "/v1/truth-matrix"):
                    if not get(path):
                        raise RuntimeError(f"empty_dashboard_response:{path}")
                    mark(path)
                with ThreadPoolExecutor(max_workers=4) as pool:
                    for result in pool.map(get, ["/api/status", "/api/pulse", "/v1/truth-matrix"] * 4):
                        if not result:
                            raise RuntimeError("empty_dashboard_response")
                mark("dashboard_concurrent")
                check_backup_download(daemon, opener, base, mark)
                check_vsa_transfer(daemon, opener, base, mark)
        finally:
            daemon.close()
    return {**({"stages": stages} if profile else {}),
            "os": sys.platform, "python": sys.version.split()[0], "pid": os.getpid(),
            "state_storage": scratch or "system_temp",
            "native": has_native(), "package_import": entry, "beacon_cartridges": sorted(beacon["cartridges"]),
            "anchor_healthy": True, "idle_rss_bytes": samples, "idle_modules": cold_modules,
            "after_vsa_rss_bytes": warm, "vsa_stats_ok": True, "temporary_state_removed": not ops.exists(),
            "vsa_db_before_first_query": vsa_disk_before, "vsa_db_after_query": vsa_disk_after,
            "after_optional_routes_rss_bytes": all_loaded, "after_optional_routes_modules": warmed_modules,
            "concurrent_http_status": True, "single_handoff_coordinator": True,
            "initializer_sha256": hashlib.sha256((root / "chimera_tp/__init__.py").read_bytes()).hexdigest()}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True, help="Folder containing the chimera_tp package")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--profile", action="store_true", help="Record per-stage OS high-water marks and dashboard traffic")
    args = parser.parse_args()
    result = json.dumps(measure(args.root, profile=args.profile), indent=2) + "\n"
    if args.out:
        with args.out.open("x", encoding="utf-8") as stream:
            stream.write(result)
    else:
        print(result, end="")
