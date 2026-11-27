"""Exercise SQLite page replication across loopback HTTP, including live WAL transactions."""

import base64
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from urllib.parse import parse_qs, urlsplit
from unittest import mock
import zlib

from chimera_tp.platform import vault_sql_pages as pages
from chimera_tp.platform.vault_sql import VaultSqlFabric


@contextmanager
def server(fabric, transform=None, legacy=False):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            try:
                args = parse_qs(urlsplit(self.path).query)
                part = fabric.export_snapshot(args["name"][0], args.get("since_sha256", [""])[0],
                             protocol=1 if legacy else args["protocol"][0],
                             target_sha256=args.get("target_sha256", [""])[0],
                             start_page=int(args.get("start_page", [0])[0]))
                data = json.dumps(transform(part) if transform else part).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            except Exception as exc:
                self.send_error(500, type(exc).__name__)

        def log_message(self, *args):
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as http:
        thread = threading.Thread(target=http.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{http.server_port}"
        finally:
            http.shutdown()
            thread.join(timeout=5)


class TestVaultPages(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.primary = VaultSqlFabric(self.root / "sender")
        self.replica = VaultSqlFabric(self.root / "receiver")
        self.source = self.root / "data #2.sqlite"
        self.db = sqlite3.connect(self.source)
        self.addCleanup(self.db.close)
        self.db.executescript("""
            PRAGMA page_size=8192;
            PRAGMA journal_mode=WAL;
            PRAGMA wal_autocheckpoint=0;
            CREATE TABLE docs(id INTEGER PRIMARY KEY, content BLOB);
            CREATE TABLE version(n INTEGER);
            INSERT INTO version VALUES(1);
        """)
        self.db.executemany("INSERT INTO docs VALUES(?,randomblob(1700))", ((i,) for i in range(72)))
        self.db.commit()
        self.primary.register_db("example", str(self.source))

    def inspect(self, path):
        with closing(sqlite3.connect(Path(path).as_uri() + "?mode=ro&immutable=1", uri=True)) as conn:
            self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone(), ("ok",))
            return conn.execute("SELECT n FROM version").fetchone()[0]

    def test_multipart_source_mutates_while_reading_but_generation_is_pinned(self):
        committed = []

        def after_first(part):
            if not committed:
                with closing(sqlite3.connect(self.source)) as writer:
                    writer.execute("UPDATE version SET n=2")
                    writer.commit()
                committed.append(part["sha256"])
            return part

        with mock.patch.object(pages, "FRAME_BYTES", 25000), server(self.primary, after_first) as url:
            first = self.replica.sync_from_peer("example", url)
            self.assertGreater(first["parts"], 1)
            self.assertEqual(first["sha256"], committed[0])
            self.assertEqual(self.inspect(first["path"]), 1)
            second = self.replica.sync_from_peer("example", url)
            self.assertEqual(second["mode"], "delta")
            self.assertLessEqual(second["changed_pages"], 3)
            self.assertEqual(self.inspect(second["path"]), 2)
            same = self.replica.sync_from_peer("example", url)
            self.assertEqual(same["wire_bytes"], 0)
            self.assertTrue(same["unchanged"])

    def test_uncommitted_change_is_excluded_and_truncation_survives(self):
        with server(self.primary) as url:
            before = self.replica.sync_from_peer("example", url)
            self.db.execute("UPDATE version SET n=9")
            self.assertTrue(self.replica.sync_from_peer("example", url)["unchanged"])
            self.db.rollback()
            self.db.execute("DELETE FROM docs WHERE id>9")
            self.db.commit()
            self.db.execute("VACUUM")
            shrunk = self.replica.sync_from_peer("example", url)
            self.assertLess(shrunk["raw_bytes"], before["raw_bytes"])
            self.assertEqual(shrunk["mode"], "delta")
            self.assertEqual(self.inspect(shrunk["path"]), 1)
            with closing(sqlite3.connect(shrunk["path"])) as replica:
                self.assertEqual(replica.execute("SELECT count(*) FROM docs").fetchone(), (10,))

    def test_corrupt_delta_is_atomic_and_base_is_checked_from_disk(self):
        first = self.primary.export_snapshot("example", protocol=2)
        result = self.replica.install_replica_snapshot("example", first)
        dest = Path(result["path"])
        self.db.execute("UPDATE version SET n=3")
        self.db.commit()
        delta = self.primary.export_snapshot("example", first["sha256"], protocol=2)
        copy = bytearray(zlib.decompress(base64.b64decode(delta["data_b64"])))
        copy[40] ^= 255
        packed = zlib.compress(copy)
        data = base64.b64encode(packed).decode()
        with self.assertRaisesRegex(ValueError, "digest"):
            self.replica.install_replica_snapshot("example", {**delta, "data_b64": data,
                                                  "wire_bytes":len(data), "compressed_bytes": len(packed)})
        self.assertEqual(pages.file_digest(dest), result["sha256"])
        self.assertEqual(self.inspect(dest), 1)
        with dest.open("r+b") as damaged:
            damaged.seek(45)
            damaged.write(b"\xff")
        with self.assertRaises(pages.BaseMismatch):
            self.replica.install_replica_snapshot("example", delta)
        with server(self.primary) as url:
            recovered = self.replica.sync_from_peer("example", url)
            self.assertEqual(recovered["mode"], "full")
            self.assertEqual(self.inspect(dest), 3)
            dest.unlink()
            self.assertEqual(self.replica.sync_from_peer("example", url)["mode"], "full")
            self.assertEqual(self.inspect(dest), 3)

    def test_expired_generation_restarts_once_and_parallel_readers_agree(self):
        expired = []

        def expire_one(part):
            if part.get("start_page") and not expired:
                expired.append(True)
                return {"ok": False, "protocol": 2, "error": "snapshot_expired"}
            return part

        with mock.patch.object(pages, "FRAME_BYTES", 25000), server(self.primary, expire_one) as url:
            replicas = (self.replica, VaultSqlFabric(self.replica.replica_dir))
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda r: r.sync_from_peer("example", url), replicas))
            self.assertTrue(any(result.get("restarted_full") for result in results))
            self.assertEqual({result["mode"] for result in results}, {"full", "unchanged"})
            self.assertEqual(len({result["sha256"] for result in results}), 1)
            self.assertEqual(self.inspect(results[0]["path"]), 1)

    def test_legacy_http_and_upgrade(self):
        with server(self.primary, legacy=True) as url:
            installed = self.replica.sync_from_peer("example", url)
            self.assertEqual(len(installed["sha256"]), 32)
            self.assertTrue(self.replica.sync_from_peer("example", url)["unchanged"])
            with self.assertRaises(pages.BaseMismatch):
                self.replica.install_replica_snapshot("missing", self.primary.export_snapshot("example", installed["sha256"]))
        with server(self.primary) as url:
            upgraded = self.replica.sync_from_peer("example", url)
            self.assertEqual(len(upgraded["sha256"]), 64)
            self.assertEqual(upgraded["mode"], "full")
            self.assertTrue(self.replica.sync_from_peer("example", url)["unchanged"])

    def test_repeated_reads_skip_backup_and_file_replacement_invalidates_it(self):
        first = self.primary.export_snapshot("example", protocol=2)
        self.assertTrue(first["source_backup_created"])
        with mock.patch.object(pages, "online_copy", side_effect=AssertionError("copied unchanged DB")):
            again = self.primary.export_snapshot("example", first["sha256"], protocol=2)
            self.assertFalse(again["source_backup_created"])
        clone = self.root / "clone.sqlite"
        with closing(sqlite3.connect(clone)) as new:
            new.execute("CREATE TABLE other(x)")
        self.primary.register_db("example", str(clone))
        fresh = self.primary.export_snapshot("example", first["sha256"], protocol=2)
        self.assertEqual(fresh["mode"], "full")
        self.assertTrue(fresh["source_backup_created"])

    def test_refuses_bad_frames_and_out_of_order_chunks(self):
        with mock.patch.object(pages, "FRAME_BYTES", 25000):
            first = self.primary.export_snapshot("example", protocol=2)
            with self.assertRaisesRegex(ValueError, "additional parts"):
                self.replica.install_replica_snapshot("example", first)
            next_part = self.primary.export_snapshot("example", protocol=2, target_sha256=first["sha256"],
                                                     start_page=first["end_page"])
            with self.assertRaises(ValueError):
                self.replica.install_replica_snapshot("example", next_part)
            malicious = base64.b64encode(zlib.compress(bytes(100000))).decode()
            with self.assertRaises(ValueError):
                self.replica.install_replica_snapshot("example", {**first, "data_b64": malicious})
            self.assertFalse((self.replica.replica_dir / "example.replica.db").exists())


if __name__ == "__main__":
    unittest.main()
