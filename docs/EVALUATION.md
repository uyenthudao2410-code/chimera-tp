# Đánh giá thực nghiệm & Before-vs-After (CHIMERA-TP v0.2.0)

Tài liệu này tổng hợp kết quả chạy thực tế của bộ unit tests (`tests/test_chimera.py`) và 6 suite benchmark tái lập được (`benchmarks/benchmark_eval.py`) trên môi trường Windows 10/11 với đầy đủ 8 cõi mạng (`GHOST_127`, `LAN_LENGTH`, `TS_V4_1280`, `TS_V6_CHORD`, `HYPERV_MCAST`, `WSL_PERMUTE`, `ICMP_REFLECT`, `LO_V6_JUMBO`).

---

## 1. Hậu kiểm lỗi thực tế phát hiện khi Stress Test

Trong lần chạy sweep đầu tiên trước bản vá v0.2.0, khi đẩy tỷ lệ rớt gói lên **70%** (gần 1,000 giọt phát đi liên tiếp ngay sau phiên 55%):
1. **Nhiễm độc liên phiên (Cross-Session Straggler Poisoning)**: CRC-16 khi đó chưa gắn `rlnc_seed`, đồng thời bộ đệm lắp ghép các kênh không được xả giữa các phiên trên cùng một `ChimeraReceiver`. Một giọt trễ từ phiên trước hợp lệ hóa sai vào ma trận phiên mới.
2. **Sập toàn bộ 7 luồng RX khi gặp `zlib.error`**: Do `zlib.decompress(raw)` không được bọc `try/except`, giải nén lỗi làm chết cả 7 thread `rx-*` nối tiếp nhau.

**Khắc phục đã xác minh bằng hồi quy `test_cross_session_straggler_rejected`**:
- Chuyển CRC-16 sang `crc16_ccitt(self.seed + body)` (0 byte tăng thêm trên dây).
- Bổ sung `reset_state()` xả socket và dọn slot lắp ghép cho từng lane khi khởi tạo phiên mới.
- Bắt `zlib.error` trong `_on_droplet_received` và bọc `Exception` trong `_rx_loop`.

---

## 2. So sánh Trước (TCP/UDP chuẩn) vs Sau (CHIMERA-TP)

| Kịch bản đo | BEFORE — Giao thức chuẩn | AFTER — CHIMERA-TP | Đánh đổi kỹ thuật |
| :--- | :--- | :--- | :--- |
| **512 B bình thường (LAN)** | TCP: `21.60 ms` (`189.61 kbps`, `552 B`)<br/>UDP: `0.39 ms` (`10,545.83 kbps`, `544 B`) | `PURE-METAMORPHIC`: `35.31 ms` (`116.01 kbps`, `28,547 B`) | Tốn băng thông **`55.76x`**, chậm hơn UDP ~90x; đổi lại `0%` plaintext trên bất kỳ 1 NIC đơn lẻ nào |
| **256 KiB Bulk (`::1`)** | TCP: `23.19 ms` (`90.43 Mbps`)<br/>UDP: `0.88 ms` (`2,373.96 Mbps`)<br/>Wire entropy: `6.12244 b/B` | `HOLOGRAPHIC-SPLIT`: `46.14 ms` (`45.46 Mbps`)<br/>Wire entropy: **`7.99929 b/B`** | Chậm hơn TCP ~2x ở 256 KiB; nâng entropy gần bão hòa `8.0` và khóa theo Topology FP |
| **1 MiB Bulk (`::1`)** | TCP: `21.78 ms` (`385.11 Mbps`)<br/>UDP: `12.94 ms` (`648.35 Mbps`) | `HOLOGRAPHIC-SPLIT`: `99.27 ms` (`84.50 Mbps`)<br/>Wire entropy: **`7.99982 b/B`** | Giữ tốc độ hàng chục Mbps cho bulk trong khi capsule khóa 72 B đi qua 7 cõi dị biệt |
| **20% Packet Loss (512 B)** | UDP: **FAIL** (`464/512 B`, `279.18 ms`) | **PASS** (`54.10 ms`, gửi `12` nhận đủ `11` giọt) | GF(256) tự bù mất gói không cần truyền lại |
| **Đảo 100% bit payload** | UDP: **FAIL** (sai SHA-256) | `LAN_LENGTH`: **PASS** (`10.75 ms`, khớp SHA-256) | Dữ liệu nằm ở chiều dài gói, bất biến với nội dung payload |
| **Đứt 3 giao diện mạng** | Single-NIC: **FAIL** (`0%` sống sót) | **PASS** (`17.53 ms`, còn 4 làn hoạt động) | Tự động dồn tải sang các giao diện còn sống |

---

## 3. Hiệu năng từng kênh khi chạy cô lập (384 B, tắt 6 kênh còn lại)

| Lane ID | Kết quả | Thời gian (ms) | Goodput (kbps) | Số gói TX | Wire Payload (B) | Tổng dây ước tính (B) | Wire Amplification |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| `TS_V4_1280` | PASS | `4.49` | `683.68` | `9` | `252` | `504` | `1.31x` |
| `ICMP_REFLECT` | PASS | `4.68` | `657.03` | `9` | `288` | `468` | `1.22x` |
| `LAN_LENGTH` | PASS | `14.04` | `218.78` | `180` | `114,468` | `119,508` | **`311.22x`** |
| `TS_V6_CHORD` | PASS | `24.57` | `125.05` | `767` | `2,301` | `39,117` | **`101.87x`** |
| `WSL_PERMUTE` | PASS | `27.00` | `113.76` | `1,080` | `3,240` | `33,480` | **`87.19x`** |
| `HYPERV_MCAST` | PASS | `40.05` | `76.70` | `360` | `720` | `10,800` | `28.12x` |
| `GHOST_127` | PASS | `98.64` | `31.14` | `90` | **`0`** | `2,520` | `6.56x` |

---

## 4. Quét tỷ lệ mất gói (`0% -> 70%`) & Scaling kích thước

### 4.1 Chaos Drop Sweep (512 B, `k=11`, toàn bộ 7 kênh + đảo 100% bit LAN)
- `0%`: `34.37 ms` (`11/11`, `1.00x`, `119.17 kbps`) — PASS
- `10%`: `42.43 ms` (`11/11`, `1.00x`, `96.53 kbps`) — PASS
- `25%`: `117.96 ms` (`16/11`, `1.45x`, `34.72 kbps`) — PASS
- `40%`: `93.56 ms` (`14/11`, `1.27x`, `43.78 kbps`) — PASS
- `55%`: `288.14 ms` (`26/11`, `2.36x`, `14.22 kbps`) — PASS
- `70%`: `460.01 ms` (`38/11`, `3.45x`, `8.90 kbps`) — PASS

### 4.2 Scaling theo kích thước
- **`PURE-METAMORPHIC` (dữ liệu ngẫu nhiên không nén được `>= 64 B`)**:
  - `0 B` (`k=1`): `4.08 ms` | `1 B` (`k=1`): `2.61 ms` | `64 B` (`k=5`): `20.25 ms` (`25.28 kbps`) | `512 B` (`k=33`): `93.80 ms` (`43.67 kbps`) | `2,048 B` (`k=129`): `342.39 ms` (`47.85 kbps`) | `4,096 B` (`k=257`): `765.70 ms` (`42.79 kbps`).
  - Cho thấy trần thông lượng tự nhiên ~`43–48 kbps` của `PURE-METAMORPHIC` do phát tuần tự qua Python và khử Gauss $O(K^3)$ khi `k` tăng.
- **`HOLOGRAPHIC-SPLIT`**:
  - `16 KiB` (1 chunk): `22.72 ms` (`5.77 Mbps`, entropy `7.98705`)
  - `256 KiB` (5 chunks): `40.26 ms` (`52.09 Mbps`, entropy `7.99933`)
  - `1 MiB` (19 chunks): `109.63 ms` (`76.52 Mbps`, entropy `7.99986`)
  - `4 MiB` (73 chunks): `367.25 ms` (**`91.37 Mbps`**, entropy **`7.99995`**)

---

## 5. Soak Test 20 lượt & Kiểm toán bất biến (5/5)

- **20-Run Randomized Soak Test**: **20/20 (100.0%)** với payload ngẫu nhiên `32–1024 B`, tắt `0–3` kênh ngẫu nhiên, mất gói `0–30%`, đảo bit LAN ngẫu nhiên; độ trễ `min = 20.5 ms`, `p50 = 53.2 ms`, `p95 = 214.78 ms`, `0` lỗi CRC lọt phiên.
- **5-Point Security & Invariant Audit (5/5 PASS)**:
  1. `ghost_zero_payload`: `GHOST_127` gửi chính xác `0` byte UDP payload.
  2. `lan_bitflip_invariant`: `LAN_LENGTH` khớp SHA-256 khi đảo 100% bit payload.
  3. `mcast_ttl_zero`: `HYPERV_MCAST` cố định `IP_MULTICAST_TTL = 0`.
  4. `holo_topology_binding`: Sửa 1 ký tự hex trong `topology_fingerprint` ở máy nhận khiến `HOLOGRAPHIC-SPLIT` giải mã sai và bị từ chối.
  5. `holo_entropy_gain`: Entropy tăng từ `6.12244` lên `7.99929 bits/byte`.

---

## 6. Giới hạn cố hữu đã ghi nhận
1. **Phóng đại băng thông cao** trên `LAN_LENGTH` (`311x`), `TS_V6_CHORD` (`102x`), `WSL_PERMUTE` (`87x`).
2. **Độ phức tạp $O(K^3)$ của GF(256)** khiến `PURE-METAMORPHIC` chỉ phù hợp cho thông điệp nhỏ hoặc capsule khóa (`< 4 KiB`), còn dữ liệu lớn bắt buộc đi qua `HOLOGRAPHIC-SPLIT`.
3. **`LO_V6_JUMBO` thiếu FEC/ARQ riêng**: nếu mất mảnh 58 KiB ở quy mô nhiều chục MB trên đường truyền thật, khối bulk sẽ chờ timeout.
4. **Phạm vi loopback / host-local**: toàn bộ 8 kênh hiện vận hành nội bộ trên cùng máy để đảm bảo an toàn thử nghiệm.
