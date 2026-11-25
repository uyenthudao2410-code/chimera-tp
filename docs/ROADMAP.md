# Lộ trình nghiên cứu tiếp theo (CHIMERA-TP Roadmap)

1. **FEC/Selective-NACK cho `LO_V6_JUMBO`**
   - Bổ sung parity chunks (5–10% XOR/RLNC theo lô siêu khung) hoặc Selective NACK qua kênh điều khiển `::1` để `HOLOGRAPHIC-SPLIT` chịu được mất gói ở kích thước hàng chục MB.

2. **Phát song song & Lập lịch nhận biết chi phí (Bandwidth-Aware Chaos)**
   - Chuyển từ phát tuần tự từng giọt sang worker pool song song cho các kênh nhiều gói (`GHOST_127`, `HYPERV_MCAST`, `WSL_PERMUTE`).
   - Thêm trọng số chi phí phóng đại (amplification-aware weights) trong `ChaosLaneScheduler` để chọn giữa chế độ *Tàng hình tối đa* (`GHOST_127`/`LAN_LENGTH`/`TS_V6_CHORD`) và *Hiệu năng/Tiết kiệm băng thông* (`TS_V4_1280`/`ICMP_REFLECT`).

3. **Thử nghiệm 2 máy thật (Cross-Host over Tailscale & LAN)**
   - Tách `ChimeraReceiver` và `ChimeraSender` qua cặp peer Tailscale (`TS_V4_1280` + `TS_V6_CHORD`) và hai máy cùng mạng LAN (`LAN_LENGTH`), bổ sung cơ chế trao đổi Offer qua kênh Out-of-Band / DNS TXT hoặc QUIC.

4. **Tăng tốc nhân GF(256) & khử Gauss bằng Rust / C Extension**
   - Chuyển `RLNCEncoder`/`RLNCDecoder` sang extension C/Rust (PyO3 hoặc `ctypes`) dùng SIMD (`PSHUFB`) để mở rộng giới hạn `PURE-METAMORPHIC` từ vài KiB lên hàng trăm KiB.
