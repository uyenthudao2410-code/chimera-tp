"""CHIMERA MIDBRAIN DOPAMINE v19 — 1% Value & Dopamine Neuron Critic, RPE-Pivot Distiller & Causal Engine."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import threading
import time
from typing import Any

from .overmind_cortex import EgressDlpGuard


N_VSA_BUCKETS = 128
N_STRUCT_FEATURES = 16
MAX_PROBE_BYTES = 262_144

_TOKEN_RE = re.compile(r"[a-z0-9_./:-]{2,}")
_PATH_RE = re.compile(r"(?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+\.[A-Za-z]{1,6}")

_POS_LINE_RE = re.compile(
    r"(?:\bpassed\b|\b0 failed\b|test_rc=0|\bfixed\b|\broot cause\b|\bbreakthrough\b|\bverified_for_pr\b|\bclean_apply\b|\[\+δ)",
    re.I,
)
_NEG_LINE_RE = re.compile(
    r"(?:\bFAILED\b|AssertionError|Traceback|SyntaxError|TypeError|ModuleNotFoundError|timed?\s*out|codex_rc=124|HTTP\s+(?:401|403|502|503)|\[-δ)",
    re.I,
)

# Calibrated heuristic prior (active until replaced by Colab White-Box 1% Distilled Probe)
_DEFAULT_FEAT_WEIGHTS: tuple[float, ...] = (
    0.85,   # 0: diff additions ratio
    -0.25,  # 1: diff deletions ratio
    -1.65,  # 2: fail hits
    1.85,   # 3: pass hits
    -1.35,  # 4: timeout/stall hits
    0.65,   # 5: unique token ratio (progress diversity)
    -1.15,  # 6: repetition ratio (reasoning loop)
    0.55,   # 7: concrete file path density
    0.25,   # 8: code/diff markers
    1.30,   # 9: [+δ] marker
    -1.30,  # 10: [-δ] marker
    0.90,   # 11: [1%-IMMUNE] marker
    -1.20,  # 12: syntax error hits
    0.65,   # 13: clean diff/patch header count
    -0.85,  # 14: assertion failures
    0.15,   # 15: log-length progress signal
)
_DEFAULT_BIAS = -0.05


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sigmoid(x: float) -> float:
    xc = max(-24.0, min(24.0, float(x)))
    return 1.0 / (1.0 + math.exp(-xc))


def extract_structural_features(text: str) -> list[float]:
    """Extract deterministic 16-float structural code/trace features (shared with Radar & Colab calibrator)."""
    raw = str(text or "")
    low = raw.lower()
    lines = [ln for ln in raw.splitlines() if ln.strip()]
    n_lines = max(1, len(lines))

    diff_adds = sum(1 for ln in lines if ln.startswith("+") and not ln.startswith("+++"))
    diff_dels = sum(1 for ln in lines if ln.startswith("-") and not ln.startswith("---"))
    patch_hdrs = sum(1 for ln in lines if ln.startswith("diff --git ") or ln.startswith("@@ "))

    fail_hits = len(re.findall(r"\b(?:failed|error|exception|traceback|crash|aborted|blocked|mismatch)\b", low))
    pass_hits = len(re.findall(r"\b(?:passed|pass|ok|fixed|resolved|clean_apply|verified|success|root cause)\b", low)) + low.count("test_rc=0")
    timeout_hits = len(re.findall(r"(?:timeout|timed out|stalled|codex_rc=124|hang|no_diff_produced)", low))
    syntax_hits = len(re.findall(r"(?:syntaxerror|indentationerror|nameerror|importerror|typeerror)", low))
    assert_hits = len(re.findall(r"(?:assertionerror|assert\s+|e\s+assert)", low))

    tokens = _TOKEN_RE.findall(low)[:400]
    n_tok = max(1, len(tokens))
    counts = Counter(tokens)
    uniq_ratio = min(1.0, len(counts) / float(n_tok))
    top_freq = max(counts.values()) if counts else 0
    repeat_ratio = min(1.0, max(0.0, (top_freq / float(n_tok)) - 0.08) * 2.5) if n_tok >= 8 else 0.0

    path_hits = len(_PATH_RE.findall(raw))
    fence_hits = raw.count("```") + patch_hdrs

    return [
        round(min(1.0, diff_adds / 25.0), 4),
        round(min(1.0, diff_dels / 25.0), 4),
        round(min(1.0, fail_hits / 6.0), 4),
        round(min(1.0, pass_hits / 6.0), 4),
        round(min(1.0, timeout_hits / 3.0), 4),
        round(uniq_ratio, 4),
        round(repeat_ratio, 4),
        round(min(1.0, path_hits / 6.0), 4),
        round(min(1.0, fence_hits / 6.0), 4),
        1.0 if "[+δ" in raw else 0.0,
        1.0 if "[-δ" in raw else 0.0,
        1.0 if "1%-IMMUNE" in raw else 0.0,
        round(min(1.0, syntax_hits / 3.0), 4),
        round(min(1.0, patch_hdrs / 4.0), 4),
        round(min(1.0, assert_hits / 4.0), 4),
        round(min(1.0, math.log1p(len(raw)) / 9.0), 4),
    ]


def vsa_bucket_projection(text: str, n_buckets: int = N_VSA_BUCKETS) -> list[float]:
    """Deterministic signed hash projection of text tokens into N_VSA_BUCKETS bounded floats."""
    n_b = max(16, int(n_buckets or N_VSA_BUCKETS))
    acc = [0.0] * n_b
    tokens = _TOKEN_RE.findall(str(text or "").lower())[:256]
    if not tokens:
        return acc
    for tok in tokens:
        dig = hashlib.blake2b(tok.encode("utf-8"), digest_size=8).digest()
        h_int = int.from_bytes(dig, "little")
        bucket = h_int % n_b
        sign = 1.0 if ((h_int >> 17) & 1) else -1.0
        acc[bucket] += sign
    norm = math.sqrt(sum(v * v for v in acc))
    if norm <= 1e-9:
        return acc
    return [round(v / norm, 5) for v in acc]


def extract_rpe_pivots(
    text: str,
    *,
    outcome: str = "neutral",
    max_pivots: int = 3,
) -> list[dict[str, Any]]:
    """Distill compact DLP-scrubbed [+δ BREAKTHROUGH] and [-δ TRAP] pivot micro-crystals from traces."""
    clean = EgressDlpGuard.redact_text(str(text or ""))
    out_tag = str(outcome or "neutral").strip().lower()
    cap = max(1, min(8, int(max_pivots or 3)))
    candidates: list[tuple[float, str, str]] = []
    seen: set[str] = set()

    for raw_ln in clean.splitlines():
        ln = " ".join(raw_ln.strip().split())
        if len(ln) < 18:
            continue
        snippet = ln[:200]
        sig = snippet.lower()[:80]
        if sig in seen:
            continue
        seen.add(sig)

        pos_m = len(_POS_LINE_RE.findall(ln))
        neg_m = len(_NEG_LINE_RE.findall(ln))
        if pos_m > neg_m or (out_tag == "win" and pos_m > 0):
            score = 2.0 + pos_m * 0.5 + (0.6 if out_tag == "win" else 0.0)
            candidates.append((score, "POS_BREAKTHROUGH", f"[+δ BREAKTHROUGH] {snippet}"[:220]))
        elif neg_m > pos_m or (out_tag == "fail" and neg_m > 0):
            score = 1.9 + neg_m * 0.5 + (0.6 if out_tag == "fail" else 0.0)
            candidates.append((score, "NEG_TRAP", f"[-δ TRAP] {snippet}"[:220]))

    if not candidates and clean.strip():
        summary = " ".join(clean.strip().split())[:195]
        if out_tag == "win":
            candidates.append((1.2, "POS_BREAKTHROUGH", f"[+δ BREAKTHROUGH] {summary}"[:220]))
        elif out_tag == "fail":
            candidates.append((1.2, "NEG_TRAP", f"[-δ TRAP] {summary}"[:220]))

    candidates.sort(key=lambda x: x[0], reverse=True)
    return [
        {"kind": kind, "pivot_text": ptxt, "weight": round(sc, 3)}
        for sc, kind, ptxt in candidates[:cap]
    ]


class MidbrainDopamineEngine:
    """Real-time Value (V_t) and Reward Prediction Error (δ_t) scoring engine with hot-swappable Colab probe."""

    def __init__(
        self,
        ops_dir: Path | str,
        *,
        pulse_bus: Any | None = None,
        vsa_memory: Any | None = None,
    ) -> None:
        self.ops_dir = Path(ops_dir)
        self.ops_dir.mkdir(parents=True, exist_ok=True)
        self.probe_path = self.ops_dir / "midbrain_value_probe.json"
        self.pulse_bus = pulse_bus
        self.vsa_memory = vsa_memory
        self._lock = threading.RLock()

        self._probe_mode = "heuristic_prior"
        self._vsa_weights: list[float] = [0.0] * N_VSA_BUCKETS
        self._feat_weights: list[float] = list(_DEFAULT_FEAT_WEIGHTS)
        self._bias: float = _DEFAULT_BIAS
        self._probe_meta: dict[str, Any] = {}

        self._task_last_v: dict[str, float] = {}
        self._scores_served = 0
        self._spikes_emitted = 0
        self._troughs_emitted = 0
        self._total_score_ms = 0.0
        self._load_probe_if_present()

    def _load_probe_if_present(self) -> None:
        if not self.probe_path.is_file():
            return
        try:
            raw_bytes = self.probe_path.read_bytes()
            if len(raw_bytes) > MAX_PROBE_BYTES:
                return
            obj = json.loads(raw_bytes.decode("utf-8", errors="ignore"))
            if isinstance(obj, dict):
                self._apply_probe_dict_locked(obj)
        except Exception:
            pass

    def _apply_probe_dict_locked(self, obj: dict[str, Any]) -> None:
        vsa_w = obj.get("student_vsa_weights")
        feat_w = obj.get("student_feat_weights")
        if not isinstance(vsa_w, list) or len(vsa_w) != N_VSA_BUCKETS:
            raise ValueError(f"student_vsa_weights must have length {N_VSA_BUCKETS}")
        if not isinstance(feat_w, list) or len(feat_w) != N_STRUCT_FEATURES:
            raise ValueError(f"student_feat_weights must have length {N_STRUCT_FEATURES}")
        self._vsa_weights = [float(x) for x in vsa_w]
        self._feat_weights = [float(x) for x in feat_w]
        self._bias = float(obj.get("student_bias", 0.0) or 0.0)
        self._probe_mode = str(obj.get("probe_mode") or "whitebox_distilled_1pct")
        meta = obj.get("probe_meta") if isinstance(obj.get("probe_meta"), dict) else {}
        self._probe_meta = {
            **meta,
            "installed_at": obj.get("installed_at") or _utc_now_iso(),
            "size_kb": round(len(json.dumps(obj, ensure_ascii=False).encode("utf-8")) / 1024.0, 2),
        }

    def install_probe(self, probe_artifact: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(probe_artifact, dict):
            return {"ok": False, "error": "invalid_probe_artifact"}
        encoded = json.dumps(probe_artifact, ensure_ascii=False, indent=2).encode("utf-8")
        if len(encoded) > MAX_PROBE_BYTES:
            return {"ok": False, "error": f"probe_too_large:{len(encoded)}>{MAX_PROBE_BYTES}"}
        with self._lock:
            self._apply_probe_dict_locked(probe_artifact)
            persisted = dict(probe_artifact)
            persisted["probe_mode"] = self._probe_mode
            persisted["installed_at"] = self._probe_meta.get("installed_at")
            tmp = self.probe_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(persisted, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            tmp.replace(self.probe_path)
            return {
                "ok": True,
                "probe_mode": self._probe_mode,
                "probe_meta": dict(self._probe_meta),
            }

    def _raw_value(self, text: str) -> float:
        buckets = vsa_bucket_projection(text, N_VSA_BUCKETS)
        feats = extract_structural_features(text)
        with self._lock:
            z = self._bias
            for w, x in zip(self._vsa_weights, buckets):
                z += w * x
            for w, x in zip(self._feat_weights, feats):
                z += w * x
        return _sigmoid(z)

    def score(
        self,
        text: str,
        *,
        prev_text: str = "",
        task_id: str = "",
    ) -> dict[str, Any]:
        t0 = time.perf_counter()
        clean = EgressDlpGuard.redact_text(str(text or ""))
        val = self._raw_value(clean)

        tid = str(task_id or "").strip()
        with self._lock:
            if prev_text:
                prev_v = self._raw_value(EgressDlpGuard.redact_text(str(prev_text)))
            elif tid and tid in self._task_last_v:
                prev_v = self._task_last_v[tid]
            else:
                prev_v = 0.5
            rpe = val - prev_v
            if tid:
                self._task_last_v[tid] = val
                if len(self._task_last_v) > 256:
                    oldest = next(iter(self._task_last_v))
                    self._task_last_v.pop(oldest, None)

            if rpe >= 0.12 or val >= 0.78:
                sig = "SPIKE"
                self._spikes_emitted += 1
            elif rpe <= -0.15 or val <= 0.30:
                sig = "TROUGH"
                self._troughs_emitted += 1
            else:
                sig = "STEADY"

            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            self._scores_served += 1
            self._total_score_ms += elapsed_ms
            mode = self._probe_mode

        if self.pulse_bus is not None and sig in ("SPIKE", "TROUGH"):
            try:
                topic = "DOPAMINE_SPIKE" if sig == "SPIKE" else "DOPAMINE_TROUGH"
                self.pulse_bus.emit(
                    topic,
                    "midbrain",
                    {"task_id": tid or "ad_hoc", "value_v": round(val, 4), "rpe_delta": round(rpe, 4)},
                )
            except Exception:
                pass

        return {
            "ok": True,
            "value_v": round(val, 4),
            "prev_v": round(prev_v, 4),
            "rpe_delta": round(rpe, 4),
            "signal": sig,
            "probe_mode": mode,
            "elapsed_ms": round(elapsed_ms, 3),
        }

    def status(self) -> dict[str, Any]:
        with self._lock:
            cnt = self._scores_served
            avg_ms = round(self._total_score_ms / cnt, 3) if cnt else 0.0
            out: dict[str, Any] = {
                "ok": True,
                "probe_mode": self._probe_mode,
                "probe_path": str(self.probe_path),
                "probe_installed": self.probe_path.is_file(),
                "probe_meta": dict(self._probe_meta),
                "scores_served": cnt,
                "spikes_emitted": self._spikes_emitted,
                "troughs_emitted": self._troughs_emitted,
                "avg_score_ms": avg_ms,
            }
        if self.vsa_memory is not None and hasattr(self.vsa_memory, "immune_vault_summary"):
            try:
                out["immune_vault"] = self.vsa_memory.immune_vault_summary()
            except Exception:
                pass
        return out
