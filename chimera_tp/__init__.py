"""CHIMERA-HYPER v4.0: Zero-Weight HyperOS (NAT Buster, Warp Edge Proxy, Sentinel Watchdog, FTS5 Search, Holo GF256 Backup + HyperGrid v3)."""

__version__ = "4.0.0"

from .active_pipe import ActivePipeEngine, ActivePipeResult, ActiveQueryServer, ComputePlan, remote_active_query
from .autopilot import OpsConfig, TelemetryStore, get_zero_weight_status, run_daily_autopilot
from .code_search import CodeSearchIndex
from .dashboard import ChimeraDaemon
from .dna_vault import DnaCodec, DnaStats, DnaVault, pack_directory, unpack_directory
from .edge_proxy import EdgeGateway, LocalEdgeProxy, edge_fetch_remote
from .fabric import BeamReport, BeamServer, ChimeraFabric, beam_send, beam_send_merkle_patch
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
from .merkle_sync import MerkleSnapshot, ShadowMerkleIndex, merkle_beam_sync
from .nat_buster import NatPunchResponder, attempt_direct_punch, discover_nat_profile
from .native import WormholeChannel, cpu_caps, has_native
from .probe import EnvironmentProfile, RealmInfo, probe_environment
from .protocol import ChimeraReceiver, ChimeraSender, FaultProfile, TransferReport
from .sentinel import SentinelEngine
from .telepathy import DomainDictionary, TelepathicCodec, TelepathicStore, train_domain_dictionary
from .warp import WarpClient, WarpServer

__all__ = [
    "ActivePipeEngine",
    "ActivePipeResult",
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
    "EdgeGateway",
    "EnvironmentProfile",
    "FaultProfile",
    "HedgedRpcClient",
    "HedgedRpcServer",
    "HyperWireReceiver",
    "HyperWireReport",
    "HyperWireSender",
    "ImmortalMultiPathReceiver",
    "ImmortalMultiPathSender",
    "ImmortalReport",
    "LocalEdgeProxy",
    "MerkleSnapshot",
    "NatPunchResponder",
    "OpsConfig",
    "RealmInfo",
    "SentinelEngine",
    "ShadowMerkleIndex",
    "TelemetryStore",
    "TelepathicCodec",
    "TelepathicStore",
    "TransferReport",
    "WarpClient",
    "WarpServer",
    "WormholeChannel",
    "attempt_direct_punch",
    "beam_send",
    "beam_send_merkle_patch",
    "cpu_caps",
    "create_holo_backup",
    "discover_nat_profile",
    "edge_fetch_remote",
    "get_zero_weight_status",
    "has_native",
    "list_holo_backups",
    "merkle_beam_sync",
    "pack_directory",
    "probe_environment",
    "reconstruct_secret_gf256_2of3",
    "restore_holo_backup",
    "split_secret_gf256_2of3",
    "train_domain_dictionary",
    "unpack_directory",
]
