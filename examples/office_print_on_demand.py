"""Run the existing Windows office dispatcher with on-demand PDF raster workers.

Use the Python environment of office_print.py. The normal queue, printer locks,
spool receipts, recovery and observation stay in the original application.
This launcher installs its pool adapter in this process only.
"""

from __future__ import annotations

import argparse
from concurrent.futures import BrokenExecutor, Executor, ProcessPoolExecutor
from contextlib import contextmanager
import importlib
import math
from pathlib import Path
import sys
import threading


class IdleRasterPool(Executor):
    """Retire all raster children after the last submitted operation settles."""

    def __init__(self, workers: int, idle_seconds: float, factory=ProcessPoolExecutor):
        if workers < 1 or idle_seconds <= 0 or not math.isfinite(idle_seconds):
            raise ValueError("workers and idle_seconds must be positive")
        self.workers = workers
        self.idle_seconds = idle_seconds
        self._factory = factory
        self._condition = threading.Condition()
        self._executor = None
        self._timer = None
        self._inflight = 0
        self._retiring = False
        self._poisoned = False
        self._closed = False

    def ready(self):
        with self._condition:
            return self._executor is not None

    def submit(self, fn, /, *args, **kwargs):
        with self._condition:
            self._condition.wait_for(lambda: self._closed or not (self._retiring or self._poisoned))
            if self._closed:
                raise RuntimeError("raster pool is closed")
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            if self._executor is None:
                self._executor = self._factory(max_workers=self.workers)
            self._inflight += 1
            try:
                future = self._executor.submit(fn, *args, **kwargs)
            except BaseException as exc:
                if isinstance(exc, BrokenExecutor):
                    self._poisoned = True
                self._finished(None)
                raise
            future.add_done_callback(self._finished)
            return future

    def _finished(self, future):
        with self._condition:
            self._inflight -= 1
            if future is not None and not future.cancelled() and isinstance(future.exception(), BrokenExecutor):
                self._poisoned = True
            if self._inflight == 0 and not self._closed:
                timer = threading.Timer(0 if self._poisoned else self.idle_seconds, self._retire)
                timer.daemon = True
                self._timer = timer
                timer.start()

    def _retire(self):
        with self._condition:
            if self._timer is not threading.current_thread() or self._inflight or self._closed:
                return
            self._timer = None
            self._retiring = True
            executor, self._executor = self._executor, None
        try:
            executor.shutdown(wait=True)
        finally:
            with self._condition:
                self._retiring = False
                self._poisoned = False
                self._condition.notify_all()

    def shutdown(self, wait=True, *, cancel_futures=False):
        # Existing callers retain results even during orderly process shutdown.
        with self._condition:
            self._closed = True
            self._condition.notify_all()
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            self._condition.wait_for(lambda: not self._retiring)
            executor, self._executor = self._executor, None
        if executor is not None:
            executor.shutdown(wait=wait, cancel_futures=cancel_futures)


@contextmanager
def dispatcher_pool(app_dir, *, workers=2, idle_seconds=30):
    """Bind the raster hooks used by office_service and office_delta at runtime."""
    root = Path(app_dir).resolve(strict=True)
    if not all((root / name).is_file() for name in ("office_pdl.py", "office_service.py")):
        raise ValueError("expected the directory containing office_service.py and office_pdl.py")
    sys.path.insert(0, str(root))
    try:
        pdl = importlib.import_module("office_pdl")
        if Path(pdl.__file__).resolve() != root / "office_pdl.py":
            raise RuntimeError("a different office_pdl module is already loaded")
        originals = {name: getattr(pdl, name) for name in
                     ("_get_pool", "_POOL_WORKERS", "_pool_ready", "warmup_pool", "shutdown_pool")}
        if pdl._pool_ready():
            raise RuntimeError("attach the adapter before starting the office dispatcher")
        with IdleRasterPool(workers, idle_seconds) as pool:
            # The worker calls warmup_pool on startup. Returning the facade postpones
            # construction until the first submission and also serves _get_pool callers.
            pdl._get_pool = pdl.warmup_pool = lambda: pool
            pdl._pool_ready = pool.ready
            pdl._POOL_WORKERS = workers
            pdl.shutdown_pool = pool.shutdown
            try:
                yield pool
            finally:
                for name, value in originals.items():
                    setattr(pdl, name, value)
    finally:
        sys.path.remove(str(root))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-dir", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--idle-seconds", type=float, default=30)
    args = parser.parse_args()
    with dispatcher_pool(args.app_dir, workers=args.workers, idle_seconds=args.idle_seconds):
        # worker() holds the office app's exclusive worker.lock throughout.
        import office_service

        office_service.worker()


if __name__ == "__main__":
    main()
