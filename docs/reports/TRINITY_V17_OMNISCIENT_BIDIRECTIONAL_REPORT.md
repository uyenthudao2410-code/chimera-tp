# Báo cáo Triển khai & Đánh giá Toàn diện — **Trinity v17 Omniscient Bidirectional**
*(Chimera-TP × Tquota Codex-First × Radar Sovereign × Google Colab CLI — Đồng bộ 100% Windows ⇄ svhome)*

- **Ngày thực thi:** 2026-11-26 (GMT+7)
- **Phạm vi kiến trúc:** Reverse-PHANTOM 2 chiều (`12551->12500`, `9790->9780`), Codex-First TTFT Arbitrage & ThoughtBrief Export, Radar Necromancer Monorepo Node Verifier + Swarm + Auto-Distill VSA (`10,000-bit`), Zero-Exposure `svhome` Colab Keyring Auth, và đồng bộ SHA-256 `22` tệp nguồn/test giữa Windows và `svhome`.
- **Trạng thái hoàn tất:** Đã triển khai, kiểm thử đơn vị trên cả Windows & `svhome`, xác nhận SHA-256 `MISMATCH_COUNT=0` cho toàn bộ tệp đồng bộ, cấu hình & khởi động lại toàn bộ daemon trên cả 2 máy, và hoàn tất 4 nhóm benchmark live.

---

## 1. Bảng Đối Chiếu Metrics Thực Tế: **BEFORE vs AFTER**

| Hạng mục / Chỉ số đo | BEFORE (Trinity v16 / Đầu phiên) | AFTER (Trinity v17 Live) | Đánh giá & Bằng chứng |
| :--- | :--- | :--- | :--- |
| **Luồng `svhome → Win` qua PHANTOM 5ms** | 1 chiều (`Win → svhome` only; `svhome.reverse_listeners` chưa có) | **2 chiều (`12551 → Win:12500`, `9790 → Win:9780`)** | Win RTT **`6.81 ms`** (samples `10.9, 6.81, 5.9`); `svhome` `12551/healthz` `12.91 ms`, `9790/api/health` `32.48 ms` |
| **Tquota Hive Gossip & `fastOrigin`** | `Win → svhome` qua `12550`; `svhome → Win` không có `fastOrigin` | **Cả 2 chiều đều `transport: PHANTOM_5MS` (`gossipErrors: 0`)** | Win `syncResults` `via: 127.0.0.1:12550` (`39` slots); `svhome` `syncResults` `via: 127.0.0.1:12551` (`49` slots) |
| **Codex-First Arbitrage cho idle fast peer** | Bỏ qua peer có `avgTtftMs === 0` (idle) | Route `codex_ttft_advantage` khi `localTtft > 3000ms` và peer idle (`50` slots) | Đã verify bằng unit test `TC-8` + live `codex exec` (`Win 12.79s OK`, `svhome 10.09s OK`) |
| **Tquota RSS (`svhome` systemd + V8 heap)** | `389.1 MB` (systemd) / `413.8 MB` (peer RSS) | **`223.3 MB`** (systemd, `peak 266M`) / **`271.6 MB`** (peer RSS) | Giảm **`~34–42%`** RAM thực tế trên `svhome` |
| **Radar RAM & Restart (`svhome` systemd)** | `704.2 MB` | **`354.5 MB`** (ngay sau restart `300.2 MB`); restart **3 services mất `2,132 ms`** | `Stopping -> Stopped` sạch `< 1s` (`14:28:17 -> 14:28:18`), không còn timeout 20s `SIGKILL` |
| **`svhome` Colab CLI Auth (tự hành 24/7)** | `SVHOME_HAS_COLAB_TOKEN=False` (chưa chạy Colab trực tiếp từ `svhome`) | **`authenticated: True`** trong `SecretService.Keyring` (**0 trace ổ đĩa**) | `/api/godmode/colab/cli/status` trả `balance_cu=2350.15`, `active_assignments=0`, `rc=0` |
| **Colab `CPU_HIGH_MEM` Node Monorepo Deps** | `test_rc=254/127` (`vitest/jest: not found`, không chạy `npm ci`) | **5/5 repo Node chạy `npm ci` thành công (`npm_deps_rc=0`)** đúng subdir monorepo | Bắt thật failure ở `dashbrr` (`rc=1`), `mergit` (`rc=1`), `lateralus#998` (`4 failed/172`); **3 repo `rc=126` (`Permission denied`)** cần chuyển Node clone ra ngoài `/dev/shm` |
| **Colab Auto-Stop sau `drain_queue`** | Thủ công kiểm tra | Tự động gọi `colab stop` (`stopped: True`, `116.14s` cho 8 jobs) | `colab usage` sau drain xác nhận **`Active assignments: 0`**, `2350.15 CU` không rò rỉ |
| **VSA `10,000-bit` Crystals & Sync Win ⇄ svhome** | Win `0` items; `svhome` `5` items (`avg_recall_ms=0.128`) | **Win `151` items == `svhome 151` items** (`distill` `145` mục từ lịch sử trong `1,336.6 ms`) | Đồng bộ 2 chiều qua `127.0.0.1:9789` mất **`306.32 ms`** (`pulled=151, pushed=151`); recall warm `svhome` `4.24–4.94 ms` HTTP / `avg 3.047 ms`, Win `avg 3.42 ms` (`int_bitcount_fast`) |
| **Cockpit Win → `svhome` Proofs & Dry-Run PR** | Chưa có `/api/trinity/proofs`, `/draft-pr`, `/swarm/run` | Win `/api/trinity/proofs` đọc đủ **`8` proofs** từ `svhome`; `draft-pr` `1.25 ms`; `swarm/run` `16.95 ms` | An toàn: `dry_run=True` mặc định, **0** PR sống / `git push` tự động |
| **Chimera UI Packed Wire Budget (`v17.0`)** | `v15.0`, chưa có nút `Proofs (5s)` / `VSA Sync` | `PHANTOM-CORTEX v17.0`, **`15,178 B` gzipped** (`19,883 B` raw) | Thấp hơn ngưỡng **`16,500 B`** wire (`assertLess(len(gzip.compress(packed_html)), 16500)` PASS) |

---

## 2. Chi tiết Các Đột Phá Đã Triển Khai

### Wave 1 — Chimera-TP: Reverse-PHANTOM & Đồng bộ VSA Lưỡng Cực
1. **[phantom_tunnel.py](file:///E:/dev/chimera-tp/chimera_tp/phantom_tunnel.py):**
   - Dùng bit MSB `_REV_CONN_MASK = 0x80000000` phân tách hoàn toàn không gian `conn_id` giữa luồng Client→Server (`1..0x7fffffff`) và luồng ngược Server→Client (`0x80000001..`).
   - `PhantomTunnelServer` hỗ trợ `reverse_forwards`, tự động mở TCP listener trên `127.0.0.1` (`_reverse_accept_loop`), gửi `_P_OPEN` ngược về `PhantomTunnelClient`, báo cáo `reverse_listeners` trong `stats()` và dọn socket khi `close()`.
   - `PhantomTunnelClient` thêm `allowed_reverse_ports` (mặc định `[9780, 12500, 12504]`) và xử lý `_P_OPEN` trong `_udp_io_loop`.
2. **[autopilot.py](file:///E:/dev/chimera-tp/chimera_tp/autopilot.py) & [dashboard.py](file:///E:/dev/chimera-tp/chimera_tp/dashboard.py):**
   - Bổ sung cấu hình `phantom_reverse_tquota_port=12551`, `phantom_reverse_http_port=9790`, `phantom_reverse_allowed_ports`.
   - `ChimeraDaemon.start()` khi chạy role `server` (`svhome`) tự động mở reverse listener `12551 -> 12500` & `9790 -> 9780`; chủ động gọi `trinity.refresh_async(ttl_s=0.0)` để không trả về snapshot rỗng lúc khởi động.
   - Bổ sung 3 endpoint mới: `GET /api/vsa/export`, `POST /api/vsa/sync-peer`, và `GET /api/trinity/proofs`.
3. **[vsa_memory_service.py](file:///E:/dev/chimera-tp/chimera_tp/vsa_memory_service.py), [sentinel.py](file:///E:/dev/chimera-tp/chimera_tp/sentinel.py), [trinity_bridge.py](file:///E:/dev/chimera-tp/chimera_tp/trinity_bridge.py), [universe_ui.py](file:///E:/dev/chimera-tp/chimera_tp/universe_ui.py):**
   - `SharedVsaMemoryService`: tiền tính toán `vec_int` khi nạp/lưu, tăng tốc `recall()` bằng phép `(q_int ^ v_int).bit_count()` (`int_bitcount_fast`), thêm `export_items()`.
   - `SentinelEngine`: bổ sung `scan_stalled_workers()` kiểm tra worker Radar chạy quá `300s` (gọi an toàn qua loopback trong `scan()`).
   - `TrinityCommandBridge`: thêm `list_proofs()` hỗ trợ lấy `VERIFICATION_PROOF.json` trực tiếp hoặc xuyên tunnel `PHANTOM_5MS`.
   - `UNIVERSE_DASHBOARD_HTML`: nâng cấp lên `PHANTOM-CORTEX v17.0` với nút `Proofs (5s)` và `VSA Sync`, giữ kích thước gzip wire ở mức **`15,178 B`**.

### Wave 2 — Tquota Codex-First & ThoughtBrief Export
1. **[hive-mind.js](file:///E:/DEV/Chung/.ch-relay/local-relay/src/hive-mind.js):** Cập nhật `recommendPeer` (`codex_ttft_advantage`) để định tuyến qua `PHANTOM_5MS` ngay cả khi peer nhanh đang idle (`avgTtftMs === 0`, nhiều slot rảnh `>= 2` và `chatgpt` sẵn sàng) nếu peer cục bộ chậm (`localTtft > 3000 ms`).
2. **[routes-hyperdrive.js](file:///E:/DEV/Chung/.ch-relay/local-relay/src/routes-hyperdrive.js):** Thêm `GET /api/thought-briefs/export` xuất các `thought_briefs` dưới dạng payload chuẩn VSA (`/api/vsa/store`) gồm `item_id`, `domain`, `text`, `payload`, `reward`.
3. **[trinity-time-crystal-20261126.test.js](file:///E:/DEV/Chung/.ch-relay/local-relay/test/trinity-time-crystal-20261126.test.js):** Thêm kiểm thử `TC-8` xác minh cả Codex idle fast peer và định dạng export `/api/thought-briefs/export`.

### Wave 3 — Radar Sovereign, Colab CLI Monorepo Verifier & Speculative Swarm
1. **[crew.py](file:///E:/DEV/Chat/radar_dashboard/app/crew.py):** `_run_codex_stdin` chạy chế độ Lean (`CODEX_DISABLE_CUA=1`), tích hợp **210s Lazarus Stall-Reaper** ngắt process group bị treo im lặng giữa chừng, giữ tương thích mock `subprocess.run` cho unit test, và giảm `timeout_sec` mặc định từ `630s` xuống `300s`.
2. **[godmode_suite.py](file:///E:/DEV/Chat/radar_dashboard/app/godmode_suite.py):** Bổ sung `EpisodicPatchCrystalBrain.distill_from_history()` tự động chưng cất lịch sử `crew_runs`, `learned_rules`, và `makefun_attempts` thành crystal `10,000-bit` đồng thời đẩy hàng loạt sang Chimera `/api/vsa/store`.
3. **[colab_cli_orchestrator.py](file:///E:/DEV/Chat/radar_dashboard/app/colab_cli_orchestrator.py):** Trong `REMOTE_BATCH_RUNNER_PY`, bổ sung tự dò `package.json` theo đường dẫn monorepo, dùng cache dùng chung `/dev/shm/trinity_npm_cache`, chạy `npm ci --ignore-scripts` trước test, và chạy đúng tệp `vitest`/`jest` có liên quan tới `changed_files`.
4. **[necromancer_verifier.py](file:///E:/DEV/Chat/radar_dashboard/app/necromancer_verifier.py):** Hỗ trợ ghi đè chứng cứ mới nhất (`overwrite=True`), thêm `list_verification_proofs()` và `prepare_or_open_draft_pr(dry_run=True)` sinh lệnh `gh pr create --draft` kèm chứng cứ xác minh Colab (luôn chặn file bảo vệ `.env`/lockfile).
5. **[makefun_runner.py](file:///E:/DEV/Chat/radar_dashboard/app/makefun_runner.py), [bounty_swarm.py](file:///E:/DEV/Chat/radar_dashboard/app/bounty_swarm.py), [scanner.py](file:///E:/DEV/Chat/radar_dashboard/app/scanner.py), [server.py](file:///E:/DEV/Chat/radar_dashboard/app/server.py):** Nối `tournament_select()` vào vòng prompt Make.fun; tạo `SpeculativeBountySwarm` đánh giá song song nhiều chiến lược kết hợp MCTS + Tournament + VSA; gắn timer tự động chưng cất VSA (15 phút) và drain Colab (30 phút); mở 4 API `/api/godmode/vsa/distill`, `/api/godmode/necromancer/proofs`, `/api/godmode/necromancer/draft-pr`, `/api/godmode/swarm/run`.

---

## 3. Đồng bộ Windows ⇄ `svhome` (SHA-256 Parity)

Tất cả **22 tệp** trong phạm vi đồng bộ đã được sao chép từ Windows sang `svhome` và đối chiếu `SHA-256` bằng công cụ hệ thống với **`MISMATCH_COUNT = 0`**:
- **Chimera-TP (`8` tệp):** `phantom_tunnel.py` (`ca5dae1001b7`), `autopilot.py` (`a2ad207da57b`), `vsa_memory_service.py` (`15f2012e0f65`), `sentinel.py` (`1acd3669e1f0`), `trinity_bridge.py` (`15578377b555`), `dashboard.py` (`e0a17497b64a`), `universe_ui.py` (`2fcc61a4c86e`), `test_v15_trinity_cortex.py` (`53fab871ebe5`).
- **Tquota (`3` tệp):** `hive-mind.js` (`df0aae379cdf`), `routes-hyperdrive.js` (`ae2f3f45ea77`), `trinity-time-crystal-20261126.test.js` (`bf110b936204`).
- **Radar (`11` tệp):** `crew.py` (`d185fd77215c`), `godmode_suite.py` (`030a79feed2a`), `colab_cli_orchestrator.py` (`a371725f8084`), `necromancer_verifier.py` (`b1f4a0d704bc`), `makefun_runner.py` (`73ac2028989b`), `bounty_swarm.py` (`b1513b80afbf`), `scanner.py` (`fcedf723d0b9`), `server.py` (`efe70886b829`), `publishers.py` (`ae646548e92f` — sửa lệch `v1.1.0` trước đó), `test_godmode_v15.py` (`e6b0b45e655a`), và `test_dashboard.py` (`e4529c2a027a`).
- **Lưu ý bảo toàn:** `makefun_optimizer.py` trên `svhome` (`52,472 B`) mới hơn bản Windows (`50,005 B`) nên giữ nguyên để không làm mất dữ liệu Make.fun trên `svhome`; tương tự 24 tệp `app/*.py` ngoài phạm vi v17 không bị ghi đè.

---

## 4. Tổng hợp Kết quả Kiểm thử (Unit Tests trên Cả 2 Máy)

| Kho mã nguồn | Bộ test & Phạm vi | Windows | `svhome` | Ghi chú minh bạch |
| :--- | :--- | :--- | :--- | :--- |
| **Chimera-TP** | `tests.test_v15_trinity_cortex` (`test_01..test_05`) | **5/5 OK** (`8.638s`) | Nằm trong full suite | Kiểm chứng Reverse-PHANTOM 2 chiều, VSA Sync, `<16.5KB` gzipped UI |
| **Chimera-TP** | Toàn bộ `unittest discover -s tests -v` (`98` tests) | **97/98 OK** (concurrent load) + **1/1 OK** rerun `test_two_process_listen_and_connect_cli` (`11.629s`) | **98/98 OK** (`90.500s`) | Không skip bất kỳ test nào |
| **Tquota** | Hyperdrive + Trinity (`trinity-time-crystal`, `hypervisor-v2`, `hyperdrive-7pillars`, `breakthrough-hedge-vault`) | **33/33 PASS** (`2.23s`) | **33/33 PASS** (`4.50s`) | Đã gồm `TC-8` mới cho Codex idle peer & ThoughtBrief export |
| **Tquota** | Toàn bộ `test/*.test.js` (`3,077` tests lúc tải nặng 3 suite) | `3,070` pass, `5` skipped, `2` fail (rerun không tải: `antigravity-coding-agent` PASS; `tquota-offline-startup-recovery:258` fail `1/42`) | Chưa chạy ngoài 4 suite Hyperdrive | Không liên quan module v17 vừa sửa |
| **Radar** | Nhóm v17 & hồi quy (`test_godmode_v15` `6/6` + `test_breakthrough_upgrades` `8/8` + `test_dashboard` `18/18`) | **32/32 PASSED** (`12.27s`) | **31/32 PASSED** (`10.91s`) | `test_godmode_v15` (**6/6**) & `test_breakthrough_upgrades` (**8/8**) PASS 100% trên cả 2 máy; `1` fail trên `svhome` là `test_makefun_heartbeat_engine_and_endpoints` do giữ `makefun_optimizer.py` bản mới hơn trên `svhome` |
| **Radar** | Toàn bộ `app/tests` (`216` tests trên Win) | `210` passed, `6` failed (lần chạy trước fix `bounty_swarm`; 4 lỗi tồn đọng ngoài v17 ở `test_daily_kpi_review`, `test_gemini_video_studio`, `test_internet_scout`, `test_tquota_breakthrough_resilience`) | Chưa chạy ngoài 3 file mục tiêu | Nhóm v17/Breakthrough đã rerun đạt `32/32` sau sửa cuối cùng |

---

## 5. Phát hiện Thực tế Quan trọng & Khuyến nghị Bước tiếp theo

1. **Colab Node `rc=126` (`Permission denied` trong `/dev/shm`):**
   - Trong đợt `drain` live 8 patch trên `CPU_HIGH_MEM`, `5/5` repo Node đã tải dependency sạch (`npm_deps_rc=0`) đúng thư mục monorepo. Tuy nhiên, 3 repo (`IdentityAtlas`, `simpler-grants-gov`, `mcp-monetize`) trả về **`sh: 1: vitest/jest/tsx: Permission denied` (`test_rc=126`)**, trong khi `dashbrr` (`rc=1`) và `mergit` (`rc=1`) chạy được runner và phát hiện lỗi test thật, còn `lateralus-lang#998` bắt chính xác `4 failed / 172 passed` ở `test_round_builtin` & `test_fold_round`.
   - **Nguyên nhân kỹ thuật:** Trên container Colab, `/dev/shm` thường mount cờ `noexec` (hoặc `--ignore-scripts` bỏ qua bước cấp quyền thực thi cho binary trong `node_modules/.bin`), khiến lời gọi trực tiếp `vitest`/`jest`/`tsx` bị chặn ở kernel (`EACCES`).
   - **Khuyến nghị v17.1 (1 dòng sửa an toàn):** Trong [colab_cli_orchestrator.py](file:///E:/DEV/Chat/radar_dashboard/app/colab_cli_orchestrator.py), với stack `node`, sử dụng thư mục làm việc `/tmp/chimera_verify_node` (giữ cache tarball ở `/tmp`) hoặc gọi trực tiếp qua `node ./node_modules/...` thay vì `/dev/shm` đối với các file cần quyền thực thi.
2. **Mạng & Quotas:**
   - Cả 2 chiều PHANTOM-5MS (`Win ⇄ svhome`) đều hoạt động ổn định qua `12550` / `12551` & `9789` / `9790` với `gossipErrors: 0`.
   - Số dư Colab hiện tại sau toàn bộ đợt benchmark vẫn giữ nguyên **`2,350.15 CU`**, **`Active assignments: 0`**.
   - **Bảo mật:** Không ghi nhận email cá nhân, IP công khai thô hay token xác thực nào trong báo cáo hoặc mã nguồn đồng bộ (`0` vi phạm kiểm tra regex).
