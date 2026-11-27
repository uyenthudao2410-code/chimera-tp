"""Capture a disposable Linux browser tab through a loopback-only SSH tunnel."""

import argparse
import hashlib
import io
import json
import re
import shlex
import socket
import subprocess
import time
import urllib.request

from PIL import Image
from playwright.sync_api import sync_playwright


REMOTE = """
import glob, os, pathlib, shutil, subprocess, sys, tempfile, time
paths = sorted(glob.glob(str(pathlib.Path.home()/'.cache/ms-playwright/chromium_headless_shell-*/*/chrome-headless-shell')),
               reverse=True)
if not paths:
    raise SystemExit('no headless chromium installed')
with tempfile.TemporaryDirectory(prefix='chimera-surface-') as path:
    executable = pathlib.Path(paths[0])
    profile = path
    command = [str(executable)]
    if shutil.which('bwrap'):
        profile = '/profile'
        command = ['bwrap', '--unshare-all', '--share-net', '--die-with-parent',
                   '--ro-bind', '/usr', '/usr', '--ro-bind','/etc','/etc',
                   '--symlink','usr/bin','/bin','--symlink','usr/lib','/lib',
                   '--symlink','usr/lib64','/lib64','--dev','/dev','--proc','/proc',
                   '--tmpfs','/tmp','--dir','/dev/shm','--tmpfs','/dev/shm',
                   '--ro-bind',str(executable.parent),'/browser','--bind',path,profile,
                   '--setenv','HOME','/tmp','--uid',str(os.getuid()),'--gid',str(os.getgid()),
                   '/browser/'+executable.name]
    browser = subprocess.Popen([*command, '--headless', '--no-first-run', '--disable-background-networking',
                                '--remote-debugging-address=127.0.0.1', '--remote-debugging-port=0',
                                '--user-data-dir='+profile, 'about:blank'], stdout=subprocess.DEVNULL)
    try:
        active = pathlib.Path(path)/'DevToolsActivePort'
        for _ in range(100):
            if browser.poll() is not None:
                raise SystemExit('sandboxed browser exited with '+str(browser.returncode))
            if active.exists() and active.read_text().splitlines():
                print(active.read_text().splitlines()[0], flush=True)
                break
            time.sleep(.1)
        else:
            raise SystemExit('browser startup timed out')
        sys.stdin.buffer.read(1)
    finally:
        browser.terminate()
        try:
            browser.wait(4)
        except subprocess.TimeoutExpired:
            browser.kill()
            browser.wait()
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--peer", default="svhome")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", args.peer):
        parser.error("expected SSH hostname")
    ssh = ["ssh", "-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5"]
    # A dedicated browser profile prevents attaching to open pages or credentials.
    control = subprocess.Popen([*ssh, args.peer, "python3 -u -c " + shlex.quote(REMOTE)],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    tunnel = None
    try:
        line = control.stdout.readline().strip()
        if not line.isdigit():
            raise RuntimeError("Remote Chromium did not open its isolated debugging endpoint")
        remote_port = int(line)
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            local_port = probe.getsockname()[1]
        tunnel = subprocess.Popen([*ssh, "-N", "-o", "ExitOnForwardFailure=yes", "-L",
                                   f"127.0.0.1:{local_port}:127.0.0.1:{remote_port}", args.peer])
        url = f"http://127.0.0.1:{local_port}"
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for _ in range(40):
            try:
                with opener.open(url + "/json/version", timeout=1) as response:
                    version = json.load(response)["Browser"]
                break
            except OSError:
                time.sleep(0.1)
        else:
            raise RuntimeError("Dedicated browser is unreachable")
        colors = [(35, 67, 99), (140, 95, 12), (19, 130, 71)]
        samples = []
        with sync_playwright() as driver:
            browser = driver.chromium.connect_over_cdp(url)
            page = browser.contexts[0].new_page()
            page.set_viewport_size({"width": 640, "height": 360})
            for color in colors:
                start = time.perf_counter()
                page.set_content(f'<body style="background:rgb{color}">CHIMERA test</body>')
                frame = page.screenshot(type="jpeg", quality=65)
                with Image.open(io.BytesIO(frame)) as img:
                    actual = img.convert("RGB").getpixel((320, 180))
                    assert img.size == (640, 360) and max(abs(a-b) for a,b in zip(actual,color)) <= 5
                samples.append({"bytes": len(frame), "ms": round((time.perf_counter()-start)*1000,2),
                                "sha256": hashlib.sha256(frame).hexdigest()})
            page.close()
            browser.close()
        print(json.dumps({"peer":args.peer, "browser":version, "codec":"JPEG", "frames":samples}))
    finally:
        control.stdin.close()
        if tunnel:
            tunnel.terminate()
            tunnel.wait(timeout=5)
        control.wait(timeout=10)


if __name__ == "__main__":
    main()
