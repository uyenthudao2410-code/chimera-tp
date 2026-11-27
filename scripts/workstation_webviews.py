"""Attribute Windows WebView2 private commit using live process identities."""

from collections import defaultdict
import hashlib
import os
from pathlib import PureWindowsPath
import re
from statistics import median

import psutil


IMAGE = "msedgewebview2.exe"


def parent_of(info, processes):
    parent = processes.get(info["ppid"])
    if parent and parent["created"] <= info["created"]:
        return parent
    return None


class WebViewObservation:
    def __init__(self):
        self._salt = os.urandom(32)
        self._roots = {}

    def _inspect_root(self, pid, info):
        """Discard argv immediately. Retain only a role, executable basename and keyed folder digest."""
        try:
            process = psutil.Process(pid)
            if process.create_time() != info["created"] or process.name().lower() != IMAGE:
                return None
            fields = {}
            for arg in process.cmdline():
                key, separator, value = arg.partition("=")
                if separator and key.lower() in ("--type", "--webview-exe-name", "--user-data-dir"):
                    fields[key.lower()] = value.strip('"')
            if fields.get("--type"):
                return None
            host = PureWindowsPath(fields.get("--webview-exe-name", "")).name.casefold()
            if not re.fullmatch(r"[\w .()-]{1,100}\.exe", host):
                host = None
            folder = fields.get("--user-data-dir")
            profile = None
            if folder:
                # No profile path, digest or salt is written to the measurement.
                profile = hashlib.blake2b(os.path.normcase(os.path.normpath(folder)).encode(),
                                          key=self._salt, digest_size=16).digest()
            return host, profile
        except (OSError, psutil.Error):
            return None

    def collect(self, processes):
        roots = {}
        totals = defaultdict(lambda: {"private_bytes": 0, "processes": 0, "roots": set(), "profiles": set()})
        unknown_bytes = unknown_count = 0
        for pid, info in processes.items():
            if info["name"] != IMAGE:
                continue
            root_pid, root = pid, info
            visited = {pid}
            while (parent := parent_of(root, processes)) is not None and parent["name"] == IMAGE:
                if root["ppid"] in visited:
                    parent = None
                    break
                root_pid, root = root["ppid"], parent
                visited.add(root_pid)
            key = (root_pid, root["created"])
            if key not in roots:
                evidence = self._roots.get(key)
                roots[key] = evidence if evidence is not None else self._inspect_root(root_pid, root)
            identity = roots[key]
            if parent is None or identity is None or identity[0] != parent["name"].casefold():
                unknown_count += 1
                unknown_bytes += info["private"]
                continue
            host, profile = identity
            group = totals[host]
            group["processes"] += 1
            group["private_bytes"] += info["private"]
            group["roots"].add(key)
            if profile is not None:
                group["profiles"].add(profile)
        self._roots = roots
        groups = {
            name: {"private_bytes": values["private_bytes"], "processes": values["processes"],
                   "roots": len(values["roots"]), "observed_profile_dirs": len(values["profiles"])}
            for name, values in totals.items()
        }
        total_bytes = sum(r["private_bytes"] for r in groups.values()) + unknown_bytes
        return {"hosts": groups, "unattributed_private_bytes": unknown_bytes,
                "unattributed_processes": unknown_count, "total_private_bytes": total_bytes}


def summarize(rows):
    views = [row["webview2"] for row in rows]
    hosts = {host for view in views for host in view["hosts"]}
    summary = []
    for name in hosts:
        groups = [view["hosts"].get(name, {}) for view in views]
        summary.append({
            "host": name, "samples_present": sum(bool(g) for g in groups),
            "runtime_private_mib_median": round(median(g.get("private_bytes", 0) for g in groups) / 2**20, 2),
            "runtime_processes_peak": max(g.get("processes", 0) for g in groups),
            "runtime_roots_peak": max(g.get("roots", 0) for g in groups),
            "observed_profile_dirs_peak": max(g.get("observed_profile_dirs", 0) for g in groups),
        })
    return {
        "hosts": sorted(summary, key=lambda g: (-g["runtime_private_mib_median"], g["host"])),
        "runtime_private_mib_median": round(median(v["total_private_bytes"] for v in views) / 2**20, 2),
        "unattributed_private_mib_peak": round(max(v["unattributed_private_bytes"] for v in views) / 2**20, 2),
        "scope": "Only WebView2 process bytes. Match the browser's declared host to its live parent image. "
                 "Treat an orphan, missing identity or disagreement as unattributed. "
                 "The root and profile counts do not establish web feature parity or achievable savings.",
    }
