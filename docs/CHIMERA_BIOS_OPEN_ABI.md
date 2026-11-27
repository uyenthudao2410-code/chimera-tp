# CHIMERA-BIOS Open Ecosystem ABI Specification

*Version: `1.0` · Architecture: Living Open-Platform Substrate (NVIDIA-CUDA-Style Open Soul) · Laws: `CHIMERA-ONE` Invariants 1–7*

> **Design Principle:** Any application, AI coding agent, daemon, mobile/browser Spore, or native process (Python, Node.js, Rust, C/C++, Go, Shell) can bind to **CHIMERA-BIOS** through a single open ABI — zero vendor lock-in, zero mandatory runtime dependency, graceful offline fallback, and `0 B` daemon startup RSS overhead via strict lazy-loading.

---

## 1. Architecture Overview (10 Living Organs → 1 Zero-Weight Hub)

`ChimeraBiosOrganism` (`chimera_tp.platform.bios.organism`) unifies all 10 living physiological, immune, cognitive, and identity organs behind one lazy-loaded facade (`PlatformSubstrate.bios`, initialized to `self._bios = None` at boot):

| # | Organ | Module | Role in Closed-Loop Living Tick |
|---|---|---|---|
| 1 | **`CHIMERA-ENDOCRINE`** | `bios/endocrine.py` | 6-hormone continuous soup (`adrenaline`, `cortisol`, `dopamine`, `melatonin`, `cytokine`, `oxytocin`) synced to 24-byte NIXL mmap + 12-byte PHANTOM wire |
| 2 | **`CHIMERA-FRISTON`** | `bios/friston.py` | `< 64 KB` Active Inference generative world-model: context-conditioned Surprise (`-ln P(obs\|ctx)`), multi-horizon forecast, EFE action planning |
| 3 | **`CHIMERA-AUTOPHAGY`** | `bios/autophagy.py` | Metabolic ATP yield ledger, Ubiquitin dormancy tagging, LZ4/zlib cold archival, static AST codebase metabolism scan, Law-6 Apoptosis proposals |
| 4 | **`CHIMERA-PARASITE`** | `bios/parasite.py` | Isolated Red-Queen adversarial self-play arena (`6` attack vectors) auto-synthesizing Law-6 Vaccine Receipts & Immune Antibodies |
| 5 | **`CHIMERA-OCTOPUS`** | `bios/octopus.py` | `< 1 ms` offline `BinaryReflexTable` (`< 16 KB`), `SocketGanglion`, `HookGanglion`, `PeerSurvivalGanglion`, and HLC + BLAKE2s Merkle-CRDT `SynapticReconciler` |
| 6 | **`CHIMERA-STIGMERGY`** | `bios/stigmergy.py` | Zero-repo-mutation SQLite WAL pheromone skin (Alarm, Co-Edit Trail prefetch, Epigenetic Methylation, half-life evaporation, `< 40`-token smell-card) |
| 7 | **`CHIMERA-UMWELT`** | `bios/umwelt.py` | Zero-camera/zero-mic passive cognitive seismograph: Flow Shield, Frustration Whisper, Circadian hourly phase learner & 5-minute anticipation |
| 8 | **`CHIMERA-HGT`** | `bios/hgt.py` | Horizontal Gene Transfer: signed `< 8 KB` reusable Plasmid capsules, ecosystem target scanner, isolated A/B parity race & Law-6 Graft Proposals |
| 9 | **`CHIMERA-MYCELIUM`** | `bios/mycelium.py` | Living Spore mesh: capability-scoped tokens, GF(256) `(K=2, N=3)` blinded shards, `< 50 ms` zero-trace Autotomy, Seed inbox, `< 50 KB` zero-CDN PWA |
| 10 | **`CHIMERA-SOUL`** | `bios/soul.py` | SHA-256 hash-chained autobiographical scar & preference lineage exporting strictly `<= 500`-token model-agnostic Living Soul Capsules |

### Closed-Loop Physiological Tick (`POST /v1/bios/pulse`)

```text
  obs / passive signals
         │
         ▼
  [7] Umwelt.assess()  +  [2] Friston.observe(obs, context)
         │                         │
         └──────────┬──────────────┘
                    ▼
        [1] Endocrine.secrete(...) + decay()
             ├──► NIXL mmap bytes 32..63 (zero-copy us-scale broadcast)
             └──► 12-byte PHANTOM wire header (win-desktop ⇄ svhome)
                    │
        ┌───────────┼───────────────┐
        ▼           ▼               ▼
  [5] Octopus   [6] Stigmergy   [3] Autophagy
  reflex table   evaporate()    record_metabolism(ATP)
        │
        ▼
  Compact `bios_pulse` frame ──► SSE `/v1/bios/stream` & Noosphere Bridge
```

---

## 2. Binary Shared-Memory ABI (NIXL 64-Byte Header Layout)

CHIMERA-BIOS extends the existing 256 KiB cross-process `NixlSignalRing` (`chimera_nixl_ring.bin`) **non-destructively** by occupying the reserved upper half (`bytes 32..63`) of the 64-byte ring header. Bytes `0..31` remain 100% byte-compatible with `NixlSignalRing` (Python, Node.js `tquota`, Rust).

**Default mmap path resolution:**
1. `$CHIMERA_NIXL_RING` (if set)
2. Windows Dev Drive: `V:\nixl\chimera_nixl_ring.bin`
3. Linux shared memory: `/dev/shm/chimera_nixl_ring.bin`
4. Fallback: `~/.chimera/chimera_nixl_ring.bin`

### 64-Byte Header Offset Map (Little-Endian)

| Byte Offset | Size | Struct Format | Owner | Field |
|---:|---:|---|---|---|
| `0..3` | 4 B | `4s` | `NixlSignalRing` | `magic = b"NXLR"` |
| `4..7` | 4 B | `uint32` | `NixlSignalRing` | `version = 1` |
| `8..11` | 4 B | `uint32` | `NixlSignalRing` | `slot_count = 256` |
| `12..15` | 4 B | `uint32` | `NixlSignalRing` | `slot_bytes = 1024` |
| `16..23` | 8 B | `uint64` | `NixlSignalRing` | `write_seq` |
| `24..31` | 8 B | `uint64` | `NixlSignalRing` | `read_seq` |
| **`32..35`** | **4 B** | **`4s`** | **`CHIMERA-ENDOCRINE`** | **`magic = b"ENDO"`** |
| **`36..37`** | **2 B** | **`uint16`** | **`CHIMERA-ENDOCRINE`** | **`seq` (monotonic hormone publish counter)** |
| **`38..39`** | **2 B** | **`uint16`** | **`CHIMERA-ENDOCRINE`** | **`crc16` (CRC-16/CCITT-FALSE, poly `0x1021`, init `0xFFFF` over `magic + seq + 24B floats`)** |
| **`40..43`** | **4 B** | **`float32`** | **`CHIMERA-ENDOCRINE`** | **`adrenaline` `[0.0 .. 1.0]`** |
| **`44..47`** | **4 B** | **`float32`** | **`CHIMERA-ENDOCRINE`** | **`cortisol` `[0.0 .. 1.0]`** |
| **`48..51`** | **4 B** | **`float32`** | **`CHIMERA-ENDOCRINE`** | **`dopamine` `[0.0 .. 1.0]`** |
| **`52..55`** | **4 B** | **`float32`** | **`CHIMERA-ENDOCRINE`** | **`melatonin` `[0.0 .. 1.0]`** |
| **`56..59`** | **4 B** | **`float32`** | **`CHIMERA-ENDOCRINE`** | **`cytokine` `[0.0 .. 1.0]`** |
| **`60..63`** | **4 B** | **`float32`** | **`CHIMERA-ENDOCRINE`** | **`oxytocin` `[0.0 .. 1.0]`** |
| `64..262207` | 256 KiB | `256 × 1024 B` | `NixlSignalRing` | Ring event slots (unchanged) |

### 12-Byte PHANTOM Cross-Host Wire Codec (`<6H`)

For piggybacking live endocrine state onto UDP/PHANTOM control packets between `win-desktop` and `svhome`:
- Format: `<6H` (6 little-endian unsigned 16-bit integers = **12 bytes total**).
- Order: `(adrenaline, cortisol, dopamine, melatonin, cytokine, oxytocin)`.
- Quantization: `q = round(clamp(value, 0.0, 1.0) * 65535)`, decoded via `value = q / 65535.0` (resolution `~1.5e-5`).

---

## 3. Discovery & HTTP / JSON / SSE Contract (`/v1/bios/*`)

All routes are served on the single CHIMERA anchor gateway (default `http://127.0.0.1:9780`).
Discover capability status via `GET /.well-known/chimera.json` → `cartridges.bios` (`status` reports `"lazy_ready"` before first BIOS access and `"active"` once loaded, or `"disabled"` if toggled off).

| Method | Path | Content-Type | Purpose |
|---|---|---|---|
| `GET` | `/.well-known/chimera.json` | `application/json` | Discovery beacon listing `cartridges.bios` + `/v1/bios/abi` |
| `GET` | `/v1/bios/status` | `application/json` | Full 10-organ living organism status, RSS & Law 1–7 telemetry |
| `GET` | `/v1/bios/abi` | `application/json` | Machine-readable Open Ecosystem ABI manifest (offsets, routes, SDKs) |
| `GET` | `/v1/bios/hormones` | `application/json` | Live 6-hormone soup, trust ledger, inflamed loci & advisory directives |
| `POST` | `/v1/bios/hormones` | `application/json` | Secrete hormone (`hormone`, `delta`, `source`), adjust `oxytocin` trust (`action="trust"`), or `inflame` locus (`action="inflame"`) |
| `POST` | `/v1/bios/pulse` | `application/json` | Execute 1 closed-loop physiological tick (`obs`, `context`) and emit `bios_pulse` |
| `POST` | `/v1/bios/predict` | `application/json` | Friston Active Inference (`obs`, `context`, `horizon_s`, optional `action="observe"\|"predict"\|"plan"`) |
| `GET` | `/v1/bios/autophagy` | `application/json` | Metabolic ATP ledger & Ubiquitin dormancy overview |
| `POST` | `/v1/bios/autophagy` | `application/json` | Actions: `record`, `ubiquitin`, `scan`, `propose_apoptosis` (strictly `auto_activated=False`) |
| `GET` | `/v1/bios/parasite/status` | `application/json` | Red-Queen evolutionary ledger, survival rate & synthesized vaccines |
| `POST` | `/v1/bios/parasite/run` | `application/json` | Run isolated sandbox Red-Queen arena (`rounds`, `seed`) → Law-6 Vaccine Receipts |
| `GET` | `/v1/bios/ganglia` | `application/json` | Octopus peripheral ganglia status, binary reflex table & island mode |
| `POST` | `/v1/bios/ganglia/reconcile` | `application/json` | Order-independent HLC + BLAKE2s Merkle-CRDT `SynapticReconciler` merge (`local_events`, `peer_events`) |
| `GET` | `/v1/bios/pheromone` | `application/json` | Query `< 40`-token smell-card (`?repo=...&rel_path=...`) or overall stigmergy status |
| `POST` | `/v1/bios/pheromone` | `application/json` | Deposit alarm, record co-edit trail, apply epigenetic methylation, evaporate, or query smell-card |
| `GET` | `/v1/bios/umwelt` | `application/json` | Current cognitive seismograph (`flow_score`, `frustration_score`, `flow_shield`, circadian anticipation) |
| `POST` | `/v1/bios/umwelt` | `application/json` | Ingest passive signal (`event_kind`, `app`, `target`, `ok`) or trigger `anticipate` |
| `GET` | `/v1/bios/hgt` | `application/json` | List signed `< 8 KB` Plasmids and HGT status |
| `POST` | `/v1/bios/hgt` | `application/json` | Actions: `extract`, `scan`, `graft` (isolated A/B parity race → Law-6 Graft Proposal) |
| `GET` | `/v1/bios/spore` | `text/html; charset=utf-8` | Serves the self-contained, zero-CDN, Zero-WebGL `< 50 KB` **CHIMERA-BIOS Spore PWA** |
| `GET` | `/v1/bios/spores` | `application/json` | List attached living spores and pending voice/text seeds |
| `POST` | `/v1/bios/spore/attach` | `application/json` | Issue token & attach a mobile/browser/remote Spore (`device_name`, `role`, `capabilities`) |
| `POST` | `/v1/bios/spore/autotomy` | `application/json` | Instant `< 50 ms` zero-trace Spore severance (`spore_id`, `reason`) |
| `POST` | `/v1/bios/spore/seed` | `application/json` | Submit voice/text seed or approval (`spore_id`, `text`, `priority`) |
| `GET` | `/v1/bios/soul` | `application/json` | Export `<= 500`-token model-agnostic Living Soul Capsule (`?query=...&target_model=...&max_tokens=500`) + lineage verification |
| `POST` | `/v1/bios/soul/scar` | `application/json` | Record permanent SHA-256 hash-chained scar or preference into the autobiographical lineage |
| `GET` | `/v1/bios/sync/bundle` | `application/json` | Export compact `<= 32 KB` SHA-256-signed cross-host BIOS sync bundle (12B endocrine wire, CRDT events, Merkle root, alarms, scars, seeds) |
| `POST` | `/v1/bios/sync` | `application/json` | 2-way bidirectional cross-host sync (`win-desktop` ⇄ `svhome`): Mode 1 applies inbound peer `bundle` + optional `reply_bundle`; Mode 2 triggers live PHANTOM-5MS / HTTP 2-way sync |
| `GET` | `/v1/bios/stream` | `text/event-stream` | Live Server-Sent Events stream emitting standard `data: {"event":"bios_pulse",...}` JSON frames (`?once=1`, `?max_events=3`, `?interval_ms=200`) |

---

## 4. Multi-Language Zero-Lock-In Bindings

### Python (Zero-Lock-In SDK — Automatic Offline Fallback)

```python
from chimera_tp.platform.client import connect

brain = connect(app="my-service")                      # Auto-discovers :9780 or falls back cleanly offline
status = brain.bios_status()                           # 10-organ living snapshot
abi = brain.bios_abi()                                 # Machine-readable Open ABI manifest
soup = brain.bios_hormones()                           # Read 6 hormones + advisory directives
pulse = brain.bios_pulse(obs={"cpu_pct": 42.0}, context="coding")
pred = brain.bios_predict({"cpu_pct": 85.0}, context="cad", horizon_s=60.0)
smell = brain.bios_pheromone(".", "chimera_tp/cli.py") # < 40-token smell-card + trail prefetch
soul = brain.bios_soul(query="law 7 rss", target_model="claude", max_tokens=500)
sync = brain.bios_sync(blend=0.35)                     # 2-way cross-host PHANTOM/HTTP sync (offline fallback safe)
```

Direct zero-copy Python `mmap` read (`< 50 us`, zero HTTP):

```python
import mmap, struct

with open(r"V:\nixl\chimera_nixl_ring.bin", "rb") as fh:
    with mmap.mmap(fh.fileno(), 64, access=mmap.ACCESS_READ) as mm:
        magic, seq, crc16 = struct.unpack_from("<4sHH", mm, 32)
        if magic == b"ENDO":
            adrenaline, cortisol, dopamine, melatonin, cytokine, oxytocin = struct.unpack_from("<6f", mm, 40)
```

### Node.js / TypeScript (Zero Dependencies)

```js
// 1) Zero-copy NIXL mmap/file hormone read (bytes 32..63)
import fs from "node:fs";

const fd = fs.openSync("V:\\nixl\\chimera_nixl_ring.bin", "r");
const buf = Buffer.alloc(32);
fs.readSync(fd, buf, 0, 32, 32);
fs.closeSync(fd);
if (buf.subarray(0, 4).toString("ascii") === "ENDO") {
  const hormones = {
    seq: buf.readUInt16LE(4),
    crc16: buf.readUInt16LE(6),
    adrenaline: buf.readFloatLE(8),
    cortisol: buf.readFloatLE(12),
    dopamine: buf.readFloatLE(16),
    melatonin: buf.readFloatLE(20),
    cytokine: buf.readFloatLE(24),
    oxytocin: buf.readFloatLE(28),
  };
  console.log(hormones);
}

// 2) HTTP/JSON + SSE live pulse stream
const soul = await fetch("http://127.0.0.1:9780/v1/bios/soul?target_model=codex&max_tokens=500").then(r => r.json());
const es = new EventSource("http://127.0.0.1:9780/v1/bios/stream");
es.onmessage = (ev) => console.log(JSON.parse(ev.data));
```

### Rust (Zero-Copy Header Read)

```rust
use std::fs::File;
use std::io::{Read, Seek, SeekFrom};

pub struct EndocrineHeader {
    pub seq: u16,
    pub crc16: u16,
    pub hormones: [f32; 6], // adrenaline, cortisol, dopamine, melatonin, cytokine, oxytocin
}

pub fn read_endocrine_mmap(path: &str) -> std::io::Result<Option<EndocrineHeader>> {
    let mut f = File::open(path)?;
    f.seek(SeekFrom::Start(32))?;
    let mut raw = [0u8; 32];
    f.read_exact(&mut raw)?;
    if &raw[0..4] != b"ENDO" {
        return Ok(None);
    }
    let seq = u16::from_le_bytes([raw[4], raw[5]]);
    let crc16 = u16::from_le_bytes([raw[6], raw[7]]);
    let mut h = [0f32; 6];
    for i in 0..6 {
        let o = 8 + i * 4;
        h[i] = f32::from_le_bytes([raw[o], raw[o + 1], raw[o + 2], raw[o + 3]]);
    }
    Ok(Some(EndocrineHeader { seq, crc16, hormones: h }))
}
```

### `curl` & CLI

```bash
# HTTP / JSON / SSE
curl -s http://127.0.0.1:9780/v1/bios/abi | jq .
curl -s http://127.0.0.1:9780/v1/bios/hormones
curl -s -X POST http://127.0.0.1:9780/v1/bios/pulse -H "Content-Type: application/json" -d '{"context":"coding"}'
curl -sN "http://127.0.0.1:9780/v1/bios/stream?max_events=2"

# Unified CLI (works live against daemon or via local fallback)
chimera-tp bios status
chimera-tp bios abi
chimera-tp bios hormones
chimera-tp bios pulse --context coding
chimera-tp bios soul --query "law 7 rss" --model gemini
chimera-tp bios sync --blend 0.35
chimera-tp bios sync --peer-url http://127.0.0.1:9789 --blend 0.35
```

---

## 5. AI Coding Agent MCP Tools (`chimera-tp mcp`)

CHIMERA-BIOS adds 5 high-leverage JSON-RPC 2.0 MCP tools in `chimera_tp/platform/mcp_server.py`:

1. **`chimera_bios_status`** — Full 10-organ living organism status, RSS & Law 1–7 telemetry (or machine-readable ABI with `include_abi=true`).
2. **`chimera_bios_hormones`** — Read live 6-hormone soup & advisory directives, or secrete / adjust Oxytocin trust / inflame Cytokine locus.
3. **`chimera_bios_pheromone`** — Query `< 40`-token stigmergic smell-card & co-edit trail prefetch, deposit alarm pheromone, record co-edit, or apply epigenetic methylation.
4. **`chimera_bios_soul`** — Export strictly `<= 500`-token model-agnostic Living Soul Capsule (`Gemini`, `Codex`, `Claude`, local LLMs) or record a SHA-256 hash-chained scar.
5. **`chimera_bios_evolve`** — Unified evolutionary & active-inference dispatcher (`action`: `pulse` | `predict` | `autophagy` | `parasite` | `hgt` | `ganglia` | `umwelt` | `spore`) — strictly Law-6 gated (`auto_activated=False`).

---

## 6. Spore PWA & Zero-Trace Autotomy Protocol

- **Single-URL Open Spore UI:** `GET /v1/bios/spore` serves a self-contained HTML5/CSS/JS PWA (`< 50 KB`, zero external CDNs, zero WebGL) connecting live to `/v1/bios/status` and `/v1/bios/stream`.
- **Zero-Trust GF(256) Blinded Shards:** Volunteer spores compute over `(K=2, N=3)` blinded shares — no single untrusted spore ever receives plaintext secrets.
- **Instant Zero-Trace Autotomy:** `POST /v1/bios/spore/autotomy` revokes capability tokens, zeroes ephemeral keys, drops state, and returns a signed autotomy receipt in `< 50 ms`.

---

## 7. 2-Way Bidirectional Cross-Host Synchronization (`win-desktop` ⇄ `svhome`)

CHIMERA-BIOS synchronizes living physiological, immune, stigmergic, mycelium, and autobiographical state bidirectionally across `win-desktop` and `svhome` in **1 HTTP round-trip** over `PHANTOM-5MS` (with authenticated direct HTTP fallback via `X-Chimera-Peer-Auth`):

### Protocol Routes

1. **`GET /v1/bios/sync/bundle`** (`?max_events=32&max_alarms=16&max_scars=16`):
   - Exports a compact, JSON-serializable, strictly `<= 32 KB` SHA-256-signed bundle (`schema: "chimera.bios.sync_bundle.v1"`):
     - `node_name`, `ts`, `bundle_sha256`, `auto_activated: false`
     - `endocrine_wire_b64`: base64 encoding of the exact **12-byte `<6H` PHANTOM hormone payload**
     - `hormones`: 6-hormone snapshot
     - `crdt_events`: Octopus `PeerSurvivalGanglion` HLC-stamped CRDT events (stamps a `bios_sync_heartbeat` event if empty so convergence is always verifiable)
     - `merkle_root`: deterministic 128-bit BLAKE2s Merkle root (`SynapticReconciler`)
     - `stigmergy_alarms`: top active decayed alarm pheromones (`repo`, `rel_path`, `signal_kind`, `severity`, `reason`)
     - `soul_scars`: recent verified `AutobiographicalSoul` scars (`title`, `event_date`, `root_cause`, `lesson_law`, `hardware_context`, `tags`, `severity`, `entry_hash`)
     - `mycelium_seeds`: recent Mycelium Seed Inbox items (`seed_id`, `spore_id`, `text`, `priority`, `created_at`)

2. **`POST /v1/bios/sync`**:
   - **Mode 1 — Inbound Peer Sync** (JSON body contains `"bundle"`):
     - Authorized via loopback / `PHANTOM-5MS` tunnel or verified `X-Chimera-Peer-Auth` peer header.
     - Enforces **Law 3 `<= 64 KB` payload cap** and **Law 4 `bundle_sha256` integrity verification**.
     - Blends the 12-byte `endocrine_wire_b64` payload via `endocrine.apply_wire_12b(raw_12b, blend=blend)` (immediately flushing `ENDO` + `CRC16` into local NIXL mmap bytes `32..63`).
     - Reconciles `crdt_events` via order-independent BLAKE2s Merkle-CRDT `SynapticReconciler` and persists merged events (deduped by `event_id`).
     - Idempotently imports peer Stigmergy alarms (zero repo file mutation), missing Soul scars (keyed by `(title, event_date)` so the SHA-256 hash chain stays valid without duplicates), and missing Mycelium seeds (keyed by `seed_id`, respecting autotomy revocations).
     - Refreshes the Octopus binary reflex table and records metabolic ATP in Autophagy.
     - When `"bidirectional": true`, embeds `"reply_bundle"` so **1 HTTP round-trip completes a full 2-way sync**.
   - **Mode 2 — Active 2-Way Trigger** (JSON body omits `"bundle"`, optionally supplying `peer_url`, `blend`, `timeout_s`):
     - Automatically resolves the peer via `daemon.active_edge_peer_base()` (`PHANTOM-5MS`) with automatic fallback to `daemon.peer_http_base()` (signed with `daemon.authenticate_peer_request`).
     - Pushes local bundle `A`, applies peer's `reply_bundle` `B`, confirms exact `local_merkle_root == peer_merkle_root` convergence (running 1 zero-blend confirmation hop only if a concurrent event arrived mid-flight), and returns a Law-4 SHA-256-signed 2-way receipt (`merkle_converged`, `local_merkle_root`, `peer_merkle_root`, `rtt_ms`, `endocrine_wire_bytes=12`, `scars_synced`, `alarms_synced`, `seeds_synced`, `auto_activated=False`).

### SDK & CLI Usage

```python
from chimera_tp.platform.client import connect

brain = connect(app="sync-ops")
receipt = brain.bios_sync(blend=0.35)  # Auto-discovers PHANTOM/HTTP peer; offline fallback returns local bundle
assert receipt["ok"]
```

```bash
# Auto-resolved PHANTOM-5MS / peer HTTP 2-way sync
chimera-tp bios sync --blend 0.35

# Explicit peer URL override
chimera-tp bios sync --peer-url http://127.0.0.1:9789 --blend 0.35
```

---

## 8. Constitutional Compliance (`CHIMERA-ONE` Laws 1–7)

| Law | Constitutional Guarantee in CHIMERA-BIOS |
|---|---|
| **Law 1 — Eliminate Before Offload** | Autophagy tracks ATP yield per organ/module and flags zero-ATP dead code before shifting work; Stigmergy & Friston prevent wasted speculative work. |
| **Law 2 — Zero-Choke Kernel Law** | Advisory physiology only. Zero CPU affinity pinning (`SetProcessAffinityMask` / `0xF00`), zero forced `EcoQoS`, zero `NtSuspendProcess`, zero `PROCTHROTTLEMAX` throttling. |
| **Law 3 — Mutual Homeostasis & Peer Guard** | `PeerSurvivalGanglion` enforces `svhome` 15W island-mode protection; 12-byte PHANTOM wire header carries full hormone telemetry without bandwidth overhead. |
| **Law 4 — Content-Addressed Work Unit** | SHA-256 hash-chained Soul lineage, BLAKE2s Merkle-CRDT Synaptic Reconciler, SHA-256 signed HGT Plasmids & Autophagy dormant archives. |
| **Law 5 — Dual-Budget Placement** | Friston Active Inference models RTT + 4-hemisphere load separately from user GUI responsiveness (`cad`, `coding`, `research`, `idle`). |
| **Law 6 — Evidence-Gated Rollback** | **Every** evolutionary output (Autophagy Apoptosis PRs, Parasite Vaccine Receipts, HGT Graft Proposals) enforces `auto_activated=False` and `requires_human_approval=True`. |
| **Law 7 — Reverse-Consolidation & `< 80 MiB` RSS** | `PlatformSubstrate.__init__` sets `self._bios = None` (`0 B` boot RSS impact; zero eager imports of `chimera_tp.platform.bios`). Total lazy-loaded BIOS working set `< 3 MiB`; daemon RSS strictly `< 80 MiB`. |
