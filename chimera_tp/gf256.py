"""GF(256) RLNC fountain math, Lehmer permutation bijection, CRC-16, and chaos scheduler."""

from __future__ import annotations

import hashlib
import math
import struct
from typing import Iterable

# AES / Rijndael irreducible polynomial: x^8 + x^4 + x^3 + x + 1 (0x11B)
# Primitive element generator MUST be 0x03 (order 255). Do NOT use 0x02 (order 51).
_GF_POLY = 0x11B
_GF_GEN = 0x03


def _gf_slow_mul(a: int, b: int) -> int:
    res = 0
    while b:
        if b & 1:
            res ^= a
        a <<= 1
        if a & 0x100:
            a ^= _GF_POLY
        b >>= 1
    return res & 0xFF


def _build_gf_tables() -> tuple[list[int], list[int], list[int], list[bytes]]:
    exp = [0] * 512
    log = [0] * 256
    x = 1
    for i in range(255):
        exp[i] = x
        exp[i + 255] = x
        log[x] = i
        x = _gf_slow_mul(x, _GF_GEN)
    inv = [0] * 256
    for v in range(1, 256):
        inv[v] = exp[255 - log[v]]
    mul_bytes: list[bytes] = []
    for scalar in range(256):
        if scalar == 0:
            mul_bytes.append(bytes(256))
        elif scalar == 1:
            mul_bytes.append(bytes(range(256)))
        else:
            ls = log[scalar]
            mul_bytes.append(
                bytes(0 if b == 0 else exp[ls + log[b]] for b in range(256))
            )
    return exp, log, inv, mul_bytes


EXP, LOG, INV, MUL_BYTES = _build_gf_tables()


def gf_mul(a: int, b: int) -> int:
    if a == 0 or b == 0:
        return 0
    return EXP[LOG[a] + LOG[b]]


def gf_inv(a: int) -> int:
    if a == 0:
        raise ZeroDivisionError("Zero has no multiplicative inverse in GF(256)")
    return INV[a]


def scale_bytes(buf: bytes | bytearray, scalar: int) -> bytes:
    """Multiply every byte of `buf` by `scalar` in GF(256) via C-speed translate."""
    if scalar == 0:
        return bytes(len(buf))
    if scalar == 1:
        return bytes(buf)
    return bytes(buf).translate(MUL_BYTES[scalar])


def xor_bytes(a: bytes | bytearray, b: bytes | bytearray) -> bytes:
    """XOR two equal-length byte buffers using C-speed big-int arithmetic."""
    if len(a) != len(b):
        raise ValueError(f"Length mismatch for XOR: {len(a)} vs {len(b)}")
    if not a:
        return b""
    ia = int.from_bytes(a, "little")
    ib = int.from_bytes(b, "little")
    return (ia ^ ib).to_bytes(len(a), "little")


def crc16_ccitt(data: bytes) -> int:
    """Compute CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF)."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc


def encode_lehmer(rank: int, n: int = 6) -> list[int]:
    """Bijectively map integer `rank` in [0, n!) to a permutation of [0..n-1]."""
    limit = math.factorial(n)
    if not (0 <= rank < limit):
        raise ValueError(f"Lehmer rank {rank} out of range [0, {limit})")
    elems = list(range(n))
    perm: list[int] = []
    rem = rank
    for i in range(n, 0, -1):
        fact = math.factorial(i - 1)
        idx = rem // fact
        rem %= fact
        perm.append(elems.pop(idx))
    return perm


def decode_lehmer(perm: list[int]) -> int:
    """Invert a permutation of [0..n-1] back to its Lehmer rank in [0, n!)."""
    n = len(perm)
    elems = list(range(n))
    rank = 0
    for i, val in enumerate(perm):
        idx = elems.index(val)
        elems.pop(idx)
        rank += idx * math.factorial(n - 1 - i)
    return rank


def chaotic_keystream(key: bytes, length: int) -> bytes:
    """Generate a deterministic high-entropy keystream using BLAKE2b in counter mode."""
    if length <= 0:
        return b""
    chunks: list[bytes] = []
    produced = 0
    ctr = 0
    while produced < length:
        digest = hashlib.blake2b(
            key + struct.pack("!Q", ctr), digest_size=64
        ).digest()
        chunks.append(digest)
        produced += len(digest)
        ctr += 1
    return b"".join(chunks)[:length]


def coeff_vector(seed: bytes, droplet_id: int, k: int) -> list[int]:
    """Deterministically generate a non-zero k-element GF(256) coefficient vector."""
    if k <= 0:
        raise ValueError("k must be positive")
    out = bytearray()
    ctr = 0
    while len(out) < k:
        digest = hashlib.blake2s(
            seed + struct.pack("!IB", droplet_id, ctr), digest_size=32
        ).digest()
        out.extend(digest)
        ctr += 1
    vec = list(out[:k])
    if all(c == 0 for c in vec):
        vec[droplet_id % k] = 1
    return vec


class ChaosLaneScheduler:
    """Logistic-map chaotic lane hopper with balanced/stealth/turbo profiles."""

    _PROFILE_WEIGHTS: dict[str, dict[str, int]] = {
        "balanced": {},
        "stealth": {
            "GHOST_127": 4,
            "LAN_LENGTH": 3,
            "TS_V6_CHORD": 3,
            "HYPERV_MCAST": 3,
            "WSL_PERMUTE": 3,
            "TS_V4_1280": 1,
            "ICMP_REFLECT": 1,
        },
        "turbo": {
            "TS_V4_1280": 8,
            "ICMP_REFLECT": 8,
            "GHOST_127": 2,
            "LAN_LENGTH": 1,
            "TS_V6_CHORD": 1,
            "HYPERV_MCAST": 1,
            "WSL_PERMUTE": 1,
        },
    }

    def __init__(
        self, active_lanes: Iterable[str], seed: bytes, profile: str = "balanced"
    ) -> None:
        self._lanes = list(active_lanes)
        if not self._lanes:
            raise ValueError("ChaosLaneScheduler requires at least one active lane")
        if profile not in self._PROFILE_WEIGHTS:
            raise ValueError(f"Unknown chaos profile: {profile}")
        self.profile = profile
        h = int.from_bytes(hashlib.blake2s(seed, digest_size=8).digest(), "big")
        # Map initial state cleanly into (0.11, 0.89), avoiding 0.25/0.5/0.75 points
        self._x = 0.11 + 0.78 * ((h & 0xFFFFFFFFFFFF) / float(1 << 48))
        if abs(self._x - 0.5) < 1e-4 or abs(self._x - 0.75) < 1e-4:
            self._x += 0.0314159
        self._step = 0
        self._seed = seed
        self._seen_in_window: set[str] = set()
        self._ring: list[str] = []
        self._rebuild_ring()

    def _rebuild_ring(self) -> None:
        weights = self._PROFILE_WEIGHTS[self.profile]
        ring: list[str] = []
        for lid in self._lanes:
            ring.extend([lid] * max(1, int(weights.get(lid, 1))))
        self._ring = ring

    @property
    def active_lanes(self) -> list[str]:
        return list(self._lanes)

    def remove_lane(self, lane_id: str) -> None:
        if lane_id in self._lanes and len(self._lanes) > 1:
            self._lanes.remove(lane_id)
            self._seen_in_window.discard(lane_id)
            self._rebuild_ring()

    def _advance_chaos(self) -> float:
        self._step += 1
        self._x = 3.99 * self._x * (1.0 - self._x)
        if self._x <= 1e-5 or self._x >= 1.0 - 1e-5 or abs(self._x - 0.74937343) < 1e-6:
            reseed = hashlib.blake2s(
                self._seed + struct.pack("!Q", self._step), digest_size=8
            ).digest()
            self._x = 0.13 + 0.74 * (int.from_bytes(reseed, "big") / float(1 << 64))
        return self._x

    def next_lane(self, eligible_lanes: Iterable[str] | None = None) -> str:
        """Select the next transport lane via chaotic logistic dynamics and active profile."""
        x = self._advance_chaos()
        if eligible_lanes is None:
            pool = self._ring
            active = self._lanes
        else:
            allowed = set(eligible_lanes)
            active = [lid for lid in self._lanes if lid in allowed]
            if not active:
                active = self._lanes
                pool = self._ring
            else:
                pool = [lid for lid in self._ring if lid in allowed]

        candidate = pool[min(len(pool) - 1, int(x * len(pool)))]

        # In balanced mode, guarantee every active lane participates within every n-step window
        if self.profile == "balanced":
            n = len(active)
            missing = [lid for lid in active if lid not in self._seen_in_window]
            if (
                missing
                and candidate in self._seen_in_window
                and len(self._seen_in_window) >= max(1, n - len(missing))
            ):
                candidate = missing[int(x * len(missing)) % len(missing)]
            self._seen_in_window.add(candidate)
            if len(self._seen_in_window) >= n:
                self._seen_in_window.clear()
        return candidate


class RLNCEncoder:
    """Random Linear Network Coding fountain encoder over GF(256)."""

    def __init__(self, blocks: list[bytes], seed: bytes) -> None:
        if not blocks:
            raise ValueError("RLNCEncoder requires at least one block")
        self.blocks = blocks
        self.k = len(blocks)
        self.block_size = len(blocks[0])
        if any(len(b) != self.block_size for b in blocks):
            raise ValueError("All RLNC source blocks must have identical length")
        self.seed = seed

    def generate_droplet(self, droplet_id: int) -> bytes:
        """Produce droplet wire bytes: [uint16 id][coded_block][uint16 crc16]."""
        coeffs = coeff_vector(self.seed, droplet_id & 0xFFFF, self.k)
        acc = bytearray(self.block_size)
        acc_int = 0
        for c, blk in zip(coeffs, self.blocks):
            if c == 0:
                continue
            scaled = blk if c == 1 else blk.translate(MUL_BYTES[c])
            acc_int ^= int.from_bytes(scaled, "little")
        acc = acc_int.to_bytes(self.block_size, "little")
        body = struct.pack("!H", droplet_id & 0xFFFF) + acc
        crc = crc16_ccitt(self.seed + body)
        return body + struct.pack("!H", crc)


class RLNCDecoder:
    """Incremental GF(256) Gaussian elimination decoder for RLNC droplets."""

    def __init__(self, k: int, block_size: int, seed: bytes) -> None:
        self.k = k
        self.block_size = block_size
        self.seed = seed
        self.pivots: dict[int, tuple[bytearray, bytearray]] = {}
        self.crc_drops = 0
        self.total_valid = 0
        self.redundant = 0

    def is_complete(self) -> bool:
        return len(self.pivots) == self.k

    @property
    def rank(self) -> int:
        return len(self.pivots)

    def add_droplet(self, droplet_bytes: bytes) -> tuple[bool, bool, int]:
        """Verify CRC-16 and incrementally reduce droplet; return (crc_ok, innovative, rank)."""
        expected_len = 2 + self.block_size + 2
        if len(droplet_bytes) != expected_len:
            self.crc_drops += 1
            return False, False, len(self.pivots)

        body = droplet_bytes[:-2]
        recv_crc = struct.unpack("!H", droplet_bytes[-2:])[0]
        if crc16_ccitt(self.seed + body) != recv_crc:
            self.crc_drops += 1
            return False, False, len(self.pivots)

        self.total_valid += 1
        droplet_id = struct.unpack("!H", body[:2])[0]
        row_data = bytearray(body[2:])
        row_coeffs = bytearray(coeff_vector(self.seed, droplet_id, self.k))

        for col in sorted(self.pivots.keys()):
            factor = row_coeffs[col]
            if factor == 0:
                continue
            pc, pd = self.pivots[col]
            if factor == 1:
                c_int = int.from_bytes(row_coeffs, "little") ^ int.from_bytes(pc, "little")
                d_int = int.from_bytes(row_data, "little") ^ int.from_bytes(pd, "little")
            else:
                table = MUL_BYTES[factor]
                c_int = int.from_bytes(row_coeffs, "little") ^ int.from_bytes(
                    bytes(pc).translate(table), "little"
                )
                d_int = int.from_bytes(row_data, "little") ^ int.from_bytes(
                    bytes(pd).translate(table), "little"
                )
            row_coeffs = bytearray(c_int.to_bytes(self.k, "little"))
            row_data = bytearray(d_int.to_bytes(self.block_size, "little"))

        pivot_col = -1
        for col in range(self.k):
            if row_coeffs[col] != 0:
                pivot_col = col
                break

        if pivot_col == -1:
            self.redundant += 1
            return True, False, len(self.pivots)

        inv_pivot = INV[row_coeffs[pivot_col]]
        if inv_pivot != 1:
            table = MUL_BYTES[inv_pivot]
            row_coeffs = bytearray(bytes(row_coeffs).translate(table))
            row_data = bytearray(bytes(row_data).translate(table))

        self.pivots[pivot_col] = (row_coeffs, row_data)
        return True, True, len(self.pivots)

    def solve(self) -> list[bytes]:
        """Back-substitute reduced row-echelon pivots to recover all k blocks."""
        if not self.is_complete():
            raise RuntimeError(
                f"Cannot solve incomplete matrix: rank {len(self.pivots)} < k {self.k}"
            )
        rows = {
            col: (bytearray(c), bytearray(d)) for col, (c, d) in self.pivots.items()
        }
        for col in range(self.k - 1, -1, -1):
            _, pd = rows[col]
            pd_bytes = bytes(pd)
            for above in range(col):
                ac, ad = rows[above]
                factor = ac[col]
                if factor == 0:
                    continue
                scaled = pd_bytes if factor == 1 else pd_bytes.translate(MUL_BYTES[factor])
                d_int = int.from_bytes(ad, "little") ^ int.from_bytes(scaled, "little")
                ad[:] = d_int.to_bytes(self.block_size, "little")
                ac[col] = 0
        return [bytes(rows[i][1]) for i in range(self.k)]


def shannon_entropy(data: bytes) -> float:
    """Compute Shannon entropy in bits per byte (max 8.0)."""
    if not data:
        return 0.0
    counts = [0] * 256
    for b in data:
        counts[b] += 1
    n = float(len(data))
    ent = 0.0
    for c in counts:
        if c:
            p = c / n
            ent -= p * math.log2(p)
    return ent
