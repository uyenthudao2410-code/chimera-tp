"""CHIMERA-ENDOCRINE (BIOS Idea #1): 24-Byte Hormonal Soup in NIXL mmap + Open Receptor Bus.

Stores 6 continuous physiological hormones directly inside the reserved bytes 32..63
of the 64-byte ``NixlSignalRing`` header (``chimera_nixl_ring.bin``), leaving bytes
0..31 (``<4sIIIQQ`` ``NXLR`` header) and all 256 ring slots completely untouched.

Binary layout at offset 32..63 (32 bytes exact, little-endian ``<4sHH6f``):
    bytes 32..35 : ``b"ENDO"`` magic (4 bytes)
    bytes 36..37 : ``seq`` (uint16, monotonic wrapping update counter)
    bytes 38..39 : ``crc16`` (uint16, CRC-16/CCITT-FALSE over magic + seq + 24B floats)
    bytes 40..63 : 6 x float32 (24 bytes) in ``HORMONE_NAMES`` order

Cross-host PHANTOM wire codec (12 bytes exact, little-endian ``<6H``):
    6 x uint16 quantized hormones (``round(clamp(v, 0, 1) * 65535)``).

100% Python stdlib, zero external dependencies, lazy-loaded, strictly Law 2 advisory-only.
"""

from __future__ import annotations

import collections
import mmap
import os
import struct
import threading
import time
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

HORMONE_NAMES: tuple[str, ...] = (
    "adrenaline",
    "cortisol",
    "dopamine",
    "melatonin",
    "cytokine",
    "oxytocin",
)

# NIXL ring geometry (must stay byte-for-byte identical to chimera_tp/platform/aeon_dynamo.py)
_NIXL_MAGIC = b"NXLR"
_NIXL_VERSION = 1
_NIXL_HEADER_BYTES = 64
_NIXL_SLOT_COUNT = 256
_NIXL_SLOT_BYTES = 1024
_NIXL_RING_BYTES = _NIXL_HEADER_BYTES + _NIXL_SLOT_COUNT * _NIXL_SLOT_BYTES

# Endocrine mmap block inside reserved bytes 32..63 of NIXL header
ENDO_MAGIC = b"ENDO"
ENDO_OFFSET = 32
ENDO_BYTES = 32
ENDO_STRUCT = struct.Struct("<4sHH6f")
WIRE_12B_STRUCT = struct.Struct("<6H")

assert ENDO_STRUCT.size == ENDO_BYTES == 32
assert WIRE_12B_STRUCT.size == 12

# Homeostasis setpoints (calm healthy organism baseline)
HOMEOSTASIS_SETPOINTS: dict[str, float] = {
    "adrenaline": 0.15,
    "cortisol": 0.10,
    "dopamine": 0.50,
    "melatonin": 0.20,
    "cytokine": 0.05,
    "oxytocin": 0.65,
}

# Biological exponential half-life in seconds toward homeostasis setpoint
HORMONE_HALF_LIFE_S: dict[str, float] = {
    "adrenaline": 45.0,
    "cortisol": 300.0,
    "dopamine": 120.0,
    "melatonin": 240.0,
    "cytokine": 600.0,
    "oxytocin": 900.0,
}


def _clamp01(value: float) -> float:
    v = float(value)
    if v != v:  # NaN guard
        return 0.0
    if v < 0.0:
        return 0.0
    if v > 1.0:
        return 1.0
    return v


def _build_crc16_table() -> tuple[int, ...]:
    tbl: list[int] = []
    for i in range(256):
        crc = i << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if (crc & 0x8000) else (crc << 1) & 0xFFFF
        tbl.append(crc)
    return tuple(tbl)


_CRC16_TABLE: tuple[int, ...] = _build_crc16_table()


def _crc16_ccitt(data: bytes | bytearray | memoryview) -> int:
    """Compute CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF) via 256-entry lookup table."""
    crc = 0xFFFF
    tbl = _CRC16_TABLE
    for byte in data:
        crc = ((crc << 8) & 0xFFFF) ^ tbl[((crc >> 8) ^ byte) & 0xFF]
    return crc


def default_nixl_ring_path() -> Path:
    """Resolve default NIXL shared-memory ring path matching aeon_dynamo.py."""
    env_p = os.environ.get("CHIMERA_NIXL_RING", "").strip()
    if env_p:
        return Path(env_p)
    if os.name == "nt":
        if Path("V:/").exists():
            return Path("V:/nixl/chimera_nixl_ring.bin")
        return Path.home() / ".chimera" / "chimera_nixl_ring.bin"
    if Path("/dev/shm").is_dir():
        return Path("/dev/shm/chimera_nixl_ring.bin")
    return Path.home() / ".chimera" / "chimera_nixl_ring.bin"


def _normalize_hormone_tuple(hormones: Mapping[str, float] | Sequence[float]) -> tuple[float, ...]:
    if isinstance(hormones, Mapping):
        return tuple(_clamp01(hormones.get(name, HOMEOSTASIS_SETPOINTS[name])) for name in HORMONE_NAMES)
    vals = list(hormones)
    if len(vals) != len(HORMONE_NAMES):
        raise ValueError(f"Expected {len(HORMONE_NAMES)} hormone values, got {len(vals)}")
    return tuple(_clamp01(v) for v in vals)


def pack_endocrine_block(hormones: Mapping[str, float] | Sequence[float], seq: int = 1) -> bytes:
    """Pack 6 float32 hormones + 8-byte ENDO header into an exact 32-byte block."""
    vals = _normalize_hormone_tuple(hormones)
    seq_u16 = int(seq) & 0xFFFF
    payload_24b = struct.pack("<6f", *vals)
    crc_input = struct.pack("<4sH", ENDO_MAGIC, seq_u16) + payload_24b
    crc16 = _crc16_ccitt(crc_input)
    return ENDO_STRUCT.pack(ENDO_MAGIC, seq_u16, crc16, *vals)


def unpack_endocrine_block(raw: bytes | bytearray | memoryview) -> dict[str, Any]:
    """Unpack and CRC-16 verify a 32-byte ENDO block."""
    if len(raw) < ENDO_BYTES:
        raise ValueError(f"Expected at least {ENDO_BYTES} bytes, got {len(raw)}")
    magic, seq_u16, stored_crc, *vals = ENDO_STRUCT.unpack_from(raw, 0)
    if magic != ENDO_MAGIC:
        return {
            "valid": False,
            "error": "invalid_magic",
            "seq": 0,
            "crc16": 0,
            "hormones": dict(HOMEOSTASIS_SETPOINTS),
        }
    payload_24b = bytes(raw[8:32])
    expected_crc = _crc16_ccitt(struct.pack("<4sH", magic, seq_u16) + payload_24b)
    if expected_crc != stored_crc:
        return {
            "valid": False,
            "error": "crc16_mismatch",
            "seq": int(seq_u16),
            "crc16": int(stored_crc),
            "expected_crc16": int(expected_crc),
            "hormones": dict(HOMEOSTASIS_SETPOINTS),
        }
    hormones = {name: round(_clamp01(v), 6) for name, v in zip(HORMONE_NAMES, vals)}
    return {
        "valid": True,
        "magic": "ENDO",
        "seq": int(seq_u16),
        "crc16": int(stored_crc),
        "hormones": hormones,
    }


def encode_wire_12b(hormones: Mapping[str, float] | Sequence[float]) -> bytes:
    """Encode 6 hormones into a 12-byte PHANTOM wire payload (6 x uint16 LE)."""
    vals = _normalize_hormone_tuple(hormones)
    quantized = tuple(int(round(v * 65535.0)) for v in vals)
    return WIRE_12B_STRUCT.pack(*quantized)


def decode_wire_12b(data: bytes | bytearray | memoryview) -> dict[str, float]:
    """Decode a 12-byte PHANTOM wire payload back into 6 hormone floats in [0, 1]."""
    if len(data) != WIRE_12B_STRUCT.size:
        raise ValueError(f"Expected exact 12-byte wire payload, got {len(data)} bytes")
    quantized = WIRE_12B_STRUCT.unpack_from(data, 0)
    return {name: round(u / 65535.0, 6) for name, u in zip(HORMONE_NAMES, quantized)}


def read_endocrine_block_mmap(ring_path: str | Path | None = None) -> dict[str, Any]:
    """Zero-copy mmap read of bytes 32..63 from the NIXL ring with timing and CRC validation."""
    t0 = time.perf_counter()
    path = Path(ring_path) if ring_path is not None else default_nixl_ring_path()
    if not path.is_file():
        return {
            "ok": False,
            "valid": False,
            "error": "ring_not_found",
            "path": str(path),
            "seq": 0,
            "hormones": dict(HOMEOSTASIS_SETPOINTS),
            "latency_us": round((time.perf_counter() - t0) * 1e6, 2),
        }
    try:
        with path.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            if size < _NIXL_HEADER_BYTES:
                return {
                    "ok": False,
                    "valid": False,
                    "error": "ring_too_small",
                    "path": str(path),
                    "seq": 0,
                    "hormones": dict(HOMEOSTASIS_SETPOINTS),
                    "latency_us": round((time.perf_counter() - t0) * 1e6, 2),
                }
            with mmap.mmap(fh.fileno(), _NIXL_HEADER_BYTES, access=mmap.ACCESS_READ) as mm:
                raw_block = mm[ENDO_OFFSET : ENDO_OFFSET + ENDO_BYTES]
        decoded = unpack_endocrine_block(raw_block)
        decoded["ok"] = bool(decoded["valid"])
        decoded["path"] = str(path)
        decoded["latency_us"] = round((time.perf_counter() - t0) * 1e6, 2)
        return decoded
    except OSError as exc:
        return {
            "ok": False,
            "valid": False,
            "error": f"mmap_read_error:{exc.__class__.__name__}",
            "path": str(path),
            "seq": 0,
            "hormones": dict(HOMEOSTASIS_SETPOINTS),
            "latency_us": round((time.perf_counter() - t0) * 1e6, 2),
        }


def read_hormones_mmap(ring_path: str | Path | None = None, *, strict: bool = False) -> dict[str, float]:
    """Zero-copy microsecond reader for external processes reading the 6 hormones from NIXL mmap."""
    block = read_endocrine_block_mmap(ring_path)
    if strict and not block.get("valid"):
        raise ValueError(f"Failed to read valid ENDO block from {block.get('path')}: {block.get('error')}")
    return dict(block["hormones"])


def _trust_to_policy(trust: float) -> dict[str, Any]:
    t = round(_clamp01(trust), 4)
    if t >= 0.75:
        return {
            "tier": "symbiotic",
            "lane": "fast_lane",
            "cow_isolation": False,
            "require_sandbox": False,
            "max_concurrent_leases": 8,
            "trust_score": t,
        }
    if t >= 0.40:
        return {
            "tier": "standard",
            "lane": "standard",
            "cow_isolation": True,
            "require_sandbox": False,
            "max_concurrent_leases": 4,
            "trust_score": t,
        }
    return {
        "tier": "quarantined",
        "lane": "sandbox_cow",
        "cow_isolation": True,
        "require_sandbox": True,
        "max_concurrent_leases": 1,
        "trust_score": t,
    }


class EndocrineSystem:
    """Living hormonal bus writing 24-byte hormone vectors + 8-byte header to NIXL mmap bytes 32..63."""

    def __init__(
        self,
        ring_path: str | Path | None = None,
        *,
        ephemeral: bool = False,
        initial_levels: Mapping[str, float] | None = None,
    ) -> None:
        self.ephemeral = bool(ephemeral)
        self.ring_path = Path(ring_path) if ring_path is not None else default_nixl_ring_path()
        self._lock = threading.RLock()
        self._fh: Any = None
        self._mm: mmap.mmap | None = None
        self._seq: int = 0
        self._levels: dict[str, float] = dict(HOMEOSTASIS_SETPOINTS)
        if initial_levels:
            for k, v in initial_levels.items():
                if k in self._levels:
                    self._levels[k] = _clamp01(v)
        self._trust_ledger: dict[str, dict[str, Any]] = {}
        self._inflamed_loci: dict[str, dict[str, Any]] = {}
        self._receptors: dict[str, Callable[[dict[str, Any]], Any]] = {}
        self._events: collections.deque[dict[str, Any]] = collections.deque(maxlen=64)
        self._last_update_ts: float = time.time()
        self._sync_to_mmap_locked()

    def _ensure_mmap_locked(self) -> mmap.mmap | None:
        if self.ephemeral:
            return None
        if self._mm is not None:
            return self._mm
        try:
            self.ring_path.parent.mkdir(parents=True, exist_ok=True)
            existed = self.ring_path.is_file()
            mode = "r+b" if existed else "w+b"
            fh = self.ring_path.open(mode)
            fh.seek(0, os.SEEK_END)
            sz = fh.tell()
            if sz < _NIXL_RING_BYTES:
                existing_head = b""
                if sz > 0:
                    fh.seek(0)
                    existing_head = fh.read(min(sz, _NIXL_HEADER_BYTES))
                fh.seek(0)
                buf = bytearray(_NIXL_RING_BYTES)
                if len(existing_head) >= 4 and existing_head[:4] == _NIXL_MAGIC:
                    # Preserve valid existing NXLR bytes 0..31 verbatim
                    keep = min(len(existing_head), ENDO_OFFSET)
                    buf[:keep] = existing_head[:keep]
                else:
                    struct.pack_into(
                        "<4sIIIQQ",
                        buf,
                        0,
                        _NIXL_MAGIC,
                        _NIXL_VERSION,
                        _NIXL_SLOT_COUNT,
                        _NIXL_SLOT_BYTES,
                        0,
                        0,
                    )
                fh.write(buf)
                fh.flush()
            mm = mmap.mmap(fh.fileno(), _NIXL_RING_BYTES)
            # Only initialize bytes 0..31 if ring was blank; NEVER clobber a live NXLR header
            if mm[:4] != _NIXL_MAGIC:
                struct.pack_into(
                    "<4sIIIQQ",
                    mm,
                    0,
                    _NIXL_MAGIC,
                    _NIXL_VERSION,
                    _NIXL_SLOT_COUNT,
                    _NIXL_SLOT_BYTES,
                    0,
                    0,
                )
            self._fh = fh
            self._mm = mm
            return mm
        except OSError:
            return None

    def _sync_to_mmap_locked(self) -> bool:
        self._seq = (self._seq + 1) & 0xFFFF
        if self._seq == 0:
            self._seq = 1
        block = pack_endocrine_block(self._levels, seq=self._seq)
        mm = self._ensure_mmap_locked()
        if mm is None:
            return False
        # Strictly write ONLY bytes 32..63; bytes 0..31 and 64..end are untouched
        mm[ENDO_OFFSET : ENDO_OFFSET + ENDO_BYTES] = block
        return True

    def _dispatch_receptors(self, event_payload: dict[str, Any]) -> None:
        with self._lock:
            callbacks = list(self._receptors.items())
        for _name, fn in callbacks:
            try:
                fn(event_payload)
            except Exception:
                # External receptor exceptions are isolated from core physiology
                continue

    def levels(self) -> dict[str, float]:
        """Return a copy of the 6 current hormone levels."""
        with self._lock:
            return {k: round(self._levels[k], 6) for k in HORMONE_NAMES}

    def sync_to_mmap(self) -> dict[str, Any]:
        """Force-flush the current 24-byte hormone vector to NIXL mmap bytes 32..63."""
        t0 = time.perf_counter()
        with self._lock:
            synced = self._sync_to_mmap_locked()
            return {
                "ok": synced or self.ephemeral,
                "mmap_synced": synced,
                "seq": self._seq,
                "latency_us": round((time.perf_counter() - t0) * 1e6, 2),
            }

    def read_from_mmap(self) -> dict[str, float]:
        """Read the current hormone vector directly via zero-copy mmap (or memory if ephemeral)."""
        if self.ephemeral:
            return self.levels()
        with self._lock:
            if self._mm is not None:
                blk = unpack_endocrine_block(self._mm[ENDO_OFFSET : ENDO_OFFSET + ENDO_BYTES])
                if blk.get("valid"):
                    return dict(blk["hormones"])
        return read_hormones_mmap(self.ring_path)

    def encode_wire_12b(self) -> bytes:
        """Encode current hormone vector into 12-byte PHANTOM wire format."""
        with self._lock:
            return encode_wire_12b(self._levels)

    def apply_wire_12b(self, data: bytes | bytearray | memoryview, *, blend: float = 0.5) -> dict[str, Any]:
        """Blend a peer host's 12-byte PHANTOM hormone packet into local physiology."""
        peer_levels = decode_wire_12b(data)
        alpha = _clamp01(blend)
        with self._lock:
            for name in HORMONE_NAMES:
                self._levels[name] = _clamp01((1.0 - alpha) * self._levels[name] + alpha * peer_levels[name])
            synced = self._sync_to_mmap_locked()
            self._last_update_ts = time.time()
            directives = self._derive_directives_locked()
            snap = {
                "ok": True,
                "event": "wire_blend",
                "blend": alpha,
                "peer_hormones": peer_levels,
                "hormones": self.levels(),
                "directives": directives,
                "seq": self._seq,
                "mmap_synced": synced,
            }
        self._dispatch_receptors(snap)
        return snap

    def secrete(
        self,
        hormone: str,
        delta: float,
        source: str = "system",
        target: str | None = None,
    ) -> dict[str, Any]:
        """Secrete a hormone delta with biological cross-hormone antagonism and mmap sync."""
        h = str(hormone).strip().lower()
        if h not in self._levels:
            raise ValueError(f"Unknown hormone {hormone!r}; expected one of {HORMONE_NAMES}")
        d = float(delta)
        now = time.time()
        with self._lock:
            prev = self._levels[h]
            new_val = _clamp01(prev + d)
            self._levels[h] = new_val

            # Biological cross-hormone antagonism
            if h == "adrenaline" and d > 0.0:
                # High adrenaline suppresses melatonin (fight-or-flight inhibits sleep)
                suppress = 0.45 * d * (0.55 + 0.45 * new_val)
                self._levels["melatonin"] = _clamp01(self._levels["melatonin"] - suppress)
                if new_val > 0.85:
                    # Extreme adrenaline slightly nudges cortisol
                    self._levels["cortisol"] = _clamp01(self._levels["cortisol"] + 0.12 * d)
            elif h == "cortisol" and d > 0.0:
                # Sustained cortisol damps dopamine and disturbs melatonin
                damp = 0.35 * d * (0.50 + 0.50 * new_val)
                self._levels["dopamine"] = _clamp01(self._levels["dopamine"] - damp)
                self._levels["melatonin"] = _clamp01(self._levels["melatonin"] - 0.15 * d)
            elif h == "melatonin" and d > 0.0:
                # Rising melatonin gently calms adrenaline
                self._levels["adrenaline"] = _clamp01(self._levels["adrenaline"] - 0.25 * d)
            elif h == "dopamine" and d > 0.0:
                # Positive reward gently buffers cortisol
                self._levels["cortisol"] = _clamp01(self._levels["cortisol"] - 0.18 * d)
            elif h == "cytokine" and d > 0.0:
                # Localized danger elevates mild vigilance cortisol & reduces blind trust
                self._levels["cortisol"] = _clamp01(self._levels["cortisol"] + 0.20 * d)
                self._levels["oxytocin"] = _clamp01(self._levels["oxytocin"] - 0.15 * d)
                if target:
                    self._inflame_locked(target, d, reason=f"secrete:{source}", now=now, couple_global=False)
            elif h == "oxytocin" and d != 0.0:
                if d > 0.0:
                    self._levels["cortisol"] = _clamp01(self._levels["cortisol"] - 0.15 * d)
                if target:
                    self._adjust_trust_locked(target, d, reason=f"secrete:{source}", now=now, couple_global=False)

            synced = self._sync_to_mmap_locked()
            self._last_update_ts = now
            directives = self._derive_directives_locked()
            cur_levels = {k: round(self._levels[k], 6) for k in HORMONE_NAMES}
            ev = {
                "ts": round(now, 3),
                "event": "secrete",
                "hormone": h,
                "delta": round(d, 4),
                "prev": round(prev, 6),
                "level": cur_levels[h],
                "source": str(source),
                "target": target,
                "seq": self._seq,
            }
            self._events.append(ev)
            result = {
                "ok": True,
                "event": "secrete",
                "hormone": h,
                "level": cur_levels[h],
                "hormones": cur_levels,
                "directives": directives,
                "seq": self._seq,
                "mmap_synced": synced,
            }
        self._dispatch_receptors(result)
        return result

    def decay(self, dt_s: float) -> dict[str, Any]:
        """Apply smooth exponential half-life decay toward homeostasis + continuous antagonism."""
        dt = max(0.0, float(dt_s))
        now = time.time()
        with self._lock:
            if dt > 0.0:
                # Continuous cross-hormone antagonism target shifts before exponential relaxation
                adrenaline_now = self._levels["adrenaline"]
                cortisol_now = self._levels["cortisol"]

                effective_targets = dict(HOMEOSTASIS_SETPOINTS)
                if adrenaline_now > 0.50:
                    # Active adrenaline holds melatonin down
                    effective_targets["melatonin"] = max(
                        0.02, HOMEOSTASIS_SETPOINTS["melatonin"] * (1.0 - 0.75 * (adrenaline_now - 0.50) * 2.0)
                    )
                if cortisol_now > 0.50:
                    # Sustained high cortisol depresses dopamine baseline
                    effective_targets["dopamine"] = max(
                        0.10, HOMEOSTASIS_SETPOINTS["dopamine"] - 0.35 * (cortisol_now - 0.50) * 2.0
                    )

                for name in HORMONE_NAMES:
                    hl = HORMONE_HALF_LIFE_S[name]
                    factor = 0.5 ** (dt / hl)
                    target_val = effective_targets[name]
                    cur = self._levels[name]
                    self._levels[name] = _clamp01(target_val + (cur - target_val) * factor)

                # Decay localized inflammation loci
                locus_factor = 0.5 ** (dt / HORMONE_HALF_LIFE_S["cytokine"])
                to_drop: list[str] = []
                for locus, info in self._inflamed_loci.items():
                    next_intensity = info["intensity"] * locus_factor
                    if next_intensity < 0.01:
                        to_drop.append(locus)
                    else:
                        info["intensity"] = round(next_intensity, 6)
                for locus in to_drop:
                    del self._inflamed_loci[locus]

            synced = self._sync_to_mmap_locked()
            self._last_update_ts = now
            cur_levels = {k: round(self._levels[k], 6) for k in HORMONE_NAMES}
            directives = self._derive_directives_locked()
            result = {
                "ok": True,
                "event": "decay",
                "dt_s": dt,
                "hormones": cur_levels,
                "directives": directives,
                "seq": self._seq,
                "mmap_synced": synced,
            }
        self._dispatch_receptors(result)
        return result

    def _adjust_trust_locked(
        self,
        app_id: str,
        delta: float,
        reason: str,
        now: float,
        *,
        couple_global: bool = True,
    ) -> dict[str, Any]:
        key = str(app_id).strip()
        if not key:
            raise ValueError("app_id must be non-empty")
        entry = self._trust_ledger.get(key)
        prev = entry["trust"] if entry else HOMEOSTASIS_SETPOINTS["oxytocin"]
        nxt = _clamp01(prev + float(delta))
        policy = _trust_to_policy(nxt)
        self._trust_ledger[key] = {
            "app_id": key,
            "trust": round(nxt, 6),
            "last_reason": str(reason),
            "updated_ts": round(now, 3),
            "events": (entry["events"] + 1) if entry else 1,
            "policy": policy,
        }
        if couple_global:
            self._levels["oxytocin"] = _clamp01(self._levels["oxytocin"] + 0.25 * float(delta))
        return {
            "app_id": key,
            "prev_trust": round(prev, 6),
            "trust": round(nxt, 6),
            "delta": round(float(delta), 6),
            "reason": str(reason),
            "trust_policy": policy,
            "oxytocin": round(self._levels["oxytocin"], 6),
        }

    def adjust_trust(self, app_id: str, delta: float, reason: str = "") -> dict[str, Any]:
        """Adjust per-app/agent Oxytocin trust and return lane/CoW/sandbox constraints."""
        now = time.time()
        with self._lock:
            res = self._adjust_trust_locked(app_id, delta, reason, now, couple_global=True)
            synced = self._sync_to_mmap_locked()
            self._last_update_ts = now
            directives = self._derive_directives_locked()
            res["mmap_synced"] = synced
            res["seq"] = self._seq
            res["directives"] = directives
            self._events.append(
                {
                    "ts": round(now, 3),
                    "event": "trust",
                    "app_id": res["app_id"],
                    "trust": res["trust"],
                    "tier": res["trust_policy"]["tier"],
                    "reason": str(reason),
                }
            )
            payload = {
                "event": "trust",
                "hormones": self.levels(),
                "directives": directives,
                "trust_update": res,
                "seq": self._seq,
            }
        self._dispatch_receptors(payload)
        return res

    def get_trust_policy(self, app_id: str) -> dict[str, Any]:
        """Inspect current trust policy for an app/agent without mutating state."""
        key = str(app_id).strip()
        with self._lock:
            entry = self._trust_ledger.get(key)
            trust = entry["trust"] if entry else HOMEOSTASIS_SETPOINTS["oxytocin"]
            return _trust_to_policy(trust)

    def _inflame_locked(
        self,
        locus: str,
        intensity: float,
        reason: str,
        now: float,
        *,
        couple_global: bool = True,
    ) -> dict[str, Any]:
        key = str(locus).strip().replace("\\", "/")
        if not key:
            raise ValueError("locus must be non-empty")
        entry = self._inflamed_loci.get(key)
        prev = entry["intensity"] if entry else 0.0
        nxt = _clamp01(prev + float(intensity))
        if nxt < 0.01:
            self._inflamed_loci.pop(key, None)
            nxt = 0.0
        else:
            self._inflamed_loci[key] = {
                "locus": key,
                "intensity": round(nxt, 6),
                "reason": str(reason),
                "updated_ts": round(now, 3),
                "hits": (entry["hits"] + 1) if entry else 1,
            }
        if couple_global and nxt > 0.0:
            peak = max((v["intensity"] for v in self._inflamed_loci.values()), default=0.0)
            self._levels["cytokine"] = _clamp01(max(self._levels["cytokine"], peak * 0.85))
            if intensity > 0.0:
                self._levels["cortisol"] = _clamp01(self._levels["cortisol"] + 0.12 * float(intensity))
        return {
            "locus": key,
            "prev_intensity": round(prev, 6),
            "intensity": round(nxt, 6),
            "reason": str(reason),
            "cytokine": round(self._levels["cytokine"], 6),
            "inflamed_loci_count": len(self._inflamed_loci),
        }

    def inflame(self, locus: str, intensity: float, reason: str = "") -> dict[str, Any]:
        """Record localized Cytokine inflammation on a path/repo/subsystem."""
        now = time.time()
        with self._lock:
            res = self._inflame_locked(locus, intensity, reason, now, couple_global=True)
            synced = self._sync_to_mmap_locked()
            self._last_update_ts = now
            directives = self._derive_directives_locked()
            res["mmap_synced"] = synced
            res["seq"] = self._seq
            res["directives"] = directives
            self._events.append(
                {
                    "ts": round(now, 3),
                    "event": "inflame",
                    "locus": res["locus"],
                    "intensity": res["intensity"],
                    "reason": str(reason),
                }
            )
            payload = {
                "event": "inflame",
                "hormones": self.levels(),
                "directives": directives,
                "inflammation": res,
                "seq": self._seq,
            }
        self._dispatch_receptors(payload)
        return res

    def clear_inflammation(self, locus: str) -> bool:
        """Clear localized inflammation at a locus after resolution."""
        key = str(locus).strip().replace("\\", "/")
        with self._lock:
            existed = self._inflamed_loci.pop(key, None) is not None
            if existed:
                peak = max((v["intensity"] for v in self._inflamed_loci.values()), default=0.0)
                self._levels["cytokine"] = _clamp01(max(HOMEOSTASIS_SETPOINTS["cytokine"], peak * 0.85))
                self._sync_to_mmap_locked()
            return existed

    def register_receptor(self, name: str, fn: Callable[[dict[str, Any]], Any]) -> None:
        """Register an open physiological receptor callback."""
        key = str(name).strip()
        if not key or not callable(fn):
            raise ValueError("Receptor requires non-empty name and callable fn")
        with self._lock:
            self._receptors[key] = fn

    def unregister_receptor(self, name: str) -> bool:
        """Remove a previously registered receptor callback."""
        with self._lock:
            return self._receptors.pop(str(name).strip(), None) is not None

    def _derive_directives_locked(self) -> dict[str, Any]:
        adr = self._levels["adrenaline"]
        cor = self._levels["cortisol"]
        dop = self._levels["dopamine"]
        mel = self._levels["melatonin"]
        cyt = self._levels["cytokine"]

        cad_vip = bool(adr >= 0.55 or (adr >= 0.42 and cor < 0.75))
        # Cooperative advisory backoff for CHIMERA background queues only (Law 2 compliant)
        bg_throttle = round(min(0.90, max(0.0, 0.65 * adr + 0.35 * cor - 0.15)), 4)
        sleep_eligible = bool(mel >= 0.55 and adr < 0.35 and cor < 0.45 and cyt < 0.45)

        sandbox_apps = sorted(
            app_id
            for app_id, info in self._trust_ledger.items()
            if info["trust"] < 0.40
        )
        active_loci = {
            locus: round(info["intensity"], 4)
            for locus, info in sorted(self._inflamed_loci.items())
            if info["intensity"] >= 0.15
        }

        if cor >= 0.70 or cyt >= 0.70:
            stress_mode = "strained"
        elif adr >= 0.65:
            stress_mode = "alert"
        elif sleep_eligible:
            stress_mode = "rest"
        elif dop >= 0.60 and cor < 0.35:
            stress_mode = "focused"
        else:
            stress_mode = "calm"

        exploration_bias = round(_clamp01(0.50 + 0.45 * (dop - 0.50) - 0.40 * cor), 4)

        return {
            "cad_vip": cad_vip,
            "background_throttle_ratio": bg_throttle,
            "sleep_eligible": sleep_eligible,
            "sandbox_required_apps": sandbox_apps,
            "inflamed_loci": active_loci,
            "stress_mode": stress_mode,
            "exploration_bias": exploration_bias,
            "law2_advisory_only": True,
        }

    def derive_directives(self) -> dict[str, Any]:
        """Compute advisory physiological posture for internal organs and external apps."""
        with self._lock:
            return self._derive_directives_locked()

    def snapshot(self) -> dict[str, Any]:
        """Return full JSON-serializable state of the Endocrine system."""
        with self._lock:
            cur_levels = {k: round(self._levels[k], 6) for k in HORMONE_NAMES}
            return {
                "hormones": cur_levels,
                "directives": self._derive_directives_locked(),
                "seq": self._seq,
                "mmap_active": self._mm is not None,
                "ephemeral": self.ephemeral,
                "ring_path": str(self.ring_path),
                "mmap_offset": ENDO_OFFSET,
                "mmap_bytes": ENDO_BYTES,
                "wire_12b_hex": encode_wire_12b(cur_levels).hex(),
                "trust_ledger": {k: dict(v) for k, v in self._trust_ledger.items()},
                "inflamed_loci": {k: dict(v) for k, v in self._inflamed_loci.items()},
                "receptors": sorted(self._receptors.keys()),
                "recent_events": list(self._events)[-16:],
                "updated_ts": round(self._last_update_ts, 3),
            }

    def close(self) -> None:
        """Close open mmap and file handles cleanly."""
        with self._lock:
            if self._mm is not None:
                try:
                    self._mm.close()
                except Exception:
                    pass
                self._mm = None
            if self._fh is not None:
                try:
                    self._fh.close()
                except Exception:
                    pass
                self._fh = None

    def __enter__(self) -> "EndocrineSystem":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()
