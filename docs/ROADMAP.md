# Lộ trình nghiên cứu & phát triển (`CHIMERA-TP` &rarr; `CHIMERA-HYPER`)

## Đã hoàn thành
- [x] **v0.2.0**: Kiến trúc 8 cõi truyền dị biệt trên Windows (`GHOST_127` &rarr; `LO_V6_JUMBO`) + GF(256) RLNC + Chaos Scheduler.
- [x] **v0.3.0**: CRC-32 từng mảnh, XOR Stripe FEC (4:1) và Selective NACK ARQ (`JCHK`/`JNCK`/`JOK!`) cho `LO_V6_JUMBO`.
- [x] **v0.4.0**: Phát song song theo từng lane và 3 profile lập lịch (`balanced`, `stealth`, `turbo`).
- [x] **v0.5.0**: Segmented RLNC ($O(K)$ scaling) + chế độ 2 tiến trình (`listen` / `connect`).
- [x] **v1.0.0 (`CHIMERA-HYPER`)**:
  - Lõi Rust 1.92 Silicon Native (`_chimera_core.dll`) tăng tốc Intel **GFNI (`VGF2P8MULB`)** + AVX2 đạt `56.9 Gbps` (`149.3x` giải mã ma trận).
  - **DNA Vault (`beam`)**: FastCDC + Odess Super-Feature + Delta Codec giảm tới `99.49%` băng thông đồng bộ tăng dần.
  - **Silicon GFNI Wire + Hedged Multi-Path + Transparent TCP Tunnel (`warp`)**: Giữ `53.0 Mbps` dưới `10%` rớt gói WAN (`82.5x` nhanh hơn TCP-CUBIC) và giảm `1.99x` độ trễ đuôi `p99`.
  - **Lock-Free Windows Shared Memory Wormhole & Active Compute-in-Transit (`pipe`)**: `11.35 Gbps` IPC cục bộ (có SHA-256) và lọc `24.6 MB` log trên đường truyền nhanh hơn `30.7x`.

## Hướng mở rộng tiếp theo (v1.1+)
1. **Cross-Host Daemon & Tailscale Auto-Peering**: Tự động phát hiện peer cùng LAN / Tailscale (`TS_V4_1280` + WAN) để `warp` và `beam` mở khóa đồng thời đa đường vật lý thực tế giữa hai máy Windows/Linux.
2. **GPU Batch Coding (CUDA/Vulkan trên GTX 1650)**: Đẩy tác vụ mã hóa GF(256) thế hệ cực lớn (>100 MB) hoặc kiểm tra hash song song sang GPU trong các đường truyền datacenter multi-10GbE.
3. **PyO3 Native Extension**: Thay lớp `ctypes` ở `pip` wheel bằng module PyO3/CFFI để cắt tiếp chi phí chuyển đổi buffer Python ở mức chunk nhỏ `1–4 KB`.
