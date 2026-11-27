"""CHIMERA v20 ZERO-IQ-LOSS SYMBIOTE ENGINE.

Pure deterministic physical layer (NEVER downgrades reasoning effort, NEVER offloads thinking
to weaker models, NEVER mutates OpenAI reserved tool schemas):
1. Out-of-V8 Bone-Marrow LZ4 Blob Store (bounded LRU byte storage).
2. Immortal 360s Harvest Registry (bridges 360s client aborts / worker restarts).
3. Deterministic Merkle Prefix Auditor, KV-Affinity Map & SHA-256 Stale-Read Detector.
4. Zero-Completed Hot Vaccine Observer (captures root causes of any `cut=completed` leak).
5. Deterministic Precognition Hands (`py_compile`, `node --check`, untracked git detection, fast tests).
"""

from __future__ import annotations

import base64
from collections import OrderedDict, deque
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import time
from typing import Any
import uuid
import zlib

from .native import lz4_compress, lz4_decompress, v12_native_caps


_MAX_RAW_BLOB_BYTES = 4 * 1024 * 1024
_PROTECTED_PREFIXES = (".git/", "__pycache__/", "node_modules/", ".pytest_cache/", ".venv/", "venv/")
_PROTECTED_NAMES = {".env", "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "Cargo.lock"}
_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,128}$")
_TOOL_CALL_TYPES = ("function_call", "custom_tool_call")
_TOOL_OUTPUT_TYPES = ("function_call_output", "custom_tool_call_output")


class ChimeraSymbioteEngine:
    """Thread-safe deterministic physical symbiote attached to OvermindCortex."""

    def __init__(
        self,
        ops_dir: Path | str,
        *,
        pulse_bus: Any = None,
        max_blob_bytes: int = 6 * 1024 * 1024,
        max_entries: int = 256,
    ) -> None:
        self.ops_dir = Path(ops_dir)
        self._pulse = pulse_bus
        self.max_blob_bytes = max(1024, int(max_blob_bytes))
        self.max_entries = max(1, int(max_entries))
        self._lock = threading.Lock()

        # 1. Bone-Marrow LZ4 Blob Store
        self._blobs: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._current_compressed_bytes = 0
        self._blobs_stored = 0
        self._blob_hits = 0
        self._blob_misses = 0
        self._raw_bytes_in = 0
        self._compressed_bytes_in = 0
        self._lz4_saved_bytes = 0
        self._evictions = 0

        # 2. Immortal 360s Registry
        self._immortal: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._immortal_registered = 0
        self._immortal_completed = 0
        self._immortal_hits = 0

        # 3. Merkle Prefix Auditor & KV-Affinity
        self._prefix_sessions: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._prefix_audits = 0
        self._prefix_clean = 0
        self._prefix_breaks_caught = 0
        self._stale_read_audits = 0
        self._stale_read_duplicates = 0

        # 4. Zero-Completed Hot Vaccine Observer
        self._total_observed = 0
        self._autocut_count = 0
        self._completed_count = 0
        self._completed_compact_count = 0
        self._aborted_499_count = 0
        self._blocked_503_count = 0
        self._scalpel_immediate_cuts = 0
        self._completed_leaks: deque[dict[str, Any]] = deque(maxlen=64)

        # 5. Deterministic Precognition Hands
        self._precog_runs = 0
        self._precog_failures = 0

        # 6. CODEX-SURGEON Out-of-Band JSONL Repair & Time-Travel Clean Fork
        self._surgeon_heals = 0
        self._surgeon_calls_rewritten = 0
        self._surgeon_forks = 0
        self._surgeon_last_receipt: dict[str, Any] | None = None

    def _prune_blobs_locked(self, now: float) -> None:
        expired = [k for k, v in self._blobs.items() if now >= float(v.get("expires_at") or 0.0)]
        for k in expired:
            entry = self._blobs.pop(k, None)
            if entry is not None:
                self._current_compressed_bytes = max(0, self._current_compressed_bytes - int(entry["comp_len"]))

    def _evict_for_space_locked(self, incoming_bytes: int) -> None:
        while self._blobs and (
            len(self._blobs) >= self.max_entries
            or self._current_compressed_bytes + incoming_bytes > self.max_blob_bytes
        ):
            _, oldest = self._blobs.popitem(last=False)
            self._current_compressed_bytes = max(0, self._current_compressed_bytes - int(oldest["comp_len"]))
            self._evictions += 1

    @staticmethod
    def _compress_payload(raw_bytes: bytes) -> tuple[bytes, str]:
        n = len(raw_bytes)
        if n < 256:
            return raw_bytes, "raw"
        try:
            comp = lz4_compress(raw_bytes)
            if comp and len(comp) < n:
                return comp, "lz4"
        except Exception:
            comp = b""
        try:
            zcomp = zlib.compress(raw_bytes, level=3)
            if zcomp and len(zcomp) < n:
                return zcomp, "zlib"
        except Exception:
            pass
        return (comp, "lz4") if comp and len(comp) < n else (raw_bytes, "raw")

    @staticmethod
    def _decompress_payload(payload: bytes, codec: str) -> bytes:
        if codec == "raw":
            return payload
        if codec == "lz4":
            return lz4_decompress(payload)
        if codec == "zlib":
            return zlib.decompress(payload)
        raise ValueError(f"Unsupported symbiote codec: {codec}")

    def put_blob(
        self,
        raw_bytes: bytes,
        *,
        key: str | None = None,
        ttl_sec: int = 900,
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not isinstance(raw_bytes, (bytes, bytearray)):
            raise TypeError("raw_bytes must be bytes or bytearray")
        raw = bytes(raw_bytes)
        n = len(raw)
        if n > _MAX_RAW_BLOB_BYTES:
            raise ValueError(f"Blob exceeds {_MAX_RAW_BLOB_BYTES} bytes limit ({n})")

        blob_key = str(key or "").strip() or hashlib.blake2s(raw, digest_size=16).hexdigest()
        ttl = max(30, min(86_400, int(ttl_sec or 900)))
        comp, codec = self._compress_payload(raw)
        comp_len = len(comp)
        if comp_len > self.max_blob_bytes:
            raise ValueError(f"Compressed blob ({comp_len} B) exceeds store cap ({self.max_blob_bytes} B)")

        now = time.time()
        with self._lock:
            self._prune_blobs_locked(now)
            prev = self._blobs.pop(blob_key, None)
            if prev is not None:
                self._current_compressed_bytes = max(0, self._current_compressed_bytes - int(prev["comp_len"]))
            self._evict_for_space_locked(comp_len)
            self._blobs[blob_key] = {
                "data": comp,
                "codec": codec,
                "raw_len": n,
                "comp_len": comp_len,
                "expires_at": now + ttl,
                "meta": dict(meta or {}),
            }
            self._current_compressed_bytes += comp_len
            self._blobs_stored += 1
            self._raw_bytes_in += n
            self._compressed_bytes_in += comp_len
            if n > comp_len:
                self._lz4_saved_bytes += n - comp_len

        ratio = round(comp_len / n, 4) if n > 0 else 1.0
        return {
            "ok": True,
            "key": blob_key,
            "codec": codec,
            "raw_bytes": n,
            "compressed_bytes": comp_len,
            "ratio": ratio,
            "saved_bytes": max(0, n - comp_len),
        }

    def get_blob(self, key: str) -> bytes | None:
        k = str(key or "").strip()
        if not k:
            return None
        now = time.time()
        with self._lock:
            self._prune_blobs_locked(now)
            entry = self._blobs.get(k)
            if entry is None:
                self._blob_misses += 1
                return None
            self._blobs.move_to_end(k, last=True)
            self._blob_hits += 1
            payload = entry["data"]
            codec = entry["codec"]
        return self._decompress_payload(payload, codec)

    def _prune_immortal_locked(self, now: float) -> None:
        expired = [k for k, v in self._immortal.items() if now >= float(v.get("expires_at") or 0.0)]
        for k in expired:
            self._immortal.pop(k, None)
        while len(self._immortal) > 128:
            self._immortal.popitem(last=False)

    def register_immortal(
        self,
        turn_key: str,
        *,
        vault_key: str = "",
        step_sig: str = "",
        ttl_sec: int = 900,
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        tk = str(turn_key or "").strip()
        if not tk:
            return {"ok": False, "error": "missing_turn_key"}
        ss = str(step_sig or (meta or {}).get("step_sig") or "").strip()
        entry_key = f"{tk}::{ss}" if ss else tk
        now = time.time()
        ttl = max(30, min(3600, int(ttl_sec or 900)))
        with self._lock:
            self._prune_immortal_locked(now)
            existing = self._immortal.get(entry_key)
            if existing and existing.get("status") == "completed":
                self._immortal.move_to_end(entry_key, last=True)
                return {
                    "ok": True,
                    "turn_key": tk,
                    "step_sig": ss,
                    "status": "completed",
                    "vault_key": existing.get("vault_key", ""),
                }
            self._immortal[entry_key] = {
                "turn_key": tk,
                "step_sig": ss,
                "vault_key": str(vault_key or ""),
                "status": "inflight",
                "blob_key": "",
                "cut": "",
                "model": str((meta or {}).get("model") or ""),
                "effort": str((meta or {}).get("effort") or ""),
                "detached_harvest": False,
                "updated_at": now,
                "expires_at": now + ttl,
            }
            self._immortal.move_to_end(entry_key, last=True)
            self._immortal_registered += 1
        return {"ok": True, "turn_key": tk, "step_sig": ss, "status": "inflight", "vault_key": str(vault_key or "")}

    def complete_immortal(
        self,
        turn_key: str,
        sse_bytes: bytes,
        *,
        vault_key: str = "",
        step_sig: str = "",
        detached_harvest: bool = True,
        cut: str = "completed",
        model: str = "",
        effort: str = "",
        ttl_sec: int = 900,
    ) -> dict[str, Any]:
        tk = str(turn_key or "").strip()
        if not tk or not sse_bytes:
            return {"ok": False, "error": "missing_turn_key_or_bytes"}
        if not bool(detached_harvest):
            return {"ok": False, "error": "not_detached_harvest"}
        ss = str(step_sig or "").strip()
        entry_key = f"{tk}::{ss}" if ss else tk
        blob_res = self.put_blob(
            sse_bytes,
            key=f"imm_{hashlib.blake2s(entry_key.encode('utf-8'), digest_size=12).hexdigest()}",
            ttl_sec=ttl_sec,
            meta={"turn_key": tk, "step_sig": ss, "vault_key": vault_key, "cut": cut, "detached_harvest": True},
        )
        now = time.time()
        ttl = max(30, min(3600, int(ttl_sec or 900)))
        with self._lock:
            self._prune_immortal_locked(now)
            self._immortal[entry_key] = {
                "turn_key": tk,
                "step_sig": ss,
                "vault_key": str(vault_key or ""),
                "status": "completed",
                "blob_key": blob_res["key"],
                "cut": str(cut or "completed"),
                "model": str(model or ""),
                "effort": str(effort or ""),
                "detached_harvest": True,
                "raw_bytes": blob_res["raw_bytes"],
                "compressed_bytes": blob_res["compressed_bytes"],
                "updated_at": now,
                "expires_at": now + ttl,
            }
            self._immortal.move_to_end(entry_key, last=True)
            self._immortal_completed += 1
        return {
            "ok": True,
            "turn_key": tk,
            "step_sig": ss,
            "detached_harvest": True,
            "status": "completed",
            "blob_key": blob_res["key"],
            "raw_bytes": blob_res["raw_bytes"],
            "compressed_bytes": blob_res["compressed_bytes"],
        }

    def lookup_immortal(
        self,
        turn_key: str,
        *,
        step_sig: str = "",
        require_detached: bool = False,
        include_bytes: bool = False,
    ) -> dict[str, Any]:
        tk = str(turn_key or "").strip()
        if not tk:
            return {"ok": True, "found": False}
        ss = str(step_sig or "").strip()
        entry_key = f"{tk}::{ss}" if ss else tk
        now = time.time()
        with self._lock:
            self._prune_immortal_locked(now)
            entry = self._immortal.get(entry_key)
            if entry is None:
                return {"ok": True, "found": False}
            self._immortal.move_to_end(entry_key, last=True)
            snapshot = dict(entry)
        if require_detached and not bool(snapshot.get("detached_harvest", False)):
            return {"ok": True, "found": False, "reason": "not_detached_harvest"}
        if snapshot.get("status") == "completed" and snapshot.get("blob_key"):
            raw = self.get_blob(snapshot["blob_key"])
            if raw is None:
                return {"ok": True, "found": False, "reason": "blob_evicted"}
            with self._lock:
                self._immortal_hits += 1
            out = {
                "ok": True,
                "found": True,
                "status": "completed",
                "turn_key": tk,
                "step_sig": snapshot.get("step_sig", ""),
                "detached_harvest": bool(snapshot.get("detached_harvest", False)),
                "vault_key": snapshot.get("vault_key", ""),
                "cut": snapshot.get("cut", "completed"),
                "model": snapshot.get("model", ""),
                "effort": snapshot.get("effort", ""),
                "raw_bytes": len(raw),
            }
            if include_bytes:
                out["sse_b64"] = base64.b64encode(raw).decode("ascii")
            return out
        return {
            "ok": True,
            "found": True,
            "status": snapshot.get("status", "inflight"),
            "turn_key": tk,
            "step_sig": snapshot.get("step_sig", ""),
            "detached_harvest": bool(snapshot.get("detached_harvest", False)),
            "vault_key": snapshot.get("vault_key", ""),
            "model": snapshot.get("model", ""),
            "effort": snapshot.get("effort", ""),
        }

    @staticmethod
    def _merkle_root(digests: list[str]) -> str:
        acc = hashlib.blake2s(digest_size=16)
        for d in digests:
            acc.update(str(d).encode("utf-8", errors="ignore"))
            acc.update(b"\n")
        return acc.hexdigest()

    @staticmethod
    def _cumulative_prefix_hashes(digests: list[str]) -> list[str]:
        """Compute rolling cumulative prefix hashes so longest common prefix resolves in O(log N)."""
        out: list[str] = []
        prev = ""
        for d in digests:
            h = hashlib.blake2s(f"{prev}\n{d}".encode("utf-8", errors="ignore"), digest_size=8).hexdigest()
            out.append(h)
            prev = h
        return out

    @staticmethod
    def _compact_item_metas(item_metas: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
        """Keep strictly hash-only metadata (zero raw message text) capped at 256 items/session."""
        if not item_metas:
            return []
        compact: list[dict[str, Any]] = []
        for m in item_metas[:256]:
            if not isinstance(m, dict):
                compact.append({"role": "", "est_tokens": 1, "field_hashes": {}})
                continue
            raw_fh = m.get("field_hashes") if isinstance(m.get("field_hashes"), dict) else {}
            fh = {str(k)[:32]: str(v)[:32] for k, v in list(raw_fh.items())[:16]}
            compact.append(
                {
                    "role": str(m.get("role") or "")[:32],
                    "est_tokens": max(1, int(m.get("est_tokens") or 1)),
                    "field_hashes": fh,
                }
            )
        return compact

    def audit_prefix(
        self,
        session_id: str,
        item_digests: list[str],
        *,
        account_id: str = "",
        tool_outputs: list[dict[str, Any]] | None = None,
        item_metas: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        sid = str(session_id or "default").strip() or "default"
        digs = [str(x or "") for x in (item_digests or [])]
        prefix_root = self._merkle_root(digs)
        cum_hashes = self._cumulative_prefix_hashes(digs)
        cur_metas = self._compact_item_metas(item_metas)
        acct = str(account_id or "").strip()
        now = time.time()

        with self._lock:
            prev = self._prefix_sessions.get(sid)
            prev_digs = list(prev.get("digests") or []) if prev else []
            prev_cum = list(prev.get("cum_hashes") or []) if prev else []
            prev_metas = list(prev.get("item_metas") or []) if prev else []
            prev_root = str(prev.get("prefix_root") or "") if prev else ""
            prev_len = len(prev_digs)
            cur_len = len(digs)
            limit = min(prev_len, cur_len)

            # O(log N) binary search over cumulative prefix hashes when available
            if limit > 0 and len(prev_cum) >= limit:
                lo, hi = 0, limit
                while lo < hi:
                    mid = (lo + hi) // 2
                    if prev_cum[mid] == cum_hashes[mid]:
                        lo = mid + 1
                    else:
                        hi = mid
                common = lo
            else:
                common = 0
                while common < limit and prev_digs[common] == digs[common]:
                    common += 1

            mid_prefix_break = prev_len > 0 and common < limit
            truncated = prev_len > cur_len and common == cur_len
            break_index = common if mid_prefix_break else None
            stored_acct = acct or (str(prev.get("account_id") or "") if prev else "")
            matched_prefix_root = cum_hashes[common - 1] if common > 0 else ""
            sticky_key = matched_prefix_root or (digs[0] if digs else prefix_root)

            # Compute hash-only forensic diff for KV-cache break / truncation triage
            break_kind = "mutation" if mid_prefix_break else ("truncation" if truncated else "clean")
            mutated_fields: list[str] = []
            added_fields: list[str] = []
            removed_fields: list[str] = []
            role_before = ""
            role_after = ""
            if mid_prefix_break and break_index is not None:
                pm = prev_metas[break_index] if break_index < len(prev_metas) else {}
                cm = cur_metas[break_index] if break_index < len(cur_metas) else {}
                role_before = str(pm.get("role") or "")
                role_after = str(cm.get("role") or "")
                pfh = pm.get("field_hashes") if isinstance(pm.get("field_hashes"), dict) else {}
                cfh = cm.get("field_hashes") if isinstance(cm.get("field_hashes"), dict) else {}
                for k in sorted(set(pfh.keys()) | set(cfh.keys())):
                    if k not in pfh:
                        added_fields.append(k)
                    elif k not in cfh:
                        removed_fields.append(k)
                    elif pfh[k] != cfh[k]:
                        mutated_fields.append(k)

            # Token survival estimate (from prev turn's cached prefix)
            kept_tokens_est = 0
            lost_tokens_est = 0
            if prev_metas:
                kept_tokens_est = sum(int(m.get("est_tokens", 1)) for m in prev_metas[:common])
                lost_tokens_est = sum(int(m.get("est_tokens", 1)) for m in prev_metas[common:])
            elif prev_len > 0:
                kept_tokens_est = common * 64
                lost_tokens_est = max(0, prev_len - common) * 64
            total_prev_tokens = kept_tokens_est + lost_tokens_est
            cache_survival_pct = round((kept_tokens_est * 100.0 / total_prev_tokens), 2) if total_prev_tokens > 0 else 100.0

            forensic_diff = {
                "break_kind": break_kind,
                "break_index": break_index if mid_prefix_break else (cur_len if truncated else None),
                "mutated_fields": mutated_fields,
                "added_fields": added_fields,
                "removed_fields": removed_fields,
                "role_before": role_before,
                "role_after": role_after,
                "kept_tokens_est": kept_tokens_est,
                "lost_tokens_est": lost_tokens_est,
                "cache_survival_pct": cache_survival_pct,
                "matched_prefix_root": matched_prefix_root,
                "prev_prefix_root": prev_root,
                "cur_prefix_root": prefix_root,
                "sticky_key": sticky_key,
            }

            self._prefix_sessions[sid] = {
                "digests": digs,
                "cum_hashes": cum_hashes,
                "item_metas": cur_metas,
                "prefix_root": prefix_root,
                "account_id": stored_acct,
                "updated_at": now,
            }
            self._prefix_sessions.move_to_end(sid, last=True)
            while len(self._prefix_sessions) > 64:
                self._prefix_sessions.popitem(last=False)

            self._prefix_audits += 1
            if mid_prefix_break:
                self._prefix_breaks_caught += 1
            else:
                self._prefix_clean += 1

        if mid_prefix_break and self._pulse is not None:
            try:
                self._pulse.emit(
                    "SYMBIOTE_PREFIX_BREAK",
                    "symbiote",
                    {
                        "session_id": sid,
                        "break_index": break_index,
                        "prev_len": prev_len,
                        "cur_len": cur_len,
                        "mutated_fields": mutated_fields,
                        "lost_tokens_est": lost_tokens_est,
                        "cache_survival_pct": cache_survival_pct,
                    },
                )
            except Exception:
                pass

        res: dict[str, Any] = {
            "ok": True,
            "session_id": sid,
            "prefix_root": prefix_root,
            "matched_prefix_root": matched_prefix_root,
            "sticky_key": sticky_key,
            "matched_prefix_len": common,
            "prev_len": prev_len,
            "cur_len": cur_len,
            "mid_prefix_break": mid_prefix_break,
            "break_index": break_index,
            "affinity_account_id": stored_acct,
            "forensic_diff": forensic_diff,
        }
        if isinstance(tool_outputs, list):
            res["stale_reads"] = self.detect_stale_file_reads(tool_outputs)
        return res

    def get_kv_affinity(self, session_id: str) -> dict[str, Any]:
        sid = str(session_id or "").strip()
        if not sid:
            return {"ok": True, "found": False, "session_id": ""}
        with self._lock:
            row = self._prefix_sessions.get(sid)
            if not row:
                return {"ok": True, "found": False, "session_id": sid}
            return {
                "ok": True,
                "found": bool(row.get("account_id")),
                "session_id": sid,
                "account_id": row.get("account_id") or "",
                "prefix_root": row.get("prefix_root") or "",
                "updated_at": row.get("updated_at") or 0.0,
            }

    def detect_stale_file_reads(self, tool_outputs: list[dict[str, Any]]) -> dict[str, Any]:
        """Deterministic SHA-256 duplicate full-file read detector (ZERO LLM calls)."""
        seen: dict[str, dict[str, Any]] = {}
        duplicates: list[dict[str, Any]] = []
        reclaimable_bytes = 0
        for idx, item in enumerate(tool_outputs or []):
            if not isinstance(item, dict):
                continue
            path = str(item.get("path") or item.get("file") or "").strip()
            content = item.get("content")
            if not isinstance(content, str) or len(content) < 64:
                continue
            raw_bytes = content.encode("utf-8", errors="ignore")
            sha = hashlib.sha256(raw_bytes).hexdigest()
            turn_idx = item.get("turn_index", idx)
            prev = seen.get(path) if path else seen.get(f"sha:{sha}")
            if prev is not None and prev["sha256"] == sha:
                duplicates.append(
                    {
                        "path": path or "<unnamed>",
                        "sha256": sha[:16],
                        "first_turn": prev["turn_index"],
                        "duplicate_turn": turn_idx,
                        "bytes": len(raw_bytes),
                    }
                )
                reclaimable_bytes += len(raw_bytes)
            else:
                key = path or f"sha:{sha}"
                seen[key] = {"sha256": sha, "turn_index": turn_idx}

        with self._lock:
            self._stale_read_audits += 1
            self._stale_read_duplicates += len(duplicates)

        return {
            "ok": True,
            "duplicate_reads": duplicates,
            "duplicate_count": len(duplicates),
            "reclaimable_bytes": reclaimable_bytes,
        }

    @staticmethod
    def _default_codex_sessions_dir() -> Path:
        return Path.home() / ".codex" / "sessions"

    def _resolve_rollout_file(
        self,
        session_id: str,
        sessions_dir: Path | str | None = None,
    ) -> Path | None:
        sid = str(session_id or "").strip()
        if not _SESSION_ID_RE.match(sid):
            raise ValueError(f"Invalid session_id for Codex Surgeon: {sid!r}")
        root = Path(sessions_dir).expanduser().resolve() if sessions_dir else self._default_codex_sessions_dir().resolve()
        if not root.is_dir():
            return None
        matches: list[Path] = []
        for cand in root.rglob(f"*{sid}.jsonl"):
            name = cand.name
            if ".bak." in name or name.endswith(".tmp"):
                continue
            try:
                resolved = cand.resolve()
                resolved.relative_to(root)
            except Exception:
                continue
            if resolved.is_file():
                matches.append(resolved)
        if not matches:
            return None
        matches.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return matches[0]

    @staticmethod
    def _make_bounded_unique_id(base: str, occ: int, used: set[str], max_len: int = 64) -> str:
        clean = str(base or "item")
        attempt = 0
        while True:
            suffix = f"_r{occ}" if attempt == 0 else f"_r{occ}_{attempt}"
            if len(clean) + len(suffix) <= max_len:
                candidate = f"{clean}{suffix}"
            else:
                keep = max(8, max_len - len(suffix))
                candidate = f"{clean[:keep]}{suffix}"
            if candidate not in used:
                used.add(candidate)
                return candidate
            attempt += 1

    def heal_codex_rollout_jsonl(
        self,
        session_id: str,
        *,
        sessions_dir: Path | str | None = None,
        min_idle_sec: float = 2.0,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Atomically repair duplicate tool call_id/id collisions in a Codex rollout JSONL."""
        sid = str(session_id or "").strip()
        target = self._resolve_rollout_file(sid, sessions_dir=sessions_dir)
        if target is None:
            return {"ok": False, "found": False, "reason": "rollout_not_found", "session_id": sid}

        st = target.stat()
        idle_s = max(0.0, float(min_idle_sec or 0.0))
        age_s = max(0.0, time.time() - st.st_mtime)
        if idle_s > 0.0 and age_s < idle_s:
            return {
                "ok": False,
                "found": True,
                "skipped": True,
                "reason": "file_recently_modified",
                "session_id": sid,
                "path": str(target),
                "age_sec": round(age_s, 3),
            }

        raw_text = target.read_text(encoding="utf-8", errors="replace")
        raw_lines = raw_text.splitlines()
        trailing_nl = raw_text.endswith("\n")

        used_call_ids: set[str] = set()
        used_item_ids: set[str] = set()
        for ln in raw_lines:
            try:
                obj = json.loads(ln)
            except Exception:
                continue
            if not isinstance(obj, dict):
                continue
            items_to_scan: list[dict[str, Any]] = []
            if obj.get("type") == "response_item" and isinstance(obj.get("payload"), dict):
                items_to_scan.append(obj["payload"])
            elif obj.get("type") == "compacted" and isinstance(obj.get("payload"), dict) and isinstance(obj["payload"].get("replacement_history"), list):
                items_to_scan.extend(x for x in obj["payload"]["replacement_history"] if isinstance(x, dict))
            elif obj.get("type") in (*_TOOL_CALL_TYPES, *_TOOL_OUTPUT_TYPES):
                items_to_scan.append(obj)
            for it in items_to_scan:
                cid = it.get("call_id")
                if isinstance(cid, str) and cid:
                    used_call_ids.add(cid)
                iid = it.get("id")
                if isinstance(iid, str) and iid:
                    used_item_ids.add(iid)

        call_occ: dict[str, int] = {}
        seen_item_ids: set[str] = set()
        pending_output_remap: dict[str, list[str]] = {}
        healed_call_ids: list[str] = []
        healed_calls = 0
        healed_outputs = 0

        def _heal_item_dict(item: dict[str, Any]) -> bool:
            nonlocal healed_calls, healed_outputs
            itype = item.get("type")
            cid = item.get("call_id")
            if itype in _TOOL_CALL_TYPES and isinstance(cid, str) and cid:
                occ = call_occ.get(cid, 0) + 1
                call_occ[cid] = occ
                orig_id = item.get("id")
                if occ == 1:
                    pending_output_remap.setdefault(cid, []).append(cid)
                    if isinstance(orig_id, str) and orig_id:
                        seen_item_ids.add(orig_id)
                    return False
                new_cid = self._make_bounded_unique_id(cid, occ, used_call_ids)
                item["call_id"] = new_cid
                call_occ[new_cid] = 1
                pending_output_remap.setdefault(cid, []).append(new_cid)
                if isinstance(orig_id, str) and orig_id:
                    if orig_id in seen_item_ids:
                        new_id = self._make_bounded_unique_id(orig_id, occ, used_item_ids)
                        item["id"] = new_id
                        seen_item_ids.add(new_id)
                    else:
                        seen_item_ids.add(orig_id)
                healed_calls += 1
                if cid not in healed_call_ids:
                    healed_call_ids.append(cid)
                return True
            if itype in _TOOL_OUTPUT_TYPES and isinstance(cid, str) and cid:
                stack = pending_output_remap.get(cid)
                mapped_cid = stack.pop() if stack else cid
                changed = False
                if mapped_cid and mapped_cid != cid:
                    item["call_id"] = mapped_cid
                    healed_outputs += 1
                    changed = True
                orig_id = item.get("id")
                if isinstance(orig_id, str) and orig_id:
                    if orig_id in seen_item_ids:
                        new_id = self._make_bounded_unique_id(orig_id, max(2, call_occ.get(cid, 2)), used_item_ids)
                        item["id"] = new_id
                        seen_item_ids.add(new_id)
                        changed = True
                    else:
                        seen_item_ids.add(orig_id)
                return changed
            return False

        out_lines: list[str] = []
        for ln in raw_lines:
            try:
                obj = json.loads(ln)
            except Exception:
                out_lines.append(ln)
                continue
            if not isinstance(obj, dict):
                out_lines.append(ln)
                continue
            mutated = False
            if obj.get("type") == "response_item" and isinstance(obj.get("payload"), dict):
                mutated = _heal_item_dict(obj["payload"])
            elif obj.get("type") == "compacted" and isinstance(obj.get("payload"), dict) and isinstance(obj["payload"].get("replacement_history"), list):
                for sub in obj["payload"]["replacement_history"]:
                    if isinstance(sub, dict) and _heal_item_dict(sub):
                        mutated = True
            elif obj.get("type") in (*_TOOL_CALL_TYPES, *_TOOL_OUTPUT_TYPES):
                mutated = _heal_item_dict(obj)
            out_lines.append(json.dumps(obj, ensure_ascii=False, separators=(",", ":")) if mutated else ln)

        if healed_calls == 0 and healed_outputs == 0:
            return {
                "ok": True,
                "found": True,
                "changed": False,
                "session_id": sid,
                "path": str(target),
                "healed_calls": 0,
                "healed_outputs": 0,
                "total_lines": len(raw_lines),
            }

        if dry_run:
            return {
                "ok": True,
                "found": True,
                "changed": True,
                "dry_run": True,
                "session_id": sid,
                "path": str(target),
                "healed_calls": healed_calls,
                "healed_outputs": healed_outputs,
                "healed_call_ids": healed_call_ids,
                "total_lines": len(raw_lines),
            }

        new_text = "\n".join(out_lines) + ("\n" if (trailing_nl or out_lines) else "")
        new_bytes = new_text.encode("utf-8")

        verify_seen: set[tuple[str, str]] = set()
        dup_remaining = 0
        for ln in out_lines:
            try:
                obj = json.loads(ln)
            except Exception:
                continue
            if isinstance(obj, dict) and obj.get("type") == "response_item" and isinstance(obj.get("payload"), dict):
                pl = obj["payload"]
                if pl.get("type") in _TOOL_CALL_TYPES and isinstance(pl.get("call_id"), str) and pl.get("call_id"):
                    key = (str(pl["type"]), pl["call_id"])
                    if key in verify_seen:
                        dup_remaining += 1
                    verify_seen.add(key)

        bak_path = target.with_name(f"{target.name}.bak.{int(time.time())}")
        shutil.copy2(target, bak_path)
        tmp_path = target.with_name(f"{target.name}.surgeon.{os.getpid()}.tmp")
        with open(tmp_path, "wb") as fh:
            fh.write(new_bytes)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, target)

        sha = hashlib.sha256(new_bytes).hexdigest()
        receipt = {
            "ok": True,
            "found": True,
            "changed": True,
            "session_id": sid,
            "path": str(target),
            "backup_path": str(bak_path),
            "healed_calls": healed_calls,
            "healed_outputs": healed_outputs,
            "healed_call_ids": healed_call_ids,
            "duplicates_remaining": dup_remaining,
            "sha256": sha,
            "total_lines": len(out_lines),
            "at": time.time(),
        }
        with self._lock:
            self._surgeon_heals += 1
            self._surgeon_calls_rewritten += healed_calls
            self._surgeon_last_receipt = dict(receipt)

        if self._pulse is not None:
            try:
                self._pulse.emit(
                    "SYMBIOTE_ROLLOUT_SURGERY",
                    "symbiote",
                    {
                        "session_id": sid,
                        "healed_calls": healed_calls,
                        "healed_outputs": healed_outputs,
                        "healed_call_ids": healed_call_ids[:8],
                        "sha256": sha[:16],
                    },
                )
            except Exception:
                pass
        return receipt

    def fork_rollout_to_last_clean_checkpoint(
        self,
        session_id: str,
        *,
        sessions_dir: Path | str | None = None,
        before_line: int | None = None,
        before_call_id: str = "",
    ) -> dict[str, Any]:
        """Time-travel clean fork of a Codex rollout before poison/corruption into a sibling session file."""
        sid = str(session_id or "").strip()
        target = self._resolve_rollout_file(sid, sessions_dir=sessions_dir)
        if target is None:
            return {"ok": False, "found": False, "reason": "rollout_not_found", "session_id": sid}

        raw_lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
        seen_calls: set[str] = set()
        open_calls: set[str] = set()
        last_clean_turn_idx = 0
        cut_idx: int | None = None
        target_call_id = str(before_call_id or "").strip()
        explicit_before = int(before_line) if before_line is not None else None

        for idx, ln in enumerate(raw_lines):
            if explicit_before is not None and idx >= explicit_before:
                cut_idx = idx
                break
            try:
                obj = json.loads(ln)
            except Exception:
                cut_idx = idx
                break
            if not isinstance(obj, dict):
                continue
            otype = obj.get("type")
            pl = obj.get("payload") if isinstance(obj.get("payload"), dict) else {}
            if otype == "turn_context" and not open_calls:
                last_clean_turn_idx = idx
            if otype == "response_item" and pl:
                pt = pl.get("type")
                cid = pl.get("call_id")
                if target_call_id and cid == target_call_id:
                    cut_idx = idx
                    break
                if pt in _TOOL_CALL_TYPES and isinstance(cid, str) and cid:
                    if cid in seen_calls:
                        cut_idx = idx
                        break
                    seen_calls.add(cid)
                    open_calls.add(cid)
                elif pt in _TOOL_OUTPUT_TYPES and isinstance(cid, str) and cid:
                    open_calls.discard(cid)
                    if not open_calls:
                        last_clean_turn_idx = idx + 1
            elif not open_calls and idx > 0 and otype in ("session_meta", "event_msg", "compacted"):
                last_clean_turn_idx = idx + 1

        if cut_idx is None:
            cut_idx = len(raw_lines)
        elif open_calls and last_clean_turn_idx > 0 and last_clean_turn_idx < cut_idx:
            cut_idx = last_clean_turn_idx

        cut_idx = max(1 if raw_lines else 0, min(len(raw_lines), cut_idx))
        kept_lines = list(raw_lines[:cut_idx])
        new_session_id = str(uuid.uuid4())
        if kept_lines:
            try:
                first_obj = json.loads(kept_lines[0])
                if isinstance(first_obj, dict) and first_obj.get("type") == "session_meta" and isinstance(first_obj.get("payload"), dict):
                    first_obj["payload"]["id"] = new_session_id
                    kept_lines[0] = json.dumps(first_obj, ensure_ascii=False, separators=(",", ":"))
            except Exception:
                pass

        stamp = time.strftime("%Y-%m-%dT%H-%M-%S", time.gmtime())
        fork_name = f"rollout-{stamp}-{new_session_id}.jsonl"
        fork_path = target.with_name(fork_name)
        new_bytes = ("\n".join(kept_lines) + ("\n" if kept_lines else "")).encode("utf-8")
        tmp_path = target.with_name(f"{fork_name}.surgeon.{os.getpid()}.tmp")
        with open(tmp_path, "wb") as fh:
            fh.write(new_bytes)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, fork_path)

        sha = hashlib.sha256(new_bytes).hexdigest()
        with self._lock:
            self._surgeon_forks += 1
        if self._pulse is not None:
            try:
                self._pulse.emit(
                    "SYMBIOTE_ROLLOUT_FORK",
                    "symbiote",
                    {
                        "source_session_id": sid,
                        "new_session_id": new_session_id,
                        "kept_lines": len(kept_lines),
                        "dropped_lines": max(0, len(raw_lines) - len(kept_lines)),
                    },
                )
            except Exception:
                pass
        return {
            "ok": True,
            "found": True,
            "source_session_id": sid,
            "new_session_id": new_session_id,
            "source_path": str(target),
            "fork_path": str(fork_path),
            "kept_lines": len(kept_lines),
            "dropped_lines": max(0, len(raw_lines) - len(kept_lines)),
            "sha256": sha,
        }

    def observe_usage(self, event: dict[str, Any]) -> dict[str, Any]:
        ev = event if isinstance(event, dict) else {}
        cut = str(ev.get("cut") or "").strip().lower()
        status = int(ev.get("status") or 0)
        is_compact = bool(ev.get("is_compact") or ev.get("isCompact") or False)
        scalpel = bool(ev.get("scalpel_immediate") or ev.get("scalpelImmediate") or False)

        leak_recorded = False
        with self._lock:
            self._total_observed += 1
            if scalpel:
                self._scalpel_immediate_cuts += 1
            if cut.startswith("autocut-"):
                self._autocut_count += 1
            elif cut == "completed":
                self._completed_count += 1
                if is_compact:
                    self._completed_compact_count += 1
                else:
                    leak_entry = {
                        "ts": time.time(),
                        "model": str(ev.get("model") or ev.get("servedModel") or ""),
                        "effort": str(ev.get("effort") or ""),
                        "cut": cut,
                        "auto_cut_miss_reason": str(ev.get("auto_cut_miss_reason") or ev.get("autoCutMissReason") or "unknown"),
                        "tool_names": list(ev.get("tool_names") or ev.get("toolNames") or [])[:12],
                        "payload_bytes": int(ev.get("payload_bytes") or ev.get("payloadBytes") or 0),
                        "cache_ratio": float(ev.get("cache_ratio") or ev.get("cacheRatio") or 0.0),
                        "session_id": str(ev.get("session_id") or ev.get("sessionId") or ""),
                    }
                    self._completed_leaks.append(leak_entry)
                    leak_recorded = True
            if status == 499:
                self._aborted_499_count += 1
            elif status == 503 or "timeout-retry" in cut:
                self._blocked_503_count += 1

        if leak_recorded and self._pulse is not None:
            try:
                self._pulse.emit(
                    "SYMBIOTE_COMPLETED_LEAK",
                    "symbiote",
                    {
                        "model": leak_entry["model"],
                        "reason": leak_entry["auto_cut_miss_reason"],
                        "tools": leak_entry["tool_names"],
                    },
                )
            except Exception:
                pass

        return {
            "ok": True,
            "leak_recorded": leak_recorded,
            "completed_count": self._completed_count,
            "autocut_count": self._autocut_count,
        }

    @staticmethod
    def _is_safe_untracked_code(rel_path: str) -> bool:
        norm = str(rel_path or "").replace("\\", "/").lstrip("./")
        if not norm or any(norm.startswith(p) or f"/{p}" in norm for p in _PROTECTED_PREFIXES):
            return False
        name = norm.rsplit("/", 1)[-1]
        if name in _PROTECTED_NAMES or name.startswith(".env.") or norm.endswith(".pyc"):
            return False
        ext = Path(norm).suffix.lower()
        return ext in {".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".go", ".rs"}

    def precog_verify(
        self,
        repo_dir: str,
        changed_files: list[str] | None = None,
        *,
        run_fast_tests: bool = False,
        timeout_sec: int = 15,
    ) -> dict[str, Any]:
        t0 = time.perf_counter()
        repo = Path(str(repo_dir or "")).resolve()
        if not repo.is_dir():
            return {"ok": False, "error": f"repo_dir_not_found:{repo_dir}", "duration_ms": 0.0}

        timeout_s = max(3, min(60, int(timeout_sec or 15)))
        untracked_code: list[str] = []
        if (repo / ".git").exists():
            try:
                st = subprocess.run(
                    ["git", "status", "--porcelain", "--untracked-files=all"],
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    cwd=repo,
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if st.returncode == 0:
                    for line in st.stdout.splitlines():
                        if line.startswith("?? "):
                            rel = line[3:].strip().strip('"')
                            if self._is_safe_untracked_code(rel):
                                untracked_code.append(rel)
            except Exception:
                pass

        targets: list[str] = []
        seen_t: set[str] = set()
        for raw_f in list(changed_files or []) + untracked_code:
            rel = str(raw_f or "").replace("\\", "/").lstrip("./")
            if rel and rel != "/dev/null" and rel not in seen_t:
                seen_t.add(rel)
                targets.append(rel)
            if len(targets) >= 30:
                break

        checked_files: list[str] = []
        syntax_errors: list[dict[str, Any]] = []
        node_bin = shutil.which("node")

        for rel in targets:
            fpath = (repo / rel).resolve()
            try:
                fpath.relative_to(repo)
            except ValueError:
                continue
            if not fpath.is_file():
                continue
            ext = fpath.suffix.lower()
            if ext == ".py":
                checked_files.append(rel)
                try:
                    cp = subprocess.run(
                        [sys.executable, "-m", "py_compile", str(fpath)],
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                        cwd=repo,
                        capture_output=True,
                        text=True,
                        timeout=min(8, timeout_s),
                    )
                    if cp.returncode != 0:
                        syntax_errors.append(
                            {
                                "file": rel,
                                "checker": "py_compile",
                                "error": (cp.stderr or cp.stdout or "syntax error").strip()[:500],
                            }
                        )
                except Exception as exc:
                    syntax_errors.append({"file": rel, "checker": "py_compile", "error": str(exc)[:300]})
            elif ext in (".js", ".mjs", ".cjs") and node_bin:
                checked_files.append(rel)
                try:
                    cp = subprocess.run(
                        [node_bin, "--check", str(fpath)],
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                        cwd=repo,
                        capture_output=True,
                        text=True,
                        timeout=min(8, timeout_s),
                    )
                    if cp.returncode != 0:
                        syntax_errors.append(
                            {
                                "file": rel,
                                "checker": "node_check",
                                "error": (cp.stderr or cp.stdout or "syntax error").strip()[:500],
                            }
                        )
                except Exception as exc:
                    syntax_errors.append({"file": rel, "checker": "node_check", "error": str(exc)[:300]})

        test_rc: int | None = None
        test_tail = ""
        if run_fast_tests and not syntax_errors and targets:
            has_py = any(f.endswith(".py") for f in targets)
            has_js = any(f.endswith((".js", ".mjs", ".cjs")) for f in targets)
            cmd: list[str] | None = None
            if has_py:
                cmd = [sys.executable, "-m", "pytest", "-q", "-x"]
            elif has_js and node_bin:
                cmd = [node_bin, "--test"]
            if cmd:
                try:
                    tp = subprocess.run(
                        cmd, cwd=repo, capture_output=True, text=True, timeout=timeout_s,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    )
                    test_rc = int(tp.returncode)
                    test_tail = ((tp.stdout or "") + "\n" + (tp.stderr or "")).strip()[-600:]
                except subprocess.TimeoutExpired:
                    test_rc = 124
                    test_tail = f"fast_test_timeout_{timeout_s}s"
                except Exception as exc:
                    test_rc = 1
                    test_tail = str(exc)[:300]

        ok = len(syntax_errors) == 0 and (not run_fast_tests or test_rc in (None, 0))
        dur_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        with self._lock:
            self._precog_runs += 1
            if not ok:
                self._precog_failures += 1

        gt_lines = [
            f"ok={ok} checked={len(checked_files)} syntax_errors={len(syntax_errors)} untracked_code={len(untracked_code)} dur_ms={dur_ms}",
        ]
        if untracked_code:
            gt_lines.append("untracked=" + ",".join(untracked_code[:8]))
        if syntax_errors:
            gt_lines.append("first_error=" + json.dumps(syntax_errors[0], ensure_ascii=False))
        if test_rc is not None:
            gt_lines.append(f"test_rc={test_rc}")
        gt_block = "<chimera_ground_truth_verify>\n" + "\n".join(gt_lines) + "\n</chimera_ground_truth_verify>"

        return {
            "ok": ok,
            "checked_files": checked_files,
            "syntax_errors": syntax_errors,
            "untracked_code_files": untracked_code,
            "test_rc": test_rc,
            "test_tail": test_tail,
            "duration_ms": dur_ms,
            "ground_truth_block": gt_block,
        }

    def status(self) -> dict[str, Any]:
        with self._lock:
            now = time.time()
            self._prune_blobs_locked(now)
            self._prune_immortal_locked(now)
            avg_ratio = (
                round(self._compressed_bytes_in / self._raw_bytes_in, 4)
                if self._raw_bytes_in > 0
                else 1.0
            )
            return {
                "ok": True,
                "zero_iq_loss_axiom": True,
                "native_caps": v12_native_caps(),
                "bone_marrow": {
                    "entries": len(self._blobs),
                    "max_entries": self.max_entries,
                    "current_compressed_bytes": self._current_compressed_bytes,
                    "max_blob_bytes": self.max_blob_bytes,
                    "blobs_stored": self._blobs_stored,
                    "blob_hits": self._blob_hits,
                    "blob_misses": self._blob_misses,
                    "raw_bytes_in": self._raw_bytes_in,
                    "compressed_bytes_in": self._compressed_bytes_in,
                    "lz4_saved_bytes": self._lz4_saved_bytes,
                    "avg_ratio": avg_ratio,
                    "evictions": self._evictions,
                },
                "immortal": {
                    "active_entries": len(self._immortal),
                    "registered": self._immortal_registered,
                    "completed": self._immortal_completed,
                    "hits": self._immortal_hits,
                },
                "prefix_shield": {
                    "tracked_sessions": len(self._prefix_sessions),
                    "prefix_audits": self._prefix_audits,
                    "prefix_clean": self._prefix_clean,
                    "prefix_breaks_caught": self._prefix_breaks_caught,
                    "stale_read_audits": self._stale_read_audits,
                    "stale_read_duplicates": self._stale_read_duplicates,
                },
                "vaccine": {
                    "total_observed": self._total_observed,
                    "autocut_count": self._autocut_count,
                    "completed_count": self._completed_count,
                    "completed_compact_count": self._completed_compact_count,
                    "aborted_499_count": self._aborted_499_count,
                    "blocked_503_count": self._blocked_503_count,
                    "scalpel_immediate_cuts": self._scalpel_immediate_cuts,
                    "recent_completed_leaks": list(self._completed_leaks)[-5:],
                },
                "precog": {
                    "runs": self._precog_runs,
                    "failures": self._precog_failures,
                },
                "surgeon": {
                    "heals": self._surgeon_heals,
                    "calls_rewritten": self._surgeon_calls_rewritten,
                    "forks": self._surgeon_forks,
                    "last_receipt": self._surgeon_last_receipt,
                },
            }
