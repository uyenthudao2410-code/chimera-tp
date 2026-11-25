"""Zero-copy ctypes bridge to Rust CHIMERA-HYPER Silicon Core (`_chimera_core.dll`)."""

from __future__ import annotations

import ctypes
import hashlib
import os
import struct
import time
from pathlib import Path
from typing import Any

from .gf256 import INV, MUL_BYTES


def _discover_and_load_dll() -> ctypes.CDLL | None:
    lib_dir = Path(__file__).resolve().parent
    repo_dir = Path(__file__).resolve().parents[1]
    if os.name == "nt":
        candidates = [
            lib_dir / "_chimera_core.dll",
            repo_dir / "native" / "chimera_core" / "target" / "release" / "chimera_core.dll",
        ]
    else:
        candidates = [lib_dir / "_chimera_core.so"]
    for path in candidates:
        if path.exists():
            try:
                lib = ctypes.CDLL(str(path))
                _bind_signatures(lib)
                return lib
            except OSError:
                continue
    return None


def _bind_signatures(lib: ctypes.CDLL) -> None:
    c_void_p = ctypes.c_void_p
    c_size_t = ctypes.c_size_t
    c_ssize_t = ctypes.c_ssize_t
    c_u8 = ctypes.c_uint8
    c_u32 = ctypes.c_uint32
    c_i32 = ctypes.c_int32
    c_u64_p = ctypes.POINTER(ctypes.c_uint64)
    c_wchar_p = ctypes.c_wchar_p

    lib.chimera_cpu_caps.argtypes = []
    lib.chimera_cpu_caps.restype = c_u32

    lib.chimera_gf256_mul_add.argtypes = [c_void_p, c_void_p, c_size_t, c_u8]
    lib.chimera_gf256_mul_add.restype = None

    lib.chimera_gf256_scale.argtypes = [c_void_p, c_void_p, c_size_t, c_u8]
    lib.chimera_gf256_scale.restype = None

    lib.chimera_gf256_encode_block.argtypes = [c_void_p, c_void_p, c_void_p, c_size_t, c_size_t]
    lib.chimera_gf256_encode_block.restype = None

    lib.chimera_gf256_decode_matrix.argtypes = [c_void_p, c_void_p, c_void_p, c_size_t, c_size_t]
    lib.chimera_gf256_decode_matrix.restype = c_i32

    lib.chimera_fastcdc.argtypes = [c_void_p, c_size_t, c_size_t, c_size_t, c_size_t, c_u64_p, c_size_t]
    lib.chimera_fastcdc.restype = c_size_t

    lib.chimera_superfeatures.argtypes = [c_void_p, c_size_t, c_u64_p]
    lib.chimera_superfeatures.restype = None

    lib.chimera_delta_encode.argtypes = [c_void_p, c_size_t, c_void_p, c_size_t, c_void_p, c_size_t]
    lib.chimera_delta_encode.restype = c_ssize_t

    lib.chimera_delta_decode.argtypes = [c_void_p, c_size_t, c_void_p, c_size_t, c_void_p, c_size_t]
    lib.chimera_delta_decode.restype = c_ssize_t

    lib.chimera_active_filter_lines.argtypes = [
        c_void_p,
        c_size_t,
        c_void_p,
        c_size_t,
        c_void_p,
        c_size_t,
        c_u64_p,
    ]
    lib.chimera_active_filter_lines.restype = c_ssize_t

    if os.name == "nt":
        lib.chimera_wormhole_create.argtypes = [c_wchar_p, c_size_t]
        lib.chimera_wormhole_create.restype = c_void_p

        lib.chimera_wormhole_open.argtypes = [c_wchar_p]
        lib.chimera_wormhole_open.restype = c_void_p
    else:
        c_char_p = ctypes.c_char_p
        lib.chimera_wormhole_create.argtypes = [c_char_p, c_size_t]
        lib.chimera_wormhole_create.restype = c_void_p

        lib.chimera_wormhole_open.argtypes = [c_char_p]
        lib.chimera_wormhole_open.restype = c_void_p

    lib.chimera_wormhole_write.argtypes = [c_void_p, c_void_p, c_size_t, c_u32]
    lib.chimera_wormhole_write.restype = c_ssize_t

    lib.chimera_wormhole_read.argtypes = [c_void_p, c_void_p, c_size_t, c_u32]
    lib.chimera_wormhole_read.restype = c_ssize_t

    lib.chimera_wormhole_mark_eof.argtypes = [c_void_p]
    lib.chimera_wormhole_mark_eof.restype = None

    lib.chimera_wormhole_close.argtypes = [c_void_p]
    lib.chimera_wormhole_close.restype = None

    if hasattr(lib, "chimera_chacha20_xor"):
        lib.chimera_chacha20_xor.argtypes = [c_void_p, c_void_p, c_size_t, c_void_p, c_void_p, c_u32]
        lib.chimera_chacha20_xor.restype = None

    if hasattr(lib, "chimera_gf256_recode"):
        lib.chimera_gf256_recode.argtypes = [c_void_p, c_void_p, c_void_p, c_void_p, c_size_t, c_size_t, c_size_t, c_void_p]
        lib.chimera_gf256_recode.restype = None

    if hasattr(lib, "chimera_slepian_syndrome"):
        lib.chimera_slepian_syndrome.argtypes = [c_void_p, c_size_t, c_size_t, c_u8, c_size_t, c_void_p]
        lib.chimera_slepian_syndrome.restype = None

    if hasattr(lib, "chimera_ppm_compress"):
        lib.chimera_ppm_compress.argtypes = [c_void_p, c_size_t, c_void_p, c_size_t]
        lib.chimera_ppm_compress.restype = c_ssize_t

    if hasattr(lib, "chimera_ppm_decompress"):
        lib.chimera_ppm_decompress.argtypes = [c_void_p, c_size_t, c_void_p, c_size_t]
        lib.chimera_ppm_decompress.restype = c_ssize_t

    if hasattr(lib, "chimera_pir_xor_query"):
        lib.chimera_pir_xor_query.argtypes = [c_void_p, c_size_t, c_size_t, c_void_p, c_void_p]
        lib.chimera_pir_xor_query.restype = None

    if hasattr(lib, "chimera_fsk_demod_bits"):
        lib.chimera_fsk_demod_bits.argtypes = [c_void_p, c_size_t, c_void_p, c_size_t]
        lib.chimera_fsk_demod_bits.restype = c_size_t


_DLL: ctypes.CDLL | None = _discover_and_load_dll()


def _ro_ptr(buf: bytes | bytearray | memoryview) -> tuple[ctypes.c_void_p, Any]:
    """Return a zero-copy c_void_p for bytes/bytearray/memoryview plus a keepalive object."""
    n = len(buf)
    if n == 0:
        return ctypes.c_void_p(0), buf
    if isinstance(buf, bytes):
        cp = ctypes.c_char_p(buf)
        return ctypes.cast(cp, ctypes.c_void_p), (buf, cp)
    if isinstance(buf, bytearray):
        arr = (ctypes.c_ubyte * n).from_buffer(buf)
        return ctypes.cast(arr, ctypes.c_void_p), (buf, arr)
    if isinstance(buf, memoryview):
        if not buf.readonly and buf.c_contiguous:
            arr = (ctypes.c_ubyte * n).from_buffer(buf)
            return ctypes.cast(arr, ctypes.c_void_p), (buf, arr)
        raw = buf.tobytes()
        cp = ctypes.c_char_p(raw)
        return ctypes.cast(cp, ctypes.c_void_p), (raw, cp)
    raw = bytes(buf)
    cp = ctypes.c_char_p(raw)
    return ctypes.cast(cp, ctypes.c_void_p), (raw, cp)


def _rw_ptr(buf: bytearray | memoryview) -> tuple[ctypes.c_void_p, Any]:
    n = len(buf)
    if n == 0:
        return ctypes.c_void_p(0), buf
    arr = (ctypes.c_ubyte * n).from_buffer(buf)
    return ctypes.cast(arr, ctypes.c_void_p), (buf, arr)


def has_native() -> bool:
    return _DLL is not None


def cpu_caps() -> dict[str, bool]:
    if _DLL is None:
        return {"native": False, "gfni": False, "avx2": False, "avx512f": False}
    mask = int(_DLL.chimera_cpu_caps())
    return {
        "native": True,
        "gfni": bool(mask & 1),
        "avx2": bool(mask & 2),
        "avx512f": bool(mask & 4),
    }


def gf256_mul_add(dst: bytearray, src: bytes | bytearray | memoryview, coeff: int) -> None:
    """In-place GF(256) multiply-accumulate: dst[i] ^= gf_mul(src[i], coeff)."""
    coeff &= 0xFF
    n = len(src)
    if len(dst) != n:
        raise ValueError(f"Length mismatch: dst={len(dst)} vs src={n}")
    if coeff == 0 or n == 0:
        return
    if _DLL is not None:
        dp, kd = _rw_ptr(dst)
        sp, ks = _ro_ptr(src)
        _DLL.chimera_gf256_mul_add(dp, sp, n, coeff)
        _ = (kd, ks)
        return
    scaled = bytes(src) if coeff == 1 else bytes(src).translate(MUL_BYTES[coeff])
    res = (int.from_bytes(dst, "little") ^ int.from_bytes(scaled, "little")).to_bytes(n, "little")
    dst[:] = res


def gf256_scale(src: bytes | bytearray | memoryview, coeff: int) -> bytes:
    """Return byte buffer scaled by `coeff` in GF(256) mod 0x11B."""
    coeff &= 0xFF
    n = len(src)
    if n == 0:
        return b""
    if _DLL is not None:
        out = bytearray(n)
        dp, kd = _rw_ptr(out)
        sp, ks = _ro_ptr(src)
        _DLL.chimera_gf256_scale(dp, sp, n, coeff)
        _ = (kd, ks)
        return bytes(out)
    if coeff == 0:
        return bytes(n)
    if coeff == 1:
        return bytes(src)
    return bytes(src).translate(MUL_BYTES[coeff])


def gf256_encode_block(
    blocks_flat: bytes | bytearray, coeffs: bytes, k: int, block_len: int
) -> bytes:
    """Linearly combine `k` equal-length source blocks into one coded symbol."""
    if len(coeffs) < k or len(blocks_flat) < k * block_len:
        raise ValueError("Invalid buffer lengths for gf256_encode_block")
    if block_len == 0 or k == 0:
        return b""
    out = bytearray(block_len)
    if _DLL is not None:
        op, ko = _rw_ptr(out)
        bp, kb = _ro_ptr(blocks_flat)
        cp, kc = _ro_ptr(coeffs)
        _DLL.chimera_gf256_encode_block(op, bp, cp, k, block_len)
        _ = (ko, kb, kc)
        return bytes(out)
    acc = 0
    mv = memoryview(blocks_flat)
    for r in range(k):
        c = coeffs[r]
        if c == 0:
            continue
        blk = bytes(mv[r * block_len : (r + 1) * block_len])
        scaled = blk if c == 1 else blk.translate(MUL_BYTES[c])
        acc ^= int.from_bytes(scaled, "little")
    return acc.to_bytes(block_len, "little")


def gf256_decode_matrix(
    coded_flat: bytes | bytearray, coeffs_flat: bytes | bytearray, k: int, block_len: int
) -> bytes:
    """Invert k x k GF(256) matrix and recover k source blocks in one native call."""
    if len(coeffs_flat) < k * k or len(coded_flat) < k * block_len:
        raise ValueError("Invalid buffer lengths for gf256_decode_matrix")
    if k == 0 or block_len == 0:
        return b""
    out = bytearray(k * block_len)
    if _DLL is not None:
        cp, kc = _ro_ptr(coded_flat)
        mp, km = _ro_ptr(coeffs_flat)
        op, ko = _rw_ptr(out)
        rc = int(_DLL.chimera_gf256_decode_matrix(cp, mp, op, k, block_len))
        _ = (kc, km, ko)
        if rc != 0:
            raise ValueError("Singular GF(256) coding matrix")
        return bytes(out)

    # Pure-Python fallback
    c_rows = [bytearray(coeffs_flat[r * k : (r + 1) * k]) for r in range(k)]
    d_rows = [bytearray(coded_flat[r * block_len : (r + 1) * block_len]) for r in range(k)]
    for col in range(k):
        piv_r = col
        while piv_r < k and c_rows[piv_r][col] == 0:
            piv_r += 1
        if piv_r == k:
            raise ValueError("Singular GF(256) coding matrix")
        if piv_r != col:
            c_rows[col], c_rows[piv_r] = c_rows[piv_r], c_rows[col]
            d_rows[col], d_rows[piv_r] = d_rows[piv_r], d_rows[col]
        piv = c_rows[col][col]
        if piv != 1:
            inv = INV[piv]
            t = MUL_BYTES[inv]
            c_rows[col] = bytearray(bytes(c_rows[col]).translate(t))
            d_rows[col] = bytearray(bytes(d_rows[col]).translate(t))
        for other in range(k):
            if other == col:
                continue
            factor = c_rows[other][col]
            if factor == 0:
                continue
            t = MUL_BYTES[factor]
            c_rows[other] = bytearray(
                (int.from_bytes(c_rows[other], "little") ^ int.from_bytes(bytes(c_rows[col]).translate(t), "little")).to_bytes(k, "little")
            )
            d_rows[other] = bytearray(
                (int.from_bytes(d_rows[other], "little") ^ int.from_bytes(bytes(d_rows[col]).translate(t), "little")).to_bytes(block_len, "little")
            )
    return b"".join(bytes(r) for r in d_rows)


def fastcdc_split(
    data: bytes | bytearray | memoryview,
    min_sz: int = 4096,
    avg_sz: int = 16384,
    max_sz: int = 65536,
) -> list[tuple[int, int]]:
    """Split `data` into content-defined (start, end) chunk byte ranges."""
    n = len(data)
    if n == 0:
        return []
    min_c = max(64, int(min_sz))
    max_c = max(min_c, int(max_sz))
    avg_c = max(min_c, min(max_c, int(avg_sz)))

    if _DLL is not None:
        max_chunks = (n // min_c) + 4
        offsets = (ctypes.c_uint64 * max_chunks)()
        dp, kd = _ro_ptr(data)
        cnt = int(_DLL.chimera_fastcdc(dp, n, min_c, avg_c, max_c, offsets, max_chunks))
        _ = kd
        spans: list[tuple[int, int]] = []
        start = 0
        for i in range(cnt):
            end = int(offsets[i])
            if end > start:
                spans.append((start, end))
                start = end
        if start < n:
            spans.append((start, n))
        return spans

    # Simple deterministic fallback chunker
    spans = []
    pos = 0
    while pos < n:
        end = min(n, pos + avg_c)
        spans.append((pos, end))
        pos = end
    return spans


def chunk_superfeatures(data: bytes | bytearray | memoryview) -> tuple[int, int, int, int]:
    """Compute 4 Odess-style 64-bit super-features for O(1) near-duplicate chunk matching."""
    n = len(data)
    if n == 0:
        return (0, 0, 0, 0)
    if _DLL is not None:
        sf = (ctypes.c_uint64 * 4)()
        dp, kd = _ro_ptr(data)
        _DLL.chimera_superfeatures(dp, n, sf)
        _ = kd
        return (int(sf[0]), int(sf[1]), int(sf[2]), int(sf[3]))
    # Pure-Python fallback
    d = hashlib.blake2b(bytes(data), digest_size=32).digest()
    return struct.unpack("!4Q", d)


def delta_encode(
    base: bytes | bytearray | memoryview, target: bytes | bytearray | memoryview
) -> bytes | None:
    """Encode `target` relative to `base` into a compact delta patch, or None on error."""
    tlen = len(target)
    if tlen == 0:
        return b""
    out_cap = tlen + 64
    if _DLL is not None:
        out = bytearray(out_cap)
        bp, kb = _ro_ptr(base)
        tp, kt = _ro_ptr(target)
        op, ko = _rw_ptr(out)
        rc = int(_DLL.chimera_delta_encode(bp, len(base), tp, tlen, op, out_cap))
        _ = (kb, kt, ko)
        if rc < 0:
            return None
        return bytes(out[:rc])

    tbytes = bytes(target)
    return b"\x02" + struct.pack("<I", len(tbytes)) + tbytes


def delta_decode(
    base: bytes | bytearray | memoryview,
    patch: bytes | bytearray | memoryview,
    expected_len: int,
) -> bytes:
    """Reconstruct target bytes from `base` and `patch`."""
    if expected_len == 0:
        return b""
    if _DLL is not None:
        out = bytearray(expected_len)
        bp, kb = _ro_ptr(base)
        pp, kp = _ro_ptr(patch)
        op, ko = _rw_ptr(out)
        rc = int(_DLL.chimera_delta_decode(bp, len(base), pp, len(patch), op, expected_len))
        _ = (kb, kp, ko)
        if rc != expected_len:
            raise ValueError(f"Delta decode failed: rc={rc}, expected={expected_len}")
        return bytes(out)

    pos = 0
    plen = len(patch)
    out_buf = bytearray()
    mv = memoryview(patch)
    while pos < plen:
        op = mv[pos]
        pos += 1
        if op == 1:
            boff, mlen = struct.unpack_from("<II", mv, pos)
            pos += 8
            out_buf.extend(base[boff : boff + mlen])
        elif op == 2:
            (llen,) = struct.unpack_from("<I", mv, pos)
            pos += 4
            out_buf.extend(mv[pos : pos + llen])
            pos += llen
        else:
            raise ValueError(f"Unknown delta opcode: {op}")
    return bytes(out_buf)


def active_filter_lines(
    data: bytes | bytearray | memoryview, needle: bytes
) -> tuple[bytes, int]:
    """Filter newline-delimited lines containing `needle` at native Rust speed."""
    n = len(data)
    if n == 0:
        return b"", 0
    if _DLL is not None:
        out = bytearray(n)
        matched = ctypes.c_uint64(0)
        dp, kd = _ro_ptr(data)
        np_, kn = _ro_ptr(needle)
        op, ko = _rw_ptr(out)
        rc = int(
            _DLL.chimera_active_filter_lines(
                dp, n, np_, len(needle), op, n, ctypes.byref(matched)
            )
        )
        _ = (kd, kn, ko)
        if rc < 0:
            raise RuntimeError("active_filter_lines overflow")
        return bytes(out[:rc]), int(matched.value)

    lines = bytes(data).splitlines(keepends=True)
    hits = [ln for ln in lines if not needle or needle in ln]
    return b"".join(hits), len(hits)


def _normalize_wormhole_name(name: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in name)
    if os.name == "nt":
        if name.startswith("Local\\") or name.startswith("Global\\"):
            return name
        return f"Local\\CHIMERA_WH_{safe}"
    if name.startswith("/") and "/" not in name[1:]:
        return name
    return f"/chimera_wh_{safe}"[:250]


class WormholeChannel:
    """Lock-free cross-process Shared Memory ring buffer (Win32 CreateFileMappingW / POSIX shm_open)."""

    def __init__(self, handle: int, name: str, is_creator: bool) -> None:
        self._handle = int(handle)
        self.name = name
        self.is_creator = is_creator
        self._closed = False

    @classmethod
    def create(
        cls,
        name: str,
        capacity_mb: int = 16,
        capacity_bytes: int | None = None,
    ) -> "WormholeChannel":
        if _DLL is None:
            raise RuntimeError("WormholeChannel requires native _chimera_core shared library")
        cap = int(capacity_bytes) if capacity_bytes is not None else int(capacity_mb) * 1024 * 1024
        full_name = _normalize_wormhole_name(name)
        arg_name = full_name if os.name == "nt" else full_name.encode("utf-8")
        handle = _DLL.chimera_wormhole_create(arg_name, cap)
        if not handle:
            raise OSError(f"Wormhole shared memory create failed for '{full_name}'")
        return cls(handle, full_name, is_creator=True)

    @classmethod
    def open(cls, name: str, wait_timeout_s: float = 5.0) -> "WormholeChannel":
        if _DLL is None:
            raise RuntimeError("WormholeChannel requires native _chimera_core shared library")
        full_name = _normalize_wormhole_name(name)
        arg_name = full_name if os.name == "nt" else full_name.encode("utf-8")
        deadline = time.perf_counter() + max(0.05, wait_timeout_s)
        while True:
            handle = _DLL.chimera_wormhole_open(arg_name)
            if handle:
                return cls(handle, full_name, is_creator=False)
            if time.perf_counter() >= deadline:
                raise TimeoutError(f"Timed out waiting for wormhole '{full_name}'")
            time.sleep(0.005)

    def write_all(
        self, data: bytes | bytearray | memoryview, timeout_ms: int = 15000
    ) -> int:
        if self._closed:
            raise RuntimeError("WormholeChannel is closed")
        n = len(data)
        if n == 0:
            return 0
        dp, kd = _ro_ptr(data)
        rc = int(_DLL.chimera_wormhole_write(self._handle, dp, n, int(timeout_ms)))  # type: ignore[union-attr]
        _ = kd
        if rc == -2:
            raise TimeoutError(f"Wormhole write timed out after {timeout_ms} ms")
        if rc < 0 or rc != n:
            raise OSError(f"Wormhole write failed: wrote {rc}/{n} bytes")
        return rc

    def read_into(self, buf: bytearray | memoryview, timeout_ms: int = 15000) -> int:
        if self._closed:
            raise RuntimeError("WormholeChannel is closed")
        n = len(buf)
        if n == 0:
            return 0
        bp, kb = _rw_ptr(buf)
        rc = int(_DLL.chimera_wormhole_read(self._handle, bp, n, int(timeout_ms)))  # type: ignore[union-attr]
        _ = kb
        if rc == -2:
            raise TimeoutError(f"Wormhole read timed out after {timeout_ms} ms")
        if rc < 0:
            raise OSError(f"Wormhole read failed: rc={rc}")
        return rc

    def read_exact(self, n: int, timeout_ms: int = 15000) -> bytes:
        if n == 0:
            return b""
        out = bytearray(n)
        mv = memoryview(out)
        pos = 0
        while pos < n:
            got = self.read_into(mv[pos:], timeout_ms=timeout_ms)
            if got == 0:
                raise EOFError(f"Wormhole reached EOF at {pos}/{n} bytes")
            pos += got
        return bytes(out)

    def read_all(
        self, chunk_size: int = 4 * 1024 * 1024, timeout_ms: int = 15000
    ) -> bytes:
        chunks: list[bytes] = []
        buf = bytearray(max(4096, chunk_size))
        while True:
            got = self.read_into(buf, timeout_ms=timeout_ms)
            if got == 0:
                break
            chunks.append(bytes(buf[:got]))
        return b"".join(chunks)

    def mark_eof(self) -> None:
        if not self._closed and self._handle and _DLL is not None:
            _DLL.chimera_wormhole_mark_eof(self._handle)

    def close(self) -> None:
        if not self._closed and self._handle and _DLL is not None:
            self._closed = True
            _DLL.chimera_wormhole_close(self._handle)
            self._handle = 0

    def __enter__(self) -> "WormholeChannel":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass


def v7_native_caps() -> dict[str, bool]:
    return {
        "chacha20": _DLL is not None and hasattr(_DLL, "chimera_chacha20_xor"),
        "rlnc_recode": _DLL is not None and hasattr(_DLL, "chimera_gf256_recode"),
        "ppm_range": _DLL is not None and hasattr(_DLL, "chimera_ppm_compress"),
        "slepian_syndrome": _DLL is not None and hasattr(_DLL, "chimera_slepian_syndrome"),
    }


def _rotl32(v: int, n: int) -> int:
    return ((v << n) | (v >> (32 - n))) & 0xFFFFFFFF


def _chacha_block_py(key: bytes, nonce: bytes, counter: int) -> bytes:
    st = list(struct.unpack("<4I8II3I", b"expand 32-byte k" + key + struct.pack("<I", counter) + nonce))
    init = list(st)
    for _ in range(10):
        for a, b, c, d in (
            (0, 4, 8, 12),
            (1, 5, 9, 13),
            (2, 6, 10, 14),
            (3, 7, 11, 15),
            (0, 5, 10, 15),
            (1, 6, 11, 12),
            (2, 7, 8, 13),
            (3, 4, 9, 14),
        ):
            st[a] = (st[a] + st[b]) & 0xFFFFFFFF
            st[d] = _rotl32(st[d] ^ st[a], 16)
            st[c] = (st[c] + st[d]) & 0xFFFFFFFF
            st[b] = _rotl32(st[b] ^ st[c], 12)
            st[a] = (st[a] + st[b]) & 0xFFFFFFFF
            st[d] = _rotl32(st[d] ^ st[a], 8)
            st[c] = (st[c] + st[d]) & 0xFFFFFFFF
            st[b] = _rotl32(st[b] ^ st[c], 7)
    return struct.pack("<16I", *(((st[i] + init[i]) & 0xFFFFFFFF) for i in range(16)))


def chacha20_xor(data: bytes | bytearray, key32: bytes, nonce12: bytes, counter: int = 0) -> bytes:
    """RFC 8439 ChaCha20 XOR stream cipher (native Rust/C11 with pure-Python fallback)."""
    if len(key32) != 32 or len(nonce12) != 12:
        raise ValueError("ChaCha20 requires 32-byte key and 12-byte nonce")
    n = len(data)
    if n == 0:
        return b""
    out = bytearray(n)
    if _DLL is not None and hasattr(_DLL, "chimera_chacha20_xor"):
        op, ko = _rw_ptr(out)
        ip, ki = _ro_ptr(data)
        kp, kk = _ro_ptr(key32)
        np, kn = _ro_ptr(nonce12)
        _DLL.chimera_chacha20_xor(op, ip, n, kp, np, int(counter) & 0xFFFFFFFF)
        _ = (ko, ki, kk, kn)
        return bytes(out)
    ctr = int(counter) & 0xFFFFFFFF
    mv = bytes(data)
    for off in range(0, n, 64):
        ks = _chacha_block_py(key32, nonce12, ctr)
        chunk = min(64, n - off)
        for i in range(chunk):
            out[off + i] = mv[off + i] ^ ks[i]
        ctr = (ctr + 1) & 0xFFFFFFFF
    return bytes(out)


def gf256_recode(
    payloads_flat: bytes | bytearray,
    coeffs_flat: bytes | bytearray,
    m_in: int,
    k: int,
    block_len: int,
    weights: bytes,
) -> tuple[bytes, bytes]:
    """Recombine M coded RLNC packets directly in GF(256) without decoding plaintext."""
    if m_in <= 0 or k <= 0 or block_len <= 0:
        return b"", b""
    if len(weights) < m_in or len(payloads_flat) < m_in * block_len or len(coeffs_flat) < m_in * k:
        raise ValueError("Invalid buffer lengths for gf256_recode")
    out_p = bytearray(block_len)
    out_c = bytearray(k)
    if _DLL is not None and hasattr(_DLL, "chimera_gf256_recode"):
        pp_o, k1 = _rw_ptr(out_p)
        cp_o, k2 = _rw_ptr(out_c)
        pp_i, k3 = _ro_ptr(payloads_flat)
        cp_i, k4 = _ro_ptr(coeffs_flat)
        wp, k5 = _ro_ptr(weights)
        _DLL.chimera_gf256_recode(pp_o, cp_o, pp_i, cp_i, m_in, k, block_len, wp)
        _ = (k1, k2, k3, k4, k5)
        return bytes(out_p), bytes(out_c)
    for i in range(m_in):
        w = weights[i]
        if w != 0:
            gf256_mul_add(out_p, payloads_flat[i * block_len : (i + 1) * block_len], w)
            gf256_mul_add(out_c, coeffs_flat[i * k : (i + 1) * k], w)
    return bytes(out_p), bytes(out_c)


def slepian_syndrome(
    blocks_flat: bytes | bytearray,
    n_blocks: int,
    block_len: int,
    alpha: int = 0x03,
    num_parities: int = 4,
) -> bytes:
    """Compute Reed-Solomon/GF(256) linear syndromes for 0-RTT Slepian-Wolf blind delta sync."""
    if n_blocks <= 0 or block_len <= 0 or num_parities <= 0:
        return b""
    if len(blocks_flat) < n_blocks * block_len:
        raise ValueError("Invalid buffer size for slepian_syndrome")
    out = bytearray(num_parities * block_len)
    if _DLL is not None and hasattr(_DLL, "chimera_slepian_syndrome"):
        bp, kb = _ro_ptr(blocks_flat)
        op, ko = _rw_ptr(out)
        _DLL.chimera_slepian_syndrome(bp, n_blocks, block_len, int(alpha) & 0xFF, num_parities, op)
        _ = (kb, ko)
        return bytes(out)
    root = 1
    for j in range(num_parities):
        syn_j = bytearray(block_len)
        pow_cur = 1
        for i in range(n_blocks):
            if pow_cur != 0:
                gf256_mul_add(syn_j, blocks_flat[i * block_len : (i + 1) * block_len], pow_cur)
            pow_cur = MUL_BYTES[pow_cur][root]
        out[j * block_len : (j + 1) * block_len] = syn_j
        root = MUL_BYTES[root][alpha & 0xFF]
    return bytes(out)


def _ppm_shift_py(st: list[Any], out: bytearray) -> None:
    low, cache, cache_size = st[0], st[2], st[3]
    if (low & 0xFFFFFFFF) < 0xFF000000 or (low >> 32) != 0:
        temp = cache
        carry = (low >> 32) & 0xFF
        while True:
            out.append((temp + carry) & 0xFF)
            temp = 0xFF
            cache_size -= 1
            if cache_size == 0:
                break
        cache = (low >> 24) & 0xFF
    cache_size += 1
    low = (low & 0xFFFFFFFF) << 8
    st[0], st[2], st[3] = low, cache, cache_size


def ppm_compress(data: bytes | bytearray) -> bytes:
    """Bit-identical Order-2 Context-Mixing Range Coder (Rust/C11 native with pure-Python parity)."""
    n = len(data)
    if n == 0:
        return b"\x00\x00\x00\x00"
    raw = bytes(data)
    if _DLL is not None and hasattr(_DLL, "chimera_ppm_compress"):
        cap = n + max(64, n // 4) + 32
        out = bytearray(cap)
        ip, ki = _ro_ptr(raw)
        op, ko = _rw_ptr(out)
        rc = int(_DLL.chimera_ppm_compress(ip, n, op, cap))
        _ = (ki, ko)
        if rc >= 4:
            return bytes(out[:rc])

    p0 = [2048] * 256
    p1 = [2048] * 65536
    p2 = [2048] * 262144
    out_b = bytearray(struct.pack("<I", n))
    st: list[Any] = [0, 0xFFFFFFFF, 0, 1]
    prev1 = 0
    prev2 = 0
    for byte_val in raw:
        ctx = 1
        for k in range(7, -1, -1):
            c0 = ctx
            c1 = (prev1 << 8) | ctx
            c2 = ((((prev2 * 257) ^ (prev1 * 17)) & 0x3FF) << 8) | ctx
            pr = (p0[c0] + 2 * p1[c1] + 5 * p2[c2]) >> 3
            if pr < 1:
                pr = 1
            elif pr > 4095:
                pr = 4095
            bound = (st[1] >> 12) * pr
            bit = (byte_val >> k) & 1
            if bit:
                st[1] = bound
                p0[c0] += (4096 - p0[c0]) >> 5
                p1[c1] += (4096 - p1[c1]) >> 5
                p2[c2] += (4096 - p2[c2]) >> 5
            else:
                st[0] += bound
                st[1] -= bound
                p0[c0] -= p0[c0] >> 5
                p1[c1] -= p1[c1] >> 5
                p2[c2] -= p2[c2] >> 5
            if st[1] < 0x01000000:
                st[1] = (st[1] << 8) & 0xFFFFFFFF
                _ppm_shift_py(st, out_b)
            ctx = (ctx << 1) | bit
        prev2 = prev1
        prev1 = ctx & 0xFF
    for _ in range(5):
        _ppm_shift_py(st, out_b)
    return bytes(out_b)


def ppm_decompress(comp: bytes | bytearray) -> bytes:
    """Decompress bit-identical Order-2 Context-Mixing Range Coder frame."""
    if len(comp) < 4:
        raise ValueError("Truncated CHIMERA PPM frame")
    raw = bytes(comp)
    orig_len = struct.unpack_from("<I", raw, 0)[0]
    if orig_len == 0:
        return b""
    if _DLL is not None and hasattr(_DLL, "chimera_ppm_decompress"):
        out = bytearray(orig_len)
        ip, ki = _ro_ptr(raw)
        op, ko = _rw_ptr(out)
        rc = int(_DLL.chimera_ppm_decompress(ip, len(raw), op, orig_len))
        _ = (ki, ko)
        if rc == orig_len:
            return bytes(out)

    p0 = [2048] * 256
    p1 = [2048] * 65536
    p2 = [2048] * 262144
    stream = raw[4:]
    slen = len(stream)
    pos = 1 if slen > 0 else 0
    code = 0
    for _ in range(4):
        b = stream[pos] if pos < slen else 0
        if pos < slen:
            pos += 1
        code = ((code << 8) | b) & 0xFFFFFFFF
    rng = 0xFFFFFFFF
    out_dec = bytearray(orig_len)
    prev1 = 0
    prev2 = 0
    for i in range(orig_len):
        ctx = 1
        for _ in range(8):
            c0 = ctx
            c1 = (prev1 << 8) | ctx
            c2 = ((((prev2 * 257) ^ (prev1 * 17)) & 0x3FF) << 8) | ctx
            pr = (p0[c0] + 2 * p1[c1] + 5 * p2[c2]) >> 3
            if pr < 1:
                pr = 1
            elif pr > 4095:
                pr = 4095
            bound = (rng >> 12) * pr
            if code < bound:
                rng = bound
                bit = 1
                p0[c0] += (4096 - p0[c0]) >> 5
                p1[c1] += (4096 - p1[c1]) >> 5
                p2[c2] += (4096 - p2[c2]) >> 5
            else:
                code -= bound
                rng -= bound
                bit = 0
                p0[c0] -= p0[c0] >> 5
                p1[c1] -= p1[c1] >> 5
                p2[c2] -= p2[c2] >> 5
            if rng < 0x01000000:
                rng = (rng << 8) & 0xFFFFFFFF
                nb = stream[pos] if pos < slen else 0
                if pos < slen:
                    pos += 1
                code = ((code << 8) | nb) & 0xFFFFFFFF
            ctx = (ctx << 1) | bit
        out_dec[i] = ctx & 0xFF
        prev2 = prev1
        prev1 = ctx & 0xFF
    return bytes(out_dec)


def v8_native_caps() -> dict[str, bool]:
    return {
        "pir_xor": _DLL is not None and hasattr(_DLL, "chimera_pir_xor_query"),
        "fsk_demod": _DLL is not None and hasattr(_DLL, "chimera_fsk_demod_bits"),
    }


def pir_xor_query(
    db_flat: bytes | bytearray,
    n_records: int,
    rec_len: int,
    query_bits: bytes | bytearray,
) -> bytes:
    """Bit-identical 2-server IT-PIR XOR accumulator over contiguous fixed-length database records."""
    if n_records <= 0 or rec_len <= 0:
        return b""
    req_q = (n_records + 7) // 8
    if len(db_flat) < n_records * rec_len or len(query_bits) < req_q:
        raise ValueError("Invalid buffer lengths for pir_xor_query")
    out = bytearray(rec_len)
    if _DLL is not None and hasattr(_DLL, "chimera_pir_xor_query"):
        dp, kd = _ro_ptr(db_flat)
        qp, kq = _ro_ptr(query_bits)
        op, ko = _rw_ptr(out)
        _DLL.chimera_pir_xor_query(dp, n_records, rec_len, qp, op)
        _ = (kd, kq, ko)
        return bytes(out)
    mv = memoryview(db_flat)
    acc = 0
    for i in range(n_records):
        if (query_bits[i >> 3] >> (i & 7)) & 1:
            off = i * rec_len
            acc ^= int.from_bytes(mv[off : off + rec_len], "little")
    return acc.to_bytes(rec_len, "little")


_FSK_COS0 = (32767, -23170, 0, 23170, -32767, 23170, 0, -23170)
_FSK_SIN0 = (0, 23170, -32767, 23170, 0, -23170, 32767, -23170)
_FSK_COS1 = (32767, -26509, 10126, 10126, -26509)
_FSK_SIN1 = (0, 19260, -31164, 31164, -19260)


def fsk_demod_bits(pcm_bytes: bytes | bytearray) -> bytes:
    """Deterministic Q15 quadrature correlator demodulating 48kHz PCM (40 samples/bit) -> 0/1 bytes."""
    n_samples = len(pcm_bytes) // 2
    if n_samples < 40:
        return b""
    n_syms = n_samples // 40
    out = bytearray(n_syms)
    if _DLL is not None and hasattr(_DLL, "chimera_fsk_demod_bits"):
        pp, kp = _ro_ptr(pcm_bytes)
        op, ko = _rw_ptr(out)
        got = int(_DLL.chimera_fsk_demod_bits(pp, n_samples, op, n_syms))
        _ = (kp, ko)
        return bytes(out[:got])
    samples = struct.unpack_from(f"<{n_syms * 40}h", pcm_bytes, 0)
    for s in range(n_syms):
        base = s * 40
        i0 = q0 = i1 = q1 = 0
        idx5 = 0
        for j in range(40):
            x = samples[base + j]
            idx8 = j & 7
            i0 += x * _FSK_COS0[idx8]
            q0 += x * _FSK_SIN0[idx8]
            i1 += x * _FSK_COS1[idx5]
            q1 += x * _FSK_SIN1[idx5]
            idx5 += 1
            if idx5 == 5:
                idx5 = 0
        si0, sq0 = i0 >> 10, q0 >> 10
        si1, sq1 = i1 >> 10, q1 >> 10
        out[s] = 1 if (si1 * si1 + sq1 * sq1) > (si0 * si0 + sq0 * sq0) else 0
    return bytes(out)
