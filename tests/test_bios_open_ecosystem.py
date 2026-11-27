"""End-to-end integration tests for CHIMERA-BIOS Open Ecosystem Soul (Hub, HTTP/SSE/PWA, SDK, MCP, CLI, Noosphere, Laws 1-7)."""

from __future__ import annotations

import contextlib
import io
import json
import re
import subprocess
import sys
import tempfile
import time
import tracemalloc
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from chimera_tp.autopilot import OpsConfig
from chimera_tp.cli import main as cli_main
from chimera_tp.dashboard import ChimeraDaemon
from chimera_tp.platform.client import connect
from chimera_tp.platform.discovery import write_agents_infra_doc
from chimera_tp.platform.mcp_server import _TOOLS, handle_mcp_request
from chimera_tp.platform.noosphere_organism import NoosphereOrganismCore


class TestChimeraBiosOpenEcosystem(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="chimera_bios_eco_")
        self.ops_dir = Path(self._tmp.name) / "ops"
        cfg = OpsConfig(
            node_name="bios-test-node",
            role="controller",
            dashboard_bind="127.0.0.1:0",
            beam_port=0,
            rpc_v4_port=0,
            rpc_v6_port=-1,
            query_port=0,
            warp_port=-1,
            edge_proxy_port=-1,
            allowed_query_roots=[self._tmp.name],
            search_roots=[self._tmp.name],
            edge_targets={},
            phantom_enabled=False,
        )
        self.daemon = ChimeraDaemon(config=cfg, ops_dir=self.ops_dir, auto_seed_on_empty=False).start()
        self.anchor = self.daemon.platform.anchor_url
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def tearDown(self) -> None:
        self.daemon.close()
        self._tmp.cleanup()

    def _get_json(self, path: str, timeout: float = 10.0) -> tuple[int, dict]:
        with self._opener.open(f"{self.anchor}{path}", timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8"))

    def _post_json(self, path: str, body: dict, timeout: float = 20.0) -> tuple[int, dict]:
        req = urllib.request.Request(
            f"{self.anchor}{path}",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with self._opener.open(req, timeout=timeout) as r:
                return r.status, json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    # ------------------------------------------------------------------
    # 1. Law 7: 0 B Startup RSS Lazy-Load Verification
    # ------------------------------------------------------------------
    def test_01_law7_zero_boot_rss_lazy_load_and_well_known_discovery(self) -> None:
        # Subprocess cold import check: importing chimera_tp & PlatformSubstrate MUST NOT import bios
        code = (
            "import json, sys; "
            "import chimera_tp; "
            "import chimera_tp.platform.substrate as sub; "
            "loaded = [m for m in sys.modules if 'platform.bios' in m]; "
            "print(json.dumps({'bios_modules': loaded}))"
        )
        proc = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            timeout=20,
            check=True,
        )
        info = json.loads(proc.stdout.strip())
        self.assertEqual(info["bios_modules"], [], f"BIOS eagerly imported on cold boot: {info['bios_modules']}")

        # Live daemon must keep _bios = None even after /.well-known/chimera.json discovery
        self.assertIsNone(self.daemon.platform._bios)
        sc, caps = self._get_json("/.well-known/chimera.json")
        self.assertEqual(sc, 200)
        self.assertIn("bios", caps["cartridges"])
        bios_cart = caps["cartridges"]["bios"]
        self.assertEqual(bios_cart["status"], "lazy_ready")
        self.assertTrue(bios_cart["lazy_loaded"])
        self.assertEqual(bios_cart["endpoint"], f"{self.anchor}/v1/bios")
        self.assertEqual(bios_cart["abi_endpoint"], f"{self.anchor}/v1/bios/abi")
        self.assertEqual(bios_cart["nixl_endocrine_offset"], 32)
        self.assertEqual(bios_cart["organs_count"], 10)
        self.assertIsNone(self.daemon.platform._bios)

        # First /v1/bios/status lazily instantiates ChimeraBiosOrganism
        sc2, st = self._get_json("/v1/bios/status")
        self.assertEqual(sc2, 200)
        self.assertTrue(st["ok"])
        self.assertEqual(st["organs_count"], 10)
        self.assertEqual(len(st["organs"]), 10)
        self.assertTrue(st["law2_compliant"])
        self.assertFalse(st["law6_auto_activated"])
        self.assertIsNotNone(self.daemon.platform._bios)

        # Capabilities now reports active
        _, caps2 = self._get_json("/.well-known/chimera.json")
        self.assertEqual(caps2["cartridges"]["bios"]["status"], "active")
        self.assertFalse(caps2["cartridges"]["bios"]["lazy_loaded"])

    # ------------------------------------------------------------------
    # 2. All /v1/bios/* HTTP/JSON Routes End-to-End
    # ------------------------------------------------------------------
    def test_02_all_bios_http_json_routes_end_to_end(self) -> None:
        # ABI manifest
        sc, abi = self._get_json("/v1/bios/abi")
        self.assertEqual(sc, 200)
        self.assertEqual(abi["schema"], "chimera.bios.open_abi.v1")
        self.assertEqual(abi["binary_abi"]["nixl_mmap"]["endocrine_block"]["offset"], 32)
        self.assertEqual(abi["binary_abi"]["nixl_mmap"]["endocrine_block"]["struct_fmt"], "<4sHH6f")
        self.assertEqual(abi["binary_abi"]["phantom_wire_12b"]["struct_fmt"], "<6H")
        for lang in ("python", "nodejs", "rust", "curl"):
            self.assertIn(lang, abi["sdk_examples"])
        self.assertIn("sync_bundle", abi["endpoints"])
        self.assertIn("sync", abi["endpoints"])
        self.assertIn("sync", abi["cli_subcommands"])

        # Hormones GET & POST (secrete, trust, inflame)
        sc, h0 = self._get_json("/v1/bios/hormones")
        self.assertEqual(sc, 200)
        self.assertEqual(len(h0["wire_12b_hex"]), 24)
        sc, h_sec = self._post_json("/v1/bios/hormones", {"hormone": "adrenaline", "delta": 0.25, "source": "test"})
        self.assertEqual(sc, 200)
        self.assertTrue(h_sec["ok"])
        sc, h_tr = self._post_json("/v1/bios/hormones", {"action": "trust", "app_id": "autocad", "delta": 0.15, "reason": "verified"})
        self.assertEqual(sc, 200)
        self.assertTrue(h_tr["ok"])
        sc, h_inf = self._post_json("/v1/bios/hormones", {"action": "inflame", "locus": "chimera_tp/cli.py", "intensity": 0.6, "reason": "flaky"})
        self.assertEqual(sc, 200)
        self.assertTrue(h_inf["ok"])
        sc, h_clr = self._post_json("/v1/bios/hormones", {"action": "clear_inflammation", "locus": "chimera_tp/cli.py"})
        self.assertEqual(sc, 200)
        self.assertIsInstance(h_clr, dict)
        self.assertTrue(h_clr["ok"])
        self.assertEqual(h_clr["action"], "clear_inflammation")
        self.assertTrue(h_clr["cleared"])
        self.assertIn("hormones", h_clr)
        self.assertIn("directives", h_clr)

        # Pulse closed-loop physiology tick
        sc, pulse = self._post_json("/v1/bios/pulse", {"obs": {"cpu_pct": 38.0, "gpu_pct": 12.0}, "context": "coding"})
        self.assertEqual(sc, 200)
        self.assertTrue(pulse["ok"])
        self.assertEqual(pulse["event"], "bios_pulse")
        self.assertIn("levels", pulse["hormones"])
        self.assertIn("directives", pulse)
        self.assertTrue(pulse["law2_compliant"])
        self.assertFalse(pulse["law6_auto_activated"])

        # Friston predict
        sc, pred = self._post_json(
            "/v1/bios/predict",
            {"obs": {"cpu_pct": 80.0, "gpu_pct": 70.0}, "context": "cad", "horizon_s": 60.0},
        )
        self.assertEqual(sc, 200)
        self.assertTrue(pred["ok"])
        self.assertIn("forecast", pred)
        self.assertIn("actions", pred)
        self.assertFalse(pred["auto_activated"])

        # Autophagy GET & POST (record + Law-6 Apoptosis proposal)
        sc, au0 = self._get_json("/v1/bios/autophagy")
        self.assertEqual(sc, 200)
        sc, au_rec = self._post_json(
            "/v1/bios/autophagy",
            {"action": "record", "entity_id": "bios.test_route", "kind": "route", "ms_saved": 4.2, "tokens_saved": 120},
        )
        self.assertEqual(sc, 200)
        self.assertTrue(au_rec.get("ok", True))
        sc, au_prop = self._post_json("/v1/bios/autophagy", {"action": "propose_apoptosis", "max_candidates": 5})
        self.assertEqual(sc, 200)
        self.assertFalse(au_prop["auto_activated"])
        self.assertTrue(au_prop["requires_human_approval"])

        # Parasite Red-Queen arena
        sc, p_run = self._post_json("/v1/bios/parasite/run", {"rounds": 3, "seed": 42})
        self.assertEqual(sc, 200)
        self.assertFalse(p_run.get("auto_activated", False))
        sc, p_st = self._get_json("/v1/bios/parasite/status")
        self.assertEqual(sc, 200)
        self.assertIn("recent_vaccines", p_st)

        # Octopus ganglia & Merkle-CRDT reconciliation
        sc, g_st = self._get_json("/v1/bios/ganglia")
        self.assertEqual(sc, 200)
        ev_a = {"event_id": "e1", "node_id": "win-desktop", "kind": "alarm", "payload": {"k": 1}, "hlc": [100, 0, "win-desktop"]}
        ev_b = {"event_id": "e2", "node_id": "svhome", "kind": "alarm", "payload": {"k": 2}, "hlc": [101, 0, "svhome"]}
        sc, r1 = self._post_json("/v1/bios/ganglia/reconcile", {"local_events": [ev_a], "peer_events": [ev_b]})
        self.assertEqual(sc, 200)
        sc, r2 = self._post_json("/v1/bios/ganglia/reconcile", {"local_events": [ev_b], "peer_events": [ev_a]})
        self.assertEqual(sc, 200)
        self.assertEqual(r1["merkle_root"], r2["merkle_root"])

        # Stigmergy pheromone alarm + coedit + smell-card (<40 tokens)
        sc, ph_mut = self._post_json(
            "/v1/bios/pheromone",
            {
                "repo": "chimera-tp",
                "rel_path": "chimera_tp/cli.py",
                "alarm": {"signal_kind": "regression", "severity": 0.75, "reason": "cli_flag_drift"},
                "coedits": ["chimera_tp/cli.py", "tests/test_bios_open_ecosystem.py"],
                "methylation": {"gene_policy": "extra_verify", "strength": 0.85, "reason": "high_fanout"},
            },
        )
        self.assertEqual(sc, 200)
        self.assertLessEqual(ph_mut["token_est"], 40)
        sc, ph_get = self._get_json("/v1/bios/pheromone?repo=chimera-tp&rel_path=chimera_tp/cli.py")
        self.assertEqual(sc, 200)
        self.assertGreater(ph_get["alarm_level"], 0.0)
        self.assertLessEqual(ph_get["token_est"], 40)

        # Umwelt passive signal & assess
        sc, um_post = self._post_json(
            "/v1/bios/umwelt",
            {"signal": {"event_kind": "edit", "app": "vscode", "target": "organism.py", "ok": True}},
        )
        self.assertEqual(sc, 200)
        self.assertTrue(um_post["ok"])
        sc, um_get = self._get_json("/v1/bios/umwelt")
        self.assertEqual(sc, 200)
        self.assertIn("assessment", um_get)

        # HGT list, scan, and Law-6 graft proposal
        sc, hgt_l = self._get_json("/v1/bios/hgt")
        self.assertEqual(sc, 200)
        self.assertGreaterEqual(hgt_l["count"], 3)
        sc, hgt_g = self._post_json(
            "/v1/bios/hgt",
            {"action": "graft", "plasmid_id": "singleflight_coalescer", "target_name": "demo_svc"},
        )
        self.assertEqual(sc, 200)
        self.assertFalse(hgt_g["auto_activated"])
        self.assertTrue(hgt_g["requires_human_approval"])
        # Unknown plasmid cleanly returns HTTP 404 JSON (never disconnects on KeyError)
        sc, hgt_404 = self._post_json(
            "/v1/bios/hgt",
            {"action": "scan", "plasmid_id": "no_such_plasmid"},
        )
        self.assertEqual(sc, 404)
        self.assertFalse(hgt_404["ok"])
        self.assertIn("no_such_plasmid", hgt_404["error"])

        # Mycelium Spore attach -> seed -> list -> autotomy (<50ms)
        sc, sp_att = self._post_json("/v1/bios/spore/attach", {"device_name": "pixel-9", "role": "mobile_pwa"})
        self.assertEqual(sc, 200)
        self.assertTrue(sp_att["ok"])
        spore_id = sp_att["spore"]["spore_id"]
        sc, sp_seed = self._post_json("/v1/bios/spore/seed", {"spore_id": spore_id, "text": "Approve graft PR #7", "priority": "high"})
        self.assertEqual(sc, 200)
        self.assertTrue(sp_seed.get("ok", True))
        sc, sp_list = self._get_json("/v1/bios/spores")
        self.assertEqual(sc, 200)
        self.assertGreaterEqual(len(sp_list["spores"]), 1)
        sc, sp_auto = self._post_json("/v1/bios/spore/autotomy", {"spore_id": spore_id, "reason": "test_detach"})
        self.assertEqual(sc, 200)
        self.assertTrue(sp_auto["ok"])
        self.assertLess(sp_auto["elapsed_ms"], 50.0)

        # Soul capsule (<= 500 tokens) & scar recording
        sc, soul0 = self._get_json("/v1/bios/soul?query=law%207%20rss&target_model=claude&max_tokens=500")
        self.assertEqual(sc, 200)
        self.assertTrue(soul0["ok"])
        self.assertLessEqual(soul0["token_est"], 500)
        self.assertTrue(soul0["lineage"]["valid"])
        sc, scar_res = self._post_json(
            "/v1/bios/soul/scar",
            {
                "title": "SSE EventSource onmessage contract",
                "event_date": "2026-11-27",
                "root_cause": "Named event lines bypass default onmessage handler",
                "lesson_law": "Send default SSE data frames with JSON event field",
                "tags": ["sse", "pwa"],
            },
        )
        self.assertEqual(sc, 200)
        self.assertTrue(scar_res.get("ok", True))
        _, soul1 = self._get_json("/v1/bios/soul?query=SSE%20EventSource&target_model=gemini")
        self.assertTrue(soul1["lineage"]["valid"])
        self.assertNotEqual(soul0["lineage_hash"], soul1["lineage_hash"])

    # ------------------------------------------------------------------
    # 3. Spore PWA HTML (< 50 KB) & Live SSE Stream (/v1/bios/stream)
    # ------------------------------------------------------------------
    def test_03_spore_pwa_html_and_sse_stream_routes(self) -> None:
        with self._opener.open(f"{self.anchor}/v1/bios/spore", timeout=5.0) as r:
            self.assertEqual(r.status, 200)
            ctype = str(r.headers.get("Content-Type") or "")
            self.assertIn("text/html", ctype.lower())
            raw_html = r.read()
        self.assertLess(len(raw_html), 50 * 1024, f"Spore PWA exceeded 50 KB: {len(raw_html)} B")
        html_txt = raw_html.decode("utf-8")
        self.assertIn("<!doctype html>", html_txt.lower())
        self.assertIn("/v1/bios/stream", html_txt)
        # Zero external CDN URLs
        self.assertIsNone(re.search(r"https?://", html_txt))

        # Bounded SSE stream (?max_events=2&interval_ms=25)
        t0 = time.perf_counter()
        with self._opener.open(f"{self.anchor}/v1/bios/stream?max_events=2&interval_ms=25", timeout=8.0) as r:
            self.assertEqual(r.status, 200)
            self.assertIn("text/event-stream", str(r.headers.get("Content-Type") or "").lower())
            sse_raw = r.read().decode("utf-8")
        elapsed_s = time.perf_counter() - t0
        self.assertLess(elapsed_s, 5.0)
        data_lines = [ln[len("data:"):].strip() for ln in sse_raw.splitlines() if ln.startswith("data:")]
        self.assertEqual(len(data_lines), 2)
        for dl in data_lines:
            ev = json.loads(dl)
            self.assertEqual(ev["event"], "bios_pulse")
            self.assertIn("levels", ev["hormones"])

        # Single-shot SSE (?once=1)
        with self._opener.open(f"{self.anchor}/v1/bios/stream?once=1", timeout=5.0) as r:
            once_raw = r.read().decode("utf-8")
        once_lines = [ln for ln in once_raw.splitlines() if ln.startswith("data:")]
        self.assertEqual(len(once_lines), 1)

    # ------------------------------------------------------------------
    # 4. ChimeraClient Online AND Offline Fallback (All 13 SDK Methods)
    # ------------------------------------------------------------------
    def test_04_client_sdk_online_and_offline_fallback(self) -> None:
        online = connect(app="eco-online", anchor_url=self.anchor, auto_register=False)
        self.assertTrue(online.available)
        self.assertTrue(online.bios_status()["ok"])
        self.assertEqual(online.bios_abi()["schema"], "chimera.bios.open_abi.v1")
        self.assertTrue(online.bios_hormones()["ok"])
        self.assertTrue(online.bios_hormones(secrete={"hormone": "dopamine", "delta": 0.1})["ok"])
        self.assertEqual(online.bios_pulse(obs={"cpu_pct": 25.0}, context="coding")["event"], "bios_pulse")
        self.assertTrue(online.bios_predict({"cpu_pct": 30.0}, context="coding", horizon_s=60.0)["ok"])
        self.assertLessEqual(online.bios_pheromone(".", "chimera_tp/cli.py", alarm={"signal_kind": "warn", "severity": 0.4})["token_est"], 40)
        self.assertTrue(online.bios_umwelt(signal={"event_kind": "cad_cmd", "app": "acad.exe", "target": "plan.dwg"})["ok"])
        self.assertLessEqual(online.bios_soul(query="law 2", target_model="codex", max_tokens=500)["token_est"], 500)
        self.assertTrue(online.bios_autophagy(action="status")["ok"] if "ok" in online.bios_autophagy(action="status") else True)
        self.assertFalse(online.bios_parasite(rounds=2).get("auto_activated", False))
        self.assertGreaterEqual(online.bios_hgt(action="list")["count"], 3)
        self.assertIn("spores", online.bios_spore(action="list"))
        self.assertIn("reflex_table", online.bios_ganglia(action="status"))

        # Offline fallback: unreachable anchor must NEVER raise and must still work gracefully
        offline = connect(app="eco-offline", anchor_url="http://127.0.0.1:1", auto_register=False)
        self.assertFalse(offline.available)
        for res in (
            offline.bios_status(),
            offline.bios_abi(),
            offline.bios_hormones(),
            offline.bios_pulse(obs={"cpu_pct": 15.0}, context="idle"),
            offline.bios_predict({"cpu_pct": 15.0}, context="idle", horizon_s=30.0),
            offline.bios_pheromone(".", "offline.py"),
            offline.bios_umwelt(),
            offline.bios_soul(query="law 7", target_model="gemini", max_tokens=500),
            offline.bios_autophagy(action="status"),
            offline.bios_parasite(rounds=2),
            offline.bios_hgt(action="list"),
            offline.bios_spore(action="list"),
            offline.bios_ganglia(action="status"),
        ):
            self.assertIsInstance(res, dict)
            self.assertTrue(res.get("ok", True))
            self.assertTrue(res.get("offline_fallback"))

    # ------------------------------------------------------------------
    # 5. MCP Server Tools (5 BIOS tools)
    # ------------------------------------------------------------------
    def test_05_mcp_bios_tools_online_and_offline(self) -> None:
        names = [t["name"] for t in _TOOLS]
        expected_bios = [
            "chimera_bios_status",
            "chimera_bios_hormones",
            "chimera_bios_pheromone",
            "chimera_bios_soul",
            "chimera_bios_evolve",
        ]
        for tn in expected_bios:
            self.assertIn(tn, names)

        calls = [
            ("chimera_bios_status", {"include_abi": True}),
            ("chimera_bios_hormones", {"action": "secrete", "hormone": "dopamine", "delta": 0.05}),
            ("chimera_bios_pheromone", {"repo": "chimera-tp", "rel_path": "chimera_tp/cli.py", "action": "smell"}),
            ("chimera_bios_soul", {"action": "capsule", "query": "law 3 svhome", "target_model": "claude", "max_tokens": 500}),
            ("chimera_bios_evolve", {"action": "pulse", "context": "coding", "obs": {"cpu_pct": 33.0}}),
            ("chimera_bios_evolve", {"action": "hgt", "sub_action": "list"}),
        ]
        for idx, (tool_name, args) in enumerate(calls, start=1):
            resp = handle_mcp_request(
                {"jsonrpc": "2.0", "id": 500 + idx, "method": "tools/call", "params": {"name": tool_name, "arguments": args}},
                anchor_url=self.anchor,
            )
            self.assertIsNotNone(resp)
            assert resp is not None
            self.assertFalse(resp["result"].get("isError", False), f"MCP error on {tool_name}: {resp}")
            parsed = json.loads(resp["result"]["content"][0]["text"])
            self.assertIsInstance(parsed, dict)

        # Offline MCP call still succeeds cleanly
        off_resp = handle_mcp_request(
            {"jsonrpc": "2.0", "id": 599, "method": "tools/call", "params": {"name": "chimera_bios_soul", "arguments": {"query": "law 7"}}},
            anchor_url="http://127.0.0.1:1",
        )
        self.assertIsNotNone(off_resp)
        assert off_resp is not None
        off_body = json.loads(off_resp["result"]["content"][0]["text"])
        self.assertTrue(off_body["ok"])
        self.assertLessEqual(off_body["token_est"], 500)

    # ------------------------------------------------------------------
    # 6. CLI `chimera-tp bios` Subcommands
    # ------------------------------------------------------------------
    def test_06_cli_bios_status_soul_and_local_pulse(self) -> None:
        for argv in (
            ["bios", "status", "--anchor", self.anchor],
            ["bios", "abi", "--anchor", self.anchor],
            ["bios", "soul", "--anchor", self.anchor, "--query", "law 7 rss", "--model", "gemini"],
            ["bios", "hormones", "--anchor", self.anchor, "--sub-action", "clear_inflammation", "--payload", '{"locus":"a.py"}'],
            ["bios", "pulse", "--local", "--context", "coding"],
        ):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = cli_main(argv)
            self.assertEqual(rc, 0, f"CLI failed for {argv}: {buf.getvalue()}")
            data = json.loads(buf.getvalue())
            self.assertIsInstance(data, dict)
            self.assertTrue(data.get("ok", True))

    # ------------------------------------------------------------------
    # 7. Discovery Doc + Noosphere Lazy Bridge + Memory Ceiling (< 3 MiB)
    # ------------------------------------------------------------------
    def test_07_discovery_doc_noosphere_bridge_and_memory_budget(self) -> None:
        _, caps = self._get_json("/.well-known/chimera.json")
        out_doc = Path(self._tmp.name) / "AGENTS_INFRA.md"
        write_agents_infra_doc(caps, out_path=out_doc)
        doc_txt = out_doc.read_text(encoding="utf-8")
        for needle in (
            "/v1/bios/abi",
            "/v1/bios/hormones",
            "/v1/bios/pheromone",
            "/v1/bios/soul",
            "/v1/bios/spore",
            "32..63",
            "brain.bios_",
        ):
            self.assertIn(needle, doc_txt)

        # Noosphere bridge: inactive when bios=None, active once attached
        noo = NoosphereOrganismCore(ephemeral=True)
        try:
            t_no_bios = noo.tick(trigger="unit_test", sample_network=False, rss_override_mb=50.0)
            self.assertIsNone(t_no_bios["bios"])
            self.assertFalse(noo.status()["bios"]["active"])

            # Attach active ChimeraBiosOrganism and measure working memory
            from chimera_tp.platform.bios.organism import ChimeraBiosOrganism

            tracemalloc.start()
            try:
                bios = ChimeraBiosOrganism(ops_dir=self.ops_dir / "mem_bios", ephemeral=True)
                noo.attach_bios(bios)
                t_with_bios = noo.tick(trigger="unit_test", sample_network=False, rss_override_mb=54.0)
                st_with_bios = noo.status()
                bios_st = bios.status()
                cur_b, peak_b = tracemalloc.get_traced_memory()
                bios.close()
            finally:
                tracemalloc.stop()

            self.assertIsNotNone(t_with_bios["bios"])
            self.assertTrue(t_with_bios["bios"]["ok"])
            self.assertIn("levels", t_with_bios["bios"]["hormones"])
            self.assertTrue(st_with_bios["bios"]["active"])
            self.assertIsNotNone(st_with_bios["bios"]["hormones"])
            self.assertEqual(bios_st["organs_count"], 10)
            self.assertLess(peak_b / (1024.0 * 1024.0), 3.0, f"BIOS peak tracemalloc exceeded 3 MiB: {peak_b / (1024*1024):.2f} MiB")
        finally:
            noo.close()

    # ------------------------------------------------------------------
    # 8. Real 2-Daemon End-to-End 2-Way Bidirectional BIOS Sync (win <-> svhome)
    # ------------------------------------------------------------------
    def test_08_two_daemon_bidirectional_bios_sync_and_convergence(self) -> None:
        from chimera_tp.platform.bios.endocrine import read_endocrine_block_mmap

        with tempfile.TemporaryDirectory(prefix="chimera_bios_sync_2way_") as td:
            root_p = Path(td)
            ops_win = root_p / "ops_win"
            ops_svh = root_p / "ops_svhome"

            cfg_win = OpsConfig(
                node_name="node-win",
                role="controller",
                dashboard_bind="127.0.0.1:0",
                beam_port=0,
                rpc_v4_port=0,
                rpc_v6_port=-1,
                query_port=0,
                warp_port=-1,
                edge_proxy_port=-1,
                allowed_query_roots=[td],
                search_roots=[td],
                edge_targets={},
                phantom_enabled=False,
            )
            cfg_svh = OpsConfig(
                node_name="node-svhome",
                role="node",
                dashboard_bind="127.0.0.1:0",
                beam_port=0,
                rpc_v4_port=0,
                rpc_v6_port=-1,
                query_port=0,
                warp_port=-1,
                edge_proxy_port=-1,
                allowed_query_roots=[td],
                search_roots=[td],
                edge_targets={},
                phantom_enabled=False,
            )

            d_win = ChimeraDaemon(config=cfg_win, ops_dir=ops_win, auto_seed_on_empty=False).start()
            d_svh = ChimeraDaemon(config=cfg_svh, ops_dir=ops_svh, auto_seed_on_empty=False).start()
            try:
                # Law 7: strictly lazy _bios = None at boot on BOTH daemons
                self.assertIsNone(d_win.platform._bios)
                self.assertIsNone(d_svh.platform._bios)

                anchor_win = d_win.platform.anchor_url
                anchor_svh = d_svh.platform.anchor_url

                def _get(base: str, path: str) -> tuple[int, dict]:
                    with self._opener.open(f"{base}{path}", timeout=10.0) as r:
                        return r.status, json.loads(r.read().decode("utf-8"))

                def _post(base: str, path: str, body: dict) -> tuple[int, dict]:
                    req = urllib.request.Request(
                        f"{base}{path}",
                        data=json.dumps(body).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    try:
                        with self._opener.open(req, timeout=15.0) as r:
                            return r.status, json.loads(r.read().decode("utf-8"))
                    except urllib.error.HTTPError as exc:
                        return exc.code, json.loads(exc.read().decode("utf-8"))

                # --- Seed divergent physiology, CRDT events, scars, alarms, and seeds ---
                # Node A (node-win): high adrenaline, unique CRDT event, unique scar A, unique alarm A
                sc, _ = _post(anchor_win, "/v1/bios/hormones", {"hormone": "adrenaline", "delta": 0.65, "source": "win_cad"})
                self.assertEqual(sc, 200)
                d_win.platform.bios.octopus.peer_ganglion.append_event(
                    "win_cad_spike",
                    {"fps_p99": 120, "origin": "node-win"},
                    key="cad:frame_budget",
                )
                sc, _ = _post(
                    anchor_win,
                    "/v1/bios/soul/scar",
                    {
                        "title": "Win-Desktop Sync Scar A",
                        "event_date": "2026-11-27",
                        "root_cause": "Unbounded DXGI swapchain stall under load",
                        "lesson_law": "Keep Win-Optic display path zero-copy and unchoked",
                        "hardware_context": "node-win GTX 1650",
                        "tags": ["win", "sync_test", "law2"],
                        "severity": "high",
                    },
                )
                self.assertEqual(sc, 200)
                sc, _ = _post(
                    anchor_win,
                    "/v1/bios/pheromone",
                    {
                        "repo": "chimera-tp",
                        "rel_path": "chimera_tp/platform/substrate.py",
                        "alarm": {"signal_kind": "regression", "severity": 0.78, "reason": "win_sync_alarm_a"},
                    },
                )
                self.assertEqual(sc, 200)

                # Node B (node-svhome): high melatonin, unique CRDT event, unique scar B, unique seed B
                sc, _ = _post(anchor_svh, "/v1/bios/hormones", {"hormone": "melatonin", "delta": 0.62, "source": "svh_night"})
                self.assertEqual(sc, 200)
                d_svh.platform.bios.octopus.peer_ganglion.append_event(
                    "svhome_thermal_ok",
                    {"temp_c": 46.5, "origin": "node-svhome"},
                    key="svhome:thermal",
                )
                sc, _ = _post(
                    anchor_svh,
                    "/v1/bios/soul/scar",
                    {
                        "title": "Svhome Sync Scar B",
                        "event_date": "2026-11-27",
                        "root_cause": "15W node load spiked during unthrottled offload",
                        "lesson_law": "Protect svhome with Law-3 64KB sync cap & peer guard",
                        "hardware_context": "node-svhome i5-4300U 15W",
                        "tags": ["svhome", "sync_test", "law3"],
                        "severity": "critical",
                    },
                )
                self.assertEqual(sc, 200)
                sc, seed_res = _post(
                    anchor_svh,
                    "/v1/bios/spore/seed",
                    {"spore_id": "spore:svhome_ops", "text": "Verify 2-way BIOS convergence receipt", "priority": "high"},
                )
                self.assertEqual(sc, 200)
                seed_b_id = seed_res["seed_id"]

                # Snapshot pre-sync hormones & bundles
                win_h_before = d_win.platform.bios.endocrine.levels()
                svh_h_before = d_svh.platform.bios.endocrine.levels()
                sc, b_win = _get(anchor_win, "/v1/bios/sync/bundle")
                self.assertEqual(sc, 200)
                sc, b_svh = _get(anchor_svh, "/v1/bios/sync/bundle")
                self.assertEqual(sc, 200)
                self.assertLessEqual(len(json.dumps(b_win).encode("utf-8")), 32 * 1024)
                self.assertLessEqual(len(json.dumps(b_svh).encode("utf-8")), 32 * 1024)
                self.assertNotEqual(b_win["merkle_root"], b_svh["merkle_root"])

                # Law 3 guard: reject inbound bundle > 64 KB
                sc_big, err_big = _post(
                    anchor_svh,
                    "/v1/bios/sync",
                    {"bundle": {"node_name": "attacker", "pad": "x" * (65 * 1024)}},
                )
                self.assertEqual(sc_big, 400)
                self.assertFalse(err_big["ok"])
                self.assertIn("64kb", err_big["error"])

                # --- Trigger REAL 2-Way Bidirectional Sync: node-win -> node-svhome ---
                sc, sync_rec = _post(
                    anchor_win,
                    "/v1/bios/sync",
                    {"peer_url": anchor_svh, "blend": 0.35},
                )
                self.assertEqual(sc, 200, f"2-way sync failed: {sync_rec}")
                self.assertTrue(sync_rec["ok"])
                self.assertTrue(sync_rec["merkle_converged"])
                self.assertEqual(sync_rec["local_merkle_root"], sync_rec["peer_merkle_root"])
                self.assertEqual(sync_rec["endocrine_wire_bytes"], 12)
                self.assertTrue(sync_rec["endocrine_mmap_ok"])
                self.assertTrue(sync_rec["peer_endocrine_mmap_ok"])
                self.assertFalse(sync_rec["auto_activated"])
                self.assertEqual(sync_rec["scars_synced"]["pushed_to_peer"], 1)
                self.assertEqual(sync_rec["scars_synced"]["pulled_from_peer"], 1)
                self.assertEqual(sync_rec["alarms_synced"]["pushed_to_peer"], 1)
                self.assertEqual(sync_rec["seeds_synced"]["pulled_from_peer"], 1)

                # Verify BOTH daemons converged to exact same Merkle root
                _, g_win = _get(anchor_win, "/v1/bios/ganglia")
                _, g_svh = _get(anchor_svh, "/v1/bios/ganglia")
                self.assertEqual(g_win["peer_ganglion"]["merkle_root"], g_svh["peer_ganglion"]["merkle_root"])
                self.assertEqual(g_win["peer_ganglion"]["merkle_root"], sync_rec["local_merkle_root"])

                # Verify BOTH daemons possess BOTH scars with valid SHA-256 hash chains
                win_titles = {s["title"] for s in d_win.platform.bios.soul.list_scars(limit=100)}
                svh_titles = {s["title"] for s in d_svh.platform.bios.soul.list_scars(limit=100)}
                for expected_title in ("Win-Desktop Sync Scar A", "Svhome Sync Scar B"):
                    self.assertIn(expected_title, win_titles)
                    self.assertIn(expected_title, svh_titles)
                self.assertTrue(d_win.platform.bios.soul.verify_lineage()["valid"])
                self.assertTrue(d_svh.platform.bios.soul.verify_lineage()["valid"])

                # Verify BOTH daemons possess alarm A and seed B (preserving exact seed_id)
                _, ph_svh = _get(anchor_svh, "/v1/bios/pheromone?repo=chimera-tp&rel_path=chimera_tp/platform/substrate.py")
                self.assertGreater(ph_svh["alarm_level"], 0.5)
                _, sp_win = _get(anchor_win, "/v1/bios/spores")
                win_seed_ids = {s["seed_id"] for s in sp_win["recent_seeds"]}
                self.assertIn(seed_b_id, win_seed_ids)

                # Verify blended hormones synced directly into BOTH isolated NIXL mmap files (bytes 32..63)
                win_ring = ops_win / "bios" / "chimera_nixl_ring.bin"
                svh_ring = ops_svh / "bios" / "chimera_nixl_ring.bin"
                self.assertTrue(win_ring.is_file())
                self.assertTrue(svh_ring.is_file())
                win_blk = read_endocrine_block_mmap(win_ring)
                svh_blk = read_endocrine_block_mmap(svh_ring)
                self.assertTrue(win_blk["valid"])
                self.assertTrue(svh_blk["valid"])
                self.assertEqual(win_blk["magic"], "ENDO")
                self.assertEqual(svh_blk["magic"], "ENDO")
                # Hormones blended toward each other
                self.assertGreater(win_blk["hormones"]["melatonin"], win_h_before["melatonin"] + 0.05)
                self.assertGreater(svh_blk["hormones"]["adrenaline"], svh_h_before["adrenaline"] + 0.05)

                # Second sync must be 100% idempotent (0 duplicates, identical Merkle root)
                sc2, sync_rec2 = _post(
                    anchor_win,
                    "/v1/bios/sync",
                    {"peer_url": anchor_svh, "blend": 0.35},
                )
                self.assertEqual(sc2, 200)
                self.assertTrue(sync_rec2["merkle_converged"])
                self.assertEqual(sync_rec2["local_merkle_root"], sync_rec["local_merkle_root"])
                self.assertEqual(sync_rec2["scars_synced"]["total"], 0)
                self.assertEqual(sync_rec2["alarms_synced"]["total"], 0)
                self.assertEqual(sync_rec2["seeds_synced"]["total"], 0)

                # ChimeraClient.bios_sync() online AND offline fallback
                cli_on = connect(app="sync-online", anchor_url=anchor_win, auto_register=False)
                sdk_sync = cli_on.bios_sync(peer_url=anchor_svh, blend=0.35)
                self.assertTrue(sdk_sync["ok"])
                self.assertTrue(sdk_sync["merkle_converged"])

                cli_off = connect(app="sync-offline", anchor_url="http://127.0.0.1:1", auto_register=False)
                self.assertFalse(cli_off.available)
                sdk_off = cli_off.bios_sync()
                self.assertTrue(sdk_off["ok"])
                self.assertTrue(sdk_off["offline_fallback"])
                self.assertIn("local_merkle_root", sdk_off)

                # CLI `chimera-tp bios sync` online + local fallback
                for argv in (
                    ["bios", "sync", "--anchor", anchor_win, "--peer-url", anchor_svh, "--blend", "0.35"],
                    ["bios", "sync", "--local"],
                ):
                    buf = io.StringIO()
                    with contextlib.redirect_stdout(buf):
                        rc = cli_main(argv)
                    self.assertEqual(rc, 0, f"CLI bios sync failed for {argv}: {buf.getvalue()}")
                    parsed_cli = json.loads(buf.getvalue())
                    self.assertTrue(parsed_cli["ok"])
            finally:
                d_win.close()
                d_svh.close()


if __name__ == "__main__":
    unittest.main()
