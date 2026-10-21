# 6. Backtest out-of-sample

Cấu hình từ chương 5, không đổi: các sleeve đóng băng, luật ở chương 3. Ensemble chính thức là equal-weight sum;
majority vote chạy để tham khảo. Giai đoạn: OOS 01/01/2023 đến 19/12/2024, forward 01/01/2026 đến 01/10/2026.

## 6.1 Lab

Lệnh: `make step6 ENSEMBLE=sum`, `make step6 ENSEMBLE=vote` (cache DNSE, phí 0,8 điểm mỗi vòng).
Report: `reports/step6_{oos,forward}_lab_{sum,vote}.json`.

Quy về 1 hợp đồng (sum chia 3):

| Giai đoạn | Ensemble | Lãi net (điểm) | Sharpe | MDD (điểm) | Margin (bps) |
|---|---|---:|---:|---:|---:|
| In-sample | Sum | +800,0 | 3,60 | 40,5 | 18,56 |
| OOS | Sum | +417,2 | 2,36 | 34,2 | 8,84 |
| Forward | Sum | +214,2 | 1,54 | 70,3 | 7,17 |
| In-sample | Vote | +1.579,4 | 3,70 | 87,7 | 20,66 |
| OOS | Vote | +755,8 | 2,31 | 77,9 | 9,46 |
| Forward | Vote | +349,3 | 1,34 | 182,2 | 6,08 |

Cả hai ensemble đều lãi sau phí ở cả hai giai đoạn. Sharpe giảm dần từ IS sang OOS rồi sang forward, và margin trên mỗi
đơn vị giao dịch giảm còn khoảng một nửa sau in-sample.

### Theo từng sleeve

Mỗi sleeve chạy riêng, 1 hợp đồng (lãi net điểm / Sharpe):

| Sleeve | In-sample | OOS | Forward |
|---|---:|---:|---:|
| Momentum | +886,8 / 2,23 | +256,3 / 0,91 | −64,3 / −0,29 |
| Basis | +630,2 / 1,81 | +426,6 / 1,44 | +412,3 / 2,01 |
| Calendar | +837,5 / 2,29 | +515,9 / 1,78 | +270,6 / 1,32 |

Phần lớn sự suy giảm đến từ Momentum, sleeve này lỗ trong giai đoạn forward. Basis và Calendar giữ Sharpe trên 1,3 ở mọi
giai đoạn.

Chương 5 đã ghi cửa sổ Basis nhạy ở phía ngắn. Ngoài mẫu, cửa sổ 30 nến đạt Sharpe 1,76 (OOS) và 0,92 (forward), cửa sổ
50 nến đạt 1,34 và 1,26, so với 1,44 và 2,01 của cửa sổ gốc 40. Các lần chạy này chỉ để theo dõi; không đổi cửa sổ dựa
trên dữ liệu ngoài mẫu.

## 6.2 Plutus

Lệnh: `make calibrum-oos ENSEMBLE=sum|vote`, `make calibrum-forward ENSEMBLE=sum|vote`. Vốn 300 triệu đồng, tối đa 3
hợp đồng, khớp mềm. Report: `reports/calibrum_plutus_{oos,forward}_{sum3,vote3}_300m.json`.

| Chỉ số | OOS sum | OOS vote | Forward sum | Forward vote |
|---|---:|---:|---:|---:|
| Trạng thái | PASSED | PASSED | FAILED | FAILED |
| Số phiên đầy đủ | 491 | 491 | 181 | 181 |
| Lãi lỗ net (triệu đồng) | +138,2 | +182,8 | +109,1 | +93,1 |
| Lợi suất (theo năm) | +46,1% (+21,5%) | +60,9% (+27,7%) | +36,4% (+54,0%) | +31,0% (+45,7%) |
| Sharpe | 2,78 | 2,00 | 2,56 | 1,48 |
| Max drawdown | 3,23% | 8,13% | 5,08% | 11,11% |
| Lệnh / khớp | 1.108 / 946 | 720 / 611 | 409 / 360 | 288 / 256 |
| Tổng phí (triệu đồng) | 17,6 | 31,3 | 10,0 | 19,1 |
| Tỷ lệ sử dụng ký quỹ cao nhất | 19,5% | 21,7% | 34,9% | 37,8% |
| Cảnh báo, gọi ký quỹ, thanh lý | 0, 0, 0 | 0, 0, 0 | 0, 0, 0 | 0, 0, 0 |

Hai lần chạy forward bị đánh dấu FAILED vì Plutus không đánh giá được hai phiên (19/01/2026, 09/03/2026); hai phiên này
bị loại khỏi các chỉ số. Vote forward còn trượt ngưỡng profit factor của runner (1,085 so với 1,20). Tỷ lệ sử dụng ký quỹ
năm 2026 cao hơn vì VN30F giao dịch quanh 1.960 điểm, so với khoảng 1.200 ở giai đoạn OOS, nên mỗi hợp đồng cần nhiều ký
quỹ hơn.

## 6.3 So sánh in-sample và out-of-sample

| Sharpe | In-sample | OOS | Forward |
|---|---:|---:|---:|
| Sum, lab | 3,60 | 2,36 | 1,54 |
| Sum, Plutus | 4,37 | 2,78 | 2,56 |
| Vote, lab | 3,70 | 2,31 | 1,34 |
| Vote, Plutus | 4,12 | 2,00 | 1,48 |

- Cả hai ensemble đều lãi sau phí thật ở mọi giai đoạn, không có cảnh báo ký quỹ nào.
- Sharpe giảm khoảng một phần ba đến một nửa từ in-sample sang OOS ở cả hai engine, và giảm tiếp ở forward, trừ sum trên
  Plutus (2,78 xuống 2,56).
- Sum có drawdown thấp hơn vote ở mọi giai đoạn và cả hai engine, giống bước 5.
- Lab và Plutus lại khác nhau về độ lớn (thời điểm khớp, chi phí; chương 4), nhưng chiều của mọi kết quả đều giống nhau.

### Phán quyết cho Momentum

Theo chế độ Phán quyết của skill `algotrade-hypothesis`:

| Câu hỏi | Trả lời |
|---|---|
| Có lãi sau phí ở đa số giai đoạn không? | In-sample và OOS có, forward không (−64,3 điểm, Sharpe −0,29) |
| Tham số có ổn định không? | Có, trên in-sample (chương 5) |
| Các dự đoán bác bỏ B1 đến B3 | Chưa kiểm tra; chúng được định nghĩa trên dữ liệu từ 02/10/2026 |
| Nguyên nhân có thể | Trọng số fit trên 2020 đến 2022, trùng với in-sample; và/hoặc lợi thế đang mất dần như protocol đã dự đoán |

Phán quyết tạm thời: bằng chứng nghiêng về BỎ Momentum khỏi tín hiệu chính, hoặc SỬA LUẬT, chẳng hạn fit lại (dự đoán B3).
Phán quyết cuối cùng chờ B1 đến B3 trên dữ liệu khoá.

### Basis và Calendar, không có Momentum (chọn sau khi xem kết quả)

Tổ hợp này được đề xuất sau khi đã xem kết quả OOS và forward ở trên, nên các con số dưới đây không phải bằng chứng ngoài
mẫu. Lab, 1 hợp đồng (lãi net điểm / Sharpe / MDD điểm):

| | In-sample | OOS | Forward |
|---|---:|---:|---:|
| B+C sum (÷ 2) | +737,9 / 3,30 / 68,8 | +474,4 / 2,24 / 73,1 | +342,3 / 2,31 / 105,8 |
| M+B+C sum (÷ 3) | +800,0 / 3,60 / 40,5 | +417,2 / 2,36 / 34,2 | +214,2 / 1,54 / 70,3 |

Bỏ Momentum thì Sharpe forward cao hơn, nhưng OOS thấp hơn một chút và drawdown lớn hơn ở mọi giai đoạn. B+C được ghi nhận
là một ứng viên mới (thêm một lần thử), sẽ kiểm tra trên dữ liệu sau 01/10/2026, chạy song song với M+B+C.

## 6.4 Kết luận bước 1 đến 6

- Cấu hình đã chốt trước, M+B+C gộp bằng equal-weight sum, có lãi ngoài mẫu trên lab và trên Plutus với phí thật;
  drawdown 3 đến 5% trên 300 triệu đồng, tỷ lệ sử dụng ký quỹ cao nhất dưới 40%.
- Kết quả giảm dần từ in-sample sang OOS rồi forward. Phần suy giảm chủ yếu đến từ Momentum.
- Basis và Calendar đứng vững ở mọi giai đoạn.
- Phép thử sạch còn lại là dữ liệu từ 02/10/2026 trở đi: paper trading (bước 7), chạy song song M+B+C và ứng viên B+C.
