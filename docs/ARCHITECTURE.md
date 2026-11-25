# Architecture — CHIMERA-HYPER v2.0.0

```
+-----------------------------------------------------------------------------+
|                        Control & Observability Plane                        |
|   HTTP Cockpit (127.0.0.1:9780)  |  SQLite Telemetry & Darwinian UCB1 Bandit |
|   Built-in 08:00 Daily Scheduler |  OS Triggers (Task Scheduler / systemd)   |
+--------------------------------------+--------------------------------------+
                                       |
      +--------------------------------+--------------------------------+
      v                                v                                v
+--------------------+      +-----------------------+      +--------------------+
|   Transport Fabric |      |   Zero-RTT DNA Beam   |      |    Active Pipe     |
|  HyperWire v2 RLNC |      | FastCDC + Odess + Zstd|      | Remote Pushdown UI |
|  Dual-Stack v4/v6  |      | Byte-Level Delta Sync |      | P0 Preview -> Body |
+---------+----------+      +-----------+-----------+      +---------+----------+
          |                             |                            |
          +-----------------------------+----------------------------+
                                        |
                                        v
+-----------------------------------------------------------------------------+
|                        Cross-Platform Silicon Core                          |
|   Windows: Rust cdylib (VGF2P8AFFINEQB GFNI / AVX2 + Named Shared Memory)   |
|   Linux:   C11 .so    (AVX2 VPSHUFB Split-Nibble GF256 + POSIX /dev/shm)    |
+-----------------------------------------------------------------------------+
```

## 1. Dual-ISA Silicon Core (`chimera_tp/native.py`)

Both native libraries export an identical ABI via `ctypes` so all higher layers (`gf256.py`, `active_pipe.py`, `hyper_wire.py`, `fabric.py`) operate identically on Windows and Linux:

| Symbol | Role | Windows Implementation (`chimera_core.dll`) | Linux Implementation (`_chimera_core.so`) |
| :--- | :--- | :--- | :--- |
| `chimera_cpu_caps` | Bitmask probe | CPUID (GFNI, AVX2, AVX-512F) | `__builtin_cpu_supports("avx2")` |
| `chimera_gf256_muladd` | `dst ^= src * coeff` in GF(2^8) `0x11B` | Rust `VGF2P8AFFINEQB` / AVX2 | C11 AVX2 `_mm256_shuffle_epi8` high/low nibble tables |
| `chimera_fastcdc_cut` | Content-defined chunking | Gear rolling hash (`32 KB` target) | Identical Gear table & masks (`32 KB` target) |
| `chimera_odess_superfeatures` | Chunk similarity sketch | AVX2/scalar Odess rolling hash | Identical Odess rolling hash |
| `chimera_delta_diff` / `apply` | Byte-level patch codec | `EQ` / `DIFF` run-length opcodes | Identical `EQ` / `DIFF` opcodes |
| `chimera_active_filter` | Native line filter | Substring scan | Identical substring scan |
| `chimera_shm_*` | Lock-free SPSC ring | Win32 `CreateFileMappingW` | POSIX `shm_open` + `mmap` (`/dev/shm`) |

## 2. HyperWire v2 & Single-Port NAT/Firewall Traversal (`chimera_tp/hyper_wire.py`)

Cross-host Tailscale/WireGuard traversal introduces two real-world constraints that v2.0 solves directly:

1. **Overlay MTU (`1280 B`)**: `SYM_SIZE = 1180`, `_CHUNK_MAX = 1140` prevents IP fragmentation across Tailscale DERP relays and direct UDP tunnels.
2. **Asymmetric Firewall Blocking Return Ephemeral Sockets**: Windows Defender Firewall frequently drops inbound UDP from peers if sent to a random ephemeral return port. `BeamServer` (`:9700`) and `ActiveQueryServer` (`:9704`) accept outbound-punched packets (`punch()`) and route feedback (`CH` ACK/solve packets) back through `send_fn` on the same bound server socket using `HyperWireSender`'s internal `feedback_queue`.
3. **Wire Protocol Demultiplexing**:
   - `b"CH"` header prefix: HyperWire RLNC packet (data coded symbols + feedback ACKs).
   - `b"AQ01"` header prefix: Active Pipe remote query envelope & P0/payload framing (collision-free with `b"CH"` on shared listeners).

## 3. Dual-Stack Hedged RPC (`chimera_tp/warp.py`, `chimera_tp/dashboard.py`)

When an IPv4 and IPv6 Tailscale address are configured, the controller's `HedgedRpcClient` dispatches concurrent or staggered (`hedge_delay_ms`) probes to `:9702` (IPv4) and `:9703` (IPv6), taking the first valid response to crush `p99` tail latency during path shifts or relay congestion.

## 4. Autopilot & Darwinian UCB1 Bandit (`chimera_tp/autopilot.py`)

Five parameter genomes define tuning across loss hint, generation size `K`, inflight generations, and hedge delay:

- `G0_BALANCED` (`gen_k=32`, `inflight=24`, `loss_hint=0.00`, `hedge=15ms`)
- `G1_DUAL_RACE` (`gen_k=32`, `inflight=28`, `loss_hint=0.02`, `hedge=0ms`)
- `G2_LOSSY_ARMOR` (`gen_k=32`, `inflight=32`, `loss_hint=0.06`, `hedge=0ms`)
- `G3_TURBO_BULK` (`gen_k=32`, `inflight=36`, `loss_hint=0.01`, `hedge=25ms`)
- `G4_LOW_JITTER_V6` (`gen_k=24`, `inflight=24`, `loss_hint=0.03`, `hedge=5ms`)

At each run, UCB1 picks either an unpulled genome (to guarantee full exploration) or maximizes `avg_reward + C * sqrt(ln(N) / n_i)`. Rewards combine normalized GF(256) speedup, WAN 5%-loss throughput speedup, DNA Beam efficiency, Active Query speedup, and dual-stack latency gains. Any fallback from native SIMD, beam failure, or severe regression lowers `health_score` and logs an `ANOMALY` event in SQLite.

## 5. 24/7 Mission-Control Cockpit (`chimera_tp/dashboard.py`)

A self-contained `ThreadingHTTPServer` binds to `127.0.0.1:9780` (controller) or `0.0.0.0:9780` (peer, Tailscale-protected) and exposes:

- `GET /` — Interactive single-page dark cockpit with live hardware badges, cross-host benchmark cards, DNA Beam transfer test button, remote log grep tester, and genome leaderboard.
- `GET /api/health` — Minimal node health + ISA bitmask.
- `GET /api/status` — Active config, 7-day averages, history, genome stats, and anomaly feed.
- `POST /api/run` — Trigger `auto-darwin` or explicit profile run on demand.
- `POST /api/live-beam` — Live DNA Beam differential sync to peer + comparison against raw TCP upload (`/api/tcp_sink`).
- `POST /api/live-query` — Live Active Pipe remote log filter vs full-file TCP baseline (`/api/raw_query_file`).
- `POST /api/profile` — Switch active autopilot policy (`auto-darwin`, etc.).
- `POST /api/exotic-audit` — Run deterministic cross-check audit across GF(256), SHM, and Active Query invariants.
