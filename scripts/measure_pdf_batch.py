"""Measure the PDF example end to end using independently generated field labels."""

import argparse
from collections import Counter
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time

from PIL import Image, ImageDraw, ImageFont
import reportlab
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas


def make_fixture(target, pages, profile="mixed"):
    scan_font = ImageFont.truetype(str(Path(reportlab.__file__).parent / "fonts" / "Vera.ttf"), 44)

    def raster(code, units):
        image = Image.new("RGB", (1000, 400), "white")
        draw = ImageDraw.Draw(image)
        draw.text((40, 95), f"JOB CODE {code}", font=scan_font, fill="black")
        draw.text((40, 176), f"UNITS {units}", font=scan_font, fill="black")
        return ImageReader(image)

    scans = [raster(8810 + i, 32 + i) for i in range(4)] if profile == "mixed" else []
    canvas = Canvas(str(target), pagesize=A4, invariant=1, pageCompression=1)
    expected = {}
    kinds = Counter()
    for number in range(1, pages + 1):
        if profile == "distinct-scans":
            code, count = str(3100 + number), str(1 + number % 91)
            canvas.drawImage(raster(code, count), 45, 460, 500, 200)
            kinds["ocr"] += 1
        elif number % 5:
            code, count = str(3000 + number), str(1 + number % 91)
            canvas.setFont("Helvetica", 22)
            canvas.drawString(50, 700, f"JOB CODE {code}")
            canvas.drawString(50, 640, f"UNITS {count}")
            kinds["native"] += 1
        else:
            i = number // 5 % len(scans)
            code, count = str(8810 + i), str(32 + i)
            mixed = number % 50 == 0
            if mixed:
                canvas.setFont("Helvetica", 18)
                canvas.drawString(50, 752, f"Inspection record {number}")
            canvas.drawImage(scans[i], 45, 460, 500, 200)
            kinds["mixed" if mixed else "ocr"] += 1
        expected[str(number)] = {"code": code, "units": count}
        canvas.showPage()
    canvas.save()
    return expected, dict(kinds)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pages", type=int, default=500)
    parser.add_argument("--dpi", type=int, default=180)
    parser.add_argument("--profile", choices=("mixed", "distinct-scans"), default="mixed")
    parser.add_argument("--progress", action="store_true", help="show committed OCR counts on stderr")
    args = parser.parse_args()
    if args.pages < 1:
        parser.error("page count must be positive")
    repo = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="chimera-pdf-fixture-") as directory:
        root = Path(directory)
        sample, truth, fields = root / "sample.pdf", root / "truth.json", root / "fields.json"
        labels, kinds = make_fixture(sample, args.pages, args.profile)
        digest = hashlib.sha256(sample.read_bytes()).hexdigest()
        truth.write_text(json.dumps({digest: labels}), encoding="utf-8")
        fields.write_text(json.dumps({"code": r"JOB CODE\s+(\d+)", "units": r"UNITS\s+(\d+)"}), encoding="utf-8")
        command = [sys.executable, "-B", "-m", "examples.pdf_text_batch", str(sample), "--dpi",
                   str(args.dpi), "--cache", str(root / "cache.sqlite"), "--fields", str(fields),
                   "--truth", str(truth), "--lang", "eng"]
        result = {}
        for name in ("cold", "cached"):
            start = time.perf_counter()
            with subprocess.Popen(command, cwd=repo, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as proc:
                timeout = max(360, 3 * args.pages)
                try:
                    while True:
                        try:
                            stdout, stderr = proc.communicate(timeout=10 if args.progress else timeout)
                            break
                        except subprocess.TimeoutExpired:
                            if time.perf_counter() - start >= timeout:
                                raise
                            path = root / "cache.sqlite"
                            if path.is_file():
                                with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as reader:
                                    count = reader.execute("SELECT count(*) FROM pdf_scans").fetchone()[0]
                                print(f"{name}: {count} OCR results committed", file=sys.stderr, flush=True)
                except BaseException:
                    proc.kill()
                    proc.communicate()
                    raise
            wall_ms = round((time.perf_counter() - start) * 1000, 2)
            if proc.returncode:
                raise RuntimeError(stderr.decode("utf-8", "replace"))
            report = json.loads(stdout)
            methods = dict(Counter(page["method"] for page in report["documents"][0]["pages"]))
            quality = report["quality"]
            if quality["expected"] != 2 * args.pages or methods != kinds:
                raise RuntimeError(f"incomplete coverage: {methods}, {quality['expected']} labels")
            if name == "cached" and (report["ocr_calls"] or report["reused_documents"] != 1):
                raise RuntimeError("the warm run reread content already in cache")
            result[name] = {key: report[key] for key in ("pages", "ocr_calls", "reused_scans",
                                                        "reused_documents", "elapsed_ms")}
            result[name].update(methods=methods, fields_correct=quality["correct"],
                                fields_expected=quality["expected"], fields_missing=quality["missing"],
                                fields_wrong=quality["wrong"], sample_mismatches=quality["mismatches"][:8],
                                cli_wall_ms=wall_ms)
            if args.progress:
                print(json.dumps({"pass": name, **result[name]}), file=sys.stderr, flush=True)
        print(json.dumps({"fixture": args.profile, "fixture_sha256": digest, "dpi": args.dpi, **result}))


if __name__ == "__main__":
    main()
