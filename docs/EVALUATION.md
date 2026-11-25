# Evaluation — CHIMERA-HYPER v4.0.0 Live Cluster Results

All cross-host telemetry below was measured live across the two-node cluster (`Windows 11 i5-11400 Rust GFNI` ↔ `Ubuntu Linux i5-4300U C11 AVX2, Python 3.14.4`) running `CHIMERA-HYPER v4.0.0` 24/7 daemons over Tailscale.

## 1. Automated Verification Suites (Verified After Final Edits)

- **Windows (`python -m unittest discover -s tests -v`)**: **36 / 36 PASS in `57.919s`** (`0` failures, `0` skipped).
- **Linux (`python3 -m unittest discover -s tests -v`)**: **36 / 36 PASS in `27.749s`** (`0` failures, `0` skipped).

## 2. Zero-Weight Memory Footprint (Windows + Linux Daemons)

| Node / Process | Measured Idle `VmRSS` / Working Set | Budget (`80 MB`) | Services Hosted |
| :--- | :---: | :---: | :--- |
| **Windows Controller (`pythonw` `:9780` + `:9788`)** | **`10.74 MB`** idle (`27.91 MB` right after heavy eval) | PASS (`13.4%` used) | Cockpit, Beam, RPC, Query, Immortal, Warp, LocalEdgeProxy |
| **Linux Server Hub (`systemd` `:9780` / TS `:9781`)** | **`45.10 MB`** (`57.62 MB` peak during Sentinel scan) | PASS (`56.4%` used) | Cluster Hub, EdgeGateway, Sentinel, FTS5 Index (`1,943` files), Holo Store |

## 3. Verified Live `v4.0` HyperOS Results

### Breakthrough #1 — Birthday-Paradox NAT Buster
- Path tested: Windows (`SYMMETRIC` NAT, staggered STUN mappings across `stun.cloudflare.com:3478` vs `stun.l.google.com:19302`) ↔ Linux (`EASY` NAT).
- Execution: `192` UDP sockets opened, **`1` punch wave** (`1,148.86 ms` total coordination + probe).
- Result: **`DIRECT_P2P_PIERCED`** — direct UDP P2P RTT **`5.20 ms`** (samples `[4.79, 5.15, 5.20, 5.45, 5.21] ms`) vs **`222.76 ms`** baseline Tailscale HTTP control RTT (**`42.84x` faster**).

### Breakthrough #2 — Universal HTTP Warp-Edge Proxy (`127.0.0.1:9788`)
- Fetched 3 independent Linux services from Windows through `LocalEdgeProxy` -> `EdgeGateway`:
  - `radar`: `82,994 B` decoded (`TELEPATHY-TELEPATHIC_ZDICT`, `486.53 ms`)
  - `tqouta`: `615,640 B` decoded (`TELEPATHY-TELEPATHIC_FOLD_ZDICT`, `1,207.14 ms`)
  - `chimera`: `51,434 B` decoded (`TELEPATHY-TELEPATHIC_FOLD_ZDICT`, `439.80 ms`)
  - Immediate follow-up `GET /chimera/api/status`: **`21,691 B` served with `X-Chimera-Edge: PREFETCH-HIT-0RTT` in `19.08 ms`**.
- Aggregate wire efficiency: **`750,068 B -> 163,281 B`** (**`-78.23%` bandwidth saved**).

### Breakthrough #3 — CHIMERA-SENTINEL Watchdog
- Probed all `3` configured Linux apps (`chimera` `1.52 ms`, `radar` `1.45 ms`, `tqouta` `6.52 ms` — all `UP HTTP 200`).
- Checked host disk (`42.57 GB / 108.81 GB` = `39.1%` free) and scanned `12` recent `.log` files (`787.59 ms`), flagging a real `[55x] MAIL_FAIL_502` error burst in production email sync logs.

### Breakthrough #4 — 0-Download SQLite FTS5 + Merkle Search
- Indexed **all `20` workspace repositories (`1,943` files)** on Linux in a compact **`32,528 KB` (`31.77 MB`)** WAL database (`max_file_bytes=48 KiB`, `max_files_per_repo=250`).
- Incremental Merkle verification (`skipped_unchanged = 1,943`): **`384–386 ms`** with zero file reads.
- Cross-host search queries over Tailscale HTTPS:
  - `"HyperWireReceiver"`: `5` ranked hits (`chimera-tp/...`) in **`2.16 ms`**
  - `"V_Finance"`: `5` ranked hits (`auto-pull.log`, `HR/AGENTS.md`, `auto-pull.sh`) in **`4.37 ms`**
  - `"radar"`: `5` ranked hits (`radar_dashboard/...`) in **`5.30 ms`**

### Breakthrough #5 — Holographic GF(256) `(K=2, N=3)` Backup
- Packed live controller `config.json` (`1,402 B` raw -> `638 B` compressed -> `960 B` per shard) in `258.56 ms` (`peer_synced=true` shipping `shard_1.chshard` to Linux).
- Observed single-shard Shannon entropies: **`[7.6773, 7.6731, 7.6712]` bits/byte**.
- Simulated total loss of `shard_0.chshard`: fetched `shard_1` back from Linux and restored `(shard_1 + export_shard_2)` with **`sha256_match=true` in `3.40 ms`**.

### Foundation & HyperGrid Telemetry (`v4.0.0` Autopilot Cycle)
- Cluster health score: **`100 / 100`** | Simulated 5% WAN drop speedup: **`29.94x`** | 1 MiB DNA Beam: **`3.72x` (`-95.36%` wire)** | Fluid Log Query: **`7.04x` (`-99.15%` wire)** | Merkle 16-file Sync: **`-96.84%` wire** | Immortal IPv4 Cut: **`true`** | Tailscale HTTPS SSR HTML: **`14,487 B` gzipped in `442.93 ms`**.
