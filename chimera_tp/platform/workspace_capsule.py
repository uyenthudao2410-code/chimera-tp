"""Capture and restore a selected, hash-pinned graph of workspace files."""

from __future__ import annotations

from contextlib import contextmanager
import ctypes
import errno
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import shutil
import stat
import sys
import tempfile
import unicodedata
import zipfile

from .build_snapshot import canonical, portable_path, sha
from .file_revisions import FileRevisions


SCHEMA = "chimera.workspace-graph/1"
GRAPH_BYTES = 4 * 1024 * 1024
MEMBER_LIMIT = 8192
HASH = re.compile(r"[a-f0-9]{64}")


def _name(value):
    name = portable_path(value)
    for p in name.split("/"):
        if (p.rstrip(" .") != p or len(p.encode("utf-8")) > 255 or PureWindowsPath(p).is_reserved()
                or any(ord(c) < 32 or c in '<>"|?*' for c in p)):
            raise ValueError(f"nonportable_workspace_member:{name}")
    return name


def _graph(data):
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        raise ValueError("invalid_workspace_graph_schema")
    entry = _name(data.get("entry"))
    files = data.get("files")
    if not isinstance(files, list) or not 1 <= len(files) <= MEMBER_LIMIT:
        raise ValueError("invalid_workspace_member_count")
    paths, aliases, sizes = {}, {}, {}
    for member in files:
        if not isinstance(member, dict):
            raise ValueError("invalid_workspace_member")
        name = _name(member.get("path"))
        size, digest, links = member.get("bytes"), member.get("sha256"), member.get("links")
        if (name in paths or type(size) is not int or size < 0 or not isinstance(digest, str)
                or not HASH.fullmatch(digest) or not isinstance(links, list) or len(links) > MEMBER_LIMIT):
            raise ValueError(f"invalid_workspace_member:{name}")
        if sizes.setdefault(digest, size) != size:
            raise ValueError(f"workspace_object_size_conflict:{name}")
        prefixes = name.split("/")
        for count in range(1, len(prefixes) + 1):
            prefix = "/".join(prefixes[:count])
            alias = unicodedata.normalize("NFC", prefix).casefold()
            if aliases.setdefault(alias, prefix) != prefix:
                raise ValueError(f"aliased_workspace_member:{prefix}")
            if count < len(prefixes) and prefix in paths:
                raise ValueError(f"file_ancestor:{prefix}")
        paths[name] = {"path": name, "sha256": digest, "bytes": size, "links": sorted({_name(i) for i in links})}
    for name in paths:
        if any(p.as_posix() in paths for p in Path(name).parents):
            raise ValueError(f"file_ancestor:{name}")
    visited, todo = set(), [entry]
    while todo:
        here = todo.pop()
        if here not in paths:
            raise ValueError(f"undeclared_workspace_dependency:{here}")
        if here not in visited:
            visited.add(here)
            todo.extend(paths[here]["links"])
    if len(visited) != len(paths):
        raise ValueError("workspace_graph_has_unreachable_members")
    return {"schema": SCHEMA, "entry": entry, "files": [paths[name] for name in sorted(paths)]}


def _read_json(stream):
    data = stream.read(GRAPH_BYTES + 1)
    if len(data) > GRAPH_BYTES:
        raise ValueError("workspace_graph_too_large")
    return json.loads(data)


def _probe(root, name):
    path = root
    for component in name.split("/"):
        path = path / component
        st = path.lstat()
        if stat.S_ISLNK(st.st_mode) or getattr(st, "st_file_attributes", 0) & 0x400:
            raise ValueError(f"linked_workspace_member:{name}")
    if not stat.S_ISREG(st.st_mode) or path.resolve(strict=True) != path:
        raise ValueError(f"nonregular_workspace_member:{name}")
    return path, (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)


def capture(revisions: FileRevisions, root: Path, graph_file: Path, output: Path):
    root = root.resolve(strict=True)
    with graph_file.open("rb") as stream:
        graph = _graph(_read_json(stream))
    output = output.absolute()
    if os.path.lexists(output):
        raise FileExistsError(output)
    identity = sha(canonical(graph))
    initial = {m["path"]: _probe(root, m["path"]) for m in graph["files"]}
    saved_objects = set()
    with tempfile.TemporaryDirectory(prefix=".workspace-capture-", dir=output.parent) as directory:
        temporary = Path(directory)
        staged = temporary / "workspace.zip"
        with zipfile.ZipFile(staged, "x", allowZip64=True) as archive:
            archive.writestr("graph.json", canonical(graph))
            for member in graph["files"]:
                name, digest = member["path"], member["sha256"]
                captured = revisions.capture(initial[name][0])
                if captured["revision"] != digest or captured["bytes"] != member["bytes"]:
                    raise ValueError(f"stale_workspace_member:{name}")
                if digest not in saved_objects:
                    obj = temporary / "object.zip"
                    revisions.export(digest, obj)
                    archive.write(obj, f"objects/{digest}.zip")
                    obj.unlink()
                    saved_objects.add(digest)
        if any(_probe(root, name)[1] != stamp for name, (_, stamp) in initial.items()):
            raise ValueError("workspace_changed_during_capture")
        os.link(staged, output)
    return {"ok": True, "capsule": identity, "entry": graph["entry"], "files": len(initial),
            "distinct_objects": len(saved_objects), "archive_bytes": output.stat().st_size}


def _unpack_graph(archive, expected):
    with archive.open("graph.json") as stream:
        graph = _graph(_read_json(stream))
    identity = sha(canonical(graph))
    if identity != expected:
        raise ValueError("workspace_capsule_identity_mismatch")
    objects = {m["sha256"] for m in graph["files"]}
    members = {"graph.json", *(f"objects/{digest}.zip" for digest in objects)}
    if len(archive.infolist()) != len(members) or set(archive.namelist()) != members:
        raise ValueError("workspace_capsule_object_inventory_mismatch")
    return graph


@contextmanager
def _object(archive, digest, scratch=None):
    """Copy one nested ZIP for random access. Reading to EOF also verifies its outer CRC."""
    item = archive.getinfo(f"objects/{digest}.zip")
    if item.compress_type != zipfile.ZIP_STORED or item.file_size != item.compress_size:
        raise ValueError("workspace_revision_wrapper_must_be_stored")
    with tempfile.TemporaryFile(dir=scratch) as local:
        with archive.open(item) as incoming:
            shutil.copyfileobj(incoming, local, length=256 * 1024)
        local.seek(0)
        yield local


def verify(archive_path: Path, expected: str, directory: Path | None = None):
    with zipfile.ZipFile(archive_path) as archive:
        graph = _unpack_graph(archive, expected)
        objects = {m["sha256"]: m["bytes"] for m in graph["files"]}
        for digest, size in objects.items():
            with _object(archive, digest) as local:
                FileRevisions.verify_full(local, revision=digest, size=size)
    result = {"capsule": expected, "checked": len(graph["files"]), "verified_objects": len(objects),
              "checked_directory": directory is not None}
    if directory is None:
        return {**result, "ok": True, "problems": []}
    root = directory.resolve(strict=True)
    problems, stamps = [], {}
    for m in graph["files"]:
        name = m["path"]
        try:
            path, before = _probe(root, name)
            with path.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            if before[2] != m["bytes"] or digest != m["sha256"]:
                problems.append({"path": name, "reason": "modified"})
            else:
                stamps[name] = before
        except FileNotFoundError:
            problems.append({"path": name, "reason": "missing"})
        except (OSError, ValueError) as exc:
            problems.append({"path": name, "reason": str(exc)})
    for name, before in stamps.items():
        try:
            if _probe(root, name)[1] != before:
                problems.append({"path": name, "reason": "modified"})
        except FileNotFoundError:
            problems.append({"path": name, "reason": "missing"})
        except (OSError, ValueError) as exc:
            problems.append({"path": name, "reason": str(exc)})
    return {**result, "ok": not problems, "problems": problems}


def _publish_directory(stage, output):
    # POSIX rename normally overwrites an empty destination. Keep that directory intact.
    if os.name == "nt":
        os.rename(stage, output)
        return
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform.startswith("linux") and hasattr(libc, "renameat2"):
        result = libc.renameat2(-100, os.fsencode(stage), -100, os.fsencode(output), 1)
    elif sys.platform == "darwin" and hasattr(libc, "renamex_np"):
        result = libc.renamex_np(os.fsencode(stage), os.fsencode(output), 4)
    else:
        raise OSError(errno.ENOTSUP, "atomic no-replace directory rename unavailable")
    if result != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), str(output))


def restore(revisions: FileRevisions, archive_path: Path, expected: str, output: Path):
    output = output.absolute()
    if os.path.lexists(output):
        raise FileExistsError(output)
    with zipfile.ZipFile(archive_path) as archive, tempfile.TemporaryDirectory(
            prefix=".workspace-restore-", dir=output.parent) as workspace:
        graph = _unpack_graph(archive, expected)
        stage = Path(workspace) / "tree"
        stage.mkdir()
        restored = set()
        for m in graph["files"]:
            digest = m["sha256"]
            if digest not in restored:
                with _object(archive, digest, workspace) as local:
                    revisions.receive(local, expected_full=(digest, m["bytes"]))
                restored.add(digest)
            target = stage / m["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            result = revisions.restore(digest, target)
            if result["bytes"] != m["bytes"]:
                raise ValueError(f"workspace_size_mismatch:{m['path']}")
        _publish_directory(stage, output)
    return {"ok": True, "capsule": expected, "entry": str(output / graph["entry"]), "files": len(graph["files"])}
