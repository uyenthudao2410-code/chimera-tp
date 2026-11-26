# CHIMERA-HYPER v17.0.0 — Personal Infrastructure Brain & Open Platform Substrate

> **1-Line Summary:** **CHIMERA-HYPER (`chimera-tp`)** unifies a **Windows Workstation** (`Rust GFNI/AVX-512F`, `NVIDIA GTX 1650`) and a **24/7 Linux Home Server** (`C11 AVX2`, `FUSE3`) over a **`~6 ms` authenticated P2P UDP tunnel (`PHANTOM-5MS`)** — and exposes an **NVIDIA/CUDA-style Open Platform Substrate (`CHIMERA-CONNECT` + 10 Hot-Loadable Cartridges)** so every project on the machine automatically discovers, attaches to, and accelerates on top of it while staying **Zero-Weight (`< 80 MB` RAM)**.

---

## 1. Architecture Overview (5-Layer Open Substrate)

```text
  [Legacy Apps: Radar, Tqouta]   [New Apps: chimera.connect()]   [AI Coding Agents]
               │                              │                          │
               └──────────────────────────────┴──────────────────────────┘
                                              ▼
 ┌─────────────────────────────────────────────────────────────────────────────────┐
 │  CHIMERA-CONNECT — Single-Anchor Auto-Discovery & Zero-Code Attach              │
 │  • Single Anchor : http://127.0.0.1:9780  (/.well-known/chimera.json, /v1/*)    │
 │  • Egress Proxy  : http://127.0.0.1:9781  (HTTP_PROXY / HTTPS_PROXY drop-in)    │
 │  • OS Beacons    : ~/.chimera/runtime.json  +  ~/.chimera/AGENTS_INFRA.md       │
 │  • Auto-Attach   : chimera_autoload.pth (<0.3ms) + chimera-tp link/init/run/mcp │
 └────────────────────────────────────────────┬────────────────────────────────────┘
                                              ▼
 ┌─────────────────────────────────────────────────────────────────────────────────┐
 │  11 HOT-LOADABLE SILICON CARTRIDGES (chimera-tp cartridge enable/disable)       │
 │  1. connect          7. vgpu_pareto       (GTX 1650 sharing + <50ms auto-yield) │
 │  2. egress_membrane  8. immortal_jobs     (SQLite WAL crash-resumable steps)    │
 │  3. pulse            9. browser_grid      (0 MB idle lazy shared Chromium CDP)  │
 │  4. hybrid_search   10. zygote_canary     (Single-thread pre-fork + Canary)     │
 │  5. blackbox        11. vault_sql         (Cross-node SQLite replica <1.4ms)    │
 │  6. diskless_secrets (+ *.chimera.local Host Reverse Proxy & Node/Python hooks) │
 └────────────────────────────────────────────┬────────────────────────────────────┘
                                              ▼
 ┌─────────────────────────────────────────────────────────────────────────────────┐
 │  CORE TRANSPORT, CRYPTO & COMPUTE FABRIC (v1–v15: Native Rust + C11 AVX2 SIMD)  │
 │  • PHANTOM-5MS Direct UDP Tunnel & PH9N 0-Copy Data-Plane (2.9 Gbps, LZ4 SIMD)  │
 │  • 10,000-bit Kanerva VSA AVX2 • FROST 2-of-3 • Live WASM Teleport • 0-KB Tarpit│
 │  • Virtual NVMe Fabric • 946 FPS UEP Stream • HostYieldGovernor • 3D Cortex UI  │
 └─────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Live Verified BEFORE vs AFTER Metrics (`win-desktop` ↔ `svhome`)

Measured live across **Windows (`Rust GFNI/AVX-512F`, GTX 1650, Python 3.11)** and **Linux `svhome` (`C11 AVX2`, Python 3.14)** connected over `PHANTOM_5MS_DIRECT` (`~6.1 ms` UDP RTT):

| Capability | Baseline / Legacy | CHIMERA-HYPER v17.0.0 (Live) | Measured Gain |
| :--- | :--- | :--- | :---: |
| **Platform Auto-Discovery** | `404` / manual ports | **`/.well-known/chimera.json` (`7.36 ms`)** + `runtime.json` + `chimera-mcp` | Zero-config attach |
| **Burst `16x` Concurrent HTTP GET** | `16` upstream calls (`573.57 ms`) | **`1` upstream call (`67.86 ms`)** via Singleflight (`:9781`) | **`-93.8%` load (`8.45x`)** |
| **Repeated HTTP GET (`10x` avg)** | `69.72 ms` | **`11.87 ms`** via Membrane TTL/ETag Cache | **`5.9x` faster** |
| **Transient `429` Rate-Limit** | `0 / 1` (app crashes) | **`1 / 1` (`100%` auto-rescued)** + `5xx` Wire-Cassette | Zero flaky drops |
| **Cross-Host Event Bus (`Pulse`)** | Polling / Redis (`>100 MB`) | **`win-desktop → svhome` `relayed_ok=True` (`< 3 MB` RAM)** | Zero-Redis pub/sub |
| **Namespaced Hybrid Search** | 3 separate internal APIs | **`2.16 ms`** (`BM25 FTS5 + 10,000-bit AVX2 VSA`) | Unified `/v1/search` |
| **VGPU Pareto + OpenAI Embeddings** | Idle GTX 1650 unshared | **Cold `12.54 ms` → Warm `0.06 ms` (`$0`)**, `< 50 ms` yield | **`209x` cache hit** |
| **Immortal-Job Crash Resume** | Re-run from step 1 | **Resumes at step `3/4`**, `dup_skipped=True` | **`-75%` wasted work** |
| **Shared Browser-Grid (CDP)** | `~1 GB` per Chrome instance | **`0.0 MB` RAM when idle**, lazy shared CDP + media block | On-demand zero-RAM |
| **Zygote Worker (`svhome` Linux)** | `python3` spawn `~60–150 ms` | **`2.791 ms` (`linux_prefork_cow`, 0 warnings)** | **`~20x–50x` faster** |
| **Cross-Node `Vault-SQL` Replica** | Remote SQLite queries / locks | **`-91.7%` compressed sync (`0 B` unchanged)** • **`1.34 ms` local read** | Zero lock errors |
| **`*.chimera.local` Host Mesh** | Manual ports / `ssh -L` | **`radar.chimera.local` & `tqouta.chimera.local` (`HTTP 200`, `55.5 ms`)** | `[ONLINE]` zero-code attach |
| **Native `PH9N` Tunnel & UI Stream** | `481 Mbps` / `3.6 MB/frame` | **`2,631.7 Mbps` (`5.47x`)** • **`1,164 FPS` (`-99.96%` wire)** | Bit-exact Rust = C11 |
| **24/7 Daemon RAM (`< 80 MB` cap)** | Heavy desktop suites | **`19.29 MB` (Win)** • **`75.87 MB` (`svhome`)** (`11` Cartridges) | **Zero-Weight PASS** |

Full detailed audit & remaining architectural recommendations: [docs/reports/CHIMERA_V17_PLATFORM_SUBSTRATE_AUDIT.md](docs/reports/CHIMERA_V17_PLATFORM_SUBSTRATE_AUDIT.md).

---

## 3. Quick Start — Connecting Projects in 30 Seconds

### Inspect Live Cluster Health (like `nvidia-smi`)
```bash
python -m chimera_tp smi
```

### Attach an Existing Project (Zero Code Changes)
```bash
# Install zero-code Python autoload hook once (<0.3ms overhead when unlinked)
python -m chimera_tp autoload install

# Link any existing repo once -> generates chimera.manifest.json & auto-attaches on future runs
python -m chimera_tp link /path/to/your_project --app my-app --port 8080

# Or wrap any ad-hoc command directly inside the substrate
python -m chimera_tp run --app my-tool -- python app.py
```

### Initialize a New Project (Zero Vendor Lock-In)
```bash
python -m chimera_tp init /path/to/new_project --app next-app
```
Use the zero-dependency SDK inside Python (automatically falls back cleanly if Chimera is not running):
```python
from chimera_tp.platform.client import connect, is_available

brain = connect(app="next-app")
resp = brain.fetch("https://api.example.com/data")               # Singleflight + Cache + 429 Shield
brain.pulse_publish("events.ready", {"ok": True})                # Cross-host Pub/Sub (<5ms)
hits = brain.search("query text", namespace="next-app")          # Hybrid BM25 + AVX2 VSA (<3ms)
emb  = brain.embed(["hello world"], dim=256)                     # OpenAI-compat VGPU/AVX2 ($0)
```

### Hot-Toggle Cartridges, Run Canary Judge & Connect AI Agents
```bash
python -m chimera_tp cartridge list
python -m chimera_tp cartridge disable browser_grid
python -m chimera_tp cartridge enable browser_grid

# Zero-downtime Canary Twin comparison (PROMOTE / ROLLBACK)
python -m chimera_tp canary http://127.0.0.1:8080 http://127.0.0.1:8081 --paths /health --samples 5

# Expose 8 live infrastructure tools to AI Coding Agents over stdio MCP
python -m chimera_tp mcp
```

---

## 4. Living 3D Command Center (`PHANTOM-CORTEX v17.0`)

Open **`http://127.0.0.1:9780`** (or the self-unpacking Kolmogorov capsule at **`http://127.0.0.1:9780/?packed=1`**, `~15 KB` wire):
* **Unified Real-Time Causal 3D Topology:** Visualizes `WIN-DESKTOP ⇄ Singularity + 10,000-bit VSA Halo ⇄ SVHOME Hub + 0-KB Tarpit` driven by live `/api/pulse` telemetry, linked apps, VGPU state, Egress hit rate, and real cross-host RPC arcs (`WASM Teleport`, `FROST 2-of-3`, `CHMC 3-Strike`, `VSA Blast/Reconstruct`).
* **`Tab` Key (`0-GPU` Tactical Mode):** Halts `requestAnimationFrame` (`0%` GPU) and renders a live SVG schematic for daily work.
* **`Ctrl+K` / `Ctrl+Space`:** Unified Spotlight search across the cluster.

---

## 5. Installation & Verification

```bash
# 1. Build native SIMD core (Rust on Windows / C11 AVX2 on Linux)
python scripts/build_native.py

# 2. Initialize server (Linux) and controller (Windows)
chimera-tp ops-init --node-name peer-linux --role server --bind 0.0.0.0:9780 --allow-root /path/to/dev
chimera-tp ops-init --node-name win-desktop --role controller --peer-name peer-linux --peer-ipv4 <PEER_TAILSCALE_IP> --bind 127.0.0.1:9780

# 3. Start 24/7 Zero-Weight daemon
chimera-tp daemon

# 4. Run full automated verification suite
python -m unittest discover -s tests -v
```

---

## 6. Repository Map & Documentation

* **`chimera_tp/platform/`** — `v16–v17` Open Platform Substrate (`discovery.py`, `client.py`, `autoload.py`, `mcp_server.py`, `egress_membrane.py`, `pulse_bus.py`, `hybrid_search.py`, `flight_recorder.py`, `vgpu_gateway.py`, `immortal_jobs.py`, `browser_grid.py`, `zygote_canary.py`, `substrate.py`).
* **`chimera_tp/`** — Core transport (`phantom_tunnel.py`, `v9_dataplane.py`, `gf256.py`), native SIMD bridge (`native.py`), sovereign & galactic engines (`v9_*`–`v12_*`), `host_governor.py`, `sentinel.py`, `medic.py`, `dashboard.py`, `universe_ui.py`.
* **`native/`** — Bit-identical Rust (`chimera_core`) & C11 (`chimera_core_c`) SIMD accelerators.
* **Docs & Plans:** [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) • [docs/EVALUATION.md](docs/EVALUATION.md) • [docs/MOONSHOT_VAULT.md](docs/MOONSHOT_VAULT.md) • [docs/ROADMAP.md](docs/ROADMAP.md) • [docs/reports/CHIMERA_V17_PLATFORM_SUBSTRATE_AUDIT.md](docs/reports/CHIMERA_V17_PLATFORM_SUBSTRATE_AUDIT.md).

---

## 7. Security & Privacy Guarantees

* **Zero Secret Leakage:** Egress proxy strips auth headers before recording `.cassette` error traces; `DisklessSecretVault` keeps secrets XOR-masked in RAM only (`0` plaintext bytes on disk) gated by loopback + per-boot token + app allowlist.
* **Loopback-First Exposure:** `EgressMembraneProxy` (`127.0.0.1:9781`) and `SharedBrowserGrid` CDP bind strictly to loopback; always run the control plane behind authenticated private overlays (Tailscale / WireGuard), never exposed publicly.
* **Containment:** File access, WebDAV, WASM sandboxes, and `CHIMERA-MEDIC` strictly enforce `allowed_query_roots` and reject path traversal or `.git` tampering.
