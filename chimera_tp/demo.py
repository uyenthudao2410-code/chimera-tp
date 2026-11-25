"""Live 4-phase CHIMERA-TP demonstration on the local Windows network stack."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

from chimera_tp.gf256 import shannon_entropy
from chimera_tp.probe import EnvironmentProfile, probe_environment
from chimera_tp.protocol import ChimeraReceiver, ChimeraSender, FaultProfile, TransferReport


def _configure_console_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except OSError:
                pass


def _print_banner(title: str) -> None:
    bar = "=" * 78
    print(f"\n{bar}\n  {title}\n{bar}")


def _print_probe_table(env: EnvironmentProfile) -> None:
    _print_banner("PHASE 0: LIVE WINDOWS NETWORK REALM DISCOVERY")
    print(f"Host       : {env.hostname} ({env.os_info})")
    print(f"Gateway    : {env.default_gateway or 'N/A'} | DNS: {', '.join(env.dns_servers) or 'N/A'}")
    print(f"Fingerprint: {env.topology_fingerprint}")
    print("-" * 78)
    print(f"{'LANE_ID':<14} {'OK':<4} {'IP':<28} {'MTU':<11} {'MS':>6}  {'TECHNIQUE'}")
    print("-" * 78)
    for lid, r in env.realms.items():
        status = "YES" if r.available else "NO"
        print(
            f"{lid:<14} {status:<4} {r.ip:<28} {str(r.mtu):<11} {r.probe_ms:>6.2f}  {r.technique}"
        )


def _print_report(label: str, report: TransferReport) -> None:
    _print_banner(label)
    print(
        f"Mode: {report.mode} | Success: {report.success} | "
        f"SHA-256 MATCH: {str(report.sha256_match).upper()}"
    )
    print(f"Expected SHA-256 : {report.expected_sha256}")
    print(f"Actual   SHA-256 : {report.actual_sha256}")
    print(
        f"Payload: {report.payload_bytes:,} B | Coded: {report.wire_coded_bytes:,} B | "
        f"k={report.k_blocks} x {report.block_size} B"
    )
    print(
        f"Droplets TX/RX/Innov/CRC-Drop: {report.droplets_sent} / {report.droplets_received} / "
        f"{report.innovative_droplets} / {report.crc_drops}"
    )
    print(
        f"Elapsed: {report.elapsed_ms:.2f} ms | Effective Goodput: {report.effective_kbps:.2f} kbps"
    )
    if report.holo_entropy_bits_per_byte is not None:
        print(
            f"Holographic Jumbo Superframes: {report.jumbo_chunks} chunks | "
            f"Wire Shannon Entropy: {report.holo_entropy_bits_per_byte:.5f} bits/byte"
        )
    print("-" * 78)
    print(
        f"{'LANE_ID':<14} {'STATE':<7} {'PKT_TX':>7} {'PKT_RX':>7} "
        f"{'DRP_TX':>7} {'DRP_RX':>7} {'WIRE_PAY_B':>11} {'AVG_TX_MS':>9}"
    )
    print("-" * 78)
    for lid, st in report.per_lane_stats.items():
        state = "KILLED" if st.get("killed") else "ALIVE"
        print(
            f"{lid:<14} {state:<7} {st['packets_sent']:>7} {st['packets_recv']:>7} "
            f"{st['droplets_sent']:>7} {st['droplets_recv']:>7} "
            f"{st['wire_payload_bytes']:>11,} {st['avg_tx_ms']:>9.3f}"
        )


def run_demo(output_json: Path | None = None) -> dict[str, Any]:
    _configure_console_utf8()
    env = probe_environment()
    _print_probe_table(env)

    # Rich Vietnamese + Unicode + high-entropy telemetry payload (~780 bytes)
    # ensuring zlib output spans ~30+ GF(256) blocks so ALL 7 alien lanes fire heavily.
    sample_seed_hex = hashlib.sha256(b"CHIMERA-TP-PHASE1-NONCE").hexdigest()
    phase1_text = (
        "CHIMERA-TP :: Giao thức truyền tải đa chiều biến hình trên Windows!\n"
        "Mục tiêu: biến từng dị tật của card mạng (Loopback /8, Intel I219-V LAN, "
        "Tailscale MTU 1280 IPv4/IPv6 ULA, Hyper-V Multicast TTL=0, WSL2 vSwitch, "
        "Raw ICMP Kernel Bounce, ::1 4GiB Jumbo) thành kênh vật lý mật mã học.\n"
        f"Topology Fingerprint: {env.topology_fingerprint}\n"
        f"Seed Anchor: {sample_seed_hex} | "
        "Dữ liệu thử nghiệm đa ngôn ngữ: Tiếng Việt có dấu (ă, â, đ, ê, ô, ơ, ư), "
        "日本語テスト, Ελληνικά ΔΣΩ, Symbols ⚛⚡🛰🧬.\n"
        "Entropy salt: " + os.urandom(220).hex()
    )
    phase1_payload = phase1_text.encode("utf-8")

    # Phase 2 payload (~520 bytes) for Apocalypse Chaos Survival
    phase2_text = (
        "APOCALYPSE CHAOS SURVIVAL TEST :: 3 LANES KILLED + 20% PACKET LOSS + "
        "100% LAN_LENGTH PAYLOAD BIT-FLIP CORRUPTION!\n"
        "Nếu 3 đường hầm chết hẳn (GHOST_127, WSL_PERMUTE, TS_V6_CHORD), "
        "GF(256) RLNC vẫn giải được hệ phương trình tuyến tính từ các giọt sống sót!\n"
        "Verification Salt: " + os.urandom(180).hex()
    )
    phase2_payload = phase2_text.encode("utf-8")

    # Phase 3: 256 KiB structured + semi-repetitive binary payload
    # Raw entropy is intentionally moderate (~4.5 bits/byte) so 7.99+ bits/byte
    # masked entropy proves cryptographic whitening over ::1 jumbo superframes.
    header_block = (
        b"CHIMERA-HOLOGRAPHIC-256K|"
        + env.topology_fingerprint.encode("ascii")
        + b"|"
        + b"\x00\x11\x22\x33\x44\x55\x66\x77\x88\x99\xAA\xBB\xCC\xDD\xEE\xFF" * 8
    )
    raw_blob = bytearray()
    while len(raw_blob) < 256 * 1024:
        raw_blob.extend(header_block)
        raw_blob.extend(os.urandom(32))
    phase3_payload = bytes(raw_blob[: 256 * 1024])
    phase3_raw_entropy = round(shannon_entropy(phase3_payload), 5)

    receiver = ChimeraReceiver(env, droplet_size=20)
    offer = receiver.start()
    try:
        sender = ChimeraSender(env, offer)

        # Phase 1: PURE-METAMORPHIC across ALL active lanes
        rec1, rep1 = sender.send_metamorphic(receiver, phase1_payload, FaultProfile())
        assert rec1 == phase1_payload, "Phase 1 payload mismatch!"
        _print_report("PHASE 1: PURE-METAMORPHIC (ALL 7 ALIEN LANES)", rep1)

        # Phase 2: APOCALYPSE CHAOS SURVIVAL
        apocalypse_fault = FaultProfile(
            kill_lanes={"GHOST_127", "WSL_PERMUTE", "TS_V6_CHORD"},
            packet_drop_rate=0.20,
            corrupt_lan_noise=True,
        )
        rec2, rep2 = sender.send_metamorphic(receiver, phase2_payload, apocalypse_fault)
        assert rec2 == phase2_payload, "Phase 2 payload mismatch!"
        _print_report(
            "PHASE 2: APOCALYPSE CHAOS SURVIVAL (3 KILLED + 20% DROP + 100% LAN BIT-FLIP)",
            rep2,
        )

        # Phase 3: HOLOGRAPHIC-SPLIT 256 KiB
        rec3, rep3 = sender.send_holographic(receiver, phase3_payload, FaultProfile())
        assert rec3 == phase3_payload, "Phase 3 payload mismatch!"
        _print_report("PHASE 3: HOLOGRAPHIC-SPLIT (256 KiB ::1 JUMBO + 7-LANE KEY CAPSULE)", rep3)
        print(f"Raw Unmasked Payload Entropy: {phase3_raw_entropy:.5f} bits/byte")
        print(f"Masked Wire Jumbo Entropy   : {rep3.holo_entropy_bits_per_byte:.5f} bits/byte")
    finally:
        receiver.close()

    telemetry = {
        "environment": env.to_dict(),
        "phase1_metamorphic": rep1.to_dict(),
        "phase2_apocalypse": rep2.to_dict(),
        "phase3_holographic": {
            **rep3.to_dict(),
            "raw_payload_entropy_bits_per_byte": phase3_raw_entropy,
        },
    }
    target_path = output_json or Path("chimera_telemetry.json")
    target_path.write_text(
        json.dumps(telemetry, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\nTelemetry saved to: {target_path.resolve()}")
    return telemetry


if __name__ == "__main__":
    run_demo()
