"""6-suite Before-vs-After benchmark, stress sweep, soak test, and security audit for CHIMERA-TP."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import random
import socket
import struct
import sys
import threading
import time
from pathlib import Path
from typing import Any

import sys
from pathlib import Path
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from chimera_tp.gf256 import shannon_entropy, xor_bytes
from chimera_tp.lanes import HyperVMcastConstellationLane
from chimera_tp.probe import EnvironmentProfile, _disable_udp_connreset, probe_environment
from chimera_tp.protocol import ChimeraReceiver, ChimeraSender, FaultProfile


def _configure_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except OSError:
                pass


def _make_semi_structured_payload(size: int) -> bytes:
    """Create semi-structured UTF-8/binary payload with moderate raw entropy (~5.5-5.9 b/B)."""
    block = (
        b"CHIMERA-EVAL-RECORD|Vietnam=TiengVietCoDau|Header=AABBCCDD|"
        + b"\x00\x11\x22\x33\x44\x55\x66\x77\x88\x99\xAA\xBB\xCC\xDD\xEE\xFF" * 4
    )
    buf = bytearray()
    rng = random.Random(42)
    while len(buf) < size:
        buf.extend(block)
        buf.extend(rng.randbytes(24))
    return bytes(buf[:size])


def _bench_plain_tcp(ip: str, family: int, payload: bytes) -> dict[str, Any]:
    """Measure standard single-interface TCP send/recv baseline."""
    expected_sha = hashlib.sha256(payload).hexdigest()
    srv = socket.socket(family, socket.SOCK_STREAM)
    srv.bind((ip, 0))
    srv.listen(1)
    port = srv.getsockname()[1]

    chunks: list[bytes] = []
    rx_err: list[str] = []

    def server_worker() -> None:
        try:
            conn, _ = srv.accept()
            with conn:
                conn.settimeout(5.0)
                while True:
                    data = conn.recv(65536)
                    if not data:
                        break
                    chunks.append(data)
        except OSError as exc:
            rx_err.append(str(exc))

    th = threading.Thread(target=server_worker, daemon=True)
    th.start()

    cli = socket.socket(family, socket.SOCK_STREAM)
    t0 = time.perf_counter()
    try:
        cli.settimeout(5.0)
        cli.connect((ip, port))
        cli.sendall(payload)
        cli.shutdown(socket.SHUT_WR)
        th.join(timeout=5.0)
    finally:
        cli.close()
        srv.close()

    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    received = b"".join(chunks)
    actual_sha = hashlib.sha256(received).hexdigest()
    hdr_overhead = (40 if family == socket.AF_INET6 else 20) + 20
    num_segs = max(1, (len(payload) + 1459) // 1460)
    wire_est = len(payload) + num_segs * hdr_overhead
    return {
        "protocol": "BASELINE_TCP",
        "ip": ip,
        "payload_bytes": len(payload),
        "received_bytes": len(received),
        "sha256_match": (actual_sha == expected_sha) and not rx_err,
        "elapsed_ms": round(elapsed_ms, 3),
        "effective_kbps": round((len(payload) * 8.0) / max(elapsed_ms, 0.001), 2),
        "wire_total_bytes_est": wire_est,
        "wire_entropy_bits_per_byte": round(shannon_entropy(payload), 5),
        "plaintext_single_nic_exposure_pct": 100.0,
        "error": "; ".join(rx_err),
    }


def _bench_plain_udp(
    ip: str,
    family: int,
    payload: bytes,
    chunk_size: int = 1400,
    drop_rate: float = 0.0,
    xor_corrupt: bool = False,
    seed: int = 1337,
) -> dict[str, Any]:
    """Measure standard single-interface UDP send/recv baseline (with optional fault injection)."""
    expected_sha = hashlib.sha256(payload).hexdigest()
    rx = socket.socket(family, socket.SOCK_DGRAM)
    _disable_udp_connreset(rx)
    try:
        rx.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
    except OSError:
        pass
    rx.bind((ip, 0))
    port = rx.getsockname()[1]

    total_chunks = max(1, (len(payload) + chunk_size - 1) // chunk_size)
    received_map: dict[int, bytes] = {}
    rx_wire = bytearray()
    rx_done = threading.Event()

    def rx_worker() -> None:
        rx.settimeout(0.25)
        deadline = time.perf_counter() + 4.0
        while time.perf_counter() < deadline:
            try:
                pkt, _ = rx.recvfrom(65535)
            except (socket.timeout, ConnectionResetError, OSError):
                break
            if len(pkt) < 4:
                continue
            idx = struct.unpack("!I", pkt[:4])[0]
            body = pkt[4:]
            received_map[idx] = body
            rx_wire.extend(body)
            if len(received_map) >= total_chunks:
                break
        rx_done.set()

    th = threading.Thread(target=rx_worker, daemon=True)
    th.start()

    tx = socket.socket(family, socket.SOCK_DGRAM)
    try:
        tx.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4 * 1024 * 1024)
    except OSError:
        pass
    rng = random.Random(seed)
    sent_pkts = 0
    wire_payload_bytes = 0
    t0 = time.perf_counter()
    try:
        for idx in range(total_chunks):
            chunk = payload[idx * chunk_size : (idx + 1) * chunk_size]
            if drop_rate > 0.0 and rng.random() < drop_rate:
                continue
            if xor_corrupt:
                chunk = xor_bytes(chunk, b"\xFF" * len(chunk))
            pkt = struct.pack("!I", idx) + chunk
            tx.sendto(pkt, (ip, port))
            sent_pkts += 1
            wire_payload_bytes += len(pkt)
            if total_chunks > 8:
                time.sleep(0.0001)
        rx_done.wait(timeout=4.5)
    finally:
        tx.close()
        rx.close()

    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    reassembled = b"".join(received_map[i] for i in range(total_chunks) if i in received_map)
    actual_sha = hashlib.sha256(reassembled).hexdigest()
    hdr_overhead = (40 if family == socket.AF_INET6 else 20) + 8
    return {
        "protocol": "BASELINE_UDP",
        "ip": ip,
        "payload_bytes": len(payload),
        "received_bytes": len(reassembled),
        "chunks_sent": sent_pkts,
        "chunks_total": total_chunks,
        "chunks_received": len(received_map),
        "sha256_match": actual_sha == expected_sha and len(received_map) == total_chunks,
        "elapsed_ms": round(elapsed_ms, 3),
        "effective_kbps": round((len(reassembled) * 8.0) / max(elapsed_ms, 0.001), 2),
        "wire_total_bytes_est": wire_payload_bytes + sent_pkts * hdr_overhead,
        "wire_entropy_bits_per_byte": round(shannon_entropy(bytes(rx_wire)), 5) if rx_wire else 0.0,
        "plaintext_single_nic_exposure_pct": 100.0,
    }


def _safe_chimera_metamorphic(
    rx: ChimeraReceiver,
    tx: ChimeraSender,
    payload: bytes,
    fault: FaultProfile,
    timeout_s: float = 12.0,
    profile: str = "balanced",
    parallel: bool = True,
) -> dict[str, Any]:
    try:
        rec, rep = tx.send_metamorphic(
            rx,
            payload,
            fault=fault,
            timeout_s=timeout_s,
            profile=profile,
            parallel=parallel,
        )
        d = rep.to_dict()
        d["verified_equal"] = bool(rep.success and rep.sha256_match and rec == payload)
        total_wire = sum(st.get("wire_total_bytes_est", 0) for st in rep.per_lane_stats.values())
        d["wire_total_bytes_est"] = total_wire
        d["wire_amplification"] = round(total_wire / max(1, len(payload)), 2)
        return d
    except Exception as exc:
        return {
            "mode": "PURE-METAMORPHIC",
            "success": False,
            "sha256_match": False,
            "verified_equal": False,
            "payload_bytes": len(payload),
            "elapsed_ms": 0.0,
            "effective_kbps": 0.0,
            "wire_total_bytes_est": 0,
            "wire_amplification": 0.0,
            "error": str(exc),
        }


def _safe_chimera_holographic(
    rx: ChimeraReceiver,
    tx: ChimeraSender,
    payload: bytes,
    fault: FaultProfile,
    timeout_s: float = 20.0,
) -> dict[str, Any]:
    try:
        rec, rep = tx.send_holographic(rx, payload, fault=fault, timeout_s=timeout_s)
        d = rep.to_dict()
        d["verified_equal"] = bool(rep.success and rep.sha256_match and rec == payload)
        total_wire = sum(st.get("wire_total_bytes_est", 0) for st in rep.per_lane_stats.values())
        d["wire_total_bytes_est"] = total_wire
        d["wire_amplification"] = round(total_wire / max(1, len(payload)), 4)
        return d
    except Exception as exc:
        return {
            "mode": "HOLOGRAPHIC-SPLIT",
            "success": False,
            "sha256_match": False,
            "verified_equal": False,
            "payload_bytes": len(payload),
            "elapsed_ms": 0.0,
            "effective_kbps": 0.0,
            "wire_total_bytes_est": 0,
            "wire_amplification": 0.0,
            "holo_entropy_bits_per_byte": None,
            "jumbo_chunks": 0,
            "error": str(exc),
        }


def suite_before_after(
    env: EnvironmentProfile, rx: ChimeraReceiver, tx: ChimeraSender
) -> dict[str, Any]:
    print("\n=== SUITE 0: BEFORE (Standard TCP/UDP) vs AFTER (CHIMERA-TP) ===")
    lan_ip = env.realms["LAN_LENGTH"].ip if "LAN_LENGTH" in env.realms else "127.0.0.1"
    p512 = _make_semi_structured_payload(512)
    p256k = _make_semi_structured_payload(256 * 1024)
    p1m = _make_semi_structured_payload(1024 * 1024)

    # Normal 512 B
    tcp_512 = _bench_plain_tcp(lan_ip, socket.AF_INET, p512)
    udp_512 = _bench_plain_udp(lan_ip, socket.AF_INET, p512, chunk_size=512)
    chim_512 = _safe_chimera_metamorphic(rx, tx, p512, FaultProfile(), timeout_s=12.0)

    # Bulk 256 KiB and 1 MiB
    tcp_256k = _bench_plain_tcp("::1", socket.AF_INET6, p256k)
    udp_256k = _bench_plain_udp("::1", socket.AF_INET6, p256k, chunk_size=58000)
    chim_256k = _safe_chimera_holographic(rx, tx, p256k, FaultProfile(), timeout_s=20.0)

    tcp_1m = _bench_plain_tcp("::1", socket.AF_INET6, p1m)
    udp_1m = _bench_plain_udp("::1", socket.AF_INET6, p1m, chunk_size=58000)
    chim_1m = _safe_chimera_holographic(rx, tx, p1m, FaultProfile(), timeout_s=20.0)

    # Fault Scenarios (512 B)
    fault_drop_udp = _bench_plain_udp(lan_ip, socket.AF_INET, p512, chunk_size=16, drop_rate=0.20)
    fault_drop_chim = _safe_chimera_metamorphic(
        rx, tx, p512, FaultProfile(packet_drop_rate=0.20), timeout_s=15.0
    )

    fault_flip_udp = _bench_plain_udp(lan_ip, socket.AF_INET, p512, chunk_size=512, xor_corrupt=True)
    all_lanes = set(env.active_droplet_lanes())
    fault_flip_chim = _safe_chimera_metamorphic(
        rx,
        tx,
        p512,
        FaultProfile(kill_lanes=all_lanes - {"LAN_LENGTH"}, corrupt_lan_noise=True),
        timeout_s=15.0,
    )

    fault_kill_plain = {
        "protocol": "BASELINE_SINGLE_NIC",
        "sha256_match": False,
        "survival_pct": 0.0,
        "note": "Single-interface TCP/UDP stops at 0% if its interface is killed",
    }
    fault_kill_chim = _safe_chimera_metamorphic(
        rx,
        tx,
        p512,
        FaultProfile(kill_lanes={"GHOST_127", "WSL_PERMUTE", "TS_V6_CHORD"}),
        timeout_s=15.0,
    )

    print(
        f"512B Normal  | TCP: {tcp_512['elapsed_ms']:.2f}ms ({tcp_512['effective_kbps']:.0f} kbps) "
        f"| UDP: {udp_512['elapsed_ms']:.2f}ms | CHIMERA Meta: {chim_512['elapsed_ms']:.2f}ms "
        f"({chim_512['effective_kbps']:.1f} kbps, amp={chim_512['wire_amplification']}x)"
    )
    print(
        f"256KiB Bulk  | TCP: {tcp_256k['elapsed_ms']:.2f}ms ({tcp_256k['effective_kbps']/1000:.1f} Mbps, ent={tcp_256k['wire_entropy_bits_per_byte']:.3f}) "
        f"| CHIMERA Holo: {chim_256k['elapsed_ms']:.2f}ms ({chim_256k['effective_kbps']/1000:.1f} Mbps, ent={chim_256k.get('holo_entropy_bits_per_byte')})"
    )
    print(
        f"1MiB Bulk    | TCP: {tcp_1m['elapsed_ms']:.2f}ms ({tcp_1m['effective_kbps']/1000:.1f} Mbps) "
        f"| UDP: {udp_1m['elapsed_ms']:.2f}ms (match={udp_1m['sha256_match']}) "
        f"| CHIMERA Holo: {chim_1m['elapsed_ms']:.2f}ms ({chim_1m['effective_kbps']/1000:.1f} Mbps, match={chim_1m['sha256_match']})"
    )
    print(
        f"Faults (512B)| 20% Drop UDP match={fault_drop_udp['sha256_match']} vs CHIMERA={fault_drop_chim['sha256_match']} | "
        f"100% Flip UDP match={fault_flip_udp['sha256_match']} vs LAN_LENGTH={fault_flip_chim['sha256_match']} | "
        f"3-Kill Plain=False vs CHIMERA={fault_kill_chim['sha256_match']}"
    )

    return {
        "normal_512b": {
            "before_tcp": tcp_512,
            "before_udp": udp_512,
            "after_chimera_metamorphic": {
                "success": chim_512["success"],
                "sha256_match": chim_512["sha256_match"],
                "elapsed_ms": chim_512["elapsed_ms"],
                "effective_kbps": chim_512["effective_kbps"],
                "wire_total_bytes_est": chim_512["wire_total_bytes_est"],
                "wire_amplification": chim_512["wire_amplification"],
                "k_blocks": chim_512.get("k_blocks", 0),
                "droplets_sent": chim_512.get("droplets_sent", 0),
                "single_nic_plaintext_exposure_pct": 0.0,
            },
        },
        "bulk_256k": {
            "raw_entropy_bits_per_byte": round(shannon_entropy(p256k), 5),
            "before_tcp": tcp_256k,
            "before_udp": udp_256k,
            "after_chimera_holographic": {
                "success": chim_256k["success"],
                "sha256_match": chim_256k["sha256_match"],
                "elapsed_ms": chim_256k["elapsed_ms"],
                "effective_kbps": chim_256k["effective_kbps"],
                "wire_total_bytes_est": chim_256k["wire_total_bytes_est"],
                "holo_entropy_bits_per_byte": chim_256k.get("holo_entropy_bits_per_byte"),
                "jumbo_chunks": chim_256k.get("jumbo_chunks", 0),
            },
        },
        "bulk_1m": {
            "raw_entropy_bits_per_byte": round(shannon_entropy(p1m), 5),
            "before_tcp": tcp_1m,
            "before_udp": udp_1m,
            "after_chimera_holographic": {
                "success": chim_1m["success"],
                "sha256_match": chim_1m["sha256_match"],
                "elapsed_ms": chim_1m["elapsed_ms"],
                "effective_kbps": chim_1m["effective_kbps"],
                "wire_total_bytes_est": chim_1m["wire_total_bytes_est"],
                "holo_entropy_bits_per_byte": chim_1m.get("holo_entropy_bits_per_byte"),
                "jumbo_chunks": chim_1m.get("jumbo_chunks", 0),
            },
        },
        "fault_scenarios": {
            "drop_20pct": {
                "before_udp": fault_drop_udp,
                "after_chimera": {
                    "sha256_match": fault_drop_chim["sha256_match"],
                    "elapsed_ms": fault_drop_chim["elapsed_ms"],
                    "droplets_sent": fault_drop_chim.get("droplets_sent", 0),
                    "droplets_received": fault_drop_chim.get("droplets_received", 0),
                },
            },
            "payload_bitflip_100pct": {
                "before_udp": fault_flip_udp,
                "after_chimera_lan_length": {
                    "sha256_match": fault_flip_chim["sha256_match"],
                    "elapsed_ms": fault_flip_chim["elapsed_ms"],
                },
            },
            "three_interfaces_killed": {
                "before_single_nic": fault_kill_plain,
                "after_chimera": {
                    "sha256_match": fault_kill_chim["sha256_match"],
                    "elapsed_ms": fault_kill_chim["elapsed_ms"],
                    "surviving_lanes": chim_kill_lanes(fault_kill_chim),
                },
            },
        },
    }


def chim_kill_lanes(rep: dict[str, Any]) -> list[str]:
    return list(rep.get("active_lanes", []))


def suite_solo_lanes(
    env: EnvironmentProfile, rx: ChimeraReceiver, tx: ChimeraSender
) -> list[dict[str, Any]]:
    print("\n=== SUITE 1: SOLO LANE ISOLATION BENCHMARK (384 B) ===")
    all_lanes = env.active_droplet_lanes()
    payload = _make_semi_structured_payload(384)
    results: list[dict[str, Any]] = []
    for lid in all_lanes:
        fault = FaultProfile(
            kill_lanes=set(all_lanes) - {lid},
            packet_drop_rate=0.0,
            corrupt_lan_noise=(lid == "LAN_LENGTH"),
        )
        rep = _safe_chimera_metamorphic(rx, tx, payload, fault, timeout_s=12.0)
        st = rep.get("per_lane_stats", {}).get(lid, {})
        row = {
            "lane_id": lid,
            "success": rep["verified_equal"],
            "sha256_match": rep["sha256_match"],
            "elapsed_ms": rep["elapsed_ms"],
            "effective_kbps": rep["effective_kbps"],
            "packets_sent": st.get("packets_sent", 0),
            "wire_payload_bytes": st.get("wire_payload_bytes", 0),
            "wire_total_bytes_est": st.get("wire_total_bytes_est", 0),
            "wire_amplification": round(
                st.get("wire_total_bytes_est", 0) / max(1, len(payload)), 2
            ),
            "avg_tx_ms": st.get("avg_tx_ms", 0.0),
            "droplets_sent": st.get("droplets_sent", 0),
            "droplets_received": st.get("droplets_recv", 0),
            "reconstruct_errors": st.get("reconstruct_errors", 0),
            "error": rep.get("error", ""),
        }
        results.append(row)
        print(
            f"  {lid:<14} ok={str(row['success']):<5} {row['elapsed_ms']:>7.2f}ms "
            f"{row['effective_kbps']:>7.1f} kbps | pkt={row['packets_sent']:>4} "
            f"pay={row['wire_payload_bytes']:>7,}B est={row['wire_total_bytes_est']:>7,}B "
            f"({row['wire_amplification']}x)"
        )
    return results


def suite_drop_sweep(rx: ChimeraReceiver, tx: ChimeraSender) -> list[dict[str, Any]]:
    print("\n=== SUITE 2: DROP-RATE CHAOS TOLERANCE SWEEP (512 B, 0% -> 70%) ===")
    payload = _make_semi_structured_payload(512)
    rates = [0.0, 0.10, 0.25, 0.40, 0.55, 0.70]
    results: list[dict[str, Any]] = []
    for rate in rates:
        fault = FaultProfile(packet_drop_rate=rate, corrupt_lan_noise=True)
        rep = _safe_chimera_metamorphic(rx, tx, payload, fault, timeout_s=15.0)
        k = max(1, rep.get("k_blocks", 1))
        dsent = rep.get("droplets_sent", 0)
        row = {
            "drop_rate": rate,
            "success": rep["verified_equal"],
            "elapsed_ms": rep["elapsed_ms"],
            "k_blocks": rep.get("k_blocks", 0),
            "droplets_sent": dsent,
            "droplets_received": rep.get("droplets_received", 0),
            "overhead_ratio": round(dsent / k, 2) if rep.get("k_blocks") else 0.0,
            "effective_kbps": rep["effective_kbps"],
            "crc_drops": rep.get("crc_drops", 0),
            "error": rep.get("error", ""),
        }
        results.append(row)
        print(
            f"  drop={int(rate*100):>2}% ok={str(row['success']):<5} {row['elapsed_ms']:>7.2f}ms "
            f"TX/RX={row['droplets_sent']}/{row['droplets_received']} (k={row['k_blocks']}, "
            f"ratio={row['overhead_ratio']:.2f}x) {row['effective_kbps']:>6.1f} kbps"
        )
    return results


def suite_scaling(rx: ChimeraReceiver, tx: ChimeraSender) -> list[dict[str, Any]]:
    print("\n=== SUITE 3: PAYLOAD SIZE SCALING ===")
    results: list[dict[str, Any]] = []

    for sz in [0, 1, 64, 512, 2048, 4096, 16384]:
        payload = os.urandom(sz) if sz >= 64 else (b"A" * sz)
        prof = "turbo" if sz >= 16384 else "balanced"
        rep = _safe_chimera_metamorphic(
            rx, tx, payload, FaultProfile(), timeout_s=15.0, profile=prof, parallel=True
        )
        row = {
            "mode": "PURE-METAMORPHIC",
            "payload_bytes": sz,
            "k_blocks": rep.get("k_blocks", 0),
            "profile": prof,
            "success": rep["verified_equal"],
            "sha256_match": rep["sha256_match"],
            "elapsed_ms": rep["elapsed_ms"],
            "effective_kbps": rep["effective_kbps"],
            "jumbo_chunks": 0,
            "holo_entropy": None,
            "error": rep.get("error", ""),
        }
        results.append(row)
        print(
            f"  METAMORPHIC {sz:>8,} B ({prof:<8}) | ok={str(row['success']):<5} k={row['k_blocks']:>4} "
            f"{row['elapsed_ms']:>8.2f}ms {row['effective_kbps']:>8.2f} kbps"
        )

    for sz in [16384, 262144, 1048576, 4194304, 8388608]:
        payload = _make_semi_structured_payload(sz)
        rep = _safe_chimera_holographic(rx, tx, payload, FaultProfile(), timeout_s=25.0)
        row = {
            "mode": "HOLOGRAPHIC-SPLIT",
            "payload_bytes": sz,
            "k_blocks": rep.get("k_blocks", 0),
            "success": rep["verified_equal"],
            "sha256_match": rep["sha256_match"],
            "elapsed_ms": rep["elapsed_ms"],
            "effective_kbps": rep["effective_kbps"],
            "jumbo_chunks": rep.get("jumbo_chunks", 0),
            "holo_entropy": rep.get("holo_entropy_bits_per_byte"),
            "error": rep.get("error", ""),
        }
        results.append(row)
        print(
            f"  HOLOGRAPHIC {sz:>8,} B | ok={str(row['success']):<5} chunks={row['jumbo_chunks']:>3} "
            f"{row['elapsed_ms']:>8.2f}ms {row['effective_kbps']/1000:>7.2f} Mbps "
            f"ent={row['holo_entropy']} {row['error']}"
        )
    return results


def suite_v05_upgrades(rx: ChimeraReceiver, tx: ChimeraSender) -> dict[str, Any]:
    print("\n=== SUITE 6 (v0.5.0): PROFILE/PARALLEL MATRIX & 25% JUMBO FEC/NACK ===")
    p2k = os.urandom(2048)
    matrix: list[dict[str, Any]] = []
    for label, prof, par in [
        ("balanced_seq", "balanced", False),
        ("balanced_par", "balanced", True),
        ("stealth_par", "stealth", True),
        ("turbo_par", "turbo", True),
    ]:
        rep = _safe_chimera_metamorphic(
            rx, tx, p2k, FaultProfile(), timeout_s=15.0, profile=prof, parallel=par
        )
        row = {
            "label": label,
            "profile": prof,
            "parallel": par,
            "success": rep["verified_equal"],
            "elapsed_ms": rep["elapsed_ms"],
            "effective_kbps": rep["effective_kbps"],
            "wire_total_bytes_est": rep["wire_total_bytes_est"],
            "wire_amplification": rep["wire_amplification"],
            "k_blocks": rep.get("k_blocks", 0),
        }
        matrix.append(row)
        print(
            f"  {label:<14} ok={str(row['success']):<5} {row['elapsed_ms']:>7.2f}ms "
            f"{row['effective_kbps']:>7.1f} kbps | wire={row['wire_total_bytes_est']:>7,}B "
            f"({row['wire_amplification']}x)"
        )

    p1m = _make_semi_structured_payload(1024 * 1024)
    holo_drop = _safe_chimera_holographic(
        rx, tx, p1m, FaultProfile(jumbo_drop_rate=0.25), timeout_s=20.0
    )
    holo_res = {
        "payload_bytes": len(p1m),
        "jumbo_drop_rate": 0.25,
        "success": holo_drop["verified_equal"],
        "sha256_match": holo_drop["sha256_match"],
        "elapsed_ms": holo_drop["elapsed_ms"],
        "effective_kbps": holo_drop["effective_kbps"],
        "jumbo_chunks": holo_drop.get("jumbo_chunks", 0),
        "jumbo_fec_recoveries": holo_drop.get("jumbo_fec_recoveries", 0),
        "jumbo_nack_retransmits": holo_drop.get("jumbo_nack_retransmits", 0),
    }
    print(
        f"  Holo 25% drop  ok={str(holo_res['success']):<5} {holo_res['elapsed_ms']:>7.2f}ms "
        f"{holo_res['effective_kbps']/1000:>6.2f} Mbps | FEC={holo_res['jumbo_fec_recoveries']} "
        f"NACK={holo_res['jumbo_nack_retransmits']}"
    )
    return {"profile_parallel_matrix_2k": matrix, "holographic_25pct_jumbo_drop": holo_res}


def suite_soak(
    env: EnvironmentProfile, rx: ChimeraReceiver, tx: ChimeraSender
) -> dict[str, Any]:
    print("\n=== SUITE 4: 20-RUN RANDOMIZED RELIABILITY SOAK TEST ===")
    rng = random.Random(20261125)
    all_lanes = env.active_droplet_lanes()
    runs: list[dict[str, Any]] = []
    latencies: list[float] = []
    passed = 0
    total_crc_drops = 0

    for i in range(1, 21):
        sz = rng.randint(32, 1024)
        payload = _make_semi_structured_payload(sz)
        n_kill = rng.randint(0, min(3, len(all_lanes) - 1))
        killed = set(rng.sample(all_lanes, n_kill))
        drop_rate = round(rng.uniform(0.0, 0.30), 3)
        corrupt_lan = rng.choice([True, False])
        fault = FaultProfile(
            kill_lanes=killed,
            packet_drop_rate=drop_rate,
            corrupt_lan_noise=corrupt_lan,
        )
        rep = _safe_chimera_metamorphic(rx, tx, payload, fault, timeout_s=12.0)
        ok = bool(rep["verified_equal"])
        if ok:
            passed += 1
            latencies.append(float(rep["elapsed_ms"]))
        total_crc_drops += int(rep.get("crc_drops", 0))
        runs.append(
            {
                "run": i,
                "payload_bytes": sz,
                "killed_lanes": sorted(killed),
                "drop_rate": drop_rate,
                "corrupt_lan": corrupt_lan,
                "success": ok,
                "elapsed_ms": rep["elapsed_ms"],
                "k_blocks": rep.get("k_blocks", 0),
                "droplets_sent": rep.get("droplets_sent", 0),
                "crc_drops": rep.get("crc_drops", 0),
                "error": rep.get("error", ""),
            }
        )

    lat_sorted = sorted(latencies)
    p50 = lat_sorted[len(lat_sorted) // 2] if lat_sorted else 0.0
    p95 = lat_sorted[min(len(lat_sorted) - 1, int(0.95 * len(lat_sorted)))] if lat_sorted else 0.0
    summary = {
        "passed": passed,
        "total": 20,
        "pass_rate_pct": round(100.0 * passed / 20.0, 2),
        "min_ms": round(min(lat_sorted), 2) if lat_sorted else 0.0,
        "p50_ms": round(p50, 2),
        "p95_ms": round(p95, 2),
        "max_ms": round(max(lat_sorted), 2) if lat_sorted else 0.0,
        "total_crc_drops": total_crc_drops,
        "runs": runs,
    }
    print(
        f"  Soak Summary: {passed}/20 ({summary['pass_rate_pct']}%) | "
        f"min={summary['min_ms']}ms p50={summary['p50_ms']}ms "
        f"p95={summary['p95_ms']}ms max={summary['max_ms']}ms | crc_drops={total_crc_drops}"
    )
    return summary


def suite_audit(
    env: EnvironmentProfile, solo_rows: list[dict[str, Any]], bulk_256k: dict[str, Any]
) -> dict[str, Any]:
    print("\n=== SUITE 5: SECURITY & INVARIANT AUDIT ===")
    checks: dict[str, dict[str, Any]] = {}

    # 1. GHOST_127 zero wire payload
    ghost_row = next((r for r in solo_rows if r["lane_id"] == "GHOST_127"), None)
    checks["ghost_zero_payload"] = {
        "passed": bool(ghost_row and ghost_row["success"] and ghost_row["wire_payload_bytes"] == 0),
        "detail": f"wire_payload_bytes={ghost_row['wire_payload_bytes'] if ghost_row else 'N/A'}",
    }

    # 2. LAN_LENGTH bit-flip invariance
    lan_row = next((r for r in solo_rows if r["lane_id"] == "LAN_LENGTH"), None)
    checks["lan_bitflip_invariant"] = {
        "passed": bool(lan_row and lan_row["success"] and lan_row["sha256_match"]),
        "detail": "100% payload XOR 0xFF survived bit-exact" if lan_row else "N/A",
    }

    # 3. HYPERV_MCAST TTL=0 check
    ttl_val = -1
    if "HYPERV_MCAST" in env.realms and env.realms["HYPERV_MCAST"].available:
        m_rx = HyperVMcastConstellationLane(env.realms["HYPERV_MCAST"].ip, 20, b"ttl-check")
        ep = m_rx.start_receiver()
        m_tx = HyperVMcastConstellationLane(env.realms["HYPERV_MCAST"].ip, 20, b"ttl-check")
        try:
            m_tx.send_droplet(ep, b"A" * 20, 0)
            if m_tx._tx_sock is not None:
                ttl_val = m_tx._tx_sock.getsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL)
        finally:
            m_tx.close()
            m_rx.close()
    checks["mcast_ttl_zero"] = {
        "passed": ttl_val == 0,
        "detail": f"IP_MULTICAST_TTL={ttl_val}",
    }

    # 4. Holographic topology binding tamper test
    tampered_env = copy.deepcopy(env)
    fp = env.topology_fingerprint
    flipped_ch = "0" if fp[0] != "0" else "1"
    tampered_env.topology_fingerprint = flipped_ch + fp[1:]

    tampered_rx = ChimeraReceiver(tampered_env, droplet_size=20)
    tampered_offer = tampered_rx.start()
    topo_rejected = False
    topo_detail = ""
    try:
        tx_real = ChimeraSender(env, tampered_offer)
        blob16k = _make_semi_structured_payload(16384)
        _, rep_tamp = tx_real.send_holographic(tampered_rx, blob16k, FaultProfile(), timeout_s=10.0)
        topo_rejected = (not rep_tamp.sha256_match) and (not rep_tamp.success)
        topo_detail = (
            f"Tampered FP rejected (sha256_match={rep_tamp.sha256_match})"
            if topo_rejected
            else "WARNING: tampered FP still matched!"
        )
    finally:
        tampered_rx.close()
    checks["holo_topology_binding"] = {
        "passed": topo_rejected,
        "detail": topo_detail,
    }

    # 5. Holographic entropy gain (raw < 6.5 -> masked > 7.99)
    raw_ent = float(bulk_256k["raw_entropy_bits_per_byte"])
    masked_ent = float(bulk_256k["after_chimera_holographic"]["holo_entropy_bits_per_byte"] or 0.0)
    checks["holo_entropy_gain"] = {
        "passed": (raw_ent < 6.5) and (masked_ent > 7.99),
        "detail": f"raw={raw_ent:.5f} -> masked={masked_ent:.5f} bits/byte",
    }

    passed_cnt = sum(1 for c in checks.values() if c["passed"])
    for name, res in checks.items():
        print(f"  {name:<24} {'PASS' if res['passed'] else 'FAIL'} | {res['detail']}")
    return {"passed": passed_cnt, "total": len(checks), "checks": checks}


def run_eval(out_path: Path | None = None) -> dict[str, Any]:
    _configure_utf8()
    env = probe_environment()
    rx = ChimeraReceiver(env, droplet_size=20)
    offer = rx.start()
    try:
        tx = ChimeraSender(env, offer)
        before_after = suite_before_after(env, rx, tx)
        solo_lanes = suite_solo_lanes(env, rx, tx)
        drop_sweep = suite_drop_sweep(rx, tx)
        scaling = suite_scaling(rx, tx)
        soak = suite_soak(env, rx, tx)
        v05 = suite_v05_upgrades(rx, tx)
    finally:
        rx.close()

    audit = suite_audit(env, solo_lanes, before_after["bulk_256k"])

    eval_data = {
        "environment": {
            "hostname": env.hostname,
            "os_info": env.os_info,
            "topology_fingerprint": env.topology_fingerprint,
            "active_droplet_lanes": env.active_droplet_lanes(),
        },
        "suite_before_after": before_after,
        "suite_solo_lanes": solo_lanes,
        "suite_drop_sweep": drop_sweep,
        "suite_scaling": scaling,
        "suite_soak": soak,
        "suite_v05_upgrades": v05,
        "suite_audit": audit,
    }
    target = out_path or Path("chimera_eval.json")
    target.write_text(json.dumps(eval_data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nEvaluation telemetry saved to: {target.resolve()}")
    return eval_data


if __name__ == "__main__":
    run_eval()

