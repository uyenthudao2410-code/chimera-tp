/* CHIMERA-DYNAMO / AEON: Zero-Dependency Hardware POPCNT VSA Batch & 10K Encoder
 * 100% bit-exact with Rust native/chimera_core/src/lib.rs & Python fallback.
 * Build on Linux svhome: gcc -O3 -march=native -mpopcnt -shared -fPIC -o chimera_tp/_chimera_vsa.so native/chimera_core/src/vsa_simd.c
 */
#include <stdint.h>
#include <stddef.h>
#include <string.h>

static inline int is_vsa_tok_byte(uint8_t b) {
    if ((b >= 'a' && b <= 'z') || (b >= 'A' && b <= 'Z') || (b >= '0' && b <= '9')) return 1;
    return (b == '_' || b == '/' || b == '.' || b == ':' || b == '-');
}

static inline uint8_t to_ascii_lower(uint8_t b) {
    return (b >= 'A' && b <= 'Z') ? (uint8_t)(b + 32) : b;
}

static inline uint64_t vsa_splitmix64(uint64_t *state) {
    *state += 0x9E3779B97F4A7C15ULL;
    uint64_t z = *state;
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ULL;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBULL;
    return z ^ (z >> 31);
}

int32_t chimera_vsa_hamming_batch(
    const uint8_t *query,
    const uint8_t *matrix,
    size_t rows,
    size_t bytes_per_row,
    uint32_t *out_dist
) {
    if (!query || !matrix || !out_dist || bytes_per_row == 0) return -1;
    if (rows == 0) return 0;
    const size_t q_chunks = bytes_per_row / 8;
    const size_t rem_off = q_chunks * 8;
    const size_t rem_len = bytes_per_row - rem_off;
    for (size_t r = 0; r < rows; r++) {
        const uint8_t *row_ptr = matrix + (r * bytes_per_row);
        uint32_t acc = 0;
        size_t c = 0;
        for (; c + 4 <= q_chunks; c += 4) {
            uint64_t a0, b0, a1, b1, a2, b2, a3, b3;
            size_t off0 = c * 8;
            memcpy(&a0, query + off0, 8);      memcpy(&b0, row_ptr + off0, 8);
            memcpy(&a1, query + off0 + 8, 8);  memcpy(&b1, row_ptr + off0 + 8, 8);
            memcpy(&a2, query + off0 + 16, 8); memcpy(&b2, row_ptr + off0 + 16, 8);
            memcpy(&a3, query + off0 + 24, 8); memcpy(&b3, row_ptr + off0 + 24, 8);
            acc += (uint32_t)__builtin_popcountll(a0 ^ b0)
                 + (uint32_t)__builtin_popcountll(a1 ^ b1)
                 + (uint32_t)__builtin_popcountll(a2 ^ b2)
                 + (uint32_t)__builtin_popcountll(a3 ^ b3);
        }
        for (; c < q_chunks; c++) {
            uint64_t a, b;
            memcpy(&a, query + c * 8, 8);
            memcpy(&b, row_ptr + c * 8, 8);
            acc += (uint32_t)__builtin_popcountll(a ^ b);
        }
        for (size_t i = 0; i < rem_len; i++) {
            uint32_t x = (uint32_t)(query[rem_off + i] ^ row_ptr[rem_off + i]);
            acc += (uint32_t)__builtin_popcount(x);
        }
        out_dist[r] = acc;
    }
    return 0;
}

int32_t chimera_vsa_encode_10k(
    const uint8_t *text,
    size_t text_len,
    uint8_t *out_buf,
    size_t out_bytes
) {
    if (!out_buf || out_bytes == 0 || out_bytes > 2048) return -1;
    const size_t n_bits = out_bytes * 8;
    int16_t acc[16384];
    memset(acc, 0, n_bits * sizeof(int16_t));

    uint64_t tok_hashes[128];
    size_t tok_count = 0;
    size_t i = 0;
    while (text && i < text_len && tok_count < 128) {
        while (i < text_len && !is_vsa_tok_byte(text[i])) i++;
        if (i >= text_len) break;
        uint64_t h = 0xcbf29ce484222325ULL;
        while (i < text_len && is_vsa_tok_byte(text[i])) {
            h ^= (uint64_t)to_ascii_lower(text[i]);
            h *= 0x00000100000001B3ULL;
            i++;
        }
        tok_hashes[tok_count++] = h;
    }
    if (tok_count == 0) {
        const char *emp = "empty";
        uint64_t h = 0xcbf29ce484222325ULL;
        for (size_t k = 0; k < 5; k++) {
            h ^= (uint64_t)(uint8_t)emp[k];
            h *= 0x00000100000001B3ULL;
        }
        tok_hashes[0] = h;
        tok_count = 1;
    }

    const size_t n_u64 = (n_bits + 63) / 64;
    for (size_t t = 0; t < tok_count; t++) {
        uint64_t st = tok_hashes[t];
        for (size_t w = 0; w < n_u64; w++) {
            uint64_t word = vsa_splitmix64(&st);
            size_t base = w * 64;
            size_t lim = n_bits - base;
            if (lim > 64) lim = 64;
            for (size_t bit = 0; bit < lim; bit++) {
                acc[base + bit] += ((word >> bit) & 1ULL) ? 1 : -1;
            }
        }
    }

    for (size_t b = 0; b < out_bytes; b++) {
        size_t base = b * 8;
        uint8_t v = 0;
        for (size_t bit = 0; bit < 8; bit++) {
            if (acc[base + bit] >= 0) v |= (uint8_t)(1u << bit);
        }
        out_buf[b] = v;
    }
    return 0;
}
