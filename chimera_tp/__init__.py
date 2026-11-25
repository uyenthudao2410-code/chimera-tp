"""CHIMERA-HYPER v6.0: APEX-SYNERGY (PHANTOM-5MS, Radar + Tqouta Fusion, Ghost-PTY, Ghost-FS WebDAV, Medic & Drop-Portal)."""

__version__ = "7.0.0"

from .active_pipe import ActivePipeEngine, ActivePipeResult, ActiveQueryServer, ComputePlan, remote_active_query
from .apex_synergy import ApexSynergyEngine
from .autopilot import OpsConfig, TelemetryStore, get_zero_weight_status, run_daily_autopilot
from .code_search import CodeSearchIndex
from .dashboard import ChimeraDaemon
from .dna_vault import DnaCodec, DnaStats, DnaVault, pack_directory, unpack_directory
from .drop_portal import DropPortalStore, pack_ai_context
from .edge_proxy import EdgeGateway, LocalEdgeProxy, edge_fetch_remote
from .fabric import BeamReport, BeamServer, ChimeraFabric, beam_send, beam_send_merkle_patch
from .ghost_fs import GhostFsEngine, build_propfind_xml
from .ghost_pty import GhostPtyManager
from .holo_backup import (
    create_holo_backup,
    list_holo_backups,
    restore_holo_backup,
    reconstruct_secret_gf256_2of3,
    split_secret_gf256_2of3,
)
from .hyper_wire import (
    HedgedRpcClient,
    HedgedRpcServer,
    HyperWireReceiver,
    HyperWireReport,
    HyperWireSender,
    ImmortalMultiPathReceiver,
    ImmortalMultiPathSender,
    ImmortalReport,
)
from .medic import MedicEngine
from .merkle_sync import MerkleSnapshot, ShadowMerkleIndex, merkle_beam_sync
from .nat_buster import NatPunchResponder, attempt_direct_punch, discover_nat_profile
from .native import WormholeChannel, cpu_caps, has_native
from .phantom_tunnel import PhantomTunnelClient, PhantomTunnelServer, open_packet, seal_packet
from .probe import EnvironmentProfile, RealmInfo, probe_environment
from .protocol import ChimeraReceiver, ChimeraSender, FaultProfile, TransferReport
from .sentinel import SentinelEngine
from .telepathy import DomainDictionary, TelepathicCodec, TelepathicStore, train_domain_dictionary
from .warp import WarpClient, WarpServer
from .omega_bench import format_omega_markdown, run_omega_benchmark
from .omega_compute import (
    NeuralPpmCodec,
    RemoteRamPool,
    RemoteRamStore,
    UepDisplayStream,
    WasmActivePipe,
    build_wasm_byte_counter_module,
)
from .omega_storage import (
    GhostBlockEngine,
    ParasiticDeadDropMesh,
    RegeneratingMeshVault,
    SlepianWolfSync,
    detect_fs_mount_caps,
)
from .omega_transport import (
    GeneticWireEngine,
    MultiIspBondingEngine,
    PolymorphicMimicLayer,
    QuantumChaffShield,
    RlncRecodingRelay,
    SiliconDataPlane,
    VirtualNicBridge,
    detect_os_tun_caps,
    hybrid_pq_decaps,
    hybrid_pq_encaps,
    hybrid_pq_keypair,
    x25519_keypair,
    x25519_shared,
)

__all__ = [
    "ActivePipeEngine",
    "ActivePipeResult",
    "ApexSynergyEngine",
    "BeamReport",
    "BeamServer",
    "ChimeraDaemon",
    "ChimeraFabric",
    "ChimeraReceiver",
    "ChimeraSender",
    "CodeSearchIndex",
    "ComputePlan",
    "DnaCodec",
    "DnaStats",
    "DnaVault",
    "DomainDictionary",
    "DropPortalStore",
    "EdgeGateway",
    "EnvironmentProfile",
    "FaultProfile",
    "GeneticWireEngine",
    "GhostBlockEngine",
    "GhostFsEngine",
    "GhostPtyManager",
    "HedgedRpcClient",
    "HedgedRpcServer",
    "HyperWireReceiver",
    "HyperWireReport",
    "HyperWireSender",
    "ImmortalMultiPathReceiver",
    "ImmortalMultiPathSender",
    "ImmortalReport",
    "LocalEdgeProxy",
    "MedicEngine",
    "MerkleSnapshot",
    "MultiIspBondingEngine",
    "NatPunchResponder",
    "NeuralPpmCodec",
    "OpsConfig",
    "ParasiticDeadDropMesh",
    "PhantomTunnelClient",
    "PhantomTunnelServer",
    "PolymorphicMimicLayer",
    "QuantumChaffShield",
    "RealmInfo",
    "RegeneratingMeshVault",
    "RemoteRamPool",
    "RemoteRamStore",
    "RlncRecodingRelay",
    "SentinelEngine",
    "ShadowMerkleIndex",
    "SiliconDataPlane",
    "SlepianWolfSync",
    "TelemetryStore",
    "TelepathicCodec",
    "TelepathicStore",
    "TransferReport",
    "UepDisplayStream",
    "VirtualNicBridge",
    "WarpClient",
    "WarpServer",
    "WasmActivePipe",
    "WormholeChannel",
    "attempt_direct_punch",
    "beam_send",
    "beam_send_merkle_patch",
    "build_propfind_xml",
    "build_wasm_byte_counter_module",
    "cpu_caps",
    "create_holo_backup",
    "detect_fs_mount_caps",
    "detect_os_tun_caps",
    "discover_nat_profile",
    "edge_fetch_remote",
    "format_omega_markdown",
    "get_zero_weight_status",
    "has_native",
    "hybrid_pq_decaps",
    "hybrid_pq_encaps",
    "hybrid_pq_keypair",
    "list_holo_backups",
    "merkle_beam_sync",
    "open_packet",
    "pack_ai_context",
    "pack_directory",
    "probe_environment",
    "reconstruct_secret_gf256_2of3",
    "restore_holo_backup",
    "run_omega_benchmark",
    "seal_packet",
    "split_secret_gf256_2of3",
    "train_domain_dictionary",
    "unpack_directory",
    "x25519_keypair",
    "x25519_shared",
]
