# Kiến trúc kỹ thuật CHIMERA-HYPER v1.0 (`chimera-tp`)

## 1. Tổng quan kiến trúc hai tầng

Từ phiên bản **v1.0.0**, `chimera-tp` tách rõ hai chế độ:
- **CHIMERA-HYPER v1.0 (Mặc định hiệu năng & công việc thật)**: Kết hợp lõi Rust `native/chimera_core` + FFI zero-copy `chimera_tp/native.py` với 4 động cơ chính (`dna_vault.py`, `hyper_wire.py`, `active_pipe.py`, `warp.py`, điều phối bởi `fabric.py`).
- **CHIMERA-TP v0.5 Exotic Realms (`lanes.py`, `protocol.py`)**: Giữ nguyên 100% tương thích 8 cõi truyền dị biệt (`GHOST_127`, `LAN_LENGTH`, `TS_V4_1280`, `TS_V6_CHORD`, `HYPERV_MCAST`, `WSL_PERMUTE`, `ICMP_REFLECT`, `LO_V6_JUMBO`) cho nghiên cứu đa kênh.

---

## 2. Lõi Silicon Native Rust (`native/chimera_core/src/lib.rs`)

Biên dịch thành `chimera_tp/_chimera_core.dll` với `opt-level = 3, lto = true, codegen-units = 1`, không phụ thuộc crate ngoài:

### 2.1 Intel GFNI (`_mm256_gf2p8mul_epi8`) & AVX2 cho $GF(2^8)$
- Đa thức chuẩn `0x11B` ($x^8 + x^4 + x^3 + x + 1$), khớp tuyệt đối 65,536/65,536 cặp byte với `chimera_tp.gf256.gf_mul`.
- `chimera_gf256_mul_add` & `chimera_gf256_scale`: xử lý 128 byte/vòng (unroll `4 x __m256i`), fallback AVX2 XOR cho `coeff == 1` và bảng hằng `MUL_LUT` tĩnh cho phần đuôi hoặc CPU không có GFNI.
- `chimera_gf256_encode_block` & `chimera_gf256_decode_matrix`: khử Gauss-Jordan toàn ma trận ngay trong Rust chỉ qua **1 lần gọi FFI** cho mỗi thế hệ `k x block_len`.

### 2.2 FastCDC + Odess Super-Feature + Delta Codec
- **FastCDC (`chimera_fastcdc`)**: Dùng bảng Gear 64-bit tĩnh (`GEAR_TABLE`) với hai mặt nạ chuẩn hóa (`mask_s` ngặt trước `avg_sz`, `mask_l` lỏng sau `avg_sz`), giúp chèn byte ở đầu file chỉ làm lệch 1 khối đầu và vẫn khớp 100% các khối phía sau.
- **Odess Super-Features (`chimera_superfeatures`)**: Băm mẫu vị trí có `(h & sample_mask) == 0` qua 12 hàm biến đổi tuyến tính độc lập, gom thành 4 super-feature `u64` (nhóm 3) để tìm khối họ hàng tương đồng ở độ phức tạp $O(1)$.
- **Delta Codec (`chimera_delta_encode` / `chimera_delta_decode`)**: Chỉ mục bảng băm trượt 16 byte trên `base`, mở rộng khớp 8 byte/bước (`COPY=0x01`, `LITERAL=0x02`).

### 2.3 Active Byte-Line Filter & Lock-Free Windows Shared Memory Wormhole
- `chimera_active_filter_lines`: lọc dòng chứa từ khóa đích trực tiếp trên vùng nhớ thô với tốc độ multi-GB/s.
- `chimera_wormhole_*`: Tạo/mở vùng nhớ dùng chung Windows (`CreateFileMappingW` / `OpenFileMappingW` trên tiền tố `Local\CHIMERA_WH_`), tiêu đề căn lề cache line (`magic`, `capacity`, `closed`, `write_pos`, `read_pos` dùng atomic `Acquire`/`Release`). Tương thích streaming vượt kích thước ring (`len > capacity`), pre-touch trang nhớ khi khởi tạo và chiến lược `spin_loop` &rarr; `yield_now` &rarr; `Sleep(1)`.

---

## 3. Giao thức Vận chuyển (`hyper_wire.py`), Tunnel (`warp.py`), Compute (`active_pipe.py`)

### 3.1 HyperWire (20-Byte Compact Frame + Adaptive GFNI FEC)
- Header **20 byte**: `magic(2)="CH"`, `ptype(1)`, `stream_id(1)`, `gen_id(2)`, `sym_id(2)`, `orig_len(4)`, `k(2)`, `payload_len(2)`, `crc32(4)`.
- **Zero-Bloat Fast Path**: Ở trạng thái mạng sạch (`est_loss == 0`), chỉ gửi `k` gói hệ thống (`SYS`), `0` gói FEC, `0` khử ma trận (`1.53%` overhead tổng).
- **Zero-Collapse Lossy Path**: Receiver theo dõi khoảng trống thứ tự gói hệ thống để cập nhật `observed_loss_ewma` và phát hiện mất gói ngay khi thấy gói thế hệ/chỉ số cao hơn (`GEN_NEED`). Sender điều chỉnh số gói sửa lỗi chủ động theo phân bố nhị thức $k \frac{p}{1-p} + 1.15\sigma$ và không bao giờ cắt đôi cửa sổ gửi (`max_inflight_gens = 24`).
- **Linear Independence Filter (`select_independent_rows`)**: Loại bỏ các hàng FEC phụ thuộc tuyến tính ngay trước khi gọi `gf256_decode_matrix`, triệt tiêu hoàn toàn nguy cơ kẹt ma trận suy biến.
- **Hedged Multi-Path Racing (`HedgedRpcClient` / `HedgedRpcServer`)**: Bắn đồng thời/trễ có kiểm soát yêu cầu RPC lên nhiều đường đích và ăn phản hồi hợp lệ về đầu tiên, chống sập `p99`.

### 3.2 Warp Transparent TCP Accelerator (`warp.py`)
- Multiplex kết nối TCP (`WarpClient` &harr; `WarpServer`) thành các mảnh `_CHUNK_MAX = 1320 B` với cờ nén `zlib` từng mảnh, nhóm parity `GF(256)` (`_FEC_GROUP = 8`) và `NACK` chọn lọc không giảm băng thông trên mạng mất gói.

### 3.3 Legacy v0.5.0 Exotic Multi-Realm Plane (`lanes.py` / `protocol.py`)
- Bảo lưu đầy đủ Segmented `GF(256)` RLNC, Chaos Scheduler (`balanced`/`stealth`/`turbo`), Parallel Per-Lane TX Workers và 8 kênh ẩn/vật lý trên Windows (`GHOST_127`, `LAN_LENGTH`, `TS_V4_1280`, `TS_V6_CHORD`, `HYPERV_MCAST TTL=0`, `WSL_PERMUTE S_6`, `ICMP_REFLECT`, `LO_V6_JUMBO`).
