"""Comprehensive test suite for CHIMERA-BIOS Ideas #7, #8, #9, and #10:
- Idea #7: `chimera_tp.platform.bios.umwelt` (CHIMERA-UMWELT)
- Idea #8: `chimera_tp.platform.bios.hgt` (CHIMERA-HGT)
- Idea #9: `chimera_tp.platform.bios.mycelium` (CHIMERA-MYCELIUM)
- Idea #10: `chimera_tp.platform.bios.soul` (CHIMERA-SOUL)
"""
from __future__ import annotations

import base64
import json
import re
import sqlite3
import time
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path

import pytest

from chimera_tp.platform.bios.hgt import HorizontalGeneTransferEngine, MAX_PLASMID_BYTES
from chimera_tp.platform.bios.mycelium import (
    MAX_PWA_BYTES,
    MyceliumSporeMesh,
    blind_reconstruct,
    blind_split,
    render_spore_pwa_html,
)
from chimera_tp.platform.bios.soul import AutobiographicalSoul, vsa_encode_10k, vsa_similarity_10k
from chimera_tp.platform.bios.umwelt import UmweltCognitiveResonator


# ---------------------------------------------------------------------------
# Idea #7: CHIMERA-UMWELT Tests
# ---------------------------------------------------------------------------


class TestUmweltCognitiveResonator:
    def test_flow_shield_activates_on_steady_focused_work(self, tmp_path: Path) -> None:
        eng = UmweltCognitiveResonator(tmp_path, ephemeral=False)
        try:
            t0 = datetime(2026, 11, 27, 10, 0, 0).timestamp()
            for i in range(8):
                eng.record_signal(
                    "edit",
                    app="vscode",
                    target="chimera_tp/platform/substrate.py",
                    ok=True,
                    ts=t0 + i * 12.0,
                )
            eng.record_signal(
                "test_pass",
                app="vscode",
                target="tests/test_substrate.py",
                ok=True,
                ts=t0 + 100.0,
            )
            state = eng.assess(now_ts=t0 + 105.0)
            assert 0.0 <= state["flow_score"] <= 1.0
            assert 0.0 <= state["frustration_score"] <= 1.0
            assert state["flow_score"] >= 0.65
            assert state["frustration_score"] < 0.25
            assert state["flow_shield"] is True
            assert state["flow_shield_directives"]["suppress_notifications"] is True
            assert state["whisper_triggered"] is False
            assert state["subconscious_whisper"]["triggered"] is False
            assert state["privacy_guarantees"] == {
                "camera": False,
                "microphone": False,
                "cloud_upload": False,
                "local_only": True,
            }
        finally:
            eng.close()

    def test_frustration_whisper_on_repeated_test_fail_and_undo_steer(self) -> None:
        eng = UmweltCognitiveResonator(ephemeral=True)
        try:
            t0 = datetime(2026, 11, 27, 14, 0, 0).timestamp()
            # Repeated same test failure >= 3x + undo/steer bursts
            for i in range(3):
                eng.record_signal(
                    "test_fail",
                    app="vscode",
                    target="tests/test_relay.py::test_reconnect",
                    ok=False,
                    ts=t0 + i * 15.0,
                )
            eng.record_signal("undo", app="vscode", target="relay.py", ok=True, ts=t0 + 50.0)
            eng.record_signal("steer", app="codex", target="relay.py", ok=True, ts=t0 + 55.0)
            eng.record_signal("undo", app="vscode", target="relay.py", ok=True, ts=t0 + 60.0)

            state = eng.assess(now_ts=t0 + 65.0)
            assert state["frustration_score"] >= 0.65
            assert state["flow_shield"] is False
            assert state["whisper_triggered"] is True
            whisper = state["subconscious_whisper"]
            assert whisper["triggered"] is True
            assert whisper["interrupt_user"] is False
            assert whisper["mode"] == "silent_out_of_band"
            assert any("same_test_fail_3x" in r for r in whisper["trigger_reasons"])
            assert whisper["hot_target"] == "tests/test_relay.py::test_reconnect"
        finally:
            eng.close()

    def test_frustration_whisper_on_file_ping_pong(self) -> None:
        eng = UmweltCognitiveResonator(ephemeral=True)
        try:
            t0 = datetime(2026, 11, 27, 15, 0, 0).timestamp()
            files = ["a.py", "b.py", "a.py", "b.py", "a.py", "b.py", "a.py", "b.py"]
            for i, f in enumerate(files):
                eng.record_signal("edit", app="vscode", target=f, ok=True, ts=t0 + i * 8.0)
            state = eng.assess(now_ts=t0 + 70.0)
            assert state["telemetry_summary"]["ping_pong_score"] >= 0.80
            assert state["frustration_score"] >= 0.60
            assert state["whisper_triggered"] is True
            assert set(state["subconscious_whisper"]["ping_pong_files"]) == {"a.py", "b.py"}
        finally:
            eng.close()

    def test_circadian_phase_learner_and_five_minute_anticipation(self, tmp_path: Path) -> None:
        # Train weekday 09:00 -> cad_mode and weekday 10:00 -> swarm_coding
        eng = UmweltCognitiveResonator(tmp_path, ephemeral=False)
        try:
            # 2026-11-27 is a Friday (weekday)
            cad_ts = datetime(2026, 11, 27, 9, 10, 0).timestamp()
            code_ts = datetime(2026, 11, 27, 10, 15, 0).timestamp()
            for i in range(5):
                eng.record_signal("cad_cmd", app="acad.exe", target="site.dwg", ts=cad_ts + i * 5)
                eng.record_signal("edit", app="vscode", target="core.py", ts=code_ts + i * 5)
        finally:
            eng.close()

        # Re-open from SQLite WAL to verify persistence
        eng2 = UmweltCognitiveResonator(tmp_path, ephemeral=False)
        try:
            # At 08:57 on a weekday, 5-minute lead looks into 09:02 -> anticipates cad_mode!
            probe_cad = datetime(2026, 11, 27, 8, 57, 0).timestamp()
            ant_cad = eng2.anticipate_phase(now_ts=probe_cad, lead_minutes=5)
            assert ant_cad["target_day_type"] == "weekday"
            assert ant_cad["target_hour"] == 9
            assert ant_cad["predicted_phase"] == "cad_mode"
            assert ant_cad["confidence"] >= 0.85
            assert ant_cad["law_2_compliant"] is True
            assert len(ant_cad["metamorphosis_actions"]) >= 1

            # At 09:57 on a weekday, 5-minute lead looks into 10:02 -> anticipates swarm_coding!
            probe_code = datetime(2026, 11, 27, 9, 57, 0).timestamp()
            ant_code = eng2.anticipate_phase(now_ts=probe_code, lead_minutes=5)
            assert ant_code["target_hour"] == 10
            assert ant_code["predicted_phase"] == "swarm_coding"
            assert ant_code["confidence"] >= 0.85
        finally:
            eng2.close()


# ---------------------------------------------------------------------------
# Idea #8: CHIMERA-HGT Tests
# ---------------------------------------------------------------------------


class TestHorizontalGeneTransferEngine:
    def test_starter_plasmids_seeded_and_valid_under_8kb(self, tmp_path: Path) -> None:
        hgt = HorizontalGeneTransferEngine(tmp_path, ephemeral=False)
        try:
            plasmids = hgt.list_plasmids()
            names = {p["name"] for p in plasmids}
            assert {
                "singleflight_coalescer",
                "wal_group_commit",
                "zero_alloc_ring_codec",
            }.issubset(names)
            for p in plasmids:
                assert p["byte_size"] <= MAX_PLASMID_BYTES
                assert len(p["sha256"]) == 64
                ver = hgt.verify_plasmid(p["plasmid_id"])
                assert ver["valid"] is True
                assert ver["within_8kb_cap"] is True
                assert ver["byte_size"] == p["byte_size"]
        finally:
            hgt.close()

    def test_extract_plasmid_enforces_8kb_cap_strictly(self) -> None:
        hgt = HorizontalGeneTransferEngine(ephemeral=True)
        try:
            small = hgt.extract_plasmid(
                name="fast_crc_cache",
                source_project="chimera-tp/net",
                code_or_spec="def fast_sum(xs):\n    return sum(xs)\n",
                io_contract={"input": "list[int]", "output": "int"},
                benchmark_oracle={"metric": "latency_ns", "parity": "exact"},
                tags=["cache", "fast", "net"],
            )
            assert small["byte_size"] <= MAX_PLASMID_BYTES
            assert hgt.verify_plasmid(small["plasmid_id"])["valid"] is True

            # Oversized plasmid (> 8192 bytes) MUST be rejected
            huge_code = "def bloated():\n    return '" + ("x" * 9000) + "'\n"
            with pytest.raises(ValueError, match="8192"):
                hgt.extract_plasmid(
                    name="oversized_gene",
                    source_project="lab",
                    code_or_spec=huge_code,
                    io_contract={"in": "none"},
                    benchmark_oracle={"metric": "none"},
                    tags=["bloat"],
                )
            assert hgt.get_plasmid("oversized_gene") is None
        finally:
            hgt.close()

    def test_scan_ecosystem_targets_ranks_matching_bottlenecks(self, tmp_path: Path) -> None:
        # Create a real synthetic Python file with per-row sqlite commit bottleneck
        bad_sqlite = tmp_path / "telemetry_writer.py"
        bad_sqlite.write_text(
            "import sqlite3\n"
            "def write_one(conn, row):\n"
            "    conn.execute('INSERT INTO t VALUES (?)', (row,))\n"
            "    conn.commit()\n",
            encoding="utf-8",
        )
        hgt = HorizontalGeneTransferEngine(ephemeral=True)
        try:
            candidates = [
                {
                    "name": "unrelated_graphics",
                    "tags": ["shader", "color"],
                    "bottlenecks": ["gamma"],
                },
                {
                    "name": "radar_sqlite_store",
                    "tags": ["sqlite", "persistence"],
                    "bottlenecks": ["wal", "batching", "ssd"],
                },
                bad_sqlite,
                {
                    "name": "already_upgraded",
                    "tags": ["sqlite", "wal"],
                    "installed_plasmids": ["wal_group_commit"],
                },
            ]
            matches = hgt.scan_ecosystem_targets("wal_group_commit", candidates)
            by_name = {m["target_name"]: m for m in matches}
            assert by_name["radar_sqlite_store"]["recommended"] is True
            assert by_name["telemetry_writer.py"]["recommended"] is True
            assert by_name["radar_sqlite_store"]["match_score"] > by_name["unrelated_graphics"]["match_score"]
            assert by_name["already_upgraded"]["already_present"] is True
            assert by_name["already_upgraded"]["recommended"] is False
        finally:
            hgt.close()

    def test_sandbox_ab_graft_parity_and_law6_enforcement(self, tmp_path: Path) -> None:
        hgt = HorizontalGeneTransferEngine(tmp_path, ephemeral=False)
        try:
            def slow_dedup(items: list[int]) -> list[int]:
                out: list[int] = []
                for x in items:
                    if x not in out:
                        out.append(x)
                return out

            def fast_dedup(items: list[int]) -> list[int]:
                return list(dict.fromkeys(items))

            def buggy_dedup(items: list[int]) -> list[int]:
                return sorted(set(items))  # changes order -> parity mismatch

            cases = [
                [3, 1, 2, 3, 2, 4, 1, 5] * 20,
                [9, 8, 7, 6, 5, 9, 8] * 15,
                [],
                [42],
            ]

            ok_prop = hgt.sandbox_ab_graft(
                "singleflight_coalescer",
                "tquota-cache",
                slow_dedup,
                fast_dedup,
                cases,
                iterations=10,
            )
            assert ok_prop["parity_passed"] is True
            assert ok_prop["cases_matched"] == len(cases)
            assert ok_prop["speedup_ratio"] > 1.0
            assert ok_prop["verdict"] == "approve_candidate"
            # Law 6 hard invariant
            assert ok_prop["auto_activated"] is False
            assert ok_prop["requires_human_approval"] is True
            assert len(ok_prop["proposal_sha256"]) == 64

            bad_prop = hgt.sandbox_ab_graft(
                "singleflight_coalescer",
                "tquota-cache-buggy",
                slow_dedup,
                buggy_dedup,
                cases,
            )
            assert bad_prop["parity_passed"] is False
            assert bad_prop["verdict"] == "reject_parity_mismatch"
            assert bad_prop["auto_activated"] is False
            assert bad_prop["requires_human_approval"] is True
            assert len(hgt.list_proposals()) == 2
        finally:
            hgt.close()


# ---------------------------------------------------------------------------
# Idea #9: CHIMERA-MYCELIUM Tests
# ---------------------------------------------------------------------------


class _HTMLStructureValidator(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: list[str] = []
        self.attrs: list[tuple[str, str | None]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append(tag.lower())
        self.attrs.extend(attrs)


class TestMyceliumSporeMesh:
    def test_gf256_blind_split_and_reconstruct_all_pairs(self) -> None:
        secret = b"CHIMERA-TOP-SECRET-TOKEN:9780:svhome-guard-key-2026"
        shares = blind_split(secret, k=2, n=3)
        assert len(shares) == 3
        assert all(s["blinded"] is True for s in shares)

        # Single share MUST NOT leak plaintext substring and MUST NOT reconstruct alone
        for s in shares:
            raw_share = base64.b64decode(s["data_b64"])
            assert b"CHIMERA" not in raw_share
            assert b"SECRET" not in raw_share
            assert raw_share != secret
            with pytest.raises(ValueError, match="Need at least 2"):
                blind_reconstruct([s])

        # Every 2-of-3 pair MUST reconstruct bit-exact plaintext
        assert blind_reconstruct([shares[0], shares[1]]) == secret
        assert blind_reconstruct([shares[0], shares[2]]) == secret
        assert blind_reconstruct([shares[1], shares[2]]) == secret
        assert blind_reconstruct([shares[2], shares[0]]) == secret

        # Tampered share MUST be rejected by SHA-256 check
        bad = dict(shares[1])
        tampered_bytes = bytearray(base64.b64decode(bad["data_b64"]))
        tampered_bytes[0] ^= 0xFF
        bad["data_b64"] = base64.b64encode(bytes(tampered_bytes)).decode("ascii")
        with pytest.raises(ValueError, match="Corrupted share"):
            blind_reconstruct([shares[0], bad])

        # Empty payload edge case
        empty_shares = blind_split(b"", k=2, n=3)
        assert blind_reconstruct(empty_shares[:2]) == b""

    def test_spore_lifecycle_seed_inbox_and_sub_50ms_autotomy(self, tmp_path: Path) -> None:
        mesh = MyceliumSporeMesh(tmp_path, node_name="win-desktop", ephemeral=False)
        try:
            cred = mesh.issue_spore_token("pixel-9", role="mobile_pwa", ttl_s=1800)
            sid = cred["spore_id"]
            token = cred["token"]
            assert mesh.verify_spore_token(token)["valid"] is True

            att = mesh.attach_spore(
                sid, "pixel-9", role="mobile_pwa", capabilities=cred["capabilities"], host_hint="100.64.0.9", token=token
            )
            assert att["ok"] is True
            assert att["attached"] is True
            assert len(mesh.list_spores()) == 1

            hb = mesh.heartbeat_spore(sid, {"battery_pct": 88, "rtt_ms": 14.2})
            assert hb["ok"] is True
            assert mesh.list_spores()[0]["metrics"]["battery_pct"] == 88

            seed = mesh.submit_seed(sid, "Approve wal_group_commit graft for radar", priority="high")
            assert seed["ok"] is True
            assert len(mesh.list_seeds()) == 1
            assert mesh.list_seeds()[0]["text"].startswith("Approve wal_group_commit")

            # Instant < 50 ms Zero-Trace Autotomy
            receipt = mesh.autotomy(sid, reason="device_lost")
            assert receipt["elapsed_ms"] < 50.0
            assert receipt["zero_trace_verified"] is True
            assert receipt["state_dropped"] is True
            assert receipt["ephemeral_keys_zeroed_bytes"] == 32
            assert receipt["revoked_tokens"] >= 1
            assert len(receipt["receipt_sha256"]) == 64

            # Post-autotomy invariants: token invalid, spore vanished, re-attach/seed blocked
            assert mesh.verify_spore_token(token)["valid"] is False
            assert mesh.list_spores() == []
            assert mesh.attach_spore(sid, "pixel-9")["attached"] is False
            assert mesh.submit_seed(sid, "late seed")["ok"] is False
            assert len(mesh.list_autotomy_receipts()) == 1
        finally:
            mesh.close()

    def test_pwa_html_under_50kb_valid_zero_external_urls(self) -> None:
        snapshot = {
            "hormones": {
                "levels": {
                    "adrenaline": 0.35,
                    "cortisol": 0.12,
                    "dopamine": 0.82,
                    "melatonin": 0.05,
                    "cytokine": 0.08,
                    "oxytocin": 0.91,
                }
            },
            "umwelt": {"assessment": {"state": "deep_flow", "flow_score": 0.88, "flow_shield": True}},
            "soul": {"lineage_hash": "abcdef0123456789", "scar_count": 4},
        }
        html = render_spore_pwa_html(anchor_url="", snapshot=snapshot)
        raw_bytes = html.encode("utf-8")
        assert len(raw_bytes) < MAX_PWA_BYTES
        assert len(raw_bytes) < 25 * 1024  # Target < 25 KB

        # Valid HTML5 structure
        assert html.lower().startswith("<!doctype html>")
        parser = _HTMLStructureValidator()
        parser.feed(html)
        for required_tag in ("html", "head", "body", "style", "script", "header", "form"):
            assert required_tag in parser.tags

        # ZERO external URLs / CDNs / WebGL
        assert not re.search(r"https?://", html, flags=re.IGNORECASE)
        assert "webgl" not in html.lower()
        assert "requestanimationframe" not in html.lower()

        # Connects to live BIOS endpoints & displays all 6 hormones
        for endpoint in ("/v1/bios/status", "/v1/bios/stream", "/v1/bios/spore/seed", "/v1/bios/spore/autotomy"):
            assert endpoint in html
        for hormone in ("adrenaline", "cortisol", "dopamine", "melatonin", "cytokine", "oxytocin"):
            assert hormone in html
        # Renders both full scar records (severity/lesson_law) and compact capsule scars (sev/lesson)
        assert "s.severity||s.sev" in html
        assert "s.lesson_law||s.lesson" in html

        # Embed a real Soul capsule snapshot and confirm compact keys survive under 25 KB
        soul = AutobiographicalSoul(ephemeral=True)
        try:
            cap = soul.export_capsule(max_tokens=360)
            html_with_cap = render_spore_pwa_html(snapshot={"soul": {"capsule": cap, "scar_count": 4}})
            assert len(html_with_cap.encode("utf-8")) < 25 * 1024
            assert cap["lineage_hash"] in html_with_cap
            m_snap = re.search(r"var SNAP=(\{.*?\});\n", html_with_cap)
            assert m_snap is not None
            parsed_snap = json.loads(m_snap.group(1))
            first_scar = parsed_snap["soul"]["capsule"]["relevant_scars"][0]
            assert first_scar["lesson"] == cap["relevant_scars"][0]["lesson"]
            assert first_scar["sev"] in ("critical", "high", "medium", "low")
            assert first_scar["sev"] == cap["relevant_scars"][0]["sev"]
        finally:
            soul.close()


# ---------------------------------------------------------------------------
# Idea #10: CHIMERA-SOUL Tests
# ---------------------------------------------------------------------------


class TestAutobiographicalSoul:
    def test_genesis_scars_idempotent_and_hash_chain_verified(self, tmp_path: Path) -> None:
        soul = AutobiographicalSoul(tmp_path, ephemeral=False)
        try:
            scars = soul.list_scars()
            assert len(scars) == 4
            titles = " | ".join(s["title"] for s in scars)
            assert "0xF00" in titles
            assert "svhome" in titles
            assert "80 MiB" in titles
            assert ":12500" in titles

            ver = soul.verify_lineage()
            assert ver["valid"] is True
            assert ver["scar_count"] == 4
            assert len(ver["head_hash"]) == 64

            # Record a new scar and verify chaining
            new_scar = soul.record_scar(
                title="NVMe Mirage Write-Amp Lesson",
                event_date="2026-11-27",
                root_cause="Unbatched SQLite writes amplified SSD wear.",
                lesson_law="Group-commit telemetry batches to minimize SSD wear.",
                hardware_context="win-desktop NVMe",
                tags=["ssd", "wal", "nvme"],
                severity="high",
            )
            assert new_scar["seq"] == 5
            assert new_scar["prev_hash"] == ver["head_hash"]
            assert soul.verify_lineage()["valid"] is True
        finally:
            soul.close()

        # Re-opening must be idempotent (must NOT duplicate genesis scars)
        soul2 = AutobiographicalSoul(tmp_path, ephemeral=False)
        try:
            assert len(soul2.list_scars()) == 5
            assert soul2.verify_lineage()["valid"] is True
        finally:
            soul2.close()

        # Direct SQLite tampering MUST break verify_lineage()!
        db_file = tmp_path / "bios_soul.sqlite3"
        conn = sqlite3.connect(str(db_file))
        conn.execute("UPDATE scars SET lesson_law = 'TAMPERED LAW' WHERE seq = 2")
        conn.commit()
        conn.close()

        soul3 = AutobiographicalSoul(tmp_path, ephemeral=False)
        try:
            tampered = soul3.verify_lineage()
            assert tampered["valid"] is False
            assert tampered["broken_seq"] == 2
            assert len(tampered["errors"]) >= 1
        finally:
            soul3.close()

    def test_10k_vsa_recall_finds_relevant_scars(self) -> None:
        v1 = vsa_encode_10k("svhome 15W thermal protection peer guard")
        v2 = vsa_encode_10k("svhome thermal 15W weak node guard")
        v3 = vsa_encode_10k("completely unrelated banana recipe")
        assert vsa_similarity_10k(v1, v2) > vsa_similarity_10k(v1, v3)

        soul = AutobiographicalSoul(ephemeral=True)
        try:
            top_svh = soul.recall_scars("svhome 15W thermal guard", top_k=2)
            assert "svhome" in top_svh[0]["title"].lower()

            top_rss = soul.recall_scars("daemon RSS 80 MiB lazy load", top_k=2)
            assert "80 mib" in top_rss[0]["title"].lower()

            top_sock = soul.recall_scars("12500 immortal socket reconnect", top_k=2)
            assert "12500" in top_sock[0]["title"]
        finally:
            soul.close()

    def test_export_capsule_under_500_tokens_and_model_agnostic(self) -> None:
        soul = AutobiographicalSoul(ephemeral=True)
        try:
            soul.record_preference("coding", "style", "minimal surgical edits", evidence="core principle")

            models = ("gemini", "codex", "claude", "local-qwen", "any")
            capsules = [
                soul.export_capsule(query="svhome thermal and RSS ceiling", target_model=m, max_tokens=500)
                for m in models
            ]

            core_hashes = {c["core_sha256"] for c in capsules}
            lineage_hashes = {c["lineage_hash"] for c in capsules}
            # Model-agnostic continuity: every LLM inherits the EXACT same soul core & lineage
            assert len(core_hashes) == 1
            assert len(lineage_hashes) == 1

            for model, cap in zip(models, capsules):
                assert cap["target_model"] == model
                assert cap["token_est"] <= 500
                assert cap["lineage_valid"] is True
                assert AutobiographicalSoul.verify_capsule(cap) is True
                assert cap["identity"]["name"] == "CHIMERA-ONE"
                assert len(cap["active_laws"]) >= 5
                assert len(cap["relevant_scars"]) >= 2
                # Independent conservative length sanity check
                assert len(json.dumps(cap, separators=(",", ":"))) <= 500 * 4

            # Tight token budget test (e.g., max_tokens=180)
            tight = soul.export_capsule(query="law 2", target_model="local", max_tokens=180)
            assert tight["token_est"] <= 180
            assert AutobiographicalSoul.verify_capsule(tight) is True
        finally:
            soul.close()

    def test_export_capsule_5_scars_boundary_model_name_invariant(self) -> None:
        """Regression test for Section 5.1: 5+ scars near 500-token ceiling must yield
        identical core_sha256 and lineage_hash regardless of target_model name length."""
        soul = AutobiographicalSoul(ephemeral=True)
        try:
            soul.record_preference("coding", "style", "minimal surgical edits", evidence="core principle")
            fifth = soul.record_scar(
                title="BIOS Evaluation Verification Scar",
                event_date="2026-11-27",
                root_cause="Synthetic benchmark lineage continuity check.",
                lesson_law="Always verify SHA-256 lineage and <=500 token budget across models.",
                hardware_context="win-desktop + svhome",
                tags=["bios", "soul", "law7"],
                severity="high",
            )
            assert fifth["seq"] == 5
            assert soul.verify_lineage()["valid"] is True

            models = ("gemini", "codex", "claude", "local-qwen", "gpt-5-codex", "any")
            query = "svhome 15W thermal and 80 MiB RSS"

            # Exact 500-token ceiling (previously diverged between gemini/codex/claude/any and local-qwen)
            capsules = [
                soul.export_capsule(query=query, target_model=m, max_tokens=500)
                for m in models
            ]
            assert len({c["core_sha256"] for c in capsules}) == 1
            assert len({c["lineage_hash"] for c in capsules}) == 1
            for model, cap in zip(models, capsules):
                assert cap["target_model"] == model
                assert cap["token_est"] <= 500
                assert cap["lineage_valid"] is True
                assert cap["identity"]["scar_count"] == 5
                assert AutobiographicalSoul.verify_capsule(cap) is True

            # Sweep boundary ceilings across the Stage-1 / Stage-2 compaction cliff
            for ceiling in (460, 495, 499, 500, 501, 505, 510):
                swept = [
                    soul.export_capsule(query=query, target_model=m, max_tokens=ceiling)
                    for m in models
                ]
                assert len({c["core_sha256"] for c in swept}) == 1
                assert len({c["lineage_hash"] for c in swept}) == 1
                assert all(c["token_est"] <= ceiling for c in swept)
                assert all(AutobiographicalSoul.verify_capsule(c) for c in swept)

            # Oversized custom model name (>32 chars) still strictly obeys token_est <= 500
            long_model = "custom-org/ultra-long-local-qwen-2.5-coder-32b-instruct-q4_k_m"
            long_cap = soul.export_capsule(query=query, target_model=long_model, max_tokens=500)
            assert long_cap["target_model"] == long_model
            assert long_cap["token_est"] <= 500
            assert long_cap["lineage_hash"] == capsules[0]["lineage_hash"]
            assert AutobiographicalSoul.verify_capsule(long_cap) is True
        finally:
            soul.close()

    def test_starter_plasmids_are_real_executable_stdlib_code(self) -> None:
        hgt = HorizontalGeneTransferEngine(ephemeral=True)
        try:
            # Verify all 3 starter plasmids execute cleanly in an isolated namespace
            for name in ("singleflight_coalescer", "wal_group_commit", "zero_alloc_ring_codec"):
                p = hgt.get_plasmid(name)
                assert p is not None
                ns: dict = {}
                exec(compile(p["code_snippet"], f"<plasmid:{name}>", "exec"), ns, ns)
                if name == "singleflight_coalescer":
                    sf = ns["SingleflightCoalescer"]()
                    assert sf.do("k1", lambda: 12345) == 12345
                elif name == "wal_group_commit":
                    conn = sqlite3.connect(":memory:")
                    conn.execute("CREATE TABLE t (x INT)")
                    buf = ns["WalGroupCommitBuffer"](conn, "INSERT INTO t VALUES (?)", max_batch=2)
                    assert buf.enqueue((1,)) == 0
                    assert buf.enqueue((2,)) == 2
                    assert conn.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 2
                    conn.close()
                elif name == "zero_alloc_ring_codec":
                    ring = ns["ZeroAllocRingCodec"](slots=8)
                    ring.write_slot(3, 99, 7, 1.5)
                    seq, kind, val = ring.read_slot(3)
                    assert (seq, kind) == (99, 7)
                    assert abs(val - 1.5) < 1e-6
        finally:
            hgt.close()

