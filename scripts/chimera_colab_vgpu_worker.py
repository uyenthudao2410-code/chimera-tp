"""1-File Colab Pro / Ultra CUDA Worker for CHIMERA-VGPU (offloads heavy GPU compute away from Windows)."""

from __future__ import annotations

import hashlib
import http.server
import json
import math
import os
import threading
import time
import urllib.request
from typing import Any


def _detect_colab_gpu() -> dict[str, Any]:
    try:
        import torch

        if torch.cuda.is_available():
            props = torch.cuda.get_device_properties(0)
            return {
                "cuda": True,
                "gpu_name": torch.cuda.get_device_name(0),
                "vram_mb": int(props.total_memory // (1024 * 1024)),
                "torch": torch.__version__,
            }
    except Exception:
        pass
    return {"cuda": False, "gpu_name": "cpu-fallback", "vram_mb": 0, "torch": "none"}


def _cuda_embed_batch(texts: list[str], dim: int = 256) -> tuple[list[list[float]], str, float]:
    t0 = time.perf_counter()
    try:
        import torch

        device = "cuda" if torch.cuda.is_available() else "cpu"
        # Fast deterministic projection matrix on CUDA silicon (T4 / L4 / A100)
        rows = []
        for txt in texts:
            raw = hashlib.blake2b(txt.encode("utf-8"), digest_size=64).digest()
            vals = [(b - 127.5) / 127.5 for b in raw]
            rows.append(vals)
        x = torch.tensor(rows, dtype=torch.float32, device=device)
        gen = torch.Generator(device=device).manual_seed(71071)
        proj = torch.randn((64, dim), generator=gen, dtype=torch.float32, device=device)
        y = torch.matmul(x, proj)
        y = torch.nn.functional.normalize(y, p=2, dim=1)
        if device == "cuda":
            torch.cuda.synchronize()
        out = [[round(float(v), 6) for v in row] for row in y.cpu().tolist()]
        return out, f"colab_pro_{device}", round((time.perf_counter() - t0) * 1000.0, 3)
    except Exception:
        out = []
        for txt in texts:
            raw = hashlib.blake2b(txt.encode("utf-8"), digest_size=64).digest()
            vec = [((raw[i % 64] ^ (i & 255)) - 127.5) / 127.5 for i in range(dim)]
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            out.append([round(v / norm, 6) for v in vec])
        return out, "colab_cpu_fallback", round((time.perf_counter() - t0) * 1000.0, 3)


def serve_colab_worker(
    host: str = "0.0.0.0",
    port: int = 9795,
    public_url: str = "",
    chimera_anchor: str = "",
    worker_id: str = "colab-pro-1",
    cu_budget: float = 2200.0,
) -> None:
    gpu = _detect_colab_gpu()

    class H(http.server.BaseHTTPRequestHandler):
        def _send(self, code: int, obj: dict[str, Any]) -> None:
            raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self) -> None:
            if self.path == "/health":
                self._send(200, {"ok": True, "worker_id": worker_id, "gpu": gpu, "cu_budget": cu_budget})
                return
            self._send(404, {"error": "not_found"})

        def do_POST(self) -> None:
            clen = int(self.headers.get("Content-Length", "0") or 0)
            body = json.loads(self.rfile.read(clen).decode("utf-8") or "{}") if clen > 0 else {}
            if self.path in ("/v1/openai/v1/embeddings", "/v1/vgpu/embed"):
                inp = body.get("input", "")
                texts = [inp] if isinstance(inp, str) else [str(x) for x in inp]
                dim = max(32, min(1024, int(body.get("dimensions") or 256)))
                vecs, eng, ms = _cuda_embed_batch(texts, dim=dim)
                self._send(
                    200,
                    {
                        "object": "list",
                        "model": str(body.get("model") or "chimera-colab-cuda"),
                        "data": [{"object": "embedding", "index": i, "embedding": v} for i, v in enumerate(vecs)],
                        "usage": {"prompt_tokens": len(texts), "total_tokens": len(texts)},
                        "chimera_engine": eng,
                        "chimera_worker": worker_id,
                        "gpu_name": gpu["gpu_name"],
                        "elapsed_ms": ms,
                    },
                )
                return
            self._send(404, {"error": "not_found"})

        def log_message(self, *_args: object) -> None:
            pass

    srv = http.server.ThreadingHTTPServer((host, int(port)), H)

    if chimera_anchor and public_url:
        def _register_loop() -> None:
            while True:
                try:
                    payload = json.dumps(
                        {
                            "worker_id": worker_id,
                            "url": public_url,
                            "provider": "colab_pro",
                            "gpu_name": gpu["gpu_name"],
                            "vram_mb": gpu["vram_mb"],
                            "cu_budget": cu_budget,
                        }
                    ).encode("utf-8")
                    req = urllib.request.Request(
                        f"{chimera_anchor.rstrip('/')}/v1/vgpu/workers/register",
                        data=payload,
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    urllib.request.urlopen(req, timeout=3.0).read()
                except Exception:
                    pass
                time.sleep(30.0)

        threading.Thread(target=_register_loop, daemon=True).start()

    print(f"CHIMERA Colab Pro VGPU Worker listening on http://{host}:{port} | GPU={gpu}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    serve_colab_worker(
        port=int(os.environ.get("CHIMERA_COLAB_PORT", "9795")),
        public_url=os.environ.get("CHIMERA_COLAB_PUBLIC_URL", ""),
        chimera_anchor=os.environ.get("CHIMERA_ANCHOR_URL", ""),
        worker_id=os.environ.get("CHIMERA_COLAB_WORKER_ID", "colab-pro-1"),
    )
