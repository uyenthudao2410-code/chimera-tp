# CHIMERA-HYPER v6.0.0 — APEX-SYNERGY

CHIMERA-HYPER (`chimera-tp`) is an autonomous, ultra-lightweight cross-platform transport, encrypted P2P tunnel, remote terminal/WebDAV workbench, forensic remediation, and multi-project AI orchestration fabric connecting Windows (`Rust GFNI/AVX2`) and Linux (`C11 AVX2`) nodes over overlay WANs (Tailscale/WireGuard) with zero desktop bloat.

Built on the strict **Zero-Weight Controller** invariant (the 24/7 Windows daemon uses **~14.5–33.1 MB RAM**, and the Linux hub uses **~45.4–46.3 MB RAM**, even during 25 MB encrypted backups), `v6.0 APEX-SYNERGY` fuses the local AI Relay (`Tqouta :12500/:12504`) and Autonomous Bounty Crew (`Radar :8787`) directly onto CHIMERA's `~5 ms` P2P backbone alongside 0-token pre-surgical code mapping, quota-aware throttling, solver burn-loop circuit breaking, 5-second WebDAV patch reviews, and isolated GF(256) `(2,3)` snapshots.

---

## What's New in `v6.0.0` (Six APEX-SYNERGY Capabilities)

1. **`PHANTOM-12550` Encrypted AI Relay Tunnel (`chimera_tp/phantom_tunnel.py`, `chimera_tp/dashboard.py`)**
   - Forwards `127.0.0.1:12550 -> peer:12500` over the `PHANTOM_5MS_DIRECT` (`4.28–6.15 ms` UDP RTT, `PH5E` AEAD) tunnel without colliding with local Windows relay ports (`12500`/`12504`).
   - Live Windows queries to peer `/v1/models` (`10` models): **`36.63 ms` min / `52.68–53.26 ms` mean** vs **`506.63 ms`** over Tailscale HTTPS (`9.5x` faster); `:9788/tqouta/api/status` serves compressed telemetry in **`24.52–39.99 ms`**.

2. **0-Token Pre-Surgical Scout (`ApexSynergyEngine.build_surgical_brief`)**
   - Performs an instant keyword + symbol scan over repository source files (skipping compiled artifacts, binaries, `.git`, `node_modules`) in **`71.89 ms`** (`102.82 ms` E2E) spending **`0` AI tokens**, generating `CHIMERA_SURGERY_PACK.md` (`< 7.2 KB`) with exact `file:line` excerpts, symbols, test paths, and recent git history.
   - Live repo test narrowed **`54` source files (`390,409 B`) -> `4,104 B` (`-98.95%` scan volume)** with top-5 ranked targets matching `4 / 4` solution patch files. Integrated via a fail-safe non-invasive hook into workspace brief generation.

3. **Redacted Quota Arbiter (`ApexSynergyEngine.evaluate_quota_arbiter`)**
   - Polls live relay fleet health & throughput (`6/6` enabled accounts, `16,755` requests, `11,889` auto-cut requests, **`76.62%` cached token ratio**) and cross-references bounty burn/ship telemetry (`17` clean ships / 30d), strictly stripping all email/label identifiers (`0` email leaks verified live).
   - Computes dynamic solver policy regimes (`TURBO`, `BALANCED`, `ECO_SURVIVAL`) and can persist atomic `CHIMERA_ARBITER_POLICY.json` hints.

4. **Token-Burn Circuit Breaker (`ApexSynergyEngine.scan_solver_burn_loops` & `trip_circuit_breaker`)**
   - Tails workspace solver logs (`agy_solver.log`), normalizes repeated tracebacks/errors (stripping timestamps, hex pointers, and line numbers), and triggers `BURN_LOOP_DETECTED` when identical failures repeat or logs bloat without diff output (`13` live workspaces scanned in **`10.85 ms`**).
   - Tripping the breaker writes `CHIMERA_CIRCUIT_BREAK.json`, drops a diagnostic alert into `Drop-Portal`, and optionally terminates stalled solver subprocesses scoped strictly to that workspace.

5. **5-Second Ready-Bounty WebDAV Review + Browser Index (`chimera_tp/edge_proxy.py`, `/api/synergy/bounties`)**
   - Fixed browser `GET /dav/` to render an interactive directory index (`200 OK`, `GHOSTFS-DAV-INDEX`) while preserving full RFC 4918 WebDAV (`PROPFIND 207`, `GET`/`PUT` with `ETag` CAS).
   - Surfaces workspaces holding ready `solution.patch` diffs with `+added / -removed` stats, clickable `/dav/.../solution.patch` links (`200 OK` in `54.16 ms`), and 1-click `Drop-Portal` 5-second mobile review publishing (`26.37 ms`).

6. **Isolated Holographic GF(256) `(K=2, N=3)` Vault (`ApexSynergyEngine.backup_apex_vault`, `medic` playbook `holo_snapshot_apex`)**
   - Packs Tqouta encrypted state files, Radar JSON state, and an atomic read-only SQLite `.backup()` snapshot of `radar.db` (`25,007,290 B -> 5,378,669 B` compressed, `8.00` bits/B shard entropy across 3 shards in **`1,926.59 ms`**).
   - Automatically isolates >2 MiB GF(256) shard operations into a short-lived worker subprocess so the 24/7 hub daemon RSS stays at **`46.28 MB` (`< 80 MB` Zero-Weight budget)**.

*(All `v5.0` PHANTOM-5MS, `v4.0` HyperOS & `v3.0` HyperGrid engines remain active: `:2222` SSH & `:9789` HTTP P2P tunnel, Ghost-PTY, Ghost-FS WebDAV, Medic, Drop-Portal, NAT Buster, Warp-Edge Proxy, Sentinel Watchdog, FTS5 Search, Holo Backup, Merkle 0-RTT Sync, Fluid `AQ02`, Telepathic Codec, Immortal IPv4+IPv6 RLNC, and Contextual UCB1.)*

---

## Verified Live Cross-Host Telemetry (Windows ↔ Linux)

Measured live between a Windows 11 Controller (`Intel Core i5-11400`, Rust GFNI) and an Ubuntu Linux Hub (`Intel Core i5-4300U`, C11 AVX2 `VPSHUFB`, Python 3.14.4):

| Capability | Baseline | CHIMERA-HYPER v6.0 Live | Gain / Budget |
| :--- | :--- | :--- | :--- |
| **Zero-Weight Daemon RSS** | `< 80 MB` cap per node | **`14.50–33.07 MB`** Win • **`45.43–46.28 MB`** Linux | PASS (`< 58%` budget post-25MB vault) |
| **`PHANTOM-12550` Relay Tunnel** | `506.63 ms` Tailscale HTTPS (`:12504`) | **`36.63 ms` min / `52.68–53.26 ms` mean** (`:12550/v1/models`) | **`9.5x` lower latency**, `0 MB` local relay RAM |
| **Edge `/tqouta/` Telemetry UI** | `506.63 ms` HTTPS direct | **`24.52–39.99 ms`** (`:9788/tqouta/api/status`) | **`12.7x–20.7x` faster** (`-78.24%` wire on full UI) |
| **0-Token Surgical Map** | Unbounded multi-turn AI file search | `54` files (`390.4 KB`) -> **`4.10 KB`** in **`71.89 ms`** | **`-98.95%`** pre-filter scan, `0` AI tokens |
| **Quota Arbiter + Redaction** | Manual inspection | `6/6` accounts OK, `76.62%` cache, `BALANCED` | **`0` emails leaked** (`@` assertion PASS) |
| **Burn-Loop & 5s PR Review** | Manual workspace SSH/grep | `13` workspaces scanned (`10.85 ms`); `6` ready PRs (`54.16 ms` DAV) | Automated loop guard + browser `/dav/` |
| **Apex GF(256) Vault (`2/3`)** | Plain local unencrypted copy | `7` targets + `radar.db` (`25.0 MB -> 5.38 MB`, `8.00 b/B`, `1.93 s`) | Subprocess-isolated (`+0.85 MB` daemon delta) |
| **Core `PHANTOM-5MS` (`v5.0`)** | `203.18 ms` HTTP / `1,243 ms` SSH | HTTP p50 **`10.55 ms`** (`19.26x`) • SSH **`214–233 ms`** (`5.55x`) | Direct UDP **`4.28–6.15 ms`** RTT |

See [docs/EVALUATION.md](docs/EVALUATION.md) and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for full benchmark tables and protocol internals.

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

### 2. Run 24/7 Daemons & `v6.0` CLI Subcommands
```bash
# Start 24/7 Cockpit + PHANTOM Tunnel (:2222 SSH, :9789 HTTP, :12550 Relay) + LocalEdgeProxy & WebDAV (:9788)
chimera-tp daemon

# Check redacted Tqouta/Radar Synergy status & throttling regime
chimera-tp synergy status --peer-http http://127.0.0.1:9780

# Generate 0-token pre-surgical brief for a solver workspace
chimera-tp synergy brief --workspace-dir /path/to/workspaces/issue_1 --title "Bug summary" --inject

# List ready PR patches (with /dav/ URLs), scan burn loops, or trigger GF(256) vault backup
chimera-tp synergy bounties --peer-http http://127.0.0.1:9780
chimera-tp synergy burn-scan --peer-http http://127.0.0.1:9780
chimera-tp synergy vault-backup --peer-http http://127.0.0.1:9780
```

---

## Automated Tests

```bash
python -m unittest discover -s tests -v
```

- **Windows (`Rust GFNI` + Python 3.11):** **48 / 48 PASS in `63.517s`** (`test_chimera`, `test_hyper`, `test_v2_autopilot`, `test_v3_hypergrid`, `test_v4_hyperos`, `test_v5_phantom`, `test_v6_synergy`).
- **Linux (`C11 AVX2` + Python 3.14):** **48 / 48 PASS in `41.295s`** (`test_chimera`, `test_hyper`, `test_v2_autopilot`, `test_v3_hypergrid`, `test_v4_hyperos`, `test_v5_phantom`, `test_v6_synergy`).

---

## Security & Scope Disclaimer

`chimera-tp` enforces multiple defense-in-depth invariants:
- **Redacted Telemetry**: `ApexSynergyEngine` strips `email` and personal `label` fields from relay responses (`test_quota_arbiter_regimes_and_email_redaction` asserts zero `@` leaks).
- **PHANTOM-5MS (`PH5E`)**: Every multiplexed UDP frame uses per-packet `BLAKE2b` keystream obfuscation and a truncated `BLAKE2s-128` MAC; server TCP dialing is restricted to `phantom_allowed_ports` on loopback (`127.0.0.1`).
- **Containment & Safe Remediation**: Ghost-FS, WebDAV `/dav/`, surgical brief generation, circuit-breaker writes, and Medic playbooks enforce path containment inside `allowed_query_roots`, block `.git` writes, support `ETag` CAS, isolate multi-MB GF(256) vault compression via worker subprocesses with atomic SQLite `.backup()`, and accept only strictly allowlisted Medic playbooks. Always expose inter-node HTTP strictly over localhost or authenticated Tailscale/WireGuard overlays.
