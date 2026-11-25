# Architecture — CHIMERA-HYPER v8.0.0 SINGULARITY

```
+------------------------------------------------------------------------------------+
|              CHIMERA-HYPER v8.0 SINGULARITY Control & Frontier Plane               |
|  Win (:9780 Cockpit | :9788 Edge + /dav/ HTML/DAV | :2222 SSH | :9789 | :12550 v1) |
|  Zero-Weight Guard (33.04 MB Win / 47.14 MB Linux) | Transparent Peer Routing      |
+----+--------------------+--------------------+--------------------+----------------+
     |                    |                    |                    |
     v                    v                    v                    v
+-------------+    +---------------+    +--------------+    +------------------------+
| SINGULARITY |    | OMEGA v7.0    |    | OMEGA v7.0   |    | APEX-SYNERGY & HyperOS |
| TimeWarp,   |    | X25519+MLWE,  |    | Ghost-Block, |    | Ghost-PTY/FS, Medic,   |
| MerkleCRDT, |    | Bond, Mimic,  |    | K=3/5, SW0,  |    | Drop-Portal, Tqouta/   |
| AirGap FSK, |    | Recode, Gene, |    | WASM AQ03,   |    | Radar :12550 & K=2/N=3 |
| IT-PIR,     |    | Chaff-as-RLNC |    | Rem-RAM, UEP |    | Subprocess GF256 Vault |
| DualVault,  |    +-------+-------+    +------+-------+    +-----------+------------+
| Kolmogorov, |            |                   |                        |
| Swarm-3Node |            +-------------------+------------------------+
+------+------+                                |
       |                                       v
+------------------------------------------------------------------------------------+
|                  Bit-Identical Cross-Platform Silicon Core (v8.0)                  |
|   Windows: Rust cdylib (GFNI/AVX2/AVX-512F + PIR XOR, Q15 FSK, ChaCha20, PPM, SHM) |
|   Linux:   C11 .so     (AVX2 VPSHUFB + AVX2 PIR XOR, Q15 FSK, ChaCha20, /dev/shm)  |
+------------------------------------------------------------------------------------+
```

## 0. `v8.0.0 SINGULARITY` Frontier Modules & Honest Guardrails
- **Native SIMD Extensions (`native/chimera_core/src/lib.rs`, `native/chimera_core_c/chimera_core.c`, `chimera_tp/native.py`)**: Exports bit-identical `chimera_pir_xor_query` (`10.03 GB/s` 2-server IT-PIR XOR accumulator) and integer Q15 quadrature correlator `chimera_fsk_demod_bits` (`18.0/19.2 kHz` orthogonal FSK at `48 kHz` / `40 samples per bit`) alongside all v7.0/v1.0 primitives.
- **Time-Warp & Offline CRDT (`chimera_tp/singularity_time_crdt.py`)**: `SpeculativeTimeWarpEngine` (Markov bigram prefetch + SHA-256 stale invalidation + automatic anti-waste throttling `< 25%` hit rate) and `MerkleCrdtShadowTwin` (`HLC` + per-line tombstones + conflict audit log + `BLAKE2s` Merkle root verified across 20 shuffled merge permutations).
- **Air-Gap Fountain, IT-PIR & Plausible Deniability (`chimera_tp/singularity_airgap_crypto.py`)**: `AirGapFountainBridge` (unidirectional 1,200 bps ultrasonic FSK + 2D grid GF(256) Fountain under `6 dB` AWGN and `30–33%` frame erasures), `PrivateInfoRetrievalEngine` (live cross-host 2-server 1 MiB IT-PIR requiring only `1,536 B` wire), and `PlausibleDeniabilityVault` (fixed 16 KB Cauchy `(2,3)` container inspected across 10-vs-10 Shannon/Chi2/autocorrelation forensic checks). Note: `/api/singularity/pir-shard` allocates its `1 MiB` slab lazily only on first PIR query so idle daemon RSS stays unaffected.
- **Kolmogorov Grammar & 3-Node Swarm (`chimera_tp/singularity_kolmogorov_swarm.py`, `singularity_bench.py`)**: `KolmogorovGrammarCodec` (schema extraction + columnar delta-zigzag/dictionary + native Order-2 PPM with strict bit-exactness verification & `+1 B` random fallback) and `SwarmAnycastMesh` (3-socket UDP 2-hop zero-plaintext GF(256) recoding relay + `K=3` standby rehydration), exposed via `v8.0 SINGULARITY Lab`, `/api/singularity/*`, and `chimera-tp singularity`.

## 0b. `v7.0.0 OMEGA-FABRIC` Protocol & Systems Modules
- **Silicon Cryptographic & Coding Primitives (`native/chimera_core`, `native/chimera_core_c`, `chimera_tp/native.py`)**: Exports bit-exact RFC 8439 `chimera_chacha20_xor`, zero-decode `chimera_gf256_recode`, GF(256) `chimera_slepian_syndrome`, and Order-2 context-mixing arithmetic codec `chimera_ppm_compress`/`chimera_ppm_decompress` across Windows Rust and Linux C11 AVX2.
- **OMEGA Transport (`chimera_tp/omega_transport.py`)**: `SiliconDataPlane` + `VirtualNicBridge` (X25519 + IPv4 framing + honest OS TUN probe), `MultiIspBondingEngine` (0 ms blackout failover), `PolymorphicMimicLayer` (QUIC/WebRTC mimicry), `RlncRecodingRelay`, `HybridPqKem` + `QuantumChaffShield` (Module-LWE + X25519 + chaotic port hopping + chaff-as-RLNC), and `GeneticWireEngine` (12-byte `CHG7` evolving wire DNA).
- **OMEGA Storage (`chimera_tp/omega_storage.py`)**: `GhostBlockEngine` (4 KB incremental patches + OS WinFsp/FUSE3 probe), `RegeneratingMeshVault` (`K=3, N=5` Cauchy shard healing without plaintext decode), `SlepianWolfSync` (0-RTT blind syndrome delta with Berlekamp-Massey + Chien search), and `ParasiticDeadDropMesh` (hourly Lehmer carrier rotation across public channels).
- **OMEGA Compute & Display (`chimera_tp/omega_compute.py`, `chimera_tp/omega_bench.py`)**: Sandboxed `WasmActivePipe` WebAssembly 1.0 interpreter (`build_wasm_byte_counter_module`, strict fuel + bounds enforcement), bounded `RemoteRamStore`/`RemoteRamPool` for 4 KB compressed page swap/fault over HTTP/PHANTOM, `NeuralPpmCodec` (shared prior tokenization + LZ residual + native Order-2 arithmetic range coding), `UepDisplayStream` (3x RLNC protection for crisp text/cursor tiles), plus `/api/omega/*` endpoints and `chimera-tp omega`.

## 1. Unified Fusion Engine (`chimera_tp/apex_synergy.py`)
- **`PHANTOM-12550` Relay Tunnel**: Extends `PhantomTunnelClient` forwards on the Windows controller with `{phantom_tquota_port: 12500}` (`127.0.0.1:12550 -> 127.0.0.1:12500` on the hub, authorized in `phantom_allowed_ports`), avoiding local Windows port collisions while sharing the hub's warm `Prompt Cache` and account `Pool`.
- **0-Token Pre-Surgical Brief (`build_surgical_brief`)**: Contained within `allowed_query_roots`, ignores build/compiled artifact dirs (`artifacts`, `cache`, `out`, `typechain-types`, `node_modules`, `.git`), ranks source files using identifier/backtick weighted scoring, extracts `±6` line context excerpts + symbol declarations + test files + `git log -n 5`, caps output `< 7.2 KB` in `CHIMERA_SURGERY_PACK.md`, and idempotently injects into `AGENT_SOLVER_BRIEF.md`.
- **Redacted Quota Arbiter (`evaluate_quota_arbiter`)**: Aggregates Tqouta `/api/dashboard` fleet health (`accounts_ok`, `needs_reauth`, `unknown_pool_count`, `cache_hit_pct`, `dualLayerSlo`) with zero email/label disclosure, cross-checking Radar `/api/overview` to emit dynamic solver throttling regimes (`TURBO`, `BALANCED`, `ECO_SURVIVAL`).
- **Burn-Loop Detector & Circuit Breaker (`scan_solver_burn_loops`, `trip_circuit_breaker`)**: Normalizes stderr/log failure signatures (stripping timestamps, line numbers, and hex addresses) across solver workspaces; flags loops when repeated errors exceed threshold or logs bloat without a diff, writing `CHIMERA_CIRCUIT_BREAK.json` and alerting `Drop-Portal`.
- **5-Second Ready-Bounty Review & GF(256) Subprocess Vault**: Parses diff stats across workspaces holding `solution.patch` for instant `/dav/.../solution.patch` review + Drop publishing, and executes >2 MiB GF(256) `(K=2, N=3)` vaults (including read-only SQLite `.backup()` of `radar.db`) inside an isolated short-lived worker subprocess so daemon RSS remains unaffected.

## 2. Interactive Browser & RFC 4918 WebDAV (`chimera_tp/edge_proxy.py`, `chimera_tp/ghost_fs.py`)
- `LocalEdgeProxy` (`/dav/...`) handles browser `GET`/`HEAD` directory browsing (`200 text/html` index + `302` trailing-slash normalization) alongside machine RFC 4918 `OPTIONS`, `PROPFIND` (`207 Multi-Status` XML), `GET`, `HEAD`, and `PUT` (`If-Match` ETag compare-and-swap, `.git` write denial) transparently over `active_edge_peer_base()`.

## 3. Control-Plane Endpoints (`chimera_tp/dashboard.py`, `chimera_tp/cli.py`, `chimera_tp/medic.py`)
- Exposes `/api/synergy/status`, `/api/synergy/bounties`, `/api/synergy/burn-scan`, `/api/synergy/surgical-brief`, `/api/synergy/circuit-break`, `/api/synergy/bounty-drop`, `/api/synergy/vault-backup`, `/api/synergy/arbiter`, the `Radar + Tqouta Synergy` Workbench tab, CLI `chimera-tp synergy ...`, and `MedicEngine` playbook `holo_snapshot_apex`.
- Controller daemons transparently proxy `/api/synergy/*`, `/api/pty/*`, `/api/fs/*`, `/api/medic/*`, and `/api/portal/*` across the active P2P tunnel (falling back safely to overlay HTTP if unpunched).

---

## Inherited Foundations (`v5.0` PHANTOM-5MS, `v4.0` HyperOS & `v3.0` HyperGrid)
- **Ghost-PTY (`ghost_pty.py`)**: `256 KiB` cursor-indexed POSIX PTY sessions (`19.6 ms` spawn, `28.68 ms` reattach).
- **NAT Buster (`nat_buster.py`)**, **Sentinel (`sentinel.py`)**, **FTS5 Code Search (`code_search.py`)**, **Holo GF(256) Backup (`holo_backup.py`)**, **Drop-Portal & Context Pack (`drop_portal.py`)**, **Merkle Sync (`merkle_sync.py`)**, **Fluid `AQ02` (`active_pipe.py`)**, and **Immortal IPv4+IPv6 RLNC (`hyper_wire.py`)**.
