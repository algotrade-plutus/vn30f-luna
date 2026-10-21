# Protocol: Calendar, dòng tiền theo lịch (19/10/2026)

Protocol này viết hồi cứu. Sleeve đã đóng băng trong `PS_V30_Vien_Calibrum/` và đã backtest trên cả ba giai đoạn trước
ngày viết. Mục đích là ghi lại giả thuyết như nó đang chạy, đếm những lần thử đã biết, và khoá một khoảng dữ liệu
chưa ai nhìn để chấm lần cuối.

Calendar gồm năm chân. Mỗi chân có thể sai riêng, nên mục 4 chấm từng chân và chấm cả sleeve.

## 1. Giả thuyết

Lợi suất VN30F1M trong một phiên phụ thuộc vào vị trí của phiên đó trên lịch: hai ngày làm việc đầu tháng, phiên
trước kỳ nghỉ, thứ Ba và thứ Tư, và ngày đáo hạn có lợi suất trung bình dương; thứ Hai thường mở cửa không tăng
(gap ≤ 0) có lợi suất trong phiên âm.

## 2. Nguồn alpha và cơ chế

- Nguồn: hiểu biết riêng của thị trường Việt Nam, và thiên kiến hành vi.
- Cơ chế từng chân, theo mức độ thuyết phục:
  - Đầu tháng: tiền mới vào thị trường theo chu kỳ tháng (lương, đóng góp định kỳ vào quỹ, giải ngân của tổ chức). Người
    trả tiền là người bán cho dòng tiền này ở giá cao hơn. Hiệu ứng turn-of-month có ở nhiều thị trường.
  - Thứ Hai thường, gap ≤ 0: tin xấu tích lại qua cuối tuần, và công ty chứng khoán xử lý tài khoản vi phạm ký quỹ vào
    đầu tuần. Người trả tiền là người bị bán giải chấp. Bộ lọc gap bỏ những thứ Hai có tin tốt.
  - Trước kỳ nghỉ: người bán khống phái sinh đóng vị thế để khỏi giữ rủi ro qua kỳ nghỉ, và tâm lý tích cực trước lễ.
    Người trả tiền là người đóng vị thế bán vì lý do rủi ro, không vì quan điểm giá.
  - Thứ Ba và thứ Tư: `docs/calendar.md` giải thích là "áp lực bán cạn kiệt" sau thứ Hai. Giải thích này chưa nói được
    ai trả tiền. Đây là chân yếu nhất về cơ chế.
  - Ngày đáo hạn (thứ Năm thứ ba của tháng): `docs/calendar.md` nói tự doanh và tạo lập giữ giá trụ VN30 để chốt hợp
    đồng. Giữ giá không giải thích vì sao chiều là Long. README mục H3 cũng không nhắc chân này, dù code bật nó.
- Vì sao lợi thế còn: lịch nạp tiền và xử lý ký quỹ là thói quen vận hành của nhà đầu tư và công ty chứng khoán, khó
  đổi nhanh. Mỗi lần chỉ ăn một phiên và tần suất thấp, nên ít người theo dõi.
- Khi nào mất: khi chu kỳ thanh toán hay cách xử lý ký quỹ thay đổi, hoặc khi đủ nhiều người giao dịch theo lịch làm
  hiệu ứng dời sang phiên trước đó.

## 3. Luật đo được

- Biến độc lập: chỉ dùng ngày và giờ, cộng một số liệu giá: gap thứ Hai = Open nến đầu phiên − Close nến cuối phiên
  trước. Gap biết được lúc nến 09:00 đóng, trước khi lệnh khớp ở nến 09:30.
- Biến phụ thuộc: lợi suất phiên. Với chân Long là từ 14:30 hôm trước tới 14:30 ngày mục tiêu; với chân Short thứ Hai
  là trong phiên, trước 14:30.
- Luật:
  - Long ngày mục tiêu nếu ngày đó là thứ Ba, thứ Tư, một trong hai ngày làm việc đầu tháng, hoặc phiên trước kỳ nghỉ.
    Vào từ nến 14:30 hôm trước để giữ qua đêm, ra lúc 14:30 ngày mục tiêu.
  - Short thứ Hai thường (không trùng đầu tháng, không trùng trước kỳ nghỉ) khi gap ≤ 0, trước 14:30.
  - Long ngày đáo hạn trước 14:30 nếu chưa có vị thế khác.
- Tham số: `long_dows = (1, 2)`, gap tối đa 0,0, giờ kết thúc 14:30, năm cờ bật tắt chân luật. Repo không ghi vì sao
  chọn thứ Ba và thứ Tư.
- Ràng buộc thật của thị trường:
  - Tín hiệu tính ở giá đóng nến T, khớp ở nến T+1.
  - Trong ensemble, nến 14:30 bị ép bằng vị thế ensemble lúc 14:00. Vì vậy phần vào lệnh qua đêm của Calendar không đi
    vào ensemble ở nến đó; chỉ khi chạy riêng sleeve mới có.
  - Ba chỗ lịch trong code chưa khớp lịch giao dịch thật:
    1. "Hai ngày đầu tháng" đếm ngày làm việc (`np.busday_count` không có danh sách nghỉ lễ), không phải phiên giao
       dịch. Tháng có ngày nghỉ ở đầu (1/1, Tết, 2/9) sẽ lệch.
    2. `_next_weekday` không bỏ ngày nghỉ, nên nến 14:30 có thể nạp vị thế cho một ngày không giao dịch.
    3. Ngày đáo hạn luôn là thứ Năm thứ ba, không dời khi trùng ngày nghỉ.

    Sửa ba chỗ này là đổi luật và tính là lần thử mới. Quyết định sửa hay không phải chốt trước khi mở khoảng khoá.

## 4. Dự đoán bác bỏ

Chấm trên khoảng khoá ở mục 7, tham số giữ nguyên.

- B1: Lợi suất trung bình của các phiên Long không lớn hơn lợi suất trung bình của mọi phiên còn lại cộng 0,8 điểm.
  Khi đó chân Long chỉ đang ăn xu hướng tăng chung của VN30, không có hiệu ứng lịch.
- B2: Lợi suất trong phiên của thứ Hai có gap ≤ 0 không thấp hơn lợi suất trong phiên của các ngày thường khác có gap
  ≤ 0. Khi đó chân Short thứ Hai chỉ là "gap âm thì giảm tiếp", không phải hiệu ứng thứ Hai, và cơ chế giải chấp sai.
- B3: Chân nào có lãi sau phí ≤ 0 trên khoảng khoá, khi chân đó đã có ít nhất 15 lần kích hoạt, thì bỏ chân đó. Nếu
  hơn một nửa số chân bị bỏ, giả thuyết Calendar sai ở mức sleeve.

## 5. Tiêu chí chấp nhận

Ngưỡng của dự án (gate trong `PS_V30_Vien_Calibrum/native_verification.json`) áp cho cả ensemble: Sharpe sau phí
≥ 1,5, margin sau phí ≥ 15 bps, ít nhất 180 lệnh, Futures Leak và Overfit PASS.

Calendar là một sleeve nên cần qua cả ba điều sau:

- Lãi sau phí trên khoảng khoá, và dương ở cả 3 giai đoạn IS, OOS, FWD của lab (đã đạt: +998,9; +550,0; +779,4 điểm,
  Sharpe 2,04; 1,83; 1,65). Đây là sleeve ổn định nhất qua các giai đoạn.
- Bỏ Calendar khỏi ensemble làm Sharpe của ensemble giảm trên khoảng khoá. Trên lab giai đoạn FWD, R + S có Sharpe
  1,65, còn R + S + C có 2,36.
- Không chân nào chiếm quá 60% lãi của sleeve. Phép thử này chưa chạy.

## 6. Ngân sách lần thử

Những lần thử đã biết:

| Lần thử | Số biến thể | Nguồn |
|---|---:|---|
| Năm chân luật, mỗi chân có cờ bật tắt | ≥ 5 | `config.json` |
| Chọn tập thứ trong tuần cho chân Long (trong 5 ngày) | chưa biết | `calendar_long_dows` |
| Ngưỡng gap thứ Hai | ≥ 1 | `calendar_monday_max_gap` |
| Bản đóng băng | 1 | `PS_V30_Vien_Calibrum/` |

Tổng tối thiểu: 7. Chọn thứ Ba và thứ Tư trong 5 ngày có thể đã thử tới 31 tập con; nếu có log, đếm thêm vào đây.
`docs/calendar.md` có thống kê theo từng chân trên in-sample (hit rate Short thứ Hai 72,7%, Long 61,6%), nên từng chân
đã được xem riêng.

Lần chấm tiếp theo không có lưới tham số. Chạy bản đóng băng, cộng 5 lần bỏ từng chân một để chấm B3. Thêm 5 lần thử,
N tối thiểu thành 12. DSR tính với N = 12 và ghi rõ đó là cận dưới.

## 7. Dữ liệu

| Khoảng | Ngày | Vai trò hiện tại | Số lần đã nhìn |
|---|---|---|---|
| In-sample | 02/01/2020 đến 30/12/2022 | Chọn chân luật và tham số | Nhiều |
| OOS cũ | 01/01/2023 đến 19/12/2024 | Validation | ≥ 4: notebook Native SDK, lab 7 tổ hợp, so sánh 8 cách ensemble, Plutus vote và sum |
| Forward cũ | 01/01/2025 đến 01/10/2026 | Validation | ≥ 4, cùng các lần trên |
| Khoá | từ 02/10/2026 | Kiểm tra cuối | 0 |

Hai khoảng 2023 đến 2026 đã dùng để so và chọn, nên không còn là out-of-sample. Kiểm tra cuối chỉ dùng dữ liệu từ
02/10/2026 trở đi, mở một lần khi Calendar đã có ít nhất 60 lệnh. Với khoảng 70 lệnh mỗi năm trên lab, mốc này đến sau
khoảng 10 tháng. Chân đáo hạn chỉ kích hoạt khoảng 12 lần mỗi năm và chân trước kỳ nghỉ khoảng 5 đến 6 lần, nên B3 cho
hai chân này cần dữ liệu lâu hơn; chưa đủ 15 lần thì ghi "chưa đủ mẫu", không phán quyết.
