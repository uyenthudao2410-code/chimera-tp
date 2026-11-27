# HỌC THUYẾT HỢP NHẤT CHIMERA-ONE (THE GRAND UNIFICATION DOCTRINE)

*Phiên bản: `1.0` · Ngày chốt: `26/11/2026` · Phạm vi: Toàn bộ hệ sinh thái `CHIMERA-TP` (`win-desktop` ⇄ `svhome` ⇄ `Colab Pro`).*

---

## Điều 0 — Bản Chất Thực Thể & Ranh Giới Tồn Tại

**CHIMERA không phải là kho sưu tầm `107+` công cụ rời, không phải phần mềm "bóp CPU Windows", và không phải hệ thống "đẩy rác từ máy khỏe sang làm hại máy yếu".**

**CHIMERA-ONE** là **Một Thực Thể Hạ Tầng Đồng Sinh Duy Nhất (`Sovereign Symbiotic Infrastructure Organism`)** vận hành thuần túy ở tầng nguyên thủy (truyền tải, lưu trữ, lập lịch, bảo mật, bộ nhớ chung, quan sát) nhằm tối ưu đồng thời:

$$\min \;\Big( \text{P99\_UI}_{\text{win}} \;+\; \text{EndToEnd\_Wait}_{\text{job}} \;+\; \text{Thermal\_Wear}_{\text{win+svh}} \;+\; \text{SSD\_Write}_{\text{win+svh}} \;+\; \text{RAM\_Waste}_{\text{cluster}} \;+\; \text{CU\_Cost}_{\text{colab}} \Big)$$

Mọi ứng dụng nghiệp vụ (`AutoCAD`, `Radar`, `Tqouta`, `AI Coding Agents`, công cụ văn phòng) chỉ cắm vào **1 Cổng Neo Duy Nhất (`:9780` / `:9781` / `autoload.pth`)** và kế thừa toàn bộ sức mạnh mà không nhúng logic nghiệp vụ vào lõi hạ tầng.

---

## I. Bảy Định Luật Bất Biến (The 7 Invariant Laws)

Mọi thiết kế, dòng mã, chính sách tự động và mọi AI Coding Agent làm việc trong kho này **bắt buộc tuân thủ tuyệt đối 7 định luật sau**:

1. **Luật 1 — Triệt Tiêu Trước Khi Dịch Chuyển (`Eliminate Before Offload`)**
   - Tải sinh ra do trùng lặp hoặc lãng phí (nhiều nhân Chromium song song, service rảnh giữ worker chết, Cross-GPU PCIe Blit, đọc/biên dịch/gọi API trùng lặp) phải bị **xóa sổ ngay tại gốc** trước khi nghĩ tới việc đẩy qua mạng.
   - Đẩy tải thừa sang máy khác là thất bại kiến trúc, không phải tối ưu.

2. **Luật 2 — Tuyệt Đối Không Bóp Nhân Hệ Điều Hành (`Zero-Choke Kernel Law`)**
   - **CẤM mặc định** mọi hành vi can thiệp cưỡng bức từ Ring 3 chống lại nhân Windows: cắt affinity cứng (`0xF00`), bật `EcoQoS` tràn lan, hạ `PROCTHROTTLEMAX < 100%` (tắt Intel Turbo Boost), gọi `NtSuspendProcess` trên tiến trình giữ khóa IPC/Shell, hoặc gọi `EmptyWorkingSet` khi RAM vật lý không cạn.
   - Chỉ sử dụng cơ chế hợp tác chính chủ OS: `MMCSS` cho luồng hợp tác, hiển thị `Zero-Copy` đúng topology Win32 `EnumDisplayDevicesW` / `QueryDisplayConfig`, `Prefetch` có kiểm soát, và phân tầng lưu trữ NVMe / Dev Drive.

3. **Luật 3 — Đồng Sinh & Cầu Chì Bảo Vệ Nút Yếu (`Mutual Homeostasis & Peer Guard`)**
   - Nút yếu chạy 24/7 (`svhome`: 2C/4T 15W, 10 GiB RAM, 109 GB SSD) phải được bảo vệ **nghiêm ngặt hơn** nút mạnh (`win-desktop`: 6C/12T 4.4 GHz, 32 GiB RAM, GTX 1650).
   - Mọi tác vụ khách gửi tới `svhome` phải qua **1 cửa duy nhất** (`peer_guard` + `work_admission` + `systemd cgroup v2`): giữ tối thiểu **`2.5 GiB` RAM khả dụng**, `load1 <= 1.8`, nhiệt CPU `< 70°C`, đĩa trống `>= 15 GB`, và không làm vỡ `P95` dịch vụ thật (`Radar`, `Tqouta`, tunnel). Vượt bất kỳ ngưỡng nào hoặc mất cảm biến → **từ chối nhận việc**, chuyển sang hàng đợi chờ hoặc `Colab Pro` có ngân sách rõ ràng.

4. **Luật 4 — Đơn Vị Công Việc Xác Thực Bằng Hàm Băm (`Content-Addressed Work Unit`)**
   - Mọi phối hợp xuyên tiến trình, xuyên AI Agent và xuyên máy đều dùng chung **1 đơn vị chuẩn**: `(SHA-256 đầu vào, định danh môi trường/toolchain, khóa File-Lease, biên nhận bất biến)`.
   - Mọi tác vụ thuần có cùng chữ ký đầu vào + môi trường phải được **gộp thực thi (`Singleflight`)** hoặc **tái sử dụng kết quả (`Memoization`)** thay vì chạy lặp; mọi sửa đổi có thể kiểm tra lại và hoàn tác (`File Revisions` / `Workspace Undo`).

5. **Luật 5 — Tách Biệt Ngân Sách CPU Và Độ Trễ (`Dual-Budget Placement`)**
   - Không bao giờ giả định đường mạng luôn `5–6 ms` (thực tế có thể dao động `6 ms → 18 ms → 105 ms` qua DERP).
   - Mọi quyết định định tuyến (`win-desktop` vs `svhome` vs `Colab Pro`) phải dựa trên **phép đo thực chứng theo từng loại job** (`build_placement`): tách riêng lợi ích *nhường CPU cho AutoCAD/GUI* khỏi *tổng thời gian chờ đầu-cuối* của người gọi.

6. **Luật 6 — Nghiệm Thu Bằng Chứng & Tự Hoàn Tác (`Evidence-Gated Do-No-Harm Rollback`)**
   - Không một tối ưu nào được bật mặc định trên phiên làm việc thật khi chưa qua 3 cổng thăng hạng: **`Lab` (unit test) → `Shadow` (đo A/B có chữ ký trên dữ liệu đại diện) → `Active` (vận hành thật có giám sát)**.
   - Mọi chính sách ở trạng thái `Active` nếu làm xấu đi `Processor Queue`, `P99` khung hình hiển thị, độ trễ dịch vụ peer, hoặc nhiệt/RAM vượt ngân sách phải **tự hoàn tác (Auto-Rollback)** và khóa khỏi danh sách tự động.

7. **Luật 7 — Hợp Nhất Ngược & Trần `80 MiB` (`Reverse-Consolidation & Zero-Weight Ceiling`)**
   - **Ngừng tạo thêm "vũ trụ/tên phiên bản song song".** Mọi năng lực mới bắt buộc gắn vào đúng **1 trong 5 Cơ Quan Chuẩn** bên dưới, dùng chung cổng neo `:9780/:9781` và dòng sự kiện nhân quả duy nhất.
   - Daemon thường trú trên **cả `win-desktop` lẫn `svhome`** bắt buộc giữ Working Set / RSS **`< 80 MiB`** (`target < 60 MiB` để luôn có biên an toàn `20 MiB`). Mọi module thực nghiệm/benchmark không phục vụ vòng chạy thật phải tách thành gói tùy chọn (lazy-loaded), không nạp sẵn vào RAM daemon.

---

## II. Kiến Trúc Hợp Nhất: `107 Module → 5 Cơ Quan Duy Nhất`

Toàn bộ kho mã `chimera_tp` được quy hoạch về **5 Cơ Quan Liên Thông** chạy trên **1 Tủy Sống Nhân Quả**:

| # | Cơ Quan | Sứ Mệnh Duy Nhất | Các Module Nòng Cốt Đã Có Trong Repo | Nguyên Tắc Cắt Gọn |
|---|---|---|---|---|
| **1** | **`Causal Spine`** *(Tủy Sống & Ký Ức)* | 1 dòng sự kiện bất biến, truyền tải xuyên máy, phiên bản tệp, kho bí mật & hoàn tác | `phantom_tunnel`, `hyper_wire`, `pulse_bus`, `flight_recorder`, `vault_sql`, `file_revisions`, `workspace_undo`, `evidence`, `clipboard_parcel`, `frame_notes`, `dna_vault`, `holo_backup` | Gộp mọi log/revision/manifest về chuẩn biên nhận SHA-256 thống nhất; không tạo thêm kho trạng thái cục bộ rời. |
| **2** | **`Hemisphere Router`** *(Bộ Điều Phối 4 Bán Cầu)* | Khớp trở kháng 4 bán cầu silicon, kiểm duyệt đầu vào & bảo vệ `svhome` | `work_admission`, `peer_guard`, `build_placement`, `exile_handoff`, `vgpu_gateway`, `colab_cli_bridge`, `colab_on_peer`, `mmcss`, `host_governor` | Mọi lệnh offload/burst bắt buộc đi qua 1 cửa `peer_guard + build_placement`; cấm nhánh gọi tắt bỏ qua ngân sách. |
| **3** | **`Akashic Swarm-Kernel`** *(Não Chung Bầy Đàn AI & App)* | Hợp nhất AI Coding Agents & ứng dụng cũ chung 1 bộ nhớ, 1 khóa file, 1 cache | `agent_probe` (`xray_batch`, `callgraph_slice`, `commit_verify`, `TokenDietCompactor`), `agent_workspace`, `guarded_build`, `swarm_symbols`, `result_reuse`, `hybrid_search`, `code_search`, `egress_membrane`, `mcp_server`, `unify`, `autoload`, `client`, `ghost_bubble` | Mọi AI Agent đọc batch/callgraph/cache/lease qua 1 cổng MCP/HTTP chung (0 PowerShell); không để 2 agent quét NTFS hay sửa đè cùng 1 tệp. |
| **4** | **`Entropy Annihilator`** *(Hệ Miễn Dịch & Chưng Cất)* | Xóa rác tài nguyên, phân tầng lưu trữ, giữ hiển thị Zero-Copy & tự hoàn tác | `phantom_silicon` (NVMe Mirage + Topology-Aware GPU-Fence), `hyper_desk` (chế độ `aether`), `workspace_capsule`, `midbrain_dopamine`, `medic`, `sentinel` | Xóa sạch mọi nhánh bóp CPU/suspend mặc định; `midbrain_dopamine` chỉ chấm thưởng trên chỉ số thật (`Queue`, `P99`, `Temp`, `Commit`). |
| **5** | **`Sovereign Skin`** *(Bề Mặt Không Trọng Lượng)* | 1 giao diện 2D Zero-WebGL, 1 CLI thống nhất & 1 hạt giống tái sinh | `universe_ui` (v26 Zero-WebGL 2D), `aether_cli`, `cli`, `discovery`, `dashboard`, `substrate` | Giữ `0` vòng lặp WebGL/RAF nền; gộp dần nhóm lệnh phân tán về mặt tiền thống nhất. |

### Đường đi của một job build hoặc Exile

| Cơ quan | Trách nhiệm trong đường chạy thật |
| --- | --- |
| Causal Spine | `work_admission.peer_ssh_route` chọn kết nối SSH qua PHANTOM khi tunnel còn khỏe. `build_queue` giữ vé và đầu vào trên Windows. `exile_queue` dùng cùng outbox khi phải phục hồi một job nhiều bước. |
| Hemisphere Router | `build_placement` ghi tuyến SSH vào hồ sơ A/B. `guarded_build` kiểm lại ngay trước khi gửi. Đổi tuyến làm job có thể lặp lại được xếp hàng với nguyên đầu vào. `peer_guard` quyết định nhận từng job và xác minh cgroup của worker Linux. `exile_colab` kiểm ngân sách trước khi yêu cầu runtime. |
| Akashic Swarm-Kernel | `guarded_build` chuyển công việc cho `local_build` hoặc `build_worker`. `build_snapshot` đóng băng nguồn và kiểm dữ liệu trả về. `build_registry` gộp công việc trùng. `guarded_cas` dùng chung đường gửi và bộ kiểm hiện vật. `exile_handoff` chỉ chốt bước sau khi khớp generation, nội dung và node nhận. |
| Entropy Annihilator | `windows_build_job` giới hạn cây tiến trình Windows. Thư mục làm việc tạm của Linux do worker giải phóng sau job. Kho VSA có SQLite đọc vector từ đĩa và giữ kết quả đứng đầu trong RAM. DB đã tạo từ bản trước dùng nguyên schema. |
| Sovereign Skin | CLI `swarm`, `swarm-placement`, `swarm-queue` và SDK/HTTP Exile dùng các hợp đồng trên. API chạy lệnh hoặc kiểm thử trực tiếp trên daemon Linux trả `guarded_build_required`. Phía gửi dùng `swarm` để được cấp worker. |

Biên nhận của từng bước gồm tuyến đã dùng, giới hạn đã xác minh và dấu vân tay đầu ra. Phép thử có hai build C dùng chung một phiên SSH đã chạy trên `svhome`. Các lần gọi Swarm độc lập vẫn mở kết nối riêng. [Biên nhận nghiệm thu](../tasks/workstation_acceptance_6076079bd54c.json) · [Các cặp build C](../tasks/guarded_build_session_6076079bd54c.json)

> **Phân loại module di sản / phòng thí nghiệm (`v9–v12`, `omega_*`, `singularity_*`, `vsa_memory_service`):** Giữ làm **Tầng Nghiên Cứu & Thư Viện Nguyên Thủy Nạp Trễ (`lazy-import`)** — không nạp tự động khi khởi động daemon để hạ RSS `svhome` từ `~79 MiB` xuống **`< 55 MiB`**.

---

## III. Ma Trận Phân Vai 4 Bán Cầu Silicon (Không Bao Giờ Xâm Phạm Vai)

| Bán Cầu | Phần Cứng Thực Tế | Vai Trò Bắt Buộc | Vùng Cấm Tuyệt Đối |
|---|---|---|---|
| **1. `WIN-REFLEX`** | `i5-11400` (6C/12T `4.4 GHz`) · `32 GiB` RAM · `C:` NVMe | AutoCAD 2027, GUI tương tác, IDE UI, biên dịch nhanh có gộp cục bộ (`--target local`), lưu trữ nóng NVMe. | Cấm bóp `0xF00`, cấm tắt Turbo `99%`, cấm suspend tiến trình IPC, cấm chạy `6` Chromium song song. |
| **2. `WIN-OPTIC`** | Windows CCD ngày 27/11/2026 ghi MSI MP275 E2 qua HDMI 120 Hz và KA272 qua DVI 75 Hz. Hai đường xuất cùng adapter NVIDIA `VEN_10DE&DEV_2188`, LUID `00000000:0000aad1`. [Biên bản CCD](../tasks/display_paths_20261127.json) | Giữ AutoCAD và hai màn hình trên Windows. Dùng UHD 730 cho các bài media đã đo với Quick Sync. | Đối chiếu adapter hiển thị và adapter ứng dụng dùng để render trước khi quy độ trễ cho việc sao chép khung hình. Đo PresentMon riêng cho thay đổi tần số quét hoặc MuMu. |
| **3. `SVHOME-NERVE`** | `i5-4300U` (2C/4T 15W, `44–48°C`) · `10 GiB` (`6 GiB` trống) · `109 GB` SSD (`34 GB` trống) | Hệ thần kinh 24/7 siêu nhẹ (`< 5%` CPU, `< 150 MB` RAM): `EgressMembrane`, `PulseBus`, `Secrets`, `MCP Router`, `Delta Store`, `Radar/Tqouta`, điều phối Colab. | Cấm đẩy Chrome GUI, IDE nặng, job `> 1.5 GiB` RAM, hay vượt ngưỡng `peer_guard` (`load > 1.8` / `>= 70°C` / `< 2.5 GiB` trống). |
| **4. `COLAB-ARTILLERY`** | `Colab Pro` (`2,350 CU` · `51 GiB` RAM · `T4/L4`) | Hứng mọi đợt bùng nổ nặng (OCR hàng trăm trang scan, Whisper, Embedding khối lớn, batch/test nặng) theo ngân sách khai báo trước rồi tự trả VM. | Cấm chạy không khai báo ngân sách CU hoặc thiếu biên nhận xác minh đầu ra. |

---

## IV. Chuẩn Đồng Bộ & Kỷ Luật Vận Hành Hai Máy

1. **Một nguồn sự thật (`Single Source of Truth`):** Mọi thay đổi ở `chimera_tp/` sau khi pass kiểm thử phải có bước đồng bộ xác minh `SHA-256` sang `svhome` và duy trì đúng dịch vụ quản lý (`chimera-hyper-daemon.service` systemd thay vì tiến trình thủ công `nohup` trôi nổi).
2. **Kiểm soát trần RAM daemon (`< 80 MiB`):** Chuyển các mô-đun thí nghiệm (`v9–v12`, `vsa`, `omega` bench) sang `lazy-import` khi được gọi API để `svhome` daemon ổn định dưới **`55–60 MiB`** (thoát ngưỡng báo động `79.17 / 80 MiB`).
3. **Bàn giao từng lát cắt thật từ `Shadow → Active` (theo [WORKSTATION_EXECUTION_PLAN.md](WORKSTATION_EXECUTION_PLAN.md)):**
   - **Lát cắt 1 (Đồng bộ + Hạ RSS `svhome` + Chốt Git):** Đồng bộ đủ `107` module sang `svhome`, khôi phục `chimera-hyper-daemon.service`, lazy-load để `svhome < 60 MiB`, rà soát và gom commit sạch.
   - **Lát cắt 2 (Giải phóng RAM thật trên Windows — `439 procs / 39.6 GB Commit → < 200 procs / < 22 GB`):** Chuyển `office_print` thật (`3.3 GB` Private Commit) sang cơ chế on-demand `0` worker lúc nghỉ; gom web-app tương thích vào chung `1` hồ sơ trình duyệt trên `GTX 1650`.
   - **Lát cắt 3 (Nghiệm thu AutoCAD `10/10` cặp thật & 1 lượt Colab thật):** Hoàn tất `10/10` cặp đo `PresentMon P99` trên DWG đại diện và 1 biên nhận chạy thực trên Colab để khóa chính sách định tuyến tự động cuối cùng.
