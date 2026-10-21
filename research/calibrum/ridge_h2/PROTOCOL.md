# Protocol: Ridge H2, quán tính giá trong phiên (19/10/2026)

Protocol này viết hồi cứu. Sleeve đã được fit, đóng băng trong `PS_V30_Vien_Calibrum/` và backtest trên cả ba giai
đoạn trước ngày viết. Mục đích là ghi lại giả thuyết như nó đang chạy, đếm những lần thử đã biết, và khoá một khoảng
dữ liệu chưa ai nhìn để chấm lần cuối.

## 1. Giả thuyết

Khi giá đóng nến 30 phút đã lệch khỏi giá mở cửa 09:00, khỏi SMA 4 nến và khỏi thân nến hiện tại theo cùng một chiều,
giá VN30F1M đi tiếp theo chiều đó trong 2 nến (1 giờ) kế tiếp. Lực đi tiếp yếu dần khi giá đã cách VWAP phiên quá xa.

## 2. Nguồn alpha và cơ chế

- Nguồn: thiên kiến hành vi, đo bằng mô hình thống kê.
- Ai trả tiền: nhà đầu tư cá nhân vào lệnh trễ. VN30F có đòn bẩy cao và phần lớn thanh khoản đến từ cá nhân, nên khi
  giá đã chạy từ đầu phiên, người thấy muộn đuổi theo và đẩy giá đi thêm. Người đang ở chiều sai bị gọi ký quỹ hoặc tự
  cắt lỗ, cũng đẩy cùng chiều. Hệ số âm trên khoảng cách tới VWAP là phần ngược lại: khi giá đã lệch xa giá trung bình
  phiên, người giữ vị thế từ sớm bắt đầu chốt lời.
- Vì sao lợi thế còn: chi phí giao dịch 0,4 điểm mỗi chiều làm phần lớn lợi thế ngắn hạn này không đáng để khai thác
  với tài khoản nhỏ, và ít tổ chức chạy chiến lược intraday trên VN30F.
- Khi nào mất: khi tỷ trọng tổ chức và bot trong VN30F tăng, hoặc khi thị trường chuyển sang đi ngang kéo dài với
  biên độ hẹp. Dấu hiệu sớm: hit rate giai đoạn forward 2025 đến 2026 trên lab chỉ còn 41%.

## 3. Luật đo được

- Biến độc lập: 5 đặc trưng tính trên 8 nến giờ liên tục (09:00 đến 11:00, 13:00 đến 14:00), chia cho ATR 14 nến
  tính từ dữ liệu đã `shift(1)`:
  - `f1 = (Close − Open lúc 09:00) / ATR14`
  - `f2 = (Close − SMA4(Close)) / ATR14`
  - `f3 = (Close − Open) / ATR14` của nến hiện tại
  - `f4 = (ΣUp² − ΣDown²) / (ΣUp² + ΣDown²)` trên 4 nến
  - `f5 = (Close − VWAP phiên) / ATR14`, VWAP tính từ 09:00 tới nến hiện tại bằng HLC3 × Volume

  Đặc trưng được chuẩn hoá bằng median và IQR của in-sample, cắt ở ±8. Score là tổ hợp tuyến tính với hệ số Ridge đã
  đóng băng trong `PS_V30_Vien_Calibrum_model.pt`: β = (+0,1472; +0,0464; +0,0423; +0,0190; −0,0396), hệ số chặn
  −0,0206.
- Biến phụ thuộc: lợi suất 2 nến tới, chia cho ATR14 (target dùng khi fit, theo `scripts/test_ridge_refit_lab.py`).
- Luật vào: Score ≥ +0,18 thì Long, Score ≤ −0,18 thì Short, ở giữa thì đứng ngoài.
- Luật ra: lỗ chưa chốt quá 10 điểm; hoặc đã giữ ít nhất 2 nến và Score đổi dấu; hoặc đã giữ 8 nến.
- Tham số: ngưỡng 0,18, giữ 2 đến 8 nến, cắt lỗ 10 điểm. Repo không ghi lý do chọn các giá trị này; chúng đến từ quá
  trình phát triển trước khi có repo (xem mục 6).
- Ràng buộc thật của thị trường:
  - Tín hiệu tính ở giá đóng nến T, khớp ở nến T+1 (`pre_shift_positions`).
  - Nến 11:30 và 14:30 không tính Score. Ở nến 14:30 (ATC) giữ nguyên vị thế.
  - Phí 0,4 điểm mỗi chiều trên lab. Plutus tính đủ phí HNX, VSDC và thuế PIT.
  - Khi đổi hợp đồng front-month, adapter reset ATR, đặc trưng và trạng thái, và ép Ridge về 0 trong phiên đáo hạn
    (`_ridge_with_roll_guard`). Gói đóng băng không có luật này; đó là một lần thử riêng.

## 4. Dự đoán bác bỏ

Chấm trên khoảng khoá ở mục 7, với hệ số và tham số giữ nguyên.

- B1: Tương quan hạng (Spearman) giữa Score và lợi suất 2 nến tới (chia ATR14) ≤ 0. Khi đó Score không dự báo được
  chiều giá và giả thuyết sai.
- B2: Lợi suất 2 nến tới tính theo chiều tín hiệu, trung bình trên các nến có |Score| ≥ 0,18, không lớn hơn 0,8 điểm.
  Khi đó quán tính có thể có thật nhưng nhỏ hơn phí một vòng, và luật này không khai thác được.
- B3: Refit Ridge mở rộng dần (expanding, cập nhật hàng tháng, như `scripts/test_ridge_refit_lab.py`) trên dữ liệu
  2023 đến hết khoảng khoá, hệ số của `f1` đổi sang âm, hoặc hệ số của `f5` đổi sang dương. Một trong hai đổi dấu nghĩa
  là cơ chế ở mục 2 (đuổi giá từ đầu phiên, chốt lời quanh VWAP) không còn đúng.

## 5. Tiêu chí chấp nhận

Ngưỡng của dự án (gate trong `PS_V30_Vien_Calibrum/native_verification.json`) áp cho cả ensemble: Sharpe sau phí
≥ 1,5, margin sau phí ≥ 15 bps, ít nhất 180 lệnh, Futures Leak và Overfit PASS.

Ridge là một sleeve nên cần qua cả ba điều sau:

- Lãi sau phí trên khoảng khoá, và dương ở ít nhất 2 trong 3 giai đoạn IS, OOS, FWD của lab (đã đạt: +1.044,7;
  +312,8; +429,3 điểm).
- Bỏ Ridge khỏi ensemble làm Sharpe của ensemble giảm trên khoảng khoá. Trên lab giai đoạn FWD, S + C có Sharpe 2,15,
  còn R + S + C có 2,36.
- Ngưỡng 0,18 nằm trong vùng ổn định: ngưỡng 0,14 và 0,22 cũng lãi sau phí trên cùng dữ liệu. Phép thử này chưa
  chạy; nó là lưới duy nhất được phép ở mục 6.

## 6. Ngân sách lần thử

Những lần thử đã biết trong repo:

| Lần thử | Số biến thể | Nguồn |
|---|---:|---|
| Refit rolling (W = 500, 1000, 1500, 2000; alpha = 10, 50) | 8 | `scripts/test_ridge_refit_lab.py` |
| Refit expanding (alpha = 10, 50, 100) | 3 | `scripts/test_ridge_refit_lab.py` |
| Chuẩn hoá rolling hoặc expanding thay cho median/IQR cố định | 11 | `scripts/test_ridge_rolling_lab.py` |
| Roll guard và ép phẳng ngày đáo hạn | 1 | `calibrum_signal_source.py` |
| Bản đóng băng | 1 | `PS_V30_Vien_Calibrum/` |

Tổng trong repo: 24. Quá trình chọn 5 đặc trưng (tên `structure5` và `H2` cho thấy đã có ít nhất một bộ khác) cùng
việc chọn ngưỡng, thời gian giữ và cắt lỗ xảy ra trước khi có repo và không được ghi lại. Vì vậy N thật lớn hơn 24 và
chưa biết. Nếu còn log hay notebook của giai đoạn đó, đếm thêm vào đây.

Lưới cho lần chấm tiếp theo, khoá trước: ngưỡng vào ∈ {0,14; 0,18; 0,22}, các tham số khác giữ nguyên. Chỉ có 3 lần
thử mới, nâng N tối thiểu lên 27. DSR tính với N = 27 và ghi rõ đó là cận dưới.

## 7. Dữ liệu

| Khoảng | Ngày | Vai trò hiện tại | Số lần đã nhìn |
|---|---|---|---|
| In-sample | 02/01/2020 đến 30/12/2022 | Fit scaler, hệ số và chọn tham số | Nhiều |
| OOS cũ | 01/01/2023 đến 19/12/2024 | Validation | ≥ 4: notebook Native SDK, lab 7 tổ hợp, so sánh 8 cách ensemble, Plutus vote và sum |
| Forward cũ | 01/01/2025 đến 01/10/2026 | Validation | ≥ 4, cùng các lần trên; dùng để chọn equal-weight sum |
| Khoá | từ 02/10/2026 | Kiểm tra cuối | 0 |

Hai khoảng 2023 đến 2026 đã dùng để so và chọn, nên không còn là out-of-sample. Kiểm tra cuối chỉ dùng dữ liệu từ
02/10/2026 trở đi, mở một lần khi Ridge đã có ít nhất 60 lệnh. Với khoảng 195 lệnh mỗi năm trên lab, mốc này đến sau
khoảng 4 tháng. Nguồn chấm: Postgres `algotradeDB` qua roll adjust của adapter, nguồn đối chiếu là DNSE.
