"""Compare two source trees using the same native library and a fresh process for each run."""

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import shutil
import statistics
import subprocess
import sys
import tempfile


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def measure(tree, *, folder=None, profile=False):
    command = [sys.executable, "-I", "-B", "-S", "measure_daemon_working_set.py", "--root", tree]
    if profile:
        command.append("--profile")
    result = subprocess.run(command, cwd=folder, timeout=45, capture_output=True,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode:
        raise RuntimeError(result.stderr.decode("utf-8", errors="replace")[-1400:])
    return json.loads(result.stdout)


def trial_set():
    rows = []
    for pair in range(1, 4):
        order = ("before", "after") if pair % 2 else ("after", "before")
        for position, tree in enumerate(order, 1):
            result = measure(tree)
            if not result["native"] or not result["temporary_state_removed"]:
                raise RuntimeError("native_library_or_isolation_unverified")
            absent = ["chimera_tp.vsa_memory_service", "chimera_tp.platform.omega_entity",
                      "chimera_tp.platform.exile_handoff", "chimera_tp.platform.cosmos_entity"]
            if tree == "after":
                if result["vsa_db_before_first_query"] or not result["vsa_db_after_query"]:
                    raise RuntimeError("incorrect_vsa_database_lifecycle")
                if any(x in result["idle_modules"] for x in absent):
                    raise RuntimeError("unexpected_idle_modules:" + str(set(absent) & set(result["idle_modules"])))
                if not set(absent).issubset(result["after_optional_routes_modules"]):
                    raise RuntimeError("optional_route_did_not_load_its_engine")
            rows.append({"pair": pair, "position": position, "tree": tree, **result})
    summary = {}
    for name in ("before", "after"):
        group = [row for row in rows if row["tree"] == name]
        summary[name] = {
            "median_import_mib": statistics.median(row["package_import"]["rss_bytes"] for row in group) / 2**20,
            "median_idle_mib": statistics.median(statistics.median(row["idle_rss_bytes"]) for row in group) / 2**20,
            "max_observed_idle_mib": max(max(row["idle_rss_bytes"]) for row in group) / 2**20,
            "max_after_routes_mib": max(row["after_optional_routes_rss_bytes"] for row in group) / 2**20,
            "imported_at_idle": len(group[0]["idle_modules"]),
        }
    return {"host": platform.node(), "os": sys.platform, "python": sys.version.split()[0],
            "rows": rows, "summary": summary}


def stage(source, dest):
    for path in (source / "chimera_tp").rglob("*"):
        if path.is_symlink() or not path.is_file() or path.suffix not in (".py", ".html", ".js", ".css"):
            continue
        target = dest / path.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)


def stage_native(folder, names=("before", "after")):
    import sqlite3

    if not sys.platform.startswith("linux"):
        raise RuntimeError("expected_linux_receiver")
    root = Path.cwd()
    unit = "chimera-hyper-daemon.service"
    pid = int(subprocess.check_output(["systemctl", "--user", "show", unit, "-p", "MainPID", "--value"]))
    maps = Path(f"/proc/{pid}/maps").read_text().splitlines()
    mapped = {Path(line.split(maxsplit=5)[5]) for line in maps if line.endswith("/chimera_tp/_chimera_core.so")}
    if len(mapped) != 1:
        raise RuntimeError("no_exact_live_native_library")
    binary = mapped.pop()
    for name in names:
        shutil.copyfile(binary, folder / name / "chimera_tp" / binary.name)
    fields = {line.split(":")[0]: line.split()[1] for line in Path(f"/proc/{pid}/status").read_text().splitlines()
              if line.startswith(("VmHWM:", "VmRSS:", "Threads:"))}
    return {"daemon_pid": pid, "daemon_proc_status": fields, "rss_unit": "KiB", "sqlite": sqlite3.sqlite_version,
            "native_sha256": sha(binary), "working_directory": str(root)}


def snapshot_receipt(receipt):
    if not receipt.get("ok") or not receipt["admission"]["limits_verified"]:
        raise RuntimeError(json.dumps({k: receipt.get(k) for k in ("state", "error", "stderr", "ticket")}))
    blob = receipt["artifacts"]["linux.json"]
    data = base64.b64decode(blob["base64"], validate=True)
    if len(data) != blob["bytes"] or hashlib.sha256(data).hexdigest() != blob["sha256"]:
        raise ValueError("linux_result_mismatch")
    return json.loads(data)


def stage_profile(folder):
    rows = []
    for _ in range(3):
        trial = measure("after", folder=folder, profile=True)
        readings = trial["stages"]
        expected = ("dashboard_concurrent", "backup_shard_48mib_identity", "backup_shard_48mib_gzip",
                    "vsa_store_800", "vsa_bidirectional_800")
        if (not trial["native"] or not trial["temporary_state_removed"] or not trial["concurrent_http_status"]
                or tuple(r["stage"] for r in readings[-len(expected):]) != expected):
            raise RuntimeError("incomplete_isolated_profile")
        crossings = [r for r in readings if r["peak_bytes"] >= 80 * 1024**2]
        rows.append({"pid": trial["pid"], "python": trial["python"], "stages": readings,
                     "first_observed_at_or_above_80_mib": crossings[0]["stage"] if crossings else None})
    cli_file = folder / "cli-log.json"
    measured = subprocess.run(
        [sys.executable, "-I", "-B", "-S", "measure_daemon_cli.py", "--root", "after",
         "--vsa-rows", "6144", "--out", str(cli_file.resolve())],
        cwd=folder, capture_output=True, timeout=65, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if measured.returncode:
        raise RuntimeError("CLI workload failed: " + measured.stderr.decode("utf-8", "replace")[-1800:])
    cli = json.loads(cli_file.read_bytes())
    if (not cli["temp_removed"] or cli["persisted_vsa_rows"] != 6144
            or [s["stage"] for s in cli["stages"][-3:]] !=
               ["build_log_tail", "vsa_open_populated", "vsa_search_populated"]):
        raise RuntimeError("incomplete_cli_log_measurement")
    peak = max(r["peak_bytes"] for row in rows for r in row["stages"]) / 1024**2
    return {"host": platform.node(), "os": sys.platform, "runs": rows, "cli_log": cli,
            "max_kernel_peak_mib": max(peak, cli["peak_mib"])}


def profile_both_nodes(output, peer):
    repo = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo))
    from chimera_tp.platform.guarded_build import submit

    with tempfile.TemporaryDirectory(prefix="chimera-stage-peaks-") as name:
        sandbox = Path(name)
        stage(repo, sandbox / "after")
        source_hashes = {
            p.relative_to(sandbox / "after").as_posix(): sha(p)
            for p in sorted((sandbox / "after" / "chimera_tp").rglob("*")) if p.is_file()
        }
        for script in ("compare_daemon_working_sets.py", "measure_daemon_working_set.py", "measure_daemon_cli.py"):
            shutil.copyfile(repo / "scripts" / script, sandbox / script)
        policy = {"job_disk_mib": 192, "job_memory_mib": 384, "runtime_seconds": 165}
        receipt = submit("python3 -I -B -S compare_daemon_working_sets.py --guest-stages",
                         cwd=sandbox, peer=peer, sync=True, reuse=False, timeout_s=145,
                         admission_policy=policy, artifacts=["linux.json"])
        linux = snapshot_receipt(receipt)
        if linux["host"] != peer or not linux["os"].startswith("linux"):
            raise RuntimeError("peer_identity_mismatch")
        dll = repo / "chimera_tp/_chimera_core.dll"
        shutil.copyfile(dll, sandbox / "after" / "chimera_tp" / dll.name)
        windows = stage_profile(sandbox)
    record = {"schema": "chimera.daemon-stage-peaks/1",
              "measured_utc": datetime.now(timezone.utc).isoformat(),
              "scope": "Three fresh processes per OS with the same saved Python sources, native libraries, "
                       "private loopback ports and empty state for the staged runs. The independent CLI "
                       "starts with 6,144 persisted vectors, checks a build log, then opens and searches "
                       "the ledger. Kernel high-water marks are cumulative for each PID.",
              "windows": windows, "linux": linux, "windows_native_sha256": sha(dll),
              "source_sha256": source_hashes, "transport": receipt.get("ssh_route"),
              "worker_snapshot": receipt["snapshot"], "worker_attempt": receipt["attempt_id"],
              "limits_verified": receipt["admission"]["limits_verified"],
              "temporary_workspaces_removed": not sandbox.exists()}
    output.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({name: record[name]["max_kernel_peak_mib"] for name in ("windows", "linux")}))


def run(reference, output, peer):
    repo = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo))
    from chimera_tp.platform.guarded_build import submit

    with tempfile.TemporaryDirectory(prefix="chimera-rss-ab-") as name:
        sandbox = Path(name)
        for label, src in (("before", reference), ("after", repo)):
            stage(src, sandbox / label)
        for script in ("compare_daemon_working_sets.py", "measure_daemon_working_set.py"):
            shutil.copyfile(repo / "scripts" / script, sandbox / script)
        command = "python3 -I -B -S compare_daemon_working_sets.py --guest"
        policy = {"job_disk_mib": 192, "job_memory_mib": 384, "runtime_seconds": 165}
        receipt = submit(command, cwd=sandbox, peer=peer, sync=True, reuse=False, timeout_s=145,
                         admission_policy=policy, artifacts=["linux.json"])
        linux = snapshot_receipt(receipt)
        if linux["host"] != peer or not linux["os"].startswith("linux"):
            raise RuntimeError("peer_identity_mismatch")
        dll = repo / "chimera_tp/_chimera_core.dll"
        for label in ("before", "after"):
            shutil.copyfile(dll, sandbox / label / "chimera_tp" / dll.name)
        proc = subprocess.run([sys.executable, "-I", "-B", "-S", "compare_daemon_working_sets.py", "--windows"],
                              cwd=sandbox, capture_output=True, timeout=170,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if proc.returncode:
            raise RuntimeError(proc.stderr.decode(errors="replace")[-1400:])
        windows = json.loads(proc.stdout)
    record = {"schema": "chimera.daemon-lazy-ab/1", "completed_utc": datetime.now(timezone.utc).isoformat(),
              "scope": "Fresh isolated ports and state. Native library identical within each OS. "
                       "Five current-RSS samples per run, then real HTTP routes. Excludes sustained production load.",
              "win_native_sha256": sha(dll), "windows": windows, "linux": linux,
              "worker_attempt": receipt["attempt_id"], "worker_snapshot": receipt["snapshot"],
              "effective_guard": receipt["admission"]["effective_policy"], "temporary_worktree_removed": not sandbox.exists()}
    with output.open("x", encoding="utf-8") as stream:
        json.dump(record, stream, indent=2)
        stream.write("\n")
    print(json.dumps({name: record[name]["summary"] for name in ("windows", "linux")}))


if __name__ == "__main__":
    if sys.argv[1:] == ["--guest-stages"]:
        observed = stage_native(Path.cwd(), names=("after",))
        with Path("linux.json").open("x", encoding="utf-8") as stream:
            json.dump({**stage_profile(Path.cwd()), "live_daemon_observed": observed}, stream)
    elif sys.argv[1:] == ["--guest"]:
        live = stage_native(Path.cwd())
        with Path("linux.json").open("x", encoding="utf-8") as stream:
            json.dump({**trial_set(), "live_daemon_observed": live}, stream)
    elif sys.argv[1:] == ["--windows"]:
        print(json.dumps(trial_set()))
    else:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("--reference-root", type=Path)
        parser.add_argument("--stages", action="store_true", help="Measure the current daemon by startup and HTTP stage")
        parser.add_argument("--out", type=Path, required=True)
        parser.add_argument("--peer", default="svhome")
        args = parser.parse_args()
        if args.stages:
            profile_both_nodes(args.out, args.peer)
        elif args.reference_root:
            run(args.reference_root, args.out, args.peer)
        else:
            parser.error("--reference-root is required for the A/B comparison")
