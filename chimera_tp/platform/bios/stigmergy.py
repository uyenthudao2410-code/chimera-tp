"""CHIMERA-STIGMERGY & EPIGENOME — Idea #6: Invisible Pheromone Skin & Epigenetic Methylation.

Zero-touch shadow coordination layer backed by SQLite WAL (NEVER modifies actual
repository files!). Lets independent AI agents, tools, and organs communicate
indirectly through the environment itself — just like ant colonies and cellular
epigenetic methylation:

  1. Alarm Pheromones        -- Track regression/bug/lock/deadlock hotspots per file.
  2. Trail Pheromones        -- Bidirectional Co-Edit Graph predicting companion files
                                & tests to prefetch before an agent reads them.
  3. Epigenetic Methylation  -- Dynamic gene expression policies (`require_ghost_bubble`,
                                `hard_lease`, `extra_verify`, `retry_backoff_mult`) on
                                scarred files or directory prefixes.
  4. Exponential Half-Life   -- Clean evaporation & demethylation so healed loci calm
                                down naturally without permanent paranoia.
  5. Open Agent Smell-Card   -- Strictly < 40-token ultra-compact structured advisory
                                (`alarm_level`, `methylation_flags`, `trail_companions`,
                                `advisory`) for any AI agent touching a path.

Compliance with CHIMERA-ONE Doctrine (Laws 1-7):
  - 100% Python stdlib, Zero-NumPy, lazy-loaded, < 2 MiB RAM
  - Zero repository file mutation; SQLite WAL in ops_dir (or `:memory:` ephemeral)
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any


def _chimera_home() -> Path:
    return Path(os.environ.get("CHIMERA_HOME") or (Path.home() / ".chimera"))


def _norm_repo(repo: str | Path) -> str:
    s = str(repo or "default").strip().replace("\\", "/")
    while s.endswith("/") and len(s) > 1:
        s = s[:-1]
    if os.name == "nt" and len(s) >= 2 and s[1] == ":":
        s = s[0].lower() + s[1:]
    return s or "default"


def _norm_rel_path(rel_path: str | Path) -> str:
    s = str(rel_path or "").strip().replace("\\", "/")
    while s.startswith("./"):
        s = s[2:]
    s = s.lstrip("/")
    while "//" in s:
        s = s.replace("//", "/")
    return s


def _ancestor_loci(rel_path: str) -> list[str]:
    """Return exact path plus directory prefix loci (most specific first) plus '*'."""
    norm = _norm_rel_path(rel_path)
    loci: list[str] = []
    if norm:
        loci.append(norm)
        parts = norm.split("/")
        for i in range(len(parts) - 1, 0, -1):
            loci.append("/".join(parts[:i]) + "/")
            loci.append("/".join(parts[:i]))
    loci.append("*")
    # Deduplicate preserving order
    seen: set[str] = set()
    out: list[str] = []
    for x in loci:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _decay_value(val: float, dt_s: float, half_life_s: float) -> float:
    if dt_s <= 0.0:
        return float(val)
    hl = max(1.0, float(half_life_s))
    return float(val) * (0.5 ** (dt_s / hl))


def _estimate_tokens(text: str) -> int:
    """Conservative token count estimator (max of whitespace words and ceil(chars/4))."""
    if not text:
        return 0
    return max((len(text) + 3) // 4, len(text.split()))


def _is_test_path(rel_path: str) -> bool:
    low = rel_path.lower()
    base = low.rsplit("/", 1)[-1]
    return (
        low.startswith("tests/")
        or "/tests/" in low
        or base.startswith("test_")
        or "_test." in base
        or ".test." in base
        or ".spec." in base
    )


def _short_label(rel_path: str) -> str:
    return rel_path.rsplit("/", 1)[-1] if "/" in rel_path else rel_path


class StigmergicEpigenome:
    """Invisible Pheromone Skin & Epigenetic Methylation store over SQLite WAL."""

    DEFAULT_ALARM_HALF_LIFE_S = 48.0 * 3600.0
    DEFAULT_TRAIL_HALF_LIFE_S = 14.0 * 86400.0
    DEFAULT_METHYL_HALF_LIFE_S = 7.0 * 86400.0

    def __init__(self, ops_dir: str | Path | None = None, ephemeral: bool = False) -> None:
        self.ephemeral = bool(ephemeral)
        if self.ephemeral:
            self.ops_dir: Path | None = None
            self.db_path = ":memory:"
        else:
            self.ops_dir = Path(ops_dir) if ops_dir is not None else (_chimera_home() / "bios")
            self.ops_dir.mkdir(parents=True, exist_ok=True)
            self.db_path = str(self.ops_dir / "stigmergy.sqlite3")

        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            cur = self._conn.cursor()
            if not self.ephemeral:
                cur.execute("PRAGMA journal_mode=WAL;")
                cur.execute("PRAGMA synchronous=NORMAL;")
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS alarm_pheromones (
                    repo TEXT NOT NULL,
                    rel_path TEXT NOT NULL,
                    signal_kind TEXT NOT NULL,
                    intensity REAL NOT NULL,
                    half_life_s REAL NOT NULL,
                    hit_count INTEGER NOT NULL DEFAULT 1,
                    last_reason TEXT NOT NULL DEFAULT '',
                    last_agent_id TEXT NOT NULL DEFAULT '',
                    updated_ts REAL NOT NULL,
                    PRIMARY KEY (repo, rel_path, signal_kind)
                )
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_alarm_repo_path ON alarm_pheromones(repo, rel_path);"
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS trail_edges (
                    repo TEXT NOT NULL,
                    file_a TEXT NOT NULL,
                    file_b TEXT NOT NULL,
                    weight REAL NOT NULL,
                    coedit_count INTEGER NOT NULL DEFAULT 1,
                    half_life_s REAL NOT NULL,
                    updated_ts REAL NOT NULL,
                    PRIMARY KEY (repo, file_a, file_b)
                )
                """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_trail_a ON trail_edges(repo, file_a);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_trail_b ON trail_edges(repo, file_b);")
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS methylation_marks (
                    repo TEXT NOT NULL,
                    locus TEXT NOT NULL,
                    gene_policy TEXT NOT NULL,
                    strength REAL NOT NULL,
                    value_json TEXT NOT NULL DEFAULT 'true',
                    half_life_s REAL NOT NULL,
                    reason TEXT NOT NULL DEFAULT '',
                    updated_ts REAL NOT NULL,
                    PRIMARY KEY (repo, locus, gene_policy)
                )
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_methyl_repo_locus ON methylation_marks(repo, locus);"
            )
            self._conn.commit()

    # ------------------------------------------------------------------
    # 1. Alarm Pheromones
    # ------------------------------------------------------------------

    def deposit_alarm(
        self,
        repo: str,
        rel_path: str,
        signal_kind: str,
        severity: float = 0.6,
        reason: str = "",
        agent_id: str = "",
        *,
        half_life_hours: float = 48.0,
        now_ts: float | None = None,
    ) -> dict[str, Any]:
        """Deposit or reinforce an alarm pheromone on `(repo, rel_path)` without touching the file."""
        ts = time.time() if now_ts is None else float(now_ts)
        r_key = _norm_repo(repo)
        p_key = _norm_rel_path(rel_path)
        s_kind = str(signal_kind or "warning").strip().lower()
        sev = max(0.01, min(1.0, float(severity)))
        hl_s = max(60.0, float(half_life_hours) * 3600.0)

        with self._lock:
            row = self._conn.execute(
                """
                SELECT intensity, half_life_s, hit_count, updated_ts
                FROM alarm_pheromones
                WHERE repo = ? AND rel_path = ? AND signal_kind = ?
                """,
                (r_key, p_key, s_kind),
            ).fetchone()

            if row is not None:
                decayed = _decay_value(float(row["intensity"]), ts - float(row["updated_ts"]), float(row["half_life_s"]))
                # Noisy-OR reinforcement smoothly bounded in [0, 1]
                new_intensity = round(min(1.0, 1.0 - (1.0 - decayed) * (1.0 - sev)), 4)
                hit_count = int(row["hit_count"]) + 1
            else:
                new_intensity = round(sev, 4)
                hit_count = 1

            self._conn.execute(
                """
                INSERT INTO alarm_pheromones
                (repo, rel_path, signal_kind, intensity, half_life_s, hit_count, last_reason, last_agent_id, updated_ts)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(repo, rel_path, signal_kind) DO UPDATE SET
                    intensity = excluded.intensity,
                    half_life_s = excluded.half_life_s,
                    hit_count = excluded.hit_count,
                    last_reason = excluded.last_reason,
                    last_agent_id = excluded.last_agent_id,
                    updated_ts = excluded.updated_ts
                """,
                (r_key, p_key, s_kind, new_intensity, hl_s, hit_count, str(reason)[:240], str(agent_id)[:64], ts),
            )
            self._conn.commit()

        return {
            "ok": True,
            "repo": r_key,
            "rel_path": p_key,
            "signal_kind": s_kind,
            "intensity": new_intensity,
            "hit_count": hit_count,
            "updated_ts": ts,
        }

    # ------------------------------------------------------------------
    # 2. Trail Pheromones (Co-Edit Graph)
    # ------------------------------------------------------------------

    def record_coedit(
        self,
        repo: str,
        files: list[str],
        *,
        weight: float = 1.0,
        half_life_days: float = 14.0,
        now_ts: float | None = None,
    ) -> dict[str, Any]:
        """Strengthen bidirectional co-edit trail edges between concurrently modified files."""
        ts = time.time() if now_ts is None else float(now_ts)
        r_key = _norm_repo(repo)
        hl_s = max(60.0, float(half_life_days) * 86400.0)
        w_add = max(0.05, float(weight))

        unique_files: list[str] = []
        seen: set[str] = set()
        for f in files[:50]:
            nf = _norm_rel_path(f)
            if nf and nf not in seen:
                seen.add(nf)
                unique_files.append(nf)

        edges_updated = 0
        if len(unique_files) < 2:
            return {"ok": True, "repo": r_key, "files": len(unique_files), "edges_updated": 0}

        with self._lock:
            for i in range(len(unique_files)):
                for j in range(i + 1, len(unique_files)):
                    a, b = unique_files[i], unique_files[j]
                    if a > b:
                        a, b = b, a
                    row = self._conn.execute(
                        "SELECT weight, coedit_count, half_life_s, updated_ts FROM trail_edges WHERE repo=? AND file_a=? AND file_b=?",
                        (r_key, a, b),
                    ).fetchone()
                    if row is not None:
                        decayed = _decay_value(float(row["weight"]), ts - float(row["updated_ts"]), float(row["half_life_s"]))
                        new_w = round(decayed + w_add, 4)
                        cnt = int(row["coedit_count"]) + 1
                    else:
                        new_w = round(w_add, 4)
                        cnt = 1
                    self._conn.execute(
                        """
                        INSERT INTO trail_edges (repo, file_a, file_b, weight, coedit_count, half_life_s, updated_ts)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(repo, file_a, file_b) DO UPDATE SET
                            weight = excluded.weight,
                            coedit_count = excluded.coedit_count,
                            half_life_s = excluded.half_life_s,
                            updated_ts = excluded.updated_ts
                        """,
                        (r_key, a, b, new_w, cnt, hl_s, ts),
                    )
                    edges_updated += 1
            self._conn.commit()

        return {
            "ok": True,
            "repo": r_key,
            "files": len(unique_files),
            "edges_updated": edges_updated,
            "updated_ts": ts,
        }

    def predict_trail_prefetch(
        self,
        repo: str,
        rel_path: str,
        top_k: int = 5,
        *,
        now_ts: float | None = None,
        min_strength: float = 0.02,
    ) -> list[dict[str, Any]]:
        """Predict top companion files and tests to prefetch along co-edit pheromone trails."""
        ts = time.time() if now_ts is None else float(now_ts)
        r_key = _norm_repo(repo)
        p_key = _norm_rel_path(rel_path)

        with self._lock:
            rows = self._conn.execute(
                """
                SELECT file_b AS neighbor, weight, coedit_count, half_life_s, updated_ts
                FROM trail_edges WHERE repo = ? AND file_a = ?
                UNION ALL
                SELECT file_a AS neighbor, weight, coedit_count, half_life_s, updated_ts
                FROM trail_edges WHERE repo = ? AND file_b = ?
                """,
                (r_key, p_key, r_key, p_key),
            ).fetchall()

        scored: list[dict[str, Any]] = []
        for row in rows:
            eff = _decay_value(float(row["weight"]), ts - float(row["updated_ts"]), float(row["half_life_s"]))
            if eff < min_strength:
                continue
            neighbor = str(row["neighbor"])
            scored.append(
                {
                    "path": neighbor,
                    "strength": round(eff, 4),
                    "coedit_count": int(row["coedit_count"]),
                    "is_test": _is_test_path(neighbor),
                }
            )
        scored.sort(key=lambda item: (-item["strength"], -item["coedit_count"], item["path"]))
        return scored[: max(1, int(top_k))]

    # ------------------------------------------------------------------
    # 3. Epigenetic Methylation Marks
    # ------------------------------------------------------------------

    def methylate(
        self,
        repo: str,
        locus: str,
        gene_policy: str,
        strength: float = 0.8,
        half_life_days: float = 7.0,
        reason: str = "",
        *,
        value: Any = True,
        now_ts: float | None = None,
    ) -> dict[str, Any]:
        """Attach or reinforce an epigenetic methylation mark controlling gene expression on a locus."""
        ts = time.time() if now_ts is None else float(now_ts)
        r_key = _norm_repo(repo)
        l_key = "*" if str(locus).strip() == "*" else _norm_rel_path(locus)
        policy = str(gene_policy).strip()
        if not policy:
            raise ValueError("gene_policy must be non-empty")
        st = max(0.01, min(1.0, float(strength)))
        hl_s = max(60.0, float(half_life_days) * 86400.0)
        val_json = json.dumps(value, separators=(",", ":"), ensure_ascii=False)

        with self._lock:
            row = self._conn.execute(
                "SELECT strength, half_life_s, updated_ts FROM methylation_marks WHERE repo=? AND locus=? AND gene_policy=?",
                (r_key, l_key, policy),
            ).fetchone()
            if row is not None:
                decayed = _decay_value(float(row["strength"]), ts - float(row["updated_ts"]), float(row["half_life_s"]))
                new_st = round(min(1.0, max(decayed, st)), 4)
            else:
                new_st = round(st, 4)

            self._conn.execute(
                """
                INSERT INTO methylation_marks
                (repo, locus, gene_policy, strength, value_json, half_life_s, reason, updated_ts)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(repo, locus, gene_policy) DO UPDATE SET
                    strength = excluded.strength,
                    value_json = excluded.value_json,
                    half_life_s = excluded.half_life_s,
                    reason = excluded.reason,
                    updated_ts = excluded.updated_ts
                """,
                (r_key, l_key, policy, new_st, val_json, hl_s, str(reason)[:240], ts),
            )
            self._conn.commit()

        return {
            "ok": True,
            "repo": r_key,
            "locus": l_key,
            "gene_policy": policy,
            "strength": new_st,
            "value": value,
            "half_life_days": round(hl_s / 86400.0, 3),
            "updated_ts": ts,
        }

    def demethylate(self, repo: str, locus: str, gene_policy: str | None = None) -> dict[str, Any]:
        """Explicitly clear methylation mark(s) on a locus."""
        r_key = _norm_repo(repo)
        l_key = "*" if str(locus).strip() == "*" else _norm_rel_path(locus)
        with self._lock:
            if gene_policy:
                cur = self._conn.execute(
                    "DELETE FROM methylation_marks WHERE repo=? AND locus=? AND gene_policy=?",
                    (r_key, l_key, str(gene_policy).strip()),
                )
            else:
                cur = self._conn.execute(
                    "DELETE FROM methylation_marks WHERE repo=? AND locus=?",
                    (r_key, l_key),
                )
            self._conn.commit()
            removed = int(cur.rowcount)
        return {"ok": True, "removed": removed}

    # ------------------------------------------------------------------
    # 4. Exponential Half-Life Decay / Demethylation
    # ------------------------------------------------------------------

    def evaporate(self, now_ts: float | None = None, *, prune_threshold: float = 0.02) -> dict[str, Any]:
        """Decay all pheromones & methylation marks exponentially and prune healed loci."""
        ts = time.time() if now_ts is None else float(now_ts)
        thresh = max(0.0, float(prune_threshold))

        alarms_decayed = alarms_pruned = 0
        trails_decayed = trails_pruned = 0
        marks_decayed = marks_demethylated = 0

        with self._lock:
            # Alarms
            for row in self._conn.execute("SELECT repo, rel_path, signal_kind, intensity, half_life_s, updated_ts FROM alarm_pheromones").fetchall():
                dt = ts - float(row["updated_ts"])
                if dt <= 0.0:
                    continue
                new_v = _decay_value(float(row["intensity"]), dt, float(row["half_life_s"]))
                if new_v < thresh:
                    self._conn.execute(
                        "DELETE FROM alarm_pheromones WHERE repo=? AND rel_path=? AND signal_kind=?",
                        (row["repo"], row["rel_path"], row["signal_kind"]),
                    )
                    alarms_pruned += 1
                else:
                    self._conn.execute(
                        "UPDATE alarm_pheromones SET intensity=?, updated_ts=? WHERE repo=? AND rel_path=? AND signal_kind=?",
                        (round(new_v, 5), ts, row["repo"], row["rel_path"], row["signal_kind"]),
                    )
                    alarms_decayed += 1

            # Trails
            for row in self._conn.execute("SELECT repo, file_a, file_b, weight, half_life_s, updated_ts FROM trail_edges").fetchall():
                dt = ts - float(row["updated_ts"])
                if dt <= 0.0:
                    continue
                new_v = _decay_value(float(row["weight"]), dt, float(row["half_life_s"]))
                if new_v < thresh:
                    self._conn.execute(
                        "DELETE FROM trail_edges WHERE repo=? AND file_a=? AND file_b=?",
                        (row["repo"], row["file_a"], row["file_b"]),
                    )
                    trails_pruned += 1
                else:
                    self._conn.execute(
                        "UPDATE trail_edges SET weight=?, updated_ts=? WHERE repo=? AND file_a=? AND file_b=?",
                        (round(new_v, 5), ts, row["repo"], row["file_a"], row["file_b"]),
                    )
                    trails_decayed += 1

            # Methylation marks
            for row in self._conn.execute("SELECT repo, locus, gene_policy, strength, half_life_s, updated_ts FROM methylation_marks").fetchall():
                dt = ts - float(row["updated_ts"])
                if dt <= 0.0:
                    continue
                new_v = _decay_value(float(row["strength"]), dt, float(row["half_life_s"]))
                if new_v < thresh:
                    self._conn.execute(
                        "DELETE FROM methylation_marks WHERE repo=? AND locus=? AND gene_policy=?",
                        (row["repo"], row["locus"], row["gene_policy"]),
                    )
                    marks_demethylated += 1
                else:
                    self._conn.execute(
                        "UPDATE methylation_marks SET strength=?, updated_ts=? WHERE repo=? AND locus=? AND gene_policy=?",
                        (round(new_v, 5), ts, row["repo"], row["locus"], row["gene_policy"]),
                    )
                    marks_decayed += 1

            self._conn.commit()

        return {
            "ok": True,
            "now_ts": ts,
            "prune_threshold": thresh,
            "alarms_decayed": alarms_decayed,
            "alarms_pruned": alarms_pruned,
            "trails_decayed": trails_decayed,
            "trails_pruned": trails_pruned,
            "marks_decayed": marks_decayed,
            "marks_demethylated": marks_demethylated,
        }

    # ------------------------------------------------------------------
    # 5. Open Agent Smell-Card (< 40 Tokens Ultra-Compact Advisory)
    # ------------------------------------------------------------------

    def smell(
        self,
        repo: str,
        rel_path: str,
        max_tokens: int = 40,
        *,
        now_ts: float | None = None,
        min_active: float = 0.05,
    ) -> dict[str, Any]:
        """Return a strictly `< max_tokens` (default `< 40`) structured smell-card for any AI agent."""
        t0 = time.perf_counter()
        ts = time.time() if now_ts is None else float(now_ts)
        budget = max(10, int(max_tokens))
        r_key = _norm_repo(repo)
        p_key = _norm_rel_path(rel_path)

        with self._lock:
            alarm_rows = self._conn.execute(
                """
                SELECT signal_kind, intensity, half_life_s, updated_ts
                FROM alarm_pheromones WHERE repo = ? AND rel_path = ?
                """,
                (r_key, p_key),
            ).fetchall()

            loci = _ancestor_loci(p_key)
            placeholders = ",".join("?" for _ in loci)
            methyl_rows = self._conn.execute(
                f"""
                SELECT locus, gene_policy, strength, value_json, half_life_s, updated_ts
                FROM methylation_marks WHERE repo = ? AND locus IN ({placeholders})
                """,
                (r_key, *loci),
            ).fetchall()

        # Combine active alarm pheromones via noisy-OR
        combined_complement = 1.0
        top_signal = ""
        top_signal_val = 0.0
        for row in alarm_rows:
            eff = _decay_value(float(row["intensity"]), ts - float(row["updated_ts"]), float(row["half_life_s"]))
            if eff >= min_active:
                combined_complement *= (1.0 - min(1.0, eff))
                if eff > top_signal_val:
                    top_signal_val = eff
                    top_signal = str(row["signal_kind"])
        alarm_level = round(1.0 - combined_complement, 3)

        # Resolve active methylation flags (most specific locus wins for same gene_policy)
        locus_rank = {loc: idx for idx, loc in enumerate(loci)}
        active_marks: dict[str, tuple[int, float, Any]] = {}
        for row in methyl_rows:
            eff = _decay_value(float(row["strength"]), ts - float(row["updated_ts"]), float(row["half_life_s"]))
            if eff < min_active:
                continue
            pol = str(row["gene_policy"])
            rank = locus_rank.get(str(row["locus"]), 99)
            try:
                val = json.loads(row["value_json"])
            except Exception:
                val = True
            if pol not in active_marks or rank < active_marks[pol][0]:
                active_marks[pol] = (rank, eff, val)

        ordered_flags = [
            pol for pol, _meta in sorted(active_marks.items(), key=lambda kv: (-kv[1][1], kv[0]))
        ]
        # Trail prefetch companions
        trails = self.predict_trail_prefetch(r_key, p_key, top_k=3, now_ts=ts, min_strength=min_active)
        companions_full = [t["path"] for t in trails]

        # Build concise advisory
        if alarm_level >= 0.70:
            advisory = f"hot:{top_signal or 'risk'};verify+lease"
        elif alarm_level >= 0.35:
            advisory = f"caution:{top_signal or 'warm'};run_tests"
        elif ordered_flags:
            advisory = "methylated;follow_flags"
        elif companions_full:
            advisory = "calm;prefetch_trail"
        else:
            advisory = "clear"

        # Enforce strict `< max_tokens` budget across BOTH `card_text` and compact structured fields
        flags_out = list(ordered_flags[:3])
        companions_out = list(companions_full[:3])

        def _render_card(fl: list[str], comp: list[str], adv: str) -> str:
            parts = [f"a={alarm_level:.2f}"]
            if fl:
                parts.append("m=" + ",".join(fl))
            if comp:
                parts.append("t=" + ",".join(_short_label(c) for c in comp))
            parts.append(adv)
            return " ".join(parts)

        card_text = _render_card(flags_out, companions_out, advisory)
        while _estimate_tokens(card_text) >= budget:
            if len(companions_out) > 1:
                companions_out.pop()
            elif len(flags_out) > 1:
                flags_out.pop()
            elif companions_out:
                companions_out.pop()
            elif flags_out:
                flags_out.pop()
            else:
                advisory = advisory[: max(4, (budget - 4) * 3)]
                card_text = _render_card(flags_out, companions_out, advisory)
                break
            card_text = _render_card(flags_out, companions_out, advisory)

        # Final hard clamp on card_text to strictly < budget tokens
        max_chars = max(8, (budget - 1) * 4 - 1)
        if len(card_text) > max_chars:
            card_text = card_text[:max_chars].rstrip()

        token_est = _estimate_tokens(card_text)
        elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 4)

        return {
            "repo": r_key,
            "path": p_key,
            "alarm_level": alarm_level,
            "methylation_flags": flags_out,
            "trail_companions": companions_out,
            "advisory": advisory,
            "card_text": card_text,
            "token_est": token_est,
            "max_tokens": budget,
            "elapsed_ms": elapsed_ms,
        }

    def status(self, repo: str | None = None) -> dict[str, Any]:
        with self._lock:
            if repo is not None:
                r_key = _norm_repo(repo)
                a_cnt = self._conn.execute("SELECT COUNT(*) FROM alarm_pheromones WHERE repo=?", (r_key,)).fetchone()[0]
                t_cnt = self._conn.execute("SELECT COUNT(*) FROM trail_edges WHERE repo=?", (r_key,)).fetchone()[0]
                m_cnt = self._conn.execute("SELECT COUNT(*) FROM methylation_marks WHERE repo=?", (r_key,)).fetchone()[0]
            else:
                a_cnt = self._conn.execute("SELECT COUNT(*) FROM alarm_pheromones").fetchone()[0]
                t_cnt = self._conn.execute("SELECT COUNT(*) FROM trail_edges").fetchone()[0]
                m_cnt = self._conn.execute("SELECT COUNT(*) FROM methylation_marks").fetchone()[0]

        return {
            "organ": "CHIMERA-STIGMERGY",
            "ephemeral": self.ephemeral,
            "repo_files_modified": 0,
            "active_alarms": int(a_cnt),
            "trail_edges": int(t_cnt),
            "methylation_marks": int(m_cnt),
        }

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass

    def __enter__(self) -> "StigmergicEpigenome":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass
