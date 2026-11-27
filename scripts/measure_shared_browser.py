"""Compare isolated and shared Chromium profiles with the same two local app windows."""

import argparse
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import statistics
import subprocess
import tempfile
import threading
import time
from urllib.parse import quote
import urllib.request

import psutil
from workspace_browser import launch_plan


class Page(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"<!doctype html><title>Workspace measurement</title><p>Ready</p>"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        if self.path in ("/one", "/two"):
            self.server.seen.add(self.path)

    def log_message(self, *args):
        pass


@contextmanager
def page_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Page)
    server.seen = set()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()


def measure(browser: Path, root: Path, shared: bool) -> dict:
    roots = []
    with page_server() as server:
        try:
            for page in ("one", "two"):
                profile = root / ("shared" if shared else page)
                profile.mkdir(exist_ok=True)
                url = f"http://127.0.0.1:{server.server_port}/{page}"
                if shared and roots:
                    port = int((profile / "DevToolsActivePort").read_text().splitlines()[0])
                    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                    request = urllib.request.Request(
                        f"http://127.0.0.1:{port}/json/new?{quote(url, safe='')}", method="PUT"
                    )
                    with opener.open(request, timeout=5) as response:
                        assert json.load(response)["type"] == "page"
                else:
                    command, = launch_plan(browser, profile, [url])
                    command[1:1] = ["--headless=new", "--remote-debugging-port=0",
                                    "--remote-debugging-address=127.0.0.1", "--no-proxy-server",
                                    "--disable-background-networking", "--disable-extensions",
                                    "--no-default-browser-check"]
                    p = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    roots.append(psutil.Process(p.pid))
                until = time.monotonic() + 18
                while f"/{page}" not in server.seen and time.monotonic() < until:
                    time.sleep(0.1)
                if f"/{page}" not in server.seen:
                    raise RuntimeError(f"Browser did not load {page}")
            time.sleep(1)
            processes = {}
            for process in roots:
                if process.is_running():
                    for child in [process, *process.children(recursive=True)]:
                        processes[child.pid] = child
            groups = 0
            private = 0
            for process in processes.values():
                try:
                    private += process.memory_info().private
                    if process.exe().lower() == str(browser.resolve()).lower() and not any(
                        arg.startswith("--type=") for arg in process.cmdline()
                    ):
                        groups += 1
                except psutil.NoSuchProcess:
                    continue
            return {"private_mib": round(private / 2**20, 2), "processes": len(processes),
                    "browser_roots": groups, "pages_loaded": len(server.seen)}
        finally:
            # Only this run's independent, disposable profiles and their children.
            owned = {}
            for p in roots:
                if p.is_running():
                    for child in [*p.children(recursive=True), p]:
                        owned[child.pid] = child
            for p in owned.values():
                try:
                    p.terminate()
                except psutil.NoSuchProcess:
                    pass
            psutil.wait_procs(list(owned.values()), timeout=6)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser", type=Path, required=True)
    parser.add_argument("--pairs", type=int, default=3)
    args = parser.parse_args()
    rows = []
    for pair in range(args.pairs):
        for shared in ((False, True) if pair % 2 == 0 else (True, False)):
            with tempfile.TemporaryDirectory(prefix="chimera-pwa-") as tmp:
                rows.append({"pair": pair + 1, "shared": shared, **measure(args.browser, Path(tmp), shared)})
    print(json.dumps({"rows": rows, "median_private_mib": {
        str(s): statistics.median(r["private_mib"] for r in rows if r["shared"] == s)
        for s in (False, True)}}))


if __name__ == "__main__":
    main()
