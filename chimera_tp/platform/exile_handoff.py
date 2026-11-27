"""CHIMERA-EXILE-HANDOFF: Checkpointed, Generation-Fenced Remote Handoff Coordinator.

Unifies ZeroEnvCasStore delta transfers, ImmortalJobEngine generation-fenced leases & single-commit
receipts, PulseBus wakeup events, HostYieldGovernor preemption checks, AgentExileEngine SSH offload,
and EvidenceLedger freshness receipts.
"""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import threading
import time
from typing import Any, Callable

from .cosmos_entity import ZeroEnvCasStore
from .evidence import EvidenceLedger
from .guarded_cas import GuardedCasFailure, compute_step_input_digest, execute_deterministic_cas_op
from .immortal_jobs import ImmortalJobEngine


def chunk_step_inputs(
    *,
    payload: bytes | bytearray | str | dict[str, Any] | list[Any] | None = None,
    blocks: dict[str, bytes] | list[bytes] | None = None,
    block_size: int = 4096,
) -> list[tuple[str, bytes]]:
    """Convert step payload or explicit blocks into deterministic ordered (rel_path, bytes) chunks."""
    if blocks is not None:
        if isinstance(blocks, dict):
            return [(str(k).replace("\\", "/"), bytes(v)) for k, v in sorted(blocks.items(), key=lambda kv: str(kv[0]))]
        return [(f"block_{idx:04d}.bin", bytes(chunk)) for idx, chunk in enumerate(blocks)]

    if payload is None:
        raw = b""
    elif isinstance(payload, (bytes, bytearray)):
        raw = bytes(payload)
    elif isinstance(payload, str):
        raw = payload.encode("utf-8")
    else:
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

    if not raw:
        return [("block_0000.bin", b"")]
    bs = max(256, int(block_size))
    return [
        (f"block_{idx:04d}.bin", raw[off : off + bs])
        for idx, off in enumerate(range(0, len(raw), bs))
    ]


class InMemoryWorkerTransport:
    """In-process remote-CAS worker transport executing deterministically with delta block tracking."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._node_cas: dict[str, dict[str, bytes]] = {}
        self.exec_counts: dict[tuple[str, str], int] = {}

    def _node_store(self, target_node: str) -> dict[str, bytes]:
        with self._lock:
            return self._node_cas.setdefault(str(target_node), {})

    def query_missing_blocks(self, target_node: str, digests: list[str]) -> list[str]:
        store = self._node_store(target_node)
        with self._lock:
            return [d for d in digests if d not in store]

    def push_blocks(self, target_node: str, blocks: dict[str, bytes]) -> dict[str, Any]:
        store = self._node_store(target_node)
        pushed = 0
        wire = 0
        with self._lock:
            for d, data in blocks.items():
                raw = bytes(data)
                if d not in store:
                    store[d] = raw
                    pushed += 1
                wire += len(raw)
        return {"ok": True, "blocks_pushed": pushed, "wire_bytes": wire}

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
        store = self._node_store(target_node)

        def _read_block(digest: str) -> bytes:
            with self._lock:
                if digest not in store:
                    raise KeyError(f"missing_remote_cas_block:{digest}")
                return store[digest]

        out_bytes, result, out_digest, out_cas = execute_deterministic_cas_op(
            op, params, block_manifest, _read_block
        )
        with self._lock:
            store[out_cas] = out_bytes
            key = (str(job_id), str(step_key))
            self.exec_counts[key] = self.exec_counts.get(key, 0) + 1

        receipt = {
            "job_id": str(job_id),
            "step_key": str(step_key),
            "generation": int(generation),
            "node_id": str(target_node),
            "input_digest": str(input_digest),
            "output_digest": out_digest,
            "output_cas_hash": out_cas,
        }
        return {
            "ok": True,
            "node_id": str(target_node),
            "output_bytes": out_bytes,
            "result": result,
            "output_digest": out_digest,
            "output_cas_hash": out_cas,
            "receipt": receipt,
        }


class _LocalCasFallbackTransport:
    """Fallback transport reading blocks directly from local ZeroEnvCasStore when remote transport is absent."""

    def __init__(self, cas: ZeroEnvCasStore, node_name: str) -> None:
        self.cas = cas
        self.node_name = node_name

    def query_missing_blocks(self, target_node: str, digests: list[str]) -> list[str]:
        return []

    def push_blocks(self, target_node: str, blocks: dict[str, bytes]) -> dict[str, Any]:
        return {"ok": True, "blocks_pushed": 0, "wire_bytes": 0}

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
        def _read_local(digest: str) -> bytes:
            obj_p = self.cas.objects_dir / digest[:2] / digest
            return obj_p.read_bytes()

        out_bytes, result, out_digest, out_cas = execute_deterministic_cas_op(
            op, params, block_manifest, _read_local
        )
        receipt = {
            "job_id": str(job_id),
            "step_key": str(step_key),
            "generation": int(generation),
            "node_id": self.node_name,
            "input_digest": str(input_digest),
            "output_digest": out_digest,
            "output_cas_hash": out_cas,
        }
        return {
            "ok": True,
            "node_id": self.node_name,
            "output_bytes": out_bytes,
            "result": result,
            "output_digest": out_digest,
            "output_cas_hash": out_cas,
            "receipt": receipt,
        }


class _GuardedCasTransport:
    """Adapt the coordinator to the shared guarded worker. Only the local journal commits steps."""

    def __init__(self, exile: Any, remote_cas_dir: str = "~/.chimera/exile_cas") -> None:
        self.exile = exile
        self.remote_cas_dir = remote_cas_dir

    def query_missing_blocks(self, target_node: str, digests: list[str]) -> list[str]:
        res = self.exile.query_remote_cas_missing(digests, remote_cas_dir=self.remote_cas_dir)
        return list(res.get("missing") or [])

    def push_blocks(self, target_node: str, blocks: dict[str, bytes]) -> dict[str, Any]:
        return self.exile.push_remote_cas_blocks(blocks, remote_cas_dir=self.remote_cas_dir)

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
        return self.exile.run_cas_step(
            job_id=job_id,
            step_key=step_key,
            generation=generation,
            op=op,
            params=params,
            block_manifest=block_manifest,
            input_digest=input_digest,
            remote_cas_dir=self.remote_cas_dir,
        )


class CheckpointedExileCoordinator:
    """Orchestrates checkpointed, generation-fenced job handoff across CAS, Journal, Pulse, Governor & Evidence."""

    def __init__(
        self,
        jobs: ImmortalJobEngine,
        cas: ZeroEnvCasStore,
        pulse: Any = None,
        governor: Any = None,
        exile: Any = None,
        evidence: EvidenceLedger | None = None,
        node_name: str = "win-desktop",
        worker_transport: Any = None,
        *,
        remote_target: str = "svhome",
        max_retries: int = 4,
        evidence_ttl_s: float = 300.0,
        queue_dir: Path | None = None,
        remote_cas_dir: str = "~/.chimera/exile_cas",
    ) -> None:
        self.jobs = jobs
        self.cas = cas
        self.pulse = pulse
        self.governor = governor
        self.exile = exile
        self.evidence = evidence
        self.node_name = str(node_name or "win-desktop")
        self.worker_transport = worker_transport
        self.remote_target = str(remote_target or "svhome")
        self.remote_cas_dir = str(remote_cas_dir)
        self.queue_dir = Path(queue_dir) if queue_dir is not None else (
            self.jobs.db_path.parent / "guarded-builds" / "outgoing")
        self.max_retries = max(0, int(max_retries))
        self.evidence_ttl_s = max(1.0, float(evidence_ttl_s))

        self._lock = threading.Lock()
        self._handoffs_total = 0
        self._steps_committed = 0
        self._steps_resumed_idempotent = 0
        self._retries_total = 0
        self._wire_bytes_total = 0
        self._retransmitted_bytes_total = 0
        self._win_cpu_yields = 0
        self._last_handoff: dict[str, Any] | None = None

    def _evaluate_governor(self, prefer_target: str | None = None) -> tuple[str, bool, dict[str, Any] | None]:
        if self.governor is None or not hasattr(self.governor, "evaluate_state"):
            return (prefer_target or self.remote_target), False, None
        gov_state = dict(self.governor.evaluate_state() or {})
        preempt = bool(gov_state.get("preempt_yield", False))
        accept_heavy = bool(gov_state.get("accept_heavy_jobs", True))
        if preempt or (not accept_heavy):
            target = prefer_target if (prefer_target and prefer_target != self.node_name) else self.remote_target
            return target, True, gov_state
        return (prefer_target or self.node_name), False, gov_state

    def _resolve_transport(self, target_node: str) -> tuple[Any, str | None]:
        if self.worker_transport is not None:
            return self.worker_transport, None
        if self.exile is not None and target_node != self.node_name:
            return _GuardedCasTransport(self.exile, self.remote_cas_dir), None
        fb = "local_cas_worker" if target_node != self.node_name else None
        return _LocalCasFallbackTransport(self.cas, self.node_name), fb

    def _publish_pulse(self, topic: str, payload: dict[str, Any], app: str = "exile") -> None:
        if self.pulse is None or not hasattr(self.pulse, "publish"):
            return
        try:
            self.pulse.publish(topic, payload, app=app, relay=False)
        except Exception:
            pass

    def _record_evidence(
        self,
        *,
        execution_node: str,
        fallback_mode: str | None,
        job_id: str,
        step_key: str,
        generation: int,
        output_digest: str,
        wire_bytes: int,
        retransmitted_bytes: int,
        win_cpu_yielded: bool,
        elapsed_ms: float,
    ) -> None:
        if self.evidence is None:
            return
        receipt_id = f"{job_id}:{step_key}:g{generation}:{output_digest[:12]}"
        job_stats = self.jobs.stats()
        self.evidence.record(
            "immortal_jobs",
            execution_node=execution_node,
            fallback_mode=fallback_mode,
            ttl_s=self.evidence_ttl_s,
            verified=True,
            violated=False,
            metrics={
                "job_id": job_id,
                "step_key": step_key,
                "generation": generation,
                "output_digest": output_digest,
                "durable_receipts": job_stats.get("durable_receipts", 0),
                "stale_receipts_rejected": job_stats.get("stale_receipts_rejected", 0),
            },
            receipt_id=receipt_id,
        )
        self.evidence.record(
            "exile",
            execution_node=execution_node,
            fallback_mode=fallback_mode,
            ttl_s=self.evidence_ttl_s,
            verified=True,
            violated=False,
            metrics={
                "job_id": job_id,
                "step_key": step_key,
                "generation": generation,
                "wire_bytes": wire_bytes,
                "retransmitted_bytes": retransmitted_bytes,
                "win_cpu_yielded": win_cpu_yielded,
                "elapsed_ms": round(elapsed_ms, 3),
            },
            receipt_id=receipt_id,
        )

    def submit_receipt(
        self,
        receipt: dict[str, Any],
        *,
        result: Any = None,
        step_index: int = 0,
    ) -> dict[str, Any]:
        """Submit an out-of-band or delayed worker receipt to the single commit authority."""
        return self.jobs.commit_step_receipt(
            job_id=str(receipt["job_id"]),
            step_key=str(receipt["step_key"]),
            step_index=int(step_index),
            generation=int(receipt["generation"]),
            node_id=str(receipt["node_id"]),
            input_digest=str(receipt["input_digest"]),
            output_digest=str(receipt["output_digest"]),
            result=result,
            output_cas_hash=str(receipt.get("output_cas_hash") or ""),
        )

    def handoff_step(
        self,
        *,
        job_id: str,
        step_key: str,
        step_index: int = 0,
        payload: bytes | bytearray | str | dict[str, Any] | list[Any] | None = None,
        blocks: dict[str, bytes] | list[bytes] | None = None,
        op: str = "sha256_manifest",
        params: dict[str, Any] | None = None,
        block_size: int = 4096,
        max_retries: int | None = None,
        prefer_target: str | None = None,
        app: str = "exile",
        post_commit_hook: Callable[[dict[str, Any]], None] | None = None,
        _frozen_chunks: list[tuple[str, memoryview]] | None = None,
    ) -> dict[str, Any]:
        """Execute a single checkpointed generation-fenced step with CAS delta transfer and retries."""
        t0 = time.perf_counter()
        chunks = _frozen_chunks if _frozen_chunks is not None else chunk_step_inputs(
            payload=payload, blocks=blocks, block_size=block_size)
        block_manifest: list[dict[str, Any]] = []
        block_bytes_map: dict[str, bytes] = {}
        unique_digests: list[str] = []
        seen_digests: set[str] = set()
        for rel_path, raw_chunk in chunks:
            ing = self.cas.ingest_bytes(f"exile/{job_id}/{step_key}/{rel_path}", raw_chunk)
            digest = str(ing["digest"])
            block_manifest.append(
                {
                    "rel_path": rel_path,
                    "digest": digest,
                    "size": int(ing["size"]),
                    "deduped": bool(ing["deduped"]),
                }
            )
            block_bytes_map[digest] = raw_chunk
            if digest not in seen_digests:
                seen_digests.add(digest)
                unique_digests.append(digest)

        input_digest = compute_step_input_digest(op, params, block_manifest)
        target_node, win_cpu_yielded, gov_state = self._evaluate_governor(prefer_target=prefer_target)
        transport, fallback_mode = self._resolve_transport(target_node)

        retries_allowed = self.max_retries if max_retries is None else max(0, int(max_retries))
        wire_bytes = 0
        retransmitted_bytes = 0
        sent_digests: set[str] = set()
        last_error = ""
        retries_used = 0

        for attempt in range(retries_allowed + 1):
            lease = self.jobs.acquire_step_lease(
                job_id,
                step_key,
                step_index,
                input_digest,
                target_node,
            )
            if lease.get("already_completed"):
                previous = lease.get("receipt") or {}
                if (not previous or previous.get("input_digest") != input_digest
                        or lease["step_index"] != int(step_index)):
                    return {"ok": False, "state": "rejected", "error": "completed_step_inputs_changed",
                            "job_id": job_id, "step_key": step_key, "attempts": 0, "retries": 0}
                elapsed_ms = (time.perf_counter() - t0) * 1000.0
                receipt = lease.get("receipt") or {}
                with self._lock:
                    self._steps_resumed_idempotent += 1
                    if win_cpu_yielded:
                        self._win_cpu_yields += 1
                return {
                    "ok": True,
                    "job_id": job_id,
                    "step_key": step_key,
                    "step_index": int(step_index),
                    "already_completed": True,
                    "idempotent_resume": True,
                    "generation": int(receipt.get("generation") or lease.get("generation") or 0),
                    "target_node": str(receipt.get("node_id") or target_node),
                    "win_cpu_yielded": win_cpu_yielded,
                    "governor": gov_state,
                    "input_digest": input_digest,
                    "output_digest": str(receipt.get("output_digest") or ""),
                    "output_cas_hash": str(receipt.get("output_cas_hash") or ""),
                    "result": lease.get("cached_result"),
                    "receipt": receipt,
                    "wire_bytes": 0,
                    "retransmitted_bytes": 0,
                    "attempts": attempt,
                    "retries": 0,
                    "elapsed_ms": round(elapsed_ms, 3),
                }

            generation = int(lease["generation"])
            self._publish_pulse(
                "exile.step.dispatched",
                {
                    "job_id": job_id,
                    "step_key": step_key,
                    "step_index": int(step_index),
                    "generation": generation,
                    "input_digest": input_digest,
                    "target_node": target_node,
                    "win_cpu_yielded": win_cpu_yielded,
                },
                app=app,
            )

            try:
                missing = list(transport.query_missing_blocks(target_node, unique_digests))
                to_push = {d: block_bytes_map[d] for d in missing if d in block_bytes_map}
                if to_push:
                    chunk_sum = sum(len(v) for v in to_push.values())
                    retrans_sum = sum(len(v) for d, v in to_push.items() if d in sent_digests)
                    wire_bytes += chunk_sum
                    retransmitted_bytes += retrans_sum
                    sent_digests.update(to_push.keys())
                    push_res = transport.push_blocks(target_node, to_push)
                    if not push_res.get("ok", True):
                        raise ConnectionError(str(push_res.get("error") or "cas_push_failed"))

                exec_res = transport.execute_step(
                    target_node=target_node,
                    job_id=job_id,
                    step_key=step_key,
                    step_index=step_index,
                    generation=generation,
                    op=op,
                    params=params or {},
                    block_manifest=block_manifest,
                    input_digest=input_digest,
                )
                if not exec_res.get("ok"):
                    raise ConnectionError(str(exec_res.get("error") or "worker_exec_failed"))

                receipt = exec_res.get("receipt") or {}
                if (receipt.get("job_id") != job_id or receipt.get("step_key") != step_key
                        or type(receipt.get("generation")) is not int or receipt["generation"] != generation
                        or receipt.get("input_digest") != input_digest):
                    raise ValueError("worker_receipt_lease_mismatch")
                actual_node = receipt.get("node_id")
                if not isinstance(actual_node, str) or not actual_node or actual_node != exec_res.get("node_id"):
                    raise ValueError("worker_receipt_node_mismatch")
                if not isinstance(transport, (_GuardedCasTransport, _LocalCasFallbackTransport)) and actual_node != target_node:
                    raise ValueError("worker_receipt_target_mismatch")
                rec_gen = receipt["generation"]
                if exec_res.get("output_bytes") is not None:
                    out_bytes = exec_res["output_bytes"]
                elif "output_bytes_b64" in exec_res:
                    out_bytes = base64.b64decode(exec_res["output_bytes_b64"], validate=True)
                else:
                    raise ValueError("worker_output_missing")
                if not isinstance(out_bytes, bytes):
                    raise ValueError("invalid_worker_output")
                out_digest = hashlib.sha256(out_bytes).hexdigest()
                out_cas_hash = hashlib.blake2s(out_bytes, digest_size=16).hexdigest()
                if any(row.get("output_digest") != out_digest or row.get("output_cas_hash") != out_cas_hash
                       for row in (receipt, exec_res)):
                    raise ValueError("worker_receipt_output_mismatch")
                result_obj = exec_res.get("result")
                if op == "zlib_compress":
                    original = hashlib.sha256()
                    for item in block_manifest:
                        original.update(block_bytes_map[item["digest"]])
                    if result_obj != {"op": op, "blocks": len(block_manifest),
                                      "raw_bytes": sum(item["size"] for item in block_manifest),
                                      "compressed_bytes": len(out_bytes), "raw_sha256": original.hexdigest(),
                                      "compressed_sha256": out_digest}:
                        raise ValueError("worker_result_mismatch")
                elif op in ("xor_scale", "transform_bytes"):
                    if result_obj != {"op": op, "blocks": len(block_manifest), "bytes": len(out_bytes),
                                      "mask": int((params or {}).get("mask", 0x5A)) & 255, "output_sha256": out_digest}:
                        raise ValueError("worker_result_mismatch")
                elif json.dumps(result_obj, sort_keys=True, separators=(",", ":")).encode() != out_bytes:
                    raise ValueError("worker_result_mismatch")
                self.cas.ingest_bytes(f"exile/{job_id}/{step_key}/output.bin", out_bytes)
                commit_res = self.jobs.commit_step_receipt(
                    job_id=job_id, step_key=step_key, step_index=int(step_index), generation=rec_gen,
                    node_id=actual_node, input_digest=input_digest, output_digest=out_digest,
                    result=result_obj, output_cas_hash=out_cas_hash,
                )
                if not commit_res.get("ok"):
                    raise ValueError(f"commit_rejected:{commit_res.get('reason')}")

                elapsed_ms = (time.perf_counter() - t0) * 1000.0
                self._publish_pulse(
                    "exile.step.committed",
                    {
                        "job_id": job_id,
                        "step_key": step_key,
                        "step_index": int(step_index),
                        "generation": rec_gen,
                        "node_id": actual_node,
                        "output_digest": out_digest,
                        "output_cas_hash": out_cas_hash,
                    },
                    app=app,
                )
                self._record_evidence(
                    execution_node=actual_node,
                    fallback_mode=fallback_mode,
                    job_id=job_id,
                    step_key=step_key,
                    generation=rec_gen,
                    output_digest=out_digest,
                    wire_bytes=wire_bytes,
                    retransmitted_bytes=retransmitted_bytes,
                    win_cpu_yielded=win_cpu_yielded,
                    elapsed_ms=elapsed_ms,
                )

                with self._lock:
                    self._steps_committed += 1
                    self._retries_total += retries_used
                    self._wire_bytes_total += wire_bytes
                    self._retransmitted_bytes_total += retransmitted_bytes
                    if win_cpu_yielded:
                        self._win_cpu_yields += 1

                final_out = {
                    **({"guard": exec_res["guard"]} if "guard" in exec_res else {}),
                    "ok": True,
                    "job_id": job_id,
                    "step_key": step_key,
                    "step_index": int(step_index),
                    "already_completed": bool(commit_res.get("already_completed", False)),
                    "idempotent_resume": bool(commit_res.get("idempotent", False)),
                    "generation": rec_gen,
                    "target_node": actual_node,
                    "fallback_mode": fallback_mode,
                    "win_cpu_yielded": win_cpu_yielded,
                    "governor": gov_state,
                    "input_digest": input_digest,
                    "output_digest": out_digest,
                    "output_cas_hash": out_cas_hash,
                    "result": result_obj if not commit_res.get("already_completed") else commit_res.get("cached_result", result_obj),
                    "receipt": commit_res.get("receipt"),
                    "wire_bytes": wire_bytes,
                    "retransmitted_bytes": retransmitted_bytes,
                    "attempts": attempt + 1,
                    "retries": retries_used,
                    "elapsed_ms": round(elapsed_ms, 3),
                }
            except (GuardedCasFailure, ValueError) as exc:
                state = exc.state if isinstance(exc, GuardedCasFailure) else "rejected"
                return {"ok": False, "state": state, "error": str(exc), "job_id": job_id,
                        "step_key": step_key, "step_index": step_index, "target_node": target_node,
                        "wire_bytes": wire_bytes, "retransmitted_bytes": retransmitted_bytes,
                        "attempts": attempt + 1, "retries": retries_used, "win_cpu_yielded": win_cpu_yielded}
            except (OSError, TimeoutError, ConnectionError, RuntimeError) as exc:
                last_error = str(exc)
                if attempt >= retries_allowed:
                    break
                retries_used += 1
                continue

            if post_commit_hook is not None:
                post_commit_hook(commit_res)
            return final_out

        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        with self._lock:
            self._retries_total += retries_used
            self._wire_bytes_total += wire_bytes
            self._retransmitted_bytes_total += retransmitted_bytes
        return {
            "ok": False,
            "job_id": job_id,
            "step_key": step_key,
            "step_index": int(step_index),
            "error": last_error or "handoff_failed",
            "target_node": target_node,
            "win_cpu_yielded": win_cpu_yielded,
            "wire_bytes": wire_bytes,
            "retransmitted_bytes": retransmitted_bytes,
            "attempts": retries_allowed + 1,
            "retries": retries_used,
            "elapsed_ms": round(elapsed_ms, 3),
        }

    def handoff_job(
        self,
        steps: list[dict[str, Any]],
        *,
        job_id: str | None = None,
        app: str = "exile",
        name: str = "exile_handoff",
        meta: dict[str, Any] | None = None,
        max_retries: int | None = None,
        prefer_target: str | None = None,
        _queue_id: str | None = None,
    ) -> dict[str, Any]:
        """Create or resume a durable multi-step job and hand off each step with generation fencing."""
        t0 = time.perf_counter()
        if not steps:
            raise ValueError("steps must be a non-empty list")
        from . import build_queue

        pending_id = _queue_id
        if job_id and _queue_id is None:
            pending = build_queue.find_exile(self.queue_dir, str(self.jobs.db_path.resolve()), str(job_id).strip())
            if pending:
                from .exile_queue import manifest

                if manifest(steps, freeze_bytes=False)[0] != pending[1]:
                    return {"ok": False, "state": "rejected", "error": "queued_exile_inputs_changed",
                            "job_id": job_id, "queue": {"stored": True, "id": pending[0]}}
                from .guarded_build import retry_queued

                return retry_queued(pending[0], state_dir=self.queue_dir)
        job_rec = self.jobs.create_job(
            job_id=job_id,
            app=app,
            name=name,
            total_steps=len(steps),
            meta=meta,
        )
        jid = str(job_rec["job_id"])
        if job_rec["total_steps"] != len(steps):
            return {"ok": False, "state": "rejected", "error": "job_step_count_changed", "job_id": jid}
        step_results: list[dict[str, Any]] = []
        total_wire = 0
        total_retrans = 0
        any_yielded = False
        all_ok = True

        for idx, spec in enumerate(steps):
            skey = str(spec.get("step_key") or f"step_{idx}")
            sidx = int(spec.get("step_index", idx))
            sres = self.handoff_step(
                job_id=jid,
                step_key=skey,
                step_index=sidx,
                payload=spec.get("payload"),
                blocks=spec.get("blocks"),
                op=str(spec.get("op") or "sha256_manifest"),
                params=spec.get("params"),
                block_size=int(spec.get("block_size") or 4096),
                max_retries=max_retries,
                prefer_target=spec.get("prefer_target") or prefer_target,
                app=app,
                post_commit_hook=spec.get("post_commit_hook"),
                _frozen_chunks=spec.get("_frozen_chunks") if _queue_id is not None else None,
            )
            step_results.append(sres)
            total_wire += int(sres.get("wire_bytes") or 0)
            total_retrans += int(sres.get("retransmitted_bytes") or 0)
            any_yielded = any_yielded or bool(sres.get("win_cpu_yielded"))
            if not sres.get("ok"):
                all_ok = False
                break

        resumed = self.jobs.resume_job(jid) or job_rec
        elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 3)
        summary = {
            "ok": all_ok and resumed.get("status") == "completed",
            "job_id": jid,
            "job_status": resumed.get("status"),
            "completed_count": resumed.get("completed_count", 0),
            "total_steps": len(steps),
            "win_cpu_yielded": any_yielded,
            "wire_bytes": total_wire,
            "retransmitted_bytes": total_retrans,
            "steps": step_results,
            "receipts": self.jobs.get_receipts(job_id=jid, limit=len(steps) + 10),
            "elapsed_ms": elapsed_ms,
        }
        if summary["ok"] and pending_id:
            build_queue.finish(self.queue_dir, pending_id)
            summary["queue"] = {"stored": False, "id": pending_id}
        elif not all_ok:
            failed = step_results[-1]
            state = failed.get("state", "failed")
            summary.update(state=state, error=failed.get("error", "handoff_failed"))
            if pending_id:
                kept = build_queue.update_reason(self.queue_dir, pending_id, summary["error"])
                summary["queue"] = {"stored": kept, "id": pending_id}
            elif state in {"deferred", "indeterminate"} and isinstance(
                self._resolve_transport(failed["target_node"])[0], _GuardedCasTransport
            ):
                from .exile_queue import enqueue

                summary["queue"] = enqueue(
                    self, steps, job_id=jid, app=job_rec["app"], name=job_rec["name"], meta=job_rec["meta"],
                    max_retries=self.max_retries if max_retries is None else max_retries,
                    prefer_target=prefer_target, failed=failed,
                )
            summary["retryable"] = bool(summary.get("queue", {}).get("stored")
                                        and state in {"deferred", "indeterminate"})
        with self._lock:
            self._handoffs_total += 1
            self._last_handoff = {
                "job_id": jid,
                "ok": summary["ok"],
                "job_status": summary["job_status"],
                "steps": len(step_results),
                "win_cpu_yielded": any_yielded,
                "wire_bytes": total_wire,
                "retransmitted_bytes": total_retrans,
                "elapsed_ms": elapsed_ms,
            }
        return summary

    def receipts(self, job_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        return self.jobs.get_receipts(job_id=job_id, limit=limit)

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "ok": True,
                "node_name": self.node_name,
                "remote_target": self.remote_target,
                "handoffs_total": self._handoffs_total,
                "steps_committed": self._steps_committed,
                "steps_resumed_idempotent": self._steps_resumed_idempotent,
                "retries_total": self._retries_total,
                "wire_bytes_total": self._wire_bytes_total,
                "retransmitted_bytes_total": self._retransmitted_bytes_total,
                "win_cpu_yields": self._win_cpu_yields,
                "jobs": self.jobs.stats(),
                "cas": self.cas.stats(),
                "last_handoff": dict(self._last_handoff) if self._last_handoff else None,
            }
