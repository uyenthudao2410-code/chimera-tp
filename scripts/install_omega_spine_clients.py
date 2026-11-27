#!/usr/bin/env python3
"""Idempotent Omega-Spine universal client installer.

Configures Streamable HTTP MCP (`http://127.0.0.1:9780/mcp`), Antigravity native plugin
`chimera-cortex` (including sub-2ms `chimera-hook` lifecycle hooks), MCP instructions,
global routing rules (`GEMINI.md` / `AGENTS.md`), and Claude Code / Codex MCP entries.

Modes:
  --dry-run   Preview all planned actions without modifying any files (default if no mode given)
  --check     Read-only compliance check (exit 0 if synced, 1 if missing/drifted)
  --install   Apply all changes atomically and idempotently
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tempfile
from pathlib import Path
from typing import Any

DEFAULT_MCP_URL = "http://127.0.0.1:9780/mcp"
PLUGIN_NAME = "chimera-cortex"

AGENT_BUS_BEGIN = "<!-- CHIMERA-UNIFY-AGENT-BUS-BEGIN -->"
AGENT_BUS_END = "<!-- CHIMERA-UNIFY-AGENT-BUS-END -->"
OMEGA_RULE_BEGIN = "<!-- CHIMERA-OMEGA-SPINE-BEGIN -->"
OMEGA_RULE_END = "<!-- CHIMERA-OMEGA-SPINE-END -->"
CODEX_TOML_BEGIN = "# CHIMERA-UNIFY-MCP-BEGIN"
CODEX_TOML_END = "# CHIMERA-UNIFY-MCP-END"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _atomic_write_bytes(path: Path, data: bytes) -> bool:
    """Write bytes atomically only if content changed. Returns True if written."""
    if path.is_file():
        try:
            if path.read_bytes() == data:
                return False
        except OSError:
            pass
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return True


def _atomic_write_text(path: Path, text: str) -> bool:
    return _atomic_write_bytes(path, text.encode("utf-8"))


def _upsert_marked_block(existing: str, begin: str, end: str, body: str) -> str:
    wrapped = f"{begin}\n{body.rstrip()}\n{end}\n"
    pat = re.compile(re.escape(begin) + r".*?" + re.escape(end) + r"\r?\n?", re.S)
    if pat.search(existing):
        return pat.sub(lambda _m: wrapped, existing, count=1)
    sep = "\n" if existing and not existing.endswith("\n") else ""
    gap = "\n" if existing.strip() else ""
    return f"{existing}{sep}{gap}{wrapped}"


def _format_hook_command(bin_path: Path, event_name: str) -> str:
    raw = str(bin_path)
    if any(ch.isspace() for ch in raw):
        return f'"{raw}" {event_name}'
    return f"{raw} {event_name}"


def _build_hooks_json(hook_bin: Path) -> dict[str, Any]:
    return {
        "chimera-omega-spine": {
            "enabled": True,
            "SessionStart": [
                {
                    "type": "command",
                    "command": _format_hook_command(hook_bin, "session_start"),
                    "timeout": 5,
                }
            ],
            "PreToolUse": [
                {
                    "matcher": "edit_file|write_file|run_command",
                    "hooks": [
                        {
                            "type": "command",
                            "command": _format_hook_command(hook_bin, "pre_tool_use"),
                            "timeout": 5,
                        }
                    ],
                }
            ],
            "PostToolUse": [
                {
                    "matcher": "edit_file|write_file|run_command",
                    "hooks": [
                        {
                            "type": "command",
                            "command": _format_hook_command(hook_bin, "post_tool_use"),
                            "timeout": 5,
                        }
                    ],
                }
            ],
            "PreInvocation": [
                {
                    "type": "command",
                    "command": _format_hook_command(hook_bin, "pre_invocation"),
                    "timeout": 5,
                }
            ],
            "Stop": [
                {
                    "type": "command",
                    "command": _format_hook_command(hook_bin, "stop"),
                    "timeout": 5,
                }
            ],
        }
    }


def _build_omega_routing_rule(mcp_url: str) -> str:
    return (
        "## CHIMERA Omega-Spine Cognitive Hypervisor (Streamable HTTP MCP + Hooks)\n\n"
        f"When MCP server `chimera` (`{mcp_url}`) is active, use its 6 Eager Super-Tools with an explicit absolute `repo` path:\n"
        "- **Cold-start orientation (1 call, `<25 ms`):** Call `chimera_bootstrap(repo=...)` instead of serial `ls`/`git status` turns.\n"
        "- **C#/Py/JS Surgical Teleport BEFORE slicing large files:** Call `chimera_surgical_bundle(repo=..., symbol=...)` (`<= 8 KB`: definition + 2-hop callers/callees + related types + tests).\n"
        "- **Zero-spawn batch inspection:** Batch `outline`, `list_files`, `regex_search`, `file_slice`, `git_status`, and `surgical_bundle` into one `chimera_xray_batch(repo=..., ops=[...])` call.\n"
        "- **Atomic edits + Iron-Cage verify:** Use `chimera_atomic_patch` (in-RAM syntax gate + rollback) and `chimera_commit_verify` (BLAKE2s-cached impacted `dotnet test`/`pytest`/`node --test`).\n"
        "- **Swarm memory & safety:** Use `chimera_hive_cortex` (`lease`, `put_capsule`, `recall_capsules`, `antibodies`, `tournament_run`, `cage_status`)."
    )


def _resolve_hook_binary(repo_root: Path, hook_bin_override: str | None) -> Path:
    if hook_bin_override:
        return Path(hook_bin_override).resolve()
    bin_name = "chimera-hook.exe" if os.name == "nt" else "chimera-hook"
    return (repo_root / "bin" / bin_name).resolve()


def _discover_t3_antigravity_profiles(home: Path) -> list[Path]:
    root = home / ".t3" / "userdata" / "providers" / "antigravity"
    if not root.is_dir():
        return []
    profiles: list[Path] = []
    try:
        for child in sorted(root.iterdir()):
            if child.is_dir() and ((child / "config").is_dir() or (child / "antigravity-acp").is_dir()):
                profiles.append(child)
    except OSError:
        pass
    return profiles


def _plan_json_mcp_update(
    target_name: str,
    path: Path,
    desired_entry: dict[str, Any],
    mode: str,
) -> dict[str, Any]:
    exists = path.is_file()
    raw = path.read_text(encoding="utf-8", errors="ignore").strip() if exists else ""
    try:
        data = json.loads(raw) if raw else {}
    except json.JSONDecodeError as exc:
        return {"target": target_name, "path": str(path), "status": "error", "error": f"invalid JSON: {exc}"}
    if not isinstance(data, dict):
        return {"target": target_name, "path": str(path), "status": "error", "error": "top-level JSON is not object"}

    servers = data.get("mcpServers")
    if not isinstance(servers, dict):
        servers = {}
        data["mcpServers"] = servers

    if servers.get("chimera") == desired_entry:
        return {"target": target_name, "path": str(path), "status": "synced"}

    if mode == "install":
        servers["chimera"] = desired_entry
        _atomic_write_text(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        return {"target": target_name, "path": str(path), "status": "updated"}
    return {
        "target": target_name,
        "path": str(path),
        "status": "needs_update" if exists else "missing",
    }


def _plan_text_file(target_name: str, path: Path, desired_text: str, mode: str) -> dict[str, Any]:
    desired_bytes = desired_text.encode("utf-8")
    exists = path.is_file()
    if exists:
        try:
            if path.read_bytes() == desired_bytes:
                return {"target": target_name, "path": str(path), "status": "synced"}
        except OSError:
            pass
    if mode == "install":
        _atomic_write_bytes(path, desired_bytes)
        return {"target": target_name, "path": str(path), "status": "updated"}
    return {
        "target": target_name,
        "path": str(path),
        "status": "needs_update" if exists else "missing",
    }


def _plan_marked_markdown(
    target_name: str,
    path: Path,
    begin: str,
    end: str,
    body: str,
    mode: str,
) -> dict[str, Any]:
    exists = path.is_file()
    prev = path.read_text(encoding="utf-8", errors="ignore") if exists else ""
    updated = _upsert_marked_block(prev, begin, end, body)
    if exists and prev == updated:
        return {"target": target_name, "path": str(path), "status": "synced"}
    if mode == "install":
        _atomic_write_text(path, updated)
        return {"target": target_name, "path": str(path), "status": "updated"}
    return {
        "target": target_name,
        "path": str(path),
        "status": "needs_update" if exists else "missing",
    }


def _plan_plugin_install(
    target_name: str,
    plugin_src: Path,
    plugin_dst: Path,
    mcp_url: str,
    hook_bin: Path,
    mode: str,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    # Determine effective hook binary path for installed plugin:
    # Copy binary into <plugin_dst>/bin/<name> if source binary exists so plugin is self-contained.
    effective_hook_bin = hook_bin
    if hook_bin.is_file():
        dst_bin = plugin_dst / "bin" / hook_bin.name
        effective_hook_bin = dst_bin
        src_bytes = hook_bin.read_bytes()
        bin_synced = dst_bin.is_file() and _sha256_bytes(dst_bin.read_bytes()) == _sha256_bytes(src_bytes)
        if bin_synced:
            records.append({"target": f"{target_name}:hook_bin", "path": str(dst_bin), "status": "synced"})
        elif mode == "install":
            _atomic_write_bytes(dst_bin, src_bytes)
            if os.name != "nt":
                cur_mode = dst_bin.stat().st_mode
                dst_bin.chmod(cur_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            records.append({"target": f"{target_name}:hook_bin", "path": str(dst_bin), "status": "updated"})
        else:
            records.append({
                "target": f"{target_name}:hook_bin",
                "path": str(dst_bin),
                "status": "needs_update" if dst_bin.is_file() else "missing",
            })

    # Dynamic JSON manifests rendered with active URL & hook binary path
    mcp_cfg_text = json.dumps({"mcpServers": {"chimera": {"url": mcp_url}}}, indent=2) + "\n"
    hooks_cfg_text = json.dumps(_build_hooks_json(effective_hook_bin), indent=2) + "\n"

    static_files = [
        "plugin.json",
        "rules/AGENTS.md",
        "skills/chimera-omega-spine/SKILL.md",
        "mcp_instructions.md",
    ]
    for rel in static_files:
        src_file = plugin_src / rel
        if not src_file.is_file():
            records.append({
                "target": f"{target_name}:{rel}",
                "path": str(plugin_dst / rel),
                "status": "error",
                "error": f"missing plugin source: {src_file}",
            })
            continue
        content = src_file.read_text(encoding="utf-8")
        records.append(_plan_text_file(f"{target_name}:{rel}", plugin_dst / rel, content, mode))

    records.append(_plan_text_file(f"{target_name}:mcp_config.json", plugin_dst / "mcp_config.json", mcp_cfg_text, mode))
    records.append(_plan_text_file(f"{target_name}:hooks.json", plugin_dst / "hooks.json", hooks_cfg_text, mode))
    return records


def run_installer(
    *,
    mode: str,
    home_dir: Path | None = None,
    repo_root: Path | None = None,
    mcp_url: str = DEFAULT_MCP_URL,
    hook_bin_override: str | None = None,
) -> dict[str, Any]:
    if mode not in ("install", "check", "dry-run"):
        raise ValueError(f"unsupported mode: {mode}")

    home = Path(home_dir).resolve() if home_dir else Path.home().resolve()
    root = Path(repo_root).resolve() if repo_root else Path(__file__).resolve().parent.parent
    plugin_src = root / "plugins" / PLUGIN_NAME
    hook_bin = _resolve_hook_binary(root, hook_bin_override)

    if not plugin_src.is_dir():
        return {
            "ok": False,
            "mode": mode,
            "error": f"plugin source directory not found: {plugin_src}",
            "items": [],
        }

    instructions_src = plugin_src / "mcp_instructions.md"
    instructions_text = instructions_src.read_text(encoding="utf-8") if instructions_src.is_file() else ""
    rule_body = _build_omega_routing_rule(mcp_url)

    ag_mcp_entry = {"url": mcp_url}
    claude_mcp_entry = {"type": "http", "url": mcp_url}

    items: list[dict[str, Any]] = []

    # 1. Antigravity IDE / CLI (~/.gemini)
    gemini_dir = home / ".gemini"
    if gemini_dir.is_dir():
        items.append(
            _plan_json_mcp_update(
                "antigravity_ide:mcp_config",
                gemini_dir / "antigravity" / "mcp_config.json",
                ag_mcp_entry,
                mode,
            )
        )
        items.append(
            _plan_json_mcp_update(
                "antigravity_cli:mcp_config",
                gemini_dir / "config" / "mcp_config.json",
                ag_mcp_entry,
                mode,
            )
        )
        items.extend(
            _plan_plugin_install(
                "antigravity_global_plugin",
                plugin_src,
                gemini_dir / "config" / "plugins" / PLUGIN_NAME,
                mcp_url,
                hook_bin,
                mode,
            )
        )
        if instructions_text:
            items.append(
                _plan_text_file(
                    "antigravity_ide:mcp_instructions",
                    gemini_dir / "antigravity" / "mcp" / "chimera" / "instructions.md",
                    instructions_text,
                    mode,
                )
            )
        # Upgrade AGENTS.md marked block (replaces legacy CHIMERA-UNIFY-AGENT-BUS block cleanly)
        agents_md = gemini_dir / "AGENTS.md"
        items.append(
            _plan_marked_markdown(
                "gemini:AGENTS.md",
                agents_md,
                AGENT_BUS_BEGIN,
                AGENT_BUS_END,
                rule_body,
                mode,
            )
        )
        # Upsert concise marked block in GEMINI.md preserving all existing user rules
        gemini_md = gemini_dir / "GEMINI.md"
        if gemini_md.is_file():
            items.append(
                _plan_marked_markdown(
                    "gemini:GEMINI.md",
                    gemini_md,
                    OMEGA_RULE_BEGIN,
                    OMEGA_RULE_END,
                    rule_body,
                    mode,
                )
            )

    # 2. T3 Antigravity ACP isolated account profiles
    for prof in _discover_t3_antigravity_profiles(home):
        tag = f"t3_acp:{prof.name[:10]}"
        items.append(
            _plan_json_mcp_update(
                f"{tag}:mcp_config",
                prof / "config" / "mcp_config.json",
                ag_mcp_entry,
                mode,
            )
        )
        items.extend(
            _plan_plugin_install(
                f"{tag}:plugin",
                plugin_src,
                prof / "config" / "plugins" / PLUGIN_NAME,
                mcp_url,
                hook_bin,
                mode,
            )
        )
        if instructions_text and (prof / "antigravity-acp").is_dir():
            items.append(
                _plan_text_file(
                    f"{tag}:mcp_instructions",
                    prof / "antigravity-acp" / "mcp" / "chimera" / "instructions.md",
                    instructions_text,
                    mode,
                )
            )
        prof_agents = prof / "AGENTS.md"
        if prof_agents.is_file():
            items.append(
                _plan_marked_markdown(
                    f"{tag}:AGENTS.md",
                    prof_agents,
                    AGENT_BUS_BEGIN,
                    AGENT_BUS_END,
                    rule_body,
                    mode,
                )
            )

    # 3. Claude Code (~/.claude.json) - migrate only if config exists
    claude_json = home / ".claude.json"
    if claude_json.is_file():
        items.append(
            _plan_json_mcp_update(
                "claude_code:mcp_config",
                claude_json,
                claude_mcp_entry,
                mode,
            )
        )

    # 4. Codex (~/.codex/config.toml & AGENTS.md) - migrate only if present
    codex_dir = home / ".codex"
    codex_toml = codex_dir / "config.toml"
    if codex_toml.is_file():
        prev_toml = codex_toml.read_text(encoding="utf-8", errors="ignore")
        codex_block = f'[mcp_servers.chimera]\nurl = "{mcp_url}"'
        updated_toml = _upsert_marked_block(prev_toml, CODEX_TOML_BEGIN, CODEX_TOML_END, codex_block)
        if prev_toml == updated_toml:
            items.append({"target": "codex:config.toml", "path": str(codex_toml), "status": "synced"})
        elif mode == "install":
            _atomic_write_text(codex_toml, updated_toml)
            items.append({"target": "codex:config.toml", "path": str(codex_toml), "status": "updated"})
        else:
            items.append({"target": "codex:config.toml", "path": str(codex_toml), "status": "needs_update"})

    codex_agents = codex_dir / "AGENTS.md"
    if codex_agents.is_file():
        items.append(
            _plan_marked_markdown(
                "codex:AGENTS.md",
                codex_agents,
                AGENT_BUS_BEGIN,
                AGENT_BUS_END,
                rule_body,
                mode,
            )
        )

    counts = {
        "total": len(items),
        "synced": sum(1 for x in items if x["status"] == "synced"),
        "updated": sum(1 for x in items if x["status"] == "updated"),
        "needs_update": sum(1 for x in items if x["status"] == "needs_update"),
        "missing": sum(1 for x in items if x["status"] == "missing"),
        "errors": sum(1 for x in items if x["status"] == "error"),
    }

    if mode == "check":
        ok = counts["errors"] == 0 and counts["needs_update"] == 0 and counts["missing"] == 0
    elif mode == "install":
        ok = counts["errors"] == 0
    else:  # dry-run
        ok = counts["errors"] == 0

    return {
        "ok": ok,
        "mode": mode,
        "home": str(home),
        "repo_root": str(root),
        "mcp_url": mcp_url,
        "hook_bin": str(hook_bin),
        "hook_bin_exists": hook_bin.is_file(),
        "counts": counts,
        "items": items,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Install/verify Chimera Omega-Spine Streamable HTTP MCP, native plugin & hooks across AI clients."
    )
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--install", action="store_true", help="Apply all client configurations idempotently")
    mode_group.add_argument("--check", action="store_true", help="Check whether all detected clients are synced")
    mode_group.add_argument("--dry-run", action="store_true", help="Preview planned actions without modifying files")
    parser.add_argument("--home", type=str, default=None, help="Override home directory (for testing/staging)")
    parser.add_argument("--repo-root", type=str, default=None, help="Override chimera-tp repo root")
    parser.add_argument("--url", type=str, default=DEFAULT_MCP_URL, help=f"Streamable HTTP MCP URL (default: {DEFAULT_MCP_URL})")
    parser.add_argument("--hook-bin", type=str, default=None, help="Override path to chimera-hook executable")
    parser.add_argument("--json", action="store_true", dest="as_json", help="Emit JSON summary to stdout")

    args = parser.parse_args(argv)
    if args.install:
        mode = "install"
    elif args.check:
        mode = "check"
    else:
        mode = "dry-run"

    result = run_installer(
        mode=mode,
        home_dir=Path(args.home) if args.home else None,
        repo_root=Path(args.repo_root) if args.repo_root else None,
        mcp_url=args.url,
        hook_bin_override=args.hook_bin,
    )

    if args.as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        c = result["counts"]
        print(
            f"[omega-spine installer] mode={mode} ok={result['ok']} "
            f"total={c['total']} synced={c['synced']} updated={c['updated']} "
            f"needs_update={c['needs_update']} missing={c['missing']} errors={c['errors']}"
        )
        for item in result["items"]:
            err = f" ({item['error']})" if "error" in item else ""
            print(f"  - [{item['status']:12s}] {item['target']} -> {item['path']}{err}")

    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
