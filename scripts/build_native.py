"""Build CHIMERA-HYPER native Silicon Core (Rust GFNI on Windows, C AVX2 on Linux)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def _build_windows(repo_root: Path) -> Path:
    crate_dir = repo_root / "native" / "chimera_core"
    target_dll = crate_dir / "target" / "release" / "chimera_core.dll"
    dest_dll = repo_root / "chimera_tp" / "_chimera_core.dll"

    proc = subprocess.run(["cargo", "build", "--release"], cwd=str(crate_dir), check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"cargo build --release failed with exit code {proc.returncode}")
    if not target_dll.exists():
        raise FileNotFoundError(f"Expected built DLL not found: {target_dll}")

    shutil.copy2(target_dll, dest_dll)
    print(f"Installed Windows Silicon Core -> {dest_dll} ({dest_dll.stat().st_size:,} bytes)")
    return dest_dll


def _build_posix(repo_root: Path) -> Path:
    src_c = repo_root / "native" / "chimera_core_c" / "chimera_core.c"
    dest_so = repo_root / "chimera_tp" / "_chimera_core.so"
    flags = ["-O3", "-std=c11", "-shared", "-fPIC", "-Wall", "-Wextra"]
    try:
        cpuinfo = Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="ignore")
        if "avx2" in cpuinfo:
            flags.append("-mavx2")
    except OSError:
        pass
    cmd = ["gcc", *flags, str(src_c), "-o", str(dest_so), "-lrt", "-lpthread"]
    proc = subprocess.run(cmd, cwd=str(repo_root), check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"gcc failed with exit code {proc.returncode}: {' '.join(cmd)}")
    print(f"Installed Linux Silicon Core -> {dest_so} ({dest_so.stat().st_size:,} bytes)")
    return dest_so


def build_native() -> Path:
    repo_root = Path(__file__).resolve().parents[1]
    if os.name == "nt":
        return _build_windows(repo_root)
    return _build_posix(repo_root)


if __name__ == "__main__":
    try:
        build_native()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
