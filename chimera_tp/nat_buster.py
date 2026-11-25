"""CHIMERA v4.0 Breakthrough #1: STUN NAT Profiling & Birthday-Paradox UDP Hole-Puncher."""

from __future__ import annotations

import ipaddress
import os
import random
import select
import socket
import struct
import threading
import time
import urllib.request
import json
from collections import OrderedDict
from typing import Any

from .hyper_wire import _disable_connreset

DEFAULT_STUN_SERVERS: tuple[tuple[str, int], ...] = (
    ("stun.cloudflare.com", 3478),
    ("stun.l.google.com", 19302),
    ("stun1.l.google.com", 19302),
)

_STUN_MAGIC_COOKIE = 0x2112A442
_MAGIC_PUNCH = b"CHNP1"
_MAGIC_ACK = b"CHNP2"
_MAGIC_PING = b"CHNP3"
_MAGIC_PONG = b"CHNP4"
_PING_STRUCT = struct.Struct("!Q")


def parse_stun_xor_mapped(data: bytes, expected_tid: bytes | None = None) -> tuple[str, int] | None:
    """Parse RFC 5389 Binding Success Response for XOR-MAPPED-ADDRESS or MAPPED-ADDRESS."""
    if len(data) < 20:
        return None
    msg_type, msg_len, cookie = struct.unpack_from("!HHI", data, 0)
    if msg_type != 0x0101 or cookie != _STUN_MAGIC_COOKIE:
        return None
    if expected_tid is not None and data[8:20] != expected_tid:
        return None

    end = min(len(data), 20 + msg_len)
    off = 20
    fallback_mapped: tuple[str, int] | None = None
    while off + 4 <= end:
        attr_type, attr_len = struct.unpack_from("!HH", data, off)
        val_start = off + 4
        val_end = val_start + attr_len
        if val_end > len(data):
            break
        val = data[val_start:val_end]
        if attr_type == 0x0020 and attr_len >= 8 and val[1] == 1:
            xport = struct.unpack_from("!H", val, 2)[0] ^ 0x2112
            xip = struct.unpack_from("!I", val, 4)[0] ^ _STUN_MAGIC_COOKIE
            ip_str = socket.inet_ntoa(struct.pack("!I", xip))
            return ip_str, int(xport)
        if attr_type == 0x0001 and attr_len >= 8 and val[1] == 1 and fallback_mapped is None:
            port = struct.unpack_from("!H", val, 2)[0]
            ip_str = socket.inet_ntoa(val[4:8])
            fallback_mapped = (ip_str, int(port))
        off += 4 + ((attr_len + 3) & ~3)
    return fallback_mapped


def stun_query(
    sock: socket.socket,
    server: tuple[str, int],
    timeout_s: float = 2.0,
) -> tuple[str, int, float] | None:
    """Send an RFC 5389 STUN Binding Request from `sock` and return `(ip, port, rtt_ms)`."""
    tid = os.urandom(12)
    req = struct.pack("!HHI", 0x0001, 0, _STUN_MAGIC_COOKIE) + tid
    prev_timeout = sock.gettimeout()
    deadline = time.perf_counter() + max(0.2, float(timeout_s))
    try:
        sock.settimeout(min(max(0.2, float(timeout_s)), 2.5))
        t0 = time.perf_counter()
        sock.sendto(req, server)
        while True:
            rem = deadline - time.perf_counter()
            if rem <= 0:
                return None
            sock.settimeout(rem)
            data, _ = sock.recvfrom(1024)
            parsed = parse_stun_xor_mapped(data, expected_tid=tid)
            if parsed is not None:
                rtt_ms = (time.perf_counter() - t0) * 1000.0
                return parsed[0], parsed[1], round(rtt_ms, 2)
    except (OSError, socket.timeout):
        return None
    finally:
        try:
            sock.settimeout(prev_timeout)
        except OSError:
            pass


def discover_nat_profile(
    stun_servers: tuple[tuple[str, int], ...] = DEFAULT_STUN_SERVERS,
    timeout_s: float = 1.8,
) -> dict[str, Any]:
    """Classify local NAT behavior (EASY vs SYMMETRIC) and sequential port delta."""
    s1 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s2 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    _disable_connreset(s1)
    _disable_connreset(s2)
    samples: list[dict[str, Any]] = []
    delta = 0
    try:
        s1.bind(("0.0.0.0", 0))
        s2.bind(("0.0.0.0", 0))
        first_srv: tuple[str, int] | None = None
        for srv in stun_servers:
            res = stun_query(s1, srv, timeout_s=timeout_s)
            if res is not None:
                if first_srv is None:
                    first_srv = srv
                samples.append(
                    {
                        "server": f"{srv[0]}:{srv[1]}",
                        "public_ip": res[0],
                        "public_port": res[1],
                        "rtt_ms": res[2],
                    }
                )
            if len(samples) >= 2:
                break

        if not samples:
            return {
                "nat_type": "BLOCKED",
                "public_ip": "",
                "public_port": 0,
                "alt_port": 0,
                "port_delta": 0,
                "stun_rtt_ms": 0.0,
                "samples": [],
            }

        if first_srv is not None:
            res2 = stun_query(s2, first_srv, timeout_s=timeout_s)
            if res2 is not None:
                delta = int(res2[1]) - int(samples[0]["public_port"])

        p0 = int(samples[0]["public_port"])
        p1 = int(samples[1]["public_port"]) if len(samples) > 1 else p0
        ip0 = str(samples[0]["public_ip"])
        ip1 = str(samples[1]["public_ip"]) if len(samples) > 1 else ip0
        if len(samples) >= 2 and (ip0 != ip1 or p0 != p1):
            nat_type = "SYMMETRIC"
        else:
            nat_type = "EASY"
        avg_rtt = round(sum(float(x["rtt_ms"]) for x in samples) / len(samples), 2)
        return {
            "nat_type": nat_type,
            "public_ip": ip0,
            "public_port": p0,
            "alt_port": p1,
            "port_delta": delta,
            "stun_rtt_ms": avg_rtt,
            "samples": samples,
        }
    finally:
        for s in (s1, s2):
            try:
                s.close()
            except OSError:
                pass


def _validate_public_or_loopback_ip(ip_str: str, allow_loopback: bool) -> str:
    addr = ipaddress.ip_address(ip_str)
    if addr.version != 4:
        raise ValueError("Only IPv4 NAT punching is supported")
    if addr.is_loopback and not allow_loopback:
        raise ValueError("Loopback address rejected when local_test_mode=False")
    if addr.is_multicast or addr.is_unspecified:
        raise ValueError(f"Invalid target IP: {ip_str}")
    return str(addr)


def _build_spray_ports(
    base_port: int,
    port_delta: int,
    spray_count: int,
    local_test_mode: bool = False,
) -> list[int]:
    """Generate prioritized target port list: delta prediction + birthday-paradox spray."""
    target = max(16, min(1500, int(spray_count)))
    ports: list[int] = []
    seen: set[int] = set()

    def _add(p: int) -> None:
        if 1024 <= p <= 65535 and p not in seen and len(ports) < target:
            seen.add(p)
            ports.append(p)

    if 1024 <= base_port <= 65535:
        _add(base_port)
        # Sequential / localized port delta predictions
        if port_delta != 0 and abs(port_delta) <= 4096:
            for mult in range(1, 33):
                _add(base_port + port_delta * mult)
                _add(base_port - port_delta * mult)
        # Tight neighborhood around observed STUN port
        for off in range(-48, 49):
            _add(base_port + off)

    if not local_test_mode and len(ports) < target:
        rem = target - len(ports)
        pool_needed = rem + len(seen)
        candidates = random.sample(range(1024, 65536), min(64512, pool_needed))
        for cand in candidates:
            _add(cand)
            if len(ports) >= target:
                break
    return ports


class NatPunchResponder:
    """On-demand zero-idle responder binding one UDP anchor and spraying candidate ports."""

    def __init__(self, max_sessions: int = 64) -> None:
        self._max_sessions = max(8, int(max_sessions))
        self._lock = threading.Lock()
        self._sessions: OrderedDict[str, dict[str, Any]] = OrderedDict()

    def get_session(self, token: str) -> dict[str, Any] | None:
        with self._lock:
            entry = self._sessions.get(token)
            return dict(entry) if entry is not None else None

    def start_session(self, offer: dict[str, Any]) -> dict[str, Any]:
        token = str(offer.get("token", "")).strip().lower()
        if len(token) != 16:
            raise ValueError("Invalid punch token length (expected 16 hex chars)")
        token_bytes = bytes.fromhex(token)

        local_test_mode = bool(offer.get("local_test_mode", False))
        peer_ip = _validate_public_or_loopback_ip(
            str(offer.get("peer_ip", "")), allow_loopback=local_test_mode
        )
        peer_stun_port = int(offer.get("peer_stun_port", 0))
        peer_port_delta = int(offer.get("peer_port_delta", 0))
        spray_count = int(offer.get("spray_count", 900))
        timeout_s = max(0.5, min(6.0, float(offer.get("timeout_s", 4.0))))

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        _disable_connreset(sock)
        try:
            sock.bind(("0.0.0.0", 0))
            local_port = int(sock.getsockname()[1])
            if local_test_mode:
                pub_ip, pub_port, nat_type = "127.0.0.1", local_port, "LOCAL_LOOPBACK"
            else:
                stun_hits: list[tuple[str, int, float]] = []
                for srv in DEFAULT_STUN_SERVERS:
                    hit = stun_query(sock, srv, timeout_s=1.5)
                    if hit is not None:
                        stun_hits.append(hit)
                    if len(stun_hits) >= 2:
                        break
                if not stun_hits:
                    raise RuntimeError("Responder STUN discovery failed")
                pub_ip, pub_port = stun_hits[0][0], stun_hits[0][1]
                if len(stun_hits) >= 2 and (
                    stun_hits[0][0] != stun_hits[1][0] or stun_hits[0][1] != stun_hits[1][1]
                ):
                    nat_type = "SYMMETRIC"
                else:
                    nat_type = "EASY"
            sock.setblocking(False)
        except Exception:
            sock.close()
            raise

        with self._lock:
            self._sessions[token] = {
                "token": token,
                "punched": False,
                "finished": False,
                "probes_sent": 0,
                "remote_addr": None,
                "responder_nat_type": nat_type,
                "responder_pub_addr": [pub_ip, pub_port],
                "elapsed_ms": 0.0,
            }
            self._sessions.move_to_end(token)
            while len(self._sessions) > self._max_sessions:
                self._sessions.popitem(last=False)

        ports = _build_spray_ports(
            base_port=peer_stun_port,
            port_delta=peer_port_delta,
            spray_count=spray_count,
            local_test_mode=local_test_mode,
        )

        th = threading.Thread(
            target=self._run_session,
            args=(sock, token, token_bytes, peer_ip, ports, timeout_s),
            daemon=True,
        )
        th.start()

        return {
            "ok": True,
            "token": token,
            "responder_pub_ip": pub_ip,
            "responder_pub_port": pub_port,
            "responder_nat_type": nat_type,
            "local_port": local_port,
            "candidate_ports": len(ports),
        }

    def _run_session(
        self,
        sock: socket.socket,
        token: str,
        token_bytes: bytes,
        peer_ip: str,
        ports: list[int],
        timeout_s: float,
    ) -> None:
        t0 = time.perf_counter()
        deadline = t0 + timeout_s
        punch_pkt = _MAGIC_PUNCH + token_bytes
        ack_pkt = _MAGIC_ACK + token_bytes
        probes_sent = 0
        punched_addr: tuple[str, int] | None = None

        try:
            idx = 0
            n_ports = len(ports)
            echo_until = deadline
            while time.perf_counter() < (echo_until if punched_addr else deadline):
                if punched_addr is None and idx < n_ports * 2:
                    batch_end = min(idx + 32, n_ports * 2)
                    while idx < batch_end:
                        p = ports[idx % n_ports]
                        try:
                            sock.sendto(punch_pkt, (peer_ip, p))
                            probes_sent += 1
                        except OSError:
                            pass
                        idx += 1

                rlist, _, _ = select.select([sock], [], [], 0.01)
                if not rlist:
                    continue
                for _ in range(64):
                    try:
                        pkt, src = sock.recvfrom(1024)
                    except (BlockingIOError, ConnectionResetError, OSError):
                        break
                    if len(pkt) < 13 or pkt[5:13] != token_bytes:
                        continue
                    magic = pkt[:5]
                    if magic == _MAGIC_PUNCH:
                        if punched_addr is None:
                            punched_addr = (src[0], int(src[1]))
                            echo_until = min(time.perf_counter() + 1.8, deadline + 1.8)
                        for _ in range(3):
                            try:
                                sock.sendto(ack_pkt, src)
                            except OSError:
                                pass
                    elif magic == _MAGIC_ACK:
                        if punched_addr is None:
                            punched_addr = (src[0], int(src[1]))
                            echo_until = min(time.perf_counter() + 1.8, deadline + 1.8)
                    elif magic == _MAGIC_PING and len(pkt) >= 21:
                        if punched_addr is None:
                            punched_addr = (src[0], int(src[1]))
                            echo_until = min(time.perf_counter() + 1.8, deadline + 1.8)
                        pong = _MAGIC_PONG + token_bytes + pkt[13:21]
                        try:
                            sock.sendto(pong, src)
                        except OSError:
                            pass
        finally:
            try:
                sock.close()
            except OSError:
                pass
            elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
            with self._lock:
                entry = self._sessions.get(token)
                if entry is not None:
                    entry["punched"] = punched_addr is not None
                    entry["finished"] = True
                    entry["probes_sent"] = probes_sent
                    entry["remote_addr"] = [punched_addr[0], punched_addr[1]] if punched_addr else None
                    entry["elapsed_ms"] = elapsed_ms


def _measure_direct_rtt(sock: socket.socket, token_bytes: bytes, target: tuple[str, int], count: int = 5) -> list[float]:
    rtts: list[float] = []
    sock.settimeout(0.6)
    for seq in range(count):
        ts_us = int(time.perf_counter_ns() // 1000)
        ping = _MAGIC_PING + token_bytes + _PING_STRUCT.pack(ts_us)
        t0 = time.perf_counter()
        try:
            sock.sendto(ping, target)
            deadline = t0 + 0.45
            while time.perf_counter() < deadline:
                rem = max(0.05, deadline - time.perf_counter())
                sock.settimeout(rem)
                pkt, _ = sock.recvfrom(1024)
                if len(pkt) >= 21 and pkt[:5] == _MAGIC_PONG and pkt[5:13] == token_bytes:
                    rtts.append(round((time.perf_counter() - t0) * 1000.0, 2))
                    break
        except (OSError, socket.timeout):
            continue
    return rtts


def attempt_direct_punch(
    peer_http_base: str,
    num_sockets: int = 192,
    spray_count: int = 900,
    timeout_s: float = 3.5,
    local_test_mode: bool = False,
) -> dict[str, Any]:
    """Attempt Birthday-Paradox P2P UDP hole-punching against peer over Tailscale control plane."""
    t_all = time.perf_counter()
    num_sockets = max(8, min(320, int(num_sockets)))
    timeout_s = max(0.6, min(6.0, float(timeout_s)))

    # Measure baseline Tailscale/HTTP control RTT
    tailscale_rtts: list[float] = []
    base = peer_http_base.rstrip("/")
    for _ in range(3):
        t0 = time.perf_counter()
        with urllib.request.urlopen(f"{base}/api/health", timeout=4.0) as resp:
            resp.read()
        tailscale_rtts.append((time.perf_counter() - t0) * 1000.0)
    tailscale_rtt_ms = round(sorted(tailscale_rtts)[len(tailscale_rtts) // 2], 2)

    if local_test_mode:
        nat_prof = {
            "nat_type": "LOCAL_LOOPBACK",
            "public_ip": "127.0.0.1",
            "public_port": 0,
            "alt_port": 0,
            "port_delta": 0,
            "stun_rtt_ms": 0.1,
        }
    else:
        nat_prof = discover_nat_profile()

    socks: list[socket.socket] = []
    token_bytes = os.urandom(8)
    token = token_bytes.hex()

    try:
        for _ in range(num_sockets):
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            _disable_connreset(s)
            s.bind(("0.0.0.0", 0))
            s.setblocking(False)
            socks.append(s)

        if local_test_mode:
            nat_prof["public_port"] = int(socks[0].getsockname()[1])

        if not nat_prof.get("public_ip"):
            return {
                "punched": False,
                "fallback_mode": "TAILSCALE_FALLBACK",
                "local_nat": nat_prof,
                "tailscale_rtt_ms": tailscale_rtt_ms,
                "direct_rtt_p50_ms": 0.0,
                "speedup_factor": 1.0,
                "diagnosis": "STUN_BLOCKED_ON_LOCAL_NETWORK",
                "elapsed_ms": round((time.perf_counter() - t_all) * 1000.0, 2),
            }

        offer_body = json.dumps(
            {
                "token": token,
                "peer_ip": nat_prof["public_ip"],
                "peer_stun_port": nat_prof["public_port"],
                "peer_nat_type": nat_prof["nat_type"],
                "peer_port_delta": nat_prof.get("port_delta", 0),
                "spray_count": spray_count,
                "timeout_s": timeout_s,
                "local_test_mode": local_test_mode,
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            f"{base}/api/nat/punch-offer",
            data=offer_body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=6.0) as resp:
            offer_ack = json.loads(resp.read().decode("utf-8"))

        resp_addr = (str(offer_ack["responder_pub_ip"]), int(offer_ack["responder_pub_port"]))
        punch_pkt = _MAGIC_PUNCH + token_bytes
        ack_pkt = _MAGIC_ACK + token_bytes

        win_sock: socket.socket | None = None
        win_src: tuple[str, int] | None = None
        waves_sent = 0
        next_wave = time.perf_counter()
        deadline = next_wave + timeout_s

        while time.perf_counter() < deadline and win_sock is None:
            now = time.perf_counter()
            if now >= next_wave and waves_sent < 4:
                for s in socks:
                    try:
                        s.sendto(punch_pkt, resp_addr)
                    except OSError:
                        pass
                waves_sent += 1
                next_wave = now + 0.18

            # Chunk select batches <= 250 sockets (safe across Windows FD_SETSIZE=512)
            for start_i in range(0, len(socks), 250):
                batch = socks[start_i : start_i + 250]
                rlist, _, _ = select.select(batch, [], [], 0.012)
                for rs in rlist:
                    try:
                        pkt, src = rs.recvfrom(1024)
                    except (BlockingIOError, ConnectionResetError, OSError):
                        continue
                    if len(pkt) >= 13 and pkt[:5] in (_MAGIC_PUNCH, _MAGIC_ACK) and pkt[5:13] == token_bytes:
                        win_sock = rs
                        win_src = (src[0], int(src[1]))
                        for _ in range(3):
                            try:
                                rs.sendto(ack_pkt, win_src)
                            except OSError:
                                pass
                        break
                if win_sock is not None:
                    break

        direct_rtts: list[float] = []
        if win_sock is not None and win_src is not None:
            direct_rtts = _measure_direct_rtt(win_sock, token_bytes, win_src, count=5)

        punched = win_sock is not None
        direct_p50 = (
            round(sorted(direct_rtts)[len(direct_rtts) // 2], 2)
            if direct_rtts
            else 0.0
        )
        speedup = (
            round(tailscale_rtt_ms / max(direct_p50, 0.05), 2)
            if (punched and direct_p50 > 0)
            else 1.0
        )
        diagnosis = (
            f"DIRECT_P2P_PIERCED ({nat_prof['nat_type']} -> {offer_ack.get('responder_nat_type')})"
            if punched
            else f"ISP_SYMMETRIC_NAT_BLOCKED_UNSOLICITED_UDP ({nat_prof['nat_type']} -> {offer_ack.get('responder_nat_type')}); KEPT_TAILSCALE_SAFE"
        )
        return {
            "punched": punched,
            "fallback_mode": "DIRECT_P2P_UDP" if punched else "TAILSCALE_FALLBACK",
            "local_nat": nat_prof,
            "responder_nat_type": offer_ack.get("responder_nat_type", ""),
            "responder_addr": f"{resp_addr[0]}:{resp_addr[1]}",
            "sockets_opened": len(socks),
            "waves_sent": waves_sent,
            "tailscale_rtt_ms": tailscale_rtt_ms,
            "direct_rtt_samples_ms": direct_rtts,
            "direct_rtt_p50_ms": direct_p50,
            "speedup_factor": speedup,
            "diagnosis": diagnosis,
            "elapsed_ms": round((time.perf_counter() - t_all) * 1000.0, 2),
        }
    finally:
        for s in socks:
            try:
                s.close()
            except OSError:
                pass
