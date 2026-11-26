"""CHIMERA-MCP: Zero-dependency stdio JSON-RPC 2.0 MCP server so AI coding agents auto-discover CHIMERA."""

from __future__ import annotations

import json
import sys
from typing import Any

from .client import connect


_TOOLS = [
    {
        "name": "chimera_capabilities",
        "description": "Discover the live CHIMERA-TP local infrastructure substrate: anchor URL, Egress-Membrane proxy, active cartridges, peer topology, and Zero-Weight RAM.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "chimera_apps",
        "description": "List all linked & online applications attached to CHIMERA-TP plus newly discovered unlinked local server ports.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "chimera_pulse_publish",
        "description": "Publish a real-time event onto CHIMERA-PULSE (shared cross-host event bus between win-desktop and svhome).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "Dot-delimited topic name, e.g. 'radar.alert'"},
                "payload": {"type": "object", "description": "JSON event payload"},
            },
            "required": ["topic", "payload"],
        },
    },
    {
        "name": "chimera_search",
        "description": "Run sub-3ms hybrid AVX2 VSA + BM25 search across a project namespace in CHIMERA-SEARCH.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "namespace": {"type": "string", "description": "App/project namespace"},
                "query": {"type": "string", "description": "Search query"},
                "top_k": {"type": "integer", "description": "Max results (default 10)"},
            },
            "required": ["namespace", "query"],
        },
    },
    {
        "name": "chimera_blackbox_freeze",
        "description": "Freeze the last 60s of dual-node Flight Recorder BlackBox telemetry to disk for post-mortem debugging.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "reason": {"type": "string", "description": "Short reason for freezing the flight recorder"},
            },
            "required": [],
        },
    },
    {
        "name": "chimera_vgpu_route",
        "description": "Query the CHIMERA-VGPU Pareto router (Windows GTX 1650 vs svhome CPU vs Cloud API) for optimal cost/latency placement.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "max_ms": {"type": "number"},
                "max_cost_usd": {"type": "number"},
                "min_tier": {"type": "string"},
            },
            "required": [],
        },
    },
    {
        "name": "chimera_job_resume",
        "description": "Inspect or resume a durable CHIMERA-IMMORTAL-JOB workflow checkpoint by job_id.",
        "inputSchema": {
            "type": "object",
            "properties": {"job_id": {"type": "string"}},
            "required": ["job_id"],
        },
    },
    {
        "name": "chimera_canary_compare",
        "description": "Run Zero-Downtime Canary Twin comparison between baseline_url and canary_url for automated PROMOTE/ROLLBACK verdict.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "baseline_url": {"type": "string"},
                "canary_url": {"type": "string"},
                "samples": {"type": "integer"},
            },
            "required": ["baseline_url", "canary_url"],
        },
    },
]


def handle_mcp_request(msg: dict[str, Any], anchor_url: str | None = None) -> dict[str, Any] | None:
    method = str(msg.get("method") or "")
    req_id = msg.get("id")
    params = msg.get("params") or {}

    if method == "notifications/initialized":
        return None

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "chimera-mcp", "version": "16.0.0"},
            },
        }

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": _TOOLS}}

    if method == "tools/call":
        tname = str(params.get("name") or "")
        args = params.get("arguments") or {}
        client = connect(app="chimera-mcp", anchor_url=anchor_url, auto_register=False)
        try:
            if tname == "chimera_capabilities":
                out = client.capabilities()
            elif tname == "chimera_apps":
                out = client._get_json("/v1/apps/list") if client.available else {"available": False, "apps": []}
            elif tname == "chimera_pulse_publish":
                out = client.pulse_publish(str(args.get("topic", "mcp.event")), args.get("payload", {}))
            elif tname == "chimera_search":
                out = client.search(
                    query=str(args.get("query", "")),
                    namespace=str(args.get("namespace", "global")),
                    top_k=int(args.get("top_k", 10)),
                )
            elif tname == "chimera_blackbox_freeze":
                out = client.freeze_blackbox(reason=str(args.get("reason", "mcp_freeze")))
            elif tname == "chimera_vgpu_route":
                out = client.pareto_route(
                    max_ms=float(args.get("max_ms", 500.0)),
                    max_cost_usd=float(args.get("max_cost_usd", 0.0)),
                    min_tier=str(args.get("min_tier", "standard")),
                )
            elif tname == "chimera_job_resume":
                out = client.job_resume(str(args.get("job_id", "")))
            elif tname == "chimera_canary_compare":
                out = client.canary_compare(
                    baseline_url=str(args.get("baseline_url", "")),
                    canary_url=str(args.get("canary_url", "")),
                    samples=int(args.get("samples", 5)),
                )
            else:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32601, "message": f"Unknown tool: {tname}"},
                }
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": json.dumps(out, indent=2, ensure_ascii=False)}],
                },
            }
        except Exception as exc:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "isError": True,
                    "content": [{"type": "text", "text": json.dumps({"error": str(exc)})}],
                },
            }

    if req_id is None:
        return None
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def serve_mcp_stdio(anchor_url: str | None = None) -> int:
    """Run line-delimited JSON-RPC 2.0 MCP server on stdin/stdout."""
    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception:
            continue
        resp = handle_mcp_request(msg, anchor_url=anchor_url)
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()
    return 0
