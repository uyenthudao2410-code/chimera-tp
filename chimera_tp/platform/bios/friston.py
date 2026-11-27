"""CHIMERA-FRISTON (BIOS Idea #2): Active Inference Generative World-Model.

Maintains a compact (< 64 KB JSON) online State-Space / Welford-Kalman +
context-conditioned Markov generative model across 3 coupled domains:
  (a) 4-hemisphere hardware telemetry (CPU, RAM/RSS, GPU, svhome load/temp, RTT, disk IO)
  (b) AI swarm cadence (token rate, cache hit ratio, active streams)
  (c) Host work context (``cad``, ``coding``, ``research``, ``idle``, ``general``)

Computes context-conditioned Variational Free Energy / Surprise
``-ln P(obs | context_model)`` with per-feature Z-score residuals so expected high load
(e.g., AutoCAD active + high GPU/CPU) yields LOW surprise while anomalous stealth spikes
(e.g., idle context + unexpected CPU/disk spike) yield HIGH surprise.

100% Python stdlib, Zero-NumPy, lazy-loaded, strictly Law 2 & Law 6 compliant.
"""

from __future__ import annotations

import json
import math
import threading
import time
from typing import Any, Mapping

KNOWN_CONTEXTS: tuple[str, ...] = ("cad", "coding", "research", "idle", "general")
MAX_STATE_BYTES = 60 * 1024  # Strictly under 64 KiB serialized JSON ceiling
_MAX_FEATURES_PER_CONTEXT = 24
_MAX_DYNAMIC_CONTEXTS = 10
_TWO_PI = 2.0 * math.pi

# Domain-grounded Bayesian priors: feature -> (mean, std) per context.
# Minimum variance floors ensure numerical stability without masking real anomalies.
_FEATURE_MIN_STD: dict[str, float] = {
    "cpu_pct": 3.5,
    "ram_pct": 4.0,
    "rss_mb": 4.0,
    "gpu_pct": 3.0,
    "svhome_load": 0.18,
    "svhome_temp_c": 2.5,
    "rtt_ms": 2.0,
    "disk_io_mb_s": 2.0,
    "token_rate": 2.0,
    "cache_hit_ratio": 0.08,
    "active_streams": 0.5,
}

_CONTEXT_PRIORS: dict[str, dict[str, tuple[float, float]]] = {
    "cad": {
        "cpu_pct": (62.0, 18.0),
        "ram_pct": (58.0, 14.0),
        "rss_mb": (48.0, 12.0),
        "gpu_pct": (68.0, 18.0),
        "svhome_load": (0.45, 0.30),
        "svhome_temp_c": (47.0, 5.0),
        "rtt_ms": (7.0, 4.0),
        "disk_io_mb_s": (35.0, 22.0),
        "token_rate": (8.0, 12.0),
        "cache_hit_ratio": (0.75, 0.18),
        "active_streams": (1.0, 1.0),
    },
    "coding": {
        "cpu_pct": (38.0, 16.0),
        "ram_pct": (55.0, 14.0),
        "rss_mb": (52.0, 12.0),
        "gpu_pct": (18.0, 12.0),
        "svhome_load": (0.70, 0.40),
        "svhome_temp_c": (50.0, 6.0),
        "rtt_ms": (8.0, 5.0),
        "disk_io_mb_s": (26.0, 18.0),
        "token_rate": (55.0, 30.0),
        "cache_hit_ratio": (0.76, 0.14),
        "active_streams": (3.0, 2.0),
    },
    "research": {
        "cpu_pct": (26.0, 14.0),
        "ram_pct": (50.0, 14.0),
        "rss_mb": (46.0, 12.0),
        "gpu_pct": (12.0, 10.0),
        "svhome_load": (0.55, 0.35),
        "svhome_temp_c": (48.0, 5.0),
        "rtt_ms": (9.0, 6.0),
        "disk_io_mb_s": (14.0, 12.0),
        "token_rate": (40.0, 25.0),
        "cache_hit_ratio": (0.68, 0.16),
        "active_streams": (2.0, 1.5),
    },
    "idle": {
        "cpu_pct": (6.0, 4.5),
        "ram_pct": (38.0, 10.0),
        "rss_mb": (42.0, 10.0),
        "gpu_pct": (4.0, 3.5),
        "svhome_load": (0.35, 0.25),
        "svhome_temp_c": (45.0, 4.0),
        "rtt_ms": (6.0, 3.5),
        "disk_io_mb_s": (2.0, 2.5),
        "token_rate": (1.0, 2.5),
        "cache_hit_ratio": (0.85, 0.14),
        "active_streams": (0.2, 0.5),
    },
    "general": {
        "cpu_pct": (30.0, 22.0),
        "ram_pct": (50.0, 16.0),
        "rss_mb": (48.0, 14.0),
        "gpu_pct": (22.0, 20.0),
        "svhome_load": (0.55, 0.40),
        "svhome_temp_c": (48.0, 6.0),
        "rtt_ms": (8.0, 6.0),
        "disk_io_mb_s": (18.0, 18.0),
        "token_rate": (25.0, 28.0),
        "cache_hit_ratio": (0.75, 0.18),
        "active_streams": (1.5, 1.5),
    },
}

# Prior pseudo-count weight so initial domain beliefs remain grounded while adapting smoothly
_PRIOR_WEIGHT = 8.0


def _flatten_numeric_obs(obs: Mapping[str, Any]) -> dict[str, float]:
    """Extract numeric telemetry features from flat or 1-level nested dicts."""
    out: dict[str, float] = {}
    for k, v in obs.items():
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)):
            fv = float(v)
            if math.isfinite(fv):
                out[str(k)] = fv
        elif isinstance(v, Mapping):
            for sub_k, sub_v in v.items():
                if isinstance(sub_v, bool):
                    continue
                if isinstance(sub_v, (int, float)):
                    fv = float(sub_v)
                    if math.isfinite(fv):
                        out[str(sub_k)] = fv
    return out


def _normalize_context(context: str | None) -> str:
    raw = str(context or "general").strip().lower()
    return raw or "general"


class ActiveInferenceBrain:
    """Online context-conditioned Welford-Kalman + Markov generative world-model (< 64 KB state)."""

    def __init__(self, *, prior_weight: float = _PRIOR_WEIGHT) -> None:
        self._lock = threading.RLock()
        self._prior_weight = max(1.0, float(prior_weight))
        # models[ctx][feat] = {"m": mean, "v": var, "vel": dx/dt, "n": count, "last": val, "ts": ts}
        self._models: dict[str, dict[str, dict[str, float]]] = {}
        # Markov transition counts: transitions[from_ctx][to_ctx] = count
        self._transitions: dict[str, dict[str, float]] = {}
        self._last_context: str = "general"
        self._last_ts: float = 0.0
        self._obs_count: int = 0
        self._last_surprise: float = 0.0
        self._init_default_priors()

    def _init_default_priors(self) -> None:
        for ctx, feats in _CONTEXT_PRIORS.items():
            self._models[ctx] = {
                f: {
                    "m": float(mu),
                    "v": float(std * std),
                    "vel": 0.0,
                    "n": self._prior_weight,
                    "last": float(mu),
                    "ts": 0.0,
                }
                for f, (mu, std) in feats.items()
            }
            # Weakly sticky Dirichlet-smoothed transition prior
            self._transitions[ctx] = {
                other: (3.0 if other == ctx else 0.5) for other in KNOWN_CONTEXTS
            }

    def _ensure_context_locked(self, ctx: str) -> dict[str, dict[str, float]]:
        if ctx in self._models:
            return self._models[ctx]
        # Respect dynamic context bound to keep state strictly < 64 KB
        dynamic = [c for c in self._models if c not in KNOWN_CONTEXTS]
        if len(dynamic) >= _MAX_DYNAMIC_CONTEXTS:
            # Evict least-observed dynamic context
            victim = min(
                dynamic,
                key=lambda c: sum(s["n"] for s in self._models[c].values()),
            )
            self._models.pop(victim, None)
            self._transitions.pop(victim, None)
        base = _CONTEXT_PRIORS["general"]
        self._models[ctx] = {
            f: {
                "m": float(mu),
                "v": float(std * std),
                "vel": 0.0,
                "n": self._prior_weight * 0.5,
                "last": float(mu),
                "ts": 0.0,
            }
            for f, (mu, std) in base.items()
        }
        self._transitions[ctx] = {other: (2.0 if other == ctx else 0.4) for other in self._models}
        for other in self._transitions:
            self._transitions[other].setdefault(ctx, 0.4)
        return self._models[ctx]

    def _ensure_feature_locked(self, ctx_model: dict[str, dict[str, float]], feat: str, val: float) -> dict[str, float]:
        if feat in ctx_model:
            return ctx_model[feat]
        if len(ctx_model) >= _MAX_FEATURES_PER_CONTEXT:
            # Evict least-observed non-core feature
            removable = [f for f in ctx_model if f not in _FEATURE_MIN_STD]
            if removable:
                victim = min(removable, key=lambda f: ctx_model[f]["n"])
                ctx_model.pop(victim, None)
        init_std = max(_FEATURE_MIN_STD.get(feat, 1.0), abs(val) * 0.25 + 1.0)
        slot = {
            "m": float(val),
            "v": float(init_std * init_std),
            "vel": 0.0,
            "n": 2.0,
            "last": float(val),
            "ts": 0.0,
        }
        ctx_model[feat] = slot
        return slot

    def _score_obs_locked(
        self,
        flat_obs: dict[str, float],
        ctx: str,
        *,
        ts: float,
        learn: bool,
    ) -> dict[str, Any]:
        ctx_model = self._ensure_context_locked(ctx)
        z_scores: dict[str, float] = {}
        excess_energies: list[float] = []
        raw_nll_total = 0.0
        anomalous: list[str] = []

        for feat, val in flat_obs.items():
            slot = self._ensure_feature_locked(ctx_model, feat, val)
            min_std = _FEATURE_MIN_STD.get(feat, 1.0)
            var = max(slot["v"], min_std * min_std)
            std = math.sqrt(var)

            # One-step Kalman predictive mean (tiny damped velocity projection if recent)
            dt = (ts - slot["ts"]) if (slot["ts"] > 0.0 and ts > slot["ts"]) else 0.0
            if 0.0 < dt <= 30.0:
                pred_mean = slot["m"] + slot["vel"] * min(dt, 5.0) * 0.25
            else:
                pred_mean = slot["m"]

            z = (val - pred_mean) / std
            z_clamped = max(-12.0, min(12.0, z))
            # Excess surprise in nats relative to mode: -ln(p(x)/p(mu)) = 0.5 * z^2
            e_nats = 0.5 * z_clamped * z_clamped
            # Full Gaussian negative log-likelihood: -ln N(x | mu, var)
            nll = 0.5 * math.log(_TWO_PI * var) + e_nats

            z_scores[feat] = round(z, 4)
            excess_energies.append(e_nats)
            raw_nll_total += nll
            if abs(z) >= 2.5:
                anomalous.append(feat)

            if learn:
                # Precision-weighted robust Kalman/Welford update:
                # High-surprise outliers have attenuated gain so stealth spikes never poison baseline!
                base_gain = max(0.03, min(0.22, 1.0 / (slot["n"] + 1.0)))
                robust_gain = base_gain / (1.0 + 0.5 * z_clamped * z_clamped)
                diff = val - slot["m"]
                new_m = slot["m"] + robust_gain * diff
                # Online variance tracking with exponential forgetting
                new_v = (1.0 - robust_gain) * var + robust_gain * (diff * diff)
                slot["m"] = new_m
                slot["v"] = max(min_std * min_std, new_v)
                if 0.1 <= dt <= 300.0:
                    inst_vel = (val - slot["last"]) / dt
                    # Clamp extreme instantaneous jumps
                    max_vel = std * 0.5
                    inst_vel = max(-max_vel, min(max_vel, inst_vel))
                    slot["vel"] = 0.70 * slot["vel"] + 0.30 * inst_vel
                else:
                    slot["vel"] *= 0.85
                slot["n"] = min(10000.0, slot["n"] + (1.0 / (1.0 + 0.25 * z_clamped * z_clamped)))
                slot["last"] = val
                slot["ts"] = ts

        if excess_energies:
            mean_e = sum(excess_energies) / len(excess_energies)
            max_e = max(excess_energies)
            # Blend mean and peak residual so single-axis stealth spikes stand out cleanly
            free_energy_nats = 0.60 * mean_e + 0.40 * max_e
        else:
            free_energy_nats = 0.0

        # Smooth monotonic normalization to [0, 1]
        surprise = 1.0 - math.exp(-free_energy_nats / 2.25)
        surprise = max(0.0, min(1.0, surprise))

        if surprise >= 0.65:
            regime = "anomalous"
        elif surprise >= 0.30:
            regime = "elevated"
        else:
            regime = "expected"

        if learn:
            if self._obs_count > 0:
                row = self._transitions.setdefault(self._last_context, {})
                row[ctx] = row.get(ctx, 0.0) + 1.0
            self._last_context = ctx
            self._last_ts = ts
            self._obs_count += 1
            self._last_surprise = surprise

        return {
            "context": ctx,
            "surprise": round(surprise, 6),
            "free_energy_nats": round(free_energy_nats, 6),
            "raw_nll_nats": round(raw_nll_total, 6),
            "z_scores": z_scores,
            "anomalous_features": sorted(anomalous),
            "regime": regime,
            "observation_count": self._obs_count,
        }

    def observe(
        self,
        obs: Mapping[str, Any],
        context: str = "general",
        *,
        ts: float | None = None,
        learn: bool = True,
    ) -> dict[str, Any]:
        """Observe telemetry in a context and compute Variational Free Energy / Surprise."""
        flat = _flatten_numeric_obs(obs or {})
        ctx = _normalize_context(context)
        now = float(ts) if ts is not None else time.time()
        with self._lock:
            return self._score_obs_locked(flat, ctx, ts=now, learn=bool(learn))

    def _markov_distribution_locked(self, start_ctx: str, horizon_s: float) -> dict[str, float]:
        contexts = sorted(self._models.keys())
        dist = {c: (1.0 if c == start_ctx else 0.0) for c in contexts}
        # One Markov transition step represents ~300s of human/workstation context inertia
        steps = max(0, min(48, int(round(max(0.0, horizon_s) / 300.0))))
        if steps == 0:
            return dist

        # Build row-stochastic transition matrix
        matrix: dict[str, dict[str, float]] = {}
        for src in contexts:
            row = self._transitions.get(src, {})
            total = sum(row.get(dst, 0.1) for dst in contexts)
            if total <= 0.0:
                matrix[src] = {dst: 1.0 / len(contexts) for dst in contexts}
            else:
                matrix[src] = {dst: row.get(dst, 0.1) / total for dst in contexts}

        for _ in range(steps):
            nxt = {c: 0.0 for c in contexts}
            for src, p_src in dist.items():
                if p_src <= 0.0:
                    continue
                row = matrix[src]
                for dst, p_t in row.items():
                    nxt[dst] += p_src * p_t
            dist = nxt
        return {c: round(p, 5) for c, p in dist.items()}

    def predict(self, horizon_s: float, context: str | None = None) -> dict[str, Any]:
        """Multi-horizon state forecast (e.g. 10s, 300s, 7200s) with 95% confidence intervals."""
        h = max(0.0, float(horizon_s))
        with self._lock:
            ctx = _normalize_context(context if context is not None else self._last_context)
            self._ensure_context_locked(ctx)
            ctx_dist = self._markov_distribution_locked(ctx, h)

            # Collect canonical features visible across the active context
            features = sorted(self._models[ctx].keys())
            predictions: dict[str, dict[str, float]] = {}

            # Damped short-term trend weight decays smoothly after ~90s
            vel_horizon = 60.0 * (1.0 - math.exp(-h / 60.0)) if h > 0.0 else 0.0
            # Uncertainty inflation grows monotonically with horizon
            horizon_scale = math.sqrt(1.0 + math.log1p(h / 15.0) * 0.45)

            for feat in features:
                min_std = _FEATURE_MIN_STD.get(feat, 1.0)
                # Law of total expectation + law of total variance across Markov context mixture
                mix_mean = 0.0
                second_moment = 0.0
                for c_name, prob in ctx_dist.items():
                    if prob <= 1e-6:
                        continue
                    slot = self._models[c_name].get(feat)
                    if slot is None:
                        continue
                    if c_name == ctx:
                        c_mean = slot["m"] + slot["vel"] * vel_horizon
                    else:
                        c_mean = slot["m"]
                    c_var = max(slot["v"], min_std * min_std)
                    mix_mean += prob * c_mean
                    second_moment += prob * (c_var + c_mean * c_mean)

                mix_var = max(min_std * min_std, second_moment - mix_mean * mix_mean)
                pred_std = math.sqrt(mix_var) * horizon_scale
                margin = 1.96 * pred_std

                # Clamp non-negative physical quantities gently at lower bound 0
                ci_low = mix_mean - margin
                if feat in _FEATURE_MIN_STD:
                    ci_low = max(0.0, ci_low)
                ci_high = mix_mean + margin
                if feat in ("cpu_pct", "ram_pct", "gpu_pct"):
                    ci_high = min(100.0, ci_high)
                    mix_mean = max(0.0, min(100.0, mix_mean))
                elif feat == "cache_hit_ratio":
                    ci_high = min(1.0, ci_high)
                    mix_mean = max(0.0, min(1.0, mix_mean))

                predictions[feat] = {
                    "mean": round(mix_mean, 4),
                    "std": round(pred_std, 4),
                    "ci_low": round(ci_low, 4),
                    "ci_high": round(ci_high, 4),
                }

            rss_pred = predictions.get("rss_mb", {}).get("ci_high", 0.0)
            sv_temp_pred = predictions.get("svhome_temp_c", {}).get("ci_high", 0.0)
            sv_load_pred = predictions.get("svhome_load", {}).get("ci_high", 0.0)
            cache_pred = predictions.get("cache_hit_ratio", {}).get("mean", 1.0)

            return {
                "context": ctx,
                "horizon_s": h,
                "context_distribution": ctx_dist,
                "predictions": predictions,
                "predicted_pressure": {
                    "rss_risk": bool(rss_pred >= 72.0),
                    "svhome_thermal_risk": bool(sv_temp_pred >= 68.0 or sv_load_pred >= 1.7),
                    "cache_cliff_risk": bool(cache_pred < 0.55),
                },
            }

    def plan_active_inference(
        self,
        obs: Mapping[str, Any],
        context: str = "general",
    ) -> list[dict[str, Any]]:
        """Generate Law-2 & Law-6 safe anticipatory actions ranked by Expected Free Energy gain."""
        flat = _flatten_numeric_obs(obs or {})
        ctx = _normalize_context(context)
        now = time.time()
        with self._lock:
            scored = self._score_obs_locked(flat, ctx, ts=now, learn=False)
            forecast_5m = self.predict(300.0, context=ctx)

        surprise = scored["surprise"]
        z_scores = scored["z_scores"]
        actions: list[dict[str, Any]] = []

        def _add(
            action: str,
            efe_gain: float,
            priority: str,
            reason: str,
            hormone_hint: dict[str, float],
            requires_approval: bool = False,
        ) -> None:
            actions.append(
                {
                    "action": action,
                    "efe_gain": round(max(0.01, float(efe_gain)), 4),
                    "priority": priority,
                    "reason": reason,
                    "context": ctx,
                    "hormone_hint": hormone_hint,
                    "law2_compliant": True,
                    "auto_activated": False,
                    "requires_human_approval": bool(requires_approval),
                }
            )

        # 1. Anomalous stealth spike during idle or unexpected resource surge -> read-only audit
        if surprise >= 0.65 and (
            ctx == "idle"
            or z_scores.get("cpu_pct", 0.0) >= 3.0
            or z_scores.get("disk_io_mb_s", 0.0) >= 3.0
        ):
            _add(
                "isolate_anomalous_process_audit",
                efe_gain=1.2 + 2.5 * surprise,
                priority="high",
                reason=(
                    f"High context-conditioned surprise ({surprise:.2f}) in '{ctx}' "
                    f"on features {scored['anomalous_features']}; capture read-only telemetry audit."
                ),
                hormone_hint={"cytokine": 0.35, "adrenaline": 0.30},
                requires_approval=True,
            )

        # 2. Interactive heavy context (CAD) or acute pressure -> cooperative adrenaline boost
        cpu_v = flat.get("cpu_pct", 0.0)
        gpu_v = flat.get("gpu_pct", 0.0)
        if (ctx == "cad" and (cpu_v >= 55.0 or gpu_v >= 55.0)) or surprise >= 0.60:
            _add(
                "raise_endocrine_adrenaline",
                efe_gain=0.85 + 0.9 * max(surprise, (cpu_v + gpu_v) / 200.0),
                priority="high" if ctx == "cad" else "medium",
                reason=(
                    f"Protect interactive responsiveness in '{ctx}' cooperatively via Endocrine "
                    f"VIP posture without OS throttling."
                ),
                hormone_hint={"adrenaline": 0.35},
            )

        # 3. AI swarm cadence approaching prefix cache cliff -> pre-cook compaction crystal
        tok_rate = flat.get("token_rate", 0.0)
        cache_hit = flat.get("cache_hit_ratio", 1.0)
        streams = flat.get("active_streams", 0.0)
        if tok_rate >= 65.0 or cache_hit < 0.58 or streams >= 4.0:
            gain = 0.70 + max(0.0, 0.70 - cache_hit) * 2.0 + (tok_rate / 150.0)
            _add(
                "pre_cook_compaction_crystal",
                efe_gain=gain,
                priority="medium",
                reason=(
                    f"Swarm cadence (tokens/s={tok_rate:.1f}, cache_hit={cache_hit:.2f}, "
                    f"streams={streams:.0f}) risks context cliff; pre-cook compact summary crystal."
                ),
                hormone_hint={"dopamine": 0.10},
            )

        # 4. Law 7 RSS cap or Law 3 svhome thermal/load pressure -> shed CHIMERA cold cache
        rss_mb = flat.get("rss_mb", 0.0)
        sv_temp = flat.get("svhome_temp_c", 0.0)
        sv_load = flat.get("svhome_load", 0.0)
        if (
            rss_mb >= 64.0
            or sv_temp >= 64.0
            or sv_load >= 1.55
            or forecast_5m["predicted_pressure"]["rss_risk"]
            or forecast_5m["predicted_pressure"]["svhome_thermal_risk"]
        ):
            gain = 1.0 + max(0.0, (rss_mb - 60.0) / 15.0) + max(0.0, (sv_temp - 62.0) / 8.0)
            _add(
                "cool_shed_cold_cache",
                efe_gain=gain,
                priority="high",
                reason=(
                    f"Approaching Law 3/7 headroom ceiling (rss={rss_mb:.1f} MiB, "
                    f"svhome_temp={sv_temp:.1f}C, svhome_load={sv_load:.2f}); shed cold internal caches."
                ),
                hormone_hint={"cortisol": 0.20},
            )

        # 5. Sustained heavy compute / peer load -> pre-warm budgeted Colab T4 burst path
        ram_pct = flat.get("ram_pct", 0.0)
        if (cpu_v >= 82.0 and ctx != "idle") or ram_pct >= 84.0 or sv_load >= 1.65:
            _add(
                "pre_warm_colab_t4",
                efe_gain=0.95 + max(0.0, (cpu_v - 75.0) / 50.0),
                priority="medium",
                reason=(
                    f"Heavy sustained load (cpu={cpu_v:.1f}%, ram={ram_pct:.1f}%, "
                    f"svhome_load={sv_load:.2f}); stage CU-budgeted Colab T4 offload readiness."
                ),
                hormone_hint={"adrenaline": 0.15},
                requires_approval=True,
            )

        # 6. Calm idle window -> sleep-time consolidation
        if ctx == "idle" and surprise < 0.25 and cpu_v < 18.0:
            _add(
                "enter_melatonin_sleep_compaction",
                efe_gain=0.55,
                priority="low",
                reason="Calm expected idle window detected; eligible for quiet sleep-time consolidation.",
                hormone_hint={"melatonin": 0.25},
            )

        actions.sort(key=lambda item: item["efe_gain"], reverse=True)
        return actions

    def _compact_state_locked(self) -> dict[str, Any]:
        models_out: dict[str, dict[str, list[float]]] = {}
        for ctx, feats in self._models.items():
            models_out[ctx] = {
                f: [
                    round(s["m"], 5),
                    round(s["v"], 5),
                    round(s["vel"], 5),
                    round(s["n"], 3),
                    round(s["last"], 5),
                    round(s["ts"], 2),
                ]
                for f, s in feats.items()
            }
        trans_out = {
            src: {dst: round(cnt, 3) for dst, cnt in row.items()}
            for src, row in self._transitions.items()
        }
        state: dict[str, Any] = {
            "version": 1,
            "prior_weight": round(self._prior_weight, 3),
            "last_context": self._last_context,
            "last_ts": round(self._last_ts, 2),
            "obs_count": int(self._obs_count),
            "last_surprise": round(self._last_surprise, 6),
            "models": models_out,
            "transitions": trans_out,
        }
        # Enforce strict < 64 KB ceiling by trimming non-core dynamic entries if ever oversized
        raw = json.dumps(state, separators=(",", ":")).encode("utf-8")
        if len(raw) > MAX_STATE_BYTES:
            for ctx in list(state["models"].keys()):
                if ctx not in KNOWN_CONTEXTS:
                    state["models"].pop(ctx, None)
                    state["transitions"].pop(ctx, None)
                    raw = json.dumps(state, separators=(",", ":")).encode("utf-8")
                    if len(raw) <= MAX_STATE_BYTES:
                        break
        if len(raw) > MAX_STATE_BYTES:
            for ctx, feats in state["models"].items():
                for f in list(feats.keys()):
                    if f not in _FEATURE_MIN_STD:
                        feats.pop(f, None)
        return state

    def to_state(self) -> dict[str, Any]:
        """Serialize full world-model into a compact JSON-ready dict (< 64 KB)."""
        with self._lock:
            return self._compact_state_locked()

    def state_bytes_size(self) -> int:
        """Return exact UTF-8 byte length of compact JSON serialized state."""
        return len(json.dumps(self.to_state(), separators=(",", ":")).encode("utf-8"))

    def load_state(self, state: Mapping[str, Any]) -> None:
        """Restore world-model state from a dictionary produced by ``to_state()``."""
        with self._lock:
            self._prior_weight = max(1.0, float(state.get("prior_weight", _PRIOR_WEIGHT)))
            self._last_context = _normalize_context(state.get("last_context", "general"))
            self._last_ts = float(state.get("last_ts", 0.0))
            self._obs_count = int(state.get("obs_count", 0))
            self._last_surprise = float(state.get("last_surprise", 0.0))

            raw_models = state.get("models", {})
            if isinstance(raw_models, Mapping) and raw_models:
                restored: dict[str, dict[str, dict[str, float]]] = {}
                for ctx, feats in raw_models.items():
                    if not isinstance(feats, Mapping):
                        continue
                    c_key = _normalize_context(ctx)
                    restored[c_key] = {}
                    for f, arr in feats.items():
                        if isinstance(arr, (list, tuple)) and len(arr) >= 6:
                            restored[c_key][str(f)] = {
                                "m": float(arr[0]),
                                "v": max(1e-6, float(arr[1])),
                                "vel": float(arr[2]),
                                "n": max(1.0, float(arr[3])),
                                "last": float(arr[4]),
                                "ts": float(arr[5]),
                            }
                if restored:
                    self._models = restored

            raw_trans = state.get("transitions", {})
            if isinstance(raw_trans, Mapping) and raw_trans:
                self._transitions = {
                    _normalize_context(src): {
                        _normalize_context(dst): float(cnt)
                        for dst, cnt in row.items()
                    }
                    for src, row in raw_trans.items()
                    if isinstance(row, Mapping)
                }

    @classmethod
    def from_state(cls, state: Mapping[str, Any]) -> "ActiveInferenceBrain":
        """Construct an ``ActiveInferenceBrain`` from serialized ``to_state()`` dict."""
        brain = cls(prior_weight=float(state.get("prior_weight", _PRIOR_WEIGHT)))
        brain.load_state(state)
        return brain

    def status(self) -> dict[str, Any]:
        """Return lightweight diagnostic summary of the world-model."""
        with self._lock:
            state_bytes = len(json.dumps(self._compact_state_locked(), separators=(",", ":")).encode("utf-8"))
            return {
                "contexts": sorted(self._models.keys()),
                "last_context": self._last_context,
                "observation_count": self._obs_count,
                "last_surprise": round(self._last_surprise, 6),
                "state_bytes": state_bytes,
                "state_limit_bytes": 65536,
                "within_64kb_budget": state_bytes < 65536,
            }
