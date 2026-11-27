"""CHIMERA Omega-Spine: Zero-Shell Self-Converging Release Conductor.

Eliminates ad-hoc agent shell deployment (`taskkill`, `Start-ScheduledTask`,
`tar | ssh ... systemctl restart`) via a Two-Phase Transactional Release model:
  1. Stage immutable release tree + deterministic tree SHA-256 manifest.
  2. Out-of-band standby verification (`py_compile` + isolated import dry-run)
     BEFORE modifying any desired-state pointer (NEVER kill before verify!).
  3. Push-over-PHANTOM replication (`POST /v1/omega/release/receive`) with
     SHA-256 + optional HMAC-SHA256 verification and strict tar traversal guard,
     preserving platform-native binaries (`_chimera_core.so`/`.dll`, `chimera-hook`).
  4. Atomic `DESIRED_RELEASE.json` write consumed by OS supervisors (`systemd.path`
     on Linux / Scheduled Task watcher on Windows) with automatic dead-man rollback.

100% Python stdlib, lazy-loaded (Laws 1-7 compliant; +0 MB idle RSS).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
import os
import py_compile
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

_EPOCH_RE = re.compile(r"^[A-Za-z0-9._-]{3,64}$")
_SKIP_DIR_NAMES = frozenset({"__pycache__", ".git", ".pytest_cache", "node_modules", ".mypy_cache"})
_SKIP_SUFFIXES = frozenset({".pyc", ".pyo"})
_MAX_ARCHIVE_BYTES = 24 * 1024 * 1024  # 24 MiB hard cap for gzipped source release

# Read-only hygiene audit markers known to cause pre-tool safety classifier false positives
_HYGIENE_TRIGGER_PHRASES = (
    "reverse shell",
    "credential harvester",
    "exploit",
    "backdoor",
    "operating policy",
    "non-con",
)


def default_releases_root() -> Path:
    env_override = os.environ.get("CHIMERA_RELEASES_ROOT", "").strip()
    if env_override:
        return Path(env_override).expanduser()
    if os.name == "nt":
        local_app = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(local_app) / "chimera" / "releases"
    xdg_data = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(xdg_data) / "chimera" / "releases"


def sanitize_epoch(epoch: str) -> str:
    ep = str(epoch or "").strip()
    if not _EPOCH_RE.fullmatch(ep) or ep in (".", "..") or ".." in ep:
        raise ValueError(f"Invalid release epoch name: {epoch!r}")
    return ep


def _compute_tree_manifest(root: Path) -> tuple[str, int, dict[str, str]]:
    """Compute deterministic SHA-256 manifest of all .py files under `root`."""
    entries: dict[str, str] = {}
    acc = hashlib.sha256()
    if not root.is_dir():
        return acc.hexdigest(), 0, entries
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIR_NAMES)
        for fn in sorted(filenames):
            if fn.endswith(".py"):
                files.append(Path(dirpath) / fn)
    for fp in files:
        rel = fp.relative_to(root).as_posix()
        digest = hashlib.sha256(fp.read_bytes()).hexdigest()
        entries[rel] = digest
        acc.update(rel.encode("utf-8"))
        acc.update(b":")
        acc.update(digest.encode("ascii"))
        acc.update(b"\n")
    return acc.hexdigest(), len(entries), entries


def _compile_tree_py(pkg_root: Path) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    for dirpath, dirnames, filenames in os.walk(pkg_root):
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIR_NAMES)
        for fn in sorted(filenames):
            if not fn.endswith(".py"):
                continue
            fp = Path(dirpath) / fn
            try:
                py_compile.compile(str(fp), doraise=True)
            except py_compile.PyCompileError as exc:
                errors.append({"file": fp.relative_to(pkg_root).as_posix(), "error": str(exc)[:300]})
    return errors


def _atomic_write_json(target: Path, data: dict[str, Any]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.{os.getpid()}.{time.time_ns()}.tmp")
    payload = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
    tmp.write_bytes(payload)
    os.replace(tmp, target)


def _hmac_key() -> bytes:
    raw = os.environ.get("CHIMERA_RELEASE_HMAC_KEY", "").strip()
    return raw.encode("utf-8") if raw else b""


def _sign_digest(archive_sha256: str, epoch: str) -> str:
    key = _hmac_key()
    if not key:
        return ""
    msg = f"{epoch}:{archive_sha256}".encode("utf-8")
    return hmac.new(key, msg, hashlib.sha256).hexdigest()


def _verify_hmac(archive_sha256: str, epoch: str, provided_sig: str) -> bool:
    key = _hmac_key()
    if not key:
        return True
    expected = _sign_digest(archive_sha256, epoch)
    return bool(provided_sig) and hmac.compare_digest(expected, str(provided_sig).strip())


def _safe_extract_tar_gz(archive_bytes: bytes, dest_dir: Path) -> int:
    """Strictly extract gzipped tar into `dest_dir`, blocking traversal, symlinks & absolute paths."""
    dest_resolved = dest_dir.resolve()
    extracted = 0
    with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:gz") as tf:
        for member in tf.getmembers():
            name = member.name.replace("\\", "/")
            if not name or name.startswith("/") or ".." in Path(name).parts:
                raise ValueError(f"Unsafe tar member path rejected: {member.name!r}")
            if member.issym() or member.islnk() or member.isdev():
                raise ValueError(f"Unsafe tar member link/device rejected: {member.name!r}")
            target = (dest_resolved / name).resolve()
            try:
                target.relative_to(dest_resolved)
            except ValueError as exc:
                raise ValueError(f"Tar member escapes destination: {member.name!r}") from exc
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                target.parent.mkdir(parents=True, exist_ok=True)
                src_f = tf.extractfile(member)
                if src_f is not None:
                    with src_f, open(target, "wb") as out_f:
                        shutil.copyfileobj(src_f, out_f)
                    extracted += 1
    return extracted


def context_hygiene_audit(workspace_paths: list[str] | None = None) -> dict[str, Any]:
    """Read-only diagnostic auditing GEMINI.md files for bloat or false-positive trigger keywords."""
    candidates: list[Path] = [Path.home() / ".gemini" / "GEMINI.md"]
    for wp in workspace_paths or []:
        p = Path(wp)
        if p.is_dir():
            candidates.append(p / "GEMINI.md")
    seen: set[str] = set()
    findings: list[dict[str, Any]] = []
    for fp in candidates:
        key = str(fp).lower()
        if key in seen or not fp.is_file():
            continue
        seen.add(key)
        try:
            txt = fp.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        low = txt.lower()
        hits = [kw for kw in _HYGIENE_TRIGGER_PHRASES if kw in low]
        bloated = len(txt) > 16384
        if hits or bloated:
            findings.append({
                "path": str(fp),
                "chars": len(txt),
                "est_tokens": len(txt) // 4,
                "bloated": bloated,
                "trigger_hits": hits,
                "advisory": (
                    "Separate non-coding policy text from coding GEMINI.md to prevent "
                    "pre-tool classifier false positives and reduce per-turn token overhead."
                ),
            })
    return {
        "ok": True,
        "clean": len(findings) == 0,
        "findings_count": len(findings),
        "findings": findings,
    }


class ReleaseConductor:
    """Two-Phase Self-Converging Release Conductor for win-desktop <-> svhome."""

    def __init__(
        self,
        *,
        releases_root: Path | None = None,
        active_release_dir: Path | None = None,
    ) -> None:
        self.releases_root = Path(releases_root) if releases_root is not None else default_releases_root()
        self._active_release_dir = Path(active_release_dir) if active_release_dir is not None else None
        self._lock = threading.Lock()
        self._stats: dict[str, Any] = {
            "staged": 0,
            "received": 0,
            "replicated": 0,
            "verified": 0,
            "rejected": 0,
            "desired_writes": 0,
        }

    @property
    def desired_manifest_path(self) -> Path:
        return self.releases_root / "DESIRED_RELEASE.json"

    @property
    def receipt_path(self) -> Path:
        return self.releases_root / "RELEASE_RECEIPT.json"

    def active_epoch(self) -> str:
        if self._active_release_dir is not None:
            return self._active_release_dir.name
        try:
            pkg_parent = Path(__file__).resolve().parents[2]
            if pkg_parent.parent.resolve() == self.releases_root.resolve():
                return pkg_parent.name
        except Exception:
            pass
        return ""

    def _find_native_donor(self, exclude_epoch: str = "") -> Path | None:
        """Locate an existing release carrying platform-native `_chimera_core` & `chimera-hook`."""
        native_name = "_chimera_core.pyd" if os.name == "nt" else "_chimera_core.so"
        alt_name = "_chimera_core.dll" if os.name == "nt" else "_chimera_core.so"
        candidates: list[Path] = []
        active = self.active_epoch()
        if active and active != exclude_epoch:
            candidates.append(self.releases_root / active)
        if self.releases_root.is_dir():
            for d in sorted(self.releases_root.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
                if d.is_dir() and d.name != exclude_epoch and d not in candidates:
                    candidates.append(d)
        for cand in candidates:
            pkg = cand / "chimera_tp"
            if (pkg / native_name).is_file() or (pkg / alt_name).is_file():
                return cand
        return None

    def _preserve_platform_binaries(self, target_release: Path, donor: Path | None) -> list[str]:
        preserved: list[str] = []
        if donor is None or not donor.is_dir():
            return preserved
        pkg_names = ("_chimera_core.dll", "_chimera_core.pyd") if os.name == "nt" else ("_chimera_core.so",)
        for fn in pkg_names:
            src = donor / "chimera_tp" / fn
            dst = target_release / "chimera_tp" / fn
            if src.is_file() and not dst.is_file():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                preserved.append(f"chimera_tp/{fn}")
        hook_name = "chimera-hook.exe" if os.name == "nt" else "chimera-hook"
        src_h = donor / "bin" / hook_name
        dst_h = target_release / "bin" / hook_name
        if src_h.is_file() and not dst_h.is_file():
            dst_h.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_h, dst_h)
            preserved.append(f"bin/{hook_name}")
        return preserved

    def stage_release(
        self,
        source_dir: str | Path,
        *,
        epoch: str | None = None,
        verify: bool = True,
        write_desired: bool = False,
    ) -> dict[str, Any]:
        src = Path(source_dir).expanduser().resolve()
        src_pkg = src / "chimera_tp"
        if not src_pkg.is_dir():
            raise ValueError(f"Source directory missing chimera_tp package: {src}")

        tree_sha, py_count, _ = _compute_tree_manifest(src_pkg)
        ep = sanitize_epoch(epoch or f"omega_{tree_sha[:12]}")
        self.releases_root.mkdir(parents=True, exist_ok=True)
        dest = self.releases_root / ep
        tmp_dir = Path(tempfile.mkdtemp(prefix=f".stage-{ep}-", dir=str(self.releases_root)))
        try:
            def _ignore(_d: str, names: list[str]) -> set[str]:
                return {n for n in names if n in _SKIP_DIR_NAMES or Path(n).suffix in _SKIP_SUFFIXES}

            shutil.copytree(src_pkg, tmp_dir / "chimera_tp", ignore=_ignore)
            src_bin = src / "bin"
            if src_bin.is_dir():
                shutil.copytree(src_bin, tmp_dir / "bin")
            preserved = self._preserve_platform_binaries(tmp_dir, self._find_native_donor(exclude_epoch=ep))

            compile_errors = _compile_tree_py(tmp_dir / "chimera_tp")
            if compile_errors:
                with self._lock:
                    self._stats["rejected"] += 1
                return {"ok": False, "epoch": ep, "error": "py_compile_failed", "compile_errors": compile_errors[:10]}

            staged_sha, staged_count, _ = _compute_tree_manifest(tmp_dir / "chimera_tp")
            manifest = {
                "schema": "chimera.release.manifest.v1",
                "epoch": ep,
                "tree_sha256": staged_sha,
                "py_files": staged_count,
                "staged_at": round(time.time(), 3),
                "source_dir": str(src),
                "preserved_binaries": preserved,
            }
            _atomic_write_json(tmp_dir / "RELEASE_MANIFEST.json", manifest)

            if dest.exists():
                backup_old = self.releases_root / f".replaced-{ep}-{time.time_ns()}"
                os.replace(dest, backup_old)
                shutil.rmtree(backup_old, ignore_errors=True)
            os.replace(tmp_dir, dest)
        except Exception:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise

        with self._lock:
            self._stats["staged"] += 1

        ver_res = self.verify_standby(ep) if verify else {"ok": True, "skipped": True}
        if not ver_res.get("ok"):
            with self._lock:
                self._stats["rejected"] += 1
            return {"ok": False, "epoch": ep, "staged_dir": str(dest), "verify": ver_res}

        desired_res = None
        if write_desired:
            desired_res = self.write_desired_manifest(ep, verify_first=False)

        return {
            "ok": True,
            "epoch": ep,
            "staged_dir": str(dest),
            "tree_sha256": staged_sha,
            "py_files": staged_count,
            "preserved_binaries": preserved,
            "verify": ver_res,
            "desired": desired_res,
        }

    def verify_standby(self, epoch: str, timeout_s: float = 12.0) -> dict[str, Any]:
        """Verify a staged release out-of-band WITHOUT stopping the active daemon."""
        ep = sanitize_epoch(epoch)
        rel_dir = self.releases_root / ep
        pkg_dir = rel_dir / "chimera_tp"
        if not pkg_dir.is_dir():
            return {"ok": False, "epoch": ep, "error": f"release_not_found:{ep}"}

        compile_errors = _compile_tree_py(pkg_dir)
        if compile_errors:
            return {"ok": False, "epoch": ep, "error": "py_compile_failed", "compile_errors": compile_errors[:10]}

        # Isolated subprocess import probe (confirms zero SyntaxError/ImportError in standby,
        # and strictly imports ONLY from `rel_dir` with stdlib — proving Law 7 zero-bloat!)
        probe_code = (
            "import sys, json, importlib; "
            "sys.path.insert(0, sys.argv[1]); "
            "mods = ['chimera_tp.omega_spine', 'chimera_tp.omega_spine.streamable_mcp', "
            "'chimera_tp.omega_spine.hook_router', 'chimera_tp.omega_spine.release_conductor']; "
            "loaded = [m for m in mods if importlib.import_module(m) is not None]; "
            "print(json.dumps({'ok': True, 'loaded': loaded}))"
        )
        creation_flags = 0x08000000 if os.name == "nt" else 0
        t0 = time.perf_counter()
        try:
            proc = subprocess.run(
                [sys.executable, "-I", "-c", probe_code, str(rel_dir)],
                cwd=str(rel_dir),
                capture_output=True,
                text=True,
                timeout=max(3.0, float(timeout_s)),
                creationflags=creation_flags,
            )
            ms = round((time.perf_counter() - t0) * 1000.0, 2)
            if proc.returncode != 0:
                return {
                    "ok": False,
                    "epoch": ep,
                    "error": "standby_import_failed",
                    "stderr": (proc.stderr or "")[-600:],
                    "ms": ms,
                }
            parsed = json.loads((proc.stdout or "{}").strip().splitlines()[-1])
        except Exception as exc:
            return {"ok": False, "epoch": ep, "error": f"standby_probe_error:{exc}"}

        tree_sha, py_count, _ = _compute_tree_manifest(pkg_dir)
        with self._lock:
            self._stats["verified"] += 1
        return {
            "ok": bool(parsed.get("ok")),
            "epoch": ep,
            "tree_sha256": tree_sha,
            "py_files": py_count,
            "loaded": parsed.get("loaded", []),
            "ms": ms,
        }

    def write_desired_manifest(
        self,
        epoch: str,
        *,
        rollback_epoch: str | None = None,
        verify_first: bool = True,
    ) -> dict[str, Any]:
        """Atomically write DESIRED_RELEASE.json after standby verification passes."""
        ep = sanitize_epoch(epoch)
        rel_dir = self.releases_root / ep
        if verify_first:
            vr = self.verify_standby(ep)
            if not vr.get("ok"):
                with self._lock:
                    self._stats["rejected"] += 1
                return {"ok": False, "epoch": ep, "error": "refused_unverified_release", "verify": vr}
        tree_sha, py_count, _ = _compute_tree_manifest(rel_dir / "chimera_tp")
        rb = sanitize_epoch(rollback_epoch) if rollback_epoch else self.active_epoch()
        if rb == ep:
            rb = ""
        manifest = {
            "schema": "chimera.desired_release.v1",
            "epoch": ep,
            "rollback_epoch": rb,
            "tree_sha256": tree_sha,
            "py_files": py_count,
            "requested_at": round(time.time(), 3),
            "health_endpoints": ["/.well-known/chimera.json", "/mcp"],
        }
        _atomic_write_json(self.desired_manifest_path, manifest)
        with self._lock:
            self._stats["desired_writes"] += 1
        return {"ok": True, "desired_manifest": str(self.desired_manifest_path), "manifest": manifest}

    def pack_release_payload(self, epoch: str) -> dict[str, Any]:
        ep = sanitize_epoch(epoch)
        rel_dir = self.releases_root / ep
        pkg_dir = rel_dir / "chimera_tp"
        if not pkg_dir.is_dir():
            raise ValueError(f"Release not found: {rel_dir}")
        tree_sha, py_count, _ = _compute_tree_manifest(pkg_dir)
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz", compresslevel=6) as tf:
            for dirpath, dirnames, filenames in os.walk(pkg_dir):
                dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIR_NAMES)
                for fn in sorted(filenames):
                    # Do NOT ship Windows .dll/.pyd to Linux peer (peer preserves its own .so!)
                    if Path(fn).suffix.lower() in (".pyc", ".pyo", ".dll", ".pyd", ".so", ".exe"):
                        continue
                    fp = Path(dirpath) / fn
                    arcname = fp.relative_to(rel_dir).as_posix()
                    tf.add(fp, arcname=arcname, recursive=False)
        archive_bytes = buf.getvalue()
        if len(archive_bytes) > _MAX_ARCHIVE_BYTES:
            raise ValueError(f"Release archive exceeds limit ({len(archive_bytes)} > {_MAX_ARCHIVE_BYTES})")
        archive_sha = hashlib.sha256(archive_bytes).hexdigest()
        return {
            "schema": "chimera.release.wire.v1",
            "epoch": ep,
            "tree_sha256": tree_sha,
            "py_files": py_count,
            "archive_sha256": archive_sha,
            "archive_bytes": len(archive_bytes),
            "hmac_sha256": _sign_digest(archive_sha, ep),
            "archive_b64": base64.b64encode(archive_bytes).decode("ascii"),
        }

    def receive_release(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Receive, verify, extract & standby-test a peer-replicated release (zero SSH!)."""
        ep = sanitize_epoch(str(payload.get("epoch") or ""))
        expected_sha = str(payload.get("archive_sha256") or "").strip().lower()
        b64 = str(payload.get("archive_b64") or "")
        if not b64 or not expected_sha:
            with self._lock:
                self._stats["rejected"] += 1
            return {"ok": False, "epoch": ep, "error": "missing_archive_or_sha256"}

        try:
            archive_bytes = base64.b64decode(b64.encode("ascii"), validate=True)
        except Exception as exc:
            with self._lock:
                self._stats["rejected"] += 1
            return {"ok": False, "epoch": ep, "error": f"invalid_base64:{exc}"}

        if len(archive_bytes) > _MAX_ARCHIVE_BYTES:
            with self._lock:
                self._stats["rejected"] += 1
            return {"ok": False, "epoch": ep, "error": "archive_too_large"}

        actual_sha = hashlib.sha256(archive_bytes).hexdigest()
        if not hmac.compare_digest(actual_sha, expected_sha):
            with self._lock:
                self._stats["rejected"] += 1
            return {"ok": False, "epoch": ep, "error": "archive_sha256_mismatch"}

        if not _verify_hmac(actual_sha, ep, str(payload.get("hmac_sha256") or "")):
            with self._lock:
                self._stats["rejected"] += 1
            return {"ok": False, "epoch": ep, "error": "hmac_verification_failed"}

        self.releases_root.mkdir(parents=True, exist_ok=True)
        dest = self.releases_root / ep
        tmp_dir = Path(tempfile.mkdtemp(prefix=f".recv-{ep}-", dir=str(self.releases_root)))
        try:
            extracted_files = _safe_extract_tar_gz(archive_bytes, tmp_dir)
            if not (tmp_dir / "chimera_tp").is_dir():
                raise ValueError("Archive missing chimera_tp root directory")
            preserved = self._preserve_platform_binaries(tmp_dir, self._find_native_donor(exclude_epoch=ep))
            tree_sha, py_count, _ = _compute_tree_manifest(tmp_dir / "chimera_tp")
            expected_tree = str(payload.get("tree_sha256") or "").strip().lower()
            if expected_tree and not hmac.compare_digest(tree_sha, expected_tree):
                raise ValueError(f"tree_sha256 mismatch: {tree_sha} != {expected_tree}")
            _atomic_write_json(
                tmp_dir / "RELEASE_MANIFEST.json",
                {
                    "schema": "chimera.release.manifest.v1",
                    "epoch": ep,
                    "tree_sha256": tree_sha,
                    "py_files": py_count,
                    "received_at": round(time.time(), 3),
                    "preserved_binaries": preserved,
                },
            )
            if dest.exists():
                backup_old = self.releases_root / f".replaced-{ep}-{time.time_ns()}"
                os.replace(dest, backup_old)
                shutil.rmtree(backup_old, ignore_errors=True)
            os.replace(tmp_dir, dest)
        except Exception as exc:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            with self._lock:
                self._stats["rejected"] += 1
            return {"ok": False, "epoch": ep, "error": str(exc)}

        verify_res = self.verify_standby(ep)
        if not verify_res.get("ok"):
            with self._lock:
                self._stats["rejected"] += 1
            return {"ok": False, "epoch": ep, "error": "standby_verification_failed", "verify": verify_res}

        with self._lock:
            self._stats["received"] += 1

        desired_res = None
        if bool(payload.get("write_desired", False)):
            desired_res = self.write_desired_manifest(ep, verify_first=False)

        return {
            "ok": True,
            "epoch": ep,
            "extracted_files": extracted_files,
            "tree_sha256": tree_sha,
            "py_files": py_count,
            "preserved_binaries": preserved,
            "verify": verify_res,
            "desired": desired_res,
        }

    def replicate_to_peer(
        self,
        epoch: str,
        peer_url: str,
        *,
        write_desired: bool = True,
        timeout_s: float = 30.0,
    ) -> dict[str, Any]:
        """Push a staged release to a peer daemon via HTTP `/v1/omega/release/receive` (PHANTOM-ready)."""
        wire = self.pack_release_payload(epoch)
        wire["write_desired"] = bool(write_desired)
        url = peer_url.rstrip("/") + "/v1/omega/release/receive"
        req = urllib.request.Request(
            url,
            data=json.dumps(wire).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=max(5.0, float(timeout_s))) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                peer_res = json.loads(raw)
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="replace")[:400]
            return {"ok": False, "epoch": wire["epoch"], "peer_url": url, "http_status": exc.code, "error": err_body}
        except Exception as exc:
            return {"ok": False, "epoch": wire["epoch"], "peer_url": url, "error": str(exc)}

        ms = round((time.perf_counter() - t0) * 1000.0, 2)
        if peer_res.get("ok"):
            with self._lock:
                self._stats["replicated"] += 1
        return {
            "ok": bool(peer_res.get("ok")),
            "epoch": wire["epoch"],
            "peer_url": url,
            "archive_bytes": wire["archive_bytes"],
            "ms": ms,
            "peer_response": peer_res,
        }

    def render_os_watcher_units(self, watcher_script: str | Path | None = None) -> dict[str, Any]:
        """Return ready-to-install Linux systemd.path + service units for OS-driven zero-shell convergence."""
        rel_root_posix = self.releases_root.as_posix()
        script_posix = str(watcher_script or "/home/svhome/DEV/chimera-tp/scripts/chimera_release_watcher.py")
        path_unit = (
            "[Unit]\n"
            "Description=Watch CHIMERA DESIRED_RELEASE.json for atomic self-converging updates\n\n"
            "[Path]\n"
            f"PathChanged={rel_root_posix}/DESIRED_RELEASE.json\n"
            "Unit=chimera-release-watcher.service\n\n"
            "[Install]\n"
            "WantedBy=default.target\n"
        )
        service_unit = (
            "[Unit]\n"
            "Description=CHIMERA Atomic Release Convergence & Dead-Man Rollback\n\n"
            "[Service]\n"
            "Type=oneshot\n"
            f"ExecStart=/usr/bin/python3 {script_posix} --converge --releases-root {rel_root_posix}\n"
        )
        return {
            "ok": True,
            "systemd_path_unit": path_unit,
            "systemd_service_unit": service_unit,
            "desired_manifest_path": str(self.desired_manifest_path),
        }

    def status(self) -> dict[str, Any]:
        staged: list[str] = []
        if self.releases_root.is_dir():
            for d in sorted(self.releases_root.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
                if d.is_dir() and not d.name.startswith(".") and (d / "chimera_tp").is_dir():
                    staged.append(d.name)
        desired = None
        if self.desired_manifest_path.is_file():
            try:
                desired = json.loads(self.desired_manifest_path.read_text(encoding="utf-8"))
            except Exception:
                desired = {"error": "unreadable"}
        receipt = None
        if self.receipt_path.is_file():
            try:
                receipt = json.loads(self.receipt_path.read_text(encoding="utf-8"))
            except Exception:
                receipt = {"error": "unreadable"}
        with self._lock:
            stats = dict(self._stats)
        return {
            "ok": True,
            "releases_root": str(self.releases_root),
            "active_epoch": self.active_epoch(),
            "staged_epochs": staged[:12],
            "desired": desired,
            "last_receipt": receipt,
            "hmac_enabled": bool(_hmac_key()),
            "stats": stats,
        }
