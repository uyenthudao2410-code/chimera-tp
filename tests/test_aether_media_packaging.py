"""Byte-level compatibility for the Aether primitives in a stdlib-only runtime."""

import io
from xml.etree import ElementTree as ET
import unittest
from unittest.mock import patch
import zipfile

from chimera_tp.platform import clipboard_parcel as parcel
from chimera_tp.platform import frame_notes
from chimera_tp.platform._table_xlsx import text_workbook


class AetherMediaCompatibility(unittest.TestCase):
    def test_legacy_aesgcm_envelope_and_authenticated_expiry(self):
        # Produced by the original cryptography AESGCM.encrypt with key 00..1f.
        key = bytes(range(32))
        old = bytes.fromhex("43485031000000007fffffff000102030405060708090a0b"
                            "044a9f5680b7833beb28efffc49b1d6d7cf76a5514a3498c11fb1cd0e9dc11c5d0")
        data = b"CHIMERA fixture\0\xff"
        self.assertEqual(parcel.unseal(old, key, now=0), data)
        with patch.object(parcel.time, "time", return_value=2147483647 - 60), \
                patch.object(parcel.os, "urandom", return_value=bytes(range(12))):
            self.assertEqual(parcel.seal(data, key, 60), old)
        with self.assertRaisesRegex(ValueError, "expired"):
            parcel.unseal(old, key, now=2147483647)
        for index in (8, 12, 24, -1):
            changed = bytearray(old)
            changed[index] ^= 1
            with self.subTest(index=index), self.assertRaisesRegex(Exception, "authentication failed"):
                parcel.unseal(bytes(changed), key, now=0)

    def test_native_evp_empty_and_binary(self):
        key = bytes(range(32))
        for data in (b"", bytes(range(256)) * 16):
            encoded = parcel.seal(data, key, 60)
            self.assertEqual(len(encoded), len(data) + 40)
            self.assertEqual(parcel.unseal(encoded, key), data)

    def test_literal_spreadsheet_cells_column_names_and_xml_text(self):
        source = ["=2+2", " a\t ", "Å & <Σ>", "row\r\nnext", "", *map(str, range(24))]
        buf = text_workbook([source])
        with zipfile.ZipFile(io.BytesIO(buf)) as archive:
            self.assertIsNone(archive.testzip())
            sheet = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
            rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        self.assertEqual(rels[0].get("Target"), "worksheets/sheet1.xml")
        cells = sheet.findall(".//{*}c")
        self.assertTrue(all(c.get("t") == "inlineStr" for c in cells))
        self.assertEqual([c.find(".//{*}t").text or "" for c in cells], source)
        self.assertEqual([c.get("r") for c in cells[25:]], ["Z1", "AA1", "AB1", "AC1"])

    def test_screen_capture_selects_native_windows_input(self):
        with patch.object(frame_notes.os, "name", "nt"), patch.object(frame_notes, "_codec", return_value="ffmpeg"), \
                patch.object(frame_notes, "_run", return_value=b"png") as run:
            self.assertEqual(frame_notes._png(None, True), b"png")
        args, payload = run.call_args.args
        self.assertIn("gdigrab", args)
        self.assertIn("desktop", args)
        self.assertIsNone(payload)
