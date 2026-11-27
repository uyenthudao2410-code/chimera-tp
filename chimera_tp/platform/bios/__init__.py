"""CHIMERA-BIOS: 10-Organ Living Open-Platform Substrate (100% lazy-loaded, 0 B boot RSS).

Importing this package does NOT eagerly import any organ engine — symbols resolve lazily
via PEP 562 ``__getattr__`` so ``PlatformSubstrate`` maintains strict Law-7 (<80 MiB RSS).
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

_MODULE_EXPORTS: dict[str, tuple[str, ...]] = {
    "organism": ("ChimeraBiosOrganism", "get_default_bios"),
    "endocrine": (
        "ENDO_BYTES",
        "ENDO_MAGIC",
        "ENDO_OFFSET",
        "ENDO_STRUCT",
        "HORMONE_NAMES",
        "WIRE_12B_STRUCT",
        "EndocrineSystem",
        "decode_wire_12b",
        "encode_wire_12b",
        "pack_endocrine_block",
        "read_endocrine_block_mmap",
        "read_hormones_mmap",
        "unpack_endocrine_block",
    ),
    "friston": ("ActiveInferenceBrain", "KNOWN_CONTEXTS", "MAX_STATE_BYTES"),
    "autophagy": ("MetabolicAutophagyEngine", "compute_atp_score"),
    "parasite": ("PARASITE_SCENARIOS", "RedQueenParasiteArena"),
    "octopus": (
        "BinaryReflexTable",
        "HookGanglion",
        "OctopusNervousSystem",
        "PeerSurvivalGanglion",
        "SocketGanglion",
        "SynapticReconciler",
    ),
    "stigmergy": ("StigmergicEpigenome",),
    "umwelt": ("CIRCADIAN_PHASES", "UmweltCognitiveResonator", "VALID_EVENT_KINDS"),
    "hgt": ("HorizontalGeneTransferEngine", "MAX_PLASMID_BYTES", "STARTER_PLASMIDS"),
    "mycelium": (
        "MAX_PWA_BYTES",
        "MyceliumSporeMesh",
        "blind_reconstruct",
        "blind_split",
        "render_spore_pwa_html",
    ),
    "soul": (
        "AutobiographicalSoul",
        "CHIMERA_ACTIVE_LAWS",
        "DEFAULT_MAX_TOKENS",
        "GENESIS_SCARS",
    ),
}

_EXPORTS: dict[str, str] = {
    name: mod for mod, names in _MODULE_EXPORTS.items() for name in names
}
_SUBMODULES: set[str] = set(_MODULE_EXPORTS.keys())


def __getattr__(name: str) -> Any:
    if name in _SUBMODULES:
        return import_module(f".{name}", __name__)
    mod_name = _EXPORTS.get(name)
    if mod_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    val = getattr(import_module(f".{mod_name}", __name__), name)
    globals()[name] = val
    return val


def __dir__() -> list[str]:
    return sorted(set(globals()) | _EXPORTS.keys() | _SUBMODULES)


__all__ = sorted(_EXPORTS.keys())
