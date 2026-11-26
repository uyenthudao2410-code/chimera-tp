"""Zero-code Python Auto-Attach hook (<0.3 ms overhead when unlinked/stopped)."""

from __future__ import annotations

import json
import os
import site
import sys
import threading
import urllib.request
from pathlib import Path
from typing import Any


_HOOK_MODULE_NAME = "_chimera_autoload_hook"
_PTH_FILENAME = "chimera_autoload.pth"

_HOOK_SOURCE = r'''"""Auto-generated CHIMERA-CONNECT site hook. Safe no-op (<0.3ms) unless project is linked."""
import json
import os
import sys
import threading
import urllib.request
from pathlib import Path


def _bootstrap() -> None:
    if os.environ.get("CHIMERA_DISABLE_AUTOLOAD") == "1":
        return
    # Never self-hook the chimera daemon/CLI itself
    argv0 = " ".join(sys.argv[:2]).lower()
    if "chimera_tp" in argv0 or "chimera-tp" in argv0:
        return

    home = Path.home() / ".chimera"
    rt_path = home / "runtime.json"
    if not rt_path.is_file() and os.name == "nt":
        la = os.environ.get("LOCALAPPDATA", "")
        if la:
            rt_path = Path(la) / "chimera" / "runtime.json"
    if not rt_path.is_file():
        return

    cwd = Path.cwd()
    manifest_file = cwd / "chimera.manifest.json"
    app_info = None
    if manifest_file.is_file():
        try:
            m = json.loads(manifest_file.read_text(encoding="utf-8"))
            if isinstance(m, dict) and m.get("auto_attach", True):
                app_info = m
        except Exception:
            return
    elif os.environ.get("CHIMERA_AUTO") == "1":
        app_info = {"app": os.environ.get("CHIMERA_APP") or cwd.name, "qos": "interactive"}
    else:
        apps_file = home / "apps.json"
        if not apps_file.is_file():
            return
        try:
            reg = json.loads(apps_file.read_text(encoding="utf-8"))
            cwd_norm = os.path.normcase(os.path.abspath(str(cwd)))
            for entry in reg.values():
                p = entry.get("path")
                if not p:
                    continue
                p_norm = os.path.normcase(os.path.abspath(str(p)))
                if cwd_norm == p_norm or cwd_norm.startswith(p_norm + os.sep):
                    app_info = entry
                    break
        except Exception:
            return

    if not app_info:
        return

    try:
        rt = json.loads(rt_path.read_text(encoding="utf-8"))
    except Exception:
        return

    anchor = str(rt.get("anchor_url") or "").rstrip("/")
    proxy = str(rt.get("egress_proxy_url") or "").strip()
    if not anchor:
        return

    app_name = str(app_info.get("app") or cwd.name)
    os.environ.setdefault("CHIMERA_URL", anchor)
    os.environ.setdefault("CHIMERA_APP", app_name)
    os.environ.setdefault("CHIMERA_RUNTIME", str(rt_path))
    if proxy and not os.environ.get("HTTP_PROXY"):
        os.environ["HTTP_PROXY"] = proxy
        os.environ["HTTPS_PROXY"] = proxy
        no_proxy = os.environ.get("NO_PROXY", "")
        peer_ip = str(rt.get("peer_ipv4") or "").strip()
        extras = "127.0.0.1,localhost,::1,.chimera.local" + (f",{peer_ip}" if peer_ip else "")
        os.environ["NO_PROXY"] = f"{no_proxy},{extras}" if no_proxy else extras

    def _announce() -> None:
        try:
            body = json.dumps({
                "app": app_name,
                "pid": os.getpid(),
                "cwd": str(cwd),
                "port": int(app_info.get("port") or 0),
                "qos": str(app_info.get("qos") or "interactive"),
                "needs": list(app_info.get("needs") or ["egress", "pulse"]),
                "attach_mode": "autoload_pth",
            }).encode("utf-8")
            req = urllib.request.Request(
                f"{anchor}/v1/apps/register",
                data=body,
                headers={"Content-Type": "application/json", "X-Chimera-App": app_name},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=0.6).read()
        except Exception:
            pass

    threading.Thread(target=_announce, daemon=True).start()


try:
    _bootstrap()
except Exception:
    pass
'''


def _target_site_dir(user_site: bool = True) -> Path:
    if user_site:
        p = Path(site.getusersitepackages())
        p.mkdir(parents=True, exist_ok=True)
        return p
    dirs = site.getsitepackages()
    return Path(dirs[0])


def install_autoload(target_dir: Path | None = None, user_site: bool = True) -> dict[str, Any]:
    sdir = Path(target_dir) if target_dir else _target_site_dir(user_site=user_site)
    sdir.mkdir(parents=True, exist_ok=True)
    hook_py = sdir / f"{_HOOK_MODULE_NAME}.py"
    pth_file = sdir / _PTH_FILENAME
    hook_py.write_text(_HOOK_SOURCE, encoding="utf-8")
    pth_file.write_text(f"import {_HOOK_MODULE_NAME}\n", encoding="utf-8")
    return {
        "ok": True,
        "site_dir": str(sdir),
        "hook_py": str(hook_py),
        "pth_file": str(pth_file),
    }


def uninstall_autoload(target_dir: Path | None = None, user_site: bool = True) -> dict[str, Any]:
    sdir = Path(target_dir) if target_dir else _target_site_dir(user_site=user_site)
    removed: list[str] = []
    for p in (sdir / f"{_HOOK_MODULE_NAME}.py", sdir / _PTH_FILENAME):
        if p.exists():
            p.unlink()
            removed.append(str(p))
    return {"ok": True, "removed": removed}


def autoload_status(target_dir: Path | None = None, user_site: bool = True) -> dict[str, Any]:
    sdir = Path(target_dir) if target_dir else _target_site_dir(user_site=user_site)
    pth_file = sdir / _PTH_FILENAME
    hook_py = sdir / f"{_HOOK_MODULE_NAME}.py"
    return {
        "installed": pth_file.is_file() and hook_py.is_file(),
        "site_dir": str(sdir),
        "pth_file": str(pth_file),
    }
