"""CHIMERA-HYPER v3.0: Zero-Weight HyperGrid (Merkle Sync, Fluid Pushdown, Telepathic Dict, Immortal Multi-Path)."""

__version__ = "3.0.0"

from .active_pipe import ActivePipeEngine, ActivePipeResult, ActiveQueryServer, ComputePlan, remote_active_query
from .autopilot import OpsConfig, TelemetryStore, get_zero_weight_status, run_daily_autopilot
from .dashboard import ChimeraDaemon
from .dna_vault import DnaCodec, DnaStats, DnaVault, pack_directory, unpack_directory
from .fabric import BeamReport, BeamServer, ChimeraFabric, beam_send, beam_send_merkle_patch
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
from .native import WormholeChannel, cpu_caps, has_native
from .probe import EnvironmentProfile, RealmInfo, probe_environment
from .protocol import ChimeraReceiver, ChimeraSender, FaultProfile, TransferReport
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
    "ComputePlan",
    "DnaCodec",
    "DnaStats",
    "DnaVault",
    "DomainDictionary",
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
    "MerkleSnapshot",
    "OpsConfig",
    "RealmInfo",
    "ShadowMerkleIndex",
    "TelemetryStore",
    "TelepathicCodec",
    "TelepathicStore",
    "TransferReport",
    "WarpClient",
    "WarpServer",
    "WormholeChannel",
    "beam_send",
    "beam_send_merkle_patch",
    "cpu_caps",
    "get_zero_weight_status",
    "has_native",
    "merkle_beam_sync",
    "pack_directory",
    "probe_environment",
    "train_domain_dictionary",
    "unpack_directory",
]
