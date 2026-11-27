"""Linux-side admission shared by all guest jobs of one account.

For an SSH worker pass its Python argv to limited_command(argv, policy), send
this source over stdin and wrap the work in reserve(DEFAULT_ROOT, policy).
assess(policy) is an advisory preflight; reserve rechecks under a kernel lock
and verifies the live limits of the worker's own cgroup before granting it.
The module uses only the Python standard library and can travel with the job.
"""

from __future__ import annotations

import contextlib
import http.client
import ipaddress
import json
import math
import os
import shlex
import shutil
import stat
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit


DEFAULT_ROOT = Path.home() / ".chimera" / "peer-guard"
_MIB = 1024 ** 2
_MAX_GUEST_MEMORY_MIB = 1536
DEFAULTS = {
    "ram_reserve_mib": 2560,
    "job_memory_mib": 512,
    "disk_reserve_mib": math.ceil(15_000_000_000 / _MIB),
    "job_disk_mib": 128,
    "cpu_quota_pct": 100,
    "max_tasks": 128,
    "runtime_seconds": 900,
    "psi_cpu_pct": 25.0,
    "psi_memory_pct": 1.0,
    "psi_io_pct": 5.0,
    "max_load1": 1.8,
    "max_temp_c": 70.0,
    "service_urls": ("http://127.0.0.1:9780/.well-known/chimera.json",),
    "service_p95_ms": 150.0,
    "service_samples": 5,
    "service_timeout_s": 0.5,
    "max_sample_age_s": 5.0,
    "require_io_cap": False,
    "io_write_bps": 8 * 1024 * 1024,
}


def guarded_build_required():
    """Describe an explicit guest request that never entered the receiver's queue."""
    return {
        "ok": False,
        "state": "deferred",
        "error": "guarded_build_required",
        "submit_via": "chimera-tp swarm",
        "queue": {"stored": False},
    }


class AdmissionDeferred(RuntimeError):
    def __init__(self, reason, details=None):
        self.reason = reason
        self.details = details or {}
        super().__init__(reason)

    def as_dict(self):
        return {"accepted": False, "decision": "defer", "reason": self.reason,
                "health": self.details}


def _config(policy):
    incoming = {} if policy is None else dict(policy)
    unknown = set(incoming) - set(DEFAULTS) - {"disk_path"}
    if unknown:
        raise ValueError(f"unknown peer guard settings: {', '.join(sorted(unknown))}")
    settings = {**DEFAULTS, **incoming}
    for key, default in DEFAULTS.items():
        value = settings[key]
        if type(default) in (float, int):
            if (type(value) not in (float, int) or not math.isfinite(value) or value <= 0
                    or (type(default) is int and type(value) is not int)):
                raise ValueError(f"{key} must be a finite positive {type(default).__name__}")
    if not isinstance(settings["require_io_cap"], bool):
        raise ValueError("require_io_cap must be boolean")
    if not 2 <= settings["service_samples"] <= 32 or settings["service_timeout_s"] > 5:
        raise ValueError("service probes need 2–32 observations and a timeout of at most 5 s")
    urls = settings["service_urls"]
    if not isinstance(urls, (list, tuple)) or not 1 <= len(urls) <= 8:
        raise ValueError("service_urls must list between one and eight receiver-local health URLs")
    for url in urls:
        parts = urlsplit(url)
        if (parts.scheme != "http" or not parts.hostname or parts.username is not None
                or parts.password is not None or parts.fragment):
            raise ValueError("service_urls requires a receiver-local HTTP URL")
        if parts.hostname != "localhost" and not ipaddress.ip_address(parts.hostname).is_loopback:
            raise ValueError("service probes must address the receiver loopback interface")
        if parts.port == 0:
            raise ValueError("service URL port must be positive")
    return settings


def _receiver_policy(directory, request):
    """Apply operator-owned floors and ceilings before considering a guest's estimates."""
    try:
        fd = os.open("policy.json", os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
                     dir_fd=directory)
    except FileNotFoundError:
        local = {}
    else:
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or info.st_mode & 0o022 or info.st_size > 16384):
                raise AdmissionDeferred("receiver_policy_unsafe")
            local = json.loads(stream.read(16385))
        if not isinstance(local, dict):
            raise AdmissionDeferred("receiver_policy_invalid")
    max_memory = local.pop("max_job_memory_mib", _MAX_GUEST_MEMORY_MIB)
    max_disk = local.pop("max_job_disk_mib", 2048)
    if any(type(cap) is not int or cap <= 0 for cap in (max_memory, max_disk)):
        raise AdmissionDeferred("receiver_policy_invalid")
    site = _config(local)
    # Existing site policies can tighten these hardware limits but cannot relax them.
    for key in ("ram_reserve_mib", "disk_reserve_mib"):
        site[key] = max(site[key], DEFAULTS[key])
    for key in ("max_load1", "max_temp_c"):
        site[key] = min(site[key], DEFAULTS[key])
    cfg = _config({**site, **(request or {})})
    for key in ("ram_reserve_mib", "disk_reserve_mib", "service_samples"):
        cfg[key] = max(site[key], cfg[key])
    for key in ("psi_cpu_pct", "psi_memory_pct", "psi_io_pct", "max_load1", "max_temp_c", "service_p95_ms",
                "service_timeout_s", "max_sample_age_s", "io_write_bps"):
        cfg[key] = min(site[key], cfg[key])
    caps = {"job_memory_mib": min(max_memory, _MAX_GUEST_MEMORY_MIB), "job_disk_mib": max_disk}
    caps.update({key: site[key] for key in ("cpu_quota_pct", "max_tasks", "runtime_seconds")})
    for key, cap in caps.items():
        if cfg[key] > cap:
            raise AdmissionDeferred("job_budget_exceeds_receiver_policy",
                                    {"field": key, "requested": cfg[key], "maximum": cap})
    cfg["require_io_cap"] = site["require_io_cap"] or cfg["require_io_cap"]
    cfg["service_urls"] = list(dict.fromkeys([*site["service_urls"], *cfg["service_urls"]]))
    if len(cfg["service_urls"]) > 8:
        raise AdmissionDeferred("too_many_service_endpoints")
    return cfg


def launch_policy(root: Path, request=None):
    """Read the receiver's limits before starting the transient unit, without taking a guest slot."""
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        info = os.fstat(fd)
        if info.st_uid != os.getuid() or info.st_mode & 0o022:
            raise AdmissionDeferred("guard_directory_unsafe")
        return _receiver_policy(fd, request)
    finally:
        os.close(fd)


def limited_command(argv, policy=None):
    """SSH command argv for an ephemeral guest unit; 'systemd-run' is resolved on Linux."""
    cfg = _config(policy)
    size = cfg["job_memory_mib"] * _MIB
    props = [
        f"MemoryHigh={size * 4 // 5}", f"MemoryMax={size}", "MemorySwapMax=0",
        f"CPUQuota={cfg['cpu_quota_pct']}%", f"TasksMax={cfg['max_tasks']}",
        f"RuntimeMaxSec={cfg['runtime_seconds']}", "KillMode=control-group",
    ]
    if cfg["require_io_cap"]:
        # systemd resolves this absolute path to its backing block device.
        disk_path = cfg.get("disk_path")
        if not disk_path or not os.fspath(disk_path).startswith("/"):
            raise ValueError("a Linux disk_path is required to enforce an SSD write rate")
        props.append(f"IOWriteBandwidthMax={shlex.quote(os.fspath(disk_path))} {cfg['io_write_bps']}")
    # A fixed transient unit name lets the service manager reject simultaneous
    # guests before allocating a second worker cgroup or starting its process.
    return ["systemd-run", "--user", "--unit=chimera-peer-guest.service", "--quiet", "--wait", "--pipe", "--collect",
            "--service-type=exec", *("--property=" + prop for prop in props), "--", *argv]


def _limits(directory, disk):
    def read(parent, name):
        try:
            return (parent / name).read_text().strip()
        except FileNotFoundError:
            return None

    def integer(value):
        return int(value) if value and value != "max" else None

    drive_id = os.stat(disk).st_dev
    device = f"{os.major(drive_id)}:{os.minor(drive_id)}"
    devices = {device}
    device_dir = Path("/sys/dev/block", device)
    if (device_dir / "partition").exists():
        devices.add((device_dir.resolve().parent / "dev").read_text().strip())
    files = {"memory_high": "memory.high", "memory_max": "memory.max",
             "swap_max": "memory.swap.max", "tasks_max": "pids.max"}
    caps = {key: [] for key in (*files, "cpu_quota_pct", "io_write_bps")}
    parent = directory
    mount = Path("/sys/fs/cgroup")
    while parent == mount or mount in parent.parents:
        for key, name in files.items():
            limit = integer(read(parent, name))
            if limit is not None:
                caps[key].append(limit)
        cpu = (read(parent, "cpu.max") or "max 100000").split()
        quota = integer(cpu[0])
        if quota is not None:
            caps["cpu_quota_pct"].append(100.0 * quota / int(cpu[1]))
        for line in (read(parent, "io.max") or "").splitlines():
            target, *fields = line.split()
            if target in devices:
                bound = dict(value.split("=") for value in fields).get("wbps")
                if integer(bound) is not None:
                    caps["io_write_bps"].append(int(bound))
        parent = parent.parent
    effective = {key: min(values) if values else None for key, values in caps.items()}
    return {**effective, "io_devices": sorted(devices)}


def _pressure(kind):
    for row in Path("/proc/pressure", kind).read_text().splitlines():
        mode, *fields = row.split()
        if mode == "some":
            value = float(dict(x.split("=") for x in fields)["avg10"])
            if math.isfinite(value) and 0 <= value <= 100:
                return value
    raise ValueError(f"missing valid {kind} PSI avg10")


def _temperature():
    readings = []
    for sensor in Path("/sys/class/hwmon").glob("hwmon*"):
        try:
            name = (sensor / "name").read_text().strip()
        except FileNotFoundError:
            continue
        if name in {"coretemp", "k10temp", "zenpower", "cpu_thermal"}:
            for channel in sensor.glob("temp*_input"):
                reading = int(channel.read_text()) / 1000
                if 0 < reading < 150:
                    readings.append(reading)
    if not readings:
        raise ValueError("CPU temperature sensor unavailable")
    return max(readings)


def _service_p95(url, cfg, started):
    parts = urlsplit(url)
    path = (parts.path or "/") + ("?" + parts.query if parts.query else "")
    spans = []
    for _ in range(cfg["service_samples"]):
        remaining = cfg["max_sample_age_s"] - (time.monotonic() - started)
        if remaining <= 0:
            raise AdmissionDeferred("stale_sample", {"endpoint": url})
        connection = http.client.HTTPConnection(parts.hostname, parts.port,
                                                timeout=min(cfg["service_timeout_s"], remaining))
        try:
            tick = time.monotonic()
            connection.request("GET", path, headers={"Connection": "close"})
            with connection.getresponse() as response:
                if not 200 <= response.status < 300:
                    raise AdmissionDeferred("service_unhealthy", {"endpoint": url, "status": response.status})
                received = 0
                while True:
                    if time.monotonic() - started >= cfg["max_sample_age_s"]:
                        raise AdmissionDeferred("stale_sample", {"endpoint": url})
                    chunk = response.read1(16 * 1024)
                    if not chunk:
                        break
                    received += len(chunk)
                    if received > 256 * 1024:
                        raise AdmissionDeferred("service_probe_oversize", {"endpoint": url})
            spans.append((time.monotonic() - tick) * 1000)
        except (OSError, http.client.HTTPException) as exc:
            raise AdmissionDeferred("service_unavailable", {"endpoint": url, "error": type(exc).__name__}) from exc
        finally:
            connection.close()
    return sorted(spans)[math.ceil(0.95 * len(spans)) - 1]


def _snapshot(cfg, root):
    started = time.monotonic()
    disk = Path(cfg.get("disk_path") or root)
    fields = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        name, _, raw = line.partition(":")
        if name == "MemAvailable":
            size, unit = raw.split()
            if unit != "kB":
                raise ValueError("unknown MemAvailable units")
            fields["available_ram_mib"] = int(size) / 1024
    if "available_ram_mib" not in fields:
        raise ValueError("MemAvailable unavailable")
    fields["available_disk_mib"] = shutil.disk_usage(disk).free / _MIB
    fields["load1"] = os.getloadavg()[0]
    fields["temp_c"] = _temperature()
    fields["psi_some_avg10"] = {name: _pressure(name) for name in ("cpu", "memory", "io")}
    unified = [x[3:] for x in Path("/proc/self/cgroup").read_text().splitlines()
               if x.startswith("0::/")]
    if len(unified) != 1 or ".." in Path(unified[0]).parts:
        raise ValueError("unified cgroup unavailable")
    mount = Path("/sys/fs/cgroup")
    unit = mount / unified[0].lstrip("/")
    fields["cgroup"] = unified[0]
    fields["limits"] = _limits(unit, disk)
    uid = os.getuid()
    manager = mount / "user.slice" / f"user-{uid}.slice" / f"user@{uid}.service"
    try:
        controllers = (manager / "cgroup.controllers").read_text().split()
    except FileNotFoundError:
        controllers = []
    fields["user_controllers"] = sorted(controllers)
    fields["service_p95_ms"] = {url: _service_p95(url, cfg, started) for url in cfg["service_urls"]}
    fields["samples_per_service"] = cfg["service_samples"]
    fields["sample_age_s"] = time.monotonic() - started
    fields["measured_at"] = time.time()
    return fields


def _decision(cfg, health, require_limits):
    if health["sample_age_s"] > cfg["max_sample_age_s"]:
        return "stale_sample"
    if health["available_ram_mib"] < cfg["ram_reserve_mib"] + cfg["job_memory_mib"]:
        return "ram_reserve"
    if health["available_disk_mib"] < cfg["disk_reserve_mib"] + cfg["job_disk_mib"]:
        return "disk_reserve"
    load1 = health.get("load1")
    if type(load1) not in (int, float) or not math.isfinite(load1) or load1 < 0:
        return "load_unavailable"
    if load1 > cfg["max_load1"]:
        return "host_load"
    if health["temp_c"] >= cfg["max_temp_c"]:
        return "temperature"
    for kind, pressure in health["psi_some_avg10"].items():
        if pressure >= cfg[f"psi_{kind}_pct"]:
            return f"{kind}_pressure"
    if any(ms > cfg["service_p95_ms"] for ms in health["service_p95_ms"].values()):
        return "service_latency"
    limits = health["limits"]
    if cfg["require_io_cap"]:
        rate = limits["io_write_bps"]
        if rate is None or rate > cfg["io_write_bps"]:
            if require_limits or "io" not in health["user_controllers"]:
                return "io_cap_unavailable"
    needed = (("memory", "memory_max", cfg["job_memory_mib"] * _MIB),
              ("memory", "memory_high", cfg["job_memory_mib"] * _MIB * 4 // 5),
              ("memory", "swap_max", 0), ("cpu", "cpu_quota_pct", cfg["cpu_quota_pct"]),
              ("pids", "tasks_max", cfg["max_tasks"]))
    for controller, key, ceiling in needed:
        if limits[key] is None or limits[key] > ceiling:
            if require_limits or controller not in health["user_controllers"]:
                return key + "_unbounded"
    return None


def recheck_running(root: Path, policy: dict) -> dict:
    """Observe the same guest while it owns the slot and already consumes its reservation."""
    try:
        health = _snapshot(policy, root)
        capacity = dict(health)
        # At admission these resources had still to be allocated. During work
        # protect the remaining host floor and verify the original cgroup caps.
        capacity["available_ram_mib"] += policy["job_memory_mib"]
        capacity["available_disk_mib"] += policy["job_disk_mib"]
        reason = _decision(policy, capacity, require_limits=True)
        if reason:
            raise AdmissionDeferred(reason, {"health": health})
        return health
    except (OSError, ValueError, IndexError, KeyError) as exc:
        raise AdmissionDeferred("running_health_unavailable", {"type": type(exc).__name__}) from exc


@contextlib.contextmanager
def _slot(root):
    if not sys.platform.startswith("linux"):
        raise AdmissionDeferred("receiver_requires_linux")
    import fcntl

    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    flags = os.O_NOFOLLOW | os.O_CLOEXEC
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | flags)
    try:
        folder = os.fstat(directory)
        if folder.st_uid != os.getuid() or folder.st_mode & 0o022:
            raise AdmissionDeferred("guard_directory_unsafe")
        lock = os.open("guest.lock", os.O_RDWR | os.O_CREAT | flags, 0o600, dir_fd=directory)
        try:
            info = os.fstat(lock)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
                raise AdmissionDeferred("lease_file_unsafe")
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise AdmissionDeferred("guest_slot_busy", {"max_guests": 1}) from None
            yield directory
        finally:
            os.close(lock)
    finally:
        os.close(directory)


@contextlib.contextmanager
def _acquire(root, request, require_limits):
    # ExitStack limits error conversion to admission itself. Exceptions from
    # the admitted application must propagate, including regular OS errors.
    with contextlib.ExitStack() as stack:
        try:
            if require_limits:
                cfg = _receiver_policy(stack.enter_context(_slot(root)), request)
            else:
                # A preflight samples availability and releases its probe lock
                # before spending network time measuring the protected service.
                with _slot(root) as directory:
                    cfg = _receiver_policy(directory, request)
            health = _snapshot(cfg, root)
        except AdmissionDeferred:
            raise
        except (OSError, ValueError, KeyError, IndexError, http.client.HTTPException) as exc:
            raise AdmissionDeferred("telemetry_unavailable",
                                    {"error": type(exc).__name__, "message": str(exc)}) from exc
        reason = _decision(cfg, health, require_limits)
        if reason:
            raise AdmissionDeferred(reason, health)
        yield {"accepted": True, "decision": "accept", "reason": "capacity",
               "limits_verified": require_limits, "health": health, "effective_policy": cfg}


def reserve(root: Path, policy: dict | None = None):
    """Hold the receiver's single guest slot throughout the worker operation."""
    return _acquire(Path(root), policy, require_limits=True)


def assess(policy: dict | None = None, *, root: Path = DEFAULT_ROOT) -> dict:
    """Sample receiver-local capacity and the slot. The caller must still reserve."""
    try:
        with _acquire(Path(root), policy, require_limits=False) as result:
            return result
    except AdmissionDeferred as exc:
        return exc.as_dict()


# ---------------------------------------------------------------------------
# v26.0 Lock-Free Egress Peer-Hop Fuse + Shared Peer-Secret Auth Helper
# ---------------------------------------------------------------------------

_FUSE_CACHE_LOCK = None
_FUSE_CACHE_TS: float = 0.0
_FUSE_CACHE_VAL: tuple[bool, str] = (True, "ok")


def load_peer_secret(secret_path: Path | None = None) -> str:
    """Read optional cluster shared secret from CHIMERA_PEER_SECRET or ~/.chimera/peer.secret."""
    env_val = os.environ.get("CHIMERA_PEER_SECRET", "").strip()
    if env_val:
        return env_val
    path = Path(secret_path) if secret_path is not None else (Path.home() / ".chimera" / "peer.secret")
    try:
        if not path.is_file():
            return ""
        if sys.platform.startswith("linux"):
            st = os.lstat(path)
            if stat.S_ISLNK(st.st_mode) or (st.st_mode & 0o077):
                return ""
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def authenticate_peer_request(request, trusted_origin: str) -> bool:
    """Attach the node credential only to the configured origin and never to a redirect."""
    origin = urlsplit(trusted_origin)
    target = urlsplit(request.full_url)
    if (origin.scheme not in {"http", "https"} or not origin.netloc
            or origin.username is not None or origin.password is not None
            or origin.path not in ("", "/") or origin.query or origin.fragment
            or (target.scheme, target.netloc.lower()) != (origin.scheme, origin.netloc.lower())):
        return False
    secret = load_peer_secret()
    if not secret:
        return False
    request.add_unredirected_header("X-Chimera-Peer-Auth", secret)
    return True


def verify_peer_auth(presented: str | None, *, expected: str | None = None) -> bool:
    """Constant-time verification of peer auth token; returns True when no secret is configured."""
    import hmac

    exp = expected if expected is not None else load_peer_secret()
    if not exp:
        return True
    if not presented:
        return False
    return hmac.compare_digest(str(presented).strip(), exp)


def fast_egress_fuse(
    *,
    cache_ttl_s: float = 2.0,
    max_daemon_ram_mb: float = 72.0,
    ram_reserve_mib: int | None = None,
    max_load1: float | None = None,
    max_temp_c: float | None = None,
    force_refresh: bool = False,
) -> tuple[bool, str]:
    """Lock-free, 2s-cached health fuse for peer-hop egress (0 flocks, 0 HTTP probes, 0 subprocesses)."""
    global _FUSE_CACHE_LOCK, _FUSE_CACHE_TS, _FUSE_CACHE_VAL
    import threading

    if _FUSE_CACHE_LOCK is None:
        _FUSE_CACHE_LOCK = threading.Lock()

    now = time.monotonic()
    with _FUSE_CACHE_LOCK:
        if (not force_refresh) and (now - _FUSE_CACHE_TS) < max(0.2, float(cache_ttl_s)):
            return _FUSE_CACHE_VAL

    ram_floor = int(ram_reserve_mib) if ram_reserve_mib is not None else int(DEFAULTS["ram_reserve_mib"])
    load_cap = float(max_load1) if max_load1 is not None else float(DEFAULTS["max_load1"])
    temp_cap = float(max_temp_c) if max_temp_c is not None else float(DEFAULTS["max_temp_c"])

    ok = True
    reason = "ok"
    try:
        if sys.platform.startswith("linux"):
            # 1. Daemon VmRSS cap (Law 7 protection on svhome)
            try:
                for line in Path("/proc/self/status").read_text(encoding="utf-8").splitlines():
                    if line.startswith("VmRSS:"):
                        rss_mb = int(line.split()[1]) / 1024.0
                        if rss_mb > float(max_daemon_ram_mb):
                            ok, reason = False, f"daemon_rss_high:{rss_mb:.1f}MiB"
                        break
            except Exception:
                pass
            # 2. MemAvailable floor
            if ok:
                try:
                    for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
                        if line.startswith("MemAvailable:"):
                            avail_mib = int(line.split()[1]) / 1024.0
                            if avail_mib < ram_floor:
                                ok, reason = False, f"ram_reserve:{avail_mib:.0f}MiB"
                            break
                except Exception:
                    pass
            # 3. 1-minute load average
            if ok:
                try:
                    l1 = os.getloadavg()[0]
                    if l1 > load_cap:
                        ok, reason = False, f"host_load:{l1:.2f}"
                except Exception:
                    pass
            # 4. CPU temperature (best-effort; some VMs lack hwmon)
            if ok:
                try:
                    temp = _temperature()
                    if temp >= temp_cap:
                        ok, reason = False, f"temperature:{temp:.1f}C"
                except Exception:
                    pass
            # 5. Linux PSI avg10 floors
            if ok:
                for pkind in ("cpu", "memory", "io"):
                    try:
                        val = _pressure(pkind)
                        if val >= float(DEFAULTS[f"psi_{pkind}_pct"]):
                            ok, reason = False, f"{pkind}_pressure:{val:.1f}%"
                            break
                    except Exception:
                        continue
        else:
            # Windows/other host: enforce daemon Zero-Weight RSS ceiling
            try:
                from ..autopilot import get_zero_weight_status

                zw = get_zero_weight_status(budget_mb=max(float(max_daemon_ram_mb), 80.0))
                if float(zw.get("daemon_ram_mb", 0.0)) > float(max_daemon_ram_mb):
                    ok, reason = False, f"daemon_rss_high:{zw.get('daemon_ram_mb')}MiB"
            except Exception:
                pass
    except Exception:
        ok, reason = True, "ok"

    res = (ok, reason)
    with _FUSE_CACHE_LOCK:
        _FUSE_CACHE_TS = now
        _FUSE_CACHE_VAL = res
    return res
