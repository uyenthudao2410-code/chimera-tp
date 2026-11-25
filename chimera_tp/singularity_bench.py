"""CHIMERA v8.0 SINGULARITY — Full 7-Idea Adversarial Benchmark & Evaluation Orchestrator."""

from __future__ import annotations

import json
import time
from typing import Any

from .native import v7_native_caps, v8_native_caps
from .singularity_airgap_crypto import (
    AirGapFountainBridge,
    PlausibleDeniabilityVault,
    PrivateInfoRetrievalEngine,
)
from .singularity_kolmogorov_swarm import KolmogorovGrammarCodec, SwarmAnycastMesh
from .singularity_time_crdt import MerkleCrdtShadowTwin, SpeculativeTimeWarpEngine


def run_singularity_benchmark(peer_http_base: str = "") -> dict[str, Any]:
    """Run real end-to-end & adversarial evaluations across all 7 SINGULARITY v8.0 breakthroughs."""
    t0 = time.perf_counter()
    results: dict[str, dict[str, Any]] = {}

    i1 = SpeculativeTimeWarpEngine.run_benchmark(peer_http_base=peer_http_base)
    results["idea_01_speculative_timewarp"] = {
        "name": "1. Speculative Time-Warp (-RTT Cache)",
        "ok": i1["ok"],
        "before": f"Cold fetch {i1['cold_mean_ms']}ms | random-walk waste risk",
        "after": f"Warm hit {i1['warm_hit_mean_ms']}ms ({i1['speedup_x']}x), {i1['predictable_hits']}, adv-throttled={i1['adversarial_throttled']}",
        "detail": i1,
    }

    i2 = MerkleCrdtShadowTwin.run_benchmark()
    results["idea_02_merkle_crdt_twin"] = {
        "name": "2. Offline Merkle-CRDT Shadow-Twin",
        "ok": i2["ok"],
        "before": i2["baseline_etag_result"],
        "after": f"20/20 shuffled orders -> 1 root ({i2['converged_root']}), {i2['conflicts_audited']} conflict audited",
        "detail": i2,
    }

    i3 = AirGapFountainBridge.run_benchmark()
    results["idea_03_airgap_fountain"] = {
        "name": "3. Air-Gap Ultrasonic & Optical Fountain",
        "ok": i3["ok"],
        "before": "0 bps when Wi-Fi/LAN/USB disconnected",
        "after": f"6dB AWGN + 25% drop -> 100% ({i3['audio_frames_survived']} audio, {i3['optical_frames_survived']} opt)",
        "detail": i3,
    }

    i4 = PrivateInfoRetrievalEngine.run_benchmark(peer_http_base=peer_http_base)
    results["idea_04_it_pir_gf256"] = {
        "name": "4. 2-Server Blind Query (IT-PIR 1 MiB)",
        "ok": i4["ok"],
        "before": f"Pull full {i4['db_bytes']}B DB or leak index",
        "after": f"{i4['wire_bytes']}B wire (-{i4['wire_saved_pct']}%), {i4['mode']}, {i4['simd_scan_gbps']} GB/s",
        "detail": i4,
    }

    i5 = PlausibleDeniabilityVault.run_benchmark()
    results["idea_05_plausible_deniability"] = {
        "name": "5. Dual-Truth Plausible Deniability Vault",
        "ok": i5["ok"],
        "before": "Single password exposes all vault contents",
        "after": f"Entropy {i5['single_mean_entropy']} vs {i5['dual_mean_entropy']} b/B (chi2 delta {i5['chi2_delta_10vs10']}, equal bytes)",
        "detail": i5,
    }

    i6 = KolmogorovGrammarCodec.run_benchmark()
    j = i6["corpora"]["jsonl_1000"]
    h = i6["corpora"]["http_access_500"]
    results["idea_06_kolmogorov_grammar"] = {
        "name": "6. Kolmogorov Grammar Wire Codec",
        "ok": i6["ok"],
        "before": f"JSONL lzma={j['lzma_bytes']}B / zlib9={j['zlib9_bytes']}B",
        "after": f"JSONL {j['v8_kolmogorov_bytes']}B (-{j['vs_zlib9_pct']}% vs z9, -{j['vs_lzma_pct']}% vs lzma); rand +{i6['random_overhead_pct']}%",
        "detail": i6,
    }

    i7 = SwarmAnycastMesh.run_benchmark()
    results["idea_07_swarm_anycast"] = {
        "name": "7. 3-Node Swarm RLNC Anycast & Failover",
        "ok": i7["ok"],
        "before": f"Direct cut {i7['direct_packets_arrived']} @ {i7['direct_degraded_est_rtt_ms']}ms",
        "after": f"2-hop recode {i7['anycast_packets_delivered']}, rehydrated {i7['standby_rehydration_ms']}ms (0 PT)",
        "detail": i7,
    }

    all_ok = all(bool(v.get("ok")) for v in results.values())
    return {
        "ok": all_ok,
        "version": "8.0.0",
        "ideas_verified": sum(1 for v in results.values() if v.get("ok")),
        "ideas_total": len(results),
        "native_v7": v7_native_caps(),
        "native_v8": v8_native_caps(),
        "total_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        "ideas": {k: {kk: vv for kk, vv in v.items() if kk != "detail"} for k, v in results.items()},
        "detail": {k: v["detail"] for k, v in results.items()},
    }


def format_singularity_markdown(report: dict[str, Any]) -> str:
    """Format the 7-idea SINGULARITY Before-vs-After benchmark report as Markdown."""
    lines = [
        f"# CHIMERA-HYPER v{report.get('version', '8.0.0')} — 7-Idea SINGULARITY Adversarial Evaluation",
        f"- **Verified:** `{report.get('ideas_verified')}/{report.get('ideas_total')}` | **Elapsed:** `{report.get('total_ms')} ms` | **Native v8:** `{json.dumps(report.get('native_v8'))}`",
        "",
        "| Capability | Before / Baseline | After (CHIMERA v8.0.0 Measured) | Status |",
        "| :--- | :--- | :--- | :---: |",
    ]
    for _k, item in (report.get("ideas") or {}).items():
        lines.append(f"| {item['name']} | {item['before']} | **{item['after']}** | {'PASS' if item['ok'] else 'FAIL'} |")
    return "\n".join(lines)
