"""Read Radar Dashboard and host counters, or compile public CPython sources in a Guard job."""

import hashlib
import http.client
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import py_compile
import re
import subprocess
import sys
import sysconfig
import time
from urllib.parse import urlsplit


UNIT = "radar-dashboard.service"
GUEST = "chimera-peer-guest.service"
PORT = 8787
MODULES = ("argparse.py", "ast.py", "configparser.py", "dataclasses.py")


class Stylesheet(HTMLParser):
    """Find the exact local URL the application's entry page requests."""

    def __init__(self):
        super().__init__()
        self.href = None

    def handle_starttag(self, tag, attributes):
        fields = dict(attributes)
        href = fields.get("href") or ""
        parts = urlsplit(href)
        if (tag == "link" and "stylesheet" in fields.get("rel", "").split()
                and not parts.scheme and not parts.netloc and parts.path == "/desk.css"):
            self.href = href


def sha(data):
    return hashlib.sha256(data).hexdigest()


def attached_service():
    command = ["systemctl", "--user", "show", UNIT, "-p", "ActiveState", "-p", "FragmentPath",
               "-p", "WorkingDirectory", "-p", "ControlGroup", "-p", "MainPID"]
    fields = dict(line.split("=", 1) for line in subprocess.check_output(
        command, text=True, timeout=4).splitlines())
    if fields["ActiveState"] != "active":
        raise RuntimeError("dashboard_unit_inactive")
    unit = Path(fields["FragmentPath"]).read_text()
    if not re.search(r"(?:--port[ =]+|\bPORT=)" + str(PORT) + r"\b", unit):
        raise RuntimeError("dashboard_unit_port_changed")
    root = Path(fields["WorkingDirectory"]) / "app"
    pages = root / "static"
    parser = Stylesheet()
    parser.feed((pages / "index.html").read_text())
    if not parser.href or 'path == "/api/health"' not in (root / "server.py").read_text():
        raise RuntimeError("published_dashboard_routes_changed")
    css = (pages / "desk.css").read_bytes()
    if not 1 <= len(css) <= 16384:
        raise RuntimeError("dashboard_fixture_outside_probe_budget")
    meta = {"unit": UNIT, "unit_pid": int(fields["MainPID"]), "port": PORT,
            "health_path": "/api/health", "asset_path": parser.href,
            "asset_bytes": len(css), "asset_sha256": sha(css),
            "unit_declares_port": True, "entry_links_asset": True}
    app_group = Path("/sys/fs/cgroup") / fields["ControlGroup"].lstrip("/")
    if not app_group.is_dir():
        raise RuntimeError("dashboard_cgroup_missing")
    return meta, app_group.parent / GUEST


def read_routes(port, meta):
    observed = {}
    for name in ("health", "asset"):
        limit = 2048 if name == "health" else meta["asset_bytes"]
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
        start = time.perf_counter_ns()
        try:
            conn.request("GET", meta[name + "_path"], headers={"Connection": "close"})
            with conn.getresponse() as response:
                payload = response.read(limit + 1)
                elapsed = (time.perf_counter_ns() - start) / 1e6
                content_type = response.headers.get_content_type()
                if response.status != 200 or len(payload) > limit:
                    raise ValueError(f"{name}_http_{response.status}_or_oversize")
        finally:
            conn.close()
        if name == "health":
            value = json.loads(payload)
            valid = content_type == "application/json" and value.get("ok") is True
            valid = valid and isinstance(value.get("version"), str) and bool(value["version"])
        else:
            valid = content_type == "text/css" and sha(payload) == meta["asset_sha256"]
        if not valid:
            raise ValueError(name + "_response_contract_changed")
        observed[name] = round(elapsed, 4)
    return observed


def key_values(path):
    return dict(row.split(None, 1) for row in path.read_text().splitlines() if row.strip())


def group_populated(group):
    try:
        return bool(int(key_values(group / "cgroup.events")["populated"]))
    except FileNotFoundError:
        return False


def disk_devices():
    dev = Path.home().stat().st_dev
    mount = Path("/sys/dev/block", f"{os.major(dev)}:{os.minor(dev)}").resolve(strict=True)
    devices = [mount, mount.parent] if (mount / "partition").exists() else [mount]
    return {node.name: node for node in devices}


def cpu_sensors():
    paths = []
    for sensor in Path("/sys/class/hwmon").glob("hwmon*"):
        if (sensor / "name").read_text().strip() in {"coretemp", "k10temp", "zenpower", "cpu_thermal"}:
            paths.extend(sensor.glob("temp*_input"))
    if not paths:
        raise RuntimeError("cpu_temperature_unavailable")
    return paths


def host_sample(devices, sensors):
    psi = {}
    for name in ("cpu", "io", "memory"):
        rows = key_values(Path("/proc/pressure") / name)
        fields = dict(item.split("=") for item in rows["some"].split())
        psi[name] = {"avg10_pct": float(fields["avg10"]), "total_us": int(fields["total"])}
    kib, unit = key_values(Path("/proc/meminfo"))["MemAvailable:"].split()
    if unit != "kB":
        raise ValueError("meminfo_units_changed")
    return {"mem_available_mib": round(int(kib) / 1024, 2), "load1": os.getloadavg()[0],
            "cpu_temp_c": max(int(p.read_text()) for p in sensors) / 1000, "psi": psi,
            "device_write_bytes": {name: int((p / "stat").read_text().split()[6]) * 512
                                   for name, p in devices.items()}}


def connection_route():
    """Passive Tailscale hint for this SSH client's IP. Return no addresses or peer inventory."""
    peer_ip = os.environ.get("SSH_CONNECTION", "").split()
    if peer_ip:
        try:
            state = subprocess.check_output(["tailscale", "status", "--json"], timeout=3)
            for peer in json.loads(state).get("Peer", {}).values():
                if peer_ip[0] in peer.get("TailscaleIPs", []):
                    if peer.get("CurAddr"):
                        return {"kind": "direct", "source": "tailscale_current_peer"}
                    if peer.get("Relay"):
                        return {"kind": "relay_hint", "region": peer["Relay"],
                                "source": "tailscale_current_peer"}
        except (subprocess.SubprocessError, OSError, ValueError):
            pass
    return {"kind": "unobserved"}


def emit(data):
    print(json.dumps(data, ensure_ascii=True, separators=(",", ":")), flush=True)


def observe():
    meta, guest = attached_service()
    devices, sensors = disk_devices(), cpu_sensors()
    emit({**meta, "route_at_open": connection_route(), "device_names": list(devices)})
    for command in sys.stdin:
        op = command.strip()
        if op == "sample":
            start = time.monotonic_ns()
            populated = group_populated(guest)
            spans = read_routes(PORT, meta)
            emit({"start_ns": start, "guest_before": populated, "linux_http_ms": spans,
                  "host": host_sample(devices, sensors)})
        elif op == "stamp":
            emit({"guest_after": group_populated(guest), "end_ns": time.monotonic_ns()})
        elif op == "identity":
            current, _ = attached_service()
            emit({"same_service": current == meta, "route_at_close": connection_route()})
        else:
            raise ValueError("unknown_probe_command")


def guest_bytes(group):
    try:
        counters = {}
        for line in (group / "io.stat").read_text().splitlines():
            device, *entries = line.split()
            counters[device] = int(dict(v.split("=") for v in entries).get("wbytes", 0))
        return counters
    except (FileNotFoundError, PermissionError):
        return None


def compile_job(rounds):
    if not 1 <= rounds <= 180:
        raise ValueError("invalid_round_count")
    unified = next(x[3:] for x in Path("/proc/self/cgroup").read_text().splitlines() if x.startswith("0::/"))
    group = Path("/sys/fs/cgroup") / unified.lstrip("/")
    if group.name != GUEST:
        raise RuntimeError("expected_guard_cgroup")
    library = Path(sysconfig.get_path("stdlib"))
    sources = {name: (library / name).read_bytes() for name in MODULES}
    ids = {name: sha(data) for name, data in sources.items()}
    w0 = int(key_values(Path("/proc/self/io"))["write_bytes:"])
    group0 = guest_bytes(group)
    cpu0 = time.process_time_ns()
    start = time.monotonic_ns()
    for _ in range(rounds):
        for name, data in sources.items():
            compile(data, name, "exec", dont_inherit=True)
    objects = {}
    for name in sources:
        dest = Path(name + "c")
        py_compile.compile(str(library / name), cfile=str(dest), dfile=name, doraise=True,
                           invalidation_mode=py_compile.PycInvalidationMode.CHECKED_HASH)
        objects[name] = {"bytes": dest.stat().st_size, "sha256": sha(dest.read_bytes())}
    end = time.monotonic_ns()
    group1 = guest_bytes(group)
    group_delta = None if group0 is None or group1 is None else {
        d: group1.get(d, 0) - group0.get(d, 0) for d in group0.keys() | group1.keys()}
    emit({"start_ns": start, "end_ns": end, "cpu_ms": round((time.process_time_ns() - cpu0) / 1e6, 3),
          "duration_ms": round((end - start) / 1e6, 3), "rounds": rounds, "source_hashes": ids,
          "objects": objects, "guard_cgroup": group.name, "cgroup_write_bytes": group_delta,
          "process_write_bytes": int(key_values(Path("/proc/self/io"))["write_bytes:"]) - w0,
          "python": sys.version.split()[0]})


if __name__ == "__main__":
    if sys.argv[1:] == ["observe"]:
        observe()
    elif sys.argv[1:2] == ["compile"] and len(sys.argv) == 3:
        compile_job(int(sys.argv[2]))
    else:
        raise SystemExit("Invoke the operator script measure_peer_service_slo.py")
