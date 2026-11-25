# Evaluation — CHIMERA-HYPER v2.0.0 Live Cluster Results

All metrics below were collected live on the two-node personal cluster running `CHIMERA-HYPER v2.0.0` (`auto-darwin` policy) over Tailscale (~`107 ms` median RTT across WAN relay) after deploying the C11 AVX2 Linux engine and v2.0 Autopilot daemon.

## 1. Test Environment

| Role | Host Type | OS & Python | CPU / SIMD Core | Runtime Core |
| :--- | :--- | :--- | :--- | :--- |
| **Controller** | Desktop (`win-desktop`) | Windows 11, Python 3.11 | Intel Core i5-11400 (GFNI + AVX2 + AVX-512F) | Rust `chimera_core.dll` (`121 KB`) |
| **Server Peer** | Linux Mini-Server (`server-peer`) | Ubuntu Linux, Python 3.14.4 | Intel Core i5-4300U (AVX2) | C11 `_chimera_core.so` (`38 KB`, `-O3 -mavx2`) |
| **Transport** | Tailscale Dual-Stack | IPv4 + IPv6 (`AF_INET`/`AF_INET6`) | UDP `1180 B` MTU-safe symbols | ~`107.16 ms` RTT p50 |

## 2. Automated Test Suites (Post-Edit Verification)

- **Windows (`python -m unittest discover -s tests -v`)**: Full unit & integration coverage (`test_chimera`, `test_hyper`, `test_v2_autopilot`) verifying GF(256) bit-accuracy, local realms, shared memory, FastCDC/Odess, Active Pipe, Autopilot SQLite UCB1, and Dashboard HTTP endpoints.
- **Linux (`python3 -m unittest discover -s tests -p "test_*.py" -v`, `test_hyper` + `test_v2_autopilot`)**: **13 / 13 PASS** in `12.094s` after Python 3.14 compatibility fixes and POSIX probe/SHM integration.

## 3. Cross-Architecture Parity Proof

Hashing and chunking identical synthetic byte buffers on Windows (`Rust GFNI`) and Linux (`C11 AVX2`):
- **FastCDC Cuts:** **13 identical chunks** (`[(0, 33626), (33626, 56949), (56949, 91706), (91706, 130162), ...]`).
- **Odess SuperFeatures:** Identical 4x64-bit tuple `(18242410013437716149, 14679853018764441541, 5222286628722741605, 12538750460317429453)`.

This guarantees a Windows controller and Linux peer always agree on chunk boundaries and delta patches without ambiguity.

## 4. Measured Benchmark Metrics

### A. Silicon Math & Local IPC (`1 MiB` Matrix / Zero-Copy Ring)
- **Windows Rust GFNI:** `0.82 ms` vs Python LUT `75.35 ms` = **91.48x** latest run (**167.71x** 7-day average across 4 runs; peak **375.27x**).
- **Linux C11 AVX2 `VPSHUFB`:** `1.05 ms` vs Python LUT `83.59 ms` = **79.74x** latest run (**81.15x** 7-day average across 3 runs).
- **Lock-Free Shared Memory Ring:** **5.04 Gbps** 7-day average on Windows (`8.11 Gbps` peak); **2.02 Gbps** 7-day average on `server-peer`.

### B. Lossy WAN Emulation (`128 KB`, `100 ms` RTT, `5%` Packet Loss)
- **Windows:** CHIMERA `196.11 ms` (`21.39 Mbps`, 11 linear solves) vs TCP `4,549.01 ms` (`0.92 Mbps`) = **23.20x** latest (**28.13x** 7-day average, peak **41.61x**).
- **Linux (`server-peer`):** CHIMERA `104.50 ms` (`40.14 Mbps`, 11 linear solves) vs TCP `4,412.51 ms` (`0.95 Mbps`) = **42.22x** latest (**32.84x** 7-day average).

### C. Live Cross-Host DNA Beam Over Tailscale (`1 MiB` blob, `30%` mutated)
- **TCP Baseline (`POST /api/tcp_sink`):** `1,131.14 ms` (`7.42 Mbps`, `1,048,576 B` on wire).
- **CHIMERA DNA Beam:** `251.90 ms` (`33.30 Mbps` effective, `37,200 B` on wire) = **4.49x speedup**, **96.89% wire reduction** (7-day average **5.78x**).

### D. Live Cross-Host Active Pipe Remote Log Query (`1,699,190 B` production log, `9,084` `ERROR` lines)
- **Baseline (`GET /api/raw_query_file` + client filter):** `1,314.18 ms` (full `1.70 MB` pulled over Tailscale).
- **CHIMERA Active Pipe:** `292.55–296.63 ms` total (`538,524 B` compressed wire = **68.31% saved**, `5.25 ms` remote filter execution, **`114.41 ms` P0 first preview match**) = **4.43x speedup** (`4.50x` 7-day average; up to `5.81x` on cold run).

## 5. Darwinian UCB1 Genome Leaderboard (Live Observed)

| Genome ID | Policy Focus | Windows Avg Reward | Linux Avg Reward |
| :--- | :--- | :---: | :---: |
| `G2_LOSSY_ARMOR` | `gen_k=32`, `loss_hint=0.06`, `hedge=0ms` | **8.710** | **5.758** |
| `G1_DUAL_RACE` | `gen_k=32`, `loss_hint=0.02`, `hedge=0ms` | 7.582 | 5.024 |
| `G3_TURBO_BULK` | `gen_k=32`, `inflight=36`, `hedge=25ms` | 6.738 | Unpulled |
| `G0_BALANCED` | `gen_k=32`, `loss_hint=0.00`, `hedge=15ms` | 6.139 | 4.104 |
| `G4_LOW_JITTER_V6` | `gen_k=24`, `loss_hint=0.03`, `hedge=5ms` | Queued | Queued |

Proactive forward error protection (`G2_LOSSY_ARMOR`) currently dominates on the `~107 ms` WAN relay path because absorbing random loss without waiting an extra `107 ms` ARQ round-trip maximizes effective throughput.
