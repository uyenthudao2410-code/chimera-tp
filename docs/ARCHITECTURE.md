# Architecture — CHIMERA-HYPER v4.0.0 Zero-Weight HyperOS

```
+----------------------------------------------------------------------------------+
|                CHIMERA-HYPER v4.0 Control & Zero-Weight HyperOS Plane            |
|   HTTP/1.1 Keep-Alive Cockpit (:9780) | Tailscale HTTPS Hub (:9781)              |
|   Zero-Weight Guard (~11 MB Win RAM)  | Contextual 24h Link-Weather UCB1 Bandit  |
+----+-------------------+-------------------+-------------------+-----------------+
     |                   |                   |                   |
     v                   v                   v                   v
+-----------+    +---------------+   +--------------+   +--------------------+
| NAT Buster|    | Edge Proxy    |   |  Sentinel &  |   | Holographic (2,3)  |
| STUN + BP |    | :9788 <->     |   | FTS5 Search  |   | GF(256) Backup     |
| P2P Hole  |    | EdgeGateway   |   |  on Linux    |   | CSPRNG + CHHB1     |
+-----+-----+    +-------+-------+   +------+-------+   +---------+----------+
      |                  |                  |                     |
      +------------------+------------------+---------------------+
                         |
                         v  (v3.0 HyperGrid: Merkle CHMRK1, Fluid AQ02, CHTC1, Immortal IPv4+IPv6)
+----------------------------------------------------------------------------------+
|                        Cross-Platform Silicon Core (Bit-Identical)               |
|   Windows: Rust cdylib (VGF2P8AFFINEQB GFNI / AVX2 + Win32 Shared Memory Ring)   |
|   Linux:   C11 .so    (AVX2 VPSHUFB Split-Nibble GF256 + POSIX /dev/shm Ring)    |
+----------------------------------------------------------------------------------+
```

## 1. Birthday-Paradox STUN NAT Buster (`chimera_tp/nat_buster.py`)
- **Zero-Idle Discovery**: `discover_nat_profile()` opens temporary UDP sockets only during probing to classify `EASY` vs `SYMMETRIC` NAT across `DEFAULT_STUN_SERVERS` and measure sequential port deltas.
- **Coordinated Punching**: `NatPunchResponder` binds an ephemeral anchor socket on the peer, coordinates `(pub_ip, pub_port)` via `POST /api/nat/punch-offer`, and sprays signed `CHNP1` probes over delta predictions + random birthday slots while the initiator opens up to 192 non-blocking sockets (`select.select` chunked in `<= 250` FDs).
- **Safe Fallback**: Once a handshake completes (`CHNP1`/`CHNP2`), direct RTT is probed (`CHNP3`/`CHNP4`) and all transient sockets close cleanly. If carriers drop external UDP, callers remain on Tailscale seamlessly.

## 2. Universal HTTP Warp-Edge Proxy (`chimera_tp/edge_proxy.py`)
- **`EdgeGateway` (Linux Hub)**: Enforces loopback-only upstream URLs (`127.0.0.1`/`localhost`) to accelerate arbitrary local dashboards over `POST /api/edge/fetch`. Automatically trains and attaches missing 16 KiB `DomainDictionary` weights (`CHTC1`/`CHLF1`).
- **Speculative 0-RTT Prefetching**: On `200 OK` HTML responses, pre-fetches configured or safe `/api/*` endpoints locally on `127.0.0.1` and bundles compressed responses inside the same payload.
- **`LocalEdgeProxy` (Windows `127.0.0.1:9788`)**: Serves decoded HTML directly and caches prefetched API responses in a bounded 32-entry, 10s-TTL RAM cache (`X-Chimera-Edge: PREFETCH-HIT-0RTT`), routing JS `/api/*` sub-requests cleanly by path prefix or `Referer`.

## 3. CHIMERA-SENTINEL Autonomous Watchdog (`chimera_tp/sentinel.py`)
- Persists baseline log error template counts in `sentinel.db` (isolated from `telemetry.db` to avoid lock contention).
- Probes configured loopback service URLs, checks disk/RAM/load metrics, and tail-scans the newest `*.log` files using `log_analytics`, raising alerts on downed services, resource pressure, or sudden error template spikes alongside safe diagnostic advice and optional webhook POSTs.

## 4. Zero-Download SQLite FTS5 + Merkle Search (`chimera_tp/code_search.py`)
- Maintains `code_index.db` (`WAL` mode, `unicode61` tokenizer, `bm25()` + `snippet()`) purely on the storage hub.
- Avoids index bloat via `SEARCH_IGNORE_DIRS`, minified suffix exclusions, `48 KiB` file cap, per-repo quota (`250` files/repo so every repository stays represented), Merkle `(size, mtime_ns)` change detection, and automatic `VACUUM` + WAL checkpoint when `>= 100` stale entries are pruned.
- Windows clients query `POST /api/search` without copying source trees or indexing locally.

## 5. Holographic GF(256) `(K=2, N=3)` Micro-Backup (`chimera_tp/holo_backup.py`)
- Packs target files into `CHHB1` with per-file SHA-256, applies self-contained `TelepathicCodec` compression, and mixes secret bytes with a CSPRNG one-time mask via `gf256_encode_block` using fixed Vandermonde pairs `SHARD_COEFFS = ((1,1), (1,2), (1,3))`.
- Stores `shard_0.chshard` + `export_shard_2.chshard` locally while shipping `shard_1.chshard` to peer `POST /api/backup/store-shard`. Any 2 shards invert the `2x2` GF(256) system natively via `gf256_decode_matrix` and verify both per-shard and archive-wide SHA-256 digests.
