"""Measure a small CUDA VMM allocation in a disposable Windows process."""
from __future__ import annotations

import argparse
import ctypes as ct
import hashlib
import json
import os
import sys
import time


SIZE = 2 * 1024 * 1024
U64 = ct.c_uint64
SIZE_T = ct.c_size_t
P = ct.POINTER
NOW = time.perf_counter_ns


class Location(ct.Structure):
    _fields_ = [("type", ct.c_int), ("id", ct.c_int)]


class AllocationFlags(ct.Structure):
    _fields_ = [
        ("compression_type", ct.c_ubyte), ("gpu_direct_rdma", ct.c_ubyte),
        ("usage", ct.c_ushort), ("reserved", ct.c_ubyte * 4),
    ]


class AllocationProp(ct.Structure):
    _fields_ = [
        ("type", ct.c_int), ("handle_types", ct.c_int), ("location", Location),
        ("windows_metadata", ct.c_void_p), ("flags", AllocationFlags),
    ]


class Access(ct.Structure):
    _fields_ = [("location", Location), ("flags", ct.c_int)]


class Unsupported(Exception):
    """The machine cannot run this experiment."""


class InvalidStagingCopy(ValueError):
    def __init__(self, observed_digest):
        super().__init__("migration digest mismatch")
        self.observed_digest = observed_digest


def emit(kind, **fields):
    print(json.dumps({"type": kind, **fields}, allow_nan=False), flush=True)


def checkpoint(stage, **fields):
    emit("sample", stage=stage, pid=os.getpid(), **fields)
    if sys.stdin.readline().rstrip() != "continue":
        raise RuntimeError("memory observer disconnected")


def elapsed(start):
    return (NOW() - start) / 1_000_000


class Driver:
    def __init__(self):
        if sys.platform != "win32" or ct.sizeof(ct.c_void_p) != 8:
            raise Unsupported("requires 64-bit Windows")
        try:
            self.lib = ct.WinDLL("nvcuda.dll", winmode=0x800)
        except OSError as error:
            raise Unsupported(str(error)) from error
        signatures = {
            "cuGetErrorName": [ct.c_int, P(ct.c_char_p)],
            "cuInit": [ct.c_uint],
            "cuDriverGetVersion": [P(ct.c_int)],
            "cuDeviceGet": [P(ct.c_int), ct.c_int],
            "cuDeviceGetName": [P(ct.c_char), ct.c_int, ct.c_int],
            "cuDeviceGetPCIBusId": [P(ct.c_char), ct.c_int, ct.c_int],
            "cuDeviceGetLuid": [P(ct.c_char), P(ct.c_uint), ct.c_int],
            "cuDeviceGetAttribute": [P(ct.c_int), ct.c_int, ct.c_int],
            "cuCtxCreate_v2": [P(ct.c_void_p), ct.c_uint, ct.c_int],
            "cuCtxDestroy_v2": [ct.c_void_p],
            "cuCtxSynchronize": [],
            "cuMemGetInfo_v2": [P(SIZE_T), P(SIZE_T)],
            "cuMemGetAllocationGranularity": [P(SIZE_T), P(AllocationProp), ct.c_int],
            "cuMemAddressReserve": [P(U64), SIZE_T, SIZE_T, U64, U64],
            "cuMemAddressFree": [U64, SIZE_T],
            "cuMemCreate": [P(U64), SIZE_T, P(AllocationProp), U64],
            "cuMemMap": [U64, SIZE_T, SIZE_T, U64, U64],
            "cuMemUnmap": [U64, SIZE_T],
            "cuMemRelease": [U64],
            "cuMemSetAccess": [U64, SIZE_T, P(Access), SIZE_T],
            "cuMemcpyHtoD_v2": [U64, ct.c_void_p, SIZE_T],
            "cuMemcpyDtoH_v2": [ct.c_void_p, U64, SIZE_T],
        }
        for name, args in signatures.items():
            try:
                fn = getattr(self.lib, name)
            except AttributeError as error:
                raise Unsupported(f"missing CUDA driver entry point {name}") from error
            fn.argtypes = args
            fn.restype = ct.c_int
            if name != "cuGetErrorName":
                fn.errcheck = self.check

    def check(self, code, function, arguments):
        if code:
            name = ct.c_char_p()
            self.lib.cuGetErrorName(code, ct.byref(name))
            label = name.value.decode("ascii") if name.value else str(code)
            if label in {"CUDA_ERROR_NO_DEVICE", "CUDA_ERROR_NOT_SUPPORTED"}:
                raise Unsupported(f"{function.__name__}: {label}")
            raise RuntimeError(f"{function.__name__}: {label}")
        return code

    def memory(self):
        free, total = SIZE_T(), SIZE_T()
        self.lib.cuMemGetInfo_v2(ct.byref(free), ct.byref(total))
        return {"free_bytes": free.value, "total_bytes": total.value}


class Page:
    def __init__(self, cuda, prop, size):
        self.cu, self.prop, self.size = cuda, prop, size
        self.ptr, self.handle = U64(), U64()
        self.reserved = self.mapped = self.owned = False

    def allocate(self):
        self.cu.cuMemAddressReserve(ct.byref(self.ptr), self.size, 0, 0, 0)
        self.reserved = True
        self.cu.cuMemCreate(ct.byref(self.handle), self.size, ct.byref(self.prop), 0)
        self.owned = True
        self.cu.cuMemMap(self.ptr, self.size, 0, self.handle, 0)
        self.mapped = True
        rights = Access(self.prop.location, 3)  # CU_MEM_ACCESS_FLAGS_PROT_READWRITE
        self.cu.cuMemSetAccess(self.ptr, self.size, ct.byref(rights), 1)

    def release_backing(self):
        start = NOW()
        self.cu.cuMemUnmap(self.ptr, self.size)
        split = NOW()
        self.mapped = False
        self.cu.cuMemRelease(self.handle)
        end = NOW()
        self.owned = False
        return {
            "unmap": (split - start) / 1e6, "release": (end - split) / 1e6,
            "unmap_plus_release": (end - start) / 1e6,
        }

    def close(self):
        if self.mapped:
            self.cu.cuMemUnmap(self.ptr, self.size)
            self.mapped = False
        if self.owned:
            self.cu.cuMemRelease(self.handle)
            self.owned = False
        if self.reserved:
            self.cu.cuMemAddressFree(self.ptr, self.size)
            self.reserved = False


def verified_release(page, readback, expected, corrupt_staging=False):
    start = NOW()
    page.cu.cuMemcpyDtoH_v2(readback, page.ptr, SIZE)
    copied = NOW()
    if corrupt_staging:
        first_byte = readback[0][0]
        readback[0] = bytes([first_byte ^ 1])
    actual = hashlib.sha256(readback).hexdigest()
    if expected != actual:
        raise InvalidStagingCopy(actual)
    verified = NOW()
    times = page.release_backing()
    times.update({
        "copy_to_host": (copied - start) / 1e6,
        "verify_sha256": (verified - copied) / 1e6,
        "copy_verify_unmap_release": elapsed(start),
    })
    return actual, times


def migration(driver, prop, alloc_size, run, observe=False):
    cu = driver.lib
    seed = f"chimera.cuda-vmm-shadow.v1/{run}".encode("ascii")
    source = hashlib.shake_256(seed).digest(SIZE)
    expected = hashlib.sha256(source).hexdigest()
    readback, recovered = ct.create_string_buffer(SIZE), ct.create_string_buffer(SIZE)
    times, rejected_digest = {}, None
    page = Page(cu, prop, alloc_size)
    try:
        start = NOW()
        page.allocate()
        times["allocate_map_set_access"] = elapsed(start)
        start = NOW()
        cu.cuMemcpyHtoD_v2(page.ptr, source, SIZE)
        cu.cuCtxSynchronize()
        times["upload_and_sync"] = elapsed(start)
        if observe:
            checkpoint("resident_page", cuda_memory=driver.memory())
            try:
                verified_release(page, readback, expected, corrupt_staging=True)
            except InvalidStagingCopy as error:
                rejected_digest = error.observed_digest
                if not page.mapped or not page.owned:
                    raise RuntimeError("corrupt staging copy released the GPU page") from error
            else:
                raise RuntimeError("corrupt staging copy passed verification")

        # In the observed round, retry from the original mapping after rejecting corruption.
        actual, yield_times = verified_release(page, readback, expected)
        times.update(yield_times)
        start = NOW()
        cu.cuCtxSynchronize()
        times["post_release_synchronize"] = elapsed(start)
        if observe:
            checkpoint("released_page_keep_context", cuda_memory=driver.memory())
        start = NOW()
        page.close()
        times["address_free"] = elapsed(start)
    finally:
        page.close()

    # Restore directly from the verified host copy to a new allocation.
    restored_page = Page(cu, prop, alloc_size)
    try:
        start = NOW()
        restored_page.allocate()
        cu.cuMemcpyHtoD_v2(restored_page.ptr, readback, SIZE)
        cu.cuCtxSynchronize()
        cu.cuMemcpyDtoH_v2(recovered, restored_page.ptr, SIZE)
        restored = hashlib.sha256(recovered).hexdigest()
        if actual != restored:
            raise ValueError("restored digest mismatch")
        times["restore_round_trip_verify"] = elapsed(start)
    finally:
        restored_page.close()
    return {
        "run": run, "sha256_before": expected, "sha256_migrated": actual,
        "sha256_restored": restored, "rejected_staging_sha256": rejected_digest,
        "phase_ms": times,
    }


def measure(trials):
    driver = Driver()
    cu = driver.lib
    device, version, support = ct.c_int(), ct.c_int(), ct.c_int()
    name, bus, luid = ct.create_string_buffer(128), ct.create_string_buffer(32), ct.create_string_buffer(8)
    mask = ct.c_uint()
    cu.cuInit(0)
    cu.cuDriverGetVersion(ct.byref(version))
    cu.cuDeviceGet(ct.byref(device), 0)
    cu.cuDeviceGetName(name, len(name), device)
    cu.cuDeviceGetPCIBusId(bus, len(bus), device)
    cu.cuDeviceGetAttribute(ct.byref(support), 102, device)
    cu.cuDeviceGetLuid(luid, ct.byref(mask), device)
    low, high = int.from_bytes(luid.raw[:4], "little"), int.from_bytes(luid.raw[4:], "little")
    emit("device", name=name.value.decode(), pci_bus=bus.value.decode(), cuda_driver_version=version.value,
         luid=f"luid_0x{high:08x}_0x{low:08x}", luid_node_mask=mask.value, vmm_supported=bool(support.value))
    if not support.value:
        raise Unsupported("VIRTUAL_MEMORY_MANAGEMENT_SUPPORTED=0")

    prop = AllocationProp()
    prop.type = 1  # CU_MEM_ALLOCATION_TYPE_PINNED
    prop.location = Location(1, device.value)  # CU_MEM_LOCATION_TYPE_DEVICE
    gran = SIZE_T()
    checkpoint("driver_initialized")
    context = ct.c_void_p()
    start = NOW()
    cu.cuCtxCreate_v2(ct.byref(context), 0, device)
    create_ms = elapsed(start)
    try:
        cu.cuMemGetAllocationGranularity(ct.byref(gran), ct.byref(prop), 0)
        if not 0 < gran.value <= 16 * 1024 * 1024:
            raise Unsupported(f"minimum allocation granularity exceeds fixture budget: {gran.value}")
        size = ((SIZE + gran.value - 1) // gran.value) * gran.value
        emit("allocation", payload_bytes=SIZE, allocation_bytes=size, min_granularity_bytes=gran.value)
        checkpoint("empty_context", cuda_memory=driver.memory())
        observed = migration(driver, prop, size, "observed", observe=True)
        emit("observed", **observed)
        for run in range(1, trials + 1):
            emit("trial", **migration(driver, prop, size, run))
    finally:
        start = NOW()
        cu.cuCtxDestroy_v2(context)
        destroy_ms = elapsed(start)
    checkpoint("context_destroyed")
    emit("completed", create_context_ms=create_ms, destroy_context_ms=destroy_ms)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trials", type=int, required=True, choices=range(2, 101), metavar="2..100")
    args = parser.parse_args()
    try:
        measure(args.trials)
    except (Unsupported, OSError, RuntimeError, ValueError) as error:
        state = "unsupported" if isinstance(error, Unsupported) else "failed"
        emit(state, error=str(error))
        sys.exit(2 if state == "unsupported" else 1)
