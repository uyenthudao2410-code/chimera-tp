import concurrent.futures
from contextlib import closing
from importlib.util import find_spec
import json
from pathlib import Path
import re
import sqlite3
import tempfile
import threading
import time
import unittest

from examples.office_print_on_demand import IdleRasterPool
from examples.pdf_fields import evaluate_fields, extract_fields, read_patterns


class TestIdleRasterPool(unittest.TestCase):
    def test_drain_concurrent_and_resume(self):
        created = []

        def factory(**kwargs):
            value = concurrent.futures.ThreadPoolExecutor(**kwargs)
            created.append(value)
            return value

        gate = threading.Event()
        with IdleRasterPool(1, 0.08, factory) as pool:
            self.assertFalse(pool.ready())
            first = pool.submit(gate.wait, 2)
            second = pool.submit(pow, 3, 2)
            time.sleep(0.16)
            self.assertTrue(pool.ready())
            self.assertFalse(second.done())
            gate.set()
            self.assertTrue(first.result(2))
            self.assertEqual(second.result(2), 9)
            deadline = time.monotonic() + 2
            while pool.ready() and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertFalse(pool.ready())
            self.assertEqual(list(pool.map(abs, [-1, -2])), [1, 2])
            self.assertEqual(len(created), 2)
        with self.assertRaises(RuntimeError):
            pool.submit(abs, -1)

    def test_broken_executor_is_replaced_before_next_job(self):
        created = []

        def factory(**kwargs):
            value = concurrent.futures.ThreadPoolExecutor(**kwargs)
            created.append(value)
            return value

        def failed_renderer():
            raise concurrent.futures.BrokenExecutor("child exited")

        with IdleRasterPool(1, 60, factory) as pool:
            with self.assertRaises(concurrent.futures.BrokenExecutor):
                pool.submit(failed_renderer).result(2)
            self.assertEqual(pool.submit(pow, 4, 2).result(2), 16)
            self.assertEqual(len(created), 2)


class TestFieldGroundTruth(unittest.TestCase):
    def test_unlabeled_duplicates_and_missing_sources(self):
        digest = "a" * 64
        absent = "b" * 64
        doc = {"sha256": digest, "pages": [{"page": 1, "fields": {"ID": "12"}}]}
        truth = {digest: {"1": {"ID": "12"}, "2": {"ID": "37"}}, absent: {"3": {"ID": "15"}}}
        score = evaluate_fields([doc, doc], truth)
        self.assertEqual((score["expected"], score["correct"], score["missing"]), (3, 1, 2))
        self.assertAlmostEqual(score["exact_match_rate"], 1 / 3)

    def test_conflicting_hits_are_unresolved(self):
        patterns = {"n": re.compile(r"number=(\d+)")}
        self.assertIsNone(extract_fields("number=6 number=7", patterns)["n"])
        self.assertEqual(extract_fields("number=6 number=6", patterns)["n"], "6")

    def test_invalid_field_contract(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "fields.json"
            path.write_text(json.dumps({"code": "abc"}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "one capture"):
                read_patterns(path)


@unittest.skipUnless(all(find_spec(name) for name in ("pypdfium2", "PIL", "reportlab")),
                     "optional PDF rendering and fixture dependencies")
class TestPDFDocuments(unittest.TestCase):
    def test_new_content_replaces_same_path_and_blank_needs_no_ocr(self):
        from examples.pdf_text_batch import PdfBatch
        from reportlab.pdfgen.canvas import Canvas

        class NoOCR:
            signature = ["fixture"]

            def __call__(self, image, dpi):
                raise AssertionError("unexpected OCR")

        with tempfile.TemporaryDirectory() as raw, closing(sqlite3.connect(":memory:")) as db:
            path = Path(raw) / "folder name.pdf"
            batch = PdfBatch(db, NoOCR())
            canvas = Canvas(str(path), invariant=1)
            canvas.showPage()
            canvas.save()
            blank = batch.extract(path)
            self.assertEqual(blank["pages"][0]["method"], "blank")
            self.assertTrue(batch.extract(path)["cached"])
            canvas = Canvas(str(path), invariant=1)
            canvas.drawString(50, 500, "Short ID")
            canvas.save()
            native = batch.extract(path)
            self.assertFalse(native["cached"])
            self.assertNotEqual(native["sha256"], blank["sha256"])
            self.assertEqual(native["pages"], [{"page": 1, "method": "native", "text": "Short ID"}])
            batch.max_bytes = 1
            with self.assertRaisesRegex(ValueError, "input exceeds"):
                batch.extract(path)

    def test_visible_marks_with_no_recognized_text_are_not_a_blank_page(self):
        from examples.pdf_text_batch import PdfBatch
        from reportlab.pdfgen.canvas import Canvas

        class EmptyRecognition:
            signature = ["test-unreadable"]

            def __call__(self, image, dpi):
                return ""

        with tempfile.TemporaryDirectory() as raw, closing(sqlite3.connect(":memory:")) as db:
            path = Path(raw) / "mark.pdf"
            canvas = Canvas(str(path), invariant=1)
            canvas.rect(50, 450, 100, 100, fill=1)
            canvas.save()
            result = PdfBatch(db, EmptyRecognition()).extract(path)
            self.assertEqual(result["pages"][0], {"page": 1, "method": "unreadable", "text": ""})


if __name__ == "__main__":
    unittest.main()
