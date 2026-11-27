# Hậu kiểm Moonshot Vault sau khắc phục ngày 26/11/2026

**Cụm `win-desktop` và `svhome` đã đóng toàn bộ các hạng mục P0/P1 có thể kiểm chứng bằng mã nguồn và thực nghiệm trong phiên, đồng bộ phiên bản `18.0.0`, khóa biên nhận bàn giao có thế hệ và chuẩn hóa đo lường — đồng thời giữ nguyên đánh giá trung thực cho các giới hạn phần cứng và đánh đổi thông lượng build.** Báo cáo này đối chiếu độc lập trạng thái **TRƯỚC** ([Kiểm định gốc](MOONSHOT_VAULT_AUDIT_2026-11-26.md)) với trạng thái **SAU** dựa trên kiểm tra HTTP trực tiếp hai daemon đang phục vụ, rà soát mã tĩnh, chạy trọn bộ 12 bộ test (`66/66` đạt) và kiểm tra 4 tệp dữ liệu benchmark.

---

## 1. Bảng đối chiếu TRƯỚC vs SAU (P0 / P1 / Đột phá / Kiến trúc)

| Hạng mục & Mức ưu tiên | TRƯỚC (Kiểm định 16:55–17:35) | SAU (Hậu kiểm độc lập 18:49–18:52) | Trạng thái |
|---|---|---|---|
| **P0 · Phạm vi Ctrl-Z trên daemon sống** | Hai daemon sống lúc 17:35 đều thiếu `ctrl_z_scope` trên `/v1/omega/status` (chỉ có ở test cô lập). | Cả `win-desktop` và `svhome` trả `ctrl_z_scope="committed_patch_files"` qua `GET /v1/omega/status`; test giữ nguyên tệp ngoài diff và từ chối khi xung đột SHA-256 đều đạt. [Omega](../../chimera_tp/platform/omega_entity.py) · [Undo](../../chimera_tp/platform/workspace_undo.py) | **Đạt** |
| **P0 · Tái tạo ứng viên Git & Wheel native** | Xuất nguồn từ commit `021c033e1a` / `877b7da1ce` lỗi `ModuleNotFoundError: cosmos_entity`; wheel thiếu binary native (`has_native() == False`); `_chimera_core.dll.prev` nằm trong cây gói. | `pyproject.toml` khai báo `package-data` (`_chimera_core.dll`, `_chimera_core.so`) và loại `*.prev`. Build từ `git archive HEAD` trong môi trường sạch: wheel native **753.865 B** (90 mục, `has_native() == True`, `avx512f=True`), wheel pure-Python **580.116 B** (89 mục, `has_native() == False`, fallback chạy sạch), CLI exit `0`. [Đóng gói](../../pyproject.toml) · [Kiểm thử build](../../scripts/verify_clean_build.py) | **Đạt (cần chủ kho commit)** |
| **P0 · Đồng bộ `package_version` & Parity hai máy** | `svhome` báo `package_version=12.0.0` ở beacon và thiếu trường này ở `/api/health`; thiếu `/v1/evidence` và `/v1/exile/receipts`. | Cả `win-desktop` và `svhome` đều trả `package_version="18.0.0"` ở cả beacon và health, `cartridge_status_basis="config_plus_live_evidence"`, `hardware.native=True`. RAM: Windows `41,64–42,29 MiB`, Linux `75,12–75,13 MiB` (`< 80 MiB`). [Substrate](../../chimera_tp/platform/substrate.py) · [Dashboard](../../chimera_tp/dashboard.py) | **Đạt** |
| **Đột phá #1 · Bàn giao Exile có checkpoint & Evidence Ledger** | `AgentExileEngine` chỉ gói thư mục chạy lệnh; `capabilities()` lấy `active` từ công tắc cấu hình; `compile_intent()` chưa đọc bằng chứng có TTL. | `ImmortalJobEngine` thêm `step_leases` + `step_receipts` (Single Commit Authority chặn thế hệ cũ); `EvidenceLedger` có TTL 300s tự hết hạn về `unverified`; `CheckpointedExileCoordinator` gắn CAS + Pulse + Governor + Exile; `compile_intent()` đọc `substrate.evidence`. Tiêm lỗi 100 lượt đạt `100/100` khớp oracle; 2 job thật `win-desktop -> svhome` đã chốt qua `/v1/exile/handoff`. [Exile Handoff](../../chimera_tp/platform/exile_handoff.py) · [Evidence](../../chimera_tp/platform/evidence.py) · [Journal](../../chimera_tp/platform/immortal_jobs.py) | **Đạt** |
| **P1 · Thực nghiệm A/B HyperDesk 10 cặp & VRAM Yield** | Chưa có A/B đối chứng cùng tải (2 mẫu cũ cách >15 phút, thiếu hard/soft faults và thời gian build); `vram_swap.yield_ms = 32,097 ms` (`>30 ms`). | 10 cặp `AB/BA` (20 lượt) trên Windows: p99 tương tác giảm **median `92,986%`** (`65,022 → 4,417 ms`, rớt khung `54,722% → 0,0%`), nhưng `build_time_s` tăng **median `+239,973%`** (`6,608 → 21,140 s`) → kết luận trung thực **`MIXED_KEEP_OPT_IN`**. VRAM yield đo lại `53,919 ms` vì `cuCtxDestroy_v2` trên WDDM mất `32–50 ms` để giữ `vram_retained_mb == 0.0`. [Benchmark A/B](../../scripts/bench_hyperdesk_ab.py) · [Kết quả A/B](../../tasks/hyperdesk_ab_results.json) | **Hoàn tất đo (giữ Opt-In)** |
| **P1 · Ngân sách UI & Wire-to-First-Interactive** | Bản WebGL đầu phiên `50.934 B` raw / `20.089 B` gzip / `27.312 B` packed (vượt trần 48k/20k/27k). Chưa đo TTI thật và tổng wire tới tương tác. | Nâng cấp `universe_ui.py` lên **v26 Zero-WebGL** (2D SVG + Canvas 2D) và nén sạch: tĩnh **`38.271 B` raw / `14.845 B` gzip9 / `20.248 B` packed**; 0 tài nguyên chặn bên ngoài; cô lập `/` + `/api/pulse` = **`17.825 B`** (`<= 26.000 B`); Playwright Chromium `/` tương tác sau `130,16 ms` (`/?packed=1` `113,45 ms`), `0` lỗi console. [UI](../../chimera_tp/universe_ui.py) · [TTI Bench](../../scripts/bench_ui_tti.py) | **Đạt** |
| **Kiến trúc #3 · Tách `TrinityCommandBridge` bằng Manifest Adapter** | Lõi `trinity_bridge.py` gắn cứng endpoint, payload và tên ứng dụng `tquota` và `radar`. | Định nghĩa `DownstreamAdapterSpec` + `adapter_from_manifest()`; `tquota` và `radar` trở thành cấu hình khai báo trong `_default_adapter_specs()`; `discovery.py` lưu `adapter` trong `chimera.manifest.v1`. Test `test_v24_trinity_adapters.py` (6/6) gắn app thứ 3 (`forge-worker`) mà **0 dòng sửa** ở `trinity_bridge.py`. [Trinity Bridge](../../chimera_tp/trinity_bridge.py) · [Discovery](../../chimera_tp/platform/discovery.py) | **Đạt** |

---

## 2. Số liệu đọc trực tiếp từ hai daemon đang phục vụ (`win-desktop` vs `svhome`)

Phép đọc HTTP trực tiếp được thực hiện độc lập lúc **18:49–18:51 ngày 26/11/2026 (giờ Việt Nam)** tới `http://127.0.0.1:9780` và `http://100.116.112.22:9780`.

| Chỉ báo trực tiếp | `win-desktop` (PID `20452`) | `svhome` (PID `3871360`) |
|---|---|---|
| Thời điểm khởi động (`started_at`) | `2026-11-26T18:42:08+07:00` | `2026-11-26T18:40:49+07:00` |
| `/.well-known/chimera.json` `version` / `package_version` | `21.0.0` / `18.0.0` | `21.0.0` / `18.0.0` |
| `/api/health` `version` / `package_version` | `12.0.0` / `18.0.0` | `12.0.0` / `18.0.0` |
| `cartridge_status_basis` | `config_plus_live_evidence` | `config_plus_live_evidence` |
| `hardware` (`/api/health`) | `native=True, gfni=True, avx2=True, avx512f=True` | `native=True, gfni=False, avx2=True, avx512f=False` |
| `zero_weight.daemon_ram_mb` (beacon / health) | `41,64 MiB` / `42,29 MiB` (`< 80 MiB`) | `75,12 MiB` / `75,13 MiB` (`< 80 MiB`) |
| `host_free_ram_gb` / `host_total_ram_gb` | `9,01` / `30,85 GiB` (`12` luồng) | `6,02` / `10,61 GiB` (`4` luồng) |
| `/v1/omega/status` `ring_minus_1_mode` / `slat_ept` | `userspace_ept_emulation` / `False` | `linux_kvm_ept_ready` / `True` |
| `/v1/omega/status` `ctrl_z_scope` | `committed_patch_files` | `committed_patch_files` |
| `/v1/evidence` (`counts` tại thời điểm đọc) | `verified=0, unverified=16, violated=0, disabled=0` (`recorded=4`) | `verified=0, unverified=15, violated=0, disabled=0` (`recorded=2`) |
| `/v1/exile/receipts` (`count` / `win_cpu_yields`) | `2` biên nhận đã chốt / `2` (`wire=400 B`, `dedup=36,8%`) | `0` biên nhận (`coordinator` ở chế độ nhận) |
| `/v1/pulse` (`latest_seq` / `active_topics`) | `4` (`exile.step.dispatched`, `exile.step.committed`) | `1` (`hyperdesk.autonomic`) |
| `/api/trinity/status` `adapters` | `['tquota', 'radar']` | `['tquota', 'radar']` |

**Quan sát thực tế về cơ chế hết hạn TTL của `EvidenceLedger`:** Trên `win-desktop`, self-check khởi động của `connect` và `egress_membrane` (`sample_count=7`, `11:42:08–09 UTC`) hết hạn lúc `11:47:08–09 UTC`, còn 2 lượt handoff xuyên máy sang `svhome` (`live-xnode-v24-1`, `live-xnode-v24-2`, `sample_count=2`, `11:42:34–38 UTC`) hết hạn lúc `11:47:38 UTC`. Khi probe độc lập lúc `11:49:42 UTC` (sau 5 phút TTL), cả 4 bản ghi này đều giữ nguyên dấu vết (`sample_count`, `receipt_id`, `execution_node`) nhưng tự chuyển `verification_status` từ `"verified"` về `"unverified"` với `"stale": true`. Tương tự trên `svhome`, self-check khởi động (`sample_count=5`, `11:40:49 UTC`) tự hết hạn lúc `11:45:49 UTC` và chuyển `"unverified"` khi probe lúc `11:49:43 UTC`. Lưu ý `svhome` đang tiêu thụ **`75,12–75,13 MiB`** (`93,9%` ngân sách `80 MiB`), biên an toàn mỏng hơn nhiều so với `win-desktop` (`41,64–42,29 MiB`).

---

## 3. Thử nghiệm bàn giao Exile 100 lượt tiêm lỗi & Chạy thật xuyên máy

Tệp chứng cứ: [exile_handoff_100_trials.json](../../tasks/exile_handoff_100_trials.json) · Script: [bench_exile_handoff.py](../../scripts/bench_exile_handoff.py).

- **Thiết kế tiêm lỗi (100 lượt, 25 lượt mỗi điểm cắt):** `pre_receive` (ngắt trước khi worker nhận CAS), `post_receive_pre_compute` (ngắt sau nhận CAS, trước tính toán), `post_compute_pre_ack` (worker tính xong ở `generation=1` nhưng rớt ACK; coordinator retry ở `generation=2` và chốt; biên nhận `gen 1` trễ được giao lại sau đó để kiểm tra từ chối), và `post_commit_pre_client_reply` (đã chốt trong journal nhưng rớt gói trả client; client mở lại idempotent).
- **Kết quả kiểm chứng từ JSON:**
  - `oracle_digest_matches`: **`100 / 100`** (`lost_accepted_jobs = 0`, `single_committed_receipt_per_step = 100 / 100`).
  - `delayed_stale_receipts_delivered`: **`25`** → `delayed_stale_receipts_rejected`: **`25 / 25`** (Single Commit Authority chặn tuyệt đối biên nhận thế hệ cũ).
  - `post_commit_idempotent_no_reexec`: **`25 / 25`** (phục hồi từ journal, không chạy lại tính toán).
  - `win_cpu_yield_honored_count`: **`100 / 100`** (khi giả lập Windows có tương tác người dùng, coordinator định tuyến sang `svhome` và ghi `win_cpu_yields = 125`).
  - Độ trễ phục hồi (`resume_latency_ms`): **`p50 = 7,175 ms`**, **`p95 = 24,408 ms`**, **`p99 = 30,346 ms`**, `min = 0,660 ms`, `max = 31,722 ms`, `mean = 7,223 ms` (tổng thời gian lượt `p50 = 10,824 ms`, `p95 = 34,428 ms`, `p99 = 47,289 ms`).
  - Băng thông & CAS: `wire_bytes_total = 520.192 B`; `retransmitted_bytes = 106.496 B` (toàn bộ phát sinh ở 25 lượt `pre_receive`; `0 B` truyền lại ở 3 điểm lỗi còn lại); `cas_dedup_saved_pct = 57,3%` (`logical_bytes = 1.958.283 B` nén lưu `835.979 B`).
- **Xác minh xuyên máy thật (`win-desktop -> svhome` qua SSH CAS):** Trên daemon `win-desktop` đang chạy, `/v1/exile/receipts` ghi nhận 2 job thật đã chốt trên `node_id="svhome"`: `live-xnode-v24-1` (`zlib_compress`, `generation=1`, `wire_bytes=400 B`, `output_digest=fb641f79...`) và `live-xnode-v24-2` (`sha256_manifest`, tái sử dụng khối CAS `f2e71b1e...` nên `wire_bytes=0 B`, `retransmitted_bytes=0 B`, `elapsed_ms=3.200,79 ms`). **Giới hạn phạm vi:** bộ 100 lượt tiêm lỗi dùng `FaultInjectingWorkerTransport` trong bộ nhớ để chèn lỗi tất định ở 4 pha mạng; đường SSH thật qua Tailscale được chứng minh trên 2 job sống không tiêm lỗi.

---

## 4. Thực nghiệm A/B HyperDesk 10 cặp luân phiên & Điều tra VRAM Yield

Tệp chứng cứ: [hyperdesk_ab_results.json](../../tasks/hyperdesk_ab_results.json) · Script: [bench_hyperdesk_ab.py](../../scripts/bench_hyperdesk_ab.py).

- **Thiết kế đối chứng:** 10 cặp chạy liên tiếp theo thứ tự đảo chiều **`AB, BA, AB, BA, AB, BA, AB, BA, AB, BA`** trên máy Windows `12` luồng (tạm dừng vòng autonomic của daemon trong lúc đo và khôi phục `running=True` sau đo). Mỗi lượt chạy song song: (1) vòng render tương tác giả lập CAD `180` khung hình tại mục tiêu `60 Hz` (`3.200` đỉnh, ngưỡng `16,6667 ms`/khung) và (2) bão build nền `12` worker × `210` tác vụ AST/compile/cấp phát trang/`zlib` (`2.520` tác vụ, checksum bất biến `120900003397004864675`). Điều kiện A chạy mặc định (`0xfff`); điều kiện B ghim tiền cảnh vào nhân Focus (`0xff`, `AboveNormal`, timer `0,5 ms`) và ép build nền vào nhân Industrial (`0xf00`, `BelowNormal`, `EcoQoS`, `MemoryPriority=VeryLow`, `WinHardCpuCage=35%`). Đo fault bằng Win32 `GetProcessMemoryInfo` + `pdh.dll` (`\Memory\Page Reads/sec`, `\Memory\Pages Input/sec`, `\Memory\Page Faults/sec`).

| Chỉ số tổng hợp (10 cặp) | Condition A (`baseline` median) | Condition B (`hyperdesk` median) | Phân phối Delta / Nhận xét |
|---|---:|---:|---|
| Tiền cảnh `p50_ms` | `18,669 ms` | `2,412 ms` | Giảm mạnh trên toàn bộ 10 cặp |
| Tiền cảnh `p95_ms` | `49,820 ms` | `3,779 ms` | Ổn định dưới ngân sách khung `16,67 ms` |
| Tiền cảnh `p99_ms` | **`65,022 ms`** | **`4,417 ms`** | Giảm **median `92,986%`** (`p25=91,118%`, `p75=94,643%`, `min=85,709%`, `max=96,708%`) |
| Rớt khung (`>16,67 ms`) | `54,722%` (`35,0%–74,444%`) | `0,0%` (`mean 0,111%`, `max 1,111%`) | Gần như triệt tiêu rớt khung |
| Thời gian build nền (`build_time_s`) | **`6,608 s`** (`mean 6,818 s`) | **`21,140 s`** (`mean 27,851 s`) | **Tăng median `+239,973%`** (`mean +338,060%`, `min +114,347%`, `max +868,471%`) |
| `private_commit_mb` | `459,410 MB` | `458,762 MB` | Không thay đổi (`±0,65 MB`) |
| `working_set_mb` | `374,101 MB` | `508,090 MB` | B tăng WS giữ trang vì tải kéo dài trên 4 nhân |
| Hard faults/s (`Page Reads/sec`) | `65,242 /s` (`pages_input=350,147 /s`) | `36,962 /s` (`pages_input=254,660 /s`) | Đo trực tiếp từ `pdh.dll` |
| Soft faults/s (từ `GetProcessMemoryInfo`) | `318.349,776 /s` | `97.403,330 /s` | Giảm tốc độ cấp phát/s tương ứng với kìm CPU nền |

- **Phán quyết trung thực (`MIXED_KEEP_OPT_IN`):** Quy tắc nghiệm thu đòi hỏi đồng thời `median_p99_reduction_pct >= 20,0%` và `median_build_time_delta_pct <= 10,0%`. Điều kiện B đạt xuất sắc vế tương tác (`92,986% >= 20%`), nhưng làm build nền chậm gấp `~3,4x` (`+239,973%`, cá biệt cặp 1 tới `+868,471%` từ `5,5615 s` lên `53,8615 s` vì kìm `HardCpuCage 35%` + giới hạn 4 luồng `0xf00`). Do đó **chính sách kìm hãm mạnh của HyperDesk phải giữ ở chế độ tùy chọn (opt-in)** khi người dùng ưu tiên CAD/tương tác tuyệt đối, không bật ép lên tác vụ build cần thông lượng tối đa.
- **Kết quả điều tra `VramCompressedSwap.yield_ms`:** Benchmark trên `NVIDIA GeForce GTX 1650` (`4,0 MB` payload) đạt `ok=True`, `compression_ratio=252,58x` (`0,016 MB` VRAM), `sha256_exact=True`, `put_ms=196,154 ms`, `get_ms=8,926 ms`, `yield_ms=53,919 ms`, `vram_retained_mb=0,0 MB`. Phân tích cho thấy `cuMemFree_v2` chỉ mất `0,18–0,37 ms`, còn **`cuCtxDestroy_v2` trên trình điều khiển WDDM Windows tốn `32–50 ms`** để thu hồi `~49 MB` ngữ cảnh CUDA. Bỏ `cuCtxDestroy_v2` để giảm dưới `30 ms` sẽ làm rò/giữ lại `~49 MB` VRAM (vi phạm bất biến `vram_retained_mb == 0,0`), nên mã nguồn giữ nguyên hành vi giải phóng hoàn toàn.

---

## 5. So sánh kích thước UI & Tổng wire tới lần tương tác đầu

Tệp chứng cứ: [ui_tti_bench.json](../../tasks/ui_tti_bench.json) · Nguồn: [universe_ui.py](../../chimera_tp/universe_ui.py) · [dashboard.py](../../chimera_tp/dashboard.py).

Trong quá trình triển khai, `universe_ui.py` đã chuyển sang kiến trúc **CHIMERA COMMAND v26 Zero-WebGL** (đồ thị topology SVG + 4 biểu đồ Canvas 2D thuần, bỏ WebGL để loại bỏ tiêu thụ GPU trên UI). Các số liệu kiểm chứng độc lập như sau:

| Chỉ số | TRƯỚC (WebGL v24 đầu phiên) | SAU (Template tĩnh v26 Zero-WebGL) | Daemon cô lập (`ui_tti_bench.json`) | Live `win-desktop` (có SSR state) | Live `svhome` (có SSR state) |
|---|---:|---:|---:|---:|---:|
| HTML gốc (`raw`) | `50.934 B` | **`38.271 B`** (`-24,9%`) | — | `63.544 B` | `69.321 B` |
| `gzip` (level 9 / wire) | `20.089 B` | **`14.845 B`** (`lvl5: 14.889 B`) | `16.495 B` | `20.631 B` | `21.697 B` |
| Packed (`/?packed=1`) | `27.312 B` | **`20.248 B`** (`pk_gz: 15.445 B`) | `20.520 B` | `20.780 B` (`gz: 15.846 B`) | `20.516 B` (`gz: 15.647 B`) |
| `GET /api/pulse` (`gzip`) | — | — | `1.330 B` | `1.990 B` | `1.821 B` |
| **Tổng wire (`/` + `/api/pulse`)** | Chưa đo | — | **`17.825 B`** (`<= 26.000 B`) | **`22.621 B`** (`<= 26.000 B`) | **`23.518 B`** (`<= 26.000 B`) |

- **Tài nguyên chặn & Trình duyệt thật:** `0` `<script src=...>`, `0` `<link stylesheet>`, `0` URL `http(s)://`. `node --check` hợp lệ trong `69,99 ms`. Thử nghiệm **Playwright Chromium** trên daemon cô lập cho:
  - `GET /`: `DOMContentLoaded = 96,8 ms`, `first_interactive_ms = 130,16 ms`, `pulse_hydrated_ms = 205,03 ms`, `0` console error, `0` page error, `6` node SVG, `4` Canvas 2D (`324×116/123`), `15` cartridge, `Ctrl+K` spotlight và `Tab` compact mode hoạt động.
  - `GET /?packed=1`: `DOMContentLoaded = 15,2 ms`, `first_interactive_ms = 113,45 ms`, `pulse_hydrated_ms = 207,51 ms`, `0` lỗi.

---

## 6. Kiểm thử tổng hợp, Bất biến Lesson 4 & Danh sách tệp Git còn mở

### 6.1. Kết quả kiểm thử độc lập trên Windows
Lệnh chạy trọn bộ 12 suite sau tất cả các chỉnh sửa:
```bash
python -m unittest tests/test_v13_cortex_ui.py tests/test_v15_trinity_cortex.py tests/test_v16_platform_connect.py tests/test_v17_silicon_cartridges.py tests/test_v18_perfection.py tests/test_v18_overmind_cortex.py tests/test_v19_v21_omega_entity.py tests/test_v23_phantom_silicon.py tests/test_v24_exile_handoff.py tests/test_v24_trinity_adapters.py tests/test_v24_hyperdesk_ab.py tests/test_v24_packaging_repro.py -v
```
- **Kết quả:** **`Ran 66 tests in 156.479s` — `OK`** (`66/66` đạt, `0` lỗi, `0` bỏ qua).
- **Trên `svhome` (theo nhật ký chạy sau chỉnh sửa cuối ở `#19`):** `7` suite (`test_v16`, `test_v17`, `test_v19_v21`, `test_v23`, `test_v24_exile_handoff`, `test_v24_trinity_adapters`, `test_v24_packaging_repro`) đạt **`39/39` trong `87,863 s`**.

### 6.2. Kiểm tra bất biến `tasks/lessons.md` Lesson 4 (`CREATE_NO_WINDOW` & không `powershell.exe`)
Quét AST toàn bộ `chimera_tp/` và `scripts/` (`45` điểm gọi `subprocess.*`):
- Tất cả các module cốt lõi/nền tảng sửa hoặc mới trong `chimera_tp/platform/` (`browser_grid.py`, `colab_cli_bridge.py`, `discovery.py:513`, `ghost_bubble.py`, `phantom_silicon.py`, `vgpu_gateway.py`), `chimera_tp/ghost_fs.py`, `chimera_tp/legacy/v9_nvme_grid.py`, và cả 4 script benchmark/kiểm thử (`bench_exile_handoff.py`, `bench_hyperdesk_ab.py`, `bench_ui_tti.py`, `verify_clean_build.py`) đều dùng `CREATE_NO_WINDOW` trên Windows và **không gọi `powershell.exe`**. (Các ngoại lệ vô hại: `discovery.py:531` nằm trong nhánh Linux `else:` chạy `ss -tlnp`; `cli.py:1816` là lệnh tương tác `chimera-tp run`; `hyper_desk.py:179` chỉ là chuỗi nhận diện tiến trình trong `_AI_AGENT_PROCS`).
- **Ghi nhận ngoài phạm vi dọn đợt này:** các module cũ chưa sửa (`chimera_tp/probe.py:90–91` vẫn gọi `powershell`, `apex_synergy.py`, `drop_portal.py`, `ghost_pty.py`, `medic.py`, `zygote_canary.py`, `v9_app_index.py`) và 5 script đo phụ (`scripts/measure_build_location.py`, `measure_service_relay.py`, `measure_shared_browser.py`, `test_remote_surface.py`, `workspace_browser.py`) vẫn có lời gọi `subprocess.*` không kèm `CREATE_NO_WINDOW`.

### 6.3. Danh sách tệp chưa track cần đưa vào commit Git ứng viên
Working tree hiện tại trên nền `HEAD = 5ff4a08a8447fe344aad2cd1c9c4c9748dc8d425` có **30 tệp tracked đã sửa** và các tệp mới chưa track (xem chi tiết trong [clean_build_verification.json](../../tasks/clean_build_verification.json)):
- **10 module Python bắt buộc trong `chimera_tp/`:** `chimera_tp/midbrain_dopamine.py`, `chimera_tp/overmind_cortex.py`, `chimera_tp/platform/cosmos_entity.py`, `chimera_tp/platform/evidence.py`, `chimera_tp/platform/exile_handoff.py`, `chimera_tp/platform/hyper_desk.py`, `chimera_tp/platform/mmcss.py`, `chimera_tp/platform/omega_entity.py`, `chimera_tp/platform/phantom_silicon.py`, `chimera_tp/platform/workspace_undo.py`.
- **8 tệp test mới trong `tests/`:** `test_v18_overmind_cortex.py`, `test_v19_midbrain_dopamine.py`, `test_v19_v21_omega_entity.py`, `test_v23_phantom_silicon.py`, `test_v24_exile_handoff.py`, `test_v24_hyperdesk_ab.py`, `test_v24_packaging_repro.py`, `test_v24_trinity_adapters.py`.
- **12 script trong `scripts/`:** `bench_exile_handoff.py`, `bench_hyperdesk_ab.py`, `bench_ui_tti.py`, `verify_clean_build.py`, cùng 8 script đo/tiện ích (`display_paths.py`, `measure_aether_hud.py`, `measure_build_location.py`, `measure_service_relay.py`, `measure_shared_browser.py`, `test_remote_surface.py`, `verify_nvme_stage.py`, `workspace_browser.py`).
- **Native & Tài liệu/Chứng cứ:** `native/loopback_relay.rs`, `docs/reports/` (`CHIMERA_V21_OMEGA_ENTITY_EVALUATION.md`, `MOONSHOT_VAULT_AUDIT_2026-11-26.md`, `MOONSHOT_VAULT_POST_REMEDIATION_2026-11-26.md`, `TRINITY_V18_OVERMIND_CORTEX_REPORT.md`, `TRINITY_V19_CHIMERA_MIDBRAIN_REPORT.md`) và các JSON trong `tasks/`.
- **KHÔNG commit:** `chimera_tp/_chimera_core.dll.prev` (bản sao lưu DLL cũ).

### 6.4. Các phạm vi trung thực vẫn còn mở
1. **Ảo hóa phần cứng & Di trú tiến trình sống:** Chưa chạy VM KVM/VT-x thực hay kiểm chứng di trú socket/PID sống xuyên máy; `SSI` tiếp tục báo đúng thực tế `local_metadata_only` (`socket_preserved=false`).
2. **Độ bền dài hạn & Hạ tầng vật lý:** Chưa có phép thử **24h soak test** tải liên tục (đặc biệt cần theo dõi RAM trên `svhome` hiện ở `75,12–75,13 / 80 MiB`), mất điện thật cả host, hoặc tách hai đường ISP vật lý độc lập.
3. **HyperDesk mặc định & WDDM VRAM Yield:** `HyperDesk` giữ chế độ **opt-in** (`MIXED_KEEP_OPT_IN`) do chi phí thời gian build `+239,973%`; `vram_swap.yield_ms` trên Windows GTX 1650 vẫn `>30 ms` (`53,919 ms`) do `cuCtxDestroy_v2` để bảo đảm `vram_retained_mb == 0,0`.
4. **Đóng gói đa nền tảng trong Git:** Chủ kho cần thực hiện `git add` & `git commit` cho các tệp ứng viên nêu trên; `_chimera_core.so` (Linux) và `_chimera_core.dll` (Windows) được biên dịch riêng theo hệ điều hành đích chứ không nằm chung trên một máy khi build wheel.
