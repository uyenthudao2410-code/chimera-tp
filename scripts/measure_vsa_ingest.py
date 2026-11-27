"""A/B the VSA encoder through the normal batch-ingestion path on Linux.

Fetch one loopback export and replay it to isolated processes over stdin.
Only aggregate measurements and digests leave the job. SQLite writes use
private directories in tmpfs. Neither running daemon's database is opened.
"""

import argparse
from contextlib import closing
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import urllib.request


EXPORT_URL = "http://127.0.0.1:12504/api/thought-briefs/export?limit=300"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def memory():
    fields = {}
    for line in Path("/proc/self/status").read_text().splitlines():
        key, _, value = line.partition(":")
        if key in {"VmHWM", "VmRSS"}:
            fields[key] = int(value.split()[0])
    return fields


def load_module(root, file):
    sys.path.insert(0, str(root))
    name = "chimera_tp.vsa_memory_service"
    spec = importlib.util.spec_from_file_location(name, file)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def digest_rows(conn):
    # Import times differ across processes. Compare every persisted data field
    # except updated_at. Each string/blob has a length prefix in the digest.
    digest = hashlib.sha256()
    count = 0
    sql = "SELECT item_id,domain,text,payload_json,vsa_blob,reward FROM vsa_items ORDER BY item_id"
    for row in conn.execute(sql):
        count += 1
        for field in row:
            data = field if isinstance(field, bytes) else str(field).encode("utf-8")
            digest.update(len(data).to_bytes(8, "little"))
            digest.update(data)
    return {"rows": count, "data_sha256": digest.hexdigest()}


def exercise(root, file, snapshot):
    module = load_module(root, file)

    def replay(url, **kwargs):
        if url != EXPORT_URL:
            raise ValueError("unexpected replay endpoint")
        return io.BytesIO(snapshot)

    with tempfile.TemporaryDirectory(dir="/dev/shm", prefix="chimera-vsa-db-") as tmp:
        with closing(module.SharedVsaMemoryService(Path(tmp) / "copy.db")) as ledger:
            opened = memory()
            passes = []
            original = urllib.request.urlopen
            try:
                urllib.request.urlopen = replay
                for temperature in ("cold", "warm"):
                    # Each private SQLite file has a single connection. Measure the
                    # WAL produced by this pass without counting previous frames.
                    checkpoint = ledger._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
                    if checkpoint != (0, 0, 0):
                        raise RuntimeError(f"incomplete private WAL checkpoint: {checkpoint}")
                    changes_before = ledger._conn.total_changes
                    before_cpu = time.process_time()
                    before_wall = time.perf_counter()
                    result = ledger.ingest_tquota_thought_briefs()
                    wall_ms = (time.perf_counter() - before_wall) * 1000
                    cpu_ms = (time.process_time() - before_cpu) * 1000
                    after = memory()
                    if not result.get("ok") or not result["stored_count"]:
                        raise RuntimeError("no valid replayed items")
                    wal = Path(str(ledger.db_path) + "-wal")
                    stamp_digest = hashlib.sha256()
                    for (stamp,) in ledger._conn.execute("SELECT updated_at FROM vsa_items ORDER BY item_id"):
                        stamp_digest.update(stamp.encode("utf-8") + b"\n")
                    writes = ledger._conn.total_changes - changes_before
                    if "changed_count" in result and result["changed_count"] != writes:
                        raise RuntimeError("ingest counter differs from SQLite changes")
                    cache = getattr(module, "_expand_token", module._token_hypervector).cache_info()
                    passes.append({"pass": temperature, "fetched": result["fetched"],
                                   "stored": result["stored_count"], "sqlite_changes": writes,
                                   "wal_bytes": wal.stat().st_size if wal.exists() else 0,
                                   "timestamps_sha256": stamp_digest.hexdigest(), "wall_ms": round(wall_ms, 2),
                                   "cpu_ms": round(cpu_ms, 2), "after_kib": after,
                                   "cache_entries": cache.currsize, **digest_rows(ledger._conn)})
            finally:
                urllib.request.urlopen = original
    return {"opened_kib": opened, "passes": passes}


def benchmark(root, base, candidate, pairs):
    versions = {"baseline": base.resolve(strict=True), "candidate": candidate.resolve(strict=True)}
    hashes = {k: sha(p.read_bytes()) for k, p in versions.items()}
    if hashes["baseline"] == hashes["candidate"]:
        raise ValueError("baseline and candidate are identical")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(EXPORT_URL, timeout=8) as response:
        snapshot = response.read()
    trials = []
    match = None
    for pair in range(pairs):
        order = tuple(versions) if pair % 2 == 0 else tuple(reversed(versions))
        for name in order:
            cmd = [sys.executable, "-I", "-B", "-S", __file__, "--child", root, versions[name]]
            proc = subprocess.run(cmd, input=snapshot, capture_output=True, timeout=140)
            if proc.returncode:
                raise RuntimeError(proc.stderr.decode(errors="replace")[-1200:])
            result = json.loads(proc.stdout)
            for row in result["passes"]:
                identity = (row["fetched"], row["stored"], row["rows"], row["data_sha256"])
                if match is not None and identity != match:
                    raise AssertionError("VSA vectors, metadata or counts differ")
                match = identity
            trials.append({"pair": pair + 1, "version": name, **result})
    return {"export_bytes": len(snapshot), "export_sha256": sha(snapshot),
            "module_sha256": hashes, "python": sys.version.split()[0], "trials": trials}


if __name__ == "__main__":
    if sys.argv[1:2] == ["--child"]:
        print(json.dumps(exercise(Path(sys.argv[2]), Path(sys.argv[3]), sys.stdin.buffer.read())))
    else:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("--package-root", required=True, type=Path)
        parser.add_argument("--baseline", required=True, type=Path)
        parser.add_argument("--candidate", required=True, type=Path)
        parser.add_argument("--pairs", type=int, choices=range(1, 6), default=3)
        args = parser.parse_args()
        print(json.dumps(benchmark(args.package_root, args.baseline, args.candidate, args.pairs),
                         separators=(",", ":")))
