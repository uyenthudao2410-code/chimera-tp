"""Verification suite for v24 Audit Breakthrough #1: EvidenceLedger, Generation-Fenced Receipts, Intent Verification & Checkpointed Exile Handoff."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import platform
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.parse import urlparse

from chimera_tp.host_governor import HostYieldGovernor
from chimera_tp.platform import build_snapshot, guarded_build, guarded_cas
from chimera_tp.platform.cosmos_entity import ZeroEnvCasStore
from chimera_tp.platform.evidence import EvidenceLedger
from chimera_tp.platform.exile_handoff import (
    CheckpointedExileCoordinator,
    InMemoryWorkerTransport,
)
from chimera_tp.platform.immortal_jobs import ImmortalJobEngine
from chimera_tp.platform.omega_entity import OmegaEntityEngine
from chimera_tp.platform.phantom_silicon import AgentExileEngine
from chimera_tp.platform.pulse_bus import PulseBus
from scripts.bench_exile_handoff import run_fault_injection_benchmark


class _FakeSubstrate:
    def __init__(self, *, ram_mb: float = 34.0, evidence: EvidenceLedger | None = None) -> None:
        self._ram_mb = ram_mb
        self.evidence = evidence
        self._cartridge_enabled = {
            "hyper_desk": True,
            "cosmos_entity": True,
            "egress_membrane": True,
            "diskless_secrets": True,
            "vgpu_pareto": True,
            "immortal_jobs": True,
            "exile": True,
        }

    def capabilities(self) -> dict:
        return {"zero_weight": {"daemon_ram_mb": self._ram_mb}}


class TestV24ExileHandoff(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.ops_dir = self.root / "ops"
        self.ops_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_01_evidence_ledger_ttl_expiry_persistence_and_snapshot(self) -> None:
        ledger = EvidenceLedger(self.ops_dir)
        t0 = 1_700_000_000.0

        # Missing capability -> unverified
        miss = ledger.evaluate("exile", now_epoch=t0)
        self.assertEqual(miss["verification_status"], "unverified")
        self.assertFalse(miss["stale"])
        self.assertEqual(miss["sample_count"], 0)
        self.assertIsNone(miss["last_verified_at"])

        # Record 2 samples -> sample_count increments, JSON persisted
        ledger.record(
            "exile",
            execution_node="svhome",
            fallback_mode=None,
            ttl_s=60.0,
            verified=True,
            metrics={"wire_bytes": 4096},
            receipt_id="job1:s0:g1",
            now_epoch=t0,
        )
        rec2 = ledger.record(
            "exile",
            execution_node="svhome",
            fallback_mode=None,
            ttl_s=60.0,
            verified=True,
            metrics={"wire_bytes": 8192},
            receipt_id="job1:s1:g1",
            now_epoch=t0 + 5.0,
        )
        self.assertEqual(rec2["sample_count"], 2)
        self.assertTrue((self.ops_dir / "evidence_ledger.json").is_file())

        # Reload from disk into a fresh instance
        reloaded = EvidenceLedger(self.ops_dir)
        fresh = reloaded.evaluate("exile", enabled=True, now_epoch=t0 + 30.0)
        self.assertEqual(fresh["verification_status"], "verified")
        self.assertFalse(fresh["stale"])
        self.assertEqual(fresh["execution_node"], "svhome")
        self.assertEqual(fresh["sample_count"], 2)
        self.assertEqual(fresh["receipt_id"], "job1:s1:g1")
        self.assertIn("T", fresh["last_verified_at"])
        self.assertIn("T", fresh["expires_at"])

        # Disabled overrides verified
        dis = reloaded.evaluate("exile", enabled=False, now_epoch=t0 + 30.0)
        self.assertEqual(dis["verification_status"], "disabled")
        self.assertFalse(dis["enabled"])

        # TTL expired -> unverified + stale=True
        expired = reloaded.evaluate("exile", enabled=True, now_epoch=t0 + 66.0)
        self.assertEqual(expired["verification_status"], "unverified")
        self.assertTrue(expired["stale"])

        # Violated while fresh -> violated
        reloaded.record(
            "hyper_desk",
            execution_node="win-desktop",
            fallback_mode="host_lz4",
            ttl_s=120.0,
            verified=False,
            violated=True,
            metrics={"vram_yield_ms": 45.0},
            receipt_id="hd-1",
            now_epoch=t0 + 66.0,
        )
        snap = reloaded.snapshot(
            {"exile": True, "hyper_desk": True, "browser_grid": False},
            now_epoch=t0 + 70.0,
        )
        self.assertFalse(snap["ok"])
        self.assertEqual(snap["capabilities"]["exile"]["verification_status"], "unverified")
        self.assertTrue(snap["capabilities"]["exile"]["stale"])
        self.assertEqual(snap["capabilities"]["hyper_desk"]["verification_status"], "violated")
        self.assertEqual(snap["capabilities"]["browser_grid"]["verification_status"], "disabled")

    def test_02_immortal_jobs_generation_fencing_and_single_commit_authority(self) -> None:
        jobs = ImmortalJobEngine(self.ops_dir / "immortal_jobs.db")
        try:
            jobs.create_job(job_id="fence-job-1", app="test", name="fence", total_steps=1)

            # Reject commit without lease
            no_lease = jobs.commit_step_receipt(
                "fence-job-1", "s0", 0, 1, "svhome", "in-a", "out-a", {"val": 1}
            )
            self.assertFalse(no_lease["ok"])
            self.assertTrue(no_lease["rejected"])
            self.assertEqual(no_lease["reason"], "stale_generation")

            # Acquire gen 1, then bump to gen 2
            l1 = jobs.acquire_step_lease("fence-job-1", "s0", 0, "in-a", "svhome")
            self.assertEqual(l1["generation"], 1)
            self.assertFalse(l1["already_completed"])

            l2 = jobs.acquire_step_lease("fence-job-1", "s0", 0, "in-a", "svhome")
            self.assertEqual(l2["generation"], 2)

            # Reject input_digest mismatch even on active generation
            bad_in = jobs.commit_step_receipt(
                "fence-job-1", "s0", 0, 2, "svhome", "wrong-in", "out-a", {"val": 1}
            )
            self.assertFalse(bad_in["ok"])
            self.assertTrue(bad_in["rejected"])
            self.assertEqual(bad_in["reason"], "input_digest_mismatch")

            # Reject stale gen 1 before gen 2 commits
            stale_pre = jobs.commit_step_receipt(
                "fence-job-1", "s0", 0, 1, "svhome", "in-a", "out-stale", {"val": 99}
            )
            self.assertFalse(stale_pre["ok"])
            self.assertEqual(stale_pre["expected_generation"], 2)
            self.assertEqual(stale_pre["got_generation"], 1)

            # Commit gen 2 atomically
            c2 = jobs.commit_step_receipt(
                "fence-job-1",
                "s0",
                0,
                2,
                "svhome",
                "in-a",
                "out-win",
                {"val": 42},
                output_cas_hash="cas-win",
            )
            self.assertTrue(c2["ok"])
            self.assertFalse(c2["already_completed"])
            self.assertEqual(c2["job_status"], "completed")
            self.assertEqual(c2["receipt"]["generation"], 2)

            # Delayed stale gen 1 arriving AFTER gen 2 commit MUST still be rejected!
            stale_post = jobs.commit_step_receipt(
                "fence-job-1", "s0", 0, 1, "svhome", "in-a", "out-stale", {"val": 99}
            )
            self.assertFalse(stale_post["ok"])
            self.assertTrue(stale_post["rejected"])
            self.assertEqual(stale_post["reason"], "stale_generation")

            # Same-generation duplicate commit is idempotent without overwriting
            dup2 = jobs.commit_step_receipt(
                "fence-job-1", "s0", 0, 2, "svhome", "in-a", "out-other", {"val": 777}
            )
            self.assertTrue(dup2["ok"])
            self.assertTrue(dup2["already_completed"])
            self.assertTrue(dup2["idempotent"])
            self.assertEqual(dup2["cached_result"]["val"], 42)
            self.assertEqual(dup2["receipt"]["output_digest"], "out-win")

            # acquire_step_lease on completed step returns cached result without bumping
            l_after = jobs.acquire_step_lease("fence-job-1", "s0", 0, "in-a", "svhome")
            self.assertTrue(l_after["already_completed"])
            self.assertEqual(l_after["generation"], 2)
            self.assertEqual(l_after["cached_result"]["val"], 42)

            receipts = jobs.get_receipts(job_id="fence-job-1")
            self.assertEqual(len(receipts), 1)
            self.assertEqual(receipts[0]["output_cas_hash"], "cas-win")
            stats = jobs.stats()
            self.assertEqual(stats["durable_receipts"], 1)
            self.assertEqual(stats["stale_receipts_rejected"], 4)
        finally:
            jobs.close()

    def test_03_compile_intent_evidence_fresh_expired_and_violated(self) -> None:
        t0 = 1_700_000_000.0
        ledger = EvidenceLedger(self.ops_dir)
        sub = _FakeSubstrate(ram_mb=32.0, evidence=ledger)
        omega = OmegaEntityEngine(ops_dir=self.ops_dir, substrate=sub)
        inv = {"p99_ms": 25, "monthly_cost_usd": 0, "data_loss": 0, "secret_egress": 0, "host_ram_mb": 80}

        # 1. Missing receipts -> unverified, all None
        p_miss = omega.compile_intent("orders", inv, now_epoch=t0)
        self.assertEqual(p_miss["verification_status"], "unverified")
        for val in p_miss["invariants_satisfied"].values():
            self.assertIsNone(val)

        # 2. Record fresh non-expired receipts with explicit per-invariant booleans -> verified
        ledger.record(
            "intent:orders",
            execution_node="svhome",
            ttl_s=60.0,
            verified=True,
            metrics={
                "p99_latency_ok": True,
                "zero_cost_ok": True,
                "zero_data_loss_gf256_ok": True,
                "zero_secret_egress_dlp_ok": True,
                "host_ram_budget_ok": True,
            },
            receipt_id="int-1",
            now_epoch=t0,
        )
        p_fresh = omega.compile_intent("orders", inv, now_epoch=t0 + 10.0)
        self.assertTrue(p_fresh["ok"])
        self.assertEqual(p_fresh["verification_status"], "verified")
        self.assertTrue(all(v is True for v in p_fresh["invariants_satisfied"].values()))
        self.assertEqual(p_fresh["evidence_receipts"]["fresh_count"], 1)

        # 3. Expired receipts -> revert back to None and unverified
        p_exp = omega.compile_intent("orders", inv, now_epoch=t0 + 90.0)
        self.assertTrue(p_exp["ok"])
        self.assertEqual(p_exp["verification_status"], "unverified")
        for val in p_exp["invariants_satisfied"].values():
            self.assertIsNone(val)
        self.assertGreaterEqual(p_exp["evidence_receipts"]["stale_count"], 1)

        # 4. Violated cartridge receipt -> violated & False
        ledger.record(
            "diskless_secrets",
            execution_node="win-desktop",
            ttl_s=60.0,
            verified=False,
            violated=True,
            metrics={"zero_secret_egress_dlp_ok": False},
            receipt_id="dlp-fail",
            now_epoch=t0 + 95.0,
        )
        p_viol = omega.compile_intent("orders", inv, now_epoch=t0 + 96.0)
        self.assertFalse(p_viol["ok"])
        self.assertEqual(p_viol["verification_status"], "violated")
        self.assertIs(p_viol["invariants_satisfied"]["zero_secret_egress_dlp_ok"], False)

        # 5. RAM violation overrides even verified host_ram_budget_ok
        sub_ram = _FakeSubstrate(ram_mb=120.0, evidence=ledger)
        omega_ram = OmegaEntityEngine(ops_dir=self.ops_dir, substrate=sub_ram)
        ledger.record(
            "intent:orders2",
            execution_node="svhome",
            ttl_s=60.0,
            verified=True,
            metrics={"host_ram_budget_ok": True},
            now_epoch=t0 + 95.0,
        )
        p_ram = omega_ram.compile_intent("orders2", inv, now_epoch=t0 + 96.0)
        self.assertFalse(p_ram["ok"])
        self.assertEqual(p_ram["verification_status"], "violated")
        self.assertIs(p_ram["invariants_satisfied"]["host_ram_budget_ok"], False)

    def test_04_coordinator_pulse_governor_cas_delta_and_agent_exile_no_window(self) -> None:
        jobs = ImmortalJobEngine(self.ops_dir / "jobs.db")
        cas = ZeroEnvCasStore(self.ops_dir / "cas")
        pulse = PulseBus(node_name="win-desktop")
        evidence = EvidenceLedger(self.ops_dir)
        transport = InMemoryWorkerTransport()
        gov = HostYieldGovernor(role="controller", policy="sovereign_only")
        try:
            coord = CheckpointedExileCoordinator(
                jobs=jobs,
                cas=cas,
                pulse=pulse,
                governor=gov,
                evidence=evidence,
                node_name="win-desktop",
                worker_transport=transport,
                remote_target="svhome",
            )
            shared = b"SHARED_BLOCK_" * 200
            r1 = coord.handoff_job(
                [{"step_key": "s0", "blocks": {"a.bin": shared, "b.bin": b"B1" * 128}, "op": "sha256_manifest"}],
                job_id="delta-1",
            )
            self.assertTrue(r1["ok"])
            self.assertTrue(r1["win_cpu_yielded"])
            self.assertEqual(r1["steps"][0]["target_node"], "svhome")

            # Second job shares a.bin; svhome CAS already holds shared block -> smaller wire_bytes!
            r2 = coord.handoff_job(
                [{"step_key": "s0", "blocks": {"a.bin": shared, "c.bin": b"C2" * 64}, "op": "sha256_manifest"}],
                job_id="delta-2",
            )
            self.assertTrue(r2["ok"])
            self.assertEqual(r2["wire_bytes"], len(b"C2" * 64))

            # Pulse dispatch + commit events emitted
            events = pulse.poll(topic="exile.step.*", since=0, limit=20)["events"]
            topics = [e["topic"] for e in events]
            self.assertIn("exile.step.dispatched", topics)
            self.assertIn("exile.step.committed", topics)

            # Evidence recorded for immortal_jobs and exile
            self.assertEqual(evidence.evaluate("immortal_jobs")["verification_status"], "verified")
            self.assertEqual(evidence.evaluate("exile")["verification_status"], "verified")
            self.assertEqual(len(coord.receipts()), 2)
        finally:
            jobs.close()

        # These are the three process boundaries used by the guarded sender on Windows.
        response = {"ok": False, "protocol": guarded_build.PROTOCOL, "state": "deferred"}
        proc = subprocess.CompletedProcess([], 0, stdout=json.dumps(response).encode(), stderr=b"")
        with patch.object(subprocess, "run", return_value=proc) as run:
            guarded_build.submit_isolated("fixture", timeout_s=5)
            build_snapshot._git(self.root, "rev-parse", "--show-toplevel")
            guarded_build._dispatch("svhome", b"fixture", {"require_io_limit": False, "timeout_s": 5}, b"")
        self.assertEqual([call.args[0][0] for call in run.call_args_list], [sys.executable, "git", "ssh"])
        for call in run.call_args_list:
            self.assertEqual(call.kwargs["creationflags"], getattr(subprocess, "CREATE_NO_WINDOW", 0))
            self.assertFalse(call.kwargs.get("shell", False))

    def test_agent_exile_validates_guarded_artifacts_and_executes_cas_worker(self) -> None:
        # Execute the shipped CAS program in a child process. Only the outer Linux
        # admission and transport are supplied by this fixture.
        actions = []
        peer_cas = str(self.root / "receiver")

        def local_submission(command, *, cwd, peer, artifacts, **options):
            self.assertEqual(peer, "svhome")
            self.assertEqual(command, "python3 -I -B -S cas_work.py")
            self.assertFalse(options["reuse"])
            self.assertTrue(options["sync"])
            actions.append(json.loads((cwd / "request.json").read_bytes())["action"])
            snapshot = build_snapshot.capture(cwd, include_data=False)["digest"]
            subprocess.run([sys.executable, "-I", "-B", "-S", "cas_work.py"], cwd=cwd,
                           capture_output=True, check=True, timeout=10)
            rows = {}
            for name in artifacts:
                raw = (cwd / name).read_bytes()
                rows[name] = {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
                              "base64": base64.b64encode(raw).decode("ascii")}
            return {"ok": True, "delivery": "executed", "target": platform.node(),
                    "snapshot": snapshot, "attempt_id": f"fixture-{len(actions)}",
                    "admission": {"limits_verified": True}, "artifacts": rows, "ssh_request_bytes": 0}

        engine = AgentExileEngine(ssh_host="svhome")
        raw = b"hello"
        digest = hashlib.blake2s(raw, digest_size=16).hexdigest()
        manifest = [{"rel_path": "input.bin", "digest": digest, "size": len(raw)}]
        params = {"mask": 17}
        expected = bytes(value ^ 17 for value in raw)
        with patch.object(guarded_build, "submit_isolated", side_effect=local_submission):
            self.assertEqual(engine.query_remote_cas_missing([digest], remote_cas_dir=peer_cas)["missing"], [digest])
            self.assertEqual(engine.push_remote_cas_blocks({digest: raw}, remote_cas_dir=peer_cas)["blocks_pushed"], 1)
            self.assertEqual(engine.query_remote_cas_missing([digest], remote_cas_dir=peer_cas)["present"], [digest])
            result = engine.run_cas_step(job_id="j", step_key="s", generation=2, op="transform_bytes",
                                         params=params, block_manifest=manifest, remote_cas_dir=peer_cas,
                                         input_digest=guarded_cas.compute_step_input_digest("transform_bytes", params, manifest))
        self.assertEqual(actions, ["query", "push", "query", "execute"])
        self.assertEqual(base64.b64decode(result["output_bytes_b64"], validate=True), expected)
        self.assertEqual(result["receipt"]["output_digest"], hashlib.sha256(expected).hexdigest())
        self.assertEqual(result["receipt"]["generation"], 2)
        self.assertTrue(result["guard"]["limits_verified"])

        with patch.object(guarded_build, "submit_isolated", return_value={"ok": True}):
            with self.assertRaisesRegex(ValueError, "missing_guarded_cas_admission"):
                engine.query_remote_cas_missing([digest], remote_cas_dir=peer_cas)

        def incomplete_inventory(*args, **kwargs):
            reply = local_submission(*args, **kwargs)
            invalid = json.dumps({"missing": [], "present": []}).encode()
            reply["artifacts"]["response.json"] = {
                "bytes": len(invalid), "sha256": hashlib.sha256(invalid).hexdigest(),
                "base64": base64.b64encode(invalid).decode("ascii")}
            return reply

        with patch.object(guarded_build, "submit_isolated", side_effect=incomplete_inventory):
            with self.assertRaisesRegex(ValueError, "guarded_cas_inventory_mismatch"):
                engine.query_remote_cas_missing([digest], remote_cas_dir=peer_cas)

    def test_http_handoff_decodes_binary_inputs_before_journaling(self) -> None:
        from chimera_tp.platform.substrate import PlatformSubstrate

        coordinator = Mock()
        coordinator.handoff_job.return_value = {"ok": True}
        platform_api = SimpleNamespace(_cartridge_enabled={"immortal_jobs": True}, exile_handoff=coordinator)
        endpoint = urlparse("/v1/exile/handoff")
        data = bytes((0, 255, 1))
        encoded = base64.b64encode(data).decode("ascii")
        body = {"steps": [{"blocks": {"named": {"base64": encoded}}},
                          {"blocks": [{"b64": encoded}, {"b64": ""}, "ghi chép"]}]}
        status, _ = PlatformSubstrate.handle_post(platform_api, endpoint, json.dumps(body).encode(), {})
        self.assertEqual(status, 200)
        steps = coordinator.handoff_job.call_args.args[0]
        self.assertEqual(steps[0]["blocks"], {"named": data})
        self.assertEqual(steps[1]["blocks"], [data, b"", "ghi chép".encode()])
        for invalid in ({"wrong": encoded}, {"base64": "!"}, {"b64": encoded, "base64": ""}):
            with self.subTest(block=invalid):
                status, _ = PlatformSubstrate.handle_post(
                    platform_api, endpoint, json.dumps({"blocks": [invalid]}).encode(), {})
                self.assertEqual(status, 400)
        coordinator.handoff_job.assert_called_once()

        for stored, http_status in ((True, 202), (False, 502)):
            with self.subTest(stored=stored):
                coordinator.handoff_job.return_value = {
                    "ok": False, "state": "deferred", "queue": {"stored": stored, "id": "test-ticket"}}
                status, _ = PlatformSubstrate.handle_post(platform_api, endpoint, json.dumps(body).encode(), {})
                self.assertEqual(status, http_status)

    def test_sdk_preserves_resumable_http_failure(self) -> None:
        from chimera_tp.platform.client import ChimeraClient

        client = SimpleNamespace(app="test", available=True, _post_json=Mock())
        receipt = {"ok": False, "job_id": "job-1", "steps": [{"state": "deferred"}],
                   "queue": {"id": "fixture-ticket"}}
        for reply in (receipt, {"error": "daemon_failure"}):
            client._post_json.side_effect = HTTPError(
                "http://127.0.0.1/v1/exile/handoff", 502, "Bad Gateway", {}, io.BytesIO(json.dumps(reply).encode()))
            if reply is receipt:
                self.assertEqual(ChimeraClient.exile_handoff(client, job_id="job-1"), receipt)
            else:
                with self.assertRaises(HTTPError):
                    ChimeraClient.exile_handoff(client, job_id="job-1")

    def test_05_100_trial_fault_injection_suite(self) -> None:
        out_json = self.ops_dir / "exile_handoff_100_trials.json"
        report = run_fault_injection_benchmark(
            ops_dir=self.ops_dir / "bench_ops",
            output_path=out_json,
            trials_per_fault=25,
        )
        self.assertTrue(report["ok"], msg=json.dumps(report, indent=2))
        self.assertEqual(report["total_trials"], 100)
        self.assertEqual(report["fault_counts"]["pre_receive"], 25)
        self.assertEqual(report["fault_counts"]["post_receive_pre_compute"], 25)
        self.assertEqual(report["fault_counts"]["post_compute_pre_ack"], 25)
        self.assertEqual(report["fault_counts"]["post_commit_pre_client_reply"], 25)
        self.assertEqual(report["oracle_digest_matches"], 100)
        self.assertEqual(report["lost_accepted_jobs"], 0)
        self.assertEqual(report["single_committed_receipt_per_step"], 100)
        self.assertEqual(report["delayed_stale_receipts_delivered"], 25)
        self.assertEqual(report["delayed_stale_receipts_rejected"], 25)
        self.assertEqual(report["post_commit_idempotent_no_reexec"], 25)
        self.assertEqual(report["win_cpu_yield_honored_count"], 100)
        self.assertGreater(report["retransmitted_bytes"]["by_fault"]["pre_receive"], 0)
        self.assertEqual(report["retransmitted_bytes"]["by_fault"]["post_receive_pre_compute"], 0)
        self.assertEqual(report["retransmitted_bytes"]["by_fault"]["post_compute_pre_ack"], 0)
        self.assertEqual(report["retransmitted_bytes"]["by_fault"]["post_commit_pre_client_reply"], 0)
        self.assertTrue(out_json.is_file())


if __name__ == "__main__":
    unittest.main()
