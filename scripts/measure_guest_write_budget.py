"""Measure flushed writes on svhome in an already capped, unprivileged CHIMERA guest."""

import argparse
from contextlib import nullcontext
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time


MIB = 1024 ** 2
BLOCK = 256 * 1024
RATES = (1 * MIB, 4 * MIB, 8 * MIB)


def device_numbers(directory):
    device = directory.stat().st_dev
    number = f"{os.major(device)}:{os.minor(device)}"
    sysdev = Path("/sys/dev/block") / number
    numbers = {number}
    if (sysdev / "partition").is_file():
        numbers.add((sysdev.resolve(strict=True).parent / "dev").read_text().strip())
    return number, numbers


def device_rows(cgroup, name):
    rows = {}
    for line in (cgroup / name).read_text().splitlines():
        device, *items = line.split()
        rows[device] = dict(entry.split("=", 1) for entry in items)
    return rows


def sample(directory, rate, kernel_group, fixture_bytes, recheck=None):
    file_device, matches = device_numbers(directory)
    rows = device_rows(kernel_group, "io.max")
    restricted = [d for d in matches if rows.get(d, {}).get("wbps") == str(rate)]
    if len(restricted) != 1:
        raise ValueError("requested write limit absent or ambiguous on the backing device")
    device = restricted[0]

    def counters():
        row = device_rows(kernel_group, "io.stat").get(device, {})
        return {key: int(row.get(key, "0")) for key in ("wbytes", "wios")}

    original = hashlib.sha256()
    samples = []
    with tempfile.TemporaryFile(dir=directory, buffering=0) as file:
        if os.fstat(file.fileno()).st_dev != directory.stat().st_dev:
            raise RuntimeError("temporary file is on a different filesystem")
        before = counters()
        begin = time.monotonic()
        next_check = begin + 1
        for offset in range(0, fixture_bytes, BLOCK):
            seed = b"chimera-io-acceptance-v1" + offset.to_bytes(4, "big")
            block = hashlib.shake_256(seed).digest(BLOCK)
            if file.write(block) != BLOCK:
                raise IOError("short fixture write")
            original.update(block)
            os.fdatasync(file.fileno())
            now = time.monotonic()
            samples.append(round(now - begin, 5))
            if recheck and now >= next_check and offset + BLOCK < fixture_bytes:
                recheck()
                next_check = time.monotonic() + 1

        elapsed = time.monotonic() - begin
        after = counters()
        # Block accounting may arrive just after the final flush.
        deadline = time.monotonic() + 2.0
        while after["wbytes"] - before["wbytes"] < fixture_bytes and time.monotonic() < deadline:
            time.sleep(0.05)
            after = counters()
        file.seek(0)
        actual = hashlib.sha256()
        for part in iter(lambda: file.read(BLOCK), b""):
            actual.update(part)
        if actual.digest() != original.digest():
            raise ValueError("flushed data does not match the generator")
        if after["wbytes"] - before["wbytes"] < fixture_bytes or after["wios"] <= before["wios"]:
            raise ValueError("kernel did not attribute the flushed writes to this guest")
        if device_rows(kernel_group, "io.max").get(device, {}).get("wbps") != str(rate):
            raise ValueError("write limit changed during the measurement")

    return {
        "file_device": file_device, "capped_device": device, "kernel_wbps": rate,
        "fixture_bytes": fixture_bytes, "sha256": original.hexdigest(),
        "flushed_throughput_bps": round(fixture_bytes / elapsed), "elapsed_s": round(elapsed, 5),
        "bytes_per_flush": BLOCK, "seconds_after_each_flush": samples,
        "io_stat_delta": {k: after[k] - v for k, v in before.items()},
    }


def kernel_group(system_trial):
    memberships = [line[3:] for line in Path("/proc/self/cgroup").read_text().splitlines()
                   if line.startswith("0::/")]
    if len(memberships) != 1 or ".." in Path(memberships[0]).parts:
        raise ValueError("cannot resolve unified cgroup")
    group = Path("/sys/fs/cgroup") / memberships[0].lstrip("/")
    if system_trial:
        expected = re.fullmatch(r"chimera-io-proof-[0-9a-f]{12}\.service", group.name)
    else:
        expected = group.name == "chimera-peer-guest.service" and f"user@{os.getuid()}.service" in group.parts
    if not expected:
        raise RuntimeError("the I/O proof must run inside the selected limited guest service")
    return group


def run(args):
    if sys.platform != "linux" or os.getuid() == 0 or os.geteuid() != os.getuid():
        raise RuntimeError("requires an unprivileged Linux guest")
    system_trial = args.system_fixture_release is not None
    group = kernel_group(system_trial)
    work = Path.cwd().resolve(strict=True)
    reservation = nullcontext(None)
    if system_trial:
        release = args.system_fixture_release.resolve(strict=True)
        source = release / "chimera_tp" / "platform" / "peer_guard.py"
        if not args.guard_sha256 or hashlib.sha256(source.read_bytes()).hexdigest() != args.guard_sha256:
            raise ValueError("peer_guard differs from the selected rollout")
        sys.path.insert(0, str(release))
        from chimera_tp.platform import peer_guard
        if Path(peer_guard.__file__).resolve(strict=True) != source:
            raise RuntimeError("unexpected receiver guard")
        policy = {
            "require_io_cap": True, "io_write_bps": args.rate, "disk_path": str(work),
            "job_memory_mib": 128, "job_disk_mib": 24, "runtime_seconds": 40,
            "service_urls": ["http://127.0.0.1:8787/api/health"],
        }
        reservation = peer_guard.reserve(peer_guard.DEFAULT_ROOT, policy)

    checks = []
    with reservation as lease:
        def monitor():
            # The receiver raises AdmissionDeferred when a service or capacity fuse opens.
            health = peer_guard.recheck_running(peer_guard.DEFAULT_ROOT, lease["effective_policy"])
            checks.append(health["temp_c"])

        measured = sample(work, args.rate, group, args.fixture_mib * MIB, monitor if system_trial else None)
        if system_trial:
            monitor()
    receipt = {
        "schema": "chimera.guest-write-budget/1", "uid": os.getuid(), "cgroup": str(group),
        "lane": "isolated_system_fixture" if system_trial else "guarded_build_user_service",
        "guard_in_trial": None if not system_trial else {
            "limits_verified": lease["limits_verified"], "rechecks": len(checks), "max_recheck_temp_c": max(checks),
        },
        **measured,
    }
    if args.artifact:
        if system_trial or args.artifact != Path("io-proof.json"):
            raise ValueError("unexpected output artifact")
        with args.artifact.open("x", encoding="utf-8") as file:
            json.dump(receipt, file)
    print(json.dumps(receipt))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rate", type=int, required=True, choices=RATES)
    parser.add_argument("--fixture-mib", type=int, choices=(1, 8), default=8)
    parser.add_argument("--system-fixture-release", type=Path)
    parser.add_argument("--guard-sha256")
    parser.add_argument("--artifact", type=Path)
    run(parser.parse_args())
