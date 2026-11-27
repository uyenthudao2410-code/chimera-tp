"""CHIMERA-EGRESS + MEMBRANE: Loopback HTTP/HTTPS Proxy with Singleflight, TTL/ETag Cache, 429 Shield & Wire-Cassette."""

from __future__ import annotations

import collections
import hashlib
import http.client
import http.server
import ipaddress
import json
import math
import random
import re
import select
import socket
import ssl
import struct
import threading
import time
import urllib.parse
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Callable


_DEFAULT_DNS_RESOLVERS: tuple[str, ...] = ("8.8.8.8", "1.1.1.1", "9.9.9.9")


def _is_ip_literal(host: str) -> bool:
    h = host.strip("[]")
    try:
        ipaddress.ip_address(h)
        return True
    except ValueError:
        return False


def _is_local_host(host: str) -> bool:
    h = host.strip().lower().strip("[]")
    return (
        h in ("localhost", "127.0.0.1", "::1", "0.0.0.0")
        or h.startswith("127.")
        or h.endswith(".local")
        or h.endswith(".chimera.local")
    )


def _build_dns_a_query(hostname: str, txid: int) -> bytes:
    """Build a minimal RFC 1035 DNS Type-A (IPv4) query packet (zero dependencies)."""
    header = struct.pack("!HHHHHH", txid & 0xFFFF, 0x0100, 1, 0, 0, 0)
    labels: list[bytes] = []
    for part in hostname.strip(".").split("."):
        try:
            b = part.encode("idna")[:63]
        except UnicodeError:
            b = part.encode("ascii", errors="ignore")[:63]
        if b:
            labels.append(bytes([len(b)]) + b)
    return header + b"".join(labels) + b"\x00" + struct.pack("!HH", 1, 1)


def _skip_dns_name(packet: bytes, offset: int) -> int:
    n = len(packet)
    jumps = 0
    while offset < n and jumps < 16:
        length = packet[offset]
        if length == 0:
            return offset + 1
        if (length & 0xC0) == 0xC0:
            return offset + 2 if offset + 2 <= n else n
        offset += 1 + length
        jumps += 1
    return n


def _parse_dns_a_response(packet: bytes, expected_txid: int) -> tuple[list[str], int]:
    """Parse IPv4 A records and minimum TTL from an RFC 1035 UDP response."""
    if len(packet) < 12:
        return [], 0
    txid, flags, qdcount, ancount, _, _ = struct.unpack("!HHHHHH", packet[:12])
    if txid != (expected_txid & 0xFFFF):
        return [], 0
    if (flags & 0x8000) == 0 or (flags & 0x000F) != 0:
        return [], 0
    off = 12
    for _ in range(qdcount):
        off = _skip_dns_name(packet, off) + 4
        if off > len(packet):
            return [], 0
    ips: list[str] = []
    min_ttl = 300
    for _ in range(ancount):
        off = _skip_dns_name(packet, off)
        if off + 10 > len(packet):
            break
        rtype, rclass, ttl, rdlen = struct.unpack("!HHIH", packet[off : off + 10])
        off += 10
        if off + rdlen > len(packet):
            break
        if rtype == 1 and rclass == 1 and rdlen == 4:
            ip_str = socket.inet_ntoa(packet[off : off + 4])
            if ip_str not in ips:
                ips.append(ip_str)
            if ttl > 0:
                min_ttl = min(min_ttl, max(30, min(600, int(ttl))))
        off += rdlen
    return ips, min_ttl


class _MultiDnsHarvester:
    """Zero-subprocess, select-multiplexed multi-resolver Anycast PoP harvester."""

    def __init__(
        self,
        resolvers: tuple[str, ...] = _DEFAULT_DNS_RESOLVERS,
        *,
        timeout_s: float = 0.28,
        max_entries: int = 256,
        custom_resolver: Callable[[str], list[str]] | None = None,
    ) -> None:
        self.resolvers = tuple(resolvers)
        self.timeout_s = max(0.05, float(timeout_s))
        self.max_entries = max(16, int(max_entries))
        self.custom_resolver = custom_resolver
        self._lock = threading.Lock()
        self._cache: collections.OrderedDict[str, dict[str, Any]] = collections.OrderedDict()

    def _query_udp_resolvers(self, host: str) -> tuple[list[str], int]:
        if not self.resolvers:
            return [], 300
        socks: list[socket.socket] = []
        txids: dict[socket.socket, int] = {}
        ips: list[str] = []
        min_ttl = 300
        try:
            for resolver in self.resolvers:
                try:
                    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    s.setblocking(False)
                    txid = random.randint(1, 65534)
                    pkt = _build_dns_a_query(host, txid)
                    s.sendto(pkt, (resolver, 53))
                    socks.append(s)
                    txids[s] = txid
                except OSError:
                    continue
            if not socks:
                return [], 300
            pending = list(socks)
            deadline = time.monotonic() + self.timeout_s
            first_hit_at: float | None = None
            while pending:
                now = time.monotonic()
                rem = deadline - now
                if rem <= 0:
                    break
                # Once we already have >=2 distinct PoP IPs and waited 60ms after first hit, finish fast
                if first_hit_at is not None and len(ips) >= 2 and (now - first_hit_at) >= 0.06:
                    break
                rlist, _, _ = select.select(pending, [], [], min(rem, 0.05))
                if not rlist:
                    continue
                for s in rlist:
                    try:
                        data, _ = s.recvfrom(2048)
                    except OSError:
                        pending.remove(s)
                        continue
                    parsed_ips, ttl = _parse_dns_a_response(data, txids.get(s, 0))
                    if parsed_ips:
                        if first_hit_at is None:
                            first_hit_at = time.monotonic()
                        for ip in parsed_ips:
                            if ip not in ips:
                                ips.append(ip)
                        if ttl > 0:
                            min_ttl = min(min_ttl, ttl)
                    if s in pending:
                        pending.remove(s)
        finally:
            for s in socks:
                try:
                    s.close()
                except OSError:
                    pass
        return ips, min_ttl

    def resolve(self, host: str, port: int = 443) -> list[str]:
        h = str(host or "").strip().lower().strip("[]")
        if not h:
            return []
        if _is_ip_literal(h):
            return [h]
        now = time.monotonic()
        with self._lock:
            entry = self._cache.get(h)
            if entry is not None and now < float(entry["expires_at"]):
                self._cache.move_to_end(h)
                return list(entry["ips"])

        ips: list[str] = []
        ttl = 300
        if self.custom_resolver is not None:
            try:
                for ip in self.custom_resolver(h) or []:
                    if ip and ip not in ips:
                        ips.append(str(ip))
            except Exception:
                pass
        else:
            if not _is_local_host(h):
                udp_ips, udp_ttl = self._query_udp_resolvers(h)
                ips.extend(udp_ips)
                ttl = min(ttl, max(60, udp_ttl))
            # Always merge OS resolver (handles /etc/hosts, intranet DNS, IPv4 fallback)
            try:
                infos = socket.getaddrinfo(h, port, socket.AF_INET, socket.SOCK_STREAM)
                for info in infos:
                    ip = str(info[4][0])
                    if ip not in ips:
                        ips.append(ip)
            except OSError:
                pass

        if ips:
            with self._lock:
                self._cache[h] = {"ips": list(ips), "expires_at": now + max(60.0, float(ttl))}
                self._cache.move_to_end(h)
                while len(self._cache) > self.max_entries:
                    self._cache.popitem(last=False)
        return ips


class _PopBandit:
    """Per-(host, ip) UCB1 Bandit with circuit-breaker cooldown & LRU Prefix-to-PoP sticky pinning."""

    def __init__(self, max_arms: int = 512, max_pins: int = 256, pin_ttl_s: float = 600.0) -> None:
        self._lock = threading.Lock()
        self._max_arms = max(32, int(max_arms))
        self._max_pins = max(16, int(max_pins))
        self._pin_ttl_s = max(10.0, float(pin_ttl_s))
        self._arms: collections.OrderedDict[tuple[str, str], dict[str, Any]] = collections.OrderedDict()
        self._pins: collections.OrderedDict[tuple[str, str], tuple[str, float]] = collections.OrderedDict()

    @staticmethod
    def _norm_sticky_key(sticky_key: str) -> str:
        s = str(sticky_key or "").strip()
        if not s:
            return ""
        return hashlib.blake2s(s.encode("utf-8", errors="ignore"), digest_size=8).hexdigest()

    def pin(self, host: str, sticky_key: str, ip: str) -> None:
        sk = self._norm_sticky_key(sticky_key)
        if not sk or not ip:
            return
        pkey = (str(host).lower(), sk)
        exp = time.monotonic() + self._pin_ttl_s
        with self._lock:
            self._pins[pkey] = (str(ip), exp)
            self._pins.move_to_end(pkey)
            while len(self._pins) > self._max_pins:
                self._pins.popitem(last=False)

    def get_pin(self, host: str, sticky_key: str) -> str | None:
        sk = self._norm_sticky_key(sticky_key)
        if not sk:
            return None
        pkey = (str(host).lower(), sk)
        now = time.monotonic()
        with self._lock:
            ent = self._pins.get(pkey)
            if ent is None:
                return None
            ip, exp = ent
            if now >= exp:
                self._pins.pop(pkey, None)
                return None
            # Sliding refresh on active sticky pin
            self._pins[pkey] = (ip, now + self._pin_ttl_s)
            self._pins.move_to_end(pkey)
            return ip

    def is_circuit_open(self, host: str, ip: str) -> bool:
        key = (str(host).lower(), str(ip))
        now = time.monotonic()
        with self._lock:
            arm = self._arms.get(key)
            return bool(arm is not None and now < float(arm.get("cooldown_until", 0.0)))

    def pin_snapshot(self) -> list[dict[str, Any]]:
        now = time.monotonic()
        with self._lock:
            out: list[dict[str, Any]] = []
            for (h, sk), (ip, exp) in list(self._pins.items()):
                rem = max(0.0, exp - now)
                if rem <= 0:
                    self._pins.pop((h, sk), None)
                    continue
                arm = self._arms.get((h, ip))
                circuit = "OPEN" if (arm is not None and now < float(arm.get("cooldown_until", 0.0))) else "CLOSED"
                out.append({"host": h, "sticky_hash": sk, "ip": ip, "ttl_rem_s": round(rem, 1), "circuit": circuit})
            return out

    def record(self, host: str, ip: str, ok: bool, ms: float, *, route: str = "direct") -> None:
        key = (str(host).lower(), str(ip))
        now = time.monotonic()
        with self._lock:
            arm = self._arms.get(key)
            if arm is None:
                arm = {
                    "host": key[0],
                    "ip": key[1],
                    "route": route,
                    "attempts": 0,
                    "ok": 0,
                    "fails": 0,
                    "consec_fails": 0,
                    "ewma_ms": max(1.0, float(ms)),
                    "last_ms": round(float(ms), 2),
                    "cooldown_until": 0.0,
                    "updated_at": now,
                }
                self._arms[key] = arm
            self._arms.move_to_end(key)
            arm["attempts"] += 1
            arm["last_ms"] = round(float(ms), 2)
            arm["updated_at"] = now
            if ok:
                arm["ok"] += 1
                arm["consec_fails"] = 0
                arm["cooldown_until"] = 0.0
                if arm["ok"] == 1:
                    arm["ewma_ms"] = max(1.0, float(ms))
                else:
                    arm["ewma_ms"] = 0.7 * float(arm["ewma_ms"]) + 0.3 * max(1.0, float(ms))
            else:
                arm["fails"] += 1
                arm["consec_fails"] += 1
                backoff = min(120.0, 15.0 * (2 ** min(3, arm["consec_fails"] - 1)))
                arm["cooldown_until"] = now + backoff
            while len(self._arms) > self._max_arms:
                self._arms.popitem(last=False)

    def rank(self, host: str, ips: list[str]) -> list[str]:
        h = str(host).lower()
        now = time.monotonic()
        with self._lock:
            total_n = max(1, sum(int(self._arms[(h, ip)]["attempts"]) for ip in ips if (h, ip) in self._arms))
            healthy: list[tuple[float, str]] = []
            cooled: list[tuple[float, str]] = []
            for ip in ips:
                arm = self._arms.get((h, ip))
                if arm is None:
                    # Slight exploration bonus so newly discovered PoPs are tested early
                    healthy.append((1.15, ip))
                    continue
                if now < float(arm["cooldown_until"]):
                    cooled.append((float(arm["cooldown_until"]), ip))
                    continue
                n = max(1, int(arm["attempts"]))
                succ = float(arm["ok"]) / n
                ewma = max(1.0, float(arm["ewma_ms"]))
                ucb = succ * (100.0 / (100.0 + ewma)) + 0.30 * math.sqrt(math.log(total_n + 1.0) / n)
                healthy.append((ucb, ip))
        healthy.sort(key=lambda x: x[0], reverse=True)
        cooled.sort(key=lambda x: x[0])
        return [ip for _, ip in healthy] + [ip for _, ip in cooled]

    def rank_with_pin(self, host: str, ips: list[str], sticky_key: str = "") -> tuple[list[str], str, str]:
        """Rank PoPs while honoring live Prefix-to-PoP sticky pins when their circuit is CLOSED.

        Returns (ordered_ips, pin_state, pinned_ip) where pin_state in {'NONE', 'SET', 'HIT', 'FAILOVER'}.
        """
        ranked = self.rank(host, ips)
        sk = self._norm_sticky_key(sticky_key)
        if not sk or not ranked:
            return ranked, "NONE", ""
        pinned = self.get_pin(host, sticky_key)
        if pinned is None:
            return ranked, "SET", ""
        if pinned in ranked and not self.is_circuit_open(host, pinned):
            ordered = [pinned] + [ip for ip in ranked if ip != pinned]
            return ordered, "HIT", pinned
        return ranked, "FAILOVER", ""

    def snapshot(self) -> list[dict[str, Any]]:
        now = time.monotonic()
        with self._lock:
            out: list[dict[str, Any]] = []
            for arm in self._arms.values():
                n = max(1, int(arm["attempts"]))
                succ = float(arm["ok"]) / n
                ewma = max(1.0, float(arm["ewma_ms"]))
                cd_rem = max(0.0, float(arm["cooldown_until"]) - now)
                out.append(
                    {
                        "host": arm["host"],
                        "ip": arm["ip"],
                        "route": arm["route"],
                        "attempts": arm["attempts"],
                        "ok": arm["ok"],
                        "fails": arm["fails"],
                        "success_pct": round(succ * 100.0, 1),
                        "ewma_ms": round(ewma, 2),
                        "last_ms": arm["last_ms"],
                        "cooldown_rem_s": round(cd_rem, 1),
                        "circuit": "OPEN" if cd_rem > 0 else "CLOSED",
                    }
                )
            return sorted(out, key=lambda x: (x["circuit"] == "OPEN", -x["success_pct"], x["ewma_ms"]))


def _tune_tcp_socket(sock: socket.socket) -> None:
    """Disable Nagle (TCP_NODELAY) and enable TCP keepalive for low-latency SSE/HTTP streaming."""
    try:
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    except OSError:
        pass
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    except OSError:
        pass


def _sendall_nonblocking(sock: socket.socket, data: bytes, timeout_s: float = 10.0) -> None:
    """Safely drain all bytes on a non-blocking socket without raising BlockingIOError under burst load."""
    view = memoryview(data)
    sent = 0
    total = len(view)
    deadline = time.monotonic() + timeout_s
    while sent < total:
        try:
            n = sock.send(view[sent:])
            if n <= 0:
                raise ConnectionResetError("socket send returned 0")
            sent += n
        except (BlockingIOError, ssl.SSLWantWriteError):
            rem = deadline - time.monotonic()
            if rem <= 0:
                raise TimeoutError("non-blocking socket send timed out")
            _, wlist, elist = select.select([], [sock], [sock], min(rem, 0.25))
            if elist or not wlist:
                if time.monotonic() >= deadline:
                    raise TimeoutError("non-blocking socket write stalled")


def _socket_still_alive(sock: socket.socket) -> bool:
    """Verify an idle standby TCP socket has not been remotely closed (FIN/RST)."""
    try:
        err = sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
        if err != 0:
            return False
        rlist, _, elist = select.select([sock], [], [sock], 0.0)
        if elist or rlist:
            # Unexpected data or EOF on an untouched standby socket -> discard
            return False
        return True
    except OSError:
        return False


_DLP_SECRET_RE = re.compile(
    r"(ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9]{20,}|AIza[A-Za-z0-9_\-]{25,}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----)"
)


_HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "proxy-connection",
}


class _ProxyServer(http.server.ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True
    request_queue_size = 128


class EgressMembraneProxy:
    """Bounded Zero-Weight (<16 MB cache) HTTP/HTTPS Egress Proxy with Singleflight + Cache + 429 Shield + Cassette."""

    def __init__(
        self,
        listen_host: str = "127.0.0.1",
        listen_port: int = 9781,
        cassettes_dir: Path | None = None,
        max_cache_bytes: int = 12 * 1024 * 1024,
        max_cache_entries: int = 384,
        default_ttl_s: float = 30.0,
        max_retries: int = 2,
        on_flow: Callable[..., Any] | None = None,
        on_activity: Callable[[str, bool, int], None] | None = None,
        *,
        dns_resolvers: tuple[str, ...] = _DEFAULT_DNS_RESOLVERS,
        custom_resolver: Callable[[str], list[str]] | None = None,
        hedge_delay_ms: float = 120.0,
        connect_attempt_timeout_s: float = 2.5,
        peer_proxy_resolver: Callable[[], str | None] | None = None,
        enable_standby_pool: bool = True,
        standby_ttl_s: float = 15.0,
        max_standby_sockets: int = 8,
        peer_hop_fuse: Callable[[], tuple[bool, str]] | None = None,
        max_peer_hop_tunnels: int = 8,
        peer_auth_secret: str | None = None,
        allow_private_peer_hop: bool = False,
        peer_hedge_delay_ms: float = 350.0,
    ) -> None:
        self.listen_host = listen_host
        self.requested_port = int(listen_port)
        self.cassettes_dir = Path(cassettes_dir) if cassettes_dir else None
        if self.cassettes_dir:
            self.cassettes_dir.mkdir(parents=True, exist_ok=True)
        self.max_cache_bytes = int(max_cache_bytes)
        self.max_cache_entries = int(max_cache_entries)
        self.default_ttl_s = float(default_ttl_s)
        self.max_retries = int(max_retries)
        self.on_flow = on_flow
        self.on_activity = on_activity
        self.hedge_delay_s = max(0.01, float(hedge_delay_ms) / 1000.0)
        self.peer_hedge_delay_s = max(0.05, float(peer_hedge_delay_ms) / 1000.0)
        self.connect_attempt_timeout_s = max(0.2, float(connect_attempt_timeout_s))
        self.peer_proxy_resolver = peer_proxy_resolver
        self.peer_hop_fuse = peer_hop_fuse
        self.peer_auth_secret = peer_auth_secret
        self.allow_private_peer_hop = bool(allow_private_peer_hop)
        self._peer_hop_sem = threading.Semaphore(max(1, int(max_peer_hop_tunnels)))
        self.enable_standby_pool = bool(enable_standby_pool)
        self.standby_ttl_s = max(1.0, float(standby_ttl_s))
        self.max_standby_sockets = max(1, int(max_standby_sockets))

        self._dns = _MultiDnsHarvester(
            resolvers=dns_resolvers,
            custom_resolver=custom_resolver,
        )
        self._pop_bandit = _PopBandit()
        self._standby_lock = threading.Lock()
        self._standby_pool: collections.OrderedDict[tuple[str, int], tuple[socket.socket, str, float]] = collections.OrderedDict()
        self._standby_warming: set[tuple[str, int]] = set()
        self._hot_hosts: dict[tuple[str, int], collections.deque[float]] = {}
        self._closed = False

        self._cache_lock = threading.Lock()
        self._cache: collections.OrderedDict[str, dict[str, Any]] = collections.OrderedDict()
        self._cache_bytes: int = 0

        self._sf_lock = threading.Lock()
        self._inflight: dict[str, dict[str, Any]] = {}

        self._stats_lock = threading.Lock()
        self._stats: dict[str, Any] = {
            "requests_total": 0,
            "cache_hits": 0,
            "etag_revalidated": 0,
            "coalesced_hits": 0,
            "retries_rescued": 0,
            "bypass_count": 0,
            "connect_tunnels": 0,
            "hedged_races": 0,
            "hedged_rescues": 0,
            "pop_failovers": 0,
            "standby_hits": 0,
            "peer_egress_rescues": 0,
            "peer_dual_hedges": 0,
            "peer_fuse_rejects": 0,
            "sticky_pin_hits": 0,
            "sticky_pin_sets": 0,
            "sticky_pin_failovers": 0,
            "errors": 0,
            "bytes_saved": 0,
            "bytes_served": 0,
            "cassettes_recorded": 0,
            "dlp_blocked": 0,
            "hit_ms_sum": 0.0,
            "miss_ms_sum": 0.0,
            "miss_count": 0,
            "per_app": {},
        }
        self._domains: dict[str, dict[str, Any]] = {}
        self.dlp_enabled: bool = True
        self.dlp_allow_hosts: set[str] = {"127.0.0.1", "localhost", "::1", "api.github.com", "api.openai.com", "generativelanguage.googleapis.com"}

        self._httpd: _ProxyServer | None = None
        self._thread: threading.Thread | None = None
        self.addr: tuple[str, int] = (listen_host, 0)

    def start(self) -> "EgressMembraneProxy":
        proxy_ref = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def _do_http(self, method: str) -> None:
                proxy_ref._handle_http(self, method)

            def do_GET(self) -> None:
                self._do_http("GET")

            def do_HEAD(self) -> None:
                self._do_http("HEAD")

            def do_POST(self) -> None:
                self._do_http("POST")

            def do_PUT(self) -> None:
                self._do_http("PUT")

            def do_PATCH(self) -> None:
                self._do_http("PATCH")

            def do_DELETE(self) -> None:
                self._do_http("DELETE")

            def do_OPTIONS(self) -> None:
                self._do_http("OPTIONS")

            def do_CONNECT(self) -> None:
                proxy_ref._handle_connect(self)

            def log_message(self, *_args: object) -> None:
                pass

        # Bind strictly to loopback; if requested port is busy, fall back cleanly to +1 or ephemeral 0
        candidates = [self.requested_port]
        if self.requested_port > 0:
            candidates.extend([self.requested_port + 1, 0])
        last_exc: Exception | None = None
        for p in candidates:
            try:
                self._httpd = _ProxyServer((self.listen_host, int(p)), Handler)
                self.addr = (self.listen_host, int(self._httpd.server_address[1]))
                last_exc = None
                break
            except OSError as exc:
                last_exc = exc
        if last_exc is not None or self._httpd is None:
            raise last_exc or RuntimeError("Failed to bind EgressMembraneProxy")

        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        return self

    def close(self) -> None:
        self._closed = True
        self._clear_standby_pool()
        if self._httpd is not None:
            try:
                self._httpd.shutdown()
                self._httpd.server_close()
            except Exception:
                pass
            self._httpd = None

    def _clear_standby_pool(self) -> None:
        with self._standby_lock:
            items = list(self._standby_pool.values())
            self._standby_pool.clear()
            self._standby_warming.clear()
        for sock, _ip, _exp in items:
            try:
                sock.close()
            except OSError:
                pass

    def _pop_standby(self, host: str, port: int, *, required_ip: str | None = None) -> tuple[socket.socket, str] | None:
        if not self.enable_standby_pool:
            return None
        key = (host.lower(), int(port))
        now = time.monotonic()
        stale: list[socket.socket] = []
        picked: tuple[socket.socket, str] | None = None
        with self._standby_lock:
            for k in list(self._standby_pool.keys()):
                s, _ip, exp = self._standby_pool[k]
                if now >= exp:
                    self._standby_pool.pop(k, None)
                    stale.append(s)
            entry = self._standby_pool.get(key)
            if entry is not None:
                s, ip, _exp = entry
                if required_ip and ip != required_ip:
                    # Preserve standby socket for unpinned/matching callers instead of breaking sticky affinity
                    entry = None
                else:
                    self._standby_pool.pop(key, None)
            if entry is not None:
                s, ip, _exp = entry
                if _socket_still_alive(s):
                    picked = (s, ip)
                else:
                    stale.append(s)
        for s in stale:
            try:
                s.close()
            except OSError:
                pass
        return picked

    def _note_host_heat_and_prewarm(self, host: str, port: int, preferred_ip: str) -> None:
        if not self.enable_standby_pool or self._closed or not preferred_ip:
            return
        key = (host.lower(), int(port))
        now = time.monotonic()
        should_warm = False
        with self._standby_lock:
            dq = self._hot_hosts.setdefault(key, collections.deque(maxlen=8))
            dq.append(now)
            while dq and (now - dq[0]) > 30.0:
                dq.popleft()
            if len(dq) >= 2 and key not in self._standby_pool and key not in self._standby_warming:
                self._standby_warming.add(key)
                should_warm = True
        if not should_warm:
            return

        def _warm() -> None:
            sock: socket.socket | None = None
            try:
                if self._closed:
                    return
                t0 = time.perf_counter()
                sock = socket.create_connection((preferred_ip, int(port)), timeout=min(1.5, self.connect_attempt_timeout_s))
                _tune_tcp_socket(sock)
                ms = (time.perf_counter() - t0) * 1000.0
                self._pop_bandit.record(host, preferred_ip, True, ms)
                evicted: socket.socket | None = None
                with self._standby_lock:
                    if self._closed or key in self._standby_pool:
                        evicted = sock
                        sock = None
                    else:
                        self._standby_pool[key] = (sock, preferred_ip, time.monotonic() + self.standby_ttl_s)
                        self._standby_pool.move_to_end(key)
                        sock = None
                        while len(self._standby_pool) > self.max_standby_sockets:
                            _, (old_s, _old_ip, _old_exp) = self._standby_pool.popitem(last=False)
                            evicted = old_s
                if evicted is not None:
                    try:
                        evicted.close()
                    except OSError:
                        pass
            except OSError:
                if sock is not None:
                    try:
                        sock.close()
                    except OSError:
                        pass
            finally:
                with self._standby_lock:
                    self._standby_warming.discard(key)

        threading.Thread(target=_warm, name=f"chimera-prewarm-{port}", daemon=True).start()

    def _dial_via_peer_proxy(
        self,
        host: str,
        port: int,
        timeout_s: float = 5.0,
        *,
        sticky_key: str = "",
    ) -> tuple[socket.socket, str] | None:
        if self.peer_proxy_resolver is None or _is_local_host(host):
            return None
        try:
            peer_url = self.peer_proxy_resolver()
        except Exception:
            return None
        if not peer_url:
            return None
        parsed = urllib.parse.urlsplit(str(peer_url))
        phost = parsed.hostname or ""
        pport = int(parsed.port or 9781)
        if not phost:
            return None
        plabel = f"peer:{phost}:{pport}"
        if self._pop_bandit.is_circuit_open(host, plabel):
            return None
        sock: socket.socket | None = None
        t0 = time.perf_counter()
        try:
            sock = socket.create_connection((phost, pport), timeout=timeout_s)
            _tune_tcp_socket(sock)
            sock.settimeout(timeout_s)
            hdr_lines = [
                f"CONNECT {host}:{int(port)} HTTP/1.1",
                f"Host: {host}:{int(port)}",
                "X-Chimera-App: peer-failover",
                "X-Chimera-Peer-Hop: 1",
            ]
            if sticky_key:
                hdr_lines.append(f"X-Chimera-Sticky-Key: {sticky_key[:128]}")
            auth_tok = self.peer_auth_secret
            if auth_tok is None:
                try:
                    from .peer_guard import load_peer_secret

                    auth_tok = load_peer_secret()
                except Exception:
                    auth_tok = ""
            if auth_tok:
                hdr_lines.append(f"X-Chimera-Peer-Auth: {auth_tok}")
            req = ("\r\n".join(hdr_lines) + "\r\n\r\n").encode("ascii", errors="ignore")
            sock.sendall(req)
            buf = b""
            while b"\r\n\r\n" not in buf:
                chunk = sock.recv(4096)
                if not chunk:
                    raise OSError("peer proxy closed during CONNECT")
                buf += chunk
                if len(buf) > 16384:
                    raise OSError("peer proxy CONNECT header overflow")
            first_line = buf.split(b"\r\n", 1)[0]
            if b" 200 " not in first_line:
                raise OSError(f"peer proxy CONNECT rejected: {first_line!r}")
            sock.settimeout(None)
            return sock, plabel
        except Exception:
            ms = (time.perf_counter() - t0) * 1000.0
            self._pop_bandit.record(host, plabel, False, ms, route="peer")
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass
            return None

    @staticmethod
    def _is_global_ip(ip_str: str) -> bool:
        try:
            return bool(ipaddress.ip_address(str(ip_str)).is_global)
        except ValueError:
            return False

    def _hedged_connect(
        self,
        host: str,
        port: int,
        *,
        timeout_s: float = 10.0,
        allow_standby: bool = True,
        allow_peer_failover: bool = True,
        sticky_key: str = "",
        sticky_mode: str = "soft",
        hemisphere_mode: str = "failover",
        require_public_ip: bool = False,
    ) -> tuple[socket.socket, str, str, float]:
        sock, ip, route, ms, _pin = self._hedged_connect_ex(
            host,
            port,
            timeout_s=timeout_s,
            allow_standby=allow_standby,
            allow_peer_failover=allow_peer_failover,
            sticky_key=sticky_key,
            sticky_mode=sticky_mode,
            hemisphere_mode=hemisphere_mode,
            require_public_ip=require_public_ip,
        )
        return sock, ip, route, ms

    def _hedged_connect_ex(
        self,
        host: str,
        port: int,
        *,
        timeout_s: float = 10.0,
        allow_standby: bool = True,
        allow_peer_failover: bool = True,
        sticky_key: str = "",
        sticky_mode: str = "soft",
        hemisphere_mode: str = "failover",
        require_public_ip: bool = False,
    ) -> tuple[socket.socket, str, str, float, str]:
        """Connect using Sticky Pin + Standby Pool -> Multi-PoP UCB1 Hedged Race -> Dual-Hemisphere Peer Failover.

        Returns (socket, winner_ip_or_peer, route_tag, connect_ms, pin_state).
        """
        t0 = time.perf_counter()
        h = str(host or "").strip()
        p = int(port)
        skey = str(sticky_key or "").strip()
        smode = str(sticky_mode or "soft").strip().lower()
        hmode = str(hemisphere_mode or "failover").strip().lower()

        raw_ips = self._dns.resolve(h, p)
        if require_public_ip:
            raw_ips = [ip for ip in raw_ips if self._is_global_ip(ip)]
            if not raw_ips:
                raise PermissionError(f"peer_hop_private_target_blocked:{h}")

        candidates, pin_state, pinned_ip = self._pop_bandit.rank_with_pin(h, raw_ips, skey)
        candidates = candidates[:4]

        # 1. Zero-RTT pre-warmed standby socket hit (honors sticky pin IP when set!)
        if allow_standby and (not skey or pinned_ip):
            warm = self._pop_standby(h, p, required_ip=(pinned_ip or None))
            if warm is not None:
                sock, ip = warm
                ms = (time.perf_counter() - t0) * 1000.0
                if skey:
                    self._pop_bandit.pin(h, skey, ip)
                self._note_host_heat_and_prewarm(h, p, ip)
                return sock, ip, "standby", ms, (pin_state if skey else "NONE")

        if not candidates:
            if require_public_ip:
                raise PermissionError(f"peer_hop_no_public_ip:{h}")
            sock = socket.create_connection((h, p), timeout=timeout_s)
            _tune_tcp_socket(sock)
            ms = (time.perf_counter() - t0) * 1000.0
            peer_ip = str(sock.getpeername()[0])
            self._pop_bandit.record(h, peer_ip, True, ms)
            if skey:
                self._pop_bandit.pin(h, skey, peer_ip)
            return sock, peer_ip, "direct", ms, ("SET" if skey else "NONE")

        # Single IP fast path (unless dual-hemisphere hedging is enabled)
        if len(candidates) == 1 and hmode != "dual":
            ip = candidates[0]
            try:
                sock = socket.create_connection((ip, p), timeout=min(timeout_s, self.connect_attempt_timeout_s))
                _tune_tcp_socket(sock)
                ms = (time.perf_counter() - t0) * 1000.0
                self._pop_bandit.record(h, ip, True, ms)
                if skey:
                    self._pop_bandit.pin(h, skey, ip)
                if allow_standby and not _is_local_host(h):
                    self._note_host_heat_and_prewarm(h, p, ip)
                return sock, ip, "direct", ms, pin_state
            except OSError:
                ms = (time.perf_counter() - t0) * 1000.0
                self._pop_bandit.record(h, ip, False, ms)
                if allow_peer_failover:
                    peer_res = self._dial_via_peer_proxy(h, p, timeout_s=min(timeout_s, 5.0), sticky_key=skey)
                    if peer_res is not None:
                        psock, plabel = peer_res
                        pms = (time.perf_counter() - t0) * 1000.0
                        self._pop_bandit.record(h, plabel, True, pms, route="peer")
                        return psock, plabel, "peer", pms, ("FAILOVER" if skey else "NONE")
                raise

        # 3. Staggered Happy-Eyeballs / Hedged TCP Race across PoP IPs (+ optional Dual-Hemisphere peer hedge)
        win_lock = threading.Lock()
        winner_ev = threading.Event()
        all_done_ev = threading.Event()
        state: dict[str, Any] = {
            "sock": None,
            "ip": "",
            "idx": -1,
            "is_peer": False,
            "errors": [],
            "started": 0,
            "finished": 0,
            "all_launched": False,
        }
        attempt_timeout = min(timeout_s, self.connect_attempt_timeout_s)

        def _try_ip(idx: int, ip: str) -> None:
            ts = time.perf_counter()
            s: socket.socket | None = None
            try:
                s = socket.create_connection((ip, p), timeout=attempt_timeout)
                _tune_tcp_socket(s)
                dur_ms = (time.perf_counter() - ts) * 1000.0
                self._pop_bandit.record(h, ip, True, dur_ms)
                claimed = False
                with win_lock:
                    if state["sock"] is None:
                        state["sock"] = s
                        state["ip"] = ip
                        state["idx"] = idx
                        state["is_peer"] = False
                        claimed = True
                        winner_ev.set()
                    state["finished"] += 1
                    if state["all_launched"] and state["finished"] >= state["started"]:
                        all_done_ev.set()
                if not claimed and s is not None:
                    try:
                        s.close()
                    except OSError:
                        pass
            except Exception as exc:
                dur_ms = (time.perf_counter() - ts) * 1000.0
                self._pop_bandit.record(h, ip, False, dur_ms)
                if s is not None:
                    try:
                        s.close()
                    except OSError:
                        pass
                with win_lock:
                    state["errors"].append(f"{ip}:{exc}")
                    state["finished"] += 1
                    if state["all_launched"] and state["finished"] >= state["started"]:
                        all_done_ev.set()

        def _try_peer() -> None:
            ts = time.perf_counter()
            peer_res = self._dial_via_peer_proxy(h, p, timeout_s=min(timeout_s, 5.0), sticky_key=skey)
            if peer_res is not None:
                psock, plabel = peer_res
                dur_ms = (time.perf_counter() - ts) * 1000.0
                self._pop_bandit.record(h, plabel, True, dur_ms, route="peer")
                claimed = False
                with win_lock:
                    if state["sock"] is None:
                        state["sock"] = psock
                        state["ip"] = plabel
                        state["idx"] = 99
                        state["is_peer"] = True
                        claimed = True
                        winner_ev.set()
                    state["finished"] += 1
                    if state["all_launched"] and state["finished"] >= state["started"]:
                        all_done_ev.set()
                if not claimed:
                    try:
                        psock.close()
                    except OSError:
                        pass
            else:
                with win_lock:
                    state["errors"].append("peer:failed")
                    state["finished"] += 1
                    if state["all_launched"] and state["finished"] >= state["started"]:
                        all_done_ev.set()

        def _launch(idx: int, ip: str) -> None:
            with win_lock:
                state["started"] += 1
            threading.Thread(target=_try_ip, args=(idx, ip), name=f"chimera-race-{idx}", daemon=True).start()

        # Primary grace delay: sticky-pinned PoP gets slightly longer grace (250ms) to avoid KV-cache churn
        primary_delay = max(self.hedge_delay_s, 0.25) if (pin_state == "HIT" and smode == "soft") else self.hedge_delay_s
        if pin_state == "HIT" and smode == "strict":
            primary_delay = min(attempt_timeout, 1.5)

        _launch(0, candidates[0])
        if len(candidates) > 1 and not winner_ev.wait(timeout=primary_delay):
            _launch(1, candidates[1])
            if len(candidates) > 2 and not winner_ev.wait(timeout=self.hedge_delay_s):
                for idx in range(2, len(candidates)):
                    _launch(idx, candidates[idx])

        # Opt-in Dual-Hemisphere adaptive peer hedge (win-desktop <-> svhome concurrent race)
        if hmode == "dual" and allow_peer_failover and self.peer_proxy_resolver is not None and not winner_ev.is_set():
            rem_peer_wait = max(0.0, self.peer_hedge_delay_s - (time.perf_counter() - t0))
            if rem_peer_wait == 0.0 or not winner_ev.wait(timeout=rem_peer_wait):
                with win_lock:
                    state["started"] += 1
                threading.Thread(target=_try_peer, name="chimera-peer-hedge", daemon=True).start()

        with win_lock:
            state["all_launched"] = True
            if state["finished"] >= state["started"]:
                all_done_ev.set()

        deadline = t0 + min(timeout_s, attempt_timeout + 0.5)
        while not winner_ev.is_set() and not all_done_ev.is_set():
            rem = deadline - time.perf_counter()
            if rem <= 0:
                break
            winner_ev.wait(timeout=min(rem, 0.05))

        with win_lock:
            win_sock = state["sock"]
            win_ip = str(state["ip"])
            win_idx = int(state["idx"])
            win_is_peer = bool(state["is_peer"])
            errs = list(state["errors"])

        if win_sock is not None:
            ms = (time.perf_counter() - t0) * 1000.0
            if win_is_peer:
                return win_sock, win_ip, "peer-hedge", ms, ("FAILOVER" if skey else "NONE")
            route_tag = "hedged" if win_idx > 0 else "direct"
            final_pin = pin_state
            if skey:
                if pin_state == "HIT" and win_ip != pinned_ip:
                    final_pin = "FAILOVER"
                self._pop_bandit.pin(h, skey, win_ip)
            if allow_standby and not _is_local_host(h):
                self._note_host_heat_and_prewarm(h, p, win_ip)
            return win_sock, win_ip, route_tag, ms, final_pin

        # 4. Last-resort Peer-Egress Failover (e.g. svhome:9781 over PHANTOM-5MS)
        if allow_peer_failover and hmode != "dual":
            peer_res = self._dial_via_peer_proxy(h, p, timeout_s=min(timeout_s, 5.0), sticky_key=skey)
            if peer_res is not None:
                psock, plabel = peer_res
                pms = (time.perf_counter() - t0) * 1000.0
                self._pop_bandit.record(h, plabel, True, pms, route="peer")
                return psock, plabel, "peer", pms, ("FAILOVER" if skey else "NONE")

        raise OSError(f"all PoP candidates failed for {h}:{p}: {'; '.join(errs[:4])}")

    @property
    def url(self) -> str:
        return f"http://{self.addr[0]}:{self.addr[1]}"

    def _bump(self, app: str, **deltas: Any) -> None:
        with self._stats_lock:
            for k, v in deltas.items():
                self._stats[k] = self._stats.get(k, 0) + v
            if app:
                pa = self._stats["per_app"].setdefault(app, {"requests": 0, "hits": 0, "bytes_saved": 0})
                pa["requests"] += int(deltas.get("requests_total", 0))
                pa["hits"] += int(deltas.get("cache_hits", 0)) + int(deltas.get("coalesced_hits", 0))
                pa["bytes_saved"] += int(deltas.get("bytes_saved", 0))

    def _cache_key(self, method: str, url: str) -> str:
        return f"{method.upper()}:{url}"

    def _cache_get(self, key: str) -> tuple[dict[str, Any] | None, bool]:
        now = time.monotonic()
        with self._cache_lock:
            entry = self._cache.get(key)
            if entry is None:
                return None, False
            self._cache.move_to_end(key)
            fresh = now < float(entry["expires_at"])
            return dict(entry), fresh

    def _cache_put(self, key: str, status: int, headers: list[tuple[str, str]], body: bytes, ttl_s: float) -> None:
        if len(body) > max(1024 * 1024, self.max_cache_bytes // 4):
            return
        etag = ""
        for hk, hv in headers:
            if hk.lower() == "etag":
                etag = hv
                break
        item = {
            "status": int(status),
            "headers": list(headers),
            "body": body,
            "etag": etag,
            "size": len(body),
            "expires_at": time.monotonic() + max(0.05, ttl_s),
        }
        with self._cache_lock:
            old = self._cache.pop(key, None)
            if old is not None:
                self._cache_bytes -= int(old["size"])
            self._cache[key] = item
            self._cache_bytes += item["size"]
            while (
                len(self._cache) > self.max_cache_entries
                or self._cache_bytes > self.max_cache_bytes
            ) and self._cache:
                _, evicted = self._cache.popitem(last=False)
                self._cache_bytes -= int(evicted["size"])

    def _parse_ttl(self, headers: list[tuple[str, str]], override_hdr: str | None) -> float:
        for name, value in headers:
            low = value.lower()
            if (name.lower() == "set-cookie"
                    or name.lower() == "vary" and "*" in low
                    or name.lower() == "cache-control" and any(k in low for k in ("private", "no-cache", "no-store"))):
                return 0.0
        if override_hdr:
            try:
                return max(0.0, min(3600.0, float(override_hdr)))
            except ValueError:
                pass
        for hk, hv in headers:
            if hk.lower() == "cache-control":
                low = hv.lower()
                if "no-store" in low:
                    return 0.0
                for part in low.split(","):
                    part = part.strip()
                    if part.startswith("max-age="):
                        try:
                            return max(0.0, min(3600.0, float(part.split("=", 1)[1])))
                        except ValueError:
                            pass
        return self.default_ttl_s

    def _record_cassette(
        self,
        app: str,
        method: str,
        url: str,
        req_headers: dict[str, str],
        status: int,
        resp_headers: list[tuple[str, str]],
        body: bytes,
        error: str = "",
    ) -> str | None:
        if self.cassettes_dir is None:
            return None
        ts = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S_%f")
        h = hashlib.blake2s(f"{method}:{url}:{ts}".encode("utf-8"), digest_size=4).hexdigest()
        name = f"cassette_{ts}_{h}.json"
        path = self.cassettes_dir / name
        safe_req_hdrs = {
            k: ("***" if k.lower() in ("authorization", "cookie", "x-api-key", "x-chimera-token") else v)
            for k, v in req_headers.items()
        }
        rec = {
            "id": name,
            "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
            "app": app,
            "method": method,
            "url": url,
            "request_headers": safe_req_hdrs,
            "status": status,
            "response_headers": resp_headers,
            "body_preview": body[:4096].decode("utf-8", errors="replace"),
            "body_size": len(body),
            "error": error,
        }
        try:
            path.write_text(json.dumps(rec, indent=2, ensure_ascii=False), encoding="utf-8")
            # Keep newest 50 cassettes only
            files = sorted(self.cassettes_dir.glob("cassette_*.json"))
            for old in files[:-50]:
                try:
                    old.unlink()
                except OSError:
                    pass
            self._bump(app, cassettes_recorded=1)
            return name
        except OSError:
            return None

    def list_cassettes(self, limit: int = 20) -> list[dict[str, Any]]:
        if self.cassettes_dir is None or not self.cassettes_dir.is_dir():
            return []
        files = sorted(self.cassettes_dir.glob("cassette_*.json"), reverse=True)[: max(1, limit)]
        out: list[dict[str, Any]] = []
        for f in files:
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
                out.append(
                    {
                        "id": d.get("id", f.name),
                        "ts": d.get("ts"),
                        "app": d.get("app"),
                        "method": d.get("method"),
                        "url": d.get("url"),
                        "status": d.get("status"),
                        "error": d.get("error", ""),
                    }
                )
            except Exception:
                continue
        return out

    def get_cassette(self, cid: str) -> dict[str, Any] | None:
        if self.cassettes_dir is None:
            return None
        safe = Path(cid).name
        p = self.cassettes_dir / safe
        if not p.is_file():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None

    def _upstream_fetch(
        self,
        method: str,
        url: str,
        req_headers: dict[str, str],
        req_body: bytes,
        allow_retry: bool,
        timeout_s: float = 15.0,
    ) -> tuple[int, list[tuple[str, str]], bytes, int]:
        parsed = urllib.parse.urlsplit(url)
        scheme = parsed.scheme.lower() or "http"
        host = parsed.hostname or ""
        port = parsed.port or (443 if scheme == "https" else 80)
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"

        clean_headers = {
            k: v
            for k, v in req_headers.items()
            if k.lower() not in _HOP_BY_HOP and not k.lower().startswith("x-chimera-")
        }
        clean_headers["Host"] = parsed.netloc
        clean_headers.setdefault("Accept-Encoding", "identity")

        attempts = (self.max_retries + 1) if allow_retry else 1
        retries_used = 0
        last_status = 502
        last_headers: list[tuple[str, str]] = []
        last_body = b""

        sticky_key = str(
            req_headers.get("X-Chimera-Sticky-Key")
            or req_headers.get("X-Chimera-Prefix-Sticky")
            or req_headers.get("x-chimera-sticky-key")
            or req_headers.get("x-chimera-prefix-sticky")
            or ""
        ).strip()
        is_peer_hop = str(req_headers.get("X-Chimera-Peer-Hop") or req_headers.get("x-chimera-peer-hop") or "").strip() == "1"
        hemisphere_mode = str(req_headers.get("X-Chimera-Hemisphere") or req_headers.get("x-chimera-hemisphere") or "failover").strip().lower()
        proxy_ref = self

        class _HedgedHTTPConnection(http.client.HTTPConnection):
            def connect(self) -> None:
                sock, _ip, _route, _ms = proxy_ref._hedged_connect(
                    self.host,
                    self.port,
                    timeout_s=float(self.timeout or 10.0),
                    allow_standby=False,
                    allow_peer_failover=not is_peer_hop,
                    sticky_key=sticky_key,
                    hemisphere_mode=hemisphere_mode,
                )
                sock.settimeout(self.timeout)
                self.sock = sock

        class _HedgedHTTPSConnection(http.client.HTTPSConnection):
            def connect(self) -> None:
                raw_sock, _ip, _route, _ms = proxy_ref._hedged_connect(
                    self.host,
                    self.port,
                    timeout_s=float(self.timeout or 10.0),
                    allow_standby=False,
                    allow_peer_failover=not is_peer_hop,
                    sticky_key=sticky_key,
                    hemisphere_mode=hemisphere_mode,
                )
                raw_sock.settimeout(self.timeout)
                self.sock = self._context.wrap_socket(raw_sock, server_hostname=self.host)

        for idx in range(attempts):
            conn: http.client.HTTPConnection | None = None
            try:
                if scheme == "https":
                    ctx = ssl.create_default_context()
                    conn = _HedgedHTTPSConnection(host, port, timeout=timeout_s, context=ctx)
                else:
                    conn = _HedgedHTTPConnection(host, port, timeout=timeout_s)
                conn.request(method, path, body=req_body if req_body else None, headers=clean_headers)
                resp = conn.getresponse()
                body = resp.read()
                hdrs = [(k, v) for k, v in resp.getheaders() if k.lower() not in _HOP_BY_HOP]
                last_status, last_headers, last_body = resp.status, hdrs, body
                if resp.status in (429, 502, 503, 504) and allow_retry and idx < attempts - 1:
                    ra = resp.getheader("Retry-After")
                    delay = 0.08 * (idx + 1)
                    if ra:
                        try:
                            delay = float(ra)
                        except ValueError:
                            try:
                                delay = parsedate_to_datetime(ra).timestamp() - time.time()
                            except (ValueError, TypeError, OverflowError):
                                return resp.status, hdrs, body, retries_used
                        if not math.isfinite(delay) or delay > 1.5:
                            return resp.status, hdrs, body, retries_used
                        delay = max(0.02, delay)
                    retries_used += 1
                    time.sleep(delay)
                    continue
                return resp.status, hdrs, body, retries_used
            except Exception as exc:
                last_status = 502
                last_headers = [("Content-Type", "application/json")]
                last_body = json.dumps({"error": f"upstream_failed: {exc}"}).encode("utf-8")
                if allow_retry and idx < attempts - 1:
                    retries_used += 1
                    time.sleep(0.06 * (idx + 1))
                    continue
                return last_status, last_headers, last_body, retries_used
            finally:
                if conn is not None:
                    try:
                        conn.close()
                    except Exception:
                        pass
        return last_status, last_headers, last_body, retries_used

    def _send_reply(
        self,
        handler: http.server.BaseHTTPRequestHandler,
        status: int,
        headers: list[tuple[str, str]],
        body: bytes,
        membrane_tag: str,
        elapsed_ms: float,
        retries: int = 0,
        cassette_id: str | None = None,
    ) -> None:
        handler.send_response(status)
        has_cl = False
        for k, v in headers:
            kl = k.lower()
            if kl in _HOP_BY_HOP:
                continue
            if kl == "content-length":
                has_cl = True
                handler.send_header("Content-Length", str(len(body)))
            else:
                handler.send_header(k, v)
        if not has_cl:
            handler.send_header("Content-Length", str(len(body)))
        handler.send_header("X-Chimera-Membrane", membrane_tag)
        handler.send_header("X-Chimera-Elapsed-Ms", f"{elapsed_ms:.2f}")
        if retries > 0:
            handler.send_header("X-Chimera-Retries", str(retries))
        if cassette_id:
            handler.send_header("X-Chimera-Cassette", cassette_id)
        handler.send_header("Connection", "close")
        handler.end_headers()
        if handler.command != "HEAD":
            handler.wfile.write(body)
        # Only the upstream request owner observes a forward. Cache and singleflight
        # followers can still serve clients when an upstream has stopped responding.
        if (self.on_activity is not None and
                membrane_tag.partition("+")[0] in {"MISS", "REVALIDATED", "BYPASS"}):
            try:
                self.on_activity("egress.forward", 200 <= status < 300, status)
            except Exception:
                pass

    def _handle_http(self, handler: http.server.BaseHTTPRequestHandler, method: str) -> None:
        t0 = time.perf_counter()
        url = handler.path
        if not url.startswith(("http://", "https://")):
            host_hdr = handler.headers.get("Host", "")
            if host_hdr:
                url = f"http://{host_hdr}{url}"
            else:
                self._send_reply(
                    handler,
                    400,
                    [("Content-Type", "application/json")],
                    b'{"error":"absolute_url_required"}',
                    "ERROR",
                    0.0,
                )
                return

        app = str(handler.headers.get("X-Chimera-App") or "external")
        bypass = str(handler.headers.get("X-Chimera-Bypass") or "").strip() in ("1", "true", "yes")
        force_record = str(handler.headers.get("X-Chimera-Record") or "").strip() in ("1", "true", "yes")
        ttl_override = handler.headers.get("X-Chimera-TTL")
        clen = int(handler.headers.get("Content-Length", "0") or 0)
        req_body = handler.rfile.read(clen) if clen > 0 else b""
        req_headers = {k: v for k, v in handler.headers.items()}
        sensitive = {"authorization", "proxy-authorization", "cookie", "x-api-key", "x-auth-token", "range"}
        lowered = {k.lower(): v for k, v in req_headers.items()}
        request_policy = lowered.get("cache-control", "").lower()
        cacheable_method = (method in ("GET", "HEAD") and not bypass and not sensitive.intersection(lowered)
                            and not req_body and not any(p in request_policy for p in ("no-cache", "no-store"))
                            and not any(k.startswith("if-") for k in lowered))
        variants = sorted((k, v) for k, v in lowered.items() if k not in _HOP_BY_HOP and not k.startswith("x-chimera-"))
        variant_key = hashlib.sha256(json.dumps([url, variants], ensure_ascii=True).encode()).hexdigest()
        ckey = self._cache_key(method, variant_key)

        self._bump(app, requests_total=1)

        # 0. Zero-Leak Egress Cryptographic DLP Sentinel (<50 us)
        target_host = (urllib.parse.urlsplit(url).hostname or "").lower()
        if self.dlp_enabled and target_host and target_host not in self.dlp_allow_hosts:
            probe_blob = url + "\n" + req_body[:8192].decode("utf-8", errors="ignore")
            m_dlp = _DLP_SECRET_RE.search(probe_blob)
            if m_dlp:
                self._bump(app, dlp_blocked=1)
                ms = (time.perf_counter() - t0) * 1000.0
                body_blk = json.dumps(
                    {
                        "error": "chimera_dlp_secret_leak_blocked",
                        "host": target_host,
                        "app": app,
                        "pattern_prefix": m_dlp.group(1)[:6] + "***",
                    }
                ).encode("utf-8")
                self._send_reply(
                    handler,
                    403,
                    [("Content-Type", "application/json"), ("X-Chimera-DLP", "BLOCKED")],
                    body_blk,
                    "DLP_BLOCKED",
                    ms,
                )
                return

        if bypass:
            self._bump(app, bypass_count=1)
            st, hdrs, body, _ = self._upstream_fetch(method, url, req_headers, req_body, allow_retry=False)
            ms = (time.perf_counter() - t0) * 1000.0
            self._bump(app, bytes_served=len(body), miss_ms_sum=ms, miss_count=1)
            self._send_reply(handler, st, hdrs, body, "BYPASS", ms)
            return

        # 1. Fast Membrane Cache lookup
        cached_entry: dict[str, Any] | None = None
        if cacheable_method:
            cached_entry, is_fresh = self._cache_get(ckey)
            if cached_entry is not None and is_fresh:
                ms = (time.perf_counter() - t0) * 1000.0
                body = cached_entry["body"]
                self._bump(app, cache_hits=1, bytes_saved=len(body), bytes_served=len(body), hit_ms_sum=ms)
                self._send_reply(handler, cached_entry["status"], cached_entry["headers"], body, "HIT", ms)
                return

        # 2. Cross-request Singleflight Coalescing for concurrent idempotent GET/HEAD
        leader = True
        sf_slot: dict[str, Any] | None = None
        if cacheable_method:
            with self._sf_lock:
                existing = self._inflight.get(ckey)
                if existing is not None:
                    leader = False
                    sf_slot = existing
                else:
                    sf_slot = {"event": threading.Event(), "result": None}
                    self._inflight[ckey] = sf_slot

        if not leader and sf_slot is not None:
            sf_slot["event"].wait(timeout=20.0)
            res = sf_slot.get("result")
            if res is not None:
                st, hdrs, body, retries = res
                ms = (time.perf_counter() - t0) * 1000.0
                self._bump(app, coalesced_hits=1, bytes_saved=len(body), bytes_served=len(body), hit_ms_sum=ms)
                self._send_reply(handler, st, hdrs, body, "COALESCED", ms, retries=retries)
                return

        # 3. Leader executes upstream fetch (with ETag conditional GET + 429/502 retry shield)
        try:
            fetch_hdrs = dict(req_headers)
            if cached_entry is not None and cached_entry.get("etag"):
                fetch_hdrs["If-None-Match"] = str(cached_entry["etag"])
            st, hdrs, body, retries = self._upstream_fetch(
                method, url, fetch_hdrs, req_body, allow_retry=(method in ("GET", "HEAD", "OPTIONS"))
            )
            membrane_tag = "MISS"
            if st == 304 and cached_entry is not None:
                st = cached_entry["status"]
                hdrs = cached_entry["headers"]
                body = cached_entry["body"]
                membrane_tag = "REVALIDATED"
                ttl_s = self._parse_ttl(hdrs, ttl_override)
                if ttl_s > 0:
                    self._cache_put(ckey, st, hdrs, body, ttl_s)
                self._bump(app, etag_revalidated=1, bytes_saved=len(body))
            elif cacheable_method and 200 <= st < 300:
                ttl_s = self._parse_ttl(hdrs, ttl_override)
                if ttl_s > 0:
                    self._cache_put(ckey, st, hdrs, body, ttl_s)

            if retries > 0 and st < 400:
                self._bump(app, retries_rescued=1)
                membrane_tag = f"{membrane_tag}+RESCUED"

            cid: str | None = None
            if st >= 500 or st == 429 or force_record:
                if st >= 500 or st == 429:
                    self._bump(app, errors=1)
                private_reply = any(k.lower() == "set-cookie" or
                                    (k.lower() == "cache-control" and any(x in v.lower() for x in ("private", "no-store")))
                                    for k, v in hdrs)
                if not sensitive.intersection(lowered) and not private_reply:
                    cid = self._record_cassette(app, method, url, req_headers, st, hdrs, body)

            if sf_slot is not None and self._parse_ttl(hdrs, ttl_override) > 0 and 200 <= st < 300:
                sf_slot["result"] = (st, hdrs, body, retries)
            ms = (time.perf_counter() - t0) * 1000.0
            self._bump(app, bytes_served=len(body), miss_ms_sum=ms, miss_count=1)
            self._record_domain_ucb1(target_host, st, ms)
            if self.on_flow is not None:
                try:
                    self.on_flow(
                        "edge",
                        app,
                        urllib.parse.urlsplit(url).hostname or "upstream",
                        f"EGRESS_{membrane_tag}",
                        wire_bytes=len(body),
                        elapsed_ms=ms,
                        detail=f"{method} {st} {url[:60]}",
                        ok=(st < 500),
                    )
                except Exception:
                    pass
            self._send_reply(handler, st, hdrs, body, membrane_tag, ms, retries=retries, cassette_id=cid)
        finally:
            if leader and sf_slot is not None:
                sf_slot["event"].set()
                with self._sf_lock:
                    if self._inflight.get(ckey) is sf_slot:
                        self._inflight.pop(ckey, None)

    def _handle_connect(self, handler: http.server.BaseHTTPRequestHandler) -> None:
        t0 = time.perf_counter()
        app = str(handler.headers.get("X-Chimera-App") or "external")
        is_peer_hop = str(handler.headers.get("X-Chimera-Peer-Hop") or "").strip() == "1"
        sticky_key = str(
            handler.headers.get("X-Chimera-Sticky-Key")
            or handler.headers.get("X-Chimera-Prefix-Sticky")
            or ""
        ).strip()
        sticky_mode = str(handler.headers.get("X-Chimera-Sticky-Mode") or "soft").strip().lower()
        hemisphere_mode = str(handler.headers.get("X-Chimera-Hemisphere") or "failover").strip().lower()
        self._bump(app, requests_total=1, connect_tunnels=1)
        host, _, port_s = handler.path.partition(":")
        port = int(port_s) if port_s.isdigit() else 443
        upstream: socket.socket | None = None
        peer_slot_acquired = False
        try:
            if is_peer_hop:
                # 1. Peer shared-secret authentication (when configured)
                from .peer_guard import verify_peer_auth

                if not verify_peer_auth(handler.headers.get("X-Chimera-Peer-Auth"), expected=self.peer_auth_secret):
                    self._bump(app, errors=1, peer_fuse_rejects=1)
                    handler.send_response(403, "Peer Auth Failed")
                    handler.send_header("X-Chimera-Peer-Fuse", "AUTH_DENIED")
                    handler.send_header("Content-Length", "0")
                    handler.end_headers()
                    return
                # 2. Lock-free peer_guard hardware/RSS fuse (protects svhome i5-4300U)
                if self.peer_hop_fuse is not None:
                    fuse_ok, fuse_reason = self.peer_hop_fuse()
                    if not fuse_ok:
                        self._bump(app, peer_fuse_rejects=1)
                        handler.send_response(503, "Peer Fuse Open")
                        handler.send_header("X-Chimera-Peer-Fuse", "OPEN")
                        handler.send_header("X-Chimera-Fuse-Reason", str(fuse_reason)[:80])
                        handler.send_header("Content-Length", "0")
                        handler.end_headers()
                        return
                # 3. Concurrent peer-hop tunnel cap (prevents RSS spikes)
                if not self._peer_hop_sem.acquire(blocking=False):
                    self._bump(app, peer_fuse_rejects=1)
                    handler.send_response(503, "Peer Hop Saturated")
                    handler.send_header("X-Chimera-Peer-Fuse", "SATURATED")
                    handler.send_header("Content-Length", "0")
                    handler.end_headers()
                    return
                peer_slot_acquired = True

            upstream, winner_ip, route_tag, connect_ms, pin_state = self._hedged_connect_ex(
                host,
                port,
                timeout_s=10.0,
                allow_standby=not is_peer_hop,
                allow_peer_failover=not is_peer_hop,
                sticky_key=sticky_key,
                sticky_mode=sticky_mode,
                hemisphere_mode=("failover" if is_peer_hop else hemisphere_mode),
                require_public_ip=(is_peer_hop and not self.allow_private_peer_hop),
            )
            deltas: dict[str, Any] = {}
            if route_tag == "standby":
                deltas["standby_hits"] = 1
            elif route_tag == "hedged":
                deltas["hedged_races"] = 1
                deltas["hedged_rescues"] = 1
                deltas["pop_failovers"] = 1
            elif route_tag == "peer":
                deltas["peer_egress_rescues"] = 1
                deltas["pop_failovers"] = 1
            elif route_tag == "peer-hedge":
                deltas["peer_egress_rescues"] = 1
                deltas["peer_dual_hedges"] = 1
                deltas["pop_failovers"] = 1
            if pin_state == "HIT":
                deltas["sticky_pin_hits"] = 1
            elif pin_state == "SET":
                deltas["sticky_pin_sets"] = 1
            elif pin_state == "FAILOVER":
                deltas["sticky_pin_failovers"] = 1
            if deltas:
                self._bump(app, **deltas)
            self._record_domain_ucb1(host.lower(), 200, connect_ms)
            if self.on_flow is not None:
                try:
                    self.on_flow(
                        "edge",
                        app,
                        host.lower() or "upstream",
                        f"CONNECT_{route_tag.upper()}",
                        wire_bytes=0,
                        elapsed_ms=connect_ms,
                        detail=f"CONNECT {host}:{port} -> {winner_ip} ({connect_ms:.1f}ms)",
                        ok=True,
                    )
                except Exception:
                    pass
            if self.on_activity is not None:
                try:
                    self.on_activity("egress.connect", True, 200)
                except Exception:
                    pass

            handler.send_response(200, "Connection Established")
            handler.send_header("X-Chimera-Membrane", "TUNNEL")
            handler.send_header("X-Chimera-PoP", winner_ip)
            handler.send_header("X-Chimera-Route", route_tag)
            handler.send_header("X-Chimera-PoP-Pin", pin_state)
            handler.send_header("X-Chimera-Connect-Ms", f"{connect_ms:.2f}")
            handler.end_headers()
            client_sock = handler.connection
            _tune_tcp_socket(client_sock)
            _tune_tcp_socket(upstream)
            client_sock.setblocking(False)
            upstream.setblocking(False)
            sockets = [client_sock, upstream]
            total_bytes = 0
            idle_deadline = time.monotonic() + 180.0
            while time.monotonic() < idle_deadline:
                rlist, _, elist = select.select(sockets, [], sockets, 1.0)
                if elist:
                    break
                if not rlist:
                    continue
                idle_deadline = time.monotonic() + 180.0
                for s in rlist:
                    other = upstream if s is client_sock else client_sock
                    try:
                        chunk = s.recv(65536)
                    except BlockingIOError:
                        continue
                    if not chunk:
                        if total_bytes:
                            self._bump(app, bytes_served=total_bytes)
                        return
                    total_bytes += len(chunk)
                    _sendall_nonblocking(other, chunk, timeout_s=15.0)
            if total_bytes:
                self._bump(app, bytes_served=total_bytes)
        except PermissionError as pe:
            self._bump(app, errors=1, peer_fuse_rejects=1)
            try:
                handler.send_response(403, "Peer Hop Target Blocked")
                handler.send_header("X-Chimera-Peer-Fuse", "SSRF_BLOCKED")
                handler.send_header("X-Chimera-Fuse-Reason", str(pe)[:80])
                handler.send_header("Content-Length", "0")
                handler.end_headers()
            except Exception:
                pass
        except Exception:
            ms = (time.perf_counter() - t0) * 1000.0
            self._bump(app, errors=1)
            self._record_domain_ucb1(host.lower(), 502, ms)
            try:
                handler.send_error(502, "CONNECT tunnel failed")
            except Exception:
                pass
        finally:
            if peer_slot_acquired:
                try:
                    self._peer_hop_sem.release()
                except ValueError:
                    pass
            if upstream is not None:
                try:
                    upstream.close()
                except Exception:
                    pass

    def pop_bandit_stats(self) -> list[dict[str, Any]]:
        return self._pop_bandit.snapshot()

    def sticky_pin_stats(self) -> list[dict[str, Any]]:
        return self._pop_bandit.pin_snapshot()

    def stats(self) -> dict[str, Any]:
        with self._stats_lock:
            st = dict(self._stats)
            st["per_app"] = {k: dict(v) for k, v in self._stats["per_app"].items()}
        with self._cache_lock:
            cache_entries = len(self._cache)
            cache_bytes = self._cache_bytes
        with self._standby_lock:
            standby_pool_size = len(self._standby_pool)
        total = max(1, int(st["requests_total"]))
        hits = int(st["cache_hits"]) + int(st["coalesced_hits"]) + int(st["etag_revalidated"])
        st["url"] = self.url
        st["port"] = self.addr[1]
        st["cache_entries"] = cache_entries
        st["cache_bytes"] = cache_bytes
        st["standby_pool_size"] = standby_pool_size
        st["pops_tracked"] = len(self._pop_bandit.snapshot())
        st["active_sticky_pins"] = len(self._pop_bandit.pin_snapshot())
        st["hit_rate_pct"] = round((hits / total) * 100.0, 2) if st["requests_total"] else 0.0
        st["avg_hit_ms"] = round(st["hit_ms_sum"] / max(1, int(st["cache_hits"]) + int(st["coalesced_hits"])), 3)
        st["avg_miss_ms"] = round(st["miss_ms_sum"] / max(1, int(st["miss_count"])), 2)
        return st

    def _record_domain_ucb1(self, domain: str, status: int, ms: float) -> None:
        if not domain:
            return
        with self._stats_lock:
            d = self._domains.setdefault(domain, {"requests": 0, "ok": 0, "errors": 0, "rate_limits": 0, "ms_sum": 0.0})
            d["requests"] += 1
            d["ms_sum"] += ms
            if status == 429:
                d["rate_limits"] += 1
            elif status >= 500 or status == 0:
                d["errors"] += 1
            else:
                d["ok"] += 1

    def domain_bandit_stats(self) -> list[dict[str, Any]]:
        with self._stats_lock:
            total_n = max(1, sum(d["requests"] for d in self._domains.values()))
            out: list[dict[str, Any]] = []
            for dom, d in self._domains.items():
                n = max(1, d["requests"])
                avg_ms = d["ms_sum"] / n
                succ_rate = d["ok"] / n
                # UCB1 health score combining success rate, inverse latency, and exploration term
                ucb1 = succ_rate * (100.0 / (100.0 + avg_ms)) + 0.25 * math.sqrt(math.log(total_n + 1.0) / n)
                circuit = "OPEN" if (n >= 3 and (d["errors"] + d["rate_limits"]) / n >= 0.7) else "CLOSED"
                out.append(
                    {
                        "domain": dom,
                        "requests": d["requests"],
                        "ok": d["ok"],
                        "errors": d["errors"],
                        "rate_limits": d["rate_limits"],
                        "avg_ms": round(avg_ms, 2),
                        "ucb1_score": round(ucb1, 4),
                        "circuit": circuit,
                    }
                )
            return sorted(out, key=lambda x: x["ucb1_score"], reverse=True)
