"""Compare file-slice receipts and the RAM retained by prefetch in fresh processes."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import time


def inputs(root, directory, mode):
    if mode == "short_lines":
        data = (b"ab\n" * 43690) + b"\r\n"
        paths = [directory / f"rows-{i}.txt" for i in range(16)]
        for path in paths:
            path.write_bytes(data)
        return paths
    paths = sorted(path for path in (root / "chimera_tp" / "platform").glob("*.py")
                   if 10_240 <= path.stat().st_size <= 131_072)
    if len(paths) < 16:
        raise ValueError("expected at least 16 eligible source files")
    return paths[:16]


def examine(source, corpus, mode):
    sys.path.insert(0, str(source))
    from chimera_tp.platform.agent_probe import OmniProbeBatchEngine, TokenDietCompactor
    from chimera_tp.platform.agent_symbiont import PrecogRunnerEngine
    from measure_daemon_working_set import process_memory

    with tempfile.TemporaryDirectory() as temporary:
        paths = inputs(corpus, Path(temporary), mode)
        expected = {}
        for path in paths:
            data = path.read_bytes()
            lines = data.decode("utf-8", errors="replace").splitlines()
            expected[path] = (hashlib.blake2s(data, digest_size=12).hexdigest(),
                              len(lines), "\n".join(lines[:3]))
        del lines, data
        probe = OmniProbeBatchEngine(TokenDietCompactor())
        runner = PrecogRunnerEngine(None, None, None)
        probe._spec_cache_lookup = getattr(runner, "get_speculative_snapshot", runner.get_speculative_lines)
        start_memory = process_memory()
        start = time.perf_counter()
        for offset in range(0, len(paths), 8):
            batch = [str(path) for path in paths[offset:offset + 8]]
            result = runner.prefetch_paths(batch)
            if result["cached_count"] != len(batch):
                raise AssertionError(result)
        warm_ms = (time.perf_counter() - start) * 1000
        cached_memory = process_memory()
        start = time.perf_counter()
        hits = correct_hash = correct_text = 0
        for path in paths:
            row = probe._op_file_slice({"path": str(path), "first": 3, "numbered": False}, None)
            digest, total, text = expected[path]
            hits += int(bool(row.get("speculative_hit")))
            correct_hash += int(row["hash"] == digest)
            correct_text += int(row["text"] == text and row["total_lines"] == total)
        return {
            "files": len(paths), "input_bytes": sum(path.stat().st_size for path in paths),
            "corpus_sha256": hashlib.sha256("".join(expected[p][0] for p in paths).encode()).hexdigest(),
            "hits": hits, "canonical_hashes": correct_hash, "correct_slices": correct_text,
            "warm_ms": round(warm_ms, 3), "read_ms": round((time.perf_counter() - start) * 1000, 3),
            "before_warm": start_memory, "after_warm": cached_memory, "after_reads": process_memory(),
        }


def compare(baseline, candidate, repetitions):
    script = Path(__file__).resolve()
    report = {"schema": "chimera.speculative-file-cache/1", "platform": sys.platform,
              "python": sys.version.split()[0], "utc": datetime.now(timezone.utc).isoformat(), "cases": {}}
    for mode in ("source_files", "short_lines"):
        rows = []
        for iteration in range(repetitions):
            pair = [("baseline", baseline), ("candidate", candidate)]
            if iteration % 2:
                pair.reverse()
            for label, source in pair:
                with tempfile.TemporaryDirectory() as empty_cache:
                    proc = subprocess.run(
                        [sys.executable, "-I", "-B", "-S", "-X", f"pycache_prefix={empty_cache}",
                         str(script), "--child", str(source), str(baseline), mode],
                        capture_output=True, timeout=45,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    )
                if proc.returncode:
                    raise RuntimeError(proc.stderr.decode(errors="replace")[-1200:])
                row = json.loads(proc.stdout)
                if row["hits"] != 16 or row["correct_slices"] != 16:
                    raise ValueError(f"incomplete {mode} read in {label}")
                if label == "candidate" and row["canonical_hashes"] != 16:
                    raise ValueError(f"candidate receipt mismatch in {mode}")
                rows.append({"arm": label, **row})
        if len({item["corpus_sha256"] for item in rows}) != 1:
            raise ValueError("source corpus changed during comparison")
        medians = {}
        for label in ("baseline", "candidate"):
            arm = [row for row in rows if row["arm"] == label]
            medians[label] = {
                "after_warm_mib": statistics.median(r["after_warm"]["rss_bytes"] for r in arm) / 2**20,
                "peak_mib": statistics.median(r["after_reads"]["peak_bytes"] for r in arm) / 2**20,
                "warm_ms": statistics.median(r["warm_ms"] for r in arm),
                "read_ms": statistics.median(r["read_ms"] for r in arm),
            }
        report["cases"][mode] = {"medians": medians, "runs": rows}
    return report


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("mode", nargs="?", choices=["source_files", "short_lines"])
    parser.add_argument("--pairs", type=int, choices=range(1, 11), default=3)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if args.child:
        result = examine(args.baseline.resolve(), args.candidate.resolve(), args.mode)
    else:
        result = compare(args.baseline.resolve(), args.candidate.resolve(), args.pairs)
    if args.out is None:
        print(json.dumps(result))
    else:
        with args.out.open("x", encoding="utf-8", newline="\n") as output:
            output.write(json.dumps(result, indent=2) + "\n")
