"""Check receiver-side coalescing and recovery after suppressing a committed SSH reply."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import shlex
import subprocess
import tempfile
import threading
from unittest.mock import patch

from verify_guarded_build import ARTIFACT, BASE, CHANGED, COMMAND, ENV, PEER, counter, evidence, init_fixture, require
from chimera_tp.platform import build_queue, guarded_build


def run_trial(temp: Path, remote: str):
    source = temp / "working"
    source.mkdir()
    init_fixture(source, remote)
    barrier = threading.Barrier(2, timeout=8)

    def client(number):
        barrier.wait()
        return guarded_build.submit(COMMAND, cwd=source, peer=PEER, reuse=True, environment_id=ENV,
                                    artifacts=[ARTIFACT], state_dir=temp / f"client-{number}")

    with ThreadPoolExecutor(2) as callers:
        pending = [callers.submit(client, i) for i in range(2)]
        replies = [p.result(timeout=150) for p in pending]
    rows = [evidence("independent-client", reply, BASE) for reply in replies]
    require(rows[0]["instance"] == rows[1]["instance"] and rows[0]["attempt_id"] == rows[1]["attempt_id"],
            "independent_sender_outboxes_duplicated_work")
    require(len(counter("read", remote)) == 1, "receiver_did_not_coalesce")

    # This change forces a cache miss. The shell discards just this request's
    # stdout on the receiver after real execution; no system network is changed.
    (source / "package.py").write_bytes(CHANGED)
    native_run = subprocess.run
    injected = []
    def suppress_reply(argv, *args, **kwargs):
        if argv[0] == "ssh" and kwargs.get("input") and not injected:
            argv = list(argv)
            argv[-1] = shlex.join(["/bin/sh", "-c", argv[-1] + " >/dev/null && exit 81"])
            injected.append(True)
        return native_run(argv, *args, **kwargs)

    state = temp / "receiver-retry"
    with patch.object(subprocess, "run", side_effect=suppress_reply):
        lost = guarded_build.submit(COMMAND, cwd=source, peer=PEER, reuse=True, environment_id=ENV,
                                    artifacts=[ARTIFACT], state_dir=state)
    require(bool(injected) and lost["state"] == "indeterminate" and lost["queue"]["stored"],
            "missing_receipt_did_not_preserve_input")
    after_loss = counter("read", remote)
    require(len(after_loss) == 2, "lost_reply_build_did_not_finish")
    (source / "package.py").write_bytes(b"new_unsent_revision = True\n")
    # Recovery starts from the retained bytes while the workspace has moved on.
    recovered = guarded_build.retry_queued(lost["queue"]["id"], state_dir=state)
    recovered_row = evidence("outbox-retry", recovered, CHANGED)
    after_recovery = counter("read", remote)
    require(recovered_row["delivery"] == "cached" and len(after_recovery) == len(after_loss),
            "receipt_recovery_launched_another_build")
    require(recovered_row["instance"] in {m["instance"] for m in after_loss}, "wrong_recovered_attempt")
    require(not build_queue.list_pending(state), "recovered_input_still_queued")
    return {"ok": True, "peer": PEER, "independent_clients": 2, "executions_after_concurrent_submit": 1,
            "receiver_delivery": [r.get("receiver_delivery") for r in replies],
            "first_artifact_sha256": rows[0]["artifact_sha256"], "first_build_attempt": rows[0]["attempt_id"],
            "fault": "one SSH command completed, discarded stdout on the receiver and exited with code 81",
            "state_after_missing_receipt": lost["state"], "executions_after_lost_reply": len(after_loss),
            "executions_after_retry": len(after_recovery), "recovered": recovered_row,
            "restored_input_despite_subsequent_edit": True, "outbox_empty": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    remote = counter("start")["directory"]
    try:
        with tempfile.TemporaryDirectory(prefix="chimera-reply-test-") as temp:
            report = run_trial(Path(temp), remote)
    finally:
        counter("finish", remote)
    report["receiver_fixture_removed"] = True
    output = json.dumps(report, ensure_ascii=True, indent=2) + "\n"
    if args.out:
        args.out.write_text(output, encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
