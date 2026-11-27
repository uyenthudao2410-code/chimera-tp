"""Verify default SDK sync of the registered small svhome telemetry replica over the live PHANTOM session."""

import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import http.client
import json
from pathlib import Path
import sqlite3
import sys
import time
import urllib.parse
import urllib.request


ANCHOR = 9780
NAME = "svhome_telemetry"
MAX_BYTES = 4 * 1024 ** 2
DISCOVERY = "/.well-known/chimera.json"


def get(port, path):
    with closing(http.client.HTTPConnection("127.0.0.1", port, timeout=8)) as connection:
        connection.request("GET", path)
        response = connection.getresponse()
        if response.status != 200:
            raise RuntimeError(f"{path.split('?')[0]} returned HTTP {response.status}")
        data = response.read(512 * 1024 + 1)
        if len(data) > 512 * 1024:
            raise ValueError("unexpectedly large metadata response")
        return json.loads(data)


def route(rollout):
    client = get(ANCHOR, "/api/phantom/status")["client"]
    if not client["connected"] or client["pong_stale"] or client["mode"] != "PHANTOM_5MS_DIRECT":
        raise RuntimeError("the direct data path is unavailable")
    port = client["listeners"][str(ANCHOR)]
    if type(port) is not int or not 0 < port < 65536 or port == ANCHOR:
        raise ValueError("invalid peer HTTP listener")
    sessions = get(port, "/api/phantom/status")["server"]["sessions"]
    active = [s["session_id"] for s in sessions if s.get("punched")]
    if len(active) != 1:
        raise RuntimeError("cannot attribute this transfer to a single PHANTOM session")
    kernels = {}
    for name, endpoint in (("win-desktop", ANCHOR), ("svhome", port)):
        beacon = get(endpoint, DISCOVERY)
        expected = rollout["nodes"][name]
        if (beacon["node_name"] != name or beacon["pid"] != expected["pid"]
                or beacon["started_at"] != expected["started_at"]):
            raise RuntimeError(f"{name} no longer matches the selected rollout")
        kernels[name] = beacon["zero_weight"]["daemon_peak_rss_bytes"]
    return {
        "port": port, "session_id": active[0], "tx": client["tx_bytes"],
        "rx": client["rx_bytes"], "kernel_peaks": kernels,
    }


def registration(port, role):
    entries = get(port, "/v1/vault-sql/status")["databases"]
    matches = [row for row in entries if row["name"] == NAME and row["role"] == role]
    if len(matches) != 1 or not 0 < matches[0]["size_bytes"] <= MAX_BYTES:
        raise ValueError(f"expected the existing small telemetry {role}")
    return matches[0]


def verify_replica(path, receipt, port):
    if Path(receipt["path"]).resolve(strict=True) != path or not 0 < path.stat().st_size <= MAX_BYTES:
        raise ValueError("unexpected replica path or size")
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if digest != receipt["sha256"] or path.stat().st_size != receipt["raw_bytes"]:
        raise ValueError("local bytes differ from the installed receipt")
    uri = path.as_uri() + "?mode=ro&immutable=1"
    with closing(sqlite3.connect(uri, uri=True)) as db:
        if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise ValueError("SQLite rejected the installed replica")
    # Read the metadata of the very same immutable primary generation, even if the live writer advanced.
    query = urllib.parse.urlencode({
        "name": NAME, "protocol": 2, "since_sha256": digest, "target_sha256": digest,
    })
    witness = get(port, "/v1/vault-sql/snapshot?" + query)
    if (not witness.get("ok") or witness.get("protocol") != 2 or witness.get("mode") != "unchanged"
            or witness["sha256"] != digest or witness["raw_bytes"] != receipt["raw_bytes"]
            or witness["changed_pages"] != 0 or witness["wire_bytes"] != 0):
        raise ValueError("the Linux primary did not confirm the exact installed generation")
    return digest


def measure(rollout_path):
    rollout = json.loads(rollout_path.read_bytes())
    if sys.platform != "win32" or rollout["schema"] != "chimera.workstation-rollout/1":
        raise ValueError("expected the workstation rollout on Windows")
    release = Path(rollout["nodes"]["win-desktop"]["root"]).resolve(strict=True)
    sdk = "chimera_tp/platform/client.py"
    if hashlib.sha256((release / sdk).read_bytes()).hexdigest() != rollout["source_sha256"][sdk]:
        raise ValueError("SDK differs from rollout")
    sys.path.insert(0, str(release))
    from chimera_tp.platform.client import ChimeraClient

    urllib.request.install_opener(urllib.request.build_opener(urllib.request.ProxyHandler({})))
    sdk_client = ChimeraClient(app="vault-sql-acceptance", anchor_url=f"http://127.0.0.1:{ANCHOR}",
                               auto_register=False, timeout_s=35)
    if not sdk_client.available:
        raise RuntimeError("local SDK connection unavailable")
    first = route(rollout)
    port = first["port"]
    local = registration(ANCHOR, "replica")
    registration(port, "primary")
    path = Path(local["path"]).resolve(strict=True)
    if path.name != NAME + ".replica.db" or not 0 < path.stat().st_size <= MAX_BYTES:
        raise ValueError("registered destination does not match the expected telemetry replica")
    rounds = []
    for index in range(2):
        start = time.perf_counter()
        receipt = sdk_client.vault_sql_sync(NAME)
        elapsed = round(1000 * (time.perf_counter() - start), 3)
        if (not receipt.get("ok") or receipt.get("name") != NAME
                or receipt.get("peer_base") != f"http://127.0.0.1:{port}"):
            raise ValueError("the default SDK call did not use the live direct peer listener")
        digest = verify_replica(path, receipt, port)
        state = route(rollout)
        if ((state["port"], state["session_id"]) != (port, first["session_id"])
                or state["tx"] < first["tx"] or state["rx"] < first["rx"]):
            raise RuntimeError("transport changed during acceptance")
        rounds.append({
            "ordinal": index + 1, "sdk_wall_ms": elapsed, "protocol": receipt["protocol"],
            "mode": receipt["mode"], "changed_pages": receipt["changed_pages"],
            "raw_bytes": receipt["raw_bytes"], "wire_bytes": receipt["wire_bytes"],
            "sha256": digest, "primary_generation_confirmed": True, "integrity_check": "ok",
            "route": state,
        })
    return {
        "schema": "chimera.live-vault-sql-route/1", "verified_utc": datetime.now(timezone.utc).isoformat(),
        "release": rollout["release"], "database": NAME, "direction": "svhome to win-desktop",
        "sdk_method": "ChimeraClient.vault_sql_sync(name)", "peer_base_override": False,
        "initial_registered_digest": local.get("last_sha256"), "route_before": first, "rounds": rounds,
        "byte_scope": "wire_bytes counts encoded page data only. PHANTOM counters include all concurrent traffic.",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rollout", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("choose a new receipt path")
    report = measure(args.rollout)
    with args.out.open("x", encoding="utf-8") as file:
        json.dump(report, file, indent=2)
        file.write("\n")
    for row in report["rounds"]:
        print(f"{row['ordinal']}: {row['mode']}, {row['raw_bytes']} bytes, SDK {row['sdk_wall_ms']} ms")
