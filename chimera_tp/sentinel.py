"""CHIMERA v4.0 Breakthrough #3: CHIMERA-SENTINEL Zero-Weight Autonomous Watchdog."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

from .active_pipe import ComputePlan, execute_operator
from .merkle_sync import DEFAULT_IGNORE_DIRS

_ERROR_KEYWORDS = ("ERROR", "CRITICAL", "FATAL", "EXCEPTION", "FAIL", "THẤT BẠI")


def _probe_http_target(url: str, timeout_s: float = 1.5) -> dict[str, Any]:
    parsed = urllib.parse.urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in ("http", "https") or host not in ("127.0.0.1", "localhost", "::1"):
        return {"up": False, "status_code": 0, "latency_ms": 0.0, "error": "non-loopback target rejected"}
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(url, timeout=timeout_s) as resp:
            return {
                "up": 200 <= int(resp.status) < 500,
                "status_code": int(resp.status),
                "latency_ms": round((time.perf_counter() - t0) * 1000.0, 2),
                "error": "",
            }
    except urllib.error.HTTPError as he:
        return {
            "up": int(he.code) < 500,
            "status_code": int(he.code),
            "latency_ms": round((time.perf_counter() - t0) * 1000.0, 2),
            "error": str(he.code),
        }
    except Exception as exc:
        return {
            "up": False,
            "status_code": 0,
            "latency_ms": round((time.perf_counter() - t0) * 1000.0, 2),
            "error": str(exc),
        }


def _diagnose_template(template: str) -> str:
    low = template.lower()
    if "couldn't find remote ref" in low or "git fetch" in low:
        return "Kiểm tra nhánh git remote (`git remote prune origin` hoặc cập nhật tên branch trong auto-pull.sh)."
    if "connection refused" in low or "timed out" in low:
        return "Dịch vụ đích không phản hồi; kiểm tra `systemctl --user status` hoặc port lắng nghe."
    if "no space left" in low or "disk" in low:
        return "Dung lượng ổ đĩa thấp; dọn cache hoặc xoay vòng file log cũ."
    return "Xem trực tiếp đoạn log lỗi mới nhất bằng Fluid Pushdown (`log_analytics` / `filter_lines`)."


def _collect_log_files(config: Any, max_files: int = 12) -> list[Path]:
    found: dict[str, tuple[float, Path]] = {}
    watched = getattr(config, "watched_query_file", "") or ""
    if watched and watched != "@synthetic":
        wp = Path(watched)
        if wp.is_file():
            try:
                found[str(wp.resolve())] = (wp.stat().st_mtime, wp.resolve())
            except OSError:
                pass

    for root_str in getattr(config, "allowed_query_roots", []) or []:
        root = Path(root_str)
        if not root.is_dir():
            continue
        root_depth = len(root.parts)
        for dirpath, dirnames, filenames in os.walk(root):
            cur_p = Path(dirpath)
            if len(cur_p.parts) - root_depth >= 3:
                dirnames[:] = []
            else:
                dirnames[:] = [d for d in dirnames if d not in DEFAULT_IGNORE_DIRS]
            for fn in filenames:
                if not fn.lower().endswith(".log"):
                    continue
                fp = cur_p / fn
                try:
                    st = fp.stat()
                    found[str(fp.resolve())] = (st.st_mtime, fp.resolve())
                except OSError:
                    continue

    ordered = sorted(found.values(), key=lambda x: -x[0])
    return [p for _, p in ordered[: max(1, int(max_files))]]


def _read_tail_bytes(path: Path, max_bytes: int) -> bytes:
    sz = int(path.stat().st_size)
    if sz <= max_bytes:
        return path.read_bytes()
    with path.open("rb") as f:
        f.seek(max(0, sz - max_bytes))
        raw = f.read(max_bytes)
    nl = raw.find(b"\n")
    return raw[nl + 1 :] if 0 <= nl < len(raw) - 1 else raw


class SentinelEngine:
    """Autonomous server-side immune monitor tracking log error spikes, services, and resources."""

    def __init__(self, ops_dir: Path) -> None:
        self.ops_dir = Path(ops_dir)
        self.ops_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.ops_dir / "sentinel.db"
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS templates_baseline (
                    file_path TEXT NOT NULL,
                    template TEXT NOT NULL,
                    last_count INTEGER NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (file_path, template)
                );
                CREATE TABLE IF NOT EXISTS alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts_local TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    category TEXT NOT NULL,
                    source TEXT NOT NULL,
                    title TEXT NOT NULL,
                    detail TEXT NOT NULL,
                    diagnosis TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS scans (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts_local TEXT NOT NULL,
                    status TEXT NOT NULL,
                    alert_count INTEGER NOT NULL,
                    summary_json TEXT NOT NULL
                );
                """
            )
            self._conn.commit()

    def scan(
        self,
        config: Any,
        max_log_files: int = 12,
        tail_bytes: int = 2 * 1024 * 1024,
        probe_timeout_s: float = 1.5,
    ) -> dict[str, Any]:
        from .autopilot import get_zero_weight_status

        t0 = time.perf_counter()
        now_local = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
        alerts: list[dict[str, str]] = []

        # 1) Service health probes (strictly loopback targets)
        services: list[dict[str, Any]] = []
        edge_targets = getattr(config, "edge_targets", {}) or {}
        for app_id, meta in edge_targets.items():
            base_url = str(meta.get("url", "")).rstrip("/")
            probe_url = f"{base_url}/api/health" if app_id == "chimera" else f"{base_url}/"
            res = _probe_http_target(probe_url, timeout_s=probe_timeout_s)
            svc_row = {
                "app_id": app_id,
                "label": str(meta.get("label", app_id)),
                "url": base_url,
                **res,
            }
            services.append(svc_row)
            if not res["up"]:
                alerts.append(
                    {
                        "severity": "CRITICAL",
                        "category": "SERVICE_DOWN",
                        "source": app_id,
                        "title": f"Dịch vụ {svc_row['label']} không phản hồi",
                        "detail": f"{probe_url} lỗi: {res['error'] or res['status_code']}",
                        "diagnosis": _diagnose_template("connection refused"),
                    }
                )

        # 2) Host RAM, disk & load telemetry
        zw = get_zero_weight_status()
        du = shutil.disk_usage(self.ops_dir)
        disk_free_gb = round(du.free / (1024.0 ** 3), 2)
        disk_total_gb = round(du.total / (1024.0 ** 3), 2)
        disk_free_pct = round(100.0 * du.free / max(1, du.total), 1)
        load_avg = (
            [round(x, 2) for x in os.getloadavg()] if hasattr(os, "getloadavg") else []
        )
        resources = {
            **zw,
            "disk_free_gb": disk_free_gb,
            "disk_total_gb": disk_total_gb,
            "disk_free_pct": disk_free_pct,
            "load_avg": load_avg,
        }
        if disk_free_pct < 10.0:
            alerts.append(
                {
                    "severity": "WARN",
                    "category": "LOW_DISK",
                    "source": str(self.ops_dir),
                    "title": f"Dung lượng ổ đĩa còn thấp ({disk_free_pct}%)",
                    "detail": f"Còn {disk_free_gb} GB / {disk_total_gb} GB",
                    "diagnosis": _diagnose_template("disk low"),
                }
            )
        if not zw["zero_weight_ok"]:
            alerts.append(
                {
                    "severity": "WARN",
                    "category": "HIGH_RAM",
                    "source": getattr(config, "node_name", "node"),
                    "title": f"RAM daemon vượt ngưỡng Zero-Weight ({zw['daemon_ram_mb']} MB)",
                    "detail": f"Ngưỡng tối đa {zw['ram_budget_mb']} MB",
                    "diagnosis": "Khởi động lại daemon để giải phóng bộ nhớ đệm.",
                }
            )

        # 3) Log template spike detection across discovered *.log files
        log_files = _collect_log_files(config, max_files=max_log_files)
        logs_scanned: list[dict[str, Any]] = []
        plan = ComputePlan(op="log_analytics")

        with self._lock:
            cur = self._conn.cursor()
            for lp in log_files:
                try:
                    raw = _read_tail_bytes(lp, tail_bytes)
                    out_b, total_lines, _ = execute_operator(raw, plan)
                    rep = json.loads(out_b.decode("utf-8"))
                except Exception:
                    continue
                sev = rep.get("severity_counts", {})
                err_total = int(sev.get("CRITICAL", 0)) + int(sev.get("ERROR", 0))
                logs_scanned.append(
                    {
                        "file": lp.name,
                        "path": str(lp),
                        "lines": int(total_lines),
                        "errors": err_total,
                        "unique_templates": int(rep.get("unique_templates", 0)),
                    }
                )
                for tmpl_obj in rep.get("top_templates", []):
                    t_text = str(tmpl_obj.get("template", ""))
                    t_count = int(tmpl_obj.get("count", 0))
                    upper_t = t_text.upper()
                    if not any(kw in upper_t for kw in _ERROR_KEYWORDS):
                        continue
                    prev_row = cur.execute(
                        "SELECT last_count FROM templates_baseline WHERE file_path = ? AND template = ?",
                        (str(lp), t_text),
                    ).fetchone()
                    prev_cnt = int(prev_row["last_count"]) if prev_row is not None else 0
                    if t_count >= 25 or (t_count > prev_cnt and t_count >= max(10, prev_cnt * 2)):
                        severity = "CRITICAL" if ("CRITICAL" in upper_t or t_count >= 100) else "WARN"
                        alerts.append(
                            {
                                "severity": severity,
                                "category": "LOG_SPIKE",
                                "source": lp.name,
                                "title": f"[{t_count}x] Mẫu lỗi trong {lp.name}",
                                "detail": t_text[:220],
                                "diagnosis": _diagnose_template(t_text),
                            }
                        )
                    cur.execute(
                        """
                        INSERT INTO templates_baseline (file_path, template, last_count, updated_at)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(file_path, template) DO UPDATE
                        SET last_count = excluded.last_count, updated_at = excluded.updated_at
                        """,
                        (str(lp), t_text, t_count, now_local),
                    )

            try:
                radar_u = str(getattr(config, "radar_url", "http://127.0.0.1:8787") or "").rstrip("/")
                if radar_u:
                    alerts.extend(self.scan_stalled_workers(radar_url=radar_u))
            except Exception:
                pass

            has_crit = any(a["severity"] == "CRITICAL" for a in alerts)
            status = "ALERT" if has_crit else ("WARN" if alerts else "OK")
            for a in alerts[:20]:
                cur.execute(
                    """
                    INSERT INTO alerts (ts_local, severity, category, source, title, detail, diagnosis)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        now_local,
                        a["severity"],
                        a["category"],
                        a["source"],
                        a["title"],
                        a["detail"],
                        a["diagnosis"],
                    ),
                )

            summary = {
                "ts_local": now_local,
                "status": status,
                "services": services,
                "resources": resources,
                "logs_scanned": logs_scanned,
                "alerts": alerts[:20],
                "alert_count": len(alerts),
                "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
            }
            cur.execute(
                "INSERT INTO scans (ts_local, status, alert_count, summary_json) VALUES (?, ?, ?, ?)",
                (now_local, status, len(alerts), json.dumps(summary, ensure_ascii=False)),
            )
            self._conn.commit()

        webhook = str(getattr(config, "sentinel_webhook_url", "") or "").strip()
        if webhook and alerts and webhook.startswith(("http://", "https://")):
            try:
                hook_payload = json.dumps(
                    {
                        "node": getattr(config, "node_name", "svhome"),
                        "status": summary["status"],
                        "ts_local": now_local,
                        "alerts": alerts[:5],
                    },
                    ensure_ascii=False,
                ).encode("utf-8")
                req = urllib.request.Request(
                    webhook,
                    data=hook_payload,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=3.5) as resp:
                    resp.read(256)
            except Exception:
                pass

        return summary

    def scan_stalled_workers(
        self,
        radar_url: str = "http://127.0.0.1:8787",
        max_age_s: float = 300.0,
    ) -> list[dict[str, Any]]:
        """Detect stalled Radar crew runs exceeding max_age_s on loopback Radar API."""
        base = str(radar_url or "").rstrip("/")
        parsed = urllib.parse.urlparse(base)
        host = (parsed.hostname or "").lower()
        if parsed.scheme not in ("http", "https") or host not in ("127.0.0.1", "localhost", "::1"):
            return []
        try:
            with urllib.request.urlopen(f"{base}/api/status", timeout=1.5) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="ignore"))
        except Exception:
            return []
        if not isinstance(data, dict):
            return []
        out: list[dict[str, Any]] = []
        candidates: list[dict[str, Any]] = []
        if isinstance(data.get("active_run"), dict):
            candidates.append(data["active_run"])
        for key in ("running_runs", "runs"):
            if isinstance(data.get(key), list):
                candidates.extend(r for r in data[key] if isinstance(r, dict))
        now_ts = time.time()
        for run in candidates:
            status = str(run.get("status") or "").lower()
            if status not in ("running", "in_progress", "active"):
                continue
            elapsed = float(run.get("elapsed_s") or 0.0)
            if elapsed <= 0.0 and run.get("started_at"):
                try:
                    dt = datetime.fromisoformat(str(run["started_at"]).replace("Z", "+00:00"))
                    elapsed = max(0.0, now_ts - dt.timestamp())
                except Exception:
                    elapsed = 0.0
            if elapsed > float(max_age_s):
                rid = run.get("id") or run.get("run_id") or "?"
                out.append(
                    {
                        "severity": "WARN",
                        "category": "STALLED_WORKER",
                        "source": f"radar:{rid}",
                        "title": f"Worker #{rid} chạy quá {int(elapsed)}s (> {int(max_age_s)}s)",
                        "detail": str(run.get("task_title") or run.get("repo") or "codex_exec")[:220],
                        "diagnosis": "Lazarus Stall-Reaper hoặc restart Radar Daemon sẽ thu hồi process treo.",
                    }
                )
        return out

    def latest_status(self) -> dict[str, Any]:
        with self._lock:
            row = self._conn.execute("SELECT summary_json FROM scans ORDER BY id DESC LIMIT 1").fetchone()
            alert_rows = self._conn.execute("SELECT * FROM alerts ORDER BY id DESC LIMIT 15").fetchall()
        latest = json.loads(row["summary_json"]) if row is not None else None
        recent_alerts = [
            {
                "id": int(r["id"]),
                "ts_local": str(r["ts_local"]),
                "severity": str(r["severity"]),
                "category": str(r["category"]),
                "source": str(r["source"]),
                "title": str(r["title"]),
                "detail": str(r["detail"]),
                "diagnosis": str(r["diagnosis"]),
            }
            for r in alert_rows
        ]
        if latest is None:
            return {
                "status": "PENDING",
                "ts_local": "",
                "services": [],
                "resources": {},
                "logs_scanned": [],
                "alerts": recent_alerts,
                "alert_count": len(recent_alerts),
            }
        latest["recent_alerts"] = recent_alerts
        return latest

    def close(self) -> None:
        with self._lock:
            self._conn.close()
