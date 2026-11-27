"""Check pinning and prompt release of packet buffers passed to the native ABI."""

import ctypes
import gc
import unittest
import weakref

from chimera_tp.native import _ro_ptr, _rw_ptr


class NativeBufferLifetime(unittest.TestCase):
    def test_pointer_alone_keeps_slice_valid_then_releases_without_gc(self):
        for make in (_ro_ptr, _rw_ptr):
            with self.subTest(function=make.__name__):
                data = bytearray(b"0123456789")
                view = memoryview(data)[3:8]
                pointer, keepalive = make(view)
                del keepalive, view
                self.assertEqual(ctypes.string_at(pointer, 5), b"34567")
                ctypes.memmove(pointer, b"abcde", 5)
                self.assertEqual(data, b"012abcde89")
                with self.assertRaises(BufferError):
                    data.extend(b"!")
                del pointer
                data.extend(b"!")

    def test_variable_lengths_release_the_buffer_export_immediately(self):
        class Buffer(bytearray):
            pass

        was_enabled = gc.isenabled()
        gc.disable()
        try:
            for size in (1, 23, 512, 1199, 1250, 16384):
                owned = Buffer(size)
                owner = weakref.ref(owned)
                address, keepalive = _rw_ptr(owned)
                self.assertTrue(address.value)
                del address, keepalive, owned
                self.assertIsNone(owner(), f"{size}-byte export survived native call")
        finally:
            if was_enabled:
                gc.enable()

    def test_empty_and_readonly_views(self):
        for make in (_ro_ptr, _rw_ptr):
            self.assertIsNone(make(bytearray())[0].value)
        pointer, keepalive = _ro_ptr(memoryview(b"012345")[::2])
        self.assertEqual(ctypes.string_at(pointer, 3), b"024")
        with self.assertRaises(TypeError):
            _rw_ptr(memoryview(b"immutable"))


if __name__ == "__main__":
    unittest.main()
