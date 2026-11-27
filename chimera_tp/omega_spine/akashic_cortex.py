"""CHIMERA Omega-Spine: Akashic Symbol Cortex & Self-Evolving Immune Antibody Engine.

Backed by lightweight SQLite WAL (`~/.chimera/omega_akashic.sqlite` default or custom `db_path`):
- Symbol Capsules (< 1024 B each) with SHA-256 incremental stale invalidation on file edits.
- Self-Evolving Immune Antibodies automatically distilled when a failed tool invocation is
  resolved by a subsequent successful call within 5 steps on the same file or command family.
"""

from __future__ import annotations

from collections import deque
import fnmatch
import json
import os
from pathlib import Path
import re
import sqlite3
import threading
import time
from typing import Any


_MAX_CAPSULE_BYTES = 1023
_DEFAULT_ANTIBODY_TTL_S = 7.0 * 86400.0
_MAX_DISTILL_WINDOW_STEPS = 5

_CS_ERROR_RE = re.compile(r"\b(CS\d{4}|MSB\d{4}|NU\d{4})\b")
_PY_ERROR_RE = re.compile(
    r"\b(SyntaxError|IndentationError|ImportError|ModuleNotFoundError|TypeError|ValueError|"
    r"AttributeError|KeyError|NameError|FileNotFoundError|PermissionError|RuntimeError|"
    r"AssertionError|OSError|ZeroDivisionError)\b"
)
_WORD_RE = re.compile(r"[A-Za-z0-9_.-]{3,}")
_STOPWORDS: frozenset[str] = frozenset(
    {
        "the",
        "and",
        "for",
        "with",
        "from",
        "that",
        "this",
        "not",
        "are",
        "was",
        "were",
        "has",
        "have",
        "had",
        "error",
        "failed",
        "failure",
        "line",
        "file",
        "path",
        "command",
        "exit",
        "code",
        "returned",
        "running",
        "into",
        "when",
        "after",
        "before",
        "fixed",
        "via",
    }
)


def _norm_repo(repo: str) -> str:
    s = str(repo or "").strip().replace("\\", "/").rstrip("/")
    return s


def _norm_rel_path(rel_path: str) -> str:
    s = str(rel_path or "").strip().replace("\\", "/")
    while s.startswith("./"):
        s = s[2:]
    return s


def _extract_file_target(args: dict[str, Any]) -> str:
    if not isinstance(args, dict):
        return ""
    for k in ("path", "Path", "file", "file_path", "rel_path", "TargetFile", "target_file"):
        v = args.get(k)
        if isinstance(v, str) and v.strip():
            return _norm_rel_path(v)
    edits = args.get("edits")
    if isinstance(edits, list) and edits:
        first = edits[0]
        if isinstance(first, dict):
            for k in ("path", "file", "rel_path"):
                v = first.get(k)
                if isinstance(v, str) and v.strip():
                    return _norm_rel_path(v)
    return ""


def _extract_command_str(args: dict[str, Any]) -> str:
    if not isinstance(args, dict):
        return ""
    for k in ("cmd", "command", "CommandLine", "command_line", "script"):
        v = args.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
        if isinstance(v, list) and v:
            return " ".join(str(x) for x in v).strip()
    return ""


def _command_family(cmd: str) -> str:
    s = cmd.strip()
    if not s:
        return ""
    # Handle leading env assignments or quotes
    parts = re.split(r"[\s;&|]+", s)
    tokens = [p.strip("\"'") for p in parts if p.strip("\"'")]
    if not tokens:
        return ""
    exe = Path(tokens[0]).stem.lower()
    if exe in ("dotnet", "git", "npm", "pnpm", "yarn", "cargo", "go", "pip", "uv") and len(tokens) >= 2:
        sub = tokens[1].lower()
        if not sub.startswith("-"):
            return f"{exe}:{sub}"
    return exe


def _normalize_error_signature(error: str, cmd: str = "") -> str:
    err = str(error or "").strip()
    if not err:
        return "unknown_error"

    low = err.lower()
    # PowerShell 5.1 '&&' separator trap
    if "&&" in err and ("not a valid statement separator" in low or "token '&&'" in low or "unexpected token" in low):
        return "PS51:invalid-statement-separator-&&"

    # .NET / Roslyn compiler error code
    cs_m = _CS_ERROR_RE.search(err)
    if cs_m:
        code = cs_m.group(1)
        # Extract concise message after the code
        tail = err[cs_m.end() :].lstrip(": ")
        first_line = tail.splitlines()[0].strip() if tail else ""
        first_line = re.sub(r"\s+", " ", first_line)[:96]
        return f"{code}: {first_line}" if first_line else code

    # Python exception signature
    py_m = _PY_ERROR_RE.search(err)
    if py_m:
        exc = py_m.group(1)
        tail = err[py_m.end() :].lstrip(": ")
        first_line = tail.splitlines()[0].strip() if tail else ""
        first_line = re.sub(r"\s+", " ", first_line)[:96]
        return f"{exc}: {first_line}" if first_line else exc

    # General: pick first non-empty error line, strip volatile hex/line numbers
    lines = [ln.strip() for ln in err.splitlines() if ln.strip()]
    sig = lines[-1] if (len(lines) > 1 and "traceback" in lines[0].lower()) else (lines[0] if lines else err)
    sig = re.sub(r"0x[0-9a-fA-F]+", "0xADDR", sig)
    sig = re.sub(r"\s+", " ", sig).strip()
    return sig[:140]


def _synthesize_fix_hint(
    fail_rec: dict[str, Any],
    ok_tool: str,
    ok_args: dict[str, Any],
    ok_cmd: str,
    ok_file: str,
    diff_hint: str,
) -> str:
    hint = str(diff_hint or "").strip()
    if hint:
        return hint[:320]

    fail_cmd = fail_rec.get("cmd_str", "")
    error_sig = fail_rec.get("error_sig", "")

    if fail_cmd and ok_cmd:
        if "&&" in fail_cmd and "&&" not in ok_cmd and ";" in ok_cmd:
            return f"Use ';' instead of '&&' in PowerShell 5.1; working command: {ok_cmd[:160]}"
        if fail_cmd != ok_cmd:
            return f"Resolved '{error_sig[:60]}' by running: {ok_cmd[:180]}"

    if ok_file:
        return f"Resolved '{error_sig[:80]}' in {ok_file} via {ok_tool}"

    return f"Resolved '{error_sig[:80]}' via {ok_tool}"


def _derive_file_pattern(file_target: str, cmd_family: str, tool_name: str) -> str:
    if file_target:
        return file_target
    if cmd_family:
        return f"cmd:{cmd_family}"
    return f"tool:{tool_name}" if tool_name else "*"


def _families_match(fail_rec: dict[str, Any], ok_tool: str, ok_file: str, ok_cmd_family: str) -> bool:
    f_file = fail_rec.get("file_target", "")
    f_cmd = fail_rec.get("cmd_family", "")
    f_tool = fail_rec.get("tool_name", "")

    if f_file and ok_file:
        if f_file.lower() == ok_file.lower():
            return True
        if Path(f_file).name.lower() == Path(ok_file).name.lower():
            return True
    if f_cmd and ok_cmd_family:
        if f_cmd == ok_cmd_family:
            return True
        # Same root executable (e.g. `dotnet:build` -> `dotnet:test`, or `powershell` commands)
        if f_cmd.split(":")[0] == ok_cmd_family.split(":")[0]:
            return True
    if not f_file and not ok_file and not f_cmd and not ok_cmd_family and f_tool and f_tool == ok_tool:
        return True
    # Command failed, then same-repo edit succeeded? Wait: keep strict same file/command family!
    # Also allow PS51 command family where failing cmd had `&&` and succeeding cmd runs via same shell tool
    if f_tool == ok_tool and f_tool in ("run_command", "shell", "powershell", "bash") and f_cmd and ok_cmd_family:
        if "PS51:" in fail_rec.get("error_sig", ""):
            return True
    return False


class AkashicCortex:
    """SQLite WAL-backed symbol capsule store with SHA-256 invalidation and Self-Evolving Immune Antibodies."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        if db_path is None:
            env_path = os.environ.get("CHIMERA_AKASHIC_DB", "").strip()
            self.db_path = Path(env_path) if env_path else (Path.home() / ".chimera" / "omega_akashic.sqlite")
        else:
            self.db_path = Path(db_path)

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.db_path), timeout=5.0, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

        # Per-(conversation_id, repo) step counter & recent failures ring buffer
        self._step_counters: dict[tuple[str, str], int] = {}
        self._recent_failures: dict[tuple[str, str], deque[dict[str, Any]]] = {}

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.executescript(
                """
                PRAGMA journal_mode=WAL;
                PRAGMA synchronous=NORMAL;
                PRAGMA busy_timeout=3000;

                CREATE TABLE IF NOT EXISTS symbol_capsules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    repo TEXT NOT NULL,
                    rel_path TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    file_sha256 TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    invariants_json TEXT NOT NULL,
                    line_range TEXT NOT NULL DEFAULT '',
                    author TEXT NOT NULL DEFAULT '',
                    stale INTEGER NOT NULL DEFAULT 0,
                    byte_size INTEGER NOT NULL DEFAULT 0,
                    updated_at REAL NOT NULL,
                    UNIQUE(repo, rel_path, symbol)
                );
                CREATE INDEX IF NOT EXISTS idx_capsules_repo_path ON symbol_capsules(repo, rel_path);
                CREATE INDEX IF NOT EXISTS idx_capsules_stale ON symbol_capsules(stale);

                CREATE TABLE IF NOT EXISTS immune_antibodies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    error_sig TEXT NOT NULL,
                    fix_hint TEXT NOT NULL,
                    file_pattern TEXT NOT NULL,
                    tool_family TEXT NOT NULL DEFAULT '',
                    repo TEXT NOT NULL DEFAULT '',
                    confidence REAL NOT NULL DEFAULT 0.75,
                    hit_count INTEGER NOT NULL DEFAULT 0,
                    ttl REAL NOT NULL DEFAULT 604800.0,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    UNIQUE(error_sig, file_pattern)
                );
                CREATE INDEX IF NOT EXISTS idx_antibodies_expires ON immune_antibodies(expires_at);
                """
            )
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass

    @staticmethod
    def _bound_capsule_fields(
        repo: str,
        rel_path: str,
        file_sha256: str,
        symbol: str,
        summary: str,
        invariants: list[str],
        line_range: str,
        author: str,
    ) -> tuple[str, list[str], int]:
        """Ensure serialized capsule JSON stays strictly < 1024 bytes."""
        clean_inv = [str(x).strip() for x in (invariants or []) if str(x).strip()]
        clean_sum = str(summary or "").strip()

        def serialize_len(s: str, inv: list[str]) -> int:
            obj = {
                "repo": repo,
                "rel_path": rel_path,
                "file_sha256": file_sha256,
                "symbol": symbol,
                "summary": s,
                "invariants": inv,
                "line_range": line_range,
                "author": author,
                "stale": False,
                "byte_size": 999,
            }
            return len(json.dumps(obj, ensure_ascii=False).encode("utf-8"))

        # First cap invariants count & individual length if oversize
        if serialize_len(clean_sum, clean_inv) >= 1024:
            clean_inv = [item[:120] for item in clean_inv[:6]]
        while len(clean_inv) > 1 and serialize_len(clean_sum, clean_inv) >= 1024:
            clean_inv.pop()
        if clean_inv and serialize_len(clean_sum, clean_inv) >= 1024:
            clean_inv[0] = clean_inv[0][:80]
        if serialize_len(clean_sum, clean_inv) >= 1024 and len(clean_sum) > 40:
            # Binary search safe UTF-8 char length for summary
            lo, hi = 0, len(clean_sum)
            while lo < hi:
                mid = (lo + hi + 1) // 2
                cand = clean_sum[:mid].rstrip() + ("..." if mid < len(clean_sum) else "")
                if serialize_len(cand, clean_inv) <= _MAX_CAPSULE_BYTES:
                    lo = mid
                else:
                    hi = mid - 1
            clean_sum = clean_sum[:lo].rstrip() + ("..." if lo < len(clean_sum) else "")
        while clean_inv and serialize_len(clean_sum, clean_inv) >= 1024:
            clean_inv.pop()
        while clean_sum and serialize_len(clean_sum, clean_inv) >= 1024:
            clean_sum = clean_sum[:-8]

        final_size = serialize_len(clean_sum, clean_inv)
        return clean_sum, clean_inv, final_size

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
        """Store/upsert a bounded (< 1024 B) symbol capsule keyed by (repo, rel_path, symbol)."""
        n_repo = _norm_repo(repo)
        n_path = _norm_rel_path(rel_path)
        n_sym = str(symbol or "").strip()
        n_sha = str(file_sha256 or "").strip()
        n_lr = str(line_range or "").strip()[:48]
        n_auth = str(author or "").strip()[:64]

        bounded_sum, bounded_inv, byte_size = self._bound_capsule_fields(
            n_repo, n_path, n_sha, n_sym, summary, invariants, n_lr, n_auth
        )
        inv_json = json.dumps(bounded_inv, ensure_ascii=False)
        now = time.time()

        with self._lock:
            self._conn.execute(
                """
                INSERT INTO symbol_capsules
                    (repo, rel_path, symbol, file_sha256, summary, invariants_json, line_range, author, stale, byte_size, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
                ON CONFLICT(repo, rel_path, symbol) DO UPDATE SET
                    file_sha256 = excluded.file_sha256,
                    summary = excluded.summary,
                    invariants_json = excluded.invariants_json,
                    line_range = excluded.line_range,
                    author = excluded.author,
                    stale = 0,
                    byte_size = excluded.byte_size,
                    updated_at = excluded.updated_at
                """,
                (n_repo, n_path, n_sym, n_sha, bounded_sum, inv_json, n_lr, n_auth, byte_size, now),
            )
            self._conn.commit()

        return {
            "ok": True,
            "repo": n_repo,
            "rel_path": n_path,
            "file_sha256": n_sha,
            "symbol": n_sym,
            "summary": bounded_sum,
            "invariants": bounded_inv,
            "line_range": n_lr,
            "author": n_auth,
            "stale": False,
            "byte_size": byte_size,
            "updated_at": now,
        }

    def recall_for_files(
        self,
        repo: str,
        file_hashes: dict[str, str],
        limit: int = 8,
    ) -> list[dict[str, Any]]:
        """Return ONLY capsules whose file_sha256 matches current hash; auto-mark mismatched ones stale=1."""
        n_repo = _norm_repo(repo)
        if not file_hashes:
            return []
        norm_hashes = {_norm_rel_path(k): str(v or "").strip() for k, v in file_hashes.items()}
        paths = list(norm_hashes.keys())
        placeholders = ",".join("?" for _ in paths)

        fresh: list[dict[str, Any]] = []
        stale_ids: list[int] = []
        refresh_ids: list[int] = []

        with self._lock:
            rows = self._conn.execute(
                f"""
                SELECT id, repo, rel_path, symbol, file_sha256, summary, invariants_json,
                       line_range, author, stale, byte_size, updated_at
                FROM symbol_capsules
                WHERE repo = ? AND rel_path IN ({placeholders})
                ORDER BY updated_at DESC
                """,
                [n_repo, *paths],
            ).fetchall()

            for row in rows:
                expected_sha = norm_hashes.get(row["rel_path"], "")
                if expected_sha and row["file_sha256"] == expected_sha:
                    if int(row["stale"]) != 0:
                        refresh_ids.append(int(row["id"]))
                    if len(fresh) < max(1, int(limit)):
                        try:
                            invs = json.loads(row["invariants_json"])
                        except Exception:
                            invs = []
                        fresh.append(
                            {
                                "repo": row["repo"],
                                "rel_path": row["rel_path"],
                                "symbol": row["symbol"],
                                "file_sha256": row["file_sha256"],
                                "summary": row["summary"],
                                "invariants": invs,
                                "line_range": row["line_range"],
                                "author": row["author"],
                                "stale": False,
                                "byte_size": int(row["byte_size"]),
                                "updated_at": float(row["updated_at"]),
                            }
                        )
                else:
                    if int(row["stale"]) == 0:
                        stale_ids.append(int(row["id"]))

            if stale_ids:
                ph = ",".join("?" for _ in stale_ids)
                self._conn.execute(f"UPDATE symbol_capsules SET stale = 1 WHERE id IN ({ph})", stale_ids)
            if refresh_ids:
                ph = ",".join("?" for _ in refresh_ids)
                self._conn.execute(f"UPDATE symbol_capsules SET stale = 0 WHERE id IN ({ph})", refresh_ids)
            if stale_ids or refresh_ids:
                self._conn.commit()

        return fresh

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
        """Track recent failures per (conversation_id, repo); auto-distill an Immune Antibody
        when a subsequent call succeeds within 5 steps on the same file or command family.
        """
        conv = str(conversation_id or "default").strip()
        n_repo = _norm_repo(repo)
        key = (conv, n_repo)
        t_name = str(tool_name or "").strip()
        safe_args = args if isinstance(args, dict) else {}
        file_target = _extract_file_target(safe_args)
        cmd_str = _extract_command_str(safe_args)
        cmd_fam = _command_family(cmd_str)
        now = time.time()

        with self._lock:
            step = self._step_counters.get(key, 0) + 1
            self._step_counters[key] = step
            q = self._recent_failures.setdefault(key, deque(maxlen=16))

            if not ok:
                err_sig = _normalize_error_signature(error, cmd_str)
                q.append(
                    {
                        "step": step,
                        "tool_name": t_name,
                        "file_target": file_target,
                        "cmd_str": cmd_str,
                        "cmd_family": cmd_fam,
                        "error": str(error or ""),
                        "error_sig": err_sig,
                        "ts": now,
                    }
                )
                return None

            # ok == True: look for a matching recent failure within 5 steps
            matched_idx = -1
            for idx in range(len(q) - 1, -1, -1):
                rec = q[idx]
                delta = step - int(rec["step"])
                if delta > _MAX_DISTILL_WINDOW_STEPS:
                    continue
                if _families_match(rec, t_name, file_target, cmd_fam):
                    matched_idx = idx
                    break

            if matched_idx < 0:
                return None

            fail_rec = q[matched_idx]
            del q[matched_idx]

            error_sig = fail_rec["error_sig"]
            file_pattern = _derive_file_pattern(
                file_target or fail_rec["file_target"],
                cmd_fam or fail_rec["cmd_family"],
                t_name or fail_rec["tool_name"],
            )
            fix_hint = _synthesize_fix_hint(fail_rec, t_name, safe_args, cmd_str, file_target, diff_hint)
            tool_family = cmd_fam or fail_rec["cmd_family"] or t_name
            ttl = _DEFAULT_ANTIBODY_TTL_S
            expires_at = now + ttl

            existing = self._conn.execute(
                "SELECT id, confidence, hit_count, created_at FROM immune_antibodies WHERE error_sig = ? AND file_pattern = ?",
                (error_sig, file_pattern),
            ).fetchone()

            if existing is not None:
                new_conf = round(min(0.99, float(existing["confidence"]) + 0.10), 4)
                hit_count = int(existing["hit_count"])
                created_at = float(existing["created_at"])
                row_id = int(existing["id"])
                self._conn.execute(
                    """
                    UPDATE immune_antibodies
                    SET fix_hint = ?, tool_family = ?, repo = ?, confidence = ?,
                        ttl = ?, updated_at = ?, expires_at = ?
                    WHERE id = ?
                    """,
                    (fix_hint, tool_family, n_repo, new_conf, ttl, now, expires_at, row_id),
                )
            else:
                new_conf = 0.75
                hit_count = 0
                created_at = now
                cur = self._conn.execute(
                    """
                    INSERT INTO immune_antibodies
                        (error_sig, fix_hint, file_pattern, tool_family, repo, confidence, hit_count, ttl, created_at, updated_at, expires_at)
                    VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)
                    """,
                    (error_sig, fix_hint, file_pattern, tool_family, n_repo, new_conf, ttl, now, now, expires_at),
                )
                row_id = int(cur.lastrowid)

            self._conn.commit()

        return {
            "id": row_id,
            "error_sig": error_sig,
            "fix_hint": fix_hint,
            "file_pattern": file_pattern,
            "tool_family": tool_family,
            "repo": n_repo,
            "confidence": new_conf,
            "hit_count": hit_count,
            "ttl": ttl,
            "created_at": created_at,
            "updated_at": now,
            "expires_at": expires_at,
        }

    def match_antibodies(self, text_or_path: str, limit: int = 5) -> list[dict[str, Any]]:
        """Match active (non-expired) immune antibodies against text or path and bump hit_count."""
        query = str(text_or_path or "").strip()
        if not query:
            return []

        q_norm = query.replace("\\", "/").lower()
        q_basename = Path(q_norm).name if "/" in q_norm or "." in q_norm else q_norm
        q_tokens = {tok for tok in _WORD_RE.findall(q_norm) if tok not in _STOPWORDS}
        q_codes = {m.group(1).lower() for m in _CS_ERROR_RE.finditer(query)}
        q_py_codes = {m.group(1).lower() for m in _PY_ERROR_RE.finditer(query)}
        now = time.time()

        scored: list[tuple[float, dict[str, Any]]] = []
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT id, error_sig, fix_hint, file_pattern, tool_family, repo,
                       confidence, hit_count, ttl, created_at, updated_at, expires_at
                FROM immune_antibodies
                WHERE expires_at > ?
                ORDER BY confidence DESC, hit_count DESC, updated_at DESC
                """,
                (now,),
            ).fetchall()

            for row in rows:
                score = 0.0
                fp = str(row["file_pattern"] or "").replace("\\", "/").lower()
                esig = str(row["error_sig"] or "").lower()
                fhint = str(row["fix_hint"] or "").lower()
                tfam = str(row["tool_family"] or "").lower()

                # 1. File pattern / command family match
                if fp and fp != "*":
                    if fp.startswith("cmd:"):
                        cmd_tok = fp[4:]
                        root_cmd = cmd_tok.split(":")[0]
                        if cmd_tok.replace(":", " ") in q_norm:
                            score += 2.6
                        elif root_cmd and re.search(rf"\b{re.escape(root_cmd)}\b", q_norm):
                            score += 1.8
                    elif fp.startswith("tool:"):
                        tool_tok = fp[5:]
                        if tool_tok and tool_tok in q_norm:
                            score += 1.6
                    else:
                        fp_base = Path(fp).name
                        if q_norm == fp or q_norm.endswith("/" + fp) or fp.endswith("/" + q_norm):
                            score += 3.2
                        elif q_basename and fp_base and q_basename == fp_base:
                            score += 2.6
                        elif fnmatch.fnmatch(q_norm, fp) or fnmatch.fnmatch(q_basename, fp):
                            score += 2.4

                # 2. Error code / signature match
                if q_codes and any(c in esig for c in q_codes):
                    score += 3.5
                if q_py_codes and any(c in esig for c in q_py_codes):
                    score += 3.0
                if "&&" in query and "&&" in esig:
                    score += 3.2
                if len(esig) >= 5 and esig in q_norm:
                    score += 3.0
                elif len(q_norm) >= 5 and q_norm in esig:
                    score += 2.2

                # 3. Keyword overlap against error_sig + fix_hint + tool_family
                ab_tokens = {
                    tok
                    for tok in _WORD_RE.findall(f"{esig} {fhint} {tfam}")
                    if tok not in _STOPWORDS and len(tok) >= 4
                }
                overlap = q_tokens & ab_tokens
                if overlap:
                    score += min(2.4, 0.85 * len(overlap))

                if score >= 1.5:
                    scored.append((score, dict(row)))

            scored.sort(
                key=lambda item: (item[0], float(item[1]["confidence"]), int(item[1]["hit_count"])),
                reverse=True,
            )
            chosen = [item[1] for item in scored[: max(1, int(limit))]]

            if chosen:
                ids = [int(r["id"]) for r in chosen]
                ph = ",".join("?" for _ in ids)
                self._conn.execute(
                    f"UPDATE immune_antibodies SET hit_count = hit_count + 1, updated_at = ? WHERE id IN ({ph})",
                    [now, *ids],
                )
                self._conn.commit()
                for r in chosen:
                    r["hit_count"] = int(r["hit_count"]) + 1
                    r["updated_at"] = now

        return chosen

    def status(self) -> dict[str, Any]:
        """Return live telemetry: capsule count, stale count, active antibodies count, total hits."""
        now = time.time()
        with self._lock:
            cap_row = self._conn.execute(
                "SELECT COUNT(*) AS total, COALESCE(SUM(CASE WHEN stale != 0 THEN 1 ELSE 0 END), 0) AS stale_cnt FROM symbol_capsules"
            ).fetchone()
            ab_row = self._conn.execute(
                """
                SELECT
                    COALESCE(SUM(CASE WHEN expires_at > ? THEN 1 ELSE 0 END), 0) AS active_cnt,
                    COALESCE(SUM(hit_count), 0) AS total_hits
                FROM immune_antibodies
                """,
                (now,),
            ).fetchone()

        total_caps = int(cap_row["total"]) if cap_row else 0
        stale_cnt = int(cap_row["stale_cnt"]) if cap_row else 0
        active_ab = int(ab_row["active_cnt"]) if ab_row else 0
        total_hits = int(ab_row["total_hits"]) if ab_row else 0

        return {
            "ok": True,
            "db_path": str(self.db_path),
            "capsule_count": total_caps,
            "fresh_capsule_count": max(0, total_caps - stale_cnt),
            "stale_count": stale_cnt,
            "active_antibodies_count": active_ab,
            "total_antibody_hits": total_hits,
        }


_CORTEX_LOCK = threading.Lock()
_CORTEX_SINGLETON: AkashicCortex | None = None


def get_akashic_cortex(db_path: Path | str | None = None) -> AkashicCortex:
    """Return process-wide AkashicCortex singleton (or a dedicated instance when db_path is explicitly provided)."""
    global _CORTEX_SINGLETON
    if db_path is not None:
        return AkashicCortex(db_path=db_path)
    with _CORTEX_LOCK:
        if _CORTEX_SINGLETON is None:
            _CORTEX_SINGLETON = AkashicCortex()
        return _CORTEX_SINGLETON
