# Kiến trúc kỹ thuật CHIMERA-TP (v0.2.0)

## 1. Mô hình phân lớp

CHIMERA-TP tách biệt **Control Plane** (bắt tay phiên trên `::1`), **Coding & Chaos Plane** (GF(256) RLNC + Logistic Map), và **Polymorphic Physical/Virtual Lanes** (8 cơ chế điều chế khác nhau trên từng giao diện Windows).

### 1.1 Trường hữu hạn $GF(2^8)$ & Phun tuyến tính (RLNC)
- **Đa thức bất khả quy**: $P(x) = x^8 + x^4 + x^3 + x + 1$ (`0x11B`).
- **Phần tử sinh nguyên thủy**: `0x03` (chu kỳ đầy đủ `255`, tạo toàn bộ $\mathbb{F}_{2^8}^*$; không dùng `0x02` vốn chỉ có bậc `51` modulo `0x11B`).
- **Tăng tốc vector**: dựng sẵn bảng `MUL_BYTES[256]` dài 256 byte cho phép nhân vô hướng cả khối qua `bytes.translate()` ở tốc độ C, kết hợp phép `XOR` trên số nguyên lớn (`int.from_bytes(..., "little")`).
- **Kích thước giọt mặc định**: `20` byte = `[uint16 droplet_id][16B coded_block][uint16 crc16]`.
- **Keyed CRC-16/CCITT (v0.2.0)**: CRC được tính trên `rlnc_seed + body` thay vì chỉ `body`, giúp loại bỏ triệt để gói trễ từ các phiên trước đó lọt sang phiên mới mà không tốn thêm byte trên dây.

### 1.2 Bộ lập lịch hỗn loạn (Chaos Lane Scheduler)
- Khởi tạo trạng thái $x_0 \in (0.11, 0.89)$ từ hash `blake2s(seed)`.
- Mỗi bước phát giọt cập nhật $x_{n+1} = 3.99 \cdot x_n (1 - x_n)$ (tự re-seed nếu tiệm cận điểm bất động hoặc biên), chọn kênh kế tiếp theo $x_{n+1}$, đồng thời áp đặt cửa sổ phủ vòng (rolling-window coverage) đảm bảo mọi kênh sống đều nhận tải trong mỗi chu kỳ $N$ bước.

---

## 2. Đặc tả 8 kênh truyền dị biệt

| Kênh | Địa chỉ & Giao thức nền | Cấu trúc gói / Cơ chế thu | Giới hạn cố hữu |
| :--- | :--- | :--- | :--- |
| **`GHOST_127`** | `127.0.0.1` UDP (`127.0.0.0/8`) | Bind 10 cổng nhận (`droplet_size / 2` cặp). Bên gửi đóng `tag4 (4b) + b0 (8b) + b1 (8b)` thành 20 bit ánh xạ vào `127.o1.o2.o3` (`o1,o2 in 1..128`, `o3 in 1..64`) và gửi **`b""` (0 byte payload)**. | Tốn syscall mở/đóng socket nguồn; vòng tag 4-bit (16 slot). |
| **`LAN_LENGTH`** | NIC LAN IPv4 UDP | Bind `droplet_size` cổng nhận. Gửi `os.urandom(64 + (tag_mod << 8) + byte)` (`tag_mod in 0..4`, tổng dài `64..1343 B <= 1472 B`). Bên nhận **bỏ qua 100% nội dung payload**, chỉ đọc `len(data) - 64`. | Phóng đại băng thông cực lớn (~`311x` ở 384 B). |
| **`TS_V4_1280`** | Tailscale IPv4 UDP | Khung `b"TS" + uint32 frame_tag + uint16 len + (droplet ^ keystream)`, kẹp chặt `<= 1200 B` để tránh phân mảnh qua MTU 1280 của WireGuard/Tailscale. | Không giấu siêu dữ liệu bằng kênh phụ; dùng để giữ thông lượng ổn định. |
| **`TS_V6_CHORD`** | Tailscale ULA IPv6 UDP | Bind 16 cổng "nốt nhạc" + 1 cổng barline. Với mỗi từ 16-bit `w`, gửi header 3B `(tag8, word_idx, popcount)` vào mọi cổng có bit `= 1`, sau đó gõ cổng barline. Chỉ chốt từ khi đủ cả barline lẫn `len(bits) == popcount`. | Số gói tỉ lệ với Hamming weight + barline (~767 gói / 384 B). |
| **`HYPERV_MCAST`** | Hyper-V Default Switch IPv4 Multicast | 16 socket tham gia `239.255.13.1..16` trên 16 cổng riêng biệt. Đặt `IP_MULTICAST_TTL = 0` và `IP_MULTICAST_LOOP = 1`. Mỗi nibble (4 bit) gửi spark 2B `(tag8, nibble_idx)` vào nhóm tương ứng. | Tốn 2 gói trên mỗi byte dữ liệu; giới hạn nội bộ host do `TTL = 0`. |
| **`WSL_PERMUTE`** | WSL2 vSwitch IPv4 UDP | Biểu diễn `rank = (byte << 1) | (idx & 1)` trong `[0..511] < 6! = 720` thành hoán vị 6 phần tử qua phép song ánh Lehmer, phát 6 gói 3B theo đúng thứ tự đó. Kiểm tra parity `rank & 1 == idx & 1` để phát hiện đảo thứ tự. | Tốn 6 gói cho mỗi byte (1,080 gói / 384 B). |
| **`ICMP_REFLECT`** | `127.0.0.1` Raw ICMP (`IPPROTO_ICMP`) | Bên gửi tạo ICMP Echo Request (`type=8`, `id=session_icmp_id`, body `b"CH" + kind + len + droplet`). Kernel Windows tự phản xạ thành Echo Reply (`type=0`) về socket raw của bên nhận. | Đòi hỏi quyền Administrator để mở `SOCK_RAW`. |
| **`LO_V6_JUMBO`** | `::1` IPv6 UDP | Gửi các siêu khung tối đa `58,000 B`: `b"JM" + uint32 tid + uint16 idx + uint16 total + masked_chunk` với `SO_RCVBUF/SO_SNDBUF = 4 MiB`. | Chưa có ARQ/FEC nội tại trên các mảnh bulk 58 KiB. |

---

## 3. Chế độ `HOLOGRAPHIC-SPLIT` & Khóa Topology

1. Bên gửi sinh `holo_key` ngẫu nhiên 256-bit và lấy `topology_fingerprint` (SHA-256 của tập bộ điều hợp, họ địa chỉ, IP, MTU trên máy).
2. Sinh luồng khóa OTP từ `blake2b(holo_key || topology_fingerprint)` để che toàn bộ khối bulk, đẩy entropy dây lên ~`7.999+ bits/byte`.
3. Khối dữ liệu đã che chạy tốc độ cao qua `LO_V6_JUMBO` (`::1`), trong khi **Capsule 72 byte** (`transfer_id + orig_len + holo_key + payload_sha256`) đi qua `PURE-METAMORPHIC` trên các kênh dị biệt.
4. Nếu một máy nhận có `topology_fingerprint` khác dù chỉ 1 ký tự hex, khóa giải mã sai lệch hoàn toàn và kiểm tra SHA-256 bị từ chối.

---

## 4. Cô lập phiên & Vòng đời luồng RX (v0.2.0)

- Trước khi trả `RDY!` cho mỗi phiên mới, `ChimeraReceiver._init_transfer_session` gọi `lane.reset_state()` trên toàn bộ kênh để xóa slot lắp ghép dở dang và xả sạch gói tồn đọng trên socket non-blocking.
- Khóa `lane._lock` chỉ giữ khi thao tác bộ đệm cục bộ của lane và được giải phóng **trước khi** gọi `_emit_droplet()` (tránh đảo khóa với `ChimeraReceiver._lock`).
- Lỗi giải nén `zlib.error` được bắt bên trong `_on_droplet_received` để báo `sha256_match = False` về cho bên gửi mà không làm sập các luồng RX nền.
