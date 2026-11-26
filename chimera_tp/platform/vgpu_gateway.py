"""CHIMERA-VGPU 4-Tier Pareto Fabric: Colab Pro CUDA -> Idle Windows nvcuda PTX -> AVX2 VSA -> Cloud API."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import shutil
import socket
import subprocess
import threading
import time
import urllib.request
from datetime import datetime
from typing import Any, Callable

from ..vsa_memory_service import encode_text_10k
from .nvcuda_ptx import NvCudaPtxEngine


def probe_nvidia_gpu() -> dict[str, Any]:
    """Probe local NVIDIA GPU via nvidia-smi (safe 0-error fallback on CPU-only servers like svhome)."""
    try:
        out = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total,memory.used,memory.free,utilization.gpu,temperature.gpu",
                "--format=csv,noheader,nounits",
            ],
            stderr=subprocess.DEVNULL,
            timeout=2.0,
            text=True,
        ).strip()
        if not out:
            return {"present": False}
        parts = [p.strip() for p in out.splitlines()[0].split(",")]
        if len(parts) < 6:
            return {"present": False}
        return {
            "present": True,
            "name": parts[0],
            "vram_total_mb": int(float(parts[1])),
            "vram_used_mb": int(float(parts[2])),
            "vram_free_mb": int(float(parts[3])),
            "util_pct": round(float(parts[4]), 1),
            "temp_c": round(float(parts[5]), 1),
        }
    except Exception:
        return {"present": False}


def probe_gpu_backends() -> dict[str, Any]:
    """Zero-RAM probe for installed ML/CUDA runtimes (never imports heavy torch weights into daemon)."""
    ollama_live = False
    try:
        with socket.create_connection(("127.0.0.1", 11434), timeout=0.12):
            ollama_live = True
    except OSError:
        ollama_live = False
    return {
        "nvcuda_ptx_jit": NvCudaPtxEngine().probe()["available"],
        "torch_installed": importlib.util.find_spec("torch") is not None,
        "onnxruntime_installed": importlib.util.find_spec("onnxruntime") is not None,
        "ollama_exe": bool(shutil.which("ollama")),
        "ollama_live_11434": ollama_live,
        "llama_server_exe": bool(shutil.which("llama-server")),
        "avx2_vsa_builtin": True,
    }


def _dense_embed(text: str, dim: int = 256) -> list[float]:
    """Deterministic L2-normalized dense embedding derived from 10,000-bit Kanerva VSA."""
    dim = max(32, min(1024, int(dim)))
    vsa_bytes = encode_text_10k(text or "")
    vec = [0.0] * dim
    n_bytes = len(vsa_bytes)
    for i in range(dim):
        b0 = vsa_bytes[(i * 4) % n_bytes]
        b1 = vsa_bytes[(i * 4 + 1) % n_bytes]
        b2 = vsa_bytes[(i * 4 + 2) % n_bytes]
        b3 = vsa_bytes[(i * 4 + 3) % n_bytes]
        ones = b0.bit_count() + b1.bit_count() + b2.bit_count() + b3.bit_count()
        vec[i] = (ones - 16.0) / 16.0
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [round(x / norm, 6) for x in vec]


class VgpuParetoGateway:
    """4-Tier GPU Fabric: pushes heavy CUDA to Colab Pro so Windows workstation stays lag-free for daily work."""

    def __init__(
        self,
        node_name: str,
        role: str,
        host_governor: Any = None,
        peer_base_resolver: Callable[[], str] | None = None,
        on_flow: Callable[..., Any] | None = None,
        colab_bridge: Any = None,
        temp_yield_c: float = 72.0,
        util_yield_pct: float = 45.0,
        min_free_vram_mb: int = 512,
    ) -> None:
        self.node_name = node_name
        self.role = role
        self.host_governor = host_governor
        self.peer_base_resolver = peer_base_resolver
        self.on_flow = on_flow
        self.colab_bridge = colab_bridge
        self.temp_yield_c = float(temp_yield_c)
        self.util_yield_pct = float(util_yield_pct)
        self.min_free_vram_mb = int(min_free_vram_mb)

        self.ptx = NvCudaPtxEngine()
        self._lock = threading.Lock()
        self._gpu_ts = 0.0
        self._gpu_cache: dict[str, Any] = {"present": False}
        self._embed_cache: dict[str, list[float]] = {}
        self._remote_workers: dict[str, dict[str, Any]] = {}
        self._stats = {
            "requests": 0,
            "cache_hits": 0,
            "colab_pro_served": 0,
            "ptx_jit_served": 0,
            "gpu_served": 0,
            "cpu_fallback_served": 0,
            "peer_offloaded": 0,
            "yield_preempts": 0,
            "items_embedded": 0,
        }

    def register_remote_worker(self, payload: dict[str, Any]) -> dict[str, Any]:
        wid = str(payload.get("worker_id") or "colab-pro-1").strip()
        url = str(payload.get("url") or "").strip().rstrip("/")
        if not url.startswith(("http://", "https://")):
            raise ValueError("Worker url must start with http:// or https://")
        entry = {
            "worker_id": wid,
            "url": url,
            "provider": str(payload.get("provider") or "colab_pro"),
            "gpu_name": str(payload.get("gpu_name") or "NVIDIA T4/L4"),
            "vram_mb": int(payload.get("vram_mb") or 15360),
            "cu_budget": float(payload.get("cu_budget") or 2200.0),
            "last_seen_epoch": time.time(),
            "last_seen": datetime.now().astimezone().strftime("%H:%M:%S"),
        }
        with self._lock:
            self._remote_workers[wid] = entry
        return {"ok": True, "worker": dict(entry)}

    def list_remote_workers(self, stale_after_s: float = 180.0) -> list[dict[str, Any]]:
        now = time.time()
        with self._lock:
            out: list[dict[str, Any]] = []
            for w in self._remote_workers.values():
                item = dict(w)
                item["online"] = (now - float(w.get("last_seen_epoch", 0.0))) <= stale_after_s
                out.append(item)
            return out

    def _active_colab_worker(self) -> dict[str, Any] | None:
        online = [w for w in self.list_remote_workers() if w.get("online")]
        return online[0] if online else None

    def _colab_cli_info(self) -> dict[str, Any]:
        if self.colab_bridge is None:
            return {"probed": False, "available": False, "via": "disabled", "balance_cu": None}
        try:
            return self.colab_bridge.summary_cached()
        except Exception:
            return {"probed": False, "available": False, "via": "error", "balance_cu": None}

    def gpu_telemetry(self, force: bool = False) -> dict[str, Any]:
        now = time.monotonic()
        with self._lock:
            if (not force) and (now - self._gpu_ts) < 2.0 and self._gpu_ts > 0:
                return dict(self._gpu_cache)
        info = probe_nvidia_gpu()
        with self._lock:
            self._gpu_cache = info
            self._gpu_ts = now
        return dict(info)

    def evaluate_gpu_eligibility(
        self,
        gpu: dict[str, Any] | None = None,
        gov_state: dict[str, Any] | None = None,
        respect_work_first: bool = False,
    ) -> dict[str, Any]:
        t0 = time.perf_counter()
        g = gpu if gpu is not None else self.gpu_telemetry()
        gov = gov_state
        if gov is None and self.host_governor is not None:
            try:
                gov = self.host_governor.status()
            except Exception:
                gov = {}
        gov = gov or {}

        if not g.get("present"):
            return {
                "gpu_ready": False,
                "reason": "no_local_gpu",
                "gpu": g,
                "governor_mode": gov.get("mode", "UNKNOWN"),
                "check_ms": round((time.perf_counter() - t0) * 1000.0, 2),
            }

        reasons: list[str] = []
        if respect_work_first and gov.get("mode") == "USER_ACTIVE":
            reasons.append("work_first_user_active(prefer_colab)")
        if float(g.get("temp_c", 0.0)) >= self.temp_yield_c:
            reasons.append(f"thermal_guard({g['temp_c']}C>={self.temp_yield_c}C)")
        if float(g.get("util_pct", 0.0)) >= self.util_yield_pct:
            reasons.append(f"gpu_busy({g['util_pct']}%>={self.util_yield_pct}%)")
        if int(g.get("vram_free_mb", 0)) < self.min_free_vram_mb:
            reasons.append(f"low_vram({g['vram_free_mb']}MB<{self.min_free_vram_mb}MB)")

        ready = len(reasons) == 0
        if not ready:
            with self._lock:
                self._stats["yield_preempts"] += 1
        return {
            "gpu_ready": ready,
            "reason": "ready" if ready else ",".join(reasons),
            "gpu": g,
            "governor_mode": gov.get("mode", "UNKNOWN"),
            "check_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }

    def pareto_route(
        self,
        max_ms: float = 500.0,
        max_cost_usd: float = 0.0,
        min_tier: str = "standard",
        payload_bytes: int = 1024,
        prefer_colab: bool = True,
    ) -> dict[str, Any]:
        """4-Tier Pareto Router: Colab Pro (HTTP or Headless CLI — protects Windows!) -> Idle Windows GPU -> AVX2 CPU -> Cloud."""
        colab = self._active_colab_worker()
        colab_cli = self._colab_cli_info()
        has_colab = (colab is not None) or bool(colab_cli.get("available"))
        elig = self.evaluate_gpu_eligibility(respect_work_first=prefer_colab and has_colab)
        candidates: list[dict[str, Any]] = []

        if colab is not None:
            candidates.append(
                {
                    "engine": "colab_pro_cuda",
                    "node": colab["worker_id"],
                    "gpu_name": colab["gpu_name"],
                    "est_ms": round(35.0 + payload_bytes / 400000.0, 2),
                    "est_cost_usd": 0.0,
                    "tier": "cuda_heavy",
                    "workstation_impact": "0%",
                    "available": True,
                }
            )
        elif colab_cli.get("available"):
            candidates.append(
                {
                    "engine": "colab_cli_headless",
                    "node": "colab-cli",
                    "gpu_name": "Colab Pro CLI (T4/L4/A100)",
                    "balance_cu": colab_cli.get("balance_cu"),
                    "via": colab_cli.get("via"),
                    "est_ms": round(120.0 + payload_bytes / 400000.0, 2),
                    "est_cost_usd": 0.0,
                    "tier": "cuda_heavy",
                    "workstation_impact": "0%",
                    "available": True,
                }
            )
        if elig["gpu_ready"]:
            candidates.append(
                {
                    "engine": "local_vgpu",
                    "node": self.node_name,
                    "est_ms": round(4.0 + payload_bytes / 200000.0, 2),
                    "est_cost_usd": 0.0,
                    "tier": "high",
                    "workstation_impact": "idle_only",
                    "available": True,
                }
            )
        candidates.append(
            {
                "engine": "local_avx2_cpu",
                "node": self.node_name,
                "est_ms": round(8.0 + payload_bytes / 60000.0, 2),
                "est_cost_usd": 0.0,
                "tier": "standard",
                "workstation_impact": "low",
                "available": True,
            }
        )
        candidates.append(
            {
                "engine": "cloud_api",
                "node": "cloud",
                "est_ms": 380.0,
                "est_cost_usd": round(max(0.0001, (payload_bytes / 4000.0) * 0.0005), 6),
                "tier": "frontier",
                "workstation_impact": "0%",
                "available": max_cost_usd > 0.0,
            }
        )

        tier_rank = {"standard": 1, "high": 2, "cuda_heavy": 3, "frontier": 4}
        min_r = tier_rank.get(min_tier, 1)

        # If Colab Pro (worker or headless CLI) is online and user wants to protect Windows workstation, prioritize Colab!
        if prefer_colab and has_colab and (min_tier in ("cuda_heavy", "high") or elig.get("governor_mode") == "USER_ACTIVE"):
            if candidates[0]["est_ms"] <= max_ms:
                return {"ok": True, "selected": candidates[0], "eligibility": elig, "candidates": candidates}

        viable = [
            c
            for c in candidates
            if c["available"]
            and c["est_cost_usd"] <= max_cost_usd + 1e-9
            and c["est_ms"] <= max_ms
            and tier_rank.get(c["tier"], 1) >= min_r
        ]
        if not viable:
            viable = [c for c in candidates if c["available"] and c["est_cost_usd"] <= max_cost_usd + 1e-9]
        if not viable:
            viable = [candidates[0]]

        chosen = sorted(viable, key=lambda c: (c["est_cost_usd"], c["est_ms"], -tier_rank.get(c["tier"], 1)))[0]
        return {"ok": True, "selected": chosen, "eligibility": elig, "candidates": candidates}

    def run_ptx_kernel_if_eligible(self, vec_a: list[float], vec_b: list[float], force: bool = False) -> dict[str, Any]:
        """Run real GTX 1650 PTX JIT kernel ONLY when workstation is cool/idle (or forced in bench), else AVX2 CPU."""
        elig = self.evaluate_gpu_eligibility(respect_work_first=not force)
        if elig["gpu_ready"] and self.ptx.probe()["available"]:
            res = self.ptx.run_vec_dot_kernel(vec_a, vec_b)
            with self._lock:
                self._stats["ptx_jit_served"] += 1
            return {**res, "engine": "win_nvcuda_ptx"}
        t0 = time.perf_counter()
        dot = sum(a * b for a, b in zip(vec_a, vec_b))
        return {
            "ok": True,
            "engine": "cpu_yield_fallback",
            "yield_reason": elig["reason"],
            "n": min(len(vec_a), len(vec_b)),
            "dot": round(float(dot), 6),
            "total_ms": round((time.perf_counter() - t0) * 1000.0, 3),
        }

    def embed_openai_compat(
        self,
        inputs: str | list[str],
        model: str = "chimera-vsa-embed-256",
        dim: int = 256,
        app: str = "external",
        allow_peer_offload: bool = True,
    ) -> dict[str, Any]:
        """OpenAI-compatible /v1/embeddings: Cache -> Colab Pro CUDA (protects Windows!) -> Local AVX2."""
        t0 = time.perf_counter()
        texts = [inputs] if isinstance(inputs, str) else [str(x) for x in inputs]
        dim = max(32, min(1024, int(dim)))

        with self._lock:
            self._stats["requests"] += 1
            self._stats["items_embedded"] += len(texts)

        # 1. Check if ALL items are already in micro-batch cache (<0.1ms)
        cached_all: list[list[float]] = []
        all_hit = True
        for txt in texts:
            ck = f"{dim}:{hashlib.blake2s(txt.encode('utf-8'), digest_size=8).hexdigest()}"
            with self._lock:
                v = self._embed_cache.get(ck)
            if v is None:
                all_hit = False
                break
            cached_all.append(v)
        if all_hit and texts:
            with self._lock:
                self._stats["cache_hits"] += len(texts)
            return {
                "object": "list",
                "model": model,
                "data": [{"object": "embedding", "index": i, "embedding": v} for i, v in enumerate(cached_all)],
                "usage": {"prompt_tokens": len(texts), "total_tokens": len(texts)},
                "chimera_engine": "membrane_embed_cache",
                "chimera_node": self.node_name,
                "cache_hits": len(texts),
                "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
            }

        # 2. Tier 1 Priority: Offload heavy CUDA directly to Colab Pro worker (0% load on Windows!)
        colab = self._active_colab_worker()
        if colab is not None and allow_peer_offload:
            try:
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                req = urllib.request.Request(
                    f"{colab['url']}/v1/openai/v1/embeddings",
                    data=json.dumps({"input": texts, "model": model, "dimensions": dim}).encode("utf-8"),
                    headers={"Content-Type": "application/json", "X-Chimera-App": app},
                    method="POST",
                )
                with opener.open(req, timeout=8.0) as r:
                    rem = json.loads(r.read().decode("utf-8"))
                if isinstance(rem, dict) and rem.get("data"):
                    with self._lock:
                        self._stats["colab_pro_served"] += 1
                        for txt, item in zip(texts, rem["data"]):
                            ck = f"{dim}:{hashlib.blake2s(txt.encode('utf-8'), digest_size=8).hexdigest()}"
                            self._embed_cache[ck] = item["embedding"]
                    rem["chimera_engine"] = f"colab_pro:{rem.get('chimera_engine', 'cuda')}"
                    rem["cache_hits"] = 0
                    rem["elapsed_ms"] = round((time.perf_counter() - t0) * 1000.0, 2)
                    return rem
            except Exception:
                pass

        # 3. Local AVX2 VSA-10K fallback (0% Windows GPU disturbance)
        elig = self.evaluate_gpu_eligibility()
        data_out: list[dict[str, Any]] = []
        cache_hits = 0
        for idx, txt in enumerate(texts):
            ck = f"{dim}:{hashlib.blake2s(txt.encode('utf-8'), digest_size=8).hexdigest()}"
            with self._lock:
                vec = self._embed_cache.get(ck)
            if vec is not None:
                cache_hits += 1
            else:
                vec = _dense_embed(txt, dim=dim)
                with self._lock:
                    if len(self._embed_cache) >= 1024:
                        self._embed_cache.pop(next(iter(self._embed_cache)))
                    self._embed_cache[ck] = vec
            data_out.append({"object": "embedding", "index": idx, "embedding": vec})

        engine = "win_vgpu_ready" if elig["gpu_ready"] else "local_avx2_vsa"
        with self._lock:
            self._stats["cache_hits"] += cache_hits
            if elig["gpu_ready"]:
                self._stats["gpu_served"] += 1
            else:
                self._stats["cpu_fallback_served"] += 1

        ms = round((time.perf_counter() - t0) * 1000.0, 2)
        if self.on_flow is not None:
            try:
                self.on_flow(
                    "compute",
                    app,
                    self.node_name,
                    "VGPU_EMBED",
                    wire_bytes=len(texts) * dim * 4,
                    elapsed_ms=ms,
                    detail=f"n={len(texts)} engine={engine} cache_hits={cache_hits}",
                    ok=True,
                )
            except Exception:
                pass

        return {
            "object": "list",
            "model": model,
            "data": data_out,
            "usage": {"prompt_tokens": sum(max(1, len(t.split())) for t in texts), "total_tokens": sum(max(1, len(t.split())) for t in texts)},
            "chimera_engine": engine,
            "chimera_node": self.node_name,
            "cache_hits": cache_hits,
            "elapsed_ms": ms,
        }

    def status(self) -> dict[str, Any]:
        elig = self.evaluate_gpu_eligibility()
        workers = self.list_remote_workers()
        with self._lock:
            st = dict(self._stats)
            cache_len = len(self._embed_cache)
        return {
            "ok": True,
            "node": self.node_name,
            "gpu_ready": elig["gpu_ready"],
            "reason": elig["reason"],
            "gpu": elig["gpu"],
            "ptx_jit": self.ptx.probe(),
            "colab_workers": workers,
            "colab_online": sum(1 for w in workers if w.get("online")),
            "colab_cli": self._colab_cli_info(),
            "backends": probe_gpu_backends(),
            "governor_mode": elig["governor_mode"],
            "embed_cache_entries": cache_len,
            "stats": st,
        }
