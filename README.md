# CHIMERA-HYPER v1.0 (`chimera-tp`)

**Silicon-Native Zero-Byte DNA Vault, Hardware GFNI (`VGF2P8MULB`) Adaptive Wire, Lock-Free Shared-Memory Wormhole & Active Compute-in-Transit Protocol**

CHIMERA-HYPER v1.0 nâng cấp toàn diện từ bản nghiên cứu đa cõi `v0.5.0` thành một **kiến trúc giao thức tăng tốc truyền tải và xử lý công việc thực tế**, kết hợp **lõi Rust 1.92 (`chimera_core.dll`)** tận dụng tập lệnh phần cứng **Intel GFNI + AVX2** cùng 4 đột phá tầng vận chuyển:

1. **Zero-Byte DNA Vault (`dna_vault.py` / `beam`)**: Cắt khối theo ranh giới nội dung bằng Rust FastCDC (`Gear hash`) + nhận diện khối họ hàng **Odess 4x64-bit Super-Feature** + nén sai khác Delta. Đồng bộ lại tập dữ liệu `30 MB` sửa `3%` qua mạng `100 Mbps` chỉ tốn **`160 KB` dây mạng (`99.49%` tiết kiệm)** — đạt tốc độ hiệu dụng **`940.0 Mbps` (`9.43x` nhanh hơn TCP)**.
2. **Silicon GFNI Adaptive Wire (`hyper_wire.py` / `warp`)**: Giao thức UDP có hệ thống + mã sửa lỗi `GF(256)` nhân trực tiếp bằng silicon Intel `VGF2P8MULB` (`56.9 Gbps`, giải ma trận `32x1360` trong `0.72 ms` — nhanh hơn Python **`149.3x`**). `0%` FEC overhead trên mạng sạch; trên mạng rớt **`10%` gói (`50 ms` RTT)** giữ tốc độ **`53.0 Mbps`** trong khi TCP-CUBIC sập xuống **`0.64 Mbps` (`82.53x` nhanh hơn TCP!)**.
3. **Active Compute-in-Transit (`active_pipe.py` / `pipe query`)**: Chạy lọc dòng/JSON/CSV (`Rust active_filter_lines`) ngay trên đường truyền và đẩy kết quả tóm tắt ưu tiên cao (`Priority-0 Preview`) sau `38.2 ms`, rút truy vấn `24.6 MB` log từ `2,011 ms` xuống **`65.4 ms` (`30.73x` nhanh hơn TCP)**.
4. **Lock-Free Shared Memory Wormhole & Hedged Multi-Path (`native.py`, `hyper_wire.py`)**: Ring buffer bộ nhớ dùng chung không khóa trên Windows cho IPC nội bộ (`11.35 Gbps` end-to-end với SHA-256 trên `64 MiB`, nhanh hơn **`1.50x`** TCP loopback; `~24 Gbps` streaming thuần) và **Hedged Multi-Path Racing** cắt **`1.99x`** độ trễ đuôi `p99`.

*(Toàn bộ 8 kênh đa cõi dị biệt từ bản v0.5.0 — `GHOST_127`, `LAN_LENGTH`, `TS_V4_1280`, `TS_V6_CHORD`, `HYPERV_MCAST`, `WSL_PERMUTE`, `ICMP_REFLECT`, `LO_V6_JUMBO` — vẫn được giữ nguyên vẹn cho mục đích nghiên cứu qua `send` / `listen` / `connect`.)*

---

## Tổng hợp kết quả đo Trước (TCP chuẩn) vs Sau (CHIMERA-HYPER v1.0)

Kiểm chứng trên Windows 64-bit (`Intel Core i5-11400`: `gfni=true`, `avx2=true`, `avx512f=true`; **`19/19` unit/integration tests PASS trong `24.47s`**):

| Tác vụ đo thực tế | BEFORE — TCP chuẩn | AFTER — CHIMERA-HYPER v1.0 | Tỷ lệ đột phá |
| :--- | :--- | :--- | :--- |
| **Core `GF(256)` 16 MiB Vector** | Python: `86.04 ms` (`1.56 Gbps`) | Rust Intel GFNI: **`2.36 ms` (`56.94 Gbps`)** | **`36.5x`** |
| **Core `32x1360` RLNC Matrix Solve** | Python: `106.77 ms` | Rust Intel GFNI: **`0.72 ms`** | **`149.3x`** |
| **Đồng bộ 30 MB (chèn đầu + sửa 3%) @ 100 Mbps** | `2,523.5 ms` (`99.7 Mbps`, `31.5 MB`) | **`267.7 ms` (`940.0 Mbps` eff., `160 KB`)** | **`9.43x`** (`99.49%` saved) |
| **Mạng WAN rớt 0% / 2% / 5% / 10% (`2 MiB`, `50 ms` RTT)** | `14.59` / `1.78` / `1.04` / `0.64 Mbps` | **`53.94` / `54.44` / `48.31` / `52.96 Mbps`** | **`3.7x` &rarr; `82.53x`** |
| **Lọc `24.6 MB` log (1% match) @ 100 Mbps** | `2,010.9 ms` (`24.6 MB`) | **`65.4 ms` (`248.9 KB`, P0 `38.2 ms`)** | **`30.73x`** (`98.99%` saved) |
| **RPC độ trễ đuôi (80 reqs, jitter + 5% loss)** | Single Path `p99 = 353.6 ms` | **Hedged Multi-Path `p99 = 177.4 ms`** | **`1.99x` giảm `p99`** |
| **IPC nội bộ `64 MiB` Windows (có SHA-256)** | TCP `127.0.0.1`: `70.94 ms` (`7.57 Gbps`) | **Wormhole SHM: `47.30 ms` (`11.35 Gbps`)** | **`1.50x`** |
| **Worst-case: `2 MiB` Random mới 100%, 0% rớt** | `173.9 ms` (`96.5 Mbps`) | `203.1 ms` (`82.6 Mbps`, `1.53%` overhead) | `0.86x` (bỏ phình v0.5) |

---

## Cài đặt & Sử dụng trong công việc hằng ngày

Yêu cầu: **Windows 10/11 (64-bit)**, **Python >= 3.11**, **Rust `cargo`** (để build lõi native zero-dependency).

```powershell
# 1. Build lõi Rust Silicon Core (GFNI/AVX2/FastCDC/Delta/Wormhole)
python scripts\build_native.py

# 2. Cài CLI toàn cục (tùy chọn)
pip install -e . --no-build-isolation

# 3. Kiểm tra phần cứng GFNI + 8 cõi mạng Windows
python -m chimera_tp probe

# 4. BEAM: Đồng bộ thư mục / file qua DNA Vault + GFNI Wire
python -m chimera_tp beam serve --bind 127.0.0.1:9100 --vault .\rx_vault --out-dir .\dest_dir --max-transfers 0
python -m chimera_tp beam send --target 127.0.0.1:9100 --dir .\src_dir --vault .\tx_vault

# 5. WARP: Tăng tốc trong suốt mọi kết nối TCP qua mạng yếu/rớt gói
python -m chimera_tp warp server --bind 0.0.0.0:9200 --forward 127.0.0.1:8080 --est-loss 0.05
python -m chimera_tp warp client --listen 127.0.0.1:7200 --target SERVER_IP:9200 --est-loss 0.05

# 6. PIPE: Lọc dữ liệu lớn ngay trên đường truyền hoặc truyền IPC qua Shared Memory Wormhole
python -m chimera_tp pipe query --file .\app.log --op filter_lines --needle ERROR
python -m chimera_tp pipe wormhole --create JOB1 --file .\dataset.bin

# 7. Chạy toàn bộ 19 bài kiểm thử & bộ benchmark Before-vs-After
python -m unittest discover -s tests -v
python -m chimera_tp bench-hyper
```

---

## Tài liệu chi tiết
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — Kiến trúc Rust Silicon Core (`GFNI`, FastCDC, Odess, Delta, Wormhole), HyperWire, Active Pipe và Warp.
- [docs/EVALUATION.md](docs/EVALUATION.md) — Báo cáo thực nghiệm chi tiết `v0.5.0` và `v1.0.0` (tất cả bài test, soak, và bảng Trước–Sau).
- [docs/ROADMAP.md](docs/ROADMAP.md) — Các mốc đã hoàn thành (`v0.2.0` &rarr; `v1.0.0`) và hướng mở rộng tiếp theo.

---

## Giấy phép
Phát hành theo giấy phép [MIT](LICENSE).
