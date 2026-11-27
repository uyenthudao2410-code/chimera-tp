# CHIMERA Omega-Spine Routing Rule (Streamable HTTP MCP + Hooks)

When MCP server `chimera` (`http://127.0.0.1:9780/mcp`) is available, route through its 6 Eager Super-Tools instead of serial shell loops:

1. **Always pass explicit `repo` path:** Supply the absolute workspace root in `repo` on every tool call so paths never drift to Chimera's runtime install dir.
2. **Cold-start orientation (`1` call):** Call `chimera_bootstrap(repo=...)` first for repo tree, git status, active Hive leases, Akashic capsules, and Immune Antibodies.
3. **C# / Python / JS Surgical Teleport BEFORE slicing large files:** Call `chimera_surgical_bundle(repo=..., symbol=...)` to pull definition + 2-hop callers/callees + related types + matching tests in `<= 8 KB` before reading multi-hundred-line files.
4. **Zero-spawn batch inspection:** Batch `outline`, `list_files`, `regex_search`, `file_slice`, `git_status`, and `surgical_bundle` ops into one `chimera_xray_batch(repo=..., ops=[...])` call (singleflight-coalesced, `0` shell spawns). Use native `read_file` with `StartLine`/`EndLine` for large known ranges.
5. **Atomic edits & Iron-Cage verification:** Use `chimera_atomic_patch` for multi-file edits (in-RAM C#/Python/JSON/JS syntax gate + auto-rollback) and `chimera_commit_verify` for BLAKE2s-cached impacted `dotnet test` / `pytest` / `node --test` inside the Kernel Iron Cage.
6. **Swarm memory & coordination:** Use `chimera_hive_cortex` (`lease`, `release`, `put_capsule`, `recall_capsules`, `antibodies`, `tournament_run`, `cage_status`) to share verified symbol capsules across Swarm workers and avoid conflicting edits.
