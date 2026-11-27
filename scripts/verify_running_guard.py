"""Trip the live peer guard using a private loopback fixture, then verify recovery."""

import argparse
import base64
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from chimera_tp.platform.guarded_build import _package


TRIAL = """
import http.server, json, os, pathlib, shlex, socketserver, sys, tempfile, threading, time
sys.path.insert(0, sys.argv[1])
from chimera_tp.platform import build_worker, peer_guard

with tempfile.TemporaryDirectory(prefix="chimera-guard-fixture-") as raw:
    folder = pathlib.Path(raw)
    marker = folder / "started"
    completed = folder / "done"
    outage = threading.Event()
    outage.set()
    observations = []

    class Service(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            failing = outage.is_set() and marker.exists()
            if failing:
                observations.append(time.monotonic_ns())
            self.send_response(503 if failing else 200)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *args):
            pass

    with http.server.ThreadingHTTPServer(("127.0.0.1", 0), Service) as service:
        thread = threading.Thread(target=service.serve_forever, daemon=True)
        thread.start()
        policy = {"disk_path":str(pathlib.Path.home()),
                  "service_urls":["http://127.0.0.1:%d/" % service.server_port]}
        command = shlex.join([sys.executable, "-I", "-B", "-S", "-c",
                              "from pathlib import Path;import time;Path('started').touch();"
                              "time.sleep(2.5);Path('done').write_text('completed')"])

        def work():
            with peer_guard.reserve(peer_guard.DEFAULT_ROOT, policy) as admission:
                def monitor():
                    return peer_guard.recheck_running(peer_guard.DEFAULT_ROOT, admission["effective_policy"])
                return build_worker._run(command, folder, 8, env=os.environ.copy(),
                                         monitor=monitor, repeatable=True)

        try:
            first = work()
            returned = time.monotonic_ns()
            if first.get("state") != "deferred" or first["ok"] or completed.exists() or not observations:
                raise RuntimeError("running build continued through the fixture outage")
            outage.clear()
            second = work()
            if not second["ok"] or completed.read_text() != "completed":
                raise RuntimeError("healthy receiver did not recover")
            print(json.dumps({"ok": True, "fixture":"private Linux loopback HTTP service, isolated job files",
                              "first_state":first["state"], "first_error":first["error"],
                              "first_artifact_created":False,
                              "first_503_to_return_ms":round((returned-observations[0])/1e6, 2),
                              "retry_succeeded":True, "retry_health_samples":second["runtime_guard"]["completed_samples"]}))
        finally:
            service.shutdown()
            thread.join(timeout=2)
"""

BOOT = """
import base64,json,pathlib,subprocess,sys,tempfile
data=sys.stdin.buffer.read(200001)
if len(data)>200000: raise ValueError("package too large")
with tempfile.TemporaryDirectory(prefix="chimera-guard-test-worker-") as scratch:
    archive=pathlib.Path(scratch,"worker.zip")
    archive.write_bytes(data)
    sys.path.insert(0,str(archive))
    from chimera_tp.platform import build_worker,peer_guard
    policy=peer_guard.launch_policy(peer_guard.DEFAULT_ROOT,build_worker.guard_policy(False))
    worker=[sys.executable,"-I","-B","-S","-c",base64.b64decode(sys.argv[1]).decode(),str(archive)]
    raise SystemExit(subprocess.call(peer_guard.limited_command(worker,policy)))
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--peer", default="svhome")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.@-]{0,200}", args.peer):
        raise ValueError("invalid SSH peer")
    src = base64.b64encode(TRIAL.encode()).decode("ascii")
    remote = shlex.join(["python3", "-I", "-B", "-S", "-c", BOOT, src])
    proc = subprocess.run(["ssh", "-T", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
                           "-o", "ConnectTimeout=5", args.peer, remote],
                          input=_package(), capture_output=True, timeout=45)
    if proc.returncode:
        raise RuntimeError(proc.stderr.decode("utf-8", "replace")[-1200:])
    result = json.loads(proc.stdout)
    if result.get("ok") is not True:
        raise ValueError("recovery verification failed")
    result["peer"] = args.peer
    report = json.dumps(result, indent=2) + "\n"
    if args.out:
        args.out.write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
