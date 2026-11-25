# CHIMERA-HYPER — Engineering Lessons

## Lesson 1 — Strict Layer Separation Between Transport Infrastructure and Downstream Apps (2026-11-25)
- **Correction:** Keep application-specific workflows (e.g., bounty patch memory, LLM prompt-cache stack batching, per-bounty USD ROI accounting) inside their own repositories (`radar_dashboard`, `Tqouta`) rather than crowding `chimera-tp`.
- **Rule for `chimera-tp`:** Proposals and core implementations in `chimera-tp` must operate at the **transport, cryptography, OS virtualization, compression, or distributed computation primitive layer** — elevating every system above it without domain-specific coupling.
