"""Verify the new SDK/HTTP build path on a private loopback anchor and a real SSH peer."""

from __future__ import annotations

import argparse
import base64
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shlex
import sys
import tempfile
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from chimera_tp.autopilot import OpsConfig
from chimera_tp.dashboard import ChimeraDaemon
from chimera_tp.platform.client import ChimeraClient


def check(peer: str) -> dict:
    with tempfile.TemporaryDirectory(prefix="chimera-exile-api-") as temporary:
        root = Path(temporary)
        work = root / "sample"
        work.mkdir()
        data = ("verified-input-" + uuid.uuid4().hex).encode("ascii")
        (work / "source.txt").write_bytes(data)
        expected = b"http-fixture\n" + data
        program = "from pathlib import Path; Path('receipt.bin').write_bytes(b'http-fixture\\n'+Path('source.txt').read_bytes())"
        config = OpsConfig(
            node_name="exile-api-fixture", role="controller", dashboard_bind="127.0.0.1:0",
            beam_port=0, rpc_v4_port=0, rpc_v6_port=-1, query_port=0, warp_port=-1, edge_proxy_port=-1,
            allowed_query_roots=[str(root)], search_roots=[str(work)], edge_targets={}, phantom_enabled=False,
        )
        daemon = ChimeraDaemon(config=config, ops_dir=root / "ops", auto_seed_on_empty=False)
        try:
            daemon.start()
            anchor = daemon.platform.anchor_url
            if anchor.rsplit(":", 1)[-1] == "9780":
                raise RuntimeError("ephemeral anchor coincides with the service port")
            client = ChimeraClient(app="exile-api-fixture", anchor_url=anchor, auto_register=False)
            before = client._get_json("/v1/exile/status")
            if before.get("build_protocol") != 1 or before.get("ssh_host") != peer:
                raise RuntimeError("private anchor did not advertise the expected verified SSH peer")
            command = shlex.join(["python3", "-I", "-B", "-S", "-c", program])
            deferred = Counter()
            deadline = time.monotonic() + 120
            while True:
                result = client.agent_exile(command, cwd=str(work), target="svhome", sync_workspace=True,
                                            artifacts=["receipt.bin"], timeout_s=30)
                if result.get("state") != "deferred" or time.monotonic() >= deadline:
                    break
                reason = result.get("error")
                if reason not in {"guest_slot_busy", "host_load", "service_latency", "cpu_pressure",
                                  "memory_pressure", "io_pressure", "temperature", "ram_reserve"}:
                    break
                deferred[reason] += 1
                time.sleep(4)
            if not result.get("ok"):
                raise RuntimeError(f"private API build failed: {result.get('state')} {result.get('error')}")
            artifact = result["artifacts"]["receipt.bin"]
            if base64.b64decode(artifact["base64"], validate=True) != expected:
                raise ValueError("HTTP artifact bytes disagree with independent Windows output")
            if artifact["sha256"] != hashlib.sha256(expected).hexdigest():
                raise ValueError("HTTP artifact digest disagrees with independent Windows digest")
            spec = json.dumps({"task": "python_compile", "payload": {"files": {"example.py": "count = 42"}}})
            denied = client.agent_exile(spec, target="colab")
            after = client._get_json("/v1/exile/status")
            if (denied.get("state") != "deferred" or denied.get("error") != "colab_budget_required_or_insufficient"
                    or after["runs"] - before["runs"] != sum(deferred.values()) + 2):
                raise RuntimeError(f"unexpected zero-budget reply {denied!r}, runs {before['runs']} to {after['runs']}")
            report = {
                "schema": "chimera.exile-sdk-http/1",
                "verified_utc": datetime.now(timezone.utc).isoformat(),
                "listen_url": anchor, "build_protocol": before["build_protocol"], "peer": peer,
                "server_calls": after["runs"] - before["runs"],
                "deferred_before_execution": dict(deferred),
                "build": {
                    "state": result["state"], "delivery": result["delivery"], "snapshot": result["snapshot"],
                    "attempt_id": result["attempt_id"], "end_to_end_ms": result["elapsed_end_to_end_ms"],
                    "artifact_sha256": artifact["sha256"], "artifact_bytes": artifact["bytes"],
                    "matches_independent_bytes": True,
                },
                "cloud_without_budget": {"state": denied["state"], "error": denied["error"]},
            }
        finally:
            daemon.close()
    report["temporary_tree_removed"] = not root.exists()
    if not report["temporary_tree_removed"]:
        raise OSError("temporary API fixture remains after closing the anchor")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--peer", default="svhome")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    result = json.dumps(check(args.peer), indent=2, ensure_ascii=False) + "\n"
    if args.out:
        args.out.write_text(result, encoding="utf-8")
    sys.stdout.write(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
