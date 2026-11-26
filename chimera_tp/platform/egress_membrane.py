"""CHIMERA-EGRESS + MEMBRANE: Loopback HTTP/HTTPS Proxy with Singleflight, TTL/ETag Cache, 429 Shield & Wire-Cassette."""

from __future__ import annotations

import collections
import hashlib
import http.client
import http.server
import json
import select
import socket
import ssl
import threading
import time
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Any, Callable


_HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "proxy-connection",
}


class _ProxyServer(http.server.ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True
    request_queue_size = 128


class EgressMembraneProxy:
    """Bounded Zero-Weight (<16 MB cache) HTTP/HTTPS Egress Proxy with Singleflight + Cache + 429 Shield + Cassette."""

    def __init__(
        self,
        listen_host: str = "127.0.0.1",
        listen_port: int = 9781,
        cassettes_dir: Path | None = None,
        max_cache_bytes: int = 12 * 1024 * 1024,
        max_cache_entries: int = 384,
        default_ttl_s: float = 30.0,
        max_retries: int = 2,
        on_flow: Callable[..., Any] | None = None,
    ) -> None:
        self.listen_host = listen_host
        self.requested_port = int(listen_port)
        self.cassettes_dir = Path(cassettes_dir) if cassettes_dir else None
        if self.cassettes_dir:
            self.cassettes_dir.mkdir(parents=True, exist_ok=True)
        self.max_cache_bytes = int(max_cache_bytes)
        self.max_cache_entries = int(max_cache_entries)
        self.default_ttl_s = float(default_ttl_s)
        self.max_retries = int(max_retries)
        self.on_flow = on_flow

        self._cache_lock = threading.Lock()
        self._cache: collections.OrderedDict[str, dict[str, Any]] = collections.OrderedDict()
        self._cache_bytes: int = 0

        self._sf_lock = threading.Lock()
        self._inflight: dict[str, dict[str, Any]] = {}

        self._stats_lock = threading.Lock()
        self._stats: dict[str, Any] = {
            "requests_total": 0,
            "cache_hits": 0,
            "etag_revalidated": 0,
            "coalesced_hits": 0,
            "retries_rescued": 0,
            "bypass_count": 0,
            "connect_tunnels": 0,
            "errors": 0,
            "bytes_saved": 0,
            "bytes_served": 0,
            "cassettes_recorded": 0,
            "hit_ms_sum": 0.0,
            "miss_ms_sum": 0.0,
            "miss_count": 0,
            "per_app": {},
        }

        self._httpd: _ProxyServer | None = None
        self._thread: threading.Thread | None = None
        self.addr: tuple[str, int] = (listen_host, 0)

    def start(self) -> "EgressMembraneProxy":
        proxy_ref = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def _do_http(self, method: str) -> None:
                proxy_ref._handle_http(self, method)

            def do_GET(self) -> None:
                self._do_http("GET")

            def do_HEAD(self) -> None:
                self._do_http("HEAD")

            def do_POST(self) -> None:
                self._do_http("POST")

            def do_PUT(self) -> None:
                self._do_http("PUT")

            def do_PATCH(self) -> None:
                self._do_http("PATCH")

            def do_DELETE(self) -> None:
                self._do_http("DELETE")

            def do_OPTIONS(self) -> None:
                self._do_http("OPTIONS")

            def do_CONNECT(self) -> None:
                proxy_ref._handle_connect(self)

            def log_message(self, *_args: object) -> None:
                pass

        # Bind strictly to loopback; if requested port is busy, fall back cleanly to +1 or ephemeral 0
        candidates = [self.requested_port]
        if self.requested_port > 0:
            candidates.extend([self.requested_port + 1, 0])
        last_exc: Exception | None = None
        for p in candidates:
            try:
                self._httpd = _ProxyServer((self.listen_host, int(p)), Handler)
                self.addr = (self.listen_host, int(self._httpd.server_address[1]))
                last_exc = None
                break
            except OSError as exc:
                last_exc = exc
        if last_exc is not None or self._httpd is None:
            raise last_exc or RuntimeError("Failed to bind EgressMembraneProxy")

        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        return self

    def close(self) -> None:
        if self._httpd is not None:
            try:
                self._httpd.shutdown()
                self._httpd.server_close()
            except Exception:
                pass
            self._httpd = None

    @property
    def url(self) -> str:
        return f"http://{self.addr[0]}:{self.addr[1]}"

    def _bump(self, app: str, **deltas: Any) -> None:
        with self._stats_lock:
            for k, v in deltas.items():
                self._stats[k] = self._stats.get(k, 0) + v
            if app:
                pa = self._stats["per_app"].setdefault(app, {"requests": 0, "hits": 0, "bytes_saved": 0})
                pa["requests"] += int(deltas.get("requests_total", 0))
                pa["hits"] += int(deltas.get("cache_hits", 0)) + int(deltas.get("coalesced_hits", 0))
                pa["bytes_saved"] += int(deltas.get("bytes_saved", 0))

    def _cache_key(self, method: str, url: str) -> str:
        return f"{method.upper()}:{url}"

    def _cache_get(self, key: str) -> tuple[dict[str, Any] | None, bool]:
        now = time.monotonic()
        with self._cache_lock:
            entry = self._cache.get(key)
            if entry is None:
                return None, False
            self._cache.move_to_end(key)
            fresh = now < float(entry["expires_at"])
            return dict(entry), fresh

    def _cache_put(self, key: str, status: int, headers: list[tuple[str, str]], body: bytes, ttl_s: float) -> None:
        if len(body) > max(1024 * 1024, self.max_cache_bytes // 4):
            return
        etag = ""
        for hk, hv in headers:
            if hk.lower() == "etag":
                etag = hv
                break
        item = {
            "status": int(status),
            "headers": list(headers),
            "body": body,
            "etag": etag,
            "size": len(body),
            "expires_at": time.monotonic() + max(0.05, ttl_s),
        }
        with self._cache_lock:
            old = self._cache.pop(key, None)
            if old is not None:
                self._cache_bytes -= int(old["size"])
            self._cache[key] = item
            self._cache_bytes += item["size"]
            while (
                len(self._cache) > self.max_cache_entries
                or self._cache_bytes > self.max_cache_bytes
            ) and self._cache:
                _, evicted = self._cache.popitem(last=False)
                self._cache_bytes -= int(evicted["size"])

    def _parse_ttl(self, headers: list[tuple[str, str]], override_hdr: str | None) -> float:
        if override_hdr:
            try:
                return max(0.0, min(3600.0, float(override_hdr)))
            except ValueError:
                pass
        for hk, hv in headers:
            if hk.lower() == "cache-control":
                low = hv.lower()
                if "no-store" in low:
                    return 0.0
                for part in low.split(","):
                    part = part.strip()
                    if part.startswith("max-age="):
                        try:
                            return max(0.0, min(3600.0, float(part.split("=", 1)[1])))
                        except ValueError:
                            pass
        return self.default_ttl_s

    def _record_cassette(
        self,
        app: str,
        method: str,
        url: str,
        req_headers: dict[str, str],
        status: int,
        resp_headers: list[tuple[str, str]],
        body: bytes,
        error: str = "",
    ) -> str | None:
        if self.cassettes_dir is None:
            return None
        ts = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S_%f")
        h = hashlib.blake2s(f"{method}:{url}:{ts}".encode("utf-8"), digest_size=4).hexdigest()
        name = f"cassette_{ts}_{h}.json"
        path = self.cassettes_dir / name
        safe_req_hdrs = {
            k: ("***" if k.lower() in ("authorization", "cookie", "x-api-key", "x-chimera-token") else v)
            for k, v in req_headers.items()
        }
        rec = {
            "id": name,
            "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
            "app": app,
            "method": method,
            "url": url,
            "request_headers": safe_req_hdrs,
            "status": status,
            "response_headers": resp_headers,
            "body_preview": body[:4096].decode("utf-8", errors="replace"),
            "body_size": len(body),
            "error": error,
        }
        try:
            path.write_text(json.dumps(rec, indent=2, ensure_ascii=False), encoding="utf-8")
            # Keep newest 50 cassettes only
            files = sorted(self.cassettes_dir.glob("cassette_*.json"))
            for old in files[:-50]:
                try:
                    old.unlink()
                except OSError:
                    pass
            self._bump(app, cassettes_recorded=1)
            return name
        except OSError:
            return None

    def list_cassettes(self, limit: int = 20) -> list[dict[str, Any]]:
        if self.cassettes_dir is None or not self.cassettes_dir.is_dir():
            return []
        files = sorted(self.cassettes_dir.glob("cassette_*.json"), reverse=True)[: max(1, limit)]
        out: list[dict[str, Any]] = []
        for f in files:
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
                out.append(
                    {
                        "id": d.get("id", f.name),
                        "ts": d.get("ts"),
                        "app": d.get("app"),
                        "method": d.get("method"),
                        "url": d.get("url"),
                        "status": d.get("status"),
                        "error": d.get("error", ""),
                    }
                )
            except Exception:
                continue
        return out

    def get_cassette(self, cid: str) -> dict[str, Any] | None:
        if self.cassettes_dir is None:
            return None
        safe = Path(cid).name
        p = self.cassettes_dir / safe
        if not p.is_file():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None

    def _upstream_fetch(
        self,
        method: str,
        url: str,
        req_headers: dict[str, str],
        req_body: bytes,
        allow_retry: bool,
        timeout_s: float = 15.0,
    ) -> tuple[int, list[tuple[str, str]], bytes, int]:
        parsed = urllib.parse.urlsplit(url)
        scheme = parsed.scheme.lower() or "http"
        host = parsed.hostname or ""
        port = parsed.port or (443 if scheme == "https" else 80)
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"

        clean_headers = {
            k: v
            for k, v in req_headers.items()
            if k.lower() not in _HOP_BY_HOP and not k.lower().startswith("x-chimera-")
        }
        clean_headers["Host"] = parsed.netloc
        clean_headers.setdefault("Accept-Encoding", "identity")

        attempts = (self.max_retries + 1) if allow_retry else 1
        retries_used = 0
        last_status = 502
        last_headers: list[tuple[str, str]] = []
        last_body = b""

        for idx in range(attempts):
            conn: http.client.HTTPConnection | None = None
            try:
                if scheme == "https":
                    ctx = ssl.create_default_context()
                    conn = http.client.HTTPSConnection(host, port, timeout=timeout_s, context=ctx)
                else:
                    conn = http.client.HTTPConnection(host, port, timeout=timeout_s)
                conn.request(method, path, body=req_body if req_body else None, headers=clean_headers)
                resp = conn.getresponse()
                body = resp.read()
                hdrs = [(k, v) for k, v in resp.getheaders() if k.lower() not in _HOP_BY_HOP]
                last_status, last_headers, last_body = resp.status, hdrs, body
                if resp.status in (429, 502, 503, 504) and allow_retry and idx < attempts - 1:
                    ra = resp.getheader("Retry-After")
                    delay = 0.08 * (idx + 1)
                    if ra:
                        try:
                            delay = min(1.5, max(0.02, float(ra)))
                        except ValueError:
                            pass
                    retries_used += 1
                    time.sleep(delay)
                    continue
                return resp.status, hdrs, body, retries_used
            except Exception as exc:
                last_status = 502
                last_headers = [("Content-Type", "application/json")]
                last_body = json.dumps({"error": f"upstream_failed: {exc}"}).encode("utf-8")
                if allow_retry and idx < attempts - 1:
                    retries_used += 1
                    time.sleep(0.06 * (idx + 1))
                    continue
                return last_status, last_headers, last_body, retries_used
            finally:
                if conn is not None:
                    try:
                        conn.close()
                    except Exception:
                        pass
        return last_status, last_headers, last_body, retries_used

    def _send_reply(
        self,
        handler: http.server.BaseHTTPRequestHandler,
        status: int,
        headers: list[tuple[str, str]],
        body: bytes,
        membrane_tag: str,
        elapsed_ms: float,
        retries: int = 0,
        cassette_id: str | None = None,
    ) -> None:
        handler.send_response(status)
        has_cl = False
        for k, v in headers:
            kl = k.lower()
            if kl in _HOP_BY_HOP:
                continue
            if kl == "content-length":
                has_cl = True
                handler.send_header("Content-Length", str(len(body)))
            else:
                handler.send_header(k, v)
        if not has_cl:
            handler.send_header("Content-Length", str(len(body)))
        handler.send_header("X-Chimera-Membrane", membrane_tag)
        handler.send_header("X-Chimera-Elapsed-Ms", f"{elapsed_ms:.2f}")
        if retries > 0:
            handler.send_header("X-Chimera-Retries", str(retries))
        if cassette_id:
            handler.send_header("X-Chimera-Cassette", cassette_id)
        handler.send_header("Connection", "close")
        handler.end_headers()
        if handler.command != "HEAD":
            handler.wfile.write(body)

    def _handle_http(self, handler: http.server.BaseHTTPRequestHandler, method: str) -> None:
        t0 = time.perf_counter()
        url = handler.path
        if not url.startswith(("http://", "https://")):
            host_hdr = handler.headers.get("Host", "")
            if host_hdr:
                url = f"http://{host_hdr}{url}"
            else:
                self._send_reply(
                    handler,
                    400,
                    [("Content-Type", "application/json")],
                    b'{"error":"absolute_url_required"}',
                    "ERROR",
                    0.0,
                )
                return

        app = str(handler.headers.get("X-Chimera-App") or "external")
        bypass = str(handler.headers.get("X-Chimera-Bypass") or "").strip() in ("1", "true", "yes")
        force_record = str(handler.headers.get("X-Chimera-Record") or "").strip() in ("1", "true", "yes")
        ttl_override = handler.headers.get("X-Chimera-TTL")
        clen = int(handler.headers.get("Content-Length", "0") or 0)
        req_body = handler.rfile.read(clen) if clen > 0 else b""
        req_headers = {k: v for k, v in handler.headers.items()}
        cacheable_method = method in ("GET", "HEAD") and not bypass and "authorization" not in {k.lower() for k in req_headers}
        ckey = self._cache_key(method, url)

        self._bump(app, requests_total=1)

        if bypass:
            self._bump(app, bypass_count=1)
            st, hdrs, body, _ = self._upstream_fetch(method, url, req_headers, req_body, allow_retry=False)
            ms = (time.perf_counter() - t0) * 1000.0
            self._bump(app, bytes_served=len(body), miss_ms_sum=ms, miss_count=1)
            self._send_reply(handler, st, hdrs, body, "BYPASS", ms)
            return

        # 1. Fast Membrane Cache lookup
        cached_entry: dict[str, Any] | None = None
        if cacheable_method:
            cached_entry, is_fresh = self._cache_get(ckey)
            if cached_entry is not None and is_fresh:
                ms = (time.perf_counter() - t0) * 1000.0
                body = cached_entry["body"]
                self._bump(app, cache_hits=1, bytes_saved=len(body), bytes_served=len(body), hit_ms_sum=ms)
                self._send_reply(handler, cached_entry["status"], cached_entry["headers"], body, "HIT", ms)
                return

        # 2. Cross-request Singleflight Coalescing for concurrent idempotent GET/HEAD
        leader = True
        sf_slot: dict[str, Any] | None = None
        if cacheable_method:
            with self._sf_lock:
                existing = self._inflight.get(ckey)
                if existing is not None:
                    leader = False
                    sf_slot = existing
                else:
                    sf_slot = {"event": threading.Event(), "result": None}
                    self._inflight[ckey] = sf_slot

        if not leader and sf_slot is not None:
            sf_slot["event"].wait(timeout=20.0)
            res = sf_slot.get("result")
            if res is not None:
                st, hdrs, body, retries = res
                ms = (time.perf_counter() - t0) * 1000.0
                self._bump(app, coalesced_hits=1, bytes_saved=len(body), bytes_served=len(body), hit_ms_sum=ms)
                self._send_reply(handler, st, hdrs, body, "COALESCED", ms, retries=retries)
                return

        # 3. Leader executes upstream fetch (with ETag conditional GET + 429/502 retry shield)
        try:
            fetch_hdrs = dict(req_headers)
            if cached_entry is not None and cached_entry.get("etag"):
                fetch_hdrs["If-None-Match"] = str(cached_entry["etag"])
            st, hdrs, body, retries = self._upstream_fetch(
                method, url, fetch_hdrs, req_body, allow_retry=(method in ("GET", "HEAD", "OPTIONS"))
            )
            membrane_tag = "MISS"
            if st == 304 and cached_entry is not None:
                st = cached_entry["status"]
                hdrs = cached_entry["headers"]
                body = cached_entry["body"]
                membrane_tag = "REVALIDATED"
                ttl_s = self._parse_ttl(hdrs, ttl_override)
                if ttl_s > 0:
                    self._cache_put(ckey, st, hdrs, body, ttl_s)
                self._bump(app, etag_revalidated=1, bytes_saved=len(body))
            elif cacheable_method and 200 <= st < 300:
                ttl_s = self._parse_ttl(hdrs, ttl_override)
                if ttl_s > 0:
                    self._cache_put(ckey, st, hdrs, body, ttl_s)

            if retries > 0 and st < 400:
                self._bump(app, retries_rescued=1)
                membrane_tag = f"{membrane_tag}+RESCUED"

            cid: str | None = None
            if st >= 500 or st == 429 or force_record:
                if st >= 500 or st == 429:
                    self._bump(app, errors=1)
                cid = self._record_cassette(app, method, url, req_headers, st, hdrs, body)

            if sf_slot is not None:
                sf_slot["result"] = (st, hdrs, body, retries)
            ms = (time.perf_counter() - t0) * 1000.0
            self._bump(app, bytes_served=len(body), miss_ms_sum=ms, miss_count=1)
            if self.on_flow is not None:
                try:
                    self.on_flow(
                        "edge",
                        app,
                        urllib.parse.urlsplit(url).hostname or "upstream",
                        f"EGRESS_{membrane_tag}",
                        wire_bytes=len(body),
                        elapsed_ms=ms,
                        detail=f"{method} {st} {url[:60]}",
                        ok=(st < 500),
                    )
                except Exception:
                    pass
            self._send_reply(handler, st, hdrs, body, membrane_tag, ms, retries=retries, cassette_id=cid)
        finally:
            if leader and sf_slot is not None:
                sf_slot["event"].set()
                with self._sf_lock:
                    if self._inflight.get(ckey) is sf_slot:
                        self._inflight.pop(ckey, None)

    def _handle_connect(self, handler: http.server.BaseHTTPRequestHandler) -> None:
        app = str(handler.headers.get("X-Chimera-App") or "external")
        self._bump(app, requests_total=1, connect_tunnels=1)
        host, _, port_s = handler.path.partition(":")
        port = int(port_s) if port_s.isdigit() else 443
        upstream: socket.socket | None = None
        try:
            upstream = socket.create_connection((host, port), timeout=10.0)
            handler.send_response(200, "Connection Established")
            handler.send_header("X-Chimera-Membrane", "TUNNEL")
            handler.end_headers()
            client_sock = handler.connection
            client_sock.setblocking(False)
            upstream.setblocking(False)
            sockets = [client_sock, upstream]
            total_bytes = 0
            idle_deadline = time.monotonic() + 60.0
            while time.monotonic() < idle_deadline:
                rlist, _, elist = select.select(sockets, [], sockets, 1.0)
                if elist:
                    break
                if not rlist:
                    continue
                idle_deadline = time.monotonic() + 60.0
                for s in rlist:
                    other = upstream if s is client_sock else client_sock
                    try:
                        chunk = s.recv(65536)
                    except BlockingIOError:
                        continue
                    if not chunk:
                        return
                    total_bytes += len(chunk)
                    other.sendall(chunk)
            self._bump(app, bytes_served=total_bytes)
        except Exception:
            self._bump(app, errors=1)
            try:
                handler.send_error(502, "CONNECT tunnel failed")
            except Exception:
                pass
        finally:
            if upstream is not None:
                try:
                    upstream.close()
                except Exception:
                    pass

    def stats(self) -> dict[str, Any]:
        with self._stats_lock:
            st = dict(self._stats)
            st["per_app"] = {k: dict(v) for k, v in self._stats["per_app"].items()}
        with self._cache_lock:
            cache_entries = len(self._cache)
            cache_bytes = self._cache_bytes
        total = max(1, int(st["requests_total"]))
        hits = int(st["cache_hits"]) + int(st["coalesced_hits"]) + int(st["etag_revalidated"])
        st["url"] = self.url
        st["port"] = self.addr[1]
        st["cache_entries"] = cache_entries
        st["cache_bytes"] = cache_bytes
        st["hit_rate_pct"] = round((hits / total) * 100.0, 2) if st["requests_total"] else 0.0
        st["avg_hit_ms"] = round(st["hit_ms_sum"] / max(1, int(st["cache_hits"]) + int(st["coalesced_hits"])), 3)
        st["avg_miss_ms"] = round(st["miss_ms_sum"] / max(1, int(st["miss_count"])), 2)
        return st
