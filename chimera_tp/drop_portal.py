"""CHIMERA v5.0 Breakthrough #5: Ephemeral Zero-Cloud Drop-Portal & AI Context Teleporter."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from .telepathy import TelepathicCodec


class DropPortalStore:
    """Thread-safe ephemeral encrypted-feel compressed clipboard & file drop store with TTL."""

    def __init__(
        self,
        portal_dir: Path,
        max_items: int = 32,
        default_ttl_s: int = 600,
        max_item_bytes: int = 16 * 1024 * 1024,
    ) -> None:
        self.portal_dir = Path(portal_dir).resolve()
        self.portal_dir.mkdir(parents=True, exist_ok=True)
        self.max_items = max(1, int(max_items))
        self.default_ttl_s = max(5, int(default_ttl_s))
        self.max_item_bytes = max(1024, int(max_item_bytes))
        self._lock = threading.Lock()
        self._codec = TelepathicCodec()
        self._meta_path = self.portal_dir / "index.json"

    def _load_meta_locked(self) -> list[dict[str, Any]]:
        if not self._meta_path.is_file():
            return []
        try:
            data = json.loads(self._meta_path.read_text(encoding="utf-8"))
            return list(data) if isinstance(data, list) else []
        except Exception:
            return []

    def _save_meta_locked(self, entries: list[dict[str, Any]]) -> None:
        tmp = self._meta_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self._meta_path)

    def _purge_expired_locked(self, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        now = time.time()
        kept: list[dict[str, Any]] = []
        for ent in entries:
            blob = self.portal_dir / f"{ent['item_id']}.chdrop"
            if float(ent.get("expires_at", 0)) <= now or not blob.is_file():
                try:
                    blob.unlink(missing_ok=True)
                except OSError:
                    pass
                continue
            kept.append(ent)
        return kept

    def put_item(
        self,
        title: str,
        data: bytes,
        kind: str = "text",
        mime: str = "text/plain; charset=utf-8",
        ttl_s: int | None = None,
    ) -> dict[str, Any]:
        if len(data) > self.max_item_bytes:
            raise ValueError(f"Drop item exceeds {self.max_item_bytes} bytes")
        ttl = max(5, min(86400, int(ttl_s if ttl_s is not None else self.default_ttl_s)))
        item_id = uuid.uuid4().hex[:12]
        frame, stats = self._codec.encode(data, domain_dict=None, allow_template_fold=True)
        sha = hashlib.sha256(data).hexdigest()
        now = time.time()
        is_text = kind == "text" or mime.startswith("text/") or b"\x00" not in data[:1024]
        preview = data[:240].decode("utf-8", errors="replace") if is_text else f"<binary {len(data)} B>"

        meta = {
            "item_id": item_id,
            "kind": kind,
            "title": str(title or "drop")[:120],
            "mime": mime,
            "raw_bytes": len(data),
            "wire_bytes": len(frame),
            "saved_pct": stats["saved_vs_raw_pct"],
            "sha256": sha,
            "preview": preview,
            "created_local": datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S"),
            "expires_at": now + ttl,
            "ttl_s": ttl,
        }

        with self._lock:
            entries = self._purge_expired_locked(self._load_meta_locked())
            while len(entries) >= self.max_items:
                old = entries.pop()
                (self.portal_dir / f"{old['item_id']}.chdrop").unlink(missing_ok=True)
            blob_path = self.portal_dir / f"{item_id}.chdrop"
            tmp = blob_path.with_suffix(".tmp")
            tmp.write_bytes(frame)
            os.replace(tmp, blob_path)
            entries.insert(0, meta)
            self._save_meta_locked(entries)

        return meta

    def list_items(self) -> list[dict[str, Any]]:
        now = time.time()
        with self._lock:
            entries = self._purge_expired_locked(self._load_meta_locked())
            self._save_meta_locked(entries)
        out = []
        for ent in entries:
            c = dict(ent)
            c["remaining_s"] = max(0, int(float(ent["expires_at"]) - now))
            out.append(c)
        return out

    def get_item(self, item_id: str) -> tuple[dict[str, Any], bytes]:
        clean = re.sub(r"[^a-fA-F0-9]", "", str(item_id or ""))
        if not clean:
            raise ValueError("Invalid item_id")
        with self._lock:
            entries = self._purge_expired_locked(self._load_meta_locked())
            self._save_meta_locked(entries)
            found = next((e for e in entries if e["item_id"] == clean), None)
            if found is None:
                raise FileNotFoundError(f"Drop item not found or expired: {item_id}")
            raw_frame = (self.portal_dir / f"{clean}.chdrop").read_bytes()
        raw_bytes = self._codec.decode(raw_frame)
        return dict(found), raw_bytes

    def delete_item(self, item_id: str) -> bool:
        clean = re.sub(r"[^a-fA-F0-9]", "", str(item_id or ""))
        with self._lock:
            entries = self._load_meta_locked()
            kept = [e for e in entries if e["item_id"] != clean]
            removed = len(kept) != len(entries)
            (self.portal_dir / f"{clean}.chdrop").unlink(missing_ok=True)
            if removed:
                self._save_meta_locked(kept)
            return removed


def pack_ai_context(
    query: str,
    code_search: Any,
    sentinel: Any = None,
    allowed_roots: list[Path] | None = None,
    repo: str = "",
    max_chars: int = 8000,
) -> dict[str, Any]:
    """Assemble a concise < 8 KB copy-ready Markdown packet from FTS5 + disk context + Sentinel."""
    t0 = time.perf_counter()
    sres = code_search.search(query=query, limit=8, repo=repo)
    hits = sres.get("hits", []) or []
    roots = [Path(r).resolve() for r in (allowed_roots or [])]
    tokens = [tok.lower() for tok in re.findall(r"[\w]+", query or "") if len(tok) >= 2]

    sections: list[str] = [
        f"# AI Context Pack: `{query}`",
        f"- **FTS5 Hits:** `{sres.get('total_hits', 0)}` / `{sres.get('indexed_files', 0)}` indexed files (`{sres.get('elapsed_ms', 0)} ms`)",
        "",
        "## 1. Relevant Code & Log Excerpts",
    ]

    for h in hits[:4]:
        rel = str(h["rel_path"])
        repo_name = str(h["repo"])
        sections.append(f"### `{rel}` (repo=`{repo_name}`, score=`{h['score']}`)")
        snippet_added = False
        for root in roots:
            cand = (root / rel).resolve()
            if (root in cand.parents or cand == root) and cand.is_file() and cand.stat().st_size <= 256 * 1024:
                try:
                    lines = cand.read_text(encoding="utf-8", errors="replace").splitlines()
                    match_line = next(
                        (i for i, ln in enumerate(lines) if any(t in ln.lower() for t in tokens)),
                        0,
                    )
                    lo = max(0, match_line - 5)
                    hi = min(len(lines), match_line + 8)
                    excerpt = "\n".join(f"{j+1}: {lines[j][:180]}" for j in range(lo, hi))
                    sections.append(f"```text\n{excerpt}\n```")
                    snippet_added = True
                    break
                except OSError:
                    pass
        if not snippet_added:
            sections.append(f"> {h.get('snippet', '')}")

    alerts_used = 0
    if sentinel is not None:
        sst = sentinel.latest_status()
        alerts = sst.get("alerts") or sst.get("recent_alerts") or []
        rel_alerts = [
            a for a in alerts if not tokens or any(t in (a.get("title", "") + a.get("detail", "")).lower() for t in tokens)
        ][:4] or alerts[:2]
        if rel_alerts:
            alerts_used = len(rel_alerts)
            sections.extend(["", "## 2. Sentinel Alerts"])
            for a in rel_alerts:
                sections.append(f"- **[{a['severity']}] {a['title']}**: `{a['detail']}` → _{a['diagnosis']}_")

    # Attach top repo recent git commits if inside an allowed git directory
    if hits and roots:
        top_repo = str(hits[0]["repo"])
        for root in roots:
            rdir = (root / top_repo).resolve()
            if (root in rdir.parents) and (rdir / ".git").exists():
                try:
                    proc = subprocess.run(
                        ["git", "-C", str(rdir), "log", "-n", "4", "--oneline"],
                        capture_output=True,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                        text=True,
                        timeout=2.5,
                    )
                    if proc.returncode == 0 and proc.stdout.strip():
                        sections.extend(["", f"## 3. Recent Git History (`{top_repo}`)", f"```text\n{proc.stdout.strip()}\n```"])
                    break
                except Exception:
                    pass

    md = "\n".join(sections)
    if len(md) > max_chars:
        md = md[: max_chars - 24] + "\n... [truncated]"
    return {
        "ok": True,
        "query": query,
        "chars": len(md),
        "hits_used": min(len(hits), 4),
        "alerts_used": alerts_used,
        "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        "markdown": md,
    }
