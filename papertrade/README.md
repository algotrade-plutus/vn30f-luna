# Algotrade Paper Trading

Khu vực tách biệt để chạy alpha trên PaperTrade Algotrade. Code nghiên cứu trong
`alphas/` của repo không import trực tiếp `paperbroker`; adapter tại đây là biên
giới giữa signal của ta và FIX/REST/Kafka của họ.

## Bố cục

- `alphas/`: alpha dành riêng cho paper trading.
- `algotrade_adapter/`: validation, safety gate và workaround cho client 0.2.8.
- `dashboard/`: web monitor private, read-only từ snapshot đã loại credential.
- `examples/official/`: 15 file `.py` tải nguyên bản từ docs ngày 2026-08-24.
- `docs/`: sổ tay API, vận hành và các lỗi đã xác minh.
- `scripts/`: cài môi trường và smoke test chỉ-đọc.
- `vendor/`: wheel chính thức `paperbroker-client==0.2.8`.

`.env` chứa credential thật, đã bị git-ignore. Không copy credential vào
source, log, notebook hay commit.

## Khởi tạo

```bash
cd papertrade
./scripts/bootstrap.sh
source .venv/bin/activate
python scripts/diagnose.py
python scripts/smoke_kafka.py --seconds 15 --offset earliest
```

Trên macOS Apple Silicon, lệnh mặc đị cài REST + Kafka. Muốn bật FIX native:

```bash
./scripts/bootstrap.sh --with-fix
python scripts/smoke_fix_login.py
```

Smoke test không gửi lệnh. `PAPERBROKER_ALLOW_ORDERS=false` là khoá cứng ở
adapter; chỉ đổi sau khi login, account reconcile, feed và session gate đều đạt.
`earliest` xác minh topic/decoder bằng record đã có; dùng `--offset latest`
để kiểm tra tick live và chấp nhận có thể không có update trong cửa sổ ngắn.

Xem [docs/PLATFORM.md](docs/PLATFORM.md), [docs/API_NOTES.md](docs/API_NOTES.md)
và [docs/COMPATIBILITY.md](docs/COMPATIBILITY.md) trước khi viết bot.

## Mở private dashboard

Dashboard không public Internet. Từ máy đã có AWS CLI + Session Manager plugin:

```bash
./scripts/open_dashboard.sh
```

Script mở `http://localhost:8080` và giữ SSM tunnel cho tới khi bấm `Ctrl+C`.
Có thể truyền port khác, ví dụ `./scripts/open_dashboard.sh 18080`.
