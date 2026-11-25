"""CHIMERA v5.0 Breakthrough #4: CHIMERA-MEDIC Safe Forensics & Playbook Self-Healer."""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from .holo_backup import create_holo_backup

PLAYBOOK_CATALOG: dict[str, dict[str, Any]] = {
    "verify_email_log_tail": {
        "title": "Phân tích lỗi log mail / sync",
        "mutating": False,
        "description": "Đọc các dòng cuối file log, gom nhóm mã lỗi và mốc thành công gần nhất.",
    },
    "probe_services": {
        "title": "Kiểm tra lại toàn bộ dịch vụ HTTP nội bộ",
        "mutating": False,
        "description": "Probe TCP/HTTP 127.0.0.1 tới chimera, radar, tqouta và đo độ trễ.",
    },
    "prune_git_remote": {
        "title": "Dọn ref nhánh remote stale (git remote prune origin)",
        "mutating": True,
        "description": "Xóa các remote-tracking ref đã bị xóa trên origin trong repo hợp lệ.",
    },
    "holo_snapshot_configs": {
        "title": "Chụp bản sao lưu Holographic GF(256) (2/3)",
        "mutating": True,
        "description": "Tạo tức thì bộ 3 mảnh mật mã hóa GF(256) cho cấu hình trọng yếu.",
    },
    "rotate_large_log": {
        "title": "Xoay vòng & sao lưu GF(256) log lớn",
        "mutating": True,
        "description": "Chụp GF(256) đuôi log trước rồi cắt chuyển phần cũ sang file .prev.log an toàn.",
    },
    "reindex_fts5": {
        "title": "Làm mới chỉ mục tìm kiếm SQLite FTS5",
        "mutating": True,
        "description": "Quét Merkle (size, mtime) cập nhật ngay chỉ mục tìm kiếm code và log.",
    },
}


class MedicEngine:
    """Forensic triage & allowlisted playbook executor with mandatory pre-heal snapshots."""

    def __init__(self, ops_dir: Path) -> None:
        self.ops_dir = Path(ops_dir)
        self.ops_dir.mkdir(parents=True, exist_ok=True)
        self.history_path = self.ops_dir / "medic_history.json"

    def _allowed_roots(self, config: Any) -> list[Path]:
        roots = [self.ops_dir.resolve()]
        for p in getattr(config, "allowed_query_roots", []) or []:
            roots.append(Path(p).resolve())
        for p in getattr(config, "search_roots", []) or []:
            roots.append(Path(p).resolve())
        watched = getattr(config, "watched_query_file", "") or ""
        if watched and watched != "@synthetic":
            roots.append(Path(watched).resolve().parent)
        return roots

    def _assert_allowed(self, raw_path: str, config: Any) -> Path:
        cand = Path(raw_path).resolve()
        roots = self._allowed_roots(config)
        if not any(cand == r or r in cand.parents for r in roots):
            raise PermissionError(f"Path outside allowed Medic roots: {cand}")
        return cand

    def _record_history(self, entry: dict[str, Any]) -> None:
        hist = self.history()
        hist.insert(0, entry)
        tmp = self.history_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(hist[:40], indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.history_path)

    def history(self) -> list[dict[str, Any]]:
        if not self.history_path.is_file():
            return []
        try:
            data = json.loads(self.history_path.read_text(encoding="utf-8"))
            return list(data) if isinstance(data, list) else []
        except Exception:
            return []

    def status(self) -> dict[str, Any]:
        return {
            "playbooks": PLAYBOOK_CATALOG,
            "recent_actions": self.history()[:15],
        }

    def investigate(self, config: Any, file_path: str = "", pattern: str = "ERROR") -> dict[str, Any]:
        t0 = time.perf_counter()
        target_str = file_path or getattr(config, "watched_query_file", "") or ""
        if not target_str or target_str == "@synthetic":
            return {
                "ok": True,
                "target": "@synthetic",
                "matched_count": 0,
                "context_samples": [],
                "recommended_playbooks": ["probe_services", "holo_snapshot_configs"],
                "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
            }

        target = self._assert_allowed(target_str, config)
        if not target.is_file():
            raise FileNotFoundError(f"Target file not found: {target}")

        raw_sz = int(target.stat().st_size)
        read_cap = min(raw_sz, 2 * 1024 * 1024)
        with target.open("rb") as f:
            if raw_sz > read_cap:
                f.seek(raw_sz - read_cap)
            text = f.read(read_cap).decode("utf-8", errors="replace")
        lines = text.splitlines()
        pat_low = (pattern or "ERROR").lower()
        matches_idx = [i for i, ln in enumerate(lines) if pat_low in ln.lower()]

        samples: list[str] = []
        for idx in matches_idx[-3:]:
            lo = max(0, idx - 1)
            hi = min(len(lines), idx + 2)
            samples.append("\n".join(f"{j+1}: {lines[j][:200]}" for j in range(lo, hi)))

        recs = ["verify_email_log_tail", "probe_services"]
        if any("git" in s.lower() for s in samples) or "git" in pat_low:
            recs.insert(0, "prune_git_remote")
        if raw_sz >= 512 * 1024:
            recs.append("rotate_large_log")

        return {
            "ok": True,
            "target": str(target),
            "size_bytes": raw_sz,
            "pattern": pattern,
            "matched_count": len(matches_idx),
            "context_samples": samples,
            "recommended_playbooks": recs,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }

    def run_playbook(
        self,
        playbook_id: str,
        config: Any,
        params: dict[str, Any] | None = None,
        backup_root: Path | None = None,
        code_search: Any = None,
    ) -> dict[str, Any]:
        t0 = time.perf_counter()
        if playbook_id not in PLAYBOOK_CATALOG:
            raise ValueError(f"Unknown or unapproved playbook: {playbook_id}")
        opts = dict(params or {})
        broot = Path(backup_root) if backup_root else (self.ops_dir / "holo_backups")
        dry_run = bool(opts.get("dry_run", False))
        ts_local = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
        pre_snapshot_id = ""
        result: dict[str, Any] = {}

        if playbook_id == "verify_email_log_tail":
            fpath = str(opts.get("file_path") or getattr(config, "watched_query_file", "") or "")
            target = self._assert_allowed(fpath, config)
            raw = target.read_bytes()[-524288:]
            lines = raw.decode("utf-8", errors="replace").splitlines()
            code_counts: Counter[str] = Counter()
            last_ok = ""
            for ln in lines:
                for tok in re.findall(r"\b(?:[A-Z][A-Z0-9_]{3,}|ERROR|CRITICAL|FAIL)\b", ln):
                    code_counts[tok] += 1
                if "IMPORTED" in ln or "Status=OK" in ln or "OK" in ln.split():
                    last_ok = ln[:160]
            result = {
                "file": str(target),
                "lines_inspected": len(lines),
                "tail_lines": lines[-10:],
                "top_tokens": code_counts.most_common(10),
                "last_ok_line": last_ok,
            }

        elif playbook_id == "probe_services":
            probes = []
            for app_id, meta in (getattr(config, "edge_targets", {}) or {}).items():
                url = str(meta.get("url", "")).rstrip("/")
                parsed = urllib.parse.urlparse(url)
                if (parsed.hostname or "").lower() not in ("127.0.0.1", "localhost", "::1"):
                    continue
                p_url = f"{url}/api/health" if app_id == "chimera" else f"{url}/"
                t_s = time.perf_counter()
                try:
                    with urllib.request.urlopen(p_url, timeout=1.5) as resp:
                        probes.append({"app_id": app_id, "up": True, "status": int(resp.status), "ms": round((time.perf_counter() - t_s) * 1000.0, 2)})
                except urllib.error.HTTPError as he:
                    probes.append({"app_id": app_id, "up": int(he.code) < 500, "status": int(he.code), "ms": round((time.perf_counter() - t_s) * 1000.0, 2)})
                except Exception as exc:
                    probes.append({"app_id": app_id, "up": False, "error": str(exc), "ms": round((time.perf_counter() - t_s) * 1000.0, 2)})
            result = {"services": probes}

        elif playbook_id == "prune_git_remote":
            repo_raw = str(opts.get("repo_path") or "")
            if not repo_raw:
                raise ValueError("repo_path is required for prune_git_remote")
            repo = self._assert_allowed(repo_raw, config)
            if not (repo / ".git").exists():
                raise FileNotFoundError(f"Not a git repository: {repo}")
            cmd = ["git", "-C", str(repo), "remote", "prune", "origin"]
            if dry_run:
                cmd.append("--dry-run")
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=12.0)
            result = {
                "repo": str(repo),
                "dry_run": dry_run,
                "returncode": proc.returncode,
                "stdout": proc.stdout.strip(),
                "stderr": proc.stderr.strip(),
            }

        elif playbook_id == "holo_snapshot_configs":
            targets = [Path(p) for p in (getattr(config, "backup_targets", []) or []) if Path(p).exists()]
            if not targets:
                cfg_f = self.ops_dir / "config.json"
                if cfg_f.exists():
                    targets = [cfg_f]
            bk = create_holo_backup(targets, backup_root=broot, backup_id=f"medic_{int(time.time())}")
            pre_snapshot_id = bk["backup_id"]
            result = {"backup": bk}

        elif playbook_id == "rotate_large_log":
            fpath = str(opts.get("file_path") or "")
            if not fpath:
                raise ValueError("file_path is required for rotate_large_log")
            target = self._assert_allowed(fpath, config)
            if not target.is_file() or target.suffix.lower() != ".log":
                raise ValueError("Target must be an existing .log file")
            bk = create_holo_backup([target], backup_root=broot, backup_id=f"pre_rot_{int(time.time())}")
            pre_snapshot_id = bk["backup_id"]
            orig_sz = int(target.stat().st_size)
            if dry_run:
                result = {"dry_run": True, "file": str(target), "orig_bytes": orig_sz, "snapshot_id": pre_snapshot_id}
            else:
                prev_path = target.with_suffix(".prev.log")
                if prev_path.exists():
                    prev_path.unlink()
                os.replace(target, prev_path)
                target.write_text("", encoding="utf-8")
                result = {"dry_run": False, "file": str(target), "rotated_to": str(prev_path), "orig_bytes": orig_sz, "snapshot_id": pre_snapshot_id}

        elif playbook_id == "reindex_fts5":
            if code_search is None:
                raise RuntimeError("CodeSearchIndex not attached")
            roots = [Path(p) for p in (getattr(config, "search_roots", []) or getattr(config, "allowed_query_roots", []) or [self.ops_dir])]
            result = code_search.incremental_index(roots)

        record = {
            "ts_local": ts_local,
            "playbook_id": playbook_id,
            "dry_run": dry_run,
            "pre_snapshot_id": pre_snapshot_id,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
            "result": result,
        }
        self._record_history(record)
        return {"ok": True, **record}
