"""Receiver-local service used to exercise admission, waiting and a fresh admission on retry."""

from __future__ import annotations

from contextlib import contextmanager
import base64
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import shlex
import subprocess
import sys
import threading
from uuid import uuid4


_HEALTH_PROBE = """
import http.server
import json
import sys
import threading

healthy = threading.Event()
counts = {"200": 0, "503": 0}

class Health(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        code = 200 if healthy.is_set() else 503
        counts[str(code)] += 1
        self.send_response(code)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *args):
        pass

with http.server.HTTPServer(("127.0.0.1", 0), Health) as server:
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(json.dumps({"url": f"http://127.0.0.1:{server.server_port}/health"}), flush=True)
    try:
        for line in sys.stdin:
            if line.strip() == "healthy":
                healthy.set()
            print(json.dumps(counts), flush=True)
    finally:
        server.shutdown()
        thread.join()
"""


@contextmanager
def receiver_health(peer):
    if not re.fullmatch(r"[\w][.\w-]*", peer, re.ASCII):
        raise ValueError("invalid SSH peer")
    cmd = ["ssh", "-T", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
           "-o", "ConnectTimeout=8", peer, shlex.join(["python3", "-I", "-B", "-S", "-u", "-c", _HEALTH_PROBE])]
    with subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)) as proc:
        lines = queue.Queue()

        def receive():
            for line in proc.stdout:
                lines.put(line)
            lines.put(None)

        reader = threading.Thread(target=receive, daemon=True)
        reader.start()

        def reply(command=None):
            if command:
                proc.stdin.write(command + "\n")
                proc.stdin.flush()
            line = lines.get(timeout=15)
            if line is None:
                raise RuntimeError("receiver health fixture exited before acknowledging request")
            return json.loads(line)

        try:
            yield reply()["url"], reply
        finally:
            proc.stdin.close()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
            reader.join(timeout=3)


def _cli(outbox, *args, expected=0):
    proc = subprocess.run([sys.executable, "-B", "-m", "chimera_tp", "swarm-queue",
                           "--state-dir", str(outbox), *args], capture_output=True, timeout=95,
                          cwd=Path(__file__).resolve().parents[1],
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if proc.returncode != expected:
        raise RuntimeError(f"swarm-queue {args[0]} returned {proc.returncode}: {proc.stdout[-800:]!r}")
    return json.loads(proc.stdout)


def verify_defer_resume(root, peer, client, coordinator, engine):
    outbox = root / "queue-recovery"
    coordinator.queue_dir = outbox
    job = f"cas-queue-{uuid4().hex}"
    original = [os.urandom(3149), os.urandom(8033)]
    specs = [{"step_key": f"xor-{i}", "op": "transform_bytes", "params": {"mask": 23},
              "blocks": [{"b64": base64.b64encode(raw).decode("ascii")}]}
             for i, raw in enumerate(original)]
    with receiver_health(peer) as (url, observe):
        engine.cas_admission_policy = {"service_urls": [url]}
        submitted = client.exile_handoff(job_id=job, steps=specs, prefer_target=peer)
        waiting = _cli(outbox, "list")["pending"]
        if not (submitted.get("state") == "deferred" and len(waiting) == 1 and waiting[0]["job_id"] == job):
            raise RuntimeError(f"expected a single retained job: {submitted}, {waiting}")
        entry = waiting[0]
        if entry["id"] != submitted["queue"]["id"] or entry["kind"] != "exile_handoff":
            raise RuntimeError("SDK and CLI disagree about the job ticket")
        if client.exile_receipts(job_id=job)["receipts"]:
            raise RuntimeError("job committed while receiver health check was failing")
        key = entry["id"]
        denied = _cli(outbox, "retry", key, expected=75)
        retained, = _cli(outbox, "list")["pending"]
        if denied.get("state") != "deferred" or retained["id"] != key:
            raise RuntimeError("unhealthy retry lost or replaced the original ticket")
        # Discard the client's input. The next process can resume from the ticket alone.
        specs.clear()
        counts_before = observe("counts")
        observe("healthy")
        result = _cli(outbox, "retry", key)
        counts_after = observe("counts")
        if not result.get("ok") or _cli(outbox, "list")["pending"] or result["job_id"] != job:
            raise RuntimeError("retry did not finish the frozen job")
        if counts_before["503"] < 2 or counts_after["200"] == 0:
            raise RuntimeError("missing independent receiver probe observations")
    committed = {r["step_key"]: r for r in client.exile_receipts(job_id=job)["receipts"]}
    if len(committed) != len(original):
        raise RuntimeError("unexpected number of committed steps")
    for i, raw in enumerate(original):
        row = committed[f"xor-{i}"]
        data = bytes(value ^ 23 for value in raw)
        key_hash = row["output_cas_hash"]
        local = coordinator.cas.objects_dir / key_hash[:2] / key_hash
        if (row["node_id"] != peer or row["output_digest"] != hashlib.sha256(data).hexdigest()
                or local.read_bytes() != data):
            raise RuntimeError("resumed journal or CAS object differs from original input")
    return {"job_id": job, "ticket_id": key, "reason": waiting[0]["reason"],
            "retained_bytes": entry["wire_bytes"], "steps": len(committed), "queue_after_retry": 0,
            "generations": {k: v["generation"] for k, v in committed.items()},
            "output_sha256": {k: v["output_digest"] for k, v in committed.items()},
            "http_503_at_receiver_before_recovery": counts_before["503"],
            "http_200_at_receiver_after_recovery": counts_after["200"]}
