"""Realistic network impairment proxy & faithful RFC TCP-CUBIC reference over UDP."""

from __future__ import annotations

import ctypes
import heapq
import os
import random
import socket
import struct
import threading
import time
from dataclasses import dataclass, field
from typing import Any


class WinTimerScope:
    """Request 1 ms Windows multimedia timer resolution while active."""

    _lock = threading.Lock()
    _refcount = 0

    def __enter__(self) -> "WinTimerScope":
        if os.name == "nt":
            with self._lock:
                if WinTimerScope._refcount == 0:
                    try:
                        ctypes.windll.winmm.timeBeginPeriod(1)
                    except Exception:
                        pass
                WinTimerScope._refcount += 1
        return self

    def __exit__(self, *_exc: object) -> None:
        if os.name == "nt":
            with self._lock:
                WinTimerScope._refcount = max(0, WinTimerScope._refcount - 1)
                if WinTimerScope._refcount == 0:
                    try:
                        ctypes.windll.winmm.timeEndPeriod(1)
                    except Exception:
                        pass


@dataclass
class BridgeStats:
    packets_in_a: int = 0
    packets_in_b: int = 0
    packets_forwarded: int = 0
    packets_dropped: int = 0
    bytes_forwarded: int = 0


class ImpairedUdpBridge:
    """Symmetric UDP packet impairment proxy modeling WAN bandwidth, RTT, jitter, and loss."""

    def __init__(
        self,
        target_b: tuple[str, int],
        bandwidth_mbps: float = 100.0,
        one_way_delay_ms: float = 25.0,
        jitter_ms: float = 0.0,
        loss_rate: float = 0.0,
        burst_loss_prob: float = 0.0,
        seed: int = 20261125,
    ) -> None:
        self.target_b = target_b
        self.bandwidth_mbps = float(bandwidth_mbps)
        self.one_way_delay_s = max(0.0, float(one_way_delay_ms)) / 1000.0
        self.jitter_s = max(0.0, float(jitter_ms)) / 1000.0
        self.loss_rate = max(0.0, min(0.95, float(loss_rate)))
        self.burst_loss_prob = max(0.0, min(0.95, float(burst_loss_prob)))
        self._rng = random.Random(seed)
        self._in_burst_a = False
        self._in_burst_b = False

        self._sock_a = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock_b = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        for s in (self._sock_a, self._sock_b):
            try:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8 * 1024 * 1024)
                s.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 8 * 1024 * 1024)
            except OSError:
                pass
            s.bind(("127.0.0.1", 0))
            s.settimeout(0.05)

        self.a_addr: tuple[str, int] = self._sock_a.getsockname()
        self.b_addr: tuple[str, int] = self._sock_b.getsockname()

        self._client_addr: tuple[str, int] | None = None
        self._stop = threading.Event()
        self._queue: list[tuple[float, int, str, bytes]] = []
        self._q_lock = threading.Lock()
        self._q_cv = threading.Condition(self._q_lock)
        self._seq = 0
        self._tx_busy_until_a = 0.0
        self._tx_busy_until_b = 0.0
        self._stats = BridgeStats()
        self._timer_scope = WinTimerScope()
        self._threads: list[threading.Thread] = []

    @property
    def stats(self) -> BridgeStats:
        return self._stats

    def start(self) -> "ImpairedUdpBridge":
        self._timer_scope.__enter__()
        self._threads = [
            threading.Thread(target=self._rx_loop, args=("A", self._sock_a), daemon=True),
            threading.Thread(target=self._rx_loop, args=("B", self._sock_b), daemon=True),
            threading.Thread(target=self._deliver_loop, daemon=True),
        ]
        for t in self._threads:
            t.start()
        return self

    def reset_seed(self, seed: int) -> None:
        with self._q_lock:
            self._rng = random.Random(seed)
            self._in_burst_a = False
            self._in_burst_b = False
            self._queue.clear()
            self._tx_busy_until_a = 0.0
            self._tx_busy_until_b = 0.0
            self._stats = BridgeStats()

    def _should_drop(self, direction: str) -> bool:
        if self.loss_rate <= 0.0 and self.burst_loss_prob <= 0.0:
            return False
        if direction == "A2B":
            if self._in_burst_a:
                if self._rng.random() < max(self.burst_loss_prob, 0.5):
                    return True
                self._in_burst_a = False
            if self._rng.random() < self.loss_rate:
                if self.burst_loss_prob > 0.0 and self._rng.random() < self.burst_loss_prob:
                    self._in_burst_a = True
                return True
        else:
            if self._in_burst_b:
                if self._rng.random() < max(self.burst_loss_prob, 0.5):
                    return True
                self._in_burst_b = False
            if self._rng.random() < self.loss_rate:
                if self.burst_loss_prob > 0.0 and self._rng.random() < self.burst_loss_prob:
                    self._in_burst_b = True
                return True
        return False

    def _rx_loop(self, side: str, sock: socket.socket) -> None:
        while not self._stop.is_set():
            try:
                data, addr = sock.recvfrom(65535)
            except (socket.timeout, ConnectionResetError):
                continue
            except OSError:
                break

            now = time.perf_counter()
            if side == "A":
                self._client_addr = addr
                direction = "A2B"
                self._stats.packets_in_a += 1
            else:
                direction = "B2A"
                self._stats.packets_in_b += 1

            ser_s = (
                (len(data) * 8.0) / (self.bandwidth_mbps * 1_000_000.0)
                if self.bandwidth_mbps > 0.0
                else 0.0
            )
            jitter = self._rng.uniform(0.0, self.jitter_s) if self.jitter_s > 0.0 else 0.0

            with self._q_lock:
                if direction == "A2B":
                    tx_end = max(self._tx_busy_until_a, now) + ser_s
                    self._tx_busy_until_a = tx_end
                else:
                    tx_end = max(self._tx_busy_until_b, now) + ser_s
                    self._tx_busy_until_b = tx_end

                if self._should_drop(direction):
                    self._stats.packets_dropped += 1
                    continue

                deliver_at = tx_end + self.one_way_delay_s + jitter
                self._seq += 1
                heapq.heappush(self._queue, (deliver_at, self._seq, direction, data))
                self._q_cv.notify()

    def _deliver_loop(self) -> None:
        while not self._stop.is_set():
            due: list[tuple[str, bytes]] = []
            wait_s = 0.02
            with self._q_lock:
                while not self._stop.is_set():
                    now = time.perf_counter()
                    while self._queue and self._queue[0][0] <= now + 0.00025:
                        _, _, direction, data = heapq.heappop(self._queue)
                        due.append((direction, data))
                    if due:
                        break
                    if self._queue:
                        wait_s = max(0.0005, self._queue[0][0] - now)
                        self._q_cv.wait(timeout=min(wait_s, 0.02))
                    else:
                        self._q_cv.wait(timeout=0.02)

            for direction, data in due:
                try:
                    if direction == "A2B":
                        self._sock_b.sendto(data, self.target_b)
                    elif self._client_addr is not None:
                        self._sock_a.sendto(data, self._client_addr)
                    self._stats.packets_forwarded += 1
                    self._stats.bytes_forwarded += len(data)
                except OSError:
                    pass

    def close(self) -> None:
        self._stop.set()
        with self._q_lock:
            self._q_cv.notify_all()
        for t in self._threads:
            t.join(timeout=1.0)
        for s in (self._sock_a, self._sock_b):
            try:
                s.close()
            except OSError:
                pass
        self._timer_scope.__exit__(None, None, None)


# ---------------------------------------------------------------------------
# Faithful RFC TCP-CUBIC-over-UDP Reference (for honest WAN comparisons)
# ---------------------------------------------------------------------------

_TCP_DATA = 1
_TCP_FIN = 2
_TCP_ACK = 3
_TCP_HDR = struct.Struct("!BBIIHH")  # type, flags, seq, ack_or_len, wnd, s_mask


@dataclass
class TcpCubicReport:
    bytes_transferred: int
    elapsed_ms: float
    throughput_mbps: float
    wire_bytes: int
    retransmits: int
    timeouts: int
    congestion_events: int
    min_cwnd_segs: int
    max_cwnd_segs: int
    sha256_match: bool


def transfer_tcp_cubic_over_udp(
    payload: bytes,
    bridge: ImpairedUdpBridge,
    server_sock: socket.socket,
    mss: int = 1360,
    timeout_s: float = 25.0,
) -> tuple[bytes, TcpCubicReport]:
    """Run an honest RFC-faithful IW10/DupACK/CUBIC ARQ stream across `bridge`."""
    total_len = len(payload)
    total_segs = max(1, (total_len + mss - 1) // mss)

    client_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        client_sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
        client_sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4 * 1024 * 1024)
    except OSError:
        pass
    client_sock.bind(("127.0.0.1", 0))
    client_sock.settimeout(0.01)

    rx_segments: dict[int, bytes] = {}
    rx_done = threading.Event()
    rx_stop = threading.Event()
    expected_total_bytes = -1
    rx_base = 0
    peer_for_ack: list[tuple[str, int] | None] = [None]

    def server_loop() -> None:
        nonlocal expected_total_bytes, rx_base
        server_sock.settimeout(0.02)
        while not rx_stop.is_set():
            try:
                pkt, addr = server_sock.recvfrom(65535)
            except (socket.timeout, ConnectionResetError):
                continue
            except OSError:
                break
            if len(pkt) < _TCP_HDR.size:
                continue
            ptype, _flags, seq, meta_len, _wnd, _ = _TCP_HDR.unpack_from(pkt, 0)
            body = pkt[_TCP_HDR.size :]
            peer_for_ack[0] = addr
            if ptype == _TCP_DATA:
                if seq not in rx_segments:
                    rx_segments[seq] = body
                while rx_base in rx_segments:
                    rx_base += 1
            elif ptype == _TCP_FIN:
                expected_total_bytes = meta_len
                if seq not in rx_segments:
                    rx_segments[seq] = body
                while rx_base in rx_segments:
                    rx_base += 1

            # Build 16-bit SACK bitmap for blocks [rx_base+1 .. rx_base+16]
            sack_mask = 0
            for bit in range(16):
                if (rx_base + 1 + bit) in rx_segments:
                    sack_mask |= 1 << bit
            ack_pkt = _TCP_HDR.pack(_TCP_ACK, 0, rx_base, seq, 256, sack_mask)
            try:
                server_sock.sendto(ack_pkt, addr)
            except OSError:
                pass
            if expected_total_bytes >= 0 and rx_base >= total_segs:
                rx_done.set()

    srv_thread = threading.Thread(target=server_loop, daemon=True)
    srv_thread.start()

    t0 = time.perf_counter()
    cwnd = 10.0  # RFC 6928 IW10
    ssthresh = 128.0
    send_base = 0
    next_seq = 0
    dup_acks = 0
    last_cum_ack = 0
    sent_times: dict[int, float] = {}
    sacked: set[int] = set()
    wire_bytes = 0
    retransmits = 0
    timeouts = 0
    cong_events = 0
    min_cwnd = int(cwnd)
    max_cwnd = int(cwnd)
    rto = max(0.08, bridge.one_way_delay_s * 4.0 + 0.04)
    in_recovery_until = 0
    cubic_epoch_start = 0.0
    w_max = 64.0

    def send_seg(seq_idx: int) -> None:
        nonlocal wire_bytes
        chunk = payload[seq_idx * mss : (seq_idx + 1) * mss]
        is_last = seq_idx == total_segs - 1
        ptype = _TCP_FIN if is_last else _TCP_DATA
        pkt = _TCP_HDR.pack(ptype, 0, seq_idx, total_len if is_last else len(chunk), 0, 0) + chunk
        client_sock.sendto(pkt, bridge.a_addr)
        wire_bytes += len(pkt)
        sent_times[seq_idx] = time.perf_counter()

    try:
        deadline = t0 + timeout_s
        while send_base < total_segs and time.perf_counter() < deadline:
            # Transmit within cwnd
            while next_seq < total_segs and (next_seq - send_base) < int(max(1.0, cwnd)):
                send_seg(next_seq)
                next_seq += 1

            # Poll incoming ACKs
            got_ack = False
            while True:
                try:
                    ack_pkt, _ = client_sock.recvfrom(4096)
                except (socket.timeout, ConnectionResetError):
                    break
                if len(ack_pkt) < _TCP_HDR.size:
                    continue
                ptype, _, cum_ack, acked_seq, _, sack_mask = _TCP_HDR.unpack_from(ack_pkt, 0)
                if ptype != _TCP_ACK:
                    continue
                got_ack = True

                for bit in range(16):
                    if sack_mask & (1 << bit):
                        sacked.add(cum_ack + 1 + bit)

                if cum_ack > send_base:
                    newly = cum_ack - send_base
                    send_base = cum_ack
                    dup_acks = 0
                    # CUBIC / AIMD growth
                    if cwnd < ssthresh:
                        cwnd += newly
                    else:
                        if cubic_epoch_start == 0.0:
                            cubic_epoch_start = time.perf_counter()
                        t_el = time.perf_counter() - cubic_epoch_start
                        # RFC 8312 W_cubic(t) = C*(t - K)^3 + W_max (C=0.4)
                        k_val = ((w_max * 0.3) / 0.4) ** (1.0 / 3.0)
                        w_cubic = 0.4 * ((t_el - k_val) ** 3) + w_max
                        cwnd = max(cwnd + newly / max(1.0, cwnd), w_cubic)
                    cwnd = min(cwnd, 256.0)
                    last_cum_ack = cum_ack
                elif cum_ack == last_cum_ack and send_base < total_segs:
                    dup_acks += 1
                    if dup_acks == 3 and send_base >= in_recovery_until:
                        # Triple DupACK -> Fast Retransmit + CUBIC beta=0.7 reduction
                        cong_events += 1
                        w_max = max(cwnd, 4.0)
                        cwnd = max(2.0, cwnd * 0.7)
                        ssthresh = cwnd
                        cubic_epoch_start = time.perf_counter()
                        in_recovery_until = next_seq
                        send_seg(send_base)
                        retransmits += 1

                min_cwnd = min(min_cwnd, int(cwnd))
                max_cwnd = max(max_cwnd, int(cwnd))

            # Check RTO on base packet
            if send_base < total_segs and send_base in sent_times:
                if (time.perf_counter() - sent_times[send_base]) > rto:
                    timeouts += 1
                    cong_events += 1
                    w_max = max(cwnd, 4.0)
                    ssthresh = max(2.0, cwnd * 0.7)
                    cwnd = max(1.0, cwnd * 0.5)  # RTO halves/resets window
                    cubic_epoch_start = time.perf_counter()
                    min_cwnd = min(min_cwnd, int(cwnd))
                    send_seg(send_base)
                    retransmits += 1

            if not got_ack:
                time.sleep(0.001)

        rx_done.wait(timeout=1.5)
    finally:
        rx_stop.set()
        srv_thread.join(timeout=1.0)
        client_sock.close()

    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    out_bytes = b"".join(rx_segments.get(i, b"") for i in range(total_segs))[:total_len]
    import hashlib

    ok = len(out_bytes) == total_len and hashlib.sha256(out_bytes).hexdigest() == hashlib.sha256(payload).hexdigest()
    return out_bytes, TcpCubicReport(
        bytes_transferred=len(out_bytes),
        elapsed_ms=round(elapsed_ms, 2),
        throughput_mbps=round((len(out_bytes) * 8.0) / max(elapsed_ms * 1000.0, 0.001), 3),
        wire_bytes=wire_bytes,
        retransmits=retransmits,
        timeouts=timeouts,
        congestion_events=cong_events,
        min_cwnd_segs=min_cwnd,
        max_cwnd_segs=max_cwnd,
        sha256_match=ok,
    )
