"""Ultra-lightweight (<35ms, stdlib-only) SessionStart hook querying CHIMERA live bootstrap.

Usage (Antigravity / Claude Code SessionStart hook or CLI):
    python -m chimera_tp.platform.session_hook [repo_path]

Emits compact JSON (`<= 1,500 B`) with live multi-agent context (git state, active Hive-Mind
leases from sibling agents, verified BLAKE2s test receipts, Immune Reflex warnings, release-drift
radar, and latest Telepathy Capsule). Silently returns `{}` if the Chimera daemon is offline so
it never blocks or breaks any session startup.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path


def fetch_bootstrap(repo: str | None = None, *, anchor: str | None = None, timeout_s: float = 1.0) -> dict:
    base = (anchor or os.environ.get("CHIMERA_URL") or "http://127.0.0.1:9780").rstrip("/")
    target_repo = str(Path(repo or os.getcwd()).resolve())
    qs = urllib.parse.urlencode({"repo": target_repo, "agent_id": os.environ.get("CHIMERA_AGENT_ID") or "session-hook"})
    url = f"{base}/v1/agent/bootstrap?{qs}"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(url, timeout=max(0.2, float(timeout_s))) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    repo = args[0] if args else os.getcwd()
    snap = fetch_bootstrap(repo)
    if not snap or not snap.get("ok"):
        sys.stdout.write("{}\n")
        return 0
    # Emit clean compact hook payload
    sys.stdout.write(json.dumps(snap, separators=(",", ":"), ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
