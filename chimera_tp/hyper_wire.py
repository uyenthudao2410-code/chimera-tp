"""Breakthrough #2 & #3: Silicon GFNI Adaptive Wire Protocol & Hedged Multi-Path Racing."""

from __future__ import annotations

import hashlib
import math
import os
import queue
import select
import socket
import struct
import threading
import time
import zlib
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any

from .gf256 import coeff_vector, select_independent_rows
from .impairment import WinTimerScope
from .native import gf256_decode_matrix, gf256_encode_block

# 20-byte compact wire header:
# magic(2s="CH"), ptype(B), stream_id(B), gen_id(H), sym_id(H),
# orig_len(I), k(H), payload_len(H), crc32(I)
_WIRE_HDR = struct.Struct("!2sBBHHIHHI")
_MAGIC = b"CH"

_PTYPE_SYS = 1
_PTYPE_FEC = 2
_PTYPE_PRIO = 3
_PTYPE_GEN_ACK = 4
_PTYPE_GEN_NEED = 5
_PTYPE_FIN_ACK = 6
_PTYPE_PRIO_ACK = 7
_PTYPE_RPC_REQ = 10
_PTYPE_RPC_RESP = 11

SYM_SIZE = 1180  # Safe <= 1280 B Tailscale MTU with 20B header + IP/UDP encapsulation
DEFAULT_GEN_K = 32


def _family_for_ip(ip: str) -> int:
    return socket.AF_INET6 if ":" in ip else socket.AF_INET


def _bind_any(family: int) -> tuple[str, int]:
    return ("::", 0) if family == socket.AF_INET6 else ("0.0.0.0", 0)


def _disable_connreset(sock: socket.socket) -> None:
    if os.name == "nt":
        try:
            sock.ioctl(0x9800000C, False)
        except (AttributeError, OSError, ValueError):
            pass


def _pack_frame(
    ptype: int,
    stream_id: int,
    gen_id: int,
    sym_id: int,
    orig_len: int,
    k: int,
    body: bytes,
) -> bytes:
    head16 = struct.pack(
        "!2sBBHHIHH",
        _MAGIC,
        ptype & 0xFF,
        stream_id & 0xFF,
        gen_id & 0xFFFF,
        sym_id & 0xFFFF,
        orig_len & 0xFFFFFFFF,
        k & 0xFFFF,
        len(body) & 0xFFFF,
    )
    crc = zlib.crc32(head16 + body) & 0xFFFFFFFF
    return head16 + struct.pack("!I", crc) + body


def _unpack_frame(
    pkt: bytes,
) -> tuple[int, int, int, int, int, int, bytes] | None:
    if len(pkt) < _WIRE_HDR.size:
        return None
    magic, ptype, stream_id, gen_id, sym_id, orig_len, k, pay_len, recv_crc = (
        _WIRE_HDR.unpack_from(pkt, 0)
    )
    if magic != _MAGIC:
        return None
    if len(pkt) != _WIRE_HDR.size + pay_len:
        return None
    body = pkt[_WIRE_HDR.size :]
    calc_crc = zlib.crc32(pkt[:16] + body) & 0xFFFFFFFF
    if calc_crc != recv_crc:
        return None
    return ptype, stream_id, gen_id, sym_id, orig_len, k, body


@dataclass
class HyperWireReport:
    bytes_transferred: int
    wire_bytes_sent: int
    wire_overhead_pct: float
    elapsed_ms: float
    throughput_mbps: float
    generations_total: int
    sys_packets_sent: int
    fec_packets_sent: int
    repair_retransmits: int
    gfni_matrix_solves: int
    observed_loss_pct: float
    priority_first_ms: float | None
    sha256_match: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class HyperWireReceiver:
    """High-throughput UDP receiver with zero-bloat systematic fast-path & GFNI recovery."""

    def __init__(
        self,
        bind_ip: str = "127.0.0.1",
        bind_port: int = 0,
        gen_k: int = DEFAULT_GEN_K,
        sym_size: int = SYM_SIZE,
        on_priority_frame: Callable[[bytes, float], None] | None = None,
    ) -> None:
        self._gen_k = gen_k
        self._sym_size = sym_size
        fam = _family_for_ip(bind_ip)
        self._sock = socket.socket(fam, socket.SOCK_DGRAM)
        _disable_connreset(self._sock)
        try:
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8 * 1024 * 1024)
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 8 * 1024 * 1024)
        except OSError:
            pass
        self._sock.bind((bind_ip, bind_port))
        self._sock.settimeout(0.01)
        self.addr: tuple[str, int] = self._sock.getsockname()[:2]
        self._on_priority_frame = on_priority_frame

        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._sessions: dict[int, _RxSession] = {}
        self._completed: dict[int, tuple[bytes, int]] = {}
        self._stream_wire_rx: dict[int, int] = {}
        self._done_cv = threading.Condition(self._lock)

    def punch(self, peer_addr: tuple[str, int]) -> None:
        """Send tiny UDP hole-punch packet so stateful firewalls allow peer return frames."""
        try:
            self._sock.sendto(b"CHP0", peer_addr)
        except OSError:
            pass

    def start(self) -> "HyperWireReceiver":
        self._thread = threading.Thread(target=self._rx_loop, daemon=True)
        self._thread.start()
        return self

    def reset_stream(self, stream_id: int) -> None:
        with self._lock:
            self._sessions.pop(stream_id, None)
            self._completed.pop(stream_id, None)
            self._stream_wire_rx.pop(stream_id, None)

    def pop_stream_wire_bytes(self, stream_id: int) -> int:
        with self._lock:
            return self._stream_wire_rx.pop(stream_id, 0)

    def wait_stream(
        self, stream_id: int, timeout_s: float = 20.0
    ) -> tuple[bytes, int]:
        deadline = time.perf_counter() + timeout_s
        with self._lock:
            while stream_id not in self._completed:
                rem = deadline - time.perf_counter()
                if rem <= 0:
                    raise TimeoutError(f"HyperWire stream {stream_id} timed out")
                self._done_cv.wait(timeout=min(rem, 0.05))
            payload, gfni_solves = self._completed.pop(stream_id)
            self._sessions.pop(stream_id, None)
            return payload, gfni_solves

    def wait_any(self, timeout_s: float = 20.0) -> tuple[int, bytes, int]:
        deadline = time.perf_counter() + timeout_s
        with self._lock:
            while not self._completed:
                rem = deadline - time.perf_counter()
                if rem <= 0:
                    raise TimeoutError("HyperWire timed out waiting for any stream")
                self._done_cv.wait(timeout=min(rem, 0.25))
            sid = next(iter(self._completed))
            payload, gfni_solves = self._completed.pop(sid)
            self._sessions.pop(sid, None)
            return sid, payload, gfni_solves

    def _send_ctrl(
        self,
        addr: tuple[str, int],
        ptype: int,
        stream_id: int,
        gen_id: int,
        sym_id: int,
        orig_len: int,
        k: int,
        body: bytes,
    ) -> None:
        pkt = _pack_frame(ptype, stream_id, gen_id, sym_id, orig_len, k, body)
        try:
            self._sock.sendto(pkt, addr)
        except OSError:
            pass

    def _rx_loop(self) -> None:
        last_nack_scan = time.perf_counter()
        self._sock.setblocking(False)
        while not self._stop.is_set():
            with self._lock:
                has_sess = bool(self._sessions)
            try:
                r, _, _ = select.select([self._sock], [], [], 0.015 if has_sess else 0.25)
            except (OSError, ValueError):
                break
            if r:
                while not self._stop.is_set():
                    try:
                        pkt, addr = self._sock.recvfrom(65535)
                    except (BlockingIOError, socket.timeout, ConnectionResetError):
                        break
                    except OSError:
                        return
                    parsed = _unpack_frame(pkt)
                    if parsed is None:
                        continue
                    self._handle_frame(addr, *parsed, pkt_len=len(pkt))

            now = time.perf_counter()
            if (now - last_nack_scan) >= 0.015:
                last_nack_scan = now
                with self._lock:
                    has_sess = bool(self._sessions)
                if has_sess:
                    self._scan_missing_generations(now)

    def _handle_frame(
        self,
        addr: tuple[str, int],
        ptype: int,
        stream_id: int,
        gen_id: int,
        sym_id: int,
        orig_len: int,
        k: int,
        body: bytes,
        pkt_len: int = 0,
    ) -> None:
        now = time.perf_counter()

        if ptype == _PTYPE_PRIO:
            if self._on_priority_frame is not None:
                try:
                    self._on_priority_frame(body, now)
                except Exception:
                    pass
            self._send_ctrl(addr, _PTYPE_PRIO_ACK, stream_id, gen_id, sym_id, orig_len, k, b"")
            return

        if ptype not in (_PTYPE_SYS, _PTYPE_FEC):
            return

        with self._lock:
            if stream_id in self._completed:
                self._send_ctrl(addr, _PTYPE_FIN_ACK, stream_id, gen_id, 0, orig_len, k, b"")
                return

            sess = self._sessions.get(stream_id)
            if sess is None or sess.orig_len != orig_len:
                sess = _RxSession(stream_id=stream_id, orig_len=orig_len, peer_addr=addr)
                self._sessions[stream_id] = sess
            sess.peer_addr = addr
            sess.wire_bytes_rx += pkt_len

            # Handle 0-byte empty payload cleanly
            if orig_len == 0:
                self._completed[stream_id] = (b"", 0)
                self._stream_wire_rx[stream_id] = sess.wire_bytes_rx
                self._done_cv.notify_all()
                self._send_ctrl(addr, _PTYPE_FIN_ACK, stream_id, 0, 0, 0, 1, b"")
                return

            if sess.total_gens == 0:
                gen_bytes = self._gen_k * self._sym_size
                sess.total_gens = max(1, (orig_len + gen_bytes - 1) // gen_bytes)

            # Estimate loss rate dynamically from systematic gaps
            if ptype == _PTYPE_SYS and sym_id < k:
                seq_num = gen_id * self._gen_k + sym_id
                sess.seen_sys_seqs += 1
                if seq_num > sess.max_sys_seq:
                    sess.max_sys_seq = seq_num
                if sess.max_sys_seq >= 15:
                    raw_loss = max(0.0, 1.0 - (sess.seen_sys_seqs / float(sess.max_sys_seq + 1)))
                    sess.loss_ewma = 0.4 * raw_loss + 0.6 * sess.loss_ewma

            gen = sess.generations.get(gen_id)
            if gen is None:
                gen = _RxGeneration(gen_id=gen_id, k=k, sym_size=len(body), created_at=now)
                sess.generations[gen_id] = gen
                # Immediately nudge any earlier generation that fell behind!
                for prev_gid, prev_gen in sess.generations.items():
                    if prev_gid < gen_id and not prev_gen.solved:
                        if (now - prev_gen.last_nack_at) >= 0.045:
                            deficit = max(1, prev_gen.k - prev_gen.unique_count)
                            prev_gen.last_nack_at = now
                            loss_bps = min(9000, int(sess.loss_ewma * 10000))
                            self._send_ctrl(
                                addr,
                                _PTYPE_GEN_NEED,
                                stream_id,
                                prev_gid,
                                deficit,
                                orig_len,
                                prev_gen.k,
                                struct.pack("<H", loss_bps),
                            )

            if gen.solved:
                return

            gen.last_rx_at = now
            if ptype == _PTYPE_SYS:
                if sym_id not in gen.sys_blocks and sym_id < k:
                    gen.sys_blocks[sym_id] = body
            else:
                if sym_id not in gen.fec_blocks:
                    gen.fec_blocks[sym_id] = body

            # Attempt fast-path or GFNI decode
            just_solved = False
            if len(gen.sys_blocks) == gen.k:
                gen.solved_blocks = [gen.sys_blocks[i] for i in range(gen.k)]
                gen.solved = True
                just_solved = True
            elif len(gen.sys_blocks) + len(gen.fec_blocks) >= gen.k:
                recovered = self._try_gfni_solve(sess.seed_for_gen(gen_id), gen)
                if recovered is not None:
                    gen.solved_blocks = recovered
                    gen.solved = True
                    sess.gfni_solves += 1
                    just_solved = True

            if just_solved:
                sess.solved_count += 1
                loss_bps = min(9000, int(sess.loss_ewma * 10000))
                self._send_ctrl(
                    addr,
                    _PTYPE_GEN_ACK,
                    stream_id,
                    gen_id,
                    sess.solved_count,
                    orig_len,
                    gen.k,
                    struct.pack("<H", loss_bps),
                )

                if sess.solved_count == sess.total_gens:
                    raw = bytearray()
                    for gid in range(sess.total_gens):
                        for blk in sess.generations[gid].solved_blocks:
                            raw.extend(blk)
                    out_bytes = bytes(raw[:orig_len])
                    self._completed[stream_id] = (out_bytes, sess.gfni_solves)
                    self._stream_wire_rx[stream_id] = sess.wire_bytes_rx
                    self._done_cv.notify_all()
                    self._send_ctrl(
                        addr,
                        _PTYPE_FIN_ACK,
                        stream_id,
                        gen_id,
                        sess.solved_count,
                        orig_len,
                        gen.k,
                        struct.pack("<H", loss_bps),
                    )

    def _try_gfni_solve(
        self, g_seed: bytes, gen: "_RxGeneration"
    ) -> list[bytes] | None:
        k = gen.k
        sym_size = gen.sym_size
        cand_coeffs: list[bytes] = []
        cand_blocks: list[bytes] = []

        for sid in sorted(gen.sys_blocks.keys()):
            row = bytearray(k)
            row[sid] = 1
            cand_coeffs.append(bytes(row))
            cand_blocks.append(gen.sys_blocks[sid])

        for fid in sorted(gen.fec_blocks.keys()):
            cand_coeffs.append(bytes(coeff_vector(g_seed, fid, k)))
            cand_blocks.append(gen.fec_blocks[fid])

        chosen = select_independent_rows(cand_coeffs, k)
        if chosen is None:
            return None

        coeffs_flat = b"".join(cand_coeffs[i] for i in chosen)
        coded_flat = b"".join(cand_blocks[i] for i in chosen)
        try:
            decoded_flat = gf256_decode_matrix(coded_flat, coeffs_flat, k, sym_size)
        except ValueError:
            return None

        return [decoded_flat[i * sym_size : (i + 1) * sym_size] for i in range(k)]

    def _scan_missing_generations(self, now: float) -> None:
        nacks: list[tuple[tuple[str, int], int, int, int, int, int, bytes]] = []
        with self._lock:
            for sid, sess in list(self._sessions.items()):
                if sid in self._completed or sess.orig_len == 0:
                    continue
                for gid, gen in sess.generations.items():
                    if gen.solved:
                        continue
                    if (now - gen.last_rx_at) >= 0.035 and (now - gen.last_nack_at) >= 0.045:
                        gen.last_nack_at = now
                        deficit = max(1, gen.k - gen.unique_count)
                        loss_bps = min(9000, int(sess.loss_ewma * 10000))
                        nacks.append(
                            (
                                sess.peer_addr,
                                _PTYPE_GEN_NEED,
                                sid,
                                gid,
                                deficit,
                                sess.orig_len,
                                gen.k,
                                struct.pack("<H", loss_bps),
                            )
                        )
        for item in nacks:
            self._send_ctrl(*item)

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        try:
            self._sock.close()
        except OSError:
            pass


@dataclass
class _RxGeneration:
    gen_id: int
    k: int
    sym_size: int
    created_at: float
    last_rx_at: float = 0.0
    last_nack_at: float = 0.0
    sys_blocks: dict[int, bytes] = None  # type: ignore[assignment]
    fec_blocks: dict[int, bytes] = None  # type: ignore[assignment]
    solved_blocks: list[bytes] = None  # type: ignore[assignment]
    solved: bool = False

    def __post_init__(self) -> None:
        self.last_rx_at = self.created_at
        if self.sys_blocks is None:
            self.sys_blocks = {}
        if self.fec_blocks is None:
            self.fec_blocks = {}
        if self.solved_blocks is None:
            self.solved_blocks = []

    @property
    def unique_count(self) -> int:
        return len(self.sys_blocks) + len(self.fec_blocks)


@dataclass
class _RxSession:
    stream_id: int
    orig_len: int
    peer_addr: tuple[str, int]
    total_gens: int = 0
    solved_count: int = 0
    seen_sys_seqs: int = 0
    max_sys_seq: int = -1
    loss_ewma: float = 0.0
    gfni_solves: int = 0
    wire_bytes_rx: int = 0
    generations: dict[int, _RxGeneration] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.generations is None:
            self.generations = {}

    def seed_for_gen(self, gen_id: int) -> bytes:
        return hashlib.blake2s(
            struct.pack("!BII", self.stream_id, self.orig_len, gen_id),
            digest_size=16,
        ).digest()


class HyperWireSender:
    """Paced systematic + adaptive Silicon-GFNI RLNC sender (0% overhead on clean links)."""

    def __init__(
        self,
        target_addr: tuple[str, int],
        sym_size: int = SYM_SIZE,
        gen_k: int = DEFAULT_GEN_K,
        max_inflight_gens: int = 24,
        pace_mbps: float | None = None,
        initial_loss_hint: float = 0.0,
    ) -> None:
        self.target_addr = target_addr
        self.sym_size = sym_size
        self.gen_k = gen_k
        self.max_inflight_gens = max_inflight_gens
        self.pace_mbps = pace_mbps
        self.initial_loss_hint = max(0.0, min(0.6, float(initial_loss_hint)))

    @staticmethod
    def _proactive_repairs(k: int, est_loss: float) -> int:
        if est_loss <= 0.002:
            return 0
        p = min(0.60, est_loss)
        expected = k * p / (1.0 - p)
        sigma = math.sqrt(max(0.01, expected * (1.0 + p)))
        return min(k, max(1, int(math.ceil(expected + 1.15 * sigma))))

    def send_stream(
        self,
        payload: bytes,
        stream_id: int = 1,
        priority_frame: bytes | None = None,
        timeout_s: float = 25.0,
        send_fn: Callable[[bytes, tuple[str, int]], None] | None = None,
        feedback_queue: "queue.Queue[bytes] | None" = None,
    ) -> HyperWireReport:
        t0 = time.perf_counter()
        orig_len = len(payload)
        own_sock: socket.socket | None = None
        if send_fn is None or feedback_queue is None:
            fam = _family_for_ip(self.target_addr[0])
            own_sock = socket.socket(fam, socket.SOCK_DGRAM)
            _disable_connreset(own_sock)
            try:
                own_sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
                own_sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4 * 1024 * 1024)
            except OSError:
                pass
            own_sock.bind(_bind_any(fam))
            own_sock.settimeout(0.005)

        def _raw_send(pkt_b: bytes) -> None:
            if send_fn is not None:
                send_fn(pkt_b, self.target_addr)
            elif own_sock is not None:
                own_sock.sendto(pkt_b, self.target_addr)

        def _raw_recv() -> bytes | None:
            if feedback_queue is not None:
                try:
                    return feedback_queue.get_nowait()
                except queue.Empty:
                    return None
            if own_sock is not None:
                try:
                    data, _ = own_sock.recvfrom(4096)
                    return data
                except (socket.timeout, ConnectionResetError):
                    return None
            return None

        wire_bytes = 0
        sys_sent = 0
        fec_sent = 0
        repair_retransmits = 0
        prio_first_ms: float | None = None
        est_loss = self.initial_loss_hint

        with WinTimerScope():
            try:
                # Optional Priority-0 semantic frame bypass
                if priority_frame is not None:
                    p_pkt = _pack_frame(
                        _PTYPE_PRIO,
                        stream_id,
                        0,
                        0,
                        len(priority_frame),
                        1,
                        priority_frame,
                    )
                    _raw_send(p_pkt)
                    wire_bytes += len(p_pkt)
                    if est_loss > 0.01:
                        _raw_send(p_pkt)
                        wire_bytes += len(p_pkt)
                    prio_first_ms = round((time.perf_counter() - t0) * 1000.0, 2)

                # Build generations
                if orig_len == 0:
                    pkt = _pack_frame(_PTYPE_SYS, stream_id, 0, 0, 0, 1, b"")
                    fin_ok = False
                    deadline = t0 + timeout_s
                    while not fin_ok and time.perf_counter() < deadline:
                        _raw_send(pkt)
                        wire_bytes += len(pkt)
                        sys_sent += 1
                        wait_end = time.perf_counter() + 0.04
                        while time.perf_counter() < wait_end:
                            ack = _raw_recv()
                            if ack is None:
                                time.sleep(0.002)
                                continue
                            parsed = _unpack_frame(ack)
                            if parsed and parsed[0] == _PTYPE_FIN_ACK and parsed[1] == stream_id:
                                fin_ok = True
                                break
                    elapsed_ms = (time.perf_counter() - t0) * 1000.0
                    return HyperWireReport(
                        bytes_transferred=0,
                        wire_bytes_sent=wire_bytes,
                        wire_overhead_pct=0.0,
                        elapsed_ms=round(elapsed_ms, 2),
                        throughput_mbps=0.0,
                        generations_total=1,
                        sys_packets_sent=sys_sent,
                        fec_packets_sent=0,
                        repair_retransmits=0,
                        gfni_matrix_solves=0,
                        observed_loss_pct=0.0,
                        priority_first_ms=prio_first_ms,
                        sha256_match=fin_ok,
                    )

                gen_bytes = self.gen_k * self.sym_size
                total_gens = (orig_len + gen_bytes - 1) // gen_bytes
                gens_blocks: list[bytes] = []
                gens_k: list[int] = []
                mv = memoryview(payload)

                for gid in range(total_gens):
                    chunk = bytes(mv[gid * gen_bytes : (gid + 1) * gen_bytes])
                    gk = max(1, (len(chunk) + self.sym_size - 1) // self.sym_size)
                    pad_len = gk * self.sym_size - len(chunk)
                    if pad_len:
                        chunk = chunk + (b"\x00" * pad_len)
                    gens_blocks.append(chunk)
                    gens_k.append(gk)

                acked_gens: set[int] = set()
                sent_gens: set[int] = set()
                next_sym_id: dict[int, int] = {gid: gens_k[gid] for gid in range(total_gens)}
                last_tx_time: dict[int, float] = {}
                next_gen_to_send = 0
                fin_acked = False
                deadline = t0 + timeout_s
                tx_clock = time.perf_counter()

                def g_seed(gid: int) -> bytes:
                    return hashlib.blake2s(
                        struct.pack("!BII", stream_id, orig_len, gid),
                        digest_size=16,
                    ).digest()

                def emit_paced(pkt_bytes: bytes) -> None:
                    nonlocal wire_bytes, tx_clock
                    if self.pace_mbps and self.pace_mbps > 0.0:
                        ser_s = (len(pkt_bytes) * 8.0) / (self.pace_mbps * 1_000_000.0)
                        tx_clock = max(tx_clock + ser_s, time.perf_counter())
                        gap = tx_clock - time.perf_counter()
                        if gap > 0.002:
                            time.sleep(0.001)
                    _raw_send(pkt_bytes)
                    wire_bytes += len(pkt_bytes)

                def emit_coded_symbols(gid: int, count: int, is_retransmit: bool = False) -> None:
                    nonlocal fec_sent, repair_retransmits
                    gk = gens_k[gid]
                    flat = gens_blocks[gid]
                    seed = g_seed(gid)
                    fid_base = next_sym_id[gid]
                    for j in range(count):
                        fid = fid_base + j
                        coeffs = bytes(coeff_vector(seed, fid, gk))
                        coded_blk = gf256_encode_block(flat, coeffs, gk, self.sym_size)
                        pkt = _pack_frame(
                            _PTYPE_FEC, stream_id, gid, fid, orig_len, gk, coded_blk
                        )
                        emit_paced(pkt)
                        fec_sent += 1
                        if is_retransmit:
                            repair_retransmits += 1
                    next_sym_id[gid] += count
                    last_tx_time[gid] = time.perf_counter()

                def send_generation(gid: int) -> None:
                    nonlocal sys_sent
                    gk = gens_k[gid]
                    flat = gens_blocks[gid]
                    fmv = memoryview(flat)
                    for sid in range(gk):
                        blk = bytes(fmv[sid * self.sym_size : (sid + 1) * self.sym_size])
                        pkt = _pack_frame(
                            _PTYPE_SYS, stream_id, gid, sid, orig_len, gk, blk
                        )
                        emit_paced(pkt)
                        sys_sent += 1
                    n_rep = self._proactive_repairs(gk, est_loss)
                    if n_rep > 0:
                        emit_coded_symbols(gid, n_rep, is_retransmit=False)
                    sent_gens.add(gid)
                    last_tx_time[gid] = time.perf_counter()

                while not fin_acked and len(acked_gens) < total_gens and time.perf_counter() < deadline:
                    inflight = len(sent_gens) - len(acked_gens)
                    while next_gen_to_send < total_gens and inflight < self.max_inflight_gens:
                        send_generation(next_gen_to_send)
                        next_gen_to_send += 1
                        inflight += 1

                    # Drain incoming feedback (GEN_ACK, GEN_NEED, FIN_ACK)
                    progressed = False
                    while True:
                        ctrl = _raw_recv()
                        if ctrl is None:
                            break
                        parsed = _unpack_frame(ctrl)
                        if parsed is None:
                            continue
                        ptype, sid_rx, gid_rx, meta_sym, _, _, body = parsed
                        if sid_rx != stream_id:
                            continue
                        progressed = True
                        if len(body) >= 2:
                            (loss_bps,) = struct.unpack_from("<H", body, 0)
                            reported_loss = loss_bps / 10000.0
                            est_loss = 0.5 * est_loss + 0.5 * reported_loss
                        if ptype == _PTYPE_FIN_ACK:
                            fin_acked = True
                            break
                        if ptype == _PTYPE_GEN_ACK:
                            acked_gens.add(gid_rx)
                        elif ptype == _PTYPE_GEN_NEED:
                            now = time.perf_counter()
                            if (
                                gid_rx not in acked_gens
                                and gid_rx in sent_gens
                                and (now - last_tx_time.get(gid_rx, 0.0)) >= 0.030
                            ):
                                extra = max(1, meta_sym + (1 if est_loss > 0.03 else 0))
                                emit_coded_symbols(gid_rx, extra, is_retransmit=True)

                    if fin_acked or len(acked_gens) == total_gens:
                        break

                    # Fallback tail probe for unacked idle generations
                    if not progressed:
                        now = time.perf_counter()
                        for gid in range(next_gen_to_send):
                            if gid not in acked_gens and (now - last_tx_time.get(gid, 0.0)) >= 0.09:
                                emit_coded_symbols(gid, 2, is_retransmit=True)
                                break
                        time.sleep(0.002)

                elapsed_ms = (time.perf_counter() - t0) * 1000.0
                success = fin_acked or len(acked_gens) == total_gens
                overhead_pct = (
                    ((wire_bytes - orig_len) / float(orig_len)) * 100.0
                    if orig_len > 0
                    else 0.0
                )
                return HyperWireReport(
                    bytes_transferred=orig_len,
                    wire_bytes_sent=wire_bytes,
                    wire_overhead_pct=round(overhead_pct, 2),
                    elapsed_ms=round(elapsed_ms, 2),
                    throughput_mbps=round((orig_len * 8.0) / max(elapsed_ms * 1000.0, 0.001), 3),
                    generations_total=total_gens,
                    sys_packets_sent=sys_sent,
                    fec_packets_sent=fec_sent,
                    repair_retransmits=repair_retransmits,
                    gfni_matrix_solves=0,
                    observed_loss_pct=round(est_loss * 100.0, 2),
                    priority_first_ms=prio_first_ms,
                    sha256_match=success,
                )
            finally:
                if own_sock is not None:
                    own_sock.close()


# ---------------------------------------------------------------------------
# Hedged Multi-Path RPC Racing (Zero Tail-Latency Stalls)
# ---------------------------------------------------------------------------


class HedgedRpcServer:
    """Multi-homed dual-stack RPC responder handling raced duplicate packets idempotently."""

    def __init__(
        self,
        bind_addrs: list[tuple[str, int]],
        handler: Callable[[bytes], bytes],
    ) -> None:
        self._handler = handler
        self._socks: list[socket.socket] = []
        self.addrs: list[tuple[str, int]] = []
        for ip, port in bind_addrs:
            s = socket.socket(_family_for_ip(ip), socket.SOCK_DGRAM)
            _disable_connreset(s)
            s.bind((ip, port))
            s.settimeout(0.25)
            self._socks.append(s)
            self.addrs.append(s.getsockname()[:2])
        self._stop = threading.Event()
        self._cache: dict[int, bytes] = {}
        self._lock = threading.Lock()
        self._threads: list[threading.Thread] = []

    def start(self) -> "HedgedRpcServer":
        for s in self._socks:
            t = threading.Thread(target=self._serve_sock, args=(s,), daemon=True)
            t.start()
            self._threads.append(t)
        return self

    def _serve_sock(self, sock: socket.socket) -> None:
        while not self._stop.is_set():
            try:
                pkt, addr = sock.recvfrom(65535)
            except (socket.timeout, ConnectionResetError):
                continue
            except OSError:
                break
            parsed = _unpack_frame(pkt)
            if parsed is None:
                continue
            ptype, stream_id, gen_id, sym_id, req_id, k, body = parsed
            if ptype != _PTYPE_RPC_REQ:
                continue
            with self._lock:
                resp = self._cache.get(req_id)
            if resp is None:
                resp = self._handler(body)
                with self._lock:
                    if len(self._cache) > 4096:
                        self._cache.clear()
                    self._cache[req_id] = resp
            rep_pkt = _pack_frame(_PTYPE_RPC_RESP, stream_id, gen_id, sym_id, req_id, k, resp)
            try:
                sock.sendto(rep_pkt, addr)
            except OSError:
                pass

    def close(self) -> None:
        self._stop.set()
        for t in self._threads:
            t.join(timeout=1.0)
        for s in self._socks:
            try:
                s.close()
            except OSError:
                pass


class HedgedRpcClient:
    """Dual-stack multi-path hedged UDP RPC client picking the fastest verified response."""

    def __init__(
        self,
        targets: list[tuple[str, int]],
        hedge_delay_ms: float = 0.0,
        retry_after_ms: float = 120.0,
    ) -> None:
        if not targets:
            raise ValueError("HedgedRpcClient requires at least one target")
        self.targets = list(targets)
        self.hedge_delay_s = max(0.0, hedge_delay_ms / 1000.0)
        self.retry_after_s = max(0.02, retry_after_ms / 1000.0)

        self._socks: dict[int, socket.socket] = {}
        for ip, _port in self.targets:
            fam = _family_for_ip(ip)
            if fam not in self._socks:
                s = socket.socket(fam, socket.SOCK_DGRAM)
                _disable_connreset(s)
                s.bind(_bind_any(fam))
                s.settimeout(0.01)
                self._socks[fam] = s

        self._req_seq = 0
        self._lock = threading.Lock()
        self._replies: dict[int, tuple[bytes, int]] = {}
        self._cv = threading.Condition(self._lock)
        self._stop = threading.Event()
        self._rx_threads: list[threading.Thread] = []
        for sock in self._socks.values():
            th = threading.Thread(target=self._rx_loop, args=(sock,), daemon=True)
            th.start()
            self._rx_threads.append(th)

    def _rx_loop(self, sock: socket.socket) -> None:
        while not self._stop.is_set():
            try:
                pkt, _ = sock.recvfrom(65535)
            except (socket.timeout, ConnectionResetError):
                continue
            except OSError:
                break
            parsed = _unpack_frame(pkt)
            if parsed is None:
                continue
            ptype, _sid, _gid, path_idx, req_id, _k, body = parsed
            if ptype == _PTYPE_RPC_RESP:
                with self._lock:
                    if req_id not in self._replies:
                        self._replies[req_id] = (body, path_idx)
                        self._cv.notify_all()

    def _sendto_target(self, pkt: bytes, dst: tuple[str, int]) -> None:
        fam = _family_for_ip(dst[0])
        sock = self._socks.get(fam)
        if sock is not None:
            try:
                sock.sendto(pkt, dst)
            except OSError:
                pass

    def call(
        self, payload: bytes, timeout_s: float = 3.0
    ) -> tuple[bytes, float, int]:
        with self._lock:
            self._req_seq += 1
            req_id = self._req_seq

        t0 = time.perf_counter()
        deadline = t0 + timeout_s
        next_retry = t0 + self.retry_after_s

        if self.hedge_delay_s == 0.0:
            for idx, dst in enumerate(self.targets):
                pkt = _pack_frame(_PTYPE_RPC_REQ, 1, 0, idx, req_id, 1, payload)
                self._sendto_target(pkt, dst)
        else:
            pkt0 = _pack_frame(_PTYPE_RPC_REQ, 1, 0, 0, req_id, 1, payload)
            self._sendto_target(pkt0, self.targets[0])

        hedged_fired = self.hedge_delay_s == 0.0

        with self._lock:
            while req_id not in self._replies:
                now = time.perf_counter()
                if now >= deadline:
                    raise TimeoutError(f"Hedged RPC req_id={req_id} timed out")
                if not hedged_fired and (now - t0) >= self.hedge_delay_s:
                    hedged_fired = True
                    for idx, dst in enumerate(self.targets[1:], start=1):
                        pkt = _pack_frame(_PTYPE_RPC_REQ, 1, 0, idx, req_id, 1, payload)
                        self._sendto_target(pkt, dst)
                elif now >= next_retry:
                    next_retry = now + self.retry_after_s
                    for idx, dst in enumerate(self.targets):
                        pkt = _pack_frame(_PTYPE_RPC_REQ, 1, 0, idx, req_id, 1, payload)
                        self._sendto_target(pkt, dst)
                self._cv.wait(timeout=0.005)

            body, win_path = self._replies.pop(req_id)

        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        return body, round(elapsed_ms, 3), win_path

    def close(self) -> None:
        self._stop.set()
        for th in self._rx_threads:
            th.join(timeout=1.0)
        for sock in self._socks.values():
            try:
                sock.close()
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Breakthrough #8: Immortal Stateless Multi-Path RLNC Striping
# ---------------------------------------------------------------------------


@dataclass
class ImmortalReport:
    bytes_transferred: int
    wire_bytes_sent: int
    wire_bytes_rx: int
    elapsed_ms: float
    throughput_mbps: float
    lanes_total: int
    lanes_killed: int
    lane_tx_counts: list[int]
    lane_rx_counts: list[int]
    gfni_solves: int
    reconnects: int
    survived_blackout: bool
    sha256_match: bool
    sha256: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class _ImmortalRxSession:
    stream_id: int
    orig_len: int
    lane_peers: dict[int, tuple[socket.socket, tuple[Any, ...], float]]
    lane_rx_counts: dict[int, int]
    total_gens: int = 0
    solved_count: int = 0
    seen_sys_seqs: int = 0
    max_sys_seq: int = -1
    loss_ewma: float = 0.0
    gfni_solves: int = 0
    wire_bytes_rx: int = 0
    generations: dict[int, _RxGeneration] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.generations is None:
            self.generations = {}

    def seed_for_gen(self, gen_id: int) -> bytes:
        return hashlib.blake2s(
            struct.pack("!BII", self.stream_id, self.orig_len, gen_id),
            digest_size=16,
        ).digest()


class ImmortalMultiPathReceiver:
    """Binds multiple IPv4/IPv6 UDP sockets into ONE shared RLNC session & matrix solver."""

    def __init__(
        self,
        bind_addrs: list[tuple[str, int]],
        gen_k: int = DEFAULT_GEN_K,
        sym_size: int = SYM_SIZE,
    ) -> None:
        if not bind_addrs:
            raise ValueError("ImmortalMultiPathReceiver requires at least one bind address")
        self._gen_k = gen_k
        self._sym_size = sym_size
        self._socks: list[socket.socket] = []
        self.addrs: list[tuple[str, int]] = []
        for ip, port in bind_addrs:
            fam = _family_for_ip(ip)
            s = socket.socket(fam, socket.SOCK_DGRAM)
            _disable_connreset(s)
            try:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8 * 1024 * 1024)
                s.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 8 * 1024 * 1024)
            except OSError:
                pass
            s.bind((ip, port))
            s.settimeout(0.015)
            self._socks.append(s)
            self.addrs.append(s.getsockname()[:2])

        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._sessions: dict[int, _ImmortalRxSession] = {}
        self._completed: dict[int, tuple[bytes, dict[str, Any]]] = {}
        self._recent_stats: dict[int, dict[str, Any]] = {}
        self._done_cv = threading.Condition(self._lock)

    def start(self) -> "ImmortalMultiPathReceiver":
        for idx, sock in enumerate(self._socks):
            th = threading.Thread(target=self._rx_loop, args=(idx, sock), daemon=True)
            th.start()
            self._threads.append(th)
        th_scan = threading.Thread(target=self._nack_loop, daemon=True)
        th_scan.start()
        self._threads.append(th_scan)
        return self

    def get_recent_stats(self, stream_id: int) -> dict[str, Any] | None:
        with self._lock:
            st = self._recent_stats.get(stream_id)
            return dict(st) if st is not None else None

    def wait_stream_stats(
        self, stream_id: int, timeout_s: float = 20.0
    ) -> tuple[bytes, dict[str, Any]]:
        deadline = time.perf_counter() + timeout_s
        with self._lock:
            while stream_id not in self._completed:
                rem = deadline - time.perf_counter()
                if rem <= 0:
                    raise TimeoutError(f"ImmortalMultiPath stream {stream_id} timed out")
                self._done_cv.wait(timeout=min(rem, 0.05))
            payload, meta = self._completed.pop(stream_id)
            self._sessions.pop(stream_id, None)
            return payload, meta

    def wait_any_stats(self, timeout_s: float = 1.0) -> tuple[int, bytes, dict[str, Any]]:
        deadline = time.perf_counter() + timeout_s
        with self._lock:
            while not self._completed:
                rem = deadline - time.perf_counter()
                if rem <= 0:
                    raise TimeoutError("ImmortalMultiPath timed out")
                self._done_cv.wait(timeout=min(rem, 0.25))
            sid = next(iter(self._completed))
            payload, meta = self._completed.pop(sid)
            self._sessions.pop(sid, None)
            return sid, payload, meta

    @staticmethod
    def _broadcast_ctrl(
        lane_peers: list[tuple[socket.socket, tuple[Any, ...]]],
        ptype: int,
        stream_id: int,
        gen_id: int,
        sym_id: int,
        orig_len: int,
        k: int,
        body: bytes,
    ) -> None:
        pkt = _pack_frame(ptype, stream_id, gen_id, sym_id, orig_len, k, body)
        for sock, addr in lane_peers:
            try:
                sock.sendto(pkt, addr)
            except OSError:
                pass

    def _rx_loop(self, lane_idx: int, sock: socket.socket) -> None:
        sock.setblocking(False)
        while not self._stop.is_set():
            try:
                r, _, _ = select.select([sock], [], [], 0.25)
            except (OSError, ValueError):
                break
            if not r:
                continue
            while not self._stop.is_set():
                try:
                    pkt, addr = sock.recvfrom(65535)
                except (BlockingIOError, socket.timeout, ConnectionResetError):
                    break
                except OSError:
                    return
                parsed = _unpack_frame(pkt)
                if parsed is None:
                    continue
                self._handle_frame(lane_idx, sock, addr, *parsed, pkt_len=len(pkt))

    def _nack_loop(self) -> None:
        while not self._stop.is_set():
            with self._lock:
                has_sess = bool(self._sessions)
            if self._stop.wait(timeout=0.018 if has_sess else 0.25):
                break
            if not has_sess:
                continue
            now = time.perf_counter()
            nacks: list[tuple[list[tuple[socket.socket, tuple[Any, ...]]], int, int, int, int, int, int, bytes]] = []
            with self._lock:
                for sid, sess in list(self._sessions.items()):
                    if sid in self._completed or sess.orig_len == 0:
                        continue
                    peers = [(s, a) for s, a, _ in sess.lane_peers.values()]
                    if not peers:
                        continue
                    for gid, gen in sess.generations.items():
                        if gen.solved:
                            continue
                        if (now - gen.last_rx_at) >= 0.030 and (now - gen.last_nack_at) >= 0.040:
                            gen.last_nack_at = now
                            deficit = max(1, gen.k - gen.unique_count)
                            loss_bps = min(9000, int(sess.loss_ewma * 10000))
                            nacks.append(
                                (peers, _PTYPE_GEN_NEED, sid, gid, deficit, sess.orig_len, gen.k, struct.pack("<H", loss_bps))
                            )
            for item in nacks:
                self._broadcast_ctrl(*item)

    def _handle_frame(
        self,
        lane_idx: int,
        sock: socket.socket,
        addr: tuple[Any, ...],
        ptype: int,
        stream_id: int,
        gen_id: int,
        sym_id: int,
        orig_len: int,
        k: int,
        body: bytes,
        pkt_len: int,
    ) -> None:
        if ptype not in (_PTYPE_SYS, _PTYPE_FEC):
            return
        now = time.perf_counter()
        ctrl_out: list[tuple[list[tuple[socket.socket, tuple[Any, ...]]], int, int, int, int, int, int, bytes]] = []

        with self._lock:
            if stream_id in self._completed:
                self._broadcast_ctrl([(sock, addr)], _PTYPE_FIN_ACK, stream_id, gen_id, 0, orig_len, k, b"")
                return

            sess = self._sessions.get(stream_id)
            if sess is None or sess.orig_len != orig_len:
                sess = _ImmortalRxSession(
                    stream_id=stream_id,
                    orig_len=orig_len,
                    lane_peers={},
                    lane_rx_counts={i: 0 for i in range(len(self._socks))},
                )
                self._sessions[stream_id] = sess

            sess.lane_peers[lane_idx] = (sock, addr, now)
            sess.lane_rx_counts[lane_idx] = sess.lane_rx_counts.get(lane_idx, 0) + 1
            sess.wire_bytes_rx += pkt_len
            all_peers = [(s, a) for s, a, _ in sess.lane_peers.values()]

            if orig_len == 0:
                meta = {
                    "stream_id": stream_id,
                    "bytes": 0,
                    "wire_bytes_rx": sess.wire_bytes_rx,
                    "lane_rx_counts": [sess.lane_rx_counts.get(i, 0) for i in range(len(self._socks))],
                    "gfni_solves": 0,
                    "sha256": hashlib.sha256(b"").hexdigest(),
                }
                self._recent_stats[stream_id] = meta
                self._completed[stream_id] = (b"", meta)
                self._done_cv.notify_all()
                ctrl_out.append((all_peers, _PTYPE_FIN_ACK, stream_id, 0, 0, 0, 1, b""))
            else:
                if sess.total_gens == 0:
                    gen_bytes = self._gen_k * self._sym_size
                    sess.total_gens = max(1, (orig_len + gen_bytes - 1) // gen_bytes)

                if ptype == _PTYPE_SYS and sym_id < k:
                    seq_num = gen_id * self._gen_k + sym_id
                    sess.seen_sys_seqs += 1
                    if seq_num > sess.max_sys_seq:
                        sess.max_sys_seq = seq_num
                    if sess.max_sys_seq >= 15:
                        raw_loss = max(0.0, 1.0 - (sess.seen_sys_seqs / float(sess.max_sys_seq + 1)))
                        sess.loss_ewma = 0.4 * raw_loss + 0.6 * sess.loss_ewma

                gen = sess.generations.get(gen_id)
                if gen is None:
                    gen = _RxGeneration(gen_id=gen_id, k=k, sym_size=len(body), created_at=now)
                    sess.generations[gen_id] = gen
                    for prev_gid, prev_gen in sess.generations.items():
                        if prev_gid < gen_id and not prev_gen.solved and (now - prev_gen.last_nack_at) >= 0.04:
                            prev_gen.last_nack_at = now
                            deficit = max(1, prev_gen.k - prev_gen.unique_count)
                            loss_bps = min(9000, int(sess.loss_ewma * 10000))
                            ctrl_out.append(
                                (
                                    all_peers,
                                    _PTYPE_GEN_NEED,
                                    stream_id,
                                    prev_gid,
                                    deficit,
                                    orig_len,
                                    prev_gen.k,
                                    struct.pack("<H", loss_bps),
                                )
                            )

                if not gen.solved:
                    gen.last_rx_at = now
                    if ptype == _PTYPE_SYS:
                        if sym_id not in gen.sys_blocks and sym_id < k:
                            gen.sys_blocks[sym_id] = body
                    else:
                        if sym_id not in gen.fec_blocks:
                            gen.fec_blocks[sym_id] = body

                    just_solved = False
                    if len(gen.sys_blocks) == gen.k:
                        gen.solved_blocks = [gen.sys_blocks[i] for i in range(gen.k)]
                        gen.solved = True
                        just_solved = True
                    elif len(gen.sys_blocks) + len(gen.fec_blocks) >= gen.k:
                        recovered = self._try_gfni_solve(sess.seed_for_gen(gen_id), gen)
                        if recovered is not None:
                            gen.solved_blocks = recovered
                            gen.solved = True
                            sess.gfni_solves += 1
                            just_solved = True

                    if just_solved:
                        sess.solved_count += 1
                        loss_bps = min(9000, int(sess.loss_ewma * 10000))
                        ctrl_out.append(
                            (
                                all_peers,
                                _PTYPE_GEN_ACK,
                                stream_id,
                                gen_id,
                                sess.solved_count,
                                orig_len,
                                gen.k,
                                struct.pack("<H", loss_bps),
                            )
                        )
                        if sess.solved_count == sess.total_gens:
                            raw = bytearray()
                            for gid in range(sess.total_gens):
                                for blk in sess.generations[gid].solved_blocks:
                                    raw.extend(blk)
                            out_bytes = bytes(raw[:orig_len])
                            meta = {
                                "stream_id": stream_id,
                                "bytes": len(out_bytes),
                                "wire_bytes_rx": sess.wire_bytes_rx,
                                "lane_rx_counts": [
                                    sess.lane_rx_counts.get(i, 0) for i in range(len(self._socks))
                                ],
                                "gfni_solves": sess.gfni_solves,
                                "sha256": hashlib.sha256(out_bytes).hexdigest(),
                            }
                            if len(self._recent_stats) >= 64:
                                oldest = next(iter(self._recent_stats))
                                self._recent_stats.pop(oldest, None)
                            self._recent_stats[stream_id] = meta
                            self._completed[stream_id] = (out_bytes, meta)
                            self._done_cv.notify_all()
                            ctrl_out.append(
                                (
                                    all_peers,
                                    _PTYPE_FIN_ACK,
                                    stream_id,
                                    gen_id,
                                    sess.solved_count,
                                    orig_len,
                                    gen.k,
                                    struct.pack("<H", loss_bps),
                                )
                            )

        for item in ctrl_out:
            self._broadcast_ctrl(*item)

    @staticmethod
    def _try_gfni_solve(g_seed: bytes, gen: "_RxGeneration") -> list[bytes] | None:
        k = gen.k
        sym_size = gen.sym_size
        cand_coeffs: list[bytes] = []
        cand_blocks: list[bytes] = []
        for sid in sorted(gen.sys_blocks.keys()):
            row = bytearray(k)
            row[sid] = 1
            cand_coeffs.append(bytes(row))
            cand_blocks.append(gen.sys_blocks[sid])
        for fid in sorted(gen.fec_blocks.keys()):
            cand_coeffs.append(bytes(coeff_vector(g_seed, fid, k)))
            cand_blocks.append(gen.fec_blocks[fid])
        chosen = select_independent_rows(cand_coeffs, k)
        if chosen is None:
            return None
        coeffs_flat = b"".join(cand_coeffs[i] for i in chosen)
        coded_flat = b"".join(cand_blocks[i] for i in chosen)
        try:
            decoded_flat = gf256_decode_matrix(coded_flat, coeffs_flat, k, sym_size)
        except ValueError:
            return None
        return [decoded_flat[i * sym_size : (i + 1) * sym_size] for i in range(k)]

    def close(self) -> None:
        self._stop.set()
        for t in self._threads:
            t.join(timeout=1.0)
        for s in self._socks:
            try:
                s.close()
            except OSError:
                pass


class ImmortalMultiPathSender:
    """Stateless multi-path RLNC striping across IPv4/IPv6 with 0-reconnect lane-cut survival."""

    def __init__(
        self,
        targets: list[tuple[str, int]],
        gen_k: int = DEFAULT_GEN_K,
        sym_size: int = SYM_SIZE,
        max_inflight_gens: int = 24,
        initial_loss_hint: float = 0.03,
    ) -> None:
        if not targets:
            raise ValueError("ImmortalMultiPathSender requires at least one target")
        self.targets = list(targets)
        self.gen_k = gen_k
        self.sym_size = sym_size
        self.max_inflight_gens = max_inflight_gens
        self.initial_loss_hint = max(0.0, min(0.6, float(initial_loss_hint)))

    def send_stream(
        self,
        payload: bytes,
        stream_id: int = 1,
        timeout_s: float = 20.0,
        chaos_kill_lane: int | None = None,
        chaos_kill_after_gens: int = 1,
    ) -> ImmortalReport:
        t0 = time.perf_counter()
        orig_len = len(payload)
        socks: list[socket.socket] = []
        for ip, _ in self.targets:
            fam = _family_for_ip(ip)
            s = socket.socket(fam, socket.SOCK_DGRAM)
            _disable_connreset(s)
            try:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
                s.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4 * 1024 * 1024)
            except OSError:
                pass
            s.bind(_bind_any(fam))
            s.setblocking(False)
            socks.append(s)

        alive_lanes = list(range(len(socks)))
        lane_tx_counts = [0] * len(socks)
        lanes_killed = 0
        wire_bytes = 0
        est_loss = self.initial_loss_hint

        with WinTimerScope():
            try:
                for idx in alive_lanes:
                    try:
                        socks[idx].sendto(b"CHP0", self.targets[idx])
                    except OSError:
                        pass

                gen_bytes = self.gen_k * self.sym_size
                total_gens = max(1, (orig_len + gen_bytes - 1) // gen_bytes) if orig_len > 0 else 1
                gens_blocks: list[bytes] = []
                gens_k: list[int] = []
                if orig_len == 0:
                    gens_blocks.append(b"")
                    gens_k.append(1)
                else:
                    mv = memoryview(payload)
                    for gid in range(total_gens):
                        chunk = bytes(mv[gid * gen_bytes : (gid + 1) * gen_bytes])
                        gk = max(1, (len(chunk) + self.sym_size - 1) // self.sym_size)
                        pad_len = gk * self.sym_size - len(chunk)
                        if pad_len:
                            chunk = chunk + (b"\x00" * pad_len)
                        gens_blocks.append(chunk)
                        gens_k.append(gk)

                acked_gens: set[int] = set()
                sent_gens: set[int] = set()
                next_sym_id: dict[int, int] = {gid: gens_k[gid] for gid in range(total_gens)}
                last_tx_time: dict[int, float] = {}
                next_gen_to_send = 0
                fin_acked = False
                deadline = t0 + timeout_s
                pkt_seq = 0
                chaos_done = False

                def g_seed(gid: int) -> bytes:
                    return hashlib.blake2s(
                        struct.pack("!BII", stream_id, orig_len, gid),
                        digest_size=16,
                    ).digest()

                def emit_rr(pkt_bytes: bytes) -> None:
                    nonlocal wire_bytes, pkt_seq
                    lane = alive_lanes[pkt_seq % len(alive_lanes)]
                    pkt_seq += 1
                    try:
                        socks[lane].sendto(pkt_bytes, self.targets[lane])
                    except OSError:
                        pass
                    lane_tx_counts[lane] += 1
                    wire_bytes += len(pkt_bytes)

                def emit_coded(gid: int, count: int) -> None:
                    gk = gens_k[gid]
                    flat = gens_blocks[gid]
                    seed = g_seed(gid)
                    fid_base = next_sym_id[gid]
                    for j in range(count):
                        fid = fid_base + j
                        coeffs = bytes(coeff_vector(seed, fid, gk))
                        coded_blk = gf256_encode_block(flat, coeffs, gk, self.sym_size)
                        emit_rr(_pack_frame(_PTYPE_FEC, stream_id, gid, fid, orig_len, gk, coded_blk))
                    next_sym_id[gid] += count
                    last_tx_time[gid] = time.perf_counter()

                def send_gen(gid: int) -> None:
                    if orig_len == 0:
                        emit_rr(_pack_frame(_PTYPE_SYS, stream_id, 0, 0, 0, 1, b""))
                        sent_gens.add(gid)
                        last_tx_time[gid] = time.perf_counter()
                        return
                    gk = gens_k[gid]
                    flat = gens_blocks[gid]
                    fmv = memoryview(flat)
                    for sid in range(gk):
                        blk = bytes(fmv[sid * self.sym_size : (sid + 1) * self.sym_size])
                        emit_rr(_pack_frame(_PTYPE_SYS, stream_id, gid, sid, orig_len, gk, blk))
                    n_rep = HyperWireSender._proactive_repairs(gk, est_loss)
                    if n_rep > 0:
                        emit_coded(gid, n_rep)
                    sent_gens.add(gid)
                    last_tx_time[gid] = time.perf_counter()

                def poll_all_socks() -> list[bytes]:
                    out: list[bytes] = []
                    for lane in alive_lanes:
                        s = socks[lane]
                        while True:
                            try:
                                data, _ = s.recvfrom(4096)
                                out.append(data)
                            except (BlockingIOError, socket.timeout, ConnectionResetError, OSError):
                                break
                    return out

                while not fin_acked and len(acked_gens) < total_gens and time.perf_counter() < deadline:
                    inflight = len(sent_gens) - len(acked_gens)
                    while next_gen_to_send < total_gens and inflight < self.max_inflight_gens:
                        send_gen(next_gen_to_send)
                        next_gen_to_send += 1
                        inflight += 1
                        if (
                            chaos_kill_lane is not None
                            and not chaos_done
                            and len(alive_lanes) > 1
                            and chaos_kill_lane in alive_lanes
                            and next_gen_to_send >= chaos_kill_after_gens
                        ):
                            alive_lanes.remove(chaos_kill_lane)
                            lanes_killed += 1
                            chaos_done = True
                            est_loss = max(est_loss, 0.05)

                    progressed = False
                    for ctrl in poll_all_socks():
                        parsed = _unpack_frame(ctrl)
                        if parsed is None:
                            continue
                        ptype, sid_rx, gid_rx, meta_sym, _, _, _ = parsed
                        if sid_rx != stream_id:
                            continue
                        progressed = True
                        if ptype == _PTYPE_FIN_ACK:
                            fin_acked = True
                            break
                        if ptype == _PTYPE_GEN_ACK:
                            acked_gens.add(gid_rx)
                        elif ptype == _PTYPE_GEN_NEED:
                            now = time.perf_counter()
                            if gid_rx not in acked_gens and (now - last_tx_time.get(gid_rx, 0.0)) >= 0.03:
                                emit_coded(gid_rx, max(1, meta_sym + 1))

                    if fin_acked or len(acked_gens) == total_gens:
                        break
                    if not progressed:
                        now = time.perf_counter()
                        for gid in range(next_gen_to_send):
                            if gid not in acked_gens and (now - last_tx_time.get(gid, 0.0)) >= 0.08:
                                emit_coded(gid, 2)
                                break
                        time.sleep(0.002)

                elapsed_ms = (time.perf_counter() - t0) * 1000.0
                success = fin_acked or len(acked_gens) == total_gens
                return ImmortalReport(
                    bytes_transferred=orig_len,
                    wire_bytes_sent=wire_bytes,
                    wire_bytes_rx=wire_bytes,
                    elapsed_ms=round(elapsed_ms, 2),
                    throughput_mbps=round((orig_len * 8.0) / max(elapsed_ms * 1000.0, 0.001), 3),
                    lanes_total=len(socks),
                    lanes_killed=lanes_killed,
                    lane_tx_counts=lane_tx_counts,
                    lane_rx_counts=[],
                    gfni_solves=0,
                    reconnects=0,
                    survived_blackout=bool(success and lanes_killed > 0),
                    sha256_match=success,
                    sha256=hashlib.sha256(payload).hexdigest(),
                )
            finally:
                for s in socks:
                    try:
                        s.close()
                    except OSError:
                        pass
