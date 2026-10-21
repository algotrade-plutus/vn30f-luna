# Mini course thống kê: đọc bảng Calendar như một phiên tòa

Bài này dựa trên chương 76 "Lý thuyết xác suất: khi may rủi đụng logic" của sách *Toán Học Chân Phương* (các mục
74.8 phương sai, 74.11 phân bố chuẩn, 74.14 định lý giới hạn trung tâm và kiểm định giả thuyết, 74.17 phân phối t), và
dùng số liệu Calendar của mình làm ví dụ. Sách *Mathematics for Machine Learning* không có phần kiểm định giả thuyết
(chương 6 chỉ nói về xác suất, chương 8 chỉ nhắc tên), nên không dùng.

Có 5 bài. Đọc theo thứ tự, mỗi bài chỉ một ý.

## Bài 1. Kiểm định giả thuyết giống một phiên tòa

Sách Chân Phương (mục 74.14.4) giải thích bằng phiên tòa:

- Bị cáo được **giả định vô tội** từ đầu.
- Tòa thu thập chứng cứ.
- Chỉ khi chứng cứ **áp đảo** thì mới kết tội. Chứng cứ yếu thì tha.

Kiểm tra một chân Calendar cũng vậy:

| Phiên tòa | Calendar |
|---|---|
| Bị cáo | Chân thứ Hai |
| Giả định vô tội | Thứ Hai **không khác gì** một ngày bình thường. Đây gọi là *giả thuyết không* (H0). |
| Tội danh | Thứ Hai giảm nhiều hơn ngày thường |
| Chứng cứ | 32 phiên thứ Hai trong dữ liệu |
| Kết tội | Kết luận "thứ Hai giảm thật", và dùng nó để giao dịch |

Tòa có thể sai theo hai kiểu:

- **Kết tội oan** (lỗi loại I): chân đó thật ra không có gì, nhưng mình tưởng là có. Hậu quả: giao dịch theo một thứ
  không tồn tại, mất tiền phí.
- **Tha nhầm** (lỗi loại II): chân đó có thật, nhưng chứng cứ không đủ nên mình bỏ qua. Hậu quả: bỏ lỡ cơ hội.

Trong giao dịch, kết tội oan nguy hiểm hơn, nên mình đòi chứng cứ phải mạnh.

## Bài 2. Độ lệch chuẩn: dữ liệu ồn cỡ nào?

Ví dụ trong sách (mục 74.8): chiều cao trung bình của học sinh là 1,7 m, độ lệch chuẩn 8 cm. Nghĩa là phần lớn học
sinh cao gần 1,7 m, lệch lên hoặc xuống khoảng 8 cm.

Với VN30F: một phiên thay đổi trung bình gần 0, nhưng độ lệch chuẩn khoảng **20 điểm**. Nghĩa là một phiên bình thường
có thể tăng hay giảm cỡ 20 điểm.

Vì vậy nhìn **một** phiên thứ Hai giảm 15 điểm thì chẳng nói được gì. Ngày thường cũng hay giảm 15 điểm. Phải nhìn
**trung bình của nhiều phiên**.

## Bài 3. Lấy trung bình nhiều lần thì bớt ồn

Sách (mục 74.14) cho ví dụ: tung một con xúc xắc thì kết quả nhảy lung tung từ 1 đến 6. Nhưng lấy trung bình của 30 lần
tung thì kết quả gần như luôn quanh 3,5, rất ít lệch. Lý do: lần cao và lần thấp bù trừ cho nhau.

Sách đưa ra quy luật: độ ồn của trung bình bằng độ ồn của một lần, chia cho căn bậc hai của số lần.

```text
độ ồn của trung bình = độ lệch chuẩn ÷ √(số phiên)
```

Đại lượng này gọi là **sai số chuẩn** (SE). Với chân thứ Hai:

```text
24,4 ÷ √32 = 24,4 ÷ 5,66 ≈ 4,3 điểm
```

Đọc: giả sử thứ Hai vô tội, trung bình của 32 phiên vẫn có thể lệch khỏi mức bình thường khoảng **±4,3 điểm** chỉ do
may.

Mẫu càng lớn thì càng ít ồn. 162 phiên thứ Ba, thứ Tư chỉ ồn khoảng ±1,4 điểm.

## Bài 4. t: chứng cứ mạnh gấp mấy lần độ ồn?

Sách (mục 74.11) có **luật 68-95-99** của phân bố chuẩn (hình chuông):

- 68% số lần, kết quả nằm trong khoảng ±1 độ lệch chuẩn.
- 95% số lần nằm trong ±2 độ lệch chuẩn.
- 99,7% số lần nằm trong ±3 độ lệch chuẩn.

Nói ngược lại: lệch quá **2** lần độ ồn thì chỉ xảy ra khoảng **5%** số lần nếu không có gì đặc biệt. Lệch quá 3 lần thì
gần như không bao giờ.

Áp vào: lấy trung bình của chân chia cho độ ồn. Con số này gọi là **t**.

```text
t = trung bình ÷ sai số chuẩn
```

Chân thứ Hai: −12,19 ÷ 4,3 ≈ **−2,83**. Trung bình lệch gần 3 lần độ ồn. Chứng cứ mạnh.

Chân thứ Ba, thứ Tư: +2,18 ÷ 1,42 ≈ **1,54**. Lệch chưa tới 2 lần độ ồn. So với 0 thì chứng cứ chưa đủ.

**Câu chuyện của chữ t** (mục 74.17): ông Gosset làm ở nhà máy bia Guinness, chỉ có vài mẫu lúa mạch để thử. Ông thấy
rằng khi mẫu nhỏ, chính độ lệch chuẩn cũng ước lượng không chuẩn, nên phải thận trọng hơn so với hình chuông. Từ đó ra
đời "phân phối t".

Bài học cho mình: chân trước kỳ nghỉ chỉ có **7 phiên**. t = 2,70 nhìn thì mạnh, nhưng với 7 phiên con số này không đáng
tin. Đừng chỉ nhìn t khi mẫu nhỏ.

## Bài 5. p: nếu vô tội, khả năng có chứng cứ mạnh như vậy là bao nhiêu?

**p** trả lời đúng câu hỏi của tòa: *nếu bị cáo vô tội, xác suất tình cờ có được chứng cứ mạnh như vầy là bao nhiêu?*

- p nhỏ: vô tội mà có chứng cứ như vậy thì rất khó, nên mình kết tội.
- p lớn: vô tội cũng dễ có chứng cứ như vậy, nên chưa kết tội được.

Ngưỡng hay dùng là **0,05**, chọn **trước** khi xem dữ liệu (sách gọi là mức ý nghĩa α, mục 74.14.4).

### Cách mình tính p: "tráo ngày"

Mình không dùng công thức mà dùng máy tính:

1. Lấy 162 ngày **bất kỳ** trong in-sample, bốc ngẫu nhiên.
2. Tính trung bình của 162 ngày đó.
3. Lặp lại 20.000 lần.
4. Đếm xem bao nhiêu lần trung bình ngẫu nhiên **tốt bằng hoặc hơn** thứ Ba, thứ Tư.

Kết quả: chỉ khoảng 3 lần trên 1.000 lần (p = 0,003). Nghĩa là nếu thứ Ba, thứ Tư chỉ là ngày bình thường, thì gần như
không thể có trung bình tốt như vậy.

Câu để nói khi thuyết trình: *"Bốc ngẫu nhiên 162 ngày bất kỳ, chỉ 3 lần trên 1.000 lần là tốt bằng thứ Ba, thứ Tư."*

### Vì sao thứ Ba, thứ Tư có t = 1,54 mà p = 0,003?

Vì hai con số so với **hai mốc khác nhau**:

- t so với **0**: "thứ Ba, thứ Tư có lãi không?" Chưa chắc.
- p so với **một ngày bình thường**: "thứ Ba, thứ Tư có tốt hơn ngày khác không?" Chắc chắn hơn nhiều.

Năm 2021 đến 2022 thị trường giảm, một ngày bình thường trung bình −1,21 điểm. Thứ Ba, thứ Tư được +2,18 điểm, tốt hơn
hẳn. Calendar cần biết ngày nào khác ngày nào, nên p là câu trả lời đúng.

Với chân thứ Hai, mốc so là các ngày **cũng mở cửa không tăng** (trung bình −2,78 điểm). Thứ Hai giảm −12,19, mạnh hơn
nhiều, nên p = 0,003. Vậy là do thứ Hai thật, không phải chỉ vì "mở cửa giảm thì giảm tiếp".

## Hai cái bẫy, cũng giải thích bằng phiên tòa

**Bẫy 1: xử nhiều bị cáo cùng lúc.** Mỗi phiên tòa có 5% khả năng kết tội oan. Xử 5 bị cáo vô tội thì khả năng **ít
nhất một người** bị kết tội oan là:

```text
1 − 0,95 × 0,95 × 0,95 × 0,95 × 0,95 ≈ 23%
```

Mình kiểm tra 5 chân Calendar cùng lúc, nên phải khó tính hơn: dùng ngưỡng 0,05 ÷ 5 = **0,01**. Hai chân chính (p =
0,003) qua được. Ba chân phụ (p từ 0,08 đến 0,11) thì không.

**Bẫy 2: ít chứng cứ.** Chân trước kỳ nghỉ chỉ có 7 phiên, đầu tháng 37 phiên, đáo hạn 19 phiên. Ít chứng cứ thì dễ
**tha nhầm** (lỗi loại II): chân có thật nhưng không chứng minh được. "Chưa đủ chứng cứ" không có nghĩa là "vô tội".

Vì vậy ba chân phụ được giữ lại nhờ "nhân chứng bên ngoài": các nghiên cứu ở thị trường khác đã thấy hiệu ứng này nhiều
năm. Rồi ở bước 5, mình xử chúng chung một lần như một nhóm, và nhóm đó qua được (Calendar đầy đủ hơn bản chỉ có chân
chính 0,45 Sharpe).

## Tóm tắt

| Từ | Nghĩa đời thường |
|---|---|
| Giả thuyết không (H0) | Giả định vô tội: ngày này không khác ngày thường |
| Độ lệch chuẩn | Một phiên ồn cỡ nào (VN30F: khoảng 20 điểm) |
| Sai số chuẩn | Trung bình của nhiều phiên ồn cỡ nào (= độ lệch chuẩn ÷ √số phiên) |
| t | Chứng cứ lớn gấp mấy lần độ ồn; trên 2 là mạnh |
| p | Nếu vô tội, khả năng tình cờ có chứng cứ như vậy; dưới 0,05 là đáng tin, xử nhiều thứ thì dưới 0,01 |

Câu nói khi bị hỏi: *"Hai chân chính có p = 0,003, nghĩa là bốc ngẫu nhiên thì chỉ 3 trên 1.000 lần tốt bằng. Ba chân phụ
quá hiếm để tự chứng minh, nên em giữ chúng nhờ nghiên cứu ở thị trường khác và kiểm tra chung một nhóm ở bước 5."*

## Bài tập

1. Một chân có 50 phiên, trung bình +3 điểm, độ lệch chuẩn 20 điểm. Tính sai số chuẩn và t. Chứng cứ có đủ mạnh không?
2. Vẫn trung bình +3 và độ lệch chuẩn 20, cần khoảng bao nhiêu phiên để t đạt 2?
3. Bạn kiểm tra 10 chân, chân tốt nhất có p = 0,03. Có nên tin không?
4. Vì sao chân thứ Hai so với các ngày mở cửa không tăng, chứ không so với tất cả các ngày?

## Đáp án

1. Sai số chuẩn = 20 ÷ √50 = 20 ÷ 7,07 ≈ 2,83. t = 3 ÷ 2,83 ≈ 1,06. Chưa đủ: trung bình chỉ cỡ một lần độ ồn.
2. Cần √(số phiên) ≥ 2 × 20 ÷ 3 ≈ 13,3, tức khoảng 178 phiên trở lên.
3. Chưa nên tin. Xử 10 bị cáo thì ngưỡng là 0,05 ÷ 10 = 0,005, mà 0,03 chưa qua. Nếu cả 10 chân đều vô tội, khả năng ít
   nhất một chân có p dưới 0,05 do may là khoảng 1 − 0,95¹⁰ ≈ 40%.
4. Vì luật chỉ bán thứ Hai khi mở cửa không tăng. Ngày mở cửa giảm vốn hay giảm tiếp, nên nếu so với tất cả các ngày thì
   thứ Hai có thể "thắng" chỉ nhờ cái gap. So với các ngày gap âm khác mới tách được phần do thứ Hai.
