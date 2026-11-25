# Roadmap — CHIMERA-HYPER

## Completed — `v1.0.0` (Hyper Foundation)
- Rust GFNI / AVX2 / AVX-512F GF(256) matrix engine + Win32 Named Shared Memory ring
- HyperWire sliding-window RLNC + XOR obfuscation
- FastCDC + Odess SuperFeature delta engine (DNA Beam)
- Active Pipe compute-in-flight filter with P0 preview streaming

## Completed — `v2.0.0 AUTOPILOT`
- Linux C11 AVX2 `VPSHUFB` core + POSIX `/dev/shm` lock-free ring (bit-identical with Windows Rust core)
- Cross-host Tailscale IPv4+IPv6 dual-stack transport & single-port UDP firewall/NAT feedback routing
- Darwinian UCB1 Bandit + SQLite persistent telemetry + 24/7 Mission-Control Cockpit & Daily Schedulers

## Completed — `v3.0.0 ZERO-WEIGHT HYPERGRID`
- Merkle Directory DNA Sync + Shadow Stat Index (`merkle_sync.py`)
- Fluid Pushdown Compute `AQ02` (`active_pipe.py`)
- Telepathic Domain Dictionary + Lossless Line Folding (`telepathy.py`)
- Immortal Stateless Multi-Path RLNC (`hyper_wire.py`)
- Contextual 24h Link-Weather & Zero-Weight Guard (`autopilot.py`, `dashboard.py`)

## Completed — `v4.0.0 ZERO-WEIGHT HYPEROS`
- Birthday-Paradox STUN NAT Buster (`nat_buster.py`) achieving `5.20 ms` direct P2P UDP RTT
- Universal HTTP Warp-Edge Proxy + Speculative Prefetch (`edge_proxy.py`: `-78.23%` wire, 0-RTT hits)
- CHIMERA-SENTINEL Watchdog (`sentinel.py`)
- 0-Download SQLite FTS5 + Merkle Search (`code_search.py`)
- Holographic GF(256) `(K=2, N=3)` Secret-Shared Micro-Backup (`holo_backup.py`)

## Completed — `v5.0.0 PHANTOM-5MS`
- **PHANTOM-5MS Persistent Encrypted P2P Tunnel (`phantom_tunnel.py`)**: Persistent `PH5E` (`BLAKE2b` + `BLAKE2s-128`) NAT-punched carrier forwarding local `:2222` SSH (`5.55x` faster) and `:9789` HTTP (`19.26x` lower p50), automatically powering `LocalEdgeProxy` (`3.04x–5.60x` faster UI loads) with clean Tailscale UDP `:9710` fallback.
- **Ghost-PTY (`ghost_pty.py`)**: Cursor-indexed persistent `256 KiB` shell sessions survive reconnects (`19.6 ms` spawn, `28.68 ms` `cursor=0` reattach).
- **Ghost-FS & WebDAV Bridge (`ghost_fs.py`, `edge_proxy.py`)**: Path-contained `/api/fs/*` + `:9788/dav/` (`PROPFIND 207` `33.24 ms`, `GET` ETag `12.06 ms`, `.git` write guard).
- **CHIMERA-MEDIC (`medic.py`)**: Forensic dossier triage (`4.24 ms`) + strict allowlisted playbooks with mandatory pre-heal GF(256) snapshots.
- **Drop-Portal & AI Context Bus (`drop_portal.py`)**: Compressed TTL `.chdrop` cross-host clipboard/files + `< 8 KB` FTS5/Sentinel/Git AI Context Packets (`1.67–2.72 ms`).

## Next Horizons — `v5.1+`
1. **Ed25519 Signed Capability Tokens & Key Rotation**: Rotate `PH5E` session keys periodically and bind per-operator Ed25519 capability signatures onto `medic`, `fs`, and `holo_backup` RPCs.
2. **ARM64 NEON (`PMULL` / `VTBL`) Native Core**: Extend bit-identical GF(256) acceleration to ARM64 servers and Apple Silicon workstations.
3. **Zero-Copy Streaming File Put for Multi-GB WebDAV Uploads**: Chunked FastCDC + HyperWire streaming mode for `/dav/` uploads larger than RAM cache thresholds.
