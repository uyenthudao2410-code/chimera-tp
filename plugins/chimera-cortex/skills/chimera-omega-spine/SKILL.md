---
name: chimera-omega-spine
description: >-
  Use this skill to run ultra-fast C#/.NET, Python, and JavaScript codebase navigation,
  atomic syntax-gated edits, Iron-Cage impacted verification, and Akashic Swarm memory
  handoffs through the Chimera Omega-Spine Streamable HTTP MCP server and lifecycle hooks.
---

# Chimera Omega-Spine Workflow

Use Chimera's 6 Eager Streamable HTTP Super-Tools (`http://127.0.0.1:9780/mcp`) with an explicit absolute `repo` argument on every call.

## Standard Execution Loop

1. **Orient (`chimera_bootstrap`)**
   - Call `chimera_bootstrap` with `{"repo": "<abs_workspace>"}` to load git branch/dirty state, top files, active Hive leases, matching Akashic symbol capsules, and Immune Antibodies in one `< 25 ms` call.
2. **Teleport (`chimera_surgical_bundle` + `chimera_xray_batch`)**
   - For any symbol across C# `partial class` splits, Python, or JS/TS, call `chimera_surgical_bundle` (`repo`, `symbol`, `hops=2`, `max_bytes=8192`) to fetch the definition, 2-hop callgraph, related types, and matching tests before opening full files.
   - Batch remaining file outlines, regex searches, and small slices into a single `chimera_xray_batch` call.
3. **Edit Atomically (`chimera_atomic_patch`)**
   - Apply multi-file edits through `chimera_atomic_patch` so C#/Python/JSON/JS syntax gates run in RAM before touching disk, with automatic rollback on error.
4. **Verify Under Iron Cage (`chimera_commit_verify`)**
   - Run `chimera_commit_verify` with `repo` and `changed_files` to execute BLAKE2s-cached impacted `dotnet test`, `pytest`, or `node --test` without starving UI cores.
5. **Persist Knowledge (`chimera_hive_cortex`)**
   - Store compact verified symbol invariants (`action="put_capsule"`) so future sessions and peer Swarm workers skip re-reading unchanged files, or run `action="tournament_run"` to benchmark competing patches deterministically.

## Diagnostics

- Check live Omega-Spine health: `GET http://127.0.0.1:9780/v1/omega/status`
- Hook lifecycle events (`SessionStart`, `PreToolUse`, `PostToolUse`, `PreInvocation`, `Stop`) fail open automatically (`{}` or `{"decision":"allow"}`) if `:9780` is offline.
