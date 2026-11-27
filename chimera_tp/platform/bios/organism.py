"""CHIMERA-BIOS Organism Hub: Unites all 10 living systems behind one lazy Open Ecosystem Soul.

Constitutional Compliance (`docs/UNIFICATION_DOCTRINE.md` Laws 1–7):
- Law 2 (Zero-Choke Kernel Law): Strictly advisory physiology — zero hard CPU affinity
  pinning, zero forced background throttling, zero IPC process suspension.
- Law 6 (Evidence-Gated Rollback): Every evolutionary output (Autophagy Apoptosis PR,
  Parasite Vaccine Receipt, HGT Graft Proposal) enforces ``auto_activated=False`` and
  ``requires_human_approval=True``.
- Law 7 (Zero-Weight Ceiling): 100% lazy-instantiated per organ; total working memory
  strictly < 3 MiB, keeping daemon RSS well below 80 MiB (0 B overhead when unloaded).
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable


def _default_bios_dir() -> Path:
    env_home = os.environ.get("CHIMERA_HOME", "").strip()
    base = Path(env_home) if env_home else (Path.home() / ".chimera")
    return base / "bios"


def _current_rss_mb() -> float:
    """Zero-subprocess process RSS in MiB (Win32 K32GetProcessMemoryInfo / Linux /proc/self/statm)."""
    try:
        if os.name == "nt":
            import ctypes
            import ctypes.wintypes as wt

            class _PMC(ctypes.Structure):
                _fields_ = [
                    ("cb", wt.DWORD),
                    ("PageFaultCount", wt.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            k32 = ctypes.windll.kernel32
            k32.GetCurrentProcess.restype = ctypes.c_void_p
            fn = getattr(k32, "K32GetProcessMemoryInfo", None) or ctypes.windll.psapi.GetProcessMemoryInfo
            fn.argtypes = [ctypes.c_void_p, ctypes.POINTER(_PMC), wt.DWORD]
            fn.restype = wt.BOOL
            pmc = _PMC()
            pmc.cb = ctypes.sizeof(pmc)
            if fn(k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb):
                return round(float(pmc.WorkingSetSize) / (1024.0 * 1024.0), 2)
        else:
            statm = Path("/proc/self/statm").read_text(encoding="ascii").split()
            if len(statm) >= 2:
                pages = int(statm[1])
                page_sz = int(os.sysconf("SC_PAGE_SIZE"))
                return round((pages * page_sz) / (1024.0 * 1024.0), 2)
    except Exception:
        pass
    return 0.0


_PHASE_TO_CONTEXT: dict[str, str] = {
    "cad_mode": "cad",
    "swarm_coding": "coding",
    "deep_research": "research",
    "rest": "idle",
}


class ChimeraBiosOrganism:
    """Unified zero-weight Open Ecosystem Soul coordinating all 10 CHIMERA-BIOS living organs."""

    ORGAN_NAMES: tuple[str, ...] = (
        "endocrine",
        "friston",
        "autophagy",
        "parasite",
        "octopus",
        "stigmergy",
        "umwelt",
        "hgt",
        "mycelium",
        "soul",
    )

    def __init__(
        self,
        ops_dir: str | Path | None = None,
        repo_root: str | Path | None = None,
        node_name: str = "win-desktop",
        nixl_ring_path: str | Path | None = None,
        ephemeral: bool = False,
    ) -> None:
        self._lock = threading.RLock()
        self.ephemeral = bool(ephemeral)
        self.ops_dir = Path(ops_dir) if ops_dir is not None else _default_bios_dir()
        self.repo_root = (
            Path(repo_root).resolve()
            if repo_root is not None
            else Path(__file__).resolve().parents[3]
        )
        self.node_name = str(node_name or socket.gethostname() or "win-desktop")
        self.nixl_ring_path = Path(nixl_ring_path) if nixl_ring_path is not None else None
        self._started_at = time.time()
        self._pulse_seq = 0
        self._last_pulse_ts = self._started_at
        self._last_pulse: dict[str, Any] | None = None
        self._closed = False

        # All 10 organs strictly lazy-loaded on first access
        self._endocrine: Any = None
        self._friston: Any = None
        self._autophagy: Any = None
        self._parasite: Any = None
        self._octopus: Any = None
        self._stigmergy: Any = None
        self._umwelt: Any = None
        self._hgt: Any = None
        self._mycelium: Any = None
        self._soul: Any = None

    # ------------------------------------------------------------------
    # Lazy Organ Properties (#1 - #10)
    # ------------------------------------------------------------------

    @property
    def endocrine(self) -> Any:
        with self._lock:
            if self._endocrine is None:
                from .endocrine import EndocrineSystem

                # When an explicit isolated nixl_ring_path is provided (e.g. per-daemon temp ops_dir),
                # keep mmap active on that isolated ring without touching the host's default ring.
                endo_ephemeral = bool(self.ephemeral and self.nixl_ring_path is None)
                self._endocrine = EndocrineSystem(
                    ring_path=self.nixl_ring_path,
                    ephemeral=endo_ephemeral,
                )
            return self._endocrine

    @property
    def friston(self) -> Any:
        with self._lock:
            if self._friston is None:
                from .friston import ActiveInferenceBrain

                self._friston = ActiveInferenceBrain()
            return self._friston

    @property
    def autophagy(self) -> Any:
        with self._lock:
            if self._autophagy is None:
                from .autophagy import MetabolicAutophagyEngine

                self._autophagy = MetabolicAutophagyEngine(
                    ops_dir=self.ops_dir,
                    repo_root=self.repo_root,
                    ephemeral=self.ephemeral,
                )
            return self._autophagy

    @property
    def parasite(self) -> Any:
        with self._lock:
            if self._parasite is None:
                from .parasite import RedQueenParasiteArena

                self._parasite = RedQueenParasiteArena(
                    ops_dir=self.ops_dir,
                    ephemeral=self.ephemeral,
                )
            return self._parasite

    @property
    def octopus(self) -> Any:
        with self._lock:
            if self._octopus is None:
                from .octopus import OctopusNervousSystem

                self._octopus = OctopusNervousSystem(
                    ops_dir=self.ops_dir,
                    node_name=self.node_name,
                    ephemeral=self.ephemeral,
                )
            return self._octopus

    @property
    def stigmergy(self) -> Any:
        with self._lock:
            if self._stigmergy is None:
                from .stigmergy import StigmergicEpigenome

                self._stigmergy = StigmergicEpigenome(
                    ops_dir=self.ops_dir,
                    ephemeral=self.ephemeral,
                )
            return self._stigmergy

    @property
    def umwelt(self) -> Any:
        with self._lock:
            if self._umwelt is None:
                from .umwelt import UmweltCognitiveResonator

                self._umwelt = UmweltCognitiveResonator(
                    ops_dir=self.ops_dir,
                    ephemeral=self.ephemeral,
                )
            return self._umwelt

    @property
    def hgt(self) -> Any:
        with self._lock:
            if self._hgt is None:
                from .hgt import HorizontalGeneTransferEngine

                self._hgt = HorizontalGeneTransferEngine(
                    ops_dir=self.ops_dir,
                    ephemeral=self.ephemeral,
                )
            return self._hgt

    @property
    def mycelium(self) -> Any:
        with self._lock:
            if self._mycelium is None:
                from .mycelium import MyceliumSporeMesh

                self._mycelium = MyceliumSporeMesh(
                    ops_dir=self.ops_dir,
                    node_name=self.node_name,
                    ephemeral=self.ephemeral,
                )
            return self._mycelium

    @property
    def soul(self) -> Any:
        with self._lock:
            if self._soul is None:
                from .soul import AutobiographicalSoul

                self._soul = AutobiographicalSoul(
                    ops_dir=self.ops_dir,
                    ephemeral=self.ephemeral,
                )
            return self._soul

    def loaded_organs(self) -> list[str]:
        with self._lock:
            return [name for name in self.ORGAN_NAMES if getattr(self, f"_{name}", None) is not None]

    # ------------------------------------------------------------------
    # Closed-Loop Living Physiology Tick
    # ------------------------------------------------------------------

    def pulse(
        self,
        obs: dict[str, Any] | None = None,
        context: str | None = None,
    ) -> dict[str, Any]:
        """Run 1 unified closed-loop living physiology tick across the core organs.

        Flow:
          umwelt.assess() + friston.observe()
            -> endocrine decay + hormone secretion (synced to 24B NIXL mmap bytes 32..63)
            -> octopus binary reflex table refresh
            -> stigmergy exponential evaporation
            -> autophagy ATP ledger recording
            -> compact live `bios_pulse` frame for SSE / Spore PWA / Noosphere
        """
        t0 = time.perf_counter()
        now = time.time()

        # 1. Cognitive Seismograph (Umwelt)
        u_assess = self.umwelt.assess(now_ts=now)
        u_next = self.umwelt.anticipate_phase(now_ts=now, lead_minutes=5.0)
        active_phase = str(u_assess.get("active_phase") or "rest")
        ctx = str(context or _PHASE_TO_CONTEXT.get(active_phase, "general")).strip().lower() or "general"

        # 2. Active Inference Observation (Friston)
        rss_mb = _current_rss_mb()
        obs_dict: dict[str, Any] = {
            "rss_mb": rss_mb,
            "flow_score": float(u_assess.get("flow_score") or 0.0),
            "frustration_score": float(u_assess.get("frustration_score") or 0.0),
        }
        if isinstance(obs, dict):
            for k, v in obs.items():
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    obs_dict[str(k)] = float(v)

        f_obs = self.friston.observe(obs_dict, context=ctx, ts=now)
        f_plan = self.friston.plan_active_inference(obs_dict, context=ctx)

        # 3. Endocrine dynamics -> decay + secretion -> 24-byte NIXL mmap sync
        with self._lock:
            dt_s = max(0.0, min(300.0, now - self._last_pulse_ts))
            self._last_pulse_ts = now
            self._pulse_seq += 1
            seq = self._pulse_seq

        if dt_s >= 0.05:
            self.endocrine.decay(dt_s)

        surprise = float(f_obs.get("surprise") or 0.0)
        flow_score = float(u_assess.get("flow_score") or 0.0)
        frust_score = float(u_assess.get("frustration_score") or 0.0)
        pain_score = float(obs_dict.get("pain_score") or 0.0)

        secretions: list[str] = []
        if surprise >= 0.45:
            delta_a = round(min(0.30, 0.25 * surprise), 4)
            self.endocrine.secrete("adrenaline", delta_a, source="friston_surprise")
            secretions.append(f"adrenaline+{delta_a}")
        if frust_score >= 0.35:
            delta_c = round(min(0.22, 0.20 * frust_score), 4)
            self.endocrine.secrete("cortisol", delta_c, source="umwelt_frustration")
            secretions.append(f"cortisol+{delta_c}")
        if flow_score >= 0.55:
            delta_d = round(min(0.10, 0.08 * flow_score), 4)
            self.endocrine.secrete("dopamine", delta_d, source="umwelt_flow")
            secretions.append(f"dopamine+{delta_d}")
        if ctx == "idle" or active_phase == "rest":
            self.endocrine.secrete("melatonin", 0.05, source="umwelt_rest")
            secretions.append("melatonin+0.05")
        if pain_score >= 0.35:
            delta_cy = round(min(0.25, 0.30 * pain_score), 4)
            self.endocrine.secrete("cytokine", delta_cy, source="noosphere_pain")
            secretions.append(f"cytokine+{delta_cy}")

        # Apply Umwelt hormone hints gently if present
        hints = u_assess.get("hormone_hints")
        if isinstance(hints, dict):
            for h_name, h_delta in hints.items():
                if isinstance(h_delta, (int, float)) and abs(float(h_delta)) >= 0.01:
                    try:
                        self.endocrine.secrete(
                            str(h_name),
                            max(-0.12, min(0.12, float(h_delta) * 0.25)),
                            source="umwelt_hint",
                        )
                    except ValueError:
                        pass

        mmap_sync = self.endocrine.sync_to_mmap()
        levels = self.endocrine.levels()
        directives = self.endocrine.derive_directives()
        wire_12b_hex = self.endocrine.encode_wire_12b().hex()

        # 4. Sync Octopus binary reflex table (< 1 ms offline peripheral cache)
        antibodies_brief: list[dict[str, Any]] | None = None
        if self._parasite is not None:
            try:
                antibodies_brief = self._parasite.list_antibodies(limit=12)
            except Exception:
                antibodies_brief = None
        reflex_sync = self.octopus.sync_reflexes(
            hormones=levels,
            antibodies=antibodies_brief,
            daemon_online=True,
        )

        # 5. Stigmergy pheromone exponential decay
        evap = self.stigmergy.evaporate(now_ts=now)

        # 6. Autophagy metabolic ATP record
        elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 3)
        atp_rec = self.autophagy.record_metabolism(
            "bios.pulse",
            kind="organ",
            calls=1,
            ms_saved=max(0.5, 2.0 if u_assess.get("flow_shield") else 0.5),
            tokens_saved=40 if u_assess.get("whisper_triggered") else 0,
            errors_prevented=1 if surprise >= 0.65 else 0,
            now_ts=now,
        )

        # Collect Law-6 proposals if already initialized (never trigger heavy work on tick)
        law6_proposals: list[dict[str, Any]] = []
        if self._hgt is not None:
            try:
                law6_proposals.extend(self._hgt.list_proposals(limit=4))
            except Exception:
                pass
        if self._parasite is not None:
            try:
                for vac in self._parasite.list_vaccines(limit=3):
                    law6_proposals.append(
                        {
                            "proposal_id": vac.get("vaccine_id") or vac.get("receipt_id"),
                            "title": f"Vaccine:{vac.get('scenario', 'red_queen')}",
                            "target": vac.get("scenario", "immune"),
                            "verdict": "vaccine_ready",
                            "auto_activated": False,
                        }
                    )
            except Exception:
                pass

        frame: dict[str, Any] = {
            "ok": True,
            "event": "bios_pulse",
            "seq": seq,
            "ts": round(now, 3),
            "node": self.node_name,
            "context": ctx,
            "elapsed_ms": elapsed_ms,
            "rss_mb": rss_mb,
            "law7_rss_ok": rss_mb < 80.0,
            "hormones": {
                "levels": levels,
                "directives": directives,
                "mmap_synced": bool(mmap_sync.get("mmap_synced", False)),
                "mmap_seq": int(mmap_sync.get("seq") or 0),
                "wire_12b_hex": wire_12b_hex,
            },
            "directives": directives,
            "secretions": secretions,
            "surprise": round(surprise, 4),
            "free_energy_nats": round(float(f_obs.get("free_energy_nats") or 0.0), 4),
            "regime": str(f_obs.get("regime") or "nominal"),
            "active_inference_actions": f_plan[:4],
            "umwelt": {
                "assessment": u_assess,
                "anticipation": u_next,
            },
            "octopus": {
                "reflex_synced": bool(reflex_sync.get("ok", True)) if isinstance(reflex_sync, dict) else True,
                "reflex_bytes": int(self.octopus.reflex_table.byte_size()),
            },
            "stigmergy": {
                "evaporated": evap,
            },
            "autophagy": {
                "entity_id": "bios.pulse",
                "atp_score": atp_rec.get("atp_score", 0.0),
            },
            "law6_proposals": law6_proposals[:6],
            "law2_compliant": True,
            "law6_auto_activated": False,
        }
        with self._lock:
            self._last_pulse = frame
        return frame

    # ------------------------------------------------------------------
    # Machine-Readable Open Ecosystem ABI Manifest (NVIDIA-CUDA-Style)
    # ------------------------------------------------------------------

    def open_abi_manifest(self, anchor_url: str = "http://127.0.0.1:9780") -> dict[str, Any]:
        """Return the machine-readable CHIMERA-BIOS Open Ecosystem ABI specification."""
        base = str(anchor_url or "http://127.0.0.1:9780").rstrip("/")
        from .endocrine import (
            ENDO_BYTES,
            ENDO_MAGIC,
            ENDO_OFFSET,
            HORMONE_NAMES,
            default_nixl_ring_path,
        )

        ring_p = str(self.nixl_ring_path or default_nixl_ring_path())
        return {
            "ok": True,
            "schema": "chimera.bios.open_abi.v1",
            "version": "1.0.0",
            "name": "CHIMERA-BIOS Open Ecosystem Soul",
            "node": self.node_name,
            "anchor_url": base,
            "organs": list(self.ORGAN_NAMES),
            "binary_abi": {
                "nixl_mmap": {
                    "default_path": ring_p,
                    "env_override": "CHIMERA_NIXL_RING",
                    "total_header_bytes": 64,
                    "nixl_ring_header": {
                        "offset": 0,
                        "bytes": 32,
                        "struct_fmt": "<4sIIIQQ",
                        "magic": "NXLR",
                        "preserved_untouched": True,
                    },
                    "endocrine_block": {
                        "offset": ENDO_OFFSET,
                        "bytes": ENDO_BYTES,
                        "struct_fmt": "<4sHH6f",
                        "magic": ENDO_MAGIC.decode("ascii"),
                        "crc_algorithm": "CRC-16/CCITT-FALSE (poly=0x1021, init=0xFFFF over magic+seq+24B_floats)",
                        "fields": [
                            {"offset": 32, "bytes": 4, "type": "4s", "name": "magic"},
                            {"offset": 36, "bytes": 2, "type": "uint16_le", "name": "seq"},
                            {"offset": 38, "bytes": 2, "type": "uint16_le", "name": "crc16"},
                            {"offset": 40, "bytes": 4, "type": "float32_le", "name": "adrenaline"},
                            {"offset": 44, "bytes": 4, "type": "float32_le", "name": "cortisol"},
                            {"offset": 48, "bytes": 4, "type": "float32_le", "name": "dopamine"},
                            {"offset": 52, "bytes": 4, "type": "float32_le", "name": "melatonin"},
                            {"offset": 56, "bytes": 4, "type": "float32_le", "name": "cytokine"},
                            {"offset": 60, "bytes": 4, "type": "float32_le", "name": "oxytocin"},
                        ],
                        "hormone_order": list(HORMONE_NAMES),
                    },
                },
                "phantom_wire_12b": {
                    "bytes": 12,
                    "struct_fmt": "<6H",
                    "quantization": "round(clamp(v, 0.0, 1.0) * 65535)",
                    "hormone_order": list(HORMONE_NAMES),
                },
            },
            "endpoints": {
                "discover": {"method": "GET", "path": "/.well-known/chimera.json", "content_type": "application/json"},
                "status": {"method": "GET", "path": "/v1/bios/status", "content_type": "application/json"},
                "abi": {"method": "GET", "path": "/v1/bios/abi", "content_type": "application/json"},
                "hormones_get": {"method": "GET", "path": "/v1/bios/hormones", "content_type": "application/json"},
                "hormones_post": {"method": "POST", "path": "/v1/bios/hormones", "content_type": "application/json"},
                "pulse": {"method": "POST", "path": "/v1/bios/pulse", "content_type": "application/json"},
                "predict": {"method": "POST", "path": "/v1/bios/predict", "content_type": "application/json"},
                "autophagy_get": {"method": "GET", "path": "/v1/bios/autophagy", "content_type": "application/json"},
                "autophagy_post": {"method": "POST", "path": "/v1/bios/autophagy", "content_type": "application/json"},
                "parasite_status": {"method": "GET", "path": "/v1/bios/parasite/status", "content_type": "application/json"},
                "parasite_run": {"method": "POST", "path": "/v1/bios/parasite/run", "content_type": "application/json"},
                "ganglia_get": {"method": "GET", "path": "/v1/bios/ganglia", "content_type": "application/json"},
                "ganglia_reconcile": {"method": "POST", "path": "/v1/bios/ganglia/reconcile", "content_type": "application/json"},
                "pheromone_get": {"method": "GET", "path": "/v1/bios/pheromone", "content_type": "application/json"},
                "pheromone_post": {"method": "POST", "path": "/v1/bios/pheromone", "content_type": "application/json"},
                "umwelt_get": {"method": "GET", "path": "/v1/bios/umwelt", "content_type": "application/json"},
                "umwelt_post": {"method": "POST", "path": "/v1/bios/umwelt", "content_type": "application/json"},
                "hgt_get": {"method": "GET", "path": "/v1/bios/hgt", "content_type": "application/json"},
                "hgt_post": {"method": "POST", "path": "/v1/bios/hgt", "content_type": "application/json"},
                "spore_pwa": {"method": "GET", "path": "/v1/bios/spore", "content_type": "text/html; charset=utf-8"},
                "spores_list": {"method": "GET", "path": "/v1/bios/spores", "content_type": "application/json"},
                "spore_attach": {"method": "POST", "path": "/v1/bios/spore/attach", "content_type": "application/json"},
                "spore_autotomy": {"method": "POST", "path": "/v1/bios/spore/autotomy", "content_type": "application/json"},
                "spore_seed": {"method": "POST", "path": "/v1/bios/spore/seed", "content_type": "application/json"},
                "soul_get": {"method": "GET", "path": "/v1/bios/soul", "content_type": "application/json"},
                "soul_scar": {"method": "POST", "path": "/v1/bios/soul/scar", "content_type": "application/json"},
                "sync_bundle": {"method": "GET", "path": "/v1/bios/sync/bundle", "content_type": "application/json"},
                "sync": {"method": "POST", "path": "/v1/bios/sync", "content_type": "application/json"},
                "stream_sse": {"method": "GET", "path": "/v1/bios/stream", "content_type": "text/event-stream"},
            },
            "mcp_tools": [
                "chimera_bios_status",
                "chimera_bios_hormones",
                "chimera_bios_pheromone",
                "chimera_bios_soul",
                "chimera_bios_evolve",
            ],
            "cli_subcommands": [
                "status", "abi", "hormones", "pulse", "predict", "autophagy",
                "parasite", "ganglia", "pheromone", "umwelt", "hgt", "spore", "soul", "sync",
            ],
            "sdk_examples": {
                "python": (
                    "from chimera_tp.platform.client import connect\n"
                    "brain = connect(app='my-app')\n"
                    "print(brain.bios_hormones())\n"
                    "print(brain.bios_soul(query='law 7 rss', target_model='any'))"
                ),
                "nodejs": (
                    f"const res = await fetch('{base}/v1/bios/hormones').then(r => r.json());\n"
                    f"const es = new EventSource('{base}/v1/bios/stream');\n"
                    "es.onmessage = (ev) => console.log(JSON.parse(ev.data));"
                ),
                "rust": (
                    "// Read 32B ENDO block at byte offset 32 of chimera_nixl_ring.bin\n"
                    "let mut raw = [0u8; 32]; file.seek(SeekFrom::Start(32))?; file.read_exact(&mut raw)?;\n"
                    "assert_eq!(&raw[0..4], b\"ENDO\");"
                ),
                "curl": (
                    f"curl -s {base}/v1/bios/status && "
                    f"curl -sN '{base}/v1/bios/stream?once=1'"
                ),
            },
            "laws": {
                "law_1": "Eliminate waste before offload (Autophagy ATP ledger + Stigmergy + Friston)",
                "law_2": "Zero-Choke Kernel Law (advisory only: no hard CPU affinity pinning, no forced throttling or process suspension)",
                "law_3": "Mutual Homeostasis & Peer Guard (svhome 15W PeerSurvivalGanglion + 12B wire codec)",
                "law_4": "Content-Addressed Work Unit (SHA-256 Soul chain, BLAKE2s Merkle-CRDT, signed Plasmids)",
                "law_5": "Dual-Budget Placement (context-aware Friston Active Inference)",
                "law_6": "Evidence-Gated Rollback (auto_activated=False & requires_human_approval=True on all proposals)",
                "law_7": "Reverse-Consolidation & <80 MiB RSS (lazy self._bios=None, 0 B boot RSS, <3 MiB active working set)",
            },
        }

    # ------------------------------------------------------------------
    # Clean Organ Facade Methods (for HTTP, SDK, MCP, CLI)
    # ------------------------------------------------------------------

    def hormones(
        self,
        *,
        secrete: dict[str, Any] | None = None,
        action: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Read or mutate endocrine hormones, Oxytocin trust, or Cytokine inflammation."""
        p = dict(payload or {})
        if isinstance(secrete, dict) and secrete:
            p.update(secrete)
        act = str(action or p.get("action") or ("secrete" if p.get("hormone") else "get")).strip().lower()

        if act == "trust":
            app_id = str(p.get("app_id") or p.get("app") or "unknown")
            delta = float(p.get("delta") or 0.0)
            reason = str(p.get("reason") or "api")
            res = dict(self.endocrine.adjust_trust(app_id, delta, reason=reason))
            res.setdefault("ok", True)
            return res
        if act == "inflame":
            locus = str(p.get("locus") or p.get("target") or "workspace")
            intensity = float(p.get("intensity") if p.get("intensity") is not None else 0.5)
            reason = str(p.get("reason") or "api")
            res = dict(self.endocrine.inflame(locus, intensity, reason=reason))
            res.setdefault("ok", True)
            return res
        if act == "clear_inflammation":
            locus = str(p.get("locus") or p.get("target") or "")
            cleared = bool(self.endocrine.clear_inflammation(locus))
            return {
                "ok": True,
                "action": "clear_inflammation",
                "locus": locus,
                "cleared": cleared,
                "hormones": self.endocrine.levels(),
                "directives": self.endocrine.derive_directives(),
            }
        if act == "decay":
            dt_s = float(p.get("dt_s") or 10.0)
            res = dict(self.endocrine.decay(dt_s))
            res.setdefault("ok", True)
            return res
        if act == "secrete" and p.get("hormone"):
            res = dict(
                self.endocrine.secrete(
                    str(p["hormone"]),
                    float(p.get("delta") or 0.0),
                    source=str(p.get("source") or "api"),
                    target=(str(p["target"]) if p.get("target") else None),
                )
            )
            res.setdefault("ok", True)
            return res
        snap = self.endocrine.snapshot()
        snap.setdefault("ok", True)
        snap["wire_12b_hex"] = self.endocrine.encode_wire_12b().hex()
        return snap

    def predict(
        self,
        obs: dict[str, Any] | None = None,
        context: str = "general",
        horizon_s: float = 60.0,
        *,
        action: str = "all",
    ) -> dict[str, Any]:
        """Run Friston Active Inference observe / predict / plan."""
        ctx = str(context or "general").strip().lower() or "general"
        h_s = max(1.0, float(horizon_s or 60.0))
        act = str(action or "all").strip().lower()
        obs_d = dict(obs) if isinstance(obs, dict) else {}

        if act == "observe":
            return self.friston.observe(obs_d, context=ctx)
        if act == "predict":
            return self.friston.predict(h_s, context=ctx)
        if act == "plan":
            return {
                "ok": True,
                "context": ctx,
                "actions": self.friston.plan_active_inference(obs_d, context=ctx),
                "auto_activated": False,
            }

        observed = self.friston.observe(obs_d, context=ctx) if obs_d else None
        forecast = self.friston.predict(h_s, context=ctx)
        actions = self.friston.plan_active_inference(obs_d, context=ctx)
        return {
            "ok": True,
            "context": ctx,
            "horizon_s": h_s,
            "observation": observed,
            "forecast": forecast,
            "actions": actions,
            "state_bytes": self.friston.state_bytes_size(),
            "law2_compliant": True,
            "auto_activated": False,
        }

    def autophagy_dispatch(
        self,
        action: str = "status",
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Dispatch Metabolic Autophagy & Law-6 Apoptosis operations."""
        act = str(action or "status").strip().lower()
        p = dict(payload or {})
        if act == "record":
            return self.autophagy.record_metabolism(
                entity_id=str(p.get("entity_id") or "custom.entity"),
                kind=str(p.get("kind") or "module"),
                calls=int(p.get("calls") or 1),
                ms_saved=float(p.get("ms_saved") or 0.0),
                tokens_saved=int(p.get("tokens_saved") or 0),
                ram_saved_mb=float(p.get("ram_saved_mb") or 0.0),
                errors_prevented=int(p.get("errors_prevented") or 0),
            )
        if act == "ubiquitin":
            return self.autophagy.evaluate_ubiquitin(
                dormancy_days=float(p.get("dormancy_days") or 30.0),
                now_ts=p.get("now_ts"),
            )
        if act == "scan":
            return self.autophagy.scan_codebase_metabolism(
                repo_root=p.get("repo_root") or self.repo_root
            )
        if act in ("propose", "propose_apoptosis", "apoptosis"):
            res = self.autophagy.propose_apoptosis_pr(
                repo_root=p.get("repo_root") or self.repo_root,
                max_candidates=int(p.get("max_candidates") or 15),
            )
            res["auto_activated"] = False
            res["requires_human_approval"] = True
            return res
        return self.autophagy.status()

    def parasite_run(
        self,
        rounds: int = 4,
        *,
        seed: int | None = None,
        scenarios: list[str] | None = None,
    ) -> dict[str, Any]:
        """Execute isolated sandbox Red-Queen tournament and synthesize Law-6 vaccines."""
        res = self.parasite.run_arena(
            rounds=max(1, min(32, int(rounds or 4))),
            seed=seed,
            scenarios=scenarios,
        )
        res.setdefault("auto_activated", False)
        return res

    def parasite_status(self) -> dict[str, Any]:
        st = self.parasite.status()
        st["recent_vaccines"] = self.parasite.list_vaccines(limit=10)
        st["recent_antibodies"] = self.parasite.list_antibodies(limit=10)
        return st

    def ganglia_status(self) -> dict[str, Any]:
        return self.octopus.status()

    def ganglia_reconcile(
        self,
        local_events: list[dict[str, Any]] | None = None,
        peer_events: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        res = self.octopus.reconcile(
            local_events=local_events,
            peer_events=peer_events or [],
        )
        if isinstance(res, dict) and "root_hash" in res and "merkle_root" not in res:
            res = {**res, "merkle_root": res["root_hash"]}
        return res

    def pheromone(
        self,
        repo: str = ".",
        rel_path: str = "",
        *,
        action: str | None = None,
        alarm: dict[str, Any] | None = None,
        coedits: list[str] | None = None,
        methylation: dict[str, Any] | None = None,
        max_tokens: int = 40,
    ) -> dict[str, Any]:
        """Query <40-token smell-card or deposit alarm / co-edit trail / epigenetic methylation."""
        repo_s = str(repo or ".")
        rel_s = str(rel_path or "")
        act = str(action or "").strip().lower()
        results: dict[str, Any] = {}

        if isinstance(alarm, dict) and alarm:
            results["alarm"] = self.stigmergy.deposit_alarm(
                repo=repo_s,
                rel_path=str(alarm.get("rel_path") or rel_s or "."),
                signal_kind=str(alarm.get("signal_kind") or alarm.get("kind") or "regression"),
                severity=float(alarm.get("severity") if alarm.get("severity") is not None else 0.6),
                reason=str(alarm.get("reason") or ""),
                agent_id=str(alarm.get("agent_id") or "ecosystem"),
            )
        if isinstance(coedits, list) and len(coedits) >= 2:
            results["coedit"] = self.stigmergy.record_coedit(repo=repo_s, files=[str(f) for f in coedits])
        if isinstance(methylation, dict) and methylation:
            results["methylation"] = self.stigmergy.methylate(
                repo=repo_s,
                locus=str(methylation.get("locus") or rel_s or "."),
                gene_policy=str(methylation.get("gene_policy") or "extra_verify"),
                strength=float(methylation.get("strength") if methylation.get("strength") is not None else 0.8),
                half_life_days=float(methylation.get("half_life_days") or 7.0),
                reason=str(methylation.get("reason") or ""),
            )
        if act == "evaporate":
            results["evaporate"] = self.stigmergy.evaporate()
            return {"ok": True, **results}
        if act == "status" or (not rel_s and not results):
            st = self.stigmergy.status(repo=repo_s if repo_s != "." else None)
            if results:
                st["mutations"] = results
            return st

        card = self.stigmergy.smell(repo=repo_s, rel_path=rel_s, max_tokens=int(max_tokens or 40))
        if results:
            card["mutations"] = results
        return card

    def umwelt_dispatch(
        self,
        signal: dict[str, Any] | None = None,
        *,
        action: str = "assess",
        lead_minutes: float = 5.0,
    ) -> dict[str, Any]:
        """Record passive cognitive signals, assess Flow/Frustration, or anticipate circadian phase."""
        act = str(action or "assess").strip().lower()
        recorded: dict[str, Any] | None = None
        if isinstance(signal, dict) and signal.get("event_kind"):
            recorded = self.umwelt.record_signal(
                event_kind=str(signal.get("event_kind") or "idle_tick"),
                app=str(signal.get("app") or ""),
                target=str(signal.get("target") or ""),
                ok=bool(signal.get("ok", True)),
                ts=signal.get("ts"),
                meta=signal.get("meta") if isinstance(signal.get("meta"), dict) else None,
            )
        if act == "anticipate":
            out = self.umwelt.anticipate_phase(lead_minutes=float(lead_minutes or 5.0))
            if recorded is not None:
                out["recorded"] = recorded
            return out
        if act == "status":
            st = self.umwelt.status()
            if recorded is not None:
                st["recorded"] = recorded
            return st
        assessment = self.umwelt.assess()
        anticipation = self.umwelt.anticipate_phase(lead_minutes=float(lead_minutes or 5.0))
        res: dict[str, Any] = {
            "ok": True,
            "assessment": assessment,
            "anticipation": anticipation,
        }
        if recorded is not None:
            res["recorded"] = recorded
        return res

    def hgt_dispatch(
        self,
        action: str = "list",
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """List, extract, scan targets, or run sandbox A/B graft proposal (Law 6)."""
        act = str(action or "list").strip().lower()
        p = dict(payload or {})
        if act == "extract":
            return self.hgt.extract_plasmid(
                name=str(p.get("name") or "custom_plasmid"),
                source_project=str(p.get("source_project") or "chimera-tp"),
                code_or_spec=str(p.get("code_or_spec") or p.get("code_snippet") or ""),
                io_contract=p.get("io_contract") if isinstance(p.get("io_contract"), dict) else {},
                benchmark_oracle=p.get("benchmark_oracle") if isinstance(p.get("benchmark_oracle"), dict) else {},
                tags=list(p.get("tags") or []),
            )
        if act == "scan":
            pid = str(p.get("plasmid_id") or p.get("name") or "singleflight_coalescer")
            candidates = p.get("candidates") or p.get("candidate_repos_or_profiles") or [
                {"name": "tquota", "tags": ["concurrency", "cache", "http", "sqlite"]},
                {"name": "radar", "tags": ["sqlite", "wal", "ring_buffer", "ipc"]},
            ]
            matches = self.hgt.scan_ecosystem_targets(pid, list(candidates))
            return {"ok": True, "plasmid_id": pid, "matches": matches}
        if act in ("graft", "propose", "ab_race"):
            pid = str(p.get("plasmid_id") or p.get("name") or "singleflight_coalescer")
            target = str(p.get("target_name") or p.get("target") or "ecosystem_target")
            # Built-in deterministic micro-benchmark functions when called over JSON/HTTP
            cases = list(p.get("test_cases") or [list(range(24)), list(range(32)), list(range(16))])

            def _baseline(xs: Any) -> Any:
                vals = list(xs) if isinstance(xs, (list, tuple)) else [xs]
                acc = 0
                for v in vals:
                    acc += int(v) if isinstance(v, (int, float)) else len(str(v))
                return acc

            def _grafted(xs: Any) -> Any:
                vals = list(xs) if isinstance(xs, (list, tuple)) else [xs]
                return sum(int(v) if isinstance(v, (int, float)) else len(str(v)) for v in vals)

            res = self.hgt.sandbox_ab_graft(
                pid,
                target,
                _baseline,
                _grafted,
                cases,
                iterations=max(1, min(20, int(p.get("iterations") or 3))),
            )
            res["auto_activated"] = False
            res["requires_human_approval"] = True
            return res
        if act == "proposals":
            return {"ok": True, "proposals": self.hgt.list_proposals(limit=int(p.get("limit") or 20))}
        if act == "status":
            return self.hgt.status()
        plasmids = self.hgt.list_plasmids(tag=p.get("tag"))
        return {
            "ok": True,
            "count": len(plasmids),
            "plasmids": plasmids,
            "proposals": self.hgt.list_proposals(limit=10),
        }

    def spore_pwa_html(self, anchor_url: str = "") -> str:
        """Render the < 50 KB self-contained Zero-CDN CHIMERA-BIOS Spore PWA HTML."""
        from .mycelium import render_spore_pwa_html

        snap = {
            "hormones": {
                "levels": self.endocrine.levels(),
                "directives": self.endocrine.derive_directives(),
            },
            "umwelt": {
                "assessment": self.umwelt.assess(),
                "anticipation": self.umwelt.anticipate_phase(lead_minutes=5.0),
            },
            "soul": {
                "capsule": self.soul.export_capsule(max_tokens=360),
                "scar_count": len(self.soul.list_scars(limit=100)),
                "lineage_valid": bool(self.soul.verify_lineage().get("valid", True)),
            },
            "mycelium": {
                "node_name": self.node_name,
                "recent_seeds": self.mycelium.list_seeds(limit=5),
            },
            "law6_proposals": self.hgt.list_proposals(limit=4) if self._hgt is not None else [],
        }
        return render_spore_pwa_html(anchor_url=anchor_url, snapshot=snap)

    def spore_attach(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        p = dict(payload or {})
        dev = str(p.get("device_name") or p.get("device") or "browser-spore")
        role = str(p.get("role") or "mobile_pwa")
        caps = p.get("capabilities") if isinstance(p.get("capabilities"), list) else None
        tok_info = self.mycelium.issue_spore_token(
            device_name=dev,
            role=role,
            capabilities=caps,
            ttl_s=int(p.get("ttl_s") or 3600),
        )
        spore_id = str(p.get("spore_id") or tok_info.get("spore_id") or "")
        attached = self.mycelium.attach_spore(
            spore_id=spore_id,
            device_name=dev,
            role=role,
            capabilities=caps,
            host_hint=str(p.get("host_hint") or ""),
            token=tok_info.get("token"),
        )
        return {
            "ok": bool(attached.get("ok", True)),
            "spore": attached,
            "token_meta": {
                "spore_id": tok_info.get("spore_id"),
                "expires_at": tok_info.get("expires_at"),
                "role": tok_info.get("role"),
            },
        }

    def spore_autotomy(self, spore_id: str, reason: str = "detach") -> dict[str, Any]:
        res = self.mycelium.autotomy(str(spore_id or ""), reason=str(reason or "detach"))
        if isinstance(res, dict):
            res = {**res}
            res.setdefault("ok", bool(res.get("severed", True)))
        return res

    def spore_seed(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        p = dict(payload or {})
        res = self.mycelium.submit_seed(
            spore_id=str(p.get("spore_id") or "spore:anonymous"),
            text=str(p.get("text") or ""),
            priority=str(p.get("priority") or "normal"),
            kind=str(p.get("kind") or "idea"),
        )
        if isinstance(res, dict):
            res = {**res}
            res.setdefault("ok", True)
        return res

    def spores_list(self) -> dict[str, Any]:
        st = dict(self.mycelium.status())
        st.setdefault("ok", True)
        st["spores"] = self.mycelium.list_spores(include_detached=False)
        st["recent_seeds"] = self.mycelium.list_seeds(limit=20)
        return st

    def soul_capsule(
        self,
        query: str = "",
        target_model: str = "any",
        max_tokens: int = 500,
    ) -> dict[str, Any]:
        cap = self.soul.export_capsule(
            query=str(query or ""),
            target_model=str(target_model or "any"),
            max_tokens=max(80, min(500, int(max_tokens or 500))),
        )
        lineage = self.soul.verify_lineage()
        return {
            "ok": True,
            "capsule": cap,
            "lineage": lineage,
            "token_est": int(cap.get("token_est") or 0),
            "max_tokens": int(cap.get("max_tokens") or 500),
            "lineage_hash": cap.get("lineage_hash"),
        }

    def soul_record_scar(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        p = dict(payload or {})
        if str(p.get("kind") or "").lower() == "preference" or (p.get("domain") and p.get("key")):
            return self.soul.record_preference(
                domain=str(p.get("domain") or "architecture"),
                key=str(p.get("key") or "rule"),
                value=p.get("value"),
                evidence=str(p.get("evidence") or ""),
            )
        return self.soul.record_scar(
            title=str(p.get("title") or "Recorded scar"),
            event_date=str(p.get("event_date") or time.strftime("%Y-%m-%d")),
            root_cause=str(p.get("root_cause") or ""),
            lesson_law=str(p.get("lesson_law") or ""),
            hardware_context=str(p.get("hardware_context") or self.node_name),
            tags=list(p.get("tags") or []),
            severity=str(p.get("severity") or "high"),
        )

    # ------------------------------------------------------------------
    # 2-Way Bidirectional Cross-Host Sync (win-desktop <-> svhome)
    # ------------------------------------------------------------------

    MAX_EXPORT_BUNDLE_BYTES: int = 32 * 1024  # <= 32 KB compact outbound payload
    MAX_INBOUND_BUNDLE_BYTES: int = 64 * 1024  # Law 3 hard svhome payload cap <= 64 KB

    @staticmethod
    def _canonical_json_bytes(obj: Any) -> bytes:
        return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

    @classmethod
    def _bundle_sha256(cls, bundle: dict[str, Any]) -> str:
        body = {k: v for k, v in bundle.items() if k != "bundle_sha256"}
        return hashlib.sha256(cls._canonical_json_bytes(body)).hexdigest()

    def _export_stigmergy_alarms(self, max_alarms: int = 16, now_ts: float | None = None) -> list[dict[str, Any]]:
        """Read top active decayed alarm pheromones without mutating any repository files."""
        ts = time.time() if now_ts is None else float(now_ts)
        lim = max(0, min(64, int(max_alarms)))
        if lim == 0:
            return []
        stig = self.stigmergy
        with stig._lock:
            rows = stig._conn.execute(
                """
                SELECT repo, rel_path, signal_kind, intensity, half_life_s, last_reason, updated_ts
                FROM alarm_pheromones
                ORDER BY intensity DESC, updated_ts DESC
                LIMIT ?
                """,
                (lim * 2,),
            ).fetchall()
        active: list[dict[str, Any]] = []
        for row in rows:
            dt = max(0.0, ts - float(row["updated_ts"]))
            hl = max(1.0, float(row["half_life_s"]))
            eff = float(row["intensity"]) * (0.5 ** (dt / hl)) if dt > 0.0 else float(row["intensity"])
            if eff < 0.02:
                continue
            active.append(
                {
                    "repo": str(row["repo"])[:160],
                    "rel_path": str(row["rel_path"])[:200],
                    "signal_kind": str(row["signal_kind"])[:48],
                    "severity": round(min(1.0, max(0.01, eff)), 4),
                    "reason": str(row["last_reason"] or "")[:200],
                }
            )
        active.sort(key=lambda a: (-a["severity"], a["repo"], a["rel_path"], a["signal_kind"]))
        return active[:lim]

    def _import_stigmergy_alarms(self, alarms: list[Any], peer_node: str) -> int:
        """Idempotently import peer alarm pheromones without touching any repo files."""
        if not isinstance(alarms, list) or not alarms:
            return 0
        from .stigmergy import _decay_value, _norm_rel_path, _norm_repo

        stig = self.stigmergy
        now = time.time()
        imported = 0
        for item in alarms[:32]:
            if not isinstance(item, dict):
                continue
            repo = _norm_repo(str(item.get("repo") or "."))
            rel_path = _norm_rel_path(str(item.get("rel_path") or ""))
            signal_kind = str(item.get("signal_kind") or "warning").strip().lower()[:48]
            if not rel_path or not signal_kind:
                continue
            try:
                sev = max(0.01, min(1.0, float(item.get("severity") if item.get("severity") is not None else 0.5)))
            except (TypeError, ValueError):
                sev = 0.5
            reason = str(item.get("reason") or "")[:200]
            with stig._lock:
                row = stig._conn.execute(
                    """
                    SELECT intensity, half_life_s, updated_ts
                    FROM alarm_pheromones
                    WHERE repo = ? AND rel_path = ? AND signal_kind = ?
                    """,
                    (repo, rel_path, signal_kind),
                ).fetchone()
            if row is not None:
                eff = _decay_value(float(row["intensity"]), now - float(row["updated_ts"]), float(row["half_life_s"]))
                if eff >= sev - 0.05:
                    continue
                # Raise intensity cleanly to peer level without noisy-OR inflation on repeated syncs
                with stig._lock:
                    stig._conn.execute(
                        """
                        UPDATE alarm_pheromones
                        SET intensity = ?, last_reason = CASE WHEN ? != '' THEN ? ELSE last_reason END,
                            last_agent_id = ?, updated_ts = ?
                        WHERE repo = ? AND rel_path = ? AND signal_kind = ?
                        """,
                        (round(sev, 4), reason, reason, f"peer:{peer_node}"[:64], now, repo, rel_path, signal_kind),
                    )
                    stig._conn.commit()
                imported += 1
            else:
                stig.deposit_alarm(
                    repo=repo,
                    rel_path=rel_path,
                    signal_kind=signal_kind,
                    severity=sev,
                    reason=reason,
                    agent_id=f"peer:{peer_node}"[:64],
                    now_ts=now,
                )
                imported += 1
        return imported

    def _import_soul_scars(self, scars: list[Any]) -> int:
        """Idempotently import missing peer scars keyed by (title, event_date) keeping hash-chain valid."""
        if not isinstance(scars, list) or not scars:
            return 0
        existing = self.soul.list_scars(limit=10000)
        existing_keys = {
            (str(s.get("title") or "").strip().lower(), str(s.get("event_date") or "").strip())
            for s in existing
        }
        imported = 0
        for sc in scars[:32]:
            if not isinstance(sc, dict):
                continue
            title = str(sc.get("title") or "").strip()
            event_date = str(sc.get("event_date") or "").strip()
            if not title or not event_date:
                continue
            key = (title.lower(), event_date)
            if key in existing_keys:
                continue
            tags_raw = sc.get("tags")
            tags = [str(t) for t in tags_raw] if isinstance(tags_raw, (list, tuple)) else []
            self.soul.record_scar(
                title=title,
                event_date=event_date,
                root_cause=str(sc.get("root_cause") or ""),
                lesson_law=str(sc.get("lesson_law") or ""),
                hardware_context=str(sc.get("hardware_context") or ""),
                tags=tags,
                severity=str(sc.get("severity") or "high"),
            )
            existing_keys.add(key)
            imported += 1
        return imported

    def _import_mycelium_seeds(self, seeds: list[Any]) -> int:
        """Idempotently import missing peer Mycelium seeds keyed by seed_id."""
        if not isinstance(seeds, list) or not seeds:
            return 0
        myc = self.mycelium
        imported = 0
        with myc._lock:
            assert myc._conn is not None
            for sd in seeds[:32]:
                if not isinstance(sd, dict):
                    continue
                text = str(sd.get("text") or "").strip()
                if not text:
                    continue
                spore_id = str(sd.get("spore_id") or "peer_spore").strip()[:96]
                if spore_id in myc._revoked_spores:
                    continue
                pri = str(sd.get("priority") or "normal").strip().lower()
                if pri not in ("low", "normal", "high", "urgent"):
                    pri = "normal"
                kind = str(sd.get("kind") or "idea").strip().lower()[:32]
                try:
                    created_at = float(sd.get("created_at") or time.time())
                except (TypeError, ValueError):
                    created_at = time.time()
                digest = hashlib.sha256(f"{spore_id}|{text}|{pri}|{created_at:.6f}".encode("utf-8")).hexdigest()
                seed_id = str(sd.get("seed_id") or "").strip()[:64] or f"seed_{digest[:12]}"
                cur = myc._conn.execute(
                    """
                    INSERT OR IGNORE INTO seeds (seed_id, spore_id, text, priority, kind, status, sha256, created_at)
                    VALUES (?, ?, ?, ?, ?, 'queued', ?, ?)
                    """,
                    (seed_id, spore_id, text[:1000], pri, kind, digest, created_at),
                )
                if cur.rowcount and cur.rowcount > 0:
                    imported += 1
            if imported > 0:
                myc._conn.commit()
        return imported

    def export_sync_bundle(
        self,
        max_events: int = 32,
        max_alarms: int = 16,
        max_scars: int = 16,
        max_seeds: int = 16,
    ) -> dict[str, Any]:
        """Export a compact, JSON-serializable, <= 32 KB cross-host CHIMERA-BIOS sync bundle."""
        now = time.time()
        lim_ev = max(1, min(64, int(max_events)))
        lim_al = max(0, min(32, int(max_alarms)))
        lim_sc = max(0, min(32, int(max_scars)))
        lim_sd = max(0, min(32, int(max_seeds)))

        # Ensure at least 1 stamped bios_sync_heartbeat event exists so Merkle-CRDT convergence is always verifiable
        all_events = self.octopus.peer_ganglion.export_events()
        if not all_events:
            self.octopus.peer_ganglion.append_event(
                "bios_sync_heartbeat",
                {"node": self.node_name, "ts": round(now, 3)},
                key=f"bios_hb:{self.node_name}",
                now_ts=now,
            )
            all_events = self.octopus.peer_ganglion.export_events()

        crdt_events = list(all_events[-lim_ev:])
        merkle_root = self.octopus.reconciler.compute_merkle_root(all_events)
        wire_12b = self.endocrine.encode_wire_12b()
        endocrine_wire_b64 = base64.b64encode(wire_12b).decode("ascii")
        hormones = self.endocrine.levels()
        alarms = self._export_stigmergy_alarms(max_alarms=lim_al, now_ts=now)

        all_scars = self.soul.list_scars(limit=1000)
        scars_slice = all_scars[-lim_sc:] if lim_sc > 0 else []
        soul_scars = [
            {
                "title": str(s.get("title") or "")[:160],
                "event_date": str(s.get("event_date") or "")[:32],
                "root_cause": str(s.get("root_cause") or "")[:360],
                "lesson_law": str(s.get("lesson_law") or "")[:360],
                "hardware_context": str(s.get("hardware_context") or "")[:160],
                "tags": list(s.get("tags") or [])[:12],
                "severity": str(s.get("severity") or "high"),
                "entry_hash": str(s.get("entry_hash") or ""),
            }
            for s in scars_slice
        ]

        seeds_raw = self.mycelium.list_seeds(limit=lim_sd) if lim_sd > 0 else []
        mycelium_seeds = [
            {
                "seed_id": str(sd.get("seed_id") or ""),
                "spore_id": str(sd.get("spore_id") or ""),
                "text": str(sd.get("text") or "")[:320],
                "priority": str(sd.get("priority") or "normal"),
                "created_at": float(sd.get("created_at") or now),
            }
            for sd in seeds_raw
        ]

        def _assemble(
            ev_list: list[dict[str, Any]],
            al_list: list[dict[str, Any]],
            sc_list: list[dict[str, Any]],
            sd_list: list[dict[str, Any]],
        ) -> dict[str, Any]:
            body: dict[str, Any] = {
                "schema": "chimera.bios.sync_bundle.v1",
                "node_name": self.node_name,
                "ts": round(now, 3),
                "endocrine_wire_b64": endocrine_wire_b64,
                "hormones": hormones,
                "crdt_events": ev_list,
                "merkle_root": merkle_root,
                "stigmergy_alarms": al_list,
                "soul_scars": sc_list,
                "mycelium_seeds": sd_list,
                "auto_activated": False,
            }
            body["bundle_sha256"] = self._bundle_sha256(body)
            return body

        bundle = _assemble(crdt_events, alarms, soul_scars, mycelium_seeds)
        # Strictly enforce <= 32 KB Law-3 compact bundle ceiling
        while len(self._canonical_json_bytes(bundle)) > self.MAX_EXPORT_BUNDLE_BYTES:
            if len(mycelium_seeds) > 2:
                mycelium_seeds = mycelium_seeds[: len(mycelium_seeds) // 2]
            elif len(alarms) > 2:
                alarms = alarms[: len(alarms) // 2]
            elif len(soul_scars) > 2:
                soul_scars = soul_scars[-(len(soul_scars) // 2) :]
            elif len(crdt_events) > 4:
                crdt_events = crdt_events[-(len(crdt_events) // 2) :]
            else:
                break
            bundle = _assemble(crdt_events, alarms, soul_scars, mycelium_seeds)

        return bundle

    def apply_sync_bundle(
        self,
        bundle: dict[str, Any],
        *,
        blend: float = 0.35,
        return_reply_bundle: bool = False,
    ) -> dict[str, Any]:
        """Apply an inbound peer CHIMERA-BIOS sync bundle cleanly under Laws 1-7."""
        t0 = time.perf_counter()
        if not isinstance(bundle, dict):
            raise ValueError("sync_bundle_must_be_dict")

        # Law 3 hard guard: reject oversized payloads > 64 KB
        raw_bytes = self._canonical_json_bytes(bundle)
        if len(raw_bytes) > self.MAX_INBOUND_BUNDLE_BYTES:
            raise ValueError(
                f"sync_bundle_exceeds_64kb_law3_cap:{len(raw_bytes)}>{self.MAX_INBOUND_BUNDLE_BYTES}"
            )

        # Law 4 integrity check when bundle_sha256 is supplied
        claimed_sha = str(bundle.get("bundle_sha256") or "").strip()
        if claimed_sha:
            expected_sha = self._bundle_sha256(bundle)
            if claimed_sha != expected_sha:
                raise ValueError("sync_bundle_sha256_mismatch")

        peer_node = str(bundle.get("node_name") or "peer").strip() or "peer"
        alpha = max(0.0, min(1.0, float(blend)))

        # 1. Decode & blend 12-byte PHANTOM endocrine wire payload (syncs to NIXL mmap bytes 32..63)
        wire_b64 = bundle.get("endocrine_wire_b64")
        if isinstance(wire_b64, str) and wire_b64.strip():
            try:
                raw_12b = base64.b64decode(wire_b64.encode("ascii"), validate=True)
            except Exception as exc:
                raise ValueError(f"invalid_endocrine_wire_b64:{exc}") from exc
            if len(raw_12b) != 12:
                raise ValueError(f"invalid_endocrine_wire_len:{len(raw_12b)}")
        elif isinstance(bundle.get("hormones"), dict):
            from .endocrine import encode_wire_12b

            raw_12b = encode_wire_12b(bundle["hormones"])
        else:
            raw_12b = self.endocrine.encode_wire_12b()

        wire_res = self.endocrine.apply_wire_12b(raw_12b, blend=alpha)
        hormones_blended = dict(wire_res.get("hormones") or self.endocrine.levels())
        endocrine_mmap_ok = bool(wire_res.get("mmap_synced", False))

        # 2. Record peer liveness BEFORE reconcile so any island_mode recovery event is included in Merkle state
        self.octopus.peer_ganglion.record_peer_heartbeat(peer_node)

        # 3. Deterministic HLC + BLAKE2s Merkle-CRDT reconciliation
        peer_events_raw = bundle.get("crdt_events")
        peer_events = [e for e in peer_events_raw[:64] if isinstance(e, dict)] if isinstance(peer_events_raw, list) else []
        local_events = self.octopus.peer_ganglion.export_events()
        rec = self.octopus.reconciler.reconcile(local_events, peer_events)
        events_added = self.octopus.peer_ganglion.absorb_merged_events(rec["merged_events"])
        merkle_root = self.octopus.reconciler.compute_merkle_root(
            self.octopus.peer_ganglion.export_events()
        )

        # 4. Idempotent import of peer Stigmergy alarms, Soul scars & Mycelium seeds
        alarms_imported = self._import_stigmergy_alarms(bundle.get("stigmergy_alarms") or [], peer_node=peer_node)
        scars_imported = self._import_soul_scars(bundle.get("soul_scars") or [])
        seeds_imported = self._import_mycelium_seeds(bundle.get("mycelium_seeds") or [])

        # 5. Refresh Octopus binary reflex table & record metabolic ATP yield
        antibodies_brief: list[dict[str, Any]] | None = None
        if self._parasite is not None:
            try:
                antibodies_brief = self._parasite.list_antibodies(limit=12)
            except Exception:
                antibodies_brief = None
        self.octopus.sync_reflexes(
            hormones=hormones_blended,
            antibodies=antibodies_brief,
            daemon_online=True,
        )
        self.autophagy.record_metabolism(
            "bios.sync",
            kind="organ",
            calls=1,
            ms_saved=1.0,
            tokens_saved=scars_imported * 60 + alarms_imported * 25 + seeds_imported * 20,
            errors_prevented=alarms_imported,
        )

        elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 3)
        receipt: dict[str, Any] = {
            "ok": True,
            "node_name": self.node_name,
            "peer_node": peer_node,
            "merkle_root": merkle_root,
            "events_merged": int(rec.get("total_events") or 0),
            "events_added": int(events_added),
            "scars_imported": int(scars_imported),
            "alarms_imported": int(alarms_imported),
            "seeds_imported": int(seeds_imported),
            "hormones_blended": hormones_blended,
            "endocrine_wire_bytes": 12,
            "endocrine_mmap_ok": endocrine_mmap_ok,
            "auto_activated": False,
            "elapsed_ms": elapsed_ms,
        }
        if return_reply_bundle:
            receipt["reply_bundle"] = self.export_sync_bundle()
        return receipt

    def sync_with_peer(
        self,
        peer_base_url: str,
        *,
        headers: dict[str, str] | None = None,
        blend: float = 0.35,
        timeout_s: float = 4.0,
        request_authorizer: Callable[[urllib.request.Request], Any] | None = None,
    ) -> dict[str, Any]:
        """Execute 1-RTT 2-way bidirectional CHIMERA-BIOS sync with a peer node and verify Merkle convergence."""
        peer_url = str(peer_base_url or "").strip().rstrip("/")
        if not peer_url:
            return {
                "ok": False,
                "error": "missing_peer_url",
                "node_name": self.node_name,
                "merkle_converged": False,
                "auto_activated": False,
            }

        t0 = time.perf_counter()
        alpha = max(0.0, min(1.0, float(blend)))
        tout = max(0.5, min(30.0, float(timeout_s or 4.0)))
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

        def _post_peer(path: str, payload: dict[str, Any]) -> dict[str, Any]:
            raw = self._canonical_json_bytes(payload)
            req_hdrs = {"Content-Type": "application/json"}
            if headers:
                for k, v in headers.items():
                    req_hdrs[str(k)] = str(v)
            req = urllib.request.Request(
                f"{peer_url}{path}",
                data=raw,
                headers=req_hdrs,
                method="POST",
            )
            if request_authorizer is not None:
                request_authorizer(req)
            with opener.open(req, timeout=tout) as resp:
                data = resp.read(192 * 1024)
            parsed = json.loads(data.decode("utf-8", errors="replace"))
            if not isinstance(parsed, dict):
                raise ValueError("peer_non_object_response")
            return parsed

        def _get_peer(path: str) -> dict[str, Any]:
            req_hdrs: dict[str, str] = {}
            if headers:
                for k, v in headers.items():
                    req_hdrs[str(k)] = str(v)
            req = urllib.request.Request(f"{peer_url}{path}", headers=req_hdrs, method="GET")
            if request_authorizer is not None:
                request_authorizer(req)
            with opener.open(req, timeout=tout) as resp:
                data = resp.read(192 * 1024)
            parsed = json.loads(data.decode("utf-8", errors="replace"))
            if not isinstance(parsed, dict):
                raise ValueError("peer_non_object_response")
            return parsed

        bundle_a = self.export_sync_bundle()
        try:
            peer_resp = _post_peer(
                "/v1/bios/sync",
                {"bundle": bundle_a, "blend": alpha, "bidirectional": True},
            )
        except urllib.error.HTTPError as exc:
            err_detail = f"http_{exc.code}"
            try:
                err_body = json.loads(exc.read(4096).decode("utf-8", errors="replace"))
                if isinstance(err_body, dict) and err_body.get("error"):
                    err_detail = f"http_{exc.code}:{err_body['error']}"
            except Exception:
                pass
            return {
                "ok": False,
                "error": f"peer_sync_failed:{err_detail}",
                "node_name": self.node_name,
                "peer_url": peer_url,
                "merkle_converged": False,
                "rtt_ms": round((time.perf_counter() - t0) * 1000.0, 2),
                "auto_activated": False,
            }
        except Exception as exc:
            return {
                "ok": False,
                "error": f"peer_sync_unreachable:{type(exc).__name__}:{exc}",
                "node_name": self.node_name,
                "peer_url": peer_url,
                "merkle_converged": False,
                "rtt_ms": round((time.perf_counter() - t0) * 1000.0, 2),
                "auto_activated": False,
            }

        if not peer_resp.get("ok"):
            return {
                "ok": False,
                "error": str(peer_resp.get("error") or "peer_rejected_sync"),
                "node_name": self.node_name,
                "peer_url": peer_url,
                "merkle_converged": False,
                "rtt_ms": round((time.perf_counter() - t0) * 1000.0, 2),
                "auto_activated": False,
            }

        reply_bundle = peer_resp.get("reply_bundle")
        if not isinstance(reply_bundle, dict):
            try:
                reply_bundle = _get_peer("/v1/bios/sync/bundle")
            except Exception as exc:
                return {
                    "ok": False,
                    "error": f"peer_reply_bundle_fetch_failed:{type(exc).__name__}:{exc}",
                    "node_name": self.node_name,
                    "peer_url": peer_url,
                    "merkle_converged": False,
                    "rtt_ms": round((time.perf_counter() - t0) * 1000.0, 2),
                    "auto_activated": False,
                }

        local_apply = self.apply_sync_bundle(reply_bundle, blend=alpha, return_reply_bundle=False)
        local_merkle_root = str(local_apply.get("merkle_root") or "")
        peer_merkle_root = str(peer_resp.get("merkle_root") or reply_bundle.get("merkle_root") or "")
        round_trips = 1

        pushed_scars = int(peer_resp.get("scars_imported") or 0)
        pushed_alarms = int(peer_resp.get("alarms_imported") or 0)
        pushed_seeds = int(peer_resp.get("seeds_imported") or 0)

        # If a concurrent local event or delta prevented 1-RTT convergence, run 1 confirm push (blend=0.0)
        if local_merkle_root != peer_merkle_root:
            try:
                confirm_bundle = self.export_sync_bundle()
                confirm_resp = _post_peer(
                    "/v1/bios/sync",
                    {"bundle": confirm_bundle, "blend": 0.0, "bidirectional": False},
                )
                round_trips += 1
                if confirm_resp.get("ok"):
                    peer_merkle_root = str(confirm_resp.get("merkle_root") or peer_merkle_root)
                    pushed_scars += int(confirm_resp.get("scars_imported") or 0)
                    pushed_alarms += int(confirm_resp.get("alarms_imported") or 0)
                    pushed_seeds += int(confirm_resp.get("seeds_imported") or 0)
            except Exception:
                pass

        rtt_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        peer_node = str(peer_resp.get("node_name") or reply_bundle.get("node_name") or "peer")
        # Safe post-reconcile RTT update: apply_sync_bundle already cleared island_mode, so zero new CRDT events emitted
        self.octopus.peer_ganglion.record_peer_heartbeat(peer_node, rtt_ms=rtt_ms)

        pulled_scars = int(local_apply.get("scars_imported") or 0)
        pulled_alarms = int(local_apply.get("alarms_imported") or 0)
        pulled_seeds = int(local_apply.get("seeds_imported") or 0)
        converged = bool(local_merkle_root and local_merkle_root == peer_merkle_root)

        result: dict[str, Any] = {
            "ok": True,
            "direction": "bidirectional",
            "node_name": self.node_name,
            "peer_node": peer_node,
            "peer_url": peer_url,
            "local_merkle_root": local_merkle_root,
            "peer_merkle_root": peer_merkle_root,
            "merkle_converged": converged,
            "rtt_ms": rtt_ms,
            "round_trips": round_trips,
            "endocrine_wire_bytes": 12,
            "endocrine_mmap_ok": bool(local_apply.get("endocrine_mmap_ok", False)),
            "peer_endocrine_mmap_ok": bool(peer_resp.get("endocrine_mmap_ok", False)),
            "hormones": local_apply.get("hormones_blended") or self.endocrine.levels(),
            "events_merged": int(local_apply.get("events_merged") or 0),
            "scars_synced": {
                "pushed_to_peer": pushed_scars,
                "pulled_from_peer": pulled_scars,
                "total": pushed_scars + pulled_scars,
            },
            "alarms_synced": {
                "pushed_to_peer": pushed_alarms,
                "pulled_from_peer": pulled_alarms,
                "total": pushed_alarms + pulled_alarms,
            },
            "seeds_synced": {
                "pushed_to_peer": pushed_seeds,
                "pulled_from_peer": pulled_seeds,
                "total": pushed_seeds + pulled_seeds,
            },
            "local_bundle_sha256": str(bundle_a.get("bundle_sha256") or ""),
            "peer_bundle_sha256": str(reply_bundle.get("bundle_sha256") or ""),
            "auto_activated": False,
        }
        result["receipt_sha256"] = hashlib.sha256(self._canonical_json_bytes(result)).hexdigest()
        return result

    # ------------------------------------------------------------------
    # Unified 10-Organ Status Snapshot
    # ------------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        """Return full 10-organ living organism status (PWA + API + MCP compatible)."""
        rss_mb = _current_rss_mb()
        endo_snap = self.endocrine.snapshot()
        friston_st = self.friston.status()
        auto_st = self.autophagy.status()
        para_st = self.parasite.status()
        octo_st = self.octopus.status()
        stig_st = self.stigmergy.status()
        umw_st = self.umwelt.status()
        hgt_st = self.hgt.status()
        myc_st = self.mycelium.status()
        soul_st = self.soul.status()
        soul_cap = self.soul.export_capsule(max_tokens=450)
        soul_lin = self.soul.verify_lineage()
        hgt_props = self.hgt.list_proposals(limit=6)

        law6_proposals: list[dict[str, Any]] = list(hgt_props)
        for vac in self.parasite.list_vaccines(limit=4):
            law6_proposals.append(
                {
                    "proposal_id": vac.get("vaccine_id") or vac.get("receipt_id"),
                    "title": f"Vaccine:{vac.get('scenario', 'red_queen')}",
                    "target": vac.get("scenario", "immune"),
                    "verdict": "vaccine_ready",
                    "auto_activated": False,
                }
            )

        return {
            "ok": True,
            "engine": "chimera-bios-v1",
            "node": self.node_name,
            "ephemeral": self.ephemeral,
            "uptime_s": round(max(0.0, time.time() - self._started_at), 2),
            "pulses_total": self._pulse_seq,
            "rss_mb": rss_mb,
            "law2_compliant": True,
            "law6_auto_activated": False,
            "law7_rss_ok": rss_mb < 80.0,
            "organs_loaded": self.loaded_organs(),
            "organs_count": len(self.ORGAN_NAMES),
            # PWA & top-level ergonomic views
            "hormones": {
                "levels": endo_snap.get("levels") or self.endocrine.levels(),
                "directives": endo_snap.get("directives") or self.endocrine.derive_directives(),
                "mmap_seq": endo_snap.get("seq", 0),
                "wire_12b_hex": self.endocrine.encode_wire_12b().hex(),
            },
            "umwelt": {
                "assessment": umw_st.get("assessment") or self.umwelt.assess(),
                "anticipation": umw_st.get("anticipation") or self.umwelt.anticipate_phase(lead_minutes=5.0),
            },
            "soul": {
                "capsule": soul_cap,
                "lineage_hash": soul_lin.get("head_hash") or soul_cap.get("lineage_hash"),
                "lineage_valid": bool(soul_lin.get("valid", True)),
                "scar_count": int(soul_lin.get("scar_count") or 0),
                "recent_scars": self.soul.list_scars(limit=4),
            },
            "mycelium": {
                "node_name": self.node_name,
                "active_spores": len(self.mycelium.list_spores(include_detached=False)),
                "recent_seeds": self.mycelium.list_seeds(limit=6),
            },
            "law6_proposals": law6_proposals[:8],
            "organs": {
                "endocrine": endo_snap,
                "friston": friston_st,
                "autophagy": auto_st,
                "parasite": para_st,
                "octopus": octo_st,
                "stigmergy": stig_st,
                "umwelt": umw_st,
                "hgt": hgt_st,
                "mycelium": myc_st,
                "soul": soul_st,
            },
        }

    def close(self) -> None:
        with self._lock:
            self._closed = True
            for name in self.ORGAN_NAMES:
                attr = f"_{name}"
                inst = getattr(self, attr, None)
                if inst is not None and hasattr(inst, "close"):
                    try:
                        inst.close()
                    except Exception:
                        pass
                setattr(self, attr, None)


_DEFAULT_LOCK = threading.Lock()
_DEFAULT_BIOS: ChimeraBiosOrganism | None = None


def get_default_bios(*, ephemeral: bool = False) -> ChimeraBiosOrganism:
    """Lazy process-local ChimeraBiosOrganism singleton for offline SDK / CLI / MCP fallback."""
    global _DEFAULT_BIOS
    if ephemeral:
        return ChimeraBiosOrganism(ephemeral=True)
    with _DEFAULT_LOCK:
        if _DEFAULT_BIOS is None or _DEFAULT_BIOS._closed:
            _DEFAULT_BIOS = ChimeraBiosOrganism(ephemeral=False)
        return _DEFAULT_BIOS
