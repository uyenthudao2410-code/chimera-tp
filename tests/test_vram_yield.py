"""Faults while migrating a page must not discard the only verified copy."""

import ctypes
import hashlib
import unittest

from chimera_tp.native import lz4_compress
from chimera_tp.platform.hyper_desk import VramCompressedSwap


class MigrationDriver:
    def __init__(self, blob, fail):
        self.blob = blob
        self.fail = fail
        self.freed = 0
        self.destroyed = 0

    def cuCtxSetCurrent(self, ctx):
        return int(self.fail == "activate")

    def cuMemcpyDtoH_v2(self, output, ptr, length):
        if self.fail == "copy":
            return 1
        data = self.blob
        if self.fail == "corrupt":
            data = bytes([data[0] ^ 0xff]) + data[1:]
        ctypes.memmove(output, data, length)
        return 0

    def cuMemFree_v2(self, ptr):
        if self.fail == "free":
            return 1
        self.freed += 1
        return 0

    def cuCtxDestroy_v2(self, ctx):
        if self.fail == "destroy":
            return 1
        self.destroyed += 1
        return 0


class VramYieldTests(unittest.TestCase):
    raw = b"preserve the only page during yield" * 4096

    def make_swap(self, fail):
        blob = lz4_compress(self.raw)
        swap = VramCompressedSwap()
        swap._ctx = ctypes.c_void_p(1)
        swap._cu = MigrationDriver(blob, fail)
        swap._vram_used_bytes = len(blob)
        swap._total_raw_bytes = len(self.raw)
        swap._pages["only"] = {"tier": "vram", "ptr": 8, "raw_len": len(self.raw), "blob": None,
                               "comp_len": len(blob), "sha256": hashlib.sha256(self.raw).hexdigest()}
        return swap

    def test_failed_migration_keeps_page_until_verified_retry(self):
        for fail in ("activate", "copy", "corrupt", "free", "destroy"):
            with self.subTest(fail=fail):
                swap = self.make_swap(fail)
                error = swap.yield_vram()
                self.assertFalse(error["ok"])
                self.assertTrue(error["context_active"])
                self.assertEqual(0, swap._cu.destroyed)
                if fail == "destroy":
                    self.assertEqual(0, error["retained_page_bytes"])
                    self.assertEqual(self.raw, swap.get_page("only")[0])
                else:
                    self.assertGreater(error["retained_page_bytes"], 0)
                    self.assertEqual("vram", swap._pages["only"]["tier"])
                    self.assertEqual(0, swap._cu.freed)
                swap._cu.fail = None
                self.assertTrue(swap.yield_vram()["ok"])
                self.assertEqual(self.raw, swap.get_page("only")[0])
                self.assertEqual(1, swap._cu.freed)
                self.assertEqual(1, swap._cu.destroyed)

    def test_explicit_drop_clears_host_and_device_and_is_repeatable(self):
        swap = self.make_swap(None)
        swap.put_page("host", self.raw, prefer_vram=False)
        result = swap.yield_vram(drop_pages=True)
        self.assertEqual(2, result["dropped_pages"])
        self.assertEqual(0, swap.status()["pages"])
        self.assertEqual(0, swap._total_raw_bytes)
        self.assertTrue(swap.yield_vram(drop_pages=True)["ok"])
        self.assertEqual(1, swap._cu.destroyed)


if __name__ == "__main__":
    unittest.main()
