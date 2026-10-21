# Protocol: Shinji, basis phái sinh và cơ sở hồi về trung bình (19/10/2026)

Protocol này viết hồi cứu. Sleeve đã đóng băng trong `PS_V30_Vien_Calibrum/` và đã backtest trên cả ba giai đoạn trước
ngày viết. Mục đích là ghi lại giả thuyết như nó đang chạy, đếm những lần thử đã biết, và khoá một khoảng dữ liệu
chưa ai nhìn để chấm lần cuối.

## 1. Giả thuyết

Khi basis (VN30F1M trừ VN30) lệch khỏi trung bình 40 nến 30 phút từ 1,5 độ lệch chuẩn trở lên, basis co lại về phía
trung bình trong vài phiên kế tiếp, và phần co lại đó lớn hơn phí một vòng.

## 2. Nguồn alpha và cơ chế

- Nguồn: mispricing, kèm hiểu biết riêng về thị trường Việt Nam.
- Ai trả tiền: nhà đầu tư cá nhân trên phái sinh. Lúc hưng phấn họ mua đuổi, đẩy hợp đồng lên cao hơn rổ VN30 bất
  thường; lúc hoảng loạn họ bán tháo, đẩy hợp đồng xuống thấp hơn rổ. Rổ cơ sở gồm 30 cổ phiếu lớn nên phản ứng chậm
  hơn hợp đồng đòn bẩy cao.
- Vì sao lợi thế còn: trên HOSE, nhà đầu tư không bán khống cổ phiếu được, nên khi phái sinh bị chiết khấu sâu không ai
  mua hợp đồng và bán rổ để ăn chênh lệch. Khi phái sinh có premium, người kinh doanh chênh lệch phải mua cả rổ 30 cổ
  phiếu, cần nhiều vốn và chịu chi phí giao dịch cổ phiếu. Cả hai chiều đều làm chênh lệch tồn tại lâu hơn ở thị trường
  có arbitrage tự do.
- Khi nào mất: khi Việt Nam cho bán khống, khi có ETF hay chứng chỉ quỹ VN30 rẻ và đủ thanh khoản để làm chân cơ sở,
  hoặc khi tổ chức chạy arbitrage basis ở quy mô lớn.

## 3. Luật đo được

- Biến độc lập: `Basis_t = Close(VN30F1M) − Close(VN30)`, giá cơ sở ghép bằng `merge_asof` hướng `backward` (chỉ lấy
  giá đã biết). `Z_t = (Basis_t − mean40) / (std40 + 1e-6)`, cần ít nhất 15 nến.
- Biến phụ thuộc: thay đổi của basis, và lãi lỗ hợp đồng, từ lúc vào tới lúc ra.
- Luật vào: Z ≤ −1,5 thì Long, Z ≥ +1,5 thì Short.
- Luật ra như code đang chạy:
  - Đã giữ ít nhất 2 nến và Z chạm cực trị ngược chiều thì đảo vị thế.
  - Lỗ chưa chốt quá 14 điểm thì về 0.
  - Luật chốt lời `|Z| ≤ z_exit` với `z_exit = 0,0` chỉ kích hoạt khi Z bằng đúng 0. Trên dữ liệu DNSE từ 15/01/2021
    đến 01/10/2026 nó kích hoạt 0 lần; lệnh chỉ đóng bằng đảo chiều (345 lần) hoặc cắt lỗ (242 lần), và sleeve có vị
    thế ở 82% số nến. README mô tả "thoát khi Z cắt 0", nhưng luật thật là giữ lệnh tới khi cắt lỗ hoặc gặp cực trị
    bên kia. Sửa cho khớp README là một bộ luật mới và tính là lần thử mới.
- Tham số: cửa sổ 40, ngưỡng vào 1,5, giữ tối thiểu 2 nến, cắt lỗ 14 điểm. `docs/shinji.md` ghi cửa sổ 40 đến 50 và cắt
  lỗ 10 đến 14, nên các giá trị này được chọn từ một lưới không có trong repo.
- Ràng buộc thật của thị trường:
  - Tín hiệu tính ở giá đóng nến T, khớp ở nến T+1. Ở nến 14:30 (ATC) giữ nguyên vị thế.
  - Basis tự co về 0 khi hợp đồng gần đáo hạn (thứ Năm thứ ba của tháng), không liên quan tới phản ứng thái quá. Gói
    đóng băng giả định chuỗi hợp đồng đã điều chỉnh liên tục. Adapter tính lại Shinji riêng cho từng hợp đồng (mỗi hợp
    đồng mới phải tích lại 40 nến) và ép về 0 trong phiên đáo hạn (`_shinji_with_roll_guard`). Đây là một lần thử
    riêng.
  - Sleeve chỉ giao dịch hợp đồng, không giao dịch rổ, nên lãi lỗ là `vị thế × (Δspot + Δbasis)`. Phần Δspot là rủi ro
    hướng giá mà sleeve gánh thêm.

## 4. Dự đoán bác bỏ

Chấm trên khoảng khoá ở mục 7, tham số giữ nguyên.

- B1: Trong các lần |Z| vượt 1,5, tỷ lệ |Z| quay về dưới 0,75 trong vòng 8 nến không quá 50%. Khi đó basis không hồi
  nhanh hơn ngẫu nhiên và giả thuyết sai.
- B2: Tách lãi lỗ mỗi lệnh thành phần do Δbasis và phần do Δspot. Nếu tổng phần Δbasis ≤ 0, hoặc nhỏ hơn một nửa tổng
  lãi, thì sleeve đang kiếm tiền nhờ đoán đúng hướng thị trường, không nhờ basis hồi. Cơ chế ở mục 2 sai, kể cả khi
  sleeve vẫn lãi.
- B3: Bỏ 3 phiên trước ngày đáo hạn mà mất hơn 70% lãi. Khi đó lợi thế là basis tự hội tụ lúc đáo hạn, một hiệu ứng cơ
  học, không phải phản ứng thái quá của cá nhân.

## 5. Tiêu chí chấp nhận

Ngưỡng của dự án (gate trong `PS_V30_Vien_Calibrum/native_verification.json`) áp cho cả ensemble: Sharpe sau phí
≥ 1,5, margin sau phí ≥ 15 bps, ít nhất 180 lệnh, Futures Leak và Overfit PASS.

Shinji là một sleeve nên cần qua cả ba điều sau:

- Lãi sau phí trên khoảng khoá, và dương ở cả 3 giai đoạn IS, OOS, FWD của lab (đã đạt: +420,6; +234,5; +1.040,1
  điểm). Lãi hiện dồn nhiều vào FWD: 61% tổng lãi giai đoạn 2021 đến 2026 đến từ khoảng 2025 đến 2026. Đây là dấu hiệu
  "lãi dồn vào một giai đoạn" cần xem lại khi phán quyết.
- Bỏ Shinji khỏi ensemble làm Sharpe của ensemble giảm trên khoảng khoá. Trên lab giai đoạn FWD, R + C có Sharpe 1,77,
  còn R + S + C có 2,36.
- Cửa sổ 40 nằm trong vùng ổn định: cửa sổ 30 và 50 cũng lãi sau phí trên cùng dữ liệu. Phép thử này chưa chạy.

## 6. Ngân sách lần thử

Những lần thử đã biết:

| Lần thử | Số biến thể | Nguồn |
|---|---:|---|
| Lưới cửa sổ × cắt lỗ trước khi có repo (cửa sổ 40 đến 50, cắt lỗ 10 đến 14) | ≥ 4 | `docs/shinji.md` |
| Tính lại theo từng hợp đồng và ép phẳng ngày đáo hạn | 1 | `calibrum_signal_source.py` |
| Bản đóng băng | 1 | `PS_V30_Vien_Calibrum/` |

Tổng tối thiểu: 6. Kích thước thật của lưới trước khi có repo chưa biết; nếu còn log, đếm thêm vào đây.

Lưới cho lần chấm tiếp theo, khoá trước: cửa sổ ∈ {30; 40; 50}, các tham số khác giữ nguyên, luật chốt lời giữ như code
(không sửa). Thêm 3 lần thử, N tối thiểu thành 9. DSR tính với N = 9 và ghi rõ đó là cận dưới.

Nếu muốn sửa luật chốt lời cho đúng ý "thoát khi Z cắt 0", đó là SỬA LUẬT: viết lại mục 3 của protocol này, đếm thêm
lần thử, và không dùng khoảng khoá để chọn giữa hai bản.

## 7. Dữ liệu

| Khoảng | Ngày | Vai trò hiện tại | Số lần đã nhìn |
|---|---|---|---|
| In-sample | 02/01/2020 đến 30/12/2022 | Chọn tham số | Nhiều |
| OOS cũ | 01/01/2023 đến 19/12/2024 | Validation | ≥ 4: notebook Native SDK, lab 7 tổ hợp, so sánh 8 cách ensemble, Plutus vote và sum |
| Forward cũ | 01/01/2025 đến 01/10/2026 | Validation | ≥ 4, cùng các lần trên |
| Khoá | từ 02/10/2026 | Kiểm tra cuối | 0 |

Hai khoảng 2023 đến 2026 đã dùng để so và chọn, nên không còn là out-of-sample. Kiểm tra cuối chỉ dùng dữ liệu từ
02/10/2026 trở đi, mở một lần khi Shinji đã có ít nhất 60 lệnh. Với khoảng 100 lệnh mỗi năm trên lab, mốc này đến sau
khoảng 7 tháng. Cần cả hai feed VN30F1M (có cột `Contract` để tính lại theo hợp đồng) và VN30, lấy từ Postgres
`algotradeDB`.
