"""CHIMERA-HYPER v1.0 Real-Work Before-vs-After Benchmark & Proof Suite."""

from __future__ import annotations

import hashlib
import json
import os
import random
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from chimera_tp.active_pipe import ActivePipeEngine, ComputePlan
from chimera_tp.dna_vault import DnaCodec, DnaVault
from chimera_tp.gf256 import RLNCDecoder, RLNCEncoder, coeff_vector, scale_bytes, xor_bytes
from chimera_tp.hyper_wire import (
    HedgedRpcClient,
    HedgedRpcServer,
    HyperWireReceiver,
    HyperWireSender,
)
from chimera_tp.impairment import (
    ImpairedUdpBridge,
    WinTimerScope,
    transfer_tcp_cubic_over_udp,
)
from chimera_tp.native import (
    WormholeChannel,
    cpu_caps,
    gf256_decode_matrix,
    gf256_encode_block,
    gf256_mul_add,
    has_native,
)


def _configure_utf8() -> None:
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            try:
                s.reconfigure(encoding="utf-8", errors="replace")
            except OSError:
                pass


def _make_realistic_corpus(size_bytes: int, seed: int = 2026) -> bytes:
    """Fast builder (~0.2s for 30 MB) simulating structured engineering/JSON/project payloads."""
    rng = random.Random(seed)
    templates = [
        (
            f'{{"ts":"2026-11-25T11:00:{i%60:02d}Z","layer":"STRUCT-A{i%12}",'
            f'"node":"E{i%500:04d}","vec":[{i%97},{i%53},1024],"hash":"{rng.randbytes(12).hex()}"}}\n'
        ).encode("ascii")
        for i in range(600)
    ]
    block_1m = bytearray()
    idx = 0
    while len(block_1m) < 1024 * 1024:
        block_1m.extend(templates[idx % len(templates)])
        idx += 1
    out = bytearray()
    mb_block = bytes(block_1m[: 1024 * 1024])
    for m in range((size_bytes // (1024 * 1024)) + 1):
        # Mix deterministic per-MB variation tag so blocks across 30 MB remain unique DNA chunks
        tag = f"/*MB={m:03d}*/\n".encode("ascii")
        out.extend(tag)
        out.extend(mb_block[len(tag) :])
    return bytes(out[:size_bytes])


def _bench_tcp_loopback(payload: bytes, recv_chunk: int = 65536) -> dict[str, Any]:
    """Measure real OS TCP loopback transfer speed."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]

    total = len(payload)
    rx_bytes = [0]
    rx_hasher = hashlib.sha256()

    def srv_fn() -> None:
        conn, _ = srv.accept()
        with conn:
            while True:
                buf = conn.recv(recv_chunk)
                if not buf:
                    break
                rx_bytes[0] += len(buf)
                rx_hasher.update(buf)

    th = threading.Thread(target=srv_fn, daemon=True)
    th.start()

    cli = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    t0 = time.perf_counter()
    try:
        cli.connect(("127.0.0.1", port))
        cli.sendall(payload)
        cli.shutdown(socket.SHUT_WR)
        th.join(timeout=30.0)
    finally:
        cli.close()
        srv.close()

    ms = (time.perf_counter() - t0) * 1000.0
    ok = rx_bytes[0] == total and rx_hasher.hexdigest() == hashlib.sha256(payload).hexdigest()
    mbps = (total * 8.0) / max(ms * 1000.0, 0.001)
    return {
        "bytes": total,
        "elapsed_ms": round(ms, 2),
        "mbps": round(mbps, 2),
        "gbps": round(mbps / 1000.0, 3),
        "sha256_match": ok,
    }


def _bench_tcp_over_paced_link(
    payload: bytes, bandwidth_mbps: float = 100.0, one_way_delay_ms: float = 5.0
) -> dict[str, Any]:
    """Real OS TCP socket throttled symmetrically across a real `bandwidth_mbps` pipe + RTT."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    srv_port = srv.getsockname()[1]

    rx_hash = hashlib.sha256()
    rx_len = [0]

    def srv_fn() -> None:
        conn, _ = srv.accept()
        with conn:
            while True:
                buf = conn.recv(65536)
                if not buf:
                    break
                rx_len[0] += len(buf)
                rx_hash.update(buf)

    th = threading.Thread(target=srv_fn, daemon=True)
    th.start()

    cli = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    t0 = time.perf_counter()
    with WinTimerScope():
        try:
            cli.connect(("127.0.0.1", srv_port))
            if one_way_delay_ms > 0:
                time.sleep(one_way_delay_ms * 2.0 / 1000.0)
            mv = memoryview(payload)
            tx_clock = time.perf_counter()
            step = 16384
            for off in range(0, len(payload), step):
                chunk = mv[off : off + step]
                cli.sendall(chunk)
                ser_s = (len(chunk) * 8.0) / (bandwidth_mbps * 1_000_000.0)
                tx_clock = max(tx_clock + ser_s, time.perf_counter())
                gap = tx_clock - time.perf_counter()
                if gap > 0.002:
                    time.sleep(0.001)
            cli.shutdown(socket.SHUT_WR)
            th.join(timeout=30.0)
        finally:
            cli.close()
            srv.close()

    ms = (time.perf_counter() - t0) * 1000.0
    ok = rx_len[0] == len(payload) and rx_hash.hexdigest() == hashlib.sha256(payload).hexdigest()
    mbps = (len(payload) * 8.0) / max(ms * 1000.0, 0.001)
    return {
        "bytes": len(payload),
        "elapsed_ms": round(ms, 2),
        "mbps": round(mbps, 2),
        "sha256_match": ok,
    }


def suite_0_silicon_core() -> dict[str, Any]:
    print("\n=== SUITE 0: SILICON CORE (Python GF(256) vs Rust Intel GFNI VGF2P8MULB) ===")
    caps = cpu_caps()
    n = 16 * 1024 * 1024  # 16 MiB
    src = os.urandom(n)
    dst_py_base = os.urandom(n)

    t0 = time.perf_counter()
    _ = xor_bytes(dst_py_base, scale_bytes(src, 0xA3))
    py_vec_ms = (time.perf_counter() - t0) * 1000.0
    py_vec_mbps = (n * 8.0) / max(py_vec_ms * 1000.0, 0.001)

    dst_rs = bytearray(dst_py_base)
    t1 = time.perf_counter()
    gf256_mul_add(dst_rs, src, 0xA3)
    rs_vec_ms = (time.perf_counter() - t1) * 1000.0
    rs_vec_mbps = (n * 8.0) / max(rs_vec_ms * 1000.0, 0.001)

    # Full 32 x 1360 RLNC Matrix Solve (43.5 KiB generation)
    k, bl = 32, 1360
    blocks = [os.urandom(bl) for _ in range(k)]
    flat = b"".join(blocks)
    seed = b"bench-mat-seed00"

    t2 = time.perf_counter()
    enc_py = RLNCEncoder(blocks, seed)
    dec_py = RLNCDecoder(k=k, block_size=bl, seed=seed)
    for did in range(k):
        dec_py.add_droplet(enc_py.generate_droplet(did))
    _ = dec_py.solve()
    py_mat_ms = (time.perf_counter() - t2) * 1000.0

    # Equivalent full 32x32 GFNI coded generation encode + Gauss-Jordan solve
    t3 = time.perf_counter()
    coeffs_all = b"".join(bytes(coeff_vector(seed, did, k)) for did in range(k))
    coded_all = b"".join(
        gf256_encode_block(flat, coeffs_all[r * k : (r + 1) * k], k, bl) for r in range(k)
    )
    rec_rs = gf256_decode_matrix(coded_all, coeffs_all, k, bl)
    rs_mat_ms = (time.perf_counter() - t3) * 1000.0
    assert rec_rs == flat

    vec_speedup = py_vec_ms / max(rs_vec_ms, 0.001)
    mat_speedup = py_mat_ms / max(rs_mat_ms, 0.001)
    print(
        f"  16 MiB GF(256) mul_add | Python: {py_vec_ms:6.2f}ms ({py_vec_mbps:6.1f} Mbps) "
        f"| Rust GFNI: {rs_vec_ms:6.2f}ms ({rs_vec_mbps:7.1f} Mbps) -> {vec_speedup:.1f}x"
    )
    print(
        f"  32x1360 RLNC Codec+Inv | Python: {py_mat_ms:6.2f}ms "
        f"| Rust GFNI: {rs_mat_ms:6.2f}ms -> {mat_speedup:.1f}x"
    )
    return {
        "cpu_caps": caps,
        "vector_16mib": {
            "python_ms": round(py_vec_ms, 3),
            "python_mbps": round(py_vec_mbps, 2),
            "rust_gfni_ms": round(rs_vec_ms, 3),
            "rust_gfni_mbps": round(rs_vec_mbps, 2),
            "speedup": round(vec_speedup, 2),
        },
        "matrix_32x1360": {
            "python_ms": round(py_mat_ms, 3),
            "rust_gfni_ms": round(rs_mat_ms, 3),
            "speedup": round(mat_speedup, 2),
        },
    }


def suite_1_dna_beam() -> dict[str, Any]:
    print("\n=== SUITE 1: 30 MB INCREMENTAL SYNC (3% edited @ 100 Mbps, 10 ms RTT) ===")
    size_30m = 30 * 1024 * 1024
    v1 = _make_realistic_corpus(size_30m, seed=20261)

    # Mutate 3% (insert 23 bytes at byte 0 + overwrite scattered ~900 KB spans)
    v2_buf = bytearray(b"/*VERSION-2-HEADER-23*/" + v1)
    rng = random.Random(77)
    for m in [3, 9, 15, 21, 27]:
        off = m * 1024 * 1024
        v2_buf[off : off + 180 * 1024] = _make_realistic_corpus(180 * 1024, seed=500 + m)
    v2 = bytes(v2_buf[:size_30m])

    # Before: Standard TCP resends all 30 MB on a 100 Mbps link
    before_tcp = _bench_tcp_over_paced_link(v2, bandwidth_mbps=100.0, one_way_delay_ms=5.0)

    # After: Warm DNA vaults + FastCDC + Odess Delta + HyperWire on the exact same 100 Mbps link
    tx_vault = DnaVault()
    rx_vault = DnaVault()
    codec = DnaCodec()
    r1, _ = codec.encode_stream(v1, rx_vault.known_cids(), {}, tx_vault)
    dec1, _ = codec.decode_stream(r1, rx_vault)
    assert dec1 == v1

    rx_wire = HyperWireReceiver().start()
    bridge = ImpairedUdpBridge(
        target_b=rx_wire.addr, bandwidth_mbps=100.0, one_way_delay_ms=5.0, loss_rate=0.0
    ).start()
    t0 = time.perf_counter()
    try:
        rx_cids, rx_sf = DnaVault.import_sketch(rx_vault.export_sketch())
        recipe, dstats = codec.encode_stream(v2, rx_cids, rx_sf, tx_vault)
        sender = HyperWireSender(bridge.a_addr, initial_loss_hint=0.0)
        wrep = sender.send_stream(recipe, stream_id=1, timeout_s=20.0)
        rec_recipe, _ = rx_wire.wait_stream(1, timeout_s=20.0)
        decoded, _ = codec.decode_stream(rec_recipe, rx_vault)
        total_ms = (time.perf_counter() - t0) * 1000.0
    finally:
        bridge.close()
        rx_wire.close()

    ok = hashlib.sha256(decoded).hexdigest() == hashlib.sha256(v2).hexdigest()
    eff_mbps = (len(v2) * 8.0) / max(total_ms * 1000.0, 0.001)
    speedup = before_tcp["elapsed_ms"] / max(total_ms, 0.001)
    print(
        f"  TCP Before   : {len(v2):>10,} B wire -> {before_tcp['elapsed_ms']:7.1f}ms ({before_tcp['mbps']:.1f} Mbps)"
    )
    print(
        f"  CHIMERA Beam : {wrep.wire_bytes_sent:>10,} B wire ({dstats.reduction_pct:.2f}% saved) "
        f"-> {total_ms:7.1f}ms (eff {eff_mbps:.1f} Mbps) -> {speedup:.1f}x FASTER!"
    )
    return {
        "raw_bytes": len(v2),
        "link_mbps": 100.0,
        "before_tcp": before_tcp,
        "after_chimera_beam": {
            "dna_recipe_bytes": len(recipe),
            "wire_bytes_sent": wrep.wire_bytes_sent,
            "wire_saved_pct": round(100.0 * (1.0 - wrep.wire_bytes_sent / len(v2)), 2),
            "ref_hits": dstats.ref_hits,
            "delta_hits": dstats.delta_hits,
            "raw_misses": dstats.raw_misses,
            "elapsed_ms": round(total_ms, 2),
            "effective_goodput_mbps": round(eff_mbps, 2),
            "sha256_match": ok,
        },
        "speedup": round(speedup, 2),
    }


def suite_2_lossy_wan_comparison() -> list[dict[str, Any]]:
    print("\n=== SUITE 2: LOSSY WAN (2 MiB @ 100 Mbps, 50 ms RTT, 0% -> 10% LOSS) ===")
    payload = os.urandom(2 * 1024 * 1024)
    results: list[dict[str, Any]] = []

    for loss in [0.0, 0.02, 0.05, 0.10]:
        # 1) TCP-CUBIC reference over ImpairedUdpBridge
        tcp_srv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        tcp_srv.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
        tcp_srv.bind(("127.0.0.1", 0))
        bridge_tcp = ImpairedUdpBridge(
            target_b=tcp_srv.getsockname(),
            bandwidth_mbps=100.0,
            one_way_delay_ms=25.0,
            loss_rate=loss,
            seed=2026 + int(loss * 100),
        ).start()
        try:
            _, tcp_rep = transfer_tcp_cubic_over_udp(
                payload, bridge_tcp, tcp_srv, mss=1360, timeout_s=30.0
            )
        finally:
            bridge_tcp.close()
            tcp_srv.close()

        # 2) CHIMERA Silicon GFNI Wire (BLIND START: initial_loss_hint=0.0!)
        rx_hw = HyperWireReceiver().start()
        bridge_hw = ImpairedUdpBridge(
            target_b=rx_hw.addr,
            bandwidth_mbps=100.0,
            one_way_delay_ms=25.0,
            loss_rate=loss,
            seed=2026 + int(loss * 100),
        ).start()
        try:
            sender = HyperWireSender(bridge_hw.a_addr, initial_loss_hint=0.0)
            hw_rep = sender.send_stream(payload, stream_id=11, timeout_s=30.0)
            rec, gfni_solves = rx_hw.wait_stream(11, timeout_s=30.0)
            hw_ok = (
                hw_rep.sha256_match
                and hashlib.sha256(rec).hexdigest() == hashlib.sha256(payload).hexdigest()
            )
        finally:
            bridge_hw.close()
            rx_hw.close()

        speedup = tcp_rep.elapsed_ms / max(hw_rep.elapsed_ms, 0.001)
        print(
            f"  loss={int(loss*100):2d}% | TCP-CUBIC: {tcp_rep.elapsed_ms:7.1f}ms "
            f"({tcp_rep.throughput_mbps:5.2f} Mbps, rtx={tcp_rep.retransmits:3d}, rto={tcp_rep.timeouts}) "
            f"| CHIMERA GFNI: {hw_rep.elapsed_ms:6.1f}ms ({hw_rep.throughput_mbps:5.2f} Mbps, "
            f"fec={hw_rep.fec_packets_sent:3d}, solves={gfni_solves:2d}) -> {speedup:.2f}x"
        )
        results.append(
            {
                "loss_rate_pct": int(loss * 100),
                "before_tcp_cubic": {
                    "elapsed_ms": tcp_rep.elapsed_ms,
                    "throughput_mbps": tcp_rep.throughput_mbps,
                    "retransmits": tcp_rep.retransmits,
                    "timeouts": tcp_rep.timeouts,
                    "congestion_events": tcp_rep.congestion_events,
                    "sha256_match": tcp_rep.sha256_match,
                },
                "after_chimera_gfni": {
                    "elapsed_ms": hw_rep.elapsed_ms,
                    "throughput_mbps": hw_rep.throughput_mbps,
                    "wire_overhead_pct": hw_rep.wire_overhead_pct,
                    "fec_packets_sent": hw_rep.fec_packets_sent,
                    "repair_retransmits": hw_rep.repair_retransmits,
                    "gfni_matrix_solves": gfni_solves,
                    "sha256_match": hw_ok,
                },
                "speedup": round(speedup, 2),
            }
        )
    return results


def suite_3_active_compute() -> dict[str, Any]:
    print("\n=== SUITE 3: ACTIVE COMPUTE-IN-TRANSIT (30 MB Logs Filter @ 100 Mbps, 1% Match) ===")
    n_lines = 290_000
    lines = []
    for i in range(n_lines):
        if i % 100 == 0:
            lines.append(f"2026-11-25T11:05:00Z ERROR auth-gateway uid={i:06d} code=E_TIMEOUT detail=deadbeef00\n")
        else:
            lines.append(f"2026-11-25T11:05:00Z INFO  telemetry-bus uid={i:06d} status=OK   pad=0123456789abcdef\n")
    raw_logs = "".join(lines).encode("ascii")

    # Before: Pull all raw bytes across 100 Mbps TCP, then filter locally
    t0 = time.perf_counter()
    tcp_res = _bench_tcp_over_paced_link(raw_logs, bandwidth_mbps=100.0, one_way_delay_ms=5.0)
    local_hits = [ln for ln in raw_logs.splitlines(keepends=True) if b"ERROR" in ln]
    before_total_ms = (time.perf_counter() - t0) * 1000.0

    # After: ActivePipeEngine over exact same 100 Mbps bridge
    rx = HyperWireReceiver().start()
    preview_at: list[float] = []
    rx._on_priority_frame = lambda _b, ts: preview_at.append(ts)
    bridge = ImpairedUdpBridge(
        target_b=rx.addr, bandwidth_mbps=100.0, one_way_delay_ms=5.0, loss_rate=0.0
    ).start()
    try:
        t_start = time.perf_counter()
        pipe_res = ActivePipeEngine().run_query(
            raw_logs,
            ComputePlan(op="filter_lines", needle="ERROR", placement="auto"),
            target_addr=bridge.a_addr,
            external_rx=rx,
            bandwidth_mbps=100.0,
        )
        preview_ms = ((preview_at[0] - t_start) * 1000.0) if preview_at else pipe_res.preview_first_ms
    finally:
        bridge.close()
        rx.close()

    assert pipe_res.matched_records == len(local_hits)
    speedup = before_total_ms / max(pipe_res.total_ms, 0.001)
    print(
        f"  TCP Download+Filter : {len(raw_logs):>10,} B wire -> {before_total_ms:7.1f}ms "
        f"(first result after {before_total_ms:7.1f}ms)"
    )
    print(
        f"  CHIMERA Active Pipe : {pipe_res.wire_bytes:>10,} B wire ({pipe_res.wire_reduction_pct:.2f}% saved) "
        f"-> {pipe_res.total_ms:7.1f}ms (P0 preview in {preview_ms:.2f}ms) -> {speedup:.1f}x FASTER!"
    )
    return {
        "raw_bytes": len(raw_logs),
        "matched_records": pipe_res.matched_records,
        "before_tcp_download_filter": {
            "wire_bytes": len(raw_logs),
            "total_ms": round(before_total_ms, 2),
            "first_result_ms": round(before_total_ms, 2),
            "sha256_match": tcp_res["sha256_match"],
        },
        "after_chimera_active_pipe": {
            "wire_bytes": pipe_res.wire_bytes,
            "wire_reduction_pct": pipe_res.wire_reduction_pct,
            "preview_first_ms": round(preview_ms, 2) if preview_ms else None,
            "total_ms": pipe_res.total_ms,
        },
        "speedup": round(speedup, 2),
    }


def suite_4_hedged_rpc() -> dict[str, Any]:
    print("\n=== SUITE 4: INTERACTIVE RPC TAIL LATENCY (80 Reqs, 50ms RTT + Jitter Spikes + 5% Loss) ===")
    srv = HedgedRpcServer(
        [("127.0.0.1", 0), ("127.0.0.1", 0)],
        handler=lambda b: b"R:" + b,
    ).start()
    b0 = ImpairedUdpBridge(
        srv.addrs[0], bandwidth_mbps=100.0, one_way_delay_ms=25.0, jitter_ms=65.0, loss_rate=0.05, seed=301
    ).start()
    b1 = ImpairedUdpBridge(
        srv.addrs[1], bandwidth_mbps=100.0, one_way_delay_ms=25.0, jitter_ms=20.0, loss_rate=0.05, seed=402
    ).start()

    try:
        c_single = HedgedRpcClient([b0.a_addr], retry_after_ms=110.0)
        s_lats = sorted(c_single.call(f"q-{i}".encode())[1] for i in range(80))
        c_single.close()

        c_hedged = HedgedRpcClient([b0.a_addr, b1.a_addr], hedge_delay_ms=0.0, retry_after_ms=110.0)
        h_lats = sorted(c_hedged.call(f"q-{i}".encode())[1] for i in range(80))
        c_hedged.close()
    finally:
        b0.close()
        b1.close()
        srv.close()

    def pct(arr: list[float], p: float) -> float:
        idx = min(len(arr) - 1, int(p * len(arr)))
        return round(arr[idx], 2)

    s_p50, s_p95, s_p99 = pct(s_lats, 0.50), pct(s_lats, 0.95), pct(s_lats, 0.99)
    h_p50, h_p95, h_p99 = pct(h_lats, 0.50), pct(h_lats, 0.95), pct(h_lats, 0.99)
    p99_speedup = s_p99 / max(h_p99, 0.01)
    print(f"  Single Path : p50={s_p50}ms  p95={s_p95}ms  p99={s_p99}ms")
    print(f"  Hedged Race : p50={h_p50}ms  p95={h_p95}ms  p99={h_p99}ms  -> p99 cut {p99_speedup:.2f}x!")
    return {
        "requests": 80,
        "before_single_path": {"p50_ms": s_p50, "p95_ms": s_p95, "p99_ms": s_p99},
        "after_hedged_multipath": {"p50_ms": h_p50, "p95_ms": h_p95, "p99_ms": h_p99},
        "p99_reduction_x": round(p99_speedup, 2),
    }


def suite_5_wormhole_ipc() -> dict[str, Any]:
    print("\n=== SUITE 5: LOCAL WINDOWS IPC 64 MiB (Python TCP 127.0.0.1 vs Lock-Free Wormhole) ===")
    size_64m = 64 * 1024 * 1024
    payload = (b"WORM-IPC-64M-" + os.urandom(51)) * (size_64m // 64)
    expected_sha = hashlib.sha256(payload).hexdigest()

    tcp_res = _bench_tcp_loopback(payload, recv_chunk=65536)

    wh_name = f"BENCH_64M_{os.getpid()}_{time.monotonic_ns()}"
    chunk_buf = bytearray(4 * 1024 * 1024)
    rx_got = [0]
    rx_hash = hashlib.sha256()
    reader_ready = threading.Event()

    with WormholeChannel.create(wh_name, capacity_mb=8) as wh_tx:
        def reader() -> None:
            with WormholeChannel.open(wh_name) as wh_rx:
                mv = memoryview(chunk_buf)
                reader_ready.set()
                while True:
                    n = wh_rx.read_into(mv)
                    if n == 0:
                        break
                    rx_got[0] += n
                    rx_hash.update(mv[:n])

        th = threading.Thread(target=reader, daemon=True)
        th.start()
        reader_ready.wait(timeout=5.0)
        t0 = time.perf_counter()
        wh_tx.write_all(payload)
        wh_tx.mark_eof()
        th.join(timeout=20.0)
        wh_ms = (time.perf_counter() - t0) * 1000.0

    wh_ok = rx_got[0] == size_64m and rx_hash.hexdigest() == expected_sha
    wh_mbps = (size_64m * 8.0) / max(wh_ms * 1000.0, 0.001)
    wh_gbps = wh_mbps / 1000.0
    speedup = tcp_res["elapsed_ms"] / max(wh_ms, 0.001)
    print(
        f"  TCP Loopback 64 MiB : {tcp_res['elapsed_ms']:6.2f}ms ({tcp_res['gbps']:5.2f} Gbps)"
    )
    print(
        f"  Wormhole SHM 64 MiB : {wh_ms:6.2f}ms ({wh_gbps:5.2f} Gbps) -> {speedup:.1f}x FASTER!"
    )
    return {
        "bytes": size_64m,
        "before_tcp_loopback": tcp_res,
        "after_wormhole_shm": {
            "elapsed_ms": round(wh_ms, 2),
            "mbps": round(wh_mbps, 2),
            "gbps": round(wh_gbps, 3),
            "sha256_match": wh_ok,
        },
        "speedup": round(speedup, 2),
    }


def suite_6_worst_case_honesty() -> dict[str, Any]:
    print("\n=== SUITE 6: WORST-CASE HONESTY CHECK (2 MiB Random Incompressible, 0% Loss) ===")
    payload = os.urandom(2 * 1024 * 1024)
    tcp_clean = _bench_tcp_over_paced_link(payload, bandwidth_mbps=100.0, one_way_delay_ms=5.0)

    rx = HyperWireReceiver().start()
    bridge = ImpairedUdpBridge(
        target_b=rx.addr, bandwidth_mbps=100.0, one_way_delay_ms=5.0, loss_rate=0.0
    ).start()
    try:
        sender = HyperWireSender(bridge.a_addr, initial_loss_hint=0.0)
        hw_rep = sender.send_stream(payload, stream_id=9, timeout_s=20.0)
        rec, _ = rx.wait_stream(9, timeout_s=20.0)
        ok = hw_rep.sha256_match and rec == payload
    finally:
        bridge.close()
        rx.close()

    ratio = hw_rep.throughput_mbps / max(tcp_clean["mbps"], 0.001)
    print(
        f"  Clean Random 2 MiB | TCP: {tcp_clean['elapsed_ms']:.1f}ms ({tcp_clean['mbps']:.1f} Mbps) "
        f"| CHIMERA Auto-Pilot: {hw_rep.elapsed_ms:.1f}ms ({hw_rep.throughput_mbps:.1f} Mbps, "
        f"overhead={hw_rep.wire_overhead_pct}%, ratio={ratio:.2f}x TCP)"
    )
    return {
        "bytes": len(payload),
        "before_tcp": tcp_clean,
        "after_chimera_autopilot": {
            "elapsed_ms": hw_rep.elapsed_ms,
            "mbps": hw_rep.throughput_mbps,
            "wire_overhead_pct": hw_rep.wire_overhead_pct,
            "fec_packets_sent": hw_rep.fec_packets_sent,
            "sha256_match": ok,
        },
        "throughput_ratio_vs_tcp": round(ratio, 3),
    }


def run_eval(out_path: Path | None = None) -> dict[str, Any]:
    _configure_utf8()
    data = {
        "version": "1.0.0",
        "native_loaded": has_native(),
        "suite_0_silicon_core": suite_0_silicon_core(),
        "suite_1_dna_beam": suite_1_dna_beam(),
        "suite_2_lossy_wan": suite_2_lossy_wan_comparison(),
        "suite_3_active_compute": suite_3_active_compute(),
        "suite_4_hedged_rpc": suite_4_hedged_rpc(),
        "suite_5_wormhole_ipc": suite_5_wormhole_ipc(),
        "suite_6_worst_case": suite_6_worst_case_honesty(),
    }
    target = out_path or (_REPO_ROOT / "chimera_hyper_eval.json")
    target.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nCHIMERA-HYPER v1.0 evaluation saved -> {target.resolve()}")
    return data


if __name__ == "__main__":
    run_eval()
