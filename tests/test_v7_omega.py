"""Comprehensive tests for CHIMERA-HYPER v7.0 OMEGA-FABRIC (All 14 Moonshots)."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import urllib.request

from chimera_tp.dashboard import ChimeraDaemon
from chimera_tp.native import (
    chacha20_xor,
    gf256_recode,
    ppm_compress,
    ppm_decompress,
    slepian_syndrome,
    v7_native_caps,
)
from chimera_tp.omega_bench import format_omega_markdown, run_omega_benchmark
from chimera_tp.omega_compute import (
    NeuralPpmCodec,
    RemoteRamPool,
    RemoteRamStore,
    UepDisplayStream,
    WasmActivePipe,
    build_wasm_byte_counter_module,
)
from chimera_tp.omega_storage import (
    GhostBlockEngine,
    ParasiticDeadDropMesh,
    RegeneratingMeshVault,
    SlepianWolfSync,
    detect_fs_mount_caps,
)
from chimera_tp.omega_transport import (
    GeneticWireEngine,
    MultiIspBondingEngine,
    PolymorphicMimicLayer,
    QuantumChaffShield,
    RlncRecodingRelay,
    SiliconDataPlane,
    VirtualNicBridge,
    detect_os_tun_caps,
    hybrid_pq_decaps,
    hybrid_pq_encaps,
    hybrid_pq_keypair,
    x25519_keypair,
    x25519_shared,
)


class TestOmegaV7Protocol(unittest.TestCase):
    def test_native_v7_chacha20_rfc8439_and_ppm_slepian_recode(self) -> None:
        # RFC 8439 Section 2.4.2 test vector
        key = bytes(range(0x00, 0x20))
        nonce = bytes.fromhex("000000000000004a00000000")
        pt = (
            b"Ladies and Gentlemen of the class of '99: If I could offer you "
            b"only one tip for the future, sunscreen would be it."
        )
        expected_ct = bytes.fromhex(
            "6e2e359a2568f98041ba0728dd0d6981"
            "e97e7aec1d4360c20a27afccfd9fae0b"
            "f91b65c5524733ab8f593dabcd62b357"
            "1639d624e65152ab8f530c359f0861d8"
            "07ca0dbf500d6a6156a38e088a22b65e"
            "52bc514d16ccf806818ce91ab7793736"
            "5af90bbf74a35be6b40b8eedf2785e42"
            "874d"
        )
        ct = chacha20_xor(pt, key, nonce, counter=1)
        self.assertEqual(ct, expected_ct)
        self.assertEqual(chacha20_xor(ct, key, nonce, counter=1), pt)

        caps = v7_native_caps()
        self.assertIsInstance(caps, dict)
        self.assertTrue(all(k in caps for k in ("chacha20", "rlnc_recode", "ppm_range", "slepian_syndrome")))

        # Order-2 PPM bit-exact roundtrip (native core + NeuralPpmCodec)
        sample = b'{"msg":"CHIMERA_PPM","val":42}\n' * 80
        comp = ppm_compress(sample)
        self.assertEqual(ppm_decompress(comp), sample)
        self.assertLess(len(comp), len(sample) // 2)
        ncomp = NeuralPpmCodec.compress(sample)
        self.assertEqual(NeuralPpmCodec.decompress(ncomp), sample)
        self.assertLess(len(ncomp), 60)

        # Slepian-Wolf syndrome linearity & GF(256) recoding
        blocks = b"A" * 64 + b"B" * 64
        syn = slepian_syndrome(blocks, 2, 64, alpha=0x03, num_parities=4)
        self.assertEqual(len(syn), 4 * 64)
        p_out, c_out = gf256_recode(blocks, b"\x01\x00\x00\x01", 2, 2, 64, b"\x05\x09")
        self.assertEqual(len(p_out), 64)
        self.assertEqual(c_out, b"\x05\x09")

    def test_ideas_1_to_4_transport_and_idea_11_14_security_evolution(self) -> None:
        # Idea #1: X25519 + ChaCha20 + Virtual NIC + real OS probe
        os_caps = detect_os_tun_caps()
        self.assertIn("platform", os_caps)
        priv_a, pub_a = x25519_keypair()
        priv_b, pub_b = x25519_keypair()
        ss_a = x25519_shared(priv_a, pub_b)
        ss_b = x25519_shared(priv_b, pub_a)
        self.assertEqual(ss_a, ss_b)

        nic_a = VirtualNicBridge(SiliconDataPlane(ss_a))
        nic_b = VirtualNicBridge(SiliconDataPlane(ss_b))
        pkt = nic_a.wrap_ip_packet(b"L3_PAYLOAD_TUN_" * 20)
        unw = nic_b.unwrap_ip_packet(pkt)
        self.assertIsNotNone(unw)
        assert unw is not None
        self.assertEqual(unw[2], b"L3_PAYLOAD_TUN_" * 20)

        # Idea #2: Multi-ISP Bonding 0ms blackout failover
        bond = MultiIspBondingEngine().send_bonded(b"BONDED_" * 150, k=8, redundancy=6, blackout_lane=0)
        self.assertTrue(bond["ok"])
        self.assertGreater(bond["blackout_dropped"], 0)

        # Idea #3: Polymorphic DPI mimicry
        mimic = PolymorphicMimicLayer()
        for mode in ("raw", "quic", "webrtc"):
            sealed = mimic.wrap(b"TEST_FRAME_99", mode=mode)
            self.assertEqual(mimic.unwrap(sealed, mode=mode), b"TEST_FRAME_99")
        adapted = mimic.adapt_against_dpi(b"ADAPT", dpi_blocks={"raw", "quic"})
        self.assertTrue(adapted["ok"])
        self.assertEqual(adapted["selected_mode"], "webrtc")

        # Idea #4: Multi-hop RLNC recoding
        rec = RlncRecodingRelay.run_multihop_demo(b"HOP_SECRET_" * 80, k=8, m_in=10, m_out=10)
        self.assertTrue(rec["ok"])
        self.assertFalse(rec["plaintext_decoded_at_relay"])

        # Idea #11: Hybrid PQ KEM (20 trials) + Chaff-as-RLNC
        for _ in range(20):
            sk, pk = hybrid_pq_keypair()
            ss1, ct = hybrid_pq_encaps(pk)
            ss2 = hybrid_pq_decaps(sk, ct)
            self.assertEqual(ss1, ss2)
        qcs = QuantumChaffShield.benchmark_chaff_shield()
        self.assertTrue(qcs["ok"])

        # Idea #14: Genetic Wire Evolution
        gw = GeneticWireEngine().evolve(loss_rate=0.08, rtt_ms=65.0, dpi_active=True, generations=12)
        self.assertTrue(gw["ok"])
        self.assertGreater(gw["evolved_fitness"], gw["baseline_static_fitness"])

    def test_ideas_5_6_8_9_storage_regen_slepian_and_parasitic(self) -> None:
        fs_caps = detect_fs_mount_caps()
        self.assertIn("platform", fs_caps)

        # Idea #5: Ghost-Block 4KB
        old_f = bytearray(b"CAD_DATABASE_SECTOR_" * 1200)
        new_f = bytearray(old_f)
        new_f[4500:4620] = b"MODIFIED_CAD_GEOMETRY_" * 5 + b"Y" * 10
        gb = GhostBlockEngine.diff_4kb_blocks(bytes(old_f), bytes(new_f))
        self.assertEqual(gb["dirty_blocks"], 1)
        self.assertEqual(GhostBlockEngine.apply_4kb_patch(bytes(old_f), gb["frame"], gb["orig_len"]), bytes(new_f))

        # Idea #6: Cauchy K=3, N=5 self-healing vault
        mv = RegeneratingMeshVault(k=3, n=5)
        secret = b"TOP_SECRET_MESH_SHARDS_" * 60
        enc = mv.encode_shards(secret)
        healed = mv.repair_missing_shard([enc["shards"][0], enc["shards"][2], enc["shards"][4]], target_node_idx=1)
        self.assertEqual(healed["sha256"], enc["shards"][1]["sha256"])
        self.assertEqual(mv.decode_shards([healed, enc["shards"][0], enc["shards"][3]]), secret)

        # Idea #8: 0-RTT Slepian-Wolf Multi-Block Blind Sync (3 scattered corrupted blocks!)
        doc_old = bytearray(b"KERNEL_STATE_RECORD_" * 400)  # 8000 B -> 16 blocks of 512 B
        doc_new = bytearray(doc_old)
        doc_new[100:130] = b"PATCH_IN_BLK0_VERIFIED_A" + b"!" * 6
        doc_new[2600:2632] = b"PATCH_IN_BLK5_VERIFIED_BBBBBBBBB"
        doc_new[5700:5724] = b"PATCH_IN_BLK11_VERIFIED!"
        pkt = SlepianWolfSync.encode_blind_packet(bytes(doc_new), block_len=512, max_err_blocks=3)
        dec = SlepianWolfSync.decode_blind_packet(bytes(doc_old), pkt)
        self.assertTrue(dec["ok"])
        self.assertEqual(dec["decoded"], bytes(doc_new))
        self.assertEqual(sorted(dec["repaired_blocks"]), [0, 5, 11])

        # Idea #9: Parasitic Dead-Drop Mesh
        pdd = ParasiticDeadDropMesh.scatter_and_recover(b"ZERO_DOLLAR_MESH_" * 15, dead_carriers=2)
        self.assertTrue(pdd["ok"])

    def test_ideas_7_10_12_13_wasm_ram_ppm_uep_and_full_benchmark(self) -> None:
        # Idea #7: WASM byte counter + fuel exhaustion test
        wasm_mod = build_wasm_byte_counter_module(target_byte=ord("\n"))
        logs = b"line1\nline2\nline3\n" * 50
        ok_res = WasmActivePipe().execute_buffer(wasm_mod, logs, fn_name="filter")
        self.assertTrue(ok_res["ok"])
        self.assertEqual(ok_res["result"], 150)
        exhaust = WasmActivePipe(max_steps=80).execute_buffer(wasm_mod, logs, fn_name="filter")
        self.assertFalse(exhaust["ok"])
        self.assertIn("fuel", exhaust["error"])

        # Idea #10: RemoteRamStore & Pool
        pool = RemoteRamPool()
        pages = [f"RAM_PAGE_{i}_".encode().ljust(4096, b"Z") for i in range(4)]
        ram_r = pool.swap_out_and_fault_in(pages)
        self.assertTrue(ram_r["ok"])
        self.assertEqual(ram_r["verified_pages"], 4)

        # Idea #12: NeuralPpmCodec
        st_log = b'{"ok":true,"node":"svhome","ms":4.2}\n' * 120
        ppm_b = NeuralPpmCodec.benchmark(st_log)
        self.assertTrue(ppm_b["ok"])
        self.assertLessEqual(ppm_b["ppm_bytes"], ppm_b["zlib9_bytes"])

        # Idea #13: UEP 15% loss display
        uep = UepDisplayStream.benchmark_15pct_loss()
        self.assertTrue(uep["ok"])

        # Orchestrator 14/14
        full = run_omega_benchmark()
        self.assertTrue(full["ok"])
        self.assertEqual(full["ideas_verified"], 14)
        self.assertEqual(full["ideas_total"], 14)
        md = format_omega_markdown(full)
        self.assertIn("CHIMERA-HYPER v7.0.0", md)

    def test_daemon_omega_endpoints_and_isolated_zero_weight_rss(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            from chimera_tp.autopilot import OpsConfig

            cfg = OpsConfig(
                role="server",
                node_name="omega_test_node",
                dashboard_bind="127.0.0.1:0",
                beam_port=0,
                rpc_v4_port=0,
                rpc_v6_port=-1,
                query_port=0,
                warp_port=-1,
                edge_proxy_port=-1,
                allowed_query_roots=[str(root)],
                search_roots=[str(root)],
                edge_targets={},
                phantom_enabled=False,
            )
            daemon = ChimeraDaemon(config=cfg, ops_dir=root / "ops", auto_seed_on_empty=False).start()
            base = f"http://127.0.0.1:{daemon.http_addr[1]}"
            try:
                h = json.loads(urllib.request.urlopen(f"{base}/api/health", timeout=4.0).read().decode())
                self.assertEqual(h["version"], "7.0.0")

                st = json.loads(urllib.request.urlopen(f"{base}/api/omega/status", timeout=4.0).read().decode())
                self.assertTrue(st["ok"])
                self.assertIn("native_v7", st)

                # Remote RAM round-trip over daemon HTTP
                req_put = urllib.request.Request(
                    f"{base}/api/omega/ram-put",
                    data=json.dumps({"page_id": "p4k", "text": "OMEGA_HTTP_4KB_" * 200}).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                self.assertTrue(json.loads(urllib.request.urlopen(req_put, timeout=4.0).read().decode())["ok"])
                req_get = urllib.request.Request(
                    f"{base}/api/omega/ram-get",
                    data=json.dumps({"page_id": "p4k"}).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                self.assertTrue(json.loads(urllib.request.urlopen(req_get, timeout=4.0).read().decode())["ok"])

                # WASM endpoint
                req_w = urllib.request.Request(
                    f"{base}/api/omega/wasm-exec",
                    data=json.dumps({"input_text": "a\nb\nc\n"}).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                w_res = json.loads(urllib.request.urlopen(req_w, timeout=4.0).read().decode())
                self.assertTrue(w_res["ok"])
                self.assertEqual(w_res["result"], 3)

                # Full 14-idea HTTP benchmark endpoint
                req_b = urllib.request.Request(
                    f"{base}/api/omega/benchmark",
                    data=json.dumps({"local_only": True}).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                b_res = json.loads(urllib.request.urlopen(req_b, timeout=20.0).read().decode())
                self.assertTrue(b_res["ok"])
                self.assertEqual(b_res["ideas_verified"], 14)
            finally:
                daemon.close()

            # Isolated fresh subprocess Zero-Weight RSS check (< 80 MB)
            probe_code = (
                "import json; from pathlib import Path; "
                "from chimera_tp.autopilot import OpsConfig; "
                "from chimera_tp.dashboard import ChimeraDaemon; "
                f"cfg=OpsConfig(role='server',node_name='zw',dashboard_bind='127.0.0.1:0',beam_port=0,rpc_v4_port=0,rpc_v6_port=-1,query_port=0,warp_port=-1,edge_proxy_port=-1,"
                f"allowed_query_roots=[{str(root)!r}],search_roots=[{str(root)!r}],phantom_enabled=False); "
                f"d=ChimeraDaemon(config=cfg,ops_dir=Path({str(root/'o2')!r}),auto_seed_on_empty=False).start(); "
                "st=d.status_payload(); d.close(); print(json.dumps(st['zero_weight']))"
            )
            proc = subprocess.run([sys.executable, "-c", probe_code], capture_output=True, text=True, check=True)
            zw = json.loads(proc.stdout.strip().splitlines()[-1])
            self.assertTrue(zw["zero_weight_ok"], f"RSS exceeded 80MB: {zw}")


if __name__ == "__main__":
    unittest.main()
