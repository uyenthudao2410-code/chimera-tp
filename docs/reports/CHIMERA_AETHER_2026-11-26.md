# Aether trên win-desktop và svhome

Ngày 26/11/2026, giờ Việt Nam. Hai tệp đề xuất cung cấp 17 giả thuyết. Phạm vi vận hành do người dùng chọn là giữ phiên hiện tại, chuẩn bị bản sao và kiểm thử trên tài nguyên riêng.

## Outcome

Phần có hiệu quả lớn nhất là gửi các thay đổi sau lần đồng bộ đầu. Với tệp nhị phân thử 80 MiB, sửa 448 byte tạo gói gửi **9.977 byte**. Windows và Linux cùng xác nhận SHA-256 của nội dung khôi phục. Khi hai agent tranh tệp, một lease hợp tác và một worktree tách biệt giữ được nội dung của cả hai cây. Đây là hai cơ chế có thể áp dụng trước khi thay hạ tầng đang chạy. [Số đo và mẫu thô](../../tasks/aether_workstation_2026-11-26.json) · [Kiểm thử hồi quy](../../tests/test_aether_workstation.py)

Đề xuất chuyển dây đã được giải quyết bằng đường xuất đang hoạt động. MSI MP275 E2 ở HDMI 120 Hz và Acer KA272 ở DVI 75 Hz có hai target khác nhau nhưng cùng adapter LUID và PCI NVIDIA GTX 1650. Người dùng cũng xác nhận sơ đồ PhysX. Intel UHD 730 vẫn mã hóa được HEVC qua Quick Sync. [Phép dò DisplayConfig](../../scripts/display_paths.py) · [API của Microsoft](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-querydisplayconfig)

## What I need from you

Không có quyết định nào để sử dụng bản thử. Một đợt chuyển ba cổng hoặc đổi đường dẫn dự án thật cần thời điểm bàn giao riêng theo lựa chọn giữ phiên. Đo hiệu quả AutoCAD cần một bản vẽ đại diện có thể dùng để thử và thao tác có thể lặp lại. Phần di động cần một tuyến mạng thứ hai trên máy Windows.

## What to do first

1. Dùng `python -m chimera_tp aether revision capture "D:\ban-thu\mau.dwg"` trên **bản thử** đã lưu. Lệnh trả SHA-256 của phiên bản. Dùng `revision restore <sha256> <tệp-mới>` để mở hai bản cạnh nhau. Các đường dẫn trong ví dụ là chỗ điền dữ liệu đã chọn.
2. Khi chạy hai agent trong một repo, bọc lệnh bằng `python -m chimera_tp aether lease --repo . --file duong/dan.py -- <lenh-agent>`. Mã thoát 75 báo đang có người giữ khóa. Thêm `--isolate-at <thư-mục-mới>` trước dấu `--` để agent thứ hai chạy ở worktree riêng khi cây hiện tại sạch. Cây có thay đổi chưa commit sẽ yêu cầu thử lại trên cùng cơ sở dữ liệu.
3. Để thử điều phối có kiểm soát, dùng `python -m chimera_tp aether admit --run --remote-root /home/svhome/DEV/chimera-tp`. Lệnh kiểm cú pháp và trả về nơi chạy, cảm biến khả dụng, số tệp và lỗi. Dùng `aether colab --profile T4` để kiểm tài khoản và kế hoạch. Thêm `--run --peer-script <script-đã-có-trên-peer>` sẽ bắt đầu một runtime dùng tài khoản Colab.
4. Dùng `python -m chimera_tp aether --help` và `<nhóm> --help` để xem các lệnh khác. Dữ liệu thử có thể tách bằng `aether --state <thư-mục-riêng>`. Các tính năng ảnh, mã hóa và XLSX dùng nhóm phụ thuộc tùy chọn `aether`. [CLI](../../chimera_tp/platform/aether_cli.py) · [Phụ thuộc](../../pyproject.toml)

## What changed or what was learned

### Bảy đề xuất ban đầu

| Đề xuất | Kết quả trước và sau | Quyết định vận hành |
|---|---|---|
| 1. Zero-Copy Display | Đã xác định cả hai màn trên GTX 1650 bằng target, LUID và PCI. WMI liệt kê hai GPU và hai tần số nhưng không đủ để ghép màn với GPU. | Giữ nguyên dây. Chưa có phép đo PCIe blit hay độ trễ con trỏ để quy lợi ích. |
| 2. Brain Transplant | Biên dịch cùng bốn nguồn, 180 lượt mỗi lần, 4 cặp đảo thứ tự. Trung vị CPU tiến trình con trên Windows **3,2734 s → 0,0625 s**. Thời gian người gọi phải chờ **3,3175 s → 5,4430 s**. H.264 trên Linux đã gửi được 5 khung sang Windows, giải mã đủ 5. | Phù hợp với việc nhường CPU cho người đang dùng máy. Python hai nơi là 3.11 và 3.14. Chromium trên peer trả lỗi `No usable sandbox`, vì thế phiên IDE từ xa chưa đạt nghiệm thu. |
| 3. Socket Phantom | Trên cổng riêng, 12 lượt mỗi cấu hình tới đúng beacon svhome. SSH trực tiếp **266,24 ms**, relay Rust + SSH **256,69 ms**. Relay dùng **0,93 MiB** bộ nhớ riêng, SSH **3,18 MiB**. Dịch vụ systemd thử nghiệm chuyển từ PID 0 sang PID thật và trả HTTP 200 khi có kết nối. | Chưa đủ bằng chứng về tăng tốc. Ba cổng thật vẫn phục vụ phiên hiện tại. Cần kiểm API, dữ liệu và danh tính từng ứng dụng trên peer trước khi đổi cổng. |
| 4. One Chromium | Hai trang thử, 3 cặp đổi thứ tự. Hai cây Edge có trung vị tổng bộ nhớ riêng **821,96 MiB**. Chung một cây còn **451,27 MiB**, giảm **370,69 MiB**. | Dùng chung profile cho các ứng dụng có bản web tương thích. Chưa có số liệu cho sáu ứng dụng thật hoặc lợi ích 15 GiB. |
| 5. MMCSS và RAM disk | Chính luồng gọi đã đăng ký được MMCSS và trả trạng thái thành công. Container cô lập trên svhome có tmpfs **2.147.483.648 byte**, ghi và đọc lại đúng SHA-256 của **8 MiB**. | Chỉ luồng tích hợp trong ứng dụng được hưởng MMCSS. Ổ RAM vừa đo ở Linux. Chưa có RAM disk Windows cho phiên AutoCAD. |
| 6. HDD Extinction | E là HDD SATA, C là NVMe. Đã tạo bản staging riêng cho hai dự án. SQLite đang dùng có bản online riêng, **131.072 byte, 13 bảng**, `quick_check=ok`. | Khi repo hoặc log còn được ghi, hai cây có thể lệch ngay sau khi đồng bộ. Cần đối chiếu cuối ở thời điểm chuyển thật. Kết quả theo từng tệp nằm trong biên bản trên NVMe. |
| 7. Zero-Watt HUD | Cùng Edge, cùng dữ liệu thử, cửa sổ 5 s. Giao diện trước có **431 callback animation và 1 yêu cầu WebGL**. Giao diện cuối có **0 và 0**. Đổi chế độ bằng Tab trên bản cuối cũng ghi **0 và 0**, không có lỗi script. | Đã loại chi phí vòng vẽ quan sát được. Điện năng toàn máy, công suất GPU và P99 ứng dụng chưa được đo trong phép thử này. |

Phần bảo vệ tương tác đặt hồ sơ mặc định trong mã nguồn thành `aether`. Các hành vi tự treo tiến trình, dồn affinity hoặc đặt trần công suất theo chính sách cũ nằm sau lựa chọn `legacy`. Ở lần kiểm trực tiếp cuối, Windows báo 230 tiến trình đọc được cùng affinity `0xFFF`, trần CPU AC/DC đều 100%. Mẫu đầu cũng đã có trần 100% và affinity đầy đủ. Những con số 157–259 tiến trình bị bóp, 8 tiến trình bị treo và xung 4,4 GHz trong tệp đính kèm chưa có phép tái hiện độc lập trong phiên này. [Chính sách HyperDesk](../../chimera_tp/platform/hyper_desk.py) · [MMCSS](https://learn.microsoft.com/en-us/windows/win32/api/avrt/nf-avrt-avsetmmthreadcharacteristicsw)

### Mười đề xuất bổ sung

| Đề xuất | Đường chạy và phép thử | Phạm vi còn mở |
|---|---|---|
| 1. QuickSync-Parasite | `aether frame record/find/replay`. Một ảnh chữ 1.000 × 260 được mã hóa thành **4.724 byte HEVC** bằng `hevc_qsv`. OCR trên svhome nhận ra số 7429. Mã hóa và OCR mất **2,96 s**. Tìm trong một bản ghi đã lập chỉ mục có trung vị **0,871 ms**, 15 lần. Ảnh phát lại đúng kích thước. | Chưa đo 1 FPS liên tục, chỉ mục một tuần, điện năng, sai số OCR bản vẽ hoặc stream tới điện thoại. [Frame journal](../../chimera_tp/platform/frame_notes.py) |
| 2. CAD-Time-Machine | `revision watch` nhận sự kiện thư mục Windows, bắt được trường hợp ứng dụng lưu bằng đổi tên. SQLite lưu chunk FastCDC trung bình mục tiêu 16 KiB và danh mục theo SHA-256. Gói đầy đủ **84.909.373 byte**. Gói delta **9.977 byte** có đúng một chunk mới. SSH cùng kiểm SHA-256 mất **164,77 s → 444,11 ms**. Có thể đọc trước tệp liên quan theo lịch sử với ngân sách byte. | Mẫu là dữ liệu nhị phân có kích thước như bản vẽ. AutoCAD có thể viết lại phần lớn DWG. Watcher cần đang chạy, có thể gộp nhiều lần ghi sát nhau. Chưa kiểm USN replay sau khi tắt máy hoặc thời gian mở xref thật. [Kho phiên bản](../../chimera_tp/platform/file_revisions.py) · [Thông báo thay đổi Windows](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-findfirstchangenotificationw) |
| 3. Immortal-Workspace | `workspace save/restore` lưu tài liệu, URL, thư mục terminal. Một manifest **234 byte** đọc lại đủ 1 tài liệu, 1 URL, 1 terminal. Lệnh mặc định hiển thị danh sách sẽ mở, `--apply` mới mở. | RAM chưa lưu, vị trí cửa sổ, scroll tab và agent đang chạy cần adapter từng ứng dụng. Khôi phục GUI trong 3 s và thu hồi 15 GiB chưa được đo. [Manifest workspace](../../chimera_tp/platform/agent_workspace.py) |
| 4. Git-Hypervisor | Lock của OS nằm trong Git common dir nên các worktree có chung trọng tài. Hai lệnh cùng sửa một tệp đã gây tranh khóa. Worktree tách chứa nội dung mới, cây gốc giữ nội dung cũ. | Agent phải dùng lệnh lease. Cây bẩn cần một base rõ ràng. Xung đột nội dung khi merge và SLA AST 0,2 ms còn mở. [Tài liệu Git worktree](https://git-scm.com/docs/git-worktree) |
| 5. Semantic-LLM-Firewall | Lần đầu trượt cache. Cùng câu hỏi, workspace, principal, provider, model, revision và tham số cho **30/30 hit**, trung vị **0,563 ms**. Đổi model tạo cache miss. Gợi ý FTS chỉ trả câu hỏi liên quan. Đã sửa cache HTTP cho Cookie, biến thể header, `private/no-store` và `Retry-After` dài. | Scope trong kho cục bộ là metadata của người dùng. Muốn phục vụ nhiều tài khoản qua mạng cần xác thực ở lớp ứng dụng. Chưa có số token hay chi phí từ nhà cung cấp. [Kho kết quả](../../chimera_tp/platform/result_reuse.py) · [Quy tắc HTTP](https://www.rfc-editor.org/rfc/rfc9110.html) |
| 6. Headless-Colab-Supercomputer | CLI trên **svhome** đọc được **2.350,14 CU**, **0,00 CU/giờ**, **0 assignment**. Đã kiểm cú pháp `colab run --timeout 180 --gpu T4`. Khi thực thi, CLI được thiết kế để trả VM sau khi script kết thúc. | Lần kiểm này chỉ đọc tài khoản. 180 s là timeout chờ output. Chưa xác nhận được RAM, GPU cấp phát, CU/job hoặc quy tắc nhàn rỗi theo phút thực tế. [Cầu nối CLI](../../chimera_tp/platform/colab_on_peer.py) · [FAQ chính thức Colab](https://research.google.com/colaboratory/faq.html) |
| 7. Thermal-Spillover | Cổng nhận việc mới xét ngưỡng **75 °C trong 60 s**, loại bỏ chuỗi mẫu bị ngắt quá 30 s. Trên máy thật đọc GPU **46,3 °C**, có peer. Job kiểm cú pháp đã chạy trên Linux với **127 tệp, 0 lỗi**. | Hai nguồn WMI Libre/OpenHardwareMonitor không có cảm biến CPU khả dụng trên máy này. Ngưỡng là lựa chọn kỹ thuật. Chưa gây tải để ép máy thật lên ngưỡng hoặc xác nhận xung kéo dài. [Điều phối](../../chimera_tp/platform/work_admission.py) |
| 8. Nocturnal-Possession | Cùng cổng nhận việc dùng khung **22h–6h**, Windows không có tương tác **ít nhất 30 phút**. Thử với đồng hồ và tín hiệu rảnh kiểm soát được cho thấy job nhường ngay trước tệp tiếp theo khi người dùng trở lại. | Job mẫu là kiểm cú pháp chỉ đọc. Chưa lập lịch thường trú, chạy việc suốt đêm, dùng GPU/AVX-512 với tác vụ thực hoặc kích hoạt Sleep. |
| 9. Telepathic-Clipboard | AES-256-GCM và SSH chuyển đúng 26 byte giữa Windows và svhome. Hai lượt gọi SSH gồm gửi và lấy lại mất **3,58 s**. Đã mở lại XLSX và kiểm ô. TXT bảng có cột cũng xuất CSV, JSON, Markdown. Sai khóa, sửa gói và hết hạn đều bị từ chối khi giải mã. | TTL 60 s giới hạn thời điểm nhận. Relay dọn gói hết hạn khi có thao tác tiếp theo. Phía nhận giữ khóa riêng qua kênh trao đổi đã tin cậy. Chưa đo điện thoại hay cam kết xóa tức thì mọi bản sao. [Gói mã hóa](../../chimera_tp/platform/clipboard_parcel.py) |
| 10. Immortal-Bonding | Hai socket UDP loopback gửi **128 KiB**, SHA-256 trùng khi cắt một tuyến sau thế hệ đầu. Cùng bài thử đo **12,38 ms** khi đủ tuyến và **15,47 ms** khi cắt tuyến, 0 reconnect của luồng CHIMERA. Đã thử thêm hai IP nguồn loopback riêng biệt. | Windows chỉ có một adapter vật lý đang hoạt động trong kiểm kê. Chưa có A/B Ethernet + 4G/5G, chuyển mạng của SSH/cuộc gọi hoặc mô hình ngoại tuyến. [Bộ gửi đa tuyến](../../chimera_tp/hyper_wire.py) |

Một bài thử riêng đã tạo **10.000 phiên bản khác nhau** của tệp 256 byte trong **110,51 s**. Lịch sử trả đủ 10.000 mục và khôi phục đúng byte của lần lưu 1, 5.000 và 10.000. Bài thử 80 MiB ở trên đo chi phí cho một lần sửa giữa hai phiên bản. Hai phép đo trả lời hai câu hỏi khác nhau về số điểm khôi phục và chi phí khi tệp lớn. [Số đo kho phiên bản](../../tasks/aether_workstation_2026-11-26.json)

### Hai cây dự án trên NVMe

Bản đối chiếu toàn bộ Chat ghi nhận 29.713 tệp ở bản sao. Trong lúc đọc, bốn tệp mã nguồn thay đổi và một log tiếp tục được ghi. Sau khi đồng bộ thêm, SHA-256 của cả năm đường dẫn trùng với nguồn tại thời điểm kiểm tra riêng. Bản SQLite online đi kèm đã qua kiểm tra toàn vẹn. Việc ghi tệp vẫn tiếp diễn nên bản staging có giá trị theo thời điểm. Biên bản đối chiếu cuối của chính repo Chimera và bản sao Chat được lưu ngoài hai cây để phép kiểm có thể bao gồm cả báo cáo này. [Bộ kiểm từng tệp](../../scripts/verify_nvme_stage.py) · [SQLite Online Backup API](https://sqlite.org/backup.html)

### Hiệu năng toàn máy khi người dùng vẫn làm việc

Hai cửa sổ có 20 mẫu, cách nhau khoảng một giây, bắt đầu lúc 18h25 và 18h48. Các giá trị dưới đây là trung vị. Tải ứng dụng và công việc khác trên máy thay đổi giữa hai cửa sổ nên các số này chỉ mô tả trạng thái quan sát được.

| Bộ đếm Windows | Cửa sổ đầu | Cửa sổ sau |
|---|---:|---:|
| CPU bận | 59,91% | 29,20% |
| Hàng đợi CPU | 13,5 | 20 |
| Bộ nhớ khả dụng | 9.904,5 MiB | 9.272,5 MiB |
| Trang bộ nhớ đọc vào mỗi giây | 482,04 | 231,58 |
| Tổng I/O đĩa mỗi giây | 6.426.429 byte | 3.026.038 byte |
| I/O ổ E mỗi giây | 221.260 byte | 0 byte |

### Hướng triển khai rút ra từ phép đo

Đơn vị nên giao giữa hai máy là **một phiên bản công việc có SHA-256**. Agent giữ lease trong lúc sửa, chốt phiên bản, gửi phần chênh cho peer rồi đối chiếu SHA-256 trước khi tái dùng kết quả. Khi chi phí gửi lần đầu cao, giữ base trên peer làm giảm lượng truyền cho các lần sửa kế tiếp. Với việc nhỏ cần phản hồi ngay, chi phí SSH có thể lớn hơn thời gian xử lý. Đây là đề xuất ghép các cơ chế đã kiểm. Vòng tự động từ sự kiện lưu DWG tới kết quả công việc chưa được nghiệm thu trên ứng dụng thật.

## How sure we are

- **Đã kiểm trực tiếp.** Số đo trước–sau, hiển thị, Colab, số liệu từng lượt Edge/SSH, tình trạng staging và kết quả kiểm thử nằm trong [bằng chứng JSON](../../tasks/aether_workstation_2026-11-26.json). Bộ thử riêng cho các đề xuất mới và bộ thử Linux có thể chạy lại trên fixture. [Bộ đo mở rộng](../../scripts/measure_aether_features.py) · [Bộ thử tài nguyên peer](../../scripts/measure_peer_resources.py)
- **Suy luận.** Delta có khả năng hữu ích cho tệp thường chỉ thay đổi một vùng nhỏ. Dời việc sang peer giúp nhường CPU Windows khi có thời gian chờ. Lợi ích phụ thuộc kiểu lưu tệp, độ ấm của cache, mạng và workload cụ thể.
- **Chưa kiểm trên môi trường sử dụng thật.** AutoCAD P99 khi pan/zoom/save, watt tại ổ cắm, failover di động, phục hồi GUI chưa lưu, idle thực của Colab và đổi cổng hay đường dẫn dự án. Gói Python trong workspace là 18.0.0, hai beacon được quan sát báo 21.0.0. Việc có mã trong workspace chưa xác nhận các daemon đang phục vụ cùng bản mã.
