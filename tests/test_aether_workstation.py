import contextlib
import http.client
import http.server
import json
import os
import random
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

from chimera_tp.platform import clipboard_parcel as parcel
from chimera_tp.platform import work_admission as admission
from chimera_tp.platform.agent_workspace import file_leases, read_workspace, run_leased, workspace_manifest
from chimera_tp.platform.egress_membrane import EgressMembraneProxy
from chimera_tp.platform.file_revisions import FileRevisions
from chimera_tp.platform.result_reuse import ResultReuse
from chimera_tp import native


class AetherCases(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def test_empty_delta_restore_and_failed_import_is_atomic(self):
        a = FileRevisions(self.root / "store")
        b = FileRevisions(self.root / "recipient")
        file = self.root / "fixture"
        file.write_bytes(b"")
        empty = a.capture(file)["revision"]
        base = self.root / "base.zip"
        a.export(empty, base)
        b.receive(base)
        file.write_bytes(os.urandom(160000))
        rev = a.capture(file)["revision"]
        delta = self.root / "delta.zip"
        a.export(rev, delta, empty)
        bogus = self.root / "damaged.zip"
        with zipfile.ZipFile(delta) as src, zipfile.ZipFile(bogus, "w") as dst:
            for key in src.namelist():
                value = src.read(key)
                dst.writestr(key, value if key != src.namelist()[-1] else b"!corrupt")
        with self.assertRaises(ValueError):
            b.receive(bogus)
        with contextlib.closing(b.connect()) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM chunks").fetchone()[0], 0)
        b.receive(delta)
        out = self.root / "new"
        b.restore(rev, out)
        self.assertEqual(file.read_bytes(), out.read_bytes())
        with self.assertRaises(FileExistsError):
            b.restore(empty, out)
        self.assertEqual(len(a.history(file)), 2)
        same = self.root / "same.zip"
        self.assertEqual(a.export(rev, same, rev)["included_chunks"], 0)
        self.assertEqual(b.receive(same)["revision"], rev)

    @unittest.skipUnless(native.has_native(), "native reference required for parity")
    def test_portable_fastcdc_reproduces_native_boundaries(self):
        data = random.Random(43).randbytes(512 * 1024 + 13)
        for sizes in ((4096, 16384, 65536), (64, 201, 498), (73, 73, 110)):
            expected = native.fastcdc_split(data, *sizes)
            with patch.object(native, "_DLL", None):
                self.assertEqual(native.fastcdc_split(data, *sizes), expected)

    @unittest.skipUnless(os.name == "nt", "Windows change notification")
    def test_watch_catches_save_by_rename_and_prewarm_stays_bounded(self):
        store = FileRevisions(self.root / "events.sqlite")
        drawing = self.root / "a.dwg"
        drawing.write_bytes(b"v1")
        related = self.root / "xref.dwg"
        related.write_bytes(b"x" * 1000)
        def edit():
            until = time.monotonic() + 3
            while not store.history(drawing) and time.monotonic() < until:
                time.sleep(0.02)
            tmp = self.root / "save.tmp"
            tmp.write_bytes(b"v2")
            tmp.replace(drawing)
        thread = threading.Thread(target=edit)
        thread.start()
        try:
            self.assertEqual(store.watch(drawing, 2)["captured"], 2)
        finally:
            thread.join()
        store.capture(related)
        self.assertEqual(store.prewarm(drawing, 12)["bytes_read"], 12)

    def test_git_conflict_rejected_and_routed_to_separate_worktree(self):
        repo = self.root / "project"
        repo.mkdir()
        def git(*args):
            subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)
        git("init", "-q")
        file = repo / "module.py"
        file.write_text("original")
        git("add", ".")
        git("-c", "user.name=fixture", "-c", "user.email=fixture@localhost", "commit", "-qm", "baseline")
        command = [sys.executable, "-c", "from pathlib import Path; Path('module.py').write_text('second')"]
        dest = self.root / "separate"
        with file_leases(repo, ["module.py"]):
            self.assertEqual(run_leased(repo, ["module.py"], command), 75)
            self.assertEqual(run_leased(repo, ["module.py"], command, dest), 0)
        self.assertEqual(file.read_text(), "original")
        self.assertEqual((dest / "module.py").read_text(), "second")
        with self.assertRaises(ValueError), file_leases(repo, ["../outside"]):
            self.fail("escaped worktree")
        self.assertEqual(run_leased(repo, ["module.py"], command), 0)

    def test_workspace_restores_only_manifest_entries(self):
        document = self.root / "project.dwg"
        document.write_bytes(b"saved")
        m = workspace_manifest([document], ["https://example.org"], [self.root])
        dest = self.root / "desk.json"
        dest.write_text(json.dumps(m), encoding="utf-8")
        self.assertEqual(read_workspace(dest), m)
        with self.assertRaises(ValueError):
            workspace_manifest([], ["file:///C:/Windows"], [])

    def test_thermal_windows_resume_and_yield(self):
        db = self.root / "thermal"
        for timestamp in (0, 20, 40, 60):
            result = admission.observe(db, timestamp, 80)
        self.assertEqual(result["continuous_hot_s"], 60)
        self.assertEqual(admission.observe(db, 102, 81)["continuous_hot_s"], 0)
        self.assertEqual(admission.observe(db, 110, None)["continuous_hot_s"], 0)
        args = dict(temp_c=44, hour=23, idle_s=1800, peer_online=True)
        self.assertEqual(admission.decide(hot_s=60, **args)[0], "peer")
        self.assertEqual(admission.decide(hot_s=0, **args)[0], "local")
        self.assertEqual(admission.decide(hot_s=0, **{**args, "idle_s": 5, "peer_online": False})[0], "defer")
        (self.root / "first.py").write_text("a = 1")
        (self.root / "second.py").write_text("b = 2")
        with patch.object(admission, "_night_available", side_effect=[True, False]), \
             patch.object(admission, "gpu_temperature", return_value=44):
            job = admission.run_batch({"target": "local"}, self.root, None)
            self.assertEqual((job["state"], job["files"]), ("yielded_to_user", 1))

    def test_result_scope_exact_parameters_revision_and_expiry(self):
        s = ResultReuse(self.root / "results")
        c = dict(workspace="test", principal="userA", provider="test", model="v1", revision="a", parameters={})
        s.put(c, "What changed?", b"result", ttl=2)
        self.assertEqual(s.get(c, "What changed?"), b"result")
        self.assertIsNone(s.get(c, "What is different?"))
        for field in ("principal", "revision", "provider", "model", "workspace", "parameters"):
            diff = {**c, field: {"temperature": 1} if field == "parameters" else "different"}
            self.assertIsNone(s.get(diff, "What changed?"))
            self.assertEqual(s.suggest(diff, "changed"), [])
        with patch("chimera_tp.platform.result_reuse.time.time", return_value=time.time() + 10):
            self.assertIsNone(s.get(c, "What changed?"))
            self.assertEqual(s.suggest(c, "changed"), [])

    def test_parcel_expiry_authentication_and_table(self):
        try:
            from cryptography.exceptions import InvalidTag
        except ImportError:
            self.skipTest("cryptography not installed")
        key = os.urandom(32)
        data = b"name\tvalue\nrow\t=1+1"
        sealed = parcel.seal(data, key, 30)
        self.assertEqual(parcel.unseal(sealed, key), data)
        with self.assertRaises(InvalidTag):
            parcel.unseal(sealed, os.urandom(32))
        with self.assertRaises(InvalidTag):
            parcel.unseal(sealed[:-1] + bytes([sealed[-1] ^ 1]), key)
        with self.assertRaises(ValueError):
            parcel.unseal(sealed, key, now=time.time() + 31)
        self.assertIn(b"'=1+1", parcel.convert_table(data, "csv"))
        self.assertEqual(json.loads(parcel.convert_table(data, "json"))[-1][1], "=1+1")
        with self.assertRaises(ValueError):
            parcel.convert_table(b"unstructured", "json")

    def test_proxy_credential_and_variant_isolation_and_retry_after(self):
        hits = []
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                hits.append(self.path)
                sensitive = self.headers.get("Cookie", "")
                lang = self.headers.get("Accept-Language", "en")
                status = 429 if self.path == "/limited" else 200
                self.send_response(status)
                if status == 429:
                    self.send_header("Retry-After", "3600")
                if self.path == "/private":
                    self.send_header("Set-Cookie", "instance=fixture")
                self.end_headers()
                self.wfile.write((sensitive + lang).encode())
            def log_message(self, *args):
                pass
        upstream = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=upstream.serve_forever, daemon=True)
        thread.start()
        proxy = EgressMembraneProxy(listen_port=0).start()
        def fetch(path, **headers):
            host = urlsplit(proxy.url)
            conn = http.client.HTTPConnection(host.hostname, host.port, timeout=3)
            try:
                conn.request("GET", f"http://127.0.0.1:{upstream.server_port}{path}", headers=headers)
                response = conn.getresponse()
                return response.status, response.read()
            finally:
                conn.close()
        try:
            for language in ("vi", "en", "vi"):
                self.assertEqual(fetch("/", **{"Accept-Language": language})[1], language.encode())
            self.assertEqual(hits.count("/"), 2)
            for cookie in ("user=a", "user=b", "user=a"):
                self.assertEqual(fetch("/user", Cookie=cookie)[1], (cookie + "en").encode())
            self.assertEqual(hits.count("/user"), 3)
            for _ in range(2):
                fetch("/private", **{"X-Chimera-TTL": "600"})
            self.assertEqual(hits.count("/private"), 2)
            self.assertEqual(fetch("/limited")[0], 429)
            self.assertEqual(hits.count("/limited"), 1)
        finally:
            proxy.close()
            upstream.shutdown()
            upstream.server_close()
