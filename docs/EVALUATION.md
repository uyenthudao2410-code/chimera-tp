# Đánh giá thực nghiệm & So sánh Trước–Sau (CHIMERA-HYPER v1.0 & v0.5.0)

Tài liệu này ghi nhận số liệu thực nghiệm đo trên hệ thống Windows 64-bit (`Intel Core i5-11400`, `gfni=true`, `avx2=true`, `avx512f=true`, Rust `1.92.0`, Python `3.11.7`).

---

## Phần A — Đánh giá CHIMERA-HYPER v1.0 (`benchmarks/benchmark_hyper.py`)

Kiểm chứng đồng thời **`19/19` unit/integration tests PASS (`24.474s`)** (`11/11` v0.5.0 + `8/8` v1.0.0) và 7 suite benchmark đối đầu trực diện TCP/UDP chuẩn trên cùng mô hình giới hạn băng thông/mất gói đối xứng (`ImpairedUdpBridge` + `WinTimerScope`).

### 1. Lõi Silicon Native Rust Intel GFNI (`suite_0_silicon_core`)

| Phép toán `GF(256)` (`0x11B`) | Python thuần (`gf256.py`) | Rust Silicon Core (`GFNI` + `AVX2`) | Tăng tốc |
| :--- | ---: | ---: | ---: |
| **16 MiB Vector `mul_add`** | `86.04 ms` (`1,559.9 Mbps`) | **`2.36 ms` (`56,939.5 Mbps`)** | **`36.5x`** |
| **32 x 1360 B RLNC Encode + Matrix Solve** | `106.77 ms` | **`0.72 ms`** | **`149.25x`** |

- Kiểm thử vét cạn **65,536/65,536** cặp byte `(a, b)` trong `[0..255] x [0..255]`: **0 sai khác** so với `gf_mul`.

### 2. Chống sập băng thông mạng WAN có rớt gói (`suite_2_lossy_wan`)

Truyền `2 MiB` dữ liệu ngẫu nhiên qua cùng cầu `ImpairedUdpBridge(bandwidth=100 Mbps, RTT=50 ms)`. **Lưu ý:** CHIMERA-HYPER khởi chạy hoàn toàn mù (`initial_loss_hint=0.0`), tự học mức rớt gói từ phản hồi vòng đầu.

| Tỷ lệ rớt gói | TCP-CUBIC chuẩn (IW10/RTO) | CHIMERA Silicon GFNI Wire | Tốc độ vượt trội |
| ---: | :--- | :--- | ---: |
| **0%** | `1,150.15 ms` (`14.59 Mbps`, rtx=0) | **`311.05 ms` (`53.94 Mbps`, fec=0, overhead=1.53%)** | **`3.70x`** |
| **2%** | `9,422.40 ms` (`1.78 Mbps`, rtx=41, rto=10) | **`308.20 ms` (`54.44 Mbps`, fec=136, solves=24)** | **`30.57x`** |
| **5%** | `16,143.58 ms` (`1.04 Mbps`, rtx=90, rto=32) | **`347.29 ms` (`48.31 Mbps`, fec=159, solves=38)** | **`46.48x`** |
| **10%** | `26,143.85 ms` (`0.64 Mbps`, rtx=172, rto=83) | **`316.79 ms` (`52.96 Mbps`, fec=288, solves=47)** | **`82.53x`** |

### 3. Bốn đột phá công việc thực tế (`suite_1`, `suite_3`, `suite_4`, `suite_5`)

| Tác vụ thực tế | BEFORE (Chuẩn truyền thống) | AFTER (CHIMERA-HYPER v1.0) | Hiệu quả đo được |
| :--- | :--- | :--- | :--- |
| **Đồng bộ 30 MB (chèn đầu + sửa 3%) @ 100 Mbps** | TCP: `2,523.5 ms` (`31.46 MB` wire, `99.7 Mbps`) | **DNA Beam**: **`267.7 ms`** (`160,080 B` wire, `1,322` REF + `9` DELTA, **`940.0 Mbps` eff.**) | **`9.43x`** (`99.49%` wire saved) |
| **Lọc `24.6 MB` log (1% khớp) @ 100 Mbps** | TCP tải về rồi lọc: `2,010.9 ms` | **Active Pipe**: **`65.4 ms`** (`248,907 B` wire, **P0 preview sau `38.2 ms`**) | **`30.73x`** (`98.99%` wire saved) |
| **RPC tương tác (80 reqs, 50 ms RTT + jitter + 5% loss)** | Đơn đường: `p50=114.6`, `p95=240.0`, `p99=353.6 ms` | **Hedged Multi-Path**: `p50=72.9`, `p95=118.8`, **`p99=177.4 ms`** | **`1.99x` giảm `p99`** |
| **IPC Windows `64 MiB` (kèm kiểm tra SHA-256)** | TCP `127.0.0.1`: `70.94 ms` (`7.57 Gbps`) | **Wormhole SHM**: **`47.30 ms` (`11.35 Gbps`)** | **`1.50x`** |

### 4. Kiểm tra trung thực Worst-Case (`suite_6_worst_case`)

- Dữ liệu `2 MiB` ngẫu nhiên không nén mới hoàn toàn trên đường truyền `100 Mbps` sạch (`0%` rớt gói):
  - **TCP**: `173.87 ms` (`96.49 Mbps`)
  - **CHIMERA Auto-Pilot**: `203.09 ms` (`82.61 Mbps`, `fec=0`, overhead khung chỉ `1.53%`, bằng **`0.856x` TCP**).
  - Xác nhận đã triệt tiêu hoàn toàn nhược điểm phình băng thông `53x–204x` và chậm `8x` ở v0.5.0 khi chạy ở chế độ thực chiến.

---

## Phần B — Lưu trữ kết quả v0.5.0 Exotic Lanes

Các tính chất đặc biệt của bộ v0.5.0 vẫn vượt qua toàn bộ **`11/11` tests** trong `tests/test_chimera.py`:
- **`GHOST_127`**: `0 B` payload UDP.
- **`LAN_LENGTH`**: Bất biến với đảo bit 100% nội dung payload.
- **`HOLOGRAPHIC-SPLIT`**: Bơm `8 MiB` đạt `85.21 Mbps` trên `::1`, chịu rớt `25%` jumbo chunk qua Stripe XOR FEC + Selective NACK, entropy `7.99998 b/B`.
