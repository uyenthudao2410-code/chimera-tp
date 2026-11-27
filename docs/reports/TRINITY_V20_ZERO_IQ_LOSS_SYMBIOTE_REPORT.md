# TRINITY v20 — CHIMERA ZERO-IQ-LOSS SYMBIOTE: IMPLEMENTATION & BEFORE/AFTER REPORT

- **Timestamp:** `2026-11-26 23:35+07`
- **Nodes Synchronized:** `win-desktop` (`E:\dev\chimera-tp`, `E:\DEV\Chung\.ch-relay\local-relay`, `E:\DEV\Chat\radar_dashboard`) ⇄ `svhome` (`/home/svhome/DEV/chimera-tp`, `/home/svhome/DEV/Tqouta/local-relay`, `/home/svhome/DEV/radar_dashboard`)
- **Upstream Preservation Reference:** `[Tquota Quota Drain Root Cause](t3-thread://v2/69366787-87c6-498a-a02a-c69508ade1d6/86801a41-7f90-445b-b2b9-213d71c7417f)` (`run 58/59/60` preserved 100%)

---

## 1. Zero-IQ-Loss Axiom Compliance (Verified Live)

No reasoning shortcuts, effort downgrades, weak-model summarization, or reserved tool schema mutations were introduced. Chimera (`~35.6 MB` Win / `~77.6 MB` `svhome`) acts strictly as a deterministic physical substrate.

| Invariant / Setting | BEFORE (`23:05+07`) | AFTER (`23:34+07`) | Verification Source |
|---|---|---|---|
| `limits.astraMinEffort` | `"max"` | `"max"` | `GET :12504/api/diagnostics` |
| `limits.astraMaxEffort` | `"max"` | `"max"` | `GET :12504/api/diagnostics` |
| `limits.solMinEffort` | `"max"` | `"max"` | `GET :12504/api/diagnostics` |
| `limits.hardCapMode` | `"shadow"` | `"shadow"` | `GET :12504/api/diagnostics` |
| `peerMesh.enabled` | `true` | `true` | `GET :12504/api/diagnostics` |
| OpenAI `collaboration.*` schemas | Protected (`run 60`) | Protected (`0` mutations) | `zero-leak-v2-20261126.test.js` (`Z3`) |
| Compaction / Stale-read detection | Full model / none | Deterministic `SHA-256` + `Z1/Z2` preserved (`0` weak-LLM calls) | `symbiote_engine.py`, `Z1–Z2` |

---

## 2. Five Pillars Implemented

1. **`CHIMERA-BONE-MARROW` (Out-of-V8 LZ4/Deflate Compression + Inflight Reaper + Streaming Vault Keys):**
   - `ChimeraSymbioteEngine` (`E:\dev\chimera-tp\chimera_tp\symbiote_engine.py`) provides bounded LRU LZ4 blob storage (`max_blob_bytes=6 MiB`, `max_entries=256`) using `chimera_tp.native.lz4_compress` / `lz4_decompress` with `zlib` fallback (`PUT /api/symbiote/blob/put`, `GET /api/symbiote/blob/get`).
   - `DetachedVault` (`E:\DEV\Chung\.ch-relay\local-relay\src\detached-vault.js`) now compresses stored SSE responses >= 4 KB outside V8 JS strings via `compressSseBytes` (`zlib.deflateRawSync`) / `decompressSseBytes` (`zlib.inflateRawSync`), enforces `maxInflightTtlMs` (`480_000 ms`) reaping on leaked `inflight` slots, and swaps string-concatenated `canonicalVaultKey` for streaming SHA-256 (`hashCanonicalStream`) with no `2 MB` size abort.
   - `server.js` immediately releases `rawText`, gates default `ingressWorkerPool` background ArrayBuffer duplication behind explicit `shadowTomography === true`, and binds `lease.addCleanup` so uncaptured requests cannot leak `detachedVault.inflightCount`.

2. **`CHIMERA-IMMORTAL-360S-BRIDGE` (Eliminate `360s 499` -> `503` Retry Storms):**
   - `DetachedVault` tracks `turnAliases` keyed by `toolRetryKey` + `stepSig` (`digestTurnStepSignature`), while Chimera exposes `/api/symbiote/immortal/{register,complete,lookup}` backed by Bone-Marrow LZ4.
   - In `server.js` (`processResponsesRequest`), **before** `toolGenerationRetryGuard.blocked(toolRetryKey)` can return `503 local-tool-timeout-retry`, Tquota checks `detachedVault.getResultByTurnKey`, awaits any live detached `getInFlightByTurnKey`, and queries Chimera `lookupImmortalRemote`, returning HTTP `200` (`x-tquota-vault: immortal-coalesced`, `0` new upstream calls) while preserving `outputs_required` safety for non-detached calls.

3. **`CHIMERA-TCP-SCALPEL` + Zero-Completed Hot Vaccine:**
   - In `stream-processor.js`, when `cut` triggers and `!shouldDrain` (e.g. `zeroDrainLocked` under `quota-saver`), `cancelCurrent(cut)` runs **immediately before** downstream batch yield/serialization, propagating `scalpelImmediate: true` into `onFinish`.
   - `server.js` (`recordUsageAndObserveAsync`) reports `completed` / `499` / `503` / `scalpelImmediate` telemetry non-blockingly to Chimera `POST /api/symbiote/observe-usage` (emitting Pulse `SYMBIOTE_COMPLETED_LEAK` on non-compact `cut=completed`), exposed via `GET :12504/api/symbiote/status` and `GET :12504/api/overmind/telemetry`.

4. **`CHIMERA-DETERMINISTIC-MERKLE-SHIELD` (KV-Cache Prefix Audit & Deterministic Stale-Read Detector):**
   - `chimera-symbiote-bridge.js` (`auditPrefixItems`) hashes `body.input` items via streaming SHA-256 without mutating prompts, detects mid-prefix breaks (`breakIndex`), and syncs asynchronously with Chimera `/api/symbiote/prefix/audit` & `GET /api/symbiote/kv-affinity`.
   - `ChimeraSymbioteEngine.detect_stale_file_reads` flags exact SHA-256 duplicate full-file reads in tool outputs deterministically (zero LLM cost).

5. **`CHIMERA-PRECOGNITION-HANDS` (Untracked Module Staging + Local Syntax Pre-Verifier):**
   - `necromancer_verifier.py` (`_stage_untracked_code_files`, `_cleanup_staged_untracked`, `_precog_verify_workspace`) stages newly created untracked non-protected code files with `git add -N` inside `ScopeFirewall` prior to `git diff HEAD` (resolving the `ModuleNotFoundError` class seen on new helper files) and verifies `.py`/`.js` syntax via Chimera `POST /api/symbiote/precog-verify` (with local `py_compile`/`node --check` fallback) before Colab enqueue (`blocked_by_precog_syntax`, `0` Colab CU wasted).

---

## 3. BEFORE vs AFTER Observed Metrics

### A. Live Daemon & Memory Telemetry (Windows + `svhome`)

| Metric | BEFORE (`2026-11-26 23:05+07`) | AFTER (`2026-11-26 23:33+07`) | Notes |
|---|---|---|---|
| **Win Tquota RSS** | `1,539.74 MB` (`1,383.91 MB` @+25s, `PID 3564`, `uptime 3858s`) | `475.76 MB` (`72s`) / `744.20 MB` (`280s`, `PID 15376`, active Codex load) | Fresh restarted worker under active traffic; `PID 3564` had stopped before rollout |
| **Win Tquota `heapUsed` / Limit** | `788.96 MB` / `1,216 MB` | `159.17 MB` (`72s`) / `358.53 MB` (`280s`) / `1,216 MB` | Early startup + active stream delta |
| **Win Tquota `largeObjectSpaceUsed`** | `535.06 MB` (`67.8%` of V8 heap) | `64.01 MB` (`72s`) / `222.21 MB` (`280s`) | Compression + streaming vault key active |
| **Win Tquota `external` / `arrayBuffers`** | `462.89 MB` / `182.21 MB` | `50.83 MB` / `38.42 MB` (`72s`), `90.78 MB` / `88.19 MB` (`280s`) | Direct raw buffer diet |
| **Win Tquota `detachedVault` live bytes** | `108` entries (`3.68 MB`), `0 B` saved (`0` hits / `135` misses / `0` coalesced) | `38` entries (`0.70 MB`), **`726,447 B` saved by compression** (~`49.7%` ratio) | Measured live at `280s` uptime |
| **Win Tquota `inflightCount` leak** | `4` leaked (`activeDetached: 0`) | `3` matching active requests + `maxInflightTtlMs` auto-reaper | Leak path closed via `lease.addCleanup` |
| **Win Tquota Symbiote Live Counters** | N/A | `prefixAudits: 45` (`10` clean, `35` breaks), `autocuts: 38`, `scalpelImmediateCuts: 38`, `completedLeaks: 0`, `chimeraSyncOk: 38` | `chimeraSyncErrors: 128` occurred only during ~3 min before `:9780` restarted |
| **Win ⇄ `svhome` `bootHash` parity** | Legacy pre-v20 | **`abe5495b750de9a3b7c0399a3e224e1812ce56d8f0102a5d9a6224cbc79684a3`** (`inSync: true` both nodes) | Exact match verified |
| **Chimera `ship-check --window 1.5`** | `loc_ram_mb: 27.44 MB` (`frame: 48.19 MB`), `peer_ram_mb: 80.98 MB`, **`ram_ok: false`** | **`ok: true`**, `loc_ram_mb: 35.58 MB`, **`peer_ram_mb: 77.59 MB` (`ram_ok: true`)**, `PHANTOM_5MS_DIRECT` (`5.59 ms`), `crdt_synced: true`, `dlp_clean: true` | `svhome` Chimera brought back under `80 MB` cap |
| **Colab Usage (`svhome` CLI)** | `2350.14 CU`, `0.00/hr`, `Active assignments: 0` | `2350.14 CU`, `0.00/hr`, **`Active assignments: 0`** | Zero CU consumed during v20 rollout |

### B. Live Chimera `:9780` Physical Benchmark Proofs (After Rollout)

| Benchmark | Measured Result |
|---|---|
| **Bone-Marrow LZ4 (`495,689 B` synthetic reasoning JSON)** | `codec: "lz4"`, `compressed_bytes: 2,079 B` (`ratio: 0.0042`), `roundtrip_ms: 17.7 ms`, `bit_exact_sha256: true` (`c241a8b5c4ab063a`) |
| **Bone-Marrow Aggregate Counter (`:9780/api/symbiote/status`)** | `blobs_stored: 9`, `raw_bytes_in: 922,324 B` -> `compressed_bytes_in: 268,714 B`, `lz4_saved_bytes: 653,610 B` (`avg_ratio: 0.2913`) |
| **Merkle Prefix Audit + KV-Affinity** | Append-only turn: `mid_prefix_break: false`; Mutated turn: `mid_prefix_break: true` (`break_index: 1`); `kv-affinity`: `acc_live_1` |
| **Deterministic Precog-Verify (`E:\dev\chimera-tp`)** | `ok: true`, `checked_files: 30`, `syntax_errors: []`, `duration_ms: 4722.56 ms` |

---

## 4. Test Matrix & Cross-Node SHA-256 Parity (`12/12`, `MISMATCH=0`)

| Component | Suites Verified | Windows Result | `svhome` Result |
|---|---|---|---|
| **Chimera-TP** | `test_v5_phantom`, `test_v18_overmind_cortex`, `test_v19_midbrain_dopamine`, `test_v20_symbiote_zero_iq_loss` | **21 / 21 passed** (`23.454s`) | **21 / 21 passed** (`19.163s`) |
| **Tquota** | All 12 suites (`symbiote-zero-iq-loss-v20` `S1–S6` + `zero-leak-v2` `Z1–Z4` + `lazarus-resilience` `T1–T5` + `midbrain-dopamine-v19` `MB-1..4` + `breakthrough-hedge-vault` + `hyperdrive-7pillars` + `trinity-time-crystal` + `pareto-quota-efficiency` + `model-alias-sol-effort` + `request-fallback` + `cache-norm-call-pairing` + `tool-generation-guard`) | **77 / 77 passed** (`20.03s`) | **77 / 77 passed** (`26.12s`) |
| **Radar Dashboard** | Targeted suite `app/tests/test_midbrain_v19.py` (`test_01..test_07`) | **7 / 7 passed** (`3.89s`) | **7 / 7 passed** (`0.82s`) |

> **Full Radar suite note:** On Windows, `pytest -q app/tests` reported `266 passed, 1 failed` (`test_daily_kpi_review.py::test_autonomous_bch_scheduling_and_config_api` asserted `auto_red_alert` while local clock after 21:00 GMT+7 selected `scheduled_21h_gmt7`). On `svhome`, `pytest -q app/tests --ignore=app/tests/test_daily_kpi_review.py` reported `266 passed, 8 failed` in pre-existing stale `svhome` `MakefunArenaEvolver` / `mcp_growth` / `devto` tests unrelated to `necromancer_verifier.py` or v20.

### Synced Files SHA-256 Parity (`MISMATCH=0`)

| File | SHA-256 Prefix (Win == `svhome`) |
|---|---|
| `chimera_tp/symbiote_engine.py` | `735992a12c11` |
| `chimera_tp/overmind_cortex.py` | `a0cae34fcee0` |
| `chimera_tp/dashboard.py` | `c0e82e00f8b7` |
| `tests/test_v20_symbiote_zero_iq_loss.py` | `2b38d346f85c` |
| `local-relay/src/chimera-symbiote-bridge.js` | `73f56a433853` |
| `local-relay/src/detached-vault.js` | `1b8bdb543eab` |
| `local-relay/src/stream-processor.js` | `0a5e0d000d42` |
| `local-relay/src/server.js` | `4b42a81d2a2d` |
| `local-relay/src/routes-hyperdrive.js` | `451c006e965f` |
| `local-relay/test/symbiote-zero-iq-loss-v20.test.js` | `572c0a7cffed` |
| `radar_dashboard/app/necromancer_verifier.py` | `2cbc3f0242d4` |
| `radar_dashboard/app/tests/test_midbrain_v19.py` | `9169d7c364d6` |

---

## 5. Honest Scope: Proven Live vs Proven in Chaos/Unit Tests

- **Proven Live on Running Daemons:**
  - HTTP 200 across all 6 endpoints on both Windows and `svhome`, matching `bootHash` (`abe5495b...`), `ship-check --window 1.5` returning `"ok": true` with `svhome` RAM reduced to `77.59 MB` (`ram_ok: true`) and `PHANTOM_5MS_DIRECT` at `5.59 ms`.
  - Real Codex traffic on Windows Tquota (`PID 15376`) exercising `DetachedVault` compression (`726,447 B` saved on `38` entries), `auditPrefixItems` (`45` audits, `35` real mid-prefix mutations detected), `TCP Scalpel` (`38/38` immediate autocuts, `0` `completed` leaks), and live Chimera Bone-Marrow LZ4 `512 KB` roundtrip (`17.7 ms`, `0.0042` ratio, bit-exact SHA-256).
  - Colab `Active assignments: 0` (`2350.14 CU`).
- **Proven in Chaos / Automated Tests (`S1–S6`, `test_07`, `test_v20`), Awaiting 12–24h Production Soak:**
  - `S2` end-to-end elimination of `503 local-tool-timeout-retry` on a `360s 499` retry (Windows uptime at measurement was `280s`, so no real `360s 499` event had occurred yet in production SQLite after restart).
  - Sustained 12–24h V8 steady-state `RSS` / `large_object_space` stability and real-traffic `detachedVault` hit rate accumulation require 12–24h of continuous Codex usage.
  - Untracked new helper capture (`pkg/_helper.py`) and syntax blocking before Colab enqueue are verified deterministically in Radar `test_07`; next live failed workspace Phoenix repair run will exercise it on real repositories.

---

## 6. v20.1 Post-Rollout Live Forensic Audit & Root-Cause Hotfix (`2026-11-27 00:00+07`)

### A. Honest Live Defects Discovered Immediately After Initial v20 Rollout

1. **`BUG #1` (CRITICAL — v20 regression): `Duplicate tool call_id: call_5926605c7aa94108aa22c78183158b01` bricked an active Codex session.**
   - `server.js` (`onHarvestSuccess`) uploaded **every** normal `200 OK` SSE response to Chimera `POST /api/symbiote/immortal/complete` (even when `detachCtx.active === false`) keyed solely by `toolRetryKey`, without `step_sig` or `detached_harvest: true`.
   - When Step N+1 hit `generation_in_flight` on the same `turnId`, local `detachedVault.getResultByTurnKey(toolRetryKey, immortalStepSig)` correctly returned `null`, then `server.js` fell through to `symbioteBridge.lookupImmortalRemote(toolRetryKey)` and replayed Step N's `custom_tool_call` twice more into `rollout-2026-11-26T18-46-29-01a217ad-b392-7ca1-9609-1a6bffb93a30.jsonl`, causing `validateToolHistory` (`responses-protocol.js`) to fail every subsequent turn with `400 duplicate_call_id`.
2. **`BUG #2` (CRITICAL — pre-existing V8 heap OOM root cause, verified via V8 heap snapshot retainer graph):**
   - Previous crashes (`PID 27968` at `1013.7 MB`, `PID 3564` at `1020.2 MB`) and rapid `PID 15376` growth (`heapUsed: 764 MB / 1216 MB`, `largeObjectSpaceUsed: 492 MB`, `arrayBuffers: 166 MB` at `uptime 851s`) came from `RequestDeadline` (`request-deadline.js`) using `AbortSignal.any([signal, this.controller.signal])` paired with an unremoved `requestDeadline.signal.addEventListener('abort', ...)` listener in `server.js`.
   - When requests completed normally (`res.writableFinished === true`), neither `workSignal` nor `controller.signal` ever aborted, pinning the composite `AbortSignal.any` and the entire `processResponsesRequest` V8 `Context` (`upstreamText`, `cachedPlainBodyText`, `body`, `req._Request.#state.body.source` `ArrayBuffer`) forever in Node.js's global `gcPersistentSignals` `Set`.
3. **`BUG #3` (MEDIUM): `prefixBreaksCaught: 66 / 91` (`74%`) false positives across concurrent subagents + `chimeraSyncErrors: 129`.**
   - `auditPrefixItems` was keyed only by parent `sessionId` rather than branch-scoped `prompt_cache_key || logicalTurnKey || sessionId:turnId`, and `postAsync` in `chimera-symbiote-bridge.js` used a `220ms` timeout without cancelling response bodies (`res.body.cancel()`).

### B. Surgical Fixes Deployed (`8/8` Files Synced Win ⇄ `svhome`)

- **`E:\DEV\Chung\.ch-relay\local-relay\src\request-deadline.js` + `E:\DEV\Chung\.ch-relay\local-relay\src\server.js`:** Removed `AbortSignal.any(...)` in favor of explicit single-listener parent forwarding with `unregister` in `dispose()`, plus explicit `removeEventListener('abort', onRequestDeadlineAbort)` + `requestDeadline.dispose()` inside `lease.addCleanup(...)`.
- **`E:\dev\chimera-tp\chimera_tp\symbiote_engine.py` + `E:\dev\chimera-tp\chimera_tp\dashboard.py` + `E:\DEV\Chung\.ch-relay\local-relay\src\chimera-symbiote-bridge.js` + `E:\DEV\Chung\.ch-relay\local-relay\src\server.js`:**
  - Enforced composite `(turn_key, step_sig)` isolation AND `detached_harvest=True` on both remote store and lookup (non-detached `200 OK` responses are rejected from remote Immortal storage; normal `200 OK` harvests no longer call `notifyImmortalComplete`).
  - Added hard client-history guard via `extractCallIdsFromSseBytes(sseBytes)`: both local and remote `immortalHit` candidates are rejected (`immortalDuplicateBlocked++`) if any replayed `call_id` already exists in `body.input`.
  - Scoped `auditPrefixItems` per branch (`prompt_cache_key || logicalTurnKey || sessionId:turnId`) and drained `res.body` in `postAsync` with `timeoutMs=600`.
- **`E:\DEV\Chung\.ch-relay\local-relay\src\responses-protocol.js`:** Added `healExactDuplicateToolCallReplays(input)` (executed in `server.js` prior to `prepareResponsesPayload` for `chatgpt` non-compatible `/v1/responses`), deterministically repairing exact identical replay duplicates (`__dup2`, `__dup3`) so already-poisoned Codex sessions auto-recover while preserving strict `validateToolHistory` rejection for divergent/malformed `duplicate_call_id` inputs.

### C. v20.1 BEFORE vs AFTER Verification Matrix

| Metric / Verification | v20 Initial (`23:39+07`) | v20.1 Hotfix (`00:00+07`) | Evidence |
|---|---|---|---|
| **V8 30×1 MB `/v1/responses` Heap Repro (`--expose-gc`)** | `los: 24.24 MB`, `ab: 19.15 MB`, `heap: 76.01 MB`, `7` leaked `343 KB` request strings & `ArrayBuffer`s in `gcPersistentSignals` | **`los: 4.93 MB`** (baseline `4.8 MB`), **`ab: 1.82 MB`**, `heap: 35.1 MB`, **`leakedStrings: 0`**, **`leakedBigAb: 0`** | Node `--expose-gc` heap snapshot audit |
| **Poisoned Live Codex Rollout (`rollout-...-01a217ad...jsonl`)** | `BEFORE_HEAL`: `400 duplicate_call_id` (`call_5926605c...` ×3) | **`AFTER_HEAL_VALIDATE: PASSED_OK (24 items)`** (`healedCount: 2`, `__dup2` / `__dup3` paired with outputs) | Live rollout JSONL dry-run + `S8` |
| **Chimera Unit Suites (Win & `svhome`)** | `21 / 21` (`test_v5/v18/v19/v20`) | **`22 / 22`** both Win (`16.87s`) & `svhome` (`19.47s`), incl. `test_06` `step_sig` + `detached_harvest` | `unittest` on both nodes |
| **Tquota Targeted Suites (Win & `svhome`)** | `77 / 77` | **`110 / 110`** (9 suites incl. `S1–S9`, `request-deadline`, `duplicate-tool-output`, `protocol`, `antigravity-input`, `anthropic-resilience`, `runtime-cleanup-tails`, `detached-vault`, `stream-autocut-v19`) both Win (`4.91s`) & `svhome` (`18.55s`) | `node --test` on both nodes |
| **Live Daemon `bootHash` Parity** | `abe5495b...` | **`8791ea02d39c6e439f7b0cd4009f2fd5523356ccfa6337d4f6ca6d02b5cbbccc`** (`Win pid 33856` == `svhome pid 3930007`, `inSync: true`) | `GET :12504/healthz` on both nodes |
| **Live Fresh Heap (`:12504/_debug/heap-breakdown`)** | Win `PID 15376`: `rss 1,044 MB`, `los 492 MB`, `ab 178 MB` (`uptime 982s`) | Win `PID 33856`: `rss 219.4–234.0 MB`, `heapUsed 42.7–44.6 MB`, `los 4.96 MB`, `ab 0.63–0.68 MB`; `svhome PID 3930007`: `rss 288.0 MB`, `los 6.36 MB`, `ab 0.78 MB` | Live `/_debug/heap-breakdown` |
| **Live Chimera `canary_ship_check(1.5)`** | `ok: true`, `loc 35.58 MB`, `peer 77.59 MB`, `5.59 ms` | **`ok: true`**, `loc_ram_mb: 26.22 MB`, **`peer_ram_mb: 69.14 MB` (`ram_ok: true`)**, **`PHANTOM_5MS_DIRECT 5.2 ms`**, `crdt_synced: true`, `dlp_clean: true` | `OvermindCortex.canary_ship_check(1.5)` |
| **Zero-IQ-Loss & Colab Safety** | `astraMin/Max=max`, `solMin=max`, `Active assignments: 0` | **`astraMin/Max=max`, `solMin=max`, `Active assignments: 0` (`2350.14 CU`, `0.00/hr`)** | `:12504/api/diagnostics` & Colab CLI (Win & `svhome`) |

### Synced Hotfix Files SHA-256 Parity (`8/8`, `MISMATCH=0`)

| File | SHA-256 Prefix (Win == `svhome`) |
|---|---|
| `chimera_tp/symbiote_engine.py` | `82cbffa4dac4` |
| `chimera_tp/dashboard.py` | `28ecd55c8dab` |
| `tests/test_v20_symbiote_zero_iq_loss.py` | `3180d89b6211` |
| `local-relay/src/request-deadline.js` | `31077ff41aba` |
| `local-relay/src/responses-protocol.js` | `0e6031c92a2d` |
| `local-relay/src/chimera-symbiote-bridge.js` | `547a10481b4d` |
| `local-relay/src/server.js` | `a43513756f02` |
| `local-relay/test/symbiote-zero-iq-loss-v20.test.js` | `8e5060379e11` |
