# Kết quả: Calibrum trên nến 1 phút (in-sample)

Theo [PROTOCOL.md](PROTOCOL.md). Chạy bằng `scripts/run_calibrum_1m.py` (các stage `momentum-cv`, `momentum-q`,
`basis-grid`); output đầy đủ ở `reports/calibrum_1m/*.json`. Mọi stage dưới đây chỉ nạp dữ liệu tới 31/12/2022, nên
chưa chạm valid hay OOS.

Quy ước chung: in-sample 01/06/2020 – 31/12/2022, 1 hợp đồng trên 100 triệu đồng, chi phí 0,4 điểm mỗi chiều, khớp tại
close nến tín hiệu, stop xét ở close từng nến gốc. 1 điểm = 100.000 đồng = 0,1% vốn. Sharpe và MDD (%) theo
`plutus.evaluation.metrics`: √250, lãi suất phi rủi ro 3%, trên lợi suất ngày của tài khoản giữ lãi lỗ (protocol mục 3.6).

## 1. Momentum

### Chọn λ

Kiểm định chéo 4 fold mở rộng trong in-sample, 5.192 nến có đủ đặc trưng và target. Phần fit của các fold có 1.198,
2.158, 3.198 và 4.158 nến; mỗi fold kiểm định có khoảng 940 đến 1.020 nến.

MSE ngoài fold:

| λ | 2021-H1 | 2021-H2 | 2022-H1 | 2022-H2 | Trung bình |
|---|---:|---:|---:|---:|---:|
| 0,01 | 1,4911 | 1,3362 | 1,4367 | 1,7214 | 1,4964 |
| 0,1 | 1,4885 | 1,3348 | 1,4317 | 1,7217 | 1,4942 |
| **1** | 1,4907 | 1,3359 | 1,4196 | 1,7259 | **1,4930** |
| 10 | 1,5124 | 1,3491 | 1,4280 | 1,7466 | 1,5090 |
| 100 | 1,5280 | 1,3606 | 1,4395 | 1,7612 | 1,5223 |

IC Spearman ngoài fold:

| λ | 2021-H1 | 2021-H2 | 2022-H1 | 2022-H2 | Trung bình |
|---|---:|---:|---:|---:|---:|
| 0,01 | 0,118 | 0,097 | 0,070 | 0,148 | 0,108 |
| 0,1 | 0,119 | 0,095 | 0,070 | 0,153 | 0,109 |
| **1** | 0,113 | 0,097 | 0,078 | 0,163 | **0,113** |
| 10 | 0,103 | 0,099 | 0,083 | 0,166 | 0,113 |
| 100 | 0,101 | 0,099 | 0,084 | 0,166 | 0,113 |

Chọn **λ = 1**: 0,01, 0,1 và 1 cách MSE nhỏ nhất dưới 1%, luật lấy λ lớn nhất trong nhóm; λ = 10 cách 1,07%.
**B1 không xảy ra**: IC dương ở cả 4 fold.

Hệ số của fit cuối (trên z đã chuẩn hoá bằng median, IQR):

| β₀ | x1 VWAP | x2 mở cửa | x3 SMA4 | x4 bất đối xứng | x5 thân nến |
|---:|---:|---:|---:|---:|---:|
| +0,0357 | +0,0383 | +0,0570 | +0,0259 | +0,0175 | +0,0194 |

Cả năm hệ số dương; cả năm đặc trưng tương quan dương với target (0,11 đến 0,15), x1 tương quan 0,89 với x2. Quán
tính được xác nhận; ý "lực đi tiếp yếu dần khi giá xa VWAP" bị bác bỏ (protocol mục 9).

### Chọn ngưỡng q

θ là phân vị q của |score| trên in-sample.

| q | θ | Lãi net (điểm) | Sharpe | MDD (điểm) | Margin (bps) | Lệnh | Hit rate | Chi phí (điểm) | Có vị thế |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0,7 | 0,127 | 899,6 | 1,54 | 147,1 | 6,5 | 566 | 43% | 453,2 | 50% |
| 0,8 | 0,166 | 834,1 | 1,56 | 145,9 | 7,6 | 451 | 46% | 361,2 | 39% |
| **0,9** | **0,232** | **731,5** | **1,57** | 151,9 | 10,7 | 279 | 50% | 223,2 | 24% |

Chọn **q = 0,9**. Cả ba mức đều lãi sau chi phí, nên ngưỡng nằm trong vùng ổn định. Với q = 0,9: lãi 73,2 triệu đồng
(73,2% vốn trong 2,6 năm), mức sử dụng ký quỹ cao nhất 20,5%.

## 2. Basis

Sharpe sau chi phí, cửa sổ W (hàng) × ngưỡng vào z_in (cột):

| W | 1,00 | 1,25 | 1,50 | 1,75 | 2,00 |
|---|---:|---:|---:|---:|---:|
| 20 | 0,28 | 0,18 | 0,24 | 0,27 | 0,17 |
| 30 | −0,15 | 0,54 | 0,55 | 0,44 | −0,07 |
| 40 | 0,49 | 0,84 | 0,71 | 0,63 | 0,50 |
| 50 | 0,98 | 0,82 | 1,09 | 1,18 | 0,70 |
| 60 | 0,74 | 0,88 | **0,99** | 1,23 | 0,88 |

Điểm vùng 3 × 3 (trung bình Sharpe của ô và các ô kề):

| W | 1,00 | 1,25 | 1,50 | 1,75 | 2,00 |
|---|---:|---:|---:|---:|---:|
| 20 | 0,21 | 0,27 | 0,37 | 0,27 | 0,20 |
| 30 | 0,36 | 0,41 | 0,49 | 0,38 | 0,32 |
| 40 | 0,58 | 0,65 | 0,75 | 0,64 | 0,56 |
| 50 | 0,79 | 0,84 | 0,93 | 0,88 | 0,85 |
| 60 | 0,85 | 0,91 | **1,03** | 1,01 | 1,00 |

Lãi net (điểm):

| W | 1,00 | 1,25 | 1,50 | 1,75 | 2,00 |
|---|---:|---:|---:|---:|---:|
| 20 | 191 | 124 | 164 | 174 | 125 |
| 30 | −95 | 367 | 345 | 280 | −8 |
| 40 | 323 | 526 | 434 | 384 | 294 |
| 50 | 642 | 522 | 624 | 663 | 367 |
| 60 | 478 | 542 | 571 | 659 | 445 |

Chọn **W = 60, z_in = 1,5**: lãi 570,7 điểm (57,1 triệu đồng), Sharpe 0,99, MDD 184 điểm, margin 14,5 bps,
161 lệnh, hit rate 42%, chi phí 128,4 điểm, có vị thế 50% thời gian, ký quỹ cao nhất 20,4%. Cả 6 ô kề đều lãi sau chi
phí.

Ô được chọn nằm ở biên lưới (W = 60 là giá trị lớn nhất được thử), và Sharpe tăng dần theo W. Lưới đã khoá trong
protocol nên không mở rộng; ghi lại để phán quyết sau.

Kiểm tra cơ chế với ô đã chọn:

- **B4 không xảy ra**: 79,2% trong 380 lần |Z| vượt 1,5 thì |Z| về dưới 0,75 trong vòng 8 nến.
- **B5 không xảy ra**: lãi gộp 699,1 điểm = 636,4 điểm do basis co lại + 62,7 điểm do chỉ số chạy.

## 3. Calendar MTW

Giữ tham số của repo calendar-mtw-vn30f, không tối ưu lại (protocol mục 3.4).

## 4. Bước 4: 7 tổ hợp với tham số ban đầu

Stage `in-sample-baseline`, chỉ nạp dữ liệu tới 31/12/2022. Tham số ban đầu (protocol mục 9): Calendar MTW như repo
gốc; Basis W = 40, z_in = 1,5; Momentum λ = 1, q = 0,8 (θ = 0,166). Gộp bằng vote, 1 hợp đồng trên 100 triệu đồng.

| Tổ hợp | Lãi net (điểm) | Lợi suất | Sharpe | MDD | Margin (bps) | Lệnh | Hit rate | Có vị thế |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| C | 1.215,4 | 121,5% | 1,93 | 17,2% | 24,2 | 205 | 63% | 53% |
| B | 434,4 | 43,4% | 0,71 | 20,9% | 8,6 | 209 | 41% | 57% |
| M | 834,1 | 83,4% | 1,56 | 8,2% | 7,6 | 451 | 46% | 39% |
| C+B | 1.193,1 | 119,3% | 1,58 | 30,3% | 16,1 | 304 | 55% | 61% |
| C+M | 1.647,4 | 164,7% | 2,54 | 9,9% | 14,9 | 452 | 50% | 66% |
| B+M | 1.074,6 | 107,5% | 1,74 | 8,1% | 9,6 | 462 | 44% | 65% |
| **C+B+M** | **1.739,4** | **173,9%** | **2,59** | 12,7% | 14,6 | 488 | 48% | 67% |

Lợi suất tính trên 100 triệu đồng, cả in-sample (2,6 năm). Mức sử dụng ký quỹ cao nhất khoảng 20,5% ở mọi tổ hợp.

Lãi net theo năm (điểm; 2020 là 7 tháng):

| Tổ hợp | 2020 | 2021 | 2022 |
|---|---:|---:|---:|
| C | 208,6 | 303,5 | 703,3 |
| B | 66,8 | 321,9 | 45,7 |
| M | 158,1 | 375,5 | 300,5 |
| C+B | 80,0 | 458,0 | 655,1 |
| C+M | 290,3 | 617,2 | 739,9 |
| B+M | 209,8 | 568,9 | 295,9 |
| C+B+M | 319,7 | 703,9 | 715,8 |

Tương quan lãi lỗ theo ngày giữa các sleeve:

| | C | B | M |
|---|---:|---:|---:|
| C | 1,00 | −0,09 | +0,15 |
| B | −0,09 | 1,00 | −0,07 |
| M | +0,15 | −0,07 | 1,00 |

Mọi tổ hợp đều lãi ở cả ba năm. Cả ba gộp lại có Sharpe cao nhất (2,59), trên Sharpe của sleeve đứng riêng tốt nhất
(Calendar, 1,93). MDD của C+B (30,3%) lớn hơn của từng sleeve: khi hai sleeve bất đồng thì vote đứng ngoài, nên C+B bỏ
lỡ phần lãi của sleeve còn lại mà vẫn giữ các lần cả hai cùng sai. Tương quan giữa ba sleeve đều gần 0.

## 5. Bước 6: valid 2023–2024 và chọn tổ hợp cuối

Mở valid một lần ngày 22/10/2026 (`scripts/run_calibrum_1m.py valid`, dữ liệu nạp tới 31/12/2024), với tham số đã chọn ở
bước 5: Momentum λ = 1, q = 0,9 (θ = 0,232); Basis W = 60, z_in = 1,5; Calendar MTW giữ nguyên. Vote, 1 hợp đồng trên
100 triệu đồng, chi phí 0,4 điểm mỗi chiều. Lãi net tính bằng triệu đồng (1 triệu = 1% vốn).

| Tổ hợp | In-sample lãi | Sharpe | MDD | Valid lãi | Sharpe | MDD |
|---|---:|---:|---:|---:|---:|---:|
| C | 122,2 | 1,94 | 17,2% | 60,2 | 1,83 | 10,6% |
| B | 57,1 | 0,99 | 11,3% | 49,4 | 1,46 | 7,8% |
| M | 73,2 | 1,57 | 8,7% | 13,7 | 0,42 | 7,0% |
| C+B | 143,3 | 2,05 | 24,1% | 71,5 | 1,94 | 10,7% |
| **C+M** | **168,7** | **2,75** | 7,7% | **62,3** | **1,76** | 9,4% |
| B+M | 114,2 | 1,92 | 8,2% | 59,9 | 1,77 | 7,7% |
| C+B+M | 180,8 | 2,77 | 11,1% | 77,5 | 2,03 | 9,0% |

In-sample của C nhích từ 121,5 (bước 4) lên 122,2 vì lệnh mua tuần cuối năm 2022 thoát vào tháng 1/2023; lần chạy bước 4
cắt dữ liệu ở 31/12/2022 nên bỏ lệnh đó.

- **B2 không xảy ra**: IC của score Momentum trên valid là +0,071.
- **B6 không xảy ra** với cả ba sleeve: C +60,2, B +49,4, M +13,7 triệu đồng. Không sleeve nào bị loại.
- Luật khoá ở mục 3.5 (xếp theo Sharpe in-sample, chênh dưới 0,2 thì ít sleeve hơn) cho **C+M**: C+B+M 2,765 và C+M
  2,750 chênh 0,015.
- **Sửa luật sau khi xem valid** (protocol mục 9, +1 lần thử): chọn tổ hợp có **Sharpe valid cao nhất**. **Tổ hợp cuối là
  C+B+M** (Sharpe valid 2,03; kế đến C+B 1,94, C+M 1,76). Việc sửa và lựa chọn được commit trước khi mở OOS 1.

## OOS 1: năm 2025

Mở một lần ngày 22/10/2026 (`run_calibrum_1m.py oos1`, dữ liệu nạp tới 31/12/2025), sau commit chọn tổ hợp.

| Tổ hợp | Lãi (triệu đồng) | Sharpe | MDD | Margin (bps) | Số lệnh | Hit rate |
|---|---:|---:|---:|---:|---:|---:|
| C | 73,5 | 2,49 | 15,9% | 34,2 | 68 | 69% |
| B | 21,9 | 0,78 | 23,7% | 9,6 | 71 | 45% |
| M | 32,7 | 1,80 | 6,1% | 10,7 | 95 | 46% |
| C+B | 73,7 | 2,38 | 20,6% | 22,9 | 102 | 52% |
| C+M | 89,2 | 3,05 | 9,7% | 25,8 | 109 | 60% |
| B+M | 47,8 | 1,68 | 16,5% | 12,2 | 122 | 51% |
| **C+B+M** | **94,9** | **3,20** | 12,7% | 23,1 | 131 | 51% |

Số trên lấy từ lần chạy liền đến 21/10/2026. Lần mở OOS 1 (dữ liệu cắt ở 31/12/2025) cho C 69,0 và C+B+M 90,4, vì lệnh
mua Calendar vào thứ Hai 29/12/2025 thoát ngày 02/01/2026 nên bị bỏ hẳn khi chưa có nến thoát. Theo quy ước chấm điểm
(một lần chạy trên toàn chuỗi, lãi lỗ cộng theo ngày), phần lãi ngày 29–31/12 thuộc năm 2025. Sleeve B và M không đổi.

IC của score Momentum trên OOS 1: +0,086. Cả 7 tổ hợp lãi; tổ hợp cuối C+B+M có Sharpe cao nhất.

## OOS 2: 01/01/2026 – 21/10/2026

Mở một lần ngày 22/10/2026 (`run_calibrum_1m.py oos2`, nến cuối 21/10/2026 14:45), sau commit OOS 1.

| Tổ hợp | Lãi (triệu đồng) | Sharpe | MDD | Margin (bps) | Số lệnh | Hit rate |
|---|---:|---:|---:|---:|---:|---:|
| C | 74,3 | 3,32 | 5,9% | 29,1 | 65 | 68% |
| B | 14,3 | 0,67 | 21,7% | 6,8 | 54 | 39% |
| M | −9,3 | −0,77 | 21,6% | −3,3 | 73 | 37% |
| C+B | 86,5 | 3,64 | 12,2% | 26,3 | 84 | 64% |
| C+M | 66,2 | 2,82 | 6,8% | 17,2 | 99 | 51% |
| B+M | 4,5 | 0,23 | 27,8% | 1,1 | 101 | 41% |
| **C+B+M** | **71,7** | **2,87** | 8,9% | 16,1 | 114 | 51% |

IC của score Momentum trên OOS 2: −0,004. Momentum lỗ 9,3 triệu đồng: score không còn dự báo được chiều giá năm 2026,
khớp với chẩn đoán trước đó trên bản Ridge cũ. Tổ hợp cuối C+B+M vẫn lãi 71,7 triệu, Sharpe 2,87; C+B tốt nhất năm này.

## Metric bổ sung: Sortino, Information Ratio, Longest drawdown

Tính ngày 23/10/2026, sau khi mọi lựa chọn và cả hai OOS đã chốt, chỉ để báo cáo, không đổi lựa chọn nào. Hàm của
Plutus (`plutus.evaluation.metrics`), lợi suất ngày trên vốn 100 triệu đồng như Sharpe. Chạy lại `in-sample-baseline`,
`valid`, `oos1 --rerun`, `oos2 --rerun`: mọi cột cũ khớp đúng số cũ. Số dưới lấy từ lần chạy liền đến 21/10/2026.

- **Sortino**: √250 · (r̄ − 3%/250) / độ lệch chiều xuống, ngưỡng 3% như rf của Sharpe.
- **Information Ratio**: √250 · trung bình(r − r_bench) / độ lệch chuẩn(r − r_bench), benchmark là mua giữ VN30F1M,
  1 hợp đồng trên cùng 100 triệu (đường xám trên biểu đồ). Mua giữ lãi 27,6 / 27,0 / 71,0 / −13,3 triệu đồng trong
  in-sample / valid / 2025 / 2026.
- **Longest drawdown**: số phiên lâu nhất từ một đỉnh vốn đến đỉnh mới kế tiếp; drawdown còn mở ở cuối giai đoạn cũng
  tính (in-sample và valid của C+B+M kết thúc khi đang dưới đỉnh 10 và 17 phiên).

| Sortino | In-sample | Valid | OOS 1 | OOS 2 |
|---|---:|---:|---:|---:|
| C | 3,03 | 3,01 | 3,93 | 6,46 |
| B | 1,61 | 2,42 | 1,25 | 0,96 |
| M | 3,21 | 0,70 | 3,75 | −1,18 |
| C+B | 3,24 | 3,13 | 3,95 | 6,80 |
| C+M | 4,94 | 2,96 | 5,05 | 5,46 |
| B+M | 3,32 | 2,97 | 2,75 | 0,34 |
| **C+B+M** | **4,92** | **3,38** | **5,45** | **5,22** |

| Information Ratio | In-sample | Valid | OOS 1 | OOS 2 |
|---|---:|---:|---:|---:|
| C | 0,91 | 0,74 | −0,02 | 2,16 |
| B | 0,22 | 0,36 | −0,85 | 0,53 |
| M | 0,38 | −0,37 | −0,90 | −0,05 |
| C+B | 0,98 | 0,86 | −0,00 | 2,20 |
| C+M | 1,24 | 0,76 | 0,35 | 1,93 |
| B+M | 0,67 | 0,55 | −0,42 | 0,33 |
| **C+B+M** | **1,24** | **0,96** | **0,39** | **1,87** |

| Longest drawdown (phiên) | In-sample | Valid | OOS 1 | OOS 2 |
|---|---:|---:|---:|---:|
| C | 74 | 153 | 80 | 38 |
| B | 106 | 64 | 113 | 125 |
| M | 131 | 141 | 63 | 159 |
| C+B | 93 | 110 | 112 | 20 |
| C+M | 62 | 125 | 27 | 56 |
| B+M | 107 | 98 | 81 | 160 |
| **C+B+M** | **50** | **128** | **92** | **36** |

- Sortino của C+B+M cao gần gấp đôi Sharpe ở mọi giai đoạn: phần biến động chủ yếu nằm ở chiều lãi.
- IR năm 2025 thấp (0,39) vì thị trường tăng mạnh (mua giữ +71,0 triệu); C+B+M vẫn lãi hơn (+94,9) nhưng ít tương quan
  với thị trường nên độ lệch so với benchmark lớn. Năm 2026 mua giữ lỗ, IR lên 1,87.
- Drawdown dài nhất của C+B+M là 128 phiên trong valid (31/01/2023 – 02/08/2023, khoảng 6 tháng). Đây là mốc tham chiếu
  khi theo dõi paper trade.

Ở bước 4 (tham số ban đầu, in-sample), C+B+M có Sortino 4,45, IR 1,15, longest drawdown 72 phiên; số của 7 tổ hợp nằm
trong `reports/calibrum_1m/in_sample_baseline.json`.

## Chưa chạy

DSR với N ≥ 418; phán quyết theo chế độ Phán quyết của skill algotrade-hypothesis.

## 6. Ghi chú vận hành

Phiên đáo hạn 16/07/2020 không có trong dữ liệu DNSE ở mọi khung, nên luật đứng ngoài phiên đáo hạn không kích hoạt
được tháng đó. Engine đóng mọi vị thế ở nến cuối của mỗi hợp đồng và reset trạng thái sleeve, để không vị thế nào vắt
qua lần đổi hợp đồng. Đây là chốt an toàn cho dữ liệu thiếu, không đổi luật giao dịch.
