# AWS runtime architecture

## Chọn kiến trúc

Runtime đầu tiên dùng một EC2 `x86_64` tại `ap-southeast-1` (Singapore),
Amazon Linux 2023, Docker và systemd. Đây là suy luận từ vị trí người dùng
Việt Nam và endpoint broker Singapore; đo RTT thực tế trước khi cố định.

Khởi điểm hợp lý: `t3.small`, 20 GB gp3. Bot chỉ mở kết nối outbound
tới HTTPS 443, FIX 5001 và Kafka 9092. Security Group không có inbound;
quản trị qua SSM Session Manager. Nếu broker whitelist IP, gắn Elastic IP và
chấp nhận phí public IPv4; nếu không whitelist thì public IP động vẫn đủ.

```text
Secrets Manager --IAM/GetSecretValue--> EC2 systemd
                                        |
                                        v
                               Docker linux/amd64
                               FIX + REST + Kafka
                                        |
                         bind mounts: runtime/state/logs
```

## Secrets

Tạo một JSON secret `/algotrade/paperbroker` theo
`deploy/aws/secret.example.json`. Không đưa credential dashboard
`ALGOTRADE_WEB_*` lên runtime vì bot không cần chúng.
Instance profile chỉ cần `secretsmanager:GetSecretValue` trên đúng ARN secret và
`AmazonSSMManagedInstanceCore`; policy tối thiểu có tại
`deploy/aws/iam-policy.example.json`. Không gắn AWS access key vào `.env`.

`render-env.sh` lấy secret qua IAM role, validate key, ghi atomically vào
`/run/algotrade/paperbroker.env` với mode 600. File local `.env` không được copy
lên EC2.

## Provision/bootstrap lần đầu

1. Tạo EC2 AL2023 x86_64, gắn IAM role SSM + read duy nhất secret, SG no-ingress.
2. Vào máy qua Session Manager, copy code này tới `/opt/algotrade`.
3. Chạy `sudo deploy/aws/install-host.sh`.
4. Chạy `sudo deploy/aws/build-and-install.sh`. Bootstrap này build tag local và
   luôn ép `hold`/order gate đóng; các lần cập nhật sau dùng release digest.
5. Kiểm tra `systemctl status algotrade-paper` và
   `docker inspect --format '{{.State.Health.Status}}' algotrade-paper`.

Mặc đị container ở `PAPERTRADING_MODE=hold`, chỉ ghi heartbeat và không
kết nối broker. Sau smoke test, đặt `PAPERTRADING_MODE=alpha` và
`ALPHA_FACTORY=alphas.<module>:build_alpha` trong Secrets Manager. Safety gate
`PAPERBROKER_ALLOW_ORDERS` vẫn phải giữ `false` cho tới lần duyệt cuối.

## Release bất biến và rollback

Production update dùng image ECR dạng `repository@sha256:<digest>`, manifest
nhúng tại `/app/release.json`, release bundle dưới
`/opt/algotrade/releases/<release-id>` và con trỏ atomic
`/opt/algotrade/current`. Không bind-mount file Python vào `/app`.

Xem code và trạng thái hiện hành từ máy quản trị:

```bash
./papertrade/scripts/botctl status
./papertrade/scripts/botctl source
./papertrade/scripts/botctl compare
```

Trên EC2, `deploy/aws/release_manager.py plan` chỉ đọc metadata/snapshot.
`apply` yêu cầu account snapshot xác minh phẳng và working orders bằng 0, lấy
deploy lock, verify manifest trong image, dừng service, backup state/runtime,
switch release và chỉ khởi động ở forced HOLD. Journal nằm tại
`/var/lib/algotrade/ops/deploy-journal.jsonl`. `rollback <release-id>` cũng giữ
HOLD và không tự cấp quyền đặt lệnh. Runbook chi tiết ở `docs/OPERATIONS.md`.

`algotrade-paper.service` giữ execution lock suốt vòng đời container. Không bật
watchdog/script khác có thể tạo FIX client thứ hai hoặc tự khởi động trading.

## Vận hành

- systemd restart container sau crash; Docker healthcheck đọc heartbeat dưới 45 giây.
- `runtime/health.json` mang release/runtime instance identity;
  `runtime/activity.jsonl` chỉ ghi transition đã whitelist và xoay vòng 5 MB × 3 file.
- Docker stdout/stderr xoay vòng tối đa 5 file × 10 MB để không ăn đầy EBS khi
  treo nhiều tháng.
- CloudWatch theo dõi `StatusCheckFailed_System` mỗi phút và gọi EC2 recovery
  sau 2 lần lỗi liên tiếp. Alarm production hiện dùng tên
  `algotrade-paper-system-recovery`.
- SQLite order state, alpha state và log nằm trên bind mount của EC2, không
  nằm trong writable layer của container.
- Container non-root, read-only root filesystem, `/tmp` tmpfs.
- Mỗi deploy phải smoke Kafka `VN30F2609`, REST account, FIX login; không submit.
- Sau restart: reconcile local SQLite với FIX status request và REST portfolio/orders.
- Báo động nếu feed stale, FIX logout, healthcheck fail, position drift, reject
  liên tiếp hoặc còn position sau 14:25 ICT.

Tạo lại alarm tự phục hồi (thay `<instance-id>` nếu dựng máy mới):

```bash
aws cloudwatch put-metric-alarm \
  --region ap-southeast-1 \
  --alarm-name algotrade-paper-system-recovery \
  --alarm-description "Recover PaperTrade EC2 after two consecutive system status-check failures" \
  --namespace AWS/EC2 \
  --metric-name StatusCheckFailed_System \
  --dimensions Name=InstanceId,Value=<instance-id> \
  --statistic Maximum \
  --period 60 \
  --evaluation-periods 2 \
  --datapoints-to-alarm 2 \
  --threshold 1 \
  --comparison-operator GreaterThanOrEqualToThreshold \
  --treat-missing-data notBreaching \
  --alarm-actions arn:aws:automate:ap-southeast-1:ec2:recover
```

## Calendar runtime

Factory production là `alphas.calendar.service:build_calendar_service`. Runtime
dùng Kafka `latest`, REST portfolio làm source-of-truth sau restart, settle mọi
order còn sống trong SQLite trước khi subscribe, và chỉ hội tụ vị thế trong cửa
sổ 14:24–14:29 ICT. `CALENDAR_QTY` mặc định 1 và có hard cap 10; trước mỗi
lệnh, runtime vẫn hỏi `get_max_placeable` và fail closed nếu broker trả về thấp
hơn toàn bộ target.

`VN30F_ROLLOVER_MODE=auto` suy front month bằng thứ Năm lần ba: giữ mã cũ tới
15:00 ngày đáo hạn, ép target mã cũ về 0 trong quyết định cuối, rồi restart child
alpha với mã tháng kế. Mọi vị thế khác mã đang quản lý làm startup/rollover fail
closed. Bảng lễ mới phủ tới hết 2027 và phải được cập nhật trước năm 2028.

## Private account dashboard

Trading runtime xuất `runtime/account.json` theo whitelist mỗi 30 giây. Snapshot
chỉ có balance, margin ratio, capacity, position, orders và transactions; không
có username, account ID, REST/FIX/Kafka credential. Container dashboard chỉ
mount runtime ở chế độ read-only, không nhận file secret và không có endpoint
ghi hay đặt lệnh.

Dashboard cũng đọc `health.json` và `activity.jsonl` để hiển thị release đang
chạy, mode/order gate và các thay đổi target/position/health gần đây. Writer và
reader đều lọc trường nhạy cảm; dashboard không render raw application log.

Host chỉ publish dashboard lên loopback `127.0.0.1:8080`. Không mở Security
Group. Truy cập từ máy quản trị bằng SSM tunnel:

```bash
aws ssm start-session \
  --target <instance-id> \
  --document-name AWS-StartPortForwardingSession \
  --parameters '{"portNumber":["8080"],"localPortNumber":["8080"]}'
```

Sau đó mở `http://localhost:8080`. Dashboard chết không ảnh hưởng container
trading; systemd quản lý và restart hai service độc lập.

Trên máy quản trị của dự án này có thể dùng shortcut tương đương:

```bash
./scripts/open_dashboard.sh
```
