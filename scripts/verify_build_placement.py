"""Measure a portable package on Windows and an admitted Linux peer, then exercise the selected path."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
FILES = ("build_snapshot.py", "build_registry.py", "peer_guard.py", "result_reuse.py")
PRODUCT = "sources.zip"
BUILD = """from pathlib import Path
from zipfile import ZipFile, ZipInfo

with ZipFile("sources.zip", "w") as jar:
    for source in sorted(Path("input").glob("*.py")):
        data = source.read_bytes()
        compile(data, source.name, "exec")
        item = ZipInfo("src/" + source.name, date_time=(2000, 1, 1, 0, 0, 0))
        item.create_system = 3
        item.external_attr = 0o644 << 16
        jar.writestr(item, data)
"""


def run_cli(*args, codes=(0,)):
    result = subprocess.run([sys.executable, "-B", "-m", "chimera_tp", "swarm-placement", *map(str, args)],
                            cwd=ROOT, capture_output=True, timeout=240)
    if result.returncode not in codes:
        reason = (result.stderr or result.stdout).decode("utf-8", "replace")[:500]
        raise RuntimeError(f"placement command returned {result.returncode}: {reason}")
    return json.loads(result.stdout)


def check():
    import base64
    import io
    import zipfile

    with tempfile.TemporaryDirectory(prefix="chimera-verified-placement-") as tmp:
        root = Path(tmp)
        work = root / "project"
        sources = work / "input"
        sources.mkdir(parents=True)
        originals = {n: (ROOT / "chimera_tp" / "platform" / n).read_bytes() for n in FILES}
        for n, content in originals.items():
            (sources / n).write_bytes(content)
        (work / "package.py").write_text(BUILD, encoding="utf-8", newline="\n")
        profile = root / "placement.json"
        identity = "stdlib-reproducible-zip-2000-v1"
        base = ["--profile", profile, "--env", identity]
        inputs = ["-I", "-B", "-S", "package.py"]
        windows = subprocess.list2cmdline([sys.executable, *inputs])
        linux = shlex.join(["python3", *inputs])
        measured = run_cli("measure", *base, "--cwd", work, "--windows-cmd", windows, "--linux-cmd", linux,
                           "--artifact", PRODUCT, "--pairs", "5", "--timeout", "25", codes=(0, 75))
        data = json.loads(profile.read_text(encoding="utf-8"))
        if not measured["ok"]:
            raise RuntimeError("paired measurement incomplete: " + str(data.get("reason")))
        assert [r["pair"] for r in data["trials"]] == [n for n in range(1, 6) for _ in range(2)]
        assert len({r["attempt_id"] for r in data["trials"]}) == 10
        ratios = []
        for i in range(0, 10, 2):
            group = {r["site"]: r["wall_ms"] for r in data["trials"][i:i + 2]}
            ratios.append(group["svhome"] / group["local"])
        mid = sorted(ratios)[2]
        want = "svhome" if mid < 1 else "local"
        plan = run_cli("plan", *base)
        assert plan["placement"]["selected"] == want
        ran = run_cli("run", *base)
        repeated = run_cli("run", *base)
        assert ran["ok"] and ran["attempt_id"] == repeated["attempt_id"]
        assert repeated["delivery"] == "cached" or repeated["source_delivery"] == "cached"
        obj = ran["artifacts"][PRODUCT]
        actual = base64.b64decode(obj["base64"], validate=True)
        assert len(actual) == obj["bytes"] and hashlib.sha256(actual).hexdigest() == obj["sha256"]
        with zipfile.ZipFile(io.BytesIO(actual)) as jar:
            assert set(jar.namelist()) == {"src/" + n for n in FILES}
            assert all(jar.read("src/" + n) == content for n, content in originals.items())
        altered_runtime = run_cli("run", "--profile", profile, "--env", "incompatible", codes=(75,))
        assert altered_runtime["error"] == "placement_profile_or_environment_changed"
        (sources / FILES[0]).write_bytes(originals[FILES[0]] + b"\n")
        stale = run_cli("run", *base, codes=(75,))
        assert stale["error"] == "placement_inputs_changed"
        report = {
            "schema": "chimera.verified-placement-trial/1", "verified_utc": datetime.now(timezone.utc).isoformat(),
            "scope": "Opt-in measurement of deadline for a fresh reproducible ZIP, not interactive CAD.",
            "module_sha256": {n: hashlib.sha256(blob).hexdigest() for n, blob in originals.items()},
            "artifact_bytes": len(actual), "artifact_sha256": obj["sha256"], "oracle": "ZIP entries equal original bytes",
            "snapshot": data["snapshot"], "runtime_sha256": data["runtime_sha256"], "trials": data["trials"],
            "comparison": data["comparison"], "selected_cli_receipt": {
                "target": ran["target"], "delivery": ran["delivery"], "attempt_id": ran["attempt_id"],
                "wall_ms": ran["elapsed_end_to_end_ms"],
            }, "repeat_delivery": repeated["source_delivery"], "edited_input": stale["error"],
            "different_dependencies": altered_runtime["error"],
        }
    report["fixture_removed"] = not root.exists()
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parsed = parser.parse_args()
    checked = check()
    parsed.out.write_text(json.dumps(checked, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: checked[k] for k in ("comparison", "artifact_bytes", "fixture_removed")}))
