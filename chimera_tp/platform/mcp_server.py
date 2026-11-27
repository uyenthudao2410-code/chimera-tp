"""CHIMERA-MCP: Zero-dependency stdio JSON-RPC 2.0 MCP server so AI coding agents auto-discover CHIMERA."""

from __future__ import annotations

import json
import sys
from typing import Any

from .client import connect


_TOOLS = [
    {
        "name": "chimera_capabilities",
        "description": "Discover the live CHIMERA-TP local infrastructure substrate: anchor URL, Egress-Membrane proxy, active cartridges, peer topology, and Zero-Weight RAM.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "chimera_apps",
        "description": "List all linked & online applications attached to CHIMERA-TP plus newly discovered unlinked local server ports.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "chimera_pulse_publish",
        "description": "Publish a real-time event onto CHIMERA-PULSE (shared cross-host event bus between win-desktop and svhome).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "Dot-delimited topic name, e.g. 'radar.alert'"},
                "payload": {"type": "object", "description": "JSON event payload"},
            },
            "required": ["topic", "payload"],
        },
    },
    {
        "name": "chimera_search",
        "description": "Run sub-3ms hybrid AVX2 VSA + BM25 search across a project namespace in CHIMERA-SEARCH.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "namespace": {"type": "string", "description": "App/project namespace"},
                "query": {"type": "string", "description": "Search query"},
                "top_k": {"type": "integer", "description": "Max results (default 10)"},
            },
            "required": ["namespace", "query"],
        },
    },
    {
        "name": "chimera_blackbox_freeze",
        "description": "Freeze the last 60s of dual-node Flight Recorder BlackBox telemetry to disk for post-mortem debugging.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "reason": {"type": "string", "description": "Short reason for freezing the flight recorder"},
            },
            "required": [],
        },
    },
    {
        "name": "chimera_vgpu_route",
        "description": "Query the CHIMERA-VGPU Pareto router (Windows GTX 1650 vs svhome CPU vs Cloud API) for optimal cost/latency placement.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "max_ms": {"type": "number"},
                "max_cost_usd": {"type": "number"},
                "min_tier": {"type": "string"},
            },
            "required": [],
        },
    },
    {
        "name": "chimera_job_resume",
        "description": "Inspect or resume a durable CHIMERA-IMMORTAL-JOB workflow checkpoint by job_id.",
        "inputSchema": {
            "type": "object",
            "properties": {"job_id": {"type": "string"}},
            "required": ["job_id"],
        },
    },
    {
        "name": "chimera_canary_compare",
        "description": "Run Zero-Downtime Canary Twin comparison between baseline_url and canary_url for automated PROMOTE/ROLLBACK verdict.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "baseline_url": {"type": "string"},
                "canary_url": {"type": "string"},
                "samples": {"type": "integer"},
            },
            "required": ["baseline_url", "canary_url"],
        },
    },
    {
        "name": "chimera_compute",
        "description": "Single unified autonomous CHIMERA-VGPU compute tool (embed, matmul, vec_dot, probe): automatically routes heavy CUDA to Google Colab Pro Elastic GPU (auto scale-from-zero, warm reuse, idle auto-stop, 0% Windows GPU load) or local GTX 1650 PTX / AVX2.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_kind": {"type": "string", "enum": ["embed", "matmul", "vec_dot", "probe"]},
                "payload": {"type": "object"},
                "prefer_cuda": {"type": "boolean"},
                "profile": {"type": "string"},
            },
            "required": ["task_kind"],
        },
    },
    {
        "name": "chimera_colab_status",
        "description": "Check live Google Colab Pro/Ultra CLI status, Compute Unit balance, and active sessions (auto-relayed win-desktop -> svhome).",
        "inputSchema": {
            "type": "object",
            "properties": {"refresh": {"type": "boolean"}},
            "required": [],
        },
    },
    {
        "name": "chimera_colab_exec",
        "description": "Dispatch a headless GPU/CUDA compute task (probe, cuda_embed, cuda_matmul) to Google Colab Pro via colab CLI with anti-congestion right-sizing and CU-leak auto-stop (0% Windows GPU impact).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_kind": {"type": "string", "enum": ["probe", "cuda_embed", "cuda_matmul"]},
                "payload": {"type": "object"},
                "profile": {"type": "string", "description": "Optional profile override: CPU, CPU_HIGH_MEM, T4, L4, A100"},
                "require_gpu": {"type": "boolean"},
                "keep_session": {"type": "boolean"},
            },
            "required": ["task_kind"],
        },
    },
    {
        "name": "chimera_hyperdesk_optimize",
        "description": "Diagnose or optimize live Windows/Linux multitasking lag via CHIMERA-HYPERDESK (Focus Cryo, Silicon Wall, Orphan Reaper, Hydra Trim, Sync Dam).",
        "inputSchema": {
            "type": "object",
            "properties": {"dry_run": {"type": "boolean"}},
            "required": [],
        },
    },
    {
        "name": "chimera_hyperdesk_autonomic",
        "description": "Inspect or control CHIMERA's built-in 24/7 autonomous multitasking reflex brain (status, on, off, tick, or policy updates).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["status", "on", "off", "tick"]},
                "policy": {"type": "object"},
            },
            "required": [],
        },
    },
    {
        "name": "chimera_omega_intent",
        "description": "Plan a topology for requested SLA bounds. Read verification_status, observations and invariants_satisfied for measurement evidence. A null invariant has no measurement.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "service": {"type": "string"},
                "invariants": {"type": "object"},
            },
            "required": ["service", "invariants"],
        },
    },
    {
        "name": "chimera_omega_benchmark",
        "description": "Run the end-to-end 25-capability CHIMERA v19-v21 Omega Entity live verification benchmark.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "chimera_nvme_mirage",
        "description": "CHIMERA-NVME-MIRAGE (v23): Elevate hot HDD project folders onto NVMe SSD via atomic NTFS Junctions without changing paths (status, promote, sync, demote, bench).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["status", "promote", "sync", "demote", "bench"]},
                "path": {"type": "string"},
                "dry_run": {"type": "boolean"},
            },
            "required": [],
        },
    },
    {
        "name": "chimera_agent_exile",
        "description": "Run a build on the caller's workstation (target=local) or an admitted SSH peer. Set cwd and sync_workspace for current edits. Declare repeatable work with reuse and a dependency/toolchain environment_id. A busy receiver returns a deferred receipt.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "cmd": {"type": "string"},
                "cwd": {"type": "string"},
                "target": {"type": "string", "enum": ["auto", "local", "svhome", "colab"]},
                "sync_workspace": {"type": "boolean"},
                "reuse": {"type": "boolean"},
                "environment_id": {"type": "string"},
                "artifacts": {"type": "array", "items": {"type": "string"}},
                "require_io_limit": {"type": "boolean"},
                "timeout_s": {"type": "number", "minimum": 1, "maximum": 300},
            },
            "required": ["cmd"],
        },
    },
    {
        "name": "chimera_exile_handoff",
        "description": "Checkpointed generation-fenced CAS job handoff across win-desktop and svhome with single-commit durable receipts.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["handoff", "receipts"]},
                "job_id": {"type": "string"},
                "step_key": {"type": "string"},
                "payload": {},
                "op": {"type": "string"},
                "params": {"type": "object"},
                "steps": {"type": "array"},
                "prefer_target": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": [],
        },
    },
    {
        "name": "chimera_evidence",
        "description": "Inspect or record live scoped capability verification evidence receipts with TTL expiry.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["status", "record"]},
                "capability": {"type": "string"},
                "execution_node": {"type": "string"},
                "fallback_mode": {"type": "string"},
                "ttl_s": {"type": "number"},
                "verified": {"type": "boolean"},
                "violated": {"type": "boolean"},
                "metrics": {"type": "object"},
                "receipt_id": {"type": "string"},
            },
            "required": [],
        },
    },
    {
        "name": "chimera_akashic_symbols",
        "description": "Zero-daemon-RAM exact Python AST symbol index & byte-budgeted definition lookup (replaces dragging whole files into LLM context).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["index", "find"]},
                "repo": {"type": "string", "description": "Git worktree root path"},
                "symbol": {"type": "string", "description": "Symbol or Class.method name (for find)"},
                "snapshot": {"type": "string", "description": "Snapshot SHA from index (auto-indexes if omitted)"},
                "path": {"type": "string", "description": "Optional relative file filter"},
                "limit": {"type": "integer", "default": 6},
                "context_bytes": {"type": "integer", "default": 1200},
            },
            "required": ["repo"],
        },
    },
    {
        "name": "chimera_akashic_recall",
        "description": "Akashic Context Offload: Vietnamese/diacritic-aware FTS5 passage recall, exact-context CAS result reuse, and hybrid VSA/BM25 indexing (0 daemon RSS for SQLite recall).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["find", "save", "show", "index", "reuse_get", "reuse_put", "reuse_suggest"]},
                "query": {"type": "string"},
                "scope": {"type": "string", "default": "default"},
                "limit": {"type": "integer", "default": 10},
                "file": {"type": "string"},
                "url": {"type": "string"},
                "text": {"type": "string"},
                "context": {"type": "string"},
                "line": {"type": "integer"},
                "identity": {"type": "string"},
                "namespace": {"type": "string", "default": "global"},
                "doc_id": {"type": "string"},
                "reuse_context": {"type": "object"},
                "question": {"type": "string"},
                "result": {"type": "string"},
                "ttl": {"type": "integer", "default": 3600},
            },
            "required": ["action"],
        },
    },
    {
        "name": "chimera_timemachine",
        "description": "Turn-Atomic Workspace Time-Machine: FileRevisions FastCDC turn checkpoints, conflict-checked atomic os.replace rollback, and conduit turn ledger (0 persistent daemon RSS).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["checkpoint", "finalize", "rollback", "list", "turns", "history"]},
                "turn_id": {"type": "string"},
                "root": {"type": "string"},
                "rel_paths": {"type": "array", "items": {"type": "string"}},
                "file": {"type": "string"},
                "force": {"type": "boolean", "default": False},
                "limit": {"type": "integer", "default": 20},
                "meta": {"type": "object"},
            },
            "required": ["action"],
        },
    },
    {
        "name": "chimera_forensics",
        "description": "Inspect live KV-cache prefix break forensic diffs, Precognition tap stats, Multi-PoP/Dual-Hemisphere egress bandit, FlightRecorder forensic ring, or Medic triage.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["kv_forensics", "precog_stats", "egress_pops", "blackbox_forensics", "diagnose", "medic"]},
                "kind": {"type": "string"},
                "limit": {"type": "integer", "default": 32},
            },
            "required": [],
        },
    },
    {
        "name": "chimera_speculative_warm",
        "description": "Bounded 64 KiB streaming OS page-cache path warming (0 retained RAM) and strictly allowlisted read-only speculative check via isolated guarded_build.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "paths": {"type": "array", "items": {"type": "string"}},
                "command": {"type": "string", "description": "Optional strictly read-only allowlisted command (e.g. 'git status', 'pytest --collect-only')"},
                "cwd": {"type": "string"},
                "budget_bytes": {"type": "integer", "default": 2097152},
                "execute": {"type": "boolean", "default": False},
            },
            "required": [],
        },
    },
    {
        "name": "chimera_xray_batch",
        "description": "CHIMERA-OMNI-PROBE (Organ 3): Execute up to 40 read-only forensic ops (file_slice, regex_search, list_files, json_query, http_get, sqlite_ro, git_status, raw_ref) concurrently in-process in milliseconds with ZERO PowerShell/Node/Python cold-boot spawns.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ops": {
                    "type": "array",
                    "description": "List of op dicts. Supported ops & keys: outline(path,limit), file_slice(path,start_line,end_line|ranges|skip,first|tail_lines), regex_search(path,pattern,max_hits|limit,glob,context), list_files(path,glob|pattern,limit), json_query(path,jpath|jpaths), http_get(url,jpath|jpaths,timeout_s), sqlite_ro(db,sql,limit), git_status(path,limit,max_chars), raw_ref(ref_id,start_line,max_lines).",
                    "items": {"type": "object"},
                },
                "cwd": {"type": "string", "description": "Optional base workspace path for relative paths"},
                "max_workers": {"type": "integer", "default": 8},
                "compact": {"type": "boolean", "default": True},
                "agent_id": {"type": "string", "description": "Optional caller agent id for Hive-Mind conflict radar"},
            },
            "required": ["ops"],
        },
    },
    {
        "name": "chimera_callgraph_slice",
        "description": "CHIMERA-CALLGRAPH-TELEPATHY (Organ 3): Multi-language (Python AST + JS/TS/Rust) 2-hop definition + callers + callees + related tests bundle packed under a compact character budget (eliminates serial grep/read ping-pong).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo": {"type": "string", "description": "Repository root path"},
                "symbol": {"type": "string", "description": "Function, method, or class name (e.g. 'resolveDesktopBareModelAlias' or 'Class.method')"},
                "depth": {"type": "integer", "default": 2},
                "include_tests": {"type": "boolean", "default": True},
                "max_chars": {"type": "integer", "default": 4500},
            },
            "required": ["repo", "symbol"],
        },
    },
    {
        "name": "chimera_commit_verify",
        "description": "CHIMERA-ATOMIC-COMMIT-VERIFY (Organ 3): Single-shot parallel py_compile + node --check + import-graph impacted unittest runner with BLAKE2s result memoization and Token-Diet stdout compaction (0 PowerShell spawns).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo": {"type": "string", "description": "Repository root path"},
                "files": {"type": "array", "items": {"type": "string"}, "description": "Optional explicit relative file list (auto-detects git dirty files if omitted)"},
                "run_tests": {"type": "boolean", "default": True},
                "explicit_tests": {"type": "array", "items": {"type": "string"}},
                "max_tests": {"type": "integer", "default": 4},
                "timeout_s": {"type": "number", "default": 60.0},
                "use_cache": {"type": "boolean", "default": True},
                "compact": {"type": "boolean", "default": True},
            },
            "required": ["repo"],
        },
    },
    {
        "name": "chimera_hive",
        "description": "CHIMERA-HIVEMIND (Organ 3 Symbiont): Multi-agent soft intent leases, live conflict radar across Codex/Claude/Antigravity, and persistent Immune Reflex warnings.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["status", "lease", "release", "immune_add", "immune_list", "mutate"], "default": "status"},
                "agent_id": {"type": "string", "default": "agent"},
                "repo": {"type": "string"},
                "files": {"type": "array", "items": {"type": "string"}},
                "intent": {"type": "string"},
                "lease_action": {"type": "string", "default": "edit"},
                "ttl_s": {"type": "number", "default": 120.0},
                "pattern": {"type": "string"},
                "warning": {"type": "string"},
                "scope": {"type": "string", "default": "global"},
                "severity": {"type": "string", "default": "warn"},
                "limit": {"type": "integer", "default": 32},
            },
            "required": [],
        },
    },
    {
        "name": "chimera_atomic_patch",
        "description": "CHIMERA-SURGEON (Organ 3 Symbiont): Transactional multi-file edit with in-RAM Pre-Commit Format Gate (AST/TOML/JSON/JS checked BEFORE touching disk), atomic os.replace, impacted test verification, and exact byte-level auto-rollback on failure.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo": {"type": "string", "description": "Repository root path"},
                "edits": {
                    "type": "array",
                    "description": "List of edit dicts: {path, target, replacement, replace_all?} or {path, content}",
                    "items": {"type": "object"},
                },
                "agent_id": {"type": "string", "default": "agent"},
                "run_tests": {"type": "boolean", "default": True},
                "explicit_tests": {"type": "array", "items": {"type": "string"}},
                "rollback_on_fail": {"type": "boolean", "default": True},
                "max_tests": {"type": "integer", "default": 4},
                "timeout_s": {"type": "number", "default": 60.0},
                "record_immune_on_gate_fail": {"type": "boolean", "default": False},
            },
            "required": ["repo", "edits"],
        },
    },
    {
        "name": "chimera_precog",
        "description": "CHIMERA-PRECOG-RUNNER (Organ 3 Symbiont): <2ms incremental AST single-file refresh, speculative background test verification while the LLM thinks (so commit_verify returns in <15ms), and optional Win32 ReadDirectoryChangesW repo watcher.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["status", "notify_save", "watch_start", "watch_stop"], "default": "status"},
                "repo": {"type": "string"},
                "files": {"type": "array", "items": {"type": "string"}},
                "run_shadow_test": {"type": "boolean", "default": True},
                "explicit_tests": {"type": "array", "items": {"type": "string"}},
                "max_tests": {"type": "integer", "default": 2},
                "timeout_s": {"type": "number", "default": 25.0},
                "agent_id": {"type": "string", "default": "precog"},
            },
            "required": [],
        },
    },
    {
        "name": "chimera_handoff_capsule",
        "description": "CHIMERA-TELEPATHY-CAPSULE (Organ 3 Symbiont): Create or load a <1,500-token verified workspace brain capsule (git stat, active Hive leases, BLAKE2s verified test receipts, Immune warnings, symbol cards) for 50ms cross-agent handoff.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["create", "load", "list"], "default": "load"},
                "repo": {"type": "string"},
                "capsule_id": {"type": "string", "default": "latest"},
                "agent_id": {"type": "string", "default": "agent"},
                "summary": {"type": "string"},
                "focus_files": {"type": "array", "items": {"type": "string"}},
                "focus_symbols": {"type": "array", "items": {"type": "string"}},
                "next_steps": {"type": "array", "items": {"type": "string"}},
                "include_git": {"type": "boolean", "default": True},
                "limit": {"type": "integer", "default": 10},
            },
            "required": [],
        },
    },
    {
        "name": "chimera_bootstrap",
        "description": "CHIMERA-SESSION-BOOTSTRAP (Organ 3 Symbiont): <25ms, <=1.5KB live multi-agent workspace snapshot (2-level tree, git state, active Hive leases, BLAKE2s verified test receipts, Immune warnings, latest capsule) eliminating cold-start exploration turns.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo": {"type": "string", "description": "Repository root path"},
                "agent_id": {"type": "string", "default": "agent"},
            },
            "required": ["repo"],
        },
    },
    {
        "name": "chimera_mirror_race",
        "description": "CHIMERA-MIRROR-RACE (Organ 3 Symbiont): Race 2-3 competing multi-file patch candidates concurrently in isolated shadow directories, commit ONLY the fastest 100%-passing winner atomically, and discard all losing shadows.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo": {"type": "string"},
                "candidates": {
                    "type": "array",
                    "description": "List of {id, edits: [{path, target, replacement}]} candidate patch sets",
                    "items": {"type": "object"},
                },
                "explicit_tests": {"type": "array", "items": {"type": "string"}},
                "commit_winner": {"type": "boolean", "default": True},
                "max_tests": {"type": "integer", "default": 4},
                "timeout_s": {"type": "number", "default": 45.0},
                "agent_id": {"type": "string", "default": "agent"},
                "offload_peer": {"type": "boolean", "default": False},
                "peer_host": {"type": "string", "default": "svhome"},
                "peer_repo": {"type": "string"},
            },
            "required": ["repo", "candidates"],
        },
    },
    {
        "name": "chimera_coroner",
        "description": "CHIMERA-POST-MORTEM-CORONER (Organ 3 Symbiont): Read-only session-log scanner for recent Codex/Antigravity JSONLs detecting shell storms, output.txt spills, TOML/syntax breaks, release 404 drift, and EDQUOT errors — optionally auto-seeding persistent Immune Reflex rules.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "log_files": {"type": "array", "items": {"type": "string"}},
                "auto_seed_immune": {"type": "boolean", "default": False},
                "max_files": {"type": "integer", "default": 6},
            },
            "required": [],
        },
    },
    {
        "name": "chimera_soft_shield",
        "description": "CHIMERA-SOFT-PRIORITY-SHIELD (Organ 4 HyperDesk): Doctrine Law-2-safe multitasking shield preserving full 12-thread Turbo (NO hard affinity, NO EcoQoS, NO gateway throttling) while elevating interactive VIP UIs to ABOVE_NORMAL and demoting headless build/test child workers to BELOW_NORMAL + IoPriorityLow.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["apply", "restore"], "default": "apply"},
                "promote_vips": {"type": "boolean", "default": True},
                "demote_batch": {"type": "boolean", "default": True},
                "extra_batch_pids": {"type": "array", "items": {"type": "integer"}},
                "dry_run": {"type": "boolean", "default": False},
            },
            "required": [],
        },
    },
    {
        "name": "chimera_exec",
        "description": "CHIMERA-EXEC (Zero-Spill Direct Runner): Execute argv directly (NO PowerShell, NO node tool-log.mjs, NO conhost, BELOW_NORMAL) with LF-normalized stdin_text and failure-first smart excerpting backed by Dev Drive logs.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "argv": {"type": "array", "items": {"type": "string"}},
                "cwd": {"type": "string", "default": "."},
                "stdin_text": {"type": "string"},
                "normalize_lf": {"type": "boolean", "default": True},
                "env_overrides": {"type": "object"},
                "timeout_s": {"type": "number", "default": 60.0},
                "max_preview_chars": {"type": "integer", "default": 2400},
            },
            "required": ["argv"],
        },
    },
    {
        "name": "chimera_run_dag",
        "description": "CHIMERA-MACRO-DAG (Zero-Turn Pipeline): Collapse 5-16 serial probe/sha256_parity/patch/verify/exec/epoch steps into ONE conditional DAG RPC (saving 5-15 LLM round-trips).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "steps": {
                    "type": "array",
                    "description": "Ordered list of {id, kind: xray|patch|verify|exec|sha256_parity|epoch, on_fail: stop|continue, if_prev_ok, ...}",
                    "items": {"type": "object"},
                },
                "cwd": {"type": "string", "default": "."},
                "agent_id": {"type": "string", "default": "agent"},
            },
            "required": ["steps"],
        },
    },
    {
        "name": "chimera_worktree_epoch",
        "description": "CHIMERA-WORKTREE-EPOCH: Create/list/remove isolated CoW Dev-Drive git worktrees (V:\\worktrees / /mnt/chimera-dev/worktrees) and coordinate Release-Epoch locks/signed publish receipts across concurrent Codex, Claude, and Antigravity agents.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["create", "list", "remove", "epoch_claim", "epoch_publish", "epoch_status"],
                    "default": "epoch_status",
                },
                "repo": {"type": "string"},
                "worktree_path": {"type": "string"},
                "ref": {"type": "string", "default": "HEAD"},
                "name": {"type": "string"},
                "release_dir": {"type": "string"},
                "agent_id": {"type": "string", "default": "agent"},
                "intent": {"type": "string"},
                "files": {"type": "array", "items": {"type": "string"}},
                "sha256_map": {"type": "object"},
                "verified_summary": {"type": "string"},
                "daemon_pid": {"type": "integer"},
                "ttl_s": {"type": "number", "default": 180.0},
            },
            "required": ["action"],
        },
    },
    {
        "name": "chimera_release_promote",
        "description": "CHIMERA-RELEASE-PROMOTE (Single-Gate Immutable Release Plane): Atomically syntax-gate, backup, promote verified files into a live release snapshot with isolated canary import verification, signed Release-Epoch receipt, and <1s rollback.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["promote", "rollback", "status"], "default": "status"},
                "source_dir": {"type": "string"},
                "target_dir": {"type": "string"},
                "files": {"type": "array", "items": {"type": "string"}},
                "agent_id": {"type": "string", "default": "agent"},
                "snapshot_root": {"type": "string"},
                "canary_imports": {"type": "array", "items": {"type": "string"}},
                "verified_summary": {"type": "string"},
                "dry_run": {"type": "boolean", "default": False},
                "epoch_id": {"type": "string"},
                "rollback_dir": {"type": "string"},
            },
            "required": ["action"],
        },
    },
]


def handle_mcp_request(msg: dict[str, Any], anchor_url: str | None = None) -> dict[str, Any] | None:
    method = str(msg.get("method") or "")
    req_id = msg.get("id")
    params = msg.get("params") or {}

    if method == "notifications/initialized":
        return None

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "chimera-mcp", "version": "16.0.0"},
            },
        }

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": _TOOLS}}

    if method == "tools/call":
        tname = str(params.get("name") or "")
        args = params.get("arguments") or {}
        client = connect(app="chimera-mcp", anchor_url=anchor_url, auto_register=False)
        try:
            if tname == "chimera_capabilities":
                out = client.capabilities()
            elif tname == "chimera_apps":
                out = client._get_json("/v1/apps/list") if client.available else {"available": False, "apps": []}
            elif tname == "chimera_pulse_publish":
                out = client.pulse_publish(str(args.get("topic", "mcp.event")), args.get("payload", {}))
            elif tname == "chimera_search":
                out = client.search(
                    query=str(args.get("query", "")),
                    namespace=str(args.get("namespace", "global")),
                    top_k=int(args.get("top_k", 10)),
                )
            elif tname == "chimera_blackbox_freeze":
                out = client.freeze_blackbox(reason=str(args.get("reason", "mcp_freeze")))
            elif tname == "chimera_vgpu_route":
                out = client.pareto_route(
                    max_ms=float(args.get("max_ms", 500.0)),
                    max_cost_usd=float(args.get("max_cost_usd", 0.0)),
                    min_tier=str(args.get("min_tier", "standard")),
                )
            elif tname == "chimera_job_resume":
                out = client.job_resume(str(args.get("job_id", "")))
            elif tname == "chimera_canary_compare":
                out = client.canary_compare(
                    baseline_url=str(args.get("baseline_url", "")),
                    canary_url=str(args.get("canary_url", "")),
                    samples=int(args.get("samples", 5)),
                )
            elif tname == "chimera_compute":
                out = client.compute(
                    task_kind=str(args.get("task_kind", "probe")),
                    payload=args.get("payload") if isinstance(args.get("payload"), dict) else {},
                    prefer_cuda=bool(args.get("prefer_cuda", False)),
                    profile=args.get("profile") or None,
                )
            elif tname == "chimera_colab_status":
                out = client.colab_status(refresh=bool(args.get("refresh", False)))
            elif tname == "chimera_colab_exec":
                out = client.colab_exec(
                    task_kind=str(args.get("task_kind", "probe")),
                    payload=args.get("payload") if isinstance(args.get("payload"), dict) else {},
                    profile=args.get("profile") or None,
                    require_gpu=bool(args.get("require_gpu", False)),
                    keep_session=bool(args.get("keep_session", False)),
                )
            elif tname == "chimera_hyperdesk_optimize":
                out = client.hyperdesk_optimize(dry_run=bool(args.get("dry_run", False)))
            elif tname == "chimera_hyperdesk_autonomic":
                out = client.hyperdesk_autonomic(
                    action=str(args.get("action") or "status"),
                    policy=args.get("policy") if isinstance(args.get("policy"), dict) else None,
                )
            elif tname == "chimera_omega_intent":
                out = client.intent_compile(str(args.get("service", "app")), dict(args.get("invariants") or {}))
            elif tname == "chimera_omega_benchmark":
                out = client.omega_benchmark()
            elif tname == "chimera_nvme_mirage":
                out = client.nvme_mirage(
                    action=str(args.get("action") or "status"),
                    path=str(args.get("path") or ""),
                    dry_run=bool(args.get("dry_run", False)),
                )
            elif tname == "chimera_agent_exile":
                out = client.agent_exile(
                    cmd=str(args.get("cmd") or ""),
                    cwd=args.get("cwd") or None,
                    target=str(args.get("target") or "auto"),
                    sync_workspace=bool(args.get("sync_workspace", False)),
                    reuse=args.get("reuse") is True,
                    environment_id=args.get("environment_id", ""),
                    artifacts=args.get("artifacts", []),
                    require_io_limit=args.get("require_io_limit") is True,
                    timeout_s=float(args.get("timeout_s", 120.0)),
                )
            elif tname == "chimera_exile_handoff":
                act = str(args.get("action") or "handoff").lower()
                if act == "receipts":
                    out = client.exile_receipts(
                        job_id=args.get("job_id") or None,
                        limit=int(args.get("limit") or 50),
                    )
                else:
                    out = client.exile_handoff(
                        steps=args.get("steps") if isinstance(args.get("steps"), list) else None,
                        payload=args.get("payload"),
                        op=str(args.get("op") or "sha256_manifest"),
                        params=args.get("params") if isinstance(args.get("params"), dict) else None,
                        job_id=args.get("job_id") or None,
                        prefer_target=args.get("prefer_target") or None,
                        step_key=str(args.get("step_key") or "step_0"),
                    )
            elif tname == "chimera_evidence":
                act = str(args.get("action") or "status").lower()
                if act == "record":
                    out = client.evidence_record(
                        str(args.get("capability") or ""),
                        execution_node=args.get("execution_node") or None,
                        fallback_mode=args.get("fallback_mode"),
                        ttl_s=float(args.get("ttl_s") if args.get("ttl_s") is not None else 300.0),
                        verified=bool(args.get("verified", True)),
                        violated=bool(args.get("violated", False)),
                        metrics=args.get("metrics") if isinstance(args.get("metrics"), dict) else None,
                        receipt_id=args.get("receipt_id"),
                    )
                else:
                    out = client.evidence(capability=args.get("capability") or None)
            elif tname == "chimera_akashic_symbols":
                from pathlib import Path as _Path
                from . import swarm_symbols

                repo = _Path(str(args.get("repo") or ".")).resolve()
                store = _Path.home() / ".chimera" / "aether" / "swarm_symbols"
                store.mkdir(parents=True, exist_ok=True)
                act = str(args.get("action") or ("find" if args.get("symbol") else "index")).lower()
                if act == "index":
                    out = swarm_symbols.index(repo, store)
                else:
                    snap = str(args.get("snapshot") or "").strip()
                    if not snap:
                        idx_res = swarm_symbols.index(repo, store)
                        snap = str(idx_res.get("snapshot") or "")
                    out = swarm_symbols.find(
                        repo,
                        store,
                        snap,
                        str(args.get("symbol") or ""),
                        path=(str(args.get("path")) if args.get("path") else None),
                        limit=int(args.get("limit") or 6),
                        context_bytes=int(args.get("context_bytes") or 1200),
                    )
            elif tname == "chimera_akashic_recall":
                from pathlib import Path as _Path
                from . import source_recall
                from .result_reuse import ResultReuse

                aether_dir = _Path.home() / ".chimera" / "aether"
                aether_dir.mkdir(parents=True, exist_ok=True)
                recall_db = aether_dir / "recall.sqlite"
                reuse_db = aether_dir / "results.sqlite"
                act = str(args.get("action") or "find").lower()
                scope = str(args.get("scope") or "default")
                if act == "find":
                    rows = source_recall.find(recall_db, str(args.get("query") or ""), scope=scope, limit=int(args.get("limit") or 10))
                    out = {"ok": True, "scope": scope, "count": len(rows), "results": rows}
                elif act == "save":
                    out = source_recall.save(
                        recall_db,
                        file=(str(args.get("file")) if args.get("file") else None),
                        url=(str(args.get("url")) if args.get("url") else None),
                        text=(str(args.get("text")) if args.get("text") else None),
                        context=str(args.get("context") or ""),
                        line=(int(args["line"]) if args.get("line") is not None else None),
                        scope=scope,
                    )
                elif act == "show":
                    out = source_recall.show(recall_db, str(args.get("identity") or ""), scope=scope)
                elif act == "index":
                    out = client.search_index(
                        namespace=str(args.get("namespace") or "global"),
                        doc_id=str(args.get("doc_id") or ""),
                        text=str(args.get("text") or ""),
                    )
                elif act == "reuse_get":
                    rr = ResultReuse(reuse_db)
                    raw = rr.get(dict(args.get("reuse_context") or {}), str(args.get("question") or ""))
                    out = {"ok": True, "found": raw is not None, "result": (raw.decode("utf-8", errors="replace") if raw is not None else None)}
                elif act == "reuse_put":
                    rr = ResultReuse(reuse_db)
                    out = rr.put(
                        dict(args.get("reuse_context") or {}),
                        str(args.get("question") or ""),
                        str(args.get("result") or "").encode("utf-8"),
                        ttl=int(args.get("ttl") or 3600),
                    )
                elif act == "reuse_suggest":
                    rr = ResultReuse(reuse_db)
                    out = {"ok": True, "suggestions": rr.suggest(dict(args.get("reuse_context") or {}), str(args.get("query") or args.get("question") or ""))}
                else:
                    out = {"ok": False, "error": f"unknown_recall_action:{act}"}
            elif tname == "chimera_timemachine":
                from pathlib import Path as _Path
                from .file_revisions import FileRevisions
                from .precog_conduit import TurnTimeMachine

                act = str(args.get("action") or "list").lower()
                tm = TurnTimeMachine()
                if act == "checkpoint":
                    out = tm.checkpoint_turn(
                        str(args.get("turn_id") or ""),
                        str(args.get("root") or "."),
                        list(args.get("rel_paths") or []),
                        meta=args.get("meta") if isinstance(args.get("meta"), dict) else None,
                    )
                elif act == "finalize":
                    out = tm.finalize_turn(str(args.get("turn_id") or ""))
                elif act == "rollback":
                    out = tm.rollback_turn(str(args.get("turn_id") or ""), force=bool(args.get("force", False)))
                elif act == "list":
                    out = {"ok": True, "checkpoints": tm.list_checkpoints(limit=int(args.get("limit") or 20))}
                elif act == "turns":
                    out = client.openai_turns(limit=int(args.get("limit") or 20))
                elif act == "history":
                    fpath = _Path(str(args.get("file") or ""))
                    out = {"ok": True, "file": str(fpath), "history": FileRevisions(tm.db_path).history(fpath)}
                else:
                    out = {"ok": False, "error": f"unknown_timemachine_action:{act}"}
            elif tname == "chimera_forensics":
                act = str(args.get("action") or "kv_forensics").lower()
                lim = int(args.get("limit") or 32)
                if act == "kv_forensics":
                    out = client.openai_forensics(limit=lim)
                elif act == "precog_stats":
                    out = client.openai_precog_stats()
                elif act == "egress_pops":
                    out = client.egress_pops()
                elif act == "blackbox_forensics":
                    out = client.blackbox_forensics(kind=str(args.get("kind") or ""), limit=lim)
                elif act == "diagnose":
                    out = client.hyperdesk_diagnose()
                elif act == "medic":
                    from ..medic import MedicEngine

                    out = MedicEngine().investigate()
                else:
                    out = {"ok": False, "error": f"unknown_forensics_action:{act}"}
            elif tname == "chimera_speculative_warm":
                from .precog_conduit import validate_readonly_command, warm_file_paths

                res: dict[str, Any] = {"ok": True}
                paths = list(args.get("paths") or [])
                if paths:
                    res["page_cache"] = warm_file_paths(paths, budget_bytes=int(args.get("budget_bytes") or 2 * 1024 * 1024))
                cmd = str(args.get("command") or "").strip()
                if cmd:
                    ok_cmd, clean_argv, reason = validate_readonly_command(cmd)
                    res["command_validation"] = {"ok": ok_cmd, "argv": clean_argv, "reason": reason}
                    if ok_cmd and bool(args.get("execute", False)) and args.get("cwd"):
                        from . import guarded_build
                        from .precog_conduit import subprocess_join
                        import os as _os
                        import shlex as _shlex

                        cmd_str = subprocess_join(clean_argv) if _os.name == "nt" else " ".join(_shlex.quote(a) for a in clean_argv)
                        res["speculative_exec"] = guarded_build.submit_isolated(
                            cmd_str,
                            cwd=str(args["cwd"]),
                            target="local",
                            sync=True,
                            reuse=True,
                            environment_id="mcp-speculative-ro-v1",
                            timeout_s=20,
                        )
                out = res
            elif tname == "chimera_xray_batch":
                out = client.xray_batch(
                    list(args.get("ops") or []),
                    cwd=(str(args["cwd"]) if args.get("cwd") else None),
                    max_workers=int(args.get("max_workers") or 8),
                    compact=bool(args.get("compact", True)),
                    agent_id=str(args.get("agent_id") or ""),
                )
            elif tname == "chimera_callgraph_slice":
                out = client.callgraph_slice(
                    str(args.get("repo") or "."),
                    str(args.get("symbol") or ""),
                    depth=int(args.get("depth") if args.get("depth") is not None else 2),
                    include_tests=bool(args.get("include_tests", True)),
                    max_chars=int(args.get("max_chars") or 4500),
                )
            elif tname == "chimera_commit_verify":
                out = client.commit_verify(
                    str(args.get("repo") or "."),
                    files=(list(args["files"]) if isinstance(args.get("files"), list) else None),
                    run_tests=bool(args.get("run_tests", True)),
                    explicit_tests=(list(args["explicit_tests"]) if isinstance(args.get("explicit_tests"), list) else None),
                    max_tests=int(args.get("max_tests") or 4),
                    timeout_s=float(args.get("timeout_s") or 60.0),
                    use_cache=bool(args.get("use_cache", True)),
                    compact=bool(args.get("compact", True)),
                )
            elif tname == "chimera_hive":
                out = client.agent_hive(
                    str(args.get("action") or "status"),
                    **{k: v for k, v in args.items() if k != "action"},
                )
            elif tname == "chimera_atomic_patch":
                out = client.atomic_patch(
                    str(args.get("repo") or "."),
                    list(args.get("edits") or []),
                    agent_id=str(args.get("agent_id") or "agent"),
                    run_tests=bool(args.get("run_tests", True)),
                    explicit_tests=(list(args["explicit_tests"]) if isinstance(args.get("explicit_tests"), list) else None),
                    rollback_on_fail=bool(args.get("rollback_on_fail", True)),
                    max_tests=int(args.get("max_tests") or 4),
                    timeout_s=float(args.get("timeout_s") or 60.0),
                    record_immune_on_gate_fail=bool(args.get("record_immune_on_gate_fail", False)),
                )
            elif tname == "chimera_precog":
                out = client.agent_precog(
                    str(args.get("action") or "status"),
                    **{k: v for k, v in args.items() if k != "action"},
                )
            elif tname == "chimera_handoff_capsule":
                out = client.agent_capsule(
                    str(args.get("action") or "load"),
                    **{k: v for k, v in args.items() if k != "action"},
                )
            elif tname == "chimera_bootstrap":
                out = client.agent_bootstrap(
                    str(args.get("repo") or "."),
                    agent_id=str(args.get("agent_id") or "agent"),
                )
            elif tname == "chimera_mirror_race":
                out = client.mirror_race(
                    str(args.get("repo") or "."),
                    list(args.get("candidates") or []),
                    explicit_tests=(list(args["explicit_tests"]) if isinstance(args.get("explicit_tests"), list) else None),
                    commit_winner=bool(args.get("commit_winner", True)),
                    max_tests=int(args.get("max_tests") or 4),
                    timeout_s=float(args.get("timeout_s") or 45.0),
                    agent_id=str(args.get("agent_id") or "agent"),
                    offload_peer=bool(args.get("offload_peer", False)),
                    peer_host=str(args.get("peer_host") or "svhome"),
                    peer_repo=(str(args["peer_repo"]) if args.get("peer_repo") else None),
                )
            elif tname == "chimera_coroner":
                out = client.agent_coroner(
                    log_files=(list(args["log_files"]) if isinstance(args.get("log_files"), list) else None),
                    auto_seed_immune=bool(args.get("auto_seed_immune", False)),
                    max_files=int(args.get("max_files") or 6),
                )
            elif tname == "chimera_soft_shield":
                out = client.hyperdesk_soft_shield(
                    action=str(args.get("action") or "apply"),
                    promote_vips=bool(args.get("promote_vips", True)),
                    demote_batch=bool(args.get("demote_batch", True)),
                    extra_batch_pids=(list(args["extra_batch_pids"]) if isinstance(args.get("extra_batch_pids"), list) else None),
                    dry_run=bool(args.get("dry_run", False)),
                )
            elif tname == "chimera_exec":
                out = client.agent_exec(
                    list(args.get("argv") or []),
                    cwd=str(args.get("cwd") or "."),
                    stdin_text=args.get("stdin_text"),
                    normalize_lf=bool(args.get("normalize_lf", True)),
                    env_overrides=(dict(args["env_overrides"]) if isinstance(args.get("env_overrides"), dict) else None),
                    timeout_s=float(args.get("timeout_s") or 60.0),
                    max_preview_chars=int(args.get("max_preview_chars") or 2400),
                )
            elif tname == "chimera_run_dag":
                out = client.agent_run_dag(
                    list(args.get("steps") or []),
                    cwd=str(args.get("cwd") or "."),
                    agent_id=str(args.get("agent_id") or "agent"),
                )
            elif tname == "chimera_worktree_epoch":
                out = client.agent_worktree_epoch(
                    str(args.get("action") or "epoch_status"),
                    **{k: v for k, v in args.items() if k != "action"},
                )
            elif tname == "chimera_release_promote":
                out = client.agent_release_promote(
                    str(args.get("action") or "status"),
                    **{k: v for k, v in args.items() if k != "action"},
                )
            else:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32601, "message": f"Unknown tool: {tname}"},
                }
            compact_wire = tname in (
                "chimera_xray_batch",
                "chimera_callgraph_slice",
                "chimera_commit_verify",
                "chimera_hive",
                "chimera_atomic_patch",
                "chimera_precog",
                "chimera_handoff_capsule",
                "chimera_bootstrap",
                "chimera_mirror_race",
                "chimera_coroner",
                "chimera_soft_shield",
                "chimera_exec",
                "chimera_run_dag",
                "chimera_worktree_epoch",
                "chimera_release_promote",
            )
            payload_text = (
                json.dumps(out, separators=(",", ":"), ensure_ascii=False)
                if compact_wire
                else json.dumps(out, indent=2, ensure_ascii=False)
            )
            # Hard <= 8,600 B UTF-8 inline Spill-Shield (prevents Antigravity output.txt disk spills!)
            if compact_wire and bool(args.get("compact", True)):
                raw_b = payload_text.encode("utf-8", errors="replace")
                if len(raw_b) > 8600 and isinstance(out, dict):
                    from .agent_probe import get_default_agent_bus

                    ref_id = get_default_agent_bus().compactor._put_raw(payload_text)
                    trimmed = dict(out)
                    if isinstance(trimmed.get("results"), list):
                        slim_results = []
                        per_cap = max(350, 6200 // max(1, len(trimmed["results"])))
                        for item in trimmed["results"]:
                            if isinstance(item, dict) and isinstance(item.get("text"), str) and len(item["text"]) > per_cap:
                                ic = dict(item)
                                ic["text"] = item["text"][:per_cap] + f"\n... [spill-shield; raw_ref={ref_id}]"
                                ic["spill_capped"] = True
                                slim_results.append(ic)
                            else:
                                slim_results.append(item)
                        trimmed["results"] = slim_results
                    elif isinstance(trimmed.get("snippets"), list):
                        trimmed["snippets"] = [
                            (dict(s, code=str(s.get("code", ""))[:700]) if isinstance(s, dict) else s)
                            for s in trimmed["snippets"][:3]
                        ]
                    trimmed["spill_shield"] = {"capped": True, "raw_bytes": len(raw_b), "ref_id": ref_id}
                    payload_text = json.dumps(trimmed, separators=(",", ":"), ensure_ascii=False)
                    if len(payload_text.encode("utf-8", errors="replace")) > 8600:
                        payload_text = payload_text[:8350] + f'...","spill_shield_ref":"{ref_id}"}}'
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": payload_text}],
                },
            }
        except Exception as exc:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "isError": True,
                    "content": [{"type": "text", "text": json.dumps({"error": str(exc)})}],
                },
            }

    if req_id is None:
        return None
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def serve_mcp_stdio(anchor_url: str | None = None) -> int:
    """Run line-delimited JSON-RPC 2.0 MCP server on stdin/stdout."""
    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception:
            continue
        resp = handle_mcp_request(msg, anchor_url=anchor_url)
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()
    return 0
