"""CHIMERA-UMWELT (Idea #7) — Passive Cognitive Seismograph & Host Resonance.

Zero-camera, zero-microphone, 100% local passive telemetry engine operating strictly
within the CHIMERA-ONE Unification Doctrine (Laws 1–7, 100% Python stdlib, Zero-NumPy,
< 512 KiB RAM, lazy-loaded).

Capabilities:
- Passive signal ingestion from OS/IDE/CAD/Tquota telemetry (`window_focus`, `edit`,
  `undo`, `steer`, `test_fail`, `test_pass`, `cad_cmd`, `build`, `idle_tick`).
- Real-time cognitive assessment (`flow_score`, `frustration_score`, `flow_shield`,
  silent `subconscious_whisper` trigger for out-of-band counterfactual scouting).
- Circadian Phase Learner tracking `(day_type, hour_0_23) -> phase` histograms
  (`cad_mode`, `swarm_coding`, `deep_research`, `rest`) with 5-minute Anticipatory
  Metamorphosis forecasting (`anticipate_phase`).
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
import threading
import time
from collections import Counter, deque
from datetime import datetime
from pathlib import Path
from typing import Any

VALID_EVENT_KINDS: tuple[str, ...] = (
    "window_focus",
    "edit",
    "undo",
    "steer",
    "test_fail",
    "test_pass",
    "cad_cmd",
    "build",
    "idle_tick",
)

CIRCADIAN_PHASES: tuple[str, ...] = (
    "cad_mode",
    "swarm_coding",
    "deep_research",
    "rest",
)

_CAD_HINTS: tuple[str, ...] = (
    "acad",
    "autocad",
    "cad",
    "dwg",
    "revit",
    "civil3d",
    "blender",
    "solidworks",
    "freecad",
)

_CODING_APPS: tuple[str, ...] = (
    "code",
    "vscode",
    "cursor",
    "windsurf",
    "antigravity",
    "terminal",
    "pwsh",
    "powershell",
    "wt",
    "codex",
    "claude",
    "gemini",
    "ide",
    "pycharm",
    "neovim",
    "vim",
    "zed",
    "tquota",
)

_RESEARCH_HINTS: tuple[str, ...] = (
    "chrome",
    "edge",
    "firefox",
    "brave",
    "browser",
    "pdf",
    "acrobat",
    "sumatra",
    "obsidian",
    "notion",
    "arxiv",
    "docs",
    "paper",
    "wiki",
    "reader",
    "zotero",
    "research",
)

_CODE_EXTS: tuple[str, ...] = (
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".rs",
    ".go",
    ".c",
    ".h",
    ".cpp",
    ".hpp",
    ".cs",
    ".java",
    ".json",
    ".toml",
    ".yaml",
    ".yml",
    ".sql",
    ".sh",
    ".ps1",
    ".html",
    ".css",
)

_METAMORPHOSIS_PLAYBOOK: dict[str, list[str]] = {
    "cad_mode": [
        "prepare_cad_vip_posture",
        "preserve_display_gpu_headroom",
        "defer_non_urgent_background_compaction",
    ],
    "swarm_coding": [
        "warm_hybrid_search_and_callgraph_cache",
        "prime_stigmergy_smell_prefetch",
        "keep_singleflight_build_queue_ready",
    ],
    "deep_research": [
        "arm_flow_shield_notification_guard",
        "prioritize_fast_local_vsa_recall",
        "trim_unused_cold_caches",
    ],
    "rest": [
        "arm_nocturnal_dream_consolidation",
        "schedule_low_impact_autophagy_scan",
        "elevate_melatonin_recovery_posture",
    ],
}


def _default_ops_dir() -> Path:
    return Path(os.environ.get("CHIMERA_HOME") or (Path.home() / ".chimera"))


def _clamp01(val: float) -> float:
    if val <= 0.0:
        return 0.0
    if val >= 1.0:
        return 1.0
    return float(val)


def _day_type_and_hour(ts: float) -> tuple[str, int]:
    dt = datetime.fromtimestamp(float(ts))
    day_type = "weekend" if dt.weekday() >= 5 else "weekday"
    return day_type, int(dt.hour)


def _infer_phase(
    event_kind: str,
    app: str,
    target: str,
    meta: dict[str, Any] | None,
) -> str:
    if isinstance(meta, dict):
        explicit = str(meta.get("phase", "")).strip().lower()
        if explicit in CIRCADIAN_PHASES:
            return explicit

    ek = (event_kind or "").strip().lower()
    app_l = (app or "").strip().lower()
    tgt_l = (target or "").strip().lower()

    if ek == "idle_tick":
        return "rest"
    if ek == "cad_cmd" or tgt_l.endswith((".dwg", ".dxf", ".rvt", ".step", ".stl")):
        return "cad_mode"
    if any(h in app_l for h in _CAD_HINTS):
        return "cad_mode"
    if ek in ("edit", "undo", "steer", "test_fail", "test_pass", "build"):
        return "swarm_coding"
    if any(h in app_l for h in _RESEARCH_HINTS) or tgt_l.endswith((".pdf", ".epub")):
        return "deep_research"
    if any(h in app_l for h in _CODING_APPS) or tgt_l.endswith(_CODE_EXTS):
        return "swarm_coding"
    return "deep_research" if ek == "window_focus" and (app_l or tgt_l) else "rest"


class UmweltCognitiveResonator:
    """Passive local cognitive seismograph, Flow Shield, Frustration Whisper & Circadian Learner."""

    MAX_WINDOW_SIGNALS = 512

    def __init__(
        self,
        ops_dir: str | Path | None = None,
        *,
        ephemeral: bool = False,
    ) -> None:
        self._lock = threading.RLock()
        self._ephemeral = bool(ephemeral)
        self._ops_dir = Path(ops_dir) if ops_dir is not None else _default_ops_dir()
        self._db_path: Path | None = None
        self._conn: sqlite3.Connection | None = None
        self._signals: deque[dict[str, Any]] = deque(maxlen=self.MAX_WINDOW_SIGNALS)
        # (day_type, hour_0_23) -> {phase: float_weight}
        self._circadian: dict[tuple[str, int], dict[str, float]] = {}
        self._total_recorded = 0
        self._init_storage()

    def _init_storage(self) -> None:
        if self._ephemeral:
            self._conn = sqlite3.connect(":memory:", check_same_thread=False)
        else:
            self._ops_dir.mkdir(parents=True, exist_ok=True)
            self._db_path = self._ops_dir / "bios_umwelt.sqlite3"
            self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL;")
            self._conn.execute("PRAGMA synchronous=NORMAL;")
            self._conn.execute("PRAGMA busy_timeout=3000;")

        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS circadian_histogram (
                day_type TEXT NOT NULL,
                hour INTEGER NOT NULL,
                phase TEXT NOT NULL,
                weight REAL NOT NULL DEFAULT 0.0,
                updated_at REAL NOT NULL,
                PRIMARY KEY (day_type, hour, phase)
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS umwelt_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                event_kind TEXT NOT NULL,
                app TEXT NOT NULL,
                target TEXT NOT NULL,
                ok INTEGER NOT NULL,
                phase TEXT NOT NULL,
                meta_json TEXT NOT NULL
            )
            """
        )
        self._conn.commit()
        self._load_from_db()

    def _load_from_db(self) -> None:
        assert self._conn is not None
        cur = self._conn.execute(
            "SELECT day_type, hour, phase, weight FROM circadian_histogram"
        )
        for day_type, hour, phase, weight in cur.fetchall():
            bucket = self._circadian.setdefault((str(day_type), int(hour)), {})
            bucket[str(phase)] = float(weight)

        cur2 = self._conn.execute(
            """
            SELECT ts, event_kind, app, target, ok, phase, meta_json
            FROM umwelt_events
            ORDER BY id DESC
            LIMIT ?
            """,
            (self.MAX_WINDOW_SIGNALS,),
        )
        rows = cur2.fetchall()
        for ts, event_kind, app, target, ok, phase, meta_json in reversed(rows):
            try:
                meta = json.loads(meta_json) if meta_json else {}
            except Exception:
                meta = {}
            self._signals.append(
                {
                    "ts": float(ts),
                    "event_kind": str(event_kind),
                    "app": str(app),
                    "target": str(target),
                    "ok": bool(ok),
                    "phase": str(phase),
                    "meta": meta if isinstance(meta, dict) else {},
                }
            )
        self._total_recorded = len(self._signals)

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                except Exception:
                    pass
                self._conn = None

    def __del__(self) -> None:
        self.close()

    def record_signal(
        self,
        event_kind: str,
        app: str = "",
        target: str = "",
        ok: bool = True,
        ts: float | None = None,
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Ingest one passive host/IDE/CAD/Tquota telemetry signal (zero camera/mic)."""
        now = float(time.time() if ts is None else ts)
        ek = str(event_kind or "idle_tick").strip().lower()
        app_s = str(app or "").strip()
        target_s = str(target or "").strip()
        meta_d = dict(meta) if isinstance(meta, dict) else {}
        ok_b = bool(ok)
        if ek == "test_fail":
            ok_b = False
        phase = _infer_phase(ek, app_s, target_s, meta_d)
        day_type, hour = _day_type_and_hour(now)

        sig = {
            "ts": now,
            "event_kind": ek,
            "app": app_s,
            "target": target_s,
            "ok": ok_b,
            "phase": phase,
            "meta": meta_d,
        }

        weight = float(meta_d.get("circadian_weight", 1.0))
        if weight <= 0.0:
            weight = 1.0

        with self._lock:
            self._signals.append(sig)
            self._total_recorded += 1
            bucket = self._circadian.setdefault((day_type, hour), {})
            bucket[phase] = bucket.get(phase, 0.0) + weight

            if self._conn is not None:
                self._conn.execute(
                    """
                    INSERT INTO circadian_histogram (day_type, hour, phase, weight, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(day_type, hour, phase)
                    DO UPDATE SET weight = weight + excluded.weight, updated_at = excluded.updated_at
                    """,
                    (day_type, hour, phase, weight, now),
                )
                if not self._ephemeral:
                    self._conn.execute(
                        """
                        INSERT INTO umwelt_events (ts, event_kind, app, target, ok, phase, meta_json)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            now,
                            ek,
                            app_s,
                            target_s,
                            1 if ok_b else 0,
                            phase,
                            json.dumps(meta_d, separators=(",", ":"), ensure_ascii=False),
                        ),
                    )
                    # Keep SQLite log compact (<= 2048 rows)
                    if self._total_recorded % 64 == 0:
                        self._conn.execute(
                            """
                            DELETE FROM umwelt_events
                            WHERE id NOT IN (
                                SELECT id FROM umwelt_events ORDER BY id DESC LIMIT 2048
                            )
                            """
                        )
                self._conn.commit()

        return {
            "recorded": True,
            "event_kind": ek,
            "inferred_phase": phase,
            "day_type": day_type,
            "hour": hour,
            "ok": ok_b,
            "ts": now,
            "window_size": len(self._signals),
        }

    def train_circadian(
        self,
        phase: str,
        *,
        ts: float | None = None,
        day_type: str | None = None,
        hour: int | None = None,
        weight: float = 1.0,
    ) -> dict[str, Any]:
        """Directly reinforce a circadian `(day_type, hour) -> phase` observation."""
        ph = str(phase).strip().lower()
        if ph not in CIRCADIAN_PHASES:
            raise ValueError(f"Unsupported phase {phase!r}; expected one of {CIRCADIAN_PHASES}")
        now = float(time.time() if ts is None else ts)
        if day_type is None or hour is None:
            dt_auto, hr_auto = _day_type_and_hour(now)
            day_type = dt_auto if day_type is None else str(day_type)
            hour = hr_auto if hour is None else int(hour)
        hour_i = int(hour) % 24
        day_s = "weekend" if str(day_type).lower() == "weekend" else "weekday"
        w = max(0.05, float(weight))

        with self._lock:
            bucket = self._circadian.setdefault((day_s, hour_i), {})
            bucket[ph] = bucket.get(ph, 0.0) + w
            if self._conn is not None:
                self._conn.execute(
                    """
                    INSERT INTO circadian_histogram (day_type, hour, phase, weight, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(day_type, hour, phase)
                    DO UPDATE SET weight = weight + excluded.weight, updated_at = excluded.updated_at
                    """,
                    (day_s, hour_i, ph, w, now),
                )
                self._conn.commit()
        return {"day_type": day_s, "hour": hour_i, "phase": ph, "weight_added": w}

    @staticmethod
    def _detect_ping_pong(targets: list[str]) -> tuple[float, list[str]]:
        """Detect rapid oscillation between 2–3 files/targets."""
        seq = [t for t in targets if t]
        if len(seq) < 4:
            return 0.0, []
        # Deduplicate consecutive identical entries to observe target switches
        switches: list[str] = [seq[0]]
        for item in seq[1:]:
            if item != switches[-1]:
                switches.append(item)
        if len(switches) < 4:
            return 0.0, []

        # Inspect tail up to 16 switches
        tail = switches[-16:]
        oscillations = 0
        osc_files: Counter[str] = Counter()
        for i in range(2, len(tail)):
            prev_window = tail[max(0, i - 3) : i]
            if tail[i] in prev_window and tail[i] != tail[i - 1]:
                oscillations += 1
                osc_files[tail[i]] += 1
                osc_files[tail[i - 1]] += 1

        unique_hot = [f for f, _ in osc_files.most_common(3)]
        if oscillations < 2:
            return 0.0, []
        unique_total = len(set(tail))
        # Classic ping-pong: oscillating tightly among 2–3 targets
        concentration = 1.0 if unique_total <= 3 else max(0.35, 3.0 / float(unique_total))
        raw = min(1.0, (oscillations / 5.0) * concentration)
        return round(raw, 4), unique_hot

    def assess(
        self,
        now_ts: float | None = None,
        *,
        window_s: float = 300.0,
    ) -> dict[str, Any]:
        """Compute live cognitive state: flow_score, frustration_score, flow_shield, whisper."""
        with self._lock:
            signals = list(self._signals)

        if now_ts is None:
            if signals:
                now = max(time.time(), signals[-1]["ts"])
            else:
                now = time.time()
        else:
            now = float(now_ts)

        cutoff = now - max(10.0, float(window_s))
        recent = [s for s in signals if cutoff <= s["ts"] <= now + 5.0]
        if not recent and signals:
            # If caller evaluates shortly after synthetic timestamps without passing now_ts
            latest_ts = signals[-1]["ts"]
            if abs(now - latest_ts) > window_s:
                return self._empty_assessment(now, active_phase="rest")

        if not recent:
            return self._empty_assessment(now, active_phase="rest")

        n = len(recent)
        kinds = Counter(s["event_kind"] for s in recent)
        phases = Counter(s["phase"] for s in recent)
        active_phase = phases.most_common(1)[0][0] if phases else "rest"

        # Productive steady work signals
        productive = [
            s
            for s in recent
            if (s["event_kind"] in ("edit", "cad_cmd", "test_pass") and s["ok"])
            or (s["event_kind"] == "build" and s["ok"])
            or (s["event_kind"] == "window_focus" and s["phase"] == "deep_research")
        ]
        idle_count = kinds.get("idle_tick", 0)
        undo_count = kinds.get("undo", 0)
        steer_count = kinds.get("steer", 0)
        fail_events = [
            s
            for s in recent
            if s["event_kind"] == "test_fail" or (not s["ok"] and s["event_kind"] != "idle_tick")
        ]

        # Track repeated failures on the same target
        fail_by_target: Counter[str] = Counter()
        for s in fail_events:
            key = s["target"] or s["app"] or "__global__"
            fail_by_target[key] += 1
        repeat_fail_target = ""
        repeat_fail_count = 0
        if fail_by_target:
            repeat_fail_target, repeat_fail_count = fail_by_target.most_common(1)[0]

        # App context switches (context thrashing)
        apps_seq = [s["app"] for s in recent if s["app"]]
        app_switches = 0
        for i in range(1, len(apps_seq)):
            if apps_seq[i] != apps_seq[i - 1]:
                app_switches += 1
        unique_apps = len(set(apps_seq))
        thrash_rate = (
            float(app_switches) / float(max(1, len(apps_seq) - 1))
            if len(apps_seq) >= 3
            else 0.0
        )
        # Penalize thrashing only when hopping across >= 3 apps or high switch ratio
        context_thrash = _clamp01(
            thrash_rate * (1.0 if unique_apps >= 3 else 0.35)
        )

        # File ping-pong detection (excluding successful passes breaking the loop)
        edit_targets = [
            s["target"]
            for s in recent
            if s["event_kind"] in ("edit", "undo", "steer", "window_focus", "test_fail")
            and s["target"]
        ]
        ping_pong_score, ping_pong_files = self._detect_ping_pong(edit_targets)

        # Recent recovery damping: consecutive test_pass at tail reduce frustration
        tail_passes = 0
        for s in reversed(recent[-4:]):
            if s["event_kind"] == "test_pass" and s["ok"]:
                tail_passes += 1
            elif s["event_kind"] in ("test_fail", "undo", "steer"):
                break
        recovery_damping = 0.20 * min(2, tail_passes)

        # Frustration score [0..1]
        undo_steer_total = undo_count + steer_count
        undo_steer_term = min(0.55, 0.14 * undo_steer_total) if undo_steer_total >= 2 else 0.05 * undo_steer_total
        if undo_steer_total >= 4:
            undo_steer_term = min(0.65, undo_steer_term + 0.12)

        repeat_fail_term = 0.0
        if repeat_fail_count >= 3:
            repeat_fail_term = min(0.65, 0.45 + 0.08 * (repeat_fail_count - 3))
        elif len(fail_events) >= 2:
            repeat_fail_term = min(0.35, 0.12 * len(fail_events))

        ping_pong_term = (0.62 if (ping_pong_score >= 0.80 and tail_passes == 0) else 0.40) * ping_pong_score
        error_ratio_term = 0.25 * (len(fail_events) / float(n))

        raw_frustration = (
            undo_steer_term
            + repeat_fail_term
            + ping_pong_term
            + error_ratio_term
            - recovery_damping
        )
        # Smooth saturation into [0, 1]
        frustration_score = _clamp01(1.0 - math.exp(-1.55 * max(0.0, raw_frustration)))
        # Ensure explicit strong thresholds guarantee clear separation
        if (
            repeat_fail_count >= 3
            or undo_steer_total >= 4
            or (ping_pong_score >= 0.75 and undo_steer_total >= 2)
            or (ping_pong_score >= 0.85 and tail_passes == 0)
        ):
            frustration_score = max(frustration_score, 0.68)
        frustration_score = round(_clamp01(frustration_score), 4)

        # Flow score [0..1]
        idle_ratio = idle_count / float(n)
        non_idle = max(1, n - idle_count)
        productive_ratio = len(productive) / float(non_idle)
        # Depth ramps cleanly as >= 4 focused signals accumulate
        depth_factor = min(1.0, len(productive) / 5.0)
        # Cadence regularity (low burst variance across productive events)
        cadence_bonus = 0.12 if len(productive) >= 4 else 0.0
        raw_flow = (
            (0.78 * productive_ratio * depth_factor + cadence_bonus)
            * (1.0 - 0.85 * frustration_score)
            * (1.0 - 0.65 * context_thrash)
            * (1.0 - 0.80 * idle_ratio)
        )
        if idle_ratio >= 0.7:
            raw_flow *= 0.25
        flow_score = round(_clamp01(raw_flow), 4)

        flow_shield = bool(flow_score >= 0.60 and frustration_score < 0.35)

        trigger_reasons: list[str] = []
        if repeat_fail_count >= 3:
            trigger_reasons.append(f"same_test_fail_{repeat_fail_count}x:{repeat_fail_target}")
        if undo_steer_total >= 3:
            trigger_reasons.append(f"undo_steer_burst:{undo_steer_total}")
        if ping_pong_score >= 0.55:
            trigger_reasons.append(f"file_ping_pong:{','.join(ping_pong_files[:3])}")

        whisper_triggered = bool(
            frustration_score >= 0.55 and (len(trigger_reasons) > 0 or len(fail_events) >= 3)
        )
        hot_target = repeat_fail_target or (ping_pong_files[0] if ping_pong_files else "")
        subconscious_whisper: dict[str, Any] = {
            "triggered": whisper_triggered,
            "mode": "silent_out_of_band" if whisper_triggered else "dormant",
            "interrupt_user": False,
            "trigger_reasons": trigger_reasons,
            "hot_target": hot_target,
            "ping_pong_files": ping_pong_files,
            "suggested_scout": (
                "counterfactual_root_cause_and_stigmergy_smell"
                if whisper_triggered
                else ""
            ),
        }

        if idle_ratio >= 0.75:
            state = "resting"
        elif whisper_triggered:
            state = "frustrated"
        elif flow_shield:
            state = "deep_flow"
        elif context_thrash >= 0.60:
            state = "thrashing"
        elif flow_score >= 0.40:
            state = "focused"
        else:
            state = "neutral"

        # Advisory hormone hints for ChimeraBiosOrganism closed-loop tick
        hormone_hints = {
            "adrenaline": round(0.25 if active_phase == "cad_mode" else (0.10 if flow_shield else 0.0), 3),
            "cortisol": round(min(0.45, frustration_score * 0.5), 3),
            "dopamine": round(min(0.40, flow_score * 0.45), 3),
            "melatonin": round(0.35 if state == "resting" else 0.0, 3),
        }

        return {
            "ts": now,
            "state": state,
            "active_phase": active_phase,
            "flow_score": flow_score,
            "frustration_score": frustration_score,
            "flow_shield": flow_shield,
            "flow_shield_directives": {
                "suppress_notifications": flow_shield,
                "defer_compaction": flow_shield,
                "defer_background_noise": flow_shield,
            },
            "whisper_triggered": whisper_triggered,
            "subconscious_whisper": subconscious_whisper,
            "telemetry_summary": {
                "window_s": float(window_s),
                "signal_count": n,
                "productive_count": len(productive),
                "undo_count": undo_count,
                "steer_count": steer_count,
                "fail_count": len(fail_events),
                "repeat_fail_target": repeat_fail_target,
                "repeat_fail_count": repeat_fail_count,
                "context_thrash": round(context_thrash, 4),
                "ping_pong_score": ping_pong_score,
                "idle_ratio": round(idle_ratio, 4),
            },
            "hormone_hints": hormone_hints,
            "privacy_guarantees": {
                "camera": False,
                "microphone": False,
                "cloud_upload": False,
                "local_only": True,
            },
        }

    def _empty_assessment(self, now: float, active_phase: str = "rest") -> dict[str, Any]:
        return {
            "ts": now,
            "state": "resting",
            "active_phase": active_phase,
            "flow_score": 0.0,
            "frustration_score": 0.0,
            "flow_shield": False,
            "flow_shield_directives": {
                "suppress_notifications": False,
                "defer_compaction": False,
                "defer_background_noise": False,
            },
            "whisper_triggered": False,
            "subconscious_whisper": {
                "triggered": False,
                "mode": "dormant",
                "interrupt_user": False,
                "trigger_reasons": [],
                "hot_target": "",
                "ping_pong_files": [],
                "suggested_scout": "",
            },
            "telemetry_summary": {
                "window_s": 300.0,
                "signal_count": 0,
                "productive_count": 0,
                "undo_count": 0,
                "steer_count": 0,
                "fail_count": 0,
                "repeat_fail_target": "",
                "repeat_fail_count": 0,
                "context_thrash": 0.0,
                "ping_pong_score": 0.0,
                "idle_ratio": 1.0,
            },
            "hormone_hints": {
                "adrenaline": 0.0,
                "cortisol": 0.0,
                "dopamine": 0.0,
                "melatonin": 0.25,
            },
            "privacy_guarantees": {
                "camera": False,
                "microphone": False,
                "cloud_upload": False,
                "local_only": True,
            },
        }

    def anticipate_phase(
        self,
        now_ts: float | None = None,
        lead_minutes: float = 5.0,
    ) -> dict[str, Any]:
        """Predict upcoming circadian phase `lead_minutes` ahead for Anticipatory Metamorphosis."""
        now = float(time.time() if now_ts is None else now_ts)
        lead_m = max(0.0, float(lead_minutes))
        future_ts = now + lead_m * 60.0
        cur_day, cur_hour = _day_type_and_hour(now)
        tgt_day, tgt_hour = _day_type_and_hour(future_ts)

        with self._lock:
            target_counts = dict(self._circadian.get((tgt_day, tgt_hour), {}))
            if not target_counts:
                # Fallback to same hour across both day types if specific day_type is cold
                merged: dict[str, float] = {}
                for dt_key in ("weekday", "weekend"):
                    for ph, w in self._circadian.get((dt_key, tgt_hour), {}).items():
                        merged[ph] = merged.get(ph, 0.0) + w
                target_counts = merged
            current_phase = (
                self._signals[-1]["phase"]
                if self._signals
                else self._dominant_phase_locked(cur_day, cur_hour)
            )

        total_w = sum(target_counts.values())
        if total_w <= 0.0:
            distribution = {ph: 0.25 for ph in CIRCADIAN_PHASES}
            predicted_phase = "rest"
            confidence = 0.0
        else:
            distribution = {
                ph: round(target_counts.get(ph, 0.0) / total_w, 4)
                for ph in CIRCADIAN_PHASES
            }
            predicted_phase = max(
                CIRCADIAN_PHASES,
                key=lambda ph: (target_counts.get(ph, 0.0), -CIRCADIAN_PHASES.index(ph)),
            )
            # Confidence accounts for both dominance ratio and sample maturity
            dominance = target_counts.get(predicted_phase, 0.0) / total_w
            maturity = min(1.0, total_w / 3.0)
            confidence = round(_clamp01(dominance * (0.5 + 0.5 * maturity)), 4)

        phase_transition = bool(
            predicted_phase != current_phase and confidence >= 0.45
        )
        actions = (
            list(_METAMORPHOSIS_PLAYBOOK.get(predicted_phase, []))
            if confidence >= 0.35
            else []
        )

        return {
            "now_ts": now,
            "future_ts": future_ts,
            "lead_minutes": lead_m,
            "current_phase": current_phase,
            "predicted_phase": predicted_phase,
            "confidence": confidence,
            "phase_transition": phase_transition,
            "target_day_type": tgt_day,
            "target_hour": tgt_hour,
            "samples_observed": round(total_w, 2),
            "distribution": distribution,
            "metamorphosis_actions": actions,
            "law_2_compliant": True,
        }

    def _dominant_phase_locked(self, day_type: str, hour: int) -> str:
        counts = self._circadian.get((day_type, hour), {})
        if not counts:
            return "rest"
        return max(counts.items(), key=lambda kv: kv[1])[0]

    def circadian_summary(self) -> dict[str, Any]:
        with self._lock:
            slots: list[dict[str, Any]] = []
            for (day_type, hour), counts in sorted(self._circadian.items()):
                total = sum(counts.values())
                if total <= 0:
                    continue
                dominant = max(counts.items(), key=lambda kv: kv[1])[0]
                slots.append(
                    {
                        "day_type": day_type,
                        "hour": hour,
                        "dominant_phase": dominant,
                        "total_weight": round(total, 2),
                        "confidence": round(counts[dominant] / total, 4),
                    }
                )
        return {
            "learned_slots": len(slots),
            "slots": slots,
        }

    def status(self, now_ts: float | None = None) -> dict[str, Any]:
        assessment = self.assess(now_ts=now_ts)
        anticipation = self.anticipate_phase(now_ts=now_ts, lead_minutes=5.0)
        return {
            "organ": "CHIMERA-UMWELT",
            "idea": 7,
            "total_signals": self._total_recorded,
            "window_signals": len(self._signals),
            "assessment": assessment,
            "anticipation": anticipation,
            "circadian_slots": len(self._circadian),
            "ephemeral": self._ephemeral,
        }
