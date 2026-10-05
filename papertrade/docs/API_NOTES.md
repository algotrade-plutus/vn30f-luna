# API notes v0.2.8

## Client

`PaperBrokerClient` gộp FIX và REST. `enable_fix=None` tự phát hiện QuickFIX;
trên Apple ARM nó sẽ âm thầm thành REST-only nếu QuickFIX chưa cài. Luôn
diagnose `is_fix_enabled` trước khi chạy bot.

Order API chính: `place_order`, `cancel_order`, `request_order_status`,
`get_order_status`, `wait_for`, `is_order_done`, `recover_pending_orders`.
Account API chính: `get_cash_balance`, `get_portfolio_by_sub`, `get_orders`,
`get_transactions_by_date`, `get_max_placeable`. Chuyển sub-account bằng
`with client.use_sub_account(id)`; `OrderRequest(sub_account=...)` không được
client 0.2.8 hỗ trợ đúng.

Event handler phải nhận `**kwargs`, chạy nhanh và không block FIX thread.
Nhóm event quan trọng: `fix:logon`, `fix:logout`, `fix:logon_error`,
`fix:order:accepted`, `partial_fill`, `filled`, `canceled`, `rejected`,
`cancel_reject` và `event:handler_error`.

## Quy tắc order bắt buộc

- Venue chỉ chấp nhận `DAY`.
- Dùng chuỗi `LIMIT` hoặc `MARKET`; giá trị lạ bị code map thành MARKET.
- Tick VN30 futures 0.1, round HALF_UP.
- MARKET vẫn cần `price` số ở client, dù matching engine không dùng giá đó.
- Ưu tiên crossing LIMIT để exit; MARKET chỉ trong phiên liên tục.
- Không tự khớp lệnh hai chiều cùng account; server có self-trade reject.
- `cancel_order()` trả `(is_terminal, status)`, không phải boolean đơn.
- Reject reason thực nằm ở FIX Text tag 58.

## Kafka market data

Khởi tạo `KafkaMarketDataClient(bootstrap_servers, username, password,
env_id, merge_updates=True)`, `subscribe()` trước `start()`, và luôn `stop()`.
Merged mode giữ snapshot đầy đủ; raw mode chỉ chứa field thay đổi. Quote
có last price/qty, ba mức bid/ask, ref/ceiling/floor, OHLC, volume và spread.

Official example 08 hard-code `env_id="real"`; code của ta phải dùng
`PAPERBROKER_ENV_ID`. Kafka được ưu tiên cho multi-instrument và quote-driven
alpha; `from_paper()` của framework lại tự dựng Redis, vì vậy phải inject Kafka
client tường minh.

## Alpha framework

Chuỗi hook: `get_indicators` → `get_signals` → `plan_orders`. `Signal` là ý
tưởng; `OrderRequest` là thi hành. Multi-leg, cross-asset, iceberg và pair trade
đều thực hiện qua `plan_orders`.

Context có bars, quotes, positions, open orders, signal states, account, clock và
trigger source. Quote-driven alpha bật `trigger_on_quote=True`; cần throttle trong
`should_evaluate_on_quote` và cancel-then-place chứ không spam replace.

Client không cung cấp OCO/TP/SL hoàn chỉnh. `CloseSignal`,
`TakeProfitSignal`, `StopLossSignal` mặc định tạo MARKET `price=None`, là lỗi đã
xác minh. Dùng `SafeSignalDrivenAlpha` của ta để tạo crossing LIMIT có giá.
