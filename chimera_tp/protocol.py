"""End-to-end CHIMERA-TP transport protocol engine (PURE-METAMORPHIC & HOLOGRAPHIC-SPLIT)."""

from __future__ import annotations

import hashlib
import json
import os
import select
import socket
import struct
import threading
import time
import zlib
from dataclasses import asdict, dataclass, field
from typing import Any

from .gf256 import (
    ChaosLaneScheduler,
    RLNCDecoder,
    RLNCEncoder,
    chaotic_keystream,
    shannon_entropy,
    xor_bytes,
)
from .lanes import (
    AlienLane,
    FaultProfile,
    IcmpKernelReflectLane,
    LaneStats,
    LoopbackV6JumboLane,
    build_droplet_lane,
)
from .probe import EnvironmentProfile, _disable_udp_connreset


@dataclass
class TransferReport:
    """Complete telemetry and verification report for a CHIMERA-TP transfer."""

    mode: str
    success: bool
    sha256_match: bool
    expected_sha256: str
    actual_sha256: str
    payload_bytes: int
    wire_coded_bytes: int
    k_blocks: int
    block_size: int
    droplets_sent: int
    droplets_received: int
    innovative_droplets: int
    crc_drops: int
    elapsed_ms: float
    effective_kbps: float
    active_lanes: list[str]
    killed_lanes: list[str]
    packet_drop_rate: float
    corrupt_lan_noise: bool
    topology_fingerprint: str
    holo_entropy_bits_per_byte: float | None = None
    jumbo_chunks: int = 0
    rank_timeline: list[dict[str, Any]] = field(default_factory=list)
    per_lane_stats: dict[str, dict[str, Any]] = field(default_factory=dict)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class _SessionDecoderState:
    def __init__(
        self,
        transfer_id: int,
        decoder: RLNCDecoder,
        orig_len: int,
        compressed_len: int,
        compressed: bool,
        expected_sha256: str,
        reply_addr: tuple[str, int],
        start_ts: float,
        baseline_rx: dict[str, tuple[int, int, int]] | None = None,
    ) -> None:
        self.transfer_id = transfer_id
        self.decoder = decoder
        self.orig_len = orig_len
        self.compressed_len = compressed_len
        self.compressed = compressed
        self.expected_sha256 = expected_sha256
        self.reply_addr = reply_addr
        self.start_ts = start_ts
        self.baseline_rx = baseline_rx or {}
        self.rank_timeline: list[dict[str, Any]] = []
        self.done_event = threading.Event()
        self.recovered_payload: bytes = b""
        self.actual_sha256: str = ""
        self.sha256_match: bool = False
        self.droplets_received: int = 0
        self.innovative_droplets: int = 0


class ChimeraReceiver:
    """Multi-realm CHIMERA-TP receiver binding all discovered Windows interfaces."""

    def __init__(
        self,
        env: EnvironmentProfile,
        droplet_size: int = 20,
        session_seed: bytes | None = None,
    ) -> None:
        self.env = env
        self.droplet_size = droplet_size
        self.block_size = droplet_size - 4  # 2B droplet_id + block_size + 2B crc16
        self.session_seed = session_seed or os.urandom(16)
        self.icmp_id = (os.getpid() ^ 0xC411) & 0xFFFF

        self._lock = threading.Lock()
        self._lanes: dict[str, AlienLane] = {}
        self._lane_endpoints: dict[str, Any] = {}
        self._jumbo_lane: LoopbackV6JumboLane | None = None
        self._jumbo_endpoint: dict[str, Any] | None = None

        self._ctrl_sock: socket.socket | None = None
        self._ctrl_port: int = 0
        self._ctrl_thread: threading.Thread | None = None
        self._stop_event = threading.Event()

        self._active_session: _SessionDecoderState | None = None
        self._completed_sessions: dict[int, _SessionDecoderState] = {}

        self._holo_blobs: dict[int, bytes] = {}
        self._holo_capsules: dict[int, bytes] = {}
        self._holo_recovered: dict[int, tuple[bytes, str, bool]] = {}
        self._holo_events: dict[int, threading.Event] = {}

    def start(self) -> dict[str, Any]:
        """Bind sockets across all available realms and return the session offer."""
        self._stop_event.clear()

        ctrl = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
        _disable_udp_connreset(ctrl)
        ctrl.bind(("::1", 0))
        ctrl.setblocking(False)
        self._ctrl_sock = ctrl
        self._ctrl_port = ctrl.getsockname()[1]
        self._ctrl_thread = threading.Thread(
            target=self._ctrl_loop, name="chimera-ctrl-rx", daemon=True
        )
        self._ctrl_thread.start()

        for lane_id in self.env.active_droplet_lanes():
            lane = build_droplet_lane(
                lane_id=lane_id,
                env=self.env,
                droplet_size=self.droplet_size,
                session_seed=self.session_seed,
                on_droplet=self._on_droplet_received,
                icmp_id=self.icmp_id,
            )
            ep = lane.start_receiver()
            self._lanes[lane_id] = lane
            self._lane_endpoints[lane_id] = ep

        if "LO_V6_JUMBO" in self.env.realms and self.env.realms["LO_V6_JUMBO"].available:
            jlane = LoopbackV6JumboLane(
                ip=self.env.realms["LO_V6_JUMBO"].ip,
                on_jumbo=self._on_jumbo_received,
                session_seed=self.session_seed,
            )
            self._jumbo_endpoint = jlane.start_receiver()
            self._jumbo_lane = jlane

        return self.get_offer()

    def get_offer(self) -> dict[str, Any]:
        return {
            "topology_fingerprint": self.env.topology_fingerprint,
            "droplet_size": self.droplet_size,
            "block_size": self.block_size,
            "session_seed_hex": self.session_seed.hex(),
            "ctrl": {"ip": "::1", "port": self._ctrl_port},
            "lanes": self._lane_endpoints,
            "jumbo": self._jumbo_endpoint,
        }

    def _ctrl_loop(self) -> None:
        while not self._stop_event.is_set():
            if self._ctrl_sock is None:
                break
            try:
                readable, _, _ = select.select([self._ctrl_sock], [], [], 0.02)
            except (OSError, ValueError):
                break
            for sock in readable:
                try:
                    data, addr = sock.recvfrom(8192)
                except (ConnectionResetError, BlockingIOError, OSError):
                    continue
                if len(data) < 4:
                    continue
                if data[:4] == b"STRT":
                    msg = json.loads(data[4:].decode("utf-8"))
                    self._init_transfer_session(msg, (addr[0], addr[1]))

    def _init_transfer_session(
        self, msg: dict[str, Any], reply_addr: tuple[str, int]
    ) -> None:
        tid = int(msg["transfer_id"])
        k = int(msg["k"])
        block_size = int(msg["block_size"])
        seed = bytes.fromhex(msg["rlnc_seed_hex"])
        dec = RLNCDecoder(k=k, block_size=block_size, seed=seed)
        for lane in self._lanes.values():
            lane.reset_state()
        with self._lock:
            baseline = {
                lid: (
                    lane.stats.packets_recv,
                    lane.stats.droplets_recv,
                    lane.stats.reconstruct_errors,
                )
                for lid, lane in self._lanes.items()
            }
            sess = _SessionDecoderState(
                transfer_id=tid,
                decoder=dec,
                orig_len=int(msg["orig_len"]),
                compressed_len=int(msg["compressed_len"]),
                compressed=bool(msg["compressed"]),
                expected_sha256=str(msg["expected_sha256"]),
                reply_addr=reply_addr,
                start_ts=time.perf_counter(),
                baseline_rx=baseline,
            )
            self._active_session = sess
            self._completed_sessions.pop(tid, None)
        if self._ctrl_sock is not None:
            ack = b"RDY!" + struct.pack("!I", tid)
            self._ctrl_sock.sendto(ack, reply_addr)

    def _on_droplet_received(
        self, lane_id: str, droplet: bytes, rx_ts: float
    ) -> None:
        solved_payload: dict[str, Any] | None = None
        reply_addr: tuple[str, int] | None = None
        tid_solved: int = 0
        capsule_bytes: bytes | None = None

        with self._lock:
            sess = self._active_session
            if sess is None or sess.done_event.is_set():
                return
            crc_ok, innovative, rank = sess.decoder.add_droplet(droplet)
            sess.droplets_received += 1
            if innovative:
                sess.innovative_droplets += 1
            elapsed_ms = (rx_ts - sess.start_ts) * 1000.0
            sess.rank_timeline.append(
                {
                    "elapsed_ms": round(elapsed_ms, 3),
                    "lane": lane_id,
                    "rank": rank,
                    "innovative": innovative,
                    "crc_ok": crc_ok,
                }
            )
            if sess.decoder.is_complete():
                blocks = sess.decoder.solve()
                raw = b"".join(blocks)[: sess.compressed_len]
                try:
                    if sess.compressed:
                        recovered = zlib.decompress(raw)
                    else:
                        recovered = raw[: sess.orig_len]
                    actual_sha = hashlib.sha256(recovered).hexdigest()
                except zlib.error:
                    recovered = b""
                    actual_sha = ""
                sess.recovered_payload = recovered
                sess.actual_sha256 = actual_sha
                sess.sha256_match = bool(actual_sha) and (actual_sha == sess.expected_sha256)
                sess.done_event.set()
                self._completed_sessions[sess.transfer_id] = sess
                tid_solved = sess.transfer_id
                reply_addr = sess.reply_addr
                capsule_bytes = recovered
                rx_lane_delta: dict[str, dict[str, Any]] = {}
                for lid, lane in self._lanes.items():
                    bp, bd, be = sess.baseline_rx.get(lid, (0, 0, 0))
                    st = lane.stats.to_dict()
                    st["packets_recv"] = max(0, lane.stats.packets_recv - bp)
                    st["droplets_recv"] = max(0, lane.stats.droplets_recv - bd)
                    st["reconstruct_errors"] = max(0, lane.stats.reconstruct_errors - be)
                    rx_lane_delta[lid] = st
                solved_payload = {
                    "transfer_id": sess.transfer_id,
                    "sha256_match": sess.sha256_match,
                    "actual_sha256": actual_sha,
                    "droplets_received": sess.droplets_received,
                    "innovative_droplets": sess.innovative_droplets,
                    "crc_drops": sess.decoder.crc_drops,
                    "rank_timeline": sess.rank_timeline,
                    "rx_lane_stats": rx_lane_delta,
                }

        if capsule_bytes is not None and len(capsule_bytes) == 72:
            # Check if this corresponds to a holographic superframe transfer
            cap_tid, _ = struct.unpack("!II", capsule_bytes[:8])
            with self._lock:
                if cap_tid in self._holo_events or cap_tid in self._holo_blobs:
                    self._holo_capsules[cap_tid] = capsule_bytes
                    self._try_finish_holographic(cap_tid)

        if solved_payload is not None and reply_addr is not None and self._ctrl_sock is not None:
            wire = b"SOLV" + json.dumps(solved_payload, separators=(",", ":")).encode("utf-8")
            for _ in range(3):
                try:
                    self._ctrl_sock.sendto(wire, reply_addr)
                except OSError:
                    break
            icmp_lane = self._lanes.get("ICMP_REFLECT")
            if isinstance(icmp_lane, IcmpKernelReflectLane):
                try:
                    icmp_lane.send_ack(
                        "127.0.0.1", self.icmp_id, struct.pack("!I", tid_solved)
                    )
                except OSError:
                    pass

    def _on_jumbo_received(
        self, transfer_id: int, masked_blob: bytes, _rx_ts: float
    ) -> None:
        with self._lock:
            self._holo_blobs[transfer_id] = masked_blob
            self._try_finish_holographic(transfer_id)

    def _try_finish_holographic(self, transfer_id: int) -> None:
        blob = self._holo_blobs.get(transfer_id)
        capsule = self._holo_capsules.get(transfer_id)
        if blob is None or capsule is None:
            return
        if len(capsule) != 72:
            return
        cap_tid, orig_len = struct.unpack("!II", capsule[:8])
        if cap_tid != transfer_id:
            return
        holo_key = capsule[8:40]
        expected_sha = capsule[40:72].hex()
        topo_bytes = bytes.fromhex(self.env.topology_fingerprint)
        stream_seed = hashlib.blake2b(holo_key + topo_bytes, digest_size=32).digest()
        recovered = xor_bytes(blob, chaotic_keystream(stream_seed, len(blob)))[:orig_len]
        actual_sha = hashlib.sha256(recovered).hexdigest()
        self._holo_recovered[transfer_id] = (
            recovered,
            actual_sha,
            actual_sha == expected_sha,
        )
        ev = self._holo_events.setdefault(transfer_id, threading.Event())
        ev.set()

    def register_holographic_waiter(self, transfer_id: int) -> threading.Event:
        with self._lock:
            return self._holo_events.setdefault(transfer_id, threading.Event())

    def get_recovered_payload(self, transfer_id: int) -> bytes:
        with self._lock:
            if transfer_id in self._holo_recovered:
                return self._holo_recovered[transfer_id][0]
            sess = self._completed_sessions.get(transfer_id)
            if sess is not None:
                return sess.recovered_payload
        raise KeyError(f"No recovered payload for transfer_id={transfer_id}")

    def get_holographic_verification(self, transfer_id: int) -> tuple[bytes, str, bool]:
        with self._lock:
            return self._holo_recovered[transfer_id]

    def get_jumbo_stats(self) -> dict[str, Any]:
        if self._jumbo_lane is None:
            return {}
        return self._jumbo_lane.stats.to_dict()

    def close(self) -> None:
        self._stop_event.set()
        if self._ctrl_thread and self._ctrl_thread.is_alive():
            self._ctrl_thread.join(timeout=0.5)
        if self._ctrl_sock is not None:
            try:
                self._ctrl_sock.close()
            except OSError:
                pass
            self._ctrl_sock = None
        for lane in self._lanes.values():
            lane.close()
        self._lanes.clear()
        if self._jumbo_lane is not None:
            self._jumbo_lane.close()
            self._jumbo_lane = None


class ChimeraSender:
    """CHIMERA-TP chaotic multi-realm sender."""

    def __init__(self, env: EnvironmentProfile, offer: dict[str, Any]) -> None:
        self.env = env
        self.offer = offer
        self.droplet_size = int(offer["droplet_size"])
        self.block_size = int(offer["block_size"])
        self.session_seed = bytes.fromhex(offer["session_seed_hex"])
        self._transfer_counter = 1

    def _next_transfer_id(self) -> int:
        tid = (int(time.time() * 1000) ^ self._transfer_counter) & 0x7FFFFFFF
        self._transfer_counter += 1
        return tid

    def _send_metamorphic_core(
        self,
        payload: bytes,
        fault: FaultProfile | None,
        compress: bool,
        mode_label: str,
        timeout_s: float,
    ) -> tuple[int, TransferReport]:
        fault = fault or FaultProfile()
        tid = self._next_transfer_id()
        expected_sha = hashlib.sha256(payload).hexdigest()

        raw_data = zlib.compress(payload, level=6) if compress else payload
        compressed_len = len(raw_data)
        k = max(1, (compressed_len + self.block_size - 1) // self.block_size)
        padded = raw_data.ljust(k * self.block_size, b"\x00")
        blocks = [
            padded[i * self.block_size : (i + 1) * self.block_size] for i in range(k)
        ]
        rlnc_seed = os.urandom(16)
        encoder = RLNCEncoder(blocks, rlnc_seed)

        # Build sender-side lane instances for all offered lanes not killed
        offered_lanes = list(self.offer["lanes"].keys())
        active_lanes = [lid for lid in offered_lanes if lid not in fault.kill_lanes]
        killed_lanes = [lid for lid in offered_lanes if lid in fault.kill_lanes]
        if not active_lanes:
            raise ValueError("Cannot run transfer with zero surviving droplet lanes")

        tx_lanes: dict[str, AlienLane] = {
            lid: build_droplet_lane(
                lane_id=lid,
                env=self.env,
                droplet_size=self.droplet_size,
                session_seed=self.session_seed,
            )
            for lid in active_lanes
        }
        scheduler = ChaosLaneScheduler(active_lanes, rlnc_seed)

        # Open sender-side ::1 control socket
        ctrl = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
        _disable_udp_connreset(ctrl)
        ctrl.bind(("::1", 0))
        ctrl.setblocking(False)
        ctrl_ep = (self.offer["ctrl"]["ip"], int(self.offer["ctrl"]["port"]))

        start_msg = {
            "transfer_id": tid,
            "k": k,
            "block_size": self.block_size,
            "orig_len": len(payload),
            "compressed_len": compressed_len,
            "compressed": compress,
            "expected_sha256": expected_sha,
            "rlnc_seed_hex": rlnc_seed.hex(),
        }
        start_pkt = b"STRT" + json.dumps(start_msg, separators=(",", ":")).encode("utf-8")

        solved_data: dict[str, Any] | None = None
        ready = False
        try:
            # Wait for RDY! handshake
            rdy_deadline = time.perf_counter() + 2.0
            while time.perf_counter() < rdy_deadline and not ready:
                ctrl.sendto(start_pkt, ctrl_ep)
                r, _, _ = select.select([ctrl], [], [], 0.05)
                for s in r:
                    pkt, _ = s.recvfrom(4096)
                    if pkt[:4] == b"RDY!" and struct.unpack("!I", pkt[4:8])[0] == tid:
                        ready = True
                        break
            if not ready:
                raise TimeoutError("Receiver did not acknowledge STRT handshake")

            t_start = time.perf_counter()
            deadline = t_start + timeout_s
            droplet_id = 0
            lane_tags: dict[str, int] = {lid: 0 for lid in active_lanes}

            while time.perf_counter() < deadline and solved_data is None:
                lid = scheduler.next_lane()
                lane = tx_lanes[lid]
                ep = self.offer["lanes"][lid]
                ftag = lane_tags[lid]
                lane_tags[lid] += 1

                droplet = encoder.generate_droplet(droplet_id)
                lane.send_droplet(ep, droplet, ftag, fault=fault)
                droplet_id += 1

                # Check non-blocking control socket for SOLV ACK
                r, _, _ = select.select([ctrl], [], [], 0.0)
                if r:
                    while True:
                        try:
                            pkt, _ = ctrl.recvfrom(65535)
                        except BlockingIOError:
                            break
                        if pkt[:4] == b"SOLV":
                            parsed = json.loads(pkt[4:].decode("utf-8"))
                            if int(parsed["transfer_id"]) == tid:
                                solved_data = parsed
                                break

                if solved_data is not None:
                    break

                # Give receiver thread a short yield after sending k droplets or in bursts
                if droplet_id >= k:
                    r, _, _ = select.select([ctrl], [], [], 0.002)
                    if r:
                        pkt, _ = ctrl.recvfrom(65535)
                        if pkt[:4] == b"SOLV":
                            parsed = json.loads(pkt[4:].decode("utf-8"))
                            if int(parsed["transfer_id"]) == tid:
                                solved_data = parsed
                                break
                elif droplet_id % 4 == 0:
                    time.sleep(0.0005)

            elapsed_ms = (time.perf_counter() - t_start) * 1000.0
            if solved_data is None:
                # Drain up to 0.5s for late SOLV
                wait_end = time.perf_counter() + 0.5
                while time.perf_counter() < wait_end and solved_data is None:
                    r, _, _ = select.select([ctrl], [], [], 0.02)
                    if r:
                        pkt, _ = ctrl.recvfrom(65535)
                        if pkt[:4] == b"SOLV":
                            parsed = json.loads(pkt[4:].decode("utf-8"))
                            if int(parsed["transfer_id"]) == tid:
                                solved_data = parsed
                                break

            merged_stats: dict[str, dict[str, Any]] = {}
            rx_stats = solved_data.get("rx_lane_stats", {}) if solved_data else {}
            for lid in offered_lanes:
                if lid in tx_lanes:
                    st = tx_lanes[lid].stats.to_dict()
                    rxs = rx_stats.get(lid, {})
                    st["packets_recv"] = rxs.get("packets_recv", 0)
                    st["droplets_recv"] = rxs.get("droplets_recv", 0)
                    st["reconstruct_errors"] = rxs.get("reconstruct_errors", 0)
                    st["killed"] = False
                else:
                    st = LaneStats(lane_id=lid).to_dict()
                    st["killed"] = True
                merged_stats[lid] = st

            if solved_data is None:
                report = TransferReport(
                    mode=mode_label,
                    success=False,
                    sha256_match=False,
                    expected_sha256=expected_sha,
                    actual_sha256="",
                    payload_bytes=len(payload),
                    wire_coded_bytes=compressed_len,
                    k_blocks=k,
                    block_size=self.block_size,
                    droplets_sent=droplet_id,
                    droplets_received=0,
                    innovative_droplets=0,
                    crc_drops=0,
                    elapsed_ms=round(elapsed_ms, 2),
                    effective_kbps=0.0,
                    active_lanes=active_lanes,
                    killed_lanes=killed_lanes,
                    packet_drop_rate=fault.packet_drop_rate,
                    corrupt_lan_noise=fault.corrupt_lan_noise,
                    topology_fingerprint=self.env.topology_fingerprint,
                    per_lane_stats=merged_stats,
                    error="Timed out waiting for SOLV ACK",
                )
                return tid, report

            eff_kbps = (len(payload) * 8.0) / max(elapsed_ms, 0.001)
            report = TransferReport(
                mode=mode_label,
                success=bool(solved_data["sha256_match"]),
                sha256_match=bool(solved_data["sha256_match"]),
                expected_sha256=expected_sha,
                actual_sha256=str(solved_data["actual_sha256"]),
                payload_bytes=len(payload),
                wire_coded_bytes=compressed_len,
                k_blocks=k,
                block_size=self.block_size,
                droplets_sent=droplet_id,
                droplets_received=int(solved_data["droplets_received"]),
                innovative_droplets=int(solved_data["innovative_droplets"]),
                crc_drops=int(solved_data["crc_drops"]),
                elapsed_ms=round(elapsed_ms, 2),
                effective_kbps=round(eff_kbps, 2),
                active_lanes=active_lanes,
                killed_lanes=killed_lanes,
                packet_drop_rate=fault.packet_drop_rate,
                corrupt_lan_noise=fault.corrupt_lan_noise,
                topology_fingerprint=self.env.topology_fingerprint,
                rank_timeline=list(solved_data.get("rank_timeline", [])),
                per_lane_stats=merged_stats,
            )
            return tid, report
        finally:
            ctrl.close()
            for lane in tx_lanes.values():
                lane.close()

    def send_metamorphic(
        self,
        receiver: ChimeraReceiver,
        payload: bytes,
        fault: FaultProfile | None = None,
        timeout_s: float = 12.0,
    ) -> tuple[bytes, TransferReport]:
        """Transmit `payload` strictly via PURE-METAMORPHIC multi-realm RLNC droplets."""
        tid, report = self._send_metamorphic_core(
            payload=payload,
            fault=fault,
            compress=True,
            mode_label="PURE-METAMORPHIC",
            timeout_s=timeout_s,
        )
        recovered = receiver.get_recovered_payload(tid) if report.success else b""
        return recovered, report

    def send_holographic(
        self,
        receiver: ChimeraReceiver,
        payload: bytes,
        fault: FaultProfile | None = None,
        timeout_s: float = 15.0,
    ) -> tuple[bytes, TransferReport]:
        """Transmit bulk OTP-masked 58 KiB superframes over ::1 and key capsule via 7 alien lanes."""
        if self.offer.get("jumbo") is None:
            raise RuntimeError("LO_V6_JUMBO endpoint is unavailable")

        t0 = time.perf_counter()
        holo_tid = self._next_transfer_id()
        waiter = receiver.register_holographic_waiter(holo_tid)

        holo_key = os.urandom(32)
        topo_bytes = bytes.fromhex(self.env.topology_fingerprint)
        stream_seed = hashlib.blake2b(holo_key + topo_bytes, digest_size=32).digest()
        masked_blob = xor_bytes(payload, chaotic_keystream(stream_seed, len(payload)))
        blob_entropy = shannon_entropy(masked_blob)
        expected_sha_bytes = hashlib.sha256(payload).digest()

        capsule = (
            struct.pack("!II", holo_tid, len(payload)) + holo_key + expected_sha_bytes
        )
        assert len(capsule) == 72

        jtx = LoopbackV6JumboLane(ip="::1", session_seed=self.session_seed)
        try:
            chunks = jtx.send_blob(self.offer["jumbo"], holo_tid, masked_blob)
            _, cap_report = self._send_metamorphic_core(
                payload=capsule,
                fault=fault,
                compress=False,
                mode_label="HOLOGRAPHIC-SPLIT",
                timeout_s=timeout_s,
            )
            if not cap_report.success:
                cap_report.payload_bytes = len(payload)
                return b"", cap_report

            if not waiter.wait(timeout=3.0):
                cap_report.success = False
                cap_report.error = "Timed out waiting for holographic blob assembly"
                return b"", cap_report

            recovered, actual_sha, sha_ok = receiver.get_holographic_verification(holo_tid)
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            j_tx_stats = jtx.stats.to_dict()
            j_rx_stats = receiver.get_jumbo_stats()
            j_tx_stats["packets_recv"] = j_rx_stats.get("packets_recv", 0)
            j_tx_stats["droplets_recv"] = j_rx_stats.get("droplets_recv", 0)
            j_tx_stats["killed"] = False
            cap_report.per_lane_stats["LO_V6_JUMBO"] = j_tx_stats

            cap_report.mode = "HOLOGRAPHIC-SPLIT"
            cap_report.payload_bytes = len(payload)
            cap_report.expected_sha256 = expected_sha_bytes.hex()
            cap_report.actual_sha256 = actual_sha
            cap_report.sha256_match = sha_ok
            cap_report.success = sha_ok
            cap_report.elapsed_ms = round(elapsed_ms, 2)
            cap_report.effective_kbps = round(
                (len(payload) * 8.0) / max(elapsed_ms, 0.001), 2
            )
            cap_report.holo_entropy_bits_per_byte = round(blob_entropy, 5)
            cap_report.jumbo_chunks = chunks
            return recovered, cap_report
        finally:
            jtx.close()
