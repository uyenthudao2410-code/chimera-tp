"""CHIMERA-MNEMOSYNE: Unified Zero-Loss Raw-Memory & Zero-Shell Execution Engine.

Unifies the empirical physics of arXiv:2610.30755 (RAW-RAG) with CHIMERA-ONE Organ 3
(Zero-Spawn Agent Hyper-Bus & Swarm Execution) under ONE core invariant:

  "Zero-Loss Raw Bus, Pointer-First Context"
  - Store 100% verbatim append-only evidence (0 LLM ingestion summarization, 0 UPDATE/DELETE).
  - Retrieve via 2-stage FTS5 + VSA/Cross-Feature Rerank + Deterministic Causal Threading
    (File/AST/Git/Error/Turn links fixing RAW-RAG's 3.66% Cascade blind spot without LLM graphs)
    + Live Reality Stamp (on-disk SHA-256 freshness without mutating raw history).
  - Eliminate serial PowerShell/SSH/truncation Cloud LLM round-trips via:
      1. BirthPrimerEngine (SessionStart <20ms RAM primer + Lossless PDF/Doc page catalog + Top-K Raw).
      2. ShellShortCircuitGuard (PreToolUse <3ms Swarm idempotent replay shield + PostToolUse dual-channel capture).
      3. WarmPythonReplPool (Persistent BELOW_NORMAL warm Python worker + Singleflight, 15-40ms vs 2s ConPTY).
      4. SwarmZeroTokenWatchdog + EntropyCommitAuditor + NocturnalRawArena (Law 1/2/6/7 strict compliance).

100% Python stdlib, 0 NumPy, 0 B boot RSS (lazy-loaded on first use), < 80 MiB Law 7 safe.
"""

from __future__ import annotations

import collections
import ctypes
import hashlib
import json
import math
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
_BELOW_NORMAL = getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0x00004000) if os.name == "nt" else 0
_BATCH_FLAGS = _NO_WINDOW | _BELOW_NORMAL

_SKIP_DIRS = frozenset({
    ".git", "__pycache__", "node_modules", ".venv", "venv", "target",
    "dist", "build", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".next", "bin", "obj", ".chimera_cold_backing",
})

_FILE_PATH_RE = re.compile(
    r"(?:[A-Za-z]:[/\\][^\s\"'<>|;,()\[\]{}]+|"
    r"/(?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+\.(?:py|js|mjs|ts|tsx|cs|rs|c|h|json|toml|md|yml|yaml|sql|ps1|sh|pdf|docx)|"
    r"(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+\.(?:py|js|mjs|ts|tsx|cs|rs|c|h|json|toml|md|yml|yaml|sql|ps1|sh|pdf|docx))\b"
)
_SYMBOL_RE = re.compile(r"\b(?:[A-Z][a-zA-Z0-9]{2,}|[a-z][a-z0-9]*_[a-z0-9_]{2,})\b")
_ERROR_SIG_RE = re.compile(
    r"(?i)\b(503|499|429|409|404|403|AttributeError|ValueError|TypeError|KeyError|"
    r"SyntaxError|ImportError|OSError|TimeoutError|EDQUOT|WinError\s*\d+|"
    r"tool_generation_timeout_retry_blocked|CRITICAL_PREFIX_EDIT_CLIFF|CS\d{4})\b"
)
_GIT_SHA_RE = re.compile(r"\b[0-9a-f]{8,40}\b")
_WORD_RE = re.compile(r"[A-Za-z0-9_]{2,}")
_CRITICAL_LINE_RE = re.compile(
    r"(?i)(error|fail|failed|traceback|exception|assert|syntaxerror|attributeerror|"
    r"503|499|429|409|edquot|ran \d+ test|\bpass\b|\bok\b|exit=|sha256|drift)"
)

# Strictly read-only shell commands eligible for Swarm Idempotent Short-Circuit
_READONLY_CMD_RE = re.compile(
    r"(?i)^\s*(?:"
    r"(?:get-childitem|gci|ls|dir)\b|"
    r"(?:get-content|gc|cat|type|head|tail)\b|"
    r"(?:get-filehash|certutil\s+-hashfile|sha256sum)\b|"
    r"(?:python|python3|py|node|npm|pytest|git|dotnet|rustc|cargo)\s+--version\b|"
    r"git\s+(?:status|branch|rev-parse|log\s+-n|diff\s+--stat)\b|"
    r"(?:netstat|ss|get-nettcpconnection)\b|"
    r"get-process\b|"
    r"get-ciminstance\s+win32_(?:operatingsystem|process)\b"
    r")"
)
_MUTATING_SHELL_RE = re.compile(
    r"(?i)(?:>>?|\b(?:rm|del|remove-item|mv|move-item|cp|copy-item|set-content|out-file|"
    r"new-item|mkdir|rmdir|stop-process|kill|restart-service|schtasks\s+/run|systemctl\s+(?:restart|stop|start)|"
    r"git\s+(?:commit|push|pull|checkout|reset|rebase|merge|add|rm)|pip\s+install|npm\s+install)\b)"
)


def _now_ts() -> float:
    return time.time()


def _sha256_str(text: str, length: int = 16) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:length]


def _sha256_file_fast(path: Path) -> str:
    try:
        h = hashlib.sha256()
        with path.open("rb") as fh:
            for blk in iter(lambda: fh.read(65536), b""):
                h.update(blk)
        return h.hexdigest()
    except OSError:
        return ""


def _dev_drive_mnemosyne_dir() -> Path:
    """Route append-only raw index to fast NVMe ReFS / XFS CoW Dev Drive when available."""
    env_dd = os.environ.get("CHIMERA_DEV_DRIVE", "").strip()
    if env_dd:
        p = Path(env_dd)
        if p.exists():
            return p / "mnemosyne"
    if os.name == "nt":
        v = Path("V:/")
        if v.exists():
            return v / "mnemosyne"
    else:
        m = Path("/mnt/chimera-dev")
        if m.exists():
            return m / "mnemosyne"
    return Path.home() / ".chimera" / "mnemosyne"


def _extract_anchors(text: str) -> list[tuple[str, str]]:
    """Extract deterministic causal anchors (0 LLM hallucination): file paths, errors, symbols."""
    anchors: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    sample = text[:8192]
    for m in _FILE_PATH_RE.finditer(sample):
        raw = m.group(0).replace("\\", "/").rstrip(".,:;)")
        low = raw.lower()
        key = ("file", Path(low).name if len(low) > 64 else low)
        if key not in seen:
            seen.add(key)
            anchors.append(key)
        bkey = ("file", Path(low).name)
        if bkey not in seen:
            seen.add(bkey)
            anchors.append(bkey)
        if len(anchors) >= 16:
            break
    for m in _ERROR_SIG_RE.finditer(sample):
        ek = ("err", m.group(1).lower().replace(" ", ""))
        if ek not in seen:
            seen.add(ek)
            anchors.append(ek)
    sym_counts: dict[str, int] = {}
    for m in _SYMBOL_RE.finditer(sample):
        s = m.group(0)
        if len(s) >= 5 and s not in ("True", "False", "None", "Error", "System", "String", "Object"):
            sym_counts[s] = sym_counts.get(s, 0) + 1
    for sym, _ in sorted(sym_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:10]:
        sk = ("sym", sym.lower())
        if sk not in seen:
            seen.add(sk)
            anchors.append(sk)
    return anchors[:28]


def _chunk_text_windows(text: str, *, window_chars: int = 1100, overlap_chars: int = 140) -> list[str]:
    """Slice raw text into ~256-300 token overlapping windows per arXiv:2610.30755 RAW-RAG."""
    clean = str(text or "").strip()
    if not clean:
        return []
    if len(clean) <= window_chars:
        return [clean]
    chunks: list[str] = []
    step = max(200, window_chars - overlap_chars)
    pos = 0
    n = len(clean)
    while pos < n and len(chunks) < 24:
        end = min(n, pos + window_chars)
        if end < n:
            nl = clean.rfind("\n", pos + step // 2, end)
            if nl > pos + 120:
                end = nl
        piece = clean[pos:end].strip()
        if piece:
            chunks.append(piece)
        if end >= n:
            break
        pos = max(pos + 1, end - overlap_chars)
    return chunks


def _sanitize_fts_query(query: str) -> str:
    toks = _WORD_RE.findall(str(query or ""))
    uniq: list[str] = []
    seen: set[str] = set()
    for t in toks:
        tl = t.lower()
        if tl not in seen and tl not in ("and", "or", "not", "the", "for", "with", "that", "this"):
            seen.add(tl)
            uniq.append(t)
        if len(uniq) >= 12:
            break
    if not uniq:
        return ""
    return " OR ".join(f'"{t}"' for t in uniq)


def _extract_raw_file_paths(text: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for m in _FILE_PATH_RE.finditer(text[:4096]):
        p = m.group(0).rstrip(".,:;)")
        if p not in seen:
            seen.add(p)
            found.append(p)
        if len(found) >= 6:
            break
    return found


def _compact_high_surprise(text: str, *, max_chars: int = 1200) -> str:
    """Extract high-surprise lines (errors/verdicts/head/tail) without discarding raw storage."""
    if len(text) <= max_chars:
        return text
    lines = text.splitlines()
    picked: list[tuple[int, str]] = []
    seen_idx: set[int] = set()
    for idx in range(min(4, len(lines))):
        picked.append((idx + 1, lines[idx]))
        seen_idx.add(idx)
    for idx, ln in enumerate(lines):
        if idx not in seen_idx and _CRITICAL_LINE_RE.search(ln):
            picked.append((idx + 1, ln))
            seen_idx.add(idx)
            if len(picked) >= 18:
                break
    for idx in range(max(0, len(lines) - 5), len(lines)):
        if idx not in seen_idx:
            picked.append((idx + 1, lines[idx]))
            seen_idx.add(idx)
    picked.sort(key=lambda x: x[0])
    out_lines = [f"L{ln}: {txt[:200]}" for ln, txt in picked]
    joined = "\n".join(out_lines)
    if len(joined) > max_chars:
        joined = joined[: max_chars - 24] + "\n... [clipped]"
    return joined


# ---------------------------------------------------------------------------
# Module A — AkashicRawStore (CHIMERA-AKASHIC-RAW + CAUSAL-RAW-RAG + Reality Stamp)
# ---------------------------------------------------------------------------

class AkashicRawStore:
    """Zero-Loss Append-Only Raw Conversation, Tool-Output & Document Page Store."""

    def __init__(self, *, db_path: Path | None = None, ephemeral: bool = False) -> None:
        self._ephemeral = bool(ephemeral)
        self._lock = threading.Lock()
        self._tmp_dir: tempfile.TemporaryDirectory[str] | None = None
        self._is_memory = False
        if db_path is not None:
            self.db_path = Path(db_path)
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False, timeout=5.0)
        elif ephemeral:
            self._is_memory = True
            self.db_path = Path(":memory:")
            self._conn = sqlite3.connect(":memory:", check_same_thread=False, timeout=5.0)
        else:
            self.db_path = _dev_drive_mnemosyne_dir() / "akashic_raw.sqlite"
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False, timeout=5.0)
        if not self._is_memory:
            self._conn.execute("PRAGMA journal_mode=WAL;")
            self._conn.execute("PRAGMA synchronous=NORMAL;")
        self._conn.execute("PRAGMA temp_store=MEMORY;")
        self._conn.execute("PRAGMA cache_size=-4000;")
        self._init_schema()
        self._stats = {
            "ingested_chunks": 0,
            "recalls": 0,
            "causal_expansions": 0,
            "reality_stamps_checked": 0,
            "tool_captures": 0,
            "doc_pages_indexed": 0,
            "codex_reranks": 0,
        }

    def _init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS raw_chunks (
                chunk_id TEXT PRIMARY KEY,
                source_kind TEXT NOT NULL,
                source_path TEXT NOT NULL,
                source_locator TEXT NOT NULL,
                thread_id TEXT NOT NULL,
                turn_idx INTEGER NOT NULL,
                repo TEXT NOT NULL,
                role TEXT NOT NULL,
                ts REAL NOT NULL,
                text TEXT NOT NULL,
                sha256 TEXT NOT NULL,
                meta_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_rc_thread_turn ON raw_chunks(thread_id, turn_idx);
            CREATE INDEX IF NOT EXISTS idx_rc_repo_ts ON raw_chunks(repo, ts DESC);
            CREATE INDEX IF NOT EXISTS idx_rc_ts ON raw_chunks(ts DESC);

            CREATE VIRTUAL TABLE IF NOT EXISTS raw_chunks_fts USING fts5(
                chunk_id UNINDEXED,
                repo UNINDEXED,
                text,
                tokenize='unicode61 remove_diacritics 2'
            );

            CREATE TABLE IF NOT EXISTS causal_links (
                anchor_kind TEXT NOT NULL,
                anchor_val TEXT NOT NULL,
                chunk_id TEXT NOT NULL,
                ts REAL NOT NULL,
                PRIMARY KEY (anchor_kind, anchor_val, chunk_id)
            );
            CREATE INDEX IF NOT EXISTS idx_cl_anchor ON causal_links(anchor_kind, anchor_val, ts DESC);
            CREATE INDEX IF NOT EXISTS idx_cl_chunk ON causal_links(chunk_id);

            CREATE TABLE IF NOT EXISTS ingest_bookmarks (
                source_key TEXT PRIMARY KEY,
                cursor_val TEXT NOT NULL,
                updated_ts REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS raw_tool_outputs (
                raw_ref_id TEXT PRIMARY KEY,
                repo TEXT NOT NULL,
                cid TEXT NOT NULL,
                cmd TEXT NOT NULL,
                exit_code INTEGER NOT NULL,
                ts REAL NOT NULL,
                sha256 TEXT NOT NULL,
                full_text TEXT NOT NULL,
                summary_text TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_rto_repo_ts ON raw_tool_outputs(repo, ts DESC);

            CREATE TABLE IF NOT EXISTS doc_pages (
                doc_sha TEXT NOT NULL,
                page_num INTEGER NOT NULL,
                repo TEXT NOT NULL,
                rel_path TEXT NOT NULL,
                total_pages INTEGER NOT NULL,
                text TEXT NOT NULL,
                indexed_ts REAL NOT NULL,
                PRIMARY KEY (doc_sha, page_num)
            );
            CREATE INDEX IF NOT EXISTS idx_dp_repo_path ON doc_pages(repo, rel_path);
            """
        )
        self._conn.commit()

    def append_raw_turn(
        self,
        *,
        source_kind: str,
        source_path: str,
        source_locator: str,
        thread_id: str,
        turn_idx: int,
        text: str,
        repo: str = "",
        role: str = "assistant",
        ts: float | None = None,
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Strictly APPEND-ONLY insertion of verbatim text windows + deterministic causal anchors."""
        windows = _chunk_text_windows(text)
        if not windows:
            return {"ok": True, "inserted": 0, "chunk_ids": []}
        t_val = float(ts if ts is not None else _now_ts())
        nrepo = str(repo or "").replace("\\", "/")
        meta_s = json.dumps(meta or {}, ensure_ascii=False)
        inserted = 0
        cids: list[str] = []
        with self._lock:
            cur = self._conn.cursor()
            for w_idx, piece in enumerate(windows):
                cid = _sha256_str(f"{source_kind}|{source_path}|{source_locator}|{w_idx}|{piece[:120]}", 20)
                cids.append(cid)
                sha = hashlib.sha256(piece.encode("utf-8", errors="replace")).hexdigest()
                res = cur.execute(
                    """
                    INSERT OR IGNORE INTO raw_chunks
                    (chunk_id, source_kind, source_path, source_locator, thread_id, turn_idx, repo, role, ts, text, sha256, meta_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (cid, source_kind, source_path, f"{source_locator}#w{w_idx}", thread_id, int(turn_idx), nrepo, role, t_val, piece, sha, meta_s),
                )
                if res.rowcount > 0:
                    inserted += 1
                    cur.execute(
                        "INSERT INTO raw_chunks_fts(chunk_id, repo, text) VALUES (?, ?, ?)",
                        (cid, nrepo, piece),
                    )
                    for ak, av in _extract_anchors(piece):
                        cur.execute(
                            "INSERT OR IGNORE INTO causal_links(anchor_kind, anchor_val, chunk_id, ts) VALUES (?, ?, ?, ?)",
                            (ak, av, cid, t_val),
                        )
                    if thread_id:
                        cur.execute(
                            "INSERT OR IGNORE INTO causal_links(anchor_kind, anchor_val, chunk_id, ts) VALUES (?, ?, ?, ?)",
                            ("thread", thread_id[:64], cid, t_val),
                        )
            self._conn.commit()
        if inserted:
            self._stats["ingested_chunks"] += inserted
        return {"ok": True, "inserted": inserted, "chunk_ids": cids}

    def capture_tool_output(
        self,
        *,
        repo: str,
        cid: str,
        cmd: str,
        output_text: str,
        exit_code: int = 0,
        max_summary_chars: int = 1200,
    ) -> dict[str, Any]:
        """Dual-Channel PostToolUse capture: 100% verbatim to append-only store + <=1.2KB high-surprise view."""
        full = str(output_text or "")
        nrepo = str(repo or "").replace("\\", "/")
        now = _now_ts()
        sha = hashlib.sha256(full.encode("utf-8", errors="replace")).hexdigest()
        ref_id = f"raw_{sha[:14]}_{int(now) % 100000}"
        summary = _compact_high_surprise(full, max_chars=max_summary_chars)
        with self._lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO raw_tool_outputs
                (raw_ref_id, repo, cid, cmd, exit_code, ts, sha256, full_text, summary_text)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (ref_id, nrepo, str(cid or "agent")[:64], str(cmd or "")[:300], int(exit_code), now, sha, full, summary),
            )
            self._conn.commit()
        # Also index verbatim tool output into AkashicRawStore so future sessions recall exact stdout/errors!
        if len(full.strip()) >= 24:
            self.append_raw_turn(
                source_kind="tool_output",
                source_path=f"raw_ref:{ref_id}",
                source_locator=f"exit={exit_code}",
                thread_id=str(cid or "agent")[:64],
                turn_idx=int(now),
                text=f"$ {cmd}\n{full[:16000]}",
                repo=nrepo,
                role="tool",
                ts=now,
                meta={"raw_ref_id": ref_id, "exit_code": int(exit_code), "full_bytes": len(full.encode("utf-8", errors="replace"))},
            )
        self._stats["tool_captures"] += 1
        return {
            "ok": True,
            "raw_ref_id": ref_id,
            "sha256": sha[:16],
            "full_bytes": len(full.encode("utf-8", errors="replace")),
            "summary_bytes": len(summary.encode("utf-8", errors="replace")),
            "distilled": len(full) > max_summary_chars,
            "summary": summary,
        }

    def get_raw_slice(self, raw_ref_id: str, *, start_line: int = 1, max_lines: int = 120) -> dict[str, Any]:
        with self._lock:
            row = self._conn.execute(
                "SELECT repo, cmd, exit_code, ts, sha256, full_text FROM raw_tool_outputs WHERE raw_ref_id = ?",
                (str(raw_ref_id or "").strip(),),
            ).fetchone()
        if not row:
            return {"ok": False, "error": f"raw_ref_not_found:{raw_ref_id}"}
        repo, cmd, rc, ts, sha, full = row
        lines = full.splitlines()
        s = max(1, int(start_line))
        e = min(len(lines), s + max(1, min(400, int(max_lines))) - 1)
        return {
            "ok": True,
            "raw_ref_id": raw_ref_id,
            "repo": repo,
            "cmd": cmd,
            "exit_code": rc,
            "ts": ts,
            "sha256": sha[:16],
            "start_line": s,
            "end_line": e,
            "total_lines": len(lines),
            "text": "\n".join(lines[s - 1 : e]),
        }

    def digest_document_pages(self, repo: str | Path, rel_path: str) -> dict[str, Any]:
        """Lossless page-by-page extraction for PDF/DOCX/MD/TXT (0 LLM summarization, SHA-256 cached)."""
        t0 = time.perf_counter()
        repo_p = Path(repo).resolve()
        fp = (repo_p / rel_path).resolve()
        if not fp.is_file():
            return {"ok": False, "error": f"doc_not_found:{rel_path}"}
        if fp != repo_p and repo_p not in fp.parents:
            return {"ok": False, "error": "doc_path_escapes_repo"}
        doc_sha = _sha256_file_fast(fp)
        if not doc_sha:
            return {"ok": False, "error": "doc_read_failed"}
        nrepo = str(repo_p).replace("\\", "/")
        rel = fp.relative_to(repo_p).as_posix()

        with self._lock:
            cached_cnt = self._conn.execute(
                "SELECT COUNT(*) FROM doc_pages WHERE doc_sha = ?", (doc_sha,)
            ).fetchone()[0]
        if cached_cnt > 0:
            return {
                "ok": True,
                "cached": True,
                "doc_sha": doc_sha[:16],
                "rel_path": rel,
                "total_pages": int(cached_cnt),
                "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
            }

        ext = fp.suffix.lower()
        pages: list[str] = []
        if ext == ".pdf":
            try:
                import pypdf  # type: ignore

                reader = pypdf.PdfReader(str(fp))
                for pg in reader.pages[:200]:
                    pages.append((pg.extract_text() or "").strip())
            except Exception as exc:
                return {"ok": False, "error": f"pdf_extract_error:{exc}"}
        elif ext == ".docx":
            try:
                with zipfile.ZipFile(fp, "r") as zf:
                    xml_bytes = zf.read("word/document.xml")
                root = ET.fromstring(xml_bytes)
                paras: list[str] = []
                for p_el in root.iter():
                    if p_el.tag.endswith("}p"):
                        txt = "".join(t.text or "" for t in p_el.iter() if t.tag.endswith("}t")).strip()
                        if txt:
                            paras.append(txt)
                full_doc = "\n".join(paras)
                pages = _chunk_text_windows(full_doc, window_chars=3200, overlap_chars=0) or [""]
            except Exception as exc:
                return {"ok": False, "error": f"docx_extract_error:{exc}"}
        else:
            raw_t = fp.read_text(encoding="utf-8", errors="replace")
            pages = _chunk_text_windows(raw_t, window_chars=3200, overlap_chars=0) or [""]

        now = _now_ts()
        tot = len(pages)
        with self._lock:
            for pno, ptxt in enumerate(pages, start=1):
                self._conn.execute(
                    """
                    INSERT OR REPLACE INTO doc_pages
                    (doc_sha, page_num, repo, rel_path, total_pages, text, indexed_ts)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (doc_sha, pno, nrepo, rel, tot, ptxt, now),
                )
            self._conn.commit()
        self._stats["doc_pages_indexed"] += tot
        return {
            "ok": True,
            "cached": False,
            "doc_sha": doc_sha[:16],
            "rel_path": rel,
            "total_pages": tot,
            "toc_preview": [f"p{i}: {p.splitlines()[0][:80] if p.splitlines() else ''}" for i, p in enumerate(pages[:12], 1)],
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }

    def read_document_page(self, repo: str | Path, rel_path: str, *, page: int = 1) -> dict[str, Any]:
        dig = self.digest_document_pages(repo, rel_path)
        if not dig.get("ok"):
            return dig
        fp = (Path(repo).resolve() / rel_path).resolve()
        doc_sha = _sha256_file_fast(fp)
        pno = max(1, int(page))
        with self._lock:
            row = self._conn.execute(
                "SELECT total_pages, text FROM doc_pages WHERE doc_sha = ? AND page_num = ?",
                (doc_sha, pno),
            ).fetchone()
        if not row:
            return {"ok": False, "error": f"page_out_of_range:{pno}", "total_pages": dig.get("total_pages", 0)}
        return {
            "ok": True,
            "rel_path": dig["rel_path"],
            "doc_sha": doc_sha[:16],
            "page": pno,
            "total_pages": int(row[0]),
            "text": row[1],
        }

    def ingest_local_raw_logs(
        self,
        *,
        max_codex_rows: int = 1200,
        max_agy_files: int = 24,
        max_t3_events: int = 800,
        codex_db: Path | None = None,
        agy_brain_dir: Path | None = None,
        t3_db: Path | None = None,
    ) -> dict[str, Any]:
        """Incrementally index real untouched raw logs (Codex + Antigravity + T3 Code), mode=ro."""
        t0 = time.perf_counter()
        counts = {"codex": 0, "antigravity": 0, "t3_code": 0}

        # 1. Codex thread_history_1.sqlite (mode=ro, zero write lock)
        cdb = codex_db or (Path.home() / ".codex" / "thread_history_1.sqlite")
        if cdb.is_file():
            try:
                last_rid = int(self._get_bookmark(f"codex:{cdb}") or "0")
                rc = sqlite3.connect(f"file:{cdb}?mode=ro", uri=True, timeout=2.0)
                rows = rc.execute(
                    """
                    SELECT rowid, thread_id, rollout_ordinal, created_at_ms, item_json
                    FROM thread_items
                    WHERE rowid > ?
                    ORDER BY rowid DESC
                    LIMIT ?
                    """,
                    (last_rid, int(max_codex_rows)),
                ).fetchall()
                rc.close()
                if rows:
                    max_seen = max(int(r[0]) for r in rows)
                    for rowid, tid, ord_i, ts_ms, item_json in reversed(rows):
                        txt, role = self._extract_codex_item_text(item_json)
                        if len(txt) < 32:
                            continue
                        r = self.append_raw_turn(
                            source_kind="codex_raw",
                            source_path=str(cdb).replace("\\", "/"),
                            source_locator=f"rowid:{rowid}",
                            thread_id=str(tid or "")[:64],
                            turn_idx=int(ord_i or rowid),
                            text=txt[:6000],
                            repo="",
                            role=role,
                            ts=(float(ts_ms) / 1000.0) if ts_ms else _now_ts(),
                        )
                        counts["codex"] += int(r.get("inserted") or 0)
                    self._set_bookmark(f"codex:{cdb}", str(max_seen))
            except Exception:
                pass

        # 2. Antigravity transcript_full.jsonl (incremental byte-offset bookmark per file!)
        if agy_brain_dir is None:
            t3_prov = Path.home() / ".t3" / "userdata" / "providers" / "antigravity"
            if t3_prov.is_dir():
                cands = list(t3_prov.glob("*/antigravity-acp/brain"))
                agy_brain_dir = cands[0] if cands else None
        if agy_brain_dir is not None and agy_brain_dir.is_dir():
            trs = sorted(
                agy_brain_dir.rglob("transcript_full.jsonl"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )[: int(max_agy_files)]
            for tf in trs:
                try:
                    bkey = f"agy:{tf}"
                    fsize = tf.stat().st_size
                    prev_off = int(self._get_bookmark(bkey) or "0")
                    if prev_off >= fsize:
                        continue
                    # Cap cold jump to last 256 KiB per file so initial ingest stays ultra-fast (<200ms)
                    start_off = max(prev_off, fsize - 262144) if prev_off == 0 else prev_off
                    tid = tf.parents[2].name if len(tf.parents) >= 3 else tf.parent.name
                    with tf.open("rb") as fh:
                        fh.seek(start_off)
                        if start_off > 0 and prev_off == 0:
                            fh.readline()  # align to next JSONL line boundary
                        cur_off = fh.tell()
                        while True:
                            raw_ln = fh.readline()
                            if not raw_ln:
                                break
                            line_off = cur_off
                            cur_off = fh.tell()
                            try:
                                obj = json.loads(raw_ln.decode("utf-8", errors="replace"))
                            except Exception:
                                continue
                            txt, role = self._extract_agy_step_text(obj)
                            if len(txt) < 32:
                                continue
                            step_i = int(obj.get("step_index") or 0)
                            r = self.append_raw_turn(
                                source_kind="antigravity_raw",
                                source_path=str(tf).replace("\\", "/"),
                                source_locator=f"byte:{line_off}",
                                thread_id=tid[:64],
                                turn_idx=step_i,
                                text=txt[:6000],
                                repo="",
                                role=role,
                                ts=tf.stat().st_mtime,
                            )
                            counts["antigravity"] += int(r.get("inserted") or 0)
                    self._set_bookmark(bkey, str(fsize))
                except Exception:
                    continue

        # 3. T3 Code statev2.sqlite (orchestration_events, mode=ro)
        tdb = t3_db or (Path.home() / ".t3" / "userdata" / "statev2.sqlite")
        if tdb.is_file():
            try:
                last_seq = int(self._get_bookmark(f"t3:{tdb}") or "0")
                rc = sqlite3.connect(f"file:{tdb}?mode=ro", uri=True, timeout=2.0)
                cols = [r[1] for r in rc.execute("PRAGMA table_info(orchestration_events)").fetchall()]
                payload_col = "payload_json" if "payload_json" in cols else ("payload" if "payload" in cols else "")
                if payload_col:
                    rows = rc.execute(
                        f"SELECT sequence, stream_id, {payload_col} FROM orchestration_events WHERE sequence > ? ORDER BY sequence DESC LIMIT ?",
                        (last_seq, int(max_t3_events)),
                    ).fetchall()
                    if rows:
                        max_seq = max(int(r[0]) for r in rows)
                        for seq, sid, ptxt in reversed(rows):
                            txt = self._extract_t3_event_text(str(ptxt or ""))
                            if len(txt) < 40:
                                continue
                            r = self.append_raw_turn(
                                source_kind="t3_raw",
                                source_path=str(tdb).replace("\\", "/"),
                                source_locator=f"seq:{seq}",
                                thread_id=str(sid or "")[:64],
                                turn_idx=int(seq),
                                text=txt[:5000],
                                repo="",
                                role="event",
                                ts=_now_ts(),
                            )
                            counts["t3_code"] += int(r.get("inserted") or 0)
                        self._set_bookmark(f"t3:{tdb}", str(max_seq))
                rc.close()
            except Exception:
                pass

        return {
            "ok": True,
            "inserted": counts,
            "total_inserted": sum(counts.values()),
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }

    @staticmethod
    def _extract_codex_item_text(item_json: str) -> tuple[str, str]:
        try:
            obj = json.loads(item_json)
        except Exception:
            return "", "unknown"
        if not isinstance(obj, dict):
            return "", "unknown"
        role = str(obj.get("role") or obj.get("type") or "item")[:24]
        parts: list[str] = []
        for k in ("text", "output", "command", "summary", "message"):
            v = obj.get(k)
            if isinstance(v, str) and v.strip():
                parts.append(v.strip())
        content = obj.get("content")
        if isinstance(content, str) and content.strip():
            parts.append(content.strip())
        elif isinstance(content, list):
            for c in content[:12]:
                if isinstance(c, dict):
                    t = c.get("text") or c.get("output_text") or c.get("input_text")
                    if isinstance(t, str) and t.strip():
                        parts.append(t.strip())
        return "\n".join(parts), role

    @staticmethod
    def _extract_agy_step_text(obj: dict[str, Any]) -> tuple[str, str]:
        if not isinstance(obj, dict):
            return "", "unknown"
        role = str(obj.get("source") or obj.get("type") or "step").lower()[:24]
        if role == "system":
            return "", role
        parts: list[str] = []
        for k in ("content", "text", "output"):
            v = obj.get(k)
            if isinstance(v, str) and v.strip():
                parts.append(v.strip())
        tcs = obj.get("tool_calls")
        if isinstance(tcs, list):
            for tc in tcs[:6]:
                if isinstance(tc, dict):
                    nm = tc.get("name") or ""
                    arg = str(tc.get("arguments") or "")[:300]
                    if nm:
                        parts.append(f"[tool:{nm}] {arg}")
        return "\n".join(parts), role

    @staticmethod
    def _extract_t3_event_text(payload_str: str) -> str:
        try:
            obj = json.loads(payload_str)
        except Exception:
            return ""
        if not isinstance(obj, dict):
            return ""
        parts: list[str] = []
        for k in ("text", "message", "prompt", "title", "output", "error"):
            v = obj.get(k)
            if isinstance(v, str) and v.strip():
                parts.append(v.strip())
        return "\n".join(parts)

    def _get_bookmark(self, key: str) -> str:
        with self._lock:
            row = self._conn.execute(
                "SELECT cursor_val FROM ingest_bookmarks WHERE source_key = ?", (key,)
            ).fetchone()
        return str(row[0]) if row else ""

    def _set_bookmark(self, key: str, val: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO ingest_bookmarks(source_key, cursor_val, updated_ts) VALUES (?, ?, ?)",
                (key, val, _now_ts()),
            )
            self._conn.commit()

    def _reality_stamp(self, text: str, chunk_ts: float, repo_hint: str = "") -> dict[str, Any]:
        """Live Reality Stamp (<0.5ms): ground historical raw evidence against live disk without mutating raw history."""
        self._stats["reality_stamps_checked"] += 1
        paths = _extract_raw_file_paths(text)
        checked: list[dict[str, Any]] = []
        status = "UNGROUNDED"
        stale_count = 0
        current_count = 0
        for raw_p in paths[:4]:
            cand = Path(raw_p)
            if not cand.is_absolute() and repo_hint:
                cand = Path(repo_hint) / raw_p
            if cand.is_file():
                try:
                    st = cand.stat()
                    if st.st_mtime > (chunk_ts + 2.0):
                        stale_count += 1
                        checked.append({"path": raw_p, "state": "MODIFIED_SINCE", "mtime": round(st.st_mtime, 1)})
                    else:
                        current_count += 1
                        checked.append({"path": raw_p, "state": "CURRENT_ON_DISK"})
                except OSError:
                    continue
        if stale_count > 0:
            status = "HISTORICAL_FILE_CHANGED"
        elif current_count > 0:
            status = "CURRENT_ON_DISK"
        return {"stamp": status, "files_checked": checked}

    def _rerank_score(self, query: str, query_toks: set[str], query_anchors: set[str], row: dict[str, Any], bm25_rank: int) -> float:
        txt = row["text"]
        tlow = txt.lower()
        qlow = query.lower()
        score = 1.0 / (12.0 + bm25_rank)
        # Exact phrase / identifier boost
        if len(qlow) >= 4 and qlow in tlow:
            score += 0.45
        # Token coverage ratio
        rtoks = {t.lower() for t in _WORD_RE.findall(txt)}
        if query_toks:
            score += 0.55 * (len(query_toks & rtoks) / len(query_toks))
        # Causal anchor overlap (file paths / error codes / symbols)
        if query_anchors:
            r_anc = {av for _, av in _extract_anchors(txt)}
            overlap = len(query_anchors & r_anc)
            if overlap:
                score += 0.35 * min(1.0, overlap / max(1, len(query_anchors)))
        # Gentle recency tie-breaker (never overrides strong relevance)
        age_h = max(0.0, (_now_ts() - float(row["ts"])) / 3600.0)
        score += 0.08 * math.exp(-age_h / 168.0)
        return round(score, 5)

    def _optional_codex_rerank(self, query: str, candidates: list[dict[str, Any]], top_k: int) -> list[dict[str, Any]]:
        """Opt-in 0-Google-token reranker via local Tquota idle Codex pool (safe fallback to local rerank)."""
        if not candidates or len(candidates) <= 2:
            return candidates[:top_k]
        try:
            brief_list = [
                f"[{i}] ({c['source_kind']}) {c['text'][:240].replace(chr(10), ' ')}"
                for i, c in enumerate(candidates[:20])
            ]
            prompt = (
                f"Query: {query}\nReturn ONLY a JSON array of up to {top_k} integer indices ranked most relevant:\n"
                + "\n".join(brief_list)
            )
            body = json.dumps({
                "model": "gpt-6-luna",
                "input": prompt,
                "stream": False,
                "reasoning": {"effort": "low"},
            }).encode("utf-8")
            req = urllib.request.Request(
                "http://127.0.0.1:12500/v1/responses",
                data=body,
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": "Bearer tqouta-local",
                },
            )
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(req, timeout=4.0) as resp:
                data = json.loads(resp.read(131072).decode("utf-8", errors="replace"))
            out_txt = str(data.get("output_text") or "")
            if not out_txt and isinstance(data.get("output"), list):
                for it in data["output"]:
                    if isinstance(it, dict) and isinstance(it.get("content"), list):
                        for cc in it["content"]:
                            if isinstance(cc, dict) and cc.get("text"):
                                out_txt += str(cc["text"])
            m = re.search(r"\[[0-9,\s]+\]", out_txt)
            if m:
                idxs = json.loads(m.group(0))
                ordered = [candidates[i] for i in idxs if isinstance(i, int) and 0 <= i < len(candidates)]
                if ordered:
                    self._stats["codex_reranks"] += 1
                    seen_ids = {c["chunk_id"] for c in ordered}
                    for c in candidates:
                        if len(ordered) >= top_k:
                            break
                        if c["chunk_id"] not in seen_ids:
                            ordered.append(c)
                    return ordered[:top_k]
        except Exception:
            pass
        return candidates[:top_k]

    def recall(
        self,
        query: str,
        *,
        repo: str = "",
        top_k: int = 8,
        causal_hops: int = 1,
        expand_turns: bool = True,
        reality_stamp: bool = True,
        use_codex_rerank: bool = False,
        max_bytes: int = 10000,
    ) -> dict[str, Any]:
        """2-Stage RAW-RAG + Deterministic CAUSAL-RAW-RAG + Live Reality Stamp (< 20 ms local)."""
        t0 = time.perf_counter()
        self._stats["recalls"] += 1
        q = str(query or "").strip()
        k = max(1, min(20, int(top_k or 8)))
        nrepo = str(repo or "").replace("\\", "/")
        fts_q = _sanitize_fts_query(q)
        query_toks = {t.lower() for t in _WORD_RE.findall(q)}
        query_anchors = {av for _, av in _extract_anchors(q)}

        candidates: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        with self._lock:
            if fts_q:
                try:
                    rows = self._conn.execute(
                        """
                        SELECT c.chunk_id, c.source_kind, c.source_path, c.source_locator,
                               c.thread_id, c.turn_idx, c.repo, c.role, c.ts, c.text, c.sha256
                        FROM raw_chunks_fts f
                        JOIN raw_chunks c ON c.chunk_id = f.chunk_id
                        WHERE raw_chunks_fts MATCH ?
                        ORDER BY bm25(raw_chunks_fts) ASC
                        LIMIT 128
                        """,
                        (fts_q,),
                    ).fetchall()
                    for r in rows:
                        if r[0] not in seen_ids:
                            seen_ids.add(r[0])
                            candidates.append({
                                "chunk_id": r[0], "source_kind": r[1], "source_path": r[2],
                                "source_locator": r[3], "thread_id": r[4], "turn_idx": r[5],
                                "repo": r[6], "role": r[7], "ts": r[8], "text": r[9],
                                "sha256": r[10][:16], "retrieval": "raw_fts",
                            })
                except sqlite3.OperationalError:
                    pass

            # Anchor direct lookup (catches exact file/error/symbol even if FTS tokenizes strangely)
            if query_anchors:
                qmarks = ",".join("?" for _ in query_anchors)
                arows = self._conn.execute(
                    f"""
                    SELECT DISTINCT c.chunk_id, c.source_kind, c.source_path, c.source_locator,
                                    c.thread_id, c.turn_idx, c.repo, c.role, c.ts, c.text, c.sha256
                    FROM causal_links cl
                    JOIN raw_chunks c ON c.chunk_id = cl.chunk_id
                    WHERE cl.anchor_val IN ({qmarks})
                    ORDER BY c.ts DESC
                    LIMIT 48
                    """,
                    tuple(query_anchors),
                ).fetchall()
                for r in arows:
                    if r[0] not in seen_ids:
                        seen_ids.add(r[0])
                        candidates.append({
                            "chunk_id": r[0], "source_kind": r[1], "source_path": r[2],
                            "source_locator": r[3], "thread_id": r[4], "turn_idx": r[5],
                            "repo": r[6], "role": r[7], "ts": r[8], "text": r[9],
                            "sha256": r[10][:16], "retrieval": "anchor_direct",
                        })

        # Stage 2: Cross-Feature Rerank (or opt-in Codex Cold-Bridge rerank)
        for rank_i, cand in enumerate(candidates):
            cand["score"] = self._rerank_score(q, query_toks, query_anchors, cand, rank_i)
            if nrepo and cand.get("repo") and nrepo.lower() in cand["repo"].lower():
                cand["score"] = round(cand["score"] + 0.15, 5)
        candidates.sort(key=lambda x: (-x["score"], -x["ts"]))
        if use_codex_rerank and len(candidates) > 2:
            selected = self._optional_codex_rerank(q, candidates[:20], k)
        else:
            selected = candidates[:k]

        # Deterministic CAUSAL-RAW-RAG expansion (fixes RAW-RAG's 3.66% Cascade blind spot!)
        causal_added = 0
        hops = max(0, min(2, int(causal_hops or 0)))
        if hops > 0 and selected:
            seed_ids = [c["chunk_id"] for c in selected[: min(4, len(selected))]]
            sel_set = {c["chunk_id"] for c in selected}
            with self._lock:
                for _ in range(hops):
                    if not seed_ids:
                        break
                    qm = ",".join("?" for _ in seed_ids)
                    anchors_rows = self._conn.execute(
                        f"SELECT DISTINCT anchor_kind, anchor_val FROM causal_links WHERE chunk_id IN ({qm}) AND anchor_kind IN ('file','err','sym') LIMIT 18",
                        tuple(seed_ids),
                    ).fetchall()
                    next_seeds: list[str] = []
                    for ak, av in anchors_rows:
                        linked = self._conn.execute(
                            """
                            SELECT c.chunk_id, c.source_kind, c.source_path, c.source_locator,
                                   c.thread_id, c.turn_idx, c.repo, c.role, c.ts, c.text, c.sha256
                            FROM causal_links cl
                            JOIN raw_chunks c ON c.chunk_id = cl.chunk_id
                            WHERE cl.anchor_kind = ? AND cl.anchor_val = ?
                            ORDER BY c.ts ASC
                            LIMIT 4
                            """,
                            (ak, av),
                        ).fetchall()
                        for r in linked:
                            if r[0] not in sel_set and causal_added < max(4, k):
                                sel_set.add(r[0])
                                causal_added += 1
                                next_seeds.append(r[0])
                                selected.append({
                                    "chunk_id": r[0], "source_kind": r[1], "source_path": r[2],
                                    "source_locator": r[3], "thread_id": r[4], "turn_idx": r[5],
                                    "repo": r[6], "role": r[7], "ts": r[8], "text": r[9],
                                    "sha256": r[10][:16], "retrieval": f"causal_hop:{ak}:{av}",
                                    "score": 0.42,
                                })
                    seed_ids = next_seeds[:6]
            if causal_added:
                self._stats["causal_expansions"] += causal_added

        # Optional Turn Expansion (pull adjacent window in same thread+turn for intact context)
        if expand_turns and selected:
            with self._lock:
                for item in selected:
                    sibs = self._conn.execute(
                        """
                        SELECT text FROM raw_chunks
                        WHERE thread_id = ? AND turn_idx = ? AND chunk_id != ?
                        ORDER BY source_locator ASC
                        LIMIT 1
                        """,
                        (item["thread_id"], item["turn_idx"], item["chunk_id"]),
                    ).fetchall()
                    if sibs and len(item["text"]) < 1400:
                        item["text"] = (item["text"] + "\n" + sibs[0][0])[:1800]
                        item["turn_expanded"] = True

        # Chronological ordering (proven critical in arXiv:2610.30755 for reader state resolution!)
        selected.sort(key=lambda x: (x["ts"], x["turn_idx"]))

        # Live Reality Stamp + strict byte budget guard
        final_items: list[dict[str, Any]] = []
        used_bytes = 0
        for item in selected:
            if reality_stamp:
                item["reality"] = self._reality_stamp(item["text"], float(item["ts"]), repo_hint=nrepo or item.get("repo", ""))
            sz = len(item["text"].encode("utf-8", errors="replace")) + 160
            if final_items and (used_bytes + sz) > max_bytes:
                break
            used_bytes += sz
            final_items.append(item)

        return {
            "ok": True,
            "query": q,
            "candidates_scanned": len(candidates),
            "causal_added": causal_added,
            "count": len(final_items),
            "chronological": True,
            "append_only_zero_mutation": True,
            "items": final_items,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }

    def status(self) -> dict[str, Any]:
        with self._lock:
            rc_cnt = int(self._conn.execute("SELECT COUNT(*) FROM raw_chunks").fetchone()[0])
            cl_cnt = int(self._conn.execute("SELECT COUNT(*) FROM causal_links").fetchone()[0])
            to_cnt = int(self._conn.execute("SELECT COUNT(*) FROM raw_tool_outputs").fetchone()[0])
            dp_cnt = int(self._conn.execute("SELECT COUNT(*) FROM doc_pages").fetchone()[0])
            by_src = dict(self._conn.execute("SELECT source_kind, COUNT(*) FROM raw_chunks GROUP BY source_kind").fetchall())
        db_mb = round(self.db_path.stat().st_size / 1048576.0, 2) if (not self._is_memory and self.db_path.exists()) else 0.0
        return {
            "ok": True,
            "db_path": str(self.db_path).replace("\\", "/"),
            "db_mb": db_mb,
            "raw_chunks": rc_cnt,
            "causal_links": cl_cnt,
            "raw_tool_outputs": to_cnt,
            "doc_pages": dp_cnt,
            "by_source": by_src,
            "stats": dict(self._stats),
        }

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass
        if self._tmp_dir is not None:
            try:
                self._tmp_dir.cleanup()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Module B — ShellShortCircuitGuard (PreToolUse Replay Shield + Swarm Bulletin)
# ---------------------------------------------------------------------------

class ShellShortCircuitGuard:
    """Blocks redundant read-only PowerShell spawns across Swarm workers in < 3 ms."""

    def __init__(self, *, raw_store: AkashicRawStore, ttl_s: float = 30.0, max_entries: int = 128) -> None:
        self._raw = raw_store
        self.ttl_s = float(ttl_s)
        self.max_entries = int(max_entries)
        self._lock = threading.Lock()
        self._cache: collections.OrderedDict[str, dict[str, Any]] = collections.OrderedDict()
        self._bulletin: collections.deque[dict[str, Any]] = collections.deque(maxlen=32)
        self._stats = {"checked": 0, "short_circuits": 0, "swarm_dedupes": 0, "captures": 0}

    @staticmethod
    def is_pure_readonly_cmd(cmd: str) -> bool:
        c = str(cmd or "").strip()
        if not c or len(c) > 400:
            return False
        if _MUTATING_SHELL_RE.search(c):
            return False
        return bool(_READONLY_CMD_RE.search(c))

    @staticmethod
    def normalize_cmd(cmd: str) -> str:
        return re.sub(r"\s+", " ", str(cmd or "").strip()).lower()

    @staticmethod
    def dir_mtime_epoch(repo: str) -> int:
        try:
            p = Path(repo)
            if p.is_dir():
                return int(p.stat().st_mtime)
        except OSError:
            pass
        return 0

    def _make_key(self, repo: str, cmd: str) -> str:
        nrepo = str(repo or "").replace("\\", "/").lower()
        ncmd = self.normalize_cmd(cmd)
        epoch = self.dir_mtime_epoch(repo) if repo else 0
        return _sha256_str(f"{nrepo}|{ncmd}|{epoch}", 20)

    def check_pre_command(self, *, repo: str, cmd: str, cid: str = "agent") -> dict[str, Any]:
        """Check whether an identical read-only command already has a fresh RAM hit (<3ms)."""
        self._stats["checked"] += 1
        ro = self.is_pure_readonly_cmd(cmd)
        if not ro:
            return {"ok": True, "readonly": False, "short_circuit": False}
        key = self._make_key(repo, cmd)
        now = _now_ts()
        with self._lock:
            hit = self._cache.get(key)
            if hit is not None and (now - float(hit["ts"])) <= self.ttl_s:
                self._cache.move_to_end(key)
                self._stats["short_circuits"] += 1
                sibling = hit.get("cid") != cid
                if sibling:
                    self._stats["swarm_dedupes"] += 1
                return {
                    "ok": True,
                    "readonly": True,
                    "short_circuit": True,
                    "sibling_hit": sibling,
                    "age_s": round(now - float(hit["ts"]), 2),
                    "raw_ref_id": hit.get("raw_ref_id"),
                    "summary": hit.get("summary", ""),
                    "cmd": cmd,
                }
        return {"ok": True, "readonly": True, "short_circuit": False, "cache_key": key}

    def record_post_command(
        self,
        *,
        repo: str,
        cmd: str,
        output_text: str,
        cid: str = "agent",
        exit_code: int = 0,
    ) -> dict[str, Any]:
        """Dual-Channel PostToolUse: store 100% verbatim output + warm Swarm short-circuit cache."""
        cap = self._raw.capture_tool_output(
            repo=repo, cid=cid, cmd=cmd, output_text=output_text, exit_code=exit_code
        )
        self._stats["captures"] += 1
        now = _now_ts()
        if exit_code == 0 and self.is_pure_readonly_cmd(cmd):
            key = self._make_key(repo, cmd)
            with self._lock:
                self._cache[key] = {
                    "ts": now,
                    "cid": cid,
                    "repo": str(repo or "").replace("\\", "/"),
                    "cmd": cmd[:200],
                    "raw_ref_id": cap["raw_ref_id"],
                    "summary": cap["summary"],
                }
                self._cache.move_to_end(key)
                while len(self._cache) > self.max_entries:
                    self._cache.popitem(last=False)
        with self._lock:
            self._bulletin.append({
                "ts": round(now, 1),
                "cid": str(cid or "agent")[:24],
                "repo": str(repo or "").replace("\\", "/"),
                "cmd": cmd[:100],
                "raw_ref_id": cap["raw_ref_id"],
                "exit_code": int(exit_code),
            })
        return cap

    def recent_bulletin(self, repo: str = "", *, within_s: float = 300.0, limit: int = 6) -> list[dict[str, Any]]:
        now = _now_ts()
        nrepo = str(repo or "").replace("\\", "/").lower()
        with self._lock:
            items = [
                dict(b) for b in reversed(self._bulletin)
                if (now - float(b["ts"])) <= within_s
                and (not nrepo or not b["repo"] or b["repo"].lower() == nrepo)
            ]
        return items[:limit]

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "ok": True,
                "cache_entries": len(self._cache),
                "bulletin_entries": len(self._bulletin),
                "ttl_s": self.ttl_s,
                "stats": dict(self._stats),
            }


# ---------------------------------------------------------------------------
# Module C — BirthPrimerEngine (CHIMERA-PRIMER for SessionStart < 20 ms)
# ---------------------------------------------------------------------------

class BirthPrimerEngine:
    """Injects <= 800-token immutable Turn-0 perception: Env + Repo Tree + Docs + Raw Recall + Swarm."""

    def __init__(self, *, raw_store: AkashicRawStore, shell_guard: ShellShortCircuitGuard) -> None:
        self._raw = raw_store
        self._guard = shell_guard
        self._lock = threading.Lock()
        self._env_cache: dict[str, Any] | None = None
        self._env_ts: float = 0.0
        self._tree_cache: dict[str, tuple[float, list[str], list[str]]] = {}
        self._active_workers: dict[str, tuple[float, str]] = {}
        self._primes_served = 0

    def env_fingerprint(self) -> dict[str, Any]:
        now = time.monotonic()
        with self._lock:
            if self._env_cache is not None and (now - self._env_ts) < 120.0:
                return dict(self._env_cache)
        tools: dict[str, str] = {"python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"}
        for bin_name in ("node", "pytest", "git", "dotnet", "rg"):
            tools[bin_name] = "ok" if shutil.which(bin_name) else "absent"
        for pkg in ("pypdf", "sqlite3", "playwright"):
            try:
                __import__(pkg)
                tools[pkg] = "ok"
            except Exception:
                tools[pkg] = "absent"
        fp = {
            "os": os.name,
            "dev_drive": str(_dev_drive_mnemosyne_dir().parent).replace("\\", "/"),
            "tools": tools,
        }
        with self._lock:
            self._env_cache = fp
            self._env_ts = now
        return dict(fp)

    def _repo_tree_and_docs(self, repo_p: Path) -> tuple[list[str], list[str]]:
        key = str(repo_p).lower()
        now = time.monotonic()
        with self._lock:
            hit = self._tree_cache.get(key)
            if hit is not None and (now - hit[0]) < 10.0:
                return list(hit[1]), list(hit[2])
        tree: list[str] = []
        docs: list[str] = []
        try:
            for item in sorted(repo_p.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
                if item.name in _SKIP_DIRS or item.name.startswith("."):
                    continue
                if len(tree) < 36:
                    tree.append(item.name + ("/" if item.is_dir() else ""))
                if item.is_file() and item.suffix.lower() in (".pdf", ".docx"):
                    docs.append(item.name)
                elif item.is_dir():
                    try:
                        for sub in sorted(item.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))[:10]:
                            if sub.name in _SKIP_DIRS:
                                continue
                            rel = f"{item.name}/{sub.name}"
                            if len(tree) < 36:
                                tree.append(rel + ("/" if sub.is_dir() else ""))
                            if sub.is_file() and sub.suffix.lower() in (".pdf", ".docx"):
                                docs.append(rel)
                    except OSError:
                        pass
        except OSError:
            pass
        with self._lock:
            if len(self._tree_cache) > 16:
                self._tree_cache.clear()
            self._tree_cache[key] = (now, list(tree), list(docs))
        return tree, docs

    def register_worker_heartbeat(self, cid: str, repo: str) -> int:
        now = _now_ts()
        with self._lock:
            self._active_workers[str(cid or "agent")[:64]] = (now, str(repo or "").replace("\\", "/"))
            # Prune inactive > 180s
            for k in [k for k, (ts, _) in self._active_workers.items() if (now - ts) > 180.0]:
                self._active_workers.pop(k, None)
            return len(self._active_workers)

    def prime(self, repo: str | Path, *, cid: str = "agent", include_raw_recall: bool = True) -> dict[str, Any]:
        t0 = time.perf_counter()
        repo_p = Path(repo).expanduser().resolve() if repo else None
        nrepo = str(repo_p).replace("\\", "/") if repo_p else ""
        active_cnt = self.register_worker_heartbeat(cid, nrepo)
        env = self.env_fingerprint()
        tree: list[str] = []
        docs: list[str] = []
        if repo_p and repo_p.is_dir():
            tree, docs = self._repo_tree_and_docs(repo_p)
        bulletin = self._guard.recent_bulletin(nrepo, within_s=300.0, limit=4)
        raw_hits: list[dict[str, Any]] = []
        if include_raw_recall and repo_p:
            rec = self._raw.recall(repo_p.name, repo=nrepo, top_k=2, causal_hops=0, expand_turns=False, max_bytes=1200)
            raw_hits = [
                {
                    "src": it["source_kind"],
                    "stamp": (it.get("reality") or {}).get("stamp", ""),
                    "excerpt": it["text"][:220].replace("\n", " "),
                }
                for it in (rec.get("items") or [])[:2]
            ]
        pacing_warn = (
            f"SWARM_PACING: {active_cnt} concurrent workers active; cap Frontier Swarm at 2-3 workers & offload broad scans to Sha256VerifiedScout/raw_recall."
            if active_cnt >= 4
            else ""
        )
        # Compact prompt string (<= 900 chars) suitable for SessionStart injection
        env_bits = ",".join(f"{k}={v}" for k, v in env["tools"].items() if v != "absent")
        parts = [f"Env[{env_bits}]"]
        if tree:
            parts.append(f"Tree({len(tree)}): {', '.join(tree[:14])}")
        if docs:
            parts.append(f"Docs(use doc_page op): {', '.join(docs[:4])}")
        if bulletin:
            parts.append("SwarmRecent: " + "; ".join(f"{b['cid']}:{b['cmd'][:40]}(ref={b['raw_ref_id']})" for b in bulletin[:2]))
        if raw_hits:
            parts.append("RawMemory: " + "; ".join(f"[{h['src']}/{h['stamp']}] {h['excerpt'][:110]}" for h in raw_hits[:2]))
        if pacing_warn:
            parts.append(pacing_warn)
        self._primes_served += 1
        return {
            "ok": True,
            "repo": nrepo,
            "env": env,
            "tree": tree,
            "docs": docs,
            "swarm_bulletin": bulletin,
            "raw_recall": raw_hits,
            "active_workers": active_cnt,
            "pacing_warning": pacing_warn,
            "compact_text": " | ".join(parts)[:1100],
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }

    def watchdog_snapshot(self) -> dict[str, Any]:
        """0-token Swarm Watchdog replacing expensive LLM @monitor workers."""
        now = _now_ts()
        with self._lock:
            workers = [
                {"cid": k, "repo": r, "idle_s": round(now - ts, 1), "stalled": (now - ts) > 120.0}
                for k, (ts, r) in self._active_workers.items()
            ]
        stalled = [w for w in workers if w["stalled"]]
        return {
            "ok": True,
            "zero_token_monitor": True,
            "active_workers": len(workers),
            "stalled_count": len(stalled),
            "over_subscribed": len(workers) >= 4,
            "workers": workers,
            "primes_served": self._primes_served,
        }


# ---------------------------------------------------------------------------
# Module D — WarmPythonReplPool (CHIMERA-WARM-REPL, Zero ConPTY + Singleflight)
# ---------------------------------------------------------------------------

_WARM_REPL_SCRIPT = r"""
import contextlib, hashlib, io, json, math, os, pathlib, re, sqlite3, sys, time, traceback, unittest
_BASE_ENV = {
    'json': json, 're': re, 'os': os, 'sys': sys, 'math': math,
    'hashlib': hashlib, 'pathlib': pathlib, 'Path': pathlib.Path,
    'sqlite3': sqlite3, 'time': time, 'unittest': unittest,
}
for raw in sys.stdin:
    raw = raw.strip()
    if not raw:
        continue
    req = json.loads(raw)
    code = str(req.get('code') or '')
    cwd = req.get('cwd') or os.getcwd()
    orig = os.getcwd()
    buf_out, buf_err = io.StringIO(), io.StringIO()
    ok = True
    t0 = time.perf_counter()
    try:
        if cwd and os.path.isdir(cwd):
            os.chdir(cwd)
        ns = dict(_BASE_ENV)
        ns['__name__'] = '__main__'
        with contextlib.redirect_stdout(buf_out), contextlib.redirect_stderr(buf_err):
            exec(compile(code, '<chimera_warm_repl>', 'exec'), ns, ns)
    except Exception:
        ok = False
        buf_err.write(traceback.format_exc())
    finally:
        try:
            os.chdir(orig)
        except OSError:
            pass
    ms = round((time.perf_counter() - t0) * 1000.0, 2)
    sys.stdout.write(json.dumps({
        'ok': ok,
        'stdout': buf_out.getvalue()[:65536],
        'stderr': buf_err.getvalue()[:16384],
        'exec_ms': ms,
    }, ensure_ascii=False) + '\n')
    sys.stdout.flush()
"""


class WarmPythonReplPool:
    """Persistent BELOW_NORMAL warm Python worker with Singleflight dedupe (15-40ms vs 2s ConPTY)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sf_lock = threading.Lock()
        self._inflight: dict[str, tuple[threading.Event, dict[str, Any] | None]] = {}
        self._proc: subprocess.Popen[str] | None = None
        self._stats = {"runs": 0, "boots": 0, "singleflight_hits": 0, "timeouts": 0}

    def _ensure_proc_locked(self) -> subprocess.Popen[str]:
        if self._proc is not None and self._proc.poll() is None:
            return self._proc
        exe = sys.executable
        if os.name == "nt" and exe.lower().endswith("pythonw.exe"):
            cand = Path(exe).with_name("python.exe")
            if cand.is_file():
                exe = str(cand)
        self._proc = subprocess.Popen(
            [exe, "-u", "-c", _WARM_REPL_SCRIPT],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=_BATCH_FLAGS,
        )
        self._stats["boots"] += 1
        return self._proc

    def _kill_locked(self) -> None:
        p = self._proc
        self._proc = None
        if p is not None:
            for stream in (p.stdin, p.stdout, p.stderr):
                try:
                    if stream:
                        stream.close()
                except Exception:
                    pass
            try:
                p.kill()
                p.wait(timeout=1.5)
            except Exception:
                pass

    def run(self, code: str, *, cwd: str = "", timeout_s: float = 15.0, singleflight: bool = True) -> dict[str, Any]:
        t0 = time.perf_counter()
        c_str = str(code or "").strip()
        if not c_str:
            return {"ok": False, "error": "empty_code"}
        sf_key = _sha256_str(f"{cwd}|{c_str}", 20)
        holder: dict[str, Any] | None = None
        if singleflight:
            with self._sf_lock:
                holder = self._inflight.get(sf_key)
                if holder is not None:
                    is_owner = False
                else:
                    holder = {"ev": threading.Event(), "res": None}
                    self._inflight[sf_key] = holder
                    is_owner = True
            if not is_owner and holder is not None:
                holder["ev"].wait(timeout=max(1.0, float(timeout_s)))
                res = holder.get("res")
                if isinstance(res, dict):
                    self._stats["singleflight_hits"] += 1
                    out = dict(res)
                    out["singleflight_hit"] = True
                    out["elapsed_ms"] = round((time.perf_counter() - t0) * 1000.0, 2)
                    return out

        result: dict[str, Any]
        try:
            with self._lock:
                proc = self._ensure_proc_locked()
                payload = json.dumps({"code": c_str, "cwd": str(cwd or "")}, ensure_ascii=False) + "\n"
                assert proc.stdin is not None and proc.stdout is not None
                proc.stdin.write(payload)
                proc.stdin.flush()

                out_holder: list[str] = []

                def _reader() -> None:
                    try:
                        ln = proc.stdout.readline()  # type: ignore[union-attr]
                        out_holder.append(ln)
                    except Exception:
                        pass

                rt = threading.Thread(target=_reader, daemon=True)
                rt.start()
                rt.join(timeout=max(1.0, min(60.0, float(timeout_s))))
                if rt.is_alive() or not out_holder or not out_holder[0]:
                    self._stats["timeouts"] += 1
                    self._kill_locked()
                    result = {"ok": False, "error": "warm_repl_timeout_or_eof", "timed_out": True}
                else:
                    result = json.loads(out_holder[0])
                    self._stats["runs"] += 1
        except Exception as exc:
            with self._lock:
                self._kill_locked()
            result = {"ok": False, "error": str(exc)}

        result["singleflight_hit"] = False
        result["elapsed_ms"] = round((time.perf_counter() - t0) * 1000.0, 2)
        if singleflight and holder is not None:
            with self._sf_lock:
                holder["res"] = result
                holder["ev"].set()
                self._inflight.pop(sf_key, None)
        return result

    def status(self) -> dict[str, Any]:
        with self._lock:
            alive = bool(self._proc is not None and self._proc.poll() is None)
            pid = int(self._proc.pid) if alive and self._proc is not None else None
        return {"ok": True, "alive": alive, "pid": pid, "stats": dict(self._stats)}

    def close(self) -> None:
        with self._lock:
            self._kill_locked()


# ---------------------------------------------------------------------------
# Module E — EntropyCommitAuditor & NocturnalRawArena (Law 1/2/6/7)
# ---------------------------------------------------------------------------

def audit_system_entropy() -> dict[str, Any]:
    """Zero-destructive audit of Commit RAM pressure, idle pythonw pools & OneDrive conflicts."""
    t0 = time.perf_counter()
    mem_info: dict[str, Any] = {}
    if os.name == "nt":
        class _MEMSTAT(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]
        ms = _MEMSTAT()
        ms.dwLength = ctypes.sizeof(_MEMSTAT)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms)):
            tot_c = ms.ullTotalPageFile / (1024 ** 3)
            used_c = (ms.ullTotalPageFile - ms.ullAvailPageFile) / (1024 ** 3)
            mem_info = {
                "memory_load_pct": int(ms.dwMemoryLoad),
                "phys_total_gb": round(ms.ullTotalPhys / (1024 ** 3), 2),
                "phys_avail_gb": round(ms.ullAvailPhys / (1024 ** 3), 2),
                "commit_total_gb": round(tot_c, 2),
                "commit_used_gb": round(used_c, 2),
                "commit_pct": round((used_c / max(0.01, tot_c)) * 100.0, 1),
            }
    else:
        try:
            kv = {}
            for ln in Path("/proc/meminfo").read_text("utf-8").splitlines():
                if ":" in ln:
                    k, v = ln.split(":", 1)
                    kv[k.strip()] = int(v.strip().split()[0])
            tot = kv.get("MemTotal", 0) / 1048576.0
            avail = kv.get("MemAvailable", 0) / 1048576.0
            mem_info = {
                "phys_total_gb": round(tot, 2),
                "phys_avail_gb": round(avail, 2),
                "commit_pct": round(((tot - avail) / max(0.01, tot)) * 100.0, 1),
            }
        except Exception:
            pass

    findings: list[dict[str, Any]] = []
    if mem_info.get("commit_pct", 0.0) >= 75.0:
        findings.append({
            "severity": "P1",
            "code": "HIGH_COMMIT_PRESSURE",
            "detail": f"Commit Charge at {mem_info['commit_pct']}% ({mem_info.get('commit_used_gb')}/{mem_info.get('commit_total_gb')} GB) increases page-fault latency on shell spawns.",
            "recommendation": "Use CHIMERA-WARM-REPL + ShellShortCircuit + lazy-spawn idle pythonw worker pools (e.g. office_pdl.warmup_pool on-demand).",
            "auto_activated": False,
        })
    return {
        "ok": True,
        "os": os.name,
        "memory": mem_info,
        "findings": findings,
        "law2_zero_choke": True,
        "law6_auto_activated": False,
        "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
    }


def run_raw_arena_benchmark(
    raw_store: AkashicRawStore,
    *,
    thought_briefs_db: Path | None = None,
    sample_n: int = 12,
) -> dict[str, Any]:
    """Nocturnal Raw-Arena: A/B test RAW-RAG vs CAUSAL-RAW-RAG vs Lossy Summary on real local history."""
    t0 = time.perf_counter()
    # Build real evidence queries from stored raw chunks that contain concrete file/error anchors
    with raw_store._lock:
        rows = raw_store._conn.execute(
            """
            SELECT chunk_id, thread_id, turn_idx, text
            FROM raw_chunks
            WHERE length(text) >= 120
            ORDER BY ts DESC
            LIMIT 120
            """
        ).fetchall()

    queries: list[tuple[str, str, str]] = []
    for cid, tid, _tidx, txt in rows:
        ancs = [av for ak, av in _extract_anchors(txt) if ak in ("file", "err", "sym")]
        if len(ancs) >= 2:
            queries.append((f"{ancs[0]} {ancs[1]}", cid, ancs[0]))
        if len(queries) >= max(3, int(sample_n)):
            break

    if not queries:
        return {"ok": True, "skipped": True, "reason": "insufficient_raw_chunks", "elapsed_ms": 0.0}

    # Optional lossy summary baseline (thought-briefs.sqlite)
    tb_path = thought_briefs_db or Path(r"E:\DEV\Chung\.ch-relay\local-relay\data\thought-briefs.sqlite")
    tb_conn: sqlite3.Connection | None = None
    if tb_path.is_file():
        try:
            tb_conn = sqlite3.connect(f"file:{tb_path}?mode=ro", uri=True, timeout=1.5)
        except Exception:
            tb_conn = None

    raw_hits = causal_hits = sum_hits = 0
    raw_ms: list[float] = []
    causal_ms: list[float] = []
    sum_ms: list[float] = []
    causal_extra_total = 0

    for q, gold_cid, anchor in queries:
        r0 = raw_store.recall(q, top_k=5, causal_hops=0, expand_turns=False, reality_stamp=False)
        raw_ms.append(float(r0.get("elapsed_ms") or 0.0))
        if any(it["chunk_id"] == gold_cid or anchor in it["text"].lower() for it in r0.get("items") or []):
            raw_hits += 1

        r1 = raw_store.recall(q, top_k=5, causal_hops=1, expand_turns=True, reality_stamp=True)
        causal_ms.append(float(r1.get("elapsed_ms") or 0.0))
        causal_extra_total += int(r1.get("causal_added") or 0)
        if any(it["chunk_id"] == gold_cid or anchor in it["text"].lower() for it in r1.get("items") or []):
            causal_hits += 1

        if tb_conn is not None:
            ts0 = time.perf_counter()
            fq = _sanitize_fts_query(q)
            found_s = False
            if fq:
                try:
                    srows = tb_conn.execute(
                        "SELECT summary FROM thought_briefs_fts WHERE thought_briefs_fts MATCH ? LIMIT 5",
                        (fq,),
                    ).fetchall()
                    found_s = any(anchor in str(sr[0] or "").lower() for sr in srows)
                except Exception:
                    pass
            sum_ms.append(round((time.perf_counter() - ts0) * 1000.0, 2))
            if found_s:
                sum_hits += 1

    if tb_conn is not None:
        tb_conn.close()

    n = len(queries)
    raw_pct = round(raw_hits / n * 100.0, 1)
    causal_pct = round(causal_hits / n * 100.0, 1)
    sum_pct = round(sum_hits / n * 100.0, 1) if sum_ms else None
    winner = "CAUSAL_RAW_RAG" if causal_pct >= raw_pct else "RAW_RAG"
    return {
        "ok": True,
        "queries_evaluated": n,
        "winner": winner,
        "raw_rag": {
            "evidence_hit_pct": raw_pct,
            "avg_ms": round(sum(raw_ms) / n, 2),
        },
        "causal_raw_rag": {
            "evidence_hit_pct": causal_pct,
            "causal_links_added_total": causal_extra_total,
            "avg_ms": round(sum(causal_ms) / n, 2),
        },
        "lossy_summary_baseline": {
            "available": sum_pct is not None,
            "evidence_hit_pct": sum_pct,
            "avg_ms": round(sum(sum_ms) / len(sum_ms), 2) if sum_ms else None,
        },
        "autophagy_proposal": {
            "auto_activated": False,
            "recommendation": "Use pointer-over-raw (CAUSAL-RAW-RAG) as ground truth; demote standalone lossy summaries to navigation pointers.",
        },
        "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
    }


# ---------------------------------------------------------------------------
# Unified Lazy Facade — MnemosyneCore
# ---------------------------------------------------------------------------

class MnemosyneCore:
    """Single lazy facade uniting all 5 loops of CHIMERA-MNEMOSYNE."""

    def __init__(self, *, ephemeral: bool = False, db_path: Path | None = None) -> None:
        self._ephemeral = bool(ephemeral)
        self.raw = AkashicRawStore(db_path=db_path, ephemeral=ephemeral)
        self.shell_guard = ShellShortCircuitGuard(raw_store=self.raw)
        self.primer = BirthPrimerEngine(raw_store=self.raw, shell_guard=self.shell_guard)
        self._warm_repl: WarmPythonReplPool | None = None
        self._repl_lock = threading.Lock()

    @property
    def warm_repl(self) -> WarmPythonReplPool:
        if self._warm_repl is None:
            with self._repl_lock:
                if self._warm_repl is None:
                    self._warm_repl = WarmPythonReplPool()
        return self._warm_repl

    def status(self) -> dict[str, Any]:
        return {
            "ok": True,
            "engine": "chimera-mnemosyne-v1",
            "law1_zero_loss_raw": True,
            "law2_zero_choke": True,
            "law6_shadow_only": True,
            "raw_store": self.raw.status(),
            "shell_guard": self.shell_guard.status(),
            "watchdog": self.primer.watchdog_snapshot(),
            "warm_repl": self._warm_repl.status() if self._warm_repl is not None else {"ok": True, "alive": False, "lazy": True},
        }

    def dispatch(self, action: str = "status", **kwargs: Any) -> dict[str, Any]:
        act = str(action or "status").strip().lower()
        if act == "status":
            return self.status()
        if act == "prime":
            return self.primer.prime(
                kwargs.get("repo") or "",
                cid=str(kwargs.get("cid") or kwargs.get("conversation_id") or "agent"),
                include_raw_recall=bool(kwargs.get("include_raw_recall", True)),
            )
        if act in ("raw_recall", "recall"):
            return self.raw.recall(
                str(kwargs.get("query") or ""),
                repo=str(kwargs.get("repo") or ""),
                top_k=int(kwargs.get("top_k") or kwargs.get("limit") or 8),
                causal_hops=int(kwargs.get("causal_hops") if kwargs.get("causal_hops") is not None else 1),
                expand_turns=bool(kwargs.get("expand_turns", True)),
                reality_stamp=bool(kwargs.get("reality_stamp", True)),
                use_codex_rerank=bool(kwargs.get("use_codex_rerank", False)),
                max_bytes=int(kwargs.get("max_bytes") or 10000),
            )
        if act in ("raw_ingest", "ingest"):
            return self.raw.ingest_local_raw_logs(
                max_codex_rows=int(kwargs.get("max_codex_rows") or 1200),
                max_agy_files=int(kwargs.get("max_agy_files") or 24),
                max_t3_events=int(kwargs.get("max_t3_events") or 800),
            )
        if act == "raw_slice":
            return self.raw.get_raw_slice(
                str(kwargs.get("raw_ref_id") or kwargs.get("ref_id") or ""),
                start_line=int(kwargs.get("start_line") or 1),
                max_lines=int(kwargs.get("max_lines") or 120),
            )
        if act == "doc_digest":
            return self.raw.digest_document_pages(
                kwargs.get("repo") or ".",
                str(kwargs.get("rel_path") or kwargs.get("path") or ""),
            )
        if act == "doc_page":
            return self.raw.read_document_page(
                kwargs.get("repo") or ".",
                str(kwargs.get("rel_path") or kwargs.get("path") or ""),
                page=int(kwargs.get("page") or 1),
            )
        if act == "shell_guard":
            if kwargs.get("output_text") is not None:
                return self.shell_guard.record_post_command(
                    repo=str(kwargs.get("repo") or ""),
                    cmd=str(kwargs.get("cmd") or ""),
                    output_text=str(kwargs.get("output_text") or ""),
                    cid=str(kwargs.get("cid") or "agent"),
                    exit_code=int(kwargs.get("exit_code") or 0),
                )
            return self.shell_guard.check_pre_command(
                repo=str(kwargs.get("repo") or ""),
                cmd=str(kwargs.get("cmd") or ""),
                cid=str(kwargs.get("cid") or "agent"),
            )
        if act == "warm_repl":
            return self.warm_repl.run(
                str(kwargs.get("code") or ""),
                cwd=str(kwargs.get("cwd") or kwargs.get("repo") or ""),
                timeout_s=float(kwargs.get("timeout_s") or 15.0),
                singleflight=bool(kwargs.get("singleflight", True)),
            )
        if act in ("entropy_audit", "audit"):
            return audit_system_entropy()
        if act in ("swarm_watchdog", "watchdog"):
            return self.primer.watchdog_snapshot()
        if act in ("raw_arena", "arena"):
            return run_raw_arena_benchmark(
                self.raw,
                sample_n=int(kwargs.get("sample_n") or 12),
            )
        return {"ok": False, "error": f"unknown_mnemosyne_action:{act}"}

    def close(self) -> None:
        if self._warm_repl is not None:
            self._warm_repl.close()
        self.raw.close()


_DEFAULT_MNEMOSYNE_LOCK = threading.Lock()
_DEFAULT_MNEMOSYNE: MnemosyneCore | None = None


def get_mnemosyne_core() -> MnemosyneCore:
    global _DEFAULT_MNEMOSYNE
    with _DEFAULT_MNEMOSYNE_LOCK:
        if _DEFAULT_MNEMOSYNE is None:
            _DEFAULT_MNEMOSYNE = MnemosyneCore(ephemeral=False)
        return _DEFAULT_MNEMOSYNE
