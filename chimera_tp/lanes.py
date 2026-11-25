"""The 8 alien CHIMERA-TP transport lanes mapped to local Windows network interfaces."""

from __future__ import annotations

import os
import random
import select
import socket
import struct
import threading
import time
import zlib
from dataclasses import dataclass, field
from typing import Any, Callable

from .gf256 import chaotic_keystream, decode_lehmer, encode_lehmer, xor_bytes
from .probe import EnvironmentProfile, _disable_udp_connreset, _icmp_checksum

DropletCallback = Callable[[str, bytes, float], None]
JumboCallback = Callable[[int, bytes, float], None]


@dataclass
class FaultProfile:
    """Adversarial fault-injection controls for Chaos Survival mode."""

    kill_lanes: set[str] = field(default_factory=set)
    packet_drop_rate: float = 0.0
    corrupt_lan_noise: bool = False
    jumbo_drop_rate: float = 0.0


@dataclass
class LaneStats:
    """Live telemetry counters for a single transport lane."""

    lane_id: str
    packets_sent: int = 0
    packets_recv: int = 0
    wire_payload_bytes: int = 0
    wire_total_bytes_est: int = 0
    droplets_sent: int = 0
    droplets_recv: int = 0
    fault_drops_injected: int = 0
    reconstruct_errors: int = 0
    fec_recoveries: int = 0
    total_tx_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        avg_tx = (self.total_tx_ms / self.droplets_sent) if self.droplets_sent else 0.0
        return {
            "lane_id": self.lane_id,
            "packets_sent": self.packets_sent,
            "packets_recv": self.packets_recv,
            "wire_payload_bytes": self.wire_payload_bytes,
            "wire_total_bytes_est": self.wire_total_bytes_est,
            "droplets_sent": self.droplets_sent,
            "droplets_recv": self.droplets_recv,
            "fault_drops_injected": self.fault_drops_injected,
            "reconstruct_errors": self.reconstruct_errors,
            "fec_recoveries": self.fec_recoveries,
            "total_tx_ms": round(self.total_tx_ms, 3),
            "avg_tx_ms": round(avg_tx, 3),
        }


class AlienLane:
    """Base interface for all CHIMERA-TP transport lanes."""

    lane_id: str = "BASE"

    def __init__(
        self,
        ip: str,
        droplet_size: int = 20,
        session_seed: bytes = b"chimera",
        on_droplet: DropletCallback | None = None,
    ) -> None:
        self.ip = ip
        self.droplet_size = droplet_size
        self.session_seed = session_seed
        self.on_droplet = on_droplet
        self.stats = LaneStats(lane_id=self.lane_id)
        self._stop_event = threading.Event()
        self._rx_socks: list[socket.socket] = []
        self._rx_thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._rng = random.Random()

    def start_receiver(self) -> dict[str, Any]:
        raise NotImplementedError

    def send_droplet(
        self,
        endpoint: dict[str, Any],
        droplet: bytes,
        frame_tag: int,
        fault: FaultProfile | None = None,
    ) -> None:
        raise NotImplementedError

    def _start_rx_thread(self) -> None:
        self._stop_event.clear()
        self._rx_thread = threading.Thread(
            target=self._rx_loop, name=f"rx-{self.lane_id}", daemon=True
        )
        self._rx_thread.start()

    def _rx_loop(self) -> None:
        while not self._stop_event.is_set():
            if not self._rx_socks:
                time.sleep(0.02)
                continue
            try:
                readable, _, _ = select.select(self._rx_socks, [], [], 0.02)
            except (OSError, ValueError):
                break
            for sock in readable:
                if self._stop_event.is_set():
                    break
                try:
                    self._handle_socket_ready(sock)
                except (ConnectionResetError, BlockingIOError, OSError):
                    continue
                except Exception:
                    self.stats.reconstruct_errors += 1
                    continue

    def _clear_assembly_state(self) -> None:
        """Clear any partial frame assembly state (called under self._lock)."""

    def _drain_rx_socks(self) -> None:
        """Drain stale unread packets queued in non-blocking RX sockets."""
        for sock in self._rx_socks:
            while True:
                try:
                    sock.recvfrom(65535)
                except (BlockingIOError, ConnectionResetError, OSError):
                    break

    def reset_state(self) -> None:
        """Reset assembly buffers and drain stale wire packets between sessions."""
        with self._lock:
            self._clear_assembly_state()
            self._drain_rx_socks()

    def _handle_socket_ready(self, sock: socket.socket) -> None:
        raise NotImplementedError

    def _emit_droplet(self, droplet: bytes, rx_ts: float) -> None:
        self.stats.droplets_recv += 1
        if self.on_droplet is not None:
            self.on_droplet(self.lane_id, droplet, rx_ts)

    def _pick_fault_drop_subpacket(
        self, fault: FaultProfile | None, subpacket_count: int
    ) -> int | None:
        if fault and fault.packet_drop_rate > 0.0:
            if self._rng.random() < fault.packet_drop_rate:
                self.stats.fault_drops_injected += 1
                return self._rng.randrange(max(1, subpacket_count))
        return None

    def close(self) -> None:
        self._stop_event.set()
        if self._rx_thread and self._rx_thread.is_alive():
            self._rx_thread.join(timeout=0.5)
        for s in self._rx_socks:
            try:
                s.close()
            except OSError:
                pass
        self._rx_socks.clear()


def _make_udp_rx(
    family: int, ip: str, port: int = 0, rcvbuf: int = 512 * 1024
) -> socket.socket:
    s = socket.socket(family, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    _disable_udp_connreset(s)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, rcvbuf)
    except OSError:
        pass
    s.bind((ip, port))
    s.setblocking(False)
    return s


# ---------------------------------------------------------------------------
# 1. GHOST_127: 0-byte UDP Source-IP Ghost Smuggling (127.A.B.C)
# ---------------------------------------------------------------------------
class Ghost127Lane(AlienLane):
    """Encodes 2 data bytes + 4-bit tag into 127.A.B.C source IP with 0-byte UDP payload."""

    lane_id = "GHOST_127"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._pair_count = (self.droplet_size + 1) // 2
        if self._pair_count > 16:
            raise ValueError("Ghost127Lane supports up to 32-byte droplets")
        self._sock_to_pair: dict[socket.socket, int] = {}
        self._slots: dict[int, tuple[float, dict[int, tuple[int, int]]]] = {}

    def start_receiver(self) -> dict[str, Any]:
        ports: list[int] = []
        for idx in range(self._pair_count):
            s = _make_udp_rx(socket.AF_INET, "127.0.0.1", 0)
            self._rx_socks.append(s)
            self._sock_to_pair[s] = idx
            ports.append(s.getsockname()[1])
        self._start_rx_thread()
        return {"ip": "127.0.0.1", "ports": ports, "pair_count": self._pair_count}

    def send_droplet(
        self,
        endpoint: dict[str, Any],
        droplet: bytes,
        frame_tag: int,
        fault: FaultProfile | None = None,
    ) -> None:
        t0 = time.perf_counter()
        ports = endpoint["ports"]
        padded = droplet + (b"\x00" if len(droplet) % 2 else b"")
        drop_idx = self._pick_fault_drop_subpacket(fault, self._pair_count)
        tag4 = frame_tag & 0x0F
        for p in range(self._pair_count):
            if drop_idx == p:
                continue
            b0 = padded[2 * p]
            b1 = padded[2 * p + 1]
            val20 = (tag4 << 16) | (b0 << 8) | b1
            o1 = 1 + ((val20 >> 13) & 0x7F)
            o2 = 1 + ((val20 >> 6) & 0x7F)
            o3 = 1 + (val20 & 0x3F)
            ghost_ip = f"127.{o1}.{o2}.{o3}"
            tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                tx.bind((ghost_ip, 0))
                tx.sendto(b"", (endpoint["ip"], ports[p]))
                self.stats.packets_sent += 1
                # Explicitly 0 wire payload bytes!
                self.stats.wire_total_bytes_est += 28
            finally:
                tx.close()
        self.stats.droplets_sent += 1
        self.stats.total_tx_ms += (time.perf_counter() - t0) * 1000.0

    def _handle_socket_ready(self, sock: socket.socket) -> None:
        data, addr = sock.recvfrom(64)
        rx_ts = time.perf_counter()
        if len(data) != 0 or not addr[0].startswith("127."):
            return
        self.stats.packets_recv += 1
        pair_idx = self._sock_to_pair[sock]
        parts = addr[0].split(".")
        if len(parts) != 4:
            return
        o1, o2, o3 = int(parts[1]) - 1, int(parts[2]) - 1, int(parts[3]) - 1
        if not (0 <= o1 < 128 and 0 <= o2 < 128 and 0 <= o3 < 64):
            return
        val20 = (o1 << 13) | (o2 << 6) | o3
        tag4 = (val20 >> 16) & 0x0F
        b0 = (val20 >> 8) & 0xFF
        b1 = val20 & 0xFF

        emit_buf: bytes | None = None
        with self._lock:
            now = time.monotonic()
            stale = [k for k, (ts, _) in self._slots.items() if now - ts > 0.15]
            for k in stale:
                del self._slots[k]
            evict = (tag4 + 8) & 0x0F
            self._slots.pop(evict, None)

            _, slot = self._slots.setdefault(tag4, (now, {}))
            self._slots[tag4] = (now, slot)
            slot[pair_idx] = (b0, b1)
            if len(slot) == self._pair_count:
                buf = bytearray()
                for p in range(self._pair_count):
                    p0, p1 = slot[p]
                    buf.append(p0)
                    buf.append(p1)
                del self._slots[tag4]
                emit_buf = bytes(buf[: self.droplet_size])
        if emit_buf is not None:
            self._emit_droplet(emit_buf, rx_ts)

    def _clear_assembly_state(self) -> None:
        self._slots.clear()


# ---------------------------------------------------------------------------
# 2. LAN_LENGTH: Packet-Length Modulated Random-Noise UDP
# ---------------------------------------------------------------------------
class LanLengthNoiseLane(AlienLane):
    """Encodes each byte strictly in UDP packet length (64..1343B of pure os.urandom noise)."""

    lane_id = "LAN_LENGTH"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._sock_to_idx: dict[socket.socket, int] = {}
        self._slots: dict[int, tuple[float, dict[int, int]]] = {}
        self._tx_sock: socket.socket | None = None

    def start_receiver(self) -> dict[str, Any]:
        ports: list[int] = []
        for idx in range(self.droplet_size):
            s = _make_udp_rx(socket.AF_INET, self.ip, 0)
            self._rx_socks.append(s)
            self._sock_to_idx[s] = idx
            ports.append(s.getsockname()[1])
        self._start_rx_thread()
        return {"ip": self.ip, "ports": ports}

    def _get_tx_sock(self) -> socket.socket:
        if self._tx_sock is None:
            self._tx_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._tx_sock.bind((self.ip, 0))
        return self._tx_sock

    def send_droplet(
        self,
        endpoint: dict[str, Any],
        droplet: bytes,
        frame_tag: int,
        fault: FaultProfile | None = None,
    ) -> None:
        t0 = time.perf_counter()
        tx = self._get_tx_sock()
        ports = endpoint["ports"]
        tag_mod = frame_tag % 5
        drop_idx = self._pick_fault_drop_subpacket(fault, len(droplet))
        corrupt = bool(fault and fault.corrupt_lan_noise)
        for idx, b in enumerate(droplet):
            if drop_idx == idx:
                continue
            target_len = 64 + (tag_mod << 8) + b
            noise = os.urandom(target_len)
            if corrupt:
                noise = xor_bytes(noise, b"\xFF" * target_len)
            tx.sendto(noise, (endpoint["ip"], ports[idx]))
            self.stats.packets_sent += 1
            self.stats.wire_payload_bytes += target_len
            self.stats.wire_total_bytes_est += target_len + 28
        self.stats.droplets_sent += 1
        self.stats.total_tx_ms += (time.perf_counter() - t0) * 1000.0

    def _handle_socket_ready(self, sock: socket.socket) -> None:
        data, _ = sock.recvfrom(2048)
        rx_ts = time.perf_counter()
        self.stats.packets_recv += 1
        idx = self._sock_to_idx[sock]
        offset = len(data) - 64
        if offset < 0:
            return
        tag_mod = offset >> 8
        b = offset & 0xFF
        if not (0 <= tag_mod < 5):
            return

        emit_buf: bytes | None = None
        with self._lock:
            now = time.monotonic()
            stale = [k for k, (ts, _) in self._slots.items() if now - ts > 0.15]
            for k in stale:
                del self._slots[k]
            evict = (tag_mod + 3) % 5
            self._slots.pop(evict, None)

            _, slot = self._slots.setdefault(tag_mod, (now, {}))
            self._slots[tag_mod] = (now, slot)
            slot[idx] = b
            if len(slot) == self.droplet_size:
                emit_buf = bytes(slot[i] for i in range(self.droplet_size))
                del self._slots[tag_mod]
        if emit_buf is not None:
            self._emit_droplet(emit_buf, rx_ts)

    def _clear_assembly_state(self) -> None:
        self._slots.clear()

    def close(self) -> None:
        super().close()
        if self._tx_sock is not None:
            try:
                self._tx_sock.close()
            except OSError:
                pass
            self._tx_sock = None


# ---------------------------------------------------------------------------
# 3. TS_V4_1280: Tailscale IPv4 Strict <=1200B MTU-Clamped Whitened Fountain
# ---------------------------------------------------------------------------
class TailscaleV4FountainLane(AlienLane):
    """Transmits whitened droplets strictly clamped well below Tailscale's 1280B MTU."""

    lane_id = "TS_V4_1280"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._port = 0
        self._tx_sock: socket.socket | None = None

    def start_receiver(self) -> dict[str, Any]:
        s = _make_udp_rx(socket.AF_INET, self.ip, 0)
        self._rx_socks.append(s)
        self._port = s.getsockname()[1]
        self._start_rx_thread()
        return {"ip": self.ip, "port": self._port}

    def send_droplet(
        self,
        endpoint: dict[str, Any],
        droplet: bytes,
        frame_tag: int,
        fault: FaultProfile | None = None,
    ) -> None:
        t0 = time.perf_counter()
        if self._tx_sock is None:
            self._tx_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._tx_sock.bind((self.ip, 0))
        if self._pick_fault_drop_subpacket(fault, 1) is None:
            mask = chaotic_keystream(
                self.session_seed + struct.pack("!4sI", b"TSV4", frame_tag),
                len(droplet),
            )
            frame = b"TS" + struct.pack("!IH", frame_tag, len(droplet)) + xor_bytes(droplet, mask)
            assert len(frame) <= 1200
            self._tx_sock.sendto(frame, (endpoint["ip"], endpoint["port"]))
            self.stats.packets_sent += 1
            self.stats.wire_payload_bytes += len(frame)
            self.stats.wire_total_bytes_est += len(frame) + 28
        self.stats.droplets_sent += 1
        self.stats.total_tx_ms += (time.perf_counter() - t0) * 1000.0

    def _handle_socket_ready(self, sock: socket.socket) -> None:
        data, _ = sock.recvfrom(1500)
        rx_ts = time.perf_counter()
        self.stats.packets_recv += 1
        if len(data) < 8 or data[:2] != b"TS":
            return
        ftag, dlen = struct.unpack("!IH", data[2:8])
        if dlen != self.droplet_size or len(data) != 8 + dlen:
            self.stats.reconstruct_errors += 1
            return
        mask = chaotic_keystream(
            self.session_seed + struct.pack("!4sI", b"TSV4", ftag),
            dlen,
        )
        self._emit_droplet(xor_bytes(data[8:], mask), rx_ts)

    def close(self) -> None:
        super().close()
        if self._tx_sock is not None:
            try:
                self._tx_sock.close()
            except OSError:
                pass
            self._tx_sock = None


# ---------------------------------------------------------------------------
# 4. TS_V6_CHORD: Tailscale ULA IPv6 16-Port Bitmask Chord + Barline
# ---------------------------------------------------------------------------
class TailscaleV6ChordLane(AlienLane):
    """Strikes 16 IPv6 note ports simultaneously + barline port; 0 data bits in payload."""

    lane_id = "TS_V6_CHORD"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._word_count = (self.droplet_size + 1) // 2
        self._note_map: dict[socket.socket, int] = {}
        self._barline_sock: socket.socket | None = None
        self._chords: dict[tuple[int, int], dict[str, Any]] = {}
        self._words: dict[int, tuple[float, dict[int, int]]] = {}
        self._tx_sock: socket.socket | None = None

    def start_receiver(self) -> dict[str, Any]:
        note_ports: list[int] = []
        for bit in range(16):
            s = _make_udp_rx(socket.AF_INET6, self.ip, 0)
            self._rx_socks.append(s)
            self._note_map[s] = bit
            note_ports.append(s.getsockname()[1])
        bs = _make_udp_rx(socket.AF_INET6, self.ip, 0)
        self._rx_socks.append(bs)
        self._barline_sock = bs
        barline_port = bs.getsockname()[1]
        self._start_rx_thread()
        return {
            "ip": self.ip,
            "note_ports": note_ports,
            "barline_port": barline_port,
            "word_count": self._word_count,
        }

    def send_droplet(
        self,
        endpoint: dict[str, Any],
        droplet: bytes,
        frame_tag: int,
        fault: FaultProfile | None = None,
    ) -> None:
        t0 = time.perf_counter()
        if self._tx_sock is None:
            self._tx_sock = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
            self._tx_sock.bind((self.ip, 0))
        note_ports = endpoint["note_ports"]
        barline_port = endpoint["barline_port"]
        padded = droplet + (b"\x00" if len(droplet) % 2 else b"")
        tag8 = frame_tag & 0xFF
        drop_wi = self._pick_fault_drop_subpacket(fault, self._word_count)
        for wi in range(self._word_count):
            w = (padded[2 * wi] << 8) | padded[2 * wi + 1]
            pop = w.bit_count()
            hdr = struct.pack("!BBB", tag8, wi, pop)
            for bit in range(16):
                if (w >> bit) & 1:
                    if drop_wi == wi and bit == (w & -w).bit_length() - 1:
                        continue
                    self._tx_sock.sendto(hdr, (endpoint["ip"], note_ports[bit]))
                    self.stats.packets_sent += 1
                    self.stats.wire_payload_bytes += 3
                    self.stats.wire_total_bytes_est += 51  # 40B IPv6 + 8B UDP + 3B hdr
            self._tx_sock.sendto(hdr, (endpoint["ip"], barline_port))
            self.stats.packets_sent += 1
            self.stats.wire_payload_bytes += 3
            self.stats.wire_total_bytes_est += 51
        self.stats.droplets_sent += 1
        self.stats.total_tx_ms += (time.perf_counter() - t0) * 1000.0

    def _handle_socket_ready(self, sock: socket.socket) -> None:
        data, _ = sock.recvfrom(64)
        rx_ts = time.perf_counter()
        self.stats.packets_recv += 1
        if len(data) != 3:
            return
        tag8, wi, pop = struct.unpack("!BBB", data)
        if wi >= self._word_count or pop > 16:
            return
        emit_buf: bytes | None = None
        with self._lock:
            now = time.monotonic()
            # Evict stale partial chords
            stale_c = [k for k, v in self._chords.items() if now - v["ts"] > 0.2]
            for k in stale_c:
                del self._chords[k]
            stale_w = [k for k, (ts, _) in self._words.items() if now - ts > 0.2]
            for k in stale_w:
                del self._words[k]

            entry = self._chords.setdefault(
                (tag8, wi), {"bits": set(), "pop": None, "barline": False, "ts": now}
            )
            entry["ts"] = now
            if sock is self._barline_sock:
                entry["barline"] = True
                entry["pop"] = pop
            else:
                entry["bits"].add(self._note_map[sock])

            if entry["barline"] and entry["pop"] is not None and len(entry["bits"]) == entry["pop"]:
                word_val = 0
                for b in entry["bits"]:
                    word_val |= 1 << b
                del self._chords[(tag8, wi)]
                _, wmap = self._words.setdefault(tag8, (now, {}))
                self._words[tag8] = (now, wmap)
                wmap[wi] = word_val
                if len(wmap) == self._word_count:
                    buf = bytearray()
                    for idx in range(self._word_count):
                        wv = wmap[idx]
                        buf.append((wv >> 8) & 0xFF)
                        buf.append(wv & 0xFF)
                    del self._words[tag8]
                    emit_buf = bytes(buf[: self.droplet_size])
        if emit_buf is not None:
            self._emit_droplet(emit_buf, rx_ts)

    def _clear_assembly_state(self) -> None:
        self._chords.clear()
        self._words.clear()

    def close(self) -> None:
        super().close()
        if self._tx_sock is not None:
            try:
                self._tx_sock.close()
            except OSError:
                pass
            self._tx_sock = None


# ---------------------------------------------------------------------------
# 5. HYPERV_MCAST: 16-Group Multicast Nibble Constellation (TTL=0 local)
# ---------------------------------------------------------------------------
class HyperVMcastConstellationLane(AlienLane):
    """Encodes each nibble as which of 16 multicast stars (239.255.13.1..16) sparks."""

    lane_id = "HYPERV_MCAST"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._sock_to_nib: dict[socket.socket, int] = {}
        self._slots: dict[int, tuple[float, dict[int, int]]] = {}
        self._tx_sock: socket.socket | None = None

    def start_receiver(self) -> dict[str, Any]:
        stars: list[list[Any]] = []
        for nib in range(16):
            grp = f"239.255.13.{nib + 1}"
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            _disable_udp_connreset(s)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 512 * 1024)
            except OSError:
                pass
            s.bind((self.ip, 0))
            port = s.getsockname()[1]
            mreq = socket.inet_aton(grp) + socket.inet_aton(self.ip)
            s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
            s.setblocking(False)
            self._rx_socks.append(s)
            self._sock_to_nib[s] = nib
            stars.append([grp, port])
        self._start_rx_thread()
        return {"ip": self.ip, "stars": stars}

    def send_droplet(
        self,
        endpoint: dict[str, Any],
        droplet: bytes,
        frame_tag: int,
        fault: FaultProfile | None = None,
    ) -> None:
        t0 = time.perf_counter()
        if self._tx_sock is None:
            tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            tx.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(self.ip))
            tx.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 0)
            tx.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)
            self._tx_sock = tx
        stars = endpoint["stars"]
        tag8 = frame_tag & 0xFF
        total_nibs = len(droplet) * 2
        drop_ni = self._pick_fault_drop_subpacket(fault, total_nibs)
        ni = 0
        for b in droplet:
            for nib in ((b >> 4) & 0x0F, b & 0x0F):
                if drop_ni != ni:
                    grp, port = stars[nib]
                    spark = struct.pack("!BB", tag8, ni)
                    self._tx_sock.sendto(spark, (grp, port))
                    self.stats.packets_sent += 1
                    self.stats.wire_payload_bytes += 2
                    self.stats.wire_total_bytes_est += 30
                ni += 1
        self.stats.droplets_sent += 1
        self.stats.total_tx_ms += (time.perf_counter() - t0) * 1000.0

    def _handle_socket_ready(self, sock: socket.socket) -> None:
        data, _ = sock.recvfrom(64)
        rx_ts = time.perf_counter()
        self.stats.packets_recv += 1
        if len(data) != 2:
            return
        tag8, ni = struct.unpack("!BB", data)
        expected_nibs = self.droplet_size * 2
        if ni >= expected_nibs:
            return
        nib = self._sock_to_nib[sock]

        emit_buf: bytes | None = None
        with self._lock:
            now = time.monotonic()
            stale = [k for k, (ts, _) in self._slots.items() if now - ts > 0.2]
            for k in stale:
                del self._slots[k]
            evict = (tag8 + 128) & 0xFF
            self._slots.pop(evict, None)

            _, slot = self._slots.setdefault(tag8, (now, {}))
            self._slots[tag8] = (now, slot)
            slot[ni] = nib
            if len(slot) == expected_nibs:
                buf = bytearray()
                for bi in range(self.droplet_size):
                    hi = slot[2 * bi]
                    lo = slot[2 * bi + 1]
                    buf.append((hi << 4) | lo)
                del self._slots[tag8]
                emit_buf = bytes(buf)
        if emit_buf is not None:
            self._emit_droplet(emit_buf, rx_ts)

    def _clear_assembly_state(self) -> None:
        self._slots.clear()

    def close(self) -> None:
        super().close()
        if self._tx_sock is not None:
            try:
                self._tx_sock.close()
            except OSError:
                pass
            self._tx_sock = None


# ---------------------------------------------------------------------------
# 6. WSL_PERMUTE: S_6 Lehmer Permutation Ordering Transposition
# ---------------------------------------------------------------------------
class WslPermutationLane(AlienLane):
    """Encodes each byte into arrival order of 6 permutation tiles over WSL2 vSwitch."""

    lane_id = "WSL_PERMUTE"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._port = 0
        self._tiles: dict[tuple[int, int], tuple[float, list[int]]] = {}
        self._bytes_map: dict[int, tuple[float, dict[int, int]]] = {}
        self._tx_sock: socket.socket | None = None

    def start_receiver(self) -> dict[str, Any]:
        s = _make_udp_rx(socket.AF_INET, self.ip, 0)
        self._rx_socks.append(s)
        self._port = s.getsockname()[1]
        self._start_rx_thread()
        return {"ip": self.ip, "port": self._port}

    def send_droplet(
        self,
        endpoint: dict[str, Any],
        droplet: bytes,
        frame_tag: int,
        fault: FaultProfile | None = None,
    ) -> None:
        t0 = time.perf_counter()
        if self._tx_sock is None:
            self._tx_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._tx_sock.bind((self.ip, 0))
        tag8 = frame_tag & 0xFF
        drop_idx = self._pick_fault_drop_subpacket(fault, len(droplet))
        for idx, b in enumerate(droplet):
            rank = (b << 1) | (idx & 1)
            perm = encode_lehmer(rank, 6)
            for pos, tile in enumerate(perm):
                if drop_idx == idx and pos == 0:
                    continue
                pkt = struct.pack("!BBB", tag8, idx, tile)
                self._tx_sock.sendto(pkt, (endpoint["ip"], endpoint["port"]))
                self.stats.packets_sent += 1
                self.stats.wire_payload_bytes += 3
                self.stats.wire_total_bytes_est += 31
        self.stats.droplets_sent += 1
        self.stats.total_tx_ms += (time.perf_counter() - t0) * 1000.0

    def _handle_socket_ready(self, sock: socket.socket) -> None:
        data, _ = sock.recvfrom(64)
        rx_ts = time.perf_counter()
        self.stats.packets_recv += 1
        if len(data) != 3:
            return
        tag8, idx, tile = struct.unpack("!BBB", data)
        if idx >= self.droplet_size or tile >= 6:
            return
        emit_buf: bytes | None = None
        with self._lock:
            now = time.monotonic()
            stale_t = [k for k, (ts, _) in self._tiles.items() if now - ts > 0.2]
            for k in stale_t:
                del self._tiles[k]
            stale_b = [k for k, (ts, _) in self._bytes_map.items() if now - ts > 0.2]
            for k in stale_b:
                del self._bytes_map[k]

            _, tlist = self._tiles.setdefault((tag8, idx), (now, []))
            self._tiles[(tag8, idx)] = (now, tlist)
            tlist.append(tile)
            if len(tlist) == 6:
                del self._tiles[(tag8, idx)]
                try:
                    rank = decode_lehmer(tlist)
                except ValueError:
                    self.stats.reconstruct_errors += 1
                    return
                if (rank & 1) != (idx & 1) or (rank >> 1) > 255:
                    self.stats.reconstruct_errors += 1
                    return
                b = rank >> 1
                _, bmap = self._bytes_map.setdefault(tag8, (now, {}))
                self._bytes_map[tag8] = (now, bmap)
                bmap[idx] = b
                if len(bmap) == self.droplet_size:
                    emit_buf = bytes(bmap[i] for i in range(self.droplet_size))
                    del self._bytes_map[tag8]
        if emit_buf is not None:
            self._emit_droplet(emit_buf, rx_ts)

    def _clear_assembly_state(self) -> None:
        self._tiles.clear()
        self._bytes_map.clear()

    def close(self) -> None:
        super().close()
        if self._tx_sock is not None:
            try:
                self._tx_sock.close()
            except OSError:
                pass
            self._tx_sock = None


# ---------------------------------------------------------------------------
# 7. ICMP_REFLECT: Raw ICMP Type-8 -> Kernel Echo-Reply Type-0 Reflector
# ---------------------------------------------------------------------------
class IcmpKernelReflectLane(AlienLane):
    """Bounces droplets off the Windows kernel via Raw ICMP Type-8 -> Type-0 Echo Reply."""

    lane_id = "ICMP_REFLECT"

    def __init__(
        self,
        ip: str = "127.0.0.1",
        droplet_size: int = 20,
        session_seed: bytes = b"chimera",
        on_droplet: DropletCallback | None = None,
        icmp_id: int | None = None,
        on_ack: Callable[[bytes], None] | None = None,
    ) -> None:
        super().__init__(ip, droplet_size, session_seed, on_droplet)
        self.icmp_id = (
            icmp_id
            if icmp_id is not None
            else ((os.getpid() ^ int.from_bytes(session_seed[:2], "big")) & 0xFFFF)
        )
        self.on_ack = on_ack
        self._tx_sock: socket.socket | None = None

    def start_receiver(self) -> dict[str, Any]:
        s = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP)
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 512 * 1024)
        except OSError:
            pass
        s.bind((self.ip, 0))
        s.setblocking(False)
        self._rx_socks.append(s)
        self._start_rx_thread()
        return {"ip": self.ip, "icmp_id": self.icmp_id}

    def _send_icmp_packet(
        self, target_ip: str, icmp_id: int, seq: int, kind: int, payload: bytes
    ) -> int:
        if self._tx_sock is None:
            tx = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP)
            tx.setsockopt(socket.IPPROTO_IP, socket.IP_TTL, 111)
            self._tx_sock = tx
        body = b"CH" + struct.pack("!BB", kind, len(payload)) + payload
        hdr0 = struct.pack("!BBHHH", 8, 0, 0, icmp_id & 0xFFFF, seq & 0xFFFF)
        ck = _icmp_checksum(hdr0 + body)
        pkt = struct.pack("!BBHHH", 8, 0, ck, icmp_id & 0xFFFF, seq & 0xFFFF) + body
        self._tx_sock.sendto(pkt, (target_ip, 0))
        return len(pkt)

    def send_droplet(
        self,
        endpoint: dict[str, Any],
        droplet: bytes,
        frame_tag: int,
        fault: FaultProfile | None = None,
    ) -> None:
        t0 = time.perf_counter()
        if self._pick_fault_drop_subpacket(fault, 1) is None:
            pkt_len = self._send_icmp_packet(
                endpoint["ip"], endpoint["icmp_id"], frame_tag, 0x01, droplet
            )
            self.stats.packets_sent += 1
            self.stats.wire_payload_bytes += pkt_len
            self.stats.wire_total_bytes_est += pkt_len + 20
        self.stats.droplets_sent += 1
        self.stats.total_tx_ms += (time.perf_counter() - t0) * 1000.0

    def send_ack(self, endpoint_ip: str, icmp_id: int, tag: bytes) -> None:
        self._send_icmp_packet(endpoint_ip, icmp_id, 0xAC4, 0x02, tag)

    def _handle_socket_ready(self, sock: socket.socket) -> None:
        raw, _ = sock.recvfrom(2048)
        rx_ts = time.perf_counter()
        if len(raw) < 28:
            return
        ihl = (raw[0] & 0x0F) * 4
        if len(raw) < ihl + 12:
            return
        itype, _, _, iid, _ = struct.unpack("!BBHHH", raw[ihl : ihl + 8])
        # Windows kernel automatically bounces Echo Request (8) into Echo Reply (0) on 127.0.0.1
        if itype != 0 or iid != self.icmp_id:
            return
        body = raw[ihl + 8 :]
        if len(body) < 4 or body[:2] != b"CH":
            return
        self.stats.packets_recv += 1
        kind, plen = struct.unpack("!BB", body[2:4])
        payload = body[4:]
        if len(payload) != plen:
            return
        if kind == 0x01 and plen == self.droplet_size:
            self._emit_droplet(payload, rx_ts)
        elif kind == 0x02 and self.on_ack is not None:
            self.on_ack(payload)

    def close(self) -> None:
        super().close()
        if self._tx_sock is not None:
            try:
                self._tx_sock.close()
            except OSError:
                pass
            self._tx_sock = None


# ---------------------------------------------------------------------------
# 8. LO_V6_JUMBO: ::1 58 KiB Chaotic-OTP Jumbo Superframes (CRC-32 + XOR FEC + NACK)
# ---------------------------------------------------------------------------
class LoopbackV6JumboLane(AlienLane):
    """Blasts 58 KiB masked superframes over Loopback IPv6 (::1) with XOR stripe FEC & NACK."""

    lane_id = "LO_V6_JUMBO"
    MAX_CHUNK = 58000
    STRIPE_SIZE = 4

    def __init__(
        self,
        ip: str = "::1",
        on_jumbo: JumboCallback | None = None,
        session_seed: bytes = b"chimera",
    ) -> None:
        super().__init__(ip=ip, droplet_size=0, session_seed=session_seed, on_droplet=None)
        self.on_jumbo = on_jumbo
        self._port = 0
        self._chunks: dict[int, dict[int, bytes]] = {}
        self._parities: dict[int, dict[int, bytes]] = {}
        self._totals: dict[int, int] = {}
        self._total_lens: dict[int, int] = {}
        self._completed_tids: set[int] = set()
        self._tx_sock: socket.socket | None = None

    def start_receiver(self) -> dict[str, Any]:
        s = _make_udp_rx(socket.AF_INET6, self.ip, 0, rcvbuf=4 * 1024 * 1024)
        self._rx_socks.append(s)
        self._port = s.getsockname()[1]
        self._start_rx_thread()
        return {"ip": self.ip, "port": self._port, "max_chunk": self.MAX_CHUNK}

    def _ensure_tx_sock(self) -> socket.socket:
        if self._tx_sock is None:
            tx = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
            tx.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4 * 1024 * 1024)
            tx.bind((self.ip, 0))
            self._tx_sock = tx
        return self._tx_sock

    def _send_jumbo_frame(
        self,
        endpoint: dict[str, Any],
        magic: bytes,
        transfer_id: int,
        seq_idx: int,
        total_chunks: int,
        total_len: int,
        payload: bytes,
        drop_rate: float,
    ) -> bool:
        if drop_rate > 0.0 and self._rng.random() < drop_rate:
            self.stats.fault_drops_injected += 1
            return False
        tx = self._ensure_tx_sock()
        crc = zlib.crc32(payload) & 0xFFFFFFFF
        frame = (
            magic
            + struct.pack("!IHHII", transfer_id, seq_idx, total_chunks, total_len, crc)
            + payload
        )
        tx.sendto(frame, (endpoint["ip"], endpoint["port"]))
        self.stats.packets_sent += 1
        self.stats.wire_payload_bytes += len(frame)
        self.stats.wire_total_bytes_est += len(frame) + 48
        return True

    def send_blob(
        self,
        endpoint: dict[str, Any],
        transfer_id: int,
        masked_blob: bytes,
        fault: FaultProfile | None = None,
    ) -> int:
        """Split `masked_blob` into 58 KiB superframes + XOR stripe parities over ::1."""
        t0 = time.perf_counter()
        total_len = len(masked_blob)
        total_chunks = max(1, (total_len + self.MAX_CHUNK - 1) // self.MAX_CHUNK)
        drop_rate = fault.jumbo_drop_rate if fault else 0.0
        chunks = [
            masked_blob[idx * self.MAX_CHUNK : (idx + 1) * self.MAX_CHUNK]
            for idx in range(total_chunks)
        ]

        for idx, chunk in enumerate(chunks):
            self._send_jumbo_frame(
                endpoint, b"JM", transfer_id, idx, total_chunks, total_len, chunk, drop_rate
            )
            if total_chunks > 4:
                time.sleep(0.00015)

        num_stripes = (total_chunks + self.STRIPE_SIZE - 1) // self.STRIPE_SIZE
        for stripe_idx in range(num_stripes):
            s_start = stripe_idx * self.STRIPE_SIZE
            s_chunks = chunks[s_start : s_start + self.STRIPE_SIZE]
            max_len = max(len(c) for c in s_chunks)
            acc = 0
            for c in s_chunks:
                padded = c.ljust(max_len, b"\x00")
                acc ^= int.from_bytes(padded, "little")
            parity = acc.to_bytes(max_len, "little")
            self._send_jumbo_frame(
                endpoint,
                b"JP",
                transfer_id,
                stripe_idx,
                total_chunks,
                total_len,
                parity,
                drop_rate,
            )

        self.stats.droplets_sent += total_chunks
        self.stats.total_tx_ms += (time.perf_counter() - t0) * 1000.0
        return total_chunks

    def send_missing_chunks(
        self,
        endpoint: dict[str, Any],
        transfer_id: int,
        masked_blob: bytes,
        missing_indices: list[int],
        fault: FaultProfile | None = None,
    ) -> int:
        """Retransmit specifically requested chunk indices for Selective NACK ARQ."""
        t0 = time.perf_counter()
        total_len = len(masked_blob)
        total_chunks = max(1, (total_len + self.MAX_CHUNK - 1) // self.MAX_CHUNK)
        drop_rate = fault.jumbo_drop_rate if fault else 0.0
        for idx in missing_indices:
            if 0 <= idx < total_chunks:
                chunk = masked_blob[idx * self.MAX_CHUNK : (idx + 1) * self.MAX_CHUNK]
                self._send_jumbo_frame(
                    endpoint, b"JM", transfer_id, idx, total_chunks, total_len, chunk, drop_rate
                )
        self.stats.total_tx_ms += (time.perf_counter() - t0) * 1000.0
        return len(missing_indices)

    def get_missing_chunks(self, transfer_id: int, expected_total: int) -> list[int]:
        """Return sorted list of chunk indices still missing for `transfer_id`."""
        with self._lock:
            if transfer_id in self._completed_tids:
                return []
            cmap = self._chunks.get(transfer_id, {})
            return [i for i in range(expected_total) if i not in cmap]

    def _try_fec_recover_locked(self, tid: int) -> None:
        total = self._totals.get(tid, 0)
        total_len = self._total_lens.get(tid, 0)
        cmap = self._chunks.get(tid)
        pmap = self._parities.get(tid)
        if not total or cmap is None or pmap is None:
            return
        for stripe_idx, parity in list(pmap.items()):
            s_start = stripe_idx * self.STRIPE_SIZE
            s_end = min(total, s_start + self.STRIPE_SIZE)
            missing = [i for i in range(s_start, s_end) if i not in cmap]
            if len(missing) == 1:
                m_idx = missing[0]
                plen = len(parity)
                acc = int.from_bytes(parity, "little")
                for i in range(s_start, s_end):
                    if i == m_idx:
                        continue
                    acc ^= int.from_bytes(cmap[i].ljust(plen, b"\x00"), "little")
                exp_len = min(self.MAX_CHUNK, max(0, total_len - m_idx * self.MAX_CHUNK))
                cmap[m_idx] = acc.to_bytes(plen, "little")[:exp_len]
                self.stats.fec_recoveries += 1
                del pmap[stripe_idx]

    def _handle_socket_ready(self, sock: socket.socket) -> None:
        data, _ = sock.recvfrom(65535)
        rx_ts = time.perf_counter()
        self.stats.packets_recv += 1
        if len(data) < 18:
            return
        magic = data[:2]
        if magic not in (b"JM", b"JP"):
            return
        tid, seq_idx, total, total_len, crc = struct.unpack("!IHHII", data[2:18])
        payload = data[18:]
        if (zlib.crc32(payload) & 0xFFFFFFFF) != crc:
            self.stats.reconstruct_errors += 1
            return

        completed_blob: bytes | None = None
        with self._lock:
            if tid in self._completed_tids:
                return
            self._totals[tid] = total
            self._total_lens[tid] = total_len
            cmap = self._chunks.setdefault(tid, {})
            pmap = self._parities.setdefault(tid, {})
            if magic == b"JM":
                if seq_idx < total and seq_idx not in cmap:
                    cmap[seq_idx] = payload
            else:
                pmap[seq_idx] = payload
            self._try_fec_recover_locked(tid)
            if len(cmap) == total:
                completed_blob = b"".join(cmap[i] for i in range(total))[:total_len]
                self._completed_tids.add(tid)
                self._chunks.pop(tid, None)
                self._parities.pop(tid, None)
                self._totals.pop(tid, None)
                self._total_lens.pop(tid, None)
                self.stats.droplets_recv += total
        if completed_blob is not None and self.on_jumbo is not None:
            self.on_jumbo(tid, completed_blob, rx_ts)

    def _clear_assembly_state(self) -> None:
        self._chunks.clear()
        self._parities.clear()
        self._totals.clear()
        self._total_lens.clear()

    def close(self) -> None:
        super().close()
        if self._tx_sock is not None:
            try:
                self._tx_sock.close()
            except OSError:
                pass
            self._tx_sock = None


def build_droplet_lane(
    lane_id: str,
    env: EnvironmentProfile,
    droplet_size: int,
    session_seed: bytes,
    on_droplet: DropletCallback | None = None,
    icmp_id: int | None = None,
) -> AlienLane:
    """Instantiate one of the 7 alien droplet lanes from a probed EnvironmentProfile."""
    realm = env.realms[lane_id]
    if lane_id == "GHOST_127":
        return Ghost127Lane(realm.ip, droplet_size, session_seed, on_droplet)
    if lane_id == "LAN_LENGTH":
        return LanLengthNoiseLane(realm.ip, droplet_size, session_seed, on_droplet)
    if lane_id == "TS_V4_1280":
        return TailscaleV4FountainLane(realm.ip, droplet_size, session_seed, on_droplet)
    if lane_id == "TS_V6_CHORD":
        return TailscaleV6ChordLane(realm.ip, droplet_size, session_seed, on_droplet)
    if lane_id == "HYPERV_MCAST":
        return HyperVMcastConstellationLane(realm.ip, droplet_size, session_seed, on_droplet)
    if lane_id == "WSL_PERMUTE":
        return WslPermutationLane(realm.ip, droplet_size, session_seed, on_droplet)
    if lane_id == "ICMP_REFLECT":
        return IcmpKernelReflectLane(
            realm.ip, droplet_size, session_seed, on_droplet, icmp_id=icmp_id
        )
    raise KeyError(f"Unknown droplet lane: {lane_id}")
