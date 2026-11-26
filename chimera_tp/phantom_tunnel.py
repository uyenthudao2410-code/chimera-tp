"""CHIMERA v5.0 Breakthrough #1: PHANTOM-5MS Persistent Authenticated P2P UDP Tunnel."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import select
import socket
import struct
import threading
import time
import urllib.request
import zlib
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

from .hyper_wire import _disable_connreset
from .native import chacha20_xor, lz4_compress, lz4_decompress
from .nat_buster import (
    DEFAULT_STUN_SERVERS,
    _MAGIC_ACK,
    _MAGIC_PUNCH,
    _build_spray_ports,
    _validate_public_or_loopback_ip,
    discover_nat_profile,
    stun_query,
)

# Authenticated outer envelope: magic(4s="PH5E"), session_id(I), dir_and_seq_nonce(8s)
_ENV_HDR = struct.Struct("!4sI8s")
_ENV_MAGIC = b"PH5E"
_ENV_MAGIC_V9 = b"PH9N"
# Fast v9 outer header: magic(4s="PH9N"), session_id(I), flags(B: bit0=LZ4), dir_and_seq_nonce(8s)
_PH9_HDR = struct.Struct("!4sIB8s")
_PH9_FLAG_LZ4 = 1
_TAG_LEN = 16

# Reliable multiplexed inner frame header (12 bytes):
# ptype(B), flags(B), conn_id(I), seq(I), aux(H)
_PH_HDR = struct.Struct("!BBIIH")
_P_OPEN = 1
_P_DATA = 2
_P_FIN = 3
_P_ACK = 4
_P_NACK = 5
_P_CLOSE = 6
_P_PING = 7
_P_PONG = 8
_REV_CONN_MASK = 0x80000000

_CHUNK_MAX = 1080  # Fits comfortably inside 1280 B overlay / PPPoE MTUs with headers


def _derive_keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    if length <= 0:
        return b""
    out = bytearray()
    blk = 0
    while len(out) < length:
        pers = nonce + struct.pack("!I", blk)
        out.extend(hashlib.blake2b(key=key, person=pers, digest_size=64).digest())
        blk += 1
    return bytes(out[:length])


def _xor_bytes(a: bytes, b: bytes) -> bytes:
    n = len(a)
    if n == 0:
        return b""
    return (int.from_bytes(a, "little") ^ int.from_bytes(b[:n], "little")).to_bytes(n, "little")


def seal_packet(session_key: bytes, session_id: int, nonce: bytes, plaintext: bytes) -> bytes:
    """Encrypt-then-MAC packet authentication using keyed BLAKE2b stream + BLAKE2s-128 MAC."""
    hdr = _ENV_HDR.pack(_ENV_MAGIC, session_id & 0xFFFFFFFF, nonce)
    ks = _derive_keystream(session_key, nonce, len(plaintext))
    ct = _xor_bytes(plaintext, ks)
    tag = hashlib.blake2s(hdr + ct, key=session_key, digest_size=_TAG_LEN).digest()
    return hdr + ct + tag


def open_packet(session_key: bytes, packet: bytes) -> tuple[int, bytes, bytes] | None:
    """Verify BLAKE2s-128 MAC cleanly and decrypt PH5E envelope, or return None."""
    min_len = _ENV_HDR.size + _TAG_LEN
    if len(packet) < min_len:
        return None
    magic, sid, nonce = _ENV_HDR.unpack_from(packet, 0)
    if magic != _ENV_MAGIC:
        return None
    ct_and_hdr = packet[:-_TAG_LEN]
    tag = packet[-_TAG_LEN:]
    expected_tag = hashlib.blake2s(ct_and_hdr, key=session_key, digest_size=_TAG_LEN).digest()
    if not hmac.compare_digest(tag, expected_tag):
        return None
    ct = packet[_ENV_HDR.size : -_TAG_LEN]
    ks = _derive_keystream(session_key, nonce, len(ct))
    return sid, nonce, _xor_bytes(ct, ks)


def seal_packet_fast(
    session_key: bytes,
    session_id: int,
    nonce: bytes,
    plaintext: bytes,
    compress: bool = True,
) -> bytes:
    """CHIMERA v9 PH9N envelope: optional native LZ4 + RFC8439 ChaCha20 C-ABI + BLAKE2s-128 MAC."""
    body = plaintext
    flags = 0
    if compress and len(plaintext) >= 96:
        comp = lz4_compress(plaintext)
        if 0 < len(comp) < len(plaintext):
            body = comp
            flags = _PH9_FLAG_LZ4
    n8 = nonce[:8].ljust(8, b"\x00")
    hdr = _PH9_HDR.pack(_ENV_MAGIC_V9, session_id & 0xFFFFFFFF, flags, n8)
    k32 = session_key[:32] if len(session_key) >= 32 else hashlib.sha256(session_key).digest()
    ct = chacha20_xor(body, k32, _ENV_MAGIC_V9 + n8, counter=1)
    tag = hashlib.blake2s(hdr + ct, key=session_key, digest_size=_TAG_LEN).digest()
    return hdr + ct + tag


def open_packet_fast(session_key: bytes, packet: bytes) -> tuple[int, bytes, bytes] | None:
    """Verify BLAKE2s-128 MAC, decrypt PH9N ChaCha20 payload in 1 C-ABI call, and optional LZ4 decode."""
    min_len = _PH9_HDR.size + _TAG_LEN
    if len(packet) < min_len:
        return None
    magic, sid, flags, n8 = _PH9_HDR.unpack_from(packet, 0)
    if magic != _ENV_MAGIC_V9:
        return None
    ct_and_hdr = packet[:-_TAG_LEN]
    tag = packet[-_TAG_LEN:]
    expected_tag = hashlib.blake2s(ct_and_hdr, key=session_key, digest_size=_TAG_LEN).digest()
    if not hmac.compare_digest(tag, expected_tag):
        return None
    ct = packet[_PH9_HDR.size : -_TAG_LEN]
    k32 = session_key[:32] if len(session_key) >= 32 else hashlib.sha256(session_key).digest()
    pt = chacha20_xor(ct, k32, _ENV_MAGIC_V9 + n8, counter=1)
    if flags & _PH9_FLAG_LZ4:
        try:
            pt = lz4_decompress(pt)
        except ValueError:
            return None
    return sid, n8, pt


def open_any_packet(session_key: bytes, packet: bytes) -> tuple[int, bytes, bytes] | None:
    """Decode either v9 native PH9N or legacy v5 PH5E authenticated packet seamlessly."""
    if len(packet) >= 4 and packet[:4] == _ENV_MAGIC_V9:
        return open_packet_fast(session_key, packet)
    return open_packet(session_key, packet)


def _pack_inner(ptype: int, flags: int, conn_id: int, seq: int, aux: int = 0, body: bytes = b"") -> bytes:
    return _PH_HDR.pack(ptype & 0xFF, flags & 0xFF, conn_id & 0xFFFFFFFF, seq & 0xFFFFFFFF, aux & 0xFFFF) + body


def _unpack_inner(data: bytes) -> tuple[int, int, int, int, int, bytes] | None:
    if len(data) < _PH_HDR.size:
        return None
    ptype, flags, conn_id, seq, aux = _PH_HDR.unpack_from(data, 0)
    return ptype, flags, conn_id, seq, aux, data[_PH_HDR.size :]


@dataclass
class _TunnelStream:
    conn_id: int
    tcp_sock: socket.socket
    open_acked: bool = False
    open_target_port: int = 0
    last_open_tx: float = 0.0
    next_tx_seq: int = 0
    tx_fin_seq: int | None = None
    tx_buffer: dict[int, tuple[int, bytes, float]] = field(default_factory=dict)
    rx_next_seq: int = 0
    rx_fin_seq: int | None = None
    rx_chunks: dict[int, bytes] = field(default_factory=dict)
    last_nack_at: float = 0.0
    closed: bool = False
    tx_eof_local: bool = False
    rx_eof_sent: bool = False
    prefer_v9: bool = False


class _TunnelEndpointMixin:
    """Shared multiplexed TCP<->UDP reliability & encryption engine for Phantom Server/Client."""

    def _init_mux(self, direction_bit: int, use_fast_wire: bool = False) -> None:
        self._dir_bit = direction_bit & 1
        self._use_fast_wire = bool(use_fast_wire)
        self._tx_counter = 0
        self._mux_lock = threading.Lock()
        self._conns: dict[int, _TunnelStream] = {}
        self._bytes_tx = 0
        self._bytes_rx = 0

    def _send_encrypted(
        self,
        sock: socket.socket,
        addr: tuple[str, int],
        key: bytes,
        sid: int,
        inner: bytes,
        fast: bool | None = None,
    ) -> None:
        with self._mux_lock:
            self._tx_counter += 1
            val = (self._dir_bit << 63) | (self._tx_counter & ((1 << 63) - 1))
            nonce = struct.pack("!Q", val)
        use_fast = self._use_fast_wire if fast is None else bool(fast)
        if use_fast:
            wire = seal_packet_fast(key, sid, nonce, inner, compress=(len(inner) >= 96 and inner[0] != _P_DATA))
        else:
            wire = seal_packet(key, sid, nonce, inner)
        try:
            sock.sendto(wire, addr)
            with self._mux_lock:
                self._bytes_tx += len(wire)
        except OSError:
            pass

    def _pump_tcp_stream(
        self,
        stream: _TunnelStream,
        get_transport: Any,
        stop_ev: threading.Event,
    ) -> None:
        try:
            stream.tcp_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            pass
        stream.tcp_sock.settimeout(0.05)
        try:
            while not stop_ev.is_set() and not stream.closed:
                with self._mux_lock:
                    inflight = len(stream.tx_buffer)
                if inflight > 128:
                    time.sleep(0.002)
                    continue
                try:
                    data = stream.tcp_sock.recv(32768)
                except socket.timeout:
                    continue
                except OSError:
                    break
                if not data:
                    break
                sock, addr, key, sid = get_transport()
                if sock is None or addr is None:
                    break
                mv = memoryview(data)
                for off in range(0, len(data), _CHUNK_MAX):
                    piece = bytes(mv[off : off + _CHUNK_MAX])
                    flags = 0
                    wire_piece = piece
                    if len(piece) >= 192:
                        comp = zlib.compress(piece, 1)
                        if len(comp) < int(len(piece) * 0.88):
                            flags = 1
                            wire_piece = comp
                    with self._mux_lock:
                        seq = stream.next_tx_seq
                        stream.next_tx_seq += 1
                        stream.tx_buffer[seq] = (flags, wire_piece, time.perf_counter())
                    pkt = _pack_inner(_P_DATA, flags, stream.conn_id, seq, 0, wire_piece)
                    self._send_encrypted(sock, addr, key, sid, pkt, fast=stream.prefer_v9 or None)
        finally:
            with self._mux_lock:
                stream.tx_eof_local = True
                fin_seq = stream.next_tx_seq
                stream.tx_fin_seq = fin_seq
            sock, addr, key, sid = get_transport()
            if sock is not None and addr is not None:
                pkt = _pack_inner(_P_FIN, 0, stream.conn_id, fin_seq, 0, b"")
                self._send_encrypted(sock, addr, key, sid, pkt, fast=stream.prefer_v9 or None)

    def _flush_rx_in_order(self, stream: _TunnelStream) -> None:
        while stream.rx_next_seq in stream.rx_chunks:
            chunk = stream.rx_chunks.pop(stream.rx_next_seq)
            if chunk:
                try:
                    stream.tcp_sock.sendall(chunk)
                except OSError:
                    stream.closed = True
                    return
            stream.rx_next_seq += 1
        if stream.rx_fin_seq is not None and stream.rx_next_seq >= stream.rx_fin_seq and not stream.rx_eof_sent:
            stream.rx_eof_sent = True
            try:
                stream.tcp_sock.shutdown(socket.SHUT_WR)
            except OSError:
                pass
            if stream.tx_eof_local and not stream.tx_buffer:
                stream.closed = True
                try:
                    stream.tcp_sock.close()
                except OSError:
                    pass

    def _handle_stream_frame(
        self,
        stream: _TunnelStream,
        ptype: int,
        flags: int,
        seq: int,
        body: bytes,
        sock: socket.socket,
        addr: tuple[str, int],
        key: bytes,
        sid: int,
    ) -> None:
        if ptype == _P_DATA:
            try:
                plain = zlib.decompress(body) if (flags & 1) else body
            except zlib.error:
                return
            with self._mux_lock:
                if seq >= stream.rx_next_seq and seq not in stream.rx_chunks:
                    stream.rx_chunks[seq] = plain
                self._flush_rx_in_order(stream)
                ack_seq = stream.rx_next_seq
            self._send_encrypted(sock, addr, key, sid, _pack_inner(_P_ACK, 0, stream.conn_id, ack_seq), fast=stream.prefer_v9 or None)
        elif ptype == _P_FIN:
            with self._mux_lock:
                stream.rx_fin_seq = seq
                self._flush_rx_in_order(stream)
                ack_seq = stream.rx_next_seq
            self._send_encrypted(sock, addr, key, sid, _pack_inner(_P_ACK, 0, stream.conn_id, ack_seq), fast=stream.prefer_v9 or None)
        elif ptype == _P_ACK:
            with self._mux_lock:
                stream.open_acked = True
                for s in [k_s for k_s in stream.tx_buffer if k_s < seq]:
                    del stream.tx_buffer[s]
                if stream.rx_eof_sent and stream.tx_eof_local and not stream.tx_buffer:
                    stream.closed = True
                    try:
                        stream.tcp_sock.close()
                    except OSError:
                        pass
        elif ptype == _P_NACK:
            count = len(body) // 4
            if count <= 0:
                return
            miss = struct.unpack_from(f"<{count}I", body, 0)
            to_res: list[tuple[int, int, bytes]] = []
            now = time.perf_counter()
            with self._mux_lock:
                for s in [k_s for k_s in stream.tx_buffer if k_s < seq]:
                    del stream.tx_buffer[s]
                for m in miss:
                    ent = stream.tx_buffer.get(m)
                    if ent is not None:
                        fl, piece, _ = ent
                        stream.tx_buffer[m] = (fl, piece, now)
                        to_res.append((fl, m, piece))
            for fl, m, piece in to_res:
                self._send_encrypted(sock, addr, key, sid, _pack_inner(_P_DATA, fl, stream.conn_id, m, 0, piece))
        elif ptype == _P_CLOSE:
            stream.closed = True
            try:
                stream.tcp_sock.close()
            except OSError:
                pass

    def _retransmit_pending(
        self,
        conns: dict[int, _TunnelStream],
        sock: socket.socket | None,
        addr: tuple[str, int] | None,
        key: bytes,
        sid: int,
    ) -> None:
        if sock is None or addr is None:
            return
        now = time.perf_counter()
        resends: list[bytes] = []
        with self._mux_lock:
            dead_ids: list[int] = []
            for cid, c in conns.items():
                if c.closed:
                    dead_ids.append(cid)
                    continue
                if not c.open_acked and c.open_target_port > 0 and (now - c.last_open_tx) >= 0.08:
                    c.last_open_tx = now
                    resends.append(_pack_inner(_P_OPEN, 0, cid, 0, c.open_target_port))
                for s, (fl, piece, last_tx) in list(c.tx_buffer.items()):
                    rto = 0.04 if len(piece) <= 256 else 0.09
                    if (now - last_tx) >= rto:
                        c.tx_buffer[s] = (fl, piece, now)
                        resends.append(_pack_inner(_P_DATA, fl, cid, s, 0, piece))
                if c.rx_chunks:
                    max_rx = max(c.rx_chunks.keys())
                    missing = [s for s in range(c.rx_next_seq, min(max_rx, c.rx_next_seq + 32)) if s not in c.rx_chunks]
                    if missing and (now - c.last_nack_at) >= 0.02:
                        c.last_nack_at = now
                        nbody = struct.pack(f"<{len(missing)}I", *missing)
                        resends.append(_pack_inner(_P_NACK, 0, cid, c.rx_next_seq, len(missing), nbody))
                elif c.rx_fin_seq is not None and c.rx_next_seq < c.rx_fin_seq and (now - c.last_nack_at) >= 0.02:
                    c.last_nack_at = now
                    missing = list(range(c.rx_next_seq, min(c.rx_fin_seq, c.rx_next_seq + 32)))
                    nbody = struct.pack(f"<{len(missing)}I", *missing)
                    resends.append(_pack_inner(_P_NACK, 0, cid, c.rx_next_seq, len(missing), nbody))
            for cid in dead_ids:
                conns.pop(cid, None)
        for inner in resends:
            self._send_encrypted(sock, addr, key, sid, inner)


@dataclass
class _ServerSession:
    session_id: int
    key: bytes
    token_bytes: bytes
    punched: bool = False
    sock: socket.socket | None = None
    peer_udp: tuple[str, int] | None = None
    last_rx: float = field(default_factory=time.monotonic)
    conns: dict[int, _TunnelStream] = field(default_factory=dict)
    prefer_v9: bool = False


class PhantomTunnelServer(_TunnelEndpointMixin):
    """Server-side persistent NAT-punched encrypted UDP tunnel forwarding into localhost TCP."""

    def __init__(
        self,
        fallback_port: int = 9710,
        allowed_forward_ports: list[int] | None = None,
        reverse_forwards: dict[int, int] | None = None,
        reverse_listen_host: str = "127.0.0.1",
    ) -> None:
        self._init_mux(direction_bit=0)
        self.fallback_port = int(fallback_port)
        self.allowed_forward_ports: set[int] = set(
            allowed_forward_ports if allowed_forward_ports is not None else [22, 8787, 9780, 12504]
        )
        self.reverse_forwards: dict[int, int] = dict(reverse_forwards or {})
        self.reverse_listen_host = str(reverse_listen_host or "127.0.0.1")
        self._stop = threading.Event()
        self._sess_lock = threading.Lock()
        self._sessions: OrderedDict[int, _ServerSession] = OrderedDict()
        self._fallback_sock: socket.socket | None = None
        self._rev_srvs: list[tuple[int, int, socket.socket]] = []
        self.reverse_bound_ports: dict[int, int] = {}
        self._next_rev_cid = 1
        self._threads: list[threading.Thread] = []
        self.fallback_addr: tuple[str, int] = ("0.0.0.0", self.fallback_port)

    def start(self) -> "PhantomTunnelServer":
        if self.fallback_port >= 0:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            _disable_connreset(s)
            try:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
                s.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4 * 1024 * 1024)
            except OSError:
                pass
            s.bind(("0.0.0.0", self.fallback_port))
            s.setblocking(False)
            self._fallback_sock = s
            self.fallback_addr = (str(s.getsockname()[0]), int(s.getsockname()[1]))
            self.fallback_port = self.fallback_addr[1]
            t_fb = threading.Thread(target=self._fallback_loop, daemon=True)
            t_fb.start()
            self._threads.append(t_fb)
        for loc_p, rem_p in self.reverse_forwards.items():
            srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            srv.bind((self.reverse_listen_host, int(loc_p)))
            srv.listen(32)
            srv.settimeout(0.25)
            actual_p = int(srv.getsockname()[1])
            self.reverse_bound_ports[int(rem_p)] = actual_p
            self._rev_srvs.append((actual_p, int(rem_p), srv))
            t_rev = threading.Thread(target=self._reverse_accept_loop, args=(srv, int(rem_p)), daemon=True)
            t_rev.start()
            self._threads.append(t_rev)
        return self

    def _active_reverse_transport(
        self,
    ) -> tuple[socket.socket | None, tuple[str, int] | None, bytes, int, _ServerSession | None]:
        with self._sess_lock:
            cands = list(reversed(self._sessions.values()))
            for s in cands:
                if s.sock is not None and s.peer_udp is not None and s.punched:
                    return s.sock, s.peer_udp, s.key, s.session_id, s
            for s in cands:
                sock = s.sock or self._fallback_sock
                if sock is not None and s.peer_udp is not None:
                    return sock, s.peer_udp, s.key, s.session_id, s
        return None, None, b"", 0, None

    def _reverse_accept_loop(self, srv: socket.socket, remote_port: int) -> None:
        while not self._stop.is_set():
            try:
                cli, _ = srv.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                cli.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            except OSError:
                pass
            sock, addr, key, sid, sess = self._active_reverse_transport()
            if sock is None or addr is None or sess is None:
                try:
                    cli.close()
                except OSError:
                    pass
                continue
            with self._mux_lock:
                cid = (self._next_rev_cid & 0x7FFFFFFF) | _REV_CONN_MASK
                self._next_rev_cid += 1
                stream = _TunnelStream(
                    conn_id=cid,
                    tcp_sock=cli,
                    open_acked=False,
                    open_target_port=remote_port,
                    last_open_tx=time.perf_counter(),
                    prefer_v9=bool(sess.prefer_v9),
                )
                sess.conns[cid] = stream
            self._send_encrypted(
                sock,
                addr,
                key,
                sid,
                _pack_inner(_P_OPEN, 0, cid, 0, remote_port),
                fast=bool(sess.prefer_v9),
            )
            threading.Thread(
                target=self._pump_tcp_stream,
                args=(stream, lambda s_obj=sess: (s_obj.sock or self._fallback_sock, s_obj.peer_udp, s_obj.key, s_obj.session_id), self._stop),
                daemon=True,
            ).start()

    def accept_offer(self, offer: dict[str, Any]) -> dict[str, Any]:
        token = str(offer.get("token", "")).strip().lower()
        if len(token) != 16:
            raise ValueError("Invalid token")
        token_bytes = bytes.fromhex(token)
        sid = int(offer["session_id"]) & 0xFFFFFFFF
        key = base64.b64decode(str(offer["session_key_b64"]).encode("ascii"))
        if len(key) < 16:
            raise ValueError("Session key too short")

        local_tm = bool(offer.get("local_test_mode", False))
        peer_ip = _validate_public_or_loopback_ip(str(offer.get("peer_ip", "")), allow_loopback=local_tm)
        peer_port = int(offer.get("peer_stun_port", 0))
        peer_delta = int(offer.get("peer_port_delta", 0))
        spray_count = int(offer.get("spray_count", 900))
        punch_timeout = max(0.5, min(6.0, float(offer.get("timeout_s", 3.5))))

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        _disable_connreset(sock)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4 * 1024 * 1024)
        except OSError:
            pass
        try:
            sock.bind(("0.0.0.0", 0))
            local_port = int(sock.getsockname()[1])
            if local_tm:
                pub_ip, pub_port, nat_type = "127.0.0.1", local_port, "LOCAL_LOOPBACK"
            else:
                hits = []
                for srv in DEFAULT_STUN_SERVERS:
                    h = stun_query(sock, srv, timeout_s=1.5)
                    if h is not None:
                        hits.append(h)
                    if len(hits) >= 2:
                        break
                if not hits:
                    raise RuntimeError("Responder STUN discovery failed")
                pub_ip, pub_port = hits[0][0], hits[0][1]
                nat_type = (
                    "SYMMETRIC"
                    if len(hits) >= 2 and (hits[0][0] != hits[1][0] or hits[0][1] != hits[1][1])
                    else "EASY"
                )
            sock.setblocking(False)
        except Exception:
            sock.close()
            raise

        sess = _ServerSession(session_id=sid, key=key, token_bytes=token_bytes, sock=sock)
        with self._sess_lock:
            for old_sid, old in list(self._sessions.items()):
                if len(self._sessions) >= 4:
                    self._close_session_obj(old)
                    self._sessions.pop(old_sid, None)
            self._sessions[sid] = sess
            self._sessions.move_to_end(sid)

        ports = _build_spray_ports(peer_port, peer_delta, spray_count, local_test_mode=local_tm)
        th = threading.Thread(
            target=self._run_direct_session,
            args=(sess, peer_ip, ports, punch_timeout),
            daemon=True,
        )
        th.start()
        self._threads.append(th)

        return {
            "ok": True,
            "session_id": sid,
            "responder_pub_ip": pub_ip,
            "responder_pub_port": pub_port,
            "responder_nat_type": nat_type,
            "fallback_port": self.fallback_port,
            "local_port": local_port,
        }

    def _close_session_obj(self, sess: _ServerSession) -> None:
        if sess.sock is not None:
            try:
                sess.sock.close()
            except OSError:
                pass
            sess.sock = None
        for c in list(sess.conns.values()):
            c.closed = True
            try:
                c.tcp_sock.close()
            except OSError:
                pass
        sess.conns.clear()

    def _dispatch_inner_server(
        self,
        sess: _ServerSession,
        sock: socket.socket,
        src: tuple[str, int],
        inner: bytes,
        prefer_v9: bool = False,
    ) -> None:
        parsed = _unpack_inner(inner)
        if parsed is None:
            return
        ptype, flags, conn_id, seq, aux, body = parsed
        sess.last_rx = time.monotonic()
        sess.peer_udp = src
        if prefer_v9:
            sess.prefer_v9 = True
        use_fast = sess.prefer_v9

        if ptype == _P_PING:
            self._send_encrypted(sock, src, sess.key, sess.session_id, _pack_inner(_P_PONG, 0, 0, seq, 0, body), fast=use_fast)
            return
        if ptype == _P_PONG:
            return

        if ptype == _P_OPEN:
            target_port = int(aux)
            with self._mux_lock:
                existing = sess.conns.get(conn_id)
            if existing is not None:
                self._send_encrypted(sock, src, sess.key, sess.session_id, _pack_inner(_P_ACK, 0, conn_id, 0), fast=use_fast)
                return
            if target_port not in self.allowed_forward_ports:
                self._send_encrypted(sock, src, sess.key, sess.session_id, _pack_inner(_P_CLOSE, 0, conn_id, 0), fast=use_fast)
                return
            tcp_s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                tcp_s.settimeout(4.0)
                tcp_s.connect(("127.0.0.1", target_port))
            except OSError:
                tcp_s.close()
                self._send_encrypted(sock, src, sess.key, sess.session_id, _pack_inner(_P_CLOSE, 0, conn_id, 0), fast=use_fast)
                return
            stream = _TunnelStream(conn_id=conn_id, tcp_sock=tcp_s, open_acked=True, open_target_port=target_port, prefer_v9=use_fast)
            with self._mux_lock:
                sess.conns[conn_id] = stream
            self._send_encrypted(sock, src, sess.key, sess.session_id, _pack_inner(_P_ACK, 0, conn_id, 0), fast=use_fast)
            threading.Thread(
                target=self._pump_tcp_stream,
                args=(stream, lambda: (sess.sock or self._fallback_sock, sess.peer_udp, sess.key, sess.session_id), self._stop),
                daemon=True,
            ).start()
            return

        with self._mux_lock:
            stream = sess.conns.get(conn_id)
        if stream is None:
            return
        stream.prefer_v9 = stream.prefer_v9 or use_fast
        self._handle_stream_frame(stream, ptype, flags, seq, body, sock, src, sess.key, sess.session_id)

    def _run_direct_session(
        self,
        sess: _ServerSession,
        peer_ip: str,
        ports: list[int],
        punch_timeout_s: float,
    ) -> None:
        sock = sess.sock
        if sock is None:
            return
        punch_pkt = _MAGIC_PUNCH + sess.token_bytes
        ack_pkt = _MAGIC_ACK + sess.token_bytes
        punch_deadline = time.monotonic() + punch_timeout_s
        idx = 0
        n_ports = len(ports)

        try:
            # Phase 1: Birthday-Paradox hole-punch until first encrypted frame OR CHNP1
            while not self._stop.is_set() and not sess.punched and time.monotonic() < punch_deadline:
                if idx < n_ports * 2:
                    batch_end = min(idx + 32, n_ports * 2)
                    while idx < batch_end:
                        try:
                            sock.sendto(punch_pkt, (peer_ip, ports[idx % n_ports]))
                        except OSError:
                            pass
                        idx += 1
                r, _, _ = select.select([sock], [], [], 0.01)
                if not r:
                    continue
                for _ in range(64):
                    try:
                        pkt, src = sock.recvfrom(65535)
                    except (BlockingIOError, ConnectionResetError, OSError):
                        break
                    src_addr = (src[0], int(src[1]))
                    if len(pkt) >= 13 and pkt[:5] in (_MAGIC_PUNCH, _MAGIC_ACK) and pkt[5:13] == sess.token_bytes:
                        sess.punched = True
                        sess.peer_udp = src_addr
                        sess.last_rx = time.monotonic()
                        for _ in range(3):
                            try:
                                sock.sendto(ack_pkt, src_addr)
                            except OSError:
                                pass
                        break
                    dec = open_any_packet(sess.key, pkt)
                    if dec is not None and dec[0] == sess.session_id:
                        sess.punched = True
                        sess.peer_udp = src_addr
                        self._dispatch_inner_server(sess, sock, src_addr, dec[2], prefer_v9=(pkt[:4] == _ENV_MAGIC_V9))
                        break

            if not sess.punched:
                # Fallback path will handle packets on self._fallback_sock
                try:
                    sock.close()
                except OSError:
                    pass
                sess.sock = None
                return

            # Phase 2: Persistent keepalive & encrypted multiplexing loop on punched socket
            while not self._stop.is_set() and sess.sock is sock:
                if (time.monotonic() - sess.last_rx) > 120.0 and not sess.conns:
                    break
                has_conns = bool(sess.conns)
                r, _, _ = select.select([sock], [], [], 0.008 if has_conns else 0.25)
                if r:
                    for _ in range(128):
                        try:
                            pkt, src = sock.recvfrom(65535)
                        except (BlockingIOError, ConnectionResetError, OSError):
                            break
                        with self._mux_lock:
                            self._bytes_rx += len(pkt)
                        src_addr = (src[0], int(src[1]))
                        if len(pkt) >= 13 and pkt[:5] == _MAGIC_PUNCH and pkt[5:13] == sess.token_bytes:
                            sess.peer_udp = src_addr
                            try:
                                sock.sendto(ack_pkt, src_addr)
                            except OSError:
                                pass
                            continue
                        dec = open_any_packet(sess.key, pkt)
                        if dec is not None and dec[0] == sess.session_id:
                            self._dispatch_inner_server(sess, sock, src_addr, dec[2], prefer_v9=(pkt[:4] == _ENV_MAGIC_V9))
                if sess.conns and sess.peer_udp is not None:
                    self._retransmit_pending(sess.conns, sock, sess.peer_udp, sess.key, sess.session_id)
        finally:
            if sess.sock is sock:
                with self._sess_lock:
                    self._close_session_obj(sess)
                    self._sessions.pop(sess.session_id, None)

    def _fallback_loop(self) -> None:
        sock = self._fallback_sock
        if sock is None:
            return
        while not self._stop.is_set():
            has_fb = False
            with self._sess_lock:
                has_fb = any(s.sock is None and bool(s.conns) for s in self._sessions.values())
            try:
                r, _, _ = select.select([sock], [], [], 0.008 if has_fb else 0.25)
            except (OSError, ValueError):
                break
            if r:
                for _ in range(128):
                    try:
                        pkt, src = sock.recvfrom(65535)
                    except (BlockingIOError, ConnectionResetError, OSError):
                        break
                    if len(pkt) < _ENV_HDR.size + _TAG_LEN:
                        continue
                    magic, sid, _ = _ENV_HDR.unpack_from(pkt, 0)
                    if magic not in (_ENV_MAGIC, _ENV_MAGIC_V9):
                        continue
                    with self._sess_lock:
                        sess = self._sessions.get(sid)
                    if sess is None:
                        continue
                    dec = open_any_packet(sess.key, pkt)
                    if dec is not None:
                        self._dispatch_inner_server(sess, sock, (src[0], int(src[1])), dec[2], prefer_v9=(magic == _ENV_MAGIC_V9))
            with self._sess_lock:
                fb_list = [s for s in self._sessions.values() if s.sock is None and s.peer_udp is not None and s.conns]
            for s in fb_list:
                self._retransmit_pending(s.conns, sock, s.peer_udp, s.key, s.session_id)

    def stats(self) -> dict[str, Any]:
        with self._sess_lock:
            active = [
                {
                    "session_id": s.session_id,
                    "punched": s.punched,
                    "conns": len(s.conns),
                    "age_s": round(time.monotonic() - s.last_rx, 1),
                }
                for s in self._sessions.values()
            ]
        return {
            "fallback_port": self.fallback_port,
            "allowed_forward_ports": sorted(self.allowed_forward_ports),
            "reverse_listeners": dict(self.reverse_bound_ports),
            "sessions": active,
            "bytes_tx": self._bytes_tx,
            "bytes_rx": self._bytes_rx,
        }

    def close(self) -> None:
        self._stop.set()
        for _, _, srv in self._rev_srvs:
            try:
                srv.close()
            except OSError:
                pass
        with self._sess_lock:
            for s in self._sessions.values():
                self._close_session_obj(s)
            self._sessions.clear()
        if self._fallback_sock is not None:
            try:
                self._fallback_sock.close()
            except OSError:
                pass
        for t in self._threads:
            t.join(timeout=1.0)


class PhantomTunnelClient(_TunnelEndpointMixin):
    """Windows Zero-Weight local TCP forwarder riding the punched 5ms Direct P2P UDP tunnel."""

    def __init__(
        self,
        peer_http_base: str,
        peer_udp_ip: str,
        peer_fallback_port: int = 9710,
        forwards: dict[int, int] | None = None,
        listen_host: str = "127.0.0.1",
        local_test_mode: bool = False,
        use_fast_wire: bool = True,
        allowed_reverse_ports: list[int] | None = None,
        keepalive_interval_s: float = 10.0,
        pong_stale_s: float = 35.0,
        reconnect_cooldown_s: float = 10.0,
        auto_reconnect: bool = True,
    ) -> None:
        self._init_mux(direction_bit=1, use_fast_wire=use_fast_wire)
        self.peer_http_base = peer_http_base.rstrip("/")
        self.peer_udp_ip = peer_udp_ip
        self.peer_fallback_port = int(peer_fallback_port)
        self.forwards: dict[int, int] = dict(forwards if forwards is not None else {2222: 22, 9789: 9780})
        self.listen_host = listen_host
        self.local_test_mode = local_test_mode
        self.allowed_reverse_ports: set[int] = set(
            allowed_reverse_ports if allowed_reverse_ports is not None else [9780, 12500, 12504]
        )
        self._keepalive_interval_s = max(0.05, float(keepalive_interval_s))
        self._pong_stale_s = max(0.2, float(pong_stale_s))
        self._reconnect_cooldown_s = max(0.1, float(reconnect_cooldown_s))
        self._auto_reconnect = bool(auto_reconnect)

        self._stop = threading.Event()
        self._conn_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._next_cid = 1

        self._session_id = 0
        self._session_key = b""
        self._sock: socket.socket | None = None
        self._peer_addr: tuple[str, int] | None = None
        self._mode = "DISCONNECTED"
        self._direct_rtt_ms = 0.0
        self._punches_ok = 0
        self._reconnect_count = 0
        self._last_reconnect_attempt = 0.0
        self._reconnecting = False
        self._last_pong = 0.0
        self._last_ping_sent: dict[int, float] = {}
        self._pending_pong: threading.Event | None = None
        self._last_pong_ms = 0.0

        self._tcp_srvs: list[tuple[int, int, socket.socket]] = []
        self._threads: list[threading.Thread] = []
        self.bound_ports: dict[int, int] = {}

    def start_listeners(self) -> "PhantomTunnelClient":
        for loc_p, rem_p in self.forwards.items():
            srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            srv.bind((self.listen_host, int(loc_p)))
            srv.listen(32)
            srv.settimeout(0.25)
            actual_p = int(srv.getsockname()[1])
            self.bound_ports[rem_p] = actual_p
            self._tcp_srvs.append((actual_p, int(rem_p), srv))
            th = threading.Thread(target=self._accept_loop, args=(srv, int(rem_p)), daemon=True)
            th.start()
            self._threads.append(th)

        t_io = threading.Thread(target=self._udp_io_loop, daemon=True)
        t_io.start()
        self._threads.append(t_io)
        return self

    def _accept_loop(self, srv: socket.socket, remote_port: int) -> None:
        while not self._stop.is_set():
            try:
                cli, _ = srv.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                cli.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            except OSError:
                pass
            with self._state_lock:
                sock, addr, key, sid = self._sock, self._peer_addr, self._session_key, self._session_id
            if sock is None or addr is None:
                # Auto-connect on first demand if disconnected
                try:
                    self.connect(local_test_mode=self.local_test_mode, num_sockets=64, spray_count=300, timeout_s=2.5)
                except Exception:
                    pass
                with self._state_lock:
                    sock, addr, key, sid = self._sock, self._peer_addr, self._session_key, self._session_id
            if sock is None or addr is None:
                cli.close()
                continue

            with self._mux_lock:
                cid = self._next_cid
                self._next_cid += 1
                stream = _TunnelStream(
                    conn_id=cid,
                    tcp_sock=cli,
                    open_acked=False,
                    open_target_port=remote_port,
                    last_open_tx=time.perf_counter(),
                )
                self._conns[cid] = stream

            self._send_encrypted(sock, addr, key, sid, _pack_inner(_P_OPEN, 0, cid, 0, remote_port))
            threading.Thread(
                target=self._pump_tcp_stream,
                args=(stream, lambda: (self._sock, self._peer_addr, self._session_key, self._session_id), self._stop),
                daemon=True,
            ).start()

    def connect(
        self,
        local_test_mode: bool | None = None,
        num_sockets: int = 192,
        spray_count: int = 900,
        timeout_s: float = 3.5,
    ) -> dict[str, Any]:
        with self._conn_lock:
            t0 = time.perf_counter()
            ltm = self.local_test_mode if local_test_mode is None else bool(local_test_mode)
            n_sock = max(8, min(240, int(num_sockets if not ltm else min(num_sockets, 16))))

            sid = int.from_bytes(os.urandom(4), "big") or 1
            key = os.urandom(32)
            token_bytes = os.urandom(8)
            token = token_bytes.hex()

            if ltm:
                nat_prof = {
                    "nat_type": "LOCAL_LOOPBACK",
                    "public_ip": "127.0.0.1",
                    "public_port": 0,
                    "port_delta": 0,
                }
            else:
                nat_prof = discover_nat_profile()

            socks: list[socket.socket] = []
            win_sock: socket.socket | None = None
            win_addr: tuple[str, int] | None = None
            try:
                for _ in range(n_sock):
                    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    _disable_connreset(s)
                    s.bind(("0.0.0.0", 0))
                    s.setblocking(False)
                    socks.append(s)

                if ltm:
                    nat_prof["public_port"] = int(socks[0].getsockname()[1])

                offer = {
                    "token": token,
                    "session_id": sid,
                    "session_key_b64": base64.b64encode(key).decode("ascii"),
                    "peer_ip": nat_prof["public_ip"],
                    "peer_stun_port": nat_prof["public_port"],
                    "peer_port_delta": nat_prof.get("port_delta", 0),
                    "spray_count": spray_count if not ltm else 64,
                    "timeout_s": timeout_s,
                    "local_test_mode": ltm,
                }
                req = urllib.request.Request(
                    f"{self.peer_http_base}/api/phantom/offer",
                    data=json.dumps(offer).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=6.0) as resp:
                    ack = json.loads(resp.read().decode("utf-8"))

                resp_addr = (str(ack["responder_pub_ip"]), int(ack["responder_pub_port"]))
                fb_port = int(ack.get("fallback_port") or self.peer_fallback_port)
                punch_pkt = _MAGIC_PUNCH + token_bytes

                waves = 0
                next_wave = time.perf_counter()
                deadline = next_wave + timeout_s
                while time.perf_counter() < deadline and win_sock is None and not self._stop.is_set():
                    now = time.perf_counter()
                    if now >= next_wave and waves < 4:
                        for s in socks:
                            try:
                                s.sendto(punch_pkt, resp_addr)
                            except OSError:
                                pass
                        waves += 1
                        next_wave = now + 0.18

                    for i0 in range(0, len(socks), 250):
                        batch = socks[i0 : i0 + 250]
                        rlist, _, _ = select.select(batch, [], [], 0.01)
                        for rs in rlist:
                            try:
                                pkt, src = rs.recvfrom(1024)
                            except (BlockingIOError, ConnectionResetError, OSError):
                                continue
                            if len(pkt) >= 13 and pkt[:5] in (_MAGIC_PUNCH, _MAGIC_ACK) and pkt[5:13] == token_bytes:
                                win_sock = rs
                                win_addr = (src[0], int(src[1]))
                                break
                        if win_sock is not None:
                            break
            finally:
                for s in socks:
                    if s is not win_sock:
                        try:
                            s.close()
                        except OSError:
                            pass

            old_sock = self._sock
            if win_sock is not None and win_addr is not None:
                try:
                    win_sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
                    win_sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4 * 1024 * 1024)
                except OSError:
                    pass
                with self._state_lock:
                    self._session_id = sid
                    self._session_key = key
                    self._sock = win_sock
                    self._peer_addr = win_addr
                    self._mode = "PHANTOM_5MS_DIRECT"
                    self._punches_ok += 1
                if old_sock is not None:
                    try:
                        old_sock.close()
                    except OSError:
                        pass
                # Verify live encrypted round-trip RTT over the newly punched socket
                rtts = self._measure_rtt(count=3)
                if rtts:
                    with self._state_lock:
                        self._direct_rtt_ms = round(sorted(rtts)[len(rtts) // 2], 2)
                        self._last_pong = time.monotonic()
                    return {**self.status(), "connected": True, "rtt_samples_ms": rtts, "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2)}

            # Fallback cleanly to Tailscale UDP fallback port if punch failed
            fb_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            _disable_connreset(fb_sock)
            fb_sock.bind(("0.0.0.0", 0))
            fb_sock.setblocking(False)
            with self._state_lock:
                self._session_id = sid
                self._session_key = key
                self._sock = fb_sock
                self._peer_addr = (self.peer_udp_ip or "127.0.0.1", fb_port)
                self._mode = "TAILSCALE_FALLBACK"
            if old_sock is not None:
                try:
                    old_sock.close()
                except OSError:
                    pass
            rtts = self._measure_rtt(count=2)
            if rtts:
                with self._state_lock:
                    self._direct_rtt_ms = round(sorted(rtts)[len(rtts) // 2], 2)
                    self._last_pong = time.monotonic()
            return {**self.status(), "connected": bool(rtts), "rtt_samples_ms": rtts, "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2)}

    def _measure_rtt(self, count: int = 3) -> list[float]:
        out: list[float] = []
        for idx in range(count):
            ev = threading.Event()
            with self._state_lock:
                sock, addr, key, sid = self._sock, self._peer_addr, self._session_key, self._session_id
                self._pending_pong = ev
            if sock is None or addr is None:
                break
            t0 = time.perf_counter()
            ping = _pack_inner(_P_PING, 0, 0, idx + 1, 0, struct.pack("!Q", int(time.perf_counter_ns() // 1000)))
            self._send_encrypted(sock, addr, key, sid, ping)
            if ev.wait(timeout=0.9):
                out.append(round((time.perf_counter() - t0) * 1000.0, 2))
        return out

    def _trigger_auto_reconnect(self, reason: str = "pong_stale") -> None:
        with self._state_lock:
            now_m = time.monotonic()
            if self._stop.is_set() or self._reconnecting or not self._auto_reconnect:
                return
            if (now_m - self._last_reconnect_attempt) < self._reconnect_cooldown_s:
                return
            self._reconnecting = True
            self._last_reconnect_attempt = now_m

        def _worker() -> None:
            try:
                res = self.connect(
                    local_test_mode=self.local_test_mode,
                    num_sockets=16 if self.local_test_mode else 96,
                    spray_count=64 if self.local_test_mode else 600,
                    timeout_s=3.0,
                )
                if res.get("connected"):
                    with self._state_lock:
                        self._reconnect_count += 1
            except Exception:
                pass
            finally:
                with self._state_lock:
                    self._reconnecting = False

        threading.Thread(target=_worker, daemon=True, name=f"phantom-reconn-{reason}").start()

    def _udp_io_loop(self) -> None:
        next_keepalive = time.monotonic() + self._keepalive_interval_s
        while not self._stop.is_set():
            with self._state_lock:
                sock, addr, key, sid = self._sock, self._peer_addr, self._session_key, self._session_id
                punches_ok = self._punches_ok
            if sock is None or addr is None:
                if self._auto_reconnect and punches_ok > 0:
                    self._trigger_auto_reconnect("disconnected")
                self._stop.wait(timeout=0.25)
                continue

            has_conns = bool(self._conns)
            try:
                r, _, _ = select.select([sock], [], [], 0.008 if has_conns else min(0.25, self._keepalive_interval_s))
            except (OSError, ValueError):
                time.sleep(0.05)
                continue

            if r:
                for _ in range(128):
                    try:
                        pkt, src = sock.recvfrom(65535)
                    except (BlockingIOError, ConnectionResetError, OSError):
                        break
                    with self._mux_lock:
                        self._bytes_rx += len(pkt)
                    dec = open_any_packet(key, pkt)
                    if dec is None or dec[0] != sid:
                        continue
                    inner = _unpack_inner(dec[2])
                    if inner is None:
                        continue
                    ptype, flags, conn_id, seq, _aux, body = inner
                    if ptype == _P_PONG:
                        with self._state_lock:
                            self._last_pong = time.monotonic()
                            if len(body) >= 8:
                                (ts_us,) = struct.unpack_from("!Q", body, 0)
                                now_us = int(time.perf_counter_ns() // 1000)
                                if now_us >= ts_us:
                                    self._direct_rtt_ms = round((now_us - ts_us) / 1000.0, 2)
                            if self._pending_pong is not None:
                                self._pending_pong.set()
                        continue
                    if ptype == _P_OPEN:
                        target_port = int(_aux)
                        with self._mux_lock:
                            existing = self._conns.get(conn_id)
                        if existing is not None:
                            self._send_encrypted(sock, addr, key, sid, _pack_inner(_P_ACK, 0, conn_id, 0))
                            continue
                        if target_port not in self.allowed_reverse_ports:
                            self._send_encrypted(sock, addr, key, sid, _pack_inner(_P_CLOSE, 0, conn_id, 0))
                            continue
                        tcp_s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        try:
                            tcp_s.settimeout(2.0)
                            tcp_s.connect(("127.0.0.1", target_port))
                        except OSError:
                            tcp_s.close()
                            self._send_encrypted(sock, addr, key, sid, _pack_inner(_P_CLOSE, 0, conn_id, 0))
                            continue
                        stream = _TunnelStream(
                            conn_id=conn_id,
                            tcp_sock=tcp_s,
                            open_acked=True,
                            open_target_port=target_port,
                            prefer_v9=bool(self._use_fast_wire),
                        )
                        with self._mux_lock:
                            self._conns[conn_id] = stream
                        self._send_encrypted(sock, addr, key, sid, _pack_inner(_P_ACK, 0, conn_id, 0))
                        threading.Thread(
                            target=self._pump_tcp_stream,
                            args=(stream, lambda: (self._sock, self._peer_addr, self._session_key, self._session_id), self._stop),
                            daemon=True,
                        ).start()
                        continue
                    with self._mux_lock:
                        stream = self._conns.get(conn_id)
                    if stream is not None:
                        self._handle_stream_frame(stream, ptype, flags, seq, body, sock, addr, key, sid)

            if self._conns:
                self._retransmit_pending(self._conns, sock, addr, key, sid)

            now = time.monotonic()
            if now >= next_keepalive:
                next_keepalive = now + self._keepalive_interval_s
                ping = _pack_inner(_P_PING, 0, 0, int(now) & 0xFFFF, 0, struct.pack("!Q", int(time.perf_counter_ns() // 1000)))
                self._send_encrypted(sock, addr, key, sid, ping)
            with self._state_lock:
                lp = self._last_pong
                p_ok = self._punches_ok
            if self._auto_reconnect and p_ok > 0 and lp > 0.0 and (now - lp) >= self._pong_stale_s:
                self._trigger_auto_reconnect("pong_stale")

    def disconnect(self) -> dict[str, Any]:
        with self._state_lock:
            if self._sock is not None:
                try:
                    self._sock.close()
                except OSError:
                    pass
                self._sock = None
            self._peer_addr = None
            self._mode = "DISCONNECTED"
        return self.status()

    def status(self) -> dict[str, Any]:
        with self._state_lock:
            pong_age = round(time.monotonic() - self._last_pong, 1) if self._last_pong else None
            return {
                "connected": self._sock is not None and self._mode != "DISCONNECTED",
                "mode": self._mode,
                "direct_rtt_ms": self._direct_rtt_ms,
                "peer_udp_addr": f"{self._peer_addr[0]}:{self._peer_addr[1]}" if self._peer_addr else "",
                "listeners": dict(self.bound_ports),
                "active_conns": len(self._conns),
                "tx_bytes": self._bytes_tx,
                "rx_bytes": self._bytes_rx,
                "punches_ok": self._punches_ok,
                "reconnect_count": self._reconnect_count,
                "reconnecting": self._reconnecting,
                "pong_stale": bool(self._last_pong and (time.monotonic() - self._last_pong) >= self._pong_stale_s),
                "last_pong_age_s": pong_age,
            }

    def close(self) -> None:
        self._stop.set()
        for _, _, srv in self._tcp_srvs:
            try:
                srv.close()
            except OSError:
                pass
        with self._mux_lock:
            for c in self._conns.values():
                c.closed = True
                try:
                    c.tcp_sock.close()
                except OSError:
                    pass
            self._conns.clear()
        self.disconnect()
        for t in self._threads:
            t.join(timeout=1.0)
