# PaperTrade — AWS và vận hành

Phạm vi: thiết kế/runbook local đã lưu, rà 09/09/2026.
Không ghi instance ID, image hiện chạy hoặc trạng thái deploy nếu chưa kiểm chứng.

## Kiến trúc vận hành

- Repo có cấu hình EC2 Linux x86-64, Docker và systemd; quản trị bằng SSM.
- Secrets Manager → IAM của instance → file env runtime. Context chứa tên biến
  và đường dẫn tham chiếu, không chứa giá trị credential.
- Order state/alpha state/log cần nằm trên persistent mount; không coi layer của
  container là nơi lưu state bền vững.
- Trading và dashboard là hai service. Dashboard đọc snapshot đã lọc thông tin,
  bind loopback và truy cập qua tunnel; không đưa API đặt lệnh vào dashboard.
- Source ở laptop, image build và image/service đang chạy là ba phiên bản riêng.
  Kiểm `ALPHA_FACTORY` thực tế; runbook cũ ghi Calendar không chứng minh service
  hiện tại vẫn là Calendar.
- Nguồn spot VN30 có thể route qua PostgreSQL read-only (`VN30_SPOT_SOURCE=postgres`)
  với các biến `VN30_PG_*` trong secret runtime; không ghi credential vào repo và
  không coi một dòng quote cũ là feed live.

## Khi xử lý vận hành

1. Ghi nhận image/factory và cấu hình liên quan đã redacted, tình trạng service/feed.
2. Kiểm REST account/working orders, FIX login, market data của đúng hợp đồng.
3. Đối chiếu state sau restart; kiểm capacity/rollover trước khi hội tụ target.
4. Nếu task gồm deploy, dùng scripts hiện có và giữ đường rollback đúng image/state.
   Không reset state để làm healthcheck xanh.

Healthcheck/heartbeat chỉ chứng minh tiến trình có hoạt động; không thay kiểm tra
feed freshness, order rejects, fills hoặc drift giữa target và position.
Không dùng một rule “flat 14:25” của bot cũ để áp cho strategy chủ động giữ overnight.

## DO / DON'T

```python
# DO: log field cần chẩn đoán, với allow-list rõ ràng.
log_record = {"image": image_id, "factory": factory, "feed_age_s": feed_age_s}

# DON'T: environment có thể chứa credential REST/FIX/Kafka.
log_record = dict(os.environ)
```

Các điểm vào code: [deploy/aws](../../deploy/aws),
[run-container.sh](../../deploy/aws/run-container.sh),
[healthcheck](../../scripts/container_healthcheck.py),
[diagnose](../../scripts/diagnose.py),
[dashboard tunnel](../../scripts/open_dashboard.sh).

## Monitor nhanh

- Dashboard private đọc `runtime/health.json` và `runtime/account.json`, refresh
  mỗi 5 giây qua SSM tunnel. Nó hiển thị target hiện tại/lý do, target calendar
  kế tiếp, tuổi feed/REST/basis, vị thế và lệnh gần đây; không có endpoint ghi.
- [check_live_alpha.sh](../../scripts/check_live_alpha.sh)
  là probe SSM read-only cho terminal, in JSON đã lọc gồm target, reason, vị thế,
  lệnh đang chờ, health và trạng thái spot/basis. Không đọc rendered environment
  hoặc state DB.

Nguồn chi tiết: [AWS runbook](../../docs/AWS_DEPLOYMENT.md),
[platform snapshot](../../docs/PLATFORM.md).
