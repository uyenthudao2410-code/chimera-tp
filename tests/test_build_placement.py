from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.parse import urlparse

from chimera_tp.platform import build_placement as placement
from chimera_tp.platform import build_queue, build_snapshot, guarded_build, work_admission


def trials(peer_ms, local_ms=100):
    result = []
    for index in range(5):
        order = ["local", "svhome"] if index % 2 == 0 else ["svhome", "local"]
        for site in order:
            result.append({"pair": index + 1, "site": site, "state": "completed", "delivery": "executed",
                           "wall_ms": peer_ms[index] if site == "svhome" else local_ms,
                           "artifacts": {"work.bin": ["a" * 64, 128]}, "attempt_id": f"{index}-{site}"})
    return result


class PlacementTests(unittest.TestCase):
    def test_linux_job_admission_precedes_all_daemon_execution(self):
        from chimera_tp.platform import substrate

        server = Mock()
        with patch.object(substrate.sys, "platform", "linux"):
            cases = [
                ("exec", {}), ("atomic-patch", {}), ("commit-verify", {}), ("mirror-race", {}),
                ("precog", {"action": "watch_start"}),
                ("run-dag", {"steps": [{"kind": "xray"}, {"kind": "verify"}]}),
            ]
            for action, body in cases:
                with self.subTest(action=action):
                    result = substrate.PlatformSubstrate.handle_post(
                        server, urlparse("/v1/agent/" + action), json.dumps(body).encode(), {}
                    )
                    self.assertEqual(result, (409, {"ok": False, "state": "deferred",
                        "error": "guarded_build_required", "submit_via": "chimera-tp swarm",
                        "queue": {"stored": False}}))
            self.assertEqual(server.mock_calls, [])
            dag = server.agent_bus.symbiont.macro_dag.run_dag
            dag.return_value = {"ok": True}
            status, response = substrate.PlatformSubstrate.handle_post(
                server, urlparse("/v1/agent/run-dag"), b'{"steps":[{"kind":"sha256_parity"}]}', {}
            )
            self.assertEqual((status, response), (200, {"ok": True}))
            dag.assert_called_once()

    def test_peer_mirror_declines_before_transport_or_local_fallback(self):
        from chimera_tp.platform import agent_symbiont, client, peer_guard, substrate

        server = Mock()
        expected = peer_guard.guarded_build_required()
        with patch.object(substrate.sys, "platform", "win32"):
            self.assertEqual(substrate.PlatformSubstrate.handle_post(
                server, urlparse("/v1/agent/mirror-race"), b'{"offload_peer":true}', {}
            ), (409, expected))
        self.assertEqual(client.ChimeraClient.mirror_race(server, ".", [], offload_peer=True), expected)
        self.assertEqual(agent_symbiont.MirrorRaceEngine.race(server, ".", [], offload_peer=True), expected)
        self.assertEqual(server.mock_calls, [])

    def test_linux_release_writes_require_maintenance(self):
        from chimera_tp.platform import substrate

        server = Mock()
        route = urlparse("/v1/agent/release-promote")
        with patch.object(substrate.sys, "platform", "linux"):
            for action in ("promote", "rollback"):
                status, reply = substrate.PlatformSubstrate.handle_post(
                    server, route, json.dumps({"action": action}).encode(), {}
                )
                self.assertEqual((status, reply["error"]), (409, "release_maintenance_required"))
            self.assertEqual(server.mock_calls, [])
            server.agent_bus.symbiont.release_promote.status.return_value = {"ok": True}
            self.assertEqual(substrate.PlatformSubstrate.handle_post(server, route, b"{}", {}), (200, {"ok": True}))

    def test_sdk_returns_daemon_denial_without_replaying_locally(self):
        import io
        from urllib.error import HTTPError
        from chimera_tp.platform import client, peer_guard

        sdk = object.__new__(client.ChimeraClient)
        sdk.app, sdk.anchor_url, sdk.token, sdk.timeout_s = "test", "http://127.0.0.1:1", None, 1
        sdk.available = True
        expected = peer_guard.guarded_build_required()
        denied = HTTPError(sdk.anchor_url, 409, "Conflict", {}, io.BytesIO(json.dumps(expected).encode()))
        with patch.object(client.urllib.request, "urlopen", side_effect=denied) as remote:
            self.assertEqual(sdk.mirror_race(".", []), expected)
            remote.assert_called_once()

    def test_new_pairs_bind_one_ssh_route(self):
        rows = trials([40] * 5)
        remote = [r for r in rows if r["site"] == "svhome"]
        for row in remote:
            row["ssh_route"] = "phantom_ssh"
        self.assertEqual(placement._choose(rows, 5)["ssh_route"], "phantom_ssh")
        for other in ("ssh_alias", None, "unknown"):
            with self.subTest(other=other):
                remote[-1]["ssh_route"] = other
                with self.assertRaisesRegex(ValueError, "inconsistent_placement_ssh_routes"):
                    placement._choose(rows, 5)

    def test_route_change_defers_before_transfer_and_preserves_pin_on_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            work, outbox = root / "work", root / "queue"
            work.mkdir()
            (work / "input.txt").write_bytes(b"fixture")
            with patch.object(work_admission, "peer_ssh_route",
                              return_value=(["must-not-start-ssh"], "ssh_alias")):
                result = guarded_build.submit("test", cwd=work, expected_ssh_route="phantom_ssh",
                                              environment_id="fixture", reuse=True, state_dir=outbox)
                self.assertEqual(result["error"], "placement_ssh_route_changed")
                self.assertEqual(result["available_ssh_route"], "ssh_alias")
                self.assertEqual(result["ssh_request_bytes"], 0)
                key = result["queue"]["id"]
                _, frozen, _ = build_queue.get(outbox, key)
                self.assertEqual(frozen["expected_ssh_route"], "phantom_ssh")
                retry = guarded_build.retry_queued(key, state_dir=outbox)
                self.assertEqual(retry["ssh_request_bytes"], 0)
                self.assertEqual(retry["queue"], {"stored": True, "id": key})

    def test_paired_count_order_and_wall_time_determine_choice(self):
        results = trials([200, 90, 85, 80, 400])
        self.assertEqual(placement._choose(results, 5)["selected"], "svhome")
        self.assertEqual(placement._choose(trials([100] * 5), 5)["selected"], "local")
        with self.assertRaisesRegex(ValueError, "incomplete"):
            placement._choose(results[:6], 5)
        results[2], results[3] = results[3], results[2]
        with self.assertRaisesRegex(ValueError, "order"):
            placement._choose(results, 5)

    def test_refuses_cached_timing_changed_outputs_and_partial_checks(self):
        for update,reason in [({"delivery": "cached"}, "observation"),
                              ({"artifacts": {"work.bin": ["c" * 64, 17]}}, "outputs_differ"),
                              ({"wall_ms": float("nan")}, "observation")]:
            with self.subTest(update=update):
                rows = trials([40] * 5)
                rows[3].update(update)
                with self.assertRaisesRegex(ValueError, reason):
                    placement._choose(rows, 5)
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            work = base / "repo"
            work.mkdir()
            (work / "source.py").write_text("x = 2")
            path = base / "profile.json"
            with patch.object(placement, "_submit", return_value={"ok": False, "state": "deferred",
                                                                  "error": "guest_slot_busy"}):
                report = placement.measure(path, work, "a", "b", "svhome", "test", ["work.bin"], 30)
            self.assertEqual(report["state"], "incomplete")
            with patch.object(placement, "_submit") as execute:
                self.assertEqual(placement.use(path, "test", execute=True)["error"], "no_complete_placement_measurement")
                execute.assert_not_called()

    def test_pinned_snapshot_is_checked_on_actual_execution_for_both_sites(self):
        with tempfile.TemporaryDirectory() as folder:
            work = Path(folder)
            src = work / "file.py"
            src.write_text("x = 2")
            digest = build_snapshot.capture(work, include_data=False)["digest"]
            src.write_text("x = 3")
            with (patch.object(guarded_build, "_dispatch") as remote,
                  patch("chimera_tp.platform.local_build.run_snapshot") as local,
                  patch("chimera_tp.platform.guarded_build.sys.platform", "win32")):
                for target in ("local", "svhome"):
                    reply = guarded_build.submit("test", cwd=work, target=target, expected_snapshot=digest)
                    self.assertEqual(reply["error"], "placement_inputs_changed")
                local.assert_not_called()
                remote.assert_not_called()

    def test_changed_summary_environment_age_or_source_never_starts_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            work = root / "source"
            work.mkdir()
            source = work / "file.py"
            source.write_bytes(b"val=4")
            path = root / "profile.json"
            rows = trials([50] * 5)
            profile = {"schema": placement.SCHEMA, "state": "measured", "snapshot": build_snapshot.capture(work)["digest"],
                       "profile_id": "fake-unit-test", "completed_at": 1_800_000_000, "pairs_requested": 5, "trials": rows,
                       "spec": placement._combination(work, "a", "b", "svhome", "env", ["work.bin"], 10),
                       "runtime_sha256": placement._runtime(), "comparison": placement._choose(rows, 5)}
            path.write_text(json.dumps(profile))
            with (patch.object(placement, "_submit") as execute,
                  patch.object(placement.time, "time", return_value=1_800_000_001)):
                self.assertEqual(placement.use(path, "env")["state"], "planned")
                self.assertEqual(placement.use(path, "env", execute=True)["error"], "placement_ssh_route_unmeasured")
                self.assertEqual(placement.use(path, "env", max_age_s=.1, execute=True)["state"], "deferred")
                self.assertEqual(placement.use(path, "other", execute=True)["state"], "deferred")
                profile["comparison"]["selected"] = "local"
                path.write_text(json.dumps(profile))
                with self.assertRaisesRegex(ValueError, "summary_differs"):
                    placement.use(path, "env", execute=True)
                profile["comparison"] = placement._choose(rows, 5)
                path.write_text(json.dumps(profile))
                source.write_bytes(b"val=5")
                self.assertEqual(placement.use(path, "env", execute=True)["error"], "placement_inputs_changed")
                execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
