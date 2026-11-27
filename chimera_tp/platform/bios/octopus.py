"""CHIMERA-OCTOPUS — Idea #5: Autonomous Peripheral Reflex Ganglia.

Decentralized peripheral nervous system allowing external hooks, sockets, and
peer nodes (`svhome`) to execute < 1 ms local survival reflexes EVEN WHEN the
central Python daemon (`:9780`) is offline or restarting.

Components:
  1. BinaryReflexTable     -- Compact (< 16 KB, 12 KiB max) file/mmap-backed
                              binary reflex cache storing antibodies, failover
                              endpoints, and the 6-hormone snapshot for zero-HTTP
                              microsecond lookups across processes.
  2. SocketGanglion        -- Manages `:12500` / Egress slot health, local SSE
                              keepalive cadence, and autonomous failover routing
                              to `svhome` peer slot (never kills OS processes).
  3. HookGanglion          -- < 1 ms local pre-tool / pre-write safety & antibody
                              evaluator reading directly from BinaryReflexTable.
  4. PeerSurvivalGanglion  -- Autonomous `svhome` island-mode coordinator enforcing
                              Law-3 protected budget fuses and buffering local
                              events in an HLC-stamped CRDT log on link loss.
  5. SynapticReconciler    -- Deterministic HLC + BLAKE2s Merkle-CRDT merger
                              yielding identical root hashes regardless of
                              merge order (commutative, associative, idempotent).
  6. OctopusNervousSystem  -- Unified zero-weight facade.

Compliance with CHIMERA-ONE Doctrine (Laws 1-7):
  - 100% Python stdlib, Zero-NumPy, lazy-loaded, < 2 MiB RAM
  - Law 2: Pure advisory/reflex guards; zero OS kernel interference
  - Law 3: Hard fuses protecting `svhome` (RAM >= 2.5 GiB, load <= 1.8, < 70C, disk >= 15 GB)
"""
from __future__ import annotations

import hashlib
import json
import mmap
import os
import re
import socket
import struct
import threading
import time
import zlib
from pathlib import Path
from typing import Any


def _chimera_home() -> Path:
    return Path(os.environ.get("CHIMERA_HOME") or (Path.home() / ".chimera"))


def _canonical_bytes(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


# ---------------------------------------------------------------------------
# 1. BinaryReflexTable (< 16 KB File / mmap-Backed Reflex Cache)
# ---------------------------------------------------------------------------

HORMONE_ORDER = ("adrenaline", "cortisol", "dopamine", "melatonin", "cytokine", "oxytocin")

_SEVERITY_TO_CODE = {"low": 1, "medium": 2, "high": 3, "critical": 4}
_CODE_TO_SEVERITY = {v: k for k, v in _SEVERITY_TO_CODE.items()}

_ACTION_TO_CODE = {"allow": 0, "warn": 1, "sandbox": 2, "block": 3, "reroute": 4}
_CODE_TO_ACTION = {v: k for k, v in _ACTION_TO_CODE.items()}

_ROLE_TO_CODE = {"primary": 0, "peer_svhome": 1, "fallback": 2, "daemon": 3}
_CODE_TO_ROLE = {v: k for k, v in _ROLE_TO_CODE.items()}

_STATE_TO_CODE = {"healthy": 0, "degraded": 1, "down": 2}
_CODE_TO_STATE = {v: k for k, v in _STATE_TO_CODE.items()}


class BinaryReflexTable:
    """Compact 12 KiB (< 16 KB) binary reflex table readable via mmap in microseconds.

    Binary Layout (little-endian, 64-byte header + compact packed body):
      0..3   : magic = b"OCTR"
      4..5   : version (u16 = 1)
      6..7   : flags (u16: bit0=daemon_online, bit1=island_mode, bit2=safe_brake)
      8..15  : generation (u64)
      16..23 : updated_ts_ms (u64)
      24..47 : 6x float32 hormones (adrenaline, cortisol, dopamine, melatonin, cytokine, oxytocin)
      48..49 : antibody_count (u16)
      50..51 : endpoint_count (u16)
      52..55 : payload_len (u32)
      56..59 : crc32 (u32 over header[0:56] + payload)
      60..63 : reserved (u32 = 0)
      64..   : packed antibody records followed by packed endpoint records
    """

    MAGIC = b"OCTR"
    VERSION = 1
    HEADER_FMT = "<4sHHQQ6fHHIII"
    HEADER_SIZE = struct.calcsize(HEADER_FMT)  # 64 bytes
    MAX_BYTES = 12288  # 12 KiB, strictly < 16 KB (16384 B)

    FLAG_DAEMON_ONLINE = 1 << 0
    FLAG_ISLAND_MODE = 1 << 1
    FLAG_SAFE_BRAKE = 1 << 2

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        ephemeral: bool = False,
        read_only: bool = False,
    ) -> None:
        self.ephemeral = bool(ephemeral or path is None)
        self.read_only = bool(read_only)
        self.path: Path | None = None if self.ephemeral else Path(path)  # type: ignore[arg-type]
        self._lock = threading.RLock()
        self._buf: bytearray | None = None
        self._fh: Any = None
        self._mm: mmap.mmap | None = None
        self._cached_gen: int = -1
        self._cached_crc: int = -1
        self._cached_snapshot: dict[str, Any] | None = None

        if self.ephemeral:
            self._buf = bytearray(self.MAX_BYTES)
            self._write_raw_frame(
                antibodies=[],
                endpoints=[],
                hormones={h: 0.0 for h in HORMONE_ORDER},
                flags=self.FLAG_DAEMON_ONLINE,
                generation=1,
            )
        else:
            assert self.path is not None
            self._open_mmap()

    def _open_mmap(self) -> None:
        assert self.path is not None
        if self.read_only:
            self._fh = open(self.path, "rb")
            self._mm = mmap.mmap(self._fh.fileno(), 0, access=mmap.ACCESS_READ)
            return

        self.path.parent.mkdir(parents=True, exist_ok=True)
        need_init = (not self.path.exists()) or (self.path.stat().st_size < self.MAX_BYTES)
        mode = "r+b" if self.path.exists() else "w+b"
        self._fh = open(self.path, mode)
        if need_init:
            self._fh.seek(0)
            self._fh.write(b"\x00" * self.MAX_BYTES)
            self._fh.flush()
        self._mm = mmap.mmap(self._fh.fileno(), self.MAX_BYTES, access=mmap.ACCESS_WRITE)
        if bytes(self._mm[:4]) != self.MAGIC:
            self._write_raw_frame(
                antibodies=[],
                endpoints=[],
                hormones={h: 0.0 for h in HORMONE_ORDER},
                flags=self.FLAG_DAEMON_ONLINE,
                generation=1,
            )

    def _backing_slice(self, start: int, end: int) -> bytes:
        if self._mm is not None:
            return bytes(self._mm[start:end])
        assert self._buf is not None
        return bytes(self._buf[start:end])

    def _write_raw_frame(
        self,
        *,
        antibodies: list[dict[str, Any]],
        endpoints: list[dict[str, Any]],
        hormones: dict[str, float],
        flags: int,
        generation: int,
    ) -> dict[str, Any]:
        payload = bytearray()
        ab_written = 0
        ep_written = 0
        max_payload = self.MAX_BYTES - self.HEADER_SIZE

        for ab in antibodies:
            sig_b = str(ab.get("pattern") or ab.get("error_sig") or "")[:180].encode("utf-8", errors="ignore")
            hint_b = str(ab.get("fix_hint") or "")[:200].encode("utf-8", errors="ignore")
            if not sig_b:
                continue
            sev = _SEVERITY_TO_CODE.get(str(ab.get("severity", "medium")).lower(), 2)
            act = _ACTION_TO_CODE.get(str(ab.get("action", "warn")).lower(), 1)
            rec = struct.pack("<BBHH", sev, act, len(sig_b), len(hint_b)) + sig_b + hint_b
            if len(payload) + len(rec) > max_payload:
                break
            payload.extend(rec)
            ab_written += 1

        for ep in endpoints:
            host_b = str(ep.get("host") or "127.0.0.1")[:96].encode("utf-8", errors="ignore")
            name_b = str(ep.get("name") or ep.get("path") or "slot")[:64].encode("utf-8", errors="ignore")
            role = _ROLE_TO_CODE.get(str(ep.get("role", "primary")).lower(), 0)
            state = _STATE_TO_CODE.get(str(ep.get("state", "healthy")).lower(), 0)
            port = max(0, min(65535, int(ep.get("port", 0))))
            rec = struct.pack("<BBHHH", role, state, port, len(host_b), len(name_b)) + host_b + name_b
            if len(payload) + len(rec) > max_payload:
                break
            payload.extend(rec)
            ep_written += 1

        h_vals = tuple(float(hormones.get(name, 0.0)) for name in HORMONE_ORDER)
        now_ms = int(time.time() * 1000)
        hdr_wo_crc = struct.pack(
            "<4sHHQQ6fHHI",
            self.MAGIC,
            self.VERSION,
            int(flags) & 0xFFFF,
            int(generation),
            now_ms,
            *h_vals,
            ab_written,
            ep_written,
            len(payload),
        )
        crc = zlib.crc32(hdr_wo_crc + bytes(payload)) & 0xFFFFFFFF
        full_hdr = hdr_wo_crc + struct.pack("<II", crc, 0)
        frame = full_hdr + bytes(payload)
        assert len(frame) <= self.MAX_BYTES

        if self._mm is not None:
            self._mm[0 : len(frame)] = frame
            if len(frame) < self.MAX_BYTES:
                # Zero trailing slack bytes for clean determinism
                self._mm[len(frame) : self.MAX_BYTES] = b"\x00" * (self.MAX_BYTES - len(frame))
        else:
            assert self._buf is not None
            self._buf[0 : len(frame)] = frame
            if len(frame) < self.MAX_BYTES:
                self._buf[len(frame) : self.MAX_BYTES] = b"\x00" * (self.MAX_BYTES - len(frame))

        self._cached_gen = -1
        self._cached_snapshot = None
        return {
            "ok": True,
            "generation": int(generation),
            "used_bytes": len(frame),
            "max_bytes": self.MAX_BYTES,
            "antibody_count": ab_written,
            "endpoint_count": ep_written,
            "crc32": crc,
        }

    def sync(
        self,
        *,
        antibodies: list[dict[str, Any]] | None = None,
        endpoints: list[dict[str, Any]] | None = None,
        hormones: dict[str, float] | None = None,
        flags: int | None = None,
    ) -> dict[str, Any]:
        """Update binary reflex table while preserving omitted sections."""
        if self.read_only:
            raise PermissionError("BinaryReflexTable opened read-only")
        with self._lock:
            cur = self.read_snapshot()
            next_gen = int(cur.get("generation", 0)) + 1
            return self._write_raw_frame(
                antibodies=cur["antibodies"] if antibodies is None else list(antibodies),
                endpoints=cur["endpoints"] if endpoints is None else list(endpoints),
                hormones=cur["hormones"] if hormones is None else dict(hormones),
                flags=cur["flags"] if flags is None else int(flags),
                generation=next_gen,
            )

    def read_snapshot(self) -> dict[str, Any]:
        """Zero-HTTP binary decode from mmap/memory with generation cache."""
        with self._lock:
            hdr_bytes = self._backing_slice(0, self.HEADER_SIZE)
            if len(hdr_bytes) < self.HEADER_SIZE:
                raise ValueError("Truncated BinaryReflexTable header")
            unpacked = struct.unpack(self.HEADER_FMT, hdr_bytes)
            magic, ver, flags, gen, updated_ms = unpacked[0:5]
            h_vals = unpacked[5:11]
            ab_cnt, ep_cnt, payload_len, crc, _res = unpacked[11:16]

            if magic != self.MAGIC:
                raise ValueError(f"Invalid BinaryReflexTable magic: {magic!r}")
            if payload_len > self.MAX_BYTES - self.HEADER_SIZE:
                raise ValueError(f"Invalid payload_len: {payload_len}")

            if self._cached_snapshot is not None and gen == self._cached_gen and crc == self._cached_crc:
                return self._cached_snapshot

            payload = self._backing_slice(self.HEADER_SIZE, self.HEADER_SIZE + payload_len)
            calc_crc = zlib.crc32(hdr_bytes[:56] + payload) & 0xFFFFFFFF
            if calc_crc != crc:
                raise ValueError(f"BinaryReflexTable CRC32 mismatch: {calc_crc:#x} != {crc:#x}")

            pos = 0
            antibodies: list[dict[str, Any]] = []
            for _ in range(ab_cnt):
                sev_c, act_c, sig_len, hint_len = struct.unpack_from("<BBHH", payload, pos)
                pos += 6
                sig = payload[pos : pos + sig_len].decode("utf-8", errors="replace")
                pos += sig_len
                hint = payload[pos : pos + hint_len].decode("utf-8", errors="replace")
                pos += hint_len
                antibodies.append(
                    {
                        "severity": _CODE_TO_SEVERITY.get(sev_c, "medium"),
                        "action": _CODE_TO_ACTION.get(act_c, "warn"),
                        "pattern": sig,
                        "fix_hint": hint,
                    }
                )

            endpoints: list[dict[str, Any]] = []
            for _ in range(ep_cnt):
                role_c, state_c, port, host_len, name_len = struct.unpack_from("<BBHHH", payload, pos)
                pos += 8
                host = payload[pos : pos + host_len].decode("utf-8", errors="replace")
                pos += host_len
                name = payload[pos : pos + name_len].decode("utf-8", errors="replace")
                pos += name_len
                endpoints.append(
                    {
                        "role": _CODE_TO_ROLE.get(role_c, "primary"),
                        "state": _CODE_TO_STATE.get(state_c, "healthy"),
                        "port": int(port),
                        "host": host,
                        "name": name,
                    }
                )

            snap = {
                "version": int(ver),
                "flags": int(flags),
                "daemon_online": bool(flags & self.FLAG_DAEMON_ONLINE),
                "island_mode": bool(flags & self.FLAG_ISLAND_MODE),
                "safe_brake": bool(flags & self.FLAG_SAFE_BRAKE),
                "generation": int(gen),
                "updated_ts_ms": int(updated_ms),
                "used_bytes": self.HEADER_SIZE + int(payload_len),
                "max_bytes": self.MAX_BYTES,
                "hormones": {name: round(float(val), 4) for name, val in zip(HORMONE_ORDER, h_vals)},
                "antibodies": antibodies,
                "endpoints": endpoints,
            }
            self._cached_gen = int(gen)
            self._cached_crc = int(crc)
            self._cached_snapshot = snap
            return snap

    def match_antibody(self, text: str) -> dict[str, Any] | None:
        """Fast < 1 ms offline antibody pattern match against mmap reflex table."""
        snap = self.read_snapshot()
        hay = text.lower()
        for ab in snap["antibodies"]:
            pat = str(ab.get("pattern") or "")
            if not pat:
                continue
            if pat.lower() in hay:
                return dict(ab)
        return None

    def get_active_endpoint(
        self,
        role_preference: tuple[str, ...] = ("primary", "peer_svhome", "fallback"),
    ) -> dict[str, Any] | None:
        snap = self.read_snapshot()
        eps = snap["endpoints"]
        for role in role_preference:
            for ep in eps:
                if ep["role"] == role and ep["state"] == "healthy":
                    return dict(ep)
        for role in role_preference:
            for ep in eps:
                if ep["role"] == role and ep["state"] == "degraded":
                    return dict(ep)
        return None

    def byte_size(self) -> int:
        if not self.ephemeral and self.path is not None and self.path.exists():
            return int(self.path.stat().st_size)
        return self.MAX_BYTES

    def close(self) -> None:
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

    def __enter__(self) -> "BinaryReflexTable":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# 2. SocketGanglion (Autonomous :12500 / Egress Failover & SSE Keepalive)
# ---------------------------------------------------------------------------

class SocketGanglion:
    """Autonomous socket health, SSE keepalive cadence, and failover state-machine."""

    def __init__(
        self,
        reflex_table: BinaryReflexTable | None = None,
        *,
        fail_threshold: int = 2,
        keepalive_interval_s: float = 15.0,
    ) -> None:
        self._table = reflex_table
        self._fail_threshold = max(1, int(fail_threshold))
        self._keepalive_interval_s = max(1.0, float(keepalive_interval_s))
        self._lock = threading.RLock()
        self._last_keepalive_ts = 0.0
        self._keepalive_seq = 0
        self._slots: dict[str, dict[str, Any]] = {
            "immortal_local": {
                "name": "immortal_local",
                "host": "127.0.0.1",
                "port": 12500,
                "role": "primary",
                "state": "healthy",
                "consecutive_failures": 0,
                "latency_ms": 0.0,
                "last_probe_ts": 0.0,
                "last_error": "",
            },
            "egress_local": {
                "name": "egress_local",
                "host": "127.0.0.1",
                "port": 9781,
                "role": "primary",
                "state": "healthy",
                "consecutive_failures": 0,
                "latency_ms": 0.0,
                "last_probe_ts": 0.0,
                "last_error": "",
            },
            "svhome_peer": {
                "name": "svhome_peer",
                "host": "svhome.local",
                "port": 9780,
                "role": "peer_svhome",
                "state": "healthy",
                "consecutive_failures": 0,
                "latency_ms": 0.0,
                "last_probe_ts": 0.0,
                "last_error": "",
            },
        }
        self._sync_table()

    def _sync_table(self) -> None:
        if self._table is None or self._table.read_only:
            return
        eps = [
            {
                "name": s["name"],
                "host": s["host"],
                "port": s["port"],
                "role": s["role"],
                "state": s["state"],
            }
            for s in self._slots.values()
        ]
        self._table.sync(endpoints=eps)

    def register_slot(
        self,
        name: str,
        host: str,
        port: int,
        role: str = "primary",
        state: str = "healthy",
    ) -> dict[str, Any]:
        with self._lock:
            self._slots[name] = {
                "name": name,
                "host": str(host),
                "port": int(port),
                "role": str(role),
                "state": str(state),
                "consecutive_failures": 0,
                "latency_ms": 0.0,
                "last_probe_ts": time.time(),
                "last_error": "",
            }
            self._sync_table()
            return dict(self._slots[name])

    def record_probe(
        self,
        name: str,
        ok: bool,
        *,
        latency_ms: float = 0.0,
        error: str = "",
        now_ts: float | None = None,
    ) -> dict[str, Any]:
        ts = time.time() if now_ts is None else float(now_ts)
        with self._lock:
            if name not in self._slots:
                raise KeyError(f"Unknown socket slot: {name}")
            slot = self._slots[name]
            slot["last_probe_ts"] = ts
            slot["latency_ms"] = round(float(latency_ms), 3)
            if ok:
                slot["consecutive_failures"] = 0
                slot["state"] = "healthy"
                slot["last_error"] = ""
            else:
                slot["consecutive_failures"] = int(slot["consecutive_failures"]) + 1
                slot["last_error"] = str(error)[:120]
                slot["state"] = "down" if slot["consecutive_failures"] >= self._fail_threshold else "degraded"
            self._sync_table()
            return dict(slot)

    def probe_tcp(self, name: str, timeout_s: float = 0.05) -> dict[str, Any]:
        """Non-destructive TCP connect health probe (loopback / configured peer)."""
        with self._lock:
            if name not in self._slots:
                raise KeyError(f"Unknown socket slot: {name}")
            host = str(self._slots[name]["host"])
            port = int(self._slots[name]["port"])
        t0 = time.perf_counter()
        try:
            with socket.create_connection((host, port), timeout=max(0.01, float(timeout_s))):
                pass
            return self.record_probe(name, True, latency_ms=(time.perf_counter() - t0) * 1000.0)
        except OSError as exc:
            return self.record_probe(
                name,
                False,
                latency_ms=(time.perf_counter() - t0) * 1000.0,
                error=type(exc).__name__,
            )

    def select_route(self, preferred_slot: str = "immortal_local") -> dict[str, Any]:
        """Autonomous failover routing: local primary -> healthy primary -> svhome peer."""
        with self._lock:
            pref = self._slots.get(preferred_slot)
            if pref and pref["state"] == "healthy":
                return {
                    "ok": True,
                    "selected": pref["name"],
                    "host": pref["host"],
                    "port": pref["port"],
                    "role": pref["role"],
                    "failover_active": False,
                }
            # Autonomous failover to healthy peer_svhome or fallback
            for role in ("peer_svhome", "fallback", "primary"):
                for s in self._slots.values():
                    if s["name"] == preferred_slot:
                        continue
                    if s["role"] == role and s["state"] == "healthy":
                        return {
                            "ok": True,
                            "selected": s["name"],
                            "host": s["host"],
                            "port": s["port"],
                            "role": s["role"],
                            "failover_active": True,
                            "reason": f"{preferred_slot}_state={pref['state'] if pref else 'missing'}",
                        }
            # Last resort degraded slot
            for s in self._slots.values():
                if s["state"] == "degraded":
                    return {
                        "ok": True,
                        "selected": s["name"],
                        "host": s["host"],
                        "port": s["port"],
                        "role": s["role"],
                        "failover_active": True,
                        "degraded": True,
                    }
            return {"ok": False, "selected": None, "failover_active": True, "reason": "all_slots_down"}

    def keepalive_tick(self, now_ts: float | None = None) -> dict[str, Any]:
        """Check whether an SSE keepalive comment frame is due."""
        ts = time.time() if now_ts is None else float(now_ts)
        with self._lock:
            due = (ts - self._last_keepalive_ts) >= self._keepalive_interval_s
            if due:
                self._last_keepalive_ts = ts
                self._keepalive_seq += 1
                frame = f": keepalive seq={self._keepalive_seq} ts={int(ts)}\n\n"
            else:
                frame = ""
            return {
                "due": due,
                "seq": self._keepalive_seq,
                "interval_s": self._keepalive_interval_s,
                "frame": frame,
            }

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "slots": {k: dict(v) for k, v in self._slots.items()},
                "active_route": self.select_route(),
                "keepalive_seq": self._keepalive_seq,
                "keepalive_interval_s": self._keepalive_interval_s,
            }


# ---------------------------------------------------------------------------
# 3. HookGanglion (< 1 ms Local Offline Pre-Tool / Pre-Write Reflex)
# ---------------------------------------------------------------------------

_SPINAL_BLOCK_RULES: tuple[tuple[str, re.Pattern[str], str], ...] = (
    (
        "spinal:secret_raw_leak",
        re.compile(r"(?:ghp_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9_-]{24,}|AIza[0-9A-Za-z_-]{24,})"),
        "Raw credential token detected; route through diskless secrets or redact before egress.",
    ),
    (
        "spinal:destructive_root_wipe",
        re.compile(r"(?:rm\s+-rf\s+/(?:\s|$)|format\s+c:|rd\s+/s\s+/q\s+c:\\)", re.IGNORECASE),
        "Destructive filesystem root wipe blocked by peripheral spinal reflex.",
    ),
)


class HookGanglion:
    """< 1 ms local pre-tool/pre-write safety & antibody reflex evaluator.

    Reads directly from `BinaryReflexTable` (mmap/memory) with zero HTTP calls,
    continuing autonomous protection even when `:9780` daemon is offline.
    """

    def __init__(self, reflex_table: BinaryReflexTable) -> None:
        self._table = reflex_table
        self._eval_count = 0
        self._blocks = 0
        self._warns = 0
        self._lock = threading.RLock()

    def evaluate(
        self,
        tool_name: str,
        payload: str | dict[str, Any],
        *,
        target_path: str = "",
        daemon_online: bool | None = None,
    ) -> dict[str, Any]:
        t0 = time.perf_counter()
        snap = self._table.read_snapshot()
        online = snap["daemon_online"] if daemon_online is None else bool(daemon_online)
        text = payload if isinstance(payload, str) else json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        composite = f"{tool_name} {target_path} {text}"

        decision = "allow"
        matched_rule: str | None = None
        fix_hint = ""
        severity = "none"

        # 1. Hardcoded spinal survival reflexes (always live)
        for rule_id, rx, hint in _SPINAL_BLOCK_RULES:
            if rx.search(composite):
                decision = "block"
                matched_rule = rule_id
                fix_hint = hint
                severity = "critical"
                break

        # 2. Dynamic binary antibody table match (synced from Parasite / Immune)
        if decision == "allow":
            ab = self._table.match_antibody(composite)
            if ab is not None:
                decision = str(ab.get("action") or "warn")
                matched_rule = f"antibody:{ab.get('pattern', '')}"
                fix_hint = str(ab.get("fix_hint") or "")
                severity = str(ab.get("severity") or "medium")

        # 3. Endocrine stress modulation from 24-byte hormone snapshot
        hormones = snap["hormones"]
        if decision == "allow" and (snap["safe_brake"] or hormones.get("cytokine", 0.0) >= 0.85):
            decision = "sandbox"
            matched_rule = "hormone:high_cytokine_inflammation"
            fix_hint = "High localized inflammation; execute inside isolated ghost-bubble sandbox."
            severity = "medium"

        elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 4)
        with self._lock:
            self._eval_count += 1
            if decision == "block":
                self._blocks += 1
            elif decision in ("warn", "sandbox"):
                self._warns += 1

        return {
            "ok": True,
            "decision": decision,
            "allowed": decision in ("allow", "warn"),
            "matched_rule": matched_rule,
            "severity": severity,
            "fix_hint": fix_hint,
            "offline_autonomous": not online,
            "table_generation": snap["generation"],
            "hormone_context": hormones,
            "elapsed_ms": elapsed_ms,
        }

    def evaluate_pre_write(
        self,
        rel_path: str,
        content_preview: str,
        *,
        daemon_online: bool | None = None,
    ) -> dict[str, Any]:
        return self.evaluate(
            "pre_write",
            content_preview,
            target_path=rel_path,
            daemon_online=daemon_online,
        )

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "evaluations": self._eval_count,
                "blocks": self._blocks,
                "warns": self._warns,
                "table_bytes": self._table.byte_size(),
                "table_generation": self._table.read_snapshot()["generation"],
            }


# ---------------------------------------------------------------------------
# 4. SynapticReconciler (Deterministic HLC + BLAKE2s Merkle-CRDT Merger)
# ---------------------------------------------------------------------------

def _norm_hlc(hlc: Any, fallback_node: str = "node") -> tuple[int, int, str]:
    if isinstance(hlc, (list, tuple)) and len(hlc) >= 3:
        return (int(hlc[0]), int(hlc[1]), str(hlc[2]))
    return (int(time.time() * 1000), 0, str(fallback_node))


def _canonical_event(raw: dict[str, Any]) -> dict[str, Any]:
    node = str(raw.get("node") or raw.get("node_id") or "unknown")
    hlc = _norm_hlc(raw.get("hlc"), fallback_node=node)
    kind = str(raw.get("kind") or "event")
    key = raw.get("key")
    payload = raw.get("payload") if isinstance(raw.get("payload"), dict) else {"value": raw.get("payload")}
    ev_id = str(raw.get("event_id") or "")
    if not ev_id:
        digest_src = _canonical_bytes({"hlc": list(hlc), "node": node, "kind": kind, "key": key, "payload": payload})
        ev_id = hashlib.blake2s(digest_src, digest_size=12).hexdigest()
    return {
        "event_id": ev_id,
        "hlc": [hlc[0], hlc[1], hlc[2]],
        "node": node,
        "kind": kind,
        "key": None if key is None else str(key),
        "payload": payload,
    }


def _event_sort_key(ev: dict[str, Any]) -> tuple[int, int, str, str]:
    h = ev["hlc"]
    return (int(h[0]), int(h[1]), str(h[2]), str(ev["event_id"]))


class SynapticReconciler:
    """Deterministic HLC + BLAKE2s Merkle-CRDT state merger.

    Properties:
      - Zero data loss: causal set-union of all unique events from both partitions.
      - Order-independent: `reconcile(A, B)` and `reconcile(B, A)` yield the exact
        same BLAKE2s `root_hash`, canonically sorted `merged_events`, and `resolved_kv`.
      - Associative & Idempotent: safe for repeated multi-node sync bursts.
    """

    @staticmethod
    def make_event(
        node_id: str,
        kind: str,
        payload: dict[str, Any],
        *,
        hlc: tuple[int, int, str] | list[Any] | None = None,
        key: str | None = None,
        event_id: str | None = None,
    ) -> dict[str, Any]:
        return _canonical_event(
            {
                "event_id": event_id or "",
                "hlc": list(_norm_hlc(hlc, fallback_node=node_id)),
                "node": node_id,
                "kind": kind,
                "key": key,
                "payload": payload,
            }
        )

    @staticmethod
    def compute_merkle_root(events: list[dict[str, Any]]) -> str:
        """Compute deterministic 128-bit BLAKE2s Merkle root over canonically sorted events."""
        if not events:
            return hashlib.blake2s(b"chimera.octopus.merkle.empty.v1", digest_size=16).hexdigest()

        # Deduplicate by event_id and sort by total HLC order
        unique: dict[str, dict[str, Any]] = {}
        for ev in events:
            c = _canonical_event(ev)
            unique[c["event_id"]] = c
        ordered = sorted(unique.values(), key=_event_sort_key)

        level = [
            hashlib.blake2s(b"\x00" + _canonical_bytes(ev), digest_size=16).digest()
            for ev in ordered
        ]
        while len(level) > 1:
            nxt: list[bytes] = []
            for i in range(0, len(level), 2):
                left = level[i]
                right = level[i + 1] if (i + 1) < len(level) else left
                nxt.append(hashlib.blake2s(b"\x01" + left + right, digest_size=16).digest())
            level = nxt
        return level[0].hex()

    def reconcile(
        self,
        local_events: list[dict[str, Any]],
        peer_events: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Deterministically merge two diverged event logs into a single converged CRDT state."""
        t0 = time.perf_counter()
        local_map: dict[str, dict[str, Any]] = {}
        for ev in local_events:
            c = _canonical_event(ev)
            local_map[c["event_id"]] = c

        peer_map: dict[str, dict[str, Any]] = {}
        for ev in peer_events:
            c = _canonical_event(ev)
            peer_map[c["event_id"]] = c

        local_ids = set(local_map.keys())
        peer_ids = set(peer_map.keys())
        common_ids = local_ids & peer_ids
        local_only = local_ids - peer_ids
        peer_only = peer_ids - local_ids

        merged_map: dict[str, dict[str, Any]] = {}
        merged_map.update(local_map)
        merged_map.update(peer_map)
        merged_events = sorted(merged_map.values(), key=_event_sort_key)

        # Deterministic LWW-Element-Map resolution for keyed updates using total HLC order
        resolved_kv: dict[str, Any] = {}
        key_versions: dict[str, int] = {}
        for ev in merged_events:
            k = ev.get("key")
            if k is not None:
                key_versions[k] = key_versions.get(k, 0) + 1
                resolved_kv[k] = {
                    "payload": ev["payload"],
                    "hlc": ev["hlc"],
                    "node": ev["node"],
                    "event_id": ev["event_id"],
                }

        conflicts_resolved = sum(1 for cnt in key_versions.values() if cnt > 1)
        root_hash = self.compute_merkle_root(merged_events)
        max_hlc = merged_events[-1]["hlc"] if merged_events else [0, 0, ""]
        elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 4)

        return {
            "ok": True,
            "root_hash": root_hash,
            "total_events": len(merged_events),
            "local_only_count": len(local_only),
            "peer_only_count": len(peer_only),
            "common_count": len(common_ids),
            "conflicts_resolved": conflicts_resolved,
            "merged_events": merged_events,
            "resolved_kv": resolved_kv,
            "max_hlc": max_hlc,
            "elapsed_ms": elapsed_ms,
        }


# ---------------------------------------------------------------------------
# 5. PeerSurvivalGanglion (Autonomous svhome Island-Mode + HLC CRDT Log)
# ---------------------------------------------------------------------------

class PeerSurvivalGanglion:
    """Autonomous `svhome` island-mode coordinator with Law-3 hard fuses and HLC CRDT buffer."""

    # Law-3 svhome hard protection limits (docs/UNIFICATION_DOCTRINE.md)
    MIN_FREE_RAM_GIB = 2.5
    MAX_LOAD1 = 1.8
    MAX_CPU_TEMP_C = 70.0
    MIN_FREE_DISK_GB = 15.0

    def __init__(
        self,
        node_name: str = "svhome",
        *,
        peer_name: str = "win-desktop",
        heartbeat_timeout_s: float = 30.0,
        reflex_table: BinaryReflexTable | None = None,
    ) -> None:
        self.node_name = str(node_name)
        self.peer_name = str(peer_name)
        self.heartbeat_timeout_s = max(1.0, float(heartbeat_timeout_s))
        self._table = reflex_table
        self._lock = threading.RLock()
        self._last_peer_hb_ts: float = time.time()
        self._last_peer_rtt_ms: float = 0.0
        self._island_mode: bool = False
        self._island_entered_ts: float | None = None
        # HLC state: (last_wall_ms, logical_counter)
        self._hlc_wall_ms: int = int(time.time() * 1000)
        self._hlc_logical: int = 0
        self._events: dict[str, dict[str, Any]] = {}

    def _tick_hlc(self, now_ts: float | None = None, remote_hlc: tuple[int, int, str] | None = None) -> tuple[int, int, str]:
        phys_ms = int((time.time() if now_ts is None else float(now_ts)) * 1000)
        if remote_hlc is not None:
            r_wall, r_log, _ = remote_hlc
            max_wall = max(phys_ms, self._hlc_wall_ms, r_wall)
            if max_wall == self._hlc_wall_ms == r_wall:
                self._hlc_logical = max(self._hlc_logical, r_log) + 1
            elif max_wall == self._hlc_wall_ms:
                self._hlc_logical += 1
            elif max_wall == r_wall:
                self._hlc_logical = r_log + 1
            else:
                self._hlc_logical = 0
            self._hlc_wall_ms = max_wall
        else:
            if phys_ms > self._hlc_wall_ms:
                self._hlc_wall_ms = phys_ms
                self._hlc_logical = 0
            else:
                self._hlc_logical += 1
        return (self._hlc_wall_ms, self._hlc_logical, self.node_name)

    def _update_table_flag(self) -> None:
        if self._table is None or self._table.read_only:
            return
        snap = self._table.read_snapshot()
        flags = int(snap["flags"])
        if self._island_mode:
            flags |= BinaryReflexTable.FLAG_ISLAND_MODE
        else:
            flags &= ~BinaryReflexTable.FLAG_ISLAND_MODE
        self._table.sync(flags=flags)

    def record_peer_heartbeat(
        self,
        peer_node: str | None = None,
        *,
        rtt_ms: float = 0.0,
        now_ts: float | None = None,
    ) -> dict[str, Any]:
        ts = time.time() if now_ts is None else float(now_ts)
        with self._lock:
            self._last_peer_hb_ts = ts
            self._last_peer_rtt_ms = round(float(rtt_ms), 3)
            was_island = self._island_mode
            self._island_mode = False
            self._island_entered_ts = None
            if was_island:
                self._update_table_flag()
                self.append_event(
                    "link_restored",
                    {"peer": peer_node or self.peer_name, "rtt_ms": self._last_peer_rtt_ms},
                    key=f"link:{peer_node or self.peer_name}",
                    now_ts=ts,
                )
            return {
                "ok": True,
                "peer": peer_node or self.peer_name,
                "island_mode": self._island_mode,
                "restored_from_island": was_island,
                "rtt_ms": self._last_peer_rtt_ms,
            }

    def check_link(self, now_ts: float | None = None) -> dict[str, Any]:
        """Evaluate peer link liveness and autonomously engage Law-3 island mode on loss."""
        ts = time.time() if now_ts is None else float(now_ts)
        with self._lock:
            age_s = max(0.0, ts - self._last_peer_hb_ts)
            lost = age_s > self.heartbeat_timeout_s
            if lost and not self._island_mode:
                self._island_mode = True
                self._island_entered_ts = ts
                self._update_table_flag()
                self.append_event(
                    "island_mode_entered",
                    {"peer": self.peer_name, "heartbeat_age_s": round(age_s, 2)},
                    key=f"link:{self.peer_name}",
                    now_ts=ts,
                )
            return {
                "node": self.node_name,
                "peer": self.peer_name,
                "island_mode": self._island_mode,
                "heartbeat_age_s": round(age_s, 3),
                "heartbeat_timeout_s": self.heartbeat_timeout_s,
                "budget_mode": "law3_island_protected" if self._island_mode else "symbiotic_connected",
                "buffered_events": len(self._events),
            }

    def admit_work(
        self,
        *,
        ram_free_gib: float,
        load1: float,
        cpu_temp_c: float,
        disk_free_gb: float,
        job_class: str = "light",
    ) -> dict[str, Any]:
        """Enforce Law-3 svhome hard fuses + island-mode self-preservation."""
        violations: list[str] = []
        if float(ram_free_gib) < self.MIN_FREE_RAM_GIB:
            violations.append(f"ram_free_gib<{self.MIN_FREE_RAM_GIB}")
        if float(load1) > self.MAX_LOAD1:
            violations.append(f"load1>{self.MAX_LOAD1}")
        if float(cpu_temp_c) >= self.MAX_CPU_TEMP_C:
            violations.append(f"cpu_temp_c>={self.MAX_CPU_TEMP_C}")
        if float(disk_free_gb) < self.MIN_FREE_DISK_GB:
            violations.append(f"disk_free_gb<{self.MIN_FREE_DISK_GB}")
        if self._island_mode and str(job_class).lower() in ("heavy", "build", "burst", "external"):
            violations.append("island_mode_rejects_heavy_job")
        return {
            "admitted": len(violations) == 0,
            "island_mode": self._island_mode,
            "job_class": job_class,
            "violations": violations,
            "fallback": "queue_or_colab" if violations else "execute_local",
        }

    def append_event(
        self,
        kind: str,
        payload: dict[str, Any],
        *,
        key: str | None = None,
        now_ts: float | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            hlc = self._tick_hlc(now_ts=now_ts)
            ev = SynapticReconciler.make_event(
                self.node_name,
                kind,
                payload,
                hlc=hlc,
                key=key,
            )
            self._events[ev["event_id"]] = ev
            return dict(ev)

    def absorb_merged_events(self, events: list[dict[str, Any]]) -> int:
        with self._lock:
            added = 0
            for raw in events:
                ev = _canonical_event(raw)
                if ev["event_id"] not in self._events:
                    self._events[ev["event_id"]] = ev
                    added += 1
                self._tick_hlc(remote_hlc=_norm_hlc(ev["hlc"], fallback_node=ev["node"]))
            return added

    def export_events(self) -> list[dict[str, Any]]:
        with self._lock:
            return sorted((dict(e) for e in self._events.values()), key=_event_sort_key)

    def status(self, now_ts: float | None = None) -> dict[str, Any]:
        link = self.check_link(now_ts=now_ts)
        with self._lock:
            link["merkle_root"] = SynapticReconciler.compute_merkle_root(list(self._events.values()))
            link["hlc"] = [self._hlc_wall_ms, self._hlc_logical, self.node_name]
            link["law3_limits"] = {
                "min_free_ram_gib": self.MIN_FREE_RAM_GIB,
                "max_load1": self.MAX_LOAD1,
                "max_cpu_temp_c": self.MAX_CPU_TEMP_C,
                "min_free_disk_gb": self.MIN_FREE_DISK_GB,
            }
        return link


# ---------------------------------------------------------------------------
# 6. OctopusNervousSystem (Unified Peripheral Ganglia Facade)
# ---------------------------------------------------------------------------

class OctopusNervousSystem:
    """Unified CHIMERA-OCTOPUS peripheral nervous ganglia facade."""

    def __init__(
        self,
        ops_dir: str | Path | None = None,
        *,
        node_name: str = "win-desktop",
        peer_name: str = "svhome",
        ephemeral: bool = False,
    ) -> None:
        self.ephemeral = bool(ephemeral)
        self.node_name = str(node_name)
        self.peer_name = str(peer_name)
        if self.ephemeral:
            self.ops_dir: Path | None = None
            table_path: Path | None = None
        else:
            self.ops_dir = Path(ops_dir) if ops_dir is not None else (_chimera_home() / "bios")
            self.ops_dir.mkdir(parents=True, exist_ok=True)
            table_path = self.ops_dir / "octopus_reflex.bin"

        self.reflex_table = BinaryReflexTable(table_path, ephemeral=self.ephemeral)
        self.socket_ganglion = SocketGanglion(self.reflex_table)
        self.hook_ganglion = HookGanglion(self.reflex_table)
        self.peer_ganglion = PeerSurvivalGanglion(
            node_name=self.node_name,
            peer_name=self.peer_name,
            reflex_table=self.reflex_table,
        )
        self.reconciler = SynapticReconciler()

    def sync_reflexes(
        self,
        *,
        antibodies: list[dict[str, Any]] | None = None,
        endpoints: list[dict[str, Any]] | None = None,
        hormones: dict[str, float] | None = None,
        daemon_online: bool = True,
    ) -> dict[str, Any]:
        snap = self.reflex_table.read_snapshot()
        flags = int(snap["flags"])
        if daemon_online:
            flags |= BinaryReflexTable.FLAG_DAEMON_ONLINE
        else:
            flags &= ~BinaryReflexTable.FLAG_DAEMON_ONLINE
        return self.reflex_table.sync(
            antibodies=antibodies,
            endpoints=endpoints,
            hormones=hormones,
            flags=flags,
        )

    def evaluate_hook(
        self,
        tool_name: str,
        payload: str | dict[str, Any],
        *,
        target_path: str = "",
        daemon_online: bool | None = None,
    ) -> dict[str, Any]:
        return self.hook_ganglion.evaluate(
            tool_name,
            payload,
            target_path=target_path,
            daemon_online=daemon_online,
        )

    def select_route(self, preferred_slot: str = "immortal_local") -> dict[str, Any]:
        return self.socket_ganglion.select_route(preferred_slot=preferred_slot)

    def reconcile(
        self,
        local_events: list[dict[str, Any]] | None = None,
        peer_events: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        loc = self.peer_ganglion.export_events() if local_events is None else list(local_events)
        rem = [] if peer_events is None else list(peer_events)
        result = self.reconciler.reconcile(loc, rem)
        if local_events is None and result["merged_events"]:
            self.peer_ganglion.absorb_merged_events(result["merged_events"])
        return result

    def status(self) -> dict[str, Any]:
        snap = self.reflex_table.read_snapshot()
        return {
            "organ": "CHIMERA-OCTOPUS",
            "node": self.node_name,
            "ephemeral": self.ephemeral,
            "reflex_table": {
                "generation": snap["generation"],
                "used_bytes": snap["used_bytes"],
                "max_bytes": snap["max_bytes"],
                "antibody_count": len(snap["antibodies"]),
                "endpoint_count": len(snap["endpoints"]),
                "daemon_online": snap["daemon_online"],
                "island_mode": snap["island_mode"],
            },
            "socket_ganglion": self.socket_ganglion.status(),
            "hook_ganglion": self.hook_ganglion.status(),
            "peer_ganglion": self.peer_ganglion.status(),
        }

    def close(self) -> None:
        self.reflex_table.close()

    def __enter__(self) -> "OctopusNervousSystem":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass
