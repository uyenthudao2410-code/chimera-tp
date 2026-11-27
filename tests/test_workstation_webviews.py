"""Exercise runtime ownership and accounting without interrogating desktop applications."""
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

if importlib.util.find_spec("psutil") is None:
    raise unittest.SkipTest("The workstation process sampler requires psutil")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from workstation_webviews import IMAGE, WebViewObservation, summarize


def proc(name, parent, born, private):
    return {"name": name, "ppid": parent, "created": born, "private": private}


class WebViewObservationTests(unittest.TestCase):
    def test_runtime_rows_are_disjoint_and_host_memory_is_excluded(self):
        processes = {
            1: proc("ms-teams.exe", 0, 1, 9000),
            2: proc(IMAGE, 1, 2, 100), 3: proc(IMAGE, 2, 3, 200),
            4: proc("olk.exe", 0, 1, 5000), 5: proc(IMAGE, 4, 2, 350),
            6: proc(IMAGE, 99, 3, 19), 7: proc(IMAGE, 1, 2, 11),
            8: proc(IMAGE, 1, 2, 21), 9: proc(IMAGE, 2, 4, 41),
        }
        labels = {2: ("ms-teams.exe", b"same"), 5: ("olk.exe", b"other"), 6: None,
                  7: ("mismatch.exe", None), 8: ("ms-teams.exe", b"same")}
        observer = WebViewObservation()
        with patch.object(observer, "_inspect_root", side_effect=lambda pid, _: labels[pid]):
            result = observer.collect(processes)
        teams = result["hosts"]["ms-teams.exe"]
        self.assertEqual((teams["processes"], teams["private_bytes"]), (4, 362))
        self.assertEqual((teams["roots"], teams["observed_profile_dirs"]), (2, 1))
        self.assertEqual(result["hosts"]["olk.exe"]["private_bytes"], 350)
        self.assertEqual((result["unattributed_processes"], result["unattributed_private_bytes"]), (2, 30))
        self.assertEqual(result["total_private_bytes"], 742)
        self.assertNotIn("same", json.dumps(result))

    def test_pid_reuse_or_failed_lookup_cannot_attach_an_old_child(self):
        observer = WebViewObservation()
        team = {1: proc("ms-teams.exe", 0, 1, 10000), 2: proc(IMAGE, 1, 2, 100)}
        orphan = {1: proc("ms-teams.exe", 0, 4, 10000), 2: proc(IMAGE, 1, 2, 100)}
        new = {1: proc("olk.exe", 0, 4, 20000), 2: proc(IMAGE, 1, 5, 200)}
        with patch.object(observer, "_inspect_root", side_effect=[("ms-teams.exe", b"a"), None, ("olk.exe", b"b")]):
            original = observer.collect(team)
            detached = observer.collect(orphan)
            denied = observer.collect(new)
            attached = observer.collect(new)
        self.assertEqual(detached["unattributed_private_bytes"], 100)
        self.assertEqual(denied["unattributed_private_bytes"], 200)
        self.assertEqual(attached["hosts"]["olk.exe"]["private_bytes"], 200)
        totals = summarize([{"webview2": v} for v in (original, detached, denied, attached)])
        self.assertEqual(sorted(g["samples_present"] for g in totals["hosts"]), [1, 1])

    def test_verified_root_profile_is_private_and_renderer_is_never_a_root(self):
        observer = WebViewObservation()
        with patch("workstation_webviews.psutil.Process") as process:
            runtime = process.return_value
            runtime.name.return_value = IMAGE
            runtime.create_time.return_value = 10
            runtime.cmdline.return_value = [IMAGE, "--user-data-dir=C:/Private/Person",
                                            "--webview-exe-name=MS-Teams.exe"]
            name, folder = observer._inspect_root(123, {"created": 10})
            self.assertEqual(name, "ms-teams.exe")
            self.assertEqual(len(folder), 16)
            self.assertNotIn(b"Person", folder)
            runtime.cmdline.return_value.append("--type=renderer")
            self.assertIsNone(observer._inspect_root(123, {"created": 10}))
            self.assertIsNone(observer._inspect_root(123, {"created": 20}))


if __name__ == "__main__":
    unittest.main()
