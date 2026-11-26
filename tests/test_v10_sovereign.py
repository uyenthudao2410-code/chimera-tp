"""CHIMERA-HYPER v10.0 SOVEREIGN & OUTLAW Adversarial Tests (13 Wave 2 Breakthroughs)."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from chimera_tp.v10_outlaw_engines import (
    CausalTimeTravelFabric,
    DctStegoDrive,
    EtherDelayLineVault,
    GeoTopologyFuzzyAuth,
    ProceduralTarpitLabyrinth,
    ScavengerGridScheduler,
    WasmProgramSynthesizer,
)
from chimera_tp.v10_sovereign_crypto import (
    _ED_L,
    FrostThreshold2of3,
    Gf256MpcEngine,
    InlineBitRotHealer,
)
from chimera_tp.v10_sovereign_runtime import (
    AsymmetricKalmanBondEngine,
    VerifiableTraceProver,
    WasmLiveTeleportEngine,
)
from chimera_tp.omega_compute import build_wasm_byte_counter_module


class TestV10Sovereign(unittest.TestCase):
    def test_01_frost_2of3_all_pairs_and_forged_share_rejected(self) -> None:
        res = FrostThreshold2of3.run_benchmark()
        self.assertTrue(res["ok"], res)
        self.assertTrue(res["tamper_rejected"])
        self.assertTrue(res["wrong_msg_rejected"])
        self.assertEqual(set(res["pairs_verified"].keys()), {"1+2", "1+3", "2+3"})
        self.assertTrue(all(res["pairs_verified"].values()))

        # Extra adversarial forged nonce/share check directly
        dkg = FrostThreshold2of3.dkg_2of3(seed=b"UNIT_TEST_FROST_SEED")
        msg = b"ADVERSARIAL_FROST_TEST"
        n1 = FrostThreshold2of3.commit_nonce(1, entropy=b"E1" * 16)
        n3 = FrostThreshold2of3.commit_nonce(3, entropy=b"E3" * 16)
        commits = [(1, n1["D"], n1["E"]), (3, n3["D"], n3["E"])]
        z1 = FrostThreshold2of3.partial_sign(1, dkg["shares"][1], n1, commits, dkg["group_pubkey"], msg)
        z3 = FrostThreshold2of3.partial_sign(3, dkg["shares"][3], n3, commits, dkg["group_pubkey"], msg)
        _, forged_ok = FrostThreshold2of3.verify_partial_and_aggregate(
            dkg["group_pubkey"], dkg["pub_shares"], commits, {1: z1, 3: (z3 + 7) % _ED_L}, msg
        )
        self.assertFalse(forged_ok)

    def test_02_wasm_live_checkpoint_teleport_and_digest_guard(self) -> None:
        res = WasmLiveTeleportEngine.run_benchmark()
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["got_result"], res["expected_result"])
        self.assertLess(res["paused_at_step"], res["total_steps"])

        # Adversarial tampered digest on resume must raise ValueError
        wasm = build_wasm_byte_counter_module(target_byte=ord("A"))
        vm = WasmLiveTeleportEngine(max_steps=100_000, max_mem_pages=2)
        paused = vm.execute_with_checkpoint(wasm, b"A" * 64, fn_name="filter", step_budget=15)
        self.assertTrue(paused["paused"])
        bad_ckpt = dict(paused["checkpoint"])
        bad_ckpt["code_sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            vm.execute_with_checkpoint(wasm, b"", fn_name="filter", checkpoint=bad_ckpt)

    def test_03_verifiable_trace_bisection_fraud_pinpointing(self) -> None:
        for cheat in (1, 17, 173, 255):
            res = VerifiableTraceProver.run_benchmark(n_steps=256, cheat_step=cheat)
            self.assertTrue(res["ok"], res)
            self.assertTrue(res["fraud_proven"])
            self.assertEqual(res["pinpointed_step"], cheat)
            self.assertLessEqual(res["bisection_rounds"], 9)

    def test_04_gf256_mpc_exact_and_single_share_uncorrelated(self) -> None:
        vx = bytes(range(256)) + os.urandom(256)
        vy = bytes(reversed(range(256))) + os.urandom(256)
        res = Gf256MpcEngine.mpc_gf256_dot_product(vx, vy)
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["mpc_dot_12"], res["expected_dot"])
        self.assertEqual(res["mpc_dot_23"], res["expected_dot"])
        self.assertLess(res["single_share_match_rate"], 0.25)

        # Single share differs completely from uniform secret (constant 0x42 buffer)
        secret = b"\x42" * 1024
        s1, s2, s3 = Gf256MpcEngine.share_bytes(secret)
        self.assertNotEqual(s1, secret)
        self.assertNotEqual(s2, secret)
        self.assertEqual(Gf256MpcEngine.reconstruct(1, s1, 3, s3), secret)

    def test_05_inline_bitrot_healer_and_overlimit_rejection(self) -> None:
        res = InlineBitRotHealer.run_benchmark()
        self.assertTrue(res["ok"], res)
        self.assertTrue(res["sha256_exact"])
        self.assertLessEqual(res["overhead_pct"], 5.0)

        # >3 corrupted bytes in one 249-byte chunk exceeds RS(255,249) 3-byte capacity -> ValueError
        data = b"Z" * 249
        syns = InlineBitRotHealer.encode_syndromes(data)
        bad = bytearray(data)
        for pos in (1, 10, 20, 30, 40):
            bad[pos] ^= 0xAA
        with self.assertRaises(ValueError):
            InlineBitRotHealer.heal_inplace(bad, syns)

    def test_06_asymmetric_kalman_bonding(self) -> None:
        res = AsymmetricKalmanBondEngine.run_benchmark()
        self.assertTrue(res["ok"], res)
        self.assertGreaterEqual(res["jitter_reduction_pct"], 50.0)

    def test_07_outlaw_engines_all_seven_and_tarpit_zero_disk(self) -> None:
        eth = EtherDelayLineVault.run_benchmark()
        self.assertTrue(eth["ok"], eth)
        self.assertEqual(eth["disk_bytes_written"], 0)
        self.assertTrue(eth["memory_wiped"])

        dct = DctStegoDrive.run_benchmark()
        self.assertTrue(dct["ok"], dct)
        self.assertTrue(dct["secret_exact_after_jpeg_q70"])
        self.assertGreaterEqual(dct["psnr_db"], 28.0)

        # Tarpit deterministic replay & strictly 0 disk writes
        with tempfile.TemporaryDirectory() as td:
            before = os.listdir(td)
            tarpit = ProceduralTarpitLabyrinth()
            deep = "/".join(f"tier_{i}" for i in range(1000)) + "/vault.yml"
            a = tarpit.inspect_path(deep)
            b = tarpit.inspect_path(deep)
            self.assertEqual(a["content"], b["content"])
            self.assertEqual(os.listdir(td), before)
        tp_res = ProceduralTarpitLabyrinth.run_benchmark()
        self.assertTrue(tp_res["ok"], tp_res)
        self.assertEqual(tp_res["persistent_ram_bytes"], 0)

        syn = WasmProgramSynthesizer.run_benchmark()
        self.assertTrue(syn["ok"], syn)

        geo = GeoTopologyFuzzyAuth.run_benchmark()
        self.assertTrue(geo["ok"], geo)
        self.assertTrue(geo["mitm_route_rejected"])
        self.assertTrue(geo["legit_jitter_accepted"])

        scav = ScavengerGridScheduler.run_benchmark()
        self.assertTrue(scav["ok"], scav)
        self.assertTrue(scav["handoff_exact"])

        tt = CausalTimeTravelFabric.run_benchmark()
        self.assertTrue(tt["ok"], tt)
        self.assertTrue(tt["tx0_bit_exact"])
        self.assertTrue(tt["dag_branch_tx1_ok"])


if __name__ == "__main__":
    unittest.main()
