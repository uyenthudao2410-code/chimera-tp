"""TrinityCommandBridge — non-blocking cross-stack aggregator (Chimera-TP x Tquota x Radar x Colab)."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import threading
import time
from typing import Any, Callable
import urllib.request

from .host_governor import HostYieldGovernor


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


class TrinityCommandBridge:
    """Aggregates live telemetry from Tquota, Radar, HostYieldGovernor, and enforces the ROI Kill-Switch."""

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
    ) -> None:
        self.governor = governor
        self.tquota_admin_url = str(tquota_admin_url or "").rstrip("/")
        self.radar_url = str(radar_url or "").rstrip("/")
        self.peer_radar_url = str(peer_radar_url or "").rstrip("/")
        self.peer_trinity_resolver = peer_trinity_resolver
        self._ephemeral_mode = bool(ephemeral_mode)
        self._on_flow = on_flow

        self._lock = threading.Lock()
        self._cache_ts: float = 0.0
        self._busy: bool = False
        self._cache: dict[str, Any] = {
            "tquota": {"online": False},
            "radar": {"online": False},
        }
        self._kill_switch: dict[str, Any] = {
            "active": False,
            "reason": "",
            "triggered_at": None,
            "auto_triggered": False,
            "quota_burn_rate_pct_hr": 0.0,
            "recent_outputs": 0,
            "max_burn_rate_pct_hr": 12.0,
        }

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
        with self._lock:
            self._kill_switch["active"] = bool(active)
            self._kill_switch["reason"] = str(reason or ("manual_operator_halt" if active else "cleared"))
            self._kill_switch["triggered_at"] = datetime.now(timezone.utc).isoformat() if active else None
            self._kill_switch["auto_triggered"] = bool(auto_triggered) if active else False
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
            ctrl_payload = {
                "paused": bool(active),
                "reason": snap["reason"],
                "source": "chimera_kill_switch",
            }
            # Actuate local Radar (and peer Radar direct if configured on controller)
            for label, base in (("local_radar", self.radar_url), ("peer_radar", self.peer_radar_url)):
                if not base:
                    continue
                res = _post_json(f"{base}/api/godmode/control", ctrl_payload, timeout_s=1.2)
                if isinstance(res, dict) and res.get("ok"):
                    actuation["targets"].append({"target": label, "endpoint": base, "paused": res.get("paused")})
                    actuation["ok"] = True
                    actuation["mode"] = "direct"

            # Relay over PHANTOM_5MS peer Chimera bridge if available on controller
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
                        },
                        timeout_s=1.5,
                    )
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

    def _poll_worker(self) -> None:
        tq_out: dict[str, Any] = {"online": False}
        rd_out: dict[str, Any] = {"online": False}
        try:
            if self.tquota_admin_url:
                hive = _fetch_json(f"{self.tquota_admin_url}/api/hive/status", timeout_s=1.2)
                tc = _fetch_json(f"{self.tquota_admin_url}/api/time-crystal/status", timeout_s=1.2)
                if hive or tc:
                    tq_out = {
                        "online": True,
                        "gossip_errors": int((hive or {}).get("gossipErrors", 0)),
                        "phantom_routes": int((hive or {}).get("phantomRoutes", 0)),
                        "cache_affinity_routes": int((hive or {}).get("cacheAffinityRoutes", 0)),
                        "quarantined_count": int((tc or hive or {}).get("quarantinedCount", 0)),
                        "healthy_count": int((tc or {}).get("healthyCount", 0)),
                        "expiring_soon": int((tc or {}).get("expiringSoonCount", 0)),
                        "colab_remaining_cu": float((tc or {}).get("totalRemainingColabCU", 0.0)),
                        "cross_family_target": (hive or {}).get("crossFamilyTarget"),
                    }
            for base in [u for u in (self.radar_url, self.peer_radar_url) if u]:
                gm = _fetch_json(f"{base}/api/godmode/status", timeout_s=1.2)
                if gm and gm.get("ok"):
                    rd_out = {
                        "online": True,
                        "endpoint": base,
                        "learned_rules": int(gm.get("learned_rules_count", 0)),
                        "patch_crystals": int(gm.get("patch_crystals_count", 0)),
                        "colab_queued": int(((gm.get("colab") or {}).get("queued_count", 0))),
                        "colab_completed": int(((gm.get("colab") or {}).get("completed_count", 0))),
                        "salvageable_runs": int(((gm.get("salvage") or {}).get("salvageable_count", 0))),
                        "engines_ready": int(len(gm.get("engines") or [])),
                    }
                    break
            if not rd_out.get("online") and self.peer_trinity_resolver is not None:
                p_base = str(self.peer_trinity_resolver() or "").rstrip("/")
                if p_base:
                    pt = _fetch_json(f"{p_base}/api/trinity/status", timeout_s=1.5)
                    pr = (pt or {}).get("radar")
                    if isinstance(pr, dict) and pr.get("online"):
                        rd_out = {**pr, "via": "PHANTOM_5MS", "endpoint": p_base}
        finally:
            with self._lock:
                self._cache = {"tquota": tq_out, "radar": rd_out}
                self._cache_ts = time.monotonic()
                self._busy = False

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
            cached = {"tquota": dict(self._cache["tquota"]), "radar": dict(self._cache["radar"])}
            ks = dict(self._kill_switch)
        return {
            "ok": True,
            "version": "15.0-trinity",
            "bridge_rev": "17.0-bidirectional",
            "governor": gov,
            "kill_switch": ks,
            "tquota": cached["tquota"],
            "radar": cached["radar"],
        }

    def list_proofs(self, *, limit: int = 20) -> dict[str, Any]:
        cap = max(1, min(100, int(limit or 20)))
        for base in [u for u in (self.radar_url, self.peer_radar_url) if u]:
            res = _fetch_json(f"{base}/api/godmode/necromancer/proofs?limit={cap}", timeout_s=2.0)
            if isinstance(res, dict) and res.get("ok"):
                return {"ok": True, "endpoint": base, "via": "direct", **res}
        if self.peer_trinity_resolver is not None:
            p_base = str(self.peer_trinity_resolver() or "").rstrip("/")
            if p_base:
                res = _fetch_json(f"{p_base}/api/trinity/proofs?limit={cap}", timeout_s=2.0)
                if isinstance(res, dict) and res.get("ok"):
                    return {"ok": True, "endpoint": p_base, "via": "PHANTOM_5MS", **res}
        return {"ok": False, "proofs": [], "count": 0, "error": "radar_proofs_unreachable"}

    def pulse_summary(self) -> dict[str, Any]:
        snap = self.snapshot(refresh=True)
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
        }
