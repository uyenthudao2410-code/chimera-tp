"""Adversarial & performance verification suite for CHIMERA-HYPER v9.0.0 HYPERDRIVE (Phần IX 6/6)."""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import urllib.error
import urllib.parse
import urllib.request

from chimera_tp.autopilot import OpsConfig
from chimera_tp import __version__
from chimera_tp.dashboard import ChimeraDaemon
from chimera_tp.native import (
    batch_chacha20_xor,
    chacha20_xor,
    lz4_compress,
    lz4_decompress,
    simd_search_count,
    tile_apply_xor,
    tile_diff_xor,
    v9_native_caps,
)
from chimera_tp.phantom_tunnel import (
    PhantomTunnelClient,
    PhantomTunnelServer,
    open_any_packet,
    open_packet,
    open_packet_fast,
    seal_packet,
    seal_packet_fast,
)
from chimera_tp.v9_app_index import LiveClusterIndexer, RemoteAppStreamEngine, SharedCasTurboCache
from chimera_tp.v9_bench import format_hyperdrive_markdown, run_hyperdrive_benchmark
from chimera_tp.v9_dataplane import MultiWanSpeedFusionEngine, NativeDataPlaneEngine
from chimera_tp.v9_nvme_grid import UnifiedHardwareGrid, VirtualNvmeFabric


def _lz4_compress_py_ref(data: bytes) -> bytes:
    """Force Python reference encoder for differential checks against native SIMD C-ABI."""
    import chimera_tp.native as nat

    saved = nat._DLL
    nat._DLL = None
    try:
        return nat.lz4_compress(data)
    finally:
        nat._DLL = saved


class TestHyperdriveV9Protocol(unittest.TestCase):
    def test_native_v9_all_5_functions_differential_and_edge_cases(self) -> None:
        caps = v9_native_caps()
        self.assertEqual(set(caps.keys()), {"lz4_codec", "batch_chacha", "simd_search", "tile_diff"})

        # 1) LZ4 compress/decompress across edge cases: empty, tiny (<13 B), RLE (offset=1), long match, random
        samples = [
            b"",
            b"A",
            b"123456789012",
            b"X" * 3000,
            (b"CHIMERA_HYPERDRIVE_V9_JSON_LOG_ROW_0123456789\n" * 180),
            os.urandom(4096),
        ]
        for s in samples:
            comp = lz4_compress(s)
            ref_comp = _lz4_compress_py_ref(s)
            self.assertEqual(comp, ref_comp, f"LZ4 native/Python parity mismatch for len={len(s)}")
            self.assertEqual(lz4_decompress(comp), s)

        with self.assertRaises(ValueError):
            lz4_decompress(b"\x10\x00\x00\x00\x01\xFF")  # corrupt truncated stream

        # 2) batch_chacha20_xor differential check against individual chacha20_xor calls
        key = hashlib.sha256(b"v9-batch-test").digest()
        nonce8 = b"\x01\x02\x03\x04\x05\x06\x07\x08"
        base_val = int.from_bytes(nonce8, "big")
        pkt_len = 512
        n_pkts = 16
        plain_slab = os.urandom(pkt_len * n_pkts)
        work = bytearray(plain_slab)
        batch_chacha20_xor(work, pkt_len, n_pkts, key, nonce8)
        for i in range(n_pkts):
            n12 = b"PH9N" + ((base_val + i) & 0xFFFFFFFFFFFFFFFF).to_bytes(8, "big")
            exp = chacha20_xor(plain_slab[i * pkt_len : (i + 1) * pkt_len], key, n12, counter=1)
            self.assertEqual(bytes(work[i * pkt_len : (i + 1) * pkt_len]), exp)
        batch_chacha20_xor(work, pkt_len, n_pkts, key, nonce8)
        self.assertEqual(bytes(work), plain_slab)

        # 3) simd_search_count overlapping + AVX2 32-byte boundary offsets
        hay = b"aaaa" + b"_" * 29 + b"NEEDLE_AT_BOUNDARY" + b"_" * 40 + b"NEEDLE_END"
        cnt_aa, off_aa = simd_search_count(hay, b"aa", max_matches=10)
        self.assertEqual(cnt_aa, 3)
        self.assertEqual(off_aa, [0, 1, 2])
        cnt_nd, off_nd = simd_search_count(hay, b"NEEDLE", max_matches=10)
        self.assertEqual(cnt_nd, 2)
        self.assertEqual(hay[off_nd[0] : off_nd[0] + 6], b"NEEDLE")
        self.assertEqual(hay[off_nd[1] : off_nd[1] + 6], b"NEEDLE")

        # 4) tile_diff_xor + tile_apply_xor clean, dirty & tail non-32-aligned tiles
        prev = os.urandom(10 * 500)
        curr = bytearray(prev)
        curr[2 * 500 + 10 : 2 * 500 + 50] = b"DIRTY_TILE_TWO_" * 2 + b"0123456789"
        curr[9 * 500 : 9 * 500 + 20] = b"DIRTY_TILE_NINE_____"
        mask, delta = tile_diff_xor(prev, curr, 10, 500)
        self.assertEqual(list(mask), [0, 0, 1, 0, 0, 0, 0, 0, 0, 1])
        self.assertEqual(len(delta), 2 * 500)
        self.assertEqual(tile_apply_xor(prev, mask, delta, 500), bytes(curr))

    def test_phantom_ph9n_fast_path_interop_and_tamper_rejection(self) -> None:
        key = os.urandom(32)
        nonce = (1 << 63 | 123).to_bytes(8, "big")
        compressible = b"PHANTOM_V9_FAST_WIRE_" * 25
        incompressible = os.urandom(300)

        w9_comp = seal_packet_fast(key, 888, nonce, compressible, compress=True)
        self.assertEqual(w9_comp[:4], b"PH9N")
        self.assertLess(len(w9_comp), len(compressible))
        dec9 = open_packet_fast(key, w9_comp)
        self.assertIsNotNone(dec9)
        self.assertEqual(dec9, (888, nonce, compressible))

        # Random data skips LZ4 inflation automatically while keeping exact round-trip
        w9_raw = seal_packet_fast(key, 888, nonce, incompressible, compress=True)
        self.assertEqual(open_any_packet(key, w9_raw), (888, nonce, incompressible))

        # 1-bit tamper rejection on PH9N
        bad9 = bytearray(w9_comp)
        bad9[-1] ^= 0x01
        self.assertIsNone(open_packet_fast(key, bytes(bad9)))
        self.assertIsNone(open_any_packet(key, bytes(bad9)))

        # Legacy PH5E interoperability via open_any_packet
        w5 = seal_packet(key, 555, nonce, b"legacy-ph5e")
        self.assertEqual(open_any_packet(key, w5), (555, nonce, b"legacy-ph5e"))
        self.assertEqual(open_packet(key, w5), (555, nonce, b"legacy-ph5e"))

    def test_v9_idea1_dataplane_and_idea4_multiwan_speed_fusion(self) -> None:
        r1 = NativeDataPlaneEngine.run_benchmark()
        self.assertTrue(r1["ok"], r1)
        self.assertGreaterEqual(r1["speedup_x"], 3.0)
        self.assertTrue(r1["tamper_rejected"])

        r4 = MultiWanSpeedFusionEngine.run_benchmark()
        self.assertTrue(r4["ok"], r4)
        self.assertGreaterEqual(r4["fusion_speedup_x"], 1.5)
        self.assertGreaterEqual(r4["anti_loss_speedup_x"], 1.8)
        self.assertTrue(r4["midstream_cut_ok"])

    def test_v9_idea2_nvme_fabric_and_idea3_unified_hardware_grid(self) -> None:
        r2 = VirtualNvmeFabric.run_benchmark()
        self.assertTrue(r2["ok"], r2)
        self.assertLess(r2["stat_mean_us"], 100.0)
        self.assertGreaterEqual(r2["random_seek_wire_saved_pct"], 96.0)
        self.assertGreaterEqual(r2["prefetch_hit_rate_pct"], 60.0)
        self.assertLess(r2["writeback_mean_ms"], 2.0)
        self.assertGreaterEqual(r2["delta_wire_saved_pct"], 90.0)

        r3 = UnifiedHardwareGrid.run_benchmark()
        self.assertTrue(r3["ok"], r3)
        self.assertTrue(r3["grid_exact"])
        self.assertTrue(r3["handoff_exact"])
        if r3.get("oversubscribed_host"):
            self.assertGreaterEqual(r3.get("worker_threads_used", 0), 2)
        else:
            min_grid_sp = 1.5 if int(r3["accelerators"].get("cpu_threads", 4)) > 4 else 1.2
            self.assertGreaterEqual(r3["grid_speedup_x"], min_grid_sp)

    def test_v9_idea5_app_stream_hub_and_idea6_live_indexer_cas(self) -> None:
        r5 = RemoteAppStreamEngine.run_benchmark()
        self.assertTrue(r5["ok"], r5)
        if r5.get("oversubscribed_host"):
            self.assertGreaterEqual(r5.get("cpu_fps", 0.0), 60.0)
        else:
            self.assertGreaterEqual(r5["pipeline_fps"], 60.0)
        self.assertTrue(r5["exact_lossless"])
        self.assertGreaterEqual(r5["wire_saved_pct"], 90.0)
        self.assertEqual(r5["uep_15pct_loss_text_recovery_pct"], 100.0)

        r6 = LiveClusterIndexer.run_benchmark()
        self.assertTrue(r6["ok"], r6)
        self.assertLess(r6["mean_query_ms"], 5.0)
        self.assertEqual(r6["recall_pct"], 100.0)

        rcas = SharedCasTurboCache.run_benchmark()
        self.assertTrue(rcas["ok"], rcas)
        self.assertLess(rcas["hit_mean_ms"], 1.0)

    def test_v9_full_benchmark_dashboard_api_containment_and_zero_weight(self) -> None:
        full = run_hyperdrive_benchmark()
        self.assertTrue(full["ok"], full)
        self.assertEqual(full["ideas_verified"], 6)
        self.assertEqual(full["ideas_total"], 6)
        self.assertIn("CHIMERA-HYPER v9.0.0", format_hyperdrive_markdown(full))

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            work = root / "work"
            work.mkdir()
            (work / "sample.py").write_bytes(b"def hyperdrive_marker_fn():\n    return 'V9_FOUND'\n")
            (root / "secret_outside.txt").write_bytes(b"OUTSIDE_SECRET_DO_NOT_READ\n")

            cfg = OpsConfig(
                role="server",
                node_name="hyperdrive_unit",
                dashboard_bind="127.0.0.1:0",
                beam_port=0,
                rpc_v4_port=0,
                rpc_v6_port=-1,
                query_port=0,
                warp_port=-1,
                edge_proxy_port=-1,
                allowed_query_roots=[str(work)],
                search_roots=[str(work)],
                edge_targets={},
                phantom_enabled=False,
            )
            daemon = ChimeraDaemon(config=cfg, ops_dir=root / "ops", auto_seed_on_empty=False).start()
            base = f"http://127.0.0.1:{daemon.http_addr[1]}"
            try:
                h = json.loads(urllib.request.urlopen(f"{base}/api/health", timeout=4.0).read().decode())
                self.assertEqual(h["version"], __version__)
                self.assertEqual(h["api_version"], "12.0.0")

                st = json.loads(urllib.request.urlopen(f"{base}/api/hyperdrive/status", timeout=4.0).read().decode())
                self.assertTrue(st["ok"])
                self.assertEqual(st["version"], h["api_version"])

                srch = json.loads(urllib.request.urlopen(f"{base}/api/hyperdrive/search?q=hyperdrive_marker_fn", timeout=4.0).read().decode())
                self.assertTrue(srch["ok"])
                self.assertGreaterEqual(srch["total_matches"], 1)

                meta = json.loads(urllib.request.urlopen(f"{base}/api/hyperdrive/nvme-meta", timeout=4.0).read().decode())
                self.assertTrue(meta["ok"])
                self.assertGreaterEqual(meta["count"], 1)

                blk = json.loads(
                    urllib.request.urlopen(
                        f"{base}/api/hyperdrive/nvme-block?path={urllib.parse.quote(str(work / 'sample.py'))}&offset=0&length=16",
                        timeout=4.0,
                    ).read().decode()
                )
                self.assertTrue(blk["ok"])
                self.assertEqual(base64.b64decode(blk["data_b64"]), b"def hyperdrive_m")

                # Path traversal outside allowed_query_roots MUST be blocked (HTTP 403)
                with self.assertRaises(urllib.error.HTTPError) as ctx_403:
                    urllib.request.urlopen(
                        f"{base}/api/hyperdrive/nvme-block?path={urllib.parse.quote(str(root / 'secret_outside.txt'))}",
                        timeout=4.0,
                    )
                self.assertEqual(ctx_403.exception.code, 403)

                # Whitelisted kernel execution + unknown kernel rejection (HTTP 400)
                req_g = urllib.request.Request(
                    f"{base}/api/hyperdrive/grid-exec",
                    data=json.dumps({"kernel": "blake2b_rounds", "start_step": 0, "end_step": 2}).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                res_g = json.loads(urllib.request.urlopen(req_g, timeout=4.0).read().decode())
                self.assertTrue(res_g["ok"])

                req_bad_k = urllib.request.Request(
                    f"{base}/api/hyperdrive/grid-exec",
                    data=json.dumps({"kernel": "os_system_evil"}).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with self.assertRaises(urllib.error.HTTPError) as ctx_400:
                    urllib.request.urlopen(req_bad_k, timeout=4.0)
                self.assertEqual(ctx_400.exception.code, 400)

                # CAS + Hub round-trip
                blob = b"CAS_HYPERDRIVE_LAYER_" * 12
                req_cas = urllib.request.Request(
                    f"{base}/api/hyperdrive/cas",
                    data=json.dumps({"data_b64": base64.b64encode(blob).decode()}).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                rc = json.loads(urllib.request.urlopen(req_cas, timeout=4.0).read().decode())
                got_c = json.loads(urllib.request.urlopen(f"{base}/api/hyperdrive/cas?key={rc['key']}", timeout=4.0).read().decode())
                self.assertEqual(base64.b64decode(got_c["data_b64"]), blob)

                req_hub = urllib.request.Request(
                    f"{base}/api/hyperdrive/hub",
                    data=json.dumps({"kind": "clipboard", "title": "t1", "text": "hello-v9-hub"}).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                urllib.request.urlopen(req_hub, timeout=4.0).read()
                hub_l = json.loads(urllib.request.urlopen(f"{base}/api/hyperdrive/hub", timeout=4.0).read().decode())
                self.assertEqual(hub_l["items"][0]["text"], "hello-v9-hub")

                # Live benchmark endpoint
                req_b = urllib.request.Request(
                    f"{base}/api/hyperdrive/benchmark",
                    data=json.dumps({"local_only": True}).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                b_res = json.loads(urllib.request.urlopen(req_b, timeout=30.0).read().decode())
                self.assertTrue(b_res["ok"], b_res)
                self.assertEqual(b_res["ideas_verified"], 6)
            finally:
                daemon.close()

            # Subprocess Zero-Weight RSS check (< 80 MB)
            probe_code = (
                "import json; from pathlib import Path; "
                "from chimera_tp.autopilot import OpsConfig; "
                "from chimera_tp.dashboard import ChimeraDaemon; "
                f"cfg=OpsConfig(role='server',node_name='zw9',dashboard_bind='127.0.0.1:0',beam_port=0,rpc_v4_port=0,rpc_v6_port=-1,query_port=0,warp_port=-1,edge_proxy_port=-1,"
                f"allowed_query_roots=[{str(work)!r}],search_roots=[{str(work)!r}],phantom_enabled=False); "
                f"d=ChimeraDaemon(config=cfg,ops_dir=Path({str(root/'o2')!r}),auto_seed_on_empty=False).start(); "
                "st=d.status_payload(); d.close(); print(json.dumps(st['zero_weight']))"
            )
            proc = subprocess.run([sys.executable, "-c", probe_code], capture_output=True, text=True, check=True)
            zw = json.loads(proc.stdout.strip().splitlines()[-1])
            self.assertTrue(zw["zero_weight_ok"], f"RSS exceeded 80MB: {zw}")


if __name__ == "__main__":
    unittest.main()
