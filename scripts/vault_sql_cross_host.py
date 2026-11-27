"""Origin, receiver and guarded dispatch for the cross-host SQLite acceptance test."""

import argparse
import base64
from contextlib import closing, contextmanager
import hashlib
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import platform
import random
import secrets
import shutil
import socket
import sqlite3
import stat
import sys
import tempfile
import threading
import time
from urllib.parse import parse_qs, urlsplit


ROWS = 360
OPERATIONS = ("cold", "damaged", "delta", "unchanged", "stale")
MAX_HTTP_BODY = 2 * 1024 ** 2


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def tell(event):
    print(json.dumps(event, separators=(",", ":")), flush=True)


class Handler(BaseHTTPRequestHandler):
    def reply(self, code, body):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@contextmanager
def serve(handler):
    with ThreadingHTTPServer(("127.0.0.1", 0), handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield server.server_port
        finally:
            server.shutdown()
            thread.join(timeout=3)


def verify_db(path, revision):
    uri = path.resolve(strict=True).as_uri() + "?mode=ro&immutable=1"
    with closing(sqlite3.connect(uri, uri=True)) as db:
        checked = db.execute("PRAGMA integrity_check").fetchall()
        count, total = db.execute("SELECT count(*), sum(rev) FROM docs").fetchone()
        row = db.execute("SELECT rev,length(payload) FROM docs WHERE id=?", (ROWS//2,)).fetchone()
    assert checked == [("ok",)] and (count, total, row) == (ROWS, revision, (revision, 3080))
    return {"sha256": digest(path), "bytes": path.stat().st_size, "rows": count,
            "selected_rev": row[0], "sum_rev": total, "integrity_check": "ok"}


def oracle(source, dest, revision):
    with closing(sqlite3.connect(source.as_uri()+"?mode=ro", uri=True)) as live, closing(sqlite3.connect(dest)) as target:
        target.execute("PRAGMA journal_mode=OFF")
        live.backup(target)
    return verify_db(dest, revision)


def origin_at(root):
    from chimera_tp.autopilot import OpsConfig
    from chimera_tp.dashboard import ChimeraDaemon

    db_path = root / "windows.sqlite"
    token = secrets.token_hex(16)
    config = OpsConfig(node_name="vault-cross-host-origin", role="controller", peer_ipv4="", peer_ipv6="",
                       dashboard_bind="127.0.0.1:0", beam_port=0, rpc_v4_port=0, rpc_v6_port=-1,
                       query_port=0, warp_port=-1, immortal_v4_port=0, immortal_v6_port=-1,
                       edge_proxy_port=-1, nat_punch_port=0, phantom_enabled=False,
                       allowed_query_roots=[str(root)], search_roots=[], edge_targets={})
    daemon = ChimeraDaemon(config=config, ops_dir=root/"ops", auto_seed_on_empty=False).start()
    try:
        with closing(sqlite3.connect(db_path, check_same_thread=False)) as writer:
            writer.executescript("PRAGMA page_size=4096; PRAGMA journal_mode=WAL; PRAGMA wal_autocheckpoint=0;"
                                 "CREATE TABLE docs(id INTEGER PRIMARY KEY, rev INTEGER, payload BLOB);")
            rng = random.Random(20261126)
            writer.executemany("INSERT INTO docs VALUES(?,0,?)", ((i, rng.randbytes(3080)) for i in range(ROWS)))
            writer.commit()
            writer.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            daemon.platform.vault_sql.register_db("sample", db_path)
            proofs = {"cold": oracle(db_path, root/"independent-cold.db", 0)}
            calls, phases, lock = [], [], threading.Lock()

            class Origin(Handler):
                def do_POST(self):
                    with lock:
                        index = len(phases)
                        expected = OPERATIONS[index] if index < len(OPERATIONS) else None
                        if self.path != f"/{token}/phase/{expected}" or expected is None:
                            return self.reply(409, b"{}")
                        if expected == "damaged":
                            writer.execute("UPDATE docs SET rev=1 WHERE id=?", (ROWS//2,))
                            writer.commit()
                            proofs["wal_bytes"] = Path(str(db_path)+"-wal").stat().st_size
                            assert proofs["wal_bytes"] and verify_db(db_path, 0)["selected_rev"] == 0
                            writer.execute("UPDATE docs SET rev=2 WHERE id=?", (ROWS//2,))
                            proofs["transaction_open"] = writer.in_transaction
                            proofs["uncommitted_revision"] = writer.execute(
                                "SELECT rev FROM docs WHERE id=?", (ROWS//2,)).fetchone()[0]
                            proofs["committed"] = oracle(db_path, root/"independent-committed.db", 1)
                        phases.append(expected)
                    self.reply(200, b"{}")

                def do_GET(self):
                    parsed = urlsplit(self.path)
                    query = parse_qs(parsed.query)
                    if (not phases or parsed.path != f"/{token}/v1/vault-sql/snapshot" or
                            query.get("name") != ["sample"] or query.get("protocol") != ["2"]):
                        return self.reply(404, b"{}")
                    with closing(http.client.HTTPConnection("127.0.0.1", daemon.http_addr[1], timeout=15)) as link:
                        link.request("GET", "/v1/vault-sql/snapshot?"+parsed.query)
                        response = link.getresponse()
                        body = response.read(MAX_HTTP_BODY+1)
                        assert response.status == 200 and len(body) <= MAX_HTTP_BODY
                    data = json.loads(body)
                    phase = phases[-1]
                    if phase == "damaged":
                        assert data["mode"] == "delta"
                        data["sha256"] = "0"*64
                        body = json.dumps(data, separators=(",", ":")).encode()
                    calls.append({"phase": phase, "mode": data["mode"], "since": query.get("since_sha256", [""])[0],
                                  "start_page": data["start_page"], "changed_pages": data["changed_pages"],
                                  "body_bytes": len(body), "body_sha256": hashlib.sha256(body).hexdigest()})
                    self.reply(200, body)

            with serve(Origin) as port:
                tell({"event": "ready", "port": port, "token": token, "os": platform.system()})
                if sys.stdin.readline().strip() != "finish":
                    raise RuntimeError("origin_controller_disconnected")
            writer.rollback()
            return {"oracle": proofs, "responses": calls, "phases": phases, "host": platform.node(),
                    "os": platform.system(), "sqlite": sqlite3.sqlite_version}
    finally:
        daemon.close()


def receive():
    from chimera_tp.platform.vault_sql import VaultSqlFabric

    settings = json.loads(Path("settings.json").read_text(encoding="utf-8"))
    unix = Path(settings["socket"])
    assert unix.parent == Path("/run/user") / str(os.getuid()) and stat.S_ISSOCK(unix.stat().st_mode)
    assert unix.stat().st_uid == os.getuid() and unix.parent.stat().st_mode & 0o077 == 0
    prefix = "/" + settings["token"]
    calls = []

    class Forward(http.client.HTTPConnection):
        def connect(self):
            self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.sock.settimeout(self.timeout)
            self.sock.connect(str(unix))

    class Receiver(Handler):
        def do_GET(self):
            if urlsplit(self.path).path != prefix+"/v1/vault-sql/snapshot":
                return self.reply(404, b"{}")
            with closing(Forward("localhost", timeout=18)) as link:
                link.request("GET", self.path)
                response = link.getresponse()
                body = response.read(MAX_HTTP_BODY+1)
                assert response.status == 200 and len(body) == int(response.getheader("Content-Length")) <= MAX_HTTP_BODY
            calls.append({"body_bytes": len(body), "body_sha256": hashlib.sha256(body).hexdigest()})
            self.reply(200, body)

    receipts = {}
    with tempfile.TemporaryDirectory(prefix="guarded-sql-replica-", dir=".") as dirname, serve(Receiver) as port:
        fabric = VaultSqlFabric(Path(dirname))
        replica = Path(dirname) / "sample.replica.db"
        for operation in OPERATIONS:
            with closing(Forward("localhost", timeout=15)) as link:
                link.request("POST", prefix+"/phase/"+operation, body=b"")
                response = link.getresponse()
                assert response.status == 200 and response.read(64) == b"{}"
            previous = {"sha256": digest(replica)} if replica.is_file() else None
            if operation == "stale":
                with closing(sqlite3.connect(replica)) as db:
                    db.execute("PRAGMA journal_mode=DELETE")
                    db.execute("UPDATE docs SET rev=77 WHERE id=?", (ROWS//2,))
                    db.commit()
                previous = verify_db(replica, 77)
            first, started = len(calls), time.perf_counter()
            try:
                result = fabric.sync_from_peer("sample", f"http://127.0.0.1:{port}"+prefix)
            except ValueError as exc:
                if operation != "damaged" or "digest" not in str(exc):
                    raise
                result = {"mode": "rejected", "reason": str(exc)}
            elapsed = round((time.perf_counter()-started)*1000, 3)
            confirmed = verify_db(replica, 0 if operation in ("cold","damaged") else 1)
            if operation == "damaged":
                assert result["mode"] == "rejected" and confirmed["sha256"] == previous["sha256"]
            else:
                expected = {"cold":"full", "delta":"delta", "unchanged":"unchanged", "stale":"full"}[operation]
                assert result["mode"] == expected and result["sha256"] == confirmed["sha256"]
            receipts[operation] = {"receipt": {k: result[k] for k in ("mode","reason","changed_pages","parts",
                                   "wire_bytes","source_backup_created") if k in result},
                                   "before": previous, "after": confirmed, "elapsed_ms": elapsed,
                                   "responses": calls[first:]}
    record = {"host": platform.node(), "os": platform.system(), "sqlite": sqlite3.sqlite_version,
              "phases": receipts, "temporary_replica_removed": not Path(dirname).exists()}
    Path("linux.json").write_text(json.dumps(record), encoding="utf-8")


def dispatch(peer, unix, token):
    from chimera_tp.platform.guarded_build import submit

    source = Path(__file__).resolve()
    repo = source.parents[1]
    with tempfile.TemporaryDirectory(prefix="vault-cross-source-") as dirname:
        stage = Path(dirname)
        for rel in ("chimera_tp/__init__.py", "chimera_tp/platform/__init__.py", "chimera_tp/platform/agent_workspace.py",
                    "chimera_tp/platform/vault_sql.py", "chimera_tp/platform/vault_sql_pages.py"):
            path = stage/rel
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(repo/rel, path)
        shutil.copyfile(source, stage/"trial.py")
        (stage/"settings.json").write_text(json.dumps({"socket":unix, "token":token}), encoding="utf-8")
        command = "python3 -I -B -S -c \"import runpy,sys;sys.path.insert(0,'.');runpy.run_path('trial.py',run_name='__main__')\" --guest"
        deadline = time.monotonic()+35
        while True:
            receipt = submit(command, cwd=stage, peer=peer, timeout_s=110, artifacts=["linux.json"],
                             admission_policy={"runtime_seconds":125, "job_disk_mib":64, "job_memory_mib":192,
                                               "service_urls":["http://127.0.0.1:8787/api/health"]})
            if receipt.get("ok"):
                break
            if (receipt.get("state") != "deferred" or "guest_slot_busy" not in str(receipt.get("error"))
                    or time.monotonic() >= deadline):
                raise RuntimeError(str({k:receipt.get(k) for k in ("state","error","stderr")}))
            time.sleep(2)
        assert receipt["delivery"] == "executed" and receipt["admission"]["limits_verified"]
        item = receipt["artifacts"]["linux.json"]
        raw = base64.b64decode(item["base64"], validate=True)
        assert len(raw) == item["bytes"] and hashlib.sha256(raw).hexdigest() == item["sha256"]
        summary = {k:receipt[k] for k in ("attempt_id","target","snapshot","client_timing_ms","elapsed_end_to_end_ms")}
        summary.update(guard_limits_verified=True, effective_policy=receipt["admission"]["effective_policy"])
    return {"worker":summary, "linux":json.loads(raw), "stage_removed":not stage.exists()}


if __name__ == "__main__":
    if sys.argv[1:] == ["--guest"]:
        receive()
    else:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("--origin", action="store_true")
        parser.add_argument("--dispatch", nargs=3, metavar=("PEER","UNIX_SOCKET","TOKEN"))
        args = parser.parse_args()
        if args.origin:
            with tempfile.TemporaryDirectory(prefix="windows-sql-fixture-") as work:
                result = origin_at(Path(work).resolve())
            tell({"event":"finished", "origin":result, "temporary_origin_removed":not Path(work).exists()})
        elif args.dispatch:
            tell(dispatch(*args.dispatch))
        else:
            parser.error("choose --origin or --dispatch")
