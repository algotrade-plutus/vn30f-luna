# Kịch bản thuyết trình (tiếng Việt)

Lời nói cho deck Calibrum, mỗi slide một đoạn, theo đúng thứ tự trong deck. Thời lượng mục tiêu khoảng 38 phút. Thời
gian ghi theo từng slide; tổng cộng dồn ở cuối mỗi phần. Số liệu khớp với slide và các chương của báo cáo. Thuật ngữ
trên slide là tiếng Anh nên khi nói vẫn giữ nguyên tên: Sharpe, drawdown, basis, sleeve, in-sample, out-of-sample.

## Mở đầu (khoảng 3,5 phút)

### 1. Calibrum (bìa) · 0:30

Xin chào thầy cô và các bạn. Em là Phan Quốc Viễn. Hôm nay em trình bày Calibrum, một chiến lược giao dịch hợp đồng
tương lai chỉ số VN30 trên nến 30 phút. Chiến lược gộp ba ý tưởng giao dịch nhỏ thành một vị thế. Em phát triển nó theo
bước 1 đến bước 6 của quy trình 9 bước của ALGOTRADE, và hôm nay em sẽ đi lần lượt theo đúng các bước đó.

### 2. VN30F1M: đòn bẩy cao, nhiều nhà đầu tư cá nhân, thanh toán bằng tiền · 1:00

Trước hết là thị trường. Em giao dịch hợp đồng tháng gần nhất của chỉ số VN30, tức 30 cổ phiếu lớn nhất sàn HOSE. Một
điểm chỉ số tương ứng 100.000 đồng mỗi hợp đồng. Thị trường giao dịch từ 9 giờ đến 14 giờ 45, có nghỉ trưa, và 15 phút
cuối là phiên khớp lệnh định kỳ đóng cửa. Hợp đồng đáo hạn vào thứ Năm tuần thứ ba của tháng và thanh toán bằng tiền
theo chỉ số. Chi phí gồm phí của HNX, của VSDC và thuế chuyển nhượng.

Điều em muốn mọi người nhớ là ô cuối cùng: nhà đầu tư không được bán khống cổ phiếu trong rổ. Vì vậy việc kinh doanh
chênh lệch giữa hợp đồng và chỉ số diễn ra chậm, và một trong ba ý tưởng của em dựa vào chính điều này.

### 3. Vì sao kết hợp nhiều nguồn alpha · 1:00

Một thuật toán giao dịch tốt nên kết hợp nhiều nguồn alpha. Nguồn alpha nào cũng có giai đoạn chạy tốt và giai đoạn chạy
kém. Nếu các nguồn dựa trên những cơ chế khác nhau, giai đoạn kém của nguồn này thường rơi vào giai đoạn tốt của nguồn
kia, nên gộp lại thì lợi nhuận đều đặn hơn. ALGOTRADE cũng nói ý này trong bài về phân bổ vốn: các chiến lược không tương
quan với nhau giúp tăng Sharpe và rút ngắn thời gian phục hồi sau drawdown.

Calibrum áp dụng nguyên tắc đó với ba nguồn alpha: lịch, basis và momentum. Câu hỏi của đề tài là: gộp ba nguồn này lại
có cho ra một chiến lược đứng vững ngoài mẫu, sau chi phí thật hay không? Để trả lời, em dùng hai engine. Engine lab chạy
nhanh, kiểm tra riêng phần alpha. Sàn giả lập Plutus kiểm tra alpha cộng với khớp lệnh, với hợp đồng thật, phí thật và ký
quỹ. Và trước mỗi phép thử, em đều viết ra luật chọn và đếm số lần thử.

### 4. Quy trình 9 bước: hôm nay trình bày bước 1 đến 6 · 0:45

Đây là lộ trình. Các ô tô đậm là sáu bước em trình bày hôm nay: giả thuyết, dữ liệu, luật, backtest in-sample, tối ưu
và backtest out-of-sample. Các ô viền đứt nét, từ paper trading đến giao dịch thật, là phần sau của công việc này.

Tổng cộng dồn: 3:15

## Bước 1: Hình thành giả thuyết (khoảng 6 phút)

### 5. 01 Forming Algorithm Hypotheses (mở đầu bước) · 0:15

Bước một: các ý tưởng đến từ đâu.

### 6. Ba ý tưởng, ba nguồn alpha · 1:00

Mỗi sleeve đến từ một con đường khác nhau. Calendar đến từ kinh nghiệm của chính em: khoảng hai tháng giao dịch ảo mỗi
ngày từ tháng 8 năm 2026, cộng với các hiệu ứng lịch đã được ghi nhận ở thị trường khác. Basis đến từ việc quan sát
basis, tức chênh lệch giữa hợp đồng và chỉ số. Momentum đến từ các nghiên cứu về momentum. Theo cách phân loại của
ALGOTRADE, đây là ba nguồn alpha khác nhau: kinh nghiệm giao dịch và thiên kiến hành vi, định giá sai và cấu trúc thị
trường, và mô hình thống kê.

### 7. Có những phiên buộc nhà đầu tư phải hành động · 1:15

Calendar có hai lớp. Các chân chính là những gì em thấy khi giao dịch ảo. Thứ Hai, nếu thị trường không mở cửa tăng,
thường giảm: tin xấu dồn lại qua cuối tuần, và công ty chứng khoán xử lý tài khoản thiếu ký quỹ vào đầu tuần, nên có
những người bị buộc phải bán. Thứ Ba và thứ Tư thường tăng lại sau khi lực bán đó đã hết.

Các chân phụ lấy từ các nghiên cứu. Đầu tháng, vì có dòng tiền vào theo chu kỳ tháng như lương hay tiền góp vào quỹ.
Phiên trước kỳ nghỉ, khi người đang bán khống hợp đồng đóng vị thế trước kỳ nghỉ dài. Và ngày đáo hạn, khi phần chiết
khấu của hợp đồng buộc phải thu hẹp lúc thanh toán. Chân nào cũng trả lời cùng một câu hỏi: hôm đó ai bị buộc phải giao
dịch.

### 8. Các chân Calendar trên dữ liệu in-sample · 1:00

Đây là phần kiểm tra trên dữ liệu in-sample. Hai chân chính rất rõ: chân thứ Hai lỗ trung bình 12 điểm, với p-value
hoán vị 0,003, và thứ Ba, thứ Tư cũng có p bằng 0,003. Các chân phụ thì khác. Phiên trước kỳ nghỉ chỉ có khoảng năm lần
mỗi năm, trong in-sample em chỉ có bảy lần. Xét từng chân thì chúng quá hiếm để chứng minh. Vì vậy em giữ chúng dựa trên
bằng chứng đã công bố và cơ chế, chứ không phải dựa trên bảng này, và em sẽ kiểm tra chúng gộp thành một nhóm ở bước 5.

### 9. Hợp đồng lệch khỏi chỉ số, rồi quay về · 1:15

Tiếp theo là sleeve Basis. Basis là giá hợp đồng trừ chỉ số. Nó hiếm khi bằng 0: khoảng cách trung vị là 4,1 điểm, và chỉ có
13,7 phần trăm số nến nằm trong khoảng một điểm. Basis cũng thu hẹp dần khi gần đáo hạn, từ 6,5 điểm khi còn ba tuần
xuống 3,6 điểm trong hai ngày cuối.

Vì sao nó quay về? Basis có một phần chậm, là chi phí vốn và tâm lý chung của thị trường, và một phần nhanh: nhà đầu tư
cá nhân dùng đòn bẩy mua đuổi rồi bán tháo hợp đồng nhanh hơn ba mươi cổ phiếu lớn có thể theo kịp. Không bán khống được
thì arbitrage diễn ra chậm, nên phần nhanh tồn tại đủ lâu để giao dịch. Sleeve này đo phần nhanh đó bằng z-score so với 40
nến gần nhất, và đánh ngược lại khi z-score vượt 1,5.

### 10. Momentum trong phiên, đo theo nhiều cách · 1:15

Còn sleeve Momentum. Momentum là một trong những hiệu ứng được ghi nhận nhiều nhất trong tài chính: cổ phiếu tăng thì tiếp tục
tăng, hợp đồng tương lai giữ xu hướng so với chính nó, và trong một ngày thì nửa giờ đầu dự báo được nửa giờ cuối. Mỗi
cách đo momentum chỉ là một tín hiệu yếu. Vì vậy sleeve này đo momentum trong phiên theo năm cách: so với giá mở cửa, trong
hai giờ, trong một nến, và thêm một lực kéo ngược là khoảng cách tới VWAP. Sau đó gộp chúng bằng hồi quy Ridge, một mô hình tuyến
tính có phạt. Phần phạt giữ các trọng số nhỏ và ổn định, và vì mô hình là tuyến tính nên em đọc được từng trọng số.

Tổng cộng dồn: 9:15

## Bước 2: Chuẩn bị dữ liệu (khoảng 6 phút)

### 11. 02 Data Preparation (mở đầu bước) · 0:15

Bước hai: dữ liệu.

### 12. Hai engine, mỗi engine đọc hợp đồng và chỉ số · 1:00

Em dùng hai engine cho hai mục đích. Lab kiểm tra riêng phần alpha; Plutus kiểm tra alpha cộng với khớp lệnh. Mỗi engine
đọc hai dòng dữ liệu: VN30F1M, là hợp đồng mình giao dịch, và chỉ số VN30, chỉ dùng cho sleeve Basis. Lab lấy cả hai từ
nến 30 phút của DNSE và suy ra mã hợp đồng từ lịch của sàn. Plutus dựng cả hai từ tick trong algotradeDB, giao dịch đúng
hợp đồng thật và tính đúng phí HNX, VSDC và thuế.
### 13. Một phiên dữ liệu, ngày 3/6/2021 · 1:15

Dữ liệu trông như thế này, một phiên. Bên trái là mười nến hợp đồng, có giá mở, cao, thấp, đóng, khối lượng và mã hợp
đồng. Bên phải là giá đóng của chỉ số. Mỗi nến gắn nhãn theo giờ bắt đầu: nến 10 giờ chạy đến 10 giờ 30, nên giá đóng
của nó đến 10 giờ 30 mới biết. Cột basis không có trong dữ liệu; đó là thứ sleeve Basis tính ra, giá đóng hợp đồng trừ
giá đóng chỉ số. Mọi người để ý nến 11 giờ 30: chỉ số không có nến này, nên sleeve dùng giá đóng chỉ số gần nhất đã
biết, không bao giờ dùng một giá đến sau.
### 14. Bảng tính của lab, từng nến · 1:30

Đây là bảng mà lab dựng ra, trên cùng phiên đó; từ 13 giờ em đổi vị thế để minh hoạ thêm vài trường hợp. Pos là vị
thế quyết định ở giá đóng của mỗi nến; HoldPos là vị thế cầm trong nến, chính là Pos của nến trước. Lúc 9 giờ, chiến
lược vẫn cầm lệnh mua qua đêm, được cộng 5,6 điểm và trả 0,4 phí để thoát. Lúc 10 giờ 30 nó mua và trả 0,4, nhưng nến
đó chưa lãi gì. Lúc 13 giờ nó đảo từ mua sang bán: thay đổi hai đơn vị nên phí 0,8, trong khi nến đó vẫn ăn phần tăng
10,7 điểm của lệnh mua. Lúc 13 giờ 30 lệnh bán có lãi vì giá giảm. Lúc 14 giờ nó đóng lệnh bán, trả 0,4 phí và chịu lỗ
của lệnh bán trong nến đó. Cộng cột Net lại thì ra D, cộng 10,5 điểm. Các metric
cũng tính từ đây. Sharpe lấy D của mọi phiên, trung bình chia độ lệch chuẩn, nhân căn 252. Margin lấy tổng Net chia
cho giá trị đã giao dịch, ở đây 10,5 chia 7.506, khoảng 14 bps. Max drawdown là mức sụt lớn nhất của Net cộng dồn, ở
đây từ 14,4 xuống 10,5, tức 3,9 điểm.

### 15. Ba giai đoạn, cùng mốc thời gian ở cả hai engine · 0:45

Dữ liệu chia làm ba giai đoạn. In-sample từ tháng 6 năm 2021 đến tháng 12 năm 2022; tháng 6 năm 2021 là ngày đầu tiên có
trong cơ sở dữ liệu, nên cả hai engine chạy trên đúng 401 phiên giống nhau. Out-of-sample là năm 2023 và 2024. Năm 2025
không dùng, và forward là từ đầu năm 2026 đến tháng 10, lần kiểm tra cuối cùng trước paper trading.
### 16. Đổi hợp đồng: chuỗi liên tục bị nhảy giá · 1:00

VN30F1M luôn là hợp đồng gần đáo hạn nhất. Sau ngày đáo hạn, chuỗi DNSE chuyển sang hợp đồng mới mà không điều chỉnh giá
và không có mã, nên đêm đầu tiên sau đáo hạn có gap trung bình 9,5 điểm, so với 4,5 điểm ở các đêm khác. Phần nhảy thêm
đó là chênh lệch giá giữa hai hợp đồng, không phải biến động của thị trường. Em dựng lại mã hợp đồng từ lịch của sàn, và
nó khớp với cơ sở dữ liệu ở mọi phiên. Giá giữ nguyên gốc, vì sleeve Basis cần giá của đúng hợp đồng đang giao dịch.
Sleeve Basis khởi động lại ở mỗi hợp đồng mới, và cả chiến lược về 0 từ 14 giờ ngày đáo hạn, nên không vị thế nào vắt
qua lúc đổi hợp đồng.

Tổng cộng dồn: 15:00

## Bước 3: Chuyển giả thuyết thành luật (khoảng 4 phút)

### 17. 03 From Hypotheses to Rules (mở đầu bước) · 0:15

Bước ba: biến mỗi giả thuyết thành luật cụ thể. Em viết luật bằng tham số; giá trị cụ thể để sang bước 4.

### 18. Một điểm số từ năm đặc trưng momentum · 1:00

Sleeve Momentum tính một điểm số: hệ số chặn beta không, cộng năm đặc trưng, mỗi đặc trưng trừ tâm mu, chia thang s và
cắt ở cộng trừ c, rồi nhân với beta. Giả thuyết chỉ quy định dấu: bốn beta đầu dương, khoảng cách tới VWAP âm. Luật là:
mua khi điểm số trên theta M, bán khi dưới âm theta M. Thoát lệnh khi lỗ L M điểm, khi điểm số đổi dấu sau h M nến,
hoặc sau H M nến.

### 19. Đánh ngược khi z-score của basis ở mức cực trị · 1:00

Sleeve Basis tính basis và z-score của nó trên cửa sổ W nến. Mua khi Z dưới âm z in, bán khi Z trên dương z in. Nó đảo
chiều khi Z chạm cực trị bên kia sau h B nến, thoát khi lỗ L B điểm, hoặc khi Z quay về trong khoảng z out.

### 20. Vị thế chỉ phụ thuộc vào ngày · 0:45

Calendar không cần chỉ báo nào. Mua vào các thứ thuộc tập D long, k phiên đầu tháng và phiên trước kỳ nghỉ. Bán vào thứ
Hai thông thường nếu gap mở cửa không quá g max. Mua vào thứ Năm ngày đáo hạn cho đến T end. Mỗi chân phụ có thể bật
hoặc tắt.

### 21. Gộp các sleeve · 1:00

Mỗi sleeve cho ra âm một, không hoặc dương một, và ensemble gán trọng số w M, w B, w C. Majority vote lấy dấu của tổng có
trọng số: nó vào đủ một vị thế ngay khi các sleeve nghiêng về một phía. Sum giữ nguyên tổng có trọng số, nên khối lượng
tăng theo mức đồng thuận. Trên Plutus, vote giao dịch N hợp đồng cho mỗi đơn vị vị thế.

Các luật thời gian ở bước 2 áp dụng cho cả hai: khớp ở nến kế tiếp, phiên ATC giữ vị thế 14 giờ, và về 0 từ 14 giờ
ngày đáo hạn.

Tổng cộng dồn: 19:00

## Bước 4: Backtest in-sample (khoảng 7 phút)

### 22. 04 In-Sample Backtesting (mở đầu bước) · 0:15

Bước bốn. Trước hết là giá trị ban đầu của tham số, rồi cách đo, rồi kết quả in-sample.

### 23. Giá trị ban đầu: gói đóng băng giữ nguyên · 1:00

Bước bốn chạy luật với đúng giá trị có sẵn trong gói đóng băng, chưa chỉnh gì. Với Momentum là năm hệ số beta cùng tâm
và thang chuẩn hoá; cả năm dấu đều khớp với giả thuyết. Các hệ số này được fit trên dữ liệu 2020 đến 2022 trước khi
đóng gói, trùng với in-sample, và em sẽ quay lại điểm này ở bước 6. Ngưỡng vào lệnh là 0,18, giữ từ 2 đến 8 nến, cắt lỗ
10 điểm. Basis dùng cửa sổ 40 nến, vào lệnh ở z-score 1,5 và cắt lỗ 14 điểm. Calendar mua thứ Ba, thứ Tư và hai phiên
đầu tháng, ngưỡng gap thứ Hai là 0. Ba sleeve có trọng số bằng nhau.

### 24. Cách lab chấm điểm một chiến lược · 1:00

Trong lab, mỗi nến được tính bằng vị thế trước đó nhân với thay đổi giá, trừ 0,4 điểm cho mỗi đơn vị thay đổi vị thế.
Sharpe tính trên lãi lỗ điểm theo ngày, kể cả những ngày không giao dịch, và quy ra năm bằng căn của 252. Margin ở đây
là lợi nhuận trên mỗi đơn vị giá trị giao dịch, tính bằng basis point, không phải tiền ký quỹ. Max drawdown là mức sụt
lớn nhất của lãi lũy kế tính từ một đỉnh trước đó.

### 25. Cách Plutus chấm điểm một chiến lược · 0:45

Plutus đo bằng tiền. Sharpe tính trên lợi suất theo ngày của tài khoản. Lãi lỗ bằng đồng chia cho 100.000 thì ra điểm
chỉ số. Còn tỷ lệ sử dụng ký quỹ là phía tiền ký quỹ: ký quỹ yêu cầu chia cho tài sản ký quỹ, có cảnh báo ở 80 phần
trăm và gọi ký quỹ ở 90 phần trăm.

### 26. Cùng một phiên trên hai engine · 1:00

Giờ áp hai công thức vào một phiên. Bên trái là lab, trên một phiên: vote ngày 3 tháng 6 năm 2021. Đường kẻ là giá của từng nến 30
phút, vùng tô màu là những nến đang giữ vị thế mua. Lúc 9 giờ, vị thế chuyển từ dương một về không. Nến đó vẫn được tính phần biến động qua đêm của
vị thế đang giữ, cộng 5,6 điểm, và trả 0,4 điểm phí thoát lệnh. Lúc 10 giờ 30 em vào lệnh mua lại và trả thêm 0,4. Cộng
các cột ở phía dưới lại sẽ ra kết quả của phiên, D bằng cộng 10,1 điểm. Sharpe của lab là trung bình của các D theo ngày chia cho độ
lệch chuẩn, nhân căn của 252.

Bên phải, Plutus ghi tài khoản mỗi phiên một lần. Vốn ban đầu là 300 triệu; r là phần trăm thay đổi của tài khoản sau phí
theo từng ngày, và Sharpe của Plutus tính trên r theo cùng cách đó. Vì vậy hai con số Sharpe không so trực tiếp được: một
cái tính trên điểm của một hợp đồng, một cái tính trên lợi suất của vốn.

### 27. Cả hai ensemble đều lãi trong in-sample · 1:00

Trong lab, tính cho một hợp đồng, majority vote lãi 1.579 điểm với Sharpe 3,70. Sum lãi 800 điểm với Sharpe 3,60. Vote
lãi nhiều hơn vì nó giữ đủ một hợp đồng mỗi khi có hai sleeve đồng ý. Nhưng mọi người hãy nhìn drawdown: sum chỉ 40
điểm, còn vote là 88 điểm.

### 28. Lãi sau phí thật, cách xa ngưỡng gọi ký quỹ · 1:00

Trên Plutus, với 300 triệu và tối đa ba hợp đồng, vote lãi 150 phần trăm trong giai đoạn in-sample, còn sum lãi 104 phần
trăm. Sum có Sharpe cao hơn, 4,37 so với 4,12, và drawdown thấp hơn, 3,2 so với 5,1 phần trăm. Mức sử dụng ký quỹ cao
nhất chỉ khoảng 20 phần trăm, không có cảnh báo hay lần gọi ký quỹ nào.

### 29. Cùng chiều, khác cách khớp lệnh · 1:00

Hai engine so với nhau thế nào? Có ba điểm. Dữ liệu khớp nhau: lab cho cùng một kết quả trên DNSE và trên cơ sở dữ
liệu, sai khác dưới một phần trăm. Chi phí thật thấp hơn lab giả định, khoảng 0,13 điểm mỗi hợp đồng mỗi chiều so với
0,4. Và thời điểm khớp lệnh khác nhau: lãi lỗ theo ngày của hai engine tương quan 0,89, và lệnh nào không khớp được thì
được gửi lại ở nến sau. Vì vậy độ lớn có khác, nhưng chiều của mọi kết quả đều giống nhau.

Tổng cộng dồn: 26:00

## Bước 5: Tối ưu (khoảng 7 phút)

### 30. 05 Optimization (mở đầu bước) · 0:15

Bước năm. Ở bước này rủi ro lớn nhất là tự đánh lừa mình, nên em bắt đầu bằng luật.

### 31. Luật chọn, chốt trước khi chạy phép thử · 1:00

Ba luật, viết ra trước khi chạy. Sharpe sau phí là thước đo quyết định. Chênh lệch dưới 0,2 thì coi là hoà, và khi hoà
thì chọn phương án có drawdown thấp hơn, rồi đến phương án ít luật hơn. Lưới tham số chỉ dùng để kiểm tra độ ổn định:
các giá trị lân cận của tham số gốc phải vẫn lãi và giữ ít nhất 70 phần trăm Sharpe, và em không bao giờ thay tham số
gốc bằng giá trị lân cận. Tổng cộng có sáu lần thử mới, liệt kê ở bên phải. Em cũng xin nói rõ: lúc viết luật này, em đã
thấy kết quả của vote và sum.

### 32. Mỗi sleeve thêm vào đều nâng Sharpe · 0:45

Từng sleeve riêng lẻ đạt Sharpe từ 1,8 đến 2,3. Ghép bất kỳ hai sleeve nào thì đạt 3,1 đến 3,3. Cả ba thì đạt 3,6 đến
3,7. Thêm sleeve nào vào cũng làm kết quả tốt lên.

### 33. Lãi nhiều hơn hay drawdown ít hơn · 0:45

Biểu đồ này cho thấy sự đánh đổi. Vote lãi nhiều nhất. Sum có drawdown thấp nhất, thấp hơn hẳn. Các cấu hình khác nằm ở
giữa.

### 34. Các sleeve gần như không đi cùng nhau · 0:45

Đây là lý do việc gộp có hiệu quả. Momentum và Basis tương quan 0,17, Momentum và Calendar 0,14, còn Basis và Calendar là
âm 0,21: cái này hay lãi đúng lúc cái kia lỗ.

### 35. Mỗi sleeve kiếm tiền vào những tháng khác nhau · 0:45

Nhìn theo từng tháng sẽ thấy rõ. Tháng 9 và tháng 10 năm 2022, Calendar lỗ trong khi Momentum lãi. Tháng 5 năm 2022, Basis
lỗ trong khi Calendar và Momentum lãi. Ensemble vote chỉ lỗ một tháng trong mười chín tháng.

### 36. Khi các sleeve đồng ý, lợi thế mỗi nến tăng gấp đôi · 1:00

Biểu đồ này giải thích sự khác nhau giữa vote và sum. Một nửa thời gian chỉ có một sleeve đứng về một phía. Khi có hai
sleeve đồng ý, giá ở nến kế tiếp đi theo hướng đó gần gấp đôi: 0,84 điểm so với 0,45. Vote vào đủ một hợp đồng chỉ từ một
sleeve; sum thì tăng khối lượng theo mức đồng thuận. Đó là lý do drawdown của sum thấp hơn nhiều.

### 37. Ba phép kiểm tra trên các sleeve · 1:00

Ba phép kiểm tra. Calendar đầy đủ các chân hơn Calendar chỉ có chân chính 0,45 Sharpe, nên giữ các chân phụ. Ngưỡng của
Momentum ổn định: hai giá trị lân cận đều giữ được khoảng 90 phần trăm Sharpe. Cửa sổ của Basis không ổn định ở phía ngắn:
cửa sổ 30 nến chỉ giữ được 63 phần trăm. Theo luật, em giữ nguyên cửa sổ 40 và theo dõi điểm này ở giai đoạn ngoài mẫu.

### 38. Mang sang bước 6 · 0:30

Quyết định là: ensemble chính thức là equal-weight sum, vì Sharpe hoà với vote mà drawdown chưa bằng một nửa. Vote chạy
song song để tham khảo. Mọi tham số giữ nguyên như bản đóng băng.

Tổng cộng dồn: 32:45

## Bước 6: Backtest out-of-sample (khoảng 4,5 phút)

### 39. 06 Out-of-Sample Backtesting (mở đầu bước) · 0:15

Bước sáu, phép thử ngoài mẫu.

### 40. Vẫn lãi ngoài mẫu, nhưng lợi thế mỏng hơn · 1:00

Trong lab, cả hai ensemble vẫn lãi ở giai đoạn 2023 đến 2024 và ở năm 2026. Nhưng lợi thế giảm dần: Sharpe của sum từ
3,60 ở in-sample xuống 2,36, rồi 1,54, và lợi nhuận trên mỗi đơn vị giao dịch giảm còn một nửa. Ở giai đoạn nào sum cũng
có drawdown thấp hơn vote.

### 41. Phí thật, hợp đồng thật, vẫn lãi · 1:00

Trên Plutus, sum lãi 46 phần trăm trong 2023 đến 2024, Sharpe 2,78, drawdown 3,2 phần trăm; và lãi 36 phần trăm từ
tháng 1 đến tháng 10 năm 2026, Sharpe 2,56, drawdown 5,1 phần trăm. Không lần chạy nào bị gọi ký quỹ. Hai lần chạy
forward bị đánh dấu FAILED vì Plutus không đánh giá được hai phiên và đã loại chúng ra.

### 42. Phần suy giảm đến từ Momentum · 1:00

Suy giảm đến từ đâu? Mọi người nhìn ô bên trái. Basis và Calendar giữ Sharpe trên 1,3 ở mọi giai đoạn. Momentum giảm từ
2,23 ở in-sample xuống 0,91, rồi lỗ trong năm 2026. Các ensemble đi xuống theo Momentum, nhưng vẫn dương.

### 43. Xử lý Momentum thế nào · 1:15

Có hai cách giải thích. Trọng số của Momentum được fit trên giai đoạn 2020 đến 2022, trùng với in-sample, nên kết quả
in-sample của nó bị thổi phồng. Và lợi thế momentum có thể đang mất dần, đúng như protocol của em đã dự đoán. Phán quyết
tạm thời của em là bỏ Momentum khỏi tín hiệu chính, hoặc fit lại nó.

Nhưng em không vội bỏ Momentum. Ở bên phải, nếu chỉ có Basis và Calendar thì năm 2026 tốt hơn, nhưng giai đoạn 2023 đến
2024 lại kém hơn, và drawdown cao hơn ở mọi giai đoạn. Hơn nữa, em chọn tổ hợp này sau khi đã thấy dữ liệu, nên nó chỉ là
một ứng viên mới, chưa phải là kết quả.

Tổng cộng dồn: 37:15

## Kết (khoảng 1 phút)

### 44. Summary · 1:00

Tóm lại. Ba sleeve độc lập, gộp bằng equal-weight sum, vẫn lãi ngoài mẫu sau phí giao dịch thật. Drawdown ở khoảng 3 đến
5 phần trăm trên 300 triệu đồng, không có lần gọi ký quỹ nào. Và Momentum đang suy giảm, nên phép thử tiếp theo, trên dữ
liệu mới từ tháng 10 năm 2026, sẽ chạy song song chiến lược đầy đủ và phiên bản không có Momentum. Em xin cảm ơn thầy cô và
các bạn đã lắng nghe, em xin sẵn sàng trả lời câu hỏi.

Tổng: khoảng 38:15
