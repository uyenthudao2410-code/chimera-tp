"""v26.0 CHIMERA-SINGULARITY-STREAM: Precognition Stream Tap, Read-Only Speculative Warmup & Turn-Atomic Time-Machine.

All primitives strictly preserve CHIMERA-ONE Invariant Laws:
- Zero-IQ-Loss: never mutates prompts, reasoning_effort, tool schemas, or streamed bytes.
- Zero-Weight (<80 MiB daemon RSS): bounded buffers (<=32 KiB/stream), streaming 64 KiB page-cache reads
  (0 retained RAM), SQLite-backed FileRevisions for persistent checkpoints (0 persistent RAM).
- Zero-Subprocess-Popup: any child call uses CREATE_NO_WINDOW on Windows and strict read-only allowlists.
"""

from __future__ import annotations

import collections
import hashlib
import json
import os
import queue
import re
import shlex
import stat
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit


_SSE_FAST_HINTS = (b"tool_calls", b"function_call", b"arguments", b"output_item", b"custom_tool_call")

_PATH_FIELD_RE = re.compile(
    r'"(?:path|file_path|file|filepath|target_file|TargetFile|Path|AbsolutePath|SearchPath|DirectoryPath|cwd)"\s*:\s*"((?:[^"\\]|\\.){2,360})"',
    re.IGNORECASE,
)
_URL_RE = re.compile(r"https?://[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]{4,240}")
_CMD_FIELD_RE = re.compile(
    r'"(?:command|cmd|CommandLine)"\s*:\s*"((?:[^"\\]|\\.){2,240})"',
    re.IGNORECASE,
)
_SHELL_META_RE = re.compile(r"[&|;><`\r\n]|\$\(")

_GIT_RO_SUBCMDS = frozenset({"status", "diff", "log", "rev-parse", "branch", "show"})
_FORBIDDEN_PYTEST_FLAGS = frozenset({"-o", "--override-ini", "--basetemp", "--rootdir"})


def _is_unc_or_symlink(p: Path) -> bool:
    s = str(p)
    if s.startswith("\\\\") or s.startswith("//"):
        return True
    try:
        st = os.lstat(p)
        if stat.S_ISLNK(st.st_mode):
            return True
        reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        if reparse and (getattr(st, "st_file_attributes", 0) & reparse):
            return True
    except OSError:
        return True
    return False


def _within_roots(target: Path, allowed_roots: list[Path] | None) -> bool:
    if not allowed_roots:
        return True
    try:
        resolved = target.resolve(strict=False)
    except OSError:
        return False
    for root in allowed_roots:
        try:
            resolved.relative_to(root.resolve(strict=False))
            return True
        except ValueError:
            continue
    return False


def warm_file_paths(
    paths: list[str | Path],
    *,
    budget_bytes: int = 2 * 1024 * 1024,
    per_file_cap: int = 262_144,
    chunk_bytes: int = 65_536,
    allowed_roots: list[Path] | None = None,
) -> dict[str, Any]:
    """Stream-read regular local files into the OS page cache and discard immediately (0 retained RSS)."""
    t0 = time.perf_counter()
    budget = max(65_536, min(int(budget_bytes), 64 * 1024 * 1024))
    file_cap = max(4096, min(int(per_file_cap), 8 * 1024 * 1024))
    chunk = max(4096, min(int(chunk_bytes), 262_144))

    warmed: list[str] = []
    skipped = 0
    total_read = 0
    seen: set[str] = set()

    for raw in paths:
        if total_read >= budget:
            break
        try:
            p = Path(str(raw).strip())
        except Exception:
            skipped += 1
            continue
        key = str(p).lower() if os.name == "nt" else str(p)
        if not str(p) or key in seen:
            continue
        seen.add(key)

        if _is_unc_or_symlink(p) or not _within_roots(p, allowed_roots):
            skipped += 1
            continue
        try:
            st = os.lstat(p)
            if not stat.S_ISREG(st.st_mode) or st.st_size <= 0:
                skipped += 1
                continue
            want = min(st.st_size, file_cap, budget - total_read)
            if want <= 0:
                break
            read_here = 0
            with open(p, "rb", buffering=0) as fh:
                while read_here < want:
                    buf = fh.read(min(chunk, want - read_here))
                    if not buf:
                        break
                    read_here += len(buf)
            if read_here > 0:
                total_read += read_here
                warmed.append(str(p))
        except OSError:
            skipped += 1

    return {
        "ok": True,
        "warmed_files": len(warmed),
        "paths": warmed[:16],
        "bytes_read": total_read,
        "skipped": skipped,
        "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 3),
    }


def validate_readonly_command(cmd: str | list[str]) -> tuple[bool, list[str], str]:
    """Strictly allowlist pure read-only tool commands; reject shell metacharacters & mutators."""
    if isinstance(cmd, str):
        raw = cmd.strip()
        if not raw or len(raw) > 512:
            return False, [], "empty_or_too_long"
        if _SHELL_META_RE.search(raw):
            return False, [], "shell_metacharacters_forbidden"
        try:
            argv = shlex.split(raw, posix=(os.name != "nt"))
        except ValueError:
            return False, [], "malformed_command"
    elif isinstance(cmd, list):
        argv = [str(x).strip() for x in cmd if str(x).strip()]
        if not argv or any(_SHELL_META_RE.search(tok) for tok in argv):
            return False, [], "shell_metacharacters_forbidden"
    else:
        return False, [], "invalid_type"

    if not argv:
        return False, [], "empty_argv"

    exe = Path(argv[0]).name.lower()
    if exe.endswith(".exe"):
        exe = exe[:-4]
    rest = argv[1:]

    if exe == "git":
        clean: list[str] = ["git", "--no-optional-locks"]
        idx = 0
        while idx < len(rest) and rest[idx] in ("--no-optional-locks", "--no-pager"):
            idx += 1
        if idx >= len(rest) or rest[idx] not in _GIT_RO_SUBCMDS:
            return False, [], "git_subcommand_not_readonly"
        sub = rest[idx]
        tail = rest[idx + 1 :]
        if sub == "branch" and any(t in ("-d", "-D", "-m", "-M", "-f", "--delete", "--move") for t in tail):
            return False, [], "git_branch_mutating"
        clean.append(sub)
        clean.extend(tail)
        return True, clean, "ok"

    if exe in ("python", "python3"):
        if len(rest) >= 3 and rest[0] == "-m" and rest[1] == "py_compile":
            return True, [exe, "-B", "-m", "py_compile", *rest[2:]], "ok"
        if len(rest) >= 3 and rest[0] == "-m" and rest[1] == "pytest" and "--collect-only" in rest[2:]:
            if any(tok in _FORBIDDEN_PYTEST_FLAGS for tok in rest[2:]):
                return False, [], "pytest_flag_forbidden"
            return True, [exe, "-B", "-m", "pytest", *rest[2:]], "ok"
        return False, [], "python_cmd_not_readonly"

    if exe == "pytest":
        if "--collect-only" not in rest:
            return False, [], "pytest_requires_collect_only"
        if any(tok in _FORBIDDEN_PYTEST_FLAGS for tok in rest):
            return False, [], "pytest_flag_forbidden"
        return True, ["pytest", *rest], "ok"

    if exe == "ruff":
        if len(rest) >= 1 and rest[0] == "check":
            if any(t.startswith("--fix") or t == "--unsafe-fixes" for t in rest):
                return False, [], "ruff_fix_forbidden"
            out = ["ruff", "check", "--no-fix"] + [t for t in rest[1:] if t != "--no-fix"]
            return True, out, "ok"
        return False, [], "ruff_subcommand_not_readonly"

    if exe == "mypy":
        if any(t in ("--install-types", "--non-interactive") for t in rest):
            return False, [], "mypy_mutating_flag"
        return True, ["mypy", *rest], "ok"

    if exe == "tsc":
        if "--noEmit" not in rest and "--noemit" not in [t.lower() for t in rest]:
            return False, [], "tsc_requires_noEmit"
        return True, ["tsc", *rest], "ok"

    if exe == "cargo":
        if len(rest) >= 1 and rest[0] == "check" and "--offline" in rest:
            return True, ["cargo", *rest], "ok"
        return False, [], "cargo_requires_check_offline"

    return False, [], f"exe_not_allowlisted:{exe}"


def _decode_json_fragment_str(escaped: str) -> str:
    try:
        return json.loads(f'"{escaped}"')
    except Exception:
        return escaped.replace("\\\\", "\\").replace('\\"', '"')


class PrecogWarmupPool:
    """Single bounded background worker executing read-only precognition warmups with 0 SSE latency impact."""

    def __init__(
        self,
        *,
        egress_getter: Callable[[], Any] | None = None,
        pulse_getter: Callable[[], Any] | None = None,
        allowed_roots_getter: Callable[[], list[Path]] | None = None,
        max_queue: int = 32,
    ) -> None:
        self._egress_getter = egress_getter
        self._pulse_getter = pulse_getter
        self._allowed_roots_getter = allowed_roots_getter
        self._q: queue.Queue[tuple[str, dict[str, Any]] | None] = queue.Queue(maxsize=max(4, int(max_queue)))
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._recent: collections.deque[dict[str, Any]] = collections.deque(maxlen=32)
        self._stats: dict[str, int] = {
            "taps_started": 0,
            "tool_calls_seen": 0,
            "hints_emitted": 0,
            "files_warmed": 0,
            "bytes_warmed": 0,
            "hosts_prewarmed": 0,
            "readonly_checks_run": 0,
            "readonly_checks_blocked": 0,
            "queue_drops": 0,
        }

    def _ensure_worker(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            if self._stop.is_set():
                return
            self._thread = threading.Thread(target=self._run, name="chimera-precog-warm", daemon=True)
            self._thread.start()

    def close(self) -> None:
        self._stop.set()
        try:
            self._q.put_nowait(None)
        except queue.Full:
            pass

    def bump(self, key: str, delta: int = 1) -> None:
        with self._lock:
            self._stats[key] = int(self._stats.get(key, 0)) + int(delta)

    def submit(self, kind: str, payload: dict[str, Any]) -> bool:
        if self._stop.is_set():
            return False
        self._ensure_worker()
        try:
            self._q.put_nowait((kind, payload))
            return True
        except queue.Full:
            self.bump("queue_drops", 1)
            return False

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                item = self._q.get(timeout=1.0)
            except queue.Empty:
                continue
            if item is None:
                break
            kind, payload = item
            try:
                self._handle_task(kind, payload)
            except Exception:
                pass

    def _handle_task(self, kind: str, payload: dict[str, Any]) -> None:
        rec: dict[str, Any] = {
            "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
            "kind": kind,
            "turn_id": payload.get("turn_id", ""),
        }
        if kind == "paths":
            paths = list(payload.get("paths") or [])
            roots = None
            if self._allowed_roots_getter is not None:
                try:
                    cand = self._allowed_roots_getter()
                    if cand:
                        roots = [Path(r) for r in cand]
                except Exception:
                    roots = None
            res = warm_file_paths(
                paths,
                budget_bytes=int(payload.get("budget_bytes", 2 * 1024 * 1024)),
                per_file_cap=int(payload.get("per_file_cap", 262_144)),
                allowed_roots=roots,
            )
            self.bump("files_warmed", int(res.get("warmed_files", 0)))
            self.bump("bytes_warmed", int(res.get("bytes_read", 0)))
            rec.update({"warmed_files": res.get("warmed_files", 0), "bytes_read": res.get("bytes_read", 0), "elapsed_ms": res.get("elapsed_ms", 0.0)})
        elif kind == "host":
            host = str(payload.get("host") or "").strip().lower()
            port = int(payload.get("port") or 443)
            egress = self._egress_getter() if self._egress_getter else None
            if egress is not None and host and host not in ("127.0.0.1", "localhost", "::1"):
                try:
                    ips = egress._dns.resolve(host, port)
                    ranked = egress._pop_bandit.rank(host, ips) if ips else []
                    if ranked:
                        egress._note_host_heat_and_prewarm(host, port, ranked[0])
                        self.bump("hosts_prewarmed", 1)
                        rec.update({"host": host, "port": port, "ip": ranked[0]})
                except Exception:
                    rec.update({"host": host, "port": port, "error": "prewarm_failed"})
        elif kind == "readonly_cmd":
            cmd = payload.get("command") or ""
            cwd = payload.get("cwd") or ""
            ok_cmd, clean_argv, reason = validate_readonly_command(cmd)
            if not ok_cmd:
                self.bump("readonly_checks_blocked", 1)
                rec.update({"blocked": True, "reason": reason})
            else:
                self.bump("readonly_checks_run", 1)
                rec.update({"argv": clean_argv[:6], "cwd": str(cwd)})
                if payload.get("allow_exec") and cwd and Path(cwd).is_dir():
                    try:
                        from . import guarded_build

                        out = guarded_build.submit_isolated(
                            " ".join(shlex.quote(a) for a in clean_argv) if os.name != "nt" else subprocess_join(clean_argv),
                            cwd=str(cwd),
                            target=str(payload.get("target") or "local"),
                            sync=True,
                            reuse=True,
                            environment_id=str(payload.get("environment_id") or "precog-readonly-v1"),
                            timeout_s=min(30, int(payload.get("timeout_s", 15))),
                        )
                        rec.update({"exec_ok": bool(out.get("ok")), "reused": bool(out.get("reused", False))})
                    except Exception as exc:
                        rec.update({"exec_ok": False, "error": str(exc)[:120]})

        with self._lock:
            self._recent.append(rec)

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                **dict(self._stats),
                "queue_depth": self._q.qsize(),
                "recent": list(self._recent)[-12:],
            }


def subprocess_join(argv: list[str]) -> str:
    import subprocess

    return subprocess.list2cmdline(argv)


class PrecognitionStreamTap:
    """Passive read-only SSE delta parser (<=32 KiB/stream) that fires warmups before [DONE]."""

    MAX_LINE_BYTES = 16_384
    MAX_ACTIVE_CALLS = 8
    MAX_ARG_BYTES = 4_096
    MAX_TARGETS_PER_TURN = 16

    def __init__(
        self,
        pool: PrecogWarmupPool,
        *,
        turn_id: str = "",
        session_id: str = "",
        workspace_root: str = "",
        allow_exec: bool = False,
        pulse_fn: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        self._pool = pool
        self.turn_id = turn_id
        self.session_id = session_id
        self.workspace_root = str(workspace_root or "").strip()
        self.allow_exec = bool(allow_exec)
        self._pulse_fn = pulse_fn

        self._line_buf = bytearray()
        self._drop_line = False
        self._call_args: dict[str, bytearray] = {}
        self._call_names: dict[str, str] = {}
        self._seen_targets: set[str] = set()
        self.hints_fired = 0
        self.tool_calls_seen = 0
        self._pool.bump("taps_started", 1)

    def feed(self, chunk: bytes) -> None:
        if not chunk or len(self._seen_targets) >= self.MAX_TARGETS_PER_TURN:
            return
        start = 0
        n = len(chunk)
        while start < n:
            nl = chunk.find(b"\n", start)
            if nl == -1:
                piece = chunk[start:]
                if not self._drop_line:
                    if len(self._line_buf) + len(piece) > self.MAX_LINE_BYTES:
                        self._line_buf.clear()
                        self._drop_line = True
                    else:
                        self._line_buf.extend(piece)
                return
            piece = chunk[start:nl]
            start = nl + 1
            if self._drop_line:
                self._drop_line = False
                self._line_buf.clear()
                continue
            if self._line_buf:
                if len(self._line_buf) + len(piece) <= self.MAX_LINE_BYTES:
                    self._line_buf.extend(piece)
                    line = bytes(self._line_buf)
                else:
                    line = b""
                self._line_buf.clear()
            else:
                line = piece
            if line:
                self._process_line(line)

    def close(self) -> None:
        self._line_buf.clear()
        self._call_args.clear()
        self._call_names.clear()

    def _process_line(self, raw_line: bytes) -> None:
        line = raw_line.strip()
        if not line.startswith(b"data:"):
            return
        payload = line[5:].strip()
        if not payload or payload == b"[DONE]":
            return
        if not any(tok in payload for tok in _SSE_FAST_HINTS):
            return
        try:
            obj = json.loads(payload.decode("utf-8", errors="ignore"))
        except Exception:
            return
        if not isinstance(obj, dict):
            return

        # 1. OpenAI Chat Completions delta.tool_calls / delta.function_call
        choices = obj.get("choices")
        if isinstance(choices, list):
            for ch in choices:
                if not isinstance(ch, dict):
                    continue
                delta = ch.get("delta")
                if not isinstance(delta, dict):
                    continue
                tcs = delta.get("tool_calls")
                if isinstance(tcs, list):
                    for tc in tcs:
                        if not isinstance(tc, dict):
                            continue
                        if "index" in tc and tc.get("index") is not None:
                            cid = f"idx:{tc.get('index')}"
                        else:
                            cid = str(tc.get("id") or "idx:0")
                        fn = tc.get("function") if isinstance(tc.get("function"), dict) else {}
                        name = str(fn.get("name") or "")
                        arg_delta = str(fn.get("arguments") or "")
                        self._ingest_call_delta(cid, name, arg_delta)
                fc = delta.get("function_call")
                if isinstance(fc, dict):
                    self._ingest_call_delta("fn:0", str(fc.get("name") or ""), str(fc.get("arguments") or ""))

        # 2. OpenAI Responses API events
        ev_type = str(obj.get("type") or "")
        if ev_type == "response.output_item.added":
            item = obj.get("item") if isinstance(obj.get("item"), dict) else {}
            if item.get("type") in ("function_call", "custom_tool_call"):
                cid = str(item.get("call_id") or item.get("id") or "resp:0")
                self._ingest_call_delta(cid, str(item.get("name") or ""), str(item.get("arguments") or item.get("input") or ""))
        elif ev_type in ("response.function_call_arguments.delta", "response.custom_tool_call_input.delta"):
            cid = str(obj.get("call_id") or obj.get("item_id") or "resp:0")
            self._ingest_call_delta(cid, "", str(obj.get("delta") or ""))

    def _ingest_call_delta(self, cid: str, name: str, arg_delta: str) -> None:
        if cid not in self._call_args:
            if len(self._call_args) >= self.MAX_ACTIVE_CALLS:
                return
            self._call_args[cid] = bytearray()
            self.tool_calls_seen += 1
            self._pool.bump("tool_calls_seen", 1)
        if name:
            self._call_names[cid] = name
        buf = self._call_args[cid]
        if arg_delta and len(buf) < self.MAX_ARG_BYTES:
            enc = arg_delta.encode("utf-8", errors="ignore")
            rem = self.MAX_ARG_BYTES - len(buf)
            buf.extend(enc[:rem])
        if buf:
            self._scan_args(cid, buf.decode("utf-8", errors="ignore"))

    def _scan_args(self, cid: str, text: str) -> None:
        if len(self._seen_targets) >= self.MAX_TARGETS_PER_TURN:
            return
        # 1. Predicted file paths
        for m in _PATH_FIELD_RE.finditer(text):
            raw_path = _decode_json_fragment_str(m.group(1)).strip()
            if not raw_path or raw_path.startswith(("http://", "https://")):
                continue
            cand = Path(raw_path)
            if not cand.is_absolute() and self.workspace_root:
                cand = Path(self.workspace_root) / cand
            key = f"path:{str(cand).lower() if os.name == 'nt' else str(cand)}"
            if key in self._seen_targets or len(self._seen_targets) >= self.MAX_TARGETS_PER_TURN:
                continue
            self._seen_targets.add(key)
            self._pool.submit("paths", {"paths": [str(cand)], "turn_id": self.turn_id})
            self._emit_hint("path", str(cand), self._call_names.get(cid, ""))

        # 2. Predicted public HTTP(S) hosts
        for m in _URL_RE.finditer(text):
            url = m.group(0)
            parts = urlsplit(url)
            host = (parts.hostname or "").lower()
            if not host or host in ("127.0.0.1", "localhost", "::1"):
                continue
            port = parts.port or (443 if parts.scheme == "https" else 80)
            key = f"host:{host}:{port}"
            if key in self._seen_targets or len(self._seen_targets) >= self.MAX_TARGETS_PER_TURN:
                continue
            self._seen_targets.add(key)
            self._pool.submit("host", {"host": host, "port": port, "turn_id": self.turn_id})
            self._emit_hint("host", f"{host}:{port}", self._call_names.get(cid, ""))

        # 3. Predicted read-only commands (strict allowlist)
        for m in _CMD_FIELD_RE.finditer(text):
            raw_cmd = _decode_json_fragment_str(m.group(1)).strip()
            if not raw_cmd:
                continue
            key = f"cmd:{raw_cmd}"
            if key in self._seen_targets or len(self._seen_targets) >= self.MAX_TARGETS_PER_TURN:
                continue
            ok_cmd, clean_argv, _ = validate_readonly_command(raw_cmd)
            if ok_cmd:
                self._seen_targets.add(key)
                self._pool.submit(
                    "readonly_cmd",
                    {
                        "command": clean_argv,
                        "cwd": self.workspace_root,
                        "allow_exec": self.allow_exec,
                        "turn_id": self.turn_id,
                    },
                )
                self._emit_hint("readonly_cmd", " ".join(clean_argv[:5]), self._call_names.get(cid, ""))

    def _emit_hint(self, hint_kind: str, target: str, tool_name: str) -> None:
        self.hints_fired += 1
        self._pool.bump("hints_emitted", 1)
        if self._pulse_fn is not None:
            try:
                self._pulse_fn(
                    "llm.precog_hint",
                    {
                        "turn_id": self.turn_id,
                        "session_id": self.session_id,
                        "hint_kind": hint_kind,
                        "target": target[:200],
                        "tool_name": tool_name[:64],
                    },
                )
            except Exception:
                pass


def _sha256_file(path: Path) -> str | None:
    if not path.exists():
        return None
    if _is_unc_or_symlink(path):
        raise ValueError(f"unsafe_path:{path}")
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(65_536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


class TurnTimeMachine:
    """Turn-Atomic workspace checkpoint & conflict-checked atomic os.replace rollback over FileRevisions."""

    MAX_CHECKPOINTS = 64

    def __init__(self, state_dir: Path | None = None, db_path: Path | None = None) -> None:
        base = Path(state_dir) if state_dir is not None else (Path.home() / ".chimera" / "aether")
        base.mkdir(parents=True, exist_ok=True)
        self.state_dir = base
        self.db_path = Path(db_path) if db_path is not None else (base / "turn_revisions.sqlite")
        self.manifest_path = base / "turn_checkpoints.json"
        self._lock = threading.Lock()

    def _load_manifests(self) -> dict[str, dict[str, Any]]:
        if not self.manifest_path.exists():
            return {}
        try:
            data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _save_manifests(self, data: dict[str, dict[str, Any]]) -> None:
        # Keep most recent MAX_CHECKPOINTS entries
        if len(data) > self.MAX_CHECKPOINTS:
            ordered = sorted(data.items(), key=lambda kv: float(kv[1].get("created_ts", 0.0)))
            data = dict(ordered[-self.MAX_CHECKPOINTS :])
        tmp = self.manifest_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.manifest_path)

    @staticmethod
    def _resolve_member(root: Path, rel: str) -> tuple[str, Path]:
        norm = str(rel or "").replace("\\", "/").strip().lstrip("/")
        if not norm or ".." in norm.split("/"):
            raise ValueError(f"invalid_relative_path:{rel}")
        dest = (root / norm)
        try:
            dest.resolve(strict=False).relative_to(root.resolve(strict=False))
        except ValueError as exc:
            raise ValueError(f"path_escapes_root:{rel}") from exc
        if dest.exists() and _is_unc_or_symlink(dest):
            raise ValueError(f"symlink_forbidden:{rel}")
        return norm, dest

    def checkpoint_turn(
        self,
        turn_id: str,
        root: str | Path,
        rel_paths: list[str],
        *,
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from .file_revisions import FileRevisions

        tid = str(turn_id or "").strip()
        if not tid:
            raise ValueError("turn_id_required")
        root_path = Path(root).resolve()
        if not root_path.is_dir():
            raise ValueError(f"root_not_directory:{root}")

        t0 = time.perf_counter()
        revs = FileRevisions(self.db_path)
        files_map: dict[str, dict[str, Any]] = {}
        captured_bytes = 0

        for rel in rel_paths:
            norm, dest = self._resolve_member(root_path, rel)
            if dest.exists():
                if not dest.is_file():
                    raise ValueError(f"not_regular_file:{norm}")
                cap = revs.capture(dest)
                captured_bytes += int(cap.get("bytes", 0))
                files_map[norm] = {
                    "before_rev": cap["revision"],
                    "before_bytes": int(cap.get("bytes", 0)),
                    "after_rev": None,
                    "finalized": False,
                }
            else:
                files_map[norm] = {
                    "before_rev": None,
                    "before_bytes": 0,
                    "after_rev": None,
                    "finalized": False,
                }

        entry = {
            "turn_id": tid,
            "root": str(root_path),
            "created_ts": time.time(),
            "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "meta": dict(meta or {}),
            "files": files_map,
            "finalized": False,
            "rolled_back": False,
        }
        with self._lock:
            manifests = self._load_manifests()
            manifests[tid] = entry
            self._save_manifests(manifests)

        return {
            "ok": True,
            "turn_id": tid,
            "root": str(root_path),
            "files_tracked": len(files_map),
            "captured_bytes": captured_bytes,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 3),
        }

    def finalize_turn(self, turn_id: str) -> dict[str, Any]:
        tid = str(turn_id or "").strip()
        with self._lock:
            manifests = self._load_manifests()
            entry = manifests.get(tid)
            if not entry:
                return {"ok": False, "error": "checkpoint_not_found", "turn_id": tid}
            root_path = Path(entry["root"])
            for norm, rec in (entry.get("files") or {}).items():
                _, dest = self._resolve_member(root_path, norm)
                rec["after_rev"] = _sha256_file(dest)
                rec["finalized"] = True
            entry["finalized"] = True
            entry["finalized_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
            manifests[tid] = entry
            self._save_manifests(manifests)
        return {"ok": True, "turn_id": tid, "files_tracked": len(entry.get("files") or {})}

    def rollback_turn(self, turn_id: str, *, force: bool = False) -> dict[str, Any]:
        from .file_revisions import FileRevisions

        tid = str(turn_id or "").strip()
        t0 = time.perf_counter()
        with self._lock:
            manifests = self._load_manifests()
            entry = manifests.get(tid)
            if not entry:
                return {"ok": False, "error": "checkpoint_not_found", "turn_id": tid}

            root_path = Path(entry["root"])
            files_map: dict[str, dict[str, Any]] = entry.get("files") or {}

            # Phase 1: optimistic conflict check (zero writes if externally mutated after finalize)
            conflicts: list[str] = []
            resolved_targets: list[tuple[str, Path, str | None]] = []
            for norm, rec in files_map.items():
                _, dest = self._resolve_member(root_path, norm)
                before_rev = rec.get("before_rev")
                after_rev = rec.get("after_rev")
                if rec.get("finalized") and not force:
                    cur_rev = _sha256_file(dest)
                    if cur_rev not in (before_rev, after_rev):
                        conflicts.append(norm)
                resolved_targets.append((norm, dest, before_rev))

            if conflicts:
                return {
                    "ok": False,
                    "error": "workspace_changed",
                    "turn_id": tid,
                    "conflicts": conflicts,
                }

            # Phase 2: atomic per-file restore via sibling temp + os.replace (handles existing targets!)
            revs = FileRevisions(self.db_path)
            restored_files = 0
            removed_files = 0
            for norm, dest, before_rev in resolved_targets:
                if before_rev is None:
                    if dest.exists():
                        dest.unlink()
                        removed_files += 1
                    # Best-effort prune empty parent dirs inside root
                    parent = dest.parent
                    while parent != root_path:
                        try:
                            parent.rmdir()
                            parent = parent.parent
                        except OSError:
                            break
                else:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    fd, tmp_name = tempfile.mkstemp(prefix=".chimera-tm-", dir=str(dest.parent))
                    os.close(fd)
                    tmp_path = Path(tmp_name)
                    try:
                        # FileRevisions.restore uses os.link -> destination path must not exist
                        tmp_path.unlink()
                        revs.restore(before_rev, tmp_path)
                        os.replace(tmp_path, dest)
                        restored_files += 1
                    finally:
                        if tmp_path.exists():
                            try:
                                tmp_path.unlink()
                            except OSError:
                                pass

            entry["rolled_back"] = True
            entry["rolled_back_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
            manifests[tid] = entry
            self._save_manifests(manifests)

        return {
            "ok": True,
            "turn_id": tid,
            "root": str(root_path),
            "restored_files": restored_files,
            "removed_files": removed_files,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 3),
        }

    def list_checkpoints(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            manifests = self._load_manifests()
        rows = sorted(manifests.values(), key=lambda x: float(x.get("created_ts", 0.0)), reverse=True)
        out: list[dict[str, Any]] = []
        for r in rows[: max(1, min(int(limit), 64))]:
            out.append(
                {
                    "turn_id": r.get("turn_id"),
                    "root": r.get("root"),
                    "created_at": r.get("created_at"),
                    "files_tracked": len(r.get("files") or {}),
                    "finalized": bool(r.get("finalized", False)),
                    "rolled_back": bool(r.get("rolled_back", False)),
                    "meta": r.get("meta") or {},
                }
            )
        return out

    def get_checkpoint(self, turn_id: str) -> dict[str, Any] | None:
        with self._lock:
            return self._load_manifests().get(str(turn_id or "").strip())
