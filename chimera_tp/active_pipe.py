"""Breakthrough #4: Active Compute-in-Transit Streaming Operators & Auto-Placement."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from typing import Any, Literal

from .hyper_wire import HyperWireReceiver, HyperWireSender
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
    # Even over 1 Gbps LAN, pushing down 90% of junk beats shipping raw bytes across TCP
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
            if fields:
                proj = {k: obj.get(k) for k in fields}
            else:
                proj = obj
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
        rows_seen = 0
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
            rows_seen += 1
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
                rep = sender.send_stream(
                    raw_data, stream_id=stream_id, timeout_s=timeout_s
                )
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
