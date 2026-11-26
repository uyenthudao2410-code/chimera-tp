"""Shared 10,000-bit Kanerva VSA Semantic Memory & L0 Cache Service backed by C11 AVX2 SIMD."""

from __future__ import annotations

from datetime import datetime, timezone
import functools
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import threading
import time
from typing import Any

from .native import v12_native_caps, vsa_bind_xor, vsa_hamming

VSA_BITS = 10_000
VSA_BYTES = VSA_BITS // 8  # 1,250 bytes

_TOKEN_RE = re.compile(r"[a-z0-9_]{2,}")
# Precompute bit-expansion lookup for each byte value (0..255) -> tuple of (+1/-1) per bit
_BYTE_SIGNS: tuple[tuple[int, ...], ...] = tuple(
    tuple(1 if ((b >> bit) & 1) else -1 for bit in range(8)) for b in range(256)
)


@functools.lru_cache(maxsize=4096)
def _token_hypervector(token: str) -> bytes:
    """Deterministically expand one token into a 1,250-byte (10,000-bit) hypervector."""
    blk = hashlib.blake2b(token.encode("utf-8"), digest_size=32).digest()
    buf = bytearray()
    while len(buf) < VSA_BYTES:
        blk = hashlib.sha256(blk).digest()
        buf.extend(blk)
    return bytes(buf[:VSA_BYTES])


def encode_text_10k(text: str) -> bytes:
    """Encode arbitrary text into a 10,000-bit binary hypervector using majority-rule bundling."""
    tokens = _TOKEN_RE.findall(str(text or "").lower())[:48]
    if not tokens:
        tokens = ["empty"]
    if len(tokens) == 1:
        return _token_hypervector(tokens[0])

    # Keep count compact and cache unique token projections
    counts = [0] * VSA_BITS
    for tok in tokens:
        raw = _token_hypervector(tok)
        idx = 0
        for bval in raw:
            s0, s1, s2, s3, s4, s5, s6, s7 = _BYTE_SIGNS[bval]
            counts[idx] += s0
            counts[idx + 1] += s1
            counts[idx + 2] += s2
            counts[idx + 3] += s3
            counts[idx + 4] += s4
            counts[idx + 5] += s5
            counts[idx + 6] += s6
            counts[idx + 7] += s7
            idx += 8

    out = bytearray(VSA_BYTES)
    idx = 0
    for bi in range(VSA_BYTES):
        out[bi] = (
            (1 if counts[idx] >= 0 else 0)
            | (2 if counts[idx + 1] >= 0 else 0)
            | (4 if counts[idx + 2] >= 0 else 0)
            | (8 if counts[idx + 3] >= 0 else 0)
            | (16 if counts[idx + 4] >= 0 else 0)
            | (32 if counts[idx + 5] >= 0 else 0)
            | (64 if counts[idx + 6] >= 0 else 0)
            | (128 if counts[idx + 7] >= 0 else 0)
        )
        idx += 8
    return bytes(out)


def hamming_similarity(a: bytes, b: bytes) -> float:
    """Compute normalized [0..1] Hamming similarity using C11 AVX2 popcnt when available."""
    dist = vsa_hamming(a[:VSA_BYTES], b[:VSA_BYTES])
    return round(max(0.0, min(1.0, 1.0 - (dist / float(VSA_BITS)))), 4)


def bind_role_value(role: str, value: str) -> bytes:
    """Bind a structured role-value pair into an orthogonal hypervector via AVX2 XOR."""
    return vsa_bind_xor(encode_text_10k(f"role:{role}"), encode_text_10k(value))


class SharedVsaMemoryService:
    """Thread-safe in-memory + SQLite-backed 10k-bit VSA store shared over Chimera HTTP/Phantom."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self.db_path = Path(db_path) if db_path is not None else None
        self._lock = threading.Lock()
        self._items: dict[str, dict[str, Any]] = {}
        self._queries_served = 0
        self._total_recall_ms = 0.0
        self._conn: sqlite3.Connection | None = None
        self._init_db()

    def _init_db(self) -> None:
        if self.db_path is None:
            return
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS vsa_items (
                item_id TEXT PRIMARY KEY,
                domain TEXT NOT NULL,
                text TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                vsa_blob BLOB NOT NULL,
                reward REAL NOT NULL DEFAULT 1.0,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.commit()
        for item_id, domain, text, payload_json, vsa_blob, reward, updated_at in conn.execute(
            "SELECT item_id, domain, text, payload_json, vsa_blob, reward, updated_at FROM vsa_items"
        ).fetchall():
            try:
                payload_obj = json.loads(payload_json)
            except Exception:
                payload_obj = payload_json
            vb = bytes(vsa_blob)[:VSA_BYTES]
            if len(vb) == VSA_BYTES:
                self._items[str(item_id)] = {
                    "item_id": str(item_id),
                    "domain": str(domain),
                    "text": str(text),
                    "payload": payload_obj,
                    "vec": vb,
                    "vec_int": int.from_bytes(vb, "big"),
                    "reward": float(reward or 1.0),
                    "updated_at": str(updated_at),
                }
        self._conn = conn

    def _coerce_vec(self, *, text: str, vsa_hex: str | None) -> bytes:
        if vsa_hex:
            try:
                raw = bytes.fromhex(str(vsa_hex).strip())
                if len(raw) >= VSA_BYTES:
                    return raw[:VSA_BYTES]
            except ValueError:
                pass
        return encode_text_10k(text)

    def _persist_items(self, rows: list[dict[str, Any]]) -> None:
        if self._conn is None or not rows:
            return
        self._conn.executemany(
            """
            INSERT OR REPLACE INTO vsa_items
            (item_id, domain, text, payload_json, vsa_blob, reward, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    r["item_id"],
                    r["domain"],
                    r["text"],
                    json.dumps(r["payload"], ensure_ascii=False),
                    sqlite3.Binary(r["vec"]),
                    float(r["reward"]),
                    r["updated_at"],
                )
                for r in rows
            ],
        )
        self._conn.commit()

    def store(
        self,
        item_id: str,
        domain: str = "global",
        text: str = "",
        payload: Any = None,
        *,
        reward: float = 1.0,
        vsa_hex: str | None = None,
    ) -> dict[str, Any]:
        t0 = time.perf_counter()
        iid = str(item_id or "").strip()
        if not iid:
            raise ValueError("item_id is required")
        vec = self._coerce_vec(text=text or iid, vsa_hex=vsa_hex)
        now_iso = datetime.now(timezone.utc).isoformat()
        rec = {
            "item_id": iid,
            "domain": str(domain or "global"),
            "text": str(text or "")[:1000],
            "payload": payload if payload is not None else {},
            "vec": vec,
            "vec_int": int.from_bytes(vec[:VSA_BYTES], "big"),
            "reward": float(reward),
            "updated_at": now_iso,
        }
        with self._lock:
            self._items[iid] = rec
            self._persist_items([rec])
            total = len(self._items)
        caps = v12_native_caps()
        return {
            "ok": True,
            "item_id": iid,
            "domain": rec["domain"],
            "vsa_bits": VSA_BITS,
            "backend": "c11_avx2" if caps.get("vsa_hamming") else "python_fallback",
            "total_items": total,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 3),
        }

    def store_batch(self, items: list[dict[str, Any]]) -> dict[str, Any]:
        t0 = time.perf_counter()
        now_iso = datetime.now(timezone.utc).isoformat()
        recs: list[dict[str, Any]] = []
        for raw in items:
            if not isinstance(raw, dict):
                continue
            iid = str(raw.get("item_id") or "").strip()
            if not iid:
                continue
            txt = str(raw.get("text") or iid)
            vec = self._coerce_vec(text=txt, vsa_hex=raw.get("vsa_hex"))
            recs.append(
                {
                    "item_id": iid,
                    "domain": str(raw.get("domain") or "global"),
                    "text": txt[:1000],
                    "payload": raw.get("payload") if raw.get("payload") is not None else {},
                    "vec": vec,
                    "vec_int": int.from_bytes(vec[:VSA_BYTES], "big"),
                    "reward": float(raw.get("reward", 1.0) or 1.0),
                    "updated_at": now_iso,
                }
            )
        with self._lock:
            for r in recs:
                self._items[r["item_id"]] = r
            self._persist_items(recs)
            total = len(self._items)
        caps = v12_native_caps()
        return {
            "ok": True,
            "stored_count": len(recs),
            "total_items": total,
            "backend": "c11_avx2" if caps.get("vsa_hamming") else "python_fallback",
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 3),
        }

    def recall(
        self,
        query_text: str = "",
        *,
        domain: str | None = None,
        top_k: int = 5,
        min_sim: float = 0.0,
        query_vsa_hex: str | None = None,
    ) -> dict[str, Any]:
        t0 = time.perf_counter()
        q_vec = self._coerce_vec(text=query_text, vsa_hex=query_vsa_hex)
        q_int = int.from_bytes(q_vec[:VSA_BYTES], "big")
        dom_filter = str(domain).strip() if domain else None
        k = max(1, min(100, int(top_k or 5)))
        thresh = float(min_sim or 0.0)

        with self._lock:
            snapshot = list(self._items.values())

        matches: list[dict[str, Any]] = []
        scanned = 0
        for rec in snapshot:
            if dom_filter and rec["domain"] != dom_filter:
                continue
            scanned += 1
            v_int = rec.get("vec_int")
            if v_int is None:
                v_int = int.from_bytes(rec["vec"][:VSA_BYTES], "big")
                rec["vec_int"] = v_int
            dist = (q_int ^ v_int).bit_count()
            sim = round(max(0.0, min(1.0, 1.0 - (dist / float(VSA_BITS)))), 4)
            if sim >= thresh:
                matches.append(
                    {
                        "item_id": rec["item_id"],
                        "domain": rec["domain"],
                        "similarity": sim,
                        "reward": rec["reward"],
                        "text": rec["text"],
                        "payload": rec["payload"],
                    }
                )

        matches.sort(key=lambda m: (m["similarity"], m["reward"]), reverse=True)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        caps = v12_native_caps()
        backend = "int_bitcount_fast" if caps.get("vsa_hamming") else "python_bitcount"

        with self._lock:
            self._queries_served += 1
            self._total_recall_ms += elapsed_ms

        return {
            "ok": True,
            "backend": backend,
            "vsa_bits": VSA_BITS,
            "scanned": scanned,
            "total_items": len(snapshot),
            "elapsed_ms": round(elapsed_ms, 3),
            "matches": matches[:k],
        }

    def export_items(self, *, domain: str | None = None, limit: int = 500) -> list[dict[str, Any]]:
        dom_filter = str(domain).strip() if domain else None
        cap = max(1, min(2000, int(limit or 500)))
        with self._lock:
            rows = [
                r for r in self._items.values()
                if not dom_filter or r["domain"] == dom_filter
            ]
        rows.sort(key=lambda r: str(r.get("updated_at") or ""), reverse=True)
        return [
            {
                "item_id": r["item_id"],
                "domain": r["domain"],
                "text": r["text"],
                "payload": r["payload"],
                "reward": r["reward"],
                "vsa_hex": r["vec"].hex(),
                "updated_at": r["updated_at"],
            }
            for r in rows[:cap]
        ]

    def stats(self) -> dict[str, Any]:
        caps = v12_native_caps()
        with self._lock:
            cnt = len(self._items)
            q_cnt = self._queries_served
            tot_ms = self._total_recall_ms
        return {
            "ok": True,
            "backend": "c11_avx2" if caps.get("vsa_hamming") else "python_fallback",
            "native_v12": caps,
            "vsa_bits": VSA_BITS,
            "item_count": cnt,
            "queries_served": q_cnt,
            "avg_recall_ms": round(tot_ms / q_cnt, 3) if q_cnt else 0.0,
        }

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                except Exception:
                    pass
                self._conn = None
