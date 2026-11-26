"""CHIMERA-HYPER v9.0 HYPERDRIVE — Full 6-Idea Performance & Capability Benchmark Orchestrator."""

from __future__ import annotations

import json
import time
from typing import Any

from .native import v9_native_caps
from .v9_app_index import LiveClusterIndexer, RemoteAppStreamEngine, SharedCasTurboCache
from .v9_dataplane import MultiWanSpeedFusionEngine, NativeDataPlaneEngine
from .v9_nvme_grid import UnifiedHardwareGrid, VirtualNvmeFabric


def run_hyperdrive_benchmark(peer_http_base: str = "", root_dir: str = "") -> dict[str, Any]:
    """Run real Before-vs-After evaluations across all 6 Phần IX (v9.0 HYPERDRIVE) breakthroughs."""
    t0 = time.perf_counter()
    results: dict[str, dict[str, Any]] = {}

    i1 = NativeDataPlaneEngine.run_benchmark()
    results["idea_01_zero_copy_dataplane"] = {
        "name": "1. 0-Copy Native Data-Plane (PH9N + LZ4 SIMD)",
        "ok": i1["ok"],
        "before": f"Python PH5E+zlib: {i1['legacy_mbps']} Mbps ({i1['legacy_ms']}ms)",
        "after": f"{i1['v9_mbps']} Mbps ({i1['speedup_x']}x) | Crypto {i1['raw_batch_chacha_mbps']} Mbps | LZ4 {i1['lz4_vs_zlib_speedup_x']}x vs z6 (-{i1['wire_saved_pct']}%)",
        "detail": i1,
    }

    i2 = VirtualNvmeFabric.run_benchmark(root_dir=root_dir or None, peer_http_base=peer_http_base)
    results["idea_02_virtual_nvme_fabric"] = {
        "name": "2. Virtual NVMe Fabric (RAM Mirror + Lazy 32KB + WB)",
        "ok": i2["ok"],
        "before": "WebDAV/SMB disk stat + full-file fetch",
        "after": f"stat {i2['stat_mean_us']}us ({i2['stat_speedup_x']}x) | Seek -{i2['random_seek_wire_saved_pct']}% | Prefetch {i2['prefetch_hit_rate_pct']}% | WB {i2['writeback_mean_ms']}ms (-{i2['delta_wire_saved_pct']}% delta)",
        "detail": i2,
    }

    i3 = UnifiedHardwareGrid.run_benchmark(peer_http_base=peer_http_base)
    results["idea_03_unified_hardware_grid"] = {
        "name": "3. Unified Hardware Grid & Live Hand-off",
        "ok": i3["ok"],
        "before": f"Serial 1-thread: {i3['serial_ms']}ms",
        "after": f"Parallel {i3['parallel_ms']}ms ({i3['grid_speedup_x']}x, peer={i3['peer_offloaded_tasks']}t) | Hand-off {i3['handoff_ms']}ms (peer={i3['handoff_resumed_on_peer']}, exact={i3['handoff_exact']})",
        "detail": i3,
    }

    i4 = MultiWanSpeedFusionEngine.run_benchmark()
    results["idea_04_multi_wan_speed_fusion"] = {
        "name": "4. Multi-WAN Speed-Fusion & 8% Anti-Loss",
        "ok": i4["ok"],
        "before": f"1x WAN {i4['single_wan_mbps']} Mbps | 8% drop {i4['loss_8pct_tcp_est_mbps']} Mbps",
        "after": f"Fused {i4['fused_wan_mbps']} Mbps ({i4['fusion_speedup_x']}x) | 8% drop {i4['loss_8pct_fusion_mbps']} Mbps ({i4['anti_loss_speedup_x']}x) | Cut failover OK",
        "detail": i4,
    }

    i5 = RemoteAppStreamEngine.run_benchmark()
    results["idea_05_remote_app_60fps_stream"] = {
        "name": "5. Seamless App Window 60-120 FPS (AVX2 Tile+LZ4+UEP)",
        "ok": i5["ok"],
        "before": f"Raw 720p frame {i5['raw_frame_kb']} KB/frame",
        "after": f"{i5['pipeline_fps']} FPS ({i5['frame_latency_ms']}ms) | {i5['mean_wire_kb']} KB (-{i5['wire_saved_pct']}%) | 15% loss text {i5['uep_15pct_loss_text_recovery_pct']}%",
        "detail": i5,
    }

    i6 = LiveClusterIndexer.run_benchmark(root_dir=root_dir or None, peer_http_base=peer_http_base)
    cas = SharedCasTurboCache.run_benchmark()
    i6["cas_cache"] = cas
    results["idea_06_live_indexer_cas_cache"] = {
        "name": "6. <5 ms Live Cluster Indexer + Shared CAS Cache",
        "ok": bool(i6["ok"] and cas["ok"]),
        "before": f"Disk scan {i6['brute_mean_ms']}ms/query",
        "after": f"{i6['mean_query_ms']}ms ({i6['speedup_x']}x, {i6['recall_pct']}% recall, {i6['indexed_files']}f) | CAS hit {cas['hit_mean_ms']}ms (-{cas['saved_pct']}%)",
        "detail": i6,
    }

    all_ok = all(bool(v.get("ok")) for v in results.values())
    return {
        "ok": all_ok,
        "version": "9.0.0",
        "ideas_verified": sum(1 for v in results.values() if v.get("ok")),
        "ideas_total": len(results),
        "native_v9": v9_native_caps(),
        "total_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        "ideas": {k: {kk: vv for kk, vv in v.items() if kk != "detail"} for k, v in results.items()},
        "detail": {k: v["detail"] for k, v in results.items()},
    }


def format_hyperdrive_markdown(report: dict[str, Any]) -> str:
    """Format the 6-idea HYPERDRIVE Before-vs-After benchmark report as Markdown."""
    lines = [
        f"# CHIMERA-HYPER v{report.get('version', '9.0.0')} — 6-Idea HYPERDRIVE Performance & Capability Evaluation",
        f"- **Verified:** `{report.get('ideas_verified')}/{report.get('ideas_total')}` | **Elapsed:** `{report.get('total_ms')} ms` | **Native v9:** `{json.dumps(report.get('native_v9'))}`",
        "",
        "| Capability | Before / Baseline | After (CHIMERA v9.0.0 Measured) | Status |",
        "| :--- | :--- | :--- | :---: |",
    ]
    for _k, item in (report.get("ideas") or {}).items():
        lines.append(f"| {item['name']} | {item['before']} | **{item['after']}** | {'PASS' if item['ok'] else 'FAIL'} |")
    return "\n".join(lines)
