"""Cooperative leases across Git worktrees and explicit desktop workspace manifests."""

from __future__ import annotations

import errno
import hashlib
import json
import os
import subprocess
from contextlib import ExitStack, contextmanager
from pathlib import Path
from urllib.parse import urlsplit


def _git(root: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(root), *args], text=True, encoding="utf-8",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    ).strip()


class LeaseBusy(Exception):
    pass


@contextmanager
def _lock(path: Path):
    handle = path.open("a+b")
    try:
        if os.name == "nt":
            import msvcrt
            if handle.seek(0, os.SEEK_END) == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        handle.close()
        if exc.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
            raise LeaseBusy(path.name) from exc
        raise
    try:
        yield
    finally:
        # Closing the handle also releases the OS lock after an agent crashes.
        handle.close()


@contextmanager
def file_leases(repo: Path, files: list[str]):
    top = Path(_git(repo, "rev-parse", "--show-toplevel")).resolve()
    shared = Path(_git(top, "rev-parse", "--path-format=absolute", "--git-common-dir")).resolve()
    directory = shared / "chimera-leases"
    directory.mkdir(exist_ok=True)
    names = set()
    for name in files:
        target = (repo / name).resolve()
        if top not in target.parents or shared in target.parents or target.is_dir():
            raise ValueError("lease target must be a file under the worktree")
        names.add(os.path.normcase(str(target.relative_to(top))).replace("\\", "/"))
    if not names:
        raise ValueError("at least one lease target is required")
    with ExitStack() as stack:
        for name in sorted(names):
            digest = hashlib.sha256(name.encode()).hexdigest()
            stack.enter_context(_lock(directory / digest))
        yield top


def run_leased(repo: Path, files: list[str], command: list[str], isolate_at: Path | None = None):
    if not command:
        raise ValueError("missing command")
    try:
        with file_leases(repo, files):
            return subprocess.run(command, cwd=repo, check=False).returncode
    except LeaseBusy:
        if isolate_at is None:
            return 75
    # Detached HEAD gives the second writer a different index and working files.
    # Refuse when HEAD would omit other writers' uncommitted state.
    top = Path(_git(repo, "rev-parse", "--show-toplevel")).resolve()
    destination = isolate_at.resolve()
    if destination.exists() or top in destination.parents:
        raise ValueError("choose a new worktree path outside the original")
    if _git(top, "status", "--porcelain", "--untracked-files=all"):
        raise ValueError("current worktree has pending changes; retry the lease or commit an explicit base")
    _git(top, "worktree", "add", "--detach", str(destination), "HEAD")
    cwd = destination / repo.resolve().relative_to(top)
    return subprocess.run(command, cwd=cwd, check=False).returncode


def workspace_manifest(files, urls, terminals):
    documents = [str(Path(p).resolve(strict=True)) for p in files]
    dirs = [str(Path(p).resolve(strict=True)) for p in terminals]
    if any(not Path(p).is_file() for p in documents) or any(not Path(p).is_dir() for p in dirs):
        raise ValueError("expected document files and terminal directories")
    for url in urls:
        parsed = urlsplit(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("select HTTP(S) URLs without embedded credentials")
    return {"version": 1, "files": documents, "urls": list(urls), "terminal_dirs": dirs}


def read_workspace(path: Path):
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("version") != 1:
        raise ValueError("unsupported workspace manifest")
    return workspace_manifest(data["files"], data["urls"], data["terminal_dirs"])


def open_workspace(manifest):
    import webbrowser

    if os.name != "nt":
        raise ValueError("desktop restore currently requires Windows")
    allowed = {".dwg", ".dxf", ".pdf", ".txt", ".csv", ".xlsx", ".png", ".jpg", ".md"}
    if any(Path(p).suffix.lower() not in allowed for p in manifest["files"]):
        raise ValueError("desktop open supports document formats only")
    for file in manifest["files"]:
        os.startfile(file, "open")
    for url in manifest["urls"]:
        webbrowser.open_new_tab(url)
    for directory in manifest["terminal_dirs"]:
        subprocess.Popen(["cmd.exe", "/d"], cwd=directory, creationflags=subprocess.CREATE_NEW_CONSOLE)
