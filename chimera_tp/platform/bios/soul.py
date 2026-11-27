"""CHIMERA-SOUL (Idea #10) — Autobiographical Continuity & Model-Agnostic Identity.

Maintains an immutable SHA-256 hash-chained evolutionary autobiography (`prev_hash -> entry_hash`)
in SQLite WAL paired with compact 10K-bit (10,240-bit) pure-Python binary VSA/trigram
semantic recall. Exports a strictly <= 500-token, model-agnostic, SHA-256-verified
Living Soul Capsule so any LLM (Gemini, Codex, Claude, local models) attached to CHIMERA
inherits the exact same continuous identity, laws, and hard-won evolutionary scars.

100% Python stdlib, Zero-NumPy, lazy-loaded, < 1 MiB RAM.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import struct
import threading
import time
from pathlib import Path
from typing import Any

GENESIS_PREV_HASH = "0" * 64
VSA_DIM_BITS = 10240  # 10K-bit hypervector = 1,280 bytes
VSA_BITS_PER_FEATURE = 12
DEFAULT_MAX_TOKENS = 500
# Fixed 32-char (11-token) canonical model label for model-name-invariant compaction
# decisions so core_sha256 never diverges across short vs long target_model names.
CANONICAL_MODEL_LABEL = "canonical-model-name-v1-0-000000"

CHIMERA_ACTIVE_LAWS: tuple[str, ...] = (
    "L1 Eliminate waste before offload",
    "L2 Zero-Choke kernel (no hard affinity choke, keep Turbo 100%)",
    "L3 Protect svhome 15W (RAM>=2.5GiB, load<=1.8, temp<70C)",
    "L4 Content-addressed SHA-256 work units & singleflight",
    "L5 Dual-budget CPU vs latency empirical placement",
    "L6 Lab->Shadow->Active human gate (auto_activated=False)",
    "L7 Daemon RSS <80MiB via stdlib zero-NumPy lazy-loading",
)

GENESIS_SCARS: tuple[dict[str, Any], ...] = (
    {
        "title": "Law 2: 0xF00 CPU Choke & Scheduler Starvation",
        "event_date": "2026-11-26",
        "root_cause": (
            "Hard Ring-3 CPU affinity mask (0xF00), indiscriminate background throttling, "
            "and IPC process suspension starved Windows interactive scheduling and AutoCAD P99 frames."
        ),
        "lesson_law": (
            "Law 2 (Zero-Choke): Never pin hard 0xF00 affinity, never cap Turbo <100%, "
            "and never suspend IPC/shell processes; use cooperative OS scheduling (MMCSS, Zero-Copy)."
        ),
        "hardware_context": "win-desktop: i5-11400 6C/12T 4.4GHz, 32 GiB RAM, GTX 1650",
        "tags": ["law2", "0xf00", "cpu", "affinity", "autocad", "win-desktop", "zero-choke"],
        "severity": "critical",
    },
    {
        "title": "Law 3: svhome 15W Weak-Node Thermal & RAM Guard",
        "event_date": "2026-11-26",
        "root_cause": (
            "Offloading heavy workstation tasks or extra browser workers onto the 24/7 15W "
            "home server threatened Radar/Tqouta P95 latency and thermal headroom."
        ),
        "lesson_law": (
            "Law 3 (Peer Guard): Protect svhome (2C/4T 15W, 10 GiB RAM) stricter than win-desktop; "
            "enforce free RAM>=2.5 GiB, load1<=1.8, temp<70C, disk>=15 GB."
        ),
        "hardware_context": "svhome: i5-4300U 2C/4T 15W, 10 GiB RAM, 109 GB SSD",
        "tags": ["law3", "svhome", "15w", "thermal", "peer_guard", "homeostasis", "offload"],
        "severity": "critical",
    },
    {
        "title": "Law 7: 80 MiB Resident Daemon RSS Ceiling",
        "event_date": "2026-11-26",
        "root_cause": (
            "Eagerly importing experimental modules and heavy numerical packages drove resident "
            "daemon RSS to 79.17 MiB, dangerously close to the 80 MiB ceiling."
        ),
        "lesson_law": (
            "Law 7 (Zero-Weight Ceiling): Keep resident daemon RSS <80 MiB (target <60 MiB) via "
            "100% stdlib Zero-NumPy core and strict lazy-loading of optional organs."
        ),
        "hardware_context": "win-desktop + svhome resident anchor daemon (:9780)",
        "tags": ["law7", "rss", "80mib", "memory", "lazy-load", "zero-numpy", "daemon"],
        "severity": "critical",
    },
    {
        "title": ":12500 Immortal Socket & Steer Preemption Lesson",
        "event_date": "2026-11-26",
        "root_cause": (
            "Unmanaged local relay sockets and detached upstream streams triggered 503 races "
            "and lost operator steers during long-running agent sessions."
        ),
        "lesson_law": (
            "Preserve :12500 immortal socket continuity with deterministic reconnect, "
            "SHA-256 receipts (Law 4), and <1 ms steer preemption without dropping context."
        ),
        "hardware_context": "win-desktop <-> svhome PHANTOM tunnel + :12500 relay",
        "tags": ["12500", "socket", "immortal", "relay", "steer", "503", "continuity"],
        "severity": "high",
    },
)

GENESIS_PREFERENCES: tuple[tuple[str, str, str, str], ...] = (
    (
        "architecture",
        "core_runtime",
        "100% Python stdlib, Zero-NumPy, lazy-loaded organs",
        "Law 7 <80 MiB daemon RSS ceiling",
    ),
    (
        "safety",
        "evolution_gate",
        "Shadow A/B proof + human approval (auto_activated=False)",
        "Law 6 do-no-harm rollback discipline",
    ),
    (
        "interface",
        "sovereign_skin",
        "Zero-WebGL 2D tactical UI under 50 KB, single anchor :9780",
        "Organ 5 Sovereign Skin doctrine",
    ),
)


def _default_ops_dir() -> Path:
    return Path(os.environ.get("CHIMERA_HOME") or (Path.home() / ".chimera"))


def _canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_hex(data: bytes | str) -> str:
    raw = data.encode("utf-8") if isinstance(data, str) else data
    return hashlib.sha256(raw).hexdigest()


def _normalize_tags(tags: list[str] | tuple[str, ...] | None) -> list[str]:
    if not tags:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for t in tags:
        tok = re.sub(r"[^a-z0-9_:+-]+", "_", str(t).strip().lower()).strip("_")
        if tok and tok not in seen:
            seen.add(tok)
            out.append(tok)
    return sorted(out)


def _extract_features(text: str) -> list[str]:
    """Extract lowercase word tokens + character 3-grams for 10K-bit VSA projection."""
    clean = re.sub(r"[^a-z0-9_:]+", " ", str(text or "").lower()).strip()
    if not clean:
        return []
    words = [w for w in clean.split() if len(w) >= 2]
    feats: list[str] = []
    seen: set[str] = set()
    for w in words[:96]:
        if w not in seen:
            seen.add(w)
            feats.append(f"w:{w}")
        if len(w) >= 3:
            padded = f"^{w}$"
            for i in range(len(padded) - 2):
                tri = f"t:{padded[i:i + 3]}"
                if tri not in seen:
                    seen.add(tri)
                    feats.append(tri)
                if len(feats) >= 240:
                    return feats
    return feats


def vsa_encode_10k(text: str) -> int:
    """Encode text into a compact 10,240-bit binary VSA hypervector (pure Python int)."""
    feats = _extract_features(text)
    if not feats:
        return 0
    hv = 0
    for feat in feats:
        digest = hashlib.blake2s(feat.encode("utf-8"), digest_size=32).digest()
        for j in range(VSA_BITS_PER_FEATURE):
            # 16 two-byte slices available in 32-byte blake2s digest
            val = struct.unpack_from("<H", digest, j * 2)[0]
            bit_pos = val % VSA_DIM_BITS
            hv |= 1 << bit_pos
    return hv


def vsa_similarity_10k(a: int, b: int) -> float:
    """Compute Jaccard/Dice overlap similarity between two 10K-bit binary hypervectors."""
    if a == 0 or b == 0:
        return 0.0
    inter = (a & b).bit_count()
    if inter == 0:
        return 0.0
    union = (a | b).bit_count()
    return float(inter) / float(max(1, union))


def estimate_tokens(payload: Any) -> int:
    """Conservative cross-LLM token estimator (BPE upper bound for Gemini/Codex/Claude/local)."""
    text = payload if isinstance(payload, str) else _canonical_json(payload)
    if not text:
        return 0
    char_est = math.ceil(len(text) / 3.8)
    word_est = len(re.findall(r"[A-Za-z0-9_]+|[^\sA-Za-z0-9_]", text))
    # Weighted blend conservative enough for JSON punctuation + BPE subwords
    return int(max(char_est, math.ceil(word_est * 0.85)))


def _compute_scar_hash(
    *,
    seq: int,
    prev_hash: str,
    title: str,
    event_date: str,
    root_cause: str,
    lesson_law: str,
    hardware_context: str,
    tags: list[str],
    severity: str,
) -> str:
    canonical = _canonical_json(
        {
            "seq": int(seq),
            "prev_hash": str(prev_hash),
            "title": str(title),
            "event_date": str(event_date),
            "root_cause": str(root_cause),
            "lesson_law": str(lesson_law),
            "hardware_context": str(hardware_context),
            "tags": list(tags),
            "severity": str(severity),
        }
    )
    return _sha256_hex(canonical)


class AutobiographicalSoul:
    """SHA-256 hash-chained evolutionary autobiography + <= 500-token model-agnostic Soul Capsule."""

    GENESIS_PREV_HASH = GENESIS_PREV_HASH
    VSA_DIM_BITS = VSA_DIM_BITS
    DEFAULT_MAX_TOKENS = DEFAULT_MAX_TOKENS
    CANONICAL_MODEL_LABEL = CANONICAL_MODEL_LABEL

    def __init__(
        self,
        ops_dir: str | Path | None = None,
        *,
        ephemeral: bool = False,
        seed_genesis: bool = True,
    ) -> None:
        self._lock = threading.RLock()
        self._ephemeral = bool(ephemeral)
        self._ops_dir = Path(ops_dir) if ops_dir is not None else _default_ops_dir()
        self._conn: sqlite3.Connection | None = None
        # In-RAM 10K-bit VSA cache: seq -> int bitmask (~1.28 KB per scar)
        self._vsa_cache: dict[int, int] = {}
        self._init_storage()
        if seed_genesis:
            self._seed_genesis_if_empty()

    def _init_storage(self) -> None:
        if self._ephemeral:
            self._conn = sqlite3.connect(":memory:", check_same_thread=False)
        else:
            self._ops_dir.mkdir(parents=True, exist_ok=True)
            db_path = self._ops_dir / "bios_soul.sqlite3"
            self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL;")
            self._conn.execute("PRAGMA synchronous=NORMAL;")
            self._conn.execute("PRAGMA busy_timeout=3000;")

        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS scars (
                seq INTEGER PRIMARY KEY,
                scar_id TEXT UNIQUE NOT NULL,
                title TEXT NOT NULL,
                event_date TEXT NOT NULL,
                root_cause TEXT NOT NULL,
                lesson_law TEXT NOT NULL,
                hardware_context TEXT NOT NULL,
                tags_json TEXT NOT NULL,
                severity TEXT NOT NULL,
                prev_hash TEXT NOT NULL,
                entry_hash TEXT NOT NULL,
                created_at REAL NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS preferences (
                domain TEXT NOT NULL,
                pref_key TEXT NOT NULL,
                pref_value TEXT NOT NULL,
                evidence TEXT NOT NULL,
                pref_sha256 TEXT NOT NULL,
                updated_at REAL NOT NULL,
                PRIMARY KEY (domain, pref_key)
            )
            """
        )
        self._conn.commit()
        self._rebuild_vsa_cache()

    def _rebuild_vsa_cache(self) -> None:
        assert self._conn is not None
        self._vsa_cache.clear()
        rows = self._conn.execute(
            "SELECT seq, title, root_cause, lesson_law, hardware_context, tags_json FROM scars"
        ).fetchall()
        for seq, title, root_cause, lesson_law, hw, tags_json in rows:
            blob = f"{title} {root_cause} {lesson_law} {hw} {tags_json}"
            self._vsa_cache[int(seq)] = vsa_encode_10k(blob)

    def _seed_genesis_if_empty(self) -> None:
        with self._lock:
            assert self._conn is not None
            scar_count = int(self._conn.execute("SELECT COUNT(*) FROM scars").fetchone()[0])
            pref_count = int(self._conn.execute("SELECT COUNT(*) FROM preferences").fetchone()[0])
        if scar_count == 0:
            for g in GENESIS_SCARS:
                self.record_scar(
                    title=g["title"],
                    event_date=g["event_date"],
                    root_cause=g["root_cause"],
                    lesson_law=g["lesson_law"],
                    hardware_context=g["hardware_context"],
                    tags=g["tags"],
                    severity=g["severity"],
                )
        if pref_count == 0:
            for domain, key, value, evidence in GENESIS_PREFERENCES:
                self.record_preference(domain, key, value, evidence=evidence)

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                except Exception:
                    pass
                self._conn = None
            self._vsa_cache.clear()

    def __del__(self) -> None:
        self.close()

    def record_scar(
        self,
        title: str,
        event_date: str,
        root_cause: str,
        lesson_law: str,
        hardware_context: str = "",
        tags: list[str] | tuple[str, ...] | None = None,
        severity: str = "high",
    ) -> dict[str, Any]:
        """Append an immutable SHA-256 hash-chained evolutionary scar to the Soul lineage."""
        t_s = str(title or "").strip()
        if not t_s:
            raise ValueError("Scar title must be non-empty")
        date_s = str(event_date or time.strftime("%Y-%m-%d")).strip()
        rc_s = str(root_cause or "").strip()
        ll_s = str(lesson_law or "").strip()
        hw_s = str(hardware_context or "").strip()
        norm_tags = _normalize_tags(tags)
        sev_s = str(severity or "high").strip().lower()
        if sev_s not in ("low", "medium", "high", "critical"):
            sev_s = "high"
        now = time.time()

        with self._lock:
            assert self._conn is not None
            last = self._conn.execute(
                "SELECT seq, entry_hash FROM scars ORDER BY seq DESC LIMIT 1"
            ).fetchone()
            if last is None:
                seq = 1
                prev_hash = self.GENESIS_PREV_HASH
            else:
                seq = int(last[0]) + 1
                prev_hash = str(last[1])

            entry_hash = _compute_scar_hash(
                seq=seq,
                prev_hash=prev_hash,
                title=t_s,
                event_date=date_s,
                root_cause=rc_s,
                lesson_law=ll_s,
                hardware_context=hw_s,
                tags=norm_tags,
                severity=sev_s,
            )
            scar_id = f"scar_{seq:04d}_{entry_hash[:10]}"
            tags_json = json.dumps(norm_tags)

            self._conn.execute(
                """
                INSERT INTO scars (
                    seq, scar_id, title, event_date, root_cause, lesson_law,
                    hardware_context, tags_json, severity, prev_hash, entry_hash, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    seq,
                    scar_id,
                    t_s,
                    date_s,
                    rc_s,
                    ll_s,
                    hw_s,
                    tags_json,
                    sev_s,
                    prev_hash,
                    entry_hash,
                    now,
                ),
            )
            self._conn.commit()
            self._vsa_cache[seq] = vsa_encode_10k(f"{t_s} {rc_s} {ll_s} {hw_s} {tags_json}")

        return {
            "seq": seq,
            "scar_id": scar_id,
            "title": t_s,
            "event_date": date_s,
            "root_cause": rc_s,
            "lesson_law": ll_s,
            "hardware_context": hw_s,
            "tags": norm_tags,
            "severity": sev_s,
            "prev_hash": prev_hash,
            "entry_hash": entry_hash,
            "created_at": round(now, 3),
        }

    def record_preference(
        self,
        domain: str,
        key: str,
        value: str,
        evidence: str = "",
    ) -> dict[str, Any]:
        """Record or update an enduring operator architectural preference or identity trait."""
        dom = str(domain or "general").strip().lower()
        k_s = str(key or "").strip()
        if not k_s:
            raise ValueError("Preference key must be non-empty")
        v_s = str(value or "").strip()
        ev_s = str(evidence or "").strip()
        now = time.time()
        digest = _sha256_hex(f"{dom}|{k_s}|{v_s}|{ev_s}")

        with self._lock:
            assert self._conn is not None
            self._conn.execute(
                """
                INSERT INTO preferences (domain, pref_key, pref_value, evidence, pref_sha256, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(domain, pref_key) DO UPDATE SET
                    pref_value = excluded.pref_value,
                    evidence = excluded.evidence,
                    pref_sha256 = excluded.pref_sha256,
                    updated_at = excluded.updated_at
                """,
                (dom, k_s, v_s, ev_s, digest, now),
            )
            self._conn.commit()

        return {
            "domain": dom,
            "key": k_s,
            "value": v_s,
            "evidence": ev_s,
            "pref_sha256": digest,
            "updated_at": round(now, 3),
        }

    def list_scars(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            assert self._conn is not None
            rows = self._conn.execute(
                """
                SELECT seq, scar_id, title, event_date, root_cause, lesson_law,
                       hardware_context, tags_json, severity, prev_hash, entry_hash, created_at
                FROM scars ORDER BY seq ASC LIMIT ?
                """,
                (max(1, int(limit)),),
            ).fetchall()
        return [
            {
                "seq": int(r[0]),
                "scar_id": r[1],
                "title": r[2],
                "event_date": r[3],
                "root_cause": r[4],
                "lesson_law": r[5],
                "hardware_context": r[6],
                "tags": json.loads(r[7]),
                "severity": r[8],
                "prev_hash": r[9],
                "entry_hash": r[10],
                "created_at": float(r[11]),
            }
            for r in rows
        ]

    def list_preferences(self, domain: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            assert self._conn is not None
            if domain:
                rows = self._conn.execute(
                    """
                    SELECT domain, pref_key, pref_value, evidence, pref_sha256, updated_at
                    FROM preferences WHERE domain = ? ORDER BY domain ASC, pref_key ASC
                    """,
                    (str(domain).strip().lower(),),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    """
                    SELECT domain, pref_key, pref_value, evidence, pref_sha256, updated_at
                    FROM preferences ORDER BY domain ASC, pref_key ASC
                    """
                ).fetchall()
        return [
            {
                "domain": r[0],
                "key": r[1],
                "value": r[2],
                "evidence": r[3],
                "pref_sha256": r[4],
                "updated_at": float(r[5]),
            }
            for r in rows
        ]

    def recall_scars(self, query: str = "", top_k: int = 4) -> list[dict[str, Any]]:
        """Recall the top-k most relevant scars via 10K-bit VSA + token/tag resonance."""
        scars = self.list_scars(limit=500)
        k = max(1, int(top_k))
        q = str(query or "").strip()
        if not q:
            sev_rank = {"critical": 3, "high": 2, "medium": 1, "low": 0}
            ordered = sorted(
                scars, key=lambda s: (-sev_rank.get(s["severity"], 0), -s["seq"])
            )
            return [{**s, "resonance_score": 1.0} for s in ordered[:k]]

        q_hv = vsa_encode_10k(q)
        q_tokens = set(re.findall(r"[a-z0-9_:]+", q.lower()))
        scored: list[tuple[float, dict[str, Any]]] = []
        with self._lock:
            vsa_map = dict(self._vsa_cache)

        for s in scars:
            s_hv = vsa_map.get(s["seq"], 0)
            vsa_sim = vsa_similarity_10k(q_hv, s_hv)
            haystack_tokens = set(
                re.findall(
                    r"[a-z0-9_:]+",
                    f"{s['title']} {s['lesson_law']} {s['root_cause']} {' '.join(s['tags'])}".lower(),
                )
            )
            exact_overlap = len(q_tokens & haystack_tokens) / float(max(1, len(q_tokens)))
            tag_overlap = len(q_tokens & set(s["tags"])) / float(max(1, len(q_tokens)))
            score = round(0.50 * vsa_sim + 0.30 * exact_overlap + 0.20 * tag_overlap, 4)
            scored.append((score, {**s, "resonance_score": score}))

        scored.sort(key=lambda pair: (-pair[0], -pair[1]["seq"]))
        return [item for _, item in scored[:k]]

    def verify_lineage(self) -> dict[str, Any]:
        """Verify full SHA-256 hash-chain integrity across the entire autobiography."""
        scars = self.list_scars(limit=100_000)
        if not scars:
            return {
                "valid": True,
                "scar_count": 0,
                "genesis_hash": self.GENESIS_PREV_HASH,
                "head_hash": self.GENESIS_PREV_HASH,
                "broken_seq": None,
                "errors": [],
            }

        expected_prev = self.GENESIS_PREV_HASH
        errors: list[str] = []
        broken_seq: int | None = None

        for idx, s in enumerate(scars, start=1):
            if s["seq"] != idx:
                errors.append(f"seq gap at index {idx}: found seq={s['seq']}")
                if broken_seq is None:
                    broken_seq = s["seq"]
            if s["prev_hash"] != expected_prev:
                errors.append(
                    f"seq {s['seq']} prev_hash mismatch: expected {expected_prev[:12]}, got {s['prev_hash'][:12]}"
                )
                if broken_seq is None:
                    broken_seq = s["seq"]
            recomputed = _compute_scar_hash(
                seq=s["seq"],
                prev_hash=s["prev_hash"],
                title=s["title"],
                event_date=s["event_date"],
                root_cause=s["root_cause"],
                lesson_law=s["lesson_law"],
                hardware_context=s["hardware_context"],
                tags=s["tags"],
                severity=s["severity"],
            )
            if recomputed != s["entry_hash"]:
                errors.append(
                    f"seq {s['seq']} entry_hash tampered: expected {recomputed[:12]}, stored {s['entry_hash'][:12]}"
                )
                if broken_seq is None:
                    broken_seq = s["seq"]
            expected_prev = s["entry_hash"]

        return {
            "valid": len(errors) == 0,
            "scar_count": len(scars),
            "genesis_hash": scars[0]["entry_hash"],
            "head_hash": scars[-1]["entry_hash"],
            "broken_seq": broken_seq,
            "errors": errors,
        }

    @staticmethod
    def _clip(text: str, max_chars: int) -> str:
        s = str(text or "").strip()
        if len(s) <= max_chars:
            return s
        return s[: max(4, max_chars - 1)].rstrip() + "…"

    def export_capsule(
        self,
        query: str = "",
        target_model: str = "any",
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> dict[str, Any]:
        """Export a strictly <= max_tokens, model-agnostic, SHA-256-verified Living Soul Capsule."""
        budget = max(64, int(max_tokens))
        model_tag = str(target_model or "any").strip() or "any"
        lineage = self.verify_lineage()
        lineage_hash = lineage["head_hash"]
        recalled = self.recall_scars(query=query, top_k=4)
        prefs = self.list_preferences()

        identity = {
            "name": "CHIMERA-ONE",
            "role": "Sovereign Symbiotic Infrastructure Organism",
            "topology": "win-desktop<->svhome<->colab",
            "anchor": ":9780",
            "scar_count": lineage["scar_count"],
        }

        active_laws = list(CHIMERA_ACTIVE_LAWS)
        compact_scars = [
            {
                "title": self._clip(s["title"], 52),
                "lesson": self._clip(s["lesson_law"], 92),
                "date": s["event_date"],
                "sev": s["severity"],
                "hash": s["entry_hash"][:10],
            }
            for s in recalled
        ]
        compact_prefs = [
            {
                "k": f"{p['domain']}.{p['key']}",
                "v": self._clip(p["value"], 64),
            }
            for p in prefs[:6]
        ]

        def _build_capsule(
            laws_in: list[str],
            scars_in: list[dict[str, Any]],
            prefs_in: list[dict[str, Any]],
            include_prompt_in: bool,
            prompt_clip_in: int,
            *,
            model_label: str = model_tag,
        ) -> dict[str, Any]:
            core = {
                "identity": identity,
                "active_laws": laws_in,
                "relevant_scars": scars_in,
                "preferences": prefs_in,
                "lineage_hash": lineage_hash,
                "lineage_valid": lineage["valid"],
            }
            core_sha = _sha256_hex(_canonical_json(core))
            prompt = ""
            if include_prompt_in:
                scar_notes = "; ".join(s["title"] for s in scars_in[:3])
                prompt = self._clip(
                    f"[CHIMERA-SOUL {lineage_hash[:12]}] Obey Laws 1-7; "
                    f"scars: {scar_notes}.",
                    prompt_clip_in,
                )
            cap = {
                "schema": "chimera.bios.soul.v1",
                "target_model": model_label,
                "identity": identity,
                "active_laws": laws_in,
                "relevant_scars": scars_in,
                "preferences": prefs_in,
                "lineage_hash": lineage_hash,
                "lineage_valid": lineage["valid"],
                "core_sha256": core_sha,
                "max_tokens": budget,
            }
            if prompt:
                cap["continuity_prompt"] = prompt
            return cap

        def _finalize(cap: dict[str, Any]) -> dict[str, Any]:
            body = dict(cap)
            body["capsule_sha256"] = _sha256_hex(_canonical_json(cap))
            tok = estimate_tokens(body)
            body["token_est"] = tok
            # Re-check including token_est field
            tok2 = estimate_tokens(body)
            body["token_est"] = tok2
            return body

        def _fit_tokens(
            laws_in: list[str],
            scars_in: list[dict[str, Any]],
            prefs_in: list[dict[str, Any]],
            include_prompt_in: bool,
            prompt_clip_in: int,
        ) -> tuple[dict[str, Any] | None, int]:
            """Evaluate budget against CANONICAL_MODEL_LABEL while still bounding actual model_tag."""
            canon_tok = _finalize(
                _build_capsule(
                    laws_in,
                    scars_in,
                    prefs_in,
                    include_prompt_in,
                    prompt_clip_in,
                    model_label=self.CANONICAL_MODEL_LABEL,
                )
            )["token_est"]
            if canon_tok > budget:
                return None, canon_tok
            actual_cap = _finalize(
                _build_capsule(
                    laws_in,
                    scars_in,
                    prefs_in,
                    include_prompt_in,
                    prompt_clip_in,
                    model_label=model_tag,
                )
            )
            return actual_cap, max(canon_tok, actual_cap["token_est"])

        # Progressive budget fitting guaranteeing model-invariant core_sha256 and token_est <= max_tokens
        laws_cur = list(active_laws)
        scars_cur = list(compact_scars)
        prefs_cur = list(compact_prefs)
        include_prompt = True
        prompt_clip = 180

        capsule, eff_tok = _fit_tokens(laws_cur, scars_cur, prefs_cur, include_prompt, prompt_clip)

        # Stage 1: trim preferences if over budget
        while eff_tok > budget and len(prefs_cur) > 2:
            prefs_cur.pop()
            capsule, eff_tok = _fit_tokens(laws_cur, scars_cur, prefs_cur, include_prompt, prompt_clip)

        # Stage 2: shorten scar lesson text / drop lowest-priority scars
        if eff_tok > budget:
            scars_cur = [
                {
                    "title": self._clip(s["title"], 38),
                    "lesson": self._clip(s["lesson"], 56),
                    "sev": s["sev"],
                    "hash": s["hash"],
                }
                for s in scars_cur
            ]
            capsule, eff_tok = _fit_tokens(laws_cur, scars_cur, prefs_cur, include_prompt, prompt_clip)
        while eff_tok > budget and len(scars_cur) > 1:
            scars_cur.pop()
            capsule, eff_tok = _fit_tokens(laws_cur, scars_cur, prefs_cur, include_prompt, prompt_clip)

        # Stage 3: compact law strings & prompt
        if eff_tok > budget:
            laws_cur = [self._clip(law, 28) for law in laws_cur]
            prompt_clip = 90
            capsule, eff_tok = _fit_tokens(laws_cur, scars_cur, prefs_cur, include_prompt, prompt_clip)
        while eff_tok > budget and prefs_cur:
            prefs_cur.pop()
            capsule, eff_tok = _fit_tokens(laws_cur, scars_cur, prefs_cur, include_prompt, prompt_clip)
        if eff_tok > budget:
            include_prompt = False
            capsule, eff_tok = _fit_tokens(laws_cur, scars_cur, prefs_cur, include_prompt, prompt_clip)
        while eff_tok > budget and len(laws_cur) > 1:
            laws_cur.pop()
            capsule, eff_tok = _fit_tokens(laws_cur, scars_cur, prefs_cur, include_prompt, prompt_clip)
        if eff_tok > budget:
            scars_cur = []
            laws_cur = ["L1-L7 active"]
            include_prompt = False
            prompt_clip = 0
            capsule, eff_tok = _fit_tokens(laws_cur, scars_cur, prefs_cur, include_prompt, prompt_clip)

        if capsule is None:
            capsule = _finalize(
                _build_capsule(laws_cur, scars_cur, prefs_cur, include_prompt, prompt_clip)
            )

        return capsule

    @staticmethod
    def verify_capsule(capsule: dict[str, Any]) -> bool:
        """Verify SHA-256 signature of an exported Living Soul Capsule."""
        if not isinstance(capsule, dict) or not capsule.get("capsule_sha256"):
            return False
        unsigned = {
            k: v for k, v in capsule.items() if k not in ("capsule_sha256", "token_est")
        }
        return _sha256_hex(_canonical_json(unsigned)) == capsule["capsule_sha256"]

    def status(self) -> dict[str, Any]:
        lineage = self.verify_lineage()
        capsule = self.export_capsule(max_tokens=self.DEFAULT_MAX_TOKENS)
        return {
            "organ": "CHIMERA-SOUL",
            "idea": 10,
            "scar_count": lineage["scar_count"],
            "preference_count": len(self.list_preferences()),
            "lineage_valid": lineage["valid"],
            "lineage_hash": lineage["head_hash"],
            "vsa_dim_bits": self.VSA_DIM_BITS,
            "capsule_token_est": capsule["token_est"],
            "capsule": capsule,
            "ephemeral": self._ephemeral,
        }
