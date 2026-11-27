"""Exact, bounded build inputs, including tracked edits and non-ignored new files."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import zipfile


MAX_INPUT_BYTES = 64 * 1024 * 1024
MAX_FILES = 12000
MAX_WIRE_BYTES = MAX_INPUT_BYTES + 8 * 1024 * 1024
MANIFEST = "manifest.json"
NON_GIT_EXCLUDES = {".git", ".venv", "__pycache__", "node_modules", ".pytest_cache",
                    ".chimera_cold_backing", "venv", "target"}


def canonical(value) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def artifact_bytes(item, remaining: int) -> bytes:
    """Verify one wire artifact before its bytes are published to a build or CAS caller."""
    size = item.get("bytes")
    encoded = item.get("base64")
    if (type(size) is not int or not 0 <= size <= remaining or not isinstance(encoded, str)
            or len(encoded) != 4 * ((size + 2) // 3)):
        raise ValueError("artifact_integrity_failure")
    data = base64.b64decode(encoded, validate=True)
    if len(data) != size or sha(data) != item.get("sha256"):
        raise ValueError("artifact_integrity_failure")
    return data


def portable_path(name: str) -> str:
    if not isinstance(name, str) or not name or "\\" in name or "\0" in name or ":" in name:
        raise ValueError("invalid_workspace_path")
    parts = name.split("/")
    if any(part in {"", ".", ".."} or part.lower() == ".git" for part in parts):
        raise ValueError(f"invalid_workspace_path:{name!r}")
    credential_dirs = {".ssh", ".aws", ".gnupg", ".azure", ".kube"}
    if any(part.casefold() in credential_dirs for part in parts):
        raise ValueError(f"credential_directory_excluded:{name!r}")
    return name


def _git(root: Path, *args: str):
    return subprocess.run(["git", "--no-optional-locks", "-C", str(root), *args],
                          capture_output=True, timeout=25,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _git_root(cwd: Path):
    try:
        result = _git(cwd, "rev-parse", "--show-toplevel")
    except FileNotFoundError:
        if any((p / ".git").exists() for p in (cwd, *cwd.parents)):
            raise ValueError("git_required_for_workspace")
        return None
    if result.returncode:
        if any((p / ".git").exists() for p in (cwd, *cwd.parents)):
            raise ValueError("git_workspace_unreadable")
        return None
    return Path(os.fsdecode(result.stdout.rstrip(b"\r\n"))).resolve(strict=True)


def _inventory(root: Path, is_git: bool) -> dict[str, int]:
    if is_git:
        tracked = _git(root, "ls-files", "--stage", "-z")
        extra = _git(root, "ls-files", "--others", "--exclude-standard", "-z")
        if tracked.returncode or extra.returncode:
            raise ValueError("git_inventory_failed")
        entries = {}
        for raw in tracked.stdout.split(b"\0"):
            if not raw:
                continue
            fields, path = raw.split(b"\t", 1)
            mode, _, stage = fields.split()
            name = portable_path(os.fsdecode(path))
            if stage != b"0" or mode not in {b"100644", b"100755"}:
                raise ValueError(f"unresolved_or_unsupported_git_entry:{name}")
            if (root / name).exists() or (root / name).is_symlink():
                entries[name] = int(mode == b"100755")
        for raw in extra.stdout.split(b"\0"):
            if raw:
                name = portable_path(os.fsdecode(raw))
                entries[name] = -1
        return entries
    entries = {}

    def fail(error):
        raise error

    for directory, dirs, files in os.walk(root, onerror=fail):
        dirs[:] = [d for d in dirs if d not in NON_GIT_EXCLUDES]
        for d in dirs:
            node = Path(directory, d)
            if node.is_symlink() or getattr(node.lstat(), "st_file_attributes", 0) & 0x400:
                raise ValueError(f"linked_directory:{node.relative_to(root)}")
        for filename in files:
            name = portable_path((Path(directory, filename).relative_to(root)).as_posix())
            entries[name] = -1
    return entries


def _stamp(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def capture(cwd: Path, *, include_data: bool = True, limit: int = MAX_INPUT_BYTES) -> dict:
    cwd = Path(cwd).resolve(strict=True)
    if not cwd.is_dir() or not 0 < limit <= MAX_INPUT_BYTES:
        raise ValueError("invalid_workspace_or_budget")
    top = _git_root(cwd)
    root = top or cwd
    if root == Path(root.anchor) or root == Path.home().resolve():
        raise ValueError("select_a_project_directory")
    inventory = _inventory(root, top is not None)
    if len(inventory) > MAX_FILES:
        raise ValueError(f"snapshot_file_limit:{len(inventory)}>{MAX_FILES}")
    rows, stamps, total = [], {}, 0
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
        for name, mode in sorted(inventory.items()):
            path = root / name
            if path.resolve(strict=True) != path or path.is_symlink():
                raise ValueError(f"linked_input:{name}")
            st = path.lstat()
            if not stat.S_ISREG(st.st_mode) or getattr(st, "st_file_attributes", 0) & 0x400:
                raise ValueError(f"unsupported_input:{name}")
            if st.st_size > limit - total:
                raise ValueError(f"snapshot_byte_limit:{name}:{limit}")
            with path.open("rb") as stream:
                content = stream.read(st.st_size + 1)
                after = os.fstat(stream.fileno())
            if len(content) != st.st_size or _stamp(st) != _stamp(after):
                raise ValueError(f"source_changed:{name}")
            total += len(content)
            executable = bool(st.st_mode & 0o111) if mode < 0 or os.name != "nt" else bool(mode)
            rows.append([name, len(content), sha(content), executable])
            stamps[name] = _stamp(st)
            if include_data:
                archive.writestr("files/" + name, content)
        if inventory != _inventory(root, top is not None) or any(
            _stamp((root / name).lstat()) != stamp for name, stamp in stamps.items()
        ):
            raise ValueError("source_changed_during_snapshot")
        manifest = {"version": 1, "cwd": cwd.relative_to(root).as_posix(), "files": rows}
        archive.writestr(MANIFEST, canonical(manifest))
    wire = buf.getvalue()
    if len(wire) > MAX_WIRE_BYTES:
        raise ValueError("snapshot_wire_limit")
    scope = str(root)
    if top:
        common = _git(top, "rev-parse", "--path-format=absolute", "--git-common-dir")
        if common.returncode:
            raise ValueError("git_worktree_scope_unavailable")
        scope = os.fsdecode(common.stdout.rstrip(b"\r\n"))
    return {"name": root.name, "digest": sha(canonical(manifest)), "files": len(rows),
            "bytes": total, "wire": wire, "cwd": manifest["cwd"], "scope": scope}


def materialize(wire: bytes, expected: str, destination: Path, existing: Path | None = None):
    """Build an isolated tree from transmitted files or hash-verified receiver files."""
    if len(wire) > MAX_WIRE_BYTES:
        raise ValueError("snapshot_wire_limit")
    with zipfile.ZipFile(io.BytesIO(wire)) as archive:
        infos = archive.infolist()
        if len(infos) > MAX_FILES + 1 or archive.getinfo(MANIFEST).file_size > 6 * 1024 * 1024:
            raise ValueError("invalid_snapshot_directory")
        manifest = json.loads(archive.read(MANIFEST))
        if sha(canonical(manifest)) != expected or manifest["version"] != 1:
            raise ValueError("snapshot_manifest_mismatch")
        entries = manifest["files"]
        if not isinstance(entries, list) or len(entries) > MAX_FILES:
            raise ValueError("invalid_file_count")
        names, recorded, total = {MANIFEST}, set(), 0
        source = existing.resolve(strict=True) if existing is not None else None
        for name, size, digest, executable in entries:
            portable_path(name)
            if name in recorded or type(size) is not int or not 0 <= size <= MAX_INPUT_BYTES - total:
                raise ValueError(f"invalid_entry:{name}")
            recorded.add(name)
            total += size
            if source is None:
                member = "files/" + name
                names.add(member)
                if archive.getinfo(member).file_size != size:
                    raise ValueError(f"snapshot_size_mismatch:{name}")
                data = archive.read(member)
            else:
                path = source / name
                if path.resolve(strict=True) != path or not path.is_file() or path.stat().st_size != size:
                    raise ValueError(f"peer_workspace_mismatch:{name}")
                with path.open("rb") as stream:
                    data = stream.read(size + 1)
            if len(data) != size or sha(data) != digest:
                raise ValueError(f"snapshot_digest_mismatch:{name}")
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as stream:
                stream.write(data)
            target.chmod(0o755 if executable else 0o644)
        if len(infos) != len(names) or set(archive.namelist()) != names:
            raise ValueError("unexpected_zip_members")
        relative = manifest["cwd"]
        where = destination if relative == "." else destination / portable_path(relative)
        where.mkdir(parents=True, exist_ok=True)
        return where
