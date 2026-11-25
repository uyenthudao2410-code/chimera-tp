"""Drop-in transparent TCP-over-CHIMERA-HYPER accelerator (non-collapsing GFNI FEC tunnel)."""

from __future__ import annotations

import math
import socket
import struct
import threading
import time
import zlib
from dataclasses import dataclass
from typing import Any

from .gf256 import coeff_vector, select_independent_rows
from .hyper_wire import _bind_any, _disable_connreset, _family_for_ip
from .native import gf256_decode_matrix, gf256_encode_block

# Warp Tunnel Packet Header (22 bytes):
# magic(2s="CW"), ptype(B), flags(B), conn_id(I), seq(I), group_id(H), idx(H), k(H), crc32(I)
_WARP_HDR = struct.Struct("!2sBBIIHHHI")
_W_MAGIC = b"CW"

_W_OPEN = 1
_W_DATA = 2
_W_FEC = 3
_W_FIN = 4
_W_ACK = 5
_W_NACK = 6
_W_CLOSE = 7

_CHUNK_MAX = 1140  # Safe <= 1280 B Tailscale MTU with 3B subhdr + 22B Warp hdr + IP/UDP
_FEC_GROUP = 8


def _pack_warp(
    ptype: int,
    flags: int,
    conn_id: int,
    seq: int,
    group_id: int,
    idx: int,
    k: int,
    body: bytes = b"",
) -> bytes:
    head18 = struct.pack(
        "!2sBBIIHHH",
        _W_MAGIC,
        ptype & 0xFF,
        flags & 0xFF,
        conn_id & 0xFFFFFFFF,
        seq & 0xFFFFFFFF,
        group_id & 0xFFFF,
        idx & 0xFFFF,
        k & 0xFFFF,
    )
    crc = zlib.crc32(head18 + body) & 0xFFFFFFFF
    return head18 + struct.pack("!I", crc) + body


def _unpack_warp(
    pkt: bytes,
) -> tuple[int, int, int, int, int, int, int, bytes] | None:
    if len(pkt) < _WARP_HDR.size:
        return None
    magic, ptype, flags, conn_id, seq, group_id, idx, k, crc = _WARP_HDR.unpack_from(pkt, 0)
    if magic != _W_MAGIC:
        return None
    body = pkt[_WARP_HDR.size :]
    if (zlib.crc32(pkt[:18] + body) & 0xFFFFFFFF) != crc:
        return None
    return ptype, flags, conn_id, seq, group_id, idx, k, body


@dataclass
class _WarpConn:
    conn_id: int
    tcp_sock: socket.socket
    peer_udp: tuple[str, int]
    next_tx_seq: int = 0
    tx_ack_base: int = 0
    tx_fin_seq: int | None = None
    tx_buffer: dict[int, tuple[int, bytes, float]] = None  # type: ignore[assignment]
    rx_next_seq: int = 0
    rx_fin_seq: int | None = None
    rx_chunks: dict[int, bytes] = None  # type: ignore[assignment]
    last_nack_at: float = 0.0
    closed: bool = False
    open_acked: bool = False
    _group_buf: list[tuple[int, bytes]] = None  # type: ignore[assignment]
    _group_id: int = 0
    _fec_rx_groups: dict[int, dict[int, tuple[int, bytes]]] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self.tx_buffer = {}
        self.rx_chunks = {}
        self._group_buf = []
        self._fec_rx_groups = {}


class _WarpEndpointBase:
    """Shared selective-repeat + proactive GFNI parity stream multiplexer over UDP."""

    def __init__(self, udp_bind: tuple[str, int], est_loss: float = 0.0) -> None:
        self.est_loss = max(0.0, min(0.5, float(est_loss)))
        fam = _family_for_ip(udp_bind[0])
        self._sock = socket.socket(fam, socket.SOCK_DGRAM)
        _disable_connreset(self._sock)
        try:
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8 * 1024 * 1024)
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 8 * 1024 * 1024)
        except OSError:
            pass
        self._sock.bind(udp_bind)
        self._sock.settimeout(0.01)
        self.udp_addr: tuple[str, int] = self._sock.getsockname()[:2]
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._conns: dict[int, _WarpConn] = {}
        self._threads: list[threading.Thread] = []

    def _proactive_parity_count(self) -> int:
        if self.est_loss <= 0.002:
            return 0
        return min(4, max(1, int(math.ceil(_FEC_GROUP * self.est_loss * 1.6))))

    def _send_tcp_bytes_over_udp(self, conn: _WarpConn, raw: bytes) -> None:
        mv = memoryview(raw)
        for off in range(0, len(raw), _CHUNK_MAX):
            piece = bytes(mv[off : off + _CHUNK_MAX])
            flags = 0
            wire_piece = piece
            if len(piece) >= 160:
                comp = zlib.compress(piece, 1)
                if len(comp) < int(len(piece) * 0.90):
                    flags = 1
                    wire_piece = comp
            # Pack 3-byte flags(1B) + piece_len(u16) inside body for exact FEC recovery
            framed = struct.pack("!BH", flags & 1, len(wire_piece)) + wire_piece
            with self._lock:
                seq = conn.next_tx_seq
                conn.next_tx_seq += 1
                now = time.perf_counter()
                conn.tx_buffer[seq] = (flags, framed, now)
                pkt = _pack_warp(
                    _W_DATA, flags, conn.conn_id, seq, conn._group_id, len(conn._group_buf), _FEC_GROUP, framed
                )
                self._sock.sendto(pkt, conn.peer_udp)

                padded = framed + b"\x00" * ((_CHUNK_MAX + 3) - len(framed))
                conn._group_buf.append((seq, padded))
                if len(conn._group_buf) == _FEC_GROUP:
                    self._emit_group_fec_locked(conn)

    def _emit_group_fec_locked(self, conn: _WarpConn) -> None:
        if not conn._group_buf:
            return
        n_par = self._proactive_parity_count()
        k = len(conn._group_buf)
        if n_par > 0 and k >= 2:
            block_len = _CHUNK_MAX + 3
            flat = b"".join(b for _, b in conn._group_buf)
            first_seq = conn._group_buf[0][0]
            seed = struct.pack("!II", conn.conn_id, conn._group_id)
            for p_idx in range(n_par):
                coeffs = bytes(coeff_vector(seed, p_idx + 1, k))
                coded = gf256_encode_block(flat, coeffs, k, block_len)
                pkt = _pack_warp(
                    _W_FEC,
                    0,
                    conn.conn_id,
                    first_seq,
                    conn._group_id,
                    p_idx + 1,
                    k,
                    coded,
                )
                try:
                    self._sock.sendto(pkt, conn.peer_udp)
                except OSError:
                    pass
        conn._group_buf.clear()
        conn._group_id = (conn._group_id + 1) & 0xFFFF

    def _pump_tcp_reader(self, conn: _WarpConn) -> None:
        conn.tcp_sock.settimeout(0.05)
        try:
            while not self._stop.is_set() and not conn.closed:
                with self._lock:
                    inflight = len(conn.tx_buffer)
                if inflight > 128:
                    time.sleep(0.002)
                    continue
                try:
                    data = conn.tcp_sock.recv(32768)
                except socket.timeout:
                    continue
                except OSError:
                    break
                if not data:
                    break
                self._send_tcp_bytes_over_udp(conn, data)
        finally:
            with self._lock:
                self._emit_group_fec_locked(conn)
                fin_seq = conn.next_tx_seq
                conn.tx_fin_seq = fin_seq
                pkt = _pack_warp(_W_FIN, 0, conn.conn_id, fin_seq, 0, 0, 0, b"")
                try:
                    self._sock.sendto(pkt, conn.peer_udp)
                    if self.est_loss > 0.01:
                        self._sock.sendto(pkt, conn.peer_udp)
                except OSError:
                    pass

    def _handle_data_chunk(
        self,
        conn: _WarpConn,
        flags: int,
        seq: int,
        group_id: int,
        k: int,
        body: bytes,
    ) -> None:
        if len(body) < 3:
            return
        bflags, wire_len = struct.unpack_from("!BH", body, 0)
        wire_piece = body[3 : 3 + wire_len]
        plain = zlib.decompress(wire_piece) if (bflags & 1) else wire_piece
        if seq >= conn.rx_next_seq and seq not in conn.rx_chunks:
            conn.rx_chunks[seq] = plain
        if k >= 2:
            grp = conn._fec_rx_groups.setdefault(seq // _FEC_GROUP, {})
            padded = body + b"\x00" * ((_CHUNK_MAX + 3) - len(body))
            grp[seq % _FEC_GROUP] = (bflags, padded)
        self._flush_rx_in_order(conn)

    def _handle_fec_packet(
        self,
        conn: _WarpConn,
        first_seq: int,
        group_id: int,
        p_idx: int,
        k: int,
        coded: bytes,
    ) -> None:
        gkey = first_seq // _FEC_GROUP
        grp = conn._fec_rx_groups.setdefault(gkey, {})
        grp[1000 + p_idx] = (0, coded)
        # Count present systematic indices [0..k-1]
        have_sys = [i for i in range(k) if i in grp]
        missing_sys = [
            i
            for i in range(k)
            if i not in grp
            and (first_seq + i) >= conn.rx_next_seq
            and (first_seq + i) not in conn.rx_chunks
        ]
        if not missing_sys:
            conn._fec_rx_groups.pop(gkey, None)
            return
        fec_entries = [(idx - 1000, blk) for idx, (_, blk) in grp.items() if idx >= 1000]
        if len(have_sys) + len(fec_entries) < k:
            return
        # Select k linearly independent rows for GFNI matrix recovery
        block_len = _CHUNK_MAX + 3
        cand_coeffs: list[bytes] = []
        cand_blocks: list[bytes] = []
        for i in range(k):
            if i in grp:
                row = bytearray(k)
                row[i] = 1
                cand_coeffs.append(bytes(row))
                cand_blocks.append(grp[i][1])
        seed = struct.pack("!II", conn.conn_id, group_id)
        for p_id, blk in fec_entries:
            cand_coeffs.append(bytes(coeff_vector(seed, p_id, k)))
            cand_blocks.append(blk)
        chosen = select_independent_rows(cand_coeffs, k)
        if chosen is None:
            return
        coeffs_flat = b"".join(cand_coeffs[i] for i in chosen)
        coded_flat = b"".join(cand_blocks[i] for i in chosen)
        try:
            rec = gf256_decode_matrix(coded_flat, coeffs_flat, k, block_len)
        except ValueError:
            return
        for miss_i in missing_sys:
            seq = first_seq + miss_i
            if seq < conn.rx_next_seq or seq in conn.rx_chunks:
                continue
            raw_blk = rec[miss_i * block_len : (miss_i + 1) * block_len]
            bflags, wlen = struct.unpack_from("!BH", raw_blk, 0)
            if wlen > _CHUNK_MAX:
                continue
            piece = raw_blk[3 : 3 + wlen]
            if bflags & 1:
                piece = zlib.decompress(piece)
            conn.rx_chunks[seq] = piece
        self._flush_rx_in_order(conn)

    def _flush_rx_in_order(self, conn: _WarpConn) -> None:
        while conn.rx_next_seq in conn.rx_chunks:
            chunk = conn.rx_chunks.pop(conn.rx_next_seq)
            try:
                conn.tcp_sock.sendall(chunk)
            except OSError:
                conn.closed = True
                return
            conn.rx_next_seq += 1

        if conn.rx_fin_seq is not None and conn.rx_next_seq >= conn.rx_fin_seq:
            try:
                conn.tcp_sock.shutdown(socket.SHUT_WR)
            except OSError:
                pass

    def _retransmit_loop(self) -> None:
        while not self._stop.is_set():
            now = time.perf_counter()
            to_send: list[tuple[bytes, tuple[str, int]]] = []
            with self._lock:
                for conn in list(self._conns.values()):
                    if conn.closed:
                        continue
                    for seq, (flags, framed, last_tx) in list(conn.tx_buffer.items()):
                        if (now - last_tx) >= 0.08:
                            conn.tx_buffer[seq] = (flags, framed, now)
                            to_send.append(
                                (
                                    _pack_warp(_W_DATA, flags, conn.conn_id, seq, 0, 0, 0, framed),
                                    conn.peer_udp,
                                )
                            )
                    if conn.rx_chunks:
                        max_rx = max(conn.rx_chunks.keys())
                        missing = [s for s in range(conn.rx_next_seq, min(max_rx, conn.rx_next_seq + 32)) if s not in conn.rx_chunks]
                        if missing and (now - conn.last_nack_at) >= 0.018:
                            conn.last_nack_at = now
                            nbody = struct.pack(f"<{len(missing)}I", *missing)
                            to_send.append(
                                (
                                    _pack_warp(_W_NACK, 0, conn.conn_id, conn.rx_next_seq, 0, 0, len(missing), nbody),
                                    conn.peer_udp,
                                )
                            )
                    elif conn.rx_fin_seq is not None and conn.rx_next_seq < conn.rx_fin_seq and (now - conn.last_nack_at) >= 0.018:
                        conn.last_nack_at = now
                        missing = list(range(conn.rx_next_seq, min(conn.rx_fin_seq, conn.rx_next_seq + 32)))
                        nbody = struct.pack(f"<{len(missing)}I", *missing)
                        to_send.append(
                            (
                                _pack_warp(_W_NACK, 0, conn.conn_id, conn.rx_next_seq, 0, 0, len(missing), nbody),
                                conn.peer_udp,
                            )
                        )
            for pkt, dst in to_send:
                try:
                    self._sock.sendto(pkt, dst)
                except OSError:
                    pass
            time.sleep(0.008)

    def _process_common_pkt(
        self,
        conn: _WarpConn,
        ptype: int,
        flags: int,
        seq: int,
        group_id: int,
        idx: int,
        k: int,
        body: bytes,
    ) -> None:
        if ptype == _W_DATA:
            self._handle_data_chunk(conn, flags, seq, group_id, k, body)
            ack = _pack_warp(_W_ACK, 0, conn.conn_id, conn.rx_next_seq, 0, 0, 0, b"")
            try:
                self._sock.sendto(ack, conn.peer_udp)
            except OSError:
                pass
        elif ptype == _W_FEC:
            self._handle_fec_packet(conn, seq, group_id, idx, k, body)
            ack = _pack_warp(_W_ACK, 0, conn.conn_id, conn.rx_next_seq, 0, 0, 0, b"")
            try:
                self._sock.sendto(ack, conn.peer_udp)
            except OSError:
                pass
        elif ptype == _W_FIN:
            conn.rx_fin_seq = seq
            self._flush_rx_in_order(conn)
            ack = _pack_warp(_W_ACK, 0, conn.conn_id, conn.rx_next_seq, 0, 0, 0, b"")
            try:
                self._sock.sendto(ack, conn.peer_udp)
            except OSError:
                pass
        elif ptype == _W_ACK:
            conn.open_acked = True
            with self._lock:
                for s in [k_s for k_s in conn.tx_buffer if k_s < seq]:
                    del conn.tx_buffer[s]
        elif ptype == _W_NACK:
            count = len(body) // 4
            if count > 0:
                miss_seqs = struct.unpack_from(f"<{count}I", body, 0)
                with self._lock:
                    for s in [k_s for k_s in conn.tx_buffer if k_s < seq]:
                        del conn.tx_buffer[s]
                    now = time.perf_counter()
                    for m in miss_seqs:
                        entry = conn.tx_buffer.get(m)
                        if entry is not None:
                            fl, fr, _ = entry
                            conn.tx_buffer[m] = (fl, fr, now)
                            pkt = _pack_warp(_W_DATA, fl, conn.conn_id, m, 0, 0, 0, fr)
                            try:
                                self._sock.sendto(pkt, conn.peer_udp)
                            except OSError:
                                pass
        elif ptype == _W_CLOSE:
            conn.closed = True
            try:
                conn.tcp_sock.close()
            except OSError:
                pass

    def close(self) -> None:
        self._stop.set()
        with self._lock:
            for c in self._conns.values():
                c.closed = True
                try:
                    c.tcp_sock.close()
                except OSError:
                    pass
        for t in self._threads:
            t.join(timeout=1.0)
        try:
            self._sock.close()
        except OSError:
            pass


class WarpServer(_WarpEndpointBase):
    """UDP CHIMERA-HYPER terminator forwarding accelerated streams to a local/remote TCP server."""

    def __init__(
        self,
        udp_bind: tuple[str, int],
        forward_tcp_addr: tuple[str, int],
        est_loss: float = 0.0,
    ) -> None:
        super().__init__(udp_bind=udp_bind, est_loss=est_loss)
        self.forward_tcp_addr = forward_tcp_addr

    def start(self) -> "WarpServer":
        t_rx = threading.Thread(target=self._udp_rx_loop, daemon=True)
        t_rt = threading.Thread(target=self._retransmit_loop, daemon=True)
        t_rx.start()
        t_rt.start()
        self._threads.extend([t_rx, t_rt])
        return self

    def _udp_rx_loop(self) -> None:
        while not self._stop.is_set():
            try:
                pkt, addr = self._sock.recvfrom(65535)
            except (socket.timeout, ConnectionResetError):
                continue
            except OSError:
                break
            parsed = _unpack_warp(pkt)
            if parsed is None:
                continue
            ptype, flags, conn_id, seq, group_id, idx, k, body = parsed
            with self._lock:
                conn = self._conns.get(conn_id)
            peer_udp = addr[:2]
            if conn is None and ptype in (_W_OPEN, _W_DATA):
                tcp_fam = _family_for_ip(self.forward_tcp_addr[0])
                tcp_s = socket.socket(tcp_fam, socket.SOCK_STREAM)
                try:
                    tcp_s.settimeout(5.0)
                    tcp_s.connect(self.forward_tcp_addr)
                except OSError:
                    tcp_s.close()
                    continue
                conn = _WarpConn(conn_id=conn_id, tcp_sock=tcp_s, peer_udp=peer_udp)
                with self._lock:
                    self._conns[conn_id] = conn
                threading.Thread(target=self._pump_tcp_reader, args=(conn,), daemon=True).start()
            if conn is None:
                continue
            conn.peer_udp = peer_udp
            self._process_common_pkt(conn, ptype, flags, seq, group_id, idx, k, body)


class WarpClient(_WarpEndpointBase):
    """Local TCP listener accelerating outbound TCP connections over CHIMERA-HYPER UDP."""

    def __init__(
        self,
        listen_tcp_addr: tuple[str, int],
        remote_udp_addr: tuple[str, int],
        est_loss: float = 0.05,
    ) -> None:
        udp_fam = _family_for_ip(remote_udp_addr[0])
        super().__init__(udp_bind=_bind_any(udp_fam), est_loss=est_loss)
        self.remote_udp_addr = remote_udp_addr
        self._tcp_srv = socket.socket(_family_for_ip(listen_tcp_addr[0]), socket.SOCK_STREAM)
        self._tcp_srv.bind(listen_tcp_addr)
        self._tcp_srv.listen(32)
        self._tcp_srv.settimeout(0.05)
        self.listen_addr: tuple[str, int] = self._tcp_srv.getsockname()[:2]
        self._next_conn_id = 1

    def start(self) -> "WarpClient":
        t_acc = threading.Thread(target=self._accept_loop, daemon=True)
        t_rx = threading.Thread(target=self._udp_rx_loop, daemon=True)
        t_rt = threading.Thread(target=self._retransmit_loop, daemon=True)
        for t in (t_acc, t_rx, t_rt):
            t.start()
            self._threads.append(t)
        return self

    def _accept_loop(self) -> None:
        while not self._stop.is_set():
            try:
                cli_sock, _ = self._tcp_srv.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with self._lock:
                cid = self._next_conn_id
                self._next_conn_id += 1
                conn = _WarpConn(conn_id=cid, tcp_sock=cli_sock, peer_udp=self.remote_udp_addr)
                self._conns[cid] = conn
            open_pkt = _pack_warp(_W_OPEN, 0, cid, 0, 0, 0, 0, b"")
            try:
                self._sock.sendto(open_pkt, self.remote_udp_addr)
                if self.est_loss > 0.01:
                    self._sock.sendto(open_pkt, self.remote_udp_addr)
            except OSError:
                pass
            threading.Thread(target=self._pump_tcp_reader, args=(conn,), daemon=True).start()

    def _udp_rx_loop(self) -> None:
        while not self._stop.is_set():
            try:
                pkt, _ = self._sock.recvfrom(65535)
            except (socket.timeout, ConnectionResetError):
                continue
            except OSError:
                break
            parsed = _unpack_warp(pkt)
            if parsed is None:
                continue
            ptype, flags, conn_id, seq, group_id, idx, k, body = parsed
            with self._lock:
                conn = self._conns.get(conn_id)
            if conn is None:
                continue
            self._process_common_pkt(conn, ptype, flags, seq, group_id, idx, k, body)

    def close(self) -> None:
        try:
            self._tcp_srv.close()
        except OSError:
            pass
        super().close()
