"""Plan or open a shared browser workspace using a dedicated, persistent profile."""

import argparse
import json
import os
from pathlib import Path
import subprocess
from urllib.parse import urlsplit


def launch_plan(browser: Path, profile: Path, urls: list[str]) -> list[list[str]]:
    if not browser.is_file():
        raise ValueError("Browser executable is unavailable")
    if not urls:
        raise ValueError("Provide at least one web application URL")
    commands = []
    for url in urls:
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password:
            raise ValueError("Use an HTTP(S) URL without embedded credentials")
        commands.append([str(browser), f"--user-data-dir={profile.resolve()}",
                         "--profile-directory=Default", "--no-first-run", f"--app={url}"])
    return commands


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("urls", nargs="+")
    parser.add_argument("--browser", type=Path, default=Path(os.environ.get("ProgramFiles(x86)", "")) /
                        "Microsoft/Edge/Application/msedge.exe")
    parser.add_argument("--profile", type=Path, default=Path(os.environ.get("LOCALAPPDATA", ".")) /
                        "Chimera/WorkspaceBrowser")
    parser.add_argument("--open", action="store_true", help="Open app windows for the proposed workspace")
    args = parser.parse_args()
    plan = launch_plan(args.browser, args.profile, args.urls)
    if args.open:
        args.profile.mkdir(parents=True, exist_ok=True)
        for command in plan:
            subprocess.Popen(command, close_fds=True)
    print(json.dumps({"opened": args.open, "profile": str(args.profile), "commands": plan}))


if __name__ == "__main__":
    main()
