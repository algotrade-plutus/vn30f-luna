# AGENTS.md — Quy Chuẩn Kiến Trúc & Hướng Dẫn Vận Hành AI Agent

Tài liệu này định hình cấu trúc dự án, quy tắc viết code và hướng dẫn vận hành cho các AI coding assistant khi làm việc trong repository này.

---

## 1. Tổng Quan Dự Án & Mục Tiêu

Dự án là hệ thống giao dịch định lượng cho hợp đồng tương lai VN30F1M. Chiến lược **Calibrum** gộp ba nguồn alpha
(Calendar MTW, Basis, Momentum) bằng vote, nghiên cứu theo quy trình 9 bước của ALGOTRADE:
1. **Lấy nến 1 phút DNSE làm nền tảng:** VN30F1M và chỉ số VN30 khung 1 phút từ API công khai của DNSE; phiên DNSE
   thiếu nến 1 phút thì lấp bằng nến 5 phút, không bao giờ ffill. Nến 10 và 30 phút gộp từ nến phút. Khoảng dữ liệu và
   giai đoạn nghiên cứu ghi trong `config/research.toml`.
2. **Lab engine cho Bước 4–6:** Lab khớp lệnh tại giá close nến tín hiệu, xét stop ở close mỗi nến phút, tính chi phí
   0,4 điểm mỗi hợp đồng mỗi chiều (gộp phí HNX, phí VSDC, thuế PIT, hoa hồng và trượt giá), lãi lỗ bằng VND trên vốn
   cố định. Sharpe và drawdown lấy từ `plutus.evaluation.metrics`, tỷ lệ ký quỹ ban đầu theo ngày lấy từ
   `plutus.market.margin`. Plutus chỉ đọc, không sửa.
3. **Research-Runtime Parity:** Logic alpha dùng chung cho backtest và bot paper/live; chỉ hoán đổi adapter thực thi.
4. **Báo cáo bằng tiền:** Kết quả ghi bằng triệu VND trên 100 triệu vốn mỗi hợp đồng; điểm chỉ số chỉ dùng cho khoảng
   cách giá.

---

## 2. Cấu Trúc Mã Nguồn

```text
src/
├── domain/          # [TẦNG 1] stdlib only: entities (Order, Position, Fill, Margin, Tick, Bar), strategy/calendar_rules
├── application/     # [TẦNG 2] Ports (IBrokerGateway, ISignalGateway, ...) và use cases (TradingCycle, RiskMonitor)
├── adapters/        # [TẦNG 3] data/ (DNSE candles, minute bars), strategies/ (Calendar MTW), brokers/ (Plutus)
└── lab/             # Ngoài 4 tầng: engine nghiên cứu (backtest/, calibrum_1m/), được dùng pandas/numpy
scripts/             # fetch_dnse_candles, run_calibrum_1m (các bước protocol), plot_calibrum_1m, plot_calibrum_positions
research/calibrum-1m # PROTOCOL.md (khoá trước khi chạy) và RESULTS.md
papertrade/          # Runtime Bước 7 trên AWS, venv và test riêng
```

### Quy tắc bất biến cho Agent:
* **Tầng Domain (`src/domain/`):** Tuyệt đối **KHÔNG IMPORT** thư viện ngoài (SQL, HTTP, socket, pandas, numpy). Chỉ dùng
  Python chuẩn. `tests/test_clean_architecture.py` kiểm tra điều này.
* **Tầng Application (`src/application/`):** Chỉ phụ thuộc Domain và các Port.
* **Tầng Adapters (`src/adapters/`):** Triển khai Port hoặc cung cấp dữ liệu/tín hiệu cho lab và runtime.

---

## 3. Bí Mật và Cấu Hình

Pipeline nghiên cứu không cần bí mật nào: DNSE là API công khai, cấu hình nằm ở `config/research.toml`. Credential của
paper trading nằm trong `papertrade/.env` (gitignore). Tuyệt đối không hardcode mật khẩu, token, API key vào code hay tài
liệu được commit.

---

## 4. Dữ Liệu

* Nến lưu đệm tại `data/dnse/` (gitignore), tải bằng `make fetch-data`.
* Chỉ số VN30 trên DNSE chỉ có từ 11/05/2020, nên in-sample bắt đầu 01/06/2020.
* Output nghiên cứu ở `reports/calibrum_1m/` (gitignore); hình cho README chép vào `image/README/`.

---

## 5. Quy Trình Làm Việc Của AI Agent (Evidence-First)

Khi giải quyết bất kỳ yêu cầu nào trong repo này, Agent phải tuân thủ:
1. **Evidence-First:** Kiểm tra code và tài liệu thực tế trước khi phát biểu. Không đoán mò API, không bịa đặt tên file.
2. **Xác nhận qua Test:** Chạy test kiểm thử trước và sau khi chỉnh sửa bằng:
   ```bash
   ./scripts/run_owned_tests.sh
   ```
3. **Giữ gìn nhánh:** `main` chứa phiên bản ổn định, đã kiểm chứng; việc mới làm trên nhánh riêng.

## 6. Triết Lý Nghiên Cứu (Bắt Buộc)

Mọi nghiên cứu chiến lược tuân theo triết lý ALGOTRADE trong [.claude/skills/algotrade-hypothesis/philosophy.md](.claude/skills/algotrade-hypothesis/philosophy.md) (người dùng chốt 19/10/2026):
1. **Thiết kế trước khi chạy:** Mỗi giả thuyết mới phải có `PROTOCOL.md` (skill `algotrade-hypothesis`, chế độ Thiết kế) nêu nguồn alpha, ai trả tiền, luật đo được, dự đoán bác bỏ, ngân sách lần thử và khoảng dữ liệu. Thiếu thì chưa backtest.
2. **Bác bỏ được:** Dự đoán bác bỏ viết trước; xảy ra thì bỏ giả thuyết, không vá cho đẹp.
3. **Đơn giản trước, bỏ nhanh:** Bắt đầu từ luật ít tham số; mỗi bộ lọc thêm là một lần thử; quá ít phiên bản có lãi thì bỏ.
4. **Vùng ổn định:** Chỉ chọn tham số mà lân cận cũng tốt, không chọn đỉnh nhọn.
5. **Out-of-sample dùng một lần:** Đếm và ghi mọi lần nhìn; đã dùng để chọn thì không còn là out-of-sample. Báo kết quả kèm tổng số lần thử và Deflated Sharpe.
6. **Phán quyết có ghi chép:** Khi nhánh có kết quả, chạy chế độ Phán quyết của skill và ghi GIỮ / SỬA LUẬT / BỎ vào report.
