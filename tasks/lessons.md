# CHIMERA-HYPER — Engineering Lessons

## Lesson 1 — Strict Layer Separation Between Transport Infrastructure and Downstream Apps (2026-11-25)
- **Correction:** Keep application-specific workflows (e.g., bounty patch memory, LLM prompt-cache stack batching, per-bounty USD ROI accounting) inside their own repositories (`radar_dashboard`, `Tqouta`) rather than crowding `chimera-tp`.
- **Rule for `chimera-tp`:** Proposals and core implementations in `chimera-tp` must operate at the **transport, cryptography, OS virtualization, compression, or distributed computation primitive layer** — elevating every system above it without domain-specific coupling.

## Lesson 2 — WebGL Shader Precision Parity & Real Browser Verification Before Delivery (2026-11-25)
- **Correction:** Mixing default `highp float` in a WebGL vertex shader with `precision mediump float;` in a fragment shader for shared uniforms (`uCenter`, `uRadius`) causes ANGLE/Chrome shader linking to fail silently if swallowed by a fallback catch block, producing a black canvas.
- **Rule:** Always declare `precision highp float;` consistently in BOTH vertex and fragment shaders, never silently swallow WebGL compile/link failures without visible fallback/logging, and always verify the live rendered page via headless Playwright (console errors, `gl.getError() === 0`, and visual screenshot inspection) before reporting done.

## Lesson 3 — Unified Real-Time Causal Visualization (No Disconnected Screensavers) (2026-11-26)
- **Correction:** Splitting 3D subsystems into isolated visual modes (`Ferrofluid`, `VSA`, `Tarpit`) hides how `WIN-DESKTOP`, `PHANTOM-5MS`, `WASM Teleport`, `FROST 2-of-3`, `VSA 10K`, and `SVHOME` actually connect and transfer data across the cluster.
- **Rule:** Render ALL subsystems together in one unified 3D spatial topology where live daemon metrics, active port tunnels, and real cross-host RPC flow events drive the visual conduits, metaballs, shield flares, and live trace feed simultaneously.

## 2026-11-26 — Zero-Console-Popup Invariant for Windows `pythonw.exe` Daemons
- **Root Cause:** Running `subprocess.run/check_output/Popen` (especially `powershell.exe`, `cmd.exe`, `robocopy`, `netstat`, `nvidia-smi`, `ssh`) from a GUI-less `pythonw.exe` daemon without `creationflags=subprocess.CREATE_NO_WINDOW` forces Windows to allocate and flash a visible console window on screen every cycle (e.g. every 30s from `StasisPodManager` -> `_win_get_cmdlines_for_pids`).
- **Permanent Rule:**
  1. NEVER spawn `powershell.exe` for process metadata/cmdline/path queries inside daemon loops — use native Win32 kernel APIs (`ntdll!NtQueryInformationProcess(ProcessCommandLineInformation = 60)` and `kernel32!QueryFullProcessImageNameW`): 350x faster (`~0.05 ms/PID`), 0 child processes, 0 window flashes.
  2. ALWAYS pass `creationflags=(getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0)` on EVERY non-interactive `subprocess.*` call across the entire daemon/platform codebase.
  3. Keep unit test `test_05_zero_powershell_native_cmdline_and_gpu_discovery` asserting `subprocess.check_output` is never called for cmdline or exe-path inspection.

## 2026-11-26 — Zero-WebGL 2D Telemetry & Architecture Priority Over Heavy 3D Shaders
- **Correction:** WebGL raymarching / 3D particle shaders cause workstation iGPU lag and visually distract from operational clarity; the user explicitly requested dropping WebGL in favor of clean, professional 2D charts and a live architecture diagram showing all features and their real-time data synchronization.
- **Permanent Rule:** Keep the Chimera dashboard strictly **Zero-WebGL** (pure event-driven 2D SVG topology + Canvas 2D telemetry charts updated on the `/api/pulse` tick, zero continuous `requestAnimationFrame` GPU loops), prioritizing information clarity, real-time cross-feature data transfer visibility, and near-zero host CPU/GPU footprint.

## 2026-11-26 — Never Trust WMI `Win32_VideoController` for Monitor Wiring & Never Choke CPU/iGPU Cross-Blit
- **Root Cause:**
  1. WMI `Win32_VideoController` falsely mirrors secondary monitor resolution/refresh rate onto unattached iGPUs (`Intel UHD 730`), whereas Win32 `EnumDisplayDevicesW` reveals the true hardware attachment (`DISPLAY1` & `DISPLAY2` both wired directly to `GTX 1650`).
  2. Assigning `GpuPreference=1` (Power-Saving iGPU) to GUI/Browser/Electron apps when ALL physical monitors are plugged into the dGPU forces every frame to copy across PCIe from Intel UHD 730 → System RAM → GTX 1650 (Cross-Adapter Blit stutter + die heat).
  3. Hard affinity pinning (`0xF00`), `EcoQoS`, `PROCTHROTTLEMAX=99%` (disables 4.4 GHz Intel Turbo Boost → 2.59 GHz), and `NtSuspendProcess` on IPC-connected apps cause `Processor Queue Length = 25` at 15% CPU and severe desktop lag.
- **Permanent Rule:**
  1. Always inspect physical display-to-GPU topology via Win32 `EnumDisplayDevicesW`; when all displays are on the dGPU, set `GpuPreference=2` (Zero-Copy dGPU) + `SwapEffectUpgradeEnable=1`.
  2. Prefer remote offload (`svhome` / `Colab`) and VIP thread/MMCSS prioritization over choking local CPU cores, disabling Turbo Boost, or suspending active IPC processes.

## 2026-11-27 — Never Pass Raw Replacement Strings With Windows Backslashes to `re.sub`
- **Root Cause:** `_upsert_marked_block` in `chimera_tp/platform/unify.py` called `pat.sub(wrapped, existing, count=1)`. On the *second* run (when updating an existing marked block in `~/.codex/config.toml`), Python's `re.sub` interpreted `\\` in `"C:\\Program Files\\Python311\\python.exe"` as regex escapes, collapsing it to `"C:\Program Files\Python311\python.exe"` and breaking TOML parsing (`missing escaped value` at `\P`).
- **Permanent Rule:**
  1. Always pass a callable (`pat.sub(lambda _m: wrapped, existing, count=1)`) whenever replacing arbitrary text blocks containing paths or TOML/JSON content.
  2. Always test idempotent re-execution (`unify_install()` twice with Windows backslash paths) and validate written TOML via `tomllib.loads()`.


## 2026-11-27 — Production Regression Incident: Unaliased `contents[]` Injection Broke Live Gemini Implicit Prefix Cache (`93.91% -> 56.45%`)
- **What Happened:** `canonicalizeUniversalPrefixAnchor` moved volatile lines from `systemInstruction` into `contents[contents.length - 1]` (`<chimera_dynamic_meta>`) on every turn WITHOUT recording a Turn Alias, and `reconcilePhantomPrefix` tried to heal the resulting mismatch by appending `<chimera_state_delta>` at the tail. On Turn `k+1`, the client sent its raw unmodified history -> `firstDiffIndex = prevEntries - 1` every turn -> by Turn `k+4` divergent indices exceeded `maxDivergentTurns = 3` -> `isWarm` collapsed to `false` -> `15` `prefix-edit` cache cliffs dropped live `cacheHitPct` from **`93.91%`** down to **`56.45%`**.
- **Secondary Finding (`70,866`-token `side-query` bypass):** Antigravity Desktop sends stateless Flash side-queries with `purpose: "side-query"`, `toolCount: 0`, and **`contents.length === 1`** (entire 206 KB transcript packed into one `contents[0].parts[0].text` blob). Both `shieldColdSideQuery` (`contents.length < 3`) and `applyFlashLiposuctionVsa` (`contents.length < 6`) skipped it!
- **Iron Rule Going Forward:**
  1. **NEVER inject unaliased tags/wrappers/deltas into `contents[]` by default on live multi-turn Antigravity sessions.** Any optimization touching multi-turn `contents[]` MUST stay strictly opt-in until verified with `prefixEditsObserved === 0` on live multi-turn traffic.
  2. **Only transform stateless 1-entry `baseline` blobs (`contents.length === 1`, `toolCount === 0`, `cached === 0` ALWAYS)** by default — zero risk to any warm KV cache, massive instant savings (`-95%` on `70K–155K` Flash side-queries).
  3. **Always audit live `:12500/api/gemini/prism` & `local-usage.sqlite` 3–5 minutes after any gateway change** to confirm `cacheHitPct >= 90%` and `prefixEditsObserved == 0`!
