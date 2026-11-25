# Roadmap — CHIMERA-HYPER

## Completed — `v1.0.0` (Hyper Foundation)
- Rust GFNI / AVX2 / AVX-512F GF(256) matrix engine + Win32 Named Shared Memory ring
- HyperWire sliding-window RLNC + XOR obfuscation
- FastCDC + Odess SuperFeature delta engine (DNA Beam)
- Active Pipe compute-in-flight filter with P0 preview streaming
- Full local benchmark & HTML visualization report

## Completed — `v2.0.0 AUTOPILOT` (Cross-Platform & Autonomous Ops)
- **Linux C11 AVX2 Silicon Core (`native/chimera_core_c`)**: `VPSHUFB` split-nibble GF(256), bit-identical FastCDC/Odess, and POSIX `/dev/shm` lock-free SPSC Wormhole.
- **Cross-Host Tailscale Dual-Stack Transport**: MTU-safe (`1180 B`) symbol framing, `AF_INET`/`AF_INET6` hedged RPC, single-port UDP NAT/firewall feedback routing, and bidirectional DNA Beam + Active Query servers.
- **Autonomous Daily Control Loop (`autopilot.py`)**: SQLite-backed run telemetry, regression/fallback anomaly detection, and 5-genome **Darwinian UCB1 Bandit** self-tuning.
- **24/7 Mission-Control Cockpit (`dashboard.py`)**: Web dashboard + REST API + built-in daily scheduler + OS-level triggers (`Task Scheduler` & `systemd --user`).

## Next Horizons — `v2.1+`
1. **Cross-Chunk Dictionary Compression (Zstd Trained Dicts)**: Train per-repo / per-log-stream Zstd dictionaries across `Odess` buckets to push Active Query wire reduction from `68%` toward `85%+` on repetitive log streams.
2. **Adaptive Congestion & RTT Estimator (Kalman Loss Tracking)**: Feed live moving-window packet loss and jitter from `HyperWire` directly into `loss_hint` mid-stream rather than per-run genome selection alone.
3. **Directory-Tree Merkle Beam (`beam-sync`)**: Extend `BeamServer` from single blobs to hierarchical Merkle trees for sub-second cross-host workspace synchronization over high-RTT VPN links.
4. **ARM64 NEON (`PMULL` / `VTBL`) Core**: Port `native/chimera_core_c` to `aarch64` NEON (`vmull_p8` / `vqtbl1q_u8`) for Raspberry Pi / Apple Silicon edge nodes.
5. **Signed Cluster Mesh Auth**: HMAC-SHA256 / Ed25519 challenge-response framing on daemon control endpoints so cockpit management remains hardened even on untrusted LANs.
