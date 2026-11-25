"""Command-line interface for CHIMERA-TP."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

from .probe import probe_environment
from .protocol import ChimeraReceiver, ChimeraSender, FaultProfile


def _configure_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except OSError:
                pass


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
        help="Invert 100% of random noise payload bytes on LAN_LENGTH",
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
        prog="chimera_tp",
        description="CHIMERA-TP: Cross-Host Interface Metamorphic Entangled Routing Architecture",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_probe = sub.add_parser("probe", help="Probe local Windows network interfaces and realms")
    p_probe.add_argument("--json", action="store_true", help="Emit probe profile as JSON")

    p_demo = sub.add_parser("demo", help="Run the 4-phase CHIMERA-TP live showcase")
    p_demo.add_argument(
        "--out",
        default="chimera_telemetry.json",
        help="Path for JSON telemetry output",
    )

    p_send = sub.add_parser("send", help="In-process send of text or a file across CHIMERA-TP")
    _add_send_options(p_send)

    p_listen = sub.add_parser(
        "listen", help="Start a standalone CHIMERA-TP receiver and wait for one transfer"
    )
    p_listen.add_argument(
        "--offer-file",
        required=True,
        help="Path where the bound JSON session offer will be written atomically",
    )
    p_listen.add_argument(
        "--out-file",
        default="",
        help="Optional output file path for received payload bytes",
    )
    p_listen.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="Seconds to wait for an incoming transfer",
    )

    p_connect = sub.add_parser(
        "connect", help="Standalone sender connecting to a running `listen` offer file"
    )
    p_connect.add_argument(
        "--offer-file",
        required=True,
        help="Path to the JSON session offer created by `listen`",
    )
    _add_send_options(p_connect)

    args = parser.parse_args(argv)

    if args.command == "probe":
        env = probe_environment()
        if args.json:
            print(json.dumps(env.to_dict(), indent=2, ensure_ascii=False))
        else:
            print(f"Host: {env.hostname} | Fingerprint: {env.topology_fingerprint}")
            for lid, r in env.realms.items():
                print(
                    f"  {lid:<14} avail={r.available!s:<5} ip={r.ip:<26} "
                    f"mtu={r.mtu:<10} probe={r.probe_ms:.2f}ms | {r.technique}"
                )
        return 0

    if args.command == "demo":
        from .demo import run_demo

        run_demo(Path(args.out))
        return 0

    if args.command == "listen":
        env = probe_environment()
        rx = ChimeraReceiver(env, droplet_size=20)
        offer = rx.start()
        offer_path = Path(args.offer_file)
        offer_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = offer_path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(offer, indent=2), encoding="utf-8")
        os.replace(tmp_path, offer_path)
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
                    {
                        "verified_equal": ok,
                        "report": report.to_dict(),
                    },
                    indent=2,
                    ensure_ascii=False,
                )
            )
            return 0 if ok else 1
        finally:
            rx.close()

    return 2
