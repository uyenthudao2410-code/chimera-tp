"""Recover a selected AutoCAD .sv$ file into a new verifiable, portable workspace."""

import argparse
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import zipfile

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from chimera_tp.platform import workspace_capsule
from chimera_tp.platform.file_revisions import FileRevisions


class SourceBusy(Exception):
    pass


def signature(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


@contextmanager
def held_reader(source):
    """Allow simultaneous readers but require Windows to exclude writers and renames."""
    if sys.platform != "win32":
        raise ValueError("Windows sharing guarantees and AutoCAD Core Console are required")
    import msvcrt

    path = source.absolute()
    if path.resolve(strict=True) != path or not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError("source_must_be_a_regular_unlinked_file")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                   wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    # GENERIC_READ, FILE_SHARE_READ, OPEN_EXISTING, FILE_FLAG_SEQUENTIAL_SCAN.
    handle = kernel.CreateFileW(str(path), 0x80000000, 1, None, 3, 0x08000000, None)
    if handle == ctypes.c_void_p(-1).value:
        code = ctypes.get_last_error()
        if code in (32, 33):
            raise SourceBusy("autosave_in_use") from None
        raise ctypes.WinError(code)
    try:
        fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
    except BaseException:
        kernel.CloseHandle(handle)
        raise
    with os.fdopen(fd, "rb") as stream:
        if signature(os.fstat(stream.fileno())) != signature(path.lstat()):
            raise SourceBusy("autosave_replaced")
        yield stream


def stage_source(source, destination, settle_ms):
    if not 0 <= settle_ms <= 10_000:
        raise ValueError("settle_ms_must_be_between_0_and_10000")
    if source.suffix.casefold() != ".sv$":
        raise ValueError("select_an_sv_dollar_autosave")
    original = signature(source.lstat())
    time.sleep(settle_ms / 1000)
    with held_reader(source) as stream:
        if signature(os.fstat(stream.fileno())) != original:
            raise SourceBusy("autosave_changed_while_settling")
        if not re.fullmatch(rb"AC10[0-9]{2}", stream.read(6)):
            raise ValueError("invalid_autosave_dwg_signature")
        stream.seek(0)
        checksum = hashlib.sha256()
        with destination.open("xb") as copy:
            while chunk := stream.read(1024 * 1024):
                copy.write(chunk)
                checksum.update(chunk)
            copy.flush()
            os.fsync(copy.fileno())
        if signature(os.fstat(stream.fileno())) != original or signature(source.lstat()) != original:
            raise SourceBusy("autosave_changed_while_reading")
    return checksum.hexdigest(), original[2]


def native_command(script, args, console=None):
    argv = ["node", str(REPO / "scripts" / script), *map(str, args)]
    if console is not None:
        argv.extend(["--console", str(console)])
    proc = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, timeout=900,
                          creationflags=subprocess.CREATE_NO_WINDOW)
    if proc.returncode:
        message = proc.stderr.decode("utf-8", errors="replace").strip()[-2500:]
        raise ValueError(f"native_drawing_check_failed: {message}")
    return json.loads(proc.stdout)


def native_facts(drawing, console):
    return native_command("autocad_autosave_facts.mjs", ["--file", drawing], console)


def load_graph(bundle):
    with zipfile.ZipFile(bundle) as archive:
        with archive.open("graph.json") as stream:
            data = stream.read(workspace_capsule.GRAPH_BYTES + 1)
    if len(data) > workspace_capsule.GRAPH_BYTES:
        raise ValueError("oversize_workspace_graph")
    return json.loads(data)


def dependency_graph(args, revisions, scratch, autosave, digest, size):
    if args.base is None:
        facts = native_facts(autosave, args.console)
        if facts["xrefs"]:
            missing = [ref["saved_path"] for ref in facts["xrefs"]]
            raise ValueError("pinned_xref_capsule_required: " + json.dumps(missing, ensure_ascii=True))
        graph = {"schema": workspace_capsule.SCHEMA, "entry": "Recovered.dwg",
                 "files": [{"path": "Recovered.dwg", "bytes": size, "sha256": digest, "links": []}]}
        folder = scratch / "isolated-drawing"
        folder.mkdir()
        os.link(autosave, folder / graph["entry"])
        return folder, graph, facts

    folder = scratch / "pinned-drawings"
    # Restore the immutable capsule from one private copy. The caller's archive
    # could be replaced between verifying it and parsing its relative paths.
    base = scratch / "baseline.zip"
    with args.base.open("rb") as src, base.open("xb") as dst:
        shutil.copyfileobj(src, dst)
    workspace_capsule.restore(revisions, base, args.base_id, folder)
    baseline = load_graph(base)
    entry = folder / baseline["entry"]
    if entry.suffix.casefold() != ".dwg":
        raise ValueError("selected_capsule_entry_is_not_a_dwg")
    old = native_facts(entry, args.console)
    # Only the scratch copy of the old host is replaced. All its XREFs remain
    # exactly the files selected by the caller's SHA-256 capsule identity.
    os.replace(autosave, entry)
    facts = native_facts(entry, args.console)
    if facts["fingerprint_guid"] != old["fingerprint_guid"]:
        raise ValueError("drawing_creation_guid_does_not_match_baseline")
    graph_output = scratch / "native-graph.json"
    native_command("cad_workspace_capsule.mjs", ["--root", folder, "--entry", baseline["entry"],
                   "--out", graph_output], args.console)
    graph = json.loads(graph_output.read_text(encoding="utf-8"))
    known = {m["path"]: (m["sha256"], m["bytes"]) for m in baseline["files"]}
    for m in graph["files"]:
        expected = (digest, size) if m["path"] == graph["entry"] else known.get(m["path"])
        if expected != (m["sha256"], m["bytes"]):
            raise ValueError(f"dependency_outside_selected_revision:{m['path']}")
    return folder, graph, facts


def recover(args):
    if bool(args.base) != bool(args.base_id):
        raise ValueError("provide_base_and_base_id_together")
    if args.base_id and not re.fullmatch("[a-f0-9]{64}", args.base_id):
        raise ValueError("invalid_base_capsule_identity")
    output = args.output.absolute()
    if os.path.lexists(output):
        raise FileExistsError(output)
    with tempfile.TemporaryDirectory(prefix=".chimera-autosave-", dir=output.parent) as tmp:
        scratch = Path(tmp)
        staged = scratch / "Candidate.dwg"
        digest, size = stage_source(args.source, staged, args.settle_ms)
        revisions = FileRevisions(scratch / "checked-revisions.sqlite")
        folder, graph, facts = dependency_graph(args, revisions, scratch, staged, digest, size)
        graph_file = scratch / "recovery-graph.json"
        graph_file.write_text(json.dumps(graph, ensure_ascii=False), encoding="utf-8")
        result = scratch / "ready"
        result.mkdir()
        archive = result / "recovery.zip"
        capsule = workspace_capsule.capture(revisions, folder, graph_file, archive)
        identity = capsule["capsule"]
        restored = result / "workspace"
        workspace_capsule.restore(FileRevisions(scratch / "fresh.sqlite"), archive, identity, restored)
        verification = workspace_capsule.verify(archive, identity, restored)
        if not verification["ok"]:
            raise ValueError("restored_workspace_failed_verification")
        provenance = "caller_selected_snapshot" if args.base else "entry_has_no_dwg_xrefs"
        receipt = {"schema": "chimera.cad.autosave-recovery/1", "autosave_sha256": digest,
                   "autosave_bytes": size, "entry": graph["entry"], "capsule_id": identity,
                   "base_capsule_id": args.base_id, "dependency_provenance": provenance,
                   "dependency_count": len(graph["files"]) - 1, "verified_files": verification["checked"],
                   "native": facts, "content_source": "selected_off_disk_sv$"}
        (result / "receipt.json").write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n",
                                             encoding="utf-8")
        # On Windows, rename publishes this entire directory or fails if the
        # destination already exists. Never remove or replace a caller's output.
        os.rename(result, output)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path, help="Selected .sv$ autosave")
    parser.add_argument("--output", required=True, type=Path, help="New recovery directory")
    parser.add_argument("--base", type=Path, help="Verified workspace capsule containing the source DWG and XREFs")
    parser.add_argument("--base-id", help="SHA-256 capsule identity printed at capture")
    parser.add_argument("--console", type=Path, help="Override AutoCAD Core Console executable")
    parser.add_argument("--settle-ms", type=int, default=500)
    try:
        receipt = recover(parser.parse_args())
    except SourceBusy as error:
        print(json.dumps({"ok": False, "state": "deferred", "reason": str(error)}))
        return 75
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile, subprocess.SubprocessError) as error:
        print(json.dumps({"ok": False, "state": "failed", "reason": str(error)}))
        return 1
    print(json.dumps({"ok": True, **receipt}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
