# Evaluation — CHIMERA-HYPER v5.0.0 PHANTOM-5MS Live Cluster Results

All cross-host telemetry below was measured live across the two-node cluster (`Windows 11 i5-11400 Rust GFNI` ↔ `Ubuntu Linux i5-4300U C11 AVX2, Python 3.14.4`) running `CHIMERA-HYPER v5.0.0` 24/7 daemons with `phantom_enabled = true`.

## 1. Automated Verification Suites (Verified After Final Edits)

- **Windows (`python -m unittest discover -s tests -v`)**: **42 / 42 PASS in `56.351s`** (`0` failures, `0` skipped — suites `test_chimera`, `test_hyper`, `test_v2_autopilot`, `test_v3_hypergrid`, `test_v4_hyperos`, `test_v5_phantom`).
- **Linux (`python3 -m unittest discover -s tests -v`)**: **42 / 42 PASS in `34.539s`** (`0` failures, `0` skipped).
- All 7 new/updated CLI `--help` entrypoints (`daemon`, `phantom`, `pty`, `fs`, `medic`, `drop`, `context-pack`) verified exit `0` on both Python 3.11 (Windows) and Python 3.14 (Linux).

## 2. Zero-Weight Memory Footprint (Windows + Linux Daemons)

| Node / Process | Measured `VmRSS` / Working Set | Budget (`80 MB`) | Hosted Stack |
| :--- | :---: | :---: | :--- |
| **Windows Controller (`pythonw`)** | **`21.19–26.01 MB`** steady (`32.34 MB` cold start) | PASS (`26.5–40.4%`) | Cockpit `:9780`, Edge + WebDAV `:9788`, Phantom `:2222`/`:9789`, Warp, Beam, Query, Immortal |
| **Linux Server Hub (`systemd`)** | **`44.38–44.80 MB`** idle (`58.18–58.36 MB` post-FTS5 reindex) | PASS (`55.5–73.0%`) | Cluster Hub `:9780`/TS `:9781`, Phantom UDP `:9710`, EdgeGateway, Sentinel, FTS5 Index, Ghost-PTY/FS/Medic/Portal |

## 3. Before (`v4.0` Tailscale) vs After (`v5.0` PHANTOM-5MS) Live Benchmarks

### Engine #1 — PHANTOM-5MS Encrypted P2P Tunnel (`PH5E`)
- Tunnel converged automatically on startup to **`PHANTOM_5MS_DIRECT`** (`1` punch wave, **`4.71–6.01 ms`** direct encrypted UDP RTT; `32,924 B` TX / `226,908 B` RX during verification).
- **Direct HTTP `/api/health` (`n=10` sequential requests)**:
  - **Tailscale HTTP (`:9780`)**: min `197.89 ms` | p50 `203.18 ms` | mean `205.12 ms` | max `217.79 ms`
  - **Phantom Encrypted Tunnel (`:9789`)**: min **`7.41 ms`** | p50 **`10.55 ms`** | mean **`13.63 ms`** | max **`24.99 ms`** (**`19.26x` lower p50**, **`15.05x` lower mean**)
- **Real OpenSSH Execution (`BatchMode=yes`, `echo ... && hostname`)**:
  - **Tailscale SSH (`:22`)**: `1,248.28 ms`, `1,238.00 ms` (mean `1,243.14 ms`)
  - **Phantom SSH Tunnel (`127.0.0.1:2222`)**: **`233.41 ms`**, **`214.28 ms`** (mean **`223.85 ms`** — **`5.55x` faster SSH**)
- **Universal Edge Proxy (`127.0.0.1:9788` routing automatically via `active_peer_base = http://127.0.0.1:9789`)**:
  - `/chimera/`: **`103.19 ms`** (`66,770 B`, `TELEPATHIC_FOLD_ZDICT`) vs `v4.0` Tailscale `439.80 ms` (**`4.26x` faster**)
  - `/radar/`: **`86.87 ms`** (`83,336 B`, `TELEPATHIC_ZDICT`) vs `v4.0` Tailscale `486.53 ms` (**`5.60x` faster**)
  - `/tqouta/`: **`397.64 ms`** (`615,640 B`, `TELEPATHIC_FOLD_ZDICT`) vs `v4.0` Tailscale `1,207.14 ms` (**`3.04x` faster**)
  - `3` `PREFETCH-HIT-0RTT` local cache hits down to **`2.67 ms`**; aggregate wire **`765,746 B -> 166,624 B`** (**`-78.24%` wire**).

### Engine #2 — Ghost-PTY Persistent Detachable Shell
- Spawned interactive `/bin/bash -i` on Linux hub via transparent Windows proxy (`19.6 ms`).
- Executed `uname -srm && pwd && echo PTY_LIVE_OK`, detached, and reattached from `cursor=0` reading `364` bytes with full prompt + command output in **`28.68 ms`**, then closed cleanly.

### Engine #3 — Ghost-FS & RFC 4918 WebDAV Bridge
- `PROPFIND http://127.0.0.1:9788/dav/<repo>/` (`Depth: 1`): **`207 Multi-Status`**, `14` XML `<D:response>` entries in **`33.24 ms`**.
- `GET http://127.0.0.1:9788/dav/<repo>/pyproject.toml`: **`200 OK`**, `1,109 B`, `ETag: "7f6ad83d2342a34f"` in **`12.06 ms`**.
- `/api/fs/list` returned `13` entries in **`11.19 ms`**; `/api/fs/git-status` verified live across multiple workspace git repositories in **`33.61–74.18 ms`** (while safely reporting non-git status on deployment extracts lacking `.git`).

### Engine #4 — CHIMERA-MEDIC Forensic Triage & Playbook Healer
- **`investigate`** on a `446,480 B` production email sync log (`pattern=MAIL_FAIL_502`): `55` matches extracted in **`4.24 ms`** server (`14.25 ms` E2E), recommending `verify_email_log_tail` + `probe_services`.
- **Playbooks executed live via Windows proxy**:
  - `verify_email_log_tail`: inspected `7,935` lines (`2,042` `IMPORTED`, `55` historical `MAIL_FAIL_502`, last OK `IMPORTED 0 / 2 mail phu hop`) in **`24.17 ms`**.
  - `probe_services`: all `3` configured Linux apps `200 OK` (`chimera` **`1.78 ms`**, `radar` **`1.14 ms`**, `tqouta` **`6.95 ms`**).
  - `reindex_fts5`: verified **`1,949` files** (`8` updated, `1,941` unchanged, `33,392.0 KB` DB) in **`487.64 ms`**.

### Engine #5 — Drop-Portal & AI Context Teleporter
- **Drop-Portal**: Dropped test item on Windows proxy (`12.26 ms`), confirmed visible over Tailscale HTTPS `/api/portal/list` (`seen_over_tailscale_https: true`), and deleted cleanly (`deleted: true`).
- **AI Context Pack (`/api/context/pack`)**:
  - Error triage query: **`1,012 chars`** (`1` hit, `1` alert) assembled in **`1.67 ms`**.
  - Symbol query (`HyperWireReceiver`): **`2,345 chars`** (`4` code excerpts + Sentinel alert + `5 / 1,949` FTS5 hits in `1.31 ms`) assembled in **`2.72 ms`**.

## 4. Core `v5.0` Autopilot Telemetry Cycle (`POST /api/run?sync=1`)

- **Health Score:** **`100 / 100`** | **Bandit Genome:** `G2_LOSSY_ARMOR` (`reward: 7.429`)
- **GFNI Native Speedup:** **`85.04x`** (`188.55 ms` Python vs `2.22 ms` native Rust GFNI)
- **Wormhole IPC:** **`4.06 Gbps`** (`33.07 ms` vs `1.91 Gbps` TCP loopback)
- **5% WAN Drop Immunity:** **`29.22x`** (`27.326 Mbps` vs `0.935 Mbps` TCP)
- **1 MiB DNA Beam:** **`-95.36%` wire** (`62,400 B` / `1,048,576 B`, **`3.76x`** vs raw TCP)
- **Fluid Log Query (`1.70 MB` -> `14.4 KB`):** **`-99.15%` wire** (`9,084` hits, **`9.03x`** vs raw TCP)
- **Merkle 16-file Sync:** **`-96.84%` wire**, SHA-256 `verified_root_match: true` | **Immortal Blackout:** `survived_blackout: true`, `reconnects: 0`
