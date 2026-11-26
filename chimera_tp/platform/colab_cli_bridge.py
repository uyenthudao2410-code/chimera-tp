"""CHIMERA-COLAB-FABRIC: Anti-Congestion Headless Google Colab Pro/Ultra CLI Orchestrator (Zero Ngrok, Zero Manual Notebook)."""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any


ALLOWED_PROFILES: tuple[str, ...] = ("CPU", "CPU_HIGH_MEM", "T4", "L4", "A100", "G4", "H100")

RUNTIME_PROFILES: dict[str, dict[str, Any]] = {
    "CPU": {"gpu": None, "high_mem": False, "est_cu_hr": 0.07, "congestion": "none", "fallback": ["CPU"]},
    "CPU_HIGH_MEM": {"gpu": None, "high_mem": True, "est_cu_hr": 0.15, "congestion": "none", "fallback": ["CPU_HIGH_MEM", "CPU"]},
    "T4": {"gpu": "T4", "high_mem": False, "est_cu_hr": 1.17, "congestion": "low", "fallback": ["T4", "CPU_HIGH_MEM", "CPU"]},
    "L4": {"gpu": "L4", "high_mem": False, "est_cu_hr": 4.82, "congestion": "medium", "fallback": ["L4", "T4"]},
    "A100": {"gpu": "A100", "high_mem": True, "est_cu_hr": 11.77, "congestion": "high", "fallback": ["A100", "L4", "T4"]},
    "G4": {"gpu": "G4", "high_mem": False, "est_cu_hr": 9.50, "congestion": "high", "fallback": ["G4", "L4", "T4"]},
    "H100": {"gpu": "H100", "high_mem": False, "est_cu_hr": 14.00, "congestion": "high", "fallback": ["H100", "A100", "L4"]},
}

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_START_MARK = "===CHIMERA_COLAB_OUT_START==="
_END_MARK = "===CHIMERA_COLAB_OUT_END==="


def select_lightest_profile(
    task_kind: str = "cuda_embed",
    *,
    batch_size: int = 1,
    require_gpu: bool = False,
    allow_heavy_gpu: bool = False,
) -> dict[str, Any]:
    """Anti-congestion right-sizing: pick cheapest sufficient Colab runtime profile to protect CU balance."""
    tk = str(task_kind or "cuda_embed").strip().lower()
    if allow_heavy_gpu:
        prof = "A100"
        reason = "explicit_heavy_gpu_opt_in"
    elif tk in ("cuda_embed", "cuda_matmul", "whisper", "ocr"):
        if require_gpu or batch_size >= 16:
            prof = "T4"
            reason = "low_congestion_t4_optimal_for_cuda_batch"
        else:
            prof = "CPU"
            reason = "small_batch_zero_gpu_wait"
    elif tk in ("highram_verify", "build_test"):
        prof = "CPU_HIGH_MEM"
        reason = "highram_cpu_avoids_gpu_queue"
    elif tk in ("llm_large", "vllm"):
        prof = "L4"
        reason = "24gb_vram_required"
    else:
        prof = "T4" if require_gpu else "CPU"
        reason = "default_anti_congestion"

    spec = RUNTIME_PROFILES[prof]
    return {
        "profile": prof,
        "gpu": spec["gpu"],
        "high_mem": bool(spec["high_mem"]),
        "est_cu_hr": float(spec["est_cu_hr"]),
        "congestion": str(spec["congestion"]),
        "fallback_chain": list(spec["fallback"]),
        "reason": reason,
    }


def parse_usage_text(raw_text: str) -> dict[str, Any]:
    txt = _ANSI_RE.sub("", str(raw_text or ""))
    bal = re.search(r"Current balance:\s*([\d.]+)", txt, re.I)
    rate = re.search(r"Usage rate:\s*([\d.]+)", txt, re.I)
    act = re.search(r"Active assignments:\s*(\d+)", txt, re.I)
    return {
        "balance_cu": float(bal.group(1)) if bal else None,
        "usage_rate_hr": float(rate.group(1)) if rate else None,
        "active_assignments": int(act.group(1)) if act else None,
    }


def parse_marked_json(stdout_text: str) -> dict[str, Any]:
    clean = _ANSI_RE.sub("", str(stdout_text or ""))
    s = clean.find(_START_MARK)
    e = clean.find(_END_MARK, s + len(_START_MARK)) if s >= 0 else -1
    if s < 0 or e < 0:
        raise ValueError(f"Missing CHIMERA Colab markers in output. tail={clean[-400:]!r}")
    return json.loads(clean[s + len(_START_MARK) : e].strip())


# Universal, domain-agnostic Colab GPU compute payload executed headlessly via `colab exec -f`
_UNIVERSAL_COLAB_RUNNER = r'''
import base64, hashlib, json, math, os, platform, shutil, time
from pathlib import Path

REQ = json.loads(base64.b64decode("__REQ_B64__").decode("utf-8"))

def probe_hw():
    ram_gb = 0.0
    try:
        for ln in Path("/proc/meminfo").read_text(encoding="utf-8", errors="ignore").splitlines():
            if ln.startswith("MemTotal:"):
                ram_gb = round(float(ln.split()[1]) / (1024.0 * 1024.0), 2)
                break
    except Exception:
        pass
    has_gpu, gpu_name, vram_gb = False, "cpu-only", 0.0
    try:
        import torch
        has_gpu = bool(torch.cuda.is_available())
        if has_gpu:
            gpu_name = str(torch.cuda.get_device_name(0))
            vram_gb = round(torch.cuda.get_device_properties(0).total_memory / (1024.0 ** 3), 2)
    except Exception:
        pass
    return {
        "hostname": platform.node(),
        "python": platform.python_version(),
        "cpu_count": os.cpu_count() or 1,
        "ram_gb": ram_gb,
        "has_gpu": has_gpu,
        "gpu_name": gpu_name,
        "vram_gb": vram_gb,
    }

def run_task(req, hw):
    t0 = time.perf_counter()
    kind = str(req.get("task_kind") or "cuda_embed").lower()
    if kind == "probe":
        return {"ok": True, "task_kind": kind, "hw": hw, "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2)}

    if kind == "cuda_embed":
        texts = [str(x) for x in (req.get("texts") or [])]
        dim = max(32, min(1024, int(req.get("dim") or 256)))
        try:
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"
            rows = [[(b - 127.5) / 127.5 for b in hashlib.blake2b(t.encode("utf-8"), digest_size=64).digest()] for t in texts]
            x = torch.tensor(rows, dtype=torch.float32, device=device)
            gen = torch.Generator(device=device).manual_seed(71071)
            proj = torch.randn((64, dim), generator=gen, dtype=torch.float32, device=device)
            y = torch.nn.functional.normalize(torch.matmul(x, proj), p=2, dim=1)
            if device == "cuda":
                torch.cuda.synchronize()
            vecs = [[round(float(v), 6) for v in row] for row in y.cpu().tolist()]
            return {
                "ok": True,
                "task_kind": kind,
                "device": device,
                "gpu_name": hw["gpu_name"],
                "count": len(vecs),
                "dim": dim,
                "embeddings": vecs,
                "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
                "hw": hw,
            }
        except Exception as exc:
            vecs = []
            for t in texts:
                raw = hashlib.blake2b(t.encode("utf-8"), digest_size=64).digest()
                vec = [((raw[i % 64] ^ (i & 255)) - 127.5) / 127.5 for i in range(dim)]
                nrm = math.sqrt(sum(v * v for v in vec)) or 1.0
                vecs.append([round(v / nrm, 6) for v in vec])
            return {"ok": True, "task_kind": kind, "device": "cpu_fallback", "note": str(exc), "count": len(vecs), "dim": dim, "embeddings": vecs, "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2), "hw": hw}

    if kind == "cuda_matmul":
        n = max(64, min(4096, int(req.get("n") or 1024)))
        import torch
        device = "cuda" if torch.cuda.is_available() else "cpu"
        a = torch.randn((n, n), dtype=torch.float32, device=device)
        b = torch.randn((n, n), dtype=torch.float32, device=device)
        if device == "cuda":
            torch.cuda.synchronize()
        tk = time.perf_counter()
        c = torch.matmul(a, b)
        if device == "cuda":
            torch.cuda.synchronize()
        kms = (time.perf_counter() - tk) * 1000.0
        gflops = round((2.0 * (n ** 3)) / max(1e-9, (kms / 1000.0)) / 1e9, 2)
        return {
            "ok": True,
            "task_kind": kind,
            "device": device,
            "gpu_name": hw["gpu_name"],
            "n": n,
            "kernel_ms": round(kms, 3),
            "gflops": gflops,
            "checksum": round(float(c[0, 0].item()), 5),
            "hw": hw,
        }

    return {"ok": False, "error": f"unsupported_task_kind:{kind}", "hw": hw}

hw = probe_hw()
res = run_task(REQ, hw)
print("===CHIMERA_COLAB_OUT_START===")
print(json.dumps(res, ensure_ascii=False))
print("===CHIMERA_COLAB_OUT_END===")
'''


class ColabCliBridge:
    """Headless Google Colab Pro/Ultra CLI orchestrator with WebSocket-SSH tunnel & CU-leak guard."""

    def __init__(
        self,
        state_dir: Path,
        *,
        colab_bin: str | None = None,
        peer_base_resolver: Any = None,
        idle_ttl_s: float = 180.0,
        reaper_interval_s: float = 5.0,
    ) -> None:
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.sessions_config_path = self.state_dir / "chimera_colab_sessions.json"
        self._colab_bin_override = colab_bin
        self.peer_base_resolver = peer_base_resolver
        self._lock = threading.Lock()
        self._session_locks: dict[str, threading.Lock] = {}
        self._status_cache: tuple[float, dict[str, Any]] | None = None
        self._tunnels: dict[str, dict[str, Any]] = {}
        self._managed_sessions: dict[str, dict[str, Any]] = {}
        self._exec_count = 0
        self._warm_hits = 0
        self._auto_reaped_count = 0
        self._scaling_now = False
        self._reaper_interval_s = max(0.05, float(reaper_interval_s))
        self._stop_ev = threading.Event()
        self._reaper_wake = threading.Event()
        self._reaper_thread: threading.Thread | None = None
        self._policy_path = self.state_dir / "auto_policy.json"
        self.policy: dict[str, Any] = {
            "enabled": True,
            "idle_ttl_s": max(1.0, float(idle_ttl_s)),
            "auto_min_batch": 16,
            "protect_workstation": True,
            "warm_session_reuse": True,
            "default_gpu_profile": "T4",
        }
        self._load_policy()

    def _load_policy(self) -> None:
        try:
            if self._policy_path.is_file():
                raw = json.loads(self._policy_path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    for k in ("enabled", "protect_workstation", "warm_session_reuse"):
                        if k in raw:
                            self.policy[k] = bool(raw[k])
                    if "idle_ttl_s" in raw:
                        self.policy["idle_ttl_s"] = max(0.2, float(raw["idle_ttl_s"]))
                    if "auto_min_batch" in raw:
                        self.policy["auto_min_batch"] = max(1, int(raw["auto_min_batch"]))
                    if "default_gpu_profile" in raw and str(raw["default_gpu_profile"]).upper() in ALLOWED_PROFILES:
                        self.policy["default_gpu_profile"] = str(raw["default_gpu_profile"]).upper()
        except Exception:
            pass

    def get_policy(self) -> dict[str, Any]:
        with self._lock:
            return dict(self.policy)

    def update_policy(self, patch: dict[str, Any], persist: bool = True) -> dict[str, Any]:
        with self._lock:
            for k in ("enabled", "protect_workstation", "warm_session_reuse"):
                if k in patch:
                    self.policy[k] = bool(patch[k])
            if "idle_ttl_s" in patch:
                self.policy["idle_ttl_s"] = max(0.2, float(patch["idle_ttl_s"]))
            if "auto_min_batch" in patch:
                self.policy["auto_min_batch"] = max(1, int(patch["auto_min_batch"]))
            if "default_gpu_profile" in patch:
                prof = str(patch["default_gpu_profile"]).strip().upper()
                if prof not in ALLOWED_PROFILES:
                    raise ValueError(f"Unsupported default_gpu_profile: {prof!r}")
                self.policy["default_gpu_profile"] = prof
            snap = dict(self.policy)
        if persist:
            try:
                self._policy_path.write_text(json.dumps(snap, indent=2), encoding="utf-8")
            except Exception:
                pass
        self._reaper_wake.set()
        return snap

    def _get_session_lock(self, session_name: str) -> threading.Lock:
        with self._lock:
            lk = self._session_locks.get(session_name)
            if lk is None:
                lk = threading.Lock()
                self._session_locks[session_name] = lk
            return lk

    def start_autonomous(self, ephemeral: bool = False) -> "ColabCliBridge":
        """Start background warm-discovery & autonomous CU-guard Idle-Reaper thread (0ms boot block)."""
        self._stop_ev.clear()
        if self._reaper_thread is None or not self._reaper_thread.is_alive():
            self._reaper_thread = threading.Thread(
                target=self._idle_reaper_loop,
                name="chimera-colab-reaper",
                daemon=True,
            )
            self._reaper_thread.start()
        if not ephemeral:
            def _bg_probe() -> None:
                try:
                    self.status(refresh=True)
                except Exception:
                    pass

            threading.Thread(target=_bg_probe, name="chimera-colab-probe", daemon=True).start()
        return self

    def _idle_reaper_loop(self) -> None:
        while not self._stop_ev.is_set():
            with self._lock:
                ttl = float(self.policy.get("idle_ttl_s", 180.0))
            wait_s = min(self._reaper_interval_s, max(0.05, ttl / 2.0))
            self._reaper_wake.wait(wait_s)
            self._reaper_wake.clear()
            if self._stop_ev.is_set():
                break
            try:
                self.reap_idle_sessions()
            except Exception:
                pass

    def reap_idle_sessions(self) -> list[str]:
        """Auto-stop any managed Colab session that has exceeded idle_ttl_s -> guarantees 0 CU/hr when idle."""
        now = time.monotonic()
        expired: list[str] = []
        with self._lock:
            for sname, info in list(self._managed_sessions.items()):
                ttl = float(info.get("idle_ttl_s") or self.policy["idle_ttl_s"])
                if (now - float(info.get("last_used_at", now))) >= ttl and not info.get("in_flight", False):
                    expired.append(sname)
        reaped: list[str] = []
        for sname in expired:
            lk = self._get_session_lock(sname)
            if not lk.acquire(blocking=False):
                continue
            try:
                with self._lock:
                    info = self._managed_sessions.get(sname)
                    if info is None or info.get("in_flight", False):
                        continue
                    ttl = float(info.get("idle_ttl_s") or self.policy["idle_ttl_s"])
                    if (time.monotonic() - float(info.get("last_used_at", 0.0))) < ttl:
                        continue
                    self._managed_sessions.pop(sname, None)
                self.stop_session(sname)
                with self._lock:
                    self._auto_reaped_count += 1
                reaped.append(sname)
            finally:
                lk.release()
        return reaped

    def autonomous_state(self) -> dict[str, Any]:
        now = time.monotonic()
        with self._lock:
            pol = dict(self.policy)
            scaling = self._scaling_now
            reaped = self._auto_reaped_count
            warm_hits = self._warm_hits
            execs = self._exec_count
            managed = []
            for sname, info in self._managed_sessions.items():
                ttl = float(info.get("idle_ttl_s") or pol["idle_ttl_s"])
                rem = max(0.0, round(ttl - (now - float(info.get("last_used_at", now))), 1))
                managed.append(
                    {
                        "session": sname,
                        "profile": info.get("profile", "?"),
                        "uses": int(info.get("uses", 0)),
                        "in_flight": bool(info.get("in_flight", False)),
                        "idle_remaining_s": rem,
                    }
                )
        if not pol.get("enabled", True):
            mode_label = "MANUAL"
        elif scaling:
            mode_label = "AUTO:SCALING"
        elif managed:
            top = managed[0]
            mode_label = f"AUTO:WARM:{top['profile']}({int(top['idle_remaining_s'])}s)"
        else:
            mode_label = "AUTO:SLEEP"
        return {
            "mode_label": mode_label,
            "policy": pol,
            "managed_sessions": managed,
            "warm_reuses": warm_hits,
            "auto_reaped": reaped,
            "executions": execs,
        }

    def find_colab_bin(self) -> str | None:
        if self._colab_bin_override and Path(self._colab_bin_override).is_file():
            return self._colab_bin_override
        for env_key in ("CHIMERA_COLAB_CLI_BIN", "RADAR_COLAB_CLI_BIN"):
            val = os.environ.get(env_key, "").strip()
            if val and Path(val).is_file():
                return val
        on_path = shutil.which("colab")
        if on_path:
            return on_path
        exe = "colab.exe" if os.name == "nt" else "colab"
        py_bin = Path(sys.executable).resolve().parent
        candidates = [
            py_bin / exe,
            Path.home() / ".local" / "bin" / exe,
            Path.home() / "DEV" / "radar_dashboard" / ".venv" / ("Scripts" if os.name == "nt" else "bin") / exe,
        ]
        for cand in candidates:
            if cand.is_file():
                return str(cand)
        return None

    def _run_colab(
        self,
        args: list[str],
        *,
        timeout: int = 180,
        check: bool = True,
        extra_env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        cbin = self.find_colab_bin()
        if not cbin:
            raise FileNotFoundError("Google Colab CLI (`colab`) not found on this node")
        cmd = [cbin, "--config", str(self.sessions_config_path), *args]
        env = os.environ.copy()
        env.setdefault("PYTHONUTF8", "1")
        if extra_env:
            env.update(extra_env)
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env,
        )
        if check and proc.returncode != 0:
            raise RuntimeError(f"colab {' '.join(args)} failed ({proc.returncode}): {(proc.stderr or proc.stdout)[-400:]}")
        return proc

    @staticmethod
    def build_new_command(session_name: str, profile: str) -> list[str]:
        prof = str(profile or "CPU").strip().upper()
        if prof not in ALLOWED_PROFILES:
            raise ValueError(f"Unsupported Colab profile: {profile!r}")
        args = ["new", "-s", str(session_name)]
        if prof not in ("CPU", "CPU_HIGH_MEM"):
            args.extend(["--gpu", prof])
        if prof in ("CPU_HIGH_MEM", "A100"):
            args.append("--high-mem")
        return args

    def get_usage(self) -> dict[str, Any]:
        cbin = self.find_colab_bin()
        if not cbin:
            return {"available": False, "cli_path": None, "balance_cu": None, "usage_rate_hr": None, "active_assignments": None}
        try:
            res = self._run_colab(["usage"], timeout=25, check=False)
            parsed = parse_usage_text((res.stdout or "") + "\n" + (res.stderr or ""))
            return {
                "available": res.returncode == 0 and parsed["balance_cu"] is not None,
                "cli_path": cbin,
                **parsed,
                "rc": res.returncode,
            }
        except Exception as exc:
            return {"available": False, "cli_path": cbin, "error": str(exc)}

    def list_sessions(self) -> dict[str, Any]:
        cbin = self.find_colab_bin()
        if not cbin:
            return {"ok": False, "sessions": []}
        try:
            res = self._run_colab(["sessions"], timeout=20, check=False)
            raw = _EMAIL_RE.sub(
                "[redacted-email]",
                _ANSI_RE.sub("", (res.stdout or "") + "\n" + (res.stderr or "")).strip(),
            )
            names: list[str] = []
            if "no active sessions" not in raw.lower():
                for ln in raw.splitlines():
                    s = ln.strip()
                    if not s or s.lower().startswith("[colab]"):
                        continue
                    for m in re.findall(r"\[([A-Za-z0-9_.:-]+)\]", s):
                        if m.lower() != "colab" and m not in names:
                            names.append(m)
                    if not names and re.match(r"^[A-Za-z0-9_.-]+\s+\|", s):
                        cand = s.split("|", 1)[0].strip()
                        if cand.lower() not in ("name", "session", "id") and cand not in names:
                            names.append(cand)
            return {"ok": res.returncode == 0, "sessions": names, "raw": raw[:400]}
        except Exception as exc:
            return {"ok": False, "sessions": [], "error": str(exc)}

    def summary_cached(self) -> dict[str, Any]:
        """Fast 0-ms cached summary (never spawns subprocesses or network during daemon boot / unit tests)."""
        auto_st = self.autonomous_state()
        if self._status_cache is not None:
            snap = self._status_cache[1]
            usage = snap.get("usage") or {}
            sess = snap.get("sessions") or {}
            return {
                "probed": True,
                "available": bool(usage.get("available")),
                "via": str(snap.get("via") or "unavailable"),
                "balance_cu": usage.get("balance_cu"),
                "usage_rate_hr": usage.get("usage_rate_hr"),
                "active_assignments": usage.get("active_assignments"),
                "active_sessions": list(sess.get("sessions") or []),
                "executions": self._exec_count,
                "autonomous": auto_st,
            }
        return {
            "probed": False,
            "available": False,
            "cli_found": self.find_colab_bin() is not None,
            "via": "unprobed",
            "balance_cu": None,
            "usage_rate_hr": None,
            "active_assignments": None,
            "active_sessions": [],
            "executions": self._exec_count,
            "autonomous": auto_st,
        }

    def status(self, refresh: bool = False) -> dict[str, Any]:
        now = time.monotonic()
        if (not refresh) and self._status_cache is not None and (now - self._status_cache[0]) < 120.0:
            return dict(self._status_cache[1])
        cbin = self.find_colab_bin()
        if cbin:
            usage = self.get_usage()
            sess = self.list_sessions()
            snap = {
                "ok": True,
                "local_cli_found": True,
                "cli_path": cbin,
                "via": "local_colab_cli",
                "usage": usage,
                "sessions": sess,
                "active_tunnels": list(self._tunnels.keys()),
                "executions": self._exec_count,
                "autonomous": self.autonomous_state(),
                "anti_congestion_order": ["CPU", "CPU_HIGH_MEM", "T4", "L4", "A100"],
            }
            self._status_cache = (now, snap)
            return dict(snap)

        # Transparently query peer node (e.g. win-desktop queries svhome's authenticated Colab CLI!)
        if self.peer_base_resolver is not None:
            try:
                pbase = (self.peer_base_resolver() or "").rstrip("/")
                if pbase:
                    q = "?refresh=1" if refresh else ""
                    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                    with opener.open(f"{pbase}/v1/vgpu/colab/status{q}", timeout=8.0) as r:
                        rem = json.loads(r.read().decode("utf-8"))
                    if isinstance(rem, dict) and rem.get("local_cli_found"):
                        rem["via"] = f"peer_relay:{pbase}"
                        self._status_cache = (now, rem)
                        return dict(rem)
            except Exception:
                pass

        return {
            "ok": True,
            "local_cli_found": False,
            "cli_path": None,
            "via": "unavailable",
            "usage": {"available": False, "balance_cu": None},
            "sessions": {"ok": False, "sessions": []},
            "active_tunnels": [],
            "executions": self._exec_count,
        }

    def ensure_session(self, session_name: str, profile: str = "T4", fallback_chain: list[str] | None = None) -> dict[str, Any]:
        sess_info = self.list_sessions()
        if session_name in set(sess_info.get("sessions") or []):
            return {"ok": True, "session": session_name, "profile_used": profile, "reused": True, "attempts": []}

        req_prof = str(profile or "CPU").strip().upper()
        if req_prof not in ALLOWED_PROFILES:
            raise ValueError(f"Unsupported profile: {profile!r}")
        raw_chain = [req_prof] + list(fallback_chain or RUNTIME_PROFILES[req_prof]["fallback"])
        candidates = [c for c in dict.fromkeys(str(x).strip().upper() for x in raw_chain) if c in ALLOWED_PROFILES]

        attempts: list[dict[str, Any]] = []
        last_err = ""
        for idx, cand in enumerate(candidates):
            cmd = self.build_new_command(session_name, cand)
            retries = "1" if idx == len(candidates) - 1 else "0"
            try:
                self._run_colab(cmd, timeout=150, check=True, extra_env={"COLAB_CLI_ASSIGN_RETRIES": retries})
                attempts.append({"profile": cand, "ok": True})
                return {"ok": True, "session": session_name, "profile_used": cand, "reused": False, "attempts": attempts}
            except Exception as exc:
                last_err = str(exc)
                attempts.append({"profile": cand, "ok": False, "error": last_err[-200:]})
                if idx + 1 < len(candidates):
                    time.sleep(1.0)
        raise RuntimeError(f"Failed provisioning Colab session {session_name!r} across {candidates}: {last_err}")

    def stop_session(self, session_name: str) -> dict[str, Any]:
        with self._lock:
            t_info = self._tunnels.pop(session_name, None)
            if t_info and t_info.get("proc") is not None:
                try:
                    t_info["proc"].terminate()
                except Exception:
                    pass
        if not self.find_colab_bin():
            if self.peer_base_resolver is not None:
                pbase = (self.peer_base_resolver() or "").rstrip("/")
                if pbase:
                    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                    req = urllib.request.Request(
                        f"{pbase}/v1/vgpu/colab/stop",
                        data=json.dumps({"session": session_name}).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    with opener.open(req, timeout=30.0) as r:
                        return json.loads(r.read().decode("utf-8"))
            return {"ok": False, "error": "colab_cli_not_found"}
        res = self._run_colab(["stop", "-s", str(session_name)], timeout=60, check=False)
        self._status_cache = None
        return {
            "ok": res.returncode == 0,
            "session": session_name,
            "rc": res.returncode,
            "output": _ANSI_RE.sub("", (res.stdout or "") + "\n" + (res.stderr or "")).strip()[:240],
        }

    def exec_task(
        self,
        task_kind: str = "cuda_embed",
        payload: dict[str, Any] | None = None,
        *,
        profile: str | None = None,
        session_name: str | None = None,
        keep_session: bool = False,
        require_gpu: bool = False,
        allow_heavy_gpu: bool = False,
    ) -> dict[str, Any]:
        """Run a headless compute/CUDA task on Colab Pro/Ultra via `colab exec -f`, auto-stopping to guard CU."""
        # If local node lacks colab CLI (e.g. win-desktop), transparently delegate to svhome over PHANTOM-5MS!
        if not self.find_colab_bin():
            if self.peer_base_resolver is not None:
                pbase = (self.peer_base_resolver() or "").rstrip("/")
                if pbase:
                    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                    req = urllib.request.Request(
                        f"{pbase}/v1/vgpu/colab/exec",
                        data=json.dumps(
                            {
                                "task_kind": task_kind,
                                "payload": payload or {},
                                "profile": profile,
                                "session": session_name,
                                "keep_session": keep_session,
                                "require_gpu": require_gpu,
                                "allow_heavy_gpu": allow_heavy_gpu,
                            },
                            ensure_ascii=False,
                        ).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    with opener.open(req, timeout=240.0) as r:
                        rem = json.loads(r.read().decode("utf-8"))
                    rem["relayed_via"] = pbase
                    return rem
            raise FileNotFoundError("Google Colab CLI (`colab`) not found locally or on peer")

        pl = dict(payload or {})
        batch_sz = len(pl.get("texts") or []) if isinstance(pl.get("texts"), list) else 1
        rt_sel = select_lightest_profile(
            task_kind, batch_size=batch_sz, require_gpu=require_gpu, allow_heavy_gpu=allow_heavy_gpu
        )
        chosen_prof = str(profile or rt_sel["profile"]).strip().upper()
        sess = str(session_name or f"chimera_{chosen_prof.lower()}")

        prov = self.ensure_session(sess, profile=chosen_prof, fallback_chain=rt_sel["fallback_chain"])
        tmp_script: Path | None = None
        stopped = False
        try:
            req_obj = {"task_kind": task_kind, **pl}
            req_b64 = base64.b64encode(json.dumps(req_obj, ensure_ascii=False).encode("utf-8")).decode("ascii")
            src = _UNIVERSAL_COLAB_RUNNER.replace("__REQ_B64__", req_b64)
            with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as tf:
                tf.write(src)
                tmp_script = Path(tf.name)

            exec_res = self._run_colab(["exec", "--timeout", "300", "-s", sess, "-f", str(tmp_script)], timeout=340)
            parsed = parse_marked_json((exec_res.stdout or "") + "\n" + (exec_res.stderr or ""))
            self._exec_count += 1
        finally:
            if tmp_script is not None:
                tmp_script.unlink(missing_ok=True)
            if not keep_session:
                st_stop = self.stop_session(sess)
                stopped = bool(st_stop.get("ok"))

        return {
            "ok": bool(parsed.get("ok")),
            "session": sess,
            "profile_requested": chosen_prof,
            "profile_used": prov.get("profile_used", chosen_prof),
            "reused_session": bool(prov.get("reused")),
            "auto_stopped_cu_guard": stopped,
            "workstation_gpu_impact": "0%",
            "result": parsed,
        }

    def auto_execute(
        self,
        task_kind: str = "cuda_embed",
        payload: dict[str, Any] | None = None,
        *,
        profile: str | None = None,
        require_gpu: bool = True,
        allow_heavy_gpu: bool = False,
    ) -> dict[str, Any]:
        """Autonomous Elastic Scale-from-Zero + Warm-Reuse + Idle-Reaper CU-Guard execution."""
        if not self.find_colab_bin():
            if self.peer_base_resolver is not None:
                pbase = (self.peer_base_resolver() or "").rstrip("/")
                if pbase:
                    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                    req = urllib.request.Request(
                        f"{pbase}/v1/vgpu/colab/auto-exec",
                        data=json.dumps(
                            {
                                "task_kind": task_kind,
                                "payload": payload or {},
                                "profile": profile,
                                "require_gpu": require_gpu,
                                "allow_heavy_gpu": allow_heavy_gpu,
                            },
                            ensure_ascii=False,
                        ).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    with opener.open(req, timeout=240.0) as r:
                        rem = json.loads(r.read().decode("utf-8"))
                    rem["relayed_via"] = pbase
                    return rem
            raise FileNotFoundError("Google Colab CLI (`colab`) not found locally or on peer")

        pol = self.get_policy()
        pl = dict(payload or {})
        batch_sz = len(pl.get("texts") or []) if isinstance(pl.get("texts"), list) else 1
        rt_sel = select_lightest_profile(
            task_kind, batch_size=batch_sz, require_gpu=require_gpu, allow_heavy_gpu=allow_heavy_gpu
        )
        chosen_prof = str(profile or rt_sel["profile"]).strip().upper()
        sess = f"chimera_auto_{chosen_prof.lower()}"
        warm_reuse = bool(pol.get("warm_session_reuse", True))
        idle_ttl = float(pol.get("idle_ttl_s", 180.0))

        lk = self._get_session_lock(sess)
        with lk:
            with self._lock:
                existing = self._managed_sessions.get(sess)
                if existing is not None:
                    existing["in_flight"] = True

            warm_hit = False
            reused = False
            prof_used = chosen_prof
            tmp_script: Path | None = None
            stopped = False
            try:
                if existing is not None and warm_reuse:
                    warm_hit = True
                    reused = True
                    prof_used = str(existing.get("profile") or chosen_prof)
                else:
                    with self._lock:
                        self._scaling_now = True
                    try:
                        prov = self.ensure_session(sess, profile=chosen_prof, fallback_chain=rt_sel["fallback_chain"])
                        reused = bool(prov.get("reused"))
                        prof_used = str(prov.get("profile_used") or chosen_prof)
                    finally:
                        with self._lock:
                            self._scaling_now = False

                req_obj = {"task_kind": task_kind, **pl}
                req_b64 = base64.b64encode(json.dumps(req_obj, ensure_ascii=False).encode("utf-8")).decode("ascii")
                src = _UNIVERSAL_COLAB_RUNNER.replace("__REQ_B64__", req_b64)
                with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as tf:
                    tf.write(src)
                    tmp_script = Path(tf.name)

                # Self-healing: if a warm Colab runtime was preempted by Google, auto-provision fresh once!
                try:
                    exec_res = self._run_colab(["exec", "--timeout", "300", "-s", sess, "-f", str(tmp_script)], timeout=340)
                except Exception:
                    if not warm_hit:
                        raise
                    warm_hit = False
                    with self._lock:
                        self._managed_sessions.pop(sess, None)
                        self._scaling_now = True
                    try:
                        prov = self.ensure_session(sess, profile=chosen_prof, fallback_chain=rt_sel["fallback_chain"])
                        prof_used = str(prov.get("profile_used") or chosen_prof)
                    finally:
                        with self._lock:
                            self._scaling_now = False
                    exec_res = self._run_colab(["exec", "--timeout", "300", "-s", sess, "-f", str(tmp_script)], timeout=340)

                parsed = parse_marked_json((exec_res.stdout or "") + "\n" + (exec_res.stderr or ""))
                now_m = time.monotonic()
                with self._lock:
                    self._exec_count += 1
                    if warm_hit:
                        self._warm_hits += 1
                    if warm_reuse:
                        prev_uses = int((self._managed_sessions.get(sess) or {}).get("uses", 0))
                        self._managed_sessions[sess] = {
                            "profile": prof_used,
                            "created_at": (self._managed_sessions.get(sess) or {}).get("created_at", now_m),
                            "last_used_at": now_m,
                            "idle_ttl_s": idle_ttl,
                            "uses": prev_uses + 1,
                            "in_flight": False,
                        }
            finally:
                if tmp_script is not None:
                    tmp_script.unlink(missing_ok=True)
                with self._lock:
                    if sess in self._managed_sessions:
                        self._managed_sessions[sess]["in_flight"] = False
                if not warm_reuse:
                    st_stop = self.stop_session(sess)
                    stopped = bool(st_stop.get("ok"))

            return {
                "ok": bool(parsed.get("ok")),
                "autonomous": True,
                "session": sess,
                "profile_requested": chosen_prof,
                "profile_used": prof_used,
                "warm_pool_hit": warm_hit,
                "reused_session": reused,
                "idle_auto_stop_s": idle_ttl if warm_reuse else 0.0,
                "auto_stopped_cu_guard": stopped,
                "workstation_gpu_impact": "0%",
                "result": parsed,
            }

    def build_ssh_tunnel_command(self, session_name: str, local_port: int, remote_port: int = 9795) -> list[str]:
        """Build cross-platform WebSocket-SSH `-L` forward command using `colab ssh --proxy-mode` (zero ngrok!)."""
        cbin = self.find_colab_bin() or "colab"
        null_hosts = "NUL" if os.name == "nt" else "/dev/null"
        proxy_cmd = f'"{cbin}" --config "{self.sessions_config_path}" ssh --proxy-mode -s {session_name}'
        return [
            "ssh",
            "-N",
            "-L",
            f"{int(local_port)}:127.0.0.1:{int(remote_port)}",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            f"UserKnownHostsFile={null_hosts}",
            "-o",
            "ExitOnForwardFailure=yes",
            "-o",
            "ServerAliveInterval=15",
            "-o",
            "ServerAliveCountMax=4",
            "-o",
            f"ProxyCommand={proxy_cmd}",
            "root@colab-runtime",
        ]

    def close(self) -> None:
        self._stop_ev.set()
        self._reaper_wake.set()
        with self._lock:
            tunnels = list(self._tunnels.values())
            self._tunnels.clear()
            managed_names = list(self._managed_sessions.keys())
            self._managed_sessions.clear()
        for info in tunnels:
            proc = info.get("proc")
            if proc is not None:
                try:
                    proc.terminate()
                except Exception:
                    pass
        for sname in managed_names:
            try:
                self.stop_session(sname)
            except Exception:
                pass
