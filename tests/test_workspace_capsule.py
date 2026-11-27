"""Verify portable graph capsules across clean and populated stores without a CAD installation."""

from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from threading import Barrier
import unittest
from unittest.mock import patch
import zipfile

from chimera_tp.platform import workspace_capsule as capsule
from chimera_tp.platform.file_revisions import FileRevisions


class WorkspaceCapsuleTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "source"
        self.source.mkdir()
        (self.source / "refs").mkdir()
        self.members = {
            "entry.md": (b"Open the reference.\n", ["refs/leaf.txt", "empty", "refs/copy.txt"]),
            "empty": (b"", []),
            "refs/leaf.txt": ("Đường kính 17\n".encode(), []),
            "refs/copy.txt": ("Đường kính 17\n".encode(), ["entry.md"]),
        }
        files = []
        for name, (data, links) in self.members.items():
            (self.source / name).write_bytes(data)
            files.append({"path": name, "sha256": hashlib.sha256(data).hexdigest(),
                          "bytes": len(data), "links": links})
        self.graph = {"schema": capsule.SCHEMA, "entry": "entry.md", "files": files}
        self.spec = self.root / "graph.json"
        self.spec.write_text(json.dumps(self.graph), encoding="utf-8")
        self.archive = self.root / "capsule.zip"
        self.sender = FileRevisions(self.root / "sender.sqlite")
        self.receiver = FileRevisions(self.root / "receiver.sqlite")

    def cli(self, *args, expected=0):
        command = [sys.executable, "-B", "-m", "chimera_tp", "aether", "--state", str(self.root / "cli"),
                   "capsule", *map(str, args)]
        result = subprocess.run(command, cwd=Path(__file__).resolve().parents[1], capture_output=True,
                                text=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, expected, (result.stdout, result.stderr))
        return json.loads(result.stdout)

    def save(self):
        return capsule.capture(self.sender, self.source, self.spec, self.archive)["capsule"]

    def test_cli_roundtrip_cycles_empty_and_equal_files(self):
        saved = self.cli("capture", self.source, self.spec, self.archive)
        self.assertEqual((saved["files"], saved["distinct_objects"]), (4, 3))
        self.source.rename(self.root / "old-location")
        checked = self.cli("verify", self.archive, saved["capsule"])
        self.assertTrue(checked["ok"])
        self.assertEqual(checked["verified_objects"], 3)
        self.assertFalse(checked["checked_directory"])
        destination = self.root / "relocated"
        restored = self.cli("restore", self.archive, saved["capsule"], destination)
        self.assertEqual(Path(restored["entry"]), destination / "entry.md")
        for name, (data, _) in self.members.items():
            self.assertEqual((destination / name).read_bytes(), data)
        damaged, missing = destination / "refs/leaf.txt", destination / "empty"
        before = damaged.stat()
        damaged.write_bytes(b"X" * before.st_size)
        os.utime(damaged, ns=(before.st_atime_ns, before.st_mtime_ns))
        missing.unlink()
        result = self.cli("verify", self.archive, saved["capsule"], destination, expected=1)
        self.assertTrue(result["checked_directory"])
        self.assertEqual({r["path"]: r["reason"] for r in result["problems"]},
                         {"refs/leaf.txt": "modified", "empty": "missing"})

    def test_invalid_inner_object_rejected_even_when_receiver_has_original(self):
        identity = self.save()
        capsule.restore(self.receiver, self.archive, identity, self.root / "known-originals")
        leaf = self.graph["files"][2]["sha256"]
        broken = self.root / "damaged.zip"
        with zipfile.ZipFile(self.archive) as original, zipfile.ZipFile(broken, "x") as replacement:
            for member in original.namelist():
                data = original.read(member)
                if member == f"objects/{leaf}.zip":
                    target = io.BytesIO()
                    with zipfile.ZipFile(io.BytesIO(data)) as inner, zipfile.ZipFile(target, "w") as other:
                        for obj in inner.namelist():
                            part = inner.read(obj)
                            if obj != "revision.json":
                                part = b"?" * len(part)
                            other.writestr(obj, part)
                    data = target.getvalue()
                replacement.writestr(member, data)
        for directory in (None, self.source):
            with self.subTest(directory=directory), self.assertRaisesRegex(ValueError, "chunk digest mismatch"):
                capsule.verify(broken, identity, directory)
        with self.assertRaisesRegex(ValueError, "chunk digest mismatch"):
            capsule.restore(self.receiver, broken, identity, self.root / "never-published")
        self.assertFalse((self.root / "never-published").exists())
        self.assertFalse(list(self.root.glob(".workspace-restore-*")))

    def test_sources_and_declared_graph_must_be_current_and_complete(self):
        tip = self.source / "refs/leaf.txt"
        tip.write_bytes(b"B" * tip.stat().st_size)
        with self.assertRaisesRegex(ValueError, "stale_workspace_member"):
            self.save()
        self.assertFalse(self.archive.exists())
        tip.unlink()
        with self.assertRaises(FileNotFoundError):
            self.save()
        self.assertFalse(self.archive.exists())
        for change, pattern in [
            ({"path": "../leaf.txt"}, "invalid_workspace_path"),
            ({"path": "REFS/leaf.txt"}, "aliased_workspace_member"),
            ({"links": ["unknown.txt"]}, "undeclared_workspace_dependency"),
            ({"bytes": 0}, "workspace_object_size_conflict"),
        ]:
            with self.subTest(change=change):
                graph = json.loads(json.dumps(self.graph))
                graph["files"][2].update(change)
                with self.assertRaisesRegex(ValueError, pattern):
                    capsule._graph(graph)
        self.graph["files"][0]["links"] = ["refs/copy.txt"]
        with self.assertRaisesRegex(ValueError, "unreachable_members"):
            capsule._graph(self.graph)

    def test_two_publishers_keep_one_complete_destination_and_never_replace(self):
        identity = self.save()
        destination = self.root / "common"
        barrier = Barrier(2)
        def publish():
            barrier.wait(timeout=5)
            try:
                return capsule.restore(self.receiver, self.archive, identity, destination)["ok"]
            except FileExistsError:
                return False
        with ThreadPoolExecutor(2) as pool:
            results = [pool.submit(publish) for _ in range(2)]
            self.assertEqual(sorted(r.result(timeout=10) for r in results), [False, True])
        self.assertTrue(capsule.verify(self.archive, identity, destination)["ok"])
        with self.assertRaisesRegex(ValueError, "identity_mismatch"):
            capsule.restore(self.receiver, self.archive, "0" * 64, self.root / "wrong")
        self.assertFalse((self.root / "wrong").exists())
        established = self.root / "established"
        established.mkdir()
        with self.assertRaises(FileExistsError):
            capsule.restore(self.receiver, self.archive, identity, established)
        self.assertEqual(list(established.iterdir()), [])

    def test_verification_detects_edit_to_earlier_member(self):
        identity = self.save()
        original_probe = capsule._probe
        def change_prior_member(root, name):
            if name == "entry.md" and (root / "empty").stat().st_size == 0:
                (root / "empty").write_bytes(b"later")
            return original_probe(root, name)
        with patch.object(capsule, "_probe", side_effect=change_prior_member):
            result = capsule.verify(self.archive, identity, self.source)
        self.assertEqual(result["problems"], [{"path": "empty", "reason": "modified"}])


if __name__ == "__main__":
    unittest.main()
