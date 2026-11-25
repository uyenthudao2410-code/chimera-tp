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
