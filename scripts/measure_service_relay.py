"""Test a loopback Rust relay through an SSH forward to a peer's existing HTTP anchor."""

import argparse
import json
from pathlib import Path
import re
import socket
import statistics
import subprocess
import time
import urllib.request

import psutil


def discovery(opener, port: int) -> tuple[tuple, float]:
    start = time.perf_counter()
    with opener.open(f"http://127.0.0.1:{port}/.well-known/chimera.json", timeout=5) as response:
        value = json.load(response)
    return (value["node_name"], value["schema"], value["version"]), (time.perf_counter() - start) * 1000


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--relay", type=Path, required=True)
    parser.add_argument("--peer", default="svhome")
    parser.add_argument("--samples", type=int, default=15)
    args = parser.parse_args()
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]*", args.peer):
        parser.error("expected SSH hostname")
    with socket.socket() as allocator:
        allocator.bind(("127.0.0.1", 0))
        ssh_port = allocator.getsockname()[1]
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    ssh = subprocess.Popen(["ssh", "-N", "-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
                            "-o", "ExitOnForwardFailure=yes", "-L",
                            f"127.0.0.1:{ssh_port}:127.0.0.1:9780", args.peer])
    relay = None
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and ssh.poll() is None:
            try:
                identity, _ = discovery(opener, ssh_port)
                break
            except OSError:
                time.sleep(0.15)
        else:
            raise RuntimeError("SSH local forward failed")
        relay = subprocess.Popen([str(args.relay), "127.0.0.1:0", f"127.0.0.1:{ssh_port}"],
                                 stdout=subprocess.PIPE, text=True)
        port = int(relay.stdout.readline().strip().rsplit(":", 1)[1])
        measurements = {"ssh_only": [], "via_relay": []}
        for i in range(args.samples):
            for name in (("ssh_only", "via_relay") if i % 2 == 0 else ("via_relay", "ssh_only")):
                result, ms = discovery(opener, ssh_port if name == "ssh_only" else port)
                if result != identity:
                    raise ValueError("Peer identity changed during test")
                measurements[name].append(round(ms, 3))
        mem = {name: round(psutil.Process(child.pid).memory_info().private / 2**20, 2)
               for name, child in (("ssh", ssh), ("rust", relay))}
        print(json.dumps({"peer": args.peer, "identity": identity, "bytes_exe": args.relay.stat().st_size,
                          "median_ms": {key: statistics.median(v) for key, v in measurements.items()},
                          "windows_private_mib": mem, "samples_ms": measurements}))
    finally:
        for child in (relay, ssh):
            if child and child.poll() is None:
                child.terminate()
                child.wait(timeout=6)


if __name__ == "__main__":
    main()
