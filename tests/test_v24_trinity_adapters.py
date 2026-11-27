"""CHIMERA-TP v24 Decoupled Manifest Adapter Tests for TrinityCommandBridge."""

from __future__ import annotations

import http.server
import json
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.parse

from chimera_tp.host_governor import HostYieldGovernor
from chimera_tp.overmind_cortex import OvermindCortex
from chimera_tp.platform.discovery import AppRegistry, link_project
from chimera_tp.trinity_bridge import (
    DownstreamAdapterSpec,
    TrinityCommandBridge,
    adapter_from_manifest,
)


class _MockForgeWorkerServer:
    """Ephemeral 3rd downstream app ('forge-worker') with custom endpoints and nested JSON."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.state: dict[str, object] = {
            "paused": False,
            "pause_source": "",
            "jobs_done": 14,
            "burn_pct_hr": 3.4,
            "queue_depth": 2,
        }
        self.halt_calls: list[dict[str, object]] = []
        self.receipts: list[dict[str, object]] = [
            {"id": "rcpt-1", "job": "build-wasm", "sha256": "aaa111"},
            {"id": "rcpt-2", "job": "compile-ptx", "sha256": "bbb222"},
            {"id": "rcpt-3", "job": "verify-cas", "sha256": "ccc333"},
        ]
        self.srv: http.server.ThreadingHTTPServer | None = None
        self.port = 0

    def start(self) -> "_MockForgeWorkerServer":
        parent = self

        class _Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                parsed = urllib.parse.urlparse(self.path)
                if parsed.path == "/v2/metrics":
                    with parent.lock:
                        payload = {
                            "service": "forge-worker",
                            "metrics": {
                                "jobs_done": parent.state["jobs_done"],
                                "burn_pct_hr": parent.state["burn_pct_hr"],
                                "queue_depth": parent.state["queue_depth"],
                            },
                            "state": {
                                "paused": parent.state["paused"],
                                "pause_source": parent.state["pause_source"],
                            },
                        }
                    raw = json.dumps(payload).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                    return

                if parsed.path == "/v2/receipts":
                    qs = urllib.parse.parse_qs(parsed.query)
                    lim = int((qs.get("limit") or ["20"])[0] or 20)
                    with parent.lock:
                        items = list(parent.receipts[:lim])
                    raw = json.dumps({"ok": True, "receipts": items, "count": len(items)}).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                    return

                self.send_response(404)
                self.end_headers()

            def do_POST(self) -> None:
                parsed = urllib.parse.urlparse(self.path)
                if parsed.path == "/v2/halt":
                    ln = int(self.headers.get("Content-Length") or 0)
                    body = json.loads(self.rfile.read(ln).decode("utf-8") or "{}")
                    with parent.lock:
                        parent.halt_calls.append(body)
                        paused_val = bool(body.get("halted", body.get("paused", False)))
                        parent.state["paused"] = paused_val
                        parent.state["pause_source"] = str(body.get("origin") or body.get("source") or "")
                    raw = json.dumps({"ok": True, "halted": paused_val}).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                    return

                self.send_response(404)
                self.end_headers()

            def log_message(self, *_args: object) -> None:
                pass

        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.srv.daemon_threads = True
        self.port = int(self.srv.server_address[1])
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        return self

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def close(self) -> None:
        if self.srv is not None:
            self.srv.shutdown()
            self.srv.server_close()


class TestV24TrinityAdapters(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.forge = _MockForgeWorkerServer().start()
        self.reg_path = self.root / "apps.json"
        self.proj_dir = self.root / "forge_worker_app"
        self.proj_dir.mkdir(parents=True)

        self.adapter_manifest_obj = {
            "roles": ["telemetry", "actuated", "proofs"],
            "base_url": self.forge.base_url,
            "telemetry_endpoints": [{"path": "/v2/metrics", "timeout_s": 1.2}],
            "field_map": {
                "outputs": "metrics.jobs_done",
                "burn_rate_pct_hr": "metrics.burn_pct_hr",
                "queue_depth": "metrics.queue_depth",
            },
            "control_endpoint": "/v2/halt",
            "control_payload_map": {
                "paused": "halted",
                "reason": "why",
                "source": "origin",
                "hlc_ts_ms": "hlc_ts_ms",
            },
            "reconcile": {
                "paused_path": "state.paused",
                "source_path": "state.pause_source",
            },
            "proofs_endpoint": "/v2/receipts?limit={limit}",
        }
        (self.proj_dir / "chimera.manifest.json").write_text(
            json.dumps(
                {
                    "schema": "chimera.manifest.v1",
                    "app": "forge-worker",
                    "port": self.forge.port,
                    "adapter": self.adapter_manifest_obj,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        self.link_res = link_project(self.proj_dir, registry_path=self.reg_path)
        self.overmind = OvermindCortex(ops_dir=self.root / "ops", node_id="win-test")
        self.bridge = TrinityCommandBridge(
            governor=HostYieldGovernor(role="controller", policy="work_first"),
            tquota_admin_url="",
            radar_url="",
            ephemeral_mode=False,
            overmind=self.overmind,
        )
        self.loaded = self.bridge.load_adapters_from_manifests(AppRegistry(self.reg_path))

    def tearDown(self) -> None:
        self.forge.close()
        self._tmp.cleanup()

    def test_01_manifest_link_registry_and_adapter_registration(self) -> None:
        self.assertIn("adapter", self.link_res["manifest"])
        self.assertEqual(self.link_res["manifest"]["app"], "forge-worker")
        self.assertIn("adapter", self.link_res["entry"])

        reloaded_reg = AppRegistry(self.reg_path)
        apps = {a["app"]: a for a in reloaded_reg.list_apps()}
        self.assertIn("forge-worker", apps)
        self.assertEqual(apps["forge-worker"]["adapter"]["control_endpoint"], "/v2/halt")
        self.assertIn("forge-worker", self.loaded)

        listed = {a["name"]: a for a in self.bridge.list_adapters()}
        self.assertIn("tquota", listed)
        self.assertIn("radar", listed)
        self.assertIn("forge-worker", listed)
        self.assertEqual(listed["forge-worker"]["base_url"], self.forge.base_url)

        spec = adapter_from_manifest(self.link_res["manifest"])
        self.assertIsInstance(spec, DownstreamAdapterSpec)
        self.assertEqual(spec.control_payload_map["paused"], "halted")

        # Also verify link_project(..., adapter=...) persists when passed explicitly
        proj2 = self.root / "explicit_app"
        res2 = link_project(
            proj2,
            app_name="explicit-worker",
            port=9922,
            registry_path=self.reg_path,
            adapter={"roles": ["telemetry"], "telemetry_endpoints": [{"path": "/health"}]},
        )
        self.assertEqual(res2["manifest"]["adapter"]["roles"], ["telemetry"])
        spec2 = adapter_from_manifest(res2["manifest"])
        self.assertEqual(spec2.base_url, "http://127.0.0.1:9922")

    def test_02_generic_telemetry_polling_with_latency_and_backward_compat_snapshot(self) -> None:
        snap = self.bridge.poll_now()
        self.assertTrue(snap["ok"])
        self.assertEqual(snap["version"], "15.0-trinity")
        self.assertEqual(snap["bridge_rev"], "18.0-overmind")
        self.assertIn("governor", snap)
        self.assertIn("kill_switch", snap)
        self.assertIn("tquota", snap)
        self.assertIn("radar", snap)
        self.assertIn("adapters", snap)

        fw = snap["adapters"]["forge-worker"]
        self.assertTrue(fw["online"])
        self.assertEqual(fw["endpoint"], self.forge.base_url)
        self.assertIsInstance(fw["latency_ms"], float)
        self.assertGreaterEqual(fw["latency_ms"], 0.0)
        self.assertEqual(fw["outputs"], 14)
        self.assertEqual(fw["burn_rate_pct_hr"], 3.4)
        self.assertEqual(fw["queue_depth"], 2)
        self.assertEqual(snap["kill_switch"]["quota_burn_rate_pct_hr"], 3.4)
        self.assertEqual(snap["kill_switch"]["recent_outputs"], 14)

    def test_03_kill_switch_actuates_mapped_control_payload(self) -> None:
        ks_on = self.bridge.set_kill_switch(True, "forge_budget_halt", actuate=True)
        self.assertTrue(ks_on["active"])
        self.assertTrue(ks_on["actuation"]["ok"])
        self.assertEqual(ks_on["actuation"]["mode"], "direct")
        self.assertEqual(ks_on["actuation"]["targets"][0]["adapter"], "forge-worker")
        self.assertTrue(self.forge.halt_calls[-1]["halted"])
        self.assertEqual(self.forge.halt_calls[-1]["why"], "forge_budget_halt")
        self.assertEqual(self.forge.halt_calls[-1]["origin"], "chimera_kill_switch")
        self.assertGreater(int(self.forge.halt_calls[-1]["hlc_ts_ms"]), 0)
        self.assertTrue(self.forge.state["paused"])

        ks_off = self.bridge.set_kill_switch(False, "forge_resume", actuate=True)
        self.assertFalse(ks_off["active"])
        self.assertTrue(ks_off["actuation"]["ok"])
        self.assertFalse(self.forge.halt_calls[-1]["halted"])
        self.assertEqual(self.forge.halt_calls[-1]["why"], "forge_resume")
        self.assertFalse(self.forge.state["paused"])

    def test_04_split_brain_mismatch_on_metrics_reconciled_automatically(self) -> None:
        # Authoritative CRDT says active=False, while forge-worker drifted to paused=True with chimera_kill_switch source
        self.overmind.crdt.mutate(
            {"kill_switch_active": False, "kill_switch_reason": "crdt_resumed"},
            source="chimera_kill_switch",
        )
        with self.forge.lock:
            self.forge.state["paused"] = True
            self.forge.state["pause_source"] = "chimera_kill_switch"
            self.forge.halt_calls.clear()

        snap = self.bridge.poll_now()
        self.assertTrue(snap["adapters"]["forge-worker"]["reconciled"])
        self.assertFalse(self.forge.state["paused"])
        self.assertEqual(len(self.forge.halt_calls), 1)
        self.assertFalse(self.forge.halt_calls[0]["halted"])

        events = self.overmind.pulse.poll(since_seq=0)["events"]
        self.assertIn("BRAIN_STATE_RECONCILED", [ev["topic"] for ev in events])

        # Non-chimera manual pause source must NOT be overridden
        with self.forge.lock:
            self.forge.state["paused"] = True
            self.forge.state["pause_source"] = "manual_local_operator"
            self.forge.halt_calls.clear()
        snap2 = self.bridge.poll_now()
        self.assertFalse(snap2["adapters"]["forge-worker"]["reconciled"])
        self.assertTrue(self.forge.state["paused"])
        self.assertEqual(len(self.forge.halt_calls), 0)

    def test_05_list_proofs_retrieves_receipts_for_custom_adapter(self) -> None:
        res = self.bridge.list_proofs(limit=2, adapter="forge-worker")
        self.assertTrue(res["ok"])
        self.assertEqual(res["adapter"], "forge-worker")
        self.assertEqual(res["via"], "direct")
        self.assertEqual(res["endpoint"], self.forge.base_url)
        self.assertEqual(len(res["receipts"]), 2)
        self.assertEqual(len(res["proofs"]), 2)
        self.assertEqual(res["receipts"][0]["id"], "rcpt-1")
        self.assertEqual(res["receipts"][1]["id"], "rcpt-2")

        missing = self.bridge.list_proofs(limit=5, adapter="unknown-app")
        self.assertFalse(missing["ok"])
        self.assertEqual(missing["count"], 0)

    def test_06_url_property_setters_unregister_and_auto_kill_switch(self) -> None:
        self.bridge.radar_url = "http://127.0.0.1:18787"
        self.bridge.tquota_admin_url = "http://127.0.0.1:12599"
        by_name = {a["name"]: a for a in self.bridge.list_adapters()}
        self.assertEqual(by_name["radar"]["base_url"], "http://127.0.0.1:18787")
        self.assertEqual(by_name["tquota"]["base_url"], "http://127.0.0.1:12599")
        self.assertEqual(self.bridge.radar_url, "http://127.0.0.1:18787")
        self.assertEqual(self.bridge.tquota_admin_url, "http://127.0.0.1:12599")

        # Auto ROI kill-switch actuates forge-worker when burn >= 12%/hr & 0 outputs >= 2h
        ks_auto = self.bridge.evaluate_auto_kill_switch(
            burn_rate_pct_hr=15.0,
            recent_outputs=0,
            zero_output_hours=2.5,
        )
        self.assertTrue(ks_auto["active"])
        self.assertTrue(ks_auto["auto_triggered"])
        self.assertTrue(self.forge.state["paused"])

        self.assertTrue(self.bridge.unregister_adapter("forge-worker"))
        self.assertFalse(self.bridge.unregister_adapter("forge-worker"))
        self.assertNotIn("forge-worker", self.bridge.snapshot(refresh=False)["adapters"])


if __name__ == "__main__":
    unittest.main()
