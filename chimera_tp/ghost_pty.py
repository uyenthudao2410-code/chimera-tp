"""CHIMERA v5.0 Breakthrough #2: Ghost-PTY Persistent Detachable Terminal."""

from __future__ import annotations

import base64
import os
import select
import shutil
import struct
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

if os.name != "nt":
    import fcntl
    import pty
    import termios

_RING_MAX = 256 * 1024


@dataclass
class _PtyEntry:
    session_id: str
    shell: str
    cwd: str
    cols: int
    rows: int
    proc: subprocess.Popen[bytes]
    master_fd: int | None
    created_at: float = field(default_factory=time.time)
    last_active: float = field(default_factory=time.monotonic)
    cond: threading.Condition = field(default_factory=threading.Condition)
    buf: bytearray = field(default_factory=bytearray)
    base_offset: int = 0
    cursor: int = 0
    closed: bool = False

    def append_output(self, data: bytes) -> None:
        if not data:
            return
        with self.cond:
            self.buf.extend(data)
            self.cursor += len(data)
            if len(self.buf) > _RING_MAX:
                excess = len(self.buf) - _RING_MAX
                del self.buf[:excess]
                self.base_offset += excess
            self.last_active = time.monotonic()
            self.cond.notify_all()


class GhostPtyManager:
    """Manages persistent interactive shells with cursor-indexed reattachment."""

    def __init__(self, max_sessions: int = 8) -> None:
        self.max_sessions = max(1, int(max_sessions))
        self._lock = threading.Lock()
        self._sessions: dict[str, _PtyEntry] = {}

    def _default_shell(self) -> list[str]:
        if os.name == "nt":
            pwsh = shutil.which("cmd.exe") or "cmd.exe"
            return [pwsh, "/Q"]
        bash = os.environ.get("SHELL") or shutil.which("bash") or "/bin/sh"
        return [bash, "-i"]

    def create_session(
        self,
        cwd: str = "",
        cols: int = 100,
        rows: int = 30,
        cmd: list[str] | None = None,
    ) -> dict[str, Any]:
        work_dir = str(Path(cwd).resolve()) if cwd and Path(cwd).is_dir() else str(Path.home())
        argv = cmd if cmd else self._default_shell()
        sid = uuid.uuid4().hex[:12]

        if os.name != "nt":
            master_fd, slave_fd = pty.openpty()
            self._set_winsize_fd(master_fd, cols, rows)
            env = dict(os.environ)
            env.setdefault("TERM", "xterm-256color")
            proc = subprocess.Popen(
                argv,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                cwd=work_dir,
                env=env,
                start_new_session=True,
                close_fds=True,
            )
            os.close(slave_fd)
            entry = _PtyEntry(
                session_id=sid,
                shell=" ".join(argv),
                cwd=work_dir,
                cols=int(cols),
                rows=int(rows),
                proc=proc,
                master_fd=master_fd,
            )
            threading.Thread(target=self._posix_reader, args=(entry,), daemon=True).start()
        else:
            proc = subprocess.Popen(
                argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                cwd=work_dir,
                bufsize=0,
            )
            entry = _PtyEntry(
                session_id=sid,
                shell=" ".join(argv),
                cwd=work_dir,
                cols=int(cols),
                rows=int(rows),
                proc=proc,
                master_fd=None,
            )
            threading.Thread(target=self._pipe_reader, args=(entry,), daemon=True).start()

        with self._lock:
            if len(self._sessions) >= self.max_sessions:
                oldest_id = min(self._sessions, key=lambda k: self._sessions[k].last_active)
                self._terminate_entry(self._sessions.pop(oldest_id))
            self._sessions[sid] = entry

        return self._session_meta(entry)

    @staticmethod
    def _set_winsize_fd(fd: int, cols: int, rows: int) -> None:
        if os.name == "nt":
            return
        try:
            ws = struct.pack("HHHH", max(10, int(rows)), max(20, int(cols)), 0, 0)
            fcntl.ioctl(fd, termios.TIOCSWINSZ, ws)
        except OSError:
            pass

    def _posix_reader(self, entry: _PtyEntry) -> None:
        fd = entry.master_fd
        if fd is None:
            return
        try:
            while not entry.closed:
                r, _, _ = select.select([fd], [], [], 0.25)
                if not r:
                    if entry.proc.poll() is not None:
                        break
                    continue
                try:
                    chunk = os.read(fd, 8192)
                except OSError:
                    break
                if not chunk:
                    break
                entry.append_output(chunk)
        finally:
            entry.proc.poll()
            with entry.cond:
                entry.closed = True
                entry.cond.notify_all()
            try:
                os.close(fd)
            except OSError:
                pass

    def _pipe_reader(self, entry: _PtyEntry) -> None:
        stdout = entry.proc.stdout
        if stdout is None:
            return
        try:
            while not entry.closed:
                chunk = stdout.read(1) if not hasattr(stdout, "read1") else stdout.read1(4096)  # type: ignore[attr-defined]
                if not chunk:
                    break
                entry.append_output(chunk)
        finally:
            entry.proc.poll()
            with entry.cond:
                entry.closed = True
                entry.cond.notify_all()

    def _get(self, session_id: str) -> _PtyEntry:
        with self._lock:
            ent = self._sessions.get(session_id)
            if ent is None:
                raise KeyError(f"Unknown Ghost-PTY session: {session_id}")
            return ent

    def write_input(self, session_id: str, data: bytes) -> dict[str, Any]:
        ent = self._get(session_id)
        ent.last_active = time.monotonic()
        if ent.master_fd is not None:
            os.write(ent.master_fd, data)
        elif ent.proc.stdin is not None:
            ent.proc.stdin.write(data)
            ent.proc.stdin.flush()
        return {"ok": True, "session_id": session_id, "written": len(data)}

    def read_output(
        self,
        session_id: str,
        cursor: int = 0,
        wait_ms: int = 400,
        max_bytes: int = 65536,
    ) -> dict[str, Any]:
        ent = self._get(session_id)
        cursor = max(0, int(cursor))
        timeout_s = max(0.0, min(5.0, float(wait_ms) / 1000.0))
        deadline = time.monotonic() + timeout_s

        with ent.cond:
            while ent.cursor <= cursor and not ent.closed:
                rem = deadline - time.monotonic()
                if rem <= 0:
                    break
                ent.cond.wait(timeout=rem)

            dropped = 0
            start_cur = cursor
            if start_cur < ent.base_offset:
                dropped = ent.base_offset - start_cur
                start_cur = ent.base_offset

            rel = start_cur - ent.base_offset
            chunk = bytes(ent.buf[rel : rel + max_bytes])
            next_cur = start_cur + len(chunk)
            alive = (ent.proc.poll() is None) and (not ent.closed)
            exit_code = ent.proc.returncode

        return {
            "session_id": session_id,
            "cursor": cursor,
            "next_cursor": next_cur,
            "dropped_bytes": dropped,
            "alive": alive,
            "exit_code": exit_code,
            "data_b64": base64.b64encode(chunk).decode("ascii"),
            "text": chunk.decode("utf-8", errors="replace"),
        }

    def resize(self, session_id: str, cols: int, rows: int) -> dict[str, Any]:
        ent = self._get(session_id)
        ent.cols = int(cols)
        ent.rows = int(rows)
        if ent.master_fd is not None:
            self._set_winsize_fd(ent.master_fd, ent.cols, ent.rows)
        return {"ok": True, "session_id": session_id, "cols": ent.cols, "rows": ent.rows}

    def _session_meta(self, ent: _PtyEntry) -> dict[str, Any]:
        alive = ent.proc.poll() is None and not ent.closed
        return {
            "session_id": ent.session_id,
            "shell": ent.shell,
            "cwd": ent.cwd,
            "cols": ent.cols,
            "rows": ent.rows,
            "cursor": ent.cursor,
            "alive": alive,
            "exit_code": ent.proc.returncode,
            "idle_s": round(time.monotonic() - ent.last_active, 1),
        }

    def list_sessions(self) -> list[dict[str, Any]]:
        with self._lock:
            return [self._session_meta(e) for e in self._sessions.values()]

    def _terminate_entry(self, ent: _PtyEntry) -> None:
        ent.closed = True
        with ent.cond:
            ent.cond.notify_all()
        for stream in (ent.proc.stdin, ent.proc.stdout, ent.proc.stderr):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass
        if ent.master_fd is not None:
            try:
                os.close(ent.master_fd)
            except OSError:
                pass
            ent.master_fd = None
        try:
            if ent.proc.poll() is None:
                ent.proc.terminate()
                try:
                    ent.proc.wait(timeout=1.5)
                except subprocess.TimeoutExpired:
                    ent.proc.kill()
                    ent.proc.wait(timeout=1.0)
            else:
                ent.proc.wait(timeout=0.5)
        except OSError:
            pass

    def close_session(self, session_id: str) -> bool:
        with self._lock:
            ent = self._sessions.pop(session_id, None)
        if ent is None:
            return False
        self._terminate_entry(ent)
        return True

    def close_all(self) -> None:
        with self._lock:
            entries = list(self._sessions.values())
            self._sessions.clear()
        for e in entries:
            self._terminate_entry(e)
