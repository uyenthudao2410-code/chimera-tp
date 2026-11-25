"""Tests for CHIMERA-HYPER v3.0 Zero-Weight HyperGrid (5 Pillars)."""

from __future__ import annotations

import gzip
import json
import os
import random
import socket
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from chimera_tp.active_pipe import ActiveQueryServer, ComputePlan, remote_active_query
from chimera_tp.autopilot import GENOMES, OpsConfig, TelemetryStore, get_zero_weight_status
from chimera_tp.dashboard import ChimeraDaemon
from chimera_tp.fabric import BeamServer
from chimera_tp.hyper_wire import ImmortalMultiPathReceiver, ImmortalMultiPathSender
from chimera_tp.merkle_sync import (
    ShadowMerkleIndex,
    diff_manifests,
    merkle_beam_sync,
    pack_merkle_patch,
    unpack_merkle_patch,
)
from chimera_tp.telepathy import (
    DomainDictionary,
    TelepathicCodec,
    TelepathicStore,
    benchmark_compression,
    train_domain_dictionary,
)


class TestChimeraV3HyperGrid(unittest.TestCase):
    def test_telepathic_dict_and_lossless_beating_plain_zlib(self) -> None:
        lines = [
            f"[2026-09-28 17:{10 + (i % 45):02d}:{i % 60:02d}] [HR] ERROR: git fetch thất bại repo_id={i % 7}\n".encode("utf-8")
            for i in range(1800)
        ]
        train_corpus = b"".join(lines[:600])
        test_corpus = b"".join(lines[600:])

        with tempfile.TemporaryDirectory() as tmp:
            store = TelepathicStore(Path(tmp) / "dicts")
            d = train_domain_dictionary([train_corpus], domain="hr_git_logs")
            store.put(d)
            loaded = store.get(d.dict_id)
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.zdict, d.zdict)  # type: ignore[union-attr]

            bench = benchmark_compression(test_corpus, loaded)  # type: ignore[arg-type]
            self.assertTrue(bench["lossless_ok"])
            self.assertGreater(bench["vs_raw_saved_pct"], 94.0)
            self.assertLess(bench["telepathic_bytes"], bench["plain_zlib_bytes"])

            # Verify CRLF + mixed-binary edge preservation
            edge = b"\xffbinary\r\n" + train_corpus[:4096] + b"\xffno-trailing-nl"
            codec = TelepathicCodec()
            frame, _ = codec.encode(edge, domain_dict=d)
            self.assertEqual(codec.decode(frame, store=store), edge)

    def test_merkle_shadow_sync_and_0rtt_noop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tdir = Path(tmp)
            src = tdir / "src"
            dst = tdir / "dst"
            shadow_file = tdir / "shadow.json"
            (src / "sub").mkdir(parents=True)
            (src / ".git").mkdir()
            (src / ".git" / "ignored.txt").write_text("skip-me", encoding="utf-8")
            for i in range(8):
                (src / "sub" / f"f_{i}.txt").write_text(f"payload-{i}-" * 80, encoding="utf-8")
            (src / "keep.txt").write_text("root-keep", encoding="utf-8")
            (src / "drop_later.txt").write_text("will-delete", encoding="utf-8")

            idx1 = ShadowMerkleIndex(shadow_file)
            s1 = idx1.scan(src)
            self.assertEqual(s1.total_files, 10)
            self.assertEqual(s1.rehashed_files, 10)

            # Second scan on unchanged tree: 0 files re-hashed!
            idx2 = ShadowMerkleIndex(shadow_file)
            s2 = idx2.scan(src)
            self.assertEqual(s2.root_hash, s1.root_hash)
            self.assertEqual(s2.rehashed_files, 0)

            # Full initial patch -> dst
            d1 = diff_manifests(s2.files, s2.root_hash, {}, "")
            p1 = pack_merkle_patch(src, d1["changed_files"], d1["deleted_files"])
            u1 = unpack_merkle_patch(p1, dst)
            self.assertEqual(u1["root_hash"], s2.root_hash)
            self.assertEqual(u1["total_files"], 10)

            # Mutate 1 file and delete 1 file -> sparse patch touches only 1 write + 1 delete
            (src / "sub" / "f_3.txt").write_text("mutated-payload", encoding="utf-8")
            (src / "drop_later.txt").unlink()
            s3 = ShadowMerkleIndex(shadow_file).scan(src)
            dst_snap = ShadowMerkleIndex().scan(dst)
            d2 = diff_manifests(s3.files, s3.root_hash, dst_snap.files, dst_snap.root_hash)
            self.assertFalse(d2["identical"])
            self.assertEqual(d2["changed_files"], ["sub/f_3.txt"])
            self.assertEqual(d2["deleted_files"], ["drop_later.txt"])

            p2 = pack_merkle_patch(src, d2["changed_files"], d2["deleted_files"])
            u2 = unpack_merkle_patch(p2, dst)
            self.assertEqual(u2["root_hash"], s3.root_hash)
            self.assertFalse((dst / "drop_later.txt").exists())

            # Traversal guard
            bad_bundle = b"CHMRK1" + (
                len(b'{"deleted":["../escape.txt"],"count":0}').to_bytes(4, "little")
                + b'{"deleted":["../escape.txt"],"count":0}'
            )
            with self.assertRaises(ValueError):
                unpack_merkle_patch(bad_bundle, dst)

    def test_fluid_pushdown_analytics_multigrep_and_sqlite_ro(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "workspace"
            sub = root / "services"
            sub.mkdir(parents=True)
            log_file = root / "service.log"
            log_file.write_text(
                "\n".join(
                    [
                        "2026-11-25 10:01:02 INFO [AUTH] ok id=101 ip=10.0.0.1",
                        "2026-11-25 10:02:02 ERROR [GIT] timeout id=202 ip=10.0.0.2",
                        "2026-11-25 11:03:02 ERROR [GIT] timeout id=303 ip=10.0.0.3",
                        "2026-11-25 11:04:02 WARN [CACHE] miss key=deadbeef01",
                    ]
                    * 150
                )
                + "\n",
                encoding="utf-8",
            )
            (sub / "app.py").write_text("def run():\n    return 'CRITICAL_TOKEN_XYZ'\n", encoding="utf-8")

            db_file = root / "metrics.db"
            conn = sqlite3.connect(str(db_file))
            conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT, val REAL)")
            conn.execute("INSERT INTO items VALUES (1, 'alpha', 12.5), (2, 'beta', 99.0)")
            conn.commit()
            conn.close()

            store = TelepathicStore(Path(tmp) / "dicts")
            dd = train_domain_dictionary([log_file.read_bytes()], domain="svc")
            store.put(dd)

            qsrv = ActiveQueryServer("127.0.0.1", 0, allowed_roots=[root], telepathy_store=store).start()
            try:
                # 1) log_analytics
                res_a, meta_a = remote_active_query(
                    qsrv.addr, str(log_file), ComputePlan(op="log_analytics", use_telepathy=True)
                )
                rep_a = json.loads(res_a.output_bytes.decode("utf-8"))
                self.assertEqual(rep_a["total_lines"], 600)
                self.assertEqual(rep_a["severity_counts"]["ERROR"], 300)
                self.assertEqual(rep_a["unique_templates"], 3)
                self.assertGreater(res_a.wire_reduction_pct, 80.0)

                # 2) multi_grep on directory
                res_g, _ = remote_active_query(
                    qsrv.addr,
                    str(root),
                    ComputePlan(op="multi_grep", patterns=("CRITICAL_TOKEN_XYZ",), file_glob="*.py"),
                )
                self.assertEqual(res_g.matched_records, 1)
                self.assertIn("services/app.py:2:", res_g.output_bytes.decode("utf-8"))

                # 3) sqlite_query SELECT allowed, DELETE/DROP rejected
                res_s, _ = remote_active_query(
                    qsrv.addr,
                    str(db_file),
                    ComputePlan(op="sqlite_query", sql="SELECT name, val FROM items ORDER BY id DESC;"),
                )
                sq = json.loads(res_s.output_bytes.decode("utf-8"))
                self.assertEqual(sq["row_count"], 2)
                self.assertEqual(sq["rows"][0][0], "beta")

                with self.assertRaises(RuntimeError):
                    remote_active_query(
                        qsrv.addr,
                        str(db_file),
                        ComputePlan(op="sqlite_query", sql="DROP TABLE items"),
                    )

                # 4) remote_digest
                res_d, _ = remote_active_query(qsrv.addr, str(root), ComputePlan(op="remote_digest"))
                dg = json.loads(res_d.output_bytes.decode("utf-8"))
                self.assertEqual(dg["kind"], "directory")
                self.assertGreaterEqual(dg["total_files"], 3)
            finally:
                qsrv.close()

    def test_immortal_multipath_survives_midstream_blackout(self) -> None:
        binds: list[tuple[str, int]] = [("127.0.0.1", 0)]
        try:
            s6 = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
            s6.bind(("::1", 0))
            s6.close()
            binds.append(("::1", 0))
        except OSError:
            binds.append(("127.0.0.1", 0))

        rx = ImmortalMultiPathReceiver(binds, gen_k=32, sym_size=1180).start()
        try:
            payload = random.Random(300).randbytes(256 * 1024)
            sender = ImmortalMultiPathSender(rx.addrs, gen_k=32, sym_size=1180, initial_loss_hint=0.04)
            rep = sender.send_stream(payload, stream_id=17, timeout_s=10.0, chaos_kill_lane=0, chaos_kill_after_gens=1)
            got, rx_meta = rx.wait_stream_stats(17, timeout_s=5.0)
            self.assertEqual(got, payload)
            self.assertTrue(rep.sha256_match)
            self.assertTrue(rep.survived_blackout)
            self.assertEqual(rep.reconnects, 0)
            self.assertGreater(rep.lane_tx_counts[0], 0)
            self.assertGreater(rep.lane_tx_counts[1], rep.lane_tx_counts[0])
            self.assertEqual(rx_meta["sha256"], rep.sha256)
        finally:
            rx.close()

    def test_v3_daemon_zero_weight_and_contextual_bandit(self) -> None:
        zw = get_zero_weight_status()
        self.assertGreater(zw["daemon_ram_mb"], 0.0)
        # Verify fresh daemon/module process RSS stays strictly under 80 MB budget
        proc = subprocess.run(
            [
                sys.executable,
                "-c",
                "import json; from chimera_tp.autopilot import get_zero_weight_status; print(json.dumps(get_zero_weight_status()))",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        fresh_zw = json.loads(proc.stdout.strip())
        self.assertGreater(fresh_zw["daemon_ram_mb"], 0.0)
        self.assertTrue(fresh_zw["zero_weight_ok"], f"Unexpected fresh RSS: {fresh_zw}")

        with tempfile.TemporaryDirectory() as tmp:
            ops = Path(tmp) / "ops"
            # Contextual 24h bandit separation test
            store = TelemetryStore(ops / "ctx.db")
            try:
                for gid in GENOMES:
                    store.record_run(
                        {
                            "ts_utc": "2026-11-25T02:00:00+00:00",
                            "ts_local": "2026-11-25 02:00:00",
                            "time_bucket": "NIGHT_CLEAN",
                            "trigger": "daily",
                            "profile": "auto-darwin",
                            "health_score": 100,
                            "anomalies": [],
                            "local": {"gfni_speedup": 80.0, "wormhole_gbps": 5.0, "wan_5pct_speedup": 40.0},
                            "peer": {"reachable": False},
                        },
                        genome_id=gid,
                        reward=9.5 if gid == "G3_TURBO_BULK" else 4.0,
                    )
                    store.record_run(
                        {
                            "ts_utc": "2026-11-25T20:00:00+00:00",
                            "ts_local": "2026-11-25 20:00:00",
                            "time_bucket": "PEAK_EVENING",
                            "trigger": "daily",
                            "profile": "auto-darwin",
                            "health_score": 100,
                            "anomalies": [],
                            "local": {"gfni_speedup": 80.0, "wormhole_gbps": 5.0, "wan_5pct_speedup": 18.0},
                            "peer": {"reachable": False},
                        },
                        genome_id=gid,
                        reward=9.5 if gid == "G2_LOSSY_ARMOR" else 4.0,
                    )
                self.assertEqual(store.select_genome("auto-darwin", hour=2)[0], "G3_TURBO_BULK")
                self.assertEqual(store.select_genome("auto-darwin", hour=20)[0], "G2_LOSSY_ARMOR")
                st = store.get_dashboard_state()
                self.assertEqual(st["recommended_sync_window"], "NIGHT_CLEAN")
            finally:
                store.close()

            cfg = OpsConfig(
                node_name="v3-test-node",
                role="controller",
                dashboard_bind="127.0.0.1:0",
                beam_port=0,
                rpc_v4_port=0,
                rpc_v6_port=-1,
                query_port=0,
                warp_port=0,
                watched_query_file="@synthetic",
            )
            daemon = ChimeraDaemon(config=cfg, ops_dir=ops / "daemon", auto_seed_on_empty=False).start()
            base = f"http://127.0.0.1:{daemon.http_addr[1]}"
            try:
                h = json.loads(urllib.request.urlopen(f"{base}/api/health", timeout=5.0).read().decode())
                self.assertIn(h["version"], ("3.0.0", "4.0.0", "5.0.0", "6.0.0", "7.0.0"))
                self.assertGreater(h["zero_weight"]["daemon_ram_mb"], 0.0)
                self.assertIn("zero_weight_ok", h["zero_weight"])

                req_m = urllib.request.Request(
                    f"{base}/api/live-merkle",
                    data=json.dumps({}).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                mrep = json.loads(urllib.request.urlopen(req_m, timeout=15.0).read().decode())
                self.assertTrue(mrep["verified_root_match"])
                self.assertTrue(mrep["second_pass_noop"])

                req_f = urllib.request.Request(
                    f"{base}/api/live-fluid",
                    data=json.dumps({"op": "log_analytics", "file_path": "@synthetic"}).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                frep = json.loads(urllib.request.urlopen(req_f, timeout=15.0).read().decode())
                self.assertGreater(frep["wire_reduction_pct"], 95.0)

                req_i = urllib.request.Request(f"{base}/api/live-immortal", data=b"", method="POST")
                irep = json.loads(urllib.request.urlopen(req_i, timeout=15.0).read().decode())
                self.assertTrue(irep["survived_blackout"])
                self.assertTrue(irep["peer_sha256_match"])
            finally:
                daemon.close()

    def test_cluster_hub_ingest_and_markdown_evaluation_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ops = Path(tmp) / "hub"
            cfg = OpsConfig(
                node_name="svhome-hub",
                role="server",
                dashboard_bind="127.0.0.1:0",
                beam_port=0,
                rpc_v4_port=0,
                rpc_v6_port=-1,
                query_port=0,
                warp_port=0,
            )
            daemon = ChimeraDaemon(config=cfg, ops_dir=ops, auto_seed_on_empty=False).start()
            base = f"http://127.0.0.1:{daemon.http_addr[1]}"
            try:
                sample_ctrl = {
                    "version": "3.0.0",
                    "node_name": "win-desktop",
                    "role": "controller",
                    "ts_utc": "2026-11-25T05:40:00+00:00",
                    "ts_local": "2026-11-25 12:40:00",
                    "time_bucket": "AFTERNOON",
                    "trigger": "daily",
                    "profile": "auto-darwin",
                    "genome_id": "G2_LOSSY_ARMOR",
                    "health_score": 100,
                    "zero_weight": {"daemon_ram_mb": 19.5, "host_free_ram_gb": 10.5, "cpu_threads": 12},
                    "local": {
                        "gfni_speedup": 95.2,
                        "wormhole_gbps": 8.1,
                        "wan_5pct_speedup": 31.4,
                        "telepathy_zlib_bytes": 860,
                        "telepathy_wire_bytes": 669,
                        "telepathy_vs_raw_pct": 98.98,
                    },
                    "peer": {
                        "reachable": True,
                        "peer_name": "svhome-hub",
                        "beam_ok": True,
                        "beam_speedup": 4.6,
                        "beam_saved_pct": 96.9,
                        "query_ok": True,
                        "query_speedup": 9.5,
                        "query_saved_pct": 99.15,
                        "query_codec_mode": "telepathic_fold_zdict",
                        "merkle": {"verified_root_match": True, "total_reduction_pct": 96.84},
                        "immortal_ok": True,
                        "immortal": {"ok": True, "lane_tx": [18, 170], "lane_rx": [8, 120]},
                    },
                }
                req = urllib.request.Request(
                    f"{base}/api/cluster/ingest",
                    data=json.dumps(sample_ctrl).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                ing = json.loads(urllib.request.urlopen(req, timeout=5.0).read().decode("utf-8"))
                self.assertTrue(ing["ok"])

                st = json.loads(urllib.request.urlopen(f"{base}/api/status", timeout=5.0).read().decode("utf-8"))
                cl = st["cluster"]
                self.assertEqual(cl["evaluation_verdict"]["grade"], "A+")
                self.assertEqual(len(cl["nodes"]), 1)
                self.assertEqual(cl["nodes"][0]["node_name"], "win-desktop")
                self.assertIsNotNone(cl["latest_cross_host"])

                md = urllib.request.urlopen(f"{base}/api/cluster/report?format=md", timeout=5.0).read().decode("utf-8")
                self.assertIn("win-desktop", md)
                self.assertIn("99.15", md)
                self.assertIn("A+", md)

                # Verify SSR hydration + gzip + ETag 304 caching
                req_html = urllib.request.Request(
                    f"{base}/", headers={"Accept-Encoding": "gzip"}
                )
                with urllib.request.urlopen(req_html, timeout=5.0) as resp_h:
                    self.assertEqual(resp_h.headers.get("Content-Encoding"), "gzip")
                    html_decoded = gzip.decompress(resp_h.read()).decode("utf-8")
                    self.assertIn("svhome-hub", html_decoded)
                    self.assertIn("win-desktop", html_decoded)

                with urllib.request.urlopen(
                    urllib.request.Request(f"{base}/api/status", headers={"Accept-Encoding": "gzip"}),
                    timeout=5.0,
                ) as resp_s:
                    self.assertEqual(resp_s.headers.get("Content-Encoding"), "gzip")
                    etag = resp_s.headers.get("ETag")
                    self.assertTrue(etag)
                    _ = gzip.decompress(resp_s.read())

                req_304 = urllib.request.Request(
                    f"{base}/api/status", headers={"If-None-Match": str(etag)}
                )
                with self.assertRaises(urllib.error.HTTPError) as ctx304:
                    urllib.request.urlopen(req_304, timeout=5.0)
                self.assertEqual(ctx304.exception.code, 304)
            finally:
                daemon.close()
