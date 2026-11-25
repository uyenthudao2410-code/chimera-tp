# Architecture — CHIMERA-HYPER v5.0.0 PHANTOM-5MS

```
+----------------------------------------------------------------------------------+
|                CHIMERA-HYPER v5.0 PHANTOM-5MS Control & Workbench Plane          |
|   Windows (:9780 Cockpit | :9788 Edge + /dav/ WebDAV | :2222 SSH | :9789 HTTP)   |
|   Zero-Weight Guard (~21-32 MB Win RAM) | Transparent Role-Aware Peer Proxy      |
+----+-------------------+-------------------+-------------------+-----------------+
     |                   |                   |                   |
     v                   v                   v                   v
+-----------+    +---------------+   +--------------+   +--------------------+
|PHANTOM-5MS|    | Ghost-PTY &   |   | CHIMERA-MEDIC|   | Drop-Portal &      |
|PH5E AEAD  |    | Ghost-FS /DAV |   | Forensics +  |   | AI Context Bus     |
|5ms P2P UDP|    | 256KiB + ETag |   | Holo Pre-Heal|   | CHdrop + FTS5 Pack |
+-----+-----+    +-------+-------+   +------+-------+   +---------+----------+
      |                  |                  |                     |
      +------------------+------------------+---------------------+
                         |
                         v  (v4.0 HyperOS + v3.0 HyperGrid: NAT Buster, Sentinel, FTS5, Holo, AQ02, CHTC1, Immortal)
+----------------------------------------------------------------------------------+
|                        Cross-Platform Silicon Core (Bit-Identical)               |
|   Windows: Rust cdylib (VGF2P8AFFINEQB GFNI / AVX2 + Win32 Shared Memory Ring)   |
|   Linux:   C11 .so    (AVX2 VPSHUFB Split-Nibble GF256 + POSIX /dev/shm Ring)    |
+----------------------------------------------------------------------------------+
```

## 1. PHANTOM-5MS Encrypted P2P Tunnel (`chimera_tp/phantom_tunnel.py`)
- **Persistent NAT-Punched Carrier**: `PhantomTunnelController` runs an automated `nat_buster` STUN/birthday punch loop on Windows startup to establish `PHANTOM_5MS_DIRECT` (~`5 ms` direct UDP socket) with automatic Tailscale UDP `:9710` fallback (`PhantomTunnelServer`).
- **PH5E Authenticated Multiplexing**: Each datagram carries a `PH5E` header (`channel_id`, `seq`, `flags`, `nonce`) sealed with a `BLAKE2b` keystream and verified by a `BLAKE2s-128` MAC. Idle loops wait on `select.select(..., 0.25)` so background CPU stays near `0%`.
- **Multi-Port Loopback Listeners**: Maps local controller TCP ports (`127.0.0.1:2222 -> 127.0.0.1:22` SSH, `127.0.0.1:9789 -> 127.0.0.1:9780` HTTP) restricted on the hub to `phantom_allowed_ports`. `LocalEdgeProxy` queries `peer_http_resolver()` on each miss to dynamically route Edge HTTP and WebDAV requests over `:9789` when direct P2P is healthy.

## 2. Ghost-PTY Persistent Detachable Shell (`chimera_tp/ghost_pty.py`)
- **`GhostPtyManager`**: Allocates POSIX PTYs (`pty.openpty()` + `TIOCSWINSZ` resize, pipe fallback on Windows) with background reader threads feeding per-session `256 KiB` ring buffers protected by `threading.Condition`.
- **Cursor-Indexed Long Poll**: Clients call `/api/pty/read?session_id=...&cursor=N&wait_ms=...`, enabling instant reattachment across browser reloads or momentary network drops without spawning heavy multiplexers.

## 3. Ghost-FS & RFC 4918 WebDAV Bridge (`chimera_tp/ghost_fs.py`, `chimera_tp/edge_proxy.py`)
- **`GhostFsEngine`**: Provides contained workspace browsing, UTF-8/binary reads, safe `git status`/`git log -n 5` inspection, and writes (`expected_etag` compare-and-swap via weak SHA-256 prefix ETags, blocking `.git` writes and `..` traversal outside `allowed_query_roots`).
- **Local WebDAV Mount (`/dav/`)**: `LocalEdgeProxy` translates HTTP `OPTIONS`, `PROPFIND` (`207 Multi-Status` XML via `build_propfind_xml`), `GET`, `HEAD`, and `PUT` directly to `active_peer_base` `/api/fs/*`, allowing native OS browsing and editing with zero local repo mirroring.

## 4. CHIMERA-MEDIC Forensics & Playbook Healer (`chimera_tp/medic.py`)
- **Dossier Triage (`investigate`)**: Tail-scans bounded log bytes (`<= 2 MiB`), extracts `±1` line context snippets for recurring anomalies, and suggests safe remediation playbooks.
- **Allowlisted Playbooks (`run_playbook`)**: Rejects arbitrary shell strings and runs only curated handlers (`verify_email_log_tail`, `probe_services`, `prune_git_remote`, `holo_snapshot_configs`, `rotate_large_log`, `reindex_fts5`). File rotation triggers mandatory pre-heal GF(256) `(K=2, N=3)` snapshots first.

## 5. Drop-Portal & AI Context Bus (`chimera_tp/drop_portal.py`)
- **`DropPortalStore`**: Compresses temporary clipboard notes or files with `TelepathicCodec` into `.chdrop` containers with lazy TTL pruning (default `600 s`) and role-transparent controller -> hub routing.
- **AI Context Teleporter (`pack_ai_context`)**: Combines server-side SQLite `FTS5` `BM25` search hits (`CodeSearchIndex`), bounded `±5/+8` disk file excerpts, matching `Sentinel` alert summaries, and recent git commits into a `< 8 KB` Markdown prompt packet.

---

## Inherited Foundations (`v4.0` HyperOS & `v3.0` HyperGrid)
- **NAT Buster (`nat_buster.py`)**: RFC 5389 STUN classifier (`EASY`/`SYMMETRIC`) & birthday-paradox puncher.
- **Warp-Edge Proxy (`edge_proxy.py`)**: Loopback `EdgeGateway` compression (`CHTC1`/`CHLF1`) + speculative 10s-TTL RAM prefetch cache.
- **Sentinel (`sentinel.py`)**, **FTS5 Code Search (`code_search.py`)**, **Holo GF(256) `(2,3)` Backup (`holo_backup.py`)**, **Merkle Sync (`merkle_sync.py`)**, **Fluid `AQ02` (`active_pipe.py`)**, and **Immortal IPv4+IPv6 RLNC (`hyper_wire.py`)**.
