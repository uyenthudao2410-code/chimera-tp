"""Freeze and resume a whole checkpointed CAS job through the shared build outbox."""

from __future__ import annotations

from contextlib import closing
import hashlib
from pathlib import Path
import sqlite3
import time

from . import build_queue
from .build_snapshot import canonical, sha


def manifest(steps, *, freeze_bytes):
    """Hash and order inputs exactly as the coordinator will dispatch them."""
    from .exile_handoff import chunk_step_inputs
    from .guarded_cas import compute_step_input_digest

    objects = {}
    wire = bytearray()
    rows = []
    fingerprints = []
    for index, step in enumerate(steps):
        key = str(step.get("step_key") or f"step_{index}")
        position = int(step.get("step_index", index))
        op = str(step.get("op") or "sha256_manifest")
        params = step.get("params") or {}
        chunks = chunk_step_inputs(payload=step.get("payload"), blocks=step.get("blocks"),
                                   block_size=int(step.get("block_size") or 4096))
        blocks = []
        for path, data in chunks:
            digest = hashlib.blake2s(data, digest_size=16).hexdigest()
            blocks.append({"rel_path": path, "digest": digest, "size": len(data)})
            if freeze_bytes and digest not in objects:
                if len(wire) + len(data) > build_queue.MAX_PENDING_BYTES:
                    raise ValueError("outbox_capacity")
                objects[digest] = {"offset": len(wire), "size": len(data)}
                wire.extend(data)
        inputs = compute_step_input_digest(op, params, blocks)
        fingerprints.append([key, position, inputs])
        rows.append({"step_key": key, "step_index": position, "op": op, "params": params,
                     "blocks": blocks, "prefer_target": step.get("prefer_target")})
    return sha(canonical(fingerprints)), rows, objects, wire


def enqueue(coordinator, steps, *, job_id, app, name, meta, max_retries, prefer_target, failed):
    """One SQLite transaction retains both the replay specification and the deduplicated bytes."""
    transport, _ = coordinator._resolve_transport(failed["target_node"])
    engine = transport.exile
    try:
        if any(step.get("post_commit_hook") is not None for step in steps):
            raise ValueError("process_local_callback_not_replayable")
        inputs, rows, objects, wire = manifest(steps, freeze_bytes=True)
        # A queued peer attempt must obtain a fresh admission from that peer, even if
        # the workstation becomes idle between the original dispatch and the retry.
        for row in rows:
            row["prefer_target"] = row["prefer_target"] or prefer_target or failed["target_node"]
        governor = coordinator.governor
        policy = governor.get_policy() if hasattr(governor, "get_policy") else "work_first"
        request = {
            "kind": "exile_handoff", "version": 1,
            "journal": str(coordinator.jobs.db_path.resolve()), "job_id": job_id,
            "cas": str(coordinator.cas.root.resolve()), "remote_cas": str(transport.remote_cas_dir),
            "admission_policy": engine.cas_admission_policy, "node": coordinator.node_name,
            "default_target": coordinator.remote_target,
            "prefer_target": prefer_target, "governor_role": getattr(governor, "role", "controller"),
            "governor_policy": policy, "max_retries": max_retries,
            "app": app, "name": name, "meta": meta or {}, "inputs_sha256": inputs,
            "steps": rows, "objects": objects, "wire_bytes": len(wire), "wire_sha256": sha(wire),
        }
        return build_queue.put(coordinator.queue_dir, engine.ssh_host, request, wire, failed["error"])
    except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
        return {"stored": False, "reason": str(exc)}


def _thaw(request, wire):
    from .guarded_cas import compute_step_input_digest

    if sha(wire) != request["wire_sha256"]:
        raise ValueError("queued_exile_input_corrupt")
    view = memoryview(wire)
    objects = {}
    for digest, obj in request["objects"].items():
        offset, size = obj["offset"], obj["size"]
        if offset < 0 or size < 0 or offset + size > len(wire):
            raise ValueError("queued_exile_object_range")
        data = view[offset:offset + size]
        if hashlib.blake2s(data, digest_size=16).hexdigest() != digest:
            raise ValueError("queued_exile_block_corrupt")
        objects[digest] = data
    steps = []
    fingerprints = []
    for row in request["steps"]:
        manifest_rows = row["blocks"]
        # Keep sequence order, repeated content and normalized path aliases exactly.
        chunks = []
        for block in manifest_rows:
            data = objects[block["digest"]]
            if len(data) != block["size"]:
                raise ValueError("queued_exile_manifest_corrupt")
            chunks.append((block["rel_path"], data))
        steps.append({**row, "_frozen_chunks": chunks})
        inputs = compute_step_input_digest(row["op"], row["params"], manifest_rows)
        fingerprints.append([row["step_key"], row["step_index"], inputs])
    if sha(canonical(fingerprints)) != request["inputs_sha256"]:
        raise ValueError("queued_exile_manifest_corrupt")
    return steps


def retry(root, key, peer, request, wire, wait_s):
    from .agent_workspace import _lock, LeaseBusy

    deadline = time.monotonic() + wait_s
    while True:
        try:
            with _lock(root / (key[:2] + ".replay.lock")):
                return _retry_locked(root, key, peer, request, wire, deadline)
        except LeaseBusy:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return {"ok": False, "state": "deferred", "error": "exile_replay_in_progress",
                        "retryable": True, "job_id": request["job_id"], "queue": {"stored": True, "id": key}}
            time.sleep(min(remaining, 0.05))


def _retry_locked(root, key, peer, request, wire, deadline):
    from ..host_governor import HostYieldGovernor
    from .cosmos_entity import ZeroEnvCasStore
    from .exile_handoff import CheckpointedExileCoordinator
    from .immortal_jobs import ImmortalJobEngine
    from .phantom_silicon import AgentExileEngine

    if request["version"] != 1:
        raise ValueError("queued_exile_version_unsupported")
    steps = _thaw(request, wire)
    journal = Path(request["journal"])
    if not journal.is_file():
        raise ValueError("queued_exile_journal_missing")
    with closing(ImmortalJobEngine(journal)) as jobs:
        job = jobs.resume_job(request["job_id"])
        if not job or job["total_steps"] != len(steps):
            raise ValueError("queued_exile_journal_mismatch")
        governor = HostYieldGovernor(role=request["governor_role"], policy=request["governor_policy"])
        engine = AgentExileEngine(ssh_host=peer, cas_admission_policy=request["admission_policy"])
        coordinator = CheckpointedExileCoordinator(
            jobs=jobs, cas=ZeroEnvCasStore(Path(request["cas"])), governor=governor,
            exile=engine, node_name=request["node"], remote_target=request["default_target"],
            remote_cas_dir=request["remote_cas"], queue_dir=root,
        )
        while True:
            active = build_queue.find_exile(root, request["journal"], request["job_id"])
            if active is None or active[0] != key:
                return {"ok": False, "state": "rejected", "error": "queued_exile_moved_or_completed",
                        "job_id": request["job_id"], "queue": {"stored": False, "id": key}}
            result = coordinator.handoff_job(
                steps, job_id=request["job_id"], app=request["app"], name=request["name"],
                meta=request["meta"], prefer_target=request["prefer_target"],
                max_retries=request["max_retries"], _queue_id=key,
            )
            remaining = deadline - time.monotonic()
            if result.get("state") != "deferred" or remaining <= 0 or not result.get("retryable"):
                return result
            time.sleep(min(remaining, 1.0))
