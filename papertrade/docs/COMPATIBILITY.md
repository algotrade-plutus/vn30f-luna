# Compatibility register

## Apple Silicon / QuickFIX

Wheel 0.2.8 khai báo dependency QuickFIX chỉ khi máy không phải
`Darwin arm64`. Vì vậy cài wheel thành công không có nghĩa FIX đã sẵn sàng.
QuickFIX 1.15.1 dùng inline assembly x86 `lock/xadd` trong
`C++/AtomicCount.h`, không compile native ARM.

`bootstrap.sh --with-fix` tải sdist 1.15.1, xác minh đúng đoạn source rồi thay
bằng Clang/GCC atomic builtin `__atomic_fetch_add(..., __ATOMIC_SEQ_CST)`. Script
từ chối patch nếu source khác mẫu, tránh sửa mù. Lựa chọn fallback là
REST-only, Docker Linux hoặc Rosetta.

## Defect đã xác minh trong wheel 0.2.8

| Vấn đề | Hậu quả | Workaround của ta |
|---|---|---|
| Ord type lạ map thành MARKET | lệnh ngoài ý muốn | adapter allow-list LIMIT/MARKET |
| Exit/kill-switch MARKET có `price=None` | TypeError, lệnh không gửi | crossing LIMIT có quote reference |
| Fill event thiếu symbol/side | position tracker bằng 0 hoặc sai BUY | enrich từ local order map + REST reconcile |
| `OrderRequest(sub_account=...)` | `place_order` không nhận tham số | `use_sub_account()` |
| legacy `session.place_order` default GTC | venue reject | chỉ gọi facade/adapter với DAY |
| `get_derivative_orders()` 404 | không lấy được history | `get_orders(start, end)` |
| ack time UTC, fill time có thể ICT | sai ordering thời gian | dùng tag 52/log receive time |
| SQLite recovery chỉ local | order state có thể cũ | FIX status request + REST reconcile |
| Kafka callback được gọi sync từ consumer thread | `async def` không bao giờ chạy | callback `def` ngắn, chuyển việc nặng sang queue |
| FIX engine đọc return của `header.getField()` | không nhận ra Logon, thiếu Password(554), server reset | đọc field object đã mutate trong adapter |

`SafeSignalDrivenAlpha` sửa defect position cho các fill sau khi alpha start, nhưng
REST portfolio vẫn là source reconcile bắt buộc sau restart/feed gap.

## Reproducible Linux image

`Dockerfile` pin base Python image bằng OCI digest và dùng `requirements.lock`
với toàn bộ dependency trực tiếp/transitive cố định. QuickFIX vẫn được compile
cho `linux/amd64`; smoke gần nhất đã import `quickfix==1.16.0` cùng
`paperbroker-client==0.2.8`. Thay version hoặc base digest là một release riêng,
phải build lại Linux image và chạy full acceptance suite.
