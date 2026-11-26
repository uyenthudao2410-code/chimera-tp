"""CHIMERA-ZYGOTE (Single-Threaded Pre-Fork Helper on Linux / Warm-Pool on Windows) + CANARY TWIN Judge."""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from typing import Any


def _run_kernel(kernel: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Whitelisted deterministic micro-kernels executed inside Zygote CoW fork or warm worker."""
    if kernel == "hash_batch":
        items = list(payload.get("items") or [])
        return {
            "count": len(items),
            "hashes": [hashlib.blake2s(str(x).encode("utf-8"), digest_size=16).hexdigest() for x in items],
        }
    if kernel == "json_filter":
        rows = list(payload.get("rows") or [])
        key = str(payload.get("key") or "")
        eq = payload.get("equals")
        matched = [r for r in rows if isinstance(r, dict) and r.get(key) == eq]
        return {"total": len(rows), "matched": len(matched), "rows": matched}
    if kernel == "regex_extract":
        text = str(payload.get("text") or "")
        pat = str(payload.get("pattern") or "")
        hits = re.findall(pat, text)[:500]
        return {"count": len(hits), "matches": hits}
    if kernel == "text_stats":
        text = str(payload.get("text") or "")
        words = text.split()
        return {"chars": len(text), "words": len(words), "lines": text.count("\n") + (1 if text else 0)}
    raise ValueError(f"Unsupported zygote kernel: {kernel}")


# Dedicated single-threaded Linux pre-fork helper script: 0 multi-thread fork warnings, 0 deadlock risk!
_LINUX_PREFORK_HELPER = r'''
import hashlib, json, os, re, sys

def run_k(kernel, payload):
    if kernel == "hash_batch":
        items = list(payload.get("items") or [])
        return {"count": len(items), "hashes": [hashlib.blake2s(str(x).encode("utf-8"), digest_size=16).hexdigest() for x in items]}
    if kernel == "json_filter":
        rows = list(payload.get("rows") or [])
        key = str(payload.get("key") or "")
        eq = payload.get("equals")
        matched = [r for r in rows if isinstance(r, dict) and r.get(key) == eq]
        return {"total": len(rows), "matched": len(matched), "rows": matched}
    if kernel == "regex_extract":
        text = str(payload.get("text") or "")
        pat = str(payload.get("pattern") or "")
        hits = re.findall(pat, text)[:500]
        return {"count": len(hits), "matches": hits}
    if kernel == "text_stats":
        text = str(payload.get("text") or "")
        words = text.split()
        return {"chars": len(text), "words": len(words), "lines": text.count("\n") + (1 if text else 0)}
    raise ValueError(f"Unsupported zygote kernel: {kernel}")

for raw_line in sys.stdin:
    line = raw_line.strip()
    if not line:
        continue
    req = json.loads(line)
    r_fd, w_fd = os.pipe()
    pid = os.fork()
    if pid == 0:
        os.close(r_fd)
        try:
            out = {"ok": True, "result": run_k(req["kernel"], req.get("payload") or {}), "pid": os.getpid()}
        except Exception as exc:
            out = {"ok": False, "error": str(exc), "pid": os.getpid()}
        with os.fdopen(w_fd, "wb") as wf:
            wf.write(json.dumps(out, ensure_ascii=False).encode("utf-8"))
        os._exit(0)
    else:
        os.close(w_fd)
        with os.fdopen(r_fd, "rb") as rf:
            data = rf.read().decode("utf-8")
        os.waitpid(pid, 0)
        sys.stdout.write(data + "\n")
        sys.stdout.flush()
'''


class ZygoteWorkerPool:
    """Single-threaded Linux pre-fork helper (0 warnings, ~1-3ms CoW fork) / Windows warm worker pool."""

    SUPPORTED_KERNELS = ("hash_batch", "json_filter", "regex_extract", "text_stats")

    def __init__(self) -> None:
        self.supports_cow_fork = hasattr(os, "fork") and os.name != "nt"
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="chimera-zygote")
        self._lock = threading.Lock()
        self._helper_lock = threading.Lock()
        self._helper: subprocess.Popen[str] | None = None
        self._exec_count = 0
        self._total_ms = 0.0

    def _ensure_helper_locked(self) -> subprocess.Popen[str]:
        if self._helper is not None and self._helper.poll() is None:
            return self._helper
        env = dict(os.environ)
        env["CHIMERA_DISABLE_AUTOLOAD"] = "1"
        self._helper = subprocess.Popen(
            [sys.executable, "-u", "-c", _LINUX_PREFORK_HELPER],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
            env=env,
        )
        return self._helper

    def execute(self, kernel: str, payload: dict[str, Any], prefer_fork: bool = True) -> dict[str, Any]:
        if kernel not in self.SUPPORTED_KERNELS:
            raise ValueError(f"Unknown kernel '{kernel}'. Allowed: {self.SUPPORTED_KERNELS}")
        t0 = time.perf_counter()
        mode = "warm_pool"
        child_pid = 0

        if self.supports_cow_fork and prefer_fork:
            mode = "linux_prefork_cow"
            with self._helper_lock:
                proc = self._ensure_helper_locked()
                assert proc.stdin is not None and proc.stdout is not None
                proc.stdin.write(json.dumps({"kernel": kernel, "payload": payload}, ensure_ascii=False) + "\n")
                proc.stdin.flush()
                line = proc.stdout.readline()
                if not line:
                    self._stop_helper_locked()
                    raise RuntimeError("Zygote pre-fork helper exited unexpectedly")
                parsed = json.loads(line)
                if not parsed.get("ok"):
                    raise RuntimeError(parsed.get("error", "prefork_worker_error"))
                out = parsed["result"]
                child_pid = int(parsed.get("pid") or 0)
        else:
            fut = self._executor.submit(_run_kernel, kernel, payload)
            out = fut.result(timeout=10.0)
            child_pid = os.getpid()

        ms = round((time.perf_counter() - t0) * 1000.0, 3)
        with self._lock:
            self._exec_count += 1
            self._total_ms += ms
        return {
            "ok": True,
            "kernel": kernel,
            "mode": mode,
            "worker_pid": child_pid,
            "elapsed_ms": ms,
            "result": out,
        }

    def status(self) -> dict[str, Any]:
        with self._lock:
            n = self._exec_count
            avg = round(self._total_ms / max(1, n), 3)
        helper_alive = self._helper is not None and self._helper.poll() is None
        return {
            "ok": True,
            "mode": "linux_prefork_cow" if self.supports_cow_fork else "windows_warm_pool",
            "supports_cow_fork": self.supports_cow_fork,
            "helper_running": helper_alive,
            "kernels": list(self.SUPPORTED_KERNELS),
            "executions": n,
            "avg_ms": avg,
        }

    def _stop_helper_locked(self) -> None:
        if self._helper is not None:
            try:
                if self._helper.stdin:
                    self._helper.stdin.close()
                if self._helper.stdout:
                    self._helper.stdout.close()
                self._helper.terminate()
                self._helper.wait(timeout=1.5)
            except Exception:
                try:
                    self._helper.kill()
                except Exception:
                    pass
            self._helper = None

    def close(self) -> None:
        with self._helper_lock:
            self._stop_helper_locked()
        self._executor.shutdown(wait=False)


def _strip_volatile(obj: Any, ignore_keys: set[str]) -> Any:
    if isinstance(obj, dict):
        return {k: _strip_volatile(v, ignore_keys) for k, v in obj.items() if k not in ignore_keys}
    if isinstance(obj, list):
        return [_strip_volatile(x, ignore_keys) for x in obj]
    return obj


class CanaryTwinJudge:
    """Zero-downtime shadow comparator: races baseline vs canary URLs and emits PROMOTE / ROLLBACK."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._runs = 0
        self._last_verdict: dict[str, Any] | None = None

    def compare(
        self,
        baseline_url: str,
        canary_url: str,
        paths: list[str] | None = None,
        samples: int = 5,
        max_p95_regression_ratio: float = 1.5,
        ignore_keys: list[str] | None = None,
        timeout_s: float = 4.0,
    ) -> dict[str, Any]:
        req_paths = list(paths or ["/"])
        n_samples = max(1, min(30, int(samples)))
        ign = set(ignore_keys or ["ts", "ts_ms", "ts_local", "elapsed_ms", "timestamp", "daemon_ram_mb", "host_free_ram_gb"])
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

        def _hit(base: str, path: str) -> dict[str, Any]:
            url = f"{base.rstrip('/')}/{path.lstrip('/')}" if path != "/" else base
            t0 = time.perf_counter()
            try:
                with opener.open(url, timeout=timeout_s) as r:
                    raw = r.read()
                    ms = (time.perf_counter() - t0) * 1000.0
                    return {"status": r.status, "ms": ms, "raw": raw, "error": ""}
            except urllib.error.HTTPError as e:
                ms = (time.perf_counter() - t0) * 1000.0
                return {"status": e.code, "ms": ms, "raw": e.read(), "error": str(e)}
            except Exception as exc:
                ms = (time.perf_counter() - t0) * 1000.0
                return {"status": 0, "ms": ms, "raw": b"", "error": str(exc)}

        base_lat: list[float] = []
        can_lat: list[float] = []
        base_err = 0
        can_err = 0
        mismatches: list[dict[str, Any]] = []
        total_checks = 0

        for i in range(n_samples):
            p = req_paths[i % len(req_paths)]
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
                f_b = ex.submit(_hit, baseline_url, p)
                f_c = ex.submit(_hit, canary_url, p)
                rb, rc = f_b.result(), f_c.result()
            total_checks += 1
            base_lat.append(rb["ms"])
            can_lat.append(rc["ms"])
            if rb["status"] == 0 or rb["status"] >= 500:
                base_err += 1
            if rc["status"] == 0 or rc["status"] >= 500:
                can_err += 1

            same = rb["status"] == rc["status"]
            if same:
                try:
                    jb = _strip_volatile(json.loads(rb["raw"].decode("utf-8")), ign)
                    jc = _strip_volatile(json.loads(rc["raw"].decode("utf-8")), ign)
                    same = jb == jc
                except Exception:
                    same = rb["raw"] == rc["raw"]
            if not same:
                mismatches.append(
                    {
                        "sample": i,
                        "path": p,
                        "baseline_status": rb["status"],
                        "canary_status": rc["status"],
                        "baseline_preview": rb["raw"][:160].decode("utf-8", "ignore"),
                        "canary_preview": rc["raw"][:160].decode("utf-8", "ignore"),
                    }
                )

        def _pct(vals: list[float], q: float) -> float:
            s = sorted(vals)
            idx = min(len(s) - 1, int(round((len(s) - 1) * q)))
            return round(s[idx], 2)

        b_p50, b_p95 = _pct(base_lat, 0.5), _pct(base_lat, 0.95)
        c_p50, c_p95 = _pct(can_lat, 0.5), _pct(can_lat, 0.95)
        parity_pct = round(((total_checks - len(mismatches)) / max(1, total_checks)) * 100.0, 2)

        reasons: list[str] = []
        if can_err > base_err:
            reasons.append(f"canary_errors({can_err}>{base_err})")
        if mismatches:
            reasons.append(f"output_mismatches({len(mismatches)}/{total_checks})")
        if b_p95 > 0 and c_p95 > max(b_p95 * max_p95_regression_ratio, b_p95 + 15.0):
            reasons.append(f"p95_regression({c_p95}ms vs {b_p95}ms)")

        verdict = "PROMOTE" if not reasons else "ROLLBACK"
        report = {
            "ok": True,
            "verdict": verdict,
            "reasons": reasons or ["all_gates_passed"],
            "samples": total_checks,
            "parity_pct": parity_pct,
            "baseline": {"url": baseline_url, "p50_ms": b_p50, "p95_ms": b_p95, "errors": base_err},
            "canary": {"url": canary_url, "p50_ms": c_p50, "p95_ms": c_p95, "errors": can_err},
            "mismatches": mismatches[:5],
        }
        with self._lock:
            self._runs += 1
            self._last_verdict = report
        return report

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {"runs": self._runs, "last_verdict": (self._last_verdict or {}).get("verdict")}
