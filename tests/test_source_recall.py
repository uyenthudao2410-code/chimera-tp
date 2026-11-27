import concurrent.futures
import hashlib
import os
import sqlite3
import tempfile
import unittest
import unicodedata
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote

from chimera_tp.platform import recall_open, source_recall as recall


class SourceRecallTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.db = self.root / "recall.sqlite"

    def write(self, relative, text):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def test_search_original_spelling_exact_scope_and_distinct_paths(self):
        first = self.write("kho/notes.txt", "Dòng đầu\nĐường kính ổ bi 42\n")
        second = self.write("xuong/notes.txt", "Dòng đầu\nĐường kính ổ bi 48\n")
        north = recall.save(self.db, file=first, line=2, context="Kệ phía bắc", scope="kho")
        south = recall.save(self.db, file=second, line=2, context="Tủ phía nam", scope="kho")
        other = recall.save(self.db, file=first, line=2, context="Kệ phía bắc", scope="khác")
        self.assertEqual(len({north["id"], south["id"], other["id"]}), 3)
        with patch.object(recall, "_snapshot", side_effect=AssertionError("search touched a source")):
            for query in ("duong kinh", "ĐƯỜNG KÍNH", unicodedata.normalize("NFD", "Đường kính")):
                self.assertEqual({x["id"] for x in recall.find(self.db, query, scope="kho")},
                                 {north["id"], south["id"]})
            hit, = recall.find(self.db, "BAC 42", scope="kho")
            self.assertEqual((hit["source"], hit["line"], hit["context"], hit["text"]),
                             (str(first), 2, "Kệ phía bắc", "Đường kính ổ bi 42"))
            self.assertEqual(recall.find(self.db, "duong kinh"), [])
        with self.assertRaises(LookupError):
            recall.show(self.db, north["id"], scope="khác")

    def test_stale_same_size_same_mtime_and_missing_sources_never_open(self):
        path = self.write("notes.txt", "nội dung A\n")
        handle = recall.save(self.db, file=path, line=1)["id"]
        with patch.object(recall_open, "_dispatch", return_value="editor_line") as launch:
            self.assertEqual(recall.show(self.db, handle)["continuity"], "verified")
            launch.assert_not_called()
            self.assertEqual(recall_open.open_source(self.db, handle)["viewer"], "editor_line")
            before = path.stat()
            self.write("notes.txt", "nội dung B\n")
            os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
            changed = recall_open.open_source(self.db, handle)
            self.assertEqual((changed["continuity"], changed["opened"], changed["excerpt"]),
                             ("changed", False, "nội dung A"))
            new = recall.save(self.db, file=path, line=1)["id"]
            self.assertNotEqual(new, handle)
            path.unlink()
            self.assertEqual(recall_open.open_source(self.db, new)["continuity"], "missing")
            self.assertEqual(recall.find(self.db, "dung A")[0]["id"], handle)
            launch.assert_called_once()

    def test_selected_web_quotes_and_anchors_require_no_network(self):
        url = "https://example.invalid/manual?edition=2#pressure"
        passages = ("Giảm áp suất nhánh A", "Tăng áp suất nhánh B")
        with patch("socket.socket.connect", side_effect=AssertionError("unexpected network")), \
             patch("webbrowser.open_new_tab", return_value=True) as browser:
            for words in passages:
                record = recall.save(self.db, url=url, quote_text=words, text="Ghi chú cho ca trực")
                hit = recall.show(self.db, record["id"])
                self.assertEqual(hit["source"], url)
                self.assertEqual(hit["target"], url + ":~:text=" + quote(words, safe=""))
                self.assertEqual((hit["continuity"], hit["excerpt"]), ("unverified_https", words))
            self.assertEqual(len(recall.find(self.db, "ap suat")), 2)
            browser.assert_not_called()
            self.assertTrue(recall_open.open_source(self.db, record["id"])["opened"])
            browser.assert_called_once_with(hit["target"])

    def test_pdf_url_fragments_and_arguments_are_unambiguous(self):
        url = "https://example.invalid/m.pdf?edition=2#zoom=170"
        page = recall.save(self.db, url=url, page=2, locator="van", text="valve")
        self.assertEqual(page["target"], url + "&page=2")
        for fields in (dict(url=url + "&page=3", page=2), dict(url=url, line=2),
                       dict(url="https://example.invalid/a#L1", line=2),
                       dict(url="https://example.invalid/#h", page=2),
                       dict(url="file:///C:/data.pdf"), dict(url="https://a:b@example.invalid/"),
                       dict(url="http://example.invalid/"), dict(url="https://x/\ny"),
                       dict(url=url, page=0), dict(url=url, page=2, line=3),
                       dict(url=url, line=2, quote_text="sample")):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                recall.save(self.db, **fields, text="test")
        other = recall.save(self.db, url="https://example.invalid/code", line=31, text="guard")
        self.assertEqual(other["target"], "https://example.invalid/code#L31")

    def test_empty_first_run_read_only_and_legacy_frames_remain_intact(self):
        old = self.root / "frames.sqlite"
        with closing(sqlite3.connect(old)) as db, db:
            db.execute("CREATE TABLE frames (id TEXT, video BLOB)")
            db.execute("INSERT INTO frames VALUES('old',x'0102')")
        before = hashlib.sha256(old.read_bytes()).digest()
        self.assertEqual(recall.find(self.db, "words"), [])
        with self.assertRaises(LookupError):
            recall.show(self.db, "missing")
        self.assertFalse(self.db.exists())
        recall.save(self.db, url="https://example.invalid/x", text="words")
        self.assertEqual(recall.find(self.db, "\" * ?"), [])
        self.assertEqual(len(recall.find(self.db, '"words" OR alien')), 0)
        self.assertEqual(hashlib.sha256(old.read_bytes()).digest(), before)

    def test_concurrent_idempotent_save_indexes_one_record(self):
        def save(_):
            return recall.save(self.db, url="https://example.invalid/retry", text="idempotent indexing")

        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            saved = list(pool.map(save, range(15)))
        self.assertEqual(sum(r["inserted"] for r in saved), 1)
        self.assertEqual(len({r["id"] for r in saved}), 1)
        self.assertEqual(len(recall.find(self.db, "idempotent")), 1)

    def test_first_uncommitted_capture_is_invisible_and_failed_fts_write_rolls_back(self):
        with closing(sqlite3.connect(self.db)) as writer:
            writer.executescript("BEGIN IMMEDIATE;\n" + recall._SCHEMA)
            self.assertEqual(recall.find(self.db, "first"), [])
            with self.assertRaises(LookupError):
                recall.show(self.db, "unknown")
            writer.rollback()
        with patch.object(recall, "_fold", side_effect=RuntimeError("injected indexing failure")):
            with self.assertRaisesRegex(RuntimeError, "indexing failure"):
                recall.save(self.db, url="https://example.invalid/first", text="first")
        self.assertEqual(recall.find(self.db, "first"), [])
        self.assertTrue(recall.save(self.db, url="https://example.invalid/first", text="first")["inserted"])
        self.assertEqual(len(recall.find(self.db, "first")), 1)

    def test_line_capture_errors_and_unicode_no_commit_on_failure(self):
        path = self.root / "lines.txt"
        path.write_text("một\nhai\n", encoding="utf-16")
        self.assertEqual(recall.save(self.db, file=path, line=2)["source"], str(path))
        self.assertEqual(recall.find(self.db, "hai")[0]["text"], "hai")
        for line in (0, 3):
            with self.assertRaises(ValueError):
                recall.save(self.db, file=path, line=line)
        path.write_bytes(b"\x00\xfe\xff")
        with self.assertRaises(ValueError):
            recall.save(self.db, file=path, line=1)
        path.write_text("x" * 70000 + "\nđích", encoding="utf-8")
        self.assertEqual(recall.show(self.db, recall.save(self.db, file=path, line=2)["id"])["excerpt"], "đích")
        with self.assertRaises(ValueError):
            recall.save(self.db, file=path, line=1)

    def test_desktop_dispatch_opens_exact_editor_line_or_pdf_page(self):
        text = self.write("a & b/ghi chú.py", "mode = 0\nmode = 2\n")
        file = self.write("sổ tay.pdf", "PDF placeholder for URI dispatch")
        note = recall.save(self.db, file=text, line=2)
        page = recall.save(self.db, file=file, page=11, text="Pilot valve")
        with patch.object(recall_open, "_code_editor", return_value="editor.exe"), \
             patch.object(recall_open.subprocess, "Popen") as editor, \
             patch.object(recall_open.webbrowser, "open_new_tab", return_value=True) as browser:
            recall_open.open_source(self.db, note["id"])
            editor.assert_called_once_with(["editor.exe", "--goto", f"{text}:2:1"])
            recall_open.open_source(self.db, page["id"])
            browser.assert_called_once_with(file.as_uri() + "#page=11")
        binary = self.write("sample.exe", "fixture")
        identity = recall.save(self.db, file=binary, text="archived item")["id"]
        with self.assertRaises(ValueError):
            recall_open.open_source(self.db, identity)


if __name__ == "__main__":
    unittest.main()
