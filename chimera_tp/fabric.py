"""Unified CHIMERA-HYPER v1.0 Auto-Pilot Fabric (Wormhole + DNA Vault + GFNI Wire + Pipe)."""

from __future__ import annotations

import hashlib
import os
import socket
import struct
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .active_pipe import ActivePipeEngine, ActivePipeResult, ComputePlan
from .dna_vault import DnaCodec, DnaStats, DnaVault, pack_directory, unpack_directory
from .hyper_wire import HyperWireReceiver, HyperWireReport, HyperWireSender
from .native import WormholeChannel, cpu_caps, has_native

_BEAM_REQ_HDR = struct.Struct("!4sHH")  # magic="BMQ1", reply_port(u16), est_loss_bps(u16)
_BEAM_PAYLOAD_HDR = struct.Struct("!BBHH")  # kind(1=file,2=dir), reserved, name_len, commit_port


@dataclass
class BeamReport:
    target: str
    kind: str
    raw_bytes: int
    dna_wire_bytes: int
    udp_wire_bytes: int
    reduction_pct: float
    effective_multiplier: float
    elapsed_ms: float
    effective_mbps: float
    dna_stats: dict[str, Any]
    wire_report: dict[str, Any]
    sha256: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class BeamServer:
    """Two-process DNA-Vault + HyperWire file/directory sync receiver."""

    def __init__(
        self,
        bind_ip: str = "127.0.0.1",
        bind_port: int = 0,
        vault_dir: Path | None = None,
        out_dir: Path = Path("chimera_received"),
        est_loss: float = 0.0,
    ) -> None:
        self.bind_ip = bind_ip
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.vault = DnaVault(vault_dir=vault_dir)
        self.codec = DnaCodec()
        self.est_loss = est_loss

        self._ctrl_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._ctrl_sock.bind((bind_ip, bind_port))
        self._ctrl_sock.settimeout(0.05)
        self.ctrl_addr: tuple[str, int] = self._ctrl_sock.getsockname()

        self._rx = HyperWireReceiver(bind_ip=bind_ip, bind_port=0).start()
        self.data_addr: tuple[str, int] = self._rx.addr

        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._vault_cv = threading.Condition(self._lock)
        self._decoding_busy = False
        self._stream_peers: dict[int, str] = {}
        self._completed: list[dict[str, Any]] = []
        self._cv = threading.Condition(self._lock)
        self._ctrl_thread = threading.Thread(target=self._ctrl_loop, daemon=True)
        self._worker_thread = threading.Thread(target=self._rx_wait_loop, daemon=True)
        self._current_stream = 1

    def start(self) -> "BeamServer":
        self._ctrl_thread.start()
        self._worker_thread.start()
        return self

    def _ctrl_loop(self) -> None:
        while not self._stop.is_set():
            try:
                pkt, addr = self._ctrl_sock.recvfrom(4096)
            except (socket.timeout, ConnectionResetError):
                continue
            except OSError:
                break
            if len(pkt) < _BEAM_REQ_HDR.size:
                continue
            magic, reply_port, loss_bps = _BEAM_REQ_HDR.unpack_from(pkt, 0)
            if magic != b"BMQ1":
                continue
            # Ensure previous transfer's DNA decode + vault commit finished before exporting sketch
            deadline = time.perf_counter() + 5.0
            with self._lock:
                while not self._stop.is_set() and time.perf_counter() < deadline:
                    with self._rx._lock:
                        has_queued = bool(self._rx._completed)
                    if not self._decoding_busy and not has_queued:
                        break
                    self._vault_cv.wait(timeout=0.02)
                stream_id = self._current_stream
                self._current_stream = (self._current_stream % 250) + 1
                self._stream_peers[stream_id] = addr[0]
                sketch = self.vault.export_sketch()
            resp_meta = struct.pack("!4sHH", b"BMR1", self.data_addr[1], stream_id)
            try:
                self._ctrl_sock.sendto(resp_meta, addr)
            except OSError:
                pass
            sketch_sender = HyperWireSender(
                (addr[0], reply_port), initial_loss_hint=max(self.est_loss, loss_bps / 10000.0)
            )
            try:
                sketch_sender.send_stream(sketch, stream_id=stream_id, timeout_s=15.0)
            except Exception:
                pass

    def _rx_wait_loop(self) -> None:
        while not self._stop.is_set():
            try:
                sid, payload, _ = self._rx.wait_any(timeout_s=0.1)
            except TimeoutError:
                continue
            except Exception:
                continue
            with self._lock:
                self._decoding_busy = True
            try:
                kind, _, name_len, commit_port = _BEAM_PAYLOAD_HDR.unpack_from(payload, 0)
                rel_name = payload[6 : 6 + name_len].decode("utf-8", errors="replace")
                recipe = payload[6 + name_len :]
                raw, dstats = self.codec.decode_stream(recipe, self.vault)
                self.vault.save()

                files_written: list[str] = []
                if kind == 2:
                    files_written = unpack_directory(
                        raw, self.out_dir / rel_name if rel_name else self.out_dir
                    )
                else:
                    target_file = (self.out_dir / (rel_name or f"beam_{sid}.bin")).resolve()
                    target_file.parent.mkdir(parents=True, exist_ok=True)
                    target_file.write_bytes(raw)
                    files_written = [target_file.name]

                rec = {
                    "stream_id": sid,
                    "kind": "dir" if kind == 2 else "file",
                    "name": rel_name,
                    "raw_bytes": len(raw),
                    "dna_wire_bytes": len(recipe),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "files": files_written,
                    "dna_stats": dstats.to_dict(),
                }
                with self._lock:
                    self._completed.append(rec)
                    self._cv.notify_all()
                    peer_ip = self._stream_peers.pop(sid, self.bind_ip)
                if commit_port:
                    ack = struct.pack("!4sH", b"BMOK", sid)
                    for _ in range(2):
                        try:
                            self._ctrl_sock.sendto(ack, (peer_ip, commit_port))
                        except OSError:
                            pass
            finally:
                with self._lock:
                    self._decoding_busy = False
                    self._vault_cv.notify_all()

    def wait_transfer(self, index: int = 0, timeout_s: float = 25.0) -> dict[str, Any]:
        deadline = time.perf_counter() + timeout_s
        with self._lock:
            while len(self._completed) <= index:
                rem = deadline - time.perf_counter()
                if rem <= 0:
                    raise TimeoutError("Timed out waiting for beam transfer")
                self._cv.wait(timeout=min(rem, 0.05))
            return self._completed[index]

    def close(self) -> None:
        self._stop.set()
        self._ctrl_thread.join(timeout=1.0)
        self._worker_thread.join(timeout=1.0)
        self._rx.close()
        try:
            self._ctrl_sock.close()
        except OSError:
            pass


def beam_send(
    target_ctrl_addr: tuple[str, int],
    source_path: Path,
    vault_dir: Path | None = None,
    est_loss: float = 0.0,
    pace_mbps: float | None = None,
    stream_id: int = 1,
    timeout_s: float = 25.0,
) -> BeamReport:
    """Sync a file or entire directory using Zero-Byte DNA Vault + Silicon GFNI Wire."""
    t0 = time.perf_counter()
    source_path = Path(source_path).resolve()
    if source_path.is_dir():
        kind = 2
        rel_name = ""
        raw = pack_directory(source_path)
    elif source_path.is_file():
        kind = 1
        rel_name = source_path.name
        raw = source_path.read_bytes()
    else:
        raise FileNotFoundError(f"Source path not found: {source_path}")

    # Handshake to fetch receiver's DNA sketch
    sketch_rx = HyperWireReceiver(bind_ip="127.0.0.1", bind_port=0).start()
    ctrl_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    ctrl_sock.settimeout(2.0)
    try:
        try:
            req = _BEAM_REQ_HDR.pack(b"BMQ1", sketch_rx.addr[1], int(est_loss * 10000)) + bytes([stream_id])
            data_port = None
            for _ in range(5):
                ctrl_sock.sendto(req, target_ctrl_addr)
                try:
                    resp, _ = ctrl_sock.recvfrom(4096)
                    if len(resp) >= 8 and resp[:4] == b"BMR1":
                        _, data_port, remote_sid = struct.unpack("!4sHH", resp[:8])
                        stream_id = remote_sid
                        break
                except socket.timeout:
                    continue
            if data_port is None:
                raise TimeoutError(f"BeamServer unreachable at {target_ctrl_addr}")

            commit_port = ctrl_sock.getsockname()[1]
            sketch_bytes, _ = sketch_rx.wait_stream(stream_id, timeout_s=min(10.0, timeout_s))
        finally:
            sketch_rx.close()

        cids, sf_map = DnaVault.import_sketch(sketch_bytes)
        tx_vault = DnaVault(vault_dir=vault_dir)
        codec = DnaCodec()
        recipe, dstats = codec.encode_stream(raw, cids, sf_map, tx_vault)
        tx_vault.save()

        name_b = rel_name.encode("utf-8")
        payload = _BEAM_PAYLOAD_HDR.pack(kind, 0, len(name_b), commit_port) + name_b + recipe
        sender = HyperWireSender(
            (target_ctrl_addr[0], data_port),
            pace_mbps=pace_mbps,
            initial_loss_hint=est_loss,
        )
        wrep = sender.send_stream(payload, stream_id=stream_id, timeout_s=timeout_s)

        # Wait briefly for receiver's disk unpack & DNA vault commit ACK
        ctrl_sock.settimeout(0.5)
        ack_deadline = time.perf_counter() + min(10.0, timeout_s)
        while time.perf_counter() < ack_deadline:
            try:
                pkt, _ = ctrl_sock.recvfrom(1024)
                if len(pkt) >= 6 and pkt[:4] == b"BMOK":
                    (ack_sid,) = struct.unpack_from("!H", pkt, 4)
                    if ack_sid == stream_id:
                        break
            except (socket.timeout, OSError):
                break
    finally:
        ctrl_sock.close()
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    eff_mbps = (len(raw) * 8.0) / max(elapsed_ms * 1000.0, 0.001)
    return BeamReport(
        target=f"{target_ctrl_addr[0]}:{target_ctrl_addr[1]}",
        kind="dir" if kind == 2 else "file",
        raw_bytes=len(raw),
        dna_wire_bytes=len(recipe),
        udp_wire_bytes=wrep.wire_bytes_sent,
        reduction_pct=round(dstats.reduction_pct, 2),
        effective_multiplier=round(dstats.effective_multiplier, 2),
        elapsed_ms=round(elapsed_ms, 2),
        effective_mbps=round(eff_mbps, 3),
        dna_stats=dstats.to_dict(),
        wire_report=wrep.to_dict(),
        sha256=hashlib.sha256(raw).hexdigest(),
    )


class ChimeraFabric:
    """Unified CHIMERA-HYPER v1.0 Auto-Pilot selecting Wormhole / DNA Beam / Active Pipe."""

    def __init__(self, vault_dir: Path | None = None) -> None:
        self.vault_dir = vault_dir
        self.tx_vault = DnaVault(vault_dir=vault_dir)
        self.rx_vault = DnaVault()
        self.codec = DnaCodec()
        self.pipe = ActivePipeEngine()

    @staticmethod
    def capabilities() -> dict[str, Any]:
        return {
            "version": "1.0.0",
            "hardware": cpu_caps(),
            "wormhole_available": has_native() and os.name == "nt",
            "modes": ["wormhole-shm", "dna-beam", "gfni-wire", "hedged-rpc", "active-pipe", "exotic-v05"],
        }

    def send_smart(
        self,
        data: bytes,
        peer_host: str = "127.0.0.1",
        est_loss: float = 0.0,
        force_wire: bool = False,
    ) -> tuple[bytes, dict[str, Any]]:
        """Automatically use Wormhole SHM for local IPC or DNA+HyperWire for network transport."""
        is_local = peer_host in ("127.0.0.1", "::1", "localhost")
        if is_local and not force_wire and has_native() and os.name == "nt" and len(data) >= 65536:
            name = f"SMART_{os.getpid()}_{time.monotonic_ns()}"
            t0 = time.perf_counter()
            out_holder: list[bytes] = []
            with WormholeChannel.create(name, capacity_mb=8) as tx_wh:
                def reader_fn() -> None:
                    with WormholeChannel.open(name) as rx_wh:
                        out_holder.append(rx_wh.read_all())
                th = threading.Thread(target=reader_fn, daemon=True)
                th.start()
                tx_wh.write_all(data)
                tx_wh.mark_eof()
                th.join(timeout=15.0)
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            rec = out_holder[0] if out_holder else b""
            return rec, {
                "transport": "WORMHOLE_SHM",
                "bytes": len(data),
                "elapsed_ms": round(elapsed_ms, 2),
                "gbps": round((len(data) * 8.0) / max(elapsed_ms * 1e6, 0.001), 3),
                "sha256_match": rec == data,
            }

        cids = self.rx_vault.known_cids()
        sf_map = dict(self.rx_vault._sf_index)
        recipe, dstats = self.codec.encode_stream(data, cids, sf_map, self.tx_vault)
        rx = HyperWireReceiver(bind_ip=peer_host).start()
        try:
            sender = HyperWireSender(rx.addr, initial_loss_hint=est_loss)
            wrep = sender.send_stream(recipe, stream_id=1)
            rec_recipe, _ = rx.wait_stream(1)
            decoded, _ = self.codec.decode_stream(rec_recipe, self.rx_vault)
            return decoded, {
                "transport": "DNA_PLUS_GFNI_WIRE",
                "dna": dstats.to_dict(),
                "wire": wrep.to_dict(),
                "sha256_match": decoded == data,
            }
        finally:
            rx.close()

    def query(self, data: bytes, plan: ComputePlan, bandwidth_mbps: float = 100.0) -> ActivePipeResult:
        return self.pipe.run_query(data, plan, bandwidth_mbps=bandwidth_mbps)
