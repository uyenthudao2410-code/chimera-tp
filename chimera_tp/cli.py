"""Command-line interface for CHIMERA-TP."""

from __future__ import annotations

import argparse
import json
import sys
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

    p_send = sub.add_parser("send", help="Send text or a file across CHIMERA-TP")
    src_group = p_send.add_mutually_exclusive_group(required=True)
    src_group.add_argument("--text", help="UTF-8 string payload to transmit")
    src_group.add_argument("--file", help="Path to binary/text file to transmit")
    p_send.add_argument(
        "--mode",
        choices=("metamorphic", "holographic"),
        default="metamorphic",
        help="Transport mode",
    )
    p_send.add_argument(
        "--kill",
        default="",
        help="Comma-separated lane IDs to disable (e.g. GHOST_127,WSL_PERMUTE)",
    )
    p_send.add_argument(
        "--drop",
        type=float,
        default=0.0,
        help="Injected packet drop rate in [0.0, 0.9]",
    )
    p_send.add_argument(
        "--corrupt-lan",
        action="store_true",
        help="Invert 100% of random noise payload bytes on LAN_LENGTH",
    )

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

    if args.command == "send":
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
        )
        env = probe_environment()
        rx = ChimeraReceiver(env, droplet_size=20)
        offer = rx.start()
        try:
            tx = ChimeraSender(env, offer)
            if args.mode == "holographic":
                recovered, report = tx.send_holographic(rx, payload, fault)
            else:
                recovered, report = tx.send_metamorphic(rx, payload, fault)
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
