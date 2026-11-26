"""CHIMERA-SEARCH: Unified Namespaced Hybrid AVX2 VSA-10K + SQLite FTS5 BM25 Search (<3 ms)."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from ..vsa_memory_service import SharedVsaMemoryService


class HybridPlatformSearch:
    """Combines SQLite FTS5 BM25 lexical recall with 10,000-bit AVX2 Kanerva VSA semantic recall per namespace."""

    def __init__(self, db_path: Path, vsa_service: SharedVsaMemoryService | None = None) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.vsa = vsa_service
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA synchronous=NORMAL;")
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS docs (
                namespace TEXT NOT NULL,
                doc_id TEXT NOT NULL,
                text TEXT NOT NULL,
                meta_json TEXT NOT NULL,
                updated_ts REAL NOT NULL,
                PRIMARY KEY (namespace, doc_id)
            )
            """
        )
        self._conn.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS docs_fts USING fts5(
                namespace UNINDEXED,
                doc_id UNINDEXED,
                text,
                tokenize='unicode61'
            )
            """
        )
        self._conn.commit()
        self._queries = 0

    def index_doc(self, namespace: str, doc_id: str, text: str, meta: dict[str, Any] | None = None) -> dict[str, Any]:
        ns = (namespace or "global").strip()[:64]
        did = str(doc_id).strip()[:128]
        txt = str(text or "")[:32768]
        meta_s = json.dumps(meta or {}, ensure_ascii=False)
        now = time.time()
        t0 = time.perf_counter()
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO docs(namespace, doc_id, text, meta_json, updated_ts) VALUES(?,?,?,?,?)",
                (ns, did, txt, meta_s, now),
            )
            self._conn.execute("DELETE FROM docs_fts WHERE namespace=? AND doc_id=?", (ns, did))
            self._conn.execute(
                "INSERT INTO docs_fts(namespace, doc_id, text) VALUES(?,?,?)",
                (ns, did, txt),
            )
            self._conn.commit()
        if self.vsa is not None:
            try:
                self.vsa.store(
                    item_id=f"{ns}:{did}",
                    domain=f"search:{ns}",
                    text=txt[:2048],
                    payload={"namespace": ns, "doc_id": did, "meta": meta or {}},
                )
            except Exception:
                pass
        return {
            "ok": True,
            "namespace": ns,
            "doc_id": did,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }

    def search(self, query: str, namespace: str = "global", top_k: int = 10) -> dict[str, Any]:
        t0 = time.perf_counter()
        ns = (namespace or "global").strip()[:64]
        q = str(query or "").strip()
        k = max(1, min(100, int(top_k)))
        if not q:
            return {"ok": True, "namespace": ns, "query": q, "results": [], "elapsed_ms": 0.0}

        # 1. Lexical FTS5 BM25
        lex_ranks: dict[str, float] = {}
        doc_cache: dict[str, tuple[str, dict[str, Any]]] = {}
        safe_tokens = [tok.replace('"', "") for tok in q.split() if tok.strip()]
        fts_expr = " OR ".join(f'"{t}"' for t in safe_tokens[:12]) if safe_tokens else ""

        with self._lock:
            self._queries += 1
            if fts_expr:
                try:
                    rows = self._conn.execute(
                        """
                        SELECT d.doc_id, d.text, d.meta_json, bm25(docs_fts) AS score
                        FROM docs_fts
                        JOIN docs d ON d.namespace = docs_fts.namespace AND d.doc_id = docs_fts.doc_id
                        WHERE docs_fts.namespace = ? AND docs_fts MATCH ?
                        ORDER BY score ASC
                        LIMIT ?
                        """,
                        (ns, fts_expr, k * 2),
                    ).fetchall()
                    for idx, (did, txt, mjson, _bm) in enumerate(rows):
                        lex_ranks[did] = 1.0 / (60.0 + idx + 1.0)
                        try:
                            meta = json.loads(mjson)
                        except Exception:
                            meta = {}
                        doc_cache[did] = (txt, meta)
                except sqlite3.OperationalError:
                    pass

        # 2. Semantic 10,000-bit AVX2 Kanerva VSA Recall
        vsa_ranks: dict[str, float] = {}
        if self.vsa is not None:
            try:
                v_res = self.vsa.recall(query_text=q, domain=f"search:{ns}", top_k=k * 2, min_sim=0.505)
                for idx, item in enumerate(v_res.get("matches") or []):
                    pl = item.get("payload") or {}
                    did = str(pl.get("doc_id") or "")
                    if not did:
                        continue
                    vsa_ranks[did] = (1.0 / (60.0 + idx + 1.0)) * (1.0 + float(item.get("similarity", 0.5)))
                    if did not in doc_cache:
                        with self._lock:
                            row = self._conn.execute(
                                "SELECT text, meta_json FROM docs WHERE namespace=? AND doc_id=?",
                                (ns, did),
                            ).fetchone()
                        if row:
                            try:
                                meta = json.loads(row[1])
                            except Exception:
                                meta = {}
                            doc_cache[did] = (row[0], meta)
            except Exception:
                pass

        # 3. Reciprocal Rank Fusion (BM25 + VSA-AVX2)
        all_ids = set(lex_ranks.keys()) | set(vsa_ranks.keys())
        ranked = sorted(
            all_ids,
            key=lambda did: lex_ranks.get(did, 0.0) + vsa_ranks.get(did, 0.0),
            reverse=True,
        )[:k]

        results = []
        for did in ranked:
            txt, meta = doc_cache.get(did, ("", {}))
            results.append(
                {
                    "doc_id": did,
                    "score": round(lex_ranks.get(did, 0.0) + vsa_ranks.get(did, 0.0), 5),
                    "sources": [
                        s
                        for s, ok in (("bm25", did in lex_ranks), ("vsa_avx2", did in vsa_ranks))
                        if ok
                    ],
                    "snippet": txt[:240],
                    "meta": meta,
                }
            )
        return {
            "ok": True,
            "namespace": ns,
            "query": q,
            "count": len(results),
            "results": results,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }

    def stats(self) -> dict[str, Any]:
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*), COUNT(DISTINCT namespace) FROM docs").fetchone()
            return {
                "docs": int(row[0] if row else 0),
                "namespaces": int(row[1] if row else 0),
                "queries": self._queries,
                "vsa_avx2_enabled": self.vsa is not None,
            }

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass
