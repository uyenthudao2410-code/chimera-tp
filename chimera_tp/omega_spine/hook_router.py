"""CHIMERA Omega-Spine: Antigravity 2.0 Lifecycle Hook Router (`/v1/hook/<event>`).

Handles all 6 Antigravity 2.0 lifecycle hooks in `< 10 ms`:
- `session_start`   : registers `(conversationId -> workspace)`, injects compact repo +
                      Hive leases + Akashic capsules + Immune Antibodies summary + UI badge.
- `pre_tool_use`    : Hive soft-lease / hard-lock check on edits, Immune Antibody matching,
                      optional heavy-command tracking/Iron Cage handling on `run_command`.
- `post_tool_use`   : records outcome to AkashicCortex (auto-distilling Immune Antibodies),
                      triggers non-blocking `PrecogVerifier.schedule(...)` on file edits.
- `pre_invocation`  : injects ONLY unseen Precog diagnostics, newly matched antibodies,
                      sibling Swarm mutations, and unseen Akashic capsules (0 noise if empty!).
- `post_invocation` : records invocation telemetry, returns `{"injectSteps": [], "terminationBehavior": ""}`.
- `stop`            : Stop sentinel checking `PrecogVerifier.has_blocking_errors(...)` when
                      `!continuationActive` and `terminationReason == "NO_TOOL_CALL"`.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

from .iron_cage import IronCage, get_iron_cage
from .precog_tournament import PrecogVerifier, ShadowTournament
from .streamable_mcp import (
    OmegaHiveStore,
    OmegaSessionRegistry,
    StreamableMcpServer,
    _fast_git_summary,
    _is_chimera_release_dir,
    resolve_akashic_cortex,
)

_EDIT_TOOLS = frozenset({
    "edit_file",
    "write_file",
    "write_to_file",
    "replace_file_content",
    "multi_replace_file_content",
    "chimera_atomic_patch",
})

_CMD_TOOLS = frozenset({
    "run_command",
    "bash",
    "powershell",
    "exec",
    "shell",
})

_HEAVY_CMD_RE = re.compile(r"(?i)^\s*(dotnet\s+(?:build|test)|pytest|python\s+-m\s+pytest|cargo\s+(?:build|test))\b")
_SHELL_META_RE = re.compile(r"[;&|><`\r\n]")
_POLICY_BLOCK_RE = re.compile(
    r"(?i)(tool call denied by pre-tool hook|security policy|all further execution must stop immediately|blocked due to potential violation)"
)

_EVENT_ALIASES = {
    "session_start": "session_start",
    "sessionstart": "session_start",
    "session-start": "session_start",
    "pre_tool_use": "pre_tool_use",
    "pretooluse": "pre_tool_use",
    "pre-tool-use": "pre_tool_use",
    "post_tool_use": "post_tool_use",
    "posttooluse": "post_tool_use",
    "post-tool-use": "post_tool_use",
    "pre_invocation": "pre_invocation",
    "preinvocation": "pre_invocation",
    "pre-invocation": "pre_invocation",
    "post_invocation": "post_invocation",
    "postinvocation": "post_invocation",
    "post-invocation": "post_invocation",
    "stop": "stop",
}


def normalize_hook_event(event: str) -> str:
    key = str(event or "").strip().lower()
    return _EVENT_ALIASES.get(key, key)


def _extract_conversation_id(payload: dict[str, Any]) -> str:
    for k in ("conversationId", "conversation_id", "sessionId", "session_id"):
        v = payload.get(k)
        if v:
            return str(v).strip()
    return "default"


def _extract_workspace(payload: dict[str, Any], sessions: OmegaSessionRegistry, cid: str) -> str:
    ws_list = payload.get("workspacePaths") or payload.get("workspace_paths")
    if isinstance(ws_list, list):
        for item in ws_list:
            s = str(item or "").strip()
            if s and not _is_chimera_release_dir(Path(s)):
                return str(Path(s).expanduser()).replace("\\", "/")
    for k in ("cwd", "repo", "workspace"):
        s = str(payload.get(k) or "").strip()
        if s and not _is_chimera_release_dir(Path(s)):
            return str(Path(s).expanduser()).replace("\\", "/")
    known = sessions.get_workspace(cid)
    return known or ""


def _extract_tool_call(payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    tc = payload.get("toolCall") or payload.get("tool_call") or {}
    if not isinstance(tc, dict):
        return "", {}
    name = str(tc.get("name") or tc.get("toolName") or tc.get("tool") or "").strip()
    raw_args = tc.get("arguments")
    if raw_args is None:
        raw_args = tc.get("input") if tc.get("input") is not None else tc.get("args")
    if isinstance(raw_args, str):
        try:
            parsed = json.loads(raw_args)
            args = parsed if isinstance(parsed, dict) else {"raw": raw_args}
        except Exception:
            args = {"raw": raw_args}
    elif isinstance(raw_args, dict):
        args = raw_args
    else:
        args = {}
    return name, args


def _extract_target_paths(args: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    for k in ("Path", "path", "TargetFile", "target_file", "file_path", "filePath"):
        v = args.get(k)
        if v and isinstance(v, str):
            paths.append(v.strip())
    edits = args.get("edits")
    if isinstance(edits, list):
        for ed in edits:
            if isinstance(ed, dict) and ed.get("path"):
                paths.append(str(ed["path"]).strip())
    return list(dict.fromkeys(paths))


def _to_rel_path(workspace: str, file_path: str) -> str:
    if not file_path:
        return ""
    if not workspace:
        return file_path.replace("\\", "/").lstrip("./")
    try:
        ws_p = Path(workspace).resolve()
        fp = Path(file_path)
        if not fp.is_absolute():
            fp = ws_p / fp
        return fp.resolve().relative_to(ws_p).as_posix()
    except Exception:
        return file_path.replace("\\", "/").lstrip("./")


def _extract_command(args: dict[str, Any]) -> str:
    for k in ("CommandLine", "command", "cmd", "command_line", "input"):
        v = args.get(k)
        if v and isinstance(v, str):
            return v.strip()
    return ""


def _extract_error(payload: dict[str, Any]) -> str:
    err = payload.get("error")
    if not err:
        return ""
    if isinstance(err, dict):
        return str(err.get("message") or err.get("error") or json.dumps(err, ensure_ascii=False))[:400]
    return str(err)[:400]


def _sha256_file_safe(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


class HookRouter:
    """Sub-10ms Antigravity 2.0 6-event lifecycle hook router."""

    def __init__(
        self,
        *,
        iron_cage: IronCage | None = None,
        precog: PrecogVerifier | None = None,
        cortex: Any = None,
        hive: OmegaHiveStore | None = None,
        sessions: OmegaSessionRegistry | None = None,
    ) -> None:
        self.iron_cage = iron_cage or get_iron_cage()
        self.precog = precog or PrecogVerifier(iron_cage=self.iron_cage)
        self._cortex = cortex
        self.hive = hive or OmegaHiveStore()
        self.sessions = sessions or OmegaSessionRegistry()
        self._lock = threading.Lock()
        self._recent_commands: list[dict[str, Any]] = []
        self._blocker_alerts: list[dict[str, Any]] = []
        self._blocker_seq: int = 0
        self._blocker_cursor: dict[str, int] = {}
        self._worker_heartbeats: dict[str, float] = {}
        self._stats: dict[str, Any] = {
            "total_calls": 0,
            "by_event": {},
            "denies": 0,
            "stop_continues": 0,
            "pre_invocation_injects": 0,
            "precog_schedules": 0,
            "antibodies_distilled": 0,
            "heavy_commands_tracked": 0,
            "blocker_alerts_recorded": 0,
            "dead_man_leases_released": 0,
            "shell_short_circuits": 0,
            "raw_tool_captures": 0,
            "raw_whispers": 0,
            "ghost_ring_ingests": 0,
            "epoch_soak_redirects": 0,
        }
        self._mnemosyne_ref: Any = None
        self._prometheus_ref: Any = None

    def _get_mnemosyne(self) -> Any | None:
        if self._mnemosyne_ref is not None:
            return self._mnemosyne_ref
        try:
            from ..platform.mnemosyne import get_mnemosyne_core
            self._mnemosyne_ref = get_mnemosyne_core()
            return self._mnemosyne_ref
        except Exception:
            return None

    def _get_prometheus(self) -> Any | None:
        if self._prometheus_ref is not None:
            return self._prometheus_ref
        try:
            from ..platform.prometheus import get_prometheus_core
            self._prometheus_ref = get_prometheus_core()
            return self._prometheus_ref
        except Exception:
            return None

    def record_blocker_alert(
        self,
        *,
        agent_id: str,
        repo: str,
        tool_name: str,
        reason: str,
        kind: str = "WORKER_BLOCKED_OUT_OF_BAND",
    ) -> dict[str, Any]:
        """Record an out-of-band halt alert and auto-release blocked worker leases."""
        if repo:
            try:
                self.hive.release_lease(agent_id=agent_id, repo=repo)
            except Exception:
                pass
        with self._lock:
            self._blocker_seq += 1
            alert = {
                "seq": self._blocker_seq,
                "kind": kind,
                "agent_id": agent_id,
                "repo": repo,
                "tool_name": tool_name,
                "reason": str(reason or "")[:240],
                "ts": round(time.time(), 3),
            }
            self._blocker_alerts.append(alert)
            if len(self._blocker_alerts) > 32:
                self._blocker_alerts = self._blocker_alerts[-32:]
            self._stats["blocker_alerts_recorded"] += 1
            return alert

    def list_blocker_alerts(self, *, repo: str | None = None, since_seq: int = 0) -> list[dict[str, Any]]:
        now = time.time()
        with self._lock:
            out = [
                dict(a)
                for a in self._blocker_alerts
                if a["seq"] > since_seq
                and (now - float(a.get("ts") or 0.0)) <= 600.0
                and (not repo or not a.get("repo") or a["repo"] == repo)
            ]
        return out

    def sweep_dead_man_leases(self, repo: str, *, stale_after_s: float = 180.0) -> list[dict[str, Any]]:
        """Auto-release open Hive leases whose worker stopped heartbeating beyond `stale_after_s`."""
        now = time.time()
        released: list[dict[str, Any]] = []
        if not repo:
            return released
        leases = self.hive.list_leases(repo=repo)
        for lease in leases:
            aid = str(lease.get("agent_id") or "")
            if not aid:
                continue
            with self._lock:
                hb = self._worker_heartbeats.get(aid)
            if hb is not None and (now - hb) > stale_after_s:
                alert = self.record_blocker_alert(
                    agent_id=aid,
                    repo=repo,
                    tool_name="heartbeat_timeout",
                    reason=f"Worker silent for {int(now - hb)}s while holding Hive lease; auto-released.",
                    kind="DEAD_MAN_LEASE_RELEASED",
                )
                with self._lock:
                    self._stats["dead_man_leases_released"] += 1
                    self._worker_heartbeats.pop(aid, None)
                released.append(alert)
        return released

    @property
    def cortex(self) -> Any:
        if self._cortex is None:
            self._cortex = resolve_akashic_cortex()
        return self._cortex

    def handle_event(self, event_name: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        t0 = time.perf_counter()
        ev = normalize_hook_event(event_name)
        body = payload if isinstance(payload, dict) else {}

        handlers = {
            "session_start": self._on_session_start,
            "pre_tool_use": self._on_pre_tool_use,
            "post_tool_use": self._on_post_tool_use,
            "pre_invocation": self._on_pre_invocation,
            "post_invocation": self._on_post_invocation,
            "stop": self._on_stop,
        }
        fn = handlers.get(ev)
        if fn is None:
            return {"ok": False, "error": f"unknown_hook_event:{event_name}"}

        res = fn(body)
        ms = round((time.perf_counter() - t0) * 1000.0, 3)
        with self._lock:
            self._stats["total_calls"] += 1
            ev_st = self._stats["by_event"].setdefault(ev, {"count": 0, "max_ms": 0.0, "last_ms": 0.0})
            ev_st["count"] += 1
            ev_st["last_ms"] = ms
            if ms > ev_st["max_ms"]:
                ev_st["max_ms"] = ms
        return res

    # --- Event 1: session_start ---

    def _on_session_start(self, body: dict[str, Any]) -> dict[str, Any]:
        cid = _extract_conversation_id(body)
        ws = _extract_workspace(body, self.sessions, cid)
        if ws:
            self.sessions.register(cid, ws)

        repo_name = Path(ws).name if ws else "unregistered"
        branch = ""
        top_count = 0
        file_hashes: dict[str, str] = {}

        cst = self.cortex.status()
        has_caps = bool(cst.get("capsule_count") or cst.get("capsules"))

        if ws and Path(ws).is_dir():
            repo_p = Path(ws)
            # Zero-subprocess branch read (< 0.5 ms!)
            git_fast = _fast_git_summary(repo_p, self.iron_cage, include_status=False)
            branch = git_fast.get("branch", "")
            try:
                entries = [p for p in repo_p.iterdir() if not p.name.startswith(".")]
                top_count = len(entries)
                if has_caps:
                    for p in entries[:8]:
                        if p.is_file() and p.stat().st_size <= 256 * 1024:
                            sha = _sha256_file_safe(p)
                            if sha:
                                file_hashes[p.name] = sha
            except OSError:
                pass

        leases = self.hive.list_leases(repo=ws) if ws else []
        sibling_leases = [l for l in leases if l.get("agent_id") != cid]
        capsules = self.cortex.recall_for_files(ws, file_hashes, limit=4) if (ws and file_hashes) else []
        has_abs = bool(cst.get("active_antibodies_count") or cst.get("active_antibodies"))
        antibodies = self.cortex.match_antibodies(ws, limit=4) if (ws and has_abs) else []

        parts = [f"[CHIMERA Omega-Spine] Workspace: {ws or 'none'}"]
        if branch:
            parts.append(f"Git branch: {branch} (top entries: {top_count})")
        if sibling_leases:
            lsum = "; ".join(
                f"{l['agent_id']}({','.join((l.get('files') or [])[:3]) or 'repo'})"
                for l in sibling_leases[:4]
            )
            parts.append(f"Active sibling Hive leases: {lsum}")
        if capsules:
            csum = "; ".join(f"{c.get('rel_path')}:{c.get('symbol')} - {str(c.get('summary', ''))[:80]}" for c in capsules[:3])
            parts.append(f"Akashic capsules: {csum}")
        if antibodies:
            asum = "; ".join(f"{a.get('error_sig', '')[:60]} -> {a.get('fix_hint', '')[:80]}" for a in antibodies[:3])
            parts.append(f"Immune antibodies: {asum}")

        # CHIMERA-MNEMOSYNE BirthPrimer (<20ms Env + Docs + Top-K Akashic Raw + Swarm Bulletin + Pacing)
        mn = self._get_mnemosyne()
        if mn is not None and ws:
            try:
                pr = mn.primer.prime(ws, cid=cid, include_raw_recall=True)
                if pr.get("compact_text"):
                    parts.append(f"Mnemosyne: {pr['compact_text'][:560]}")
            except Exception:
                pass

        # CHIMERA-PROMETHEUS Empirical Axioms + Active Soak-Freeze Guard (<=220 tok)
        prom = self._get_prometheus()
        if prom is not None:
            try:
                ax_sum = prom.axioms.birth_primer_summary(max_chars=420)
                if ax_sum:
                    parts.append(ax_sum)
                active_soaks = prom.epoch.active_soak_leases()
                if active_soaks:
                    lead = active_soaks[0]
                    parts.append(
                        f"SOAK-FREEZE ACTIVE: {lead['lease_id']} (owner={lead['owner_id']}, PID={lead['target_pid']}, "
                        f"{lead['remaining_s']}s left) -> DO NOT restart live daemon; use Shadow Port :{prom.epoch.default_shadow_port}"
                    )
            except Exception:
                pass

        sys_msg = " | ".join(parts)[:2100]
        badge = (
            f"**CHIMERA Omega-Spine** | `{repo_name}`"
            + (f" (`{branch}`)" if branch else "")
            + f" | Leases: {len(sibling_leases)} | Capsules: {len(capsules)} | Antibodies: {len(antibodies)}"
        )
        return {
            "injectSteps": [
                {
                    "systemMessage": {
                        "systemMessage": sys_msg,
                        "metadata": {"user_markdown": badge},
                    }
                }
            ]
        }

    # --- Event 2: pre_tool_use ---

    def _on_pre_tool_use(self, body: dict[str, Any]) -> dict[str, Any]:
        cid = _extract_conversation_id(body)
        ws = _extract_workspace(body, self.sessions, cid)
        tool_name, args = _extract_tool_call(body)
        tlow = tool_name.lower()

        if tlow in _EDIT_TOOLS:
            raw_paths = _extract_target_paths(args)
            rel_paths = [_to_rel_path(ws, p) for p in raw_paths if p]
            if ws and rel_paths:
                lease_res = self.hive.acquire_lease(
                    agent_id=cid,
                    repo=ws,
                    files=rel_paths,
                    intent=f"hook:{tool_name}",
                    ttl_s=120.0,
                    hard_lock=False,
                )
                if lease_res.get("blocked_by_hard_lock"):
                    hc = (lease_res.get("hard_conflicts") or [{}])[0]
                    holder = hc.get("agent_id", "another-agent")
                    ov = ", ".join(hc.get("overlap") or rel_paths)
                    with self._lock:
                        self._stats["denies"] += 1
                    return {
                        "decision": "deny",
                        "reason": f"Chimera Hive hard-lock held by {holder} on {ov}",
                    }
                for conflict in lease_res.get("conflicts") or []:
                    self.sessions.push_advisory(
                        cid,
                        "hive_conflict",
                        f"Sibling `{conflict.get('agent_id')}` holds soft lease on {', '.join(conflict.get('overlap') or rel_paths)}",
                    )
                for rel in rel_paths:
                    self.sessions.record_touched_file(cid, rel)
                    for ab in self.cortex.match_antibodies(rel, limit=2):
                        self.sessions.push_advisory(
                            cid,
                            "antibody",
                            f"[{ab.get('file_pattern', rel)}] {ab.get('error_sig', '')[:80]} -> {ab.get('fix_hint', '')[:120]}",
                        )
            return {"decision": "allow"}

        if tlow in _CMD_TOOLS:
            cmd = _extract_command(args)
            if cmd:
                # CHIMERA-SOVEREIGN-EPOCH Soak-Freeze Guard: prevent sibling restart from killing active soak PID
                if re.search(r"\b(restart|stop|kill|Stop-Process|taskkill)\b.*(chimera|9780)", cmd, re.I):
                    prom = self._get_prometheus()
                    if prom is not None:
                        try:
                            dec = prom.epoch.request_promote(
                                requester_id=cid,
                                candidate_tree_sha256="hook_cmd_check",
                            )
                            if not dec.get("allowed", True):
                                with self._lock:
                                    self._stats["epoch_soak_redirects"] += 1
                                self.sessions.push_advisory(
                                    cid,
                                    "soak_freeze_redirect",
                                    f"{dec.get('reason', 'Soak-Freeze active')} Use Shadow Port :{dec.get('shadow_port', 9796)}.",
                                )
                        except Exception:
                            pass

                # CHIMERA-MNEMOSYNE PreToolUse Shell Idempotent Replay Shield (< 3 ms across Swarm!)
                mn = self._get_mnemosyne()
                if mn is not None:
                    try:
                        sc = mn.shell_guard.check_pre_command(repo=ws, cmd=cmd, cid=cid)
                        if sc.get("short_circuit"):
                            with self._lock:
                                self._stats["shell_short_circuits"] += 1
                            summary_preview = str(sc.get("summary") or "")[:480]
                            ref_id = sc.get("raw_ref_id") or ""
                            self.sessions.push_advisory(
                                cid,
                                "shell_cache_hit",
                                f"Duplicate read-only shell skipped ({sc.get('age_s')}s ago, ref={ref_id}): {summary_preview[:180]}",
                            )
                            if sc.get("sibling_hit") or os.environ.get("CHIMERA_SHELL_SHORTCIRCUIT", "1") == "1":
                                with self._lock:
                                    self._stats["denies"] += 1
                                return {
                                    "decision": "deny",
                                    "short_circuited": True,
                                    "raw_ref_id": ref_id,
                                    "reason": f"[CHIMERA Shell-ShortCircuit RAM HIT {sc.get('age_s')}s ago, ref={ref_id}] {summary_preview}",
                                }
                    except Exception:
                        pass
                for ab in self.cortex.match_antibodies(cmd, limit=2):
                    self.sessions.push_advisory(
                        cid,
                        "antibody",
                        f"Command trap: {ab.get('error_sig', '')[:80]} -> {ab.get('fix_hint', '')[:120]}",
                    )
                is_heavy = bool(_HEAVY_CMD_RE.search(cmd))
                with self._lock:
                    self._recent_commands.append({
                        "cid": cid,
                        "cmd": cmd[:180],
                        "heavy": is_heavy,
                        "ts": round(time.time(), 3),
                    })
                    if len(self._recent_commands) > 40:
                        self._recent_commands = self._recent_commands[-40:]
                    if is_heavy:
                        self._stats["heavy_commands_tracked"] += 1

                # Safe opt-in Iron Cage delayed sweep for heavy build/test commands (never corrupts user shell semantics)
                if is_heavy and os.environ.get("CHIMERA_IRON_CAGE_WRAP") == "1":
                    def _delayed_cage_sweep() -> None:
                        time.sleep(0.15)
                        try:
                            self.iron_cage.cage_sweep_agent_children()
                        except Exception:
                            pass

                    threading.Thread(
                        target=_delayed_cage_sweep,
                        daemon=True,
                        name="chimera-hook-cage-sweep",
                    ).start()
            return {"decision": "allow"}

        return {"decision": "allow"}

    # --- Event 3: post_tool_use ---

    def _on_post_tool_use(self, body: dict[str, Any]) -> dict[str, Any]:
        cid = _extract_conversation_id(body)
        with self._lock:
            self._worker_heartbeats[cid] = time.time()
        ws = _extract_workspace(body, self.sessions, cid)
        tool_name, args = _extract_tool_call(body)
        tlow = tool_name.lower()
        err_str = _extract_error(body)
        ok = not bool(err_str)

        if not ok and _POLICY_BLOCK_RE.search(err_str):
            self.record_blocker_alert(
                agent_id=cid,
                repo=ws,
                tool_name=tool_name or "unknown",
                reason=err_str,
            )

        raw_paths = _extract_target_paths(args)
        rel_paths = [_to_rel_path(ws, p) for p in raw_paths if p]
        diff_hint = f"Fixed via {tool_name} on {', '.join(rel_paths[:2])}" if (ok and rel_paths) else ""

        distilled = self.cortex.record_tool_outcome(
            cid,
            ws or ".",
            tool_name or "unknown",
            args,
            ok,
            error=err_str,
            diff_hint=diff_hint,
        )
        if distilled is not None:
            with self._lock:
                self._stats["antibodies_distilled"] += 1

        if ok and tlow in _EDIT_TOOLS and ws and rel_paths:
            self.hive.record_mutation(
                agent_id=cid,
                repo=ws,
                files=rel_paths,
                kind=tlow,
                detail=f"step {body.get('stepIdx', '')}",
            )
            for rel in rel_paths:
                self.sessions.record_touched_file(cid, rel)
                self.precog.schedule(cid, ws, rel)
                with self._lock:
                    self._stats["precog_schedules"] += 1

        # CHIMERA-GHOST-POOL Passive Shared Read-Ring ingestion (turns 0-hit Precog into cross-agent hits!)
        if ok and raw_paths:
            prom = self._get_prometheus()
            if prom is not None:
                try:
                    abs_targets = [
                        str((Path(ws) / p).resolve()) if (ws and not Path(p).is_absolute()) else str(Path(p).resolve())
                        for p in raw_paths[:6]
                        if p
                    ]
                    ing = prom.ghost.ingest_paths(abs_targets, source=f"hook:{tlow}")
                    if ing.get("ingested"):
                        with self._lock:
                            self._stats["ghost_ring_ingests"] += int(ing["ingested"])
                except Exception:
                    pass

        # CHIMERA-MNEMOSYNE Dual-Channel PostToolUse Lossless Raw Capture (100% verbatim + <=1.2KB cache!)
        if tlow in _CMD_TOOLS:
            cmd = _extract_command(args)
            out_txt = str(body.get("output") or body.get("stdout") or body.get("result") or "")
            if cmd and out_txt:
                mn = self._get_mnemosyne()
                if mn is not None:
                    try:
                        mn.shell_guard.record_post_command(
                            repo=ws,
                            cmd=cmd,
                            output_text=out_txt,
                            cid=cid,
                            exit_code=0 if ok else 1,
                        )
                        with self._lock:
                            self._stats["raw_tool_captures"] += 1
                    except Exception:
                        pass

        return {}

    # --- Event 4: pre_invocation ---

    def _on_pre_invocation(self, body: dict[str, Any]) -> dict[str, Any]:
        cid = _extract_conversation_id(body)
        with self._lock:
            self._worker_heartbeats[cid] = time.time()
        ws = _extract_workspace(body, self.sessions, cid)

        sections: list[str] = []
        badge_bits: list[str] = []

        # 0) Out-of-band Swarm Dead-Man's Switch / Pre-Tool Policy Blocker Alerts
        if ws:
            self.sweep_dead_man_leases(ws)
        with self._lock:
            last_bseq = self._blocker_cursor.get(cid, 0)
        new_blockers = [
            b for b in self.list_blocker_alerts(repo=ws or None, since_seq=last_bseq)
            if b.get("agent_id") != cid
        ]
        if new_blockers:
            with self._lock:
                self._blocker_cursor[cid] = max(b["seq"] for b in new_blockers)
            bsum = "; ".join(
                f"[{b['kind']}] {b['agent_id']} halted on {b['tool_name']}: {b['reason'][:110]}"
                for b in new_blockers[:3]
            )
            sections.append(f"SWARM BLOCKER: {bsum}")
            badge_bits.append(f"BLOCKED: {len(new_blockers)}")

        # 1) Unseen Precog syntax/compile diagnostics
        diags = self.precog.consume_diagnostics(cid, ws or None)
        if diags:
            formatted = "; ".join(
                f"{d.get('file')}:{d.get('line')} [{d.get('code')}] {d.get('message')}"
                for d in diags[:5]
            )
            sections.append(f"PRECOG DIAGNOSTICS ({len(diags)}): {formatted}")
            badge_bits.append(f"Precog: {len(diags)} err")

        # 2) Newly matched Immune Antibodies & Hive soft-lease advisories
        advisories = self.sessions.drain_advisories(cid)
        if advisories:
            adv_txt = "; ".join(f"[{a['kind']}] {a['message']}" for a in advisories[:4])
            sections.append(f"ALERTS: {adv_txt}")
            badge_bits.append(f"Alerts: {len(advisories)}")

        # 3) Sibling Swarm mutations in the same repo since last invocation
        if ws:
            _, head_now = self.hive.sibling_mutations_since(agent_id=cid, repo=ws, since_seq=0)
            prev_seq = self.sessions.get_and_advance_mutation_seq(cid, head_now)
            sib_muts, _ = self.hive.sibling_mutations_since(agent_id=cid, repo=ws, since_seq=prev_seq)
            if sib_muts:
                msum = "; ".join(
                    f"{m['agent_id']} modified {', '.join((m.get('files') or [])[:3])}"
                    for m in sib_muts[:4]
                )
                sections.append(f"SWARM MUTATIONS: {msum}")
                badge_bits.append(f"Swarm: {len(sib_muts)} mut")

            # 4) Unseen fresh Akashic capsules for recently touched files
            touched = self.sessions.get_touched_files(cid)
            if touched:
                cst = self.cortex.status()
                if cst.get("capsule_count") or cst.get("capsules"):
                    repo_p = Path(ws)
                    fhashes = {}
                    for rel in touched[-6:]:
                        fp = repo_p / rel
                        if fp.is_file():
                            sha = _sha256_file_safe(fp)
                            if sha:
                                fhashes[rel] = sha
                    if fhashes:
                        recalled = self.cortex.recall_for_files(ws, fhashes, limit=4)
                        fresh = self.sessions.filter_unseen_capsules(cid, recalled)
                        if fresh:
                            csum = "; ".join(
                                f"{c.get('rel_path')}:{c.get('symbol')} - {str(c.get('summary', ''))[:90]}"
                                for c in fresh[:3]
                            )
                            sections.append(f"AKASHIC CAPSULES: {csum}")
                            badge_bits.append(f"Capsules: {len(fresh)}")

                # 5) CHIMERA-MNEMOSYNE KV-Safe Append-Only Raw Whisper + 0-token Watchdog
                mn = self._get_mnemosyne()
                if mn is not None:
                    try:
                        mn.primer.register_worker_heartbeat(cid, ws)
                        last_rel = touched[-1]
                        w_key = f"raw_whisper:{ws}:{last_rel}"
                        seen_w = getattr(self, "_seen_whispers", None)
                        if seen_w is None:
                            seen_w = set()
                            self._seen_whispers = seen_w
                        if (cid, w_key) not in seen_w:
                            rec_w = mn.raw.recall(Path(last_rel).name, repo=ws, top_k=2, causal_hops=0, expand_turns=False, max_bytes=700)
                            items_w = [
                                it for it in (rec_w.get("items") or [])
                                if it.get("thread_id") != cid and float(it.get("score") or 0.0) >= 0.45
                            ]
                            if items_w:
                                seen_w.add((cid, w_key))
                                with self._lock:
                                    self._stats["raw_whispers"] += 1
                                w_txt = "; ".join(
                                    f"[{it['source_kind']}/{(it.get('reality') or {}).get('stamp','')}] {it['text'][:110].replace(chr(10),' ')}"
                                    for it in items_w[:2]
                                )
                                sections.append(f"RAW MEMORY WHISPER ({Path(last_rel).name}): {w_txt}")
                                badge_bits.append(f"Raw:{len(items_w)}")
                    except Exception:
                        pass

        if not sections:
            return {"injectSteps": []}

        with self._lock:
            self._stats["pre_invocation_injects"] += 1

        return {
            "injectSteps": [
                {
                    "systemMessage": {
                        "systemMessage": " | ".join(sections)[:1600],
                        "metadata": {
                            "user_markdown": "**CHIMERA Pulse** | " + " | ".join(badge_bits),
                        },
                    }
                }
            ]
        }

    # --- Event 5: post_invocation ---

    def _on_post_invocation(self, body: dict[str, Any]) -> dict[str, Any]:
        cid = _extract_conversation_id(body)
        self.sessions.bump_invocation(
            cid,
            {
                "invocationNum": body.get("invocationNum"),
                "stepIdx": body.get("stepIdx"),
                "terminationReason": body.get("terminationReason"),
            },
        )
        return {"injectSteps": [], "terminationBehavior": ""}

    # --- Event 6: stop ---

    def _on_stop(self, body: dict[str, Any]) -> dict[str, Any]:
        cid = _extract_conversation_id(body)
        ws = _extract_workspace(body, self.sessions, cid)
        continuation_active = bool(body.get("continuationActive") or body.get("continuation_active"))
        term_reason = str(body.get("terminationReason") or body.get("termination_reason") or "").strip()

        if continuation_active or term_reason != "NO_TOOL_CALL":
            return {}

        if not self.precog.has_blocking_errors(cid, ws or None):
            return {}

        errors = self.precog.get_blocking_errors(cid, ws or None)
        summary = "; ".join(
            f"{e.get('file')}:{e.get('line')} [{e.get('code')}] {e.get('message')}"
            for e in errors[:5]
        )
        with self._lock:
            self._stats["stop_continues"] += 1
        return {
            "decision": "continue",
            "reason": f"Chimera Precog detected syntax/compile errors in your edited files: {summary}",
        }

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "ok": True,
                "stats": {
                    **self._stats,
                    "by_event": {k: dict(v) for k, v in self._stats["by_event"].items()},
                },
                "recent_commands": list(self._recent_commands[-8:]),
                "sessions": self.sessions.status(),
            }


# ---------------------------------------------------------------------------
# Unified Facade Attached to ChimeraDaemon
# ---------------------------------------------------------------------------

class OmegaSpineRuntime:
    """Single clean container uniting IronCage, Precog, Tournament, MCP, Hooks & Akashic."""

    def __init__(
        self,
        *,
        ops_dir: Path | None = None,
        ephemeral: bool = False,
        enable_dotnet_build: bool = True,
    ) -> None:
        self.iron_cage = IronCage()
        self.precog = PrecogVerifier(
            iron_cage=self.iron_cage,
            enable_dotnet_build=enable_dotnet_build,
        )
        self.tournament = ShadowTournament(iron_cage=self.iron_cage)
        self.hive = OmegaHiveStore()
        self.sessions = OmegaSessionRegistry()
        db_path = (Path(ops_dir) / "omega_akashic.sqlite") if (ephemeral and ops_dir is not None) else None
        self._db_path = db_path
        self._cortex: Any = None
        self._release_conductor: Any = None
        self.mcp = StreamableMcpServer(
            iron_cage=self.iron_cage,
            precog=self.precog,
            tournament=self.tournament,
            cortex=self.cortex,
            hive=self.hive,
            sessions=self.sessions,
        )
        self.hooks = HookRouter(
            iron_cage=self.iron_cage,
            precog=self.precog,
            cortex=self.cortex,
            hive=self.hive,
            sessions=self.sessions,
        )
        if ephemeral:
            try:
                from ..platform.mnemosyne import MnemosyneCore
                self.hooks._mnemosyne_ref = MnemosyneCore(ephemeral=True)
            except Exception:
                pass
            try:
                from ..platform.prometheus import ChimeraPrometheusCore
                p_dir = (Path(ops_dir) / "prometheus") if ops_dir is not None else (Path.home() / ".chimera_ops" / "prometheus_eph")
                self.hooks._prometheus_ref = ChimeraPrometheusCore(data_dir=p_dir, ephemeral=True)
            except Exception:
                pass
        self.mcp.attach_runtime(self)

    @property
    def release_conductor(self) -> Any:
        if self._release_conductor is None:
            from .release_conductor import ReleaseConductor

            self._release_conductor = ReleaseConductor()
        return self._release_conductor

    @property
    def cortex(self) -> Any:
        if self._cortex is None:
            self._cortex = resolve_akashic_cortex(db_path=self._db_path)
        return self._cortex

    def status(self) -> dict[str, Any]:
        return {
            "ok": True,
            "mcp": self.mcp.status(),
            "hooks": self.hooks.status(),
            "iron_cage": self.iron_cage.status(),
            "precog": self.precog.status(),
            "tournament": self.tournament.status(),
            "hive": self.hive.status(),
            "akashic": self.cortex.status(),
        }

    def close(self) -> None:
        self.iron_cage.close()
        mn = getattr(self.hooks, "_mnemosyne_ref", None)
        if mn is not None and hasattr(mn, "close"):
            try:
                mn.close()
            except Exception:
                pass
        prom = getattr(self.hooks, "_prometheus_ref", None)
        if prom is not None and hasattr(prom, "close"):
            try:
                prom.close()
            except Exception:
                pass
        close_fn = getattr(self._cortex, "close", None)
        if callable(close_fn):
            try:
                close_fn()
            except Exception:
                pass


_DEFAULT_HOOK_LOCK = threading.Lock()
_DEFAULT_HOOK_ROUTER: HookRouter | None = None


def get_hook_router() -> HookRouter:
    global _DEFAULT_HOOK_ROUTER
    with _DEFAULT_HOOK_LOCK:
        if _DEFAULT_HOOK_ROUTER is None:
            _DEFAULT_HOOK_ROUTER = HookRouter()
        return _DEFAULT_HOOK_ROUTER


def handle_hook_event(event_name: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    return get_hook_router().handle_event(event_name, payload)
