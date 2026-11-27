"""Measure the dashboard's default rendering work in an isolated Chromium profile."""

import argparse
import importlib.util
import json
from pathlib import Path

from playwright.sync_api import sync_playwright


INSTRUMENT = """
    window.hudMetrics = {callbacks: 0, contextRequests: 0};
    const schedule = window.requestAnimationFrame.bind(window);
    window.requestAnimationFrame = (fn) => schedule((time) => {
        window.hudMetrics.callbacks++;
        return fn(time);
    });
    const context = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function(kind, ...args) {
        if (kind === 'webgl' || kind === 'webgl2') window.hudMetrics.contextRequests++;
        return context.call(this, kind, ...args);
    };
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser", required=True)
    parser.add_argument("--seconds", type=int, default=5)
    args = parser.parse_args()
    ui = Path(__file__).resolve().parents[1] / "chimera_tp" / "universe_ui.py"
    spec = importlib.util.spec_from_file_location("audited_ui", ui)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with sync_playwright() as driver:
        browser = driver.chromium.launch(executable_path=args.browser, headless=True)
        page = browser.new_page(viewport={"width": 900, "height": 600})
        page.add_init_script(INSTRUMENT)
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))

        def respond(route):
            if route.request.resource_type == "document":
                route.fulfill(content_type="text/html", body=module.UNIVERSE_DASHBOARD_HTML)
            else:
                route.fulfill(content_type="application/json", body="{}")

        page.route("http://hud.test/**", respond)
        page.goto("http://hud.test/", wait_until="domcontentloaded")
        page.wait_for_timeout(args.seconds * 1000)
        initial = page.evaluate("({...window.hudMetrics})")
        page.keyboard.press("Tab")
        page.wait_for_timeout(1800)
        toggled = page.evaluate("({...window.hudMetrics, tactical: document.body.classList.contains('tac')})")
        print(json.dumps({
            "browser": browser.version, "window_s": args.seconds,
            "initial": initial, "after_toggle": toggled, "script_errors": errors,
        }))
        browser.close()


if __name__ == "__main__":
    main()
