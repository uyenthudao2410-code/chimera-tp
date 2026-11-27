"""CHIMERA-TP v16.0 Platform Substrate: CHIMERA-CONNECT, Egress-Membrane, Pulse, Hybrid Search, BlackBox & MCP."""

# Map the existing public names to their owning modules without importing the engines.
_MODULE_EXPORTS = {
    "agent_probe": (
        "AgentHyperBus",
        "AtomicCommitVerifyEngine",
        "CallgraphTelepathyEngine",
        "OmniProbeBatchEngine",
        "TokenDietCompactor",
        "get_default_agent_bus",
    ),
    "agent_symbiont": (
        "AgentSymbiontCore",
        "HiveMindCortex",
        "PrecogRunnerEngine",
        "SurgeonAtomicPatchEngine",
        "TelepathyCapsuleEngine",
    ),
    "autoload": (
        "autoload_status",
        "install_autoload",
        "install_systemd_dropin",
        "uninstall_autoload",
    ),
    "browser_grid": ("SharedBrowserGrid", "find_browser_binary"),
    "client": ("ChimeraClient", "connect", "is_available"),
    "colab_cli_bridge": (
        "ColabCliBridge",
        "parse_marked_json",
        "parse_usage_text",
        "select_lightest_profile",
    ),
    "cosmos_entity": (
        "CosmosEntityEngine",
        "ImmuneSecurityKernel",
        "OmniMemoryFabric",
        "ThermodynamicPhysicsEngine",
        "ZeroEnvCasStore",
    ),
    "discovery": (
        "AppRegistry",
        "PassivePortScanner",
        "chimera_home_dir",
        "discover_runtime_file",
        "init_project",
        "link_project",
        "runtime_beacon_paths",
        "write_agents_infra_doc",
    ),
    "egress_membrane": ("EgressMembraneProxy",),
    "evidence": ("EvidenceLedger",),
    "exile_handoff": ("CheckpointedExileCoordinator", "InMemoryWorkerTransport"),
    "flight_recorder": ("DisklessSecretVault", "FlightRecorderBlackBox"),
    "folded_cavity_rlnc": ("CristaeFoldedCavityRLNC",),
    "ghost_bubble": ("GhostBubbleEngine",),
    "hybrid_search": ("HybridPlatformSearch",),
    "hyper_desk": ("HyperDeskEngine", "VramCompressedSwap"),
    "phantom_silicon": (
        "AgentExileEngine",
        "GpuFenceManager",
        "NvmeMirageEngine",
        "SiliconThermostat",
        "StasisPodManager",
    ),
    "immortal_jobs": ("ImmortalJobEngine",),
    "mcp_server": ("handle_mcp_request", "serve_mcp_stdio"),
    "nvcuda_ptx": ("NvCudaPtxEngine",),
    "omega_entity": ("OmegaEntityEngine",),
    "pulse_bus": ("PulseBus",),
    "substrate": ("PlatformSubstrate", "render_smi"),
    "unify": ("unify_install", "unify_status", "unify_uninstall"),
    "vault_sql": ("VaultSqlFabric",),
    "vgpu_gateway": ("VgpuParetoGateway", "probe_gpu_backends", "probe_nvidia_gpu"),
    "zygote_canary": ("CanaryTwinJudge", "ZygoteWorkerPool"),
}
_EXPORTS = {name: module for module, names in _MODULE_EXPORTS.items() for name in names}

# These modules were also available through package attribute access.
_SUBMODULES = set(_MODULE_EXPORTS) | {
    "workspace_undo",
}


def __getattr__(name):
    from importlib import import_module

    if name in _SUBMODULES:
        return import_module(f".{name}", __name__)
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(f".{module}", __name__), name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | _EXPORTS.keys() | _SUBMODULES)


__all__ = [
    "AppRegistry",
    "CanaryTwinJudge",
    "CheckpointedExileCoordinator",
    "ChimeraClient",
    "ColabCliBridge",
    "CosmosEntityEngine",
    "CristaeFoldedCavityRLNC",
    "DisklessSecretVault",
    "EgressMembraneProxy",
    "EvidenceLedger",
    "FlightRecorderBlackBox",
    "GhostBubbleEngine",
    "HybridPlatformSearch",
    "HyperDeskEngine",
    "ImmortalJobEngine",
    "ImmuneSecurityKernel",
    "InMemoryWorkerTransport",
    "NvCudaPtxEngine",
    "OmegaEntityEngine",
    "OmniMemoryFabric",
    "PassivePortScanner",
    "PlatformSubstrate",
    "PulseBus",
    "SharedBrowserGrid",
    "ThermodynamicPhysicsEngine",
    "VaultSqlFabric",
    "VgpuParetoGateway",
    "VramCompressedSwap",
    "ZeroEnvCasStore",
    "ZygoteWorkerPool",
    "autoload_status",
    "chimera_home_dir",
    "connect",
    "discover_runtime_file",
    "find_browser_binary",
    "handle_mcp_request",
    "init_project",
    "install_autoload",
    "install_systemd_dropin",
    "is_available",
    "link_project",
    "parse_marked_json",
    "parse_usage_text",
    "probe_gpu_backends",
    "probe_nvidia_gpu",
    "render_smi",
    "runtime_beacon_paths",
    "select_lightest_profile",
    "serve_mcp_stdio",
    "unify_install",
    "unify_status",
    "unify_uninstall",
    "uninstall_autoload",
    "write_agents_infra_doc",
]
