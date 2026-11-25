"""Command-line interface for CHIMERA-HYPER v1.0 (and legacy v0.5.0 exotic modes)."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import sys
import time
from pathlib import Path

from .active_pipe import ActivePipeEngine, ComputePlan
from .autopilot import OpsConfig, TelemetryStore, default_ops_dir, run_daily_autopilot
from .dashboard import ChimeraDaemon
from .fabric import BeamServer, ChimeraFabric, beam_send
from .native import WormholeChannel
from .probe import probe_environment
from .protocol import ChimeraReceiver, ChimeraSender, FaultProfile
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
        description="CHIMERA-HYPER v1.0: Silicon-Native High-Performance Transport + Exotic Multi-Realm Suite",
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
            f"CHIMERA-HYPER v2.0 Daemon listening at http://{daemon.http_addr[0]}:{daemon.http_addr[1]}",
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
