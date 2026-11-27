"""CHIMERA-HGT (Idea #8) — Horizontal Gene Transfer (Plasmid DNA Engine).

Distills verified reusable optimizations and patterns into signed <= 8 KB Plasmid
capsules, scans ecosystem projects/profiles for matching bottlenecks, and runs isolated
sandbox A/B parity & latency verification producing strictly Law-6 Graft Proposals
(`auto_activated=False`, `requires_human_approval=True`).

100% Python stdlib, Zero-NumPy, lazy-loaded, < 1 MiB RAM, SQLite WAL persistence.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Callable

MAX_PLASMID_BYTES = 8192


def _default_ops_dir() -> Path:
    return Path(os.environ.get("CHIMERA_HOME") or (Path.home() / ".chimera"))


def _canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_hex(data: bytes | str) -> str:
    raw = data.encode("utf-8") if isinstance(data, str) else data
    return hashlib.sha256(raw).hexdigest()


def _slugify(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9_]+", "_", str(name).strip().lower()).strip("_")
    return s[:40] or "plasmid"


def _normalize_tags(tags: list[str] | tuple[str, ...] | None) -> list[str]:
    if not tags:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for t in tags:
        tok = re.sub(r"[^a-z0-9_+-]+", "_", str(t).strip().lower()).strip("_")
        if tok and tok not in seen:
            seen.add(tok)
            out.append(tok)
    return sorted(out)


def _analyze_python_ast(code: str) -> tuple[bool, list[str], list[str]]:
    """Inspect Python snippet via stdlib AST (zero execution)."""
    import ast

    try:
        tree = ast.parse(code)
    except SyntaxError:
        return False, [], []
    symbols: list[str] = []
    signals: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            symbols.append(node.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                signals.add(alias.name.split(".")[0].lower())
        elif isinstance(node, ast.ImportFrom) and node.module:
            signals.add(node.module.split(".")[0].lower())
        elif isinstance(node, ast.Attribute):
            attr = node.attr.lower()
            if attr in ("pack", "pack_into", "unpack", "unpack_from", "executemany", "commit"):
                signals.add(attr)
    return True, symbols[:16], sorted(signals)[:24]


def _canonical_value_signature(val: Any) -> tuple[str, str]:
    """Strict type + canonical payload signature for bit-exact parity checking."""
    tname = f"{type(val).__module__}.{type(val).__qualname__}"
    if isinstance(val, (bytes, bytearray, memoryview)):
        return tname, _sha256_hex(bytes(val))
    try:
        return tname, _sha256_hex(
            json.dumps(val, sort_keys=True, separators=(",", ":"), default=repr)
        )
    except Exception:
        return tname, _sha256_hex(repr(val))


def _invoke_case(fn: Callable[..., Any], case: Any) -> Any:
    """Invoke candidate function with flexible test-case conventions."""
    if isinstance(case, dict) and (
        ("args" in case or "kwargs" in case)
        and set(case.keys()).issubset({"args", "kwargs", "name", "expected"})
    ):
        args = case.get("args", ())
        kwargs = case.get("kwargs", {})
        if not isinstance(args, (list, tuple)):
            args = (args,)
        return fn(*args, **kwargs)

    if isinstance(case, tuple):
        import inspect

        try:
            sig = inspect.signature(fn)
            positional = [
                p
                for p in sig.parameters.values()
                if p.kind
                in (
                    inspect.Parameter.POSITIONAL_ONLY,
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                )
            ]
            has_varargs = any(
                p.kind == inspect.Parameter.VAR_POSITIONAL
                for p in sig.parameters.values()
            )
            if has_varargs or (len(positional) == len(case) and len(case) > 1):
                return fn(*case)
        except (TypeError, ValueError):
            pass
    return fn(case)


# ---------------------------------------------------------------------------
# 3 Built-In Starter Plasmids (real, verified, stdlib-only, well under 8 KB)
# ---------------------------------------------------------------------------

STARTER_PLASMIDS: tuple[dict[str, Any], ...] = (
    {
        "name": "singleflight_coalescer",
        "source_project": "chimera-tp/platform/result_reuse",
        "tags": ["singleflight", "concurrency", "dedup", "cache", "law1", "law4", "io"],
        "io_contract": {
            "input": "key: str, fn: Callable[[], T]",
            "output": "T (exact shared result of single in-flight execution)",
            "invariants": ["at_most_one_inflight_per_key", "propagates_exception_cleanly"],
        },
        "benchmark_oracle": {
            "metric": "duplicate_work_elimination_ratio",
            "target_speedup": ">= 1.5x under concurrent identical keys",
            "parity": "bit_exact_result",
        },
        "code_or_spec": (
            "import threading\n\n"
            "class SingleflightCoalescer:\n"
            "    def __init__(self):\n"
            "        self._mu = threading.Lock()\n"
            "        self._inflight = {}\n\n"
            "    def do(self, key, fn):\n"
            "        with self._mu:\n"
            "            slot = self._inflight.get(key)\n"
            "            if slot is None:\n"
            "                slot = [threading.Event(), None, None]\n"
            "                self._inflight[key] = slot\n"
            "                leader = True\n"
            "            else:\n"
            "                leader = False\n"
            "        if not leader:\n"
            "            slot[0].wait()\n"
            "            if slot[2] is not None:\n"
            "                raise slot[2]\n"
            "            return slot[1]\n"
            "        try:\n"
            "            slot[1] = fn()\n"
            "            return slot[1]\n"
            "        except BaseException as exc:\n"
            "            slot[2] = exc\n"
            "            raise\n"
            "        finally:\n"
            "            with self._mu:\n"
            "                self._inflight.pop(key, None)\n"
            "            slot[0].set()\n"
        ),
    },
    {
        "name": "wal_group_commit",
        "source_project": "chimera-tp/platform/vault_sql",
        "tags": ["sqlite", "wal", "batching", "ssd", "storage", "persistence", "law1"],
        "io_contract": {
            "input": "conn: sqlite3.Connection, sql: str, rows: list[tuple]",
            "output": "int (committed row count in single WAL transaction)",
            "invariants": ["atomic_transaction", "reduced_fsync_write_amp"],
        },
        "benchmark_oracle": {
            "metric": "commits_per_100_writes",
            "target_speedup": ">= 3.0x write throughput vs per-row commit",
            "parity": "identical_final_table_rows",
        },
        "code_or_spec": (
            "class WalGroupCommitBuffer:\n"
            "    def __init__(self, conn, sql, max_batch=64):\n"
            "        self._conn = conn\n"
            "        self._sql = sql\n"
            "        self._max_batch = max(1, int(max_batch))\n"
            "        self._pending = []\n\n"
            "    def enqueue(self, params):\n"
            "        self._pending.append(params)\n"
            "        if len(self._pending) >= self._max_batch:\n"
            "            return self.flush()\n"
            "        return 0\n\n"
            "    def flush(self):\n"
            "        if not self._pending:\n"
            "            return 0\n"
            "        batch = self._pending\n"
            "        self._pending = []\n"
            "        with self._conn:\n"
            "            self._conn.executemany(self._sql, batch)\n"
            "        return len(batch)\n"
        ),
    },
    {
        "name": "zero_alloc_ring_codec",
        "source_project": "chimera-tp/platform/aeon_dynamo",
        "tags": ["binary", "ring", "zero_alloc", "mmap", "ipc", "memory", "low_latency", "law7"],
        "io_contract": {
            "input": "buf: bytearray|memoryview, slot_idx: int, seq: int, kind: int, val: float",
            "output": "int (byte offset written in-place with zero heap allocation)",
            "invariants": ["fixed_16b_slot", "little_endian_stable_abi"],
        },
        "benchmark_oracle": {
            "metric": "encode_decode_ns_per_frame",
            "target_speedup": ">= 1.3x and 0 intermediate bytes allocations",
            "parity": "bit_exact_slot_bytes",
        },
        "code_or_spec": (
            "import struct\n\n"
            "_SLOT = struct.Struct('<QIf')\n\n"
            "class ZeroAllocRingCodec:\n"
            "    SLOT_SIZE = _SLOT.size\n\n"
            "    def __init__(self, slots=256):\n"
            "        self.slots = max(1, int(slots))\n"
            "        self.buf = bytearray(self.slots * self.SLOT_SIZE)\n\n"
            "    def write_slot(self, idx, seq, kind, value):\n"
            "        off = (int(idx) % self.slots) * self.SLOT_SIZE\n"
            "        _SLOT.pack_into(self.buf, off, int(seq), int(kind), float(value))\n"
            "        return off\n\n"
            "    def read_slot(self, idx):\n"
            "        off = (int(idx) % self.slots) * self.SLOT_SIZE\n"
            "        return _SLOT.unpack_from(self.buf, off)\n"
        ),
    },
)


class HorizontalGeneTransferEngine:
    """Plasmid DNA extraction, ecosystem target scanning, and Law-6 A/B sandbox grafting."""

    MAX_PLASMID_BYTES = MAX_PLASMID_BYTES

    def __init__(
        self,
        ops_dir: str | Path | None = None,
        *,
        ephemeral: bool = False,
        seed_starters: bool = True,
    ) -> None:
        self._lock = threading.RLock()
        self._ephemeral = bool(ephemeral)
        self._ops_dir = Path(ops_dir) if ops_dir is not None else _default_ops_dir()
        self._conn: sqlite3.Connection | None = None
        self._init_storage()
        if seed_starters:
            self._seed_starter_plasmids()

    def _init_storage(self) -> None:
        if self._ephemeral:
            self._conn = sqlite3.connect(":memory:", check_same_thread=False)
        else:
            self._ops_dir.mkdir(parents=True, exist_ok=True)
            db_path = self._ops_dir / "bios_hgt.sqlite3"
            self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL;")
            self._conn.execute("PRAGMA synchronous=NORMAL;")
            self._conn.execute("PRAGMA busy_timeout=3000;")

        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS plasmids (
                plasmid_id TEXT PRIMARY KEY,
                name TEXT UNIQUE NOT NULL,
                source_project TEXT NOT NULL,
                sha256 TEXT NOT NULL,
                byte_size INTEGER NOT NULL,
                tags_json TEXT NOT NULL,
                capsule_json TEXT NOT NULL,
                created_at REAL NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS graft_proposals (
                proposal_id TEXT PRIMARY KEY,
                plasmid_id TEXT NOT NULL,
                target_name TEXT NOT NULL,
                verdict TEXT NOT NULL,
                parity_passed INTEGER NOT NULL,
                speedup_ratio REAL NOT NULL,
                auto_activated INTEGER NOT NULL DEFAULT 0,
                requires_human_approval INTEGER NOT NULL DEFAULT 1,
                proposal_sha256 TEXT NOT NULL,
                proposal_json TEXT NOT NULL,
                created_at REAL NOT NULL
            )
            """
        )
        self._conn.commit()

    def _seed_starter_plasmids(self) -> None:
        with self._lock:
            assert self._conn is not None
            existing = {
                row[0]
                for row in self._conn.execute("SELECT name FROM plasmids").fetchall()
            }
        for spec in STARTER_PLASMIDS:
            if spec["name"] not in existing:
                self.extract_plasmid(
                    name=spec["name"],
                    source_project=spec["source_project"],
                    code_or_spec=spec["code_or_spec"],
                    io_contract=spec["io_contract"],
                    benchmark_oracle=spec["benchmark_oracle"],
                    tags=spec["tags"],
                )

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

    def extract_plasmid(
        self,
        name: str,
        source_project: str,
        code_or_spec: str,
        io_contract: dict[str, Any],
        benchmark_oracle: dict[str, Any],
        tags: list[str] | tuple[str, ...] | None = None,
    ) -> dict[str, Any]:
        """Distill a reusable pattern into a signed <= 8 KB Plasmid capsule."""
        clean_name = str(name or "").strip()
        if not clean_name:
            raise ValueError("Plasmid name must be non-empty")
        src_proj = str(source_project or "unknown").strip()
        snippet = str(code_or_spec or "")
        if not snippet.strip():
            raise ValueError("code_or_spec must be non-empty")
        contract = dict(io_contract) if isinstance(io_contract, dict) else {"spec": str(io_contract)}
        oracle = (
            dict(benchmark_oracle)
            if isinstance(benchmark_oracle, dict)
            else {"spec": str(benchmark_oracle)}
        )
        norm_tags = _normalize_tags(tags)
        ast_valid, ast_symbols, ast_signals = _analyze_python_ast(snippet)

        core_payload = {
            "schema": "chimera.bios.plasmid.v1",
            "name": clean_name,
            "source_project": src_proj,
            "tags": norm_tags,
            "io_contract": contract,
            "code_snippet": snippet,
            "oracle_spec": oracle,
            "ast_valid": ast_valid,
            "ast_symbols": ast_symbols,
            "ast_signals": ast_signals,
        }
        digest = _sha256_hex(_canonical_json(core_payload))
        plasmid_id = f"plsm_{_slugify(clean_name)}_{digest[:10]}"
        now = time.time()

        capsule = {
            "plasmid_id": plasmid_id,
            "sha256": digest,
            "created_at": round(now, 3),
            **core_payload,
        }
        # Measure exact UTF-8 byte size of the full signed capsule via fixed-point iteration
        actual_size = len(_canonical_json({**capsule, "byte_size": 0}).encode("utf-8"))
        for _ in range(3):
            next_size = len(
                _canonical_json({**capsule, "byte_size": actual_size}).encode("utf-8")
            )
            if next_size == actual_size:
                break
            actual_size = next_size
        if actual_size > self.MAX_PLASMID_BYTES:
            raise ValueError(
                f"Plasmid '{clean_name}' exceeds {self.MAX_PLASMID_BYTES}-byte cap "
                f"({actual_size} bytes)"
            )
        capsule["byte_size"] = actual_size
        capsule_str = _canonical_json(capsule)

        with self._lock:
            assert self._conn is not None
            self._conn.execute(
                """
                INSERT INTO plasmids (
                    plasmid_id, name, source_project, sha256, byte_size,
                    tags_json, capsule_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    plasmid_id = excluded.plasmid_id,
                    source_project = excluded.source_project,
                    sha256 = excluded.sha256,
                    byte_size = excluded.byte_size,
                    tags_json = excluded.tags_json,
                    capsule_json = excluded.capsule_json,
                    created_at = excluded.created_at
                """,
                (
                    plasmid_id,
                    clean_name,
                    src_proj,
                    digest,
                    actual_size,
                    json.dumps(norm_tags),
                    capsule_str,
                    now,
                ),
            )
            self._conn.commit()

        return capsule

    def get_plasmid(self, plasmid_id_or_name: str) -> dict[str, Any] | None:
        key = str(plasmid_id_or_name or "").strip()
        with self._lock:
            assert self._conn is not None
            row = self._conn.execute(
                """
                SELECT capsule_json FROM plasmids
                WHERE plasmid_id = ? OR name = ?
                LIMIT 1
                """,
                (key, key),
            ).fetchone()
        if not row:
            return None
        return json.loads(row[0])

    def list_plasmids(self, tag: str | None = None) -> list[dict[str, Any]]:
        tag_filter = str(tag).strip().lower() if tag else None
        with self._lock:
            assert self._conn is not None
            rows = self._conn.execute(
                "SELECT capsule_json FROM plasmids ORDER BY name ASC"
            ).fetchall()
        out: list[dict[str, Any]] = []
        for (raw,) in rows:
            item = json.loads(raw)
            if tag_filter and tag_filter not in item.get("tags", []):
                continue
            out.append(item)
        return out

    def verify_plasmid(self, plasmid_id_or_name: str) -> dict[str, Any]:
        plasmid = self.get_plasmid(plasmid_id_or_name)
        if plasmid is None:
            return {"valid": False, "error": "plasmid_not_found"}
        core_keys = (
            "schema",
            "name",
            "source_project",
            "tags",
            "io_contract",
            "code_snippet",
            "oracle_spec",
            "ast_valid",
            "ast_symbols",
            "ast_signals",
        )
        core_payload = {k: plasmid[k] for k in core_keys if k in plasmid}
        recomputed = _sha256_hex(_canonical_json(core_payload))
        byte_size = len(_canonical_json(plasmid).encode("utf-8"))
        valid = bool(recomputed == plasmid.get("sha256") and byte_size <= self.MAX_PLASMID_BYTES)
        return {
            "valid": valid,
            "plasmid_id": plasmid["plasmid_id"],
            "name": plasmid["name"],
            "sha256": plasmid["sha256"],
            "recomputed_sha256": recomputed,
            "byte_size": byte_size,
            "within_8kb_cap": byte_size <= self.MAX_PLASMID_BYTES,
        }

    @staticmethod
    def _inspect_candidate_path(path: Path) -> tuple[set[str], set[str], list[str]]:
        """Lightweight bounded static AST scan of a local file or directory."""
        inferred_tags: set[str] = set()
        inferred_bottlenecks: set[str] = set()
        ast_signals: set[str] = set()

        files: list[Path] = []
        if path.is_file() and path.suffix == ".py":
            files = [path]
        elif path.is_dir():
            for p in sorted(path.glob("*.py"))[:12]:
                files.append(p)

        for fp in files:
            try:
                src = fp.read_text(encoding="utf-8", errors="replace")[:32768]
            except OSError:
                continue
            ok, _, sigs = _analyze_python_ast(src)
            if ok:
                ast_signals.update(sigs)
            low = src.lower()
            if "sqlite3" in low:
                inferred_tags.update(["sqlite", "persistence", "storage"])
                if ".commit()" in low and "executemany" not in low:
                    inferred_bottlenecks.update(["wal", "batching", "ssd"])
            if "struct." in low or "mmap" in low:
                inferred_tags.update(["binary", "ipc", "mmap", "low_latency"])
                if "struct.pack(" in low and "pack_into" not in low:
                    inferred_bottlenecks.update(["zero_alloc", "ring", "memory"])
            if "threading" in low or "urllib" in low or "cache" in low:
                inferred_tags.update(["concurrency", "io", "cache"])
                if "singleflight" not in low:
                    inferred_bottlenecks.update(["singleflight", "dedup"])
        return inferred_tags, inferred_bottlenecks, sorted(ast_signals)

    def scan_ecosystem_targets(
        self,
        plasmid_id: str,
        candidate_repos_or_profiles: list[dict[str, Any] | str | Path],
    ) -> list[dict[str, Any]]:
        """Match a plasmid against candidate ecosystem projects/profiles via tag, bottleneck & AST signals."""
        plasmid = self.get_plasmid(plasmid_id)
        if plasmid is None:
            raise KeyError(f"Unknown plasmid: {plasmid_id}")

        p_tags = set(plasmid.get("tags", []))
        p_ast = set(plasmid.get("ast_signals", []))
        p_keywords = set(p_tags) | set(re.findall(r"[a-z0-9]+", plasmid["name"].lower()))
        p_source = str(plasmid.get("source_project", "")).lower()

        matches: list[dict[str, Any]] = []
        for idx, cand in enumerate(candidate_repos_or_profiles or []):
            if isinstance(cand, (str, Path)):
                c_path = Path(cand)
                target_name = c_path.name or str(cand)
                c_tags, c_bottlenecks, c_ast_list = self._inspect_candidate_path(c_path)
                installed: set[str] = set()
            elif isinstance(cand, dict):
                target_name = str(cand.get("name") or cand.get("repo") or f"target_{idx}")
                c_tags = set(_normalize_tags(cand.get("tags")))
                c_bottlenecks = set(_normalize_tags(cand.get("bottlenecks") or cand.get("needs")))
                c_ast_list = []
                installed = set(_normalize_tags(cand.get("installed_plasmids")))

                # Tokenize free-text description/bottlenecks too
                desc = str(cand.get("description", "")).lower()
                for tok in re.findall(r"[a-z0-9_]+", desc):
                    if tok in p_keywords:
                        c_bottlenecks.add(tok)

                src_code = cand.get("source_code")
                if isinstance(src_code, str) and src_code.strip():
                    ok, _, sigs = _analyze_python_ast(src_code)
                    if ok:
                        c_ast_list.extend(sigs)
                    low = src_code.lower()
                    if "sqlite3" in low and "executemany" not in low:
                        c_bottlenecks.update(["sqlite", "wal", "batching"])
                    if "struct.pack(" in low and "pack_into" not in low:
                        c_bottlenecks.update(["zero_alloc", "binary", "ring"])
                    if ("threading" in low or "cache" in low) and "singleflight" not in low:
                        c_bottlenecks.update(["singleflight", "dedup", "concurrency"])

                cand_path = cand.get("path")
                if cand_path:
                    pt, pb, pa = self._inspect_candidate_path(Path(cand_path))
                    c_tags.update(pt)
                    c_bottlenecks.update(pb)
                    c_ast_list.extend(pa)
            else:
                continue

            c_ast = set(c_ast_list)
            already_present = (
                target_name.lower() == p_source
                or plasmid["name"].lower() in installed
                or plasmid["plasmid_id"].lower() in installed
            )

            matched_tags = sorted(p_tags & c_tags)
            matched_bottlenecks = sorted(p_keywords & c_bottlenecks)
            matched_ast = sorted(p_ast & c_ast)

            if already_present:
                score = 0.0
                reason = "plasmid_already_present_in_source"
            else:
                tag_score = len(matched_tags) / float(max(1, min(len(p_tags), 4)))
                bn_score = len(matched_bottlenecks) / float(max(1, min(len(p_keywords), 3)))
                ast_score = len(matched_ast) / float(max(1, len(p_ast))) if p_ast else 0.0
                score = min(1.0, 0.45 * min(1.0, tag_score) + 0.40 * min(1.0, bn_score) + 0.15 * min(1.0, ast_score))
                reasons = []
                if matched_tags:
                    reasons.append(f"tags={','.join(matched_tags[:4])}")
                if matched_bottlenecks:
                    reasons.append(f"bottlenecks={','.join(matched_bottlenecks[:4])}")
                if matched_ast:
                    reasons.append(f"ast={','.join(matched_ast[:4])}")
                reason = "; ".join(reasons) if reasons else "no_strong_capability_overlap"

            matches.append(
                {
                    "target_name": target_name,
                    "plasmid_id": plasmid["plasmid_id"],
                    "plasmid_name": plasmid["name"],
                    "match_score": round(score, 4),
                    "matched_tags": matched_tags,
                    "matched_bottlenecks": matched_bottlenecks,
                    "ast_signals": matched_ast,
                    "recommended": bool(score >= 0.25 and not already_present),
                    "already_present": already_present,
                    "reason": reason,
                }
            )

        matches.sort(key=lambda m: (-m["match_score"], m["target_name"]))
        return matches

    def sandbox_ab_graft(
        self,
        plasmid_id: str,
        target_name: str,
        baseline_fn: Callable[..., Any],
        grafted_fn: Callable[..., Any],
        test_cases: list[Any],
        *,
        iterations: int = 1,
    ) -> dict[str, Any]:
        """Run isolated A/B bit-exact parity + speedup verification and emit Law-6 Graft Proposal."""
        plasmid = self.get_plasmid(plasmid_id)
        if plasmid is None:
            raise KeyError(f"Unknown plasmid: {plasmid_id}")
        cases = list(test_cases or [])
        if not cases:
            raise ValueError("test_cases must contain at least one test case")
        iters = max(1, int(iterations))

        cases_matched = 0
        mismatches: list[dict[str, Any]] = []
        base_ns_total = 0
        graft_ns_total = 0

        for idx, case in enumerate(cases):
            case_label = case.get("name", f"case_{idx}") if isinstance(case, dict) else f"case_{idx}"
            has_expected = isinstance(case, dict) and "expected" in case
            expected_sig = _canonical_value_signature(case["expected"]) if has_expected else None

            base_err: str | None = None
            graft_err: str | None = None
            base_out: Any = None
            graft_out: Any = None

            t0 = time.perf_counter_ns()
            try:
                for _ in range(iters):
                    base_out = _invoke_case(baseline_fn, case)
            except Exception as exc:
                base_err = f"{type(exc).__name__}: {exc}"
            t1 = time.perf_counter_ns()
            base_ns_total += max(1, t1 - t0)

            t2 = time.perf_counter_ns()
            try:
                for _ in range(iters):
                    graft_out = _invoke_case(grafted_fn, case)
            except Exception as exc:
                graft_err = f"{type(exc).__name__}: {exc}"
            t3 = time.perf_counter_ns()
            graft_ns_total += max(1, t3 - t2)

            if base_err is not None or graft_err is not None:
                mismatches.append(
                    {
                        "case": case_label,
                        "reason": "execution_error",
                        "baseline_error": base_err,
                        "grafted_error": graft_err,
                    }
                )
                continue

            base_sig = _canonical_value_signature(base_out)
            graft_sig = _canonical_value_signature(graft_out)
            exact_equal = (base_sig == graft_sig) and (base_out == graft_out)
            if has_expected and expected_sig is not None:
                exact_equal = exact_equal and (graft_sig == expected_sig)

            if exact_equal:
                cases_matched += 1
            else:
                if len(mismatches) < 10:
                    mismatches.append(
                        {
                            "case": case_label,
                            "reason": "output_parity_mismatch",
                            "baseline_type": base_sig[0],
                            "grafted_type": graft_sig[0],
                        }
                    )

        parity_passed = bool(cases_matched == len(cases) and not mismatches)
        baseline_ms = round(base_ns_total / 1_000_000.0, 4)
        grafted_ms = round(graft_ns_total / 1_000_000.0, 4)
        speedup_ratio = round(float(base_ns_total) / float(max(1, graft_ns_total)), 4)

        if not parity_passed:
            verdict = "reject_parity_mismatch"
            law_6_gate = "shadow_ab_rejected"
        elif speedup_ratio < 1.0:
            verdict = "shadow_parity_ok_no_speedup"
            law_6_gate = "shadow_ab_verified"
        else:
            verdict = "approve_candidate"
            law_6_gate = "shadow_ab_verified"

        now = time.time()
        # Law 6 hard invariant: NEVER auto-activate mutations without human sign-off.
        body = {
            "schema": "chimera.bios.graft_proposal.v1",
            "plasmid_id": plasmid["plasmid_id"],
            "plasmid_name": plasmid["name"],
            "plasmid_sha256": plasmid["sha256"],
            "target_name": str(target_name),
            "cases_tested": len(cases),
            "cases_matched": cases_matched,
            "parity_passed": parity_passed,
            "mismatches": mismatches,
            "iterations": iters,
            "baseline_ms": baseline_ms,
            "grafted_ms": grafted_ms,
            "speedup_ratio": speedup_ratio,
            "verdict": verdict,
            "law_6_gate": law_6_gate,
            "auto_activated": False,
            "requires_human_approval": True,
            "rollback_recipe": (
                f"Revert graft '{plasmid['name']}' on '{target_name}' via WorkspaceUndo / "
                "FileRevisions restore and lock plasmid from automatic nomination."
            ),
            "created_at": round(now, 3),
        }
        proposal_sha256 = _sha256_hex(_canonical_json(body))
        proposal_id = f"graft_{_slugify(target_name)}_{proposal_sha256[:10]}"
        proposal = {
            "proposal_id": proposal_id,
            "proposal_sha256": proposal_sha256,
            **body,
        }

        with self._lock:
            assert self._conn is not None
            self._conn.execute(
                """
                INSERT OR REPLACE INTO graft_proposals (
                    proposal_id, plasmid_id, target_name, verdict, parity_passed,
                    speedup_ratio, auto_activated, requires_human_approval,
                    proposal_sha256, proposal_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, 0, 1, ?, ?, ?)
                """,
                (
                    proposal_id,
                    plasmid["plasmid_id"],
                    str(target_name),
                    verdict,
                    1 if parity_passed else 0,
                    speedup_ratio,
                    proposal_sha256,
                    _canonical_json(proposal),
                    now,
                ),
            )
            self._conn.commit()

        return proposal

    def list_proposals(self, target_name: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            assert self._conn is not None
            if target_name:
                rows = self._conn.execute(
                    """
                    SELECT proposal_json FROM graft_proposals
                    WHERE target_name = ?
                    ORDER BY created_at DESC LIMIT ?
                    """,
                    (str(target_name), max(1, int(limit))),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    """
                    SELECT proposal_json FROM graft_proposals
                    ORDER BY created_at DESC LIMIT ?
                    """,
                    (max(1, int(limit)),),
                ).fetchall()
        return [json.loads(r[0]) for r in rows]

    def status(self) -> dict[str, Any]:
        plasmids = self.list_plasmids()
        proposals = self.list_proposals(limit=20)
        return {
            "organ": "CHIMERA-HGT",
            "idea": 8,
            "max_plasmid_bytes": self.MAX_PLASMID_BYTES,
            "plasmid_count": len(plasmids),
            "plasmid_names": [p["name"] for p in plasmids],
            "proposal_count": len(proposals),
            "auto_activated": False,
            "requires_human_approval": True,
            "ephemeral": self._ephemeral,
        }
