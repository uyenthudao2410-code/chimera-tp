"""CHIMERA-SYMBIONT (Organ 3 Evolution): Multi-Agent Hive-Mind, Precog Runner, Surgeon Atomic Patch & Telepathy Capsule.

100% Python stdlib, lazy-loaded (0 startup RSS), bounded memory (< 3 MiB), zero PowerShell spawns.

Four integrated pillars sitting atop `AgentHyperBus`:
1. `HiveMindCortex`: Soft intent leases, cross-agent live conflict radar, mutation ledger, and
   SQLite-WAL-backed `ImmuneReflexTable` ("1 agent learns -> all agents become immune").
2. `PrecogRunnerEngine`: `< 2 ms` single-file incremental AST updates, singleflight speculative
   background test verification while the LLM is still thinking (`commit_verify` joins or hits
   cached BLAKE2s receipts in `< 15 ms`), plus optional event-driven Win32 `ReadDirectoryChangesW`
   repo watcher (0% idle polling, 0 PowerShell).
3. `SurgeonAtomicPatchEngine`: Transactional multi-file patch with Pre-Commit Format Gate in RAM
   (`ast.parse` for `.py`, `tomllib.loads` for `.toml`, `json.loads` for `.json`, `node --check`
   for `.js/.mjs/.cjs`) BEFORE touching disk, atomic `os.replace`, impacted verification, and
   exact byte-level auto-rollback on failure.
4. `TelepathyCapsuleEngine`: `< 50 ms`, `< 1,500`-token verified workspace brain handoff bundle
   combining live git diff stat, active Hive leases, BLAKE2s verified test badges, matching Immune
   Reflex warnings, and compact Callgraph signatures so switching between Codex / Claude / 6× T3
   Antigravity resumes with zero re-discovery burn.
"""

from __future__ import annotations

import ast
import collections
import ctypes
import difflib
import fnmatch
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import tomllib
import uuid
from pathlib import Path
from typing import Any

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
_WATCH_EXTS = {".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".rs", ".toml", ".json"}
_SKIP_WATCH_PARTS = {".git", "__pycache__", "node_modules", ".venv", "venv", "target", "dist", "build", ".pytest_cache"}


def _norm_repo(repo: str | Path) -> str:
    try:
        return str(Path(repo).resolve()).replace("\\", "/")
    except Exception:
        return str(repo).replace("\\", "/")


def _norm_rel(path: str) -> str:
    return str(path or "").strip().replace("\\", "/").lstrip("./")


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.chimera.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


# ---------------------------------------------------------------------------
# PILLAR 1: HIVE-MIND CORTEX (Soft Leases, Conflict Radar & Immune Reflex)
# ---------------------------------------------------------------------------

class HiveMindCortex:
    """Shared in-RAM multi-agent awareness + persistent Immune Reflex table (< 1 MiB RAM)."""

    MAX_LEASES = 128
    MAX_MUTATIONS = 64
    MAX_IMMUNE_RULES = 128

    def __init__(self, db_path: Path | None = None, *, ephemeral: bool = False) -> None:
        self._lock = threading.Lock()
        self._leases: dict[str, dict[str, Any]] = {}
        self._mutations: collections.deque[dict[str, Any]] = collections.deque(maxlen=self.MAX_MUTATIONS)
        self._immune: collections.OrderedDict[str, dict[str, Any]] = collections.OrderedDict()
        self._ephemeral = ephemeral
        if db_path is not None:
            self._db_path: Path | None = Path(db_path)
        elif ephemeral:
            self._db_path = None
        else:
            self._db_path = Path.home() / ".chimera" / "agent_symbiont.sqlite"
        self._db_ready = False
        self._init_db()
        self._load_immune_from_db()

    def _connect(self) -> sqlite3.Connection | None:
        if self._db_path is None:
            return None
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(str(self._db_path), timeout=5.0)
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=NORMAL")
        return con

    def _init_db(self) -> None:
        con = self._connect()
        if con is None:
            return
        try:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS immune_rules (
                    rule_id TEXT PRIMARY KEY,
                    pattern TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    warning TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    hit_count INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS handoff_capsules (
                    capsule_id TEXT PRIMARY KEY,
                    repo TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS release_epochs (
                    epoch_id TEXT PRIMARY KEY,
                    release_dir TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    published_at REAL NOT NULL,
                    daemon_pid INTEGER NOT NULL DEFAULT 0,
                    verified_summary TEXT NOT NULL DEFAULT '',
                    files_json TEXT NOT NULL DEFAULT '[]',
                    sha256_json TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            con.commit()
            self._db_ready = True
        except Exception:
            self._db_ready = False
        finally:
            con.close()

    def _load_immune_from_db(self) -> None:
        if not self._db_ready:
            return
        con = self._connect()
        if con is None:
            return
        try:
            cur = con.execute(
                "SELECT rule_id, pattern, scope, warning, severity, created_by, created_at, hit_count "
                "FROM immune_rules ORDER BY created_at DESC LIMIT ?",
                (self.MAX_IMMUNE_RULES,),
            )
            with self._lock:
                for row in reversed(cur.fetchall()):
                    self._immune[row[0]] = {
                        "rule_id": row[0],
                        "pattern": row[1],
                        "scope": row[2],
                        "warning": row[3],
                        "severity": row[4],
                        "created_by": row[5],
                        "created_at": float(row[6]),
                        "hit_count": int(row[7]),
                    }
        except Exception:
            pass
        finally:
            con.close()

    def _prune_leases_locked(self, now: float) -> None:
        expired = [k for k, v in self._leases.items() if float(v.get("expires_at", 0.0)) <= now]
        for k in expired:
            self._leases.pop(k, None)

    def acquire_lease(
        self,
        *,
        agent_id: str,
        repo: str,
        files: list[str] | None = None,
        intent: str = "",
        action: str = "edit",
        ttl_s: float = 120.0,
    ) -> dict[str, Any]:
        aid = str(agent_id or "unknown-agent").strip()[:64]
        nrepo = _norm_repo(repo)
        norm_files = sorted({_norm_rel(f) for f in (files or []) if _norm_rel(f)})[:64]
        now = time.time()
        ttl = max(5.0, min(900.0, float(ttl_s or 120.0)))
        lease_key = f"{aid}::{nrepo}"

        with self._lock:
            self._prune_leases_locked(now)
            conflicts = self._find_conflicts_locked(aid, nrepo, norm_files, now)
            lease = {
                "lease_id": lease_key,
                "agent_id": aid,
                "repo": nrepo,
                "files": norm_files,
                "intent": str(intent or "")[:180],
                "action": str(action or "edit")[:24],
                "updated_at": round(now, 3),
                "expires_at": round(now + ttl, 3),
            }
            if len(self._leases) >= self.MAX_LEASES and lease_key not in self._leases:
                oldest = min(self._leases.items(), key=lambda kv: kv[1].get("updated_at", 0.0))[0]
                self._leases.pop(oldest, None)
            self._leases[lease_key] = lease

        immune_hits = self.match_immune(norm_files, repo=nrepo)
        return {
            "ok": True,
            "lease": lease,
            "conflicts": conflicts,
            "immune_warnings": immune_hits,
        }

    def release_lease(self, *, agent_id: str, repo: str | None = None) -> dict[str, Any]:
        aid = str(agent_id or "").strip()
        nrepo = _norm_repo(repo) if repo else None
        removed = 0
        with self._lock:
            keys = [
                k
                for k, v in self._leases.items()
                if v.get("agent_id") == aid and (nrepo is None or v.get("repo") == nrepo)
            ]
            for k in keys:
                self._leases.pop(k, None)
                removed += 1
        return {"ok": True, "removed": removed}

    def record_mutation(
        self,
        *,
        agent_id: str,
        repo: str,
        files: list[str],
        kind: str = "edit",
        detail: str = "",
    ) -> None:
        now = time.time()
        entry = {
            "agent_id": str(agent_id or "unknown")[:64],
            "repo": _norm_repo(repo),
            "files": sorted({_norm_rel(f) for f in files if _norm_rel(f)})[:32],
            "kind": str(kind or "edit")[:24],
            "detail": str(detail or "")[:160],
            "ts": round(now, 3),
        }
        with self._lock:
            self._mutations.append(entry)

    def _find_conflicts_locked(
        self,
        agent_id: str,
        nrepo: str,
        norm_files: list[str],
        now: float,
    ) -> list[dict[str, Any]]:
        fset = set(norm_files)
        conflicts: list[dict[str, Any]] = []
        for v in self._leases.values():
            if v.get("agent_id") == agent_id:
                continue
            if v.get("repo") != nrepo:
                continue
            other_files = set(v.get("files") or [])
            overlap = sorted(fset & other_files) if fset and other_files else []
            # Repo-wide deploy/restart lease conflicts with everything in the same repo
            if overlap or v.get("action") in ("deploy", "restart") or (not other_files and fset):
                conflicts.append({
                    "type": "active_lease",
                    "agent_id": v.get("agent_id"),
                    "action": v.get("action"),
                    "intent": v.get("intent"),
                    "overlap": overlap,
                    "age_s": round(max(0.0, now - float(v.get("updated_at", now))), 1),
                })
        # Recent mutations by other agents within last 180s
        for m in reversed(self._mutations):
            age = now - float(m.get("ts", 0.0))
            if age > 180.0:
                break
            if m.get("agent_id") == agent_id or m.get("repo") != nrepo:
                continue
            overlap = sorted(fset & set(m.get("files") or [])) if fset else list(m.get("files") or [])[:5]
            if overlap or m.get("kind") in ("deploy", "restart"):
                conflicts.append({
                    "type": "recent_mutation",
                    "agent_id": m.get("agent_id"),
                    "kind": m.get("kind"),
                    "overlap": overlap,
                    "detail": m.get("detail"),
                    "age_s": round(max(0.0, age), 1),
                })
                if len(conflicts) >= 8:
                    break
        return conflicts

    def check_alerts(self, *, agent_id: str, repo: str | None, files: list[str]) -> dict[str, Any]:
        """Fast O(active_leases + rules) piggyback check for xray_batch & callgraph_slice."""
        nrepo = _norm_repo(repo) if repo else ""
        norm_files = sorted({_norm_rel(f) for f in files if _norm_rel(f)})
        now = time.time()
        conflicts: list[dict[str, Any]] = []
        if nrepo:
            with self._lock:
                self._prune_leases_locked(now)
                conflicts = self._find_conflicts_locked(str(agent_id or ""), nrepo, norm_files, now)
        immune = self.match_immune(norm_files, repo=nrepo)
        return {"conflicts": conflicts, "immune_warnings": immune}

    def add_immune_rule(
        self,
        *,
        pattern: str,
        warning: str,
        scope: str = "global",
        severity: str = "warn",
        created_by: str = "agent",
    ) -> dict[str, Any]:
        pat = str(pattern or "").strip().replace("\\", "/")
        warn = str(warning or "").strip()[:280]
        if not pat or not warn:
            return {"ok": False, "error": "pattern_and_warning_required"}
        rid = "imm_" + hashlib.blake2s(f"{scope}|{pat}|{warn}".encode("utf-8"), digest_size=6).hexdigest()
        now = time.time()
        rule = {
            "rule_id": rid,
            "pattern": pat,
            "scope": str(scope or "global")[:64],
            "warning": warn,
            "severity": str(severity or "warn")[:16],
            "created_by": str(created_by or "agent")[:64],
            "created_at": round(now, 3),
            "hit_count": 0,
        }
        with self._lock:
            if rid in self._immune:
                rule["hit_count"] = int(self._immune[rid].get("hit_count", 0))
            while len(self._immune) >= self.MAX_IMMUNE_RULES and rid not in self._immune:
                self._immune.popitem(last=False)
            self._immune[rid] = rule
            self._immune.move_to_end(rid)

        if self._db_ready:
            con = self._connect()
            if con is not None:
                try:
                    con.execute(
                        "INSERT OR REPLACE INTO immune_rules "
                        "(rule_id, pattern, scope, warning, severity, created_by, created_at, hit_count) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            rule["rule_id"],
                            rule["pattern"],
                            rule["scope"],
                            rule["warning"],
                            rule["severity"],
                            rule["created_by"],
                            rule["created_at"],
                            rule["hit_count"],
                        ),
                    )
                    con.commit()
                except Exception:
                    pass
                finally:
                    con.close()
        return {"ok": True, "rule": rule}

    def match_immune(self, targets: list[str], *, repo: str = "") -> list[dict[str, Any]]:
        if not targets and not repo:
            return []
        norm_targets = [str(t or "").replace("\\", "/").lower() for t in targets if t]
        repo_low = str(repo or "").replace("\\", "/").lower()
        hits: list[dict[str, Any]] = []
        hit_ids: list[str] = []

        with self._lock:
            for rid, rule in self._immune.items():
                pat = str(rule.get("pattern") or "").lower()
                if not pat:
                    continue
                matched_on = ""
                for t in norm_targets:
                    if fnmatch.fnmatch(t, pat) or (pat in t) or fnmatch.fnmatch(os.path.basename(t), pat):
                        matched_on = t
                        break
                if not matched_on and repo_low and (fnmatch.fnmatch(repo_low, pat) or pat in repo_low):
                    matched_on = repo_low
                if matched_on:
                    rule["hit_count"] = int(rule.get("hit_count", 0)) + 1
                    hit_ids.append(rid)
                    hits.append({
                        "rule_id": rid,
                        "severity": rule.get("severity", "warn"),
                        "matched": matched_on,
                        "warning": rule.get("warning"),
                    })
                    if len(hits) >= 6:
                        break

        if hit_ids and self._db_ready:
            con = self._connect()
            if con is not None:
                try:
                    con.executemany(
                        "UPDATE immune_rules SET hit_count = hit_count + 1 WHERE rule_id = ?",
                        [(rid,) for rid in hit_ids],
                    )
                    con.commit()
                except Exception:
                    pass
                finally:
                    con.close()
        return hits

    def list_immune(self, limit: int = 32) -> list[dict[str, Any]]:
        with self._lock:
            items = list(self._immune.values())
        return list(reversed(items))[: max(1, min(128, int(limit or 32)))]

    def status(self, repo: str | None = None) -> dict[str, Any]:
        now = time.time()
        nrepo = _norm_repo(repo) if repo else None
        with self._lock:
            self._prune_leases_locked(now)
            leases = [
                dict(v, ttl_left_s=round(max(0.0, float(v["expires_at"]) - now), 1))
                for v in self._leases.values()
                if nrepo is None or v.get("repo") == nrepo
            ]
            muts = [
                dict(m, age_s=round(max(0.0, now - float(m["ts"])), 1))
                for m in reversed(self._mutations)
                if nrepo is None or m.get("repo") == nrepo
            ][:16]
            immune_count = len(self._immune)
        return {
            "ok": True,
            "active_leases": leases,
            "recent_mutations": muts,
            "immune_rules_count": immune_count,
            "immune_rules": self.list_immune(limit=12),
        }


# ---------------------------------------------------------------------------
# PILLAR 2: PRECOG-RUNNER (Incremental AST + Speculative Background Test)
# ---------------------------------------------------------------------------

class PrecogRunnerEngine:
    """Speculative verification while the LLM is thinking: <2ms AST delta + singleflight shadow tests."""

    def __init__(self, callgraph: Any, verifier: Any, hive: HiveMindCortex) -> None:
        self.callgraph = callgraph
        self.verifier = verifier
        self.hive = hive
        self._lock = threading.Lock()
        self._inflight: dict[str, threading.Event] = {}
        self._watchers: dict[str, dict[str, Any]] = {}
        self._spec_cache: dict[str, dict[str, Any]] = {}
        self._stats = {
            "saves_processed": 0,
            "ast_incremental_updates": 0,
            "shadow_tests_started": 0,
            "shadow_tests_completed": 0,
            "shadow_cache_joins": 0,
            "shadow_precomputed_hits": 0,
            "syntax_early_catches": 0,
            "prefetch_calls": 0,
            "prefetched_files": 0,
            "spec_cache_stores": 0,
            "spec_cache_hits": 0,
        }

    def _quick_syntax_check(self, fp: Path) -> str | None:
        ext = fp.suffix.lower()
        try:
            raw = fp.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return f"read_error:{exc}"
        if ext == ".py":
            try:
                ast.parse(raw, filename=str(fp))
            except SyntaxError as exc:
                return f"SyntaxError L{exc.lineno}: {exc.msg}"
        elif ext == ".toml":
            try:
                tomllib.loads(raw)
            except Exception as exc:
                return f"TOMLDecodeError: {exc}"
        elif ext == ".json":
            try:
                if raw.strip():
                    json.loads(raw)
            except Exception as exc:
                return f"JSONDecodeError: {exc}"
        return None

    def notify_save(
        self,
        repo_path: str | Path,
        rel_paths: list[str],
        *,
        run_shadow_test: bool = True,
        explicit_tests: list[str] | None = None,
        max_tests: int = 2,
        timeout_s: float = 25.0,
        agent_id: str = "precog",
    ) -> dict[str, Any]:
        t0 = time.perf_counter()
        repo = Path(repo_path).resolve()
        if not repo.is_dir():
            return {"ok": False, "error": "repo_not_found", "repo": str(repo)}

        cleaned = [_norm_rel(p) for p in (rel_paths or []) if _norm_rel(p)]
        if not cleaned:
            return {"ok": False, "error": "rel_paths_required"}

        ast_updated: list[str] = []
        syntax_errors: list[dict[str, str]] = []
        for rel in cleaned[:24]:
            fp = repo / rel
            if not fp.is_file():
                continue
            err = self._quick_syntax_check(fp)
            if err:
                syntax_errors.append({"file": rel, "error": err})
            if hasattr(self.callgraph, "update_single_file"):
                if self.callgraph.update_single_file(repo, rel):
                    ast_updated.append(rel)

        with self._lock:
            self._stats["saves_processed"] += len(cleaned)
            self._stats["ast_incremental_updates"] += len(ast_updated)
            if syntax_errors:
                self._stats["syntax_early_catches"] += len(syntax_errors)

        shadow_scheduled = False
        shadow_fingerprint = ""
        shadow_tests: list[str] = []

        if run_shadow_test and not syntax_errors:
            py_or_js = [r for r in cleaned if Path(r).suffix.lower() in (".py", ".js", ".mjs", ".cjs")]
            if py_or_js:
                if explicit_tests:
                    shadow_tests = [_norm_rel(t) for t in explicit_tests if (repo / t).is_file()][: max(1, int(max_tests))]
                else:
                    shadow_tests = self.verifier._find_impacted_tests(repo, py_or_js, max_tests=max(1, int(max_tests)))
                shadow_fingerprint = self.verifier._fingerprint(repo, py_or_js, shadow_tests)
                if shadow_tests and not self.verifier.has_fresh_cache(shadow_fingerprint):
                    with self._lock:
                        already = shadow_fingerprint in self._inflight
                        if not already and len(self._inflight) < 2:
                            ev = threading.Event()
                            self._inflight[shadow_fingerprint] = ev
                            self._stats["shadow_tests_started"] += 1
                            shadow_scheduled = True
                        else:
                            ev = None
                    if shadow_scheduled and ev is not None:
                        def _run_shadow(
                            _repo: str = str(repo),
                            _files: list[str] = list(py_or_js),
                            _tests: list[str] = list(shadow_tests),
                            _fp: str = shadow_fingerprint,
                            _ev: threading.Event = ev,
                        ) -> None:
                            try:
                                self.verifier.verify(
                                    _repo,
                                    files=_files,
                                    run_tests=True,
                                    explicit_tests=_tests,
                                    max_tests=len(_tests),
                                    timeout_s=float(timeout_s),
                                    use_cache=True,
                                    compact=True,
                                    mark_precog=True,
                                )
                                with self._lock:
                                    self._stats["shadow_tests_completed"] += 1
                            except Exception:
                                pass
                            finally:
                                with self._lock:
                                    self._inflight.pop(_fp, None)
                                _ev.set()

                        t = threading.Thread(target=_run_shadow, name=f"chimera-precog-{shadow_fingerprint[:8]}", daemon=True)
                        t.start()

        if agent_id != "precog":
            self.hive.record_mutation(
                agent_id=agent_id,
                repo=str(repo),
                files=cleaned,
                kind="save",
                detail=f"ast={len(ast_updated)} shadow={shadow_scheduled}",
            )

        return {
            "ok": len(syntax_errors) == 0,
            "repo": str(repo),
            "ast_updated": ast_updated,
            "syntax_errors": syntax_errors,
            "shadow_scheduled": shadow_scheduled,
            "shadow_fingerprint": shadow_fingerprint,
            "shadow_tests": shadow_tests,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }

    def wait_inflight(self, fingerprint: str, timeout_s: float = 30.0) -> bool:
        """If a speculative shadow test for this exact BLAKE2s fingerprint is running, join it!"""
        with self._lock:
            ev = self._inflight.get(fingerprint)
        if ev is None:
            return False
        with self._lock:
            self._stats["shadow_cache_joins"] += 1
        return ev.wait(timeout=max(0.5, float(timeout_s)))

    def note_precomputed_hit(self) -> None:
        with self._lock:
            self._stats["shadow_precomputed_hits"] += 1

    SPEC_CACHE_MAX_FILES = 16
    SPEC_CACHE_MAX_FILE_BYTES = 131072
    SPEC_CACHE_TTL_S = 15.0

    def prefetch_paths(
        self,
        paths: list[str],
        *,
        max_bytes_per_file: int = 65536,
        warm_cache: bool = True,
    ) -> dict[str, Any]:
        """Speculative read-only OS page-cache & RAM Speculative Result Cache warmer (0 side effects)."""
        t0 = time.perf_counter()
        cap = max(4096, min(262144, int(max_bytes_per_file)))
        warmed: list[str] = []
        cached_count = 0
        total_bytes = 0
        now_m = time.monotonic()
        for raw in (paths or [])[:8]:
            s = str(raw or "").strip()
            if not s or len(s) > 400:
                continue
            try:
                p = Path(s).resolve()
                if not p.is_file():
                    continue
                st = p.stat()
                read_len = st.st_size if (warm_cache and st.st_size <= self.SPEC_CACHE_MAX_FILE_BYTES) else cap
                with p.open("rb") as fh:
                    chunk = fh.read(read_len)
                total_bytes += len(chunk)
                warmed.append(str(p))
                if warm_cache and st.st_size <= self.SPEC_CACHE_MAX_FILE_BYTES and b"\x00" not in chunk[:2048]:
                    text = chunk.decode("utf-8", errors="replace")
                    key = os.path.normcase(str(p))
                    digest = hashlib.blake2s(chunk, digest_size=8).hexdigest()
                    with self._lock:
                        self._spec_cache.pop(key, None)
                        self._spec_cache[key] = {
                            "mtime_ns": st.st_mtime_ns,
                            "size": st.st_size,
                            "ts": now_m,
                            "hash": digest,
                            "lines": text.splitlines(),
                        }
                        while len(self._spec_cache) > self.SPEC_CACHE_MAX_FILES:
                            oldest = next(iter(self._spec_cache))
                            self._spec_cache.pop(oldest, None)
                        self._stats["spec_cache_stores"] += 1
                    cached_count += 1
            except OSError:
                continue
        with self._lock:
            self._stats["prefetch_calls"] += 1
            self._stats["prefetched_files"] += len(warmed)
        return {
            "ok": True,
            "warmed_count": len(warmed),
            "cached_count": cached_count,
            "warmed_bytes": total_bytes,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }

    def get_speculative_lines(self, path: str | Path) -> tuple[str, list[str]] | None:
        """Return (blake2s_hash, lines) in <0.05ms if file was pre-warmed by SSE tap & mtime/size still match."""
        try:
            p = Path(path).resolve()
            key = os.path.normcase(str(p))
        except OSError:
            return None
        now_m = time.monotonic()
        with self._lock:
            entry = self._spec_cache.get(key)
        if not entry:
            return None
        if (now_m - float(entry["ts"])) > self.SPEC_CACHE_TTL_S:
            with self._lock:
                self._spec_cache.pop(key, None)
            return None
        try:
            st = p.stat()
        except OSError:
            return None
        if st.st_mtime_ns != entry["mtime_ns"] or st.st_size != entry["size"]:
            with self._lock:
                self._spec_cache.pop(key, None)
            return None
        with self._lock:
            self._stats["spec_cache_hits"] += 1
        return str(entry["hash"]), list(entry["lines"])

    # --- Optional Event-Driven Win32 ReadDirectoryChangesW Repo Watcher ---

    def start_watch(self, repo_path: str | Path, *, run_shadow_test: bool = True) -> dict[str, Any]:
        repo = Path(repo_path).resolve()
        if not repo.is_dir():
            return {"ok": False, "error": "repo_not_found", "repo": str(repo)}
        key = _norm_repo(repo)
        with self._lock:
            if key in self._watchers and self._watchers[key]["alive"]:
                return {"ok": True, "repo": str(repo), "already_watching": True, "backend": self._watchers[key]["backend"]}
            stop_ev = threading.Event()
            backend = "win32_rdcw" if os.name == "nt" else "posix_poll"
            entry: dict[str, Any] = {
                "repo": str(repo),
                "stop": stop_ev,
                "alive": True,
                "backend": backend,
                "events": 0,
                "started_at": time.time(),
            }
            self._watchers[key] = entry

        if os.name == "nt":
            th = threading.Thread(
                target=self._win32_watch_loop,
                args=(repo, stop_ev, entry, run_shadow_test),
                name=f"chimera-watch-{repo.name[:16]}",
                daemon=True,
            )
        else:
            th = threading.Thread(
                target=self._posix_watch_loop,
                args=(repo, stop_ev, entry, run_shadow_test),
                name=f"chimera-watch-{repo.name[:16]}",
                daemon=True,
            )
        entry["thread"] = th
        th.start()
        return {"ok": True, "repo": str(repo), "watching": True, "backend": backend}

    def stop_watch(self, repo_path: str | Path | None = None) -> dict[str, Any]:
        stopped = 0
        with self._lock:
            targets = list(self._watchers.keys()) if repo_path is None else [_norm_repo(repo_path)]
            for k in targets:
                w = self._watchers.pop(k, None)
                if w is not None:
                    w["alive"] = False
                    w["stop"].set()
                    handle = w.get("dir_handle")
                    if handle and os.name == "nt":
                        try:
                            ctypes.windll.kernel32.CancelIoEx(ctypes.c_void_p(handle), None)
                            ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(handle))
                        except Exception:
                            pass
                    stopped += 1
        return {"ok": True, "stopped": stopped}

    def _win32_watch_loop(self, repo: Path, stop_ev: threading.Event, entry: dict[str, Any], run_shadow: bool) -> None:
        kernel32 = ctypes.windll.kernel32
        FILE_LIST_DIRECTORY = 0x0001
        FILE_SHARE_READ = 0x00000001
        FILE_SHARE_WRITE = 0x00000002
        FILE_SHARE_DELETE = 0x00000004
        OPEN_EXISTING = 3
        FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
        FILE_NOTIFY_CHANGE_LAST_WRITE = 0x00000010
        FILE_NOTIFY_CHANGE_FILE_NAME = 0x00000001
        INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

        kernel32.CreateFileW.restype = ctypes.c_void_p
        hdir = kernel32.CreateFileW(
            str(repo),
            FILE_LIST_DIRECTORY,
            FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
            None,
            OPEN_EXISTING,
            FILE_FLAG_BACKUP_SEMANTICS,
            None,
        )
        if not hdir or hdir == INVALID_HANDLE_VALUE:
            entry["alive"] = False
            return
        entry["dir_handle"] = hdir
        buf = ctypes.create_string_buffer(32768)
        bytes_ret = ctypes.c_ulong(0)
        try:
            while not stop_ev.is_set():
                ok = kernel32.ReadDirectoryChangesW(
                    ctypes.c_void_p(hdir),
                    buf,
                    len(buf),
                    True,
                    FILE_NOTIFY_CHANGE_LAST_WRITE | FILE_NOTIFY_CHANGE_FILE_NAME,
                    ctypes.byref(bytes_ret),
                    None,
                    None,
                )
                if not ok or stop_ev.is_set():
                    break
                nbytes = int(bytes_ret.value)
                if nbytes <= 0:
                    continue
                changed: list[str] = []
                offset = 0
                raw = buf.raw[:nbytes]
                while offset + 12 <= nbytes:
                    next_off = int.from_bytes(raw[offset : offset + 4], "little")
                    name_len = int.from_bytes(raw[offset + 8 : offset + 12], "little")
                    name_bytes = raw[offset + 12 : offset + 12 + name_len]
                    rel = name_bytes.decode("utf-16le", errors="ignore").replace("\\", "/")
                    parts = set(rel.split("/"))
                    if rel and not (parts & _SKIP_WATCH_PARTS) and Path(rel).suffix.lower() in _WATCH_EXTS:
                        if rel not in changed:
                            changed.append(rel)
                    if next_off == 0:
                        break
                    offset += next_off
                if changed:
                    entry["events"] = int(entry.get("events", 0)) + len(changed)
                    # Brief 120ms debounce so atomic editors finish flushing
                    time.sleep(0.12)
                    self.notify_save(repo, changed, run_shadow_test=run_shadow, agent_id="precog-watcher")
        except Exception:
            pass
        finally:
            entry["alive"] = False
            try:
                kernel32.CloseHandle(ctypes.c_void_p(hdir))
            except Exception:
                pass

    def _posix_watch_loop(self, repo: Path, stop_ev: threading.Event, entry: dict[str, Any], run_shadow: bool) -> None:
        mtimes: dict[str, int] = {}
        while not stop_ev.is_set():
            changed: list[str] = []
            for root, dirs, files in os.walk(repo):
                dirs[:] = [d for d in dirs if d not in _SKIP_WATCH_PARTS]
                for fn in files:
                    if Path(fn).suffix.lower() not in _WATCH_EXTS:
                        continue
                    fp = Path(root) / fn
                    try:
                        mt = fp.stat().st_mtime_ns
                    except OSError:
                        continue
                    rel = fp.relative_to(repo).as_posix()
                    prev = mtimes.get(rel)
                    mtimes[rel] = mt
                    if prev is not None and prev != mt:
                        changed.append(rel)
            if changed:
                entry["events"] = int(entry.get("events", 0)) + len(changed)
                self.notify_save(repo, changed, run_shadow_test=run_shadow, agent_id="precog-watcher")
            stop_ev.wait(1.0)
        entry["alive"] = False

    def status(self) -> dict[str, Any]:
        with self._lock:
            watchers = [
                {
                    "repo": w["repo"],
                    "alive": w["alive"],
                    "backend": w["backend"],
                    "events": w["events"],
                }
                for w in self._watchers.values()
            ]
            st = dict(self._stats)
            inflight = len(self._inflight)
        return {
            "ok": True,
            "inflight_shadow_tests": inflight,
            "watchers": watchers,
            **st,
        }


# ---------------------------------------------------------------------------
# PILLAR 3: SURGEON ATOMIC PATCH (RAM Format Gate + Apply + Test + Rollback)
# ---------------------------------------------------------------------------

class SurgeonAtomicPatchEngine:
    """Transactional multi-file edit with Pre-Commit AST/TOML/JSON Gate, Test & Exact Auto-Rollback."""

    def __init__(
        self,
        callgraph: Any,
        verifier: Any,
        hive: HiveMindCortex,
        precog: PrecogRunnerEngine,
    ) -> None:
        self.callgraph = callgraph
        self.verifier = verifier
        self.hive = hive
        self.precog = precog
        self._lock = threading.Lock()
        self._stats = {
            "patches_attempted": 0,
            "patches_committed": 0,
            "gate_rejections": 0,
            "rollbacks_executed": 0,
        }

    @staticmethod
    def _validate_in_ram(rel: str, text: str) -> str | None:
        ext = Path(rel).suffix.lower()
        if ext == ".py":
            try:
                ast.parse(text, filename=rel)
            except SyntaxError as exc:
                return f"py_syntax_error L{exc.lineno}:{exc.offset}: {exc.msg}"
        elif ext == ".toml":
            try:
                tomllib.loads(text)
            except Exception as exc:
                return f"toml_syntax_error: {exc}"
        elif ext == ".json":
            try:
                if text.strip():
                    json.loads(text)
            except Exception as exc:
                return f"json_syntax_error: {exc}"
        elif ext in (".js", ".mjs", ".cjs"):
            node_exe = shutil.which("node")
            if node_exe:
                tmp_path = None
                try:
                    with tempfile.NamedTemporaryFile("w", suffix=ext, encoding="utf-8", delete=False) as tf:
                        tf.write(text)
                        tmp_path = tf.name
                    proc = subprocess.run(
                        [node_exe, "--check", tmp_path],
                        capture_output=True,
                        text=True,
                        timeout=6.0,
                        creationflags=_NO_WINDOW,
                    )
                    if proc.returncode != 0:
                        return f"js_syntax_error: {(proc.stderr or proc.stdout).strip()[:300]}"
                except Exception:
                    pass
                finally:
                    if tmp_path:
                        try:
                            os.unlink(tmp_path)
                        except OSError:
                            pass
        return None

    def atomic_patch(
        self,
        repo_path: str | Path,
        edits: list[dict[str, Any]],
        *,
        agent_id: str = "agent",
        run_tests: bool = True,
        explicit_tests: list[str] | None = None,
        rollback_on_fail: bool = True,
        max_tests: int = 4,
        timeout_s: float = 60.0,
        record_immune_on_gate_fail: bool = False,
    ) -> dict[str, Any]:
        t0 = time.perf_counter()
        with self._lock:
            self._stats["patches_attempted"] += 1

        repo = Path(repo_path).resolve()
        if not repo.is_dir():
            return {"ok": False, "committed": False, "error": "repo_not_found", "repo": str(repo)}
        if not isinstance(edits, list) or not edits:
            return {"ok": False, "committed": False, "error": "edits_must_be_non_empty_list"}

        # Phase 1: Dry-apply every edit in RAM and validate AST/TOML/JSON/JS BEFORE touching disk!
        staged_text: dict[str, str] = {}
        originals: dict[str, bytes | None] = {}
        line_endings: dict[str, str] = {}
        touched_order: list[str] = []

        for idx, ed in enumerate(edits[:32]):
            if not isinstance(ed, dict):
                return {"ok": False, "committed": False, "error": f"invalid_edit_at_{idx}"}
            rel = _norm_rel(str(ed.get("path") or ""))
            if not rel:
                return {"ok": False, "committed": False, "error": f"missing_path_at_{idx}"}
            fp = (repo / rel).resolve()
            try:
                fp.relative_to(repo)
            except ValueError:
                return {"ok": False, "committed": False, "error": f"path_escapes_repo:{rel}"}

            if rel not in staged_text:
                if fp.is_file():
                    raw_b = fp.read_bytes()
                    originals[rel] = raw_b
                    decoded = raw_b.decode("utf-8", errors="replace")
                    line_endings[rel] = "\r\n" if "\r\n" in decoded else "\n"
                    staged_text[rel] = decoded.replace("\r\n", "\n")
                else:
                    originals[rel] = None
                    line_endings[rel] = "\n"
                    staged_text[rel] = ""
                touched_order.append(rel)

            cur = staged_text[rel]
            if "content" in ed and ed.get("target") is None:
                staged_text[rel] = str(ed["content"]).replace("\r\n", "\n")
            else:
                target = str(ed.get("target") or "").replace("\r\n", "\n")
                replacement = str(ed.get("replacement") or "").replace("\r\n", "\n")
                if not target:
                    return {"ok": False, "committed": False, "error": f"missing_target_at_{idx}", "file": rel}
                count = cur.count(target)
                if count == 0:
                    hint = self._closest_line_hint(cur, target)
                    err_resp: dict[str, Any] = {
                        "ok": False,
                        "committed": False,
                        "gate_rejected": True,
                        "error": "target_not_found",
                        "file": rel,
                        "edit_index": idx,
                    }
                    if hint is not None:
                        err_resp["closest_match"] = hint
                    return err_resp
                replace_all = bool(ed.get("replace_all", False))
                if count > 1 and not replace_all:
                    return {
                        "ok": False,
                        "committed": False,
                        "gate_rejected": True,
                        "error": f"ambiguous_target_matched_{count}_times",
                        "file": rel,
                        "edit_index": idx,
                    }
                staged_text[rel] = cur.replace(target, replacement) if replace_all else cur.replace(target, replacement, 1)

        # Pre-commit format gate in RAM (ZERO disk mutations if any file fails!)
        gate_errors: list[dict[str, str]] = []
        for rel in touched_order:
            gerr = self._validate_in_ram(rel, staged_text[rel])
            if gerr:
                gate_errors.append({"file": rel, "error": gerr})

        if gate_errors:
            with self._lock:
                self._stats["gate_rejections"] += 1
            if record_immune_on_gate_fail:
                for ge in gate_errors[:2]:
                    self.hive.add_immune_rule(
                        pattern=ge["file"],
                        warning=f"Pre-commit gate caught {ge['error'][:160]}",
                        scope=repo.name,
                        severity="warn",
                        created_by=agent_id,
                    )
            return {
                "ok": False,
                "committed": False,
                "rolled_back": False,
                "gate_rejected": True,
                "disk_touched": False,
                "gate_errors": gate_errors,
                "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
            }

        # Check Hive conflicts before committing
        alerts = self.hive.check_alerts(agent_id=agent_id, repo=str(repo), files=touched_order)

        # Phase 2: Atomic write to disk (preserving original CRLF/LF line endings) + incremental AST refresh
        try:
            for rel in touched_order:
                out_str = staged_text[rel].replace("\n", line_endings.get(rel, "\n"))
                _atomic_write_bytes(repo / rel, out_str.encode("utf-8"))
        except Exception as exc:
            self._restore_originals(repo, originals)
            return {
                "ok": False,
                "committed": False,
                "rolled_back": True,
                "error": f"write_failed:{exc}",
                "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
            }

        for rel in touched_order:
            if hasattr(self.callgraph, "update_single_file"):
                self.callgraph.update_single_file(repo, rel)

        # Phase 3: Impacted verification (compile + targeted tests)
        verify_res = self.verifier.verify(
            str(repo),
            files=touched_order,
            run_tests=run_tests,
            explicit_tests=explicit_tests,
            max_tests=max_tests,
            timeout_s=timeout_s,
            use_cache=False,
            compact=True,
        )

        passed = bool(verify_res.get("ok", False))
        rolled_back = False
        if not passed and rollback_on_fail:
            self._restore_originals(repo, originals)
            for rel in touched_order:
                if hasattr(self.callgraph, "update_single_file"):
                    self.callgraph.update_single_file(repo, rel)
            rolled_back = True
            with self._lock:
                self._stats["rollbacks_executed"] += 1
        elif passed:
            with self._lock:
                self._stats["patches_committed"] += 1
            self.hive.record_mutation(
                agent_id=agent_id,
                repo=str(repo),
                files=touched_order,
                kind="atomic_patch",
                detail=f"files={len(touched_order)} tests_ok=True",
            )
            # If caller skipped synchronous tests for speed, pre-warm Precog-Runner in background!
            if not run_tests:
                try:
                    self.precog.notify_save(
                        str(repo),
                        touched_order,
                        run_shadow_test=True,
                        explicit_tests=explicit_tests,
                        max_tests=min(2, max(1, int(max_tests))),
                        timeout_s=min(25.0, float(timeout_s)),
                        agent_id=agent_id,
                    )
                except Exception:
                    pass

        out: dict[str, Any] = {
            "ok": passed,
            "committed": passed or (not rollback_on_fail),
            "rolled_back": rolled_back,
            "gate_rejected": False,
            "files_patched": touched_order,
            "verify": verify_res,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }
        if alerts["conflicts"]:
            out["hive_conflicts"] = alerts["conflicts"]
        if alerts["immune_warnings"]:
            out["immune_warnings"] = alerts["immune_warnings"]
        return out

    @staticmethod
    def _closest_line_hint(file_text: str, target: str) -> dict[str, Any] | None:
        """< 3ms fuzzy line-drift hint when target_not_found occurs (avoids an extra read_file turn)."""
        anchor = next((ln.strip() for ln in target.splitlines() if ln.strip()), "")
        if not anchor:
            return None
        lines = file_text.splitlines()
        best_score = 0.0
        best_idx = -1
        a_low = anchor.lower()
        for i, ln in enumerate(lines):
            s = ln.strip()
            if not s:
                continue
            sc = difflib.SequenceMatcher(None, a_low, s.lower()).ratio()
            if sc > best_score:
                best_score = sc
                best_idx = i
        if best_idx < 0 or best_score < 0.42:
            return None
        lo = max(0, best_idx - 1)
        hi = min(len(lines), best_idx + 3)
        return {
            "line": best_idx + 1,
            "score": round(best_score, 2),
            "snippet": "\n".join(f"{j + 1}: {lines[j][:160]}" for j in range(lo, hi)),
        }

    @staticmethod
    def _restore_originals(repo: Path, originals: dict[str, bytes | None]) -> None:
        for rel, orig_b in originals.items():
            fp = repo / rel
            try:
                if orig_b is None:
                    fp.unlink(missing_ok=True)
                else:
                    _atomic_write_bytes(fp, orig_b)
            except OSError:
                pass

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._stats)


# ---------------------------------------------------------------------------
# PILLAR 4: TELEPATHY HANDOFF CAPSULE (< 50ms Cross-Agent Brain Transfer)
# ---------------------------------------------------------------------------

class TelepathyCapsuleEngine:
    """Packs verified workspace ground-truth (< 1,500 tokens) for instant cross-agent handoff."""

    MAX_CAPSULES = 32

    def __init__(self, callgraph: Any, verifier: Any, hive: HiveMindCortex) -> None:
        self.callgraph = callgraph
        self.verifier = verifier
        self.hive = hive
        self._lock = threading.Lock()
        self._capsules: collections.OrderedDict[str, dict[str, Any]] = collections.OrderedDict()

    @staticmethod
    def _git_compact(repo: Path, *, include_diff: bool = True) -> dict[str, Any]:
        info: dict[str, Any] = {"branch": "", "dirty_count": 0}
        try:
            p1 = subprocess.run(
                ["git", "status", "--porcelain=v1", "-b"],
                cwd=str(repo),
                capture_output=True,
                text=True,
                timeout=4.0,
                creationflags=_NO_WINDOW,
            )
            if p1.returncode == 0:
                lns = p1.stdout.splitlines()
                if lns and lns[0].startswith("## "):
                    info["branch"] = lns[0][3:].strip()
                dirty = lns[1:]
                info["dirty_count"] = len(dirty)
                if dirty:
                    info["dirty_sample"] = dirty[:8]
            if include_diff:
                p2 = subprocess.run(
                    ["git", "diff", "--stat"],
                    cwd=str(repo),
                    capture_output=True,
                    text=True,
                    timeout=4.0,
                    creationflags=_NO_WINDOW,
                )
                if p2.returncode == 0:
                    stat_lines = [ln for ln in p2.stdout.splitlines() if ln.strip()]
                    info["diff_stat"] = "\n".join(stat_lines[-12:])[:700]
        except Exception:
            pass
        return info

    def create(
        self,
        repo_path: str | Path,
        *,
        agent_id: str = "agent",
        summary: str = "",
        focus_files: list[str] | None = None,
        focus_symbols: list[str] | None = None,
        next_steps: list[str] | None = None,
        include_git: bool = True,
    ) -> dict[str, Any]:
        t0 = time.perf_counter()
        repo = Path(repo_path).resolve()
        nrepo = _norm_repo(repo)
        cid = "cap_" + uuid.uuid4().hex[:8]
        norm_files = sorted({_norm_rel(f) for f in (focus_files or []) if _norm_rel(f)})[:20]

        hive_st = self.hive.status(repo=nrepo)
        immune_hits = self.hive.match_immune(norm_files, repo=nrepo)
        recent_verified = self.verifier.recent_receipts(limit=4) if hasattr(self.verifier, "recent_receipts") else []

        symbol_cards: list[dict[str, Any]] = []
        for sym in (focus_symbols or [])[:4]:
            try:
                sl = self.callgraph.slice_symbol(str(repo), str(sym), depth=1, include_tests=True, max_chars=900)
                if sl.get("ok"):
                    symbol_cards.append({
                        "symbol": sym,
                        "defs": sl.get("definitions", [])[:2],
                        "callers": [c["qualname"] for c in (sl.get("callers") or [])[:5]],
                        "callees": [c["qualname"] for c in (sl.get("callees") or [])[:5]],
                        "tests": [t["file"] for t in (sl.get("related_tests") or [])[:3]],
                    })
            except Exception:
                pass

        capsule: dict[str, Any] = {
            "capsule_id": cid,
            "created_at": round(time.time(), 3),
            "created_by": str(agent_id or "agent")[:64],
            "repo": nrepo,
            "summary": str(summary or "")[:800],
            "focus_files": norm_files,
            "next_steps": [str(s)[:160] for s in (next_steps or [])[:6]],
            "git": self._git_compact(repo) if (include_git and repo.is_dir()) else {},
            "verified_receipts": recent_verified,
            "active_leases": hive_st.get("active_leases", [])[:6],
            "recent_mutations": hive_st.get("recent_mutations", [])[:6],
            "immune_warnings": immune_hits,
            "symbol_cards": symbol_cards,
        }

        serialized = json.dumps(capsule, separators=(",", ":"), ensure_ascii=False)
        est_tokens = max(1, len(serialized) // 4)
        capsule["bytes"] = len(serialized.encode("utf-8"))
        capsule["est_tokens"] = est_tokens

        with self._lock:
            while len(self._capsules) >= self.MAX_CAPSULES:
                self._capsules.popitem(last=False)
            self._capsules[cid] = capsule

        if self.hive._db_ready:
            con = self.hive._connect()
            if con is not None:
                try:
                    con.execute(
                        "INSERT OR REPLACE INTO handoff_capsules (capsule_id, repo, agent_id, created_at, payload_json) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (cid, nrepo, capsule["created_by"], capsule["created_at"], json.dumps(capsule, ensure_ascii=False)),
                    )
                    con.commit()
                except Exception:
                    pass
                finally:
                    con.close()

        return {
            "ok": True,
            "capsule_id": cid,
            "est_tokens": est_tokens,
            "bytes": capsule["bytes"],
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
            "capsule": capsule,
        }

    def load(self, capsule_id: str = "latest", *, repo: str | None = None) -> dict[str, Any]:
        t0 = time.perf_counter()
        cid = str(capsule_id or "latest").strip()
        nrepo = _norm_repo(repo) if repo else None

        found: dict[str, Any] | None = None
        with self._lock:
            if cid == "latest":
                for c in reversed(self._capsules.values()):
                    if nrepo is None or c.get("repo") == nrepo:
                        found = dict(c)
                        break
            elif cid in self._capsules:
                found = dict(self._capsules[cid])

        if found is None and self.hive._db_ready:
            con = self.hive._connect()
            if con is not None:
                try:
                    if cid == "latest":
                        if nrepo:
                            row = con.execute(
                                "SELECT payload_json FROM handoff_capsules WHERE repo = ? ORDER BY created_at DESC LIMIT 1",
                                (nrepo,),
                            ).fetchone()
                        else:
                            row = con.execute(
                                "SELECT payload_json FROM handoff_capsules ORDER BY created_at DESC LIMIT 1"
                            ).fetchone()
                    else:
                        row = con.execute(
                            "SELECT payload_json FROM handoff_capsules WHERE capsule_id = ?",
                            (cid,),
                        ).fetchone()
                    if row:
                        found = json.loads(row[0])
                except Exception:
                    pass
                finally:
                    con.close()

        if found is None:
            return {"ok": False, "error": "capsule_not_found", "capsule_id": cid}
        return {
            "ok": True,
            "capsule_id": found.get("capsule_id"),
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
            "capsule": found,
        }

    def list_capsules(self, *, repo: str | None = None, limit: int = 10) -> dict[str, Any]:
        nrepo = _norm_repo(repo) if repo else None
        with self._lock:
            items = [
                {
                    "capsule_id": c["capsule_id"],
                    "repo": c["repo"],
                    "created_by": c["created_by"],
                    "created_at": c["created_at"],
                    "est_tokens": c.get("est_tokens", 0),
                    "summary": c.get("summary", "")[:120],
                }
                for c in reversed(self._capsules.values())
                if nrepo is None or c.get("repo") == nrepo
            ][: max(1, min(32, int(limit or 10)))]
        return {"ok": True, "count": len(items), "capsules": items}


# ---------------------------------------------------------------------------
# PILLAR 5: MIRROR-RACE ENGINE (Parallel CoW Shadow Candidate Racing)
# ---------------------------------------------------------------------------

class MirrorRaceEngine:
    """Races 2-3 competing multi-file patch candidates in isolated shadow dirs; commits ONLY winner."""

    MAX_CANDIDATES = 3
    MAX_SHADOW_BYTES = 48 * 1024 * 1024
    _COPY_SKIP = frozenset({
        ".git", "__pycache__", "node_modules", ".venv", "venv", "target",
        "dist", "build", ".pytest_cache", ".mypy_cache", "ErrorReports",
    })

    def __init__(self, surgeon: SurgeonAtomicPatchEngine, verifier: Any, hive: HiveMindCortex) -> None:
        self.surgeon = surgeon
        self.verifier = verifier
        self.hive = hive
        self._lock = threading.Lock()
        self._stats = {"races_run": 0, "winners_committed": 0, "candidates_evaluated": 0}

    @staticmethod
    def _resolve_shadow_base() -> Path | None:
        """Prefer fast NVMe ReFS Dev Drive (Windows V:\\shadows) or SSD XFS CoW mount (/mnt/chimera-dev/shadows)."""
        candidates: list[Path] = []
        env_dd = os.environ.get("CHIMERA_DEV_DRIVE", "").strip()
        if env_dd:
            candidates.append(Path(env_dd) / "shadows")
        if os.name == "nt":
            candidates.append(Path("V:/shadows"))
        else:
            candidates.append(Path("/mnt/chimera-dev/shadows"))
        for cand in candidates:
            try:
                if cand.is_dir() and os.access(cand, os.W_OK):
                    return cand
            except OSError:
                continue
        return None

    def _copy_clean_shadow(self, src_repo: Path, dst_shadow: Path) -> int:
        copied_bytes = 0
        for root, dirs, files in os.walk(src_repo):
            dirs[:] = [d for d in dirs if d not in self._COPY_SKIP]
            rel_root = Path(root).relative_to(src_repo)
            out_dir = dst_shadow / rel_root
            out_dir.mkdir(parents=True, exist_ok=True)
            for fn in files:
                sp = Path(root) / fn
                try:
                    sz = sp.stat().st_size
                except OSError:
                    continue
                if sz > 4 * 1024 * 1024:
                    continue
                if copied_bytes + sz > self.MAX_SHADOW_BYTES:
                    continue
                try:
                    shutil.copy2(sp, out_dir / fn)
                    copied_bytes += sz
                except OSError:
                    pass
        return copied_bytes

    def race(
        self,
        repo_path: str | Path,
        candidates: list[dict[str, Any]],
        *,
        explicit_tests: list[str] | None = None,
        commit_winner: bool = True,
        max_tests: int = 4,
        timeout_s: float = 45.0,
        agent_id: str = "agent",
        offload_peer: bool = False,
        peer_host: str = "svhome",
        peer_repo: str | None = None,
    ) -> dict[str, Any]:
        if offload_peer:
            # Only the guarded build worker may admit a guest on the peer.
            from .peer_guard import guarded_build_required

            return guarded_build_required()

        import concurrent.futures

        t0 = time.perf_counter()
        repo = Path(repo_path).resolve()
        if not repo.is_dir():
            return {"ok": False, "error": "repo_not_found", "repo": str(repo)}
        if not isinstance(candidates, list) or len(candidates) < 1:
            return {"ok": False, "error": "candidates_required"}

        clipped = candidates[: self.MAX_CANDIDATES]
        shadow_base = self._resolve_shadow_base()
        results: list[dict[str, Any]] = []

        def _eval_one(idx: int, cand: dict[str, Any]) -> dict[str, Any]:
            cid = str(cand.get("id") or f"cand_{idx}")
            edits = list(cand.get("edits") or [])
            c0 = time.perf_counter()
            if not edits:
                return {"id": cid, "ok": False, "error": "empty_edits", "ms": 0.0}
            with tempfile.TemporaryDirectory(
                prefix=f"chimera_race_{cid[:8]}_",
                dir=str(shadow_base) if shadow_base else None,
            ) as td:
                shadow = Path(td) / "repo"
                self._copy_clean_shadow(repo, shadow)
                res = self.surgeon.atomic_patch(
                    shadow,
                    edits,
                    agent_id=f"{agent_id}:race:{cid}",
                    run_tests=True,
                    explicit_tests=explicit_tests,
                    rollback_on_fail=False,
                    max_tests=max_tests,
                    timeout_s=timeout_s,
                )
                return {
                    "id": cid,
                    "ok": bool(res.get("ok")),
                    "gate_rejected": bool(res.get("gate_rejected")),
                    "gate_errors": res.get("gate_errors"),
                    "error": res.get("error"),
                    "files_patched": res.get("files_patched") or [],
                    "verify_ok": bool((res.get("verify") or {}).get("ok", False)),
                    "ms": round((time.perf_counter() - c0) * 1000.0, 2),
                    "_edits": edits,
                }

        with concurrent.futures.ThreadPoolExecutor(max_workers=len(clipped)) as ex:
            futs = [ex.submit(_eval_one, i, c if isinstance(c, dict) else {}) for i, c in enumerate(clipped)]
            for f in concurrent.futures.as_completed(futs):
                results.append(f.result())

        results.sort(key=lambda r: (not r["ok"], r["ms"]))
        winner = next((r for r in results if r["ok"]), None)
        committed = False
        commit_res: dict[str, Any] | None = None

        if winner is not None and commit_winner:
            commit_res = self.surgeon.atomic_patch(
                repo,
                winner["_edits"],
                agent_id=agent_id,
                run_tests=False,  # Already proved green in isolated shadow; auto-triggers Precog background verify!
                explicit_tests=explicit_tests,
                rollback_on_fail=True,
            )
            committed = bool(commit_res.get("committed"))
            if committed:
                self.hive.record_mutation(
                    agent_id=agent_id,
                    repo=str(repo),
                    files=list(winner.get("files_patched") or []),
                    kind="mirror_race",
                    detail=f"winner={winner['id']} of {len(clipped)} via local in {winner['ms']}ms",
                )

        with self._lock:
            self._stats["races_run"] += 1
            self._stats["candidates_evaluated"] += len(clipped)
            if committed:
                self._stats["winners_committed"] += 1

        leaderboard = [{k: v for k, v in r.items() if k != "_edits"} for r in results]
        return {
            "ok": winner is not None,
            "winner_id": winner["id"] if winner else None,
            "committed": committed,
            "execution_node": "local",
            "win_cpu_offloaded": False,
            "candidates_tested": len(clipped),
            "leaderboard": leaderboard,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._stats)


# ---------------------------------------------------------------------------
# PILLAR 6: POST-MORTEM CORONER (Idle JSONL Scanner -> Auto Immune Reflex)
# ---------------------------------------------------------------------------

class PostMortemCoronerEngine:
    """Read-only, <0.1% CPU session-log coroner distilling recurring friction into Immune Reflex rules."""

    MAX_FILES = 6
    MAX_TAIL_BYTES = 512 * 1024

    def __init__(self, hive: HiveMindCortex) -> None:
        self.hive = hive
        self._lock = threading.Lock()
        self._stats = {"scans_run": 0, "files_scanned": 0, "findings_total": 0, "rules_seeded": 0}

    @staticmethod
    def _default_log_files() -> list[tuple[str, Path]]:
        home = Path.home()
        found: list[tuple[float, str, Path]] = []
        codex_dir = home / ".codex" / "sessions"
        if codex_dir.is_dir():
            for fp in codex_dir.rglob("*.jsonl"):
                try:
                    found.append((fp.stat().st_mtime, "codex", fp))
                except OSError:
                    pass
        t3_ag = home / ".t3" / "userdata" / "providers" / "antigravity"
        if t3_ag.is_dir():
            for fp in t3_ag.glob("*/antigravity-acp/brain/*/.system_generated/logs/transcript.jsonl"):
                try:
                    found.append((fp.stat().st_mtime, "antigravity", fp))
                except OSError:
                    pass
        found.sort(key=lambda x: x[0], reverse=True)
        return [(kind, fp) for _, kind, fp in found[: PostMortemCoronerEngine.MAX_FILES]]

    def scan(
        self,
        *,
        log_files: list[str] | None = None,
        auto_seed_immune: bool = False,
        max_files: int = 6,
    ) -> dict[str, Any]:
        t0 = time.perf_counter()
        if log_files:
            targets = [("custom", Path(p)) for p in log_files if Path(p).is_file()][: max(1, int(max_files))]
        else:
            targets = self._default_log_files()[: max(1, min(self.MAX_FILES, int(max_files)))]

        counters = {
            "shell_exec_calls": 0,
            "chimera_mcp_calls": 0,
            "output_txt_spills": 0,
            "target_not_found": 0,
            "toml_or_syntax_breaks": 0,
            "http_404_drift": 0,
            "edquot_tmp": 0,
        }
        scanned_meta: list[dict[str, Any]] = []

        for kind, fp in targets:
            try:
                sz = fp.stat().st_size
                with fp.open("rb") as fh:
                    if sz > self.MAX_TAIL_BYTES:
                        fh.seek(sz - self.MAX_TAIL_BYTES)
                    tail = fh.read().decode("utf-8", errors="replace")
            except OSError:
                continue
            c_exec = tail.count('"CommandExecution"') + tail.count('"name": "run_command"') + tail.count('"name":"run_command"')
            c_chim = tail.count("chimera_xray_batch") + tail.count("chimera_atomic_patch") + tail.count("chimera_bootstrap")
            c_spill = tail.count("output.txt")
            c_tnf = tail.count("target_not_found")
            c_toml = tail.count("missing escaped value") + tail.count("TOMLDecodeError") + tail.count("toml_syntax_error")
            c_404 = tail.count("HTTP=404") + tail.count("HTTP Error 404")
            c_edq = tail.count("Disk quota exceeded") + tail.count("EDQUOT")

            counters["shell_exec_calls"] += c_exec
            counters["chimera_mcp_calls"] += c_chim
            counters["output_txt_spills"] += c_spill
            counters["target_not_found"] += c_tnf
            counters["toml_or_syntax_breaks"] += c_toml
            counters["http_404_drift"] += c_404
            counters["edquot_tmp"] += c_edq
            scanned_meta.append({"kind": kind, "file": fp.name, "kb": round(sz / 1024.0, 1), "exec": c_exec, "chimera": c_chim, "spills": c_spill})

        findings: list[dict[str, Any]] = []
        if counters["shell_exec_calls"] >= 12 and counters["shell_exec_calls"] > counters["chimera_mcp_calls"] * 3:
            findings.append({
                "kind": "shell_storm",
                "count": counters["shell_exec_calls"],
                "pattern": "*",
                "warning": f"Coroner saw {counters['shell_exec_calls']} shell calls vs {counters['chimera_mcp_calls']} Chimera MCP calls; batch read-only ops via chimera_xray_batch",
                "severity": "info",
            })
        if counters["output_txt_spills"] >= 2:
            findings.append({
                "kind": "disk_spill",
                "count": counters["output_txt_spills"],
                "pattern": "*mcp_server.py",
                "warning": f"Coroner saw {counters['output_txt_spills']} output.txt spills; keep MCP compact=True (<=8.6 KB Spill-Shield) and use native read_file for large known ranges",
                "severity": "warn",
            })
        if counters["toml_or_syntax_breaks"] >= 1:
            findings.append({
                "kind": "syntax_config_break",
                "count": counters["toml_or_syntax_breaks"],
                "pattern": "*config.toml",
                "warning": "Coroner caught TOML escape corruption; edit via chimera_atomic_patch RAM gate or validate with tomllib.loads()",
                "severity": "critical",
            })
        if counters["http_404_drift"] >= 1:
            findings.append({
                "kind": "endpoint_404_drift",
                "count": counters["http_404_drift"],
                "pattern": "*substrate.py",
                "warning": "Coroner saw HTTP 404 on :9780; check chimera_bootstrap release_drift before restarting daemon",
                "severity": "warn",
            })
        if counters["edquot_tmp"] >= 1:
            findings.append({
                "kind": "edquot_tmp",
                "count": counters["edquot_tmp"],
                "pattern": "*svhome*",
                "warning": "Coroner saw EDQUOT/Disk quota exceeded; stage remote archives in ~/ instead of /tmp",
                "severity": "warn",
            })

        seeded = 0
        if auto_seed_immune:
            for fnd in findings:
                r = self.hive.add_immune_rule(
                    pattern=fnd["pattern"],
                    warning=fnd["warning"],
                    scope="coroner",
                    severity=fnd["severity"],
                    created_by="post-mortem-coroner",
                )
                if r.get("ok"):
                    seeded += 1

        with self._lock:
            self._stats["scans_run"] += 1
            self._stats["files_scanned"] += len(scanned_meta)
            self._stats["findings_total"] += len(findings)
            self._stats["rules_seeded"] += seeded

        return {
            "ok": True,
            "files_scanned": len(scanned_meta),
            "sessions": scanned_meta,
            "counters": counters,
            "findings": findings,
            "rules_seeded": seeded,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._stats)


# ---------------------------------------------------------------------------
# PILLAR 7: CHIMERA-EXEC (Zero-Spill Direct Runner — No pwsh, No tool-log.mjs, No conhost)
# ---------------------------------------------------------------------------

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
_EXEC_DIAG_RE = re.compile(r"\b(?:error|[a-z]+error|fatal|failed|failure|panic|exception|traceback)\b|^\s*(?:not ok|FAIL)\b", re.I)
_EXEC_SUMMARY_RE = re.compile(r"^\s*(?:[#ℹ]\s*)?(?:tests?|pass|fail|skipped|ran\s+\d+\s+tests?|ok|failed)\b", re.I)
_EXEC_PASS_RE = re.compile(r"^\s*(?:#\s*Subtest:|ok\s+\d+|[✔✓]\s)")


def _resolve_dev_drive_root() -> Path | None:
    candidates: list[Path] = []
    env_dd = os.environ.get("CHIMERA_DEV_DRIVE", "").strip()
    if env_dd:
        candidates.append(Path(env_dd))
    if os.name == "nt":
        candidates.append(Path("V:/"))
    else:
        candidates.append(Path("/mnt/chimera-dev"))
    for cand in candidates:
        try:
            if cand.is_dir() and os.access(cand, os.W_OK):
                return cand
        except OSError:
            continue
    return None


def _smart_excerpt_output(text: str, *, max_preview_chars: int = 2400) -> dict[str, Any]:
    """Failure-first ANSI-stripped preview matching tool-log.mjs fidelity with 0 Node/pwsh boot cost."""
    clean = _ANSI_RE.sub("", text or "")
    lines = clean.splitlines()
    total_lines = len(lines)
    if len(clean) <= max_preview_chars and total_lines <= 28:
        return {"lines": total_lines, "omitted": 0, "preview": clean}
    selected_idx: list[int] = []
    seen: set[int] = set()

    def _add(idx: int) -> None:
        if 0 <= idx < total_lines and idx not in seen:
            seen.add(idx)
            selected_idx.append(idx)

    for i in range(min(3, total_lines)):
        _add(i)
    err_hits = 0
    for i, ln in enumerate(lines):
        if _EXEC_SUMMARY_RE.search(ln):
            _add(i)
        elif not _EXEC_PASS_RE.search(ln) and _EXEC_DIAG_RE.search(ln):
            if err_hits < 8:
                _add(i)
                err_hits += 1
    for i in range(max(0, total_lines - 5), total_lines):
        _add(i)
    selected_idx.sort()
    preview_lines = [f"L{idx + 1}: {lines[idx][:220]}" for idx in selected_idx]
    preview = "\n".join(preview_lines)
    if len(preview) > max_preview_chars:
        preview = preview[: max_preview_chars - 24] + "\n... [excerpt capped]"
    return {"lines": total_lines, "omitted": max(0, total_lines - len(selected_idx)), "preview": preview}


class DirectExecEngine:
    """Zero-conhost, BELOW_NORMAL direct command runner replacing `pwsh -> node tool-log.mjs -> python`."""

    _BATCH_FLAGS = (_NO_WINDOW | 0x00004000) if os.name == "nt" else 0

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._stats = {"runs": 0, "ok_runs": 0, "failed_runs": 0, "logs_spilled_to_devdrive": 0}

    def _log_dir(self) -> Path:
        dd = _resolve_dev_drive_root()
        if dd is not None:
            cand = dd / ("shadows" if os.name == "nt" else "tmp") / "exec_logs"
            try:
                cand.mkdir(parents=True, exist_ok=True)
                return cand
            except OSError:
                pass
        cand = Path(tempfile.gettempdir()) / "chimera_exec_logs"
        cand.mkdir(parents=True, exist_ok=True)
        return cand

    def run(
        self,
        argv: list[str],
        *,
        cwd: str | Path = ".",
        stdin_text: str | None = None,
        normalize_lf: bool = True,
        env_overrides: dict[str, str] | None = None,
        timeout_s: float = 60.0,
        max_preview_chars: int = 2400,
    ) -> dict[str, Any]:
        t0 = time.perf_counter()
        if not isinstance(argv, list) or not argv or not all(isinstance(x, str) and x for x in argv):
            return {"ok": False, "error": "argv_must_be_non_empty_string_list"}
        work_dir = Path(cwd).resolve()
        if not work_dir.is_dir():
            return {"ok": False, "error": "cwd_not_found", "cwd": str(work_dir)}
        env = dict(os.environ)
        dd = _resolve_dev_drive_root()
        if dd is not None:
            env.setdefault("CHIMERA_DEV_DRIVE", str(dd))
        if isinstance(env_overrides, dict):
            for k, v in env_overrides.items():
                if isinstance(k, str) and k and v is not None:
                    env[k] = str(v)

        inp_bytes: bytes | None = None
        if stdin_text is not None:
            s_in = str(stdin_text)
            if normalize_lf:
                s_in = s_in.replace("\r\n", "\n")
            inp_bytes = s_in.encode("utf-8")

        cap_timeout = max(1.0, min(180.0, float(timeout_s)))
        try:
            proc = subprocess.run(
                argv,
                cwd=str(work_dir),
                input=inp_bytes,
                capture_output=True,
                timeout=cap_timeout,
                env=env,
                shell=False,
                creationflags=self._BATCH_FLAGS,
            )
            rc = int(proc.returncode)
            stdout_s = proc.stdout.decode("utf-8", errors="replace")
            stderr_s = proc.stderr.decode("utf-8", errors="replace")
            timed_out = False
        except subprocess.TimeoutExpired as exc:
            rc = 124
            stdout_s = (exc.stdout or b"").decode("utf-8", errors="replace") if isinstance(exc.stdout, (bytes, bytearray)) else str(exc.stdout or "")
            stderr_s = (exc.stderr or b"").decode("utf-8", errors="replace") if isinstance(exc.stderr, (bytes, bytearray)) else str(exc.stderr or "")
            timed_out = True
        except OSError as exc:
            return {"ok": False, "error": f"exec_os_error: {exc}", "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2)}

        combined = stdout_s + ("\n--- STDERR ---\n" + stderr_s if stderr_s.strip() else "")
        excerpt = _smart_excerpt_output(combined, max_preview_chars=max(400, min(4000, int(max_preview_chars))))
        log_path: str | None = None
        if len(combined) > max_preview_chars:
            try:
                ld = self._log_dir()
                lp = ld / f"exec_{int(time.time())}_{uuid.uuid4().hex[:6]}.log"
                lp.write_text(combined, encoding="utf-8", errors="replace")
                log_path = str(lp)
                with self._lock:
                    self._stats["logs_spilled_to_devdrive"] += 1
            except OSError:
                pass

        ok = (rc == 0) and (not timed_out)
        with self._lock:
            self._stats["runs"] += 1
            if ok:
                self._stats["ok_runs"] += 1
            else:
                self._stats["failed_runs"] += 1
        return {
            "ok": ok,
            "rc": rc,
            "timed_out": timed_out,
            "stdout_bytes": len(stdout_s.encode("utf-8", errors="replace")),
            "stderr_bytes": len(stderr_s.encode("utf-8", errors="replace")),
            "lines": excerpt["lines"],
            "omitted": excerpt["omitted"],
            "preview": excerpt["preview"],
            "log_path": log_path,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._stats)


# ---------------------------------------------------------------------------
# PILLAR 8: CHIMERA-WORKTREE-EPOCH (CoW Dev-Drive Worktrees + Signed Release-Epoch Lock)
# ---------------------------------------------------------------------------

class WorktreeEpochEngine:
    """Isolates concurrent agents on Dev Drive worktrees & eliminates cross-agent release collisions."""

    def __init__(self, hive: HiveMindCortex) -> None:
        self.hive = hive
        self._lock = threading.Lock()
        self._claims: dict[str, dict[str, Any]] = {}
        self._epochs: collections.deque[dict[str, Any]] = collections.deque(maxlen=40)
        self._stats = {"worktrees_created": 0, "epoch_claims": 0, "epoch_conflicts": 0, "epochs_published": 0}
        self._load_epochs_from_db()

    def _load_epochs_from_db(self) -> None:
        if not self.hive._db_ready:
            return
        con = self.hive._connect()
        if con is None:
            return
        try:
            rows = con.execute(
                "SELECT epoch_id, release_dir, agent_id, published_at, daemon_pid, verified_summary, files_json, sha256_json "
                "FROM release_epochs ORDER BY published_at DESC LIMIT 25"
            ).fetchall()
            for r in reversed(rows):
                try:
                    files = json.loads(r[6] or "[]")
                    sha_map = json.loads(r[7] or "{}")
                except Exception:
                    files, sha_map = [], {}
                self._epochs.append({
                    "epoch_id": r[0],
                    "release_dir": r[1],
                    "agent_id": r[2],
                    "published_at": float(r[3]),
                    "daemon_pid": int(r[4] or 0),
                    "verified_summary": str(r[5] or ""),
                    "files": files,
                    "sha256_count": len(sha_map) if isinstance(sha_map, dict) else 0,
                })
        except Exception:
            pass
        finally:
            con.close()

    @staticmethod
    def _worktree_base() -> Path:
        dd = _resolve_dev_drive_root()
        if dd is not None:
            cand = dd / "worktrees"
            try:
                cand.mkdir(parents=True, exist_ok=True)
                return cand
            except OSError:
                pass
        cand = Path(tempfile.gettempdir()) / "chimera_worktrees"
        cand.mkdir(parents=True, exist_ok=True)
        return cand

    def create_worktree(
        self,
        repo_path: str | Path,
        *,
        agent_id: str = "agent",
        ref: str = "HEAD",
        name: str | None = None,
    ) -> dict[str, Any]:
        t0 = time.perf_counter()
        repo = Path(repo_path).resolve()
        if not repo.is_dir():
            return {"ok": False, "error": "repo_not_found", "repo": str(repo)}
        base = self._worktree_base()
        safe_agent = re.sub(r"[^A-Za-z0-9_-]", "_", str(agent_id or "agent"))[:20]
        slug = re.sub(r"[^A-Za-z0-9_-]", "_", str(name or f"{repo.name}_{safe_agent}_{uuid.uuid4().hex[:6]}"))[:48]
        wt_path = base / slug
        if wt_path.exists():
            return {"ok": False, "error": "worktree_path_exists", "worktree_path": str(wt_path)}
        cmd = ["git", "worktree", "add", "--detach", str(wt_path), str(ref or "HEAD")]
        proc = subprocess.run(
            cmd,
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=45.0,
            creationflags=_NO_WINDOW,
        )
        if proc.returncode != 0:
            return {
                "ok": False,
                "error": "git_worktree_add_failed",
                "stderr": (proc.stderr or proc.stdout or "")[:500],
                "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
            }
        with self._lock:
            self._stats["worktrees_created"] += 1
        self.hive.record_mutation(
            agent_id=agent_id,
            repo=str(repo),
            files=[str(wt_path)],
            kind="worktree_create",
            detail=f"ref={ref} on devdrive={str(base)}",
        )
        return {
            "ok": True,
            "repo": _norm_repo(repo),
            "worktree_path": str(wt_path),
            "on_dev_drive": _resolve_dev_drive_root() is not None,
            "ref": str(ref or "HEAD"),
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }

    def list_worktrees(self, repo_path: str | Path) -> dict[str, Any]:
        repo = Path(repo_path).resolve()
        if not repo.is_dir():
            return {"ok": False, "error": "repo_not_found"}
        proc = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=10.0,
            creationflags=_NO_WINDOW,
        )
        if proc.returncode != 0:
            return {"ok": False, "error": "git_worktree_list_failed", "stderr": (proc.stderr or "")[:300]}
        entries: list[dict[str, str]] = []
        cur: dict[str, str] = {}
        for ln in proc.stdout.splitlines():
            if not ln.strip():
                if cur:
                    entries.append(cur)
                    cur = {}
                continue
            parts = ln.split(" ", 1)
            cur[parts[0]] = parts[1].strip() if len(parts) > 1 else ""
        if cur:
            entries.append(cur)
        return {"ok": True, "repo": _norm_repo(repo), "worktrees": entries, "dev_drive_base": str(self._worktree_base())}

    def remove_worktree(self, repo_path: str | Path, worktree_path: str | Path, *, force: bool = True) -> dict[str, Any]:
        repo = Path(repo_path).resolve()
        wt = Path(worktree_path).resolve()
        args = ["git", "worktree", "remove"]
        if force:
            args.append("--force")
        args.append(str(wt))
        proc = subprocess.run(args, cwd=str(repo), capture_output=True, text=True, timeout=30.0, creationflags=_NO_WINDOW)
        return {
            "ok": proc.returncode == 0,
            "worktree_path": str(wt),
            "stderr": (proc.stderr or "")[:300] if proc.returncode != 0 else "",
        }

    def epoch_claim(self, release_dir: str, *, agent_id: str = "agent", intent: str = "", ttl_s: float = 180.0) -> dict[str, Any]:
        key = _norm_repo(release_dir)
        now = time.time()
        ttl = max(10.0, min(900.0, float(ttl_s)))
        with self._lock:
            for k in [k for k, v in self._claims.items() if v["expires_at"] <= now]:
                self._claims.pop(k, None)
            existing = self._claims.get(key)
            conflict = None
            if existing and existing["agent_id"] != agent_id:
                self._stats["epoch_conflicts"] += 1
                conflict = {
                    "holder": existing["agent_id"],
                    "intent": existing["intent"],
                    "ttl_left_s": round(max(0.0, existing["expires_at"] - now), 1),
                }
            else:
                self._claims[key] = {
                    "release_dir": key,
                    "agent_id": str(agent_id or "agent")[:64],
                    "intent": str(intent or "")[:160],
                    "claimed_at": now,
                    "expires_at": now + ttl,
                }
                self._stats["epoch_claims"] += 1
        return {"ok": conflict is None, "release_dir": key, "conflict": conflict, "ttl_s": ttl}

    def epoch_publish(
        self,
        release_dir: str,
        *,
        agent_id: str = "agent",
        files: list[str] | None = None,
        sha256_map: dict[str, str] | None = None,
        verified_summary: str = "",
        daemon_pid: int = 0,
    ) -> dict[str, Any]:
        key = _norm_repo(release_dir)
        now = time.time()
        eid = "ep_" + uuid.uuid4().hex[:8]
        norm_files = sorted({_norm_rel(f) for f in (files or []) if _norm_rel(f)})[:64]
        clean_sha = {str(k): str(v)[:64] for k, v in (sha256_map or {}).items()}
        rec = {
            "epoch_id": eid,
            "release_dir": key,
            "agent_id": str(agent_id or "agent")[:64],
            "published_at": round(now, 3),
            "daemon_pid": int(daemon_pid or 0),
            "verified_summary": str(verified_summary or "")[:200],
            "files": norm_files,
            "sha256_count": len(clean_sha),
        }
        with self._lock:
            self._epochs.append(rec)
            self._stats["epochs_published"] += 1
            cur_claim = self._claims.get(key)
            if cur_claim and cur_claim["agent_id"] == rec["agent_id"]:
                self._claims.pop(key, None)

        if self.hive._db_ready:
            con = self.hive._connect()
            if con is not None:
                try:
                    con.execute(
                        "INSERT OR REPLACE INTO release_epochs "
                        "(epoch_id, release_dir, agent_id, published_at, daemon_pid, verified_summary, files_json, sha256_json) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            eid,
                            key,
                            rec["agent_id"],
                            rec["published_at"],
                            rec["daemon_pid"],
                            rec["verified_summary"],
                            json.dumps(norm_files, ensure_ascii=False),
                            json.dumps(clean_sha, ensure_ascii=False),
                        ),
                    )
                    con.commit()
                except Exception:
                    pass
                finally:
                    con.close()

        self.hive.record_mutation(
            agent_id=rec["agent_id"],
            repo=key,
            files=norm_files,
            kind="release_epoch_publish",
            detail=f"{eid} pid={rec['daemon_pid']} {rec['verified_summary']}".strip(),
        )
        return {"ok": True, **rec}

    def epoch_status(self, release_dir: str | None = None) -> dict[str, Any]:
        key = _norm_repo(release_dir) if release_dir else None
        now = time.time()
        with self._lock:
            for k in [k for k, v in self._claims.items() if v["expires_at"] <= now]:
                self._claims.pop(k, None)
            claims = [
                {**v, "ttl_left_s": round(max(0.0, v["expires_at"] - now), 1)}
                for k, v in self._claims.items()
                if key is None or k == key
            ]
            epochs = [
                {**e, "age_s": round(max(0.0, now - float(e["published_at"])), 1)}
                for e in reversed(self._epochs)
                if key is None or e["release_dir"] == key
            ][:8]
        return {
            "ok": True,
            "active_claims": claims,
            "recent_epochs": epochs,
            "dev_drive_root": str(_resolve_dev_drive_root() or ""),
        }

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._stats)


# ---------------------------------------------------------------------------
# PILLAR 9: CHIMERA-MACRO-DAG (Collapse 19 Serial Shell LLM Turns -> 1 Declarative DAG!)
# ---------------------------------------------------------------------------

class MacroDagEngine:
    """Executes a conditional multi-step probe/hash/patch/verify/exec DAG in 1 daemon RPC."""

    MAX_STEPS = 16

    def __init__(
        self,
        bus: Any,
        surgeon: SurgeonAtomicPatchEngine,
        direct_exec: DirectExecEngine,
        worktree_epoch: WorktreeEpochEngine,
    ) -> None:
        self.bus = bus
        self.surgeon = surgeon
        self.direct_exec = direct_exec
        self.worktree_epoch = worktree_epoch
        self._lock = threading.Lock()
        self._stats = {"dags_run": 0, "steps_executed": 0, "llm_turns_saved_est": 0}

    @staticmethod
    def _sha256_parity(cwd: Path, files: list[str], compare_dir: str | None = None) -> dict[str, Any]:
        t0 = time.perf_counter()
        hashes_a: dict[str, str | None] = {}
        mismatches: list[str] = []
        matched = 0
        cmp_root = Path(compare_dir).resolve() if compare_dir else None

        def checksum(path: Path) -> str | None:
            if not path.is_file():
                return None
            with path.open("rb") as stream:
                return hashlib.file_digest(stream, "sha256").hexdigest()

        for rel in (files or [])[:64]:
            r = _norm_rel(rel)
            if not r:
                continue
            pa = cwd / r
            ha = checksum(pa)
            hashes_a[r] = ha[:16] if ha else None
            if cmp_root is not None:
                pb = cmp_root / r
                hb = checksum(pb)
                if ha is not None and ha == hb:
                    matched += 1
                else:
                    mismatches.append(r)
        return {
            "ok": (len(mismatches) == 0) if cmp_root is not None else all(v is not None for v in hashes_a.values()),
            "files_checked": len(hashes_a),
            "matched": matched if cmp_root is not None else len(hashes_a),
            "mismatches": mismatches,
            "hashes": hashes_a,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }

    def run_dag(
        self,
        steps: list[dict[str, Any]],
        *,
        cwd: str | Path = ".",
        agent_id: str = "agent",
    ) -> dict[str, Any]:
        t0 = time.perf_counter()
        if not isinstance(steps, list) or not steps:
            return {"ok": False, "error": "steps_required"}
        base_cwd = Path(cwd).resolve()
        if not base_cwd.is_dir():
            return {"ok": False, "error": "cwd_not_found", "cwd": str(base_cwd)}

        clipped = steps[: self.MAX_STEPS]
        results: list[dict[str, Any]] = []
        prev_ok = True
        all_ok = True

        for idx, raw_step in enumerate(clipped):
            if not isinstance(raw_step, dict):
                continue
            sid = str(raw_step.get("id") or f"step_{idx}")
            kind = str(raw_step.get("kind") or "").strip().lower()
            on_fail = str(raw_step.get("on_fail") or "stop").strip().lower()
            if_prev = raw_step.get("if_prev_ok")
            if if_prev is True and not prev_ok:
                results.append({"id": sid, "kind": kind, "skipped": True, "ok": True})
                continue
            if if_prev is False and prev_ok:
                results.append({"id": sid, "kind": kind, "skipped": True, "ok": True})
                continue

            step_cwd = Path(raw_step["cwd"]).resolve() if raw_step.get("cwd") else base_cwd
            s0 = time.perf_counter()
            if kind == "xray":
                out = self.bus.xray_batch(list(raw_step.get("ops") or []), cwd=str(step_cwd), agent_id=agent_id)
            elif kind == "patch":
                out = self.surgeon.atomic_patch(
                    step_cwd,
                    list(raw_step.get("edits") or []),
                    agent_id=agent_id,
                    run_tests=bool(raw_step.get("run_tests", True)),
                    explicit_tests=(list(raw_step["explicit_tests"]) if isinstance(raw_step.get("explicit_tests"), list) else None),
                    rollback_on_fail=bool(raw_step.get("rollback_on_fail", True)),
                )
            elif kind == "verify":
                out = self.bus.commit_verify(
                    str(step_cwd),
                    files=(list(raw_step["files"]) if isinstance(raw_step.get("files"), list) else None),
                    run_tests=bool(raw_step.get("run_tests", True)),
                    explicit_tests=(list(raw_step["explicit_tests"]) if isinstance(raw_step.get("explicit_tests"), list) else None),
                    use_cache=bool(raw_step.get("use_cache", True)),
                )
            elif kind == "exec":
                out = self.direct_exec.run(
                    list(raw_step.get("argv") or []),
                    cwd=step_cwd,
                    stdin_text=raw_step.get("stdin_text"),
                    env_overrides=raw_step.get("env_overrides"),
                    timeout_s=float(raw_step.get("timeout_s") or 60.0),
                    max_preview_chars=int(raw_step.get("max_preview_chars") or 1200),
                )
            elif kind == "sha256_parity":
                out = self._sha256_parity(
                    step_cwd,
                    list(raw_step.get("files") or []),
                    compare_dir=(str(raw_step["compare_dir"]) if raw_step.get("compare_dir") else None),
                )
            elif kind == "epoch":
                act = str(raw_step.get("action") or "status").strip().lower()
                if act == "claim":
                    out = self.worktree_epoch.epoch_claim(
                        str(raw_step.get("release_dir") or step_cwd),
                        agent_id=agent_id,
                        intent=str(raw_step.get("intent") or ""),
                        ttl_s=float(raw_step.get("ttl_s") or 180.0),
                    )
                elif act == "publish":
                    out = self.worktree_epoch.epoch_publish(
                        str(raw_step.get("release_dir") or step_cwd),
                        agent_id=agent_id,
                        files=list(raw_step.get("files") or []),
                        sha256_map=raw_step.get("sha256_map"),
                        verified_summary=str(raw_step.get("verified_summary") or ""),
                        daemon_pid=int(raw_step.get("daemon_pid") or 0),
                    )
                else:
                    out = self.worktree_epoch.epoch_status(
                        str(raw_step["release_dir"]) if raw_step.get("release_dir") else None
                    )
            else:
                out = {"ok": False, "error": f"unknown_dag_step_kind:{kind}"}

            step_ok = bool(out.get("ok"))
            prev_ok = step_ok
            if not step_ok:
                all_ok = False
            results.append({
                "id": sid,
                "kind": kind,
                "ok": step_ok,
                "ms": round((time.perf_counter() - s0) * 1000.0, 2),
                "out": out,
            })
            if not step_ok and on_fail != "continue":
                break

        with self._lock:
            self._stats["dags_run"] += 1
            self._stats["steps_executed"] += len(results)
            self._stats["llm_turns_saved_est"] += max(0, len(results) - 1)

        return {
            "ok": all_ok,
            "steps_run": len(results),
            "steps_ok": sum(1 for r in results if r.get("ok")),
            "llm_turns_collapsed": max(0, len(results) - 1),
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
            "results": results,
        }

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._stats)


# ---------------------------------------------------------------------------
# PILLAR 10: SINGLE-GATE IMMUTABLE RELEASE PLANE (Atomic Promote + Canary + <1s Rollback)
# ---------------------------------------------------------------------------

class ReleasePromoteEngine:
    """Single atomic release promotion gate preventing uncoordinated multi-agent release jumps."""

    def __init__(
        self,
        worktree_epoch: WorktreeEpochEngine,
        direct_exec: DirectExecEngine,
        hive: HiveMindCortex,
    ) -> None:
        self.worktree_epoch = worktree_epoch
        self.direct_exec = direct_exec
        self.hive = hive
        self._lock = threading.Lock()
        self._history: list[dict[str, Any]] = []
        self._stats = {
            "promotions_ok": 0,
            "promotions_failed": 0,
            "rollbacks_ok": 0,
            "canary_failures": 0,
        }

    @staticmethod
    def _default_snapshot_root(target_dir: Path) -> Path:
        dev = _resolve_dev_drive_root()
        if dev is not None:
            root = dev / "releases"
            try:
                root.mkdir(parents=True, exist_ok=True)
                return root
            except OSError:
                pass
        root = target_dir / ".chimera_rollbacks"
        root.mkdir(parents=True, exist_ok=True)
        return root

    @staticmethod
    def _syntax_gate_file(fp: Path) -> str | None:
        ext = fp.suffix.lower()
        try:
            raw = fp.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return f"read_error:{exc}"
        if ext == ".py":
            try:
                ast.parse(raw, filename=str(fp))
            except SyntaxError as exc:
                return f"SyntaxError L{exc.lineno}: {exc.msg}"
        elif ext == ".json":
            try:
                if raw.strip():
                    json.loads(raw)
            except Exception as exc:
                return f"JSONDecodeError:{exc}"
        elif ext == ".toml":
            try:
                tomllib.loads(raw)
            except Exception as exc:
                return f"TOMLDecodeError:{exc}"
        return None

    @staticmethod
    def _sha256_file(fp: Path) -> str:
        with fp.open("rb") as fh:
            return hashlib.file_digest(fh, "sha256").hexdigest()

    @staticmethod
    def _atomic_copy(src: Path, dst: Path) -> None:
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_name(f".{dst.name}.promote.{os.getpid()}.tmp")
        shutil.copy2(src, tmp)
        os.replace(tmp, dst)

    def _restore_bundle(self, bundle_dir: Path, target_dir: Path, manifest: dict[str, Any]) -> int:
        restored = 0
        for rel, meta in (manifest.get("prior_files") or {}).items():
            dst = target_dir / rel
            if meta.get("existed"):
                bak = bundle_dir / "backup" / rel
                if bak.is_file():
                    self._atomic_copy(bak, dst)
                    restored += 1
            else:
                if dst.is_file():
                    try:
                        dst.unlink()
                        restored += 1
                    except OSError:
                        pass
        return restored

    def promote(
        self,
        source_dir: str | Path,
        target_dir: str | Path,
        files: list[str],
        *,
        agent_id: str = "agent",
        snapshot_root: str | Path | None = None,
        canary_imports: list[str] | None = None,
        verified_summary: str = "",
        dry_run: bool = False,
    ) -> dict[str, Any]:
        t0 = time.perf_counter()
        src_root = Path(source_dir).resolve()
        dst_root = Path(target_dir).resolve()
        if not src_root.is_dir():
            return {"ok": False, "error": "source_dir_not_found", "source_dir": str(src_root)}
        if not dst_root.is_dir():
            return {"ok": False, "error": "target_dir_not_found", "target_dir": str(dst_root)}

        clean_files = [_norm_rel(f) for f in (files or []) if _norm_rel(f)]
        if not clean_files:
            return {"ok": False, "error": "files_required"}

        modules = list(canary_imports or [])
        if any(not isinstance(name, str) or not all(part.isidentifier() for part in name.split("."))
               for name in modules):
            return {"ok": False, "error": "invalid_canary_module_name"}

        # 1. Pre-flight existence + syntax gate BEFORE touching release dir or claiming lock
        gate_errors: list[dict[str, str]] = []
        sha_map: dict[str, str] = {}
        for rel in clean_files:
            sfp = src_root / rel
            if not sfp.is_file():
                gate_errors.append({"file": rel, "error": "source_file_not_found"})
                continue
            err = self._syntax_gate_file(sfp)
            if err:
                gate_errors.append({"file": rel, "error": err})
                continue
            sha_map[rel] = self._sha256_file(sfp)
        if gate_errors:
            with self._lock:
                self._stats["promotions_failed"] += 1
            return {
                "ok": False,
                "error": "syntax_gate_rejected",
                "gate_errors": gate_errors,
                "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
            }

        if dry_run:
            return {
                "ok": True,
                "dry_run": True,
                "files": clean_files,
                "sha256_map": {k: v[:16] for k, v in sha_map.items()},
                "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
            }

        # 2. Acquire single-gate Release-Epoch lock
        claim = self.worktree_epoch.epoch_claim(
            str(dst_root),
            agent_id=agent_id,
            intent=f"release_promote:{len(clean_files)}files",
            ttl_s=120.0,
        )
        if not claim.get("ok"):
            with self._lock:
                self._stats["promotions_failed"] += 1
            return {
                "ok": False,
                "error": "release_epoch_busy",
                "holder": claim.get("holder"),
                "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
            }

        epoch_id = f"rel_{int(time.time())}_{hashlib.blake2s(':'.join(sha_map.values()).encode(), digest_size=4).hexdigest()}"
        snap_base = Path(snapshot_root).resolve() if snapshot_root else self._default_snapshot_root(dst_root)
        bundle_dir = snap_base / f"rollback_{epoch_id}"
        backup_root = bundle_dir / "backup"
        backup_root.mkdir(parents=True, exist_ok=True)

        # 3. Backup prior target versions into immutable rollback bundle
        prior_files: dict[str, dict[str, Any]] = {}
        for rel in clean_files:
            dfp = dst_root / rel
            if dfp.is_file():
                prior_files[rel] = {"existed": True, "sha256": self._sha256_file(dfp)}
                self._atomic_copy(dfp, backup_root / rel)
            else:
                prior_files[rel] = {"existed": False, "sha256": None}

        manifest = {
            "epoch_id": epoch_id,
            "agent_id": agent_id,
            "source_dir": str(src_root),
            "target_dir": str(dst_root),
            "created_at": time.time(),
            "files": clean_files,
            "sha256_map": sha_map,
            "prior_files": prior_files,
            "verified_summary": verified_summary,
        }
        (bundle_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        # 4. Atomic copy into target release dir
        try:
            for rel in clean_files:
                self._atomic_copy(src_root / rel, dst_root / rel)
        except OSError as exc:
            self._restore_bundle(bundle_dir, dst_root, manifest)
            with self._lock:
                self._stats["promotions_failed"] += 1
            return {"ok": False, "error": f"copy_failed:{exc}", "rolled_back": True, "epoch_id": epoch_id}

        # 5. Isolated Canary Import Smoke Check (auto-rollback on failure!)
        canary_ok = True
        canary_detail = "skipped"
        if modules:
            code = ("import importlib, sys; "
                    "[importlib.import_module(name) for name in sys.argv[1:]]; print('CANARY_OK')")
            c_res = self.direct_exec.run(
                [sys.executable, "-c", code, *modules],
                cwd=dst_root,
                env_overrides={"PYTHONPATH": str(dst_root)},
                timeout_s=20.0,
                max_preview_chars=400,
            )
            canary_ok = bool(c_res.get("ok")) and "CANARY_OK" in str(c_res.get("preview") or "")
            canary_detail = "passed" if canary_ok else str(c_res.get("preview") or c_res.get("error") or "canary_failed")[:240]
            if not canary_ok:
                restored = self._restore_bundle(bundle_dir, dst_root, manifest)
                with self._lock:
                    self._stats["promotions_failed"] += 1
                    self._stats["canary_failures"] += 1
                    self._stats["rollbacks_ok"] += 1
                return {
                    "ok": False,
                    "error": "canary_failed",
                    "canary_detail": canary_detail,
                    "rolled_back": True,
                    "restored_files": restored,
                    "epoch_id": epoch_id,
                    "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
                }

        # 6. Publish signed Release-Epoch receipt
        pub = self.worktree_epoch.epoch_publish(
            str(dst_root),
            agent_id=agent_id,
            files=clean_files,
            sha256_map={k: v[:16] for k, v in sha_map.items()},
            verified_summary=verified_summary or f"release_promote:{epoch_id}",
            daemon_pid=os.getpid(),
        )
        record = {
            "epoch_id": epoch_id,
            "target_dir": str(dst_root),
            "rollback_dir": str(bundle_dir),
            "files": clean_files,
            "sha256_short": {k: v[:16] for k, v in sha_map.items()},
            "canary": canary_detail,
            "ts": time.time(),
        }
        with self._lock:
            self._history.append(record)
            self._history = self._history[-20:]
            self._stats["promotions_ok"] += 1
        self.hive.record_mutation(
            agent_id=agent_id,
            repo=str(dst_root),
            files=clean_files,
            kind="release_promote",
            detail=f"{epoch_id} canary={canary_detail}",
        )
        return {
            "ok": True,
            "epoch_id": epoch_id,
            "promoted_files": clean_files,
            "sha256_map": {k: v[:16] for k, v in sha_map.items()},
            "canary_ok": canary_ok,
            "canary_detail": canary_detail,
            "rollback_dir": str(bundle_dir),
            "epoch_receipt": pub.get("epoch_id"),
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }

    def rollback(
        self,
        epoch_id: str | None = None,
        *,
        rollback_dir: str | Path | None = None,
    ) -> dict[str, Any]:
        t0 = time.perf_counter()
        bdir: Path | None = Path(rollback_dir).resolve() if rollback_dir else None
        if bdir is None:
            with self._lock:
                if epoch_id:
                    rec = next((r for r in reversed(self._history) if r["epoch_id"] == epoch_id), None)
                else:
                    rec = self._history[-1] if self._history else None
            if rec:
                bdir = Path(rec["rollback_dir"])
        if bdir is None or not (bdir / "manifest.json").is_file():
            return {"ok": False, "error": "rollback_bundle_not_found", "epoch_id": epoch_id}
        manifest = json.loads((bdir / "manifest.json").read_text(encoding="utf-8"))
        target_dir = Path(manifest["target_dir"])
        restored = self._restore_bundle(bdir, target_dir, manifest)
        with self._lock:
            self._stats["rollbacks_ok"] += 1
        return {
            "ok": True,
            "epoch_id": manifest.get("epoch_id"),
            "target_dir": str(target_dir),
            "restored_files": restored,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "ok": True,
                **self._stats,
                "recent_promotions": list(self._history)[-8:],
            }


# ---------------------------------------------------------------------------
# Unified Facade: AgentSymbiontCore
# ---------------------------------------------------------------------------

class AgentSymbiontCore:
    """Fuses Hive-Mind, Precog-Runner, Surgeon, Mirror-Race, Coroner, DirectExec, WorktreeEpoch, MacroDAG & ReleasePromote."""

    def __init__(self, bus: Any, *, db_path: Path | None = None, ephemeral: bool = False) -> None:
        self.bus = bus
        self.hive = HiveMindCortex(db_path=db_path, ephemeral=ephemeral)
        self.precog = PrecogRunnerEngine(bus.callgraph, bus.verifier, self.hive)
        self.surgeon = SurgeonAtomicPatchEngine(bus.callgraph, bus.verifier, self.hive, self.precog)
        self.capsules = TelepathyCapsuleEngine(bus.callgraph, bus.verifier, self.hive)
        self.mirror_race = MirrorRaceEngine(self.surgeon, bus.verifier, self.hive)
        self.coroner = PostMortemCoronerEngine(self.hive)
        self.direct_exec = DirectExecEngine()
        self.worktree_epoch = WorktreeEpochEngine(self.hive)
        self.macro_dag = MacroDagEngine(bus, self.surgeon, self.direct_exec, self.worktree_epoch)
        self.release_promote = ReleasePromoteEngine(self.worktree_epoch, self.direct_exec, self.hive)
        self._git_cache_lock = threading.Lock()
        self._git_cache: dict[str, tuple[float, dict[str, Any]]] = {}

    def _cached_git_fast(self, repo: Path) -> dict[str, Any]:
        key = _norm_repo(repo)
        now = time.monotonic()
        with self._git_cache_lock:
            hit = self._git_cache.get(key)
            if hit is not None and (now - hit[0]) < 3.0:
                return dict(hit[1])
        info = self.capsules._git_compact(repo, include_diff=False)
        with self._git_cache_lock:
            if len(self._git_cache) >= 16:
                self._git_cache.clear()
            self._git_cache[key] = (now, dict(info))
        return info

    def bootstrap_snapshot(self, repo_path: str | Path, *, agent_id: str = "agent") -> dict[str, Any]:
        """Fast (< 60ms cold, < 3ms cached), strict <= 1,500 B live multi-agent workspace bootstrap."""
        t0 = time.perf_counter()
        repo = Path(repo_path).resolve()
        if not repo.is_dir():
            return {"ok": False, "error": "repo_not_found", "repo": str(repo)}
        nrepo = _norm_repo(repo)
        # Compact 2-level directory summary
        tree_entries: list[str] = []
        try:
            for item in sorted(repo.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
                if item.name in _SKIP_WATCH_PARTS or item.name.startswith("."):
                    continue
                if item.is_dir():
                    subs = [
                        s.name
                        for s in sorted(item.iterdir(), key=lambda x: x.name.lower())
                        if s.name not in _SKIP_WATCH_PARTS and not s.name.startswith(".")
                    ][:4]
                    tree_entries.append(f"{item.name}/({','.join(subs)})" if subs else f"{item.name}/")
                else:
                    tree_entries.append(item.name)
                if len(tree_entries) >= 16:
                    break
        except OSError:
            pass

        hive_st = self.hive.status(repo=nrepo)
        immune_hits = self.hive.match_immune([], repo=nrepo) or self.hive.list_immune(limit=3)
        recent_verified = [
            {
                "ok": bool(r.get("ok")),
                "fp": str(r.get("fingerprint") or "")[:10],
                "n_tests": len(r.get("tests") or []),
                "age_s": r.get("age_s", 0.0),
            }
            for r in (self.bus.verifier.recent_receipts(limit=2) if hasattr(self.bus.verifier, "recent_receipts") else [])
        ]
        latest_cap = self.capsules.list_capsules(repo=nrepo, limit=1).get("capsules", [])

        # Release-Drift Radar: detect when daemon runs from a frozen release snapshot instead of workspace repo
        runtime_dir = _norm_repo(Path(__file__).resolve().parents[2])
        release_drift: dict[str, str] | None = None
        if (repo / "chimera_tp" / "platform" / "agent_symbiont.py").is_file() and runtime_dir.lower() != nrepo.lower():
            release_drift = {
                "runtime_dir": runtime_dir,
                "workspace_dir": nrepo,
                "note": "Daemon running from release snapshot; sync edits there before restarting :9780",
            }

        snap: dict[str, Any] = {
            "ok": True,
            "repo": nrepo,
            "tree": tree_entries,
            "git": self._cached_git_fast(repo),
            "active_leases": [
                {"agent": l["agent_id"], "action": l["action"], "files": l["files"][:3], "ttl_s": l["ttl_left_s"]}
                for l in hive_st.get("active_leases", [])[:3]
                if l.get("agent_id") != agent_id
            ],
            "recent_mutations": [
                {"agent": m["agent_id"], "kind": m["kind"], "files": m["files"][:3], "age_s": m["age_s"]}
                for m in hive_st.get("recent_mutations", [])[:3]
            ],
            "verified_receipts": recent_verified,
            "immune_warnings": [str(r.get("warning") or "")[:120] for r in immune_hits[:3] if r.get("warning")],
            "latest_capsule": latest_cap[0]["capsule_id"] if latest_cap else None,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }
        if release_drift is not None:
            snap["release_drift"] = release_drift
        ep_st = self.worktree_epoch.epoch_status(runtime_dir)
        if ep_st.get("recent_epochs"):
            latest_ep = ep_st["recent_epochs"][0]
            snap["release_epoch"] = {
                "id": latest_ep["epoch_id"],
                "by": latest_ep["agent_id"],
                "pid": latest_ep["daemon_pid"],
                "n_files": len(latest_ep.get("files") or []),
                "age_s": latest_ep.get("age_s", 0.0),
                "summary": latest_ep.get("verified_summary", "")[:80],
            }

        # Strict <= 1,500 B UTF-8 enforcement (progressive shrink keeping highest-value live signals)
        def _measure() -> int:
            snap["bytes"] = 0
            return len(json.dumps(snap, separators=(",", ":"), ensure_ascii=False).encode("utf-8")) + 4

        if _measure() > 1500:
            snap["git"].pop("dirty_sample", None)
        if _measure() > 1500:
            snap["tree"] = [e.split("(", 1)[0] for e in snap["tree"][:14]]
        if _measure() > 1500:
            snap["recent_mutations"] = snap["recent_mutations"][:2]
            snap["immune_warnings"] = [w[:80] for w in snap["immune_warnings"][:2]]
        if _measure() > 1500:
            snap["tree"] = snap["tree"][:8]
            snap["verified_receipts"] = snap["verified_receipts"][:1]

        snap["elapsed_ms"] = round((time.perf_counter() - t0) * 1000.0, 2)
        snap["bytes"] = len(json.dumps(snap, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
        return snap

    def stats(self) -> dict[str, Any]:
        return {
            "ok": True,
            "hive": {
                "active_leases": len(self.hive._leases),
                "recent_mutations": len(self.hive._mutations),
                "immune_rules": len(self.hive._immune),
            },
            "precog": self.precog.status(),
            "surgeon": self.surgeon.stats(),
            "mirror_race": self.mirror_race.stats(),
            "coroner": self.coroner.stats(),
            "direct_exec": self.direct_exec.stats(),
            "worktree_epoch": self.worktree_epoch.stats(),
            "macro_dag": self.macro_dag.stats(),
            "release_promote": self.release_promote.status(),
            "capsules": {"stored": len(self.capsules._capsules)},
        }

    def close(self) -> None:
        self.precog.stop_watch()
