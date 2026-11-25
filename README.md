# CHIMERA-HYPER v3.0.0 — Zero-Weight HyperGrid

CHIMERA-HYPER (`chimera-tp`) is an autonomous, ultra-lightweight cross-platform transport, synchronization, and pushdown-compute fabric connecting Windows (`Rust GFNI/AVX2`) and Linux (`C11 AVX2`) nodes across high-RTT, lossy overlay WANs (Tailscale/WireGuard) without straining desktop RAM or CPU.

Designed around a strict **Zero-Weight Controller** invariant (the Windows 24/7 daemon consumes **~18–31 MB RAM** and ~0% idle CPU), `v3.0` pushes heavy directory indexing, analytics, regex scans, and read-only SQLite queries onto the remote storage host while slashing WAN traffic up to **99.93%** and surviving mid-stream IP path loss with **0 reconnects**.

---

## Core Architecture (5 v3.0 Pillars + v2.0 Silicon Foundation)

1. **Zero-Weight Merkle Directory DNA Sync (`chimera_tp/merkle_sync.py`, `fabric.py`)**
   - On-demand `(size, mtime_ns, blake2b)` shadow cache scans unchanged files in **`~2 ms`** with zero redundant disk reads.
   - Exchanges deterministic Merkle manifests (`POST /api/merkle/diff`): returns **0-byte payload (`noop`)** when synced; otherwise ships ONLY modified files & tombstones via `CHMRK1` over FastCDC/Odess `BeamServer` (`kind=3`) with full SHA-256 verification and strict path-traversal rejection.

2. **Fluid Pushdown Compute `AQ02` (`chimera_tp/active_pipe.py`)**
   - Pushes computation 100% onto the data-holding node near disk:
     - `log_analytics`: normalizes timestamps, IPs, hex IDs, and integers into unique templates + hourly trends + severity counters.
     - `multi_grep`: regex/substring search across entire source directories (`file_glob`, capped scans).
     - `sqlite_query`: strict read-only (`?mode=ro` URI + single-statement `SELECT`/`WITH`/`PRAGMA TABLE_INFO` allowlist + 3s progress timeout + `max_rows` cap) directly on remote SQLite DBs.
     - `remote_digest`: sub-millisecond remote tree/file hashing without transferring contents.

3. **Telepathic Domain-Trained Dictionary + Template Folding (`chimera_tp/telepathy.py`)**
   - Learns a compact **≤32 KiB** preset `zlib` dictionary sorted with hottest recurring prefixes/lines at the tail (`CHTC1` framing), paired with a lossless byte-exact segment folder (`CHLF1`).
   - Automatically integrated into `ActiveQueryServer` / `remote_active_query` so filtered log results shrink up to **99.15%–99.93%** on the wire—beating both raw transfers and standard `zlib`.

4. **Immortal Stateless Multi-Path RLNC Striping (`chimera_tp/hyper_wire.py`)**
   - Stripes systematic + GF(256) network-coded blocks simultaneously over **IPv4 + IPv6** (`ImmortalMultiPathSender` / `Receiver` on UDP `:9706/:9707`) into one unified decoding matrix, mirroring control feedback on all active sockets.
   - Survives complete mid-stream loss of an IPv4 path with **0 reconnects** and **100% SHA-256 verification**.

5. **Contextual 24h Link Weather Bandit & Zero-Weight Guard (`chimera_tp/autopilot.py`, `dashboard.py`)**
   - Learns optimal genomes (`G0_BALANCED` .. `G4_LOW_JITTER_V6`) per time-of-day window (`NIGHT_CLEAN`, `MORNING`, `AFTERNOON`, `PEAK_EVENING`), tracks link-weather EMAs, recommends the cleanest sync window, and continuously enforces OS-native daemon RSS & free-RAM telemetry.

6. **Dual-ISA Silicon Core (`native/chimera_core` Rust GFNI + `native/chimera_core_c` C11 AVX2)**
   - Bit-identical FastCDC chunk boundaries, Odess SuperFeatures, GF(256) (`0x11B`) SIMD linear solves, and lock-free Named/POSIX `/dev/shm` Wormhole rings on both Windows and Linux.

---

## Verified Live Cross-Host Telemetry (Windows ↔ Linux Over Tailscale ~109 ms RTT)

Measured live between a Windows 11 Controller (`Intel Core i5-11400`, Rust GFNI) and an Ubuntu Linux Server Peer (`Intel Core i5-4300U`, C11 AVX2 `VPSHUFB`, Python 3.14.4):

| Capability | Baseline / Previous | CHIMERA-HYPER v3.0 Live | Gain |
| :--- | :--- | :--- | :--- |
| **Daemon Memory Footprint** | — | **`18.43 MB`** (Win) / **`42.88 MB`** (Linux) | Zero desktop lag (`<80 MB` budget) |
| **Remote Log Filter (`1.70 MB` log, 9,084 hits)** | `1,852.18 ms` TCP / `538.5 KB` v2.0 | **`14.4 KB` wire (`-99.15%`)**, **`194.89 ms`** (`telepathic_fold_zdict`) | **9.50x speedup**, **37x smaller wire vs v2.0** |
| **Fluid `log_analytics` (`23,991` lines)** | Pull `1.70 MB` & parse locally | **`1,200 B` wire (`-99.93%`)**, **`405.44 ms`**, 31 templates | Instant remote summary |
| **Fluid `multi_grep` (`485 KB` codebase)** | Pull tree or SSH shell | **`1,200 B` wire (`-99.75%`)**, **`119.34 ms`** (`10.61 ms` server exec) | Sub-120 ms code search |
| **Fluid `sqlite_query` (Remote RO DB)** | Download full SQLite `.db` | **`1,200 B` wire (`-97.07%`)**, **`114.93 ms`** (`1.12 ms` exec) | Zero raw DB copy |
| **Merkle Directory Sync (`16` files, 1 changed)** | Re-send full tree | **`1.96 ms` scan → `4,800 B` (`-96.84%`)**; 2nd pass **`0 B` (`244.66 ms`)** | 0-RTT no-op when clean |
| **Immortal Chaos Cut (Kill IPv4 Mid-Stream)** | TCP stall / disconnect | TX `[18, 170]`, RX `[8, 120]`, **`0` reconnects**, **`251.19 ms`** | Unbreakable stream continuity |
| **WAN 5% Loss / GFNI Matrix / SHM** | TCP `0.93 Mbps` / Python `73.4 ms` | **`32.57x` WAN (`30.41 Mbps`)** / **`71.83x` GFNI (`1.02 ms`)** / **`8.28 Gbps` SHM** | Hardware-speed recovery |

See [docs/EVALUATION.md](docs/EVALUATION.md) for complete verification metrics and test coverage.

---

## Quick Start

### 1. Build Native Silicon Core
```bash
# Windows (Rust MSVC) / Linux (GCC -O3 -mavx2)
python scripts/build_native.py
```

### 2. Initialize Runtime Operations Config (`~/.chimera_ops/config.json`)
```bash
# Server Peer (Linux)
chimera ops-init --node-name peer-linux --role server --bind 0.0.0.0:9780 --watched-file /path/to/app.log --allow-root /path/to/dev

# Controller Node (Windows)
chimera ops-init --node-name win-desktop --role controller --peer-name peer-linux --peer-ipv4 <PEER_TAILSCALE_IPV4> --peer-ipv6 <PEER_TAILSCALE_IPV6> --watched-file /path/to/app.log --bind 127.0.0.1:9780
```
Runtime state resides exclusively under `~/.chimera_ops/` (see [docs/ops_config.example.json](docs/ops_config.example.json)).

### 3. Run 24/7 Mission-Control Daemon & v3.0 CLI Tools
```bash
# Start 24/7 Cockpit + Beam + Dual-Stack RPC + ActiveQuery + Immortal + Warp
chimera daemon

# 0-RTT Merkle directory sync
chimera merkle-sync --dir ./project --ws myproj --peer-http http://<PEER_IP>:9780 --peer-beam <PEER_IP>:9700

# Fluid pushdown query over UDP + Telepathic compression
chimera fluid --peer-query <PEER_IP>:9704 --path /path/to/app.log --op log_analytics

# Benchmark Telepathic domain compression against raw & plain zlib
chimera telepathy-bench --file /path/to/app.log

# Single contextual autopilot evaluation cycle
chimera autopilot --trigger manual
```

---

## Tests

```bash
python -m unittest discover -s tests -v
```

- **Windows:** **29 / 29 PASS** (`test_chimera`, `test_hyper`, `test_v2_autopilot`, `test_v3_hypergrid`).
- **Linux (`C11 AVX2` + Python 3.14):** **18 / 18 PASS** (`test_hyper`, `test_v2_autopilot`, `test_v3_hypergrid`).

---

## Security & Scope Disclaimer

`chimera-tp` executes `sqlite_query` strictly in read-only URI mode (`?mode=ro`) with a single-statement `SELECT`/`WITH`/`PRAGMA TABLE_INFO` allowlist and strict directory containment (`allowed_roots`), and rejects directory traversal on all Merkle sync unpack/delete operations. For production multi-tenant traffic across untrusted WANs, run inside authenticated Tailscale or WireGuard overlays.
