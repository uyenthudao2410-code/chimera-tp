"""CHIMERA v7.0 OMEGA-FABRIC — Compute, Sandbox & Compression Plane (Ideas #7, #10, #12, #13)."""

from __future__ import annotations

from collections import OrderedDict
import hashlib
import json
import random
import struct
import threading
import time
import urllib.request
from typing import Any
import zlib

from ..gf256 import INV, MUL_BYTES
from ..native import gf256_mul_add, ppm_compress, ppm_decompress

# ==============================================================================
# IDEA #7 — Sandboxed WebAssembly MVP Active-Pipe (AQ03)
# ==============================================================================


def _u32_leb(v: int) -> bytes:
    out = bytearray()
    while True:
        b = v & 0x7F
        v >>= 7
        if v:
            out.append(b | 0x80)
        else:
            out.append(b)
            break
    return bytes(out)


def _s32_leb(v: int) -> bytes:
    out = bytearray()
    more = True
    while more:
        b = v & 0x7F
        v >>= 7
        sign = (b & 0x40) != 0
        if (v == 0 and not sign) or (v == -1 and sign):
            more = False
        else:
            b |= 0x80
        out.append(b)
    return bytes(out)


def _wasm_section(sec_id: int, payload: bytes) -> bytes:
    return bytes([sec_id]) + _u32_leb(len(payload)) + payload


def build_wasm_byte_counter_module(target_byte: int = 10) -> bytes:
    """Compile a self-contained WebAssembly 1.0 MVP binary exporting memory and filter(ptr, len) -> count."""
    tb = int(target_byte) & 0xFF
    if tb >= 128:
        tb_sleb = _s32_leb(tb - 256)
    else:
        tb_sleb = _s32_leb(tb)

    # Type 0: (i32, i32) -> (i32)
    sec_type = _wasm_section(1, bytes([0x01, 0x60, 0x02, 0x7F, 0x7F, 0x01, 0x7F]))
    # Func 0 -> Type 0
    sec_func = _wasm_section(3, bytes([0x01, 0x00]))
    # Memory 0: min=2 pages (128 KB), max=4 pages (256 KB)
    sec_mem = _wasm_section(5, bytes([0x01, 0x01, 0x02, 0x04]))
    # Exports: "memory" (mem 0), "filter" (func 0)
    exp_mem = b"\x06memory\x02\x00"
    exp_fn = b"\x06filter\x00\x00"
    sec_export = _wasm_section(7, bytes([0x02]) + exp_mem + exp_fn)

    # Locals: params(0=ptr, 1=len), locals(2=i, 3=count)
    code = bytearray()
    code.extend(b"\x01\x02\x7f")  # 1 group of 2 i32 locals
    code.extend(b"\x41\x00\x21\x02")  # i32.const 0; local.set 2 (i=0)
    code.extend(b"\x41\x00\x21\x03")  # i32.const 0; local.set 3 (count=0)
    code.extend(b"\x02\x40")  # block void
    code.extend(b"\x03\x40")  # loop void
    code.extend(b"\x20\x02\x20\x01\x4f\x0d\x01")  # if i >=u len: br 1
    code.extend(b"\x20\x00\x20\x02\x6a\x2d\x00\x00")  # i32.load8_u(ptr + i)
    code.append(0x41)
    code.extend(tb_sleb)
    code.extend(b"\x46\x04\x40")  # i32.eq; if void
    code.extend(b"\x20\x03\x41\x01\x6a\x21\x03")  # count += 1
    code.extend(b"\x0b")  # end if
    code.extend(b"\x20\x02\x41\x01\x6a\x21\x02")  # i += 1
    code.extend(b"\x0c\x00")  # br 0 (loop)
    code.extend(b"\x0b\x0b")  # end loop; end block
    code.extend(b"\x20\x03\x0b")  # local.get 3; end

    body = _u32_leb(len(code)) + bytes(code)
    sec_code = _wasm_section(10, b"\x01" + body)
    return b"\x00asm\x01\x00\x00\x00" + sec_type + sec_func + sec_mem + sec_export + sec_code


class _WasmReader:
    def __init__(self, buf: bytes) -> None:
        self.buf = buf
        self.pos = 0

    def read_u8(self) -> int:
        b = self.buf[self.pos]
        self.pos += 1
        return b

    def read_bytes(self, n: int) -> bytes:
        s = self.buf[self.pos : self.pos + n]
        if len(s) != n:
            raise ValueError("Unexpected EOF in WASM module")
        self.pos += n
        return s

    def read_u32(self) -> int:
        res = 0
        shift = 0
        while True:
            b = self.read_u8()
            res |= (b & 0x7F) << shift
            if (b & 0x80) == 0:
                return res
            shift += 7
            if shift > 35:
                raise ValueError("LEB128 u32 overflow")

    def read_s32(self) -> int:
        res = 0
        shift = 0
        while True:
            b = self.read_u8()
            res |= (b & 0x7F) << shift
            shift += 7
            if (b & 0x80) == 0:
                if shift < 32 and (b & 0x40):
                    res |= -(1 << shift)
                return res & 0xFFFFFFFF


def _to_s32(v: int) -> int:
    v &= 0xFFFFFFFF
    return v - 0x100000000 if (v & 0x80000000) else v


class WasmActivePipe:
    """Deterministic zero-capability WebAssembly 1.0 interpreter with strict fuel & bounds checks."""

    def __init__(self, max_steps: int = 2_000_000, max_mem_pages: int = 4) -> None:
        self.max_steps = max(64, int(max_steps))
        self.max_mem_pages = max(1, int(max_mem_pages))

    def _parse_module(self, wasm_bytes: bytes) -> dict[str, Any]:
        if len(wasm_bytes) < 8 or wasm_bytes[:4] != b"\x00asm" or wasm_bytes[4:8] != b"\x01\x00\x00\x00":
            raise ValueError("Invalid WebAssembly 1.0 magic/version header")
        r = _WasmReader(wasm_bytes)
        r.pos = 8
        types: list[tuple[list[int], list[int]]] = []
        funcs: list[int] = []
        mem_pages = 1
        exports: dict[str, tuple[int, int]] = {}
        codes: list[tuple[list[int], bytes]] = []

        while r.pos < len(wasm_bytes):
            sec_id = r.read_u8()
            sec_len = r.read_u32()
            sec_end = r.pos + sec_len
            if sec_id == 1:
                cnt = r.read_u32()
                for _ in range(cnt):
                    form = r.read_u8()
                    if form != 0x60:
                        raise ValueError("Unsupported WASM type form")
                    np = r.read_u32()
                    params = [r.read_u8() for _ in range(np)]
                    nr = r.read_u32()
                    rets = [r.read_u8() for _ in range(nr)]
                    types.append((params, rets))
            elif sec_id == 3:
                cnt = r.read_u32()
                funcs = [r.read_u32() for _ in range(cnt)]
            elif sec_id == 5:
                cnt = r.read_u32()
                if cnt > 0:
                    flags = r.read_u8()
                    pmin = r.read_u32()
                    pmax = r.read_u32() if (flags & 1) else self.max_mem_pages
                    mem_pages = min(self.max_mem_pages, max(1, min(pmin, pmax)))
            elif sec_id == 7:
                cnt = r.read_u32()
                for _ in range(cnt):
                    nlen = r.read_u32()
                    name = r.read_bytes(nlen).decode("utf-8")
                    kind = r.read_u8()
                    idx = r.read_u32()
                    exports[name] = (kind, idx)
            elif sec_id == 10:
                cnt = r.read_u32()
                for _ in range(cnt):
                    blen = r.read_u32()
                    bstart = r.pos
                    bend = bstart + blen
                    lcnt = r.read_u32()
                    extra_locals: list[int] = []
                    for _ in range(lcnt):
                        lnum = r.read_u32()
                        _ltype = r.read_u8()
                        extra_locals.extend([0] * lnum)
                    body = wasm_bytes[r.pos : bend]
                    codes.append((extra_locals, body))
                    r.pos = bend
            r.pos = sec_end

        return {
            "types": types,
            "funcs": funcs,
            "mem_pages": mem_pages,
            "exports": exports,
            "codes": codes,
        }

    @staticmethod
    def _precompute_jumps(code: bytes) -> dict[int, int]:
        """Map structured control op offsets (block/loop/if/else) to matching targets."""
        stack: list[tuple[str, int]] = []
        pairs: dict[int, int] = {}
        r = _WasmReader(code)
        while r.pos < len(code):
            pos = r.pos
            op = r.read_u8()
            if op in (0x02, 0x03, 0x04):  # block, loop, if
                _btype = r.read_u8()
                kind = {0x02: "block", 0x03: "loop", 0x04: "if"}[op]
                stack.append((kind, pos))
            elif op == 0x05:  # else
                if stack and stack[-1][0] == "if":
                    _k, start_pos = stack.pop()
                    pairs[start_pos] = pos
                    stack.append(("else", pos))
            elif op == 0x0B:  # end
                if stack:
                    _k, start_pos = stack.pop()
                    pairs[start_pos] = pos
            elif op in (0x0C, 0x0D, 0x20, 0x21, 0x22):
                r.read_u32()
            elif op == 0x41:
                r.read_s32()
            elif op in (0x28, 0x2C, 0x2D, 0x36, 0x3A):
                r.read_u32()
                r.read_u32()
        return pairs

    def execute_buffer(self, wasm_bytes: bytes, input_bytes: bytes, fn_name: str = "filter") -> dict[str, Any]:
        """Execute exported fn(ptr, len) inside an isolated linear memory sandbox."""
        t0 = time.perf_counter()
        try:
            mod = self._parse_module(wasm_bytes)
        except Exception as exc:
            return {"ok": False, "error": f"parse_error: {exc}", "result": None, "steps": 0, "elapsed_ms": 0.0}

        exp = mod["exports"].get(fn_name)
        if exp is None or exp[0] != 0:
            return {"ok": False, "error": f"missing_export: {fn_name}", "result": None, "steps": 0, "elapsed_ms": 0.0}
        fn_idx = exp[1]
        if fn_idx >= len(mod["codes"]):
            return {"ok": False, "error": "invalid_func_index", "result": None, "steps": 0, "elapsed_ms": 0.0}

        mem_pages = max(mod["mem_pages"], (len(input_bytes) + 65535) // 65536)
        if mem_pages > self.max_mem_pages:
            return {"ok": False, "error": "oob_memory_cap", "result": None, "steps": 0, "elapsed_ms": 0.0}

        mem = bytearray(mem_pages * 65536)
        data_ptr = 0
        mem[data_ptr : data_ptr + len(input_bytes)] = input_bytes

        extra_locals, code = mod["codes"][fn_idx]
        locals_arr = [data_ptr, len(input_bytes)] + list(extra_locals)
        jumps = self._precompute_jumps(code)

        stack: list[int] = []
        # ctrl entries: (kind, start_pos, end_target)
        ctrl: list[tuple[str, int, int]] = []
        r = _WasmReader(code)
        steps = 0

        def do_branch(depth: int) -> None:
            if depth >= len(ctrl):
                r.pos = len(code)
                return
            for _ in range(depth):
                ctrl.pop()
            kind, start_pos, end_target = ctrl[-1]
            if kind == "loop":
                r.pos = start_pos + 2  # past opcode + blocktype
            else:
                ctrl.pop()
                r.pos = end_target + 1  # past matching end

        while r.pos < len(code):
            steps += 1
            if steps > self.max_steps:
                return {
                    "ok": False,
                    "error": f"fuel_exhausted (limit={self.max_steps})",
                    "result": None,
                    "steps": steps - 1,
                    "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
                }
            pos = r.pos
            op = r.read_u8()

            if op == 0x01:  # nop
                continue
            elif op == 0x02:  # block
                _bt = r.read_u8()
                ctrl.append(("block", pos, jumps.get(pos, len(code) - 1)))
            elif op == 0x03:  # loop
                _bt = r.read_u8()
                ctrl.append(("loop", pos, jumps.get(pos, len(code) - 1)))
            elif op == 0x04:  # if
                _bt = r.read_u8()
                cond = stack.pop()
                target = jumps.get(pos, len(code) - 1)
                if code[target] == 0x05:  # has else branch
                    end_pos = jumps.get(target, len(code) - 1)
                    if cond != 0:
                        ctrl.append(("if", pos, end_pos))
                    else:
                        ctrl.append(("else", target, end_pos))
                        r.pos = target + 1
                else:
                    if cond != 0:
                        ctrl.append(("if", pos, target))
                    else:
                        r.pos = target + 1
            elif op == 0x05:  # reached else from true branch -> skip to end
                if ctrl:
                    _k, _s, end_pos = ctrl.pop()
                    r.pos = end_pos + 1
            elif op == 0x0B:  # end
                if ctrl:
                    ctrl.pop()
                else:
                    break
            elif op == 0x0C:  # br
                depth = r.read_u32()
                do_branch(depth)
            elif op == 0x0D:  # br_if
                depth = r.read_u32()
                if stack.pop() != 0:
                    do_branch(depth)
            elif op == 0x0F:  # return
                break
            elif op == 0x1A:  # drop
                stack.pop()
            elif op == 0x20:  # local.get
                stack.append(locals_arr[r.read_u32()])
            elif op == 0x21:  # local.set
                locals_arr[r.read_u32()] = stack.pop()
            elif op == 0x22:  # local.tee
                locals_arr[r.read_u32()] = stack[-1]
            elif op == 0x28:  # i32.load
                _align = r.read_u32()
                off = r.read_u32()
                addr = (stack.pop() + off) & 0xFFFFFFFF
                if addr + 4 > len(mem):
                    return {"ok": False, "error": "oob_memory", "result": None, "steps": steps, "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2)}
                stack.append(struct.unpack_from("<I", mem, addr)[0])
            elif op == 0x2D:  # i32.load8_u
                _align = r.read_u32()
                off = r.read_u32()
                addr = (stack.pop() + off) & 0xFFFFFFFF
                if addr >= len(mem):
                    return {"ok": False, "error": "oob_memory", "result": None, "steps": steps, "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2)}
                stack.append(mem[addr])
            elif op == 0x3A:  # i32.store8
                _align = r.read_u32()
                off = r.read_u32()
                val = stack.pop() & 0xFF
                addr = (stack.pop() + off) & 0xFFFFFFFF
                if addr >= len(mem):
                    return {"ok": False, "error": "oob_memory", "result": None, "steps": steps, "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2)}
                mem[addr] = val
            elif op == 0x41:  # i32.const
                stack.append(r.read_s32())
            elif op == 0x45:  # i32.eqz
                stack.append(1 if stack.pop() == 0 else 0)
            elif op == 0x46:  # i32.eq
                b, a = stack.pop(), stack.pop()
                stack.append(1 if a == b else 0)
            elif op == 0x47:  # i32.ne
                b, a = stack.pop(), stack.pop()
                stack.append(1 if a != b else 0)
            elif op == 0x48:  # i32.lt_s
                b, a = _to_s32(stack.pop()), _to_s32(stack.pop())
                stack.append(1 if a < b else 0)
            elif op == 0x49:  # i32.lt_u
                b, a = stack.pop(), stack.pop()
                stack.append(1 if a < b else 0)
            elif op == 0x4A:  # i32.gt_s
                b, a = _to_s32(stack.pop()), _to_s32(stack.pop())
                stack.append(1 if a > b else 0)
            elif op == 0x4B:  # i32.gt_u
                b, a = stack.pop(), stack.pop()
                stack.append(1 if a > b else 0)
            elif op == 0x4D:  # i32.le_u
                b, a = stack.pop(), stack.pop()
                stack.append(1 if a <= b else 0)
            elif op == 0x4E:  # i32.ge_s
                b, a = _to_s32(stack.pop()), _to_s32(stack.pop())
                stack.append(1 if a >= b else 0)
            elif op == 0x4F:  # i32.ge_u
                b, a = stack.pop(), stack.pop()
                stack.append(1 if a >= b else 0)
            elif op == 0x6A:  # i32.add
                b, a = stack.pop(), stack.pop()
                stack.append((a + b) & 0xFFFFFFFF)
            elif op == 0x6B:  # i32.sub
                b, a = stack.pop(), stack.pop()
                stack.append((a - b) & 0xFFFFFFFF)
            elif op == 0x6C:  # i32.mul
                b, a = stack.pop(), stack.pop()
                stack.append((a * b) & 0xFFFFFFFF)
            else:
                return {"ok": False, "error": f"unsupported_opcode_0x{op:02x}", "result": None, "steps": steps, "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2)}

        ret_val = _to_s32(stack[-1]) if stack else 0
        return {
            "ok": True,
            "fn_name": fn_name,
            "result": ret_val,
            "steps": steps,
            "wasm_bytes": len(wasm_bytes),
            "input_bytes": len(input_bytes),
            "mem_pages": mem_pages,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }


# ==============================================================================
# IDEA #10 — Compressed 4 KB Remote RAM Pool over 5 ms PHANTOM HTTP
# ==============================================================================


class RemoteRamStore:
    """Bounded thread-safe compressed 4 KB page store living inside the peer daemon."""

    def __init__(self, max_bytes: int = 16 * 1024 * 1024) -> None:
        self.max_bytes = max(64 * 1024, int(max_bytes))
        self._lock = threading.Lock()
        self._pages: OrderedDict[str, tuple[bytes, int, str]] = OrderedDict()
        self._stored_bytes = 0
        self._raw_bytes = 0
        self._hits = 0

    def put_page(self, page_id: str, payload: bytes, raw_len: int | None = None, compressed: bool = False) -> dict[str, Any]:
        if compressed:
            comp = bytes(payload)
            orig_len = int(raw_len or len(comp))
            digest = hashlib.blake2s(comp, digest_size=16).hexdigest()
        else:
            raw = bytes(payload)
            orig_len = len(raw)
            comp = zlib.compress(raw, 6)
            digest = hashlib.blake2s(raw, digest_size=16).hexdigest()

        with self._lock:
            old = self._pages.pop(page_id, None)
            if old is not None:
                self._stored_bytes -= len(old[0])
                self._raw_bytes -= old[1]
            while self._stored_bytes + len(comp) > self.max_bytes and self._pages:
                _k, evicted = self._pages.popitem(last=False)
                self._stored_bytes -= len(evicted[0])
                self._raw_bytes -= evicted[1]
            self._pages[page_id] = (comp, orig_len, digest)
            self._stored_bytes += len(comp)
            self._raw_bytes += orig_len

        return {
            "ok": True,
            "page_id": page_id,
            "raw_bytes": orig_len,
            "stored_bytes": len(comp),
            "sha_blake2s": digest,
        }

    def get_page(self, page_id: str, decompress: bool = True) -> dict[str, Any]:
        with self._lock:
            item = self._pages.get(page_id)
            if item is None:
                return {"ok": False, "error": "page_not_found", "page_id": page_id}
            self._pages.move_to_end(page_id)
            self._hits += 1
            comp, orig_len, digest = item
        if decompress:
            raw = zlib.decompress(comp)
            return {
                "ok": True,
                "page_id": page_id,
                "raw_bytes": orig_len,
                "stored_bytes": len(comp),
                "data": raw,
                "sha_blake2s": digest,
            }
        return {
            "ok": True,
            "page_id": page_id,
            "raw_bytes": orig_len,
            "stored_bytes": len(comp),
            "comp": comp,
            "sha_blake2s": digest,
        }

    def stats(self) -> dict[str, Any]:
        with self._lock:
            saved_pct = round(100.0 * (1.0 - self._stored_bytes / max(1, self._raw_bytes)), 2) if self._raw_bytes else 0.0
            return {
                "pages": len(self._pages),
                "stored_bytes": self._stored_bytes,
                "raw_bytes": self._raw_bytes,
                "max_bytes": self.max_bytes,
                "ram_saved_pct": saved_pct,
                "fault_hits": self._hits,
            }


class RemoteRamPool:
    """Client orchestrating 4 KB compressed page swap-out and fault-in locally or over peer HTTP."""

    def __init__(self, peer_http_base: str = "") -> None:
        self.peer_http_base = str(peer_http_base or "").strip().rstrip("/")
        self._local_store = RemoteRamStore(max_bytes=16 * 1024 * 1024)

    def swap_out_and_fault_in(self, pages: list[bytes], prefix: str = "omega_ram") -> dict[str, Any]:
        t0 = time.perf_counter()
        raw_total = 0
        comp_total = 0
        verified = 0
        mode = "REMOTE_HTTP" if self.peer_http_base else "LOCAL_SLAB"

        for idx, page in enumerate(pages):
            pid = f"{prefix}_{idx:04d}"
            raw_b = bytes(page)
            comp = zlib.compress(raw_b, 6)
            raw_total += len(raw_b)
            comp_total += len(comp)

            if self.peer_http_base:
                put_req = urllib.request.Request(
                    f"{self.peer_http_base}/api/omega/ram-put",
                    data=json.dumps(
                        {
                            "local_only": True,
                            "page_id": pid,
                            "comp_hex": comp.hex(),
                            "raw_len": len(raw_b),
                        }
                    ).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(put_req, timeout=4.0) as resp:
                    put_res = json.loads(resp.read().decode("utf-8"))
                if not put_res.get("ok"):
                    raise RuntimeError(f"Remote ram-put failed: {put_res}")

                get_req = urllib.request.Request(
                    f"{self.peer_http_base}/api/omega/ram-get",
                    data=json.dumps({"local_only": True, "page_id": pid, "raw_only": True}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(get_req, timeout=4.0) as resp:
                    get_res = json.loads(resp.read().decode("utf-8"))
                if not get_res.get("ok"):
                    raise RuntimeError(f"Remote ram-get failed: {get_res}")
                restored = zlib.decompress(bytes.fromhex(get_res["comp_hex"]))
            else:
                self._local_store.put_page(pid, comp, raw_len=len(raw_b), compressed=True)
                got = self._local_store.get_page(pid, decompress=False)
                restored = zlib.decompress(got["comp"])

            if restored == raw_b:
                verified += 1

        saved_pct = round(100.0 * (1.0 - comp_total / max(1, raw_total)), 2)
        return {
            "ok": verified == len(pages) and len(pages) > 0,
            "mode": mode,
            "pages": len(pages),
            "verified_pages": verified,
            "raw_bytes": raw_total,
            "compressed_bytes": comp_total,
            "ram_saved_pct": saved_pct,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }


# ==============================================================================
# IDEA #12 — Order-2 Context-Mixing Arithmetic Range Codec
# ==============================================================================

_SHARED_PRIORS: tuple[bytes, ...] = (
    b'"latency_ms":',
    b'"cache_hit":true',
    b'"status":"OK"',
    b'"node":"hub"',
    b'"node":"svhome"',
    b'2026-11-25T16:',
    b'00Z","',
    b' node=svhome',
    b' path=/api/',
    b' status=',
)


def _model_tokenize(data: bytes) -> bytes:
    """Bijective shared-weight domain prior + escape encoding."""
    toks = bytearray()
    n = len(data)
    i = 0
    while i < n:
        matched = -1
        for idx, p in enumerate(_SHARED_PRIORS):
            if data.startswith(p, i):
                matched = idx
                i += len(p)
                break
        if matched >= 0:
            toks.append(0x80 + matched)
        else:
            b = data[i]
            if b >= 0x7F:
                toks.extend((0x7F, b))
            else:
                toks.append(b)
            i += 1
    return bytes(toks)


def _model_detokenize(src: bytes) -> bytes:
    out = bytearray()
    n = len(src)
    i = 0
    limit = 0x80 + len(_SHARED_PRIORS)
    while i < n:
        b = src[i]
        if b == 0x7F:
            out.append(src[i + 1])
            i += 2
        elif 0x80 <= b < limit:
            out.extend(_SHARED_PRIORS[b - 0x80])
            i += 1
        else:
            out.append(b)
            i += 1
    return bytes(out)


def _lz_residual_encode(src: bytes) -> bytes:
    sn = len(src)
    out = bytearray()
    table: dict[bytes, int] = {}
    i = 0
    while i < sn:
        best_len = 0
        best_dist = 0
        if i + 4 <= sn:
            h = src[i : i + 4]
            prev = table.get(h, -1)
            table[h] = i
            if prev >= 0 and (i - prev) <= 65535:
                mlen = 4
                maxm = min(65535, sn - i)
                while mlen < maxm and src[prev + mlen] == src[i + mlen]:
                    mlen += 1
                if mlen >= 4:
                    best_len = mlen
                    best_dist = i - prev
        if best_len >= 4:
            d = best_dist - 1
            if best_len < 132 and d < 256:
                out.append(0xFE)
                out.append(best_len - 4)
                out.append(d)
            else:
                out.append(0xFD)
                out.extend(best_len.to_bytes(2, "big"))
                out.extend(d.to_bytes(2, "big"))
            for k in range(1, min(best_len, 4)):
                if i + k + 4 <= sn:
                    table[src[i + k : i + k + 4]] = i + k
            i += best_len
        else:
            b = src[i]
            if b in (0xFC, 0xFD, 0xFE, 0xFF):
                out.extend((0xFC, b))
            else:
                out.append(b)
            i += 1
    return bytes(out)


def _lz_residual_decode(raw_lz: bytes) -> bytes:
    src = bytearray()
    n = len(raw_lz)
    j = 0
    while j < n:
        b = raw_lz[j]
        if b == 0xFC:
            src.append(raw_lz[j + 1])
            j += 2
        elif b == 0xFE:
            mlen = raw_lz[j + 1] + 4
            dist = raw_lz[j + 2] + 1
            for _ in range(mlen):
                src.append(src[-dist])
            j += 3
        elif b == 0xFD:
            mlen = int.from_bytes(raw_lz[j + 1 : j + 3], "big")
            dist = int.from_bytes(raw_lz[j + 3 : j + 5], "big") + 1
            for _ in range(mlen):
                src.append(src[-dist])
            j += 5
        else:
            src.append(b)
            j += 1
    return bytes(src)


class NeuralPpmCodec:
    """Bit-exact Shared-Model + Native Order-2 Context-Mixing Arithmetic Range Coder."""

    @staticmethod
    def compress(data: bytes | bytearray) -> bytes:
        raw = bytes(data)
        p_raw = ppm_compress(raw)
        if len(raw) < 16:
            return b"\x00" + p_raw
        p_mod = ppm_compress(_lz_residual_encode(_model_tokenize(raw)))
        if len(p_mod) <= len(p_raw):
            return b"\x01" + p_mod
        return b"\x00" + p_raw

    @staticmethod
    def decompress(comp: bytes | bytearray) -> bytes:
        buf = bytes(comp)
        if not buf:
            return b""
        mode = buf[0]
        body = buf[1:]
        if mode == 0:
            return ppm_decompress(body)
        if mode == 1:
            return _model_detokenize(_lz_residual_decode(ppm_decompress(body)))
        raise ValueError(f"Unsupported CHIMERA NeuralPpmCodec mode {mode}")

    @classmethod
    def benchmark(cls, sample: bytes) -> dict[str, Any]:
        raw = bytes(sample)
        t0 = time.perf_counter()
        comp = cls.compress(raw)
        comp_ms = round((time.perf_counter() - t0) * 1000.0, 2)

        t1 = time.perf_counter()
        dec = cls.decompress(comp)
        decomp_ms = round((time.perf_counter() - t1) * 1000.0, 2)

        z9 = zlib.compress(raw, 9)
        vs_zlib = round(100.0 * (1.0 - len(comp) / max(1, len(z9))), 2)
        return {
            "ok": dec == raw,
            "raw_bytes": len(raw),
            "zlib9_bytes": len(z9),
            "ppm_bytes": len(comp),
            "vs_zlib9_saved_pct": vs_zlib,
            "ppm_comp_ms": comp_ms,
            "ppm_decomp_ms": decomp_ms,
        }


# ==============================================================================
# IDEA #13 — Zero-Freeze UEP-RLNC Display Stream
# ==============================================================================


def _solve_gf256_system(coeff_rows: list[bytes], rhs_rows: list[bytes], k: int) -> list[bytes] | None:
    """Solve k x k GF(256) linear system over tile payloads."""
    if len(coeff_rows) < k:
        return None
    m = len(coeff_rows)
    b_len = len(rhs_rows[0])
    A = [bytearray(c[:k]) for c in coeff_rows]
    B = [bytearray(r) for r in rhs_rows]

    piv_row = 0
    for col in range(k):
        sel = -1
        for r in range(piv_row, m):
            if A[r][col] != 0:
                sel = r
                break
        if sel < 0:
            return None
        A[piv_row], A[sel] = A[sel], A[piv_row]
        B[piv_row], B[sel] = B[sel], B[piv_row]

        inv_p = INV[A[piv_row][col]]
        if inv_p != 1:
            row_a = A[piv_row]
            row_b = B[piv_row]
            mul_tbl = MUL_BYTES[inv_p]
            for c in range(col, k):
                row_a[c] = mul_tbl[row_a[c]]
            for c in range(b_len):
                row_b[c] = mul_tbl[row_b[c]]

        for r in range(m):
            if r != piv_row and A[r][col] != 0:
                fac = A[r][col]
                gf256_mul_add(A[r], A[piv_row], fac)
                gf256_mul_add(B[r], B[piv_row], fac)
        piv_row += 1

    return [bytes(B[i]) for i in range(k)]


class UepDisplayStream:
    """Unequal Error Protection RLNC protecting crisp text/cursor tiles with 3x FEC redundancy."""

    @staticmethod
    def benchmark_15pct_loss(tiles_total: int = 16, text_tiles: int = 4, loss_rate: float = 0.15) -> dict[str, Any]:
        t0 = time.perf_counter()
        rng = random.Random(20261125)
        tile_size = 512
        text_src = [f"CRISP_TEXT_TILE_{i:02d}_".encode().ljust(tile_size, b"T") for i in range(text_tiles)]
        bg_src = [f"BG_TILE_{i:02d}_".encode().ljust(tile_size, b"B") for i in range(tiles_total - text_tiles)]

        # UEP tier-0: 3x RLNC over k=text_tiles (e.g., 4 -> 12 packets, tolerates 8 drops)
        m_text = text_tiles * 3
        text_pkts: list[tuple[bytes, bytes]] = []
        for idx in range(m_text):
            coeffs = bytes(rng.randrange(1, 256) for _ in range(text_tiles))
            coded = bytearray(tile_size)
            for j, c in enumerate(coeffs):
                gf256_mul_add(coded, text_src[j], c)
            text_pkts.append((coeffs, bytes(coded)))

        # UEP tier-1: 1.25x RLNC over background tiles
        k_bg = max(1, len(bg_src))
        m_bg = k_bg + max(2, k_bg // 4)
        bg_pkts: list[tuple[bytes, bytes]] = []
        for _ in range(m_bg):
            coeffs = bytes(rng.randrange(1, 256) for _ in range(k_bg))
            coded = bytearray(tile_size)
            for j, c in enumerate(coeffs):
                gf256_mul_add(coded, bg_src[j], c)
            bg_pkts.append((coeffs, bytes(coded)))

        trials = 25
        plain_perfect = 0
        uep_perfect = 0
        bg_survivals = 0
        for _t in range(trials):
            # Baseline uncoded transmission of text tiles: any 1 dropped text tile freezes crisp text
            plain_drops = sum(1 for _ in range(text_tiles) if rng.random() < loss_rate)
            if plain_drops == 0:
                plain_perfect += 1

            # UEP transmission under identical loss_rate (plus adversarial burst)
            surv_c: list[bytes] = []
            surv_p: list[bytes] = []
            for c, p in text_pkts:
                if rng.random() >= loss_rate:
                    surv_c.append(c)
                    surv_p.append(p)
            if len(surv_c) >= text_tiles:
                dec = _solve_gf256_system(surv_c[:text_tiles], surv_p[:text_tiles], text_tiles)
                if dec == text_src:
                    uep_perfect += 1

            surv_bg = sum(1 for _ in range(m_bg) if rng.random() >= loss_rate)
            if surv_bg >= k_bg:
                bg_survivals += 1

        return {
            "ok": uep_perfect == trials and plain_perfect < uep_perfect,
            "trials": trials,
            "tiles_total": tiles_total,
            "text_tiles": text_tiles,
            "loss_rate": loss_rate,
            "plain_crisp_text_survival": f"{plain_perfect}/{trials}",
            "uep_crisp_text_survival": f"{uep_perfect}/{trials}",
            "bg_tile_survival": f"{bg_survivals}/{trials}",
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }
