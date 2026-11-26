"""CHIMERA-TP v16.0 Platform Substrate: CHIMERA-CONNECT, Egress-Membrane, Pulse, Hybrid Search, BlackBox & MCP."""

from .autoload import autoload_status, install_autoload, uninstall_autoload
from .browser_grid import SharedBrowserGrid, find_browser_binary
from .client import ChimeraClient, connect, is_available
from .discovery import (
    AppRegistry,
    PassivePortScanner,
    chimera_home_dir,
    discover_runtime_file,
    init_project,
    link_project,
    runtime_beacon_paths,
    write_agents_infra_doc,
)
from .egress_membrane import EgressMembraneProxy
from .flight_recorder import DisklessSecretVault, FlightRecorderBlackBox
from .hybrid_search import HybridPlatformSearch
from .immortal_jobs import ImmortalJobEngine
from .mcp_server import handle_mcp_request, serve_mcp_stdio
from .pulse_bus import PulseBus
from .substrate import PlatformSubstrate, render_smi
from .vgpu_gateway import VgpuParetoGateway, probe_nvidia_gpu
from .zygote_canary import CanaryTwinJudge, ZygoteWorkerPool

__all__ = [
    "AppRegistry",
    "CanaryTwinJudge",
    "ChimeraClient",
    "DisklessSecretVault",
    "EgressMembraneProxy",
    "FlightRecorderBlackBox",
    "HybridPlatformSearch",
    "ImmortalJobEngine",
    "PassivePortScanner",
    "PlatformSubstrate",
    "PulseBus",
    "SharedBrowserGrid",
    "VgpuParetoGateway",
    "ZygoteWorkerPool",
    "autoload_status",
    "chimera_home_dir",
    "connect",
    "discover_runtime_file",
    "find_browser_binary",
    "handle_mcp_request",
    "init_project",
    "install_autoload",
    "is_available",
    "link_project",
    "probe_nvidia_gpu",
    "render_smi",
    "runtime_beacon_paths",
    "serve_mcp_stdio",
    "uninstall_autoload",
    "write_agents_infra_doc",
]
