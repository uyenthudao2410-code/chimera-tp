# TRINITY v21 — APEX MUTATION: IMPLEMENTATION & VERIFICATION REPORT

- **Timestamp:** `2026-11-27 00:40+07`
- **Nodes Synchronized:** `win-desktop` (`E:\dev\chimera-tp`, `E:\DEV\Chung\.ch-relay\local-relay`) ⇄ `svhome` (`/home/svhome/DEV/chimera-tp`, `/home/svhome/DEV/Tqouta/local-relay`)
- **Live Boot Parity (`runtimeSourceSync.bootHash`):** `cfd8bfc568fd070134d86faf2b1f80dd038158fa7a0dda588488adf9937091e2` (`inSync: true` on both nodes)
- **Upstream Preservation Reference:** `[Tquota Quota Drain Root Cause](t3-thread://v2/69366787-87c6-498a-a02a-c69508ade1d6/86801a41-7f90-445b-b2b9-213d71c7417f)` (`run 58/59/60` preserved 100%)

---

## 1. Zero-IQ-Loss Axiom Compliance (Verified Live)

| Invariant / Setting | BEFORE (v20.1 `00:04+07`) | AFTER (v21 `00:40+07`) | Verification Source |
|---|---|---|---|
| `limits.astraMinEffort` | `"max"` | `"max"` | `GET 127.0.0.1:12504/api/diagnostics` |
| `limits.astraMaxEffort` | `"max"` | `"max"` | `GET 127.0.0.1:12504/api/diagnostics` |
| `limits.solMinEffort` | `"max"` | `"max"` | `GET 127.0.0.1:12504/api/diagnostics` |
| OpenAI `collaboration.*` schemas | Protected (`run 60`) | Protected (`0` schema mutations) | `zero-leak-v2-20261126.test.js` (`Z3`) |
| Tool history strictness (`validateToolHistory`) | Enforced | Enforced (divergent duplicates rejected) | `duplicate-tool-output-20261113.test.js`, `symbiote-zero-iq-loss-v20.test.js` (`S8`) |
| Google Colab assignments | `0` (`2350.14 CU`) | `0` (`2350.14 CU`, `0.00/hr`) | `colab usage` (Win + `svhome`) |

---

## 2. Six Apex Mutations Implemented

1. **Mutation 1 — `CODEX-SURGEON` (Out-of-Band Atomic JSONL Surgery & Time-Travel Clean Fork):**
   - [`symbiote_engine.py`](file:///E:/dev/chimera-tp/chimera_tp/symbiote_engine.py): Added `heal_codex_rollout_jsonl` (strict `_SESSION_ID_RE` validation, idle-mtime safety guard, immutable `.bak.<ts>` backup, atomic `fsync` + `os.replace`, bounded <= 64-char unique ID remapping across `response_item` and `compacted.replacement_history`, SHA-256 post-write verification, Pulse `SYMBIOTE_ROLLOUT_SURGERY`) and `fork_rollout_to_last_clean_checkpoint` (non-destructive sibling clean fork with `SYMBIOTE_ROLLOUT_FORK`).
   - [`dashboard.py`](file:///E:/dev/chimera-tp/chimera_tp/dashboard.py): Wired `POST /api/symbiote/surgeon/heal` and `POST /api/symbiote/surgeon/fork`.
   - [`chimera-symbiote-bridge.js`](file:///E:/DEV/Chung/.ch-relay/local-relay/src/chimera-symbiote-bridge.js) & [`server.js`](file:///E:/DEV/Chung/.ch-relay/local-relay/src/server.js): Automatically requests out-of-band surgery (`60s` per-session debounce) whenever `healExactDuplicateToolCallReplays` heals duplicates live.

2. **Mutation 2 — `CROSS-NODE THERMAL HEDGE` + `LOSER SCALPEL`:**
   - [`hedge-response.js`](file:///E:/DEV/Chung/.ch-relay/local-relay/src/hedge-response.js): Separates bare SSE connection frames (`response.created`) from genuine model activity (`meaningfulProgress` / `realReasoningBytes`).
   - [`hive-mind.js`](file:///E:/DEV/Chung/.ch-relay/local-relay/src/hive-mind.js): Added `findThermalHedgePeer` prioritizing healthy `PHANTOM_5MS` `fastOrigin` peers.
   - [`server.js`](file:///E:/DEV/Chung/.ch-relay/local-relay/src/server.js): Replaced the blanket `>= 65 KB` hedge ban with Stall-Only Thermal Hedge (`largeContextStallHedgeMs = 90_000` default / `x-tquota-large-stall-hedge-ms`), gated strictly by `!primaryRealProgress && realReasoningBytes === 0`, with cross-node PHANTOM peer fallback (`startPeerThermalLane` -> `peerHedgeWinResponse`) and immediate `cancelLoser` abort before `response.completed`.

3. **Mutation 3 — `409 Uncertain-Dispatch Auto-Resolver` + `EdgeHotSwapProxy` PHANTOM Priority:**
   - [`codex-generation-ledger.js`](file:///E:/DEV/Chung/.ch-relay/local-relay/src/codex-generation-ledger.js), [`tool-generation-guard.js`](file:///E:/DEV/Chung/.ch-relay/local-relay/src/tool-generation-guard.js), [`server.js`](file:///E:/DEV/Chung/.ch-relay/local-relay/src/server.js): Clears uncertain dispatch locks (`clearUncertainDispatchByKey` + `clearUncertainQuotaDispatch`) on `onHarvestSuccess`, `200 OK` finish, and cached vault hits; prevents blocked retries from overwriting active `turnAliases` (`if (detachCtx && !acquireError)`); resolves `409 codex_uncertain_dispatch_blocked` from `detachedVault` (`detachedHarvest: true` + `extractCallIdsFromSseBytes` non-duplicate guard) returning `200 OK` (`x-tquota-vault: uncertain-resolved`).
   - [`server.js`](file:///E:/DEV/Chung/.ch-relay/local-relay/src/server.js): `cmd === "edge"` prepends `TQUOTA_PHANTOM_PEER_ORIGIN` ahead of configured Tailscale peers in `EdgeHotSwapProxy` `fallbackPeers`.

4. **Mutation 4 — `SINGLE-PASS ZERO-COPY DIGEST` + Opt-In Wire Gzip:**
   - [`detached-vault.js`](file:///E:/DEV/Chung/.ch-relay/local-relay/src/detached-vault.js), [`chimera-symbiote-bridge.js`](file:///E:/DEV/Chung/.ch-relay/local-relay/src/chimera-symbiote-bridge.js), [`server.js`](file:///E:/DEV/Chung/.ch-relay/local-relay/src/server.js): Reuses `inboundHistory.hashes` from `requestFootprints.snapshot` across `auditPrefixItems(..., { precomputedDigests })`, `canonicalVaultKeyFromDigests` (`>= 65 KB` untouched inputs), and zero-copy synchronous `shadowTomography` (eliminating duplicate 2+ MB JSON walks and `ingressWorkerPool` ArrayBuffer copies unless `shadowTomographyWorker === true`). Added opt-in `upstreamRequestGzip` (disabled by default) with automatic 415/400 uncompressed fallback + 600s circuit break.

5. **Mutation 5 — `KV-TELEPATHY` (Soft Quota Reservation + Cross-Node CRDT Affinity):**
   - [`pool-manager.js`](file:///E:/DEV/Chung/.ch-relay/local-relay/src/pool-manager.js): Soft Quota Reservation (`softQuotaReservePct = 85`) shields accounts holding warm active sticky sessions (`COLD_CACHE_AFFINITY_HORIZON_MS`, using `updatedAt ?? at`) from new sessions whenever another healthy candidate `< 95` with headroom exists, while existing sticky sessions keep full `85–99%` access.
   - [`hive-mind.js`](file:///E:/DEV/Chung/.ch-relay/local-relay/src/hive-mind.js) & [`server.js`](file:///E:/DEV/Chung/.ch-relay/local-relay/src/server.js): `bindSessionAccount` + `prefixRoot` propagation into `warmSessions` gossip.

6. **Mutation 6 — `CLOSED-LOOP SCALPEL VACCINE`:**
   - [`optimizer.js`](file:///E:/DEV/Chung/.ch-relay/local-relay/src/optimizer.js), [`optimized-output.js`](file:///E:/DEV/Chung/.ch-relay/local-relay/src/optimized-output.js), [`server.js`](file:///E:/DEV/Chung/.ch-relay/local-relay/src/server.js): Under `quota-saver` (`forceSerialForSaver`), `schema_ineligible` single-call function tools (`canInjectFunctionArgPad === false`, non-collab) are tracked in `cutPlan.unpaddedSerialTools`, force `parallel_tool_calls = false`, and seal at `response.output_item.done` via `autocut-unpadded-done` (keeping OpenAI `collaboration.*` untouched on `autocut-collab-done`).

---

## 3. BEFORE vs AFTER Results

### A. Live Cross-Node Health, Memory & Live Rollout Surgery

| Check / Metric | BEFORE | AFTER (v21 Live) |
|---|---|---|
| Poisoned Rollout `01a217ad-b392-7ca1-9609-1a6bffb93a30` (`3,802` lines, `13.88 MB`) | `2` duplicate `custom_tool_call` + `2` duplicate `custom_tool_call_output` (`call_5926605c7aa94108aa22c78183158b01`) on disk | **Cured live via `POST /api/symbiote/surgeon/heal`**: `healed_calls: 2`, `healed_outputs: 2`, **`duplicates_remaining: 0`**, `bad_json: 0`, backup `.bak.1795714808` (`13,875,510 B`) verified on disk |
| Win Tquota (`PID 37512`) Memory (`/_debug/heap-breakdown`, `59s`) | `heapUsed: 88.61 MB`, `largeObjectSpaceUsed: 26.65 MB` | `rss: 294.81 MB`, `heapUsed: 58.56 MB`, **`largeObjectSpaceUsed: 10.92 MB`**, `arrayBuffers: 5.42 MB` |
| Win ⇄ `svhome` `bootHash` Parity | `8791ea02d39c...` (v20.1) | **`cfd8bfc568fd070134d86faf2b1f80dd038158fa7a0dda588488adf9937091e2`** (`inSync: true` on Win `PID 37512` & `svhome` `PID 3937589`) |
| `OvermindCortex.canary_ship_check(delta_window_s=1.5)` | `ok: true` (`5.2 ms`) | **`ok: true`**, `PHANTOM_5MS_DIRECT` (**`4.82 ms` RTT**), `no_storm: true` (`tx_delta_bytes: 0`), `ram_ok: true` (`23.52 MB` Win / `66.52 MB` `svhome`), `crdt_synced: true`, `dlp_clean: true` |

### B. Automated Test Matrix (Windows + `svhome`)

| Suite Scope | Windows Result | `svhome` Result |
|---|---|---|
| Chimera 4 suites (`test_v5_phantom`, `test_v18_overmind_cortex`, `test_v19_midbrain_dopamine`, `test_v20_symbiote_zero_iq_loss` incl. `test_07` & `test_08`) | **24 / 24 passed** (`20.09s`) | **24 / 24 passed** (`22.37s`) |
| Tquota 15 suites (`trinity-v21-apex-mutation` `M1–M6`, `symbiote-zero-iq-loss-v20` `S1–S9`, `zero-leak-v2` `Z1–Z4`, `pareto-quota-efficiency`, `breakthrough-hedge-vault`, `elastic-cold-affinity`, `request-deadline`, `duplicate-tool-output`, `protocol`, `antigravity-input`, `anthropic-resilience`, `chrelay1213-runtime-cleanup-tails`, `detached-vault`, `stream-autocut-v19`, `codex-generation-ledger`) | **161 / 161 passed** (`14.26s`, `0` fail) | **140 / 140** in 15-suite run (`31.00s`, `0` fail) + **21 / 21** `codex-generation-ledger` (`0.13s`, `0` fail) |
| Node `--expose-gc` 30×1 MB `RequestDeadline` Leak Check | **`{heapMb: 4.71, extMb: 1.96}`** (`0` leak) | N/A (code SHA-256 identical) |
| Cross-Node File Sync Verification (all 14 modified code/test files) | `MISMATCH=0` | `MISMATCH=0` |

---

## 4. Trinity v21.1 Post-Deploy Live Audit & Comprehensive Hotfix (`2026-11-27 01:13+07`)

Post-deploy SQLite + live telemetry inspection across both nodes surfaced **4 production defects** in v21.0 traffic (`SV_5484` `15 ms` `503 generation_in_flight`, `WIN_70547` `359.4s` `499` + `SV_5498` `236.4s` spillover double-dispatch, `peerMesh.errors = 21/65`, and false-positive `prefixBreaksCaught: 6` on `svhome` / `1` on `win-desktop` at `breakIndex: 0`). All 4 were root-caused, patched, covered by regression tests (`M7–M9`), synced bit-for-bit (`MISMATCH=0`), and deployed live (`bootHash: 274a821a6084299a0d4fa1e624bec24ae82e0ec2cb284fd610417f0e2064f2ef` on both nodes).

### A. Root Causes & Surgical Fixes

1. **`rawStepSig` Mutation-Drift Coalescing + Multi-Step `turnAliases` (Fixes `SV_5484` `503 generation_in_flight` & `peerMesh` `503` storms):**
   - **Cause:** `server.js` computed `immortalStepSig` before `body` mutations (`prepareResponsesPayload` tool schema padding `+4.6 KB`, `hoistInstructionsForGpt62`, `thoughtBriefStore`, `dupHeal`), while `registerTurnAlias`, `409` uncertain auto-resolver, and `onHarvestSuccess` computed `digestTurnStepSignature(body)` *after* mutation. Furthermore, `detached-vault.js` stored only one `turnAliases` slot per `turnKey`.
   - **Fix:** [`server.js`](file:///E:/DEV/Chung/.ch-relay/local-relay/src/server.js) computes `rawStepSig` once before any mutation and reuses it across all 4 sites; [`detached-vault.js`](file:///E:/DEV/Chung/.ch-relay/local-relay/src/detached-vault.js) keys `turnAliases` by `${turnKey}::${stepSig}` with safe empty-`stepSig` fallback.
2. **Prefix Auditor Hash Parity & Coordinate Alignment (Fixes false `prefixBreaksCaught` at `breakIndex: 0`):**
   - **Cause:** `auditPrefixItems` mixed `requestFootprints.snapshot` hashes (`sha256(JSON.stringify(item))`, insertion key order) with `digestCanonicalStreaming` (sorted keys) whenever `canReuseInboundHashes` flipped, AND audited after `prepareResponsesPayload` mutated `tool_search_output` inside `body.input`.
   - **Fix:** [`chimera-symbiote-bridge.js`](file:///E:/DEV/Chung/.ch-relay/local-relay/src/chimera-symbiote-bridge.js) aligns fallback hashing (`hashPrefixItemHex`) bit-for-bit with `requestFootprints.snapshot`; [`server.js`](file:///E:/DEV/Chung/.ch-relay/local-relay/src/server.js) runs `auditPrefixItems` immediately before `prepareResponsesPayload` (raising live Zero-Copy reuse to **100%**).
3. **Thermal Stall Hedge Empty-Shell & Mid-Stream Freeze Watchdog (Fixes `WIN_70547` / `SV_5498` missed hedge):**
   - **Cause:** `hedge-response.js` marked empty `response.reasoning_summary_part.added` (`0` real bytes) as `meaningfulProgress`, permanently exiting `stallOnlyLargeHedge` at `90s` (`primary_active`) even when the stream then froze silently for `238s+`; additionally default `largeContextStallHedgeMs = 90_000` raced `streamTimeouts.firstByteMs = 90_000`.
   - **Fix:** [`hedge-response.js`](file:///E:/DEV/Chung/.ch-relay/local-relay/src/hedge-response.js) requires non-empty reasoning payload bytes (`delta`, `text`, or `encrypted_content`) for `meaningfulProgress`; [`server.js`](file:///E:/DEV/Chung/.ch-relay/local-relay/src/server.js) lowers default `largeContextStallHedgeMs` to `75_000 ms` (`< 90_000 ms` `firstByteMs`) and replaces the one-shot `primary_active` exit with a sustained mid-stream zombie silence watchdog (`2× stallDelay`, capped at `150s`), keeping active reasoning zero-waste (`M2c` stays `1` call).
4. **Peer Mesh `max`-Effort Runway & Un-Mutated Forward Body (Fixes `WIN_70547` `120s` spillover timeout + duplicate local dispatch):**
   - **Cause:** `peerMesh.trySpillover` enforced `120s` header timeout while `svhome` held headers inside `inspectHedgeResponse` during a `235s` `max`-effort reasoning turn, aborting `svhome` into detached harvest and silently dispatching a duplicate local call (`359.4s 499`, 2× quota).
   - **Fix:** [`server.js`](file:///E:/DEV/Chung/.ch-relay/local-relay/src/server.js) elevates production spillover timeout (`base >= 30s`) to `420s` for `max`-effort (`240s` otherwise, bound by `req.signal`) and forwards `preparedPayload?.plainBodyText || rawText || JSON.stringify(body)` without double mutation.

### B. v21.1 Verification Matrix (Windows ⇄ `svhome`)

| Verification Check | Windows (`win-desktop`) | `svhome` |
|---|---|---|
| Live Daemon `bootHash` (`inSync`) | `274a821a6084299a0d4fa1e624bec24ae82e0ec2cb284fd610417f0e2064f2ef` (`inSync: true`, `PID 35720`) | `274a821a6084299a0d4fa1e624bec24ae82e0ec2cb284fd610417f0e2064f2ef` (`inSync: true`, `PID 3943406`) |
| SHA-256 Parity (13 core/test files) | `13 / 13`, `MISMATCH=0` | `13 / 13`, `MISMATCH=0` |
| Tquota 16 Test Suites (incl. `M7`, `M8`, `M9`) | **135 / 135 passed** (`0` fail) | **135 / 135 passed** (`33.66s`, `0` fail) |
| `--expose-gc` 30×1 MB Alternating Prefix Audit | `gcDeltaMB: +1.06 MB`, `item0FalseBreaks: 0` | Identical code (`MISMATCH=0`) |
| Live Memory (`/_debug/heap-breakdown`) | `RSS: 288.88 MB`, `heapUsed: 68.78 MB`, `largeObjectSpaceUsed: 8.11 MB`, `arrayBuffers: 13.17 MB` | `RSS: 267.12 MB`, `heapUsed: 52.87 MB`, `largeObjectSpaceUsed: 6.49 MB`, `arrayBuffers: 1.57 MB` |
| Live Post-v21.1 Symbiote Counters | `prefixAudits: 6`, `prefixClean: 6`, `prefixBreaksCaught: 0`, `singlePassReuses: 6/6 (100%)`, `completedLeaks: 0`, `aborted499: 0` | `prefixAudits: 7`, `prefixClean: 7`, `prefixBreaksCaught: 0`, `singlePassReuses: 7/7 (100%)`, `completedLeaks: 0`, `aborted499: 0`, `SQLite 6/6 = 100% 200 OK (p50 17.85s, p95 24.74s)` |
| Zero-IQ-Loss Effort Lock | `astraMinEffort: max`, `astraMaxEffort: max`, `solMinEffort: max` | `astraMinEffort: max`, `astraMaxEffort: max`, `solMinEffort: max` |
| `OvermindCortex.canary_ship_check(1.5s)` | `ok: true`, `PHANTOM_5MS_DIRECT` (`6.46 ms`), `no_storm: true`, `ram_ok: true` (`77.64 MB` / `77.67 MB`), `crdt_synced: true`, `dlp_clean: true` | Verified via peer link |
| Google Colab Guardrail | `2350.14 CU`, `Usage rate: 0.00/hr`, `Active assignments: 0` | `0` assignments |

