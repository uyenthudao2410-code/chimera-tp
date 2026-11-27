"""Shared 10,000-bit Kanerva VSA Semantic Memory & L0 Cache Service backed by C11 AVX2 SIMD."""

from __future__ import annotations

from contextlib import closing, contextmanager
from datetime import datetime, timezone
import functools
import hashlib
import heapq
from itertools import islice
import json
import math
from pathlib import Path
import re
import sqlite3
import tempfile
import threading
import time
from typing import Any

from .native import v12_native_caps, vsa_bind_xor, vsa_hamming
from .overmind_cortex import EgressDlpGuard, _is_loopback_http
import urllib.request

VSA_BITS = 10_000
VSA_BYTES = VSA_BITS // 8  # 1,250 bytes
_COLUMNS = "item_id, domain, text, payload_json, vsa_blob, reward, updated_at"
_VALID_VECTOR = f"length(vsa_blob) >= {VSA_BYTES}"

_TOKEN_RE = re.compile(r"[a-z0-9_]{2,}")

@functools.lru_cache(maxsize=256)
def _expand_token(seed: bytes) -> bytes:
    """Expand one fixed-size token digest into its original 10,000-bit projection."""
    block = seed
    buf = bytearray()
    while len(buf) < VSA_BYTES:
        block = hashlib.sha256(block).digest()
        buf.extend(block)
    return bytes(buf[:VSA_BYTES])


def _token_hypervector(token: str) -> bytes:
    seed = hashlib.blake2b(token.encode("utf-8"), digest_size=32).digest()
    return _expand_token(seed)


def encode_text_10k(text: str) -> bytes:
    """Bundle up to 48 token vectors by majority, setting ties to one."""
    words = _TOKEN_RE.finditer(str(text or "").lower())
    tokens = [match.group() for match in islice(words, 48)] or ["empty"]
    if len(tokens) == 1:
        return _token_hypervector(tokens[0])

    # Each integer is one bit of the vote count at all 10,000 positions.
    planes = [0] * len(tokens).bit_length()
    for token in tokens:
        carry = int.from_bytes(_token_hypervector(token), "little")
        for bit, plane in enumerate(planes):
            planes[bit] = plane ^ carry
            carry &= plane
            if not carry:
                break

    # Compare from low to high: a one in the threshold requires this plane AND
    # the lower comparison, a zero accepts this plane OR the lower comparison.
    # count > (n - 1) // 2 implements the original nonnegative signed vote.
    threshold = (len(tokens) - 1) // 2
    majority = 0
    for bit, plane in enumerate(planes):
        if threshold & (1 << bit):
            majority &= plane
        else:
            majority |= plane
    return majority.to_bytes(VSA_BYTES, "little")


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
        self.db_path = None if db_path is None or str(db_path) == ":memory:" else Path(db_path).absolute()
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
        conn.execute("PRAGMA cache_size=-384")
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
        self._conn = conn

    @staticmethod
    def _record(row):
        iid, domain, text, encoded, vector, reward, updated_at = row
        try:
            payload = json.loads(encoded)
        except (TypeError, ValueError):
            payload = encoded
        return {"item_id": iid, "domain": domain, "text": text, "payload": payload,
                "vec": vector[:VSA_BYTES], "reward": reward, "updated_at": updated_at}

    @contextmanager
    def _transaction(self, *, write):
        if self._conn is None:
            if self.db_path is not None:
                raise RuntimeError("VSA database is closed")
            yield
            return
        with self._conn:
            self._conn.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield

    def _count(self):
        if self._conn is None:
            return len(self._items)
        return self._conn.execute(f"SELECT count(*) FROM vsa_items WHERE {_VALID_VECTOR}").fetchone()[0]

    def _get(self, iid):
        if self._conn is None:
            return self._items.get(iid)
        row = self._conn.execute(
            f"SELECT {_COLUMNS} FROM vsa_items WHERE item_id=? AND {_VALID_VECTOR}", (iid,)
        ).fetchone()
        return self._record(row) if row else None

    def _records(self):
        if self._conn is None:
            yield from self._items.values()
        else:
            with closing(self._conn.execute(
                f"SELECT {_COLUMNS} FROM vsa_items WHERE {_VALID_VECTOR} ORDER BY rowid"
            )) as cursor:
                for row in cursor:
                    yield self._record(row)

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
        if self._conn is None:
            for row in rows:
                self._items[row["item_id"]] = row
            return
        self._conn.executemany(
            """
            INSERT INTO vsa_items
            (item_id, domain, text, payload_json, vsa_blob, reward, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(item_id) DO UPDATE SET domain=excluded.domain, text=excluded.text,
                payload_json=excluded.payload_json, vsa_blob=excluded.vsa_blob,
                reward=excluded.reward, updated_at=excluded.updated_at
            """,
            (
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
            ),
        )

    def _store_records(self, records):
        # Preserve feedback on repeated IDs, including two updates in one submitted batch.
        with self._lock, self._transaction(write=True):
            for row in records:
                previous = self._get(row["item_id"])
                payload = previous["payload"] if previous else None
                if (isinstance(payload, dict) and "_midbrain" in payload
                        and isinstance(row["payload"], dict) and "_midbrain" not in row["payload"]):
                    row["payload"] = {**row["payload"], "_midbrain": payload["_midbrain"]}
                self._persist_items([row])
            return self._count()

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
            "reward": float(reward),
            "updated_at": now_iso,
        }
        total = self._store_records([rec])
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
                    "reward": float(raw.get("reward", 1.0) or 1.0),
                    "updated_at": now_iso,
                }
            )
        total = self._store_records(recs)
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

        scanned = 0
        def ranks(candidates):
            nonlocal scanned
            for iid, vector, reward in candidates:
                scanned += 1
                dist = (q_int ^ int.from_bytes(vector[:VSA_BYTES], "big")).bit_count()
                sim = round(1.0 - dist / VSA_BITS, 4)
                if sim >= thresh:
                    yield sim, reward, iid

        with self._lock, self._transaction(write=False):
            total = self._count()
            if self._conn is None:
                candidates = ((r["item_id"], r["vec"], r["reward"]) for r in self._items.values()
                              if not dom_filter or r["domain"] == dom_filter)
            else:
                condition = " AND domain=?" if dom_filter else ""
                candidates = self._conn.execute(
                    f"SELECT item_id, vsa_blob, reward FROM vsa_items WHERE {_VALID_VECTOR}"
                    + condition + " ORDER BY rowid", (dom_filter,) if dom_filter else ()
                )
            # nlargest preserves insertion order on ties, as did the full stable sort.
            best = heapq.nlargest(k, ranks(candidates), key=lambda hit: hit[:2])
            matches = []
            for sim, reward, iid in best:
                rec = self._get(iid)
                matches.append({"item_id": iid, "domain": rec["domain"], "similarity": sim,
                                "reward": reward, "text": rec["text"], "payload": rec["payload"]})
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
            "total_items": total,
            "elapsed_ms": round(elapsed_ms, 3),
            "matches": matches,
        }

    def iter_export(self, *, domain: str | None = None, limit: int = 500):
        dom_filter = str(domain).strip() if domain else None
        cap = max(1, min(2000, int(limit or 500)))
        def export_row(r):
            return {
                "item_id": r["item_id"],
                "domain": r["domain"],
                "text": r["text"],
                "payload": r["payload"],
                "reward": r["reward"],
                "vsa_hex": r["vec"].hex(),
                "updated_at": r["updated_at"],
            }

        if self.db_path is None:
            with self._lock:
                rows = heapq.nlargest(cap, (r for r in self._items.values() if not dom_filter or
                                            r["domain"] == dom_filter), key=lambda r: r["updated_at"])
            yield from (export_row(r) for r in rows)
            return

        # A WAL reader owns the snapshot while downstream HTTP consumers apply
        # backpressure. Never hold the writer lock across yield (including self-sync).
        uri = self.db_path.as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True)) as reader:
            reader.execute("PRAGMA cache_size=-256")
            reader.execute("BEGIN")
            condition = " AND domain=?" if dom_filter else ""
            args = (dom_filter, cap) if dom_filter else (cap,)
            # Sort identifiers and timestamps only. Carrying payloads through a sort
            # can materialize the entire export in SQLite's temporary storage.
            ids = reader.execute(f"SELECT rowid FROM vsa_items WHERE {_VALID_VECTOR}" + condition
                                 + " ORDER BY updated_at DESC, rowid LIMIT ?", args)
            for (rowid,) in ids:
                row = reader.execute(f"SELECT {_COLUMNS} FROM vsa_items WHERE rowid=?", (rowid,)).fetchone()
                yield export_row(self._record(row))

    def export_items(self, *, domain: str | None = None, limit: int = 500) -> list[dict[str, Any]]:
        return list(self.iter_export(domain=domain, limit=limit))

    def sync_peer(self, base, *, domain, limit, bidirectional, authorize):
        """Validate a complete export before applying it, and bound both directions to small batches."""
        limit = max(1, min(2000, int(limit or 500)))
        params = urllib.parse.urlencode({"domain": domain or "", "limit": limit})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        req = urllib.request.Request(f"{base}/api/vsa/export?{params}",
                                     headers={"Accept": "application/x-ndjson"})
        authorize(req)
        pulled = pushed = received = sent = 0
        peer_total = None
        with opener.open(req, timeout=4.0) as response, tempfile.TemporaryFile() as spool:
            if response.headers.get_content_type() == "application/x-ndjson":
                count = 0
                complete = False
                for line in response:
                    received += len(line)
                    row = json.loads(line)
                    if complete or not isinstance(row, dict):
                        raise ValueError("invalid_vsa_stream")
                    if "end" in row:
                        if type(row["end"]) is not int or row["end"] != count:
                            raise ValueError("vsa_count_mismatch")
                        complete = True
                    else:
                        if count >= limit or not row.get("item_id"):
                            raise ValueError("invalid_vsa_export_record")
                        spool.write(line)
                        count += 1
                if not complete:
                    raise ValueError("incomplete_vsa_export")
                spool.seek(0)
                items = map(json.loads, spool)
            else:
                # Rolling upgrades may temporarily speak the original JSON format.
                raw = response.read()
                received = len(raw)
                items = iter(json.loads(raw)["items"])
                del raw
            while batch := list(islice(items, 24)):
                pulled += self.store_batch(batch)["stored_count"]
        if bidirectional:
            items = self.iter_export(domain=domain, limit=limit)
            while batch := list(islice(items, 24)):
                body = json.dumps({"items": batch}, ensure_ascii=False).encode("utf-8")
                req = urllib.request.Request(base + "/api/vsa/store", data=body,
                                             headers={"Content-Type": "application/json"})
                authorize(req)
                with opener.open(req, timeout=4.0) as response:
                    result = json.load(response)
                if not result.get("ok") or result.get("stored_count") != len(batch):
                    raise ValueError("peer_store_count_mismatch")
                pushed += result["stored_count"]
                peer_total = result.get("total_items")
                sent += len(body)
        return {"pulled": pulled, "pushed": pushed, "peer_total": peer_total,
                "body_bytes": received + sent}

    def stats(self) -> dict[str, Any]:
        caps = v12_native_caps()
        with self._lock:
            cnt = self._count()
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

    def ingest_tquota_thought_briefs(
        self,
        tquota_admin_url: str = "http://127.0.0.1:12504",
        *,
        limit: int = 300,
        timeout_s: float = 4.0,
    ) -> dict[str, Any]:
        """Pull verified Tquota ThoughtBrief skeletons via loopback/PHANTOM, DLP-scrub, and index into 10k-bit VSA."""
        t0 = time.perf_counter()
        base = str(tquota_admin_url or "").strip().rstrip("/")
        if not _is_loopback_http(base):
            return {"ok": False, "error": "non_loopback_tquota_url_rejected", "stored_count": 0}
        cap = max(1, min(300, int(limit or 300)))
        try:
            with urllib.request.urlopen(f"{base}/api/thought-briefs/export?limit={cap}", timeout=timeout_s) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="ignore"))
        except Exception as exc:
            return {"ok": False, "error": str(exc), "stored_count": 0}

        raw_items = list((data or {}).get("items") or []) if isinstance(data, dict) else []
        clean_items: list[dict[str, Any]] = []
        for raw in raw_items:
            if not isinstance(raw, dict):
                continue
            iid = str(raw.get("item_id") or "").strip()
            if not iid:
                continue
            txt = EgressDlpGuard.redact_text(str(raw.get("text") or iid))
            pl = EgressDlpGuard.redact_obj(raw.get("payload") if raw.get("payload") is not None else {})
            clean_items.append(
                {
                    "item_id": iid,
                    "domain": str(raw.get("domain") or "tquota_thought"),
                    "text": txt,
                    "payload": pl,
                    "reward": float(raw.get("reward", 1.0) or 1.0),
                    "vsa_hex": raw.get("vsa_hex"),
                }
            )
        res = self.store_batch(clean_items)
        return {
            "ok": True,
            "fetched": len(raw_items),
            "stored_count": int(res.get("stored_count", 0)),
            "total_items": res["total_items"],
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }

    def build_memory_capsule(
        self,
        query_text: str,
        *,
        domains: list[str] | None = None,
        top_k: int = 4,
        min_sim: float = 0.502,
        max_chars: int = 900,
    ) -> dict[str, Any]:
        """Recall high-similarity cross-stack memory crystals and pack them into a DLP-clean prompt capsule."""
        k = max(1, min(12, int(top_k or 4)))
        rec = self.recall(
            query_text=str(query_text or ""),
            domain=None,
            top_k=max(k * 4, 16),
            min_sim=float(min_sim or 0.0),
        )
        dom_set = {str(d).strip() for d in (domains or []) if str(d).strip()}
        candidates: list[tuple[float, dict[str, Any]]] = []
        seen_sig: set[str] = set()
        for m in rec.get("matches") or []:
            dom = str(m.get("domain") or "global")
            if dom_set and dom not in dom_set:
                continue
            pl = m.get("payload") if isinstance(m.get("payload"), dict) else {}
            mb = pl.get("_midbrain") if isinstance(pl.get("_midbrain"), dict) else {}
            rpe_tag = str(pl.get("rpe_tag") or mb.get("rpe_tag") or "").strip()
            immune_pinned = bool(mb.get("immune_pinned", False))
            hint_raw = str(pl.get("pivot_text") or pl.get("resolution_hint") or pl.get("brief_text") or m.get("text") or "").strip()
            hint_clean = " ".join(EgressDlpGuard.redact_text(hint_raw).split())[:220]
            sig = f"{m.get('item_id')}|{hint_clean[:60].lower()}"
            if not hint_clean or sig in seen_sig:
                continue
            seen_sig.add(sig)
            sim = float(m.get("similarity") or 0.0)
            boost = (0.08 if immune_pinned else 0.0) + (0.04 if rpe_tag else 0.0) + min(0.03, float(mb.get("ema_impact") or 0.0) * 0.02)
            candidates.append(
                (
                    sim + boost,
                    {
                        "item_id": str(m.get("item_id") or ""),
                        "domain": dom,
                        "similarity": sim,
                        "reward": float(m.get("reward") or 1.0),
                        "rpe_tag": rpe_tag,
                        "immune_pinned": immune_pinned,
                        "hint": hint_clean,
                    },
                )
            )
        candidates.sort(key=lambda pair: (pair[0], pair[1]["reward"]), reverse=True)
        selected = [pair[1] for pair in candidates[:k]]

        lines: list[str] = []
        used_chars = 0
        cap_chars = max(160, int(max_chars or 900))
        used_item_ids: list[str] = []
        for item in selected:
            tags: list[str] = []
            if item.get("immune_pinned"):
                tags.append("1%-IMMUNE")
            if item.get("rpe_tag") == "POS_BREAKTHROUGH":
                tags.append("+δ")
            elif item.get("rpe_tag") == "NEG_TRAP":
                tags.append("-δ")
            tag_prefix = ("[" + "|".join(tags) + "] ") if tags else ""
            line = f"- {tag_prefix}[{item['domain']} sim={item['similarity']:.2f}] {item['hint']}"
            if used_chars + len(line) + 1 > cap_chars and lines:
                break
            lines.append(line)
            used_chars += len(line) + 1
            if item["item_id"]:
                used_item_ids.append(item["item_id"])

        capsule = "\n".join(lines)
        return {
            "ok": True,
            "backend": rec.get("backend"),
            "hits": len(lines),
            "elapsed_ms": rec.get("elapsed_ms", 0.0),
            "capsule": capsule,
            "used_item_ids": used_item_ids,
            "matches": selected[:len(lines)],
        }

    def _refresh_immune_vault_locked(self) -> dict[str, Any]:
        total = self._count()
        pin_cap = max(3, math.ceil(total * 0.01)) if total else 0
        previously_pinned = set()

        def eligible():
            for rec in self._records():
                pl = rec["payload"] if isinstance(rec["payload"], dict) else {}
                mb = pl.get("_midbrain") if isinstance(pl.get("_midbrain"), dict) else {}
                if mb.get("immune_pinned"):
                    previously_pinned.add(rec["item_id"])
                reward = float(rec["reward"] or 1.0)
                if int(mb.get("uses") or 0) > 0 or reward > 1:
                    score = float(mb.get("ema_impact") or 0.0) * 2 + min(2.0, reward) * 0.25
                    if score > 0:
                        yield score, rec["item_id"]

        best = heapq.nlargest(pin_cap, eligible(), key=lambda entry: entry[0])
        pinned_ids = {iid for _, iid in best}
        for iid in pinned_ids.symmetric_difference(previously_pinned):
            rec = self._get(iid)
            pl = rec["payload"]
            if isinstance(pl, dict):
                mb = pl.get("_midbrain")
                if not isinstance(mb, dict):
                    mb = {"uses": 0, "wins": 0, "ema_impact": 0.5}
                rec["payload"] = {**pl, "_midbrain": {**mb, "immune_pinned": iid in pinned_ids}}
                self._persist_items([rec])
        return {"pinned_count": len(pinned_ids), "pin_cap": pin_cap, "total_items": total}

    def record_causal_feedback(
        self,
        item_ids: list[str],
        *,
        success: bool,
        rpe_delta: float = 0.0,
    ) -> dict[str, Any]:
        """Update per-crystal causal impact & refresh Top-1% Immune Vault."""
        clean_ids = [str(x).strip() for x in (item_ids or []) if str(x).strip()]
        target_signal = (1.0 if success else -0.6) + float(rpe_delta or 0.0) * 0.5
        updated = 0
        with self._lock, self._transaction(write=True):
            for iid in clean_ids:
                rec = self._get(iid)
                if not rec:
                    continue
                pl = rec.get("payload") if isinstance(rec.get("payload"), dict) else {"value": rec.get("payload")}
                mb = pl.get("_midbrain") if isinstance(pl.get("_midbrain"), dict) else {}
                uses = int(mb.get("uses") or 0) + 1
                wins = int(mb.get("wins") or 0) + (1 if success else 0)
                prev_ema = float(mb.get("ema_impact") or 0.0)
                ema = round(0.65 * prev_ema + 0.35 * target_signal, 4)
                pl["_midbrain"] = {
                    **mb,
                    "uses": uses,
                    "wins": wins,
                    "ema_impact": ema,
                    "last_feedback_at": datetime.now(timezone.utc).isoformat(),
                }
                rec["payload"] = pl
                rec["reward"] = round(max(0.2, min(5.0, float(rec.get("reward") or 1.0) + (0.3 if success else -0.15))), 3)
                self._persist_items([rec])
                updated += 1
            vault_info = self._refresh_immune_vault_locked()
        return {"ok": True, "updated_count": updated, **vault_info}

    def distill_rpe_pivots(self, *, limit: int = 200) -> dict[str, Any]:
        """Distill [+δ BREAKTHROUGH] and [-δ TRAP] pivot micro-crystals from indexed VSA entries."""
        from .midbrain_dopamine import extract_rpe_pivots

        cap = max(1, min(600, int(limit or 200)))
        with self._lock:
            rows = heapq.nlargest(
                cap, (r for r in self._records() if r.get("domain") != "rpe_pivot"),
                key=lambda r: float(r.get("reward") or 1.0),
            )
        new_items: list[dict[str, Any]] = []
        for rec in rows:
            pl = rec.get("payload") if isinstance(rec.get("payload"), dict) else {}
            src_txt = str(pl.get("brief_text") or pl.get("resolution_hint") or rec.get("text") or "")
            outcome = "win" if (bool(pl.get("verified")) or float(rec.get("reward") or 1.0) >= 1.5) else "neutral"
            for idx, piv in enumerate(extract_rpe_pivots(src_txt, outcome=outcome, max_pivots=2)):
                piv_id = f"rpe_{rec['item_id']}_{idx}"
                new_items.append(
                    {
                        "item_id": piv_id,
                        "domain": "rpe_pivot",
                        "text": piv["pivot_text"],
                        "payload": {
                            "source_id": rec["item_id"],
                            "source_domain": rec.get("domain"),
                            "rpe_tag": piv["kind"],
                            "pivot_text": piv["pivot_text"],
                        },
                        "reward": round(float(piv.get("weight") or 1.5), 3),
                    }
                )
        res = self.store_batch(new_items)
        return {"ok": True, "scanned_items": len(rows), "pivots_stored": res["stored_count"],
                "total_items": res["total_items"]}

    def prune_low_value(self, *, max_items: int = 5000) -> dict[str, Any]:
        """Evict oldest/lowest-value memories past max_items while keeping Top-1% Immune Vault entries immortal."""
        cap = max(5, int(max_items or 5000))
        with self._lock, self._transaction(write=True):
            total = self._count()
            if total <= cap:
                return {"ok": True, "evicted_count": 0, "total_items": total}

            def evictable():
                for rec in self._records():
                    pl = rec["payload"] if isinstance(rec["payload"], dict) else {}
                    mb = pl.get("_midbrain") if isinstance(pl.get("_midbrain"), dict) else {}
                    if not mb.get("immune_pinned"):
                        score = float(mb.get("ema_impact") or 0) * 2 + float(rec["reward"] or 1)
                        yield score, rec["updated_at"], rec["item_id"]

            ordered = heapq.nsmallest(total - cap, evictable(), key=lambda entry: entry[:2])
            removed_ids = [iid for _, _, iid in ordered]
            if self._conn is not None:
                self._conn.executemany("DELETE FROM vsa_items WHERE item_id=?", ((iid,) for iid in removed_ids))
            else:
                for iid in removed_ids:
                    del self._items[iid]
            remaining = total - len(removed_ids)
        return {"ok": True, "evicted_count": len(removed_ids), "total_items": remaining}

    def immune_vault_summary(self, *, limit: int = 12) -> dict[str, Any]:
        with self._lock:
            pinned: list[dict[str, Any]] = []
            for rec in self._records():
                pl = rec.get("payload") if isinstance(rec.get("payload"), dict) else {}
                mb = pl.get("_midbrain") if isinstance(pl.get("_midbrain"), dict) else {}
                if bool(mb.get("immune_pinned", False)):
                    pinned.append(
                        {
                            "item_id": rec["item_id"],
                            "domain": rec["domain"],
                            "reward": rec["reward"],
                            "ema_impact": mb.get("ema_impact", 0.0),
                            "uses": mb.get("uses", 0),
                            "wins": mb.get("wins", 0),
                            "text_preview": str(rec.get("text") or "")[:120],
                        }
                    )
            pinned.sort(key=lambda r: (float(r.get("ema_impact") or 0.0), float(r.get("reward") or 1.0)), reverse=True)
            total = self._count()
        return {"pinned_count": len(pinned), "total_items": total, "items": pinned[: max(1, int(limit or 12))]}

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                except Exception:
                    pass
                self._conn = None
