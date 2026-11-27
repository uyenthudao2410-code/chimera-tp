"""Breakthrough #4: Active Compute-in-Transit & Fluid Pushdown Operators (`AQ01` / `AQ02`)."""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import queue
import re
import socket
import sqlite3
import struct
import threading
import time
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from .hyper_wire import (
    HyperWireReceiver,
    HyperWireSender,
    _bind_any,
    _disable_connreset,
    _family_for_ip,
)
from .merkle_sync import DEFAULT_IGNORE_DIRS, DEFAULT_IGNORE_EXTS, ShadowMerkleIndex
from .native import active_filter_lines
from .telepathy import DomainDictionary, TelepathicCodec, TelepathicStore

ComputeOp = Literal[
    "filter_lines",
    "json_filter_project",
    "csv_group_sum",
    "multi_grep",
    "log_analytics",
    "sqlite_query",
    "remote_digest",
]

_TS_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?\b")
_IPV4_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_HEX_RE = re.compile(r"\b(?:0x[0-9a-fA-F]+|[0-9a-fA-F]{8,})\b")
_NUM_RE = re.compile(r"\b\d+\b")
_HOUR_RE = re.compile(r"(\d{4}-\d{2}-\d{2})[T ](\d{2}):")
_FORBIDDEN_SQL_RE = re.compile(
    r"\b(?:INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|REPLACE|ATTACH|DETACH|VACUUM|REINDEX|ANALYZE)\b",
    re.IGNORECASE,
)


@dataclass
class ComputePlan:
    op: ComputeOp
    needle: str = ""
    where_key: str = ""
    where_eq: str = ""
    project_fields: tuple[str, ...] = ()
    delimiter: str = ","
    group_col: int = 0
    value_col: int = 1
    skip_header: bool = True
    placement: Literal["auto", "sender", "receiver"] = "auto"
    patterns: tuple[str, ...] = ()
    match_mode: Literal["any", "all"] = "any"
    regex: bool = False
    ignore_case: bool = False
    file_glob: str = "*"
    sql: str = ""
    max_rows: int = 500
    use_telepathy: bool = True
    dict_id: str = ""


@dataclass
class ActivePipeResult:
    op: str
    executed_at: str
    raw_bytes: int
    wire_bytes: int
    wire_reduction_pct: float
    matched_records: int
    preview_items: list[str]
    preview_first_ms: float | None
    total_ms: float
    output_bytes: bytes

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("output_bytes", None)
        d["output_size_bytes"] = len(self.output_bytes)
        return d


def make_synthetic_logs(total_bytes: int = 2 * 1024 * 1024) -> bytes:
    """Deterministic realistic log corpus (~1% ERROR/CRITICAL lines) for Active Pipe evaluation."""
    chunk_lines: list[str] = []
    for i in range(100):
        if i == 0:
            chunk_lines.append(
                f"2026-11-25T11:30:00Z CRITICAL ERROR auth-gateway uid={i:06d} code=E_TIMEOUT detail=deadbeef00\n"
            )
        else:
            chunk_lines.append(
                f"2026-11-25T11:30:00Z INFO  telemetry-bus uid={i:06d} status=OK   pad=0123456789abcdef\n"
            )
    unit = "".join(chunk_lines).encode("ascii")
    reps = max(1, (total_bytes // len(unit)) + 1)
    return (unit * reps)[:total_bytes]


def decide_placement(
    raw_bytes: int,
    estimated_selectivity: float = 0.1,
    bandwidth_mbps: float = 100.0,
    sender_cpu_load: float = 0.25,
) -> Literal["sender", "receiver"]:
    """Auto-decide whether executing in-transit at sender beats shipping raw bytes."""
    if raw_bytes <= 4096:
        return "receiver"
    if estimated_selectivity >= 0.90 and sender_cpu_load >= 0.80:
        return "receiver"
    if estimated_selectivity < 0.70 or bandwidth_mbps <= 2000.0:
        return "sender"
    return "receiver"


def _iter_log_lines(data: bytes):
    """Decode ordinary LF/CRLF logs in bounded blocks, preserving splitlines semantics."""
    start = 0
    while start < len(data):
        end = min(start + 64 * 1024, len(data))
        if end < len(data):
            # LF is a complete line terminator and cannot split a UTF-8 character.
            boundary = data.rfind(b"\n", start, end)
            if boundary < start:
                boundary = data.find(b"\n", end)
            end = len(data) if boundary < 0 else boundary + 1
        yield from data[start:end].decode("utf-8", errors="replace").splitlines()
        start = end


def _normalize_log_template(line: str) -> str:
    s = _TS_RE.sub("<TS>", line)
    s = _IPV4_RE.sub("<IP>", s)
    s = _HEX_RE.sub("<HEX>", s)
    s = _NUM_RE.sub("<N>", s)
    return s.strip()


def _validate_readonly_sql(sql: str) -> str:
    s = str(sql or "").strip()
    if s.endswith(";"):
        s = s[:-1].strip()
    if not s:
        raise ValueError("Empty SQL query")
    if ";" in s:
        raise ValueError("Multiple SQL statements rejected")
    if _FORBIDDEN_SQL_RE.search(s):
        raise ValueError("Mutating SQL keywords rejected in read-only mode")
    if re.match(r"^PRAGMA\b", s, re.IGNORECASE):
        if not re.match(r"^PRAGMA\s+(?:TABLE_INFO|TABLE_LIST)\b", s, re.IGNORECASE):
            raise ValueError("Only PRAGMA table_info / table_list allowed")
    elif not re.match(r"^(?:SELECT|WITH)\b", s, re.IGNORECASE):
        raise ValueError("Only read-only SELECT / WITH queries allowed")
    return s


def _execute_multi_grep_lines(
    lines: list[str], plan: ComputePlan, prefix: str = ""
) -> list[str]:
    pats = [p for p in plan.patterns if p] or ([plan.needle] if plan.needle else [])
    flags = re.IGNORECASE if plan.ignore_case else 0
    compiled = [re.compile(p, flags) if plan.regex else None for p in pats]
    pats_cmp = [p.lower() if plan.ignore_case else p for p in pats]

    hits: list[str] = []
    for idx, line in enumerate(lines, start=1):
        if not pats:
            matched = True
        elif plan.regex:
            checks = (bool(rx.search(line)) for rx in compiled if rx is not None)
            matched = all(checks) if plan.match_mode == "all" else any(checks)
        else:
            hay = line.lower() if plan.ignore_case else line
            checks = (p in hay for p in pats_cmp)
            matched = all(checks) if plan.match_mode == "all" else any(checks)
        if matched:
            hits.append(f"{prefix}{idx}: {line}" if prefix else line)
    return hits


def analyze_log_lines(lines: Iterable[str]) -> dict[str, Any]:
    """Summarize decoded log lines for the wire operator and the local Sentinel."""
    sev_counts = {"CRITICAL": 0, "ERROR": 0, "WARN": 0, "INFO": 0, "OTHER": 0}
    hourly: dict[str, int] = {}
    templates: dict[str, dict[str, Any]] = {}
    total_lines = 0
    for raw_line in lines:
        if not raw_line.strip():
            continue
        total_lines += 1
        upper = raw_line.upper()
        if "CRITICAL" in upper:
            sev_counts["CRITICAL"] += 1
        elif "ERROR" in upper or "FAIL" in upper or "EXCEPTION" in upper:
            sev_counts["ERROR"] += 1
        elif "WARN" in upper:
            sev_counts["WARN"] += 1
        elif "INFO" in upper:
            sev_counts["INFO"] += 1
        else:
            sev_counts["OTHER"] += 1

        hm = _HOUR_RE.search(raw_line)
        if hm:
            hb = f"{hm.group(1)} {hm.group(2)}:00"
            hourly[hb] = hourly.get(hb, 0) + 1

        ts_m = _TS_RE.search(raw_line)
        ts_str = ts_m.group(0) if ts_m else ""
        tmpl = _normalize_log_template(raw_line)
        ent = templates.get(tmpl)
        if ent is None:
            templates[tmpl] = {
                "template": tmpl,
                "count": 1,
                "first_ts": ts_str,
                "last_ts": ts_str,
            }
        else:
            ent["count"] += 1
            if ts_str:
                if not ent["first_ts"]:
                    ent["first_ts"] = ts_str
                ent["last_ts"] = ts_str

    top_templates = sorted(
        templates.values(), key=lambda x: (-int(x["count"]), str(x["template"]))
    )[:20]
    report = {
        "total_lines": total_lines,
        "unique_templates": len(templates),
        "severity_counts": sev_counts,
        "hourly_top": dict(sorted(hourly.items(), key=lambda kv: kv[0])[-24:]),
        "top_templates": top_templates,
    }
    return report


def execute_operator(data: bytes, plan: ComputePlan) -> tuple[bytes, int, list[str]]:
    """Run an active compute operator locally, returning (result_bytes, matches, preview_top5)."""
    if plan.op == "filter_lines":
        needle_b = plan.needle.encode("utf-8")
        filtered, matched = active_filter_lines(data, needle_b)
        preview = [
            ln.decode("utf-8", errors="replace").rstrip("\r\n")
            for ln in filtered.splitlines()[:5]
        ]
        return filtered, matched, preview

    if plan.op == "json_filter_project":
        out_lines: list[str] = []
        preview: list[str] = []
        where_key = plan.where_key
        where_eq = plan.where_eq
        fields = plan.project_fields
        text = data.decode("utf-8", errors="replace")
        for line in text.splitlines():
            line_s = line.strip()
            if not line_s:
                continue
            try:
                obj = json.loads(line_s)
            except json.JSONDecodeError:
                continue
            if where_key and str(obj.get(where_key, "")) != where_eq:
                continue
            proj = {k: obj.get(k) for k in fields} if fields else obj
            encoded = json.dumps(proj, ensure_ascii=False, separators=(",", ":"))
            out_lines.append(encoded)
            if len(preview) < 5:
                preview.append(encoded)
        result = ("\n".join(out_lines) + ("\n" if out_lines else "")).encode("utf-8")
        return result, len(out_lines), preview

    if plan.op == "csv_group_sum":
        sums: dict[str, list[float]] = {}
        delim = plan.delimiter
        gcol = plan.group_col
        vcol = plan.value_col
        lines = data.decode("utf-8", errors="replace").splitlines()
        start_idx = 1 if (plan.skip_header and lines) else 0
        for line in lines[start_idx:]:
            if not line:
                continue
            parts = line.split(delim)
            if max(gcol, vcol) >= len(parts):
                continue
            key = parts[gcol]
            try:
                val = float(parts[vcol])
            except ValueError:
                continue
            entry = sums.get(key)
            if entry is None:
                sums[key] = [val, 1.0]
            else:
                entry[0] += val
                entry[1] += 1.0

        summary = {
            k: {"sum": round(v[0], 4), "count": int(v[1])}
            for k, v in sorted(sums.items())
        }
        payload = json.dumps(summary, ensure_ascii=False, indent=2).encode("utf-8")
        preview = [
            f"{k}: sum={v['sum']}, count={v['count']}"
            for k, v in list(summary.items())[:5]
        ]
        return payload, len(summary), preview

    if plan.op == "log_analytics":
        report = analyze_log_lines(_iter_log_lines(data))
        payload = json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8")
        preview = [
            f"[{t['count']}x] {t['template'][:110]}" for t in report["top_templates"][:5]
        ]
        return payload, report["total_lines"], preview

    if plan.op == "multi_grep":
        lines = data.decode("utf-8", errors="replace").splitlines()
        hits = _execute_multi_grep_lines(lines, plan)
        out_b = ("\n".join(hits) + ("\n" if hits else "")).encode("utf-8")
        return out_b, len(hits), hits[:5]

    raise ValueError(f"Unsupported in-memory active compute operator: {plan.op}")


def execute_path_operator(
    target_path: Path | None,
    raw_data: bytes | None,
    plan: ComputePlan,
) -> tuple[bytes, int, int, list[str]]:
    """Execute file/directory/SQLite operator near disk, returning (out_bytes, raw_scanned, matched, preview)."""
    if plan.op == "sqlite_query":
        if target_path is None or not target_path.is_file():
            raise FileNotFoundError(f"SQLite DB file not found: {target_path}")
        sql_clean = _validate_readonly_sql(plan.sql)
        max_rows = max(1, min(500, int(plan.max_rows)))
        raw_sz = int(target_path.stat().st_size)
        deadline = time.perf_counter() + 3.0
        conn = sqlite3.connect(f"file:{target_path.as_posix()}?mode=ro", uri=True)
        try:
            conn.set_progress_handler(lambda: 1 if time.perf_counter() > deadline else 0, 5000)
            cur = conn.execute(sql_clean)
            cols = [d[0] for d in (cur.description or [])]
            fetched = cur.fetchmany(max_rows + 1)
            truncated = len(fetched) > max_rows
            rows_raw = fetched[:max_rows]
            rows: list[list[Any]] = []
            for r in rows_raw:
                rows.append([v.hex() if isinstance(v, (bytes, bytearray)) else v for v in r])
            out_obj = {
                "sql": sql_clean,
                "columns": cols,
                "row_count": len(rows),
                "truncated": truncated,
                "rows": rows,
            }
            payload = json.dumps(out_obj, ensure_ascii=False, indent=2).encode("utf-8")
            preview = [json.dumps(r, ensure_ascii=False) for r in rows[:5]]
            return payload, raw_sz, len(rows), preview
        finally:
            conn.close()

    if plan.op == "remote_digest":
        if target_path is None or not target_path.exists():
            data = raw_data or b""
            digest = {
                "kind": "bytes",
                "total_bytes": len(data),
                "blake2b_16": hashlib.blake2b(data, digest_size=16).hexdigest(),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
            payload = json.dumps(digest, indent=2).encode("utf-8")
            return payload, len(data), 1, [f"blake2b={digest['blake2b_16']} bytes={len(data)}"]

        if target_path.is_file():
            data = target_path.read_bytes()
            digest = {
                "kind": "file",
                "name": target_path.name,
                "total_bytes": len(data),
                "blake2b_16": hashlib.blake2b(data, digest_size=16).hexdigest(),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
            payload = json.dumps(digest, ensure_ascii=False, indent=2).encode("utf-8")
            return payload, len(data), 1, [f"{target_path.name}: {len(data)}B sha256={digest['sha256'][:16]}..."]

        snap = ShadowMerkleIndex().scan(target_path)
        top_files = sorted(
            ((k, v["size"], v["hash"]) for k, v in snap.files.items()),
            key=lambda x: (-int(x[1]), x[0]),
        )[:15]
        digest = {
            "kind": "directory",
            "root": str(target_path),
            "root_hash": snap.root_hash,
            "total_files": snap.total_files,
            "total_bytes": snap.total_bytes,
            "scan_ms": snap.scan_ms,
            "largest_files": [{"path": p, "size": sz, "hash": h} for p, sz, h in top_files],
        }
        payload = json.dumps(digest, ensure_ascii=False, indent=2).encode("utf-8")
        preview = [
            f"root={snap.root_hash} files={snap.total_files} total={snap.total_bytes}B",
            *[f"{p} ({sz} B)" for p, sz, _ in top_files[:4]],
        ]
        return payload, snap.total_bytes, snap.total_files, preview

    if plan.op == "multi_grep" and target_path is not None and target_path.is_dir():
        hits_all: list[str] = []
        raw_scanned = 0
        max_scan = 32 * 1024 * 1024
        files_scanned = 0
        glob_pat = plan.file_glob or "*"
        for dirpath, dirnames, filenames in os.walk(target_path):
            dirnames[:] = sorted(d for d in dirnames if d not in DEFAULT_IGNORE_DIRS)
            for fn in sorted(filenames):
                if files_scanned >= 200 or raw_scanned >= max_scan:
                    break
                p = Path(dirpath) / fn
                if p.suffix.lower() in DEFAULT_IGNORE_EXTS or not fnmatch.fnmatch(fn, glob_pat):
                    continue
                try:
                    raw = p.read_bytes()
                except OSError:
                    continue
                if b"\x00" in raw[:4096]:
                    continue
                files_scanned += 1
                raw_scanned += len(raw)
                rel = p.relative_to(target_path).as_posix()
                lines = raw.decode("utf-8", errors="replace").splitlines()
                hits_all.extend(_execute_multi_grep_lines(lines, plan, prefix=f"{rel}:"))
            if files_scanned >= 200 or raw_scanned >= max_scan:
                break
        out_b = ("\n".join(hits_all) + ("\n" if hits_all else "")).encode("utf-8")
        return out_b, raw_scanned, len(hits_all), hits_all[:5]

    data = raw_data if raw_data is not None else (target_path.read_bytes() if target_path else b"")
    out_b, matched, preview = execute_operator(data, plan)
    return out_b, len(data), matched, preview


class ActivePipeEngine:
    """Execute Compute-in-Transit queries across HyperWire with Priority-0 live previews."""

    def run_query(
        self,
        raw_data: bytes,
        plan: ComputePlan,
        target_addr: tuple[str, int] | None = None,
        external_rx: HyperWireReceiver | None = None,
        bandwidth_mbps: float = 100.0,
        est_loss: float = 0.0,
        stream_id: int = 1,
        timeout_s: float = 20.0,
    ) -> ActivePipeResult:
        t0 = time.perf_counter()
        placement = plan.placement
        if placement == "auto":
            placement = decide_placement(
                len(raw_data), estimated_selectivity=0.05, bandwidth_mbps=bandwidth_mbps
            )

        preview_ts: list[float] = []
        preview_payload: list[list[str]] = []

        def on_prio(frame: bytes, ts: float) -> None:
            if not preview_ts:
                preview_ts.append((ts - t0) * 1000.0)
            try:
                obj = json.loads(frame.decode("utf-8"))
                preview_payload.append(obj.get("preview", []))
            except Exception:
                pass

        owns_rx = external_rx is None
        rx = external_rx if external_rx is not None else HyperWireReceiver(on_priority_frame=on_prio).start()
        if not owns_rx and rx._on_priority_frame is None:
            rx._on_priority_frame = on_prio
        dst_addr = target_addr or rx.addr
        try:
            sender = HyperWireSender(dst_addr, initial_loss_hint=est_loss)
            if placement == "sender":
                computed_bytes, matched, preview = execute_operator(raw_data, plan)
                prio_bytes = json.dumps(
                    {"op": plan.op, "matched": matched, "preview": preview},
                    ensure_ascii=False,
                ).encode("utf-8")
                rep = sender.send_stream(
                    computed_bytes,
                    stream_id=stream_id,
                    priority_frame=prio_bytes,
                    timeout_s=timeout_s,
                )
                delivered, _ = rx.wait_stream(stream_id, timeout_s=timeout_s)
                if not rep.sha256_match:
                    raise RuntimeError("HyperWire active pipe delivery incomplete")
                total_ms = (time.perf_counter() - t0) * 1000.0
                red_pct = (
                    max(0.0, 100.0 * (1.0 - rep.wire_bytes_sent / len(raw_data)))
                    if raw_data
                    else 0.0
                )
                return ActivePipeResult(
                    op=plan.op,
                    executed_at="sender",
                    raw_bytes=len(raw_data),
                    wire_bytes=rep.wire_bytes_sent,
                    wire_reduction_pct=round(red_pct, 2),
                    matched_records=matched,
                    preview_items=preview_payload[0] if preview_payload else preview,
                    preview_first_ms=round(preview_ts[0], 2) if preview_ts else None,
                    total_ms=round(total_ms, 2),
                    output_bytes=delivered,
                )
            else:
                rep = sender.send_stream(raw_data, stream_id=stream_id, timeout_s=timeout_s)
                delivered, _ = rx.wait_stream(stream_id, timeout_s=timeout_s)
                computed_bytes, matched, preview = execute_operator(delivered, plan)
                total_ms = (time.perf_counter() - t0) * 1000.0
                return ActivePipeResult(
                    op=plan.op,
                    executed_at="receiver",
                    raw_bytes=len(raw_data),
                    wire_bytes=rep.wire_bytes_sent,
                    wire_reduction_pct=0.0,
                    matched_records=matched,
                    preview_items=preview,
                    preview_first_ms=None,
                    total_ms=round(total_ms, 2),
                    output_bytes=computed_bytes,
                )
        finally:
            if owns_rx:
                rx.close()


class ActiveQueryServer:
    """Single-port symmetric UDP server executing Active & Fluid Compute + Telepathic Wire."""

    def __init__(
        self,
        bind_ip: str = "0.0.0.0",
        bind_port: int = 0,
        allowed_roots: list[Path] | None = None,
        telepathy_store: TelepathicStore | None = None,
    ) -> None:
        self.allowed_roots = [Path(p).resolve() for p in (allowed_roots or [])]
        self.telepathy_store = telepathy_store
        self._tele_codec = TelepathicCodec()
        self._sock = socket.socket(_family_for_ip(bind_ip), socket.SOCK_DGRAM)
        _disable_connreset(self._sock)
        try:
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4 * 1024 * 1024)
        except OSError:
            pass
        self._sock.bind((bind_ip, bind_port))
        self._sock.settimeout(0.25)
        self.addr: tuple[str, int] = self._sock.getsockname()[:2]
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._fb_queues: dict[int, queue.Queue[bytes]] = {}
        self._next_stream = 1
        self._thread = threading.Thread(target=self._serve_loop, daemon=True)

    def start(self) -> "ActiveQueryServer":
        self._thread.start()
        return self

    def _resolve_target_path(self, file_path: str) -> Path | None:
        if file_path == "@synthetic":
            return None
        candidate = Path(file_path).resolve()
        if not self.allowed_roots:
            raise PermissionError("Remote queries disabled (no allowed_roots configured)")
        if not any(candidate == r or r in candidate.parents for r in self.allowed_roots):
            raise PermissionError(f"Path outside allowed_roots: {candidate}")
        if not candidate.exists():
            raise FileNotFoundError(f"Query target not found: {candidate}")
        return candidate

    def _load_target_bytes(self, file_path: str) -> bytes:
        target = self._resolve_target_path(file_path)
        if target is None:
            return make_synthetic_logs(2 * 1024 * 1024)
        if not target.is_file():
            raise FileNotFoundError(f"Target is not a regular file: {target}")
        return target.read_bytes()

    def _serve_loop(self) -> None:
        while not self._stop.is_set():
            try:
                pkt, addr = self._sock.recvfrom(65535)
            except (socket.timeout, ConnectionResetError):
                continue
            except OSError:
                break

            if (pkt.startswith(b"AQ01") or pkt.startswith(b"AQ02")) and len(pkt) >= 6:
                (reply_port,) = struct.unpack_from("<H", pkt, 4)
                try:
                    req = json.loads(pkt[6:].decode("utf-8"))
                except Exception:
                    continue
            else:
                if len(pkt) >= 20 and pkt[:2] == b"CH":
                    sid = pkt[3]
                    with self._lock:
                        fq = self._fb_queues.get(sid)
                    if fq is not None:
                        fq.put(pkt)
                continue

            with self._lock:
                sid = self._next_stream
                self._next_stream = (self._next_stream % 250) + 1
                fb_q: queue.Queue[bytes] = queue.Queue()
                self._fb_queues[sid] = fb_q

            threading.Thread(
                target=self._execute_and_reply,
                args=(addr, reply_port, sid, fb_q, req),
                daemon=True,
            ).start()

    def _execute_and_reply(
        self,
        ctrl_peer: tuple[str, int],
        reply_port: int,
        sid: int,
        fb_q: "queue.Queue[bytes]",
        req: dict[str, Any],
    ) -> None:
        t0 = time.perf_counter()
        raw_scanned = 0
        matched = 0
        preview: list[str] = []
        tele_stats: dict[str, Any] = {
            "mode_name": "raw",
            "dict_id": "",
            "plain_zlib_bytes": 0,
            "wire_bytes": 0,
        }
        wire_payload = b""
        computed = b""
        err = ""

        try:
            fpath = str(req.get("file_path", "@synthetic"))
            target_path = self._resolve_target_path(fpath)
            raw_opt = make_synthetic_logs(2 * 1024 * 1024) if target_path is None else None
            plan = ComputePlan(
                op=req.get("op", "filter_lines"),
                needle=str(req.get("needle", "")),
                where_key=str(req.get("where_key", "")),
                where_eq=str(req.get("where_eq", "")),
                project_fields=tuple(req.get("project_fields", [])),
                group_col=int(req.get("group_col", 0)),
                value_col=int(req.get("value_col", 1)),
                placement="sender",
                patterns=tuple(req.get("patterns", [])),
                match_mode="all" if req.get("match_mode") == "all" else "any",
                regex=bool(req.get("regex", False)),
                ignore_case=bool(req.get("ignore_case", False)),
                file_glob=str(req.get("file_glob", "*")),
                sql=str(req.get("sql", "")),
                max_rows=int(req.get("max_rows", 500)),
                use_telepathy=bool(req.get("use_telepathy", True)),
                dict_id=str(req.get("dict_id", "")),
            )
            computed, raw_scanned, matched, preview = execute_path_operator(
                target_path, raw_opt, plan
            )
            if plan.use_telepathy:
                dd = (
                    self.telepathy_store.get(plan.dict_id)
                    if (self.telepathy_store is not None and plan.dict_id)
                    else None
                )
                wire_payload, tele_stats = self._tele_codec.encode(
                    computed, domain_dict=dd, allow_template_fold=True
                )
            else:
                wire_payload = computed
                tele_stats["wire_bytes"] = len(computed)
        except Exception as exc:
            err = str(exc)

        exec_ms = (time.perf_counter() - t0) * 1000.0
        ack = b"QAK1" + json.dumps(
            {
                "stream_id": sid,
                "raw_bytes": raw_scanned,
                "uncompressed_bytes": len(computed),
                "compressed_bytes": len(wire_payload),
                "plain_zlib_bytes": tele_stats.get("plain_zlib_bytes", len(computed)),
                "codec_mode": tele_stats.get("mode_name", "raw"),
                "dict_id": tele_stats.get("dict_id", ""),
                "matched": matched,
                "server_exec_ms": round(exec_ms, 2),
                "error": err,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        try:
            self._sock.sendto(ack, ctrl_peer[:2])
        except OSError:
            pass

        if err:
            with self._lock:
                self._fb_queues.pop(sid, None)
            return

        prio_bytes = json.dumps(
            {"matched": matched, "preview": preview}, ensure_ascii=False
        ).encode("utf-8")
        loss_hint = float(req.get("est_loss", 0.02))
        dst = (ctrl_peer[0], reply_port)
        try:
            HyperWireSender(dst, initial_loss_hint=loss_hint).send_stream(
                wire_payload,
                stream_id=sid,
                priority_frame=prio_bytes,
                timeout_s=20.0,
                send_fn=lambda b, d: self._sock.sendto(b, d),
                feedback_queue=fb_q,
            )
        except Exception:
            pass
        finally:
            with self._lock:
                self._fb_queues.pop(sid, None)

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=1.0)
        try:
            self._sock.close()
        except OSError:
            pass


def remote_active_query(
    target_addr: tuple[str, int],
    file_path: str,
    plan: ComputePlan,
    est_loss: float = 0.02,
    timeout_s: float = 15.0,
    telepathy_store: TelepathicStore | None = None,
    domain_dict: DomainDictionary | None = None,
) -> tuple[ActivePipeResult, dict[str, Any]]:
    """Run an Active / Fluid Compute-in-Transit query with Telepathic decode over UDP."""
    t0 = time.perf_counter()
    fam = _family_for_ip(target_addr[0])
    bind_ip = "::" if fam == socket.AF_INET6 else "0.0.0.0"

    preview_ts: list[float] = []
    preview_items: list[list[str]] = []

    def on_prio(frame: bytes, ts: float) -> None:
        if not preview_ts:
            preview_ts.append((ts - t0) * 1000.0)
        try:
            obj = json.loads(frame.decode("utf-8"))
            preview_items.append(obj.get("preview", []))
        except Exception:
            pass

    rx = HyperWireReceiver(bind_ip=bind_ip, bind_port=0, on_priority_frame=on_prio).start()
    ctrl = socket.socket(fam, socket.SOCK_DGRAM)
    _disable_connreset(ctrl)
    ctrl.bind(_bind_any(fam))
    ctrl.settimeout(1.5)
    dict_id = plan.dict_id or (domain_dict.dict_id if domain_dict else "")
    try:
        req_payload = b"AQ02" + struct.pack("<H", rx.addr[1]) + json.dumps(
            {
                "file_path": file_path,
                "op": plan.op,
                "needle": plan.needle,
                "where_key": plan.where_key,
                "where_eq": plan.where_eq,
                "project_fields": list(plan.project_fields),
                "group_col": plan.group_col,
                "value_col": plan.value_col,
                "patterns": list(plan.patterns),
                "match_mode": plan.match_mode,
                "regex": plan.regex,
                "ignore_case": plan.ignore_case,
                "file_glob": plan.file_glob,
                "sql": plan.sql,
                "max_rows": plan.max_rows,
                "use_telepathy": plan.use_telepathy,
                "dict_id": dict_id,
                "est_loss": est_loss,
            },
            ensure_ascii=False,
        ).encode("utf-8")

        meta: dict[str, Any] | None = None
        for _ in range(4):
            rx.punch(target_addr)
            ctrl.sendto(req_payload, target_addr)
            try:
                resp, _ = ctrl.recvfrom(8192)
                if resp.startswith(b"QAK1"):
                    meta = json.loads(resp[4:].decode("utf-8"))
                    break
            except socket.timeout:
                continue

        if meta is None:
            raise TimeoutError(f"ActiveQueryServer unreachable at {target_addr}")
        if meta.get("error"):
            raise RuntimeError(f"Remote ActiveQueryServer error: {meta['error']}")

        sid = int(meta["stream_id"])
        raw_bytes = int(meta["raw_bytes"])
        matched = int(meta["matched"])
        delivered_raw, gfni_solves = rx.wait_stream(sid, timeout_s=timeout_s)
        rx_wire = rx.pop_stream_wire_bytes(sid)
        decoded = TelepathicCodec().decode(
            delivered_raw, store=telepathy_store, domain_dict=domain_dict
        )
        total_ms = (time.perf_counter() - t0) * 1000.0
        wire_bytes = rx_wire if rx_wire > 0 else len(delivered_raw)
        red_pct = (
            max(0.0, 100.0 * (1.0 - wire_bytes / raw_bytes)) if raw_bytes > 0 else 0.0
        )
        res = ActivePipeResult(
            op=plan.op,
            executed_at="remote_sender",
            raw_bytes=raw_bytes,
            wire_bytes=wire_bytes,
            wire_reduction_pct=round(red_pct, 2),
            matched_records=matched,
            preview_items=preview_items[0] if preview_items else [],
            preview_first_ms=round(preview_ts[0], 2) if preview_ts else None,
            total_ms=round(total_ms, 2),
            output_bytes=decoded,
        )
        return res, {
            "stream_id": sid,
            "server_exec_ms": meta.get("server_exec_ms", 0.0),
            "gfni_solves": gfni_solves,
            "codec_mode": meta.get("codec_mode", "raw"),
            "dict_id": meta.get("dict_id", ""),
            "uncompressed_output_bytes": meta.get("uncompressed_bytes", len(decoded)),
            "compressed_payload_bytes": meta.get("compressed_bytes", len(delivered_raw)),
            "plain_zlib_bytes": meta.get("plain_zlib_bytes", len(decoded)),
        }
    finally:
        ctrl.close()
        rx.close()
