"""CHIMERA UI Wire-to-First-Interactive & Headless Browser Benchmark."""

from __future__ import annotations

import gzip
import json
import os
import py_compile
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from chimera_tp.autopilot import OpsConfig
from chimera_tp.dashboard import ChimeraDaemon
from chimera_tp.universe_ui import UNIVERSE_DASHBOARD_HTML, build_kolmogorov_packed_html

OUT_JSON = ROOT / "tasks" / "ui_tti_bench.json"
CREATION_FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


def _fetch_http(url: str, accept_gzip: bool = True) -> dict[str, Any]:
    headers = {"Accept-Encoding": "gzip"} if accept_gzip else {}
    req = urllib.request.Request(url, headers=headers)
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=10.0) as resp:
        data = resp.read()
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        return {
            "status": resp.status,
            "wire_bytes": len(data),
            "content_encoding": resp.headers.get("Content-Encoding", ""),
            "x_chimera_packed": resp.headers.get("X-Chimera-Packed", ""),
            "elapsed_ms": round(elapsed_ms, 2),
        }


def _check_js_syntax() -> dict[str, Any]:
    py_compile.compile(str(ROOT / "chimera_tp" / "universe_ui.py"), doraise=True)
    scripts = re.findall(r"<script>(.*?)</script>", UNIVERSE_DASHBOARD_HTML, re.S)
    node = shutil.which("node")
    if not node or len(scripts) != 1:
        return {
            "node_checked": False,
            "node_path": node,
            "script_tags": len(scripts),
            "ok": len(scripts) == 1,
        }
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
        f.write(scripts[0])
        jsp = f.name
    try:
        t0 = time.perf_counter()
        proc = subprocess.run(
            [node, "--check", jsp],
            capture_output=True,
            text=True,
            timeout=10.0,
            creationflags=CREATION_FLAGS,
        )
        return {
            "node_checked": True,
            "ok": proc.returncode == 0,
            "check_ms": round((time.perf_counter() - t0) * 1000.0, 2),
            "stderr": proc.stderr.strip(),
        }
    finally:
        os.unlink(jsp)


def _run_playwright_check(base_url: str) -> dict[str, Any]:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        return {"available": False, "engine": "playwright", "reason": f"import failed: {exc}"}

    pages_out: dict[str, Any] = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            for label, path in (("root", "/"), ("packed", "/?packed=1")):
                page = browser.new_page(viewport={"width": 1440, "height": 900})
                console_errors: list[str] = []
                page_errors: list[str] = []
                page.on(
                    "console",
                    lambda m, out=console_errors: out.append(f"{m.type}: {m.text}")
                    if m.type == "error"
                    else None,
                )
                page.on("pageerror", lambda e, out=page_errors: out.append(str(e)))

                t0 = time.perf_counter()
                page.goto(f"{base_url}{path}", wait_until="domcontentloaded")
                page.wait_for_function(
                    "() => !!(window.__CORTEX__ && document.querySelectorAll('#sil-list .kpi').length === 3 && document.querySelectorAll('#mesh-svg .nd').length === 6)",
                    timeout=10000,
                )
                first_interactive_ms = (time.perf_counter() - t0) * 1000.0

                page.wait_for_function(
                    "() => document.querySelectorAll('#c-ch .cc').length > 0 && /SYNC #[1-9]/.test((document.getElementById('hb-l')||{}).textContent||'')",
                    timeout=10000,
                )
                pulse_hydrated_ms = (time.perf_counter() - t0) * 1000.0

                dom_state = page.evaluate(
                    """() => {
                        const nav = performance.getEntriesByType('navigation')[0];
                        const charts = ['c-ram', 'c-kal', 'c-ph', 'c-ht'].map(id => {
                            const c = document.getElementById(id);
                            return {id, width: c ? c.width : 0, height: c ? c.height : 0};
                        });
                        return {
                            title: document.title,
                            cortex: window.__CORTEX__ || null,
                            domContentLoadedMs: nav ? Math.round(nav.domContentLoadedEventEnd * 100) / 100 : null,
                            loadEventMs: nav ? Math.round(nav.loadEventEnd * 100) / 100 : null,
                            kpiGroups: ['#sil-list', '#net-kpi', '#gpu-kpi', '#sub-kpi'].map(
                                s => document.querySelectorAll(s + ' .kpi').length
                            ),
                            svgNodes: document.querySelectorAll('#mesh-svg .nd').length,
                            charts,
                            cartridgesRendered: document.querySelectorAll('#c-ch .cc').length,
                            syncLabel: (document.getElementById('hb-l') || {}).textContent || '',
                        };
                    }"""
                )

                page.keyboard.press("Control+KeyK")
                spotlight_opened = bool(
                    page.evaluate("() => document.getElementById('spotlight-modal').classList.contains('open')")
                )
                page.keyboard.press("Escape")
                page.keyboard.press("Tab")
                tactical_opened = bool(page.evaluate("() => document.body.classList.contains('tac')"))
                page.keyboard.press("Tab")
                tactical_closed = bool(page.evaluate("() => !document.body.classList.contains('tac')"))

                cortex = dom_state.get("cortex") or {}
                is_zero_webgl = cortex.get("zeroGpu") is True and cortex.get("webgl") is False
                pages_out[label] = {
                    "path": path,
                    "dom_content_loaded_ms": dom_state.get("domContentLoadedMs"),
                    "first_interactive_ms": round(first_interactive_ms, 2),
                    "pulse_hydrated_ms": round(pulse_hydrated_ms, 2),
                    "console_error_count": len(console_errors),
                    "page_error_count": len(page_errors),
                    "errors": console_errors + page_errors,
                    "mode": "v26_zero_webgl" if is_zero_webgl else "webgl",
                    "webgl_ok": cortex.get("glOk") if not is_zero_webgl else None,
                    "gl_error": cortex.get("glError") if not is_zero_webgl else None,
                    "cortex": cortex,
                    "kpi_groups": dom_state.get("kpiGroups"),
                    "svg_nodes": dom_state.get("svgNodes"),
                    "charts": dom_state.get("charts"),
                    "cartridges_rendered": dom_state.get("cartridgesRendered"),
                    "sync_label": dom_state.get("syncLabel"),
                    "interactions": {
                        "spotlight_ctrl_k": spotlight_opened,
                        "tactical_tab_toggle": tactical_opened and tactical_closed,
                    },
                }
                page.close()
        finally:
            browser.close()

    return {"available": True, "engine": "playwright_chromium", "pages": pages_out}


def _find_edge_or_chrome() -> str | None:
    candidates = [
        shutil.which("msedge"),
        shutil.which("chrome"),
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    ]
    for path in candidates:
        if path and os.path.exists(path):
            return path
    return None


def _run_cdp_fallback(base_url: str) -> dict[str, Any]:
    exe = _find_edge_or_chrome()
    if not exe:
        return {"available": False, "engine": "cdp", "reason": "No Edge or Chrome executable found"}
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        cdp_port = s.getsockname()[1]
    with tempfile.TemporaryDirectory() as profile_dir:
        proc = subprocess.Popen(
            [
                exe,
                "--headless",
                "--disable-gpu",
                f"--remote-debugging-port={cdp_port}",
                f"--user-data-dir={profile_dir}",
                f"{base_url}/",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=CREATION_FLAGS,
        )
        try:
            deadline = time.time() + 6.0
            targets: list[dict[str, Any]] = []
            while time.time() < deadline:
                try:
                    raw = urllib.request.urlopen(f"http://127.0.0.1:{cdp_port}/json", timeout=1.0).read()
                    targets = json.loads(raw.decode("utf-8"))
                    if targets:
                        break
                except Exception:
                    time.sleep(0.15)
            return {
                "available": bool(targets),
                "engine": Path(exe).name,
                "cdp_targets": len(targets),
                "note": "CDP target booted without Playwright; deep DOM metrics unavailable without websocket client",
            }
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=3.0)
            except Exception:
                proc.kill()


def main() -> int:
    raw_bytes = UNIVERSE_DASHBOARD_HTML.encode("utf-8")
    gz9_bytes = gzip.compress(raw_bytes, compresslevel=9)
    gz5_bytes = gzip.compress(raw_bytes, compresslevel=5)
    packed_bytes = build_kolmogorov_packed_html("{}", '""')
    packed_gz_bytes = gzip.compress(packed_bytes, compresslevel=9)

    static_assets = {
        "external_script_srcs": len(re.findall(r"<script\b[^>]*\bsrc\s*=", UNIVERSE_DASHBOARD_HTML, re.I)),
        "external_stylesheets": len(
            re.findall(r"<link\b[^>]*\brel\s*=\s*[\"']?stylesheet\b", UNIVERSE_DASHBOARD_HTML, re.I)
        ),
        "external_http_urls": len(re.findall(r"https?://", UNIVERSE_DASHBOARD_HTML, re.I)),
    }
    js_check = _check_js_syntax()

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        work = root / "work"
        work.mkdir()
        cfg = OpsConfig(
            role="controller",
            node_name="bench_ui_tti",
            dashboard_bind="127.0.0.1:0",
            beam_port=0,
            rpc_v4_port=0,
            rpc_v6_port=-1,
            query_port=0,
            warp_port=-1,
            edge_proxy_port=-1,
            allowed_query_roots=[str(work)],
            search_roots=[str(work)],
            edge_targets={},
            phantom_enabled=False,
        )
        daemon = ChimeraDaemon(config=cfg, ops_dir=root / "ops", auto_seed_on_empty=False).start()
        base_url = f"http://127.0.0.1:{daemon.http_addr[1]}"
        try:
            root_http = _fetch_http(f"{base_url}/", accept_gzip=True)
            packed_http = _fetch_http(f"{base_url}/?packed=1", accept_gzip=False)
            pulse_http = _fetch_http(f"{base_url}/api/pulse", accept_gzip=True)
            total_wire_bytes = int(root_http["wire_bytes"]) + int(pulse_http["wire_bytes"])

            browser = _run_playwright_check(base_url)
            if not browser.get("available"):
                cdp = _run_cdp_fallback(base_url)
                browser = {
                    "available": False,
                    "playwright_fallback_reason": browser.get("reason"),
                    "cdp_fallback": cdp,
                }
        finally:
            daemon.close()

    report = {
        "ui_mode": "v26_zero_webgl",
        "static_sizes": {
            "raw_bytes": len(raw_bytes),
            "gzip_level9_bytes": len(gz9_bytes),
            "gzip_level5_bytes": len(gz5_bytes),
            "packed_bytes": len(packed_bytes),
            "packed_gzip_bytes": len(packed_gz_bytes),
        },
        "blocking_assets": static_assets,
        "js_syntax": js_check,
        "live_wire": {
            "root": root_http,
            "packed": packed_http,
            "pulse": pulse_http,
            "total_wire_to_first_interactive_bytes": total_wire_bytes,
            "budget_bytes": 26_000,
            "within_budget": total_wire_bytes <= 26_000,
        },
        "browser_verification": browser,
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
