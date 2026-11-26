"""Zero-dependency NVIDIA CUDA Driver API (nvcuda.dll) PTX JIT kernel runner for idle Windows GTX 1650."""

from __future__ import annotations

import ctypes
import math
import os
import threading
import time
from typing import Any


_PTX_VEC_MUL = b"""
.version 7.0
.target sm_75
.address_size 64
.visible .entry vec_dot_elem(
    .param .u64 p_a,
    .param .u64 p_b,
    .param .u64 p_out,
    .param .u32 p_n
) {
    .reg .pred %p<2>;
    .reg .b32 %r<5>;
    .reg .f32 %f<4>;
    .reg .b64 %rd<9>;
    ld.param.u64 %rd1, [p_a];
    ld.param.u64 %rd2, [p_b];
    ld.param.u64 %rd3, [p_out];
    ld.param.u32 %r1, [p_n];
    mov.u32 %r2, %ctaid.x;
    mov.u32 %r3, %ntid.x;
    mov.u32 %r4, %tid.x;
    mad.lo.s32 %r2, %r2, %r3, %r4;
    setp.ge.u32 %p1, %r2, %r1;
    @%p1 bra DONE;
    mul.wide.u32 %rd4, %r2, 4;
    add.s64 %rd5, %rd1, %rd4;
    add.s64 %rd6, %rd2, %rd4;
    add.s64 %rd7, %rd3, %rd4;
    ld.global.f32 %f1, [%rd5];
    ld.global.f32 %f2, [%rd6];
    mul.f32 %f3, %f1, %f2;
    st.global.f32 [%rd7], %f3;
DONE:
    ret;
}
"""


class NvCudaPtxEngine:
    """Lazy, zero-install CUDA PTX JIT accelerator via nvcuda.dll / libcuda.so (0 MB idle VRAM)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cu: Any = None
        self._device_name: str = ""
        self._sm: str = ""
        self._available: bool | None = None
        self._runs = 0

    def probe(self) -> dict[str, Any]:
        with self._lock:
            if self._available is not None:
                return {
                    "available": self._available,
                    "device": self._device_name,
                    "sm": self._sm,
                    "runs": self._runs,
                }
            try:
                lib = ctypes.WinDLL("nvcuda.dll") if os.name == "nt" else ctypes.CDLL("libcuda.so.1")
                lib.cuInit.argtypes = [ctypes.c_uint]
                lib.cuDeviceGet.argtypes = [ctypes.POINTER(ctypes.c_int), ctypes.c_int]
                lib.cuDeviceGetName.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.c_int]
                lib.cuDeviceGetAttribute.argtypes = [ctypes.POINTER(ctypes.c_int), ctypes.c_int, ctypes.c_int]
                lib.cuCtxCreate_v2.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.c_uint, ctypes.c_int]
                lib.cuCtxDestroy_v2.argtypes = [ctypes.c_void_p]
                lib.cuModuleLoadData.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.c_char_p]
                lib.cuModuleGetFunction.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p, ctypes.c_char_p]
                lib.cuMemAlloc_v2.argtypes = [ctypes.POINTER(ctypes.c_uint64), ctypes.c_size_t]
                lib.cuMemFree_v2.argtypes = [ctypes.c_uint64]
                lib.cuMemcpyHtoD_v2.argtypes = [ctypes.c_uint64, ctypes.c_void_p, ctypes.c_size_t]
                lib.cuMemcpyDtoH_v2.argtypes = [ctypes.c_void_p, ctypes.c_uint64, ctypes.c_size_t]
                lib.cuLaunchKernel.argtypes = [
                    ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint,
                    ctypes.c_uint, ctypes.c_uint, ctypes.c_uint,
                    ctypes.c_uint, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p),
                ]
                lib.cuCtxSynchronize.argtypes = []
                if lib.cuInit(0) != 0:
                    raise RuntimeError("cuInit failed")
                dev = ctypes.c_int(0)
                if lib.cuDeviceGet(ctypes.byref(dev), 0) != 0:
                    raise RuntimeError("cuDeviceGet failed")
                buf = ctypes.create_string_buffer(128)
                lib.cuDeviceGetName(buf, 128, dev)
                maj, minv = ctypes.c_int(0), ctypes.c_int(0)
                lib.cuDeviceGetAttribute(ctypes.byref(maj), 75, dev)
                lib.cuDeviceGetAttribute(ctypes.byref(minv), 76, dev)
                self._cu = lib
                self._device_name = buf.value.decode("utf-8", errors="ignore")
                self._sm = f"{maj.value}.{minv.value}"
                self._available = True
            except Exception:
                self._available = False
            return {
                "available": bool(self._available),
                "device": self._device_name,
                "sm": self._sm,
                "runs": self._runs,
            }

    def run_vec_dot_kernel(self, vec_a: list[float], vec_b: list[float]) -> dict[str, Any]:
        """Execute elementwise product on GTX 1650 silicon via inline PTX JIT and destroy context cleanly (0 MB VRAM retained)."""
        info = self.probe()
        if not info["available"]:
            raise RuntimeError("nvcuda PTX JIT not available on this host")
        n = min(len(vec_a), len(vec_b))
        if n <= 0:
            return {"ok": True, "dot": 0.0, "n": 0, "elapsed_ms": 0.0, "device": self._device_name}

        t0 = time.perf_counter()
        with self._lock:
            cu = self._cu
            dev = ctypes.c_int(0)
            ctx = ctypes.c_void_p()
            da, db, do = ctypes.c_uint64(0), ctypes.c_uint64(0), ctypes.c_uint64(0)
            if cu.cuDeviceGet(ctypes.byref(dev), 0) != 0:
                raise RuntimeError("cuDeviceGet failed")
            if cu.cuCtxCreate_v2(ctypes.byref(ctx), 0, dev) != 0:
                raise RuntimeError("cuCtxCreate_v2 failed")
            try:
                mod = ctypes.c_void_p()
                if cu.cuModuleLoadData(ctypes.byref(mod), _PTX_VEC_MUL) != 0:
                    raise RuntimeError("cuModuleLoadData PTX failed")
                fn = ctypes.c_void_p()
                if cu.cuModuleGetFunction(ctypes.byref(fn), mod, b"vec_dot_elem") != 0:
                    raise RuntimeError("cuModuleGetFunction failed")

                ca = (ctypes.c_float * n)(*vec_a[:n])
                cb = (ctypes.c_float * n)(*vec_b[:n])
                cout = (ctypes.c_float * n)()
                nbytes = n * 4
                assert cu.cuMemAlloc_v2(ctypes.byref(da), nbytes) == 0
                assert cu.cuMemAlloc_v2(ctypes.byref(db), nbytes) == 0
                assert cu.cuMemAlloc_v2(ctypes.byref(do), nbytes) == 0

                t_k = time.perf_counter()
                cu.cuMemcpyHtoD_v2(da, ca, nbytes)
                cu.cuMemcpyHtoD_v2(db, cb, nbytes)
                cn = ctypes.c_uint32(n)
                params = (ctypes.c_void_p * 4)(
                    ctypes.addressof(da), ctypes.addressof(db), ctypes.addressof(do), ctypes.addressof(cn)
                )
                grid_x = (n + 255) // 256
                assert cu.cuLaunchKernel(fn, grid_x, 1, 1, 256, 1, 1, 0, None, params, None) == 0
                assert cu.cuCtxSynchronize() == 0
                cu.cuMemcpyDtoH_v2(cout, do, nbytes)
                kernel_ms = (time.perf_counter() - t_k) * 1000.0
                dot = float(sum(cout))
                self._runs += 1
            finally:
                for ptr in (da, db, do):
                    if ptr.value:
                        cu.cuMemFree_v2(ptr)
                cu.cuCtxDestroy_v2(ctx)

        return {
            "ok": True,
            "device": self._device_name,
            "sm": self._sm,
            "n": n,
            "dot": round(dot, 6),
            "kernel_ms": round(kernel_ms, 3),
            "total_ms": round((time.perf_counter() - t0) * 1000.0, 3),
            "vram_retained_mb": 0.0,
        }
