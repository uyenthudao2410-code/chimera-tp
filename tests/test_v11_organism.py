"""CHIMERA-HYPER v11.0 ORGANISM & AUTOPOIETIC Adversarial Tests (11 Wave 3 Breakthroughs)."""

from __future__ import annotations

import unittest

from chimera_tp.v11_autopoietic_systems import (
    ActiveMatterCell,
    AutopoieticKernelEngine,
    SplitBrainOrchestrator,
    ThermodynamicResourceMarket,
    UnifiedCausalRealityStream,
)
from chimera_tp.v11_organism_mesh import (
    BabelPointerCodec,
    CoupledChaoticWire,
    DataGravityPlanner,
    GravitationalOverlayRouter,
    ImmuneProtocolOrganism,
    MultiverseExecutor,
)


class TestV11Organism(unittest.TestCase):
    def test_01_babel_pointer_codec_roundtrip(self) -> None:
        res = BabelPointerCodec.run_benchmark()
        self.assertTrue(res["ok"], res)
        self.assertTrue(res["bit_exact"])

    def test_02_immune_dpi_organism_evolved_and_chi1(self) -> None:
        res = ImmuneProtocolOrganism.run_benchmark()
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["antibody_header_bytes"], 12)
        self.assertGreater(res["evolved_goodput_mbps"], 15.0)
        self.assertGreaterEqual(res["dpi_evasion_speedup_x"], 10.0)
        # Adversarial raw legacy phenotype blocked by DPI
        drop_pct, mbps = ImmuneProtocolOrganism._simulate_dpi_firewall(shell=0, mtu=1400, fec=0, jitter_ms=0)
        self.assertGreaterEqual(drop_pct, 85.0)
        self.assertLess(mbps, 2.0)

    def test_03_data_gravity_and_hyperbolic_mesh(self) -> None:
        dg = DataGravityPlanner.run_benchmark()
        self.assertTrue(dg["ok"], dg)
        self.assertEqual(dg["job1_heavy_compute_route"], "win-desktop")
        self.assertEqual(dg["job2_heavy_data_route"], "svhome")

        hr = GravitationalOverlayRouter.run_benchmark(n_nodes=16)
        self.assertTrue(hr["ok"], hr)
        self.assertEqual(hr["ip_mutations_midflight"], 8)

    def test_04_coupled_chaotic_wire_avalanche_and_wrong_key(self) -> None:
        res = CoupledChaoticWire.run_benchmark()
        self.assertTrue(res["ok"], res)

        key = b"ADVERSARIAL_CHAOS_KEY_V11_32BYTE"
        nonce = b"NONCE_01"
        pt = b"A" * 2048
        wire = CoupledChaoticWire.encrypt(key, nonce, pt)
        self.assertEqual(CoupledChaoticWire.decrypt(key, wire), pt)
        # 1-bit flip in first ciphertext block cascades across all later blocks
        flipped = bytearray(wire)
        flipped[12] ^= 0x01
        bad = CoupledChaoticWire.decrypt(key, bytes(flipped))
        diff_frac = sum(1 for a, b in zip(pt[128:], bad[128:]) if a != b) / (len(pt) - 128)
        self.assertGreater(diff_frac, 0.40)
        self.assertNotEqual(CoupledChaoticWire.decrypt(b"WRONG_KEY_32_BYTES_0000000000000", wire), pt)

    def test_05_multiverse_and_autopoietic_kernel(self) -> None:
        mv = MultiverseExecutor.run_benchmark()
        self.assertTrue(mv["ok"], mv)

        ak = AutopoieticKernelEngine.run_benchmark()
        self.assertTrue(ak["ok"], ak)
        self.assertTrue(ak["canary_parity_100pct"])
        self.assertTrue(ak["bad_mutant_rolled_back"])

    def test_06_active_matter_cell_blind_search_heal_and_3strike_shred(self) -> None:
        res = ActiveMatterCell.run_benchmark()
        self.assertTrue(res["ok"], res)
        self.assertTrue(res["blind_search_encrypted_ok"])
        self.assertTrue(res["bit_rot_self_healed_and_unlocked"])
        self.assertTrue(res["self_shred_after_3_strikes"])

        k = b"CELL_SECRET_KEY_TEST"
        cell = ActiveMatterCell(k, b"alpha_secret beta_marker gamma_node " * 20)
        self.assertTrue(cell.search_blind_encrypted(cell.make_trapdoor("beta_marker", k)))
        self.assertFalse(cell.search_blind_encrypted(cell.make_trapdoor("absent_tok_999", k)))
        # 2 wrong attempts do NOT destroy yet; 3rd wrong attempt permanently zeroes payload
        for _ in range(2):
            ok, _ = cell.unlock(b"BAD_KEY")
            self.assertFalse(ok)
            self.assertFalse(cell.destroyed)
        ok, _ = cell.unlock(b"BAD_KEY")
        self.assertFalse(ok)
        self.assertTrue(cell.destroyed)
        ok_after, data_after = cell.unlock(k)
        self.assertFalse(ok_after)
        self.assertEqual(data_after, b"")

    def test_07_thermodynamic_market_split_brain_and_reality_dag(self) -> None:
        mkt = ThermodynamicResourceMarket.run_benchmark()
        self.assertTrue(mkt["ok"], mkt)
        self.assertLessEqual(mkt["max_allocated_ram_mb"], 72.5)
        self.assertTrue(mkt["bottleneck_adaptation_ok"])

        sb = SplitBrainOrchestrator.run_benchmark()
        self.assertTrue(sb["ok"], sb)
        self.assertTrue(sb["mpc_dot_exact"])
        self.assertTrue(sb["frost_2of3_verified"])
        self.assertTrue(sb["fraud_bisection_caught"])

        dag_res = UnifiedCausalRealityStream.run_benchmark()
        self.assertTrue(dag_res["ok"], dag_res)
        # Idempotent / duplicate merge convergence check
        a = UnifiedCausalRealityStream("n1")
        b = UnifiedCausalRealityStream("n2")
        e1 = a.append("op1", {"v": 1})
        e2 = b.append("op2", {"v": 2}, parents=[e1])
        a.merge_from(b)
        a.merge_from(b)
        b.merge_from(a)
        self.assertEqual(a.merkle_root(), b.merkle_root())
        self.assertIn(e2, a.nodes)


if __name__ == "__main__":
    unittest.main()
