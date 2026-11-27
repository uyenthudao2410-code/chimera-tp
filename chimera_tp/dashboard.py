"""24/7 CHIMERA-HYPER v6.0 APEX-SYNERGY HyperOS Daemon, Tunnel & Web Cockpit."""

from __future__ import annotations

import base64
from collections import deque
import gc
import gzip
import hashlib
import http.server
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

from . import __version__
from .active_pipe import (
    ActiveQueryServer,
    ComputePlan,
    remote_active_query,
)
from .autopilot import (
    VALID_PROFILES,
    OpsConfig,
    TelemetryStore,
    _build_incremental_sample,
    _http_get_json,
    _http_post_json,
    default_ops_dir,
    format_cluster_markdown_report,
    get_zero_weight_status,
    prepare_merkle_demo_workspace,
    run_daily_autopilot,
)
from .code_search import CodeSearchIndex
from .drop_portal import DropPortalStore, pack_ai_context
from .native import v12_native_caps, v9_native_caps


# Phantom-Demand Lazy Loader: keeps cold v6-v12 lab modules out of RAM until explicitly invoked!
_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "ApexSynergyEngine": (".apex_synergy", "ApexSynergyEngine"),
    "run_omega_benchmark": (".omega_bench", "run_omega_benchmark"),
    "NeuralPpmCodec": (".omega_compute", "NeuralPpmCodec"),
    "RemoteRamStore": (".omega_compute", "RemoteRamStore"),
    "WasmActivePipe": (".omega_compute", "WasmActivePipe"),
    "build_wasm_byte_counter_module": (".omega_compute", "build_wasm_byte_counter_module"),
    "RegeneratingMeshVault": (".omega_storage", "RegeneratingMeshVault"),
    "SlepianWolfSync": (".omega_storage", "SlepianWolfSync"),
    "detect_fs_mount_caps": (".omega_storage", "detect_fs_mount_caps"),
    "GeneticWireEngine": (".omega_transport", "GeneticWireEngine"),
    "detect_os_tun_caps": (".omega_transport", "detect_os_tun_caps"),
    "AirGapFountainBridge": (".singularity_airgap_crypto", "AirGapFountainBridge"),
    "PlausibleDeniabilityVault": (".singularity_airgap_crypto", "PlausibleDeniabilityVault"),
    "PrivateInfoRetrievalEngine": (".singularity_airgap_crypto", "PrivateInfoRetrievalEngine"),
    "build_deterministic_pir_db": (".singularity_airgap_crypto", "build_deterministic_pir_db"),
    "run_singularity_benchmark": (".singularity_bench", "run_singularity_benchmark"),
    "KolmogorovGrammarCodec": (".singularity_kolmogorov_swarm", "KolmogorovGrammarCodec"),
    "SwarmAnycastMesh": (".singularity_kolmogorov_swarm", "SwarmAnycastMesh"),
    "MerkleCrdtShadowTwin": (".singularity_time_crdt", "MerkleCrdtShadowTwin"),
    "SpeculativeTimeWarpEngine": (".singularity_time_crdt", "SpeculativeTimeWarpEngine"),
    "ProceduralTarpitLabyrinth": (".v10_outlaw_engines", "ProceduralTarpitLabyrinth"),
    "FrostThreshold2of3": (".v10_sovereign_crypto", "FrostThreshold2of3"),
    "WasmLiveTeleportEngine": (".v10_sovereign_runtime", "WasmLiveTeleportEngine"),
    "ActiveMatterCell": (".v11_autopoietic_systems", "ActiveMatterCell"),
    "run_galactic_benchmark": (".v12_bench", "run_galactic_benchmark"),
    "HyperdimensionalVsaMesh": (".v12_galactic_engines", "HyperdimensionalVsaMesh"),
    "LiveClusterIndexer": (".v9_app_index", "LiveClusterIndexer"),
    "RemoteAppStreamEngine": (".v9_app_index", "RemoteAppStreamEngine"),
    "SharedCasTurboCache": (".v9_app_index", "SharedCasTurboCache"),
    "UniversalInstantHub": (".v9_app_index", "UniversalInstantHub"),
    "probe_hw_encoders": (".v9_app_index", "probe_hw_encoders"),
    "run_hyperdrive_benchmark": (".v9_bench", "run_hyperdrive_benchmark"),
    "UnifiedHardwareGrid": (".v9_nvme_grid", "UnifiedHardwareGrid"),
    "VirtualNvmeFabric": (".v9_nvme_grid", "VirtualNvmeFabric"),
    "WorkspaceHandOffManager": (".v9_nvme_grid", "WorkspaceHandOffManager"),
    "execute_whitelisted_kernel": (".v9_nvme_grid", "execute_whitelisted_kernel"),
    "probe_accelerators": (".v9_nvme_grid", "probe_accelerators"),
    "probe_mount_drivers": (".v9_nvme_grid", "probe_mount_drivers"),
}


class _LazyRef:
    """Transparent callable/class proxy importing heavy lab modules strictly on first access."""

    def __init__(self, name: str, mod_rel: str, attr: str) -> None:
        self._name = name
        self._mod_rel = mod_rel
        self._attr = attr
        self._target: Any = None

    def _resolve(self) -> Any:
        if self._target is None:
            import importlib

            mod = importlib.import_module(self._mod_rel, package=__package__)
            self._target = getattr(mod, self._attr)
            globals()[self._name] = self._target
        return self._target

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return self._resolve()(*args, **kwargs)

    def __getattr__(self, item: str) -> Any:
        return getattr(self._resolve(), item)


for _lname, (_lmod, _lattr) in _LAZY_EXPORTS.items():
    globals()[_lname] = _LazyRef(_lname, _lmod, _lattr)
from .edge_proxy import EdgeGateway, LocalEdgeProxy, edge_fetch_remote
from .fabric import BeamServer, beam_send
from .ghost_fs import GhostFsEngine
from .ghost_pty import GhostPtyManager
from .host_governor import HostYieldGovernor
from .overmind_cortex import OvermindCortex
from .trinity_bridge import TrinityCommandBridge
from .holo_backup import (
    create_holo_backup,
    list_holo_backups,
    restore_holo_backup,
    sanitize_backup_id,
    store_received_shard,
)
from .hyper_wire import HedgedRpcServer, ImmortalMultiPathReceiver, ImmortalMultiPathSender
from .medic import MedicEngine
from .merkle_sync import (
    ShadowMerkleIndex,
    diff_manifests,
    merkle_beam_sync,
    sanitize_workspace_id,
)
from .nat_buster import NatPunchResponder, attempt_direct_punch, discover_nat_profile
from .native import cpu_caps
from .phantom_tunnel import PhantomTunnelClient, PhantomTunnelServer
from .platform import PlatformSubstrate
from .probe import probe_environment
from .protocol import ChimeraReceiver, ChimeraSender, FaultProfile
from .sentinel import SentinelEngine
from .telepathy import DomainDictionary, TelepathicStore, train_domain_dictionary
from .warp import WarpServer

from .universe_ui import UNIVERSE_DASHBOARD_HTML as _DASHBOARD_HTML, build_kolmogorov_packed_html


class _ThreadingControlServer(http.server.ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True
    request_queue_size = 64


class _VsaServiceOnDemand:
    """Share one VSA database connection across consumers only after a VSA operation."""

    def __init__(self, path: Path):
        self._path = path
        self._lock = threading.Lock()
        self._service = None
        self._closed = False

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        with self._lock:
            if self._closed:
                raise RuntimeError("vsa_service_closed")
            if self._service is None:
                from .vsa_memory_service import SharedVsaMemoryService
                self._service = SharedVsaMemoryService(db_path=self._path)
            return getattr(self._service, name)

    def close(self):
        with self._lock:
            self._closed = True
            if self._service is not None:
                self._service.close()
                self._service = None


class ChimeraDaemon:
    """24/7 Zero-Weight Mission-Control HTTP + UDP service host & daily self-scheduling daemon."""

    def __init__(
        self,
        config: OpsConfig | None = None,
        ops_dir: Path | None = None,
        auto_seed_on_empty: bool = False,
    ) -> None:
        self.ops_dir = Path(ops_dir) if ops_dir else default_ops_dir()
        self.config = config if config is not None else OpsConfig.load(self.ops_dir)
        self.store = TelemetryStore(self.ops_dir / "telemetry.db")
        self.telepathy_store = TelepathicStore(self.ops_dir / "dicts")
        self.merkle_root = self.ops_dir / "merkle_workspaces"
        self.merkle_root.mkdir(parents=True, exist_ok=True)
        self.backup_root = self.ops_dir / "holo_backups"
        self.backup_root.mkdir(parents=True, exist_ok=True)
        self.auto_seed_on_empty = auto_seed_on_empty

        self.nat_responder = NatPunchResponder()
        self.edge_gateway = EdgeGateway(
            targets=self.config.edge_targets, telepathy_store=self.telepathy_store
        )
        self.sentinel = SentinelEngine(ops_dir=self.ops_dir)
        self.code_search = CodeSearchIndex(self.ops_dir / "code_index.db")

        fs_root = (
            Path(self.config.search_roots[0])
            if self.config.search_roots
            else (
                Path(self.config.allowed_query_roots[0])
                if self.config.allowed_query_roots
                else self.ops_dir
            )
        )
        self.ghost_pty = GhostPtyManager()
        self.ghost_fs = GhostFsEngine(fs_root)
        self.medic = MedicEngine(self.ops_dir)
        self.vsa_memory = _VsaServiceOnDemand(self.ops_dir / "vsa_memory.db")
        self.drop_portal = DropPortalStore(
            self.ops_dir / "drop_portal",
            default_ttl_s=int(getattr(self.config, "drop_ttl_s", 600)),
        )
        self._synergy: Any = None
        self._remote_ram: Any = None
        self._genetic_wire: Any = None
        self._time_warp: Any = None
        self._pir_lock = threading.Lock()
        self._pir_slab: bytes | None = None
        self._v9_lock = threading.Lock()
        self._v9_nvme: VirtualNvmeFabric | None = None
        self._v9_indexer: LiveClusterIndexer | None = None
        self._v9_cas: SharedCasTurboCache | None = None
        self._v9_hub: UniversalInstantHub | None = None
        self._v9_handoff: WorkspaceHandOffManager | None = None

        self._run_lock = threading.Lock()
        self._ephemeral_mode = int(self.config.beam_port) == 0 and int(self.config.query_port) == 0
        self._status_cache_lock = threading.Lock()
        self._status_cache_ts: float = 0.0
        self._status_cache_data: tuple[dict[str, Any], bytes, str] | None = None
        self._last_nat_result: dict[str, Any] | None = None
        self._flow_lock = threading.Lock()
        self.host_governor = HostYieldGovernor(role=self.config.role)
        self.overmind = OvermindCortex(ops_dir=self.ops_dir, node_id=self.config.node_name)
        self.overmind.midbrain.vsa_memory = self.vsa_memory
        _peer_radar = (
            f"http://{self.config.peer_ipv4}:8787"
            if self.config.role == "controller" and self.config.peer_ipv4
            else ""
        )
        self.trinity = TrinityCommandBridge(
            governor=self.host_governor,
            tquota_admin_url=str(getattr(self.config, "tquota_admin_url", "http://127.0.0.1:12504")),
            radar_url=str(getattr(self.config, "radar_url", "http://127.0.0.1:8787")),
            peer_radar_url=_peer_radar,
            peer_trinity_resolver=(self.active_edge_peer_base if self.config.role == "controller" else None),
            ephemeral_mode=self._ephemeral_mode,
            on_flow=self.record_flow,
            overmind=self.overmind,
        )
        self._flow_seq: int = 0
        self._flow_ring: deque[dict[str, Any]] = deque(maxlen=28)
        self._peer_health_lock = threading.Lock()
        self._peer_health_ts: float = 0.0
        self._peer_health_busy: bool = False
        self._peer_health_cache: dict[str, Any] | None = None
        self._stop = threading.Event()
        self._beam_srv: BeamServer | None = None
        self._rpc_srv: HedgedRpcServer | None = None
        self._query_srv: ActiveQueryServer | None = None
        self._immortal_rx: ImmortalMultiPathReceiver | None = None
        self._warp_srv: WarpServer | None = None
        self._local_edge_proxy: LocalEdgeProxy | None = None
        self._phantom_srv: PhantomTunnelServer | None = None
        self._phantom_client: PhantomTunnelClient | None = None
        self._httpd: _ThreadingControlServer | None = None
        self._threads: list[threading.Thread] = []
        self.http_addr: tuple[str, int] = ("127.0.0.1", 0)
        self.platform = PlatformSubstrate(self)
        self._omega_spine_lock = threading.Lock()
        self._omega_spine: Any = None

    @property
    def omega_spine(self) -> Any:
        if self._omega_spine is None:
            with self._omega_spine_lock:
                if self._omega_spine is None:
                    from .omega_spine.hook_router import OmegaSpineRuntime

                    self._omega_spine = OmegaSpineRuntime(
                        ops_dir=self.ops_dir,
                        ephemeral=self._ephemeral_mode,
                    )
        return self._omega_spine

    @property
    def synergy(self) -> Any:
        if self._synergy is None:
            self._synergy = ApexSynergyEngine(
                ops_dir=self.ops_dir,
                allowed_roots=self._allowed_roots(),
                tquota_admin_url=str(getattr(self.config, "tquota_admin_url", "http://127.0.0.1:12504")),
                tquota_relay_url=str(getattr(self.config, "tquota_relay_url", "http://127.0.0.1:12500")),
                radar_url=str(getattr(self.config, "radar_url", "http://127.0.0.1:8787")),
                radar_root=str(getattr(self.config, "radar_root", "")),
                tquota_data_dir=str(getattr(self.config, "tquota_data_dir", "")),
            )
        return self._synergy

    @property
    def remote_ram(self) -> Any:
        if self._remote_ram is None:
            self._remote_ram = RemoteRamStore(max_bytes=16 * 1024 * 1024)
        return self._remote_ram

    @property
    def genetic_wire(self) -> Any:
        if self._genetic_wire is None:
            self._genetic_wire = GeneticWireEngine()
        return self._genetic_wire

    @property
    def time_warp(self) -> Any:
        if self._time_warp is None:
            self._time_warp = SpeculativeTimeWarpEngine()
        return self._time_warp

    def record_flow(
        self,
        lane: str,
        src: str,
        dst: str,
        op: str,
        wire_bytes: int = 0,
        elapsed_ms: float = 0.0,
        detail: str = "",
        ok: bool = True,
    ) -> dict[str, Any]:
        with self._flow_lock:
            self._flow_seq += 1
            ev = {
                "id": self._flow_seq,
                "ts": datetime.now().astimezone().strftime("%H:%M:%S"),
                "lane": lane,
                "src": src,
                "dst": dst,
                "op": op,
                "bytes": int(wire_bytes),
                "ms": round(float(elapsed_ms), 2),
                "detail": detail[:140],
                "ok": bool(ok),
            }
            self._flow_ring.append(ev)
            return ev

    def list_flows(self, limit: int = 16) -> list[dict[str, Any]]:
        with self._flow_lock:
            items = list(self._flow_ring)
        return list(reversed(items[-max(1, limit) :]))

    def get_cached_peer_health(self) -> dict[str, Any] | None:
        if self.config.role != "controller" or self._ephemeral_mode or not self.config.peer_ipv4:
            return None
        now = time.monotonic()
        with self._peer_health_lock:
            cached = self._peer_health_cache
            need_refresh = (now - self._peer_health_ts) > 4.0 and not self._peer_health_busy
            if need_refresh:
                self._peer_health_busy = True

        if need_refresh:
            def _probe_peer() -> None:
                res: dict[str, Any]
                try:
                    t0 = time.perf_counter()
                    base = self.active_edge_peer_base()
                    with urllib.request.urlopen(f"{base}/api/health", timeout=1.2) as r:
                        data = json.loads(r.read().decode("utf-8"))
                    res = {
                        "online": True,
                        "node_name": data.get("node_name", self.config.peer_name or "svhome"),
                        "version": data.get("version"),
                        "hardware": data.get("hardware", {}),
                        "native_v9": data.get("native_v9", {}),
                        "native_v12": data.get("native_v12", {}),
                        "zero_weight": data.get("zero_weight", {}),
                        "probe_ms": round((time.perf_counter() - t0) * 1000.0, 2),
                    }
                except Exception as exc:
                    res = {"online": False, "node_name": self.config.peer_name or "svhome", "error": str(exc)[:80]}
                with self._peer_health_lock:
                    self._peer_health_cache = res
                    self._peer_health_ts = time.monotonic()
                    self._peer_health_busy = False

            threading.Thread(target=_probe_peer, daemon=True, name="chimera-peer-probe").start()
        return cached

    def active_edge_peer_base(self) -> str:
        if self._phantom_client is not None:
            st = self._phantom_client.status()
            if st.get("connected") and st.get("mode") == "PHANTOM_5MS_DIRECT":
                loc_p = (st.get("listeners") or {}).get(int(self.config.peer_dashboard_port))
                if loc_p:
                    return f"http://127.0.0.1:{loc_p}"
        if self._phantom_srv is not None:
            st = self._phantom_srv.stats()
            rev_p = (st.get("reverse_listeners") or {}).get(int(self.config.peer_dashboard_port or 9780))
            if rev_p and any(bool(s.get("punched")) for s in (st.get("sessions") or [])):
                return f"http://127.0.0.1:{rev_p}"
        return self.peer_http_base()

    def _should_proxy(self, is_local_flag: bool = False) -> bool:
        return (
            not is_local_flag
            and self.config.role == "controller"
            and bool(self.config.peer_ipv4)
        )

    def authenticate_peer_request(self, req: urllib.request.Request) -> None:
        """Attach the node credential only to an exact configured peer origin."""
        if self.config.peer_ipv4:
            from .platform.peer_guard import authenticate_peer_request

            authenticate_peer_request(req, self.peer_http_base())

    def proxy_request(
        self,
        method: str,
        path_and_query: str,
        body_bytes: bytes | None = None,
        timeout_s: float = 12.0,
    ) -> tuple[int, str, bytes]:
        bases: list[str] = []
        act = self.active_edge_peer_base()
        if act != self.peer_http_base():
            bases.append(act)
        bases.append(self.peer_http_base())
        last_exc: Exception | None = None
        for b in bases:
            url = f"{b}{path_and_query}"
            headers = {"Content-Type": "application/json"} if method == "POST" else {}
            req = urllib.request.Request(url, data=body_bytes if method == "POST" else None, headers=headers, method=method)
            self.authenticate_peer_request(req)
            t0 = time.perf_counter()
            try:
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                with opener.open(req, timeout=timeout_s) as r:
                    rb = r.read()
                    sc = int(r.status)
                    ms = (time.perf_counter() - t0) * 1000.0
                    p_clean = path_and_query.split("?", 1)[0]
                    lane = "tarpit" if "/tarpit" in p_clean else "phantom"
                    self.record_flow(
                        lane,
                        self.config.node_name,
                        self.config.peer_name or "svhome",
                        p_clean,
                        wire_bytes=len(rb) + len(body_bytes or b""),
                        elapsed_ms=ms,
                        detail=f"HTTP {sc} via {'PH5M' if b != self.peer_http_base() else 'DIRECT'}",
                        ok=sc < 400,
                    )
                    return sc, str(r.headers.get("Content-Type", "application/json")), rb
            except urllib.error.HTTPError as he:
                return int(he.code), str(he.headers.get("Content-Type", "application/json")), he.read()
            except Exception as exc:
                last_exc = exc
        raise RuntimeError(f"Peer proxy unreachable: {last_exc}")

    def _allowed_roots(self) -> list[Path]:
        roots = [Path(p).resolve() for p in self.config.allowed_query_roots]
        roots.append(self.ops_dir.resolve())
        if self.config.watched_query_file and self.config.watched_query_file != "@synthetic":
            roots.append(Path(self.config.watched_query_file).resolve().parent)
        for p in self.config.search_roots:
            roots.append(Path(p).resolve())
        for p in self.config.backup_targets:
            roots.append(Path(p).resolve())
        return roots

    def _assert_path_allowed(self, raw_path: str) -> Path:
        cand = Path(raw_path).resolve()
        allowed = self._allowed_roots()
        if not any(cand == r or r in cand.parents for r in allowed):
            raise PermissionError(f"Path outside allowed roots: {cand}")
        return cand

    def peer_http_base(self) -> str:
        if self.config.peer_ipv4:
            return f"http://{self.config.peer_ipv4}:{self.config.peer_dashboard_port}"
        return f"http://127.0.0.1:{self.http_addr[1]}"

    def _get_v9_nvme(self) -> VirtualNvmeFabric:
        with self._v9_lock:
            if self._v9_nvme is None:
                self._v9_nvme = VirtualNvmeFabric(root=self.ghost_fs.root_dir, max_cache_bytes=4 * 1024 * 1024)
            return self._v9_nvme

    def _get_v9_indexer(self) -> LiveClusterIndexer:
        with self._v9_lock:
            if self._v9_indexer is None:
                if (
                    not self.config.search_roots
                    and not self.config.allowed_query_roots
                    and self.ghost_fs.root_dir == Path.home()
                ):
                    roots = [Path(__file__).resolve().parents[1]]
                else:
                    roots = [self.ghost_fs.root_dir]
                    repo_cand = self.ghost_fs.root_dir / "chimera-tp"
                    if repo_cand.is_dir():
                        roots.insert(0, repo_cand)
                    else:
                        for p in self._allowed_roots():
                            if p not in roots:
                                roots.append(p)
                self._v9_indexer = LiveClusterIndexer(roots=roots[:4], max_corpus_bytes=1536 * 1024)
                self._v9_indexer.build_index(max_files=200)
            return self._v9_indexer

    def _get_v9_cas(self) -> SharedCasTurboCache:
        with self._v9_lock:
            if self._v9_cas is None:
                self._v9_cas = SharedCasTurboCache(max_bytes=4 * 1024 * 1024)
            return self._v9_cas

    def _get_v9_hub(self) -> UniversalInstantHub:
        with self._v9_lock:
            if self._v9_hub is None:
                self._v9_hub = UniversalInstantHub(max_items=64)
            return self._v9_hub

    def _get_v9_handoff(self) -> WorkspaceHandOffManager:
        with self._v9_lock:
            if self._v9_handoff is None:
                self._v9_handoff = WorkspaceHandOffManager(max_tasks=64)
            return self._v9_handoff

    def start(self) -> "ChimeraDaemon":
        ephemeral_mode = int(self.config.beam_port) == 0 and int(self.config.query_port) == 0

        # 1) Start persistent BeamServer (supporting kind=3 Merkle patches)
        self._beam_srv = BeamServer(
            bind_ip="0.0.0.0",
            bind_port=int(self.config.beam_port),
            vault_dir=self.ops_dir / "rx_vault",
            out_dir=self.ops_dir / "received_beam",
            merkle_root=self.merkle_root,
        ).start()
        self.config.beam_port = self._beam_srv.ctrl_addr[1]

        # 2) Start Dual-Stack HedgedRpcServer (IPv4 + optional IPv6)
        rpc_binds: list[tuple[str, int]] = [("0.0.0.0", int(self.config.rpc_v4_port))]
        if int(self.config.rpc_v6_port) >= 0:
            try:
                self._rpc_srv = HedgedRpcServer(
                    rpc_binds + [("::", int(self.config.rpc_v6_port))],
                    handler=lambda b: b"CHIMERA-PONG:" + b[:32],
                ).start()
            except OSError:
                self._rpc_srv = HedgedRpcServer(
                    rpc_binds, handler=lambda b: b"CHIMERA-PONG:" + b[:32]
                ).start()
        else:
            self._rpc_srv = HedgedRpcServer(
                rpc_binds, handler=lambda b: b"CHIMERA-PONG:" + b[:32]
            ).start()
        self.config.rpc_v4_port = self._rpc_srv.addrs[0][1]
        if len(self._rpc_srv.addrs) > 1:
            self.config.rpc_v6_port = self._rpc_srv.addrs[1][1]

        # 3) Start ActiveQueryServer (AQ01/AQ02 + Fluid Compute + Telepathy)
        self._query_srv = ActiveQueryServer(
            bind_ip="0.0.0.0",
            bind_port=int(self.config.query_port),
            allowed_roots=self._allowed_roots(),
            telepathy_store=self.telepathy_store,
        ).start()
        self.config.query_port = self._query_srv.addr[1]

        # 4) Start ImmortalMultiPathReceiver (IPv4 + optional IPv6)
        imm_v4_p = 0 if ephemeral_mode else int(self.config.immortal_v4_port)
        imm_v6_p = 0 if ephemeral_mode else int(self.config.immortal_v6_port)
        if imm_v4_p >= 0:
            imm_binds = [("0.0.0.0", imm_v4_p)]
            if imm_v6_p >= 0:
                try:
                    self._immortal_rx = ImmortalMultiPathReceiver(
                        imm_binds + [("::", imm_v6_p)]
                    ).start()
                except OSError:
                    self._immortal_rx = ImmortalMultiPathReceiver(imm_binds).start()
            else:
                self._immortal_rx = ImmortalMultiPathReceiver(imm_binds).start()
            self.config.immortal_v4_port = self._immortal_rx.addrs[0][1]
            if len(self._immortal_rx.addrs) > 1:
                self.config.immortal_v6_port = self._immortal_rx.addrs[1][1]

            def _drain_immortal() -> None:
                while not self._stop.is_set() and self._immortal_rx is not None:
                    try:
                        self._immortal_rx.wait_any_stats(timeout_s=0.3)
                    except TimeoutError:
                        continue
                    except Exception:
                        break

            th_imm = threading.Thread(target=_drain_immortal, daemon=True)
            th_imm.start()
            self._threads.append(th_imm)

        # 5) Start HTTP Control Cockpit
        daemon_ref = self
        host_b, port_b = self.config.dashboard_bind.rsplit(":", 1)
        host_b = host_b.strip("[]") or "127.0.0.1"

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            timeout = 15.0

            def _send_bytes(
                self,
                code: int,
                ctype: str,
                raw: bytes,
                extra_headers: dict[str, str] | None = None,
            ) -> None:
                accept_enc = (self.headers.get("Accept-Encoding") or "").lower()
                use_gzip = len(raw) >= 512 and "gzip" in accept_enc
                body = gzip.compress(raw, compresslevel=5) if use_gzip else raw
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Vary", "Accept-Encoding")
                if use_gzip:
                    self.send_header("Content-Encoding", "gzip")
                if extra_headers:
                    for k, v in extra_headers.items():
                        self.send_header(k, v)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                try:
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass

            def _send_json(
                self,
                code: int,
                obj: Any,
                extra_headers: dict[str, str] | None = None,
            ) -> None:
                body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
                self._send_bytes(
                    code,
                    "application/json; charset=utf-8",
                    body,
                    extra_headers=extra_headers,
                )

            def _send_shard(self, path: Path) -> None:
                import zlib

                try:
                    stream = path.open("rb")
                except FileNotFoundError:
                    self._send_json(404, {"error": "Shard not found"})
                    return
                with stream:
                    remaining = os.fstat(stream.fileno()).st_size
                    # Use identity framing for HTTP/1.0 clients that cannot dechunk.
                    accepted = self.headers.get("Accept-Encoding", "").lower().split(",")
                    compress = (remaining >= 512 and self.request_version == "HTTP/1.1"
                                and any(token.strip() == "gzip" for token in accepted))
                    encoder = zlib.compressobj(level=5, wbits=31) if compress else None
                    self.send_response(200)
                    self.send_header("Content-Type", "application/octet-stream")
                    self.send_header("Vary", "Accept-Encoding")
                    if encoder is None:
                        self.send_header("Content-Length", str(remaining))
                    else:
                        self.send_header("Content-Encoding", "gzip")
                        self.send_header("Transfer-Encoding", "chunked")
                    self.end_headers()
                    try:
                        while remaining:
                            block = stream.read(min(remaining, 64 * 1024))
                            if not block:
                                self.close_connection = True
                                return
                            remaining -= len(block)
                            if encoder is None:
                                self.wfile.write(block)
                            else:
                                self._write_http_chunk(encoder.compress(block))
                        if encoder is not None:
                            self._write_http_chunk(encoder.flush())
                            self.wfile.write(b"0\r\n\r\n")
                    except OSError:
                        self.close_connection = True

            def _write_http_chunk(self, block: bytes) -> None:
                if block:
                    self.wfile.write(f"{len(block):x}\r\n".encode("ascii"))
                    self.wfile.write(block)
                    self.wfile.write(b"\r\n")

            def _read_body(self) -> bytes:
                clen = int(self.headers.get("Content-Length", "0"))
                return self.rfile.read(clen) if clen > 0 else b""

            def _allow_management_request(self) -> bool:
                if self.client_address[0] in ("127.0.0.1", "::1"):
                    return True
                from .platform.peer_guard import load_peer_secret, verify_peer_auth

                # Remote health checks must not grant access to the virtual-host proxy.
                path = urllib.parse.urlsplit(self.path).path
                host = (self.headers.get("Host") or "").lower().partition(":")[0].rstrip(".")
                if (self.command == "GET" and path in ("/api/health", "/.well-known/chimera.json")
                        and not host.endswith(".chimera.local")):
                    return True
                secret = load_peer_secret()
                if secret and verify_peer_auth(self.headers.get("X-Chimera-Peer-Auth"), expected=secret):
                    if path != "/api/phantom/offer":
                        del self.headers["X-Chimera-Peer-Auth"]
                    return True
                # A denied POST can still have an unread body on this connection.
                self.close_connection = True
                self._send_json(403, {"error": "peer_auth_required"}, {"Connection": "close"})
                return False

            def do_GET(self) -> None:
                if not self._allow_management_request():
                    return
                host_prox = daemon_ref.platform.handle_host_proxy("GET", self.path, self.headers)
                if host_prox is not None:
                    self._send_bytes(host_prox[0], host_prox[1], host_prox[2])
                    return
                parsed = urllib.parse.urlparse(self.path)
                if parsed.path == "/mcp":
                    code, obj, hdrs = daemon_ref.omega_spine.mcp.handle_get(self.headers)
                    self._send_json(code, obj, extra_headers=hdrs)
                    return
                if parsed.path == "/v1/hook/status":
                    self._send_json(200, daemon_ref.omega_spine.hooks.status())
                    return
                if parsed.path == "/v1/omega/cage":
                    self._send_json(200, daemon_ref.omega_spine.iron_cage.status())
                    return
                if parsed.path == "/v1/omega/tournament":
                    self._send_json(200, daemon_ref.omega_spine.tournament.status())
                    return
                if parsed.path == "/v1/omega/release/status":
                    self._send_json(200, daemon_ref.omega_spine.release_conductor.status())
                    return
                if parsed.path == "/v1/omega/release/units":
                    self._send_json(200, daemon_ref.omega_spine.release_conductor.render_os_watcher_units())
                    return
                if parsed.path == "/v1/omega/blockers":
                    qs = urllib.parse.parse_qs(parsed.query)
                    repo_q = (qs.get("repo") or [""])[0].strip() or None
                    alerts = daemon_ref.omega_spine.hooks.list_blocker_alerts(repo=repo_q)
                    self._send_json(200, {"ok": True, "count": len(alerts), "alerts": alerts})
                    return
                if parsed.path == "/v1/omega/hygiene":
                    from .omega_spine.release_conductor import context_hygiene_audit

                    qs = urllib.parse.parse_qs(parsed.query)
                    repo_q = (qs.get("repo") or [""])[0].strip()
                    self._send_json(200, context_hygiene_audit([repo_q] if repo_q else []))
                    return
                if parsed.path == "/v1/omega/precog":
                    qs = urllib.parse.parse_qs(parsed.query)
                    cid = (qs.get("conversation_id") or [""])[0].strip()
                    repo_q = (qs.get("repo") or [""])[0].strip() or None
                    st_p = daemon_ref.omega_spine.precog.status()
                    if cid:
                        st_p["conversation_id"] = cid
                        st_p["has_blocking_errors"] = daemon_ref.omega_spine.precog.has_blocking_errors(cid, repo_q)
                        st_p["blocking_errors"] = daemon_ref.omega_spine.precog.get_blocking_errors(cid, repo_q)
                    self._send_json(200, st_p)
                    return
                if parsed.path == "/v1/omega/status":
                    plat_res = daemon_ref.platform.handle_get(parsed, self.headers)
                    base_obj = dict(plat_res[1]) if (plat_res is not None and isinstance(plat_res[1], dict)) else {"ok": True}
                    base_obj["omega_spine"] = daemon_ref.omega_spine.status()
                    self._send_json(plat_res[0] if plat_res is not None else 200, base_obj)
                    return
                if parsed.path in ("/v1/bios/spore", "/v1/bios/stream"):
                    raw_fn = getattr(daemon_ref.platform, "handle_bios_get_stream", None)
                    if callable(raw_fn) and raw_fn(self, parsed, self.headers):
                        return
                if parsed.path == "/.well-known/chimera.json" or parsed.path.startswith("/v1/"):
                    plat_res = daemon_ref.platform.handle_get(parsed, self.headers)
                    if plat_res is not None:
                        self._send_json(plat_res[0], plat_res[1])
                        return
                if parsed.path == "/":
                    payload, raw_json, etag = daemon_ref.get_cached_status()
                    if "packed=1" in parsed.query:
                        cfg_d = payload.get("config") or {}
                        ph_d = payload.get("phantom") or {}
                        boot_obj = {
                            "version": payload.get("version"),
                            "config": {"node_name": cfg_d.get("node_name"), "role": cfg_d.get("role")},
                            "hardware": payload.get("hardware"),
                            "zero_weight": payload.get("zero_weight"),
                            "phantom": {"client": ph_d.get("client")} if ph_d.get("client") else {},
                            "cluster": {"summary": (payload.get("cluster") or {}).get("summary", {})},
                        }
                        safe_boot = json.dumps(boot_obj, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
                        packed_raw = build_kolmogorov_packed_html(safe_boot, '""')
                        self._send_bytes(
                            200,
                            "text/html; charset=utf-8",
                            packed_raw,
                            extra_headers={"Cache-Control": "no-cache", "X-Chimera-Packed": "kolmogorov-deflate-raw"},
                        )
                        return
                    safe_json = raw_json.decode("utf-8").replace("</", "<\\/")
                    hydrated = _DASHBOARD_HTML.replace(
                        "/*__INIT_STATE__*/null", safe_json, 1
                    ).replace("/*__INIT_ETAG__*/\"\"", json.dumps(etag), 1)
                    self._send_bytes(
                        200,
                        "text/html; charset=utf-8",
                        hydrated.encode("utf-8"),
                        extra_headers={"Cache-Control": "no-cache"},
                    )
                    return
                if parsed.path == "/api/health":
                    self._send_json(
                        200,
                        {
                            "ok": True,
                            "version": __version__,
                            "package_version": __version__,
                            "api_version": "12.0.0",
                            "node_name": daemon_ref.config.node_name,
                            "role": daemon_ref.config.role,
                            "hardware": cpu_caps(),
                            "native_v9": v9_native_caps(),
                            "native_v12": v12_native_caps(),
                            "zero_weight": get_zero_weight_status(),
                        },
                    )
                    return
                if parsed.path == "/api/pulse":
                    _, _, etag = daemon_ref.get_cached_status()
                    sent_st = daemon_ref.sentinel.latest_status() or {}
                    recent_ev = daemon_ref.store.get_dashboard_state(limit=1).get("events", [])
                    self._send_json(
                        200,
                        {
                            "ok": True,
                            "ts_ms": int(time.time() * 1000),
                            "ts_local": datetime.now().astimezone().strftime("%H:%M:%S"),
                            "zero_weight": get_zero_weight_status(),
                            "phantom": daemon_ref.phantom_status(),
                            "sentinel_status": sent_st.get("status", "PENDING"),
                            "sentinel_services": sent_st.get("services", []),
                            "latest_event": recent_ev[0] if recent_ev else None,
                            "portal_count": len(daemon_ref.drop_portal.list_items()),
                            "pty_sessions": len(daemon_ref.ghost_pty.list_sessions()),
                            "status_etag": etag,
                            "peer": daemon_ref.get_cached_peer_health(),
                            "flows": daemon_ref.list_flows(limit=16),
                            "edge": daemon_ref.edge_stats(),
                            "trinity": daemon_ref.trinity.pulse_summary(),
                            "platform": daemon_ref.platform.pulse_summary(),
                        },
                        extra_headers={"Cache-Control": "no-store"},
                    )
                    return
                if parsed.path == "/api/galactic/tarpit" or parsed.path.startswith("/api/galactic/tarpit/"):
                    if daemon_ref._should_proxy("local=1" in parsed.query):
                        try:
                            sc, ct, rb = daemon_ref.proxy_request("GET", self.path, timeout_s=8.0)
                            self._send_bytes(sc, ct, rb)
                        except Exception as exc:
                            self._send_json(502, {"error": str(exc)})
                        return
                    rel = parsed.path[len("/api/galactic/tarpit"):] or "/"
                    t0_tp = time.perf_counter()
                    tp_data = ProceduralTarpitLabyrinth().inspect_path(rel)
                    daemon_ref.record_flow(
                        "tarpit",
                        "probe",
                        daemon_ref.config.node_name,
                        "TARPIT_0KB",
                        wire_bytes=len(tp_data.get("content", "") or ""),
                        elapsed_ms=(time.perf_counter() - t0_tp) * 1000.0,
                        detail=f"path={rel} disk=0B",
                        ok=True,
                    )
                    self._send_json(
                        200,
                        {
                            "ok": True,
                            "node_name": daemon_ref.config.node_name,
                            "stateless": True,
                            **tp_data,
                        },
                    )
                    return

                if parsed.path == "/api/hyperdrive/search":
                    qs = urllib.parse.parse_qs(parsed.query)
                    q = qs.get("q", [""])[0]
                    limit = max(1, min(50, int(qs.get("limit", ["20"])[0])))
                    local_only = "local=1" in parsed.query
                    res = daemon_ref._get_v9_indexer().search(q, limit=limit)
                    hits = [{"node": daemon_ref.config.node_name, **h} for h in res.get("hits", [])]
                    tot_matches = int(res.get("total_matches", 0))
                    if not local_only and daemon_ref._should_proxy(False):
                        try:
                            pq = f"/api/hyperdrive/search?q={urllib.parse.quote(q)}&limit={limit}&local=1"
                            sc, _, rb = daemon_ref.proxy_request("GET", pq, timeout_s=4.0)
                            if sc == 200:
                                pr = json.loads(rb.decode("utf-8"))
                                p_name = pr.get("node_name", daemon_ref.config.peer_name or "peer")
                                hits.extend({"node": p_name, **h} for h in pr.get("hits", []))
                                tot_matches += int(pr.get("total_matches", 0))
                        except Exception:
                            pass
                    daemon_ref.record_flow(
                        "phantom",
                        daemon_ref.config.node_name,
                        daemon_ref.config.peer_name or daemon_ref.config.node_name,
                        "SPOTLIGHT",
                        wire_bytes=max(32, len(q) + tot_matches * 64),
                        elapsed_ms=float(res.get("elapsed_ms", 0.0)),
                        detail=f"q={q!r} hits={tot_matches}",
                        ok=True,
                    )
                    self._send_json(
                        200,
                        {
                            "ok": True,
                            "node_name": daemon_ref.config.node_name,
                            "query": q,
                            "indexed_files": res.get("indexed_files", 0),
                            "total_matches": tot_matches,
                            "hits": hits[:limit],
                            "elapsed_ms": res.get("elapsed_ms", 0.0),
                        },
                    )
                    return
                if parsed.path == "/api/phantom/status":
                    self._send_json(200, daemon_ref.phantom_status())
                    return
                if parsed.path == "/api/vsa/stats":
                    self._send_json(200, daemon_ref.vsa_memory.stats())
                    return
                if parsed.path == "/api/vsa/export":
                    qs = urllib.parse.parse_qs(parsed.query)
                    dom = (qs.get("domain") or [""])[0].strip() or None
                    lim = int((qs.get("limit") or ["500"])[0] or 500)
                    if self.headers.get("Accept") == "application/x-ndjson":
                        self.send_response(200)
                        self.send_header("Content-Type", "application/x-ndjson")
                        self.send_header("Transfer-Encoding", "chunked")
                        self.send_header("Vary", "Accept")
                        self.end_headers()
                        count = 0
                        try:
                            for row in daemon_ref.vsa_memory.iter_export(domain=dom, limit=lim):
                                line = json.dumps(row, ensure_ascii=False).encode("utf-8")
                                self._write_http_chunk(line + b"\n")
                                count += 1
                            self._write_http_chunk(json.dumps({"end": count}).encode("ascii") + b"\n")
                            self.wfile.write(b"0\r\n\r\n")
                        except OSError:
                            self.close_connection = True
                        return
                    self._send_json(
                        200,
                        {"ok": True, "items": daemon_ref.vsa_memory.export_items(domain=dom, limit=lim)},
                    )
                    return
                if parsed.path == "/api/trinity/governor":
                    self._send_json(200, daemon_ref.host_governor.evaluate_state())
                    return
                if parsed.path == "/api/trinity/status":
                    self._send_json(200, daemon_ref.trinity.snapshot(refresh=True))
                    return
                if parsed.path == "/api/trinity/proofs":
                    qs = urllib.parse.parse_qs(parsed.query)
                    lim = int((qs.get("limit") or ["20"])[0] or 20)
                    self._send_json(200, daemon_ref.trinity.list_proofs(limit=lim))
                    return
                if parsed.path == "/api/overmind/state":
                    self._send_json(
                        200,
                        {
                            "ok": True,
                            "node_id": daemon_ref.config.node_name,
                            "crdt": daemon_ref.overmind.crdt.snapshot(),
                            "pulse": daemon_ref.overmind.pulse.stats(),
                            "flight_recorder": daemon_ref.overmind.flight_recorder.status(),
                        },
                    )
                    return
                if parsed.path == "/api/overmind/pulse":
                    qs = urllib.parse.parse_qs(parsed.query)
                    since_seq = int((qs.get("since_seq") or ["0"])[0] or 0)
                    lim = int((qs.get("limit") or ["50"])[0] or 50)
                    self._send_json(200, daemon_ref.overmind.pulse.poll(since_seq=since_seq, limit=lim))
                    return
                if parsed.path == "/api/overmind/flight-recorder":
                    self._send_json(200, daemon_ref.overmind.flight_recorder.status())
                    return
                if parsed.path == "/api/midbrain/status":
                    self._send_json(200, daemon_ref.overmind.midbrain.status())
                    return
                if parsed.path == "/api/symbiote/status":
                    self._send_json(200, daemon_ref.overmind.symbiote.status())
                    return
                if parsed.path == "/api/symbiote/blob/get":
                    qs = urllib.parse.parse_qs(parsed.query)
                    bkey = str((qs.get("key") or [""])[0] or "").strip()
                    raw = daemon_ref.overmind.symbiote.get_blob(bkey)
                    if raw is None:
                        self._send_json(404, {"ok": False, "error": "not_found", "key": bkey})
                    else:
                        self._send_json(
                            200,
                            {
                                "ok": True,
                                "key": bkey,
                                "raw_bytes_len": len(raw),
                                "data_b64": base64.b64encode(raw).decode("ascii"),
                            },
                        )
                    return
                if parsed.path == "/api/symbiote/kv-affinity":
                    qs = urllib.parse.parse_qs(parsed.query)
                    sid = str((qs.get("session_id") or [""])[0] or "").strip()
                    self._send_json(200, daemon_ref.overmind.symbiote.get_kv_affinity(sid))
                    return
                if parsed.path in (
                    "/api/pty/list",
                    "/api/pty/read",
                    "/api/fs/list",
                    "/api/fs/stat",
                    "/api/fs/read",
                    "/api/fs/git-status",
                    "/api/medic/status",
                    "/api/portal/list",
                    "/api/portal/item",
                    "/api/synergy/status",
                    "/api/synergy/bounties",
                    "/api/synergy/burn-scan",
                    "/api/omega/status",
                    "/api/singularity/status",
                    "/api/hyperdrive/status",
                    "/api/hyperdrive/nvme-meta",
                    "/api/hyperdrive/nvme-block",
                    "/api/hyperdrive/cas",
                    "/api/hyperdrive/hub",
                    "/api/hyperdrive/handoff",
                    "/api/galactic/status",
                ):
                    qs = urllib.parse.parse_qs(parsed.query)
                    if daemon_ref._should_proxy("local=1" in parsed.query):
                        try:
                            sc, ct, rb = daemon_ref.proxy_request("GET", self.path, timeout_s=10.0)
                            self._send_bytes(sc, ct, rb)
                        except Exception as exc:
                            self._send_json(502, {"error": str(exc)})
                        return
                    try:
                        if parsed.path == "/api/pty/list":
                            self._send_json(200, {"sessions": daemon_ref.ghost_pty.list_sessions()})
                        elif parsed.path == "/api/pty/read":
                            sid = qs.get("session_id", [""])[0]
                            cur = int(qs.get("cursor", ["0"])[0])
                            wait_ms = int(qs.get("wait_ms", ["350"])[0])
                            self._send_json(200, daemon_ref.ghost_pty.read_output(sid, cursor=cur, wait_ms=wait_ms))
                        elif parsed.path == "/api/fs/list":
                            rp = qs.get("path", [""])[0]
                            out = daemon_ref.ghost_fs.list_dir(rp)
                            if qs.get("with_self", ["0"])[0] == "1":
                                out["self_entry"] = daemon_ref.ghost_fs.stat_entry(rp)
                            self._send_json(200, out)
                        elif parsed.path == "/api/fs/stat":
                            rp = qs.get("path", [""])[0]
                            self._send_json(200, daemon_ref.ghost_fs.stat_entry(rp))
                        elif parsed.path == "/api/fs/read":
                            rp = qs.get("path", [""])[0]
                            self._send_json(200, daemon_ref.ghost_fs.read_file(rp))
                        elif parsed.path == "/api/fs/git-status":
                            rp = qs.get("repo", [""])[0]
                            self._send_json(200, daemon_ref.ghost_fs.git_status(rp))
                        elif parsed.path == "/api/medic/status":
                            self._send_json(200, daemon_ref.medic.status())
                        elif parsed.path == "/api/portal/list":
                            self._send_json(200, {"items": daemon_ref.drop_portal.list_items()})
                        elif parsed.path == "/api/portal/item":
                            iid = qs.get("item_id", [""])[0]
                            meta, raw_data = daemon_ref.drop_portal.get_item(iid)
                            if qs.get("raw", ["0"])[0] == "1":
                                self._send_bytes(200, str(meta.get("mime", "application/octet-stream")), raw_data)
                            else:
                                self._send_json(200, {**meta, "data_b64": base64.b64encode(raw_data).decode("ascii")})
                        elif parsed.path == "/api/synergy/status":
                            self._send_json(200, daemon_ref.synergy.evaluate_quota_arbiter(apply_policy=False))
                        elif parsed.path == "/api/synergy/bounties":
                            lim = int(qs.get("limit", ["25"])[0])
                            self._send_json(200, daemon_ref.synergy.list_ready_bounties(limit=lim))
                        elif parsed.path == "/api/synergy/burn-scan":
                            rep_th = int(qs.get("repeat_threshold", ["3"])[0])
                            self._send_json(200, daemon_ref.synergy.scan_solver_burn_loops(repeat_threshold=rep_th))
                        elif parsed.path == "/api/omega/status":
                            from .native import v7_native_caps

                            self._send_json(
                                200,
                                {
                                    "ok": True,
                                    "version": "7.0.0",
                                    "node_name": daemon_ref.config.node_name,
                                    "role": daemon_ref.config.role,
                                    "native_v7": v7_native_caps(),
                                    "os_tun_caps": detect_os_tun_caps(),
                                    "fs_mount_caps": detect_fs_mount_caps(),
                                    "remote_ram": daemon_ref.remote_ram.stats(),
                                },
                            )
                        elif parsed.path == "/api/singularity/status":
                            from .native import v7_native_caps, v8_native_caps

                            self._send_json(
                                200,
                                {
                                    "ok": True,
                                    "version": "8.0.0",
                                    "node_name": daemon_ref.config.node_name,
                                    "role": daemon_ref.config.role,
                                    "native_v7": v7_native_caps(),
                                    "native_v8": v8_native_caps(),
                                    "pir_db_loaded": daemon_ref._pir_slab is not None,
                                    "time_warp_throttled": daemon_ref.time_warp.throttled,
                                    "zero_weight": get_zero_weight_status(),
                                },
                            )
                        elif parsed.path == "/api/hyperdrive/status":
                            self._send_json(
                                200,
                                {
                                    "ok": True,
                                    "version": "12.0.0",
                                    "node_name": daemon_ref.config.node_name,
                                    "role": daemon_ref.config.role,
                                    "native_v9": v9_native_caps(),
                                    "mount_drivers": probe_mount_drivers(),
                                    "accelerators": probe_accelerators(),
                                    "hw_encoders": probe_hw_encoders(),
                                    "cas_stats": daemon_ref._get_v9_cas().stats(),
                                    "hub_count": len(daemon_ref._get_v9_hub().list_items(limit=64)),
                                    "zero_weight": get_zero_weight_status(),
                                },
                            )
                        elif parsed.path == "/api/hyperdrive/nvme-meta":
                            raw_root = qs.get("root", [""])[0]
                            target_root = daemon_ref._assert_path_allowed(raw_root) if raw_root else daemon_ref.ghost_fs.root_dir
                            nvme = daemon_ref._get_v9_nvme()
                            cnt = nvme.mirror.scan_root(target_root, max_entries=1024)
                            self._send_json(
                                200,
                                {
                                    "ok": True,
                                    "node_name": daemon_ref.config.node_name,
                                    "root": str(target_root),
                                    "count": cnt,
                                    "entries": nvme.mirror.export_snapshot(limit=512),
                                },
                            )
                        elif parsed.path == "/api/hyperdrive/nvme-block":
                            raw_path = qs.get("path", [""])[0]
                            if not raw_path:
                                raise ValueError("path query parameter is required")
                            cand = daemon_ref._assert_path_allowed(raw_path)
                            if ".git" in cand.parts:
                                raise PermissionError("Access to .git denied")
                            if not cand.is_file():
                                raise FileNotFoundError(str(cand))
                            off = max(0, int(qs.get("offset", ["0"])[0]))
                            ln = max(1, min(262144, int(qs.get("length", ["32768"])[0])))
                            with open(cand, "rb") as fh:
                                fh.seek(off)
                                blk = fh.read(ln)
                            self._send_json(
                                200,
                                {
                                    "ok": True,
                                    "path": str(cand),
                                    "offset": off,
                                    "size": len(blk),
                                    "sha256": hashlib.sha256(blk).hexdigest(),
                                    "data_b64": base64.b64encode(blk).decode("ascii"),
                                },
                            )
                        elif parsed.path == "/api/hyperdrive/cas":
                            key_q = qs.get("key", [""])[0].strip().lower()
                            if not key_q:
                                self._send_json(200, {"ok": True, "stats": daemon_ref._get_v9_cas().stats()})
                            else:
                                raw_c = daemon_ref._get_v9_cas().get(key_q)
                                if raw_c is None:
                                    self._send_json(404, {"error": "CAS key not found"})
                                else:
                                    self._send_json(
                                        200,
                                        {
                                            "ok": True,
                                            "key": key_q,
                                            "raw_bytes": len(raw_c),
                                            "data_b64": base64.b64encode(raw_c).decode("ascii"),
                                        },
                                    )
                        elif parsed.path == "/api/hyperdrive/hub":
                            lim = max(1, min(64, int(qs.get("limit", ["25"])[0])))
                            self._send_json(
                                200,
                                {
                                    "ok": True,
                                    "node_name": daemon_ref.config.node_name,
                                    "items": daemon_ref._get_v9_hub().list_items(limit=lim),
                                },
                            )
                        elif parsed.path == "/api/hyperdrive/handoff":
                            self._send_json(
                                200,
                                {
                                    "ok": True,
                                    "node_name": daemon_ref.config.node_name,
                                    "tasks": daemon_ref._get_v9_handoff().list_tasks(),
                                },
                            )
                        elif parsed.path == "/api/galactic/status":
                            self._send_json(
                                200,
                                {
                                    "ok": True,
                                    "version": "12.0.0",
                                    "node_name": daemon_ref.config.node_name,
                                    "role": daemon_ref.config.role,
                                    "native_v9": v9_native_caps(),
                                    "native_v12": v12_native_caps(),
                                    "zero_weight": get_zero_weight_status(),
                                },
                            )
                    except PermissionError as pe:
                        self._send_json(403, {"error": str(pe)})
                    except FileNotFoundError as fnf:
                        self._send_json(404, {"error": str(fnf)})
                    except Exception as exc:
                        self._send_json(400, {"error": str(exc)})
                    return
                if parsed.path == "/api/nat/profile":
                    self._send_json(200, discover_nat_profile())
                    return
                if parsed.path == "/api/nat/session":
                    qs = urllib.parse.parse_qs(parsed.query)
                    tok = qs.get("token", [""])[0]
                    st = daemon_ref.nat_responder.get_session(tok)
                    self._send_json(200 if st else 404, st or {"error": "Session not found"})
                    return
                if parsed.path == "/api/edge/stats":
                    self._send_json(200, daemon_ref.edge_stats())
                    return
                if parsed.path == "/api/sentinel/status":
                    if (
                        daemon_ref.config.role == "controller"
                        and daemon_ref.config.peer_ipv4
                        and "local=1" not in parsed.query
                    ):
                        try:
                            rem = _http_get_json(f"{daemon_ref.peer_http_base()}/api/sentinel/status", timeout_s=4.0)
                            self._send_json(200, rem)
                            return
                        except Exception:
                            pass
                    self._send_json(200, daemon_ref.sentinel.latest_status())
                    return
                if parsed.path == "/api/search/stats":
                    if (
                        daemon_ref.code_search.stats().get("indexed_files", 0) == 0
                        and daemon_ref.config.peer_ipv4
                        and "local=1" not in parsed.query
                    ):
                        try:
                            rem = _http_get_json(f"{daemon_ref.peer_http_base()}/api/search/stats", timeout_s=4.0)
                            self._send_json(200, rem)
                            return
                        except Exception:
                            pass
                    self._send_json(200, daemon_ref.code_search.stats())
                    return
                if parsed.path == "/api/backup/list":
                    self._send_json(200, {"backups": list_holo_backups(daemon_ref.backup_root)})
                    return
                if parsed.path == "/api/backup/shard":
                    qs = urllib.parse.parse_qs(parsed.query)
                    bid = sanitize_workspace_id(qs.get("backup_id", [""])[0])
                    idx_s = qs.get("idx", ["1"])[0]
                    if idx_s not in ("0", "1", "2"):
                        self._send_json(400, {"error": "Invalid shard idx"})
                        return
                    bdir = (daemon_ref.backup_root / bid).resolve()
                    if daemon_ref.backup_root.resolve() not in bdir.parents:
                        self._send_json(403, {"error": "Invalid backup_id"})
                        return
                    cand = bdir / ("export_shard_2.chshard" if idx_s == "2" and (bdir / "export_shard_2.chshard").is_file() else f"shard_{idx_s}.chshard")
                    if not cand.is_file():
                        self._send_json(404, {"error": "Shard not found"})
                        return
                    self._send_shard(cand)
                    return
                if parsed.path == "/api/status":
                    _, raw_json, etag = daemon_ref.get_cached_status()
                    inm = (self.headers.get("If-None-Match") or "").strip()
                    if inm == etag:
                        self.send_response(304)
                        self.send_header("ETag", etag)
                        self.send_header("Cache-Control", "no-cache")
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                        return
                    self._send_bytes(
                        200,
                        "application/json; charset=utf-8",
                        raw_json,
                        extra_headers={"ETag": etag, "Cache-Control": "no-cache"},
                    )
                    return
                if parsed.path == "/api/cluster/report":
                    qs = urllib.parse.parse_qs(parsed.query)
                    fmt = qs.get("format", ["json"])[0]
                    st_payload, _, _ = daemon_ref.get_cached_status()
                    if fmt == "md":
                        md_bytes = format_cluster_markdown_report(st_payload).encode("utf-8")
                        self._send_bytes(
                            200,
                            "text/markdown; charset=utf-8",
                            md_bytes,
                            extra_headers={"Content-Disposition": 'inline; filename="chimera_eval_report.md"'},
                        )
                        return
                    self._send_json(
                        200,
                        {
                            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                            "version": "12.0.0",
                            "cluster": st_payload.get("cluster", {}),
                            "status": st_payload,
                        },
                    )
                    return
                if parsed.path == "/api/immortal/result":
                    qs = urllib.parse.parse_qs(parsed.query)
                    sid = int(qs.get("stream_id", ["0"])[0])
                    st = (
                        daemon_ref._immortal_rx.get_recent_stats(sid)
                        if daemon_ref._immortal_rx is not None
                        else None
                    )
                    self._send_json(200, {"found": st is not None, **(st or {})})
                    return
                if parsed.path == "/api/raw_query_file":
                    qs = urllib.parse.parse_qs(parsed.query)
                    req_path = qs.get("path", [daemon_ref.config.watched_query_file])[0] or "@synthetic"
                    try:
                        raw = daemon_ref._query_srv._load_target_bytes(req_path)  # type: ignore[union-attr]
                    except Exception as exc:
                        self._send_json(400, {"error": str(exc)})
                        return
                    self.send_response(200)
                    self.send_header("Content-Type", "application/octet-stream")
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                    return
                self._send_json(404, {"error": "Not found"})

            def do_POST(self) -> None:
                if not self._allow_management_request():
                    return
                if str(self.headers.get("Host") or "").lower().split(":", 1)[0].endswith(".chimera.local"):
                    host_prox = daemon_ref.platform.handle_host_proxy("POST", self.path, self.headers, self._read_body())
                    if host_prox is not None:
                        self._send_bytes(host_prox[0], host_prox[1], host_prox[2])
                        return
                parsed = urllib.parse.urlparse(self.path)
                if parsed.path == "/mcp":
                    code, resp_obj, hdrs = daemon_ref.omega_spine.mcp.handle_post(self._read_body(), self.headers)
                    if resp_obj is None:
                        self.send_response(code)
                        for hk, hv in hdrs.items():
                            self.send_header(hk, hv)
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                        return
                    self._send_json(code, resp_obj, extra_headers=hdrs)
                    return
                if parsed.path.startswith("/v1/hook/"):
                    event_name = parsed.path[len("/v1/hook/"):].strip("/")
                    try:
                        raw_hk = self._read_body()
                        hk_body = json.loads(raw_hk.decode("utf-8")) if raw_hk.strip() else {}
                        if not isinstance(hk_body, dict):
                            hk_body = {}
                    except Exception:
                        hk_body = {}
                    hk_res = daemon_ref.omega_spine.hooks.handle_event(event_name, hk_body)
                    code = 404 if (isinstance(hk_res, dict) and str(hk_res.get("error", "")).startswith("unknown_hook_event:")) else 200
                    self._send_json(code, hk_res)
                    return
                if parsed.path == "/v1/omega/cage":
                    try:
                        raw_b = self._read_body()
                        body = json.loads(raw_b.decode("utf-8") or "{}") if raw_b.strip() else {}
                        act = str(body.get("action") or "status").strip().lower()
                        cage = daemon_ref.omega_spine.iron_cage
                        if act == "sweep":
                            res = cage.cage_sweep_agent_children(
                                target_names=body.get("target_names"),
                                cpu_rate_pct=int(body.get("cpu_rate_pct") or 75),
                            )
                        elif act == "cage_pid":
                            res = cage.cage_worker_pid(
                                int(body.get("pid") or 0),
                                max_cores_mask=body.get("max_cores_mask"),
                                cpu_rate_pct=int(body.get("cpu_rate_pct") or 75),
                            )
                        elif act == "royal_ui":
                            res = cage.apply_royal_ui_tier(body.get("pids") or [])
                        elif act == "spawn":
                            res = cage.spawn_caged(
                                body.get("cmd") or "",
                                cwd=body.get("cwd") or None,
                                timeout_s=float(body.get("timeout_s") or 30.0),
                                cpu_rate_pct=int(body.get("cpu_rate_pct") or 75),
                                use_singleflight=bool(body.get("use_singleflight", False)),
                            )
                        else:
                            res = cage.status()
                        self._send_json(200, res)
                    except Exception as exc:
                        self._send_json(400, {"ok": False, "error": str(exc)})
                    return
                if parsed.path == "/v1/omega/tournament":
                    try:
                        raw_b = self._read_body()
                        body = json.loads(raw_b.decode("utf-8") or "{}") if raw_b.strip() else {}
                        act = str(body.get("action") or "run").strip().lower()
                        trn = daemon_ref.omega_spine.tournament
                        if act == "promote" or (body.get("promote") and body.get("tournament_id")):
                            res = trn.promote_winner(str(body.get("tournament_id") or ""), force=bool(body.get("force", False)))
                        elif act == "status":
                            res = trn.status()
                        else:
                            res = trn.run(
                                repo=str(body.get("repo") or ""),
                                candidates=list(body.get("candidates") or []),
                                oracle_cmd=body.get("oracle_cmd"),
                                timeout_s=float(body.get("timeout_s") or 30.0),
                                isolation=str(body.get("isolation") or "auto"),
                            )
                        self._send_json(200 if res.get("ok") else 400, res)
                    except Exception as exc:
                        self._send_json(400, {"ok": False, "error": str(exc)})
                    return
                if parsed.path in (
                    "/v1/omega/release/stage",
                    "/v1/omega/release/verify",
                    "/v1/omega/release/receive",
                    "/v1/omega/release/replicate",
                    "/v1/omega/release/desired",
                ):
                    try:
                        raw_b = self._read_body()
                        body = json.loads(raw_b.decode("utf-8") or "{}") if raw_b.strip() else {}
                        rc = daemon_ref.omega_spine.release_conductor
                        if parsed.path.endswith("/stage"):
                            res = rc.stage_release(
                                str(body.get("source_dir") or body.get("repo") or ""),
                                epoch=body.get("epoch") or None,
                                verify=bool(body.get("verify", True)),
                                write_desired=bool(body.get("write_desired", False)),
                            )
                        elif parsed.path.endswith("/verify"):
                            res = rc.verify_standby(str(body.get("epoch") or ""))
                        elif parsed.path.endswith("/receive"):
                            res = rc.receive_release(body)
                        elif parsed.path.endswith("/replicate"):
                            res = rc.replicate_to_peer(
                                str(body.get("epoch") or ""),
                                str(body.get("peer_url") or ""),
                                write_desired=bool(body.get("write_desired", True)),
                            )
                        else:
                            res = rc.write_desired_manifest(
                                str(body.get("epoch") or ""),
                                rollback_epoch=body.get("rollback_epoch") or None,
                                verify_first=bool(body.get("verify_first", True)),
                            )
                        self._send_json(200 if res.get("ok") else 400, res)
                    except Exception as exc:
                        self._send_json(400, {"ok": False, "error": str(exc)})
                    return
                if parsed.path == "/v1/omega/precog":
                    try:
                        raw_b = self._read_body()
                        body = json.loads(raw_b.decode("utf-8") or "{}") if raw_b.strip() else {}
                        act = str(body.get("action") or "status").strip().lower()
                        pc = daemon_ref.omega_spine.precog
                        cid = str(body.get("conversation_id") or "default")
                        repo_arg = str(body.get("repo") or "")
                        fpath = str(body.get("file_path") or body.get("path") or "")
                        if act == "schedule":
                            res = pc.schedule(
                                cid,
                                repo_arg,
                                fpath,
                                enable_dotnet_build=body.get("enable_dotnet_build"),
                                enable_pytest=body.get("enable_pytest"),
                            )
                        elif act == "verify":
                            res = pc.verify_file_now(
                                cid,
                                repo_arg,
                                fpath,
                                enable_dotnet_build=body.get("enable_dotnet_build"),
                                enable_pytest=body.get("enable_pytest"),
                            )
                        elif act == "consume":
                            diags = pc.consume_diagnostics(cid, repo_arg or None)
                            res = {"ok": True, "conversation_id": cid, "count": len(diags), "diagnostics": diags}
                        elif act == "blocking":
                            errs = pc.get_blocking_errors(cid, repo_arg or None)
                            res = {"ok": True, "conversation_id": cid, "has_blocking_errors": bool(errs), "errors": errs}
                        else:
                            res = pc.status()
                        self._send_json(200, res)
                    except Exception as exc:
                        self._send_json(400, {"ok": False, "error": str(exc)})
                    return
                if parsed.path in (
                    "/v1/openai/v1/chat/completions",
                    "/v1/openai/v1/responses",
                    "/v1/openai/v1/completions",
                ):
                    if daemon_ref.platform.handle_openai_post_stream(
                        self,
                        parsed,
                        self._read_body(),
                        self.headers,
                    ):
                        return
                if parsed.path.startswith("/v1/"):
                    plat_res = daemon_ref.platform.handle_post(
                        parsed,
                        self._read_body(),
                        self.headers,
                        client_ip=str(self.client_address[0] if self.client_address else "127.0.0.1"),
                    )
                    if plat_res is not None:
                        self._send_json(plat_res[0], plat_res[1])
                        return
                if parsed.path == "/api/tcp_sink":
                    t0 = time.perf_counter()
                    clen = int(self.headers.get("Content-Length", "0"))
                    rem = clen
                    hasher = hashlib.sha256()
                    while rem > 0:
                        chunk = self.rfile.read(min(65536, rem))
                        if not chunk:
                            break
                        hasher.update(chunk)
                        rem -= len(chunk)
                    ms = (time.perf_counter() - t0) * 1000.0
                    self._send_json(
                        200,
                        {"bytes": clen - rem, "sha256": hasher.hexdigest(), "server_ms": round(ms, 2)},
                    )
                    return

                if parsed.path == "/api/run":
                    sync = "sync=1" in parsed.query
                    if sync:
                        rep = daemon_ref.run_cycle(trigger="manual_dashboard")
                        self._send_json(200, rep)
                    else:
                        threading.Thread(
                            target=daemon_ref.run_cycle,
                            kwargs={"trigger": "manual_dashboard"},
                            daemon=True,
                        ).start()
                        self._send_json(202, {"queued": True})
                    return

                if parsed.path == "/api/cluster/ingest":
                    try:
                        body = json.loads(self._read_body().decode("utf-8"))
                        if not body.get("node_name") or not body.get("ts_local"):
                            self._send_json(400, {"error": "Missing node_name or ts_local"})
                            return
                        rid = daemon_ref.store.record_cluster_report(body)
                        daemon_ref.store.log_event(
                            "INFO",
                            "CLUSTER",
                            f"Ingested report #{rid} from {body.get('node_name')} score={body.get('health_score')}",
                        )
                        daemon_ref.invalidate_status_cache()
                        self._send_json(200, {"ok": True, "report_id": rid})
                    except Exception as exc:
                        self._send_json(400, {"error": str(exc)})
                    return

                if parsed.path == "/api/profile":
                    try:
                        body = json.loads(self._read_body().decode("utf-8"))
                        prof = str(body.get("active_profile", ""))
                        if prof not in VALID_PROFILES:
                            self._send_json(400, {"error": f"Invalid profile: {prof}"})
                            return
                        daemon_ref.config.active_profile = prof
                        daemon_ref.config.save(daemon_ref.ops_dir)
                        daemon_ref.store.log_event("INFO", "CONFIG", f"Switched profile -> {prof}")
                        daemon_ref.invalidate_status_cache()
                        self._send_json(200, {"active_profile": prof})
                    except Exception as exc:
                        self._send_json(400, {"error": str(exc)})
                    return

                if parsed.path == "/api/merkle/diff":
                    try:
                        body = json.loads(self._read_body().decode("utf-8") or "{}")
                        ws_id = sanitize_workspace_id(str(body.get("workspace_id", "default")))
                        ws_dir = daemon_ref.merkle_root / ws_id
                        snap = ShadowMerkleIndex().scan(ws_dir)
                        diff = diff_manifests(
                            local_files=body.get("files", {}),
                            local_root=str(body.get("root_hash", "")),
                            remote_files=snap.files,
                            remote_root=snap.root_hash,
                        )
                        diff["remote_root_hash"] = snap.root_hash
                        diff["workspace_id"] = ws_id
                        self._send_json(200, diff)
                    except Exception as exc:
                        self._send_json(400, {"error": str(exc)})
                    return

                if parsed.path == "/api/telepathy/train":
                    try:
                        body = json.loads(self._read_body().decode("utf-8") or "{}")
                        fpath = str(body.get("file_path") or daemon_ref.config.watched_query_file or "@synthetic")
                        domain = str(body.get("domain", "default"))
                        raw = daemon_ref._query_srv._load_target_bytes(fpath)  # type: ignore[union-attr]
                        d = train_domain_dictionary([raw[: 512 * 1024]], domain=domain)
                        daemon_ref.telepathy_store.put(d)
                        daemon_ref.store.log_event(
                            "INFO", "TELEPATHY", f"Trained dict={d.dict_id} ({len(d.zdict)}B) for {domain}"
                        )
                        daemon_ref.invalidate_status_cache()
                        self._send_json(200, d.to_wire_dict())
                    except Exception as exc:
                        self._send_json(400, {"error": str(exc)})
                    return

                if parsed.path == "/api/live-merkle":
                    try:
                        body = json.loads(self._read_body().decode("utf-8") or "{}")
                        ws_id = sanitize_workspace_id(str(body.get("workspace_id", "autopilot_demo")))
                        local_dir_arg = str(body.get("local_dir", ""))
                        if local_dir_arg:
                            target_dir = Path(local_dir_arg).resolve()
                        else:
                            target_dir = prepare_merkle_demo_workspace(daemon_ref.ops_dir)
                        peer_ip = daemon_ref.config.peer_ipv4 or "127.0.0.1"
                        peer_bport = (
                            daemon_ref.config.peer_beam_port
                            if daemon_ref.config.peer_ipv4
                            else daemon_ref.config.beam_port
                        )
                        peer_http = (
                            f"http://{peer_ip}:{daemon_ref.config.peer_dashboard_port}"
                            if daemon_ref.config.peer_ipv4
                            else f"http://127.0.0.1:{daemon_ref.http_addr[1]}"
                        )
                        rep1 = merkle_beam_sync(
                            peer_http_base=peer_http,
                            peer_beam_addr=(peer_ip, peer_bport),
                            local_dir=target_dir,
                            workspace_id=ws_id,
                            vault_dir=daemon_ref.ops_dir / "tx_vault",
                            shadow_dir=daemon_ref.ops_dir / "merkle_shadows",
                            est_loss=0.02,
                        )
                        rep2 = merkle_beam_sync(
                            peer_http_base=peer_http,
                            peer_beam_addr=(peer_ip, peer_bport),
                            local_dir=target_dir,
                            workspace_id=ws_id,
                            vault_dir=daemon_ref.ops_dir / "tx_vault",
                            shadow_dir=daemon_ref.ops_dir / "merkle_shadows",
                            est_loss=0.02,
                        )
                        rep1["second_pass_noop"] = rep2["noop"]
                        rep1["second_pass_ms"] = rep2["elapsed_ms"]
                        daemon_ref.store.log_event(
                            "INFO",
                            "MERKLE",
                            f"Sync ws={ws_id} changed={rep1['changed_files']}/{rep1['total_files']} wire={rep1['udp_wire_bytes']}B 2nd_noop={rep2['noop']}({rep2['elapsed_ms']}ms)",
                        )
                        daemon_ref.invalidate_status_cache()
                        self._send_json(200, rep1)
                    except Exception as exc:
                        self._send_json(500, {"error": str(exc)})
                    return

                if parsed.path == "/api/live-fluid":
                    try:
                        body = json.loads(self._read_body().decode("utf-8") or "{}")
                        op = str(body.get("op", "log_analytics"))
                        fpath = str(
                            body.get("file_path")
                            or daemon_ref.config.watched_query_file
                            or "@synthetic"
                        )
                        peer_ip = daemon_ref.config.peer_ipv4 or "127.0.0.1"
                        peer_qport = (
                            daemon_ref.config.peer_query_port
                            if daemon_ref.config.peer_ipv4
                            else daemon_ref.config.query_port
                        )
                        peer_http = (
                            f"http://{peer_ip}:{daemon_ref.config.peer_dashboard_port}"
                            if daemon_ref.config.peer_ipv4
                            else f"http://127.0.0.1:{daemon_ref.http_addr[1]}"
                        )
                        dd: DomainDictionary | None = daemon_ref.telepathy_store.latest_for_domain("watched_log")
                        if dd is None and bool(body.get("use_telepathy", True)) and op in ("filter_lines", "multi_grep", "log_analytics"):
                            try:
                                tr = _http_post_json(
                                    f"{peer_http}/api/telepathy/train",
                                    {"file_path": fpath, "domain": "watched_log"},
                                    timeout_s=8.0,
                                )
                                if tr.get("zdict_b64"):
                                    dd = DomainDictionary.from_wire_dict(tr)
                                    daemon_ref.telepathy_store.put(dd)
                            except Exception:
                                pass

                        plan = ComputePlan(
                            op=op,  # type: ignore[arg-type]
                            needle=str(body.get("needle", "ERROR")),
                            patterns=tuple(body.get("patterns", [])),
                            match_mode="all" if body.get("match_mode") == "all" else "any",
                            regex=bool(body.get("regex", False)),
                            ignore_case=bool(body.get("ignore_case", False)),
                            file_glob=str(body.get("file_glob", "*")),
                            sql=str(body.get("sql", "")),
                            max_rows=int(body.get("max_rows", 200)),
                            use_telepathy=bool(body.get("use_telepathy", True)),
                            dict_id=dd.dict_id if dd else "",
                        )
                        res, meta = remote_active_query(
                            (peer_ip, peer_qport),
                            file_path=fpath,
                            plan=plan,
                            est_loss=0.02,
                            timeout_s=15.0,
                            telepathy_store=daemon_ref.telepathy_store,
                            domain_dict=dd,
                        )
                        out = res.to_dict()
                        out.update(meta)
                        txt = res.output_bytes.decode("utf-8", errors="replace")
                        out["output_preview_text"] = txt[:1600]
                        daemon_ref.store.log_event(
                            "INFO",
                            "FLUID",
                            f"op={op} codec={meta.get('codec_mode')} wire={res.wire_bytes}B (-{res.wire_reduction_pct}%) {res.total_ms}ms",
                        )
                        daemon_ref.invalidate_status_cache()
                        self._send_json(200, out)
                    except Exception as exc:
                        self._send_json(500, {"error": str(exc)})
                    return

                if parsed.path == "/api/live-immortal":
                    try:
                        peer_ip = daemon_ref.config.peer_ipv4 or "127.0.0.1"
                        if daemon_ref.config.peer_ipv4:
                            targets = [(peer_ip, daemon_ref.config.peer_immortal_v4_port)]
                            if daemon_ref.config.peer_ipv6 and daemon_ref.config.peer_immortal_v6_port > 0:
                                targets.append((daemon_ref.config.peer_ipv6, daemon_ref.config.peer_immortal_v6_port))
                            peer_http = f"http://{peer_ip}:{daemon_ref.config.peer_dashboard_port}"
                        else:
                            targets = [
                                ("127.0.0.1", daemon_ref.config.immortal_v4_port),
                                (
                                    "::1" if daemon_ref._immortal_rx and len(daemon_ref._immortal_rx.addrs) > 1 else "127.0.0.1",
                                    daemon_ref.config.immortal_v6_port
                                    if (daemon_ref._immortal_rx and len(daemon_ref._immortal_rx.addrs) > 1)
                                    else daemon_ref.config.immortal_v4_port,
                                ),
                            ]
                            peer_http = f"http://127.0.0.1:{daemon_ref.http_addr[1]}"

                        sid = (int(time.time()) % 200) + 20
                        payload = os.urandom(128 * 1024)
                        irep = ImmortalMultiPathSender(
                            targets, gen_k=32, initial_loss_hint=0.03
                        ).send_stream(
                            payload,
                            stream_id=sid,
                            timeout_s=12.0,
                            chaos_kill_lane=0 if len(targets) >= 2 else None,
                            chaos_kill_after_gens=1,
                        )
                        rx_check: dict[str, Any] = {}
                        for _ in range(5):
                            try:
                                rx_check = _http_get_json(
                                    f"{peer_http}/api/immortal/result?stream_id={sid}", timeout_s=2.0
                                )
                                if rx_check.get("found"):
                                    break
                            except Exception:
                                pass
                            time.sleep(0.05)
                        out = irep.to_dict()
                        out["lane_rx_counts"] = rx_check.get("lane_rx_counts", [])
                        out["peer_sha256_match"] = rx_check.get("sha256") == irep.sha256
                        daemon_ref.store.log_event(
                            "INFO",
                            "IMMORTAL",
                            f"lanes={irep.lanes_total} killed={irep.lanes_killed} tx={irep.lane_tx_counts} rx={out['lane_rx_counts']} ok={out['peer_sha256_match']}",
                        )
                        daemon_ref.invalidate_status_cache()
                        self._send_json(200, out)
                    except Exception as exc:
                        self._send_json(500, {"error": str(exc)})
                    return

                if parsed.path == "/api/live-beam":
                    try:
                        peer_ip = daemon_ref.config.peer_ipv4 or "127.0.0.1"
                        peer_port = (
                            daemon_ref.config.peer_beam_port
                            if daemon_ref.config.peer_ipv4
                            else daemon_ref.config.beam_port
                        )
                        work = daemon_ref.ops_dir / "beam_work"
                        work.mkdir(parents=True, exist_ok=True)
                        bfile = work / "live_button_1mb.bin"
                        data = _build_incremental_sample(1024 * 1024, int(time.time()) % 10000)
                        bfile.write_bytes(data)
                        rep = beam_send(
                            (peer_ip, peer_port),
                            bfile,
                            vault_dir=daemon_ref.ops_dir / "tx_vault",
                            est_loss=0.02,
                            timeout_s=20.0,
                        )
                        daemon_ref.store.log_event(
                            "INFO",
                            "LIVE_BEAM",
                            f"Synced {rep.raw_bytes}B in {rep.elapsed_ms}ms (saved {rep.reduction_pct}%)",
                        )
                        daemon_ref.invalidate_status_cache()
                        self._send_json(200, rep.to_dict())
                    except Exception as exc:
                        self._send_json(500, {"error": str(exc)})
                    return

                if parsed.path == "/api/live-query":
                    try:
                        body = json.loads(self._read_body().decode("utf-8") or "{}")
                        needle = str(body.get("needle", "ERROR"))
                        fpath = str(
                            body.get("file_path")
                            or daemon_ref.config.watched_query_file
                            or "@synthetic"
                        )
                        peer_ip = daemon_ref.config.peer_ipv4 or "127.0.0.1"
                        peer_qport = (
                            daemon_ref.config.peer_query_port
                            if daemon_ref.config.peer_ipv4
                            else daemon_ref.config.query_port
                        )
                        dd = daemon_ref.telepathy_store.latest_for_domain("watched_log")
                        res, meta = remote_active_query(
                            (peer_ip, peer_qport),
                            file_path=fpath,
                            plan=ComputePlan(
                                op="filter_lines",
                                needle=needle,
                                use_telepathy=True,
                                dict_id=dd.dict_id if dd else "",
                            ),
                            est_loss=0.02,
                            timeout_s=15.0,
                            telepathy_store=daemon_ref.telepathy_store,
                            domain_dict=dd,
                        )
                        daemon_ref.store.log_event(
                            "INFO",
                            "LIVE_QUERY",
                            f"needle={needle!r} matched={res.matched_records} wire_saved={res.wire_reduction_pct}% in {res.total_ms}ms",
                        )
                        daemon_ref.invalidate_status_cache()
                        out = res.to_dict()
                        out.update(meta)
                        self._send_json(200, out)
                    except Exception as exc:
                        self._send_json(500, {"error": str(exc)})
                    return

                if parsed.path == "/api/exotic-audit":
                    try:
                        env = probe_environment()
                        if os.name == "nt":
                            rx = ChimeraReceiver(env, droplet_size=20)
                            offer = rx.start()
                            try:
                                tx = ChimeraSender(env, offer)
                                sample = b"CHIMERA-EXOTIC-AUDIT-" + os.urandom(64)
                                rec, rep = tx.send_metamorphic(
                                    rx, sample, FaultProfile(packet_drop_rate=0.2), timeout_s=8.0
                                )
                                res_obj = {
                                    "os": "windows",
                                    "active_realms": env.active_droplet_lanes(),
                                    "sha256_match": rec == sample and rep.sha256_match,
                                    "elapsed_ms": rep.elapsed_ms,
                                }
                            finally:
                                rx.close()
                        else:
                            res_obj = {
                                "os": "linux",
                                "active_realms": list(env.realms.keys()),
                                "note": "8-lane Windows quirks are Windows-specific; Linux runs C AVX2 HyperWire/DNA/Wormhole.",
                            }
                        daemon_ref.store.log_event("INFO", "EXOTIC", json.dumps(res_obj))
                        daemon_ref.invalidate_status_cache()
                        self._send_json(200, res_obj)
                    except Exception as exc:
                        self._send_json(500, {"error": str(exc)})
                    return

                if parsed.path == "/api/nat/punch-offer":
                    try:
                        body = json.loads(self._read_body().decode("utf-8") or "{}")
                        self._send_json(200, daemon_ref.nat_responder.start_session(body))
                    except Exception as exc:
                        self._send_json(400, {"error": str(exc)})
                    return

                if parsed.path == "/api/nat/bust":
                    try:
                        body = json.loads(self._read_body().decode("utf-8") or "{}")
                        peer_base = str(body.get("peer_http") or daemon_ref.peer_http_base())
                        local_tm = bool(body.get("local_test_mode", not bool(daemon_ref.config.peer_ipv4)))
                        n_sock = int(body.get("num_sockets", 192 if not local_tm else 16))
                        spray = int(body.get("spray_count", 900 if not local_tm else 64))
                        res = attempt_direct_punch(
                            peer_http_base=peer_base,
                            num_sockets=n_sock,
                            spray_count=spray,
                            timeout_s=float(body.get("timeout_s", 3.5 if not local_tm else 1.5)),
                            local_test_mode=local_tm,
                        )
                        daemon_ref._last_nat_result = res
                        daemon_ref.store.log_event(
                            "INFO", "NAT_BUSTER", f"mode={res['fallback_mode']} {res['diagnosis']}"
                        )
                        daemon_ref.invalidate_status_cache()
                        self._send_json(200, res)
                    except Exception as exc:
                        self._send_json(500, {"error": str(exc)})
                    return

                if parsed.path == "/api/edge/fetch":
                    try:
                        body = json.loads(self._read_body().decode("utf-8") or "{}")
                        res = daemon_ref.edge_gateway.fetch(
                            app_id=str(body.get("app_id", "chimera")),
                            path=str(body.get("path", "/")),
                            query=str(body.get("query", "")),
                            method=str(body.get("method", "GET")),
                            body_b64=str(body.get("body_b64", "")),
                            content_type=str(body.get("content_type", "")),
                            allow_prefetch=bool(body.get("allow_prefetch", True)),
                            known_dict_ids=list(body.get("known_dict_ids", [])),
                        )
                        self._send_json(200, res)
                    except PermissionError as pe:
                        self._send_json(403, {"error": str(pe)})
                    except KeyError as ke:
                        self._send_json(404, {"error": str(ke)})
                    except Exception as exc:
                        self._send_json(400, {"error": str(exc)})
                    return

                if parsed.path == "/api/sentinel/scan":
                    try:
                        body = json.loads(self._read_body().decode("utf-8") or "{}")
                        if (
                            daemon_ref.config.role == "controller"
                            and daemon_ref.config.peer_ipv4
                            and not bool(body.get("local_only", False))
                        ):
                            rem = _http_post_json(
                                f"{daemon_ref.peer_http_base()}/api/sentinel/scan",
                                {"local_only": True},
                                timeout_s=12.0,
                            )
                            self._send_json(200, rem)
                            return
                        rep = daemon_ref.sentinel.scan(daemon_ref.config)
                        daemon_ref.store.log_event(
                            "WARN" if rep["alert_count"] else "INFO",
                            "SENTINEL",
                            f"status={rep['status']} alerts={rep['alert_count']} logs={len(rep['logs_scanned'])} ({rep['elapsed_ms']}ms)",
                        )
                        daemon_ref.invalidate_status_cache()
                        self._send_json(200, rep)
                    except Exception as exc:
                        self._send_json(500, {"error": str(exc)})
                    return

                if parsed.path == "/api/search/reindex":
                    try:
                        body = json.loads(self._read_body().decode("utf-8") or "{}")
                        if (
                            not body.get("roots")
                            and not daemon_ref.config.search_roots
                            and daemon_ref.config.role == "controller"
                            and daemon_ref.config.peer_ipv4
                            and not bool(body.get("local_only", False))
                        ):
                            rem = _http_post_json(
                                f"{daemon_ref.peer_http_base()}/api/search/reindex",
                                {"local_only": True},
                                timeout_s=30.0,
                            )
                            self._send_json(200, rem)
                            return
                        raw_roots = body.get("roots")
                        if raw_roots:
                            roots = [daemon_ref._assert_path_allowed(str(r)) for r in raw_roots]
                        elif daemon_ref.config.search_roots:
                            roots = [Path(p) for p in daemon_ref.config.search_roots]
                        else:
                            roots = [Path(p) for p in daemon_ref.config.allowed_query_roots] or [daemon_ref.ops_dir]
                        rep = daemon_ref.code_search.incremental_index(roots)
                        daemon_ref.store.log_event(
                            "INFO",
                            "CODE_SEARCH",
                            f"Indexed {rep['total_files']} files (updated={rep['updated']}, skipped={rep['skipped_unchanged']}) in {rep['elapsed_ms']}ms",
                        )
                        daemon_ref.invalidate_status_cache()
                        self._send_json(200, rep)
                    except PermissionError as pe:
                        self._send_json(403, {"error": str(pe)})
                    except Exception as exc:
                        self._send_json(400, {"error": str(exc)})
                    return

                if parsed.path == "/api/search":
                    try:
                        body = json.loads(self._read_body().decode("utf-8") or "{}")
                        if (
                            daemon_ref.code_search.stats().get("indexed_files", 0) == 0
                            and daemon_ref.config.peer_ipv4
                            and not bool(body.get("local_only", False))
                        ):
                            rem = _http_post_json(
                                f"{daemon_ref.peer_http_base()}/api/search",
                                {
                                    "query": body.get("query", ""),
                                    "limit": body.get("limit", 10),
                                    "repo": body.get("repo", ""),
                                    "local_only": True,
                                },
                                timeout_s=8.0,
                            )
                            self._send_json(200, rem)
                            return
                        res = daemon_ref.code_search.search(
                            query=str(body.get("query", "")),
                            limit=int(body.get("limit", 10)),
                            repo=str(body.get("repo", "")),
                        )
                        self._send_json(200, res)
                    except Exception as exc:
                        self._send_json(400, {"error": str(exc)})
                    return

                if parsed.path == "/api/backup/store-shard":
                    try:
                        ct = (self.headers.get("Content-Type") or "").lower()
                        raw_body = self._read_body()
                        if "application/json" in ct or raw_body.lstrip().startswith(b"{"):
                            obj = json.loads(raw_body.decode("utf-8"))
                            shard_bytes = base64.b64decode(str(obj["shard_b64"]).encode("ascii"))
                        else:
                            shard_bytes = raw_body
                        ack = store_received_shard(shard_bytes, daemon_ref.backup_root)
                        daemon_ref.store.log_event(
                            "INFO",
                            "HOLO_BACKUP",
                            f"Stored remote shard #{ack['shard_idx']} for {ack['backup_id']} ({ack['bytes']}B)",
                        )
                        daemon_ref.invalidate_status_cache()
                        self._send_json(200, ack)
                    except Exception as exc:
                        self._send_json(400, {"error": str(exc)})
                    return

                if parsed.path == "/api/backup/create":
                    try:
                        body = json.loads(self._read_body().decode("utf-8") or "{}")
                        raw_paths = body.get("paths")
                        if raw_paths:
                            targets = [daemon_ref._assert_path_allowed(str(p)) for p in raw_paths]
                        elif daemon_ref.config.backup_targets:
                            targets = [Path(p) for p in daemon_ref.config.backup_targets if Path(p).exists()]
                        else:
                            cfg_file = daemon_ref.ops_dir / "config.json"
                            if not cfg_file.exists():
                                daemon_ref.config.save(daemon_ref.ops_dir)
                            targets = [cfg_file]
                        peer_base = (
                            daemon_ref.peer_http_base()
                            if (daemon_ref.config.peer_ipv4 and not bool(body.get("no_sync", False)))
                            else ""
                        )
                        rep = create_holo_backup(
                            paths=targets,
                            backup_root=daemon_ref.backup_root,
                            backup_id=str(body.get("backup_id", "")),
                            peer_http_base=peer_base,
                        )
                        daemon_ref.store.log_event(
                            "INFO",
                            "HOLO_BACKUP",
                            f"Created (2,3) GF256 {rep['backup_id']} raw={rep['raw_bytes']}B shard={rep['shard_bytes']}B peer_synced={rep['peer_synced']}",
                        )
                        daemon_ref.invalidate_status_cache()
                        self._send_json(200, rep)
                    except PermissionError as pe:
                        self._send_json(403, {"error": str(pe)})
                    except Exception as exc:
                        self._send_json(400, {"error": str(exc)})
                    return

                if parsed.path == "/api/backup/restore":
                    try:
                        body = json.loads(self._read_body().decode("utf-8") or "{}")
                        broot = daemon_ref.backup_root.resolve()
                        shards_raw = body.get("shard_paths", [])
                        if len(shards_raw) < 2:
                            self._send_json(400, {"error": "Provide at least 2 shard_paths"})
                            return
                        shard_paths: list[Path] = []
                        for sp in shards_raw:
                            cand = Path(str(sp)).resolve()
                            if broot not in cand.parents or not cand.is_file():
                                raise PermissionError(f"Invalid shard path outside backup_root: {sp}")
                            shard_paths.append(cand)
                        bid = sanitize_backup_id(str(body.get("backup_id", shard_paths[0].parent.name)))
                        out_dir = daemon_ref.backup_root / "restored" / bid
                        rep = restore_holo_backup(shard_paths, out_dir=out_dir)
                        self._send_json(200, rep)
                    except PermissionError as pe:
                        self._send_json(403, {"error": str(pe)})
                    except Exception as exc:
                        self._send_json(400, {"error": str(exc)})
                    return

                if parsed.path == "/api/phantom/offer":
                    try:
                        # Authenticate remote Phantom offers when a cluster peer.secret is configured
                        client_ip = str(self.client_address[0] if self.client_address else "")
                        is_loop = client_ip in ("127.0.0.1", "::1", "localhost")
                        if not is_loop or os.environ.get("CHIMERA_REQUIRE_PEER_AUTH") == "1":
                            from .platform.peer_guard import verify_peer_auth

                            if not verify_peer_auth(self.headers.get("X-Chimera-Peer-Auth")):
                                self._send_json(403, {"error": "phantom_peer_auth_required"})
                                return
                        body = json.loads(self._read_body().decode("utf-8") or "{}")
                        if daemon_ref._phantom_srv is None:
                            self._send_json(503, {"error": "PhantomTunnelServer not enabled on node"})
                            return
                        self._send_json(200, daemon_ref._phantom_srv.accept_offer(body))
                    except Exception as exc:
                        self._send_json(400, {"error": str(exc)})
                    return

                if parsed.path == "/api/phantom/connect":
                    try:
                        body = json.loads(self._read_body().decode("utf-8") or "{}")
                        if daemon_ref._phantom_client is None:
                            peer_ip = daemon_ref.config.peer_ipv4 or "127.0.0.1"
                            daemon_ref._phantom_client = PhantomTunnelClient(
                                peer_http_base=daemon_ref.peer_http_base(),
                                peer_udp_ip=peer_ip,
                                peer_fallback_port=int(daemon_ref.config.phantom_fallback_port),
                                forwards={
                                    int(daemon_ref.config.phantom_ssh_port): 22,
                                    int(daemon_ref.config.phantom_http_port): int(daemon_ref.config.peer_dashboard_port or daemon_ref.http_addr[1]),
                                },
                                local_test_mode=bool(body.get("local_test_mode", not bool(daemon_ref.config.peer_ipv4))),
                                allowed_reverse_ports=list(
                                    getattr(daemon_ref.config, "phantom_reverse_allowed_ports", [9780, 12500, 12504])
                                ) + [int(daemon_ref.http_addr[1])],
                            ).start_listeners()
                        res = daemon_ref._phantom_client.connect(
                            local_test_mode=bool(body.get("local_test_mode", daemon_ref._phantom_client.local_test_mode)),
                            num_sockets=int(body.get("num_sockets", 192)),
                            spray_count=int(body.get("spray_count", 900)),
                            timeout_s=float(body.get("timeout_s", 3.5)),
                        )
                        daemon_ref.store.log_event(
                            "INFO", "PHANTOM", f"mode={res['mode']} RTT={res['direct_rtt_ms']}ms conns={res['listeners']}"
                        )
                        daemon_ref.record_flow(
                            "phantom",
                            daemon_ref.config.node_name,
                            daemon_ref.config.peer_name or "svhome",
                            "PHANTOM_5MS",
                            wire_bytes=len(json.dumps(res)),
                            elapsed_ms=float(res.get("direct_rtt_ms", 0.0)),
                            detail=f"{res.get('mode')} ports={res.get('listeners')}",
                            ok=bool(res.get("connected")),
                        )
                        daemon_ref.invalidate_status_cache()
                        self._send_json(200, res)
                    except Exception as exc:
                        self._send_json(500, {"error": str(exc)})
                    return

                if parsed.path == "/api/phantom/disconnect":
                    if daemon_ref._phantom_client is not None:
                        st = daemon_ref._phantom_client.disconnect()
                        daemon_ref.invalidate_status_cache()
                        self._send_json(200, st)
                    else:
                        self._send_json(200, {"connected": False, "mode": "DISCONNECTED"})
                    return

                if parsed.path in (
                    "/api/pty/create",
                    "/api/pty/write",
                    "/api/pty/resize",
                    "/api/pty/close",
                    "/api/fs/write",
                    "/api/medic/investigate",
                    "/api/medic/heal",
                    "/api/portal/drop",
                    "/api/portal/delete",
                    "/api/context/pack",
                    "/api/synergy/surgical-brief",
                    "/api/synergy/burn-scan",
                    "/api/synergy/circuit-break",
                    "/api/synergy/bounty-drop",
                    "/api/synergy/vault-backup",
                    "/api/synergy/arbiter",
                    "/api/omega/wasm-exec",
                    "/api/omega/ram-put",
                    "/api/omega/ram-get",
                    "/api/omega/slepian-sync",
                    "/api/omega/regen-vault",
                    "/api/singularity/pir-shard",
                    "/api/singularity/speculative-fetch",
                    "/api/singularity/crdt-merge",
                    "/api/singularity/dual-vault",
                    "/api/singularity/kolmogorov",
                    "/api/singularity/airgap",
                    "/api/singularity/swarm",
                    "/api/hyperdrive/grid-exec",
                    "/api/hyperdrive/handoff",
                    "/api/hyperdrive/nvme-delta",
                    "/api/hyperdrive/cas",
                    "/api/hyperdrive/hub",
                    "/api/galactic/frost-sign",
                    "/api/galactic/wasm-resume",
                    "/api/galactic/vsa-query",
                ):
                    raw_b = self._read_body()
                    try:
                        body = json.loads(raw_b.decode("utf-8") or "{}")
                    except Exception:
                        self._send_json(400, {"error": "Invalid JSON body"})
                        return
                    if daemon_ref._should_proxy(bool(body.get("local_only", False))):
                        try:
                            sc, ct, rb = daemon_ref.proxy_request("POST", self.path, body_bytes=raw_b, timeout_s=20.0)
                            self._send_bytes(sc, ct, rb)
                        except Exception as exc:
                            self._send_json(502, {"error": str(exc)})
                        return
                    try:
                        if parsed.path == "/api/pty/create":
                            self._send_json(
                                200,
                                daemon_ref.ghost_pty.create_session(
                                    cwd=str(body.get("cwd", "")),
                                    cols=int(body.get("cols", 100)),
                                    rows=int(body.get("rows", 30)),
                                ),
                            )
                        elif parsed.path == "/api/pty/write":
                            sid = str(body.get("session_id", ""))
                            data_b = base64.b64decode(body["data_b64"].encode("ascii")) if body.get("data_b64") else str(body.get("text", "")).encode("utf-8")
                            self._send_json(200, daemon_ref.ghost_pty.write_input(sid, data_b))
                        elif parsed.path == "/api/pty/resize":
                            self._send_json(
                                200,
                                daemon_ref.ghost_pty.resize(str(body.get("session_id", "")), int(body.get("cols", 100)), int(body.get("rows", 30))),
                            )
                        elif parsed.path == "/api/pty/close":
                            self._send_json(200, {"closed": daemon_ref.ghost_pty.close_session(str(body.get("session_id", "")))})
                        elif parsed.path == "/api/fs/write":
                            raw_f = base64.b64decode(body["content_b64"].encode("ascii")) if body.get("content_b64") else str(body.get("text", "")).encode("utf-8")
                            self._send_json(
                                200,
                                daemon_ref.ghost_fs.write_file(
                                    rel_path=str(body.get("path", "")),
                                    content=raw_f,
                                    expected_etag=str(body.get("expected_etag", "")),
                                ),
                            )
                        elif parsed.path == "/api/medic/investigate":
                            self._send_json(
                                200,
                                daemon_ref.medic.investigate(
                                    daemon_ref.config,
                                    file_path=str(body.get("file_path", "")),
                                    pattern=str(body.get("pattern", "ERROR")),
                                ),
                            )
                        elif parsed.path == "/api/medic/heal":
                            rep = daemon_ref.medic.run_playbook(
                                playbook_id=str(body.get("playbook_id", "")),
                                config=daemon_ref.config,
                                params=dict(body.get("params") or {}),
                                backup_root=daemon_ref.backup_root,
                                code_search=daemon_ref.code_search,
                            )
                            daemon_ref.store.log_event("INFO", "MEDIC", f"playbook={rep['playbook_id']} dry={rep['dry_run']} ({rep['elapsed_ms']}ms)")
                            daemon_ref.invalidate_status_cache()
                            self._send_json(200, rep)
                        elif parsed.path == "/api/portal/drop":
                            data_b = base64.b64decode(body["data_b64"].encode("ascii")) if body.get("data_b64") else str(body.get("text", "")).encode("utf-8")
                            meta = daemon_ref.drop_portal.put_item(
                                title=str(body.get("title", "drop")),
                                data=data_b,
                                kind=str(body.get("kind", "text")),
                                mime=str(body.get("mime", "text/plain; charset=utf-8")),
                                ttl_s=int(body["ttl_s"]) if body.get("ttl_s") else None,
                            )
                            daemon_ref.invalidate_status_cache()
                            self._send_json(200, meta)
                        elif parsed.path == "/api/portal/delete":
                            self._send_json(200, {"deleted": daemon_ref.drop_portal.delete_item(str(body.get("item_id", "")))})
                        elif parsed.path == "/api/context/pack":
                            res = pack_ai_context(
                                query=str(body.get("query", "")),
                                code_search=daemon_ref.code_search,
                                sentinel=daemon_ref.sentinel,
                                allowed_roots=daemon_ref._allowed_roots(),
                                repo=str(body.get("repo", "")),
                                max_chars=int(body.get("max_chars", 8000)),
                            )
                            self._send_json(200, res)
                        elif parsed.path == "/api/synergy/surgical-brief":
                            self._send_json(
                                200,
                                daemon_ref.synergy.build_surgical_brief(
                                    workspace_dir=str(body.get("workspace_dir", "")),
                                    issue_title=str(body.get("issue_title", "")),
                                    issue_body=str(body.get("issue_body", "")),
                                    max_chars=int(body.get("max_chars", 7200)),
                                    inject=bool(body.get("inject", False)),
                                ),
                            )
                        elif parsed.path == "/api/synergy/burn-scan":
                            self._send_json(
                                200,
                                daemon_ref.synergy.scan_solver_burn_loops(
                                    workspaces_root=str(body.get("workspaces_root", "")),
                                    repeat_threshold=int(body.get("repeat_threshold", 3)),
                                ),
                            )
                        elif parsed.path == "/api/synergy/circuit-break":
                            self._send_json(
                                200,
                                daemon_ref.synergy.trip_circuit_breaker(
                                    workspace_id=str(body.get("workspace_id", "")),
                                    drop_portal=daemon_ref.drop_portal,
                                    workspaces_root=str(body.get("workspaces_root", "")),
                                    repeat_threshold=int(body.get("repeat_threshold", 3)),
                                    terminate_stuck=bool(body.get("terminate_stuck", False)),
                                ),
                            )
                        elif parsed.path == "/api/synergy/bounty-drop":
                            self._send_json(
                                200,
                                daemon_ref.synergy.publish_bounty_to_portal(
                                    workspace_id=str(body.get("workspace_id", "")),
                                    drop_portal=daemon_ref.drop_portal,
                                    workspaces_root=str(body.get("workspaces_root", "")),
                                    dav_base=str(body.get("dav_base", "http://127.0.0.1:9788/dav")),
                                ),
                            )
                        elif parsed.path == "/api/synergy/vault-backup":
                            peer_url = str(body.get("peer_http_base") or (daemon_ref.peer_http_base() if daemon_ref.config.peer_ipv4 else ""))
                            rep_v = daemon_ref.synergy.backup_apex_vault(
                                backup_root=daemon_ref.backup_root,
                                peer_http_base=peer_url,
                                include_radar_db=bool(body.get("include_radar_db", True)),
                            )
                            daemon_ref.invalidate_status_cache()
                            self._send_json(200, rep_v)
                        elif parsed.path == "/api/synergy/arbiter":
                            self._send_json(
                                200,
                                daemon_ref.synergy.evaluate_quota_arbiter(apply_policy=bool(body.get("apply_policy", True))),
                            )
                        elif parsed.path == "/api/omega/wasm-exec":
                            wasm_b = (
                                base64.b64decode(body["wasm_b64"])
                                if body.get("wasm_b64")
                                else build_wasm_byte_counter_module(int(body.get("target_byte", 10)))
                            )
                            if body.get("input_b64"):
                                inp_b = base64.b64decode(body["input_b64"])
                            else:
                                inp_b = str(body.get("input_text") or ("INFO ok\nERR\n" * 300)).encode("utf-8")
                            vm = WasmActivePipe(max_steps=int(body.get("max_steps", 2_000_000)))
                            res = vm.execute_buffer(wasm_b, inp_b, fn_name=str(body.get("fn_name", "filter")))
                            res["executed_on"] = daemon_ref.config.node_name
                            self._send_json(200, res)
                        elif parsed.path == "/api/omega/ram-put":
                            pid = str(body.get("page_id") or "page_0")
                            if body.get("comp_hex"):
                                out = daemon_ref.remote_ram.put_page(
                                    pid,
                                    bytes.fromhex(str(body["comp_hex"])),
                                    raw_len=int(body.get("raw_len") or 4096),
                                    compressed=True,
                                )
                            else:
                                raw_b = base64.b64decode(body["data_b64"]) if body.get("data_b64") else str(body.get("text", "OMEGA_PAGE")).encode("utf-8")
                                out = daemon_ref.remote_ram.put_page(pid, raw_b, compressed=False)
                            out["node_name"] = daemon_ref.config.node_name
                            self._send_json(200, out)
                        elif parsed.path == "/api/omega/ram-get":
                            pid = str(body.get("page_id") or "page_0")
                            raw_only = bool(body.get("raw_only", False))
                            got = daemon_ref.remote_ram.get_page(pid, decompress=not raw_only)
                            if not got.get("ok"):
                                self._send_json(404, got)
                            elif raw_only:
                                self._send_json(
                                    200,
                                    {
                                        "ok": True,
                                        "page_id": pid,
                                        "raw_bytes": got["raw_bytes"],
                                        "stored_bytes": got["stored_bytes"],
                                        "comp_hex": got["comp"].hex(),
                                        "sha_blake2s": got["sha_blake2s"],
                                        "node_name": daemon_ref.config.node_name,
                                    },
                                )
                            else:
                                self._send_json(
                                    200,
                                    {
                                        "ok": True,
                                        "page_id": pid,
                                        "raw_bytes": got["raw_bytes"],
                                        "stored_bytes": got["stored_bytes"],
                                        "data_b64": base64.b64encode(got["data"]).decode("ascii"),
                                        "sha_blake2s": got["sha_blake2s"],
                                        "node_name": daemon_ref.config.node_name,
                                    },
                                )
                        elif parsed.path == "/api/omega/slepian-sync":
                            old_b = (
                                base64.b64decode(body["old_b64"])
                                if body.get("old_b64")
                                else str(body.get("old_text") or ("SLEPIAN_SYNC_BASE_" * 400)).encode("utf-8")
                            )
                            if body.get("packet_b64"):
                                pkt = base64.b64decode(body["packet_b64"])
                                dec = SlepianWolfSync.decode_blind_packet(old_b, pkt)
                            else:
                                if body.get("new_b64"):
                                    new_b = base64.b64decode(body["new_b64"])
                                else:
                                    tmp = bytearray(old_b)
                                    tmp[1024:1056] = b"OMEGA_0RTT_SLEPIAN_BLIND_PATCH_1"
                                    new_b = bytes(tmp)
                                pkt = SlepianWolfSync.encode_blind_packet(new_b, block_len=512, max_err_blocks=3)
                                dec = SlepianWolfSync.decode_blind_packet(old_b, pkt)
                                dec["bit_exact"] = dec.get("decoded") == new_b
                            dec_clean = {k: v for k, v in dec.items() if k != "decoded"}
                            if body.get("return_decoded"):
                                dec_clean["decoded_b64"] = base64.b64encode(dec.get("decoded", b"")).decode("ascii")
                            dec_clean["node_name"] = daemon_ref.config.node_name
                            self._send_json(200, dec_clean)
                        elif parsed.path == "/api/omega/regen-vault":
                            raw_b = base64.b64decode(body["data_b64"]) if body.get("data_b64") else str(body.get("text") or ("REGEN_VAULT_SECRET_" * 64)).encode("utf-8")
                            mv = RegeneratingMeshVault(k=int(body.get("k", 3)), n=int(body.get("n", 5)))
                            enc = mv.encode_shards(raw_b)
                            miss_idx = int(body.get("missing_idx", 1))
                            avail = [s for s in enc["shards"] if s["node_idx"] != miss_idx][: mv.k]
                            healed = mv.repair_missing_shard(avail, target_node_idx=miss_idx)
                            rec = mv.decode_shards([healed] + avail[: mv.k - 1])
                            self._send_json(
                                200,
                                {
                                    "ok": rec == raw_b and healed["sha256"] == enc["shards"][miss_idx]["sha256"],
                                    "k": mv.k,
                                    "n": mv.n,
                                    "healed_node": miss_idx,
                                    "repair_ms": healed["repair_ms"],
                                    "entropy": healed["entropy"],
                                    "shard_bytes": len(healed["data"]),
                                },
                            )
                        elif parsed.path == "/api/singularity/pir-shard":
                            from .native import pir_xor_query

                            n_rec = int(body.get("n_records", 2048))
                            r_len = int(body.get("rec_len", 512))
                            with daemon_ref._pir_lock:
                                if daemon_ref._pir_slab is None or len(daemon_ref._pir_slab) != n_rec * r_len:
                                    daemon_ref._pir_slab = build_deterministic_pir_db(n_rec, r_len)
                                db_buf = daemon_ref._pir_slab
                            q_bytes = bytes.fromhex(str(body["query_hex"])) if body.get("query_hex") else b"\x55" * ((n_rec + 7) // 8)
                            t_pir = time.perf_counter()
                            ans = pir_xor_query(db_buf, n_rec, r_len, q_bytes)
                            scan_ms = round((time.perf_counter() - t_pir) * 1000.0, 4)
                            self._send_json(
                                200,
                                {
                                    "ok": len(ans) == r_len,
                                    "node_name": daemon_ref.config.node_name,
                                    "n_records": n_rec,
                                    "rec_len": r_len,
                                    "ans_hex": ans.hex(),
                                    "scan_ms": scan_ms,
                                },
                            )
                        elif parsed.path == "/api/singularity/speculative-fetch":
                            key_name = str(body.get("key") or "mod_00.py")
                            ver_tag = str(body.get("version_tag") or "v1")
                            plen = max(16, min(65536, int(body.get("payload_len", 800))))
                            seed_b = (f"# remote {key_name} {ver_tag}\n".encode("utf-8") * ((plen // 20) + 3))[:plen]
                            self._send_json(
                                200,
                                {
                                    "ok": True,
                                    "node_name": daemon_ref.config.node_name,
                                    "key": key_name,
                                    "version_tag": ver_tag,
                                    "data_hex": seed_b.hex(),
                                    "sha256": hashlib.sha256(seed_b).hexdigest(),
                                },
                            )
                        elif parsed.path == "/api/singularity/crdt-merge":
                            out_c = MerkleCrdtShadowTwin.run_benchmark()
                            out_c["node_name"] = daemon_ref.config.node_name
                            self._send_json(200, out_c)
                        elif parsed.path == "/api/singularity/dual-vault":
                            out_v = PlausibleDeniabilityVault.run_benchmark()
                            out_v["node_name"] = daemon_ref.config.node_name
                            self._send_json(200, out_v)
                        elif parsed.path == "/api/singularity/kolmogorov":
                            out_k = KolmogorovGrammarCodec.run_benchmark()
                            out_k["node_name"] = daemon_ref.config.node_name
                            self._send_json(200, out_k)
                        elif parsed.path == "/api/singularity/airgap":
                            out_a = AirGapFountainBridge.run_benchmark()
                            out_a["node_name"] = daemon_ref.config.node_name
                            self._send_json(200, out_a)
                        elif parsed.path == "/api/singularity/swarm":
                            out_s = SwarmAnycastMesh.run_benchmark()
                            out_s["node_name"] = daemon_ref.config.node_name
                            self._send_json(200, out_s)
                        elif parsed.path == "/api/hyperdrive/grid-exec":
                            kernel = str(body.get("kernel") or "")
                            p_b64 = str(body.get("payload_b64") or "")
                            raw_p = base64.b64decode(p_b64.encode("ascii")) if p_b64 else b""
                            s0 = int(body.get("start_step", 0))
                            s1 = int(body.get("end_step", 6))
                            init_hex = str(body.get("init_state_hex") or "")
                            out_g = execute_whitelisted_kernel(kernel, raw_p, s0, s1, init_hex)
                            out_g["node_name"] = daemon_ref.config.node_name
                            self._send_json(200, out_g)
                        elif parsed.path == "/api/hyperdrive/handoff":
                            out_ho = daemon_ref._get_v9_handoff().accept_and_resume(
                                task_id=str(body.get("task_id") or "handoff_task"),
                                kernel=str(body.get("kernel") or "lz4_compress_hash"),
                                payload_b64=str(body.get("payload_b64") or ""),
                                state_hex=str(body.get("state_hex") or ""),
                                resume_step=int(body.get("resume_step", 0)),
                                total_steps=int(body.get("total_steps", 6)),
                            )
                            out_ho["node_name"] = daemon_ref.config.node_name
                            self._send_json(200, out_ho)
                        elif parsed.path == "/api/hyperdrive/nvme-delta":
                            raw_path = str(body.get("path") or "")
                            if not raw_path:
                                raise ValueError("path is required")
                            cand = daemon_ref._assert_path_allowed(raw_path)
                            if ".git" in cand.parts:
                                raise PermissionError("Access to .git denied")
                            raw_d = base64.b64decode(str(body.get("data_b64") or "").encode("ascii"))
                            if len(raw_d) > 262144:
                                raise ValueError("Delta write exceeds 256 KB limit")
                            off_d = max(0, int(body.get("offset", 0)))
                            nvme = daemon_ref._get_v9_nvme()
                            rel_p = cand.name
                            wb = nvme.write_back_bytes(rel_p, off_d, raw_d)
                            wb["node_name"] = daemon_ref.config.node_name
                            self._send_json(200, wb)
                        elif parsed.path == "/api/hyperdrive/cas":
                            raw_c = base64.b64decode(str(body.get("data_b64") or "").encode("ascii"))
                            if len(raw_c) > 1024 * 1024:
                                raise ValueError("CAS object exceeds 1 MiB cap")
                            res_c = daemon_ref._get_v9_cas().put(raw_c)
                            res_c["node_name"] = daemon_ref.config.node_name
                            self._send_json(200, res_c)
                        elif parsed.path == "/api/hyperdrive/hub":
                            item = daemon_ref._get_v9_hub().push_item(
                                kind=str(body.get("kind") or "clipboard"),
                                title=str(body.get("title") or "Hub"),
                                text=str(body.get("text") or ""),
                                source_node=str(body.get("source_node") or daemon_ref.config.node_name),
                            )
                            self._send_json(200, {"ok": True, **item})
                        elif parsed.path == "/api/galactic/frost-sign":
                            commits = [
                                (int(c[0]), bytes.fromhex(str(c[1])), bytes.fromhex(str(c[2])))
                                for c in body["commits"]
                            ]
                            z = FrostThreshold2of3.partial_sign(
                                int(body["share_id"]),
                                int(str(body["secret_hex"]), 16),
                                {"d": int(str(body["nonce_d_hex"]), 16), "e": int(str(body["nonce_e_hex"]), 16)},
                                commits,
                                bytes.fromhex(str(body["group_pubkey_hex"])),
                                bytes.fromhex(str(body["message_hex"])),
                            )
                            self._send_json(
                                200,
                                {
                                    "ok": True,
                                    "node_name": daemon_ref.config.node_name,
                                    "share_id": int(body["share_id"]),
                                    "z_hex": hex(z)[2:],
                                },
                            )
                        elif parsed.path == "/api/galactic/wasm-resume":
                            ckpt = body.get("checkpoint")
                            if not isinstance(ckpt, dict) or not ckpt.get("wasm_b64"):
                                raise ValueError("Missing checkpoint or wasm_b64")
                            wasm_raw = base64.b64decode(str(ckpt["wasm_b64"]))
                            if len(wasm_raw) > 65536 or int(ckpt.get("mem_pages", 1)) > 4:
                                raise ValueError("WASM checkpoint exceeds sandbox cap")
                            vm = WasmLiveTeleportEngine(max_steps=500_000, max_mem_pages=4)
                            res = vm.execute_with_checkpoint(
                                wasm_raw,
                                b"",
                                fn_name=str(ckpt.get("fn_name") or "filter"),
                                checkpoint=ckpt,
                            )
                            res["node_name"] = daemon_ref.config.node_name
                            self._send_json(200, res)
                        elif parsed.path == "/api/galactic/vsa-query":
                            trials = max(1, min(200, int(body.get("trials", 50))))
                            corrupt_pct = max(0.0, min(0.45, float(body.get("corrupt_pct", 0.40))))
                            res = HyperdimensionalVsaMesh.run_benchmark(trials=trials, corrupt_pct=corrupt_pct)
                            res["node_name"] = daemon_ref.config.node_name
                            daemon_ref.record_flow(
                                "crypto",
                                daemon_ref.config.node_name,
                                daemon_ref.config.node_name,
                                "VSA_RECONSTRUCT",
                                wire_bytes=1250,
                                elapsed_ms=float(res.get("mean_query_ms", 0.0)),
                                detail=f"recall={res.get('recall_pct')}% ({trials}x40% dmg)",
                                ok=bool(res.get("ok")),
                            )
                            self._send_json(200, res)
                    except PermissionError as pe:
                        self._send_json(403, {"error": str(pe)})
                    except FileNotFoundError as fnf:
                        self._send_json(404, {"error": str(fnf)})
                    except FileExistsError as fee:
                        self._send_json(409, {"error": str(fee)})
                    except Exception as exc:
                        self._send_json(400, {"error": str(exc)})
                    return

                if parsed.path == "/api/omega/benchmark":
                    raw_b = self._read_body()
                    try:
                        body = json.loads(raw_b.decode("utf-8") or "{}")
                    except Exception:
                        self._send_json(400, {"error": "Invalid JSON body"})
                        return
                    try:
                        peer_base = (
                            daemon_ref.active_edge_peer_base()
                            if (daemon_ref.config.role == "controller" and not bool(body.get("local_only", False)))
                            else ""
                        )
                        rep = run_omega_benchmark(peer_http_base=peer_base)
                        self._send_json(200, rep)
                    except Exception as exc:
                        self._send_json(500, {"error": str(exc)})
                    return

                if parsed.path == "/api/singularity/benchmark":
                    raw_b = self._read_body()
                    try:
                        body = json.loads(raw_b.decode("utf-8") or "{}")
                    except Exception:
                        self._send_json(400, {"error": "Invalid JSON body"})
                        return
                    try:
                        peer_base = (
                            daemon_ref.active_edge_peer_base()
                            if (daemon_ref.config.role == "controller" and not bool(body.get("local_only", False)))
                            else ""
                        )
                        rep = run_singularity_benchmark(peer_http_base=peer_base)
                        gc.collect()
                        self._send_json(200, rep)
                    except Exception as exc:
                        self._send_json(500, {"error": str(exc)})
                    return

                if parsed.path == "/api/hyperdrive/benchmark":
                    raw_b = self._read_body()
                    try:
                        body = json.loads(raw_b.decode("utf-8") or "{}")
                    except Exception:
                        self._send_json(400, {"error": "Invalid JSON body"})
                        return
                    try:
                        peer_base = (
                            daemon_ref.active_edge_peer_base()
                            if (daemon_ref.config.role == "controller" and not bool(body.get("local_only", False)))
                            else ""
                        )
                        rep = run_hyperdrive_benchmark(peer_http_base=peer_base, root_dir=str(daemon_ref.ghost_fs.root_dir))
                        daemon_ref.record_flow(
                            "phantom",
                            daemon_ref.config.node_name,
                            daemon_ref.config.peer_name or "local",
                            "BENCH_V9",
                            wire_bytes=4096,
                            elapsed_ms=float(rep.get("total_ms", 0.0)),
                            detail=f"{rep.get('ideas_verified')}/{rep.get('ideas_total')} PASS",
                            ok=bool(rep.get("ok")),
                        )
                        gc.collect()
                        self._send_json(200, rep)
                    except Exception as exc:
                        self._send_json(500, {"error": str(exc)})
                    return

                if parsed.path == "/api/galactic/benchmark":
                    raw_b = self._read_body()
                    try:
                        body = json.loads(raw_b.decode("utf-8") or "{}")
                    except Exception:
                        self._send_json(400, {"error": "Invalid JSON body"})
                        return
                    try:
                        peer_base = (
                            daemon_ref.active_edge_peer_base()
                            if (daemon_ref.config.role == "controller" and not bool(body.get("local_only", False)))
                            else ""
                        )
                        wave = str(body.get("wave") or "all")
                        rep = run_galactic_benchmark(peer_http_base=peer_base, wave=wave)
                        daemon_ref.record_flow(
                            "compute",
                            daemon_ref.config.node_name,
                            daemon_ref.config.peer_name or "local",
                            f"BENCH_V12({wave})",
                            wire_bytes=2048,
                            elapsed_ms=float(rep.get("total_ms", 0.0)),
                            detail=f"{rep.get('ideas_verified')}/{rep.get('ideas_total')} PASS",
                            ok=bool(rep.get("ok")),
                        )
                        gc.collect()
                        self._send_json(200, rep)
                    except Exception as exc:
                        self._send_json(500, {"error": str(exc)})
                    return

                if parsed.path == "/api/trinity/governor":
                    try:
                        body = json.loads(self._read_body().decode("utf-8") or "{}")
                        if body.get("policy"):
                            daemon_ref.host_governor.set_policy(str(body["policy"]))
                        if body.get("check_preempt"):
                            ov = body.get("override_metrics")
                            self._send_json(200, daemon_ref.host_governor.check_preempt(override_metrics=ov))
                        else:
                            ov = body.get("override_metrics")
                            self._send_json(200, daemon_ref.host_governor.evaluate_state(override_metrics=ov))
                    except Exception as exc:
                        self._send_json(400, {"error": str(exc)})
                    return

                if parsed.path == "/api/vsa/store":
                    try:
                        body = json.loads(self._read_body().decode("utf-8") or "{}")
                        if isinstance(body.get("items"), list):
                            res = daemon_ref.vsa_memory.store_batch(
                                body["items"], skip_unchanged=body.get("skip_unchanged") is True
                            )
                        else:
                            res = daemon_ref.vsa_memory.store(
                                str(body.get("item_id") or ""),
                                domain=str(body.get("domain") or "global"),
                                text=str(body.get("text") or ""),
                                payload=body.get("payload"),
                                reward=float(body.get("reward", 1.0) or 1.0),
                                vsa_hex=body.get("vsa_hex"),
                            )
                        self._send_json(200, res)
                    except Exception as exc:
                        self._send_json(400, {"error": str(exc)})
                    return

                if parsed.path == "/api/vsa/recall":
                    try:
                        body = json.loads(self._read_body().decode("utf-8") or "{}")
                        res = daemon_ref.vsa_memory.recall(
                            str(body.get("query_text") or ""),
                            domain=body.get("domain"),
                            top_k=int(body.get("top_k") or 5),
                            min_sim=float(body.get("min_sim") or 0.0),
                            query_vsa_hex=body.get("query_vsa_hex"),
                        )
                        daemon_ref.record_flow(
                            "crypto",
                            daemon_ref.config.node_name,
                            daemon_ref.config.node_name,
                            "VSA_RECALL",
                            wire_bytes=1250,
                            elapsed_ms=float(res.get("elapsed_ms", 0.0)),
                            detail=f"backend={res.get('backend')} n={res.get('scanned')}",
                            ok=bool(res.get("ok")),
                        )
                        self._send_json(200, res)
                    except Exception as exc:
                        self._send_json(400, {"error": str(exc)})
                    return

                if parsed.path == "/api/vsa/sync-peer":
                    try:
                        body = json.loads(self._read_body().decode("utf-8") or "{}")
                        peer_base = str(body.get("peer_base") or daemon_ref.active_edge_peer_base() or "").rstrip("/")
                        if not peer_base:
                            self._send_json(400, {"error": "no_peer_base"})
                            return
                        dom = str(body.get("domain") or "").strip()
                        lim = int(body.get("limit") or 500)
                        t0 = time.perf_counter()
                        sync = daemon_ref.vsa_memory.sync_peer(
                            peer_base, domain=dom or None, limit=lim,
                            bidirectional=bool(body.get("bidirectional", True)),
                            authorize=daemon_ref.authenticate_peer_request,
                        )
                        pulled, pushed = sync["pulled"], sync["pushed"]
                        peer_total = sync["peer_total"]
                        st_loc = daemon_ref.vsa_memory.stats()
                        elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
                        daemon_ref.record_flow(
                            "crypto",
                            daemon_ref.config.node_name,
                            daemon_ref.config.peer_name or "peer",
                            "VSA_SYNC",
                            wire_bytes=sync["body_bytes"],
                            elapsed_ms=elapsed_ms,
                            detail=f"pulled={pulled} pushed={pushed} total={st_loc.get('item_count')}",
                            ok=True,
                        )
                        self._send_json(
                            200,
                            {
                                "ok": True,
                                "peer_base": peer_base,
                                "pulled": pulled,
                                "pushed": pushed,
                                "local_total": st_loc.get("item_count", 0),
                                "peer_total": peer_total if peer_total is not None else st_loc.get("item_count", 0),
                                "elapsed_ms": elapsed_ms,
                            },
                        )
                    except Exception as exc:
                        self._send_json(502, {"error": str(exc)})
                    return

                if parsed.path == "/api/trinity/kill-switch":
                    try:
                        body = json.loads(self._read_body().decode("utf-8") or "{}")
                        from_peer = bool(body.get("from_peer", False))
                        if from_peer and isinstance(body.get("crdt"), dict):
                            daemon_ref.trinity.sync_crdt_from_peer(body["crdt"])
                        if body.get("evaluate_auto"):
                            ks = daemon_ref.trinity.evaluate_auto_kill_switch(
                                burn_rate_pct_hr=float(body.get("burn_rate_pct_hr", 0.0)),
                                recent_outputs=int(body.get("recent_outputs", 0)),
                                zero_output_hours=float(body.get("zero_output_hours", 2.0)),
                            )
                        else:
                            ks = daemon_ref.trinity.set_kill_switch(
                                bool(body.get("active", True)),
                                str(body.get("reason") or ""),
                                auto_triggered=bool(body.get("auto_triggered", False)),
                                relay_to_peer=not from_peer,
                            )
                        self._send_json(200, {"ok": True, "kill_switch": ks})
                    except Exception as exc:
                        self._send_json(400, {"error": str(exc)})
                    return

                if parsed.path == "/api/overmind/state":
                    try:
                        body = json.loads(self._read_body().decode("utf-8") or "{}")
                        self._send_json(200, daemon_ref.trinity.sync_crdt_from_peer(body))
                    except Exception as exc:
                        self._send_json(400, {"error": str(exc)})
                    return

                if parsed.path == "/api/overmind/pulse":
                    try:
                        body = json.loads(self._read_body().decode("utf-8") or "{}")
                        from_peer = bool(body.get("from_peer", False))
                        peer_u = "" if (from_peer or not body.get("relay", True)) else daemon_ref.active_edge_peer_base()
                        ev = daemon_ref.overmind.pulse.emit(
                            str(body.get("topic") or "SYSTEM"),
                            str(body.get("source") or "api"),
                            body.get("payload") if isinstance(body.get("payload"), dict) else {},
                            peer_url=peer_u,
                            from_peer=from_peer,
                        )
                        self._send_json(200, {"ok": True, "event": ev})
                    except Exception as exc:
                        self._send_json(400, {"error": str(exc)})
                    return

                if parsed.path == "/api/overmind/hippocampus/ingest-tquota":
                    try:
                        body = json.loads(self._read_body().decode("utf-8") or "{}")
                        tq_url = str(
                            body.get("tquota_admin_url")
                            or getattr(daemon_ref.config, "tquota_admin_url", "http://127.0.0.1:12504")
                        )
                        res = daemon_ref.vsa_memory.ingest_tquota_thought_briefs(
                            tq_url,
                            limit=int(body.get("limit") or 300),
                        )
                        daemon_ref.record_flow(
                            "crypto",
                            "tquota",
                            daemon_ref.config.node_name,
                            "HIPPOCAMPUS_INGEST",
                            wire_bytes=int(res.get("stored_count", 0)) * 1250,
                            elapsed_ms=float(res.get("elapsed_ms", 0.0)),
                            detail=f"fetched={res.get('fetched')} stored={res.get('stored_count')} total={res.get('total_items')}",
                            ok=bool(res.get("ok")),
                        )
                        self._send_json(200 if res.get("ok") else 502, res)
                    except Exception as exc:
                        self._send_json(400, {"error": str(exc)})
                    return

                if parsed.path == "/api/overmind/hippocampus/capsule":
                    try:
                        body = json.loads(self._read_body().decode("utf-8") or "{}")
                        doms = body.get("domains") if isinstance(body.get("domains"), list) else None
                        res = daemon_ref.vsa_memory.build_memory_capsule(
                            str(body.get("query_text") or body.get("query") or ""),
                            domains=doms,
                            top_k=int(body.get("top_k") or 4),
                            min_sim=float(body.get("min_sim", 0.502)),
                            max_chars=int(body.get("max_chars") or 900),
                        )
                        self._send_json(200, res)
                    except Exception as exc:
                        self._send_json(400, {"error": str(exc)})
                    return

                if parsed.path == "/api/overmind/flight-recorder":
                    try:
                        body = json.loads(self._read_body().decode("utf-8") or "{}")
                        res = daemon_ref.overmind.flight_recorder.freeze_cassette(
                            str(body.get("reason") or "manual_api"),
                            extra=body.get("extra") if isinstance(body.get("extra"), dict) else None,
                        )
                        self._send_json(200, res)
                    except Exception as exc:
                        self._send_json(400, {"error": str(exc)})
                    return

                if parsed.path == "/api/overmind/dlp-scan":
                    try:
                        body = json.loads(self._read_body().decode("utf-8") or "{}")
                        if "text" in body:
                            res = daemon_ref.overmind.dlp.scan_text(str(body.get("text") or ""))
                        else:
                            res = daemon_ref.overmind.dlp.scan_payload(body.get("payload", body))
                        self._send_json(200, res)
                    except Exception as exc:
                        self._send_json(400, {"error": str(exc)})
                    return

                if parsed.path == "/api/overmind/schedule":
                    try:
                        body = json.loads(self._read_body().decode("utf-8") or "{}")
                        snap = daemon_ref.trinity.snapshot(refresh=False)
                        gov = body.get("win_governor") if isinstance(body.get("win_governor"), dict) else snap.get("governor")
                        cu = body.get("colab_cu") if body.get("colab_cu") is not None else ((snap.get("tquota") or {}).get("colab_remaining_cu") or 0.0)
                        res = daemon_ref.overmind.planner.plan(
                            str(body.get("task_type") or "light_daemon"),
                            stack=body.get("stack") if isinstance(body.get("stack"), list) else None,
                            est_sec=float(body.get("est_sec", 15.0)),
                            win_governor=gov,
                            svhome_free_ram_gb=float(body.get("svhome_free_ram_gb", 5.0)),
                            colab_cu=float(cu),
                        )
                        self._send_json(200, res)
                    except Exception as exc:
                        self._send_json(400, {"error": str(exc)})
                    return

                if parsed.path == "/api/midbrain/score":
                    try:
                        body = json.loads(self._read_body().decode("utf-8") or "{}")
                        res = daemon_ref.overmind.midbrain.score(
                            str(body.get("text") or ""),
                            prev_text=str(body.get("prev_text") or ""),
                            task_id=str(body.get("task_id") or ""),
                        )
                        self._send_json(200, res)
                    except Exception as exc:
                        self._send_json(400, {"error": str(exc)})
                    return

                if parsed.path == "/api/midbrain/feedback":
                    try:
                        body = json.loads(self._read_body().decode("utf-8") or "{}")
                        res = daemon_ref.vsa_memory.record_causal_feedback(
                            list(body.get("item_ids") or []),
                            success=bool(body.get("success", False)),
                            rpe_delta=float(body.get("rpe_delta", 0.0) or 0.0),
                        )
                        self._send_json(200, res)
                    except Exception as exc:
                        self._send_json(400, {"error": str(exc)})
                    return

                if parsed.path == "/api/midbrain/distill-pivots":
                    try:
                        body = json.loads(self._read_body().decode("utf-8") or "{}")
                        res = daemon_ref.vsa_memory.distill_rpe_pivots(limit=int(body.get("limit") or 200))
                        self._send_json(200, res)
                    except Exception as exc:
                        self._send_json(400, {"error": str(exc)})
                    return

                if parsed.path == "/api/midbrain/probe":
                    try:
                        body = json.loads(self._read_body().decode("utf-8") or "{}")
                        res = daemon_ref.overmind.midbrain.install_probe(body)
                        self._send_json(200 if res.get("ok") else 400, res)
                    except Exception as exc:
                        self._send_json(400, {"error": str(exc)})
                    return

                if parsed.path == "/api/symbiote/blob/put":
                    try:
                        body = json.loads(self._read_body().decode("utf-8") or "{}")
                        raw_b = base64.b64decode(str(body.get("data_b64") or ""), validate=False)
                        res = daemon_ref.overmind.symbiote.put_blob(
                            raw_b,
                            key=body.get("key"),
                            ttl_sec=int(body.get("ttl_sec") or 900),
                            meta=body.get("meta") if isinstance(body.get("meta"), dict) else None,
                        )
                        self._send_json(200, res)
                    except Exception as exc:
                        self._send_json(400, {"ok": False, "error": str(exc)})
                    return

                if parsed.path == "/api/symbiote/immortal/register":
                    try:
                        body = json.loads(self._read_body().decode("utf-8") or "{}")
                        res = daemon_ref.overmind.symbiote.register_immortal(
                            str(body.get("turn_key") or ""),
                            vault_key=str(body.get("vault_key") or ""),
                            step_sig=str(body.get("step_sig") or ""),
                            ttl_sec=int(body.get("ttl_sec") or 900),
                            meta=body.get("meta") if isinstance(body.get("meta"), dict) else None,
                        )
                        self._send_json(200 if res.get("ok") else 400, res)
                    except Exception as exc:
                        self._send_json(400, {"ok": False, "error": str(exc)})
                    return

                if parsed.path == "/api/symbiote/immortal/complete":
                    try:
                        body = json.loads(self._read_body().decode("utf-8") or "{}")
                        raw_sse = base64.b64decode(str(body.get("sse_b64") or ""), validate=False)
                        res = daemon_ref.overmind.symbiote.complete_immortal(
                            str(body.get("turn_key") or ""),
                            raw_sse,
                            vault_key=str(body.get("vault_key") or ""),
                            step_sig=str(body.get("step_sig") or ""),
                            detached_harvest=bool(body.get("detached_harvest", True)),
                            cut=str(body.get("cut") or "completed"),
                            model=str(body.get("model") or ""),
                            effort=str(body.get("effort") or ""),
                            ttl_sec=int(body.get("ttl_sec") or 900),
                        )
                        self._send_json(200 if res.get("ok") else 400, res)
                    except Exception as exc:
                        self._send_json(400, {"ok": False, "error": str(exc)})
                    return

                if parsed.path == "/api/symbiote/immortal/lookup":
                    try:
                        body = json.loads(self._read_body().decode("utf-8") or "{}")
                        res = daemon_ref.overmind.symbiote.lookup_immortal(
                            str(body.get("turn_key") or ""),
                            step_sig=str(body.get("step_sig") or ""),
                            require_detached=bool(body.get("require_detached", False)),
                            include_bytes=bool(body.get("include_bytes", True)),
                        )
                        self._send_json(200, res)
                    except Exception as exc:
                        self._send_json(400, {"ok": False, "error": str(exc)})
                    return

                if parsed.path == "/api/symbiote/prefix/audit":
                    try:
                        body = json.loads(self._read_body().decode("utf-8") or "{}")
                        res = daemon_ref.overmind.symbiote.audit_prefix(
                            str(body.get("session_id") or "default"),
                            list(body.get("item_digests") or []),
                            account_id=str(body.get("account_id") or ""),
                            tool_outputs=body.get("tool_outputs") if isinstance(body.get("tool_outputs"), list) else None,
                        )
                        self._send_json(200, res)
                    except Exception as exc:
                        self._send_json(400, {"ok": False, "error": str(exc)})
                    return

                if parsed.path == "/api/symbiote/observe-usage":
                    try:
                        body = json.loads(self._read_body().decode("utf-8") or "{}")
                        res = daemon_ref.overmind.symbiote.observe_usage(body)
                        self._send_json(200, res)
                    except Exception as exc:
                        self._send_json(400, {"ok": False, "error": str(exc)})
                    return

                if parsed.path == "/api/symbiote/precog-verify":
                    try:
                        body = json.loads(self._read_body().decode("utf-8") or "{}")
                        res = daemon_ref.overmind.symbiote.precog_verify(
                            str(body.get("repo_dir") or ""),
                            changed_files=list(body.get("changed_files") or []),
                            run_fast_tests=bool(body.get("run_fast_tests", False)),
                            timeout_sec=int(body.get("timeout_sec") or 15),
                        )
                        self._send_json(200, res)
                    except Exception as exc:
                        self._send_json(400, {"ok": False, "error": str(exc)})
                    return

                if parsed.path == "/api/symbiote/surgeon/heal":
                    try:
                        body = json.loads(self._read_body().decode("utf-8") or "{}")
                        res = daemon_ref.overmind.symbiote.heal_codex_rollout_jsonl(
                            str(body.get("session_id") or ""),
                            sessions_dir=body.get("sessions_dir") or None,
                            min_idle_sec=float(body.get("min_idle_sec", 2.0)),
                            dry_run=bool(body.get("dry_run", False)),
                        )
                        status_code = 200 if (res.get("ok") or res.get("skipped")) else (404 if res.get("reason") == "rollout_not_found" else 400)
                        self._send_json(status_code, res)
                    except Exception as exc:
                        self._send_json(400, {"ok": False, "error": str(exc)})
                    return

                if parsed.path == "/api/symbiote/surgeon/fork":
                    try:
                        body = json.loads(self._read_body().decode("utf-8") or "{}")
                        before_line = body.get("before_line")
                        res = daemon_ref.overmind.symbiote.fork_rollout_to_last_clean_checkpoint(
                            str(body.get("session_id") or ""),
                            sessions_dir=body.get("sessions_dir") or None,
                            before_line=int(before_line) if before_line is not None else None,
                            before_call_id=str(body.get("before_call_id") or ""),
                        )
                        status_code = 200 if res.get("ok") else (404 if res.get("reason") == "rollout_not_found" else 400)
                        self._send_json(status_code, res)
                    except Exception as exc:
                        self._send_json(400, {"ok": False, "error": str(exc)})
                    return

                if parsed.path == "/api/galactic/live-teleport":
                    raw_b = self._read_body()
                    try:
                        body = json.loads(raw_b.decode("utf-8") or "{}")
                    except Exception:
                        self._send_json(400, {"error": "Invalid JSON body"})
                        return
                    try:
                        peer_base = (
                            daemon_ref.active_edge_peer_base()
                            if (daemon_ref.config.role == "controller" and not bool(body.get("local_only", False)))
                            else ""
                        )
                        res = WasmLiveTeleportEngine.run_benchmark(peer_http_base=peer_base)
                        daemon_ref.record_flow(
                            "compute",
                            daemon_ref.config.node_name,
                            (daemon_ref.config.peer_name or "peer") if res.get("resumed_on_peer") else daemon_ref.config.node_name,
                            "WASM_TELEPORT",
                            wire_bytes=int(res.get("checkpoint_wire_bytes", 0)),
                            elapsed_ms=float(res.get("teleport_ms", 0.0)),
                            detail=f"step {res.get('paused_at_step')}/{res.get('total_steps')} peer={res.get('resumed_on_peer')} res={res.get('got_result')}",
                            ok=bool(res.get("ok")),
                        )
                        self._send_json(200, res)
                    except Exception as exc:
                        self._send_json(500, {"error": str(exc)})
                    return

                if parsed.path == "/api/galactic/live-frost":
                    raw_b = self._read_body()
                    try:
                        body = json.loads(raw_b.decode("utf-8") or "{}")
                    except Exception:
                        self._send_json(400, {"error": "Invalid JSON body"})
                        return
                    try:
                        peer_base = (
                            daemon_ref.active_edge_peer_base()
                            if (daemon_ref.config.role == "controller" and not bool(body.get("local_only", False)))
                            else ""
                        )
                        res = FrostThreshold2of3.run_benchmark(peer_http_base=peer_base)
                        daemon_ref.record_flow(
                            "crypto",
                            daemon_ref.config.node_name,
                            (daemon_ref.config.peer_name or "peer") if res.get("peer_signed_live") else daemon_ref.config.node_name,
                            "FROST_2OF3",
                            wire_bytes=192,
                            elapsed_ms=float(res.get("elapsed_ms", 0.0)),
                            detail=f"3 pairs OK peer={res.get('peer_signed_live')} tamper_blocked={res.get('tamper_rejected')}",
                            ok=bool(res.get("ok")),
                        )
                        self._send_json(200, res)
                    except Exception as exc:
                        self._send_json(500, {"error": str(exc)})
                    return

                if parsed.path == "/api/galactic/live-chmc":
                    try:
                        res = ActiveMatterCell.run_benchmark()
                        daemon_ref.record_flow(
                            "crypto",
                            daemon_ref.config.node_name,
                            daemon_ref.config.node_name,
                            "CHMC_3STRIKE",
                            wire_bytes=int(res.get("stored_cipher_bytes", 0)),
                            elapsed_ms=float(res.get("elapsed_ms", 0.0)),
                            detail=f"blind={res.get('blind_search_encrypted_ok')} heal={res.get('bit_rot_self_healed_and_unlocked')} shred={res.get('self_shred_after_3_strikes')}",
                            ok=bool(res.get("ok")),
                        )
                        self._send_json(200, res)
                    except Exception as exc:
                        self._send_json(500, {"error": str(exc)})
                    return

                self._send_json(404, {"error": "Not found"})

            def do_DELETE(self) -> None:
                if not self._allow_management_request():
                    return
                parsed = urllib.parse.urlparse(self.path)
                if parsed.path == "/mcp":
                    code, obj, hdrs = daemon_ref.omega_spine.mcp.handle_delete(self.headers)
                    self._send_json(code, obj, extra_headers=hdrs)
                    return
                self._send_json(404, {"error": "Not found"})

            def log_message(self, *_args: object) -> None:
                pass

        self._httpd = _ThreadingControlServer((host_b, int(port_b)), Handler)
        self.http_addr = self._httpd.server_address[:2]
        self.platform.start()

        if int(self.config.warp_port) >= 0:
            self._warp_srv = WarpServer(
                udp_bind=("0.0.0.0", int(self.config.warp_port)),
                forward_tcp_addr=("127.0.0.1", self.http_addr[1]),
                est_loss=0.02,
            ).start()
            self.config.warp_port = self._warp_srv.udp_addr[1]

        fb_port = 0 if self._ephemeral_mode else int(self.config.phantom_fallback_port)
        egress_port = int(self.platform.egress.addr[1] or 9781) if self.platform is not None else 9781
        rev_fwds: dict[int, int] = {}
        if (not self._ephemeral_mode) and self.config.role == "server":
            rtq = int(getattr(self.config, "phantom_reverse_tquota_port", 12551))
            rhp = int(getattr(self.config, "phantom_reverse_http_port", 9790))
            reg = int(getattr(self.config, "phantom_reverse_egress_port", 9792))
            if rtq > 0:
                rev_fwds[rtq] = 12500
            if rhp > 0:
                rev_fwds[rhp] = int(self.http_addr[1])
            if reg > 0:
                rev_fwds[reg] = egress_port
        self._phantom_srv = PhantomTunnelServer(
            fallback_port=fb_port,
            allowed_forward_ports=list(self.config.phantom_allowed_ports) + [int(self.http_addr[1]), egress_port],
            reverse_forwards=rev_fwds,
        ).start()

        if bool(self.config.phantom_enabled) and self.config.role == "controller" and self.config.peer_ipv4:
            ph_forwards: dict[int, int] = {
                int(self.config.phantom_ssh_port): 22,
                int(self.config.phantom_http_port): int(self.config.peer_dashboard_port),
            }
            tq_port = int(getattr(self.config, "phantom_tquota_port", 0))
            if tq_port > 0:
                ph_forwards[tq_port] = 12500
            eg_port = int(getattr(self.config, "phantom_egress_port", 9791))
            if eg_port > 0:
                ph_forwards[eg_port] = 9781
            self._phantom_client = PhantomTunnelClient(
                peer_http_base=self.peer_http_base(),
                peer_udp_ip=self.config.peer_ipv4,
                peer_fallback_port=int(self.config.phantom_fallback_port),
                forwards=ph_forwards,
                local_test_mode=False,
                allowed_reverse_ports=list(
                    getattr(self.config, "phantom_reverse_allowed_ports", [9780, 9781, 12500, 12504])
                ) + [int(self.http_addr[1]), egress_port],
            ).start_listeners()
            if not self._ephemeral_mode:
                def _auto_phantom() -> None:
                    if self._stop.wait(timeout=1.0) or self._phantom_client is None:
                        return
                    try:
                        res = self._phantom_client.connect()
                        self.store.log_event(
                            "INFO", "PHANTOM", f"Auto-connect mode={res['mode']} RTT={res['direct_rtt_ms']}ms"
                        )
                        self.invalidate_status_cache()
                    except Exception as exc:
                        self.store.log_event("WARN", "PHANTOM", f"Auto-connect failed: {exc}")

                th_ph = threading.Thread(target=_auto_phantom, daemon=True)
                th_ph.start()
                self._threads.append(th_ph)

        if int(self.config.edge_proxy_port) >= 0:
            proxy_peer = self.peer_http_base()
            self._local_edge_proxy = LocalEdgeProxy(
                listen_host="127.0.0.1",
                listen_port=int(self.config.edge_proxy_port),
                peer_http_base=proxy_peer,
                targets=self.config.edge_targets,
                telepathy_store=self.telepathy_store,
                peer_http_resolver=self.active_edge_peer_base,
            ).start()
            self.config.edge_proxy_port = self._local_edge_proxy.addr[1]

        t_http = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        t_sched = threading.Thread(target=self._scheduler_loop, daemon=True)
        t_http.start()
        t_sched.start()
        self._threads.extend([t_http, t_sched])
        self.trinity.refresh_async(ttl_s=0.0)
        gc.collect()
        zw = get_zero_weight_status()
        self.store.log_event(
            "INFO",
            "DAEMON",
            f"v9.0 Started on http://{self.http_addr[0]}:{self.http_addr[1]} | RAM={zw['daemon_ram_mb']}MB | Beam={self.config.beam_port} EdgeProxy={self.config.edge_proxy_port} PhantomFB={self._phantom_srv.fallback_port}",
        )
        return self

    def phantom_status(self) -> dict[str, Any]:
        return {
            "client": self._phantom_client.status() if self._phantom_client is not None else None,
            "server": self._phantom_srv.stats() if self._phantom_srv is not None else None,
        }

    def edge_stats(self) -> dict[str, Any]:
        return {
            "gateway": self.edge_gateway.stats(),
            "local_proxy": self._local_edge_proxy.stats() if self._local_edge_proxy is not None else None,
        }

    def invalidate_status_cache(self) -> None:
        with self._status_cache_lock:
            self._status_cache_ts = 0.0
            self._status_cache_data = None

    def get_cached_status(self, ttl_s: float = 15.0) -> tuple[dict[str, Any], bytes, str]:
        now = time.monotonic()
        with self._status_cache_lock:
            if self._status_cache_data is not None and (now - self._status_cache_ts) < ttl_s:
                return self._status_cache_data
        payload = self.status_payload()
        raw_json = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        etag = f'"{hashlib.blake2s(raw_json, digest_size=8).hexdigest()}"'
        entry = (payload, raw_json, etag)
        with self._status_cache_lock:
            self._status_cache_data = entry
            self._status_cache_ts = time.monotonic()
        return entry

    def status_payload(self) -> dict[str, Any]:
        return {
            "version": __version__,
            "api_version": "12.0.0",
            "config": self.config.to_dict(),
            "hardware": cpu_caps(),
            "zero_weight": get_zero_weight_status(),
            "telepathy_dicts": self.telepathy_store.list_dicts(),
            "today_daily_done": self.store.has_daily_run_today(),
            "telemetry": self.store.get_dashboard_state(limit=30),
            "cluster": self.store.get_cluster_overview(limit=30),
            "sentinel": self.sentinel.latest_status(),
            "code_search": self.code_search.stats(),
            "edge": self.edge_stats(),
            "holo_backups": list_holo_backups(self.backup_root)[:8],
            "nat_last": self._last_nat_result,
            "phantom": self.phantom_status(),
            "portal": {"count": len(self.drop_portal.list_items())},
        }

    def run_cycle(self, trigger: str = "manual") -> dict[str, Any]:
        with self._run_lock:
            res = run_daily_autopilot(
                self.config, self.store, trigger=trigger, ops_dir=self.ops_dir
            )
            self.invalidate_status_cache()
            return res

    def _handle_sentinel_spike(self, alert: dict[str, str]) -> None:
        try:
            sig = f"{alert.get('source', '')}|{alert.get('detail', '')}"
            iid = f"sent_{hashlib.sha256(sig.encode('utf-8', errors='ignore')).hexdigest()[:12]}"
            txt = f"{alert.get('source', '')} {alert.get('detail', '')} -> {alert.get('diagnosis', '')}"
            self.vsa_memory.store(
                iid,
                domain="sentinel_reflex",
                text=txt,
                payload={"resolution_hint": str(alert.get("diagnosis") or ""), "severity": alert.get("severity", "WARN")},
                reward=1.8,
            )
            if str(alert.get("severity") or "").upper() == "CRITICAL":
                self.overmind.flight_recorder.freeze_cassette(
                    f"sentinel_{alert.get('source', 'crit')}",
                    extra={"alert": alert},
                )
        except Exception:
            pass

    def _scheduler_loop(self) -> None:
        if self.auto_seed_on_empty:
            st = self.store.get_dashboard_state(limit=1)
            if st["total_runs"] == 0 and not self._stop.wait(timeout=1.5):
                try:
                    self.run_cycle(trigger="startup_seed")
                except Exception:
                    pass

        is_persistent = not self._ephemeral_mode
        last_sentinel = 0.0
        last_hippocampus = 0.0
        if is_persistent and (self.config.role == "server" or self.config.search_roots):
            try:
                if self.config.search_roots:
                    self.code_search.incremental_index([Path(p) for p in self.config.search_roots])
                if self.config.role == "server":
                    self.sentinel.scan(self.config, on_spike_callback=self._handle_sentinel_spike)
                    last_sentinel = time.monotonic()
                self.invalidate_status_cache()
            except Exception as exc:
                self.store.log_event("ERROR", "HYPEROS_INIT", str(exc))

        sent_iv = max(60, int(getattr(self.config, "sentinel_interval_s", 300)))
        while not self._stop.wait(timeout=15.0):
            try:
                now_m = time.monotonic()
                now_hm = datetime.now().astimezone().strftime("%H:%M")
                if now_hm >= self.config.daily_time and not self.store.has_daily_run_today():
                    self.run_cycle(trigger="daemon_daily")
                if is_persistent:
                    zw = get_zero_weight_status()
                    ph = self.phantom_status()
                    cli_st = ph.get("client") if isinstance(ph.get("client"), dict) else {}
                    tr_snap = self.trinity.snapshot(refresh=False)
                    self.overmind.flight_recorder.record_sample(
                        {
                            "daemon_ram_mb": zw.get("daemon_ram_mb"),
                            "host_free_ram_gb": zw.get("host_free_ram_gb"),
                            "phantom_mode": cli_st.get("mode", "SERVER" if not cli_st else "DISCONNECTED"),
                            "phantom_rtt_ms": cli_st.get("direct_rtt_ms", 0.0),
                            "tx_bytes": cli_st.get("tx_bytes", 0),
                            "phantom_conns": cli_st.get("active_conns", 0),
                            "tquota_gossip_errors": (tr_snap.get("tquota") or {}).get("gossip_errors", 0),
                            "tquota_burn_pct_hr": (tr_snap.get("kill_switch") or {}).get("quota_burn_rate_pct_hr", 0.0),
                        }
                    )
                    if last_hippocampus == 0.0 or (now_m - last_hippocampus) >= 600.0:
                        last_hippocampus = now_m
                        tq_url = str(getattr(self.config, "tquota_admin_url", "http://127.0.0.1:12504"))
                        self.vsa_memory.ingest_tquota_thought_briefs(tq_url, limit=300)
                        peer_base = self.active_edge_peer_base()
                        if peer_base:
                            _http_post_json(f"{peer_base}/api/overmind/state", self.overmind.crdt.snapshot(), timeout_s=1.5)
                            try:
                                with urllib.request.urlopen(
                                    urllib.request.Request(
                                        f"http://127.0.0.1:{self.http_addr[1]}/api/vsa/sync-peer",
                                        data=json.dumps({"peer_base": peer_base, "bidirectional": True}).encode("utf-8"),
                                        headers={"Content-Type": "application/json"},
                                        method="POST",
                                    ),
                                    timeout=4.0,
                                ) as _sr:
                                    _sr.read(64)
                            except Exception:
                                pass
                        gc.collect()
                        if os.name == "posix":
                            # After this ten-minute batch, let glibc return free
                            # allocator pages to the OS. Other allocators can skip it.
                            import ctypes
                            try:
                                trim = ctypes.CDLL(None).malloc_trim
                            except (AttributeError, OSError):
                                pass
                            else:
                                trim.argtypes = [ctypes.c_size_t]
                                trim.restype = ctypes.c_int
                                trim(0)
                if is_persistent and self.config.role == "server":
                    if (now_m - last_sentinel) >= sent_iv:
                        self.sentinel.scan(self.config, on_spike_callback=self._handle_sentinel_spike)
                        last_sentinel = now_m
                        self.invalidate_status_cache()
            except Exception as exc:
                self.store.log_event("ERROR", "SCHEDULER", str(exc))

    def close(self) -> None:
        self._stop.set()
        if self._omega_spine is not None:
            self._omega_spine.close()
        self.platform.close()
        if self._phantom_client is not None:
            self._phantom_client.close()
        if self._phantom_srv is not None:
            self._phantom_srv.close()
        if self._local_edge_proxy is not None:
            self._local_edge_proxy.close()
        self.ghost_pty.close_all()
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
        for srv in (
            self._warp_srv,
            self._immortal_rx,
            self._query_srv,
            self._rpc_srv,
            self._beam_srv,
        ):
            if srv is not None:
                srv.close()
        self.sentinel.close()
        self.code_search.close()
        self.vsa_memory.close()
        self.store.close()
