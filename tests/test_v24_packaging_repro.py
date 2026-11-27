"""Packaging, native wheel inclusion, and clean-environment reproducibility tests (v24)."""

from __future__ import annotations

import json
import os
import py_compile
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.verify_clean_build import (
    _build_wheel,
    _clean_subprocess_env,
    _prepare_builder_python,
    _run,
    _verify_wheel_in_venv,
    audit_git_candidate,
)


class TestV24PackagingRepro(unittest.TestCase):
    def test_01_pyproject_package_data_and_prev_exclusion(self) -> None:
        pyproject_path = REPO_ROOT / "pyproject.toml"
        data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))

        find_cfg = data.get("tool", {}).get("setuptools", {}).get("packages", {}).get("find", {})
        self.assertIn("chimera_tp*", find_cfg.get("include", []))

        pkg_data = data.get("tool", {}).get("setuptools", {}).get("package-data", {})
        chimera_pkg_data = pkg_data.get("chimera_tp", [])
        self.assertIn("_chimera_core.dll", chimera_pkg_data)
        self.assertIn("_chimera_core.so", chimera_pkg_data)
        self.assertFalse(any(str(pat).endswith(".prev") for pat in chimera_pkg_data))

        excl_data = data.get("tool", {}).get("setuptools", {}).get("exclude-package-data", {})
        all_excludes = []
        for vals in excl_data.values():
            all_excludes.extend(vals)
        self.assertIn("*.prev", all_excludes)

        for py_file in (REPO_ROOT / "chimera_tp").rglob("*.py"):
            if "__pycache__" in py_file.parts:
                continue
            text = py_file.read_text(encoding="utf-8-sig")
            self.assertNotIn("_chimera_core.dll.prev", text, f"Unexpected .prev reference in {py_file}")

    def test_02_all_chimera_modules_compile_and_resolve_local_imports(self) -> None:
        audit = audit_git_candidate(REPO_ROOT)
        self.assertEqual(
            audit["missing_local_imports"],
            [],
            f"Missing local chimera_tp imports: {audit['missing_local_imports']}",
        )
        self.assertEqual(
            audit["external_third_party_imports"],
            {},
            f"Unexpected third-party deps in chimera_tp runtime violate zero-dependency requirement: {audit['external_third_party_imports']}",
        )

        with tempfile.TemporaryDirectory(prefix="chimera-compile-") as tmp:
            tmp_dir = Path(tmp)
            compiled = 0
            for py_file in sorted((REPO_ROOT / "chimera_tp").rglob("*.py")):
                if "__pycache__" in py_file.parts:
                    continue
                rel = py_file.relative_to(REPO_ROOT)
                cfile = tmp_dir / rel.with_suffix(".pyc")
                cfile.parent.mkdir(parents=True, exist_ok=True)
                py_compile.compile(str(py_file), cfile=str(cfile), doraise=True)
                compiled += 1
            self.assertGreaterEqual(compiled, 70)

    def test_03_clean_isolated_native_and_pure_wheel_reproducibility(self) -> None:
        tmp_root = Path(tempfile.mkdtemp(prefix="chimera-pkg-test-"))
        try:
            builder_py, build_mode = _prepare_builder_python(tmp_root)
            empty_cwd = tmp_root / "empty_cwd"
            empty_cwd.mkdir(parents=True, exist_ok=True)

            def _export_clean_tree(dest: Path, *, include_native: bool) -> None:
                dest.mkdir(parents=True, exist_ok=True)
                for fname in ("pyproject.toml", "README.md", "LICENSE"):
                    src = REPO_ROOT / fname
                    if src.is_file():
                        shutil.copy2(src, dest / fname)
                for src in (REPO_ROOT / "chimera_tp").rglob("*"):
                    if not src.is_file():
                        continue
                    rel = src.relative_to(REPO_ROOT)
                    if "__pycache__" in rel.parts or src.name.endswith((".pyc", ".pyo", ".prev", ".tmp")):
                        continue
                    if not include_native and src.name in ("_chimera_core.dll", "_chimera_core.so"):
                        continue
                    out = dest / rel
                    out.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, out)

            has_dll = (REPO_ROOT / "chimera_tp" / "_chimera_core.dll").is_file()
            has_so = (REPO_ROOT / "chimera_tp" / "_chimera_core.so").is_file()

            # 1) Native wheel build + install + smoke check
            src_native = tmp_root / "src_native"
            _export_clean_tree(src_native, include_native=True)
            whl_native = _build_wheel(src_native, tmp_root / "w_native", builder_py, build_mode)
            with zipfile.ZipFile(whl_native, "r") as zf:
                names = zf.namelist()
            self.assertFalse(any(n.lower().endswith(".prev") for n in names))
            if os.name == "nt" and has_dll:
                self.assertIn("chimera_tp/_chimera_core.dll", names)

            res_native = _verify_wheel_in_venv(
                whl_native,
                tmp_root / "venv_native",
                empty_cwd,
                expect_native=bool(has_dll or has_so),
                check_all_v21_v23=True,
            )
            self.assertTrue(res_native["ok"])
            self.assertEqual(res_native["version"], "18.0.0")
            self.assertEqual(res_native["cli_help_exit_code"], 0)
            if os.name == "nt" and has_dll:
                self.assertTrue(res_native["has_native"])
                self.assertTrue(res_native["cpu_caps"]["native"])

            # 2) Pure-Python fallback wheel build + install + smoke check
            src_pure = tmp_root / "src_pure"
            _export_clean_tree(src_pure, include_native=False)
            whl_pure = _build_wheel(src_pure, tmp_root / "w_pure", builder_py, build_mode)
            res_pure = _verify_wheel_in_venv(
                whl_pure,
                tmp_root / "venv_pure",
                empty_cwd,
                expect_native=False,
                check_all_v21_v23=False,
            )
            self.assertTrue(res_pure["ok"])
            self.assertFalse(res_pure["has_native"])
            self.assertFalse(res_pure["cpu_caps"]["native"])
            self.assertTrue(res_pure["pure_fallback_ops_ok"])
            self.assertEqual(res_pure["cli_help_exit_code"], 0)
        finally:
            shutil.rmtree(tmp_root, ignore_errors=True)

    def test_04_substrate_evidence_exile_handoff_http_and_mcp(self) -> None:
        from chimera_tp.autopilot import OpsConfig
        from chimera_tp.dashboard import ChimeraDaemon
        from chimera_tp.platform import InMemoryWorkerTransport, handle_mcp_request

        with tempfile.TemporaryDirectory(prefix="chimera-p2-http-") as tmp:
            ops_dir = Path(tmp) / "ops"
            cfg = OpsConfig(
                node_name="p2-test-node",
                role="controller",
                dashboard_bind="127.0.0.1:0",
                beam_port=0,
                rpc_v4_port=0,
                rpc_v6_port=-1,
                query_port=0,
                warp_port=-1,
                edge_proxy_port=-1,
                allowed_query_roots=[tmp],
                search_roots=[tmp],
                edge_targets={},
                phantom_enabled=False,
            )
            daemon = ChimeraDaemon(config=cfg, ops_dir=ops_dir, auto_seed_on_empty=False).start()
            daemon.platform.exile_handoff.worker_transport = InMemoryWorkerTransport()
            try:
                anchor = daemon.platform.anchor_url
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

                def _get(path: str) -> dict:
                    with opener.open(f"{anchor}{path}", timeout=5.0) as r:
                        return json.loads(r.read().decode("utf-8"))

                def _post(path: str, body: dict) -> tuple[int, dict]:
                    req = urllib.request.Request(
                        f"{anchor}{path}",
                        data=json.dumps(body).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    try:
                        with opener.open(req, timeout=10.0) as r:
                            return r.status, json.loads(r.read().decode("utf-8"))
                    except urllib.error.HTTPError as exc:
                        return exc.code, json.loads(exc.read().decode("utf-8"))

                caps = _get("/.well-known/chimera.json")
                self.assertEqual(caps["cartridge_status_basis"], "config_plus_live_evidence")
                self.assertEqual(caps["cartridges"]["connect"]["evidence"]["verification_status"], "verified")
                self.assertEqual(caps["cartridges"]["egress_membrane"]["evidence"]["verification_status"], "verified")
                self.assertEqual(caps["cartridges"]["immortal_jobs"]["evidence"]["verification_status"], "unverified")

                ev_all = _get("/v1/evidence")
                self.assertTrue(ev_all["ok"])
                self.assertIn("capabilities", ev_all)

                st_rec, rec_out = _post(
                    "/v1/evidence/record",
                    {
                        "capability": "hyper_desk",
                        "execution_node": "p2-test-node",
                        "ttl_s": 120.0,
                        "verified": True,
                        "metrics": {"vram_yield_ms": 12.5},
                        "receipt_id": "probe-hd-1",
                    },
                )
                self.assertEqual(st_rec, 200)
                self.assertEqual(rec_out["evaluated"]["verification_status"], "verified")

                # Loopback guard on /v1/evidence/record
                st_nonlocal, _ = daemon.platform.handle_post(
                    urllib.parse.urlparse("/v1/evidence/record"),
                    b'{"capability":"hyper_desk"}',
                    {},
                    client_ip="10.0.0.5",
                )
                self.assertEqual(st_nonlocal, 403)

                # Execute local checkpointed handoff over HTTP (empty prefer_target avoids SSH in unit test)
                st_ho, ho_out = _post(
                    "/v1/exile/handoff",
                    {
                        "job_id": "http-handoff-1",
                        "op": "zlib_compress",
                        "payload": "chimera-phase2-payload-" * 20,
                        "prefer_target": "p2-test-node",
                    },
                )
                self.assertEqual(st_ho, 200, msg=json.dumps(ho_out))
                self.assertTrue(ho_out["ok"])
                self.assertEqual(ho_out["job_status"], "completed")
                self.assertEqual(len(ho_out["receipts"]), 1)

                recs = _get("/v1/exile/receipts?job_id=http-handoff-1")
                self.assertTrue(recs["ok"])
                self.assertEqual(len(recs["receipts"]), 1)
                self.assertEqual(_get("/v1/evidence?capability=immortal_jobs")["evidence"]["verification_status"], "verified")
                self.assertEqual(_get("/v1/evidence?capability=exile")["evidence"]["verification_status"], "verified")

                # MCP tools
                tools = handle_mcp_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, anchor_url=anchor)
                tool_names = {t["name"] for t in tools["result"]["tools"]}
                self.assertIn("chimera_evidence", tool_names)
                self.assertIn("chimera_exile_handoff", tool_names)

                mcp_ev = handle_mcp_request(
                    {
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "tools/call",
                        "params": {"name": "chimera_evidence", "arguments": {"action": "status", "capability": "exile"}},
                    },
                    anchor_url=anchor,
                )
                self.assertEqual(json.loads(mcp_ev["result"]["content"][0]["text"])["evidence"]["verification_status"], "verified")

                mcp_rec = handle_mcp_request(
                    {
                        "jsonrpc": "2.0",
                        "id": 3,
                        "method": "tools/call",
                        "params": {"name": "chimera_exile_handoff", "arguments": {"action": "receipts", "job_id": "http-handoff-1"}},
                    },
                    anchor_url=anchor,
                )
                self.assertEqual(len(json.loads(mcp_rec["result"]["content"][0]["text"])["receipts"]), 1)
            finally:
                daemon.close()


if __name__ == "__main__":
    unittest.main()
