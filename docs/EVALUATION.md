# Evaluation — CHIMERA-HYPER v7.0.0 OMEGA-FABRIC Live Cluster Results

All cross-host telemetry below was measured live across the two-node cluster (`Windows Controller Rust GFNI/AVX512F` ↔ `Linux Hub C11 AVX2, Python 3.14.4`) running `CHIMERA-HYPER v7.0.0` 24/7 daemons with `PHANTOM_5MS_DIRECT` (**`5.8 ms`** direct UDP RTT).

## 1. Automated Verification & Native Parity (`v7.0.0`)

- **Windows (`python -m unittest discover -s tests -v`)**: **53 / 53 PASS in `65.270s`** (`0` failures, `0` skipped — `test_chimera`, `test_hyper`, `test_v2_autopilot`, `test_v3_hypergrid`, `test_v4_hyperos`, `test_v5_phantom`, `test_v6_synergy`, `test_v7_omega`).
- **Linux (`python3 -m unittest discover -s tests -v`)**: **53 / 53 PASS in `45.678s`** (`0` failures, `0` skipped). Note: `test_parallel_dispatch_and_profiles_turbo_stealth` experienced one transient timing flake prior to clean rerun pass on both hosts.
- **CLI Entrypoints**: All 8 CLI `--help` checks (`--help`, `omega`, `synergy`, `pty`, `fs`, `medic`, `drop`, `daemon`) exited `0`.
- **Cross-Core Bit-Exact Rust ↔ C11 SHA-256 Parity (`4/4` native primitives `True` on both hosts)**:
  - `chimera_chacha20_xor`: `9147a3d293ae877f8a95f08386f8970fa28a4e343c39dee89790bf39d7bca230`
  - `chimera_gf256_recode`: `a54835898d1684ebc8679db73f628b4c1a5a440c6a0961f911097de3d60789c4`
  - `chimera_slepian_syndrome`: `5c70dfa433b9d3408918e33c408a984ca7e26f903734286b8f31cc341583a144`
  - `chimera_ppm_compress`: `647accc9d3eea899720f57a571fece1cbe2561a3bcc8531f07a3128addd7f06b`

## 2. Zero-Weight Memory Footprint & OS Capability Honesty

| Node / Process | Measured `VmRSS` / Working Set | Budget (`80 MB`) | Hardware / Unprivileged OS Probe |
| :--- | :---: | :---: | :--- |
| **Windows Controller (`pythonw`, v7.0.0)** | **`32.79 MB`** | PASS (`41.0%`) | `gfni=True, avx2=True, avx512f=True`, `wintun=False`, `WinFsp=False`, `privileged=False` |
| **Linux Server Hub (`systemd`, v7.0.0)** | **`44.40 MB`** | PASS (`55.5%`) | `avx2=True`, `/dev/net/tun` present (`privileged=False`), `/usr/bin/fusermount3` (`FUSE3`) |

## 3. Live 14-Idea Before vs After Matrix (`POST /api/omega/benchmark`, `469.81 ms`, `14/14 PASS`)

| # / Capability | Before (Baseline) | After (`CHIMERA-HYPER v7.0.0` Live) | Status |
| :--- | :--- | :--- | :---: |
| **1. Rust/C11 X25519 + ChaCha20 Virtual NIC** | Per-port Python proxy | **IPv4/ChaCha20 native (`1216 B`, `4.03 ms`)** | PASS |
| **2. Multi-ISP RLNC Bonding** | Single NIC drop → TCP stall/reset | **`0 ms` failover across 2 lanes (survived `5` drops in `2.25 ms`)** | PASS |
| **3. Polymorphic QUIC/WebRTC Mimicry** | Custom UDP blocked by DPI | **Auto-morphed → `webrtc` (`270 B`)** | PASS |
| **4. Multi-Hop RLNC Recoding-in-Flight** | Hop-by-hop store-decode/ARQ | **Native `GF(256)` recode (`0.962 ms`, `0` relay plaintext)** | PASS |
| **5. Ghost-Block 4KB File Patch** | Re-upload `26,624 B` whole file | **`95 B` delta (`-99.64%`, `1/7` dirty blocks)** | PASS |
| **6. Self-Healing GF(256) Regenerating Mesh** | Static single-copy or full rebuild | **`3-of-5` Cauchy heal in `0.05 ms` (entropy `5.8007 b/B`)** | PASS |
| **7. Sandboxed WASM Active-Pipe AQ03** | Pull `16,800 B` log over WAN | **`109 B` `.wasm` → `count=1200` (`251.14 ms`, `274,812` ops)** | PASS |
| **8. Slepian-Wolf 0-RTT Blind Delta** | 1–2 RTT Merkle/rsync round-trip | **0-RTT `3,124 B` syndrome (`-72.6%`, fixed `2` blks)** | PASS |
| **9. Serverless Parasitic Dead-Drop ($0)** | Blocked when VPN/VPS drops | **Survived `2/5` dead channels in `0.37 ms` (`5.684 b/B`)** | PASS |
| **10. Compressed 4KB Remote RAM Pool** | Local swap / OOM pressure | **`16 KB → 843 B` (`-94.85%`, `REMOTE_HTTP` live, `163.05 ms`)** | PASS |
| **11. Hybrid MLWE+X25519 & Chaff-RLNC** | Classical ECDH + wasted chaff BW | **PQ `672 B` CT + chaff repaired `3/12` drops (`26.15 ms`)** | PASS |
| **12. Native Order-2 PPM Range Codec** | Raw `16,559 B` / `zlib-9` `650 B` | **PPM `608 B` (`-6.46%` vs `zlib-9`, `9.63 ms`)** | PASS |
| **13. Zero-Freeze UEP-RLNC Display** | Plain crisp text at 15% loss: `11/25` | **UEP crisp text: `25/25` (`6.78 ms`)** | PASS |
| **14. Self-Mutating Genetic Wire DNA** | Static default fitness `0.01` | **Evolved `87.007` (`webrtc`, `12 B` hdr)** | PASS |

- **Remote Cross-Host Execution Over 5 ms PHANTOM Tunnel (`win-desktop → Linux hub`)**:
  - `POST /api/omega/wasm-exec`: executed `109 B` `.wasm` module remotely in **`0.72 ms`** (`executed_on: "svhome"`, `result: 3`, `299 ops`).
  - `POST /api/omega/slepian-sync`: decoded 0-RTT syndrome remotely (`3,124 B` vs `7,200 B`, **`-56.61%`**, `1.47 ms`, `bit_exact: true`, `node_name: "svhome"`).

---

## Inherited `v6.0.0` APEX-SYNERGY & `v5.0.0` PHANTOM-5MS Live Baselines

All telemetry below remains active in `v7.0.0`:

### `v6.0.0` Verification Suites (Historical Baseline)

- **Windows (`python -m unittest discover -s tests -v`)**: **48 / 48 PASS in `63.517s`** (`0` failures, `0` skipped — suites `test_chimera`, `test_hyper`, `test_v2_autopilot`, `test_v3_hypergrid`, `test_v4_hyperos`, `test_v5_phantom`, `test_v6_synergy`).
- **Linux (`python3 -m unittest discover -s tests -v`)**: **48 / 48 PASS in `41.295s`** (`0` failures, `0` skipped).
- **Radar Integration Hook Verification**: `radar_dashboard/app/crew.py` syntax-checked (`py_compile` exit `0`) and targeted pytest suite passed **`19 passed in 3.55s`**.
- **CLI Entrypoints**: All 7 subcommands (`synergy`, `phantom`, `pty`, `fs`, `medic`, `drop`, `context-pack`) verified exit `0` on both Python 3.11 and Python 3.14.

## 2. Zero-Weight Memory Footprint (Even During 25 MB GF(256) Vault Operations)

| Node / Process | Measured `VmRSS` / Working Set | Budget (`80 MB`) | Notes |
| :--- | :---: | :---: | :--- |
| **Windows Controller (`pythonw`)** | **`14.50–33.07 MB`** | PASS (`18.1–41.3%`) | Hosts Cockpit `:9780`, Edge + WebDAV `:9788`, Phantom `:2222`/`:9789`/`:12550` |
| **Linux Server Hub (`systemd`) — Idle / Healthy** | **`45.43 MB`** | PASS (`56.8%`) | Hosts Hub `:9780`/TS `:9781`, Phantom UDP `:9710`, EdgeGateway, Synergy Engine |
| **Linux Server Hub — After 25 MB Vault (isolated)** | **`46.28 MB`** (`+0.85 MB` delta) | PASS (`57.9%`) | Subprocess worker isolation eliminated earlier `103.64 MB` glibc arena retention |

## 3. Verified Live `v6.0.0` APEX-SYNERGY Results

### 1. `PHANTOM-12550` AI Relay Tunnel (`127.0.0.1:12550 -> svhome:12500`)
- Tunnel converged automatically on startup to `PHANTOM_5MS_DIRECT` (**`5.69 ms`** direct UDP RTT during vault/brief run, range `4.28–6.15 ms`).
- `GET http://127.0.0.1:12550/v1/models` (`10` models) from Windows: **`36.63 ms` min / `60.12 ms` p50 / `53.26 ms` mean** (and **`52.68 ms`** after reconnect) vs **`506.63 ms`** over Tailscale HTTPS (`:12504/api/status`) — **`9.5x` lower latency**.
- `GET http://127.0.0.1:9788/tqouta/api/status` via Edge Proxy: **`24.52–39.99 ms`** (`200 OK`).

### 2. 0-Token Pre-Surgical Brief (`/api/synergy/surgical-brief`)
- Tested live against a completed multi-contract + JS bounty workspace:
  - Filtered compiled artifacts (`artifacts`, `cache`) automatically.
  - Scanned **`54` source files (`390,409 B`) -> generated `4,104 B` surgical map (`-98.95%` scan volume)** in **`71.89 ms`** (`102.82 ms` E2E, **`0` AI tokens**).
  - Top-5 ranked files matched **`4 / 4`** actual files touched in the winning `solution.patch`, alongside `6` relevant test files.

### 3. Redacted Quota Arbiter (`/api/synergy/status`)
- Live aggregated state across relay & bounty engines (`959.61 ms` E2E):
  - Relay metrics observed: `6/6` enabled accounts (`ok=6`, `needs_reauth=0`, `unknown_pool_count=3`), `16,755` requests, `11,889` auto-cut requests, **`76.62%` cache hit ratio** (`263,405,220` cached / `343,768,906` input tokens).
  - Bounty engine telemetry: `50` approvals queued, `15` crew runs, `17` clean ships (30d), `barbell_alert=false`.
  - Evaluated regime: **`BALANCED`** (`max_parallel_solvers=2`, `brief_max_chars=5200`).
  - Redaction assertion verified: **`email_leak_zero = true`** (`0` `@` occurrences).

### 4. Token-Burn Circuit Breaker (`/api/synergy/burn-scan`)
- Scanned all **`13` active solver workspaces** on Linux in **`10.85 ms`** (`47.47 ms` E2E), reporting **`alert_count: 0`**.

### 5. 5-Second Ready-Bounty WebDAV Review & Browser Index (`/dav/` + `/api/synergy/bounties`)
- Identified **`6` ready workspaces** holding non-empty `solution.patch` diffs in **`51.69 ms`** with parsed diff counts and clickable `/dav/` URLs.
- Browser `GET http://127.0.0.1:9788/dav/` verified **`200 text/html`** (`GHOSTFS-DAV-INDEX`) + `302` folder normalization + `GET` of a real `solution.patch` (`12,664 B`, `200 OK`, ETag `"50f8e4a49f6bcdba"` in **`54.16 ms`**) + `PROPFIND 207` preserved (`7,543 B`).
- `POST /api/synergy/bounty-drop` pushed top diff summary into `Drop-Portal` in **`26.37 ms`** and cleaned up cleanly.

### 6. Subprocess-Isolated GF(256) `(K=2, N=3)` Apex Vault (`/api/synergy/vault-backup`)
- Packed **`7` critical files** (`local-state.json`, `adaptive-cpt.json`, `agent-context-budget.json`, `instructions-hoist-lock.enc`, `alpha_suite_state.json`, `turbo_suite_state.json`, and an atomic read-only SQLite `.backup()` of `radar.db`):
  - **`25,007,290 B` raw -> `5,378,669 B` compressed** (`5,379,005 B` per shard, Shannon entropies **`[8.0, 8.0, 8.0]` bits/B**) in **`1,926.59 ms`** (`1,967.29 ms` E2E).
  - Linux daemon RSS measured immediately after backup: **`46.28 MB`** (`zero_weight_ok: true`, `< 80 MB`).

---

## Inherited `v5.0 PHANTOM-5MS` Live Baseline
- **Direct P2P HTTP `/api/health` p50**: **`10.55 ms`** (`7.41 ms` min) vs `203.18 ms` Tailscale (**`19.26x`**) | **Real SSH `:2222`**: **`214.28–233.41 ms`** vs `1,238–1,248 ms` (**`5.55x`**) | **Ghost-PTY**: `19.6 ms` spawn / `28.68 ms` reattach | **Medic**: `4.24 ms` log dossier / `487.64 ms` FTS5 (`1,949` files) | **Core Autopilot**: `100/100` health, GFNI `85.04x`, WAN 5% drop `29.22x`, Query `-99.15%`.
