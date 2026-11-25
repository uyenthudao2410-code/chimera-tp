# CHIMERA-HYPER v4.0.0 — Zero-Weight HyperOS

CHIMERA-HYPER (`chimera-tp`) is an autonomous, ultra-lightweight cross-platform transport, edge-acceleration, search, monitoring, and erasure-coded backup fabric connecting Windows (`Rust GFNI/AVX2`) and Linux (`C11 AVX2`) nodes over overlay WANs (Tailscale/WireGuard) with zero desktop bloat.

Built on the strict **Zero-Weight Controller** invariant (the Windows 24/7 daemon + local Edge Proxy consumes only **~11–32 MB RAM** and ~0% idle CPU), `v4.0` offloads heavy indexing, anomaly monitoring, compression, and storage onto the Linux hub while adding direct STUN UDP hole-punching, an HTTP Warp-Edge proxy, and GF(256) secret-shared backups.

---

## What's New in `v4.0.0` (5 Zero-Weight HyperOS Engines)

1. **Birthday-Paradox STUN NAT Buster (`chimera_tp/nat_buster.py`)**
   - Pure-stdlib RFC 5389 STUN profiling (`EASY` vs `SYMMETRIC` + sequential port delta) and coordinated multi-socket UDP hole-punching across Tailscale's control plane.
   - Live cross-ISP punch (`SYMMETRIC -> EASY`) pierced in 1 wave (`1.15 s`) delivering **`5.20 ms` direct P2P RTT** vs **`222.76 ms`** overlay baseline (**`42.84x` faster**), with automatic safe fallback if a carrier blocks UDP.

2. **Universal HTTP Warp-Edge Proxy + Speculative 0-RTT Prefetch (`chimera_tp/edge_proxy.py`)**
   - Loopback-locked `EdgeGateway` on the Linux hub accelerates ANY local web UI (`chimera`, `radar`, `tqouta`, etc.) via `TelepathicCodec` (`CHTC1`/`CHLF1`), slashing **`750 KB -> 163 KB` (`-78.23%` wire)**.
   - Transparent Windows `LocalEdgeProxy` (`127.0.0.1:9788`) speculatively caches hot `/api/*` endpoints bundled alongside `/` HTML, resolving follow-up API requests from local RAM with **`PREFETCH-HIT-0RTT` (`19.08 ms`)**.

3. **CHIMERA-SENTINEL Watchdog (`chimera_tp/sentinel.py`)**
   - Server-side autonomous immune system scanning configured local services, disk/RAM headroom, and tail logs via `log_analytics`, flagging recurring error template spikes with safe remediation hints and optional webhook alerts.

4. **0-Download SQLite FTS5 + Merkle Instant Search (`chimera_tp/code_search.py`)**
   - Pure-stdlib SQLite `FTS5` (`unicode61`) + `BM25` search engine hosted exclusively on the Linux hub (`0 MB` Windows RAM).
   - Incremental `(size, mtime_ns)` updates with noisy-dir filtering and per-repo fairness indexed **all 20 repositories (`1,943` files)** in a **`31.8 MB`** WAL DB, re-verifying in **`386 ms`** and answering cross-repo queries in **`2.16–5.30 ms`**.

5. **Holographic GF(256) `(K=2, N=3)` Secret-Shared Micro-Backup (`chimera_tp/holo_backup.py`)**
   - Uses native GFNI/AVX2 `gf256_encode_block` / `gf256_decode_matrix` + CSPRNG masking over `TelepathicCodec` to split critical configs into 3 shards (`Shard 0` local, `Shard 1` auto-synced to peer, `Shard 2` offline export).
   - Any single shard looks like random noise (`~7.67+ bits/byte` entropy, zero plaintext leak); any 2 of 3 shards reconstruct bit-exact SHA-256 files in **`3.40 ms`**.

*(All `v3.0` HyperGrid engines remain active: Merkle 0-RTT Sync, Fluid Pushdown `AQ02`, Telepathic Dictionaries, Immortal IPv4+IPv6 Multi-Path RLNC, and Contextual 24h Link-Weather UCB1.)*

---

## Verified Live Cross-Host Telemetry (Windows ↔ Linux Over Tailscale)

Measured live between a Windows 11 Controller (`Intel Core i5-11400`, Rust GFNI) and an Ubuntu Linux Hub (`Intel Core i5-4300U`, C11 AVX2 `VPSHUFB`, Python 3.14.4):

| Capability | Baseline / Previous | CHIMERA-HYPER v4.0 Live | Gain |
| :--- | :--- | :--- | :--- |
| **Idle Daemon RAM** | — | **`10.74 MB`** Win (`:9780`+`:9788`) / **`45.10 MB`** Linux | `< 80 MB` Zero-Weight budget |
| **NAT Buster P2P RTT** | `222.76 ms` Tailscale baseline | **`5.20 ms`** direct UDP P2P (`SYMMETRIC -> EASY`) | **`42.84x` lower RTT** |
| **Universal Edge Proxy** | Uncompressed proxied HTTP | **`163 KB` / `750 KB` (`-78.23%`)**, **`19.08 ms`** prefetch hit | **Instant 0-RTT API hits** |
| **FTS5 20-Repo Search** | Full repo pull / slow grep | **`2.16–5.30 ms`** BM25 (`1,943` files, `31.8 MB` DB) | **`386 ms` incremental reindex** |
| **Sentinel Watchdog** | Manual SSH log tailing | `3/3` apps UP, `12` logs (`787 ms`), caught `[55x]` email err | Zero Windows overhead |
| **Holo GF(256) (2/3) Backup** | Plain single-copy backup | Entropy `7.67 bits/B`, peer synced, **`3.40 ms`** restore `(1+2)` | Information-theoretic safety |
| **Fluid Log Filter + Beam** | `1.70 MB` raw over TCP | **`-99.15%`** query (`7.04x`) • **`-95.36%`** Beam (`3.72x`) | `100/100` cluster health |

See [docs/EVALUATION.md](docs/EVALUATION.md) and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for full details.

---

## Quick Start & CLI Tools

### 1. Build Native Silicon Core & Init Runtime Config
```bash
python scripts/build_native.py

# Linux Hub Server
chimera-tp ops-init --node-name peer-linux --role server --bind 0.0.0.0:9780 --watched-file /path/to/app.log --allow-root /path/to/dev

# Windows Controller
chimera-tp ops-init --node-name win-desktop --role controller --peer-name peer-linux --peer-ipv4 <PEER_TAILSCALE_IPV4> --peer-ipv6 <PEER_TAILSCALE_IPV6> --bind 127.0.0.1:9780
```
Runtime config lives strictly under `~/.chimera_ops/` (see [docs/ops_config.example.json](docs/ops_config.example.json)).

### 2. Run 24/7 HyperOS Daemons & v4.0 Subcommands
```bash
# Start 24/7 Mission-Control Cockpit + Warp + ActiveQuery + Immortal + LocalEdgeProxy
chimera-tp daemon

# Attempt Birthday-Paradox STUN direct P2P UDP punch
chimera-tp nat-bust --peer-http http://<PEER_IP>:9780

# Stand-alone Windows Local Edge Proxy accelerating remote localhost web apps
chimera-tp edge-proxy --listen 127.0.0.1:9788 --peer-http http://<PEER_IP>:9780

# Remote 0-download BM25 search across hub repositories
chimera-tp search "HyperWireReceiver" --peer-http https://<HUB_HOST>:9781

# Run CHIMERA-SENTINEL watchdog scan locally or inspect latest alerts
chimera-tp sentinel --scan

# Create & restore GF(256) (K=2, N=3) Holographic Micro-Backups
chimera-tp holo-backup create --path ~/.chimera_ops/config.json --peer-http http://<PEER_IP>:9780
chimera-tp holo-backup restore --shard shard_1.chshard --shard export_shard_2.chshard --out-dir ./restored
```

---

## Automated Tests

```bash
python -m unittest discover -s tests -v
```

- **Windows (`Rust GFNI` + Python 3.11):** **36 / 36 PASS** (`test_chimera`, `test_hyper`, `test_v2_autopilot`, `test_v3_hypergrid`, `test_v4_hyperos`).
- **Linux (`C11 AVX2` + Python 3.14):** **36 / 36 PASS** (`test_chimera`, `test_hyper`, `test_v2_autopilot`, `test_v3_hypergrid`, `test_v4_hyperos`).

---

## Security & Scope Disclaimer

`chimera-tp` enforces strict loopback SSRF allowlisting on `EdgeGateway` (`127.0.0.1`/`localhost` targets only), directory-root containment (`allowed_roots`) on all `AQ02` pushdown queries, Merkle patches, backup targets, and FTS5 reindexing, read-only URI SQLite queries (`?mode=ro`), and per-shard SHA-256 + archive SHA-256 verification on holographic restores. Always expose inter-node HTTP traffic only inside authenticated Tailscale or WireGuard overlays (`tailscale serve` HTTPS for remote cockpit access).
