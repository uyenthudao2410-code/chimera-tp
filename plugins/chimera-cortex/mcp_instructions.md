# Chimera Omega-Spine + Mnemosyne MCP Cheatsheet (`http://127.0.0.1:9780/mcp`)

Always pass an explicit absolute `repo` path. Never rely on implicit CWD.

| Tool | Purpose | Key Args |
| :--- | :--- | :--- |
| `chimera_bootstrap` | 1-call repo orientation + Env Fingerprint + PDF/Doc catalog + Top-K `AKASHIC-RAW` + Hive leases + Swarm Bulletin | `repo` |
| `chimera_xray_batch` | Zero-spawn batched `outline`, `list_files`, `regex_search`, `file_slice`, `git_status`, `surgical_bundle`, **`file_hash`**, **`win_probe`**, **`watch_until`**, **`remote_xray`** (`8ms` `svhome`), **`raw_recall`** (`CAUSAL-RAW-RAG`), **`doc_page`** (lossless PDF/DOCX) | `repo`, `ops` |
| `chimera_surgical_bundle` | C#/Py/JS 2-hop symbol definition + callers/callees + related types + tests (`<= 8 KB`) | `repo`, `symbol`, `hops=2`, `max_bytes=8192` |
| `chimera_atomic_patch` | Transactional multi-file edit with in-RAM syntax gate + auto-rollback | `repo`, `edits` |
| `chimera_commit_verify` | BLAKE2s-cached impacted `dotnet test` / `pytest` / `node --test` inside Iron Cage | `repo`, `changed_files`, `cmd?` |
| `chimera_hive_cortex` | Hive leases, capsules, antibodies, Shadow Tournament, Iron Cage, **`raw_recall`**, **`raw_ingest`**, **`raw_slice`**, **`warm_repl`**, **`entropy_audit`**, **`raw_arena`**, **`swarm_watchdog`**, **`shell_guard_status`** | `action`, `repo?`, ... |

## Quick Rules (Zero-Loss Raw Bus · Zero-Shell)
- **Never** run serial `Get-ChildItem`, `Get-Content`, `Get-FileHash`, `--version`, or `ssh svhome` loops — use `chimera_xray_batch` (`file_hash`, `win_probe`, `remote_xray`, `watch_until`, `doc_page`) or `chimera_hive_cortex(action="warm_repl", code=...)`.
- **Recall verbatim history before guessing:** call `raw_recall` (`CAUSAL-RAW-RAG` + `Live Reality Stamp`) across Codex + Antigravity + T3 raw logs.
- **Duplicate read-only shells** are automatically short-circuited in `PreToolUse`; large `>4 KB` outputs are stored 100% verbatim in `AKASHIC-RAW` with a `raw_ref_id`.
