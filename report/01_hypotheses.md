# 1. Hình thành giả thuyết

Chương 0 đã nói lý do: một thuật toán giao dịch tốt nên kết hợp nhiều nguồn alpha có cơ chế khác nhau. Chương này
trình bày ba nguồn mà Calibrum dùng. Mỗi nguồn đến từ một con đường khác nhau, và ứng với một trong tám nguồn alpha của
ALGOTRADE Knowledge Hub.

| Sleeve | Ý tưởng đến từ đâu | Nguồn alpha |
|---|---|---|
| Calendar | Hai tháng giao dịch ảo mỗi ngày, cộng các hiệu ứng lịch đã được ghi nhận | Kinh nghiệm giao dịch, thiên kiến hành vi |
| Basis | Quan sát chênh lệch giữa hợp đồng và chỉ số (basis) | Định giá sai, cấu trúc thị trường Việt Nam |
| Momentum | Các nghiên cứu về momentum, gộp bằng một mô hình tuyến tính có phạt | Mô hình thống kê, thiên kiến hành vi |

Mỗi sleeve được trình bày theo cùng một thứ tự: ý tưởng đến từ đâu, giả thuyết, cơ chế (ai trả tiền cho mình), và khi
nào lợi thế sẽ mất. Protocol đầy đủ, gồm dự đoán bác bỏ và ngân sách lần thử, nằm ở
`research/calibrum/<sleeve>/PROTOCOL.md`. Trong code và trong thư mục `research/`, sleeve Basis mang tên cũ là `shinji`, sleeve
Momentum mang tên cũ là `ridge` (Ridge H2).

## 1.1 H1: dòng tiền theo lịch (Calendar)

Calendar có hai lớp. Các chân chính đến từ quan sát trực tiếp và xảy ra đủ thường xuyên để kiểm tra. Các chân phụ đến
từ những hiệu ứng lịch đã được ghi nhận ở thị trường khác, và mỗi năm chỉ xảy ra vài lần.

### Chân chính: thứ Hai và giữa tuần

#### Quan sát

Ý tưởng đến từ khoảng hai tháng giao dịch ảo mỗi ngày trên VPS, bắt đầu từ tháng 8 năm 2026. Thứ Hai phần lớn là ngày
giảm, còn thứ Ba và thứ Tư tăng rõ hơn hẳn so với thứ Hai.

#### Giả thuyết

Thứ Hai thông thường, nếu mở cửa không tăng (gap ≤ 0), có lợi suất trong phiên âm. Phiên thứ Ba và thứ Tư có lợi suất
trung bình dương.

#### Cơ chế

- Thứ Hai: tin xấu dồn lại qua cuối tuần, và công ty chứng khoán xử lý các tài khoản vi phạm tỷ lệ ký quỹ vào đầu tuần.
  Người trả tiền là người bị buộc phải bán. Điều kiện gap ≤ 0 loại bỏ những thứ Hai mở cửa với tin tốt. Hiệu ứng cuối
  tuần đã được ghi nhận từ lâu trên thị trường cổ phiếu (French, 1980).
- Thứ Ba và thứ Tư: khi lực bán bắt buộc của thứ Hai đã hết, giá hồi lại. Giải thích này yếu hơn của thứ Hai, vì nó
  chưa chỉ ra được ai là người trả tiền.

### Chân phụ: đầu tháng, trước kỳ nghỉ, ngày đáo hạn

#### Nguồn gốc

Các chân này được bổ sung từ những hiệu ứng lịch đã được ghi nhận ở thị trường khác, sau đó kiểm tra lại trên dữ liệu
in-sample.

#### Giả thuyết

Hai phiên đầu tháng, phiên cuối cùng trước kỳ nghỉ, và phiên đáo hạn hợp đồng có lợi suất trung bình dương.

#### Cơ chế

- Đầu tháng: lợi suất cổ phiếu dồn vào quanh đầu tháng (Ariel, 1987; Lakonishok và Smidt, 1988). Tiền mới vào thị
  trường theo chu kỳ tháng: lương, tiền góp định kỳ vào quỹ, giải ngân của tổ chức. Người bán cho dòng tiền này bán rẻ
  hơn so với vài ngày sau.
- Trước kỳ nghỉ: các phiên trước ngày lễ có lợi suất cao bất thường (Ariel, 1990). Trên VN30F, người đang bán khống hợp
  đồng đóng vị thế trước kỳ nghỉ dài (Tết, 30/4, 2/9). Họ mua lại để khỏi gánh rủi ro qua kỳ nghỉ, chứ không phải vì có
  quan điểm về giá.
- Ngày đáo hạn: trong in-sample, hợp đồng thường giao dịch thấp hơn chỉ số, trung bình khoảng −4,5 điểm khi còn 15 đến
  21 ngày tới đáo hạn, so với +0,6 điểm trong hai ngày cuối (mục 1.2). Thanh toán bằng tiền buộc phần chiết khấu đó phải
  thu hẹp trước cuối phiên đáo hạn, và người đang bán hợp đồng để phòng hộ phải mua lại hoặc chuyển sang hợp đồng sau.
  Vị thế mua trong ngày đáo hạn hưởng phần chiết khấu đang thu hẹp đó. Nếu thị trường chuyển sang trạng thái hợp đồng
  cao hơn chỉ số kéo dài, chân này sẽ yếu đi hoặc đổi chiều.

### Kiểm tra trên dữ liệu in-sample

Nến 30 phút DNSE, 01/06/2021 đến 30/12/2022, 400 phiên có giá đóng cửa phiên trước (`scripts/report_calendar_stats.py`).
Chân mua dùng thay đổi giá từ đóng cửa phiên trước đến đóng cửa phiên này; chân thứ Hai dùng thay đổi từ mở cửa đến
đóng cửa. p-value hoán vị là tỷ lệ trong 20.000 lần bốc ngẫu nhiên cùng số phiên mà trung bình cực đoan bằng hoặc hơn.

| Chân | Số phiên mỗi năm | Số phiên trong IS | Trung bình (điểm) | Số phiên tăng | t | p hoán vị |
|---|---:|---:|---:|---:|---:|---:|
| Thứ Ba hoặc thứ Tư | khoảng 100 | 162 | +2,18 | 56% | 1,54 | 0,003 |
| Thứ Hai thông thường, gap ≤ 0 | khoảng 20 | 32 | −12,19 | 31% | −2,83 | 0,003 |
| Hai phiên đầu tháng | 24 | 37 | +3,14 | 62% | 1,03 | 0,082 |
| Thứ Năm đáo hạn | 12 | 19 | +4,34 | 68% | 1,48 | 0,105 |
| Trước kỳ nghỉ | khoảng 5 | 7 | +8,37 | 86% | 2,70 | 0,094 |
| Gộp các ngày chân phụ | khoảng 40 | 62 | +4,12 | 66% | 2,01 | 0,010 |

Độ lệch chuẩn thay đổi giá một phiên là 20,1 điểm, nên chân nào có ít phiên thì trung bình phải lớn mới nổi bật được.
Hai chân chính rõ ràng. Các chân phụ, xét từng chân, quá hiếm để chứng minh chỉ bằng dữ liệu này: không chân nào có
p-value gần 0,01, là mức phù hợp khi kiểm tra năm chân cùng lúc, và chân trước kỳ nghỉ chỉ dựa trên 7 phiên. Gộp lại
thành một nhóm thì trông mạnh hơn. Mình giữ các chân phụ nhờ bằng chứng đã công bố và cơ chế của chúng, không phải nhờ
bảng này. Một số ngày chân phụ cũng rơi vào thứ Ba, thứ Tư, nên một phần trung bình của chúng có thể là hiệu ứng thứ
trong tuần. Chương 5 quyết định giữ hay bỏ.

### Khi nào lợi thế mất

Các chân dựa trên thói quen vận hành của nhà đầu tư và công ty chứng khoán: khi nào nạp tiền, khi nào xử lý ký quỹ,
khi nào chuyển vị thế phòng hộ. Lợi thế sẽ mờ đi nếu chu kỳ thanh toán hoặc cách xử lý ký quỹ thay đổi, hoặc nếu đủ
nhiều người giao dịch theo lịch khiến hiệu ứng dời sang các phiên trước đó.

## 1.2 H2: chênh lệch basis hồi về (Basis)

### Quan sát

Chênh lệch basis, tức giá hợp đồng trừ chỉ số VN30, hiếm khi gần 0. Nó thường lệch 4 đến 5 điểm, có lúc lên tới 9 đến 10 điểm.

Dữ liệu in-sample cho thấy đúng như vậy (nến 30 phút DNSE, 01/06/2021 đến 30/12/2022, 4.009 nến,
`scripts/report_basis_stats.py`):

| Thống kê | Giá trị |
|---|---|
| Tỷ lệ nến có \|basis\| ≤ 1 điểm | 13,7% |
| Trung vị \|basis\| | 4,1 điểm |
| Phân vị 75 và 90 của \|basis\| | 7,9 và 12,3 điểm |
| Tỷ lệ nến hợp đồng cao hơn chỉ số | 34,5% |
| \|basis\| trung bình khi còn 15 đến 21 ngày tới đáo hạn | 6,5 điểm |
| \|basis\| trung bình khi còn 2 ngày trở xuống | 3,6 điểm |

Basis lệch về cả hai phía, và thu hẹp dần khi gần đáo hạn.

### Giả thuyết

Khi basis lệch khỏi trung bình của chính nó trong 40 nến gần nhất (khoảng năm phiên) từ 1,5 độ lệch chuẩn trở lên, nó
quay về phía trung bình trong các phiên tiếp theo, và phần quay về lớn hơn phí một vòng giao dịch.

### Cơ chế

Basis gồm hai phần.

- Phần chậm: chi phí vốn trừ cổ tức, cộng tâm lý chung của giai đoạn. Phần này đổi dần theo ngày và theo số ngày còn
  lại tới đáo hạn.
- Phần nhanh: nhà đầu tư cá nhân dùng đòn bẩy cao trên phái sinh, mua đuổi khi giá tăng và bán tháo khi giá giảm, đẩy
  hợp đồng đi nhanh hơn rổ 30 cổ phiếu lớn có thể theo kịp.

Hợp đồng thanh toán bằng tiền theo chỉ số VN30 lúc đáo hạn, nên về lâu dài nó bị kéo về chỉ số. Ở Việt Nam, kinh doanh
chênh lệch để đóng khoảng lệch này rất khó: không được bán khống cổ phiếu, còn mua cả rổ thì tốn vốn và phí giao dịch cổ
phiếu. Vì vậy phần lệch nhanh tồn tại đủ lâu để giao dịch. Người trả tiền là những nhà đầu tư dùng đòn bẩy đã đẩy hợp
đồng lệch khỏi chỉ số.

Phần chậm luôn trôi, nên một ngưỡng cố định kiểu "basis trên 5 điểm" sẽ trộn lẫn hai phần. Z-score so với 40 nến gần
nhất chỉ đo phần lệch nhanh.

Chênh lệch basis có thể hồi về theo hai cách: hợp đồng quay về gần chỉ số, hoặc chỉ số chạy theo hợp đồng. Sleeve Basis chỉ giao dịch
hợp đồng, nên chỉ có lãi ở cách thứ nhất.

### Khi nào lợi thế mất

Khi Việt Nam cho bán khống, khi có ETF VN30 rẻ và đủ thanh khoản để làm chân cơ sở, hoặc khi các tổ chức chạy kinh doanh
chênh lệch basis ở quy mô lớn.

## 1.3 H3: quán tính giá trong phiên (Momentum)

### Điểm xuất phát: các nghiên cứu về momentum

Momentum là một trong những hiệu ứng được ghi nhận rộng rãi nhất trên thị trường:

- Jegadeesh và Titman (1993): cổ phiếu tăng giá trong 3 đến 12 tháng qua tiếp tục tốt hơn thị trường trong các tháng
  sau.
- Moskowitz, Ooi và Pedersen (2012): điều tương tự đúng với một tài sản so với chính quá khứ của nó (time-series
  momentum), trên hợp đồng tương lai chỉ số, trái phiếu, tiền tệ và hàng hoá.
- Gao, Han, Li và Zhou (2018): trong cùng một ngày, lợi suất nửa giờ đầu của thị trường dự báo được lợi suất nửa giờ
  cuối (market intraday momentum).

Điểm chung là giá phản ứng chậm rồi đi thành xu hướng. Mỗi cách đo momentum là một tín hiệu riêng, ở một tầm thời gian
riêng. Ý tưởng của sleeve Momentum là đo momentum trong phiên theo nhiều cách cùng lúc rồi gộp lại.

### Giả thuyết

Khi giá đóng của một nến 30 phút đã lệch khỏi giá mở cửa 09:00, khỏi trung bình 4 nến và khỏi giá mở của chính nến đó,
cả ba cùng một chiều, thì VN30F1M tiếp tục đi theo chiều đó trong 2 nến (1 giờ) tiếp theo. Lực đi tiếp yếu dần khi giá
đã cách xa VWAP của phiên.

### Cơ chế

VN30F là thị trường dùng đòn bẩy, khối lượng của nhà đầu tư cá nhân chiếm tỷ trọng lớn. Khi giá đã chạy từ đầu phiên,
người vào muộn đuổi theo, còn người đang ở chiều sai bị buộc thoát ra vì cắt lỗ và gọi ký quỹ. Cả hai đều đẩy giá đi
thêm theo cùng chiều. Khi giá đã cách xa VWAP, những người vào lệnh từ sớm bắt đầu chốt lời; đó là lực kéo ngược ở vế
cuối của giả thuyết.

### Vì sao dùng hồi quy Ridge

Bốn đặc trưng đo momentum ở các tầm thời gian khác nhau trong phiên, đặc trưng thứ năm đo lực kéo về VWAP. Hồi quy Ridge
gộp chúng thành một điểm số. Phần phạt L2 giữ các trọng số nhỏ và ổn định, nên điểm số ít bị overfit hơn hồi quy thường.
Mô hình là tuyến tính: phần phi tuyến nằm trong chính các đặc trưng (chia cho ATR, khoảng cách tới VWAP). Trọng số đọc
được trực tiếp, nên sleeve này minh bạch.

| Đặc trưng | Tầm thời gian | Định nghĩa | Trọng số |
|---|---|---|---:|
| f1 | Cả phiên | (Close − Open lúc 09:00) / ATR14 | +0,1472 |
| f2 | 2 giờ | (Close − SMA4 của Close) / ATR14 | +0,0464 |
| f3 | 1 nến | (Close − Open của nến) / ATR14 | +0,0423 |
| f4 | 4 nến | Độ lệch tăng/giảm của bình phương biến động | +0,0190 |
| f5 | Lực kéo ngược | (Close − VWAP phiên) / ATR14 | −0,0396 |

Trọng số là các hệ số đóng băng trong `PS_V30_Vien_Calibrum/PS_V30_Vien_Calibrum_model.pt`. Khoảng cách so với giá mở
cửa (f1) có trọng số lớn nhất, và khoảng cách tới VWAP (f5) là trọng số âm duy nhất, khớp với cơ chế.

### Khi nào lợi thế mất

Khi tổ chức và giao dịch thuật toán chiếm phần lớn hơn trong khối lượng VN30F, hoặc trong những giai đoạn đi ngang kéo
dài với biên độ ngày hẹp.

## 1.4 Vì sao gộp ba sleeve

Ba sleeve dựa trên ba cơ chế khác nhau: hôm đó ai bị buộc phải giao dịch, hợp đồng lệch khỏi chỉ số bao xa, và người
giao dịch phản ứng thế nào với một đợt giá đang chạy. Vì vậy lãi lỗ của chúng nên gần như độc lập với nhau. Chương 5 đo
tương quan này.

## Tài liệu tham khảo

- Ariel, R. A. (1987). A monthly effect in stock returns. Journal of Financial Economics, 18(1), 161–174.
- Ariel, R. A. (1990). High stock returns before holidays: Existence and evidence on possible causes. Journal of
  Finance, 45(5), 1611–1626.
- French, K. R. (1980). Stock returns and the weekend effect. Journal of Financial Economics, 8(1), 55–69.
- Gao, L., Han, Y., Li, S. Z., and Zhou, G. (2018). Market intraday momentum. Journal of Financial Economics, 129(2),
  394–414.
- Jegadeesh, N., and Titman, S. (1993). Returns to buying winners and selling losers: Implications for stock market
  efficiency. Journal of Finance, 48(1), 65–91.
- Lakonishok, J., and Smidt, S. (1988). Are seasonal anomalies real? A ninety-year perspective. Review of Financial
  Studies, 1(4), 403–425.
- Moskowitz, T. J., Ooi, Y. H., and Pedersen, L. H. (2012). Time series momentum. Journal of Financial Economics,
  104(2), 228–250.
