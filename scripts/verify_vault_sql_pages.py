"""Measure protocol 2 through an isolated production HTTP daemon and a counted loopback link."""

import argparse
from contextlib import closing, contextmanager
from datetime import datetime, timezone
import hashlib
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import platform
import random
import sqlite3
import sys
import tempfile
import threading
import time
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from chimera_tp.autopilot import OpsConfig
from chimera_tp.dashboard import ChimeraDaemon
from chimera_tp.platform.vault_sql import VaultSqlFabric


@contextmanager
def counting_link(origin):
    upstream = urlsplit(origin)
    calls = []

    class Count(BaseHTTPRequestHandler):
        def do_GET(self):
            with closing(http.client.HTTPConnection(upstream.hostname, upstream.port, timeout=120)) as conn:
                conn.request("GET", self.path)
                with conn.getresponse() as response:
                    payload = response.read()
                    calls.append(len(payload))
                    self.send_response(response.status)
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)

        def log_message(self, *args):
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Count) as proxy:
        thread = threading.Thread(target=proxy.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{proxy.server_port}", calls
        finally:
            proxy.shutdown()
            thread.join(timeout=5)


def verify_replica(result, rows, rev):
    path = Path(result["path"])
    with path.open("rb") as stream:
        assert hashlib.file_digest(stream, "sha256").hexdigest() == result["sha256"]
    with closing(sqlite3.connect(path.as_uri()+"?mode=ro&immutable=1", uri=True)) as db:
        assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert db.execute("SELECT count(*),sum(rev) FROM docs").fetchone() == (rows, rev)
        assert db.execute("SELECT rev FROM docs WHERE id=?", (rows//2,)).fetchone() == (rev,)


def measure(store, link, calls):
    before = len(calls)
    start = time.perf_counter()
    result = store.sync_from_peer("example", link)
    assert result["protocol"] == 2
    receipt = {k: result[k] for k in ("sha256", "mode", "raw_bytes", "parts", "changed_pages",
                                      "wire_bytes", "compressed_bytes", "source_backup_created")}
    replies = calls[before:]
    assert len(replies) == receipt["parts"]
    receipt.update(elapsed_ms=round(1000*(time.perf_counter()-start), 2), http_json_bytes=sum(replies),
                   largest_reply_bytes=max(replies))
    return result, receipt


def trial(root, count):
    cfg = OpsConfig(node_name="sqlite-delta-fixture", role="controller", dashboard_bind="127.0.0.1:0",
                    beam_port=0, rpc_v4_port=0, rpc_v6_port=-1, query_port=0, warp_port=-1,
                    edge_proxy_port=-1, allowed_query_roots=[str(root)], search_roots=[str(root)],
                    edge_targets={}, phantom_enabled=False)
    primary = ChimeraDaemon(config=cfg, ops_dir=root/"ops", auto_seed_on_empty=False).start()
    try:
        uri = "http://127.0.0.1:" + str(primary.http_addr[1])
        replica = VaultSqlFabric(root/"receiver")
        alternate = VaultSqlFabric(root/"cold-receiver")
        source = root / "source.sqlite"
        rng = random.Random(20261126)
        with closing(sqlite3.connect(source)) as writer, counting_link(uri) as (link, calls):
            writer.executescript("PRAGMA page_size=4096; PRAGMA journal_mode=WAL; PRAGMA wal_autocheckpoint=0;"
                                 "CREATE TABLE docs(id INTEGER PRIMARY KEY, rev INTEGER, content BLOB);")
            primary.platform.vault_sql.register_db("example", str(source))
            probe = primary.platform.vault_sql.export_snapshot("example", protocol=2)
            with closing(http.client.HTTPConnection("127.0.0.1", primary.http_addr[1], timeout=10)) as conn:
                conn.request("GET", "/v1/vault-sql/snapshot?name=example&protocol=2&since_sha256="+probe["sha256"])
                payload = json.loads(conn.getresponse().read())
                assert payload.get("mode") == "unchanged", "Production HTTP route must negotiate protocol=2"
            writer.executemany("INSERT INTO docs VALUES(?,0,?)",
                               ((i, rng.randbytes(3500)) for i in range(count)))
            writer.commit()
            writer.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            initialized, full_first = measure(replica, link, calls)
            verify_replica(initialized, count, 0)
            writer.execute("UPDATE docs SET rev=1 WHERE id=?", (count//2,))
            writer.commit()
            wal_bytes = Path(str(source)+"-wal").stat().st_size
            with closing(sqlite3.connect(source.as_uri()+"?immutable=1", uri=True)) as bare:
                main_revision = bare.execute("SELECT rev FROM docs WHERE id=?", (count//2,)).fetchone()[0]
            assert wal_bytes > 0 and main_revision == 0
            writer.execute("UPDATE docs SET rev=2 WHERE id=?", (count//2,))
            updated, delta = measure(replica, link, calls)
            verify_replica(updated, count, 1)
            writer.rollback()
            cold, full_final = measure(alternate, link, calls)
            verify_replica(cold, count, 1)
            assert full_final["sha256"] == delta["sha256"] and full_first["sha256"] != delta["sha256"]
            steady, unchanged = measure(replica, link, calls)
            verify_replica(steady, count, 1)
            assert 1 <= delta["changed_pages"] <= 3 and unchanged["mode"] == "unchanged"
            return {"transport": "Windows loopback HTTP through the production Vault-SQL GET handler",
                    "transaction": "one committed row change in WAL followed by an uncommitted update",
                    "rows": count, "page_size": 4096, "wal_bytes_after_commit": wal_bytes,
                    "main_file_revision_ignoring_WAL": main_revision, "replica_revision": 1,
                    "integrity_check": "ok", "initial_full": full_first, "one_row_delta": delta,
                    "independent_full_same_generation": full_final, "unchanged": unchanged,
                    "http_json_savings_pct": round(100*(1-delta["http_json_bytes"]/full_final["http_json_bytes"]), 5),
                    "elapsed_savings_pct": round(100*(1-delta["elapsed_ms"]/full_final["elapsed_ms"]), 3),
                    "wire_scope": "HTTP JSON response body including metadata and Base64. Headers excluded.",
                    "disk_scope": "Steady unchanged input can reuse a witnessed source image. A changed source still needs a complete online backup and an incoming delta still stages a complete replica."}
    finally:
        primary.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--rows", type=int, default=51200)
    p.add_argument("--out", type=Path)
    args = p.parse_args()
    if not 2 <= args.rows <= 100000:
        p.error("--rows must be between 2 and 100000")
    with tempfile.TemporaryDirectory(prefix="chimera-vault-delta-") as directory:
        result = trial(Path(directory), args.rows)
    result.update(verified_utc=datetime.now(timezone.utc).isoformat(), sqlite=sqlite3.sqlite_version,
                  python=platform.python_version(), temporary_tree_removed=not Path(directory).exists())
    result["source_sha256"] = {}
    for rel in ("chimera_tp/platform/vault_sql.py", "chimera_tp/platform/vault_sql_pages.py",
                "chimera_tp/platform/substrate.py", "scripts/verify_vault_sql_pages.py", "tests/test_vault_sql_delta.py"):
        result["source_sha256"][rel] = hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()
    if args.out:
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=True))


if __name__ == "__main__":
    main()
