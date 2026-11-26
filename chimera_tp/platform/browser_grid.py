"""CHIMERA-BROWSER-GRID: Zero-RAM Lazy Shared Chromium CDP Multiplexer with Idle Auto-Reap."""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import urllib.request
import uuid
from pathlib import Path
from typing import Any


def find_browser_binary() -> str | None:
    """Locate an installed Chromium / Chrome / Edge binary on Windows or Linux."""
    candidates: list[str] = []
    if os.name == "nt":
        for base in (
            os.environ.get("PROGRAMFILES", r"C:\Program Files"),
            os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
            os.environ.get("LOCALAPPDATA", ""),
        ):
            if not base:
                continue
            candidates.extend(
                [
                    os.path.join(base, "Google", "Chrome", "Application", "chrome.exe"),
                    os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe"),
                    os.path.join(base, "Chromium", "Application", "chrome.exe"),
                ]
            )
    else:
        for name in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable"):
            found = shutil.which(name)
            if found:
                candidates.append(found)

    # Also check Playwright's bundled headless chromium cache if present
    pw_roots = [
        Path.home() / ".cache" / "ms-playwright",
        Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright" if os.name == "nt" else Path("/nonexistent"),
    ]
    for root in pw_roots:
        if root.is_dir():
            exe_name = "chrome.exe" if os.name == "nt" else "chrome"
            for hit in sorted(root.glob(f"chromium*/**/{exe_name}"), reverse=True):
                candidates.append(str(hit))
                break

    for c in candidates:
        if c and os.path.isfile(c):
            return c
    return None


class SharedBrowserGrid:
    """Maintains ONE lazy headless Chromium process (0 MB RAM when idle) shared across all apps via CDP."""

    ZERO_MEDIA_BLOCK_TYPES = ["image", "media", "font"]
    ZERO_MEDIA_BLOCK_URLS = ["*google-analytics*", "*doubleclick*", "*facebook.net*", "*.woff2", "*.mp4"]

    def __init__(self, cdp_port: int = 9785, idle_shutdown_s: float = 120.0) -> None:
        self.requested_port = int(cdp_port)
        self.cdp_port = int(cdp_port)
        self.idle_shutdown_s = float(idle_shutdown_s)
        self._lock = threading.Lock()
        self._proc: subprocess.Popen[bytes] | None = None
        self._profile_dir: str | None = None
        self._sessions: dict[str, dict[str, Any]] = {}
        self._last_activity = 0.0
        self._launches = 0
        self._binary = find_browser_binary()

    def _pick_free_port(self) -> int:
        for p in (self.requested_port, self.requested_port + 10, 0):
            s = socket.socket()
            try:
                s.bind(("127.0.0.1", p))
                chosen = int(s.getsockname()[1])
                s.close()
                return chosen
            except OSError:
                s.close()
        return 9785

    def _is_running_locked(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def _ensure_browser_locked(self) -> dict[str, Any]:
        if self._is_running_locked():
            ver = self._probe_cdp_version(self.cdp_port)
            if ver:
                return ver
        if not self._binary:
            raise RuntimeError("No Chromium/Chrome/Edge binary found on host")

        self.cdp_port = self._pick_free_port()
        self._profile_dir = tempfile.mkdtemp(prefix="chimera_cdp_")
        cmd = [
            self._binary,
            "--headless=new",
            "--disable-gpu",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-extensions",
            "--disable-background-networking",
            f"--remote-debugging-port={self.cdp_port}",
            f"--user-data-dir={self._profile_dir}",
            "about:blank",
        ]
        self._proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self._launches += 1
        self._last_activity = time.monotonic()

        deadline = time.monotonic() + 8.0
        while time.monotonic() < deadline:
            ver = self._probe_cdp_version(self.cdp_port)
            if ver:
                return ver
            if self._proc.poll() is not None:
                raise RuntimeError(f"Browser exited early with code {self._proc.returncode}")
            time.sleep(0.15)
        raise RuntimeError("Timed out waiting for shared Chromium CDP port")

    @staticmethod
    def _probe_cdp_version(port: int) -> dict[str, Any] | None:
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(f"http://127.0.0.1:{port}/json/version", timeout=0.6) as r:
                if r.status == 200:
                    return json.loads(r.read().decode("utf-8"))
        except Exception:
            return None
        return None

    def acquire_session(self, app: str = "external", zero_media: bool = True, ttl_s: float = 120.0) -> dict[str, Any]:
        t0 = time.perf_counter()
        with self._lock:
            ver = self._ensure_browser_locked()
            sid = f"cdp-{uuid.uuid4().hex[:10]}"
            now = time.monotonic()
            self._last_activity = now
            sess = {
                "session_id": sid,
                "app": str(app),
                "cdp_http_url": f"http://127.0.0.1:{self.cdp_port}",
                "ws_debugger_url": ver.get("webSocketDebuggerUrl", ""),
                "browser": ver.get("Browser", "chromium"),
                "zero_media": bool(zero_media),
                "block_resource_types": self.ZERO_MEDIA_BLOCK_TYPES if zero_media else [],
                "block_url_patterns": self.ZERO_MEDIA_BLOCK_URLS if zero_media else [],
                "expires_at": now + max(10.0, float(ttl_s)),
                "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
            }
            self._sessions[sid] = sess
            return {"ok": True, **sess}

    def release_session(self, session_id: str, shutdown_if_empty: bool = False) -> dict[str, Any]:
        with self._lock:
            existed = self._sessions.pop(str(session_id), None) is not None
            rem = len(self._sessions)
            if shutdown_if_empty and rem == 0:
                self._stop_browser_locked()
            return {"ok": True, "released": existed, "active_sessions": rem, "browser_running": self._is_running_locked()}

    def reap_idle(self) -> int:
        now = time.monotonic()
        with self._lock:
            expired = [sid for sid, s in self._sessions.items() if now >= float(s["expires_at"])]
            for sid in expired:
                self._sessions.pop(sid, None)
            if (
                self._is_running_locked()
                and not self._sessions
                and (now - self._last_activity) >= self.idle_shutdown_s
            ):
                self._stop_browser_locked()
            return len(expired)

    def _stop_browser_locked(self) -> None:
        if self._proc is not None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=2.0)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None
        if self._profile_dir:
            shutil.rmtree(self._profile_dir, ignore_errors=True)
            self._profile_dir = None

    def status(self) -> dict[str, Any]:
        self.reap_idle()
        with self._lock:
            running = self._is_running_locked()
            return {
                "ok": True,
                "binary_found": bool(self._binary),
                "binary": self._binary or "",
                "running": running,
                "cdp_http_url": f"http://127.0.0.1:{self.cdp_port}" if running else "",
                "active_sessions": len(self._sessions),
                "launches": self._launches,
                "idle_ram_mb": 0.0 if not running else None,
            }

    def close(self) -> None:
        with self._lock:
            self._sessions.clear()
            self._stop_browser_locked()
