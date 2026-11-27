"""Check a serving daemon memory report against its rollout and completed journal records."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys


DAY = 86400
BUDGET = 80 * 1024 ** 2
NODES = {"win-desktop", "svhome"}


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def utc(value):
    stamp = datetime.fromisoformat(value)
    require(stamp.utcoffset() is not None, "timestamp_without_offset")
    return stamp.astimezone(timezone.utc)


def check(path, rollout_path, *, now=None):
    report = json.loads(path.read_bytes())
    require(report["schema"] == "chimera.live-daemon-soak/1", "unknown_report_schema")
    require(report["journal"] == path.with_suffix(".jsonl").name, "unexpected_journal_name")
    require(report["required_seconds"] == DAY and report["exclusive_limit_bytes"] == BUDGET,
            "observation_policy_changed")
    require(report.get("source_check_interval_seconds") == 3600, "hourly_source_checks_required")
    state = report["state"]
    require(state in ("running", "failed", "passed"), "unknown_collector_state")
    interval = report["interval_seconds"]
    require(type(interval) is int and 15 <= interval <= 300, "invalid_sampling_interval")
    require(set(report["expected_pids"]) == NODES and set(report["maximum_bytes"]) <= NODES,
            "incorrect_node_set")
    if rollout_path is None:
        name = report.get("rollout_receipt")
        require(name and Path(name).name == name, "rollout_receipt_required")
        rollout_path = path.parent / name
    raw = rollout_path.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == report["rollout_sha256"], "rollout_digest_changed")
    rollout = json.loads(raw)
    require(rollout["schema"] == "chimera.workstation-rollout/1" and rollout["release"] == report["release"],
            "rollout_release_mismatch")
    deadline = 2 * interval + 20
    last_good = first_good = last_check = prior_stamp = None
    peaks, identity = {}, {}
    samples = source_checks = missed = 0
    last_error = None
    with path.with_suffix(".jsonl").open("rb") as stream:
        for line in stream:
            row = json.loads(line)
            stamp = utc(row["utc"])
            require(prior_stamp is None or stamp > prior_stamp, "journal_clock_out_of_order")
            prior_stamp = stamp
            last_error = row.get("error")
            terminal_failure = state == "failed" and row["utc"] == report["updated_utc"]
            if last_error and not terminal_failure:
                missed += 1
            if "nodes" in row and not terminal_failure:
                nodes = row["nodes"]
                require(set(nodes) == NODES, "missing_node_sample")
                require(last_good is None or (stamp - last_good).total_seconds() <= deadline + 1,
                        "observation_gap_in_journal")
                for name in NODES:
                    node = nodes[name]
                    observed = (node["pid"], node["started_at"])
                    require(node["pid"] == report["expected_pids"][name]
                            and identity.setdefault(name, observed) == observed, "process_identity_changed")
                    if not report.get("new_window_after_restart"):
                        expected = rollout["nodes"][name]
                        require(observed == (expected["pid"], expected["started_at"]), "unexpected_rollout_pid")
                    require(node["version"] == rollout["live"][name]["version"], "node_version_changed")
                    peak, rss = node["peak_bytes"], node["rss_bytes"]
                    require(type(rss) is int and type(peak) is int and 0 < rss <= peak < BUDGET
                            and peak >= peaks.get(name, 0), "invalid_kernel_peak")
                    peaks[name] = peak
                # The writer counts a valid kernel reading even if the source hash probe then times out.
                samples += 1
                if not last_error:
                    if last_check is not None:
                        require((stamp - last_check).total_seconds() <= 3600 + deadline + 1,
                                "hourly_source_check_missing")
                    if row.get("release_sources_verified") is True:
                        source_checks += 1
                        last_check = stamp
                    require(last_check is not None, "no_source_attestation")
                    first_good = first_good or stamp
                    last_good = stamp
            else:
                require(last_error, "missing_sample_or_error")
            if row["utc"] == report["updated_utc"]:
                break
        else:
            raise ValueError("journal_does_not_reach_report")
    require(source_checks == report["source_checks"], "source_check_count_mismatch")
    result = {
        "release": report["release"], "state": state, "samples": report["samples"],
        "source_checks": source_checks, "missed": report["missed"], "observed_seconds": report["observed_seconds"],
        "peak_mib": {k: round(v / 1024 ** 2, 2) for k, v in report["maximum_bytes"].items()},
        "last_observation_utc": report["updated_utc"], "required_seconds": DAY,
    }
    if state == "failed":
        reason = report.get("reason")
        since_last_good = (prior_stamp - (last_good or utc(report["started_utc"]))).total_seconds()
        require(last_error and (last_error == reason or (reason == "observation_gap" and since_last_good >= deadline - 1)),
                "failure_reason_not_in_journal")
        if reason == "kernel_peak_reached_budget":
            terminal_peaks = {name: row["nodes"][name]["peak_bytes"] for name in NODES}
            require(terminal_peaks == report["maximum_bytes"] and max(terminal_peaks.values()) >= BUDGET,
                    "budget_failure_not_in_journal")
        return {**result, "reason": reason}
    require(samples == report["samples"] and peaks == report["maximum_bytes"] and missed == report["missed"],
            "journal_and_report_disagree")
    if last_good is None:
        require(state == "running" and last_error, "no_valid_samples")
        age = ((now or datetime.now(timezone.utc)) - utc(report["started_utc"])).total_seconds()
        return {**result, "state": "awaiting_first_sample" if 0 <= age <= deadline else "stale"}
    span = (last_good - first_good).total_seconds()
    # UTC stamps precede network sampling; elapsed_seconds is the writer's monotonic interval after sampling.
    require(abs(span - report["observed_seconds"]) <= deadline, "elapsed_time_disagreement")
    if state == "passed":
        # UTC is logged before fetching the two counters. A fractional second of acquisition jitter
        # is possible even though the writer measures a full day with its monotonic clock.
        require(not last_error and last_check == last_good and report["observed_seconds"] >= DAY
                and span >= DAY - 1, "incomplete_final_attestation")
    else:
        age = ((now or datetime.now(timezone.utc)) - last_good).total_seconds()
        if age > deadline or age < -1:
            return {**result, "state": "stale", "reason": "no_recent_successful_sample"}
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--rollout", type=Path)
    args = parser.parse_args()
    try:
        result = check(args.report, args.rollout)
    except (KeyError, OSError, ValueError, TypeError) as exc:
        print(json.dumps({"state": "unverified", "reason": str(exc)}))
        sys.exit(2)
    print(json.dumps(result, indent=2))
    sys.exit({"passed": 0, "running": 1, "awaiting_first_sample": 1}.get(result["state"], 2))
