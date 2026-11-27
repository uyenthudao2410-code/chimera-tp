"""Comprehensive tests for CHIMERA-BIOS Ideas #1, #2, and #3 (physio-core).

Covers:
  - Idea #1: CHIMERA-ENDOCRINE (24-byte NIXL mmap compatibility, 12B wire codec,
             hormone antagonism & decay, Oxytocin trust, Cytokine inflammation, receptors)
  - Idea #2: CHIMERA-FRISTON (context-conditioned surprise discrimination,
             multi-horizon forecasts, active inference planning, < 64 KB state bound)
  - Idea #3: CHIMERA-AUTOPHAGY & APOPTOSIS (ATP ledger, Ubiquitin tagging, cold archival
             SHA-256 round-trip, real chimera_tp AST scan, Law-6 auto_activated=False)
  - Laws 2, 6, 7 compliance & < 2 MiB memory footprint.
"""

from __future__ import annotations

import json
import math
import sqlite3
import struct
import time
import tracemalloc
from pathlib import Path

import pytest

from chimera_tp.platform.aeon_dynamo import NixlSignalRing
from chimera_tp.platform.bios.autophagy import (
    MetabolicAutophagyEngine,
    compute_atp_score,
)
from chimera_tp.platform.bios.endocrine import (
    ENDO_BYTES,
    ENDO_MAGIC,
    ENDO_OFFSET,
    HOMEOSTASIS_SETPOINTS,
    HORMONE_HALF_LIFE_S,
    HORMONE_NAMES,
    EndocrineSystem,
    decode_wire_12b,
    encode_wire_12b,
    pack_endocrine_block,
    read_endocrine_block_mmap,
    read_hormones_mmap,
    unpack_endocrine_block,
)
from chimera_tp.platform.bios.friston import (
    KNOWN_CONTEXTS,
    ActiveInferenceBrain,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# IDEA #1: CHIMERA-ENDOCRINE TESTS
# ---------------------------------------------------------------------------


def test_endocrine_nixl_64b_header_binary_compatibility(tmp_path: Path) -> None:
    """NixlSignalRing publish/drain must stay byte-for-byte intact when Endocrine writes bytes 32..63."""
    ring_path = tmp_path / "chimera_nixl_ring.bin"

    ring = NixlSignalRing(ring_path)
    try:
        p1 = ring.publish("sptc", {"doc": "alpha", "tokens": 128})
        p2 = ring.publish("kv_hint", {"layer": 4, "hot": True})
        assert p1["ok"] and p2["ok"]

        # Snapshot exact bytes 0..31 before Endocrine touches the ring
        before_head = ring_path.read_bytes()[:32]
        assert before_head[:4] == b"NXLR"

        with EndocrineSystem(ring_path) as endo:
            res = endo.secrete("adrenaline", 0.55, source="autocad_burst")
            assert res["ok"] and res["mmap_synced"]
            endo.inflame("chimera_tp/platform/substrate.py", 0.45, reason="hot_edit")
            endo.adjust_trust("agent_alpha", 0.20, reason="clean_tests")

            # Verify bytes 0..31 are completely untouched
            raw_hdr = ring_path.read_bytes()[:64]
            assert raw_hdr[:32] == before_head

            # Verify bytes 32..63 carry valid ENDO magic + CRC16 + 6 floats
            block = unpack_endocrine_block(raw_hdr[ENDO_OFFSET : ENDO_OFFSET + ENDO_BYTES])
            assert block["valid"] is True
            assert block["magic"] == "ENDO"
            assert block["seq"] >= 1
            for name in HORMONE_NAMES:
                assert math.isclose(block["hormones"][name], endo.levels()[name], abs_tol=1e-5)

            # External zero-copy reader must see identical hormones
            ext_levels = read_hormones_mmap(ring_path, strict=True)
            for name in HORMONE_NAMES:
                assert math.isclose(ext_levels[name], endo.levels()[name], abs_tol=1e-5)

            # Publish a 3rd message via NixlSignalRing AFTER Endocrine writes
            p3 = ring.publish("homeostasis", {"temp_c": 46.5})
            assert p3["ok"] and p3["seq"] == 3

            # Drain all 3 messages — exact payload fidelity preserved
            drained = ring.drain(limit=10)
            assert len(drained) == 3
            assert [m["kind"] for m in drained] == ["sptc", "kv_hint", "homeostasis"]
            assert drained[0]["payload"] == {"doc": "alpha", "tokens": 128}
            assert drained[1]["payload"] == {"layer": 4, "hot": True}
            assert drained[2]["payload"] == {"temp_c": 46.5}

            # Verify NixlSignalRing write/drain did not disturb ENDO block bytes 32..63
            post_block = read_endocrine_block_mmap(ring_path)
            assert post_block["valid"] is True
            assert math.isclose(post_block["hormones"]["adrenaline"], endo.levels()["adrenaline"], abs_tol=1e-5)
    finally:
        ring.close()


def test_endocrine_creates_ring_first_then_nixl_uses_it(tmp_path: Path) -> None:
    """If EndocrineSystem creates the ring file first, NixlSignalRing still attaches without clobbering ENDO."""
    ring_path = tmp_path / "fresh_ring.bin"
    with EndocrineSystem(ring_path) as endo:
        endo.secrete("dopamine", 0.30, source="test_pass")
        expected_dop = endo.levels()["dopamine"]

        ring = NixlSignalRing(ring_path)
        try:
            pub = ring.publish("sptc", {"hello": "bios"})
            assert pub["ok"]
            drained = ring.drain(limit=4)
            assert len(drained) == 1
            assert drained[0]["payload"] == {"hello": "bios"}
        finally:
            ring.close()

        read_back = read_hormones_mmap(ring_path, strict=True)
        assert math.isclose(read_back["dopamine"], expected_dop, abs_tol=1e-5)


def test_endocrine_crc16_tamper_detection(tmp_path: Path) -> None:
    ring_path = tmp_path / "tamper_ring.bin"
    with EndocrineSystem(ring_path) as endo:
        endo.secrete("adrenaline", 0.4, source="probe")
    # Flip a byte inside bytes 40..63 (hormone float payload)
    raw = bytearray(ring_path.read_bytes())
    raw[44] ^= 0xFF
    ring_path.write_bytes(raw)

    blk = read_endocrine_block_mmap(ring_path)
    assert blk["valid"] is False
    assert blk["error"] == "crc16_mismatch"
    with pytest.raises(ValueError, match="crc16_mismatch"):
        read_hormones_mmap(ring_path, strict=True)


def test_endocrine_wire_12b_roundtrip_and_blend() -> None:
    sample = {
        "adrenaline": 0.0,
        "cortisol": 1.0,
        "dopamine": 0.7312,
        "melatonin": 0.2500,
        "cytokine": 0.4198,
        "oxytocin": 0.8888,
    }
    wire = encode_wire_12b(sample)
    assert len(wire) == 12
    decoded = decode_wire_12b(wire)
    for name in HORMONE_NAMES:
        assert math.isclose(decoded[name], sample[name], abs_tol=1e-4)

    with pytest.raises(ValueError):
        decode_wire_12b(b"short")

    endo = EndocrineSystem(ephemeral=True)
    before_adr = endo.levels()["adrenaline"]
    peer_wire = encode_wire_12b({**sample, "adrenaline": 0.90})
    blended = endo.apply_wire_12b(peer_wire, blend=0.5)
    assert math.isclose(blended["hormones"]["adrenaline"], 0.5 * before_adr + 0.5 * 0.90, abs_tol=1e-3)


def test_endocrine_antagonism_decay_trust_cytokine_and_receptors() -> None:
    endo = EndocrineSystem(ephemeral=True)
    received: list[dict] = []
    endo.register_receptor("observer", lambda payload: received.append(payload))
    endo.register_receptor("faulty", lambda _payload: 1 / 0)  # must be isolated

    # Raise melatonin first, then spike adrenaline -> adrenaline must suppress melatonin
    endo.secrete("melatonin", 0.60, source="night_idle")
    mel_before = endo.levels()["melatonin"]
    assert mel_before >= 0.70
    assert endo.derive_directives()["sleep_eligible"] is True

    endo.secrete("adrenaline", 0.70, source="autocad_pan")
    assert endo.levels()["melatonin"] < mel_before - 0.20
    assert endo.derive_directives()["cad_vip"] is True
    assert endo.derive_directives()["sleep_eligible"] is False
    assert endo.derive_directives()["law2_advisory_only"] is True

    # Sustained cortisol damps dopamine
    dop_before = endo.levels()["dopamine"]
    endo.secrete("cortisol", 0.65, source="thermal_stress")
    assert endo.levels()["dopamine"] < dop_before - 0.15

    # Exponential half-life decay brings elevated hormones smoothly back toward setpoint
    adr_peak = endo.levels()["adrenaline"]
    endo.decay(HORMONE_HALF_LIFE_S["adrenaline"])
    adr_after_hl = endo.levels()["adrenaline"]
    expected_mid = HOMEOSTASIS_SETPOINTS["adrenaline"] + 0.5 * (adr_peak - HOMEOSTASIS_SETPOINTS["adrenaline"])
    assert math.isclose(adr_after_hl, expected_mid, abs_tol=0.03)

    # Oxytocin trust ledger transitions & sandbox directives
    t_high = endo.adjust_trust("trusted_agent", 0.25, reason="verified_commits")
    assert t_high["trust_policy"]["tier"] == "symbiotic"
    assert t_high["trust_policy"]["lane"] == "fast_lane"
    assert t_high["trust_policy"]["require_sandbox"] is False

    t_low = endo.adjust_trust("rogue_script", -0.45, reason="secret_probe")
    assert t_low["trust_policy"]["tier"] == "quarantined"
    assert t_low["trust_policy"]["require_sandbox"] is True
    assert "rogue_script" in endo.derive_directives()["sandbox_required_apps"]

    # Localized Cytokine inflammation + clearing
    inf = endo.inflame("chimera_tp/platform/vault_sql.py", 0.65, reason="lock_contention")
    assert inf["intensity"] >= 0.65
    assert "chimera_tp/platform/vault_sql.py" in endo.derive_directives()["inflamed_loci"]
    assert endo.clear_inflammation("chimera_tp/platform/vault_sql.py") is True
    assert "chimera_tp/platform/vault_sql.py" not in endo.derive_directives()["inflamed_loci"]

    # Receptor received callbacks despite faulty sibling receptor
    assert len(received) >= 5
    snap = endo.snapshot()
    assert len(bytes.fromhex(snap["wire_12b_hex"])) == 12
    assert snap["ephemeral"] is True


# ---------------------------------------------------------------------------
# IDEA #2: CHIMERA-FRISTON TESTS
# ---------------------------------------------------------------------------


def test_friston_distinguishes_expected_cad_load_from_stealth_idle_spike() -> None:
    brain = ActiveInferenceBrain()
    t0 = 1_700_000_000.0

    # Prime a few realistic CAD and idle ticks
    for i in range(5):
        brain.observe(
            {
                "cpu_pct": 64.0 + i,
                "gpu_pct": 70.0 + i,
                "ram_pct": 58.0,
                "disk_io_mb_s": 34.0,
                "token_rate": 6.0,
                "active_streams": 1,
            },
            context="cad",
            ts=t0 + i * 5.0,
        )
        brain.observe(
            {
                "cpu_pct": 6.0 + (i % 2),
                "gpu_pct": 4.0,
                "ram_pct": 38.0,
                "disk_io_mb_s": 2.0,
                "token_rate": 0.5,
                "active_streams": 0,
            },
            context="idle",
            ts=t0 + 100.0 + i * 5.0,
        )

    # Expected high load during AutoCAD work -> LOW surprise
    cad_high = brain.observe(
        {
            "cpu_pct": 74.0,
            "gpu_pct": 78.0,
            "ram_pct": 62.0,
            "disk_io_mb_s": 40.0,
            "token_rate": 8.0,
            "active_streams": 1,
        },
        context="cad",
        ts=t0 + 200.0,
    )
    assert cad_high["surprise"] < 0.25
    assert cad_high["regime"] == "expected"

    # Identical/similar high CPU + disk surge during IDLE -> HIGH surprise (stealth spike!)
    stealth_idle = brain.observe(
        {
            "cpu_pct": 74.0,
            "gpu_pct": 18.0,
            "ram_pct": 44.0,
            "disk_io_mb_s": 90.0,
            "token_rate": 0.5,
            "active_streams": 0,
        },
        context="idle",
        ts=t0 + 210.0,
    )
    assert stealth_idle["surprise"] > 0.85
    assert stealth_idle["regime"] == "anomalous"
    assert "cpu_pct" in stealth_idle["anomalous_features"]
    assert "disk_io_mb_s" in stealth_idle["anomalous_features"]
    assert stealth_idle["z_scores"]["cpu_pct"] > 5.0
    assert stealth_idle["surprise"] - cad_high["surprise"] > 0.65

    # Robustness check: stealth spike must NOT corrupt idle baseline into ignoring a repeat spike
    stealth_repeat = brain.observe(
        {"cpu_pct": 72.0, "disk_io_mb_s": 85.0},
        context="idle",
        ts=t0 + 220.0,
    )
    assert stealth_repeat["surprise"] > 0.85


def test_friston_multi_horizon_forecast_and_active_inference_plans() -> None:
    brain = ActiveInferenceBrain()
    f_10s = brain.predict(10.0, context="coding")
    f_300s = brain.predict(300.0, context="coding")
    f_7200s = brain.predict(7200.0, context="coding")

    # Confidence interval width must grow monotonically with forecast horizon
    std_10 = f_10s["predictions"]["cpu_pct"]["std"]
    std_300 = f_300s["predictions"]["cpu_pct"]["std"]
    std_7200 = f_7200s["predictions"]["cpu_pct"]["std"]
    assert std_10 < std_300 < std_7200
    assert math.isclose(sum(f_7200s["context_distribution"].values()), 1.0, abs_tol=1e-3)

    # Active inference actions on stealth idle spike
    idle_plan = brain.plan_active_inference(
        {"cpu_pct": 78.0, "disk_io_mb_s": 95.0, "rss_mb": 70.0},
        context="idle",
    )
    action_names = [a["action"] for a in idle_plan]
    assert "isolate_anomalous_process_audit" in action_names
    assert "cool_shed_cold_cache" in action_names
    assert all(a["law2_compliant"] is True and a["auto_activated"] is False for a in idle_plan)
    # Sorted descending by EFE gain
    gains = [a["efe_gain"] for a in idle_plan]
    assert gains == sorted(gains, reverse=True)

    # Active inference on heavy swarm coding cadence
    swarm_plan = brain.plan_active_inference(
        {"cpu_pct": 85.0, "token_rate": 95.0, "cache_hit_ratio": 0.42, "active_streams": 5, "svhome_temp_c": 67.0},
        context="coding",
    )
    swarm_actions = {a["action"] for a in swarm_plan}
    assert "pre_cook_compaction_crystal" in swarm_actions
    assert "pre_warm_colab_t4" in swarm_actions
    assert "cool_shed_cold_cache" in swarm_actions


def test_friston_state_serialization_strictly_under_64kb() -> None:
    brain = ActiveInferenceBrain()
    # Stress-test with many dynamic contexts and synthetic telemetry keys
    for c_idx in range(25):
        obs = {f"custom_metric_{k}": float(k + c_idx) for k in range(35)}
        obs["cpu_pct"] = 30.0 + c_idx
        brain.observe(obs, context=f"dyn_ctx_{c_idx}")

    state = brain.to_state()
    raw_bytes = json.dumps(state, separators=(",", ":")).encode("utf-8")
    assert len(raw_bytes) < 65536
    assert brain.state_bytes_size() < 65536
    assert brain.status()["within_64kb_budget"] is True

    restored = ActiveInferenceBrain.from_state(state)
    assert restored.status()["observation_count"] == brain.status()["observation_count"]
    assert set(restored.status()["contexts"]) == set(brain.status()["contexts"])
    for ctx in KNOWN_CONTEXTS:
        assert ctx in restored.status()["contexts"]


# ---------------------------------------------------------------------------
# IDEA #3: CHIMERA-AUTOPHAGY & APOPTOSIS TESTS
# ---------------------------------------------------------------------------


def test_autophagy_atp_ubiquitin_and_cold_dormancy_roundtrip(tmp_path: Path) -> None:
    now = 1_750_000_000.0
    old_ts = now - 45.0 * 86400.0  # 45 days stale

    with MetabolicAutophagyEngine(tmp_path / "ops", REPO_ROOT, ephemeral=False) as eng:
        active = eng.record_metabolism(
            "organ.agent_probe",
            "organ",
            calls=40,
            ms_saved=1250.0,
            tokens_saved=18000,
            ram_saved_mb=12.5,
            errors_prevented=3,
            now_ts=now,
        )
        assert active["atp_score"] == compute_atp_score(40, 1250.0, 18000, 12.5, 3)
        assert active["atp_score"] > 100.0

        zero_atp = eng.record_metabolism("legacy.dead_helper", "module", calls=0, now_ts=now)
        assert zero_atp["atp_score"] == 0.0

        stale = eng.record_metabolism("legacy.old_route", "route", calls=1, ms_saved=10.0, now_ts=old_ts)
        assert stale["atp_score"] > 0.0

        ubiq = eng.evaluate_ubiquitin(dormancy_days=30.0, now_ts=now)
        tagged_ids = {t["entity_id"] for t in ubiq["tagged"]}
        healthy_ids = {h["entity_id"] for h in ubiq["healthy"]}
        assert "legacy.dead_helper" in tagged_ids
        assert "legacy.old_route" in tagged_ids
        assert "organ.agent_probe" in healthy_ids

        # Cold archival round-trip (0 B hot RAM + compression + SHA-256 verification)
        payload = (b'{"legacy_rule":"dormant_cache_payload","entries":[' + b'"item",' * 400 + b'"end"]}')
        arc = eng.archive_dormant("legacy.dead_helper", payload)
        assert arc["ok"] is True
        assert arc["hot_ram_bytes"] == 0
        assert arc["compressed_bytes"] < arc["raw_bytes"]
        assert arc["codec"] in ("lz4", "zlib")

        restored = eng.rehydrate_dormant("legacy.dead_helper")
        assert restored == payload

        # Tamper with stored sha256 to prove integrity gate raises ValueError
        eng._conn.execute(
            "UPDATE dormant_vault SET sha256 = ? WHERE entity_id = ?",
            ("0" * 64, "legacy.dead_helper"),
        )
        eng._conn.commit()
        with pytest.raises(ValueError, match="SHA-256 integrity mismatch"):
            eng.rehydrate_dormant("legacy.dead_helper")


def test_autophagy_real_codebase_scan_and_law6_apoptosis_proposal() -> None:
    with MetabolicAutophagyEngine(repo_root=REPO_ROOT, ephemeral=True) as eng:
        scan = eng.scan_codebase_metabolism(REPO_ROOT)
        assert scan["ok"] is True
        assert scan["total_modules"] >= 100
        assert scan["total_loc"] > 10_000
        assert scan["parse_errors"] == []
        assert isinstance(scan["cold_modules"], list)
        assert isinstance(scan["legacy_modules"], list)
        assert scan["scan_ms"] >= 0.0

        proposal = eng.propose_apoptosis_pr(REPO_ROOT, max_candidates=10)
        # Strictly Law-6 compliant
        assert proposal["auto_activated"] is False
        assert proposal["requires_human_approval"] is True
        assert proposal["promotion_stage"] == "Lab"
        assert len(proposal["sha256"]) == 64
        assert proposal["rollback_recipe"]["zero_files_modified"] is True
        assert proposal["invariant_checks"]["law6_auto_activated_false"] is True
        assert proposal["invariant_checks"]["law2_zero_choke_compliant"] is True

        st = eng.status()
        assert st["ephemeral"] is True
        assert st["apoptosis_proposals_count"] == 1


# ---------------------------------------------------------------------------
# LAWS 2, 6, 7 CONSTITUTIONAL & MEMORY FOOTPRINT CHECKS
# ---------------------------------------------------------------------------


def test_physio_core_constitutional_laws_and_memory_budget() -> None:
    bios_dir = REPO_ROOT / "chimera_tp" / "platform" / "bios"
    forbidden_tokens = (
        "SetProcessAffinityMask",
        "0xF00",
        "EcoQoS",
        "NtSuspendProcess",
        "PROCTHROTTLEMAX",
        "import numpy",
        "from numpy",
    )
    for fname in ("endocrine.py", "friston.py", "autophagy.py"):
        src = (bios_dir / fname).read_text(encoding="utf-8")
        for tok in forbidden_tokens:
            assert tok not in src, f"Forbidden token {tok!r} found in {fname}"

    # Verify combined runtime RAM footprint of all 3 engines is well under 2 MiB
    tracemalloc.start()
    try:
        endo = EndocrineSystem(ephemeral=True)
        brain = ActiveInferenceBrain()
        auto = MetabolicAutophagyEngine(repo_root=REPO_ROOT, ephemeral=True)
        endo.secrete("adrenaline", 0.3, source="mem_check")
        brain.observe({"cpu_pct": 45.0, "gpu_pct": 30.0}, context="coding")
        auto.record_metabolism("probe.x", "module", calls=3, ms_saved=20.0)
        current_bytes, peak_bytes = tracemalloc.get_traced_memory()
        auto.close()
        endo.close()
    finally:
        tracemalloc.stop()

    assert peak_bytes < 2 * 1024 * 1024, f"Peak memory {peak_bytes} exceeded 2 MiB budget"
    assert current_bytes < 2 * 1024 * 1024
