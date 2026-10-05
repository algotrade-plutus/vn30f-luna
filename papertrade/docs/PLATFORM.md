# PaperTrade platform handbook

Nguồn chính thức đã đọc ngày 2026-08-24:

- <https://papertrade.algotrade.vn/docs/>
- <https://papertrade.algotrade.vn/docs/fix-guide/>
- <https://papertrade.algotrade.vn/docs/order-placement/>
- <https://papertrade.algotrade.vn/docs/api-reference/>
- <https://papertrade.algotrade.vn/docs/examples/>
- <https://papertrade.algotrade.vn/docs/changelog/>
- <https://papertrade.algotrade.vn/docs/formulas/>

## Kiến trúc

Hệ thống có ba đường độc lập:

1. FIX 4.4/QuickFIX: login, submit, cancel và order lifecycle.
2. REST: cash, portfolio, order/transaction history, max placeable.
3. Kafka/Redis: quote market data. Kafka topic có dạng
   `{env_id}.{exchange}.{symbol}`.

Web trader, environment, FIX account, sub-account và alias là các khái niệm
khác nhau. Username đăng nhập dashboard không được tự suy diễn thành
`PAPER_USERNAME`; phải copy config từ nút `.env` của account.

## Cài đặt được pin

- Wheel: `paperbroker-client==0.2.8`.
- Linux runtime pin `quickfix==1.16.0`; macOS ARM bootstrap dùng bản 1.15.1
  đã patch vì 1.16.0 không có wheel ARM sẵn.
- Container runtime dùng Python 3.11 trên Alpine 3.24/musl, chỉ mang thêm
  `libstdc++` cần cho QuickFIX; build stage không đi vào image chạy thật.
- SHA-256: `f0ecee6e492475edeb7b2fe46caf3adda21f3cf5cfc3d223a5a60db55147214b`.
- Python package metadata cho phép Python `>=3.8`; docs khuyên Python 3.10+.
- 0.2.8 sửa cancel reject: rollback `PendingCancel`, cancel ID duy nhất và
  có `request_order_status()`/`get_last_cancel_reject()`.

## Phiên giao dịch ICT

| Khoảng | Trạng thái |
|---|---|
| trước 09:00 | không gửi lệnh |
| 09:00–11:30 | liên tục |
| 11:30–13:00 | nghỉ trưa |
| 13:00–14:30 | liên tục |
| 14:30–14:45 | ATC, chỉ LO sống sót |
| từ 14:45 | đóng cửa |

Bot của ta ngừng entry và bắt đầu flatten trước 14:25. Không chờ
tới 14:44:30 như official example 11.

## FIX lifecycle

`PendingNew` chưa phải accepted. Chờ `New`; sau đó mới cancel hay coi order
là working. Theo dõi `CumQty`, `LeavesQty`, partial fills và text tag 58. Mỗi
request phải có `ClOrdID` duy nhất; cancel dùng `OrigClOrdID`, không dùng
server `OrderID` thay thế.

Reconnect dùng backoff 1, 2, 4, 8, tối đa 30 giây. Sau restart, local SQLite
chỉ khôi phục ý định; phải query status FIX và REST `get_orders()`.

## Arena

Hệ số futures là 100.000 VND/điểm, margin ratio 25%, risk-free 7%/năm,
252 ngày/năm và initial balance 500 triệu. Dashboard tính Sharpe, MDD,
Sortino, IR, turnover, round trips và margin usage turnover; khi đối chiếu local
phải dùng cùng constants.
