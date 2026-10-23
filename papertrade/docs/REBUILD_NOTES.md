# Ghi chú để build lại PaperTrade cho Calibrum

Ngày 23/10/2026. Gom từ docs chính thức (đọc lại hôm nay), tài liệu cũ trong `papertrade/docs/`, code adapter
và trạng thái EC2 đọc bằng `botctl status`. Mục đích: viết lại runtime gọn, rõ, dễ kiểm soát, chạy Calibrum C+B+M.

## 1. Hiện trạng EC2 (23/10/2026, 10:31 ICT)

| Mục | Giá trị |
|---|---|
| Release | `ec2-baseline-observable-20260924-015c4e1b1be0`, image ECR theo digest, không còn code mount |
| Alpha | `HybridGatedSupervisor` (Calendar cũ + FOMO + T+2), **không phải Calibrum** |
| Mode / order gate | `alpha` / **OPEN** |
| Vị thế | **Long 8 `VN30F2611`**, lý do `t2_hold_long`, 0 lệnh chờ |
| Lần quyết định kế | 14:24 ICT hôm nay |
| Restart | 37 lần; container dừng và chạy lại mỗi sáng khoảng 07:00 |
| Feed | futures 0 s; **spot VN30 UNKNOWN** |

Hệ quả cho việc đổi sang Calibrum:

- `release_manager.py apply` chỉ chạy khi tài khoản **phẳng và 0 lệnh chờ**. Bot đang Long 8, nên phải đóng vị thế
  trước (để bot cũ tự đóng trong cửa sổ 14:24–14:29, hoặc flatten có chủ đích), rồi mới deploy.
- Basis cần giá VN30 spot sống. Trên EC2 nguồn spot đang UNKNOWN; phải xác minh được feed spot trước khi bật Basis.

**Cập nhật 10:57 cùng ngày:** `algotrade-paper` đã `stop` và `disable` (không còn timer hay watchdog nào bật lại;
dashboard vẫn chạy). Tài khoản đã phẳng: SELL 8 `VN30F2611` LIMIT 1890,3 (bid 1890,6) khớp đủ, REST xác nhận không vị
thế, 0 lệnh chờ. Script một lần chạy trong image release, giữ `execution.lock`.

## 2. File môi trường

Secret runtime nằm ở AWS Secrets Manager `/algotrade/paperbroker` (đổi lần cuối 15/09/2026, 33 biến). Trên EC2,
`deploy/aws/render-env.sh` ghi nó ra `/run/algotrade/paperbroker.env` (mode 600). File local `papertrade/.env`
hiện **chỉ có biến DB** (`ALGOTRADE_DB_*`, `PLUTUS_DATA_ROOT`), không có biến PaperTrade nào.

Biến trên EC2, giá trị công khai ghi rõ, credential ghi `<set>`:

| Nhóm | Biến |
|---|---|
| FIX/REST | `PAPER_ACCOUNT_ID` `<set>`, `PAPER_USERNAME` `<set>`, `PAPER_PASSWORD` `<set>`, `PAPER_REST_BASE_URL=https://papertrade.algotrade.vn/accounting`, `SOCKET_HOST` `<set>`, `SOCKET_PORT=5001`, `SENDER_COMP_ID` `<set>`, `TARGET_COMP_ID=SERVER` |
| Kafka | `PAPERBROKER_KAFKA_BOOTSTRAP_SERVERS` `<set>`, `PAPERBROKER_KAFKA_USERNAME` `<set>`, `PAPERBROKER_KAFKA_PASSWORD` `<set>`, `PAPERBROKER_ENV_ID=real` |
| Spot VN30 | `VN30_SPOT_SOURCE=kafka`, `VN30_INDEX` `<set>`, `VN30_PG_HOST/DATABASE/USER/PASSWORD` `<set>`, `VN30_PG_PORT=5432`, `VN30_PG_TICKER=VN30`, `VN30_PG_POLL_INTERVAL_S=1.0` |
| Hợp đồng | `VN30F1M=HNXDS:VN30F2609` (dự phòng, đã cũ), `VN30F_ROLLOVER_MODE=auto` |
| Bot cũ | `PAPERTRADING_MODE=alpha`, `ALPHA_FACTORY=alphas.master_unified.service:build_hybrid_gated_service`, `PAPERBROKER_ALLOW_ORDERS=true`, `CALENDAR_QTY=8`, `HYBRID_GATED_QTY=8`, `CALENDAR_CANCEL_AFTER_S=8`, `CALENDAR_CROSS_POINTS=0.1`, `CALENDAR_EVAL_INTERVAL_S=2`, `ACCOUNT_SNAPSHOT_REFRESH_S=30`, `GENESIS_BASIS_MAX_AGE_S` `<set>` |

Lấy về máy local (chạy tay trong terminal, file không bị commit vì `.gitignore` đã chặn `**/.env.*`):

```bash
cd papertrade
(umask 077; aws secretsmanager get-secret-value --secret-id /algotrade/paperbroker \
  --query SecretString --output text \
  | python3 -c 'import json,sys; [print(f"{k}={v}") for k,v in json.load(sys.stdin).items()]' > .env.aws)
```

Bản mới nên đọc một file env duy nhất qua một config loader có kiểu, đổi tên biến theo Calibrum
(`CALIBRUM_QTY` thay cho `CALENDAR_QTY`/`HYBRID_GATED_QTY`), bỏ biến của bot cũ, và không suy `VN30F1M` cố định
khi đã có rollover tự động.

## 3. Sự thật về API (docs chính thức, đọc 23/10/2026)

- Client mới nhất vẫn là **`paperbroker-client 0.2.8`** (27/07/2026); không có bản mới hơn. Python 3.10+.
- Ba đường độc lập: **FIX 4.4** (đăng nhập, đặt/hủy, vòng đời lệnh), **REST** `…/accounting` (tiền, danh mục,
  lịch sử lệnh, `get_max_placeable`), **Kafka/Redis** (quote; Kafka topic `{env_id}.{exchange}.{symbol}`). Quyền
  market data cấp theo user, giá trị không có trong nút `.env` của dashboard.
- FIX: `TargetCompID=SERVER`, `HeartBtInt=30`, `ResetOnLogon/Logout/Disconnect=Y`; `SenderCompID` duy nhất cho mỗi
  client, hai client cùng ID thì xung đột phiên. Reconnect backoff 1, 2, 4, 8, tối đa 30 giây.

### Phiên giao dịch (ICT) và loại lệnh

| Khung | LIMIT (DAY) | MARKET |
|---|---|---|
| trước 09:00 | coi như không gửi được | reject "outside allowed same-day trading session" |
| 09:00–11:30 | nhận | chỉ khi đã có price band và lệnh marketable |
| 11:30–13:00 | thị trường nghỉ | reject: band unavailable |
| 13:00–14:25 | nhận | như buổi sáng |
| 14:25–14:30 | nhận | không đoán được: có thể khớp hoặc bị reject band |
| 14:30–14:45 (ATC) | chỉ LO sống sót | reject "only LO or ATC orders are accepted during the ATC session" |
| từ 14:45 | reject | reject "the market is closed for the day" |

- Chỉ `DAY`; GTC/IOC bị reject. Client chỉ phát LIMIT và MARKET; chuỗi lạ (`"LO"`, `"ATC"`, `"limit"`) thành MARKET.
- Tick 0,1, làm tròn HALF_UP trước khi gửi. MARKET vẫn cần `price` số; sàn bỏ qua giá đó khi khớp.
- `TradingSession` trong wheel mở cửa 09:15 (lịch HOSE cổ phiếu), **không dùng làm cổng gửi lệnh**.

### Reject (đọc tag 58, server không bao giờ set tag 103)

| Text (58) | Xử lý |
|---|---|
| "ceiling/floor price band is unavailable" | lùi ≥ 30 giây hoặc dùng LIMIT vượt giá; retry ngay sẽ lặp vô hạn |
| "outside allowed same-day trading session" | sai giờ hoặc sai TIF |
| "Insufficient balance to place order" | dừng, gọi `get_max_placeable` |
| "Order would match against your own resting order (self-trade prevention)" | kiểm sổ lệnh của chính mình trước |
| Cancel reject 1: "Order not found or already cancelled" | race vô hại, xử lý idempotent |
| Cancel reject 0: "Too late to cancel: order is already in auction queue" | không rút được; đừng để LO nằm qua 14:30 |

Trạng thái thấy được: PendingNew (A), New (0), PartiallyFilled (1), Filled (2), Canceled (4), Rejected (8), Expired (C,
hiếm, chỉ MARKET). Không có Replaced; không có luồng sửa lệnh, chỉ hủy rồi đặt lại.

## 4. Lỗi đã gặp và cách tránh

| # | Lỗi | Hậu quả | Cách làm đúng |
|---|---|---|---|
| 1 | Exit/kill-switch MARKET `price=None` của framework | TypeError bị nuốt, lệnh không ra sàn | luôn LIMIT có giá vượt sổ (BUY ask1 + 0,1; SELL bid1 − 0,1, chặn trần/sàn) |
| 2 | Fill event thiếu symbol/side | position tracker = 0 hoặc sai chiều | REST portfolio là nguồn vị thế; tracker local chỉ là cache |
| 3 | `OrderRequest(sub_account=…)` | `place_order` không nhận | `client.use_sub_account()` |
| 4 | `client.session.place_order` mặc định GTC | mọi lệnh bị reject | chỉ gọi `client.place_order` qua adapter |
| 5 | `cancel_order()` trả tuple `(is_terminal, status)` | `bool(...)` luôn True | unpack tuple; dùng `get_last_cancel_reject` thay vì so chuỗi |
| 6 | Hủy lệnh chưa tới New | `TimeoutError` | chờ New rồi mới hủy |
| 7 | Tag 60: ack theo UTC, fill theo ICT | lệch 7 giờ khi sắp thứ tự | dùng tag 52 hoặc giờ nhận của mình |
| 8 | `recover_pending_orders()` chỉ đọc SQLite local | lệnh đã khớp vẫn hiện như đang sống | sau đó gọi `request_order_status()` và REST `get_orders()` |
| 9 | Order store dùng chung nhiều ngày | lệnh cũ gây cancel reject | file theo ngày `orders-YYYYMMDD.db` (bản hiện tại vẫn dùng một `orders.db`) |
| 10 | Kafka callback `async def` | không bao giờ chạy | callback `def` ngắn, đẩy việc nặng sang queue |
| 11 | QuickFIX `header.getField()` trả field rỗng | thiếu Password(554), không logon | patch `_inject_admin_credentials` (đã có trong `client.py`) |
| 12 | QuickFIX trên macOS ARM | không compile | chạy trong Docker linux/amd64; local chỉ REST + Kafka |
| 13 | `get_derivative_orders()` | 404 | `get_orders(start, end)` |
| 14 | Symbol REST cố định theo tháng | hỏng âm thầm sau đáo hạn | rollover trước thứ Năm tuần 3, có test |
| 15 | `ValidatedPaperClient.__getattr__` chuyển tiếp mọi method | cancel và method khác đi vòng qua cổng an toàn | adapter mới khai báo tường minh từng method được phép, không `__getattr__` |
| 16 | Hot-patch: bind-mount 4 file Python vào container | không biết production chạy code nào (`REMOTE_DRIFT`) | chỉ deploy image theo digest; không mount code |
| 17 | Watchdog tự re-entry | có thể mở FIX client thứ hai, tự bật trading | một chủ thực thi duy nhất (flock); không timer nào được tự bật lệnh |
| 18 | Tên tham số lệch (`monday_max_gap` vs `monday_max_gap_pct`) | cấu hình không có tác dụng, không báo lỗi | config loader có kiểu, từ chối khóa lạ |
| 19 | Field health đặt tên sai (`ret_2d` thực là 20 bar) | đọc sai khi chẩn đoán | tên field theo đúng đơn vị |
| 20 | Bảng ngày nghỉ lệch giữa local và EC2 (02/05/2025, 02/01/2026) | lịch sai | một bảng lễ duy nhất, dùng chung cho research và runtime |
| 21 | Spot VN30 không có trên Kafka | Basis không có dữ liệu | lấy VN30 từ DNSE (mục 7); freshness spot chặn Basis, không chặn cả bot |
| 22 | Lệnh LIMIT vượt giá khớp ngay nhưng 8 giây không có ExecutionReport khớp (23/10/2026): client vẫn `filled=0`, gửi hủy, nhận cancel reject "Order not found or already cancelled" | nếu tin trạng thái FIX local mà gửi lại, sẽ bán gấp đôi và thành Short | trước mỗi lần gửi lại, đọc vị thế REST; cancel reject 1 nghĩa là phải hỏi lại trạng thái, không phải "chưa khớp" |

## 5. Mẹo đã kiểm chứng

- Thoát và đảo chiều bằng LIMIT vượt giá vài tick, trong cửa sổ đặt lệnh liên tục: khớp như MARKET mà không dính
  reject band hay ATC.
- Đảo Short → Long: đóng về 0, chờ REST xác nhận phẳng, rồi mới mở chiều mới.
- Có lệnh chờ thì không đặt lệnh mới; lệnh quá 8 giây thì hủy.
- Gọi `get_max_placeable` trước mỗi lệnh; thiếu sức mua thì fail closed, không tự giảm khối lượng.
- Kafka offset `latest` khi chạy thật, `earliest` khi smoke test decoder.
- Ghi log có allow-list; không bao giờ `dict(os.environ)` hay stringify message Logon.
- `fix_message_log=False` để raw log FIX không chứa credential.
- Lỗi query remote không được biến thành danh sách rỗng: phân biệt "không có" với "không biết".

## 6. Arena chấm khác Plutus

| | Arena PaperTrade | Lab (Plutus) |
|---|---|---|
| Vốn đầu | 500 triệu | 100 triệu / hợp đồng |
| Lãi suất phi rủi ro | 7%/năm, 252 ngày | 3%/năm, 250 ngày |
| Sortino | so với benchmark VNINDEX/VN30 | so với ngưỡng 3% |
| IR | so với VNINDEX/VN30 | so với mua giữ VN30F1M |
| Ký quỹ | 25% cố định | theo ngày (VSD) |
| Turnover | gross, close, round trips, margin usage | không tính |

Khi đối chiếu kết quả paper với backtest, phải tính lại bằng cùng hằng số, không so trực tiếp số trên dashboard.

## 7. Dữ liệu tín hiệu từ DNSE

API chart công khai của DNSE (`https://api.dnse.com.vn/chart-api/v2/ohlcs/{derivative|index}`, `symbol=VN30F1M` hoặc
`VN30`, `resolution=1`), không cần đăng nhập, là đúng nguồn của dữ liệu nghiên cứu. Đo trong phiên 23/10/2026:

| | VN30F1M | VN30 |
|---|---|---|
| Một request | 100–250 ms | khoảng 100 ms |
| Nến 1 phút xuất hiện sau mốc đóng | thường 1–2 s, có lần 8–15 s | 1–2 s |
| Nến đang chạy | không trả về | không trả về |

- Dùng DNSE cho tín hiệu (C, B, M, vote, stop) để live và backtest cùng nguồn, cùng định nghĩa nến; spot VN30 cho
  Basis cũng lấy ở đây. PaperTrade Kafka chỉ dùng lấy bid/ask để định giá LIMIT, vì lệnh khớp ở sàn PaperTrade.
- **Bẫy:** các request liên tiếp có thể trả dữ liệu cũ hơn (nến cuối 10:50 rồi lại 10:49), có lẽ do nhiều cache sau
  load balancer. Không cho thời gian nến lùi; chỉ chốt nến khi hai lần đọc liên tiếp trùng nhau; quá khoảng 30 s sau mốc
  phút mà chưa có nến thì báo stale và không ra quyết định mới.
- Nếu cần realtime hơn: DNSE có market data qua MQTT, cần tài khoản DNSE.

## 8. Yêu cầu cho runtime Calibrum

| Phần | Backtest đang làm | Live cần |
|---|---|---|
| Dữ liệu | nến 1 phút DNSE, gộp 10 và 30 phút | poll nến 1 phút DNSE (mục 7), gộp đúng như lab |
| Calendar MTW | nến 10 phút, bỏ nến ATC; IB 3 nến, cửa sổ thứ Hai tới 13:00, vào 14:20, thoát 10:00 | cùng code `calendar_mtw_signal_source.py` |
| Basis | z-score F − VN30 trên W = 60 nến 30 phút, khởi động lại mỗi hợp đồng; stop 14 điểm | spot VN30 sống; warm-up 60 nến của hợp đồng mới (khoảng 6 phiên) |
| Momentum | Ridge 5 đặc trưng, λ = 1, θ = 0,232; giữ 2–8 nến; stop 10 điểm | hệ số đông cứng từ `momentum_model.json`; giá cộng dồn qua roll cho đặc trưng |
| Vote | `sign(C + B + M)`, 1 hợp đồng / 100 triệu | qty từ config, mặc định 1 |
| Khớp | giá close nến tín hiệu; stop xét ở close mỗi phút | LIMIT vượt giá ngay sau khi nến đóng; đo trượt giá thật so với 0,4 điểm/chiều |
| Đáo hạn | phẳng cả phiên đáo hạn; đóng ở nến cuối hợp đồng | cùng luật; rollover sang mã tháng kế |

Nguyên tắc dựng lại:

1. **Một lõi chiến lược chung.** Runtime gọi đúng các hàm trong `src/` mà backtest dùng, chỉ cấp dữ liệu khác. Có
   test parity: replay nến 1 phút một tuần qua runtime ra đúng vị thế như lab.
2. **Lớp thực thi mỏng.** Lõi trả về target `{-q, 0, +q}`; lớp thực thi hội tụ vị thế tới target bằng LIMIT vượt giá,
   một lệnh tại một thời điểm, REST là nguồn sự thật.
3. **Một adapter broker tường minh.** Mỗi method mutate (`place`, `cancel`) đi qua cùng cổng; không `__getattr__`.
4. **Trạng thái điều khiển rõ ràng:** HOLD → OBSERVE → ACTIVE, cùng HALT bền vững. `PAPERBROKER_ALLOW_ORDERS=false`
   chặn mọi submit.
5. **Theo dõi từng sleeve.** Ghi target của C, B, M và vote mỗi lần quyết định, để giám sát như mentor yêu cầu và so
   với backtest. Mốc cảnh báo: drawdown dài hơn 128 phiên hoặc sâu hơn khoảng 13%.
6. **Một lịch giao dịch.** Lịch lễ và luật đáo hạn dùng chung `src/domain/strategy/calendar_rules.py`.

## 9. Việc cần làm trước khi deploy

- [ ] Lấy `.env.aws` về local (lệnh ở mục 2).
- [x] Dừng bot cũ và đóng 8 hợp đồng Long (23/10/2026 10:57).
- [x] Nguồn spot VN30: DNSE (mục 7), trễ 1–2 s.
- [ ] Tìm nguyên nhân container dừng mỗi sáng khoảng 07:00 (37 lần restart).
- [ ] Quyết định qty cho Calibrum trên tài khoản paper (backtest: 1 hợp đồng / 100 triệu).
- [ ] AWS CLI local đang dùng credential **root**; nên tạo IAM user hoặc role quyền tối thiểu cho vận hành.
