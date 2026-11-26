//! CHIMERA-HYPER v1.0 Silicon-Native Core
//!
//! Zero-dependency native library providing:
//! - Hardware Intel GFNI (`_mm256_gf2p8mul_epi8`) & AVX2 accelerated GF(256) (poly 0x11B)
//! - In-Rust full Gauss-Jordan matrix solver for zero-copy RLNC FEC recovery
//! - FastCDC content-defined chunking via 64-bit Gear rolling hash
//! - Odess-style grouped 4x64-bit super-features for O(1) sibling detection
//! - Greedy sliding-hash delta encoder / decoder
//! - High-speed in-transit byte-line active filter
//! - Lock-free Windows Shared Memory Ring Buffer ("Wormhole IPC")

#![allow(clippy::missing_safety_doc)]

use std::ffi::c_void;
use std::ptr;
use std::sync::atomic::{AtomicU32, AtomicU64, Ordering};
use std::time::{Duration, Instant};

#[cfg(target_arch = "x86_64")]
use std::arch::x86_64::*;

const GF_POLY: u16 = 0x11B;

const fn gf_slow_mul(mut a: u8, mut b: u8) -> u8 {
    let mut res: u8 = 0;
    let mut i = 0;
    while i < 8 {
        if (b & 1) != 0 {
            res ^= a;
        }
        let hi = a & 0x80;
        a <<= 1;
        if hi != 0 {
            a ^= (GF_POLY & 0xFF) as u8;
        }
        b >>= 1;
        i += 1;
    }
    res
}

const fn build_mul_lut() -> [[u8; 256]; 256] {
    let mut lut = [[0u8; 256]; 256];
    let mut a = 0usize;
    while a < 256 {
        let mut b = 0usize;
        while b < 256 {
            lut[a][b] = gf_slow_mul(a as u8, b as u8);
            b += 1;
        }
        a += 1;
    }
    lut
}

const fn build_inv_lut() -> [u8; 256] {
    let mut inv = [0u8; 256];
    let mut a = 1usize;
    while a < 256 {
        let mut b = 1usize;
        while b < 256 {
            if gf_slow_mul(a as u8, b as u8) == 1 {
                inv[a] = b as u8;
                break;
            }
            b += 1;
        }
        a += 1;
    }
    inv
}

const fn splitmix64(mut x: u64) -> u64 {
    x = x.wrapping_add(0x9E37_79B9_7F4A_7C15);
    x = (x ^ (x >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
    x = (x ^ (x >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
    x ^ (x >> 31)
}

const fn build_gear_table() -> [u64; 256] {
    let mut table = [0u64; 256];
    let mut i = 0usize;
    while i < 256 {
        let mut v = splitmix64((i as u64).wrapping_mul(0x517C_C1B7_2722_0A95).wrapping_add(0x243F_6A88_85A3_08D3));
        if v == 0 {
            v = 0x1357_9BDF_2468_ACE1;
        }
        table[i] = v;
        i += 1;
    }
    table
}

static MUL_LUT: [[u8; 256]; 256] = build_mul_lut();
static INV_LUT: [u8; 256] = build_inv_lut();
static GEAR_TABLE: [u64; 256] = build_gear_table();

// ---------------------------------------------------------------------------
// CPU capabilities
// ---------------------------------------------------------------------------

#[no_mangle]
pub extern "C" fn chimera_cpu_caps() -> u32 {
    let mut caps = 0u32;
    #[cfg(target_arch = "x86_64")]
    {
        if std::arch::is_x86_feature_detected!("gfni") {
            caps |= 1 << 0;
        }
        if std::arch::is_x86_feature_detected!("avx2") {
            caps |= 1 << 1;
        }
        if std::arch::is_x86_feature_detected!("avx512f") {
            caps |= 1 << 2;
        }
    }
    caps
}

// ---------------------------------------------------------------------------
// GF(256) SIMD primitives (Intel GFNI VGF2P8MULB + AVX2 + LUT fallback)
// ---------------------------------------------------------------------------

#[cfg(target_arch = "x86_64")]
#[target_feature(enable = "avx2")]
unsafe fn gf256_xor_avx2(dst: *mut u8, src: *const u8, len: usize) {
    let mut i = 0usize;
    while i + 128 <= len {
        let d0 = _mm256_loadu_si256(dst.add(i) as *const __m256i);
        let s0 = _mm256_loadu_si256(src.add(i) as *const __m256i);
        _mm256_storeu_si256(dst.add(i) as *mut __m256i, _mm256_xor_si256(d0, s0));

        let d1 = _mm256_loadu_si256(dst.add(i + 32) as *const __m256i);
        let s1 = _mm256_loadu_si256(src.add(i + 32) as *const __m256i);
        _mm256_storeu_si256(dst.add(i + 32) as *mut __m256i, _mm256_xor_si256(d1, s1));

        let d2 = _mm256_loadu_si256(dst.add(i + 64) as *const __m256i);
        let s2 = _mm256_loadu_si256(src.add(i + 64) as *const __m256i);
        _mm256_storeu_si256(dst.add(i + 64) as *mut __m256i, _mm256_xor_si256(d2, s2));

        let d3 = _mm256_loadu_si256(dst.add(i + 96) as *const __m256i);
        let s3 = _mm256_loadu_si256(src.add(i + 96) as *const __m256i);
        _mm256_storeu_si256(dst.add(i + 96) as *mut __m256i, _mm256_xor_si256(d3, s3));

        i += 128;
    }
    while i + 32 <= len {
        let d0 = _mm256_loadu_si256(dst.add(i) as *const __m256i);
        let s0 = _mm256_loadu_si256(src.add(i) as *const __m256i);
        _mm256_storeu_si256(dst.add(i) as *mut __m256i, _mm256_xor_si256(d0, s0));
        i += 32;
    }
    while i < len {
        *dst.add(i) ^= *src.add(i);
        i += 1;
    }
}

#[cfg(target_arch = "x86_64")]
#[target_feature(enable = "gfni,avx2")]
unsafe fn gf256_mul_add_gfni(dst: *mut u8, src: *const u8, len: usize, coeff: u8) {
    let cvec = _mm256_set1_epi8(coeff as i8);
    let mut i = 0usize;
    while i + 128 <= len {
        let s0 = _mm256_loadu_si256(src.add(i) as *const __m256i);
        let d0 = _mm256_loadu_si256(dst.add(i) as *const __m256i);
        let p0 = _mm256_gf2p8mul_epi8(s0, cvec);
        _mm256_storeu_si256(dst.add(i) as *mut __m256i, _mm256_xor_si256(d0, p0));

        let s1 = _mm256_loadu_si256(src.add(i + 32) as *const __m256i);
        let d1 = _mm256_loadu_si256(dst.add(i + 32) as *const __m256i);
        let p1 = _mm256_gf2p8mul_epi8(s1, cvec);
        _mm256_storeu_si256(dst.add(i + 32) as *mut __m256i, _mm256_xor_si256(d1, p1));

        let s2 = _mm256_loadu_si256(src.add(i + 64) as *const __m256i);
        let d2 = _mm256_loadu_si256(dst.add(i + 64) as *const __m256i);
        let p2 = _mm256_gf2p8mul_epi8(s2, cvec);
        _mm256_storeu_si256(dst.add(i + 64) as *mut __m256i, _mm256_xor_si256(d2, p2));

        let s3 = _mm256_loadu_si256(src.add(i + 96) as *const __m256i);
        let d3 = _mm256_loadu_si256(dst.add(i + 96) as *const __m256i);
        let p3 = _mm256_gf2p8mul_epi8(s3, cvec);
        _mm256_storeu_si256(dst.add(i + 96) as *mut __m256i, _mm256_xor_si256(d3, p3));

        i += 128;
    }
    while i + 32 <= len {
        let s0 = _mm256_loadu_si256(src.add(i) as *const __m256i);
        let d0 = _mm256_loadu_si256(dst.add(i) as *const __m256i);
        let p0 = _mm256_gf2p8mul_epi8(s0, cvec);
        _mm256_storeu_si256(dst.add(i) as *mut __m256i, _mm256_xor_si256(d0, p0));
        i += 32;
    }
    let row = &MUL_LUT[coeff as usize];
    while i < len {
        *dst.add(i) ^= row[*src.add(i) as usize];
        i += 1;
    }
}

#[cfg(target_arch = "x86_64")]
#[target_feature(enable = "gfni,avx2")]
unsafe fn gf256_scale_gfni(dst: *mut u8, src: *const u8, len: usize, coeff: u8) {
    let cvec = _mm256_set1_epi8(coeff as i8);
    let mut i = 0usize;
    while i + 128 <= len {
        let s0 = _mm256_loadu_si256(src.add(i) as *const __m256i);
        let s1 = _mm256_loadu_si256(src.add(i + 32) as *const __m256i);
        let s2 = _mm256_loadu_si256(src.add(i + 64) as *const __m256i);
        let s3 = _mm256_loadu_si256(src.add(i + 96) as *const __m256i);
        _mm256_storeu_si256(dst.add(i) as *mut __m256i, _mm256_gf2p8mul_epi8(s0, cvec));
        _mm256_storeu_si256(dst.add(i + 32) as *mut __m256i, _mm256_gf2p8mul_epi8(s1, cvec));
        _mm256_storeu_si256(dst.add(i + 64) as *mut __m256i, _mm256_gf2p8mul_epi8(s2, cvec));
        _mm256_storeu_si256(dst.add(i + 96) as *mut __m256i, _mm256_gf2p8mul_epi8(s3, cvec));
        i += 128;
    }
    while i + 32 <= len {
        let s0 = _mm256_loadu_si256(src.add(i) as *const __m256i);
        _mm256_storeu_si256(dst.add(i) as *mut __m256i, _mm256_gf2p8mul_epi8(s0, cvec));
        i += 32;
    }
    let row = &MUL_LUT[coeff as usize];
    while i < len {
        *dst.add(i) = row[*src.add(i) as usize];
        i += 1;
    }
}

#[inline]
unsafe fn gf256_mul_add_impl(dst: *mut u8, src: *const u8, len: usize, coeff: u8, has_gfni: bool, has_avx2: bool) {
    if coeff == 0 || len == 0 {
        return;
    }
    if coeff == 1 {
        #[cfg(target_arch = "x86_64")]
        if has_avx2 && len >= 32 {
            gf256_xor_avx2(dst, src, len);
            return;
        }
        let mut i = 0usize;
        while i < len {
            *dst.add(i) ^= *src.add(i);
            i += 1;
        }
        return;
    }
    #[cfg(target_arch = "x86_64")]
    if has_gfni && has_avx2 && len >= 32 {
        gf256_mul_add_gfni(dst, src, len, coeff);
        return;
    }
    let row = &MUL_LUT[coeff as usize];
    let mut i = 0usize;
    while i < len {
        *dst.add(i) ^= row[*src.add(i) as usize];
        i += 1;
    }
}

#[inline]
unsafe fn gf256_scale_impl(dst: *mut u8, src: *const u8, len: usize, coeff: u8, has_gfni: bool, has_avx2: bool) {
    if len == 0 {
        return;
    }
    if coeff == 0 {
        ptr::write_bytes(dst, 0, len);
        return;
    }
    if coeff == 1 {
        if (dst as *const u8) != src {
            ptr::copy(src, dst, len);
        }
        return;
    }
    #[cfg(target_arch = "x86_64")]
    if has_gfni && has_avx2 && len >= 32 {
        gf256_scale_gfni(dst, src, len, coeff);
        return;
    }
    let row = &MUL_LUT[coeff as usize];
    let mut i = 0usize;
    while i < len {
        *dst.add(i) = row[*src.add(i) as usize];
        i += 1;
    }
}

#[no_mangle]
pub unsafe extern "C" fn chimera_gf256_mul_add(
    dst: *mut u8,
    src: *const u8,
    len: usize,
    coeff: u8,
) {
    if dst.is_null() || src.is_null() || len == 0 || coeff == 0 {
        return;
    }
    let caps = chimera_cpu_caps();
    gf256_mul_add_impl(dst, src, len, coeff, (caps & 1) != 0, (caps & 2) != 0);
}

#[no_mangle]
pub unsafe extern "C" fn chimera_gf256_scale(
    dst: *mut u8,
    src: *const u8,
    len: usize,
    coeff: u8,
) {
    if dst.is_null() || src.is_null() || len == 0 {
        return;
    }
    let caps = chimera_cpu_caps();
    gf256_scale_impl(dst, src, len, coeff, (caps & 1) != 0, (caps & 2) != 0);
}

#[no_mangle]
pub unsafe extern "C" fn chimera_gf256_encode_block(
    out: *mut u8,
    blocks_flat: *const u8,
    coeffs: *const u8,
    k: usize,
    block_len: usize,
) {
    if out.is_null() || blocks_flat.is_null() || coeffs.is_null() || k == 0 || block_len == 0 {
        return;
    }
    ptr::write_bytes(out, 0, block_len);
    let caps = chimera_cpu_caps();
    let has_gfni = (caps & 1) != 0;
    let has_avx2 = (caps & 2) != 0;
    for r in 0..k {
        let c = *coeffs.add(r);
        if c != 0 {
            gf256_mul_add_impl(out, blocks_flat.add(r * block_len), block_len, c, has_gfni, has_avx2);
        }
    }
}

#[no_mangle]
pub unsafe extern "C" fn chimera_gf256_decode_matrix(
    coded_flat: *const u8,
    coeffs_flat: *const u8,
    out_flat: *mut u8,
    k: usize,
    block_len: usize,
) -> i32 {
    if coded_flat.is_null() || coeffs_flat.is_null() || out_flat.is_null() || k == 0 || block_len == 0 {
        return -1;
    }
    let caps = chimera_cpu_caps();
    let has_gfni = (caps & 1) != 0;
    let has_avx2 = (caps & 2) != 0;

    let mut c_mat = vec![0u8; k * k];
    ptr::copy_nonoverlapping(coeffs_flat, c_mat.as_mut_ptr(), k * k);
    if coded_flat as *const u8 != out_flat as *const u8 {
        ptr::copy_nonoverlapping(coded_flat, out_flat, k * block_len);
    }

    for col in 0..k {
        let mut pivot_row = col;
        while pivot_row < k && c_mat[pivot_row * k + col] == 0 {
            pivot_row += 1;
        }
        if pivot_row == k {
            return -1;
        }
        if pivot_row != col {
            for j in col..k {
                c_mat.swap(col * k + j, pivot_row * k + j);
            }
            ptr::swap_nonoverlapping(
                out_flat.add(col * block_len),
                out_flat.add(pivot_row * block_len),
                block_len,
            );
        }

        let piv = c_mat[col * k + col];
        if piv != 1 {
            let inv = INV_LUT[piv as usize];
            let row_slice = &MUL_LUT[inv as usize];
            for j in col..k {
                c_mat[col * k + j] = row_slice[c_mat[col * k + j] as usize];
            }
            gf256_scale_impl(
                out_flat.add(col * block_len),
                out_flat.add(col * block_len),
                block_len,
                inv,
                has_gfni,
                has_avx2,
            );
        }

        for other in 0..k {
            if other == col {
                continue;
            }
            let factor = c_mat[other * k + col];
            if factor == 0 {
                continue;
            }
            let mul_row = &MUL_LUT[factor as usize];
            for j in col..k {
                c_mat[other * k + j] ^= mul_row[c_mat[col * k + j] as usize];
            }
            gf256_mul_add_impl(
                out_flat.add(other * block_len),
                out_flat.add(col * block_len),
                block_len,
                factor,
                has_gfni,
                has_avx2,
            );
        }
    }
    0
}

// ---------------------------------------------------------------------------
// FastCDC + Odess Super-Features + Delta Codec
// ---------------------------------------------------------------------------

#[no_mangle]
pub unsafe extern "C" fn chimera_fastcdc(
    data: *const u8,
    len: usize,
    min_sz: usize,
    avg_sz: usize,
    max_sz: usize,
    out_offsets: *mut u64,
    max_chunks: usize,
) -> usize {
    if data.is_null() || out_offsets.is_null() || len == 0 || max_chunks == 0 {
        return 0;
    }
    let slice = std::slice::from_raw_parts(data, len);
    let min_c = min_sz.max(64);
    let max_c = max_sz.max(min_c);
    let avg_c = avg_sz.clamp(min_c, max_c);

    let bits = avg_c.ilog2().clamp(6, 22);
    // Stricter mask (more 1-bits) before avg_c, looser mask after avg_c (normalized chunking)
    let mask_s: u64 = ((1u64 << (bits + 1)) - 1) & 0x0FFF_FFFF;
    let mask_l: u64 = ((1u64 << bits.saturating_sub(1)) - 1) & 0x0FFF_FFFF;

    let mut pos = 0usize;
    let mut chunks = 0usize;

    while pos < len && chunks < max_chunks {
        let rem = len - pos;
        if rem <= min_c || chunks + 1 == max_chunks {
            pos = len;
            *out_offsets.add(chunks) = pos as u64;
            chunks += 1;
            break;
        }
        let end_max = (pos + max_c).min(len);
        let normal_end = (pos + avg_c).min(end_max);
        let mut i = pos + min_c.saturating_sub(64);
        let min_cut = pos + min_c;
        let mut h = 0u64;

        while i < min_cut {
            h = (h << 1).wrapping_add(GEAR_TABLE[slice[i] as usize]);
            i += 1;
        }

        let mut cut = end_max;
        while i < normal_end {
            h = (h << 1).wrapping_add(GEAR_TABLE[slice[i] as usize]);
            i += 1;
            if (h & mask_s) == 0 {
                cut = i;
                break;
            }
        }
        if cut == end_max {
            while i < end_max {
                h = (h << 1).wrapping_add(GEAR_TABLE[slice[i] as usize]);
                i += 1;
                if (h & mask_l) == 0 {
                    cut = i;
                    break;
                }
            }
        }

        pos = cut;
        *out_offsets.add(chunks) = pos as u64;
        chunks += 1;
    }

    chunks
}

#[no_mangle]
pub unsafe extern "C" fn chimera_superfeatures(
    data: *const u8,
    len: usize,
    out_sf4: *mut u64,
) {
    if data.is_null() || out_sf4.is_null() {
        return;
    }
    if len == 0 {
        for i in 0..4 {
            *out_sf4.add(i) = 0;
        }
        return;
    }
    let slice = std::slice::from_raw_parts(data, len);

    const SALTS: [u64; 12] = [
        0x243F_6A88_85A3_08D3,
        0x1319_8A2E_0370_7344,
        0xA409_3822_299F_31D0,
        0x082E_FA98_EC4E_6C89,
        0x4528_21E6_38D0_1377,
        0xBE54_66CF_34E9_0C6C,
        0xC0AC_29B7_C97C_50DD,
        0x3F84_D5B5_B547_0917,
        0x9216_D5D9_8979_FB1B,
        0xD131_0BA6_98DF_B5AC,
        0x2FFD_72DB_D01A_DFB7,
        0xB8E1_AFED_6A26_7E96,
    ];
    const MULTS: [u64; 12] = [
        0xBF58_476D_1CE4_E5B9,
        0x94D0_49BB_1331_11EB,
        0xD6E8_FEB8_6659_FD93,
        0xA076_1D64_78BD_642F,
        0xE703_7ED1_A0B4_28DB,
        0x8EBC_6AF0_9C88_C6E3,
        0x5899_65CC_7537_4CC3,
        0x1D8E_4E27_C47D_124F,
        0xEB44_ACCA_B455_D165,
        0x6199_9999_9999_9999,
        0x9E37_79B9_7F4A_7C15,
        0xC2B2_AE3D_27D4_EB4F,
    ];

    let sample_mask: u64 = if len < 512 {
        0x03
    } else if len < 2048 {
        0x0F
    } else {
        0x1F
    };

    let mut mins = [u64::MAX; 12];
    let mut sampled = 0usize;
    let mut h = 0u64;

    for (idx, &b) in slice.iter().enumerate() {
        h = (h << 1).wrapping_add(GEAR_TABLE[b as usize]);
        if idx >= 15 && (h & sample_mask) == 0 {
            sampled += 1;
            for f in 0..12 {
                let v = (h ^ SALTS[f]).wrapping_mul(MULTS[f]);
                let v = v ^ (v >> 29);
                if v < mins[f] {
                    mins[f] = v;
                }
            }
        }
    }

    if sampled < 3 {
        let mut fallback_h = 0u64;
        for &b in slice {
            fallback_h = (fallback_h << 1).wrapping_add(GEAR_TABLE[b as usize]);
            for f in 0..12 {
                let v = (fallback_h ^ SALTS[f]).wrapping_mul(MULTS[f]);
                let v = v ^ (v >> 29);
                if v < mins[f] {
                    mins[f] = v;
                }
            }
        }
    }

    for g in 0..4 {
        let m0 = mins[g * 3];
        let m1 = mins[g * 3 + 1].rotate_left(21);
        let m2 = mins[g * 3 + 2].rotate_left(43);
        let mut combined = splitmix64(m0 ^ m1 ^ m2 ^ (g as u64).wrapping_mul(0x9E37_79B9_7F4A_7C15));
        if combined == 0 {
            combined = 1;
        }
        *out_sf4.add(g) = combined;
    }
}

#[inline]
unsafe fn hash16_unaligned(p: *const u8) -> u64 {
    let a = ptr::read_unaligned(p as *const u64);
    let b = ptr::read_unaligned(p.add(8) as *const u64);
    let x = a.wrapping_mul(0x9E37_79B9_7F4A_7C15) ^ b.wrapping_mul(0xBF58_476D_1CE4_E5B9);
    x ^ (x >> 31)
}

#[inline]
unsafe fn eq16_unaligned(a: *const u8, b: *const u8) -> bool {
    let a0 = ptr::read_unaligned(a as *const u64);
    let b0 = ptr::read_unaligned(b as *const u64);
    if a0 != b0 {
        return false;
    }
    let a1 = ptr::read_unaligned(a.add(8) as *const u64);
    let b1 = ptr::read_unaligned(b.add(8) as *const u64);
    a1 == b1
}

#[inline]
fn emit_literal(
    src: &[u8],
    out_buf: *mut u8,
    out_cap: usize,
    out_pos: &mut usize,
) -> bool {
    if src.is_empty() {
        return true;
    }
    let need = 5 + src.len();
    if *out_pos + need > out_cap {
        return false;
    }
    unsafe {
        *out_buf.add(*out_pos) = 0x02;
        ptr::copy_nonoverlapping((src.len() as u32).to_le_bytes().as_ptr(), out_buf.add(*out_pos + 1), 4);
        ptr::copy_nonoverlapping(src.as_ptr(), out_buf.add(*out_pos + 5), src.len());
    }
    *out_pos += need;
    true
}

#[inline]
fn emit_copy(
    base_off: u32,
    match_len: u32,
    out_buf: *mut u8,
    out_cap: usize,
    out_pos: &mut usize,
) -> bool {
    let need = 9usize;
    if *out_pos + need > out_cap {
        return false;
    }
    unsafe {
        *out_buf.add(*out_pos) = 0x01;
        ptr::copy_nonoverlapping(base_off.to_le_bytes().as_ptr(), out_buf.add(*out_pos + 1), 4);
        ptr::copy_nonoverlapping(match_len.to_le_bytes().as_ptr(), out_buf.add(*out_pos + 5), 4);
    }
    *out_pos += need;
    true
}

#[no_mangle]
pub unsafe extern "C" fn chimera_delta_encode(
    base: *const u8,
    base_len: usize,
    target: *const u8,
    target_len: usize,
    out_buf: *mut u8,
    out_cap: usize,
) -> isize {
    if target.is_null() || out_buf.is_null() {
        return -1;
    }
    if target_len == 0 {
        return 0;
    }
    let tgt_slice = std::slice::from_raw_parts(target, target_len);
    let mut out_pos = 0usize;

    if base.is_null() || base_len < 16 || target_len < 16 {
        if !emit_literal(tgt_slice, out_buf, out_cap, &mut out_pos) {
            return -1;
        }
        return out_pos as isize;
    }
    let base_slice = std::slice::from_raw_parts(base, base_len);

    let table_sz = (base_len.saturating_mul(2)).next_power_of_two().clamp(1024, 524_288);
    let mask = table_sz - 1;
    let mut table = vec![u32::MAX; table_sz];

    let index_step = if base_len > 131_072 { 4 } else { 1 };
    let mut bpos = 0usize;
    while bpos + 16 <= base_len {
        let h = hash16_unaligned(base.add(bpos));
        table[(h as usize) & mask] = bpos as u32;
        bpos += index_step;
    }

    let mut lit_start = 0usize;
    let mut tpos = 0usize;

    while tpos + 16 <= target_len {
        let h = hash16_unaligned(target.add(tpos));
        let cand_u32 = table[(h as usize) & mask];
        if cand_u32 != u32::MAX {
            let mut cand = cand_u32 as usize;
            if cand + 16 <= base_len && eq16_unaligned(base.add(cand), target.add(tpos)) {
                let mut m_tpos = tpos;
                while m_tpos > lit_start && cand > 0 && tgt_slice[m_tpos - 1] == base_slice[cand - 1] {
                    m_tpos -= 1;
                    cand -= 1;
                }
                let mut mlen = 16 + (tpos - m_tpos);
                while cand + mlen + 8 <= base_len
                    && m_tpos + mlen + 8 <= target_len
                    && ptr::read_unaligned(base.add(cand + mlen) as *const u64)
                        == ptr::read_unaligned(target.add(m_tpos + mlen) as *const u64)
                {
                    mlen += 8;
                }
                while cand + mlen < base_len
                    && m_tpos + mlen < target_len
                    && base_slice[cand + mlen] == tgt_slice[m_tpos + mlen]
                {
                    mlen += 1;
                }

                if !emit_literal(&tgt_slice[lit_start..m_tpos], out_buf, out_cap, &mut out_pos) {
                    return -1;
                }
                if !emit_copy(cand as u32, mlen as u32, out_buf, out_cap, &mut out_pos) {
                    return -1;
                }
                tpos = m_tpos + mlen;
                lit_start = tpos;
                continue;
            }
        }
        tpos += 1;
    }

    if lit_start < target_len {
        if !emit_literal(&tgt_slice[lit_start..target_len], out_buf, out_cap, &mut out_pos) {
            return -1;
        }
    }

    out_pos as isize
}

#[no_mangle]
pub unsafe extern "C" fn chimera_delta_decode(
    base: *const u8,
    base_len: usize,
    patch: *const u8,
    patch_len: usize,
    out_buf: *mut u8,
    out_cap: usize,
) -> isize {
    if patch.is_null() || out_buf.is_null() {
        return -1;
    }
    let p_slice = std::slice::from_raw_parts(patch, patch_len);
    let mut ppos = 0usize;
    let mut opos = 0usize;

    while ppos < patch_len {
        let op = p_slice[ppos];
        ppos += 1;
        match op {
            0x01 => {
                if ppos + 8 > patch_len || base.is_null() {
                    return -1;
                }
                let boff = u32::from_le_bytes(p_slice[ppos..ppos + 4].try_into().unwrap()) as usize;
                let mlen = u32::from_le_bytes(p_slice[ppos + 4..ppos + 8].try_into().unwrap()) as usize;
                ppos += 8;
                if boff.checked_add(mlen).map_or(true, |e| e > base_len)
                    || opos.checked_add(mlen).map_or(true, |e| e > out_cap)
                {
                    return -1;
                }
                ptr::copy_nonoverlapping(base.add(boff), out_buf.add(opos), mlen);
                opos += mlen;
            }
            0x02 => {
                if ppos + 4 > patch_len {
                    return -1;
                }
                let llen = u32::from_le_bytes(p_slice[ppos..ppos + 4].try_into().unwrap()) as usize;
                ppos += 4;
                if ppos.checked_add(llen).map_or(true, |e| e > patch_len)
                    || opos.checked_add(llen).map_or(true, |e| e > out_cap)
                {
                    return -1;
                }
                ptr::copy_nonoverlapping(patch.add(ppos), out_buf.add(opos), llen);
                ppos += llen;
                opos += llen;
            }
            _ => return -1,
        }
    }

    opos as isize
}

// ---------------------------------------------------------------------------
// Active Compute-in-Transit: High-Speed Byte-Line Filter
// ---------------------------------------------------------------------------

#[inline]
fn contains_bytes(haystack: &[u8], needle: &[u8]) -> bool {
    if needle.is_empty() {
        return true;
    }
    if haystack.len() < needle.len() {
        return false;
    }
    let first = needle[0];
    let nlen = needle.len();
    let end = haystack.len() - nlen + 1;
    let mut i = 0usize;
    while i < end {
        if haystack[i] == first && &haystack[i..i + nlen] == needle {
            return true;
        }
        i += 1;
    }
    false
}

#[no_mangle]
pub unsafe extern "C" fn chimera_active_filter_lines(
    data: *const u8,
    len: usize,
    needle: *const u8,
    needle_len: usize,
    out_buf: *mut u8,
    out_cap: usize,
    out_matched_lines: *mut u64,
) -> isize {
    if out_matched_lines.is_null() || out_buf.is_null() {
        return -1;
    }
    *out_matched_lines = 0;
    if data.is_null() || len == 0 {
        return 0;
    }
    let hay = std::slice::from_raw_parts(data, len);
    let ndl = if needle.is_null() || needle_len == 0 {
        &[]
    } else {
        std::slice::from_raw_parts(needle, needle_len)
    };

    let mut out_pos = 0usize;
    let mut line_start = 0usize;
    let mut matched = 0u64;

    for (i, &b) in hay.iter().enumerate() {
        if b == b'\n' || i + 1 == len {
            let line_end = i + 1;
            let line = &hay[line_start..line_end];
            if contains_bytes(line, ndl) {
                matched += 1;
                if out_pos + line.len() > out_cap {
                    return -1;
                }
                ptr::copy_nonoverlapping(line.as_ptr(), out_buf.add(out_pos), line.len());
                out_pos += line.len();
            }
            line_start = line_end;
        }
    }

    *out_matched_lines = matched;
    out_pos as isize
}

// ---------------------------------------------------------------------------
// Lock-Free Windows Shared Memory Ring Buffer ("Wormhole IPC")
// ---------------------------------------------------------------------------

#[cfg(windows)]
#[link(name = "kernel32")]
extern "system" {
    fn CreateFileMappingW(
        hFile: *mut c_void,
        lpFileMappingAttributes: *mut c_void,
        flProtect: u32,
        dwMaximumSizeHigh: u32,
        dwMaximumSizeLow: u32,
        lpName: *const u16,
    ) -> *mut c_void;
    fn OpenFileMappingW(
        dwDesiredAccess: u32,
        bInheritHandle: i32,
        lpName: *const u16,
    ) -> *mut c_void;
    fn MapViewOfFile(
        hFileMappingObject: *mut c_void,
        dwDesiredAccess: u32,
        dwFileOffsetHigh: u32,
        dwFileOffsetLow: u32,
        dwNumberOfBytesToMap: usize,
    ) -> *mut c_void;
    fn UnmapViewOfFile(lpBaseAddress: *const c_void) -> i32;
    fn CloseHandle(hObject: *mut c_void) -> i32;
    fn Sleep(dwMilliseconds: u32);
}

#[cfg(windows)]
const INVALID_HANDLE: *mut c_void = (-1isize) as *mut c_void;
#[cfg(windows)]
const PAGE_READWRITE: u32 = 0x04;
#[cfg(windows)]
const FILE_MAP_ALL_ACCESS: u32 = 0x000F_001F;

const WORMHOLE_MAGIC: [u8; 8] = *b"CHWORM01";
const WORMHOLE_HEADER_SIZE: usize = 4096;

#[repr(C)]
struct WormholeHeader {
    magic: [u8; 8],
    capacity: u64,
    closed: AtomicU32,
    _pad0: [u8; 44],
    write_pos: AtomicU64,
    _pad1: [u8; 56],
    read_pos: AtomicU64,
    _pad2: [u8; 56],
}

struct WormholeHandle {
    map_handle: *mut c_void,
    view_ptr: *mut u8,
    capacity: usize,
}

#[cfg(windows)]
#[no_mangle]
pub unsafe extern "C" fn chimera_wormhole_create(
    name_utf16: *const u16,
    capacity: usize,
) -> *mut c_void {
    if name_utf16.is_null() {
        return ptr::null_mut();
    }
    let cap = capacity.max(4096).next_power_of_two();
    let total_size = WORMHOLE_HEADER_SIZE + cap;
    let hi = ((total_size as u64) >> 32) as u32;
    let lo = (total_size as u64 & 0xFFFF_FFFF) as u32;

    let map_handle = CreateFileMappingW(
        INVALID_HANDLE,
        ptr::null_mut(),
        PAGE_READWRITE,
        hi,
        lo,
        name_utf16,
    );
    if map_handle.is_null() {
        return ptr::null_mut();
    }

    let view = MapViewOfFile(map_handle, FILE_MAP_ALL_ACCESS, 0, 0, total_size);
    if view.is_null() {
        CloseHandle(map_handle);
        return ptr::null_mut();
    }

    ptr::write_bytes(view as *mut u8, 0, total_size);
    let hdr = &mut *(view as *mut WormholeHeader);
    hdr.magic = WORMHOLE_MAGIC;
    hdr.capacity = cap as u64;
    hdr.closed.store(0, Ordering::Release);
    hdr.write_pos.store(0, Ordering::Release);
    hdr.read_pos.store(0, Ordering::Release);

    let boxed = Box::new(WormholeHandle {
        map_handle,
        view_ptr: view as *mut u8,
        capacity: cap,
    });
    Box::into_raw(boxed) as *mut c_void
}

#[cfg(windows)]
#[no_mangle]
pub unsafe extern "C" fn chimera_wormhole_open(name_utf16: *const u16) -> *mut c_void {
    if name_utf16.is_null() {
        return ptr::null_mut();
    }
    let map_handle = OpenFileMappingW(FILE_MAP_ALL_ACCESS, 0, name_utf16);
    if map_handle.is_null() {
        return ptr::null_mut();
    }

    let hdr_view = MapViewOfFile(map_handle, FILE_MAP_ALL_ACCESS, 0, 0, WORMHOLE_HEADER_SIZE);
    if hdr_view.is_null() {
        CloseHandle(map_handle);
        return ptr::null_mut();
    }
    let hdr = &*(hdr_view as *const WormholeHeader);
    if hdr.magic != WORMHOLE_MAGIC || !hdr.capacity.is_power_of_two() || hdr.capacity < 4096 {
        UnmapViewOfFile(hdr_view);
        CloseHandle(map_handle);
        return ptr::null_mut();
    }
    let cap = hdr.capacity as usize;
    UnmapViewOfFile(hdr_view);

    let full_view = MapViewOfFile(
        map_handle,
        FILE_MAP_ALL_ACCESS,
        0,
        0,
        WORMHOLE_HEADER_SIZE + cap,
    );
    if full_view.is_null() {
        CloseHandle(map_handle);
        return ptr::null_mut();
    }

    let boxed = Box::new(WormholeHandle {
        map_handle,
        view_ptr: full_view as *mut u8,
        capacity: cap,
    });
    Box::into_raw(boxed) as *mut c_void
}

#[cfg(windows)]
#[no_mangle]
pub unsafe extern "C" fn chimera_wormhole_write(
    h: *mut c_void,
    data: *const u8,
    len: usize,
    timeout_ms: u32,
) -> isize {
    if h.is_null() || data.is_null() {
        return -1;
    }
    if len == 0 {
        return 0;
    }
    let wh = &*(h as *const WormholeHandle);
    let hdr = &*(wh.view_ptr as *const WormholeHeader);
    let data_ptr = wh.view_ptr.add(WORMHOLE_HEADER_SIZE);
    let cap = wh.capacity;
    let mask = cap - 1;

    let mut written = 0usize;
    let start = Instant::now();
    let timeout = Duration::from_millis(timeout_ms as u64);
    let mut spins = 0u32;

    while written < len {
        if hdr.closed.load(Ordering::Acquire) >= 2 {
            return if written > 0 { written as isize } else { -1 };
        }
        let w = hdr.write_pos.load(Ordering::Relaxed);
        let r = hdr.read_pos.load(Ordering::Acquire);
        let used = w.wrapping_sub(r) as usize;
        let free = cap.saturating_sub(used);

        if free > 0 {
            let chunk = free.min(len - written);
            let idx = (w as usize) & mask;
            let first = chunk.min(cap - idx);
            ptr::copy_nonoverlapping(data.add(written), data_ptr.add(idx), first);
            if chunk > first {
                ptr::copy_nonoverlapping(data.add(written + first), data_ptr, chunk - first);
            }
            hdr.write_pos.store(w.wrapping_add(chunk as u64), Ordering::Release);
            written += chunk;
            spins = 0;
        } else {
            if timeout_ms == 0 || start.elapsed() >= timeout {
                return if written > 0 { written as isize } else { -2 };
            }
            if spins < 4096 {
                spins += 1;
                std::hint::spin_loop();
            } else if spins < 32768 {
                spins += 1;
                std::thread::yield_now();
            } else {
                Sleep(1);
            }
        }
    }

    written as isize
}

#[cfg(windows)]
#[no_mangle]
pub unsafe extern "C" fn chimera_wormhole_read(
    h: *mut c_void,
    out: *mut u8,
    max_len: usize,
    timeout_ms: u32,
) -> isize {
    if h.is_null() || out.is_null() {
        return -1;
    }
    if max_len == 0 {
        return 0;
    }
    let wh = &*(h as *const WormholeHandle);
    let hdr = &*(wh.view_ptr as *const WormholeHeader);
    let data_ptr = wh.view_ptr.add(WORMHOLE_HEADER_SIZE);
    let cap = wh.capacity;
    let mask = cap - 1;

    let start = Instant::now();
    let timeout = Duration::from_millis(timeout_ms as u64);
    let mut spins = 0u32;

    loop {
        let r = hdr.read_pos.load(Ordering::Relaxed);
        let w = hdr.write_pos.load(Ordering::Acquire);
        let avail = w.wrapping_sub(r) as usize;

        if avail > 0 {
            let chunk = avail.min(max_len);
            let idx = (r as usize) & mask;
            let first = chunk.min(cap - idx);
            ptr::copy_nonoverlapping(data_ptr.add(idx), out, first);
            if chunk > first {
                ptr::copy_nonoverlapping(data_ptr, out.add(first), chunk - first);
            }
            hdr.read_pos.store(r.wrapping_add(chunk as u64), Ordering::Release);
            return chunk as isize;
        }

        let closed_state = hdr.closed.load(Ordering::Acquire);
        if closed_state != 0 {
            // Re-check write_pos after observing closed flag so trailing bytes are never missed
            let w2 = hdr.write_pos.load(Ordering::Acquire);
            if w2.wrapping_sub(r) == 0 {
                return 0;
            }
            continue;
        }

        if timeout_ms == 0 || start.elapsed() >= timeout {
            return -2;
        }
        if spins < 4096 {
            spins += 1;
            std::hint::spin_loop();
        } else if spins < 32768 {
            spins += 1;
            std::thread::yield_now();
        } else {
            Sleep(1);
        }
    }
}

#[cfg(windows)]
#[no_mangle]
pub unsafe extern "C" fn chimera_wormhole_mark_eof(h: *mut c_void) {
    if h.is_null() {
        return;
    }
    let wh = &*(h as *const WormholeHandle);
    let hdr = &*(wh.view_ptr as *const WormholeHeader);
    hdr.closed.store(1, Ordering::Release);
}

#[cfg(windows)]
#[no_mangle]
pub unsafe extern "C" fn chimera_wormhole_close(h: *mut c_void) {
    if h.is_null() {
        return;
    }
    let wh = Box::from_raw(h as *mut WormholeHandle);
    if !wh.view_ptr.is_null() {
        UnmapViewOfFile(wh.view_ptr as *const c_void);
    }
    if !wh.map_handle.is_null() {
        CloseHandle(wh.map_handle);
    }
}

// ---------------------------------------------------------------------------
// CHIMERA v7.0 OMEGA-FABRIC Extensions (ChaCha20, RLNC Recode, PPM, Slepian)
// ---------------------------------------------------------------------------

#[inline(always)]
fn chacha_qr(s: &mut [u32; 16], a: usize, b: usize, c: usize, d: usize) {
    s[a] = s[a].wrapping_add(s[b]);
    s[d] = (s[d] ^ s[a]).rotate_left(16);
    s[c] = s[c].wrapping_add(s[d]);
    s[b] = (s[b] ^ s[c]).rotate_left(12);
    s[a] = s[a].wrapping_add(s[b]);
    s[d] = (s[d] ^ s[a]).rotate_left(8);
    s[c] = s[c].wrapping_add(s[d]);
    s[b] = (s[b] ^ s[c]).rotate_left(7);
}

#[no_mangle]
pub unsafe extern "C" fn chimera_chacha20_xor(
    out: *mut u8,
    inp: *const u8,
    len: usize,
    key32: *const u8,
    nonce12: *const u8,
    mut counter: u32,
) {
    if out.is_null() || inp.is_null() || key32.is_null() || nonce12.is_null() || len == 0 {
        return;
    }
    let key = std::slice::from_raw_parts(key32, 32);
    let nonce = std::slice::from_raw_parts(nonce12, 12);
    let mut base = [0u32; 16];
    base[0] = 0x6170_7865;
    base[1] = 0x3320_646e;
    base[2] = 0x7962_2d32;
    base[3] = 0x6b20_6574;
    for i in 0..8 {
        base[4 + i] = u32::from_le_bytes([key[4 * i], key[4 * i + 1], key[4 * i + 2], key[4 * i + 3]]);
    }
    for i in 0..3 {
        base[13 + i] = u32::from_le_bytes([nonce[4 * i], nonce[4 * i + 1], nonce[4 * i + 2], nonce[4 * i + 3]]);
    }

    let mut off = 0usize;
    let mut ks = [0u8; 64];
    while off < len {
        let mut st = base;
        st[12] = counter;
        for _ in 0..10 {
            chacha_qr(&mut st, 0, 4, 8, 12);
            chacha_qr(&mut st, 1, 5, 9, 13);
            chacha_qr(&mut st, 2, 6, 10, 14);
            chacha_qr(&mut st, 3, 7, 11, 15);
            chacha_qr(&mut st, 0, 5, 10, 15);
            chacha_qr(&mut st, 1, 6, 11, 12);
            chacha_qr(&mut st, 2, 7, 8, 13);
            chacha_qr(&mut st, 3, 4, 9, 14);
        }
        for i in 0..16 {
            let v = st[i].wrapping_add(if i == 12 { counter } else { base[i] });
            let b = v.to_le_bytes();
            ks[4 * i] = b[0];
            ks[4 * i + 1] = b[1];
            ks[4 * i + 2] = b[2];
            ks[4 * i + 3] = b[3];
        }
        let chunk = (len - off).min(64);
        for i in 0..chunk {
            *out.add(off + i) = *inp.add(off + i) ^ ks[i];
        }
        off += chunk;
        counter = counter.wrapping_add(1);
    }
}

#[no_mangle]
pub unsafe extern "C" fn chimera_gf256_recode(
    out_payload: *mut u8,
    out_coeffs: *mut u8,
    payloads_flat: *const u8,
    coeffs_flat: *const u8,
    m_in: usize,
    k: usize,
    block_len: usize,
    weights: *const u8,
) {
    if out_payload.is_null()
        || out_coeffs.is_null()
        || payloads_flat.is_null()
        || coeffs_flat.is_null()
        || weights.is_null()
        || m_in == 0
        || k == 0
        || block_len == 0
    {
        return;
    }
    ptr::write_bytes(out_payload, 0, block_len);
    ptr::write_bytes(out_coeffs, 0, k);
    let caps = chimera_cpu_caps();
    let has_gfni = (caps & 1) != 0;
    let has_avx2 = (caps & 2) != 0;
    for i in 0..m_in {
        let w = *weights.add(i);
        if w != 0 {
            gf256_mul_add_impl(out_payload, payloads_flat.add(i * block_len), block_len, w, has_gfni, has_avx2);
            gf256_mul_add_impl(out_coeffs, coeffs_flat.add(i * k), k, w, has_gfni, has_avx2);
        }
    }
}

#[no_mangle]
pub unsafe extern "C" fn chimera_slepian_syndrome(
    blocks_flat: *const u8,
    n_blocks: usize,
    block_len: usize,
    alpha: u8,
    num_parities: usize,
    out_syndromes: *mut u8,
) {
    if blocks_flat.is_null() || out_syndromes.is_null() || n_blocks == 0 || block_len == 0 || num_parities == 0 {
        return;
    }
    let total = num_parities * block_len;
    ptr::write_bytes(out_syndromes, 0, total);
    let caps = chimera_cpu_caps();
    let has_gfni = (caps & 1) != 0;
    let has_avx2 = (caps & 2) != 0;
    let mut root = 1u8;
    for j in 0..num_parities {
        let syn_j = out_syndromes.add(j * block_len);
        let mut pow_cur = 1u8;
        for i in 0..n_blocks {
            if pow_cur != 0 {
                gf256_mul_add_impl(syn_j, blocks_flat.add(i * block_len), block_len, pow_cur, has_gfni, has_avx2);
            }
            pow_cur = MUL_LUT[pow_cur as usize][root as usize];
        }
        root = MUL_LUT[root as usize][alpha as usize];
    }
}

struct PpmRangeEnc {
    low: u64,
    range: u32,
    cache: u8,
    cache_size: u64,
}

impl PpmRangeEnc {
    fn new() -> Self {
        Self {
            low: 0,
            range: 0xFFFF_FFFF,
            cache: 0,
            cache_size: 1,
        }
    }

    #[inline(always)]
    fn shift_low(&mut self, out: &mut Vec<u8>) {
        if (self.low as u32) < 0xFF00_0000 || (self.low >> 32) != 0 {
            let mut temp = self.cache;
            loop {
                out.push(temp.wrapping_add((self.low >> 32) as u8));
                temp = 0xFF;
                self.cache_size -= 1;
                if self.cache_size == 0 {
                    break;
                }
            }
            self.cache = ((self.low >> 24) & 0xFF) as u8;
        }
        self.cache_size += 1;
        self.low = ((self.low as u32) << 8) as u64;
    }

    #[inline(always)]
    fn encode_bit(&mut self, bit: u32, prob: u32, out: &mut Vec<u8>) {
        let p = prob.clamp(1, 4095);
        let bound = (self.range >> 12) * p;
        if bit != 0 {
            self.range = bound;
        } else {
            self.low += bound as u64;
            self.range -= bound;
        }
        if self.range < 0x0100_0000 {
            self.range <<= 8;
            self.shift_low(out);
        }
    }

    fn finish(&mut self, out: &mut Vec<u8>) {
        for _ in 0..5 {
            self.shift_low(out);
        }
    }
}

struct PpmRangeDec<'a> {
    data: &'a [u8],
    pos: usize,
    code: u32,
    range: u32,
}

impl<'a> PpmRangeDec<'a> {
    fn new(data: &'a [u8]) -> Self {
        let mut pos = 1.min(data.len());
        let mut code = 0u32;
        for _ in 0..4 {
            let b = if pos < data.len() {
                let v = data[pos];
                pos += 1;
                v
            } else {
                0
            };
            code = (code << 8) | (b as u32);
        }
        Self {
            data,
            pos,
            code,
            range: 0xFFFF_FFFF,
        }
    }

    #[inline(always)]
    fn decode_bit(&mut self, prob: u32) -> u32 {
        let p = prob.clamp(1, 4095);
        let bound = (self.range >> 12) * p;
        let bit = if self.code < bound {
            self.range = bound;
            1
        } else {
            self.code -= bound;
            self.range -= bound;
            0
        };
        if self.range < 0x0100_0000 {
            self.range <<= 8;
            let b = if self.pos < self.data.len() {
                let v = self.data[self.pos];
                self.pos += 1;
                v
            } else {
                0
            };
            self.code = (self.code << 8) | (b as u32);
        }
        bit
    }
}

#[no_mangle]
pub unsafe extern "C" fn chimera_ppm_compress(
    inp: *const u8,
    inp_len: usize,
    out: *mut u8,
    out_cap: usize,
) -> isize {
    if out.is_null() || out_cap < 4 {
        return -1;
    }
    let len_b = (inp_len as u32).to_le_bytes();
    if inp_len == 0 || inp.is_null() {
        ptr::copy_nonoverlapping(len_b.as_ptr(), out, 4);
        return 4;
    }
    let src = std::slice::from_raw_parts(inp, inp_len);
    let mut p0 = vec![2048u16; 256];
    let mut p1 = vec![2048u16; 65536];
    let mut p2 = vec![2048u16; 262144];

    let mut enc = PpmRangeEnc::new();
    let mut buf: Vec<u8> = Vec::with_capacity((inp_len / 2).max(64) + 16);
    buf.extend_from_slice(&len_b);

    let mut prev1 = 0usize;
    let mut prev2 = 0usize;
    for &byte_val in src {
        let mut ctx = 1usize;
        for k in (0..8).rev() {
            let c0 = ctx;
            let c1 = (prev1 << 8) | ctx;
            let h2 = ((prev2.wrapping_mul(257)) ^ (prev1.wrapping_mul(17))) & 0x3FF;
            let c2 = (h2 << 8) | ctx;
            let pr = ((p0[c0] as u32) + 2 * (p1[c1] as u32) + 5 * (p2[c2] as u32)) >> 3;
            let bit = ((byte_val >> k) & 1) as u32;
            enc.encode_bit(bit, pr, &mut buf);
            if bit != 0 {
                p0[c0] = (p0[c0] as i32 + ((4096 - p0[c0] as i32) >> 5)) as u16;
                p1[c1] = (p1[c1] as i32 + ((4096 - p1[c1] as i32) >> 5)) as u16;
                p2[c2] = (p2[c2] as i32 + ((4096 - p2[c2] as i32) >> 5)) as u16;
            } else {
                p0[c0] -= p0[c0] >> 5;
                p1[c1] -= p1[c1] >> 5;
                p2[c2] -= p2[c2] >> 5;
            }
            ctx = (ctx << 1) | (bit as usize);
        }
        prev2 = prev1;
        prev1 = ctx & 0xFF;
    }
    enc.finish(&mut buf);
    if buf.len() > out_cap {
        return -1;
    }
    ptr::copy_nonoverlapping(buf.as_ptr(), out, buf.len());
    buf.len() as isize
}

#[no_mangle]
pub unsafe extern "C" fn chimera_ppm_decompress(
    inp: *const u8,
    inp_len: usize,
    out: *mut u8,
    out_cap: usize,
) -> isize {
    if inp.is_null() || inp_len < 4 {
        return -1;
    }
    let src = std::slice::from_raw_parts(inp, inp_len);
    let orig_len = u32::from_le_bytes([src[0], src[1], src[2], src[3]]) as usize;
    if orig_len == 0 {
        return 0;
    }
    if out.is_null() || orig_len > out_cap {
        return -1;
    }
    let mut p0 = vec![2048u16; 256];
    let mut p1 = vec![2048u16; 65536];
    let mut p2 = vec![2048u16; 262144];

    let mut dec = PpmRangeDec::new(&src[4..]);
    let mut prev1 = 0usize;
    let mut prev2 = 0usize;
    for i in 0..orig_len {
        let mut ctx = 1usize;
        for _ in 0..8 {
            let c0 = ctx;
            let c1 = (prev1 << 8) | ctx;
            let h2 = ((prev2.wrapping_mul(257)) ^ (prev1.wrapping_mul(17))) & 0x3FF;
            let c2 = (h2 << 8) | ctx;
            let pr = ((p0[c0] as u32) + 2 * (p1[c1] as u32) + 5 * (p2[c2] as u32)) >> 3;
            let bit = dec.decode_bit(pr);
            if bit != 0 {
                p0[c0] = (p0[c0] as i32 + ((4096 - p0[c0] as i32) >> 5)) as u16;
                p1[c1] = (p1[c1] as i32 + ((4096 - p1[c1] as i32) >> 5)) as u16;
                p2[c2] = (p2[c2] as i32 + ((4096 - p2[c2] as i32) >> 5)) as u16;
            } else {
                p0[c0] -= p0[c0] >> 5;
                p1[c1] -= p1[c1] >> 5;
                p2[c2] -= p2[c2] >> 5;
            }
            ctx = (ctx << 1) | (bit as usize);
        }
        *out.add(i) = (ctx & 0xFF) as u8;
        prev2 = prev1;
        prev1 = ctx & 0xFF;
    }
    orig_len as isize
}

// -----------------------------------------------------------------------------
// CHIMERA v8.0 SINGULARITY Extensions (IT-PIR SIMD XOR & Q15 FSK Demodulator)
// -----------------------------------------------------------------------------

#[no_mangle]
pub unsafe extern "C" fn chimera_pir_xor_query(
    db_flat: *const u8,
    n_records: usize,
    rec_len: usize,
    query_bits: *const u8,
    out_rec: *mut u8,
) {
    if out_rec.is_null() || rec_len == 0 {
        return;
    }
    ptr::write_bytes(out_rec, 0, rec_len);
    if db_flat.is_null() || query_bits.is_null() || n_records == 0 {
        return;
    }
    let out_slice = std::slice::from_raw_parts_mut(out_rec, rec_len);
    let q_bytes = (n_records + 7) / 8;
    let q_slice = std::slice::from_raw_parts(query_bits, q_bytes);
    let words = rec_len / 8;
    for i in 0..n_records {
        if ((q_slice[i >> 3] >> (i & 7)) & 1) != 0 {
            let rec = std::slice::from_raw_parts(db_flat.add(i * rec_len), rec_len);
            let dst_ptr = out_slice.as_mut_ptr() as *mut u64;
            let src_ptr = rec.as_ptr() as *const u64;
            for w in 0..words {
                let d = ptr::read_unaligned(dst_ptr.add(w));
                let s = ptr::read_unaligned(src_ptr.add(w));
                ptr::write_unaligned(dst_ptr.add(w), d ^ s);
            }
            for b in (words * 8)..rec_len {
                out_slice[b] ^= rec[b];
            }
        }
    }
}

#[no_mangle]
pub unsafe extern "C" fn chimera_fsk_demod_bits(
    pcm: *const i16,
    n_samples: usize,
    out_bits: *mut u8,
    max_bits: usize,
) -> usize {
    if pcm.is_null() || out_bits.is_null() || n_samples < 40 || max_bits == 0 {
        return 0;
    }
    const COS0: [i64; 8] = [32767, -23170, 0, 23170, -32767, 23170, 0, -23170];
    const SIN0: [i64; 8] = [0, 23170, -32767, 23170, 0, -23170, 32767, -23170];
    const COS1: [i64; 5] = [32767, -26509, 10126, 10126, -26509];
    const SIN1: [i64; 5] = [0, 19260, -31164, 31164, -19260];

    let n_syms = (n_samples / 40).min(max_bits);
    let samples = std::slice::from_raw_parts(pcm, n_syms * 40);
    let out = std::slice::from_raw_parts_mut(out_bits, n_syms);
    for s in 0..n_syms {
        let base = s * 40;
        let mut i0: i64 = 0;
        let mut q0: i64 = 0;
        let mut i1: i64 = 0;
        let mut q1: i64 = 0;
        let mut idx5 = 0usize;
        for j in 0..40 {
            let x = samples[base + j] as i64;
            let idx8 = j & 7;
            i0 += x * COS0[idx8];
            q0 += x * SIN0[idx8];
            i1 += x * COS1[idx5];
            q1 += x * SIN1[idx5];
            idx5 += 1;
            if idx5 == 5 {
                idx5 = 0;
            }
        }
        let si0 = i0 >> 10;
        let sq0 = q0 >> 10;
        let si1 = i1 >> 10;
        let sq1 = q1 >> 10;
        let e0 = si0 * si0 + sq0 * sq0;
        let e1 = si1 * si1 + sq1 * sq1;
        out[s] = if e1 > e0 { 1 } else { 0 };
    }
    n_syms
}

// -----------------------------------------------------------------------------
// CHIMERA v9.0 HYPERDRIVE Extensions (LZ4 SIMD, Batch ChaCha20, Search, Tiles)
// -----------------------------------------------------------------------------

#[inline(always)]
unsafe fn lz4_write_ext_len(dst: *mut u8, op: &mut usize, dst_cap: usize, mut rem: usize) -> bool {
    while rem >= 255 {
        if *op >= dst_cap {
            return false;
        }
        *dst.add(*op) = 255;
        *op += 1;
        rem -= 255;
    }
    if *op >= dst_cap {
        return false;
    }
    *dst.add(*op) = rem as u8;
    *op += 1;
    true
}

#[no_mangle]
pub unsafe extern "C" fn chimera_lz4_compress(
    src: *const u8,
    src_len: usize,
    dst: *mut u8,
    dst_cap: usize,
) -> isize {
    if src_len == 0 {
        return 0;
    }
    if src.is_null() || dst.is_null() || dst_cap < 4 || src_len > (u32::MAX as usize) {
        return -1;
    }
    let len_le = (src_len as u32).to_le_bytes();
    ptr::copy_nonoverlapping(len_le.as_ptr(), dst, 4);
    let mut op = 4usize;

    let mut ht = [-1i32; 4096];
    let mut ip = 0usize;
    let mut anchor = 0usize;

    if src_len >= 13 {
        let mflimit = src_len - 12;
        let matchlimit = src_len - 5;
        while ip <= mflimit {
            let v = ptr::read_unaligned(src.add(ip) as *const u32).to_le();
            let hh = ((v.wrapping_mul(2654435761u32)) >> 20) as usize & 0xFFF;
            let ref_pos = ht[hh];
            ht[hh] = ip as i32;

            if ref_pos >= 0 {
                let ru = ref_pos as usize;
                let off = ip - ru;
                if off >= 1
                    && off <= 65535
                    && ptr::read_unaligned(src.add(ru) as *const u32).to_le() == v
                {
                    let mut ml = 4usize;
                    while ip + ml < matchlimit && *src.add(ru + ml) == *src.add(ip + ml) {
                        ml += 1;
                    }
                    let lit_len = ip - anchor;
                    let mc = ml - 4;
                    if op >= dst_cap {
                        return -1;
                    }
                    let tok_l = lit_len.min(15);
                    let tok_m = mc.min(15);
                    *dst.add(op) = ((tok_l << 4) | tok_m) as u8;
                    op += 1;
                    if lit_len >= 15 && !lz4_write_ext_len(dst, &mut op, dst_cap, lit_len - 15) {
                        return -1;
                    }
                    if op + lit_len + 2 > dst_cap {
                        return -1;
                    }
                    if lit_len > 0 {
                        ptr::copy_nonoverlapping(src.add(anchor), dst.add(op), lit_len);
                        op += lit_len;
                    }
                    *dst.add(op) = (off & 0xFF) as u8;
                    *dst.add(op + 1) = ((off >> 8) & 0xFF) as u8;
                    op += 2;
                    if mc >= 15 && !lz4_write_ext_len(dst, &mut op, dst_cap, mc - 15) {
                        return -1;
                    }
                    ip += ml;
                    anchor = ip;
                    continue;
                }
            }
            ip += 1;
        }
    }

    let last_lit = src_len - anchor;
    if op >= dst_cap {
        return -1;
    }
    let tok_l = last_lit.min(15);
    *dst.add(op) = (tok_l << 4) as u8;
    op += 1;
    if last_lit >= 15 && !lz4_write_ext_len(dst, &mut op, dst_cap, last_lit - 15) {
        return -1;
    }
    if op + last_lit > dst_cap {
        return -1;
    }
    if last_lit > 0 {
        ptr::copy_nonoverlapping(src.add(anchor), dst.add(op), last_lit);
        op += last_lit;
    }
    op as isize
}

#[no_mangle]
pub unsafe extern "C" fn chimera_lz4_decompress(
    src: *const u8,
    src_len: usize,
    dst: *mut u8,
    dst_cap: usize,
) -> isize {
    if src_len == 0 {
        return 0;
    }
    if src.is_null() || src_len < 4 {
        return -1;
    }
    let s = std::slice::from_raw_parts(src, src_len);
    let orig_len = u32::from_le_bytes([s[0], s[1], s[2], s[3]]) as usize;
    if orig_len == 0 {
        return if src_len == 4 { 0 } else { -1 };
    }
    if dst.is_null() || orig_len > dst_cap {
        return -1;
    }

    let mut ip = 4usize;
    let mut op = 0usize;
    while ip < src_len {
        let tok = s[ip];
        ip += 1;
        let mut lit_len = (tok >> 4) as usize;
        if lit_len == 15 {
            loop {
                if ip >= src_len {
                    return -1;
                }
                let b = s[ip] as usize;
                ip += 1;
                if lit_len > orig_len - op {
                    return -1;
                }
                lit_len += b;
                if b < 255 {
                    break;
                }
            }
        }
        if ip + lit_len > src_len || op + lit_len > orig_len {
            return -1;
        }
        if lit_len > 0 {
            ptr::copy_nonoverlapping(src.add(ip), dst.add(op), lit_len);
            ip += lit_len;
            op += lit_len;
        }
        if ip >= src_len {
            break;
        }
        if ip + 2 > src_len {
            return -1;
        }
        let off = (s[ip] as usize) | ((s[ip + 1] as usize) << 8);
        ip += 2;
        if off == 0 || off > op {
            return -1;
        }
        let mut ml = ((tok & 0x0F) as usize) + 4;
        if (tok & 0x0F) == 15 {
            loop {
                if ip >= src_len {
                    return -1;
                }
                let b = s[ip] as usize;
                ip += 1;
                if ml > orig_len - op {
                    return -1;
                }
                ml += b;
                if b < 255 {
                    break;
                }
            }
        }
        if op + ml > orig_len {
            return -1;
        }
        let mpos = op - off;
        for k in 0..ml {
            *dst.add(op + k) = *dst.add(mpos + k);
        }
        op += ml;
    }
    if ip == src_len && op == orig_len {
        orig_len as isize
    } else {
        -1
    }
}

#[no_mangle]
pub unsafe extern "C" fn chimera_batch_chacha20_xor(
    bufs_flat: *mut u8,
    packet_len: usize,
    n_packets: usize,
    key32: *const u8,
    base_nonce8: *const u8,
) {
    if bufs_flat.is_null() || key32.is_null() || base_nonce8.is_null() || packet_len == 0 || n_packets == 0 {
        return;
    }
    let n8 = std::slice::from_raw_parts(base_nonce8, 8);
    let base_val = u64::from_be_bytes([n8[0], n8[1], n8[2], n8[3], n8[4], n8[5], n8[6], n8[7]]);
    let mut nonce12 = [b'P', b'H', b'9', b'N', 0, 0, 0, 0, 0, 0, 0, 0];
    for i in 0..n_packets {
        let v = base_val.wrapping_add(i as u64).to_be_bytes();
        nonce12[4..12].copy_from_slice(&v);
        let p = bufs_flat.add(i * packet_len);
        chimera_chacha20_xor(p, p, packet_len, key32, nonce12.as_ptr(), 1);
    }
}

#[cfg(target_arch = "x86_64")]
#[target_feature(enable = "avx2")]
unsafe fn simd_search_avx2(
    hay: *const u8,
    hay_len: usize,
    needle: *const u8,
    needle_len: usize,
    out_offsets: *mut u32,
    max_matches: usize,
) -> usize {
    let limit = hay_len - needle_len + 1;
    let first = _mm256_set1_epi8(*needle as i8);
    let last = _mm256_set1_epi8(*needle.add(needle_len - 1) as i8);
    let mut i = 0usize;
    let mut count = 0usize;

    while i + 32 <= limit {
        let b0 = _mm256_loadu_si256(hay.add(i) as *const __m256i);
        let b1 = _mm256_loadu_si256(hay.add(i + needle_len - 1) as *const __m256i);
        let eq = _mm256_and_si256(_mm256_cmpeq_epi8(b0, first), _mm256_cmpeq_epi8(b1, last));
        let mut mask = _mm256_movemask_epi8(eq) as u32;
        while mask != 0 {
            let bit = mask.trailing_zeros() as usize;
            let pos = i + bit;
            let mut ok = true;
            if needle_len > 2 {
                let mut k = 1usize;
                while k < needle_len - 1 {
                    if *hay.add(pos + k) != *needle.add(k) {
                        ok = false;
                        break;
                    }
                    k += 1;
                }
            }
            if ok {
                if !out_offsets.is_null() && count < max_matches {
                    *out_offsets.add(count) = pos as u32;
                }
                count += 1;
            }
            mask &= mask - 1;
        }
        i += 32;
    }

    while i < limit {
        let mut ok = *hay.add(i) == *needle && *hay.add(i + needle_len - 1) == *needle.add(needle_len - 1);
        if ok && needle_len > 2 {
            let mut k = 1usize;
            while k < needle_len - 1 {
                if *hay.add(i + k) != *needle.add(k) {
                    ok = false;
                    break;
                }
                k += 1;
            }
        }
        if ok {
            if !out_offsets.is_null() && count < max_matches {
                *out_offsets.add(count) = i as u32;
            }
            count += 1;
        }
        i += 1;
    }
    count
}

#[no_mangle]
pub unsafe extern "C" fn chimera_simd_search_count(
    haystack: *const u8,
    hay_len: usize,
    needle: *const u8,
    needle_len: usize,
    out_offsets: *mut u32,
    max_matches: usize,
) -> usize {
    if haystack.is_null() || needle.is_null() || needle_len == 0 || needle_len > hay_len {
        return 0;
    }
    #[cfg(target_arch = "x86_64")]
    if std::arch::is_x86_feature_detected!("avx2") {
        return simd_search_avx2(haystack, hay_len, needle, needle_len, out_offsets, max_matches);
    }
    let limit = hay_len - needle_len + 1;
    let mut count = 0usize;
    let hay_s = std::slice::from_raw_parts(haystack, hay_len);
    let ndl_s = std::slice::from_raw_parts(needle, needle_len);
    for i in 0..limit {
        if &hay_s[i..i + needle_len] == ndl_s {
            if !out_offsets.is_null() && count < max_matches {
                *out_offsets.add(count) = i as u32;
            }
            count += 1;
        }
    }
    count
}

#[cfg(target_arch = "x86_64")]
#[target_feature(enable = "avx2")]
unsafe fn tile_is_equal_avx2(p: *const u8, c: *const u8, len: usize) -> bool {
    let mut i = 0usize;
    while i + 32 <= len {
        let vp = _mm256_loadu_si256(p.add(i) as *const __m256i);
        let vc = _mm256_loadu_si256(c.add(i) as *const __m256i);
        let x = _mm256_xor_si256(vp, vc);
        if _mm256_testz_si256(x, x) == 0 {
            return false;
        }
        i += 32;
    }
    while i < len {
        if *p.add(i) != *c.add(i) {
            return false;
        }
        i += 1;
    }
    true
}

#[cfg(target_arch = "x86_64")]
#[target_feature(enable = "avx2")]
unsafe fn tile_xor_copy_avx2(dst: *mut u8, p: *const u8, c: *const u8, len: usize) {
    let mut i = 0usize;
    while i + 32 <= len {
        let vp = _mm256_loadu_si256(p.add(i) as *const __m256i);
        let vc = _mm256_loadu_si256(c.add(i) as *const __m256i);
        _mm256_storeu_si256(dst.add(i) as *mut __m256i, _mm256_xor_si256(vp, vc));
        i += 32;
    }
    while i < len {
        *dst.add(i) = *p.add(i) ^ *c.add(i);
        i += 1;
    }
}

#[no_mangle]
pub unsafe extern "C" fn chimera_tile_diff_xor(
    prev: *const u8,
    curr: *const u8,
    n_tiles: usize,
    tile_bytes: usize,
    out_mask: *mut u8,
    out_delta: *mut u8,
    max_delta: usize,
) -> isize {
    if n_tiles == 0 || tile_bytes == 0 {
        return 0;
    }
    if prev.is_null() || curr.is_null() || out_mask.is_null() {
        return -1;
    }
    let has_avx2 = {
        #[cfg(target_arch = "x86_64")]
        {
            std::arch::is_x86_feature_detected!("avx2")
        }
        #[cfg(not(target_arch = "x86_64"))]
        {
            false
        }
    };
    let mut written = 0usize;
    for t in 0..n_tiles {
        let off = t * tile_bytes;
        let p = prev.add(off);
        let c = curr.add(off);
        let same = if has_avx2 {
            #[cfg(target_arch = "x86_64")]
            {
                tile_is_equal_avx2(p, c, tile_bytes)
            }
            #[cfg(not(target_arch = "x86_64"))]
            {
                false
            }
        } else {
            let mut eq = true;
            for k in 0..tile_bytes {
                if *p.add(k) != *c.add(k) {
                    eq = false;
                    break;
                }
            }
            eq
        };
        if same {
            *out_mask.add(t) = 0;
        } else {
            *out_mask.add(t) = 1;
            if out_delta.is_null() || written + tile_bytes > max_delta {
                return -1;
            }
            let d = out_delta.add(written);
            if has_avx2 {
                #[cfg(target_arch = "x86_64")]
                tile_xor_copy_avx2(d, p, c, tile_bytes);
            } else {
                for k in 0..tile_bytes {
                    *d.add(k) = *p.add(k) ^ *c.add(k);
                }
            }
            written += tile_bytes;
        }
    }
    written as isize
}

#[no_mangle]
pub unsafe extern "C" fn chimera_vsa_bind_xor(
    a: *const u8,
    b: *const u8,
    out: *mut u8,
    len: usize,
) {
    if a.is_null() || b.is_null() || out.is_null() || len == 0 {
        return;
    }
    let mut i = 0usize;
    #[cfg(target_arch = "x86_64")]
    if std::arch::is_x86_feature_detected!("avx2") {
        while i + 32 <= len {
            let va = _mm256_loadu_si256(a.add(i) as *const __m256i);
            let vb = _mm256_loadu_si256(b.add(i) as *const __m256i);
            _mm256_storeu_si256(out.add(i) as *mut __m256i, _mm256_xor_si256(va, vb));
            i += 32;
        }
    }
    while i < len {
        *out.add(i) = *a.add(i) ^ *b.add(i);
        i += 1;
    }
}

#[no_mangle]
pub unsafe extern "C" fn chimera_vsa_hamming(a: *const u8, b: *const u8, len: usize) -> usize {
    if a.is_null() || b.is_null() || len == 0 {
        return 0;
    }
    let sa = std::slice::from_raw_parts(a, len);
    let sb = std::slice::from_raw_parts(b, len);
    let mut tot = 0usize;
    let mut i = 0usize;
    while i + 8 <= len {
        let va = u64::from_le_bytes(sa[i..i + 8].try_into().unwrap());
        let vb = u64::from_le_bytes(sb[i..i + 8].try_into().unwrap());
        tot += (va ^ vb).count_ones() as usize;
        i += 8;
    }
    while i < len {
        tot += (sa[i] ^ sb[i]).count_ones() as usize;
        i += 1;
    }
    tot
}

#[inline(always)]
fn ch_fold_q16(v: i64) -> i32 {
    ((v + 1_048_576).rem_euclid(2_097_152) - 1_048_576) as i32
}

#[no_mangle]
pub unsafe extern "C" fn chimera_chaos_step_q16(
    state: *mut i32,
    drive: *const u8,
    out_ks: *mut u8,
    len: usize,
    coupling_q16: i32,
) {
    if state.is_null() || drive.is_null() || out_ks.is_null() || len == 0 {
        return;
    }
    let mut x = *state.add(0) as i64;
    let mut y = *state.add(1) as i64;
    let mut z = *state.add(2) as i64;
    let c = coupling_q16.clamp(0, 65_536) as i64;
    let dt: i64 = 655;

    for i in 0..len {
        let d_q16 = ((*drive.add(i) as i32 - 128) << 11) as i64;
        let xd = x + ((c * (d_q16 - x)) >> 16);
        let nx = ch_fold_q16(xd + ((10 * (y - xd) * dt) >> 16) + ((z ^ (y >> 3)) & 0x7FFF)) as i64;
        let ny = ch_fold_q16(y + ((((xd * (1_835_008 - z)) >> 16) - y) * dt >> 16) + (d_q16 >> 2)) as i64;
        let nz = ch_fold_q16(
            z + ((((xd * y) >> 16) - ((z * 174_762) >> 16)) * dt >> 16) + ((nx >> 2) & 0xFFFF),
        ) as i64;

        let nx_u = (nx as i32) as u32;
        let ny_u = (ny as i32) as u32;
        let nz_u = (nz as i32) as u32;
        let mut mix = (nx_u ^ (ny_u >> 5) ^ (nz_u >> 11) ^ (nx_u << 7)).wrapping_mul(2_654_435_761);
        mix ^= mix >> 16;
        *out_ks.add(i) = (mix.wrapping_mul(2_246_822_519) >> 24) as u8;

        x = nx;
        y = ny;
        z = nz;
    }
    *state.add(0) = x as i32;
    *state.add(1) = y as i32;
    *state.add(2) = z as i32;
}

#[inline(always)]
fn ch_splitmix64(state: &mut u64) -> u64 {
    *state = state.wrapping_add(0x9E37_79B9_7F4A_7C15);
    let mut z = *state;
    z = (z ^ (z >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
    z = (z ^ (z >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
    z ^ (z >> 31)
}

#[no_mangle]
pub unsafe extern "C" fn chimera_babel_mine(
    target: *const u8,
    len: usize,
    start_seed: u64,
    n_candidates: u32,
    out_best_seed: *mut u64,
    out_best_dist: *mut u32,
) {
    if target.is_null() || len == 0 || n_candidates == 0 {
        if !out_best_seed.is_null() {
            *out_best_seed = start_seed;
        }
        if !out_best_dist.is_null() {
            *out_best_dist = len as u32;
        }
        return;
    }
    let tgt = std::slice::from_raw_parts(target, len);
    let mut best_dist: u32 = (len as u32).saturating_add(1);
    let mut best_seed: u64 = start_seed;

    for k in 0..n_candidates {
        let seed = start_seed.wrapping_add(k as u64);
        let mut s = seed;
        let mut dist: u32 = 0;
        let mut i = 0usize;
        let mut aborted = false;
        while i < len {
            let w = ch_splitmix64(&mut s).to_le_bytes();
            let take = (len - i).min(8);
            for j in 0..take {
                if w[j] != tgt[i + j] {
                    dist += 1;
                    if dist >= best_dist {
                        aborted = true;
                        break;
                    }
                }
            }
            if aborted {
                break;
            }
            i += take;
        }
        if !aborted && dist < best_dist {
            best_dist = dist;
            best_seed = seed;
            if best_dist == 0 {
                break;
            }
        }
    }
    if !out_best_seed.is_null() {
        *out_best_seed = best_seed;
    }
    if !out_best_dist.is_null() {
        *out_best_dist = best_dist;
    }
}
