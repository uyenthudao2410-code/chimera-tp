# CHIMERA-HYPER v7.0.0 — Hướng Dẫn Dễ Hiểu (Cũng Dùng Được Dù Không Chuyên Công Nghệ)

> **Tóm tắt 1 câu:** **CHIMERA-HYPER (`chimera-tp`)** là *"đường cao tốc riêng + bộ trợ lý siêu nhẹ"* nối thẳng **máy tính Windows trước mặt bạn** với **máy chủ Linux đặt ở nhà (chạy 24/7)** thành như một chiếc máy tính liền mạch — **nhanh gấp ~5.5–19 lần**, **chống mất kết nối/nghẽn mạng**, và **cắt mạnh tiền token AI + bảo vệ dữ liệu**.

---

## 1. CHIMERA-HYPER thực sự dùng để làm gì trong đời thực?

Nếu bạn nâng cấp nhiều phiên bản nhưng chưa hình dung bức tranh tổng thể: hãy tưởng tượng bạn đang ngồi ở ngoài (cầm laptop/PC Windows), còn toàn bộ đồ nghề nặng (kho code, AI Relay `Tqouta`, hệ thống săn/giải bounty `Radar`) nằm trên máy chủ ở nhà.

Trước đây, mỗi lần từ Windows chui về máy ở nhà qua VPN thường (như Tailscale relay), mọi thứ giống như **đi qua cầu một làn giữa giờ cao điểm**: mở web chậm nửa giây (`~506 ms`), gửi lệnh SSH khựng từng nhịp (`~1.2 giây`), đổi một dòng nhỏ trong file lớn phải đẩy lại, AI đọc nhầm log là đốt sạch hạn mức token.

**CHIMERA-HYPER sinh ra để giải quyết đúng 3 vấn đề gốc rễ đó:**
1. **Đục một đường hầm thẳng P2P riêng (`~5.8 ms` RTT)** nối trực tiếp hai máy với nhau ở tốc độ gần như mạng LAN trong nhà, mã hóa toàn bộ.
2. **Giảm tối đa lượng dữ liệu & token phải chạy qua mạng** (chỉ truyền phần thay đổi, nén dữ liệu trước khi đi dây, lọc log ngay tại máy chủ rồi mới trả kết quả, soi sẵn đúng file cần sửa tốn `0` token AI).
3. **Siêu nhẹ ("Zero-Weight"):** toàn bộ phần mềm chạy ngầm 24/7 trên Windows chỉ tốn **`32.79 MB` RAM** và trên Linux chỉ **`44.40 MB` RAM** — nhẹ hơn cả một tab Chrome/Edge bình thường (giới hạn an toàn đặt ở `80 MB`).

---

## 2. Năm lợi ích thực tế đang âm thầm chạy giúp bạn 24/7

Đây là những thứ đang trực tiếp phục vụ bạn mỗi ngày ngay lúc này:

### 1) Đường truyền thẳng `~5.8 ms` — Mọi thao tác về nhà mượt như ngồi cạnh máy
- Mở kết nối AI Relay `Tqouta` từ Windows về nhà qua cổng `127.0.0.1:12550`: phản hồi chỉ khoảng **`36.6–53.3 ms`** thay vì **`506.6 ms`** qua Tailscale HTTPS — **nhanh hơn `9.5 lần`**.
- Mở web quản lý / API nội bộ qua hầm (`127.0.0.1:9789`): **nhanh hơn tới `19.26 lần`**; mở cửa sổ dòng lệnh SSH (`cổng 2222`): **nhanh hơn `5.55 lần`**.

### 2) Bảng điều khiển & Duyệt file máy chủ ngay trên trình duyệt Windows
Không cần nhớ lệnh Linux hay cài phần mềm FTP rườm rà:
- Mở **`http://127.0.0.1:9780`** để xem toàn bộ sức khỏe 2 máy, log lỗi, bật tìm kiếm và chạy kiểm tra chỉ bằng 1 nút bấm.
- Mở **`http://127.0.0.1:9788/dav/`** ngay trên Chrome/Edge để duyệt thư mục máy chủ, bấm xem file `.patch` kết quả như đang mở một trang web/ổ đĩa bình thường.
- Có sẵn **Drop-Portal** (quăng nhanh đoạn chữ, ảnh, file giữa Windows ↔ Linux không cần gửi qua Zalo/Telegram/Google Drive) và **Ghost-PTY** (cửa sổ dòng lệnh giữ phiên: lỡ rớt Wi-Fi, kết nối lại vẫn còn nguyên màn hình đang chạy dở).

### 3) Tiết kiệm tiền & chống "đốt token" cho `Radar` và `Tqouta`
- **Bản đồ phẫu thuật 0 token (`Surgical Map`):** Thay vì để AI tự mò đọc hàng chục file tốn hàng nghìn token, CHIMERA quét chớp nhoáng kho code trong **`71.89 ms` (`0` token)** và khoanh gọn từ **`54` file (`390.4 KB`) xuống còn `4.1 KB` (`-98.95%`)** đúng ngay chỗ cần sửa.
- **Cầu dao ngắt vòng lặp đốt token (`Burn-Loop Circuit Breaker`):** Tự soi log của `Radar`; nếu thấy AI kẹt vào một lỗi lặp đi lặp lại không tiến triển (`13` workspace quét mất `10.85 ms`), hệ thống lập tức ngắt phanh để tránh cháy quota.
- **Trọng tài điều phối (`Quota Arbiter`):** Tự theo dõi `Tqouta` (`76.62%` tỉ lệ cache) và tự hạ/nâng tốc độ giải (`TURBO` / `BALANCED` / `ECO_SURVIVAL`), đồng thời **che sạch toàn bộ địa chỉ email (`0` rò rỉ)**.
- **Duyệt kèo sẵn nộp trong 5 giây:** Gom các workspace đã có `solution.patch` ra thành danh sách click-là-xem.

### 4) Két sắt "xé mảnh nhiễu trắng" bảo vệ dữ liệu (`GF(256)`)
- Đóng gói trạng thái `Tqouta` + dữ liệu `Radar` (`25.0 MB` nén còn `5.38 MB`) rồi trộn toán học thành các mảnh nhiễu trắng tuyệt đối (`8.00 bits/B`).
- Hiểu đơn giản như chia mật mã thành 3 phong bì: **nhặt được 1 phong bì hoàn toàn vô nghĩa**, mất 1 máy vẫn lấy 2 phong bì còn lại ghép nguyên vẹn bản gốc; toàn bộ việc nặng chạy trong tiến trình phụ nên không làm phình RAM của daemon chính.

### 5) Bác sĩ trực máy chủ (`CHIMERA-MEDIC` & `Sentinel`)
- Tự theo dõi dịch vụ, soi vết lỗi bất thường trong log và cung cấp sẵn các nút sửa lỗi an toàn có chụp bản sao lưu trước khi đụng vào cấu hình.

---

## 3. Giải mã 14 nâng cấp `v7.0 OMEGA-FABRIC` bằng ngôn ngữ đời thường

Phiên bản `v7.0` bổ sung **14 động cơ công nghệ cốt lõi** ở tầng giao thức bên dưới ([docs/MOONSHOT_VAULT.md](docs/MOONSHOT_VAULT.md)) giúp hệ thống **tự chống nghẽn, tự chữa lành, chạy được ngay cả khi mạng bị bóp hay đứt một đường**, cụ thể chia thành 4 nhóm dễ hiểu:

### Nhóm A — Mạng siêu bền, gộp đường truyền & qua mặt bóp băng thông
1. **Đường truyền mật mã lõi Rust/C11 & Card mạng ảo (`Virtual NIC + ChaCha20`):** Đóng gói và mã hóa dữ liệu kiểu `IPv4/ChaCha20` bằng ngôn ngữ tốc độ cao sát phần cứng. *Lưu ý trung thực về quyền máy:* hệ thống tự dò driver (`Wintun` trên Windows, quyền nâng cao trên Linux); khi máy bạn đang chạy ở quyền người dùng thường không dùng quyền Admin/Root, CHIMERA tự chuyển mượt sang chế độ an toàn không cần cài driver kernel.
2. **Gộp nhiều đường mạng (`Multi-ISP RLNC Bonding`):** Khi bạn dùng song song Wi-Fi + 4G phát từ điện thoại, dữ liệu được trộn phương trình đi cả hai đường. Thử nghiệm giật đứt đột ngột 1 đường giữa chừng: **độ trễ chuyển mạch `0 ms`** (sống sót qua 5 gói rơi liên tiếp trong `2.25 ms`, không bị rớt kết nối như mạng thường).
3. **Ngụy trang đa hình (`Polymorphic QUIC/WebRTC`):** Gặp mạng công ty hoặc Wi-Fi công cộng chặn/bóp lưu lượng lạ, CHIMERA tự "thay áo" gói tin giả dạng y hệt cuộc gọi WebRTC (`270 B`) hoặc luồng HTTP/3 QUIC để đi lọt.
4. **Trung chuyển trộn mã trên đường bay (`RLNC Recoding-in-Flight`):** Máy trung gian có thể pha trộn lại các gói tin bị rơi rớt ngay trên đường truyền (`0.962 ms`) **mà không bao giờ giải mã xem được nội dung thật** bên trong.

### Nhóm B — Đồng bộ thông minh: Không bao giờ gửi lại những gì bên kia đã có
5. **Vá từng mẩu `4 KB` (`Ghost-Block`):** Sửa một chút trong file lớn (`26,624 B`), thay vì tải lại cả file như cách cũ, CHIMERA chỉ gửi đúng miếng `4 KB` bị đổi — thu gọn còn **`95 B` (tiết kiệm `99.64%` lưu lượng)**. Trên máy chưa bật ổ đĩa ảo `WinFsp`/`FUSE`, hệ thống tự động chạy ở chế độ đồng bộ theo khối cực nhẹ.
6. **Kho phân tán tự vá (`Self-Healing Mesh K=3, N=5`):** Chia dữ liệu ra 5 nơi (mỗi mảnh vô nghĩa nếu đứng một mình). Nếu 1–2 nơi hỏng ổ cứng, chỉ cần **3 nơi còn sống** tự vá lại thành mảnh mới thay thế trong **`0.05 ms`** mà không cần gom toàn bộ bản gốc về một chỗ.
7. **Đồng bộ mù một chiều không cần hỏi qua lại (`0-RTT Slepian-Wolf`):** Bình thường 2 máy phải nhắn tin hỏi *"Mày đang giữ bản nào? Khác dòng nào?"* mất `1–2` lượt đi về. Nay máy gửi bắn thẳng một "bản tóm tắt toán học" (`3,124 B`) — máy nhận tự đối chiếu với file cũ sẵn có để khôi phục chính xác từng bit dữ liệu mới (**tiết kiệm `56.61%–72.60%` dung lượng chỉ trong 1 lượt gửi**).
8. **Kênh liên lạc ký sinh `$0` (`Parasitic Dead-Drop Mesh`):** Trường hợp xấu nhất là cả VPN lẫn kết nối thẳng đều bị tường lửa chặn, tin nhắn điều khiển vẫn có thể chia nhỏ, xoay vòng ngẫu nhiên theo giờ (`Lehmer`) gửi rải lên 5 kênh công cộng độc lập — **chết mất `2/5` kênh vẫn ghép lại được tin trong `0.37 ms`**.

### Nhóm C — Gửi "robot tí hon" đến tận nơi & Mượn RAM qua dây mạng `5 ms`
9. **Chạy mã hộp cát ngay bên cạnh file gốc (`WASM Active-Pipe AQ03`):** Thay vì kéo cả file log `16,800 B` về máy bạn rồi mới tìm kiếm, Windows chỉ gửi một đoạn mã hộp cát **WebAssembly bé `109 B`** (bị khóa kín không thể đụng file bừa bãi hay vào mạng) sang chạy thẳng trên Linux (`0.72 ms`), đếm xong kết quả rồi mới gửi về mỗi con số.
10. **Mượn RAM nén qua hầm `5 ms` (`Compressed 4 KB Remote RAM`):** Các ô nhớ RAM `4 KB` ít dùng được nén siêu nhỏ (thử nghiệm **`16,384 B` nén còn `843 B`, tiết kiệm `94.85%`**) rồi đẩy thẳng qua đường hầm `5 ms` gửi tạm sang RAM dư trên máy Linux thay vì đẩy xuống ổ cứng chậm chạp (`REMOTE_HTTP`, đo thực tế giữa 2 máy hết `163.05 ms`).

### Nhóm D — Nén nhỏ hơn chuẩn `zip`, giữ chữ nét khi mạng lag & bảo mật tương lai
11. **Nén thông minh đoán trước dữ liệu (`Order-2 PPM Range Codec`):** Đã được học sẵn quy luật của các dòng log/JSON kỹ thuật, nén **`16,559 B` xuống còn `608 B`** — **nhỏ hơn cả mức nén cao nhất `zlib-9` (`650 B`) thêm `6.46%`**, chạy bit-y-hệt trên cả hai máy.
12. **Hiển thị màn hình chống đứng chữ (`UEP-RLNC Display`):** Khi mạng chập chờn rơi `15%` gói tin (ngồi xe, thang máy), phần chữ đọc và con trỏ chuột được ưu tiên bảo vệ gấp 3 lần nền xung quanh — tỷ lệ chữ giữ sắc nét tăng từ **`11/25` (44%) lên `25/25` (100%)**.
13. **Khóa hậu lượng tử + Ngụy trang có ích (`Hybrid MLWE+X25519 & Chaff-RLNC`):** Kết hợp mật mã cổ điển và lưới toán học hậu lượng tử (`672 B`), đồng thời biến các gói "nhiễu đánh lạc hướng kẻ nghe lén" thành các gói mang **mã sửa lỗi thật** (tự vá luôn `3/12` gói bị rơi miễn phí).
14. **Giao thức tự tiến hóa gen (`Self-Mutating Genetic Wire`):** Thay vì dùng mãi 1 cấu hình cứng, bộ lõi tự thử nghiệm kích thước gói, tỉ lệ dự phòng, nhịp gửi qua 14 thế hệ (nâng điểm thích nghi từ **`0.01 -> 87.007`**) rồi nhét gọn cấu hình tối ưu vào phần đầu gói xác nhận chỉ **`12 B`**.

---

## 4. Bảng tóm tắt Trước & Sau đo thực tế trên hệ thống thật

Tất cả số liệu dưới đây được đo trực tiếp giữa **PC Windows** (`Rust GFNI/AVX-512F`, Python 3.11) và **Linux Home Server** (`C11 AVX2`, Python 3.14.4) nối qua `PHANTOM_5MS_DIRECT` (**`5.8 ms`** RTT):

| Hạng mục kiểm chứng | Trước đây (Cách thông thường) | Sau khi có CHIMERA-HYPER v7.0.0 | Đánh giá |
| :--- | :--- | :--- | :---: |
| **Bộ nhớ RAM chạy ngầm 24/7** | Tốn nặng nếu chạy app desktop | **`32.79 MB`** (Win) • **`44.40 MB`** (Linux) — dưới trần `80 MB` | Đạt |
| **Độ khớp lõi Windows ↔ Linux** | Dễ lệch giữa 2 hệ điều hành | **Khớp từng bit SHA-256 (`4/4` hàm native lõi Rust = C11)** | Đạt |
| **Tốc độ gọi AI `Tqouta` về nhà** | `506.63 ms` qua HTTPS chuẩn | **`36.63 ms` min / `52.68–53.26 ms` TB** (`:12550`) | Nhanh hơn `9.5x` |
| **Soi đường dẫn code (`Radar`)** | AI tự mò, tốn nhiều lượt token | **`390.4 KB -> 4.10 KB` (`-98.95%`)** trong `71.89 ms`, `0` token | Tiết kiệm triệt để |
| **Độ bền toàn bộ 14 ý tưởng v7.0** | Chạy đơn lẻ từng lớp rời rạc | **Đạt `14 / 14`** khi kiểm chuẩn live trong **`469.81 ms`** | Đạt 100% |
| **Vá file 4 KB / Đồng bộ 0-RTT** | Tải lại cả file / hỏi qua lại 2 vòng | Ghost-Block **`-99.64%`** (`95 B`) • Slepian-Wolf **`-56.61%..72.6%`** | Nhanh, ít băng thông |
| **Gửi mã WASM / Mượn RAM `5 ms`** | Kéo log thô / Swap ổ đĩa | WASM **`109 B` chạy trên Linux mất `0.72 ms`** • RAM **`-94.85%`** | Chạy xuyên máy thật |
| **Kiểm thử tự động toàn dự án** | — | **`53 / 53` bài test PASS** trên cả Windows (`65.3s`) và Linux (`45.7s`) | Ổn định cả 2 đầu |

Chi tiết kỹ thuật sâu hơn xem thêm tại [docs/EVALUATION.md](docs/EVALUATION.md), [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) và [docs/ROADMAP.md](docs/ROADMAP.md).

---

## 5. Cách dùng hàng ngày (Không cần biết lập trình)

Khi hai máy đã bật sẵn dịch vụ chạy ngầm, bạn chỉ cần mở trình duyệt trên Windows:

- **Bảng điều khiển trung tâm (Xem RAM, log, bấm test 14 công nghệ v7.0):**
  👉 Mở trình duyệt vào **`http://127.0.0.1:9780`** -> chọn tab **v7.0 OMEGA-14 Lab** hoặc **Radar + Tqouta Synergy**.
- **Xem thư mục & kết quả file patch trên máy chủ ở nhà:**
  👉 Mở trình duyệt vào **`http://127.0.0.1:9788/dav/`**.

Nếu bạn muốn kiểm tra nhanh bằng dòng lệnh (`PowerShell` hoặc `Terminal`):

```bash
# Chạy kiểm tra thực tế toàn bộ 14 công nghệ qua đường hầm 5 ms
chimera-tp omega bench --peer-http http://127.0.0.1:9780

# Xem trạng thái driver/phần cứng cả 2 đầu và thử gửi mã WASM sang máy nhà
chimera-tp omega status --peer-http http://127.0.0.1:9780
chimera-tp omega wasm --peer-http http://127.0.0.1:9780

# Xem trạng thái Radar + Tqouta (đã che sạch email)
chimera-tp synergy status --peer-http http://127.0.0.1:9780

# Tự chạy toàn bộ 53 bài kiểm tra tự động
python -m unittest discover -s tests -v
```

### Tự cài đặt từ đầu trên máy mới (nếu cần)
```bash
python scripts/build_native.py
chimera-tp ops-init --node-name peer-linux --role server --bind 0.0.0.0:9780 --watched-file /path/to/app.log --allow-root /path/to/dev
chimera-tp ops-init --node-name win-desktop --role controller --peer-name peer-linux --peer-ipv4 <PEER_TAILSCALE_IPV4> --peer-ipv6 <PEER_TAILSCALE_IPV6> --bind 127.0.0.1:9780
chimera-tp daemon
```
Mẫu file cấu hình nằm tại [docs/ops_config.example.json](docs/ops_config.example.json) (cấu hình thực tế trên máy được lưu riêng tại `~/.chimera_ops/`).

---

## 6. Nguyên tắc An toàn & Quyền riêng tư

- **Không lộ thông tin nhạy cảm:** Toàn bộ phản hồi quota đều che địa chỉ email và nhãn tài khoản cá nhân; kiểm tra rà soát mã nguồn xác nhận **0 rò rỉ IP thật hay khóa bí mật** trước khi đồng bộ lên kho lưu trữ.
- **Khóa vùng truy cập (`Containment`):** WebDAV `/dav/`, bộ đọc file, WASM hộp cát và `CHIMERA-MEDIC` chỉ được phép chạm vào đúng các thư mục đã cấp phép trong `allowed_query_roots`, chặn ghi đè `.git` và giới hạn tài nguyên CPU/RAM để bảo vệ máy chủ chạy 24/7.
- **Khuyến nghị triển khai:** Luôn đặt dịch vụ đằng sau localhost hoặc mạng riêng ảo đã xác thực (như Tailscale/WireGuard), không mở thẳng cổng điều khiển ra Internet công cộng.
