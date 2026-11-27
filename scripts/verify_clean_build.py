"""Verify clean Git-archive reproducibility, native wheel packaging, and pure-Python fallback.

Performs isolated verification strictly in temporary directories without mutating the
workspace Git repository or its commit history.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
_EXCLUDED_DIR_NAMES = frozenset({
    ".git",
    "__pycache__",
    "target",
    "dist",
    "build",
    ".venv",
    "venv",
    ".pytest_cache",
})
_EXCLUDED_SUFFIXES = (".pyc", ".pyo", ".pyd", ".prev", ".pdb", ".lib", ".exp", ".tmp")


def _run(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd is not None else None,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=_NO_WINDOW,
    )
    if check and proc.returncode != 0:
        raise RuntimeError(
            f"Command failed (rc={proc.returncode}): {' '.join(cmd)}\n"
            f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
    return proc


def _clean_subprocess_env() -> dict[str, str]:
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _venv_python(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _venv_cli(venv_dir: Path, name: str = "chimera-tp") -> Path:
    if os.name == "nt":
        exe = venv_dir / "Scripts" / f"{name}.exe"
        return exe if exe.exists() else (venv_dir / "Scripts" / name)
    return venv_dir / "bin" / name


def _supports_no_build_isolation(python_exe: Path) -> bool:
    code = (
        "import importlib.metadata as im, setuptools; "
        "ver = tuple(int(x) for x in setuptools.__version__.split('.')[:2] if x.isdigit()); "
        "eps = {e.name for e in im.entry_points(group='distutils.commands')}; "
        "print('OK' if (ver >= (68, 0) and 'bdist_wheel' in eps) else 'NO')"
    )
    proc = _run([str(python_exe), "-c", code], env=_clean_subprocess_env(), check=False)
    return proc.returncode == 0 and proc.stdout.strip().endswith("OK")


def _prepare_builder_python(tmp_root: Path) -> tuple[Path, str]:
    sys_py = Path(sys.executable)
    if _supports_no_build_isolation(sys_py):
        return sys_py, "no_build_isolation_host"
    builder_venv = tmp_root / "builder_venv"
    _run([str(sys_py), "-m", "venv", str(builder_venv)], env=_clean_subprocess_env())
    b_py = _venv_python(builder_venv)
    install = _run(
        [str(b_py), "-m", "pip", "install", "--quiet", "setuptools>=68.0", "wheel"],
        env=_clean_subprocess_env(),
        check=False,
    )
    if install.returncode == 0 and _supports_no_build_isolation(b_py):
        return b_py, "no_build_isolation_builder_venv"
    return sys_py, "pep517_isolated"


def _build_wheel(src_dir: Path, wheel_dir: Path, builder_py: Path, build_mode: str) -> Path:
    wheel_dir.mkdir(parents=True, exist_ok=True)
    cmd = [str(builder_py), "-m", "pip", "wheel", "--no-deps"]
    if build_mode.startswith("no_build_isolation"):
        cmd.append("--no-build-isolation")
    cmd.extend([str(src_dir), "-w", str(wheel_dir)])
    _run(cmd, cwd=src_dir, env=_clean_subprocess_env())
    wheels = sorted(wheel_dir.glob("*.whl"))
    if len(wheels) != 1:
        raise RuntimeError(f"Expected 1 wheel in {wheel_dir}, found: {[w.name for w in wheels]}")
    return wheels[0]


def _should_exclude_rel(rel_parts: tuple[str, ...], name: str) -> bool:
    if any(part in _EXCLUDED_DIR_NAMES or part.endswith(".egg-info") for part in rel_parts):
        return True
    lower = name.lower()
    if any(lower.endswith(suf) for suf in _EXCLUDED_SUFFIXES):
        return True
    if rel_parts == ("tasks", "clean_build_verification.json"):
        return True
    return False


def _git_status_and_ls(repo_root: Path) -> dict[str, Any]:
    probe = _run(["git", "-C", str(repo_root), "rev-parse", "--is-inside-work-tree"], check=False)
    if probe.returncode != 0 or probe.stdout.strip().lower() != "true":
        disk_files: list[str] = []
        for dp, dns, fns in os.walk(repo_root):
            dns[:] = [d for d in dns if d not in _EXCLUDED_DIR_NAMES and not d.endswith(".egg-info")]
            for fn in fns:
                fp = Path(dp) / fn
                rel = fp.relative_to(repo_root)
                if not _should_exclude_rel(rel.parts, fn):
                    disk_files.append(rel.as_posix())
        return {
            "head_sha": None,
            "tracked_files": [],
            "modified_tracked_files": [],
            "untracked_files_all": sorted(disk_files),
        }

    head_sha = _run(["git", "-C", str(repo_root), "rev-parse", "HEAD"], check=True).stdout.strip()
    ls_raw = _run(["git", "-C", str(repo_root), "ls-files", "-z"], check=True).stdout
    tracked = sorted(p for p in ls_raw.split("\0") if p)

    st_raw = _run(["git", "-C", str(repo_root), "status", "--porcelain=v1", "-z"], check=True).stdout
    entries = [e for e in st_raw.split("\0") if e]
    modified_tracked: list[str] = []
    untracked_all: list[str] = []
    i = 0
    while i < len(entries):
        rec = entries[i]
        code = rec[:2]
        path = rec[3:]
        if code == "??":
            p_abs = repo_root / path
            if p_abs.is_dir():
                for child in sorted(p_abs.rglob("*")):
                    if child.is_file():
                        rel = child.relative_to(repo_root).as_posix()
                        untracked_all.append(rel)
            else:
                untracked_all.append(path)
        else:
            modified_tracked.append(path)
            if code[0] in ("R", "C") or code[1] in ("R", "C"):
                i += 1
        i += 1

    return {
        "head_sha": head_sha,
        "tracked_files": tracked,
        "modified_tracked_files": sorted(set(modified_tracked)),
        "untracked_files_all": sorted(set(untracked_all)),
    }


def audit_git_candidate(repo_root: Path) -> dict[str, Any]:
    """Scan git ls-files, git status, and Python AST imports across chimera_tp/ and tests/."""
    git_info = _git_status_and_ls(repo_root)
    tracked_set = set(git_info["tracked_files"])
    untracked_all = git_info["untracked_files_all"]

    local_mods: dict[str, Path] = {}
    pkg_dirs: set[str] = set()
    for py_path in sorted((repo_root / "chimera_tp").rglob("*.py")):
        rel = py_path.relative_to(repo_root)
        if _should_exclude_rel(rel.parts, py_path.name):
            continue
        mod_parts = list(rel.with_suffix("").parts)
        if mod_parts[-1] == "__init__":
            mod_name = ".".join(mod_parts[:-1])
            pkg_dirs.add(mod_name)
        else:
            mod_name = ".".join(mod_parts)
        local_mods[mod_name] = py_path

    missing_local_imports: list[dict[str, str]] = []
    runtime_external_imports: dict[str, set[str]] = {}
    test_external_imports: dict[str, set[str]] = {}
    import_edges: dict[str, set[str]] = {}
    stdlib = sys.stdlib_module_names

    scan_roots = [repo_root / "chimera_tp", repo_root / "tests"]
    for scan_dir in scan_roots:
        if not scan_dir.exists():
            continue
        for py_path in sorted(scan_dir.rglob("*.py")):
            rel = py_path.relative_to(repo_root)
            if _should_exclude_rel(rel.parts, py_path.name):
                continue
            rel_posix = rel.as_posix()
            is_runtime_pkg = rel.parts[0] == "chimera_tp"
            src_parts = list(rel.with_suffix("").parts)
            pkg_parts = src_parts[:-1]  # package parts for both __init__.py and regular module
            tree = ast.parse(py_path.read_text(encoding="utf-8-sig"), filename=str(py_path))
            edges = import_edges.setdefault(rel_posix, set())
            ext_bucket = runtime_external_imports if is_runtime_pkg else test_external_imports
            ignored_local_tops = ("benchmarks", "tests") if is_runtime_pkg else ("benchmarks", "tests", "scripts")
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        top = alias.name.split(".")[0]
                        if alias.name == "chimera_tp" or alias.name.startswith("chimera_tp."):
                            if alias.name not in local_mods:
                                missing_local_imports.append({"file": rel_posix, "import": alias.name})
                            else:
                                edges.add(local_mods[alias.name].relative_to(repo_root).as_posix())
                        elif top not in stdlib and top not in ignored_local_tops:
                            ext_bucket.setdefault(top, set()).add(rel_posix)
                elif isinstance(node, ast.ImportFrom):
                    if node.level > 0:
                        cur_pkg = pkg_parts
                        up = node.level - 1
                        if up > len(cur_pkg):
                            missing_local_imports.append({"file": rel_posix, "import": f"{'.' * node.level}{node.module or ''}"})
                            continue
                        anchor = cur_pkg[: len(cur_pkg) - up]
                        base_mod = ".".join(anchor + ([node.module] if node.module else []))
                    else:
                        base_mod = node.module or ""

                    if base_mod == "chimera_tp" or base_mod.startswith("chimera_tp."):
                        if base_mod not in local_mods:
                            missing_local_imports.append({"file": rel_posix, "import": base_mod})
                        else:
                            edges.add(local_mods[base_mod].relative_to(repo_root).as_posix())
                            if base_mod in pkg_dirs:
                                for alias in node.names:
                                    sub_mod = f"{base_mod}.{alias.name}"
                                    if sub_mod in local_mods:
                                        edges.add(local_mods[sub_mod].relative_to(repo_root).as_posix())
                    elif node.level == 0 and base_mod:
                        top = base_mod.split(".")[0]
                        if top not in stdlib and top not in ignored_local_tops:
                            ext_bucket.setdefault(top, set()).add(rel_posix)

    # Transitive BFS from tracked chimera_tp/ and tests/ files to find every untracked module they require
    untracked_imported_mods: set[str] = set()
    queue = [f for f in import_edges if f in tracked_set]
    seen_nodes = set(queue)
    while queue:
        cur = queue.pop(0)
        for dep in import_edges.get(cur, ()):
            if dep not in tracked_set:
                untracked_imported_mods.add(dep)
            if dep not in seen_nodes:
                seen_nodes.add(dep)
                queue.append(dep)

    untracked_py = [
        p for p in untracked_all
        if p.endswith(".py") and not _should_exclude_rel(Path(p).parts, Path(p).name)
    ]
    required_untracked_chimera_py = [p for p in untracked_py if p.startswith("chimera_tp/")]
    required_untracked_tests_scripts_py = [
        p for p in untracked_py if p.startswith("tests/") or p.startswith("scripts/") or p.startswith("benchmarks/")
    ]
    excluded_artifacts = [
        p for p in untracked_all
        if _should_exclude_rel(Path(p).parts, Path(p).name)
    ]
    # Also note gitignored binaries in chimera_tp/
    native_binaries: dict[str, Any] = {}
    for bin_name in ("_chimera_core.dll", "_chimera_core.so"):
        bp = repo_root / "chimera_tp" / bin_name
        native_binaries[bin_name] = {
            "present": bp.is_file(),
            "bytes": bp.stat().st_size if bp.is_file() else 0,
            "sha256": _sha256_file(bp) if bp.is_file() else None,
        }
    prev_path = repo_root / "chimera_tp" / "_chimera_core.dll.prev"
    if prev_path.exists() and "chimera_tp/_chimera_core.dll.prev" not in excluded_artifacts:
        excluded_artifacts.append("chimera_tp/_chimera_core.dll.prev")

    return {
        "head_sha": git_info["head_sha"],
        "tracked_count": len(git_info["tracked_files"]),
        "modified_tracked_files": git_info["modified_tracked_files"],
        "untracked_files_all": untracked_all,
        "untracked_python_files": sorted(untracked_py),
        "required_untracked_files_for_git": sorted(
            set(required_untracked_chimera_py + required_untracked_tests_scripts_py)
        ),
        "required_untracked_chimera_modules": sorted(required_untracked_chimera_py),
        "required_untracked_tests_and_scripts": sorted(required_untracked_tests_scripts_py),
        "untracked_imported_by_tracked": sorted(untracked_imported_mods),
        "missing_local_imports": missing_local_imports,
        "external_third_party_imports": {k: sorted(v) for k, v in sorted(runtime_external_imports.items())},
        "test_external_imports": {k: sorted(v) for k, v in sorted(test_external_imports.items())},
        "excluded_artifacts": sorted(set(excluded_artifacts)),
        "native_binaries_in_workspace": native_binaries,
        "tracked_files": git_info["tracked_files"],
    }


def _copy_candidate_to_temp_git(
    repo_root: Path,
    stage_repo: Path,
    audit: dict[str, Any],
) -> tuple[bool, bool]:
    """Copy tracked + untracked source files (excluding build/target/dist/*.prev) into temp git repo.

    Creates two commits:
      - branch `pure-source` (HEAD~1): pure source candidate without _chimera_core.dll/.so
      - `HEAD`: same source plus force-added _chimera_core.dll/.so when present on disk
    Returns (has_dll, has_so).
    """
    stage_repo.mkdir(parents=True, exist_ok=True)
    candidates = sorted(set(audit["tracked_files"]) | set(audit["untracked_files_all"]))
    for rel_str in candidates:
        rel = Path(rel_str)
        if _should_exclude_rel(rel.parts, rel.name):
            continue
        if rel_str in ("chimera_tp/_chimera_core.dll", "chimera_tp/_chimera_core.so"):
            continue
        src = repo_root / rel
        if not src.is_file():
            continue
        dst = stage_repo / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    _run(["git", "init", "-b", "main"], cwd=stage_repo)
    _run(["git", "config", "user.name", "chimera-verify"], cwd=stage_repo)
    _run(["git", "config", "user.email", "chimera-verify@local"], cwd=stage_repo)
    _run(["git", "add", "-A"], cwd=stage_repo)
    _run(["git", "commit", "-m", "Pure-Python workspace candidate"], cwd=stage_repo)
    _run(["git", "branch", "pure-source", "HEAD"], cwd=stage_repo)

    has_dll = False
    has_so = False
    for bin_name in ("_chimera_core.dll", "_chimera_core.so"):
        src_bin = repo_root / "chimera_tp" / bin_name
        if src_bin.is_file():
            dst_bin = stage_repo / "chimera_tp" / bin_name
            dst_bin.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_bin, dst_bin)
            _run(["git", "add", "-f", f"chimera_tp/{bin_name}"], cwd=stage_repo)
            if bin_name == "_chimera_core.dll":
                has_dll = True
            else:
                has_so = True

    if has_dll or has_so:
        _run(["git", "commit", "-m", "Add built native core binary for wheel audit"], cwd=stage_repo)

    staged_files = _run(["git", "ls-files"], cwd=stage_repo).stdout.splitlines()
    prev_leaks = [f for f in staged_files if f.lower().endswith(".prev")]
    if prev_leaks:
        raise RuntimeError(f"Temp candidate git repo unexpectedly tracked .prev files: {prev_leaks}")
    return has_dll, has_so


def _export_git_archive(stage_repo: Path, ref: str, dest_dir: Path, tar_path: Path) -> None:
    dest_dir.mkdir(parents=True, exist_ok=True)
    _run(["git", "archive", "--format=tar", "-o", str(tar_path), ref], cwd=stage_repo)
    root_resolved = dest_dir.resolve()
    with tarfile.open(tar_path, "r") as tf:
        for member in tf.getmembers():
            target = (dest_dir / member.name).resolve()
            if not (target == root_resolved or target.is_relative_to(root_resolved)):
                raise RuntimeError(f"Unsafe tar member path: {member.name}")
        tf.extractall(dest_dir)


def _verify_wheel_in_venv(
    wheel_path: Path,
    venv_dir: Path,
    empty_cwd: Path,
    *,
    expect_native: bool,
    check_all_v21_v23: bool,
) -> dict[str, Any]:
    with zipfile.ZipFile(wheel_path, "r") as zf:
        names = zf.namelist()
    contains_dll = "chimera_tp/_chimera_core.dll" in names
    contains_so = "chimera_tp/_chimera_core.so" in names
    prev_files = [n for n in names if n.lower().endswith(".prev")]

    if prev_files:
        raise AssertionError(f"Wheel {wheel_path.name} unexpectedly contains .prev files: {prev_files}")
    if expect_native and os.name == "nt" and not contains_dll:
        raise AssertionError(f"Native Windows wheel {wheel_path.name} is missing chimera_tp/_chimera_core.dll")
    if not expect_native and (contains_dll or contains_so):
        raise AssertionError(f"Pure-Python fallback wheel {wheel_path.name} unexpectedly contains native binary")

    _run([sys.executable, "-m", "venv", str(venv_dir)], env=_clean_subprocess_env())
    v_py = _venv_python(venv_dir)
    _run(
        [str(v_py), "-m", "pip", "install", "--quiet", "--no-deps", "--no-index", str(wheel_path)],
        cwd=empty_cwd,
        env=_clean_subprocess_env(),
    )

    if check_all_v21_v23:
        probe_code = """
import json
from pathlib import Path
import chimera_tp
from chimera_tp.native import cpu_caps, has_native
from chimera_tp.platform.substrate import PlatformSubstrate
from chimera_tp.platform import cosmos_entity, hyper_desk, omega_entity, phantom_silicon, workspace_undo
from chimera_tp.platform.cosmos_entity import CosmosEntityEngine
from chimera_tp.platform.hyper_desk import HyperDeskEngine
from chimera_tp.platform.omega_entity import OmegaEntityEngine
from chimera_tp.platform.phantom_silicon import AgentExileEngine
from chimera_tp.platform.workspace_undo import WorkspaceUndo

print(json.dumps({
    "package_file": str(Path(chimera_tp.__file__).resolve()),
    "version": chimera_tp.__version__,
    "has_native": bool(has_native()),
    "cpu_caps": cpu_caps(),
    "imports": [
        PlatformSubstrate.__name__,
        CosmosEntityEngine.__name__,
        HyperDeskEngine.__name__,
        OmegaEntityEngine.__name__,
        AgentExileEngine.__name__,
        WorkspaceUndo.__name__,
        cosmos_entity.__name__,
        hyper_desk.__name__,
        omega_entity.__name__,
        phantom_silicon.__name__,
        workspace_undo.__name__,
    ],
}))
"""
    else:
        probe_code = """
import json
from pathlib import Path
import chimera_tp
from chimera_tp import cli
from chimera_tp.native import chacha20_xor, cpu_caps, fastcdc_split, gf256_scale, has_native
from chimera_tp.platform.substrate import PlatformSubstrate
from chimera_tp.platform import workspace_undo
from chimera_tp.platform.workspace_undo import WorkspaceUndo

scaled = gf256_scale(b"chimera-pure-fallback", 3)
enc = chacha20_xor(b"hello-world-pure", b"k" * 32, b"n" * 12)
dec = chacha20_xor(enc, b"k" * 32, b"n" * 12)
spans = fastcdc_split(b"abcd" * 2048)

print(json.dumps({
    "package_file": str(Path(chimera_tp.__file__).resolve()),
    "version": chimera_tp.__version__,
    "has_native": bool(has_native()),
    "cpu_caps": cpu_caps(),
    "imports": [PlatformSubstrate.__name__, WorkspaceUndo.__name__, cli.__name__, workspace_undo.__name__],
    "pure_fallback_ops_ok": (len(scaled) == 21 and dec == b"hello-world-pure" and len(spans) >= 1),
}))
"""
    proc = _run([str(v_py), "-c", probe_code], cwd=empty_cwd, env=_clean_subprocess_env())
    info = json.loads(proc.stdout.strip())

    pkg_path = Path(info["package_file"]).resolve()
    venv_resolved = venv_dir.resolve()
    if not pkg_path.is_relative_to(venv_resolved):
        raise AssertionError(f"Imported chimera_tp from {pkg_path}, outside isolated venv {venv_resolved}")
    if info["version"] != "18.0.0":
        raise AssertionError(f"Expected version 18.0.0, got {info['version']!r}")
    if expect_native:
        if os.name == "nt":
            if info["has_native"] is not True or info["cpu_caps"].get("native") is not True:
                raise AssertionError(f"Expected native enabled on Windows, got: {info}")
    else:
        if info["has_native"] is not False or info["cpu_caps"].get("native") is not False:
            raise AssertionError(f"Expected has_native()==False in pure fallback venv, got: {info}")
        if not info.get("pure_fallback_ops_ok"):
            raise AssertionError("Pure-Python fallback ops check failed")

    cli_exe = _venv_cli(venv_dir, "chimera-tp")
    cli_proc = _run([str(cli_exe), "--help"], cwd=empty_cwd, env=_clean_subprocess_env())

    return {
        "ok": True,
        "wheel_filename": wheel_path.name,
        "wheel_size_bytes": wheel_path.stat().st_size,
        "wheel_entries_count": len(names),
        "contains_native_dll": contains_dll,
        "contains_native_so": contains_so,
        "contains_prev_file": bool(prev_files),
        "installed_package_path": info["package_file"],
        "version": info["version"],
        "imports_ok": True,
        "verified_imports": info["imports"],
        "has_native": info["has_native"],
        "cpu_caps": info["cpu_caps"],
        "pure_fallback_ops_ok": info.get("pure_fallback_ops_ok"),
        "cli_help_exit_code": cli_proc.returncode,
    }


def run_clean_build_verification(
    repo_root: Path | None = None,
    out_json_path: Path | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path(__file__).resolve().parents[1]).resolve()
    out_path = out_json_path or (root / "tasks" / "clean_build_verification.json")

    audit = audit_git_candidate(root)
    if audit["missing_local_imports"]:
        raise AssertionError(f"Unresolved local chimera_tp imports found: {audit['missing_local_imports']}")

    tmp_root = Path(tempfile.mkdtemp(prefix="chimera-clean-build-"))
    try:
        stage_repo = tmp_root / "candidate_repo"
        has_dll, has_so = _copy_candidate_to_temp_git(root, stage_repo, audit)
        builder_py, build_mode = _prepare_builder_python(tmp_root)

        empty_cwd = tmp_root / "empty_cwd"
        empty_cwd.mkdir(parents=True, exist_ok=True)

        # 2a: Native wheel build from git archive HEAD
        export_native = tmp_root / "export_native"
        _export_git_archive(stage_repo, "HEAD", export_native, tmp_root / "archive_native.tar")
        wheel_native = _build_wheel(export_native, tmp_root / "wheels_native", builder_py, build_mode)
        native_res = _verify_wheel_in_venv(
            wheel_native,
            tmp_root / "venv_native",
            empty_cwd,
            expect_native=bool(has_dll or has_so),
            check_all_v21_v23=True,
        )
        native_res["build_mode"] = build_mode

        # 2b: Pure-Python fallback wheel build from git archive pure-source
        export_pure = tmp_root / "export_pure"
        _export_git_archive(stage_repo, "pure-source", export_pure, tmp_root / "archive_pure.tar")
        wheel_pure = _build_wheel(export_pure, tmp_root / "wheels_pure", builder_py, build_mode)
        pure_res = _verify_wheel_in_venv(
            wheel_pure,
            tmp_root / "venv_pure",
            empty_cwd,
            expect_native=False,
            check_all_v21_v23=False,
        )
        pure_res["build_mode"] = build_mode
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)

    # Strip large tracked_files list from saved summary while keeping counts and untracked audit
    audit_summary = {k: v for k, v in audit.items() if k != "tracked_files"}
    report: dict[str, Any] = {
        "ok": bool(native_res["ok"] and pure_res["ok"] and not audit["missing_local_imports"]),
        "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "platform": {
            "os": platform.system().lower(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python_version": platform.python_version(),
        },
        "git_candidate_audit": audit_summary,
        "native_wheel_check": native_res,
        "pure_python_fallback_check": pure_res,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_json = out_path.with_suffix(".json.tmp")
    tmp_json.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp_json, out_path)
    return report


def main() -> int:
    report = run_clean_build_verification()
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
