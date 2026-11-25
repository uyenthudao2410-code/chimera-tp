# CHIMERA-HYPER v2.0.0 — Autonomous Cross-Platform Zero-Bloat Fabric

CHIMERA-HYPER (`chimera-tp`) is an experimental high-throughput transport, synchronization, and compute-in-flight toolkit built for high-RTT, lossy overlay WANs (Tailscale/WireGuard), fast local IPC, and 24/7 autonomous monitoring.

Instead of fighting TCP's head-of-line blocking, repetitive file retransmissions, or transferring raw gigabytes just to grep locally, CHIMERA combines hardware-accelerated Galois arithmetic, sliding-window RLNC, content-defined deduplication, pushdown active pipelines, dual-stack IPv4+IPv6 hedged transport, and a self-tuning Darwinian UCB1 control loop.

---

## Core Architecture (5 Engines + v2.0 Autopilot)

1. **Dual-ISA Silicon GF(256) Core**
   - **Windows x64 (`native/chimera_core` — Rust):** `VGF2P8AFFINEQB` (GFNI) + AVX-512F + AVX2 SIMD matrix engine (`0x11B`) + Lock-Free Shared Memory SPSC Ring + FastCDC/Odess.
   - **Linux x64 (`native/chimera_core_c` — C11):** AVX2 `VPSHUFB` split-nibble GF(256) (`0x11B`), bit-identical FastCDC (`32 KB` avg) + Odess SuperFeatures, Active-Pipe predicate scanner, and POSIX `/dev/shm` lock-free ring (`shm_open` + `mmap`).
   - Verified cross-architecture parity: Windows Rust GFNI and Linux C AVX2 produce **100% bit-identical chunk cut points and Odess SuperFeatures** on identical byte streams.

2. **HyperWire v2 (Sliding-Window RLNC + Wire-Stealth + Dual-Stack Tailscale MTU)**
   - Clamped symbol payload (`1180 B` total packet budget) engineered to survive Tailscale/WireGuard `1280 B` MTU without IP fragmentation.
   - Dual-stack `AF_INET` / `AF_INET6` sockets with single-port symmetric UDP feedback routing (`send_fn` + `feedback_queue`) and NAT punch-through.
   - Ephemeral XOR+MAC stream obfuscation so middleboxes see uniform encrypted entropy.

3. **Zero-RTT DNA Beam (FastCDC + Odess Delta Sync)**
   - Content-defined chunking (`FastCDC`) + similarity sketch indexing (`Odess` SuperFeatures) + byte-level patch opcodes (`EQ`/`DIFF`).
   - Only changed chunk fingerprints and compressed diffs hit the wire (`>95%` wire reduction on 30%-mutated `1 MiB` blobs).

4. **Active Pipe (Pushdown Remote Log & Filter Engine)**
   - Executes log predicates (`filter_lines`, `top_errors`, `regex_count`) right at the data owner before encoding onto the wire.
   - Streams Priority-0 (`P0`) preview hits immediately (~1 RTT first byte) while the compressed full match payload completes in parallel.

5. **v2.0 AUTOPILOT & 24/7 Mission-Control Cockpit**
   - **Darwinian UCB1 Genome Bandit:** Rotates and scores 5 transport genomes (`G0_BALANCED` .. `G4_LOW_JITTER_V6`) based on real LAN/WAN throughput, jitter, and RTT reward, persisted in SQLite (`~/.chimera_ops/telemetry.db`).
   - **Daily Scheduler & Anomaly Alerts:** Runs built-in daily benchmarks + OS-level triggers (`Task Scheduler` on Windows, `systemd --user` timer on Linux) and flags hardware fallbacks or >25% latency regressions.
   - **Web Mission-Control UI (`127.0.0.1:9780` / `0.0.0.0:9780`):** Live throughput/speedup telemetry, 1-click live DNA Beam transfer, on-demand remote log query tester, and genome leaderboard.

---

## Verified Cross-Host Benchmarks (Windows ↔ Linux Over Tailscale ~107 ms RTT)

Measured live between a Windows 11 Controller (`Intel Core i5-11400`, Rust GFNI) and an Ubuntu Linux Server Peer (`Intel Core i5-4300U`, C11 AVX2 `VPSHUFB`, Python 3.14.4):

| Workload | Standard TCP Baseline | CHIMERA-HYPER v2.0 | Gain |
| :--- | :--- | :--- | :--- |
| **GF(256) Matrix (1 MiB, Win Rust GFNI)** | `75.35 ms` (Python LUT) | `0.82 ms` (Native GFNI) | **91.48x** (7d avg **167.71x**) |
| **GF(256) Matrix (1 MiB, Linux C AVX2)** | `83.59 ms` (Python LUT) | `1.05 ms` (C11 `VPSHUFB`) | **79.74x** (7d avg **81.15x**) |
| **Zero-Copy Shared Memory IPC** | TCP Loopback (`2.23–5.22 Gbps`) | Lock-Free Ring (`3.53 Gbps` Win latest, **5.04 Gbps** Win 7d avg / **2.02 Gbps** Linux 7d avg) | Zero-syscall SPSC ring |
| **100 ms RTT, 5% Loss (128 KB)** | `0.92–0.95 Mbps` (`~4.4–4.5 s`) | `21.39 Mbps` (Win) / `40.14 Mbps` (Linux) | **23.20x – 42.22x** |
| **Live DNA Beam (1 MiB, 30% mutated)** | `1,131.14 ms` (`7.42 Mbps`) | `251.90 ms` (`33.30 Mbps`, `37.2 KB` wire) | **4.49x speedup**, **96.89% wire saved** |
| **Live Active Log Query (`1.70 MB` prod log, 9,084 `ERROR` hits)** | `1,314.18 ms` (pull full + local grep) | `292.55–296.63 ms` total (`114.4 ms` P0 first hit, `5.25 ms` remote exec) | **4.43x speedup**, **68.31% wire saved** |

See [docs/EVALUATION.md](docs/EVALUATION.md) for methodology and raw counters.

---

## Quick Start

### 1. Build Native Silicon Core
```bash
# Windows (requires Rust MSVC toolchain)
python scripts/build_native.py

# Linux (requires gcc with -mavx2; falls back cleanly to portable C flags if needed)
python3 scripts/build_native.py
```

### 2. Initialize Runtime Operations Config (`~/.chimera_ops/config.json`)
```bash
# Server Peer (Linux)
chimera ops-init --node-name peer-linux --role server --dashboard-bind 0.0.0.0:9780 --watched-query-file /path/to/app.log

# Controller Node (Windows)
chimera ops-init --node-name win-desktop --role controller --peer-name peer-linux --peer-ipv4 <PEER_TAILSCALE_IPV4> --peer-ipv6 <PEER_TAILSCALE_IPV6> --watched-query-file /path/to/app.log --dashboard-bind 127.0.0.1:9780
```
Runtime configs and SQLite databases live exclusively under `~/.chimera_ops/` and are never committed to Git. See [docs/ops_config.example.json](docs/ops_config.example.json).

### 3. Run Daemon + Daily Autopilot
```bash
# Start 24/7 Mission-Control Dashboard + Beam / HedgedRPC / ActiveQuery / Warp servers
chimera daemon

# Run an immediate single autopilot cycle (Darwinian UCB1 + WAN + Cross-Host verification)
chimera autopilot --trigger manual --profile auto-darwin
```

### 4. Register Daily Automation (OS-Specific)
- **Windows:** `schtasks` daily at `08:00` calling `chimera autopilot --trigger scheduled` + logon trigger for `chimera daemon`.
- **Linux:** `systemd --user` persistent unit `chimera-hyper-daemon.service` + `chimera-hyper-daily.timer` (`OnCalendar=*-*-* 08:00:00`, `loginctl enable-linger`).

---

## Tests

```bash
python -m unittest discover -s tests -v
```

- **Windows (`win-desktop`):** Full suite (`test_chimera`, `test_hyper`, `test_v2_autopilot`) covering local realms, Rust GFNI/AVX2 kernels, HyperWire, Wormhole SHM, DNA Beam, Active Pipe, Warp proxy, SQLite telemetry, Darwinian UCB1 selection, and HTTP cockpit APIs.
- **Linux (`peer-linux`):** `test_hyper` + `test_v2_autopilot` verifying C11 AVX2 `VPSHUFB`, POSIX `/dev/shm` Wormhole, POSIX `probe`, cross-platform config, and live server APIs.

---

## Security & Scope Disclaimer

`chimera-tp` is an experimental WAN/IPC transport engine. Its ephemeral wire obfuscation protects packet headers against passive heuristics; for production multi-tenant deployment over untrusted networks, always run behind authenticated private overlays such as Tailscale or WireGuard (authenticated Noise/ChaCha20-Poly1305).
