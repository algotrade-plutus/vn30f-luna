# PaperTrade — API, signal và execution

Phạm vi: adapter trong repo và ghi chú `paperbroker-client==0.2.8`.
Rà source/tài liệu 09/09/2026; không xác nhận trạng thái broker đang chạy.

## Ranh giới

- Output `Position` không phải lệnh broker. Research nằm trong `alphas/`;
  tích hợp broker ở `papertrade/`.
- FIX: login/order lifecycle. REST: account, capacity, portfolio/orders.
  Kafka/Redis: market feed. Username web, FIX account và sub-account không đồng nhất.
- Chuỗi framework: `get_indicators → get_signals → plan_orders`.
  Dùng adapter `SafeSignalDrivenAlpha` cho các alpha theo kiến trúc hiện có.
- `master_unified/service.py` chỉ còn HybridGated; `build_unified_service()` là
  alias tương thích trỏ cùng factory Hybrid.

## Quy tắc thực thi

- Phân biệt target, position được broker xác nhận, working orders và fills.
  Sau restart phải reconcile; local state không đủ chứng minh vị thế thực.
- Adapter hiện ưu tiên crossing LIMIT có giá hợp lệ, `DAY`, tick 0.1.
  Không copy exit MARKET `price=None` từ ví dụ SDK 0.2.8.
- Kiểm capacity và pending order trước mỗi bước. Đảo Short → Long có thể cần
  đóng phần Short, nhận fill/reconcile rồi mở Long; không coi delta toàn phần là
  lệnh chắc chắn đủ sức mua.
- Request gửi được chưa phải accepted/filled. Theo dõi status, cumulative fill,
  leaves quantity và reject reason. Cancel acknowledgment chưa cho phép suy fill bằng 0.
- Trạng thái terminal phải xét canonical status; mô tả chữ/leavesQty có thể lệch nhau.
- Signal clock, cửa sổ gửi lệnh, ATC và rollover là các luật riêng. Kiểm schedule
  đúng service; không áp giờ của Calendar cho mọi alpha hoặc hardcode mã tháng cũ.
- Kafka callback dùng `def`, xử lý nhanh/đẩy queue; SDK ghi nhận không await callback async.

## DO / DON'T

```python
# DO: trong luồng execution đã được yêu cầu, xử lý đúng return API.
is_terminal, status = client.cancel_order(order_id)

# DON'T: tuple không rỗng vẫn truthy khi phần tử đầu là False.
is_terminal = bool(client.cancel_order(order_id))
```

Khi đổi sub-account dùng `client.use_sub_account(...)` theo adapter/version hiện có;
không tự truyền trường `sub_account` vào OrderRequest chỉ vì tên có vẻ hợp lý.
Nhận timestamp có timezone và chuyển về giờ sàn; ack UTC/fill ICT từng được ghi nhận.

## Đọc code mẫu theo mục đích

[Index ví dụ](../EXAMPLES.md): 01 login, 06 account,
07 capacity, 08 Kafka; 09–15 là ví dụ chiến lược/order. Đọc
[compatibility](../COMPATIBILITY.md) trước khi tái sử dụng.
Không chạy ví dụ có đặt lệnh chỉ để xem interface.

Nguồn: [API notes](../API_NOTES.md),
[SafeSignalDrivenAlpha](../../algotrade_adapter/safe_alpha.py),
[service](../../alphas/master_unified/service.py).
