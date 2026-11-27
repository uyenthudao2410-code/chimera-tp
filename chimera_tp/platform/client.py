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
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout_s) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if not path.startswith("/v1/agent/") or exc.code not in {401, 403, 409}:
                raise
            # An explicit admission decision must not trigger in-process execution.
            with exc:
                try:
                    response = json.load(exc)
                except (ValueError, OSError):
                    response = None
            if isinstance(response, dict) and response.get("error"):
                return {**response, "ok": False}
            return {"ok": False, "error": f"agent_http_{exc.code}"}

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

    def embed(self, texts: str | list[str], dim: int = 256, prefer_cuda: bool = False) -> dict[str, Any]:
        if not self.available:
            return {"ok": False, "via": "local_fallback", "data": []}
        return self._post_json(
            "/v1/openai/v1/embeddings",
            {"input": texts, "dimensions": dim, "app": self.app, "prefer_cuda": prefer_cuda},
            timeout=240.0 if prefer_cuda else self.timeout_s,
        )

    def compute(
        self,
        task_kind: str,
        payload: dict[str, Any] | None = None,
        *,
        prefer_cuda: bool = False,
        profile: str | None = None,
    ) -> dict[str, Any]:
        """Single unified CHIMERA-VGPU compute call: auto-routes across Colab Pro Elastic GPU, PTX JIT, and AVX2 CPU."""
        if not self.available:
            return {"ok": False, "via": "local_fallback"}
        return self._post_json(
            "/v1/vgpu/compute",
            {
                "task_kind": task_kind,
                "payload": payload or {},
                "prefer_cuda": prefer_cuda,
                "profile": profile,
                "app": self.app,
            },
            timeout=240.0,
        )

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

    def colab_status(self, refresh: bool = False) -> dict[str, Any]:
        if not self.available:
            return {"ok": False, "via": "local_fallback", "usage": {"available": False}}
        q = "?refresh=1" if refresh else ""
        return self._get_json(f"/v1/vgpu/colab/status{q}", timeout=12.0)

    def colab_exec(
        self,
        task_kind: str = "cuda_embed",
        payload: dict[str, Any] | None = None,
        *,
        profile: str | None = None,
        session: str | None = None,
        keep_session: bool = False,
        require_gpu: bool = False,
        allow_heavy_gpu: bool = False,
    ) -> dict[str, Any]:
        if not self.available:
            return {"ok": False, "via": "local_fallback"}
        return self._post_json(
            "/v1/vgpu/colab/exec",
            {
                "task_kind": task_kind,
                "payload": payload or {},
                "profile": profile,
                "session": session,
                "keep_session": keep_session,
                "require_gpu": require_gpu,
                "allow_heavy_gpu": allow_heavy_gpu,
            },
            timeout=240.0,
        )

    def colab_stop(self, session: str) -> dict[str, Any]:
        if not self.available:
            return {"ok": False, "via": "local_fallback"}
        return self._post_json("/v1/vgpu/colab/stop", {"session": session}, timeout=30.0)

    def hyperdesk_diagnose(self) -> dict[str, Any]:
        if not self.available:
            return {"ok": False, "via": "local_fallback"}
        return self._get_json("/v1/hyperdesk/diagnose", timeout=10.0)

    def hyperdesk_optimize(self, dry_run: bool = False) -> dict[str, Any]:
        if not self.available:
            return {"ok": False, "via": "local_fallback"}
        return self._post_json("/v1/hyperdesk/optimize", {"dry_run": dry_run}, timeout=15.0)

    def hyperdesk_autonomic(self, action: str = "status", policy: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.available:
            return {"ok": False, "via": "local_fallback"}
        if action == "status" and not policy:
            return self._get_json("/v1/hyperdesk/autonomic", timeout=10.0)
        body: dict[str, Any] = {"action": action}
        if policy:
            body["policy"] = policy
        return self._post_json("/v1/hyperdesk/autonomic", body, timeout=15.0)

    def nvme_mirage(self, action: str = "status", path: str = "", dry_run: bool = False) -> dict[str, Any]:
        if not self.available:
            return {"ok": False, "via": "local_fallback"}
        if action == "status":
            return self._get_json("/v1/hyperdesk/mirage/status", timeout=10.0)
        if action == "promote":
            return self._post_json("/v1/hyperdesk/mirage/promote", {"path": path, "dry_run": dry_run}, timeout=300.0)
        if action == "demote":
            return self._post_json("/v1/hyperdesk/mirage/demote", {"path": path}, timeout=300.0)
        if action == "sync":
            return self._post_json("/v1/hyperdesk/mirage/sync", {"path": path or None}, timeout=180.0)
        return self._post_json("/v1/hyperdesk/mirage/bench", {"path": path or "."}, timeout=30.0)

    def agent_exile(self, cmd: str, cwd: str | None = None, target: str = "auto", sync_workspace: bool = False,
                    *, environment_id: str = "", reuse: bool = False, artifacts=(),
                    require_io_limit: bool = False, timeout_s: float = 120.0) -> dict[str, Any]:
        if target == "local":
            from .guarded_build import submit

            # Local is the caller's workstation, including when its optional anchor is offline.
            return submit(cmd, cwd=cwd or Path.cwd(), target="local", sync=True, environment_id=environment_id,
                          reuse=reuse, artifacts=artifacts, require_io_limit=require_io_limit, timeout_s=timeout_s)
        if not self.available:
            return {"ok": False, "via": "local_fallback"}
        status = self._get_json("/v1/exile/status", timeout=4)
        if status.get("build_protocol") != 1:
            local = urllib.parse.urlsplit(self.anchor_url).hostname in {"127.0.0.1", "localhost", "::1"}
            if not local or target not in {"svhome", "auto", "colab"} or not status.get("ok"):
                return {"ok": False, "error": "verified_exile_protocol_unavailable", "state": "deferred"}
            cartridges = self.capabilities().get("cartridges", {})
            if cartridges.get("hyper_desk", {}).get("status") != "active":
                return {"ok": False, "state": "deferred", "error": "local_exile_cartridge_inactive"}
            if target == "colab":
                from .discovery import chimera_home_dir
                from .exile_colab import run_local

                if cartridges.get("vgpu_pareto", {}).get("status") != "active":
                    return {"ok": False, "state": "deferred", "error": "local_colab_cartridge_inactive"}
                return {**run_local(cmd, chimera_home_dir() / "exile-colab"), "via": "local_client_colab"}
            from .guarded_build import submit
            result = submit(cmd, cwd=cwd, peer=status["ssh_host"], remote_root=status["remote_dev_root"],
                            sync=sync_workspace, environment_id=environment_id, reuse=reuse,
                            artifacts=artifacts, require_io_limit=require_io_limit, timeout_s=timeout_s)
            return {**result, "via": "local_client_ssh"}
        return self._post_json(
            "/v1/exile/run",
            {"cmd": cmd, "cwd": cwd, "target": target, "sync_workspace": sync_workspace,
             "reuse": reuse, "environment_id": environment_id, "artifacts": list(artifacts),
             "require_io_limit": require_io_limit, "timeout_s": timeout_s},
            timeout=max(180.0, timeout_s + 60.0, 600.0 if target == "colab" else 0),
        )

    def exile_handoff(
        self,
        steps: list[dict[str, Any]] | None = None,
        *,
        payload: Any = None,
        blocks: dict[str, Any] | list[Any] | None = None,
        op: str = "sha256_manifest",
        params: dict[str, Any] | None = None,
        job_id: str | None = None,
        prefer_target: str | None = None,
        step_key: str = "step_0",
    ) -> dict[str, Any]:
        if not self.available:
            return {"ok": False, "via": "local_fallback"}
        body: dict[str, Any] = {
            "job_id": job_id,
            "prefer_target": prefer_target,
            "app": self.app,
        }
        if steps is not None:
            body["steps"] = steps
        else:
            body.update({
                "step_key": step_key,
                "payload": payload,
                "blocks": blocks,
                "op": op,
                "params": params or {},
            })
        try:
            return self._post_json("/v1/exile/handoff", body, timeout=180.0)
        except urllib.error.HTTPError as exc:
            # Older anchors return 502 even for a valid, resumable handoff.
            with exc:
                try:
                    reply = json.load(exc)
                except (UnicodeError, ValueError):
                    raise exc from None
            if isinstance(reply, dict) and reply.get("job_id") and isinstance(reply.get("steps"), list):
                return reply
            raise

    def exile_receipts(self, job_id: str | None = None, limit: int = 50) -> dict[str, Any]:
        if not self.available:
            return {"ok": False, "via": "local_fallback", "receipts": []}
        params: dict[str, str] = {"limit": str(int(limit))}
        if job_id:
            params["job_id"] = job_id
        return self._get_json(f"/v1/exile/receipts?{urllib.parse.urlencode(params)}")

    def evidence(self, capability: str | None = None) -> dict[str, Any]:
        if not self.available:
            return {"ok": False, "via": "local_fallback"}
        if capability:
            return self._get_json(f"/v1/evidence?{urllib.parse.urlencode({'capability': capability})}")
        return self._get_json("/v1/evidence")

    def evidence_record(
        self,
        capability: str,
        *,
        execution_node: str | None = None,
        fallback_mode: str | None = None,
        ttl_s: float = 300.0,
        verified: bool = True,
        violated: bool = False,
        metrics: dict[str, Any] | None = None,
        receipt_id: str | None = None,
    ) -> dict[str, Any]:
        if not self.available:
            return {"ok": False, "via": "local_fallback"}
        body: dict[str, Any] = {
            "capability": capability,
            "fallback_mode": fallback_mode,
            "ttl_s": float(ttl_s),
            "verified": bool(verified),
            "violated": bool(violated),
            "metrics": metrics,
            "receipt_id": receipt_id,
        }
        if execution_node is not None:
            body["execution_node"] = execution_node
        return self._post_json("/v1/evidence/record", body)

    def omni_put(self, key: str, value: Any, namespace: str | None = None) -> dict[str, Any]:
        if not self.available:
            return self.kv_set(key, value)
        return self._post_json("/v1/cosmos/omni/put", {"key": key, "value": value, "namespace": namespace or self.app})

    def omni_get(self, key: str, namespace: str | None = None, as_of_seq: int | None = None) -> dict[str, Any]:
        if not self.available:
            return {"ok": True, "found": key in self._fallback_kv, "value": self._fallback_kv.get(key)}
        params = {"key": key, "namespace": namespace or self.app}
        if as_of_seq is not None:
            params["as_of_seq"] = str(as_of_seq)
        return self._get_json(f"/v1/cosmos/omni/get?{urllib.parse.urlencode(params)}")

    def intent_compile(self, service: str, invariants: dict[str, Any]) -> dict[str, Any]:
        if not self.available:
            return {"ok": False, "via": "local_fallback"}
        return self._post_json("/v1/omega/intent/compile", {"service": service, "invariants": invariants})

    def omega_benchmark(self) -> dict[str, Any]:
        if not self.available:
            return {"ok": False, "via": "local_fallback"}
        return self._post_json("/v1/omega/benchmark", {}, timeout=30.0)

    def openai_forensics(self, limit: int = 32) -> dict[str, Any]:
        if not self.available:
            return {"ok": False, "via": "local_fallback", "forensics": []}
        return self._get_json(f"/v1/openai/forensics?limit={int(limit)}")

    def openai_precog_stats(self) -> dict[str, Any]:
        if not self.available:
            return {"ok": False, "via": "local_fallback"}
        return self._get_json("/v1/openai/precog/stats")

    def openai_turns(self, limit: int = 20) -> dict[str, Any]:
        if not self.available:
            return {"ok": False, "via": "local_fallback", "turns": [], "checkpoints": []}
        return self._get_json(f"/v1/openai/turns?limit={int(limit)}")

    def turn_checkpoint(
        self,
        turn_id: str,
        root: str,
        rel_paths: list[str],
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self.available:
            return {"ok": False, "via": "local_fallback"}
        return self._post_json(
            "/v1/openai/turn/checkpoint",
            {"turn_id": turn_id, "root": root, "rel_paths": list(rel_paths), "meta": dict(meta or {})},
        )

    def turn_finalize(self, turn_id: str) -> dict[str, Any]:
        if not self.available:
            return {"ok": False, "via": "local_fallback"}
        return self._post_json("/v1/openai/turn/finalize", {"turn_id": turn_id})

    def turn_rollback(self, turn_id: str, *, force: bool = False) -> dict[str, Any]:
        if not self.available:
            return {"ok": False, "via": "local_fallback"}
        return self._post_json("/v1/openai/turn/rollback", {"turn_id": turn_id, "force": bool(force)})

    def egress_pops(self) -> dict[str, Any]:
        if not self.available:
            return {"ok": False, "via": "local_fallback", "pops": []}
        return self._get_json("/v1/egress/pops")

    def blackbox_forensics(self, kind: str = "", limit: int = 32) -> dict[str, Any]:
        if not self.available:
            return {"ok": False, "via": "local_fallback", "forensics": []}
        params = {"limit": str(int(limit))}
        if kind:
            params["kind"] = kind
        return self._get_json(f"/v1/blackbox/forensics?{urllib.parse.urlencode(params)}")

    # --- CHIMERA-ONE Organ 3: Zero-Spawn Agent Hyper-Bus (auto local in-process fallback!) ---
    def xray_batch(
        self,
        ops: list[dict[str, Any]],
        *,
        cwd: str | None = None,
        max_workers: int = 8,
        compact: bool = True,
        agent_id: str = "",
    ) -> dict[str, Any]:
        if self.available:
            try:
                return self._post_json(
                    "/v1/agent/xray-batch",
                    {"ops": ops, "cwd": cwd, "max_workers": max_workers, "compact": compact, "agent_id": agent_id},
                    timeout=30.0,
                )
            except Exception:
                pass
        from .agent_probe import get_default_agent_bus

        res = get_default_agent_bus().xray_batch(ops, cwd=cwd, max_workers=max_workers, compact=compact, agent_id=agent_id)
        res["via"] = "in_process_fallback"
        return res

    def callgraph_slice(
        self,
        repo: str,
        symbol: str,
        *,
        depth: int = 2,
        include_tests: bool = True,
        max_chars: int = 4500,
    ) -> dict[str, Any]:
        if self.available:
            try:
                return self._post_json(
                    "/v1/agent/callgraph-slice",
                    {
                        "repo": repo,
                        "symbol": symbol,
                        "depth": depth,
                        "include_tests": include_tests,
                        "max_chars": max_chars,
                    },
                    timeout=30.0,
                )
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    try:
                        return json.loads(exc.read().decode("utf-8"))
                    except Exception:
                        pass
            except Exception:
                pass
        from .agent_probe import get_default_agent_bus

        res = get_default_agent_bus().callgraph_slice(
            repo, symbol, depth=depth, include_tests=include_tests, max_chars=max_chars
        )
        res["via"] = "in_process_fallback"
        return res

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
        if self.available:
            try:
                return self._post_json(
                    "/v1/agent/commit-verify",
                    {
                        "repo": repo,
                        "files": files,
                        "run_tests": run_tests,
                        "explicit_tests": explicit_tests,
                        "max_tests": max_tests,
                        "timeout_s": timeout_s,
                        "use_cache": use_cache,
                        "compact": compact,
                    },
                    timeout=max(30.0, float(timeout_s) + 15.0),
                )
            except Exception:
                pass
        from .agent_probe import get_default_agent_bus

        res = get_default_agent_bus().commit_verify(
            repo,
            files=files,
            run_tests=run_tests,
            explicit_tests=explicit_tests,
            max_tests=max_tests,
            timeout_s=timeout_s,
            use_cache=use_cache,
            compact=compact,
        )
        res["via"] = "in_process_fallback"
        return res

    def agent_probe_stats(self) -> dict[str, Any]:
        if self.available:
            try:
                return self._get_json("/v1/agent/probe-stats")
            except Exception:
                pass
        from .agent_probe import get_default_agent_bus

        res = get_default_agent_bus().stats()
        res["via"] = "in_process_fallback"
        return res

    def agent_hive(self, action: str = "status", **kwargs: Any) -> dict[str, Any]:
        payload = {"action": action, **kwargs}
        if self.available:
            try:
                return self._post_json("/v1/agent/hive", payload, timeout=10.0)
            except Exception:
                pass
        from .agent_probe import get_default_agent_bus

        hive = get_default_agent_bus().symbiont.hive
        act = str(action or "status").lower()
        if act == "lease":
            res = hive.acquire_lease(
                agent_id=str(kwargs.get("agent_id") or "agent"),
                repo=str(kwargs.get("repo") or "."),
                files=list(kwargs.get("files") or []),
                intent=str(kwargs.get("intent") or ""),
                action=str(kwargs.get("lease_action") or "edit"),
                ttl_s=float(kwargs.get("ttl_s") or 120.0),
            )
        elif act == "release":
            res = hive.release_lease(agent_id=str(kwargs.get("agent_id") or "agent"), repo=kwargs.get("repo"))
        elif act == "immune_add":
            res = hive.add_immune_rule(
                pattern=str(kwargs.get("pattern") or ""),
                warning=str(kwargs.get("warning") or ""),
                scope=str(kwargs.get("scope") or "global"),
                severity=str(kwargs.get("severity") or "warn"),
                created_by=str(kwargs.get("agent_id") or "agent"),
            )
        elif act == "immune_list":
            res = {"ok": True, "rules": hive.list_immune(limit=int(kwargs.get("limit") or 32))}
        else:
            res = hive.status(repo=kwargs.get("repo"))
        res["via"] = "in_process_fallback"
        return res

    def atomic_patch(
        self,
        repo: str,
        edits: list[dict[str, Any]],
        *,
        agent_id: str = "agent",
        run_tests: bool = True,
        explicit_tests: list[str] | None = None,
        rollback_on_fail: bool = True,
        max_tests: int = 4,
        timeout_s: float = 60.0,
        record_immune_on_gate_fail: bool = False,
    ) -> dict[str, Any]:
        payload = {
            "repo": repo,
            "edits": edits,
            "agent_id": agent_id,
            "run_tests": run_tests,
            "explicit_tests": explicit_tests,
            "rollback_on_fail": rollback_on_fail,
            "max_tests": max_tests,
            "timeout_s": timeout_s,
            "record_immune_on_gate_fail": record_immune_on_gate_fail,
        }
        if self.available:
            try:
                return self._post_json("/v1/agent/atomic-patch", payload, timeout=max(30.0, float(timeout_s) + 15.0))
            except Exception:
                pass
        from .agent_probe import get_default_agent_bus

        res = get_default_agent_bus().symbiont.surgeon.atomic_patch(
            repo,
            edits,
            agent_id=agent_id,
            run_tests=run_tests,
            explicit_tests=explicit_tests,
            rollback_on_fail=rollback_on_fail,
            max_tests=max_tests,
            timeout_s=timeout_s,
            record_immune_on_gate_fail=record_immune_on_gate_fail,
        )
        res["via"] = "in_process_fallback"
        return res

    def agent_precog(self, action: str = "status", **kwargs: Any) -> dict[str, Any]:
        payload = {"action": action, **kwargs}
        if self.available:
            try:
                return self._post_json("/v1/agent/precog", payload, timeout=15.0)
            except Exception:
                pass
        from .agent_probe import get_default_agent_bus

        precog = get_default_agent_bus().symbiont.precog
        act = str(action or "status").lower()
        if act == "notify_save":
            res = precog.notify_save(
                str(kwargs.get("repo") or "."),
                list(kwargs.get("files") or kwargs.get("rel_paths") or []),
                run_shadow_test=bool(kwargs.get("run_shadow_test", True)),
                explicit_tests=kwargs.get("explicit_tests"),
                max_tests=int(kwargs.get("max_tests") or 2),
                timeout_s=float(kwargs.get("timeout_s") or 25.0),
                agent_id=str(kwargs.get("agent_id") or "precog"),
            )
        elif act == "watch_start":
            res = precog.start_watch(str(kwargs.get("repo") or "."), run_shadow_test=bool(kwargs.get("run_shadow_test", True)))
        elif act == "watch_stop":
            res = precog.stop_watch(kwargs.get("repo"))
        else:
            res = precog.status()
        res["via"] = "in_process_fallback"
        return res

    def agent_capsule(self, action: str = "load", **kwargs: Any) -> dict[str, Any]:
        payload = {"action": action, **kwargs}
        if self.available:
            try:
                return self._post_json("/v1/agent/capsule", payload, timeout=15.0)
            except Exception:
                pass
        from .agent_probe import get_default_agent_bus

        caps = get_default_agent_bus().symbiont.capsules
        act = str(action or "load").lower()
        if act == "create":
            res = caps.create(
                str(kwargs.get("repo") or "."),
                agent_id=str(kwargs.get("agent_id") or "agent"),
                summary=str(kwargs.get("summary") or ""),
                focus_files=kwargs.get("focus_files"),
                focus_symbols=kwargs.get("focus_symbols"),
                next_steps=kwargs.get("next_steps"),
                include_git=bool(kwargs.get("include_git", True)),
            )
        elif act == "list":
            res = caps.list_capsules(repo=kwargs.get("repo"), limit=int(kwargs.get("limit") or 10))
        else:
            res = caps.load(str(kwargs.get("capsule_id") or "latest"), repo=kwargs.get("repo"))
        res["via"] = "in_process_fallback"
        return res

    def agent_bootstrap(self, repo: str, *, agent_id: str = "agent") -> dict[str, Any]:
        if self.available:
            try:
                return self._post_json("/v1/agent/bootstrap", {"repo": repo, "agent_id": agent_id}, timeout=8.0)
            except Exception:
                pass
        from .agent_probe import get_default_agent_bus

        res = get_default_agent_bus().symbiont.bootstrap_snapshot(repo, agent_id=agent_id)
        res["via"] = "in_process_fallback"
        return res

    def mirror_race(
        self,
        repo: str,
        candidates: list[dict[str, Any]],
        *,
        explicit_tests: list[str] | None = None,
        commit_winner: bool = True,
        max_tests: int = 4,
        timeout_s: float = 45.0,
        agent_id: str = "agent",
        offload_peer: bool = False,
        peer_host: str = "svhome",
        peer_repo: str | None = None,
        generations: int = 1,
    ) -> dict[str, Any]:
        if offload_peer:
            # A peer on the preceding release still accepts unguarded mirror races.
            from .peer_guard import guarded_build_required

            return guarded_build_required()
        payload = {
            "repo": repo,
            "candidates": candidates,
            "explicit_tests": explicit_tests,
            "commit_winner": commit_winner,
            "max_tests": max_tests,
            "timeout_s": timeout_s,
            "agent_id": agent_id,
            "offload_peer": offload_peer,
            "peer_host": peer_host,
            "peer_repo": peer_repo,
            "generations": int(generations or 1),
        }
        if self.available:
            try:
                return self._post_json("/v1/agent/mirror-race", payload, timeout=max(30.0, float(timeout_s) + 15.0))
            except Exception:
                pass
        from .agent_probe import get_default_agent_bus

        res = get_default_agent_bus().symbiont.mirror_race.race(
            repo,
            candidates,
            explicit_tests=explicit_tests,
            commit_winner=commit_winner,
            max_tests=max_tests,
            timeout_s=timeout_s,
            agent_id=agent_id,
            offload_peer=offload_peer,
            peer_host=peer_host,
            peer_repo=peer_repo,
            generations=int(generations or 1),
        )
        res["via"] = "in_process_fallback"
        return res

    def agent_coroner(
        self,
        *,
        log_files: list[str] | None = None,
        auto_seed_immune: bool = False,
        max_files: int = 6,
    ) -> dict[str, Any]:
        payload = {"log_files": log_files, "auto_seed_immune": auto_seed_immune, "max_files": max_files}
        if self.available:
            try:
                return self._post_json("/v1/agent/coroner", payload, timeout=15.0)
            except Exception:
                pass
        from .agent_probe import get_default_agent_bus

        res = get_default_agent_bus().symbiont.coroner.scan(
            log_files=log_files,
            auto_seed_immune=auto_seed_immune,
            max_files=max_files,
        )
        res["via"] = "in_process_fallback"
        return res

    def hyperdesk_soft_shield(
        self,
        *,
        action: str = "apply",
        promote_vips: bool = True,
        demote_batch: bool = True,
        extra_batch_pids: list[int] | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        payload = {
            "action": action,
            "promote_vips": promote_vips,
            "demote_batch": demote_batch,
            "extra_batch_pids": extra_batch_pids,
            "dry_run": dry_run,
        }
        if self.available:
            try:
                return self._post_json("/v1/hyperdesk/soft-shield", payload, timeout=10.0)
            except Exception:
                pass
        from .hyper_desk import HyperDeskEngine

        hd = HyperDeskEngine()
        res = hd.restore_soft_batch_shield() if action == "restore" else hd.apply_soft_batch_shield(
            promote_vips=promote_vips,
            demote_batch=demote_batch,
            extra_batch_pids=extra_batch_pids,
            dry_run=dry_run,
        )
        res["via"] = "in_process_fallback"
        return res

    def agent_exec(
        self,
        argv: list[str],
        *,
        cwd: str = ".",
        stdin_text: str | None = None,
        normalize_lf: bool = True,
        env_overrides: dict[str, str] | None = None,
        timeout_s: float = 60.0,
        max_preview_chars: int = 2400,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "argv": list(argv),
            "cwd": cwd,
            "stdin_text": stdin_text,
            "normalize_lf": normalize_lf,
            "env_overrides": env_overrides,
            "timeout_s": timeout_s,
            "max_preview_chars": max_preview_chars,
        }
        if self.available:
            try:
                return self._post_json("/v1/agent/exec", payload, timeout=max(20.0, float(timeout_s) + 10.0))
            except Exception:
                pass
        from .agent_probe import get_default_agent_bus

        res = get_default_agent_bus().symbiont.direct_exec.run(
            argv,
            cwd=cwd,
            stdin_text=stdin_text,
            normalize_lf=normalize_lf,
            env_overrides=env_overrides,
            timeout_s=timeout_s,
            max_preview_chars=max_preview_chars,
        )
        res["via"] = "in_process_fallback"
        return res

    def agent_run_dag(
        self,
        steps: list[dict[str, Any]],
        *,
        cwd: str = ".",
        agent_id: str = "agent",
    ) -> dict[str, Any]:
        payload = {"steps": list(steps), "cwd": cwd, "agent_id": agent_id}
        if self.available:
            try:
                return self._post_json("/v1/agent/run-dag", payload, timeout=180.0)
            except Exception:
                pass
        from .agent_probe import get_default_agent_bus

        res = get_default_agent_bus().symbiont.macro_dag.run_dag(steps, cwd=cwd, agent_id=agent_id)
        res["via"] = "in_process_fallback"
        return res

    def agent_worktree_epoch(self, action: str = "epoch_status", **kwargs: Any) -> dict[str, Any]:
        payload = {"action": action, **kwargs}
        if self.available:
            try:
                return self._post_json("/v1/agent/worktree-epoch", payload, timeout=45.0)
            except Exception:
                pass
        from .agent_probe import get_default_agent_bus

        we = get_default_agent_bus().symbiont.worktree_epoch
        act = str(action or "epoch_status").strip().lower()
        if act == "create":
            res = we.create_worktree(
                str(kwargs.get("repo") or "."),
                agent_id=str(kwargs.get("agent_id") or "agent"),
                ref=str(kwargs.get("ref") or "HEAD"),
                name=kwargs.get("name"),
            )
        elif act == "list":
            res = we.list_worktrees(str(kwargs.get("repo") or "."))
        elif act == "remove":
            res = we.remove_worktree(str(kwargs.get("repo") or "."), str(kwargs.get("worktree_path") or ""), force=bool(kwargs.get("force", True)))
        elif act == "epoch_claim":
            res = we.epoch_claim(str(kwargs.get("release_dir") or kwargs.get("repo") or "."), agent_id=str(kwargs.get("agent_id") or "agent"), intent=str(kwargs.get("intent") or ""), ttl_s=float(kwargs.get("ttl_s") or 180.0))
        elif act == "epoch_publish":
            res = we.epoch_publish(str(kwargs.get("release_dir") or kwargs.get("repo") or "."), agent_id=str(kwargs.get("agent_id") or "agent"), files=list(kwargs.get("files") or []), sha256_map=kwargs.get("sha256_map"), verified_summary=str(kwargs.get("verified_summary") or ""), daemon_pid=int(kwargs.get("daemon_pid") or 0))
        else:
            res = we.epoch_status(kwargs.get("release_dir"))
        res["via"] = "in_process_fallback"
        return res

    def agent_release_promote(self, action: str = "status", **kwargs: Any) -> dict[str, Any]:
        payload = {"action": action, **kwargs}
        if self.available:
            try:
                return self._post_json("/v1/agent/release-promote", payload, timeout=45.0)
            except Exception:
                pass
        from .agent_probe import get_default_agent_bus

        rp = get_default_agent_bus().symbiont.release_promote
        act = str(action or "status").strip().lower()
        if act == "promote":
            res = rp.promote(
                str(kwargs.get("source_dir") or "."),
                str(kwargs.get("target_dir") or "."),
                list(kwargs.get("files") or []),
                agent_id=str(kwargs.get("agent_id") or "agent"),
                snapshot_root=kwargs.get("snapshot_root"),
                canary_imports=kwargs.get("canary_imports"),
                verified_summary=str(kwargs.get("verified_summary") or ""),
                dry_run=bool(kwargs.get("dry_run", False)),
            )
        elif act == "rollback":
            res = rp.rollback(
                epoch_id=kwargs.get("epoch_id"),
                rollback_dir=kwargs.get("rollback_dir"),
            )
        else:
            res = rp.status()
        res["via"] = "in_process_fallback"
        return res

    def agent_darwin(self, action: str = "status", **kwargs: Any) -> dict[str, Any]:
        payload = {"action": action, **kwargs}
        if self.available:
            try:
                if str(action or "status").strip().lower() == "status" and not kwargs:
                    return self._get_json("/v1/darwin/status", timeout=10.0)
                return self._post_json("/v1/darwin/evolve", payload, timeout=90.0)
            except Exception:
                pass
        from .agent_probe import get_default_agent_bus

        res = get_default_agent_bus().symbiont.darwin.dispatch(action, **kwargs)
        res["via"] = "in_process_fallback"
        return res

    def agent_aeon(self, action: str = "status", **kwargs: Any) -> dict[str, Any]:
        payload = {"action": action, **kwargs}
        if self.available:
            try:
                if str(action or "status").strip().lower() == "status" and not kwargs:
                    return self._get_json("/v1/aeon/status", timeout=10.0)
                return self._post_json("/v1/aeon/evolve", payload, timeout=60.0)
            except Exception:
                pass
        from .agent_probe import get_default_agent_bus

        res = get_default_agent_bus().symbiont.aeon.dispatch(action, **kwargs)
        res["via"] = "in_process_fallback"
        return res

    def agent_noosphere(self, action: str = "status", **kwargs: Any) -> dict[str, Any]:
        payload = {"action": action, **kwargs}
        if self.available:
            try:
                act_low = str(action or "status").strip().lower()
                if act_low == "status" and not kwargs:
                    return self._get_json("/v1/noosphere/status", timeout=10.0)
                if act_low == "epiphany" and not kwargs:
                    return self._get_json("/v1/noosphere/epiphany", timeout=10.0)
                return self._post_json("/v1/noosphere/dispatch", payload, timeout=60.0)
            except Exception:
                pass
        from .agent_probe import get_default_agent_bus

        res = get_default_agent_bus().symbiont.noosphere.dispatch(action, **kwargs)
        res["via"] = "in_process_fallback"
        return res

    def agent_eidolon(self, action: str = "status", **kwargs: Any) -> dict[str, Any]:
        payload = {"action": action, **kwargs}
        if self.available:
            try:
                act_low = str(action or "status").strip().lower()
                if act_low == "status" and not kwargs:
                    return self._get_json("/v1/eidolon/status", timeout=10.0)
                return self._post_json("/v1/eidolon/dispatch", payload, timeout=60.0)
            except Exception:
                pass
        from .agent_probe import get_default_agent_bus

        res = get_default_agent_bus().symbiont.eidolon.dispatch(action, **kwargs)
        res["via"] = "in_process_fallback"
        return res

    def agent_mnemosyne(self, action: str = "status", **kwargs: Any) -> dict[str, Any]:
        payload = {"action": action, **kwargs}
        if self.available:
            try:
                act_low = str(action or "status").strip().lower()
                if act_low == "status" and not kwargs:
                    return self._get_json("/v1/mnemosyne/status", timeout=10.0)
                if act_low == "entropy_audit" and not kwargs:
                    return self._get_json("/v1/mnemosyne/entropy-audit", timeout=10.0)
                if act_low == "swarm_watchdog" and not kwargs:
                    return self._get_json("/v1/mnemosyne/watchdog", timeout=10.0)
                return self._post_json("/v1/mnemosyne/dispatch", payload, timeout=60.0)
            except Exception:
                pass
        from .agent_probe import get_default_agent_bus

        res = get_default_agent_bus().symbiont.mnemosyne.dispatch(action, **kwargs)
        res["via"] = "in_process_fallback"
        return res

    # --- CHIMERA-BIOS Open Ecosystem Soul SDK (100% graceful offline fallback) ---
    @staticmethod
    def _bios_fallback_call(fn_name: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
        try:
            from .bios.organism import get_default_bios

            bios = get_default_bios()
            out = getattr(bios, fn_name)(*args, **kwargs)
            if isinstance(out, dict):
                res = dict(out)
                res.setdefault("ok", True)
                res["via"] = "in_process_fallback"
                res["offline_fallback"] = True
                return res
            return {"ok": True, "result": out, "via": "in_process_fallback", "offline_fallback": True}
        except Exception as exc:
            return {"ok": False, "via": "local_fallback", "offline_fallback": True, "error": str(exc)}

    def bios_status(self) -> dict[str, Any]:
        if self.available:
            try:
                return self._get_json("/v1/bios/status", timeout=10.0)
            except Exception:
                pass
        return self._bios_fallback_call("status")

    def bios_abi(self) -> dict[str, Any]:
        if self.available:
            try:
                return self._get_json("/v1/bios/abi", timeout=5.0)
            except Exception:
                pass
        return self._bios_fallback_call("open_abi_manifest", anchor_url=self.anchor_url)

    def bios_hormones(
        self,
        secrete: dict[str, Any] | None = None,
        *,
        action: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = dict(kwargs)
        if isinstance(secrete, dict) and secrete:
            payload["secrete"] = dict(secrete)
        if action:
            payload["action"] = str(action)
        if self.available:
            try:
                if not payload:
                    return self._get_json("/v1/bios/hormones", timeout=5.0)
                return self._post_json("/v1/bios/hormones", payload, timeout=5.0)
            except Exception:
                pass
        return self._bios_fallback_call(
            "hormones",
            secrete=secrete,
            action=action,
            payload=payload or None,
        )

    def bios_pulse(
        self,
        obs: dict[str, Any] | None = None,
        context: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if obs is not None:
            body["obs"] = dict(obs)
        if context is not None:
            body["context"] = str(context)
        if self.available:
            try:
                return self._post_json("/v1/bios/pulse", body, timeout=10.0)
            except Exception:
                pass
        return self._bios_fallback_call("pulse", obs=obs, context=context)

    def bios_predict(
        self,
        obs: dict[str, Any] | None,
        context: str = "general",
        horizon_s: float = 60.0,
        *,
        action: str = "all",
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "obs": dict(obs) if isinstance(obs, dict) else {},
            "context": str(context or "general"),
            "horizon_s": float(horizon_s or 60.0),
            "action": str(action or "all"),
        }
        if self.available:
            try:
                return self._post_json("/v1/bios/predict", body, timeout=10.0)
            except Exception:
                pass
        return self._bios_fallback_call(
            "predict",
            obs=body["obs"],
            context=body["context"],
            horizon_s=body["horizon_s"],
            action=body["action"],
        )

    def bios_pheromone(
        self,
        repo: str,
        rel_path: str,
        alarm: dict[str, Any] | None = None,
        coedits: list[str] | None = None,
        *,
        action: str | None = None,
        methylation: dict[str, Any] | None = None,
        max_tokens: int = 40,
    ) -> dict[str, Any]:
        has_mut = bool(alarm or coedits or methylation or (action and action not in ("smell", "status")))
        if self.available:
            try:
                if not has_mut and not action:
                    qs = urllib.parse.urlencode(
                        {"repo": str(repo or "."), "rel_path": str(rel_path or ""), "max_tokens": int(max_tokens or 40)}
                    )
                    return self._get_json(f"/v1/bios/pheromone?{qs}", timeout=5.0)
                body: dict[str, Any] = {
                    "repo": str(repo or "."),
                    "rel_path": str(rel_path or ""),
                    "max_tokens": int(max_tokens or 40),
                }
                if action:
                    body["action"] = str(action)
                if alarm is not None:
                    body["alarm"] = dict(alarm)
                if coedits is not None:
                    body["coedits"] = list(coedits)
                if methylation is not None:
                    body["methylation"] = dict(methylation)
                return self._post_json("/v1/bios/pheromone", body, timeout=8.0)
            except Exception:
                pass
        return self._bios_fallback_call(
            "pheromone",
            repo=str(repo or "."),
            rel_path=str(rel_path or ""),
            action=action,
            alarm=alarm,
            coedits=coedits,
            methylation=methylation,
            max_tokens=int(max_tokens or 40),
        )

    def bios_umwelt(
        self,
        signal: dict[str, Any] | None = None,
        *,
        action: str = "assess",
        lead_minutes: float = 5.0,
    ) -> dict[str, Any]:
        if self.available:
            try:
                if signal is None and action in ("status", "assess"):
                    return self._get_json("/v1/bios/umwelt", timeout=5.0)
                body: dict[str, Any] = {"action": str(action or "assess"), "lead_minutes": float(lead_minutes or 5.0)}
                if isinstance(signal, dict):
                    body["signal"] = dict(signal)
                return self._post_json("/v1/bios/umwelt", body, timeout=8.0)
            except Exception:
                pass
        return self._bios_fallback_call(
            "umwelt_dispatch",
            signal=signal,
            action=action,
            lead_minutes=lead_minutes,
        )

    def bios_soul(
        self,
        query: str = "",
        target_model: str = "any",
        max_tokens: int = 500,
        *,
        scar: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if self.available:
            try:
                if isinstance(scar, dict) and scar:
                    return self._post_json("/v1/bios/soul/scar", dict(scar), timeout=8.0)
                qs = urllib.parse.urlencode(
                    {
                        "query": str(query or ""),
                        "target_model": str(target_model or "any"),
                        "max_tokens": int(max_tokens or 500),
                    }
                )
                return self._get_json(f"/v1/bios/soul?{qs}", timeout=8.0)
            except Exception:
                pass
        if isinstance(scar, dict) and scar:
            return self._bios_fallback_call("soul_record_scar", scar)
        return self._bios_fallback_call(
            "soul_capsule",
            query=str(query or ""),
            target_model=str(target_model or "any"),
            max_tokens=int(max_tokens or 500),
        )

    def bios_autophagy(
        self,
        action: str = "status",
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        act = str(action or "status").strip().lower()
        body = {"action": act, **(dict(payload or {}))}
        if self.available:
            try:
                if act == "status" and not payload:
                    return self._get_json("/v1/bios/autophagy", timeout=10.0)
                return self._post_json("/v1/bios/autophagy", body, timeout=30.0)
            except Exception:
                pass
        return self._bios_fallback_call("autophagy_dispatch", action=act, payload=body)

    def bios_parasite(
        self,
        rounds: int = 4,
        *,
        action: str = "run",
        seed: int | None = None,
        scenarios: list[str] | None = None,
    ) -> dict[str, Any]:
        act = str(action or "run").strip().lower()
        if self.available:
            try:
                if act == "status":
                    return self._get_json("/v1/bios/parasite/status", timeout=10.0)
                body: dict[str, Any] = {"rounds": int(rounds or 4)}
                if seed is not None:
                    body["seed"] = int(seed)
                if scenarios is not None:
                    body["scenarios"] = list(scenarios)
                return self._post_json("/v1/bios/parasite/run", body, timeout=20.0)
            except Exception:
                pass
        if act == "status":
            return self._bios_fallback_call("parasite_status")
        return self._bios_fallback_call("parasite_run", rounds=int(rounds or 4), seed=seed, scenarios=scenarios)

    def bios_hgt(
        self,
        action: str = "list",
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        act = str(action or "list").strip().lower()
        body = {"action": act, **(dict(payload or {}))}
        if self.available:
            try:
                if act == "list" and not payload:
                    return self._get_json("/v1/bios/hgt", timeout=10.0)
                return self._post_json("/v1/bios/hgt", body, timeout=20.0)
            except Exception:
                pass
        return self._bios_fallback_call("hgt_dispatch", action=act, payload=body)

    def bios_spore(
        self,
        action: str = "list",
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        act = str(action or "list").strip().lower()
        p = dict(payload or {})
        if self.available:
            try:
                if act in ("list", "status"):
                    return self._get_json("/v1/bios/spores", timeout=8.0)
                if act == "pwa":
                    req = urllib.request.Request(f"{self.anchor_url}/v1/bios/spore", headers=self._headers())
                    with urllib.request.urlopen(req, timeout=self.timeout_s) as r:
                        html = r.read().decode("utf-8", errors="replace")
                    return {"ok": True, "html": html, "bytes": len(html.encode("utf-8"))}
                if act == "attach":
                    return self._post_json("/v1/bios/spore/attach", p, timeout=8.0)
                if act == "autotomy":
                    return self._post_json("/v1/bios/spore/autotomy", p, timeout=8.0)
                if act == "seed":
                    return self._post_json("/v1/bios/spore/seed", p, timeout=8.0)
            except Exception:
                pass
        if act == "attach":
            return self._bios_fallback_call("spore_attach", p)
        if act == "autotomy":
            return self._bios_fallback_call(
                "spore_autotomy",
                str(p.get("spore_id") or ""),
                reason=str(p.get("reason") or "detach"),
            )
        if act == "seed":
            return self._bios_fallback_call("spore_seed", p)
        if act == "pwa":
            res = self._bios_fallback_call("spore_pwa_html", anchor_url="")
            if isinstance(res.get("result"), str):
                html = res["result"]
                return {
                    "ok": True,
                    "html": html,
                    "bytes": len(html.encode("utf-8")),
                    "via": "in_process_fallback",
                    "offline_fallback": True,
                }
            return res
        return self._bios_fallback_call("spores_list")

    def bios_ganglia(
        self,
        action: str = "status",
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        act = str(action or "status").strip().lower()
        p = dict(payload or {})
        if self.available:
            try:
                if act == "reconcile":
                    return self._post_json("/v1/bios/ganglia/reconcile", p, timeout=10.0)
                return self._get_json("/v1/bios/ganglia", timeout=8.0)
            except Exception:
                pass
        if act == "reconcile":
            return self._bios_fallback_call(
                "ganglia_reconcile",
                local_events=p.get("local_events"),
                peer_events=p.get("peer_events"),
            )
        return self._bios_fallback_call("ganglia_status")

    def bios_sync(
        self,
        peer_url: str | None = None,
        blend: float = 0.35,
        *,
        timeout_s: float = 4.0,
    ) -> dict[str, Any]:
        """Trigger 2-way bidirectional CHIMERA-BIOS cross-host sync with clean offline fallback."""
        body: dict[str, Any] = {
            "blend": float(blend),
            "direction": "bidirectional",
            "timeout_s": float(timeout_s),
        }
        if peer_url:
            body["peer_url"] = str(peer_url).strip()
        if self.available:
            try:
                return self._post_json(
                    "/v1/bios/sync",
                    body,
                    timeout=max(self.timeout_s, float(timeout_s) + 4.0),
                )
            except urllib.error.HTTPError as exc:
                with exc:
                    try:
                        parsed = json.load(exc)
                        if isinstance(parsed, dict):
                            return parsed
                    except Exception:
                        pass
            except Exception:
                pass
        if peer_url:
            return self._bios_fallback_call(
                "sync_with_peer",
                str(peer_url).strip(),
                blend=float(blend),
                timeout_s=float(timeout_s),
            )
        bundle = self._bios_fallback_call("export_sync_bundle")
        return {
            "ok": bool(bundle.get("ok", True)),
            "via": "in_process_fallback",
            "offline_fallback": True,
            "direction": "local_bundle_only",
            "node_name": bundle.get("node_name"),
            "local_merkle_root": bundle.get("merkle_root"),
            "peer_merkle_root": None,
            "merkle_converged": False,
            "endocrine_wire_bytes": 12,
            "bundle": bundle,
            "auto_activated": False,
        }


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
