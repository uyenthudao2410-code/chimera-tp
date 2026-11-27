"""CHIMERA-EVIDENCE: Thread-safe scoped measurement and verification ledger with TTL expiry."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import threading
import time
from typing import Any, Callable


_TRAFFIC = {
    "pulse.publish": ("pulse", "sequence"),
    "pulse.relay": ("pulse.relay", "sequence"),
    "egress.forward": ("egress_membrane", "http_status"),
    "agent.xray_batch": ("agent_hyper_bus", "operations"),
}


def _iso_utc(epoch: float) -> str:
    return datetime.fromtimestamp(float(epoch), tz=timezone.utc).isoformat()


class EvidenceLedger:
    """Thread-safe verification receipt store with per-capability TTL expiry and optional JSON persistence."""

    def __init__(
        self,
        ops_dir: Path | str | None = None,
        *,
        path: Path | str | None = None,
        persist: bool = True,
    ) -> None:
        if path is not None:
            self.path: Path | None = Path(path)
            self.ops_dir: Path | None = self.path.parent
        elif ops_dir is not None and persist:
            self.ops_dir = Path(ops_dir)
            self.path = self.ops_dir / "evidence_ledger.json"
        else:
            self.ops_dir = Path(ops_dir) if ops_dir is not None else None
            self.path = None
        self._lock = threading.Lock()
        self._entries: dict[str, dict[str, Any]] = {}
        self._session = os.urandom(16).hex()
        self._last_flush = -math.inf
        self._traffic_dirty = False
        if self.path is not None:
            self._load_locked()

    def _load_locked(self) -> None:
        if self.path is None or not self.path.is_file():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            raw_entries = data.get("entries") if isinstance(data, dict) else None
            if isinstance(raw_entries, dict):
                for cap, item in raw_entries.items():
                    if isinstance(cap, str) and isinstance(item, dict):
                        self._entries[cap] = dict(item)
        except Exception:
            pass

    def _save_locked(self) -> None:
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = json.dumps(
                {"version": 1, "entries": self._entries},
                indent=2,
                ensure_ascii=False,
            )
            tmp = self.path.with_name(f"{self.path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
            tmp.write_text(payload, encoding="utf-8")
            for attempt in range(4):
                try:
                    os.replace(tmp, self.path)
                    self._traffic_dirty = False
                    break
                except PermissionError:
                    if attempt == 3:
                        try:
                            tmp.unlink(missing_ok=True)
                        except OSError:
                            pass
                        break
                    time.sleep(0.01)
        except Exception:
            pass

    def record(
        self,
        capability: str,
        *,
        execution_node: str,
        fallback_mode: str | None = None,
        ttl_s: float = 300.0,
        verified: bool = True,
        violated: bool = False,
        metrics: dict[str, Any] | None = None,
        receipt_id: str | None = None,
        now_epoch: float | None = None,
    ) -> dict[str, Any]:
        """Record a verification observation for a capability with bounded TTL."""
        cap = str(capability or "").strip()
        if not cap:
            raise ValueError("capability must be a non-empty string")
        now_ts = float(now_epoch) if now_epoch is not None else time.time()
        ttl = max(0.0, float(ttl_s))
        exp_ts = now_ts + ttl
        last_iso = _iso_utc(now_ts)
        exp_iso = _iso_utc(exp_ts)
        fb = str(fallback_mode) if fallback_mode is not None else None
        metrics_copy = dict(metrics) if isinstance(metrics, dict) else (dict(metrics) if metrics is not None else None)

        with self._lock:
            prev = self._entries.get(cap)
            sample_count = int(prev.get("sample_count", 0)) + 1 if prev else 1
            entry: dict[str, Any] = {
                "capability": cap,
                "execution_node": str(execution_node),
                "fallback_mode": fb,
                "ttl_s": ttl,
                "verified": bool(verified),
                "violated": bool(violated),
                "sample_count": sample_count,
                "last_verified_at": last_iso,
                "last_verified_epoch": now_ts,
                "expires_at": exp_iso,
                "expires_epoch": exp_ts,
                "metrics": metrics_copy,
                "receipt_id": str(receipt_id) if receipt_id is not None else None,
            }
            self._entries[cap] = entry
            self._save_locked()
            return dict(entry)

    def activity_observer(
        self, execution_node: str, *, synthetic: bool = False, ttl_s: float = 300.0,
        flush_interval_s: float = 30.0,
    ) -> Callable[[str, bool, int], None]:
        """Observe completed operations. Only the fixed operation name and a numeric result enter the ledger."""
        if not (math.isfinite(ttl_s) and math.isfinite(flush_interval_s) and 0 < flush_interval_s < ttl_s):
            raise ValueError("require finite positive flush_interval_s less than ttl_s")
        node = str(execution_node)
        source = "fixture_traffic" if synthetic else "runtime_traffic"

        def observe(operation: str, success: bool, value: int) -> None:
            cap, field = _TRAFFIC[operation]
            if type(success) is not bool or type(value) is not int or value < 1:
                raise ValueError("invalid traffic observation")
            if field == "http_status" and (not 100 <= value <= 599 or success != (200 <= value < 300)):
                raise ValueError("HTTP observation disagrees with the final response")
            with self._lock:
                now = time.time()
                tick = time.monotonic()
                previous = self._entries.get(cap, {})
                count = int(previous.get("sample_count", 0)) + 1
                origin = [self._session, node, source, operation, count, now, success, value]
                receipt = hashlib.sha256(json.dumps(origin, separators=(",", ":")).encode()).hexdigest()
                when = _iso_utc(now)
                self._entries[cap] = {
                    "capability": cap, "execution_node": node, "fallback_mode": None,
                    "sample_count": count, "verified": success, "violated": False,
                    "ttl_s": ttl_s, "expires_epoch": now + ttl_s, "expires_at": _iso_utc(now + ttl_s),
                    "last_observed_at": when, "last_verified_at": when if success else previous.get("last_verified_at"),
                    "last_verified_epoch": now if success else previous.get("last_verified_epoch"),
                    "receipt_id": receipt, "activity_session": self._session, "evidence_source": source,
                    "metrics": {"operation": operation, "successful": success, field: value},
                }
                self._traffic_dirty = True
                if self.path is not None and tick - self._last_flush >= flush_interval_s:
                    self._last_flush = tick
                    self._save_locked()

        return observe

    def flush_traffic(self) -> None:
        """Persist remaining observations at orderly shutdown without changing their observation time."""
        with self._lock:
            if self._traffic_dirty and self.path is not None:
                self._save_locked()

    def _evaluate_entry(
        self,
        entry: dict[str, Any] | None,
        *,
        enabled: bool,
        now_ts: float,
    ) -> dict[str, Any]:
        if entry is None:
            return {
                "enabled": bool(enabled),
                "verification_status": "disabled" if not enabled else "unverified",
                "last_verified_at": None,
                "execution_node": None,
                "fallback_mode": None,
                "sample_count": 0,
                "expires_at": None,
                "stale": False,
                "metrics": None,
                "receipt_id": None,
            }

        exp_epoch = float(entry.get("expires_epoch", 0.0))
        expired = now_ts >= exp_epoch
        previous_process = "activity_session" in entry and entry["activity_session"] != self._session
        if not enabled:
            status = "disabled"
        elif expired or previous_process:
            status = "unverified"
        elif bool(entry.get("violated", False)):
            status = "violated"
        elif bool(entry.get("verified", True)):
            status = "verified"
        else:
            status = "unverified"

        raw_metrics = entry.get("metrics")
        return {
            "enabled": bool(enabled),
            "verification_status": status,
            "last_verified_at": entry.get("last_verified_at"),
            "last_observed_at": entry.get("last_observed_at", entry.get("last_verified_at")),
            "evidence_source": entry.get("evidence_source", "recorded_receipt"),
            "previous_process": previous_process,
            "execution_node": entry.get("execution_node"),
            "fallback_mode": entry.get("fallback_mode"),
            "sample_count": int(entry.get("sample_count", 0)),
            "expires_at": entry.get("expires_at"),
            "stale": bool(expired),
            "metrics": dict(raw_metrics) if isinstance(raw_metrics, dict) else raw_metrics,
            "receipt_id": entry.get("receipt_id"),
        }

    def evaluate(
        self,
        capability: str,
        *,
        enabled: bool = True,
        now_epoch: float | None = None,
    ) -> dict[str, Any]:
        """Evaluate freshness and verification status for one capability."""
        cap = str(capability or "").strip()
        now_ts = float(now_epoch) if now_epoch is not None else time.time()
        with self._lock:
            entry = self._entries.get(cap)
            entry_copy = dict(entry) if entry is not None else None
        return self._evaluate_entry(entry_copy, enabled=bool(enabled), now_ts=now_ts)

    def snapshot(
        self,
        enabled_map: dict[str, bool] | None = None,
        now_epoch: float | None = None,
        *,
        include_extra: bool = False,
    ) -> dict[str, Any]:
        """Evaluate all capabilities in enabled_map (or all recorded capabilities when None)."""
        now_ts = float(now_epoch) if now_epoch is not None else time.time()
        with self._lock:
            entries_snap = {k: dict(v) for k, v in self._entries.items()}

        if enabled_map is None:
            keys = sorted(entries_snap.keys())
            eff_enabled = {k: True for k in keys}
        else:
            eff_enabled = {str(k): bool(v) for k, v in enabled_map.items()}
            keys = list(eff_enabled.keys())
            if include_extra:
                for k in sorted(entries_snap.keys()):
                    if k not in eff_enabled:
                        keys.append(k)
                        eff_enabled[k] = eff_enabled.get("pulse", True) if k == "pulse.relay" else True

        capabilities: dict[str, dict[str, Any]] = {}
        counts = {"verified": 0, "unverified": 0, "violated": 0, "disabled": 0}
        for k in keys:
            ev = self._evaluate_entry(entries_snap.get(k), enabled=eff_enabled[k], now_ts=now_ts)
            capabilities[k] = ev
            st = ev["verification_status"]
            counts[st] = counts.get(st, 0) + 1

        return {
            "ok": counts.get("violated", 0) == 0,
            "generated_at": _iso_utc(now_ts),
            "capabilities": capabilities,
            "counts": counts,
            "recorded_capabilities": len(entries_snap),
        }

    def truth_matrix(self, enabled_map: dict[str, bool], *, now_epoch: float | None = None) -> dict[str, Any]:
        """Classify the evidence underlying each current receipt, including explicit gaps."""
        snap = self.snapshot(enabled_map, now_epoch, include_extra=True)
        rows = {}
        for capability, entry in snap["capabilities"].items():
            status = entry["verification_status"]
            source = entry.get("evidence_source")
            basis = status
            if status == "verified":
                if source in ("runtime_traffic", "fixture_traffic"):
                    basis = source
                elif (entry.get("metrics") or {}).get("startup_self_check") is True:
                    basis = "startup_check"
                else:
                    basis = "recorded_receipt"
            rows[capability] = {**entry, "basis": basis}
        return {"schema": "chimera.traffic-evidence/1", "as_of": snap["generated_at"],
                "scope": "Latest observation per capability and operation, from this ledger",
                "counts": snap["counts"], "capabilities": rows}
