"""Shared input vectors and an independent byte oracle for the Exile recovery trials."""

from __future__ import annotations

import hashlib
import json
import zlib


FAULT_POINTS = (
    "pre_receive",
    "post_receive_pre_compute",
    "post_compute_pre_ack",
    "post_commit_pre_client_reply",
)


def trial_inputs(index: int, fault: str) -> tuple[str, dict[str, int], dict[str, bytes]]:
    """Include a cross-job shared block and a second copy of the job-specific block."""
    op = ("sha256_manifest", "zlib_compress", "xor_scale")[index % 3]
    params = {"trial": index, "mask": (index * 7 + 19) & 0xFF, "level": 4}
    unique = hashlib.sha256(f"payload-{index}-{fault}".encode()).digest() * 128
    blocks = {
        "00_shared.bin": (b"CHIMERA_SHARED_CAS_BASE_BLOCK_" * 140)[:4096],
        "01_unique_a.bin": unique,
        "02_unique_b.bin": unique,
    }
    return op, params, blocks


def _canonical(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def reference_output(
    op: str, params: dict[str, int], blocks: dict[str, bytes]
) -> tuple[str, bytes]:
    """Build the specified input digest and exact expected output using only the standard library."""
    ordered = sorted(blocks.items())
    manifest = [
        {"rel_path": name, "size": len(data), "digest": hashlib.blake2s(data, digest_size=16).hexdigest()}
        for name, data in ordered
    ]
    specification = _canonical({"op": op, "params": params, "blocks": manifest})
    raw = b"".join(data for _, data in ordered)
    if op == "zlib_compress":
        output = zlib.compress(raw, level=params["level"])
    elif op == "xor_scale":
        translation = bytes(value ^ params["mask"] for value in range(256))
        output = raw.translate(translation)
    elif op == "sha256_manifest":
        checksums = [hashlib.sha256(data).hexdigest() for _, data in ordered]
        prefix = _canonical({"op": op, "params": params})
        aggregate = hashlib.sha256(prefix + "".join(checksums).encode("ascii")).hexdigest()
        output = _canonical({
            "aggregate_sha256": aggregate,
            "block_sha256s": checksums,
            "blocks": len(ordered),
            "op": op,
            "total_bytes": len(raw),
        })
    else:
        raise ValueError(f"No reference vector for operation {op!r}")
    return hashlib.sha256(specification).hexdigest(), output
