"""CHIMERA Omega-Spine: Polyglot X-Ray, Akashic Cortex, Iron Cage, Precog, Streamable MCP & Hooks."""

from __future__ import annotations

from .akashic_cortex import AkashicCortex, get_akashic_cortex
from .csharp_xray import (
    callgraph_slice,
    impacted_dotnet_tests,
    outline_file,
    resolve_safe_repo,
    surgical_bundle,
    syntax_gate_csharp,
)

__all__ = [
    "AkashicCortex",
    "get_akashic_cortex",
    "outline_file",
    "callgraph_slice",
    "surgical_bundle",
    "syntax_gate_csharp",
    "impacted_dotnet_tests",
    "resolve_safe_repo",
]

# Guarded optional re-exports from sibling omega_spine modules so imports never break
# while modules load or initialize independently.
try:
    from . import iron_cage as _iron_cage

    for _name in (
        "apply_royal_ui_tier",
        "cage_worker_pid",
        "spawn_caged",
        "SingleflightCommandCache",
        "cage_sweep_agent_children",
    ):
        if hasattr(_iron_cage, _name):
            globals()[_name] = getattr(_iron_cage, _name)
            __all__.append(_name)
except Exception:
    pass

try:
    from . import precog_tournament as _precog_tournament

    for _name in ("PrecogVerifier", "ShadowTournament", "get_precog_verifier", "get_shadow_tournament"):
        if hasattr(_precog_tournament, _name):
            globals()[_name] = getattr(_precog_tournament, _name)
            __all__.append(_name)
except Exception:
    pass

try:
    from . import streamable_mcp as _streamable_mcp

    for _name in ("StreamableMcpServer", "handle_mcp_request", "get_mcp_server"):
        if hasattr(_streamable_mcp, _name):
            globals()[_name] = getattr(_streamable_mcp, _name)
            __all__.append(_name)
except Exception:
    pass

try:
    from . import hook_router as _hook_router

    for _name in ("HookRouter", "handle_hook_event", "get_hook_router"):
        if hasattr(_hook_router, _name):
            globals()[_name] = getattr(_hook_router, _name)
            __all__.append(_name)
except Exception:
    pass

try:
    from . import release_conductor as _release_conductor

    for _name in ("ReleaseConductor", "context_hygiene_audit", "default_releases_root"):
        if hasattr(_release_conductor, _name):
            globals()[_name] = getattr(_release_conductor, _name)
            __all__.append(_name)
except Exception:
    pass
