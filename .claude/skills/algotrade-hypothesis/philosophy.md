# Triết lý giao dịch thuật toán (ALGOTRADE Knowledge Hub)

Nguồn: <https://www.algotrade.vn/knowledge>, đọc 19/10/2026. Toàn văn local: `docs/algotrade_knowledge_hub/` (số file
ghi trong ngoặc). Đây là tóm tắt, trích ngắn trong ngoặc kép.

## Ba nguyên tắc khoa học

Nguồn: Scientific Principles (05), The 9-Step (10).

1. Minh bạch. Ghi lại dữ liệu, tiêu chí quyết định, mọi lần thử và kết quả, đủ để chạy lại ra cùng số. Không dùng mô
   hình hộp đen mà không giải thích được nó dựa vào đâu.
2. Bác bỏ được. Trước khi chạy, viết ra dự đoán nào sẽ chứng minh giả thuyết sai. Sai thì bỏ.
3. Nhất quán. Áp cùng một luật đủ lâu và đủ số lệnh để có ý nghĩa thống kê; đánh giá quy trình qua nhiều lệnh.
   "process, not profit, is the true leading indicator".

## Quy tắc làm việc

- Nguồn alpha trước, chỉ báo sau (Three Pillars 13, Eight Sources of Alpha 11). Mỗi giả thuyết nói rõ nó khai thác sự
  kém hiệu quả nào, ai trả tiền, vì sao lợi thế còn tồn tại. Tám nguồn: common sense, mispricing, thiên kiến hành vi,
  tốc độ, mô hình thống kê, hiểu biết riêng của thị trường, lợi thế riêng của công ty, dữ liệu. Ví dụ trong bài: ngại lỗ
  dẫn tới "higher volatility when the market is in a downtrend compared to when it is in an uptrend".
- Giả thuyết thành luật đo được (From Hypothesis to Rules 08). Tách biến độc lập và phụ thuộc, đo được từng biến, đưa
  ràng buộc thật vào luật. Một giả thuyết sinh nhiều bộ luật; bộ luật hỏng chưa chắc giả thuyết sai.
- Đơn giản trước (Techniques to Avoid Overfitting 09). Bắt đầu từ luật ít tham số; mỗi luật thêm vào phải tự chứng minh
  giá trị.
- Bỏ nhanh. Nếu quá ít phiên bản có lãi, bỏ giả thuyết thay vì tinh chỉnh tiếp: "Fail fast, fail often".
- Vùng ổn định, không đỉnh nhọn. Chỉ chọn tham số mà lân cận cũng tốt.
- Out-of-sample dùng "ideally just once". Dùng nhiều lần thì nó thành tập validation.
- Walk-forward có giới hạn: "Meaningful segmentation of financial data remains an unsolved challenge". Dữ liệu gần mang
  nhiều thông tin hơn dữ liệu xa.
- Dự báo giá là khoa học xã hội (Stock Price Prediction 23). Mô hình tốt sau phí đúng khoảng 55%, hành động sai vẫn
  thắng khoảng 35%, nên không quy được một kết quả về một quyết định; chỉ đánh giá qua nhiều lệnh.
- Độ thực tế tăng dần (Assessing Realism 07). In-sample, out-of-sample, paper trading, tài khoản nhỏ: dữ liệu, lệnh và
  vốn lần lượt trở thành thật. Hiệu suất nhất quán qua các mức là tín hiệu alpha mạnh nhất.
- Chống thiên kiến hành động (Action Bias 22). Ý tưởng mới ghi vào nhật ký, thử trong sandbox; không can thiệp hệ thống
  đang chạy vì một biến động ngắn hạn.

## Quy trình 9 bước (The 9-Step, 10)

1. Hình thành giả thuyết.
2. Chuẩn bị dữ liệu.
3. Chuyển giả thuyết thành bộ luật.
4. Backtest in-sample (bài gợi ý chia 70/30, ít nhất 30 giao dịch, tính đủ phí, thuế, trượt giá).
5. Tối ưu: tìm vùng tham số ổn định, tránh overfit.
6. Backtest out-of-sample.
7. Paper trading.
8. Thử tài khoản nhỏ (khoảng 2 tháng).
9. Chạy thật; theo dõi khoảng 3 tháng trước khi chính thức.
