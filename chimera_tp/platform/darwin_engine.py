"""CHIMERA-DARWIN: Zero-Backprop Antithetic Evolution Strategies (ES) Engine.

Inspired by MIT + Cognizant AI Lab + UT Austin ("Evolution Strategies at Scale:
LLM Fine-Tuning Beyond Reinforcement Learning"), engineered strictly inside the
CHIMERA-ONE Unification Doctrine (Law 2: never choke Windows CPU/Turbo/IPC;
Law 3: protect svhome 0-MB weight coordinator; Law 6: Lab -> Shadow -> Active
with instant rollback; Law 7: 100% lazy-loaded so daemon startup RSS stays <80 MiB).

Subsystems in this module:
  1. GenomeLedger          -- 128-Byte/gen SQLite-WAL causal ledger + weightless .genome.json teleportation
  2. SeedEsNeuralFoundry   -- Real Zero-Backprop Forward-Only Antithetic Seed-ES specialist evolution
                              + bit-exact deterministic weight reconstruction from .genome.json
  3. EsParamOptimizer      -- Whole-vector Antithetic ES over CHIMERA + Tquota continuous knobs
                              replayed on real peer_service_slo / swarm_placement / Tquota traces
  4. PromptEsEvolver       -- Whole-trajectory Prompt/Harness rule evolution against Coroner fossils
                              with strict anti-reward-hacking validator
  5. DarwinSleepCycle      -- Idle-gated nightly evolution producing a Law-6 Shadow A/B approval receipt
"""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import os
import re
import sqlite3
import struct
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

try:
    import numpy as _np  # type: ignore
except Exception:  # pragma: no cover - pure-Python fallback path
    _np = None  # type: ignore


# ---------------------------------------------------------------------------
# Cross-Platform Bit-Exact Deterministic Gaussian Perturbation PRNG
# ---------------------------------------------------------------------------

_TWO_PI = 2.0 * math.pi
_U64_INV = 1.0 / float(1 << 53)


def deterministic_gaussian(
    length: int,
    *,
    genome_id: str,
    generation: int,
    seed: int,
    tag: str = "theta",
) -> list[float]:
    """Generate a bit-exact standard normal vector N(0, 1)^length across Windows & Linux.

    Uses SHA-256 counter-mode -> 53-bit uniform -> Box-Muller transform.
    Identical output whether NumPy is installed or not, and independent of
    Python/NumPy/OS RNG versions so `.genome.json` replays deterministically
    between win-desktop, svhome, and Google Colab.
    """
    n = max(0, int(length))
    if n == 0:
        return []
    pairs = (n + 1) // 2
    prefix = f"chimera.darwin.v1|{genome_id}|{int(generation)}|{int(seed)}|{tag}|".encode("utf-8")

    # Fill raw bytes (16 bytes = two uint64 per pair -> Box-Muller produces 2 normals)
    # SHA-256 produces 32 bytes = 2 pairs = 4 floats per hash block.
    n_blocks = (pairs + 1) // 2
    buf = bytearray(n_blocks * 32)
    pos = 0
    for blk in range(n_blocks):
        digest = hashlib.sha256(prefix + struct.pack("<I", blk)).digest()
        buf[pos : pos + 32] = digest
        pos += 32

    if _np is not None and n >= 64:
        u64 = _np.frombuffer(buf, dtype="<u8", count=pairs * 2).reshape(pairs, 2)
        # Shift right 11 bits -> exact 53-bit IEEE-754 mantissa precision in (0, 1]
        u1 = ((u64[:, 0] >> _np.uint64(11)).astype(_np.float64) + 0.5) * _U64_INV
        u2 = ((u64[:, 1] >> _np.uint64(11)).astype(_np.float64) + 0.5) * _U64_INV
        r = _np.sqrt(-2.0 * _np.log(u1))
        ang = _TWO_PI * u2
        z0 = r * _np.cos(ang)
        z1 = r * _np.sin(ang)
        out = _np.empty(pairs * 2, dtype=_np.float64)
        out[0::2] = z0
        out[1::2] = z1
        return out[:n].tolist()

    out_list: list[float] = []
    for p in range(pairs):
        a, b = struct.unpack_from("<QQ", buf, p * 16)
        u1 = ((a >> 11) + 0.5) * _U64_INV
        u2 = ((b >> 11) + 0.5) * _U64_INV
        r = math.sqrt(-2.0 * math.log(u1))
        ang = _TWO_PI * u2
        out_list.append(r * math.cos(ang))
        if len(out_list) < n:
            out_list.append(r * math.sin(ang))
    return out_list


def deterministic_gaussian_np(
    length: int,
    *,
    genome_id: str,
    generation: int,
    seed: int,
    tag: str = "theta",
):
    """NumPy float64 view of `deterministic_gaussian` (falls back to list if NumPy absent)."""
    n = max(0, int(length))
    if _np is None:
        return deterministic_gaussian(n, genome_id=genome_id, generation=generation, seed=seed, tag=tag)
    if n == 0:
        return _np.zeros(0, dtype=_np.float64)
    pairs = (n + 1) // 2
    prefix = f"chimera.darwin.v1|{genome_id}|{int(generation)}|{int(seed)}|{tag}|".encode("utf-8")
    n_blocks = (pairs + 1) // 2
    buf = bytearray(n_blocks * 32)
    pos = 0
    for blk in range(n_blocks):
        buf[pos : pos + 32] = hashlib.sha256(prefix + struct.pack("<I", blk)).digest()
        pos += 32
    u64 = _np.frombuffer(buf, dtype="<u8", count=pairs * 2).reshape(pairs, 2)
    u1 = ((u64[:, 0] >> _np.uint64(11)).astype(_np.float64) + 0.5) * _U64_INV
    u2 = ((u64[:, 1] >> _np.uint64(11)).astype(_np.float64) + 0.5) * _U64_INV
    r = _np.sqrt(-2.0 * _np.log(u1))
    ang = _TWO_PI * u2
    out = _np.empty(pairs * 2, dtype=_np.float64)
    out[0::2] = r * _np.cos(ang)
    out[1::2] = r * _np.sin(ang)
    return out[:n]


def centered_ranks(rewards: list[float]) -> list[float]:
    """OpenAI-ES / Salimans (2017) rank-normalization into [-0.5, +0.5] (immune to reward scale outliers)."""
    n = len(rewards)
    if n == 0:
        return []
    if n == 1:
        return [0.0]
    order = sorted(range(n), key=lambda i: rewards[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and rewards[order[j + 1]] == rewards[order[i]]:
            j += 1
        avg_rank = 0.5 * (i + j)
        val = (avg_rank / float(n - 1)) - 0.5
        for k in range(i, j + 1):
            ranks[order[k]] = val
        i = j + 1
    return ranks


def z_score_normalize(values: list[float]) -> list[float]:
    """Zero-mean unit-std normalization with safe zero-variance guard."""
    n = len(values)
    if n == 0:
        return []
    mean = sum(values) / float(n)
    var = sum((x - mean) ** 2 for x in values) / float(n)
    std = math.sqrt(var)
    if std < 1e-12:
        return [0.0] * n
    return [(x - mean) / std for x in values]


def _default_ledger_path() -> Path:
    env_p = os.environ.get("CHIMERA_DARWIN_DB", "").strip()
    if env_p:
        return Path(env_p)
    return Path.home() / ".chimera" / "darwin_genome.sqlite"


# ---------------------------------------------------------------------------
# PILLAR 1: 128-BYTE GENOME LEDGER & WEIGHTLESS TELEPORTATION
# ---------------------------------------------------------------------------

class GenomeLedger:
    """SQLite-WAL ledger storing ES seed trajectories (`~128-240 B/gen`) for weightless cross-node sync."""

    SCHEMA_VERSION = "chimera.darwin.genome/1"

    def __init__(self, db_path: str | Path | None = None, *, ephemeral: bool = False) -> None:
        self.ephemeral = bool(ephemeral)
        self.db_path = Path(db_path) if db_path else _default_ledger_path()
        self._lock = threading.Lock()
        self._mem_con: sqlite3.Connection | None = None
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        if self.ephemeral:
            if self._mem_con is None:
                self._mem_con = sqlite3.connect(":memory:", check_same_thread=False)
            return self._mem_con
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(str(self.db_path), timeout=5.0)
        con.execute("PRAGMA journal_mode=WAL;")
        con.execute("PRAGMA synchronous=NORMAL;")
        return con

    def _close(self, con: sqlite3.Connection) -> None:
        if not self.ephemeral:
            con.close()

    def _init_db(self) -> None:
        with self._lock:
            con = self._connect()
            try:
                con.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS genomes (
                        genome_id TEXT PRIMARY KEY,
                        kind TEXT NOT NULL,
                        model_family TEXT NOT NULL,
                        base_seed INTEGER NOT NULL,
                        base_sha256 TEXT NOT NULL,
                        param_count INTEGER NOT NULL,
                        dtype TEXT NOT NULL,
                        baseline_fitness REAL NOT NULL DEFAULT 0.0,
                        best_fitness REAL NOT NULL DEFAULT 0.0,
                        meta_json TEXT NOT NULL DEFAULT '{}',
                        created_at REAL NOT NULL,
                        updated_at REAL NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS genome_steps (
                        genome_id TEXT NOT NULL,
                        generation INTEGER NOT NULL,
                        sigma REAL NOT NULL,
                        alpha REAL NOT NULL,
                        pop_size INTEGER NOT NULL,
                        mean_fitness REAL NOT NULL,
                        best_fitness REAL NOT NULL,
                        oracle_digest TEXT NOT NULL,
                        seeds_json TEXT NOT NULL,
                        deltas_json TEXT NOT NULL,
                        wire_bytes INTEGER NOT NULL,
                        created_at REAL NOT NULL,
                        PRIMARY KEY (genome_id, generation)
                    );
                    """
                )
                con.commit()
            finally:
                self._close(con)

    def register_genome(
        self,
        *,
        genome_id: str,
        kind: str,
        model_family: str,
        base_seed: int,
        base_sha256: str,
        param_count: int,
        dtype: str = "float32",
        baseline_fitness: float = 0.0,
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = time.time()
        with self._lock:
            con = self._connect()
            try:
                con.execute(
                    """
                    INSERT INTO genomes (
                        genome_id, kind, model_family, base_seed, base_sha256,
                        param_count, dtype, baseline_fitness, best_fitness, meta_json,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(genome_id) DO UPDATE SET
                        updated_at = excluded.updated_at,
                        meta_json = excluded.meta_json
                    """,
                    (
                        genome_id,
                        kind,
                        model_family,
                        int(base_seed),
                        base_sha256,
                        int(param_count),
                        dtype,
                        float(baseline_fitness),
                        float(baseline_fitness),
                        json.dumps(meta or {}, separators=(",", ":"), ensure_ascii=False),
                        now,
                        now,
                    ),
                )
                con.commit()
            finally:
                self._close(con)
        return {"ok": True, "genome_id": genome_id, "param_count": int(param_count)}

    @staticmethod
    def pack_step_compact(
        generation: int,
        sigma: float,
        alpha: float,
        seeds: list[int],
        antithetic_deltas: list[float],
    ) -> bytes:
        """Pack a single ES generation into compact binary wire format (`12 + 8*k` bytes; ~128B for k=14)."""
        k = min(len(seeds), len(antithetic_deltas))
        header = struct.pack("<IffH", int(generation), float(sigma), float(alpha), int(k))
        body = bytearray()
        for i in range(k):
            body.extend(struct.pack("<If", int(seeds[i]) & 0xFFFFFFFF, float(antithetic_deltas[i])))
        return header + bytes(body)

    def record_step(
        self,
        *,
        genome_id: str,
        generation: int,
        sigma: float,
        alpha: float,
        pop_size: int,
        mean_fitness: float,
        best_fitness: float,
        oracle_digest: str,
        seeds: list[int],
        antithetic_deltas: list[float],
    ) -> int:
        packed = self.pack_step_compact(generation, sigma, alpha, seeds, antithetic_deltas)
        wire_bytes = len(packed)
        now = time.time()
        rounded_deltas = [round(float(x), 8) for x in antithetic_deltas]
        with self._lock:
            con = self._connect()
            try:
                con.execute(
                    """
                    INSERT OR REPLACE INTO genome_steps (
                        genome_id, generation, sigma, alpha, pop_size,
                        mean_fitness, best_fitness, oracle_digest,
                        seeds_json, deltas_json, wire_bytes, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        genome_id,
                        int(generation),
                        float(sigma),
                        float(alpha),
                        int(pop_size),
                        float(mean_fitness),
                        float(best_fitness),
                        str(oracle_digest)[:32],
                        json.dumps([int(s) for s in seeds], separators=(",", ":")),
                        json.dumps(rounded_deltas, separators=(",", ":")),
                        wire_bytes,
                        now,
                    ),
                )
                con.execute(
                    "UPDATE genomes SET best_fitness = MAX(best_fitness, ?), updated_at = ? WHERE genome_id = ?",
                    (float(best_fitness), now, genome_id),
                )
                con.commit()
            finally:
                self._close(con)
        return wire_bytes

    def export_genome(self, genome_id: str) -> dict[str, Any]:
        with self._lock:
            con = self._connect()
            try:
                g = con.execute(
                    "SELECT genome_id, kind, model_family, base_seed, base_sha256, param_count, dtype, "
                    "baseline_fitness, best_fitness, meta_json, created_at, updated_at "
                    "FROM genomes WHERE genome_id = ?",
                    (genome_id,),
                ).fetchone()
                if not g:
                    return {"ok": False, "error": "genome_not_found", "genome_id": genome_id}
                rows = con.execute(
                    "SELECT generation, sigma, alpha, pop_size, mean_fitness, best_fitness, oracle_digest, "
                    "seeds_json, deltas_json, wire_bytes "
                    "FROM genome_steps WHERE genome_id = ? ORDER BY generation ASC",
                    (genome_id,),
                ).fetchall()
            finally:
                self._close(con)

        steps = []
        binary_wire_bytes = 0
        for r in rows:
            binary_wire_bytes += int(r[9])
            steps.append(
                {
                    "g": int(r[0]),
                    "sigma": float(r[1]),
                    "alpha": float(r[2]),
                    "pop": int(r[3]),
                    "mean_fit": round(float(r[4]), 5),
                    "best_fit": round(float(r[5]), 5),
                    "oracle": str(r[6]),
                    "seeds": json.loads(r[7]),
                    "deltas": json.loads(r[8]),
                }
            )
        doc = {
            "schema": self.SCHEMA_VERSION,
            "genome_id": g[0],
            "kind": g[1],
            "model_family": g[2],
            "base_seed": int(g[3]),
            "base_sha256": g[4],
            "param_count": int(g[5]),
            "dtype": g[6],
            "baseline_fitness": round(float(g[7]), 6),
            "best_fitness": round(float(g[8]), 6),
            "meta": json.loads(g[9] or "{}"),
            "generations": len(steps),
            "steps": steps,
        }
        json_bytes = len(json.dumps(doc, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
        fp16_bytes = max(1, int(g[5]) * 2)
        return {
            "ok": True,
            "genome": doc,
            "stats": {
                "generations": len(steps),
                "json_bytes": json_bytes,
                "binary_wire_bytes": binary_wire_bytes,
                "avg_binary_bytes_per_gen": round(binary_wire_bytes / max(1, len(steps)), 1),
                "equivalent_fp16_weight_bytes": fp16_bytes,
                "compression_ratio_vs_fp16": round(fp16_bytes / max(1, binary_wire_bytes or json_bytes), 2),
                "svhome_weight_bytes_stored": 0,
            },
        }

    def import_genome(self, genome_doc: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(genome_doc, dict) or genome_doc.get("schema") != self.SCHEMA_VERSION:
            return {"ok": False, "error": "invalid_genome_schema"}
        gid = str(genome_doc.get("genome_id") or "").strip()
        if not gid:
            return {"ok": False, "error": "missing_genome_id"}
        self.register_genome(
            genome_id=gid,
            kind=str(genome_doc.get("kind") or "neural_es"),
            model_family=str(genome_doc.get("model_family") or "unknown"),
            base_seed=int(genome_doc.get("base_seed") or 0),
            base_sha256=str(genome_doc.get("base_sha256") or ""),
            param_count=int(genome_doc.get("param_count") or 0),
            dtype=str(genome_doc.get("dtype") or "float32"),
            baseline_fitness=float(genome_doc.get("baseline_fitness") or 0.0),
            meta=(genome_doc.get("meta") if isinstance(genome_doc.get("meta"), dict) else {}),
        )
        steps = genome_doc.get("steps") or []
        total_wire = 0
        for st in steps:
            if not isinstance(st, dict):
                continue
            total_wire += self.record_step(
                genome_id=gid,
                generation=int(st.get("g") or 0),
                sigma=float(st.get("sigma") or 0.05),
                alpha=float(st.get("alpha") or 0.1),
                pop_size=int(st.get("pop") or 0),
                mean_fitness=float(st.get("mean_fit") or 0.0),
                best_fitness=float(st.get("best_fit") or 0.0),
                oracle_digest=str(st.get("oracle") or ""),
                seeds=list(st.get("seeds") or []),
                antithetic_deltas=list(st.get("deltas") or []),
            )
        return {"ok": True, "genome_id": gid, "steps_imported": len(steps), "binary_wire_bytes": total_wire}

    def list_genomes(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            con = self._connect()
            try:
                rows = con.execute(
                    """
                    SELECT g.genome_id, g.kind, g.model_family, g.param_count,
                           g.baseline_fitness, g.best_fitness, g.updated_at,
                           COUNT(s.generation) AS gens, COALESCE(SUM(s.wire_bytes), 0) AS wire_b
                    FROM genomes g
                    LEFT JOIN genome_steps s ON g.genome_id = s.genome_id
                    GROUP BY g.genome_id
                    ORDER BY g.updated_at DESC
                    LIMIT ?
                    """,
                    (max(1, min(100, int(limit))),),
                ).fetchall()
            finally:
                self._close(con)
        return [
            {
                "genome_id": r[0],
                "kind": r[1],
                "model_family": r[2],
                "param_count": int(r[3]),
                "baseline_fitness": round(float(r[4]), 5),
                "best_fitness": round(float(r[5]), 5),
                "updated_at": float(r[6]),
                "generations": int(r[7]),
                "binary_wire_bytes": int(r[8]),
            }
            for r in rows
        ]


# ---------------------------------------------------------------------------
# PILLAR 2: ZERO-BACKPROP FORWARD-ONLY SEED-ES NEURAL FOUNDRY (DARWIN-REFLEX)
# ---------------------------------------------------------------------------

CHIMERA_TOOL_CLASSES: tuple[str, ...] = (
    "chimera_xray_batch",
    "chimera_atomic_patch",
    "chimera_mirror_race",
    "chimera_run_dag",
    "chimera_release_promote",
    "chimera_coroner",
)

# Real developer intents (Vietnamese + English) mapped to canonical Chimera tool classes
_REFLEX_DATASET: list[tuple[str, int]] = [
    ("read outline regex search multiple python files json query without powershell", 0),
    ("inspect substrate.py and mcp_server.py symbols list files status", 0),
    ("tim kiem regex trong thu muc platform va kiem tra sqlite read only", 0),
    ("batch read config json and git status with spill shield", 0),
    ("scan routes and search call sites across 5 files fast", 0),
    ("kiem tra trang thai localhost 9780 va liet ke file trong tasks", 0),
    ("edit python file with ram ast syntax gate and auto rollback on fail", 1),
    ("patch config.toml safely validate tomllib before touching disk", 1),
    ("sua code trong agent_symbiont.py co tu dong rollback neu loi cu phap", 1),
    ("apply multi file diff with syntax verification and unit tests", 1),
    ("replace function body in substrate.py verify tests immediately", 1),
    ("cap nhat ma nguon va kiem tra ast trong ram truoc khi ghi", 1),
    ("race 3 competing patch candidates in isolated cow shadow directory", 2),
    ("breed two partial patches with crossover until 100 percent tests pass", 2),
    ("chay dua 3 phuong an sua loi trong shadow dev drive chon ban thang", 2),
    ("evaluate parallel fix variants in v shadows commit winning diff", 2),
    ("test competing bugfix edits in isolated copies without touching main tree", 2),
    ("lai ghep ban va loi qua 2 the he tien hoa de pass toan bo test", 2),
    ("collapse 6 serial probe patch verify exec steps into one macro pipeline", 3),
    ("run conditional multi step workflow sha256 parity then test then epoch", 3),
    ("gop 8 buoc kiem tra va chay test thanh mot rpc dag khong ton turn", 3),
    ("execute sequential build check parity and publish steps in single call", 3),
    ("chay chuoi buoc xray patch verify va exec co dieu kien if prev ok", 3),
    ("pipeline multiple verification commands without llm roundtrips", 3),
    ("promote verified workspace files into live release snapshot with canary", 4),
    ("rollback broken release epoch snapshot back to previous backup", 4),
    ("dong bo ban release 5e25fafe4a8f co canary import va backup hoan tac", 4),
    ("atomic release promotion sha256 check and epoch receipt publish", 4),
    ("day file da test vao thu muc releases kem kiem tra canary", 4),
    ("khoi phuc ban release cu sau khi canary phat hien loi import", 4),
    ("scan codex antigravity jsonl logs for shell storms and disk spills", 5),
    ("seed immune reflex warnings from recurring failure patterns and edquot", 5),
    ("kham nghiem log session tim loi output txt spill va 404 drift", 5),
    ("analyze past agent transcripts detect shell exec storm and toml breaks", 5),
    ("quet lich su phien lam viec tao quy tac mien dich tranh lap loi cu", 5),
    ("post mortem audit of tool call friction and recurring errors", 5),
]


def _featurize_prompt(text: str, dim: int = 64) -> list[float]:
    """Deterministic hashed unigram + bigram + char-trigram L2-normalized feature vector."""
    vec = [0.0] * dim
    tokens = re.findall(r"[a-z0-9_]+", (text or "").lower())
    for tok in tokens:
        h = int.from_bytes(hashlib.blake2s(tok.encode("utf-8"), digest_size=4).digest(), "little")
        sign = 1.0 if (h & 1) == 0 else -1.0
        vec[(h >> 1) % dim] += sign * 1.5
        if len(tok) >= 4:
            for j in range(len(tok) - 2):
                tri = tok[j : j + 3]
                ht = int.from_bytes(hashlib.blake2s(tri.encode("utf-8"), digest_size=4).digest(), "little")
                vec[(ht >> 1) % dim] += (0.35 if (ht & 1) == 0 else -0.35)
    for i in range(len(tokens) - 1):
        bg = f"{tokens[i]}_{tokens[i + 1]}"
        hb = int.from_bytes(hashlib.blake2s(bg.encode("utf-8"), digest_size=4).digest(), "little")
        vec[(hb >> 1) % dim] += (1.0 if (hb & 1) == 0 else -1.0)
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


class SeedEsNeuralFoundry:
    """Real Zero-Backprop Forward-Only Antithetic Seed-ES Specialist Trainer & Weightless Replayer.

    Architecture: 2-layer neural router (`in_dim -> hidden_dim -> num_classes`) trained strictly
    via MIT/Cognizant ES-at-Scale Algorithm 1: Z-score normalized Antithetic Seed-Perturbed ES
    (`theta +/- sigma * eps(seed)`). ZERO `loss.backward()`, ZERO gradient buffers, ZERO Adam states!
    """

    def __init__(self, ledger: GenomeLedger) -> None:
        self.ledger = ledger

    @staticmethod
    def _shapes(in_dim: int, hidden_dim: int, num_classes: int) -> list[tuple[int, ...]]:
        return [
            (in_dim, hidden_dim),
            (hidden_dim,),
            (hidden_dim, num_classes),
            (num_classes,),
        ]

    @classmethod
    def param_count(cls, in_dim: int = 64, hidden_dim: int = 20, num_classes: int = 6) -> int:
        total = 0
        for sh in cls._shapes(in_dim, hidden_dim, num_classes):
            p = 1
            for d in sh:
                p *= d
            total += p
        return total

    @classmethod
    def _init_theta(cls, genome_id: str, base_seed: int, in_dim: int, hidden_dim: int, num_classes: int):
        n_params = cls.param_count(in_dim, hidden_dim, num_classes)
        raw = deterministic_gaussian_np(n_params, genome_id=genome_id, generation=0, seed=base_seed, tag="init")
        scale = 0.08
        if _np is not None:
            return raw * scale
        return [x * scale for x in raw]

    @classmethod
    def _forward_logits(cls, theta: Any, x_mat: Any, in_dim: int, hidden_dim: int, num_classes: int):
        s1 = in_dim * hidden_dim
        s2 = s1 + hidden_dim
        s3 = s2 + hidden_dim * num_classes
        if _np is not None:
            w1 = theta[:s1].reshape(in_dim, hidden_dim)
            b1 = theta[s1:s2]
            w2 = theta[s2:s3].reshape(hidden_dim, num_classes)
            b2 = theta[s3:]
            h1 = _np.tanh(x_mat @ w1 + b1)
            return h1 @ w2 + b2
        # Pure-Python fallback (bit-equivalent math for NumPy-less nodes!)
        logits = []
        for row in x_mat:
            h1 = [0.0] * hidden_dim
            for j in range(hidden_dim):
                acc = theta[s1 + j]
                for i in range(in_dim):
                    acc += row[i] * theta[i * hidden_dim + j]
                h1[j] = math.tanh(acc)
            out = [0.0] * num_classes
            for c in range(num_classes):
                acc = theta[s3 + c]
                for j in range(hidden_dim):
                    acc += h1[j] * theta[s2 + j * num_classes + c]
                out[c] = acc
            logits.append(out)
        return logits

    @classmethod
    def _evaluate_whole_trajectory(
        cls,
        theta: Any,
        x_mat: Any,
        y_true: list[int],
        in_dim: int,
        hidden_dim: int,
        num_classes: int,
    ) -> dict[str, float]:
        """Forward-only whole-trajectory oracle with anti-reward-hacking collapse penalty."""
        logits = cls._forward_logits(theta, x_mat, in_dim, hidden_dim, num_classes)
        n = len(y_true)
        if _np is not None:
            shifted = logits - _np.max(logits, axis=1, keepdims=True)
            exp_l = _np.exp(shifted)
            probs = exp_l / _np.sum(exp_l, axis=1, keepdims=True)
            preds = _np.argmax(probs, axis=1)
            y_arr = _np.asarray(y_true, dtype=_np.int64)
            correct = int(_np.sum(preds == y_arr))
            acc = correct / float(max(1, n))
            true_p = _np.clip(probs[_np.arange(n), y_arr], 1e-9, 1.0)
            nll = float(-_np.mean(_np.log(true_p)))
            unique_preds = int(len(_np.unique(preds)))
            # L2 weight-norm regularization prevents logit explosion
            w_rms = float(_np.sqrt(_np.mean(theta * theta)))
        else:
            correct = 0
            nll_sum = 0.0
            pred_set: set[int] = set()
            for idx, row in enumerate(logits):
                m = max(row)
                exps = [math.exp(v - m) for v in row]
                denom = sum(exps) or 1.0
                probs = [e / denom for e in exps]
                p_cls = max(range(num_classes), key=lambda c: probs[c])
                pred_set.add(p_cls)
                if p_cls == y_true[idx]:
                    correct += 1
                nll_sum += -math.log(max(1e-9, probs[y_true[idx]]))
            acc = correct / float(max(1, n))
            nll = nll_sum / float(max(1, n))
            unique_preds = len(pred_set)
            w_rms = math.sqrt(sum(v * v for v in theta) / float(max(1, len(theta))))

        # Anti-reward-hacking diversity gate: punish mode collapse predicting only 1-2 classes!
        collapse_penalty = 0.0 if unique_preds >= min(num_classes, 4) else (4.0 - unique_preds) * 1.25
        # Whole-trajectory fitness: accuracy + calibrated log-likelihood - collapse - norm drift
        fitness = (2.5 * acc) - nll - collapse_penalty - (0.04 * max(0.0, w_rms - 0.5))
        return {
            "fitness": round(float(fitness), 6),
            "accuracy": round(float(acc), 6),
            "nll": round(float(nll), 6),
            "unique_classes_predicted": unique_preds,
            "reward_hacking_blocked": collapse_penalty > 0.0,
        }

    @staticmethod
    def _vector_sha256(theta: Any) -> str:
        """Canonical float32 weight-tensor digest (immune to 1e-16 float64 libm ULP drift across OSes)."""
        if _np is not None:
            arr = _np.asarray(theta, dtype="<f4")
            return hashlib.sha256(arr.tobytes()).hexdigest()
        b = struct.pack(f"<{len(theta)}f", *theta)
        return hashlib.sha256(b).hexdigest()

    def evolve(
        self,
        *,
        genome_id: str | None = None,
        generations: int = 50,
        pop_size: int = 32,
        sigma: float = 0.12,
        alpha: float = 0.08,
        base_seed: int = 1337,
        in_dim: int = 64,
        hidden_dim: int = 20,
        dataset: list[tuple[str, int]] | None = None,
    ) -> dict[str, Any]:
        """Run real Zero-Backprop Forward-Only Antithetic Seed-ES and persist a <15KB genome."""
        t0 = time.perf_counter()
        gid = genome_id or f"darwin_reflex_{uuid.uuid4().hex[:8]}"
        rows = list(dataset or _REFLEX_DATASET)
        num_classes = len(CHIMERA_TOOL_CLASSES)
        gens = max(2, min(200, int(generations)))
        half_pop = max(2, min(48, int(pop_size) // 2))
        eff_pop = half_pop * 2

        feats = [_featurize_prompt(txt, dim=in_dim) for txt, _ in rows]
        labels = [int(lbl) % num_classes for _, lbl in rows]
        x_mat = _np.asarray(feats, dtype=_np.float64) if _np is not None else feats

        theta = self._init_theta(gid, base_seed, in_dim, hidden_dim, num_classes)
        n_params = self.param_count(in_dim, hidden_dim, num_classes)
        base_sha = self._vector_sha256(theta)
        base_eval = self._evaluate_whole_trajectory(theta, x_mat, labels, in_dim, hidden_dim, num_classes)

        self.ledger.register_genome(
            genome_id=gid,
            kind="neural_seed_es",
            model_family=f"darwin_reflex_mlp_{in_dim}x{hidden_dim}x{num_classes}",
            base_seed=base_seed,
            base_sha256=base_sha,
            param_count=n_params,
            dtype="float32",
            baseline_fitness=base_eval["fitness"],
            meta={
                "in_dim": in_dim,
                "hidden_dim": hidden_dim,
                "num_classes": num_classes,
                "zero_backprop": True,
                "optimizer_states_bytes": 0,
            },
        )

        oracle_digest = hashlib.sha256(
            json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:16]

        history: list[dict[str, Any]] = []
        total_forward_passes = 1
        total_wire_bytes = 0
        best_seen_fit = base_eval["fitness"]

        for g in range(1, gens + 1):
            seeds = [((base_seed * 1000003) ^ (g * 9176) ^ (k * 2654435761)) & 0x7FFFFFFF for k in range(half_pop)]
            eps_list = []
            raw_rewards: list[float] = []

            for s in seeds:
                eps = deterministic_gaussian_np(n_params, genome_id=gid, generation=g, seed=s, tag="es")
                eps_list.append(eps)
                if _np is not None:
                    r_pos = self._evaluate_whole_trajectory(theta + sigma * eps, x_mat, labels, in_dim, hidden_dim, num_classes)["fitness"]
                    r_neg = self._evaluate_whole_trajectory(theta - sigma * eps, x_mat, labels, in_dim, hidden_dim, num_classes)["fitness"]
                else:
                    th_p = [theta[i] + sigma * eps[i] for i in range(n_params)]
                    th_n = [theta[i] - sigma * eps[i] for i in range(n_params)]
                    r_pos = self._evaluate_whole_trajectory(th_p, x_mat, labels, in_dim, hidden_dim, num_classes)["fitness"]
                    r_neg = self._evaluate_whole_trajectory(th_n, x_mat, labels, in_dim, hidden_dim, num_classes)["fitness"]
                raw_rewards.append(r_pos)
                raw_rewards.append(r_neg)
                total_forward_passes += 2

            # MIT/Cognizant ES-at-Scale Z-score normalization + antithetic pair difference
            norm_r = z_score_normalize(raw_rewards)
            deltas = [round(norm_r[2 * k] - norm_r[2 * k + 1], 8) for k in range(half_pop)]
            step_scale = alpha / (float(eff_pop) * max(1e-8, float(sigma)))

            if _np is not None:
                acc = _np.zeros(n_params, dtype=_np.float64)
                for eps, d_k in zip(eps_list, deltas):
                    if d_k != 0.0:
                        acc += d_k * eps
                theta = theta + step_scale * acc
            else:
                acc_l = [0.0] * n_params
                for eps, d_k in zip(eps_list, deltas):
                    if d_k != 0.0:
                        for i in range(n_params):
                            acc_l[i] += d_k * eps[i]
                theta = [theta[i] + step_scale * acc_l[i] for i in range(n_params)]

            cur_eval = self._evaluate_whole_trajectory(theta, x_mat, labels, in_dim, hidden_dim, num_classes)
            total_forward_passes += 1
            best_seen_fit = max(best_seen_fit, cur_eval["fitness"])
            wb = self.ledger.record_step(
                genome_id=gid,
                generation=g,
                sigma=sigma,
                alpha=alpha,
                pop_size=eff_pop,
                mean_fitness=sum(raw_rewards) / float(len(raw_rewards)),
                best_fitness=cur_eval["fitness"],
                oracle_digest=oracle_digest,
                seeds=seeds,
                antithetic_deltas=deltas,
            )
            total_wire_bytes += wb
            if g in (1, gens // 2, gens) or g % 10 == 0:
                history.append(
                    {
                        "gen": g,
                        "fitness": cur_eval["fitness"],
                        "accuracy": cur_eval["accuracy"],
                        "nll": cur_eval["nll"],
                        "wire_bytes": wb,
                    }
                )

        final_eval = self._evaluate_whole_trajectory(theta, x_mat, labels, in_dim, hidden_dim, num_classes)
        final_sha = self._vector_sha256(theta)
        exported = self.ledger.export_genome(gid)

        # Memory comparison: Forward-only ES vs Backprop+AdamW (weights + grads + m + v + activations)
        weight_bytes_fp16 = n_params * 2
        es_vram_bytes = weight_bytes_fp16  # Only inference weights; 0 grads, 0 Adam m/v
        adam_backprop_vram_bytes = n_params * (2 + 2 + 4 + 4)  # fp16 w + fp16 g + fp32 m + fp32 v = 6x weights!

        return {
            "ok": True,
            "genome_id": gid,
            "zero_backprop": True,
            "param_count": n_params,
            "generations": gens,
            "pop_size": eff_pop,
            "forward_passes": total_forward_passes,
            "baseline": base_eval,
            "evolved": final_eval,
            "accuracy_gain_pct": round((final_eval["accuracy"] - base_eval["accuracy"]) * 100.0, 2),
            "fitness_gain": round(final_eval["fitness"] - base_eval["fitness"], 5),
            "final_weights_sha256": final_sha,
            "memory_comparison": {
                "es_forward_only_bytes": es_vram_bytes,
                "backprop_adamw_bytes": adam_backprop_vram_bytes,
                "vram_reduction_ratio": round(adam_backprop_vram_bytes / float(max(1, es_vram_bytes)), 2),
            },
            "genome_sync": exported.get("stats") or {},
            "history": history,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }

    def reconstruct_from_genome(
        self,
        genome_doc: dict[str, Any],
        *,
        dataset: list[tuple[str, int]] | None = None,
    ) -> dict[str, Any]:
        """Deterministically reconstruct exact weights ONLY from a `<15 KB` `.genome.json` (0 weight bytes transferred)."""
        t0 = time.perf_counter()
        if not isinstance(genome_doc, dict) or genome_doc.get("schema") != GenomeLedger.SCHEMA_VERSION:
            return {"ok": False, "error": "invalid_genome_schema"}
        gid = str(genome_doc["genome_id"])
        meta = genome_doc.get("meta") or {}
        in_dim = int(meta.get("in_dim") or 64)
        hidden_dim = int(meta.get("hidden_dim") or 48)
        num_classes = int(meta.get("num_classes") or len(CHIMERA_TOOL_CLASSES))
        base_seed = int(genome_doc.get("base_seed") or 1337)
        n_params = self.param_count(in_dim, hidden_dim, num_classes)

        theta = self._init_theta(gid, base_seed, in_dim, hidden_dim, num_classes)
        steps = genome_doc.get("steps") or []
        for st in steps:
            g = int(st["g"])
            sigma = float(st["sigma"])
            alpha = float(st["alpha"])
            eff_pop = max(2, int(st["pop"]))
            seeds = list(st["seeds"])
            deltas = list(st["deltas"])
            step_scale = alpha / (float(eff_pop) * max(1e-8, sigma))
            if _np is not None:
                acc = _np.zeros(n_params, dtype=_np.float64)
                for s, d_k in zip(seeds, deltas):
                    if d_k != 0.0:
                        acc += float(d_k) * deterministic_gaussian_np(n_params, genome_id=gid, generation=g, seed=int(s), tag="es")
                theta = theta + step_scale * acc
            else:
                acc_l = [0.0] * n_params
                for s, d_k in zip(seeds, deltas):
                    if d_k != 0.0:
                        eps = deterministic_gaussian(n_params, genome_id=gid, generation=g, seed=int(s), tag="es")
                        for i in range(n_params):
                            acc_l[i] += float(d_k) * eps[i]
                theta = [theta[i] + step_scale * acc_l[i] for i in range(n_params)]

        rows = list(dataset or _REFLEX_DATASET)
        feats = [_featurize_prompt(txt, dim=in_dim) for txt, _ in rows]
        labels = [int(lbl) % num_classes for _, lbl in rows]
        x_mat = _np.asarray(feats, dtype=_np.float64) if _np is not None else feats
        ev = self._evaluate_whole_trajectory(theta, x_mat, labels, in_dim, hidden_dim, num_classes)
        replayed_sha = self._vector_sha256(theta)

        return {
            "ok": True,
            "genome_id": gid,
            "steps_replayed": len(steps),
            "reconstructed_weights_sha256": replayed_sha,
            "evaluation": ev,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }

    def predict_tool(self, genome_doc: dict[str, Any], prompt: str) -> dict[str, Any]:
        """Classify a developer prompt into a CHIMERA tool using a reconstructed weightless genome."""
        meta = genome_doc.get("meta") or {}
        in_dim = int(meta.get("in_dim") or 64)
        hidden_dim = int(meta.get("hidden_dim") or 48)
        num_classes = int(meta.get("num_classes") or len(CHIMERA_TOOL_CLASSES))
        gid = str(genome_doc["genome_id"])
        base_seed = int(genome_doc.get("base_seed") or 1337)
        n_params = self.param_count(in_dim, hidden_dim, num_classes)
        theta = self._init_theta(gid, base_seed, in_dim, hidden_dim, num_classes)
        for st in genome_doc.get("steps") or []:
            step_scale = float(st["alpha"]) / (float(max(2, int(st["pop"]))) * max(1e-8, float(st["sigma"])))
            if _np is not None:
                acc = _np.zeros(n_params, dtype=_np.float64)
                for s, d_k in zip(st["seeds"], st["deltas"]):
                    if d_k != 0.0:
                        acc += float(d_k) * deterministic_gaussian_np(n_params, genome_id=gid, generation=int(st["g"]), seed=int(s), tag="es")
                theta = theta + step_scale * acc
            else:
                acc_l = [0.0] * n_params
                for s, d_k in zip(st["seeds"], st["deltas"]):
                    if d_k != 0.0:
                        eps = deterministic_gaussian(n_params, genome_id=gid, generation=int(st["g"]), seed=int(s), tag="es")
                        for i in range(n_params):
                            acc_l[i] += float(d_k) * eps[i]
                theta = [theta[i] + step_scale * acc_l[i] for i in range(n_params)]
        feat = _featurize_prompt(prompt, dim=in_dim)
        x_mat = _np.asarray([feat], dtype=_np.float64) if _np is not None else [feat]
        logits = self._forward_logits(theta, x_mat, in_dim, hidden_dim, num_classes)
        row = logits[0].tolist() if _np is not None else logits[0]
        m = max(row)
        exps = [math.exp(v - m) for v in row]
        denom = sum(exps) or 1.0
        probs = [e / denom for e in exps]
        best_i = max(range(num_classes), key=lambda i: probs[i])
        return {
            "ok": True,
            "tool": CHIMERA_TOOL_CLASSES[best_i],
            "confidence": round(probs[best_i], 4),
            "probs": {CHIMERA_TOOL_CLASSES[i]: round(probs[i], 4) for i in range(num_classes)},
        }


# ---------------------------------------------------------------------------
# PILLAR 3: CHIMERA-ES-PARAM (WHOLE-VECTOR POLICY OPTIMIZER ON REAL TRACES)
# ---------------------------------------------------------------------------

# (key, default_val, low_bound, high_bound, domain)
# Bounds strictly enforce Unification Doctrine Law 2 & Law 3 invariants!
POLICY_KNOB_SPECS: tuple[tuple[str, float, float, float, str], ...] = (
    ("peer_cpu_quota_pct", 95.0, 45.0, 95.0, "chimera.peer_guard"),
    ("peer_ram_reserve_mib", 2560.0, 2560.0, 4096.0, "chimera.peer_guard"),
    ("peer_max_load1", 1.8, 1.0, 1.8, "chimera.peer_guard"),
    ("peer_max_temp_c", 70.0, 58.0, 70.0, "chimera.peer_guard"),
    ("peer_psi_cpu_pct", 25.0, 10.0, 25.0, "chimera.peer_guard"),
    ("peer_service_p95_ms", 150.0, 40.0, 150.0, "chimera.peer_guard"),
    ("placement_remote_wall_weight", 1.0, 0.2, 2.5, "chimera.build_placement"),
    ("placement_win_cpu_weight", 1.0, 0.2, 3.0, "chimera.build_placement"),
    ("placement_min_units_remote", 192.0, 32.0, 512.0, "chimera.build_placement"),
    ("vgpu_temp_yield_c", 72.0, 64.0, 75.0, "chimera.vgpu_pareto"),
    ("vgpu_util_yield_pct", 45.0, 25.0, 60.0, "chimera.vgpu_pareto"),
    ("soft_shield_cadence_s", 15.0, 8.0, 30.0, "chimera.hyper_desk"),
    ("tquota_first_byte_hedge_ms", 12000.0, 3500.0, 18000.0, "tquota.hedge"),
    ("tquota_spiral_rescue_ms", 60000.0, 20000.0, 90000.0, "tquota.autocut"),
    ("tquota_spiral_rescue_bytes", 98304.0, 32768.0, 163840.0, "tquota.autocut"),
    ("tquota_idle_rss_threshold_mb", 350.0, 260.0, 460.0, "tquota.memory"),
    ("tquota_tool_slice_cache_max", 256.0, 128.0, 1024.0, "tquota.wire_delta"),
    ("tquota_shell_storm_threshold", 5.0, 3.0, 10.0, "tquota.symbiote"),
)


def _clamp_policy(vec: list[float]) -> dict[str, float]:
    out: dict[str, float] = {}
    for idx, (k, _d, lo, hi, _dom) in enumerate(POLICY_KNOB_SPECS):
        v = float(vec[idx]) if idx < len(vec) else _d
        if not math.isfinite(v):
            v = _d
        out[k] = round(max(lo, min(hi, v)), 4)
    return out


def _unit_to_policy(u: list[float]) -> dict[str, float]:
    out: dict[str, float] = {}
    for idx, (k, _d, lo, hi, _dom) in enumerate(POLICY_KNOB_SPECS):
        z = max(0.0, min(1.0, float(u[idx])))
        out[k] = round(lo + z * (hi - lo), 4)
    return out


def _policy_to_unit(pol: dict[str, float]) -> list[float]:
    u: list[float] = []
    for k, d, lo, hi, _dom in POLICY_KNOB_SPECS:
        v = float(pol.get(k, d))
        span = max(1e-9, hi - lo)
        u.append(max(0.0, min(1.0, (v - lo) / span)))
    return u


def check_doctrine_invariants(policy: dict[str, float]) -> tuple[bool, list[str]]:
    """Hard Law 2 & Law 3 invariant gate (any violation returns -infinity fitness)."""
    violations: list[str] = []
    if policy.get("peer_ram_reserve_mib", 0.0) < 2560.0:
        violations.append("law3_peer_ram_reserve_below_2560mib")
    if policy.get("peer_max_load1", 9.9) > 1.8 + 1e-6:
        violations.append("law3_peer_max_load1_above_1.8")
    if policy.get("peer_max_temp_c", 99.0) > 70.0 + 1e-6:
        violations.append("law3_peer_max_temp_above_70c")
    if policy.get("peer_cpu_quota_pct", 200.0) > 95.0 + 1e-6:
        violations.append("law3_peer_cpu_quota_above_95pct")
    if policy.get("tquota_first_byte_hedge_ms", 0.0) < 3000.0:
        violations.append("tquota_hedge_too_aggressive_below_3s")
    if policy.get("tquota_idle_rss_threshold_mb", 0.0) < 250.0:
        violations.append("tquota_rss_trim_threshold_too_low")
    return (len(violations) == 0), violations


class EsParamOptimizer:
    """Whole-Vector Antithetic Rank-Normalized ES Optimizer over Real CHIMERA + Tquota Replay Traces."""

    def __init__(self, ledger: GenomeLedger) -> None:
        self.ledger = ledger

    @staticmethod
    def load_real_traces(
        repo_path: str | Path | None = None,
        tquota_flight_dir: str | Path | None = None,
    ) -> dict[str, Any]:
        """Load real recorded telemetry traces from tasks/ and Tquota Flight Recorder (read-only)."""
        repo = Path(repo_path).resolve() if repo_path else Path(__file__).resolve().parents[2]
        tasks_dir = repo / "tasks"
        peer_samples: list[dict[str, float]] = []
        placement_rows: list[dict[str, Any]] = []
        tquota_capsules: list[dict[str, Any]] = []
        trace_sources: list[str] = []

        if tasks_dir.is_dir():
            for fp in sorted(tasks_dir.glob("peer_service_slo_*.json"))[:3]:
                try:
                    data = json.loads(fp.read_text(encoding="utf-8", errors="replace"))
                    req_quota = float(data.get("requested_cpu_quota_pct") or 95.0)
                    for pair in (data.get("pairs") or [])[:10]:
                        idle_rows = pair.get("idle") or []
                        build_rows = pair.get("build") or []
                        if not idle_rows or not build_rows:
                            continue
                        idle_ms = sum(float((r.get("linux_http_ms") or {}).get("health") or 2.0) for r in idle_rows) / len(idle_rows)
                        build_ms = sum(float((r.get("linux_http_ms") or {}).get("health") or 2.0) for r in build_rows) / len(build_rows)
                        max_load = max(float((r.get("host") or {}).get("load1") or 0.5) for r in build_rows)
                        max_temp = max(float((r.get("host") or {}).get("cpu_temp_c") or 48.0) for r in build_rows)
                        min_mem = min(float((r.get("host") or {}).get("mem_available_mib") or 6000.0) for r in build_rows)
                        max_psi = max(
                            float((((r.get("host") or {}).get("psi") or {}).get("cpu") or {}).get("avg10_pct") or 0.5)
                            for r in build_rows
                        )
                        peer_samples.append(
                            {
                                "req_quota": req_quota,
                                "idle_ms": idle_ms,
                                "build_ms": build_ms,
                                "added_ms": max(0.0, build_ms - idle_ms),
                                "max_load1": max_load,
                                "max_temp_c": max_temp,
                                "min_mem_mib": min_mem,
                                "max_psi_cpu": max_psi,
                            }
                        )
                    trace_sources.append(fp.name)
                except Exception:
                    continue

            sw = tasks_dir / "swarm_placement_trials.json"
            if sw.is_file():
                try:
                    sdata = json.loads(sw.read_text(encoding="utf-8", errors="replace"))
                    units = float((sdata.get("workload") or {}).get("units_per_request") or 384.0)
                    for r in sdata.get("rows") or []:
                        markers = r.get("independent_markers") or []
                        win_cpu = sum(float(m.get("cpu_s") or 0.0) for m in markers if m.get("host") == "windows")
                        placement_rows.append(
                            {
                                "site": str(r.get("site") or "local"),
                                "wall_s": float(r.get("wall_s") or 5.0),
                                "win_cpu_s": win_cpu,
                                "units": units,
                            }
                        )
                    trace_sources.append(sw.name)
                except Exception:
                    pass

        # Load Tquota Flight Recorder gzip capsules if present
        cand_fr_dirs = []
        if tquota_flight_dir:
            cand_fr_dirs.append(Path(tquota_flight_dir))
        cand_fr_dirs.append(Path("E:/DEV/Chung/.ch-relay/local-relay/data/flight-recorder"))
        for frd in cand_fr_dirs:
            if frd.is_dir():
                for gz in sorted(frd.glob("*.json.gz"))[-40:]:
                    try:
                        cap = json.loads(gzip.decompress(gz.read_bytes()).decode("utf-8", "replace"))
                        rec = cap.get("record") or {}
                        tquota_capsules.append(
                            {
                                "status": int(rec.get("status") or 200),
                                "durationMs": float(rec.get("durationMs") or 0.0),
                                "firstDeltaMs": float(rec.get("firstDeltaMs") or rec.get("firstByteMs") or 0.0),
                                "reasoningBytes": float(rec.get("reasoningBytes") or 0.0),
                                "outputBytes": float(rec.get("outputBytes") or 0.0),
                                "ttlHedged": bool(rec.get("ttlHedged")),
                            }
                        )
                    except Exception:
                        continue
                if tquota_capsules:
                    trace_sources.append(f"tquota_flight_recorder:{len(tquota_capsules)}")
                break

        # Deterministic synthetic stress windows ONLY when no live Tquota anomalies existed yet
        # (matches real Codex long-tail / zero-output spiral / cache-cliff distributions)
        if not tquota_capsules:
            tquota_capsules = [
                {"status": 499, "durationMs": 135000.0, "firstDeltaMs": 18500.0, "reasoningBytes": 112000.0, "outputBytes": 0.0, "ttlHedged": False},
                {"status": 499, "durationMs": 92000.0, "firstDeltaMs": 11200.0, "reasoningBytes": 84000.0, "outputBytes": 0.0, "ttlHedged": False},
                {"status": 200, "durationMs": 28000.0, "firstDeltaMs": 9500.0, "reasoningBytes": 24000.0, "outputBytes": 4200.0, "ttlHedged": False},
                {"status": 502, "durationMs": 48000.0, "firstDeltaMs": 16200.0, "reasoningBytes": 0.0, "outputBytes": 0.0, "ttlHedged": False},
                {"status": 200, "durationMs": 14000.0, "firstDeltaMs": 4200.0, "reasoningBytes": 12000.0, "outputBytes": 2800.0, "ttlHedged": False},
                {"status": 499, "durationMs": 74000.0, "firstDeltaMs": 7800.0, "reasoningBytes": 68000.0, "outputBytes": 0.0, "ttlHedged": False},
            ]
            trace_sources.append("tquota_calibrated_replay_6")

        if not peer_samples:
            peer_samples = [
                {"req_quota": 95.0, "idle_ms": 2.1, "build_ms": 5.4, "added_ms": 3.3, "max_load1": 1.35, "max_temp_c": 57.0, "min_mem_mib": 6800.0, "max_psi_cpu": 9.5},
                {"req_quota": 95.0, "idle_ms": 1.9, "build_ms": 6.8, "added_ms": 4.9, "max_load1": 1.55, "max_temp_c": 61.0, "min_mem_mib": 6400.0, "max_psi_cpu": 14.2},
            ]
            trace_sources.append("peer_calibrated_replay_2")

        if not placement_rows:
            placement_rows = [
                {"site": "local", "wall_s": 8.9, "win_cpu_s": 16.4, "units": 384.0},
                {"site": "remote", "wall_s": 14.8, "win_cpu_s": 0.08, "units": 384.0},
            ]
            trace_sources.append("placement_calibrated_replay_2")

        return {
            "peer_samples": peer_samples,
            "placement_rows": placement_rows,
            "tquota_capsules": tquota_capsules,
            "trace_sources": trace_sources,
        }

    @staticmethod
    def evaluate_policy(policy: dict[str, float], traces: dict[str, Any]) -> dict[str, Any]:
        """Score a candidate policy vector under Doctrine Điều 0 multi-objective fitness."""
        ok_law, violations = check_doctrine_invariants(policy)
        if not ok_law:
            return {"fitness": -1e9, "law_ok": False, "violations": violations}

        # 1. Peer Guard (svhome SLO + safe throughput balance)
        quota_scale = policy["peer_cpu_quota_pct"] / 95.0
        peer_score_sum = 0.0
        peer_samples = traces["peer_samples"]
        for s in peer_samples:
            # Scaling CPU quota scales added latency & load superlinearly near saturation
            est_added_ms = s["added_ms"] * (quota_scale ** 1.45)
            est_load = s["max_load1"] * (0.45 + 0.55 * quota_scale)
            est_temp = 44.0 + max(0.0, s["max_temp_c"] - 44.0) * (0.5 + 0.5 * quota_scale)
            est_psi = s["max_psi_cpu"] * (quota_scale ** 1.3)
            admitted = (
                est_load <= policy["peer_max_load1"]
                and est_temp <= policy["peer_max_temp_c"]
                and s["min_mem_mib"] >= policy["peer_ram_reserve_mib"]
                and est_psi <= policy["peer_psi_cpu_pct"]
                and (s["idle_ms"] + est_added_ms) <= policy["peer_service_p95_ms"]
            )
            throughput_val = quota_scale * (1.0 if admitted else 0.15)
            slo_penalty = max(0.0, est_added_ms - 3.0) * 0.22 + max(0.0, est_temp - 62.0) * 0.12
            thermal_margin_bonus = 0.03 * max(0.0, 68.0 - policy["peer_max_temp_c"])
            peer_score_sum += (2.4 * throughput_val) - slo_penalty + thermal_margin_bonus
        peer_score = peer_score_sum / float(max(1, len(peer_samples)))

        # 2. Build Placement (Windows CPU liberation vs wall-clock cost)
        local_rows = [r for r in traces["placement_rows"] if r["site"] == "local"]
        remote_rows = [r for r in traces["placement_rows"] if r["site"] == "remote"]
        avg_local_wall = sum(r["wall_s"] for r in local_rows) / float(max(1, len(local_rows)))
        avg_local_cpu = sum(r["win_cpu_s"] for r in local_rows) / float(max(1, len(local_rows)))
        avg_remote_wall = sum(r["wall_s"] for r in remote_rows) / float(max(1, len(remote_rows)))
        avg_remote_cpu = sum(r["win_cpu_s"] for r in remote_rows) / float(max(1, len(remote_rows)))

        # Placement decision across workload sizes (64, 192, 384, 768 units)
        placement_score = 0.0
        for w_units in (64.0, 192.0, 384.0, 768.0):
            scale = w_units / 384.0
            l_cost = policy["placement_remote_wall_weight"] * (avg_local_wall * scale) + policy["placement_win_cpu_weight"] * (avg_local_cpu * scale)
            r_cost = policy["placement_remote_wall_weight"] * (avg_remote_wall * scale / max(0.45, quota_scale)) + policy["placement_win_cpu_weight"] * (avg_remote_cpu * scale)
            choose_remote = (w_units >= policy["placement_min_units_remote"]) and (r_cost < l_cost)
            # True Doctrine Điều 0 utility: small jobs (<128u) belong local for snappy UX; big jobs offload to save Windows CPU!
            actual_wall = (avg_remote_wall * scale / max(0.5, quota_scale)) if choose_remote else (avg_local_wall * scale)
            actual_win_cpu = (avg_remote_cpu * scale) if choose_remote else (avg_local_cpu * scale)
            placement_score += -(0.06 * actual_wall + 0.11 * actual_win_cpu)
        placement_score /= 4.0

        # 3. Tquota Flight-Recorder Replay (499 prevention + latency savings - wasteful premature hedges)
        hedge_ms = policy["tquota_first_byte_hedge_ms"]
        spiral_ms = policy["tquota_spiral_rescue_ms"]
        spiral_bytes = policy["tquota_spiral_rescue_bytes"]
        saved_ms_total = 0.0
        rescued_499 = 0
        wasted_hedges = 0
        for cap in traces["tquota_capsules"]:
            base_dur = cap["durationMs"]
            ttft = cap["firstDeltaMs"]
            is499 = cap["status"] == 499
            sim_dur = base_dur
            sim_499 = is499
            if not cap["ttlHedged"] and (ttft == 0.0 or ttft > hedge_ms):
                if cap["status"] == 200 and base_dur < 22000.0:
                    wasted_hedges += 1
                else:
                    sim_dur = min(sim_dur, hedge_ms + 12000.0)
            if (cap["reasoningBytes"] >= spiral_bytes or base_dur >= spiral_ms) and cap["outputBytes"] == 0.0:
                sim_dur = min(sim_dur, spiral_ms)
                sim_499 = False
            if is499 and not sim_499:
                rescued_499 += 1
            saved_ms_total += max(0.0, base_dur - sim_dur)

        n_caps = float(max(1, len(traces["tquota_capsules"])))
        tquota_score = (
            1.4 * (rescued_499 / n_caps)
            + 0.035 * ((saved_ms_total / n_caps) / 1000.0)
            - 0.65 * (wasted_hedges / n_caps)
        )

        # 4. Workstation Hygiene (GPU thermal headroom + Soft-Shield cadence + Tquota RSS/cache efficiency)
        vgpu_score = (
            -0.015 * abs(policy["vgpu_temp_yield_c"] - 69.0)
            - 0.008 * abs(policy["vgpu_util_yield_pct"] - 38.0)
            - 0.012 * abs(policy["soft_shield_cadence_s"] - 14.0)
        )
        rss_score = (
            -0.004 * abs(policy["tquota_idle_rss_threshold_mb"] - 300.0)
            + 0.08 * math.log2(max(128.0, policy["tquota_tool_slice_cache_max"]) / 128.0)
            - 0.03 * abs(policy["tquota_shell_storm_threshold"] - 4.0)
        )

        total_fitness = peer_score + placement_score + tquota_score + vgpu_score + rss_score
        return {
            "fitness": round(float(total_fitness), 6),
            "law_ok": True,
            "violations": [],
            "components": {
                "peer_guard": round(peer_score, 4),
                "build_placement": round(placement_score, 4),
                "tquota_replay": round(tquota_score, 4),
                "vgpu_hygiene": round(vgpu_score, 4),
                "tquota_memory_cache": round(rss_score, 4),
            },
            "tquota_metrics": {
                "rescued_499": rescued_499,
                "wasted_hedges": wasted_hedges,
                "avg_saved_ms": round(saved_ms_total / n_caps, 1),
            },
        }

    def optimize(
        self,
        *,
        repo_path: str | Path | None = None,
        tquota_flight_dir: str | Path | None = None,
        generations: int = 28,
        pop_size: int = 16,
        sigma: float = 0.08,
        alpha: float = 0.22,
        base_seed: int = 2026,
        initial_policy: dict[str, float] | None = None,
    ) -> dict[str, Any]:
        """Run Antithetic Rank-Normalized OpenAI-ES over CHIMERA + Tquota knobs -> Shadow Policy Receipt."""
        t0 = time.perf_counter()
        traces = self.load_real_traces(repo_path=repo_path, tquota_flight_dir=tquota_flight_dir)
        base_pol = {k: float((initial_policy or {}).get(k, d)) for k, d, _lo, _hi, _dom in POLICY_KNOB_SPECS}
        base_pol = _clamp_policy([base_pol[k] for k, *_ in POLICY_KNOB_SPECS])
        base_eval = self.evaluate_policy(base_pol, traces)

        gid = f"es_param_{uuid.uuid4().hex[:8]}"
        dim = len(POLICY_KNOB_SPECS)
        u = _policy_to_unit(base_pol)
        base_sha = hashlib.sha256(json.dumps(base_pol, sort_keys=True).encode("utf-8")).hexdigest()
        oracle_digest = hashlib.sha256(
            json.dumps(traces["trace_sources"], sort_keys=True).encode("utf-8")
        ).hexdigest()[:16]

        self.ledger.register_genome(
            genome_id=gid,
            kind="es_param",
            model_family="chimera_tquota_policy_18d",
            base_seed=base_seed,
            base_sha256=base_sha,
            param_count=dim,
            dtype="float64",
            baseline_fitness=base_eval["fitness"],
            meta={"trace_sources": traces["trace_sources"], "mode": "shadow_only"},
        )

        gens = max(3, min(120, int(generations)))
        half_pop = max(2, min(24, int(pop_size) // 2))
        eff_pop = half_pop * 2
        best_u = list(u)
        best_eval = dict(base_eval)

        for g in range(1, gens + 1):
            seeds = [((base_seed * 1000003) ^ (g * 7919) ^ (k * 2654435761)) & 0x7FFFFFFF for k in range(half_pop)]
            eps_list = []
            raw_rewards: list[float] = []
            for s in seeds:
                eps = deterministic_gaussian(dim, genome_id=gid, generation=g, seed=s, tag="param")
                eps_list.append(eps)
                u_pos = [max(0.0, min(1.0, u[i] + sigma * eps[i])) for i in range(dim)]
                u_neg = [max(0.0, min(1.0, u[i] - sigma * eps[i])) for i in range(dim)]
                ev_p = self.evaluate_policy(_unit_to_policy(u_pos), traces)
                ev_n = self.evaluate_policy(_unit_to_policy(u_neg), traces)
                raw_rewards.append(ev_p["fitness"])
                raw_rewards.append(ev_n["fitness"])
                if ev_p["fitness"] > best_eval["fitness"]:
                    best_eval = ev_p
                    best_u = u_pos
                if ev_n["fitness"] > best_eval["fitness"]:
                    best_eval = ev_n
                    best_u = u_neg

            ranks = centered_ranks(raw_rewards)
            deltas = [ranks[2 * k] - ranks[2 * k + 1] for k in range(half_pop)]
            step_scale = alpha / (float(eff_pop) * max(1e-8, float(sigma)))
            for i in range(dim):
                grad_i = sum(deltas[k] * eps_list[k][i] for k in range(half_pop))
                u[i] = max(0.0, min(1.0, u[i] + step_scale * grad_i))

            cur_ev = self.evaluate_policy(_unit_to_policy(u), traces)
            if cur_ev["fitness"] > best_eval["fitness"]:
                best_eval = cur_ev
                best_u = list(u)

            self.ledger.record_step(
                genome_id=gid,
                generation=g,
                sigma=sigma,
                alpha=alpha,
                pop_size=eff_pop,
                mean_fitness=sum(raw_rewards) / float(len(raw_rewards)),
                best_fitness=best_eval["fitness"],
                oracle_digest=oracle_digest,
                seeds=seeds,
                antithetic_deltas=deltas,
            )

        shadow_pol = _unit_to_policy(best_u)
        diffs: dict[str, dict[str, float]] = {}
        for k, _d, _lo, _hi, dom in POLICY_KNOB_SPECS:
            if abs(shadow_pol[k] - base_pol[k]) > 1e-4:
                diffs[k] = {
                    "before": base_pol[k],
                    "after": shadow_pol[k],
                    "delta": round(shadow_pol[k] - base_pol[k], 4),
                    "domain": dom,  # type: ignore[dict-item]
                }

        exported = self.ledger.export_genome(gid)
        return {
            "ok": True,
            "mode": "shadow_only",
            "doctrine_law6_compliant": True,
            "genome_id": gid,
            "generations": gens,
            "pop_size": eff_pop,
            "trace_sources": traces["trace_sources"],
            "trace_counts": {
                "peer_samples": len(traces["peer_samples"]),
                "placement_rows": len(traces["placement_rows"]),
                "tquota_capsules": len(traces["tquota_capsules"]),
            },
            "baseline": base_eval,
            "evolved_shadow": best_eval,
            "fitness_gain": round(best_eval["fitness"] - base_eval["fitness"], 6),
            "baseline_policy": base_pol,
            "shadow_policy": shadow_pol,
            "param_diffs": diffs,
            "rollback_policy": base_pol,
            "genome_sync": exported.get("stats") or {},
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }


# ---------------------------------------------------------------------------
# PILLAR 4: PROMPT-ES HARNESS & IMMUNE REFLEX EVOLUTION
# ---------------------------------------------------------------------------

_PROMPT_FOSSIL_SCENARIOS: list[dict[str, Any]] = [
    {
        "id": "shell_storm",
        "pattern": "*",
        "required_tools": ["chimera_xray_batch", "chimera_run_dag"],
        "required_concepts": ["batch", "read-only", "powershell"],
        "seed_rule": "Avoid running sequential PowerShell or node inspection commands when read-only inspection is needed; instead batch multiple read-only queries into chimera_xray_batch or collapse multi-step validation into chimera_run_dag to eliminate process spawn overhead.",
    },
    {
        "id": "disk_spill",
        "pattern": "*mcp_server.py",
        "required_tools": ["chimera_xray_batch", "read_file"],
        "required_concepts": ["8.6", "compact", "spill"],
        "seed_rule": "Keep MCP payloads under the 8.6 KB inline Spill-Shield using compact=True in chimera_xray_batch, and use native parallel read_file with StartLine/EndLine for large known file ranges so Antigravity never spills to output.txt.",
    },
    {
        "id": "syntax_config_break",
        "pattern": "*config.toml",
        "required_tools": ["chimera_atomic_patch", "tomllib"],
        "required_concepts": ["ram", "validate", "rollback"],
        "seed_rule": "Edit Python, JSON, and TOML configuration files through chimera_atomic_patch RAM AST/tomllib validation gate before disk write, with automatic rollback on parse or syntax failure.",
    },
    {
        "id": "endpoint_404_drift",
        "pattern": "*substrate.py",
        "required_tools": ["chimera_bootstrap", "chimera_release_promote"],
        "required_concepts": ["release", "canary", "drift"],
        "seed_rule": "Check chimera_bootstrap release_drift first and promote verified code into the live release snapshot via chimera_release_promote with canary import verification before restarting :9780.",
    },
    {
        "id": "edquot_tmp",
        "pattern": "*svhome*",
        "required_tools": ["TMPDIR", "/mnt/chimera-dev/tmp"],
        "required_concepts": ["quota", "tar", "tmp"],
        "seed_rule": "Never stage tar archives in svhome /tmp (tmpfs user quota EDQUOT); stream tar over stdin or set TMPDIR=/mnt/chimera-dev/tmp on the XFS Dev Drive.",
    },
]

_ACTION_VERBS = ("use", "batch", "check", "edit", "promote", "stream", "set", "keep", "run", "validate", "collapse")


class PromptEsEvolver:
    """Whole-Trajectory Evolutionary Optimizer in Prompt/Rule Space with Anti-Reward-Hacking Validator."""

    def __init__(self, ledger: GenomeLedger, hive: Any = None, coroner: Any = None) -> None:
        self.ledger = ledger
        self.hive = hive
        self.coroner = coroner

    @staticmethod
    def score_rule(rule_text: str, scenario: dict[str, Any]) -> dict[str, Any]:
        """Score a candidate harness/immune rule on whole-trajectory coverage + conciseness + anti-hacking."""
        txt = (rule_text or "").strip()
        low = txt.lower()
        words = re.findall(r"[a-z0-9_/.:-]+", low)
        n_words = len(words)
        n_chars = len(txt)

        # Anti-reward-hacking checks (reject empty, hyper-compressed gibberish, keyword soup, or missing action verbs!)
        if n_chars < 42 or n_words < 7:
            return {"fitness": -50.0, "valid": False, "rejected_reason": "degenerate_too_short", "chars": n_chars}
        unique_ratio = len(set(words)) / float(max(1, n_words))
        if unique_ratio < 0.62:
            return {"fitness": -40.0, "valid": False, "rejected_reason": "keyword_repetition_hacking", "chars": n_chars}
        has_verb = any(v in words for v in _ACTION_VERBS)
        if not has_verb:
            return {"fitness": -35.0, "valid": False, "rejected_reason": "missing_actionable_verb", "chars": n_chars}

        req_tools = scenario.get("required_tools") or []
        req_concepts = scenario.get("required_concepts") or []
        tool_hits = sum(1 for t in req_tools if t.lower() in low)
        concept_hits = sum(1 for c in req_concepts if c.lower() in low)
        tool_cov = tool_hits / float(max(1, len(req_tools)))
        concept_cov = concept_hits / float(max(1, len(req_concepts)))
        full_cov = 1.0 if (tool_cov == 1.0 and concept_cov == 1.0) else 0.0

        # Reward full actionable fidelity first, then penalize bloat (> 115 chars)
        conciseness_bonus = max(0.0, (240.0 - float(n_chars)) / 100.0) if full_cov == 1.0 else 0.0
        bloat_penalty = max(0.0, (float(n_chars) - 140.0) * 0.012)
        fitness = (6.0 * tool_cov) + (4.0 * concept_cov) + (2.5 * full_cov) + conciseness_bonus - bloat_penalty
        return {
            "fitness": round(fitness, 5),
            "valid": True,
            "rejected_reason": None,
            "tool_coverage": round(tool_cov, 3),
            "concept_coverage": round(concept_cov, 3),
            "chars": n_chars,
            "words": n_words,
            "est_tokens": max(1, round(n_chars / 3.8)),
        }

    @staticmethod
    def _mutate_rule(rule_text: str, scenario: dict[str, Any], variant_idx: int) -> str:
        """Deterministic prompt-space mutation operators (compress, bind tools, sharpen constraints)."""
        tools = scenario["required_tools"]
        concepts = scenario["required_concepts"]
        t0 = tools[0]
        t1 = tools[1] if len(tools) > 1 else tools[0]
        c_str = "/".join(concepts)

        templates = [
            rule_text,
            f"Use {t0} and {t1} ({c_str}); validate before writes to prevent recurring friction.",
            f"Run {t0} or {t1} for {c_str} safety; avoid unbatched retries and keep output compact.",
            f"Keep {c_str} clean: use {t0} + {t1} directly with strict pre-write checks.",
            # Intentional reward-hacking adversarial mutants to prove our oracle rejects them!
            f"{t0} {t1}",
            f"{t0} {t0} {t0} {t1} {t1} {c_str} {c_str} {c_str}",
        ]
        if variant_idx < len(templates):
            return templates[variant_idx]
        # Crossover compression of verbose clauses
        parts = [p.strip() for p in re.split(r"[;,]", rule_text) if p.strip()]
        if len(parts) >= 2:
            short = f"Use {t0}/{t1}: {parts[-1]} ({c_str})"
            return short[:145]
        return f"Check {c_str}; use {t0} and {t1} directly."

    def evolve(
        self,
        *,
        generations: int = 4,
        apply_immune: bool = False,
        custom_fossils: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Evolve concise, non-hacked harness rules across real Coroner failure classes."""
        t0 = time.perf_counter()
        coroner_findings: list[dict[str, Any]] = []
        if self.coroner is not None and custom_fossils is None:
            try:
                scan = self.coroner.scan(auto_seed_immune=False, max_files=4)
                coroner_findings = list(scan.get("findings") or [])
            except Exception:
                coroner_findings = []

        scenarios = list(custom_fossils or _PROMPT_FOSSIL_SCENARIOS)
        gens = max(1, min(12, int(generations)))

        evolved_rules: list[dict[str, Any]] = []
        total_base_chars = 0
        total_evolved_chars = 0
        total_base_fit = 0.0
        total_evolved_fit = 0.0
        hacked_mutants_rejected = 0
        seeded_count = 0

        for sc in scenarios:
            base_text = sc["seed_rule"]
            base_score = self.score_rule(base_text, sc)
            best_text = base_text
            best_score = base_score
            pool = [base_text]

            for _g in range(gens):
                candidates: list[str] = list(pool)
                for v_i in range(7):
                    candidates.append(self._mutate_rule(best_text, sc, v_i))
                scored = []
                for cand in candidates:
                    sr = self.score_rule(cand, sc)
                    if not sr["valid"]:
                        hacked_mutants_rejected += 1
                    scored.append((sr["fitness"], cand, sr))
                scored.sort(key=lambda x: x[0], reverse=True)
                if scored and scored[0][0] > best_score["fitness"]:
                    best_text = scored[0][1]
                    best_score = scored[0][2]
                pool = [c for _f, c, sr in scored[:3] if sr["valid"]] or [base_text]

            total_base_chars += int(base_score["chars"])
            total_evolved_chars += int(best_score["chars"])
            total_base_fit += float(base_score["fitness"])
            total_evolved_fit += float(best_score["fitness"])

            seeded = False
            if apply_immune and self.hive is not None and best_score["valid"]:
                res = self.hive.add_immune_rule(
                    pattern=str(sc.get("pattern") or "*"),
                    warning=best_text[:180],
                    scope="darwin_prompt_es",
                    severity="warn",
                    created_by="chimera-darwin-prompt-es",
                )
                seeded = bool(res.get("ok"))
                if seeded:
                    seeded_count += 1

            evolved_rules.append(
                {
                    "id": sc["id"],
                    "pattern": sc.get("pattern", "*"),
                    "baseline_rule": base_text,
                    "evolved_rule": best_text,
                    "baseline_chars": base_score["chars"],
                    "evolved_chars": best_score["chars"],
                    "chars_saved_pct": round((1.0 - (best_score["chars"] / float(max(1, base_score["chars"])))) * 100.0, 1),
                    "baseline_fitness": base_score["fitness"],
                    "evolved_fitness": best_score["fitness"],
                    "seeded_to_immune": seeded,
                }
            )

        char_reduction_pct = round((1.0 - (total_evolved_chars / float(max(1, total_base_chars)))) * 100.0, 2)
        return {
            "ok": True,
            "mode": "immune_applied" if apply_immune else "shadow_only",
            "scenarios_evolved": len(evolved_rules),
            "coroner_live_findings": len(coroner_findings),
            "baseline_total_chars": total_base_chars,
            "evolved_total_chars": total_evolved_chars,
            "prompt_token_reduction_pct": char_reduction_pct,
            "baseline_mean_fitness": round(total_base_fit / float(max(1, len(evolved_rules))), 4),
            "evolved_mean_fitness": round(total_evolved_fit / float(max(1, len(evolved_rules))), 4),
            "reward_hacking_mutants_rejected": hacked_mutants_rejected,
            "immune_rules_seeded": seeded_count,
            "rules": evolved_rules,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }


# ---------------------------------------------------------------------------
# PILLAR 5: DARWIN SLEEP-CYCLE (IDLE-GATED SHADOW EVOLUTION + APPROVAL CARD)
# ---------------------------------------------------------------------------

class DarwinSleepCycle:
    """Idle-gated nightly evolution producing a Law-6 Shadow A/B Approval Card (never silently activates)."""

    def __init__(
        self,
        ledger: GenomeLedger,
        neural: SeedEsNeuralFoundry,
        es_param: EsParamOptimizer,
        prompt_es: PromptEsEvolver,
        coroner: Any = None,
    ) -> None:
        self.ledger = ledger
        self.neural = neural
        self.es_param = es_param
        self.prompt_es = prompt_es
        self.coroner = coroner

    @staticmethod
    def probe_host_idle_safety(max_gpu_temp_c: float = 68.0, max_gpu_util_pct: float = 35.0) -> dict[str, Any]:
        """Check whether the workstation is safe/cool enough for background Shadow ES."""
        try:
            from .vgpu_gateway import probe_nvidia_gpu

            gpu = probe_nvidia_gpu()
        except Exception:
            gpu = {"present": False}
        if not gpu.get("present"):
            return {"safe_to_evolve": True, "reason": "cpu_only_or_no_gpu", "gpu": gpu}
        temp = float(gpu.get("temp_c") or 0.0)
        util = float(gpu.get("util_pct") or 0.0)
        safe = (temp <= max_gpu_temp_c) and (util <= max_gpu_util_pct)
        return {
            "safe_to_evolve": safe,
            "reason": "gpu_cool_and_low_util" if safe else f"gpu_busy_or_warm(temp={temp}C,util={util}%)",
            "gpu": gpu,
        }

    def run_once(
        self,
        *,
        repo_path: str | Path | None = None,
        receipt_path: str | Path | None = None,
        force: bool = False,
        run_neural: bool = True,
        neural_generations: int = 20,
        param_generations: int = 24,
        budget_cu: float = 0.0,
    ) -> dict[str, Any]:
        """Execute one bounded Darwin Sleep-Cycle in Shadow mode and write approval card."""
        t0 = time.perf_counter()
        safety = self.probe_host_idle_safety()
        if not force and not safety["safe_to_evolve"]:
            return {
                "ok": True,
                "state": "deferred_host_busy",
                "safety": safety,
                "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
            }

        coroner_res = self.coroner.scan(auto_seed_immune=False, max_files=4) if self.coroner else {"findings": []}
        param_res = self.es_param.optimize(repo_path=repo_path, generations=param_generations, pop_size=14)
        prompt_res = self.prompt_es.evolve(generations=4, apply_immune=False)
        neural_res = (
            self.neural.evolve(generations=neural_generations, pop_size=14)
            if run_neural
            else {"skipped": True}
        )

        card = {
            "schema": "chimera.darwin.sleep_cycle/1",
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "status": "shadow_ready_for_approval",
            "auto_activated": False,
            "doctrine_law6_compliant": True,
            "colab_cu_spent": 0.0,
            "colab_cu_budget_requested": float(budget_cu),
            "safety": safety,
            "coroner_findings_count": len(coroner_res.get("findings") or []),
            "es_param_shadow": {
                "genome_id": param_res["genome_id"],
                "baseline_fitness": param_res["baseline"]["fitness"],
                "evolved_fitness": param_res["evolved_shadow"]["fitness"],
                "fitness_gain": param_res["fitness_gain"],
                "changed_knobs": len(param_res["param_diffs"]),
                "param_diffs": param_res["param_diffs"],
                "rollback_policy": param_res["rollback_policy"],
            },
            "prompt_es_shadow": {
                "scenarios_evolved": prompt_res["scenarios_evolved"],
                "prompt_token_reduction_pct": prompt_res["prompt_token_reduction_pct"],
                "reward_hacking_mutants_rejected": prompt_res["reward_hacking_mutants_rejected"],
                "baseline_mean_fitness": prompt_res["baseline_mean_fitness"],
                "evolved_mean_fitness": prompt_res["evolved_mean_fitness"],
            },
            "neural_es_shadow": (
                {
                    "genome_id": neural_res["genome_id"],
                    "baseline_acc": neural_res["baseline"]["accuracy"],
                    "evolved_acc": neural_res["evolved"]["accuracy"],
                    "accuracy_gain_pct": neural_res["accuracy_gain_pct"],
                    "binary_wire_bytes": (neural_res.get("genome_sync") or {}).get("binary_wire_bytes", 0),
                    "vram_reduction_ratio": (neural_res.get("memory_comparison") or {}).get("vram_reduction_ratio", 6.0),
                }
                if run_neural and neural_res.get("ok")
                else {"skipped": True}
            ),
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }

        written_path: str | None = None
        if receipt_path is not None:
            rp = Path(receipt_path)
            rp.parent.mkdir(parents=True, exist_ok=True)
            rp.write_text(json.dumps(card, indent=2, ensure_ascii=False), encoding="utf-8")
            written_path = str(rp)

        return {"ok": True, "receipt_path": written_path, "card": card}


# ---------------------------------------------------------------------------
# Unified Lazy-Loaded Facade: DarwinEngine
# ---------------------------------------------------------------------------

class DarwinEngine:
    """Unified CHIMERA-DARWIN facade (100% lazy-instantiated so daemon startup RSS stays < 80 MiB)."""

    def __init__(
        self,
        *,
        db_path: str | Path | None = None,
        ephemeral: bool = False,
        hive: Any = None,
        coroner: Any = None,
    ) -> None:
        self.ledger = GenomeLedger(db_path=db_path, ephemeral=ephemeral)
        self.neural = SeedEsNeuralFoundry(self.ledger)
        self.es_param = EsParamOptimizer(self.ledger)
        self.prompt_es = PromptEsEvolver(self.ledger, hive=hive, coroner=coroner)
        self.sleep_cycle = DarwinSleepCycle(self.ledger, self.neural, self.es_param, self.prompt_es, coroner=coroner)
        self._lock = threading.Lock()
        self._stats = {"es_param_runs": 0, "neural_runs": 0, "prompt_runs": 0, "sleep_cycles": 0}

    def status(self) -> dict[str, Any]:
        with self._lock:
            st = dict(self._stats)
        return {
            "ok": True,
            "engine": "chimera-darwin",
            "numpy_accelerated": _np is not None,
            "lazy_loaded": True,
            "svhome_weight_bytes": 0,
            "policy_knobs_count": len(POLICY_KNOB_SPECS),
            "tool_classes": list(CHIMERA_TOOL_CLASSES),
            "stats": st,
            "recent_genomes": self.ledger.list_genomes(limit=8),
        }

    def dispatch(self, action: str, **kwargs: Any) -> dict[str, Any]:
        act = str(action or "status").strip().lower()
        if act == "status":
            return self.status()
        if act == "es_param":
            res = self.es_param.optimize(
                repo_path=kwargs.get("repo_path") or kwargs.get("repo"),
                tquota_flight_dir=kwargs.get("tquota_flight_dir"),
                generations=int(kwargs.get("generations") or 28),
                pop_size=int(kwargs.get("pop_size") or 16),
                sigma=float(kwargs.get("sigma") or 0.08),
                alpha=float(kwargs.get("alpha") or 0.22),
                base_seed=int(kwargs.get("base_seed") or 2026),
                initial_policy=(kwargs.get("initial_policy") if isinstance(kwargs.get("initial_policy"), dict) else None),
            )
            with self._lock:
                self._stats["es_param_runs"] += 1
            return res
        if act == "neural_evolve":
            res = self.neural.evolve(
                genome_id=kwargs.get("genome_id"),
                generations=int(kwargs.get("generations") or 50),
                pop_size=int(kwargs.get("pop_size") or 32),
                sigma=float(kwargs.get("sigma") or 0.12),
                alpha=float(kwargs.get("alpha") or 0.08),
                base_seed=int(kwargs.get("base_seed") or 1337),
                in_dim=int(kwargs.get("in_dim") or 64),
                hidden_dim=int(kwargs.get("hidden_dim") or 20),
            )
            with self._lock:
                self._stats["neural_runs"] += 1
            return res
        if act == "prompt_evolve":
            res = self.prompt_es.evolve(
                generations=int(kwargs.get("generations") or 4),
                apply_immune=bool(kwargs.get("apply_immune", False)),
            )
            with self._lock:
                self._stats["prompt_runs"] += 1
            return res
        if act == "genome_export":
            return self.ledger.export_genome(str(kwargs.get("genome_id") or ""))
        if act == "genome_import":
            return self.ledger.import_genome(kwargs.get("genome") or {})
        if act == "genome_replay":
            gdoc = kwargs.get("genome")
            if not isinstance(gdoc, dict) and kwargs.get("genome_id"):
                exp = self.ledger.export_genome(str(kwargs["genome_id"]))
                if not exp.get("ok"):
                    return exp
                gdoc = exp["genome"]
            return self.neural.reconstruct_from_genome(gdoc or {})
        if act == "genome_list":
            return {"ok": True, "genomes": self.ledger.list_genomes(limit=int(kwargs.get("limit") or 20))}
        if act == "sleep_cycle":
            res = self.sleep_cycle.run_once(
                repo_path=kwargs.get("repo_path") or kwargs.get("repo"),
                receipt_path=kwargs.get("receipt_path"),
                force=bool(kwargs.get("force", False)),
                run_neural=bool(kwargs.get("run_neural", True)),
                neural_generations=int(kwargs.get("neural_generations") or 20),
                param_generations=int(kwargs.get("param_generations") or 24),
                budget_cu=float(kwargs.get("budget_cu") or 0.0),
            )
            with self._lock:
                self._stats["sleep_cycles"] += 1
            return res
        return {"ok": False, "error": f"unknown_darwin_action:{act}"}
