"""CHIMERA Omega-Spine: Precog Speculative Verifier + Shadow Tournament Arena.

1. `PrecogVerifier`: Asynchronous (max 2 concurrent daemon workers inside Iron Cage)
   speculative verification triggered immediately on `PostToolUse(edit_file|write_file)`.
   - `.cs`: `< 5 ms` in-RAM `syntax_gate_csharp` + optional debounced `dotnet build --no-restore`
     extracting `CS####` compiler diagnostics keyed by `(repo, rel_path, mtime_ns)`.
   - `.py`: instant `ast.parse` gate + optional impacted `pytest`.
   - `.js`/`.mjs`/`.cjs`: instant `node --check` gate (inside Iron Cage).
   - `.json`/`.toml`: instant stdlib parser gate.
   Feeds `PreInvocation` (`consume_diagnostics`) and `Stop` sentinel (`has_blocking_errors`).

2. `ShadowTournament`: Runs 2-3 competing candidate patches/algorithms in isolated
   temporary workspaces (detached `git worktree` or fast filtered copy/hardlink sandbox,
   always auto-cleaned in `finally`), evaluates each with a deterministic `oracle_cmd`,
   ranks strictly by verified metrics (`pass`, `score`, `elapsed_ms`), and supports
   atomic winner promotion via `promote_winner(tournament_id)`.
"""

from __future__ import annotations

import ast
import collections
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import time
import tomllib
import uuid
from pathlib import Path
from typing import Any

from .iron_cage import IronCage, get_iron_cage

_CS_DIAG_RE = re.compile(
    r"^\s*(?P<file>[^\r\n(]+?)\((?P<line>\d+)(?:,(?P<col>\d+))?\):\s*"
    r"(?P<severity>error|warning)\s+(?P<code>CS\d{4}):\s*(?P<message>.+?)\s*(?:\[[^\]]+\])?\s*$",
    re.MULTILINE,
)

_SKIP_SANDBOX_DIRS = frozenset({
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
})


def _norm_repo(repo: str | Path) -> str:
    try:
        return str(Path(repo).resolve()).replace("\\", "/")
    except OSError:
        return str(repo).replace("\\", "/")


def _norm_rel(repo: Path, file_path: str | Path) -> tuple[str, Path]:
    p = Path(file_path)
    if not p.is_absolute():
        p = repo / p
    try:
        rp = p.resolve()
        rr = repo.resolve()
        rel = rp.relative_to(rr).as_posix()
        return rel, rp
    except Exception:
        return str(file_path).replace("\\", "/").lstrip("./"), p


def _fallback_syntax_gate_csharp(content: str, path: str = "") -> dict[str, Any]:
    """Minimal string/comment-aware brace/paren/bracket balance fallback if csharp_xray is not yet present."""
    stack: list[tuple[str, int]] = []
    pairs = {"{": "}", "(": ")", "[": "]"}
    closers = {"}": "{", ")": "(", "]": "["}
    errors: list[dict[str, Any]] = []
    i = 0
    n = len(content)
    line = 1
    while i < n:
        ch = content[i]
        nxt = content[i + 1] if i + 1 < n else ""
        if ch == "\n":
            line += 1
            i += 1
            continue
        # Line comment
        if ch == "/" and nxt == "/":
            nl = content.find("\n", i + 2)
            if nl < 0:
                break
            line += 1
            i = nl + 1
            continue
        # Block comment
        if ch == "/" and nxt == "*":
            end = content.find("*/", i + 2)
            if end < 0:
                errors.append({"line": line, "message": "Unterminated block comment"})
                break
            line += content.count("\n", i, end + 2)
            i = end + 2
            continue
        # Verbatim string @"..." or $@"..."
        if (ch == "@" and nxt == '"') or (ch == "$" and nxt == "@" and i + 2 < n and content[i + 2] == '"'):
            start_line = line
            i += 3 if ch == "$" else 2
            closed = False
            while i < n:
                if content[i] == "\n":
                    line += 1
                elif content[i] == '"':
                    if i + 1 < n and content[i + 1] == '"':
                        i += 2
                        continue
                    closed = True
                    i += 1
                    break
                i += 1
            if not closed:
                errors.append({"line": start_line, "message": "Unterminated verbatim string"})
            continue
        # Regular string "..."
        if ch == '"':
            start_line = line
            i += 1
            closed = False
            while i < n:
                c = content[i]
                if c == "\\":
                    i += 2
                    continue
                if c == "\n":
                    break
                if c == '"':
                    closed = True
                    i += 1
                    break
                i += 1
            if not closed:
                errors.append({"line": start_line, "message": "Unterminated string literal"})
            continue
        # Char literal '...'
        if ch == "'":
            start_line = line
            i += 1
            closed = False
            while i < n:
                c = content[i]
                if c == "\\":
                    i += 2
                    continue
                if c == "\n":
                    break
                if c == "'":
                    closed = True
                    i += 1
                    break
                i += 1
            if not closed:
                errors.append({"line": start_line, "message": "Unterminated char literal"})
            continue
        if ch in pairs:
            stack.append((ch, line))
        elif ch in closers:
            if not stack or stack[-1][0] != closers[ch]:
                errors.append({"line": line, "message": f"Unmatched closing '{ch}'"})
            else:
                stack.pop()
        i += 1
    for opener, oline in stack:
        errors.append({"line": oline, "message": f"Unclosed '{opener}'"})
    return {"ok": len(errors) == 0, "errors": errors, "path": path}


def syntax_gate_content(content: str, path: str, *, iron_cage: IronCage | None = None) -> dict[str, Any]:
    """Run instant in-RAM syntax gate for .cs/.py/.json/.toml/.js/.mjs/.cjs."""
    ext = Path(path).suffix.lower()
    if ext == ".cs":
        try:
            from .csharp_xray import syntax_gate_csharp
            res = syntax_gate_csharp(content, path=path)
        except ImportError:
            res = _fallback_syntax_gate_csharp(content, path=path)
        diags = []
        for err in res.get("errors") or []:
            diags.append({
                "file": path,
                "line": int(err.get("line") or 1),
                "severity": "error",
                "code": str(err.get("code") or "CS_SYNTAX"),
                "message": str(err.get("message") or "C# syntax error"),
            })
        return {"ok": bool(res.get("ok")) and not diags, "diagnostics": diags, "lang": "csharp"}

    if ext == ".py":
        try:
            ast.parse(content, filename=path or "<memory>")
            return {"ok": True, "diagnostics": [], "lang": "python"}
        except SyntaxError as exc:
            return {
                "ok": False,
                "diagnostics": [{
                    "file": path,
                    "line": int(exc.lineno or 1),
                    "col": int(exc.offset or 0),
                    "severity": "error",
                    "code": "PY_SYNTAX",
                    "message": str(exc.msg or exc),
                }],
                "lang": "python",
            }

    if ext == ".json":
        if not content.strip():
            return {"ok": True, "diagnostics": [], "lang": "json"}
        try:
            json.loads(content)
            return {"ok": True, "diagnostics": [], "lang": "json"}
        except json.JSONDecodeError as exc:
            return {
                "ok": False,
                "diagnostics": [{
                    "file": path,
                    "line": int(exc.lineno or 1),
                    "col": int(exc.colno or 0),
                    "severity": "error",
                    "code": "JSON_SYNTAX",
                    "message": str(exc.msg),
                }],
                "lang": "json",
            }

    if ext == ".toml":
        try:
            tomllib.loads(content)
            return {"ok": True, "diagnostics": [], "lang": "toml"}
        except Exception as exc:
            return {
                "ok": False,
                "diagnostics": [{
                    "file": path,
                    "line": 1,
                    "severity": "error",
                    "code": "TOML_SYNTAX",
                    "message": str(exc),
                }],
                "lang": "toml",
            }

    if ext in (".js", ".mjs", ".cjs"):
        node_bin = shutil.which("node")
        if node_bin:
            cage = iron_cage or get_iron_cage()
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                suffix=ext,
                prefix="chimera_jsgate_",
                delete=False,
            ) as tf:
                tf.write(content)
                tmp_path = tf.name
            try:
                out = cage.spawn_caged([node_bin, "--check", tmp_path], cwd=Path(tmp_path).parent, timeout_s=8.0)
            finally:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
            if out["ok"]:
                return {"ok": True, "diagnostics": [], "lang": "javascript"}
            err_txt = (out.get("stderr") or out.get("stdout") or "JS syntax error").strip()
            line_no = 1
            m = re.search(r":(\d+)\b", err_txt)
            if m:
                line_no = int(m.group(1))
            first_msg = next((ln.strip() for ln in err_txt.splitlines() if "SyntaxError" in ln), err_txt.splitlines()[-1] if err_txt else "SyntaxError")
            return {
                "ok": False,
                "diagnostics": [{
                    "file": path,
                    "line": line_no,
                    "severity": "error",
                    "code": "JS_SYNTAX",
                    "message": first_msg[:260],
                }],
                "lang": "javascript",
            }
        # Fallback if node binary is absent
        fb = _fallback_syntax_gate_csharp(content, path=path)
        diags = [{
            "file": path,
            "line": int(e.get("line") or 1),
            "severity": "error",
            "code": "JS_SYNTAX",
            "message": str(e.get("message") or "JS syntax error"),
        } for e in (fb.get("errors") or [])]
        return {"ok": not diags, "diagnostics": diags, "lang": "javascript"}

    return {"ok": True, "diagnostics": [], "lang": ext.lstrip(".") or "text"}


def parse_dotnet_diagnostics(output: str, repo_root: Path | None = None) -> list[dict[str, Any]]:
    """Parse MSBuild / Roslyn CS#### diagnostics from `dotnet build` output."""
    diags: list[dict[str, Any]] = []
    seen: set[tuple[str, int, str, str]] = set()
    for m in _CS_DIAG_RE.finditer(output or ""):
        raw_file = m.group("file").strip()
        rel = raw_file.replace("\\", "/")
        if repo_root is not None:
            try:
                p = Path(raw_file)
                if p.is_absolute():
                    rel = p.resolve().relative_to(repo_root.resolve()).as_posix()
            except Exception:
                pass
        line = int(m.group("line"))
        col = int(m.group("col") or 0)
        sev = m.group("severity").lower()
        code = m.group("code").upper()
        msg = m.group("message").strip()
        dedup = (rel, line, code, msg)
        if dedup in seen:
            continue
        seen.add(dedup)
        diags.append({
            "file": rel,
            "line": line,
            "col": col,
            "severity": sev,
            "code": code,
            "message": msg[:260],
        })
    return diags


def _find_nearest_dotnet_project(file_path: Path, repo_root: Path) -> Path | None:
    cur = file_path.parent if file_path.is_file() or file_path.suffix else file_path
    try:
        root_res = repo_root.resolve()
        cur_res = cur.resolve()
    except OSError:
        return None
    while True:
        try:
            for ext in ("*.csproj", "*.sln"):
                found = sorted(cur_res.glob(ext))
                if found:
                    return found[0]
        except OSError:
            pass
        if cur_res == root_res or cur_res.parent == cur_res:
            break
        if root_res not in cur_res.parents:
            break
        cur_res = cur_res.parent
    return None


class PrecogVerifier:
    """Asynchronous speculative verifier feeding PreInvocation + Stop hook sentinel."""

    def __init__(
        self,
        *,
        iron_cage: IronCage | None = None,
        max_concurrent: int = 2,
        enable_dotnet_build: bool = True,
        enable_pytest: bool = False,
        dotnet_debounce_s: float = 0.25,
    ) -> None:
        self.iron_cage = iron_cage or get_iron_cage()
        self._sem = threading.Semaphore(max(1, int(max_concurrent)))
        self.enable_dotnet_build = bool(enable_dotnet_build)
        self.enable_pytest = bool(enable_pytest)
        self.dotnet_debounce_s = max(0.0, float(dotnet_debounce_s))
        self._lock = threading.Lock()
        # (conversation_id, norm_repo, rel_path) -> entry dict
        self._entries: dict[tuple[str, str, str], dict[str, Any]] = {}
        # (norm_repo, rel_path, mtime_ns) -> cached result dict
        self._mtime_cache: collections.OrderedDict[tuple[str, str, int], dict[str, Any]] = collections.OrderedDict()
        self._recent: collections.deque[dict[str, Any]] = collections.deque(maxlen=40)
        self._inflight = 0
        self._idle_cv = threading.Condition(self._lock)
        self._stats = {
            "scheduled": 0,
            "completed": 0,
            "syntax_catches": 0,
            "dotnet_builds": 0,
            "pytest_runs": 0,
            "cache_hits": 0,
        }

    def schedule(
        self,
        conversation_id: str,
        repo: str | Path,
        file_path: str | Path,
        *,
        enable_dotnet_build: bool | None = None,
        enable_pytest: bool | None = None,
    ) -> dict[str, Any]:
        """Schedule non-blocking speculative verification for an edited file."""
        cid = str(conversation_id or "default")
        repo_p = Path(repo)
        nrepo = _norm_repo(repo_p)
        rel_path, abs_path = _norm_rel(repo_p, file_path)

        use_dotnet = self.enable_dotnet_build if enable_dotnet_build is None else bool(enable_dotnet_build)
        use_pytest = self.enable_pytest if enable_pytest is None else bool(enable_pytest)

        with self._lock:
            self._stats["scheduled"] += 1
            self._inflight += 1

        def _worker() -> None:
            acquired = self._sem.acquire(timeout=15.0)
            try:
                if acquired:
                    self.verify_file_now(
                        cid,
                        repo_p,
                        abs_path,
                        enable_dotnet_build=use_dotnet,
                        enable_pytest=use_pytest,
                    )
            finally:
                if acquired:
                    self._sem.release()
                with self._lock:
                    self._inflight = max(0, self._inflight - 1)
                    if self._inflight == 0:
                        self._idle_cv.notify_all()

        t = threading.Thread(target=_worker, daemon=True, name=f"chimera-precog-{rel_path[:24]}")
        t.start()
        return {"ok": True, "scheduled": True, "conversation_id": cid, "repo": nrepo, "file": rel_path}

    def wait_idle(self, timeout_s: float = 5.0) -> bool:
        deadline = time.monotonic() + max(0.05, float(timeout_s))
        with self._lock:
            while self._inflight > 0:
                rem = deadline - time.monotonic()
                if rem <= 0:
                    return False
                self._idle_cv.wait(timeout=rem)
            return True

    def verify_file_now(
        self,
        conversation_id: str,
        repo: str | Path,
        file_path: str | Path,
        *,
        enable_dotnet_build: bool | None = None,
        enable_pytest: bool | None = None,
    ) -> dict[str, Any]:
        """Run immediate verification and record keyed diagnostics for (conversation_id, repo, rel_path)."""
        t0 = time.perf_counter()
        cid = str(conversation_id or "default")
        repo_p = Path(repo)
        nrepo = _norm_repo(repo_p)
        rel_path, abs_path = _norm_rel(repo_p, file_path)

        if not abs_path.is_file():
            entry = {
                "conversation_id": cid,
                "repo": nrepo,
                "file": rel_path,
                "mtime_ns": 0,
                "ok": True,
                "blocking": False,
                "diagnostics": [],
                "seen": True,
                "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
                "verified_at": round(time.time(), 3),
                "stage": "missing",
            }
            with self._lock:
                self._entries.pop((cid, nrepo, rel_path), None)
            return entry

        try:
            st = abs_path.stat()
            mtime_ns = int(st.st_mtime_ns)
            content = abs_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return {
                "conversation_id": cid,
                "repo": nrepo,
                "file": rel_path,
                "ok": False,
                "blocking": False,
                "diagnostics": [{"file": rel_path, "line": 1, "severity": "warning", "code": "IO_ERR", "message": str(exc)}],
                "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
            }

        cache_key = (nrepo, rel_path, mtime_ns)
        with self._lock:
            cached = self._mtime_cache.get(cache_key)
            if cached is not None:
                self._mtime_cache.move_to_end(cache_key)
                self._stats["cache_hits"] += 1
                entry = dict(cached, conversation_id=cid, seen=False if cached.get("diagnostics") else True)
                self._entries[(cid, nrepo, rel_path)] = entry
                return entry

        gate = syntax_gate_content(content, rel_path, iron_cage=self.iron_cage)
        diags: list[dict[str, Any]] = list(gate.get("diagnostics") or [])
        stage = "syntax_gate"
        ext = abs_path.suffix.lower()

        use_dotnet = self.enable_dotnet_build if enable_dotnet_build is None else bool(enable_dotnet_build)
        if os.environ.get("CHIMERA_PRECOG_DOTNET_BUILD") == "0":
            use_dotnet = False
        use_pytest = self.enable_pytest if enable_pytest is None else bool(enable_pytest)

        if not diags and ext == ".cs" and use_dotnet and shutil.which("dotnet"):
            proj = _find_nearest_dotnet_project(abs_path, repo_p)
            if proj is not None:
                stage = "dotnet_build"
                cmd = ["dotnet", "build", str(proj), "--no-restore", "--nologo", "-v:q"]
                res = self.iron_cage.spawn_caged(
                    cmd,
                    cwd=proj.parent,
                    timeout_s=45.0,
                    use_singleflight=True,
                )
                with self._lock:
                    self._stats["dotnet_builds"] += 1
                if not res.get("ok"):
                    parsed = parse_dotnet_diagnostics(
                        (res.get("stdout") or "") + "\n" + (res.get("stderr") or ""),
                        repo_root=repo_p,
                    )
                    if parsed:
                        diags.extend(parsed)
                    else:
                        diags.append({
                            "file": rel_path,
                            "line": 1,
                            "severity": "error",
                            "code": "CS_BUILD",
                            "message": ((res.get("stderr") or res.get("stdout") or "dotnet build failed").strip())[:260],
                        })

        elif not diags and ext == ".py" and use_pytest:
            test_cand = _find_matching_py_test(repo_p, rel_path)
            if test_cand is not None:
                stage = "pytest"
                res = self.iron_cage.spawn_caged(
                    [sys.executable, "-m", "pytest", "-q", str(test_cand)],
                    cwd=repo_p,
                    timeout_s=25.0,
                    use_singleflight=True,
                )
                with self._lock:
                    self._stats["pytest_runs"] += 1
                if not res.get("ok"):
                    tail = ((res.get("stdout") or "") + "\n" + (res.get("stderr") or "")).strip().splitlines()[-3:]
                    diags.append({
                        "file": rel_path,
                        "line": 1,
                        "severity": "error",
                        "code": "PYTEST_FAIL",
                        "message": " | ".join(t.strip() for t in tail if t.strip())[:260] or "pytest failed",
                    })

        blocking = any(str(d.get("severity") or "error").lower() == "error" for d in diags)
        elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        entry = {
            "conversation_id": cid,
            "repo": nrepo,
            "file": rel_path,
            "mtime_ns": mtime_ns,
            "ok": not blocking,
            "blocking": blocking,
            "diagnostics": diags,
            "seen": False if diags else True,
            "elapsed_ms": elapsed_ms,
            "verified_at": round(time.time(), 3),
            "stage": stage,
        }

        with self._lock:
            self._stats["completed"] += 1
            if blocking:
                self._stats["syntax_catches"] += 1
            self._entries[(cid, nrepo, rel_path)] = entry
            self._mtime_cache[cache_key] = dict(entry)
            self._mtime_cache.move_to_end(cache_key)
            while len(self._mtime_cache) > 128:
                self._mtime_cache.popitem(last=False)
            self._recent.append({
                "conversation_id": cid,
                "file": rel_path,
                "ok": entry["ok"],
                "blocking": blocking,
                "diag_count": len(diags),
                "stage": stage,
                "elapsed_ms": elapsed_ms,
            })
        return entry

    def _refresh_if_stale(self, entry: dict[str, Any]) -> dict[str, Any]:
        """If file changed on disk since last check, re-run fast in-RAM syntax gate (< 2 ms)."""
        repo_p = Path(entry["repo"])
        fp = repo_p / entry["file"]
        if not fp.is_file():
            entry["blocking"] = False
            entry["ok"] = True
            entry["diagnostics"] = []
            return entry
        try:
            st = fp.stat()
            if int(st.st_mtime_ns) == int(entry.get("mtime_ns") or 0):
                return entry
            content = fp.read_text(encoding="utf-8", errors="replace")
            gate = syntax_gate_content(content, entry["file"], iron_cage=self.iron_cage)
            diags = list(gate.get("diagnostics") or [])
            blocking = any(str(d.get("severity") or "error").lower() == "error" for d in diags)
            entry["mtime_ns"] = int(st.st_mtime_ns)
            entry["diagnostics"] = diags
            entry["blocking"] = blocking
            entry["ok"] = not blocking
            if diags:
                entry["seen"] = False
        except OSError:
            pass
        return entry

    def consume_diagnostics(
        self,
        conversation_id: str,
        repo: str | Path | None = None,
    ) -> list[dict[str, Any]]:
        """Return unseen diagnostics for PreInvocation injection and mark them seen."""
        cid = str(conversation_id or "default")
        nrepo = _norm_repo(repo) if repo else None
        out: list[dict[str, Any]] = []
        with self._lock:
            for (ecid, erepo, _rel), entry in list(self._entries.items()):
                if ecid != cid:
                    continue
                if nrepo is not None and erepo != nrepo:
                    continue
                self._refresh_if_stale(entry)
                if not entry.get("seen") and entry.get("diagnostics"):
                    for d in entry["diagnostics"]:
                        out.append({
                            **d,
                            "repo": erepo,
                            "stage": entry.get("stage", "syntax_gate"),
                        })
                    entry["seen"] = True
        return out

    def get_blocking_errors(
        self,
        conversation_id: str,
        repo: str | Path | None = None,
    ) -> list[dict[str, Any]]:
        """Return all current blocking syntax/compile errors for files edited by conversation_id."""
        cid = str(conversation_id or "default")
        nrepo = _norm_repo(repo) if repo else None
        blocking_diags: list[dict[str, Any]] = []
        with self._lock:
            for (ecid, erepo, _rel), entry in list(self._entries.items()):
                if ecid != cid:
                    continue
                if nrepo is not None and erepo != nrepo:
                    continue
                self._refresh_if_stale(entry)
                if entry.get("blocking"):
                    for d in entry.get("diagnostics") or []:
                        if str(d.get("severity") or "error").lower() == "error":
                            blocking_diags.append({**d, "repo": erepo})
        return blocking_diags

    def has_blocking_errors(
        self,
        conversation_id: str,
        repo: str | Path | None = None,
    ) -> bool:
        """True if conversation_id has unresolved blocking syntax/compile errors."""
        return len(self.get_blocking_errors(conversation_id, repo)) > 0

    def status(self) -> dict[str, Any]:
        with self._lock:
            blocking_entries = sum(1 for e in self._entries.values() if e.get("blocking"))
            return {
                "ok": True,
                "inflight": self._inflight,
                "active_entries": len(self._entries),
                "blocking_count": blocking_entries,
                "stats": dict(self._stats),
                "recent": list(reversed(self._recent))[:12],
            }


def _find_matching_py_test(repo_root: Path, rel_path: str) -> Path | None:
    stem = Path(rel_path).stem
    if stem.startswith("test_"):
        cand = repo_root / rel_path
        return cand if cand.is_file() else None
    tests_dir = repo_root / "tests"
    if not tests_dir.is_dir():
        return None
    direct = tests_dir / f"test_{stem}.py"
    if direct.is_file():
        return direct
    return None


def _apply_candidate_edits(sandbox_root: Path, candidate: dict[str, Any]) -> list[str]:
    """Apply candidate `files` dict and/or `edits` list inside an isolated sandbox root."""
    touched: list[str] = []
    root_res = sandbox_root.resolve()

    def _safe_target(rel: str) -> Path:
        p = (sandbox_root / rel).resolve()
        if p != root_res and root_res not in p.parents:
            raise ValueError(f"path_escape_denied:{rel}")
        return p

    files_map = candidate.get("files")
    if isinstance(files_map, dict):
        for rel, content in files_map.items():
            tp = _safe_target(str(rel))
            tp.parent.mkdir(parents=True, exist_ok=True)
            tp.write_text(str(content), encoding="utf-8")
            touched.append(str(rel).replace("\\", "/"))

    edits = candidate.get("edits")
    if isinstance(edits, list):
        for ed in edits:
            if not isinstance(ed, dict):
                continue
            rel = str(ed.get("path") or "").strip()
            if not rel:
                continue
            tp = _safe_target(rel)
            if ed.get("delete"):
                if tp.exists():
                    tp.unlink()
            elif "content" in ed and ed["content"] is not None:
                tp.parent.mkdir(parents=True, exist_ok=True)
                tp.write_text(str(ed["content"]), encoding="utf-8")
            elif "old" in ed and "new" in ed:
                if not tp.is_file():
                    raise FileNotFoundError(f"edit_target_missing:{rel}")
                cur = tp.read_text(encoding="utf-8")
                old = str(ed["old"])
                new = str(ed["new"])
                if old not in cur:
                    raise ValueError(f"edit_target_not_found:{rel}")
                updated = cur.replace(old, new) if ed.get("replace_all") else cur.replace(old, new, 1)
                tp.write_text(updated, encoding="utf-8")
            touched.append(rel.replace("\\", "/"))
    return sorted(set(touched))


def _parse_oracle_metric(stdout: str, exit_code: int) -> dict[str, Any]:
    """Parse deterministic scorer JSON from oracle stdout (last JSON object wins)."""
    text = (stdout or "").strip()
    parsed: dict[str, Any] | None = None
    if text:
        try:
            obj = json.loads(text)
            if isinstance(obj, dict):
                parsed = obj
        except json.JSONDecodeError:
            for line in reversed(text.splitlines()):
                ln = line.strip()
                if not (ln.startswith("{") and ln.endswith("}")):
                    continue
                try:
                    obj = json.loads(ln)
                    if isinstance(obj, dict):
                        parsed = obj
                        break
                except json.JSONDecodeError:
                    continue

    if parsed is not None:
        passed = bool(parsed.get("pass", exit_code == 0))
        try:
            score = float(parsed.get("score", 1.0 if passed else 0.0))
        except (TypeError, ValueError):
            score = 1.0 if passed else 0.0
        return {"pass": passed, "score": score, "raw_metric": parsed}

    passed = exit_code == 0
    return {"pass": passed, "score": 1.0 if passed else 0.0, "raw_metric": None}


def _copy_filtered_sandbox(src_repo: Path, dst_dir: Path) -> None:
    """Fast filtered copy/hardlink sandbox skipping build/vendor/git dirs."""
    dst_dir.mkdir(parents=True, exist_ok=True)
    for root, dirs, files in os.walk(src_repo):
        dirs[:] = [d for d in dirs if d not in _SKIP_SANDBOX_DIRS]
        rel_root = Path(root).relative_to(src_repo)
        target_root = dst_dir / rel_root
        target_root.mkdir(parents=True, exist_ok=True)
        for fn in files:
            sp = Path(root) / fn
            dp = target_root / fn
            try:
                shutil.copy2(sp, dp)
            except OSError:
                try:
                    shutil.copyfile(sp, dp)
                except OSError:
                    pass


class ShadowTournament:
    """Isolated multi-candidate patch/algorithm arena with deterministic oracle scoring."""

    MAX_HISTORY = 32

    def __init__(self, *, iron_cage: IronCage | None = None) -> None:
        self.iron_cage = iron_cage or get_iron_cage()
        self._lock = threading.Lock()
        self._tournaments: collections.OrderedDict[str, dict[str, Any]] = collections.OrderedDict()
        self._total = 0

    def _prepare_sandbox(self, repo_path: Path, sandbox_dir: Path, isolation: str) -> str:
        use_wt = isolation == "worktree" or (isolation == "auto" and (repo_path / ".git").exists())
        if use_wt and shutil.which("git"):
            res = self.iron_cage.spawn_caged(
                ["git", "worktree", "add", "--detach", "--force", str(sandbox_dir), "HEAD"],
                cwd=repo_path,
                timeout_s=15.0,
            )
            if res.get("ok") and sandbox_dir.is_dir():
                return "git_worktree"
            if sandbox_dir.exists():
                shutil.rmtree(sandbox_dir, ignore_errors=True)
        _copy_filtered_sandbox(repo_path, sandbox_dir)
        return "filtered_copy"

    def _cleanup_sandbox(self, repo_path: Path, sandbox_dir: Path, mode: str) -> None:
        try:
            if mode == "git_worktree" and shutil.which("git"):
                self.iron_cage.spawn_caged(
                    ["git", "worktree", "remove", "--force", str(sandbox_dir)],
                    cwd=repo_path,
                    timeout_s=10.0,
                )
        finally:
            if sandbox_dir.exists():
                shutil.rmtree(sandbox_dir, ignore_errors=True)

    def run(
        self,
        repo: str | Path,
        candidates: list[dict[str, Any]],
        oracle_cmd: str | list[str] | None = None,
        *,
        timeout_s: float = 30.0,
        isolation: str = "auto",
    ) -> dict[str, Any]:
        """Execute 2-3+ competing candidates in isolated sandboxes and rank by oracle metrics."""
        repo_path = Path(repo).resolve()
        if not repo_path.is_dir():
            return {"ok": False, "error": f"repo_not_found:{repo_path}"}
        if not candidates or not isinstance(candidates, list):
            return {"ok": False, "error": "candidates_required"}
        if len(candidates) > 8:
            return {"ok": False, "error": "too_many_candidates_max_8"}

        t0 = time.perf_counter()
        tid = f"trn_{uuid.uuid4().hex[:10]}"
        results: list[dict[str, Any]] = []
        cand_specs: dict[str, dict[str, Any]] = {}

        for idx, raw_cand in enumerate(candidates):
            cand = dict(raw_cand) if isinstance(raw_cand, dict) else {}
            cname = str(cand.get("name") or f"cand_{idx + 1}")
            cmd = cand.get("cmd") or oracle_cmd
            if not cmd:
                results.append({
                    "name": cname,
                    "pass": False,
                    "score": float("-inf"),
                    "exit_code": -1,
                    "elapsed_ms": 0.0,
                    "error": "oracle_cmd_missing",
                })
                continue

            cand_specs[cname] = {
                "files": cand.get("files") if isinstance(cand.get("files"), dict) else None,
                "edits": cand.get("edits") if isinstance(cand.get("edits"), list) else None,
            }

            tmp_parent = Path(tempfile.mkdtemp(prefix=f"chimera_trn_{tid}_{idx}_"))
            sandbox_dir = tmp_parent / "ws"
            iso_mode = "filtered_copy"
            try:
                iso_mode = self._prepare_sandbox(repo_path, sandbox_dir, isolation=isolation)
                touched = _apply_candidate_edits(sandbox_dir, cand)
                run_res = self.iron_cage.spawn_caged(cmd, cwd=sandbox_dir, timeout_s=timeout_s)
                metric = _parse_oracle_metric(run_res.get("stdout", ""), int(run_res.get("exit_code", -1)))
                results.append({
                    "name": cname,
                    "pass": bool(metric["pass"]),
                    "score": float(metric["score"]),
                    "raw_metric": metric["raw_metric"],
                    "exit_code": int(run_res.get("exit_code", -1)),
                    "timed_out": bool(run_res.get("timed_out", False)),
                    "elapsed_ms": float(run_res.get("elapsed_ms", 0.0)),
                    "isolation": iso_mode,
                    "touched_files": touched,
                    "stdout_tail": (run_res.get("stdout") or "")[-600:],
                    "stderr_tail": (run_res.get("stderr") or "")[-400:],
                })
            except Exception as exc:
                results.append({
                    "name": cname,
                    "pass": False,
                    "score": float("-inf"),
                    "exit_code": -1,
                    "elapsed_ms": 0.0,
                    "isolation": iso_mode,
                    "error": str(exc),
                })
            finally:
                self._cleanup_sandbox(repo_path, sandbox_dir, iso_mode)
                shutil.rmtree(tmp_parent, ignore_errors=True)

        ranked = sorted(
            results,
            key=lambda r: (
                1 if r.get("pass") else 0,
                float(r.get("score") if r.get("score") != float("-inf") else -1e18),
                -float(r.get("elapsed_ms", 0.0)),
            ),
            reverse=True,
        )
        for rank_idx, r in enumerate(ranked, start=1):
            r["rank"] = rank_idx
            if r.get("score") == float("-inf"):
                r["score"] = 0.0

        winner = ranked[0] if (ranked and ranked[0].get("pass")) else None
        record = {
            "ok": True,
            "tournament_id": tid,
            "repo": str(repo_path).replace("\\", "/"),
            "candidates_count": len(ranked),
            "rankings": ranked,
            "winner": winner,
            "promoted": False,
            "promoted_at": None,
            "promoted_files": [],
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
            "created_at": round(time.time(), 3),
            "_specs": cand_specs,
        }
        with self._lock:
            self._total += 1
            self._tournaments[tid] = record
            self._tournaments.move_to_end(tid)
            while len(self._tournaments) > self.MAX_HISTORY:
                self._tournaments.popitem(last=False)

        return {k: v for k, v in record.items() if not k.startswith("_")}

    def promote_winner(self, tournament_id: str, *, force: bool = False) -> dict[str, Any]:
        """Atomically apply the winning candidate's edits to the real repository."""
        with self._lock:
            rec = self._tournaments.get(str(tournament_id))
        if rec is None:
            return {"ok": False, "error": f"tournament_not_found:{tournament_id}"}
        winner = rec.get("winner")
        if not winner:
            if not force or not rec.get("rankings"):
                return {"ok": False, "error": "no_passing_winner", "tournament_id": tournament_id}
            winner = rec["rankings"][0]

        wname = str(winner["name"])
        spec = (rec.get("_specs") or {}).get(wname) or {}
        repo_path = Path(rec["repo"])
        if not repo_path.is_dir():
            return {"ok": False, "error": f"repo_not_found:{repo_path}"}

        # Compute full target snapshot for atomic rollback safety
        target_rels: set[str] = set()
        if isinstance(spec.get("files"), dict):
            target_rels.update(str(k) for k in spec["files"].keys())
        if isinstance(spec.get("edits"), list):
            for ed in spec["edits"]:
                if isinstance(ed, dict) and ed.get("path"):
                    target_rels.add(str(ed["path"]))

        backups: dict[Path, bytes | None] = {}
        root_res = repo_path.resolve()
        for rel in target_rels:
            tp = (repo_path / rel).resolve()
            if tp != root_res and root_res not in tp.parents:
                return {"ok": False, "error": f"path_escape_denied:{rel}"}
            backups[tp] = tp.read_bytes() if tp.is_file() else None

        try:
            touched = _apply_candidate_edits(repo_path, spec)
            # Syntax gate check after staging; roll back if any edited file fails syntax
            gate_errors: list[dict[str, Any]] = []
            for rel in touched:
                tp = (repo_path / rel).resolve()
                if tp.is_file():
                    g = syntax_gate_content(tp.read_text(encoding="utf-8", errors="replace"), rel, iron_cage=self.iron_cage)
                    if not g["ok"]:
                        gate_errors.extend(g["diagnostics"])
            if gate_errors:
                raise ValueError(f"winner_syntax_gate_failed:{gate_errors[0].get('message')}")
        except Exception as exc:
            for tp, orig in backups.items():
                try:
                    if orig is None:
                        if tp.exists():
                            tp.unlink()
                    else:
                        tp.parent.mkdir(parents=True, exist_ok=True)
                        tp.write_bytes(orig)
                except OSError:
                    pass
            return {"ok": False, "rolled_back": True, "error": str(exc), "tournament_id": tournament_id}

        with self._lock:
            rec["promoted"] = True
            rec["promoted_at"] = round(time.time(), 3)
            rec["promoted_files"] = touched

        return {
            "ok": True,
            "tournament_id": tournament_id,
            "winner": wname,
            "score": winner.get("score"),
            "promoted_files": touched,
            "rolled_back": False,
        }

    def status(self) -> dict[str, Any]:
        with self._lock:
            recent = [
                {
                    "tournament_id": r["tournament_id"],
                    "repo": r["repo"],
                    "candidates_count": r["candidates_count"],
                    "winner": (r["winner"]["name"] if r.get("winner") else None),
                    "winner_score": (r["winner"]["score"] if r.get("winner") else None),
                    "promoted": bool(r.get("promoted")),
                    "elapsed_ms": r.get("elapsed_ms"),
                }
                for r in reversed(self._tournaments.values())
            ][:12]
            return {
                "ok": True,
                "tournaments_total": self._total,
                "stored_count": len(self._tournaments),
                "recent": recent,
            }


_DEFAULT_PRECOG_LOCK = threading.Lock()
_DEFAULT_PRECOG: PrecogVerifier | None = None
_DEFAULT_TOURNAMENT: ShadowTournament | None = None


def get_precog_verifier() -> PrecogVerifier:
    global _DEFAULT_PRECOG
    with _DEFAULT_PRECOG_LOCK:
        if _DEFAULT_PRECOG is None:
            _DEFAULT_PRECOG = PrecogVerifier()
        return _DEFAULT_PRECOG


def get_shadow_tournament() -> ShadowTournament:
    global _DEFAULT_TOURNAMENT
    with _DEFAULT_PRECOG_LOCK:
        if _DEFAULT_TOURNAMENT is None:
            _DEFAULT_TOURNAMENT = ShadowTournament()
        return _DEFAULT_TOURNAMENT
