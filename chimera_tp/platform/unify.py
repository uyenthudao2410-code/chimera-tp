"""CHIMERA-UNIFY: 3-Layer Host-Wide Unified Connection (OS Runtime/venv + OpenAI Standard + AI Agent MCP/Beacon)."""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from .autoload import autoload_status, install_autoload, shared_autoload_dir
from .discovery import _atomic_write_text, chimera_home_dir, discover_runtime_file

_AGENTS_BEGIN = "<!-- CHIMERA-UNIFY-BEGIN -->"
_AGENTS_END = "<!-- CHIMERA-UNIFY-END -->"
_SHELL_BEGIN = "# CHIMERA-UNIFY-BEGIN"
_SHELL_END = "# CHIMERA-UNIFY-END"
_TOML_BEGIN = "# CHIMERA-UNIFY-MCP-BEGIN"
_TOML_END = "# CHIMERA-UNIFY-MCP-END"


def _default_dev_roots(home: Path) -> list[str]:
    roots: list[str] = []
    if os.name == "nt":
        for cand in (Path("E:/DEV"), home / "DEV", home / "dev"):
            if cand.is_dir():
                s = str(cand.resolve())
                if s not in roots:
                    roots.append(s)
    else:
        for cand in (home / "DEV", home / "dev"):
            if cand.is_dir():
                s = str(cand.resolve())
                if s not in roots:
                    roots.append(s)
    return roots


def _upsert_marked_block(existing: str, begin: str, end: str, block_body: str) -> str:
    wrapped = f"{begin}\n{block_body.rstrip()}\n{end}\n"
    pat = re.compile(re.escape(begin) + r".*?" + re.escape(end) + r"\r?\n?", re.S)
    if pat.search(existing):
        return pat.sub(wrapped, existing, count=1)
    sep = "\n" if existing and not existing.endswith("\n") else ""
    gap = "\n" if existing.strip() else ""
    return f"{existing}{sep}{gap}{wrapped}"


def _remove_marked_block(existing: str, begin: str, end: str) -> tuple[str, bool]:
    pat = re.compile(r"\r?\n?" + re.escape(begin) + r".*?" + re.escape(end) + r"\r?\n?", re.S)
    if not pat.search(existing):
        return existing, False
    cleaned = pat.sub("\n", existing).strip()
    return (cleaned + "\n" if cleaned else ""), True


def _build_dev_root_beacon(anchor: str, proxy: str, openai_base: str, compute_url: str) -> str:
    return f"""## CHIMERA-TP Unified Infrastructure Substrate (Host-Wide Auto-Compliance)

This workstation/server runs **CHIMERA-TP (`v18.1`)**, a Zero-Weight (`< 80 MB`) unified infrastructure brain bridging `win-desktop`, `svhome`, and **Autonomous Elastic Google Colab Pro/Ultra GPU**.

**Mandatory rules for every project and AI Coding Agent inside this workspace:**
1. **Discover First (Zero Reinvention):** Check `GET {anchor}/.well-known/chimera.json` or call MCP tool `chimera_capabilities` before adding standalone Redis, Qdrant, custom retry/proxy layers, or manual Colab notebooks.
2. **1 Unified Compute & Embeddings Endpoint (Zero-Lock-In Standard):**
   - Point any OpenAI-compatible SDK (`openai`, `langchain`, `httpx`, Node/Go/Rust) to `OPENAI_BASE_URL={openai_base}` (`CHIMERA_OPENAI_BASE`):
     - `POST /embeddings` automatically routes light loads to local AVX2 (`< 2 ms`, `$0`) and heavy batches (`>= 16` or `prefer_cuda`) to **Autonomous Elastic Colab Pro GPU** (`0%` Windows GPU load, warm-pool reuse, automatic idle stop back to `0 CU`).
     - `POST /chat/completions` & `/models` transparently relay through local LLM gateway (`tquota`) when active.
   - Or invoke unified compute directly via `POST {compute_url}` / Python `chimera_tp.platform.client.connect(app=...).compute(...)` / MCP tool `chimera_compute`.
3. **Egress Membrane & Zero-Leak DLP (Auto-Injected):** Outbound HTTP/HTTPS automatically uses `HTTP_PROXY={proxy}` (Singleflight dedup, TTL/ETag cache, `429` auto-rescue, `< 50 us` secret-leak DLP `403` guard).
4. **Cross-Host State & Safety:** Use `/v1/pulse` (Pub/Sub + KV), `/v1/search` (BM25 + AVX2 VSA), `/v1/jobs` (crash-resumable steps), `/v1/vault-sql` (SQLite replica), and `chimera-tp ghost` (CoW dry-run bubble).
"""


def _install_dev_root_beacons(
    dev_roots: list[str],
    anchor: str,
    proxy: str,
    openai_base: str,
    compute_url: str,
) -> list[str]:
    written: list[str] = []
    body = _build_dev_root_beacon(anchor, proxy, openai_base, compute_url)
    for root in dev_roots:
        p = Path(root)
        if not p.is_dir():
            continue
        agents_md = p / "AGENTS.md"
        prev = agents_md.read_text(encoding="utf-8", errors="ignore") if agents_md.is_file() else ""
        updated = _upsert_marked_block(prev, _AGENTS_BEGIN, _AGENTS_END, body)
        if _atomic_write_text(agents_md, updated):
            written.append(str(agents_md))
    return written


def _remove_dev_root_beacons(dev_roots: list[str]) -> list[str]:
    cleaned_paths: list[str] = []
    for root in dev_roots:
        agents_md = Path(root) / "AGENTS.md"
        if not agents_md.is_file():
            continue
        prev = agents_md.read_text(encoding="utf-8", errors="ignore")
        new_txt, changed = _remove_marked_block(prev, _AGENTS_BEGIN, _AGENTS_END)
        if changed:
            if new_txt.strip():
                _atomic_write_text(agents_md, new_txt)
            else:
                agents_md.unlink(missing_ok=True)
            cleaned_paths.append(str(agents_md))
    return cleaned_paths


def _configure_user_env_windows(
    shared_dir: Path,
    env_vars: dict[str, str],
    remove: bool = False,
) -> dict[str, Any]:
    import ctypes
    import winreg

    changed: list[str] = []
    shared_s = str(shared_dir)
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_READ | winreg.KEY_WRITE) as key:
        try:
            cur_pp, reg_type = winreg.QueryValueEx(key, "PYTHONPATH")
        except FileNotFoundError:
            cur_pp, reg_type = "", winreg.REG_EXPAND_SZ

        parts = [x for x in str(cur_pp).split(";") if x.strip()]
        norm_shared = os.path.normcase(os.path.abspath(shared_s))
        filtered = [x for x in parts if os.path.normcase(os.path.abspath(x)) != norm_shared]

        if remove:
            if len(filtered) != len(parts):
                if filtered:
                    winreg.SetValueEx(key, "PYTHONPATH", 0, reg_type, ";".join(filtered))
                else:
                    try:
                        winreg.DeleteValue(key, "PYTHONPATH")
                    except FileNotFoundError:
                        pass
                changed.append("PYTHONPATH")
            for k in env_vars:
                try:
                    winreg.DeleteValue(key, k)
                    changed.append(k)
                except FileNotFoundError:
                    pass
        else:
            new_parts = filtered + [shared_s]
            new_pp = ";".join(new_parts)
            if new_pp != str(cur_pp):
                winreg.SetValueEx(key, "PYTHONPATH", 0, winreg.REG_EXPAND_SZ, new_pp)
                changed.append("PYTHONPATH")
            for k, v in env_vars.items():
                try:
                    old_v, _ = winreg.QueryValueEx(key, k)
                except FileNotFoundError:
                    old_v = None
                if old_v != v:
                    winreg.SetValueEx(key, k, 0, winreg.REG_SZ, v)
                    changed.append(k)

    # Notify Windows Explorer & new shells immediately (non-blocking 1s timeout)
    try:
        ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x001A, 0, "Environment", 0x0002, 1000, None)
    except Exception:
        pass
    return {"ok": True, "os": "windows_hkcu", "changed": changed}


def _configure_user_env_posix(
    home: Path,
    shared_dir: Path,
    env_vars: dict[str, str],
    remove: bool = False,
) -> dict[str, Any]:
    changed: list[str] = []
    envd_file = home / ".config" / "environment.d" / "90-chimera-unify.conf"
    if remove:
        if envd_file.exists():
            envd_file.unlink()
            changed.append(str(envd_file))
        for rc in (home / ".bashrc", home / ".profile"):
            if rc.is_file():
                prev = rc.read_text(encoding="utf-8", errors="ignore")
                new_t, mod = _remove_marked_block(prev, _SHELL_BEGIN, _SHELL_END)
                if mod:
                    _atomic_write_text(rc, new_t)
                    changed.append(str(rc))
        return {"ok": True, "os": "posix", "changed": changed}

    envd_lines = [
        "# Auto-generated by CHIMERA-UNIFY (host-wide .venv & runtime auto-attach)",
        f"PYTHONPATH={shared_dir}:${{PYTHONPATH}}",
    ] + [f"{k}={v}" for k, v in env_vars.items()]
    if _atomic_write_text(envd_file, "\n".join(envd_lines) + "\n"):
        changed.append(str(envd_file))

    shell_lines = [
        f'case ":${{PYTHONPATH:-}}:" in *":{shared_dir}:"*) ;; *) export PYTHONPATH="{shared_dir}${{PYTHONPATH:+:$PYTHONPATH}}" ;; esac',
    ] + [f'export {k}="{v}"' for k, v in env_vars.items()]
    shell_block = "\n".join(shell_lines)
    for rc in (home / ".bashrc", home / ".profile"):
        if rc.is_file() or rc.name == ".bashrc":
            prev = rc.read_text(encoding="utf-8", errors="ignore") if rc.is_file() else ""
            updated = _upsert_marked_block(prev, _SHELL_BEGIN, _SHELL_END, shell_block)
            if _atomic_write_text(rc, updated):
                changed.append(str(rc))
    return {"ok": True, "os": "posix", "changed": changed}


def _register_mcp_configs(home: Path, python_exe: str, remove: bool = False) -> list[dict[str, Any]]:
    """Register/remove `chimera` stdio MCP server cleanly in existing AI agent config files."""
    results: list[dict[str, Any]] = []
    json_targets = [
        ("claude_code", home / ".claude.json", False),
        ("cursor", home / ".cursor" / "mcp.json", False),
        ("antigravity", home / ".gemini" / "antigravity" / "mcp_config.json", (home / ".gemini").is_dir()),
    ]
    mcp_entry = {"command": python_exe, "args": ["-m", "chimera_tp", "mcp"]}

    for name, path, create_if_parent_exists in json_targets:
        if not path.is_file() and (remove or not create_if_parent_exists):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
            if not isinstance(data, dict):
                continue
            servers = data.get("mcpServers")
            if not isinstance(servers, dict):
                servers = {}
                data["mcpServers"] = servers
            if remove:
                if "chimera" in servers:
                    servers.pop("chimera", None)
                    _atomic_write_text(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
                    results.append({"agent": name, "path": str(path), "action": "removed"})
            else:
                if servers.get("chimera") != mcp_entry:
                    servers["chimera"] = mcp_entry
                    _atomic_write_text(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
                    results.append({"agent": name, "path": str(path), "action": "registered"})
                else:
                    results.append({"agent": name, "path": str(path), "action": "already_registered"})
        except Exception as exc:
            results.append({"agent": name, "path": str(path), "action": "error", "error": str(exc)})

    codex_toml = home / ".codex" / "config.toml"
    if codex_toml.is_file():
        try:
            prev = codex_toml.read_text(encoding="utf-8", errors="ignore")
            if remove:
                new_t, mod = _remove_marked_block(prev, _TOML_BEGIN, _TOML_END)
                if mod:
                    _atomic_write_text(codex_toml, new_t)
                    results.append({"agent": "codex", "path": str(codex_toml), "action": "removed"})
            else:
                py_toml = python_exe.replace("\\", "\\\\")
                block = (
                    "[mcp_servers.chimera]\n"
                    f'command = "{py_toml}"\n'
                    'args = ["-m", "chimera_tp", "mcp"]'
                )
                updated = _upsert_marked_block(prev, _TOML_BEGIN, _TOML_END, block)
                _atomic_write_text(codex_toml, updated)
                results.append({"agent": "codex", "path": str(codex_toml), "action": "registered"})
        except Exception as exc:
            results.append({"agent": "codex", "path": str(codex_toml), "action": "error", "error": str(exc)})

    return results


def unify_install(
    *,
    dev_roots: list[str] | None = None,
    anchor_url: str | None = None,
    proxy_url: str | None = None,
    install_env: bool = True,
    install_mcp: bool = True,
    install_beacons: bool = True,
    home_dir: Path | None = None,
    site_target_dir: Path | None = None,
    python_exe: str | None = None,
) -> dict[str, Any]:
    """Install all 3 unification layers so legacy apps, .venv projects, and AI agents comply automatically."""
    home = Path(home_dir) if home_dir else Path.home()
    chimera_dir = home / ".chimera"
    chimera_dir.mkdir(parents=True, exist_ok=True)
    shared = (chimera_dir / "autoload") if home_dir else shared_autoload_dir()
    shared.mkdir(parents=True, exist_ok=True)

    rt = discover_runtime_file() or {}
    anchor = str(anchor_url or rt.get("anchor_url") or "http://127.0.0.1:9780").rstrip("/")
    proxy = str(proxy_url or rt.get("egress_proxy_url") or "http://127.0.0.1:9781").rstrip("/")
    openai_base = f"{anchor}/v1/openai/v1"
    compute_url = f"{anchor}/v1/vgpu/compute"
    py_exe = python_exe or sys.executable

    roots = [str(Path(r).resolve()) for r in dev_roots] if dev_roots is not None else _default_dev_roots(home)

    # 1. Refresh Python .pth + universal sitecustomize.py + Node preload hook
    al_res = install_autoload(
        target_dir=site_target_dir,
        shared_dir_override=shared if home_dir else None,
    )

    # 2. Persist ~/.chimera/unify.json (read by sitecustomize.py & chimera_node_hook.cjs in <0.2ms!)
    unify_cfg = {
        "schema": "chimera.unify.v1",
        "installed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "anchor_url": anchor,
        "egress_proxy_url": proxy,
        "openai_base_url": openai_base,
        "compute_url": compute_url,
        "dev_roots": roots,
        "autoload_dir": str(shared),
        "python_exe": py_exe,
    }
    unify_path = chimera_dir / "unify.json"
    _atomic_write_text(unify_path, json.dumps(unify_cfg, indent=2, ensure_ascii=False))

    # 3. User-level OS environment variables (enables every .venv on Windows & Linux automatically!)
    env_vars = {
        "CHIMERA_URL": anchor,
        "CHIMERA_EGRESS_PROXY": proxy,
        "CHIMERA_OPENAI_BASE": openai_base,
        "CHIMERA_COMPUTE_URL": compute_url,
    }
    env_res: dict[str, Any] = {"skipped": True}
    if install_env:
        if os.name == "nt" and home_dir is None:
            env_res = _configure_user_env_windows(shared, env_vars, remove=False)
        else:
            env_res = _configure_user_env_posix(home, shared, env_vars, remove=False)

    # 4. Workspace-root AGENTS.md discovery beacons
    beacons = _install_dev_root_beacons(roots, anchor, proxy, openai_base, compute_url) if install_beacons else []

    # 5. Global AI Coding Agent MCP registration
    mcp_res = _register_mcp_configs(home, py_exe, remove=False) if install_mcp else []

    return {
        "ok": True,
        "unify_config": str(unify_path),
        "dev_roots": roots,
        "endpoints": {
            "anchor_url": anchor,
            "egress_proxy_url": proxy,
            "openai_base_url": openai_base,
            "compute_url": compute_url,
        },
        "autoload": al_res,
        "user_env": env_res,
        "dev_root_beacons": beacons,
        "mcp_registrations": mcp_res,
    }


def unify_uninstall(
    *,
    home_dir: Path | None = None,
    install_env: bool = True,
    install_mcp: bool = True,
    install_beacons: bool = True,
) -> dict[str, Any]:
    home = Path(home_dir) if home_dir else Path.home()
    chimera_dir = home / ".chimera"
    unify_path = chimera_dir / "unify.json"
    shared = (chimera_dir / "autoload") if home_dir else shared_autoload_dir()
    roots: list[str] = []
    if unify_path.is_file():
        try:
            roots = list(json.loads(unify_path.read_text(encoding="utf-8")).get("dev_roots") or [])
        except Exception:
            pass
    env_vars = {
        "CHIMERA_URL": "",
        "CHIMERA_EGRESS_PROXY": "",
        "CHIMERA_OPENAI_BASE": "",
        "CHIMERA_COMPUTE_URL": "",
    }
    env_res: dict[str, Any] = {"skipped": True}
    if install_env:
        if os.name == "nt" and home_dir is None:
            env_res = _configure_user_env_windows(shared, env_vars, remove=True)
        else:
            env_res = _configure_user_env_posix(home, shared, env_vars, remove=True)
    beacons = _remove_dev_root_beacons(roots) if install_beacons else []
    mcp_res = _register_mcp_configs(home, sys.executable, remove=True) if install_mcp else []
    if unify_path.is_file():
        unify_path.unlink(missing_ok=True)
    return {
        "ok": True,
        "removed_beacons": beacons,
        "user_env": env_res,
        "mcp_registrations": mcp_res,
    }


def unify_status(*, home_dir: Path | None = None) -> dict[str, Any]:
    home = Path(home_dir) if home_dir else Path.home()
    chimera_dir = home / ".chimera"
    unify_path = chimera_dir / "unify.json"
    cfg: dict[str, Any] = {}
    if unify_path.is_file():
        try:
            cfg = json.loads(unify_path.read_text(encoding="utf-8"))
        except Exception:
            cfg = {}
    roots = list(cfg.get("dev_roots") or [])
    beacons_present = [str(Path(r) / "AGENTS.md") for r in roots if (Path(r) / "AGENTS.md").is_file()]

    env_active = False
    shared_s = str(cfg.get("autoload_dir") or (chimera_dir / "autoload"))
    if os.name == "nt" and home_dir is None:
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_READ) as key:
                pp, _ = winreg.QueryValueEx(key, "PYTHONPATH")
                env_active = os.path.normcase(shared_s) in os.path.normcase(str(pp))
        except Exception:
            env_active = False
    else:
        envd = home / ".config" / "environment.d" / "90-chimera-unify.conf"
        env_active = envd.is_file()

    mcp_active: list[str] = []
    for name, p in (
        ("claude_code", home / ".claude.json"),
        ("cursor", home / ".cursor" / "mcp.json"),
        ("antigravity", home / ".gemini" / "antigravity" / "mcp_config.json"),
    ):
        if p.is_file():
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(d.get("mcpServers"), dict) and "chimera" in d["mcpServers"]:
                    mcp_active.append(name)
            except Exception:
                pass
    codex_p = home / ".codex" / "config.toml"
    if codex_p.is_file() and "[mcp_servers.chimera]" in codex_p.read_text(encoding="utf-8", errors="ignore"):
        mcp_active.append("codex")

    al = autoload_status() if home_dir is None else {"installed": (chimera_dir / "autoload" / "sitecustomize.py").is_file()}
    return {
        "ok": True,
        "unified": bool(cfg) and bool(al.get("installed")) and env_active,
        "config_path": str(unify_path),
        "dev_roots": roots,
        "dev_root_beacons_present": beacons_present,
        "user_env_pythonpath_active": env_active,
        "autoload_installed": bool(al.get("installed")),
        "mcp_registered_agents": mcp_active,
        "endpoints": {
            "anchor_url": cfg.get("anchor_url", "http://127.0.0.1:9780"),
            "egress_proxy_url": cfg.get("egress_proxy_url", "http://127.0.0.1:9781"),
            "openai_base_url": cfg.get("openai_base_url", "http://127.0.0.1:9780/v1/openai/v1"),
            "compute_url": cfg.get("compute_url", "http://127.0.0.1:9780/v1/vgpu/compute"),
        },
    }
