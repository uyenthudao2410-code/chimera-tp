"""CHIMERA OVERMIND CORTEX — Central Nervous System & Self-Healing Brain for Trinity v18."""

from __future__ import annotations

import base64
from collections import deque
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import threading
import time
from typing import Any
import urllib.parse
import urllib.request


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _shannon_entropy(data: str) -> float:
    if not data:
        return 0.0
    freq: dict[str, int] = {}
    for ch in data:
        freq[ch] = freq.get(ch, 0) + 1
    n = float(len(data))
    return -sum((cnt / n) * math.log2(cnt / n) for cnt in freq.values())


def _is_loopback_http(url: str) -> bool:
    try:
        p = urllib.parse.urlparse(str(url or "").strip())
        host = (p.hostname or "").lower()
        return p.scheme in ("http", "https") and host in ("127.0.0.1", "localhost", "::1")
    except Exception:
        return False


class EgressDlpGuard:
    """Zero-dependency DLP scanner & redactor blocking emails, non-loopback IPv4s, tokens, and encoded secrets."""

    _EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
    _IPV4_RE = re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b")
    _TOKEN_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
        ("oauth_ya29", re.compile(r"ya29\.[A-Za-z0-9._-]{8,}")),
        ("bearer_token", re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]{12,}")),
        ("github_pat", re.compile(r"gh[pousr]_[A-Za-z0-9_]{12,}")),
        ("api_sk", re.compile(r"sk-[A-Za-z0-9_-]{16,}")),
        ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    )
    _B64_CHUNK_RE = re.compile(r"\b[A-Za-z0-9+/]{24,}={0,2}\b")
    _SECRET_MARKERS = ("ya29.", "ghp_", "gho_", "ghu_", "ghs_", "sk-", "PRIVATE KEY")
    _ALLOWED_IPS = frozenset({"127.0.0.1", "0.0.0.0"})

    @classmethod
    def _is_encoded_secret(cls, chunk: str) -> bool:
        padded = chunk + ("=" * ((4 - len(chunk) % 4) % 4))
        try:
            raw = base64.b64decode(padded.encode("ascii"), validate=True)
        except Exception:
            return False
        if not raw:
            return False
        decoded = raw.decode("utf-8", errors="ignore")
        if any(m in decoded for m in cls._SECRET_MARKERS):
            return True
        if _shannon_entropy(decoded) >= 4.2 and any(x in decoded.lower() for x in ("token", "secret", "password")):
            return True
        return False

    @classmethod
    def scan_text(cls, text: str) -> dict[str, Any]:
        t0 = time.perf_counter()
        raw = str(text or "")
        categories: list[str] = []
        finding_count = 0

        emails = cls._EMAIL_RE.findall(raw)
        if emails:
            categories.append("email")
            finding_count += len(emails)

        ips = [ip for ip in cls._IPV4_RE.findall(raw) if ip not in cls._ALLOWED_IPS]
        if ips:
            categories.append("non_loopback_ip")
            finding_count += len(ips)

        for cat, pat in cls._TOKEN_PATTERNS:
            hits = pat.findall(raw)
            if hits:
                categories.append(cat)
                finding_count += len(hits)

        b64_hits = 0
        for chunk in cls._B64_CHUNK_RE.findall(raw):
            if cls._is_encoded_secret(chunk):
                b64_hits += 1
        if b64_hits:
            categories.append("base64_secret")
            finding_count += b64_hits

        return {
            "ok": finding_count == 0,
            "blocked": finding_count > 0,
            "finding_count": finding_count,
            "categories": categories,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 3),
        }

    @classmethod
    def redact_text(cls, text: str) -> str:
        out = str(text or "")
        out = cls._EMAIL_RE.sub("[REDACTED_EMAIL]", out)
        out = cls._IPV4_RE.sub(lambda m: m.group(0) if m.group(0) in cls._ALLOWED_IPS else "[REDACTED_IP]", out)
        for _cat, pat in cls._TOKEN_PATTERNS:
            out = pat.sub("[REDACTED_SECRET]", out)
        out = cls._B64_CHUNK_RE.sub(
            lambda m: "[REDACTED_B64_SECRET]" if cls._is_encoded_secret(m.group(0)) else m.group(0),
            out,
        )
        return out

    @classmethod
    def redact_obj(cls, obj: Any) -> Any:
        if isinstance(obj, str):
            return cls.redact_text(obj)
        if isinstance(obj, list):
            return [cls.redact_obj(x) for x in obj]
        if isinstance(obj, dict):
            return {str(k): cls.redact_obj(v) for k, v in obj.items()}
        return obj

    @classmethod
    def scan_payload(cls, payload: Any) -> dict[str, Any]:
        if isinstance(payload, str):
            return cls.scan_text(payload)
        try:
            serialized = json.dumps(payload, ensure_ascii=False)
        except Exception:
            serialized = str(payload)
        return cls.scan_text(serialized)


class BrainStateCRDT:
    """Persistent HLC-ordered LWW-CRDT converging kill-switch & governor state across Win <-> svhome restarts."""

    _FIELDS = (
        "kill_switch_active",
        "kill_switch_reason",
        "kill_switch_source",
        "kill_switch_auto",
        "governor_policy",
        "max_burn_rate_pct_hr",
    )

    def __init__(self, ops_dir: Path | str, node_id: str = "node") -> None:
        self.ops_dir = Path(ops_dir)
        self.ops_dir.mkdir(parents=True, exist_ok=True)
        self.node_id = str(node_id or "node")[:64]
        self.path = self.ops_dir / "brain_state_crdt.json"
        self._lock = threading.RLock()
        self._state: dict[str, Any] = {
            "kill_switch_active": False,
            "kill_switch_reason": "",
            "kill_switch_source": "init",
            "kill_switch_auto": False,
            "governor_policy": "work_first",
            "max_burn_rate_pct_hr": 12.0,
            "hlc_ts_ms": 0,
            "hlc_counter": 0,
            "hlc_node": self.node_id,
            "updated_at": None,
        }
        self._load()

    def _load(self) -> None:
        if not self.path.is_file():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8", errors="ignore"))
            if isinstance(raw, dict):
                with self._lock:
                    for key in (*self._FIELDS, "hlc_ts_ms", "hlc_counter", "hlc_node", "updated_at"):
                        if key in raw:
                            self._state[key] = raw[key]
                    self._state["kill_switch_active"] = bool(self._state.get("kill_switch_active", False))
                    self._state["hlc_ts_ms"] = int(self._state.get("hlc_ts_ms") or 0)
                    self._state["hlc_counter"] = int(self._state.get("hlc_counter") or 0)
        except Exception:
            pass

    def _save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(self.path)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._state)

    def mutate(self, updates: dict[str, Any], *, source: str = "local") -> dict[str, Any]:
        with self._lock:
            now_ms = int(time.time() * 1000)
            prev_ts = int(self._state.get("hlc_ts_ms") or 0)
            prev_cnt = int(self._state.get("hlc_counter") or 0)
            if now_ms > prev_ts:
                self._state["hlc_ts_ms"] = now_ms
                self._state["hlc_counter"] = 0
            else:
                self._state["hlc_ts_ms"] = prev_ts
                self._state["hlc_counter"] = prev_cnt + 1
            self._state["hlc_node"] = self.node_id
            for key in self._FIELDS:
                if key in updates and updates[key] is not None:
                    self._state[key] = updates[key]
            self._state["kill_switch_active"] = bool(self._state.get("kill_switch_active", False))
            if "kill_switch_source" not in updates and source:
                self._state["kill_switch_source"] = str(source)
            self._state["updated_at"] = _utc_now_iso()
            self._save()
            return dict(self._state)

    def merge(self, remote: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(remote, dict):
            return {"ok": False, "merged": False, "error": "invalid_remote_state", "state": self.snapshot()}
        r_ts = int(remote.get("hlc_ts_ms") or 0)
        r_cnt = int(remote.get("hlc_counter") or 0)
        r_node = str(remote.get("hlc_node") or "")
        with self._lock:
            l_tuple = (int(self._state.get("hlc_ts_ms") or 0), int(self._state.get("hlc_counter") or 0), str(self._state.get("hlc_node") or ""))
            r_tuple = (r_ts, r_cnt, r_node)
            if r_tuple > l_tuple and r_ts > 0:
                for key in self._FIELDS:
                    if key in remote and remote[key] is not None:
                        self._state[key] = remote[key]
                self._state["kill_switch_active"] = bool(self._state.get("kill_switch_active", False))
                self._state["hlc_ts_ms"] = r_ts
                self._state["hlc_counter"] = r_cnt
                self._state["hlc_node"] = r_node or self.node_id
                self._state["updated_at"] = str(remote.get("updated_at") or _utc_now_iso())
                self._save()
                return {"ok": True, "merged": True, "state": dict(self._state)}
            return {"ok": True, "merged": False, "state": dict(self._state)}


class PulseEventBus:
    """Zero-dependency bounded ring Pub/Sub event bus for Chimera Overmind cross-node coordination."""

    def __init__(self, node_id: str = "node", *, maxlen: int = 256) -> None:
        self.node_id = str(node_id or "node")[:64]
        self._lock = threading.Lock()
        self._seq = 0
        self._events: deque[dict[str, Any]] = deque(maxlen=max(32, int(maxlen)))

    def emit(
        self,
        topic: str,
        source: str,
        payload: dict[str, Any] | None = None,
        *,
        peer_url: str = "",
        from_peer: bool = False,
    ) -> dict[str, Any]:
        clean_payload = EgressDlpGuard.redact_obj(payload if isinstance(payload, dict) else {})
        with self._lock:
            self._seq += 1
            ev = {
                "seq": self._seq,
                "ts": _utc_now_iso(),
                "topic": str(topic or "SYSTEM")[:64],
                "source": str(source or "chimera")[:64],
                "node_id": self.node_id,
                "from_peer": bool(from_peer),
                "payload": clean_payload,
            }
            self._events.append(ev)

        target_peer = str(peer_url or "").rstrip("/")
        if target_peer and not from_peer and _is_loopback_http(target_peer):
            def _relay() -> None:
                try:
                    req = urllib.request.Request(
                        f"{target_peer}/api/overmind/pulse",
                        data=json.dumps({
                            "topic": ev["topic"],
                            "source": ev["source"],
                            "payload": ev["payload"],
                            "from_peer": True,
                        }, ensure_ascii=False).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    with urllib.request.urlopen(req, timeout=1.0) as resp:
                        resp.read(128)
                except Exception:
                    pass

            threading.Thread(target=_relay, daemon=True, name="overmind-pulse-relay").start()
        return ev

    def poll(self, since_seq: int = 0, limit: int = 50) -> dict[str, Any]:
        cap = max(1, min(256, int(limit or 50)))
        s_seq = int(since_seq or 0)
        with self._lock:
            rows = [ev for ev in self._events if ev["seq"] > s_seq]
            latest = self._seq
        return {"ok": True, "latest_seq": latest, "count": len(rows[-cap:]), "events": rows[-cap:]}

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {"ok": True, "latest_seq": self._seq, "buffered": len(self._events), "node_id": self.node_id}


class FlightRecorderRing:
    """8-MB style bounded zero-disk ring telemetry buffer freezing DLP-scrubbed cassettes on anomaly."""

    def __init__(self, ops_dir: Path | str, *, maxlen: int = 600, max_cassettes: int = 20) -> None:
        self.ops_dir = Path(ops_dir)
        self.cassettes_dir = self.ops_dir / "cassettes"
        self.maxlen = max(10, int(maxlen))
        self.max_cassettes = max(4, int(max_cassettes))
        self._lock = threading.Lock()
        self._frames: deque[dict[str, Any]] = deque(maxlen=self.maxlen)
        self._prev_tx_bytes: int | None = None
        self._prev_ts_mono: float | None = None
        self._last_freeze: dict[str, float] = {}

    def record_sample(self, frame: dict[str, Any], *, anomaly_cooldown_s: float = 300.0) -> dict[str, Any]:
        now_m = time.monotonic()
        clean_frame = EgressDlpGuard.redact_obj(dict(frame or {}))
        clean_frame.setdefault("ts", _utc_now_iso())

        tx_bps = float(clean_frame.get("phantom_tx_bps") or 0.0)
        if "tx_bytes" in clean_frame and clean_frame.get("phantom_tx_bps") is None:
            cur_tx = int(clean_frame.get("tx_bytes") or 0)
            with self._lock:
                if self._prev_tx_bytes is not None and self._prev_ts_mono is not None:
                    dt = now_m - self._prev_ts_mono
                    if dt > 0.1 and cur_tx >= self._prev_tx_bytes:
                        tx_bps = round((cur_tx - self._prev_tx_bytes) / dt, 1)
                self._prev_tx_bytes = cur_tx
                self._prev_ts_mono = now_m
            clean_frame["phantom_tx_bps"] = tx_bps

        with self._lock:
            self._frames.append(clean_frame)

        trigger_reason = ""
        if tx_bps > 2_000_000.0:
            trigger_reason = "phantom_tx_storm"
        elif float(clean_frame.get("phantom_rtt_ms") or 0.0) > 150.0:
            trigger_reason = "phantom_high_rtt"
        elif int(clean_frame.get("phantom_conns") or 0) > 25:
            trigger_reason = "phantom_conn_spike"

        frozen = None
        if trigger_reason:
            with self._lock:
                last_t = self._last_freeze.get(trigger_reason, 0.0)
                should_freeze = (now_m - last_t) >= float(anomaly_cooldown_s)
                if should_freeze:
                    self._last_freeze[trigger_reason] = now_m
            if should_freeze:
                frozen = self.freeze_cassette(trigger_reason, extra={"trigger_frame": clean_frame})
        return {"ok": True, "tx_bps": tx_bps, "trigger_reason": trigger_reason, "frozen_cassette": frozen}

    def freeze_cassette(self, reason: str, *, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        self.cassettes_dir.mkdir(parents=True, exist_ok=True)
        slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", str(reason or "manual"))[:48].strip("_") or "manual"
        ts_tag = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        with self._lock:
            frames = list(self._frames)
        payload = EgressDlpGuard.redact_obj(
            {
                "reason": str(reason or "manual"),
                "frozen_at": _utc_now_iso(),
                "frame_count": len(frames),
                "frames": frames[-120:],
                "extra": extra or {},
            }
        )
        raw_json = json.dumps(payload, indent=2, ensure_ascii=False)
        dlp_check = EgressDlpGuard.scan_text(raw_json)
        fname = f"cassette_{ts_tag}_{slug}.json"
        fpath = self.cassettes_dir / fname
        fpath.write_text(raw_json + "\n", encoding="utf-8")

        existing = sorted(self.cassettes_dir.glob("cassette_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in existing[self.max_cassettes :]:
            try:
                old.unlink()
            except OSError:
                pass

        return {
            "ok": True,
            "file": fname,
            "path": str(fpath),
            "frame_count": len(frames),
            "bytes": len(raw_json.encode("utf-8")),
            "dlp_clean": bool(dlp_check["ok"]),
        }

    def status(self) -> dict[str, Any]:
        with self._lock:
            frames = list(self._frames)
        cassettes: list[dict[str, Any]] = []
        if self.cassettes_dir.is_dir():
            for cf in sorted(self.cassettes_dir.glob("cassette_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:10]:
                try:
                    cassettes.append({"file": cf.name, "bytes": cf.stat().st_size})
                except OSError:
                    continue
        est_kb = round((len(frames) * 320) / 1024.0, 2)
        return {
            "ok": True,
            "buffered_frames": len(frames),
            "max_frames": self.maxlen,
            "est_memory_kb": est_kb,
            "last_frame": frames[-1] if frames else None,
            "cassettes": cassettes,
        }


class TriTierWorkStealingPlanner:
    """Unified Win-12T (Turbo when idle) <-> svhome (24/7) <-> Colab (CPU_HIGH_MEM) task scheduler."""

    @staticmethod
    def plan(
        task_type: str,
        *,
        stack: list[str] | None = None,
        est_sec: float = 15.0,
        win_governor: dict[str, Any] | None = None,
        svhome_free_ram_gb: float = 5.0,
        colab_cu: float = 0.0,
    ) -> dict[str, Any]:
        tt = str(task_type or "light_daemon").strip().lower()
        st = {str(s).lower() for s in (stack or [])}
        gov = win_governor if isinstance(win_governor, dict) else {}
        win_mode = str(gov.get("mode") or "USER_ACTIVE").upper()
        win_idle_ok = win_mode == "TURBO_IDLE" and bool(gov.get("accept_heavy_jobs", False))
        heavy_stack = bool(st & {"node", "npm", "rust", "cpp", "c++", "docker", "monorepo"}) or float(est_sec or 0.0) > 25.0

        if tt in ("colab_test", "verify_patch") or (tt in ("test", "verify") and heavy_stack):
            if float(colab_cu or 0.0) > 10.0:
                return {
                    "ok": True,
                    "task_type": tt,
                    "executor": "colab_cpu_high_mem",
                    "allow_heavy_gpu": False,
                    "keep_session": False,
                    "fallback": "svhome_sovereign_24x7",
                    "preempt_budget_ms": None,
                    "reason": "heavy_untrusted_verification_offloaded_to_colab",
                }
            return {
                "ok": True,
                "task_type": tt,
                "executor": "svhome_sovereign_24x7",
                "fallback": "github_fork_ci",
                "preempt_budget_ms": None,
                "reason": "colab_cu_low_fallback_svhome",
            }

        if tt in ("build", "index", "mcts", "compile", "heavy_cpu"):
            if win_idle_ok:
                return {
                    "ok": True,
                    "task_type": tt,
                    "executor": "win_12t_turbo_idle",
                    "fallback": "svhome_sovereign_24x7",
                    "preempt_budget_ms": 50,
                    "reason": "win_idle_turbo_work_steal_active",
                }
            return {
                "ok": True,
                "task_type": tt,
                "executor": "svhome_sovereign_24x7",
                "fallback": "colab_cpu_high_mem" if float(colab_cu or 0.0) > 10.0 else "local_throttled",
                "preempt_budget_ms": 50,
                "reason": f"win_protected_{win_mode.lower()}_routed_to_svhome",
            }

        if tt in ("codex_patch", "codex_solve", "codex_repair"):
            return {
                "ok": True,
                "task_type": tt,
                "executor": "tquota_codex_phantom_5ms",
                "lean_mode": True,
                "fallback": "svhome_local_tquota",
                "preempt_budget_ms": None,
                "reason": "codex_first_lean_headless_via_phantom",
            }

        return {
            "ok": True,
            "task_type": tt,
            "executor": "svhome_sovereign_24x7",
            "fallback": "win_12t_turbo_idle" if win_idle_ok else "svhome_sovereign_24x7",
            "preempt_budget_ms": 50 if win_idle_ok else None,
            "svhome_free_ram_gb": round(float(svhome_free_ram_gb or 0.0), 2),
            "reason": "sovereign_default_svhome",
        }


class OvermindCortex:
    """Unified coordinator exposing CRDT, DLP, Pulse Bus, Flight Recorder, Planner, and Canary Ship Check."""

    def __init__(self, ops_dir: Path | str, node_id: str = "node") -> None:
        from .midbrain_dopamine import MidbrainDopamineEngine
        from .symbiote_engine import ChimeraSymbioteEngine

        self.ops_dir = Path(ops_dir)
        self.node_id = str(node_id or "node")
        self.dlp = EgressDlpGuard
        self.crdt = BrainStateCRDT(self.ops_dir, node_id=self.node_id)
        self.pulse = PulseEventBus(node_id=self.node_id)
        self.flight_recorder = FlightRecorderRing(self.ops_dir)
        self.planner = TriTierWorkStealingPlanner()
        self.midbrain = MidbrainDopamineEngine(self.ops_dir, pulse_bus=self.pulse)
        self.symbiote = ChimeraSymbioteEngine(self.ops_dir, pulse_bus=self.pulse)

    @staticmethod
    def _get_json(url: str, timeout_s: float = 2.0) -> dict[str, Any] | None:
        if not _is_loopback_http(url):
            return None
        try:
            with urllib.request.urlopen(url, timeout=timeout_s) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="ignore"))
                return data if isinstance(data, dict) else {"raw": data}
        except Exception:
            return None

    @classmethod
    def canary_ship_check(
        cls,
        local_base: str = "http://127.0.0.1:9780",
        peer_base: str = "http://127.0.0.1:9789",
        *,
        delta_window_s: float = 1.5,
    ) -> dict[str, Any]:
        """Verify 4 hard Overmind shipping invariants (PHANTOM RTT, zero storm, RSS, CRDT parity & DLP)."""
        loc = str(local_base or "").rstrip("/")
        peer = str(peer_base or "").rstrip("/")

        ph1 = cls._get_json(f"{loc}/api/phantom/status") or {}
        cli1 = ph1.get("client") if isinstance(ph1.get("client"), dict) else {}
        time.sleep(max(0.2, float(delta_window_s)))
        ph2 = cls._get_json(f"{loc}/api/phantom/status") or {}
        cli2 = ph2.get("client") if isinstance(ph2.get("client"), dict) else {}

        tx1 = int(cli1.get("tx_bytes") or 0)
        tx2 = int(cli2.get("tx_bytes") or 0)
        tx_delta = max(0, tx2 - tx1)
        rtt_ms = float(cli2.get("direct_rtt_ms") or 9999.0) if cli2 else 0.0
        phantom_mode = str(cli2.get("mode") or ("SERVER_ONLY" if not cli2 else "DISCONNECTED"))

        st_loc = cls._get_json(f"{loc}/api/status") or {}
        zw_loc = st_loc.get("zero_weight") if isinstance(st_loc.get("zero_weight"), dict) else {}
        ram_ok_loc = bool(zw_loc.get("zero_weight_ok", True))

        ov_loc = cls._get_json(f"{loc}/api/overmind/state") or {}
        crdt_loc = ov_loc.get("crdt") if isinstance(ov_loc.get("crdt"), dict) else {}

        ov_peer = cls._get_json(f"{peer}/api/overmind/state") if peer else None
        st_peer = cls._get_json(f"{peer}/api/status") if peer else None
        crdt_peer = (ov_peer or {}).get("crdt") if isinstance((ov_peer or {}).get("crdt"), dict) else {}
        zw_peer = (st_peer or {}).get("zero_weight") if isinstance((st_peer or {}).get("zero_weight"), dict) else {}
        ram_ok_peer = bool(zw_peer.get("zero_weight_ok", True)) if st_peer else True

        crdt_synced = (
            bool(crdt_loc)
            and (
                not peer
                or (
                    bool(crdt_peer)
                    and bool(crdt_loc.get("kill_switch_active")) == bool(crdt_peer.get("kill_switch_active"))
                )
            )
        )
        dlp_check = EgressDlpGuard.scan_payload({"crdt_loc": crdt_loc, "crdt_peer": crdt_peer, "mode": phantom_mode})
        phantom_ok = (not cli2) or (bool(cli2.get("connected")) and phantom_mode == "PHANTOM_5MS_DIRECT" and rtt_ms < 25.0)
        no_storm = tx_delta < 500_000
        ram_ok = ram_ok_loc and ram_ok_peer
        dlp_clean = bool(dlp_check["ok"])

        checks = {
            "phantom_ok": phantom_ok,
            "no_storm": no_storm,
            "ram_ok": ram_ok,
            "crdt_synced": crdt_synced,
            "dlp_clean": dlp_clean,
        }
        return {
            "ok": all(checks.values()),
            "checks": checks,
            "metrics": {
                "phantom_mode": phantom_mode,
                "phantom_rtt_ms": rtt_ms,
                "tx_delta_bytes": tx_delta,
                "loc_ram_mb": zw_loc.get("daemon_ram_mb"),
                "peer_ram_mb": zw_peer.get("daemon_ram_mb") if st_peer else None,
                "loc_ks_active": crdt_loc.get("kill_switch_active"),
                "peer_ks_active": crdt_peer.get("kill_switch_active") if crdt_peer else None,
                "loc_hlc_ts_ms": crdt_loc.get("hlc_ts_ms"),
                "peer_hlc_ts_ms": crdt_peer.get("hlc_ts_ms") if crdt_peer else None,
            },
        }
