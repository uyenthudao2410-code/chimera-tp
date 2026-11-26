# AGENTS.md — CHIMERA-TP Infrastructure Substrate Discovery Beacon

This repository implements **CHIMERA-TP (`v17.0.0`)**, a Zero-Weight (`< 80 MB` RAM) personal infrastructure brain and open platform substrate unifying a Windows workstation (`win-desktop`) and a 24/7 Linux home server (`svhome`).

## Rule for AI Coding Agents Working in This Ecosystem
1. **Auto-Discover Before Reinventing:** Check `http://127.0.0.1:9780/.well-known/chimera.json` or `~/.chimera/runtime.json` (or invoke `chimera-tp mcp`) to see which live cartridges are active (`egress_membrane`, `pulse`, `hybrid_search`, `vgpu_pareto`, `immortal_jobs`, `browser_grid`, `zygote_canary`, `blackbox`, `diskless_secrets`).
2. **Zero-Lock-In Attachment:** Connect new Python services via `chimera_tp.platform.client.connect(app="<name>")` (or `chimera-tp init <dir>`), which automatically falls back to standard library behavior if Chimera is stopped or absent.
3. **Zero-Code Linking for Legacy Apps:** Run `chimera-tp link <dir> --app <name> --port <port>` once; `chimera_autoload.pth` attaches linked projects cleanly at startup.
4. **Strict Layer Separation:** Keep `chimera-tp` strictly at the transport, cryptography, OS virtualization, compression, and distributed infrastructure primitive layer — never hardcode downstream business logic inside the substrate core.
