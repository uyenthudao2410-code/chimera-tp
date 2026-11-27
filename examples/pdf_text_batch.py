"""Extract native and scanned PDF pages locally, with content-addressed OCR reuse.

Run python -m examples.pdf_text_batch FILE [...] --help from the checkout.
Dependencies are pypdfium2, Pillow and Tesseract with the requested languages.
"""

from __future__ import annotations

import argparse
from contextlib import closing, contextmanager
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import tempfile
import time
import unicodedata

import pypdfium2 as pdfium
import pypdfium2.raw as pdfraw


@contextmanager
def _input_snapshot(path, max_bytes):
    """Hash the exact immutable byte stream which PDFium will read."""
    digest = hashlib.sha256()
    with path.open("rb") as source, tempfile.SpooledTemporaryFile(max_size=4 << 20) as snapshot:
        while block := source.read(1 << 20):
            if snapshot.tell() + len(block) > max_bytes:
                raise ValueError(f"input exceeds {max_bytes} bytes: {path}")
            digest.update(block)
            snapshot.write(block)
        snapshot.seek(0)
        yield digest.hexdigest(), snapshot


def _file_digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def _normalized(text):
    return " ".join(unicodedata.normalize("NFKC", text).split()).casefold()


class LocalOCR:
    def __init__(self, languages, executable=None, tessdata=None):
        if not re.fullmatch(r"[A-Za-z0-9_]+(?:\+[A-Za-z0-9_]+)*", languages):
            raise ValueError("expected Tesseract language identifiers joined by '+'")
        standard = Path(os.getenv("ProgramFiles", "C:/Program Files")) / "Tesseract-OCR/tesseract.exe"
        resolved = executable or shutil.which("tesseract") or (standard if standard.is_file() else None)
        self.exe = Path(resolved).resolve(strict=True) if resolved else None
        self.languages = languages
        self.tessdata = Path(tessdata).resolve(strict=True) if tessdata else None
        self.signature = ["unavailable", languages]
        if self.exe:
            if self.tessdata is None:
                output = subprocess.run([str(self.exe), "--list-langs"], capture_output=True,
                                        timeout=8, check=True, encoding="utf-8", errors="replace")
                match = re.search(r'languages in "([^"]+)"', output.stdout + output.stderr)
                location = match.group(1) if match else os.getenv("TESSDATA_PREFIX")
                self.tessdata = Path(location) if location else self.exe.parent / "tessdata"
            models = [self.tessdata / (lang + ".traineddata") for lang in languages.split("+")]
            self.signature = [_file_digest(self.exe), languages,
                              [_file_digest(path) if path.is_file() else None for path in models]]

    def __call__(self, image, dpi):
        if self.exe is None:
            raise RuntimeError("Tesseract is required for this scanned page")
        with io.BytesIO() as encoded:
            image.save(encoded, format="PPM")
            proc = subprocess.run(
                [str(self.exe), "stdin", "stdout", "--tessdata-dir", str(self.tessdata),
                 "-l", self.languages, "--dpi", str(dpi), "--psm", "3"],
                input=encoded.getvalue(), capture_output=True, timeout=90,
                env={**os.environ, "OMP_THREAD_LIMIT": "1"},
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        if proc.returncode:
            raise RuntimeError(proc.stderr.decode("utf-8", errors="replace").strip())
        return proc.stdout.decode("utf-8").strip()


def _has_scanned_region(page, area):
    for image in page.get_objects(filter=[pdfraw.FPDF_PAGEOBJ_IMAGE], max_depth=8):
        # Small logos can coexist with native text. A substantial bitmap can contain
        # a table which is invisible to native text extraction.
        bounds = getattr(image, "get_bounds", None) or image.get_pos
        left, bottom, right, top = bounds()
        if abs((right - left) * (top - bottom)) >= area * 0.10:
            return True
    return False


class PdfBatch:
    def __init__(self, db, ocr, *, dpi=210, edge=3600, max_bytes=256 << 20):
        if dpi < 72 or edge < 128 or max_bytes < 1:
            raise ValueError("expected dpi >= 72, edge >= 128 and a positive input size limit")
        self.db, self.ocr = db, ocr
        self.dpi, self.edge, self.max_bytes = dpi, edge, max_bytes
        self.scope = json.dumps(["pdf-text-v2", str(pdfium.PDFIUM_INFO), str(pdfium.PYPDFIUM_INFO),
                                 dpi, edge, ocr.signature], separators=(",", ":"))
        db.executescript("""
            CREATE TABLE IF NOT EXISTS pdf_documents (
                scope TEXT, digest TEXT, pages TEXT NOT NULL, PRIMARY KEY(scope, digest));
            CREATE TABLE IF NOT EXISTS pdf_scans (
                scope TEXT, digest TEXT, text TEXT NOT NULL, PRIMARY KEY(scope, digest));
        """)
        self.scans_run = 0
        self.scans_reused = 0

    def _scan(self, image, dpi):
        digest = hashlib.sha256(f"L:{image.width}:{image.height}:{dpi}:".encode("ascii"))
        digest.update(image.tobytes())
        key = (self.scope, digest.hexdigest())
        cached = self.db.execute("SELECT text FROM pdf_scans WHERE scope=? AND digest=?", key).fetchone()
        if cached:
            self.scans_reused += 1
            return cached[0]
        text = self.ocr(image, dpi)
        self.scans_run += 1
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO pdf_scans VALUES(?,?,?)", (*key, text))
        return text

    def _page(self, page):
        with closing(page.get_textpage()) as textpage:
            native = textpage.get_text_bounded().replace("\x00", "").strip()
        width, height = page.get_size()
        if min(width, height) <= 0 or not math.isfinite(width + height):
            raise ValueError("invalid PDF page geometry")
        if native and not _has_scanned_region(page, width * height):
            return "native", native
        scale = min(self.dpi / 72, self.edge / max(width, height))
        with closing(page.render(scale=scale, grayscale=True)) as bitmap:
            with bitmap.to_pil() as rendered, rendered.convert("L") as image:
                empty = image.getextrema()[0] >= 250
                scanned = "" if empty else self._scan(image, max(1, round(72 * scale)))
        if not native:
            if scanned:
                return "ocr", scanned
            return ("blank" if empty else "unreadable"), ""
        native_lines = {_normalized(line) for line in native.splitlines()}
        additional = [line for line in scanned.splitlines() if line.strip() and _normalized(line) not in native_lines]
        return ("mixed", "\n".join([native, *additional])) if additional else ("native", native)

    def extract(self, path):
        path = Path(path)
        begin = time.perf_counter()
        with _input_snapshot(path, self.max_bytes) as (digest, contents):
            key = (self.scope, digest)
            cached = self.db.execute("SELECT pages FROM pdf_documents WHERE scope=? AND digest=?", key).fetchone()
            if cached:
                pages = json.loads(cached[0])
            else:
                pages = []
                with closing(pdfium.PdfDocument(contents)) as document:
                    for index in range(len(document)):
                        with closing(document[index]) as page:
                            method, text = self._page(page)
                        pages.append({"page": index + 1, "method": method, "text": text})
                with self.db:
                    self.db.execute("INSERT OR IGNORE INTO pdf_documents VALUES(?,?,?)",
                                    (*key, json.dumps(pages, ensure_ascii=False)))
        return {"file": str(path), "sha256": digest, "cached": bool(cached), "pages": pages,
                "elapsed_ms": round((time.perf_counter() - begin) * 1000, 2)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--cache", default=":memory:", help="optional SQLite file for reuse between runs")
    parser.add_argument("--lang", default="vie+eng")
    parser.add_argument("--tesseract", type=Path)
    parser.add_argument("--tessdata-dir", type=Path)
    parser.add_argument("--dpi", type=int, default=210)
    parser.add_argument("--edge", type=int, default=3600, help="maximum rendered long edge in pixels")
    parser.add_argument("--fields", type=Path, help="JSON mapping of field names to regexes with one capture")
    parser.add_argument("--truth", type=Path, help="JSON mapping of document SHA-256 to page to expected fields")
    args = parser.parse_args()
    if args.truth and not args.fields:
        parser.error("--truth requires --fields")
    from examples.pdf_fields import extract_fields, evaluate_fields, read_patterns

    start = time.perf_counter()
    ocr = LocalOCR(args.lang, args.tesseract, args.tessdata_dir)
    patterns = read_patterns(args.fields) if args.fields else {}
    with closing(sqlite3.connect(args.cache, timeout=30)) as db:
        batch = PdfBatch(db, ocr, dpi=args.dpi, edge=args.edge)
        docs = []
        for path in args.inputs:
            result = batch.extract(path)
            if patterns:
                for page in result["pages"]:
                    page["fields"] = extract_fields(page["text"], patterns)
            docs.append(result)
        report = {"documents": docs, "pages": sum(len(doc["pages"]) for doc in docs),
                  "ocr_calls": batch.scans_run, "reused_scans": batch.scans_reused,
                  "reused_documents": sum(doc["cached"] for doc in docs),
                  "elapsed_ms": round((time.perf_counter() - start) * 1000, 2)}
        if args.truth:
            truth = json.loads(args.truth.read_text(encoding="utf-8-sig"))
            report["quality"] = evaluate_fields(docs, truth)
    print(json.dumps(report, ensure_ascii=True))


if __name__ == "__main__":
    main()
