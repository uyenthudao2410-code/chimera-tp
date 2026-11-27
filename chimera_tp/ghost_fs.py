"""CHIMERA v5.0 Breakthrough #3: Zero-RAM Ghost-FS Explorer & RFC 4918 WebDAV Bridge."""

from __future__ import annotations

import base64
import hashlib
import html
import os
import subprocess
import time
from datetime import datetime, timezone
from email.utils import formatdate
from pathlib import Path
from typing import Any

from .telepathy import TelepathicCodec


def _compute_etag(data: bytes) -> str:
    return f'"{hashlib.blake2s(data, digest_size=8).hexdigest()}"'


class GhostFsEngine:
    """Remote file browser/editor safely confined within configured repository roots."""

    def __init__(self, root_dir: Path) -> None:
        self.root_dir = Path(root_dir).resolve()
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self._codec = TelepathicCodec()

    def _resolve_rel(self, rel_path: str, for_write: bool = False) -> tuple[str, Path]:
        clean = str(rel_path or "").replace("\\", "/").strip("/")
        if clean.startswith("/") or ".." in clean.split("/"):
            raise PermissionError(f"Path traversal rejected: {rel_path}")
        parts = [p for p in clean.split("/") if p and p != "."]
        if any(p == ".git" for p in parts) and for_write:
            raise PermissionError("Writing inside .git directory is forbidden")
        target = (self.root_dir / Path(*parts)).resolve() if parts else self.root_dir
        if target != self.root_dir and self.root_dir not in target.parents:
            raise PermissionError(f"Resolved path escaped Ghost-FS root: {rel_path}")
        return "/".join(parts), target

    def stat_entry(self, rel_path: str = "") -> dict[str, Any]:
        rel_clean, target = self._resolve_rel(rel_path)
        if not target.exists():
            raise FileNotFoundError(f"Not found: {rel_clean or '/'}")
        st = target.stat()
        return {
            "name": target.name or self.root_dir.name,
            "rel_path": rel_clean,
            "is_dir": target.is_dir(),
            "size": 0 if target.is_dir() else int(st.st_size),
            "mtime": float(st.st_mtime),
            "mtime_iso": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(timespec="seconds"),
            "etag": f'"{int(st.st_size)}-{int(st.st_mtime_ns)}"',
        }

    def list_dir(self, rel_path: str = "", limit: int = 300) -> dict[str, Any]:
        t0 = time.perf_counter()
        rel_clean, target = self._resolve_rel(rel_path)
        if not target.is_dir():
            raise NotADirectoryError(f"Not a directory: {rel_clean}")
        items: list[dict[str, Any]] = []
        children = sorted(
            target.iterdir(),
            key=lambda p: (not p.is_dir(), p.name.lower()),
        )
        for p in children:
            if p.name == ".git":
                continue
            try:
                st = p.stat()
            except OSError:
                continue
            rel_c = f"{rel_clean}/{p.name}" if rel_clean else p.name
            items.append(
                {
                    "name": p.name,
                    "rel_path": rel_c,
                    "is_dir": p.is_dir(),
                    "size": 0 if p.is_dir() else int(st.st_size),
                    "mtime": float(st.st_mtime),
                    "mtime_iso": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).strftime("%Y-%m-%d %H:%M"),
                }
            )
            if len(items) >= int(limit):
                break
        return {
            "root": str(self.root_dir),
            "rel_path": rel_clean,
            "entries": items,
            "count": len(items),
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }

    def read_file(self, rel_path: str, max_bytes: int = 512 * 1024) -> dict[str, Any]:
        t0 = time.perf_counter()
        rel_clean, target = self._resolve_rel(rel_path)
        if not target.is_file():
            raise FileNotFoundError(f"File not found: {rel_clean}")
        sz = int(target.stat().st_size)
        if sz > max_bytes:
            raise ValueError(f"File exceeds {max_bytes} byte Ghost-FS cap ({sz} B)")
        raw = target.read_bytes()
        etag = _compute_etag(raw)
        is_binary = b"\x00" in raw[:4096]
        frame, stats = self._codec.encode(raw, domain_dict=None, allow_template_fold=True)
        return {
            "rel_path": rel_clean,
            "size": sz,
            "etag": etag,
            "is_binary": is_binary,
            "raw_bytes": sz,
            "wire_bytes": len(frame),
            "saved_pct": stats["saved_vs_raw_pct"],
            "frame_b64": base64.b64encode(frame).decode("ascii"),
            "text": "" if is_binary else raw.decode("utf-8", errors="replace"),
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }

    def write_file(self, rel_path: str, content: bytes, expected_etag: str = "") -> dict[str, Any]:
        rel_clean, target = self._resolve_rel(rel_path, for_write=True)
        if not rel_clean:
            raise ValueError("Cannot overwrite Ghost-FS root directory")
        if expected_etag:
            if not target.exists():
                raise FileExistsError("Target does not exist for expected ETag")
            cur_etag = _compute_etag(target.read_bytes())
            if expected_etag.strip() != cur_etag:
                raise FileExistsError(f"ETag conflict: expected {expected_etag}, current {cur_etag}")
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(f".{target.name}.chimera_tmp")
        tmp.write_bytes(content)
        os.replace(tmp, target)
        return {
            "ok": True,
            "rel_path": rel_clean,
            "size": len(content),
            "etag": _compute_etag(content),
            "written_bytes": len(content),
        }

    def git_status(self, rel_repo: str = "") -> dict[str, Any]:
        rel_clean, target = self._resolve_rel(rel_repo)
        if not target.is_dir():
            raise NotADirectoryError(f"Directory not found: {rel_clean}")
        try:
            _nw = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
            st = subprocess.run(
                ["git", "-C", str(target), "status", "--short", "--branch"],
                capture_output=True,
                text=True,
                timeout=3.0,
                creationflags=_nw,
            )
            lg = subprocess.run(
                ["git", "-C", str(target), "log", "-n", "5", "--oneline"],
                capture_output=True,
                text=True,
                timeout=3.0,
                creationflags=_nw,
            )
            return {
                "repo": rel_clean or self.root_dir.name,
                "ok": st.returncode == 0,
                "status_text": st.stdout.strip() or st.stderr.strip(),
                "recent_commits": lg.stdout.strip(),
            }
        except Exception as exc:
            return {"repo": rel_clean, "ok": False, "status_text": str(exc), "recent_commits": ""}


def build_propfind_xml(
    base_href: str,
    self_entry: dict[str, Any],
    children: list[dict[str, Any]] | None = None,
) -> bytes:
    """Render minimal RFC 4918 WebDAV PROPFIND XML multistatus response."""
    base_clean = "/" + base_href.strip("/")
    if not base_clean.endswith("/"):
        base_clean += "/"

    def _fmt_resp(href: str, ent: dict[str, Any]) -> str:
        is_dir = bool(ent.get("is_dir"))
        sz = 0 if is_dir else int(ent.get("size", 0))
        mtime = float(ent.get("mtime") or time.time())
        last_mod = formatdate(mtime, usegmt=True)
        name = html.escape(str(ent.get("name", "")))
        rtype = "<D:collection/>" if is_dir else ""
        ctype = "" if is_dir else "<D:getcontenttype>application/octet-stream</D:getcontenttype>"
        return (
            "<D:response>"
            f"<D:href>{html.escape(href)}</D:href>"
            "<D:propstat><D:prop>"
            f"<D:displayname>{name}</D:displayname>"
            f"<D:resourcetype>{rtype}</D:resourcetype>"
            f"<D:getcontentlength>{sz}</D:getcontentlength>"
            f"<D:getlastmodified>{last_mod}</D:getlastmodified>"
            f"{ctype}"
            '</D:prop><D:status>HTTP/1.1 200 OK</D:status></D:propstat>'
            "</D:response>"
        )

    blocks = [_fmt_resp(base_clean if self_entry.get("is_dir") else base_clean.rstrip("/"), self_entry)]
    for ch in children or []:
        cname = str(ch["name"])
        ch_href = f"{base_clean}{cname}" + ("/" if ch.get("is_dir") else "")
        blocks.append(_fmt_resp(ch_href, ch))

    xml = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<D:multistatus xmlns:D="DAV:">'
        + "".join(blocks)
        + "</D:multistatus>"
    )
    return xml.encode("utf-8")
