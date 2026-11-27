"""Compare every regular file in a read-only project tree with its staged copy."""

import argparse
import hashlib
import json
import os
from pathlib import Path


def inventory(root: Path) -> tuple[dict[str, tuple[int, str]], list[str]]:
    files = {}
    failures = []
    stack = [root]
    while stack:
        directory = stack.pop()
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    path = Path(entry.path)
                    relative = path.relative_to(root).as_posix()
                    try:
                        before = entry.stat(follow_symlinks=False)
                        if getattr(before, "st_file_attributes", 0) & 0x400 or entry.is_symlink():
                            failures.append(relative + " (link/reparse point)")
                        elif entry.is_dir(follow_symlinks=False):
                            stack.append(path)
                        elif entry.is_file(follow_symlinks=False):
                            with path.open("rb") as stream:
                                digest = hashlib.file_digest(stream, "sha256").hexdigest()
                            after = path.stat()
                            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                                failures.append(relative + " (changed during read)")
                            else:
                                files[relative] = (after.st_size, digest)
                    except OSError as exc:
                        failures.append(f"{relative} ({exc.__class__.__name__})")
        except OSError as exc:
            failures.append(f"{directory.relative_to(root)} ({exc.__class__.__name__})")
    return files, failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("staged", type=Path)
    args = parser.parse_args()
    source = args.source.resolve(strict=True)
    staged = args.staged.resolve(strict=True)
    if source == staged or source in staged.parents or staged in source.parents:
        parser.error("expected independent directories")
    original, errors_a = inventory(source)
    copy, errors_b = inventory(staged)
    missing = sorted(original.keys() - copy.keys())
    extra = sorted(copy.keys() - original.keys())
    different = sorted(path for path in original.keys() & copy.keys() if original[path] != copy[path])
    ok = not any((missing, extra, different, errors_a, errors_b))
    print(json.dumps({
        "ok": ok, "source": str(source), "staged": str(staged),
        "files": len(original), "staged_files": len(copy),
        "bytes": sum(size for size, digest in original.values()),
        "missing": missing[:20], "extra": extra[:20], "different": different[:20],
        "source_errors": errors_a[:20], "stage_errors": errors_b[:20],
    }))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
