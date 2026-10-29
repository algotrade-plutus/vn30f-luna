# Calibrum paper trading

Chạy Calibrum C+B+M trên PaperTrade Algotrade, 10 hợp đồng VN30F1M, từ một EC2 ở Singapore. Ghi chú thiết kế, lỗi đã
gặp và quyết định: [docs/REBUILD_NOTES.md](docs/REBUILD_NOTES.md).

## Cách nó chạy

```
DNSE nến 1 phút (F + VN30) ─► calibrum/feed.py      chốt nến khi 2 lần đọc trùng nhau, không bao giờ lùi
                              src/lab/calibrum_1m/live.py   target C, B, M và vote bằng đúng code backtest
                              calibrum/execution.py  vote → tối đa một lệnh: chặn, cắt ký quỹ, đóng, mở
                              calibrum/broker.py     cổng duy nhất tới FIX/REST, vá lỗi SDK 0.2.8
                              calibrum/quotes.py     bid/ask từ Kafka, chỉ để định giá lệnh
                              calibrum/runner.py     vòng lặp mỗi 2 giây, journal.jsonl, health.json
```

- **Mỗi ngày giao dịch:** `calibrum.timer` khởi động `calibrum.service` lúc 08:30 ICT thứ Hai đến thứ Sáu; service cũng
  bật khi EC2 boot. Runner chờ tới 08:30 nếu khởi động sớm, thoát ngay nếu là ngày nghỉ, thoát lúc 15:00. Lỗi thì
  systemd chạy lại sau 60 giây.
- **Lệnh:** LIMIT vượt giá 0,3 điểm trong phiên liên tục, giá trần/sàn trong ATC; một lệnh một lúc; hủy sau 8 giây; đọc
  REST trước mỗi quyết định. Mở `min(10, sức mua)`; thiếu ký quỹ thì cắt vừa đủ; đảo chiều thì về 0 trước.
- **Chặn lệnh** (ghi vào journal khi lý do đổi): file HALT, FIX rớt, feed DNSE cũ hơn 90 giây trong phiên liên tục,
  vị thế ở mã khác. Khởi động mà tài khoản còn lệnh chờ thì runner từ chối chạy.
- **Bí mật:** AWS Secrets Manager `/algotrade/paperbroker`, `deploy/render-env.sh` ghi ra `/run/algotrade/` (mode 600).
  Nút vận hành ở `/etc/calibrum/calibrum.env`: `CALIBRUM_MODE`, `CALIBRUM_QTY`, `CALIBRUM_ALLOW_ORDERS`.

## Vận hành (từ máy có AWS CLI)

| Việc | Lệnh |
|---|---|
| Xem trạng thái, health, journal | `make papertrade-status` |
| Mở dashboard web (chỉ đọc) tại http://localhost:18080, qua tunnel SSM; Ctrl-C để đóng | `make papertrade-dashboard` |
| Dừng lệnh mới ngay và dừng runner (vị thế giữ nguyên, HALT còn qua các ngày sau) | `make papertrade-stop` |
| Bỏ HALT và chạy lại | `make papertrade-resume` |
| Triển khai code đã commit | `make papertrade-deploy` |
| Thử đường gửi lệnh (1 hợp đồng mua rồi bán, cần tài khoản phẳng) | `bash papertrade/ops/calibrum_smoke.sh` |

`push_build.sh` gửi code của commit hiện tại lên EC2 qua SSM, build `calibrum-paper:<git sha>` trên nền image PaperTrade
đã có QuickFIX, rồi `deploy/install.sh` ghi release vào `/etc/calibrum/release.env` (giữ image trước đó để rollback) và
cài unit. Nó không khởi động runner; timer làm việc đó.

Trên EC2: state ở `/var/lib/calibrum/live/` (`journal.jsonl`, `health.json`, `HALT`, log và order store SDK theo ngày).

Dashboard (`calibrum/dashboard.py`, unit `calibrum-dashboard.service`) chạy cùng image với runner nhưng không có
secret: chỉ đọc `health.json` và `journal.jsonl` (mount read-only), không gọi broker, chỉ nghe ở `127.0.0.1:8080`
trên EC2. Trang hiện trạng thái, vị thế, tín hiệu C/B/M/vote của nến vừa đóng, độ trễ dữ liệu, dải tín hiệu trong
phiên, giá trị tài khoản ở các lúc đứng phẳng (lúc đó tiền mặt là toàn bộ tài khoản), bảng lệnh và journal.
Giá vào lệnh chỉ là xấp xỉ (giá LIMIT ∓ 0,3 điểm); lãi lỗ chính xác vẫn xem trên trang PaperTrade.

Bản công khai ở https://calibrum.binarysearch.id.vn: cùng trang, nhưng không có mã lệnh và nội dung lỗi. Dashboard
phục vụ bản này ở `127.0.0.1:8081`; `calibrum-tunnel.service` chạy connector `cloudflared` (tunnel `calibrum`), chỉ
gọi ra Cloudflare, không mở cổng nào trên EC2. Credentials của tunnel nằm ở SSM `/calibrum/cloudflared-credentials`
(SecureString); thiếu parameter đó thì unit thoát êm và dashboard chỉ còn bản riêng. Container dashboard bị giới hạn
0,5 CPU và 640 MB, và mỗi khoảng ngày chỉ tính lại tối đa một lần mỗi 15 giây, để người xem không làm chậm runner.

## Test

`make papertrade-test`: planner, feed, runner (giả lập broker) và parity giữa target live với backtest (cần cache DNSE).
