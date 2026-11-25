"""Comprehensive unit & integration tests for CHIMERA-HYPER v1.0 breakthroughs."""

from __future__ import annotations

import hashlib
import http.server
import json
import os
import random
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from pathlib import Path

from chimera_tp.active_pipe import ActivePipeEngine, ComputePlan
from chimera_tp.dna_vault import DnaCodec, DnaVault
from chimera_tp.gf256 import coeff_vector, gf_mul
from chimera_tp.hyper_wire import (
    HedgedRpcClient,
    HedgedRpcServer,
    HyperWireReceiver,
    HyperWireSender,
)
from chimera_tp.impairment import ImpairedUdpBridge
from chimera_tp.native import (
    WormholeChannel,
    cpu_caps,
    delta_decode,
    delta_encode,
    gf256_decode_matrix,
    gf256_encode_block,
    gf256_mul_add,
    gf256_scale,
    has_native,
)
from chimera_tp.warp import WarpClient, WarpServer


class TestChimeraHyperV1(unittest.TestCase):
    def test_gfni_exhaustive_65536_equivalence(self) -> None:
        self.assertTrue(has_native(), "Native Rust _chimera_core.dll must be present")
        caps = cpu_caps()
        self.assertTrue(caps["gfni"], f"Expected Intel GFNI enabled on host, got {caps}")

        # 1) Exhaustive all 256 x 256 byte products (includes leading & embedded 0x00 bytes)
        src = bytes(range(256))
        for a in range(256):
            scaled = gf256_scale(src, a)
            expected = bytes(gf_mul(a, b) for b in range(256))
            self.assertEqual(scaled, expected, f"Mismatch at scalar a={a}")

        # Verify large buffer GFNI mul_add containing embedded NUL bytes
        dst = bytearray(b"\x00\xAA\x55\x00" * 1024)
        rhs = b"\x00\x01\x03\xFF" * 1024
        orig_dst = bytes(dst)
        gf256_mul_add(dst, rhs, 0x57)
        for i in range(64):
            self.assertEqual(dst[i], orig_dst[i] ^ gf_mul(0x57, rhs[i]))

        # 2) Full 32 x 1360 GFNI RLNC encode & matrix solve with 50% erasures replaced by FEC
        k = 32
        blk_len = 1360
        blocks = [os.urandom(blk_len) for _ in range(k)]
        flat = b"".join(blocks)
        seed = b"gfni-matrix-test"

        coeffs_rows = bytearray()
        coded_rows = bytearray()
        # Keep 16 even systematic blocks + generate 16 coded GFNI blocks
        for i in range(0, k, 2):
            row = bytearray(k)
            row[i] = 1
            coeffs_rows.extend(row)
            coded_rows.extend(blocks[i])
        for fid in range(1, 17):
            c = bytes(coeff_vector(seed, fid, k))
            coeffs_rows.extend(c)
            coded_rows.extend(gf256_encode_block(flat, c, k, blk_len))

        recovered = gf256_decode_matrix(coded_rows, coeffs_rows, k, blk_len)
        self.assertEqual(recovered, flat)

    def test_fastcdc_and_delta_roundtrip_and_dedup(self) -> None:
        # Verify low-level delta roundtrip with insertion + modification
        base = (b"HEADER-BLOCK-1234567890|" + os.urandom(200)) * 80
        edited_base = b"PREPEND-17-BYTES!" + base[:8000] + b"---PATCHED-SLICE---" + base[8019:]
        patch = delta_encode(base, edited_base)
        self.assertIsNotNone(patch)
        self.assertEqual(delta_decode(base, patch, len(edited_base)), edited_base)

        # Verify 4 MiB DnaCodec incremental sync (insert at byte 0 + ~3% scattered edits)
        rng = random.Random(42)
        chunk_templates = [
            f"RECORD-{i:05d}|DATA={rng.randbytes(48).hex()}|TAIL=XYZ\n".encode("ascii")
            for i in range(512)
        ]
        corpus_v1 = b"".join(chunk_templates[i % len(chunk_templates)] for i in range(52000))[: 4 * 1024 * 1024]

        tx_vault = DnaVault()
        rx_vault = DnaVault()
        codec = DnaCodec()

        # Sync #1 (cold vault)
        recipe1, stats1 = codec.encode_stream(corpus_v1, rx_vault.known_cids(), {}, tx_vault)
        rec1, _ = codec.decode_stream(recipe1, rx_vault)
        self.assertEqual(rec1, corpus_v1)

        # Build v2: insert 19 bytes at byte 0 + modify ~2.5% of chunks near end & middle
        corpus_v2 = bytearray(b"INSERTED-AT-OFFSET0" + corpus_v1)
        patch_offsets = [len(corpus_v2) // 3, (2 * len(corpus_v2)) // 3]
        for off in patch_offsets:
            corpus_v2[off : off + 4096] = rng.randbytes(4096)
        v2_bytes = bytes(corpus_v2)

        rx_cids, rx_sf = DnaVault.import_sketch(rx_vault.export_sketch())
        recipe2, stats2 = codec.encode_stream(v2_bytes, rx_cids, rx_sf, tx_vault)
        rec2, _ = codec.decode_stream(recipe2, rx_vault)
        self.assertEqual(rec2, v2_bytes)
        self.assertGreater(stats2.ref_hits + stats2.delta_hits, 0)
        self.assertGreater(stats2.reduction_pct, 90.0, f"Expected >90% dedup savings, got {stats2}")

    def test_wormhole_shared_memory_two_processes_32mb(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            src = tmp_dir / "src_32m.bin"
            dst = tmp_dir / "dst_32m.bin"
            payload = (b"WORMHOLE-BLOCK-00\x00\xFF" + os.urandom(4077)) * 8040
            payload = payload[: 32 * 1024 * 1024]
            src.write_bytes(payload)
            expected_sha = hashlib.sha256(payload).hexdigest()

            wh_name = f"TEST_WH_{os.getpid()}_{time.monotonic_ns()}"
            repo_root = str(Path(__file__).resolve().parents[1])

            writer_code = (
                "import sys; from pathlib import Path; "
                "from chimera_tp.native import WormholeChannel; "
                "data = Path(sys.argv[2]).read_bytes(); "
                "wh = WormholeChannel.create(sys.argv[1], capacity_mb=8); "
                "wh.write_all(data, timeout_ms=15000); "
                "wh.mark_eof(); "
                "import time; time.sleep(0.2); wh.close()"
            )
            reader_code = (
                "import sys; from pathlib import Path; "
                "from chimera_tp.native import WormholeChannel; "
                "wh = WormholeChannel.open(sys.argv[1], wait_timeout_s=10.0); "
                "data = wh.read_all(timeout_ms=15000); "
                "wh.close(); "
                "Path(sys.argv[2]).write_bytes(data)"
            )

            p_w = subprocess.Popen(
                [sys.executable, "-c", writer_code, wh_name, str(src)],
                cwd=repo_root,
            )
            p_r = subprocess.Popen(
                [sys.executable, "-c", reader_code, wh_name, str(dst)],
                cwd=repo_root,
            )
            try:
                rc_w = p_w.wait(timeout=20)
                rc_r = p_r.wait(timeout=20)
                self.assertEqual(rc_w, 0)
                self.assertEqual(rc_r, 0)
                self.assertEqual(dst.stat().st_size, len(payload))
                self.assertEqual(hashlib.sha256(dst.read_bytes()).hexdigest(), expected_sha)
            finally:
                for p in (p_w, p_r):
                    if p.poll() is None:
                        p.kill()

    def test_hyper_wire_zero_bloat_and_lossy_gfni_recovery(self) -> None:
        # 1) Clean 0% loss -> 0 FEC repair packets
        rx = HyperWireReceiver().start()
        try:
            clean_data = os.urandom(256 * 1024)
            sender = HyperWireSender(rx.addr, initial_loss_hint=0.0)
            rep_clean = sender.send_stream(clean_data, stream_id=1)
            rec_clean, solves_clean = rx.wait_stream(1, timeout_s=10.0)
            self.assertTrue(rep_clean.sha256_match)
            self.assertEqual(rep_clean.fec_packets_sent, 0)
            self.assertEqual(solves_clean, 0)
            self.assertLess(rep_clean.wire_overhead_pct, 3.0)
            self.assertEqual(rec_clean, clean_data)
        finally:
            rx.close()

        # 2) Lossy 10% bridge + Priority-0 frame early arrival + GFNI solves
        prio_hits: list[bytes] = []
        rx_lossy = HyperWireReceiver(on_priority_frame=lambda b, _t: prio_hits.append(b)).start()
        bridge = ImpairedUdpBridge(
            target_b=rx_lossy.addr,
            bandwidth_mbps=150.0,
            one_way_delay_ms=10.0,
            loss_rate=0.10,
            seed=999,
        ).start()
        try:
            lossy_data = os.urandom(512 * 1024)
            sender = HyperWireSender(bridge.a_addr, initial_loss_hint=0.10)
            rep = sender.send_stream(
                lossy_data,
                stream_id=7,
                priority_frame=b'{"urgent":"preview-0"}',
                timeout_s=15.0,
            )
            rec, gfni_solves = rx_lossy.wait_stream(7, timeout_s=15.0)
            self.assertTrue(rep.sha256_match)
            self.assertEqual(hashlib.sha256(rec).hexdigest(), hashlib.sha256(lossy_data).hexdigest())
            self.assertGreater(gfni_solves, 0)
            self.assertEqual(prio_hits, [b'{"urgent":"preview-0"}'])
        finally:
            bridge.close()
            rx_lossy.close()

    def test_hedged_multipath_racing_reduces_tail_latency(self) -> None:
        srv = HedgedRpcServer(
            [("127.0.0.1", 0), ("127.0.0.1", 0)],
            handler=lambda req: b"OK:" + req[:16],
        ).start()
        # Path 0 has heavy jitter + loss; Path 1 is independent impaired path
        b0 = ImpairedUdpBridge(
            srv.addrs[0], bandwidth_mbps=100.0, one_way_delay_ms=15.0, jitter_ms=45.0, loss_rate=0.12, seed=101
        ).start()
        b1 = ImpairedUdpBridge(
            srv.addrs[1], bandwidth_mbps=100.0, one_way_delay_ms=15.0, jitter_ms=10.0, loss_rate=0.08, seed=202
        ).start()
        try:
            single_cli = HedgedRpcClient([b0.a_addr], hedge_delay_ms=0.0, retry_after_ms=95.0)
            single_lats = [single_cli.call(f"req-{i}".encode())[1] for i in range(25)]
            single_cli.close()

            hedged_cli = HedgedRpcClient([b0.a_addr, b1.a_addr], hedge_delay_ms=0.0, retry_after_ms=95.0)
            hedged_lats = [hedged_cli.call(f"req-{i}".encode())[1] for i in range(25)]
            hedged_cli.close()

            single_p95 = sorted(single_lats)[int(0.92 * len(single_lats))]
            hedged_p95 = sorted(hedged_lats)[int(0.92 * len(hedged_lats))]
            self.assertLess(hedged_p95, single_p95)
        finally:
            b0.close()
            b1.close()
            srv.close()

    def test_active_compute_in_transit_operators(self) -> None:
        # 1) Rust filter_lines
        lines = []
        for i in range(4000):
            tag = "CRITICAL_ERROR" if i % 100 == 0 else "INFO_HEARTBEAT"
            lines.append(f"2026-11-25T11:00:00Z [{tag}] seq={i} payload=abcdef0123456789\n")
        raw_logs = "".join(lines).encode("utf-8")

        engine = ActivePipeEngine()
        res1 = engine.run_query(
            raw_logs,
            ComputePlan(op="filter_lines", needle="CRITICAL_ERROR", placement="auto"),
        )
        self.assertEqual(res1.executed_at, "sender")
        self.assertEqual(res1.matched_records, 40)
        self.assertGreater(res1.wire_reduction_pct, 95.0)
        self.assertIsNotNone(res1.preview_first_ms)

        # 2) json_filter_project
        ndjson = "\n".join(
            json.dumps({"id": i, "level": "err" if i % 50 == 0 else "ok", "msg": f"m{i}", "blob": "X" * 120})
            for i in range(1000)
        ).encode("utf-8")
        res2 = engine.run_query(
            ndjson,
            ComputePlan(op="json_filter_project", where_key="level", where_eq="err", project_fields=("id", "msg")),
        )
        self.assertEqual(res2.matched_records, 20)
        self.assertGreater(res2.wire_reduction_pct, 90.0)

        # 3) csv_group_sum
        csv_lines = ["dept,amount"] + [f"ENG,{i%10 + 1}" for i in range(500)] + [f"OPS,{i%5 + 2}" for i in range(500)]
        res3 = engine.run_query("\n".join(csv_lines).encode("utf-8"), ComputePlan(op="csv_group_sum"))
        agg = json.loads(res3.output_bytes.decode("utf-8"))
        self.assertEqual(agg["ENG"]["count"], 500)
        self.assertEqual(agg["OPS"]["count"], 500)

    def test_warp_live_http_over_impaired_lossy_link(self) -> None:
        blob = (b"WARP-HTTP-BODY-" + os.urandom(64)) * 3200
        blob = blob[: 256 * 1024]
        expected_sha = hashlib.sha256(blob).hexdigest()

        class BlobHandler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(len(blob)))
                self.end_headers()
                self.wfile.write(blob)

            def log_message(self, *_args: object) -> None:
                pass

        httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), BlobHandler)
        http_port = httpd.server_address[1]
        http_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        http_thread.start()

        warp_srv = WarpServer(("127.0.0.1", 0), ("127.0.0.1", http_port), est_loss=0.05).start()
        bridge = ImpairedUdpBridge(
            target_b=warp_srv.udp_addr,
            bandwidth_mbps=100.0,
            one_way_delay_ms=15.0,
            loss_rate=0.05,
            seed=777,
        ).start()
        warp_cli = WarpClient(("127.0.0.1", 0), bridge.a_addr, est_loss=0.05).start()

        try:
            url = f"http://127.0.0.1:{warp_cli.listen_addr[1]}/payload.bin"
            with urllib.request.urlopen(url, timeout=15.0) as resp:
                got = resp.read()
            self.assertEqual(len(got), len(blob))
            self.assertEqual(hashlib.sha256(got).hexdigest(), expected_sha)
        finally:
            warp_cli.close()
            bridge.close()
            warp_srv.close()
            httpd.shutdown()
            httpd.server_close()

    def test_beam_cli_two_process_directory_sync(self) -> None:
        repo_root = str(Path(__file__).resolve().parents[1])
        with tempfile.TemporaryDirectory() as tmp:
            tdir = Path(tmp)
            src_dir = tdir / "project_src"
            out_dir = tdir / "project_out"
            tx_vault = tdir / "tx_vault"
            rx_vault = tdir / "rx_vault"
            port_file = tdir / "beam_port.json"
            src_dir.mkdir(parents=True, exist_ok=True)

            # Create 15 files (~1.5 MiB total)
            for i in range(15):
                content = (f"FILE-{i:02d}|CAD-LAYER=WALLS|SEQ=" + os.urandom(32).hex() + "\n") * 1050
                (src_dir / f"module_{i:02d}.dat").write_text(content, encoding="utf-8")

            srv_proc = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "chimera_tp",
                    "beam",
                    "serve",
                    "--bind",
                    "127.0.0.1:0",
                    "--port-file",
                    str(port_file),
                    "--vault",
                    str(rx_vault),
                    "--out-dir",
                    str(out_dir),
                    "--max-transfers",
                    "2",
                    "--timeout",
                    "25",
                ],
                cwd=repo_root,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                # 1) Cold directory sync
                send1 = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "chimera_tp",
                        "beam",
                        "send",
                        "--target",
                        f"@{port_file}",
                        "--dir",
                        str(src_dir),
                        "--vault",
                        str(tx_vault),
                    ],
                    cwd=repo_root,
                    capture_output=True,
                    text=True,
                    timeout=25,
                    check=False,
                )
                self.assertEqual(send1.returncode, 0, msg=send1.stderr or send1.stdout)
                for p in src_dir.glob("*"):
                    self.assertEqual((out_dir / p.name).read_bytes(), p.read_bytes())

                # 2) Edit 1 file by prepending + modifying, re-sync with persistent DNA vaults
                edited_p = src_dir / "module_03.dat"
                edited_p.write_bytes(b"// EDITED-AT-HEAD\n" + edited_p.read_bytes()[:40000] + b"// MID-PATCH\n" + edited_p.read_bytes()[40012:])

                send2 = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "chimera_tp",
                        "beam",
                        "send",
                        "--target",
                        f"@{port_file}",
                        "--dir",
                        str(src_dir),
                        "--vault",
                        str(tx_vault),
                    ],
                    cwd=repo_root,
                    capture_output=True,
                    text=True,
                    timeout=25,
                    check=False,
                )
                self.assertEqual(send2.returncode, 0, msg=send2.stderr or send2.stdout)
                rep2 = json.loads(send2.stdout)
                self.assertGreater(rep2["reduction_pct"], 90.0)
                for p in src_dir.glob("*"):
                    self.assertEqual((out_dir / p.name).read_bytes(), p.read_bytes())

                srv_out, srv_err = srv_proc.communicate(timeout=20)
                self.assertEqual(srv_proc.returncode, 0, msg=srv_err or srv_out)
            finally:
                if srv_proc.poll() is None:
                    srv_proc.kill()
                for pipe in (srv_proc.stdout, srv_proc.stderr):
                    if pipe is not None:
                        pipe.close()


if __name__ == "__main__":
    unittest.main()
