# Kết quả: Calibrum trên nến 1 phút (in-sample)

Theo [PROTOCOL.md](PROTOCOL.md). Chạy bằng `scripts/run_calibrum_1m.py` (các stage `momentum-cv`, `momentum-q`,
`basis-grid`); output đầy đủ ở `reports/calibrum_1m/*.json`. Mọi stage dưới đây chỉ nạp dữ liệu tới 31/12/2022, nên
chưa chạm valid hay OOS.

Quy ước chung: in-sample 01/06/2020 – 31/12/2022, 1 hợp đồng trên 100 triệu đồng, chi phí 0,4 điểm mỗi chiều, khớp tại
close nến tín hiệu, stop xét ở close từng nến gốc. 1 điểm = 100.000 đồng = 0,1% vốn.

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
| 0,7 | 0,127 | 899,6 | 1,62 | 147,1 | 6,5 | 566 | 43% | 453,2 | 50% |
| 0,8 | 0,166 | 834,1 | 1,63 | 145,9 | 7,6 | 451 | 46% | 361,2 | 39% |
| **0,9** | **0,232** | **731,5** | **1,73** | 151,9 | 10,7 | 279 | 50% | 223,2 | 24% |

Chọn **q = 0,9**. Cả ba mức đều lãi sau chi phí, nên ngưỡng nằm trong vùng ổn định. Với q = 0,9: lãi 73,2 triệu đồng
(73,2% vốn trong 2,6 năm), MDD 15,2% vốn, mức sử dụng ký quỹ cao nhất 20,5%.

## 2. Basis

Sharpe sau chi phí, cửa sổ W (hàng) × ngưỡng vào z_in (cột):

| W | 1,00 | 1,25 | 1,50 | 1,75 | 2,00 |
|---|---:|---:|---:|---:|---:|
| 20 | 0,29 | 0,19 | 0,28 | 0,33 | 0,25 |
| 30 | −0,16 | 0,61 | 0,61 | 0,53 | −0,02 |
| 40 | 0,56 | 0,94 | 0,81 | 0,75 | 0,64 |
| 50 | 1,15 | 0,94 | 1,20 | 1,34 | 0,87 |
| 60 | 0,89 | 0,99 | **1,11** | 1,37 | 1,03 |

Điểm vùng 3 × 3 (trung bình Sharpe của ô và các ô kề):

| W | 1,00 | 1,25 | 1,50 | 1,75 | 2,00 |
|---|---:|---:|---:|---:|---:|
| 20 | 0,23 | 0,30 | 0,42 | 0,33 | 0,27 |
| 30 | 0,41 | 0,46 | 0,56 | 0,47 | 0,42 |
| 40 | 0,67 | 0,74 | 0,86 | 0,75 | 0,69 |
| 50 | 0,91 | 0,95 | 1,05 | 1,01 | 1,00 |
| 60 | 0,99 | 1,05 | **1,16** | 1,15 | 1,15 |

Lãi net (điểm):

| W | 1,00 | 1,25 | 1,50 | 1,75 | 2,00 |
|---|---:|---:|---:|---:|---:|
| 20 | 191 | 124 | 164 | 174 | 125 |
| 30 | −95 | 367 | 345 | 280 | −8 |
| 40 | 323 | 526 | 434 | 384 | 294 |
| 50 | 642 | 522 | 624 | 663 | 367 |
| 60 | 478 | 542 | 571 | 659 | 445 |

Chọn **W = 60, z_in = 1,5**: lãi 570,7 điểm (57,1 triệu đồng), Sharpe 1,11, MDD 184 điểm (18,4% vốn), margin 14,5 bps,
161 lệnh, hit rate 42%, chi phí 128,4 điểm, có vị thế 50% thời gian, ký quỹ cao nhất 20,4%. Cả 6 ô kề đều lãi sau chi
phí.

Ô được chọn nằm ở biên lưới (W = 60 là giá trị lớn nhất được thử), và Sharpe tăng dần theo W. Lưới đã khoá trong
protocol nên không mở rộng; ghi lại để phán quyết sau.

Kiểm tra cơ chế với ô đã chọn:

- **B4 không xảy ra**: 79,2% trong 380 lần |Z| vượt 1,5 thì |Z| về dưới 0,75 trong vòng 8 nến.
- **B5 không xảy ra**: lãi gộp 699,1 điểm = 636,4 điểm do basis co lại + 62,7 điểm do chỉ số chạy.

## 3. Calendar MTW

Giữ tham số của repo calendar-mtw-vn30f, không tối ưu lại (protocol mục 3.4).

## 4. Chưa chạy

7 tổ hợp trên in-sample và valid; B2 và B6 trên valid; chọn tổ hợp cuối; OOS 1 và OOS 2.

## 5. Ghi chú vận hành

Phiên đáo hạn 16/07/2020 không có trong dữ liệu DNSE ở mọi khung, nên luật đứng ngoài phiên đáo hạn không kích hoạt
được tháng đó. Engine đóng mọi vị thế ở nến cuối của mỗi hợp đồng và reset trạng thái sleeve, để không vị thế nào vắt
qua lần đổi hợp đồng. Đây là chốt an toàn cho dữ liệu thiếu, không đổi luật giao dịch.
