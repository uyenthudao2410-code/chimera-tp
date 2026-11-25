"""CHIMERA v4.0 Breakthrough #2: Universal HTTP Warp-Edge Proxy & Speculative 0-RTT Prefetcher."""

from __future__ import annotations

import base64
import html
import http.server
import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import OrderedDict
from typing import Any, Callable

from .ghost_fs import build_propfind_xml
from .telepathy import DomainDictionary, TelepathicCodec, TelepathicStore, train_domain_dictionary

DEFAULT_EDGE_TARGETS: dict[str, dict[str, Any]] = {
    "chimera": {
        "url": "http://127.0.0.1:9780",
        "prefetch": ["/api/status", "/api/health"],
        "label": "CHIMERA Cockpit",
    },
    "radar": {
        "url": "http://127.0.0.1:8787",
        "prefetch": [],
        "label": "Radar Dashboard",
    },
    "tqouta": {
        "url": "http://127.0.0.1:12504",
        "prefetch": [],
        "label": "Tqouta Admin",
    },
}

_API_HINT_RE = re.compile(r"""(?:fetch\s*\(|href\s*=)\s*['"](/api/[a-zA-Z0-9_./-]+)['"]""")
_SAFE_PREFETCH_WORDS = ("status", "health", "stats", "list", "report", "summary", "metrics", "state", "sentinel")


def _assert_loopback_url(url: str) -> None:
    parsed = urllib.parse.urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in ("http", "https") or host not in ("127.0.0.1", "localhost", "::1"):
        raise PermissionError(f"Edge target must stay on loopback 127.0.0.1/localhost (got {url})")


def _normalize_subpath(raw_path: str, query: str = "") -> str:
    p = str(raw_path or "/").strip()
    if "://" in p or p.startswith("//"):
        raise ValueError(f"Invalid relative edge path: {raw_path}")
    if not p.startswith("/"):
        p = "/" + p
    norm = urllib.parse.urlsplit(p).path
    if ".." in norm.split("/"):
        raise ValueError(f"Path traversal rejected: {raw_path}")
    return f"{norm}?{query}" if query else norm


class EdgeGateway:
    """Server-side localhost HTTP accelerator with Telepathic compression & speculative prefetching."""

    def __init__(
        self,
        targets: dict[str, dict[str, Any]] | None = None,
        telepathy_store: TelepathicStore | None = None,
    ) -> None:
        self.targets: dict[str, dict[str, Any]] = {}
        src = targets if targets is not None else DEFAULT_EDGE_TARGETS
        for app_id, meta in src.items():
            url = str(meta.get("url", "")).rstrip("/")
            _assert_loopback_url(url)
            self.targets[str(app_id)] = {
                "url": url,
                "prefetch": [str(x) for x in meta.get("prefetch", [])],
                "label": str(meta.get("label", app_id)),
            }
        self.telepathy_store = telepathy_store or TelepathicStore(dict_dir=None, max_mem_dicts=8)
        self._codec = TelepathicCodec()
        self._lock = threading.Lock()
        self._requests = 0
        self._total_raw_bytes = 0
        self._total_wire_bytes = 0
        self._prefetched_count = 0

    def _http_call(
        self,
        full_url: str,
        method: str = "GET",
        body_bytes: bytes | None = None,
        content_type: str = "",
        timeout_s: float = 5.0,
        max_bytes: int = 4 * 1024 * 1024,
    ) -> tuple[int, str, bytes]:
        headers = {"Accept-Encoding": "identity"}
        if content_type:
            headers["Content-Type"] = content_type
        req = urllib.request.Request(
            full_url,
            data=body_bytes if method in ("POST", "PUT", "PATCH") else None,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                raw = resp.read(max_bytes)
                ct = str(resp.headers.get("Content-Type", "application/octet-stream"))
                return int(resp.status), ct, raw
        except urllib.error.HTTPError as he:
            raw = he.read(max_bytes)
            ct = str(he.headers.get("Content-Type", "text/plain"))
            return int(he.code), ct, raw

    def _encode_body(
        self,
        app_id: str,
        raw_body: bytes,
        ctype: str,
        known_dict_ids: set[str],
        attached_dicts: dict[str, dict[str, Any]],
    ) -> tuple[bytes, dict[str, Any]]:
        is_text = any(tok in ctype.lower() for tok in ("text/", "json", "javascript", "xml", "svg"))
        dd: DomainDictionary | None = None
        if is_text and len(raw_body) >= 2048:
            dom = f"edge_{app_id}"
            dd = self.telepathy_store.latest_for_domain(dom)
            if dd is None:
                dd = train_domain_dictionary([raw_body[: 128 * 1024]], domain=dom, max_dict_bytes=16384)
                self.telepathy_store.put(dd)
        frame, stats = self._codec.encode(raw_body, domain_dict=dd, allow_template_fold=True)
        used_id = str(stats.get("dict_id", ""))
        if used_id and dd is not None and used_id not in known_dict_ids and used_id not in attached_dicts:
            attached_dicts[used_id] = dd.to_wire_dict()
        return frame, stats

    def fetch(
        self,
        app_id: str,
        path: str = "/",
        query: str = "",
        method: str = "GET",
        body_b64: str = "",
        content_type: str = "",
        allow_prefetch: bool = True,
        known_dict_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        t0 = time.perf_counter()
        if app_id not in self.targets:
            raise KeyError(f"Unknown edge target: {app_id}")
        target = self.targets[app_id]
        base_url = str(target["url"])
        _assert_loopback_url(base_url)

        req_method = str(method or "GET").upper()
        if req_method not in ("GET", "POST", "HEAD"):
            raise ValueError(f"Unsupported HTTP method for EdgeGateway: {req_method}")
        rel_url = _normalize_subpath(path, query=query)
        req_body = base64.b64decode(body_b64.encode("ascii")) if body_b64 else None

        status, ctype, raw_body = self._http_call(
            f"{base_url}{rel_url}",
            method=req_method,
            body_bytes=req_body,
            content_type=content_type,
        )

        known = {str(x) for x in (known_dict_ids or [])}
        attached_dicts: dict[str, dict[str, Any]] = {}
        frame, stats = self._encode_body(app_id, raw_body, ctype, known, attached_dicts)

        prefetched: dict[str, dict[str, Any]] = {}
        prefetch_wire = 0
        if allow_prefetch and req_method == "GET" and status == 200 and "text/html" in ctype.lower():
            cand_paths: list[str] = list(target.get("prefetch", []))
            html_head = raw_body[:131072].decode("utf-8", errors="replace")
            for m in _API_HINT_RE.findall(html_head):
                if any(w in m.lower() for w in _SAFE_PREFETCH_WORDS) and m not in cand_paths:
                    cand_paths.append(m)
                if len(cand_paths) >= 4:
                    break
            for sp in cand_paths[:4]:
                try:
                    sp_norm = _normalize_subpath(sp)
                    ps, pct, praw = self._http_call(
                        f"{base_url}{sp_norm}", method="GET", timeout_s=1.2, max_bytes=512 * 1024
                    )
                    if ps == 200 and praw:
                        pf, pstats = self._encode_body(app_id, praw, pct, known, attached_dicts)
                        prefetch_wire += len(pf)
                        prefetched[sp_norm] = {
                            "status": ps,
                            "content_type": pct,
                            "raw_bytes": len(praw),
                            "wire_bytes": len(pf),
                            "frame_b64": base64.b64encode(pf).decode("ascii"),
                            "mode_name": pstats["mode_name"],
                        }
                except Exception:
                    continue

        with self._lock:
            self._requests += 1
            self._total_raw_bytes += len(raw_body)
            self._total_wire_bytes += len(frame)
            self._prefetched_count += len(prefetched)

        exec_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        return {
            "ok": True,
            "app_id": app_id,
            "path": rel_url,
            "status": status,
            "content_type": ctype,
            "raw_bytes": len(raw_body),
            "wire_bytes": len(frame),
            "plain_zlib_bytes": stats["plain_zlib_bytes"],
            "saved_vs_raw_pct": stats["saved_vs_raw_pct"],
            "mode_name": stats["mode_name"],
            "frame_b64": base64.b64encode(frame).decode("ascii"),
            "attached_dicts": attached_dicts,
            "prefetched": prefetched,
            "prefetch_wire_bytes": prefetch_wire,
            "server_exec_ms": exec_ms,
        }

    def stats(self) -> dict[str, Any]:
        with self._lock:
            saved = (
                round(max(0.0, 100.0 * (1.0 - self._total_wire_bytes / self._total_raw_bytes)), 2)
                if self._total_raw_bytes > 0
                else 0.0
            )
            return {
                "targets": {k: {"label": v["label"], "url": v["url"]} for k, v in self.targets.items()},
                "requests": self._requests,
                "total_raw_bytes": self._total_raw_bytes,
                "total_wire_bytes": self._total_wire_bytes,
                "saved_pct": saved,
                "prefetched_items": self._prefetched_count,
            }


def edge_fetch_remote(
    peer_http_base: str,
    app_id: str,
    path: str = "/",
    query: str = "",
    method: str = "GET",
    body_bytes: bytes = b"",
    content_type: str = "",
    telepathy_store: TelepathicStore | None = None,
    allow_prefetch: bool = True,
    timeout_s: float = 8.0,
) -> dict[str, Any]:
    """Fetch `app_id:path` through remote peer's `EdgeGateway` and decode Telepathic payloads."""
    t0 = time.perf_counter()
    known_ids = (
        [str(d["dict_id"]) for d in telepathy_store.list_dicts()]
        if telepathy_store is not None
        else []
    )
    req_obj = {
        "app_id": app_id,
        "path": path,
        "query": query,
        "method": method,
        "body_b64": base64.b64encode(body_bytes).decode("ascii") if body_bytes else "",
        "content_type": content_type,
        "allow_prefetch": allow_prefetch,
        "known_dict_ids": known_ids,
    }
    req = urllib.request.Request(
        f"{peer_http_base.rstrip('/')}/api/edge/fetch",
        data=json.dumps(req_obj).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        res = json.loads(resp.read().decode("utf-8"))

    attached: dict[str, DomainDictionary] = {}
    for did, wdict in (res.get("attached_dicts") or {}).items():
        dd = DomainDictionary.from_wire_dict(wdict)
        attached[did] = dd
        if telepathy_store is not None:
            telepathy_store.put(dd)

    codec = TelepathicCodec()

    def _decode_frame(frame_b64: str) -> bytes:
        raw_frame = base64.b64decode(frame_b64.encode("ascii"))
        # Try passing matching dict if attached, else fallback to telepathy_store
        try:
            return codec.decode(raw_frame, store=telepathy_store)
        except KeyError:
            for dd in attached.values():
                try:
                    return codec.decode(raw_frame, store=telepathy_store, domain_dict=dd)
                except KeyError:
                    continue
            raise

    main_body = _decode_frame(res["frame_b64"])
    decoded_prefetch: dict[str, dict[str, Any]] = {}
    for sub_path, sub_meta in (res.get("prefetched") or {}).items():
        try:
            decoded_prefetch[sub_path] = {
                "status": int(sub_meta["status"]),
                "content_type": str(sub_meta["content_type"]),
                "body": _decode_frame(sub_meta["frame_b64"]),
                "raw_bytes": int(sub_meta["raw_bytes"]),
                "wire_bytes": int(sub_meta["wire_bytes"]),
            }
        except Exception:
            continue

    total_ms = round((time.perf_counter() - t0) * 1000.0, 2)
    return {
        "ok": True,
        "app_id": app_id,
        "status": int(res["status"]),
        "content_type": str(res["content_type"]),
        "body": main_body,
        "raw_bytes": int(res["raw_bytes"]),
        "wire_bytes": int(res["wire_bytes"]),
        "saved_vs_raw_pct": float(res["saved_vs_raw_pct"]),
        "mode_name": str(res["mode_name"]),
        "prefetched": decoded_prefetch,
        "server_exec_ms": float(res.get("server_exec_ms", 0.0)),
        "total_ms": total_ms,
    }


def _fmt_dav_size(num: int) -> str:
    if num < 1024:
        return f"{num} B"
    if num < 1024 * 1024:
        return f"{num / 1024.0:.1f} KB"
    return f"{num / (1024.0 * 1024.0):.1f} MB"


def _render_dav_dir_html(rel: str, entries: list[dict[str, Any]], active_peer_base: str) -> bytes:
    """Render an interactive browser directory index for GET /dav/... requests."""
    parts = [p for p in rel.split("/") if p]
    crumbs = ['<a href="/dav/">/dav</a>']
    acc = []
    for seg in parts:
        acc.append(urllib.parse.quote(seg, safe=""))
        crumbs.append(f'<a href="/dav/{"/".join(acc)}/">{html.escape(seg)}</a>')

    rows: list[str] = []
    if parts:
        parent_href = "/dav/" if len(parts) == 1 else f'/dav/{"/".join(urllib.parse.quote(p, safe="") for p in parts[:-1])}/'
        rows.append(
            f'<tr><td><a class="dir" href="{parent_href}">[DIR] ../</a></td>'
            f'<td class="mono muted">-</td></tr>'
        )

    ordered = sorted(entries, key=lambda e: (not bool(e.get("is_dir")), str(e.get("name", "")).lower()))
    for ent in ordered:
        name = str(ent.get("name", ""))
        if not name:
            continue
        is_dir = bool(ent.get("is_dir"))
        sub_rel = "/".join([*parts, name])
        href = f"/dav/{urllib.parse.quote(sub_rel, safe='/')}" + ("/" if is_dir else "")
        cls = "dir" if is_dir else "file"
        label = f"[DIR] {html.escape(name)}/" if is_dir else html.escape(name)
        sz = "-" if is_dir else _fmt_dav_size(int(ent.get("size", 0)))
        rows.append(f'<tr><td><a class="{cls}" href="{href}">{label}</a></td><td class="mono">{sz}</td></tr>')

    body_rows = "\n".join(rows) or '<tr><td colspan="2" class="muted">(Thư mục trống)</td></tr>'
    page = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>Ghost-FS WebDAV — /dav/{html.escape(rel)}</title>"
        "<style>body{background:#0b0f17;color:#e2e8f0;font-family:system-ui,sans-serif;padding:24px;max-width:980px;margin:0 auto}"
        "a{color:#22d3ee;text-decoration:none}a:hover{text-decoration:underline}"
        "a.dir{color:#38bdf8;font-weight:700}a.file{color:#e2e8f0}"
        ".meta{background:#111827;border:1px solid #1f2937;border-radius:8px;padding:12px 14px;margin:12px 0;font-size:13px;line-height:1.5}"
        ".muted{color:#94a3b8}.mono{font-family:ui-monospace,monospace;font-size:12px}"
        "table{width:100%;border-collapse:collapse;background:#111827;border:1px solid #1f2937;border-radius:8px;overflow:hidden}"
        "th,td{padding:8px 12px;border-bottom:1px solid #1f2937;text-align:left}"
        "th{font-size:11px;text-transform:uppercase;color:#94a3b8;background:#0f172a}"
        "tr:last-child td{border-bottom:none}</style></head><body>"
        f"<h2>Ghost-FS WebDAV &mdash; {' / '.join(crumbs)}</h2>"
        f"<div class='meta'>Active Gateway: <code>{html.escape(active_peer_base)}</code> &bull; "
        "Mount thành ổ mạng Windows: <code>net use Z: http://127.0.0.1:9788/dav</code> "
        "<span class='muted'>(hoặc dùng Explorer khi dịch vụ WebClient đang bật; WebDAV PROPFIND 207 vẫn hoạt động song song)</span></div>"
        "<table><thead><tr><th>Tên mục</th><th>Kích thước</th></tr></thead>"
        f"<tbody>{body_rows}</tbody></table></body></html>"
    ).encode("utf-8")
    return page


class _ProxyHttpServer(http.server.ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True
    request_queue_size = 64


class LocalEdgeProxy:
    """Zero-Weight Windows local HTTP Edge Proxy with 0-RTT Speculative Prefetch Cache."""

    def __init__(
        self,
        listen_host: str = "127.0.0.1",
        listen_port: int = 9788,
        peer_http_base: str = "http://127.0.0.1:9780",
        targets: dict[str, dict[str, Any]] | None = None,
        telepathy_store: TelepathicStore | None = None,
        cache_ttl_s: float = 10.0,
        peer_http_resolver: Callable[[], str] | None = None,
    ) -> None:
        self.listen_host = listen_host
        self.listen_port = int(listen_port)
        self.peer_http_base = peer_http_base.rstrip("/")
        self.peer_http_resolver = peer_http_resolver
        self.targets = targets if targets is not None else DEFAULT_EDGE_TARGETS
        self.telepathy_store = telepathy_store or TelepathicStore(dict_dir=None, max_mem_dicts=8)
        self.cache_ttl_s = max(1.0, float(cache_ttl_s))

        self._lock = threading.Lock()
        self._cache: OrderedDict[tuple[str, str], tuple[int, str, bytes, float]] = OrderedDict()
        self._requests = 0
        self._prefetch_hits = 0
        self._total_raw_bytes = 0
        self._total_wire_bytes = 0
        self._httpd: _ProxyHttpServer | None = None
        self._thread: threading.Thread | None = None
        self.addr: tuple[str, int] = (listen_host, self.listen_port)

    def _cache_put(self, app_id: str, path: str, status: int, ctype: str, body: bytes) -> None:
        key = (app_id, path)
        exp = time.monotonic() + self.cache_ttl_s
        with self._lock:
            self._cache[key] = (status, ctype, body, exp)
            self._cache.move_to_end(key)
            while len(self._cache) > 32:
                self._cache.popitem(last=False)

    def _cache_get(self, app_id: str, path: str) -> tuple[int, str, bytes] | None:
        key = (app_id, path)
        now = time.monotonic()
        with self._lock:
            ent = self._cache.get(key)
            if ent is None:
                return None
            status, ctype, body, exp = ent
            if now > exp:
                self._cache.pop(key, None)
                return None
            self._cache.move_to_end(key)
            return status, ctype, body

    def _resolve_app_and_path(self, req_path: str, referer: str) -> tuple[str | None, str]:
        clean = req_path if req_path.startswith("/") else "/" + req_path
        parts = [p for p in clean.split("/") if p]
        if parts and parts[0] in self.targets:
            app_id = parts[0]
            rest = "/" + "/".join(parts[1:])
            if clean.endswith("/") and not rest.endswith("/"):
                rest += "/"
            return app_id, rest
        if referer:
            ref_parts = [p for p in urllib.parse.urlparse(referer).path.split("/") if p]
            if ref_parts and ref_parts[0] in self.targets:
                return ref_parts[0], clean
        return None, clean

    def active_peer_base(self) -> str:
        if self.peer_http_resolver is not None:
            try:
                dyn = str(self.peer_http_resolver() or "").strip()
                if dyn:
                    return dyn.rstrip("/")
            except Exception:
                pass
        return self.peer_http_base

    def stats(self) -> dict[str, Any]:
        with self._lock:
            saved = (
                round(max(0.0, 100.0 * (1.0 - self._total_wire_bytes / self._total_raw_bytes)), 2)
                if self._total_raw_bytes > 0
                else 0.0
            )
            return {
                "listen": f"http://{self.addr[0]}:{self.addr[1]}",
                "peer_http_base": self.peer_http_base,
                "active_peer_base": self.active_peer_base(),
                "requests": self._requests,
                "prefetch_hits": self._prefetch_hits,
                "total_raw_bytes": self._total_raw_bytes,
                "total_wire_bytes": self._total_wire_bytes,
                "saved_pct": saved,
                "cache_entries": len(self._cache),
            }

    def start(self) -> "LocalEdgeProxy":
        proxy_ref = self

        class ProxyHandler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            timeout = 15.0

            def _send(self, code: int, ctype: str, raw: bytes, edge_hdr: str = "PASS") -> None:
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("X-Chimera-Edge", edge_hdr)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                try:
                    self.wfile.write(raw)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass

            def _handle_dav(self, method: str) -> None:
                parsed = urllib.parse.urlparse(self.path)
                rel = urllib.parse.unquote(parsed.path[4:] if parsed.path.startswith("/dav") else "").strip("/")
                peer_base = proxy_ref.active_peer_base()
                clen = int(self.headers.get("Content-Length", "0"))
                req_body = self.rfile.read(clen) if clen > 0 else b""

                def _fetch_list(target_rel: str) -> dict[str, Any]:
                    st_url = f"{peer_base}/api/fs/list?path={urllib.parse.quote(target_rel)}&with_self=1"
                    with urllib.request.urlopen(st_url, timeout=8.0) as r:
                        return json.loads(r.read().decode("utf-8"))

                def _fetch_read(target_rel: str) -> dict[str, Any]:
                    rd_url = f"{peer_base}/api/fs/read?path={urllib.parse.quote(target_rel)}"
                    with urllib.request.urlopen(rd_url, timeout=8.0) as r:
                        return json.loads(r.read().decode("utf-8"))

                try:
                    if method == "PROPFIND":
                        depth = (self.headers.get("Depth") or "1").strip()
                        try:
                            lst = _fetch_list(rel)
                            self_ent = lst.get("self_entry") or {"name": rel or "DEV", "is_dir": True, "size": 0, "mtime": time.time()}
                            children = lst.get("entries", []) if depth != "0" else []
                        except urllib.error.HTTPError:
                            rd_url = f"{peer_base}/api/fs/stat?path={urllib.parse.quote(rel)}"
                            with urllib.request.urlopen(rd_url, timeout=6.0) as r:
                                self_ent = json.loads(r.read().decode("utf-8"))
                            children = []
                        xml = build_propfind_xml(parsed.path, self_ent, children)
                        self._send(207, "application/xml; charset=utf-8", xml, edge_hdr="GHOSTFS-DAV")
                        return

                    if method in ("GET", "HEAD"):
                        if parsed.path == "/dav":
                            self.send_response(302)
                            self.send_header("Location", "/dav/")
                            self.send_header("Content-Length", "0")
                            self.end_headers()
                            return

                        if rel == "" or parsed.path.endswith("/"):
                            lst = _fetch_list(rel)
                            page = _render_dav_dir_html(rel, list(lst.get("entries", [])), peer_base)
                            self.send_response(200)
                            self.send_header("Content-Type", "text/html; charset=utf-8")
                            self.send_header("X-Chimera-Edge", "GHOSTFS-DAV-INDEX")
                            self.send_header("Content-Length", str(len(page)))
                            self.end_headers()
                            if method == "GET":
                                self.wfile.write(page)
                            return

                        try:
                            fobj = _fetch_read(rel)
                        except urllib.error.HTTPError as read_err:
                            if int(read_err.code) in (400, 404):
                                try:
                                    _fetch_list(rel)
                                    self.send_response(302)
                                    self.send_header("Location", f"/dav/{urllib.parse.quote(rel, safe='/')}/")
                                    self.send_header("Content-Length", "0")
                                    self.end_headers()
                                    return
                                except urllib.error.HTTPError:
                                    pass
                            raise read_err

                        raw = TelepathicCodec().decode(base64.b64decode(fobj["frame_b64"].encode("ascii")))
                        self.send_response(200)
                        self.send_header("Content-Type", "text/plain; charset=utf-8" if not fobj.get("is_binary") else "application/octet-stream")
                        self.send_header("ETag", str(fobj.get("etag", "")))
                        self.send_header("X-Chimera-Edge", "GHOSTFS-DAV-TELEPATHY")
                        self.send_header("Content-Length", str(len(raw)))
                        self.end_headers()
                        if method == "GET":
                            self.wfile.write(raw)
                        return

                    if method == "PUT":
                        payload = json.dumps(
                            {
                                "path": rel,
                                "content_b64": base64.b64encode(req_body).decode("ascii"),
                                "expected_etag": (self.headers.get("If-Match") or "").strip(),
                            }
                        ).encode("utf-8")
                        req = urllib.request.Request(
                            f"{peer_base}/api/fs/write",
                            data=payload,
                            headers={"Content-Type": "application/json"},
                            method="POST",
                        )
                        with urllib.request.urlopen(req, timeout=8.0) as r:
                            _ = r.read()
                        self._send(201, "text/plain", b"Created\n", edge_hdr="GHOSTFS-DAV")
                        return

                    self._send(405, "text/plain", b"Method Not Allowed", edge_hdr="DAV")
                except urllib.error.HTTPError as he:
                    self._send(int(he.code), "application/json", he.read(), edge_hdr="GHOSTFS-DAV-ERR")
                except Exception as exc:
                    self._send(502, "application/json", json.dumps({"error": str(exc)}).encode("utf-8"), edge_hdr="GHOSTFS-DAV-ERR")

            def _forward(self, method: str) -> None:
                parsed = urllib.parse.urlparse(self.path)
                if parsed.path == "/dav" or parsed.path.startswith("/dav/"):
                    self._handle_dav(method)
                    return
                if method == "GET" and parsed.path == "/_edge_stats":
                    self._send(
                        200,
                        "application/json; charset=utf-8",
                        json.dumps(proxy_ref.stats(), ensure_ascii=False).encode("utf-8"),
                        edge_hdr="STATS",
                    )
                    return

                if method == "GET" and parsed.path == "/":
                    st = proxy_ref.stats()
                    items = "".join(
                        f'<li><a href="/{html.escape(k)}/">{html.escape(str(v.get("label", k)))}</a> '
                        f'<small style="color:#94a3b8">(/{html.escape(k)}/ &rarr; {html.escape(str(v.get("url", "")))})</small></li>'
                        for k, v in proxy_ref.targets.items()
                    )
                    items += '<li><a href="/dav/">Ghost-FS WebDAV (/dav/)</a> <small style="color:#94a3b8">(mount vào Explorer/VSCode)</small></li>'
                    page = (
                        "<!doctype html><html><head><meta charset='utf-8'>"
                        "<title>CHIMERA v5.0 PHANTOM Edge</title>"
                        "<style>body{background:#0b0f17;color:#e2e8f0;font-family:sans-serif;padding:24px}"
                        "a{color:#22d3ee;text-decoration:none;font-weight:700}</style></head><body>"
                        f"<h2>CHIMERA v5.0 Local Edge Proxy</h2>"
                        f"<p>Active Gateway: <code>{html.escape(st['active_peer_base'])}</code> | "
                        f"Saved: <b>{st['saved_pct']}%</b> | Prefetch Hits: <b>{st['prefetch_hits']}</b></p>"
                        f"<ul>{items}</ul></body></html>"
                    ).encode("utf-8")
                    self._send(200, "text/html; charset=utf-8", page, edge_hdr="LAUNCHER")
                    return

                app_id, sub_path = proxy_ref._resolve_app_and_path(
                    parsed.path, self.headers.get("Referer", "")
                )
                if app_id is None:
                    self._send(404, "application/json", b'{"error":"Unknown edge target prefix"}', edge_hdr="MISS")
                    return

                if method == "GET" and parsed.path == f"/{app_id}":
                    self.send_response(302)
                    self.send_header("Location", f"/{app_id}/")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return

                full_sub = f"{sub_path}?{parsed.query}" if parsed.query else sub_path
                if method == "GET":
                    hit = proxy_ref._cache_get(app_id, full_sub)
                    if hit is not None:
                        with proxy_ref._lock:
                            proxy_ref._requests += 1
                            proxy_ref._prefetch_hits += 1
                        self._send(hit[0], hit[1], hit[2], edge_hdr="PREFETCH-HIT-0RTT")
                        return

                clen = int(self.headers.get("Content-Length", "0"))
                req_body = self.rfile.read(clen) if clen > 0 else b""
                try:
                    res = edge_fetch_remote(
                        peer_http_base=proxy_ref.active_peer_base(),
                        app_id=app_id,
                        path=sub_path,
                        query=parsed.query,
                        method=method,
                        body_bytes=req_body,
                        content_type=self.headers.get("Content-Type", ""),
                        telepathy_store=proxy_ref.telepathy_store,
                        allow_prefetch=(method == "GET"),
                    )
                except Exception as exc:
                    err = json.dumps({"error": str(exc)}).encode("utf-8")
                    self._send(502, "application/json", err, edge_hdr="ERROR")
                    return

                with proxy_ref._lock:
                    proxy_ref._requests += 1
                    proxy_ref._total_raw_bytes += int(res["raw_bytes"])
                    proxy_ref._total_wire_bytes += int(res["wire_bytes"])

                for pf_path, pf_obj in (res.get("prefetched") or {}).items():
                    proxy_ref._cache_put(
                        app_id,
                        pf_path,
                        int(pf_obj["status"]),
                        str(pf_obj["content_type"]),
                        bytes(pf_obj["body"]),
                    )

                self._send(
                    int(res["status"]),
                    str(res["content_type"]),
                    bytes(res["body"]),
                    edge_hdr=f"TELEPATHY-{res['mode_name'].upper()}",
                )

            def do_OPTIONS(self) -> None:
                self.send_response(200)
                self.send_header("Allow", "OPTIONS, GET, HEAD, PUT, PROPFIND")
                self.send_header("DAV", "1")
                self.send_header("MS-Author-Via", "DAV")
                self.send_header("Content-Length", "0")
                self.end_headers()

            def do_PROPFIND(self) -> None:
                self._forward("PROPFIND")

            def do_HEAD(self) -> None:
                self._forward("HEAD")

            def do_PUT(self) -> None:
                self._forward("PUT")

            def do_GET(self) -> None:
                self._forward("GET")

            def do_POST(self) -> None:
                self._forward("POST")

            def log_message(self, *_args: object) -> None:
                pass

        self._httpd = _ProxyHttpServer((self.listen_host, self.listen_port), ProxyHandler)
        self.addr = (str(self._httpd.server_address[0]), int(self._httpd.server_address[1]))
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        return self

    def close(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None
