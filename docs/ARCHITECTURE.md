# Kiến trúc kỹ thuật CHIMERA-TP (v0.5.0)

## 1. Mô hình phân lớp

CHIMERA-TP tách biệt **Control Plane** (bắt tay `STRT`/`RDY!`/`GACK`/`SOLV`/`JCHK`/`JNCK`/`JOK!` trên `::1`), **Segmented Coding & Parallel Chaos Plane** (GF(256) RLNC + Logistic Map + Worker Pool theo lane), và **Polymorphic Physical/Virtual Lanes** (8 cơ chế điều chế khác nhau trên từng giao diện Windows).

### 1.1 Trường hữu hạn $GF(2^8)$ & Segmented RLNC ($O(K)$ Scaling)
- **Đa thức bất khả quy**: $P(x) = x^8 + x^4 + x^3 + x + 1$ (`0x11B`), **phần tử sinh nguyên thủy `0x03`** (chu kỳ `255`).
- **Tăng tốc vector**: bảng `MUL_BYTES[256]` qua `bytes.translate()` ở tốc độ C + big-int `XOR`.
- **Segmented Multi-Generation RLNC (v0.5.0)**:
  - Chia dữ liệu thành nhiều thế hệ (mặc định `gen_size = 32` khối = `512 B/generation`, tối đa `64` thế hệ = `32 KiB` dữ liệu không nén).
  - Nếu `num_gens == 1`: giữ nguyên header 16-bit `droplet_id`.
  - Nếu `num_gens > 1`: đóng gói `wire_id = ((gen_id & 0x3F) << 10) | (local_id & 0x3FF)`, dẫn xuất seed riêng cho từng thế hệ qua `blake2s(rlnc_seed + uint16(gen_id))` và tính Keyed CRC-16 trên `rlnc_seed + body`.
  - Khi một thế hệ giải đủ `gk` khối, bên nhận phát `GACK(tid, gen_id)` để bên gửi loại thế hệ đó khỏi `pending_gens` ngay lập tức.
  - Độ phức tạp khử Gauss giảm từ $O(K^3)$ xuống $O((K/G) \cdot G^3) = O(K \cdot 32^2)$ tuyến tính theo $K$.

### 1.2 Bộ lập lịch hỗn loạn & Phát song song theo Lane (v0.4.0)
- **Ba profile hỗn loạn**:
  - `balanced`: phân bổ đều với cửa sổ phủ vòng (rolling-window coverage) đảm bảo mọi kênh đều tham gia.
  - `stealth`: ưu tiên các kênh ẩn dữ liệu thuần metadata (`GHOST_127:4`, `LAN_LENGTH:3`, `TS_V6_CHORD:3`, `HYPERV_MCAST:3`, `WSL_PERMUTE:3`, `TS_V4_1280:1`, `ICMP_REFLECT:1`).
  - `turbo`: ưu tiên kênh độ trễ thấp và khuếch đại dây thấp (`TS_V4_1280:8`, `ICMP_REFLECT:8`, `GHOST_127:2`, các kênh còn lại `1`).
- **Per-Lane Parallel Dispatch**: Mỗi kênh sống sở hữu đúng 1 thread worker TX và `queue.Queue(maxsize=2)`. Kiến trúc 1-worker-per-lane đảm bảo thứ tự `frame_tag` và socket nội bộ của lane luôn tuần tự an toàn, trong khi các lane chậm không làm nghẽn lane nhanh.

---

## 2. Đặc tả 8 kênh truyền dị biệt

| Kênh | Địa chỉ & Giao thức nền | Cấu trúc gói / Cơ chế thu | Đặc tính chính |
| :--- | :--- | :--- | :--- |
| **`GHOST_127`** | `127.0.0.1` UDP (`127.0.0.0/8`) | Bind 10 cổng nhận; đóng `tag4 + b0 + b1` vào IP nguồn `127.o1.o2.o3`, gửi **`0 B` UDP payload**. | 0 byte payload trên dây; độ trễ cao do tạo/đóng socket nguồn. |
| **`LAN_LENGTH`** | NIC LAN IPv4 UDP | Bind `droplet_size` cổng nhận. Gửi `os.urandom(64 + (tag_mod << 8) + byte)` (`64..1343 B`). Bên nhận **bỏ qua 100% nội dung payload**. | Miễn nhiễm đảo 100% bit payload; phóng đại băng thông `~310x`. |
| **`TS_V4_1280`** | Tailscale IPv4 UDP | Khung `b"TS" + uint32 frame_tag + uint16 len + (droplet ^ keystream)` ép `<= 1200 B`. | Nhanh nhất (`~0.1–0.15 ms/giọt`), khuếch đại chỉ `1.31x`. |
| **`TS_V6_CHORD`** | Tailscale ULA IPv6 UDP | 16 cổng note + 1 cổng barline. Mỗi từ 16-bit gửi header 3B `(tag8, word_idx, popcount)` cho từng bit `1`, chốt bằng barline. | Không chứa bit dữ liệu trong payload (`~109x` wire amp). |
| **`HYPERV_MCAST`** | Hyper-V Default Switch Multicast | 16 nhóm `239.255.13.1..16` trên 16 cổng, `IP_MULTICAST_TTL = 0`, spark 2B theo nibble. | Ràng buộc host-local tuyệt đối nhờ `TTL=0`. |
| **`WSL_PERMUTE`** | WSL2 vSwitch IPv4 UDP | Ánh xạ `(byte << 1) | (idx & 1)` thành hoán vị 6 phần tử ($S_6$ Lehmer), phát 6 gói 3B theo thứ tự. | Tự phát hiện đảo thứ tự qua bit parity `idx & 1`. |
| **`ICMP_REFLECT`** | `127.0.0.1` Raw ICMP (`IPPROTO_ICMP`) | Echo Request `type=8` (`id=session_icmp_id`) -> Kernel Windows phản xạ `type=0`. | Khuếch đại `1.22x`, đòi hỏi quyền Administrator. |
| **`LO_V6_JUMBO`** | `::1` IPv6 UDP | Siêu khung `JM` tối đa `58,000 B` kèm `CRC-32` + gói chẵn lẻ `JP` (Stripe XOR `4:1`) + `JCHK`/`JNCK`/`JOK!` Selective NACK. | Đạt `85+ Mbps` trên `8 MiB` và tự phục hồi khi rớt 25% chunk. |

---

## 3. Chế độ `HOLOGRAPHIC-SPLIT`, Khóa Topology & Vận hành 2 tiến trình

1. Khối dữ liệu lớn được che bằng `blake2b(holo_key || topology_fingerprint)`.
2. Khối che chia thành các siêu khung 58 KiB qua `LO_V6_JUMBO` kèm gói parity XOR theo từng stripe `4` chunk (`JP`). Nếu mất `1` chunk trong stripe, bên nhận khôi phục tức thì ở **0 RTT**; nếu mất `>= 2` chunk trong cùng stripe, cơ chế `JCHK -> JNCK(missing)` yêu cầu phát lại đúng các mảnh thiếu.
3. Capsule khóa 72 byte (`is_capsule=True`) truyền qua `PURE-METAMORPHIC` trên 7 kênh dị biệt.
4. Khi chạy tách 2 tiến trình (`chimera-tp listen` và `chimera-tp connect`), `ChimeraReceiver` ghi `offer.json` nguyên tử qua `os.replace()` và đồng bộ hoàn tất qua hàng đợi `_incoming_queue` + thông điệp mạng `SOLV`/`JOK!`.
