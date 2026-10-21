# Calibrum VN30F: báo cáo nghiên cứu

Mỗi chương ứng với một bước trong quy trình 9 bước (bước 1 đến 6). Slide được dựng từ các chương này.

| Chương | Bước | Trạng thái |
|---|---|---|
| [00_introduction.md](00_introduction.md) | Thị trường, mục tiêu, cách làm | Bản nháp |
| [01_hypotheses.md](01_hypotheses.md) | 1. Hình thành giả thuyết | Bản nháp |
| [02_data_preparation.md](02_data_preparation.md) | 2. Chuẩn bị dữ liệu | Bản nháp |
| [03_rules.md](03_rules.md) | 3. Chuyển giả thuyết thành luật | Bản nháp |
| [04_in_sample.md](04_in_sample.md) | 4. Backtest in-sample | Bản nháp |
| [05_optimization.md](05_optimization.md) | 5. Tối ưu | Bản nháp |
| [06_out_of_sample.md](06_out_of_sample.md) | 6. Backtest out-of-sample | Bản nháp |

Tài liệu đi kèm: kịch bản thuyết trình ([tiếng Việt](presentation_script_vi.md), [tiếng Anh](presentation_script.md)),
và thư mục [exercise/](exercise/) gồm bài tập tự tính backtest lab và bảng "đồng hồ" của mô hình.

## Quy ước dùng chung

Hai engine backtest, hai mục đích:

| | Lab (`src/lab/backtest/`) | Plutus (`PlutusResearchRunner`) |
|---|---|---|
| Kiểm tra | Riêng phần alpha | Alpha cộng khớp lệnh |
| Dữ liệu | Nến 30 phút DNSE (`data/dnse/`) | Tick trong `algotradeDB`, gộp thành nến 30 phút |
| Khớp lệnh | Giá đóng nến: vị thế cầm trong nến t là vị thế quyết định ở nến t−1 | Khớp mềm theo giá quan sát của nến, không dùng độ sâu sổ lệnh, tối đa 10% khối lượng nến |
| Đơn vị | Điểm chỉ số, 1 hợp đồng | Đồng, trên vốn tài khoản |
| Phí | 0,8 điểm mỗi vòng | Phí HNX, VSDC và thuế TNCN do Plutus tính |
| Sharpe | Lãi lỗ điểm theo ngày, mean / std × √252, R_f = 0 | Lợi suất tài khoản theo ngày, mean / std × √252, R_f = 0 |

Engine nào dùng ở bước nào:

| Bước | Lab | Plutus |
|---|:---:|:---:|
| 4. In-sample | có | có |
| 5. Tối ưu | có | |
| 6. Out-of-sample | có | có |

Các giai đoạn. In-sample bắt đầu từ 01/06/2021, ngày đầu tiên có dữ liệu trong cơ sở dữ liệu, nên hai engine chạy trên
cùng một khoảng:

| Giai đoạn | Thời gian |
|---|---|
| In-sample (IS) | 01/06/2021 đến 30/12/2022 |
| Out-of-sample (OOS) | 01/01/2023 đến 19/12/2024 |
| Forward (FWD) | 01/01/2026 đến dữ liệu mới nhất (hiện là 01/10/2026) |

Năm 2025 không dùng. Forward là lần kiểm tra cuối trước paper trading (bước 7).

Thông số Plutus: vốn 300 triệu đồng, mọi cách gộp đều tối đa 3 hợp đồng để so sánh công bằng. Cách gộp không chia khối
lượng (majority vote, tín hiệu thuộc {−1, 0, +1}) giao dịch 3 hợp đồng; equal-weight sum giao dịch M + B + C, trong
khoảng −3 đến +3. Lệnh chạy: `make calibrum-insample ENSEMBLE=vote` hoặc `ENSEMBLE=sum`.

Mỗi con số trong các chương đều ghi kèm file report hoặc lệnh đã tạo ra nó.

## Việc còn mở

- Trọng số hồi quy của Momentum lấy từ gói đóng băng và không rõ nguồn gốc fit. Hướng sửa đã bàn: coi trọng số là tham số,
  bước 4 khởi tạo theo dấu của giả thuyết, bước 5 mới fit hồi quy Ridge trên in-sample. Chưa làm.
- Hình Plutus cũ trong `README.md` ở gốc repo ghi OOS kết thúc ngày 31/12/2024; các lần chạy mới kết thúc ngày
  19/12/2024.
