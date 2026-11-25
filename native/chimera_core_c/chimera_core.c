/*
 * CHIMERA-HYPER v2.0 Cross-Platform Silicon Core (Linux/POSIX C11 + AVX2 VPSHUFB)
 *
 * Exports the exact 16-function C-ABI as native/chimera_core (Rust/Windows) with:
 * - Bit-identical GF(256) poly 0x11B arithmetic accelerated via AVX2 split-nibble VPSHUFB
 * - Bit-identical FastCDC 64-bit Gear table & masks (cross-host Windows <-> Linux DNA parity!)
 * - Bit-identical Odess 4x64-bit super-features & 16-byte sliding Delta codec
 * - High-speed in-transit Active Byte-Line Filter
 * - Lock-free POSIX Shared Memory Ring Buffer ("Wormhole IPC")
 */

#define _POSIX_C_SOURCE 200809L

#include <errno.h>
#include <fcntl.h>
#include <sched.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

#if defined(__x86_64__) || defined(_M_X64)
#include <immintrin.h>
#endif

static uint8_t MUL_LUT[256][256];
static uint8_t INV_LUT[256];
static uint64_t GEAR_TABLE[256];
static int g_tables_ready = 0;

static inline uint8_t gf_slow_mul(uint8_t a, uint8_t b) {
    uint8_t res = 0;
    for (int i = 0; i < 8; i++) {
        if (b & 1) {
            res ^= a;
        }
        uint8_t hi = a & 0x80;
        a <<= 1;
        if (hi) {
            a ^= 0x1B; /* low 8 bits of 0x11B */
        }
        b >>= 1;
    }
    return res;
}

static inline uint64_t splitmix64(uint64_t x) {
    x += UINT64_C(0x9E3779B97F4A7C15);
    x = (x ^ (x >> 30)) * UINT64_C(0xBF58476D1CE4E5B9);
    x = (x ^ (x >> 27)) * UINT64_C(0x94D049BB133111EB);
    return x ^ (x >> 31);
}

static inline uint64_t rotl64(uint64_t x, unsigned r) {
    return (x << r) | (x >> (64 - r));
}

__attribute__((constructor))
static void chimera_init_tables(void) {
    if (g_tables_ready) {
        return;
    }
    for (int a = 0; a < 256; a++) {
        for (int b = 0; b < 256; b++) {
            MUL_LUT[a][b] = gf_slow_mul((uint8_t)a, (uint8_t)b);
        }
    }
    memset(INV_LUT, 0, sizeof(INV_LUT));
    for (int a = 1; a < 256; a++) {
        for (int b = 1; b < 256; b++) {
            if (gf_slow_mul((uint8_t)a, (uint8_t)b) == 1) {
                INV_LUT[a] = (uint8_t)b;
                break;
            }
        }
    }
    for (int i = 0; i < 256; i++) {
        uint64_t v = splitmix64(((uint64_t)i * UINT64_C(0x517CC1B727220A95)) + UINT64_C(0x243F6A8885A308D3));
        if (v == 0) {
            v = UINT64_C(0x13579BDF2468ACE1);
        }
        GEAR_TABLE[i] = v;
    }
    g_tables_ready = 1;
}

uint32_t chimera_cpu_caps(void) {
    uint32_t caps = 0;
#if (defined(__x86_64__) || defined(_M_X64)) && defined(__GNUC__)
    __builtin_cpu_init();
    if (__builtin_cpu_supports("gfni")) {
        caps |= (1u << 0);
    }
    if (__builtin_cpu_supports("avx2")) {
        caps |= (1u << 1);
    }
    if (__builtin_cpu_supports("avx512f")) {
        caps |= (1u << 2);
    }
#endif
    return caps;
}

#if (defined(__x86_64__) || defined(_M_X64)) && defined(__GNUC__)
__attribute__((target("avx2")))
static void gf256_xor_avx2(uint8_t *dst, const uint8_t *src, size_t len) {
    size_t i = 0;
    while (i + 32 <= len) {
        __m256i d = _mm256_loadu_si256((const __m256i *)(dst + i));
        __m256i s = _mm256_loadu_si256((const __m256i *)(src + i));
        _mm256_storeu_si256((__m256i *)(dst + i), _mm256_xor_si256(d, s));
        i += 32;
    }
    while (i < len) {
        dst[i] ^= src[i];
        i++;
    }
}

__attribute__((target("avx2")))
static void gf256_mul_add_avx2(uint8_t *dst, const uint8_t *src, size_t len, uint8_t coeff) {
    uint8_t lo_arr[16], hi_arr[16];
    const uint8_t *row = MUL_LUT[coeff];
    for (int n = 0; n < 16; n++) {
        lo_arr[n] = row[n];
        hi_arr[n] = row[n << 4];
    }
    __m128i lo128 = _mm_loadu_si128((const __m128i *)lo_arr);
    __m128i hi128 = _mm_loadu_si128((const __m128i *)hi_arr);
    __m256i tbl_lo = _mm256_broadcastsi128_si256(lo128);
    __m256i tbl_hi = _mm256_broadcastsi128_si256(hi128);
    __m256i mask_0f = _mm256_set1_epi8(0x0F);

    size_t i = 0;
    while (i + 32 <= len) {
        __m256i s = _mm256_loadu_si256((const __m256i *)(src + i));
        __m256i d = _mm256_loadu_si256((const __m256i *)(dst + i));
        __m256i lo = _mm256_and_si256(s, mask_0f);
        __m256i hi = _mm256_and_si256(_mm256_srli_epi16(s, 4), mask_0f);
        __m256i p = _mm256_xor_si256(
            _mm256_shuffle_epi8(tbl_lo, lo),
            _mm256_shuffle_epi8(tbl_hi, hi)
        );
        _mm256_storeu_si256((__m256i *)(dst + i), _mm256_xor_si256(d, p));
        i += 32;
    }
    while (i < len) {
        dst[i] ^= row[src[i]];
        i++;
    }
}

__attribute__((target("avx2")))
static void gf256_scale_avx2(uint8_t *dst, const uint8_t *src, size_t len, uint8_t coeff) {
    uint8_t lo_arr[16], hi_arr[16];
    const uint8_t *row = MUL_LUT[coeff];
    for (int n = 0; n < 16; n++) {
        lo_arr[n] = row[n];
        hi_arr[n] = row[n << 4];
    }
    __m128i lo128 = _mm_loadu_si128((const __m128i *)lo_arr);
    __m128i hi128 = _mm_loadu_si128((const __m128i *)hi_arr);
    __m256i tbl_lo = _mm256_broadcastsi128_si256(lo128);
    __m256i tbl_hi = _mm256_broadcastsi128_si256(hi128);
    __m256i mask_0f = _mm256_set1_epi8(0x0F);

    size_t i = 0;
    while (i + 32 <= len) {
        __m256i s = _mm256_loadu_si256((const __m256i *)(src + i));
        __m256i lo = _mm256_and_si256(s, mask_0f);
        __m256i hi = _mm256_and_si256(_mm256_srli_epi16(s, 4), mask_0f);
        __m256i p = _mm256_xor_si256(
            _mm256_shuffle_epi8(tbl_lo, lo),
            _mm256_shuffle_epi8(tbl_hi, hi)
        );
        _mm256_storeu_si256((__m256i *)(dst + i), p);
        i += 32;
    }
    while (i < len) {
        dst[i] = row[src[i]];
        i++;
    }
}
#endif

static inline void gf256_mul_add_impl(uint8_t *dst, const uint8_t *src, size_t len, uint8_t coeff, int has_avx2) {
    if (coeff == 0 || len == 0) {
        return;
    }
    if (coeff == 1) {
#if (defined(__x86_64__) || defined(_M_X64)) && defined(__GNUC__)
        if (has_avx2 && len >= 32) {
            gf256_xor_avx2(dst, src, len);
            return;
        }
#endif
        for (size_t i = 0; i < len; i++) {
            dst[i] ^= src[i];
        }
        return;
    }
#if (defined(__x86_64__) || defined(_M_X64)) && defined(__GNUC__)
    if (has_avx2 && len >= 32) {
        gf256_mul_add_avx2(dst, src, len, coeff);
        return;
    }
#endif
    const uint8_t *row = MUL_LUT[coeff];
    for (size_t i = 0; i < len; i++) {
        dst[i] ^= row[src[i]];
    }
}

static inline void gf256_scale_impl(uint8_t *dst, const uint8_t *src, size_t len, uint8_t coeff, int has_avx2) {
    if (len == 0) {
        return;
    }
    if (coeff == 0) {
        memset(dst, 0, len);
        return;
    }
    if (coeff == 1) {
        if (dst != src) {
            memmove(dst, src, len);
        }
        return;
    }
#if (defined(__x86_64__) || defined(_M_X64)) && defined(__GNUC__)
    if (has_avx2 && len >= 32) {
        gf256_scale_avx2(dst, src, len, coeff);
        return;
    }
#endif
    const uint8_t *row = MUL_LUT[coeff];
    for (size_t i = 0; i < len; i++) {
        dst[i] = row[src[i]];
    }
}

void chimera_gf256_mul_add(uint8_t *dst, const uint8_t *src, size_t len, uint8_t coeff) {
    if (!dst || !src || len == 0 || coeff == 0) {
        return;
    }
    if (!g_tables_ready) chimera_init_tables();
    int has_avx2 = (chimera_cpu_caps() & 2u) != 0;
    gf256_mul_add_impl(dst, src, len, coeff, has_avx2);
}

void chimera_gf256_scale(uint8_t *dst, const uint8_t *src, size_t len, uint8_t coeff) {
    if (!dst || !src || len == 0) {
        return;
    }
    if (!g_tables_ready) chimera_init_tables();
    int has_avx2 = (chimera_cpu_caps() & 2u) != 0;
    gf256_scale_impl(dst, src, len, coeff, has_avx2);
}

void chimera_gf256_encode_block(uint8_t *out, const uint8_t *blocks_flat, const uint8_t *coeffs, size_t k, size_t block_len) {
    if (!out || !blocks_flat || !coeffs || k == 0 || block_len == 0) {
        return;
    }
    if (!g_tables_ready) chimera_init_tables();
    memset(out, 0, block_len);
    int has_avx2 = (chimera_cpu_caps() & 2u) != 0;
    for (size_t r = 0; r < k; r++) {
        uint8_t c = coeffs[r];
        if (c != 0) {
            gf256_mul_add_impl(out, blocks_flat + (r * block_len), block_len, c, has_avx2);
        }
    }
}

int32_t chimera_gf256_decode_matrix(const uint8_t *coded_flat, const uint8_t *coeffs_flat, uint8_t *out_flat, size_t k, size_t block_len) {
    if (!coded_flat || !coeffs_flat || !out_flat || k == 0 || block_len == 0) {
        return -1;
    }
    if (!g_tables_ready) chimera_init_tables();
    int has_avx2 = (chimera_cpu_caps() & 2u) != 0;

    uint8_t *c_mat = (uint8_t *)malloc(k * k);
    uint8_t *swap_tmp = (uint8_t *)malloc(block_len);
    if (!c_mat || !swap_tmp) {
        free(c_mat);
        free(swap_tmp);
        return -1;
    }
    memcpy(c_mat, coeffs_flat, k * k);
    if (coded_flat != out_flat) {
        memcpy(out_flat, coded_flat, k * block_len);
    }

    for (size_t col = 0; col < k; col++) {
        size_t pivot_row = col;
        while (pivot_row < k && c_mat[pivot_row * k + col] == 0) {
            pivot_row++;
        }
        if (pivot_row == k) {
            free(c_mat);
            free(swap_tmp);
            return -1;
        }
        if (pivot_row != col) {
            for (size_t j = col; j < k; j++) {
                uint8_t t = c_mat[col * k + j];
                c_mat[col * k + j] = c_mat[pivot_row * k + j];
                c_mat[pivot_row * k + j] = t;
            }
            memcpy(swap_tmp, out_flat + col * block_len, block_len);
            memcpy(out_flat + col * block_len, out_flat + pivot_row * block_len, block_len);
            memcpy(out_flat + pivot_row * block_len, swap_tmp, block_len);
        }

        uint8_t piv = c_mat[col * k + col];
        if (piv != 1) {
            uint8_t inv = INV_LUT[piv];
            const uint8_t *row_slice = MUL_LUT[inv];
            for (size_t j = col; j < k; j++) {
                c_mat[col * k + j] = row_slice[c_mat[col * k + j]];
            }
            gf256_scale_impl(out_flat + col * block_len, out_flat + col * block_len, block_len, inv, has_avx2);
        }

        for (size_t other = 0; other < k; other++) {
            if (other == col) continue;
            uint8_t factor = c_mat[other * k + col];
            if (factor == 0) continue;
            const uint8_t *mul_row = MUL_LUT[factor];
            for (size_t j = col; j < k; j++) {
                c_mat[other * k + j] ^= mul_row[c_mat[col * k + j]];
            }
            gf256_mul_add_impl(out_flat + other * block_len, out_flat + col * block_len, block_len, factor, has_avx2);
        }
    }

    free(c_mat);
    free(swap_tmp);
    return 0;
}

/* -------------------------------------------------------------------------
 * FastCDC + Odess Super-Features + Delta Codec (exact parity with Rust)
 * ------------------------------------------------------------------------- */

size_t chimera_fastcdc(
    const uint8_t *data,
    size_t len,
    size_t min_sz,
    size_t avg_sz,
    size_t max_sz,
    uint64_t *out_offsets,
    size_t max_chunks
) {
    if (!data || !out_offsets || len == 0 || max_chunks == 0) {
        return 0;
    }
    if (!g_tables_ready) chimera_init_tables();

    size_t min_c = min_sz > 64 ? min_sz : 64;
    size_t max_c = max_sz > min_c ? max_sz : min_c;
    size_t avg_c = avg_sz < min_c ? min_c : (avg_sz > max_c ? max_c : avg_sz);

    unsigned bits = (unsigned)(63 - __builtin_clzll((unsigned long long)avg_c));
    if (bits < 6) bits = 6;
    if (bits > 22) bits = 22;
    uint64_t mask_s = ((UINT64_C(1) << (bits + 1)) - 1) & UINT64_C(0x0FFFFFFF);
    unsigned bits_m1 = bits > 1 ? bits - 1 : 0;
    uint64_t mask_l = ((UINT64_C(1) << bits_m1) - 1) & UINT64_C(0x0FFFFFFF);

    size_t pos = 0;
    size_t chunks = 0;

    while (pos < len && chunks < max_chunks) {
        size_t rem = len - pos;
        if (rem <= min_c || chunks + 1 == max_chunks) {
            pos = len;
            out_offsets[chunks++] = (uint64_t)pos;
            break;
        }
        size_t end_max = (pos + max_c < len) ? (pos + max_c) : len;
        size_t normal_end = (pos + avg_c < end_max) ? (pos + avg_c) : end_max;
        size_t i = pos + (min_c > 64 ? min_c - 64 : 0);
        size_t min_cut = pos + min_c;
        uint64_t h = 0;

        while (i < min_cut) {
            h = (h << 1) + GEAR_TABLE[data[i]];
            i++;
        }

        size_t cut = end_max;
        while (i < normal_end) {
            h = (h << 1) + GEAR_TABLE[data[i]];
            i++;
            if ((h & mask_s) == 0) {
                cut = i;
                break;
            }
        }
        if (cut == end_max) {
            while (i < end_max) {
                h = (h << 1) + GEAR_TABLE[data[i]];
                i++;
                if ((h & mask_l) == 0) {
                    cut = i;
                    break;
                }
            }
        }
        pos = cut;
        out_offsets[chunks++] = (uint64_t)pos;
    }

    return chunks;
}

void chimera_superfeatures(const uint8_t *data, size_t len, uint64_t *out_sf4) {
    if (!data || !out_sf4) {
        return;
    }
    if (!g_tables_ready) chimera_init_tables();
    if (len == 0) {
        for (int i = 0; i < 4; i++) out_sf4[i] = 0;
        return;
    }

    static const uint64_t SALTS[12] = {
        UINT64_C(0x243F6A8885A308D3), UINT64_C(0x13198A2E03707344), UINT64_C(0xA4093822299F31D0),
        UINT64_C(0x082EFA98EC4E6C89), UINT64_C(0x452821E638D01377), UINT64_C(0xBE5466CF34E90C6C),
        UINT64_C(0xC0AC29B7C97C50DD), UINT64_C(0x3F84D5B5B5470917), UINT64_C(0x9216D5D98979FB1B),
        UINT64_C(0xD1310BA698DFB5AC), UINT64_C(0x2FFD72DBD01ADFB7), UINT64_C(0xB8E1AFED6A267E96),
    };
    static const uint64_t MULTS[12] = {
        UINT64_C(0xBF58476D1CE4E5B9), UINT64_C(0x94D049BB133111EB), UINT64_C(0xD6E8FEB86659FD93),
        UINT64_C(0xA0761D6478BD642F), UINT64_C(0xE7037ED1A0B428DB), UINT64_C(0x8EBC6AF09C88C6E3),
        UINT64_C(0x589965CC75374CC3), UINT64_C(0x1D8E4E27C47D124F), UINT64_C(0xEB44ACCAB455D165),
        UINT64_C(0x6199999999999999), UINT64_C(0x9E3779B97F4A7C15), UINT64_C(0xC2B2AE3D27D4EB4F),
    };

    uint64_t sample_mask = (len < 512) ? 0x03 : ((len < 2048) ? 0x0F : 0x1F);
    uint64_t mins[12];
    for (int f = 0; f < 12; f++) mins[f] = UINT64_MAX;
    size_t sampled = 0;
    uint64_t h = 0;

    for (size_t idx = 0; idx < len; idx++) {
        h = (h << 1) + GEAR_TABLE[data[idx]];
        if (idx >= 15 && (h & sample_mask) == 0) {
            sampled++;
            for (int f = 0; f < 12; f++) {
                uint64_t v = (h ^ SALTS[f]) * MULTS[f];
                v ^= (v >> 29);
                if (v < mins[f]) mins[f] = v;
            }
        }
    }

    if (sampled < 3) {
        uint64_t fb_h = 0;
        for (size_t idx = 0; idx < len; idx++) {
            fb_h = (fb_h << 1) + GEAR_TABLE[data[idx]];
            for (int f = 0; f < 12; f++) {
                uint64_t v = (fb_h ^ SALTS[f]) * MULTS[f];
                v ^= (v >> 29);
                if (v < mins[f]) mins[f] = v;
            }
        }
    }

    for (int g = 0; g < 4; g++) {
        uint64_t m0 = mins[g * 3];
        uint64_t m1 = rotl64(mins[g * 3 + 1], 21);
        uint64_t m2 = rotl64(mins[g * 3 + 2], 43);
        uint64_t combined = splitmix64(m0 ^ m1 ^ m2 ^ ((uint64_t)g * UINT64_C(0x9E3779B97F4A7C15)));
        if (combined == 0) combined = 1;
        out_sf4[g] = combined;
    }
}

static inline uint64_t hash16_unaligned(const uint8_t *p) {
    uint64_t a, b;
    memcpy(&a, p, 8);
    memcpy(&b, p + 8, 8);
    uint64_t x = (a * UINT64_C(0x9E3779B97F4A7C15)) ^ (b * UINT64_C(0xBF58476D1CE4E5B9));
    return x ^ (x >> 31);
}

static inline uint32_t read_u32_le(const uint8_t *p) {
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

static inline void write_u32_le(uint8_t *p, uint32_t v) {
    p[0] = (uint8_t)(v & 0xFF);
    p[1] = (uint8_t)((v >> 8) & 0xFF);
    p[2] = (uint8_t)((v >> 16) & 0xFF);
    p[3] = (uint8_t)((v >> 24) & 0xFF);
}

static inline int emit_literal(const uint8_t *src, size_t n, uint8_t *out, size_t cap, size_t *pos) {
    if (n == 0) return 1;
    if (*pos + 5 + n > cap) return 0;
    out[*pos] = 0x02;
    write_u32_le(out + *pos + 1, (uint32_t)n);
    memcpy(out + *pos + 5, src, n);
    *pos += 5 + n;
    return 1;
}

static inline int emit_copy(uint32_t off, uint32_t mlen, uint8_t *out, size_t cap, size_t *pos) {
    if (*pos + 9 > cap) return 0;
    out[*pos] = 0x01;
    write_u32_le(out + *pos + 1, off);
    write_u32_le(out + *pos + 5, mlen);
    *pos += 9;
    return 1;
}

ssize_t chimera_delta_encode(
    const uint8_t *base,
    size_t base_len,
    const uint8_t *target,
    size_t target_len,
    uint8_t *out_buf,
    size_t out_cap
) {
    if (!target || !out_buf) return -1;
    if (target_len == 0) return 0;
    size_t out_pos = 0;

    if (!base || base_len < 16 || target_len < 16) {
        if (!emit_literal(target, target_len, out_buf, out_cap, &out_pos)) return -1;
        return (ssize_t)out_pos;
    }

    size_t table_sz = 1024;
    size_t want = base_len * 2;
    while (table_sz < want && table_sz < 524288) table_sz <<= 1;
    size_t mask = table_sz - 1;
    uint32_t *table = (uint32_t *)malloc(table_sz * sizeof(uint32_t));
    if (!table) return -1;
    memset(table, 0xFF, table_sz * sizeof(uint32_t));

    size_t step = (base_len > 131072) ? 4 : 1;
    for (size_t bpos = 0; bpos + 16 <= base_len; bpos += step) {
        uint64_t h = hash16_unaligned(base + bpos);
        table[(size_t)h & mask] = (uint32_t)bpos;
    }

    size_t lit_start = 0;
    size_t tpos = 0;
    while (tpos + 16 <= target_len) {
        uint64_t h = hash16_unaligned(target + tpos);
        uint32_t cand_u = table[(size_t)h & mask];
        if (cand_u != UINT32_MAX) {
            size_t cand = (size_t)cand_u;
            if (cand + 16 <= base_len && memcmp(base + cand, target + tpos, 16) == 0) {
                size_t m_tpos = tpos;
                while (m_tpos > lit_start && cand > 0 && target[m_tpos - 1] == base[cand - 1]) {
                    m_tpos--;
                    cand--;
                }
                size_t mlen = 16 + (tpos - m_tpos);
                while (cand + mlen + 8 <= base_len && m_tpos + mlen + 8 <= target_len) {
                    uint64_t u0, u1;
                    memcpy(&u0, base + cand + mlen, 8);
                    memcpy(&u1, target + m_tpos + mlen, 8);
                    if (u0 != u1) break;
                    mlen += 8;
                }
                while (cand + mlen < base_len && m_tpos + mlen < target_len && base[cand + mlen] == target[m_tpos + mlen]) {
                    mlen++;
                }

                if (!emit_literal(target + lit_start, m_tpos - lit_start, out_buf, out_cap, &out_pos) ||
                    !emit_copy((uint32_t)cand, (uint32_t)mlen, out_buf, out_cap, &out_pos)) {
                    free(table);
                    return -1;
                }
                tpos = m_tpos + mlen;
                lit_start = tpos;
                continue;
            }
        }
        tpos++;
    }

    if (lit_start < target_len) {
        if (!emit_literal(target + lit_start, target_len - lit_start, out_buf, out_cap, &out_pos)) {
            free(table);
            return -1;
        }
    }

    free(table);
    return (ssize_t)out_pos;
}

ssize_t chimera_delta_decode(
    const uint8_t *base,
    size_t base_len,
    const uint8_t *patch,
    size_t patch_len,
    uint8_t *out_buf,
    size_t out_cap
) {
    if (!patch || !out_buf) return -1;
    size_t ppos = 0;
    size_t opos = 0;
    while (ppos < patch_len) {
        uint8_t op = patch[ppos++];
        if (op == 0x01) {
            if (ppos + 8 > patch_len || !base) return -1;
            size_t boff = (size_t)read_u32_le(patch + ppos);
            size_t mlen = (size_t)read_u32_le(patch + ppos + 4);
            ppos += 8;
            if (boff > base_len || mlen > base_len - boff || mlen > out_cap - opos) return -1;
            memcpy(out_buf + opos, base + boff, mlen);
            opos += mlen;
        } else if (op == 0x02) {
            if (ppos + 4 > patch_len) return -1;
            size_t llen = (size_t)read_u32_le(patch + ppos);
            ppos += 4;
            if (llen > patch_len - ppos || llen > out_cap - opos) return -1;
            memcpy(out_buf + opos, patch + ppos, llen);
            ppos += llen;
            opos += llen;
        } else {
            return -1;
        }
    }
    return (ssize_t)opos;
}

/* -------------------------------------------------------------------------
 * Active Compute-in-Transit: Fast Byte-Line Filter
 * ------------------------------------------------------------------------- */

ssize_t chimera_active_filter_lines(
    const uint8_t *data,
    size_t len,
    const uint8_t *needle,
    size_t needle_len,
    uint8_t *out_buf,
    size_t out_cap,
    uint64_t *out_matched_lines
) {
    if (!out_matched_lines || !out_buf) return -1;
    *out_matched_lines = 0;
    if (!data || len == 0) return 0;

    size_t out_pos = 0;
    size_t line_start = 0;
    uint64_t matched = 0;
    uint8_t first = (needle && needle_len > 0) ? needle[0] : 0;

    for (size_t i = 0; i < len; i++) {
        if (data[i] == '\n' || i + 1 == len) {
            size_t line_end = i + 1;
            size_t line_len = line_end - line_start;
            const uint8_t *line = data + line_start;
            int hit = 0;
            if (!needle || needle_len == 0) {
                hit = 1;
            } else if (line_len >= needle_len) {
                size_t end = line_len - needle_len + 1;
                for (size_t j = 0; j < end; j++) {
                    if (line[j] == first && memcmp(line + j, needle, needle_len) == 0) {
                        hit = 1;
                        break;
                    }
                }
            }
            if (hit) {
                matched++;
                if (out_pos + line_len > out_cap) return -1;
                memcpy(out_buf + out_pos, line, line_len);
                out_pos += line_len;
            }
            line_start = line_end;
        }
    }

    *out_matched_lines = matched;
    return (ssize_t)out_pos;
}

/* -------------------------------------------------------------------------
 * POSIX Lock-Free Shared Memory Ring Buffer ("Wormhole IPC")
 * ------------------------------------------------------------------------- */

#define WORMHOLE_MAGIC "CHWORM01"
#define WORMHOLE_HEADER_SIZE 4096

typedef struct {
    uint8_t magic[8];
    uint64_t capacity;
    _Atomic uint32_t closed;
    uint8_t _pad0[44];
    _Atomic uint64_t write_pos;
    uint8_t _pad1[56];
    _Atomic uint64_t read_pos;
    uint8_t _pad2[56];
} WormholeHeader;

typedef struct {
    uint8_t *view;
    size_t capacity;
    int is_creator;
    char *shm_name;
} WormholeHandle;

static uint64_t now_ms(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000u + (uint64_t)(ts.tv_nsec / 1000000u);
}

static size_t next_pow2(size_t v) {
    size_t p = 4096;
    while (p < v) p <<= 1;
    return p;
}

void *chimera_wormhole_create(const char *name, size_t capacity) {
    if (!name || !name[0]) return NULL;
    size_t cap = next_pow2(capacity < 4096 ? 4096 : capacity);
    size_t total = WORMHOLE_HEADER_SIZE + cap;

    shm_unlink(name);
    int fd = shm_open(name, O_CREAT | O_EXCL | O_RDWR, 0600);
    if (fd < 0) fd = shm_open(name, O_CREAT | O_RDWR, 0600);
    if (fd < 0) return NULL;
    if (ftruncate(fd, (off_t)total) != 0) {
        close(fd);
        shm_unlink(name);
        return NULL;
    }
    uint8_t *view = (uint8_t *)mmap(NULL, total, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    close(fd);
    if (view == MAP_FAILED) {
        shm_unlink(name);
        return NULL;
    }

    memset(view, 0, total);
    WormholeHeader *hdr = (WormholeHeader *)view;
    memcpy(hdr->magic, WORMHOLE_MAGIC, 8);
    hdr->capacity = (uint64_t)cap;
    atomic_store_explicit(&hdr->closed, 0, memory_order_release);
    atomic_store_explicit(&hdr->write_pos, 0, memory_order_release);
    atomic_store_explicit(&hdr->read_pos, 0, memory_order_release);

    WormholeHandle *h = (WormholeHandle *)calloc(1, sizeof(WormholeHandle));
    if (!h) {
        munmap(view, total);
        shm_unlink(name);
        return NULL;
    }
    h->view = view;
    h->capacity = cap;
    h->is_creator = 1;
    h->shm_name = strdup(name);
    return h;
}

void *chimera_wormhole_open(const char *name) {
    if (!name || !name[0]) return NULL;
    int fd = shm_open(name, O_RDWR, 0600);
    if (fd < 0) return NULL;

    uint8_t *hdr_view = (uint8_t *)mmap(NULL, WORMHOLE_HEADER_SIZE, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    if (hdr_view == MAP_FAILED) {
        close(fd);
        return NULL;
    }
    WormholeHeader *hdr = (WormholeHeader *)hdr_view;
    uint64_t cap64 = hdr->capacity;
    int valid = (memcmp(hdr->magic, WORMHOLE_MAGIC, 8) == 0) && cap64 >= 4096 && ((cap64 & (cap64 - 1)) == 0);
    munmap(hdr_view, WORMHOLE_HEADER_SIZE);
    if (!valid) {
        close(fd);
        return NULL;
    }
    size_t cap = (size_t)cap64;
    uint8_t *full_view = (uint8_t *)mmap(NULL, WORMHOLE_HEADER_SIZE + cap, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    close(fd);
    if (full_view == MAP_FAILED) return NULL;

    WormholeHandle *h = (WormholeHandle *)calloc(1, sizeof(WormholeHandle));
    if (!h) {
        munmap(full_view, WORMHOLE_HEADER_SIZE + cap);
        return NULL;
    }
    h->view = full_view;
    h->capacity = cap;
    h->is_creator = 0;
    return h;
}

ssize_t chimera_wormhole_write(void *hp, const uint8_t *data, size_t len, uint32_t timeout_ms) {
    if (!hp || !data) return -1;
    if (len == 0) return 0;
    WormholeHandle *wh = (WormholeHandle *)hp;
    WormholeHeader *hdr = (WormholeHeader *)wh->view;
    uint8_t *ring = wh->view + WORMHOLE_HEADER_SIZE;
    size_t cap = wh->capacity;
    size_t mask = cap - 1;

    size_t written = 0;
    uint64_t start = now_ms();
    uint32_t spins = 0;

    while (written < len) {
        if (atomic_load_explicit(&hdr->closed, memory_order_acquire) >= 2) {
            return written > 0 ? (ssize_t)written : -1;
        }
        uint64_t w = atomic_load_explicit(&hdr->write_pos, memory_order_relaxed);
        uint64_t r = atomic_load_explicit(&hdr->read_pos, memory_order_acquire);
        size_t used = (size_t)(w - r);
        size_t free_sp = cap > used ? (cap - used) : 0;

        if (free_sp > 0) {
            size_t chunk = free_sp < (len - written) ? free_sp : (len - written);
            size_t idx = (size_t)w & mask;
            size_t first = chunk < (cap - idx) ? chunk : (cap - idx);
            memcpy(ring + idx, data + written, first);
            if (chunk > first) {
                memcpy(ring, data + written + first, chunk - first);
            }
            atomic_store_explicit(&hdr->write_pos, w + chunk, memory_order_release);
            written += chunk;
            spins = 0;
        } else {
            if (timeout_ms == 0 || (now_ms() - start) >= timeout_ms) {
                return written > 0 ? (ssize_t)written : -2;
            }
            if (spins < 4096) {
                spins++;
#if defined(__x86_64__) || defined(_M_X64)
                __builtin_ia32_pause();
#endif
            } else if (spins < 32768) {
                spins++;
                sched_yield();
            } else {
                struct timespec ts = {0, 1000000};
                nanosleep(&ts, NULL);
            }
        }
    }
    return (ssize_t)written;
}

ssize_t chimera_wormhole_read(void *hp, uint8_t *out, size_t max_len, uint32_t timeout_ms) {
    if (!hp || !out) return -1;
    if (max_len == 0) return 0;
    WormholeHandle *wh = (WormholeHandle *)hp;
    WormholeHeader *hdr = (WormholeHeader *)wh->view;
    const uint8_t *ring = wh->view + WORMHOLE_HEADER_SIZE;
    size_t cap = wh->capacity;
    size_t mask = cap - 1;

    uint64_t start = now_ms();
    uint32_t spins = 0;

    for (;;) {
        uint64_t r = atomic_load_explicit(&hdr->read_pos, memory_order_relaxed);
        uint64_t w = atomic_load_explicit(&hdr->write_pos, memory_order_acquire);
        size_t avail = (size_t)(w - r);

        if (avail > 0) {
            size_t chunk = avail < max_len ? avail : max_len;
            size_t idx = (size_t)r & mask;
            size_t first = chunk < (cap - idx) ? chunk : (cap - idx);
            memcpy(out, ring + idx, first);
            if (chunk > first) {
                memcpy(out + first, ring, chunk - first);
            }
            atomic_store_explicit(&hdr->read_pos, r + chunk, memory_order_release);
            return (ssize_t)chunk;
        }

        uint32_t closed = atomic_load_explicit(&hdr->closed, memory_order_acquire);
        if (closed != 0) {
            uint64_t w2 = atomic_load_explicit(&hdr->write_pos, memory_order_acquire);
            if (w2 - r == 0) {
                return 0;
            }
            continue;
        }

        if (timeout_ms == 0 || (now_ms() - start) >= timeout_ms) {
            return -2;
        }
        if (spins < 4096) {
            spins++;
#if defined(__x86_64__) || defined(_M_X64)
            __builtin_ia32_pause();
#endif
        } else if (spins < 32768) {
            spins++;
            sched_yield();
        } else {
            struct timespec ts = {0, 1000000};
            nanosleep(&ts, NULL);
        }
    }
}

void chimera_wormhole_mark_eof(void *hp) {
    if (!hp) return;
    WormholeHandle *wh = (WormholeHandle *)hp;
    WormholeHeader *hdr = (WormholeHeader *)wh->view;
    atomic_store_explicit(&hdr->closed, 1, memory_order_release);
}

void chimera_wormhole_close(void *hp) {
    if (!hp) return;
    WormholeHandle *wh = (WormholeHandle *)hp;
    if (wh->view) {
        munmap(wh->view, WORMHOLE_HEADER_SIZE + wh->capacity);
    }
    if (wh->is_creator && wh->shm_name) {
        shm_unlink(wh->shm_name);
        free(wh->shm_name);
    }
    free(wh);
}
