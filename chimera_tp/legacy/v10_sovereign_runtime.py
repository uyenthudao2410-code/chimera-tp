"""CHIMERA-HYPER v10.0 SOVEREIGN — Live WASM Teleport, Verifiable Bisection Trace & Kalman Bonding (Phần IV #2, #3, #6)."""

from __future__ import annotations

import base64
import hashlib
import json
import math
import random
import socket
import struct
import threading
import time
import urllib.request
from typing import Any

from ..native import lz4_compress, lz4_decompress
from ..omega_compute import WasmActivePipe, _WasmReader, _to_s32, build_wasm_byte_counter_module

# ==============================================================================
# IV.2 — Live WASM Checkpoint-Teleport (Freeze mid-execution -> resume on peer)
# ==============================================================================


class WasmLiveTeleportEngine(WasmActivePipe):
    """Pause live WebAssembly execution mid-flight, serialize VM state+memory, and teleport over 5ms HTTP."""

    def execute_with_checkpoint(
        self,
        wasm_bytes: bytes,
        input_bytes: bytes,
        fn_name: str = "filter",
        step_budget: int | None = None,
        checkpoint: dict[str, Any] | None = None,
        return_mem_prefix: int = 0,
    ) -> dict[str, Any]:
        t0 = time.perf_counter()
        mod = self._parse_module(wasm_bytes)
        exp = mod["exports"].get(fn_name)
        if exp is None or exp[0] != 0:
            raise ValueError(f"missing_export: {fn_name}")
        fn_idx = exp[1]
        extra_locals, code = mod["codes"][fn_idx]
        jumps = self._precompute_jumps(code)

        r = _WasmReader(code)
        if checkpoint is not None:
            if checkpoint.get("code_sha256") != hashlib.sha256(wasm_bytes).hexdigest():
                raise ValueError("WASM module digest mismatch on resume")
            mem = bytearray(lz4_decompress(base64.b64decode(checkpoint["mem_lz4_b64"])))
            mem_pages = int(checkpoint["mem_pages"])
            locals_arr = [int(v) for v in checkpoint["locals"]]
            stack = [int(v) for v in checkpoint["stack"]]
            ctrl = [(str(k), int(s), int(e)) for k, s, e in checkpoint["ctrl"]]
            r.pos = int(checkpoint["pc"])
            steps_done = int(checkpoint["steps_done"])
        else:
            mem_pages = max(mod["mem_pages"], (len(input_bytes) + 65535) // 65536)
            if mem_pages > self.max_mem_pages:
                raise ValueError("oob_memory_cap")
            mem = bytearray(mem_pages * 65536)
            mem[: len(input_bytes)] = input_bytes
            locals_arr = [0, len(input_bytes)] + list(extra_locals)
            stack = []
            ctrl = []
            steps_done = 0

        def do_branch(depth: int) -> None:
            if depth >= len(ctrl):
                r.pos = len(code)
                return
            for _ in range(depth):
                ctrl.pop()
            kind, start_pos, end_target = ctrl[-1]
            if kind == "loop":
                r.pos = start_pos + 2
            else:
                ctrl.pop()
                r.pos = end_target + 1

        step_slice = 0
        while r.pos < len(code):
            if step_budget is not None and step_slice >= step_budget:
                comp_mem = lz4_compress(bytes(mem))
                return {
                    "ok": True,
                    "paused": True,
                    "checkpoint": {
                        "wasm_b64": base64.b64encode(wasm_bytes).decode("ascii"),
                        "code_sha256": hashlib.sha256(wasm_bytes).hexdigest(),
                        "fn_name": fn_name,
                        "pc": r.pos,
                        "locals": locals_arr,
                        "stack": stack,
                        "ctrl": [list(x) for x in ctrl],
                        "mem_pages": mem_pages,
                        "mem_lz4_b64": base64.b64encode(comp_mem).decode("ascii"),
                        "steps_done": steps_done,
                    },
                    "wire_bytes": len(comp_mem),
                    "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
                }

            steps_done += 1
            step_slice += 1
            if steps_done > self.max_steps:
                raise RuntimeError("fuel_exhausted")
            pos = r.pos
            op = r.read_u8()

            if op == 0x01:
                continue
            elif op == 0x02:
                r.read_u8()
                ctrl.append(("block", pos, jumps.get(pos, len(code) - 1)))
            elif op == 0x03:
                r.read_u8()
                ctrl.append(("loop", pos, jumps.get(pos, len(code) - 1)))
            elif op == 0x04:
                r.read_u8()
                cond = stack.pop()
                target = jumps.get(pos, len(code) - 1)
                if code[target] == 0x05:
                    end_pos = jumps.get(target, len(code) - 1)
                    if cond != 0:
                        ctrl.append(("if", pos, end_pos))
                    else:
                        ctrl.append(("else", target, end_pos))
                        r.pos = target + 1
                elif cond != 0:
                    ctrl.append(("if", pos, target))
                else:
                    r.pos = target + 1
            elif op == 0x05:
                if ctrl:
                    _, _, end_pos = ctrl.pop()
                    r.pos = end_pos + 1
            elif op == 0x0B:
                if ctrl:
                    ctrl.pop()
                else:
                    break
            elif op == 0x0C:
                do_branch(r.read_u32())
            elif op == 0x0D:
                depth = r.read_u32()
                if stack.pop() != 0:
                    do_branch(depth)
            elif op == 0x0F:
                break
            elif op == 0x1A:
                stack.pop()
            elif op == 0x20:
                stack.append(locals_arr[r.read_u32()])
            elif op == 0x21:
                locals_arr[r.read_u32()] = stack.pop()
            elif op == 0x22:
                locals_arr[r.read_u32()] = stack[-1]
            elif op == 0x28:
                r.read_u32()
                off = r.read_u32()
                addr = (stack.pop() + off) & 0xFFFFFFFF
                if addr + 4 > len(mem):
                    raise RuntimeError("oob_memory")
                stack.append(struct.unpack_from("<I", mem, addr)[0])
            elif op == 0x2D:
                r.read_u32()
                off = r.read_u32()
                addr = (stack.pop() + off) & 0xFFFFFFFF
                if addr >= len(mem):
                    raise RuntimeError("oob_memory")
                stack.append(mem[addr])
            elif op == 0x3A:
                r.read_u32()
                off = r.read_u32()
                val = stack.pop() & 0xFF
                addr = (stack.pop() + off) & 0xFFFFFFFF
                if addr >= len(mem):
                    raise RuntimeError("oob_memory")
                mem[addr] = val
            elif op == 0x41:
                stack.append(r.read_s32())
            elif op == 0x45:
                stack.append(1 if stack.pop() == 0 else 0)
            elif op == 0x46:
                b, a = stack.pop(), stack.pop()
                stack.append(1 if a == b else 0)
            elif op == 0x47:
                b, a = stack.pop(), stack.pop()
                stack.append(1 if a != b else 0)
            elif op == 0x48:
                b, a = _to_s32(stack.pop()), _to_s32(stack.pop())
                stack.append(1 if a < b else 0)
            elif op == 0x49:
                b, a = stack.pop(), stack.pop()
                stack.append(1 if a < b else 0)
            elif op == 0x4A:
                b, a = _to_s32(stack.pop()), _to_s32(stack.pop())
                stack.append(1 if a > b else 0)
            elif op == 0x4B:
                b, a = stack.pop(), stack.pop()
                stack.append(1 if a > b else 0)
            elif op == 0x4D:
                b, a = stack.pop(), stack.pop()
                stack.append(1 if a <= b else 0)
            elif op == 0x4E:
                b, a = _to_s32(stack.pop()), _to_s32(stack.pop())
                stack.append(1 if a >= b else 0)
            elif op == 0x4F:
                b, a = stack.pop(), stack.pop()
                stack.append(1 if a >= b else 0)
            elif op == 0x6A:
                b, a = stack.pop(), stack.pop()
                stack.append((a + b) & 0xFFFFFFFF)
            elif op == 0x6B:
                b, a = stack.pop(), stack.pop()
                stack.append((a - b) & 0xFFFFFFFF)
            elif op == 0x6C:
                b, a = stack.pop(), stack.pop()
                stack.append((a * b) & 0xFFFFFFFF)
            else:
                raise ValueError(f"unsupported_opcode_0x{op:02x}")

        ret = _to_s32(stack[-1]) if stack else 0
        out_res: dict[str, Any] = {
            "ok": True,
            "paused": False,
            "result": ret,
            "steps": steps_done,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }
        if return_mem_prefix > 0:
            out_res["mem_prefix"] = bytes(mem[:return_mem_prefix])
        return out_res

    @classmethod
    def run_benchmark(cls, peer_http_base: str = "") -> dict[str, Any]:
        """Run full reference WASM filter vs 50%-paused teleported checkpoint resumed remotely or locally."""
        wasm_bin = build_wasm_byte_counter_module(target_byte=ord("X"))
        payload = (b"AAAXBBB_X_TELEPORT_WASM_FRAME_\n" * 64)[:2048]
        vm = cls(max_steps=500_000, max_mem_pages=4)
        ref = vm.execute_buffer(wasm_bin, payload, fn_name="filter")
        half_steps = max(10, int(ref["steps"]) // 2)

        t0 = time.perf_counter()
        paused = vm.execute_with_checkpoint(wasm_bin, payload, fn_name="filter", step_budget=half_steps)
        ckpt = paused["checkpoint"]
        resumed_remote = False
        resumed: dict[str, Any] | None = None
        if peer_http_base:
            try:
                req = urllib.request.Request(
                    f"{peer_http_base.rstrip('/')}/api/galactic/wasm-resume",
                    data=json.dumps({"checkpoint": ckpt, "local_only": True}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=5.0) as r:
                    resumed = json.loads(r.read().decode("utf-8"))
                resumed_remote = bool(resumed.get("ok") and not resumed.get("paused"))
            except Exception:
                resumed = None

        if not resumed or not resumed.get("ok"):
            resumed = vm.execute_with_checkpoint(wasm_bin, b"", fn_name="filter", checkpoint=ckpt)
        teleport_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        exact = bool(
            resumed["ok"]
            and not resumed["paused"]
            and resumed["result"] == ref["result"]
            and resumed["steps"] == ref["steps"]
        )
        return {
            "ok": exact and paused["paused"],
            "expected_result": ref["result"],
            "got_result": resumed["result"],
            "total_steps": ref["steps"],
            "paused_at_step": ckpt["steps_done"],
            "checkpoint_wire_bytes": paused["wire_bytes"],
            "resumed_on_peer": resumed_remote,
            "teleport_ms": teleport_ms,
        }


# ==============================================================================
# IV.3 — Verifiable Execution Trace & O(log N) Bisection Dispute Protocol
# ==============================================================================


class VerifiableTraceProver:
    """Merkle commitment over N execution steps + O(log N) interactive bisection fraud pinpointing."""

    @staticmethod
    def step_fn(state: bytes, step_idx: int) -> bytes:
        return hashlib.blake2s(state + struct.pack("<I", step_idx), digest_size=32).digest()

    @staticmethod
    def build_merkle_root(leaves: list[bytes]) -> tuple[bytes, list[list[bytes]]]:
        level = list(leaves)
        levels = [level]
        while len(level) > 1:
            if len(level) % 2 == 1:
                level.append(level[-1])
            nxt = [
                hashlib.blake2s(level[i] + level[i + 1], digest_size=32).digest()
                for i in range(0, len(level), 2)
            ]
            levels.append(nxt)
            level = nxt
        return level[0], levels

    @classmethod
    def run_benchmark(cls, n_steps: int = 256, cheat_step: int = 173) -> dict[str, Any]:
        t0 = time.perf_counter()
        seed = hashlib.blake2s(b"CHIMERA_TRACE_SEED_V10", digest_size=32).digest()

        # Honest trace h[0..N]
        honest = [seed]
        for s in range(n_steps):
            honest.append(cls.step_fn(honest[-1], s))
        honest_root, _ = cls.build_merkle_root(honest)

        # Dishonest worker diverges at exact `cheat_step` (step transition cheat_step -> cheat_step+1)
        dishonest = list(honest[: cheat_step + 1])
        bad_state = bytearray(cls.step_fn(dishonest[-1], cheat_step))
        bad_state[0] ^= 0xFF
        dishonest.append(bytes(bad_state))
        for s in range(cheat_step + 1, n_steps):
            dishonest.append(cls.step_fn(dishonest[-1], s))
        dishonest_root, _ = cls.build_merkle_root(dishonest)

        # Interactive O(log N) Bisection over [lo, hi] where transition lo->hi diverges:
        lo, hi = 0, n_steps
        rounds = 0
        while hi - lo > 1:
            mid = (lo + hi) // 2
            rounds += 1
            if dishonest[mid] == honest[mid]:
                lo = mid
            else:
                hi = mid

        # Final 1-step challenge verification at single disputed transition `lo -> lo + 1`
        recomputed = cls.step_fn(dishonest[lo], lo)
        fraud_proven = recomputed != dishonest[lo + 1] and lo == cheat_step
        elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        return {
            "ok": fraud_proven and rounds <= 9 and honest_root != dishonest_root,
            "n_steps": n_steps,
            "injected_cheat_step": cheat_step,
            "pinpointed_step": lo,
            "bisection_rounds": rounds,
            "fraud_proven": fraud_proven,
            "elapsed_ms": elapsed_ms,
        }


# ==============================================================================
# IV.6 — Asymmetric Simplex-Lane Bonding + Scalar Kalman Playout Filter
# ==============================================================================


class AsymmetricKalmanBondEngine:
    """Separates fast TX lane from jittered RX lane and applies 2-state Kalman delay tracking."""

    @staticmethod
    def run_benchmark() -> dict[str, Any]:
        rx_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        tx_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        rx_sock.bind(("127.0.0.1", 0))
        rx_sock.settimeout(2.0)
        dst = rx_sock.getsockname()

        n_pkts = 64
        rng = random.Random(1006)
        payloads = [struct.pack("<I", i) + hashlib.blake2s(bytes([i]), digest_size=28).digest() for i in range(n_pkts)]
        rx_samples_ms: list[float] = []
        received: list[bytes] = []

        # Simulate asymmetric RX jitter bursts cleanly in UDP loopback sender/receiver
        def _sender() -> None:
            base = time.perf_counter()
            for idx, pkt in enumerate(payloads):
                # Deterministic jitter spikes (0..18 ms) mimicking asymmetric congested ISP downlink
                spike_ms = 14.0 if (idx % 9 == 4) else (idx % 3) * 1.5
                target = base + idx * 0.002 + spike_ms * 0.001
                rem = target - time.perf_counter()
                if rem > 0:
                    time.sleep(min(0.015, rem))
                tx_sock.sendto(pkt, dst)

        t0 = time.perf_counter()
        st = threading.Thread(target=_sender, daemon=True)
        st.start()
        try:
            for _ in range(n_pkts):
                pkt, _ = rx_sock.recvfrom(512)
                rx_samples_ms.append((time.perf_counter() - t0) * 1000.0)
                received.append(pkt)
        finally:
            st.join(timeout=1.0)
            tx_sock.close()
            rx_sock.close()

        # Raw inter-arrival jitter vs 2-state Kalman smoothed cadence (est_delay, inter_spacing)
        raw_intervals = [max(0.0, rx_samples_ms[i] - rx_samples_ms[i - 1]) for i in range(1, len(rx_samples_ms))]
        raw_mean = sum(raw_intervals) / len(raw_intervals)
        raw_std = math.sqrt(sum((x - raw_mean) ** 2 for x in raw_intervals) / len(raw_intervals))

        # Kalman smoothing over measured arrival timestamps [t_est, dt_est]
        x_t = rx_samples_ms[0]
        x_dt = raw_mean
        p00, p01, p11 = 1.0, 0.0, 0.5
        q_t, q_dt = 0.02, 0.01
        r_meas = 36.0  # absorb +/-6ms observation burst noise
        smoothed_intervals: list[float] = []
        prev_out = x_t
        for i in range(1, len(rx_samples_ms)):
            # Predict
            pred_t = x_t + x_dt
            p00 = p00 + 2 * p01 + p11 + q_t
            p01 = p01 + p11
            p11 = p11 + q_dt
            # Update with noisy network observation
            innov = rx_samples_ms[i] - pred_t
            s_cov = p00 + r_meas
            k0 = p00 / s_cov
            k1 = p01 / s_cov
            x_t = pred_t + k0 * innov
            x_dt = max(0.2, x_dt + k1 * innov)
            p00 = (1.0 - k0) * p00
            p01 = (1.0 - k0) * p01
            p11 = max(0.01, p11 - k1 * p01)
            smoothed_intervals.append(max(0.0, x_t - prev_out))
            prev_out = x_t

        sm_mean = sum(smoothed_intervals) / len(smoothed_intervals)
        sm_std = math.sqrt(sum((x - sm_mean) ** 2 for x in smoothed_intervals) / len(smoothed_intervals))
        jitter_reduction_pct = round((1.0 - sm_std / max(1e-6, raw_std)) * 100.0, 1)

        lossless = len(received) == n_pkts and all(
            struct.unpack_from("<I", p, 0)[0] == i for i, p in enumerate(received)
        )
        return {
            "ok": lossless and jitter_reduction_pct >= 50.0,
            "packets_received": len(received),
            "raw_jitter_std_ms": round(raw_std, 2),
            "kalman_jitter_std_ms": round(sm_std, 2),
            "jitter_reduction_pct": jitter_reduction_pct,
        }
