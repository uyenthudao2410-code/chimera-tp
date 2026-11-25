# Architecture — CHIMERA-HYPER v3.0.0 Zero-Weight HyperGrid

```
+----------------------------------------------------------------------------------+
|                    Control, Observability & Zero-Weight Plane                    |
|   HTTP Cockpit (:9780)  |  SQLite Contextual 24h UCB1 & Link-Weather Estimator   |
|   Zero-Weight RSS Guard (<80 MB) | Built-in Scheduler + Task Scheduler / systemd |
+----------------------------------------+-----------------------------------------+
                                         |
   +-------------------+-----------------+------------------+--------------------+
   v                   v                                    v                    v
+--------------+  +------------------+            +------------------+  +------------------+
| Merkle Sync  |  | Fluid Pushdown   |            |   Telepathic     |  |    Immortal      |
| Shadow Index |  | AQ02 Operators   |            |   ZDict + Fold   |  | Multi-Path RLNC  |
| b"CHMRK1"    |  | Analytics / SQL  |            | b"CHTC1"+"CHLF1" |  | IPv4+IPv6 Stripe |
+------+-------+  +--------+---------+            +--------+---------+  +--------+---------+
       |                   |                               |                     |
       +-------------------+-------------------------------+---------------------+
                                           |
                                           v
+----------------------------------------------------------------------------------+
|                        Cross-Platform Silicon Core (Bit-Identical)               |
|   Windows: Rust cdylib (VGF2P8AFFINEQB GFNI / AVX2 + Win32 Shared Memory Ring)   |
|   Linux:   C11 .so    (AVX2 VPSHUFB Split-Nibble GF256 + POSIX /dev/shm Ring)    |
+----------------------------------------------------------------------------------+
```

## 1. Zero-Weight Merkle Directory DNA Sync (`chimera_tp/merkle_sync.py`)
- **Zero Polling Daemon**: No background `inotify`/`ReadDirectoryChangesW` watchers eating desktop CPU/handles.
- **Shadow Index (`ShadowMerkleIndex`)**: Stores `{rel_path: {size, mtime_ns, blake2b_16}}` locally. When unchanged, `scan()` skips file reads completely (`~2 ms` for 16 files).
- **Sparse `CHMRK1` Bundle**: `POST /api/merkle/diff` compares manifests by `(size, hash)` cleanly across OS clocks. When `root_hash` matches, sync terminates in 0 bytes transferred; otherwise only dirty files and tombstones traverse `BeamServer` (`kind=3`, FastCDC + Odess delta).

## 2. Fluid Pushdown Compute `AQ02` (`chimera_tp/active_pipe.py`)
Runs directly inside the peer's `ActiveQueryServer` next to storage:
- `log_analytics`: normalizes timestamps, IPv4 addresses, hex hashes, and integers into distinct structural templates + severity buckets + hourly breakdown.
- `multi_grep`: multi-pattern/regex search across directories (`allowed_roots`-contained, skipping binary/ignored dirs).
- `sqlite_query`: validates single-statement `SELECT`/`WITH`/`PRAGMA TABLE_INFO|TABLE_LIST` allowlist, opens SQLite via `file:...?mode=ro` URI, enforces 3s `progress_handler` deadline and `max_rows` limit.
- `remote_digest`: fast Merkle root + largest-file manifest computation.

## 3. Telepathic Dictionary & Template Compression (`chimera_tp/telepathy.py`)
- `train_domain_dictionary()` extracts top recurring prefixes/lines from up to 512 KiB of corpus and lays out `zdict` (`<= 32 KiB`) with the highest-frequency sequences at the **tail** for optimal zlib shortest-offset matching.
- `_fold_tokens_lossless()` builds an arbitrary-byte-safe escape dictionary (`CHLF1`, escaping `0xFF` bytes) so repetitive filtered log hits shrink far past vanilla `zlib`.
- `TelepathicCodec` competes `RAW` vs `ZLIB` vs `ZDICT` vs `FOLD+ZDICT` automatically per message under frame `CHTC1`, backed by a bounded 16-entry LRU cache (`< 512 KiB` RAM).

## 4. Immortal Stateless Multi-Path Striping (`chimera_tp/hyper_wire.py`)
- `ImmortalMultiPathSender` stripes systematic and GF(256) repair frames round-robin across independent IPv4 and IPv6 sockets (`:9706`, `:9707`) carrying identical `stream_id` and `gen_id`.
- `ImmortalMultiPathReceiver` ingests frames from all NICs into one unified GF(256) decoder matrix and broadcasts `GEN_ACK` / `GEN_NEED` / `FIN_ACK` symmetrically across every registered `(socket, addr)` peer tuple so killing an entire IP path mid-stream heals immediately without session reset.

## 5. Contextual 24h Link-Weather & Zero-Weight Guard (`chimera_tp/autopilot.py`, `dashboard.py`)
- Classifies runs into `NIGHT_CLEAN` (`00–07`), `MORNING` (`07–12`), `AFTERNOON` (`12–19`), and `PEAK_EVENING` (`19–24`).
- Stores contextual pull statistics (`context_genomes`) and exponential moving link weather (`link_weather`) in SQLite, recommending clean windows for heavy scheduled syncs.
- Queries OS process working set (`GetProcessMemoryInfo` / `/proc/self/status`) and host free RAM natively to surface real-time Zero-Weight health on `/api/health` and `/api/status`.
