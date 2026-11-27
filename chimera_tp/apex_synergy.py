"""CHIMERA v6.0 APEX-SYNERGY: Unified Fusion Engine for Radar Bounty Crew & Tqouta Local AI Relay."""

from __future__ import annotations

import json
import os
import re
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from .holo_backup import create_holo_backup

_IGNORE_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".venv",
        "venv",
        "node_modules",
        "dist",
        "build",
        "target",
        "artifacts",
        "cache",
        "out",
        "typechain-types",
        ".next",
        ".nuxt",
        "coverage",
    }
)

_SOURCE_EXTS = frozenset(
    {
        ".py",
        ".js",
        ".mjs",
        ".cjs",
        ".ts",
        ".tsx",
        ".jsx",
        ".go",
        ".rs",
        ".java",
        ".kt",
        ".rb",
        ".php",
        ".cs",
        ".c",
        ".h",
        ".cpp",
        ".hpp",
        ".sh",
        ".sql",
        ".yaml",
        ".yml",
        ".toml",
        ".json",
        ".md",
    }
)

_STOP_WORDS = frozenset(
    {
        "the",
        "and",
        "for",
        "with",
        "that",
        "this",
        "from",
        "when",
        "where",
        "what",
        "which",
        "into",
        "using",
        "should",
        "would",
        "could",
        "there",
        "their",
        "about",
        "have",
        "been",
        "were",
        "does",
        "error",
        "issue",
        "feature",
        "fix",
        "add",
        "update",
        "check",
        "make",
        "support",
        "need",
        "want",
        "code",
        "file",
        "files",
        "line",
        "lines",
        "test",
        "tests",
    }
)

_ERR_LINE_RE = re.compile(
    r"(?:Traceback|AssertionError|FAILED|Error:|Exception:|SyntaxError|ModuleNotFoundError|"
    r"ImportError|TypeError|ValueError|429|rate[_ ]limit|Command failed|exit code [1-9])",
    re.IGNORECASE,
)

_SYMBOL_LINE_RE = re.compile(
    r"^\s*(?:async\s+def|def|class|export\s+(?:async\s+)?function|function|func|pub\s+fn|fn)\s+([A-Za-z_][A-Za-z0-9_]*)"
)


def _http_get_json(url: str, timeout_s: float = 2.5) -> dict[str, Any] | list[Any]:
    with urllib.request.urlopen(url, timeout=timeout_s) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _normalize_error_sig(line: str) -> str:
    clean = re.sub(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?Z?", "", line)
    clean = re.sub(r"0x[0-9a-fA-F]+", "0xX", clean)
    clean = re.sub(r":\d+\b", ":N", clean)
    clean = re.sub(r"\b\d{4,}\b", "N", clean)
    return " ".join(clean.strip().split())[:180]


def _extract_query_terms(issue_title: str, issue_body: str) -> list[tuple[str, float]]:
    weights: dict[str, float] = {}
    text = f"{issue_title}\n{issue_body}"
    for tick in re.findall(r"`([^`\n]{2,60})`", text):
        for sub in re.findall(r"[A-Za-z0-9_./-]{3,}", tick):
            k = sub.lower().strip("./")
            if k and k not in _STOP_WORDS:
                weights[k] = max(weights.get(k, 0.0), 3.2)
    for tok in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}|[A-Za-z0-9_-]+\.[a-z]{1,5}", text):
        k = tok.lower()
        if k in _STOP_WORDS or len(k) < 3:
            continue
        is_ident = ("_" in tok) or ("." in tok) or any(c.isupper() for c in tok[1:])
        w = 2.4 if is_ident else 1.0
        weights[k] = max(weights.get(k, 0.0), w)
    return sorted(weights.items(), key=lambda x: (-x[1], -len(x[0])))[:28]


def _parse_patch_stats(patch_text: str) -> dict[str, Any]:
    files: list[str] = []
    added = 0
    removed = 0
    for ln in patch_text.splitlines():
        if ln.startswith("+++ "):
            p = ln[4:].strip()
            if p.startswith("b/"):
                p = p[2:]
            if p and p != "/dev/null" and p not in files:
                files.append(p)
        elif ln.startswith("+") and not ln.startswith("+++"):
            added += 1
        elif ln.startswith("-") and not ln.startswith("---"):
            removed += 1
    return {
        "files_changed": len(files),
        "changed_paths": files[:12],
        "lines_added": added,
        "lines_removed": removed,
    }


def _find_repo_dir(workspace_dir: Path) -> Path:
    children = [p for p in sorted(workspace_dir.iterdir()) if p.is_dir() and not p.name.startswith(".")]
    for c in children:
        if (c / ".git").exists():
            return c
    if children:
        return max(children, key=lambda d: sum(1 for _ in d.iterdir()) if d.is_dir() else 0)
    return workspace_dir


def _atomic_write_text(path: Path, text: str) -> None:
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


class ApexSynergyEngine:
    """Bridges CHIMERA 0-token search/teleport, Tqouta relay health, and Radar bounty automation."""

    def __init__(
        self,
        ops_dir: Path,
        allowed_roots: list[Path] | None = None,
        tquota_admin_url: str = "http://127.0.0.1:12504",
        tquota_relay_url: str = "http://127.0.0.1:12500",
        radar_url: str = "http://127.0.0.1:8787",
        radar_root: str = "",
        tquota_data_dir: str = "",
    ) -> None:
        self.ops_dir = Path(ops_dir).resolve()
        roots = [Path(r).resolve() for r in (allowed_roots or [])]
        if self.ops_dir not in roots:
            roots.append(self.ops_dir)
        self.allowed_roots = roots
        self.tquota_admin_url = (tquota_admin_url or "http://127.0.0.1:12504").rstrip("/")
        self.tquota_relay_url = (tquota_relay_url or "http://127.0.0.1:12500").rstrip("/")
        self.radar_url = (radar_url or "http://127.0.0.1:8787").rstrip("/")
        self.radar_root_cfg = str(radar_root or "").strip()
        self.tquota_data_dir_cfg = str(tquota_data_dir or "").strip()

    def _assert_allowed(self, raw_path: str | Path) -> Path:
        cand = Path(raw_path).resolve()
        if any(cand == r or r in cand.parents for r in self.allowed_roots):
            return cand
        raise PermissionError(f"Path outside allowed roots: {cand}")

    def resolve_radar_root(self) -> Path | None:
        if self.radar_root_cfg:
            p = Path(self.radar_root_cfg).resolve()
            if p.is_dir():
                return p
        for r in self.allowed_roots:
            for cand in (r / "radar_dashboard", r):
                if (cand / "workspaces").is_dir() or (cand / "job_radar").is_dir():
                    return cand.resolve()
        return None

    def resolve_workspaces_root(self, workspaces_root: str = "") -> Path:
        if workspaces_root:
            ws = self._assert_allowed(workspaces_root)
            if not ws.is_dir():
                raise FileNotFoundError(f"Workspaces directory not found: {ws}")
            return ws
        rr = self.resolve_radar_root()
        if rr is None or not (rr / "workspaces").is_dir():
            raise FileNotFoundError("Radar workspaces directory not configured or found")
        return (rr / "workspaces").resolve()

    def resolve_tquota_data_dir(self) -> Path | None:
        if self.tquota_data_dir_cfg:
            p = Path(self.tquota_data_dir_cfg).resolve()
            if p.is_dir():
                return p
        for r in self.allowed_roots:
            for cand in (r / "Tqouta" / "local-relay" / "data", r / "local-relay" / "data", r):
                if (cand / "local-state.json").is_file() or (cand / "adaptive-cpt.json").is_file():
                    return cand.resolve()
        return None

    def fetch_tquota_health(self) -> dict[str, Any]:
        """Query local Tqouta admin API returning strictly redacted/aggregate counts (zero emails)."""
        t0 = time.perf_counter()
        try:
            dash = _http_get_json(f"{self.tquota_admin_url}/api/dashboard", timeout_s=2.5)
            if not isinstance(dash, dict):
                raise ValueError("Invalid /api/dashboard response")
        except Exception as exc:
            return {
                "reachable": False,
                "error": str(exc),
                "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
            }

        accounts = dash.get("accounts") or []
        by_provider: Counter[str] = Counter()
        enabled_cnt = 0
        ok_cnt = 0
        reauth_cnt = 0
        for acc in accounts:
            if not isinstance(acc, dict):
                continue
            prov = str(acc.get("provider") or "unknown")
            by_provider[prov] += 1
            if acc.get("enabled"):
                enabled_cnt += 1
            st = str(acc.get("status") or "").lower()
            if st == "ok":
                ok_cnt += 1
            elif "reauth" in st or "expired" in st or "error" in st:
                reauth_cnt += 1

        warnings = (dash.get("fleetHealth") or {}).get("warnings") or []
        unknown_pool = sum(int(w.get("count", 0)) for w in warnings if isinstance(w, dict) and "unknown" in str(w.get("code", "")))
        stats = dash.get("stats") or {}
        in_tok = int(stats.get("totalInputTokens") or 0)
        cached_tok = int(stats.get("totalCachedTokens") or 0)
        cache_hit_pct = round(100.0 * cached_tok / max(1, in_tok), 2) if in_tok > 0 else 0.0
        mem = dash.get("memory") or {}
        ttft = (((dash.get("slo") or {}).get("metrics") or {}).get("proxyTtftMs") or {}).get("p50Ms")
        dual_slo = (dash.get("dualLayerSlo") or {}).get("overallStatus", "unknown")
        sched = dash.get("accountScheduler") or {}

        return {
            "reachable": True,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
            "accounts_total": len(accounts),
            "accounts_enabled": enabled_cnt,
            "accounts_ok": ok_cnt,
            "accounts_needs_reauth": reauth_cnt,
            "unknown_pool_count": unknown_pool,
            "accounts_in_flight": int(sched.get("accountsInFlight") or 0),
            "by_provider": dict(by_provider),
            "total_requests": int(stats.get("totalRequests") or 0),
            "auto_cut_requests": int(stats.get("autoCutRequests") or 0),
            "total_input_tokens": in_tok,
            "total_cached_tokens": cached_tok,
            "cache_hit_pct": cache_hit_pct,
            "trimmed_input_chars": int(stats.get("trimmedInputChars") or 0),
            "dual_layer_slo": str(dual_slo),
            "proxy_ttft_p50_ms": float(ttft) if ttft is not None else None,
            "tquota_rss_mb": round(float(mem.get("rssBytes") or 0) / (1024.0 * 1024.0), 2),
        }

    def fetch_radar_overview(self) -> dict[str, Any]:
        t0 = time.perf_counter()
        try:
            ov = _http_get_json(f"{self.radar_url}/api/overview", timeout_s=2.5)
            if not isinstance(ov, dict):
                raise ValueError("Invalid /api/overview response")
        except Exception as exc:
            return {
                "reachable": False,
                "error": str(exc),
                "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
            }

        barbell = (ov.get("breakthrough") or {}).get("barbell") or {}
        k2 = (barbell.get("kill_switches") or {}).get("K2_burn_efficiency") or {}
        approvals = ov.get("approvals") or []
        crew_runs = ov.get("crew_runs") or []
        return {
            "reachable": True,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
            "approvals_count": len(approvals) if isinstance(approvals, list) else int(approvals or 0),
            "crew_runs_count": len(crew_runs) if isinstance(crew_runs, list) else int(crew_runs or 0),
            "clean_ships_30d": int(k2.get("clean_ships_30d") or 0),
            "api_burn_30d_usd": float(k2.get("api_burn_30d_usd") or 0.0),
            "realized_usd_30d": float(k2.get("realized_usd_30d") or 0.0),
            "barbell_alert": bool(k2.get("alert", False)),
            "barbell_weights": barbell.get("weights") or {},
        }

    def evaluate_quota_arbiter(self, apply_policy: bool = False) -> dict[str, Any]:
        """Compute Radar solver throttling regime from live Tqouta fleet health."""
        tq = self.fetch_tquota_health()
        rd = self.fetch_radar_overview()

        if not tq.get("reachable"):
            regime = "ECO_SURVIVAL"
            reason = "Tqouta admin unreachable — force low-burn survival policy."
            policy = {
                "max_parallel_solvers": 1,
                "recommended_focus": "short_bounties_48h_only",
                "brief_max_chars": 3600,
                "pause_non_makefun": True,
            }
        else:
            ok_cnt = int(tq["accounts_ok"])
            reauth = int(tq["accounts_needs_reauth"])
            unknown_pool = int(tq["unknown_pool_count"])
            slo = str(tq["dual_layer_slo"])
            if ok_cnt <= 1 or reauth > 0 or bool(rd.get("barbell_alert")):
                regime = "ECO_SURVIVAL"
                reason = f"Constrained fleet (ok={ok_cnt}, reauth={reauth}, barbell_alert={rd.get('barbell_alert')})."
                policy = {
                    "max_parallel_solvers": 1,
                    "recommended_focus": "short_bounties_48h_only",
                    "brief_max_chars": 3600,
                    "pause_non_makefun": True,
                }
            elif ok_cnt >= 4 and unknown_pool == 0 and slo != "relay_degraded":
                regime = "TURBO"
                reason = f"Healthy fleet (ok={ok_cnt}, slo={slo}, cache_hit={tq['cache_hit_pct']}%)."
                policy = {
                    "max_parallel_solvers": 3,
                    "recommended_focus": "full_bounties",
                    "brief_max_chars": 7200,
                    "pause_non_makefun": False,
                }
            else:
                regime = "BALANCED"
                reason = f"Moderate headroom (ok={ok_cnt}, unknown_pool={unknown_pool}, slo={slo})."
                policy = {
                    "max_parallel_solvers": 2,
                    "recommended_focus": "short_bounties",
                    "brief_max_chars": 5200,
                    "pause_non_makefun": False,
                }

        policy_path = ""
        if apply_policy:
            rr = self.resolve_radar_root()
            if rr is not None:
                data_dir = rr / "job_radar" / "data" if (rr / "job_radar" / "data").is_dir() else rr
                pfile = data_dir / "CHIMERA_ARBITER_POLICY.json"
                _atomic_write_text(
                    pfile,
                    json.dumps(
                        {
                            "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                            "regime": regime,
                            "reason": reason,
                            "policy": policy,
                        },
                        indent=2,
                        ensure_ascii=False,
                    ),
                )
                policy_path = str(pfile)

        return {
            "ok": True,
            "regime": regime,
            "reason": reason,
            "policy": policy,
            "policy_file": policy_path,
            "tquota": tq,
            "radar": rd,
        }

    def build_surgical_brief(
        self,
        workspace_dir: str,
        issue_title: str = "",
        issue_body: str = "",
        max_chars: int = 7200,
        inject: bool = False,
    ) -> dict[str, Any]:
        """0-token code scan generating a < 8KB surgical brief for Radar solvers."""
        t0 = time.perf_counter()
        ws = self._assert_allowed(workspace_dir)
        if not ws.is_dir():
            raise FileNotFoundError(f"Workspace directory not found: {ws}")

        brief_path = ws / "AGENT_SOLVER_BRIEF.md"
        if not issue_title and not issue_body and brief_path.is_file():
            seed_txt = brief_path.read_text(encoding="utf-8", errors="replace")[:3000]
            first_h = next((ln.lstrip("# ").strip() for ln in seed_txt.splitlines() if ln.strip()), ws.name)
            issue_title = first_h
            issue_body = seed_txt

        repo_dir = _find_repo_dir(ws)
        terms = _extract_query_terms(issue_title, issue_body)

        scanned_files = 0
        scanned_bytes = 0
        test_files: list[str] = []
        ranked: list[tuple[float, str, int, list[str], list[str]]] = []

        for dirpath, dirnames, filenames in os.walk(repo_dir):
            dirnames[:] = sorted(d for d in dirnames if d not in _IGNORE_DIRS and not d.startswith("."))
            for fn in sorted(filenames):
                if scanned_files >= 400:
                    break
                fp = Path(dirpath) / fn
                if fp.suffix.lower() not in _SOURCE_EXTS:
                    continue
                try:
                    sz = int(fp.stat().st_size)
                except OSError:
                    continue
                if sz <= 0 or sz > 128 * 1024:
                    continue
                scanned_files += 1
                scanned_bytes += sz
                rel = fp.relative_to(repo_dir).as_posix()
                low_rel = rel.lower()
                if "/tests/" in f"/{low_rel}" or "/test/" in f"/{low_rel}" or fn.startswith("test_") or ".test." in low_rel or "_test." in low_rel:
                    test_files.append(rel)

                try:
                    txt = fp.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                low_txt = txt.lower()
                score = 0.0
                for term, w in terms:
                    if term in low_rel:
                        score += w * 2.5
                    cnt = low_txt.count(term)
                    if cnt > 0:
                        score += w * min(4.0, 1.0 + 0.35 * cnt)
                if score <= 0.0:
                    continue

                lines = txt.splitlines()
                best_idx = 0
                best_line_score = -1.0
                symbols: list[str] = []
                for idx, ln in enumerate(lines[:1500]):
                    m_sym = _SYMBOL_LINE_RE.match(ln)
                    if m_sym and len(symbols) < 6:
                        symbols.append(f"L{idx+1}:{m_sym.group(1)}")
                    ll = ln.lower()
                    lscore = sum(w for t, w in terms if t in ll)
                    if lscore > best_line_score:
                        best_line_score = lscore
                        best_idx = idx
                lo = max(0, best_idx - 6)
                hi = min(len(lines), best_idx + 7)
                excerpt = [f"{j+1}: {lines[j][:160]}" for j in range(lo, hi)]
                ranked.append((score, rel, best_idx + 1, symbols, excerpt))
            if scanned_files >= 400:
                break

        ranked.sort(key=lambda x: (-x[0], x[1]))
        top_matches = ranked[:5]

        git_log_txt = ""
        if (repo_dir / ".git").exists():
            try:
                proc = subprocess.run(
                    ["git", "-C", str(repo_dir), "log", "-n", "5", "--oneline"],
                    capture_output=True,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    text=True,
                    timeout=3.0,
                )
                if proc.returncode == 0:
                    git_log_txt = proc.stdout.strip()
            except Exception:
                pass

        sections: list[str] = [
            "## CHIMERA 0-Token Surgical Map",
            f"- **Repo:** `{repo_dir.name}` | **Scanned:** `{scanned_files}` files (`{round(scanned_bytes / 1024.0, 1)} KB`, `0` AI tokens spent)",
            f"- **Detected Tests ({len(test_files)}):** " + (", ".join(f"`{t}`" for t in test_files[:6]) if test_files else "_None detected_"),
            "- **Measurement Note:** Input scan reduction reflects file bytes narrowed before Tqouta relay submission; verify actual token billing in Tqouta `/api/account-usage`.",
            "",
            "### Top Target Files & Line Excerpts",
        ]
        if not top_matches:
            sections.append("_No high-confidence keyword hits; inspect repository root directly._")
        for score, rel, line_no, syms, excerpt in top_matches:
            sym_note = f" | symbols: {', '.join(syms[:4])}" if syms else ""
            sections.append(f"#### `{rel}:{line_no}` (score=`{round(score, 2)}`{sym_note})")
            sections.append("```text\n" + "\n".join(excerpt) + "\n```")

        if git_log_txt:
            sections.extend(["", "### Recent Git Commits", f"```text\n{git_log_txt}\n```"])

        pack_md = "\n".join(sections)
        cap = max(1200, int(max_chars))
        if len(pack_md) > cap:
            pack_md = pack_md[: cap - 24] + "\n... [truncated]"

        pack_path = ws / "CHIMERA_SURGERY_PACK.md"
        _atomic_write_text(pack_path, pack_md + "\n")

        injected = False
        if inject and brief_path.is_file():
            existing = brief_path.read_text(encoding="utf-8", errors="replace")
            if "## CHIMERA 0-Token Surgical Map" not in existing:
                _atomic_write_text(brief_path, existing.rstrip() + "\n\n" + pack_md + "\n")
                injected = True

        pack_bytes = len(pack_md.encode("utf-8"))
        reduction_pct = round(100.0 * (1.0 - pack_bytes / scanned_bytes), 2) if scanned_bytes > pack_bytes > 0 else 0.0
        elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)

        return {
            "ok": True,
            "workspace": ws.name,
            "repo_dir": repo_dir.name,
            "scanned_files": scanned_files,
            "scanned_bytes": scanned_bytes,
            "pack_bytes": pack_bytes,
            "scan_reduction_pct": reduction_pct,
            "top_files": [m[1] for m in top_matches],
            "test_files": test_files[:8],
            "pack_path": str(pack_path),
            "injected_into_brief": injected,
            "elapsed_ms": elapsed_ms,
            "markdown": pack_md,
        }

    def _inspect_workspace_burn(self, ws_dir: Path, repeat_threshold: int = 3) -> dict[str, Any]:
        log_p = ws_dir / "agy_solver.log"
        patch_p = ws_dir / "solution.patch"
        log_bytes = int(log_p.stat().st_size) if log_p.is_file() else 0
        patch_bytes = int(patch_p.stat().st_size) if patch_p.is_file() else 0
        sig_counts: Counter[str] = Counter()
        if log_p.is_file() and log_bytes > 0:
            with log_p.open("rb") as f:
                if log_bytes > 131072:
                    f.seek(log_bytes - 131072)
                tail_txt = f.read(131072).decode("utf-8", errors="replace")
            for ln in tail_txt.splitlines():
                if _ERR_LINE_RE.search(ln):
                    sig = _normalize_error_sig(ln)
                    if sig:
                        sig_counts[sig] += 1

        top_sig, top_cnt = sig_counts.most_common(1)[0] if sig_counts else ("", 0)
        reason = ""
        alert = False
        if top_cnt >= max(2, int(repeat_threshold)):
            alert = True
            reason = f"BURN_LOOP_REPEATED_ERROR ({top_cnt}x)"
        elif log_bytes >= 8192 and patch_bytes == 0:
            alert = True
            reason = f"BURN_LOOP_NO_PATCH_BLOAT ({log_bytes}B log, 0B patch)"

        breaker_active = (ws_dir / "CHIMERA_CIRCUIT_BREAK.json").is_file()
        return {
            "workspace_id": ws_dir.name,
            "log_bytes": log_bytes,
            "patch_bytes": patch_bytes,
            "max_repeat_count": top_cnt,
            "top_error_sig": top_sig,
            "alert": alert,
            "reason": reason,
            "breaker_active": breaker_active,
        }

    def scan_solver_burn_loops(self, workspaces_root: str = "", repeat_threshold: int = 3) -> dict[str, Any]:
        t0 = time.perf_counter()
        ws_root = self.resolve_workspaces_root(workspaces_root)
        items: list[dict[str, Any]] = []
        alerts: list[dict[str, Any]] = []
        for d in sorted(ws_root.iterdir()):
            if not d.is_dir() or d.name.startswith("."):
                continue
            info = self._inspect_workspace_burn(d, repeat_threshold=repeat_threshold)
            items.append(info)
            if info["alert"]:
                alerts.append(info)
        alerts.sort(key=lambda x: (-x["max_repeat_count"], -x["log_bytes"]))
        return {
            "ok": True,
            "workspaces_scanned": len(items),
            "alert_count": len(alerts),
            "alerts": alerts,
            "items": items[:30],
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }

    def trip_circuit_breaker(
        self,
        workspace_id: str,
        drop_portal: Any = None,
        workspaces_root: str = "",
        repeat_threshold: int = 3,
        terminate_stuck: bool = False,
    ) -> dict[str, Any]:
        ws_root = self.resolve_workspaces_root(workspaces_root)
        clean_id = Path(str(workspace_id or "").strip()).name
        if not clean_id or clean_id in (".", "..") or clean_id != str(workspace_id or "").strip():
            raise PermissionError("Invalid workspace_id")
        ws_dir = self._assert_allowed(ws_root / clean_id)
        if not ws_dir.is_dir():
            raise FileNotFoundError(f"Workspace not found: {clean_id}")

        info = self._inspect_workspace_burn(ws_dir, repeat_threshold=repeat_threshold)
        breaker_payload = {
            "tripped_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "workspace_id": clean_id,
            "reason": info["reason"] or "MANUAL_OPERATOR_TRIP",
            "max_repeat_count": info["max_repeat_count"],
            "top_error_sig": info["top_error_sig"],
        }
        breaker_path = ws_dir / "CHIMERA_CIRCUIT_BREAK.json"
        _atomic_write_text(breaker_path, json.dumps(breaker_payload, indent=2, ensure_ascii=False))

        terminated_pids: list[int] = []
        if terminate_stuck and os.name != "nt" and Path("/proc").is_dir():
            needle = f"workspaces/{clean_id}"
            for proc_dir in Path("/proc").iterdir():
                if not proc_dir.name.isdigit():
                    continue
                pid = int(proc_dir.name)
                if pid == os.getpid():
                    continue
                try:
                    raw_cmd = (proc_dir / "cmdline").read_bytes().replace(b"\x00", b" ").decode("utf-8", errors="replace")
                    if needle in raw_cmd:
                        os.kill(pid, signal.SIGTERM)
                        terminated_pids.append(pid)
                except OSError:
                    continue

        drop_meta = None
        if drop_portal is not None:
            note = (
                f"# CHIMERA Circuit Breaker Tripped: `{clean_id}`\n"
                f"- **Reason:** {breaker_payload['reason']}\n"
                f"- **Repeated Signature ({info['max_repeat_count']}x):** `{info['top_error_sig']}`\n"
                f"- **Terminated PIDs:** `{terminated_pids}`\n"
            )
            drop_meta = drop_portal.put_item(title=f"Circuit Break: {clean_id}", data=note.encode("utf-8"))

        return {
            "ok": True,
            "workspace_id": clean_id,
            "breaker_file": str(breaker_path),
            "terminated_pids": terminated_pids,
            "drop_item": drop_meta,
            "inspection": info,
        }

    def list_ready_bounties(
        self,
        workspaces_root: str = "",
        dav_base: str = "http://127.0.0.1:9788/dav",
        limit: int = 25,
    ) -> dict[str, Any]:
        t0 = time.perf_counter()
        ws_root = self.resolve_workspaces_root(workspaces_root)
        dav = (dav_base or "http://127.0.0.1:9788/dav").rstrip("/")
        candidates: list[tuple[float, dict[str, Any]]] = []

        for d in ws_root.iterdir():
            if not d.is_dir() or d.name.startswith("."):
                continue
            patch_p = d / "solution.patch"
            if not patch_p.is_file():
                continue
            st = patch_p.stat()
            if st.st_size <= 0:
                continue
            patch_txt = patch_p.read_text(encoding="utf-8", errors="replace")
            diff_stats = _parse_patch_stats(patch_txt)

            meta: dict[str, Any] = {}
            meta_p = d / "PR_META.json"
            if meta_p.is_file():
                try:
                    loaded = json.loads(meta_p.read_text(encoding="utf-8", errors="replace"))
                    if isinstance(loaded, dict):
                        meta = loaded
                except Exception:
                    pass

            report_excerpt = ""
            rep_p = d / "CREW_REPORT.md"
            if rep_p.is_file():
                report_excerpt = "\n".join(rep_p.read_text(encoding="utf-8", errors="replace").splitlines()[:12])

            pr_body_excerpt = ""
            prb_p = d / "PR_BODY.md"
            if prb_p.is_file():
                pr_body_excerpt = "\n".join(prb_p.read_text(encoding="utf-8", errors="replace").splitlines()[:10])

            q_ws = urllib.parse.quote(d.name, safe="")
            candidates.append(
                (
                    float(st.st_mtime),
                    {
                        "workspace_id": d.name,
                        "mtime_local": datetime.fromtimestamp(st.st_mtime).astimezone().strftime("%Y-%m-%d %H:%M:%S"),
                        "patch_bytes": int(st.st_size),
                        "diff_stats": diff_stats,
                        "meta": {k: meta.get(k) for k in ("title", "url", "pr_url", "bounty_usd", "status", "repo") if k in meta},
                        "dav_patch_url": f"{dav}/radar_dashboard/workspaces/{q_ws}/solution.patch",
                        "dav_pr_body_url": f"{dav}/radar_dashboard/workspaces/{q_ws}/PR_BODY.md" if prb_p.is_file() else "",
                        "dav_report_url": f"{dav}/radar_dashboard/workspaces/{q_ws}/CREW_REPORT.md" if rep_p.is_file() else "",
                        "report_excerpt": report_excerpt[:600],
                        "pr_body_excerpt": pr_body_excerpt[:500],
                    },
                )
            )

        candidates.sort(key=lambda x: -x[0])
        bounties = [item for _, item in candidates[: max(1, int(limit))]]
        return {
            "ok": True,
            "total_ready": len(candidates),
            "bounties": bounties,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }

    def publish_bounty_to_portal(
        self,
        workspace_id: str,
        drop_portal: Any,
        workspaces_root: str = "",
        dav_base: str = "http://127.0.0.1:9788/dav",
    ) -> dict[str, Any]:
        ws_root = self.resolve_workspaces_root(workspaces_root)
        clean_id = Path(str(workspace_id or "").strip()).name
        if not clean_id or clean_id in (".", "..") or clean_id != str(workspace_id or "").strip():
            raise PermissionError("Invalid workspace_id")
        ws_dir = self._assert_allowed(ws_root / clean_id)
        patch_p = ws_dir / "solution.patch"
        if not patch_p.is_file():
            raise FileNotFoundError(f"solution.patch not found in {clean_id}")

        patch_txt = patch_p.read_text(encoding="utf-8", errors="replace")
        ds = _parse_patch_stats(patch_txt)
        q_ws = urllib.parse.quote(clean_id, safe="")
        dav = (dav_base or "http://127.0.0.1:9788/dav").rstrip("/")
        packet = (
            f"# 5-Second Bounty Review: `{clean_id}`\n"
            f"- **Diff:** `{ds['files_changed']}` files | `+{ds['lines_added']} / -{ds['lines_removed']}` lines (`{len(patch_txt.encode('utf-8'))} B`)\n"
            f"- **Patch Link:** {dav}/radar_dashboard/workspaces/{q_ws}/solution.patch\n\n"
            f"```diff\n{patch_txt[:2500]}\n```"
        )
        meta = drop_portal.put_item(title=f"PR Ready: {clean_id}", data=packet.encode("utf-8"))
        return {"ok": True, "workspace_id": clean_id, "diff_stats": ds, "drop_item": meta}

    def backup_apex_vault(
        self,
        backup_root: Path,
        peer_http_base: str = "",
        include_radar_db: bool = True,
    ) -> dict[str, Any]:
        """GF(256) (K=2, N=3) atomic snapshot of Tqouta state + Radar DB/state."""
        t0 = time.perf_counter()
        targets: list[Path] = []
        tmp_dir: Path | None = None
        skipped: list[str] = []

        try:
            tq_dir = self.resolve_tquota_data_dir()
            if tq_dir is not None:
                for fn in ("local-state.json", "adaptive-cpt.json", "agent-context-budget.json", "instructions-hoist-lock.enc"):
                    cand = tq_dir / fn
                    if cand.is_file():
                        targets.append(cand)

            rr = self.resolve_radar_root()
            if rr is not None:
                data_dir = rr / "job_radar" / "data" if (rr / "job_radar" / "data").is_dir() else rr
                for fn in ("alpha_suite_state.json", "turbo_suite_state.json"):
                    cand = data_dir / fn
                    if cand.is_file():
                        targets.append(cand)

                db_cand = data_dir / "radar.db"
                if include_radar_db and db_cand.is_file():
                    raw_sum = sum(p.stat().st_size for p in targets)
                    if raw_sum + db_cand.stat().st_size <= 28 * 1024 * 1024:
                        tmp_dir = Path(tempfile.mkdtemp(prefix="chimera_apex_vault_"))
                        snap_db = tmp_dir / "radar_db_snapshot.sqlite"
                        src_conn = sqlite3.connect(f"file:{db_cand}?mode=ro", uri=True)
                        dst_conn = sqlite3.connect(str(snap_db))
                        try:
                            src_conn.backup(dst_conn)
                        finally:
                            dst_conn.close()
                            src_conn.close()
                        targets.append(snap_db)
                    else:
                        skipped.append(f"radar.db ({db_cand.stat().st_size} B exceeds 28 MiB vault headroom)")

            if not targets:
                cfg_fallback = self.ops_dir / "config.json"
                if cfg_fallback.is_file():
                    targets.append(cfg_fallback)
                else:
                    raise FileNotFoundError("No Tqouta/Radar state targets found for Apex Vault backup")

            raw_total = sum(p.stat().st_size for p in targets)
            bid = f"apex_vault_{int(time.time())}"
            if raw_total > 2 * 1024 * 1024:
                # Isolate multi-MB GF(256) shard buffers in a short-lived worker so 24/7 daemon RSS stays < 80 MB
                worker_code = (
                    "import json, sys; from pathlib import Path; "
                    "from chimera_tp.holo_backup import create_holo_backup; "
                    "req = json.loads(sys.stdin.read()); "
                    "rep = create_holo_backup([Path(p) for p in req['paths']], backup_root=Path(req['backup_root']), "
                    "backup_id=req['backup_id'], peer_http_base=req['peer_http_base']); "
                    "print(json.dumps(rep))"
                )
                req_payload = json.dumps(
                    {
                        "paths": [str(p) for p in targets],
                        "backup_root": str(backup_root),
                        "backup_id": bid,
                        "peer_http_base": peer_http_base,
                    }
                )
                proc = subprocess.run(
                    [sys.executable, "-c", worker_code],
                    input=req_payload,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    capture_output=True,
                    text=True,
                    timeout=60,
                    check=True,
                )
                bk = json.loads(proc.stdout.strip().splitlines()[-1])
            else:
                bk = create_holo_backup(
                    paths=targets,
                    backup_root=Path(backup_root),
                    backup_id=bid,
                    peer_http_base=peer_http_base,
                )
            return {
                "ok": True,
                "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
                "included_files": [p.name for p in targets],
                "skipped": skipped,
                "backup": bk,
            }
        finally:
            if tmp_dir is not None and tmp_dir.exists():
                for p in tmp_dir.iterdir():
                    try:
                        p.unlink()
                    except OSError:
                        pass
                try:
                    tmp_dir.rmdir()
                except OSError:
                    pass
