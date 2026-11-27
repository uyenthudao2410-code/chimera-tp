"""PlatformSubstrate: Unified CHIMERA-CONNECT + 4 Core Gateways attached cleanly to ChimeraDaemon."""

from __future__ import annotations

import base64
import collections
import ctypes
import gc
import hashlib
import http.client
import json
import os
import platform
import re
import select
import socket
import sys
import threading
import time
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Any

from .. import __version__
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
from .evidence import EvidenceLedger
from .flight_recorder import DisklessSecretVault, FlightRecorderBlackBox
from .folded_cavity_rlnc import CristaeFoldedCavityRLNC
from .ghost_bubble import GhostBubbleEngine
from .hybrid_search import HybridPlatformSearch
from .ct_scanner import (
    ModelDnaRegistry,
    anthropic_to_openai_response,
    audit_instruction_durability,
    classify_http_fault,
    classify_response,
    ct_scan,
    openai_to_anthropic_request,
    sanitize_prompt,
)
from .immortal_jobs import ImmortalJobEngine
from .peer_guard import fast_egress_fuse
from .precog_conduit import PrecognitionStreamTap, PrecogWarmupPool, TurnTimeMachine
from .spore import QuarantineGuard, SporeAutopoieticWatcher, SporeEngine
from .pulse_bus import PulseBus
from .browser_grid import SharedBrowserGrid
from .hyper_desk import HyperDeskEngine
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
        self.evidence = EvidenceLedger(ops_dir=Path(daemon.ops_dir))
        self._observe_activity = self.evidence.activity_observer(daemon.config.node_name, synthetic=self.ephemeral)
        self.egress = EgressMembraneProxy(
            listen_host="127.0.0.1",
            listen_port=0 if self.ephemeral else 9781,
            cassettes_dir=Path(daemon.ops_dir) / "cassettes",
            on_flow=daemon.record_flow,
            on_activity=self._observe_activity,
            peer_proxy_resolver=self._resolve_peer_egress_proxy,
            peer_hop_fuse=(None if self.ephemeral else fast_egress_fuse),
        )
        self.pulse = PulseBus(
            node_name=daemon.config.node_name,
            authorize_peer_request=daemon.authenticate_peer_request,
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
            on_activity=self._observe_activity,
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
            ops_dir=Path(daemon.ops_dir),
            host_governor=getattr(daemon, "host_governor", None),
            pulse_bus=self.pulse,
            zygote_pool=self.zygote,
            browser_grid=self.browser,
            colab_bridge=self.colab,
            peer_base_resolver=(
                daemon.active_edge_peer_base
                if (not self.ephemeral and daemon.config.peer_ipv4)
                else None
            ),
            on_flow=daemon.record_flow,
        )
        self._engine_lock = threading.RLock()
        self._engines_closed = False
        self._cosmos = None
        self._omega = None
        self._bios = None
        self._exile_handoff = None
        self._peer_apps_lock = threading.Lock()
        self._peer_apps_ts: float = 0.0
        self._peer_apps_cache: list[dict[str, Any]] = []
        self._openai_models_lock = threading.Lock()
        self._openai_models_ts: float = 0.0
        self._openai_models_cache: list[dict[str, Any]] = []
        self._openai_model_routes: dict[str, tuple[str, float]] = {}
        self._openai_conduit_lock = threading.Lock()
        self._openai_conduit_stats: dict[str, Any] = {
            "requests_total": 0,
            "streams_total": 0,
            "sse_chunks_in": 0,
            "sse_flushes_out": 0,
            "immortal_detached": 0,
            "immortal_completed": 0,
            "immortal_replays": 0,
            "prefix_audits": 0,
            "prefix_breaks": 0,
            "prefix_tokens_lost_est": 0,
            "precog_taps": 0,
            "precog_hints": 0,
            "turns_tracked": 0,
            "bytes_streamed": 0,
            "default_coalesce_ms": 16,
        }
        self._detached_harvest_sem = threading.Semaphore(4)
        self._turn_ledger: collections.OrderedDict[str, dict[str, Any]] = collections.OrderedDict()
        self._fallback_symbiote: Any = None
        self._precog_pool = PrecogWarmupPool(
            egress_getter=lambda: self.egress,
            pulse_getter=lambda: self.pulse,
            allowed_roots_getter=(
                (lambda: self.daemon._allowed_roots())
                if hasattr(daemon, "_allowed_roots")
                else None
            ),
        )
        self._turn_tm = TurnTimeMachine(
            state_dir=(Path(daemon.ops_dir) / "timemachine") if self.ephemeral else None,
        )
        self._dna = ModelDnaRegistry(
            path=(Path(daemon.ops_dir) / "model_dna.json") if self.ephemeral else None,
        )
        self._spore = SporeEngine(
            chimera_dir=(Path(daemon.ops_dir) / "chimera_spore_home") if self.ephemeral else None,
            ops_dir=Path(daemon.ops_dir),
        )
        self._spore_watcher = SporeAutopoieticWatcher(
            self._spore,
            auto_discover_defaults=(not self.ephemeral),
        )
        self._trim_tick: int = 0
        self._pulse_beat: int = 0
        self._unify_check_ts: float = 0.0
        self._unify_active_cache: bool = False
        self._pulse_cache_lock = threading.Lock()
        self._pulse_cache_ts: float = 0.0
        self._pulse_cache_val: dict[str, Any] | None = None
        self._agent_bus: Any = None
        self._prometheus: Any = None

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
            "agent_hyper_bus": True,
            "bios": True,
            "prometheus": True,
        }
        self._load_cartridge_config()
        self._beacon_paths: list[Path] = []

    @property
    def prometheus(self) -> Any:
        if self._prometheus is None:
            from .prometheus import ChimeraPrometheusCore, get_prometheus_core

            if self.ephemeral:
                self._prometheus = ChimeraPrometheusCore(
                    data_dir=Path(self.daemon.ops_dir) / "prometheus",
                    ephemeral=True,
                )
            else:
                self._prometheus = get_prometheus_core()
        return self._prometheus

    @property
    def agent_bus(self) -> Any:
        if self._agent_bus is None:
            from .agent_probe import AgentHyperBus

            self._agent_bus = AgentHyperBus(
                symbiont_db_path=(Path(self.daemon.ops_dir) / "agent_symbiont.sqlite") if self.ephemeral else None,
                ephemeral=self.ephemeral,
            )
        return self._agent_bus

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
        if name == "hyper_desk":
            if enabled:
                self.hyper_desk.start_autonomic()
            else:
                self.hyper_desk.stop_autonomic(restore_defaults=True)
        self.write_beacons()
        try:
            self.daemon.record_flow(
                "compute",
                "cortex-ui",
                name,
                "CARTRIDGE_TOGGLE",
                detail=f"enabled={bool(enabled)}",
                ok=True,
            )
        except Exception:
            pass
        return {"ok": True, "cartridge": name, "enabled": bool(enabled), "cartridges": dict(self._cartridge_enabled)}

    def _trim_memory_if_needed(self, ram_mb: float) -> None:
        """Keep Linux glibc RSS strictly under Zero-Weight 80 MB budget after burst CONNECT tunnels / forks."""
        self._trim_tick += 1
        if ram_mb < 66.0 and (self._trim_tick % 30) != 0:
            return
        try:
            gc.collect()
            if os.name != "nt":
                ctypes.CDLL("libc.so.6").malloc_trim(0)
        except Exception:
            pass

    def _sample_frame(self) -> dict[str, Any]:
        zw = get_zero_weight_status()
        ram_mb = float(zw.get("daemon_ram_mb", 0.0))
        self._trim_memory_if_needed(ram_mb)
        if not self.ephemeral:
            try:
                coroner_cb = None
                if self._agent_bus is not None and hasattr(self._agent_bus, "symbiont"):
                    coroner_cb = lambda: self._agent_bus.symbiont.coroner.scan(auto_seed_immune=True)
                self._spore_watcher.tick_if_due(
                    coroner_fn=coroner_cb,
                    node_name=str(self.daemon.config.node_name),
                    pulse_fn=lambda topic, payload: self.pulse.publish(topic, payload, app="spore-watcher", relay=False),
                )
            except Exception:
                pass
        eg = self.egress.stats()
        return {
            "ram_mb": ram_mb,
            "apps_online": sum(1 for a in self.registry.list_apps() if a.get("online")),
            "egress_reqs": eg.get("requests_total", 0),
            "egress_hit_pct": eg.get("hit_rate_pct", 0.0),
            "pulse_seq": self.pulse.stats().get("latest_seq", 0),
        }

    def _seed_startup_evidence(self) -> None:
        """Seed only honest startup self-check evidence; leave unprobed cartridges unverified."""
        node = str(self.daemon.config.node_name)
        if int(self.daemon.http_addr[1]) > 0:
            self.evidence.record(
                "connect",
                execution_node=node,
                fallback_mode=None,
                ttl_s=300.0,
                verified=True,
                metrics={"anchor_port": int(self.daemon.http_addr[1]), "startup_self_check": True},
            )
        if self._cartridge_enabled.get("egress_membrane", True) and int(self.egress.addr[1]) > 0:
            self.evidence.record(
                "egress_membrane",
                execution_node=node,
                fallback_mode=None,
                ttl_s=300.0,
                verified=True,
                metrics={"listen_port": int(self.egress.addr[1]), "startup_self_check": True},
            )

    def start(self) -> "PlatformSubstrate":
        self.egress.start()
        self.colab.start_autonomous(ephemeral=self.ephemeral)
        if not self.ephemeral:
            self.blackbox.start()
            if self._cartridge_enabled.get("hyper_desk", True) and self.hyper_desk._autonomic_policy.get("enabled", True):
                self.hyper_desk.start_autonomic()
            try:
                noo = self.agent_bus.symbiont.noosphere
                peer_getter = lambda: self.daemon.active_edge_peer_base()
                peer_auth = lambda req: self.daemon.authenticate_peer_request(req)
                noo.attach_peer_transport(
                    peer_base_getter=peer_getter,
                    peer_auth_fn=peer_auth,
                )
                if hasattr(self.agent_bus.probe, "attach_peer_transport"):
                    self.agent_bus.probe.attach_peer_transport(
                        peer_base_getter=peer_getter,
                        peer_auth_fn=peer_auth,
                    )
                if hasattr(noo, "attach_bios"):
                    noo.attach_bios(lambda: self._bios)
                noo.start_autonomic_pulse()
            except Exception:
                pass
        else:
            self.blackbox.record_once()
        self._seed_startup_evidence()
        self.write_beacons()
        return self

    @property
    def cosmos(self):
        with self._engine_lock:
            if self._engines_closed:
                raise RuntimeError("substrate_closed")
            if self._cosmos is None:
                from .cosmos_entity import CosmosEntityEngine
                self._cosmos = CosmosEntityEngine(
                    ops_dir=Path(self.daemon.ops_dir), node_name=self.daemon.config.node_name,
                    role=self.daemon.config.role, substrate=self)
            return self._cosmos

    @property
    def omega(self):
        with self._engine_lock:
            if self._engines_closed:
                raise RuntimeError("substrate_closed")
            if self._omega is None:
                from .omega_entity import OmegaEntityEngine
                self._omega = OmegaEntityEngine(ops_dir=Path(self.daemon.ops_dir), substrate=self)
            return self._omega

    @property
    def bios(self):
        with self._engine_lock:
            if self._engines_closed:
                raise RuntimeError("substrate_closed")
            if self._bios is None:
                from .bios.organism import ChimeraBiosOrganism

                self._bios = ChimeraBiosOrganism(
                    ops_dir=Path(self.daemon.ops_dir) / "bios",
                    repo_root=Path(__file__).resolve().parents[2],
                    node_name=str(self.daemon.config.node_name),
                    nixl_ring_path=(
                        (Path(self.daemon.ops_dir) / "bios" / "chimera_nixl_ring.bin")
                        if self.ephemeral
                        else None
                    ),
                    ephemeral=self.ephemeral,
                )
            return self._bios

    @property
    def exile_handoff(self):
        with self._engine_lock:
            if self._engines_closed:
                raise RuntimeError("substrate_closed")
            if self._exile_handoff is None:
                from . import build_queue
                from .exile_handoff import CheckpointedExileCoordinator
                self._exile_handoff = CheckpointedExileCoordinator(
                    jobs=self.jobs, cas=self.cosmos.zero_env, pulse=self.pulse,
                    governor=getattr(self.daemon, "host_governor", None), exile=self.hyper_desk.exile,
                    evidence=self.evidence, node_name=self.daemon.config.node_name,
                    queue_dir=None if self.ephemeral else build_queue.outgoing(),
                    remote_target=str(getattr(self.daemon.config, "peer_name", "") or "svhome"))
            return self._exile_handoff

    def close(self) -> None:
        self._precog_pool.close()
        self.blackbox.close()
        self.egress.close()
        self.search.close()
        self.jobs.close()
        self.browser.close()
        self.zygote.close()
        self.ghost.close()
        self.hyper_desk.close()
        with self._engine_lock:
            self._engines_closed = True
            if self._cosmos is not None:
                self._cosmos.close()
            if self._omega is not None:
                self._omega.close()
            if self._bios is not None:
                self._bios.close()
            bus = getattr(self, "_agent_bus", None) or self.__dict__.get("agent_bus")
            if bus is not None:
                bus.close()
        self.evidence.flush_traffic()
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
        cartridges = {
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
                "description": "Placement planning, local task checkpoints, content-addressed environments, journal views, policy checks and configuration seeds",
            },
            "omega_entity": {
                "status": "active" if self._cartridge_enabled["omega_entity"] else "disabled",
                "endpoint": f"{anchor}/v1/omega/status",
                "description": "Hardware capability probe, userspace buffer deduplication, memoization, CPU/GPU kernels, topology planning and workspace trials",
            },
            "agent_hyper_bus": {
                "status": "active" if self._cartridge_enabled["agent_hyper_bus"] else "disabled",
                "endpoint": f"{anchor}/v1/agent/xray-batch",
                "description": "Zero-Spawn Organ 3 Agent Hyper-Bus: concurrent 40-op xray-batch, 2-hop AST/JS/Rust callgraph-slice, atomic BLAKE2s commit-verify & Token-Diet compactor",
            },
            "bios": {
                "status": (
                    ("active" if self._bios is not None else "lazy_ready")
                    if self._cartridge_enabled.get("bios", True)
                    else "disabled"
                ),
                "endpoint": f"{anchor}/v1/bios",
                "abi_endpoint": f"{anchor}/v1/bios/abi",
                "sync_endpoint": f"{anchor}/v1/bios/sync",
                "spore_pwa": f"{anchor}/v1/bios/spore",
                "stream_sse": f"{anchor}/v1/bios/stream",
                "nixl_endocrine_offset": 32,
                "nixl_endocrine_bytes": 32,
                "lazy_loaded": self._bios is None,
                "organs_count": 10,
                "description": "CHIMERA-BIOS 10-organ living physiology, immunity, cognition & Open Ecosystem Soul (0 B boot RSS)",
            },
            "prometheus": {
                "status": (
                    ("active" if self._prometheus is not None else "lazy_ready")
                    if self._cartridge_enabled.get("prometheus", True)
                    else "disabled"
                ),
                "endpoint": f"{anchor}/v1/prometheus/status",
                "oracle_endpoint": f"{anchor}/v1/prometheus/oracle/probe",
                "epoch_endpoint": f"{anchor}/v1/prometheus/epoch/status",
                "ghost_endpoint": f"{anchor}/v1/prometheus/ghost/status",
                "lazy_loaded": self._prometheus is None,
                "description": "CHIMERA-PROMETHEUS Empirical Axioms, Sovereign Epoch Arbiter, Galileo Science, PHANTOM-RPC Oracle, Ghost Pool & Native Micronucleus (0 B boot RSS)",
            },
        }
        for cname, cinfo in cartridges.items():
            en = True if cname == "connect" else bool(self._cartridge_enabled.get(cname, True))
            cinfo["enabled"] = en
            cinfo["evidence"] = self.evidence.evaluate(cname, enabled=en)
        ev_snap = self.evidence.snapshot({"connect": True, **self._cartridge_enabled}, include_extra=True)
        return {
            "ok": True,
            "schema": "chimera.capabilities.v1",
            "version": __version__,
            "package_version": __version__,
            "capability_version": "21.0.0",
            "cartridge_status_basis": "config_plus_live_evidence",
            "runtime_source_dir": str(Path(__file__).resolve().parents[2]).replace("\\", "/"),
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
            "evidence_summary": ev_snap["counts"],
            "cartridges": cartridges,
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
        now_m = time.monotonic()
        with self._pulse_cache_lock:
            if self._pulse_cache_val is not None and (now_m - self._pulse_cache_ts) < 2.0:
                cached = dict(self._pulse_cache_val)
                self._pulse_beat += 1
                cached["heartbeat"] = self._pulse_beat
                return cached
        self._pulse_beat += 1
        apps = self.merged_apps()
        eg = self.egress.stats()
        vg = self.vgpu.status()
        gpu = vg.get("gpu") or {}
        ccli = vg.get("colab_cli") or {}
        cauto = ccli.get("autonomous") or {}
        colab_cu = float(ccli.get("balance_cu") or 0.0)
        if colab_cu <= 0.0:
            try:
                cc = getattr(self.colab, "_status_cache", None)
                if cc and isinstance(cc, tuple) and len(cc) >= 2 and isinstance(cc[1], dict):
                    colab_cu = float((cc[1].get("usage") or {}).get("balance_cu") or 0.0)
            except Exception:
                pass
        hd = self.hyper_desk.status()
        vram_st = hd.get("vram_swap") or {}
        stasis_st = hd.get("stasis") or {}
        thermo_st = hd.get("thermostat") or {}
        gov = getattr(self.daemon, "host_governor", None)
        hm = gov.get_host_metrics() if gov else {}
        peer_online = bool(getattr(getattr(self.daemon, "config", None), "peer_ipv4", ""))
        # A passive heartbeat must not start an optional engine or open its databases.
        cosmos, omega = self._cosmos, self._omega
        th = cosmos.thermo.optimize_placement(
            host_metrics=hm, gpu=gpu, colab_cu=colab_cu, peer_online=peer_online
        ) if cosmos is not None else {}
        imm = cosmos.immune.stats() if cosmos is not None else {}
        zenv = cosmos.zero_env.stats() if cosmos is not None else {}
        om = omega.status() if omega is not None else {}
        gen = om.get("active_genome") or {}
        reclaimed_mb = (
            float(hd.get("cryo_est_ws_reclaimed_mb") or 0.0)
            + float(hd.get("orphans_commit_reclaimed_mb") or 0.0)
            + float(hd.get("hydra_trimmed_mb") or 0.0)
            + float(stasis_st.get("total_ws_reclaimed_mb") or 0.0)
        )
        if (now_m - self._unify_check_ts) >= 30.0:
            self._unify_check_ts = now_m
            self._unify_active_cache = (chimera_home_dir() / "unify.json").is_file()
        with self._openai_models_lock:
            oai_cnt = len(self._openai_models_cache) or 3
        host_cpu = hm.get("cpu_pct")
        real_cpu = round(float(host_cpu), 1) if host_cpu is not None else round(float(th.get("cpu_pct") or 0.0), 1)
        # Compact living-organism telemetry (never triggers lazy-load in ephemeral tests!)
        bus_live = getattr(self, "_agent_bus", None) or self.__dict__.get("agent_bus")
        noo_live = getattr(getattr(bus_live, "symbiont", None), "_noosphere", None) if bus_live is not None else None
        eid_live = getattr(getattr(bus_live, "symbiont", None), "_eidolon", None) if bus_live is not None else None
        org_data: dict[str, Any] = {"alive": False, "mcp_tools": 43}
        if noo_live is not None:
            try:
                ns = noo_live.status()
                ap = ns.get("autonomic_pulse") or {}
                bs = ns.get("bidirectional_sync") or {}
                im = ns.get("immune") or {}
                mc = ns.get("metacognition") or {}
                ws = ns.get("workspace") or {}
                sub = ns.get("subconscious") or {}
                dr = ns.get("dreamer") or {}
                pv = bs.get("peer_vitals") or {}
                eg_st = ns.get("source_echo_guard") or {}
                org_data = {
                    "alive": bool(ap.get("alive")),
                    "ticks": int(ap.get("ticks") or 0),
                    "tick_ms": round(float(ap.get("last_tick_ms") or 0.0), 1),
                    "pain": round(float(im.get("last_pain_score") or 0.0), 2),
                    "antibodies": int(im.get("antibodies_emitted") or 0),
                    "gc_trims": int(im.get("gc_trims_total") or 0),
                    "fatigue": round(float(mc.get("cognitive_fatigue") or 0.0), 2),
                    "ws_items": int(ws.get("total_items") or 0),
                    "ws_top": [
                        {"k": str(it.get("kind") or "")[:16], "s": str(it.get("summary") or "")[:96]}
                        for it in (ws.get("top_items") or [])[:3]
                    ],
                    "dreams": int(dr.get("dreams_completed") or 0),
                    "has_epiphany": bool(dr.get("has_epiphany")),
                    "sub_hits": int(sub.get("offloaded_locally_total") or sub.get("handled_total") or 0),
                    "sub_saved": int(sub.get("google_tokens_saved_total") or 0),
                    "sync_on": bool(bs.get("enabled")),
                    "sync_cnt": int(bs.get("sync_count") or 0),
                    "sync_err": int(bs.get("sync_errors") or 0),
                    "sync_rtt": round(float(bs.get("last_rtt_ms") or 0.0), 1),
                    "peer_node": str(pv.get("node") or ""),
                    "peer_rss": round(float(pv.get("rss_mb") or 0.0), 1),
                    "echo_hits": int(eg_st.get("echo_hits") or 0),
                    "mcp_tools": 43,
                }
            except Exception:
                pass
        if eid_live is not None:
            try:
                es = eid_live.status()
                org_data["eidolon"] = {
                    "scout": int((es.get("scout") or {}).get("scans") or 0),
                    "fuzz": int((es.get("silent_fuzzer") or {}).get("runs") or 0),
                    "precog": int((es.get("precog_twin") or {}).get("verifies") or 0),
                    "syn_proj": len((es.get("synesthesia") or {}).get("projects_indexed") or []),
                    "syn_mem": int((es.get("synesthesia") or {}).get("memories_indexed") or 0),
                    "bg_req": bool((es.get("maintenance_lock") or {}).get("blue_green_required")),
                }
            except Exception:
                pass

        # Fast cached Tquota PRISM/Cold-Bridge snapshot (non-ephemeral only, 4s TTL, 0.28s timeout)
        prism_data: dict[str, Any] = getattr(self, "_prism_pulse_cache", None) or {}
        if not self.ephemeral and (now_m - float(getattr(self, "_prism_pulse_ts", 0.0))) >= 4.0:
            self._prism_pulse_ts = now_m
            try:
                import urllib.request as _ur

                opener = _ur.build_opener(_ur.ProxyHandler({}))
                with opener.open("http://127.0.0.1:12500/api/gemini/prism", timeout=0.28) as r:
                    pr = json.loads(r.read(65536).decode("utf-8", errors="replace"))
                if isinstance(pr, dict) and pr.get("ok"):
                    inv = pr.get("invariants") or {}
                    sqd = pr.get("sideQueryDedupe") or {}
                    wf = pr.get("singleAccountWavefront") or {}
                    prism_data = {
                        "ok": True,
                        "gate": bool(pr.get("gatePass")),
                        "hit_pct": pr.get("cacheHitPct"),
                        "turns": int(pr.get("turnsObserved") or 0),
                        "edits": int(pr.get("prefixEditsObserved") or 0),
                        "saved_tok": int(pr.get("totalSavedTokens") or 0),
                        "saved_wk": float(pr.get("savedWeeklyPct") or 0.0),
                        "sq_hits": int(sqd.get("exactHits") or 0) + int(sqd.get("semanticBurstHits") or 0),
                        "sub_hits": int(pr.get("subconsciousLocalHits") or 0),
                        "cb_hits": int(pr.get("coldBridgeHits") or 0),
                        "cb_on": bool(inv.get("coldBridgeToCodexEnabled")),
                        "sub_on": bool(inv.get("subconsciousLocalEnabled")),
                        "xhigh_ok": not bool(pr.get("effortMutationAllowed")),
                        "wf_sessions": int(wf.get("activeWarmSessions") or 0),
                        "wf_kv": int(wf.get("totalWarmKvTokens") or 0),
                    }
                    self._prism_pulse_cache = prism_data
            except Exception:
                pass

        out = {
            "version": "27.0.0",
            "heartbeat": self._pulse_beat,
            "organism": org_data,
            "prism": prism_data,
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
            "vgpu_ready": vg.get("gpu_ready", False),
            "colab_online": vg.get("colab_online", 0),
            "colab_cu": round(colab_cu, 1),
            "colab_mode": str(cauto.get("mode_label") or "AUTO:SLEEP"),
            "colab_warm_reuses": int(cauto.get("warm_reuses") or 0),
            "colab_auto_reaped": int(cauto.get("auto_reaped") or 0),
            "colab_execs": int(cauto.get("executions") or 0),
            "openai_models_count": oai_cnt,
            "unify_active": self._unify_active_cache,
            "gpu_name": str(gpu.get("name") or "CPU/Peer"),
            "gpu_temp_c": gpu.get("temp_c"),
            "gpu_util_pct": gpu.get("util_pct"),
            "vram_total_mb": gpu.get("vram_total_mb") or 0,
            "vram_used_mb": gpu.get("vram_used_mb") or 0,
            "vram_free_mb": gpu.get("vram_free_mb") or 0,
            "host_cpu_pct": real_cpu,
            "host_free_ram_gb": round(float(hm.get("free_ram_gb") or 0.0), 2),
            "immortal_jobs": self.jobs.stats().get("total_jobs", 0),
            "browser_sessions": self.browser.status().get("active_sessions", 0),
            "zygote_execs": self.zygote.status().get("executions", 0),
            "ghost_runs": self.ghost.status().get("runs", 0),
            "vault_sql_dbs": int(self.vault_sql.status().get("db_count") or 0),
            "hyper_desk": {
                "reclaimed_mb": round(reclaimed_mb, 1),
                "cryo_procs": int(hd.get("cryo_trimmed_procs") or 0) + int(stasis_st.get("active_stasis_pids") or 0),
                "wall_pinned": int(hd.get("silicon_wall_pinned_procs") or 0),
                "orphans": int(hd.get("orphans_reaped") or 0),
                "hydra_mb": round(float(hd.get("hydra_trimmed_mb") or 0.0), 1),
                "vram_yield_ms": round(float(vram_st.get("last_yield_ms") or 0.0), 1),
                "sync_dam": bool(hd.get("sync_dam_active")),
                "autonomic_on": bool((hd.get("autonomic") or {}).get("running")),
                "thermostat_state": str(thermo_st.get("state") or "CRYO_ECO_99"),
                "cpu_cap_pct": int(thermo_st.get("cpu_max_pct") or 100),
            },
            "thermo": {
                "engine_loaded": cosmos is not None,
                "regime": str(thermo_st.get("state") or th.get("regime") or "COOL_LOCAL_HYBRID"),
                "watts": round(float(th.get("est_host_watts") or 0.0), 1),
                "cpu_pct": real_cpu,
                "ssd_save_pct": round(float((th.get("ssd_barrier") or {}).get("write_reduction_pct") or 0.0), 1),
                "zero_env_pct": round(float(zenv.get("dedup_saved_pct") or 0.0), 1),
                "quarantined": len(imm.get("quarantined_actors") or []),
                "ransomware_trips": int(imm.get("ransomware_trips") or 0),
            },
            "omega": {
                "engine_loaded": omega is not None,
                "genome": str(gen.get("codec") or "lz4_simd"),
                "gen": int(gen.get("generation") or 1),
                "score": round(float(gen.get("score") or 0.0), 1),
                "akashic_hits": int(om.get("akashic_hits") or 0),
                "precog_hits": int(om.get("precog_hits") or 0),
                "ctrl_z_depth": int(om.get("ctrl_z_depth") or 0),
            },
            "cartridges": dict(self._cartridge_enabled),
        }
        with self._pulse_cache_lock:
            self._pulse_cache_ts = now_m
            self._pulse_cache_val = dict(out)
        return out

    def handle_get(self, parsed: urllib.parse.ParseResult, headers: Any) -> tuple[int, dict[str, Any]] | None:
        path = parsed.path
        qs = urllib.parse.parse_qs(parsed.query)

        if path in ("/.well-known/chimera.json", "/v1/discover", "/v1/capabilities"):
            return 200, self.capabilities()

        if path == "/v1/smi":
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

        if path == "/v1/egress/pops":
            return 200, {
                "ok": True,
                "pops": self.egress.pop_bandit_stats(),
                "sticky_pins": self.egress.sticky_pin_stats(),
            }

        if path == "/v1/openai/conduit/stats":
            return 200, {"ok": True, "conduit": self.openai_conduit_stats()}

        if path == "/v1/openai/forensics":
            lim = max(1, min(64, int((qs.get("limit") or ["32"])[0] or 32)))
            return 200, {
                "ok": True,
                "conduit": self.openai_conduit_stats(),
                "forensics": self.blackbox.query_forensics(kind="kv_prefix_break", limit=lim),
                "sticky_pins": self.egress.sticky_pin_stats(),
            }

        if path == "/v1/openai/precog/stats":
            return 200, {"ok": True, "precog": self._precog_pool.stats()}

        if path == "/v1/openai/turns":
            lim = max(1, min(64, int((qs.get("limit") or ["20"])[0] or 20)))
            with self._openai_conduit_lock:
                turns = list(reversed(list(self._turn_ledger.values())[-lim:]))
            return 200, {
                "ok": True,
                "turns": turns,
                "checkpoints": self._turn_tm.list_checkpoints(limit=lim),
            }

        if path == "/v1/spore/status":
            st_sp = self._spore.status()
            st_sp["watch"] = self._spore_watcher.status()
            return 200, st_sp

        if path == "/v1/spore/watch":
            return 200, self._spore_watcher.status()

        if path == "/v1/dna/list":
            return 200, {"ok": True, "models": self._dna.list_all()}

        if path == "/v1/dna/rank":
            tc = str((qs.get("task_class") or ["general"])[0] or "general")
            return 200, {"ok": True, "task_class": tc, "ranked": self._dna.rank_models(task_class=tc)}

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
            now_m = time.monotonic()
            with self._openai_models_lock:
                if self._openai_models_cache and (now_m - self._openai_models_ts) < 30.0:
                    return 200, {"object": "list", "data": list(self._openai_models_cache)}

            models: list[dict[str, Any]] = [
                {"id": "chimera-vsa-embed-256", "object": "model", "owned_by": "chimera-vgpu-avx2"},
                {"id": "chimera-cuda-embed", "object": "model", "owned_by": "chimera-colab-elastic"},
                {"id": "chimera-colab-elastic", "object": "model", "owned_by": "chimera-colab-elastic"},
            ]
            gateways = self._discover_openai_gateways(headers)
            import urllib.request as _ur

            opener = _ur.build_opener(_ur.ProxyHandler({}))
            seen = {m["id"] for m in models}
            for base_url, extra_hdrs in gateways:
                murl = f"{base_url}/v1/models" if not base_url.endswith("/v1") else f"{base_url}/models"
                tout = 1.5 if extra_hdrs.get("X-Chimera-OpenAI-Hop") == "1" else 0.45
                try:
                    req_hdrs = dict(extra_hdrs)
                    if headers.get("Authorization"):
                        req_hdrs["Authorization"] = str(headers.get("Authorization"))
                    req = _ur.Request(murl, headers=req_hdrs, method="GET")
                    with opener.open(req, timeout=tout) as r:
                        rem = json.loads(r.read().decode("utf-8"))
                    for item in (rem.get("data") or []):
                        mid = item.get("id")
                        if mid:
                            with self._openai_models_lock:
                                self._openai_model_routes[str(mid)] = (base_url, now_m + 60.0)
                            if mid not in seen:
                                models.append(item)
                                seen.add(mid)
                except Exception:
                    continue
            with self._openai_models_lock:
                self._openai_models_cache = list(models)
                self._openai_models_ts = now_m
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

        if path in ("/v1/pulse", "/v1/pulse/stats"):
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

        if path == "/v1/blackbox/forensics":
            kind = str((qs.get("kind") or [""])[0] or "")
            lim = max(1, min(64, int((qs.get("limit") or ["32"])[0] or 32)))
            return 200, {
                "ok": True,
                "forensics": self.blackbox.query_forensics(kind=kind, limit=lim),
                "stats": self.blackbox.stats(),
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
                return 200, self.vault_sql.export_snapshot(
                    name=name, since_sha256=since_sha, protocol=(qs.get("protocol") or ["1"])[0],
                    target_sha256=(qs.get("target_sha256") or [""])[0],
                    start_page=int((qs.get("start_page") or ["0"])[0]))
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

        # --- v19-v23 CHIMERA-HYPERDESK & PHANTOM-SILICON GET routes ---
        if path == "/v1/hyperdesk/status":
            return 200, self.hyper_desk.status()
        if path == "/v1/hyperdesk/diagnose":
            return 200, self.hyper_desk.diagnose()
        if path == "/v1/hyperdesk/vram/status":
            return 200, {"ok": True, "vram_swap": self.hyper_desk.vram_swap.status()}
        if path == "/v1/hyperdesk/autonomic":
            return 200, self.hyper_desk.get_autonomic_status()
        if path == "/v1/hyperdesk/mirage/status":
            return 200, self.hyper_desk.mirage.status()
        if path == "/v1/hyperdesk/stasis/status":
            return 200, self.hyper_desk.stasis.status()
        if path == "/v1/hyperdesk/gpu-fence":
            return 200, self.hyper_desk.gpu_fence.status()
        if path == "/v1/hyperdesk/pwm/status":
            from ..native import native_focus_state, native_pwm_stats
            return 200, {"ok": True, "pwm": native_pwm_stats(), "focus": native_focus_state()}
        if path == "/v1/hyperdesk/thermostat":
            return 200, self.hyper_desk.thermostat.status()
        if path == "/v1/hyperdesk/soft-shield":
            return 200, self.hyper_desk.apply_soft_batch_shield(dry_run=True)
        if path == "/v1/exile/status":
            probe = (qs.get("probe") or ["0"])[0].lower() in ("1", "true", "yes")
            out = self.hyper_desk.exile.status(probe=probe)
            out["coordinator"] = self.exile_handoff.status()
            return 200, out
        if path == "/v1/exile/receipts":
            jid = (qs.get("job_id") or [""])[0].strip() or None
            lim = max(1, min(500, int((qs.get("limit") or ["50"])[0] or 50)))
            return 200, {
                "ok": True,
                "receipts": self.exile_handoff.receipts(job_id=jid, limit=lim),
                "coordinator": self.exile_handoff.status(),
                "jobs_stats": self.jobs.stats(),
            }
        if path == "/v1/truth-matrix":
            return 200, self.evidence.truth_matrix({"connect": True, **self._cartridge_enabled})
        if path == "/v1/evidence":
            cap = (qs.get("capability") or qs.get("cap") or [""])[0].strip()
            if cap:
                en = True if cap == "connect" else bool(self._cartridge_enabled.get(cap, True))
                return 200, {
                    "ok": True,
                    "capability": cap,
                    "evidence": self.evidence.evaluate(cap, enabled=en),
                }
            return 200, self.evidence.snapshot({"connect": True, **self._cartridge_enabled}, include_extra=True)

        # --- CHIMERA-ONE Organ 3: Zero-Spawn Agent Hyper-Bus & Symbiont GET routes ---
        if path == "/v1/agent/probe-stats":
            return 200, self.agent_bus.stats()
        if path == "/v1/agent/hive":
            repo_q = (qs.get("repo") or [""])[0] or None
            return 200, self.agent_bus.symbiont.hive.status(repo=repo_q)
        if path == "/v1/agent/precog":
            return 200, self.agent_bus.symbiont.precog.status()
        if path == "/v1/agent/capsule":
            cid = (qs.get("id") or ["latest"])[0]
            repo_q = (qs.get("repo") or [""])[0] or None
            if cid == "list":
                return 200, self.agent_bus.symbiont.capsules.list_capsules(repo=repo_q)
            res_c = self.agent_bus.symbiont.capsules.load(cid, repo=repo_q)
            return (200 if res_c.get("ok") else 404), res_c
        if path == "/v1/agent/bootstrap":
            repo_q = (qs.get("repo") or ["."])[0]
            aid = (qs.get("agent_id") or ["agent"])[0]
            return 200, self.agent_bus.symbiont.bootstrap_snapshot(repo_q, agent_id=aid)
        if path == "/v1/agent/coroner":
            return 200, self.agent_bus.symbiont.coroner.scan(auto_seed_immune=False)
        if path == "/v1/agent/worktree-epoch":
            rel_q = (qs.get("release_dir") or [""])[0] or None
            return 200, self.agent_bus.symbiont.worktree_epoch.epoch_status(rel_q)
        if path == "/v1/agent/release-promote":
            return 200, self.agent_bus.symbiont.release_promote.status()
        if path == "/v1/darwin/status":
            return 200, self.agent_bus.symbiont.darwin.status()
        if path == "/v1/darwin/genome":
            gid = (qs.get("genome_id") or [""])[0].strip()
            if gid:
                res_g = self.agent_bus.symbiont.darwin.dispatch("genome_export", genome_id=gid)
                return (200 if res_g.get("ok") else 404), res_g
            return 200, self.agent_bus.symbiont.darwin.dispatch("genome_list")
        if path == "/v1/aeon/status":
            return 200, self.agent_bus.symbiont.aeon.status()
        if path == "/v1/noosphere/status":
            return 200, self.agent_bus.symbiont.noosphere.status()
        if path == "/v1/noosphere/workspace":
            lim_raw = (qs.get("limit") or ["16"])[0]
            lim = int(lim_raw) if lim_raw.isdigit() else 16
            kind = (qs.get("kind") or [""])[0].strip() or None
            return 200, self.agent_bus.symbiont.noosphere.dispatch("workspace", limit=lim, kind=kind)
        if path == "/v1/noosphere/epiphany":
            return 200, self.agent_bus.symbiont.noosphere.dispatch("epiphany")
        if path == "/v1/noosphere/deploy-gate":
            svc = (qs.get("service") or ["tquota"])[0]
            return 200, self.agent_bus.symbiont.eidolon.dispatch("deploy_gate", service=svc)
        if path == "/v1/noosphere/panopticon":
            return 200, self.agent_bus.symbiont.eidolon.dispatch("panopticon")
        if path == "/v1/eidolon/status":
            return 200, self.agent_bus.symbiont.eidolon.status()

        # --- CHIMERA-MNEMOSYNE (Unified Zero-Loss Raw-Memory & Zero-Shell Execution) GET routes ---
        if path == "/v1/mnemosyne/status":
            return 200, self.agent_bus.symbiont.mnemosyne.status()
        if path == "/v1/mnemosyne/entropy-audit":
            return 200, self.agent_bus.symbiont.mnemosyne.dispatch("entropy_audit")
        if path == "/v1/mnemosyne/watchdog":
            return 200, self.agent_bus.symbiont.mnemosyne.dispatch("swarm_watchdog")
        if path == "/v1/agent/prime":
            repo_q = (qs.get("repo") or [""])[0]
            cid_q = (qs.get("cid") or qs.get("conversation_id") or ["agent"])[0]
            inc_raw = (qs.get("include_raw_recall") or ["1"])[0].lower() not in ("0", "false", "no")
            return 200, self.agent_bus.symbiont.mnemosyne.dispatch(
                "prime", repo=repo_q, cid=cid_q, include_raw_recall=inc_raw
            )

        # --- CHIMERA-PROMETHEUS (Waves 1-3 Empirical Evolution) GET routes ---
        if path == "/v1/prometheus" or path.startswith("/v1/prometheus/"):
            pr = self.prometheus
            if path in ("/v1/prometheus", "/v1/prometheus/status"):
                return 200, pr.status()
            if path == "/v1/prometheus/axioms":
                st_f = (qs.get("status") or [None])[0]
                return 200, pr.dispatch("axioms", filter_status=st_f)
            if path == "/v1/prometheus/epoch/status":
                return 200, pr.dispatch("epoch_status")
            if path == "/v1/prometheus/epoch/worktrees":
                repo_q = (qs.get("repo") or ["."])[0]
                return 200, pr.dispatch("worktrees", repo=repo_q, execute_prune=False)
            if path == "/v1/prometheus/galileo/status":
                return 200, pr.dispatch("galileo_status")
            if path == "/v1/prometheus/oracle/probe":
                repo_q = (qs.get("repo_dir") or [None])[0]
                rel_q = (qs.get("release_dir") or [None])[0]
                return 200, pr.dispatch("oracle_probe", repo_dir=repo_q, release_dir=rel_q)
            if path == "/v1/prometheus/oracle/brief":
                repo_q = (qs.get("repo_dir") or [None])[0]
                return 200, pr.dispatch("morning_brief", repo_dir=repo_q)
            if path == "/v1/prometheus/ghost/status":
                return 200, pr.dispatch("ghost_status")
            if path == "/v1/prometheus/spine/status":
                return 200, pr.dispatch("spine_status")
            return 404, {"ok": False, "error": f"unknown_prometheus_route:{path}"}

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

        # --- CHIMERA-BIOS Open Ecosystem Soul GET routes (100% lazy-loaded, 0 B boot RSS) ---
        if path == "/v1/bios" or path.startswith("/v1/bios/"):
            if not self._cartridge_enabled.get("bios", True):
                return 503, {"error": "cartridge_disabled:bios"}
            if path in ("/v1/bios", "/v1/bios/status"):
                return 200, self.bios.status()
            if path == "/v1/bios/abi":
                return 200, self.bios.open_abi_manifest(anchor_url=self.anchor_url)
            if path == "/v1/bios/hormones":
                return 200, self.bios.hormones()
            if path == "/v1/bios/autophagy":
                return 200, self.bios.autophagy_dispatch(action="status")
            if path == "/v1/bios/parasite/status":
                return 200, self.bios.parasite_status()
            if path == "/v1/bios/ganglia":
                return 200, self.bios.ganglia_status()
            if path == "/v1/bios/pheromone":
                repo_q = (qs.get("repo") or ["."])[0]
                rel_q = (qs.get("rel_path") or qs.get("path") or [""])[0]
                max_tok_raw = (qs.get("max_tokens") or ["40"])[0]
                max_tok = int(max_tok_raw) if max_tok_raw.isdigit() else 40
                return 200, self.bios.pheromone(repo=repo_q, rel_path=rel_q, max_tokens=max_tok)
            if path == "/v1/bios/umwelt":
                return 200, self.bios.umwelt_dispatch(action="status")
            if path == "/v1/bios/hgt":
                tag_q = (qs.get("tag") or [""])[0].strip() or None
                return 200, self.bios.hgt_dispatch(action="list", payload={"tag": tag_q})
            if path == "/v1/bios/spores":
                return 200, self.bios.spores_list()
            if path == "/v1/bios/soul":
                q_s = (qs.get("query") or qs.get("q") or [""])[0]
                mdl = (qs.get("target_model") or qs.get("model") or ["any"])[0]
                mt_raw = (qs.get("max_tokens") or ["500"])[0]
                mt = int(mt_raw) if mt_raw.isdigit() else 500
                return 200, self.bios.soul_capsule(query=q_s, target_model=mdl, max_tokens=mt)
            if path == "/v1/bios/sync/bundle":
                me_raw = (qs.get("max_events") or ["32"])[0]
                ma_raw = (qs.get("max_alarms") or ["16"])[0]
                ms_raw = (qs.get("max_scars") or ["16"])[0]
                return 200, self.bios.export_sync_bundle(
                    max_events=int(me_raw) if me_raw.isdigit() else 32,
                    max_alarms=int(ma_raw) if ma_raw.isdigit() else 16,
                    max_scars=int(ms_raw) if ms_raw.isdigit() else 16,
                )

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

        if sys.platform.startswith("linux") and path.startswith("/v1/agent/"):
            # A forwarded loopback request has the daemon's privileges, not a guest
            # cgroup. Delegate build/test execution to the existing reserved worker.
            needs_guest = path in {"/v1/agent/exec", "/v1/agent/commit-verify",
                                   "/v1/agent/atomic-patch", "/v1/agent/mirror-race"}
            if path == "/v1/agent/run-dag":
                steps = body.get("steps") or []
                needs_guest = isinstance(steps, list) and any(
                    isinstance(step, dict) and str(step.get("kind", "")).strip().lower()
                    in {"exec", "verify", "patch"} for step in steps
                )
            if path == "/v1/agent/precog":
                needs_guest = str(body.get("action") or "").strip().lower() in {"watch_start", "notify_save"}
            if needs_guest:
                from .peer_guard import guarded_build_required

                return 409, guarded_build_required()
            if path == "/v1/agent/release-promote":
                action = str(body.get("action") or "status").strip().lower()
                if action == "rollback" or (action == "promote" and body.get("dry_run") is not True):
                    # Only the maintenance rollout switches the serving release on this node.
                    return 409, {"ok": False, "state": "deferred", "error": "release_maintenance_required",
                                 "queue": {"stored": False}}

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

        if path in ("/v1/openai/turn/checkpoint", "/v1/openai/turn/finalize", "/v1/openai/turn/rollback"):
            if client_ip not in ("127.0.0.1", "::1", "localhost"):
                return 403, {"error": "loopback_only"}
            tid = str(body.get("turn_id") or "").strip()
            if not tid:
                return 400, {"error": "missing_turn_id"}
            try:
                if path == "/v1/openai/turn/checkpoint":
                    res = self._turn_tm.checkpoint_turn(
                        tid,
                        str(body.get("root") or "."),
                        list(body.get("rel_paths") or []),
                        meta=body.get("meta") if isinstance(body.get("meta"), dict) else None,
                    )
                    with self._openai_conduit_lock:
                        if tid in self._turn_ledger:
                            self._turn_ledger[tid]["checkpointed"] = True
                    return 200, res
                if path == "/v1/openai/turn/finalize":
                    res = self._turn_tm.finalize_turn(tid)
                    return (200 if res.get("ok") else 404), res
                res = self._turn_tm.rollback_turn(tid, force=bool(body.get("force", False)))
                if res.get("ok"):
                    with self._openai_conduit_lock:
                        if tid in self._turn_ledger:
                            self._turn_ledger[tid]["rolled_back"] = True
                    try:
                        self.pulse.publish("llm.turn_rollback", res, app="hydra-conduit", relay=False)
                    except Exception:
                        pass
                return (200 if res.get("ok") else 409), res
            except ValueError as exc:
                return 400, {"error": str(exc)}

        if path in ("/v1/spore/distill", "/v1/spore/pack", "/v1/spore/hatch", "/v1/spore/engram", "/v1/spore/screen", "/v1/spore/watch"):
            if path != "/v1/spore/screen" and client_ip not in ("127.0.0.1", "::1", "localhost"):
                return 403, {"error": "loopback_only"}
            try:
                if path == "/v1/spore/watch":
                    w_act = str(body.get("action") or "status").lower()
                    if w_act in ("tick", "sync", "sync_now"):
                        coroner_cb = None
                        if bool(body.get("run_coroner", True)) and self._agent_bus is not None and hasattr(self._agent_bus, "symbiont"):
                            coroner_cb = lambda: self._agent_bus.symbiont.coroner.scan(auto_seed_immune=True)
                        return 200, self._spore_watcher.tick_if_due(
                            force=bool(body.get("force", True)),
                            coroner_fn=coroner_cb,
                            node_name=str(self.daemon.config.node_name),
                            pulse_fn=lambda topic, payload: self.pulse.publish(topic, payload, app="spore-watcher", relay=False),
                        )
                    if w_act == "add_source":
                        res_a = self._spore_watcher.add_source(str(body.get("path") or ""), kind=str(body.get("kind") or "lesson"))
                        return (200 if res_a.get("ok") else 400), res_a
                    if w_act == "remove_source":
                        return 200, self._spore_watcher.remove_source(str(body.get("path") or ""))
                    if w_act in ("enable", "disable", "configure"):
                        return 200, self._spore_watcher.configure(
                            enabled=(True if w_act == "enable" else (False if w_act == "disable" else (body.get("enabled") if "enabled" in body else None))),
                            interval_s=(float(body["interval_s"]) if body.get("interval_s") is not None else None),
                            auto_pack=(bool(body["auto_pack"]) if "auto_pack" in body else None),
                            auto_coroner=(bool(body["auto_coroner"]) if "auto_coroner" in body else None),
                        )
                    return 200, self._spore_watcher.status()
                if path == "/v1/spore/screen":
                    qg = QuarantineGuard.from_policy_file(body["policy_file"]) if body.get("policy_file") else self._spore.quarantine
                    return 200, qg.screen_text(str(body.get("text") or ""), source_path=str(body.get("source_path") or ""))
                if path == "/v1/spore/distill":
                    return 200, self._spore.distill_to_local(
                        extra_lessons_paths=list(body.get("lessons") or []),
                        policy_file=(str(body["policy_file"]) if body.get("policy_file") else None),
                    )
                if path == "/v1/spore/pack":
                    sp = Path(str(body["path"])) if body.get("path") else (self._spore.chimera_dir / "chimera.spore")
                    return 200, self._spore.pack(
                        sp,
                        extra_lessons_paths=list(body.get("lessons") or []),
                        policy_file=(str(body["policy_file"]) if body.get("policy_file") else None),
                        passphrase=str(body.get("passphrase") or ""),
                        node_name=str(self.daemon.config.node_name),
                    )
                if path == "/v1/spore/hatch":
                    sp = Path(str(body["path"])) if body.get("path") else (self._spore.chimera_dir / "chimera.spore")
                    res = self._spore.hatch(
                        sp,
                        target_chimera_dir=(Path(str(body["target_dir"])) if body.get("target_dir") else None),
                        passphrase=str(body.get("passphrase") or ""),
                        dry_run=bool(body.get("dry_run", False)),
                    )
                    if res.get("ok") and not body.get("dry_run") and not body.get("target_dir"):
                        self._dna._load()
                    return 200, res
                return 200, self._spore.record_engram(
                    str(body.get("title") or "engram"),
                    str(body.get("body") or body.get("text") or ""),
                    kind=str(body.get("kind") or "lesson"),
                    tags=list(body.get("tags") or []),
                    proof_receipt=(body.get("proof_receipt") if isinstance(body.get("proof_receipt"), dict) else None),
                )
            except (ValueError, PermissionError, OSError) as exc:
                return 400, {"error": str(exc)}

        if path in ("/v1/dna/scan", "/v1/dna/classify", "/v1/dna/sanitize", "/v1/dna/durability"):
            if path == "/v1/dna/classify":
                return 200, classify_response(str(body.get("text") or ""), marker=str(body.get("marker") or ""))
            if path == "/v1/dna/sanitize":
                return 200, sanitize_prompt(str(body.get("text") or ""))
            if path == "/v1/dna/durability":
                return 200, audit_instruction_durability(
                    str(body.get("path") or ""),
                    measured_lift=(float(body["measured_lift"]) if body.get("measured_lift") is not None else None),
                    pinned_sha256=str(body.get("pinned_sha256") or ""),
                )
            if client_ip not in ("127.0.0.1", "::1", "localhost"):
                return 403, {"error": "loopback_only"}
            base_u = str(body.get("base_url") or "").strip()
            mdl = str(body.get("model") or "").strip()
            if not base_u or not mdl:
                return 400, {"error": "missing_base_url_or_model"}
            dna = ct_scan(
                base_u,
                mdl,
                api_key=str(body.get("api_key") or ""),
                protocol=str(body.get("protocol") or "openai"),
                mode=str(body.get("mode") or "quick"),
                timeout_s=float(body.get("timeout_s") or 25.0),
            )
            return 200, self._dna.upsert(dna)

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
            model_name = str(body.get("model") or "")
            gateways = self._discover_openai_gateways(headers, model=model_name)
            candidates: list[tuple[str, dict[str, str]]] = [
                (f"{base}{sub_ep}", extra) for base, extra in gateways
            ]
            import urllib.error as _ue
            import urllib.request as _ur

            opener = _ur.build_opener(_ur.ProxyHandler({}))
            base_hdrs = {"Content-Type": "application/json"}
            if headers.get("Authorization"):
                base_hdrs["Authorization"] = str(headers.get("Authorization"))
            last_err = ""
            for target_url, extra_hdrs in candidates:
                try:
                    hdrs = {**base_hdrs, **extra_hdrs}
                    req = _ur.Request(target_url, data=raw_body, headers=hdrs, method="POST")
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
            return 503, {"error": f"openai_relay_unavailable:{last_err}", "hint": "Ensure a local OpenAI gateway is linked (needs=['openai']) or tquota (:12500) is active."}

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
            return 200, self.vgpu.run_ptx_benchmark(
                int(body.get("n") or 16384), force=bool(body.get("force", False))
            )

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
            if path == "/v1/hyperdesk/soft-shield":
                if str(body.get("action") or "apply").strip().lower() == "restore":
                    return 200, self.hyper_desk.restore_soft_batch_shield()
                return 200, self.hyper_desk.apply_soft_batch_shield(
                    promote_vips=bool(body.get("promote_vips", True)),
                    demote_batch=bool(body.get("demote_batch", True)),
                    extra_batch_pids=(list(body["extra_batch_pids"]) if isinstance(body.get("extra_batch_pids"), list) else None),
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
            if path == "/v1/hyperdesk/autonomic":
                action = str(body.get("action") or "").strip().lower()
                if action == "on":
                    return 200, self.hyper_desk.start_autonomic()
                if action == "off":
                    return 200, self.hyper_desk.stop_autonomic(restore_defaults=bool(body.get("restore_defaults", True)))
                if action == "tick":
                    return 200, self.hyper_desk.autonomic_tick_once(
                        force_patrol=bool(body.get("force_patrol", True)),
                        force_orphan=bool(body.get("force_orphan", False)),
                        dry_run=bool(body.get("dry_run", False)),
                    )
                if isinstance(body.get("policy"), dict):
                    try:
                        return 200, self.hyper_desk.update_autonomic_policy(body["policy"])
                    except ValueError as exc:
                        return 400, {"ok": False, "error": str(exc)}
                return 200, self.hyper_desk.get_autonomic_status()
            if path == "/v1/hyperdesk/mirage/promote":
                return 200, self.hyper_desk.mirage.promote(
                    str(body.get("path") or ""),
                    max_repo_gb=float(body.get("max_repo_gb") or 8.0),
                    dry_run=bool(body.get("dry_run", False)),
                )
            if path == "/v1/hyperdesk/mirage/demote":
                return 200, self.hyper_desk.mirage.demote(str(body.get("path") or ""))
            if path == "/v1/hyperdesk/mirage/sync":
                p = body.get("path")
                return 200, self.hyper_desk.mirage.sync_back(str(p) if p else None)
            if path == "/v1/hyperdesk/mirage/bench":
                return 200, self.hyper_desk.mirage.benchmark_dir(
                    str(body.get("path") or "."),
                    max_files=int(body.get("max_files") or 200),
                )
            if path == "/v1/hyperdesk/stasis/hibernate":
                return 200, self.hyper_desk.stasis_hibernate(
                    min_ws_mb=float(body.get("min_ws_mb") or 20.0),
                    dry_run=bool(body.get("dry_run", False)),
                )
            if path == "/v1/hyperdesk/stasis/wake":
                app_nm = str(body.get("app") or "")
                if app_nm:
                    return 200, self.hyper_desk.stasis.wake_family(app_name=app_nm)
                return 200, self.hyper_desk.stasis.wake_all()
            if path == "/v1/hyperdesk/gpu-phoenix":
                return 200, self.hyper_desk.gpu_phoenix(
                    threshold_commit_mb=float(body.get("threshold_commit_mb") or 1600.0),
                    allow_recycle=bool(body.get("allow_recycle", False)),
                )
            if path == "/v1/hyperdesk/gpu-fence":
                return 200, self.hyper_desk.gpu_fence.apply_fence(
                    overwrite_existing=bool(body.get("overwrite_existing", False)),
                    dry_run=bool(body.get("dry_run", False)),
                )
            if path == "/v1/hyperdesk/thermostat":
                mode = str(body.get("mode") or "").strip().lower()
                if mode:
                    if self.hyper_desk.aether_active and mode != "turbo_100":
                        return 409, {"ok": False, "error": "Aether leaves CPU scheduling and boost to Windows"}
                    try:
                        res = self.hyper_desk.thermostat.set_mode(mode)
                        self.hyper_desk.update_autonomic_policy({"thermostat_mode": mode})
                        return 200, res
                    except ValueError as exc:
                        return 400, {"error": str(exc)}
                return 200, self.hyper_desk.thermostat.status()

        if path == "/v1/exile/run":
            if client_ip not in ("127.0.0.1", "::1", "localhost"):
                return 403, {"error": "submit_exile_through_local_anchor"}
            if not self._cartridge_enabled.get("hyper_desk", True):
                return 503, {"error": "cartridge_disabled:hyper_desk"}
            duration = body.get("timeout_s", 120)
            if type(duration) not in (int, float) or not 1 <= duration <= 300:
                return 400, {"error": "invalid_build_timeout"}
            return 200, self.hyper_desk.exile.run(
                str(body.get("cmd") or ""),
                cwd=body.get("cwd") or None,
                target=str(body.get("target") or "auto"),
                sync_workspace=bool(body.get("sync_workspace", False)),
                timeout_s=duration,
                environment_id=body.get("environment_id", ""),
                reuse=body.get("reuse") is True,
                artifacts=body.get("artifacts", []),
                require_io_limit=body.get("require_io_limit") is True,
            )

        if path == "/v1/exile/handoff":
            if not self._cartridge_enabled.get("immortal_jobs", True):
                return 503, {"error": "cartridge_disabled:immortal_jobs"}
            pref = body.get("prefer_target")
            if isinstance(pref, str) and pref.strip().lower() in ("", "auto"):
                pref = None

            def _decode_block(value: Any) -> bytes:
                if not isinstance(value, dict):
                    return value if isinstance(value, bytes) else str(value).encode("utf-8")
                encoded = value.get("b64", value.get("base64"))
                if (not isinstance(encoded, str) or
                        ("base64" in value and value["base64"] != encoded)):
                    raise ValueError("a binary block requires one unambiguous base64 string")
                # Keep accepting wrapped base64 while rejecting mistyped or damaged data.
                return base64.b64decode(b"".join(encoded.encode("ascii").split()), validate=True)

            def _decode_blocks(raw_blocks: Any) -> dict[str, bytes] | list[bytes] | None:
                if raw_blocks is None:
                    return None
                if isinstance(raw_blocks, dict):
                    return {str(k): _decode_block(v) for k, v in raw_blocks.items()}
                if isinstance(raw_blocks, list):
                    return [_decode_block(v) for v in raw_blocks]
                raise ValueError("blocks must be an object or list")

            try:
                raw_steps = body.get("steps")
                if raw_steps is None:
                    steps = [{
                        "step_key": str(body.get("step_key") or "step_0"),
                        "step_index": int(body.get("step_index") or 0),
                        "payload": body.get("payload"),
                        "blocks": _decode_blocks(body.get("blocks")),
                        "op": str(body.get("op") or "sha256_manifest"),
                        "params": body.get("params") if isinstance(body.get("params"), dict) else {},
                        "block_size": int(body.get("block_size") or 4096),
                        "prefer_target": pref,
                    }]
                else:
                    if not isinstance(raw_steps, list) or not raw_steps:
                        return 400, {"ok": False, "error": "steps_must_be_non_empty_list"}
                    steps = []
                    for idx, sp in enumerate(raw_steps):
                        if not isinstance(sp, dict):
                            return 400, {"ok": False, "error": f"step_{idx}_must_be_object"}
                        sp_copy = dict(sp)
                        if "blocks" in sp_copy:
                            sp_copy["blocks"] = _decode_blocks(sp_copy.get("blocks"))
                        steps.append(sp_copy)
                res = self.exile_handoff.handoff_job(
                    steps,
                    job_id=body.get("job_id") or None,
                    app=str(body.get("app") or headers.get("X-Chimera-App") or "exile"),
                    name=str(body.get("name") or "exile_handoff"),
                    meta=body.get("meta") if isinstance(body.get("meta"), dict) else None,
                    max_retries=int(body["max_retries"]) if body.get("max_retries") is not None else None,
                    prefer_target=pref,
                )
                queued = res.get("queue") or {}
                if res.get("state") in ("deferred", "indeterminate") and queued.get("stored") and queued.get("id"):
                    return 202, res
                return (200 if res.get("ok") else 502), res
            except (ValueError, KeyError, TypeError) as exc:
                return 400, {"ok": False, "error": str(exc)}
            except Exception as exc:
                return 502, {"ok": False, "error": str(exc)}

        if path == "/v1/evidence/record":
            if client_ip not in ("127.0.0.1", "::1", "localhost"):
                return 403, {"error": "loopback_only"}
            cap = str(body.get("capability") or "").strip()
            if not cap:
                return 400, {"ok": False, "error": "capability_required"}
            try:
                entry = self.evidence.record(
                    cap,
                    execution_node=str(body.get("execution_node") or self.daemon.config.node_name),
                    fallback_mode=body.get("fallback_mode"),
                    ttl_s=float(body.get("ttl_s") if body.get("ttl_s") is not None else 300.0),
                    verified=bool(body.get("verified", True)),
                    violated=bool(body.get("violated", False)),
                    metrics=body.get("metrics") if isinstance(body.get("metrics"), dict) else None,
                    receipt_id=body.get("receipt_id"),
                )
                en = True if cap == "connect" else bool(self._cartridge_enabled.get(cap, True))
                return 200, {
                    "ok": True,
                    "entry": entry,
                    "evaluated": self.evidence.evaluate(cap, enabled=en),
                }
            except (TypeError, ValueError) as exc:
                return 400, {"ok": False, "error": str(exc)}

        # --- CHIMERA-ONE Organ 3: Zero-Spawn Agent Hyper-Bus POST routes (loopback only) ---
        if path.startswith("/v1/agent/"):
            if client_ip not in ("127.0.0.1", "::1", "localhost"):
                return 403, {"ok": False, "error": "loopback_only"}
            if path == "/v1/agent/xray-batch":
                ops = body.get("ops")
                if not isinstance(ops, list) or not ops:
                    return 400, {"ok": False, "error": "ops_must_be_non_empty_list"}
                res = self.agent_bus.xray_batch(
                    ops,
                    cwd=body.get("cwd") or None,
                    max_workers=int(body.get("max_workers") or 8),
                    compact=bool(body.get("compact", True)),
                    agent_id=str(body.get("agent_id") or ""),
                )
                self._observe_activity("agent.xray_batch", res["ok"], res["ops_count"])
                try:
                    self.daemon.record_flow(
                        "compute",
                        "agent",
                        "akashic-bus",
                        "XRAY_BATCH",
                        detail=f"ops={res.get('ops_count', 0)} ok={res.get('ok_count', 0)} ps=0",
                        ms=float(res.get("elapsed_ms") or 0.0),
                        ok=bool(res.get("ok")),
                    )
                except Exception:
                    pass
                return 200, res
            if path == "/v1/agent/callgraph-slice":
                repo = str(body.get("repo") or ".").strip()
                symbol = str(body.get("symbol") or "").strip()
                if not symbol:
                    return 400, {"ok": False, "error": "symbol_required"}
                res = self.agent_bus.callgraph_slice(
                    repo,
                    symbol,
                    depth=int(body.get("depth") if body.get("depth") is not None else 2),
                    include_tests=bool(body.get("include_tests", True)),
                    max_chars=int(body.get("max_chars") or 4500),
                )
                try:
                    self.daemon.record_flow(
                        "compute",
                        "agent",
                        "callgraph",
                        "CALLGRAPH_SLICE",
                        detail=f"sym={symbol[:28]} chars={res.get('chars_used', 0)}",
                        ms=float(res.get("elapsed_ms") or 0.0),
                        ok=bool(res.get("ok")),
                    )
                except Exception:
                    pass
                return (200 if res.get("ok") else 404), res
            if path == "/v1/agent/commit-verify":
                repo = str(body.get("repo") or ".").strip()
                res = self.agent_bus.commit_verify(
                    repo,
                    files=(list(body["files"]) if isinstance(body.get("files"), list) else None),
                    run_tests=bool(body.get("run_tests", True)),
                    explicit_tests=(list(body["explicit_tests"]) if isinstance(body.get("explicit_tests"), list) else None),
                    max_tests=int(body.get("max_tests") or 4),
                    timeout_s=float(body.get("timeout_s") or 60.0),
                    use_cache=bool(body.get("use_cache", True)),
                    compact=bool(body.get("compact", True)),
                )
                try:
                    self.daemon.record_flow(
                        "compute",
                        "agent",
                        "verify",
                        "COMMIT_VERIFY",
                        detail=f"files={res.get('files_checked', 0)} hit={res.get('cache_hit', False)}",
                        ms=float(res.get("elapsed_ms") or 0.0),
                        ok=bool(res.get("ok")),
                    )
                except Exception:
                    pass
                return 200, res
            if path == "/v1/agent/hive":
                act = str(body.get("action") or "status").strip().lower()
                hive = self.agent_bus.symbiont.hive
                if act == "lease":
                    return 200, hive.acquire_lease(
                        agent_id=str(body.get("agent_id") or "agent"),
                        repo=str(body.get("repo") or "."),
                        files=(list(body["files"]) if isinstance(body.get("files"), list) else []),
                        intent=str(body.get("intent") or ""),
                        action=str(body.get("lease_action") or "edit"),
                        ttl_s=float(body.get("ttl_s") or 120.0),
                    )
                if act == "release":
                    return 200, hive.release_lease(
                        agent_id=str(body.get("agent_id") or "agent"),
                        repo=(str(body["repo"]) if body.get("repo") else None),
                    )
                if act == "immune_add":
                    return 200, hive.add_immune_rule(
                        pattern=str(body.get("pattern") or ""),
                        warning=str(body.get("warning") or ""),
                        scope=str(body.get("scope") or "global"),
                        severity=str(body.get("severity") or "warn"),
                        created_by=str(body.get("agent_id") or "agent"),
                    )
                if act == "immune_list":
                    return 200, {"ok": True, "rules": hive.list_immune(limit=int(body.get("limit") or 32))}
                if act == "mutate":
                    hive.record_mutation(
                        agent_id=str(body.get("agent_id") or "agent"),
                        repo=str(body.get("repo") or "."),
                        files=(list(body["files"]) if isinstance(body.get("files"), list) else []),
                        kind=str(body.get("kind") or "edit"),
                        detail=str(body.get("detail") or ""),
                    )
                    return 200, {"ok": True}
                return 200, hive.status(repo=(str(body["repo"]) if body.get("repo") else None))
            if path == "/v1/agent/atomic-patch":
                res = self.agent_bus.symbiont.surgeon.atomic_patch(
                    str(body.get("repo") or "."),
                    list(body.get("edits") or []),
                    agent_id=str(body.get("agent_id") or "agent"),
                    run_tests=bool(body.get("run_tests", True)),
                    explicit_tests=(list(body["explicit_tests"]) if isinstance(body.get("explicit_tests"), list) else None),
                    rollback_on_fail=bool(body.get("rollback_on_fail", True)),
                    max_tests=int(body.get("max_tests") or 4),
                    timeout_s=float(body.get("timeout_s") or 60.0),
                    record_immune_on_gate_fail=bool(body.get("record_immune_on_gate_fail", False)),
                )
                try:
                    self.daemon.record_flow(
                        "compute",
                        "agent",
                        "surgeon",
                        "ATOMIC_PATCH",
                        detail=f"committed={res.get('committed')} gate_rej={res.get('gate_rejected')} rb={res.get('rolled_back')}",
                        ms=float(res.get("elapsed_ms") or 0.0),
                        ok=bool(res.get("ok")),
                    )
                except Exception:
                    pass
                return 200, res
            if path == "/v1/agent/precog":
                act = str(body.get("action") or "status").strip().lower()
                precog = self.agent_bus.symbiont.precog
                if act == "notify_save":
                    return 200, precog.notify_save(
                        str(body.get("repo") or "."),
                        list(body.get("files") or body.get("rel_paths") or []),
                        run_shadow_test=bool(body.get("run_shadow_test", True)),
                        explicit_tests=(list(body["explicit_tests"]) if isinstance(body.get("explicit_tests"), list) else None),
                        max_tests=int(body.get("max_tests") or 2),
                        timeout_s=float(body.get("timeout_s") or 25.0),
                        agent_id=str(body.get("agent_id") or "precog"),
                    )
                if act == "watch_start":
                    return 200, precog.start_watch(
                        str(body.get("repo") or "."),
                        run_shadow_test=bool(body.get("run_shadow_test", True)),
                    )
                if act == "watch_stop":
                    return 200, precog.stop_watch(str(body["repo"]) if body.get("repo") else None)
                if act == "prefetch_paths":
                    return 200, precog.prefetch_paths(
                        list(body.get("paths") or []),
                        max_bytes_per_file=int(body.get("max_bytes_per_file") or 65536),
                        warm_cache=bool(body.get("warm_cache", True)),
                    )
                return 200, precog.status()
            if path == "/v1/agent/capsule":
                act = str(body.get("action") or "load").strip().lower()
                caps = self.agent_bus.symbiont.capsules
                if act == "create":
                    return 200, caps.create(
                        str(body.get("repo") or "."),
                        agent_id=str(body.get("agent_id") or "agent"),
                        summary=str(body.get("summary") or ""),
                        focus_files=(list(body["focus_files"]) if isinstance(body.get("focus_files"), list) else None),
                        focus_symbols=(list(body["focus_symbols"]) if isinstance(body.get("focus_symbols"), list) else None),
                        next_steps=(list(body["next_steps"]) if isinstance(body.get("next_steps"), list) else None),
                        include_git=bool(body.get("include_git", True)),
                    )
                if act == "list":
                    return 200, caps.list_capsules(
                        repo=(str(body["repo"]) if body.get("repo") else None),
                        limit=int(body.get("limit") or 10),
                    )
                res_c = caps.load(
                    str(body.get("capsule_id") or "latest"),
                    repo=(str(body["repo"]) if body.get("repo") else None),
                )
                return (200 if res_c.get("ok") else 404), res_c
            if path == "/v1/agent/bootstrap":
                return 200, self.agent_bus.symbiont.bootstrap_snapshot(
                    str(body.get("repo") or "."),
                    agent_id=str(body.get("agent_id") or "agent"),
                )
            if path == "/v1/agent/mirror-race":
                if body.get("offload_peer"):
                    from .peer_guard import guarded_build_required

                    return 409, guarded_build_required()
                res = self.agent_bus.symbiont.mirror_race.race(
                    str(body.get("repo") or "."),
                    list(body.get("candidates") or []),
                    explicit_tests=(list(body["explicit_tests"]) if isinstance(body.get("explicit_tests"), list) else None),
                    commit_winner=bool(body.get("commit_winner", True)),
                    max_tests=int(body.get("max_tests") or 4),
                    timeout_s=float(body.get("timeout_s") or 45.0),
                    agent_id=str(body.get("agent_id") or "agent"),
                    offload_peer=bool(body.get("offload_peer", False)),
                    peer_host=str(body.get("peer_host") or "svhome"),
                    peer_repo=(str(body["peer_repo"]) if body.get("peer_repo") else None),
                    generations=int(body.get("generations") or 1),
                )
                try:
                    self.daemon.record_flow(
                        "compute",
                        "agent",
                        "mirror-race",
                        "MIRROR_RACE",
                        detail=f"winner={res.get('winner_id')} n={res.get('candidates_tested')}",
                        ms=float(res.get("elapsed_ms") or 0.0),
                        ok=bool(res.get("ok")),
                    )
                except Exception:
                    pass
                return 200, res
            if path == "/v1/agent/coroner":
                return 200, self.agent_bus.symbiont.coroner.scan(
                    log_files=(list(body["log_files"]) if isinstance(body.get("log_files"), list) else None),
                    auto_seed_immune=bool(body.get("auto_seed_immune", False)),
                    max_files=int(body.get("max_files") or 6),
                )
            if path == "/v1/agent/exec":
                return 200, self.agent_bus.symbiont.direct_exec.run(
                    list(body.get("argv") or []),
                    cwd=str(body.get("cwd") or "."),
                    stdin_text=body.get("stdin_text"),
                    normalize_lf=bool(body.get("normalize_lf", True)),
                    env_overrides=(dict(body["env_overrides"]) if isinstance(body.get("env_overrides"), dict) else None),
                    timeout_s=float(body.get("timeout_s") or 60.0),
                    max_preview_chars=int(body.get("max_preview_chars") or 2400),
                )
            if path == "/v1/agent/run-dag":
                res = self.agent_bus.symbiont.macro_dag.run_dag(
                    list(body.get("steps") or []),
                    cwd=str(body.get("cwd") or "."),
                    agent_id=str(body.get("agent_id") or "agent"),
                )
                try:
                    self.daemon.record_flow(
                        "compute",
                        "agent",
                        "macro-dag",
                        "MACRO_DAG",
                        detail=f"steps={res.get('steps_run')} ok={res.get('steps_ok')} saved={res.get('llm_turns_collapsed')}",
                        ms=float(res.get("elapsed_ms") or 0.0),
                        ok=bool(res.get("ok")),
                    )
                except Exception:
                    pass
                return 200, res
            if path == "/v1/agent/worktree-epoch":
                act = str(body.get("action") or "epoch_status").strip().lower()
                we = self.agent_bus.symbiont.worktree_epoch
                if act == "create":
                    return 200, we.create_worktree(
                        str(body.get("repo") or "."),
                        agent_id=str(body.get("agent_id") or "agent"),
                        ref=str(body.get("ref") or "HEAD"),
                        name=(str(body["name"]) if body.get("name") else None),
                    )
                if act == "list":
                    return 200, we.list_worktrees(str(body.get("repo") or "."))
                if act == "remove":
                    return 200, we.remove_worktree(
                        str(body.get("repo") or "."),
                        str(body.get("worktree_path") or ""),
                        force=bool(body.get("force", True)),
                    )
                if act == "epoch_claim":
                    return 200, we.epoch_claim(
                        str(body.get("release_dir") or body.get("repo") or "."),
                        agent_id=str(body.get("agent_id") or "agent"),
                        intent=str(body.get("intent") or ""),
                        ttl_s=float(body.get("ttl_s") or 180.0),
                    )
                if act == "epoch_publish":
                    return 200, we.epoch_publish(
                        str(body.get("release_dir") or body.get("repo") or "."),
                        agent_id=str(body.get("agent_id") or "agent"),
                        files=(list(body["files"]) if isinstance(body.get("files"), list) else []),
                        sha256_map=(dict(body["sha256_map"]) if isinstance(body.get("sha256_map"), dict) else None),
                        verified_summary=str(body.get("verified_summary") or ""),
                        daemon_pid=int(body.get("daemon_pid") or 0),
                    )
                return 200, we.epoch_status(
                    str(body["release_dir"]) if body.get("release_dir") else None
                )
            if path == "/v1/agent/release-promote":
                act = str(body.get("action") or "status").strip().lower()
                rp = self.agent_bus.symbiont.release_promote
                if act == "promote":
                    return 200, rp.promote(
                        str(body.get("source_dir") or "."),
                        str(body.get("target_dir") or "."),
                        list(body.get("files") or []),
                        agent_id=str(body.get("agent_id") or "agent"),
                        snapshot_root=(str(body["snapshot_root"]) if body.get("snapshot_root") else None),
                        canary_imports=(list(body["canary_imports"]) if isinstance(body.get("canary_imports"), list) else None),
                        verified_summary=str(body.get("verified_summary") or ""),
                        dry_run=bool(body.get("dry_run", False)),
                    )
                if act == "rollback":
                    return 200, rp.rollback(
                        epoch_id=(str(body["epoch_id"]) if body.get("epoch_id") else None),
                        rollback_dir=(str(body["rollback_dir"]) if body.get("rollback_dir") else None),
                    )
                return 200, rp.status()

        # --- CHIMERA-DARWIN POST routes (lazy-loaded; Law-6 Shadow-only by default) ---
        if path.startswith("/v1/darwin/"):
            darwin = self.agent_bus.symbiont.darwin
            if path == "/v1/darwin/evolve":
                act = str(body.get("action") or "status").strip().lower()
                # Law 3: Protect svhome 2C/4T from heavy neural training loops unless replay/read-only
                if sys.platform.startswith("linux") and act == "neural_evolve" and int(body.get("generations") or 30) > 10:
                    return 409, {"ok": False, "error": "svhome_neural_training_offload_required", "max_svhome_generations": 10}
                res_d = darwin.dispatch(act, **{k: v for k, v in body.items() if k != "action"})
                return (200 if res_d.get("ok") else 400), res_d
            if path == "/v1/darwin/sleep-cycle":
                res_s = darwin.dispatch("sleep_cycle", **body)
                return 200, res_s

        # --- CHIMERA-DYNAMO / AEON POST routes (100% lazy-loaded, 0 B boot RSS) ---
        if path.startswith("/v1/aeon/"):
            aeon = self.agent_bus.symbiont.aeon
            if path == "/v1/aeon/evolve":
                act = str(body.get("action") or "status").strip().lower()
                res_a = aeon.dispatch(act, **{k: v for k, v in body.items() if k != "action"})
                return (200 if res_a.get("ok") else 400), res_a
            if path == "/v1/aeon/speculate":
                res_sp = aeon.dispatch("sptc_speculate", **body)
                return (200 if res_sp.get("ok") else 400), res_sp

        # --- CHIMERA-NOOSPHERE Living Organism POST routes ---
        if path.startswith("/v1/noosphere/"):
            noo = self.agent_bus.symbiont.noosphere
            if path == "/v1/noosphere/dispatch":
                act = str(body.get("action") or "status").strip().lower()
                res_n = noo.dispatch(act, **{k: v for k, v in body.items() if k != "action"})
                return (200 if res_n.get("ok") else 400), res_n
            if path == "/v1/noosphere/tick":
                res_t = noo.dispatch("tick", **body)
                return (200 if res_t.get("ok") else 400), res_t
            if path == "/v1/noosphere/dream":
                res_d = noo.dispatch("dream", **body)
                return (200 if res_d.get("ok") else 400), res_d
            if path == "/v1/noosphere/subconscious":
                res_s = noo.dispatch("subconscious", **body)
                return (200 if res_s.get("ok") else 400), res_s
            if path == "/v1/noosphere/workspace":
                if isinstance(body.get("items"), list):
                    res_w = noo.dispatch("merge_workspace", items=body["items"])
                else:
                    res_w = noo.dispatch("publish_fact", **body)
                return (200 if res_w.get("ok") else 400), res_w
            if path == "/v1/noosphere/sync":
                res_sy = noo.sync_with_peer(
                    peer_base=body.get("peer_base"),
                    timeout=float(body.get("timeout") or 2.5),
                )
                return (200 if res_sy.get("ok") or res_sy.get("skipped") else 502), res_sy
            if path == "/v1/noosphere/sync_exchange":
                res_ex = noo.handle_sync_exchange(body)
                return (200 if res_ex.get("ok") else 400), res_ex
            if path == "/v1/noosphere/deploy-gate":
                res_dg = self.agent_bus.symbiont.eidolon.dispatch("deploy_gate", **body)
                return (200 if res_dg.get("ok") else 400), res_dg

        # --- CHIMERA-EIDOLON & MOONSHOT #2-#5 POST routes ---
        if path.startswith("/v1/eidolon/"):
            eid = self.agent_bus.symbiont.eidolon
            if path == "/v1/eidolon/dispatch":
                act = str(body.get("action") or "status").strip().lower()
                res_e = eid.dispatch(act, **{k: v for k, v in body.items() if k != "action"})
                return (200 if res_e.get("ok") else 400), res_e
            if path == "/v1/eidolon/precog-verify":
                res_pv = eid.dispatch("precog_verify", **body)
                return (200 if res_pv.get("ok") else 400), res_pv
            if path == "/v1/eidolon/scout":
                res_sc = eid.dispatch("scout", **body)
                return (200 if res_sc.get("ok") else 400), res_sc
            if path == "/v1/eidolon/fuzz":
                res_fz = eid.dispatch("fuzz", **body)
                return (200 if res_fz.get("ok") else 400), res_fz
            if path == "/v1/eidolon/counterfactual":
                res_cf = eid.dispatch("counterfactual", **body)
                return (200 if res_cf.get("ok") else 400), res_cf
            if path == "/v1/eidolon/autopoiesis":
                res_ap = eid.dispatch("autopoiesis", **body)
                return (200 if res_ap.get("ok") else 400), res_ap
            if path == "/v1/eidolon/synesthesia":
                act_syn = "synesthesia_recall" if body.get("query") else "synesthesia_index"
                res_sy = eid.dispatch(act_syn, **body)
                return (200 if res_sy.get("ok") else 400), res_sy

        # --- CHIMERA-MNEMOSYNE POST routes ---
        if path.startswith("/v1/mnemosyne/") or path in ("/v1/agent/prime", "/v1/agent/shell-guard", "/v1/agent/warm-repl"):
            mn = self.agent_bus.symbiont.mnemosyne
            if path == "/v1/agent/prime":
                res_m = mn.dispatch("prime", **body)
            elif path == "/v1/agent/shell-guard":
                res_m = mn.dispatch("shell_guard", **body)
            elif path == "/v1/agent/warm-repl":
                res_m = mn.dispatch("warm_repl", **body)
            elif path == "/v1/mnemosyne/dispatch":
                act_m = str(body.get("action") or "status").strip().lower()
                res_m = mn.dispatch(act_m, **{k: v for k, v in body.items() if k != "action"})
            elif path == "/v1/mnemosyne/recall":
                res_m = mn.dispatch("raw_recall", **body)
            elif path == "/v1/mnemosyne/ingest":
                res_m = mn.dispatch("raw_ingest", **body)
            elif path == "/v1/mnemosyne/raw-slice":
                res_m = mn.dispatch("raw_slice", **body)
            elif path == "/v1/mnemosyne/doc-page":
                res_m = mn.dispatch("doc_page", **body)
            elif path == "/v1/mnemosyne/arena":
                res_m = mn.dispatch("raw_arena", **body)
            else:
                return 404, {"ok": False, "error": f"unknown_mnemosyne_route:{path}"}
            return (200 if res_m.get("ok") else 400), res_m

        # --- CHIMERA-PROMETHEUS POST routes ---
        if path.startswith("/v1/prometheus/"):
            pr = self.prometheus
            route_map = {
                "/v1/prometheus/axioms/check": "axiom_check",
                "/v1/prometheus/axioms/record": "axiom_record",
                "/v1/prometheus/epoch/seal": "epoch_seal",
                "/v1/prometheus/epoch/verify": "epoch_verify",
                "/v1/prometheus/epoch/soak/acquire": "soak_acquire",
                "/v1/prometheus/epoch/soak/release": "soak_release",
                "/v1/prometheus/epoch/promote": "epoch_promote",
                "/v1/prometheus/epoch/worktrees": "worktrees",
                "/v1/prometheus/oracle/probe": "oracle_probe",
                "/v1/prometheus/oracle/phantom-probe": "phantom_probe",
                "/v1/prometheus/oracle/speculate": "oracle_speculate",
                "/v1/prometheus/ghost/read": "ghost_read",
                "/v1/prometheus/ghost/ingest": "ghost_ingest",
            }
            if path == "/v1/prometheus/dispatch":
                act_p = str(body.get("action") or "status").strip().lower()
                res_p = pr.dispatch(act_p, **{k: v for k, v in body.items() if k != "action"})
            elif path in route_map:
                res_p = pr.dispatch(route_map[path], **body)
            else:
                return 404, {"ok": False, "error": f"unknown_prometheus_route:{path}"}
            return (200 if res_p.get("ok") else 400), res_p

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
                try:
                    return 200, self.omega.compile_intent(
                        str(body.get("service") or "app"),
                        dict(body.get("invariants") or {}),
                    )
                except (TypeError, ValueError, OverflowError) as exc:
                    return 400, {"ok": False, "error": str(exc)}
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

        # --- CHIMERA-BIOS Open Ecosystem Soul POST routes (100% lazy-loaded, Law 1-7 compliant) ---
        if path.startswith("/v1/bios/"):
            if not self._cartridge_enabled.get("bios", True):
                return 503, {"error": "cartridge_disabled:bios"}
            try:
                if path == "/v1/bios/hormones":
                    sec = body.get("secrete") if isinstance(body.get("secrete"), dict) else None
                    return 200, self.bios.hormones(
                        secrete=sec,
                        action=body.get("action"),
                        payload=body,
                    )
                if path == "/v1/bios/pulse":
                    obs_d = body.get("obs") if isinstance(body.get("obs"), dict) else None
                    return 200, self.bios.pulse(obs=obs_d, context=body.get("context"))
                if path == "/v1/bios/predict":
                    obs_d = body.get("obs") if isinstance(body.get("obs"), dict) else None
                    return 200, self.bios.predict(
                        obs=obs_d,
                        context=str(body.get("context") or "general"),
                        horizon_s=float(body.get("horizon_s") or 60.0),
                        action=str(body.get("action") or "all"),
                    )
                if path == "/v1/bios/autophagy":
                    return 200, self.bios.autophagy_dispatch(
                        action=str(body.get("action") or "status"),
                        payload=body,
                    )
                if path == "/v1/bios/parasite/run":
                    return 200, self.bios.parasite_run(
                        rounds=int(body.get("rounds") or 4),
                        seed=body.get("seed"),
                        scenarios=(list(body["scenarios"]) if isinstance(body.get("scenarios"), list) else None),
                    )
                if path == "/v1/bios/ganglia/reconcile":
                    return 200, self.bios.ganglia_reconcile(
                        local_events=(list(body["local_events"]) if isinstance(body.get("local_events"), list) else None),
                        peer_events=(list(body["peer_events"]) if isinstance(body.get("peer_events"), list) else []),
                    )
                if path == "/v1/bios/pheromone":
                    act_p = str(body.get("action") or "").strip().lower()
                    alarm_d = body.get("alarm") if isinstance(body.get("alarm"), dict) else None
                    if alarm_d is None and (act_p == "alarm" or body.get("signal_kind")):
                        alarm_d = {
                            "rel_path": body.get("rel_path") or body.get("path") or ".",
                            "signal_kind": body.get("signal_kind") or "regression",
                            "severity": body.get("severity", 0.6),
                            "reason": body.get("reason") or "",
                            "agent_id": body.get("agent_id") or "ecosystem",
                        }
                    coedits_l = body.get("coedits") if isinstance(body.get("coedits"), list) else None
                    if coedits_l is None and isinstance(body.get("files"), list):
                        coedits_l = body["files"]
                    meth_d = body.get("methylation") if isinstance(body.get("methylation"), dict) else None
                    if meth_d is None and (act_p == "methylate" or body.get("gene_policy")):
                        meth_d = {
                            "locus": body.get("locus") or body.get("rel_path") or body.get("path") or ".",
                            "gene_policy": body.get("gene_policy") or "extra_verify",
                            "strength": body.get("strength", 0.8),
                            "half_life_days": body.get("half_life_days", 7.0),
                            "reason": body.get("reason") or "",
                        }
                    return 200, self.bios.pheromone(
                        repo=str(body.get("repo") or "."),
                        rel_path=str(body.get("rel_path") or body.get("path") or ""),
                        action=act_p or None,
                        alarm=alarm_d,
                        coedits=coedits_l,
                        methylation=meth_d,
                        max_tokens=int(body.get("max_tokens") or 40),
                    )
                if path == "/v1/bios/umwelt":
                    sig = body.get("signal") if isinstance(body.get("signal"), dict) else None
                    if sig is None and body.get("event_kind"):
                        sig = body
                    act_u = str(body.get("action") or ("assess" if sig is not None else "status"))
                    return 200, self.bios.umwelt_dispatch(
                        signal=sig,
                        action=act_u,
                        lead_minutes=float(body.get("lead_minutes") or 5.0),
                    )
                if path == "/v1/bios/hgt":
                    return 200, self.bios.hgt_dispatch(
                        action=str(body.get("action") or "list"),
                        payload=body,
                    )
                if path == "/v1/bios/spore/attach":
                    return 200, self.bios.spore_attach(body)
                if path == "/v1/bios/spore/autotomy":
                    sid = str(body.get("spore_id") or "").strip()
                    if not sid:
                        return 400, {"ok": False, "error": "missing_spore_id"}
                    return 200, self.bios.spore_autotomy(sid, reason=str(body.get("reason") or "detach"))
                if path == "/v1/bios/spore/seed":
                    return 200, self.bios.spore_seed(body)
                if path == "/v1/bios/soul/scar":
                    return 200, self.bios.soul_record_scar(body)
                if path == "/v1/bios/sync":
                    blend_val = float(body.get("blend") if body.get("blend") is not None else 0.35)
                    # Mode 1: Inbound peer sync carrying an explicit sync bundle
                    if isinstance(body.get("bundle"), dict):
                        if client_ip not in ("127.0.0.1", "::1", "localhost"):
                            presented_auth = headers.get("X-Chimera-Peer-Auth") if headers else None
                            if presented_auth is not None:
                                from .peer_guard import verify_peer_auth

                                if not verify_peer_auth(presented_auth):
                                    return 403, {"ok": False, "error": "peer_auth_required"}
                        bidir = bool(body.get("bidirectional", False))
                        res_in = self.bios.apply_sync_bundle(
                            body["bundle"],
                            blend=blend_val,
                            return_reply_bundle=bidir,
                        )
                        try:
                            self.daemon.record_flow(
                                "phantom",
                                str(res_in.get("peer_node") or "peer"),
                                str(self.daemon.config.node_name),
                                "BIOS_SYNC_IN",
                                wire_bytes=len(raw_body),
                                elapsed_ms=float(res_in.get("elapsed_ms") or 0.0),
                                detail=f"merkle={str(res_in.get('merkle_root') or '')[:12]} scars+={res_in.get('scars_imported', 0)}",
                                ok=True,
                            )
                        except Exception:
                            pass
                        return 200, res_in

                    # Mode 2: Active 2-way bidirectional sync trigger (PHANTOM-5MS first, HTTP peer fallback)
                    explicit_peer = str(body.get("peer_url") or body.get("peer_base") or "").strip().rstrip("/")
                    timeout_s = max(0.5, min(15.0, float(body.get("timeout_s") or body.get("timeout") or 4.0)))
                    self_base = self.anchor_url.rstrip("/")
                    direct_base = ""
                    try:
                        direct_base = str(self.daemon.peer_http_base() or "").strip().rstrip("/")
                    except Exception:
                        direct_base = ""

                    candidates: list[tuple[str, str]] = []
                    if explicit_peer:
                        candidates.append((explicit_peer, "explicit"))
                    else:
                        try:
                            act_base = str(self.daemon.active_edge_peer_base() or "").strip().rstrip("/")
                        except Exception:
                            act_base = ""
                        if act_base and act_base != self_base:
                            t_kind = "phantom_5ms" if (direct_base and act_base != direct_base) else "direct_http"
                            candidates.append((act_base, t_kind))
                        if (
                            direct_base
                            and direct_base != self_base
                            and getattr(self.daemon.config, "peer_ipv4", "")
                            and all(c[0] != direct_base for c in candidates)
                        ):
                            candidates.append((direct_base, "direct_http"))

                    if not candidates:
                        return 503, {
                            "ok": False,
                            "error": "no_peer_configured",
                            "node_name": str(self.daemon.config.node_name),
                            "merkle_converged": False,
                            "auto_activated": False,
                        }

                    last_res: dict[str, Any] = {"ok": False, "error": "peer_sync_failed"}
                    tried: list[str] = []
                    for cand_url, transport_kind in candidates:
                        tried.append(cand_url)
                        res_sync = self.bios.sync_with_peer(
                            cand_url,
                            blend=blend_val,
                            timeout_s=timeout_s,
                            request_authorizer=self.daemon.authenticate_peer_request,
                        )
                        if res_sync.get("ok"):
                            res_sync["transport"] = transport_kind
                            try:
                                self.daemon.record_flow(
                                    "phantom",
                                    str(self.daemon.config.node_name),
                                    str(res_sync.get("peer_node") or self.daemon.config.peer_name or "peer"),
                                    "BIOS_SYNC_2WAY",
                                    wire_bytes=12,
                                    elapsed_ms=float(res_sync.get("rtt_ms") or 0.0),
                                    detail=f"via={transport_kind} converged={res_sync.get('merkle_converged')}",
                                    ok=True,
                                )
                            except Exception:
                                pass
                            return 200, res_sync
                        last_res = res_sync
                    last_res["tried_urls"] = tried
                    return 502, last_res
            except KeyError as exc:
                return 404, {"ok": False, "error": str(exc)}
            except (TypeError, ValueError) as exc:
                return 400, {"ok": False, "error": str(exc)}

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
            if k.lower() not in ("host", "connection", "content-length", "transfer-encoding", "x-chimera-peer-auth")
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

    def _resolve_peer_egress_proxy(self) -> str | None:
        if self.ephemeral:
            return None
        env_url = os.environ.get("CHIMERA_PEER_EGRESS_URL", "").strip()
        if env_url and (
            self._is_loopback_http_url(env_url)
            or os.environ.get("CHIMERA_ALLOW_REMOTE_EGRESS_URL") == "1"
        ):
            return env_url
        cfg_url = str(getattr(self.daemon.config, "peer_egress_proxy_url", "") or "").strip()
        if cfg_url and (
            self._is_loopback_http_url(cfg_url)
            or os.environ.get("CHIMERA_ALLOW_REMOTE_EGRESS_URL") == "1"
        ):
            return cfg_url

        # Auto-discover encrypted PHANTOM-5MS loopback forward -> peer's 127.0.0.1:9781
        try:
            ph_health = self.daemon.get_cached_peer_health() if hasattr(self.daemon, "get_cached_peer_health") else None
            if isinstance(ph_health, dict) and ph_health.get("online") is False:
                return None
            if isinstance(ph_health, dict):
                zw = ph_health.get("zero_weight")
                if isinstance(zw, dict) and zw.get("zero_weight_ok") is False:
                    return None
        except Exception:
            pass

        ph_cli = getattr(self.daemon, "_phantom_client", None)
        if ph_cli is not None:
            try:
                st = ph_cli.status()
                if st.get("connected"):
                    listeners = st.get("listeners") or {}
                    # PhantomTunnelClient.status()["listeners"] maps remote_port -> local_port (e.g. {"9781": 9791})
                    lport = listeners.get(9781) or listeners.get("9781")
                    if lport and int(lport) > 0:
                        return f"http://127.0.0.1:{int(lport)}"
                    for k, v in (st.get("forwards") or {}).items():
                        if int(v) == 9781 and int(k) > 0:
                            return f"http://127.0.0.1:{int(k)}"
            except Exception:
                pass

        ph_srv = getattr(self.daemon, "_phantom_srv", None)
        if ph_srv is not None:
            try:
                st = ph_srv.stats()
                if st.get("sessions") or st.get("active_sessions", 0) > 0:
                    rev = st.get("reverse_listeners") or {}
                    lport = rev.get(9781) or rev.get("9781")
                    if lport and int(lport) > 0:
                        return f"http://127.0.0.1:{int(lport)}"
                    for k, v in (st.get("reverse_forwards") or {}).items():
                        if int(v) == 9781 and int(k) > 0:
                            return f"http://127.0.0.1:{int(k)}"
            except Exception:
                pass
        return None

    def _ensure_symbiote_engine(self) -> Any:
        sym = getattr(getattr(self.daemon, "overmind", None), "symbiote", None)
        if sym is not None:
            return sym
        with self._engine_lock:
            if self._fallback_symbiote is None:
                from ..symbiote_engine import ChimeraSymbioteEngine

                self._fallback_symbiote = ChimeraSymbioteEngine(ops_dir=Path(self.daemon.ops_dir))
            return self._fallback_symbiote

    @staticmethod
    def _is_loopback_http_url(url: str) -> bool:
        try:
            p = urllib.parse.urlsplit(str(url or "").strip())
            host = (p.hostname or "").lower().strip("[]")
            return p.scheme == "http" and host in ("127.0.0.1", "localhost", "::1") and bool(p.port)
        except Exception:
            return False

    def _discover_openai_gateways(
        self,
        headers: Any,
        *,
        model: str = "",
    ) -> list[tuple[str, dict[str, str]]]:
        """Discover local & peer OpenAI-compatible gateways declaratively (zero vendor hardcoding)."""
        is_hop = str(headers.get("X-Chimera-OpenAI-Hop") or "") == "1"
        gateways: list[tuple[str, dict[str, str]]] = []
        seen: set[str] = set()

        def _add(base_url: str, extra: dict[str, str] | None = None) -> None:
            b = str(base_url or "").strip().rstrip("/")
            if not b or b in seen:
                return
            seen.add(b)
            gateways.append((b, dict(extra or {})))

        # 1. Explicit per-request loopback upstream override (strictly loopback-only)
        override = str(headers.get("X-Chimera-Upstream") or "").strip().rstrip("/")
        if override and self._is_loopback_http_url(override):
            _add(override)

        # 2. Cached model -> gateway affinity route
        if model:
            now_m = time.monotonic()
            with self._openai_models_lock:
                cached = self._openai_model_routes.get(model)
            if cached and now_m < float(cached[1]):
                _add(cached[0])

        # 3. Declarative linked/attached apps advertising openai/llm-gateway capability
        try:
            for app in self.registry.list_apps():
                port = int(app.get("port") or 0)
                if port <= 0:
                    continue
                needs = {str(x).lower() for x in (app.get("needs") or [])}
                caps = {str(x).lower() for x in (app.get("capabilities") or [])}
                adapter = app.get("adapter") if isinstance(app.get("adapter"), dict) else {}
                role = str(adapter.get("role") or "").lower()
                if (
                    needs.intersection({"openai", "openai-gateway", "llm-gateway"})
                    or caps.intersection({"openai", "openai-gateway", "llm-gateway"})
                    or role == "openai_gateway"
                ):
                    _add(f"http://127.0.0.1:{port}")
        except Exception:
            pass

        # 4. Configured default local relay (e.g. tquota :12500)
        relay_base = str(getattr(self.daemon.config, "tquota_relay_url", "") or "http://127.0.0.1:12500").rstrip("/")
        if relay_base:
            _add(relay_base)

        # 5. Cross-host peer fallback (anti-loop protected)
        if (not is_hop) and (not self.ephemeral) and getattr(self.daemon.config, "peer_ipv4", ""):
            try:
                pbase = (self.daemon.active_edge_peer_base() or "").rstrip("/")
                if pbase:
                    _add(f"{pbase}/v1/openai", {"X-Chimera-OpenAI-Hop": "1"})
            except Exception:
                pass

        return gateways

    def openai_conduit_stats(self) -> dict[str, Any]:
        with self._openai_conduit_lock:
            st = dict(self._openai_conduit_stats)
            st["turns_in_ledger"] = len(self._turn_ledger)
        chunks_in = int(st.get("sse_chunks_in") or 0)
        flushes_out = max(1, int(st.get("sse_flushes_out") or 0))
        st["coalesce_ratio"] = round(chunks_in / flushes_out, 2) if chunks_in else 1.0
        with self._openai_models_lock:
            st["cached_model_routes"] = {k: v[0] for k, v in self._openai_model_routes.items()}
        st["gateways"] = [b for b, _ in self._discover_openai_gateways({})]
        st["precog"] = self._precog_pool.stats()
        st["peer_egress_proxy"] = self._resolve_peer_egress_proxy() or ""
        return st

    @staticmethod
    def _sanitize_turn_id(raw: str | None) -> str:
        s = str(raw or "").strip()
        if s and re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", s):
            return s
        return f"turn-{hashlib.blake2s(f'{time.time_ns()}-{threading.get_ident()}'.encode('ascii'), digest_size=6).hexdigest()}"

    @staticmethod
    def _hash_prompt_items(items: list[Any]) -> tuple[list[str], list[dict[str, Any]]]:
        """Single-pass item digest + compact hash-only metadata (0 raw text retained)."""
        digests: list[str] = []
        metas: list[dict[str, Any]] = []
        for idx, item in enumerate(items):
            encoded = json.dumps(item, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
                "utf-8", errors="ignore"
            )
            digests.append(hashlib.blake2s(encoded, digest_size=8).hexdigest())
            if idx < 256:
                if isinstance(item, dict):
                    fhashes: dict[str, str] = {}
                    for fk in list(item.keys())[:16]:
                        fv = json.dumps(item[fk], sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
                            "utf-8", errors="ignore"
                        )
                        fhashes[str(fk)[:32]] = hashlib.blake2s(fv, digest_size=8).hexdigest()
                    metas.append(
                        {
                            "role": str(item.get("role") or item.get("type") or "")[:32],
                            "est_tokens": max(1, len(encoded) // 4),
                            "field_hashes": fhashes,
                        }
                    )
                else:
                    metas.append({"role": "", "est_tokens": max(1, len(encoded) // 4), "field_hashes": {}})
        return digests, metas

    def _record_turn_state(self, turn_id: str, updates: dict[str, Any]) -> None:
        with self._openai_conduit_lock:
            row = self._turn_ledger.get(turn_id)
            if row is None:
                row = {"turn_id": turn_id}
                self._turn_ledger[turn_id] = row
                self._openai_conduit_stats["turns_tracked"] += 1
            row.update(updates)
            self._turn_ledger.move_to_end(turn_id)
            while len(self._turn_ledger) > 64:
                self._turn_ledger.popitem(last=False)

    def handle_openai_post_stream(
        self,
        handler: Any,
        parsed: Any,
        raw_body: bytes,
        headers: Any,
    ) -> bool:
        """Zero-IQ-Loss SSE Streaming Conduit with 16ms Frame Coalescer, Detached Immortal Harvest & Merkle Prefix Audit."""
        import queue as _queue

        sub_ep = parsed.path[len("/v1/openai") :]
        if parsed.query:
            sub_ep = f"{sub_ep}?{parsed.query}"

        try:
            body = json.loads(raw_body.decode("utf-8")) if raw_body else {}
            if not isinstance(body, dict):
                body = {}
        except Exception:
            err_b = json.dumps({"error": "invalid_json_body"}).encode("utf-8")
            handler.send_response(400)
            handler.send_header("Content-Type", "application/json")
            handler.send_header("Content-Length", str(len(err_b)))
            handler.end_headers()
            handler.wfile.write(err_b)
            return True

        with self._openai_conduit_lock:
            self._openai_conduit_stats["requests_total"] += 1

        model = str(body.get("model") or "")
        is_stream = bool(body.get("stream", False))
        no_replay = str(headers.get("X-Chimera-No-Replay") or "").strip() in ("1", "true", "yes")
        precog_enabled = str(headers.get("X-Chimera-Precog") or "1").strip() not in ("0", "false", "no")
        precog_exec = str(headers.get("X-Chimera-Precog-Exec") or "").strip() in ("1", "true", "yes")
        workspace_root = str(headers.get("X-Chimera-Workspace") or "").strip()
        turn_id = self._sanitize_turn_id(headers.get("X-Chimera-Turn-Id"))
        try:
            coalesce_ms = max(0, min(100, int(headers.get("X-Chimera-Coalesce-Ms") or 16)))
        except (TypeError, ValueError):
            coalesce_ms = 16
        coalesce_s = coalesce_ms / 1000.0

        # 1. O(log N) Deterministic Merkle Prefix-Cache Audit + Hash-Only Forensics (zero prompt mutation!)
        symbiote = self._ensure_symbiote_engine()
        prefix_clean = True
        prefix_root = ""
        sticky_key = ""
        session_id = str(headers.get("X-Chimera-Session") or "").strip()
        forensic_diff: dict[str, Any] = {}
        turn_key = ""
        items = body.get("messages") if isinstance(body.get("messages"), list) else (
            body.get("input") if isinstance(body.get("input"), list) else []
        )
        if items and symbiote is not None:
            try:
                digests, item_metas = self._hash_prompt_items(items)
                if not session_id:
                    session_id = digests[0] if digests else "default"
                audit = symbiote.audit_prefix(session_id, digests, item_metas=item_metas)
                prefix_clean = not bool(audit.get("mid_prefix_break", False))
                prefix_root = str(audit.get("prefix_root") or "")
                sticky_key = str(audit.get("sticky_key") or audit.get("matched_prefix_root") or (digests[0] if digests else prefix_root))
                forensic_diff = audit.get("forensic_diff") if isinstance(audit.get("forensic_diff"), dict) else {}
                lost_tok = int(forensic_diff.get("lost_tokens_est") or 0) if not prefix_clean else 0
                with self._openai_conduit_lock:
                    self._openai_conduit_stats["prefix_audits"] += 1
                    if not prefix_clean:
                        self._openai_conduit_stats["prefix_breaks"] += 1
                        self._openai_conduit_stats["prefix_tokens_lost_est"] += lost_tok
                if not prefix_clean:
                    ev_payload = {
                        "turn_id": turn_id,
                        "session_id": session_id,
                        "model": model,
                        "break_index": audit.get("break_index"),
                        "item_count": len(digests),
                        **forensic_diff,
                    }
                    try:
                        self.blackbox.record_forensic("kv_prefix_break", ev_payload)
                    except Exception:
                        pass
                    try:
                        self.pulse.publish("llm.prefix_break", ev_payload, app="hydra-conduit", relay=False)
                    except Exception:
                        pass
                turn_key = hashlib.blake2s(
                    f"{sub_ep}\n{model}\n{prefix_root}\n{digests[-1] if digests else ''}".encode("utf-8"),
                    digest_size=16,
                ).hexdigest()
            except Exception:
                pass
        elif symbiote is not None:
            turn_key = hashlib.blake2s(raw_body or b"{}", digest_size=16).hexdigest()

        self._record_turn_state(
            turn_id,
            {
                "session_id": session_id or "default",
                "model": model,
                "prefix_root": prefix_root,
                "sticky_key": sticky_key,
                "prefix_clean": prefix_clean,
                "turn_key": turn_key,
                "workspace_root": workspace_root,
                "started_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "status": "inflight",
            },
        )
        try:
            self.pulse.publish(
                "llm.turn_start",
                {"turn_id": turn_id, "session_id": session_id or "default", "model": model, "prefix_clean": prefix_clean},
                app="hydra-conduit",
                relay=False,
            )
        except Exception:
            pass

        # 2. Immortal Harvest Replay (ONLY for previously detached aborted turns!)
        if is_stream and (not no_replay) and turn_key and symbiote is not None:
            try:
                hit = symbiote.lookup_immortal(turn_key, require_detached=True, include_bytes=True)
                if hit.get("found") and hit.get("status") == "completed" and hit.get("sse_b64"):
                    sse_bytes = base64.b64decode(hit["sse_b64"])
                    try:
                        handler.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                    except OSError:
                        pass
                    handler.send_response(200)
                    handler.send_header("Content-Type", "text/event-stream; charset=utf-8")
                    handler.send_header("Cache-Control", "no-cache")
                    handler.send_header("Transfer-Encoding", "chunked")
                    handler.send_header("Connection", "close")
                    handler.send_header("X-Chimera-Conduit", "hydra-sse")
                    handler.send_header("X-Chimera-Immortal", "HIT")
                    handler.send_header("X-Chimera-Turn-Id", turn_id)
                    handler.send_header("X-Chimera-Prefix-Clean", "1" if prefix_clean else "0")
                    if prefix_root:
                        handler.send_header("X-Chimera-Prefix-Root", prefix_root)
                    if sticky_key:
                        handler.send_header("X-Chimera-Prefix-Sticky", sticky_key)
                    handler.end_headers()
                    for off in range(0, len(sse_bytes), 16384):
                        part = sse_bytes[off : off + 16384]
                        handler.wfile.write(f"{len(part):x}\r\n".encode("ascii") + part + b"\r\n")
                    handler.wfile.write(b"0\r\n\r\n")
                    handler.wfile.flush()
                    # Consume detached entry once replayed so later intentional re-runs hit upstream fresh
                    with symbiote._lock:
                        symbiote._immortal.pop(turn_key, None)
                    with self._openai_conduit_lock:
                        self._openai_conduit_stats["streams_total"] += 1
                        self._openai_conduit_stats["immortal_replays"] += 1
                        self._openai_conduit_stats["bytes_streamed"] += len(sse_bytes)
                    self._record_turn_state(
                        turn_id,
                        {"status": "replayed", "bytes_streamed": len(sse_bytes), "ended_at": datetime.now().astimezone().isoformat(timespec="seconds")},
                    )
                    return True
            except Exception:
                pass

        # 3. Forward raw_body verbatim (or via Universal Protocol Shim + Self-Healing Conduit Shield)
        t_req_start = time.perf_counter()
        self_heal = str(headers.get("X-Chimera-Self-Heal") or "1").strip() not in ("0", "false", "no")
        dna_entry = self._dna.get(model) if model else None
        upstream_proto = str(
            headers.get("X-Chimera-Upstream-Protocol")
            or (dna_entry.get("protocol") if isinstance(dna_entry, dict) else "")
            or "openai"
        ).strip().lower()

        gateways = self._discover_openai_gateways(headers, model=model)
        fwd_headers: dict[str, str] = {
            "Content-Type": str(headers.get("Content-Type") or "application/json"),
            "Content-Length": str(len(raw_body)),
            "Accept": str(headers.get("Accept") or ("text/event-stream" if is_stream else "application/json")),
            "Connection": "close",
            "X-Chimera-Turn-Id": turn_id,
            "X-Chimera-Prefix-Clean": "1" if prefix_clean else "0",
        }
        if prefix_root:
            fwd_headers["X-Chimera-Prefix-Root"] = prefix_root
        if sticky_key:
            fwd_headers["X-Chimera-Prefix-Sticky"] = sticky_key
        for passthru in ("Authorization", "OpenAI-Organization", "OpenAI-Beta", "X-Api-Key"):
            val = headers.get(passthru)
            if val:
                fwd_headers[passthru] = str(val)

        send_body = raw_body
        proto_shimmed = False
        if upstream_proto == "anthropic" and "/chat/completions" in sub_ep:
            anth_obj = openai_to_anthropic_request(body)
            anth_obj.pop("stream", None)
            send_body = json.dumps(anth_obj, ensure_ascii=False).encode("utf-8")
            fwd_headers["Content-Length"] = str(len(send_body))
            fwd_headers["Accept"] = "application/json"
            fwd_headers.setdefault("anthropic-version", "2023-06-01")
            if "X-Api-Key" in fwd_headers and "x-api-key" not in fwd_headers:
                fwd_headers["x-api-key"] = fwd_headers["X-Api-Key"]
            proto_shimmed = True

        conn: http.client.HTTPConnection | None = None
        resp: http.client.HTTPResponse | None = None
        chosen_base = ""
        self_healed_tag = ""
        last_err = "no_gateways"
        for gw_idx, (base_url, extra_hdrs) in enumerate(gateways):
            u = urllib.parse.urlsplit(base_url)
            u_host = u.hostname or "127.0.0.1"
            u_port = int(u.port or (443 if u.scheme == "https" else 80))
            u_prefix = u.path.rstrip("/")
            target_path = f"{u_prefix}/v1/messages" if proto_shimmed else f"{u_prefix}{sub_ep}"
            c_try: http.client.HTTPConnection | None = None
            try:
                if u.scheme == "https":
                    c_try = http.client.HTTPSConnection(u_host, u_port, timeout=300.0)
                else:
                    c_try = http.client.HTTPConnection(u_host, u_port, timeout=300.0)
                c_try.connect()
                if c_try.sock is not None:
                    try:
                        c_try.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                    except OSError:
                        pass
                req_hdrs = {**fwd_headers, **extra_hdrs}
                c_try.request("POST", target_path, body=send_body, headers=req_hdrs)
                r_try = c_try.getresponse()

                # Self-Heal #1: Automatic failover across gateways on 502/503 maintenance
                if self_heal and r_try.status in (502, 503) and gw_idx < len(gateways) - 1:
                    _err_preview = r_try.read(512).decode("utf-8", errors="ignore")
                    c_try.close()
                    if model:
                        self._dna.record_runtime_outcome(model, ok=False, fault_class=classify_http_fault(r_try.status, _err_preview))
                    self_healed_tag = "gateway_failover"
                    last_err = f"{base_url}: HTTP {r_try.status}"
                    continue

                # Self-Heal #2: On HTTP 400 retry_blocked, jitter temperature -0.04 and retry once!
                if self_heal and r_try.status == 400 and (not proto_shimmed):
                    err_bytes = r_try.read()
                    err_txt = err_bytes.decode("utf-8", errors="ignore")
                    if classify_http_fault(400, err_txt) == "retry_blocked":
                        c_try.close()
                        if model:
                            self._dna.record_runtime_outcome(model, ok=False, fault_class="retry_blocked")
                        try:
                            j_retry = dict(body)
                            cur_t = float(j_retry.get("temperature") if j_retry.get("temperature") is not None else 0.7)
                            j_retry["temperature"] = round(max(0.05, cur_t - 0.04), 3)
                            rb_jitter = json.dumps(j_retry, ensure_ascii=False).encode("utf-8")
                            c_try = (
                                http.client.HTTPSConnection(u_host, u_port, timeout=300.0)
                                if u.scheme == "https"
                                else http.client.HTTPConnection(u_host, u_port, timeout=300.0)
                            )
                            c_try.connect()
                            if c_try.sock is not None:
                                try:
                                    c_try.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                                except OSError:
                                    pass
                            j_hdrs = {**req_hdrs, "Content-Length": str(len(rb_jitter))}
                            c_try.request("POST", target_path, body=rb_jitter, headers=j_hdrs)
                            r_try = c_try.getresponse()
                            self_healed_tag = "retry_jitter"
                        except Exception:
                            raise
                    else:
                        # Replay exact 400 error body back to client cleanly
                        c_try.close()
                        handler.send_response(400)
                        handler.send_header("Content-Type", str(r_try.getheader("Content-Type") or "application/json"))
                        handler.send_header("Content-Length", str(len(err_bytes)))
                        handler.send_header("X-Chimera-Conduit", "hydra-json")
                        handler.send_header("X-Chimera-Upstream", base_url)
                        handler.send_header("X-Chimera-Turn-Id", turn_id)
                        handler.send_header("Connection", "close")
                        handler.end_headers()
                        handler.wfile.write(err_bytes)
                        handler.wfile.flush()
                        if model:
                            self._dna.record_runtime_outcome(model, ok=False, fault_class=classify_http_fault(400, err_txt))
                        return True

                resp = r_try
                conn = c_try
                chosen_base = base_url
                break
            except Exception as exc:
                last_err = f"{base_url}: {exc}"
                if c_try is not None:
                    try:
                        c_try.close()
                    except Exception:
                        pass

        if conn is None or resp is None:
            err_b = json.dumps(
                {
                    "error": f"openai_relay_unavailable:{last_err}",
                    "hint": "Ensure a local OpenAI gateway is linked (needs=['openai']) or tquota (:12500) is active.",
                }
            ).encode("utf-8")
            handler.send_response(503)
            handler.send_header("Content-Type", "application/json")
            handler.send_header("Content-Length", str(len(err_b)))
            handler.send_header("Connection", "close")
            handler.end_headers()
            handler.wfile.write(err_b)
            return True

        ctype = str(resp.getheader("Content-Type") or "application/json")
        is_sse_resp = resp.status == 200 and ("text/event-stream" in ctype.lower())

        # Non-SSE response (JSON completion or upstream 4xx/5xx error): pass through cleanly
        if not is_sse_resp:
            try:
                body_out = resp.read()
            finally:
                try:
                    conn.close()
                except Exception:
                    pass
            fault_detected = classify_http_fault(resp.status, body_out.decode("utf-8", errors="ignore"))
            if resp.status == 200 and "json" in ctype.lower():
                try:
                    jobj = json.loads(body_out.decode("utf-8"))
                    if isinstance(jobj, dict):
                        if proto_shimmed:
                            jobj = anthropic_to_openai_response(jobj, model=model)
                        jobj.setdefault("chimera_relay_via", f"{chosen_base}{sub_ep}")
                        # Detect silent fake-empty 200 antibody!
                        chs = jobj.get("choices")
                        if isinstance(chs, list) and chs and isinstance(chs[0], dict):
                            msg = chs[0].get("message") or {}
                            if isinstance(msg, dict) and not (msg.get("content") or msg.get("reasoning_content") or msg.get("tool_calls")):
                                fault_detected = "fake_empty_200"
                                try:
                                    self.blackbox.record_forensic(
                                        "model_fault",
                                        {"turn_id": turn_id, "model": model, "fault": "fake_empty_200", "upstream": chosen_base},
                                    )
                                except Exception:
                                    pass
                        body_out = json.dumps(jobj, ensure_ascii=False).encode("utf-8")
                except Exception:
                    pass
            if model:
                self._dna.record_runtime_outcome(
                    model,
                    ok=(resp.status == 200 and fault_detected == "ok"),
                    latency_ms=(time.perf_counter() - t_req_start) * 1000.0,
                    fault_class=("" if fault_detected == "ok" else fault_detected),
                )
            handler.send_response(resp.status)
            handler.send_header("Content-Type", "application/json" if proto_shimmed else ctype)
            handler.send_header("Content-Length", str(len(body_out)))
            handler.send_header("X-Chimera-Conduit", "hydra-json")
            handler.send_header("X-Chimera-Upstream", chosen_base)
            handler.send_header("X-Chimera-Turn-Id", turn_id)
            handler.send_header("X-Chimera-Prefix-Clean", "1" if prefix_clean else "0")
            if proto_shimmed:
                handler.send_header("X-Chimera-Protocol-Shim", "anthropic->openai")
            if self_healed_tag:
                handler.send_header("X-Chimera-Self-Healed", self_healed_tag)
            if prefix_root:
                handler.send_header("X-Chimera-Prefix-Root", prefix_root)
            if sticky_key:
                handler.send_header("X-Chimera-Prefix-Sticky", sticky_key)
            handler.send_header("Connection", "close")
            handler.end_headers()
            handler.wfile.write(body_out)
            handler.wfile.flush()
            self._record_turn_state(
                turn_id,
                {
                    "status": "completed" if 200 <= resp.status < 300 else "error",
                    "http_status": resp.status,
                    "bytes_streamed": len(body_out),
                    "ended_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                },
            )
            return True

        # 4. Zero-Copy SSE Pass-Through + 16ms Frame Coalescer + Precognition Tap + Detached Immortal Harvest
        with self._openai_conduit_lock:
            self._openai_conduit_stats["streams_total"] += 1
        if symbiote is not None and turn_key:
            try:
                symbiote.register_immortal(turn_key, meta={"model": model, "turn_id": turn_id})
            except Exception:
                pass

        try:
            handler.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            pass

        handler.send_response(200)
        handler.send_header("Content-Type", ctype)
        handler.send_header("Cache-Control", "no-cache")
        handler.send_header("Transfer-Encoding", "chunked")
        handler.send_header("Connection", "close")
        handler.send_header("X-Chimera-Conduit", "hydra-sse")
        handler.send_header("X-Chimera-Immortal", "LIVE")
        handler.send_header("X-Chimera-Upstream", chosen_base)
        handler.send_header("X-Chimera-Turn-Id", turn_id)
        handler.send_header("X-Chimera-Prefix-Clean", "1" if prefix_clean else "0")
        handler.send_header("X-Chimera-Coalesce-Ms", str(coalesce_ms))
        if prefix_root:
            handler.send_header("X-Chimera-Prefix-Root", prefix_root)
        if sticky_key:
            handler.send_header("X-Chimera-Prefix-Sticky", sticky_key)
        if self_healed_tag:
            handler.send_header("X-Chimera-Self-Healed", self_healed_tag)
        handler.end_headers()
        handler.wfile.flush()

        q: _queue.Queue[bytes | None] = _queue.Queue(maxsize=64)
        client_gone = threading.Event()
        abort_upstream = threading.Event()
        harvest_lock = threading.Lock()
        detached_flag = [False]
        reader_done = [False]
        harvest_buf = bytearray()
        max_harvest_bytes = 2 * 1024 * 1024
        read_err: list[str] = []

        precog_tap: PrecognitionStreamTap | None = None
        if precog_enabled:
            precog_tap = PrecognitionStreamTap(
                self._precog_pool,
                turn_id=turn_id,
                session_id=session_id or "default",
                workspace_root=workspace_root,
                allow_exec=precog_exec,
                pulse_fn=lambda topic, payload: self.pulse.publish(topic, payload, app="hydra-conduit", relay=False),
            )
            with self._openai_conduit_lock:
                self._openai_conduit_stats["precog_taps"] += 1

        def _commit_detached_harvest() -> None:
            if harvest_buf and symbiote is not None and turn_key:
                try:
                    symbiote.complete_immortal(
                        turn_key,
                        bytes(harvest_buf),
                        detached_harvest=True,
                        cut="completed",
                        model=model,
                    )
                    with self._openai_conduit_lock:
                        self._openai_conduit_stats["immortal_completed"] += 1
                    self._record_turn_state(
                        turn_id,
                        {"status": "detached_completed", "ended_at": datetime.now().astimezone().isoformat(timespec="seconds")},
                    )
                except Exception:
                    pass

        def _upstream_reader() -> None:
            try:
                while not abort_upstream.is_set():
                    chunk = resp.read1(8192)
                    if not chunk:
                        break
                    if len(harvest_buf) + len(chunk) <= max_harvest_bytes:
                        harvest_buf.extend(chunk)
                    if not client_gone.is_set():
                        while not client_gone.is_set() and not abort_upstream.is_set():
                            try:
                                q.put(chunk, timeout=0.5)
                                break
                            except _queue.Full:
                                continue
                        # Strictly AFTER q.put(chunk) -> 0ms TTFT cost & read-only zero-mutation tap!
                        if precog_tap is not None and not client_gone.is_set():
                            try:
                                precog_tap.feed(chunk)
                            except Exception:
                                pass
            except Exception as exc:
                read_err.append(str(exc))
            finally:
                if precog_tap is not None:
                    hints_here = int(precog_tap.hints_fired)
                    precog_tap.close()
                    if hints_here:
                        with self._openai_conduit_lock:
                            self._openai_conduit_stats["precog_hints"] += hints_here
                with harvest_lock:
                    reader_done[0] = True
                    should_commit = bool(detached_flag[0])
                if should_commit:
                    _commit_detached_harvest()
                    try:
                        self._detached_harvest_sem.release()
                    except ValueError:
                        pass
                try:
                    q.put_nowait(None)
                except _queue.Full:
                    pass
                try:
                    conn.close()
                except Exception:
                    pass

        reader_t = threading.Thread(target=_upstream_reader, name="chimera-sse-reader", daemon=True)
        reader_t.start()

        pending = bytearray()
        first_chunk_sent = False
        saw_done = False
        last_flush = time.monotonic()
        chunks_in = 0
        flushes_out = 0
        bytes_out = 0

        def _flush_pending() -> None:
            nonlocal last_flush, flushes_out, bytes_out
            if not pending:
                return
            frame = bytes(pending)
            pending.clear()
            handler.wfile.write(f"{len(frame):x}\r\n".encode("ascii") + frame + b"\r\n")
            handler.wfile.flush()
            last_flush = time.monotonic()
            flushes_out += 1
            bytes_out += len(frame)

        try:
            while True:
                if pending and coalesce_s > 0:
                    rem = coalesce_s - (time.monotonic() - last_flush)
                    if rem <= 0:
                        _flush_pending()
                        continue
                    try:
                        item = q.get(timeout=rem)
                    except _queue.Empty:
                        _flush_pending()
                        continue
                else:
                    try:
                        item = q.get(timeout=300.0)
                    except _queue.Empty:
                        break

                if item is None:
                    _flush_pending()
                    break

                chunks_in += 1
                if b"[DONE]" in item:
                    saw_done = True
                pending.extend(item)

                # Flush immediately on chunk #1 (0ms TTFT penalty), on [DONE], on >=4KB, or when coalescing off
                if (not first_chunk_sent) or saw_done or coalesce_s <= 0 or len(pending) >= 4096:
                    _flush_pending()
                    first_chunk_sent = True

            handler.wfile.write(b"0\r\n\r\n")
            handler.wfile.flush()
            abort_upstream.set()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            # Client aborted mid-stream -> promote reader thread into Detached Immortal Harvest!
            if (not saw_done) and symbiote is not None and turn_key:
                commit_now = False
                handed_off = False
                with harvest_lock:
                    if reader_done[0]:
                        commit_now = True
                    elif self._detached_harvest_sem.acquire(blocking=False):
                        detached_flag[0] = True
                        handed_off = True
                client_gone.set()
                if handed_off:
                    with self._openai_conduit_lock:
                        self._openai_conduit_stats["immortal_detached"] += 1
                elif commit_now:
                    with self._openai_conduit_lock:
                        self._openai_conduit_stats["immortal_detached"] += 1
                    _commit_detached_harvest()
                else:
                    abort_upstream.set()
                    try:
                        conn.close()
                    except Exception:
                        pass
            else:
                abort_upstream.set()
                client_gone.set()
                try:
                    conn.close()
                except Exception:
                    pass
        finally:
            with self._openai_conduit_lock:
                self._openai_conduit_stats["sse_chunks_in"] += chunks_in
                self._openai_conduit_stats["sse_flushes_out"] += flushes_out
                self._openai_conduit_stats["bytes_streamed"] += bytes_out
            turn_status = "detached" if detached_flag[0] else ("completed" if saw_done or not client_gone.is_set() else "aborted")
            if model:
                self._dna.record_runtime_outcome(
                    model,
                    ok=(bytes_out > 0 and not read_err),
                    latency_ms=(time.perf_counter() - t_req_start) * 1000.0,
                    fault_class=("" if (bytes_out > 0 and not read_err) else ("fake_empty_200" if not read_err else "network")),
                )
            self._record_turn_state(
                turn_id,
                {
                    "status": turn_status,
                    "http_status": 200,
                    "bytes_streamed": bytes_out,
                    "saw_done": saw_done,
                    "ended_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                },
            )
            try:
                self.pulse.publish(
                    "llm.turn_end",
                    {"turn_id": turn_id, "status": turn_status, "bytes_streamed": bytes_out, "saw_done": saw_done},
                    app="hydra-conduit",
                    relay=False,
                )
            except Exception:
                pass

        return True

    def handle_bios_get_stream(
        self,
        handler: Any,
        parsed: urllib.parse.ParseResult,
        headers: Any,
    ) -> bool:
        """Serve non-JSON CHIMERA-BIOS GET endpoints: Spore PWA HTML and live SSE pulse stream."""
        path = parsed.path
        if path not in ("/v1/bios/spore", "/v1/bios/stream"):
            return False

        if not self._cartridge_enabled.get("bios", True):
            raw_err = json.dumps({"ok": False, "error": "cartridge_disabled:bios"}).encode("utf-8")
            handler.send_response(503)
            handler.send_header("Content-Type", "application/json; charset=utf-8")
            handler.send_header("Content-Length", str(len(raw_err)))
            handler.end_headers()
            handler.wfile.write(raw_err)
            return True

        qs = urllib.parse.parse_qs(parsed.query)
        if path == "/v1/bios/spore":
            anchor_override = (qs.get("anchor") or [""])[0].strip()
            html = self.bios.spore_pwa_html(anchor_url=anchor_override)
            raw_html = html.encode("utf-8")
            handler.send_response(200)
            handler.send_header("Content-Type", "text/html; charset=utf-8")
            handler.send_header("Cache-Control", "no-cache")
            handler.send_header("Content-Length", str(len(raw_html)))
            handler.end_headers()
            handler.wfile.write(raw_html)
            handler.wfile.flush()
            return True

        # GET /v1/bios/stream -> bounded or live SSE (text/event-stream)
        once = (qs.get("once") or ["0"])[0].strip().lower() in ("1", "true", "yes")
        max_ev_raw = (qs.get("max_events") or [""])[0].strip()
        bounded = once or bool(max_ev_raw)
        if once:
            max_events = 1
        elif max_ev_raw.isdigit():
            max_events = max(1, min(100, int(max_ev_raw)))
        else:
            max_events = 30
        int_raw = (qs.get("interval_ms") or [""])[0].strip()
        if int_raw.isdigit():
            interval_ms = max(20, min(10000, int(int_raw)))
        else:
            interval_ms = 80 if bounded else 2000

        try:
            handler.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            pass
        handler.send_response(200)
        handler.send_header("Content-Type", "text/event-stream; charset=utf-8")
        handler.send_header("Cache-Control", "no-cache")
        handler.send_header("Connection", "close")
        handler.end_headers()
        handler.wfile.flush()

        for idx in range(max_events):
            try:
                frame = self.bios.pulse(context="sse_stream")
                payload = json.dumps(frame, separators=(",", ":"), ensure_ascii=False)
                chunk = f"id: {frame.get('seq', idx + 1)}\ndata: {payload}\n\n".encode("utf-8")
                handler.wfile.write(chunk)
                handler.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
                break
            if idx + 1 < max_events:
                time.sleep(interval_ms / 1000.0)
        return True


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
        f"| CHIMERA-SMI v{caps.get('package_version') or caps.get('version') or __version__:<8} | Node: {caps.get('node_name', '?'):<14} ({caps.get('role', '?'):<10}) | PID: {caps.get('pid', 0):<8} |",
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
        f"|  [ON] hyper_desk      : auto={'ON' if (hd.get('autonomic') or {}).get('running') else 'OFF':<3} wall={hd.get('silicon_wall_pinned_procs',0):<2} cryo={hd.get('cryo_passes',0):<3} reap={hd.get('orphans_reaped',0):<2} dec={((hd.get('autonomic') or {}).get('decisions',0)):<3} |",
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
