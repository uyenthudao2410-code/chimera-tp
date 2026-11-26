"""PlatformSubstrate: Unified CHIMERA-CONNECT + 4 Core Gateways attached cleanly to ChimeraDaemon."""

from __future__ import annotations

import json
import os
import platform
import threading
import time
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Any

from ..autopilot import get_zero_weight_status
from .autoload import autoload_status
from .colab_cli_bridge import ColabCliBridge
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
from .folded_cavity_rlnc import CristaeFoldedCavityRLNC
from .ghost_bubble import GhostBubbleEngine
from .hybrid_search import HybridPlatformSearch
from .immortal_jobs import ImmortalJobEngine
from .pulse_bus import PulseBus
from .browser_grid import SharedBrowserGrid
from .cosmos_entity import CosmosEntityEngine
from .hyper_desk import HyperDeskEngine
from .omega_entity import OmegaEntityEngine
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
        self.colab = ColabCliBridge(
            state_dir=Path(daemon.ops_dir) / "colab",
            peer_base_resolver=(
                daemon.active_edge_peer_base
                if (not self.ephemeral and daemon.config.peer_ipv4)
                else None
            ),
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
            colab_bridge=self.colab,
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
        self.ghost = GhostBubbleEngine(work_root=Path(daemon.ops_dir) / "ghost_bubbles")
        self.hyper_desk = HyperDeskEngine(
            host_governor=getattr(daemon, "host_governor", None),
            pulse_bus=self.pulse,
            zygote_pool=self.zygote,
            browser_grid=self.browser,
            peer_base_resolver=(
                daemon.active_edge_peer_base
                if (not self.ephemeral and daemon.config.peer_ipv4)
                else None
            ),
            on_flow=daemon.record_flow,
        )
        self.cosmos = CosmosEntityEngine(
            ops_dir=Path(daemon.ops_dir),
            node_name=daemon.config.node_name,
            role=daemon.config.role,
            substrate=self,
        )
        self.omega = OmegaEntityEngine(ops_dir=Path(daemon.ops_dir), substrate=self)
        self._peer_apps_lock = threading.Lock()
        self._peer_apps_ts: float = 0.0
        self._peer_apps_cache: list[dict[str, Any]] = []

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
            "ghost_bubble": True,
            "hyper_desk": True,
            "cosmos_entity": True,
            "omega_entity": True,
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
        self.colab.start_autonomous(ephemeral=self.ephemeral)
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
        self.ghost.close()
        self.hyper_desk.close()
        self.cosmos.close()
        self.colab.close()

    def merged_apps(self) -> list[dict[str, Any]]:
        """Merge local app registry with live ONLINE apps from peer node (e.g. svhome radar/tqouta visible on Windows)."""
        local = self.registry.list_apps()
        if self.ephemeral or not self.daemon.config.peer_ipv4:
            return local
        now = time.monotonic()
        with self._peer_apps_lock:
            cached = list(self._peer_apps_cache)
            stale = (now - self._peer_apps_ts) >= 10.0
        if stale:
            try:
                import urllib.request as _ur

                pbase = self.daemon.active_edge_peer_base().rstrip("/")
                if pbase:
                    opener = _ur.build_opener(_ur.ProxyHandler({}))
                    with opener.open(f"{pbase}/v1/apps/list", timeout=1.5) as r:
                        rem = json.loads(r.read().decode("utf-8"))
                    cached = list(rem.get("apps") or [])
                    with self._peer_apps_lock:
                        self._peer_apps_cache = cached
                        self._peer_apps_ts = now
            except Exception:
                pass
        by_name = {a["app"]: dict(a) for a in local}
        peer_label = self.daemon.config.peer_name or "peer"
        for ra in cached:
            name = ra.get("app")
            if not name:
                continue
            if name in by_name:
                if (not by_name[name].get("online")) and ra.get("online"):
                    by_name[name]["online"] = True
                    by_name[name]["pid"] = ra.get("pid", 0)
                    by_name[name]["attach_mode"] = f"{ra.get('attach_mode', 'peer')}@{peer_label}"
                    by_name[name]["last_seen"] = ra.get("last_seen", "")
            else:
                item = dict(ra)
                item["attach_mode"] = f"{ra.get('attach_mode', 'peer')}@{peer_label}"
                by_name[name] = item
        return [by_name[k] for k in sorted(by_name.keys())]

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
            "version": "21.0.0",
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
                    "description": "Single-writer WAL-safe SQLite cross-node replica fabric (<1.4ms local reads)",
                },
                "ghost_bubble": {
                    "status": "active" if self._cartridge_enabled["ghost_bubble"] else "disabled",
                    "endpoint": f"{anchor}/v1/ghost/run",
                    "description": "Unprivileged Copy-on-Write dry-run reality bubble with atomic commit/discard",
                },
                "hyper_desk": {
                    "status": "active" if self._cartridge_enabled["hyper_desk"] else "disabled",
                    "endpoint": f"{anchor}/v1/hyperdesk/diagnose",
                    "description": "v19 Kernel multitasking optimizer: Focus Cryo, Silicon Wall, GTX1650 VRAM-Swap, Hydra Collapse, Orphan Reaper & Sync Dam",
                },
                "cosmos_entity": {
                    "status": "active" if self._cartridge_enabled["cosmos_entity"] else "disabled",
                    "endpoint": f"{anchor}/v1/cosmos/status",
                    "description": "v20 Cosmic Infrastructure Entity: SSI, Zero-Env CAS, Omni-Memory (6 views), Immortal-Net, Immune-OS, Autogen SRE, Swarm OS, Thermo & Genesis",
                },
                "omega_entity": {
                    "status": "active" if self._cartridge_enabled["omega_entity"] else "disabled",
                    "endpoint": f"{anchor}/v1/omega/status",
                    "description": "v21 Singularity Entity: Ring-1 EPT dedup, Akashic DAG+Fusion, Silicon Alchemy, Precognition, Vampire Cloud, Intent Kernel, Multiverse & Autopoietic DNA",
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
        apps = self.merged_apps()
        eg = self.egress.stats()
        return {
            "version": "21.0.0",
            "anchor_url": self.anchor_url,
            "egress_proxy_url": self.egress.url,
            "apps_online": [a["app"] for a in apps if a.get("online")],
            "apps_linked": [a["app"] for a in apps if a.get("linked")],
            "apps_total": len(apps),
            "egress_requests": eg.get("requests_total", 0),
            "egress_hit_pct": eg.get("hit_rate_pct", 0.0),
            "egress_dlp_blocked": eg.get("dlp_blocked", 0),
            "egress_bytes_saved": eg.get("bytes_saved", 0),
            "pulse_seq": self.pulse.stats().get("latest_seq", 0),
            "search_docs": self.search.stats().get("docs", 0),
            "blackbox_frames": self.blackbox.stats().get("buffered_frames", 0),
            "vgpu_ready": self.vgpu.status().get("gpu_ready", False),
            "colab_online": self.vgpu.status().get("colab_online", 0),
            "immortal_jobs": self.jobs.stats().get("total_jobs", 0),
            "browser_sessions": self.browser.status().get("active_sessions", 0),
            "zygote_execs": self.zygote.status().get("executions", 0),
            "ghost_runs": self.ghost.status().get("runs", 0),
        }

    def handle_get(self, parsed: urllib.parse.ParseResult, headers: Any) -> tuple[int, dict[str, Any]] | None:
        path = parsed.path
        qs = urllib.parse.parse_qs(parsed.query)

        if path in ("/.well-known/chimera.json", "/v1/discover", "/v1/capabilities"):
            return 200, self.capabilities()

        if path == "/v1/smi":
            if not self.ephemeral:
                try:
                    self.colab.status(refresh=False)
                except Exception:
                    pass
            caps = self.capabilities()
            apps = self.merged_apps()
            known_ports = {int(self.daemon.http_addr[1]), int(self.egress.addr[1])}
            known_ports |= {int(a.get("port") or 0) for a in apps if int(a.get("port") or 0) > 0}
            unlinked = self.port_scanner.scan(exclude_ports=known_ports)[:12]
            return 200, {
                "ok": True,
                "capabilities": caps,
                "apps": apps,
                "unlinked_ports": unlinked,
                "egress": self.egress.stats(),
                "egress_domains": self.egress.domain_bandit_stats()[:10],
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
                "ghost": self.ghost.status(),
                "hyper_desk": self.hyper_desk.status(),
                "cosmos": self.cosmos.status(),
                "omega": self.omega.status(),
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

        if path == "/v1/egress/domains":
            return 200, {"ok": True, "domains": self.egress.domain_bandit_stats()}

        if path == "/v1/vgpu/workers/list":
            return 200, {"ok": True, "workers": self.vgpu.list_remote_workers()}

        if path == "/v1/vgpu/colab/status":
            refresh = (qs.get("refresh") or ["0"])[0].lower() in ("1", "true", "yes")
            return 200, self.colab.status(refresh=refresh)

        if path == "/v1/vgpu/colab/policy":
            return 200, {"ok": True, "policy": self.colab.get_policy(), "autonomous": self.colab.autonomous_state()}

        if path == "/v1/unify/status":
            from .unify import unify_status

            return 200, unify_status()

        if path == "/v1/openai/v1/models":
            models: list[dict[str, Any]] = [
                {"id": "chimera-vsa-embed-256", "object": "model", "owned_by": "chimera-vgpu-avx2"},
                {"id": "chimera-cuda-embed", "object": "model", "owned_by": "chimera-colab-elastic"},
                {"id": "chimera-colab-elastic", "object": "model", "owned_by": "chimera-colab-elastic"},
            ]
            relay_url = str(getattr(self.daemon.config, "tquota_relay_url", "") or "http://127.0.0.1:12500").rstrip("/")
            model_urls = [f"{relay_url}/v1/models"]
            if (not self.ephemeral) and getattr(self.daemon.config, "peer_ipv4", ""):
                model_urls.append(f"http://{self.daemon.config.peer_ipv4}:12500/v1/models")
            import urllib.request as _ur

            opener = _ur.build_opener(_ur.ProxyHandler({}))
            seen = {m["id"] for m in models}
            for murl in model_urls:
                try:
                    with opener.open(murl, timeout=1.2) as r:
                        rem = json.loads(r.read().decode("utf-8"))
                    added = False
                    for item in (rem.get("data") or []):
                        mid = item.get("id")
                        if mid and mid not in seen:
                            models.append(item)
                            seen.add(mid)
                            added = True
                    if added:
                        break
                except Exception:
                    continue
            return 200, {"object": "list", "data": models}

        if path == "/v1/ghost/status":
            return 200, self.ghost.status()

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

        # --- v19 CHIMERA-HYPERDESK GET routes ---
        if path == "/v1/hyperdesk/status":
            return 200, self.hyper_desk.status()
        if path == "/v1/hyperdesk/diagnose":
            return 200, self.hyper_desk.diagnose()
        if path == "/v1/hyperdesk/vram/status":
            return 200, {"ok": True, "vram_swap": self.hyper_desk.vram_swap.status()}

        # --- v20 CHIMERA-COSMOS GET routes ---
        if path == "/v1/cosmos/status":
            return 200, self.cosmos.status()
        if path == "/v1/cosmos/omni/get":
            key = (qs.get("key") or [""])[0]
            ns = (qs.get("namespace") or ["global"])[0]
            asof_raw = (qs.get("as_of_seq") or [""])[0]
            asof = int(asof_raw) if asof_raw.isdigit() else None
            return 200, self.cosmos.omni.get(key, namespace=ns, as_of_seq=asof)
        if path == "/v1/cosmos/omni/search":
            q = (qs.get("q") or [""])[0]
            ns = (qs.get("namespace") or ["global"])[0]
            return 200, self.cosmos.omni.search(q, namespace=ns)
        if path == "/v1/cosmos/genesis/seed":
            return 200, self.cosmos.export_genesis_seed()
        if path == "/v1/cosmos/genesis/assimilate":
            return 200, self.cosmos.assimilate_profile()

        # --- v21 CHIMERA-OMEGA ENTITY GET routes ---
        if path == "/v1/omega/status":
            return 200, self.omega.status()
        if path == "/v1/omega/gravity":
            return 200, self.omega.omega_gravity_status()

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
                prefer_cuda=bool(body.get("prefer_cuda", False)),
            )

        if path in ("/v1/openai/v1/chat/completions", "/v1/openai/v1/responses", "/v1/openai/v1/completions"):
            sub_ep = path[len("/v1/openai") :]
            relay_base = str(getattr(self.daemon.config, "tquota_relay_url", "") or "http://127.0.0.1:12500").rstrip("/")
            candidates = [f"{relay_base}{sub_ep}"]
            if (not self.ephemeral) and getattr(self.daemon.config, "peer_ipv4", ""):
                candidates.append(f"http://{self.daemon.config.peer_ipv4}:12500{sub_ep}")
            import urllib.error as _ue
            import urllib.request as _ur

            opener = _ur.build_opener(_ur.ProxyHandler({}))
            fwd_hdrs = {"Content-Type": "application/json"}
            if headers.get("Authorization"):
                fwd_hdrs["Authorization"] = str(headers.get("Authorization"))
            last_err = ""
            for target_url in candidates:
                try:
                    req = _ur.Request(target_url, data=raw_body, headers=fwd_hdrs, method="POST")
                    with opener.open(req, timeout=60.0) as r:
                        data = json.loads(r.read().decode("utf-8"))
                    if isinstance(data, dict):
                        data.setdefault("chimera_relay_via", target_url)
                    return r.status, data if isinstance(data, dict) else {"data": data}
                except _ue.HTTPError as e:
                    try:
                        return e.code, json.loads(e.read().decode("utf-8"))
                    except Exception:
                        return e.code, {"error": str(e)}
                except Exception as exc:
                    last_err = str(exc)
            return 503, {"error": f"openai_relay_unavailable:{last_err}", "hint": "Ensure local/peer tquota relay (:12500) is active; /v1/openai/v1/embeddings works standalone."}

        if path == "/v1/vgpu/compute":
            if not self._cartridge_enabled.get("vgpu_pareto", True):
                return 503, {"error": "cartridge_disabled:vgpu_pareto"}
            try:
                return 200, self.vgpu.compute_unified(
                    task_kind=str(body.get("task_kind") or "embed"),
                    payload=body.get("payload") or {},
                    prefer_cuda=bool(body.get("prefer_cuda", False)),
                    profile=body.get("profile") or None,
                    app=str(body.get("app") or headers.get("X-Chimera-App") or "external"),
                )
            except ValueError as exc:
                return 400, {"error": str(exc)}
            except Exception as exc:
                return 502, {"error": str(exc)}

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

        if path == "/v1/vgpu/workers/register":
            try:
                return 200, self.vgpu.register_remote_worker(body)
            except Exception as exc:
                return 400, {"error": str(exc)}

        if path == "/v1/vgpu/colab/exec":
            if not self._cartridge_enabled.get("vgpu_pareto", True):
                return 503, {"error": "cartridge_disabled:vgpu_pareto"}
            try:
                return 200, self.colab.exec_task(
                    task_kind=str(body.get("task_kind") or "cuda_embed"),
                    payload=body.get("payload") or {},
                    profile=body.get("profile") or None,
                    session_name=body.get("session") or None,
                    keep_session=bool(body.get("keep_session", False)),
                    require_gpu=bool(body.get("require_gpu", False)),
                    allow_heavy_gpu=bool(body.get("allow_heavy_gpu", False)),
                )
            except Exception as exc:
                return 502, {"error": str(exc)}

        if path == "/v1/vgpu/colab/stop":
            sess = str(body.get("session") or "").strip()
            if not sess:
                return 400, {"error": "missing_session"}
            return 200, self.colab.stop_session(sess)

        if path == "/v1/vgpu/colab/tunnel-cmd":
            sess = str(body.get("session") or "chimera_t4").strip()
            lport = int(body.get("local_port") or 9795)
            rport = int(body.get("remote_port") or 9795)
            cmd = self.colab.build_ssh_tunnel_command(sess, local_port=lport, remote_port=rport)
            return 200, {"ok": True, "session": sess, "local_port": lport, "remote_port": rport, "cmd": cmd}

        if path == "/v1/vgpu/colab/auto-exec":
            if not self._cartridge_enabled.get("vgpu_pareto", True):
                return 503, {"error": "cartridge_disabled:vgpu_pareto"}
            try:
                return 200, self.colab.auto_execute(
                    task_kind=str(body.get("task_kind") or "cuda_embed"),
                    payload=body.get("payload") or {},
                    profile=body.get("profile") or None,
                    require_gpu=bool(body.get("require_gpu", True)),
                    allow_heavy_gpu=bool(body.get("allow_heavy_gpu", False)),
                )
            except Exception as exc:
                return 502, {"error": str(exc)}

        if path == "/v1/vgpu/colab/policy":
            try:
                pol = self.colab.update_policy(body)
                return 200, {"ok": True, "policy": pol, "autonomous": self.colab.autonomous_state()}
            except ValueError as exc:
                return 400, {"error": str(exc)}

        if path == "/v1/vgpu/ptx-bench":
            n = max(64, min(262144, int(body.get("n") or 16384)))
            va = [float((i % 13) - 6) for i in range(n)]
            vb = [float((i % 7) - 3) for i in range(n)]
            return 200, self.vgpu.run_ptx_kernel_if_eligible(va, vb, force=bool(body.get("force", False)))

        if path == "/v1/rlnc/folded-bench":
            return 200, CristaeFoldedCavityRLNC.run_benchmark(
                payload_bytes=max(1024, min(65536, int(body.get("payload_bytes") or 16384))),
                loss_rate=max(0.05, min(0.45, float(body.get("loss_rate") or 0.32))),
            )

        if path == "/v1/ghost/run":
            if not self._cartridge_enabled.get("ghost_bubble", True):
                return 503, {"error": "cartridge_disabled:ghost_bubble"}
            try:
                return 200, self.ghost.run_bubble(
                    target_dir=str(body.get("target_dir") or ""),
                    cmd=body.get("cmd") or "",
                    timeout_s=float(body.get("timeout_s") or 30.0),
                    auto_discard=bool(body.get("auto_discard", False)),
                )
            except Exception as exc:
                return 400, {"error": str(exc)}

        if path == "/v1/ghost/commit":
            try:
                return 200, self.ghost.commit(str(body.get("bubble_id") or ""))
            except Exception as exc:
                return 404, {"error": str(exc)}

        if path == "/v1/ghost/discard":
            return 200, self.ghost.discard(str(body.get("bubble_id") or ""))

        # --- v19 CHIMERA-HYPERDESK POST routes ---
        if path.startswith("/v1/hyperdesk/"):
            if not self._cartridge_enabled.get("hyper_desk", True):
                return 503, {"error": "cartridge_disabled:hyper_desk"}
            if path == "/v1/hyperdesk/optimize":
                return 200, self.hyper_desk.optimize_now(
                    reap_orphans=bool(body.get("reap_orphans", True)),
                    apply_cryo=bool(body.get("apply_cryo", True)),
                    apply_silicon_wall=bool(body.get("apply_silicon_wall", True)),
                    apply_sync_dam=bool(body.get("apply_sync_dam", True)),
                    apply_hydra=bool(body.get("apply_hydra", True)),
                    dry_run=bool(body.get("dry_run", False)),
                )
            if path == "/v1/hyperdesk/cryo":
                return 200, self.hyper_desk.apply_cryo(
                    min_ws_mb=float(body.get("min_ws_mb") or 40.0),
                    allow_suspend=bool(body.get("allow_suspend", False)),
                    dry_run=bool(body.get("dry_run", False)),
                )
            if path == "/v1/hyperdesk/thaw":
                return 200, self.hyper_desk.thaw_all()
            if path == "/v1/hyperdesk/silicon-wall":
                return 200, self.hyper_desk.apply_silicon_wall(
                    release_to_full=bool(body.get("release_to_full", False)),
                    dry_run=bool(body.get("dry_run", False)),
                )
            if path == "/v1/hyperdesk/reap-orphans":
                return 200, self.hyper_desk.reap_orphans(dry_run=bool(body.get("dry_run", True)))
            if path == "/v1/hyperdesk/hydra":
                return 200, self.hyper_desk.collapse_hydra(dry_run=bool(body.get("dry_run", False)))
            if path == "/v1/hyperdesk/sync-dam":
                return 200, self.hyper_desk.apply_sync_dam(
                    suspend=bool(body.get("suspend", False)),
                    release=bool(body.get("release", False)),
                    dry_run=bool(body.get("dry_run", False)),
                )
            if path == "/v1/hyperdesk/vram/bench":
                return 200, self.hyper_desk.vram_swap.benchmark(payload_mb=float(body.get("payload_mb") or 4.0))
            if path == "/v1/hyperdesk/vram/yield":
                return 200, self.hyper_desk.vram_swap.yield_vram(drop_pages=bool(body.get("drop_pages", False)))
            if path == "/v1/hyperdesk/cortex/watch":
                try:
                    return 200, self.hyper_desk.cortex_watch_scan(str(body.get("dir") or "."))
                except Exception as exc:
                    return 400, {"error": str(exc)}

        # --- v20 CHIMERA-COSMOS POST routes ---
        if path.startswith("/v1/cosmos/"):
            if not self._cartridge_enabled.get("cosmos_entity", True):
                return 503, {"error": "cartridge_disabled:cosmos_entity"}
            if path == "/v1/cosmos/ssi/place":
                try:
                    return 200, self.cosmos.ssi_place_and_levitate(
                        str(body.get("task_id") or f"task_{int(time.time())}"),
                        work_kind=str(body.get("work_kind") or "cpu_batch"),
                        data_locality=str(body.get("data_locality") or "local"),
                        state=body.get("state"),
                        levitate_to=body.get("levitate_to"),
                    )
                except Exception as exc:
                    return 400, {"error": str(exc)}
            if path == "/v1/cosmos/omni/put":
                return 200, self.cosmos.omni.put(
                    str(body.get("key") or "k"),
                    body.get("value"),
                    namespace=str(body.get("namespace") or "global"),
                    tier=str(body.get("tier") or "hot_ram"),
                )
            if path == "/v1/cosmos/omni/sql":
                try:
                    return 200, self.cosmos.omni.sql_query(str(body.get("sql") or ""))
                except Exception as exc:
                    return 400, {"error": str(exc)}
            if path == "/v1/cosmos/omni/heal":
                return 200, self.cosmos.omni.test_gf256_self_heal(int(body.get("seq") or 1))
            if path == "/v1/cosmos/net/resolve":
                try:
                    return 200, self.cosmos.resolve_capability_uri(str(body.get("uri") or ""))
                except Exception as exc:
                    return 400, {"error": str(exc)}
            if path == "/v1/cosmos/immune/ghost-issue":
                return 200, self.cosmos.immune.issue_ghost_token(
                    str(body.get("secret_name") or "API_KEY"),
                    str(body.get("real_value") or ""),
                    list(body.get("allowed_domains") or []),
                )
            if path == "/v1/cosmos/immune/ghost-resolve":
                return 200, self.cosmos.immune.resolve_ghost_token(
                    str(body.get("ghost_token") or ""),
                    str(body.get("target_domain") or ""),
                )
            if path == "/v1/cosmos/autogen/sre":
                return 200, self.cosmos.autogen_sre_cycle(execute=bool(body.get("execute", False)))
            if path == "/v1/cosmos/swarm/spawn":
                try:
                    return 200, self.cosmos.swarm_spawn_agent(
                        str(body.get("agent_id") or "agent1"),
                        str(body.get("target_dir") or "."),
                        max_ram_mb=int(body.get("max_ram_mb") or 512),
                        max_cost_usd=float(body.get("max_cost_usd") or 0.25),
                    )
                except Exception as exc:
                    return 400, {"error": str(exc)}
            if path == "/v1/cosmos/swarm/burn-check":
                return 200, self.cosmos.swarm_check_burn_loop(
                    str(body.get("agent_id") or ""),
                    str(body.get("error_trace") or ""),
                    float(body.get("cost_delta_usd") or 0.0),
                )
            if path == "/v1/cosmos/thermo/flush":
                return 200, self.cosmos.thermo.flush_coalesced()

        # --- v21 CHIMERA-OMEGA ENTITY POST routes ---
        if path.startswith("/v1/omega/"):
            if not self._cartridge_enabled.get("omega_entity", True):
                return 503, {"error": "cartridge_disabled:omega_entity"}
            if path == "/v1/omega/benchmark":
                return 200, self.omega.run_full_entity_benchmark()
            if path == "/v1/omega/intent/compile":
                return 200, self.omega.compile_intent(
                    str(body.get("service") or "app"),
                    dict(body.get("invariants") or {}),
                )
            if path == "/v1/omega/akashic/eval":
                return 200, self.omega.akashic_eval(
                    str(body.get("op") or "agg"),
                    list(body.get("records") or []),
                    threshold=float(body.get("threshold") or 0.0),
                )
            if path == "/v1/omega/alchemy/run":
                return 200, self.omega.silicon_alchemy_run(
                    n=int(body.get("n") or 8192),
                    prefer_gpu=bool(body.get("prefer_gpu", True)),
                )
            if path == "/v1/omega/vampire/dispatch":
                raw = str(body.get("payload") or "chimera_vampire_payload").encode("utf-8")
                return 200, self.omega.vampire_cloud_dispatch(raw, scalar=int(body.get("scalar") or 7))
            if path == "/v1/omega/multiverse/race":
                try:
                    return 200, self.omega.multiverse_race(
                        str(body.get("target_dir") or ""),
                        list(body.get("candidates") or []),
                        collapse_winner=bool(body.get("collapse_winner", True)),
                    )
                except Exception as exc:
                    return 400, {"error": str(exc)}
            if path == "/v1/omega/multiverse/ctrl-z":
                return 200, self.omega.global_ctrl_z(body.get("snap_id"))
            if path == "/v1/omega/autopoietic/evolve":
                return 200, self.omega.autopoietic_evolve()

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
    gh = smi_data.get("ghost") or {}
    hd = smi_data.get("hyper_desk") or {}
    cs = smi_data.get("cosmos") or {}
    om = smi_data.get("omega") or {}
    gpu = vg.get("gpu") or {}
    colab_n = int(vg.get("colab_online", 0))
    ccli = vg.get("colab_cli") or {}
    auto_lbl = str((ccli.get("autonomous") or {}).get("mode_label") or "")
    if ccli.get("available") and ccli.get("balance_cu") is not None:
        colab_tag = f"Colab:{float(ccli['balance_cu']):.0f}CU[{auto_lbl or 'AUTO'}]"
    else:
        colab_tag = f"Colab:{colab_n}"
    gpu_desc = (
        f"{colab_tag} | {gpu.get('name','GPU')[:11]} {gpu.get('util_pct',0):.0f}% {gpu.get('temp_c',0):.0f}C"
        if gpu.get("present")
        else f"{colab_tag} | AVX2/peer"
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
        f"|  [ON] egress_membrane : req={eg.get('requests_total',0):<5} hit={eg.get('hit_rate_pct',0):>5.1f}% dlp={eg.get('dlp_blocked',0):<3} saved={eg.get('bytes_saved',0):>8} B |",
        f"|  [ON] pulse_bus       : seq={pl.get('latest_seq',0):<5} buf={pl.get('buffered_events',0):<4} kv={pl.get('kv_entries',0):<4} relayed={pl.get('relayed_to_peer',0):<6} |",
        f"|  [ON] hybrid_search   : docs={sr.get('docs',0):<5} ns={sr.get('namespaces',0):<4} q={sr.get('queries',0):<5} avx2_vsa={str(sr.get('vsa_avx2_enabled')):<7} |",
        f"|  [ON] flight_recorder : frames={bb.get('buffered_frames',0):<4}/{bb.get('max_frames',0):<4} freezes={bb.get('freezes',0):<4} (0-disk-write ring)   |",
        f"|  [ON] vgpu_pareto     : ready={str(vg.get('gpu_ready',False)):<5} {gpu_desc:<43}|",
        f"|  [ON] immortal_jobs   : jobs={jb.get('total_jobs',0):<4} done={jb.get('completed_jobs',0):<4} steps={jb.get('completed_steps',0):<5} dup_skip={jb.get('duplicate_steps_skipped',0):<5}|",
        f"|  [ON] browser_grid    : bin={str(br.get('binary_found',False)):<5} running={str(br.get('running',False)):<5} sessions={br.get('active_sessions',0):<3} (0MB idle)  |",
        f"|  [ON] zygote_canary   : mode={zg.get('mode','?'):<17} execs={zg.get('executions',0):<4} canary_runs={cn.get('runs',0):<3} |",
        f"|  [ON] vault_sql       : dbs={vq.get('db_count',0):<4} syncs={vq.get('syncs',0):<4} queries={vq.get('queries',0):<5} saved={vq.get('bytes_saved',0):>7} B |",
        f"|  [ON] ghost_bubble    : open={gh.get('open_bubbles',0):<3} runs={gh.get('runs',0):<4} commits={gh.get('commits',0):<4} discards={gh.get('discards',0):<4}   |",
        f"|  [ON] hyper_desk      : cryo={hd.get('cryo_passes',0):<3} wall={hd.get('silicon_wall_pinned_procs',0):<3} reaped={hd.get('orphans_reaped',0):<3} vram={str((hd.get('vram_swap') or {}).get('cuda_available',False)):<5}  |",
        f"|  [ON] cosmos_entity   : omni={((cs.get('omni_memory') or {}).get('log_entries',0)):<4} cas={((cs.get('zero_env') or {}).get('envs',0)):<3} ssi={cs.get('ssi_tasks',0):<3} regime={str((cs.get('thermodynamic') or {}).get('regime','?'))[:13]:<13}|",
        f"|  [ON] omega_entity    : ept={om.get('ept_unique_pages',0):<4} akashic={om.get('akashic_hits',0):<4} gen={((om.get('active_genome') or {}).get('generation',1)):<3} mode={str(om.get('ring_minus_1_mode','?'))[:14]:<14}|",
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
