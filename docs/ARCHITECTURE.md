# Architecture — CHIMERA-HYPER v6.0.0 APEX-SYNERGY

```
+------------------------------------------------------------------------------------+
|               CHIMERA-HYPER v6.0 APEX-SYNERGY Control & Fusion Plane               |
|  Win (:9780 Cockpit | :9788 Edge + /dav/ HTML/DAV | :2222 SSH | :9789 | :12550 v1) |
|  Zero-Weight Guard (~14.5-33 MB Win / ~46 MB Linux) | Transparent Peer Routing     |
+----+--------------------+--------------------+--------------------+----------------+
     |                    |                    |                    |
     v                    v                    v                    v
+-------------+    +---------------+    +--------------+    +------------------------+
| PHANTOM-5MS |    | APEX-SYNERGY  |    | Ghost-PTY &  |    | Drop-Portal, Medic &   |
| PH5E AEAD   |    | 0-Tok Brief,  |    | Ghost-FS DAV |    | GF(256) Subprocess     |
| :12550/v1   |    | Arbiter &Burn |    | 207+HTML Idx |    | Apex Vault (K=2,N=3)   |
+------+------+    +-------+-------+    +------+-------+    +-----------+------------+
       |                   |                   |                        |
       +-------------------+-------------------+------------------------+
                           |
                           v  (v5.0 + v4.0 + v3.0: FTS5, Sentinel, NAT Buster, Merkle, AQ02, CHTC1, Immortal)
+------------------------------------------------------------------------------------+
|                        Cross-Platform Silicon Core (Bit-Identical)                 |
|   Windows: Rust cdylib (VGF2P8AFFINEQB GFNI / AVX2 + Win32 Shared Memory Ring)     |
|   Linux:   C11 .so    (AVX2 VPSHUFB Split-Nibble GF256 + POSIX /dev/shm Ring)      |
+------------------------------------------------------------------------------------+
```

## 1. Unified Fusion Engine (`chimera_tp/apex_synergy.py`)
- **`PHANTOM-12550` Relay Tunnel**: Extends `PhantomTunnelClient` forwards on the Windows controller with `{phantom_tquota_port: 12500}` (`127.0.0.1:12550 -> 127.0.0.1:12500` on the hub, authorized in `phantom_allowed_ports`), avoiding local Windows port collisions while sharing the hub's warm `Prompt Cache` and account `Pool`.
- **0-Token Pre-Surgical Brief (`build_surgical_brief`)**: Contained within `allowed_query_roots`, ignores build/compiled artifact dirs (`artifacts`, `cache`, `out`, `typechain-types`, `node_modules`, `.git`), ranks source files using identifier/backtick weighted scoring, extracts `±6` line context excerpts + symbol declarations + test files + `git log -n 5`, caps output `< 7.2 KB` in `CHIMERA_SURGERY_PACK.md`, and idempotently injects into `AGENT_SOLVER_BRIEF.md`.
- **Redacted Quota Arbiter (`evaluate_quota_arbiter`)**: Aggregates Tqouta `/api/dashboard` fleet health (`accounts_ok`, `needs_reauth`, `unknown_pool_count`, `cache_hit_pct`, `dualLayerSlo`) with zero email/label disclosure, cross-checking Radar `/api/overview` to emit dynamic solver throttling regimes (`TURBO`, `BALANCED`, `ECO_SURVIVAL`).
- **Burn-Loop Detector & Circuit Breaker (`scan_solver_burn_loops`, `trip_circuit_breaker`)**: Normalizes stderr/log failure signatures (stripping timestamps, line numbers, and hex addresses) across solver workspaces; flags loops when repeated errors exceed threshold or logs bloat without a diff, writing `CHIMERA_CIRCUIT_BREAK.json` and alerting `Drop-Portal`.
- **5-Second Ready-Bounty Review & GF(256) Subprocess Vault**: Parses diff stats across workspaces holding `solution.patch` for instant `/dav/.../solution.patch` review + Drop publishing, and executes >2 MiB GF(256) `(K=2, N=3)` vaults (including read-only SQLite `.backup()` of `radar.db`) inside an isolated short-lived worker subprocess so daemon RSS remains unaffected.

## 2. Interactive Browser & RFC 4918 WebDAV (`chimera_tp/edge_proxy.py`, `chimera_tp/ghost_fs.py`)
- `LocalEdgeProxy` (`/dav/...`) handles browser `GET`/`HEAD` directory browsing (`200 text/html` index + `302` trailing-slash normalization) alongside machine RFC 4918 `OPTIONS`, `PROPFIND` (`207 Multi-Status` XML), `GET`, `HEAD`, and `PUT` (`If-Match` ETag compare-and-swap, `.git` write denial) transparently over `active_edge_peer_base()`.

## 3. Control-Plane Endpoints (`chimera_tp/dashboard.py`, `chimera_tp/cli.py`, `chimera_tp/medic.py`)
- Exposes `/api/synergy/status`, `/api/synergy/bounties`, `/api/synergy/burn-scan`, `/api/synergy/surgical-brief`, `/api/synergy/circuit-break`, `/api/synergy/bounty-drop`, `/api/synergy/vault-backup`, `/api/synergy/arbiter`, the `Radar + Tqouta Synergy` Workbench tab, CLI `chimera-tp synergy ...`, and `MedicEngine` playbook `holo_snapshot_apex`.
- Controller daemons transparently proxy `/api/synergy/*`, `/api/pty/*`, `/api/fs/*`, `/api/medic/*`, and `/api/portal/*` across the active P2P tunnel (falling back safely to overlay HTTP if unpunched).

---

## Inherited Foundations (`v5.0` PHANTOM-5MS, `v4.0` HyperOS & `v3.0` HyperGrid)
- **Ghost-PTY (`ghost_pty.py`)**: `256 KiB` cursor-indexed POSIX PTY sessions (`19.6 ms` spawn, `28.68 ms` reattach).
- **NAT Buster (`nat_buster.py`)**, **Sentinel (`sentinel.py`)**, **FTS5 Code Search (`code_search.py`)**, **Holo GF(256) Backup (`holo_backup.py`)**, **Drop-Portal & Context Pack (`drop_portal.py`)**, **Merkle Sync (`merkle_sync.py`)**, **Fluid `AQ02` (`active_pipe.py`)**, and **Immortal IPv4+IPv6 RLNC (`hyper_wire.py`)**.
