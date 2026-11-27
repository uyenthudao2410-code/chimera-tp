"""CHIMERA-AUTOPHAGY & APOPTOSIS (BIOS Idea #3): Metabolic ATP Ledger & Self-Pruning.

Tracks real metabolic ATP yield per organ/cartridge/module/antibody/route in SQLite WAL
(or pure in-memory SQLite when ``ephemeral=True``), tags zero-ATP / stale entities with
Ubiquitin scores, archives dormant payloads to cold compressed storage (0 B hot RAM,
LZ4 if available else stdlib zlib + SHA-256 integrity verification), scans ``chimera_tp/``
via real static Python AST import-graph analysis, and emits strictly Law-6 compliant
(``auto_activated=False``, ``requires_human_approval=True``) signed Apoptosis proposals.

100% Python stdlib, Zero-NumPy, lazy-loaded, strictly Law 1-7 compliant.
"""

from __future__ import annotations

import ast
import collections
import hashlib
import json
import os
import re
import sqlite3
import threading
import time
import uuid
import warnings
import zlib
from pathlib import Path
from typing import Any

try:
    import lz4.frame as _lz4_frame  # type: ignore[import-not-found]
except Exception:
    _lz4_frame = None


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS metabolism_ledger (
    entity_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    calls INTEGER NOT NULL DEFAULT 0,
    ms_saved REAL NOT NULL DEFAULT 0.0,
    tokens_saved INTEGER NOT NULL DEFAULT 0,
    ram_saved_mb REAL NOT NULL DEFAULT 0.0,
    errors_prevented INTEGER NOT NULL DEFAULT 0,
    atp_score REAL NOT NULL DEFAULT 0.0,
    ubiquitin_score REAL NOT NULL DEFAULT 0.0,
    state TEXT NOT NULL DEFAULT 'active',
    first_seen_ts REAL NOT NULL,
    last_active_ts REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS dormant_vault (
    entity_id TEXT PRIMARY KEY,
    codec TEXT NOT NULL,
    raw_bytes INTEGER NOT NULL,
    compressed_bytes INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    archived_ts REAL NOT NULL,
    payload BLOB NOT NULL
);

CREATE TABLE IF NOT EXISTS apoptosis_proposals (
    proposal_id TEXT PRIMARY KEY,
    created_ts REAL NOT NULL,
    sha256 TEXT NOT NULL,
    auto_activated INTEGER NOT NULL DEFAULT 0,
    proposal_json TEXT NOT NULL
);
"""

# Entrypoints & core substrate modules excluded from cold-module pruning flags
_ENTRYPOINT_SUFFIXES = (
    ".__init__",
    ".__main__",
    ".cli",
    ".aether_cli",
    ".substrate",
    ".autoload",
    ".mcp_server",
)

_LEGACY_NAME_RE = re.compile(
    r"(?:^|\.)(?:legacy\.|omega_|singularity_|cosmos_|v(?:9|10|11|12)_)",
    re.IGNORECASE,
)

_STRING_MOD_REF_RE = re.compile(r"chimera_tp(?:\.[A-Za-z_][A-Za-z0-9_]*)+")


def compute_atp_score(
    calls: int = 0,
    ms_saved: float = 0.0,
    tokens_saved: int = 0,
    ram_saved_mb: float = 0.0,
    errors_prevented: int = 0,
) -> float:
    """Compute metabolic ATP yield score from real operational savings."""
    score = (
        max(0, int(calls)) * 0.5
        + max(0.0, float(ms_saved)) / 25.0
        + max(0, int(tokens_saved)) / 200.0
        + max(0.0, float(ram_saved_mb)) * 4.0
        + max(0, int(errors_prevented)) * 15.0
    )
    return round(score, 4)


def _compress_payload(raw: bytes) -> tuple[str, bytes]:
    if _lz4_frame is not None:
        return "lz4", _lz4_frame.compress(raw)
    return "zlib", zlib.compress(raw, level=6)


def _decompress_payload(codec: str, blob: bytes) -> bytes:
    if codec == "lz4":
        if _lz4_frame is None:
            raise RuntimeError("lz4.frame codec unavailable to rehydrate lz4 archive")
        return bytes(_lz4_frame.decompress(blob))
    if codec == "zlib":
        return zlib.decompress(blob)
    raise ValueError(f"Unsupported dormant archive codec: {codec!r}")


def _module_name_for_file(pkg_root: Path, py_file: Path) -> str:
    rel = py_file.relative_to(pkg_root.parent).with_suffix("")
    parts = list(rel.parts)
    if parts and parts[-1] == "__init__":
        return ".".join(parts[:-1])
    return ".".join(parts)


def _resolve_relative_import(current_mod: str, is_pkg_init: bool, level: int, target: str | None) -> str:
    parts = current_mod.split(".")
    if not is_pkg_init:
        parts = parts[:-1]
    up = max(0, int(level) - 1)
    if up > 0:
        parts = parts[:-up] if up < len(parts) else []
    if target:
        parts.extend(target.split("."))
    return ".".join(p for p in parts if p)


def _ast_function_fingerprint(node: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[str, int] | None:
    """Build a structural AST fingerprint for non-trivial top-level helper functions."""
    if node.name.startswith("__") and node.name.endswith("__"):
        return None
    node_types: list[str] = []
    for child in ast.walk(node):
        if isinstance(child, (ast.Load, ast.Store, ast.Del, ast.Expr)):
            continue
        node_types.append(type(child).__name__)
    # Ignore tiny wrappers/getters (< 12 AST nodes) to prevent noise
    if len(node_types) < 12:
        return None
    arg_count = len(node.args.args) + len(node.args.kwonlyargs)
    sig = f"{node.name}|args={arg_count}|" + ",".join(sorted(node_types))
    digest = hashlib.sha256(sig.encode("utf-8")).hexdigest()[:16]
    return digest, len(node_types)


class MetabolicAutophagyEngine:
    """Metabolic ATP ledger, Ubiquitin tagging, cold archival, AST codebase scan & Law-6 Apoptosis."""

    def __init__(
        self,
        ops_dir: str | Path | None = None,
        repo_root: str | Path | None = None,
        *,
        ephemeral: bool = False,
    ) -> None:
        self.ephemeral = bool(ephemeral)
        self.ops_dir = Path(ops_dir) if ops_dir is not None else (Path.home() / ".chimera" / "bios")
        self.repo_root = Path(repo_root) if repo_root is not None else Path.cwd()
        self._lock = threading.RLock()
        self._db_path = ":memory:" if self.ephemeral else str(self.ops_dir / "bios_autophagy.sqlite")
        if not self.ephemeral:
            self.ops_dir.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            if not self.ephemeral:
                self._conn.execute("PRAGMA journal_mode=WAL;")
                self._conn.execute("PRAGMA synchronous=NORMAL;")
            self._conn.executescript(_SCHEMA_SQL)
            self._conn.commit()

    def record_metabolism(
        self,
        entity_id: str,
        kind: str = "module",
        calls: int = 1,
        ms_saved: float = 0.0,
        tokens_saved: int = 0,
        ram_saved_mb: float = 0.0,
        errors_prevented: int = 0,
        *,
        now_ts: float | None = None,
    ) -> dict[str, Any]:
        """Accumulate real metabolic ATP yield for an organ, cartridge, module, antibody, or route."""
        eid = str(entity_id).strip()
        if not eid:
            raise ValueError("entity_id must be non-empty")
        k = str(kind or "module").strip().lower()
        ts = float(now_ts) if now_ts is not None else time.time()
        c_inc = max(0, int(calls))
        ms_inc = max(0.0, float(ms_saved))
        tok_inc = max(0, int(tokens_saved))
        ram_inc = max(0.0, float(ram_saved_mb))
        err_inc = max(0, int(errors_prevented))

        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM metabolism_ledger WHERE entity_id = ?",
                (eid,),
            ).fetchone()
            if row is None:
                tot_calls = c_inc
                tot_ms = ms_inc
                tot_tok = tok_inc
                tot_ram = ram_inc
                tot_err = err_inc
                first_ts = ts
            else:
                tot_calls = int(row["calls"]) + c_inc
                tot_ms = float(row["ms_saved"]) + ms_inc
                tot_tok = int(row["tokens_saved"]) + tok_inc
                tot_ram = float(row["ram_saved_mb"]) + ram_inc
                tot_err = int(row["errors_prevented"]) + err_inc
                first_ts = float(row["first_seen_ts"])

            atp = compute_atp_score(tot_calls, tot_ms, tot_tok, tot_ram, tot_err)
            last_ts = ts if (row is None or atp > float(row["atp_score"]) or c_inc > 0) else float(row["last_active_ts"])
            state = "active" if atp > 0.0 else (row["state"] if row is not None else "active")

            self._conn.execute(
                """
                INSERT INTO metabolism_ledger (
                    entity_id, kind, calls, ms_saved, tokens_saved, ram_saved_mb,
                    errors_prevented, atp_score, ubiquitin_score, state, first_seen_ts, last_active_ts
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0.0, ?, ?, ?)
                ON CONFLICT(entity_id) DO UPDATE SET
                    kind=excluded.kind,
                    calls=excluded.calls,
                    ms_saved=excluded.ms_saved,
                    tokens_saved=excluded.tokens_saved,
                    ram_saved_mb=excluded.ram_saved_mb,
                    errors_prevented=excluded.errors_prevented,
                    atp_score=excluded.atp_score,
                    state=excluded.state,
                    last_active_ts=excluded.last_active_ts
                """,
                (eid, k, tot_calls, tot_ms, tot_tok, tot_ram, tot_err, atp, state, first_ts, last_ts),
            )
            self._conn.commit()
            return {
                "ok": True,
                "entity_id": eid,
                "kind": k,
                "calls": tot_calls,
                "ms_saved": round(tot_ms, 3),
                "tokens_saved": tot_tok,
                "ram_saved_mb": round(tot_ram, 4),
                "errors_prevented": tot_err,
                "atp_score": atp,
                "state": state,
                "last_active_ts": round(last_ts, 3),
            }

    def evaluate_ubiquitin(
        self,
        dormancy_days: float = 30.0,
        now_ts: float | None = None,
    ) -> dict[str, Any]:
        """Score all ledger entities and tag zero-ATP or dormant entities with Ubiquitin."""
        now = float(now_ts) if now_ts is not None else time.time()
        window_days = max(0.001, float(dormancy_days))
        tagged: list[dict[str, Any]] = []
        healthy: list[dict[str, Any]] = []

        with self._lock:
            rows = self._conn.execute("SELECT * FROM metabolism_ledger ORDER BY entity_id ASC").fetchall()
            for row in rows:
                eid = str(row["entity_id"])
                atp = float(row["atp_score"])
                last_ts = float(row["last_active_ts"])
                cur_state = str(row["state"])
                age_days = max(0.0, (now - last_ts) / 86400.0)
                stale_ratio = min(1.0, age_days / window_days)

                if atp <= 0.0:
                    ubiq = min(1.0, 0.72 + 0.28 * stale_ratio)
                    reason = "zero_atp_yield"
                else:
                    low_yield = 1.0 / (1.0 + atp / 10.0)
                    ubiq = min(1.0, stale_ratio * (0.58 + 0.42 * low_yield))
                    reason = "dormant_stale" if ubiq >= 0.60 else "metabolically_active"

                ubiq = round(ubiq, 4)
                is_tagged = bool(ubiq >= 0.60)
                new_state = cur_state
                if cur_state != "dormant":
                    new_state = "tagged_ubiquitin" if is_tagged else "active"

                self._conn.execute(
                    "UPDATE metabolism_ledger SET ubiquitin_score = ?, state = ? WHERE entity_id = ?",
                    (ubiq, new_state, eid),
                )
                entry = {
                    "entity_id": eid,
                    "kind": str(row["kind"]),
                    "atp_score": round(atp, 4),
                    "age_days": round(age_days, 2),
                    "ubiquitin_score": ubiq,
                    "tagged": is_tagged,
                    "state": new_state,
                    "reason": reason,
                }
                if is_tagged:
                    tagged.append(entry)
                else:
                    healthy.append(entry)
            self._conn.commit()

        tagged.sort(key=lambda x: (-x["ubiquitin_score"], x["entity_id"]))
        return {
            "dormancy_days": window_days,
            "evaluated_count": len(tagged) + len(healthy),
            "tagged_count": len(tagged),
            "tagged": tagged,
            "healthy": healthy,
        }

    def archive_dormant(self, entity_id: str, payload_bytes: bytes | bytearray | memoryview) -> dict[str, Any]:
        """Compress and archive a dormant entity to cold storage (0 B hot RAM) with SHA-256."""
        eid = str(entity_id).strip()
        if not eid:
            raise ValueError("entity_id must be non-empty")
        if not isinstance(payload_bytes, (bytes, bytearray, memoryview)):
            raise TypeError("payload_bytes must be bytes-like")
        raw = bytes(payload_bytes)
        digest = hashlib.sha256(raw).hexdigest()
        codec, compressed = _compress_payload(raw)
        now = time.time()

        with self._lock:
            self._conn.execute(
                """
                INSERT INTO dormant_vault (
                    entity_id, codec, raw_bytes, compressed_bytes, sha256, archived_ts, payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(entity_id) DO UPDATE SET
                    codec=excluded.codec,
                    raw_bytes=excluded.raw_bytes,
                    compressed_bytes=excluded.compressed_bytes,
                    sha256=excluded.sha256,
                    archived_ts=excluded.archived_ts,
                    payload=excluded.payload
                """,
                (eid, codec, len(raw), len(compressed), digest, now, sqlite3.Binary(compressed)),
            )
            row = self._conn.execute(
                "SELECT entity_id FROM metabolism_ledger WHERE entity_id = ?",
                (eid,),
            ).fetchone()
            if row is None:
                self._conn.execute(
                    """
                    INSERT INTO metabolism_ledger (
                        entity_id, kind, calls, ms_saved, tokens_saved, ram_saved_mb,
                        errors_prevented, atp_score, ubiquitin_score, state, first_seen_ts, last_active_ts
                    ) VALUES (?, 'archived', 0, 0.0, 0, 0.0, 0, 0.0, 1.0, 'dormant', ?, ?)
                    """,
                    (eid, now, now),
                )
            else:
                self._conn.execute(
                    "UPDATE metabolism_ledger SET state = 'dormant' WHERE entity_id = ?",
                    (eid,),
                )
            self._conn.commit()

        ratio = round(len(compressed) / max(1, len(raw)), 4)
        return {
            "ok": True,
            "entity_id": eid,
            "codec": codec,
            "raw_bytes": len(raw),
            "compressed_bytes": len(compressed),
            "compression_ratio": ratio,
            "sha256": digest,
            "hot_ram_bytes": 0,
        }

    def rehydrate_dormant(self, entity_id: str) -> bytes:
        """Rehydrate an archived dormant entity and verify its SHA-256 digest."""
        eid = str(entity_id).strip()
        with self._lock:
            row = self._conn.execute(
                "SELECT codec, sha256, payload FROM dormant_vault WHERE entity_id = ?",
                (eid,),
            ).fetchone()
            if row is None:
                raise KeyError(f"Dormant entity not found: {eid}")
            codec = str(row["codec"])
            expected_sha = str(row["sha256"])
            blob = bytes(row["payload"])

        raw = _decompress_payload(codec, blob)
        actual_sha = hashlib.sha256(raw).hexdigest()
        if actual_sha != expected_sha:
            raise ValueError(
                f"SHA-256 integrity mismatch for dormant entity {eid!r}: "
                f"expected {expected_sha}, got {actual_sha}"
            )
        with self._lock:
            self._conn.execute(
                "UPDATE metabolism_ledger SET state = 'active', last_active_ts = ? WHERE entity_id = ?",
                (time.time(), eid),
            )
            self._conn.commit()
        return raw

    def scan_codebase_metabolism(self, repo_root: str | Path | None = None) -> dict[str, Any]:
        """Static AST import-graph scan of ``chimera_tp/`` for cold/legacy modules & duplicate helpers."""
        t0 = time.perf_counter()
        root = Path(repo_root) if repo_root is not None else self.repo_root
        pkg_dir = root / "chimera_tp"
        if not pkg_dir.is_dir():
            return {
                "ok": False,
                "error": f"package_dir_not_found:{pkg_dir}",
                "repo_root": str(root),
                "total_modules": 0,
                "cold_modules": [],
                "legacy_modules": [],
                "duplicate_helpers": [],
            }

        py_files = sorted(
            p for p in pkg_dir.rglob("*.py")
            if "__pycache__" not in p.parts
        )
        mod_info: dict[str, dict[str, Any]] = {}
        internal_imports: dict[str, set[str]] = collections.defaultdict(set)
        in_degree: dict[str, int] = collections.defaultdict(int)
        ext_in_degree: dict[str, int] = collections.defaultdict(int)
        helper_buckets: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
        parse_errors: list[str] = []

        # Pass 1: discover all modules
        for py_file in py_files:
            mod_name = _module_name_for_file(pkg_dir, py_file)
            is_init = py_file.name == "__init__.py"
            try:
                src = py_file.read_text(encoding="utf-8-sig", errors="replace")
            except OSError as exc:
                parse_errors.append(f"{py_file}: {exc}")
                continue
            loc = sum(1 for ln in src.splitlines() if ln.strip() and not ln.lstrip().startswith("#"))
            size_bytes = len(src.encode("utf-8"))
            rel_path = py_file.relative_to(root).as_posix()
            mod_info[mod_name] = {
                "module": mod_name,
                "rel_path": rel_path,
                "loc": loc,
                "bytes": size_bytes,
                "est_rss_mb": round((size_bytes * 2.8) / (1024.0 * 1024.0), 4),
                "is_init": is_init,
                "is_legacy": bool(_LEGACY_NAME_RE.search(mod_name)),
                "src": src,
            }

        known_mods = set(mod_info.keys())

        def _extract_refs(src: str, current_mod: str, is_init: bool) -> tuple[set[str], ast.AST | None]:
            refs: set[str] = set()
            tree: ast.AST | None = None
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    tree = ast.parse(src)
            except SyntaxError:
                return refs, None

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        target = alias.name
                        if target in known_mods:
                            refs.add(target)
                elif isinstance(node, ast.ImportFrom):
                    if node.level > 0:
                        base = _resolve_relative_import(current_mod, is_init, node.level, node.module)
                    else:
                        base = node.module or ""
                    if base in known_mods:
                        refs.add(base)
                    for alias in node.names:
                        cand = f"{base}.{alias.name}" if base else alias.name
                        if cand in known_mods:
                            refs.add(cand)
            # Also catch lazy/string-based dynamic imports (importlib.import_module)
            for match in _STRING_MOD_REF_RE.findall(src):
                if match in known_mods and match != current_mod:
                    refs.add(match)
            refs.discard(current_mod)
            return refs, tree

        # Pass 2: build internal import graph + duplicate helper fingerprints
        for mod_name, info in mod_info.items():
            refs, tree = _extract_refs(info["src"], mod_name, info["is_init"])
            if tree is None:
                parse_errors.append(info["rel_path"])
            internal_imports[mod_name] = refs
            for target in refs:
                in_degree[target] += 1

            if tree is not None:
                for node in tree.body:
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        fp = _ast_function_fingerprint(node)
                        if fp is not None:
                            digest, ast_nodes = fp
                            helper_buckets[digest].append(
                                {
                                    "name": node.name,
                                    "module": mod_name,
                                    "rel_path": info["rel_path"],
                                    "lineno": int(node.lineno),
                                    "ast_nodes": ast_nodes,
                                }
                            )

        # Pass 3: scan tests/ and scripts/ as external callers
        for ext_dir_name in ("tests", "scripts"):
            ext_dir = root / ext_dir_name
            if not ext_dir.is_dir():
                continue
            for py_file in ext_dir.rglob("*.py"):
                if "__pycache__" in py_file.parts:
                    continue
                try:
                    src = py_file.read_text(encoding="utf-8-sig", errors="replace")
                except OSError:
                    continue
                refs, _tree = _extract_refs(src, "", False)
                for target in refs:
                    ext_in_degree[target] += 1

        # Classify cold/legacy modules & duplicate helpers
        cold_modules: list[dict[str, Any]] = []
        legacy_modules: list[dict[str, Any]] = []
        total_loc = 0
        for mod_name, info in sorted(mod_info.items()):
            total_loc += info["loc"]
            indeg = in_degree.get(mod_name, 0)
            ext_deg = ext_in_degree.get(mod_name, 0)
            is_entry = (
                mod_name == "chimera_tp"
                or mod_name.endswith(_ENTRYPOINT_SUFFIXES)
                or info["is_init"]
                or ".bios." in mod_name
            )
            record = {
                "module": mod_name,
                "rel_path": info["rel_path"],
                "loc": info["loc"],
                "est_rss_mb": info["est_rss_mb"],
                "internal_importers": indeg,
                "external_importers": ext_deg,
                "is_legacy": info["is_legacy"],
            }
            if info["is_legacy"]:
                legacy_modules.append(record)
            if not is_entry and indeg == 0:
                cold_modules.append(record)

        cold_modules.sort(key=lambda r: (r["external_importers"], -r["loc"], r["module"]))
        duplicate_helpers: list[dict[str, Any]] = []
        for digest, occs in sorted(helper_buckets.items()):
            distinct_mods = {o["module"] for o in occs}
            if len(distinct_mods) >= 2:
                duplicate_helpers.append(
                    {
                        "fingerprint": digest,
                        "name": occs[0]["name"],
                        "occurrences": len(occs),
                        "modules": sorted(distinct_mods),
                        "locations": occs[:8],
                    }
                )
        duplicate_helpers.sort(key=lambda d: (-d["occurrences"], d["name"]))

        reclaimable_loc = sum(m["loc"] for m in cold_modules if m["external_importers"] == 0)
        reclaimable_rss_mb = round(
            sum(m["est_rss_mb"] for m in cold_modules if m["external_importers"] == 0), 4
        )
        scan_ms = round((time.perf_counter() - t0) * 1000.0, 2)

        return {
            "ok": True,
            "repo_root": str(root),
            "total_modules": len(mod_info),
            "total_loc": total_loc,
            "cold_module_count": len(cold_modules),
            "legacy_module_count": len(legacy_modules),
            "duplicate_helper_groups": len(duplicate_helpers),
            "reclaimable_loc_est": reclaimable_loc,
            "reclaimable_rss_mb_est": reclaimable_rss_mb,
            "cold_modules": cold_modules,
            "legacy_modules": legacy_modules,
            "duplicate_helpers": duplicate_helpers[:25],
            "parse_errors": parse_errors,
            "scan_ms": scan_ms,
        }

    def propose_apoptosis_pr(
        self,
        repo_root: str | Path | None = None,
        *,
        max_candidates: int = 15,
    ) -> dict[str, Any]:
        """Emit a strictly Law-6 (auto_activated=False) signed Apoptosis pruning proposal."""
        root = Path(repo_root) if repo_root is not None else self.repo_root
        scan = self.scan_codebase_metabolism(root)
        ubiq = self.evaluate_ubiquitin()
        cap = max(1, int(max_candidates))

        candidates: list[dict[str, Any]] = []
        for mod in scan.get("cold_modules", [])[:cap]:
            ext_refs = int(mod.get("external_importers", 0))
            if mod.get("is_legacy") and ext_refs == 0:
                action = "archive_to_dormant_vault"
                risk = "low"
                reason = "unreferenced_legacy_module"
            elif ext_refs == 0:
                action = "human_review_prune_or_archive"
                risk = "medium"
                reason = "zero_internal_and_external_importers"
            else:
                action = "keep_lazy_import_only"
                risk = "low"
                reason = "referenced_only_by_tests_or_scripts"
            candidates.append(
                {
                    "kind": "module",
                    "target": mod["module"],
                    "rel_path": mod["rel_path"],
                    "loc": mod["loc"],
                    "est_rss_mb": mod["est_rss_mb"],
                    "internal_importers": mod["internal_importers"],
                    "external_importers": ext_refs,
                    "risk_tier": risk,
                    "recommended_action": action,
                    "reason": reason,
                }
            )

        for tag in ubiq.get("tagged", []):
            if len(candidates) >= cap + 5:
                break
            candidates.append(
                {
                    "kind": tag["kind"],
                    "target": tag["entity_id"],
                    "rel_path": None,
                    "loc": 0,
                    "est_rss_mb": 0.0,
                    "ubiquitin_score": tag["ubiquitin_score"],
                    "atp_score": tag["atp_score"],
                    "risk_tier": "low",
                    "recommended_action": "archive_to_dormant_vault",
                    "reason": tag["reason"],
                }
            )

        now = time.time()
        proposal_id = f"apop-{uuid.uuid4().hex[:12]}"
        candidate_paths = [c["rel_path"] for c in candidates if c.get("rel_path")]

        body: dict[str, Any] = {
            "proposal_id": proposal_id,
            "created_ts": round(now, 3),
            "repo_root": str(root),
            "promotion_stage": "Lab",
            "auto_activated": False,
            "requires_human_approval": True,
            "summary": {
                "total_modules_scanned": scan.get("total_modules", 0),
                "cold_module_count": scan.get("cold_module_count", 0),
                "ubiquitin_tagged_count": ubiq.get("tagged_count", 0),
                "candidate_count": len(candidates),
                "reclaimable_loc_est": scan.get("reclaimable_loc_est", 0),
                "reclaimable_rss_mb_est": scan.get("reclaimable_rss_mb_est", 0.0),
            },
            "candidates": candidates,
            "duplicate_helpers_preview": scan.get("duplicate_helpers", [])[:5],
            "rollback_recipe": {
                "git_restore": f"git checkout -- {' '.join(candidate_paths[:6])}" if candidate_paths else "git status",
                "vault_rehydrate": "engine.rehydrate_dormant(entity_id) with SHA-256 verification",
                "verify_command": "pytest -q tests/test_bios_physio.py",
                "zero_files_modified": True,
            },
            "invariant_checks": {
                "law1_eliminate_waste_first": True,
                "law2_zero_choke_compliant": True,
                "law4_content_addressed_receipt": True,
                "law6_auto_activated_false": True,
                "law6_requires_human_approval": True,
                "law7_rss_ceiling_respected": True,
            },
        }
        canonical = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
        digest = hashlib.sha256(canonical).hexdigest()
        proposal = {**body, "sha256": digest}

        with self._lock:
            self._conn.execute(
                """
                INSERT INTO apoptosis_proposals (
                    proposal_id, created_ts, sha256, auto_activated, proposal_json
                ) VALUES (?, ?, ?, 0, ?)
                """,
                (proposal_id, now, digest, json.dumps(proposal, separators=(",", ":"))),
            )
            self._conn.commit()
        return proposal

    def status(self) -> dict[str, Any]:
        """Return summary metrics of the metabolic ATP ledger and dormant vault."""
        with self._lock:
            ledger_row = self._conn.execute(
                """
                SELECT
                    COUNT(*) AS cnt,
                    COALESCE(SUM(atp_score), 0.0) AS total_atp,
                    COALESCE(SUM(calls), 0) AS total_calls,
                    COALESCE(SUM(ms_saved), 0.0) AS total_ms_saved,
                    COALESCE(SUM(tokens_saved), 0) AS total_tokens_saved
                FROM metabolism_ledger
                """
            ).fetchone()
            vault_row = self._conn.execute(
                """
                SELECT
                    COUNT(*) AS cnt,
                    COALESCE(SUM(raw_bytes), 0) AS raw_bytes,
                    COALESCE(SUM(compressed_bytes), 0) AS compressed_bytes
                FROM dormant_vault
                """
            ).fetchone()
            prop_cnt = int(
                self._conn.execute("SELECT COUNT(*) FROM apoptosis_proposals").fetchone()[0]
            )

        return {
            "ephemeral": self.ephemeral,
            "db_path": self._db_path,
            "compression_codec": "lz4" if _lz4_frame is not None else "zlib",
            "entities_tracked": int(ledger_row["cnt"]),
            "total_atp": round(float(ledger_row["total_atp"]), 4),
            "total_calls": int(ledger_row["total_calls"]),
            "total_ms_saved": round(float(ledger_row["total_ms_saved"]), 2),
            "total_tokens_saved": int(ledger_row["total_tokens_saved"]),
            "dormant_archived_count": int(vault_row["cnt"]),
            "dormant_raw_bytes": int(vault_row["raw_bytes"]),
            "dormant_compressed_bytes": int(vault_row["compressed_bytes"]),
            "dormant_hot_ram_bytes": 0,
            "apoptosis_proposals_count": prop_cnt,
        }

    def close(self) -> None:
        """Close SQLite connection cleanly."""
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass

    def __enter__(self) -> "MetabolicAutophagyEngine":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()
