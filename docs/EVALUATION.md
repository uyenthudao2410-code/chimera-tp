# Đánh giá thực nghiệm & So sánh nâng cấp (v0.2.0 &rarr; v0.5.0)

Tài liệu này tổng hợp kết quả chạy thực tế sau nâng cấp v0.5.0 của bộ test (`11/11` tests PASS trong `20.543s`) và 7 suite benchmark (`benchmarks/benchmark_eval.py`) trên môi trường Windows thực tế.

---

## 1. Hậu kiểm các bug đã phát hiện & xử lý qua hai vòng kiểm thử

1. **v0.2.0 — Nhiễm độc liên phiên & chết luồng RX tại 70% drop**:
   - Đã vá bằng Keyed CRC-16 (`rlnc_seed + body`), `reset_state()` xả socket/slot trước mỗi phiên và bắt `zlib.error`.
2. **v0.5.0 (Milestone 3) — `SOLV` JSON tràn ngưỡng UDP `65,507 B` (`WinError 10040`) ở 16 KiB (`k=1,025`)**:
   - Khi chuyển sang Segmented RLNC và gửi thành công `1,025` khối, danh sách `rank_timeline` dài 1,032 phần tử khiến gói UDP `SOLV` vượt 90 KiB và bị hệ điều hành từ chối im lặng.
   - **Khắc phục**: Lấy mẫu đều tối đa `120` mốc `rank_timeline` trong gói `SOLV`, giúp `SOLV` luôn `< 12 KiB` ngay cả khi truyền hàng nghìn khối.

---

## 2. So sánh Trước (TCP/UDP chuẩn) vs Sau (CHIMERA-TP v0.5.0)

| Kịch bản đo | BEFORE — TCP / UDP chuẩn | AFTER — CHIMERA-TP v0.5.0 | Ghi chú kỹ thuật |
| :--- | :--- | :--- | :--- |
| **512 B bình thường (LAN)** | TCP: `2.12 ms` (`1,928 kbps`, `552 B`)<br/>UDP: `0.62 ms` (`6,606 kbps`, `544 B`) | `PURE-METAMORPHIC`: `32.65 ms` (`125.4 kbps`, `53.17x` amp) | `0%` plaintext trên từng NIC đơn lẻ; đổi lại độ trễ và băng thông gấp nhiều lần |
| **256 KiB Bulk (`::1`)** | TCP: `2.04 ms` (`1,030.0 Mbps`)<br/>Wire entropy: `6.122 b/B` | `HOLOGRAPHIC-SPLIT`: `60.94 ms` (`34.4 Mbps`)<br/>Wire entropy: **`7.99934 b/B`** | Che OTP gắn với `topology_fingerprint` |
| **1 MiB Bulk (`::1`)** | TCP: `16.12 ms` (`520.3 Mbps`)<br/>UDP: `12.78 ms` (`656.4 Mbps`) | `HOLOGRAPHIC-SPLIT`: `132.41 ms` (`63.4 Mbps`)<br/>Wire entropy: **`7.99982 b/B`** | Chậm hơn TCP `~8x`, bù lại entropy `7.9998 b/B` và khóa 72 B đi 7 kênh |
| **20% Packet Loss (512 B)** | UDP: **FAIL** (`SHA-256 sai`) | **PASS** (`SHA-256 khớp`) | GF(256) tự bù không cần bắt tay lại |
| **Đảo 100% bit payload** | UDP: **FAIL** (`SHA-256 sai`) | `LAN_LENGTH`: **PASS** (`SHA-256 khớp`) | Giải mã theo độ dài gói, bất biến với nội dung payload |
| **Đứt 3 giao diện mạng** | Single-NIC: **FAIL** (`0%`) | **PASS** (`SHA-256 khớp` trên 4 làn sống) | Khả năng sống sót đa đường truyền |
| **Mất 25% chunk `LO_V6_JUMBO` (`1 MiB`)** | UDP thuần: **FAIL** | **PASS** (`111.55 ms`, `75.20 Mbps`, `FEC=4, NACK=2`) | **Tính năng mới v0.5.0**: Stripe XOR FEC 0-RTT + Selective NACK |

---

## 3. Bước nhảy vọt từ v0.2.0 lên v0.5.0 (Số liệu đo thực tế)

### 3.1 Ma trận Profile & Song song (2,048 B dữ liệu ngẫu nhiên không nén, `k=129`)

| Cấu hình | Kết quả | Thời gian (ms) | Goodput (kbps) | Tổng dây ước tính (B) | Wire Amplification |
| :--- | :--- | ---: | ---: | ---: | ---: |
| `balanced_seq` (như v0.2.0) | PASS | `363.42` | `45.08` | `417,784` | `204.00x` |
| `balanced_par` (v0.5.0) | PASS | `83.71` | `195.72` | `197,768` | `96.57x` |
| `stealth_par` (v0.5.0) | PASS | `75.95` | `215.73` | `167,826` | `81.95x` |
| `turbo_par` (v0.5.0) | PASS | **`65.32`** | **`250.81`** | **`161,631`** | **`78.92x`** |

### 3.2 Scaling kích thước & Soak Test
- **`PURE-METAMORPHIC` (`0 B -> 16 KiB` không nén)**:
  - `0 B`: `4.33 ms` | `1 B`: `3.87 ms` | `64 B`: `7.38 ms` (`69.35 kbps`) | `512 B`: `94.60 ms` | `2,048 B`: `83.88 ms` (`195.33 kbps`) | `4,096 B`: `180.69 ms` (`181.35 kbps`, nhanh hơn **4.24x** so với `765.70 ms` của v0.2.0) | `16,384 B` (`turbo`, `k=1,025`, 33 gen): **`536.78 ms` (`244.18 kbps`)**.
- **`HOLOGRAPHIC-SPLIT` (`16 KiB -> 8 MiB`)**:
  - `16 KiB`: `17.65 ms` (`7.43 Mbps`, `7.98988 b/B`)
  - `256 KiB`: `48.45 ms` (`43.29 Mbps`, `7.99920 b/B`)
  - `1 MiB`: `130.77 ms` (`64.15 Mbps`, `7.99982 b/B`)
  - `4 MiB`: `473.79 ms` (`70.82 Mbps`, `7.99996 b/B`)
  - `8 MiB` (145 chunks): `787.55 ms` (**`85.21 Mbps`**, `7.99998 b/B`)
- **Chaos Drop Sweep (`0% -> 70%`)**: **6/6 PASS** (`19.09 ms` @ `0%` -> `444.81 ms` @ `70%`, `ratio=3.64x`).
- **20-Run Soak Test**: **20/20 (100.0%)** — `min=9.85 ms`, `p50=24.35 ms`, `p95=129.10 ms`, `crc_drops=0`.
- **2-Process CLI (`listen` / `connect`)**: PASS cả `PURE-METAMORPHIC` lẫn `HOLOGRAPHIC-SPLIT` dưới `25%` jumbo drop trên 2 tiến trình OS tách biệt.
- **5-Point Security Audit**: **5/5 PASS**.

---

## 4. Giới hạn còn tồn tại ở v0.5.0
1. **Phóng đại băng thông vẫn lớn** khi dùng `LAN_LENGTH` (`~310x`), `TS_V6_CHORD` (`~109x`), `WSL_PERMUTE` (`~97x`); chế độ `turbo` giảm tổng dây từ `204x` xuống `78.9x` nhưng chưa triệt tiêu hẳn nếu không tắt `LAN_LENGTH`.
2. **Phạm vi host-local**: `GHOST_127`, `ICMP_REFLECT` (`127.0.0.1`), `HYPERV_MCAST` (`TTL=0`), và `LO_V6_JUMBO` (`::1`) chỉ hoạt động nội bộ trên cùng máy chủ.
3. **Nút cổ chai Python thuần**: Khi truyền trên `::1`, `HOLOGRAPHIC-SPLIT` đạt `~63–85 Mbps` so với `520–1,030 Mbps` của TCP kernel do chi phí băm `blake2b` tạo keystream OTP và vòng lặp đóng/mở gói ở user-space.
