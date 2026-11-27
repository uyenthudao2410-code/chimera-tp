# Trinity v19 — CHIMERA MIDBRAIN (Full 3-Phase Implementation & Live Verification Report)

## 1. Architecture Summary

Inspired by Stanford's *Sparse Reward Subsystem in Large Language Models* (`<1%` sparse Value + Dopamine RPE neurons), **Trinity v19 (CHIMERA MIDBRAIN)** deploys a unified three-phase sparse neural critic and causal reward-prediction-error loop across Windows and `svhome`:

- **Phase 1 — Chimera Midbrain & Tquota Behavioral Dopamine Gate**
  - `E:\dev\chimera-tp\chimera_tp\midbrain_dopamine.py`: Shared `128`-bucket signed blake2b VSA projection (`vsa_bucket_projection`) + `16`-float structural feature vector (`extract_structural_features`), real-time `V_t` & `δ_t = V_t - V_{t-1}` scoring (`SPIKE` / `TROUGH` / `STEADY`), Pulse emission (`DOPAMINE_SPIKE` / `DOPAMINE_TROUGH`), hot-swappable `< 256 KB` probe (`install_probe`), and `extract_rpe_pivots` (`[+δ BREAKTHROUGH]` / `[-δ TRAP]`).
  - `E:\dev\chimera-tp\chimera_tp\vsa_memory_service.py`: Top-1% `immune_vault` pinning (`immune_pinned`), causal feedback EMA updates (`record_causal_feedback`), RPE pivot distillation (`distill_rpe_pivots`), and capsule usage provenance (`used_item_ids`).
  - `E:\dev\chimera-tp\chimera_tp\overmind_cortex.py` & `dashboard.py`: Exposed `GET /api/midbrain/status` and `POST /api/midbrain/{score,feedback,distill-pivots,probe}`.
  - `E:\DEV\Chung\.ch-relay\local-relay\src\dopamine-gate.js`, `responses-payload.js`, `routes-hyperdrive.js`, `server.js`: Added `BehavioralDopamineGate` (SSE progress lock on `SPIKE`, early rescue on `TROUGH`), `extractCriticalValueAnchors` / `repinDroppedValueAnchors` (`<tquota_value_anchors_1pct>` surviving compaction), and `GET /api/dopamine/status` + `dopamine` inside `GET /api/overmind/telemetry` (Codex-First strictly preserved).

- **Phase 2 — Radar Midbrain NeuroCritic, Dopamine Tree-of-Thoughts & Pre-Colab Value Gate**
  - `E:\DEV\Chat\radar_dashboard\app\midbrain_critic.py`: Bit-compatible `128 + 16` NeuroCritic (`MidbrainNeuroCritic`), 3-branch hypothesis ranking (`score_hypotheses`), zero-waste `pre_colab_value_gate`, corpus collector (`collect_probe_training_corpus`), and atomic probe installation (`save_probe_from_colab_result`).
  - `E:\DEV\Chat\radar_dashboard\app\necromancer_verifier.py` & `server.py`: Upgraded `phoenix_repair_failed_workspaces` with optional 3-hypothesis Dopamine Tree-of-Thoughts scout, Pre-Colab Value Gate, causal `/api/midbrain/feedback` loop, and `/api/godmode/midbrain/{status,score,calibrate}` endpoints.

- **Phase 3 — Colab White-Box 1% Probe Calibrator & Student Distillation**
  - `E:\DEV\Chat\radar_dashboard\app\colab_bridge.py` & `colab_cli_orchestrator.py`: Registered `midbrain_probe_calibrator` (`T4`, fallback `["T4", "CPU_HIGH_MEM", "CPU"]`), added full hidden-layer scan, L2 ridge linear probing, Top-1% Value neuron extraction (`k = max(8, round(0.01 * d_model))`), Sparse-1% probing, validation representation knockout + PyTorch forward-hook knockout ablation, paired Dopamine RPE verification, and `144`-dim linear student distillation (`< 256 KB`).

---

## 2. Synchronized File Inventory (16 Files — `MISMATCH_16=0`)

All 16 Trinity v19 files matched byte-for-byte (SHA-256) between Windows and `svhome`:

| Stack | Relative File Path | SHA-256 (`Win == svhome`) |
| :--- | :--- | :--- |
| Chimera | `chimera_tp/midbrain_dopamine.py` | `c6151f77c21cdf5b2b34c37bfff50ea9848a9df1bd16c664914846f37d19f625` |
| Chimera | `chimera_tp/vsa_memory_service.py` | `7ccc207d65491177f5724bad18c50a99bd03ae784bce3ca5303e35877cdc1c29` |
| Chimera | `chimera_tp/overmind_cortex.py` | `7423b85806a2b7d704f72e65e1a85ba78992430dd377d12a7807345d27c857f2` |
| Chimera | `chimera_tp/dashboard.py` | `a14de88607d048f369299d7c3bb27b1b8461acb89cc7549b082b9d040e68c36e` |
| Chimera | `tests/test_v19_midbrain_dopamine.py` | `25e061440e8f546154ae741c1b73f7ca3955f0f2685a59de2efdb289478a8b44` |
| Tquota | `src/dopamine-gate.js` | `b26eeeb34dfc9a4203b59f4e483655cd7157baaff5f0bb0e52c60b5ff47ac785` |
| Tquota | `src/responses-payload.js` | `0e5344a99d57158f7847291c5199f2f8205eb2f4e7a41d3265d42a52fad6def9` |
| Tquota | `src/routes-hyperdrive.js` | `8b96a11cfc309b008b8bd0598dd2625376749e7692cf89f23cd498824d195a5a` |
| Tquota | `src/server.js` | `d2f1d4095582719224ba8b8a679d62c8886f7c6d41cdc36141fccd353c6ecb92` |
| Tquota | `test/midbrain-dopamine-v19.test.js` | `8ef3cad7007a23330954ae91f04932fe4202b38d67b09535cdcc702f7b9ae8fd` |
| Radar | `app/midbrain_critic.py` | `4f68d6091a34164eae97978d32b0dfe0967c5811f058b76e87588f91eef6b635` |
| Radar | `app/colab_bridge.py` | `ced56b6a6a8e6608e094d852e89a367c7a3e6c1cd8c68103f4bd3e31d63b667d` |
| Radar | `app/colab_cli_orchestrator.py` | `fafee80a57878589b410a4adf6b1ce98ac183df8fc6f5ee2bb6e4b5d3d2cbaff` |
| Radar | `app/necromancer_verifier.py` | `99b34e34798ebbdd6313d6c91eac19a41a666189705334c9e0933505cd2ebb16` |
| Radar | `app/server.py` | `c9f7453ee2a75448ead8dfb300e536181e1fdf21d5399746ba5c26750779ceaa` |
| Radar | `app/tests/test_midbrain_v19.py` | `06f56911da92eb24cec279a6c479f7a0a6f051d7871a603611` |

Calibrated Student Probe (`midbrain_value_probe.json`, `2.92 KB` on disk / `2.17 KB` in-memory serialized):
- `svhome` Radar (`data/midbrain_value_probe.json`), `svhome` Chimera (`.chimera_ops/midbrain_value_probe.json`), and Windows Radar (`data/midbrain_value_probe.json`) SHA-256: `31201491c5a1e9adafc851a341b0e8f9dd46d7130238e84ac230d25fdceef645`.
- Windows Chimera installed via `POST /api/midbrain/probe` (`probe_mode: "whitebox_distilled_1pct"`, `probe_installed: true`).

---

## 3. Unit Test Verification (Both Nodes — 0 Failures)

- **Chimera-TP** (`tests.test_v5_phantom`, `tests.test_v18_overmind_cortex`, `tests.test_v19_midbrain_dopamine`):
  - Windows: **16 tests OK** (`19.345s`)
  - `svhome`: **16 tests OK** (`16.604s`)
- **Tquota Codex-First** (`breakthrough-hedge-vault-20261125`, `hyperdrive-7pillars-20261125`, `midbrain-dopamine-v19`, `pareto-quota-efficiency-20261126`, `model-alias-sol-effort-20261126`, `trinity-time-crystal-20261126`):
  - Windows: **27/27 PASS** + **12/12 PASS** (**39/39 PASS**)
  - `svhome` (`--test-concurrency=1`): **39/39 PASS** (note: `P2`/`P7` in `pareto-quota-efficiency` raced on a `50ms`/`80ms` timer under 6-file parallel load before passing sequentially `39/39`)
- **Radar Dashboard** (`test_godmode_v15`, `test_autonomy_unblock_suite`, `test_tquota_hyperdrive`, `test_tquota_breakthrough_resilience`, `test_bounty_assassin_and_trojan_pr`, `test_halo_bridge`, `test_midbrain_v19`):
  - Windows (7-suite full run prior to final 1-line `colab_bridge.py` update): **38 passed** (`21.47s`), then post-edit re-run (`test_godmode_v15` + `test_midbrain_v19`): **13 passed** (`4.80s`)
  - `svhome`: **38 passed** (`55.19s`), then post-edit re-run (`test_godmode_v15` + `test_midbrain_v19`): **13 passed** (`2.91s`)

---

## 4. Pha 3 Colab White-Box 1% Probe Calibration (`Tesla T4`, Live Proof #1)

Executed live via `POST http://127.0.0.1:8787/api/godmode/midbrain/calibrate` (`dry_run: false, drain_now: true, max_samples: 64`, Job ID `colab_20261126T105419_a0364e9e`):

| Metric | Observed Value |
| :--- | :--- |
| Hardware / Runtime | **Tesla T4** (`14.56 GB VRAM`), `fallback: ["T4", "CPU_HIGH_MEM", "CPU"]` |
| Open-Weight Teacher | `Qwen/Qwen2.5-Coder-0.5B-Instruct` (`n_layers = 24`, `d_model = 896`) |
| Best Probing Layer / Corpus | Layer **24** / `46` samples (`8` real workspace proofs + `38` balanced domain traces; `val_size = 10`) |
| Top-1% Value Neurons Selected | **9 neurons** (`1.00%` of `896`: indices `[364, 39, 748, 566, 378, 20, 859, 646, 759]`) |
| `full_layer_acc` | `1.0` (`100%`) |
| `sparse_1pct_acc` (only 9 neurons) | `0.9` (`90%`) |
| `value_1pct_knockout_acc` / `random_1pct_knockout_acc` | `1.0` / `1.0` (`knockout_drop_pct = 0.0%`, `random_knockout_drop_pct = 0.0%`) |
| Forward-Hook Knockout (`hook_full_acc` / `hook_value_knockout_acc` / `hook_random_knockout_acc`) | `1.0` / `1.0` / `1.0` (`hook_drop_pct = 0.0%`) |
| Dopamine RPE Paired Transitions | `mean_rpe_breakthrough = +0.1645` vs `mean_rpe_flaw = -0.2827` |
| Student Distillation (`144`-dim VSA+Struct) | `student_r2 = 0.6048`, `student_val_acc = 1.0`, `size_kb = 2.92 KB` (`< 256 KB`) |
| Colab Usage After Calibration | `balance_cu = 2350.14`, `usage_rate_hr = 0.0`, **`active_assignments = 0`** |

*Scientific Observation:* Just **9 neurons (`1%` of `d_model=896`)** preserved `90%` validation classification accuracy and separated paired breakthrough vs flaw prompts cleanly (`+0.1645` vs `-0.2827` RPE). On the full `896`-dim Layer-24 hidden state, linear separability remained distributed redundantly across the remaining `887` neurons on the 10-sample validation split (`knockout_drop_pct = 0.0%`).

---

## 5. Live Proofs #2–#4 Summary

- **Live Proof #2 (Chimera Distill, Peer Sync, Sub-2ms Score & Immune Vault):**
  - `POST /api/midbrain/distill-pivots` on `svhome`: `scanned_items: 200`, `pivots_stored: 200`, `total_items: 689`.
  - `POST /api/vsa/sync-peer` on `svhome`: `pulled: 12`, `pushed: 12`, `local_total: 689`, `peer_total: 489`, `elapsed_ms: 43.47`.
  - Live `POST /api/midbrain/score` (`whitebox_distilled_1pct`):
    - `svhome`: `+δ` breakthrough `value_v = 0.7984` (`rpe_delta = +0.6743`, `SPIKE`, `1.193 ms`); `[-δ]` trap `value_v = 0.0720` (`rpe_delta = -0.7264`, `TROUGH`, `0.270 ms`).
    - Windows: `+δ` breakthrough `value_v = 0.7449` (`rpe_delta = +0.6208`, `SPIKE`, `0.944 ms`); `[-δ]` trap `value_v = 0.1412` (`rpe_delta = -0.6037`, `TROUGH`, `0.221 ms`).
  - `immune_vault`: `pinned_count: 5` -> `7` (after causal feedback), protected against low-value pruning.

- **Live Proof #3 (Tquota Telemetry & Chimera Ship-Check):**
  - Windows `GET /api/dopamine/status` + `GET /api/overmind/telemetry`: HTTP `200`, `codexFirst: true`, `healthyAccountsTotal: 7`, `watchdogOk: true`.
  - `svhome` `GET /api/dopamine/status` + `GET /api/overmind/telemetry`: HTTP `200`, `codexFirst: true`, `healthyChatgptAccounts: 4`, `quarantinedChatgptAccounts: 1`, `watchdogOk: true`.
  - Windows `python -m chimera_tp ship-check --window 1.5`: **`ok: true`**, `phantom_mode: "PHANTOM_5MS_DIRECT"`, `phantom_rtt_ms: 4.96`, `crdt_synced: true`, `dlp_clean: true`, `loc_hlc_ts_ms == peer_hlc_ts_ms == 1795683437821`. (`svhome` runs in `SERVER_ONLY` passive tunnel mode.)

- **Live Proof #4 (Live Phoenix Dopamine Tree-of-Thoughts Attempt 2/2 — `bad-antics__lateralus-lang__issue_998`):**
  - Dopamine ToT evaluated `3` hypotheses and selected `H1_minimal` (`value_v = 0.8255`, `rpe_delta = +0.6858`, `signal = "SPIKE"`, `composite_score = 1.0655`).
  - Surgical Codex produced a `2,474`-byte diff across `lateralus_lang/codegen/python.py`, `math_engine.py`, `optimizer.py`, `stdlib/math.ltl` before hitting `codex_rc = 124`; Pre-Colab Value Gate evaluated `value_v = 0.5994` (`allow_colab: true`, `whitebox_distilled_1pct`) and queued `colab_20261126T110203_a79ac5df`.
  - Live Colab drain (`CPU_HIGH_MEM`, `50.99 GB RAM`, `8 vCPU`, `3721.3 ms`) applied the diff cleanly (`git_apply_ok: true`, `clean_apply`), then failed pytest collection (`test_rc = 2`, `verified_for_pr: false`) with `ModuleNotFoundError: No module named 'lateralus_lang._rounding'` because Codex created an untracked helper module not captured by `git diff HEAD`.
  - **Final Colab Cleanup:** `/home/svhome/DEV/radar_dashboard/.venv/bin/colab usage </dev/null` confirmed **`Current balance: 2350.14 compute units`**, `Usage rate: 0.00/hr`, **`Active assignments: 0`**.
