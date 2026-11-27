from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from chimera_tp.platform import build_queue, build_snapshot, exile_colab, guarded_build
from chimera_tp.platform.client import ChimeraClient
from chimera_tp.platform.colab_cli_bridge import ColabCliBridge, _UNIVERSAL_COLAB_RUNNER


class SnapshotTests(unittest.TestCase):
    def test_worktree_changes_modes_and_exact_verification(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "src"
            root.mkdir()
            subprocess.run(["git", "init", "-q", "--template=", str(root)], check=True)
            module = root / "lib"
            module.mkdir()
            (root / ".gitignore").write_text("ignored.bin\n", encoding="utf-8")
            tracked = module / "code.py"
            tracked.write_text("before", encoding="utf-8")
            deleted = root / "removed.py"
            deleted.write_text("removed", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "."], check=True, capture_output=True)
            tracked.write_text("after", encoding="utf-8")
            deleted.unlink()
            (root / "ignored.bin").write_bytes(b"secret")
            (root / "new.py").write_text("new", encoding="utf-8")
            snapshot = build_snapshot.capture(module)
            copy = Path(temp) / "rebuilt"
            copy.mkdir()
            cwd = build_snapshot.materialize(snapshot["wire"], snapshot["digest"], copy)
            self.assertEqual(cwd, copy / "lib")
            self.assertEqual((cwd / "code.py").read_text(), "after")
            self.assertTrue((copy / "new.py").is_file())
            self.assertFalse((copy / "ignored.bin").exists())
            self.assertFalse((copy / deleted.name).exists())
            verify_only = build_snapshot.capture(module, include_data=False)
            self.assertEqual(verify_only["digest"], snapshot["digest"])
            (copy / "new.py").write_text("bad", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "digest_mismatch"):
                build_snapshot.materialize(verify_only["wire"], snapshot["digest"], Path(temp) / "other", copy)
            with self.assertRaisesRegex(ValueError, "byte_limit"):
                build_snapshot.capture(root, limit=2)

    def test_manifest_tampering_and_path_errors(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "source").write_bytes(b"contents")
            snap = build_snapshot.capture(root)
            with self.assertRaisesRegex(ValueError, "manifest_mismatch"):
                build_snapshot.materialize(snap["wire"], "0" * 64, root)
            for name in ("../file", "C:/escape", "/root/file", "valid//file", "a/.git/config", ".ssh/id_rsa"):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    build_snapshot.portable_path(name)


class QueueTests(unittest.TestCase):
    def test_defer_retry_uses_original_snapshot_and_removes_completed_ticket(self):
        with tempfile.TemporaryDirectory() as temp:
            store = Path(temp) / "outbox"
            src = Path(temp) / "src"
            src.mkdir()
            source = src / "value.txt"
            source.write_text("original", encoding="utf-8")
            defer = {"ok": False, "state": "deferred", "error": "service_latency", "protocol": 1}
            with patch.object(guarded_build, "_dispatch", return_value=defer):
                response = guarded_build.submit("cat value.txt", cwd=src, reuse=True, environment_id="v",
                                                state_dir=store)
            self.assertEqual(response["state"], "deferred")
            self.assertTrue(response["queue"]["stored"])
            key = response["queue"]["id"]
            source.write_text("unrelated later edit", encoding="utf-8")

            def accepted(peer, package, req, wire):
                self.assertEqual(peer, "svhome")
                destination = Path(temp) / "verified"
                destination.mkdir()
                cwd = build_snapshot.materialize(wire, req["snapshot"], destination)
                self.assertEqual((cwd / "value.txt").read_text(), "original")
                return {"ok": True, "state": "completed", "attempt_id": "one"}

            self.assertEqual(build_queue.list_pending(store)[0]["id"], key)
            with (patch.object(guarded_build, "_dispatch", side_effect=accepted),
                  patch.object(guarded_build, "_package", return_value=b"compatible updated worker")):
                self.assertEqual(guarded_build.retry_queued(key, state_dir=store)["attempt_id"], "one")
            self.assertEqual(build_queue.list_pending(store), [])

    def test_artifact_receipt_rejects_changed_bytes(self):
        req = {"snapshot": "source", "artifacts": ["result.txt"]}
        item = {"bytes": 4, "sha256": hashlib.sha256(b"good").hexdigest(), "base64": "YmFhZA=="}
        result = {"ok": True, "protocol": 1, "state": "completed", "snapshot": "source",
                  "attempt_id": "one", "artifacts": {"result.txt": item}}
        with self.assertRaisesRegex(ValueError, "artifact_integrity_failure"):
            guarded_build._verify(result, req)


class ColabTests(unittest.TestCase):
    def test_budget_and_operation_are_checked_before_billing(self):
        self.assertEqual(exile_colab.run(object(), "echo abc")["error"], "unsupported_colab_task")
        self.assertEqual(exile_colab.run(object(), "probe")["state"], "deferred")
        self.assertEqual(exile_colab.run(None, "probe")["error"], "colab_bridge_unavailable")

    def test_legacy_local_anchor_validates_budget_before_opening_any_session(self):
        client = object.__new__(ChimeraClient)
        client.available = True
        client.anchor_url = "http://127.0.0.1:9780"
        spec = json.dumps({"task": "python_compile", "payload": {"files": {"fixture.py": "x = 4"}}})
        cartridges = {k: {"status": "active"} for k in ("hyper_desk", "vgpu_pareto")}
        with (tempfile.TemporaryDirectory() as folder,
              patch.object(client, "_get_json", return_value={"ok": True}),
              patch.object(client, "capabilities", return_value={"cartridges": cartridges}),
              patch("chimera_tp.platform.discovery.chimera_home_dir", return_value=Path(folder)),
              patch.object(ColabCliBridge, "status") as status,
              patch.object(ColabCliBridge, "exec_task") as execute):
            result = client.agent_exile(spec, target="colab")
            self.assertEqual(result["via"], "local_client_colab")
            self.assertEqual(result["state"], "deferred")
            client.anchor_url = "http://example.invalid"
            self.assertEqual(client.agent_exile(spec, target="colab")["error"], "verified_exile_protocol_unavailable")
            status.assert_not_called()
            execute.assert_not_called()

    def test_cuda_request_rejects_cpu_receipt_and_lost_provision_attempts_stop(self):
        bridge = Mock()
        bridge.status.return_value = {"usage": {"available": True, "balance_cu": 10}}
        bridge.exec_task.return_value = {
            "ok": True, "auto_stopped_cu_guard": True,
            "result": {"ok": True, "task_kind": "cuda_matmul", "device": "cpu"},
        }
        spec = json.dumps({"task": "cuda_matmul", "max_estimated_cu": 0.4, "payload": {"n": 64}})
        self.assertEqual(exile_colab.run(bridge, spec)["state"], "failed")
        bridge.exec_task.return_value["auto_stopped_cu_guard"] = False
        self.assertEqual(exile_colab.run(bridge, spec)["state"], "indeterminate")
        with tempfile.TemporaryDirectory() as folder:
            local = ColabCliBridge(Path(folder))
            with (patch.object(local, "find_colab_bin", return_value="test-cli"),
                  patch.object(local, "ensure_session", side_effect=TimeoutError("lost")) as ensure,
                  patch.object(local, "stop_session", return_value={"ok": True}) as stop):
                with self.assertRaises(TimeoutError):
                    local.exec_task("cuda_matmul", {"n": 64}, profile="T4", require_gpu=True,
                                    session_name="test-one-shot", keep_session=False)
                self.assertEqual(ensure.call_args.kwargs["fallback_chain"], ["T4"])
                stop.assert_called_once_with("test-one-shot")

    def test_real_runner_compiles_declared_sources_and_adapter_checks_result(self):
        tree = ast.parse(_UNIVERSAL_COLAB_RUNNER)
        func = next(x for x in tree.body if isinstance(x, ast.FunctionDef) and x.name == "run_task")
        namespace = {"hashlib": hashlib, "time": time}
        exec(compile(ast.Module(body=[func], type_ignores=[]), "<runner>", "exec"), namespace)

        class Bridge:
            def status(self, *, refresh):
                return {"usage": {"available": refresh, "balance_cu": 1.0}}

            def exec_task(self, task_kind, payload, **options):
                value = namespace["run_task"]({"task_kind": task_kind, **payload}, {})
                return {"ok": value["ok"], "result": value, "auto_stopped_cu_guard": not options["keep_session"]}

        def compile_source(source):
            return exile_colab.run(Bridge(), json.dumps({"task": "python_compile", "max_estimated_cu": 0.1,
                                                        "payload": {"files": {"module.py": source}}}))
        self.assertTrue(compile_source("answer = 42")["ok"])
        self.assertFalse(compile_source("answer =")["ok"])
