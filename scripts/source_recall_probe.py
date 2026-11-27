"""Fixture and isolated measurement helpers for verify_source_recall.mjs."""

import argparse
from contextlib import closing, redirect_stdout
import hashlib
import io
import json
from math import ceil
from pathlib import Path
import platform
import sqlite3
import statistics
import sys
import time
from urllib.parse import parse_qs, urlsplit
from urllib.request import url2pathname
from unittest.mock import patch


def latency(samples):
    ordered = sorted(samples)
    return {"n": len(ordered), "p50_ms": round(statistics.median(ordered), 3),
            "p95_ms": round(ordered[ceil(len(ordered) * 0.95) - 1], 3)}


def seed(state):
    from reportlab.pdfgen.canvas import Canvas
    from chimera_tp.platform import source_recall as recall

    fixture = state.parent / "sources"
    db = state / "recall.sqlite"
    records, cases = {}, []

    def add(key, expected_excerpt="", **fields):
        saved = recall.save(db, **fields)
        # Ground truth comes from authored source paths and selected passages before indexing.
        records[key] = dict(source=str(fields.get("file") or fields["url"]), page=fields.get("page"),
                            line=fields.get("line"), locator=fields.get("locator", ""),
                            text=fields.get("text", expected_excerpt), excerpt=expected_excerpt,
                            scope=fields.get("scope", "default"), context=fields.get("context", ""))
        return saved["id"]

    def label(q, *keys, scope="default"):
        cases.append(dict(query=q, scope=scope, keys=keys))

    for key, number, shelf in (("north", 42, "bắc"), ("south", 48, "nam")):
        path = fixture / key / "thông số.txt"
        path.parent.mkdir(parents=True)
        words = f"Đường kính ổ bi {number} mm"
        path.write_text(f"Thông số kỹ thuật\n{words}\nKết thúc\n", encoding="utf-8")
        add(key, words, file=path, line=2, context=f"Kệ {shelf} bên kho")
    label("duong kinh ke NAM", "south")
    label("ĐƯỜNG KÍNH 42", "north")
    label("ổ bi", "north", "south")

    pdf = fixture / "sổ tay van.pdf"
    document = Canvas(str(pdf), pagesize=(420, 300), invariant=1)
    pdf_specs = {2: ("Seal opening pressure 18 bar", "Mở van đỏ"),
                 4: ("Seal closing pressure 11 bar", "Đóng van xanh")}
    for page in range(1, 5):
        document.drawString(30, 200, pdf_specs.get(page, ("Unselected maintenance page", ""))[0])
        document.showPage()
    document.save()
    for page, (words, context) in pdf_specs.items():
        add(f"page{page}", file=pdf, page=page, text=words, context=context)
    label("pressure 18", "page2")
    label("van xanh 11", "page4")
    label("seal pressure", "page2", "page4")

    url = "https://source-recall.invalid/quy-trinh?rev=2#kiem-tra"
    for key, word, note in (("web1", "Tăng điện áp nhánh tải A", "Kiểm tra ở đầu vào"),
                           ("web2", "Giảm điện áp nhánh tải B", "Đo phía sau tải")):
        add(key, word, url=url, quote_text=word, text=note, context="Biên bản nghiệm thu")
    label("GIẢM ĐIỆN ÁP", "web2")
    label("dau vao dien ap", "web1")
    label("nhánh tải", "web1", "web2")

    add("separate", url=url, text="Đường kính ổ bi 42 mm", context="Ca đêm", scope="night")
    label("ổ bi 42", "separate", scope="night")
    label("cam bien hut chan khong")
    label("bao tri ngoai hien truong", scope="unused")

    names = ("bơm tuần hoàn", "cơ cấu nâng", "bộ chia lưu lượng", "tủ điện")
    for lot in range(32):
        for station in range(32):
            key = f"s{station:02d}-l{lot:02d}"
            item = names[(lot + station) % len(names)]
            fields = dict(url=f"https://source-recall.invalid/work/{station:02d}", locator=f"lot-{lot:02d}",
                          text=f"Lịch bảo trì {item} trạm{station:02d} lô{lot:02d}",
                          context="Phiếu xác nhận nhóm vận hành")
            if station == lot and lot % 2 == 0:
                add(key, **fields)
                label(f"trạm{station:02d} LÔ{lot:02d} {item}", key)
            else:
                recall.save(db, **fields)
    with closing(sqlite3.connect(db)) as con:
        entries, sources = con.execute("SELECT count(*), count(DISTINCT source) FROM passages").fetchone()
    return dict(cases=cases, expected=records, entries=entries, distinct_sources=sources,
                sqlite_version=sqlite3.sqlite_version, python=sys.version.split()[0], platform=platform.platform())


def query_metrics(state, cases):
    import psutil

    process = psutil.Process()
    baseline = process.memory_info().rss
    from chimera_tp.platform.source_recall import find

    database = state / "recall.sqlite"
    readings, rss = [], [baseline]
    for index in range(21):
        for case in cases:
            start = time.perf_counter_ns()
            find(database, case["query"], scope=case["scope"], limit=10)
            elapsed = (time.perf_counter_ns() - start) / 1e6
            if index:
                readings.append(elapsed)
        rss.append(process.memory_info().rss)
    memory = process.memory_info()
    return dict(query=latency(readings), rss_bytes={"before_recall_import": baseline, "after": memory.rss,
                "max_sampled_after_each_round": max(rss), "process_peak_working_set": getattr(memory, "peak_wset", None)},
                sqlite_files_bytes={p.name: p.stat().st_size for p in database.parent.glob(database.name + "*")})


def controlled_open(state, identity, viewer):
    from chimera_tp.cli import main

    # Replace only the desktop dispatch, keeping the complete CLI, ID lookup and source verification.
    output = io.StringIO()
    with patch("webbrowser.open_new_tab", side_effect=viewer), redirect_stdout(output):
        rc = main(["aether", "--state", str(state), "recall", "open", identity])
    if rc:
        raise ValueError(output.getvalue())
    return json.loads(output.getvalue())


def render_selected_pdf(state, identity):
    import pypdfium2
    from importlib.metadata import version

    verified = {}

    def viewer(target):
        parts = urlsplit(target)
        if parts.scheme != "file" or parts.netloc:
            raise ValueError("the verification viewer only opens its local PDF fixture")
        path = Path(url2pathname(parts.path)).resolve(strict=True)
        if path != (state.parent / "sources" / "sổ tay van.pdf").resolve(strict=True):
            raise ValueError("unexpected verification document")
        page_number = int(parse_qs(parts.fragment)["page"][0])
        with closing(pypdfium2.PdfDocument(path)) as doc, closing(doc[page_number - 1]) as page:
            with closing(page.get_textpage()) as text, closing(page.render(scale=1)) as bitmap:
                verified.update(page=page_number, text=text.get_text_bounded(),
                                width=bitmap.width, height=bitmap.height,
                                pixel_sha256=hashlib.sha256(bytes(bitmap.buffer)).hexdigest())
        return True

    dispatch = controlled_open(state, identity, viewer)
    return dict(dispatch=dispatch, rendered=verified, pdfium_binding=version("pypdfium2"))


def render_selected_quote(state, identity):
    from playwright.sync_api import sync_playwright

    source = "https://source-recall.invalid/quy-trinh?rev=2"
    phrases = ("Tăng điện áp nhánh tải A", "Giảm điện áp nhánh tải B")
    html = ('<meta charset="utf-8"><style>p{margin:1500px 0}</style><h1 id="kiem-tra">Kiểm tra</h1>'
            + "".join(f"<p>{p}</p>" for p in phrases) + '<div style="height:1500px"></div>')
    observed = {}

    def viewer(target):
        if target.split("#", 1)[0] != source:
            raise ValueError("unexpected fixture URL")
        with sync_playwright() as driver:
            browser = driver.chromium.launch(channel="chrome", headless=True, args=[
                "--disable-background-networking", "--host-resolver-rules=MAP * ~NOTFOUND"])
            context = browser.new_context(offline=True, service_workers="block",
                                          viewport={"width": 900, "height": 600})
            context.route("**/*", lambda route: route.fulfill(status=200, body=html,
                          content_type="text/html; charset=utf-8") if route.request.url == source else route.abort())
            tab = context.new_page()
            tab.goto(target, wait_until="load", timeout=10000)
            visible = tab.wait_for_function("""
                () => {
                    const hits = Array.from(document.querySelectorAll('p')).filter(p => {
                        const rect = p.getBoundingClientRect();
                        return rect.top >= 0 && rect.bottom <= innerHeight;
                    });
                    return hits.length === 1 && { text: hits[0].textContent, scroll_y: scrollY };
                }
            """, timeout=5000).json_value()
            observed.update(**visible, chrome=browser.version)
            browser.close()
        return True

    return dict(dispatch=controlled_open(state, identity, viewer), visible=observed)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("seed", "query", "pdf", "web"))
    parser.add_argument("state", type=Path)
    parser.add_argument("payload", nargs="?")
    args = parser.parse_args()
    if args.stage == "seed":
        result = seed(args.state)
    elif args.stage == "query":
        result = query_metrics(args.state, json.loads(Path(args.payload).read_text(encoding="utf-8")))
    elif args.stage == "pdf":
        result = render_selected_pdf(args.state, args.payload)
    else:
        result = render_selected_quote(args.state, args.payload)
    print(json.dumps(result, ensure_ascii=False))
