# Luna — VN30F research

Luna là chiến lược nghiên cứu cho hợp đồng tương lai VN30 (VN30F). Dữ liệu
lịch sử được đọc trực tiếp, chỉ-đọc từ PostgreSQL `algotradeDB`; simulator
`plutus.market.session.ExchangeSession` chịu trách nhiệm về lệnh, fill, phí,
variation margin, đáo hạn và kiểm soát margin.

## Phạm vi repository

- `src/`: Clean Architecture cho Luna, PostgreSQL adapters và Plutus runner.
- `scripts/`: data audit, In-Sample, sensitivity, Out-of-Sample và biểu đồ.
- `config/`: cấu hình frozen của Luna.
- `tests/`: test thuộc Luna.
- `plutus/`: Git submodule được pin tới engine upstream; không vendored source.

Không đưa dữ liệu thị trường, secrets, reports sinh ra hay tài liệu làm việc
nội bộ vào repository này. PostgreSQL là nguồn dữ liệu cho các lần chạy mới.

## Cài đặt

```bash
git clone --recurse-submodules https://github.com/Viendeptrai1/luna-vn30f.git
cd luna-vn30f
cp .env.example .env
# điền các biến ALGOTRADE_DB_* bằng tài khoản read-only
make setup
```

Nếu đã clone mà thiếu engine:

```bash
git submodule update --init --recursive
```

Yêu cầu Python 3.12 và `uv`. Không commit `.env`.

## Chạy

```bash
make data-audit  # validate dữ liệu PostgreSQL trong cửa sổ nghiên cứu
make step4       # In-Sample qua Plutus
make step5       # sensitivity grid
make step6       # Out-of-Sample với cấu hình frozen
make plot        # vẽ từ report Plutus đã sinh
make check       # owned tests, ruff và compile
```

Lệnh backtest dùng bars 30 phút và soft-fill khi không có depth lịch sử. Các
backtest có order book phải nạp depth as-of timestamp trước khi dùng
`book_walk`; không diễn giải soft fill là bằng chứng live execution.

## Ghi chú phương pháp

Signal chỉ nhìn thấy bar sau khi bar hoàn thành và lệnh được gửi tại bar kế
tiếp, nhằm tránh same-close look-ahead. Lịch ngày nghỉ, margin profile và mọi
giả định thực thi đều nằm trong code/provenance của kết quả chạy.
