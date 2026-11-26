"""Command-line interface for CHIMERA-HYPER v5.0 (plus v1.0-v4.0 and v0.5.0 exotic modes)."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import sys
import time
import urllib.request
from pathlib import Path

from .active_pipe import ActivePipeEngine, ComputePlan, remote_active_query
from .autopilot import OpsConfig, TelemetryStore, default_ops_dir, run_daily_autopilot
from .code_search import CodeSearchIndex
from .dashboard import ChimeraDaemon
from .edge_proxy import LocalEdgeProxy
from .fabric import BeamServer, ChimeraFabric, beam_send
from .holo_backup import create_holo_backup, list_holo_backups, restore_holo_backup
from .merkle_sync import merkle_beam_sync
from .nat_buster import attempt_direct_punch, discover_nat_profile
from .native import WormholeChannel
from .probe import probe_environment
from .protocol import ChimeraReceiver, ChimeraSender, FaultProfile
from .sentinel import SentinelEngine
from .telepathy import TelepathicStore, benchmark_compression, train_domain_dictionary
from .warp import WarpClient, WarpServer


def _configure_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except OSError:
                pass


def _parse_host_port(spec: str) -> tuple[str, int]:
    if ":" not in spec:
        raise ValueError(f"Expected HOST:PORT endpoint, got: {spec}")
    host, port_str = spec.rsplit(":", 1)
    host = host.strip("[]") or "127.0.0.1"
    return host, int(port_str)


def _atomic_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def _add_send_options(p: argparse.ArgumentParser) -> None:
    src_group = p.add_mutually_exclusive_group(required=True)
    src_group.add_argument("--text", help="UTF-8 string payload to transmit")
    src_group.add_argument("--file", help="Path to binary/text file to transmit")
    p.add_argument(
        "--mode",
        choices=("metamorphic", "holographic"),
        default="metamorphic",
        help="Transport mode",
    )
    p.add_argument(
        "--exotic",
        action="store_true",
        help="Explicitly acknowledge exotic 8-realm research channels (default behavior for send/connect)",
    )
    p.add_argument(
        "--kill",
        default="",
        help="Comma-separated lane IDs to disable (e.g. GHOST_127,WSL_PERMUTE)",
    )
    p.add_argument(
        "--drop",
        type=float,
        default=0.0,
        help="Injected droplet drop rate in [0.0, 0.9]",
    )
    p.add_argument(
        "--jumbo-drop",
        type=float,
        default=0.0,
        help="Injected ::1 jumbo chunk drop rate in [0.0, 0.9]",
    )
    p.add_argument(
        "--corrupt-lan",
        action="store_true",
        help="Invert all random noise payload bytes on LAN_LENGTH",
    )
    p.add_argument(
        "--profile",
        choices=("balanced", "stealth", "turbo"),
        default="balanced",
        help="Chaos scheduler profile",
    )
    p.add_argument(
        "--sequential",
        action="store_true",
        help="Disable per-lane parallel TX workers",
    )


def main(argv: list[str] | None = None) -> int:
    _configure_utf8()
    parser = argparse.ArgumentParser(
        prog="chimera-tp",
        description="CHIMERA-HYPER v5.0: PHANTOM-5MS Tunnel + Ghost-PTY + Ghost-FS + Medic + Drop-Portal",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # ---- Daily Work Subcommands (CHIMERA-HYPER v1.0) ----
    p_beam = sub.add_parser("beam", help="Zero-Byte DNA Vault + GFNI Wire file/directory sync")
    beam_sub = p_beam.add_subparsers(dest="beam_action", required=True)

    p_b_serve = beam_sub.add_parser("serve", help="Run Beam receiver")
    p_b_serve.add_argument("--bind", default="127.0.0.1:0", help="UDP bind HOST:PORT")
    p_b_serve.add_argument("--out-dir", required=True, help="Directory to write synced files")
    p_b_serve.add_argument("--vault", default="", help="Optional persistent DNA vault directory")
    p_b_serve.add_argument("--port-file", default="", help="Write bound port JSON atomically here")
    p_b_serve.add_argument("--max-transfers", type=int, default=1, help="Exit after N transfers (0=forever)")
    p_b_serve.add_argument("--est-loss", type=float, default=0.0, help="Initial loss hint [0..0.5]")
    p_b_serve.add_argument("--timeout", type=float, default=60.0, help="Seconds per transfer")

    p_b_send = beam_sub.add_parser("send", help="Sync a file or directory to a Beam server")
    p_b_send.add_argument("--target", required=True, help="Target HOST:PORT (or @port-file path)")
    b_src = p_b_send.add_mutually_exclusive_group(required=True)
    b_src.add_argument("--dir", help="Directory to sync")
    b_src.add_argument("--file", help="Single file to sync")
    p_b_send.add_argument("--vault", default="", help="Optional persistent sender DNA vault directory")
    p_b_send.add_argument("--est-loss", type=float, default=0.0, help="Initial loss hint [0..0.5]")
    p_b_send.add_argument("--pace-mbps", type=float, default=0.0, help="Optional pacing cap in Mbps")
    p_b_send.add_argument("--timeout", type=float, default=60.0, help="Timeout seconds")

    p_warp = sub.add_parser("warp", help="Drop-in TCP accelerator over Silicon GFNI Wire")
    warp_sub = p_warp.add_subparsers(dest="warp_action", required=True)
    p_w_srv = warp_sub.add_parser("server", help="Run Warp UDP-to-TCP server")
    p_w_srv.add_argument("--bind", required=True, help="UDP bind HOST:PORT")
    p_w_srv.add_argument("--forward", required=True, help="Target TCP HOST:PORT")
    p_w_srv.add_argument("--est-loss", type=float, default=0.0, help="FEC loss ratio hint")
    p_w_cli = warp_sub.add_parser("client", help="Run Warp TCP-to-UDP local proxy")
    p_w_cli.add_argument("--listen", required=True, help="Local TCP listen HOST:PORT")
    p_w_cli.add_argument("--target", required=True, help="Remote WarpServer UDP HOST:PORT")
    p_w_cli.add_argument("--est-loss", type=float, default=0.05, help="FEC loss ratio hint")

    p_pipe = sub.add_parser("pipe", help="Shared-Memory Wormhole IPC & Active Compute-in-Transit")
    pipe_sub = p_pipe.add_subparsers(dest="pipe_action", required=True)
    p_p_wh = pipe_sub.add_parser("wormhole", help="Stream data through Lock-Free Windows Shared Memory")
    wh_mode = p_p_wh.add_mutually_exclusive_group(required=True)
    wh_mode.add_argument("--create", help="Create named shared-memory wormhole and write payload")
    wh_mode.add_argument("--open", help="Open named shared-memory wormhole and read payload")
    p_p_wh.add_argument("--file", default="", help="Input file (--create) or output file (--open)")
    p_p_wh.add_argument("--text", default="", help="Inline UTF-8 text (--create)")
    p_p_wh.add_argument("--cap-mb", type=int, default=8, help="Ring buffer capacity in MiB")

    p_p_q = pipe_sub.add_parser("query", help="Run Active Compute-in-Transit operator over a file")
    p_p_q.add_argument("--file", required=True, help="Input text/NDJSON/CSV file")
    p_p_q.add_argument(
        "--op",
        choices=("filter_lines", "json_filter_project", "csv_group_sum"),
        required=True,
    )
    p_p_q.add_argument("--needle", default="", help="Substring filter for filter_lines")
    p_p_q.add_argument("--where-key", default="", help="JSON filter key")
    p_p_q.add_argument("--where-eq", default="", help="JSON filter exact value")
    p_p_q.add_argument("--fields", default="", help="Comma-separated JSON projection fields")
    p_p_q.add_argument("--group-col", type=int, default=0, help="CSV group column index")
    p_p_q.add_argument("--value-col", type=int, default=1, help="CSV sum value column index")
    p_p_q.add_argument("--placement", choices=("auto", "sender", "receiver"), default="auto")
    p_p_q.add_argument("--out-file", default="", help="Optional output file")

    p_bh = sub.add_parser("bench-hyper", help="Run CHIMERA-HYPER v1.0 Before-vs-After benchmark suite")
    p_bh.add_argument("--out", default="chimera_hyper_eval.json", help="Output JSON path")

    p_init = sub.add_parser("ops-init", help="Initialize ~/.chimera_ops/config.json for 24/7 operation")
    p_init.add_argument("--ops-dir", default="", help="Override ops directory (default ~/.chimera_ops)")
    p_init.add_argument("--node-name", default="", help="Logical node name")
    p_init.add_argument("--role", choices=("controller", "server"), default="controller")
    p_init.add_argument("--bind", default="127.0.0.1:9780", help="Dashboard HTTP HOST:PORT")
    p_init.add_argument("--peer-name", default="", help="Peer hostname/label")
    p_init.add_argument("--peer-ipv4", default="", help="Peer IPv4 (Tailscale/LAN)")
    p_init.add_argument("--peer-ipv6", default="", help="Peer IPv6 (Tailscale)")
    p_init.add_argument("--watched-file", default="@synthetic", help="Remote/local log file for Active Pipe")
    p_init.add_argument("--allow-root", action="append", default=[], help="Allowed root directories for ActiveQueryServer")
    p_init.add_argument("--daily-time", default="08:00", help="Daily HH:MM local time")
    p_init.add_argument("--profile", default="auto-darwin", choices=("auto-darwin", "max-speed", "lossy-armor", "exotic-v05"))

    p_daemon = sub.add_parser("daemon", help="Run 24/7 Mission-Control Dashboard & UDP accelerator services")
    p_daemon.add_argument("--ops-dir", default="", help="Override ops directory")
    p_daemon.add_argument("--bind", default="", help="Override dashboard HOST:PORT")
    p_daemon.add_argument("--no-seed", action="store_true", help="Skip startup baseline run when telemetry DB is empty")

    p_auto = sub.add_parser("autopilot", help="Run one daily health + Before-vs-After + Darwinian UCB1 cycle")
    p_auto.add_argument("--ops-dir", default="", help="Override ops directory")
    p_auto.add_argument("--trigger", default="manual", help="Run trigger tag (daily/manual/startup)")

    p_ms = sub.add_parser("merkle-sync", help="0-RTT Merkle hash check and sparse directory DNA sync")
    p_ms.add_argument("--dir", required=True, help="Local directory to synchronize")
    p_ms.add_argument("--ws", default="default", help="Workspace identifier on peer")
    p_ms.add_argument("--peer-http", required=True, help="Peer dashboard HTTP base URL")
    p_ms.add_argument("--peer-beam", required=True, help="Peer BeamServer HOST:PORT")
    p_ms.add_argument("--ops-dir", default="", help="Override ops directory")
    p_ms.add_argument("--est-loss", type=float, default=0.02, help="Estimated UDP loss hint")

    p_fl = sub.add_parser("fluid", help="Execute remote Fluid Compute operator on peer near disk")
    p_fl.add_argument("--peer-query", required=True, help="Peer ActiveQueryServer HOST:PORT")
    p_fl.add_argument("--path", required=True, help="Remote file, directory, or SQLite DB path")
    p_fl.add_argument(
        "--op",
        choices=("log_analytics", "filter_lines", "multi_grep", "sqlite_query", "remote_digest"),
        default="log_analytics",
        help="Fluid pushdown operator name",
    )
    p_fl.add_argument("--needle", default="ERROR", help="Filter substring or pattern")
    p_fl.add_argument("--sql", default="", help="Read-only SQL SELECT/WITH query")
    p_fl.add_argument("--no-telepathy", action="store_true", help="Disable Telepathic dict compression")

    p_tb = sub.add_parser("telepathy-bench", help="Benchmark Telepathic dictionary vs raw and plain zlib")
    p_tb.add_argument("--file", required=True, help="Sample log, code, or JSON file")

    # ---- CHIMERA-HYPER v4.0 HyperOS Subcommands ----
    p_nat = sub.add_parser("nat-bust", help="STUN NAT profile and Birthday-Paradox P2P UDP punch")
    p_nat.add_argument("--peer-http", default="", help="Peer HTTP base URL")
    p_nat.add_argument("--sockets", type=int, default=192, help="UDP sockets to open during punch")
    p_nat.add_argument("--spray", type=int, default=900, help="Candidate port spray count on responder")
    p_nat.add_argument("--profile-only", action="store_true", help="Only inspect local STUN NAT profile")
    p_nat.add_argument("--local-test", action="store_true", help="Run loopback punch test")

    p_ep = sub.add_parser("edge-proxy", help="Run Zero-Weight local HTTP Warp-Edge Proxy with 0-RTT prefetch")
    p_ep.add_argument("--listen", default="127.0.0.1:9788", help="Local HTTP listen HOST:PORT")
    p_ep.add_argument("--peer-http", required=True, help="Peer CHIMERA EdgeGateway base URL")

    p_sent = sub.add_parser("sentinel", help="Run CHIMERA-SENTINEL health and log spike monitor")
    p_sent.add_argument("--ops-dir", default="", help="Override ops directory")
    p_sent.add_argument("--scan", action="store_true", help="Execute a fresh Sentinel scan now")

    p_srch = sub.add_parser("search", help="Zero-download SQLite FTS5 BM25 code and log search")
    p_srch.add_argument("query", nargs="?", default="", help="Search terms")
    p_srch.add_argument("--reindex", action="store_true", help="Incrementally update index via Merkle stat cache")
    p_srch.add_argument("--root", action="append", default=[], help="Root directories to index locally")
    p_srch.add_argument("--peer-http", default="", help="Remote CHIMERA HTTP base URL")
    p_srch.add_argument("--repo", default="", help="Optional repo filter")
    p_srch.add_argument("--limit", type=int, default=10, help="Maximum search hits")
    p_srch.add_argument("--ops-dir", default="", help="Override ops directory")

    p_hb = sub.add_parser("holo-backup", help="Holographic GF(256) (K=2, N=3) secret-shared backup")
    p_hb.add_argument("action", choices=("create", "restore", "list"), help="Backup operation")
    p_hb.add_argument("--path", action="append", default=[], help="Source file or directory for create")
    p_hb.add_argument("--shard", action="append", default=[], help="Shard file path (need 2) for restore")
    p_hb.add_argument("--out-dir", default="", help="Restore output directory")
    p_hb.add_argument("--backup-id", default="", help="Optional backup identifier")
    p_hb.add_argument("--peer-http", default="", help="Optional peer HTTP URL to sync Shard 1")
    p_hb.add_argument("--ops-dir", default="", help="Override ops directory")

    # ---- CHIMERA-HYPER v5.0 PHANTOM-5MS Subcommands ----
    p_ph = sub.add_parser("phantom", help="Check or connect PHANTOM-5MS persistent P2P tunnel via daemon")
    p_ph.add_argument("action", choices=("status", "connect", "disconnect"), help="Tunnel control action")
    p_ph.add_argument("--daemon-http", default="http://127.0.0.1:9780", help="Local daemon HTTP URL")

    p_pty = sub.add_parser("pty", help="Interact with persistent Ghost-PTY sessions via HTTP")
    p_pty.add_argument("action", choices=("create", "list", "exec", "close"), help="PTY action")
    p_pty.add_argument("--peer-http", default="http://127.0.0.1:9780", help="Target daemon HTTP URL")
    p_pty.add_argument("--sid", default="", help="PTY session id")
    p_pty.add_argument("--cmd", default="", help="Shell command for exec")

    p_fs = sub.add_parser("fs", help="Inspect Ghost-FS files or git status remotely")
    p_fs.add_argument("action", choices=("ls", "cat", "git"), help="Ghost-FS action")
    p_fs.add_argument("--path", default="", help="Relative file or repo path")
    p_fs.add_argument("--peer-http", default="http://127.0.0.1:9780", help="Target daemon HTTP URL")

    p_med = sub.add_parser("medic", help="CHIMERA-MEDIC forensic triage and safe playbook runner")
    p_med.add_argument("action", choices=("status", "investigate", "heal"), help="Medic action")
    p_med.add_argument("--playbook", default="probe_services", help="Allowlisted playbook ID")
    p_med.add_argument("--pattern", default="ERROR", help="Error pattern for diagnose")
    p_med.add_argument("--file-path", default="", help="Target file or repo path")
    p_med.add_argument("--dry-run", action="store_true", help="Run playbook in dry-run mode")
    p_med.add_argument("--peer-http", default="http://127.0.0.1:9780", help="Target daemon HTTP URL")

    p_dp = sub.add_parser("drop", help="Send or list ephemeral Zero-Cloud Drop-Portal items")
    p_dp.add_argument("action", choices=("put", "list", "get"), help="Drop action")
    p_dp.add_argument("--title", default="clip", help="Drop item title")
    p_dp.add_argument("--text", default="", help="UTF-8 text snippet to drop")
    p_dp.add_argument("--file", default="", help="File path to drop")
    p_dp.add_argument("--item-id", default="", help="Item id for get")
    p_dp.add_argument("--peer-http", default="http://127.0.0.1:9780", help="Target daemon HTTP URL")

    p_ctx = sub.add_parser("context-pack", help="Build compact Markdown AI Context Pack from FTS5 + Sentinel")
    p_ctx.add_argument("query", help="Symptom, symbol, or issue query")
    p_ctx.add_argument("--repo", default="", help="Optional repo filter")
    p_ctx.add_argument("--peer-http", default="http://127.0.0.1:9780", help="Target daemon HTTP URL")

    # ---- CHIMERA-HYPER v6.0 APEX-SYNERGY Subcommands ----
    p_syn = sub.add_parser("synergy", help="Radar and Tqouta fusion status, surgical briefs, burn scan, and vault")
    p_syn.add_argument("action", choices=("status", "bounties", "burn-scan", "brief", "vault-backup"), help="Synergy action")
    p_syn.add_argument("--workspace-dir", default="", help="Target Radar workspace directory for brief")
    p_syn.add_argument("--title", default="", help="Issue title for surgical brief")
    p_syn.add_argument("--inject", action="store_true", help="Inject surgical map into AGENT_SOLVER_BRIEF.md")
    p_syn.add_argument("--peer-http", default="http://127.0.0.1:9780", help="Target daemon HTTP URL")

    # ---- CHIMERA-HYPER v7.0 OMEGA-FABRIC Subcommands ----
    p_om = sub.add_parser("omega", help="OMEGA-FABRIC 14-idea status, benchmark, PPM codec, WASM sandbox, Slepian-Wolf, and regen vault")
    p_om.add_argument("action", choices=("status", "bench", "ppm", "wasm", "slepian", "regen"), help="Omega action")
    p_om.add_argument("--input", default="", help="Input text for ppm, wasm, or slepian action")
    p_om.add_argument("--peer-http", default="http://127.0.0.1:9780", help="Target daemon HTTP URL")
    p_om.add_argument("--local", action="store_true", help="Run action offline instead of querying daemon")

    # ---- CHIMERA-HYPER v8.0 SINGULARITY Subcommands ----
    p_sg = sub.add_parser("singularity", help="SINGULARITY 7-idea status, adversarial bench, PIR, Kolmogorov codec, CRDT, airgap, dual vault, and swarm")
    p_sg.add_argument("action", choices=("status", "bench", "pir", "kolmogorov", "crdt", "airgap", "dual-vault", "swarm"), help="Singularity action")
    p_sg.add_argument("--input", default="", help="Optional input text for Kolmogorov codec test")
    p_sg.add_argument("--peer-http", default="http://127.0.0.1:9780", help="Target daemon HTTP URL")
    p_sg.add_argument("--local", action="store_true", help="Run action offline instead of querying daemon")

    # ---- CHIMERA-HYPER v9.0 HYPERDRIVE Subcommands ----
    p_hd = sub.add_parser("hyperdrive", help="HYPERDRIVE v9.0 6-idea status, bench, search, grid, nvme, stream, fusion, and hub")
    p_hd.add_argument("action", choices=("status", "bench", "dataplane", "nvme", "grid", "fusion", "stream", "search", "hub"), help="Hyperdrive action")
    p_hd.add_argument("--query", default="PhantomTunnel", help="Search query or hub message")
    p_hd.add_argument("--peer-http", default="http://127.0.0.1:9780", help="Target daemon HTTP URL")
    p_hd.add_argument("--local", action="store_true", help="Run action offline instead of querying daemon")

    # ---- CHIMERA-HYPER v12.0 OMEGA-GALACTIC Subcommands (Wave 2-4 / 29 Ideas) ----
    p_gl = sub.add_parser("galactic", help="OMEGA-GALACTIC v10-v12 29-idea status, bench, frost, teleport, tarpit, babel, immune, vsa, bennett, slp")
    p_gl.add_argument(
        "action",
        choices=("status", "bench", "frost", "teleport", "tarpit", "babel", "immune", "vsa", "bennett", "slp"),
        help="Galactic action",
    )
    p_gl.add_argument("--wave", default="all", choices=("all", "v10", "v11", "v12"), help="Wave filter for galactic bench")
    p_gl.add_argument("--path", default="/env/prod/vault_keys.yml", help="Synthetic path for stateless tarpit inspection")
    p_gl.add_argument("--peer-http", default="http://127.0.0.1:9780", help="Target daemon HTTP URL")
    p_gl.add_argument("--local", action="store_true", help="Run action offline instead of querying daemon")

    # ---- CHIMERA-CONNECT v16.0 Open Platform Substrate Subcommands ----
    p_smi = sub.add_parser("smi", help="nvidia-smi style overview of CHIMERA Anchor, Cartridges, Egress-Membrane & Linked Apps")
    p_smi.add_argument("--anchor", default="", help="Override CHIMERA anchor URL (default: auto-discover runtime.json)")
    p_smi.add_argument("--json", action="store_true", help="Output raw JSON telemetry")

    p_link = sub.add_parser("link", help="Link an existing project to CHIMERA-CONNECT (generates chimera.manifest.json + auto-attach)")
    p_link.add_argument("path", nargs="?", default=".", help="Project directory to link")
    p_link.add_argument("--app", default="", help="Override application name")
    p_link.add_argument("--port", type=int, default=0, help="Optional service port")
    p_link.add_argument("--qos", default="interactive", choices=("realtime", "interactive", "batch", "scavenger"), help="QoS class")

    p_init = sub.add_parser("init", help="Initialize a new project with chimera.manifest.json + zero-lock-in chimera_bridge.py")
    p_init.add_argument("path", nargs="?", default=".", help="Project directory")
    p_init.add_argument("--app", default="", help="Application name")
    p_init.add_argument("--port", type=int, default=0, help="Optional service port")
    p_init.add_argument("--no-bridge", action="store_true", help="Skip generating chimera_bridge.py")

    p_run = sub.add_parser("run", help="Run any command inside CHIMERA-CONNECT (zero-code proxy, env & live registration)")
    p_run.add_argument("--app", default="", help="Application name (default: current directory name)")
    p_run.add_argument("--port", type=int, default=0, help="Optional service port")
    p_run.add_argument("--qos", default="interactive", help="QoS priority class")
    p_run.add_argument("--no-proxy", action="store_true", help="Do not inject HTTP_PROXY/HTTPS_PROXY")
    p_run.add_argument("cmd", nargs=argparse.REMAINDER, help="Command to execute (prefix with --)")

    p_al = sub.add_parser("autoload", help="Install/remove/check zero-code Python chimera_autoload.pth hook")
    p_al.add_argument("action", choices=("install", "uninstall", "status"), help="Autoload action")

    p_mcp = sub.add_parser("mcp", help="Run stdio JSON-RPC 2.0 CHIMERA-MCP server for AI coding agents")
    p_mcp.add_argument("--anchor", default="", help="Override CHIMERA anchor URL")

    p_cart = sub.add_parser("cartridge", help="List, enable, or disable hot-loadable CHIMERA Cartridges")
    p_cart.add_argument("action", choices=("list", "enable", "disable"), help="Cartridge action")
    p_cart.add_argument("name", nargs="?", default="", help="Cartridge name (for enable/disable)")
    p_cart.add_argument("--anchor", default="", help="Override CHIMERA anchor URL")

    p_can = sub.add_parser("canary", help="Run Zero-Downtime Canary Twin comparison between baseline and canary URLs")
    p_can.add_argument("baseline_url", help="Current live baseline URL")
    p_can.add_argument("canary_url", help="New candidate canary URL")
    p_can.add_argument("--paths", default="/", help="Comma-separated paths to compare")
    p_can.add_argument("--samples", type=int, default=5, help="Number of paired samples")
    p_can.add_argument("--anchor", default="", help="Override CHIMERA anchor URL")

    p_sd = sub.add_parser("attach-systemd", help="Install non-destructive systemd user drop-in for Python (.venv) or Node service")
    p_sd.add_argument("unit", help="systemd user unit name (e.g. radar-dashboard.service or tquota.service)")
    p_sd.add_argument("--app", required=True, help="Application name")
    p_sd.add_argument("--runtime", choices=("python", "node"), required=True, help="Service runtime")
    p_sd.add_argument("--port", type=int, default=0, help="Service listening port")
    p_sd.add_argument("--inject-proxy", action="store_true", help="Also set HTTP_PROXY/HTTPS_PROXY to :9781")

    p_dns = sub.add_parser("dns", help="Show *.chimera.local registered domains and hosts hint")
    p_dns.add_argument("--anchor", default="", help="Override CHIMERA anchor URL")

    p_gh = sub.add_parser("ghost", help="Run any command in a 0-risk Copy-on-Write reality bubble and inspect diff")
    p_gh.add_argument("dir", help="Target directory to clone into CoW bubble")
    p_gh.add_argument("--commit", action="store_true", help="Commit changes back to target directory if exit_code==0")
    p_gh.add_argument("cmd", nargs=argparse.REMAINDER, help="Command to test (prefix with --)")

    p_clb = sub.add_parser("colab", help="Headless Google Colab Pro/Ultra CLI fabric (zero ngrok, anti-congestion, CU auto-stop)")
    p_clb.add_argument("action", choices=("status", "exec", "embed", "matmul", "stop", "tunnel-cmd"), help="Colab CLI action")
    p_clb.add_argument("--task", default="probe", choices=("probe", "cuda_embed", "cuda_matmul"), help="Task kind for exec")
    p_clb.add_argument("--profile", default="", help="Optional Colab profile override (CPU, CPU_HIGH_MEM, T4, L4, A100)")
    p_clb.add_argument("--session", default="", help="Optional Colab session name")
    p_clb.add_argument("--texts", nargs="*", default=None, help="Input texts for embed")
    p_clb.add_argument("--dim", type=int, default=256, help="Embedding dimension for embed")
    p_clb.add_argument("--n", type=int, default=1024, help="Matrix dimension NxN for matmul")
    p_clb.add_argument("--require-gpu", action="store_true", help="Require GPU (default auto-picks lightest T4)")
    p_clb.add_argument("--allow-heavy-gpu", action="store_true", help="Allow A100 heavy GPU tier")
    p_clb.add_argument("--keep-session", action="store_true", help="Keep Colab runtime alive after execution (default auto-stops to guard CU)")
    p_clb.add_argument("--refresh", action="store_true", help="Bypass status cache and query Colab CLI live")
    p_clb.add_argument("--local-port", type=int, default=9795, help="Local port for WebSocket-SSH tunnel-cmd")
    p_clb.add_argument("--remote-port", type=int, default=9795, help="Remote Colab port for WebSocket-SSH tunnel-cmd")
    p_clb.add_argument("--anchor", default="", help="Override CHIMERA anchor URL")

    p_ship = sub.add_parser("ship-check", help="Verify Overmind Cortex canary shipping invariants (PHANTOM, storm, RAM, CRDT, DLP)")
    p_ship.add_argument("--local", default="http://127.0.0.1:9780", help="Local Chimera dashboard URL")
    p_ship.add_argument("--peer", default="http://127.0.0.1:9789", help="Peer Chimera URL via PHANTOM or loopback")
    p_ship.add_argument("--window", type=float, default=1.5, help="Storm tx_delta observation window in seconds")

    # ---- Legacy Research Subcommands (v0.5.0 Multi-Realm Exotic Lanes) ----
    p_probe = sub.add_parser("probe", help="Probe hardware capabilities & Windows network realms")
    p_probe.add_argument("--json", action="store_true", help="Emit probe profile as JSON")

    p_demo = sub.add_parser("demo", help="Run the 4-phase CHIMERA-TP v0.5 exotic live showcase")
    p_demo.add_argument("--out", default="chimera_telemetry.json", help="Path for JSON telemetry output")

    p_send = sub.add_parser("send", help="Exotic v0.5 in-process multi-realm send (--exotic)")
    _add_send_options(p_send)

    p_listen = sub.add_parser("listen", help="Start standalone CHIMERA-TP v0.5 exotic receiver")
    p_listen.add_argument("--offer-file", required=True, help="Path for bound JSON session offer")
    p_listen.add_argument("--out-file", default="", help="Optional output file path")
    p_listen.add_argument("--timeout", type=float, default=30.0, help="Seconds to wait")

    p_connect = sub.add_parser("connect", help="Exotic v0.5 sender connecting to a `listen` offer file")
    p_connect.add_argument("--offer-file", required=True, help="Path to JSON offer created by `listen`")
    _add_send_options(p_connect)

    args = parser.parse_args(argv)

    if args.command == "ship-check":
        from .overmind_cortex import OvermindCortex

        rep = OvermindCortex.canary_ship_check(
            local_base=args.local,
            peer_base=args.peer,
            delta_window_s=float(args.window),
        )
        print(json.dumps(rep, indent=2, ensure_ascii=False))
        return 0 if rep.get("ok") else 1

    if args.command == "probe":
        env = probe_environment()
        caps = ChimeraFabric.capabilities()
        if args.json:
            data = env.to_dict()
            data["hyper_capabilities"] = caps
            print(json.dumps(data, indent=2, ensure_ascii=False))
        else:
            print(f"CHIMERA-HYPER v1.0 | Hardware: {caps['hardware']} | Wormhole SHM: {caps['wormhole_available']}")
            print(f"Host: {env.hostname} | Fingerprint: {env.topology_fingerprint}")
            for lid, r in env.realms.items():
                print(
                    f"  {lid:<14} avail={r.available!s:<5} ip={r.ip:<26} "
                    f"mtu={r.mtu:<10} probe={r.probe_ms:.2f}ms | {r.technique}"
                )
        return 0

    if args.command == "beam":
        if args.beam_action == "serve":
            ip, port = _parse_host_port(args.bind)
            vault_dir = Path(args.vault) if args.vault else None
            srv = BeamServer(
                bind_ip=ip,
                bind_port=port,
                vault_dir=vault_dir,
                out_dir=Path(args.out_dir),
                est_loss=float(args.est_loss),
            ).start()
            if args.port_file:
                _atomic_write_json(
                    Path(args.port_file),
                    {"host": srv.ctrl_addr[0], "port": srv.ctrl_addr[1]},
                )
            results: list[dict] = []
            try:
                idx = 0
                while args.max_transfers == 0 or idx < args.max_transfers:
                    rec = srv.wait_transfer(index=idx, timeout_s=float(args.timeout))
                    results.append(rec)
                    idx += 1
                print(json.dumps({"transfers": results}, indent=2, ensure_ascii=False))
                return 0
            except TimeoutError as exc:
                print(json.dumps({"error": str(exc)}), file=sys.stderr)
                return 1
            finally:
                srv.close()

        if args.beam_action == "send":
            target_spec = args.target
            if target_spec.startswith("@"):
                pfile = Path(target_spec[1:])
                deadline = time.perf_counter() + 5.0
                while not pfile.exists() and time.perf_counter() < deadline:
                    time.sleep(0.05)
                info = json.loads(pfile.read_text(encoding="utf-8"))
                taddr = (info["host"], int(info["port"]))
            else:
                taddr = _parse_host_port(target_spec)
            src = Path(args.dir) if args.dir else Path(args.file)
            vault_dir = Path(args.vault) if args.vault else None
            pace = float(args.pace_mbps) if args.pace_mbps > 0 else None
            rep = beam_send(
                taddr,
                src,
                vault_dir=vault_dir,
                est_loss=float(args.est_loss),
                pace_mbps=pace,
                timeout_s=float(args.timeout),
            )
            print(json.dumps(rep.to_dict(), indent=2, ensure_ascii=False))
            return 0 if rep.wire_report.get("sha256_match") else 1

    if args.command == "warp":
        stop_ev = False

        def _handle_sig(_signum: int, _frame: object) -> None:
            nonlocal stop_ev
            stop_ev = True

        signal.signal(signal.SIGINT, _handle_sig)
        if args.warp_action == "server":
            srv = WarpServer(
                udp_bind=_parse_host_port(args.bind),
                forward_tcp_addr=_parse_host_port(args.forward),
                est_loss=float(args.est_loss),
            ).start()
            print(f"WarpServer UDP {srv.udp_addr} -> TCP {args.forward}", flush=True)
            try:
                while not stop_ev:
                    time.sleep(0.2)
            finally:
                srv.close()
            return 0

        if args.warp_action == "client":
            cli = WarpClient(
                listen_tcp_addr=_parse_host_port(args.listen),
                remote_udp_addr=_parse_host_port(args.target),
                est_loss=float(args.est_loss),
            ).start()
            print(f"WarpClient TCP {cli.listen_addr} -> UDP {args.target}", flush=True)
            try:
                while not stop_ev:
                    time.sleep(0.2)
            finally:
                cli.close()
            return 0

    if args.command == "pipe":
        if args.pipe_action == "wormhole":
            if args.create:
                data = (
                    Path(args.file).read_bytes()
                    if args.file
                    else args.text.encode("utf-8")
                )
                t0 = time.perf_counter()
                with WormholeChannel.create(args.create, capacity_mb=int(args.cap_mb)) as wh:
                    written = wh.write_all(data)
                    wh.mark_eof()
                    # Brief wait to allow immediate local single-command peers to attach
                    time.sleep(0.05)
                ms = (time.perf_counter() - t0) * 1000.0
                print(
                    json.dumps(
                        {
                            "role": "writer",
                            "wormhole": args.create,
                            "bytes": written,
                            "sha256": hashlib.sha256(data).hexdigest(),
                            "elapsed_ms": round(ms, 2),
                        },
                        indent=2,
                    )
                )
                return 0
            if args.open:
                t0 = time.perf_counter()
                with WormholeChannel.open(args.open, wait_timeout_s=10.0) as wh:
                    data = wh.read_all()
                ms = (time.perf_counter() - t0) * 1000.0
                if args.file:
                    out_p = Path(args.file)
                    out_p.parent.mkdir(parents=True, exist_ok=True)
                    out_p.write_bytes(data)
                print(
                    json.dumps(
                        {
                            "role": "reader",
                            "wormhole": args.open,
                            "bytes": len(data),
                            "sha256": hashlib.sha256(data).hexdigest(),
                            "elapsed_ms": round(ms, 2),
                        },
                        indent=2,
                    )
                )
                return 0

        if args.pipe_action == "query":
            raw = Path(args.file).read_bytes()
            fields = tuple(f.strip() for f in args.fields.split(",") if f.strip())
            plan = ComputePlan(
                op=args.op,
                needle=args.needle,
                where_key=args.where_key,
                where_eq=args.where_eq,
                project_fields=fields,
                group_col=int(args.group_col),
                value_col=int(args.value_col),
                placement=args.placement,
            )
            res = ActivePipeEngine().run_query(raw, plan)
            if args.out_file:
                Path(args.out_file).write_bytes(res.output_bytes)
            print(json.dumps(res.to_dict(), indent=2, ensure_ascii=False))
            return 0

    if args.command == "bench-hyper":
        from benchmarks.benchmark_hyper import run_eval

        run_eval(Path(args.out))
        return 0

    if args.command == "ops-init":
        ops_dir = Path(args.ops_dir) if args.ops_dir else default_ops_dir()
        cfg = OpsConfig.load(ops_dir)
        if args.node_name:
            cfg.node_name = args.node_name
        cfg.role = args.role
        cfg.dashboard_bind = args.bind
        if args.peer_name:
            cfg.peer_name = args.peer_name
        if args.peer_ipv4:
            cfg.peer_ipv4 = args.peer_ipv4
        if args.peer_ipv6:
            cfg.peer_ipv6 = args.peer_ipv6
        if args.watched_file:
            cfg.watched_query_file = args.watched_file
        if args.allow_root:
            cfg.allowed_query_roots = [str(Path(p)) for p in args.allow_root]
        cfg.daily_time = args.daily_time
        cfg.active_profile = args.profile
        saved = cfg.save(ops_dir)
        print(json.dumps({"config_path": str(saved), "config": cfg.to_dict()}, indent=2, ensure_ascii=False))
        return 0

    if args.command == "daemon":
        ops_dir = Path(args.ops_dir) if args.ops_dir else default_ops_dir()
        cfg = OpsConfig.load(ops_dir)
        if args.bind:
            cfg.dashboard_bind = args.bind
        stop_ev = False

        def _sig_stop(_signum: int, _frame: object) -> None:
            nonlocal stop_ev
            stop_ev = True

        signal.signal(signal.SIGINT, _sig_stop)
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, _sig_stop)

        daemon = ChimeraDaemon(
            config=cfg, ops_dir=ops_dir, auto_seed_on_empty=not bool(args.no_seed)
        ).start()
        print(
            f"CHIMERA-HYPER v5.0 Daemon listening at http://{daemon.http_addr[0]}:{daemon.http_addr[1]}",
            flush=True,
        )
        try:
            while not stop_ev:
                time.sleep(0.5)
        finally:
            daemon.close()
        return 0

    if args.command == "autopilot":
        ops_dir = Path(args.ops_dir) if args.ops_dir else default_ops_dir()
        cfg = OpsConfig.load(ops_dir)
        store = TelemetryStore(ops_dir / "telemetry.db")
        try:
            rep = run_daily_autopilot(cfg, store, trigger=args.trigger, ops_dir=ops_dir)
            print(json.dumps(rep, indent=2, ensure_ascii=False))
            return 0 if int(rep["health_score"]) >= 60 else 1
        finally:
            store.close()

    if args.command == "merkle-sync":
        ops_dir = Path(args.ops_dir) if args.ops_dir else default_ops_dir()
        rep = merkle_beam_sync(
            peer_http_base=args.peer_http,
            peer_beam_addr=_parse_host_port(args.peer_beam),
            local_dir=Path(args.dir),
            workspace_id=args.ws,
            vault_dir=ops_dir / "tx_vault",
            shadow_dir=ops_dir / "merkle_shadows",
            est_loss=float(args.est_loss),
        )
        print(json.dumps(rep, indent=2, ensure_ascii=False))
        return 0 if rep.get("verified_root_match") else 1

    if args.command == "fluid":
        plan = ComputePlan(
            op=args.op,
            needle=args.needle,
            patterns=(args.needle,) if args.needle else (),
            sql=args.sql,
            use_telepathy=not bool(args.no_telepathy),
        )
        res, meta = remote_active_query(_parse_host_port(args.peer_query), args.path, plan)
        out = res.to_dict()
        out.update(meta)
        out["output_preview"] = res.output_bytes.decode("utf-8", errors="replace")[:1200]
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 0

    if args.command == "telepathy-bench":
        raw = Path(args.file).read_bytes()
        split = max(1024, len(raw) // 2)
        d = train_domain_dictionary([raw[:split]], domain=Path(args.file).stem)
        rep = benchmark_compression(raw[split:] if len(raw) > split else raw, d)
        print(json.dumps(rep, indent=2, ensure_ascii=False))
        return 0 if rep["lossless_ok"] else 1

    if args.command == "nat-bust":
        if args.profile_only or not args.peer_http:
            print(json.dumps(discover_nat_profile(), indent=2, ensure_ascii=False))
            return 0
        res = attempt_direct_punch(
            peer_http_base=args.peer_http,
            num_sockets=int(args.sockets),
            spray_count=int(args.spray),
            local_test_mode=bool(args.local_test),
        )
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0

    if args.command == "edge-proxy":
        host, port = _parse_host_port(args.listen)
        stop_ev = False

        def _sig_ep(_s: int, _f: object) -> None:
            nonlocal stop_ev
            stop_ev = True

        signal.signal(signal.SIGINT, _sig_ep)
        proxy = LocalEdgeProxy(
            listen_host=host,
            listen_port=port,
            peer_http_base=args.peer_http,
            telepathy_store=TelepathicStore(default_ops_dir() / "dicts"),
        ).start()
        print(f"CHIMERA v4.0 LocalEdgeProxy listening at http://{proxy.addr[0]}:{proxy.addr[1]}", flush=True)
        try:
            while not stop_ev:
                time.sleep(0.5)
        finally:
            proxy.close()
        return 0

    if args.command == "sentinel":
        ops_dir = Path(args.ops_dir) if args.ops_dir else default_ops_dir()
        cfg = OpsConfig.load(ops_dir)
        eng = SentinelEngine(ops_dir)
        try:
            out = eng.scan(cfg) if args.scan else eng.latest_status()
            print(json.dumps(out, indent=2, ensure_ascii=False))
            return 0
        finally:
            eng.close()

    if args.command == "search":
        if args.peer_http:
            base = args.peer_http.rstrip("/")
            if args.reindex:
                req = urllib.request.Request(
                    f"{base}/api/search/reindex",
                    data=b"{}",
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=30.0) as resp:
                    print(resp.read().decode("utf-8"))
                return 0
            req = urllib.request.Request(
                f"{base}/api/search",
                data=json.dumps(
                    {"query": args.query, "repo": args.repo, "limit": int(args.limit)}
                ).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10.0) as resp:
                print(resp.read().decode("utf-8"))
            return 0

        ops_dir = Path(args.ops_dir) if args.ops_dir else default_ops_dir()
        cfg = OpsConfig.load(ops_dir)
        idx = CodeSearchIndex(ops_dir / "code_index.db")
        try:
            if args.reindex:
                roots = [Path(r) for r in args.root] if args.root else [Path(r) for r in (cfg.search_roots or cfg.allowed_query_roots)]
                print(json.dumps(idx.incremental_index(roots), indent=2, ensure_ascii=False))
                return 0
            res = idx.search(args.query, limit=int(args.limit), repo=args.repo) if args.query else idx.stats()
            print(json.dumps(res, indent=2, ensure_ascii=False))
            return 0
        finally:
            idx.close()

    if args.command == "holo-backup":
        ops_dir = Path(args.ops_dir) if args.ops_dir else default_ops_dir()
        broot = ops_dir / "holo_backups"
        if args.action == "list":
            print(json.dumps({"backups": list_holo_backups(broot)}, indent=2, ensure_ascii=False))
            return 0
        if args.action == "create":
            cfg = OpsConfig.load(ops_dir)
            targets = [Path(p) for p in args.path] if args.path else [Path(p) for p in (cfg.backup_targets or [ops_dir / "config.json"])]
            rep = create_holo_backup(
                paths=targets,
                backup_root=broot,
                backup_id=args.backup_id,
                peer_http_base=args.peer_http,
            )
            print(json.dumps(rep, indent=2, ensure_ascii=False))
            return 0 if rep.get("ok") else 1
        if args.action == "restore":
            out_dir = Path(args.out_dir) if args.out_dir else (broot / "restored" / (args.backup_id or "cli_restore"))
            rep = restore_holo_backup([Path(s) for s in args.shard], out_dir=out_dir)
            print(json.dumps(rep, indent=2, ensure_ascii=False))
            return 0 if rep.get("sha256_match") else 1

    if args.command == "phantom":
        base = args.daemon_http.rstrip("/")
        if args.action == "status":
            with urllib.request.urlopen(f"{base}/api/phantom/status", timeout=5.0) as r:
                print(r.read().decode("utf-8"))
            return 0
        ep = "/api/phantom/connect" if args.action == "connect" else "/api/phantom/disconnect"
        req = urllib.request.Request(f"{base}{ep}", data=b"{}", headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=12.0) as r:
            print(r.read().decode("utf-8"))
        return 0

    if args.command == "pty":
        base = args.peer_http.rstrip("/")
        if args.action == "list":
            with urllib.request.urlopen(f"{base}/api/pty/list", timeout=6.0) as r:
                print(r.read().decode("utf-8"))
            return 0
        if args.action == "create":
            req = urllib.request.Request(f"{base}/api/pty/create", data=b"{}", headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=6.0) as r:
                print(r.read().decode("utf-8"))
            return 0
        if args.action == "close":
            req = urllib.request.Request(f"{base}/api/pty/close", data=json.dumps({"session_id": args.sid}).encode(), headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=6.0) as r:
                print(r.read().decode("utf-8"))
            return 0
        req_w = urllib.request.Request(
            f"{base}/api/pty/write",
            data=json.dumps({"session_id": args.sid, "text": args.cmd + "\n"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req_w, timeout=6.0) as r:
            _ = r.read()
        time.sleep(0.3)
        with urllib.request.urlopen(f"{base}/api/pty/read?session_id={args.sid}&cursor=0&wait_ms=400", timeout=6.0) as r2:
            print(r2.read().decode("utf-8"))
        return 0

    if args.command == "fs":
        import urllib.parse

        base = args.peer_http.rstrip("/")
        q = urllib.parse.quote(args.path)
        ep = f"/api/fs/list?path={q}" if args.action == "ls" else (f"/api/fs/read?path={q}" if args.action == "cat" else f"/api/fs/git-status?repo={q}")
        with urllib.request.urlopen(f"{base}{ep}", timeout=8.0) as r:
            print(r.read().decode("utf-8"))
        return 0

    if args.command == "medic":
        base = args.peer_http.rstrip("/")
        if args.action == "status":
            with urllib.request.urlopen(f"{base}/api/medic/status", timeout=6.0) as r:
                print(r.read().decode("utf-8"))
            return 0
        if args.action == "investigate":
            req = urllib.request.Request(
                f"{base}/api/medic/investigate",
                data=json.dumps({"file_path": args.file_path, "pattern": args.pattern}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10.0) as r:
                print(r.read().decode("utf-8"))
            return 0
        req = urllib.request.Request(
            f"{base}/api/medic/heal",
            data=json.dumps({"playbook_id": args.playbook, "params": {"file_path": args.file_path, "repo_path": args.file_path, "dry_run": bool(args.dry_run)}}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15.0) as r:
            print(r.read().decode("utf-8"))
        return 0

    if args.command == "drop":
        import base64 as b64

        base = args.peer_http.rstrip("/")
        if args.action == "list":
            with urllib.request.urlopen(f"{base}/api/portal/list", timeout=6.0) as r:
                print(r.read().decode("utf-8"))
            return 0
        if args.action == "get":
            with urllib.request.urlopen(f"{base}/api/portal/item?item_id={args.item_id}", timeout=6.0) as r:
                print(r.read().decode("utf-8"))
            return 0
        raw_b = Path(args.file).read_bytes() if args.file else args.text.encode("utf-8")
        req = urllib.request.Request(
            f"{base}/api/portal/drop",
            data=json.dumps({"title": args.title, "data_b64": b64.b64encode(raw_b).decode("ascii"), "kind": "file" if args.file else "text"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10.0) as r:
            print(r.read().decode("utf-8"))
        return 0

    if args.command == "context-pack":
        base = args.peer_http.rstrip("/")
        req = urllib.request.Request(
            f"{base}/api/context/pack",
            data=json.dumps({"query": args.query, "repo": args.repo}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10.0) as r:
            res = json.loads(r.read().decode("utf-8"))
        print(res.get("markdown", ""))
        return 0

    if args.command == "synergy":
        base = args.peer_http.rstrip("/")
        if args.action == "status":
            with urllib.request.urlopen(f"{base}/api/synergy/status", timeout=8.0) as r:
                print(r.read().decode("utf-8"))
            return 0
        if args.action == "bounties":
            with urllib.request.urlopen(f"{base}/api/synergy/bounties", timeout=8.0) as r:
                print(r.read().decode("utf-8"))
            return 0
        if args.action == "burn-scan":
            with urllib.request.urlopen(f"{base}/api/synergy/burn-scan", timeout=8.0) as r:
                print(r.read().decode("utf-8"))
            return 0
        if args.action == "brief":
            req = urllib.request.Request(
                f"{base}/api/synergy/surgical-brief",
                data=json.dumps({"workspace_dir": args.workspace_dir, "issue_title": args.title, "inject": bool(args.inject)}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=15.0) as r:
                print(r.read().decode("utf-8"))
            return 0
        req = urllib.request.Request(
            f"{base}/api/synergy/vault-backup",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30.0) as r:
            print(r.read().decode("utf-8"))
        return 0

    if args.command == "omega":
        import urllib.request
        from .native import v7_native_caps
        from .omega_bench import format_omega_markdown, run_omega_benchmark
        from .omega_compute import NeuralPpmCodec, WasmActivePipe, build_wasm_byte_counter_module
        from .omega_storage import RegeneratingMeshVault, SlepianWolfSync, detect_fs_mount_caps
        from .omega_transport import detect_os_tun_caps

        base = args.peer_http.rstrip("/")
        if args.action == "status":
            if args.local:
                print(
                    json.dumps(
                        {
                            "ok": True,
                            "version": "7.0.0",
                            "native_v7": v7_native_caps(),
                            "os_tun_caps": detect_os_tun_caps(),
                            "fs_mount_caps": detect_fs_mount_caps(),
                        },
                        indent=2,
                    )
                )
                return 0
            with urllib.request.urlopen(f"{base}/api/omega/status", timeout=8.0) as r:
                print(r.read().decode("utf-8"))
            return 0
        if args.action == "bench":
            if args.local:
                rep = run_omega_benchmark()
            else:
                req = urllib.request.Request(
                    f"{base}/api/omega/benchmark",
                    data=b"{}",
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=25.0) as r:
                    rep = json.loads(r.read().decode("utf-8"))
            print(format_omega_markdown(rep))
            return 0
        if args.action == "ppm":
            sample = (args.input or '{"node":"hub","status":"OK","latency_ms":4.5}\n' * 120).encode("utf-8")
            print(json.dumps(NeuralPpmCodec.benchmark(sample), indent=2))
            return 0
        if args.action == "wasm":
            inp_s = args.input or ("INFO ok\nERROR MAIL_502\n" * 200)
            if args.local:
                res = WasmActivePipe().execute_buffer(build_wasm_byte_counter_module(ord("\n")), inp_s.encode("utf-8"))
                print(json.dumps(res, indent=2))
                return 0
            req = urllib.request.Request(
                f"{base}/api/omega/wasm-exec",
                data=json.dumps({"input_text": inp_s}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=15.0) as r:
                print(r.read().decode("utf-8"))
            return 0
        if args.action == "slepian":
            old_b = (args.input or "SLEPIAN_WOLF_SYNC_STREAM_" * 200).encode("utf-8")
            new_arr = bytearray(old_b)
            if len(new_arr) > 600:
                new_arr[512:544] = b"0RTT_SYNDROME_BLIND_REPAIR_TEST!"
            pkt = SlepianWolfSync.encode_blind_packet(bytes(new_arr), block_len=512, max_err_blocks=3)
            dec = SlepianWolfSync.decode_blind_packet(old_b, pkt)
            print(json.dumps({k: v for k, v in dec.items() if k != "decoded"}, indent=2))
            return 0
        raw_v = (args.input or "CAUCHY_REGEN_VAULT_SECRET_" * 40).encode("utf-8")
        mv = RegeneratingMeshVault(k=3, n=5)
        enc = mv.encode_shards(raw_v)
        healed = mv.repair_missing_shard([enc["shards"][0], enc["shards"][2], enc["shards"][3]], target_node_idx=1)
        rec = mv.decode_shards([healed, enc["shards"][3], enc["shards"][4]])
        print(json.dumps({"ok": rec == raw_v, "repair_ms": healed["repair_ms"], "entropy": healed["entropy"]}, indent=2))
        return 0

    if args.command == "singularity":
        import urllib.request
        from .native import v8_native_caps
        from .singularity_airgap_crypto import (
            AirGapFountainBridge,
            PlausibleDeniabilityVault,
            PrivateInfoRetrievalEngine,
        )
        from .singularity_bench import format_singularity_markdown, run_singularity_benchmark
        from .singularity_kolmogorov_swarm import KolmogorovGrammarCodec, SwarmAnycastMesh
        from .singularity_time_crdt import MerkleCrdtShadowTwin

        base = args.peer_http.rstrip("/")
        if args.action == "status":
            if args.local:
                print(json.dumps({"ok": True, "version": "8.0.0", "native_v8": v8_native_caps()}, indent=2))
                return 0
            with urllib.request.urlopen(f"{base}/api/singularity/status", timeout=8.0) as r:
                print(r.read().decode("utf-8"))
            return 0
        if args.action == "bench":
            if args.local:
                rep = run_singularity_benchmark()
            else:
                req = urllib.request.Request(
                    f"{base}/api/singularity/benchmark",
                    data=b"{}",
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=30.0) as r:
                    rep = json.loads(r.read().decode("utf-8"))
            print(format_singularity_markdown(rep))
            return 0
        if args.action == "pir":
            print(json.dumps(PrivateInfoRetrievalEngine.run_benchmark(), indent=2))
            return 0
        if args.action == "kolmogorov":
            if args.input:
                raw_in = args.input.encode("utf-8")
                comp_in = KolmogorovGrammarCodec.compress(raw_in)
                print(json.dumps({"ok": KolmogorovGrammarCodec.decompress(comp_in) == raw_in, "raw_bytes": len(raw_in), "comp_bytes": len(comp_in)}, indent=2))
                return 0
            print(json.dumps(KolmogorovGrammarCodec.run_benchmark(), indent=2))
            return 0
        if args.action == "crdt":
            print(json.dumps(MerkleCrdtShadowTwin.run_benchmark(), indent=2))
            return 0
        if args.action == "airgap":
            print(json.dumps(AirGapFountainBridge.run_benchmark(), indent=2))
            return 0
        if args.action == "dual-vault":
            print(json.dumps(PlausibleDeniabilityVault.run_benchmark(), indent=2))
            return 0
        print(json.dumps(SwarmAnycastMesh.run_benchmark(), indent=2))
        return 0

    if args.command == "hyperdrive":
        import urllib.parse
        import urllib.request
        from .native import v9_native_caps
        from .v9_app_index import LiveClusterIndexer, RemoteAppStreamEngine
        from .v9_bench import format_hyperdrive_markdown, run_hyperdrive_benchmark
        from .v9_dataplane import MultiWanSpeedFusionEngine, NativeDataPlaneEngine
        from .v9_nvme_grid import UnifiedHardwareGrid, VirtualNvmeFabric

        base = args.peer_http.rstrip("/")
        if args.action == "status":
            if args.local:
                print(json.dumps({"ok": True, "version": "9.0.0", "native_v9": v9_native_caps()}, indent=2))
                return 0
            with urllib.request.urlopen(f"{base}/api/hyperdrive/status", timeout=8.0) as r:
                print(r.read().decode("utf-8"))
            return 0
        if args.action == "bench":
            if args.local:
                rep = run_hyperdrive_benchmark()
            else:
                req = urllib.request.Request(
                    f"{base}/api/hyperdrive/benchmark",
                    data=b"{}",
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=45.0) as r:
                    rep = json.loads(r.read().decode("utf-8"))
            print(format_hyperdrive_markdown(rep))
            return 0
        if args.action == "dataplane":
            print(json.dumps(NativeDataPlaneEngine.run_benchmark(), indent=2))
            return 0
        if args.action == "nvme":
            print(json.dumps(VirtualNvmeFabric.run_benchmark(), indent=2))
            return 0
        if args.action == "grid":
            print(json.dumps(UnifiedHardwareGrid.run_benchmark(), indent=2))
            return 0
        if args.action == "fusion":
            print(json.dumps(MultiWanSpeedFusionEngine.run_benchmark(), indent=2))
            return 0
        if args.action == "stream":
            print(json.dumps(RemoteAppStreamEngine.run_benchmark(), indent=2))
            return 0
        if args.action == "search":
            if args.local:
                idx = LiveClusterIndexer([Path.cwd()])
                idx.build_index(max_files=300)
                print(json.dumps(idx.search(args.query), indent=2))
                return 0
            with urllib.request.urlopen(f"{base}/api/hyperdrive/search?q={urllib.parse.quote(args.query)}", timeout=6.0) as r:
                print(r.read().decode("utf-8"))
            return 0
        with urllib.request.urlopen(f"{base}/api/hyperdrive/hub", timeout=6.0) as r:
            print(r.read().decode("utf-8"))
        return 0

    if args.command == "galactic":
        import urllib.parse
        import urllib.request
        from .native import v12_native_caps, v9_native_caps
        from .v10_outlaw_engines import ProceduralTarpitLabyrinth
        from .v10_sovereign_crypto import FrostThreshold2of3
        from .v10_sovereign_runtime import WasmLiveTeleportEngine
        from .v11_organism_mesh import BabelPointerCodec, ImmuneProtocolOrganism
        from .v12_bench import format_galactic_markdown, run_galactic_benchmark
        from .v12_galactic_engines import HolographicSlpEngine, HyperdimensionalVsaMesh, ReversibleBennettVM

        base = args.peer_http.rstrip("/")
        if args.action == "status":
            if args.local:
                print(json.dumps({"ok": True, "version": "12.0.0", "native_v9": v9_native_caps(), "native_v12": v12_native_caps()}, indent=2))
                return 0
            with urllib.request.urlopen(f"{base}/api/galactic/status", timeout=8.0) as r:
                print(r.read().decode("utf-8"))
            return 0
        if args.action == "bench":
            if args.local:
                rep = run_galactic_benchmark(wave=args.wave)
            else:
                req = urllib.request.Request(
                    f"{base}/api/galactic/benchmark",
                    data=json.dumps({"wave": args.wave}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=60.0) as r:
                    rep = json.loads(r.read().decode("utf-8"))
            print(format_galactic_markdown(rep))
            return 0
        if args.action == "tarpit":
            if args.local:
                print(json.dumps({"ok": True, "stateless": True, **ProceduralTarpitLabyrinth().inspect_path(args.path)}, indent=2))
                return 0
            rel = "/" + str(args.path or "").lstrip("/")
            with urllib.request.urlopen(f"{base}/api/galactic/tarpit{urllib.parse.quote(rel)}", timeout=8.0) as r:
                print(r.read().decode("utf-8"))
            return 0
        if args.action == "vsa":
            if args.local:
                print(json.dumps(HyperdimensionalVsaMesh.run_benchmark(), indent=2))
                return 0
            req = urllib.request.Request(
                f"{base}/api/galactic/vsa-query",
                data=b"{}",
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=15.0) as r:
                print(r.read().decode("utf-8"))
            return 0
        if args.action == "frost":
            print(json.dumps(FrostThreshold2of3.run_benchmark(peer_http_base="" if args.local else base), indent=2))
            return 0
        if args.action == "teleport":
            print(json.dumps(WasmLiveTeleportEngine.run_benchmark(peer_http_base="" if args.local else base), indent=2))
            return 0
        if args.action == "babel":
            print(json.dumps(BabelPointerCodec.run_benchmark(), indent=2))
            return 0
        if args.action == "immune":
            print(json.dumps(ImmuneProtocolOrganism.run_benchmark(), indent=2))
            return 0
        if args.action == "bennett":
            print(json.dumps(ReversibleBennettVM.run_benchmark(), indent=2))
            return 0
        print(json.dumps(HolographicSlpEngine.run_benchmark(), indent=2))
        return 0

    if args.command == "smi":
        import urllib.request as _urlreq
        from .platform import discover_runtime_file, render_smi

        rt = discover_runtime_file()
        anchor = (args.anchor or (rt or {}).get("anchor_url") or "http://127.0.0.1:9780").rstrip("/")
        try:
            with _urlreq.urlopen(f"{anchor}/v1/smi", timeout=4.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            print(json.dumps({"ok": False, "anchor": anchor, "error": str(exc)}, indent=2), file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(data, indent=2, ensure_ascii=False))
        else:
            print(render_smi(data))
        return 0

    if args.command == "link":
        from .platform import link_project

        res = link_project(
            project_dir=args.path,
            app_name=args.app or None,
            port=args.port or None,
            qos=args.qos,
        )
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0

    if args.command == "init":
        from .platform import init_project

        res = init_project(
            project_dir=args.path,
            app_name=args.app or None,
            port=args.port or None,
            with_bridge=not args.no_bridge,
        )
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0

    if args.command == "autoload":
        from .platform import autoload_status, install_autoload, uninstall_autoload

        if args.action == "install":
            print(json.dumps(install_autoload(), indent=2, ensure_ascii=False))
        elif args.action == "uninstall":
            print(json.dumps(uninstall_autoload(), indent=2, ensure_ascii=False))
        else:
            print(json.dumps(autoload_status(), indent=2, ensure_ascii=False))
        return 0

    if args.command == "mcp":
        from .platform import serve_mcp_stdio

        return serve_mcp_stdio(anchor_url=args.anchor or None)

    if args.command == "cartridge":
        import urllib.request as _urlreq
        from .platform import discover_runtime_file

        rt = discover_runtime_file()
        anchor = (args.anchor or (rt or {}).get("anchor_url") or "http://127.0.0.1:9780").rstrip("/")
        if args.action == "list":
            with _urlreq.urlopen(f"{anchor}/v1/cartridges", timeout=4.0) as resp:
                print(json.dumps(json.loads(resp.read().decode("utf-8")), indent=2))
            return 0
        body = json.dumps({"name": args.name, "enabled": args.action == "enable"}).encode("utf-8")
        req = _urlreq.Request(f"{anchor}/v1/cartridges", data=body, headers={"Content-Type": "application/json"}, method="POST")
        with _urlreq.urlopen(req, timeout=4.0) as resp:
            print(json.dumps(json.loads(resp.read().decode("utf-8")), indent=2))
        return 0

    if args.command == "canary":
        import urllib.request as _urlreq
        from .platform import discover_runtime_file

        rt = discover_runtime_file()
        anchor = (args.anchor or (rt or {}).get("anchor_url") or "http://127.0.0.1:9780").rstrip("/")
        paths = [p.strip() for p in args.paths.split(",") if p.strip()]
        body = json.dumps(
            {"baseline_url": args.baseline_url, "canary_url": args.canary_url, "paths": paths, "samples": args.samples}
        ).encode("utf-8")
        req = _urlreq.Request(f"{anchor}/v1/canary/compare", data=body, headers={"Content-Type": "application/json"}, method="POST")
        with _urlreq.urlopen(req, timeout=15.0) as resp:
            res = json.loads(resp.read().decode("utf-8"))
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0 if res.get("verdict") == "PROMOTE" else 1

    if args.command == "attach-systemd":
        from .platform import install_systemd_dropin

        res = install_systemd_dropin(
            unit_name=args.unit,
            app_name=args.app,
            runtime=args.runtime,
            port=args.port,
            inject_http_proxy=bool(args.inject_proxy),
        )
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0

    if args.command == "dns":
        import urllib.request as _urlreq
        from .platform import discover_runtime_file

        rt = discover_runtime_file()
        anchor = (args.anchor or (rt or {}).get("anchor_url") or "http://127.0.0.1:9780").rstrip("/")
        with _urlreq.urlopen(f"{anchor}/v1/dns/hosts-hint", timeout=4.0) as resp:
            print(json.dumps(json.loads(resp.read().decode("utf-8")), indent=2, ensure_ascii=False))
        return 0

    if args.command == "ghost":
        from .platform import GhostBubbleEngine

        cmd = list(args.cmd or [])
        if cmd and cmd[0] == "--":
            cmd = cmd[1:]
        if not cmd:
            print("Usage: chimera-tp ghost <dir> [--commit] -- <command...>", file=sys.stderr)
            return 2
        eng = GhostBubbleEngine()
        res = eng.run_bubble(args.dir, cmd, auto_discard=False)
        if args.commit and res["exit_code"] == 0:
            res["commit_result"] = eng.commit(res["bubble_id"])
        else:
            res["discard_result"] = eng.discard(res["bubble_id"])
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return int(res["exit_code"])

    if args.command == "colab":
        import urllib.request as _urlreq
        from .platform import discover_runtime_file

        rt = discover_runtime_file()
        anchor = (args.anchor or (rt or {}).get("anchor_url") or "http://127.0.0.1:9780").rstrip("/")
        opener = _urlreq.build_opener(_urlreq.ProxyHandler({}))
        if args.action == "status":
            q = "?refresh=1" if args.refresh else ""
            with opener.open(f"{anchor}/v1/vgpu/colab/status{q}", timeout=20.0) as resp:
                print(json.dumps(json.loads(resp.read().decode("utf-8")), indent=2, ensure_ascii=False))
            return 0
        if args.action == "stop":
            sess = args.session or "chimera_t4"
            req = _urlreq.Request(
                f"{anchor}/v1/vgpu/colab/stop",
                data=json.dumps({"session": sess}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with opener.open(req, timeout=45.0) as resp:
                res = json.loads(resp.read().decode("utf-8"))
            print(json.dumps(res, indent=2, ensure_ascii=False))
            return 0 if res.get("ok") else 1
        if args.action == "tunnel-cmd":
            req = _urlreq.Request(
                f"{anchor}/v1/vgpu/colab/tunnel-cmd",
                data=json.dumps(
                    {
                        "session": args.session or "chimera_t4",
                        "local_port": int(args.local_port),
                        "remote_port": int(args.remote_port),
                    }
                ).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with opener.open(req, timeout=10.0) as resp:
                print(json.dumps(json.loads(resp.read().decode("utf-8")), indent=2, ensure_ascii=False))
            return 0
        task_kind = (
            "cuda_embed"
            if args.action == "embed"
            else ("cuda_matmul" if args.action == "matmul" else args.task)
        )
        payload: dict[str, object] = {}
        if task_kind == "cuda_embed":
            payload = {"texts": list(args.texts or ["chimera colab fabric test"]), "dim": int(args.dim)}
        elif task_kind == "cuda_matmul":
            payload = {"n": int(args.n)}
        req = _urlreq.Request(
            f"{anchor}/v1/vgpu/colab/exec",
            data=json.dumps(
                {
                    "task_kind": task_kind,
                    "payload": payload,
                    "profile": args.profile or None,
                    "session": args.session or None,
                    "keep_session": bool(args.keep_session),
                    "require_gpu": bool(args.require_gpu or args.action == "matmul"),
                    "allow_heavy_gpu": bool(args.allow_heavy_gpu),
                },
                ensure_ascii=False,
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with opener.open(req, timeout=260.0) as resp:
            res = json.loads(resp.read().decode("utf-8"))
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0 if res.get("ok") else 1

    if args.command == "run":
        import subprocess
        import urllib.request as _urlreq
        from .platform import discover_runtime_file

        cmd = list(args.cmd or [])
        if cmd and cmd[0] == "--":
            cmd = cmd[1:]
        if not cmd:
            print("Usage: chimera-tp run --app <name> -- <command...>", file=sys.stderr)
            return 2
        rt = discover_runtime_file() or {}
        anchor = str(rt.get("anchor_url") or os.environ.get("CHIMERA_URL") or "http://127.0.0.1:9780").rstrip("/")
        proxy = str(rt.get("egress_proxy_url") or "")
        app_name = args.app or Path.cwd().name
        env = dict(os.environ)
        env["CHIMERA_URL"] = anchor
        env["CHIMERA_APP"] = app_name
        env["CHIMERA_AUTO"] = "1"
        if rt.get("_runtime_path"):
            env["CHIMERA_RUNTIME"] = str(rt["_runtime_path"])
        if rt.get("boot_token"):
            env["CHIMERA_TOKEN"] = str(rt["boot_token"])
        if proxy and not args.no_proxy:
            env["HTTP_PROXY"] = proxy
            env["HTTPS_PROXY"] = proxy
            np = env.get("NO_PROXY", "")
            peer_ip = str(rt.get("peer_ipv4") or "").strip()
            extras = "127.0.0.1,localhost,::1,.chimera.local" + (f",{peer_ip}" if peer_ip else "")
            env["NO_PROXY"] = f"{np},{extras}" if np else extras
        try:
            body = json.dumps(
                {
                    "app": app_name,
                    "pid": os.getpid(),
                    "cwd": str(Path.cwd()),
                    "port": int(args.port or 0),
                    "qos": str(args.qos),
                    "attach_mode": "chimera_run",
                }
            ).encode("utf-8")
            req = _urlreq.Request(
                f"{anchor}/v1/apps/register",
                data=body,
                headers={"Content-Type": "application/json", "X-Chimera-App": app_name},
                method="POST",
            )
            _urlreq.urlopen(req, timeout=0.8).read()
        except Exception:
            pass
        return int(subprocess.call(cmd, env=env))

    if args.command == "demo":
        from .demo import run_demo

        run_demo(Path(args.out))
        return 0

    if args.command == "listen":
        env = probe_environment()
        rx = ChimeraReceiver(env, droplet_size=20)
        offer = rx.start()
        _atomic_write_json(Path(args.offer_file), offer)
        try:
            tid, payload, sha_ok, mode = rx.wait_next_transfer(timeout_s=float(args.timeout))
            if args.out_file:
                out_p = Path(args.out_file)
                out_p.parent.mkdir(parents=True, exist_ok=True)
                out_p.write_bytes(payload)
            print(
                json.dumps(
                    {
                        "transfer_id": tid,
                        "mode": mode,
                        "bytes": len(payload),
                        "sha256_match": sha_ok,
                        "sha256": hashlib.sha256(payload).hexdigest(),
                    },
                    indent=2,
                )
            )
            return 0 if sha_ok else 1
        except TimeoutError as exc:
            print(json.dumps({"error": str(exc)}), file=sys.stderr)
            return 1
        finally:
            rx.close()

    if args.command in ("send", "connect"):
        payload = (
            args.text.encode("utf-8")
            if args.text is not None
            else Path(args.file).read_bytes()
        )
        kill_set = {x.strip() for x in args.kill.split(",") if x.strip()}
        fault = FaultProfile(
            kill_lanes=kill_set,
            packet_drop_rate=max(0.0, min(0.9, float(args.drop))),
            corrupt_lan_noise=bool(args.corrupt_lan),
            jumbo_drop_rate=max(0.0, min(0.9, float(args.jumbo_drop))),
        )
        env = probe_environment()

        if args.command == "connect":
            offer_path = Path(args.offer_file)
            wait_end = time.perf_counter() + 5.0
            while not offer_path.exists() and time.perf_counter() < wait_end:
                time.sleep(0.05)
            offer = json.loads(offer_path.read_text(encoding="utf-8"))
            tx = ChimeraSender(env, offer)
            if args.mode == "holographic":
                _, report = tx.send_holographic(
                    None,
                    payload,
                    fault,
                    profile=args.profile,
                    parallel=not args.sequential,
                )
            else:
                _, report = tx.send_metamorphic(
                    None,
                    payload,
                    fault,
                    profile=args.profile,
                    parallel=not args.sequential,
                )
            ok = bool(report.success and report.sha256_match)
            print(
                json.dumps(
                    {"verified_remote": ok, "report": report.to_dict()},
                    indent=2,
                    ensure_ascii=False,
                )
            )
            return 0 if ok else 1

        rx = ChimeraReceiver(env, droplet_size=20)
        offer = rx.start()
        try:
            tx = ChimeraSender(env, offer)
            if args.mode == "holographic":
                recovered, report = tx.send_holographic(
                    rx,
                    payload,
                    fault,
                    profile=args.profile,
                    parallel=not args.sequential,
                )
            else:
                recovered, report = tx.send_metamorphic(
                    rx,
                    payload,
                    fault,
                    profile=args.profile,
                    parallel=not args.sequential,
                )
            ok = report.success and recovered == payload
            print(
                json.dumps(
                    {"verified_equal": ok, "report": report.to_dict()},
                    indent=2,
                    ensure_ascii=False,
                )
            )
            return 0 if ok else 1
        finally:
            rx.close()

    return 2
