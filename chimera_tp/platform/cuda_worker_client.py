"""Client for Windows daemon CUDA calls on an on-demand child process."""

from array import array
import json
from pathlib import Path
import subprocess
import sys
import threading
import time

from .cuda_worker import BUFFER_LIMIT, HEADER_LIMIT


class CudaWorkerEngine:
    """Keep nvcuda.dll out of the daemon, including for capability discovery."""

    _hardware_lock = threading.Lock()
    _capability = None
    _slot = threading.Lock()

    def __init__(self, *, lease_ttl_s=5.0):
        self._ttl = max(.5, min(30., float(lease_ttl_s)))
        self._lock = threading.RLock()
        self._process = None
        self._pipe = None
        self._deadline = 0.
        self._status = {}
        self._runs = 0
        self._lease_hits = 0
        self._lease_creates = 0
        self._lease_releases = 0
        self._last_reason = "init"
        self._last_worker = None
        self._worker_count = 0

    def _start(self):
        import _winapi
        from multiprocessing import Pipe

        parent, child = Pipe(duplex=True)
        try:
            handle = _winapi.DuplicateHandle(_winapi.GetCurrentProcess(), child.fileno(),
                                             _winapi.GetCurrentProcess(), 0, True, _winapi.DUPLICATE_SAME_ACCESS)
            try:
                startup = subprocess.STARTUPINFO()
                startup.lpAttributeList = {"handle_list": [handle]}
                script = Path(__file__).with_name("cuda_worker.py").resolve(strict=True)
                process = subprocess.Popen(
                    [sys.executable, "-I", "-B", "-S", str(script), str(handle), str(self._ttl)],
                    startupinfo=startup, close_fds=True,
                    creationflags=subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS,
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
            finally:
                _winapi.CloseHandle(handle)
        except BaseException:
            parent.close()
            raise
        finally:
            child.close()
        self._pipe, self._process = parent, process
        self._worker_count += 1

    def _finish(self, *, kill=False):
        process, pipe = self._process, self._pipe
        self._pipe = self._process = None
        self._deadline = 0.
        if pipe is not None:
            pipe.close()
        if process is not None:
            if kill and process.poll() is None:
                process.kill()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
            if self._last_worker and self._last_worker["pid"] == process.pid:
                self._last_worker["exited"] = True
            if self._status.get("lease_active"):
                self._lease_releases += 1
        self._status = {}

    def _alive(self):
        if self._process is None:
            return False
        if self._process.poll() is not None:
            self._finish()
            return False
        return True

    def _call(self, request, buffers=(), response_type=None, count=0):
        with self._lock, self._slot:
            if not self._alive():
                self._start()
            expiration = time.monotonic() + 45.
            # A write to a full pipe also needs a deadline if the child
            # becomes unresponsive before it has read the numeric buffers.
            process = self._process
            watchdog = threading.Timer(45., process.kill)
            watchdog.daemon = True
            watchdog.start()
            try:
                self._pipe.send_bytes(json.dumps(request, separators=(",", ":")).encode())
                for buffer in buffers:
                    self._pipe.send_bytes(memoryview(buffer).cast("B"))
                if not self._pipe.poll(max(0., expiration - time.monotonic())):
                    raise TimeoutError("CUDA worker response timed out")
                message = json.loads(self._pipe.recv_bytes(HEADER_LIMIT))
                if "error" in message:
                    error = ValueError if message["error"] in ("ValueError", "OverflowError") else RuntimeError
                    raise error(message["reason"])
                if message["pid"] != self._process.pid or message["peak_bytes"] <= 0:
                    raise RuntimeError("CUDA worker identity or working-set counters missing")
                result = message["result"]
                if response_type is not None:
                    code, key = response_type
                    if not self._pipe.poll(max(0., expiration - time.monotonic())):
                        raise TimeoutError("CUDA worker returned no numeric payload")
                    data = self._pipe.recv_bytes(max(1, count * 4))
                    if len(data) != count * 4:
                        raise RuntimeError("CUDA worker output length mismatch")
                    values = array(code)
                    values.frombytes(data)
                    result[key] = values.tolist()
                self._last_worker = {"pid": message["pid"], "peak_bytes": message["peak_bytes"], "exited": False}
                self._status = message["status"]
                self._last_reason = self._status["last_release_reason"]
                self._deadline = time.monotonic() + self._status["remaining_s"]
                if not message["lease_kept"]:
                    self._finish()
                return {**result, "execution": "windows_cuda_worker", "worker": dict(self._last_worker)}
            except BaseException:
                self._finish(kill=True)
                raise
            finally:
                watchdog.cancel()

    @staticmethod
    def is_vip_gpu_focused():
        from .nvcuda_ptx import NvCudaPtxEngine
        return NvCudaPtxEngine.is_vip_gpu_focused()

    def probe(self):
        # The device/SM are process-independent. The lease and run counters are
        # instance state. Coalesce simultaneous probes from the dashboard and router.
        with self._lock, self._hardware_lock:
            cached = type(self)._capability
            if cached is None or time.monotonic() >= cached[0]:
                result = self._call({"op": "probe"})
                device = {k: result[k] for k in ("available", "sm", "device")}
                type(self)._capability = (time.monotonic() + 60, device)
            else:
                device = cached[1]
            active = self._alive() and self._deadline > time.monotonic()
            return {**device, "runs": self._runs, "lease_hits": self._lease_hits,
                    "vip_yields": self._status.get("vip_yields", 0), "lease_active": active,
                    "execution": "windows_cuda_worker", "worker": self._last_worker}

    def lease_status(self):
        with self._lock:
            active = self._alive() and self._deadline > time.monotonic()
            vip, exe = self.is_vip_gpu_focused()
            return {"lease_active": active, "ttl_s": self._ttl,
                    "remaining_s": round(max(0, self._deadline - time.monotonic()), 2) if active else 0.,
                    "cached_kernels": list(self._status.get("cached_kernels", [])) if active else [],
                    "lease_creates": self._lease_creates, "lease_hits": self._lease_hits,
                    "lease_releases": self._lease_releases, "vip_yields": self._status.get("vip_yields", 0),
                    "last_release_reason": self._last_reason, "foreground_exe": exe, "vip_focused": vip,
                    "vram_retained_mb": -1. if active else 0., "execution": "windows_cuda_worker",
                    "worker": self._last_worker, "workers_started": self._worker_count}

    def release_lease(self, reason="explicit"):
        with self._lock:
            if self._alive():
                try:
                    result = self._call({"op": "release", "reason": str(reason)[:128]})
                except (EOFError, BrokenPipeError):
                    # A foreground yield or idle expiry may already have closed the worker.
                    pass
                else:
                    self._lease_releases += int(result["destroyed"])
                    return result
            return {"ok": True, "destroyed": False, "reason": reason, "vram_retained_mb": 0.,
                    "release_ms": 0., "execution": "windows_cuda_worker", "worker": self._last_worker}

    def _kernel(self, request, buffers, response_type=None, count=0):
        with self._lock:
            # A foreground yield or lease expiry can close the pipe while the next
            # request is arriving. These three numeric kernels have no persistent side effects.
            reused = self._alive()
            try:
                result = self._call(request, buffers, response_type, count)
            except (EOFError, BrokenPipeError):
                if not reused:
                    raise
                result = self._call(request, buffers, response_type, count)
            self._runs += 1
            self._lease_hits += int(bool(result.get("lease_reused")))
            self._lease_creates += int(bool(self._status.get("lease_active")) and not result.get("lease_reused"))
            return result

    def run_vsa_hamming_batch(self, query_words, matrix_words, *, rows, words_per_row=313, use_lease=False):
        n, words = max(0, int(rows)), max(1, int(words_per_row))
        qsize, msize = (words * 4 if n else 0), n * words * 4
        q = memoryview(query_words).cast("B")
        m = memoryview(matrix_words).cast("B")
        if qsize > BUFFER_LIMIT or msize > BUFFER_LIMIT or len(q) < qsize or len(m) < msize:
            raise ValueError("invalid CUDA Hamming dimensions or buffer length")
        return self._kernel({"op": "hamming", "rows": n, "words": words, "use_lease": bool(use_lease)},
                            (q[:qsize], m[:msize]), ("I", "distances"), n)

    def _vectors(self, op, x, y, use_lease, scale=None):
        from itertools import islice
        n = min(len(x), len(y))
        if n * 4 > BUFFER_LIMIT:
            raise ValueError("CUDA numeric array exceeds worker limit")
        buffers = [array("f", islice(items, n)) for items in (x, y)]
        request = {"op": op, "count": n, "use_lease": bool(use_lease), "scale": scale}
        return self._kernel(request, buffers, ("f", "out") if op == "axpy" else None, n)

    def run_dot_benchmark(self, count):
        return self._kernel({"op": "dot_bench", "count": count}, ())

    def run_vsa_benchmark(self, rows):
        return self._kernel({"op": "vsa_bench", "rows": rows}, ())

    def run_vec_dot_kernel(self, vec_a, vec_b, *, use_lease=False):
        return self._vectors("dot", vec_a, vec_b, use_lease)

    def run_es_axpy_kernel(self, theta, eps, scale, *, use_lease=False):
        return self._vectors("axpy", theta, eps, use_lease, float(scale))
