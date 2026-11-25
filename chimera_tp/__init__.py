"""CHIMERA-HYPER v2.0: Silicon-Native Zero-Byte & GFNI Accelerated Transport + Mission Control."""

__version__ = "2.0.0"

from .active_pipe import ActivePipeEngine, ActivePipeResult, ActiveQueryServer, ComputePlan, remote_active_query
from .autopilot import OpsConfig, TelemetryStore, run_daily_autopilot
from .dashboard import ChimeraDaemon
from .dna_vault import DnaCodec, DnaStats, DnaVault, pack_directory, unpack_directory
from .fabric import BeamReport, BeamServer, ChimeraFabric, beam_send
from .hyper_wire import (
    HedgedRpcClient,
    HedgedRpcServer,
    HyperWireReceiver,
    HyperWireReport,
    HyperWireSender,
)
from .native import WormholeChannel, cpu_caps, has_native
from .probe import EnvironmentProfile, RealmInfo, probe_environment
from .protocol import ChimeraReceiver, ChimeraSender, FaultProfile, TransferReport
from .warp import WarpClient, WarpServer

__all__ = [
    "ActivePipeEngine",
    "ActivePipeResult",
    "BeamReport",
    "BeamServer",
    "ChimeraFabric",
    "ChimeraReceiver",
    "ChimeraSender",
    "ComputePlan",
    "DnaCodec",
    "DnaStats",
    "DnaVault",
    "EnvironmentProfile",
    "FaultProfile",
    "HedgedRpcClient",
    "HedgedRpcServer",
    "HyperWireReceiver",
    "HyperWireReport",
    "HyperWireSender",
    "RealmInfo",
    "TransferReport",
    "WarpClient",
    "WarpServer",
    "WormholeChannel",
    "beam_send",
    "cpu_caps",
    "has_native",
    "pack_directory",
    "probe_environment",
    "unpack_directory",
]
