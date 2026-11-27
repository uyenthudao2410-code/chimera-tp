"""Cold-restore a saved capsule on a guarded Linux peer and return a freshly captured one."""

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import sys
import tempfile
import zipfile


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def measure_receiver(identity):
    from chimera_tp.platform.file_revisions import FileRevisions
    from chimera_tp.platform.workspace_capsule import capture, restore, verify

    if platform.system() != "Linux":
        raise RuntimeError("expected_linux_receiver")
    archive = Path("source.zip")
    if not verify(archive, identity)["ok"]:
        raise ValueError("invalid_incoming_capsule")
    with tempfile.TemporaryDirectory(prefix="cad-return-", dir=".") as name:
        scratch = Path(name)
        tree = scratch / "drawing"
        restore(FileRevisions(scratch / "received.sqlite"), archive, identity, tree)
        if not verify(archive, identity, tree)["ok"]:
            raise ValueError("receiver_restored_content_mismatch")
        with zipfile.ZipFile(archive) as obj:
            manifest = obj.read("graph.json")
        graph = scratch / "graph.json"
        graph.write_bytes(manifest)
        members = [{"path": path.relative_to(tree).as_posix(), "sha256": digest(path),
                    "bytes": path.stat().st_size} for path in sorted(tree.rglob("*")) if path.is_file()]
        result = capture(FileRevisions(scratch / "recaptured.sqlite"), tree, graph, Path("returned.zip"))
        if result["capsule"] != identity or not verify(Path("returned.zip"), identity, tree)["ok"]:
            raise ValueError("recaptured_identity_mismatch")
    facts = {"system": platform.system(), "hostname": platform.node(), "python": platform.python_version(),
             "capsule": identity, "members_read_from_linux_filesystem": members,
             "input_archive_sha256": digest(archive), "returned_archive_sha256": digest(Path("returned.zip")),
             "temporary_tree_removed": not scratch.exists()}
    with Path("receiver.json").open("x", encoding="utf-8") as output:
        json.dump(facts, output, allow_nan=False)


def checked_artifact(receipt, name):
    row = receipt["artifacts"][name]
    data = base64.b64decode(row["base64"], validate=True)
    if len(data) != row["bytes"] or hashlib.sha256(data).hexdigest() != row["sha256"]:
        raise ValueError(f"returned_transfer_mismatch:{name}")
    return data


def roundtrip(archive, identity, output, peer):
    from chimera_tp.platform.guarded_build import submit
    from chimera_tp.platform.workspace_capsule import verify

    source = Path(__file__).resolve()
    root = source.parents[1]
    if not verify(archive, identity)["ok"] or os.path.lexists(output):
        raise ValueError("invalid_input_or_existing_output")
    with tempfile.TemporaryDirectory(prefix="cad-peer-input-") as name:
        staged = Path(name)
        shutil.copyfile(archive, staged / "source.zip")
        shutil.copyfile(source, staged / "probe.py")
        for path in (root / "chimera_tp").rglob("*.py"):
            dest = staged / path.relative_to(root)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, dest)
        entry = ("import runpy,sys; sys.path.insert(0,'.'); "
                 "runpy.run_path('probe.py',run_name='__main__')")
        command = shlex.join(["python3", "-I", "-B", "-S", "-c", entry, "--receiver", identity])
        receipt = submit(command, cwd=staged, peer=peer, sync=True, reuse=False, timeout_s=80,
                         admission_policy={"job_disk_mib": 48, "job_memory_mib": 256},
                         artifacts=["returned.zip", "receiver.json"])
    if not receipt.get("ok"):
        details = {k: receipt.get(k) for k in ("state", "error", "stderr", "queue")}
        raise RuntimeError(json.dumps(details))
    if receipt["delivery"] != "executed" or not receipt["admission"]["limits_verified"]:
        raise ValueError("unverified_receiver_execution")
    facts = json.loads(checked_artifact(receipt, "receiver.json"))
    if (facts["system"] != "Linux" or facts["capsule"] != identity
            or facts["input_archive_sha256"] != digest(archive) or not facts["temporary_tree_removed"]):
        raise ValueError("unexpected_receiver_evidence")
    with tempfile.TemporaryDirectory(prefix="cad-return-", dir=output.parent) as name:
        archive_copy = Path(name) / "returned.zip"
        archive_copy.write_bytes(checked_artifact(receipt, "returned.zip"))
        if facts["returned_archive_sha256"] != digest(archive_copy) or not verify(archive_copy, identity)["ok"]:
            raise ValueError("returned_capsule_mismatch")
        os.link(archive_copy, output)
    return {**facts, "peer": peer, "attempt_id": receipt["attempt_id"], "snapshot": receipt["snapshot"],
            "delivery": receipt["delivery"], "guard_limits_verified": receipt["admission"]["limits_verified"],
            "elapsed_end_to_end_ms": receipt["elapsed_end_to_end_ms"]}


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--receiver":
        measure_receiver(sys.argv[2])
        return
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("identity")
    parser.add_argument("output", type=Path)
    parser.add_argument("--peer", default="svhome")
    args = parser.parse_args()
    if not re.fullmatch("[0-9a-f]{64}", args.identity):
        parser.error("expected the SHA-256 identity of the capsule graph")
    print(json.dumps(roundtrip(args.archive, args.identity, args.output, args.peer)))


if __name__ == "__main__":
    main()
