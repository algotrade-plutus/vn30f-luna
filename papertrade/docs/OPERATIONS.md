# Vận hành PaperTrade hằng ngày

Tài liệu này trả lời hai câu hỏi chính: code production nằm ở đâu và bot đang
làm gì. Mọi lệnh xem trạng thái đều read-only và không đọc file secret.

## Ba lệnh dùng hằng ngày

Chạy từ repository root:

```bash
./papertrade/scripts/botctl status
./papertrade/scripts/botctl source
./papertrade/scripts/botctl compare
```

- `status` đọc snapshot đã sanitize qua SSM và in code identity, process, target,
  vị thế, working orders, freshness, activity và execution gần nhất.
- `source` in đường dẫn local chứa đúng source đã xác minh của runtime EC2.
- `compare` so sánh runtime, snapshot production và working tree đang phát triển.

Runtime hiện tại đã migration; `status` phải báo `IMMUTABLE_MATCH`, code mounts
bằng 0 và activity có transition. Release đang cài là
`ec2-baseline-observable-20260924-015c4e1b1be0`. Mode và order gate là trạng
thái vận hành có thể thay đổi; luôn đọc bằng `botctl status`, không suy từ tài
liệu này.

Clean architecture và trạng thái P1–P6 được chốt tại
[`CLEAN_ARCHITECTURE.md`](CLEAN_ARCHITECTURE.md). Refactor trong working tree
không phải code production cho tới khi có release digest mới và qua quy trình
cutover.

## Source chuẩn

| Mục đích | Đường dẫn |
|---|---|
| Source EC2 hiện đang thực thi | `papertrade/runtime-baseline/observable-source/app` |
| Snapshot runtime cũ trước migration | `papertrade/runtime-baseline/production-source/app` |
| Manifest release hiện hành | `papertrade/runtime-baseline/observable-release-manifest.json` |
| Code nghiên cứu/phát triển | `papertrade/alphas`, `papertrade/luna_core` trong working tree |

Không chép file từ working tree lên `/var/lib/algotrade/*.py`. Candidate và mọi
release sau migration phải chạy toàn bộ code trong image, pin bằng digest.

## Kiểm tra candidate local

```bash
python3 papertrade/scripts/verify_observable_baseline.py \
  --image algotrade-paper:baseline-observable-015c4e1b
python3 -m pytest papertrade/tests -q -p no:cacheprovider
```

Release production hiện tại là
`ec2-baseline-observable-20260924-015c4e1b1be0`. Nó giữ nguyên bốn file strategy
override đã capture từ EC2 và chỉ thêm identity/activity/dashboard read-only.

## Quy trình deploy đã chuẩn bị

Image phải được push thành ref bất biến dạng `repository@sha256:<digest>`. Trên
host, xem plan trước:

```bash
sudo /opt/algotrade/current/deploy/aws/release_manager.py plan \
  --manifest /path/to/release.json \
  --image-ref 'repository@sha256:<digest>'
```

`apply` chỉ chạy khi account được xác minh phẳng và đúng 0 working orders. Khi
runtime đang HOLD, controller dùng REST probe read-only thay cho snapshot cũ.
Transaction lấy deploy lock, pull/verify manifest, dừng hai service, backup
state/runtime, atomic switch `/opt/algotrade/current`, cài unit, rồi khởi động
candidate trong forced HOLD. Thành công chỉ được ghi khi heartbeat mới đúng
release, `mode=hold`, health fresh và order gate đóng.

```bash
sudo /opt/algotrade/current/deploy/aws/release_manager.py apply \
  --manifest /path/to/release.json \
  --image-ref 'repository@sha256:<digest>' \
  --bundle /path/to/algotrade-bundle
```

Journal nằm tại `/var/lib/algotrade/ops/deploy-journal.jsonl`; backup trước switch
nằm dưới `/var/lib/algotrade/backups`. Release đã cài nằm trong
`/opt/algotrade/releases/<release-id>` và `/etc/algotrade/release.env` chỉ chứa
metadata public, không chứa broker credential.

Rollback cũng luôn trở lại HOLD và yêu cầu account phẳng, không working orders:

```bash
sudo /opt/algotrade/current/deploy/aws/release_manager.py rollback <release-id>
```

Deploy không cấp quyền giao dịch. Việc đổi sang alpha, mở
`PAPERBROKER_ALLOW_ORDERS=true` hoặc tăng quantity là bước activation riêng và
cần phê duyệt ngay trước khi thực hiện.

## Đường chạy duy nhất

`algotrade-paper.service` là owner của trading container. Launcher giữ
`/var/lib/algotrade/ops/execution.lock` suốt vòng đời container. Unit
`algotrade-reentry-watchdog.service` trên EC2 hiện disabled/inactive và không
được bật lại vì script đó có thể tạo FIX client thứ hai và tự khởi động service.

Dashboard tiếp tục chỉ bind `127.0.0.1:8080` và mở qua SSM tunnel. Nó không nhận
secret, không có POST action và trading runtime không phụ thuộc vào dashboard.
