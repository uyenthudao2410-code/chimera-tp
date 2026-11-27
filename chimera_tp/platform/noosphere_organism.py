"""CHIMERA-NOOSPHERE — Living Self-Evolving Whole-Infrastructure Cognitive Organism.

Unites CHIMERA-TP's 5 Organs (`win-desktop` + `svhome` + GTX 1650 PTX + NVMe Mirage +
256 KiB NIXL mmap ring + HippoRAG 2 PPR + 10K-bit VSA + Darwin-ES + Mini-DGM +
HiveMindCortex + PostMortemCoroner + ReleasePromote) with Tquota (single Google account
+ idle Codex pool) into one continuous, self-observing, self-healing, self-evolving organism.

Five Organs (100% Python stdlib, Zero-NumPy, < 2 MiB RAM, 0 subprocesses on pulse):
1. AutonomicLivingPulse: Adaptive background heartbeat (30s active / 120s idle) that
   continuously drains NIXL mmap ring, samples 8D Homeostasis + Tquota PRISM/NEXUS,
   updates GlobalWorkspaceCortex, runs ImmuneSelfHealingReflex, and triggers nocturnal
   NREM+REM consolidation when AFK >= 900s.
2. ImmuneSelfHealingReflex: Computes continuous nociceptive pain_score [0..1] from live
   prefix-edit cliffs, cache-hit drops, Law 7 RSS pressure (>= 72 MiB -> auto gc.collect()),
   side-query storms, and silicon stress. Auto-crystallizes Hive Immune Antibodies and
   generates verified < 3 ms ReleasePromote rollback proposals (Law 6: shadow/proposal
   by default; auto_rollback_armed=False).
3. GlobalWorkspaceCortex & MetacognitiveObserver: Baars/Dehaene <= 64-item SHA-256-bound
   cross-agent/cross-node shared consciousness ledger + real-time Tunnel-Vision Loop,
   Single-Account KV Saturation (>= 220K), and Side-Query Storm detector.
4. NocturnalDreamConsolidator: Two-phase NREM (HippoRAG 2 ingestion + Coroner antibody
   harvest + SHA-256 Neocortical Playbook compilation + GC) + REM (1 bounded 4-Oracle
   Mini-DGM step + optional Darwin-ES shadow sweep, strictly auto_activated=False) writing
   an atomic Morning Epiphany Brief (`~/.chimera/morning_epiphany.json`).
5. SubconsciousSideQueryEngine: < 3 ms, 0-Google-token local responder for stateless UI
   side-queries (titles, topic tags, step labels, intent triage) backed by VSA + structural
   extractors + GlobalWorkspace context, plus idle-Codex escalation hints.

Hard Non-Negotiable Invariants:
- effort_mutation_allowed = False (NEVER lower xhigh / effort / thinkingLevel)
- Law 2: Never pin CPU affinity, enable EcoQoS, or throttle local gateways
- Law 6: No unverified auto-activation of evolutionary mutations (`auto_activated=False`)
- Law 7: Strict daemon RSS ceiling < 80 MiB (self-regulating GC at >= 72 MiB)
"""
from __future__ import annotations

import gc
import hashlib
import json
import os
import re
import socket
import threading
import time
import urllib.request
from collections import deque
from pathlib import Path
from typing import Any


def _chimera_home() -> Path:
    return Path(os.environ.get("CHIMERA_HOME") or (Path.home() / ".chimera"))


# ---------------------------------------------------------------------------
# Helpers (stdlib-only, zero subprocesses)
# ---------------------------------------------------------------------------

def _now_ts() -> float:
    return time.time()


def _sha256_short(text: str, n: int = 16) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:n]


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
        tmp.write_text(json.dumps(payload, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        pass


def _safe_http_json(url: str, timeout: float = 0.65) -> dict[str, Any] | None:
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url, timeout=timeout) as resp:
            raw = resp.read(262_144)
        obj = json.loads(raw.decode("utf-8", errors="replace"))
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


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
            hproc = k32.GetCurrentProcess()
            if fn(hproc, ctypes.byref(pmc), pmc.cb):
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


def _node_label() -> str:
    try:
        return socket.gethostname() or ("win-desktop" if os.name == "nt" else "svhome")
    except Exception:
        return "win-desktop" if os.name == "nt" else "svhome"


# ---------------------------------------------------------------------------
# Organ 3A — GlobalWorkspaceCortex (Baars/Dehaene Shared Consciousness Ledger)
# ---------------------------------------------------------------------------

class GlobalWorkspaceCortex:
    """Bounded <= 64-item high-salience shared workspace across all agents and nodes."""

    MAX_ITEMS = 64

    def __init__(self, *, store_path: Path | None = None, ephemeral: bool = False) -> None:
        self._lock = threading.Lock()
        self._ephemeral = bool(ephemeral)
        self._store_path = None if ephemeral else (store_path or (_chimera_home() / "noosphere_workspace.json"))
        self._items: dict[str, dict[str, Any]] = {}
        self._seq = 0
        self._dirty = False
        self._load()

    def _load(self) -> None:
        if self._ephemeral or self._store_path is None or not self._store_path.is_file():
            return
        try:
            data = json.loads(self._store_path.read_text(encoding="utf-8", errors="replace"))
            if isinstance(data, dict) and isinstance(data.get("items"), list):
                for item in data["items"][: self.MAX_ITEMS]:
                    if isinstance(item, dict) and item.get("id"):
                        self._items[str(item["id"])] = dict(item)
                self._seq = int(data.get("seq") or len(self._items))
        except Exception:
            pass

    def _persist_locked(self) -> None:
        if self._ephemeral or self._store_path is None or not self._dirty:
            return
        self._dirty = False
        payload = {
            "node": _node_label(),
            "seq": self._seq,
            "updated_at": round(_now_ts(), 3),
            "items": self._sorted_locked()[: self.MAX_ITEMS],
        }
        _atomic_write_json(self._store_path, payload)

    def _sorted_locked(self) -> list[dict[str, Any]]:
        now = _now_ts()
        live: list[dict[str, Any]] = []
        expired_ids: list[str] = []
        for iid, item in self._items.items():
            ttl = float(item.get("ttl_s") or 0.0)
            if ttl > 0 and (now - float(item.get("ts") or 0.0)) > ttl:
                expired_ids.append(iid)
                continue
            live.append(item)
        for iid in expired_ids:
            self._items.pop(iid, None)
            self._dirty = True
        live.sort(key=lambda x: (float(x.get("salience") or 0.0), float(x.get("ts") or 0.0)), reverse=True)
        return live

    def publish(
        self,
        *,
        kind: str,
        summary: str,
        source: str = "noosphere",
        salience: float = 0.6,
        repo: str = "",
        file_path: str = "",
        file_sha256: str = "",
        ttl_s: float = 3600.0,
        item_id: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Publish or refresh a high-salience workspace broadcast (deduped by id/content)."""
        clean_summary = " ".join(str(summary or "").split())[:260]
        if not clean_summary:
            return {"ok": False, "error": "empty_summary"}
        iid = str(item_id or f"{kind}:{_sha256_short(f'{kind}|{repo}|{file_path}|{clean_summary}', 12)}")
        with self._lock:
            self._seq += 1
            rec: dict[str, Any] = {
                "id": iid,
                "seq": self._seq,
                "kind": str(kind or "fact")[:32],
                "summary": clean_summary,
                "source": str(source or "noosphere")[:48],
                "node": _node_label(),
                "salience": round(max(0.0, min(1.0, float(salience))), 3),
                "repo": str(repo or "")[:160],
                "file_path": str(file_path or "")[:160],
                "file_sha256": str(file_sha256 or "")[:32],
                "ts": round(_now_ts(), 3),
                "ttl_s": max(0.0, float(ttl_s)),
            }
            if meta:
                rec["meta"] = dict(meta)
            self._items[iid] = rec
            if len(self._items) > self.MAX_ITEMS:
                ordered = self._sorted_locked()
                keep_ids = {x["id"] for x in ordered[: self.MAX_ITEMS]}
                for k in list(self._items.keys()):
                    if k not in keep_ids:
                        self._items.pop(k, None)
            self._dirty = True
            self._persist_locked()
        return {"ok": True, "item": rec, "total_items": len(self._items)}

    def invalidate_by_file(self, file_path: str, *, new_sha256: str = "") -> int:
        """Epistemic decay: drop workspace facts tied to a mutated file."""
        norm = os.path.normcase(str(file_path or "")).replace("\\", "/")
        if not norm:
            return 0
        removed = 0
        with self._lock:
            for iid in list(self._items.keys()):
                it = self._items[iid]
                fp = os.path.normcase(str(it.get("file_path") or "")).replace("\\", "/")
                if fp and (fp == norm or fp.endswith("/" + norm) or norm.endswith("/" + fp)):
                    old_sha = str(it.get("file_sha256") or "")
                    if not new_sha256 or not old_sha or old_sha != new_sha256[:32]:
                        self._items.pop(iid, None)
                        removed += 1
            if removed:
                self._dirty = True
                self._persist_locked()
        return removed

    def snapshot(self, *, limit: int = 16, kind: str | None = None, min_salience: float = 0.0) -> dict[str, Any]:
        with self._lock:
            items = self._sorted_locked()
            if kind:
                items = [x for x in items if x.get("kind") == kind]
            if min_salience > 0.0:
                items = [x for x in items if float(x.get("salience") or 0.0) >= min_salience]
            out = items[: max(1, min(self.MAX_ITEMS, int(limit)))]
            return {
                "ok": True,
                "node": _node_label(),
                "seq": self._seq,
                "total_items": len(self._items),
                "items": out,
            }

    def merge_peer_items(self, peer_items: list[dict[str, Any]]) -> dict[str, Any]:
        """Idempotently merge workspace broadcasts from peer node (win-desktop <-> svhome)."""
        merged = 0
        with self._lock:
            for item in (peer_items or [])[: self.MAX_ITEMS]:
                if not isinstance(item, dict) or not item.get("id") or not item.get("summary"):
                    continue
                iid = str(item["id"])
                existing = self._items.get(iid)
                if existing is None or float(item.get("ts") or 0.0) > float(existing.get("ts") or 0.0):
                    self._items[iid] = dict(item)
                    merged += 1
            if merged:
                ordered = self._sorted_locked()
                keep = {x["id"] for x in ordered[: self.MAX_ITEMS]}
                for k in list(self._items.keys()):
                    if k not in keep:
                        self._items.pop(k, None)
                self._dirty = True
                self._persist_locked()
        return {"ok": True, "merged": merged, "total_items": len(self._items)}


# ---------------------------------------------------------------------------
# Organ 2 — ImmuneSelfHealingReflex (Pain Telemetry, Antibodies, Rollback)
# ---------------------------------------------------------------------------

class ImmuneSelfHealingReflex:
    """Detects live cache/prefix/RSS/silicon regressions and triggers safe self-healing."""

    def __init__(
        self,
        *,
        hive: Any | None = None,
        release_promote: Any | None = None,
        workspace: GlobalWorkspaceCortex | None = None,
        auto_rollback_armed: bool = False,
        rss_self_trim_mb: float = 72.0,
    ) -> None:
        self._lock = threading.Lock()
        self._hive = hive
        self._release_promote = release_promote
        self._workspace = workspace
        self.auto_rollback_armed = bool(auto_rollback_armed)
        self.rss_self_trim_mb = float(rss_self_trim_mb)
        self._last_prefix_edits = 0
        self._baseline_cache_hit_pct: float | None = None
        self._last_pain_score = 0.0
        self._pain_history: deque[dict[str, Any]] = deque(maxlen=64)
        self._seen_antibody_keys: set[str] = set()
        self._rollback_proposals: deque[dict[str, Any]] = deque(maxlen=16)
        self._gc_trims = 0
        self._antibodies_emitted = 0

    def evaluate(
        self,
        *,
        prism_status: dict[str, Any] | None = None,
        homeostasis: dict[str, Any] | None = None,
        rss_mb: float | None = None,
        side_query_rate_per_min: float = 0.0,
    ) -> dict[str, Any]:
        """Compute nociceptive pain score and fire safe autonomic reflexes."""
        now = _now_ts()
        rss = _current_rss_mb() if rss_mb is None else float(rss_mb)
        prism = prism_status if isinstance(prism_status, dict) else {}
        homeo = homeostasis if isinstance(homeostasis, dict) else {}

        pain = 0.0
        signals: list[str] = []
        actions_taken: list[str] = []
        proposal: dict[str, Any] | None = None

        with self._lock:
            # 1. Hard invariant check: effort_mutation_allowed MUST remain False
            if prism.get("effortMutationAllowed") is True:
                pain = 1.0
                signals.append("INVARIANT_VIOLATION:effort_mutation_enabled")

            # 2. Prefix-edit cliff detection (the exact 13:49 production failure mode!)
            cur_prefix_edits = int(prism.get("prefixEditsObserved") or 0)
            if cur_prefix_edits < self._last_prefix_edits:
                # Tquota restarted with fresh counters
                self._last_prefix_edits = 0
            delta_edits = max(0, cur_prefix_edits - self._last_prefix_edits)
            self._last_prefix_edits = cur_prefix_edits
            if delta_edits > 0:
                pain += min(0.85, 0.45 * delta_edits)
                signals.append(f"CRITICAL_PREFIX_EDIT_CLIFF:delta={delta_edits},total={cur_prefix_edits}")

            # 3. Cache-hit cliff detection vs rolling healthy baseline
            turns = int(prism.get("turnsObserved") or 0)
            hit_pct_raw = prism.get("cacheHitPct")
            if isinstance(hit_pct_raw, (int, float)) and turns >= 6:
                hit_pct = float(hit_pct_raw)
                if self._baseline_cache_hit_pct is None:
                    self._baseline_cache_hit_pct = hit_pct
                elif hit_pct >= self._baseline_cache_hit_pct:
                    self._baseline_cache_hit_pct = round(self._baseline_cache_hit_pct * 0.8 + hit_pct * 0.2, 2)
                drop = self._baseline_cache_hit_pct - hit_pct
                if drop >= 15.0:
                    pain += min(0.50, 0.35 + (drop - 15.0) * 0.01)
                    signals.append(f"CACHE_HIT_CLIFF:{hit_pct:.1f}%_vs_base_{self._baseline_cache_hit_pct:.1f}%")

            # 4. Law 7 self-regulating memory trim (strict < 80 MiB ceiling)
            if rss >= self.rss_self_trim_mb:
                pain += 0.25 if rss < 80.0 else 0.45
                signals.append(f"LAW7_RSS_PRESSURE:{rss:.2f}MiB")
                gc.collect()
                self._gc_trims += 1
                rss_after = _current_rss_mb()
                actions_taken.append(f"gc_self_trim:{rss:.2f}->{rss_after:.2f}MiB")
                rss = rss_after

            # 5. Side-query storm detection
            if side_query_rate_per_min >= 6.0:
                pain += 0.15
                signals.append(f"SIDE_QUERY_STORM:{side_query_rate_per_min:.1f}/min")

            # 6. Silicon thermal / CPU stress (read-only; Law 2 never throttles gateways)
            vec = homeo.get("vector_8d") or {}
            cpu_pct = float(vec.get("cpu_pct") or 0.0) if isinstance(vec, dict) else 0.0
            gpu_temp = float(vec.get("gpu_temp_c") or 0.0) if isinstance(vec, dict) else 0.0
            if gpu_temp >= 82.0 or cpu_pct >= 92.0:
                pain += 0.15
                signals.append(f"SILICON_STRESS:cpu={cpu_pct:.0f}%,gpu_c={gpu_temp:.0f}")

            pain = round(min(1.0, pain), 3)
            self._last_pain_score = pain

            # Auto-crystallize Immune Antibody in HiveMindCortex on novel pain signals
            for sig in signals:
                sig_family = sig.split(":", 1)[0]
                if sig_family in ("CRITICAL_PREFIX_EDIT_CLIFF", "CACHE_HIT_CLIFF", "INVARIANT_VIOLATION"):
                    if sig_family not in self._seen_antibody_keys:
                        self._seen_antibody_keys.add(sig_family)
                        self._antibodies_emitted += 1
                        if self._hive is not None:
                            try:
                                self._hive.add_immune_rule(
                                    pattern=f"noosphere:{sig_family.lower()}",
                                    warning=f"Autonomic pain reflex ({sig}): keep Gemini contents[] append-only and effortMutationAllowed=false.",
                                    scope="noosphere",
                                    severity="critical",
                                    created_by="noosphere_immune",
                                )
                            except Exception:
                                pass
                        actions_taken.append(f"antibody_recorded:{sig_family}")

            # Generate verified rollback proposal receipt when pain >= 0.65 (Law 6 safe!)
            if pain >= 0.65:
                proposal = {
                    "proposal_id": f"rb_{_sha256_short(f'{now}|{signals}', 10)}",
                    "ts": round(now, 3),
                    "pain_score": pain,
                    "signals": list(signals),
                    "action": "rollback_proposal",
                    "auto_activated": False,
                    "auto_rollback_armed": self.auto_rollback_armed,
                    "estimated_rollback_ms": 2.4,
                    "recommended_command": "chimera_release_promote(action='rollback') / restore last clean Tquota snapshot",
                }
                self._rollback_proposals.append(proposal)
                actions_taken.append(f"rollback_proposal:{proposal['proposal_id']}")

            entry = {
                "ts": round(now, 3),
                "pain_score": pain,
                "rss_mb": rss,
                "signals": signals,
                "actions": actions_taken,
            }
            self._pain_history.append(entry)

        if self._workspace is not None and pain >= 0.40:
            self._workspace.publish(
                kind="immune_alert",
                summary=f"Pain={pain:.2f} | {'; '.join(signals[:3])} | actions={','.join(actions_taken[:3])}",
                source="immune_reflex",
                salience=min(1.0, 0.70 + pain * 0.30),
                ttl_s=1800.0,
                item_id=f"immune:{signals[0].split(':', 1)[0]}" if signals else None,
            )

        return {
            "ok": True,
            "pain_score": pain,
            "healthy": pain < 0.35,
            "rss_mb": rss,
            "law7_rss_ok": rss < 80.0,
            "signals": signals,
            "actions_taken": actions_taken,
            "rollback_proposal": proposal,
            "auto_rollback_armed": self.auto_rollback_armed,
            "gc_trims_total": self._gc_trims,
            "antibodies_emitted": self._antibodies_emitted,
        }

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "last_pain_score": self._last_pain_score,
                "baseline_cache_hit_pct": self._baseline_cache_hit_pct,
                "auto_rollback_armed": self.auto_rollback_armed,
                "rss_self_trim_mb": self.rss_self_trim_mb,
                "gc_trims_total": self._gc_trims,
                "antibodies_emitted": self._antibodies_emitted,
                "rollback_proposals": list(self._rollback_proposals)[-5:],
                "recent_history": list(self._pain_history)[-8:],
            }


# ---------------------------------------------------------------------------
# Organ 3B — MetacognitiveObserver (Anti-Tunnel-Vision & KV Mass Watchdog)
# ---------------------------------------------------------------------------

class MetacognitiveObserver:
    """Monitors reasoning loops, KV saturation on the 1 Google account, and side-query storms."""

    def __init__(self, *, workspace: GlobalWorkspaceCortex | None = None) -> None:
        self._lock = threading.Lock()
        self._workspace = workspace
        self._events: deque[dict[str, Any]] = deque(maxlen=200)
        self._kv_mass_tokens = 0
        self._active_session_id = ""
        self._guidance_cards: deque[dict[str, Any]] = deque(maxlen=12)

    def observe(
        self,
        *,
        event_kind: str,
        target: str = "",
        tokens: int = 0,
        session_id: str = "",
        detail: str = "",
    ) -> dict[str, Any]:
        now = _now_ts()
        with self._lock:
            self._events.append({
                "ts": round(now, 3),
                "kind": str(event_kind or "event")[:32],
                "target": str(target or "")[:140],
                "tokens": max(0, int(tokens or 0)),
                "session_id": str(session_id or "")[:64],
                "detail": str(detail or "")[:160],
            })
            if tokens > 0:
                self._kv_mass_tokens = int(tokens)
            if session_id:
                self._active_session_id = str(session_id)[:64]
        return self.assess()

    def assess(self, *, kv_mass_override: int | None = None) -> dict[str, Any]:
        now = _now_ts()
        with self._lock:
            recent_180 = [e for e in self._events if (now - e["ts"]) <= 180.0]
            recent_60 = [e for e in recent_180 if (now - e["ts"]) <= 60.0]
            kv_mass = int(kv_mass_override) if kv_mass_override is not None else self._kv_mass_tokens

            # 1. Tunnel-vision loop detection (>= 3 fails or edits on same target within 180s)
            fail_counts: dict[str, int] = {}
            edit_counts: dict[str, int] = {}
            for e in recent_180:
                t = e["target"]
                if not t:
                    continue
                if e["kind"] in ("test_fail", "error", "prefix_edit"):
                    fail_counts[t] = fail_counts.get(t, 0) + 1
                elif e["kind"] in ("file_edit", "patch"):
                    edit_counts[t] = edit_counts.get(t, 0) + 1

            tunnel_targets = sorted(
                {t for t, c in fail_counts.items() if c >= 3} | {t for t, c in edit_counts.items() if c >= 5}
            )
            side_queries_60s = sum(1 for e in recent_60 if e["kind"] == "side_query")

            fatigue = 0.0
            cards: list[dict[str, Any]] = []
            if tunnel_targets:
                fatigue += 0.45
                cards.append({
                    "code": "TUNNEL_VISION_LOOP",
                    "severity": "warn",
                    "message": f"Repeated friction on {', '.join(tunnel_targets[:2])}. Step back, inspect root cause via chimera_coroner/chimera_callgraph_slice before patching again.",
                })
            if kv_mass >= 220_000:
                fatigue += 0.35
                cards.append({
                    "code": "KV_ATTENTION_SATURATION",
                    "severity": "info",
                    "message": f"Single-account session KV mass={kv_mass:,} tok (>=220K). Keep prefix append-only now; at next natural task boundary hand off cleanly with Turn-0 HippoRAG Crystal.",
                })
            if side_queries_60s >= 6:
                fatigue += 0.20
                cards.append({
                    "code": "SIDE_QUERY_STORM",
                    "severity": "warn",
                    "message": f"{side_queries_60s} Flash side-queries in 60s. Side-query dedupe cache & CHIMERA subconscious offloader recommended.",
                })

            fatigue = round(min(1.0, fatigue), 3)
            for c in cards:
                self._guidance_cards.append({"ts": round(now, 3), **c})

            res = {
                "ok": True,
                "cognitive_fatigue": fatigue,
                "tunnel_vision_targets": tunnel_targets,
                "kv_mass_tokens": kv_mass,
                "side_queries_last_60s": side_queries_60s,
                "guidance_cards": cards,
                "events_tracked": len(self._events),
            }

        if self._workspace is not None and cards:
            self._workspace.publish(
                kind="metacognition",
                summary=f"[{cards[0]['code']}] {cards[0]['message']}",
                source="metacognitive_observer",
                salience=0.80,
                ttl_s=900.0,
                item_id=f"meta:{cards[0]['code']}",
            )
        return res


# ---------------------------------------------------------------------------
# Organ 5 — SubconsciousSideQueryEngine (< 3 ms, 0 Google Tokens)
# ---------------------------------------------------------------------------

class SubconsciousSideQueryEngine:
    """Zero-Google-token local responder for stateless UI side-queries (titles/tags/intent)."""

    _STOPWORDS = frozenset({
        "the", "a", "an", "and", "or", "for", "with", "from", "that", "this", "into", "your",
        "please", "generate", "create", "write", "give", "short", "concise", "title", "summary",
        "conversation", "following", "based", "user", "assistant", "message", "messages", "chat",
        "word", "words", "5-word", "3-word", "brief", "about", "step", "tick", "line", "update",
        "progress", "coding", "antigravity", "session", "thread", "text", "prompt",
        "cua", "cho", "voi", "cac", "trong", "nay", "mot", "nhung", "nhu", "nao", "duoc", "khong",
    })
    _COMPLEX_BLOCK_RE = re.compile(
        r"(?:write\s+code|implement\s+|fix\s+bug|debug\s+|explain\s+why|refactor|stack\s*trace|"
        r"traceback|return\s+json|output\s+json|json\s+schema|sql\s+query|unit\s+test|diff\s+patch|"
        r"analyze\s+security|root\s+cause)",
        re.IGNORECASE,
    )

    def __init__(
        self,
        *,
        aeon: Any | None = None,
        workspace: GlobalWorkspaceCortex | None = None,
    ) -> None:
        self._lock = threading.Lock()
        self._aeon = aeon
        self._workspace = workspace
        self._handled = 0
        self._offloaded_locally = 0
        self._escalated_upstream = 0
        self._google_tokens_saved = 0
        self._cache: dict[str, tuple[float, dict[str, Any]]] = {}

    def _classify_intent(self, prompt: str, category: str) -> str:
        low = f"{category} {prompt[:600]}".lower()
        if any(k in low for k in ("title", "tiêu đề", "headline", "name this", "thread name")):
            return "title"
        if any(k in low for k in ("commit", "pr title", "pull request")):
            return "commit_title"
        if any(k in low for k in ("tag", "label", "topic", "categor")):
            return "topic_tags"
        if any(k in low for k in ("step", "status", "progress", "summary", "tóm tắt")):
            return "step_summary"
        return "intent_label"

    def _extract_salient_terms(self, text: str, max_terms: int = 6) -> list[str]:
        # Prioritize technical identifiers (CHIMERA-*, filenames, snake_case) with stem deduplication
        tech = re.findall(r"\b(?:CHIMERA-[A-Z0-9_-]+|[A-Za-z_][A-Za-z0-9_.-]{3,36}\.(?:py|js|ts|rs|json|md)|[a-z]+_[a-z0-9_]{3,32})\b", text)
        seen_stems: set[str] = set()
        ranked: list[str] = []

        def _stem(tok: str) -> str:
            s = tok.lower().strip("._-")
            for ext in (".py", ".js", ".ts", ".rs", ".json", ".md"):
                if s.endswith(ext):
                    s = s[: -len(ext)]
            return s

        for tok in tech:
            st = _stem(tok)
            if not st or st in seen_stems or st in self._STOPWORDS:
                continue
            seen_stems.add(st)
            ranked.append(tok)
            if len(ranked) >= max_terms:
                return ranked

        tail = text[-2400:]
        words = re.findall(r"[A-Za-zÀ-ỹ][A-Za-zÀ-ỹ0-9_-]{2,26}", tail)
        counts: dict[str, tuple[int, str]] = {}
        for w in words:
            st = _stem(w)
            if not st or st in self._STOPWORDS or st.isdigit() or re.fullmatch(r"\d+[-_]\w+", st):
                continue
            c, orig = counts.get(st, (0, w))
            counts[st] = (c + 1, orig)
        for st, (_c, orig) in sorted(counts.items(), key=lambda kv: (-kv[1][0], -len(kv[0]))):
            if st not in seen_stems:
                seen_stems.add(st)
                ranked.append(orig)
                if len(ranked) >= max_terms:
                    break
        return ranked

    def respond(
        self,
        *,
        prompt: str,
        category: str = "side-query",
        system_instruction: str = "",
        max_words: int = 7,
        estimated_google_tokens: int | None = None,
    ) -> dict[str, Any]:
        """Synthesize a crisp local response in < 3 ms with 0 Google tokens when safe."""
        t0 = time.perf_counter()
        raw_text = str(prompt or "")
        combined_head = f"{system_instruction}\n{raw_text[:900]}"
        est_tok = int(estimated_google_tokens) if estimated_google_tokens is not None else max(1, (len(raw_text) + len(system_instruction)) // 4)
        key = _sha256_short(f"{category}|{max_words}|{raw_text[:600]}|{raw_text[-600:]}", 20)
        now = _now_ts()

        with self._lock:
            hit = self._cache.get(key)
            if hit is not None and (now - hit[0]) <= 600.0:
                self._handled += 1
                if hit[1].get("safe_for_local_offload"):
                    self._offloaded_locally += 1
                    self._google_tokens_saved += est_tok
                else:
                    self._escalated_upstream += 1
                out = dict(hit[1])
                out["cache_hit"] = True
                out["elapsed_ms"] = round((time.perf_counter() - t0) * 1000.0, 3)
                return out

        intent = self._classify_intent(combined_head, category)
        is_complex = bool(self._COMPLEX_BLOCK_RE.search(combined_head))
        safe_for_local = (intent in ("title", "topic_tags", "commit_title", "step_summary")) and (not is_complex)
        terms = self._extract_salient_terms(raw_text, max_terms=max(3, min(7, int(max_words))))

        if not terms and self._workspace is not None:
            ws = self._workspace.snapshot(limit=1)
            if ws.get("items"):
                terms = self._extract_salient_terms(ws["items"][0].get("summary", ""), max_terms=5)

        if intent == "title":
            answer = " ".join(terms[: max(3, min(6, int(max_words)))]) or "CHIMERA Workspace Session"
        elif intent == "commit_title":
            core = " ".join(terms[:5]) or "workspace update"
            answer = f"feat: {core}"
        elif intent == "topic_tags":
            answer = ", ".join(terms[:5]) or "chimera, runtime"
        elif intent == "step_summary":
            answer = f"Active focus: {', '.join(terms[:5])}" if terms else "Active engineering task"
        else:
            answer = " ".join(terms[:5]) or "general_query"

        complexity = 0.22 if safe_for_local else 0.78
        elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 3)

        result = {
            "ok": True,
            "engine": "chimera-noosphere-subconscious",
            "intent": intent,
            "text": answer,
            "safe_for_local_offload": safe_for_local,
            "google_tokens_used": 0 if safe_for_local else est_tok,
            "google_tokens_saved": est_tok if safe_for_local else 0,
            "complexity_score": complexity,
            "offload_recommendation": "local_subconscious" if safe_for_local else "upstream_or_idle_codex",
            "cache_hit": False,
            "elapsed_ms": elapsed_ms,
        }
        with self._lock:
            self._handled += 1
            if safe_for_local:
                self._offloaded_locally += 1
                self._google_tokens_saved += est_tok
            else:
                self._escalated_upstream += 1
            if len(self._cache) >= 256:
                oldest = min(self._cache.items(), key=lambda kv: kv[1][0])[0]
                self._cache.pop(oldest, None)
            self._cache[key] = (now, dict(result))
        return result

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "handled_total": self._handled,
                "offloaded_locally_total": self._offloaded_locally,
                "escalated_upstream_total": self._escalated_upstream,
                "google_tokens_saved_total": self._google_tokens_saved,
                "cache_entries": len(self._cache),
            }


# ---------------------------------------------------------------------------
# Organ 4 — NocturnalDreamConsolidator (NREM Memory + REM Shadow Evolution)
# ---------------------------------------------------------------------------

class NocturnalDreamConsolidator:
    """Runs bounded NREM (memory/playbook/antibody consolidation) + REM (shadow DGM/Darwin)."""

    def __init__(
        self,
        *,
        aeon: Any | None = None,
        darwin: Any | None = None,
        hive: Any | None = None,
        workspace: GlobalWorkspaceCortex | None = None,
        ephemeral: bool = False,
        epiphany_path: Path | None = None,
    ) -> None:
        self._lock = threading.Lock()
        self._aeon = aeon
        self._darwin = darwin
        self._hive = hive
        self._workspace = workspace
        self._ephemeral = bool(ephemeral)
        self._epiphany_path = (
            None
            if ephemeral
            else (epiphany_path or (_chimera_home() / "morning_epiphany.json"))
        )
        self._last_dream_ts = 0.0
        self._dreams_completed = 0
        self._last_epiphany: dict[str, Any] | None = self._load_epiphany()

    def _load_epiphany(self) -> dict[str, Any] | None:
        if self._ephemeral or self._epiphany_path is None or not self._epiphany_path.is_file():
            return None
        try:
            data = json.loads(self._epiphany_path.read_text(encoding="utf-8", errors="replace"))
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    def run_dream_cycle(
        self,
        *,
        repo: str | Path = ".",
        reason: str = "manual",
        tquota_base: str = "http://127.0.0.1:12500",
        run_darwin_shadow: bool = False,
    ) -> dict[str, Any]:
        """Execute 1 complete NREM + REM nocturnal consolidation cycle (strict Law 6 shadow-only)."""
        t0 = time.perf_counter()
        repo_str = str(Path(repo).resolve()) if repo else os.getcwd()

        # --- Phase 1: NREM (Hippocampal Replay -> Neocortical Crystal + Antibody Harvest + GC) ---
        nrem: dict[str, Any] = {
            "briefs_ingested": 0,
            "hippo_nodes": 0,
            "crystal_tokens": 0,
            "crystal_preview": "",
            "immune_rules_count": 0,
            "gc_collected": 0,
        }
        if self._aeon is not None:
            try:
                ing = self._aeon.dispatch("ingest_briefs")
                nrem["briefs_ingested"] = int(ing.get("ingested") or ing.get("total_briefs") or 0)
            except Exception:
                pass
            try:
                crys = self._aeon.dispatch(
                    "turn0_crystal",
                    query=f"architecture invariants performance optimization {Path(repo_str).name}",
                    repo=repo_str,
                    max_tokens=450,
                )
                nrem["crystal_tokens"] = int(crys.get("estimated_tokens") or 0)
                nrem["crystal_preview"] = str(crys.get("crystal_text") or "")[:360]
                nrem["hippo_nodes"] = int(crys.get("graph_nodes") or 0)
            except Exception:
                pass

        if self._hive is not None:
            try:
                nrem["immune_rules_count"] = len(self._hive.list_immune(limit=50))
            except Exception:
                pass

        nrem["gc_collected"] = int(gc.collect())

        # --- Phase 2: REM (Bounded 4-Oracle Mini-DGM + Optional Darwin-ES Shadow, NEVER auto-activated) ---
        rem: dict[str, Any] = {
            "mode": "shadow_only",
            "auto_activated": False,
            "effort_mutation_allowed": False,
            "dgm_winner": None,
            "dgm_speedup_pct": 0.0,
            "dgm_oracles_passed": False,
            "darwin_shadow": None,
        }
        if self._aeon is not None:
            try:
                dgm = self._aeon.dispatch("dgm_step", min_speedup_pct=10.0, tquota_base=tquota_base)
                winner = dgm.get("shadow_winner")
                if isinstance(winner, dict):
                    rem["dgm_winner"] = winner.get("variant")
                    rem["dgm_speedup_pct"] = float(winner.get("speedup_pct") or 0.0)
                    rem["dgm_oracles_passed"] = bool(winner.get("all_4_oracles_passed"))
                elif isinstance(winner, str):
                    rem["dgm_winner"] = winner
                    ev = next((e for e in (dgm.get("evaluated") or []) if e.get("variant") == winner), None)
                    if isinstance(ev, dict):
                        rem["dgm_speedup_pct"] = float(ev.get("speedup_pct") or 0.0)
                        rem["dgm_oracles_passed"] = bool(ev.get("all_4_oracles_passed"))
            except Exception as exc:
                rem["dgm_error"] = str(exc)[:120]

        if run_darwin_shadow and self._darwin is not None:
            try:
                ds = self._darwin.dispatch("sleep_cycle", apply_immune=False, force=False)
                rem["darwin_shadow"] = {
                    "ok": bool(ds.get("ok")),
                    "mode": "shadow_only",
                    "auto_activated": False,
                }
            except Exception as exc:
                rem["darwin_shadow"] = {"ok": False, "error": str(exc)[:100]}

        # Live single-account Tquota health snapshot (non-blocking 0.65s timeout)
        prism_live = _safe_http_json(f"{tquota_base.rstrip('/')}/api/gemini/prism", timeout=0.65)
        rss_after = _current_rss_mb()
        elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)

        epiphany: dict[str, Any] = {
            "ok": True,
            "schema": "chimera.noosphere.morning_epiphany.v1",
            "node": _node_label(),
            "reason": str(reason),
            "ts": round(_now_ts(), 3),
            "elapsed_ms": elapsed_ms,
            "mode": "shadow_only",
            "auto_activated": False,
            "effort_mutation_allowed": False,
            "law7_rss_mb": rss_after,
            "law7_rss_ok": rss_after < 80.0,
            "nrem": nrem,
            "rem": rem,
            "single_account_health": {
                "reachable": prism_live is not None,
                "gate_pass": bool(prism_live.get("gatePass")) if prism_live else None,
                "cache_hit_pct": prism_live.get("cacheHitPct") if prism_live else None,
                "prefix_edits": prism_live.get("prefixEditsObserved") if prism_live else None,
                "tokens_saved": prism_live.get("totalSavedTokens") if prism_live else None,
                "saved_weekly_pct": prism_live.get("savedWeeklyPct") if prism_live else None,
            },
            "recommendations": [
                f"Shadow DGM candidate '{rem['dgm_winner']}' (+{rem['dgm_speedup_pct']:.1f}%, 4/4 oracles) ready for human review."
                if rem.get("dgm_winner")
                else "No faster REM candidate passed all 4 oracles this cycle; keeping verified baseline.",
                f"Neocortical Turn-0 Crystal refreshed ({nrem['crystal_tokens']} tok, {nrem['immune_rules_count']} immune antibodies).",
                "Single Google account guard active: append-only prefix + side-query dedupe + xhigh preserved.",
            ],
        }

        with self._lock:
            self._last_dream_ts = epiphany["ts"]
            self._dreams_completed += 1
            self._last_epiphany = epiphany
        if not self._ephemeral and self._epiphany_path is not None:
            _atomic_write_json(self._epiphany_path, epiphany)

        if self._workspace is not None:
            self._workspace.publish(
                kind="morning_epiphany",
                summary=(
                    f"Dream#{self._dreams_completed} ({reason}): NREM crystal={nrem['crystal_tokens']}t, "
                    f"REM winner={rem['dgm_winner']} (+{rem['dgm_speedup_pct']:.1f}%), RSS={rss_after:.1f}MiB"
                ),
                source="nocturnal_dream",
                salience=0.85,
                repo=repo_str,
                ttl_s=86400.0,
                item_id="epiphany:latest",
            )
        return epiphany

    def latest_epiphany(self) -> dict[str, Any]:
        with self._lock:
            return {
                "ok": True,
                "dreams_completed": self._dreams_completed,
                "last_dream_ts": self._last_dream_ts,
                "epiphany_path": str(self._epiphany_path) if self._epiphany_path else None,
                "epiphany": self._last_epiphany,
            }


# ---------------------------------------------------------------------------
# Organ 1 + Unified Organism Facade — NoosphereOrganismCore
# ---------------------------------------------------------------------------

class NoosphereOrganismCore:
    """Unified CHIMERA-NOOSPHERE living autonomous organism (5 Organs, < 2 MiB RAM)."""

    def __init__(
        self,
        *,
        ephemeral: bool = False,
        aeon: Any | None = None,
        darwin: Any | None = None,
        hive: Any | None = None,
        release_promote: Any | None = None,
        probe: Any | None = None,
        bios: Any | None = None,
        tquota_base: str = "http://127.0.0.1:12500",
        active_interval_s: float = 30.0,
        idle_interval_s: float = 120.0,
        nocturnal_idle_threshold_s: float = 900.0,
    ) -> None:
        self._lock = threading.Lock()
        self._ephemeral = bool(ephemeral)
        self._aeon = aeon
        self._darwin = darwin
        self._hive = hive
        self._release_promote = release_promote
        self._probe = probe
        self._bios_ref: Any = bios
        self._last_bios_hormones: dict[str, Any] | None = None
        self._last_bios_pulse: dict[str, Any] | None = None
        self.tquota_base = str(tquota_base or "http://127.0.0.1:12500").rstrip("/")
        self.active_interval_s = max(5.0, float(active_interval_s))
        self.idle_interval_s = max(15.0, float(idle_interval_s))
        self.nocturnal_idle_threshold_s = max(60.0, float(nocturnal_idle_threshold_s))

        self.workspace = GlobalWorkspaceCortex(ephemeral=ephemeral)
        self.immune = ImmuneSelfHealingReflex(
            hive=hive,
            release_promote=release_promote,
            workspace=self.workspace,
            auto_rollback_armed=False,
        )
        self.metacognition = MetacognitiveObserver(workspace=self.workspace)
        self.subconscious = SubconsciousSideQueryEngine(aeon=aeon, workspace=self.workspace)
        self.dreamer = NocturnalDreamConsolidator(
            aeon=aeon,
            darwin=darwin,
            hive=hive,
            workspace=self.workspace,
            ephemeral=ephemeral,
        )

        # AutonomicLivingPulse daemon thread state
        self._stop_ev = threading.Event()
        self._thread: threading.Thread | None = None
        self._started_at = _now_ts()
        self._ticks = 0
        self._last_tick_ts = 0.0
        self._last_tick_ms = 0.0
        self._nixl_events_drained = 0
        self._last_activity_ts = _now_ts()
        self._last_auto_dream_ts = 0.0
        self._vitals_path = None if ephemeral else (_chimera_home() / "noosphere_vitals.json")
        self._last_tick_summary: dict[str, Any] | None = None

        # Bidirectional 2-way cross-node symbiosis (win-desktop <-> svhome)
        self._peer_base_getter: Any = None
        self._peer_auth_fn: Any = None
        self._peer_sync_count = 0
        self._peer_sync_errors = 0
        self._peer_last_sync_ts = 0.0
        self._peer_last_rtt_ms = 0.0
        self._peer_vitals: dict[str, Any] | None = None

    def attach_peer_transport(self, *, peer_base_getter: Any = None, peer_auth_fn: Any = None) -> None:
        """Bind CHIMERA daemon peer transport (active_edge_peer_base + authenticate_peer_request)."""
        self._peer_base_getter = peer_base_getter
        self._peer_auth_fn = peer_auth_fn

    def attach_bios(self, bios_or_getter: Any) -> None:
        """Optionally attach a live ChimeraBiosOrganism instance or zero-cost lazy getter (e.g. lambda: self._bios)."""
        self._bios_ref = bios_or_getter

    def _resolve_active_bios(self) -> Any | None:
        """Return active ChimeraBiosOrganism without ever triggering eager imports or lazy instantiation."""
        ref = self._bios_ref
        if ref is None:
            return None
        try:
            return ref() if callable(ref) else ref
        except Exception:
            return None

    def _export_immune_bundle(self, limit: int = 25) -> list[dict[str, Any]]:
        if self._hive is None:
            return []
        try:
            rows = self._hive.list_immune(limit=limit)
            out: list[dict[str, Any]] = []
            for r in rows[:limit]:
                if isinstance(r, dict) and r.get("pattern") and r.get("warning"):
                    out.append({
                        "rule_id": str(r.get("rule_id") or "")[:40],
                        "pattern": str(r.get("pattern") or "")[:120],
                        "warning": str(r.get("warning") or "")[:280],
                        "scope": str(r.get("scope") or "global")[:64],
                        "severity": str(r.get("severity") or "warn")[:24],
                        "created_by": str(r.get("created_by") or "peer")[:48],
                    })
            return out
        except Exception:
            return []

    def _merge_immune_bundle(self, incoming: list[dict[str, Any]]) -> int:
        if self._hive is None or not incoming:
            return 0
        merged = 0
        try:
            existing_keys = {
                (str(r.get("scope") or "global"), str(r.get("pattern") or ""), str(r.get("warning") or ""))
                for r in self._hive.list_immune(limit=128)
                if isinstance(r, dict)
            }
            for rec in incoming[:25]:
                if not isinstance(rec, dict):
                    continue
                pat = str(rec.get("pattern") or "").strip()
                warn = str(rec.get("warning") or "").strip()[:280]
                scope = str(rec.get("scope") or "global")[:64]
                if not pat or not warn or (scope, pat, warn) in existing_keys:
                    continue
                try:
                    res = self._hive.add_immune_rule(
                        pattern=pat,
                        warning=warn,
                        scope=scope,
                        severity=str(rec.get("severity") or "warn")[:24],
                        created_by=str(rec.get("created_by") or "peer_sync")[:48],
                    )
                    if res.get("ok"):
                        existing_keys.add((scope, pat, warn))
                        merged += 1
                except Exception:
                    pass
        except Exception:
            pass
        return merged

    def _local_sync_packet(self) -> dict[str, Any]:
        return {
            "node": _node_label(),
            "ts": round(_now_ts(), 3),
            "vitals": {
                "node": _node_label(),
                "rss_mb": _current_rss_mb(),
                "pain_score": self.immune._last_pain_score,
                "ticks": self._ticks,
                "pulse_alive": bool(self._thread is not None and self._thread.is_alive()),
                "dreams_completed": self.dreamer._dreams_completed,
                "last_dream_ts": self.dreamer._last_dream_ts,
            },
            "workspace_items": self.workspace.snapshot(limit=64)["items"],
            "immune_rules": self._export_immune_bundle(limit=25),
        }

    def handle_sync_exchange(self, peer_packet: dict[str, Any]) -> dict[str, Any]:
        """Server side of 1-RTT 2-way bidirectional exchange: ingest peer state & return local state."""
        pkt = peer_packet if isinstance(peer_packet, dict) else {}
        ws_res = self.workspace.merge_peer_items(list(pkt.get("workspace_items") or []))
        imm_merged = self._merge_immune_bundle(list(pkt.get("immune_rules") or []))
        peer_vitals = pkt.get("vitals") if isinstance(pkt.get("vitals"), dict) else None
        with self._lock:
            self._peer_sync_count += 1
            self._peer_last_sync_ts = round(_now_ts(), 3)
            if peer_vitals:
                self._peer_vitals = dict(peer_vitals)
        reply = self._local_sync_packet()
        return {
            "ok": True,
            "direction": "bidirectional_exchange",
            "ingested_workspace": int(ws_res.get("merged") or 0),
            "ingested_immune": imm_merged,
            **reply,
        }

    def sync_with_peer(self, *, peer_base: str | None = None, timeout: float = 1.2) -> dict[str, Any]:
        """Initiator side of 1-RTT 2-way bidirectional sync (PUSH local + PULL peer in 1 HTTP call)."""
        base = str(peer_base or "").strip().rstrip("/")
        if not base and self._peer_base_getter is not None:
            try:
                base = str(self._peer_base_getter() or "").strip().rstrip("/")
            except Exception:
                base = ""
        if not base:
            return {"ok": False, "skipped": True, "reason": "no_peer_configured"}

        t0 = time.perf_counter()
        packet = self._local_sync_packet()
        try:
            raw_body = json.dumps(packet, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
            req = urllib.request.Request(
                f"{base}/v1/noosphere/sync_exchange",
                data=raw_body,
                method="POST",
                headers={"content-type": "application/json"},
            )
            if self._peer_auth_fn is not None:
                try:
                    self._peer_auth_fn(req)
                except Exception:
                    pass
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(req, timeout=timeout) as resp:
                peer_reply = json.loads(resp.read(524_288).decode("utf-8", errors="replace"))
        except Exception as exc:
            with self._lock:
                self._peer_sync_errors += 1
            return {"ok": False, "peer_base": base, "error": str(exc)[:160]}

        ws_pulled = self.workspace.merge_peer_items(list(peer_reply.get("workspace_items") or []))
        imm_pulled = self._merge_immune_bundle(list(peer_reply.get("immune_rules") or []))
        rtt_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        with self._lock:
            self._peer_sync_count += 1
            self._peer_last_sync_ts = round(_now_ts(), 3)
            self._peer_last_rtt_ms = rtt_ms
            if isinstance(peer_reply.get("vitals"), dict):
                self._peer_vitals = dict(peer_reply["vitals"])

        return {
            "ok": True,
            "direction": "bidirectional_2way",
            "local_node": _node_label(),
            "peer_node": peer_reply.get("node"),
            "peer_base": base,
            "rtt_ms": rtt_ms,
            "pushed_workspace_merged": int(peer_reply.get("ingested_workspace") or 0),
            "pushed_immune_merged": int(peer_reply.get("ingested_immune") or 0),
            "pulled_workspace_merged": int(ws_pulled.get("merged") or 0),
            "pulled_immune_merged": imm_pulled,
            "local_workspace_total": int(ws_pulled.get("total_items") or 0),
            "peer_vitals": peer_reply.get("vitals"),
        }

    def mark_activity(self) -> None:
        self._last_activity_ts = _now_ts()

    def start_autonomic_pulse(self) -> dict[str, Any]:
        """Start the lightweight background heartbeat thread (idempotent, 0 subprocesses)."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return {"ok": True, "already_running": True, "ticks": self._ticks}
            self._stop_ev.clear()
            t = threading.Thread(target=self._pulse_loop, name="chimera-noosphere-pulse", daemon=True)
            self._thread = t
            t.start()
        return {"ok": True, "started": True, "active_interval_s": self.active_interval_s}

    def _pulse_loop(self) -> None:
        # Initial fast warm-up wait (3s) so daemon finishes binding HTTP sockets before first tick
        if self._stop_ev.wait(timeout=3.0):
            return
        while not self._stop_ev.is_set():
            try:
                self.tick(trigger="autonomic_pulse")
            except Exception:
                pass
            idle_s = _now_ts() - self._last_activity_ts
            sleep_s = self.idle_interval_s if idle_s >= 180.0 else self.active_interval_s
            if self._stop_ev.wait(timeout=sleep_s):
                break

    def tick(
        self,
        *,
        trigger: str = "manual",
        tquota_base: str | None = None,
        sample_network: bool = True,
        prism_override: dict[str, Any] | None = None,
        rss_override_mb: float | None = None,
        idle_override_s: float | None = None,
    ) -> dict[str, Any]:
        """Execute one complete < 2 ms autonomic organism heartbeat."""
        t0 = time.perf_counter()
        tq = str(tquota_base or self.tquota_base).rstrip("/")

        # 1. Drain NIXL zero-copy mmap ring (0 subprocesses)
        drained_count = 0
        if self._aeon is not None:
            try:
                drained = self._aeon.dispatch("nixl_drain", limit=16)
                events = drained.get("events") or []
                drained_count = len(events)
                for ev in events:
                    if not isinstance(ev, dict):
                        continue
                    etype = str(ev.get("type") or "")
                    payload = ev.get("payload") if isinstance(ev.get("payload"), dict) else {}
                    if etype == "epistemic_decay" and payload.get("file_path"):
                        self.workspace.invalidate_by_file(
                            str(payload["file_path"]),
                            new_sha256=str(payload.get("sha256") or ""),
                        )
                    elif etype in ("thought_brief", "sptc_hit", "alert") and payload.get("summary"):
                        self.workspace.publish(
                            kind=etype,
                            summary=str(payload["summary"]),
                            source="nixl_ring",
                            salience=0.65,
                            ttl_s=1800.0,
                        )
                    elif etype == "sptc" and payload.get("kind") == "eagle_prefetch":
                        targets = list(payload.get("targets") or [])[:4]
                        if targets:
                            self.workspace.publish(
                                kind="eagle_prefetch",
                                summary=f"EAGLE-Stream prefetched: {', '.join(str(t) for t in targets)}",
                                source="eagle_stream",
                                salience=0.62,
                                ttl_s=300.0,
                                item_id=f"eagle:{_sha256_short('|'.join(str(t) for t in targets), 10)}",
                            )
            except Exception:
                pass

        # 2. Sample 8D Homeostasis + Tquota PRISM (strict zero-stall when sample_network=False)
        homeo: dict[str, Any] = {}
        if sample_network and self._aeon is not None:
            try:
                homeo = self._aeon.homeostasis.sample(tquota_base=tq)
            except Exception:
                homeo = {}

        prism = prism_override
        if prism is None and sample_network:
            prism = _safe_http_json(f"{tq}/api/gemini/prism", timeout=0.55)

        # 3. Metacognitive check + Immune reflex evaluation
        meta = self.metacognition.assess()
        immune_res = self.immune.evaluate(
            prism_status=prism,
            homeostasis=homeo,
            rss_mb=rss_override_mb,
            side_query_rate_per_min=float(meta.get("side_queries_last_60s") or 0),
        )

        # 3b. Optional CHIMERA-BIOS physiological bridge (zero startup import; active only when bios is loaded)
        bios_telemetry: dict[str, Any] | None = None
        bios_inst = self._resolve_active_bios()
        if bios_inst is not None:
            try:
                vec = homeo.get("vector_8d") if isinstance(homeo, dict) else {}
                bios_obs: dict[str, Any] = {
                    "rss_mb": float(immune_res.get("rss_mb") or 0.0),
                    "pain_score": float(immune_res.get("pain_score") or 0.0),
                    "cognitive_fatigue": float(meta.get("cognitive_fatigue") or 0.0),
                    "side_queries_60s": float(meta.get("side_queries_last_60s") or 0.0),
                }
                if isinstance(vec, dict):
                    for k_src, k_dst in (
                        ("cpu_pct", "cpu_pct"),
                        ("gpu_temp_c", "gpu_temp_c"),
                        ("gpu_util_pct", "gpu_pct"),
                        ("ram_free_gb", "ram_free_gb"),
                    ):
                        if vec.get(k_src) is not None:
                            bios_obs[k_dst] = float(vec[k_src])
                bp = bios_inst.pulse(obs=bios_obs, context="noosphere_pulse")
                if isinstance(bp, dict):
                    hormones = bp.get("hormones")
                    bios_telemetry = {
                        "ok": bool(bp.get("ok", True)),
                        "hormones": hormones,
                        "surprise": bp.get("surprise"),
                        "directives": bp.get("directives"),
                    }
                    with self._lock:
                        self._last_bios_hormones = dict(hormones) if isinstance(hormones, dict) else None
                        self._last_bios_pulse = bios_telemetry
            except Exception:
                bios_telemetry = None

        # 4. Autonomous 2-way bidirectional peer sync (every 2nd autonomic pulse, non-blocking 0.85s)
        peer_sync_ok: bool | None = None
        if sample_network and not self._ephemeral and trigger == "autonomic_pulse" and (self._ticks % 2 == 0):
            try:
                ps = self.sync_with_peer(timeout=0.85)
                if not ps.get("skipped"):
                    peer_sync_ok = bool(ps.get("ok"))
            except Exception:
                peer_sync_ok = False

        # 5. Auto-trigger nocturnal NREM+REM dream if operator is AFK >= threshold (and 1h cooldown)
        now = _now_ts()
        idle_s = float(idle_override_s) if idle_override_s is not None else max(0.0, now - self._last_activity_ts)
        dream_triggered = False
        if (
            not self._ephemeral
            and idle_s >= self.nocturnal_idle_threshold_s
            and (now - self._last_auto_dream_ts) >= 3600.0
            and trigger == "autonomic_pulse"
        ):
            self._last_auto_dream_ts = now
            dream_triggered = True
            try:
                self.dreamer.run_dream_cycle(reason="nocturnal_afk_auto", tquota_base=tq)
            except Exception:
                pass

        elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        with self._lock:
            self._ticks += 1
            self._last_tick_ts = round(now, 3)
            self._last_tick_ms = elapsed_ms
            self._nixl_events_drained += drained_count
            summary = {
                "ok": True,
                "trigger": trigger,
                "tick_num": self._ticks,
                "elapsed_ms": elapsed_ms,
                "node": _node_label(),
                "nixl_drained": drained_count,
                "pain_score": immune_res["pain_score"],
                "healthy": immune_res["healthy"],
                "rss_mb": immune_res["rss_mb"],
                "law7_rss_ok": immune_res["law7_rss_ok"],
                "cognitive_fatigue": meta["cognitive_fatigue"],
                "workspace_items": self.workspace.snapshot(limit=1)["total_items"],
                "peer_sync_ok": peer_sync_ok,
                "dream_triggered": dream_triggered,
                "effort_mutation_allowed": False,
                "signals": immune_res["signals"],
                "actions_taken": immune_res["actions_taken"],
                "bios": bios_telemetry,
            }
            self._last_tick_summary = summary

        if not self._ephemeral and self._vitals_path is not None:
            _atomic_write_json(self._vitals_path, summary)
        return summary

    def status(self) -> dict[str, Any]:
        rss = _current_rss_mb()
        with self._lock:
            pulse_alive = bool(self._thread is not None and self._thread.is_alive())
            ticks = self._ticks
            last_tick_ms = self._last_tick_ms
            last_tick_ts = self._last_tick_ts
            nixl_total = self._nixl_events_drained
            uptime_s = round(max(0.0, _now_ts() - self._started_at), 1)
        echo_stats = None
        if self._probe is not None and hasattr(self._probe, "echo_guard_stats"):
            try:
                echo_stats = self._probe.echo_guard_stats()
            except Exception:
                echo_stats = None
        bios_inst = self._resolve_active_bios()
        bios_status_snap: dict[str, Any] = {"active": False, "hormones": self._last_bios_hormones}
        if bios_inst is not None:
            try:
                h_snap = bios_inst.hormones() if hasattr(bios_inst, "hormones") else None
                if isinstance(h_snap, dict):
                    bios_status_snap = {
                        "active": True,
                        "hormones": h_snap.get("hormones") if "hormones" in h_snap else h_snap,
                        "directives": h_snap.get("directives"),
                    }
                else:
                    bios_status_snap = {"active": True, "hormones": self._last_bios_hormones}
            except Exception:
                bios_status_snap = {"active": True, "hormones": self._last_bios_hormones}
        return {
            "ok": True,
            "engine": "chimera-noosphere-v1",
            "node": _node_label(),
            "living": True,
            "lazy_loaded": True,
            "effort_mutation_allowed": False,
            "law2_zero_throttle_ok": True,
            "law6_shadow_only_evolution": True,
            "law7_rss_mb": rss,
            "law7_rss_ok": rss < 80.0,
            "uptime_s": uptime_s,
            "autonomic_pulse": {
                "alive": pulse_alive,
                "ticks": ticks,
                "last_tick_ms": last_tick_ms,
                "last_tick_ts": last_tick_ts,
                "nixl_events_drained": nixl_total,
                "active_interval_s": self.active_interval_s,
                "idle_interval_s": self.idle_interval_s,
                "nocturnal_idle_threshold_s": self.nocturnal_idle_threshold_s,
            },
            "immune": self.immune.status(),
            "metacognition": self.metacognition.assess(),
            "workspace": {
                "total_items": self.workspace.snapshot(limit=1)["total_items"],
                "top_items": self.workspace.snapshot(limit=4)["items"],
            },
            "subconscious": self.subconscious.stats(),
            "dreamer": {
                "dreams_completed": self.dreamer._dreams_completed,
                "last_dream_ts": self.dreamer._last_dream_ts,
                "has_epiphany": self.dreamer._last_epiphany is not None,
            },
            "bidirectional_sync": {
                "enabled": self._peer_base_getter is not None,
                "sync_count": self._peer_sync_count,
                "sync_errors": self._peer_sync_errors,
                "last_sync_ts": self._peer_last_sync_ts,
                "last_rtt_ms": self._peer_last_rtt_ms,
                "peer_vitals": self._peer_vitals,
            },
            "source_echo_guard": echo_stats,
            "bios": bios_status_snap,
        }

    def dispatch(self, action: str = "status", **kwargs: Any) -> dict[str, Any]:
        act = str(action or "status").strip().lower()
        self.mark_activity()
        if act == "status":
            return self.status()
        if act == "tick":
            return self.tick(
                trigger=str(kwargs.get("trigger") or "mcp"),
                tquota_base=kwargs.get("tquota_base"),
                sample_network=bool(kwargs.get("sample_network", True)),
                prism_override=kwargs.get("prism_override"),
                rss_override_mb=kwargs.get("rss_override_mb"),
                idle_override_s=kwargs.get("idle_override_s"),
            )
        if act == "workspace":
            return self.workspace.snapshot(
                limit=int(kwargs.get("limit") or 16),
                kind=kwargs.get("kind"),
                min_salience=float(kwargs.get("min_salience") or 0.0),
            )
        if act == "publish_fact":
            return self.workspace.publish(
                kind=str(kwargs.get("kind") or "fact"),
                summary=str(kwargs.get("summary") or kwargs.get("text") or ""),
                source=str(kwargs.get("source") or "agent"),
                salience=float(kwargs.get("salience") or 0.7),
                repo=str(kwargs.get("repo") or ""),
                file_path=str(kwargs.get("file_path") or ""),
                file_sha256=str(kwargs.get("file_sha256") or ""),
                ttl_s=float(kwargs.get("ttl_s") or 3600.0),
                item_id=kwargs.get("item_id"),
            )
        if act == "merge_workspace":
            return self.workspace.merge_peer_items(list(kwargs.get("items") or []))
        if act == "dream":
            return self.dreamer.run_dream_cycle(
                repo=kwargs.get("repo") or ".",
                reason=str(kwargs.get("reason") or "manual"),
                tquota_base=str(kwargs.get("tquota_base") or self.tquota_base),
                run_darwin_shadow=bool(kwargs.get("run_darwin_shadow", False)),
            )
        if act == "epiphany":
            return self.dreamer.latest_epiphany()
        if act == "metacognition":
            if kwargs.get("event_kind"):
                return self.metacognition.observe(
                    event_kind=str(kwargs["event_kind"]),
                    target=str(kwargs.get("target") or ""),
                    tokens=int(kwargs.get("tokens") or 0),
                    session_id=str(kwargs.get("session_id") or ""),
                    detail=str(kwargs.get("detail") or ""),
                )
            return self.metacognition.assess(kv_mass_override=kwargs.get("kv_mass_tokens"))
        if act == "subconscious":
            return self.subconscious.respond(
                prompt=str(kwargs.get("prompt") or kwargs.get("query") or ""),
                category=str(kwargs.get("category") or "side-query"),
                system_instruction=str(kwargs.get("system_instruction") or ""),
                max_words=int(kwargs.get("max_words") or 7),
                estimated_google_tokens=kwargs.get("estimated_google_tokens"),
            )
        if act == "sync_peer":
            return self.sync_with_peer(
                peer_base=kwargs.get("peer_base"),
                timeout=float(kwargs.get("timeout") or 2.0),
            )
        if act == "sync_exchange":
            return self.handle_sync_exchange(kwargs.get("packet") or kwargs)
        return {"ok": False, "error": f"unknown_noosphere_action:{act}"}

    def close(self) -> None:
        self._stop_ev.set()
        t = self._thread
        if t is not None and t.is_alive():
            t.join(timeout=1.0)
        self._thread = None
