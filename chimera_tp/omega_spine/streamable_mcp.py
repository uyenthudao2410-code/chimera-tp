"""CHIMERA Omega-Spine: MCP 2025-03-26 Streamable HTTP Server (`/mcp` on `:9780`).

Exposes 6 crisp Eager Super-Tools (never 40 bloated tools) over JSON-RPC 2.0
Streamable HTTP with `Mcp-Session-Id` session management, strict CWD / repo
confinement (`resolve_safe_repo`), Iron Cage + Singleflight coalescing, in-RAM
atomic patch syntax gating with rollback, BLAKE2s verification caching, and
Hive/Akashic/Tournament integration.
"""

from __future__ import annotations

import collections
import fnmatch
import hashlib
import inspect
import json
import os
import re
import shutil
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from .. import __version__
from .iron_cage import IronCage, compute_workspace_fingerprint, get_iron_cage
from .precog_tournament import PrecogVerifier, ShadowTournament, syntax_gate_content

MCP_PROTOCOL_VERSION = "2025-03-26"
_RUNTIME_SOURCE_DIR = str(Path(__file__).resolve().parents[1]).replace("\\", "/")

_SKIP_DIRS = frozenset({
    ".git",
    "bin",
    "obj",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "target",
    "dist",
    "build",
    "artifacts",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".next",
    ".chimera_cold_backing",
})

_TEXT_EXTS = frozenset({
    ".cs", ".csproj", ".sln", ".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx",
    ".rs", ".c", ".h", ".cpp", ".hpp", ".go", ".java", ".json", ".toml", ".yaml",
    ".yml", ".xml", ".md", ".txt", ".ini", ".cfg", ".sh", ".ps1", ".sql", ".html",
    ".css", ".razor", ".xaml",
})

_RELEASE_DIR_MARKERS = (
    "/appdata/local/chimera/releases",
    "/.local/share/chimera/releases",
)


# ---------------------------------------------------------------------------
# Lazy Bridges to Sibling `csharp-xray` Modules (with Resilient Fallbacks)
# ---------------------------------------------------------------------------

def _is_chimera_release_dir(path: Path) -> bool:
    low = str(path).replace("\\", "/").lower()
    return any(m in low for m in _RELEASE_DIR_MARKERS)


def _fallback_resolve_safe_repo(repo: str | None, fallback_cwd: str | None = None) -> Path:
    explicit = str(repo or "").strip()
    if explicit:
        p = Path(explicit).expanduser().resolve()
        if not p.exists():
            raise ValueError(f"Repository path does not exist: {p}")
        if p.is_file():
            p = p.parent
        return p

    cand_raw = str(fallback_cwd or "").strip() or os.getcwd()
    cand = Path(cand_raw).expanduser().resolve()
    if _is_chimera_release_dir(cand):
        raise ValueError(
            f"Refusing to resolve workspace to Chimera's own release directory ({cand}). "
            "Pass an explicit `repo` path or register your workspace via SessionStart hook."
        )
    if not cand.exists():
        raise ValueError(f"Fallback workspace path does not exist: {cand}")
    return cand


def _resolve_safe_repo(repo: str | None, fallback_cwd: str | None = None) -> Path:
    try:
        from .csharp_xray import resolve_safe_repo as _ext_resolve
        resolved = _ext_resolve(repo, fallback_cwd=fallback_cwd)
        p = Path(resolved).resolve()
        if not p.exists():
            raise ValueError(f"Repository path does not exist: {p}")
        return p
    except ImportError:
        return _fallback_resolve_safe_repo(repo, fallback_cwd=fallback_cwd)


def _fallback_outline_file(path: Path) -> dict[str, Any]:
    t0 = time.perf_counter()
    raw = path.read_text(encoding="utf-8", errors="replace")
    lines = raw.splitlines()
    ext = path.suffix.lower()
    symbols: list[dict[str, Any]] = []
    if ext == ".py":
        import ast
        try:
            tree = ast.parse(raw)
            for node in ast.walk(tree):
                if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                    kind = "class" if isinstance(node, ast.ClassDef) else "function"
                    symbols.append({
                        "name": node.name,
                        "kind": kind,
                        "container": "",
                        "start_line": int(getattr(node, "lineno", 1)),
                        "end_line": int(getattr(node, "end_lineno", getattr(node, "lineno", 1))),
                        "signature": lines[node.lineno - 1].strip() if 0 < node.lineno <= len(lines) else node.name,
                    })
            symbols.sort(key=lambda s: s["start_line"])
        except SyntaxError:
            pass
    else:
        pat = re.compile(
            r"^\s*(?:public|private|protected|internal|static|async|virtual|override|sealed|abstract|partial|\s)*"
            r"(?P<kind>namespace|class|struct|record|interface|enum|function)\s+(?P<name>[A-Za-z_][A-Za-z0-9_.]*)"
        )
        for idx, ln in enumerate(lines, start=1):
            m = pat.match(ln)
            if m:
                symbols.append({
                    "name": m.group("name"),
                    "kind": m.group("kind"),
                    "container": "",
                    "start_line": idx,
                    "end_line": idx,
                    "signature": ln.strip()[:160],
                })
    return {
        "ok": True,
        "lang": ext.lstrip(".") or "text",
        "path": str(path).replace("\\", "/"),
        "lines": len(lines),
        "symbols": symbols,
        "ms": round((time.perf_counter() - t0) * 1000.0, 2),
    }


def _call_outline_file(path: Path) -> dict[str, Any]:
    try:
        from .csharp_xray import outline_file
        return outline_file(path)
    except ImportError:
        return _fallback_outline_file(path)


def _fallback_surgical_bundle(repo: Path, symbol: str, max_bytes: int = 8192) -> dict[str, Any]:
    t0 = time.perf_counter()
    sym_re = re.compile(rf"\b{re.escape(symbol)}\b")
    defs: list[dict[str, Any]] = []
    refs: list[dict[str, Any]] = []
    tests: list[dict[str, Any]] = []
    for root, dirs, files in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        for fn in files:
            fp = Path(root) / fn
            if fp.suffix.lower() not in _TEXT_EXTS:
                continue
            try:
                raw_b = fp.read_bytes()
            except OSError:
                continue
            if symbol.encode("utf-8") not in raw_b:
                continue
            rel = fp.relative_to(repo).as_posix()
            text = raw_b.decode("utf-8", errors="replace")
            lines = text.splitlines()
            is_test = ("test" in fn.lower()) or ("/tests/" in f"/{rel.lower()}")
            for idx, ln in enumerate(lines, start=1):
                if sym_re.search(ln):
                    snippet = "\n".join(lines[max(0, idx - 1): min(len(lines), idx + 15)])
                    if re.search(rf"\b(class|struct|record|interface|def|function|void|async|public|private|internal|protected)\b.*\b{re.escape(symbol)}\b", ln):
                        defs.append({"file": rel, "line": idx, "snippet": snippet[:1200]})
                    elif is_test:
                        tests.append({"file": rel, "line": idx, "line_text": ln.strip()[:200]})
                    else:
                        refs.append({"file": rel, "line": idx, "line_text": ln.strip()[:200]})
                    if len(defs) >= 5 and len(refs) >= 12:
                        break
    packet = {
        "ok": True,
        "symbol": symbol,
        "repo": str(repo).replace("\\", "/"),
        "definitions": defs[:5],
        "references": refs[:12],
        "tests": tests[:8],
        "fallback": True,
        "ms": round((time.perf_counter() - t0) * 1000.0, 2),
    }
    raw_json = json.dumps(packet, ensure_ascii=False)
    if len(raw_json.encode("utf-8")) > max_bytes:
        packet["references"] = packet["references"][:4]
        packet["tests"] = packet["tests"][:3]
    return packet


def _call_surgical_bundle(repo: Path, symbol: str, *, hops: int = 2, max_bytes: int = 8192) -> dict[str, Any]:
    try:
        from .csharp_xray import surgical_bundle
        sig = inspect.signature(surgical_bundle)
        if "hops" in sig.parameters:
            res = surgical_bundle(repo, symbol, hops=hops, max_bytes=max_bytes)
        else:
            res = surgical_bundle(repo, symbol, max_bytes=max_bytes)
        if isinstance(res, dict) and hops != 2 and "callgraph" not in res:
            try:
                from .csharp_xray import callgraph_slice
                cg = callgraph_slice(repo, symbol, hops=hops)
                if isinstance(cg, dict) and len(json.dumps(res, ensure_ascii=False)) < max_bytes:
                    res = dict(res)
                    res.setdefault("hops", hops)
            except Exception:
                pass
        return res
    except ImportError:
        return _fallback_surgical_bundle(repo, symbol, max_bytes=max_bytes)


def _call_impacted_dotnet_tests(repo: Path, changed_files: list[str]) -> dict[str, Any]:
    try:
        from .csharp_xray import impacted_dotnet_tests
        return impacted_dotnet_tests(repo, changed_files)
    except ImportError:
        test_projs: list[str] = []
        for root, dirs, files in os.walk(repo):
            dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
            for fn in files:
                if fn.endswith(".csproj") and "test" in fn.lower():
                    test_projs.append(str((Path(root) / fn).relative_to(repo).as_posix()))
        filters = [Path(f).stem for f in changed_files if Path(f).suffix.lower() == ".cs"]
        filter_expr = "|".join(f"FullyQualifiedName~{stem}" for stem in filters[:8])
        cmds: list[list[str]] = []
        for tp in test_projs[:4]:
            cmd = ["dotnet", "test", tp, "--no-restore", "--nologo"]
            if filter_expr:
                cmd.extend(["--filter", filter_expr])
            cmds.append(cmd)
        return {"ok": True, "test_projects": test_projs, "commands": cmds, "filter": filter_expr}


class _FallbackAkashicCortex:
    """In-memory fallback used ONLY if sibling `akashic_cortex.py` is absent during parallel build."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._capsules: dict[tuple[str, str, str], dict[str, Any]] = {}
        self._failures: dict[tuple[str, str], list[dict[str, Any]]] = {}
        self._antibodies: list[dict[str, Any]] = []
        self._hits = 0

    def put_symbol_capsule(
        self,
        repo: str,
        rel_path: str,
        file_sha256: str,
        symbol: str,
        summary: str,
        invariants: list[str],
        line_range: str = "",
        author: str = "",
    ) -> dict[str, Any]:
        key = (str(repo).replace("\\", "/"), str(rel_path).replace("\\", "/"), str(symbol))
        cap = {
            "repo": key[0],
            "rel_path": key[1],
            "file_sha256": str(file_sha256),
            "symbol": key[2],
            "summary": str(summary)[:360],
            "invariants": [str(x)[:120] for x in (invariants or [])][:8],
            "line_range": str(line_range or ""),
            "author": str(author or ""),
            "stale": 0,
            "updated_at": round(time.time(), 3),
        }
        with self._lock:
            self._capsules[key] = cap
        return {"ok": True, "capsule": cap}

    def recall_for_files(self, repo: str, file_hashes: dict[str, str], limit: int = 8) -> list[dict[str, Any]]:
        nrepo = str(repo).replace("\\", "/")
        norm_hashes = {str(k).replace("\\", "/"): str(v) for k, v in (file_hashes or {}).items()}
        out: list[dict[str, Any]] = []
        with self._lock:
            for (crepo, rel, _sym), cap in self._capsules.items():
                if crepo != nrepo or rel not in norm_hashes:
                    continue
                if cap["file_sha256"] == norm_hashes[rel]:
                    out.append(dict(cap))
                else:
                    cap["stale"] = 1
        return out[: max(1, int(limit))]

    def record_tool_outcome(
        self,
        conversation_id: str,
        repo: str,
        tool_name: str,
        args: dict[str, Any],
        ok: bool,
        error: str = "",
        diff_hint: str = "",
    ) -> dict[str, Any] | None:
        key = (str(conversation_id), str(repo).replace("\\", "/"))
        with self._lock:
            if not ok and error:
                self._failures.setdefault(key, []).append({
                    "tool": tool_name,
                    "error": str(error)[:240],
                    "args": dict(args or {}),
                    "ts": time.time(),
                })
                self._failures[key] = self._failures[key][-5:]
                return None
            prev = self._failures.get(key) or []
            if ok and prev:
                last_err = prev.pop()
                pat = str((last_err.get("args") or {}).get("path") or (last_err.get("args") or {}).get("file_path") or tool_name)
                ab = {
                    "antibody_id": f"ab_{hashlib.blake2s((last_err['error'] + pat).encode('utf-8'), digest_size=5).hexdigest()}",
                    "error_sig": last_err["error"][:160],
                    "fix_hint": (diff_hint or f"Resolved {tool_name} after prior error")[:200],
                    "file_pattern": str(pat).replace("\\", "/"),
                    "confidence": 0.75,
                    "hit_count": 0,
                    "ttl": 86400,
                }
                self._antibodies.append(ab)
                self._antibodies = self._antibodies[-64:]
                return ab
        return None

    def match_antibodies(self, text_or_path: str, limit: int = 5) -> list[dict[str, Any]]:
        needle = str(text_or_path or "").replace("\\", "/").lower()
        if not needle:
            return []
        hits: list[dict[str, Any]] = []
        with self._lock:
            for ab in reversed(self._antibodies):
                fp = str(ab.get("file_pattern") or "").lower()
                es = str(ab.get("error_sig") or "").lower()
                if (fp and (fp in needle or needle in fp or fnmatch.fnmatch(needle, fp))) or (es and es[:24] in needle):
                    ab["hit_count"] = int(ab.get("hit_count", 0)) + 1
                    self._hits += 1
                    hits.append(dict(ab))
                    if len(hits) >= max(1, int(limit)):
                        break
        return hits

    def status(self) -> dict[str, Any]:
        with self._lock:
            stale = sum(1 for c in self._capsules.values() if c.get("stale"))
            return {
                "ok": True,
                "backend": "fallback_memory",
                "capsules": len(self._capsules),
                "stale_capsules": stale,
                "active_antibodies": len(self._antibodies),
                "total_antibody_hits": self._hits,
            }


def resolve_akashic_cortex(db_path: Path | None = None) -> Any:
    try:
        from .akashic_cortex import AkashicCortex, get_akashic_cortex
        if db_path is not None:
            return AkashicCortex(db_path=db_path)
        return get_akashic_cortex()
    except ImportError:
        return _FallbackAkashicCortex()


# ---------------------------------------------------------------------------
# Shared Session & Hive Lease Registry (Soft Leases, Hard Locks & Mutations)
# ---------------------------------------------------------------------------

class OmegaSessionRegistry:
    """Maps Antigravity `conversationId -> workspace` and tracks per-session touched files."""

    MAX_SESSIONS = 512

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions: collections.OrderedDict[str, dict[str, Any]] = collections.OrderedDict()
        self._last_workspace: str = ""

    def register(self, conversation_id: str, workspace: str | Path) -> dict[str, Any]:
        cid = str(conversation_id or "").strip() or "default"
        ws = str(Path(workspace).expanduser()).replace("\\", "/")
        now = time.time()
        with self._lock:
            cur = self._sessions.get(cid) or {}
            entry = {
                "conversation_id": cid,
                "workspace": ws,
                "registered_at": cur.get("registered_at", round(now, 3)),
                "updated_at": round(now, 3),
                "touched_files": list(cur.get("touched_files") or []),
                "last_mutation_seq": int(cur.get("last_mutation_seq", 0)),
                "seen_capsules": set(cur.get("seen_capsules") or set()),
                "pending_advisories": list(cur.get("pending_advisories") or []),
                "invocations": int(cur.get("invocations", 0)),
            }
            self._sessions[cid] = entry
            self._sessions.move_to_end(cid)
            if ws:
                self._last_workspace = ws
            while len(self._sessions) > self.MAX_SESSIONS:
                self._sessions.popitem(last=False)
            return {k: v for k, v in entry.items() if k != "seen_capsules"}

    def get_workspace(self, conversation_id: str | None = None) -> str | None:
        with self._lock:
            if conversation_id:
                ent = self._sessions.get(str(conversation_id))
                if ent and ent.get("workspace"):
                    return str(ent["workspace"])
            return self._last_workspace or None

    def record_touched_file(self, conversation_id: str, rel_path: str) -> None:
        cid = str(conversation_id or "default")
        rel = str(rel_path or "").replace("\\", "/").lstrip("./")
        if not rel:
            return
        with self._lock:
            ent = self._sessions.setdefault(cid, {
                "conversation_id": cid,
                "workspace": self._last_workspace,
                "registered_at": round(time.time(), 3),
                "updated_at": round(time.time(), 3),
                "touched_files": [],
                "last_mutation_seq": 0,
                "seen_capsules": set(),
                "pending_advisories": [],
                "invocations": 0,
            })
            files = ent["touched_files"]
            if rel in files:
                files.remove(rel)
            files.append(rel)
            if len(files) > 32:
                del files[:-32]
            ent["updated_at"] = round(time.time(), 3)

    def get_touched_files(self, conversation_id: str) -> list[str]:
        with self._lock:
            ent = self._sessions.get(str(conversation_id or "default"))
            return list(ent.get("touched_files") or []) if ent else []

    def push_advisory(self, conversation_id: str, kind: str, message: str) -> None:
        cid = str(conversation_id or "default")
        with self._lock:
            ent = self._sessions.setdefault(cid, {
                "conversation_id": cid,
                "workspace": self._last_workspace,
                "registered_at": round(time.time(), 3),
                "updated_at": round(time.time(), 3),
                "touched_files": [],
                "last_mutation_seq": 0,
                "seen_capsules": set(),
                "pending_advisories": [],
                "invocations": 0,
            })
            adv = ent["pending_advisories"]
            item = {"kind": kind, "message": message[:320]}
            if item not in adv:
                adv.append(item)
            if len(adv) > 16:
                del adv[:-16]

    def drain_advisories(self, conversation_id: str) -> list[dict[str, str]]:
        cid = str(conversation_id or "default")
        with self._lock:
            ent = self._sessions.get(cid)
            if not ent:
                return []
            items = list(ent.get("pending_advisories") or [])
            ent["pending_advisories"] = []
            return items

    def get_and_advance_mutation_seq(self, conversation_id: str, new_seq: int) -> int:
        cid = str(conversation_id or "default")
        with self._lock:
            ent = self._sessions.setdefault(cid, {
                "conversation_id": cid,
                "workspace": self._last_workspace,
                "registered_at": round(time.time(), 3),
                "updated_at": round(time.time(), 3),
                "touched_files": [],
                "last_mutation_seq": 0,
                "seen_capsules": set(),
                "pending_advisories": [],
                "invocations": 0,
            })
            prev = int(ent.get("last_mutation_seq", 0))
            if new_seq > prev:
                ent["last_mutation_seq"] = new_seq
            return prev

    def filter_unseen_capsules(self, conversation_id: str, capsules: list[dict[str, Any]]) -> list[dict[str, Any]]:
        cid = str(conversation_id or "default")
        out: list[dict[str, Any]] = []
        with self._lock:
            ent = self._sessions.setdefault(cid, {
                "conversation_id": cid,
                "workspace": self._last_workspace,
                "registered_at": round(time.time(), 3),
                "updated_at": round(time.time(), 3),
                "touched_files": [],
                "last_mutation_seq": 0,
                "seen_capsules": set(),
                "pending_advisories": [],
                "invocations": 0,
            })
            seen: set[str] = ent["seen_capsules"]
            for c in capsules:
                sig = f"{c.get('rel_path', '')}|{c.get('symbol', '')}|{c.get('file_sha256', '')}"
                if sig not in seen:
                    seen.add(sig)
                    out.append(c)
        return out

    def bump_invocation(self, conversation_id: str, info: dict[str, Any] | None = None) -> int:
        cid = str(conversation_id or "default")
        with self._lock:
            ent = self._sessions.setdefault(cid, {
                "conversation_id": cid,
                "workspace": self._last_workspace,
                "registered_at": round(time.time(), 3),
                "updated_at": round(time.time(), 3),
                "touched_files": [],
                "last_mutation_seq": 0,
                "seen_capsules": set(),
                "pending_advisories": [],
                "invocations": 0,
            })
            ent["invocations"] = int(ent.get("invocations", 0)) + 1
            ent["updated_at"] = round(time.time(), 3)
            if info:
                ent["last_invocation_info"] = dict(info)
            return int(ent["invocations"])

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "active_sessions": len(self._sessions),
                "last_workspace": self._last_workspace,
            }


class OmegaHiveStore:
    """In-RAM Hive soft-lease, hard-lock, and Swarm mutation ledger."""

    MAX_LEASES = 128
    MAX_MUTATIONS = 128

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._leases: dict[str, dict[str, Any]] = {}
        self._mutations: collections.deque[dict[str, Any]] = collections.deque(maxlen=self.MAX_MUTATIONS)
        self._mut_seq = 0

    @staticmethod
    def _nrepo(repo: str | Path) -> str:
        try:
            return str(Path(repo).resolve()).replace("\\", "/")
        except OSError:
            return str(repo).replace("\\", "/")

    @staticmethod
    def _nrel(path: str) -> str:
        return str(path or "").strip().replace("\\", "/").lstrip("./")

    def _prune_locked(self, now: float) -> None:
        expired = [k for k, v in self._leases.items() if float(v.get("expires_at", 0.0)) <= now]
        for k in expired:
            self._leases.pop(k, None)

    def acquire_lease(
        self,
        *,
        agent_id: str,
        repo: str | Path,
        files: list[str] | None = None,
        intent: str = "",
        ttl_s: float = 120.0,
        hard_lock: bool = False,
    ) -> dict[str, Any]:
        aid = str(agent_id or "agent").strip()[:64]
        nrepo = self._nrepo(repo)
        nfiles = sorted({self._nrel(f) for f in (files or []) if self._nrel(f)})[:64]
        now = time.time()
        ttl = max(5.0, min(900.0, float(ttl_s or 120.0)))
        key = f"{aid}::{nrepo}"

        with self._lock:
            self._prune_locked(now)
            conflicts = self._find_conflicts_locked(aid, nrepo, nfiles, now)
            hard_conflicts = [c for c in conflicts if c.get("hard_lock")]
            if hard_conflicts:
                return {
                    "ok": False,
                    "blocked_by_hard_lock": True,
                    "conflicts": conflicts,
                    "hard_conflicts": hard_conflicts,
                }
            # Merge with existing leased files for the same agent/repo so sequential edits stay leased
            existing = self._leases.get(key)
            merged_files = sorted(set((existing or {}).get("files") or []) | set(nfiles))[:64]
            lease = {
                "lease_id": key,
                "agent_id": aid,
                "repo": nrepo,
                "files": merged_files,
                "intent": str(intent or (existing or {}).get("intent") or "")[:180],
                "hard_lock": bool(hard_lock),
                "updated_at": round(now, 3),
                "expires_at": round(now + ttl, 3),
            }
            if len(self._leases) >= self.MAX_LEASES and key not in self._leases:
                oldest = min(self._leases.items(), key=lambda kv: kv[1].get("updated_at", 0.0))[0]
                self._leases.pop(oldest, None)
            self._leases[key] = lease

        return {
            "ok": True,
            "blocked_by_hard_lock": False,
            "lease": lease,
            "conflicts": conflicts,
            "hard_conflicts": [],
        }

    def release_lease(self, *, agent_id: str, repo: str | Path | None = None) -> dict[str, Any]:
        aid = str(agent_id or "").strip()
        nrepo = self._nrepo(repo) if repo else None
        removed = 0
        with self._lock:
            keys = [
                k for k, v in self._leases.items()
                if v.get("agent_id") == aid and (nrepo is None or v.get("repo") == nrepo)
            ]
            for k in keys:
                self._leases.pop(k, None)
                removed += 1
        return {"ok": True, "removed": removed}

    def check_conflicts(self, *, agent_id: str, repo: str | Path, files: list[str]) -> list[dict[str, Any]]:
        nrepo = self._nrepo(repo)
        nfiles = sorted({self._nrel(f) for f in (files or []) if self._nrel(f)})
        now = time.time()
        with self._lock:
            self._prune_locked(now)
            return self._find_conflicts_locked(str(agent_id or ""), nrepo, nfiles, now)

    def _find_conflicts_locked(
        self,
        agent_id: str,
        nrepo: str,
        nfiles: list[str],
        now: float,
    ) -> list[dict[str, Any]]:
        fset = set(nfiles)
        out: list[dict[str, Any]] = []
        for lease in self._leases.values():
            if lease.get("agent_id") == agent_id or lease.get("repo") != nrepo:
                continue
            other = set(lease.get("files") or [])
            overlap = sorted(fset & other) if (fset and other) else []
            if overlap or (not other and fset):
                out.append({
                    "type": "hard_lock" if lease.get("hard_lock") else "soft_lease",
                    "hard_lock": bool(lease.get("hard_lock")),
                    "agent_id": lease.get("agent_id"),
                    "intent": lease.get("intent", ""),
                    "overlap": overlap,
                    "age_s": round(max(0.0, now - float(lease.get("updated_at", now))), 1),
                })
        return out

    def record_mutation(
        self,
        *,
        agent_id: str,
        repo: str | Path,
        files: list[str],
        kind: str = "edit",
        detail: str = "",
    ) -> dict[str, Any]:
        with self._lock:
            self._mut_seq += 1
            entry = {
                "seq": self._mut_seq,
                "agent_id": str(agent_id or "agent")[:64],
                "repo": self._nrepo(repo),
                "files": sorted({self._nrel(f) for f in files if self._nrel(f)})[:32],
                "kind": str(kind or "edit")[:24],
                "detail": str(detail or "")[:160],
                "ts": round(time.time(), 3),
            }
            self._mutations.append(entry)
            return entry

    def sibling_mutations_since(
        self,
        *,
        agent_id: str,
        repo: str | Path,
        since_seq: int,
    ) -> tuple[list[dict[str, Any]], int]:
        nrepo = self._nrepo(repo)
        with self._lock:
            head_seq = self._mut_seq
            out = [
                dict(m) for m in self._mutations
                if int(m["seq"]) > int(since_seq)
                and m["repo"] == nrepo
                and m["agent_id"] != str(agent_id or "")
            ]
        return out[-10:], head_seq

    def list_leases(self, repo: str | Path | None = None) -> list[dict[str, Any]]:
        now = time.time()
        nrepo = self._nrepo(repo) if repo else None
        with self._lock:
            self._prune_locked(now)
            return [
                dict(v, ttl_left_s=round(max(0.0, float(v["expires_at"]) - now), 1))
                for v in self._leases.values()
                if nrepo is None or v.get("repo") == nrepo
            ]

    def status(self, repo: str | Path | None = None) -> dict[str, Any]:
        leases = self.list_leases(repo=repo)
        nrepo = self._nrepo(repo) if repo else None
        with self._lock:
            muts = [
                dict(m) for m in reversed(self._mutations)
                if nrepo is None or m.get("repo") == nrepo
            ][:12]
        return {
            "ok": True,
            "active_leases": leases,
            "lease_count": len(leases),
            "recent_mutations": muts,
        }


# ---------------------------------------------------------------------------
# 6 Crisp Eager Super-Tool Schemas
# ---------------------------------------------------------------------------

EAGER_SUPER_TOOLS: list[dict[str, Any]] = [
    {
        "name": "chimera_bootstrap",
        "description": (
            "Orient in one call: returns repo tree, git branch/dirty state, active Hive leases, "
            "fresh Akashic symbol capsules, matching Immune Antibodies, and runtime_source_dir."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo": {"type": "string", "description": "Explicit repository root path (auto-resolved from session if omitted)."},
                "conversation_id": {"type": "string", "description": "Optional Antigravity conversationId for workspace lookup."},
                "agent_id": {"type": "string"},
                "max_entries": {"type": "integer", "default": 40},
            },
            "required": [],
        },
    },
    {
        "name": "chimera_xray_batch",
        "description": (
            "Execute up to 40 zero-spawn read-only probes (outline, list_files, regex_search, file_slice, "
            "git_status, surgical_bundle, file_hash, win_probe, watch_until, remote_xray, raw_recall, doc_page) "
            "in one singleflight-coalesced call strictly confined to `repo`."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo": {"type": "string", "description": "Repository root path (required unless session workspace registered)."},
                "ops": {
                    "type": "array",
                    "description": "List of probe objects: {op: outline|list_files|regex_search|file_slice|git_status|surgical_bundle|file_hash|win_probe|watch_until|remote_xray|raw_recall|doc_page, ...}.",
                    "items": {"type": "object"},
                },
                "conversation_id": {"type": "string"},
                "bypass_cache": {"type": "boolean", "default": False},
            },
            "required": ["ops"],
        },
    },
    {
        "name": "chimera_surgical_bundle",
        "description": (
            "Extract one byte-budgeted C#/Python/JS surgical packet for `symbol`: target definition, "
            "2-hop callers/callees, related types, matching tests, and fresh Akashic capsules."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo": {"type": "string", "description": "Repository root path."},
                "symbol": {"type": "string", "description": "Class, method, struct, or function name."},
                "hops": {"type": "integer", "default": 2},
                "max_bytes": {"type": "integer", "default": 8192},
                "conversation_id": {"type": "string"},
            },
            "required": ["symbol"],
        },
    },
    {
        "name": "chimera_atomic_patch",
        "description": (
            "Transactional multi-file edit with in-RAM C#/Python/JSON/TOML/JS syntax gate BEFORE "
            "disk write and automatic byte-exact rollback on failure."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo": {"type": "string", "description": "Repository root path."},
                "edits": {
                    "type": "array",
                    "description": "Edits: [{path, content} | {path, old, new, replace_all?} | {path, delete: true}].",
                    "items": {"type": "object"},
                },
                "agent_id": {"type": "string"},
                "conversation_id": {"type": "string"},
                "dry_run": {"type": "boolean", "default": False},
            },
            "required": ["edits"],
        },
    },
    {
        "name": "chimera_commit_verify",
        "description": (
            "Run BLAKE2s-cached impacted verification (syntax gate + targeted dotnet test / pytest / "
            "node --test or custom `cmd`) inside the Kernel Iron Cage."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo": {"type": "string", "description": "Repository root path."},
                "changed_files": {"type": "array", "items": {"type": "string"}},
                "cmd": {"type": "string", "description": "Optional explicit verification command."},
                "timeout_s": {"type": "number", "default": 60},
                "force": {"type": "boolean", "default": False},
                "conversation_id": {"type": "string"},
            },
            "required": [],
        },
    },
    {
        "name": "chimera_hive_cortex",
        "description": (
            "Swarm coordination & cognitive memory hub: manage Hive leases, store/recall Akashic "
            "symbol capsules, query Immune Antibodies, run Shadow Tournaments, or inspect Iron Cage."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "lease",
                        "release",
                        "status",
                        "put_capsule",
                        "recall_capsules",
                        "antibodies",
                        "tournament_run",
                        "cage_status",
                        "release_status",
                        "release_stage",
                        "release_replicate",
                        "blocker_alerts",
                        "context_hygiene",
                        "raw_recall",
                        "raw_ingest",
                        "raw_slice",
                        "warm_repl",
                        "entropy_audit",
                        "raw_arena",
                        "swarm_watchdog",
                        "shell_guard_status",
                    ],
                },
                "repo": {"type": "string"},
                "agent_id": {"type": "string"},
                "files": {"type": "array", "items": {"type": "string"}},
                "intent": {"type": "string"},
                "ttl_s": {"type": "number"},
                "hard_lock": {"type": "boolean"},
                "rel_path": {"type": "string"},
                "file_sha256": {"type": "string"},
                "symbol": {"type": "string"},
                "summary": {"type": "string"},
                "invariants": {"type": "array", "items": {"type": "string"}},
                "line_range": {"type": "string"},
                "file_hashes": {"type": "object"},
                "query": {"type": "string"},
                "limit": {"type": "integer"},
                "candidates": {"type": "array", "items": {"type": "object"}},
                "oracle_cmd": {"type": "string"},
                "tournament_id": {"type": "string"},
                "promote": {"type": "boolean"},
                "timeout_s": {"type": "number"},
                "sweep": {"type": "boolean"},
            },
            "required": ["action"],
        },
    },
]


# ---------------------------------------------------------------------------
# Fast Repo Utilities (Confinement, Git Info, File Tree, Search)
# ---------------------------------------------------------------------------

def _confine_path(repo_root: Path, raw_path: str) -> tuple[Path, str]:
    """Resolve `raw_path` strictly inside `repo_root`; reject traversal escapes."""
    root_res = repo_root.resolve()
    p = Path(str(raw_path or "."))
    cand = p.resolve() if p.is_absolute() else (root_res / p).resolve()
    if cand != root_res and root_res not in cand.parents:
        raise ValueError(f"Path '{raw_path}' escapes repository root '{root_res}'")
    rel = "." if cand == root_res else cand.relative_to(root_res).as_posix()
    return cand, rel


def _fast_git_summary(repo_root: Path, iron_cage: IronCage, *, include_status: bool = True) -> dict[str, Any]:
    git_entry = repo_root / ".git"
    if not git_entry.exists():
        return {"is_git": False, "branch": "", "head_sha": "", "dirty": False, "dirty_count": 0, "modified": []}

    git_dir = git_entry
    if git_entry.is_file():
        try:
            raw = git_entry.read_text(encoding="utf-8", errors="ignore").strip()
            if raw.lower().startswith("gitdir:"):
                gd = Path(raw.split(":", 1)[1].strip())
                git_dir = gd if gd.is_absolute() else (repo_root / gd)
        except OSError:
            pass

    branch = ""
    head_sha = ""
    try:
        head_txt = (git_dir / "HEAD").read_text(encoding="utf-8", errors="ignore").strip()
        if head_txt.startswith("ref:"):
            ref = head_txt.split(":", 1)[1].strip()
            branch = ref.replace("refs/heads/", "")
            ref_file = git_dir / ref
            if ref_file.is_file():
                head_sha = ref_file.read_text(encoding="utf-8", errors="ignore").strip()[:12]
        else:
            branch = "DETACHED"
            head_sha = head_txt[:12]
    except OSError:
        pass

    modified: list[str] = []
    if include_status and shutil.which("git"):
        res = iron_cage.spawn_caged(
            ["git", "--no-optional-locks", "status", "--porcelain=v1", "-uall"],
            cwd=repo_root,
            timeout_s=4.0,
            use_singleflight=True,
        )
        if res.get("ok"):
            for ln in (res.get("stdout") or "").splitlines():
                if len(ln) >= 4:
                    modified.append(ln[3:].strip().replace("\\", "/"))
    return {
        "is_git": True,
        "branch": branch,
        "head_sha": head_sha,
        "dirty": len(modified) > 0,
        "dirty_count": len(modified),
        "modified": modified[:24],
    }


def _repo_tree_preview(repo_root: Path, max_entries: int = 40) -> list[str]:
    entries: list[str] = []
    cap = max(5, min(200, int(max_entries or 40)))
    try:
        top_items = sorted(repo_root.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except OSError:
        return entries
    for item in top_items:
        if item.name in _SKIP_DIRS:
            continue
        rel = item.name + ("/" if item.is_dir() else "")
        entries.append(rel)
        if len(entries) >= cap:
            break
        if item.is_dir():
            try:
                sub_items = sorted(item.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
            except OSError:
                sub_items = []
            for sub in sub_items[:6]:
                if sub.name in _SKIP_DIRS:
                    continue
                entries.append(f"{item.name}/{sub.name}" + ("/" if sub.is_dir() else ""))
                if len(entries) >= cap:
                    break
        if len(entries) >= cap:
            break
    return entries


def _sha256_file(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


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
# Streamable HTTP MCP Server
# ---------------------------------------------------------------------------

class StreamableMcpServer:
    """MCP 2025-03-26 Streamable HTTP protocol handler + 6 Eager Super-Tools."""

    def __init__(
        self,
        *,
        iron_cage: IronCage | None = None,
        precog: PrecogVerifier | None = None,
        tournament: ShadowTournament | None = None,
        cortex: Any = None,
        hive: OmegaHiveStore | None = None,
        sessions: OmegaSessionRegistry | None = None,
    ) -> None:
        self.iron_cage = iron_cage or get_iron_cage()
        self.precog = precog or PrecogVerifier(iron_cage=self.iron_cage)
        self.tournament = tournament or ShadowTournament(iron_cage=self.iron_cage)
        self._cortex = cortex
        self.hive = hive or OmegaHiveStore()
        self.sessions = sessions or OmegaSessionRegistry()
        self._lock = threading.Lock()
        self._mcp_sessions: collections.OrderedDict[str, dict[str, Any]] = collections.OrderedDict()
        self._verify_cache: collections.OrderedDict[str, dict[str, Any]] = collections.OrderedDict()
        self._stats = {
            "requests": 0,
            "tool_calls": 0,
            "tool_errors": 0,
            "verify_cache_hits": 0,
        }

    @property
    def cortex(self) -> Any:
        if self._cortex is None:
            self._cortex = resolve_akashic_cortex()
        return self._cortex

    def _resolve_repo_for_call(self, args: dict[str, Any]) -> Path:
        raw_repo = str(args.get("repo") or "").strip() or None
        cid = str(args.get("conversation_id") or "").strip() or None
        fallback = self.sessions.get_workspace(cid) if raw_repo is None else None
        return _resolve_safe_repo(raw_repo, fallback_cwd=fallback)

    # --- HTTP Transport Entry Points ---

    def handle_get(self, headers: Any = None) -> tuple[int, dict[str, Any], dict[str, str]]:
        """Per MCP 2025-03-26 Streamable HTTP spec, return 405 if GET SSE stream is not offered."""
        return (
            405,
            {
                "ok": False,
                "error": "Method Not Allowed",
                "detail": "Streamable HTTP MCP server serves JSON-RPC 2.0 via POST /mcp (protocol 2025-03-26).",
            },
            {"Allow": "POST, DELETE, OPTIONS"},
        )

    def handle_delete(self, headers: Any = None) -> tuple[int, dict[str, Any], dict[str, str]]:
        sid = self._header(headers, "Mcp-Session-Id")
        closed = False
        if sid:
            with self._lock:
                closed = self._mcp_sessions.pop(sid, None) is not None
        return 200, {"ok": True, "session_id": sid, "closed": closed}, {}

    def handle_post(
        self,
        raw_body: bytes,
        headers: Any = None,
    ) -> tuple[int, Any, dict[str, str]]:
        """Handle POST /mcp JSON-RPC 2.0 request (single or batch)."""
        with self._lock:
            self._stats["requests"] += 1

        try:
            payload = json.loads((raw_body or b"").decode("utf-8"))
        except Exception as exc:
            return (
                400,
                {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": f"Parse error: {exc}"}},
                {},
            )

        incoming_sid = self._header(headers, "Mcp-Session-Id")
        extra_headers: dict[str, str] = {}

        if isinstance(payload, list):
            if not payload:
                return (
                    400,
                    {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Empty batch"}},
                    {},
                )
            responses: list[dict[str, Any]] = []
            for item in payload:
                resp, sid_out = self._dispatch_single(item, incoming_sid)
                if sid_out:
                    incoming_sid = sid_out
                    extra_headers["Mcp-Session-Id"] = sid_out
                if resp is not None:
                    responses.append(resp)
            if not responses:
                return 202, None, extra_headers
            return 200, responses, extra_headers

        if not isinstance(payload, dict):
            return (
                400,
                {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Request"}},
                {},
            )

        resp, sid_out = self._dispatch_single(payload, incoming_sid)
        if sid_out:
            extra_headers["Mcp-Session-Id"] = sid_out
        if resp is None:
            return 202, None, extra_headers
        return 200, resp, extra_headers

    @staticmethod
    def _header(headers: Any, name: str) -> str:
        if headers is None:
            return ""
        if hasattr(headers, "get"):
            val = headers.get(name) or headers.get(name.lower()) or ""
            return str(val).strip()
        return ""

    def _dispatch_single(self, req: Any, session_id: str) -> tuple[dict[str, Any] | None, str]:
        if not isinstance(req, dict):
            return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Request"}}, session_id

        req_id = req.get("id")
        is_notification = ("id" not in req)
        method = str(req.get("method") or "")
        params = req.get("params") if isinstance(req.get("params"), dict) else {}

        if method == "initialize":
            sid = session_id or f"mcp_{uuid.uuid4().hex}"
            with self._lock:
                self._mcp_sessions[sid] = {
                    "session_id": sid,
                    "created_at": round(time.time(), 3),
                    "client_info": params.get("clientInfo") or {},
                    "protocol_version": str(params.get("protocolVersion") or MCP_PROTOCOL_VERSION),
                    "initialized": False,
                }
                self._mcp_sessions.move_to_end(sid)
                while len(self._mcp_sessions) > 256:
                    self._mcp_sessions.popitem(last=False)
            result = {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "chimera-omega-spine", "version": __version__},
                "instructions": (
                    "Pass explicit `repo` path on tool calls. Use `chimera_bootstrap` once per repo, "
                    "`chimera_surgical_bundle` for C#/Py/JS symbols, `chimera_xray_batch` for batched reads, "
                    "`chimera_atomic_patch` for syntax-gated edits, `chimera_commit_verify` for cached tests."
                ),
            }
            return (None if is_notification else {"jsonrpc": "2.0", "id": req_id, "result": result}), sid

        if method == "notifications/initialized":
            if session_id:
                with self._lock:
                    if session_id in self._mcp_sessions:
                        self._mcp_sessions[session_id]["initialized"] = True
            return (None if is_notification else {"jsonrpc": "2.0", "id": req_id, "result": {}}), session_id

        if method == "ping":
            return (None if is_notification else {"jsonrpc": "2.0", "id": req_id, "result": {}}), session_id

        if method == "tools/list":
            return (
                None
                if is_notification
                else {"jsonrpc": "2.0", "id": req_id, "result": {"tools": EAGER_SUPER_TOOLS}}
            ), session_id

        if method == "tools/call":
            tool_name = str(params.get("name") or "")
            tool_args = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
            valid_names = {t["name"] for t in EAGER_SUPER_TOOLS}
            if tool_name not in valid_names:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32602, "message": f"Unknown tool: {tool_name}"},
                }, session_id

            with self._lock:
                self._stats["tool_calls"] += 1
            try:
                out = self.call_tool(tool_name, tool_args)
                is_err = not bool(out.get("ok", True))
                if is_err:
                    with self._lock:
                        self._stats["tool_errors"] += 1
                res_obj = {
                    "content": [{"type": "text", "text": json.dumps(out, ensure_ascii=False)}],
                    "structuredContent": out,
                    "isError": is_err,
                }
            except Exception as exc:
                with self._lock:
                    self._stats["tool_errors"] += 1
                err_payload = {"ok": False, "tool": tool_name, "error": str(exc)}
                res_obj = {
                    "content": [{"type": "text", "text": json.dumps(err_payload, ensure_ascii=False)}],
                    "structuredContent": err_payload,
                    "isError": True,
                }
            return (None if is_notification else {"jsonrpc": "2.0", "id": req_id, "result": res_obj}), session_id

        if is_notification:
            return None, session_id

        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }, session_id

    # --- Tool Implementations ---

    def call_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        dispatch: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
            "chimera_bootstrap": self._tool_bootstrap,
            "chimera_xray_batch": self._tool_xray_batch,
            "chimera_surgical_bundle": self._tool_surgical_bundle,
            "chimera_atomic_patch": self._tool_atomic_patch,
            "chimera_commit_verify": self._tool_commit_verify,
            "chimera_hive_cortex": self._tool_hive_cortex,
        }
        fn = dispatch.get(name)
        if fn is None:
            raise ValueError(f"Unknown tool: {name}")
        return fn(dict(args or {}))

    def _tool_bootstrap(self, args: dict[str, Any]) -> dict[str, Any]:
        t0 = time.perf_counter()
        repo = self._resolve_repo_for_call(args)
        nrepo = str(repo).replace("\\", "/")
        cid = str(args.get("conversation_id") or "").strip()
        if cid:
            self.sessions.register(cid, repo)

        git_info = _fast_git_summary(repo, self.iron_cage, include_status=True)
        tree = _repo_tree_preview(repo, max_entries=int(args.get("max_entries") or 40))
        leases = self.hive.list_leases(repo=repo)

        # Hash modified + touched files for instant fresh capsule recall
        candidate_files = list(git_info.get("modified") or [])[:8]
        if cid:
            for tf in self.sessions.get_touched_files(cid)[:8]:
                if tf not in candidate_files:
                    candidate_files.append(tf)
        file_hashes: dict[str, str] = {}
        for rel in candidate_files[:12]:
            fp = repo / rel
            if fp.is_file():
                sha = _sha256_file(fp)
                if sha:
                    file_hashes[rel] = sha

        capsules = self.cortex.recall_for_files(nrepo, file_hashes, limit=6) if file_hashes else []
        antibodies = self.cortex.match_antibodies(nrepo, limit=5)
        blocking = self.precog.get_blocking_errors(cid, repo) if cid else []

        primer: dict[str, Any] = {}
        try:
            from ..platform.mnemosyne import get_mnemosyne_core
            mn = get_mnemosyne_core()
            pr = mn.primer.prime(repo, cid=cid or "mcp-boot", include_raw_recall=True)
            primer = {
                "env": pr.get("env"),
                "docs": pr.get("docs") or [],
                "swarm_bulletin": pr.get("swarm_bulletin") or [],
                "raw_recall": pr.get("raw_recall") or [],
                "active_workers": pr.get("active_workers") or 1,
                "pacing_warning": pr.get("pacing_warning") or "",
            }
        except Exception:
            primer = {}

        return {
            "ok": True,
            "repo": nrepo,
            "runtime_source_dir": _RUNTIME_SOURCE_DIR,
            "repo_tree": tree,
            "git": git_info,
            "hive_leases": leases,
            "akashic_capsules": capsules,
            "immune_antibodies": antibodies,
            "precog_blocking": blocking,
            "primer": primer,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }

    def _tool_xray_batch(self, args: dict[str, Any]) -> dict[str, Any]:
        t0 = time.perf_counter()
        repo = self._resolve_repo_for_call(args)
        ops = args.get("ops")
        if not isinstance(ops, list) or not ops:
            raise ValueError("`ops` must be a non-empty array of probe objects")
        if len(ops) > 40:
            raise ValueError("`ops` exceeds maximum batch size of 40")

        bypass = bool(args.get("bypass_cache", False))
        # Collect explicitly referenced files so workspace fingerprint invalidates immediately on edits
        ref_files = [
            str(op.get("path"))
            for op in ops
            if isinstance(op, dict) and op.get("path")
        ]
        fp = compute_workspace_fingerprint(repo, extra_files=ref_files)
        canon = json.dumps(ops, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        sf_key = self.iron_cage.singleflight.make_key(repo, f"xray_batch:{canon}", fp)

        def _exec_batch() -> list[dict[str, Any]]:
            out: list[dict[str, Any]] = []
            for idx, op_obj in enumerate(ops):
                if not isinstance(op_obj, dict):
                    out.append({"index": idx, "ok": False, "error": "invalid_op_object"})
                    continue
                op_name = str(op_obj.get("op") or "").strip().lower()
                try:
                    out.append(self._run_xray_op(repo, op_name, op_obj, idx))
                except Exception as exc:
                    out.append({"index": idx, "op": op_name, "ok": False, "error": str(exc)})
            return out

        results, mode = self.iron_cage.singleflight.run_or_join(sf_key, _exec_batch, bypass_cache=bypass)
        return {
            "ok": True,
            "repo": str(repo).replace("\\", "/"),
            "count": len(results),
            "results": results,
            "singleflight_hit": mode != "executed",
            "singleflight_mode": mode,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }

    def _run_xray_op(self, repo: Path, op_name: str, spec: dict[str, Any], idx: int) -> dict[str, Any]:
        if op_name == "outline":
            target, rel = _confine_path(repo, str(spec.get("path") or ""))
            if not target.is_file():
                raise FileNotFoundError(f"File not found: {rel}")
            res = _call_outline_file(target)
            return {"index": idx, "op": "outline", "rel_path": rel, **res}

        if op_name == "list_files":
            base, rel_base = _confine_path(repo, str(spec.get("path") or "."))
            pattern = str(spec.get("glob") or "*")
            max_files = max(1, min(500, int(spec.get("max_files") or 100)))
            found: list[str] = []
            truncated = False
            if base.is_dir():
                for root, dirs, files in os.walk(base):
                    dirs[:] = sorted(d for d in dirs if d not in _SKIP_DIRS)
                    for fn in sorted(files):
                        fp = Path(root) / fn
                        rel = fp.relative_to(repo).as_posix()
                        if fnmatch.fnmatch(fn, pattern) or fnmatch.fnmatch(rel, pattern):
                            found.append(rel)
                            if len(found) >= max_files:
                                truncated = True
                                break
                    if truncated:
                        break
            return {
                "index": idx,
                "op": "list_files",
                "ok": True,
                "path": rel_base,
                "count": len(found),
                "truncated": truncated,
                "files": found,
            }

        if op_name == "regex_search":
            pat_str = str(spec.get("pattern") or "")
            if not pat_str:
                raise ValueError("regex_search requires `pattern`")
            flags = re.IGNORECASE if bool(spec.get("ignore_case", False)) else 0
            rx = re.compile(pat_str, flags)
            base, _ = _confine_path(repo, str(spec.get("path") or "."))
            glob_pat = str(spec.get("glob") or "*")
            max_hits = max(1, min(200, int(spec.get("max_hits") or 50)))
            hits: list[dict[str, Any]] = []
            files_scanned = 0
            if base.is_file():
                scan_files = [base]
            else:
                scan_files = []
                for root, dirs, files in os.walk(base):
                    dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
                    for fn in files:
                        fp = Path(root) / fn
                        if fp.suffix.lower() not in _TEXT_EXTS and glob_pat == "*":
                            continue
                        rel = fp.relative_to(repo).as_posix()
                        if fnmatch.fnmatch(fn, glob_pat) or fnmatch.fnmatch(rel, glob_pat):
                            scan_files.append(fp)
            for fp in scan_files:
                files_scanned += 1
                try:
                    raw = fp.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                if not rx.search(raw):
                    continue
                rel = fp.relative_to(repo).as_posix()
                for lno, line in enumerate(raw.splitlines(), start=1):
                    if rx.search(line):
                        hits.append({"file": rel, "line": lno, "text": line.strip()[:220]})
                        if len(hits) >= max_hits:
                            break
                if len(hits) >= max_hits:
                    break
            return {
                "index": idx,
                "op": "regex_search",
                "ok": True,
                "pattern": pat_str,
                "files_scanned": files_scanned,
                "hit_count": len(hits),
                "hits": hits,
            }

        if op_name == "file_slice":
            target, rel = _confine_path(repo, str(spec.get("path") or ""))
            if not target.is_file():
                raise FileNotFoundError(f"File not found: {rel}")
            start = max(1, int(spec.get("start_line") or 1))
            end = max(start, int(spec.get("end_line") or (start + 119)))
            lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
            end_clamped = min(len(lines), end)
            sliced = lines[start - 1: end_clamped]
            return {
                "index": idx,
                "op": "file_slice",
                "ok": True,
                "path": rel,
                "start_line": start,
                "end_line": end_clamped,
                "total_lines": len(lines),
                "content": "\n".join(sliced),
            }

        if op_name == "git_status":
            return {"index": idx, "op": "git_status", "ok": True, **_fast_git_summary(repo, self.iron_cage, include_status=True)}

        if op_name == "surgical_bundle":
            symbol = str(spec.get("symbol") or "").strip()
            if not symbol:
                raise ValueError("surgical_bundle op requires `symbol`")
            hops = max(1, min(4, int(spec.get("hops") or 2)))
            max_bytes = max(512, min(65536, int(spec.get("max_bytes") or 8192)))
            bundle = _call_surgical_bundle(repo, symbol, hops=hops, max_bytes=max_bytes)
            return {"index": idx, "op": "surgical_bundle", **bundle}

        if op_name in ("file_hash", "sha256"):
            paths = spec.get("paths") or ([spec.get("path")] if spec.get("path") else [])
            if not isinstance(paths, list) or not paths:
                raise ValueError("file_hash op requires `paths` or `path`")
            hashes: dict[str, Any] = {}
            for raw in paths[:64]:
                target, rel = _confine_path(repo, str(raw))
                if target.is_file():
                    hashes[rel] = {"sha256": _sha256_file(target), "bytes": target.stat().st_size}
                else:
                    hashes[rel] = {"exists": False}
            return {"index": idx, "op": "file_hash", "ok": True, "count": len(hashes), "hashes": hashes}

        if op_name in ("win_probe", "sys_probe"):
            from ..platform.mnemosyne import audit_system_entropy
            return {"index": idx, "op": "win_probe", **audit_system_entropy()}

        if op_name in ("raw_recall", "mnemosyne_recall"):
            from ..platform.mnemosyne import get_mnemosyne_core
            res = get_mnemosyne_core().dispatch(
                "raw_recall",
                query=str(spec.get("query") or ""),
                repo=str(repo).replace("\\", "/"),
                top_k=int(spec.get("top_k") or 6),
                causal_hops=int(spec.get("causal_hops") if spec.get("causal_hops") is not None else 1),
            )
            return {"index": idx, "op": "raw_recall", **res}

        if op_name in ("doc_page", "pdf_page"):
            from ..platform.mnemosyne import get_mnemosyne_core
            target, rel = _confine_path(repo, str(spec.get("path") or spec.get("rel_path") or ""))
            res = get_mnemosyne_core().dispatch("doc_page", repo=str(repo), rel_path=rel, page=int(spec.get("page") or 1))
            return {"index": idx, "op": "doc_page", **res}

        if op_name in ("watch_until", "remote_xray"):
            from ..platform.agent_probe import get_default_agent_bus
            _, res = get_default_agent_bus().probe._exec_one(idx, spec, repo)
            return {"index": idx, **res}

        raise ValueError(f"Unsupported xray op: {op_name}")

    def _tool_surgical_bundle(self, args: dict[str, Any]) -> dict[str, Any]:
        t0 = time.perf_counter()
        repo = self._resolve_repo_for_call(args)
        symbol = str(args.get("symbol") or "").strip()
        if not symbol:
            raise ValueError("`symbol` is required")
        hops = max(1, min(4, int(args.get("hops") or 2)))
        max_bytes = max(512, min(65536, int(args.get("max_bytes") or 8192)))

        fp = compute_workspace_fingerprint(repo)
        sf_key = self.iron_cage.singleflight.make_key(repo, f"surgical_bundle:{symbol}:{hops}:{max_bytes}", fp)
        bundle, mode = self.iron_cage.singleflight.run_or_join(
            sf_key,
            lambda: _call_surgical_bundle(repo, symbol, hops=hops, max_bytes=max_bytes),
        )
        out = dict(bundle) if isinstance(bundle, dict) else {"ok": True, "data": bundle}
        out.setdefault("ok", True)
        out["repo"] = str(repo).replace("\\", "/")
        out["singleflight_hit"] = mode != "executed"
        out["elapsed_ms"] = round((time.perf_counter() - t0) * 1000.0, 2)
        return out

    def _tool_atomic_patch(self, args: dict[str, Any]) -> dict[str, Any]:
        t0 = time.perf_counter()
        repo = self._resolve_repo_for_call(args)
        edits = args.get("edits")
        if not isinstance(edits, list) or not edits:
            raise ValueError("`edits` must be a non-empty array")

        dry_run = bool(args.get("dry_run", False))
        agent_id = str(args.get("agent_id") or args.get("conversation_id") or "mcp-client")
        cid = str(args.get("conversation_id") or agent_id)

        # Phase 1: In-RAM simulation (zero disk mutations yet)
        staged: dict[Path, bytes | None] = {}
        rel_map: dict[Path, str] = {}
        orig_map: dict[Path, bytes | None] = {}

        for idx, ed in enumerate(edits):
            if not isinstance(ed, dict):
                raise ValueError(f"Edit #{idx} must be an object")
            raw_path = str(ed.get("path") or "").strip()
            if not raw_path:
                raise ValueError(f"Edit #{idx} missing `path`")
            target, rel = _confine_path(repo, raw_path)
            rel_map[target] = rel

            if target not in orig_map:
                orig_map[target] = target.read_bytes() if target.is_file() else None
            cur_bytes = staged[target] if target in staged else orig_map[target]

            if ed.get("delete"):
                staged[target] = None
            elif "content" in ed and ed["content"] is not None:
                staged[target] = str(ed["content"]).encode("utf-8")
            elif "old" in ed and "new" in ed:
                if cur_bytes is None:
                    return {
                        "ok": False,
                        "stage": "simulate",
                        "error": f"Cannot replace in missing file: {rel}",
                        "written": [],
                        "rolled_back": False,
                    }
                cur_txt = cur_bytes.decode("utf-8", errors="replace")
                old = str(ed["old"])
                new = str(ed["new"])
                if old not in cur_txt:
                    return {
                        "ok": False,
                        "stage": "simulate",
                        "error": f"Target snippet not found in {rel}",
                        "written": [],
                        "rolled_back": False,
                    }
                updated = cur_txt.replace(old, new) if ed.get("replace_all") else cur_txt.replace(old, new, 1)
                staged[target] = updated.encode("utf-8")
            else:
                raise ValueError(f"Edit #{idx} ({rel}) requires `content`, `old`+`new`, or `delete: true`")

        # Phase 1b: In-RAM Syntax Gate BEFORE touching disk!
        syntax_errors: list[dict[str, Any]] = []
        for target, new_bytes in staged.items():
            if new_bytes is None:
                continue
            rel = rel_map[target]
            gate = syntax_gate_content(new_bytes.decode("utf-8", errors="replace"), rel, iron_cage=self.iron_cage)
            if not gate["ok"]:
                syntax_errors.extend(gate["diagnostics"])

        if syntax_errors:
            return {
                "ok": False,
                "stage": "syntax_gate",
                "error": f"Pre-write syntax gate rejected patch ({len(syntax_errors)} error(s))",
                "errors": syntax_errors,
                "written": [],
                "rolled_back": False,
                "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
            }

        if dry_run:
            return {
                "ok": True,
                "dry_run": True,
                "repo": str(repo).replace("\\", "/"),
                "files": sorted(rel_map.values()),
                "written": [],
                "rolled_back": False,
                "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
            }

        # Phase 2: Transactional disk write + automatic rollback on any failure
        written: list[Path] = []
        sha_out: dict[str, str] = {}
        try:
            for target, new_bytes in staged.items():
                rel = rel_map[target]
                if new_bytes is None:
                    if target.exists():
                        target.unlink()
                    written.append(target)
                else:
                    _atomic_write_bytes(target, new_bytes)
                    written.append(target)
                    sha_out[rel] = hashlib.sha256(new_bytes).hexdigest()
        except Exception as exc:
            for target in reversed(written):
                orig = orig_map.get(target)
                try:
                    if orig is None:
                        if target.exists():
                            target.unlink()
                    else:
                        _atomic_write_bytes(target, orig)
                except OSError:
                    pass
            return {
                "ok": False,
                "stage": "write",
                "error": str(exc),
                "written": [],
                "rolled_back": True,
                "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
            }

        touched_rels = sorted(rel_map.values())
        self.iron_cage.singleflight.invalidate()
        self.hive.record_mutation(
            agent_id=agent_id,
            repo=repo,
            files=touched_rels,
            kind="atomic_patch",
            detail=f"{len(touched_rels)} file(s)",
        )
        for rel in touched_rels:
            self.sessions.record_touched_file(cid, rel)

        return {
            "ok": True,
            "repo": str(repo).replace("\\", "/"),
            "written": touched_rels,
            "sha256": sha_out,
            "rolled_back": False,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }

    def _tool_commit_verify(self, args: dict[str, Any]) -> dict[str, Any]:
        t0 = time.perf_counter()
        repo = self._resolve_repo_for_call(args)
        nrepo = str(repo).replace("\\", "/")
        cid = str(args.get("conversation_id") or "mcp-verify")
        force = bool(args.get("force", False))
        timeout_s = max(2.0, min(300.0, float(args.get("timeout_s") or 60.0)))

        raw_files = args.get("changed_files")
        changed_files: list[str] = []
        if isinstance(raw_files, list):
            for f in raw_files:
                _, rel = _confine_path(repo, str(f))
                if rel != ".":
                    changed_files.append(rel)
        if not changed_files:
            git_st = _fast_git_summary(repo, self.iron_cage, include_status=True)
            changed_files = list(git_st.get("modified") or [])[:32]

        custom_cmd = args.get("cmd")

        # Compute deterministic BLAKE2s digest across git HEAD + changed file bytes + matching test bytes + cmd
        # (intentionally excludes root dir mtime so test runners creating .pytest_cache/TestResults don't poison cache)
        git_head = _fast_git_summary(repo, self.iron_cage, include_status=False)
        hash_targets: set[str] = set(changed_files)
        for rel in list(changed_files):
            stem = Path(rel).stem
            cand_test = repo / "tests" / f"test_{stem}.py"
            if cand_test.is_file():
                hash_targets.add(cand_test.relative_to(repo).as_posix())

        h = hashlib.blake2s(digest_size=16)
        h.update(nrepo.lower().encode("utf-8", errors="replace"))
        h.update(f"|head:{git_head.get('branch', '')}:{git_head.get('head_sha', '')}|cmd:{custom_cmd or ''}|".encode("utf-8", errors="replace"))
        for rel in sorted(hash_targets):
            fp = repo / rel
            h.update(f"|{rel}:".encode("utf-8", errors="replace"))
            if fp.is_file():
                try:
                    h.update(fp.read_bytes())
                except OSError:
                    h.update(b"<err>")
            else:
                h.update(b"<deleted>")
        digest = h.hexdigest()

        if not force:
            with self._lock:
                cached = self._verify_cache.get(digest)
                if cached is not None:
                    self._verify_cache.move_to_end(digest)
                    self._stats["verify_cache_hits"] += 1
                    res = dict(cached)
                    res["cache_hit"] = True
                    res["elapsed_ms"] = round((time.perf_counter() - t0) * 1000.0, 2)
                    return res

        # Fast in-RAM syntax gate first
        syntax_errors: list[dict[str, Any]] = []
        for rel in changed_files:
            fp = repo / rel
            if fp.is_file():
                gate = syntax_gate_content(fp.read_text(encoding="utf-8", errors="replace"), rel, iron_cage=self.iron_cage)
                if not gate["ok"]:
                    syntax_errors.extend(gate["diagnostics"])

        if syntax_errors:
            out = {
                "ok": False,
                "repo": nrepo,
                "blake2s": digest,
                "cache_hit": False,
                "stage": "syntax_gate",
                "changed_files": changed_files,
                "syntax_errors": syntax_errors,
                "exit_code": 1,
                "stdout": "",
                "stderr": syntax_errors[0].get("message", "syntax error"),
                "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
            }
            self.cortex.record_tool_outcome(cid, nrepo, "chimera_commit_verify", {"changed_files": changed_files}, False, error=out["stderr"])
            return out

        # Choose verification command
        exec_cmd: str | list[str] | None = None
        runner = "syntax_only"
        if custom_cmd:
            exec_cmd = custom_cmd
            runner = "custom"
        else:
            has_cs = any(f.lower().endswith(".cs") for f in changed_files) or any(repo.glob("*.sln")) or any(repo.glob("*.csproj"))
            has_py = any(f.lower().endswith(".py") for f in changed_files)
            has_js = any(f.lower().endswith((".js", ".mjs", ".cjs")) for f in changed_files)

            if has_cs and shutil.which("dotnet"):
                dn = _call_impacted_dotnet_tests(repo, changed_files)
                imp_projs = dn.get("impacted_projects") or []
                cmds = dn.get("commands") or []
                if imp_projs and isinstance(imp_projs[0], dict) and imp_projs[0].get("argv"):
                    exec_cmd = list(imp_projs[0]["argv"])
                    runner = "dotnet_test"
                elif cmds:
                    exec_cmd = cmds[0]
                    runner = "dotnet_test"
                else:
                    slns = sorted(repo.glob("*.sln")) or sorted(repo.glob("*.csproj"))
                    if slns:
                        exec_cmd = ["dotnet", "build", str(slns[0]), "--no-restore", "--nologo", "-v:q"]
                        runner = "dotnet_build"
            elif has_py:
                py_tests: list[str] = []
                for rel in changed_files:
                    stem = Path(rel).stem
                    if stem.startswith("test_") and (repo / rel).is_file():
                        py_tests.append(rel)
                    else:
                        cand = repo / "tests" / f"test_{stem}.py"
                        if cand.is_file():
                            py_tests.append(cand.relative_to(repo).as_posix())
                if not py_tests and (repo / "tests").is_dir():
                    py_tests = [p.relative_to(repo).as_posix() for p in sorted((repo / "tests").glob("test_*.py"))[:6]]
                if py_tests:
                    import importlib.util as _ilu
                    if _ilu.find_spec("pytest") is not None:
                        exec_cmd = [sys.executable, "-m", "pytest", "-q", *sorted(set(py_tests))]
                        runner = "pytest"
                    else:
                        exec_cmd = [sys.executable, "-m", "unittest", *sorted(set(py_tests))]
                        runner = "unittest"
            elif has_js and shutil.which("node"):
                js_tests = [
                    p.relative_to(repo).as_posix()
                    for p in sorted(repo.rglob("*.test.*"))[:6]
                    if not any(part in _SKIP_DIRS for part in p.parts)
                ]
                if js_tests:
                    exec_cmd = ["node", "--test", *js_tests]
                    runner = "node_test"

        if exec_cmd is None:
            out = {
                "ok": True,
                "repo": nrepo,
                "blake2s": digest,
                "cache_hit": False,
                "runner": runner,
                "cmd": None,
                "changed_files": changed_files,
                "syntax_errors": [],
                "exit_code": 0,
                "stdout": "syntax_gate_passed (no matching test runner)",
                "stderr": "",
                "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
            }
        else:
            run_res = self.iron_cage.spawn_caged(
                exec_cmd,
                cwd=repo,
                timeout_s=timeout_s,
                use_singleflight=True,
                fingerprint=digest,
                bypass_cache=force,
            )
            out = {
                "ok": bool(run_res.get("ok")),
                "repo": nrepo,
                "blake2s": digest,
                "cache_hit": False,
                "runner": runner,
                "cmd": exec_cmd,
                "changed_files": changed_files,
                "syntax_errors": [],
                "exit_code": int(run_res.get("exit_code", -1)),
                "timed_out": bool(run_res.get("timed_out", False)),
                "stdout": (run_res.get("stdout") or "")[-4000:],
                "stderr": (run_res.get("stderr") or "")[-2000:],
                "conhost_avoided": bool(run_res.get("conhost_avoided", False)),
                "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
            }

        self.cortex.record_tool_outcome(
            cid,
            nrepo,
            "chimera_commit_verify",
            {"changed_files": changed_files, "cmd": str(exec_cmd or "")},
            bool(out["ok"]),
            error="" if out["ok"] else (out.get("stderr") or out.get("stdout") or "verify_failed")[:240],
        )

        with self._lock:
            self._verify_cache[digest] = dict(out)
            self._verify_cache.move_to_end(digest)
            while len(self._verify_cache) > 64:
                self._verify_cache.popitem(last=False)
        return out

    def _tool_hive_cortex(self, args: dict[str, Any]) -> dict[str, Any]:
        action = str(args.get("action") or "status").strip().lower()

        if action == "lease":
            repo = self._resolve_repo_for_call(args)
            res = self.hive.acquire_lease(
                agent_id=str(args.get("agent_id") or "mcp-agent"),
                repo=repo,
                files=list(args.get("files") or []),
                intent=str(args.get("intent") or ""),
                ttl_s=float(args.get("ttl_s") or 120.0),
                hard_lock=bool(args.get("hard_lock", False)),
            )
            ab = self.cortex.match_antibodies(str(repo).replace("\\", "/"), limit=4)
            res["antibodies"] = ab
            return res

        if action == "release":
            raw_repo = str(args.get("repo") or "").strip() or None
            repo = _resolve_safe_repo(raw_repo) if raw_repo else None
            return self.hive.release_lease(
                agent_id=str(args.get("agent_id") or "mcp-agent"),
                repo=repo,
            )

        if action == "status":
            raw_repo = str(args.get("repo") or "").strip() or None
            repo = _resolve_safe_repo(raw_repo) if raw_repo else None
            return {
                "ok": True,
                "hive": self.hive.status(repo=repo),
                "akashic": self.cortex.status(),
                "iron_cage": self.iron_cage.status(),
                "precog": self.precog.status(),
                "tournament": self.tournament.status(),
                "sessions": self.sessions.status(),
            }

        if action == "put_capsule":
            repo = self._resolve_repo_for_call(args)
            nrepo = str(repo).replace("\\", "/")
            rel_path = str(args.get("rel_path") or "").strip().replace("\\", "/").lstrip("./")
            symbol = str(args.get("symbol") or "").strip()
            summary = str(args.get("summary") or "").strip()
            if not rel_path or not symbol or not summary:
                raise ValueError("put_capsule requires `rel_path`, `symbol`, and `summary`")
            sha = str(args.get("file_sha256") or "").strip()
            if not sha:
                target, rel_path = _confine_path(repo, rel_path)
                sha = _sha256_file(target) if target.is_file() else hashlib.sha256(b"").hexdigest()
            return self.cortex.put_symbol_capsule(
                nrepo,
                rel_path,
                sha,
                symbol,
                summary,
                list(args.get("invariants") or []),
                line_range=str(args.get("line_range") or ""),
                author=str(args.get("agent_id") or "mcp-agent"),
            )

        if action == "recall_capsules":
            repo = self._resolve_repo_for_call(args)
            nrepo = str(repo).replace("\\", "/")
            file_hashes = dict(args.get("file_hashes") or {})
            if not file_hashes:
                for rel in list(args.get("files") or []):
                    target, clean_rel = _confine_path(repo, str(rel))
                    if target.is_file():
                        file_hashes[clean_rel] = _sha256_file(target)
            caps = self.cortex.recall_for_files(nrepo, file_hashes, limit=int(args.get("limit") or 8))
            return {"ok": True, "repo": nrepo, "count": len(caps), "capsules": caps}

        if action == "antibodies":
            q = str(args.get("query") or args.get("repo") or "").strip()
            hits = self.cortex.match_antibodies(q, limit=int(args.get("limit") or 5)) if q else []
            return {"ok": True, "query": q, "count": len(hits), "antibodies": hits, "cortex": self.cortex.status()}

        if action == "tournament_run":
            if bool(args.get("promote")) and args.get("tournament_id"):
                return self.tournament.promote_winner(str(args["tournament_id"]))
            repo = self._resolve_repo_for_call(args)
            return self.tournament.run(
                repo=repo,
                candidates=list(args.get("candidates") or []),
                oracle_cmd=args.get("oracle_cmd"),
                timeout_s=float(args.get("timeout_s") or 30.0),
                isolation=str(args.get("isolation") or "auto"),
            )

        if action == "cage_status":
            sweep_res = self.iron_cage.cage_sweep_agent_children() if bool(args.get("sweep")) else None
            st = self.iron_cage.status()
            if sweep_res is not None:
                st["sweep"] = sweep_res
            return st

        if action == "release_status":
            rc = self._get_release_conductor()
            return rc.status()

        if action == "release_stage":
            rc = self._get_release_conductor()
            repo = self._resolve_repo_for_call(args)
            return rc.stage_release(
                repo,
                epoch=args.get("epoch") or None,
                verify=bool(args.get("verify", True)),
                write_desired=bool(args.get("write_desired", False)),
            )

        if action == "release_replicate":
            rc = self._get_release_conductor()
            epoch = str(args.get("epoch") or "").strip()
            peer_url = str(args.get("peer_url") or "").strip()
            if not epoch or not peer_url:
                raise ValueError("release_replicate requires both 'epoch' and 'peer_url'")
            return rc.replicate_to_peer(epoch, peer_url, write_desired=bool(args.get("write_desired", True)))

        if action == "blocker_alerts":
            rt = getattr(self, "_runtime_ref", None)
            hooks = getattr(rt, "hooks", None) if rt is not None else None
            repo_q = str(args.get("repo") or "").strip() or None
            alerts = hooks.list_blocker_alerts(repo=repo_q) if hooks is not None else []
            return {"ok": True, "count": len(alerts), "alerts": alerts}

        if action == "context_hygiene":
            from .release_conductor import context_hygiene_audit

            repo_q = str(args.get("repo") or "").strip()
            return context_hygiene_audit([repo_q] if repo_q else [])

        if action in (
            "raw_recall",
            "raw_ingest",
            "raw_slice",
            "warm_repl",
            "entropy_audit",
            "raw_arena",
            "swarm_watchdog",
            "shell_guard_status",
        ):
            from ..platform.mnemosyne import get_mnemosyne_core
            mn = get_mnemosyne_core()
            if action == "shell_guard_status":
                return mn.shell_guard.status()
            return mn.dispatch(action, **{k: v for k, v in args.items() if k != "action"})

        if action in (
            "prometheus_status",
            "axioms",
            "axiom_check",
            "epoch_status",
            "epoch_seal",
            "epoch_verify",
            "soak_acquire",
            "soak_release",
            "epoch_promote",
            "worktrees",
            "galileo_status",
            "oracle_probe",
            "phantom_probe",
            "oracle_speculate",
            "morning_brief",
            "ghost_status",
            "ghost_read",
            "spine_status",
        ):
            from ..platform.prometheus import get_prometheus_core
            prom = get_prometheus_core()
            act_norm = "status" if action == "prometheus_status" else action
            return prom.dispatch(act_norm, **{k: v for k, v in args.items() if k != "action"})

        raise ValueError(f"Unsupported hive_cortex action: {action}")

    def attach_runtime(self, runtime: Any) -> None:
        self._runtime_ref = runtime

    def _get_release_conductor(self) -> Any:
        rt = getattr(self, "_runtime_ref", None)
        if rt is not None and hasattr(rt, "release_conductor"):
            return rt.release_conductor
        from .release_conductor import ReleaseConductor

        return ReleaseConductor()

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "ok": True,
                "protocol_version": MCP_PROTOCOL_VERSION,
                "tools_count": len(EAGER_SUPER_TOOLS),
                "tool_names": [t["name"] for t in EAGER_SUPER_TOOLS],
                "active_mcp_sessions": len(self._mcp_sessions),
                "verify_cache_entries": len(self._verify_cache),
                "stats": dict(self._stats),
            }


_DEFAULT_MCP_LOCK = threading.Lock()
_DEFAULT_MCP: StreamableMcpServer | None = None


def get_mcp_server() -> StreamableMcpServer:
    global _DEFAULT_MCP
    with _DEFAULT_MCP_LOCK:
        if _DEFAULT_MCP is None:
            _DEFAULT_MCP = StreamableMcpServer()
        return _DEFAULT_MCP


def handle_mcp_request(raw_body: bytes | dict[str, Any], headers: Any = None) -> tuple[int, Any, dict[str, str]]:
    if isinstance(raw_body, dict):
        raw_b = json.dumps(raw_body, ensure_ascii=False).encode("utf-8")
    else:
        raw_b = raw_body
    return get_mcp_server().handle_post(raw_b, headers=headers)
