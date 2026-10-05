# AGENTS.md — Quy Chuẩn Kiến Trúc & Hướng Dẫn Vận Hành AI Agent

Tài liệu này định hình toàn bộ cấu trúc dự án, quy tắc viết code (Clean Architecture) và hướng dẫn vận hành cho các AI Coding Assistant (Antigravity, Gemini, Claude, Cursor,...) khi làm việc trong repository này.

---

## 1. Tổng Quan Dự Án & Mục Tiêu

Dự án này là hệ thống giao dịch định lượng (Quantitative Trading System) cho thị trường chứng khoán & phái sinh Việt Nam (VN30F), được tái cấu trúc theo mô hình **Plutus-Centric Clean Architecture**:
1. **Lấy dữ liệu Tick & Order Book làm nền tảng:** Kết nối trực tiếp với PostgreSQL `algotradeDB` (`quote.matched`, `quote.bidprice`, `quote.askprice`).
2. **Plutus Engine thay thế hoàn toàn Bước 4 (In-Sample) và Bước 6 (Out-of-Sample):** Mọi kiểm thử đều diễn ra trên sàn giả lập trung thực (Plutus HNXDS/VSDC) có tính ngày hiệu lực (effective-dated), trừ đầy đủ phí HNX, bù trừ VSDC, thuế PIT và đo lường an toàn ký quỹ (Margin Utilisation, Margin Call 90%).
3. **Research-Runtime Parity (Tính tương đồng tuyệt đối):** Dùng chung **100% Core Alpha logic** cho cả Backtest và Bot Live trên AWS EC2. Chỉ hoán đổi Execution Adapter, không viết lại code.
4. **Kiểm định tính tái lập (Reproducibility):** Dùng `plutus-verify` và `.plutus/manifest.yaml` để đóng băng baseline trong container Docker độc lập.

---

## 2. Quy Tắc Kiến Trúc 4 Tầng (Clean Architecture)

Mọi mã nguồn mới được tổ chức chặt chẽ trong thư mục `src/` theo quy tắc phụ thuộc một chiều (Dependency Rule):

```text
src/
├── domain/                  # [TẦNG 1] Nghiệp vụ cốt lõi (Core Business)
│   ├── entities/            # Order, Position, Fill, Margin, Tick, Bar
│   └── strategy/            # CalendarRules, Hypothesis
│
├── application/             # [TẦNG 2] Use Cases & Ports (Interfaces)
│   ├── ports/               # IBrokerGateway, IMarketFeedGateway, IStateStore
│   └── use_cases/           # RiskMonitorUseCase
│
├── adapters/                # [TẦNG 3] Interface Adapters (Cầu nối thực thi)
│   ├── brokers/             # PlutusBrokerAdapter (Backtest), LivePaperAdapter (EC2 FIX/REST)
│   └── data/                # PostgresTickSource, ParquetSource, KafkaLiveStream
│
└── infrastructure/          # [TẦNG 4] Frameworks & Drivers
    ├── database/            # psycopg2 pool, SQL queries
    └── fix_protocol/        # QuickFIX config, message serializer
```

### Quy tắc bất biến cho Agent:
* **Tầng Domain (`src/domain/`):** Tuyệt đối **KHÔNG IMPORT** các thư viện bên ngoài như SQL, HTTP, Socket, QuickFIX, Pandas, Numpy. Chỉ sử dụng Python chuẩn (stdlib, dataclasses, Decimal, datetime).
* **Tầng Application (`src/application/`):** Chỉ tương tác với Tầng Domain và các Interfaces (Ports). Không phụ thuộc vào triển khai cụ thể của sàn hay database.
* **Tầng Adapters (`src/adapters/`):** Triển khai các Ports bằng cách kết nối với Plutus (`ExchangeSession`) hoặc PaperBroker (`FIX/REST`).

---

## 3. Cấu Hình Môi Trường (.env)

Mọi bí mật và thông số kết nối được lưu trong `.env` (đã nằm trong `.gitignore`):

```bash
# PostgreSQL Production Data (Read-only Tick & Order Book)
ALGOTRADE_DB_HOST=api.algotrade.vn
ALGOTRADE_DB_PORT=5432
ALGOTRADE_DB_NAME=algotradeDB
ALGOTRADE_DB_USER=intern_read_only
ALGOTRADE_DB_PASSWORD=...

# Plutus Corpus Path
PLUTUS_DATA_ROOT=data/aug2026_corpus
```

> **Cảnh báo bảo mật:** Tuyệt đối không hardcode mật khẩu, token, API keys vào các file Python hoặc tài liệu được commit vào Git. Luôn đọc qua `os.getenv(...)`. File mẫu không mang bí mật được lưu tại `.env.example`.

---

## 4. Dữ Liệu Cơ Sở Dữ Liệu (Postgres `algotradeDB`)

Kho dữ liệu `algotradeDB` chứa 44 bảng. Khi viết query, luôn chú ý:
* Bảng Tick: `quote.matched` `(datetime, tickersymbol, price)`
* Bảng Volume Tick: `quote.matchedvolume` `(datetime, tickersymbol, quantity)`
* Bảng Sổ Lệnh Mua/Bán: `quote.bidprice`, `quote.bidsize`, `quote.askprice`, `quote.asksize` `(datetime, tickersymbol, depth, price/quantity)`
* Bảng Hợp Đồng Phái Sinh: `quote.futurecontractcode` `(tickersymbol, datetime, futurecode)`
* **Quy tắc Index:** Luôn kèm `WHERE datetime >= ... AND datetime <= ...` trong mọi câu lệnh query để kích hoạt Primary B-Tree Index `(datetime, tickersymbol)`, tránh sequential scan toàn bảng.

---

## 5. Quy Trình Làm Việc Của AI Agent (Evidence-First)

Khi giải quyết bất kỳ yêu cầu nào trong repo này, Agent phải tuân thủ:
1. **Evidence-First:** Kiểm tra code và tài liệu thực tế trước khi phát biểu. Không đoán mò API, không bịa đặt tên file.
2. **Xác nhận qua Test:** Chạy test kiểm thử trước và sau khi chỉnh sửa bằng:
   ```bash
   ./scripts/run_owned_tests.sh
   ```
3. **Giữ gìn nhánh:**
   * Nhánh `main`: Chứa phiên bản ổn định, baseline đã kiểm chứng.
   * Nhánh `refactor/clean-architecture`: Nhánh phát triển kiến trúc 4 tầng mới.
