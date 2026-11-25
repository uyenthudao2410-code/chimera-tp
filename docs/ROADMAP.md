# Lộ trình nghiên cứu tiếp theo (CHIMERA-TP Roadmap)

## Đã hoàn thành (v0.2.0 &rarr; v0.5.0)
- [x] **v0.3.0**: CRC-32 từng mảnh, XOR Stripe FEC (4:1) và Selective NACK ARQ (`JCHK`/`JNCK`/`JOK!`) cho `LO_V6_JUMBO`.
- [x] **v0.4.0**: Phát song song theo từng lane (1 worker thread + bounded queue/lane) và 3 profile lập lịch (`balanced`, `stealth`, `turbo`).
- [x] **v0.5.0-alpha**: Multi-generation Segmented RLNC + `GACK` cho độ phức tạp tuyến tính $O(K)$, mở rộng `PURE-METAMORPHIC` lên `16 KiB+` dữ liệu không nén.
- [x] **v0.5.0**: Chế độ 2 tiến trình độc lập (`chimera-tp listen` / `chimera-tp connect`).

## Bước nghiên cứu tiếp theo (v0.6.0+)
1. **Thử nghiệm liên máy (Cross-Host over Tailscale & LAN)**
   - Triển khai cặp `listen`/`connect` qua hai máy thật trên Tailscale (`TS_V4_1280` + `TS_V6_CHORD`) và LAN (`LAN_LENGTH`), tự động vô hiệu hóa các lane loopback nội bộ khi địa chỉ offer khác host.
2. **Tăng tốc OTP Keystream & GF(256) bằng Rust / C Extension**
   - Chuyển `chaotic_keystream` và phép nhân/khử ma trận $GF(2^8)$ sang SIMD (`PSHUFB` / AES-NI) để đẩy `HOLOGRAPHIC-SPLIT` từ `~85 Mbps` lên ngang mức giới hạn bộ nhớ loopback.
3. **Trao đổi Offer bảo mật (Signed Out-of-Band Offer)**
   - Ký số JSON `offer` bằng khóa phiên dùng một lần hoặc QR/DNS TXT record thay cho file cục bộ.
