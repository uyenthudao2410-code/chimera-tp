"""Read-only Radar and host samples bracketed by the workstation performance clock."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import http.client
import json
from pathlib import Path
import re
import sys
import threading
import time
from urllib.parse import urlsplit

from measure_peer_service_slo import observation_channel, probe


def clock_ms():
    return time.perf_counter_ns() / 1_000_000


def sync_linux(request, count):
    """The receiver reads its monotonic clock strictly inside the measured request."""
    spans = []
    for _ in range(count):
        sent = clock_ms()
        remote = request("stamp")["end_ns"] / 1_000_000
        received = clock_ms()
        spans.append({"sent_ms": sent, "linux_ms": remote, "received_ms": received})
    return spans


def windows_get(endpoint, radar):
    url = urlsplit(endpoint)
    cls = http.client.HTTPSConnection if url.scheme == "https" else http.client.HTTPConnection
    conn = cls(url.hostname, url.port, timeout=2.5)
    route = (url.path or "/") + ("?" + url.query if url.query else "")
    started = clock_ms()
    try:
        conn.request("GET", route, headers={"Connection": "close"})
        with conn.getresponse() as response:
            limit = 2048 if radar else 1_048_576
            body = response.read(limit + 1)
            elapsed = clock_ms() - started
            if not 200 <= response.status < 300 or len(body) > limit:
                raise ValueError("workstation_http_status_or_body_limit")
            if radar:
                obj = json.loads(body)
                if (response.headers.get_content_type() != "application/json" or obj.get("ok") is not True
                        or not isinstance(obj.get("version"), str) or not obj["version"]):
                    raise ValueError("workstation_radar_body_invalid")
            return {"http_ms": elapsed}
    finally:
        conn.close()


def sample_loop(operation, stopping):
    rows = []
    while not stopping.is_set():
        begin = clock_ms()
        try:
            record = operation()
        except (OSError, ValueError, RuntimeError, KeyError, http.client.HTTPException) as exc:
            record = {"error": type(exc).__name__}
        end = clock_ms()
        rows.append({"start_ms": begin, "end_ms": end, **record})
        # Each lane issues at most five requests per second and has one request in flight.
        stopping.wait(max(0, (200 - (end - begin)) / 1000))
    return rows


def observe(peer, override):
    with observation_channel(peer) as (request, port, metadata):
        automatic = not override
        endpoint = override or f"http://127.0.0.1:{port}{metadata['health_path']}"
        url = urlsplit(endpoint)
        if url.scheme not in ("http", "https") or not url.hostname or url.username or url.password:
            raise ValueError("expected HTTP(S) service without embedded credentials")
        opening = sync_linux(request, 3)
        probe.emit({"type": "ready", "service": metadata,
                    "windows_endpoint": "Radar /api/health via SSH loopback forward" if automatic else endpoint,
                    "source_sha256": hashlib.sha256(Path(probe.__file__).read_bytes()).hexdigest()})
        if sys.stdin.readline().strip() != "start":
            return
        stopping = threading.Event()
        with ThreadPoolExecutor(max_workers=2) as pool:
            linux = pool.submit(sample_loop, lambda: request("sample"), stopping)
            windows = pool.submit(sample_loop, lambda: windows_get(endpoint, automatic), stopping)
            probe.emit({"type": "started", "clock_ms": clock_ms()})
            try:
                sys.stdin.readline()
            finally:
                stopping.set()
            linux_rows, windows_rows = linux.result(), windows.result()
        closing = sync_linux(request, 2)
        identity = request("identity")
        probe.emit({"type": "result", "linux": linux_rows, "windows": windows_rows,
                    "linux_sync_open": opening, "linux_sync_close": closing, "identity": identity})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--peer", required=True)
    parser.add_argument("--service-url")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", args.peer):
        parser.error("invalid configured SSH host")
    observe(args.peer, args.service_url)
