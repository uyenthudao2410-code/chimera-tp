"""Measure a disposable daemon through its real CLI, including agent reads of a build log."""
from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import http.client
import json
import os
from pathlib import Path
import queue
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time


def run_service(root: Path, ops: Path) -> int:
    """Give the CLI a graceful stop signal when the parent closes its pipe."""
    import faulthandler
    import runpy
    import signal

    def stop_at_eof():
        sys.stdin.buffer.read(1)
        signal.raise_signal(signal.SIGINT)

    threading.Thread(target=stop_at_eof, daemon=True).start()
    sys.path.insert(0, str(root))
    sys.argv = ["chimera_tp", "daemon", "--ops-dir", str(ops), "--bind", "127.0.0.1:0", "--no-seed"]
    with (ops / "thread-stacks.txt").open("w", encoding="utf-8") as trace:
        faulthandler.dump_traceback_later(18, file=trace)
        try:
            runpy.run_module("chimera_tp", run_name="__main__")
        finally:
            faulthandler.cancel_dump_traceback_later()
    return 0


def request(port, path, body=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=45)
    try:
        raw = None if body is None else json.dumps(body).encode()
        conn.request("GET" if raw is None else "POST", path, raw, {"Content-Type": "application/json"})
        res = conn.getresponse()
        data = res.read(1024 * 1024 + 1)
        if res.status != 200 or len(data) > 1024 * 1024:
            raise RuntimeError(f"{path}: HTTP {res.status}, {len(data)} bytes")
        return json.loads(data)
    finally:
        conn.close()


def seed_vsa(database, count):
    """Construct the original on-disk schema without warming the measured process."""
    normal = bytes([255]) * 1250
    winner = bytes(1250)
    with closing(sqlite3.connect(database)) as db, db:
        db.execute("CREATE TABLE vsa_items(item_id TEXT PRIMARY KEY,domain TEXT NOT NULL,text TEXT NOT NULL,"
                   "payload_json TEXT NOT NULL,vsa_blob BLOB NOT NULL,reward REAL NOT NULL,updated_at TEXT NOT NULL)")
        rows = ((f"legacy-{i}", "fixture", f"module {i}", json.dumps({"n": i, "note": "đo " * 180},
                 ensure_ascii=False), winner if i == count - 1 else normal, 1.0, "2025-01-01")
                for i in range(count))
        db.executemany("INSERT INTO vsa_items VALUES(?,?,?,?,?,?,?)", rows)


def measure(root: Path, vsa_rows=0, *, daily=False):
    root = root.resolve(strict=True)
    if not (root / "chimera_tp" / "cli.py").is_file():
        raise ValueError("missing package CLI in selected source tree")
    stages = []
    daily_runs = []
    tmpfs = Path("/dev/shm")
    scratch = (tmpfs if sys.platform.startswith("linux") and os.access(tmpfs, os.W_OK)
               and shutil.disk_usage(tmpfs).free >= 64 * 1024**2 else None)
    with tempfile.TemporaryDirectory(prefix="chimera-cli-rss-", dir=scratch) as folder:
        ops = Path(folder)
        config = dict(node_name="rss-cli", role="server", dashboard_bind="127.0.0.1:0",
                      beam_port=0, rpc_v4_port=0, rpc_v6_port=-1, query_port=0,
                      immortal_v4_port=0, immortal_v6_port=-1, warp_port=-1, edge_proxy_port=-1,
                      nat_punch_port=0, phantom_enabled=False, peer_ipv4="", peer_ipv6="",
                      allowed_query_roots=[folder], search_roots=[], edge_targets={})
        (ops / "config.json").write_text(json.dumps(config), encoding="utf-8")
        if vsa_rows:
            seed_vsa(ops / "vsa_memory.db", vsa_rows)
        log = ops / "compile.log"
        line = "compile module — đường dẫn build " + "x" * 79
        block = ((line + "\n") * 256).encode()
        chunks = 768
        content_hash = hashlib.blake2s(digest_size=12)
        with log.open("xb") as output:
            for _ in range(chunks):
                output.write(block)
                content_hash.update(block)

        cmd = [sys.executable, "-I", "-B", "-S", str(Path(__file__).resolve()),
               "--service", str(root), str(ops)]
        env = dict(os.environ, HOME=folder, USERPROFILE=folder, LOCALAPPDATA=folder, APPDATA=folder)
        with tempfile.TemporaryFile(mode="w+b") as errors, subprocess.Popen(
            cmd, cwd=root, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=errors, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
        ) as child:
            try:
                output_lines = queue.Queue()

                def collect_output():
                    for raw in child.stdout:
                        output_lines.put(raw.decode("utf-8", "replace").strip())
                    output_lines.put(None)

                reader = threading.Thread(target=collect_output, daemon=True)
                reader.start()
                end = time.monotonic() + 25
                while True:
                    message = output_lines.get(timeout=max(.01, end - time.monotonic()))
                    if message is None:
                        raise RuntimeError("CLI exited before opening its loopback dashboard")
                    match = re.search(r"Daemon listening at http://127\.0\.0\.1:(\d+)", message)
                    if match:
                        port = int(match.group(1))
                        break

                def mark(name):
                    beacon = request(port, "/.well-known/chimera.json")
                    if beacon["node_name"] != "rss-cli" or beacon["pid"] != child.pid:
                        raise RuntimeError("probe connected to a different process")
                    memory = beacon["zero_weight"]
                    stages.append({"stage": name, "rss_bytes": memory["daemon_rss_bytes"],
                                   "peak_bytes": memory["daemon_peak_rss_bytes"]})

                mark("cli_beacon")
                if not request(port, "/api/health").get("ok"):
                    raise RuntimeError("health endpoint failed")
                request(port, "/v1/truth-matrix")
                mark("health_truth")
                result = request(port, "/v1/agent/xray-batch", {
                    "cwd": folder, "compact": False,
                    "ops": [{"op": "file_slice", "path": str(log), "tail_lines": 2, "numbered": False}],
                })["results"][0]
                if (not result["ok"] or result["total_lines"] != chunks * 256
                        or result["hash"] != content_hash.hexdigest()
                        or result["text"] != line + "\n" + line):
                    raise RuntimeError("tail text, line count or BLAKE2s differed from the fixture")
                mark("build_log_tail")
                if vsa_rows:
                    if request(port, "/api/vsa/stats")["item_count"] != vsa_rows:
                        raise RuntimeError("incorrect persisted VSA record count")
                    mark("vsa_open_populated")
                    ranked = request(port, "/api/vsa/recall", {
                        "domain": "fixture", "top_k": 5, "query_vsa_hex": bytes(1250).hex()
                    })
                    hits = ranked["matches"]
                    expected = [vsa_rows - 1, 0, 1, 2, 3]
                    if (ranked["scanned"] != vsa_rows or ranked["total_items"] != vsa_rows
                            or [r["item_id"] for r in hits] != [f"legacy-{i}" for i in expected]
                            or [r["similarity"] for r in hits] != [1.0, 0.0, 0.0, 0.0, 0.0]
                            or any(r["payload"] != {"n": i, "note": "đo " * 180}
                                   for r, i in zip(hits, expected))):
                        raise RuntimeError("persistent recall count, stable ranking or payload mismatch")
                    mark("vsa_search_populated")
                if daily:
                    for _ in range(2):
                        result = request(port, "/api/run?sync=1", {})
                        local = result["local"]
                        if (result["node_name"] != "rss-cli" or result["trigger"] != "manual_dashboard"
                                or not all(local[key] for key in ("gfni_ok", "wormhole_ok", "telepathy_ok", "wan_5pct_ok"))):
                            raise RuntimeError("isolated daily transport did not pass all payload checks")
                        if "wormhole_transfer_bytes" in local and (
                            local["wormhole_transfer_bytes"] != 16 * 1024**2
                            or local["tcp_loopback_verified_bytes"] != 16 * 1024**2
                        ):
                            raise RuntimeError("daily transport lost bytes")
                        daily_runs.append({
                            "run_id": result["run_id"], "genome": result["genome_id"],
                            "wormhole_ok": local["wormhole_ok"], "ring_bytes": local.get("wormhole_ring_bytes"),
                            "wormhole_transfer_bytes": local.get("wormhole_transfer_bytes"),
                            "tcp_loopback_verified_bytes": local.get("tcp_loopback_verified_bytes"),
                            "kernel_peak_at_health_report": result["zero_weight"]["daemon_peak_rss_bytes"],
                        })
                        mark("daily_transport_" + str(len(daily_runs)))
            except (OSError, RuntimeError, queue.Empty) as exc:
                trace = ops / "thread-stacks.txt"
                if trace.is_file():
                    details = [line for line in trace.read_text(errors="replace").splitlines()
                               if "agent_symbiont" in line or "subprocess.py" in line or
                               "agent_probe.py" in line or "measure_daemon_cli.py" in line]
                    if hasattr(exc, "add_note"):
                        exc.add_note("\n".join(details))
                raise
            finally:
                child.stdin.close()
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    child.terminate()
                    child.wait(timeout=5)
                child.stdout.close()
            if child.returncode:
                errors.seek(0)
                raise RuntimeError(f"disposable daemon exit {child.returncode}: "
                                   + errors.read(2000).decode("utf-8", "replace"))
        size = log.stat().st_size
    return {"host": sys.platform, "pid": child.pid, "stages": stages, "fixture_bytes": size,
            "persisted_vsa_rows": vsa_rows, "daily_runs": daily_runs,
            "fixture_lines": chunks * 256, "verified_hash": content_hash.hexdigest(),
            "peak_mib": max(s["peak_bytes"] for s in stages) / 2**20,
            "temp_removed": not Path(folder).exists()}


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--service":
        raise SystemExit(run_service(Path(sys.argv[2]), Path(sys.argv[3])))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--vsa-rows", type=int, choices=(0, 6144), default=0)
    parser.add_argument("--daily", action="store_true", help="Exercise two full daily cycles inside the disposable daemon")
    args = parser.parse_args()
    sample = measure(args.root, args.vsa_rows, daily=args.daily)
    with args.out.open("x", encoding="utf-8") as output:
        json.dump(sample, output, indent=2)
        output.write("\n")
    print(json.dumps({s["stage"]: round(s["peak_bytes"] / 2**20, 2) for s in sample["stages"]}))
