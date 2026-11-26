"""CHIMERA-HYPER v14.0 PHANTOM-CORTEX Unified Causal Topology Tests."""

from __future__ import annotations

import base64
import gzip
import json
import os
import py_compile
import re
import shutil
import subprocess
import tempfile
import unittest
import urllib.request
import zlib
from pathlib import Path

from chimera_tp.autopilot import OpsConfig
from chimera_tp.dashboard import ChimeraDaemon
from chimera_tp.universe_ui import UNIVERSE_DASHBOARD_HTML, build_kolmogorov_packed_html


class TestV13CortexUI(unittest.TestCase):
    def test_01_size_budgets_and_shader_precision(self) -> None:
        raw_bytes = UNIVERSE_DASHBOARD_HTML.encode("utf-8")
        gz_bytes = gzip.compress(raw_bytes, compresslevel=9)
        packed_bytes = build_kolmogorov_packed_html("{}", '""')

        self.assertLessEqual(len(raw_bytes), 46_000, f"Raw UI bloated: {len(raw_bytes)} B")
        self.assertLessEqual(len(gz_bytes), 18_500, f"Gzip UI bloated: {len(gz_bytes)} B")
        self.assertLessEqual(len(packed_bytes), 25_000, f"Packed UI bloated: {len(packed_bytes)} B")
        # v26+ Zero-WebGL invariant: pure 2D SVG/Canvas observability console (0% GPU lag)
        self.assertNotIn("getContext('webgl'", UNIVERSE_DASHBOARD_HTML)
        self.assertNotIn("precision highp float;", UNIVERSE_DASHBOARD_HTML)

        for marker in (
            "CHIMERA-HYPER v2.0",
            "CHIMERA-HYPER v12.0 OMEGA-GALACTIC",
            "OMNISCIENCE v24",
            "mesh-svg",
            "sil-list",
            "c-ht",
            "c-ph",
            "pane-hyperdrive",
            "pane-galactic",
            "spotlight-modal",
            "spotlight-input",
            "spotlight-out",
            "tactical-deck",
            "flow-feed",
            "__CORTEX__",
        ):
            self.assertIn(marker, UNIVERSE_DASHBOARD_HTML)

    def test_02_js_syntax_check_and_dashboard_compile(self) -> None:
        py_compile.compile("chimera_tp/universe_ui.py", doraise=True)
        py_compile.compile("chimera_tp/dashboard.py", doraise=True)
        scripts = re.findall(r"<script>(.*?)</script>", UNIVERSE_DASHBOARD_HTML, re.S)
        self.assertEqual(len(scripts), 1)
        node = shutil.which("node")
        if node:
            with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
                f.write(scripts[0])
                jsp = f.name
            try:
                proc = subprocess.run(
                    [node, "--check", jsp],
                    capture_output=True,
                    text=True,
                    creationflags=(getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0),
                )
                self.assertEqual(proc.returncode, 0, proc.stderr)
            finally:
                os.unlink(jsp)

    def test_03_live_daemon_packed_endpoint_and_realtime_flow_ring(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            work = root / "work"
            work.mkdir()
            cfg = OpsConfig(
                role="server",
                node_name="cortex_unit",
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
                req = urllib.request.Request(f"{base}/", headers={"Accept-Encoding": "gzip"})
                with urllib.request.urlopen(req, timeout=5.0) as r:
                    wire_gz = r.read()
                    self.assertEqual(r.headers.get("Content-Encoding"), "gzip")
                    self.assertLessEqual(len(wire_gz), 19_500, f"Root gzip wire too large: {len(wire_gz)}")
                    raw_html = gzip.decompress(wire_gz).decode("utf-8")
                    self.assertIn("CHIMERA-HYPER v12.0 OMEGA-GALACTIC", raw_html)
                    self.assertIn("cortex_unit", raw_html)

                with urllib.request.urlopen(f"{base}/?packed=1", timeout=5.0) as r2:
                    packed_raw = r2.read()
                    self.assertEqual(r2.headers.get("X-Chimera-Packed"), "kolmogorov-deflate-raw")
                    self.assertLessEqual(len(packed_raw), 25_500, f"Packed wire too large: {len(packed_raw)}")
                    packed_txt = packed_raw.decode("utf-8")
                    self.assertIn("DecompressionStream('deflate-raw')", packed_txt)
                    b64s = re.findall(r"_u\('([A-Za-z0-9+/=]+)'\)", packed_txt)
                    self.assertEqual(len(b64s), 2)
                    unpacked_state = zlib.decompress(base64.b64decode(b64s[1]), -zlib.MAX_WBITS).decode("utf-8")
                    self.assertIn("cortex_unit", unpacked_state)

                # Trigger live single-action primitives and confirm real-time /api/pulse flow ring records all of them
                for ep in ("/api/galactic/live-teleport", "/api/galactic/live-frost", "/api/galactic/live-chmc"):
                    req_p = urllib.request.Request(
                        f"{base}{ep}", data=b"{}", headers={"Content-Type": "application/json"}, method="POST"
                    )
                    res_p = json.loads(urllib.request.urlopen(req_p, timeout=20.0).read().decode("utf-8"))
                    self.assertTrue(res_p["ok"], f"{ep}: {res_p}")

                urllib.request.urlopen(f"{base}/api/galactic/tarpit/env/prod.yml", timeout=4.0).read()
                pulse = json.loads(urllib.request.urlopen(f"{base}/api/pulse", timeout=4.0).read().decode("utf-8"))
                ops = {f["op"] for f in pulse.get("flows", [])}
                self.assertTrue({"WASM_TELEPORT", "FROST_2OF3", "CHMC_3STRIKE", "TARPIT_0KB"}.issubset(ops), ops)
            finally:
                daemon.close()

    def test_04_zero_blocking_assets_and_total_wire_to_first_interactive(self) -> None:
        self.assertEqual(re.findall(r"<script\b[^>]*\bsrc\s*=", UNIVERSE_DASHBOARD_HTML, re.I), [])
        self.assertEqual(
            re.findall(r"<link\b[^>]*\brel\s*=\s*[\"']?stylesheet\b", UNIVERSE_DASHBOARD_HTML, re.I),
            [],
        )
        self.assertEqual(re.findall(r"https?://", UNIVERSE_DASHBOARD_HTML, re.I), [])

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            work = root / "work"
            work.mkdir()
            cfg = OpsConfig(
                role="server",
                node_name="wire_tti_unit",
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
                req_root = urllib.request.Request(f"{base}/", headers={"Accept-Encoding": "gzip"})
                with urllib.request.urlopen(req_root, timeout=5.0) as r_root:
                    self.assertEqual(r_root.headers.get("Content-Encoding"), "gzip")
                    root_gz = r_root.read()

                req_pulse = urllib.request.Request(f"{base}/api/pulse", headers={"Accept-Encoding": "gzip"})
                with urllib.request.urlopen(req_pulse, timeout=5.0) as r_pulse:
                    self.assertEqual(r_pulse.headers.get("Content-Encoding"), "gzip")
                    pulse_gz = r_pulse.read()
                    pulse_obj = json.loads(gzip.decompress(pulse_gz).decode("utf-8"))
                    self.assertIn("zero_weight", pulse_obj)

                total_wire = len(root_gz) + len(pulse_gz)
                self.assertLessEqual(
                    total_wire,
                    26_000,
                    f"Total wire to first interactive too large: {len(root_gz)} + {len(pulse_gz)} = {total_wire} B",
                )
            finally:
                daemon.close()


if __name__ == "__main__":
    unittest.main()
