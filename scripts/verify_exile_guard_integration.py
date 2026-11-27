"""Check two content-addressed SDK handoffs on a private anchor and a real guarded peer."""

from __future__ import annotations

import argparse
import base64
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
from unittest.mock import patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from chimera_tp.dashboard import ChimeraDaemon, OpsConfig
from chimera_tp.platform import guarded_build
from chimera_tp.platform.client import ChimeraClient
from scripts.exile_guard_queue_check import verify_defer_resume


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def peer_python(peer, source, *arguments):
    require(re.fullmatch(r"[\w][.\w-]*", peer, re.ASCII), "invalid SSH peer")
    command = ["ssh", "-T", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
               "-o", "ConnectTimeout=8", peer, shlex.join(["python3", "-I", "-B", "-S", "-", *arguments])]
    proc = subprocess.run(command, input=source.encode(), capture_output=True, check=True, timeout=25,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return json.loads(proc.stdout)


@contextmanager
def peer_scratch(peer):
    info = peer_python(peer, """
import json, os, pathlib, socket, tempfile
root = pathlib.Path(tempfile.mkdtemp(prefix="chimera-exile-check-")).resolve()
beacon = json.loads((pathlib.Path.home() / ".chimera/runtime.json").read_text())
print(json.dumps({"root": str(root), "node": socket.gethostname(),
                  "beacon_node": beacon.get("node_name"), "pid": beacon.get("pid")}))
""")
    try:
        yield info
    finally:
        info["removed"] = peer_python(peer, """
import json, os, pathlib, shutil, sys, tempfile
path = pathlib.Path(sys.argv[1])
if (path.resolve() != path or path.parent != pathlib.Path(tempfile.gettempdir()).resolve()
        or not path.name.startswith("chimera-exile-check-") or path.stat().st_uid != os.getuid()):
    raise ValueError("unexpected acceptance scratch directory")
shutil.rmtree(path)
print(json.dumps(not path.exists()))
""", info["root"])


@contextmanager
def measure_dispatches(cas_dir):
    # Observe the original transport. Only the location of the receiver's synthetic
    # objects changes. The controller process, SSH, admission and systemd still run.
    phases = []
    submit = guarded_build.submit_isolated

    def measured(command, *, cwd, **options):
        path = Path(cwd) / "request.json"
        request = json.loads(path.read_bytes())
        require(request["cas_dir"] == cas_dir, "unexpected receiver CAS namespace")
        reply = submit(command, cwd=cwd, **options)
        phases.append({
            "action": request["action"], "ok": reply.get("ok"), "state": reply.get("state"),
            "error": reply.get("error"), "delivery": reply.get("delivery"),
            "attempt_id": reply.get("attempt_id"), "node": reply.get("target"),
            "snapshot": reply.get("snapshot"), "ssh_stdin_bytes": reply.get("ssh_request_bytes", 0),
            "elapsed_ms": reply.get("elapsed_end_to_end_ms"),
            "limits_verified": reply.get("admission", {}).get("limits_verified", False),
        })
        if request["action"] == "push":
            phases[-1]["block_count"] = len(request["blocks"])
            phases[-1]["block_payload_bytes"] = sum(request["blocks"].values())
        return reply

    with patch.object(guarded_build, "submit_isolated", side_effect=measured):
        yield phases


def make_step(first, second):
    return {"step_key": "xor", "op": "transform_bytes", "params": {"mask": 93},
            "blocks": {name: {"base64": base64.b64encode(raw).decode("ascii")}
                       for name, raw in (("01-shared.bin", first), ("02-version.bin", second))}}


def check_step(row, shared, version, peer):
    require(row.get("ok"), f"handoff failed: {row.get('steps')}")
    step = row["steps"][0]
    output = bytes(x ^ 93 for x in shared + version)
    expected_sha = hashlib.sha256(output).hexdigest()
    expected_cas = hashlib.blake2s(output, digest_size=16).hexdigest()
    receipt, = row["receipts"]
    require(receipt["output_digest"] == expected_sha and receipt["output_cas_hash"] == expected_cas,
            "remote result differs from independently calculated bytes")
    require(receipt["generation"] == step["generation"] and receipt["node_id"] == peer,
            "generation or execution node differs from journal")
    return {"job_id": row["job_id"], "generation": receipt["generation"], "execution_node": receipt["node_id"],
            "input_digest": receipt["input_digest"], "output_sha256": expected_sha,
            "output_cas_hash": expected_cas, "output_bytes": len(output),
            "raw_input_bytes": len(shared) + len(version), "raw_pushed_bytes": step["wire_bytes"],
            "elapsed_ms": row["elapsed_ms"]}


def check_live(root, peer, scratch):
    config = OpsConfig(node_name="win-exile-check", peer_name=peer, role="controller",
                       dashboard_bind="127.0.0.1:0", query_port=0, beam_port=0,
                       rpc_v4_port=0, rpc_v6_port=-1, edge_proxy_port=-1, warp_port=-1,
                       allowed_query_roots=[str(root)], search_roots=[str(root)],
                       edge_targets={}, phantom_enabled=False)
    daemon = ChimeraDaemon(ops_dir=root / "anchor", config=config, auto_seed_on_empty=False)
    try:
        daemon.start()
        coordinator = daemon.platform.exile_handoff
        engine = daemon.platform.hyper_desk.exile
        engine.ssh_host = peer
        same_dir = scratch["root"]
        coordinator.remote_cas_dir = same_dir
        coordinator.queue_dir = root / "initial-outbox"
        anchor = daemon.platform.anchor_url
        require(anchor.rsplit(":", 1)[-1] != "9780", "fixture anchor uses the service port")
        client = ChimeraClient(app="exile-verification", anchor_url=anchor, auto_register=False)
        shared = os.urandom(64 * 1024)
        variants = (os.urandom(8192), os.urandom(8192))
        results = []
        with measure_dispatches(same_dir) as phases:
            for index, version in enumerate(variants):
                start = len(phases)
                spec = make_step(shared, version)
                job = f"cas-{index}-{uuid4().hex}"
                reply = client.exile_handoff(steps=[spec], job_id=job, prefer_target=peer)
                result = check_step(reply, shared, version, scratch["node"])
                result["phases"] = phases[start:]
                require([p["action"] for p in result["phases"]] == ["query", "push", "execute"],
                        "unexpected dispatch sequence")
                require(all(p["limits_verified"] and p["delivery"] == "executed" and p["snapshot"]
                            and p["node"] == scratch["node"] and p["attempt_id"] and p["ssh_stdin_bytes"] > 0
                            for p in result["phases"]), "missing real admission or SSH stdin measurement")
                result["total_ssh_stdin_bytes"] = sum(p["ssh_stdin_bytes"] for p in result["phases"])
                pushed = result["phases"][1]
                result["push_ssh_stdin_bytes"] = pushed["ssh_stdin_bytes"]
                result["missing_blocks"] = pushed["block_count"]
                require(pushed["block_payload_bytes"] == result["raw_pushed_bytes"],
                        "coordinator byte count differs from block payload in the measured push")
                require(result["missing_blocks"] == 2 - index
                        and result["raw_pushed_bytes"] == len(version) + (0 if index else len(shared)),
                        "unexpected CAS block reuse")
                path = coordinator.cas.objects_dir / result["output_cas_hash"][:2] / result["output_cas_hash"]
                require(hashlib.sha256(path.read_bytes()).hexdigest() == result["output_sha256"],
                        "sender object is missing or corrupt after commit")
                results.append(result)
            before_replay = len(phases)
            replay = client.exile_handoff(steps=[spec], job_id=job, prefer_target=peer)
            stored = client.exile_receipts(job_id=job)["receipts"]
            require(replay["ok"] and replay["steps"][0]["already_completed"] and len(stored) == 1
                    and stored == reply["receipts"] and replay["wire_bytes"] == 0
                    and len(phases) == before_replay, "replay executed or committed again")
            replay_check = {"job_id": job, "committed_receipts": len(stored),
                            "generation": stored[0]["generation"], "new_ssh_requests": len(phases) - before_replay}
        queued = verify_defer_resume(root, peer, client, coordinator, engine)
        return {"jobs": results, "replay": replay_check, "guarded_queue_recovery": queued}
    finally:
        daemon.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--peer", default="svhome")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--fault-report", type=Path, help="Link separately executed local fault trials")
    args = parser.parse_args()
    report = {"schema": "chimera.guarded-exile-integration/1", "ok": False,
              "measured_utc": datetime.now(timezone.utc).isoformat(),
              "scope": "Windows SDK, ephemeral HTTP anchor, actual SSH, Linux peer admission and CAS worker. "
                       "Byte counters measure framed SSH stdin and exclude SSH/TCP overhead and responses."}
    try:
        if args.fault_report is not None:
            raw_faults = args.fault_report.read_bytes()
            faults = json.loads(raw_faults)
            require(faults.get("schema") == "chimera.exile-guard-fault-trials/1"
                    and faults.get("ok") and faults.get("passed_trials") == faults.get("total_trials") == 100,
                    "fault report did not pass the 100-job matrix")
            report["local_fault_trials"] = {
                "report": os.path.relpath(args.fault_report, args.out.parent).replace(os.sep, "/"),
                "sha256": hashlib.sha256(raw_faults).hexdigest(), "passed": faults["passed_trials"],
                "stale_receipts_rejected": faults["delayed_stale_receipts_rejected"],
                "scope": "Windows child-process workers and SQLite, with SSH and Linux admission supplied by a fixture.",
            }
        with tempfile.TemporaryDirectory(prefix="chimera-exile-check-") as raw, peer_scratch(args.peer) as scratch:
            root = Path(raw)
            report["peer"] = scratch
            report.update(check_live(root, args.peer, scratch))
        require(scratch["removed"] and not root.exists(), "fixture cleanup incomplete")
        report["local_fixture_removed"] = True
        report["ok"] = True
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": report["ok"], "error": report.get("error"), "report": str(args.out)}))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
