"""Pair the project's full Python compile on two identified Windows volumes."""

from __future__ import annotations

import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import marshal
import os
from pathlib import Path
import platform
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import uuid


REPO = Path(__file__).resolve().parents[1]
MAX_SOURCE_BYTES = 32 * 1024**2
COMPILE_ARGS = [
    "-I", "-S", "-B", "-m", "compileall", "-f", "-q", "-j", "1",
    "--invalidation-mode", "checked-hash", "-d", "chimera_tp", "chimera_tp",
]
DEVICE_QUERY = """
$ErrorActionPreference = 'Stop'
$physical = @(Get-PhysicalDisk)
$rows = foreach ($letter in __REQUESTED_VOLUMES__) {
    $vol = Get-Volume -DriveLetter $letter
    $disk = Get-Partition -DriveLetter $letter | Get-Disk
    if ($letter -eq 'V') {
        [pscustomobject]@{
            letter = $letter; filesystem = [string]$vol.FileSystem; disk_number = [int]$disk.Number
            model = [string]$disk.FriendlyName; bus = [string]$disk.BusType
            backing_file = [string]$disk.Location; free_bytes = [int64]$vol.SizeRemaining
        }
        continue
    }
    $drive = @($physical | Where-Object {
        [string]$_.DeviceId -eq [string]$disk.Number -and $_.FriendlyName -eq $disk.FriendlyName
    })
    if ($drive.Count -ne 1) { throw "Ambiguous physical disk mapping for $letter" }
    [pscustomobject]@{
        letter = $letter; filesystem = [string]$vol.FileSystem; disk_number = [int]$disk.Number
        model = [string]$disk.FriendlyName; bus = [string]$disk.BusType
        media = [string]$drive[0].MediaType; free_bytes = [int64]$vol.SizeRemaining
    }
}
$rows | ConvertTo-Json -Compress
"""


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def manifest_hash(entries):
    encoded = json.dumps(entries, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha(encoded.encode("utf-8"))


def git(*args):
    return subprocess.check_output(["git", "-C", str(REPO), *args], timeout=20,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def paths_on_disk():
    raw = git("ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", "chimera_tp")
    names = sorted(set(row.decode("utf-8") for row in raw.split(b"\0") if row.endswith(b".py")))
    result = {}
    total = 0
    for name in names:
        path = REPO / name
        if not path.exists():
            continue  # A tracked file deleted in the working tree has no source to compile.
        if path.resolve(strict=True) != path or not path.is_file() or path.stat().st_nlink != 1:
            raise ValueError(f"Unsupported link or non-regular input: {name}")
        total += path.stat().st_size
        if total > MAX_SOURCE_BYTES:
            raise ValueError("Working tree exceeds the benchmark input budget")
        result[name] = path
    if not result:
        raise ValueError("No Python package sources were discovered")
    return result


def snapshot():
    for _ in range(3):
        revision = git("rev-parse", "HEAD").decode("ascii").strip()
        try:
            files = {name: path.read_bytes() for name, path in paths_on_disk().items()}
            current = paths_on_disk()
            stable = files.keys() == current.keys() and all(
                data == current[name].read_bytes() for name, data in files.items()
            )
        except FileNotFoundError:
            continue
        if stable and revision == git("rev-parse", "HEAD").decode("ascii").strip():
            if sum(map(len, files.values())) > MAX_SOURCE_BYTES:
                raise ValueError("Source changed size beyond the benchmark budget")
            return revision, files
    raise RuntimeError("Working package changed during three successive snapshot attempts")


def volumes(refs=False):
    query = DEVICE_QUERY.replace("__REQUESTED_VOLUMES__", "'C','V'" if refs else "'E','C'")
    raw = subprocess.check_output(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", query],
        timeout=35, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    devices = {item["letter"]: item for item in json.loads(raw)}
    native = (("C", "SSD", "NVMe"),) if refs else (("E", "HDD", "SATA"), ("C", "SSD", "NVMe"))
    for letter, media, bus in native:
        info = devices[letter]
        if (info["media"], info["bus"], info["filesystem"]) != (media, bus, "NTFS"):
            raise ValueError(f"{letter}: does not match the requested device and filesystem")
        if info["free_bytes"] < 2 * 1024**3:
            raise ValueError(f"Too little free scratch space on {letter}:")
    if refs:
        dev = devices["V"]
        backing = Path(dev["backing_file"]).resolve(strict=True)
        if (dev["filesystem"] != "ReFS" or dev["bus"] != "File Backed Virtual"
                or backing.drive.upper() != "C:" or backing.suffix.lower() != ".vhdx"
                or not backing.is_file() or dev["free_bytes"] < 2 * 1024**3):
            raise ValueError("V: must be a ReFS VHDX backed by the measured C: volume")
    elif devices["C"]["disk_number"] == devices["E"]["disk_number"]:
        raise ValueError("Both volumes resolve to the same physical disk")
    return devices


def scratch_root(stack, letter, candidate):
    parent = candidate.resolve(strict=True)
    if not parent.is_dir() or parent.drive.upper() != letter + ":" or parent.is_relative_to(REPO):
        raise ValueError(f"Invalid scratch directory on {letter}: {parent}")
    token = uuid.uuid4().hex
    root = Path(tempfile.mkdtemp(prefix="chimera-storage-build-" + token + "-", dir=parent))
    marker = root / ".benchmark-owner"
    marker.write_text(token, encoding="ascii")

    def cleanup():
        actual = root.resolve(strict=True)
        if (actual != root or actual.parent != parent or not root.name.startswith("chimera-storage-build-" + token)
                or not marker.is_file() or marker.read_text(encoding="ascii") != token):
            raise RuntimeError(f"Scratch ownership changed: {root}")
        shutil.rmtree(actual)

    stack.callback(cleanup)
    return root


def stage(work, files):
    work.mkdir()
    for name, data in files.items():
        path = work / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    for name, data in files.items():
        if (work / name).read_bytes() != data:
            raise IOError(f"Staging verification failed for {name}")


def run_build(work):
    start_utc = utc_now()
    start = time.perf_counter_ns()
    completed = subprocess.run(
        [sys.executable, *COMPILE_ARGS], cwd=work, capture_output=True, timeout=120,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    elapsed = (time.perf_counter_ns() - start) / 1_000_000
    if completed.returncode:
        raise RuntimeError((completed.stdout + completed.stderr).decode("utf-8", errors="replace")[-1200:])
    return {"start_utc": start_utc, "wall_ms": round(elapsed, 3)}


def verify_product(work, files):
    observed = {}
    byte_count = 0
    for name, data in files.items():
        product = Path(importlib.util.cache_from_source(str(work / name)))
        pyc = product.read_bytes()
        expected_header = importlib.util.MAGIC_NUMBER + (3).to_bytes(4, "little") + importlib.util.source_hash(data)
        if pyc[:16] != expected_header:
            raise ValueError(f"Bytecode header/source hash mismatch: {name}")
        code = marshal.loads(pyc[16:])
        expected = compile(data, str(Path(name)), "exec", dont_inherit=True, optimize=0)
        if code.co_filename != expected.co_filename or code != expected:
            raise ValueError(f"Bytecode differs from independent compilation: {name}")
        observed[name] = sha(pyc)
        byte_count += len(pyc)
    if sum(1 for _ in work.rglob("*.pyc")) != len(files):
        raise ValueError("Output set differs from snapshot")
    return {"manifest_sha256": manifest_hash(observed), "pyc_files": len(observed), "bytes": byte_count}


def summarize(pairs, baseline="E", trial="C"):
    reference = [p["runs"][baseline]["wall_ms"] for p in pairs]
    measured = [p["runs"][trial]["wall_ms"] for p in pairs]
    ratios = [(left - right) * 100 / left for left, right in zip(reference, measured)]
    names = ("c_ntfs", "v_refs") if trial == "V" else ("hdd", "nvme")
    return {
        "pairs": len(pairs),
        names[0] + "_median_ms": round(statistics.median(reference), 3),
        names[1] + "_median_ms": round(statistics.median(measured), 3),
        "median_paired_reduction_pct": round(statistics.median(ratios), 2),
        "paired_reduction_range_pct": [round(min(ratios), 2), round(max(ratios), 2)],
        names[1] + "_faster_pairs": sum(value > 0 for value in ratios),
        "identical_verified_products": len(pairs) * 2,
    }


def measure(pair_count, refs=False):
    if os.name != "nt" or pair_count not in (6, 8, 10, 12):
        raise ValueError("This experiment takes 6, 8, 10 or 12 paired samples on Windows")
    started = utc_now()
    devices = volumes(refs)
    baseline, trial = ("C", "V") if refs else ("E", "C")
    revision, files = snapshot()
    input_manifest = {name: sha(data) for name, data in files.items()}
    captured_at = utc_now()
    pairs = []
    product = None
    with ExitStack() as stack:
        parents = {"C": Path(tempfile.gettempdir()), "V": Path("V:/"), "E": Path("E:/Temp")}
        roots = {letter: scratch_root(stack, letter, parents[letter]) for letter in (baseline, trial)}
        for index in range(pair_count):
            order = (baseline, trial) if index % 2 == 0 else (trial, baseline)
            work = {letter: roots[letter] / f"pair-{index + 1:02}" for letter in order}
            for letter in order:
                stage(work[letter], files)
            runs = {letter: run_build(work[letter]) for letter in order}
            for letter in order:
                verified = verify_product(work[letter], files)
                if product is not None and verified != product:
                    raise ValueError("Verified output differs between runs")
                product = verified
                runs[letter]["product_sha256"] = verified["manifest_sha256"]
            pairs.append({"pair": index + 1, "order": list(order), "runs": runs})
    return {
        "schema": "chimera.refs-compile-ab/1" if refs else "chimera.ntfs-compile-ab/1",
        "started_utc": started, "completed_utc": utc_now(),
        "workload": "Forced single-process byte compilation of all working chimera_tp Python package sources",
        "python": sys.version, "os": platform.platform(), "executable": sys.executable,
        "command_after_python": COMPILE_ARGS, "volumes": devices, "fixture_directories_removed": True,
        "snapshot": {"captured_utc": captured_at, "git_head_at_capture": revision,
                     "scope": "Working package *.py including tracked changes and nonignored untracked files",
                     "files": len(files), "bytes": sum(map(len, files.values())),
                     "manifest_sha256": manifest_hash(input_manifest), "sha256_by_path": input_manifest},
        "protocol": {
            "cache": "New output paths every run. Inputs were just staged and read back. OS caches were not flushed.",
            "order": f"Alternating {baseline}{trial} and {trial}{baseline}. Both builds precede output verification.",
            "timing": "Process startup, reading sources, compiling, and writing pycs through process exit. No forced disk flush.",
            "verification": "Each pyc header/source hash, marshalled code vs independent compile, exact file count and tree SHA-256.",
            "limits": "Live desktop and normal filesystem caches. Measures the full volume configuration "
                      "including any VHDX layering. Antivirus settings and CAD were not varied.",
        },
        "verified_product": product, "pairs": pairs, "summary": summarize(pairs, baseline, trial),
        "script_sha256": sha(Path(__file__).read_bytes()),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pairs", type=int, default=8, choices=[6, 8, 10, 12])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--refs", action="store_true", help="Pair native NVMe C: with its ReFS VHDX on V:")
    args = parser.parse_args()
    report = measure(args.pairs, args.refs)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))
