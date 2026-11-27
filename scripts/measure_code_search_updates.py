"""Compare incremental FTS5 updates on a private tmpfs copy of a Linux index.

Run inside the peer's guarded guest job. The source DB is opened read-only.
Fixture files reproduce indexed names, sizes and mtimes using sparse files.
Only the bytes of the 12 deliberately changed files are read by the indexer.
"""

import argparse
from contextlib import closing
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import subprocess
import sys
import tempfile


MARKER = "ChimeraIndexBenchUniqueCodeMarkerWX"
SAMPLE_SIZE = 12


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def memory_kib():
    fields = {}
    for line in Path("/proc/self/status").read_text().splitlines():
        name, _, value = line.partition(":")
        if name in {"VmRSS", "VmHWM"}:
            fields[name] = int(value.split()[0])
    return fields


def open_module(package_root, filename):
    sys.path.insert(0, str(package_root))
    name = "chimera_tp.code_search"
    spec = importlib.util.spec_from_file_location(name, filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def child(args):
    package_root, filename, root, database, changes = map(Path, args)
    sample = json.loads(changes.read_text())
    before = memory_kib()
    module = open_module(package_root, filename)
    index = module.CodeSearchIndex(database)
    opened = memory_kib()
    steps = 0

    def progress():
        nonlocal steps
        steps += 10000
        return 0

    try:
        index._conn.set_progress_handler(progress, 10000)
        report = index.incremental_index([root])
        indexed = memory_kib()
        index._conn.set_progress_handler(None, 0)
        observed = {name: report[name] for name in sample["counts"]}
        if observed != sample["counts"]:
            raise AssertionError(f"index counts: {observed} vs {sample['counts']}")
        hits = index.search(MARKER, limit=50)["hits"]
        if sorted(h["rel_path"] for h in hits) != sorted(sample["updated"]):
            raise AssertionError("marker search returned different paths")
        fingerprint = hashlib.sha256()
        for term in (MARKER, "class", "def"):
            rows = index.search(term, limit=20)["hits"]
            fingerprint.update(json.dumps(rows, sort_keys=True).encode())
        deleted = sample["removed"]
        if deleted:
            parameters = ",".join("?" for _ in deleted)
            sql = f"SELECT count(*) FROM code_fts WHERE rel_path IN ({parameters})"
            if index._conn.execute(sql, deleted).fetchone()[0]:
                raise AssertionError("removed paths are still indexed")
        expected = observed["total_files"]
        counts = index._conn.execute("SELECT count(*), count(DISTINCT rel_path) FROM code_fts").fetchone()
        if tuple(counts) != (expected, expected):
            raise AssertionError("metadata and FTS document counts differ")
        return {"counts": observed, "fts_documents": expected, "marker_hits": len(hits),
                "search_sha256": fingerprint.hexdigest(), "elapsed_ms": report["elapsed_ms"],
                "vm_steps_floor": steps, "before_kib": before, "opened_kib": opened,
                "indexed_kib": indexed}
    finally:
        index.close()


def prepare(source, seed, work):
    with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as src:
        src.execute("PRAGMA query_only=ON")
        with closing(sqlite3.connect(seed)) as dest:
            src.backup(dest, pages=256)
            roots = dest.execute("SELECT DISTINCT root_path FROM files").fetchall()
            if len(roots) != 1:
                raise ValueError("fixture expects one indexed root")
            root = work / "tree" / Path(roots[0][0]).name
            rows = dest.execute("SELECT rel_path, size, mtime_ns FROM files ORDER BY rel_path")
            selected = []
            count = 0
            for key, size, mtime in rows:
                rel = PurePosixPath(key)
                if rel.is_absolute() or not rel.parts or ".." in rel.parts or size < 0:
                    raise ValueError("invalid relative path or size in index")
                file = root / rel
                file.parent.mkdir(parents=True, exist_ok=True)
                with file.open("xb") as stream:
                    stream.truncate(size)
                os.utime(file, ns=(mtime, mtime))
                count += 1
                if 0 < size < 49152 and len(selected) < SAMPLE_SIZE * 2:
                    selected.append(key)
    if len(selected) != SAMPLE_SIZE * 2:
        raise ValueError("not enough indexed text files for the batch")
    return root, count, selected


def benchmark(args):
    candidate = args.candidate.resolve(strict=True)
    package_root = args.package_root.resolve(strict=True)
    baseline = args.baseline.resolve(strict=True)
    if digest(baseline) == digest(candidate):
        raise ValueError("baseline and candidate are identical")
    source = args.database.resolve(strict=True)
    scratch = Path("/dev/shm")
    if shutil.disk_usage(scratch).free < 4 * source.stat().st_size + 32 * 1024**2:
        raise OSError("insufficient space on tmpfs")
    with tempfile.TemporaryDirectory(dir=scratch, prefix="chimera-fts-ab-") as tmp:
        work = Path(tmp)
        seed = work / "seed.db"
        root, total, selected = prepare(source, seed, work)
        versions = {"baseline": baseline, "candidate": candidate}
        report = {"snapshot_bytes": seed.stat().st_size, "snapshot_sha256": digest(seed),
                  "indexed_files": total, "sqlite_version": sqlite3.sqlite_version,
                  "python_version": sys.version.split()[0],
                  "module_sha256": {k: digest(v) for k, v in versions.items()}, "trials": []}
        for mode in ("unchanged", "mixed"):
            changed, removed = [], []
            if mode == "mixed":
                changed, removed = selected[::2], selected[1::2]
                for key in changed:
                    (root / key).write_text(MARKER + "\n", encoding="utf-8")
                for key in removed:
                    (root / key).unlink()
            counts = {"total_files": total - len(removed), "updated": len(changed),
                      "removed": len(removed), "skipped_unchanged": total - len(changed) - len(removed),
                      "skipped_binary_or_large": 0}
            change_file = work / "changes.json"
            change_file.write_text(json.dumps({"counts": counts, "updated": changed, "removed": removed}))
            for pair in range(args.pairs):
                order = tuple(versions) if pair % 2 == 0 else tuple(reversed(versions))
                fingerprints = []
                for version in order:
                    with tempfile.TemporaryDirectory(dir=work, prefix="trial-") as trial:
                        database = Path(trial) / "copy.db"
                        shutil.copyfile(seed, database)
                        proc = subprocess.run(
                            [sys.executable, "-I", "-B", "-S", __file__, "--child", package_root,
                             versions[version], root, database, change_file],
                            capture_output=True, text=True, timeout=60,
                        )
                        if proc.returncode:
                            raise RuntimeError(proc.stderr[-1200:])
                        row = json.loads(proc.stdout)
                        report["trials"].append({"mode": mode, "pair": pair + 1, "version": version, **row})
                        fingerprints.append(row["search_sha256"])
                if fingerprints[0] != fingerprints[1]:
                    raise AssertionError("ranked hits and snippets differ within pair")
        return report


if __name__ == "__main__":
    if sys.argv[1:2] == ["--child"]:
        print(json.dumps(child(sys.argv[2:])))
    else:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("--database", type=Path, required=True)
        parser.add_argument("--package-root", type=Path, required=True)
        parser.add_argument("--baseline", type=Path, required=True)
        parser.add_argument("--candidate", type=Path, required=True)
        parser.add_argument("--pairs", type=int, choices=range(1, 6), default=3)
        print(json.dumps(benchmark(parser.parse_args()), separators=(",", ":")))
