# Báo Cáo Đánh Giá Hiệu Suất Trước & Sau Nâng Cấp: Trinity v16 (Chimera-TP × Tquota Codex-First × Radar Sovereign)

**Phạm vi nâng cấp:** [Chimera-TP](file:///E:/dev/chimera-tp) · [Tquota (`local-relay`)](file:///E:/DEV/Chung/.ch-relay/local-relay) · [Radar Dashboard (`radar_dashboard`)](file:///E:/DEV/Chat/radar_dashboard) · **Google Colab CLI Anti-Congestion Fleet (`CPU_HIGH_MEM`)**  
**Trọng tâm kiến trúc:** Tối ưu **Tquota thuần cho Codex (`chatgpt` / `/v1/responses`)**, nối mạng **Chimera C11 AVX2 VSA & Hard Kill-Switch xuyên `PHANTOM_5MS`**, vá triệt để **`SIGKILL` khi restart Radar trên `svhome`**, và biến bộ não God-Mode thành vòng khép kín tạo **bằng chứng patch kiểm chứng thật (`VERIFICATION_PROOF.json`)**. *(Giữ nguyên cấu hình Antigravity theo chỉ đạo, không đào sâu Antigravity.)*

---

## 1. Bảng Đối Chiếu Hiệu Suất Thực Đo: TRƯỚC (BEFORE) vs SAU (AFTER)

Toàn bộ số liệu dưới đây được đo trực tiếp trên hệ thống sống Windows (`12T`, `30.85 GB RAM`) và `svhome` (`2C/4T`, `10.61 GB RAM`) trước và sau khi triển khai mã nguồn v16:

| Hạng mục / Chỉ số đo | TRƯỚC (`BEFORE`) | SAU (`AFTER`) | Mức cải thiện / Ghi chú xác thực |
| :--- | :--- | :--- | :--- |
| **Tquota `svhome` `gossipErrors`** | **`225 / 450` (`50.0%` lỗi liên tục)** | **`0 / 21` (`0.0%` lỗi)** *(Win: `0 / 34` ngay cả qua 4 lần fallback)* | **Giảm `-100%` lỗi gossip** nhờ gỡ env chết `:12550` trên `svhome` & thêm circuit-breaker `120s` theo từng transport trong [hive-mind.js](file:///E:/DEV/Chung/.ch-relay/local-relay/src/hive-mind.js) |
| **Tquota `svhome` RSS (Bộ nhớ sống)** | **`484.6 MB`** (`496,200 KB`, VSZ `20.0 GB`) | **`277.9–284.6 MB`** (`291,420 KB` OS / `279.5 MB` telemetry) | **Giảm `-41.3%` đến `-42.3%` RSS** (`~200 MB` RAM giải phóng cho `svhome`) nhờ `--max-old-space-size=384` & `TQUOTA_TELEMETRY_CACHE_MAX_BYTES=4194304` |
| **Tquota Windows `/v1/models` Latency** | `p50 = 50.84 ms`, **`p95 = 2,702.17 ms`** | **`p50 = 26.53 ms`, `p95 = 38.54 ms`** | **`p95` nhanh hơn `70.1x`** (`svhome`: `p50 = 27.53 ms`, `p95 = 47.61 ms`) |
| **Tquota Codex `/v1/responses` Smoke Test** | Chưa mở mặc định KV-cache affinity (`x-tquota-hive-cache-route: 1`) | **Mở mặc định cho `chatgpt`** + TTFT arbitrage qua `PHANTOM_5MS` | Live HTTP `200` với `gpt-6.2-sol`: **`443.9 ms` (`svhome`)** & **`2,800.6 ms` (Win)**; `svhome` `vaultCoalesceHits: 1`, `fastOrigin` Win tự hồi phục sau cooldown |
| **Radar `svhome` Shutdown / Restart** | Treo hết `stop-sigterm` **`20,000 ms` → `SIGKILL` (`status=9/KILL`)** | Restart #1: **`766 ms`** · Restart #2: **`741 ms`** (`0` `SIGKILL`) | **Nhanh hơn `~26.5x`** nhờ async-signal-safe `Event` watcher trong [run_dashboard.py](file:///E:/DEV/Chat/radar_dashboard/run_dashboard.py), thu hồi `Popen` group trong [crew.py](file:///E:/DEV/Chat/radar_dashboard/app/crew.py) & `KillMode=mixed` |
| **Radar `svhome` RSS (Bộ nhớ sống)** | **`338.0 MB`** (`346,092 KB`) | **`164.1 MB`** (`168,012 KB`) | **Giảm `-51.4%` RSS** (`-173.9 MB`) |
| **Chimera VSA 10,000-bit & Mã hóa Crystal** | `/api/vsa/stats` = `HTTP 404`; Python encode **`25.119 ms`** (Win) / **`12.919 ms`** (`svhome`) | Endpoint `/api/vsa/*` sống (`backend: "c11_avx2"`); cached encode **`5.134 ms`** (Win, **`4.9x` nhanh hơn**); quét `1,000` vector int bitcount **`0.758 ms` (Win)** / **`1.535 ms` (`svhome`)** *(C11 `vsa_hamming` `2.807 ms` Win / `5.327 ms` `svhome`)* | Radar `patch_brain` đã nối live vào Chimera (`vsa_backend: "chimera_c11_avx2"`) qua [vsa_memory_service.py](file:///E:/dev/chimera-tp/chimera_tp/vsa_memory_service.py) |
| **Hard Kill-Switch Chimera → Radar** | Chỉ đổi cờ trong RAM trên Chimera, Radar vẫn chạy bình thường | Bật/tắt từ Win Chimera → xuyên **`PHANTOM_5MS` (`7.62 ms` RTT)** → `svhome` Radar lật **`paused: true / false`** ngay (`1.75–2.16 ms` nội bộ `svhome`, `~1.45s` tổng 2 chiều) | Có cổng pre-flight trong `crew.py` chặn đốt token ngay khi `paused=True` |
| **7 Patch thật trong `workspaces/` (`svhome`)** | Đắp chiếu `0/7` được kiểm chứng độc lập | **Necromancer Verifier** đóng gói **`7/7` (`100%`)** lên **Colab `CPU_HIGH_MEM` (`50.99 GB RAM`, `0.15 CU/hr`, 0 GPU congestion)** | **`7/7 clean_apply`** trên upstream HEAD, **`2/7 verified=True` (`test_rc=0`)**, sinh **`7/7` file `VERIFICATION_PROOF.json`**, `gdrive` sync `19` kết quả, **tiêu hao Colab `~0.00 CU` (`2,350.15 CU`, `Active assignments: 0`)** |
| **Make.fun Digital-Twin Tournament Gate** | Tách rời `MakefunArenaEvolver` | Huấn luyện trên toàn bộ **`58` điểm thi thật** trong `makefun_attempts` + MAP-Elites + lọc đa dạng Jaccard | Chấm & xếp hạng Top-3 trong **`7.356 ms`** qua `POST /api/godmode/makefun/tournament` |

*(Ghi chú kỹ thuật trung thực về vi chuẩn VSA: Khi quét từng cặp `bytes` qua `ctypes` `vsa_hamming` `1,000` lần từ Python, chi phí gọi FFI `~2.8–5.3 ms` cao hơn `(qi ^ vi).bit_count()` thuần trên số nguyên Python `0.76–1.54 ms`; đồng thời API `/api/vsa/recall` đã chia sẻ bộ nhớ ngữ nghĩa liên tiến trình qua `c11_avx2` và `encode_text_10k` tăng tốc `4.9x` nhờ lookup sign table + LRU token vector.)*

---

## 2. Chi Tiết Thay Đổi Theo Từng Hệ Thống

### Wave 1 — Chimera-TP Nervous System
- [vsa_memory_service.py](file:///E:/dev/chimera-tp/chimera_tp/vsa_memory_service.py): Dịch vụ `SharedVsaMemoryService` lưu trữ RAM + SQLite WAL, mã hóa siêu vector nhị phân `10,000-bit` (`1,250 B`) với cache LRU `4,096` token và so khớp `vsa_hamming` C11 AVX2 (`native_v12`).
- [trinity_bridge.py](file:///E:/dev/chimera-tp/chimera_tp/trinity_bridge.py): Nâng cấp `set_kill_switch()` gọi thực thi HTTP `POST /api/godmode/control` tới Radar cục bộ và chuyển tiếp an toàn (chống vòng lặp bằng cờ `from_peer`) qua `PHANTOM_5MS` sang peer Chimera (`svhome`).
- [dashboard.py](file:///E:/dev/chimera-tp/chimera_tp/dashboard.py): Mở endpoint `GET /api/vsa/stats`, `POST /api/vsa/store`, `POST /api/vsa/recall` và nối cờ chống lặp cho `/api/trinity/kill-switch`.
- [test_v15_trinity_cortex.py](file:///E:/dev/chimera-tp/tests/test_v15_trinity_cortex.py): Bổ sung `test_03_shared_vsa_avx2_memory_service` và `test_04_kill_switch_actuates_radar_control_endpoint`.

### Wave 2 — Tquota Codex-First Hyper-Optimization
- [hive-mind.js](file:///E:/DEV/Chung/.ch-relay/local-relay/src/hive-mind.js):
  1. **Per-Transport Circuit Breaker:** Khi `fastOrigin` lỗi 2 lần liên tiếp sẽ vào cooldown `120s` (`cooledFastOrigins`), chuyển fallback sang Tailscale mà **không cộng oan `gossipErrors`**, và tự động phục hồi khi hầm `PHANTOM_5MS` `:12550` sống lại.
  2. **`PHANTOM_5MS` Vault & Codex TTFT Arbitrage:** `findVaultPeer` ưu tiên `fastOrigin` khỏe mạnh; `recommendPeer` bổ sung nhánh `codex_ttft_advantage` riêng cho `requestedProvider === 'chatgpt'` khi peer qua `PHANTOM_5MS` nhanh hơn tối thiểu `800 ms` và còn `>= 2` slot trống.
- [server.js](file:///E:/DEV/Chung/.ch-relay/local-relay/src/server.js): Mở mặc định `warm_kv_cache_affinity` & `codex_ttft_advantage` cho mọi yêu cầu Codex (`chatgpt`, trừ khi client gửi `x-tquota-hive-cache-route: 0`), truyền `sloTelemetry` `proxyTtftMs.p50Ms` vào `hiveMind.recommendPeer(...)`.
- **Systemd `svhome` (`tquota.service`):** Gỡ bỏ `TQUOTA_PHANTOM_PEER_ORIGIN=http://127.0.0.1:12550` bị sai hướng trên Linux, đặt `--max-old-space-size=384` và `TQUOTA_TELEMETRY_CACHE_MAX_BYTES=4194304`.
- [trinity-time-crystal-20261126.test.js](file:///E:/DEV/Chung/.ch-relay/local-relay/test/trinity-time-crystal-20261126.test.js): Bổ sung test `TC-6` (circuit-breaker `0 gossipErrors`) và `TC-7` (`codex_ttft_advantage` + `findVaultPeer` `PHANTOM_5MS`).

### Wave 3 — Radar Sovereign Stability, Causal Memory, Necromancer & Tournament Gate
- [run_dashboard.py](file:///E:/DEV/Chat/radar_dashboard/run_dashboard.py), [scanner.py](file:///E:/DEV/Chat/radar_dashboard/app/scanner.py), [crew.py](file:///E:/DEV/Chat/radar_dashboard/app/crew.py): Async-signal-safe `SIGTERM` event + watcher thread + watchdog `4s`, dừng `KvWarmHeartbeat`, thu hồi mọi `Popen` process group đang mở để thoát `status=0/SUCCESS` trong `~0.75s` (cùng `KillMode=mixed` trong `radar-dashboard.service`).
- [sovereign_governor.py](file:///E:/DEV/Chat/radar_dashboard/app/sovereign_governor.py) & [server.py](file:///E:/DEV/Chat/radar_dashboard/app/server.py): Trạng thái tạm dừng bền vững trên đĩa `sovereign_control.json` qua `GET/POST /api/godmode/control`, được kiểm tra ngay trước lúc `crew.py` gọi AI solver, kèm tiêm Top-3 VSA `patch_crystals` + active `learned_rules` + `WeightClassScheduler` vào `AGENT_SOLVER_BRIEF.md`.
- [godmode_suite.py](file:///E:/DEV/Chat/radar_dashboard/app/godmode_suite.py): Nâng cấp `EpisodicPatchCrystalBrain` dùng sign-table cache + kết nối Chimera `/api/vsa/*` (`vsa_backend: "chimera_c11_avx2"`).
- [necromancer_verifier.py](file:///E:/DEV/Chat/radar_dashboard/app/necromancer_verifier.py), [colab_cli_orchestrator.py](file:///E:/DEV/Chat/radar_dashboard/app/colab_cli_orchestrator.py) & [server.py](file:///E:/DEV/Chat/radar_dashboard/app/server.py): Quét `workspaces/*/solution.patch` qua `/api/godmode/necromancer/patches` và `/api/godmode/necromancer/queue`, chạy thật trên Colab `CPU_HIGH_MEM` (`git clone`, decode `raw|gzip` `patch_b64`, `git apply`, `py_compile`/test), và xuất `VERIFICATION_PROOF.json` tại chỗ (không tự đẩy PR).
- [makefun_arena_evo.py](file:///E:/DEV/Chat/radar_dashboard/app/makefun_arena_evo.py): Thêm `tournament_select()` + endpoint `POST /api/godmode/makefun/tournament`.
- [test_godmode_v15.py](file:///E:/DEV/Chat/radar_dashboard/app/tests/test_godmode_v15.py): Bổ sung `test_05_sovereign_control_necromancer_and_tournament_gate`.

---

## 3. Kết Quả Kiểm Thử Tự Động & Chi Tiết 7 Patch Necromancer

### Bộ test tự động sau lần chỉnh sửa cuối cùng
| Thành phần | Windows | `svhome` (Linux) | Ghi chú |
| :--- | :--- | :--- | :--- |
| **Chimera-TP (`unittest discover -s tests`)** | **`97 / 97` PASS** (`103.5s`) | **`97 / 97` PASS** | Toàn bộ v1..v15 + 2 test VSA/Kill-Switch mới đều xanh |
| **Tquota (`node --test` 4 suites)** | **`29 / 29` PASS** (`6.40s`) | **`29 / 29` PASS** (`5.20s`) | Bảo toàn `antigravity-upgraded`, `hypervisor-v2`, `pareto`, `trinity-time-crystal` (`TC-1..TC-7`) |
| **Radar (`pytest` 3 suites)** | **`26 / 26` PASS** (`13.93s`) | **`25 / 26` PASS** (`5/5` `test_godmode_v15`, `3/3` `test_turbo_suite`, `17/18` `test_dashboard`) | 1 fail trên `svhome` ở `test_publishers_devto_hashnode_idempotent_update_and_channels` (`app/publishers.py` chưa đồng bộ `v1.2.0` từ Win trước đó, nằm ngoài phạm vi sửa) |

### Kết quả Necromancer Verifier thực chạy trên Google Colab `CPU_HIGH_MEM` (`50.99 GB RAM`, `0.15 CU/hr`)
| Workspace | Repo & Issue | Kích thước diff | `git apply` | Syntax | `test_rc` / Trạng thái | Thời gian (`ms`) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `KyaniteHQ__threadsift__issue_725` | `KyaniteHQ/threadsift#725` | `1,778 B` | `clean_apply` (1 file) | `True` | `rc=0` · **`verified_for_pr=True`** | `1,832.15` |
| `bad-antics__lateralus-lang__issue_947` | `bad-antics/lateralus-lang#947` | `2,619 B` | `clean_apply` (2 files) | `True` | `rc=0` · **`verified_for_pr=True`** | `1,448.39` |
| `Fortigi__IdentityAtlas__issue_1683` | `Fortigi/IdentityAtlas#1683` | `15,640 B` | `clean_apply` (12 files) | `True` | `rc=254` *(thiếu `npm ci` trong `/dev/shm`)* | `6,822.97` |
| `HHS__simpler-grants-gov__issue_6832` | `HHS/simpler-grants-gov#6832` | `3,032 B` | `clean_apply` (1 file) | `True` | `rc=254` *(thiếu `npm ci` trong `/dev/shm`)* | `5,845.03` |
| `autobrr__dashbrr__issue_231` | `autobrr/dashbrr#231` | `12,433 B` | `clean_apply` (5 files) | `True` | `rc=254` *(thiếu `npm ci` trong `/dev/shm`)* | `836.61` |
| `odiseo159-beep__mergit__issue_25` | `odiseo159-beep/mergit#25` | `12,664 B` | `clean_apply` (4 files) | `True` | `rc=254` *(thiếu `npm ci` trong `/dev/shm`)* | `763.94` |
| `RitualDev-Lab__mcp-monetize__issue_3` | `RitualDev-Lab/mcp-monetize#3` | `6,993 B` | `clean_apply` (5 files) | `True` | `rc=127` *(toolchain/npm thiếu trong env tối giản)* | `1,767.82` |

**Hướng nâng cấp tiếp theo hợp lý nhất (từ kết quả thực đo):** Cho phép tùy chọn `run_npm_ci: true` nhẹ (`npm ci --ignore-scripts --silent`) bên trong `/dev/shm/chimera_verify` trên Colab `CPU_HIGH_MEM` (`50.99 GB RAM`) đối với các patch Node đã qua bước `clean_apply` nhằm thu nốt `test_rc=0` cho 5 workspace Node còn lại.
