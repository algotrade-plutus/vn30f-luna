# Kế hoạch: bước 4 đến bước 7

Ghi ngày 20/10/2026. Slide đã chốt đến slide 22 (trang mở đầu bước 4). Báo cáo `.md` sửa trước, slide sửa sau.

## Bước 4: Backtest in-sample

1. Metric đánh giá: lab (slide 24, 25 hiện tại) và Plutus. Đặt lên đầu bước 4.
2. Tham số khởi tạo ban đầu cho cả ba sleeve và ensemble (slide 23 hiện tại, dời ra sau phần metric).
3. Chạy backtest IS và vẽ biểu đồ cho cả lab và Plutus. Mỗi biểu đồ chồng 9 cấu hình để so sánh trực tiếp:
   C, M, B, CM, CB, BM, ensemble vote, ensemble sum. Metric để vẽ chọn sau (ví dụ Sharpe, HPR, MDD, ...).
4. Một slide nhận xét.
5. Tương quan vị thế giữa các sleeve (có thể bỏ).

Slide 26 hiện tại ("The same session in both engines") trùng nội dung với slide 14: bỏ, hoặc chỉ giữ phần Plutus.

## Bước 5: Tối ưu

- Tối ưu từng sleeve riêng, sau đó mới kết hợp lại.
- M (Momentum): định nghĩa hàm mục tiêu. Ridge: J(β) = Σ (y_t − β_0 − Σ β_j x_j,t)² + λ Σ β_j², với y_t = lợi suất 2 nến
  tới chia ATR14. Tham số cần chọn là λ (có thể thêm cửa sổ fit); β là kết quả của việc giải J trên IS.
- C (Calendar) và B (Basis): grid search.

## Bước 6: Backtest out-of-sample

Vẽ lại đúng bộ biểu đồ của bước 4 cho giai đoạn ngoài mẫu.

## Bước 7

Nếu slide xong đến bước 6 thì code bước 7 (paper trading cho cả ensemble; repo hiện chỉ có paper trading của Calendar).

## Việc kỹ thuật cần làm

- Plutus hiện chỉ chạy được ensemble vote và sum. Thêm tuỳ chọn chọn sleeve (ví dụ `--sleeves M,B`) ở adapter và
  `scripts/run_calibrum_plutus.py` để chạy sleeve lẻ và cặp. Không sửa `plutus/`.
- Gom 9 đường vào một hình trong `scripts/generate_report_plots.py` (lab), và viết script tương tự cho Plutus.

## Điểm cần chốt trước khi làm

1. Số hợp đồng trên Plutus cho sleeve lẻ và cặp. Đề xuất: mọi cấu hình tối đa 3 hợp đồng. Sleeve lẻ = 3 × vị thế, cặp
   gộp kiểu vote = 3 × sign(tổng), vote = 3 × vị thế, sum = tổng (tối đa 3).
2. Metric nào để vẽ. Đề xuất mỗi engine hai hình: đường lãi luỹ kế kèm drawdown (9 đường: sleeve lẻ nét mảnh, cặp nét
   đứt, ensemble nét đậm) và biểu đồ cột Sharpe, MDD, HPR (Plutus) hoặc margin (lab).
3. OOS 2023–2024 đã được xem một lần với cấu hình đóng băng. Tối ưu lại rồi chạy lại cùng OOS là lần nhìn thứ hai.
   Đề xuất: khoá luật chọn và ngân sách lần thử của bước 5 trong protocol trước khi chạy, ghi rõ điều này trong báo cáo,
   và coi dữ liệu từ 02/10/2026 (paper trading) là phép thử sạch.
4. Grid của C và B giữ nhỏ, vì mỗi ô là một lần thử và làm DSR chiết khấu mạnh hơn.
