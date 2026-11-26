"""Zero-code Python & Node.js Auto-Attach hooks (<0.3ms overhead) + systemd drop-in installer."""

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

_HOOK_SOURCE = r'''"""Auto-generated CHIMERA-CONNECT Python hook. Safe no-op (<0.3ms) unless project is linked."""
import json
import os
import sys
import threading
import time
import urllib.request
from pathlib import Path


def _install_win_orphan_job_guard() -> None:
    """Attach current Windows process tree to a KILL_ON_JOB_CLOSE JobObject to prevent multiprocessing.spawn zombies."""
    if os.name != "nt" or os.environ.get("CHIMERA_DISABLE_JOB_GUARD") == "1":
        return
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        job = k32.CreateJobObjectW(None, None)
        if not job:
            return
        class _IO_COUNTERS(ctypes.Structure):
            _fields_ = [(n, ctypes.c_uint64) for n in ("r", "w", "o", "rt", "wt", "ot")]
        class _BASIC(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", ctypes.c_uint32),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", ctypes.c_uint32),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", ctypes.c_uint32),
                ("SchedulingClass", ctypes.c_uint32),
            ]
        class _EXT(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", _BASIC),
                ("IoInfo", _IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]
        ext = _EXT()
        ext.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        k32.SetInformationJobObject(ctypes.c_void_p(job), 9, ctypes.byref(ext), ctypes.sizeof(ext))
        k32.AssignProcessToJobObject(ctypes.c_void_p(job), k32.GetCurrentProcess())
        globals()["_CHIMERA_JOB_HANDLE"] = job
    except Exception:
        pass


def _bootstrap() -> None:
    if os.environ.get("CHIMERA_DISABLE_AUTOLOAD") == "1":
        return
    argv0 = " ".join(sys.argv[:2]).lower()
    if "chimera_tp" in argv0 or "chimera-tp" in argv0:
        return
    _install_win_orphan_job_guard()

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
    elif os.environ.get("CHIMERA_AUTO") == "1" or os.environ.get("CHIMERA_APP"):
        app_info = {
            "app": os.environ.get("CHIMERA_APP") or cwd.name,
            "port": int(os.environ.get("CHIMERA_PORT") or 0),
            "qos": os.environ.get("CHIMERA_QOS") or "interactive",
        }
    else:
        apps_file = home / "apps.json"
        if apps_file.is_file():
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
                pass
        if not app_info:
            unify_file = home / "unify.json"
            if unify_file.is_file():
                try:
                    ucfg = json.loads(unify_file.read_text(encoding="utf-8"))
                    cwd_norm = os.path.normcase(os.path.abspath(str(cwd)))
                    for droot in (ucfg.get("dev_roots") or []):
                        dr_norm = os.path.normcase(os.path.abspath(str(droot)))
                        if cwd_norm.startswith(dr_norm + os.sep):
                            rel = os.path.relpath(str(cwd), str(droot))
                            top = rel.split(os.sep)[0]
                            if top and top.lower() not in ("chimera-tp", ".", ".."):
                                app_info = {"app": top, "port": 0, "qos": "interactive", "attach_mode": "python_unify"}
                            break
                except Exception:
                    pass

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
    os.environ.setdefault("CHIMERA_OPENAI_BASE", f"{anchor}/v1/openai/v1")
    os.environ.setdefault("CHIMERA_COMPUTE_URL", f"{anchor}/v1/vgpu/compute")
    if proxy:
        os.environ.setdefault("CHIMERA_EGRESS_PROXY", proxy)
        if os.environ.get("CHIMERA_INJECT_HTTP_PROXY", "1") == "1" and not os.environ.get("HTTP_PROXY"):
            os.environ["HTTP_PROXY"] = proxy
            os.environ["HTTPS_PROXY"] = proxy
            no_proxy = os.environ.get("NO_PROXY", "")
            peer_ip = str(rt.get("peer_ipv4") or "").strip()
            extras = "127.0.0.1,localhost,::1,.chimera.local" + (f",{peer_ip}" if peer_ip else "")
            os.environ["NO_PROXY"] = f"{no_proxy},{extras}" if no_proxy else extras

    payload_bytes = json.dumps({
        "app": app_name,
        "pid": os.getpid(),
        "cwd": str(cwd),
        "port": int(app_info.get("port") or 0),
        "qos": str(app_info.get("qos") or "interactive"),
        "needs": list(app_info.get("needs") or ["egress", "pulse"]),
        "attach_mode": str(app_info.get("attach_mode") or "python_autoload"),
    }).encode("utf-8")

    def _heartbeat_loop() -> None:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        while True:
            try:
                req = urllib.request.Request(
                    f"{anchor}/v1/apps/register",
                    data=payload_bytes,
                    headers={"Content-Type": "application/json", "X-Chimera-App": app_name},
                    method="POST",
                )
                opener.open(req, timeout=0.8).read()
            except Exception:
                pass
            time.sleep(60.0)

    threading.Thread(target=_heartbeat_loop, daemon=True).start()


try:
    _bootstrap()
except Exception:
    pass
'''

_NODE_HOOK_SOURCE = r'''/* Auto-generated CHIMERA-CONNECT Node.js preload hook (NODE_OPTIONS=--require=...). Zero dependencies. */
"use strict";
const fs = require("fs");
const http = require("http");
const os = require("os");
const path = require("path");

(function chimeraBootstrap() {
  if (process.env.CHIMERA_DISABLE_AUTOLOAD === "1") return;
  try {
    const home = path.join(os.homedir(), ".chimera");
    const rtPath = process.env.CHIMERA_RUNTIME || path.join(home, "runtime.json");
    if (!fs.existsSync(rtPath)) return;
    const rt = JSON.parse(fs.readFileSync(rtPath, "utf8"));
    const anchor = String(rt.anchor_url || "").replace(/\/+$/, "");
    if (!anchor) return;

    const cwd = process.cwd();
    let appInfo = null;
    const mf = path.join(cwd, "chimera.manifest.json");
    if (fs.existsSync(mf)) {
      appInfo = JSON.parse(fs.readFileSync(mf, "utf8"));
    } else if (process.env.CHIMERA_APP) {
      appInfo = { app: process.env.CHIMERA_APP, port: Number(process.env.CHIMERA_PORT || 0), qos: process.env.CHIMERA_QOS || "realtime" };
    }
    if (!appInfo) return;

    const appName = String(appInfo.app || path.basename(cwd));
    process.env.CHIMERA_URL = process.env.CHIMERA_URL || anchor;
    process.env.CHIMERA_APP = process.env.CHIMERA_APP || appName;
    process.env.CHIMERA_OPENAI_BASE = process.env.CHIMERA_OPENAI_BASE || (anchor + "/v1/openai/v1");
    process.env.CHIMERA_COMPUTE_URL = process.env.CHIMERA_COMPUTE_URL || (anchor + "/v1/vgpu/compute");
    if (rt.egress_proxy_url) {
      process.env.CHIMERA_EGRESS_PROXY = process.env.CHIMERA_EGRESS_PROXY || rt.egress_proxy_url;
    }

    const u = new URL(anchor + "/v1/apps/register");
    const body = JSON.stringify({
      app: appName,
      pid: process.pid,
      cwd,
      port: Number(appInfo.port || 0),
      qos: String(appInfo.qos || "realtime"),
      needs: Array.isArray(appInfo.needs) ? appInfo.needs : ["egress", "pulse"],
      attach_mode: "node_preload",
    });

    const beat = () => {
      try {
        const req = http.request({
          hostname: u.hostname,
          port: u.port || 9780,
          path: u.pathname,
          method: "POST",
          timeout: 800,
          headers: { "Content-Type": "application/json", "Content-Length": Buffer.byteLength(body), "X-Chimera-App": appName },
        }, (res) => { res.resume(); });
        req.on("error", () => {});
        req.on("timeout", () => req.destroy());
        req.write(body);
        req.end();
      } catch (_) {}
    };

    beat();
    const t = setInterval(beat, 60000);
    if (typeof t.unref === "function") t.unref();
  } catch (_) {}
})();
'''


def _target_site_dir(user_site: bool = True) -> Path:
    if user_site:
        p = Path(site.getusersitepackages())
        p.mkdir(parents=True, exist_ok=True)
        return p
    dirs = site.getsitepackages()
    return Path(dirs[0])


def shared_autoload_dir() -> Path:
    d = Path.home() / ".chimera" / "autoload"
    d.mkdir(parents=True, exist_ok=True)
    return d


def install_autoload(
    target_dir: Path | None = None,
    user_site: bool = True,
    shared_dir_override: Path | None = None,
) -> dict[str, Any]:
    sdir = Path(target_dir) if target_dir else _target_site_dir(user_site=user_site)
    sdir.mkdir(parents=True, exist_ok=True)
    hook_py = sdir / f"{_HOOK_MODULE_NAME}.py"
    pth_file = sdir / _PTH_FILENAME
    hook_py.write_text(_HOOK_SOURCE, encoding="utf-8")
    pth_file.write_text(f"import {_HOOK_MODULE_NAME}\n", encoding="utf-8")

    # Also install universal PYTHONPATH sitecustomize.py + Node.js preload hook in ~/.chimera/autoload/
    if shared_dir_override is not None:
        shared = Path(shared_dir_override)
    else:
        shared = shared_autoload_dir() if target_dir is None else (sdir / "chimera_shared")
    shared.mkdir(parents=True, exist_ok=True)
    site_cust = shared / "sitecustomize.py"
    node_hook = shared / "chimera_node_hook.cjs"
    site_cust.write_text(_HOOK_SOURCE, encoding="utf-8")
    node_hook.write_text(_NODE_HOOK_SOURCE, encoding="utf-8")

    return {
        "ok": True,
        "site_dir": str(sdir),
        "hook_py": str(hook_py),
        "pth_file": str(pth_file),
        "python_sitecustomize": str(site_cust),
        "node_preload_hook": str(node_hook),
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
    shared = shared_autoload_dir() if target_dir is None else (sdir / "chimera_shared")
    node_hook = shared / "chimera_node_hook.cjs"
    return {
        "installed": pth_file.is_file() and hook_py.is_file(),
        "node_hook_installed": node_hook.is_file(),
        "site_dir": str(sdir),
        "pth_file": str(pth_file),
        "node_preload_hook": str(node_hook),
    }


def install_systemd_dropin(
    unit_name: str,
    app_name: str,
    runtime: str = "python",
    port: int = 0,
    inject_http_proxy: bool = False,
    anchor_url: str = "http://127.0.0.1:9780",
    proxy_url: str = "http://127.0.0.1:9781",
    systemd_user_dir: Path | None = None,
) -> dict[str, Any]:
    """Generate a non-destructive systemd user drop-in so Python (.venv) or Node services auto-attach."""
    unit = unit_name if unit_name.endswith(".service") else f"{unit_name}.service"
    base_dir = Path(systemd_user_dir) if systemd_user_dir else (Path.home() / ".config" / "systemd" / "user")
    drop_dir = base_dir / f"{unit}.d"
    drop_dir.mkdir(parents=True, exist_ok=True)
    conf_path = drop_dir / "90-chimera.conf"

    shared = shared_autoload_dir()
    lines = [
        "# Auto-generated by CHIMERA-CONNECT (non-destructive drop-in)",
        "[Service]",
        f"Environment=CHIMERA_URL={anchor_url}",
        f"Environment=CHIMERA_APP={app_name}",
        f"Environment=CHIMERA_EGRESS_PROXY={proxy_url}",
    ]
    if port > 0:
        lines.append(f"Environment=CHIMERA_PORT={int(port)}")
    if runtime == "python":
        lines.append(f"Environment=PYTHONPATH={shared}")
        lines.append(f"Environment=CHIMERA_INJECT_HTTP_PROXY={'1' if inject_http_proxy else '0'}")
    elif runtime == "node":
        lines.append(f"Environment=NODE_OPTIONS=--require={shared / 'chimera_node_hook.cjs'}")
    if inject_http_proxy:
        lines.append(f"Environment=HTTP_PROXY={proxy_url}")
        lines.append(f"Environment=HTTPS_PROXY={proxy_url}")
        lines.append("Environment=NO_PROXY=127.0.0.1,localhost,::1,.chimera.local")

    conf_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"ok": True, "unit": unit, "dropin_path": str(conf_path), "runtime": runtime}
