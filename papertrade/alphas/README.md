# Alpha runtime

Mỗi alpha nên có một package riêng, config không chứa secret và state path
riêng theo bot/ngày. Dùng `SafeSignalDrivenAlpha` thay cho
`paperbroker.alpha.SignalDrivenAlpha` để exit luôn có giá LIMIT hợp lệ và fill
được bổ sung symbol/side trước khi cập nhật position.

Quy ước bắt buộc:

1. Chỉ `LIMIT`, `DAY`, tick 0.1; MARKET chỉ dùng qua adapter có reference price.
2. Calendar quyết định trong 14:24–14:29 ICT bằng crossing LIMIT; không gửi
   lệnh mới từ 14:30 để tránh phụ thuộc cơ chế ATC.
3. Kiểm tra `get_max_placeable` và working order trước mỗi batch.
4. Reconcile position qua REST, không tin duy nhất fill event của client 0.2.8.
5. Calendar supervisor giữ hợp đồng hiện hành tới hết phiên đáo hạn, bắt buộc
   flatten tại quyết định cuối, rồi tự chuyển mã kế tiếp sau 15:00 ICT. Nếu mã
   cũ chưa phẳng thì rollover bị chặn và runtime fail closed.

## HybridGated runtime

Runtime production cho `PS_V30_Vien_hybrid_gated` nằm tại
`alphas.master_unified` để thay thế alpha cũ mà không chạy thêm service thứ hai.
Factory ưu tiên là `alphas.master_unified.service:build_hybrid_gated_service`;
`build_unified_service` được giữ làm alias tương thích cho cấu hình AWS hiện tại.

Signal engine pure-Python phải parity với research trên từng bar: calendar dùng
phiên giao dịch thật cho SOM2/next session, FOMO tree dùng đủ ret-2/ret-5,
SMA120 và ATR20, còn T+2 chỉ chuyển trạng thái sau khi nến 30 phút hoàn tất.
Target đã quyết định được giữ nguyên giữa các cửa sổ; hard veto của gatekeeper
không cho T+2 mở lại Long trong phiên bị chặn.
