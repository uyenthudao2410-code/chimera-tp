"""AES-256-GCM through the OpenSSL EVP provider used by the host Python runtime."""

from __future__ import annotations

import ctypes as ct
import ctypes.util
from functools import lru_cache
import os
from pathlib import Path
import ssl
import sys


class InvalidParcelTag(ValueError):
    """The authentication tag did not verify. No plaintext is released."""


@lru_cache(maxsize=1)
def _library():
    if os.name == "nt":
        # CPython for Windows ships OpenSSL alongside _ssl.pyd in its DLLs directory.
        version = ssl.OPENSSL_VERSION_INFO
        suffix = str(version[0]) if version[0] >= 3 else f"{version[0]}_{version[1]}"
        directory = Path(sys.base_prefix) / "DLLs"
        choices = [directory / f"libcrypto-{suffix}{arch}.dll" for arch in ("", "-x64", "-arm64")]
        name = next((str(p) for p in choices if p.is_file()), None)
    else:
        name = ctypes.util.find_library("crypto")
    if not name:
        raise RuntimeError("the host OpenSSL libcrypto shared library is required for AES-GCM")
    lib = ct.CDLL(name)
    pointer, integer = ct.c_void_p, ct.c_int
    signatures = {
        "EVP_CIPHER_CTX_new": (pointer, []),
        "EVP_CIPHER_CTX_free": (None, [pointer]),
        "EVP_aes_256_gcm": (pointer, []),
        "EVP_CipherInit_ex": (integer, [pointer, pointer, pointer, pointer, pointer, integer]),
        "EVP_CipherUpdate": (integer, [pointer, pointer, ct.POINTER(integer), pointer, integer]),
        "EVP_CipherFinal_ex": (integer, [pointer, pointer, ct.POINTER(integer)]),
        "EVP_CIPHER_CTX_ctrl": (integer, [pointer, integer, integer, pointer]),
    }
    for symbol, (result, arguments) in signatures.items():
        function = getattr(lib, symbol)
        function.argtypes = arguments
        function.restype = result
    return lib


def _require(status):
    if status != 1:
        raise RuntimeError("OpenSSL AES-GCM provider operation failed")


def transform(key: bytes, nonce: bytes, aad: bytes, data: bytes, *, encrypt: bool) -> bytes:
    if len(key) != 32 or len(nonce) != 12 or (not encrypt and len(data) < 16):
        raise ValueError("AES-256-GCM requires a 32-byte key, 12-byte nonce and 16-byte tag")
    lib = _library()
    ctx = lib.EVP_CIPHER_CTX_new()
    if not ctx:
        raise RuntimeError("could not allocate OpenSSL cipher context")
    # The OpenSSL EVP GCM IV length defaults to 12. GET_TAG and SET_TAG are
    # EVP_CTRL_AEAD_GET_TAG and EVP_CTRL_AEAD_SET_TAG from openssl/evp.h.
    payload = data if encrypt else data[:-16]
    out = ct.create_string_buffer(len(payload) + 16)
    count = ct.c_int()
    try:
        _require(lib.EVP_CipherInit_ex(ctx, lib.EVP_aes_256_gcm(), None, key, nonce, int(encrypt)))
        _require(lib.EVP_CipherUpdate(ctx, None, ct.byref(count), aad, len(aad)))
        _require(lib.EVP_CipherUpdate(ctx, out, ct.byref(count), payload, len(payload)))
        size = count.value
        tag = ct.create_string_buffer(16) if encrypt else ct.create_string_buffer(data[-16:], 16)
        if not encrypt:
            _require(lib.EVP_CIPHER_CTX_ctrl(ctx, 0x11, 16, tag))
        status = lib.EVP_CipherFinal_ex(ctx, ct.byref(out, size), ct.byref(count))
        if not encrypt and status != 1:
            # Existing optional cryptography clients that catch InvalidTag have
            # already imported their exception. A standalone installation gets
            # the standard ValueError subclass above, without loading that package.
            error = getattr(sys.modules.get("cryptography.exceptions"), "InvalidTag", InvalidParcelTag)
            raise error("parcel authentication failed")
        _require(status)
        result = out.raw[:size + count.value]
        if encrypt:
            _require(lib.EVP_CIPHER_CTX_ctrl(ctx, 0x10, 16, tag))
            result += tag.raw
        return result
    finally:
        ct.memset(out, 0, len(out))
        lib.EVP_CIPHER_CTX_free(ctx)
