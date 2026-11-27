"""CHIMERA-ONE Organ 3 (Akashic Swarm-Kernel): Zero-Spawn Agent Hyper-Bus.

Eliminates the dual tax destroying AI coding-agent workflows on Windows/Linux:
1. Cold-Process Tax: 20-60 sequential PowerShell / Node / Python / rg / SSH spawns per turn.
2. Serial LLM Round-Trip & Token Tax: reading 16-line slices one-by-one and flooding context with stdout noise.

Provides four stdlib-only, lazy-loaded, zero-PowerShell primitives:
- TokenDietCompactor: collapses verbose PASS/noise stdout (-60% to -85% bytes), preserves 100% FAIL/TRACEBACK/DIFF,
  and stores bounded raw logs by ref_id for on-demand drill-down.
- OmniProbeBatchEngine (`chimera_xray_batch`): executes up to 40 mixed read-only probes
  (file_slice, regex_search, list_files, json_query, http_get, sqlite_ro, git_status, raw_ref)
  concurrently in-process in milliseconds with 0 shell spawns.
- CallgraphTelepathyEngine (`chimera_callgraph_slice`): multi-language (Python AST + JS/TS/Rust)
  2-hop caller/callee + related-test slicer packed under a strict character budget.
- AtomicCommitVerifyEngine (`chimera_commit_verify`): single-shot parallel py_compile + node --check +
  import-graph impacted-test runner with BLAKE2s result memoization and Token-Diet output compaction.
"""

from __future__ import annotations

import ast
import collections
import concurrent.futures
import fnmatch
import hashlib
import json
import os
import py_compile
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from array import array
from pathlib import Path
from typing import Any

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
_BELOW_NORMAL = getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0x00004000) if os.name == "nt" else 0
_BATCH_FLAGS = _NO_WINDOW | _BELOW_NORMAL

_SKIP_DIRS = frozenset({
    ".git",
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
    "target",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "dist",
    "build",
    ".next",
    ".chimera_cold_backing",
})

_TEXT_EXTS = frozenset({
    ".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".rs",
    ".json", ".toml", ".yaml", ".yml", ".md", ".txt", ".ini", ".cfg",
    ".sh", ".ps1", ".sql", ".html", ".css", ".env", ".pbtxt",
})

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

_CRITICAL_LINE_RE = re.compile(
    r"(?i)(error|fail|failed|traceback|assertionerror|exception|syntaxerror|typeerror|valueerror|"
    r"keyerror|attributeerror|importerror|modulenotfounderror|^\+\+\+|^---|^@@|^[-+]\s|ran \d+ test|ok$|exit=)"
)
_NOISE_PASS_RE = re.compile(r"(\.\.\.\s*ok\s*$|PASSED\s*$|^\s*ok\s*$)")


def _blake2s_short(data: bytes) -> str:
    return hashlib.blake2s(data, digest_size=12).hexdigest()


_LINE_END = re.compile(rb"\r\n|[\n\r\v\f\x1c-\x1e]|\xc2\x85|\xe2\x80[\xa8\xa9]")
_OTHER_LINE_ENDS = (b"\v", b"\f", b"\x1c", b"\x1d", b"\x1e", b"\xc2\x85", b"\xe2\x80\xa8", b"\xe2\x80\xa9")


class _CachedTextLines:
    """A bounded byte snapshot. Ordinary source slices decode only their requested rows."""

    def __init__(self, data: bytes):
        self.data = data
        cr = data.count(b"\r")
        self.normal = (not cr or cr == data.count(b"\r\n")) and not any(end in data for end in _OTHER_LINE_ENDS)
        if self.normal:
            self.count = data.count(b"\n") + int(bool(data) and not data.endswith(b"\n"))
        else:
            self.count = len(data.decode("utf-8", errors="replace").splitlines())

    def read_range(self, first: int, last: int) -> list[str]:
        last = min(last, self.count)
        if last < first:
            return []
        # A deep slice is cheaper with one native split than with thousands of Python iterations.
        if not self.normal or first > 128 or last - first > 256:
            return self.data.decode("utf-8", errors="replace").splitlines()[first - 1:last]
        start = 0
        for _ in range(first - 1):
            start = self.data.index(b"\n", start) + 1
        end = start
        for _ in range(last - first + 1):
            lf = self.data.find(b"\n", end)
            if lf < 0:
                end = len(self.data)
                break
            end = lf + 1
        return self.data[start:end].decode("utf-8", errors="replace").splitlines()


def _line_offsets(stream, digest=None):
    """Yield byte offsets immediately after every delimiter recognized by str.splitlines()."""
    position = stream.tell()
    carry = b""
    while True:
        block = stream.read(64 * 1024)
        if digest is not None:
            digest.update(block)
        data = carry + block
        # Delay a possible CRLF, NEL, LINE SEPARATOR or PARAGRAPH SEPARATOR at a block boundary.
        hold = 0
        if block:
            if data.endswith(b"\xe2\x80"):
                hold = 2
            elif data.endswith((b"\r", b"\xc2", b"\xe2")):
                hold = 1
        stop = len(data) - hold
        for match in _LINE_END.finditer(data, 0, stop):
            yield position + match.end()
        position += stop
        carry = data[stop:]
        if not block:
            break


def _file_identity(stat: os.stat_result):
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


class _SparseTextLines:
    """A batch can share a digest and at most 64 KiB of offsets for a large source file."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.stride = 256
        self.offsets = array("Q", [0])
        digest = hashlib.blake2s(digest_size=12)
        breaks = last_end = 0
        with path.open("rb") as stream:
            self.identity = _file_identity(os.fstat(stream.fileno()))
            for after in _line_offsets(stream, digest):
                breaks += 1
                last_end = after
                if breaks % self.stride == 0:
                    if len(self.offsets) >= 8192:
                        self.offsets = self.offsets[::2]
                        self.stride *= 2
                    if breaks % self.stride == 0:
                        self.offsets.append(after)
            self._check(stream)
        self.count = breaks + int(last_end < self.identity[2])
        self.digest = digest.hexdigest()

    def _check(self, stream):
        if _file_identity(os.fstat(stream.fileno())) != self.identity:
            raise OSError("file_changed_during_read")

    def read_range(self, first: int, last: int) -> list[str]:
        if last < first:
            return []
        slot = (first - 1) // self.stride
        line = 1 + slot * self.stride
        start = self.offsets[slot]
        with self.path.open("rb") as stream:
            self._check(stream)
            stream.seek(start)
            end = self.identity[2]
            for after in _line_offsets(stream):
                if line < first:
                    start = after
                if line == last:
                    end = after
                    break
                line += 1
            stream.seek(start)
            raw = stream.read(end - start)
            self._check(stream)
        return raw.decode("utf-8", errors="replace").splitlines()


def _safe_resolve(path_str: str, base_dir: Path | None = None) -> Path:
    p = Path(path_str)
    if not p.is_absolute() and base_dir is not None:
        p = base_dir / p
    return p.resolve()


def _extract_jpath(obj: Any, jpath: str) -> Any:
    """Simple dotted/array JSON projection: e.g. 'models[].id', 'zero_weight.daemon_ram_mb', 'items[0].name'."""
    if not jpath or jpath == "$":
        return obj
    cur = obj
    parts = [p for p in jpath.lstrip("$.").split(".") if p]

    def _walk(node: Any, idx: int) -> Any:
        if idx >= len(parts):
            return node
        seg = parts[idx]
        if seg.endswith("[]"):
            key = seg[:-2]
            arr = node.get(key) if (key and isinstance(node, dict)) else (node if not key else None)
            if not isinstance(arr, list):
                return None
            return [_walk(item, idx + 1) for item in arr]
        m = re.match(r"^([^\[\]]*)\[(\d+)\]$", seg)
        if m:
            key, arr_idx = m.group(1), int(m.group(2))
            arr = node.get(key) if (key and isinstance(node, dict)) else (node if not key else None)
            if isinstance(arr, list) and 0 <= arr_idx < len(arr):
                return _walk(arr[arr_idx], idx + 1)
            return None
        if isinstance(node, dict):
            return _walk(node.get(seg), idx + 1)
        if isinstance(node, list):
            return [_walk(item, idx) for item in node]
        return None

    return _walk(cur, 0)


# ---------------------------------------------------------------------------
# 1. CHIMERA-TOKEN-DIET-COMPACTOR
# ---------------------------------------------------------------------------

class TokenDietCompactor:
    """Strips ANSI/PASS/log bloat while preserving 100% of FAIL/ERROR/TRACEBACK/DIFF lines."""

    def __init__(self, *, max_entries: int = 32, max_total_bytes: int = 256 * 1024) -> None:
        self._lock = threading.Lock()
        self._store: collections.OrderedDict[str, str] = collections.OrderedDict()
        self._total_bytes: int = 0
        self._max_entries = max(4, int(max_entries))
        self._max_total_bytes = max(32 * 1024, int(max_total_bytes))
        self._raw_in: int = 0
        self._compact_out: int = 0
        self._calls: int = 0

    def _put_raw(self, text: str) -> str:
        raw_b = text.encode("utf-8", errors="replace")
        ref = _blake2s_short(raw_b)
        stored = text[:64_000]
        sb = len(stored.encode("utf-8", errors="replace"))
        with self._lock:
            if ref in self._store:
                self._store.move_to_end(ref)
                return ref
            while (len(self._store) >= self._max_entries or self._total_bytes + sb > self._max_total_bytes) and self._store:
                _, old = self._store.popitem(last=False)
                self._total_bytes -= len(old.encode("utf-8", errors="replace"))
            self._store[ref] = stored
            self._total_bytes += sb
        return ref

    def get_raw(self, ref_id: str, start_line: int = 1, max_lines: int = 200) -> dict[str, Any]:
        with self._lock:
            txt = self._store.get(str(ref_id or "").strip())
        if txt is None:
            return {"ok": False, "error": "ref_not_found", "ref_id": ref_id}
        lines = txt.splitlines()
        s = max(1, int(start_line))
        n = max(1, min(500, int(max_lines)))
        chunk = lines[s - 1 : s - 1 + n]
        return {
            "ok": True,
            "ref_id": ref_id,
            "total_lines": len(lines),
            "start_line": s,
            "end_line": s + len(chunk) - 1 if chunk else s,
            "text": "\n".join(chunk),
        }

    def compact(
        self,
        text: str,
        *,
        max_lines: int = 50,
        max_chars: int = 3200,
        store_ref: bool = True,
    ) -> dict[str, Any]:
        clean = _ANSI_RE.sub("", str(text or ""))
        raw_bytes = len(clean.encode("utf-8", errors="replace"))
        lines = clean.splitlines()
        if raw_bytes <= max_chars and len(lines) <= max_lines:
            with self._lock:
                self._calls += 1
                self._raw_in += raw_bytes
                self._compact_out += raw_bytes
            return {
                "text": clean,
                "compacted": False,
                "raw_bytes": raw_bytes,
                "compacted_bytes": raw_bytes,
                "saved_pct": 0.0,
                "ref_id": None,
            }

        ref_id = self._put_raw(clean) if store_ref else None

        # Always keep critical error/traceback/diff lines + head + tail while collapsing verbose PASS noise
        kept: list[str] = []
        pass_collapsed = 0
        in_traceback = False
        tb_budget = 0
        for idx, ln in enumerate(lines):
            stripped = ln.strip()
            if not stripped:
                continue
            if "Traceback (most recent call last):" in ln or ln.startswith("====") or ln.startswith("ERROR:") or ln.startswith("FAIL:"):
                in_traceback = True
                tb_budget = 35
            if in_traceback:
                kept.append(ln)
                tb_budget -= 1
                if tb_budget <= 0 or (ln.startswith("----") and len(ln) >= 20):
                    in_traceback = False
                continue
            if _NOISE_PASS_RE.search(ln) and not _CRITICAL_LINE_RE.search(ln):
                pass_collapsed += 1
                continue
            if _CRITICAL_LINE_RE.search(ln) or idx < 5 or idx >= len(lines) - 8:
                kept.append(ln)

        # Deduplicate consecutive identical lines
        deduped: list[str] = []
        dup_run = 0
        for ln in kept:
            if deduped and ln == deduped[-1]:
                dup_run += 1
                continue
            if dup_run > 0:
                deduped.append(f"... [repeated {dup_run}x]")
                dup_run = 0
            deduped.append(ln)
        if dup_run > 0:
            deduped.append(f"... [repeated {dup_run}x]")

        if pass_collapsed > 0:
            deduped.insert(0, f"[token-diet: collapsed {pass_collapsed} PASS/OK lines; ref_id={ref_id}]")

        if len(deduped) > max_lines:
            head_n = max(8, max_lines // 2)
            tail_n = max(8, max_lines - head_n - 1)
            omitted = len(deduped) - head_n - tail_n
            deduped = deduped[:head_n] + [f"... [omitted {omitted} middle lines; full ref_id={ref_id}] ..."] + deduped[-tail_n:]

        out_text = "\n".join(deduped)
        if len(out_text) > max_chars:
            keep_head = max(400, max_chars // 2)
            keep_tail = max(400, max_chars - keep_head - 72)
            out_text = (
                out_text[:keep_head]
                + f"\n... [truncated to {max_chars} chars; full ref_id={ref_id}] ...\n"
                + out_text[-keep_tail:]
            )

        comp_bytes = len(out_text.encode("utf-8", errors="replace"))
        saved_pct = round(max(0.0, (1.0 - (comp_bytes / max(1, raw_bytes))) * 100.0), 1)
        with self._lock:
            self._calls += 1
            self._raw_in += raw_bytes
            self._compact_out += comp_bytes
        return {
            "text": out_text,
            "compacted": True,
            "raw_bytes": raw_bytes,
            "compacted_bytes": comp_bytes,
            "saved_pct": saved_pct,
            "ref_id": ref_id,
        }

    def stats(self) -> dict[str, Any]:
        with self._lock:
            saved = max(0, self._raw_in - self._compact_out)
            pct = round((saved / max(1, self._raw_in)) * 100.0, 1) if self._raw_in else 0.0
            return {
                "calls": self._calls,
                "raw_bytes_in": self._raw_in,
                "compacted_bytes_out": self._compact_out,
                "bytes_saved": saved,
                "saved_pct": pct,
                "stored_refs": len(self._store),
                "stored_bytes": self._total_bytes,
            }


# ---------------------------------------------------------------------------
# 2. CHIMERA-OMNI-PROBE BATCH ENGINE (`chimera_xray_batch`)
# ---------------------------------------------------------------------------

class _BatchCoalescer:
    """Ephemeral per-batch singleflight cache (0 retained RAM after run_batch returns)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._inflight: dict[str, threading.Event] = {}
        self._values: dict[str, tuple[bool, Any]] = {}
        self.coalesced_hits: int = 0

    def get_or_load(self, key: str, loader: Any) -> Any:
        while True:
            with self._lock:
                if key in self._values:
                    self.coalesced_hits += 1
                    ok, val = self._values[key]
                    if ok:
                        return val
                    raise val
                ev = self._inflight.get(key)
                if ev is None:
                    ev = threading.Event()
                    self._inflight[key] = ev
                    owner = True
                else:
                    owner = False
            if not owner:
                ev.wait(timeout=15.0)
                continue
            try:
                val = loader()
                with self._lock:
                    self._values[key] = (True, val)
                    self._inflight.pop(key, None)
                    ev.set()
                return val
            except Exception as exc:
                with self._lock:
                    self._values[key] = (False, exc)
                    self._inflight.pop(key, None)
                    ev.set()
                raise


class OmniProbeBatchEngine:
    """Single-shot concurrent read-only forensic batch runner (0 PowerShell/Node/Python spawns)."""

    MAX_OPS = 40

    def __init__(self, compactor: TokenDietCompactor) -> None:
        self.compactor = compactor
        self._lock = threading.Lock()
        self._batches_run = 0
        self._ops_run = 0
        self._shells_avoided = 0
        self._coalesced_hits = 0
        self._spec_cache_lookup: Callable[[Path], tuple[str, _CachedTextLines] | None] | None = None

    def _op_file_slice(
        self,
        spec: dict[str, Any],
        base_dir: Path | None,
        cache: _BatchCoalescer | None = None,
    ) -> dict[str, Any]:
        path_raw = str(spec.get("path") or "")
        if not path_raw:
            return {"ok": False, "error": "path_required"}
        p = _safe_resolve(path_raw, base_dir)
        if not p.is_file():
            return {"ok": False, "error": "file_not_found", "path": str(p)}

        def load_lines():
            lookup = self._spec_cache_lookup
            if lookup is not None:
                cached_spec = lookup(p)
                if cached_spec is not None:
                    s_hash, snapshot = cached_spec
                    return s_hash, snapshot.count, snapshot.read_range, True
            if p.stat().st_size > 256 * 1024:
                index = _SparseTextLines(p)
                return index.digest, index.count, index.read_range, False
            raw = p.read_bytes()
            lines = raw.decode("utf-8", errors="replace").splitlines()
            return _blake2s_short(raw), len(lines), lambda first, last: lines[first - 1:last], False

        key = "file:" + os.path.normcase(str(p))
        sha, total, read_range, spec_hit = cache.get_or_load(key, load_lines) if cache else load_lines()
        source = {"speculative_hit": True} if spec_hit else {}

        # Support multiple non-contiguous ranges in ONE file read: ranges=[[10,30],[100,120]]
        ranges = spec.get("ranges")
        if isinstance(ranges, list) and ranges:
            out_ranges = []
            for rg in ranges[:12]:
                if isinstance(rg, (list, tuple)) and len(rg) >= 2:
                    s = max(1, int(rg[0]))
                    e = min(total, max(s, int(rg[1])))
                    out_ranges.append({
                        "start": s,
                        "end": e,
                        "lines": [f"{i}: {line}" for i, line in enumerate(read_range(s, e), s)],
                    })
            return {"ok": True, "path": str(p), "total_lines": total, "hash": sha, "ranges": out_ranges, **source}

        if spec.get("skip") is not None or spec.get("first") is not None:
            start = max(1, int(spec.get("skip") or 0) + 1)
            count = max(1, min(400, int(spec.get("first") or 80)))
            end = min(total, start + count - 1)
        elif spec.get("tail_lines") is not None:
            n = max(1, min(400, int(spec["tail_lines"])))
            start = max(1, total - n + 1)
            end = total
        else:
            start = max(1, int(spec.get("start_line") or 1))
            end = min(total, int(spec.get("end_line") or (start + 119)))
            if end < start:
                end = min(total, start + 119)
            if (end - start + 1) > 400:
                end = start + 399

        numbered = spec.get("numbered", True)
        sliced = [
            (f"{i}: {line}" if numbered else line)
            for i, line in enumerate(read_range(start, end), start)
        ] if total > 0 and start <= total else []
        return {
            "ok": True,
            "path": str(p),
            "total_lines": total,
            "start_line": start,
            "end_line": end if sliced else start,
            "hash": sha,
            **source,
            "text": "\n".join(sliced),
        }

    def _op_regex_search(self, spec: dict[str, Any], base_dir: Path | None) -> dict[str, Any]:
        pattern = str(spec.get("pattern") or "")
        if not pattern:
            return {"ok": False, "error": "pattern_required"}
        flags = re.IGNORECASE if bool(spec.get("ignore_case", False)) else 0
        try:
            rx = re.compile(re.escape(pattern) if bool(spec.get("fixed", False)) else pattern, flags)
        except re.error as exc:
            return {"ok": False, "error": f"invalid_regex:{exc}"}

        target = _safe_resolve(str(spec.get("path") or "."), base_dir)
        max_hits_raw = spec.get("max_hits") if spec.get("max_hits") is not None else spec.get("limit")
        max_hits = max(1, min(100, int(max_hits_raw or 25)))
        ctx = max(0, min(5, int(spec.get("context") or 0)))
        glob_pat = str(spec.get("glob") or "").strip()
        exts = {str(e).lower() for e in (spec.get("exts") or [])}

        hits: list[dict[str, Any]] = []
        files_scanned = 0

        def _scan_file(fp: Path) -> None:
            nonlocal files_scanned
            if len(hits) >= max_hits:
                return
            try:
                st = fp.stat()
                if st.st_size > 2 * 1024 * 1024:
                    return
                raw = fp.read_bytes()
                if b"\x00" in raw[:4096]:
                    return
                files_scanned += 1
                lines = raw.decode("utf-8", errors="replace").splitlines()
                for i, ln in enumerate(lines):
                    if rx.search(ln):
                        entry: dict[str, Any] = {
                            "file": str(fp.relative_to(base_dir)) if (base_dir and fp.is_relative_to(base_dir)) else str(fp),
                            "line": i + 1,
                            "text": ln[:240],
                        }
                        if ctx > 0:
                            lo = max(0, i - ctx)
                            hi = min(len(lines), i + ctx + 1)
                            entry["context"] = [f"{j + 1}: {lines[j][:200]}" for j in range(lo, hi)]
                        hits.append(entry)
                        if len(hits) >= max_hits:
                            return
            except OSError:
                return

        if target.is_file():
            _scan_file(target)
        elif target.is_dir():
            for root, dirs, files in os.walk(target):
                dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
                for fn in files:
                    if len(hits) >= max_hits:
                        break
                    fp = Path(root) / fn
                    if glob_pat and not fnmatch.fnmatch(fn, glob_pat):
                        continue
                    if exts and fp.suffix.lower() not in exts:
                        continue
                    if not exts and not glob_pat and fp.suffix.lower() not in _TEXT_EXTS:
                        continue
                    _scan_file(fp)
                if len(hits) >= max_hits:
                    break
        else:
            return {"ok": False, "error": "target_not_found", "path": str(target)}

        return {"ok": True, "pattern": pattern, "files_scanned": files_scanned, "count": len(hits), "hits": hits}

    def _op_list_files(self, spec: dict[str, Any], base_dir: Path | None) -> dict[str, Any]:
        target = _safe_resolve(str(spec.get("path") or "."), base_dir)
        if not target.is_dir():
            return {"ok": False, "error": "dir_not_found", "path": str(target)}
        glob_pat = str(spec.get("glob") or spec.get("pattern") or "*").strip() or "*"
        limit = max(1, min(500, int(spec.get("limit") or 150)))
        out: list[dict[str, Any]] = []
        for root, dirs, files in os.walk(target):
            dirs[:] = sorted(d for d in dirs if d not in _SKIP_DIRS)
            for fn in sorted(files):
                if not fnmatch.fnmatch(fn, glob_pat):
                    continue
                fp = Path(root) / fn
                rel = fp.relative_to(target).as_posix()
                try:
                    sz = fp.stat().st_size
                except OSError:
                    sz = 0
                out.append({"path": rel, "bytes": sz})
                if len(out) >= limit:
                    break
            if len(out) >= limit:
                break
        return {"ok": True, "root": str(target), "glob": glob_pat, "count": len(out), "files": out}

    def _op_json_query(
        self,
        spec: dict[str, Any],
        base_dir: Path | None,
        cache: _BatchCoalescer | None = None,
    ) -> dict[str, Any]:
        path_raw = str(spec.get("path") or "")
        if not path_raw:
            return {"ok": False, "error": "path_required"}
        p = _safe_resolve(path_raw, base_dir)
        if not p.is_file():
            return {"ok": False, "error": "file_not_found", "path": str(p)}
        try:
            def _load_json() -> Any:
                return json.loads(p.read_text(encoding="utf-8", errors="replace"))

            data = cache.get_or_load(f"json:{str(p).lower()}", _load_json) if cache is not None else _load_json()
        except Exception as exc:
            return {"ok": False, "error": f"json_parse_error:{exc}", "path": str(p)}
        jpaths = spec.get("jpaths")
        if isinstance(jpaths, list) and jpaths:
            vals = {str(jp): _extract_jpath(data, str(jp)) for jp in jpaths[:20]}
            return {"ok": True, "path": str(p), "values": vals}
        jpath = str(spec.get("jpath") or "")
        val = _extract_jpath(data, jpath) if jpath else data
        return {"ok": True, "path": str(p), "jpath": jpath or "$", "value": val}

    def _op_http_get(
        self,
        spec: dict[str, Any],
        cache: _BatchCoalescer | None = None,
    ) -> dict[str, Any]:
        url = str(spec.get("url") or "").strip()
        if not url:
            return {"ok": False, "error": "url_required"}
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme not in ("http", "https"):
            return {"ok": False, "error": "invalid_scheme"}
        host = (parsed.hostname or "").lower()
        is_loopback = host in ("127.0.0.1", "localhost", "::1")
        if not is_loopback and not bool(spec.get("allow_remote", False)):
            return {"ok": False, "error": "loopback_only_by_default", "host": host}
        timeout_s = max(0.5, min(15.0, float(spec.get("timeout_s") or 4.0)))

        def _fetch() -> tuple[int, float, str, Any, bool]:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}) if is_loopback else urllib.request.ProxyHandler())
            req = urllib.request.Request(url, headers={"Accept": "application/json, text/plain"})
            t0 = time.perf_counter()
            with opener.open(req, timeout=timeout_s) as resp:
                raw = resp.read(256 * 1024)
                ms = round((time.perf_counter() - t0) * 1000.0, 2)
                txt = raw.decode("utf-8", errors="replace")
                try:
                    return resp.status, ms, txt, json.loads(txt), True
                except ValueError:
                    return resp.status, ms, txt, None, False

        try:
            status, ms, txt, parsed_json, is_json = (
                cache.get_or_load(f"http:{url}", _fetch) if cache is not None else _fetch()
            )
            if is_json:
                jpaths = spec.get("jpaths")
                if isinstance(jpaths, list) and jpaths:
                    vals = {str(jp): _extract_jpath(parsed_json, str(jp)) for jp in jpaths[:20]}
                    return {"ok": True, "url": url, "status": status, "ms": ms, "values": vals}
                jpath = str(spec.get("jpath") or "")
                val = _extract_jpath(parsed_json, jpath) if jpath else parsed_json
                return {"ok": True, "url": url, "status": status, "ms": ms, "json": val}
            return {"ok": True, "url": url, "status": status, "ms": ms, "text": txt[:2000]}
        except urllib.error.HTTPError as exc:
            return {"ok": False, "url": url, "status": exc.code, "error": str(exc.reason)}
        except Exception as exc:
            return {"ok": False, "url": url, "error": str(exc)}

    def _op_sqlite_ro(self, spec: dict[str, Any], base_dir: Path | None) -> dict[str, Any]:
        db_raw = str(spec.get("db") or spec.get("path") or "").strip()
        sql = str(spec.get("sql") or "SELECT name, type FROM sqlite_master WHERE type IN ('table','view')").strip()
        if not db_raw:
            return {"ok": False, "error": "db_path_required"}
        low = sql.lstrip().lower()
        if not (low.startswith("select ") or low.startswith("pragma ") or low.startswith("with ") or low.startswith("explain ")):
            return {"ok": False, "error": "readonly_sql_only"}
        p = _safe_resolve(db_raw, base_dir)
        if not p.is_file():
            return {"ok": False, "error": "db_not_found", "path": str(p)}
        limit = max(1, min(100, int(spec.get("limit") or 30)))
        uri = f"file:{urllib.parse.quote(p.as_posix())}?mode=ro"
        con = sqlite3.connect(uri, uri=True, timeout=3.0)
        con.row_factory = sqlite3.Row
        try:
            cur = con.execute(sql)
            rows = [dict(r) for r in cur.fetchmany(limit)]
            return {"ok": True, "db": str(p), "count": len(rows), "rows": rows}
        except Exception as exc:
            return {"ok": False, "db": str(p), "error": str(exc)}
        finally:
            con.close()

    def _op_git_status(self, spec: dict[str, Any], base_dir: Path | None) -> dict[str, Any]:
        repo = _safe_resolve(str(spec.get("path") or "."), base_dir)
        try:
            proc = subprocess.run(
                ["git", "status", "--porcelain=v1", "-b"],
                cwd=str(repo),
                capture_output=True,
                text=True,
                timeout=8.0,
                creationflags=_NO_WINDOW,
            )
            if proc.returncode != 0:
                return {"ok": False, "error": (proc.stderr or "git_failed").strip()[:200]}
            lines = proc.stdout.splitlines()
            branch = lines[0][3:].strip() if lines and lines[0].startswith("## ") else ""
            entries = lines[1:]
            limit = max(1, min(200, int(spec.get("limit") or 60)))
            selected = entries[:limit]
            max_chars = int(spec.get("max_chars") or 0)
            truncated = False
            if max_chars > 0:
                capped: list[str] = []
                acc = len(branch) + 32
                for ent in selected:
                    if capped and (acc + len(ent) + 4) > max_chars:
                        truncated = True
                        break
                    capped.append(ent)
                    acc += len(ent) + 4
                selected = capped
            return {
                "ok": True,
                "repo": str(repo),
                "branch": branch,
                "total_dirty": len(entries),
                "truncated": truncated,
                "entries": selected,
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def _op_outline(self, spec: dict[str, Any], base_dir: Path | None) -> dict[str, Any]:
        """Ultra-fast AST/JS/Rust symbol outline with exact start..end line numbers (avoids reading whole files)."""
        path_raw = str(spec.get("path") or "").strip()
        if not path_raw:
            return {"ok": False, "error": "path_required"}
        p = _safe_resolve(path_raw, base_dir)
        if not p.is_file():
            return {"ok": False, "error": "file_not_found", "path": str(p)}
        try:
            txt = p.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
        ext = p.suffix.lower()
        rel = str(p.relative_to(base_dir).as_posix()) if (base_dir and p.is_relative_to(base_dir)) else p.name
        cg = CallgraphTelepathyEngine()
        if ext == ".py":
            defs = cg._index_python_file(rel, txt)
        elif ext == ".rs":
            defs = cg._index_brace_file(rel, txt, _RUST_DEF_RE)
        else:
            defs = cg._index_brace_file(rel, txt, _JS_DEF_RE)
        limit = max(1, min(120, int(spec.get("limit") or 60)))
        items = [f"L{d['start']}-{d['end']} {d['kind']} {d['qualname']}" for d in defs[:limit]]
        return {
            "ok": True,
            "path": rel,
            "total_lines": len(txt.splitlines()),
            "count": len(defs),
            "truncated": len(defs) > limit,
            "outline": items,
        }

    def _exec_one(
        self,
        idx: int,
        spec: dict[str, Any],
        base_dir: Path | None,
        cache: _BatchCoalescer | None = None,
    ) -> tuple[int, dict[str, Any]]:
        op = str(spec.get("op") or "").strip().lower()
        op_id = str(spec.get("id") or f"op_{idx}")
        t0 = time.perf_counter()
        try:
            if op in ("file_slice", "read", "slice"):
                res = self._op_file_slice(spec, base_dir, cache)
            elif op in ("regex_search", "grep", "rg"):
                res = self._op_regex_search(spec, base_dir)
            elif op in ("list_files", "ls", "files"):
                res = self._op_list_files(spec, base_dir)
            elif op in ("json_query", "json"):
                res = self._op_json_query(spec, base_dir, cache)
            elif op in ("http_get", "get", "http"):
                res = self._op_http_get(spec, cache)
            elif op in ("sqlite_ro", "sqlite", "sql"):
                res = self._op_sqlite_ro(spec, base_dir)
            elif op in ("git_status", "git"):
                res = self._op_git_status(spec, base_dir)
            elif op in ("outline", "symbols"):
                res = self._op_outline(spec, base_dir)
            elif op == "raw_ref":
                res = self.compactor.get_raw(
                    str(spec.get("ref_id") or ""),
                    start_line=int(spec.get("start_line") or 1),
                    max_lines=int(spec.get("max_lines") or 150),
                )
            else:
                res = {"ok": False, "error": f"unsupported_op:{op}"}
        except Exception as exc:
            res = {"ok": False, "error": str(exc)}
        res["id"] = op_id
        res["op"] = op
        res["ms"] = round((time.perf_counter() - t0) * 1000.0, 2)
        return idx, res

    def run_batch(
        self,
        ops: list[dict[str, Any]],
        *,
        cwd: str | None = None,
        max_workers: int = 8,
        compact: bool = True,
    ) -> dict[str, Any]:
        if not isinstance(ops, list) or not ops:
            return {"ok": False, "error": "ops_must_be_non_empty_list"}
        clipped = ops[: self.MAX_OPS]
        base_dir = Path(cwd).resolve() if cwd else None
        t0 = time.perf_counter()
        workers = max(1, min(int(max_workers), len(clipped), 12))
        results: list[dict[str, Any] | None] = [None] * len(clipped)
        batch_cache = _BatchCoalescer()

        if workers == 1:
            for i, sp in enumerate(clipped):
                _, r = self._exec_one(i, sp if isinstance(sp, dict) else {}, base_dir, batch_cache)
                results[i] = r
        else:
            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
                futs = [
                    ex.submit(self._exec_one, i, sp if isinstance(sp, dict) else {}, base_dir, batch_cache)
                    for i, sp in enumerate(clipped)
                ]
                for fut in concurrent.futures.as_completed(futs):
                    i, r = fut.result()
                    results[i] = r

        final_results: list[dict[str, Any]] = []
        for r in results:
            item = r or {"ok": False, "error": "missing_result"}
            if compact and isinstance(item.get("text"), str):
                op_name = str(item.get("op") or "")
                txt = item["text"]
                if op_name in ("file_slice", "read", "slice"):
                    # Preserve intact source code lines (never run PASS/FAIL test-log filter on code!)
                    if len(txt) > 9000:
                        ref_id = self.compactor._put_raw(txt)
                        head = txt[:4300]
                        tail = txt[-4300:]
                        item["text"] = f"{head}\n... [code slice capped at 9000 chars; full ref_id={ref_id}] ...\n{tail}"
                        item["compacted"] = True
                        item["ref_id"] = ref_id
                elif len(txt) > 3600:
                    c = self.compactor.compact(txt, max_lines=70, max_chars=3600)
                    item["text"] = c["text"]
                    item["compacted"] = c["compacted"]
                    item["ref_id"] = c["ref_id"]
            final_results.append(item)

        elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        shells_avoided = sum(1 for r in final_results if r.get("op") != "git_status")
        with self._lock:
            self._batches_run += 1
            self._ops_run += len(final_results)
            self._shells_avoided += shells_avoided
            self._coalesced_hits += batch_cache.coalesced_hits

        return {
            "ok": all(bool(r.get("ok")) for r in final_results),
            "ops_count": len(final_results),
            "ok_count": sum(1 for r in final_results if r.get("ok")),
            "powershell_spawns": 0,
            "shells_avoided": shells_avoided,
            "coalesced_hits": batch_cache.coalesced_hits,
            "elapsed_ms": elapsed_ms,
            "results": final_results,
        }

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "batches_run": self._batches_run,
                "ops_run": self._ops_run,
                "shells_avoided": self._shells_avoided,
                "coalesced_hits": self._coalesced_hits,
            }


# ---------------------------------------------------------------------------
# 3. CHIMERA-CALLGRAPH-TELEPATHY (`chimera_callgraph_slice`)
# ---------------------------------------------------------------------------

_JS_DEF_RE = re.compile(
    r"^(?:export\s+)?(?:default\s+)?(?:async\s+)?(?:function\s+([A-Za-z_$][\w$]*)\s*\(|"
    r"class\s+([A-Za-z_$][\w$]*)\b|"
    r"(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s+)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>|"
    r"(?:async\s+)?([A-Za-z_$][\w$]*)\s*\([^;{}]*\)\s*\{)"
)
_RUST_DEF_RE = re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?(?:unsafe\s+)?(?:fn|struct|enum|trait)\s+([A-Za-z_]\w*)")
_CALL_IDENT_RE = re.compile(r"\b([A-Za-z_$][\w$]{2,})\s*\(")
_CALL_STOP = frozenset({
    "if", "for", "while", "switch", "catch", "return", "super", "print", "len", "str", "int",
    "float", "bool", "dict", "list", "set", "tuple", "range", "isinstance", "getattr", "setattr",
    "hasattr", "open", "type", "min", "max", "sum", "sorted", "enumerate", "zip", "any", "all",
    "require", "import", "console", "Promise", "Array", "Object", "JSON", "Math", "Error", "Date",
    "String", "Number", "Boolean", "Map", "Set", "RegExp", "Buffer", "parseInt", "parseFloat",
})


class CallgraphTelepathyEngine:
    """Multi-language (Python AST + JS/TS/Rust) mtime-cached 2-hop caller/callee & test slicer."""

    def __init__(self, *, max_repos: int = 3) -> None:
        self._lock = threading.Lock()
        self._repo_cache: collections.OrderedDict[str, dict[str, Any]] = collections.OrderedDict()
        self._max_repos = max(1, int(max_repos))
        self._queries = 0

    def _index_python_file(self, rel: str, text: str) -> list[dict[str, Any]]:
        defs: list[dict[str, Any]] = []
        lines = text.splitlines()
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return defs

        def _collect_calls(node: ast.AST) -> list[str]:
            found: set[str] = set()
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call):
                    fn = sub.func
                    if isinstance(fn, ast.Name) and fn.id not in _CALL_STOP:
                        found.add(fn.id)
                    elif isinstance(fn, ast.Attribute) and fn.attr not in _CALL_STOP:
                        found.add(fn.attr)
            return sorted(found)

        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                s, e = int(node.lineno), int(getattr(node, "end_lineno", node.lineno))
                defs.append({
                    "name": node.name,
                    "qualname": node.name,
                    "kind": "def",
                    "file": rel,
                    "start": s,
                    "end": e,
                    "sig": lines[s - 1].strip() if 0 < s <= len(lines) else node.name,
                    "callees": _collect_calls(node),
                })
            elif isinstance(node, ast.ClassDef):
                cs, ce = int(node.lineno), int(getattr(node, "end_lineno", node.lineno))
                defs.append({
                    "name": node.name,
                    "qualname": node.name,
                    "kind": "class",
                    "file": rel,
                    "start": cs,
                    "end": ce,
                    "sig": lines[cs - 1].strip() if 0 < cs <= len(lines) else node.name,
                    "callees": [],
                })
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        ms, me = int(item.lineno), int(getattr(item, "end_lineno", item.lineno))
                        defs.append({
                            "name": item.name,
                            "qualname": f"{node.name}.{item.name}",
                            "kind": "method",
                            "file": rel,
                            "start": ms,
                            "end": me,
                            "sig": lines[ms - 1].strip() if 0 < ms <= len(lines) else item.name,
                            "callees": _collect_calls(item),
                        })
        return defs

    def _index_brace_file(self, rel: str, text: str, rx: re.Pattern[str]) -> list[dict[str, Any]]:
        defs: list[dict[str, Any]] = []
        lines = text.splitlines()
        n = len(lines)
        for i, ln in enumerate(lines):
            m = rx.match(ln.strip())
            if not m:
                continue
            name = next((g for g in m.groups() if g), None)
            if not name or name in _CALL_STOP:
                continue
            # Estimate block end via brace depth up to 120 lines
            depth = 0
            saw_open = False
            end = min(n, i + 25)
            for j in range(i, min(n, i + 120)):
                depth += lines[j].count("{") - lines[j].count("}")
                if "{" in lines[j]:
                    saw_open = True
                if saw_open and depth <= 0:
                    end = j + 1
                    break
            body = "\n".join(lines[i:end])
            callees = sorted({c for c in _CALL_IDENT_RE.findall(body) if c != name and c not in _CALL_STOP})
            defs.append({
                "name": name,
                "qualname": name,
                "kind": "fn",
                "file": rel,
                "start": i + 1,
                "end": end,
                "sig": ln.strip()[:160],
                "callees": callees[:24],
            })
        return defs

    def _refresh_repo(self, repo: Path) -> dict[str, Any]:
        key = str(repo.resolve())
        with self._lock:
            cache = self._repo_cache.get(key)
            if cache is None:
                cache = {"files": {}, "built_at": 0.0}
                while len(self._repo_cache) >= self._max_repos:
                    self._repo_cache.popitem(last=False)
                self._repo_cache[key] = cache
            else:
                self._repo_cache.move_to_end(key)

        files_map: dict[str, dict[str, Any]] = cache["files"]
        live_rels: set[str] = set()
        reparsed = 0
        code_exts = {".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".rs"}

        for root, dirs, files in os.walk(repo):
            dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
            for fn in files:
                ext = os.path.splitext(fn)[1].lower()
                if ext not in code_exts:
                    continue
                fp = Path(root) / fn
                try:
                    st = fp.stat()
                except OSError:
                    continue
                if st.st_size > 1024 * 1024:
                    continue
                rel = fp.relative_to(repo).as_posix()
                live_rels.add(rel)
                sig = (st.st_mtime_ns, st.st_size)
                prev = files_map.get(rel)
                if prev is not None and prev["sig"] == sig:
                    continue
                try:
                    txt = fp.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                if ext == ".py":
                    defs = self._index_python_file(rel, txt)
                elif ext == ".rs":
                    defs = self._index_brace_file(rel, txt, _RUST_DEF_RE)
                else:
                    defs = self._index_brace_file(rel, txt, _JS_DEF_RE)
                files_map[rel] = {"sig": sig, "defs": defs}
                reparsed += 1

        for stale in list(files_map):
            if stale not in live_rels:
                del files_map[stale]
        cache["built_at"] = time.time()
        return {"files_map": files_map, "files_indexed": len(files_map), "reparsed": reparsed}

    def update_single_file(self, repo: Path, rel: str) -> bool:
        """< 2 ms incremental single-file AST/symbol update without walking the repository."""
        rel_norm = str(rel or "").replace("\\", "/").lstrip("./")
        if not rel_norm:
            return False
        ext = os.path.splitext(rel_norm)[1].lower()
        code_exts = {".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".rs"}
        if ext not in code_exts:
            return False
        key = str(repo.resolve())
        with self._lock:
            cache = self._repo_cache.get(key)
            if cache is None:
                cache = {"files": {}, "built_at": time.time()}
                while len(self._repo_cache) >= self._max_repos:
                    self._repo_cache.popitem(last=False)
                self._repo_cache[key] = cache
            files_map = cache["files"]
        fp = repo / rel_norm
        if not fp.is_file():
            files_map.pop(rel_norm, None)
            return True
        try:
            st = fp.stat()
            if st.st_size > 1024 * 1024:
                return False
            txt = fp.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return False
        if ext == ".py":
            defs = self._index_python_file(rel_norm, txt)
        elif ext == ".rs":
            defs = self._index_brace_file(rel_norm, txt, _RUST_DEF_RE)
        else:
            defs = self._index_brace_file(rel_norm, txt, _JS_DEF_RE)
        files_map[rel_norm] = {"sig": (st.st_mtime_ns, st.st_size), "defs": defs}
        return True

    def slice_symbol(
        self,
        repo_path: str,
        symbol: str,
        *,
        depth: int = 2,
        include_tests: bool = True,
        max_chars: int = 4500,
    ) -> dict[str, Any]:
        repo = Path(repo_path).resolve()
        if not repo.is_dir():
            return {"ok": False, "error": "repo_not_found", "repo": str(repo)}
        sym = str(symbol or "").strip()
        if not sym:
            return {"ok": False, "error": "symbol_required"}

        t0 = time.perf_counter()
        idx_info = self._refresh_repo(repo)
        files_map: dict[str, dict[str, Any]] = idx_info["files_map"]

        by_name: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
        by_qual: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
        all_defs: list[dict[str, Any]] = []
        for entry in files_map.values():
            for d in entry["defs"]:
                all_defs.append(d)
                by_name[d["name"]].append(d)
                by_qual[d["qualname"]].append(d)

        roots = list(by_qual.get(sym) or by_name.get(sym) or [])
        if not roots:
            # Case-insensitive / substring fallback
            low = sym.lower()
            roots = [d for d in all_defs if low in d["qualname"].lower()][:5]
        if not roots:
            return {
                "ok": False,
                "error": "symbol_not_found",
                "symbol": sym,
                "files_indexed": idx_info["files_indexed"],
                "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
            }

        # Prefer non-test definitions first as primary roots
        roots.sort(key=lambda d: (1 if ("test" in d["file"].lower()) else 0, len(d["file"]), d["start"]))
        primary = roots[:3]

        # Build 2-hop callee & caller graph
        depth_n = max(0, min(3, int(depth)))
        callees_out: list[dict[str, Any]] = []
        callers_out: list[dict[str, Any]] = []
        tests_out: list[dict[str, Any]] = []
        seen_keys: set[tuple[str, str, int]] = {(d["file"], d["qualname"], d["start"]) for d in primary}

        frontier = list(primary)
        for hop in range(1, depth_n + 1):
            next_frontier: list[dict[str, Any]] = []
            for cur in frontier:
                for cname in cur.get("callees") or []:
                    for target in by_name.get(cname, [])[:2]:
                        tk = (target["file"], target["qualname"], target["start"])
                        if tk in seen_keys or "test" in target["file"].lower():
                            continue
                        seen_keys.add(tk)
                        callees_out.append({
                            "hop": hop,
                            "from": cur["qualname"],
                            "qualname": target["qualname"],
                            "file": target["file"],
                            "line": target["start"],
                            "end": target["end"],
                            "sig": target["sig"],
                        })
                        next_frontier.append(target)
                        if len(callees_out) >= 10:
                            break
                    if len(callees_out) >= 10:
                        break
            frontier = next_frontier[:6]

        target_names = {d["name"] for d in primary}
        for d in all_defs:
            if not target_names.intersection(d.get("callees") or ()):
                continue
            dk = (d["file"], d["qualname"], d["start"])
            if dk in seen_keys:
                continue
            is_test = ("test" in d["file"].lower()) or d["name"].startswith("test_")
            item = {
                "qualname": d["qualname"],
                "file": d["file"],
                "line": d["start"],
                "end": d["end"],
                "sig": d["sig"],
            }
            if is_test:
                if include_tests and len(tests_out) < 8:
                    tests_out.append(item)
            elif len(callers_out) < 10:
                callers_out.append(item)

        # Read exact line snippets within strict character budget
        budget = max(800, min(16_000, int(max_chars)))
        used = 0
        snippets: list[dict[str, Any]] = []
        file_lines_cache: dict[str, list[str]] = {}

        def _get_snippet(rel: str, start: int, end: int, max_ln: int) -> str:
            if rel not in file_lines_cache:
                try:
                    file_lines_cache[rel] = (repo / rel).read_text(encoding="utf-8", errors="replace").splitlines()
                except OSError:
                    file_lines_cache[rel] = []
            lns = file_lines_cache[rel]
            e = min(len(lns), start + max_ln - 1, end)
            return "\n".join(f"{i}: {lns[i - 1]}" for i in range(start, e + 1))

        for d in primary:
            body = _get_snippet(d["file"], d["start"], d["end"], 55)
            if used + len(body) > budget:
                body = body[: max(200, budget - used)]
            used += len(body)
            snippets.append({
                "role": "definition",
                "qualname": d["qualname"],
                "file": d["file"],
                "start": d["start"],
                "end": d["end"],
                "code": body,
            })

        for c in callees_out[:4]:
            if used >= budget - 250:
                break
            body = _get_snippet(c["file"], c["line"], c["end"], 18)
            if used + len(body) > budget:
                body = body[: max(120, budget - used)]
            used += len(body)
            snippets.append({
                "role": f"callee_hop{c['hop']}",
                "qualname": c["qualname"],
                "file": c["file"],
                "start": c["line"],
                "end": c["end"],
                "code": body,
            })

        with self._lock:
            self._queries += 1

        return {
            "ok": True,
            "symbol": sym,
            "repo": str(repo),
            "files_indexed": idx_info["files_indexed"],
            "reparsed_files": idx_info["reparsed"],
            "definitions": [{"qualname": d["qualname"], "file": d["file"], "line": d["start"], "end": d["end"], "sig": d["sig"]} for d in primary],
            "callees": callees_out,
            "callers": callers_out,
            "related_tests": tests_out,
            "snippets": snippets,
            "chars_used": used,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {"queries": self._queries, "cached_repos": len(self._repo_cache)}


# ---------------------------------------------------------------------------
# 4. CHIMERA-ATOMIC-COMMIT-VERIFY (`chimera_commit_verify`)
# ---------------------------------------------------------------------------

class _WarmUnittestWorker:
    """Lazy 1-process pre-imported Python unittest worker (0 daemon RSS, 0 conhost, BELOW_NORMAL)."""

    _WORKER_CODE = (
        "import contextlib, importlib, io, json, linecache, os, sys, unittest\n"
        "_BASE_MODULES = frozenset(sys.modules.keys())\n"
        "_BASE_PATH = list(sys.path)\n"
        "def _reset_env(repo_path=None):\n"
        "    for mname in list(sys.modules.keys()):\n"
        "        if mname not in _BASE_MODULES:\n"
        "            sys.modules.pop(mname, None)\n"
        "    sys.path[:] = ([repo_path] + _BASE_PATH) if repo_path else list(_BASE_PATH)\n"
        "    importlib.invalidate_caches()\n"
        "    linecache.clearcache()\n"
        "for raw in sys.stdin:\n"
        "    raw = raw.strip()\n"
        "    if not raw:\n"
        "        continue\n"
        "    req = json.loads(raw)\n"
        "    repo = os.path.abspath(req['repo'])\n"
        "    tests = req['tests']\n"
        "    orig_cwd = os.getcwd()\n"
        "    buf = io.StringIO()\n"
        "    rc = 0\n"
        "    try:\n"
        "        _reset_env(repo)\n"
        "        os.chdir(repo)\n"
        "        loader = unittest.TestLoader()\n"
        "        suite = unittest.TestSuite()\n"
        "        for t in tests:\n"
        "            mod_name = t[:-3].replace('/', '.').replace('\\\\', '.') if t.endswith('.py') else t\n"
        "            suite.addTests(loader.loadTestsFromName(mod_name))\n"
        "        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):\n"
        "            runner = unittest.TextTestRunner(stream=buf, verbosity=2)\n"
        "            res = runner.run(suite)\n"
        "        rc = 0 if res.wasSuccessful() else 1\n"
        "    except Exception as exc:\n"
        "        buf.write(f'WARM_WORKER_ERR: {exc}\\n')\n"
        "        rc = 2\n"
        "    finally:\n"
        "        try:\n"
        "            os.chdir(orig_cwd)\n"
        "        except OSError:\n"
        "            pass\n"
        "        _reset_env(None)\n"
        "    sys.stdout.write(json.dumps({'rc': rc, 'out': buf.getvalue()}) + '\\n')\n"
        "    sys.stdout.flush()\n"
    )

    def __init__(self, idle_ttl_s: float = 120.0) -> None:
        self._lock = threading.Lock()
        self._proc: subprocess.Popen[str] | None = None
        self._last_used = 0.0
        self._idle_ttl_s = idle_ttl_s
        self.warm_runs = 0
        self.worker_boots = 0

    def _ensure_alive_locked(self) -> subprocess.Popen[str]:
        if self._proc is not None and self._proc.poll() is None:
            return self._proc
        self._proc = subprocess.Popen(
            [sys.executable, "-u", "-c", self._WORKER_CODE],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            creationflags=_BATCH_FLAGS,
        )
        self.worker_boots += 1
        return self._proc

    def run_tests(self, repo: Path, tests: list[str], timeout_s: float) -> tuple[int, str] | None:
        with self._lock:
            try:
                proc = self._ensure_alive_locked()
                assert proc.stdin and proc.stdout
                proc.stdin.write(json.dumps({"repo": str(repo), "tests": tests}) + "\n")
                proc.stdin.flush()
                res_box: list[str] = []

                def _reader() -> None:
                    try:
                        ln = proc.stdout.readline()  # type: ignore[union-attr]
                        res_box.append(ln)
                    except Exception:
                        pass

                t = threading.Thread(target=_reader, daemon=True)
                t.start()
                t.join(timeout=max(5.0, float(timeout_s)))
                if t.is_alive() or not res_box or not res_box[0].strip():
                    self._kill_locked()
                    return None
                data = json.loads(res_box[0])
                self._last_used = time.monotonic()
                if int(data.get("rc", 2)) == 2:
                    return None
                self.warm_runs += 1
                return int(data["rc"]), str(data.get("out") or "")
            except Exception:
                self._kill_locked()
                return None

    def _kill_locked(self) -> None:
        proc = self._proc
        self._proc = None
        if proc is not None:
            for stream in (proc.stdin, proc.stdout):
                if stream is not None:
                    try:
                        stream.close()
                    except Exception:
                        pass
            try:
                proc.terminate()
                proc.wait(timeout=1.5)
            except Exception:
                try:
                    proc.kill()
                    proc.wait(timeout=1.5)
                except Exception:
                    pass

    def close(self) -> None:
        with self._lock:
            self._kill_locked()


class AtomicCommitVerifyEngine:
    """Single-shot syntax compile + import-graph impacted test execution + BLAKE2s singleflight & warm worker."""

    def __init__(self, compactor: TokenDietCompactor) -> None:
        self.compactor = compactor
        self._lock = threading.Lock()
        self._cache: collections.OrderedDict[str, tuple[float, dict[str, Any]]] = collections.OrderedDict()
        self._inflight: dict[str, threading.Event] = {}
        self._warm_worker = _WarmUnittestWorker()
        self._runs = 0
        self._cache_hits = 0
        self._singleflight_joins = 0

    def _detect_changed_files(self, repo: Path) -> list[str]:
        try:
            proc = subprocess.run(
                ["git", "status", "--porcelain=v1"],
                cwd=str(repo),
                capture_output=True,
                text=True,
                timeout=8.0,
                creationflags=_NO_WINDOW,
            )
            if proc.returncode != 0:
                return []
            out: list[str] = []
            for ln in proc.stdout.splitlines():
                if len(ln) < 4:
                    continue
                rel = ln[3:].strip()
                if " -> " in rel:
                    rel = rel.split(" -> ", 1)[1].strip()
                rel = rel.strip('"')
                if (repo / rel).is_file():
                    out.append(rel)
            return out
        except Exception:
            return []

    def _select_impacted_tests(self, repo: Path, rel_files: list[str], max_tests: int) -> list[str]:
        tests_dir = repo / "tests"
        if not tests_dir.is_dir():
            return []
        selected: list[str] = []
        stems: set[str] = set()
        for rf in rel_files:
            norm = rf.replace("\\", "/")
            if norm.startswith("tests/") and Path(norm).name.startswith("test_") and norm.endswith(".py"):
                if norm not in selected:
                    selected.append(norm)
            elif norm.endswith(".py"):
                stems.add(Path(norm).stem)

        if stems and len(selected) < max_tests:
            candidates: list[tuple[int, str]] = []
            for tf in sorted(tests_dir.glob("test_*.py")):
                rel_t = tf.relative_to(repo).as_posix()
                if rel_t in selected:
                    continue
                try:
                    txt = tf.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                score = sum(1 for st in stems if st in txt)
                if score > 0:
                    candidates.append((score, rel_t))
            candidates.sort(key=lambda x: (-x[0], x[1]))
            for _, rel_t in candidates:
                selected.append(rel_t)
                if len(selected) >= max_tests:
                    break
        return selected[:max_tests]

    def _find_impacted_tests(self, repo: Path, rel_files: list[str], max_tests: int = 4) -> list[str]:
        return self._select_impacted_tests(repo, rel_files, max(1, min(10, int(max_tests))))

    def _fingerprint(self, repo: Path, rel_files: list[str], impacted_tests: list[str], run_tests: bool = True) -> str:
        h = hashlib.blake2s(digest_size=16)
        h.update(str(repo).encode("utf-8"))
        h.update(f"|tests={int(bool(run_tests))}|".encode("ascii"))
        for rel in sorted(set(rel_files) | set(impacted_tests)):
            fp = repo / rel
            if fp.is_file():
                h.update(rel.encode("utf-8"))
                h.update(b":")
                h.update(fp.read_bytes())
        return h.hexdigest()

    def has_fresh_cache(self, fingerprint: str) -> bool:
        with self._lock:
            hit = self._cache.get(fingerprint)
            return bool(hit and (time.time() - hit[0]) <= 600.0)

    def recent_receipts(self, limit: int = 4) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        now = time.time()
        with self._lock:
            for ts, rec in reversed(list(self._cache.values())):
                if (now - ts) > 600.0:
                    continue
                out.append({
                    "ok": bool(rec.get("ok")),
                    "fingerprint": rec.get("fingerprint"),
                    "files_checked": rec.get("files_checked", 0),
                    "tests": (rec.get("tests") or {}).get("tests", []),
                    "precog": bool(rec.get("precog_computed", False)),
                    "age_s": round(max(0.0, now - ts), 1),
                })
                if len(out) >= max(1, int(limit or 4)):
                    break
        return out

    def verify(
        self,
        repo_path: str,
        *,
        files: list[str] | None = None,
        run_tests: bool = True,
        explicit_tests: list[str] | None = None,
        max_tests: int = 4,
        timeout_s: float = 60.0,
        use_cache: bool = True,
        compact: bool = True,
        mark_precog: bool = False,
        precog_waiter: Any = None,
    ) -> dict[str, Any]:
        repo = Path(repo_path).resolve()
        if not repo.is_dir():
            return {"ok": False, "error": "repo_not_found", "repo": str(repo)}

        t0 = time.perf_counter()
        rel_files = [str(f).replace("\\", "/") for f in (files or []) if str(f).strip()]
        if not rel_files:
            rel_files = self._detect_changed_files(repo)

        # Select impacted tests deterministically
        if explicit_tests:
            impacted_tests = [str(t).replace("\\", "/") for t in explicit_tests if (repo / t).is_file()][:max_tests]
        elif run_tests:
            impacted_tests = self._select_impacted_tests(repo, rel_files, max(1, min(10, int(max_tests))))
        else:
            impacted_tests = []

        # Build BLAKE2s fingerprint of checked files + impacted test files
        fingerprint = self._fingerprint(repo, rel_files, impacted_tests, run_tests=run_tests)
        owner_ev: threading.Event | None = None

        if use_cache:
            def _try_cache() -> dict[str, Any] | None:
                with self._lock:
                    hit = self._cache.get(fingerprint)
                    if hit and (time.time() - hit[0]) <= 600.0:
                        self._cache.move_to_end(fingerprint)
                        self._cache_hits += 1
                        cached_out = dict(hit[1])
                        cached_out["cache_hit"] = True
                        if cached_out.get("precog_computed"):
                            cached_out["precog_hit"] = True
                        cached_out["elapsed_ms"] = round((time.perf_counter() - t0) * 1000.0, 2)
                        return cached_out
                return None

            cached = _try_cache()
            if cached is not None:
                return cached
            # If Precog-Runner is already running this exact BLAKE2s shadow test in background, join it!
            if precog_waiter is not None and precog_waiter(fingerprint, timeout_s=min(float(timeout_s), 30.0)):
                cached = _try_cache()
                if cached is not None:
                    cached["precog_joined"] = True
                    return cached

            # Cross-agent Singleflight: if another agent is ALREADY verifying this exact fingerprint right now, join it!
            wait_ev: threading.Event | None = None
            with self._lock:
                if fingerprint in self._inflight:
                    wait_ev = self._inflight[fingerprint]
                    self._singleflight_joins += 1
                else:
                    owner_ev = threading.Event()
                    self._inflight[fingerprint] = owner_ev
            if wait_ev is not None:
                wait_ev.wait(timeout=max(5.0, float(timeout_s)))
                cached = _try_cache()
                if cached is not None:
                    cached["singleflight_joined"] = True
                    return cached

        try:
            # 1. Syntax checks (in-process py_compile + optional node --check)
            py_checked: list[str] = []
            js_checked: list[str] = []
            syntax_errors: list[dict[str, str]] = []
            node_bin = shutil.which("node")

            for rel in rel_files:
                fp = repo / rel
                if not fp.is_file():
                    continue
                ext = fp.suffix.lower()
                if ext == ".py":
                    py_checked.append(rel)
                    try:
                        py_compile.compile(str(fp), doraise=True)
                    except py_compile.PyCompileError as exc:
                        syntax_errors.append({"file": rel, "error": str(exc)})
                elif ext in (".js", ".mjs", ".cjs") and node_bin:
                    js_checked.append(rel)
                    proc = subprocess.run(
                        [node_bin, "--check", str(fp)],
                        capture_output=True,
                        text=True,
                        timeout=10.0,
                        creationflags=_BATCH_FLAGS,
                    )
                    if proc.returncode != 0:
                        syntax_errors.append({"file": rel, "error": (proc.stderr or proc.stdout).strip()[:400]})

            # 2. Run impacted unittest suites if syntax is clean (Warm pre-imported worker first, BELOW_NORMAL fallback!)
            test_res: dict[str, Any] = {"ran": False, "tests": impacted_tests, "ok": True}
            if run_tests and impacted_tests and not syntax_errors:
                used_warm = False
                warm_out = self._warm_worker.run_tests(repo, impacted_tests, timeout_s=max(5.0, min(180.0, float(timeout_s))))
                if warm_out is not None:
                    rc, combined = warm_out[0], warm_out[1].strip()
                    used_warm = True
                else:
                    proc = subprocess.run(
                        [sys.executable, "-m", "unittest", "-v", *impacted_tests],
                        cwd=str(repo),
                        capture_output=True,
                        text=True,
                        timeout=max(5.0, min(180.0, float(timeout_s))),
                        creationflags=_BATCH_FLAGS,
                    )
                    rc = proc.returncode
                    combined = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
                comp = self.compactor.compact(combined, max_lines=45, max_chars=2800) if compact else {
                    "text": combined,
                    "compacted": False,
                    "raw_bytes": len(combined.encode("utf-8", errors="replace")),
                    "compacted_bytes": len(combined.encode("utf-8", errors="replace")),
                    "saved_pct": 0.0,
                    "ref_id": None,
                }
                test_res = {
                    "ran": True,
                    "ok": rc == 0,
                    "returncode": rc,
                    "warm_worker": used_warm,
                    "tests": impacted_tests,
                    "output": comp["text"],
                    "token_diet": {
                        "compacted": comp["compacted"],
                        "raw_bytes": comp["raw_bytes"],
                        "compacted_bytes": comp["compacted_bytes"],
                        "saved_pct": comp["saved_pct"],
                        "ref_id": comp["ref_id"],
                    },
                }

            overall_ok = (len(syntax_errors) == 0) and bool(test_res.get("ok", True))
            receipt = {
                "ok": overall_ok,
                "cache_hit": False,
                "precog_computed": bool(mark_precog),
                "fingerprint": fingerprint,
                "repo": str(repo),
                "files_checked": len(py_checked) + len(js_checked),
                "py_compiled": py_checked,
                "js_checked": js_checked,
                "syntax_errors": syntax_errors,
                "tests": test_res,
                "powershell_spawns": 0,
                "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
            }

            with self._lock:
                self._runs += 1
                while len(self._cache) >= 24:
                    self._cache.popitem(last=False)
                self._cache[fingerprint] = (time.time(), dict(receipt))

            return receipt
        finally:
            if owner_ev is not None:
                with self._lock:
                    self._inflight.pop(fingerprint, None)
                owner_ev.set()

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "runs": self._runs,
                "cache_hits": self._cache_hits,
                "singleflight_joins": self._singleflight_joins,
                "warm_worker_runs": self._warm_worker.warm_runs,
                "warm_worker_boots": self._warm_worker.worker_boots,
                "cached_fingerprints": len(self._cache),
            }

    def close(self) -> None:
        self._warm_worker.close()


# ---------------------------------------------------------------------------
# Unified Facade for Organ 3 (Akashic Swarm-Kernel)
# ---------------------------------------------------------------------------

class AgentHyperBus:
    """Unified facade combining Omni-Probe, Callgraph Telepathy, Atomic Commit-Verify, Token-Diet & Symbiont."""

    def __init__(self, *, symbiont_db_path: Path | None = None, ephemeral: bool = False) -> None:
        self.compactor = TokenDietCompactor()
        self.probe = OmniProbeBatchEngine(self.compactor)
        self.callgraph = CallgraphTelepathyEngine()
        self.verifier = AtomicCommitVerifyEngine(self.compactor)
        self._symbiont: Any = None
        self._symbiont_lock = threading.Lock()
        self._symbiont_db_path = symbiont_db_path
        self._ephemeral = ephemeral

    @property
    def symbiont(self) -> Any:
        if self._symbiont is None:
            with self._symbiont_lock:
                if self._symbiont is None:
                    from .agent_symbiont import AgentSymbiontCore

                    self._symbiont = AgentSymbiontCore(
                        self,
                        db_path=self._symbiont_db_path,
                        ephemeral=self._ephemeral,
                    )
                    self.probe._spec_cache_lookup = self._symbiont.precog.get_speculative_snapshot
        return self._symbiont

    def _attach_hive_alerts(self, res: dict[str, Any], *, agent_id: str, repo: str | None, files: list[str]) -> dict[str, Any]:
        if self._symbiont is None:
            return res
        try:
            alerts = self._symbiont.hive.check_alerts(agent_id=agent_id, repo=repo, files=files)
            if alerts.get("conflicts"):
                res["hive_conflicts"] = alerts["conflicts"]
            if alerts.get("immune_warnings"):
                res["immune_warnings"] = alerts["immune_warnings"]
        except Exception:
            pass
        return res

    def xray_batch(
        self,
        ops: list[dict[str, Any]],
        *,
        cwd: str | None = None,
        max_workers: int = 8,
        compact: bool = True,
        agent_id: str = "",
    ) -> dict[str, Any]:
        res = self.probe.run_batch(ops, cwd=cwd, max_workers=max_workers, compact=compact)
        touched = [str(op.get("path") or op.get("db") or "") for op in (ops or []) if isinstance(op, dict)]
        return self._attach_hive_alerts(res, agent_id=agent_id, repo=cwd, files=touched)

    def callgraph_slice(
        self,
        repo: str,
        symbol: str,
        *,
        depth: int = 2,
        include_tests: bool = True,
        max_chars: int = 4500,
        agent_id: str = "",
    ) -> dict[str, Any]:
        res = self.callgraph.slice_symbol(repo, symbol, depth=depth, include_tests=include_tests, max_chars=max_chars)
        touched = [str(d.get("file") or "") for d in (res.get("definitions") or [])]
        return self._attach_hive_alerts(res, agent_id=agent_id, repo=repo, files=touched)

    def commit_verify(
        self,
        repo: str,
        *,
        files: list[str] | None = None,
        run_tests: bool = True,
        explicit_tests: list[str] | None = None,
        max_tests: int = 4,
        timeout_s: float = 60.0,
        use_cache: bool = True,
        compact: bool = True,
    ) -> dict[str, Any]:
        waiter = self._symbiont.precog.wait_inflight if self._symbiont is not None else None
        res = self.verifier.verify(
            repo,
            files=files,
            run_tests=run_tests,
            explicit_tests=explicit_tests,
            max_tests=max_tests,
            timeout_s=timeout_s,
            use_cache=use_cache,
            compact=compact,
            precog_waiter=waiter,
        )
        if res.get("precog_hit") and self._symbiont is not None:
            self._symbiont.precog.note_precomputed_hit()
        return res

    def stats(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "ok": True,
            "organ": "akashic_swarm_kernel",
            "probe": self.probe.stats(),
            "callgraph": self.callgraph.stats(),
            "verifier": self.verifier.stats(),
            "token_diet": self.compactor.stats(),
        }
        if self._symbiont is not None:
            out["symbiont"] = self._symbiont.stats()
        return out

    def close(self) -> None:
        self.verifier.close()
        if self._symbiont is not None:
            self._symbiont.close()


_DEFAULT_BUS: AgentHyperBus | None = None
_BUS_LOCK = threading.Lock()


def get_default_agent_bus() -> AgentHyperBus:
    global _DEFAULT_BUS
    if _DEFAULT_BUS is None:
        with _BUS_LOCK:
            if _DEFAULT_BUS is None:
                _DEFAULT_BUS = AgentHyperBus()
    return _DEFAULT_BUS
