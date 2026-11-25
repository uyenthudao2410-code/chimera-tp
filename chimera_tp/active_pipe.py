"""Breakthrough #4: Active Compute-in-Transit Operators, Auto-Placement & Remote Query Server."""

from __future__ import annotations

import json
import queue
import socket
import struct
import threading
import time
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
from .native import active_filter_lines

ComputeOp = Literal["filter_lines", "json_filter_project", "csv_group_sum"]


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

    raise ValueError(f"Unsupported active compute operator: {plan.op}")


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
    """Single-port symmetric UDP server executing Active Compute-in-Transit on local files."""

    def __init__(
        self,
        bind_ip: str = "0.0.0.0",
        bind_port: int = 0,
        allowed_roots: list[Path] | None = None,
    ) -> None:
        self.allowed_roots = [Path(p).resolve() for p in (allowed_roots or [])]
        self._sock = socket.socket(_family_for_ip(bind_ip), socket.SOCK_DGRAM)
        _disable_connreset(self._sock)
        try:
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4 * 1024 * 1024)
        except OSError:
            pass
        self._sock.bind((bind_ip, bind_port))
        self._sock.settimeout(0.05)
        self.addr: tuple[str, int] = self._sock.getsockname()[:2]
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._fb_queues: dict[int, queue.Queue[bytes]] = {}
        self._next_stream = 1
        self._thread = threading.Thread(target=self._serve_loop, daemon=True)

    def start(self) -> "ActiveQueryServer":
        self._thread.start()
        return self

    def _load_target_bytes(self, file_path: str) -> bytes:
        if file_path == "@synthetic":
            return make_synthetic_logs(2 * 1024 * 1024)
        candidate = Path(file_path).resolve()
        if not self.allowed_roots:
            raise PermissionError("Remote file queries disabled (no allowed_roots configured)")
        if not any(candidate == r or r in candidate.parents for r in self.allowed_roots):
            raise PermissionError(f"Path outside allowed_roots: {candidate}")
        if not candidate.is_file():
            raise FileNotFoundError(f"Query target not found: {candidate}")
        return candidate.read_bytes()

    def _serve_loop(self) -> None:
        while not self._stop.is_set():
            try:
                pkt, addr = self._sock.recvfrom(65535)
            except (socket.timeout, ConnectionResetError):
                continue
            except OSError:
                break

            if pkt.startswith(b"AQ01") and len(pkt) >= 6:
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
        try:
            raw = self._load_target_bytes(str(req.get("file_path", "@synthetic")))
            plan = ComputePlan(
                op=req.get("op", "filter_lines"),
                needle=str(req.get("needle", "")),
                where_key=str(req.get("where_key", "")),
                where_eq=str(req.get("where_eq", "")),
                project_fields=tuple(req.get("project_fields", [])),
                group_col=int(req.get("group_col", 0)),
                value_col=int(req.get("value_col", 1)),
                placement="sender",
            )
            computed, matched, preview = execute_operator(raw, plan)
            err = ""
        except Exception as exc:
            raw = b""
            computed = b""
            matched = 0
            preview = []
            err = str(exc)

        exec_ms = (time.perf_counter() - t0) * 1000.0
        ack = b"QAK1" + json.dumps(
            {
                "stream_id": sid,
                "raw_bytes": len(raw),
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
                computed,
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
) -> tuple[ActivePipeResult, dict[str, Any]]:
    """Run an Active Compute-in-Transit query on a remote ActiveQueryServer over single-port UDP."""
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
    try:
        req_payload = b"AQ01" + struct.pack("<H", rx.addr[1]) + json.dumps(
            {
                "file_path": file_path,
                "op": plan.op,
                "needle": plan.needle,
                "where_key": plan.where_key,
                "where_eq": plan.where_eq,
                "project_fields": list(plan.project_fields),
                "group_col": plan.group_col,
                "value_col": plan.value_col,
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
        delivered, gfni_solves = rx.wait_stream(sid, timeout_s=timeout_s)
        total_ms = (time.perf_counter() - t0) * 1000.0
        wire_bytes = max(len(delivered), int(len(delivered) * 1.04))
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
            output_bytes=delivered,
        )
        return res, {
            "stream_id": sid,
            "server_exec_ms": meta.get("server_exec_ms", 0.0),
            "gfni_solves": gfni_solves,
        }
    finally:
        ctrl.close()
        rx.close()
