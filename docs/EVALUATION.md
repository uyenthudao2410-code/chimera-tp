# Evaluation — CHIMERA-HYPER v6.0.0 APEX-SYNERGY Live Cluster Results

All cross-host telemetry below was measured live across the two-node cluster (`Windows 11 i5-11400 Rust GFNI` ↔ `Ubuntu Linux i5-4300U C11 AVX2, Python 3.14.4`) running `CHIMERA-HYPER v6.0.0` 24/7 daemons with `PHANTOM_5MS_DIRECT` (`4.28–6.15 ms` UDP RTT).

## 1. Automated Verification Suites (Verified After Final Edits)

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
