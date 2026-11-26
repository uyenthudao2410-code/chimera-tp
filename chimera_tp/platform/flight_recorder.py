"""Flight Recorder BlackBox (<2 MB bounded RAM ring) + Diskless Ephemeral RAM Secret Vault."""

from __future__ import annotations

import collections
import hashlib
import json
import os
import secrets
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable


class FlightRecorderBlackBox:
    """Zero-disk-write continuous RAM ring buffer; freezes synchronized 60s telemetry window on crash/trigger."""

    def __init__(
        self,
        out_dir: Path,
        sample_fn: Callable[[], dict[str, Any]],
        max_frames: int = 360,
        interval_s: float = 0.5,
    ) -> None:
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.sample_fn = sample_fn
        self.max_frames = int(max_frames)
        self.interval_s = max(0.1, float(interval_s))
        self._lock = threading.Lock()
        self._ring: collections.deque[dict[str, Any]] = collections.deque(maxlen=self.max_frames)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._freezes: int = 0

    def start(self) -> "FlightRecorderBlackBox":
        if self._thread is not None:
            return self
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return self

    def close(self) -> None:
        self._stop.set()

    def record_once(self) -> dict[str, Any]:
        try:
            snap = self.sample_fn()
        except Exception as exc:
            snap = {"error": str(exc)}
        frame = {
            "ts_ms": int(time.time() * 1000),
            "ts": datetime.now().astimezone().strftime("%H:%M:%S.%f")[:-3],
            **snap,
        }
        with self._lock:
            self._ring.append(frame)
        return frame

    def _loop(self) -> None:
        self.record_once()
        while not self._stop.wait(timeout=self.interval_s):
            self.record_once()

    def freeze(self, reason: str = "manual", app: str = "system", window_frames: int = 120) -> dict[str, Any]:
        self.record_once()
        with self._lock:
            frames = list(self._ring)[-max(1, int(window_frames)) :]
            self._freezes += 1
        ts = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
        fname = f"blackbox_{ts}_{self._freezes}.json"
        fpath = self.out_dir / fname
        payload = {
            "id": fname,
            "frozen_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "reason": str(reason),
            "app": str(app),
            "frame_count": len(frames),
            "frames": frames,
        }
        fpath.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        # Prune oldest snapshots > 25
        for old in sorted(self.out_dir.glob("blackbox_*.json"))[:-25]:
            try:
                old.unlink()
            except OSError:
                pass
        return {
            "ok": True,
            "id": fname,
            "path": str(fpath),
            "frame_count": len(frames),
            "reason": reason,
        }

    def list_freezes(self, limit: int = 10) -> list[dict[str, Any]]:
        files = sorted(self.out_dir.glob("blackbox_*.json"), reverse=True)[: max(1, limit)]
        out: list[dict[str, Any]] = []
        for f in files:
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
                out.append(
                    {
                        "id": d.get("id", f.name),
                        "frozen_at": d.get("frozen_at"),
                        "reason": d.get("reason"),
                        "app": d.get("app"),
                        "frame_count": d.get("frame_count", 0),
                    }
                )
            except Exception:
                continue
        return out

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "buffered_frames": len(self._ring),
                "max_frames": self.max_frames,
                "interval_s": self.interval_s,
                "freezes": self._freezes,
            }


class DisklessSecretVault:
    """In-RAM ephemeral secret store (0 plaintext written to disk); XOR-masked with per-boot ephemeral key."""

    def __init__(self, boot_token: str) -> None:
        self._boot_token = boot_token
        self._mask_key = secrets.token_bytes(32)
        self._lock = threading.Lock()
        self._secrets: dict[str, dict[str, Any]] = {}

    def _xor_stream(self, name: str, data: bytes) -> bytes:
        out = bytearray(len(data))
        blk_idx = 0
        pos = 0
        while pos < len(data):
            pad = hashlib.blake2b(
                self._mask_key + name.encode("utf-8") + blk_idx.to_bytes(4, "little"),
                digest_size=64,
            ).digest()
            take = min(len(data) - pos, len(pad))
            for i in range(take):
                out[pos + i] = data[pos + i] ^ pad[i]
            pos += take
            blk_idx += 1
        return bytes(out)

    def authorize(self, token: str | None) -> bool:
        return bool(token) and secrets.compare_digest(str(token), self._boot_token)

    def set_secret(self, name: str, value: str, allowed_apps: list[str] | None = None) -> dict[str, Any]:
        k = str(name).strip()
        if not k:
            raise ValueError("Secret name required")
        ct = self._xor_stream(k, str(value).encode("utf-8"))
        with self._lock:
            self._secrets[k] = {
                "ct": ct,
                "allowed_apps": list(allowed_apps or ["*"]),
                "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            }
        return {"ok": True, "name": k, "disk_bytes": 0, "allowed_apps": list(allowed_apps or ["*"])}

    def get_secret(self, name: str, app: str = "") -> dict[str, Any]:
        k = str(name).strip()
        with self._lock:
            entry = self._secrets.get(k)
            if entry is None:
                return {"ok": True, "found": False, "name": k}
            allowed = entry["allowed_apps"]
            if "*" not in allowed and app not in allowed:
                return {"ok": False, "found": False, "error": "app_not_authorized", "name": k}
            val = self._xor_stream(k, entry["ct"]).decode("utf-8")
            return {"ok": True, "found": True, "name": k, "value": val}

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {"count": len(self._secrets), "names": sorted(self._secrets.keys()), "disk_bytes": 0}
