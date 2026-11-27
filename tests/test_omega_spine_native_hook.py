"""Tests for Project OMEGA-SPINE native hook binaries, Antigravity plugin, and client installer."""

from __future__ import annotations

import json
import os
import socket
import statistics
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK_EXE = REPO_ROOT / "bin" / ("chimera-hook.exe" if os.name == "nt" else "chimera-hook")
HOOK_RS = REPO_ROOT / "native" / "chimera_hook_rs" / "chimera_hook.rs"
HOOK_C = REPO_ROOT / "native" / "chimera_hook_c" / "chimera_hook.c"
PLUGIN_DIR = REPO_ROOT / "plugins" / "chimera-cortex"
INSTALLER_SCRIPT = REPO_ROOT / "scripts" / "install_omega_spine_clients.py"

sys.path.insert(0, str(REPO_ROOT / "scripts"))
import install_omega_spine_clients as installer  # noqa: E402


class _MockHookServer:
    def __init__(self) -> None:
        self.received: list[dict[str, Any]] = []
        self.mode: str = "ok"
        self.delay_s: float = 0.0
        parent = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
                return

            def do_POST(self) -> None:  # noqa: N802
                cl = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(cl) if cl > 0 else b""
                parent.received.append({
                    "path": self.path,
                    "content_type": self.headers.get("Content-Type", ""),
                    "body": raw,
                })
                if parent.delay_s > 0:
                    time.sleep(parent.delay_s)

                if parent.mode == "status_500":
                    payload = b'{"error":"boom"}'
                    self.send_response(500)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    self.send_header("Connection", "close")
                    self.end_headers()
                    self.wfile.write(payload)
                    return

                if parent.mode == "non_json":
                    payload = b"<html><body>502 Bad Gateway</body></html>"
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html")
                    self.send_header("Content-Length", str(len(payload)))
                    self.send_header("Connection", "close")
                    self.end_headers()
                    self.wfile.write(payload)
                    return

                if parent.mode == "chunked":
                    event = self.path.rsplit("/", 1)[-1]
                    body = json.dumps({"ok": True, "chunked": True, "event": event}).encode("utf-8")
                    mid = len(body) // 2
                    c1, c2 = body[:mid], body[mid:]
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Transfer-Encoding", "chunked")
                    self.send_header("Connection", "close")
                    self.end_headers()
                    self.wfile.write(f"{len(c1):x}\r\n".encode("ascii") + c1 + b"\r\n")
                    self.wfile.write(f"{len(c2):x}\r\n".encode("ascii") + c2 + b"\r\n")
                    self.wfile.write(b"0\r\n\r\n")
                    return

                event = self.path.rsplit("/", 1)[-1]
                try:
                    parsed = json.loads(raw.decode("utf-8"))
                except Exception:
                    parsed = {"raw_len": len(raw)}

                if event == "pre_tool_use":
                    resp = {"decision": "allow", "reason": "verified", "echo": parsed}
                elif event == "session_start":
                    resp = {
                        "injectSteps": [
                            {"systemMessage": {"systemMessage": "Omega-Spine live"}}
                        ],
                        "echo": parsed,
                    }
                elif event == "stop":
                    resp = {"decision": "continue", "reason": "precog check"}
                else:
                    resp = {"ok": True, "event": event, "echo": parsed}

                payload = json.dumps(resp, separators=(",", ":")).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(payload)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


@pytest.fixture()
def mock_hook_server():
    srv = _MockHookServer()
    try:
        yield srv
    finally:
        srv.close()


def _run_hook(event: str, stdin_bytes: bytes, url: str, extra_env: dict[str, str] | None = None) -> tuple[subprocess.CompletedProcess[bytes], float]:
    env = os.environ.copy()
    env["CHIMERA_HOOK_URL"] = url
    if extra_env:
        env.update(extra_env)
    t0 = time.perf_counter()
    proc = subprocess.run(
        [str(HOOK_EXE), event],
        input=stdin_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        timeout=5,
        check=False,
    )
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    return proc, elapsed_ms


def _unused_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def test_native_hook_binary_and_sources_exist() -> None:
    assert HOOK_RS.is_file(), f"Missing Rust source: {HOOK_RS}"
    assert HOOK_C.is_file(), f"Missing C source: {HOOK_C}"
    assert HOOK_EXE.is_file(), f"Missing compiled hook binary: {HOOK_EXE}"
    assert HOOK_EXE.stat().st_size > 10_000

    c_src = HOOK_C.read_text(encoding="utf-8")
    for token in ("CHIMERA_HOOK_URL", "/v1/hook/", "TCP_NODELAY", "SIGPIPE", r'{\"decision\":\"allow\"}', "poll("):
        assert token in c_src, f"Expected POSIX token {token!r} in chimera_hook.c"


def test_hook_e2e_forwarding_and_latency(mock_hook_server: _MockHookServer) -> None:
    events = [
        ("session_start", {"conversationId": "conv-1", "workspacePaths": ["E:/dev/chimera-tp"]}),
        ("pre_tool_use", {"conversationId": "conv-1", "toolCall": {"name": "edit_file", "args": {"Path": "a.cs"}}}),
        ("post_tool_use", {"conversationId": "conv-1", "toolCall": {"name": "edit_file"}, "stepIdx": 3}),
        ("pre_invocation", {"conversationId": "conv-1", "invocationNum": 2}),
        ("stop", {"conversationId": "conv-1", "terminationReason": "NO_TOOL_CALL", "continuationActive": False}),
    ]
    for ev, payload in events:
        raw_in = json.dumps(payload).encode("utf-8")
        proc, _ = _run_hook(ev, raw_in, mock_hook_server.url)
        assert proc.returncode == 0
        assert proc.stderr == b""
        out = json.loads(proc.stdout.decode("utf-8"))
        assert isinstance(out, dict)
        last = mock_hook_server.received[-1]
        assert last["path"] == f"/v1/hook/{ev}"
        assert last["content_type"] == "application/json"
        assert last["body"] == raw_in
        if ev == "pre_tool_use":
            assert out["decision"] == "allow"
            assert out["echo"] == payload
        elif ev == "session_start":
            assert out["injectSteps"][0]["systemMessage"]["systemMessage"] == "Omega-Spine live"
            assert out["echo"] == payload

    # Measure warm e2e execution latency (process spawn + loopback HTTP roundtrip)
    latencies_ms: list[float] = []
    probe_body = b'{"conversationId":"bench","invocationNum":1}'
    for _ in range(15):
        proc, ms = _run_hook("pre_invocation", probe_body, mock_hook_server.url)
        assert proc.returncode == 0
        assert json.loads(proc.stdout.decode("utf-8"))["ok"] is True
        latencies_ms.append(ms)

    p50_ms = statistics.median(latencies_ms)
    assert p50_ms < 25.0, f"Expected < 25 ms e2e p50 latency, got {p50_ms:.2f} ms ({latencies_ms})"


def test_hook_chunked_and_large_payload(mock_hook_server: _MockHookServer) -> None:
    mock_hook_server.mode = "chunked"
    proc, _ = _run_hook("pre_invocation", b'{"a":1}', mock_hook_server.url)
    assert proc.returncode == 0
    assert json.loads(proc.stdout.decode("utf-8")) == {"ok": True, "chunked": True, "event": "pre_invocation"}

    mock_hook_server.mode = "ok"
    big = json.dumps({"blob": "x" * 128_000}).encode("utf-8")
    proc2, _ = _run_hook("post_tool_use", big, mock_hook_server.url)
    assert proc2.returncode == 0
    out2 = json.loads(proc2.stdout.decode("utf-8"))
    assert len(out2["echo"]["blob"]) == 128_000


def test_hook_fail_open_closed_port_under_300ms() -> None:
    dead_port = _unused_loopback_port()
    dead_url = f"http://127.0.0.1:{dead_port}"

    proc1, ms1 = _run_hook("session_start", b'{"conversationId":"dead"}', dead_url)
    assert proc1.returncode == 0
    assert json.loads(proc1.stdout.decode("utf-8")) == {}
    assert ms1 < 300.0, f"Fail-open on closed port took {ms1:.1f} ms (>= 300 ms)"

    proc2, ms2 = _run_hook("pre_tool_use", b'{"toolCall":{"name":"run_command"}}', dead_url)
    assert proc2.returncode == 0
    assert json.loads(proc2.stdout.decode("utf-8")) == {"decision": "allow"}
    assert ms2 < 300.0, f"PreToolUse fail-open on closed port took {ms2:.1f} ms (>= 300 ms)"


def test_hook_fail_open_errors_and_malformed_stdin(mock_hook_server: _MockHookServer) -> None:
    # HTTP 500 -> fail-open
    mock_hook_server.mode = "status_500"
    p500, _ = _run_hook("pre_tool_use", b"{}", mock_hook_server.url)
    assert p500.returncode == 0
    assert json.loads(p500.stdout.decode("utf-8")) == {"decision": "allow"}

    # Non-JSON 200 HTML -> fail-open
    mock_hook_server.mode = "non_json"
    phtml, _ = _run_hook("post_tool_use", b"{}", mock_hook_server.url)
    assert phtml.returncode == 0
    assert json.loads(phtml.stdout.decode("utf-8")) == {}

    # Server read timeout -> fail-open
    mock_hook_server.mode = "ok"
    mock_hook_server.delay_s = 0.8
    ptmo, ms_tmo = _run_hook(
        "stop",
        b"{}",
        mock_hook_server.url,
        extra_env={"CHIMERA_HOOK_IO_TIMEOUT_MS": "200"},
    )
    assert ptmo.returncode == 0
    assert json.loads(ptmo.stdout.decode("utf-8")) == {}
    assert ms_tmo < 600.0
    mock_hook_server.delay_s = 0.0

    # Malformed stdin, empty stdin, invalid UTF-8 bytes -> zero crash
    for bad_in in (b"{{{not valid json", b"", b"\xff\xfe\x00\x01"):
        pbad, _ = _run_hook("post_tool_use", bad_in, mock_hook_server.url)
        assert pbad.returncode == 0
        parsed = json.loads(pbad.stdout.decode("utf-8"))
        assert isinstance(parsed, dict)


def test_plugin_bundle_schemas() -> None:
    plugin_json = json.loads((PLUGIN_DIR / "plugin.json").read_text(encoding="utf-8"))
    assert plugin_json["name"] == "chimera-cortex"
    assert plugin_json["displayName"] == "Chimera Cortex"
    assert "Omega-Spine" in plugin_json["description"]

    mcp_cfg = json.loads((PLUGIN_DIR / "mcp_config.json").read_text(encoding="utf-8"))
    assert mcp_cfg == {"mcpServers": {"chimera": {"url": "http://127.0.0.1:9780/mcp"}}}

    hooks_cfg = json.loads((PLUGIN_DIR / "hooks.json").read_text(encoding="utf-8"))
    assert "chimera-omega-spine" in hooks_cfg
    spec = hooks_cfg["chimera-omega-spine"]
    assert spec.get("enabled") is True

    # Flat events
    for flat_ev, arg_ev in (
        ("SessionStart", "session_start"),
        ("PreInvocation", "pre_invocation"),
        ("Stop", "stop"),
    ):
        handlers = spec[flat_ev]
        assert isinstance(handlers, list) and len(handlers) == 1
        assert handlers[0]["type"] == "command"
        assert handlers[0]["timeout"] == 5
        assert "chimera-hook.exe" in handlers[0]["command"]
        assert handlers[0]["command"].endswith(arg_ev)

    # Grouped events with matcher
    for grp_ev, arg_ev in (("PreToolUse", "pre_tool_use"), ("PostToolUse", "post_tool_use")):
        groups = spec[grp_ev]
        assert isinstance(groups, list) and len(groups) == 1
        assert groups[0]["matcher"] == "edit_file|write_file|run_command"
        h = groups[0]["hooks"][0]
        assert h["type"] == "command"
        assert h["timeout"] == 5
        assert "chimera-hook.exe" in h["command"]
        assert h["command"].endswith(arg_ev)

    # Rules, Skill, Instructions
    rules_md = (PLUGIN_DIR / "rules" / "AGENTS.md").read_text(encoding="utf-8")
    for tool in (
        "chimera_bootstrap",
        "chimera_xray_batch",
        "chimera_surgical_bundle",
        "chimera_atomic_patch",
        "chimera_commit_verify",
        "chimera_hive_cortex",
    ):
        assert tool in rules_md

    skill_md = (PLUGIN_DIR / "skills" / "chimera-omega-spine" / "SKILL.md").read_text(encoding="utf-8")
    assert skill_md.startswith("---\n")
    assert "name: chimera-omega-spine" in skill_md
    assert "description:" in skill_md

    instr_md = (PLUGIN_DIR / "mcp_instructions.md").read_text(encoding="utf-8")
    assert "chimera_surgical_bundle" in instr_md
    assert "http://127.0.0.1:9780/mcp" in instr_md


def test_client_installer_dry_run_install_check_idempotent(tmp_path: Path) -> None:
    fake_home = tmp_path / "home"
    # Populate realistic Antigravity IDE, CLI, T3 ACP, Claude Code, and Codex fixtures
    (fake_home / ".gemini" / "antigravity").mkdir(parents=True)
    (fake_home / ".gemini" / "config").mkdir(parents=True)
    (fake_home / ".gemini" / "antigravity" / "mcp_config.json").write_text(
        json.dumps({"mcpServers": {"chimera": {"command": "python.exe", "args": ["-m", "chimera_tp", "mcp"]}}}),
        encoding="utf-8",
    )
    (fake_home / ".gemini" / "config" / "mcp_config.json").write_text(
        json.dumps({
            "mcpServers": {
                "stitch": {"serverUrl": "https://stitch.googleapis.com/mcp"},
                "chimera": {"command": "python.exe", "args": ["-m", "chimera_tp", "mcp"]},
            }
        }),
        encoding="utf-8",
    )
    (fake_home / ".gemini" / "GEMINI.md").write_text("# User Custom Policy\nKeep me intact.\n", encoding="utf-8")
    (fake_home / ".gemini" / "AGENTS.md").write_text(
        "<!-- CHIMERA-UNIFY-AGENT-BUS-BEGIN -->\nlegacy rule\n<!-- CHIMERA-UNIFY-AGENT-BUS-END -->\n",
        encoding="utf-8",
    )

    t3_prof = fake_home / ".t3" / "userdata" / "providers" / "antigravity" / "abcdef1234567890"
    (t3_prof / "config").mkdir(parents=True)
    (t3_prof / "antigravity-acp").mkdir(parents=True)
    (t3_prof / "config" / "mcp_config.json").write_text(
        json.dumps({"mcpServers": {"chimera": {"command": "python.exe", "args": ["-m", "chimera_tp", "mcp"]}}}),
        encoding="utf-8",
    )
    (t3_prof / "AGENTS.md").write_text(
        "<!-- CHIMERA-UNIFY-AGENT-BUS-BEGIN -->\nold t3\n<!-- CHIMERA-UNIFY-AGENT-BUS-END -->\n",
        encoding="utf-8",
    )

    (fake_home / ".claude.json").write_text(
        json.dumps({
            "mcpServers": {
                "autocad-mcp": {"command": "python.exe", "args": ["cad.py"]},
                "chimera": {"command": "python.exe", "args": ["-m", "chimera_tp", "mcp"]},
            }
        }),
        encoding="utf-8",
    )
    (fake_home / ".codex").mkdir(parents=True)
    (fake_home / ".codex" / "config.toml").write_text(
        '[mcp_servers.node_repl]\ncommand = "node_repl.exe"\n\n'
        '# CHIMERA-UNIFY-MCP-BEGIN\n[mcp_servers.chimera]\ncommand = "python.exe"\nargs = ["-m", "chimera_tp", "mcp"]\n# CHIMERA-UNIFY-MCP-END\n',
        encoding="utf-8",
    )

    # 1. Dry-run must NOT modify anything
    dry = installer.run_installer(mode="dry-run", home_dir=fake_home, repo_root=REPO_ROOT)
    assert dry["ok"] is True
    assert dry["counts"]["updated"] == 0
    assert (dry["counts"]["needs_update"] + dry["counts"]["missing"]) > 0
    assert not (fake_home / ".gemini" / "config" / "plugins" / "chimera-cortex").exists()

    # 2. Check before install must return ok=False
    chk_before = installer.run_installer(mode="check", home_dir=fake_home, repo_root=REPO_ROOT)
    assert chk_before["ok"] is False

    # 3. Install via CLI subprocess to test argparse + exit code
    proc = subprocess.run(
        [sys.executable, str(INSTALLER_SCRIPT), "--install", "--home", str(fake_home), "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    inst = json.loads(proc.stdout)
    assert inst["ok"] is True
    assert inst["counts"]["errors"] == 0
    assert inst["counts"]["updated"] > 0

    # Verify unrelated servers preserved and chimera migrated to Streamable HTTP
    ag_cli_mcp = json.loads((fake_home / ".gemini" / "config" / "mcp_config.json").read_text(encoding="utf-8"))
    assert ag_cli_mcp["mcpServers"]["stitch"]["serverUrl"] == "https://stitch.googleapis.com/mcp"
    assert ag_cli_mcp["mcpServers"]["chimera"] == {"url": "http://127.0.0.1:9780/mcp"}

    ag_ide_mcp = json.loads((fake_home / ".gemini" / "antigravity" / "mcp_config.json").read_text(encoding="utf-8"))
    assert ag_ide_mcp["mcpServers"]["chimera"] == {"url": "http://127.0.0.1:9780/mcp"}

    t3_mcp = json.loads((t3_prof / "config" / "mcp_config.json").read_text(encoding="utf-8"))
    assert t3_mcp["mcpServers"]["chimera"] == {"url": "http://127.0.0.1:9780/mcp"}

    claude_cfg = json.loads((fake_home / ".claude.json").read_text(encoding="utf-8"))
    assert "autocad-mcp" in claude_cfg["mcpServers"]
    assert claude_cfg["mcpServers"]["chimera"] == {"type": "http", "url": "http://127.0.0.1:9780/mcp"}

    codex_toml = (fake_home / ".codex" / "config.toml").read_text(encoding="utf-8")
    assert "[mcp_servers.node_repl]" in codex_toml
    assert 'url = "http://127.0.0.1:9780/mcp"' in codex_toml
    assert 'command = "python.exe"' not in codex_toml

    # Verify GEMINI.md preserved existing user policy + added Omega-Spine block
    gemini_md = (fake_home / ".gemini" / "GEMINI.md").read_text(encoding="utf-8")
    assert "# User Custom Policy\nKeep me intact." in gemini_md
    assert "<!-- CHIMERA-OMEGA-SPINE-BEGIN -->" in gemini_md
    assert "chimera_surgical_bundle" in gemini_md

    # Verify plugin installed at both global & T3 profile paths with self-contained hook binary
    for plugin_dst in (
        fake_home / ".gemini" / "config" / "plugins" / "chimera-cortex",
        t3_prof / "config" / "plugins" / "chimera-cortex",
    ):
        assert (plugin_dst / "plugin.json").is_file()
        assert (plugin_dst / "mcp_config.json").is_file()
        assert (plugin_dst / "hooks.json").is_file()
        assert (plugin_dst / "rules" / "AGENTS.md").is_file()
        assert (plugin_dst / "skills" / "chimera-omega-spine" / "SKILL.md").is_file()
        assert (plugin_dst / "bin" / HOOK_EXE.name).is_file()

    assert (fake_home / ".gemini" / "antigravity" / "mcp" / "chimera" / "instructions.md").is_file()
    assert (t3_prof / "antigravity-acp" / "mcp" / "chimera" / "instructions.md").is_file()

    # 4. Check after install must exit 0 with ok=True
    chk_after = subprocess.run(
        [sys.executable, str(INSTALLER_SCRIPT), "--check", "--home", str(fake_home), "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert chk_after.returncode == 0
    assert json.loads(chk_after.stdout)["ok"] is True

    # 5. Re-running install must be 100% idempotent (0 updates)
    inst2 = installer.run_installer(mode="install", home_dir=fake_home, repo_root=REPO_ROOT)
    assert inst2["ok"] is True
    assert inst2["counts"]["updated"] == 0
    assert inst2["counts"]["synced"] == inst2["counts"]["total"]
