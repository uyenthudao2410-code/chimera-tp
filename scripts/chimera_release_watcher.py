#!/usr/bin/env python3
"""OS-Supervisor Release Convergence Watcher for CHIMERA (Linux systemd.path & Windows).

Reads `DESIRED_RELEASE.json`, verifies the staged release tree, updates the OS
service working directory, restarts the daemon cleanly, validates `/.well-known/chimera.json`
+ `POST /mcp`, and AUTOMATICALLY rolls back to `rollback_epoch` on health failure.

Run via `systemd --user` (`chimera-release-watcher.path`) on Linux or Task Scheduler on Windows.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any


def _default_releases_root() -> Path:
    if os.name == "nt":
        local_app = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(local_app) / "chimera" / "releases"
    xdg_data = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(xdg_data) / "chimera" / "releases"


def _probe_health(anchor_url: str, expected_epoch: str, timeout_s: float = 12.0) -> tuple[bool, dict[str, Any]]:
    deadline = time.monotonic() + timeout_s
    last_info: dict[str, Any] = {}
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{anchor_url}/.well-known/chimera.json", timeout=2.5) as r:
                wk = json.loads(r.read().decode("utf-8"))
            rt_dir = str(wk.get("runtime_source_dir") or "")
            mcp_req = urllib.request.Request(
                f"{anchor_url}/mcp",
                data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(mcp_req, timeout=2.5) as mr:
                md = json.loads(mr.read().decode("utf-8"))
            tools_n = len((md.get("result") or {}).get("tools") or [])
            last_info = {"pid": wk.get("pid"), "runtime_source_dir": rt_dir, "mcp_tools": tools_n}
            if expected_epoch in rt_dir and tools_n >= 6:
                return True, last_info
        except Exception as exc:
            last_info = {"error": str(exc)}
        time.sleep(0.75)
    return False, last_info


def _apply_linux_systemd(rel_dir: Path) -> None:
    dropin_dir = Path.home() / ".config" / "systemd" / "user" / "chimera-hyper-daemon.service.d"
    dropin_dir.mkdir(parents=True, exist_ok=True)
    dropin = dropin_dir / "zz-workstation-active-release.conf"
    dropin.write_text(f"[Service]\nWorkingDirectory={rel_dir.as_posix()}\n", encoding="utf-8")
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "restart", "chimera-hyper-daemon.service"], check=True)


def _apply_windows_schtask(rel_dir: Path, task_name: str = "ChimeraHyperDashboard") -> None:
    ps = (
        f"$t = Get-ScheduledTask -TaskName '{task_name}'; "
        f"$a = $t.Actions[0]; "
        f"$na = New-ScheduledTaskAction -Execute $a.Execute -Argument $a.Arguments -WorkingDirectory '{rel_dir}'; "
        f"Set-ScheduledTask -TaskName '{task_name}' -Action $na | Out-Null; "
        "$c = Get-NetTCPConnection -LocalPort 9780 -State Listen -ErrorAction SilentlyContinue; "
        "if ($c) { Stop-Process -Id $c[0].OwningProcess -Force -ErrorAction SilentlyContinue; Start-Sleep -Milliseconds 600 }; "
        f"Start-ScheduledTask -TaskName '{task_name}'"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True)


def converge(releases_root: Path, anchor_url: str = "http://127.0.0.1:9780", dry_run: bool = False) -> dict[str, Any]:
    desired_path = releases_root / "DESIRED_RELEASE.json"
    receipt_path = releases_root / "RELEASE_RECEIPT.json"
    if not desired_path.is_file():
        return {"ok": True, "action": "noop", "reason": "no_desired_manifest"}

    desired = json.loads(desired_path.read_text(encoding="utf-8"))
    epoch = str(desired.get("epoch") or "").strip()
    rollback_epoch = str(desired.get("rollback_epoch") or "").strip()
    target_dir = releases_root / epoch
    if not epoch or not (target_dir / "chimera_tp").is_dir():
        return {"ok": False, "error": f"staged_release_missing:{epoch}"}

    # Idempotency check: if live daemon already serves this exact epoch + 6 MCP tools, skip!
    already_ok, live_info = _probe_health(anchor_url, epoch, timeout_s=1.5)
    if already_ok:
        return {"ok": True, "action": "already_converged", "epoch": epoch, "live": live_info}

    if dry_run:
        return {"ok": True, "action": "dry_run_would_converge", "epoch": epoch, "target_dir": str(target_dir)}

    apply_fn = _apply_windows_schtask if os.name == "nt" else _apply_linux_systemd
    apply_fn(target_dir)
    healthy, info = _probe_health(anchor_url, epoch, timeout_s=12.0)

    rolled_back = False
    if not healthy and rollback_epoch and rollback_epoch != epoch and (releases_root / rollback_epoch / "chimera_tp").is_dir():
        apply_fn(releases_root / rollback_epoch)
        rolled_back, info = _probe_health(anchor_url, rollback_epoch, timeout_s=10.0)

    receipt = {
        "ok": healthy,
        "epoch": epoch,
        "rollback_epoch": rollback_epoch,
        "rolled_back": rolled_back,
        "converged_at": round(time.time(), 3),
        "live": info,
    }
    tmp = receipt_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(receipt, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, receipt_path)
    return receipt


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="CHIMERA OS-Supervisor Release Convergence Watcher")
    ap.add_argument("--releases-root", default=str(_default_releases_root()))
    ap.add_argument("--anchor-url", default="http://127.0.0.1:9780")
    ap.add_argument("--converge", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    res = converge(Path(args.releases_root), anchor_url=args.anchor_url, dry_run=args.dry_run)
    print(json.dumps(res, ensure_ascii=False))
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
