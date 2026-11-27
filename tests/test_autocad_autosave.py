"""Windows sharing and input-boundary regression cases for selected autosave recovery."""

import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts import autocad_autosave as recovery


@unittest.skipUnless(sys.platform == "win32", "requires Windows sharing modes")
class TestAutosaveCapture(unittest.TestCase):
    def test_regular_input_is_copied_with_digest_and_preserved(self):
        with tempfile.TemporaryDirectory() as root:
            source, output = Path(root, "Drawing.sv$"), Path(root, "private.dwg")
            original = b"AC1032" + b"selected bytes" * 100_000
            source.write_bytes(original)
            checksum, size = recovery.stage_source(source, output, 0)
            self.assertEqual(size, len(original))
            self.assertEqual(checksum, hashlib.sha256(original).hexdigest())
            self.assertEqual(output.read_bytes(), source.read_bytes())
            with self.assertRaises(FileExistsError):
                recovery.stage_source(source, output, 0)

    def test_ac_dollar_and_invalid_header_are_refused(self):
        with tempfile.TemporaryDirectory() as root:
            out = Path(root, "temp.dwg")
            for name, data in [("work.ac$", b"AC1032"), ("damaged.sv$", b"000000")]:
                with self.subTest(name):
                    source = Path(root, name)
                    source.write_bytes(data)
                    with self.assertRaises(ValueError):
                        recovery.stage_source(source, out, 0)
                    self.assertFalse(out.exists())

    def test_open_writer_is_deferred_before_copying(self):
        with tempfile.TemporaryDirectory() as root:
            source, out = Path(root, "writing.SV$"), Path(root, "temp.dwg")
            with source.open("wb") as writer:
                writer.write(b"AC1032" + b"w" * 55)
                writer.flush()
                with self.assertRaisesRegex(recovery.SourceBusy, "autosave_in_use"):
                    recovery.stage_source(source, out, 0)
            self.assertFalse(out.exists())
            self.assertEqual(recovery.stage_source(source, out, 0)[1], 61)

    def test_replace_between_observations_is_deferred(self):
        with tempfile.TemporaryDirectory() as root:
            source, out = Path(root, "writing.sv$"), Path(root, "temp.dwg")
            source.write_bytes(b"AC1032a")

            def replace_file(_seconds):
                second = Path(root, "replace")
                second.write_bytes(b"AC1032b")
                second.replace(source)

            with patch.object(recovery.time, "sleep", side_effect=replace_file):
                with self.assertRaisesRegex(recovery.SourceBusy, "changed_while_settling"):
                    recovery.stage_source(source, out, 500)
            self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
