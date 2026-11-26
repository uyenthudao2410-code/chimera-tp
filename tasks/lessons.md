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
