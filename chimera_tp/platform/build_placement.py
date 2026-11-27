"""Pair verified builds on the two machines and select the lower observed wall time."""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
import statistics
import tempfile
import time
import uuid

from . import build_snapshot, guarded_build
from .agent_workspace import LeaseBusy, _lock


SCHEMA = "chimera.build-placement/1"


def _runtime():
    from . import build_registry, build_worker, local_build, peer_guard, windows_build_job, work_admission

    modules = (build_snapshot, guarded_build, local_build, windows_build_job, build_worker,
               build_registry, peer_guard, work_admission)
    return build_snapshot.sha(build_snapshot.canonical(
        {module.__name__: build_snapshot.sha(Path(module.__file__).read_bytes()) for module in modules}))


def _combination(repo, windows_cmd, linux_cmd, peer, environment_id, artifacts, timeout):
    if not (isinstance(windows_cmd, str) and windows_cmd.strip() and isinstance(linux_cmd, str)
            and linux_cmd.strip() and isinstance(environment_id, str) and environment_id.strip()):
        raise ValueError("both_platform_commands_and_dependency_identifier_required")
    if not isinstance(artifacts, (list, tuple)) or not 1 <= len(artifacts) <= 32:
        raise ValueError("declare_between_one_and_32_output_files")
    names = sorted({build_snapshot.portable_path(n) for n in artifacts})
    if not names or not 1 <= timeout <= 300:
        raise ValueError("declare_at_least_one_artifact_and_a_1_to_300_second_timeout")
    full = Path(repo).resolve(strict=True)
    return {"repo": os.path.normcase(str(full)), "windows_cmd": windows_cmd, "linux_cmd": linux_cmd,
            "peer": peer, "environment_id": environment_id, "artifacts": names, "timeout": timeout}


def _store(profile_path, report):
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    # Never expose a half-written report. Temporary names are unique for concurrent runs.
    fd, name = tempfile.mkstemp(prefix=".placement-", suffix=".tmp", dir=profile_path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2, ensure_ascii=False, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, profile_path)
    finally:
        Path(name).unlink(missing_ok=True)


def _artifacts(receipt, names):
    items = receipt.get("artifacts") or {}
    if set(items) != set(names):
        raise ValueError("build_artifact_set_changed")
    return {name: [items[name]["sha256"], items[name]["bytes"]] for name in names}


def _submit(spec, site, digest, *, calibration, ssh_route=None):
    return guarded_build.submit(
        spec["windows_cmd" if site == "local" else "linux_cmd"], peer=spec["peer"], target=site,
        cwd=spec["repo"], environment_id=spec["environment_id"], reuse=not calibration,
        artifacts=spec["artifacts"], timeout_s=spec["timeout"], expected_snapshot=digest,
        expected_ssh_route=ssh_route if site == "svhome" else None,
    )


def _choose(rows, expected_pairs):
    if type(expected_pairs) is not int or not 5 <= expected_pairs <= 30 or len(rows) != 2 * expected_pairs:
        raise ValueError("incomplete_paired_observations")
    ratios = []
    elapsed = {"local": [], "svhome": []}
    digests = set()
    attempts = set()
    peer_routes = set()
    for i in range(expected_pairs):
        pair = rows[2 * i:2 * i + 2]
        order = ["local", "svhome"] if i % 2 == 0 else ["svhome", "local"]
        if [r["site"] for r in pair] != order:
            raise ValueError("placement_order_mismatch")
        for entry in pair:
            value = entry["wall_ms"]
            if (entry["pair"] != i + 1 or entry["state"] != "completed" or
                    entry["delivery"] != "executed" or type(value) not in (int, float)
                    or not math.isfinite(value) or value <= 0):
                raise ValueError("invalid_placement_observation")
            attempt = entry.get("attempt_id")
            if not isinstance(attempt, str) or not attempt or attempt in attempts:
                raise ValueError("missing_or_repeated_attempt")
            attempts.add(attempt)
            if entry["site"] == "svhome":
                peer_routes.add(entry.get("ssh_route"))
            elapsed[entry["site"]].append(value)
            digests.add(build_snapshot.sha(build_snapshot.canonical(entry["artifacts"])))
        ratios.append(elapsed["svhome"][-1] / elapsed["local"][-1])
    if len(digests) != 1:
        raise ValueError("platform_outputs_differ")
    ratio = statistics.median(ratios)
    if len(peer_routes) != 1 or not peer_routes <= (guarded_build.SSH_ROUTES | {None}):
        raise ValueError("inconsistent_placement_ssh_routes")
    route = peer_routes.pop()
    return {**({"ssh_route": route} if route is not None else {}),
            "selected": "svhome" if ratio < 1 else "local", "median_paired_peer_to_local": ratio,
            "median_ms": {s: statistics.median(times) for s, times in elapsed.items()},
            "peer_faster_pairs": sum(v < 1 for v in ratios), "pairs": expected_pairs,
            "paired_ratio_range": [min(ratios), max(ratios)]}


def measure(profile_path, repo, windows_cmd, linux_cmd, peer, environment_id, artifacts, timeout, *, pairs=5):
    if not 5 <= pairs <= 30 or type(pairs) is not int:
        raise ValueError("pairs_must_be_5_to_30")
    spec = _combination(repo, windows_cmd, linux_cmd, peer, environment_id, artifacts, timeout)
    source = build_snapshot.capture(Path(repo), include_data=False)
    root = Path(repo).resolve()
    for _ in Path(source["cwd"]).parts:
        root = root.parent
    output = Path(profile_path).resolve()
    if output.is_relative_to(root):
        raise ValueError("save_the_changing_profile_outside_the_measured_workspace")
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with _lock(output.with_name(output.name + ".lock")):
            return _measure_locked(output, spec, source["digest"], pairs)
    except LeaseBusy:
        return {"state": "incomplete", "reason": "measurement_already_running_for_profile"}


def _measure_locked(output, spec, digest, pairs):
    data = {"schema": SCHEMA, "profile_id": uuid.uuid4().hex, "created_at": time.time(),
            "spec": spec, "snapshot": digest, "runtime_sha256": _runtime(),
            "pairs_requested": pairs, "trials": [],
            "state": "measuring", "scope": "Sequential uncached attempts. CPU child accounting and wall time "
            "are separate. The comparison does not measure CAD frames or mixed project revisions."}
    _store(output, data)
    expected_outputs = None
    measured_route = None
    for index in range(pairs):
        order = ("local", "svhome") if index % 2 == 0 else ("svhome", "local")
        for site in order:
            begin = time.monotonic()
            reply = _submit(spec, site, data["snapshot"], calibration=True, ssh_route=measured_route)
            row = {"pair": index + 1, "site": site, "wall_ms": (time.monotonic() - begin) * 1000,
                   "state": reply.get("state"), "delivery": reply.get("delivery"),
                   "attempt_id": reply.get("attempt_id")}
            data["trials"].append(row)
            if not reply.get("ok"):
                row["error"] = reply.get("error", "no_successful_receipt")
                data.update(state="incomplete", reason=row["error"])
                _store(output, data)
                return data
            if site == "svhome":
                route = reply.get("ssh_route")
                if route not in guarded_build.SSH_ROUTES or (measured_route is not None and route != measured_route):
                    data.update(state="incomplete", reason="placement_ssh_route_unverified")
                    _store(output, data)
                    return data
                measured_route = row["ssh_route"] = route
            row["artifacts"] = _artifacts(reply, spec["artifacts"])
            for field in ("client_timing_ms", "attempt_timing_ms", "ssh_exchange_ms", "ssh_request_bytes",
                          "reaped_child_cpu_ms", "process_wall_ms"):
                if field in reply:
                    row[field] = reply[field]
            if (reply["snapshot"] != digest or row["delivery"] != "executed" or
                    (expected_outputs is not None and expected_outputs != row["artifacts"])):
                data.update(state="incomplete", reason="workload_or_outputs_differ")
                _store(output, data)
                return data
            expected_outputs = row["artifacts"]
            _store(output, data)
    data.update(state="measured", completed_at=time.time(), comparison=_choose(data["trials"], pairs))
    _store(output, data)
    return data


def use(profile_path, environment_id, *, execute=False, max_age_s=86400):
    if not math.isfinite(max_age_s) or max_age_s <= 0:
        raise ValueError("invalid_profile_lifetime")
    path = Path(profile_path)
    if path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError("oversized_placement_profile")
    data = json.loads(path.read_text(encoding="utf-8"))
    refused = {"ok": False, "state": "deferred"}
    if data.get("schema") != SCHEMA or data.get("state") != "measured":
        return {**refused, "error": "no_complete_placement_measurement"}
    spec = _combination(**data["spec"])
    age = time.time() - data["completed_at"]
    if not 0 <= age <= max_age_s or spec["environment_id"] != environment_id or _runtime() != data["runtime_sha256"]:
        return {**refused, "error": "placement_profile_or_environment_changed"}
    comparison = _choose(data["trials"], data["pairs_requested"])
    if comparison != data["comparison"]:
        raise ValueError("placement_summary_differs_from_trials")
    if build_snapshot.capture(Path(spec["repo"]), include_data=False)["digest"] != data["snapshot"]:
        return {**refused, "error": "placement_inputs_changed"}
    site = comparison["selected"]
    if not execute:
        return {"ok": True, "state": "planned", "placement": comparison, "snapshot": data["snapshot"]}
    route = comparison.get("ssh_route")
    if site == "svhome" and route is None:
        return {**refused, "error": "placement_ssh_route_unmeasured", "placement": comparison}
    receipt = _submit(spec, site, data["snapshot"], calibration=False, ssh_route=route)
    expected_outputs = data["trials"][0]["artifacts"]
    if receipt.get("ok") and _artifacts(receipt, spec["artifacts"]) != expected_outputs:
        return {"ok": False, "state": "failed", "error": "build_differs_from_measured_artifacts",
                "placement": comparison, "attempt_id": receipt.get("attempt_id")}
    return {**receipt, "placement": comparison, "profile_id": data["profile_id"]}


def configure(parser):
    actions = parser.add_subparsers(dest="placement_action", required=True)
    check = actions.add_parser("measure", help="Run paired independent builds with declared, repeatable outputs")
    check.add_argument("--cwd", type=Path, required=True)
    check.add_argument("--windows-cmd", required=True)
    check.add_argument("--linux-cmd", required=True)
    check.add_argument("--artifact", action="append", required=True)
    check.add_argument("--pairs", type=int, default=5)
    check.add_argument("--timeout", type=int, default=120)
    check.add_argument("--peer", default="svhome")
    plan = actions.add_parser("plan", help="Check whether measured placement still applies")
    run = actions.add_parser("run", help="Run this profile's recorded command on the measured target")
    for action in (check, plan, run):
        action.add_argument("--profile", required=True, type=Path)
        action.add_argument("--env", required=True, help="Pinned toolchain and external dependencies")
        if action is not check:
            action.add_argument("--max-age", type=float, default=86400,
                                help="Maximum accepted profile age, in seconds (default 86400)")


def cli(args):
    try:
        if args.placement_action == "measure":
            row = measure(args.profile, args.cwd, args.windows_cmd, args.linux_cmd, args.peer, args.env,
                          args.artifact, args.timeout, pairs=args.pairs)
            output = {"ok": row["state"] == "measured", "state": row["state"], "profile": str(args.profile),
                      "comparison": row.get("comparison"), "reason": row.get("reason")}
        else:
            output = use(args.profile, args.env, execute=args.placement_action == "run", max_age_s=args.max_age)
    except (KeyError, TypeError, ValueError, OSError) as exc:
        output = {"ok": False, "state": "rejected", "error": str(exc)}
    print(json.dumps(output, indent=2, ensure_ascii=True))
    return 0 if output["ok"] else (75 if output["state"] in {"deferred", "incomplete"} else 1)
