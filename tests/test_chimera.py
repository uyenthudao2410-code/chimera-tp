"""Unit and live-network integration tests for CHIMERA-TP."""

from __future__ import annotations

import hashlib
import os
import socket
import threading
import unittest

from chimera_tp.gf256 import (
    EXP,
    LOG,
    RLNCDecoder,
    RLNCEncoder,
    decode_lehmer,
    encode_lehmer,
    gf_inv,
    gf_mul,
)
from chimera_tp.lanes import (
    FaultProfile,
    Ghost127Lane,
    HyperVMcastConstellationLane,
    LanLengthNoiseLane,
    build_droplet_lane,
)
from chimera_tp.probe import probe_environment
from chimera_tp.protocol import ChimeraReceiver, ChimeraSender


class TestGF256AndMath(unittest.TestCase):
    def test_gf256_generator_full_order_255(self) -> None:
        # Generator 0x03 mod 0x11B must visit all 255 non-zero field elements
        seen = set(EXP[:255])
        self.assertEqual(len(seen), 255)
        self.assertNotIn(0, seen)
        for v in range(1, 256):
            self.assertEqual(EXP[LOG[v]], v)
            self.assertEqual(gf_mul(v, gf_inv(v)), 1)

    def test_lehmer_bijection_all_720(self) -> None:
        seen = set()
        for rank in range(720):
            perm = encode_lehmer(rank, 6)
            self.assertEqual(sorted(perm), [0, 1, 2, 3, 4, 5])
            self.assertEqual(decode_lehmer(perm), rank)
            seen.add(tuple(perm))
        self.assertEqual(len(seen), 720)

    def test_rlnc_recovers_after_dropping_50_percent_droplets(self) -> None:
        blocks = [os.urandom(16) for _ in range(12)]
        seed = os.urandom(16)
        enc = RLNCEncoder(blocks, seed)
        dec = RLNCDecoder(k=12, block_size=16, seed=seed)

        # Generate 36 droplets, drop every even droplet (50% loss!)
        for did in range(36):
            drop = enc.generate_droplet(did)
            if did % 2 == 0:
                continue
            crc_ok, _, _ = dec.add_droplet(drop)
            self.assertTrue(crc_ok)
            if dec.is_complete():
                break

        self.assertTrue(dec.is_complete())
        self.assertEqual(dec.solve(), blocks)


class TestLiveHostRealms(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.env = probe_environment()

    def test_probe_discovers_local_realms(self) -> None:
        self.assertGreaterEqual(len(self.env.active_droplet_lanes()), 5)
        self.assertTrue(self.env.realms["GHOST_127"].available)
        self.assertTrue(self.env.realms["LO_V6_JUMBO"].available)
        self.assertEqual(len(self.env.topology_fingerprint), 64)

    def test_every_available_droplet_lane_in_isolation(self) -> None:
        sample = b"\x01\x23\x45\x67\x89\xAB\xCD\xEF" * 2 + b"CHIM"
        self.assertEqual(len(sample), 20)
        seed = b"lane-isolation-0"

        for lid in self.env.active_droplet_lanes():
            with self.subTest(lane=lid):
                received: list[bytes] = []
                done = threading.Event()

                def on_drop(_lane: str, data: bytes, _ts: float) -> None:
                    received.append(data)
                    if len(received) >= 3:
                        done.set()

                rx_lane = build_droplet_lane(
                    lid, self.env, droplet_size=20, session_seed=seed, on_droplet=on_drop, icmp_id=0xD123
                )
                ep = rx_lane.start_receiver()
                tx_lane = build_droplet_lane(
                    lid, self.env, droplet_size=20, session_seed=seed
                )
                try:
                    fault = FaultProfile(corrupt_lan_noise=(lid == "LAN_LENGTH"))
                    for tag in range(3):
                        tx_lane.send_droplet(ep, sample, tag, fault=fault)
                    self.assertTrue(
                        done.wait(timeout=2.0), f"Lane {lid} timed out receiving 3 droplets"
                    )
                    self.assertEqual(received, [sample, sample, sample])

                    if isinstance(tx_lane, Ghost127Lane):
                        self.assertEqual(tx_lane.stats.wire_payload_bytes, 0)
                        self.assertGreater(tx_lane.stats.packets_sent, 0)
                    if isinstance(tx_lane, HyperVMcastConstellationLane):
                        self.assertIsNotNone(tx_lane._tx_sock)
                        ttl = tx_lane._tx_sock.getsockopt(
                            socket.IPPROTO_IP, socket.IP_MULTICAST_TTL
                        )
                        self.assertEqual(ttl, 0)
                    if isinstance(tx_lane, LanLengthNoiseLane):
                        self.assertGreater(tx_lane.stats.wire_payload_bytes, 0)
                finally:
                    tx_lane.close()
                    rx_lane.close()

    def test_end_to_end_metamorphic_apocalypse_and_holographic(self) -> None:
        rx = ChimeraReceiver(self.env, droplet_size=20)
        offer = rx.start()
        try:
            tx = ChimeraSender(self.env, offer)

            # 1. Pure Metamorphic
            p1 = (
                "CHIMERA-TP Unit Test Tiếng Việt + UTF-8 ⚛⚡ "
                + os.urandom(320).hex()
            ).encode("utf-8")
            rec1, rep1 = tx.send_metamorphic(rx, p1, FaultProfile())
            self.assertTrue(rep1.success)
            self.assertTrue(rep1.sha256_match)
            self.assertEqual(rec1, p1)

            # 2. Apocalypse Chaos Survival
            p2 = ("APOCALYPSE-SURVIVAL-" + os.urandom(240).hex()).encode("utf-8")
            fault = FaultProfile(
                kill_lanes={"GHOST_127", "WSL_PERMUTE", "TS_V6_CHORD"},
                packet_drop_rate=0.20,
                corrupt_lan_noise=True,
            )
            rec2, rep2 = tx.send_metamorphic(rx, p2, fault)
            self.assertTrue(rep2.success)
            self.assertTrue(rep2.sha256_match)
            self.assertEqual(rec2, p2)
            self.assertGreater(rep2.droplets_sent, 0)

            # 3. Holographic Split (256 KiB)
            p3 = (b"HOLO256K-" + b"\xAA\x55" * 16) * (256 * 1024 // 41 + 1)
            p3 = p3[: 256 * 1024]
            rec3, rep3 = tx.send_holographic(rx, p3, FaultProfile())
            self.assertTrue(rep3.success)
            self.assertTrue(rep3.sha256_match)
            self.assertEqual(
                hashlib.sha256(rec3).hexdigest(), hashlib.sha256(p3).hexdigest()
            )
            self.assertIsNotNone(rep3.holo_entropy_bits_per_byte)
            self.assertGreater(rep3.holo_entropy_bits_per_byte, 7.95)
        finally:
            rx.close()

    def test_cross_session_straggler_rejected(self) -> None:
        blocks = [os.urandom(16) for _ in range(4)]
        enc_a = RLNCEncoder(blocks, b"seed-session-A-0")
        dec_b = RLNCDecoder(k=4, block_size=16, seed=b"seed-session-B-0")

        straggler = enc_a.generate_droplet(0)
        crc_ok, innovative, rank = dec_b.add_droplet(straggler)
        self.assertFalse(crc_ok)
        self.assertFalse(innovative)
        self.assertEqual(rank, 0)

        # Consecutive high-drop transfers on one ChimeraReceiver must keep RX threads alive
        rx = ChimeraReceiver(self.env, droplet_size=20)
        offer = rx.start()
        try:
            tx = ChimeraSender(self.env, offer)
            p1 = os.urandom(320)
            rec1, rep1 = tx.send_metamorphic(
                rx, p1, FaultProfile(packet_drop_rate=0.55, corrupt_lan_noise=True), timeout_s=10.0
            )
            self.assertTrue(rep1.success)
            self.assertEqual(rec1, p1)

            p2 = os.urandom(320)
            rec2, rep2 = tx.send_metamorphic(
                rx, p2, FaultProfile(packet_drop_rate=0.70, corrupt_lan_noise=True), timeout_s=12.0
            )
            self.assertTrue(rep2.success)
            self.assertEqual(rec2, p2)

            p3 = b"RECOVERY-AFTER-EXTREME-LOSS" * 4
            rec3, rep3 = tx.send_metamorphic(rx, p3, FaultProfile(), timeout_s=8.0)
            self.assertTrue(rep3.success)
            self.assertEqual(rec3, p3)
        finally:
            rx.close()


if __name__ == "__main__":
    unittest.main()
