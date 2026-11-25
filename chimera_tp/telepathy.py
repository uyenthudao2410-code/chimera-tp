"""Breakthrough #6: Telepathic Domain-Trained Dictionary + Lossless Line-Template Compression."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import struct
import threading
import time
import zlib
from collections import Counter, OrderedDict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_TELE_HDR = struct.Struct("!5sBBI")  # magic="CHTC1", mode(B), dict_id_len(B), orig_len(I)
_TELE_MAGIC = b"CHTC1"
_FOLD_MAGIC = b"CHLF1"

_MODE_RAW = 0
_MODE_ZLIB = 1
_MODE_ZDICT = 2
_MODE_FOLD_ZLIB = 3

_FALLBACK_DICT = (
    b"2026- INFO WARN ERROR DEBUG CRITICAL traceback timeout failed ok "
    b'status=200 status=500 GET POST HTTP/1.1 application/json {"id": "ts": "msg":}\n'
)

_TOKEN_RE = re.compile(rb"(?:\[[^\r\n\]]{1,48}\]|\"[^\r\n\"]{2,36}\":?|[A-Za-z0-9_./:=-]{6,64})")


@dataclass
class DomainDictionary:
    dict_id: str
    domain: str
    zdict: bytes
    templates: list[str]
    created_utc: str

    def to_meta_dict(self) -> dict[str, Any]:
        return {
            "dict_id": self.dict_id,
            "domain": self.domain,
            "dict_bytes": len(self.zdict),
            "templates": list(self.templates),
            "created_utc": self.created_utc,
        }

    def to_wire_dict(self) -> dict[str, Any]:
        d = self.to_meta_dict()
        d["zdict_b64"] = base64.b64encode(self.zdict).decode("ascii")
        return d

    @classmethod
    def from_wire_dict(cls, obj: dict[str, Any]) -> "DomainDictionary":
        zdict = base64.b64decode(obj["zdict_b64"].encode("ascii"))
        return cls(
            dict_id=str(obj["dict_id"]),
            domain=str(obj.get("domain", "default")),
            zdict=zdict,
            templates=[str(t) for t in obj.get("templates", [])],
            created_utc=str(obj.get("created_utc", "")),
        )


def train_domain_dictionary(
    samples: list[bytes],
    domain: str = "default",
    max_dict_bytes: int = 32768,
) -> DomainDictionary:
    """Train a compact 32 KiB zlib preset dictionary optimized for domain logs/code/JSON."""
    max_dict_bytes = max(512, min(32768, int(max_dict_bytes)))
    budget = 512 * 1024
    buf = bytearray()
    for s in samples:
        if not s:
            continue
        rem = budget - len(buf)
        if rem <= 0:
            break
        buf.extend(s[:rem])
    corpus = bytes(buf)

    line_counts: Counter[bytes] = Counter()
    seg_counts: Counter[bytes] = Counter()

    if corpus:
        for line in corpus.splitlines(keepends=True):
            if 10 <= len(line) <= 200:
                line_counts[line] += 1
            # Extract post-timestamp recurring suffix if line starts with '[' or digit timestamp
            if len(line) >= 24 and (line[0] == 91 or (48 <= line[0] <= 57)):
                idx = line.find(b"] ")
                if 10 <= idx <= 36 and len(line) - idx > 10:
                    seg_counts[line[idx + 2 :]] += 1
            for m in _TOKEN_RE.findall(line):
                seg_counts[m] += 1

    scored: dict[bytes, int] = {}
    for tok, freq in line_counts.items():
        if freq >= 2:
            scored[tok] = max(scored.get(tok, 0), (freq - 1) * len(tok))
    for tok, freq in seg_counts.items():
        if freq >= 3:
            scored[tok] = max(scored.get(tok, 0), (freq - 1) * len(tok))

    # Rank descending to choose best tokens, then reverse at the end so hottest stay near tail
    ranked = sorted(scored.items(), key=lambda kv: (kv[1], len(kv[0])), reverse=True)
    chosen: list[bytes] = []
    total_len = 0
    seen_concat = bytearray()

    for tok, _score in ranked:
        if len(chosen) >= 400:
            break
        # Avoid pure duplicate or tiny slice already embedded inside an existing top token
        if tok in seen_concat and len(tok) < 24:
            continue
        add_len = len(tok) + (1 if chosen else 0)
        if total_len + add_len > max_dict_bytes:
            continue
        chosen.append(tok)
        seen_concat.extend(tok)
        seen_concat.append(10)
        total_len += add_len

    if not chosen and corpus:
        # Fallback: sample evenly across corpus tail up to max_dict_bytes
        raw_tail = corpus[-max_dict_bytes:]
        zdict = raw_tail if len(raw_tail) >= 64 else (_FALLBACK_DICT + raw_tail)
    elif not chosen:
        zdict = _FALLBACK_DICT
    else:
        # Zlib preset dictionaries give highest priority (shortest offsets) to the END of zdict
        chosen.reverse()
        zdict = b"".join(chosen)

    if len(zdict) > max_dict_bytes:
        zdict = zdict[-max_dict_bytes:]

    dict_id = hashlib.blake2s(zdict, digest_size=8).hexdigest()
    templates = [
        t.decode("utf-8", errors="replace").strip()
        for t, _ in ranked[:16]
        if t.strip()
    ]
    return DomainDictionary(
        dict_id=dict_id,
        domain=domain,
        zdict=zdict,
        templates=templates,
        created_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )


class TelepathicStore:
    """Bounded LRU store (<= 512 KiB RAM) persisting trained DomainDictionaries to disk."""

    def __init__(self, dict_dir: Path | None = None, max_mem_dicts: int = 16) -> None:
        self.dict_dir = Path(dict_dir) if dict_dir is not None else None
        self.max_mem_dicts = max(1, min(32, int(max_mem_dicts)))
        self._lock = threading.Lock()
        self._cache: OrderedDict[str, DomainDictionary] = OrderedDict()
        self._domain_latest: dict[str, str] = {}
        if self.dict_dir is not None:
            self.dict_dir.mkdir(parents=True, exist_ok=True)
            self._load_index()

    def _load_index(self) -> None:
        if self.dict_dir is None or not self.dict_dir.exists():
            return
        for jf in sorted(self.dict_dir.glob("*.json")):
            if jf.name.endswith(".tmp"):
                continue
            try:
                meta = json.loads(jf.read_text(encoding="utf-8"))
                did = str(meta["dict_id"])
                dom = str(meta.get("domain", "default"))
                self._domain_latest[dom] = did
            except Exception:
                continue

    def _cache_put(self, d: DomainDictionary) -> None:
        self._cache[d.dict_id] = d
        self._cache.move_to_end(d.dict_id)
        while len(self._cache) > self.max_mem_dicts:
            self._cache.popitem(last=False)
        self._domain_latest[d.domain] = d.dict_id

    def put(self, d: DomainDictionary) -> None:
        with self._lock:
            self._cache_put(d)
            if self.dict_dir is not None:
                self.dict_dir.mkdir(parents=True, exist_ok=True)
                zpath = self.dict_dir / f"{d.dict_id}.zdict"
                jpath = self.dict_dir / f"{d.dict_id}.json"
                ztmp = self.dict_dir / f"{d.dict_id}.zdict.tmp"
                jtmp = self.dict_dir / f"{d.dict_id}.json.tmp"
                ztmp.write_bytes(d.zdict)
                os.replace(ztmp, zpath)
                jtmp.write_text(
                    json.dumps(d.to_meta_dict(), indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
                os.replace(jtmp, jpath)

    def get(self, dict_id: str) -> DomainDictionary | None:
        if not dict_id or not re.fullmatch(r"[0-9a-fA-F]{8,64}", dict_id):
            return None
        with self._lock:
            cached = self._cache.get(dict_id)
            if cached is not None:
                self._cache.move_to_end(dict_id)
                return cached
            if self.dict_dir is None:
                return None
            zpath = self.dict_dir / f"{dict_id}.zdict"
            jpath = self.dict_dir / f"{dict_id}.json"
            if not zpath.exists() or not jpath.exists():
                return None
            meta = json.loads(jpath.read_text(encoding="utf-8"))
            d = DomainDictionary(
                dict_id=dict_id,
                domain=str(meta.get("domain", "default")),
                zdict=zpath.read_bytes(),
                templates=[str(t) for t in meta.get("templates", [])],
                created_utc=str(meta.get("created_utc", "")),
            )
            self._cache_put(d)
            return d

    def latest_for_domain(self, domain: str) -> DomainDictionary | None:
        with self._lock:
            did = self._domain_latest.get(domain)
        return self.get(did) if did else None

    def list_dicts(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        if self.dict_dir is not None and self.dict_dir.exists():
            for jf in sorted(self.dict_dir.glob("*.json")):
                try:
                    out.append(json.loads(jf.read_text(encoding="utf-8")))
                except Exception:
                    continue
        else:
            with self._lock:
                out = [d.to_meta_dict() for d in self._cache.values()]
        return out


def _fold_tokens_lossless(data: bytes) -> bytes | None:
    """Losslessly fold recurring high-frequency segments via 2-byte escape tokens (b'CHLF1')."""
    if len(data) < 256:
        return None
    counts: Counter[bytes] = Counter()
    for line in data.splitlines(keepends=True):
        if 12 <= len(line) <= 180:
            counts[line] += 1
        if len(line) >= 24 and (line[0] == 91 or (48 <= line[0] <= 57)):
            idx = line.find(b"] ")
            if 10 <= idx <= 36 and len(line) - idx >= 12:
                counts[line[idx + 2 :]] += 1
        for m in _TOKEN_RE.findall(line):
            if len(m) >= 8:
                counts[m] += 1

    # Rank candidates by estimated net byte savings
    cands: list[tuple[int, bytes]] = []
    for tok, freq in counts.items():
        if freq < 3 or len(tok) < 8:
            continue
        gain = freq * (len(tok) - 2) - (len(tok) + 2)
        if gain > 24:
            cands.append((gain, tok))
    if not cands:
        return None

    cands.sort(key=lambda x: (-x[0], -len(x[1])))
    tokens: list[bytes] = []
    # Sort selected patterns longest-first for greedy alternation matching
    for _, tok in cands[:128]:
        tokens.append(tok)
    tokens.sort(key=len, reverse=True)
    tok_to_id = {t: idx for idx, t in enumerate(tokens)}

    pat = re.compile(b"|".join(re.escape(t) for t in tokens))
    out = bytearray(_FOLD_MAGIC)
    out.extend(struct.pack("<H", len(tokens)))
    for t in tokens:
        out.extend(struct.pack("<H", len(t)))
        out.extend(t)

    def _emit_literal(chunk: bytes) -> None:
        if b"\xff" in chunk:
            out.extend(chunk.replace(b"\xff", b"\xff\xff"))
        else:
            out.extend(chunk)

    pos = 0
    for m in pat.finditer(data):
        if m.start() > pos:
            _emit_literal(data[pos : m.start()])
        tid = tok_to_id[m.group(0)]
        out.append(0xFF)
        out.append(tid)
        pos = m.end()
    if pos < len(data):
        _emit_literal(data[pos:])

    return bytes(out) if len(out) < len(data) else None


def _unfold_tokens_lossless(blob: bytes) -> bytes:
    """Invert b'CHLF1' back into bit-exact original bytes."""
    if not blob.startswith(_FOLD_MAGIC):
        raise ValueError("Invalid CHLF1 template-fold magic")
    pos = len(_FOLD_MAGIC)
    (n_tokens,) = struct.unpack_from("<H", blob, pos)
    pos += 2
    tokens: list[bytes] = []
    for _ in range(n_tokens):
        (tlen,) = struct.unpack_from("<H", blob, pos)
        pos += 2
        tokens.append(blob[pos : pos + tlen])
        pos += tlen

    out = bytearray()
    mv = memoryview(blob)
    total = len(blob)
    while pos < total:
        # Fast-scan to next 0xFF sentinel
        idx = blob.find(b"\xff", pos)
        if idx == -1:
            out.extend(mv[pos:])
            break
        if idx > pos:
            out.extend(mv[pos:idx])
        if idx + 1 >= total:
            raise ValueError("Truncated CHLF1 escape sequence")
        nxt = blob[idx + 1]
        if nxt == 0xFF:
            out.append(0xFF)
        else:
            out.extend(tokens[nxt])
        pos = idx + 2
    return bytes(out)


class TelepathicCodec:
    """Selects optimal lossless encoding among RAW, ZLIB, ZLIB+ZDict, and TemplateFold+ZDict."""

    def encode(
        self,
        data: bytes,
        domain_dict: DomainDictionary | None = None,
        allow_template_fold: bool = True,
    ) -> tuple[bytes, dict[str, Any]]:
        orig_len = len(data)
        if orig_len == 0:
            hdr = _TELE_HDR.pack(_TELE_MAGIC, _MODE_RAW, 0, 0)
            return hdr, {
                "orig_bytes": 0,
                "plain_zlib_bytes": 0,
                "wire_bytes": len(hdr),
                "mode": _MODE_RAW,
                "mode_name": "raw",
                "dict_id": "",
                "saved_vs_raw_pct": 0.0,
                "extra_saved_vs_zlib_pct": 0.0,
            }

        plain_comp = zlib.compress(data, 6)
        candidates: list[tuple[int, int, bytes, bytes]] = [
            (_TELE_HDR.size + orig_len, _MODE_RAW, b"", data),
            (_TELE_HDR.size + len(plain_comp), _MODE_ZLIB, b"", plain_comp),
        ]

        dict_id_b = domain_dict.dict_id.encode("ascii") if domain_dict else b""
        if domain_dict is not None and domain_dict.zdict:
            co = zlib.compressobj(level=6, zdict=domain_dict.zdict)
            zdict_comp = co.compress(data) + co.flush()
            candidates.append(
                (_TELE_HDR.size + len(dict_id_b) + len(zdict_comp), _MODE_ZDICT, dict_id_b, zdict_comp)
            )

        if allow_template_fold and 256 <= orig_len <= 4 * 1024 * 1024:
            folded = _fold_tokens_lossless(data)
            if folded is not None:
                if domain_dict is not None and domain_dict.zdict:
                    co_f = zlib.compressobj(level=6, zdict=domain_dict.zdict)
                    f_comp = co_f.compress(folded) + co_f.flush()
                    f_did = dict_id_b
                else:
                    f_comp = zlib.compress(folded, 6)
                    f_did = b""
                candidates.append(
                    (_TELE_HDR.size + len(f_did) + len(f_comp), _MODE_FOLD_ZLIB, f_did, f_comp)
                )

        best_total, best_mode, best_did, best_body = min(candidates, key=lambda c: c[0])
        frame = _TELE_HDR.pack(_TELE_MAGIC, best_mode, len(best_did), orig_len) + best_did + best_body

        mode_names = {
            _MODE_RAW: "raw",
            _MODE_ZLIB: "zlib",
            _MODE_ZDICT: "telepathic_zdict",
            _MODE_FOLD_ZLIB: "telepathic_fold_zdict",
        }
        plain_total = len(plain_comp)
        saved_vs_raw = max(0.0, 100.0 * (1.0 - (len(frame) / orig_len)))
        extra_vs_zlib = (
            100.0 * (1.0 - (len(frame) / max(1, plain_total)))
            if plain_total > 0
            else 0.0
        )
        return frame, {
            "orig_bytes": orig_len,
            "plain_zlib_bytes": plain_total,
            "wire_bytes": len(frame),
            "mode": best_mode,
            "mode_name": mode_names.get(best_mode, "unknown"),
            "dict_id": best_did.decode("ascii"),
            "saved_vs_raw_pct": round(saved_vs_raw, 2),
            "extra_saved_vs_zlib_pct": round(extra_vs_zlib, 2),
        }

    def decode(
        self,
        frame: bytes,
        store: TelepathicStore | None = None,
        domain_dict: DomainDictionary | None = None,
    ) -> bytes:
        if not frame.startswith(_TELE_MAGIC):
            return frame
        if len(frame) < _TELE_HDR.size:
            raise ValueError("Truncated CHTC1 header")
        magic, mode, did_len, orig_len = _TELE_HDR.unpack_from(frame, 0)
        if magic != _TELE_MAGIC:
            return frame
        pos = _TELE_HDR.size
        dict_id = frame[pos : pos + did_len].decode("ascii") if did_len else ""
        body = frame[pos + did_len :]

        if mode == _MODE_RAW:
            out = body
        elif mode == _MODE_ZLIB:
            out = zlib.decompress(body)
        elif mode in (_MODE_ZDICT, _MODE_FOLD_ZLIB):
            dd: DomainDictionary | None = None
            if dict_id:
                if domain_dict is not None and domain_dict.dict_id == dict_id:
                    dd = domain_dict
                elif store is not None:
                    dd = store.get(dict_id)
                if dd is None:
                    raise KeyError(f"Missing Telepathic DomainDictionary dict_id={dict_id}")
                do = zlib.decompressobj(zdict=dd.zdict)
                raw_or_folded = do.decompress(body) + do.flush()
            else:
                raw_or_folded = zlib.decompress(body)
            out = _unfold_tokens_lossless(raw_or_folded) if mode == _MODE_FOLD_ZLIB else raw_or_folded
        else:
            raise ValueError(f"Unsupported CHTC1 compression mode: {mode}")

        if len(out) != orig_len:
            raise ValueError(f"Telepathic decode length mismatch: {len(out)} != {orig_len}")
        return out


def benchmark_compression(data: bytes, domain_dict: DomainDictionary) -> dict[str, Any]:
    """Compare raw size vs plain zlib vs Telepathic domain compression with lossless check."""
    codec = TelepathicCodec()
    t0 = time.perf_counter()
    frame, stats = codec.encode(data, domain_dict=domain_dict, allow_template_fold=True)
    enc_ms = (time.perf_counter() - t0) * 1000.0
    t1 = time.perf_counter()
    restored = codec.decode(frame, domain_dict=domain_dict)
    dec_ms = (time.perf_counter() - t1) * 1000.0
    return {
        "raw_bytes": len(data),
        "plain_zlib_bytes": stats["plain_zlib_bytes"],
        "telepathic_bytes": len(frame),
        "mode_name": stats["mode_name"],
        "dict_id": domain_dict.dict_id,
        "vs_raw_saved_pct": stats["saved_vs_raw_pct"],
        "vs_zlib_saved_pct": stats["extra_saved_vs_zlib_pct"],
        "ratio_vs_raw": round(len(data) / max(1, len(frame)), 2),
        "encode_ms": round(enc_ms, 2),
        "decode_ms": round(dec_ms, 2),
        "lossless_ok": restored == data,
    }
