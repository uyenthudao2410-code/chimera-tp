"""Windows CUDA worker serving a single private inherited pipe.

Only numeric buffers and the fixed PTX kernels are accepted. The process
stops after a one-shot operation, explicit release, foreground yield, pipe
closure, or expiration of its short native CUDA lease.
"""

import json
import os
from pathlib import Path
import sys

HEADER_LIMIT = 8192
BUFFER_LIMIT = 64 * 1024 * 1024


def _header(channel):
    data = json.loads(channel.recv_bytes(HEADER_LIMIT))
    if not isinstance(data, dict):
        raise ValueError("invalid CUDA request")
    return data


def _buffer(channel, size):
    if not 0 <= size <= BUFFER_LIMIT:
        raise ValueError("CUDA array size outside worker limit")
    data = channel.recv_bytes(max(1, size))
    if len(data) != size:
        raise ValueError("CUDA buffer size mismatch")
    return data


def _execute(engine, channel, header):
    from array import array

    op = header["op"]
    leased = header.get("use_lease") is True
    if op == "probe":
        return engine.probe()
    if op == "release":
        return engine.release_lease(str(header.get("reason", "explicit"))[:128])
    if op == "vsa_bench":
        from chimera_tp.platform.aeon_dynamo import AeonDynamoCore
        return AeonDynamoCore._run_green_ptx_benchmark(engine, int(header["rows"]))
    if op == "dot_bench":
        count = max(64, min(262144, int(header["count"])))
        left = array("f", (i % 13 - 6 for i in range(count)))
        right = array("f", (i % 7 - 3 for i in range(count)))
        return engine.run_vec_dot_kernel(left, right)
    if op == "hamming":
        rows = int(header["rows"])
        words = int(header["words"])
        if rows < 0 or words < 1 or rows * words * 4 > BUFFER_LIMIT:
            raise ValueError("invalid Hamming dimensions")
        q = _buffer(channel, words * 4 if rows else 0)
        matrix = _buffer(channel, rows * words * 4)
        return engine.run_vsa_hamming_batch(q, matrix, rows=rows, words_per_row=words, use_lease=leased)
    if op in ("dot", "axpy"):
        count = int(header["count"])
        x = array("f")
        y = array("f")
        x.frombytes(_buffer(channel, count * 4))
        y.frombytes(_buffer(channel, count * 4))
        if op == "dot":
            return engine.run_vec_dot_kernel(x, y, use_lease=leased)
        return engine.run_es_axpy_kernel(x, y, float(header["scale"]), use_lease=leased)
    raise ValueError("unknown CUDA operation")


def serve(handle, ttl):
    from array import array
    from multiprocessing.connection import PipeConnection

    # With python -I -S the checkout is not on the import path. Resolve the
    # package from this worker's own file, independently of cwd/PYTHONPATH.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from chimera_tp.autopilot import get_zero_weight_status
    from chimera_tp.platform.nvcuda_ptx import NvCudaPtxEngine

    engine = NvCudaPtxEngine(lease_ttl_s=ttl)
    with PipeConnection(handle) as channel:
        try:
            while True:
                try:
                    request = _header(channel)
                    op = request["op"]
                    result = _execute(engine, channel, request)
                    payload = None
                    if "distances" in result:
                        payload = array("I", result.pop("distances"))
                    elif "out" in result:
                        payload = array("f", result.pop("out"))
                    status = engine.lease_status()
                    process = get_zero_weight_status()
                    response = {"result": result, "status": status, "pid": os.getpid(),
                                "peak_bytes": process["daemon_peak_rss_bytes"],
                                "lease_kept": op != "release" and status["lease_active"]}
                    channel.send_bytes(json.dumps(response, separators=(",", ":")).encode())
                    if payload is not None:
                        channel.send_bytes(memoryview(payload).cast("B"))
                except (EOFError, BrokenPipeError):
                    break
                except (OSError, RuntimeError, TypeError, ValueError, KeyError, OverflowError) as exc:
                    channel.send_bytes(json.dumps({"error": type(exc).__name__, "reason": str(exc)[:512]}).encode())
                    break
                if not response["lease_kept"]:
                    break
                # The native engine watches foreground applications as well as
                # its TTL. No child is kept solely for answering a status query.
                while not channel.poll(.1):
                    if not engine.lease_status()["lease_active"]:
                        return
        finally:
            engine.release_lease("worker_exit")


if __name__ == "__main__":
    if os.name != "nt" or len(sys.argv) != 3:
        raise SystemExit("Windows worker requires an inherited pipe and a lease TTL")
    serve(int(sys.argv[1]), float(sys.argv[2]))
