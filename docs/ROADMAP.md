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
- **Birthday-Paradox STUN NAT Buster (`nat_buster.py`)**: RFC 5389 NAT classifier + coordinated multi-socket UDP hole-punching achieving **`5.20 ms` direct P2P RTT (`42.84x` faster)** across `SYMMETRIC -> EASY` NATs with clean Tailscale fallback.
- **Universal HTTP Warp-Edge Proxy + Speculative Prefetch (`edge_proxy.py`)**: Loopback-guarded server gateway + Windows `:9788` local proxy delivering **`-78.23%` wire** and **`19.08 ms` 0-RTT prefetched API hits**.
- **CHIMERA-SENTINEL Watchdog (`sentinel.py`)**: Autonomous service probes, disk/RAM health, and baseline-tracked log error spike detection with diagnostic hints & webhooks.
- **0-Download SQLite FTS5 + Merkle Search (`code_search.py`)**: Fair 20-repo (`1,943` files, `31.8 MB` DB) server-side BM25 search returning hits in **`2.16–5.30 ms`** with `0 MB` Windows RAM.
- **Holographic GF(256) `(K=2, N=3)` Backup (`holo_backup.py`)**: CSPRNG-masked native GF(256) shard splitting (`~7.67 bits/B` single-shard entropy), automatic peer shard replication, and bit-exact `3.40 ms` 2-of-3 recovery.

## Next Horizons — `v4.1+`
1. **HyperWire UDP Carrier for `EdgeGateway`**: Pipe `/api/edge/fetch` frames directly over punched `5 ms` Direct P2P UDP sockets instead of Tailscale TCP HTTP.
2. **Ed25519 Signed Capability Tokens**: Bind per-operator cryptographic signatures onto `AQ02`, `EdgeGateway`, and `CHSH1` peer shard requests for multi-peer team topologies.
3. **ARM64 NEON (`PMULL` / `VTBL`) Core**: Native shared library build target for ARM64 single-board servers and Apple Silicon machines.
