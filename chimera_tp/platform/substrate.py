"""PlatformSubstrate: Unified CHIMERA-CONNECT + 4 Core Gateways attached cleanly to ChimeraDaemon."""

from __future__ import annotations

import json
import os
import platform
import time
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Any

from ..autopilot import get_zero_weight_status
from .autoload import autoload_status
from .discovery import (
    AppRegistry,
    PassivePortScanner,
    _atomic_write_text,
    chimera_home_dir,
    generate_boot_token,
    runtime_beacon_paths,
    write_agents_infra_doc,
)
from .egress_membrane import EgressMembraneProxy
from .flight_recorder import DisklessSecretVault, FlightRecorderBlackBox
from .hybrid_search import HybridPlatformSearch
from .immortal_jobs import ImmortalJobEngine
from .pulse_bus import PulseBus
from .browser_grid import SharedBrowserGrid
from .vault_sql import VaultSqlFabric
from .vgpu_gateway import VgpuParetoGateway
from .zygote_canary import CanaryTwinJudge, ZygoteWorkerPool


class PlatformSubstrate:
    """Single clean facade exposing /.well-known/chimera.json + /v1/* + :9781 Egress-Membrane."""

    def __init__(self, daemon: Any) -> None:
        self.daemon = daemon
        self.ephemeral = bool(getattr(daemon, "_ephemeral_mode", False))
        self.boot_token = generate_boot_token()
        self.started_at = datetime.now().astimezone().isoformat(timespec="seconds")

        reg_path = (
            Path(daemon.ops_dir) / "apps.json"
            if self.ephemeral
            else (chimera_home_dir() / "apps.json")
        )
        self.registry = AppRegistry(reg_path)
        self.port_scanner = PassivePortScanner(cache_ttl_s=10.0)
        self.egress = EgressMembraneProxy(
            listen_host="127.0.0.1",
            listen_port=0 if self.ephemeral else 9781,
            cassettes_dir=Path(daemon.ops_dir) / "cassettes",
            on_flow=daemon.record_flow,
        )
        self.pulse = PulseBus(
            node_name=daemon.config.node_name,
            peer_base_resolver=(
                daemon.active_edge_peer_base
                if (not self.ephemeral and daemon.config.peer_ipv4)
                else None
            ),
            fallback_peer_resolver=(
                daemon.peer_http_base
                if (not self.ephemeral and daemon.config.peer_ipv4)
                else None
            ),
            on_flow=daemon.record_flow,
        )
        self.search = HybridPlatformSearch(
            db_path=Path(daemon.ops_dir) / "platform_search.db",
            vsa_service=getattr(daemon, "vsa_memory", None),
        )
        self.secrets = DisklessSecretVault(boot_token=self.boot_token)
        self.blackbox = FlightRecorderBlackBox(
            out_dir=Path(daemon.ops_dir) / "blackbox",
            sample_fn=self._sample_frame,
            max_frames=240,
            interval_s=1.0,
        )
        self.vgpu = VgpuParetoGateway(
            node_name=daemon.config.node_name,
            role=daemon.config.role,
            host_governor=getattr(daemon, "host_governor", None),
            peer_base_resolver=(
                daemon.active_edge_peer_base
                if (not self.ephemeral and daemon.config.peer_ipv4)
                else None
            ),
            on_flow=daemon.record_flow,
        )
        self.jobs = ImmortalJobEngine(db_path=Path(daemon.ops_dir) / "immortal_jobs.db")
        self.browser = SharedBrowserGrid(cdp_port=0 if self.ephemeral else 9785, idle_shutdown_s=120.0)
        self.zygote = ZygoteWorkerPool()
        self.canary = CanaryTwinJudge()
        self.vault_sql = VaultSqlFabric(
            replica_dir=Path(daemon.ops_dir) / "vault_sql",
            peer_base_resolver=(
                daemon.active_edge_peer_base
                if (not self.ephemeral and daemon.config.peer_ipv4)
                else None
            ),
        )

        self._cart_cfg_path = Path(daemon.ops_dir) / "cartridges.json"
        self._cartridge_enabled: dict[str, bool] = {
            "connect": True,
            "egress_membrane": True,
            "pulse": True,
            "hybrid_search": True,
            "blackbox": True,
            "diskless_secrets": True,
            "vgpu_pareto": True,
            "immortal_jobs": True,
            "browser_grid": True,
            "zygote_canary": True,
            "vault_sql": True,
        }
        self._load_cartridge_config()
        self._beacon_paths: list[Path] = []

    def _load_cartridge_config(self) -> None:
        try:
            if self._cart_cfg_path.is_file():
                d = json.loads(self._cart_cfg_path.read_text(encoding="utf-8"))
                if isinstance(d, dict):
                    for k, v in d.items():
                        if k in self._cartridge_enabled and k != "connect":
                            self._cartridge_enabled[k] = bool(v)
        except Exception:
            pass

    def set_cartridge(self, name: str, enabled: bool) -> dict[str, Any]:
        if name not in self._cartridge_enabled:
            raise ValueError(f"Unknown cartridge: {name}")
        if name == "connect" and not enabled:
            raise ValueError("Core 'connect' cartridge cannot be disabled")
        self._cartridge_enabled[name] = bool(enabled)
        _atomic_write_text(self._cart_cfg_path, json.dumps(self._cartridge_enabled, indent=2))
        if name == "browser_grid" and not enabled:
            self.browser.close()
        self.write_beacons()
        return {"ok": True, "cartridge": name, "enabled": bool(enabled), "cartridges": dict(self._cartridge_enabled)}

    def _sample_frame(self) -> dict[str, Any]:
        zw = get_zero_weight_status()
        eg = self.egress.stats()
        return {
            "ram_mb": zw.get("daemon_ram_mb", 0.0),
            "apps_online": sum(1 for a in self.registry.list_apps() if a.get("online")),
            "egress_reqs": eg.get("requests_total", 0),
            "egress_hit_pct": eg.get("hit_rate_pct", 0.0),
            "pulse_seq": self.pulse.stats().get("latest_seq", 0),
        }

    def start(self) -> "PlatformSubstrate":
        self.egress.start()
        if not self.ephemeral:
            self.blackbox.start()
        else:
            self.blackbox.record_once()
        self.write_beacons()
        return self

    def close(self) -> None:
        self.blackbox.close()
        self.egress.close()
        self.search.close()
        self.jobs.close()
        self.browser.close()
        self.zygote.close()

    @property
    def anchor_url(self) -> str:
        host, port = self.daemon.http_addr
        connect_host = "127.0.0.1" if host in ("0.0.0.0", "::", "") else host
        return f"http://{connect_host}:{port}"

    def capabilities(self) -> dict[str, Any]:
        anchor = self.anchor_url
        eg_stats = self.egress.stats()
        apps = self.registry.list_apps()
        return {
            "ok": True,
            "schema": "chimera.capabilities.v1",
            "version": "17.0.0",
            "node_name": self.daemon.config.node_name,
            "role": self.daemon.config.role,
            "os": platform.system().lower(),
            "pid": os.getpid(),
            "started_at": self.started_at,
            "anchor_url": anchor,
            "egress_proxy_url": self.egress.url,
            "egress_proxy_port": self.egress.addr[1],
            "peer_name": self.daemon.config.peer_name or "",
            "peer_ipv4": self.daemon.config.peer_ipv4 or "",
            "autoload": autoload_status(),
            "zero_weight": get_zero_weight_status(),
            "apps_summary": {
                "total": len(apps),
                "online": sum(1 for a in apps if a.get("online")),
                "linked": sum(1 for a in apps if a.get("linked")),
            },
            "cartridges": {
                "connect": {
                    "status": "active",
                    "endpoint": f"{anchor}/.well-known/chimera.json",
                    "description": "Single-Anchor discovery, app registry, autoload & MCP beacon",
                },
                "egress_membrane": {
                    "status": "active" if self._cartridge_enabled["egress_membrane"] else "disabled",
                    "endpoint": self.egress.url,
                    "hit_rate_pct": eg_stats.get("hit_rate_pct", 0.0),
                    "description": "Loopback HTTP/HTTPS proxy with Singleflight, TTL/ETag cache, 429 shield & Wire-Cassette",
                },
                "pulse": {
                    "status": "active" if self._cartridge_enabled["pulse"] else "disabled",
                    "endpoint": f"{anchor}/v1/pulse",
                    "description": "Zero-Redis cross-host Pub/Sub event bus & TTL Shared KV",
                },
                "hybrid_search": {
                    "status": "active" if self._cartridge_enabled["hybrid_search"] else "disabled",
                    "endpoint": f"{anchor}/v1/search",
                    "description": "Namespaced hybrid SQLite FTS5 BM25 + 10,000-bit AVX2 Kanerva VSA search",
                },
                "blackbox": {
                    "status": "active" if self._cartridge_enabled["blackbox"] else "disabled",
                    "endpoint": f"{anchor}/v1/blackbox/freeze",
                    "description": "Zero-disk-write RAM ring-buffer Flight Recorder (60s pre-crash freeze)",
                },
                "diskless_secrets": {
                    "status": "active" if self._cartridge_enabled["diskless_secrets"] else "disabled",
                    "endpoint": f"{anchor}/v1/secrets/get",
                    "description": "In-RAM XOR-masked ephemeral secret vault (0 plaintext bytes on disk)",
                },
                "vgpu_pareto": {
                    "status": "active" if self._cartridge_enabled["vgpu_pareto"] else "disabled",
                    "endpoint": f"{anchor}/v1/openai/v1/embeddings",
                    "gpu_ready": self.vgpu.status().get("gpu_ready", False),
                    "description": "NVIDIA GTX 1650 sharing with HostYieldGovernor auto-yield, Pareto router & OpenAI-compat embeddings",
                },
                "immortal_jobs": {
                    "status": "active" if self._cartridge_enabled["immortal_jobs"] else "disabled",
                    "endpoint": f"{anchor}/v1/jobs/create",
                    "description": "SQLite WAL durable workflow step journal (crash/reboot idempotent resume)",
                },
                "browser_grid": {
                    "status": "active" if self._cartridge_enabled["browser_grid"] else "disabled",
                    "endpoint": f"{anchor}/v1/browser/session",
                    "binary_found": self.browser.status().get("binary_found", False),
                    "description": "Zero-RAM lazy shared Chromium CDP multiplexer with zero-media blocking & idle auto-reap",
                },
                "zygote_canary": {
                    "status": "active" if self._cartridge_enabled["zygote_canary"] else "disabled",
                    "endpoint": f"{anchor}/v1/zygote/exec",
                    "mode": self.zygote.status().get("mode", "warm_pool"),
                    "description": "Single-threaded Linux pre-fork CoW / Windows warm worker pool + Canary Twin judge",
                },
                "vault_sql": {
                    "status": "active" if self._cartridge_enabled["vault_sql"] else "disabled",
                    "endpoint": f"{anchor}/v1/vault-sql/query",
                    "description": "Single-writer WAL-safe SQLite cross-node replica fabric (<0.3ms local reads)",
                },
            },
        }

    def write_beacons(self) -> list[str]:
        caps = self.capabilities()
        beacon = {
            **caps,
            "boot_token": self.boot_token,
            "written_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        raw = json.dumps(beacon, indent=2, ensure_ascii=False)
        written: list[str] = []
        self._beacon_paths = runtime_beacon_paths(Path(self.daemon.ops_dir), ephemeral=self.ephemeral)
        for p in self._beacon_paths:
            if _atomic_write_text(p, raw):
                written.append(str(p))
        if not self.ephemeral:
            write_agents_infra_doc(caps)
        return written

    def pulse_summary(self) -> dict[str, Any]:
        apps = self.registry.list_apps()
        eg = self.egress.stats()
        return {
            "version": "17.0.0",
            "anchor_url": self.anchor_url,
            "egress_proxy_url": self.egress.url,
            "apps_online": [a["app"] for a in apps if a.get("online")],
            "apps_linked": [a["app"] for a in apps if a.get("linked")],
            "apps_total": len(apps),
            "egress_requests": eg.get("requests_total", 0),
            "egress_hit_pct": eg.get("hit_rate_pct", 0.0),
            "egress_bytes_saved": eg.get("bytes_saved", 0),
            "pulse_seq": self.pulse.stats().get("latest_seq", 0),
            "search_docs": self.search.stats().get("docs", 0),
            "blackbox_frames": self.blackbox.stats().get("buffered_frames", 0),
            "vgpu_ready": self.vgpu.status().get("gpu_ready", False),
            "immortal_jobs": self.jobs.stats().get("total_jobs", 0),
            "browser_sessions": self.browser.status().get("active_sessions", 0),
            "zygote_execs": self.zygote.status().get("executions", 0),
        }

    def handle_get(self, parsed: urllib.parse.ParseResult, headers: Any) -> tuple[int, dict[str, Any]] | None:
        path = parsed.path
        qs = urllib.parse.parse_qs(parsed.query)

        if path in ("/.well-known/chimera.json", "/v1/discover", "/v1/capabilities"):
            return 200, self.capabilities()

        if path == "/v1/smi":
            caps = self.capabilities()
            apps = self.registry.list_apps()
            known_ports = {int(self.daemon.http_addr[1]), int(self.egress.addr[1])}
            known_ports |= {int(a.get("port") or 0) for a in apps if int(a.get("port") or 0) > 0}
            unlinked = self.port_scanner.scan(exclude_ports=known_ports)[:12]
            return 200, {
                "ok": True,
                "capabilities": caps,
                "apps": apps,
                "unlinked_ports": unlinked,
                "egress": self.egress.stats(),
                "pulse": self.pulse.stats(),
                "search": self.search.stats(),
                "blackbox": self.blackbox.stats(),
                "secrets": self.secrets.stats(),
                "cassettes": self.egress.list_cassettes(limit=10),
                "vgpu": self.vgpu.status(),
                "jobs": self.jobs.stats(),
                "browser": self.browser.status(),
                "zygote": self.zygote.status(),
                "canary": self.canary.stats(),
                "vault_sql": self.vault_sql.status(),
                "cartridge_toggles": dict(self._cartridge_enabled),
            }

        if path == "/v1/apps/list":
            apps = self.registry.list_apps()
            known_ports = {int(self.daemon.http_addr[1]), int(self.egress.addr[1])}
            known_ports |= {int(a.get("port") or 0) for a in apps if int(a.get("port") or 0) > 0}
            return 200, {
                "ok": True,
                "apps": apps,
                "unlinked_ports": self.port_scanner.scan(exclude_ports=known_ports)[:16],
            }

        if path == "/v1/egress/stats":
            return 200, {"ok": True, "egress": self.egress.stats()}

        if path == "/v1/cassettes":
            cid = (qs.get("id") or [""])[0]
            if cid:
                item = self.egress.get_cassette(cid)
                if item is None:
                    return 404, {"error": "cassette_not_found"}
                return 200, {"ok": True, "cassette": item}
            return 200, {"ok": True, "cassettes": self.egress.list_cassettes(limit=25)}

        if path == "/v1/pulse/events":
            topic = (qs.get("topic") or ["*"])[0]
            since = int((qs.get("since") or ["0"])[0] or 0)
            limit = int((qs.get("limit") or ["50"])[0] or 50)
            wait_ms = int((qs.get("wait_ms") or ["0"])[0] or 0)
            return 200, self.pulse.poll(topic=topic, since=since, limit=limit, wait_ms=wait_ms)

        if path == "/v1/pulse/kv":
            key = (qs.get("key") or [""])[0]
            if not key:
                return 400, {"error": "missing_key"}
            return 200, self.pulse.kv_get(key)

        if path == "/v1/pulse/stats":
            return 200, {"ok": True, "pulse": self.pulse.stats()}

        if path == "/v1/search":
            q = (qs.get("q") or [""])[0]
            ns = (qs.get("namespace") or ["global"])[0]
            top_k = int((qs.get("top_k") or ["10"])[0] or 10)
            return 200, self.search.search(query=q, namespace=ns, top_k=top_k)

        if path == "/v1/search/stats":
            return 200, {"ok": True, "search": self.search.stats()}

        if path == "/v1/blackbox/status":
            return 200, {
                "ok": True,
                "blackbox": self.blackbox.stats(),
                "freezes": self.blackbox.list_freezes(limit=10),
            }

        if path == "/v1/cartridges":
            return 200, {"ok": True, "cartridges": dict(self._cartridge_enabled)}

        if path == "/v1/vgpu/status":
            return 200, self.vgpu.status()

        if path == "/v1/jobs/list":
            app = (qs.get("app") or [""])[0] or None
            lim = int((qs.get("limit") or ["30"])[0] or 30)
            return 200, {"ok": True, "jobs": self.jobs.list_jobs(app=app, limit=lim), "stats": self.jobs.stats()}

        if path == "/v1/jobs/resume":
            jid = (qs.get("job_id") or [""])[0]
            if not jid:
                return 400, {"error": "missing_job_id"}
            res = self.jobs.resume_job(jid)
            if res is None:
                return 404, {"error": "job_not_found"}
            return 200, res

        if path == "/v1/browser/status":
            return 200, self.browser.status()

        if path == "/v1/zygote/status":
            return 200, self.zygote.status()

        if path == "/v1/vault-sql/status":
            return 200, self.vault_sql.status()

        if path == "/v1/vault-sql/snapshot":
            name = (qs.get("name") or [""])[0]
            since_sha = (qs.get("since_sha256") or [""])[0]
            try:
                return 200, self.vault_sql.export_snapshot(name=name, since_sha256=since_sha)
            except Exception as exc:
                return 404, {"error": str(exc)}

        if path == "/v1/dns/hosts-hint":
            apps = self.registry.list_apps()
            domains = sorted({a["domain"] for a in apps if a.get("domain")})
            hosts_line = ("127.0.0.1 " + " ".join(domains)) if domains else ""
            return 200, {
                "ok": True,
                "anchor_port": int(self.daemon.http_addr[1]),
                "domains": domains,
                "hosts_line": hosts_line,
                "usage_hint": "curl -H 'Host: radar.chimera.local' http://127.0.0.1:9780/api/health",
            }

        return None

    def handle_post(
        self,
        parsed: urllib.parse.ParseResult,
        raw_body: bytes,
        headers: Any,
        client_ip: str = "127.0.0.1",
    ) -> tuple[int, dict[str, Any]] | None:
        path = parsed.path
        if not path.startswith("/v1/"):
            return None
        try:
            body = json.loads(raw_body.decode("utf-8") or "{}")
            if not isinstance(body, dict):
                return 400, {"error": "json_object_required"}
        except Exception:
            return 400, {"error": "invalid_json"}

        if path == "/v1/apps/register":
            entry = self.registry.register_live(body)
            self.daemon.record_flow(
                "control",
                entry["app"],
                self.daemon.config.node_name,
                "APP_ATTACH",
                wire_bytes=len(raw_body),
                elapsed_ms=0.1,
                detail=f"mode={entry['attach_mode']} pid={entry['pid']} qos={entry['qos']}",
                ok=True,
            )
            return 200, {
                "ok": True,
                "entry": entry,
                "anchor_url": self.anchor_url,
                "egress_proxy_url": self.egress.url,
            }

        if path == "/v1/apps/unlink":
            removed = self.registry.unlink_entry(str(body.get("app") or ""))
            return 200, {"ok": True, "removed": removed}

        if path == "/v1/pulse/publish":
            ev = self.pulse.publish(
                topic=str(body.get("topic") or "default"),
                payload=body.get("payload"),
                app=str(body.get("app") or headers.get("X-Chimera-App") or "system"),
                relay=bool(body.get("relay", True)),
                origin_node=body.get("origin_node"),
            )
            return 200, {"ok": True, "event": ev}

        if path == "/v1/pulse/kv":
            key = str(body.get("key") or "").strip()
            if not key:
                return 400, {"error": "missing_key"}
            res = self.pulse.kv_set(
                key=key,
                value=body.get("value"),
                ttl_s=float(body.get("ttl_s") or 0.0),
                app=str(body.get("app") or headers.get("X-Chimera-App") or "system"),
            )
            return 200, res

        if path == "/v1/search/index":
            ns = str(body.get("namespace") or "global")
            did = str(body.get("doc_id") or "")
            txt = str(body.get("text") or "")
            if not did:
                return 400, {"error": "missing_doc_id"}
            return 200, self.search.index_doc(ns, did, txt, meta=body.get("meta") or {})

        if path == "/v1/search":
            return 200, self.search.search(
                query=str(body.get("q") or body.get("query") or ""),
                namespace=str(body.get("namespace") or "global"),
                top_k=int(body.get("top_k") or 10),
            )

        if path == "/v1/blackbox/freeze":
            res = self.blackbox.freeze(
                reason=str(body.get("reason") or "manual_api"),
                app=str(body.get("app") or headers.get("X-Chimera-App") or "system"),
                window_frames=int(body.get("window_frames") or 120),
            )
            return 200, res

        if path in ("/v1/secrets/set", "/v1/secrets/get"):
            if client_ip not in ("127.0.0.1", "::1", "localhost"):
                return 403, {"error": "loopback_only"}
            tok = headers.get("X-Chimera-Token") or body.get("token")
            if not self.secrets.authorize(tok):
                return 401, {"error": "invalid_boot_token"}
            if path == "/v1/secrets/set":
                try:
                    return 200, self.secrets.set_secret(
                        name=str(body.get("name") or ""),
                        value=str(body.get("value") or ""),
                        allowed_apps=body.get("allowed_apps"),
                    )
                except ValueError as exc:
                    return 400, {"error": str(exc)}
            res = self.secrets.get_secret(
                name=str(body.get("name") or ""),
                app=str(body.get("app") or headers.get("X-Chimera-App") or ""),
            )
            return (200 if res.get("ok") else 403), res

        if path == "/v1/cartridges":
            try:
                return 200, self.set_cartridge(str(body.get("name") or ""), bool(body.get("enabled", True)))
            except ValueError as exc:
                return 400, {"error": str(exc)}

        if path == "/v1/vgpu/route":
            if not self._cartridge_enabled.get("vgpu_pareto", True):
                return 503, {"error": "cartridge_disabled:vgpu_pareto"}
            return 200, self.vgpu.pareto_route(
                max_ms=float(body.get("max_ms") or 500.0),
                max_cost_usd=float(body.get("max_cost_usd") or 0.0),
                min_tier=str(body.get("min_tier") or "standard"),
                payload_bytes=int(body.get("payload_bytes") or 1024),
            )

        if path in ("/v1/vgpu/embed", "/v1/openai/v1/embeddings"):
            if not self._cartridge_enabled.get("vgpu_pareto", True):
                return 503, {"error": "cartridge_disabled:vgpu_pareto"}
            inp = body.get("input", body.get("texts", ""))
            return 200, self.vgpu.embed_openai_compat(
                inputs=inp,
                model=str(body.get("model") or "chimera-vsa-embed-256"),
                dim=int(body.get("dimensions") or body.get("dim") or 256),
                app=str(body.get("app") or headers.get("X-Chimera-App") or "external"),
                allow_peer_offload=bool(body.get("allow_peer_offload", True)),
            )

        if path == "/v1/jobs/create":
            if not self._cartridge_enabled.get("immortal_jobs", True):
                return 503, {"error": "cartridge_disabled:immortal_jobs"}
            return 200, self.jobs.create_job(
                job_id=body.get("job_id"),
                app=str(body.get("app") or headers.get("X-Chimera-App") or "system"),
                name=str(body.get("name") or "workflow"),
                total_steps=int(body.get("total_steps") or 1),
                meta=body.get("meta") or {},
            )

        if path == "/v1/jobs/step":
            if not self._cartridge_enabled.get("immortal_jobs", True):
                return 503, {"error": "cartridge_disabled:immortal_jobs"}
            try:
                return 200, self.jobs.checkpoint_step(
                    job_id=str(body.get("job_id") or ""),
                    step_key=str(body.get("step_key") or ""),
                    step_index=int(body.get("step_index") or 0),
                    status=str(body.get("status") or "completed"),
                    result=body.get("result"),
                )
            except ValueError as exc:
                return 400, {"error": str(exc)}

        if path == "/v1/browser/session":
            if not self._cartridge_enabled.get("browser_grid", True):
                return 503, {"error": "cartridge_disabled:browser_grid"}
            try:
                return 200, self.browser.acquire_session(
                    app=str(body.get("app") or headers.get("X-Chimera-App") or "external"),
                    zero_media=bool(body.get("zero_media", True)),
                    ttl_s=float(body.get("ttl_s") or 120.0),
                )
            except Exception as exc:
                return 503, {"error": str(exc)}

        if path == "/v1/browser/close":
            return 200, self.browser.release_session(
                session_id=str(body.get("session_id") or ""),
                shutdown_if_empty=bool(body.get("shutdown_if_empty", False)),
            )

        if path == "/v1/zygote/exec":
            if not self._cartridge_enabled.get("zygote_canary", True):
                return 503, {"error": "cartridge_disabled:zygote_canary"}
            try:
                return 200, self.zygote.execute(
                    kernel=str(body.get("kernel") or ""),
                    payload=body.get("payload") or {},
                    prefer_fork=bool(body.get("prefer_fork", True)),
                )
            except Exception as exc:
                return 400, {"error": str(exc)}

        if path == "/v1/canary/compare":
            if not self._cartridge_enabled.get("zygote_canary", True):
                return 503, {"error": "cartridge_disabled:zygote_canary"}
            b_url = str(body.get("baseline_url") or "")
            c_url = str(body.get("canary_url") or "")
            if not b_url or not c_url:
                return 400, {"error": "baseline_url_and_canary_url_required"}
            return 200, self.canary.compare(
                baseline_url=b_url,
                canary_url=c_url,
                paths=body.get("paths"),
                samples=int(body.get("samples") or 5),
                max_p95_regression_ratio=float(body.get("max_p95_regression_ratio") or 1.5),
                ignore_keys=body.get("ignore_keys"),
            )

        if path == "/v1/vault-sql/register":
            try:
                return 200, self.vault_sql.register_db(
                    name=str(body.get("name") or ""),
                    path=str(body.get("path") or ""),
                    role=str(body.get("role") or "primary"),
                )
            except Exception as exc:
                return 400, {"error": str(exc)}

        if path == "/v1/vault-sql/sync":
            try:
                if body.get("snapshot"):
                    return 200, self.vault_sql.install_replica_snapshot(str(body.get("name") or ""), body["snapshot"])
                return 200, self.vault_sql.sync_from_peer(
                    name=str(body.get("name") or ""),
                    peer_base=body.get("peer_base"),
                )
            except Exception as exc:
                return 502, {"error": str(exc)}

        if path == "/v1/vault-sql/query":
            try:
                return 200, self.vault_sql.query_readonly(
                    name=str(body.get("name") or ""),
                    sql=str(body.get("sql") or ""),
                    params=body.get("params"),
                    limit=int(body.get("limit") or 200),
                )
            except ValueError as exc:
                return 400, {"error": str(exc)}
            except Exception as exc:
                return 404, {"error": str(exc)}

        return None

    def handle_host_proxy(
        self,
        method: str,
        raw_path: str,
        headers: Any,
        raw_body: bytes = b"",
    ) -> tuple[int, str, bytes] | None:
        """Transparent *.chimera.local Host-header reverse proxy (local port first, then peer via PHANTOM)."""
        host_hdr = str(headers.get("Host") or "").strip().lower()
        hostname = host_hdr.split(":", 1)[0]
        if not hostname.endswith(".chimera.local"):
            return None
        app_sub = hostname[: -len(".chimera.local")].strip(".")
        if not app_sub:
            return None
        apps = self.registry.list_apps()
        target = next((a for a in apps if a.get("app") == app_sub or a.get("domain") == hostname), None)
        if target is None or int(target.get("port") or 0) <= 0:
            return 404, "application/json", json.dumps({"error": f"unknown_chimera_domain:{hostname}"}).encode("utf-8")

        port = int(target["port"])
        import urllib.error
        import urllib.request

        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        fwd_headers = {
            k: v
            for k, v in headers.items()
            if k.lower() not in ("host", "connection", "content-length", "transfer-encoding")
        }
        fwd_headers["X-Forwarded-Host"] = host_hdr

        # Try local 127.0.0.1:<port> first; if refused and peer exists, forward through peer :9780 with same Host!
        attempts: list[tuple[str, dict[str, str]]] = [(f"http://127.0.0.1:{port}{raw_path}", dict(fwd_headers))]
        if (not self.ephemeral) and self.daemon.config.peer_ipv4:
            try:
                pbase = self.daemon.active_edge_peer_base().rstrip("/")
                if pbase:
                    ph = dict(fwd_headers)
                    ph["Host"] = hostname
                    attempts.append((f"{pbase}{raw_path}", ph))
            except Exception:
                pass

        last_err = ""
        for url, hdrs in attempts:
            try:
                req = urllib.request.Request(
                    url,
                    data=raw_body if method in ("POST", "PUT", "PATCH") else None,
                    headers=hdrs,
                    method=method,
                )
                with opener.open(req, timeout=8.0) as r:
                    ct = r.headers.get("Content-Type", "application/octet-stream")
                    return r.status, ct, r.read()
            except urllib.error.HTTPError as e:
                ct = e.headers.get("Content-Type", "application/octet-stream") if e.headers else "application/json"
                return e.code, ct, e.read()
            except Exception as exc:
                last_err = str(exc)
        return 502, "application/json", json.dumps({"error": f"chimera_local_proxy_failed:{hostname}:{last_err}"}).encode("utf-8")


def render_smi(smi_data: dict[str, Any]) -> str:
    """Format nvidia-smi style terminal overview of the live CHIMERA Substrate."""
    caps = smi_data.get("capabilities") or {}
    zw = caps.get("zero_weight") or {}
    eg = smi_data.get("egress") or {}
    pl = smi_data.get("pulse") or {}
    sr = smi_data.get("search") or {}
    bb = smi_data.get("blackbox") or {}
    vg = smi_data.get("vgpu") or {}
    jb = smi_data.get("jobs") or {}
    br = smi_data.get("browser") or {}
    zg = smi_data.get("zygote") or {}
    cn = smi_data.get("canary") or {}
    vq = smi_data.get("vault_sql") or {}
    gpu = vg.get("gpu") or {}
    gpu_desc = (
        f"{gpu.get('name','GPU')[:22]} {gpu.get('util_pct',0)}% {gpu.get('temp_c',0)}C free={gpu.get('vram_free_mb',0)}MB"
        if gpu.get("present")
        else "CPU-AVX2 / peer-offload"
    )
    apps = smi_data.get("apps") or []
    unlinked = smi_data.get("unlinked_ports") or []

    lines = [
        "+" + "-" * 78 + "+",
        f"| CHIMERA-SMI v{caps.get('version', '17.0.0'):<8} | Node: {caps.get('node_name', '?'):<14} ({caps.get('role', '?'):<10}) | PID: {caps.get('pid', 0):<8} |",
        "+" + "-" * 78 + "+",
        f"| Anchor : {caps.get('anchor_url', ''):<34} | RAM : {zw.get('daemon_ram_mb', 0):>6.2f} / {zw.get('ram_budget_mb', 80):.0f} MB    |",
        f"| Proxy  : {caps.get('egress_proxy_url', ''):<34} | Peer: {caps.get('peer_name') or '(local)':<18} |",
        f"| Autold : {'INSTALLED' if (caps.get('autoload') or {}).get('installed') else 'OFF (run: chimera-tp autoload install)':<66} |",
        "+" + "-" * 78 + "+",
        "| CARTRIDGES                                                                   |",
        f"|  [ON] egress_membrane : req={eg.get('requests_total',0):<5} hit={eg.get('hit_rate_pct',0):>5.1f}% coal={eg.get('coalesced_hits',0):<4} saved={eg.get('bytes_saved',0):>8} B |",
        f"|  [ON] pulse_bus       : seq={pl.get('latest_seq',0):<5} buf={pl.get('buffered_events',0):<4} kv={pl.get('kv_entries',0):<4} relayed={pl.get('relayed_to_peer',0):<6} |",
        f"|  [ON] hybrid_search   : docs={sr.get('docs',0):<5} ns={sr.get('namespaces',0):<4} q={sr.get('queries',0):<5} avx2_vsa={str(sr.get('vsa_avx2_enabled')):<7} |",
        f"|  [ON] flight_recorder : frames={bb.get('buffered_frames',0):<4}/{bb.get('max_frames',0):<4} freezes={bb.get('freezes',0):<4} (0-disk-write ring)   |",
        f"|  [ON] vgpu_pareto     : ready={str(vg.get('gpu_ready',False)):<5} {gpu_desc:<43}|",
        f"|  [ON] immortal_jobs   : jobs={jb.get('total_jobs',0):<4} done={jb.get('completed_jobs',0):<4} steps={jb.get('completed_steps',0):<5} dup_skip={jb.get('duplicate_steps_skipped',0):<5}|",
        f"|  [ON] browser_grid    : bin={str(br.get('binary_found',False)):<5} running={str(br.get('running',False)):<5} sessions={br.get('active_sessions',0):<3} (0MB idle)  |",
        f"|  [ON] zygote_canary   : mode={zg.get('mode','?'):<17} execs={zg.get('executions',0):<4} canary_runs={cn.get('runs',0):<3} |",
        f"|  [ON] vault_sql       : dbs={vq.get('db_count',0):<4} syncs={vq.get('syncs',0):<4} queries={vq.get('queries',0):<5} saved={vq.get('bytes_saved',0):>7} B |",
        "+" + "-" * 78 + "+",
        f"| ATTACHED & LINKED APPS ({len(apps)})                                                   |",
    ]
    if not apps:
        lines.append("|  (none yet — run: chimera-tp link <project_dir> or chimera-tp run --app ...) |")
    else:
        for a in apps[:12]:
            st = "ONLINE" if a.get("online") else "LINKED"
            lines.append(
                f"|  [{st:<6}] {a.get('app',''):<18} port={a.get('port',0):<5} mode={a.get('attach_mode',''):<12} {a.get('domain',''):<20}|"
            )
    if unlinked:
        ports_str = ", ".join(f":{u['port']}" + (f"({u['process']})" if u.get("process") else "") for u in unlinked[:6])
        lines.append("+" + "-" * 78 + "+")
        lines.append(f"| UNLINKED LOCAL PORTS: {ports_str[:54]:<54} |")
    lines.append("+" + "-" * 78 + "+")
    return "\n".join(lines)
