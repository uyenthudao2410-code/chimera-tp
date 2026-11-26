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

---

## 6. Trinity v17.1 Hardening, 75/75 Radar Parity & Live Production Proofs

Sau khi nghiệm thu v17, hệ thống được gia cố thêm bản vá **Trinity v17.1** để đóng 4 lỗ hổng vận hành thực tế (đồng bộ 100% Radar `app/*.py`, tự động nối lại PHANTOM + dập triệt để bão retransmit khi khởi động lại daemon, chạy Node trên `/tmp` ngoài `/dev/shm` `noexec`, và chế độ headless Lean `codex exec` không kéo `cua-repl`).

### 6.1 Các bản vá v17.1 đã triển khai & đồng bộ `Win ⇄ svhome`
1. **Đồng bộ toàn bộ Radar `75/75` `app/*.py` + hermetic test fixture:**
   - Kéo 14 module `app/*.py` mới hơn từ `svhome` về Windows (`agency_closer.py`, `approval_dispatch.py`, `commerce_feed.py`, `commerce_policy.py`, `competitor_intel.py`, `experience_memory.py`, `learning_content.py`, `makefun_optimizer.py`, `mcp_growth_scout.py`, `security_hunter.py`, `self_debate.py`, `self_upgrade.py`, `shadow_bounty.py`, `submission_journal.py`) và đồng bộ ngược lại mọi bản sửa v17.1.
   - Kiểm tra SHA-256 chuẩn hóa LF trên toàn bộ **`75/75` tệp `radar_dashboard/app/*.py`**: `win_only=0`, `sv_only=0`, **`MISMATCH_COUNT=0`**.
   - Trong [test_dashboard.py](file:///E:/DEV/Chat/radar_dashboard/app/tests/test_dashboard.py) (`_prepare_temp_radar_dir`), cố định `cfg.setdefault("guardrails", {})["min_makefun_pool_usd"] = 100.0` cho fixture test `$100`, giữ nguyên ngưỡng sản xuất `150.0` trong `job_radar/config.json` của `svhome` và đưa bộ test Radar trên cả 2 node lên **`51/51 PASSED`**.
2. **Chimera Watchdog Tự nối lại + Fix bão retransmit `506 MB` & Deadlock `_state_lock`:**
   - Trong [phantom_tunnel.py](file:///E:/dev/chimera-tp/chimera_tp/phantom_tunnel.py): thêm keepalive `10s`, watchdog `pong_stale_s=35s`, cooldown `10s`, tái đấm full budget (`192` sockets, `900` sprays, `6` waves, `3.5s`), cơ chế nâng cấp tự động không gián đoạn `TAILSCALE_FALLBACK -> PHANTOM_5MS_DIRECT` mỗi `15s`, và dọn session fallback rảnh `> 120s` trên server.
   - Khi kiểm chứng thực tế phát hiện sự cố **bão retransmit `506 MB` UDP (`CLOSE-WAIT` kẹt trên `12551`/`9790`)** và **deadlock `_state_lock`** lúc chuyển phiên: đã thêm `_reset_conns_for_new_session()` khi tạo session mới trong `connect()`, trả `_P_CLOSE` cho `conn_id` mồ côi ở cả Server & Client, giới hạn `inflight <= 32` (`recv(16384)`), áp dụng exponential backoff + ngưỡng tử `_retransmit_pending()` (`max 24/tick`, `6/stream`, `_P_OPEN` tối đa `12` lần / `8s`, `tx_buffer` treo `> 15s`, reaper `CLOSE-WAIT` `> 6s`), giới hạn `_P_NACK` (`0.08s`, cửa sổ `16`), đồng thời chuyển `_state_lock` sang `RLock` và gọi `self.status()` ngoài lock ở nhánh `preserve_on_fallback_fail`.
   - Bổ sung `test_06`, `test_07`, `test_08` trong [test_v15_trinity_cortex.py](file:///E:/dev/chimera-tp/tests/test_v15_trinity_cortex.py).
3. **Colab Node `/tmp` Exec & Lọc đường dẫn Monorepo ([colab_cli_orchestrator.py](file:///E:/DEV/Chat/radar_dashboard/app/colab_cli_orchestrator.py)):**
   - `REMOTE_BATCH_RUNNER_PY` tự chuyển `is_node_job` sang `/tmp/chimera_verify_node` (tránh `/dev/shm` gắn cờ `noexec`), dùng cache `NPM_CONFIG_CACHE="/tmp/trinity_npm_cache"`, cấp `os.chmod(..., 0o755)` cho `node_modules/.bin/*`, và lọc chặt `node_tests` theo `fp_cf.relative_to(pkg_dir)`.
4. **Headless Lean `codex exec` diệt treo `cua-repl` ([crew.py](file:///E:/DEV/Chat/radar_dashboard/app/crew.py), [self_upgrade.py](file:///E:/DEV/Chat/radar_dashboard/app/self_upgrade.py)):**
   - Thêm `build_lean_codex_exec_cmd(...)` dùng `--ignore-user-config -c openai_base_url="http://127.0.0.1:12500/v1" [-c model_catalog_json="..."] --ephemeral --dangerously-bypass-approvals-and-sandbox --skip-git-repo-check` (tuyệt đối không gắn `--model`/`-m`/`--effort`) cho `_run_codex_stdin` và `self_upgrade.py`, giữ nguyên `makefun_runner.py` không có `-c` theo ràng buộc hồi quy `test_ai_solvable_channels.py`.

### 6.2 Kết quả Kiểm thử Đơn vị (v17.1 Final)

| Kho mã nguồn | Bộ kiểm thử | Windows | `svhome` | Parity SHA-256 (LF) |
| :--- | :--- | :--- | :--- | :--- |
| **Chimera-TP** | `tests.test_v5_phantom` + `tests.test_v15_trinity_cortex` (`14` tests gồm `test_06..test_08`) | **14/14 OK** (`23.224s`) | **14/14 OK** (`26.317s`) | `phantom_tunnel.py` (`2547ec7609b9038c`) & `test_v15_trinity_cortex.py` (`0e5354e6da5656d2`) khớp `True` |
| **Radar** | `5` bộ: `test_godmode_v15` (`6`), `test_breakthrough_upgrades` (`8`), `test_ai_solvable_channels` (`8`), `test_closed_loop_self_upgrade` (`11`), `test_dashboard` (`18`) | **51/51 PASSED** (`18/18` `test_dashboard` sau sửa cuối `8.08s`; full 51 trên Win trước sửa cuối `21.44s`) | **51/51 PASSED** (`17.31s`) | **75/75** `app/*.py` + `test_godmode_v15.py` + `test_dashboard.py` khớp `True` (`MISMATCH_COUNT=0`) |
| **Tquota** | `4` bộ Hyperdrive + Trinity (`TC-8` Codex idle peer & export) | **33/33 PASS** (`2.23s`) | **33/33 PASS** (`4.50s`) | Đồng nhất từ v17 |

### 6.3 Ba Bằng chứng Sản xuất Thực tế (Live Production Proofs)

1. **Live Proof #1 — Tự động khôi phục PHANTOM `5ms` & Dập bão retransmit (0 thao tác tay):**
   - Khởi động lại duy nhất `chimera-hyper-daemon.service` trên `svhome`. Không gọi `/api/phantom/connect`, Windows tự phát hiện mất pong và đấm lại **`PHANTOM_5MS_DIRECT`** sau **`30s`** (`rtt: 7.11 ms -> 4.27 ms`, `punches_ok=2`, `reconnect_count=1`, `svhome` xác nhận `punched: true`).
   - Reverse-PHANTOM trên `svhome` phục vụ lại tức thì: `http://127.0.0.1:12551/healthz` trả **`43,016 B`** JSON HTTP **`200`** trong **`95.4 ms`**; `http://127.0.0.1:9790/api/health` trả **`517 B`** HTTP **`200`** trong **`13.73 ms`**.
   - Kiểm tra delta `2s` sau CURL: **`tx_delta = 0 B`, `rx_delta = 0 B`** (`tx_total = 31,990 B`, giảm **`15,819x`** so với mức bão `506,066,692 B` trước bản vá).
   - Tquota Hive `/api/hive/status?sync=1` trên `svhome` khôi phục sạch về `via: http://127.0.0.1:12551`, `transport: "PHANTOM_5MS"`, `availableSlots: 50`, **`gossipErrors: 0`**.
2. **Live Proof #2 — Colab Node `/tmp` Exec (Chấm dứt hoàn toàn `rc=126`):**
   - Xếp hàng và drain **`8/8`** patch trên Colab `CPU_HIGH_MEM` (`allow_heavy_gpu: false`, `keep_session: false`, `stopped: True`):
     - **`3/8` ĐẠT `verified_for_pr=True` (`test_rc=0`):** `autobrr/dashbrr#231` (`npm test --silent` — trước đây lỗi, nay verified thật), `KyaniteHQ/threadsift#725`, `bad-antics/lateralus-lang#947`.
     - **`5/8` `test_rc=1`** đều là lỗi test/assertion thật trong mã nguồn ứng viên (`RitualDev-Lab/mcp-monetize#3`, `HHS/simpler-grants-gov#6832`, `Fortigi/IdentityAtlas#1683`, `bad-antics/lateralus-lang#998`, `odiseo159-beep/mergit#25`), với bộ lọc `IdentityAtlas` đã loại sạch file `app/ui/...` khỏi lệnh `vitest` của `app/api`.
     - **Tỷ lệ `test_rc=126` / `Permission denied`: `0/8`**.
   - Kiểm tra `/colab usage </dev/null` ngay sau drain: **`Active assignments: 0`**, số dư **`2,350.14 CU`**, `Usage rate: 0.00/hr`.
3. **Live Proof #3 — Headless Lean `_run_codex_stdin` Zero-`cua-repl` trên `svhome`:**
   - Gọi trực tiếp `app.crew._run_codex_stdin(...)` kèm thread giám sát `ps -eo args` mỗi `0.15s` (`48` mẫu): trả `rc=0`, đáp chuẩn `'OK'` (`17,372` tokens) trong **`8,006.5 ms`**, **`cua_seen=False`**, và **`lingering_cua=0`**.

### 6.4 Trạng thái Hạ tầng Trực tuyến Hiện tại (Snapshot cuối phiên)

| Thành phần | Windows (Controller / Peer) | `svhome` (24/7 Single-Master Server) | Đánh giá sẵn sàng |
| :--- | :--- | :--- | :--- |
| **Chimera-TP** | `ChimeraHyperDashboard` chạy nền (`PHANTOM_5MS_DIRECT`, RTT **`4.27 ms`**, `ram=25.9 MB`, VSA **`152`** mục / recall `0.926 ms`) | `chimera-hyper-daemon.service` **`active`** (`38.6 MB` RSS, reverse `12551->12500` & `9790->9780`, VSA **`151`** mục / recall **`0.564 ms`**) | **Đạt 100%** — 2 chiều `PHANTOM_5MS`, tự reconnect không bão UDP |
| **Tquota (Codex-First)** | `1.2.9-local` (`PID 32404`, `66.7 MB` peer RSS, `5` tài khoản `chatgpt` + `2` `antigravity`, `gossipErrors: 0`) | `tquota.service` **`active`** (`395.8 MB` systemd RSS, `4` tài khoản `chatgpt` hoạt động + `1` cách ly, định tuyến `PHANTOM_5MS` `via 127.0.0.1:12551`, `gossipErrors: 0`) | **Đạt 100% Codex-first** (không đụng phần Antigravity) |
| **Radar Sovereign** | Tắt có chủ đích (Standby; `WIN_RADAR_UP=False`, tránh xung đột single-master) | `radar-dashboard.service` **`active`** (`467.5 MB` systemd RSS, chế độ `SOVEREIGN_24X7`, **`151`** patch crystal, **`8`** Necromancer proofs mới nhất, Colab **`2,350.14 CU`** / `Active: 0`) | **Đạt & tự hành 24/7** trên `svhome`; 5 patch `test_rc=1` cần crew tự sửa vòng sau trước khi mở draft PR |

*(Ghi chú tồn đọng ngoài phạm vi v17.1: trên Windows còn 4 unit test nền cũ ở `test_daily_kpi_review`, `test_gemini_video_studio`, `test_internet_scout`, `test_tquota_breakthrough_resilience` và 1 case `tquota-offline-startup-recovery:258` đã ghi nhận từ trước khi mở v17, không thuộc chuỗi v17/v17.1.)*
