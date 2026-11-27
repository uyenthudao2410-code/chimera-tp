"""Stage an immutable reference compile workload and run it locally or over SSH."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import textwrap
import zlib

from measure_build_location import WORKER


INPUTS = (
    "chimera_tp/native.py",
    "chimera_tp/platform/hyper_desk.py",
    "chimera_tp/platform/phantom_silicon.py",
    "chimera_tp/platform/substrate.py",
)


TIMED_WORKER = (
    "import contextlib, io, json, time\n"
    "output = io.StringIO()\n"
    "before = time.perf_counter_ns()\n"
    "with contextlib.redirect_stdout(output):\n"
    + textwrap.indent(WORKER.strip(), "    ")
    + "\nafter = time.perf_counter_ns()\n"
    "result = json.loads(output.getvalue())\n"
    "result['window_ms'] = [before / 1_000_000, after / 1_000_000]\n"
    "print(json.dumps(result))\n"
)


def stable_bytes(value):
    return json.dumps(value, ensure_ascii=True, separators=(",", ":")).encode("ascii")


def prepare(path: Path, rounds: int):
    project = Path(__file__).resolve().parents[1]
    files = [[name, (project / name).read_text(encoding="utf-8")] for name in INPUTS]
    payload = stable_bytes({"files": files, "rounds": rounds})
    with path.open("xb") as stream:
        stream.write(payload)
    return {"input_sha256": hashlib.sha256(payload).hexdigest(), "sources": list(INPUTS),
            "bytes": len(payload), "rounds": rounds}


def run(path: Path, site: str, peer: str, timeout: float):
    data = path.read_bytes()
    bundle = json.loads(data)
    source_digest = hashlib.sha256(stable_bytes(bundle["files"])).hexdigest()
    if site == "local":
        command = [sys.executable, "-I", "-B", "-S", "-c", TIMED_WORKER]
    else:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", peer):
            raise ValueError("Invalid SSH hostname")
        worker = base64.b64encode(zlib.compress(TIMED_WORKER.encode())).decode("ascii")
        remote = "python3 -I -B -S -c \"import base64,zlib;exec(zlib.decompress(base64.b64decode('%s')))\"" % worker
        command = ["ssh", "-T", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
                   "-o", "UpdateHostKeys=no", "-o", "ConnectTimeout=5", peer, remote]
    result = subprocess.run(command, input=data, capture_output=True, timeout=timeout, check=False)
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors="replace")[-800:] or
                           f"Compile subprocess exited with {result.returncode}")
    receipt = json.loads(result.stdout)
    if receipt["digest"] != source_digest or receipt["units"] != len(INPUTS) * bundle["rounds"]:
        raise ValueError("Compile worker returned an inconsistent source digest or compile count")
    # CPython bytecode is version-specific. The shared assertion here is that each
    # exact source compiled successfully in every round, with a receipt from the worker.
    result_digest = hashlib.sha256(stable_bytes([receipt["digest"], receipt["units"]])).hexdigest()
    return {"input_sha256": hashlib.sha256(data).hexdigest(), "result_sha256": result_digest,
            "result_kind": "all_sources_compiled", "compiler_windows_ms": [receipt["window_ms"]],
            "compiler_clock": "windows_qpc" if site == "local" else "linux_monotonic", **receipt}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("prepare", "local", "remote"))
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--rounds", type=int, default=400)
    parser.add_argument("--peer", default="svhome")
    parser.add_argument("--timeout", type=float, default=150)
    args = parser.parse_args()
    if not 1 <= args.rounds <= 3000 or not 0 < args.timeout <= 1800:
        parser.error("rounds must be 1..3000 and timeout must be in (0, 1800] seconds")
    record = (prepare(args.snapshot, args.rounds) if args.operation == "prepare" else
              run(args.snapshot, args.operation, args.peer, args.timeout))
    print(json.dumps(record, ensure_ascii=True))


if __name__ == "__main__":
    main()
