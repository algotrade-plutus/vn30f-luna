# Official examples index

15 file trong `examples/official/` được giữ nguyên bản để đối chiếu:

| # | Nội dung | Nhận xét khi tái sử dụng |
|---|---|---|
| 01 | FIX login + cash | dùng `os._exit` do QuickFIX cleanup segfault |
| 02 | nhiều order + cancel | cần chờ NEW, parse tuple cancel |
| 03 | cross-match D1/D2 | có lệnh thật trên paper; không dùng làm smoke test |
| 04 | Redis query | danh sách symbol minh hoạ cũ |
| 05 | Redis subscribe | merged vs raw snapshot |
| 06 | portfolio/orders/transactions | REST reconciliation pattern |
| 07 | max placeable | chỉ tính, không submit |
| 08 | Kafka feed | phải thay hard-coded `env_id="real"` bằng env |
| 09 | RSI 1m | alpha template, exit bằng signal ngược |
| 10 | Bollinger | StateStore chống re-entry sau restart |
| 11 | TP/SL/DD/EOD | MARKET `price=None` lỗi; EOD 14:44:30 quá trễ |
| 12 | pair spread | multi-leg không thực sự atomic ở broker |
| 13 | signal X, trade Y | override `plan_orders` |
| 14 | iceberg | chia làm N LIMIT; phần dư qty bị bỏ |
| 15 | market making | quote-driven; cancel/replace cần rate limit và reconcile |

Không chạy 02, 03, 09–15 bằng credential thật trước khi safety gate và
risk control được review. Example là tài liệu học API, không phải production bot.
