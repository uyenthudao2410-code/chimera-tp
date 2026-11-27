"""TrinityCommandBridge — generic cross-stack control plane decoupled via declarative manifest adapters."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
import threading
import time
from typing import TYPE_CHECKING, Any, Callable
import urllib.parse
import urllib.request

from .host_governor import HostYieldGovernor

if TYPE_CHECKING:
    from .overmind_cortex import OvermindCortex

_MISSING = object()


def _fetch_json(url: str, timeout_s: float = 1.2) -> dict[str, Any] | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout_s) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
            return data if isinstance(data, dict) else {"raw": data}
    except Exception:
        return None


def _post_json(url: str, payload: dict[str, Any], timeout_s: float = 1.2) -> dict[str, Any] | None:
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
            return data if isinstance(data, dict) else {"raw": data}
    except Exception:
        return None


@dataclass
class DownstreamAdapterSpec:
    """Declarative specification enabling TrinityCommandBridge to integrate any downstream app."""

    name: str
    roles: tuple[str, ...] = ("telemetry",)
    base_url: str = ""
    fallback_urls: tuple[str, ...] = ()
    telemetry_endpoints: tuple[dict[str, Any], ...] = ()
    field_map: dict[str, Any] = field(default_factory=dict)
    require_ok: bool = False
    control_endpoint: str = ""
    control_payload_map: dict[str, str] = field(default_factory=dict)
    control_all_urls: bool = False
    reconcile: dict[str, Any] = field(default_factory=dict)
    proofs_endpoint: str = ""
    outputs_field: str = "outputs"
    burn_rate_field: str = "burn_rate_pct_hr"
    peer_relay: bool = True

    def __post_init__(self) -> None:
        self.name = str(self.name or "").strip()
        self.roles = tuple(str(r).strip().lower() for r in self.roles if str(r or "").strip())
        self.base_url = str(self.base_url or "").strip().rstrip("/")
        self.fallback_urls = tuple(
            str(u).strip().rstrip("/") for u in self.fallback_urls if str(u or "").strip()
        )
        norm_eps: list[dict[str, Any]] = []
        for ep in self.telemetry_endpoints:
            if isinstance(ep, str):
                p = ep.strip()
                if p:
                    norm_eps.append({"path": p if p.startswith("/") else f"/{p}", "timeout_s": 1.2})
            elif isinstance(ep, dict):
                p = str(ep.get("path") or "").strip()
                if p:
                    item = dict(ep)
                    item["path"] = p if p.startswith("/") else f"/{p}"
                    item["timeout_s"] = float(ep.get("timeout_s", 1.2) or 1.2)
                    norm_eps.append(item)
        self.telemetry_endpoints = tuple(norm_eps)
        self.field_map = copy.deepcopy(dict(self.field_map or {}))
        ctrl = str(self.control_endpoint or "").strip()
        self.control_endpoint = (ctrl if ctrl.startswith("/") else f"/{ctrl}") if ctrl else ""
        self.control_payload_map = {str(k): str(v) for k, v in (self.control_payload_map or {}).items()}
        self.reconcile = copy.deepcopy(dict(self.reconcile or {}))
        proofs = str(self.proofs_endpoint or "").strip()
        self.proofs_endpoint = (proofs if proofs.startswith("/") else f"/{proofs}") if proofs else ""
        self.outputs_field = str(self.outputs_field or "outputs")
        self.burn_rate_field = str(self.burn_rate_field or "burn_rate_pct_hr")

    def to_summary(self, *, online: bool = False) -> dict[str, Any]:
        return {
            "name": self.name,
            "roles": list(self.roles),
            "base_url": self.base_url,
            "fallback_urls": list(self.fallback_urls),
            "telemetry_endpoints": [dict(ep) for ep in self.telemetry_endpoints],
            "field_map": copy.deepcopy(self.field_map),
            "control_endpoint": self.control_endpoint,
            "control_payload_map": dict(self.control_payload_map),
            "reconcile": copy.deepcopy(self.reconcile),
            "proofs_endpoint": self.proofs_endpoint,
            "online": bool(online),
        }


def adapter_from_manifest(manifest_dict: dict[str, Any]) -> DownstreamAdapterSpec | None:
    """Build a DownstreamAdapterSpec from a chimera.manifest.v1 dict or registry entry."""
    if not isinstance(manifest_dict, dict):
        return None
    raw_adapter = manifest_dict.get("adapter")
    if raw_adapter is None and any(
        k in manifest_dict for k in ("roles", "telemetry_endpoints", "control_endpoint", "proofs_endpoint")
    ):
        raw_adapter = manifest_dict
    if not isinstance(raw_adapter, dict):
        return None

    name = str(raw_adapter.get("name") or manifest_dict.get("app") or raw_adapter.get("app") or "").strip()
    if not name:
        return None

    base_url = str(raw_adapter.get("base_url") or "").strip().rstrip("/")
    if not base_url:
        port = int(manifest_dict.get("port") or raw_adapter.get("port") or 0)
        if port > 0:
            base_url = f"http://127.0.0.1:{port}"

    raw_fb = raw_adapter.get("fallback_urls") or ()
    if isinstance(raw_fb, str):
        raw_fb = (raw_fb,)

    raw_roles = raw_adapter.get("roles")
    if raw_roles is None:
        inferred: list[str] = []
        if raw_adapter.get("telemetry_endpoints"):
            inferred.append("telemetry")
        if raw_adapter.get("control_endpoint"):
            inferred.append("actuated")
        if raw_adapter.get("proofs_endpoint"):
            inferred.append("proofs")
        roles = tuple(inferred) if inferred else ("telemetry",)
    elif isinstance(raw_roles, str):
        roles = (raw_roles,)
    else:
        roles = tuple(raw_roles)

    return DownstreamAdapterSpec(
        name=name,
        roles=roles,
        base_url=base_url,
        fallback_urls=tuple(raw_fb),
        telemetry_endpoints=tuple(raw_adapter.get("telemetry_endpoints") or ()),
        field_map=dict(raw_adapter.get("field_map") or {}),
        require_ok=bool(raw_adapter.get("require_ok", False)),
        control_endpoint=str(raw_adapter.get("control_endpoint") or ""),
        control_payload_map=dict(raw_adapter.get("control_payload_map") or {}),
        control_all_urls=bool(raw_adapter.get("control_all_urls", False)),
        reconcile=dict(raw_adapter.get("reconcile") or {}),
        proofs_endpoint=str(raw_adapter.get("proofs_endpoint") or ""),
        outputs_field=str(raw_adapter.get("outputs_field") or "outputs"),
        burn_rate_field=str(raw_adapter.get("burn_rate_field") or "burn_rate_pct_hr"),
        peer_relay=bool(raw_adapter.get("peer_relay", True)),
    )


def _extract_path(obj: Any, path: str) -> Any:
    cur = obj
    for part in str(path or "").split("."):
        if not part:
            continue
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, (list, tuple)) and part.isdigit():
            idx = int(part)
            if 0 <= idx < len(cur):
                cur = cur[idx]
            else:
                return _MISSING
        else:
            return _MISSING
    return cur


def _resolve_from_sources(merged_raw: dict[str, Any], by_alias: dict[str, dict[str, Any]], path: str) -> Any:
    head, sep, rest = str(path or "").partition(".")
    if sep and head in by_alias:
        val = _extract_path(by_alias[head], rest)
        if val is not _MISSING:
            return val
    return _extract_path(merged_raw, path)


def _coerce_value(val: Any, rule: dict[str, Any]) -> Any:
    if rule.get("transform") == "len":
        val = len(val or ()) if val is not None else 0
    kind = str(rule.get("type") or "").lower()
    if kind == "int":
        val = int(val or 0)
    elif kind == "float":
        val = float(val or 0.0)
    elif kind == "bool":
        val = bool(val)
    elif kind == "str":
        val = str(val or "")
    if "round" in rule and isinstance(val, (int, float)) and not isinstance(val, bool):
        val = round(float(val), int(rule["round"]))
    return val


def _apply_field_map(
    merged_raw: dict[str, Any],
    by_alias: dict[str, dict[str, Any]],
    field_map: dict[str, Any],
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if not field_map:
        for k, v in merged_raw.items():
            if k not in ("online", "endpoint", "latency_ms"):
                out[k] = v
        return out

    for dst_key, spec in field_map.items():
        if isinstance(spec, str):
            val = _resolve_from_sources(merged_raw, by_alias, spec)
            if val is not _MISSING:
                out[dst_key] = val
        elif isinstance(spec, (list, tuple)):
            for candidate in spec:
                val = _resolve_from_sources(merged_raw, by_alias, str(candidate))
                if val is not _MISSING:
                    out[dst_key] = val
                    break
        elif isinstance(spec, dict):
            candidates = list(spec.get("paths") or ())
            if spec.get("path"):
                candidates.insert(0, str(spec["path"]))
            val = _MISSING
            for candidate in candidates:
                found = _resolve_from_sources(merged_raw, by_alias, str(candidate))
                if found is not _MISSING:
                    val = found
                    break
            if val is _MISSING or (val is None and "default" in spec):
                if "default" in spec:
                    out[dst_key] = spec["default"]
                continue
            out[dst_key] = _coerce_value(val, spec)
    return out


def _build_control_payload(
    spec: DownstreamAdapterSpec,
    *,
    active: bool,
    reason: str,
    source: str,
    hlc_ts_ms: int,
) -> dict[str, Any]:
    canonical = {
        "paused": bool(active),
        "reason": str(reason),
        "source": str(source),
        "hlc_ts_ms": int(hlc_ts_ms),
    }
    if not spec.control_payload_map:
        return canonical
    payload: dict[str, Any] = {}
    for src_key, dst_path in spec.control_payload_map.items():
        if src_key not in canonical or not dst_path:
            continue
        parts = [p for p in str(dst_path).split(".") if p]
        if not parts:
            continue
        cur = payload
        for part in parts[:-1]:
            nxt = cur.get(part)
            if not isinstance(nxt, dict):
                nxt = {}
                cur[part] = nxt
            cur = nxt
        cur[parts[-1]] = canonical[src_key]
    return payload


def _iter_manifest_dicts(source: Any) -> list[dict[str, Any]]:
    if source is None:
        return []
    if isinstance(source, (str, Path)):
        p = Path(source)
        if p.is_dir():
            p = p / "chimera.manifest.json"
        if not p.is_file():
            return []
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return []
        return _iter_manifest_dicts(data)
    if hasattr(source, "list_apps") and callable(source.list_apps):
        out: list[dict[str, Any]] = []
        for item in list(source.list_apps()):
            if not isinstance(item, dict):
                continue
            if isinstance(item.get("adapter"), dict):
                out.append(item)
            elif item.get("path"):
                mf = Path(str(item["path"])) / "chimera.manifest.json"
                if mf.is_file():
                    out.extend(_iter_manifest_dicts(mf))
        return out
    if isinstance(source, dict):
        if "adapter" in source or any(
            k in source for k in ("roles", "telemetry_endpoints", "control_endpoint", "proofs_endpoint")
        ):
            return [source]
        out = []
        for app_key, val in source.items():
            if isinstance(val, dict):
                out.append({"app": str(app_key), **val})
        return out
    if isinstance(source, (list, tuple, set)):
        out = []
        for item in source:
            out.extend(_iter_manifest_dicts(item))
        return out
    return []


def _default_adapter_specs(
    *,
    tquota_admin_url: str,
    radar_url: str,
    peer_radar_url: str,
) -> tuple[DownstreamAdapterSpec, DownstreamAdapterSpec]:
    tquota_spec = DownstreamAdapterSpec(
        name="tquota",
        roles=("telemetry",),
        base_url=str(tquota_admin_url or "").rstrip("/"),
        telemetry_endpoints=(
            {"path": "/api/hive/status", "timeout_s": 1.2, "alias": "hive"},
            {"path": "/api/time-crystal/status", "timeout_s": 1.2, "alias": "tc"},
            {"path": "/api/overmind/telemetry", "timeout_s": 1.2, "alias": "ov"},
        ),
        field_map={
            "gossip_errors": {"path": "hive.gossipErrors", "type": "int", "default": 0},
            "phantom_routes": {"path": "hive.phantomRoutes", "type": "int", "default": 0},
            "cache_affinity_routes": {"path": "hive.cacheAffinityRoutes", "type": "int", "default": 0},
            "codex_fast_routes": {"path": "hive.codexFastRoutes", "type": "int", "default": 0},
            "quarantined_count": {"paths": ["tc.quarantinedCount", "hive.quarantinedCount"], "type": "int", "default": 0},
            "healthy_count": {"path": "tc.healthyCount", "type": "int", "default": 0},
            "expiring_soon": {"path": "tc.expiringSoonCount", "type": "int", "default": 0},
            "colab_remaining_cu": {"path": "tc.totalRemainingColabCU", "type": "float", "default": 0.0},
            "cross_family_target": {"path": "hive.crossFamilyTarget", "default": None},
            "burn_rate_pct_hr": {"path": "ov.burnRatePctHr", "type": "float", "round": 2, "default": 0.0},
            "thought_brief_entries": {"path": "ov.thoughtBriefsEntries", "type": "int", "default": 0},
            "thought_brief_hits": {"path": "ov.thoughtBriefHits", "type": "int", "default": 0},
            "codex_p50_ttft_ms": {"path": "ov.p50TtftMs", "type": "int", "default": 0},
        },
        burn_rate_field="burn_rate_pct_hr",
        peer_relay=False,
    )
    radar_spec = DownstreamAdapterSpec(
        name="radar",
        roles=("telemetry", "actuated", "proofs"),
        base_url=str(radar_url or "").rstrip("/"),
        fallback_urls=tuple(u for u in (str(peer_radar_url or "").rstrip("/"),) if u),
        telemetry_endpoints=(
            {"path": "/api/godmode/status", "timeout_s": 1.2, "require_ok": True},
        ),
        require_ok=True,
        field_map={
            "paused": {"path": "sovereign.paused", "type": "bool", "default": False},
            "pause_source": {"path": "sovereign.pause_source", "type": "str", "default": ""},
            "learned_rules": {"path": "learned_rules_count", "type": "int", "default": 0},
            "patch_crystals": {"path": "patch_crystals_count", "type": "int", "default": 0},
            "colab_queued": {"path": "colab.queued_count", "type": "int", "default": 0},
            "colab_completed": {"path": "colab.completed_count", "type": "int", "default": 0},
            "salvageable_runs": {"path": "salvage.salvageable_count", "type": "int", "default": 0},
            "engines_ready": {"path": "engines", "transform": "len", "default": 0},
        },
        control_endpoint="/api/godmode/control",
        control_payload_map={
            "paused": "paused",
            "reason": "reason",
            "source": "source",
            "hlc_ts_ms": "hlc_ts_ms",
        },
        control_all_urls=True,
        reconcile={
            "paused_path": "sovereign.paused",
            "source_path": "sovereign.pause_source",
            "expected_source": "chimera_kill_switch",
        },
        proofs_endpoint="/api/godmode/necromancer/proofs?limit={limit}",
        outputs_field="colab_completed",
        peer_relay=True,
    )
    return tquota_spec, radar_spec


class TrinityCommandBridge:
    """Generic cross-stack control plane aggregating telemetry, CRDT kill-switch, reconciliation, and proofs via manifest adapters."""

    def __init__(
        self,
        *,
        governor: HostYieldGovernor,
        tquota_admin_url: str = "http://127.0.0.1:12504",
        radar_url: str = "http://127.0.0.1:8787",
        peer_radar_url: str = "",
        peer_trinity_resolver: Callable[[], str] | None = None,
        ephemeral_mode: bool = False,
        on_flow: Callable[..., None] | None = None,
        overmind: "OvermindCortex | None" = None,
    ) -> None:
        self.governor = governor
        self._tquota_admin_url = str(tquota_admin_url or "").rstrip("/")
        self._radar_url = str(radar_url or "").rstrip("/")
        self._peer_radar_url = str(peer_radar_url or "").rstrip("/")
        self.peer_trinity_resolver = peer_trinity_resolver
        self._ephemeral_mode = bool(ephemeral_mode)
        self._on_flow = on_flow
        self.overmind = overmind

        self._lock = threading.Lock()
        self._cache_ts: float = 0.0
        self._busy: bool = False
        self._adapters: dict[str, DownstreamAdapterSpec] = {}
        self._cache: dict[str, dict[str, Any]] = {}

        for default_spec in _default_adapter_specs(
            tquota_admin_url=self._tquota_admin_url,
            radar_url=self._radar_url,
            peer_radar_url=self._peer_radar_url,
        ):
            self._adapters[default_spec.name] = default_spec
            self._cache[default_spec.name] = {"online": False}

        crdt_init = overmind.crdt.snapshot() if overmind is not None else {}
        self._kill_switch: dict[str, Any] = {
            "active": bool(crdt_init.get("kill_switch_active", False)),
            "reason": str(crdt_init.get("kill_switch_reason") or ""),
            "triggered_at": crdt_init.get("updated_at") if crdt_init.get("kill_switch_active") else None,
            "auto_triggered": bool(crdt_init.get("kill_switch_auto", False)),
            "quota_burn_rate_pct_hr": 0.0,
            "recent_outputs": 0,
            "max_burn_rate_pct_hr": float(crdt_init.get("max_burn_rate_pct_hr") or 12.0),
        }

    @property
    def tquota_admin_url(self) -> str:
        with self._lock:
            spec = self._adapters.get("tquota")
            return spec.base_url if spec is not None else self._tquota_admin_url

    @tquota_admin_url.setter
    def tquota_admin_url(self, value: str) -> None:
        url = str(value or "").rstrip("/")
        with self._lock:
            self._tquota_admin_url = url
            spec = self._adapters.get("tquota")
            if spec is not None:
                spec.base_url = url

    @property
    def radar_url(self) -> str:
        with self._lock:
            spec = self._adapters.get("radar")
            return spec.base_url if spec is not None else self._radar_url

    @radar_url.setter
    def radar_url(self, value: str) -> None:
        url = str(value or "").rstrip("/")
        with self._lock:
            self._radar_url = url
            spec = self._adapters.get("radar")
            if spec is not None:
                spec.base_url = url

    @property
    def peer_radar_url(self) -> str:
        with self._lock:
            spec = self._adapters.get("radar")
            if spec is not None and spec.fallback_urls:
                return spec.fallback_urls[0]
            return self._peer_radar_url

    @peer_radar_url.setter
    def peer_radar_url(self, value: str) -> None:
        url = str(value or "").rstrip("/")
        with self._lock:
            self._peer_radar_url = url
            spec = self._adapters.get("radar")
            if spec is not None:
                spec.fallback_urls = (url,) if url else ()

    def register_adapter(self, name: str, spec: DownstreamAdapterSpec | dict[str, Any]) -> DownstreamAdapterSpec:
        clean_name = str(name or "").strip()
        if not clean_name:
            raise ValueError("adapter name must be non-empty")
        if isinstance(spec, DownstreamAdapterSpec):
            resolved = copy.deepcopy(spec)
            resolved.name = clean_name
        elif isinstance(spec, dict):
            payload = {"app": clean_name, **spec} if "app" not in spec and "name" not in spec else dict(spec)
            parsed = adapter_from_manifest(payload)
            if parsed is None:
                raise ValueError(f"invalid adapter specification for {clean_name!r}")
            resolved = parsed
            resolved.name = clean_name
        else:
            raise TypeError("spec must be DownstreamAdapterSpec or dict")

        with self._lock:
            self._adapters[clean_name] = resolved
            self._cache.setdefault(clean_name, {"online": False})
            if clean_name == "tquota":
                self._tquota_admin_url = resolved.base_url
            elif clean_name == "radar":
                self._radar_url = resolved.base_url
                self._peer_radar_url = resolved.fallback_urls[0] if resolved.fallback_urls else ""
            return copy.deepcopy(resolved)

    def unregister_adapter(self, name: str) -> bool:
        clean_name = str(name or "").strip()
        with self._lock:
            existed = clean_name in self._adapters
            self._adapters.pop(clean_name, None)
            self._cache.pop(clean_name, None)
            return existed

    def list_adapters(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                spec.to_summary(online=bool((self._cache.get(name) or {}).get("online", False)))
                for name, spec in self._adapters.items()
            ]

    def load_adapters_from_manifests(self, manifests_or_registry: Any) -> list[str]:
        loaded: list[str] = []
        for manifest_dict in _iter_manifest_dicts(manifests_or_registry):
            spec = adapter_from_manifest(manifest_dict)
            if spec is not None:
                self.register_adapter(spec.name, spec)
                loaded.append(spec.name)
        return loaded

    def set_kill_switch(
        self,
        active: bool,
        reason: str = "",
        *,
        auto_triggered: bool = False,
        actuate: bool | None = None,
        relay_to_peer: bool = True,
    ) -> dict[str, Any]:
        t0 = time.perf_counter()
        resolved_reason = str(reason or ("manual_operator_halt" if active else "cleared"))
        crdt_snap: dict[str, Any] = {}
        if self.overmind is not None:
            crdt_snap = self.overmind.crdt.mutate(
                {
                    "kill_switch_active": bool(active),
                    "kill_switch_reason": resolved_reason,
                    "kill_switch_source": "chimera_kill_switch",
                    "kill_switch_auto": bool(auto_triggered) if active else False,
                },
                source="chimera_kill_switch",
            )
            self.overmind.pulse.emit(
                "BRAIN_STATE_CHANGED",
                "trinity",
                {
                    "active": bool(active),
                    "reason": resolved_reason,
                    "auto": bool(auto_triggered),
                    "hlc_ts_ms": crdt_snap.get("hlc_ts_ms", 0),
                },
            )

        with self._lock:
            self._kill_switch["active"] = bool(active)
            self._kill_switch["reason"] = resolved_reason
            self._kill_switch["triggered_at"] = datetime.now(timezone.utc).isoformat() if active else None
            self._kill_switch["auto_triggered"] = bool(auto_triggered) if active else False
            if crdt_snap:
                self._kill_switch["hlc_ts_ms"] = crdt_snap.get("hlc_ts_ms", 0)
            snap = dict(self._kill_switch)

        do_actuate = (not self._ephemeral_mode) if actuate is None else bool(actuate)
        actuation: dict[str, Any] = {
            "ok": False,
            "mode": "skipped_ephemeral" if not do_actuate else "unreachable",
            "targets": [],
            "elapsed_ms": 0.0,
        }
        if do_actuate:
            t_act = time.perf_counter()
            hlc_ms = int(crdt_snap.get("hlc_ts_ms", 0) or 0)
            with self._lock:
                actuated_specs = [
                    copy.deepcopy(spec)
                    for spec in self._adapters.values()
                    if any(r in ("actuated", "control") for r in spec.roles) and spec.control_endpoint
                ]
            for spec in actuated_specs:
                urls = [u for u in (spec.base_url, *spec.fallback_urls) if u]
                if not urls:
                    continue
                ctrl_payload = _build_control_payload(
                    spec,
                    active=bool(active),
                    reason=snap["reason"],
                    source="chimera_kill_switch",
                    hlc_ts_ms=hlc_ms,
                )
                for idx, base in enumerate(urls):
                    res = _post_json(f"{base}{spec.control_endpoint}", ctrl_payload, timeout_s=1.2)
                    if isinstance(res, dict) and res.get("ok", True):
                        paused_key = str((spec.control_payload_map or {}).get("paused") or "paused")
                        paused_val = res.get("paused", res.get(paused_key, bool(active)))
                        label = spec.name if idx == 0 else f"{spec.name}_peer_{idx}"
                        actuation["targets"].append(
                            {
                                "target": label,
                                "adapter": spec.name,
                                "endpoint": base,
                                "paused": paused_val,
                            }
                        )
                        actuation["ok"] = True
                        actuation["mode"] = "direct"
                        if not spec.control_all_urls:
                            break

            if relay_to_peer and self.peer_trinity_resolver is not None:
                p_base = str(self.peer_trinity_resolver() or "").rstrip("/")
                if p_base:
                    p_res = _post_json(
                        f"{p_base}/api/trinity/kill-switch",
                        {
                            "active": bool(active),
                            "reason": snap["reason"],
                            "auto_triggered": bool(auto_triggered),
                            "from_peer": True,
                            "crdt": crdt_snap,
                        },
                        timeout_s=1.5,
                    )
                    if crdt_snap:
                        _post_json(f"{p_base}/api/overmind/state", crdt_snap, timeout_s=1.2)
                    p_ks = (p_res or {}).get("kill_switch") if isinstance(p_res, dict) else None
                    if isinstance(p_ks, dict):
                        actuation["targets"].append(
                            {
                                "target": "peer_trinity_phantom",
                                "endpoint": p_base,
                                "peer_actuation": p_ks.get("actuation"),
                            }
                        )
                        if (p_ks.get("actuation") or {}).get("ok") or p_res.get("ok"):
                            actuation["ok"] = True
                            actuation["mode"] = "direct+phantom_peer" if actuation["mode"] == "direct" else "phantom_peer"
            actuation["elapsed_ms"] = round((time.perf_counter() - t_act) * 1000.0, 2)

        with self._lock:
            self._kill_switch["actuation"] = actuation
            snap = dict(self._kill_switch)

        if self._on_flow is not None:
            self._on_flow(
                "governor",
                "trinity",
                "KILL_SWITCH",
                "ROI_KILL_SWITCH" if active else "ROI_RESUME",
                wire_bytes=64,
                elapsed_ms=(time.perf_counter() - t0) * 1000.0,
                detail=f"active={snap['active']} mode={actuation['mode']} reason={snap['reason'][:36]}",
                ok=True,
            )
        return snap

    def evaluate_auto_kill_switch(
        self,
        *,
        burn_rate_pct_hr: float,
        recent_outputs: int,
        zero_output_hours: float = 2.0,
    ) -> dict[str, Any]:
        rate = float(burn_rate_pct_hr or 0.0)
        outs = int(recent_outputs or 0)
        hrs = float(zero_output_hours or 0.0)
        with self._lock:
            threshold = float(self._kill_switch.get("max_burn_rate_pct_hr", 12.0))
            self._kill_switch["quota_burn_rate_pct_hr"] = round(rate, 2)
            self._kill_switch["recent_outputs"] = outs
        if rate >= threshold and outs == 0 and hrs >= 2.0:
            return self.set_kill_switch(
                True,
                f"auto_roi_cutoff: burn={rate:.1f}%/hr >= {threshold:.1f}%/hr with 0 outputs over {hrs:.1f}h",
                auto_triggered=True,
            )
        with self._lock:
            return dict(self._kill_switch)

    def _reconcile_adapter_split_brain(
        self,
        spec: DownstreamAdapterSpec,
        base: str,
        merged_raw: dict[str, Any],
        by_alias: dict[str, dict[str, Any]],
    ) -> bool:
        if self.overmind is None or not spec.reconcile or not spec.control_endpoint:
            return False
        paused_path = str(spec.reconcile.get("paused_path") or "").strip()
        if not paused_path:
            return False
        paused_val = _resolve_from_sources(merged_raw, by_alias, paused_path)
        if paused_val is _MISSING:
            return False

        crdt_st = self.overmind.crdt.snapshot()
        hlc_ms = int(crdt_st.get("hlc_ts_ms") or 0)
        if hlc_ms <= 0:
            return False

        remote_paused = bool(paused_val)
        crdt_active = bool(crdt_st.get("kill_switch_active"))
        source_path = str(spec.reconcile.get("source_path") or "").strip()
        if source_path:
            raw_src = _resolve_from_sources(merged_raw, by_alias, source_path)
            pause_src = "" if raw_src is _MISSING or raw_src is None else str(raw_src)
            expected_source = str(spec.reconcile.get("expected_source", "chimera_kill_switch"))
            if expected_source != "*" and pause_src != expected_source:
                return False

        if remote_paused == crdt_active:
            return False

        ctrl_payload = _build_control_payload(
            spec,
            active=crdt_active,
            reason=str(crdt_st.get("kill_switch_reason") or ("reconcile_halt" if crdt_active else "crdt_reconciled")),
            source="chimera_kill_switch",
            hlc_ts_ms=hlc_ms,
        )
        res = _post_json(f"{base}{spec.control_endpoint}", ctrl_payload, timeout_s=1.2)
        if isinstance(res, dict) and res.get("ok", True):
            self.overmind.pulse.emit(
                "BRAIN_STATE_RECONCILED",
                "trinity",
                {
                    "adapter": spec.name,
                    "endpoint": base,
                    "reconciled_paused": crdt_active,
                    "hlc_ts_ms": hlc_ms,
                },
            )
            return True
        return False

    def sync_crdt_from_peer(self, peer_state: dict[str, Any]) -> dict[str, Any]:
        if self.overmind is None:
            return {"ok": False, "merged": False}
        res = self.overmind.crdt.merge(peer_state)
        st = res.get("state") or {}
        if res.get("merged"):
            active = bool(st.get("kill_switch_active", False))
            reason = str(st.get("kill_switch_reason") or "crdt_peer_merge")
            hlc_ms = int(st.get("hlc_ts_ms") or 0)
            with self._lock:
                self._kill_switch["active"] = active
                self._kill_switch["reason"] = str(st.get("kill_switch_reason") or "")
                self._kill_switch["auto_triggered"] = bool(st.get("kill_switch_auto", False))
                self._kill_switch["hlc_ts_ms"] = hlc_ms
                actuated_specs = [
                    copy.deepcopy(spec)
                    for spec in self._adapters.values()
                    if any(r in ("actuated", "control") for r in spec.roles) and spec.control_endpoint
                ]
            if not self._ephemeral_mode:
                for spec in actuated_specs:
                    if not spec.base_url:
                        continue
                    ctrl_payload = _build_control_payload(
                        spec,
                        active=active,
                        reason=reason,
                        source="chimera_kill_switch",
                        hlc_ts_ms=hlc_ms,
                    )
                    _post_json(f"{spec.base_url}{spec.control_endpoint}", ctrl_payload, timeout_s=1.2)
        return res

    def _poll_single_adapter(
        self,
        spec: DownstreamAdapterSpec,
        peer_state_getter: Callable[[], tuple[str, dict[str, Any] | None]],
    ) -> dict[str, Any]:
        if "telemetry" not in spec.roles or not spec.telemetry_endpoints:
            return {"online": False}

        candidates = [u for u in (spec.base_url, *spec.fallback_urls) if u]
        for base in candidates:
            t0 = time.perf_counter()
            by_alias: dict[str, dict[str, Any]] = {}
            merged_raw: dict[str, Any] = {}
            any_ok = False
            for ep in spec.telemetry_endpoints:
                ep_path = str(ep.get("path") or "").strip()
                if not ep_path:
                    continue
                timeout_s = float(ep.get("timeout_s", 1.2) or 1.2)
                resp = _fetch_json(f"{base}{ep_path}", timeout_s=timeout_s)
                if isinstance(resp, dict):
                    ep_req_ok = bool(ep.get("require_ok", spec.require_ok))
                    if ep_req_ok and not resp.get("ok"):
                        continue
                    any_ok = True
                    alias = str(ep.get("alias") or "").strip()
                    if alias:
                        by_alias[alias] = resp
                    merged_raw.update(resp)
            latency_ms = round((time.perf_counter() - t0) * 1000.0, 2)
            if any_ok:
                mapped = _apply_field_map(merged_raw, by_alias, spec.field_map)
                healed = self._reconcile_adapter_split_brain(spec, base, merged_raw, by_alias)
                status: dict[str, Any] = {
                    "online": True,
                    "endpoint": base,
                    "latency_ms": latency_ms,
                    **mapped,
                }
                if spec.reconcile:
                    if "paused" not in status and spec.reconcile.get("paused_path"):
                        pv = _resolve_from_sources(merged_raw, by_alias, str(spec.reconcile["paused_path"]))
                        if pv is not _MISSING:
                            status["paused"] = bool(pv)
                    if "pause_source" not in status and spec.reconcile.get("source_path"):
                        sv = _resolve_from_sources(merged_raw, by_alias, str(spec.reconcile["source_path"]))
                        if sv is not _MISSING:
                            status["pause_source"] = str(sv or "")
                    status["reconciled"] = healed
                return status

        if spec.peer_relay and self.peer_trinity_resolver is not None:
            p_base, pt = peer_state_getter()
            if p_base and isinstance(pt, dict):
                remote_st = (pt.get("adapters") or {}).get(spec.name)
                if not isinstance(remote_st, dict):
                    remote_st = pt.get(spec.name)
                if isinstance(remote_st, dict) and remote_st.get("online"):
                    return {**remote_st, "via": "PHANTOM_5MS", "endpoint": p_base}

        return {"online": False}

    def _poll_worker(self) -> None:
        with self._lock:
            specs = [copy.deepcopy(spec) for spec in self._adapters.values()]

        peer_cache: dict[str, Any] = {"fetched": False, "base": "", "data": None}

        def _get_peer_status() -> tuple[str, dict[str, Any] | None]:
            if not peer_cache["fetched"]:
                peer_cache["fetched"] = True
                if self.peer_trinity_resolver is not None:
                    p_base = str(self.peer_trinity_resolver() or "").rstrip("/")
                    peer_cache["base"] = p_base
                    if p_base:
                        peer_cache["data"] = _fetch_json(f"{p_base}/api/trinity/status", timeout_s=1.5)
            return str(peer_cache["base"]), peer_cache["data"]

        results: dict[str, dict[str, Any]] = {}
        burn_values: list[float] = []
        output_values: list[int] = []
        try:
            for spec in specs:
                st = self._poll_single_adapter(spec, _get_peer_status)
                results[spec.name] = st
                if st.get("online"):
                    bval = st.get(spec.burn_rate_field)
                    if isinstance(bval, (int, float)) and not isinstance(bval, bool):
                        burn_values.append(float(bval))
                    oval = st.get(spec.outputs_field)
                    if isinstance(oval, (int, float)) and not isinstance(oval, bool):
                        output_values.append(int(oval))
        finally:
            with self._lock:
                for name in list(self._adapters.keys()):
                    if name in results:
                        self._cache[name] = results[name]
                    else:
                        self._cache.setdefault(name, {"online": False})
                if burn_values:
                    self._kill_switch["quota_burn_rate_pct_hr"] = round(max(burn_values), 2)
                if output_values:
                    self._kill_switch["recent_outputs"] = sum(output_values)
                self._cache_ts = time.monotonic()
                self._busy = False

    def poll_now(self) -> dict[str, Any]:
        """Synchronously poll all registered adapters and return the fresh snapshot."""
        self._poll_worker()
        return self.snapshot(refresh=False)

    def refresh_async(self, *, ttl_s: float = 5.0) -> None:
        if self._ephemeral_mode:
            return
        now = time.monotonic()
        with self._lock:
            if (now - self._cache_ts) < ttl_s or self._busy:
                return
            self._busy = True
        threading.Thread(target=self._poll_worker, daemon=True, name="trinity-bridge-poll").start()

    def snapshot(self, *, refresh: bool = True) -> dict[str, Any]:
        if refresh:
            self.refresh_async()
        gov = self.governor.evaluate_state()
        with self._lock:
            adapters_snap = {name: dict(st) for name, st in self._cache.items()}
            ks = dict(self._kill_switch)
        overmind_meta = {}
        if self.overmind is not None:
            overmind_meta = {
                "crdt": self.overmind.crdt.snapshot(),
                "pulse_seq": self.overmind.pulse.stats().get("latest_seq", 0),
                "flight_frames": self.overmind.flight_recorder.status().get("buffered_frames", 0),
            }
        return {
            "ok": True,
            "version": "15.0-trinity",
            "bridge_rev": "18.0-overmind",
            "governor": gov,
            "kill_switch": ks,
            "tquota": dict(adapters_snap.get("tquota", {"online": False})),
            "radar": dict(adapters_snap.get("radar", {"online": False})),
            "adapters": adapters_snap,
            **overmind_meta,
        }

    def list_proofs(self, limit: int = 20, adapter: str | None = None) -> dict[str, Any]:
        cap = max(1, min(100, int(limit or 20)))
        target_name = str(adapter).strip() if adapter is not None else None
        with self._lock:
            proof_specs = [
                copy.deepcopy(spec)
                for spec in self._adapters.values()
                if "proofs" in spec.roles and spec.proofs_endpoint
                and (target_name is None or spec.name == target_name)
            ]

        if target_name is not None and not proof_specs:
            return {
                "ok": False,
                "adapter": target_name,
                "proofs": [],
                "count": 0,
                "error": f"adapter_proofs_not_configured:{target_name}",
            }

        for spec in proof_specs:
            ep_path = (
                spec.proofs_endpoint.replace("{limit}", str(cap))
                if "{limit}" in spec.proofs_endpoint
                else spec.proofs_endpoint
            )
            for base in [u for u in (spec.base_url, *spec.fallback_urls) if u]:
                res = _fetch_json(f"{base}{ep_path}", timeout_s=2.0)
                if isinstance(res, dict) and res.get("ok", True):
                    items = res.get("proofs")
                    if items is None:
                        items = res.get("receipts")
                    if items is None:
                        items = res.get("items")
                    if items is None and isinstance(res.get("raw"), list):
                        items = res["raw"]
                    if not isinstance(items, list):
                        items = []
                    items = items[:cap]
                    out: dict[str, Any] = {
                        "ok": True,
                        "adapter": spec.name,
                        "endpoint": base,
                        "via": "direct",
                        **res,
                    }
                    out.setdefault("proofs", items)
                    out.setdefault("count", len(items))
                    return out

        if self.peer_trinity_resolver is not None:
            p_base = str(self.peer_trinity_resolver() or "").rstrip("/")
            if p_base:
                qs = f"limit={cap}"
                if target_name:
                    qs += f"&adapter={urllib.parse.quote(target_name)}"
                res = _fetch_json(f"{p_base}/api/trinity/proofs?{qs}", timeout_s=2.0)
                if isinstance(res, dict) and res.get("ok"):
                    return {"ok": True, "endpoint": p_base, "via": "PHANTOM_5MS", **res}

        return {
            "ok": False,
            **({"adapter": target_name} if target_name else {}),
            "proofs": [],
            "count": 0,
            "error": "adapter_proofs_unreachable" if target_name else "proofs_unreachable",
        }

    def pulse_summary(self) -> dict[str, Any]:
        snap = self.snapshot(refresh=True)
        adapters = snap.get("adapters") or {}
        return {
            "governor_mode": snap["governor"]["mode"],
            "accept_heavy_jobs": snap["governor"]["accept_heavy_jobs"],
            "kill_switch": snap["kill_switch"]["active"],
            "tquota_online": snap["tquota"].get("online", False),
            "tquota_quarantined": snap["tquota"].get("quarantined_count", 0),
            "colab_cu": snap["tquota"].get("colab_remaining_cu", 0.0),
            "radar_online": snap["radar"].get("online", False),
            "radar_learned_rules": snap["radar"].get("learned_rules", 0),
            "radar_crystals": snap["radar"].get("patch_crystals", 0),
            "colab_queued": snap["radar"].get("colab_queued", 0),
            "adapters_online": sum(1 for st in adapters.values() if isinstance(st, dict) and st.get("online")),
            "adapters_total": len(adapters),
        }
