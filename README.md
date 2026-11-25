# CHIMERA-HYPER v5.0.0 — PHANTOM-5MS

CHIMERA-HYPER (`chimera-tp`) is an autonomous, ultra-lightweight cross-platform transport, encrypted P2P tunnel, remote terminal/WebDAV workbench, forensic remediation, and telemetry fabric connecting Windows (`Rust GFNI/AVX2`) and Linux (`C11 AVX2`) nodes over overlay WANs (Tailscale/WireGuard) with zero desktop bloat.

Built on the strict **Zero-Weight Controller** invariant (the 24/7 Windows daemon running the Cockpit, Local Edge Proxy, WebDAV bridge, and encrypted P2P tunnel uses only **~21–32 MB RAM** and ~0% idle CPU), `v5.0 PHANTOM-5MS` promotes the `~5 ms` NAT-punched UDP socket from a one-off probe into a permanent authenticated TCP multi-port tunnel while adding browser-native persistent PTY shells, zero-RAM WebDAV repository mounting, allowlisted log/service remediation, and `< 8 KB` AI context bundling.

---

## What's New in `v5.0.0` (Five PHANTOM-5MS Zero-Weight Engines)

1. **PHANTOM-5MS Persistent Encrypted P2P Tunnel (`chimera_tp/phantom_tunnel.py`)**
   - Converts the Birthday-Paradox STUN hole punch into a persistent keepalive-driven bidirectional TCP-over-UDP multiplexor (`PH5E` wire framing: per-packet `BLAKE2b` keystream + truncated `BLAKE2s-128` MAC).
   - Automatically falls back to Tailscale UDP (`:9710`) if symmetric/carrier NAT blocks direct UDP, and automatically feeds `LocalEdgeProxy` (`active_peer_base`) via `peer_http_resolver`.
   - Forwards **`127.0.0.1:2222 -> peer:22` (SSH)** and **`127.0.0.1:9789 -> peer:9780` (HTTP)** at **`4.71–6.01 ms`** direct UDP RTT:
     - HTTP `/api/health` (`n=10`): **`7.41 ms` min / `10.55 ms` p50 / `13.63 ms` mean** vs **`203.18 ms` p50** over Tailscale (**`19.26x` faster p50**, **`15.05x` faster mean**).
     - Real `ssh -p 2222`: **`214.28–233.41 ms`** vs **`1,238.00–1,248.28 ms`** over Tailscale (**`5.55x` faster**).
     - Edge Proxy `:9788`: `/chimera/` **`103.19 ms`** (`4.26x` vs v4), `/radar/` **`86.87 ms`** (`5.60x`), `/tqouta/` **`397.64 ms`** (`3.04x`), **`2.67 ms`** `PREFETCH-HIT-0RTT` cache hits, and **`-78.24%`** wire savings (`765.7 KB -> 166.6 KB`).

2. **Ghost-PTY Persistent Detachable Shell (`chimera_tp/ghost_pty.py`)**
   - Spawns hub interactive shells (`pty.openpty()` on Linux with window-resize `TIOCSWINSZ`, pipe fallback on Windows) backed by a **`256 KiB`** circular byte buffer and `threading.Condition` long-poll cursor synchronization (`/api/pty/create`, `write`, `read`, `resize`, `close`, `list`).
   - Browser tabs or CLI clients can disconnect and reattach at any byte cursor without losing terminal output (`create` in **`19.6 ms`**, `cursor=0` reattach of `364 B` in **`28.68 ms`**).

3. **Ghost-FS & RFC 4918 WebDAV Bridge (`chimera_tp/ghost_fs.py`, `chimera_tp/edge_proxy.py`)**
   - Exposes `allowed_query_roots` over `/api/fs/*` (`list`, `stat`, `read`, `write`, `git-status`) AND RFC 4918 WebDAV at `http://127.0.0.1:9788/dav/...` (`OPTIONS`, `PROPFIND`, `GET`, `HEAD`, `PUT`) for native Windows Explorer/editor mapping at `0 MB` local sync cost.
   - Enforces path traversal blocking, `.git` write denial, and HTTP `If-Match` ETag conflict checking (`409 Conflict` / `412 Precondition Failed`). Live verified: `PROPFIND 207` (`14` entries, **`33.24 ms`**), `GET` with ETag (`1,109 B`, **`12.06 ms`**), Git status (`33.61–74.18 ms`).

4. **CHIMERA-MEDIC Forensic Triage & Playbook Healer (`chimera_tp/medic.py`)**
   - `/api/medic/investigate` extracts bounded tail match snippets and ranks safe playbooks (`4.24 ms` server / `14.25 ms` E2E on a `446 KB` production email log with `55` matched lines).
   - Strictly allowlisted playbooks (`verify_email_log_tail` **`24.17 ms`**, `probe_services` **`1.14–6.95 ms`**, `prune_git_remote`, `holo_snapshot_configs`, `rotate_large_log` with mandatory pre-heal GF(256) `(2,3)` backup, and `reindex_fts5` indexing `1,949` files in **`487.64 ms`**).

5. **Drop-Portal & AI Context Teleporter (`chimera_tp/drop_portal.py`)**
   - **Drop-Portal**: TTL-expiring ephemeral text/file store (`TelepathicCodec`-compressed `.chdrop` payloads, default `600 s`) synced transparently across nodes (`12.26 ms` drop verified live across Tailscale HTTPS).
   - **AI Context Pack (`/api/context/pack`)**: Fuses FTS5 BM25 hits (`5 / 1,949` files in `1.31 ms`), `±5/+8` disk excerpts, Sentinel alerts, and recent `git log` into a copy-ready `< 8 KB` Markdown packet in **`1.67–2.72 ms`**.

*(All `v4.0` HyperOS & `v3.0` HyperGrid engines remain active: STUN NAT Buster, Warp-Edge Proxy, Sentinel Watchdog, SQLite FTS5 Search, Holo GF(256) `(2,3)` Backup, Merkle 0-RTT Sync, Fluid `AQ02`, Telepathic Codec, Immortal IPv4+IPv6 RLNC, and Contextual UCB1.)*

---

## Verified Live Cross-Host Telemetry (Windows ↔ Linux)

Measured live between a Windows 11 Controller (`Intel Core i5-11400`, Rust GFNI) and an Ubuntu Linux Hub (`Intel Core i5-4300U`, C11 AVX2 `VPSHUFB`, Python 3.14.4):

| Capability | Baseline (`v4.0` Tailscale / Raw) | CHIMERA-HYPER v5.0 Live (`PHANTOM-5MS`) | Gain |
| :--- | :--- | :--- | :--- |
| **Zero-Weight Daemon RSS** | Budget `< 80 MB` | **`21.19–26.01 MB`** Win • **`44.38–58.36 MB`** Linux | Well under `80 MB` cap |
| **HTTP `/api/health` p50** | `203.18 ms` (mean `205.12 ms`) | **`10.55 ms`** (`7.41 ms` min, `13.63 ms` mean) | **`19.26x` lower p50** |
| **Real SSH Command (`BatchMode`)** | `1,238.00–1,248.28 ms` (`:22`) | **`214.28–233.41 ms`** (via `127.0.0.1:2222`) | **`5.55x` faster SSH** |
| **Edge Proxy UIs (`:9788`)** | `/chimera/` `439.8 ms` • `/radar/` `486.5 ms` • `/tqouta/` `1,207.1 ms` | **`103.19 ms`** • **`86.87 ms`** • **`397.64 ms`** (`-78.24%` wire, **`2.67 ms`** 0-RTT hit) | **`3.04x–5.60x` faster UIs** |
| **Ghost-PTY Shell** | New SSH per command | **`19.6 ms`** create • **`28.68 ms`** `cursor=0` reattach (`364 B`) | Survives network drops |
| **Ghost-FS + WebDAV (`/dav/`)** | Full repo clone / SFTP sync | `PROPFIND 207` **`33.24 ms`** • `GET` ETag **`12.06 ms`** • Git **`33.61 ms`** | Zero-RAM remote editing |
| **CHIMERA-MEDIC (`heal`)** | Manual SSH grep & checks | Log triage **`4.24 ms`** • 3/3 probes **`1.14–6.95 ms`** • FTS5 **`487.64 ms`** | Strict allowlisted heals |
| **Drop-Portal + AI Context** | Slow manual copy/paste | Drop **`12.26 ms`** • `< 8 KB` AI Context Pack **`1.67–2.72 ms`** | Instant AI bug packets |
| **Autopilot Core Cycle** | Unoptimized WAN | `100/100` health • GFNI **`85.04x`** • WAN 5% **`29.22x`** • Query **`-99.15%`** | `G2_LOSSY_ARMOR` |

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

### 2. Run 24/7 Daemons & `v5.0` CLI Subcommands
```bash
# Start 24/7 Mission-Control Cockpit + Phantom 5ms Tunnel + LocalEdgeProxy + WebDAV
chimera-tp daemon

# Stand-alone Phantom Tunnel or live SSH over punched P2P
chimera-tp phantom connect --peer-http http://<PEER_IP>:9780
ssh -p 2222 <USER>@127.0.0.1

# Stand-alone Windows Local Edge Proxy + /dav/ WebDAV bridge
chimera-tp edge-proxy --listen 127.0.0.1:9788 --peer-http http://127.0.0.1:9789

# Ghost-PTY remote interactive shell commands
chimera-tp pty exec "uname -a && uptime" --peer-http http://127.0.0.1:9780

# Ghost-FS remote browse / git status without cloning
chimera-tp fs ls . --peer-http http://127.0.0.1:9780
chimera-tp fs git-status my-repo --peer-http http://127.0.0.1:9780

# CHIMERA-MEDIC forensic triage & safe allowlisted heal
chimera-tp medic investigate --file /path/to/app.log --pattern ERROR --peer-http http://127.0.0.1:9780
chimera-tp medic heal probe_services --peer-http http://127.0.0.1:9780

# Drop-Portal & AI Context Teleporter
chimera-tp drop put --title note --text "quick payload" --peer-http http://127.0.0.1:9780
chimera-tp context-pack "HyperWireReceiver" --peer-http http://127.0.0.1:9780
```

---

## Automated Tests

```bash
python -m unittest discover -s tests -v
```

- **Windows (`Rust GFNI` + Python 3.11):** **42 / 42 PASS in `56.351s`** (`test_chimera`, `test_hyper`, `test_v2_autopilot`, `test_v3_hypergrid`, `test_v4_hyperos`, `test_v5_phantom`).
- **Linux (`C11 AVX2` + Python 3.14):** **42 / 42 PASS in `34.539s`** (`test_chimera`, `test_hyper`, `test_v2_autopilot`, `test_v3_hypergrid`, `test_v4_hyperos`, `test_v5_phantom`).

---

## Security & Scope Disclaimer

`chimera-tp` enforces multiple defense-in-depth invariants:
- **PHANTOM-5MS (`PH5E`)**: Every multiplexed UDP frame uses per-packet `BLAKE2b` keystream obfuscation and a truncated `BLAKE2s-128` MAC verified before accept/forward; server TCP dialing is restricted to `phantom_allowed_ports` on loopback (`127.0.0.1`).
- **EdgeGateway & WebDAV**: Strict loopback SSRF allowlisting (`127.0.0.1`/`localhost`) on `/api/edge/fetch`; RFC 4918 WebDAV `/dav/` and `/api/fs/*` enforce path containment inside `allowed_query_roots`, deny writes into `.git`, and support `If-Match` / `expected_etag` compare-and-swap conflict detection.
- **Medic & Storage**: `MedicEngine` permits ONLY explicit allowlisted playbooks (`verify_email_log_tail`, `probe_services`, `prune_git_remote`, `holo_snapshot_configs`, `rotate_large_log`, `reindex_fts5`), enforces path containment, takes mandatory pre-heal GF(256) `(2,3)` snapshots before log rotation, runs `sqlite3` analytics read-only (`?mode=ro`), and exposes HTTP traffic strictly on localhost or authenticated Tailscale/WireGuard overlays.
