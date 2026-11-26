"""Zero-dependency Universal Client SDK (<15 KB) with automatic fallback when Chimera is absent."""

from __future__ import annotations

import json
import os
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from .discovery import discover_runtime_file


_AVAIL_LOCK = threading.Lock()
_AVAIL_CACHE: tuple[float, bool, dict[str, Any] | None] = (0.0, False, None)


def _probe_runtime(ttl_s: float = 3.0, explicit_url: str | None = None) -> tuple[bool, dict[str, Any] | None]:
    global _AVAIL_CACHE
    if explicit_url:
        try:
            with urllib.request.urlopen(f"{explicit_url.rstrip('/')}/.well-known/chimera.json", timeout=0.6) as r:
                if r.status == 200:
                    return True, json.loads(r.read().decode("utf-8"))
        except Exception:
            return False, None

    now = time.monotonic()
    with _AVAIL_LOCK:
        if (now - _AVAIL_CACHE[0]) < ttl_s:
            return _AVAIL_CACHE[1], _AVAIL_CACHE[2]

    rt = discover_runtime_file()
    anchor = (rt or {}).get("anchor_url") or os.environ.get("CHIMERA_URL", "").strip()
    ok = False
    if anchor:
        try:
            parsed = urllib.parse.urlparse(anchor)
            host = parsed.hostname or "127.0.0.1"
            port = parsed.port or 9780
            with socket.create_connection((host, port), timeout=0.25):
                ok = True
        except OSError:
            ok = False

    if ok and rt is None and anchor:
        try:
            with urllib.request.urlopen(f"{anchor.rstrip('/')}/.well-known/chimera.json", timeout=0.6) as r:
                if r.status == 200:
                    rt = json.loads(r.read().decode("utf-8"))
        except Exception:
            pass

    with _AVAIL_LOCK:
        _AVAIL_CACHE = (now, ok, rt if ok else None)
    return ok, (rt if ok else None)


def is_available(anchor_url: str | None = None) -> bool:
    """Like torch.cuda.is_available(): fast (<0.5ms cached) probe for local CHIMERA Brain."""
    ok, _ = _probe_runtime(explicit_url=anchor_url)
    return ok


class ChimeraClient:
    """Unified drop-in client for CHIMERA-CONNECT with 100% graceful offline fallback."""

    def __init__(
        self,
        app: str | None = None,
        anchor_url: str | None = None,
        auto_register: bool = True,
        port: int = 0,
        qos: str = "interactive",
        timeout_s: float = 5.0,
    ) -> None:
        self.app = app or os.environ.get("CHIMERA_APP") or Path.cwd().name or "chimera-app"
        self.timeout_s = float(timeout_s)
        self._fallback_kv: dict[str, Any] = {}
        self._fallback_events: list[dict[str, Any]] = []

        ok, rt = _probe_runtime(explicit_url=anchor_url)
        self.available: bool = bool(ok)
        self.runtime: dict[str, Any] = rt or {}
        self.anchor_url: str = (
            (anchor_url or self.runtime.get("anchor_url") or os.environ.get("CHIMERA_URL") or "http://127.0.0.1:9780")
            .rstrip("/")
        )
        self.proxy_url: str = (
            self.runtime.get("egress_proxy_url")
            or os.environ.get("CHIMERA_EGRESS_PROXY")
            or ""
        )
        self.token: str = str(self.runtime.get("boot_token") or os.environ.get("CHIMERA_TOKEN") or "")

        if self.available and auto_register:
            self._register_async(port=port, qos=qos)

    def _register_async(self, port: int = 0, qos: str = "interactive") -> None:
        def _send() -> None:
            try:
                self._post_json(
                    "/v1/apps/register",
                    {
                        "app": self.app,
                        "pid": os.getpid(),
                        "cwd": str(Path.cwd()),
                        "port": int(port),
                        "qos": qos,
                        "attach_mode": "sdk",
                    },
                    timeout=1.0,
                )
            except Exception:
                pass

        threading.Thread(target=_send, daemon=True).start()

    def _headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        h = {
            "X-Chimera-App": self.app,
            "Content-Type": "application/json",
        }
        if self.token:
            h["X-Chimera-Token"] = self.token
        if extra:
            h.update(extra)
        return h

    def _get_json(self, path: str, timeout: float | None = None) -> dict[str, Any]:
        req = urllib.request.Request(f"{self.anchor_url}{path}", headers=self._headers())
        with urllib.request.urlopen(req, timeout=timeout or self.timeout_s) as r:
            return json.loads(r.read().decode("utf-8"))

    def _post_json(self, path: str, body: dict[str, Any], timeout: float | None = None) -> dict[str, Any]:
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            f"{self.anchor_url}{path}",
            data=raw,
            headers=self._headers(),
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout or self.timeout_s) as r:
            return json.loads(r.read().decode("utf-8"))

    def capabilities(self) -> dict[str, Any]:
        if not self.available:
            return {"available": False, "fallback": True}
        try:
            return self._get_json("/.well-known/chimera.json")
        except Exception as exc:
            return {"available": False, "error": str(exc)}

    def fetch(
        self,
        url: str,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        data: bytes | None = None,
        bypass: bool = False,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        hdrs = dict(headers or {})
        hdrs.setdefault("X-Chimera-App", self.app)
        if bypass:
            hdrs["X-Chimera-Bypass"] = "1"
        req = urllib.request.Request(url, data=data, headers=hdrs, method=method.upper())
        t0 = time.perf_counter()
        if self.available and self.proxy_url:
            opener = urllib.request.build_opener(
                urllib.request.ProxyHandler({"http": self.proxy_url, "https": self.proxy_url})
            )
            with opener.open(req, timeout=timeout or self.timeout_s) as r:
                body = r.read()
                return {
                    "status": r.status,
                    "body": body,
                    "headers": dict(r.headers),
                    "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
                    "via": "chimera_egress",
                    "membrane": r.headers.get("X-Chimera-Membrane", "MISS"),
                }
        with urllib.request.urlopen(req, timeout=timeout or self.timeout_s) as r:
            body = r.read()
            return {
                "status": r.status,
                "body": body,
                "headers": dict(r.headers),
                "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
                "via": "direct_fallback",
                "membrane": "BYPASS",
            }

    def pulse_publish(self, topic: str, payload: Any, relay: bool = True) -> dict[str, Any]:
        if not self.available:
            ev = {"seq": len(self._fallback_events) + 1, "topic": topic, "payload": payload, "app": self.app}
            self._fallback_events.append(ev)
            return {"ok": True, "via": "local_fallback", "event": ev}
        return self._post_json(
            "/v1/pulse/publish",
            {"topic": topic, "payload": payload, "app": self.app, "relay": relay},
        )

    def pulse_poll(self, topic: str = "*", since: int = 0, limit: int = 50, wait_ms: int = 0) -> dict[str, Any]:
        if not self.available:
            evs = [e for e in self._fallback_events if e["seq"] > since]
            return {"ok": True, "via": "local_fallback", "events": evs[-limit:]}
        qs = urllib.parse.urlencode({"topic": topic, "since": since, "limit": limit, "wait_ms": wait_ms})
        return self._get_json(f"/v1/pulse/events?{qs}", timeout=max(self.timeout_s, wait_ms / 1000.0 + 2.0))

    def kv_set(self, key: str, value: Any, ttl_s: float = 0.0) -> dict[str, Any]:
        if not self.available:
            self._fallback_kv[key] = value
            return {"ok": True, "via": "local_fallback", "key": key}
        return self._post_json("/v1/pulse/kv", {"key": key, "value": value, "ttl_s": ttl_s, "app": self.app})

    def kv_get(self, key: str, default: Any = None) -> Any:
        if not self.available:
            return self._fallback_kv.get(key, default)
        qs = urllib.parse.urlencode({"key": key})
        res = self._get_json(f"/v1/pulse/kv?{qs}")
        return res.get("value", default) if res.get("found") else default

    def search_index(self, doc_id: str, text: str, namespace: str | None = None, meta: dict[str, Any] | None = None) -> dict[str, Any]:
        ns = namespace or self.app
        if not self.available:
            return {"ok": False, "via": "local_fallback"}
        return self._post_json(
            "/v1/search/index",
            {"namespace": ns, "doc_id": doc_id, "text": text, "meta": meta or {}},
        )

    def search(self, query: str, namespace: str | None = None, top_k: int = 10) -> dict[str, Any]:
        ns = namespace or self.app
        if not self.available:
            return {"ok": True, "via": "local_fallback", "results": []}
        qs = urllib.parse.urlencode({"namespace": ns, "q": query, "top_k": top_k})
        return self._get_json(f"/v1/search?{qs}")

    def secret(self, name: str, default: str = "") -> str:
        if self.available:
            try:
                res = self._post_json("/v1/secrets/get", {"name": name, "app": self.app}, timeout=1.5)
                if res.get("found"):
                    return str(res.get("value", ""))
            except Exception:
                pass
        return os.environ.get(name, default)

    def freeze_blackbox(self, reason: str = "client_trigger") -> dict[str, Any]:
        if not self.available:
            return {"ok": False, "via": "local_fallback"}
        return self._post_json("/v1/blackbox/freeze", {"reason": reason, "app": self.app})

    def embed(self, texts: str | list[str], dim: int = 256) -> dict[str, Any]:
        if not self.available:
            return {"ok": False, "via": "local_fallback", "data": []}
        return self._post_json("/v1/openai/v1/embeddings", {"input": texts, "dimensions": dim, "app": self.app})

    def pareto_route(self, max_ms: float = 500.0, max_cost_usd: float = 0.0, min_tier: str = "standard") -> dict[str, Any]:
        if not self.available:
            return {"ok": True, "selected": {"engine": "local_fallback", "est_cost_usd": 0.0}}
        return self._post_json(
            "/v1/vgpu/route",
            {"max_ms": max_ms, "max_cost_usd": max_cost_usd, "min_tier": min_tier},
        )

    def job_create(self, job_id: str | None = None, name: str = "workflow", total_steps: int = 1) -> dict[str, Any]:
        if not self.available:
            return {"ok": True, "via": "local_fallback", "job_id": job_id or "local-job", "completed_outputs": {}}
        return self._post_json("/v1/jobs/create", {"job_id": job_id, "app": self.app, "name": name, "total_steps": total_steps})

    def job_step(self, job_id: str, step_key: str, step_index: int = 0, result: Any = None, status: str = "completed") -> dict[str, Any]:
        if not self.available:
            return {"ok": True, "via": "local_fallback", "already_completed": False}
        return self._post_json(
            "/v1/jobs/step",
            {"job_id": job_id, "step_key": step_key, "step_index": step_index, "status": status, "result": result},
        )

    def job_resume(self, job_id: str) -> dict[str, Any]:
        if not self.available:
            return {"ok": False, "via": "local_fallback"}
        return self._get_json(f"/v1/jobs/resume?{urllib.parse.urlencode({'job_id': job_id})}")

    def zygote_exec(self, kernel: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.available:
            return {"ok": False, "via": "local_fallback"}
        return self._post_json("/v1/zygote/exec", {"kernel": kernel, "payload": payload})

    def canary_compare(self, baseline_url: str, canary_url: str, paths: list[str] | None = None, samples: int = 5) -> dict[str, Any]:
        if not self.available:
            return {"ok": False, "via": "local_fallback"}
        return self._post_json(
            "/v1/canary/compare",
            {"baseline_url": baseline_url, "canary_url": canary_url, "paths": paths or ["/"], "samples": samples},
        )

    def vault_sql_sync(self, name: str, peer_base: str | None = None) -> dict[str, Any]:
        if not self.available:
            return {"ok": False, "via": "local_fallback"}
        return self._post_json("/v1/vault-sql/sync", {"name": name, "peer_base": peer_base})

    def vault_sql_query(self, name: str, sql: str, params: list[Any] | None = None, limit: int = 200) -> dict[str, Any]:
        if not self.available:
            return {"ok": False, "via": "local_fallback", "rows": []}
        return self._post_json("/v1/vault-sql/query", {"name": name, "sql": sql, "params": params or [], "limit": limit})


def connect(
    app: str | None = None,
    anchor_url: str | None = None,
    auto_register: bool = True,
    port: int = 0,
    qos: str = "interactive",
) -> ChimeraClient:
    return ChimeraClient(
        app=app,
        anchor_url=anchor_url,
        auto_register=auto_register,
        port=port,
        qos=qos,
    )
