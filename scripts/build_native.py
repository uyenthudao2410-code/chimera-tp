"""Build CHIMERA-HYPER native Rust Silicon Core and install into chimera_tp/_chimera_core.dll."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


def build_native() -> Path:
    repo_root = Path(__file__).resolve().parents[1]
    crate_dir = repo_root / "native" / "chimera_core"
    target_dll = crate_dir / "target" / "release" / "chimera_core.dll"
    dest_dll = repo_root / "chimera_tp" / "_chimera_core.dll"

    proc = subprocess.run(
        ["cargo", "build", "--release"],
        cwd=str(crate_dir),
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"cargo build --release failed with exit code {proc.returncode}")
    if not target_dll.exists():
        raise FileNotFoundError(f"Expected built DLL not found: {target_dll}")

    shutil.copy2(target_dll, dest_dll)
    print(f"Installed native Silicon Core -> {dest_dll} ({dest_dll.stat().st_size:,} bytes)")
    return dest_dll


if __name__ == "__main__":
    try:
        build_native()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
