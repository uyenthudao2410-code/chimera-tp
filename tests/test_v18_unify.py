"""Comprehensive tests for CHIMERA-UNIFY 3-layer host-wide unification (venv auto-attach, OpenAI pass-through, AGENTS.md & MCP)."""

from __future__ import annotations

import http.server
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

from chimera_tp.autopilot import OpsConfig
from chimera_tp.dashboard import ChimeraDaemon
from chimera_tp.platform import unify_install, unify_status, unify_uninstall


class TestV18Unify(unittest.TestCase):
    def test_01_unify_install_beacons_mcp_and_zero_link_venv_auto_attach(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fake_home = root / "home"
            fake_home.mkdir()
            dev_root = root / "DEV"
            brand_new_proj = dev_root / "my-brand-new-app"
            brand_new_proj.mkdir(parents=True)
            site_dir = root / "site"
            site_dir.mkdir()

            # Existing user configs that MUST be preserved intact!
            (dev_root / "AGENTS.md").write_text("# My Existing Workspace Notes\nKeep me!\n", encoding="utf-8")
            (fake_home / ".claude.json").write_text(
                json.dumps({"mcpServers": {"other_tool": {"command": "echo", "args": ["ok"]}}, "theme": "dark"}),
                encoding="utf-8",
            )
            (fake_home / ".codex").mkdir()
            (fake_home / ".codex" / "config.toml").write_text('model = "gpt-5"\n', encoding="utf-8")
            (fake_home / ".codex" / "AGENTS.md").write_text("# Codex Global\n", encoding="utf-8")
            (fake_home / ".gemini" / "config").mkdir(parents=True)
            (fake_home / ".gemini" / "config" / "mcp_config.json").write_text(
                json.dumps({"mcpServers": {"stitch": {"serverUrl": "https://example.invalid/mcp"}}}),
                encoding="utf-8",
            )
            # Simulate T3 Code isolated Antigravity profile with a 0-byte config/mcp_config.json
            t3_prof = fake_home / ".t3" / "userdata" / "providers" / "antigravity" / "abc1234567890" / "config"
            t3_prof.mkdir(parents=True)
            (t3_prof / "mcp_config.json").write_text("", encoding="utf-8")

            # Write fake runtime.json into fake_home/.chimera/
            rt_dir = fake_home / ".chimera"
            rt_dir.mkdir(parents=True)
            (rt_dir / "runtime.json").write_text(
                json.dumps(
                    {
                        "anchor_url": "http://127.0.0.1:9780",
                        "egress_proxy_url": "http://127.0.0.1:9781",
                    }
                ),
                encoding="utf-8",
            )

            res = unify_install(
                dev_roots=[str(dev_root)],
                anchor_url="http://127.0.0.1:9780",
                proxy_url="http://127.0.0.1:9781",
                install_env=True,
                install_mcp=True,
                install_beacons=True,
                home_dir=fake_home,
                site_target_dir=site_dir,
            )
            self.assertTrue(res["ok"])
            self.assertEqual(len(res["dev_root_beacons"]), 1)

            # Verify existing AGENTS.md content preserved + beacon added idempotently
            agents_txt = (dev_root / "AGENTS.md").read_text(encoding="utf-8")
            self.assertIn("Keep me!", agents_txt)
            self.assertIn("CHIMERA-UNIFY-BEGIN", agents_txt)

            # Verify MCP registrations preserved existing servers & added `chimera`
            claude_cfg = json.loads((fake_home / ".claude.json").read_text(encoding="utf-8"))
            self.assertIn("other_tool", claude_cfg["mcpServers"])
            self.assertIn("chimera", claude_cfg["mcpServers"])
            self.assertEqual(claude_cfg["theme"], "dark")
            codex_txt = (fake_home / ".codex" / "config.toml").read_text(encoding="utf-8")
            self.assertIn('model = "gpt-5"', codex_txt)
            self.assertIn("[mcp_servers.chimera]", codex_txt)
            # Re-run unify_install with Windows backslashes to guard against re.sub backslash-halving in TOML!
            res2 = unify_install(
                dev_roots=[str(dev_root)],
                anchor_url="http://127.0.0.1:9780",
                proxy_url="http://127.0.0.1:9781",
                install_env=True,
                install_mcp=True,
                install_beacons=True,
                home_dir=fake_home,
                site_target_dir=site_dir,
                python_exe=r"C:\Program Files\Python311\python.exe",
            )
            self.assertTrue(res2["ok"])
            import tomllib

            parsed_toml = tomllib.loads((fake_home / ".codex" / "config.toml").read_text(encoding="utf-8"))
            self.assertEqual(parsed_toml["mcp_servers"]["chimera"]["command"], r"C:\Program Files\Python311\python.exe")
            # Restore original python_exe for subsequent assertions
            unify_install(
                dev_roots=[str(dev_root)],
                anchor_url="http://127.0.0.1:9780",
                proxy_url="http://127.0.0.1:9781",
                install_env=True,
                install_mcp=True,
                install_beacons=True,
                home_dir=fake_home,
                site_target_dir=site_dir,
            )
            self.assertTrue((fake_home / ".gemini" / "antigravity" / "mcp_config.json").is_file())
            cli_mcp = json.loads((fake_home / ".gemini" / "config" / "mcp_config.json").read_text(encoding="utf-8"))
            self.assertIn("stitch", cli_mcp["mcpServers"])
            self.assertIn("chimera", cli_mcp["mcpServers"])
            t3_mcp = json.loads((t3_prof / "mcp_config.json").read_text(encoding="utf-8"))
            self.assertIn("chimera", t3_mcp["mcpServers"])
            self.assertIn("chimera_xray_batch", (fake_home / ".codex" / "AGENTS.md").read_text(encoding="utf-8"))
            self.assertIn("chimera_xray_batch", (fake_home / ".gemini" / "AGENTS.md").read_text(encoding="utf-8"))

            st = unify_status(home_dir=fake_home)
            self.assertTrue(st["unified"])
            self.assertEqual(
                set(st["mcp_registered_agents"]),
                {"claude_code", "antigravity", "antigravity_cli", "t3_antigravity:abc1234567", "codex"},
            )

            # Simulate a BRAND-NEW project inside dev_root (NEVER ran `chimera-tp link`!) running Python with PYTHONPATH=autoload
            env = dict(os.environ)
            env["HOME"] = str(fake_home)
            env["USERPROFILE"] = str(fake_home)
            env["PYTHONPATH"] = str(fake_home / ".chimera" / "autoload")
            for k in ("CHIMERA_URL", "CHIMERA_APP", "CHIMERA_OPENAI_BASE", "CHIMERA_COMPUTE_URL", "HTTP_PROXY", "HTTPS_PROXY"):
                env.pop(k, None)
            out = subprocess.check_output(
                [
                    sys.executable,
                    "-c",
                    "import json, os; print(json.dumps({k: os.environ.get(k) for k in ('CHIMERA_URL','CHIMERA_APP','CHIMERA_OPENAI_BASE','CHIMERA_COMPUTE_URL','HTTP_PROXY')}))",
                ],
                cwd=str(brand_new_proj),
                env=env,
                text=True,
                timeout=10.0,
            ).strip()
            injected = json.loads(out)
            self.assertEqual(injected["CHIMERA_APP"], "my-brand-new-app")
            self.assertEqual(injected["CHIMERA_URL"], "http://127.0.0.1:9780")
            self.assertEqual(injected["CHIMERA_OPENAI_BASE"], "http://127.0.0.1:9780/v1/openai/v1")
            self.assertEqual(injected["CHIMERA_COMPUTE_URL"], "http://127.0.0.1:9780/v1/vgpu/compute")
            self.assertEqual(injected["HTTP_PROXY"], "http://127.0.0.1:9781")

            # Clean uninstall removes ONLY Chimera entries and keeps user's original content intact!
            un = unify_uninstall(home_dir=fake_home)
            self.assertTrue(un["ok"])
            self.assertEqual((dev_root / "AGENTS.md").read_text(encoding="utf-8").strip(), "# My Existing Workspace Notes\nKeep me!")
            claude_after = json.loads((fake_home / ".claude.json").read_text(encoding="utf-8"))
            self.assertIn("other_tool", claude_after["mcpServers"])
            self.assertNotIn("chimera", claude_after["mcpServers"])
            self.assertNotIn("[mcp_servers.chimera]", (fake_home / ".codex" / "config.toml").read_text(encoding="utf-8"))
            t3_after = json.loads((t3_prof / "mcp_config.json").read_text(encoding="utf-8"))
            self.assertNotIn("chimera", t3_after["mcpServers"])
            self.assertEqual((fake_home / ".codex" / "AGENTS.md").read_text(encoding="utf-8").strip(), "# Codex Global")
            self.assertFalse((fake_home / ".gemini" / "AGENTS.md").exists())

    def test_02_unified_openai_gateway_models_embeddings_and_chat_passthrough(self) -> None:
        # Mock local tquota LLM relay
        class RelayH(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                if self.path == "/v1/models":
                    b = json.dumps({"object": "list", "data": [{"id": "claude-sonnet-relay", "object": "model"}]}).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(b)))
                    self.end_headers()
                    self.wfile.write(b)

            def do_POST(self) -> None:
                clen = int(self.headers.get("Content-Length", "0") or 0)
                body = json.loads(self.rfile.read(clen).decode() or "{}")
                b = json.dumps({
                    "id": "chatcmpl-test",
                    "object": "chat.completion",
                    "model": body.get("model", "unknown"),
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": "unified-ok"}}],
                }).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

            def log_message(self, *_a: object) -> None:
                pass

        relay = http.server.ThreadingHTTPServer(("127.0.0.1", 0), RelayH)
        rport = relay.server_address[1]
        threading.Thread(target=relay.serve_forever, daemon=True).start()

        tmp = tempfile.TemporaryDirectory()
        cfg = OpsConfig(
            node_name="unify-test",
            role="controller",
            dashboard_bind="127.0.0.1:0",
            beam_port=0,
            rpc_v4_port=0,
            rpc_v6_port=-1,
            query_port=0,
            warp_port=-1,
            edge_proxy_port=-1,
            allowed_query_roots=[tmp.name],
            search_roots=[tmp.name],
            edge_targets={},
            phantom_enabled=False,
            tquota_relay_url=f"http://127.0.0.1:{rport}",
        )
        daemon = ChimeraDaemon(config=cfg, ops_dir=Path(tmp.name) / "ops", auto_seed_on_empty=False).start()
        try:
            anchor = daemon.platform.anchor_url
            # 1. GET /v1/openai/v1/models merges Chimera VGPU + tquota relay models
            with urllib.request.urlopen(f"{anchor}/v1/openai/v1/models", timeout=5.0) as r:
                mods = json.loads(r.read().decode("utf-8"))
            ids = {m["id"] for m in mods["data"]}
            self.assertIn("chimera-colab-elastic", ids)
            self.assertIn("claude-sonnet-relay", ids)

            # 2. POST /v1/openai/v1/chat/completions transparently passes through to tquota relay
            req_c = urllib.request.Request(
                f"{anchor}/v1/openai/v1/chat/completions",
                data=json.dumps({"model": "claude-sonnet-relay", "messages": [{"role": "user", "content": "hi"}]}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req_c, timeout=5.0) as r:
                chat = json.loads(r.read().decode("utf-8"))
            self.assertEqual(chat["choices"][0]["message"]["content"], "unified-ok")
            self.assertIn(f":{rport}/v1/chat/completions", chat["chimera_relay_via"])

            # 3. POST /v1/openai/v1/embeddings stays inside CHIMERA VGPU ($0)
            req_e = urllib.request.Request(
                f"{anchor}/v1/openai/v1/embeddings",
                data=json.dumps({"input": ["one unified gateway"], "dimensions": 64}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req_e, timeout=5.0) as r:
                emb = json.loads(r.read().decode("utf-8"))
            self.assertEqual(len(emb["data"][0]["embedding"]), 64)
        finally:
            daemon.close()
            relay.shutdown()
            relay.server_close()
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
