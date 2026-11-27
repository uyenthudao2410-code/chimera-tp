"""Dynamic Windows network realm discovery and live socket capability probing."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import socket
import struct
import subprocess
import time
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class RealmInfo:
    """Metadata and live probe result for a single CHIMERA-TP network realm."""

    lane_id: str
    adapter_name: str
    address_family: str
    ip: str
    mtu: int
    link_speed: str
    available: bool
    probe_ms: float
    technique: str
    note: str = ""
    if_index: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EnvironmentProfile:
    """Complete probed network topology profile of the current host."""

    hostname: str
    os_info: str
    topology_fingerprint: str
    realms: dict[str, RealmInfo]
    raw_adapters: list[dict[str, Any]] = field(default_factory=list)
    dns_servers: list[str] = field(default_factory=list)
    default_gateway: str = ""

    def active_droplet_lanes(self) -> list[str]:
        """Return all available droplet-capable lanes (excludes bulk jumbo lane)."""
        order = [
            "GHOST_127",
            "LAN_LENGTH",
            "TS_V4_1280",
            "TS_V6_CHORD",
            "HYPERV_MCAST",
            "WSL_PERMUTE",
            "ICMP_REFLECT",
        ]
        return [lid for lid in order if lid in self.realms and self.realms[lid].available]

    def to_dict(self) -> dict[str, Any]:
        return {
            "hostname": self.hostname,
            "os_info": self.os_info,
            "topology_fingerprint": self.topology_fingerprint,
            "default_gateway": self.default_gateway,
            "dns_servers": self.dns_servers,
            "realms": {k: v.to_dict() for k, v in self.realms.items()},
            "raw_adapters": self.raw_adapters,
        }


def _query_windows_network() -> dict[str, Any]:
    """Query adapters, IP interfaces, IP addresses, routes, and DNS in one PowerShell call."""
    ps_script = r"""
$adapters = @(Get-NetAdapter | Select-Object Name, InterfaceDescription, Status, LinkSpeed, MacAddress, InterfaceIndex)
$ipifs = @(Get-NetIPInterface | Select-Object InterfaceAlias, InterfaceIndex, @{N='AddressFamily';E={$_.AddressFamily.ToString()}}, NlMtu, @{N='ConnectionState';E={$_.ConnectionState.ToString()}}, InterfaceMetric)
$ips = @(Get-NetIPAddress | Where-Object { $_.AddressState -eq 'Preferred' } | Select-Object InterfaceAlias, InterfaceIndex, @{N='AddressFamily';E={$_.AddressFamily.ToString()}}, IPAddress, PrefixLength, @{N='PrefixOrigin';E={$_.PrefixOrigin.ToString()}})
$routes = @(Get-NetRoute -DestinationPrefix '0.0.0.0/0','::/0' -ErrorAction SilentlyContinue | Select-Object InterfaceAlias, InterfaceIndex, DestinationPrefix, NextHop, RouteMetric)
$dns = @(Get-DnsClientServerAddress | Where-Object { $_.ServerAddresses.Count -gt 0 } | Select-Object InterfaceAlias, InterfaceIndex, @{N='AddressFamily';E={$_.AddressFamily.ToString()}}, ServerAddresses)
@{
    adapters = $adapters
    ipifs = $ipifs
    ips = $ips
    routes = $routes
    dns = $dns
} | ConvertTo-Json -Depth 5 -Compress
"""
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
        capture_output=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        text=True,
        timeout=15,
        check=False,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        return {"adapters": [], "ipifs": [], "ips": [], "routes": [], "dns": []}
    data = json.loads(proc.stdout)
    for key in ("adapters", "ipifs", "ips", "routes", "dns"):
        val = data.get(key)
        if val is None:
            data[key] = []
        elif isinstance(val, dict):
            data[key] = [val]
    return data


def _disable_udp_connreset(sock: socket.socket) -> None:
    """Disable Windows SIO_UDP_CONNRESET (10054) on UDP sockets."""
    try:
        sock.ioctl(0x9800000C, False)
    except (AttributeError, OSError, ValueError):
        pass


def _icmp_checksum(data: bytes) -> int:
    if len(data) % 2:
        data += b"\x00"
    total = sum(struct.unpack(f"!{len(data) // 2}H", data))
    total = (total >> 16) + (total & 0xFFFF)
    total += total >> 16
    return (~total) & 0xFFFF


def _probe_ghost_127() -> tuple[bool, float, str]:
    t0 = time.perf_counter()
    rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    _disable_udp_connreset(rx)
    try:
        rx.bind(("127.0.0.1", 0))
        dp = rx.getsockname()[1]
        tx.bind(("127.65.66.67", 0))
        tx.sendto(b"", ("127.0.0.1", dp))
        rx.settimeout(0.5)
        data, addr = rx.recvfrom(64)
        ok = len(data) == 0 and addr[0] == "127.65.66.67"
        return ok, (time.perf_counter() - t0) * 1000.0, "0-byte UDP from 127.65.66.67"
    except OSError as exc:
        return False, (time.perf_counter() - t0) * 1000.0, str(exc)
    finally:
        rx.close()
        tx.close()


def _probe_udp_unicast(family: int, ip: str, payload: bytes = b"probe") -> tuple[bool, float, str]:
    t0 = time.perf_counter()
    rx = socket.socket(family, socket.SOCK_DGRAM)
    tx = socket.socket(family, socket.SOCK_DGRAM)
    _disable_udp_connreset(rx)
    try:
        if family == socket.AF_INET6:
            rx.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 2 * 1024 * 1024)
            tx.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 2 * 1024 * 1024)
        rx.bind((ip, 0))
        port = rx.getsockname()[1]
        tx.bind((ip, 0))
        tx.sendto(payload, (ip, port))
        rx.settimeout(0.5)
        data, _ = rx.recvfrom(max(128, len(payload) + 64))
        ok = len(data) == len(payload)
        return ok, (time.perf_counter() - t0) * 1000.0, f"{len(data)}B self-loop OK"
    except OSError as exc:
        return False, (time.perf_counter() - t0) * 1000.0, str(exc)
    finally:
        rx.close()
        tx.close()


def _probe_hyperv_mcast(ip: str) -> tuple[bool, float, str]:
    t0 = time.perf_counter()
    grp = "239.255.13.1"
    rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    _disable_udp_connreset(rx)
    try:
        rx.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        rx.bind((ip, 0))
        port = rx.getsockname()[1]
        mreq = socket.inet_aton(grp) + socket.inet_aton(ip)
        rx.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        tx.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(ip))
        tx.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 0)
        tx.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)
        tx.sendto(b"\x00\x01", (grp, port))
        rx.settimeout(0.5)
        data, _ = rx.recvfrom(64)
        ok = data == b"\x00\x01"
        return ok, (time.perf_counter() - t0) * 1000.0, "239.255.13.1 TTL=0 loop OK"
    except OSError as exc:
        return False, (time.perf_counter() - t0) * 1000.0, str(exc)
    finally:
        rx.close()
        tx.close()


def _probe_icmp_reflect() -> tuple[bool, float, str]:
    t0 = time.perf_counter()
    probe_id = (os.getpid() ^ 0x5A3C) & 0xFFFF
    try:
        rx = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP)
        tx = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP)
    except (PermissionError, OSError) as exc:
        return False, (time.perf_counter() - t0) * 1000.0, f"Unavailable (requires admin): {exc}"

    try:
        rx.bind(("127.0.0.1", 0))
        rx.settimeout(0.35)
        body = b"CHPROBE"
        hdr0 = struct.pack("!BBHHH", 8, 0, 0, probe_id, 1)
        ck = _icmp_checksum(hdr0 + body)
        pkt = struct.pack("!BBHHH", 8, 0, ck, probe_id, 1) + body
        tx.sendto(pkt, ("127.0.0.1", 0))
        deadline = time.perf_counter() + 0.35
        while time.perf_counter() < deadline:
            try:
                raw, _ = rx.recvfrom(1024)
            except socket.timeout:
                break
            if len(raw) < 28:
                continue
            ihl = (raw[0] & 0x0F) * 4
            if len(raw) < ihl + 8:
                continue
            itype, _, _, iid, _ = struct.unpack("!BBHHH", raw[ihl : ihl + 8])
            if itype == 0 and iid == probe_id and raw[ihl + 8 :] == body:
                return True, (time.perf_counter() - t0) * 1000.0, "Kernel Type-0 Echo Reply bounce OK"
        return False, (time.perf_counter() - t0) * 1000.0, "No Type-0 reply received"
    except OSError as exc:
        return False, (time.perf_counter() - t0) * 1000.0, str(exc)
    finally:
        rx.close()
        tx.close()


def _probe_posix_environment() -> EnvironmentProfile:
    """Discover local POSIX/Linux network interfaces cleanly (for dual-host deployment)."""
    realms: dict[str, RealmInfo] = {}
    ok4, ms4, note4 = _probe_udp_unicast(socket.AF_INET, "127.0.0.1", b"LO4")
    realms["LO_V4"] = RealmInfo(
        lane_id="LO_V4",
        adapter_name="lo",
        address_family="IPv4",
        ip="127.0.0.1",
        mtu=65536,
        link_speed="Loopback",
        available=ok4,
        probe_ms=round(ms4, 2),
        technique="POSIX Loopback IPv4",
        note=note4,
        if_index=1,
    )
    ok6, ms6, note6 = _probe_udp_unicast(socket.AF_INET6, "::1", b"J" * 32000)
    realms["LO_V6_JUMBO"] = RealmInfo(
        lane_id="LO_V6_JUMBO",
        adapter_name="lo",
        address_family="IPv6",
        ip="::1",
        mtu=65536,
        link_speed="Loopback IPv6",
        available=ok6,
        probe_ms=round(ms6, 2),
        technique="POSIX IPv6 Loopback Bulk",
        note=note6,
        if_index=1,
    )

    try:
        proc = subprocess.run(
            ["ip", "-j", "addr"], capture_output=True, text=True, timeout=5, check=False
        )
        ifaces = json.loads(proc.stdout) if proc.returncode == 0 and proc.stdout.strip() else []
    except Exception:
        ifaces = []

    raw_adapters: list[dict[str, Any]] = []
    for iface in ifaces:
        ifname = str(iface.get("ifname", ""))
        mtu = int(iface.get("mtu", 1500))
        raw_adapters.append({"Name": ifname, "MTU": mtu, "OperState": iface.get("operstate", "")})
        for addr in iface.get("addr_info", []):
            fam = addr.get("family", "")
            ip = str(addr.get("local", ""))
            if not ip or ip.startswith("127.") or ip == "::1" or ip.startswith("fe80:"):
                continue
            if "tailscale" in ifname.lower() or ip.startswith("100.") or ip.startswith("fd7a:"):
                if fam == "inet" and "TS_V4_1280" not in realms:
                    ok, ms, note = _probe_udp_unicast(socket.AF_INET, ip, b"TSV4")
                    realms["TS_V4_1280"] = RealmInfo(
                        lane_id="TS_V4_1280",
                        adapter_name=ifname,
                        address_family="IPv4",
                        ip=ip,
                        mtu=mtu,
                        link_speed="Tailscale Tunnel",
                        available=ok,
                        probe_ms=round(ms, 2),
                        technique="Cross-Host Tailscale IPv4 <=1280B MTU",
                        note=note,
                        if_index=int(iface.get("ifindex", 0)),
                    )
                elif fam == "inet6" and "TS_V6_CHORD" not in realms:
                    ok, ms, note = _probe_udp_unicast(socket.AF_INET6, ip, b"TSV6")
                    realms["TS_V6_CHORD"] = RealmInfo(
                        lane_id="TS_V6_CHORD",
                        adapter_name=ifname,
                        address_family="IPv6",
                        ip=ip,
                        mtu=mtu,
                        link_speed="Tailscale Tunnel IPv6",
                        available=ok,
                        probe_ms=round(ms, 2),
                        technique="Cross-Host Tailscale IPv6 Path",
                        note=note,
                        if_index=int(iface.get("ifindex", 0)),
                    )
            elif fam == "inet" and "LAN_LENGTH" not in realms:
                ok, ms, note = _probe_udp_unicast(socket.AF_INET, ip, b"LAN4")
                realms["LAN_LENGTH"] = RealmInfo(
                    lane_id="LAN_LENGTH",
                    adapter_name=ifname,
                    address_family="IPv4",
                    ip=ip,
                    mtu=mtu,
                    link_speed="NIC IPv4",
                    available=ok,
                    probe_ms=round(ms, 2),
                    technique="POSIX Physical/Wi-Fi IPv4 Interface",
                    note=note,
                    if_index=int(iface.get("ifindex", 0)),
                )

    fp_items = sorted(f"{r.adapter_name}|{r.address_family}|{r.ip}|{r.mtu}" for r in realms.values())
    fingerprint = hashlib.sha256("\n".join(fp_items).encode("utf-8")).hexdigest()
    return EnvironmentProfile(
        hostname=socket.gethostname(),
        os_info=platform.platform(),
        topology_fingerprint=fingerprint,
        realms=realms,
        raw_adapters=raw_adapters,
    )


def probe_environment() -> EnvironmentProfile:
    """Discover local network interfaces and verify CHIMERA transport realms."""
    if os.name != "nt":
        return _probe_posix_environment()
    net = _query_windows_network()
    adapters = net["adapters"]
    ipifs = net["ipifs"]
    ips = net["ips"]
    routes = net["routes"]
    dns_entries = net["dns"]

    adapter_by_name = {a.get("Name", ""): a for a in adapters}
    mtu_map: dict[tuple[str, str], int] = {}
    for iface in ipifs:
        alias = iface.get("InterfaceAlias", "")
        fam = str(iface.get("AddressFamily", ""))
        mtu_map[(alias, fam)] = int(iface.get("NlMtu", 1500))

    default_gw = ""
    default_if = ""
    best_metric = 10**9
    for r in routes:
        if r.get("DestinationPrefix") == "0.0.0.0/0":
            metric = int(r.get("RouteMetric", 999))
            if metric < best_metric:
                best_metric = metric
                default_gw = str(r.get("NextHop", ""))
                default_if = str(r.get("InterfaceAlias", ""))

    dns_servers: list[str] = []
    for d in dns_entries:
        if str(d.get("AddressFamily")) in ("IPv4", "2"):
            for s in d.get("ServerAddresses", []):
                if s not in dns_servers:
                    dns_servers.append(str(s))

    def _find_ip(predicate: Any) -> dict[str, Any] | None:
        for entry in ips:
            if predicate(entry):
                return entry
        return None

    lan_entry = _find_ip(
        lambda e: e.get("AddressFamily") == "IPv4"
        and e.get("InterfaceAlias") == default_if
        and not str(e.get("IPAddress", "")).startswith("127.")
    )
    if lan_entry is None:
        lan_entry = _find_ip(
            lambda e: e.get("AddressFamily") == "IPv4"
            and "Ethernet" in str(e.get("InterfaceAlias", ""))
            and not str(e.get("IPAddress", "")).startswith("127.")
        )

    ts_v4 = _find_ip(
        lambda e: e.get("AddressFamily") == "IPv4" and "Tailscale" in str(e.get("InterfaceAlias", ""))
    )
    ts_v6 = _find_ip(
        lambda e: e.get("AddressFamily") == "IPv6"
        and "Tailscale" in str(e.get("InterfaceAlias", ""))
        and not str(e.get("IPAddress", "")).startswith("fe80:")
    )
    hv_v4 = _find_ip(
        lambda e: e.get("AddressFamily") == "IPv4" and "Default Switch" in str(e.get("InterfaceAlias", ""))
    )
    wsl_v4 = _find_ip(
        lambda e: e.get("AddressFamily") == "IPv4" and "WSL" in str(e.get("InterfaceAlias", ""))
    )
    lo_v4 = _find_ip(
        lambda e: e.get("AddressFamily") == "IPv4" and str(e.get("IPAddress", "")) == "127.0.0.1"
    )
    lo_v6 = _find_ip(
        lambda e: e.get("AddressFamily") == "IPv6" and str(e.get("IPAddress", "")) == "::1"
    )

    realms: dict[str, RealmInfo] = {}

    # 1. GHOST_127
    ok, ms, note = _probe_ghost_127()
    lo_alias = lo_v4.get("InterfaceAlias", "Loopback Pseudo-Interface 1") if lo_v4 else "Loopback Pseudo-Interface 1"
    realms["GHOST_127"] = RealmInfo(
        lane_id="GHOST_127",
        adapter_name=lo_alias,
        address_family="IPv4",
        ip="127.0.0.1",
        mtu=mtu_map.get((lo_alias, "IPv4"), 4294967295),
        link_speed="Kernel Loopback",
        available=ok,
        probe_ms=round(ms, 2),
        technique="0-Byte UDP Source-IP Ghost Smuggling (127.A.B.C)",
        note=note,
        if_index=int(lo_v4.get("InterfaceIndex", 1)) if lo_v4 else 1,
    )

    # 2. LAN_LENGTH
    if lan_entry:
        alias = str(lan_entry["InterfaceAlias"])
        ip = str(lan_entry["IPAddress"])
        ok, ms, note = _probe_udp_unicast(socket.AF_INET, ip, os.urandom(128))
        spd = str(adapter_by_name.get(alias, {}).get("LinkSpeed", "1 Gbps"))
        realms["LAN_LENGTH"] = RealmInfo(
            lane_id="LAN_LENGTH",
            adapter_name=alias,
            address_family="IPv4",
            ip=ip,
            mtu=mtu_map.get((alias, "IPv4"), 1500),
            link_speed=spd,
            available=ok,
            probe_ms=round(ms, 2),
            technique="Packet-Length Modulated Random-Noise UDP (payload ignored)",
            note=note,
            if_index=int(lan_entry.get("InterfaceIndex", 0)),
        )

    # 3. TS_V4_1280
    if ts_v4:
        alias = str(ts_v4["InterfaceAlias"])
        ip = str(ts_v4["IPAddress"])
        ok, ms, note = _probe_udp_unicast(socket.AF_INET, ip, b"TSV4")
        spd = str(adapter_by_name.get(alias, {}).get("LinkSpeed", "100 Gbps"))
        realms["TS_V4_1280"] = RealmInfo(
            lane_id="TS_V4_1280",
            adapter_name=alias,
            address_family="IPv4",
            ip=ip,
            mtu=mtu_map.get((alias, "IPv4"), 1280),
            link_speed=spd,
            available=ok,
            probe_ms=round(ms, 2),
            technique="Strict <=1200B MTU-Clamped Whitened Fountain",
            note=note,
            if_index=int(ts_v4.get("InterfaceIndex", 0)),
        )

    # 4. TS_V6_CHORD
    if ts_v6:
        alias = str(ts_v6["InterfaceAlias"])
        ip = str(ts_v6["IPAddress"])
        ok, ms, note = _probe_udp_unicast(socket.AF_INET6, ip, b"TSV6")
        spd = str(adapter_by_name.get(alias, {}).get("LinkSpeed", "100 Gbps"))
        realms["TS_V6_CHORD"] = RealmInfo(
            lane_id="TS_V6_CHORD",
            adapter_name=alias,
            address_family="IPv6",
            ip=ip,
            mtu=mtu_map.get((alias, "IPv6"), 1280),
            link_speed=spd,
            available=ok,
            probe_ms=round(ms, 2),
            technique="16-Port IPv6 Bitmask Chord + Barline Synchronization",
            note=note,
            if_index=int(ts_v6.get("InterfaceIndex", 0)),
        )

    # 5. HYPERV_MCAST
    if hv_v4:
        alias = str(hv_v4["InterfaceAlias"])
        ip = str(hv_v4["IPAddress"])
        ok, ms, note = _probe_hyperv_mcast(ip)
        spd = str(adapter_by_name.get(alias, {}).get("LinkSpeed", "10 Gbps"))
        realms["HYPERV_MCAST"] = RealmInfo(
            lane_id="HYPERV_MCAST",
            adapter_name=alias,
            address_family="IPv4",
            ip=ip,
            mtu=mtu_map.get((alias, "IPv4"), 1500),
            link_speed=spd,
            available=ok,
            probe_ms=round(ms, 2),
            technique="16-Group Multicast Nibble Constellation (239.255.13.1..16, TTL=0)",
            note=note,
            if_index=int(hv_v4.get("InterfaceIndex", 0)),
        )

    # 6. WSL_PERMUTE
    if wsl_v4:
        alias = str(wsl_v4["InterfaceAlias"])
        ip = str(wsl_v4["IPAddress"])
        ok, ms, note = _probe_udp_unicast(socket.AF_INET, ip, b"WSL")
        spd = str(adapter_by_name.get(alias, {}).get("LinkSpeed", "10 Gbps"))
        realms["WSL_PERMUTE"] = RealmInfo(
            lane_id="WSL_PERMUTE",
            adapter_name=alias,
            address_family="IPv4",
            ip=ip,
            mtu=mtu_map.get((alias, "IPv4"), 1500),
            link_speed=spd,
            available=ok,
            probe_ms=round(ms, 2),
            technique="S_6 Lehmer-Permutation Ordering Transposition",
            note=note,
            if_index=int(wsl_v4.get("InterfaceIndex", 0)),
        )

    # 7. ICMP_REFLECT
    ok, ms, note = _probe_icmp_reflect()
    realms["ICMP_REFLECT"] = RealmInfo(
        lane_id="ICMP_REFLECT",
        adapter_name=lo_alias,
        address_family="IPv4-RAW-ICMP",
        ip="127.0.0.1",
        mtu=mtu_map.get((lo_alias, "IPv4"), 4294967295),
        link_speed="Kernel ICMP",
        available=ok,
        probe_ms=round(ms, 2),
        technique="Raw ICMP Type-8 -> Kernel Echo-Reply Type-0 Reflector",
        note=note,
        if_index=int(lo_v4.get("InterfaceIndex", 1)) if lo_v4 else 1,
    )

    # 8. LO_V6_JUMBO
    lo6_alias = lo_v6.get("InterfaceAlias", lo_alias) if lo_v6 else lo_alias
    ok, ms, note = _probe_udp_unicast(socket.AF_INET6, "::1", b"J" * 60000)
    realms["LO_V6_JUMBO"] = RealmInfo(
        lane_id="LO_V6_JUMBO",
        adapter_name=lo6_alias,
        address_family="IPv6",
        ip="::1",
        mtu=mtu_map.get((lo6_alias, "IPv6"), 4294967295),
        link_speed="4 GiB Virtual Loopback",
        available=ok,
        probe_ms=round(ms, 2),
        technique="58 KiB Chaotic-OTP Jumbo Superframes (Holographic Bulk)",
        note=note,
        if_index=int(lo_v6.get("InterfaceIndex", 1)) if lo_v6 else 1,
    )

    fp_items = sorted(
        f"{r.adapter_name}|{r.address_family}|{r.ip}|{r.mtu}" for r in realms.values()
    )
    fingerprint = hashlib.sha256("\n".join(fp_items).encode("utf-8")).hexdigest()

    return EnvironmentProfile(
        hostname=socket.gethostname(),
        os_info=platform.platform(),
        topology_fingerprint=fingerprint,
        realms=realms,
        raw_adapters=adapters,
        dns_servers=dns_servers,
        default_gateway=default_gw,
    )
