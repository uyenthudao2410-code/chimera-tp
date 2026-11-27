"""Fixtures and timed workloads for comparing private Linux daemon builds."""

from contextlib import closing, contextmanager
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time


RSS_LIMIT = 55 * 1024**2
CYCLE_SECONDS = 660


def source_identity(baseline, candidate):
    """Include native libraries as well as Python sources in the comparison."""
    def inventory(root):
        package = root / "chimera_tp"
        return {
            path.relative_to(package).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(package.rglob("*"))
            if path.is_file() and "__pycache__" not in path.parts and path.suffix not in (".pyc", ".pyo")
        }

    left, right = inventory(baseline), inventory(candidate)
    changed = {name: [left.get(name), right.get(name)] for name in sorted(left.keys() | right.keys())
               if left.get(name) != right.get(name)}
    if set(changed) != {"native.py", "code_search.py"}:
        raise ValueError(f"unexpected differences between the two package copies: {sorted(changed)}")

    def summary(files):
        return {"files": len(files), "sha256": hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()}

    return {"baseline": summary(left), "candidate": summary(right), "changed_files": changed}


def compile_private_copy(source, destination):
    """Compile only a fresh disposable package, independently of the serving interpreter cache."""
    import compileall
    import py_compile
    import shutil
    from importlib.util import cache_from_source, source_hash

    package = destination / "chimera_tp"
    shutil.copytree(source / "chimera_tp", package, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"))
    if not compileall.compile_dir(package, quiet=2, workers=1, invalidation_mode=py_compile.PycInvalidationMode.CHECKED_HASH):
        raise RuntimeError("private release bytecode compilation failed")
    files = list(package.rglob("*.py"))
    for path in files:
        with Path(cache_from_source(str(path))).open("rb") as stream:
            header = stream.read(16)
        if int.from_bytes(header[4:8], "little") != 3 or header[8:16] != source_hash(path.read_bytes()):
            raise RuntimeError(f"invalid checked-hash bytecode for {path.name}")
    return len(files)


def freeze_index_roots(database, roots, target):
    """Freeze the already-indexed source files so concurrent repo edits cannot bias an arm."""
    sources = [Path(p).resolve(strict=True) for p in roots]
    if len({p.name for p in sources}) != len(sources):
        raise ValueError("cannot freeze roots with duplicate names")
    copies = {p: target / "indexed-input" / p.name for p in sources}
    for directory in copies.values():
        directory.mkdir(parents=True)
    manifest = hashlib.sha256()
    count = size = missing = 0
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as db:
        for name, original in db.execute("SELECT rel_path, root_path FROM files ORDER BY rel_path"):
            root = Path(original).resolve(strict=True)
            relative = Path(name)
            if len(sources) > 1:
                relative = relative.relative_to(root.name)
            if root not in copies or relative.is_absolute() or ".." in relative.parts:
                raise ValueError("indexed path outside the declared roots")
            source = (root / relative).resolve()
            if not source.is_relative_to(root):
                raise ValueError("indexed symlink outside the declared root")
            if not source.is_file():
                missing += 1
                continue
            before = source.stat()
            size += before.st_size
            if size > 128 * 1024**2 or count >= 8000:
                raise ValueError("frozen index input exceeds fixture budget")
            destination = copies[root] / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            file_hash = hashlib.sha256()
            with source.open("rb") as reader, destination.open("xb") as writer:
                while block := reader.read(65536):
                    writer.write(block)
                    file_hash.update(block)
            after = source.stat()
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise RuntimeError("an indexed input changed during capture")
            os.utime(destination, ns=(before.st_atime_ns, before.st_mtime_ns))
            manifest.update(json.dumps([name, before.st_mtime_ns, file_hash.hexdigest()]).encode() + b"\n")
            count += 1
    if count == 0:
        raise ValueError("frozen source tree is empty")
    return list(map(str, copies.values())), {
        "files": count, "bytes": size, "missing_since_index": missing, "manifest_sha256": manifest.hexdigest()
    }


def packet_replay(port):
    """Exercise native GF buffers and the running daemon's loopback UDP request/reply path."""
    from chimera_tp.gf256 import MUL_BYTES
    from chimera_tp.hyper_wire import HedgedRpcClient
    from chimera_tp.native import gf256_mul_add, has_native

    if not has_native():
        raise RuntimeError("expected the release's native Linux library")
    check = hashlib.sha256()
    replies = hashlib.sha256()
    total = calls = 0
    timings = []
    template = bytes(range(256)) * 7
    client = HedgedRpcClient([("127.0.0.1", port)])
    try:
        for sequence in range(1452):
            size = 1 + (sequence * 131) % 1452
            offset = sequence % 251
            coeff = 1 + sequence % 255
            source = bytearray(template[offset:offset + size])
            output = bytearray(size)
            gf256_mul_add(output, memoryview(source), coeff)
            if output != bytes(source).translate(MUL_BYTES[coeff]):
                raise RuntimeError("native packet calculation changed bytes")
            total += size
            check.update(output)
            if sequence % 12 == 0:
                payload = sequence.to_bytes(2, "big") + output
                actual, latency_ms, _ = client.call(payload, timeout_s=2)
                if actual != b"CHIMERA-PONG:" + payload[:32]:
                    raise RuntimeError("unexpected UDP response")
                calls += 1
                replies.update(actual)
                timings.append(latency_ms)
    finally:
        client.close()
    return {
        "packets": 1452, "bytes": total, "rpc_calls": calls, "payload_sha256": check.hexdigest(),
        "rpc_sha256": replies.hexdigest(), "rpc_p95_ms": round(sorted(timings)[(95 * calls + 99) // 100 - 1], 3)
    }


@contextmanager
def private_peer(root, seed_db, home, env):
    """Start a separate production CLI on loopback with a private DB, home and ephemeral ports."""
    import re
    import selectors
    import shutil
    import subprocess
    import sys
    import tempfile
    from measure_daemon_cli import request

    home.mkdir(mode=0o700)
    config = dict(node_name="rss-replay-peer", role="server", dashboard_bind="127.0.0.1:0",
                  beam_port=0, rpc_v4_port=0, rpc_v6_port=-1, query_port=0, immortal_v4_port=0,
                  immortal_v6_port=-1, warp_port=-1, edge_proxy_port=-1, nat_punch_port=0,
                  phantom_enabled=False, peer_ipv4="", peer_ipv6="", search_roots=[], edge_targets={},
                  allowed_query_roots=[str(home)], daily_time="99:99")
    (home / "config.json").write_text(json.dumps(config))
    shutil.copyfile(seed_db, home / "vsa_memory.db")
    keys = ("HOME", "TMPDIR", "XDG_STATE_HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME")
    peer_env = {**env, **dict.fromkeys(keys, str(home))}
    # The peer uses a fixed baseline configuration across all measured arms.
    peer_env.pop("CHIMERA_COMPACT_INDEX_CACHE", None)
    command = [sys.executable, "-I", "-B", "-S", "-u", str(Path(__file__).with_name("measure_daemon_cli.py")),
               "--service", str(root), str(home)]
    with tempfile.TemporaryFile() as errors, subprocess.Popen(
        command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errors, cwd=home, env=peer_env
    ) as child:
        try:
            banner = bytearray()
            with selectors.DefaultSelector() as selector:
                selector.register(child.stdout, selectors.EVENT_READ)
                deadline = time.monotonic() + 20
                while not (match := re.search(rb"Daemon listening at http://127\.0\.0\.1:(\d+)\r?\n", banner)):
                    if not selector.select(max(0, deadline - time.monotonic())):
                        raise TimeoutError("second private CLI did not announce a port")
                    chunk = os.read(child.stdout.fileno(), 4096)
                    if not chunk or len(banner) > 8192:
                        raise RuntimeError("second private CLI did not start")
                    banner.extend(chunk)
            port = int(match.group(1))
            beacon = request(port, "/.well-known/chimera.json")
            if (beacon["pid"], beacon["node_name"]) != (child.pid, config["node_name"]) or port == 9780:
                raise RuntimeError("unexpected private peer identity")
            yield port, child.pid
        finally:
            child.stdin.close()
            if child.poll() is None:
                child.terminate()
            try:
                child.wait(timeout=6)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


def sync_private_peer(port, peer_port, request, local_total):
    peer_before = request(peer_port, "/api/vsa/stats")["item_count"]
    response = request(port, "/api/vsa/sync-peer",
                       {"peer_base": f"http://127.0.0.1:{peer_port}", "limit": 500, "bidirectional": True})
    peer_total = request(peer_port, "/api/vsa/stats")["item_count"]
    if (not response.get("ok") or response["local_total"] != local_total
            or response["peer_total"] != peer_total or response["pulled"] != min(500, peer_before)
            or response["pushed"] != min(500, local_total)):
        raise RuntimeError("two-daemon VSA counts did not match")
    return {key: response[key] for key in ("pulled", "pushed", "local_total", "peer_total", "elapsed_ms")}


def observe_cycle(daemon, request, memory, expected_ingest, expected_log_lines, peer_port=None, *, accelerated=False):
    """Replay timed server work in ephemeral mode, with no configured peer or live relay writes."""
    port = daemon.http_addr[1]
    started = time.monotonic()
    samples, events = [], []
    scan_times = (5, 10) if accelerated else (300, 600)
    duration = 15 if accelerated else CYCLE_SECONDS
    for due in range(0, duration + 1, 5):
        time.sleep(max(0, started + due - time.monotonic()))
        if due in scan_times:
            scan = daemon.sentinel.scan(daemon.config)
            lines = [r["lines"] for r in scan["logs_scanned"]]
            if lines != expected_log_lines:
                raise RuntimeError("Sentinel replay inputs changed")
            events.append({"op": "sentinel", "scheduled_s": due, "lines": lines})
        if due == scan_times[-1]:
            response = request(port, "/api/overmind/hippocampus/ingest-tquota",
                               {"tquota_admin_url": daemon.config.tquota_admin_url, "limit": 300})
            counts = [response[k] for k in ("stored_count", "changed_count", "total_items")]
            if not response.get("ok") or counts != expected_ingest:
                raise RuntimeError("timed VSA replay changed store contents")
            events.append({"op": "tquota_ingest", "scheduled_s": due, "counts": counts})
            if peer_port:
                sync = sync_private_peer(port, peer_port, request, counts[2])
                events.append({"op": "vsa_sync", "scheduled_s": due, **sync})
        ping = time.perf_counter()
        if not request(port, "/api/health").get("ok"):
            raise RuntimeError("private daemon failed a timed health check")
        latency_ms = (time.perf_counter() - ping) * 1000
        samples.append({"t_s": round(time.monotonic() - started, 3), **memory(),
                        "health_ms": round(latency_ms, 3)})
    return {"accelerated": accelerated, "duration_s": samples[-1]["t_s"], "interval_s": 5, "events": events, "samples": samples,
            "samples_at_or_above_55_mib": sum(r["VmRSS"] >= RSS_LIMIT for r in samples),
            "max_rss_bytes": max(r["VmRSS"] for r in samples), "max_hwm_bytes": max(r["VmHWM"] for r in samples)}
