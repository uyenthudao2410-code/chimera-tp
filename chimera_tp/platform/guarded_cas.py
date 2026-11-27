"""Verified content-addressed jobs on the existing peer-guarded build transport."""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import tempfile
from typing import Any, Callable
import zlib


_MAX_BYTES = 64 * 1024 * 1024
_RETURN_BYTES = 4 * 1024 * 1024
_RANGE_BYTES = 3 * 1024 * 1024
_MAX_BLOCKS = 12000
_COMMAND = "python3 -I -B -S cas_work.py"
_HASH = re.compile(r"[0-9a-f]{32}")


class GuardedCasFailure(RuntimeError):
    """The coordinator may resume this job explicitly, subject to a fresh admission."""

    def __init__(self, state, reason):
        super().__init__(reason)
        self.state = state


def _digest(value):
    if not isinstance(value, str) or not _HASH.fullmatch(value):
        raise ValueError("invalid_cas_digest")
    return value


def _cas_id(data):
    return hashlib.blake2s(data, digest_size=16).hexdigest()


def compute_step_input_digest(
    op: str,
    params: dict[str, Any] | None,
    block_manifest: list[dict[str, Any]],
) -> str:
    """Compute canonical SHA-256 input digest binding operation, params, and CAS block digests."""
    canonical = json.dumps(
        {
            "op": str(op),
            "params": params or {},
            "blocks": [
                {"rel_path": b["rel_path"], "digest": b["digest"], "size": int(b["size"])}
                for b in block_manifest
            ],
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def execute_deterministic_cas_op(
    op: str,
    params: dict[str, Any] | None,
    block_manifest: list[dict[str, Any]],
    block_reader: Callable[[str], bytes],
) -> tuple[bytes, dict[str, Any], str, str]:
    """Execute deterministic CAS transform returning (output_bytes, result, output_digest, output_cas_hash)."""
    p = params or {}
    chunks: list[bytes] = []
    block_shas: list[dict[str, Any]] = []
    for item in block_manifest:
        digest = str(item["digest"])
        raw_b = bytes(block_reader(digest))
        if len(raw_b) != item["size"] or _cas_id(raw_b) != digest:
            raise ValueError("cas_input_digest_or_size_mismatch")
        chunks.append(raw_b)
        block_shas.append(
            {
                "rel_path": item["rel_path"],
                "digest": digest,
                "size": len(raw_b),
                "sha256": hashlib.sha256(raw_b).hexdigest(),
            }
        )

    raw_all = b"".join(chunks)
    if op == "zlib_compress":
        lvl = max(1, min(9, int(p.get("level", 6))))
        out_bytes = zlib.compress(raw_all, level=lvl)
        result: dict[str, Any] = {
            "op": op,
            "blocks": len(block_manifest),
            "raw_bytes": len(raw_all),
            "compressed_bytes": len(out_bytes),
            "raw_sha256": hashlib.sha256(raw_all).hexdigest(),
            "compressed_sha256": hashlib.sha256(out_bytes).hexdigest(),
        }
    elif op in ("xor_scale", "transform_bytes"):
        mask = int(p.get("mask", 0x5A)) & 0xFF
        out_bytes = bytes(b ^ mask for b in raw_all)
        result = {
            "op": op,
            "blocks": len(block_manifest),
            "bytes": len(out_bytes),
            "mask": mask,
            "output_sha256": hashlib.sha256(out_bytes).hexdigest(),
        }
    else:
        h = hashlib.sha256()
        h.update(json.dumps({"op": op, "params": p}, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        for row in block_shas:
            h.update(row["sha256"].encode("ascii"))
        result = {
            "op": op,
            "blocks": len(block_manifest),
            "total_bytes": len(raw_all),
            "block_sha256s": [r["sha256"] for r in block_shas],
            "aggregate_sha256": h.hexdigest(),
        }
        out_bytes = json.dumps(result, sort_keys=True, separators=(",", ":")).encode("utf-8")

    output_digest = hashlib.sha256(out_bytes).hexdigest()
    output_cas_hash = hashlib.blake2s(out_bytes, digest_size=16).hexdigest()
    return out_bytes, result, output_digest, output_cas_hash


def _object(root, digest):
    digest = _digest(digest)
    path = root / "objects" / digest[:2] / digest
    if path.resolve() != path:
        raise ValueError("unsafe_cas_path")
    return path


def _read(path, digest, size=None):
    with path.open("rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > _MAX_BYTES or (
                size is not None and info.st_size != size):
            raise ValueError("cas_object_size_mismatch")
        data = stream.read(info.st_size + 1)
    if len(data) != info.st_size or _cas_id(data) != digest:
        raise ValueError("cas_object_corrupt")
    return data


def _publish(root, digest, data):
    path = _object(root, digest)
    if _cas_id(data) != digest or len(data) > _MAX_BYTES:
        raise ValueError("invalid_cas_payload")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.exists():
        _read(path, digest, len(data))
        return
    fd, name = tempfile.mkstemp(prefix=".cas-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(name, path)
        except FileExistsError:
            _read(path, digest, len(data))
    finally:
        Path(name).unlink(missing_ok=True)


def _cas_root(value):
    path = Path(value).expanduser()
    if not path.is_absolute() or path == Path(path.anchor) or ".." in path.parts or path.resolve() != path:
        raise ValueError("invalid_receiver_cas_root")
    return path


def _receiver(action, request, root):
    if action == "query":
        keys = request["digests"]
        if len(keys) > _MAX_BLOCKS:
            raise ValueError("too_many_cas_blocks")
        present, missing = [], []
        for digest in keys:
            path = _object(root, digest)
            if path.exists():
                _read(path, digest)
                present.append(digest)
            else:
                missing.append(digest)
        return {"present": present, "missing": missing}
    if action == "push":
        blocks = request["blocks"]
        if len(blocks) > _MAX_BLOCKS or sum(blocks.values()) > _MAX_BYTES:
            raise ValueError("cas_transfer_limit")
        for digest, size in blocks.items():
            data = _read(Path("input") / _digest(digest), digest, size)
            _publish(root, digest, data)
        return {"blocks_pushed": len(blocks)}
    if action == "read":
        digest = _digest(request["digest"])
        data = _read(_object(root, digest), digest, request["size"])
        offset = request["offset"]
        if type(offset) is not int or not 0 <= offset < len(data):
            raise ValueError("invalid_cas_offset")
        chunk = data[offset:offset + _RANGE_BYTES]
        Path("output.bin").write_bytes(chunk)
        return {"offset": offset, "bytes": len(chunk), "digest": digest}
    if action != "execute":
        raise ValueError("unsupported_cas_action")
    manifest = request["block_manifest"]
    if (len(manifest) > _MAX_BLOCKS or any(type(item["size"]) is not int or item["size"] < 0 for item in manifest)
            or sum(item["size"] for item in manifest) > _MAX_BYTES):
        raise ValueError("cas_input_limit")
    if compute_step_input_digest(request["op"], request["params"], manifest) != request["input_digest"]:
        raise ValueError("cas_input_manifest_mismatch")
    output, result, output_sha, digest = execute_deterministic_cas_op(
        request["op"], request["params"], manifest, lambda d: _read(_object(root, d), d))
    _publish(root, digest, output)
    worker_node = platform.node()
    receipt = {key: request[key] for key in ("job_id", "step_key", "generation", "input_digest")}
    receipt.update(node_id=worker_node, output_digest=output_sha, output_cas_hash=digest)
    # Larger output is read from the published object in bounded, individually verified ranges.
    limit = _RETURN_BYTES - len(json.dumps(result).encode()) - 4096
    inline = len(output) <= min(_RANGE_BYTES, limit)
    Path("output.bin").write_bytes(output if inline else b"")
    return {"result": result, "receipt": receipt, "output_digest": output_sha, "output_size": len(output),
            "output_cas_hash": digest, "inline": inline, "node_id": worker_node}


def _main():
    with Path("request.json").open(encoding="utf-8") as stream:
        request = json.load(stream)
    response = _receiver(request["action"], request, _cas_root(request["cas_dir"]))
    with Path("response.json").open("x", encoding="utf-8") as stream:
        json.dump({"ok": True, **response}, stream, ensure_ascii=True, separators=(",", ":"), allow_nan=False)


def _artifact(parent, name):
    # The receiver runs a stand-alone copy of this file. Only the sender reads artifacts.
    from .build_snapshot import artifact_bytes

    try:
        return artifact_bytes(parent["artifacts"][name], _RETURN_BYTES)
    except ValueError as exc:
        raise ValueError("invalid_guarded_artifact") from exc


def dispatch(action, request, *, peer, cas_dir, timeout_s, blocks=None, policy=None):
    from .guarded_build import submit_isolated

    artifacts = ["response.json"]
    if action in ("execute", "read"):
        artifacts.append("output.bin")
    if blocks is not None and (len(blocks) > _MAX_BLOCKS or sum(map(len, blocks.values())) > _MAX_BYTES):
        raise ValueError("cas_transfer_limit")
    with tempfile.TemporaryDirectory(prefix="chimera-exile-action-") as directory:
        root = Path(directory)
        shutil.copyfile(__file__, root / "cas_work.py")
        payload = {**request, "action": action, "cas_dir": str(cas_dir)}
        if blocks is not None:
            inputs = root / "input"
            inputs.mkdir()
            payload["blocks"] = {}
            for digest, data in blocks.items():
                if _cas_id(data) != _digest(digest):
                    raise ValueError("invalid_cas_payload")
                (inputs / digest).write_bytes(data)
                payload["blocks"][digest] = len(data)
        (root / "request.json").write_text(json.dumps(payload, allow_nan=False), encoding="utf-8")
        parent = submit_isolated(_COMMAND, cwd=root, peer=peer, timeout_s=timeout_s, sync=True,
                                 reuse=False, artifacts=artifacts, admission_policy=policy)
    if not parent.get("ok"):
        raise GuardedCasFailure(parent.get("state", "failed"),
                                str(parent.get("error") or parent.get("stderr") or "guarded_cas_action_failed"))
    if (not parent.get("admission", {}).get("limits_verified") or parent.get("delivery") != "executed"
            or not parent.get("target") or not parent.get("attempt_id") or not parent.get("snapshot")):
        raise ValueError("missing_guarded_cas_admission")
    result = json.loads(_artifact(parent, "response.json"))
    if action == "query":
        missing = result.get("missing")
        present = result.get("present")
        if not isinstance(missing, list) or not isinstance(present, list):
            raise ValueError("guarded_cas_inventory_mismatch")
        reported = [_digest(value) for value in missing + present]
        if sorted(reported) != sorted(request["digests"]) or set(missing).intersection(present):
            raise ValueError("guarded_cas_inventory_mismatch")
    result["guard"] = {key: parent.get(key) for key in
                       ("attempt_id", "snapshot", "target", "runtime_guard", "ssh_request_bytes", "elapsed_end_to_end_ms")}
    result["guard"]["limits_verified"] = True
    if action in ("execute", "read"):
        result["output_bytes"] = _artifact(parent, "output.bin")
    if action == "execute":
        receipt = result["receipt"]
        if (any(receipt.get(key) != request[key] for key in ("job_id", "step_key", "generation", "input_digest"))
                or receipt.get("node_id") != parent["target"] or result.get("node_id") != parent["target"]
                or receipt.get("output_digest") != result.get("output_digest")
                or receipt.get("output_cas_hash") != result.get("output_cas_hash")):
            raise ValueError("guarded_cas_receipt_mismatch")
        size = result["output_size"]
        if type(size) is not int or not 0 <= size <= _MAX_BYTES:
            raise ValueError("invalid_guarded_output_size")
        data = result.pop("output_bytes")
        if result["inline"] is False:
            if data or not size:
                raise ValueError("invalid_chunked_cas_output")
            collected = bytearray()
            while len(collected) < size:
                offset = len(collected)
                part = dispatch("read", {"digest": result["output_cas_hash"], "size": size, "offset": offset},
                                peer=peer, cas_dir=cas_dir, timeout_s=timeout_s, policy=policy)
                chunk = part["output_bytes"]
                if (part.get("offset") != offset or part.get("digest") != result["output_cas_hash"]
                        or len(chunk) != min(size - offset, _RANGE_BYTES) or part.get("bytes") != len(chunk)):
                    raise ValueError("guarded_cas_chunk_mismatch")
                collected.extend(chunk)
            data = bytes(collected)
        if len(data) != size or hashlib.sha256(data).hexdigest() != result["output_digest"] or _cas_id(data) != result["output_cas_hash"]:
            raise ValueError("guarded_cas_output_mismatch")
        result["output_bytes_b64"] = base64.b64encode(data).decode("ascii")
    elif action == "push":
        result["wire_bytes"] = parent["ssh_request_bytes"]
    return result


if __name__ == "__main__":
    _main()
