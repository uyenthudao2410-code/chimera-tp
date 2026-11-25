# CHIMERA-HYPER v7.0.0 — OMEGA-FABRIC

CHIMERA-HYPER (`chimera-tp`) is an autonomous, ultra-lightweight cross-platform transport, cryptographic coding fabric, encrypted P2P tunnel, remote terminal/WebDAV workbench, forensic remediation, and multi-project AI orchestration engine connecting Windows (`Rust GFNI/AVX-512F`) and Linux (`C11 AVX2`) nodes over overlay WANs (Tailscale/WireGuard) with zero desktop bloat.

Built on the strict **Zero-Weight Controller** invariant (the 24/7 Windows daemon runs at **32.79 MB RAM** and the Linux hub at **44.40 MB RAM**, well below the `80 MB` cap), `v7.0 OMEGA-FABRIC` implements **all 14 protocol & systems breakthroughs** from [docs/MOONSHOT_VAULT.md](docs/MOONSHOT_VAULT.md) on top of bit-identical Rust & C11 silicon primitives (`chimera_chacha20_xor`, `chimera_gf256_recode`, `chimera_slepian_syndrome`, `chimera_ppm_compress` / `chimera_ppm_decompress`) and fuses with the `v6.0 APEX-SYNERGY` & `v5.0 PHANTOM-5MS` stack (`~5.8 ms` direct P2P UDP tunnel).

---

## What's New in `v7.0.0 OMEGA-FABRIC` (14 Core Protocol Breakthroughs)

1. **Silicon X25519 + ChaCha20 Virtual NIC (`omega_transport.py`, `native/chimera_core*`)** — Bit-exact RFC 8439 ChaCha20 XOR stream cipher across Rust/C11 with Curve25519 key agreement, IPv4 framing, and honest unprivileged OS TUN capability probes.
2. **True Multi-ISP RLNC Bonding (`MultiIspBondingEngine`)** — Spreads GF(256) equations across parallel links with **`0 ms` failover** across sudden mid-stream lane blackout (`5` drops survived in `2.25 ms`).
3. **Polymorphic QUIC / WebRTC DPI Mimicry (`PolymorphicMimicLayer`)** — Auto-morphs encapsulated frames into HTTP/3 QUIC or WebRTC SRTP headers when raw/QUIC UDP paths suffer DPI drops (`270 B` wire frame).
4. **Multi-Hop RLNC Recoding-in-Flight (`RlncRecodingRelay`, `chimera_gf256_recode`)** — Recombines coded GF(256) packets natively at intermediate hops in **`0.962 ms`** with zero relay plaintext decoding.
5. **Ghost-Block 4 KB Sub-File Patching (`GhostBlockEngine`)** — Transmits only dirty 4 KB blocks (`26,624 B -> 95 B` delta, **`-99.64%`**) alongside WinFsp/FUSE3 mount capability probing.
6. **Cauchy `(K=3, N=5)` Self-Healing Regenerating Mesh (`RegeneratingMeshVault`)** — Repairs missing node shards from any `3` live peers in **`0.05 ms`** (`5.80 b/B` shard entropy) without materializing plaintext at the repair site.
7. **Sandboxed WebAssembly 1.0 Active-Pipe (`WasmActivePipe`, `AQ03`)** — Ships **`109 B`** `.wasm` bytecode (`274,812` fuel-metered ops) to execute directly beside remote logs (`16,800 B` scanned locally on peer in **`0.72–251.14 ms`** with zero host/FS/network syscalls).
8. **0-RTT Blind Delta Sync via Slepian-Wolf Syndromes (`SlepianWolfSync`)** — Reconstructs scattered edits bit-exactly in **1-way `0-RTT`** via Berlekamp-Massey + Chien search over GF(256) linear syndromes (`-72.60%` wire local / `-56.61%` remote in `1.47 ms`).
9. **Serverless `$0` Parasitic Dead-Drop Mesh (`ParasiticDeadDropMesh`)** — Scatters GF(256) shards across `5` independent public carriers with hourly Lehmer permutation (`survives 2/5 blocked channels` in `0.37 ms`).
10. **Compressed 4 KB Remote RAM Pool (`RemoteRamPool`, `RemoteRamStore`)** — Swaps & faults compressed 4 KB RAM slabs over the `5 ms` PHANTOM HTTP tunnel (`16,384 B -> 843 B`, **`-94.85%`** RAM footprint in `REMOTE_HTTP` mode).
11. **Hybrid Post-Quantum KEM + Chaotic Port-Hopping + Chaff-as-RLNC (`QuantumChaffShield`)** — Pairs Module-LWE + X25519 (`672 B` ciphertext) with synchronized port rotation and adaptive chaff packets that carry real GF(256) repair equations (`3/12` drops repaired).
12. **Bit-Exact Order-2 Context-Mixing Arithmetic Range Codec (`NeuralPpmCodec`)** — Shared-prior tokenizer + LZ residual + native Rust/C11 Order-2 range coder (`16,559 B` raw / `650 B` `zlib-9` -> **`608 B`**, **`-6.46%` smaller than `zlib-9`**).
13. **Zero-Freeze `UEP-RLNC` Remote Display Stream (`UepDisplayStream`)** — Applies `3x` unequal GF(256) redundancy to crisp text/cursor tiles (`25/25` crisp survival under `15%` packet loss vs `11/25` plain).
14. **Self-Mutating Genetic Wire DNA (`GeneticWireEngine`)** — Evolves MTU, FEC ratio, pacing, window, and mimicry chromosomes into a **`12 B` `CHG7` ACK header** (`0.01 -> 87.007` fitness over `14` generations).

*(Includes the complete `v6.0 APEX-SYNERGY`, `v5.0 PHANTOM-5MS`, `v4.0 HyperOS`, and `v3.0 HyperGrid` stacks.)*

---

## Verified Live Cross-Host Telemetry (Windows ↔ Linux)

Measured live between a Windows Controller (`Rust GFNI/AVX-512F`, Python 3.11) and a Linux Hub (`C11 AVX2 VPSHUFB`, Python 3.14.4) connected via `PHANTOM_5MS_DIRECT` (`5.8 ms` UDP RTT):

| Check / Capability | Baseline | CHIMERA-HYPER v7.0.0 Live | Result |
| :--- | :--- | :--- | :---: |
| **Zero-Weight 24/7 Daemon RSS** | `< 80 MB` cap | **`32.79 MB`** Win (`41.0%`) • **`44.40 MB`** Linux (`55.5%`) | PASS |
| **Rust ↔ C11 Bit-Exact Parity** | Cross-ISA drift risk | **`4/4` identical SHA-256** (`chacha20`, `recode`, `slepian`, `ppm`) | PASS |
| **14-Idea OMEGA Live Matrix** | Sequential baselines | **`14 / 14` verified** in **`469.81 ms`** (`REMOTE_HTTP` enabled) | PASS |
| **Remote `.wasm` & 0-RTT Sync** | Pull raw logs / multi-RTT | WASM `109 B` (`0.72 ms`) • Slepian 0-RTT `-56.61%` (`1.47 ms`) | PASS |
| **`PHANTOM-12550` (`v6.0`)** | `506.63 ms` HTTPS overlay | **`36.63 ms` min / `52.68–53.26 ms` mean** (`9.5x` faster) | PASS |
| **0-Token Surgical Map (`v6.0`)** | Multi-turn AI search | `54` files (`390.4 KB`) -> **`4.10 KB`** (`-98.95%` in `71.89 ms`) | PASS |

See [docs/EVALUATION.md](docs/EVALUATION.md), [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), and [docs/MOONSHOT_VAULT.md](docs/MOONSHOT_VAULT.md) for complete benchmarks and protocol internals.

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

### 2. Run 24/7 Daemons & `v7.0` / `v6.0` CLI Subcommands
```bash
# Start 24/7 Cockpit + PHANTOM Tunnel (:2222 SSH, :9789 HTTP, :12550 Relay) + LocalEdgeProxy & WebDAV (:9788)
chimera-tp daemon

# Inspect v7.0 OMEGA capabilities & run 14-idea Before/After benchmark (live across 5ms tunnel or --local)
chimera-tp omega status --peer-http http://127.0.0.1:9780
chimera-tp omega bench --peer-http http://127.0.0.1:9780
chimera-tp omega ppm
chimera-tp omega wasm --peer-http http://127.0.0.1:9780
chimera-tp omega slepian
chimera-tp omega regen

# Check redacted Synergy status, 0-token brief, ready PRs, burn scan, or GF(256) vault
chimera-tp synergy status --peer-http http://127.0.0.1:9780
chimera-tp synergy brief --workspace-dir /path/to/workspaces/issue_1 --title "Bug summary" --inject
```

---

## Automated Tests

```bash
python -m unittest discover -s tests -v
```

- **Windows (`Rust GFNI` + Python 3.11):** **53 / 53 PASS in `65.270s`** (`test_chimera`, `test_hyper`, `test_v2_autopilot`, `test_v3_hypergrid`, `test_v4_hyperos`, `test_v5_phantom`, `test_v6_synergy`, `test_v7_omega`).
- **Linux (`C11 AVX2` + Python 3.14):** **53 / 53 PASS in `45.678s`** (`test_chimera`, `test_hyper`, `test_v2_autopilot`, `test_v3_hypergrid`, `test_v4_hyperos`, `test_v5_phantom`, `test_v6_synergy`, `test_v7_omega`).

---

## Security & Scope Disclaimer

`chimera-tp` enforces multiple defense-in-depth invariants:
- **Redacted Telemetry**: `ApexSynergyEngine` strips `email` and personal `label` fields from relay responses (`test_quota_arbiter_regimes_and_email_redaction` asserts zero `@` leaks).
- **PHANTOM-5MS (`PH5E`)**: Every multiplexed UDP frame uses per-packet `BLAKE2b` keystream obfuscation and a truncated `BLAKE2s-128` MAC; server TCP dialing is restricted to `phantom_allowed_ports` on loopback (`127.0.0.1`).
- **Containment & Safe Remediation**: Ghost-FS, WebDAV `/dav/`, surgical brief generation, circuit-breaker writes, and Medic playbooks enforce path containment inside `allowed_query_roots`, block `.git` writes, support `ETag` CAS, isolate multi-MB GF(256) vault compression via worker subprocesses with atomic SQLite `.backup()`, and accept only strictly allowlisted Medic playbooks. Always expose inter-node HTTP strictly over localhost or authenticated Tailscale/WireGuard overlays.
