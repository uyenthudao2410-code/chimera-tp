# Evaluation — CHIMERA-HYPER v3.0.0 Zero-Weight HyperGrid Results

All cross-host telemetry below was recorded live on the two-node cluster over a real Tailscale WAN path (`~109.08 ms` median RTT) running `CHIMERA-HYPER v3.0.0` daemons on both machines.

## 1. Automated Verification Suites (Verified After Final Edits)

- **Windows (`python -m unittest discover -s tests -v`)**: **29 / 29 PASS** (`test_chimera`, `test_hyper`, `test_v2_autopilot`, `test_v3_hypergrid`).
- **Linux (`python3 -m unittest tests/test_hyper.py tests/test_v2_autopilot.py tests/test_v3_hypergrid.py -v`, Python 3.14.4 + C11 AVX2)**: **18 / 18 PASS in `13.831s`**.

## 2. Zero-Weight Memory Footprint (Windows Desktop Guardrail)

| Process / Node | Measured Daemon RSS | Host Free RAM | Host Total RAM | Budget Status |
| :--- | :---: | :---: | :---: | :--- |
| **Windows Controller (`win-desktop`)** | **`18.43 MB`** (peak during run: `19.21 MB`) | `10.72 GB` | `30.85 GB` | Zero lag (`< 80 MB` budget) |
| **Linux Server Peer (`server-peer`)** | **`42.88 MB`** (baseline `31.15 MB`) | `6.62 GB` | `10.61 GB` | Within budget (`< 80 MB`) |

## 3. Telepathic Compression & Fluid Pushdown Benchmarks (Live WAN)

All remote queries executed against real server artifacts over UDP `:9704` (`AQ02` + `CHTC1`) from Windows to Linux:

| Operator & Target | Raw Size | Compressed Payload | Wire Bytes | Wire Saved | Latency / Notes |
| :--- | :---: | :---: | :---: | :---: | :--- |
| **`filter_lines` (`ERROR`, prod log)** | `1,699,190 B` | **`13,444 B`** (`telepathic_fold_zdict` vs `15,118 B` plain zlib) | **`14,400 B`** | **`99.15%`** | **`194.89 ms`** total vs `1,852.18 ms` TCP (**9.50x speedup**; `37x` less wire than v2.0 `538.5 KB`) |
| **`log_analytics` (prod log)** | `1,699,190 B` | **`863 B`** (`telepathic_zdict` vs `957 B` plain zlib; `3,975 B` JSON) | **`1,200 B`** | **`99.93%`** | **`405.44 ms`**, collapsed `23,991` lines into `31` templates (`server_exec=292.37 ms`) |
| **`multi_grep` (`chimera_tp/` tree)** | `485,251 B` | `201 B` (`465 B` matches) | **`1,200 B`** | **`99.75%`** | **`119.34 ms`** total (`10.61 ms` remote tree scan, `7` matches) |
| **`sqlite_query` (remote `telemetry.db`)** | `40,960 B` | `275 B` (`516 B` JSON) | **`1,200 B`** | **`97.07%`** | **`114.93 ms`** total (`1.12 ms` RO SQLite execution, `P0=113.68 ms`) |

## 4. Merkle Directory 0-RTT Sync & Incremental DNA Beam

- **Merkle 16-file Workspace (`152,071 B`, `1` file mutated = `164 B`):**
  - Shadow index scan: **`1.96 ms`** (re-hashed only `1` file out of `16`, skipping `15` disk reads).
  - Sparse wire payload (`dna_wire=200 B`): **`4,800 B` UDP wire** (`96.84%` reduction), `verified_root_match=true`.
  - Immediate 2nd sync pass (`second_pass_noop=true`): **`0 B` payload**, root verification in **`244.66 ms`**.
- **1 MiB Binary Delta (`beam`):** **`38,400 B`** UDP wire (**`96.90%` saved**) in `279.18 ms` vs `1,276.76 ms` TCP HTTP (`4.57x` speedup).

## 5. Immortal Multi-Path Mid-Stream Blackout Test (Real Tailscale IPv4 + IPv6)

- Payload: `131,072 B` striped concurrently across Tailscale IPv4 (`:9706`) and IPv6 (`:9707`) with `chaos_kill_lane=0` executed after Generation 1.
- Observed TX packet split: **`[18, 170]`** (`18` IPv4 packets before lane cut, `170` packets carried over IPv6).
- Observed peer RX packet split: **`[8, 120]`** (`peer_sha256_match=true`).
- Reconnects triggered: **`0`** | Total completion including chaos cut: **`251.19 ms`** (`survived_blackout=true`).

## 6. Silicon Core, SHM Ring & Lossy WAN Summary (`v3.0` Run)

- **Windows GFNI (`1 MiB` matrix):** `1.02 ms` vs Python LUT `73.39 ms` (**`71.83x`**).
- **Zero-Copy Shared Memory Ring (`16 MiB`):** **`8.28 Gbps`** (`16.22 ms`) vs TCP loopback `6.27 Gbps`.
- **WAN 5% Loss Emulation (`512 KiB`):** `137.92 ms` (`30.41 Mbps`, 13 GFNI solves) vs TCP `4,492.68 ms` (`0.934 Mbps`) = **`32.57x` speedup**.
- **Contextual Link-Weather Active Winner (`AFTERNOON`):** `G4_LOW_JITTER_V6` (`reward=8.292`).
