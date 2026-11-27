"""100-trial fault-injection benchmark for CheckpointedExileCoordinator (Audit Breakthrough #1)."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import tempfile
import time
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from chimera_tp.host_governor import HostYieldGovernor
from chimera_tp.platform.cosmos_entity import ZeroEnvCasStore
from chimera_tp.platform.evidence import EvidenceLedger
from chimera_tp.platform.exile_handoff import (
    CheckpointedExileCoordinator,
    InMemoryWorkerTransport,
)
from chimera_tp.platform.immortal_jobs import ImmortalJobEngine
from chimera_tp.platform.pulse_bus import PulseBus
from scripts.exile_fault_cases import FAULT_POINTS, reference_output, trial_inputs



class _ActiveWorkstationGovernor(HostYieldGovernor):
    """HostYieldGovernor evaluating real controller rules under active Windows workstation input."""

    def evaluate_state(self, override_metrics: dict[str, Any] | None = None) -> dict[str, Any]:
        active = {"idle_sec": 4.5, "cpu_pct": 28.0, "free_ram_gb": 10.5, "total_ram_gb": 32.0}
        if override_metrics:
            active.update(override_metrics)
        return super().evaluate_state(override_metrics=active)


class _ClientReplyDroppedError(ConnectionResetError):
    """Raised post-commit to simulate a client reply drop after durable journal commit."""


class FaultInjectingWorkerTransport(InMemoryWorkerTransport):
    """Deterministic worker transport injecting realistic disconnect faults at exact pipeline phases."""

    def __init__(self) -> None:
        super().__init__()
        self._armed_faults: dict[str, dict[str, Any]] = {}
        self._active_job_id: str | None = None
        self.delayed_stale_receipts: dict[str, dict[str, Any]] = {}
        self.attempted_wire_bytes_by_job: dict[str, int] = {}

    def arm_fault(self, job_id: str, fault_point: str) -> None:
        self._armed_faults[job_id] = {"point": fault_point, "fired": False, "fault_ts": None}
        self._active_job_id = job_id

    def fault_timestamp(self, job_id: str) -> float | None:
        info = self._armed_faults.get(job_id)
        return info.get("fault_ts") if info else None

    def push_blocks(self, target_node: str, blocks: dict[str, bytes]) -> dict[str, Any]:
        jid = self._active_job_id
        if jid:
            self.attempted_wire_bytes_by_job[jid] = self.attempted_wire_bytes_by_job.get(jid, 0) + sum(len(v) for v in blocks.values())
        if jid and jid in self._armed_faults:
            info = self._armed_faults[jid]
            if info["point"] == "pre_receive" and not info["fired"]:
                info["fired"] = True
                info["fault_ts"] = time.perf_counter()
                raise ConnectionAbortedError(f"injected_fault:pre_receive:{jid}")
        return super().push_blocks(target_node, blocks)

    def execute_step(
        self,
        *,
        target_node: str,
        job_id: str,
        step_key: str,
        step_index: int,
        generation: int,
        op: str,
        params: dict[str, Any],
        block_manifest: list[dict[str, Any]],
        input_digest: str,
    ) -> dict[str, Any]:
        self._active_job_id = job_id
        info = self._armed_faults.get(job_id)
        if info and info["point"] == "post_receive_pre_compute" and not info["fired"]:
            info["fired"] = True
            info["fault_ts"] = time.perf_counter()
            raise ConnectionResetError(f"injected_fault:post_receive_pre_compute:{job_id}")

        res = super().execute_step(
            target_node=target_node,
            job_id=job_id,
            step_key=step_key,
            step_index=step_index,
            generation=generation,
            op=op,
            params=params,
            block_manifest=block_manifest,
            input_digest=input_digest,
        )

        if info and info["point"] == "post_compute_pre_ack" and not info["fired"]:
            info["fired"] = True
            info["fault_ts"] = time.perf_counter()
            self.delayed_stale_receipts[job_id] = {
                "receipt": dict(res["receipt"]),
                "result": res["result"],
                "step_index": step_index,
            }
            raise TimeoutError(f"injected_fault:post_compute_pre_ack:{job_id}")

        return res


def _percentile(sorted_vals: list[float], pct: float) -> float:
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return round(sorted_vals[0], 3)
    k = (len(sorted_vals) - 1) * (pct / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return round(sorted_vals[int(k)], 3)
    val = sorted_vals[f] * (c - k) + sorted_vals[c] * (k - f)
    return round(val, 3)


def run_fault_injection_benchmark(
    *,
    ops_dir: Path | None = None,
    output_path: Path | None = None,
    trials_per_fault: int = 25,
    transport_mode: str = "memory",
) -> dict[str, Any]:
    """Run 4xN fault-injection trials and verify zero data loss, generation fencing, and CAS delta efficiency."""
    if trials_per_fault < 1:
        raise ValueError("trials_per_fault must be positive")
    if transport_mode == "guarded-local":
        from scripts.exile_guard_fault_fixture import run_guarded_trials

        return run_guarded_trials(ops_dir, output_path, trials_per_fault)
    if transport_mode != "memory":
        raise ValueError(f"Unknown transport mode {transport_mode!r}")
    t_bench_start = time.perf_counter()
    tmp_ctx: tempfile.TemporaryDirectory[str] | None = None
    if ops_dir is None:
        tmp_ctx = tempfile.TemporaryDirectory()
        base_dir = Path(tmp_ctx.name) / "ops"
    else:
        base_dir = Path(ops_dir)
    base_dir.mkdir(parents=True, exist_ok=True)

    jobs: ImmortalJobEngine | None = None
    try:
        jobs = ImmortalJobEngine(base_dir / "immortal_jobs.db")
        cas = ZeroEnvCasStore(base_dir / "cas")
        pulse = PulseBus(node_name="win-desktop")
        governor = _ActiveWorkstationGovernor(role="controller", policy="work_first")
        evidence = EvidenceLedger(base_dir, persist=True)
        transport = FaultInjectingWorkerTransport()
        coord = CheckpointedExileCoordinator(
            jobs=jobs,
            cas=cas,
            pulse=pulse,
            governor=governor,
            evidence=evidence,
            node_name="win-desktop",
            worker_transport=transport,
            remote_target="svhome",
            max_retries=3,
        )

        fault_counts: dict[str, int] = {fp: 0 for fp in FAULT_POINTS}
        retrans_by_fault: dict[str, int] = {fp: 0 for fp in FAULT_POINTS}
        wire_by_fault: dict[str, int] = {fp: 0 for fp in FAULT_POINTS}
        resume_latencies_ms: list[float] = []
        end_to_end_latencies_ms: list[float] = []

        oracle_matches = 0
        lost_jobs = 0
        single_receipt_ok = 0
        stale_delivered = 0
        stale_rejected = 0
        win_yield_honored = 0
        post_commit_no_reexec = 0

        total_trials = trials_per_fault * len(FAULT_POINTS)
        for trial_idx in range(total_trials):
            fault_point = FAULT_POINTS[trial_idx % len(FAULT_POINTS)]
            fault_counts[fault_point] += 1
            job_id = f"exile-trial-{trial_idx:03d}"
            step_key = "compute_chunk"
            op, params, blocks = trial_inputs(trial_idx, fault_point)
            exp_in_digest, expected = reference_output(op, params, blocks)
            exp_out_digest = hashlib.sha256(expected).hexdigest()
            exp_out_cas = hashlib.blake2s(expected, digest_size=16).hexdigest()

            transport.arm_fault(job_id, fault_point)
            t_trial_0 = time.perf_counter()

            if fault_point == "post_commit_pre_client_reply":
                dropped_once = {"flag": False, "ts": None}

                def _drop_reply(_commit_res: dict[str, Any], _state: dict[str, Any] = dropped_once) -> None:
                    if not _state["flag"]:
                        _state["flag"] = True
                        _state["ts"] = time.perf_counter()
                        raise _ClientReplyDroppedError("injected_fault:post_commit_pre_client_reply")

                step_spec = {
                    "step_key": step_key,
                    "step_index": 0,
                    "blocks": blocks,
                    "op": op,
                    "params": params,
                    "post_commit_hook": _drop_reply,
                }
                try:
                    coord.handoff_job([step_spec], job_id=job_id, app="bench", name="fault_trial")
                except _ClientReplyDroppedError:
                    pass

                execs_before_resume = transport.exec_counts.get((job_id, step_key), 0)
                t_res_0 = dropped_once["ts"] or time.perf_counter()
                res = coord.handoff_job(
                    [{"step_key": step_key, "step_index": 0, "blocks": blocks, "op": op, "params": params}],
                    job_id=job_id,
                    app="bench",
                    name="fault_trial",
                )
                resume_ms = (time.perf_counter() - t_res_0) * 1000.0
                execs_after_resume = transport.exec_counts.get((job_id, step_key), 0)
                if execs_before_resume == 1 and execs_after_resume == 1:
                    post_commit_no_reexec += 1
            else:
                res = coord.handoff_job(
                    [{"step_key": step_key, "step_index": 0, "blocks": blocks, "op": op, "params": params}],
                    job_id=job_id,
                    app="bench",
                    name="fault_trial",
                )
                t_fault = transport.fault_timestamp(job_id) or t_trial_0
                resume_ms = (time.perf_counter() - t_fault) * 1000.0

            total_ms = (time.perf_counter() - t_trial_0) * 1000.0
            resume_latencies_ms.append(resume_ms)
            end_to_end_latencies_ms.append(total_ms)

            # Fault 3: deliver delayed stale generation-1 receipt AFTER gen-2 commit and confirm rejection
            if fault_point == "post_compute_pre_ack" and job_id in transport.delayed_stale_receipts:
                stale_delivered += 1
                delayed = transport.delayed_stale_receipts[job_id]
                rej = coord.submit_receipt(
                    delayed["receipt"],
                    result=delayed["result"],
                    step_index=delayed["step_index"],
                )
                if (not rej.get("ok")) and rej.get("rejected") and rej.get("reason") == "stale_generation":
                    stale_rejected += 1

            step_out = (res.get("steps") or [{}])[0]
            receipts = jobs.get_receipts(job_id=job_id, limit=10)
            if len(receipts) == 1:
                single_receipt_ok += 1

            if (not res.get("ok")) or (res.get("job_status") != "completed"):
                lost_jobs += 1

            if (
                len(receipts) == 1
                and receipts[0]["input_digest"] == exp_in_digest
                and receipts[0]["output_digest"] == exp_out_digest
                and receipts[0]["output_cas_hash"] == exp_out_cas
                and step_out.get("output_digest") == exp_out_digest
            ):
                oracle_matches += 1

            if step_out.get("win_cpu_yielded") and (step_out.get("target_node") == "svhome"):
                win_yield_honored += 1

            retrans_by_fault[fault_point] += int(res.get("retransmitted_bytes") or 0)
            wire_by_fault[fault_point] += int(transport.attempted_wire_bytes_by_job.get(job_id, res.get("wire_bytes") or 0))

        sorted_res = sorted(resume_latencies_ms)
        sorted_e2e = sorted(end_to_end_latencies_ms)
        j_stats = jobs.stats()
        coord_status = coord.status()
        ev_snap = evidence.snapshot({"immortal_jobs": True, "exile": True})

        report = {
            "ok": (
                oracle_matches == total_trials
                and lost_jobs == 0
                and single_receipt_ok == total_trials
                and stale_rejected == trials_per_fault
                and win_yield_honored == total_trials
                and post_commit_no_reexec == trials_per_fault
            ),
            "total_trials": total_trials,
            "trials_per_fault": trials_per_fault,
            "fault_counts": fault_counts,
            "oracle_digest_matches": oracle_matches,
            "lost_accepted_jobs": lost_jobs,
            "single_committed_receipt_per_step": single_receipt_ok,
            "delayed_stale_receipts_delivered": stale_delivered,
            "delayed_stale_receipts_rejected": stale_rejected,
            "post_commit_idempotent_no_reexec": post_commit_no_reexec,
            "win_cpu_yield_honored_count": win_yield_honored,
            "resume_latency_ms": {
                "p50": _percentile(sorted_res, 50.0),
                "p95": _percentile(sorted_res, 95.0),
                "p99": _percentile(sorted_res, 99.0),
                "min": round(min(sorted_res), 3) if sorted_res else 0.0,
                "max": round(max(sorted_res), 3) if sorted_res else 0.0,
                "mean": round(sum(sorted_res) / max(1, len(sorted_res)), 3),
            },
            "total_trial_latency_ms": {
                "p50": _percentile(sorted_e2e, 50.0),
                "p95": _percentile(sorted_e2e, 95.0),
                "p99": _percentile(sorted_e2e, 99.0),
            },
            "wire_bytes_total": sum(wire_by_fault.values()),
            "wire_bytes_by_fault": wire_by_fault,
            "retransmitted_bytes": {
                "total": sum(retrans_by_fault.values()),
                "by_fault": retrans_by_fault,
            },
            "cas_stats": cas.stats(),
            "jobs_stats": j_stats,
            "coordinator_status": coord_status,
            "evidence_snapshot": ev_snap,
            "elapsed_total_s": round(time.perf_counter() - t_bench_start, 3),
        }

        if output_path is not None:
            out_p = Path(output_path)
            out_p.parent.mkdir(parents=True, exist_ok=True)
            out_p.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        return report
    finally:
        if jobs is not None:
            jobs.close()
        if tmp_ctx is not None:
            tmp_ctx.cleanup()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transport", choices=("memory", "guarded-local"), default="memory")
    parser.add_argument("--trials-per-fault", type=int, default=25)
    parser.add_argument("--output", type=Path)
    options = parser.parse_args()
    filename = ("exile_guard_fault_trials.json" if options.transport == "guarded-local"
                else "exile_handoff_100_trials.json")
    out_file = options.output or REPO_ROOT / "tasks" / filename
    report = run_fault_injection_benchmark(
        output_path=out_file, trials_per_fault=options.trials_per_fault, transport_mode=options.transport
    )
    print(json.dumps({key: value for key, value in report.items() if key != "trials"},
                     indent=2, ensure_ascii=False))
    if not report["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
