# 3. Chuyển giả thuyết thành luật

Chương này viết luật của từng sleeve bằng tham số, chưa gán giá trị. Giá trị ban đầu dùng ở bước 4 nằm ở mục 4.1; bước 5
chọn lại một số tham số theo luật chọn đã chốt trước (chương 5).

Luật nằm trong `PS_V30_Vien_Calibrum/PS_V30_Vien_Calibrum.py`. Tham số có ba nguồn: `config.json` (đổi được không cần sửa
code), `PS_V30_Vien_Calibrum_model.pt` (hệ số hồi quy của Momentum và trọng số ensemble), và vài hằng số viết thẳng trong
code. Ở mỗi lần nến đóng, mỗi sleeve cho ra một vị thế thuộc {−1, 0, +1}. Luật phiên và cách gộp nằm trong
`src/adapters/strategies/calibrum_signal_source.py`.

## 3.1 Momentum

Sleeve này gộp năm đặc trưng bằng hồi quy Ridge; trong code nó mang tên `ridge` (`_ridge_positions`,
`ridge_entry_threshold`, ...). Điểm số chỉ tính trên các nến thường từ 09:00 đến 14:00 (không tính nến 11:30 và 14:30):

```text
Score_t = β_0 + Σ_{j=1..5} β_j · clip((f_j,t − μ_j) / s_j, −c, c)
```

| Đặc trưng | Định nghĩa |
|---|---|
| f1 | (Close − Open của nến 09:00) / ATR |
| f2 | (Close − SMA của Close trên n_SMA nến) / ATR |
| f3 | (Close − Open) / ATR |
| f4 | (ΣUp² − ΣDown²) / (ΣUp² + ΣDown²) trên n_A nến |
| f5 | (Close − VWAP phiên) / ATR, VWAP tính từ HLC3 × khối lượng kể từ 09:00 |

ATR là trung bình true range của n_ATR nến thường trước đó. μ_j và s_j chuẩn hoá từng đặc trưng; c cắt các giá trị cực
đoan. Giả thuyết ở chương 1 cho dấu kỳ vọng của hệ số: β_1 đến β_4 dương (đi theo đà), β_5 âm (xa VWAP thì lực kéo
ngược).

| Luật | Điều kiện |
|---|---|
| Vào lệnh mua | Score ≥ +θ_M |
| Vào lệnh bán | Score ≤ −θ_M |
| Thoát lệnh | Lỗ tại giá đóng nến ≥ L_M điểm; hoặc, sau ít nhất h_M nến, Score đổi dấu; hoặc đã giữ H_M nến |

Thời gian giữ chỉ đếm các nến có tính Score, nên vị thế có thể giữ qua đêm. Thoát lệnh xong, sleeve có thể vào lại ngay
trên cùng nến đó.

## 3.2 Basis

```text
Basis_t = Close(VN30F1M)_t − Close(VN30)_t
Z_t     = (Basis_t − trung bình W nến gần nhất) / (độ lệch chuẩn W nến gần nhất)
```

Giá đóng chỉ số là giá gần nhất đã biết tại nến hợp đồng (ghép as-of). Cửa sổ cần ít nhất W_min nến. Trong code, sleeve
này và các tham số của nó mang tên `shinji` (`_shinji_positions`, `shinji_window`, ...).

| Luật | Điều kiện |
|---|---|
| Vào lệnh mua | Z ≤ −z_in |
| Vào lệnh bán | Z ≥ +z_in |
| Đảo chiều | Z chạm cực trị phía bên kia sau khi đã giữ ít nhất h_B nến |
| Thoát lệnh | Lỗ tại giá đóng nến ≥ L_B điểm; hoặc \|Z\| ≤ z_out sau ít nhất h_B nến |

## 3.3 Calendar

| Chân | Ngày | Vị thế |
|---|---|---|
| Mua | Các thứ trong tuần thuộc tập D_long, k phiên đầu tháng, phiên cuối trước kỳ nghỉ | +1 cả phiên; bắt đầu từ nến cuối của phiên trước |
| Bán thứ Hai | Thứ Hai thông thường (không phải ngày mua) có gap mở cửa ≤ g_max điểm | −1 từ 09:00 đến trước T_end |
| Mua ngày đáo hạn | Thứ Năm tuần thứ ba của tháng, nếu không có chân nào khác đang bật | +1 từ 09:00 đến trước T_end |

Mỗi chân phụ (đầu tháng, trước kỳ nghỉ, bán thứ Hai, đáo hạn) có một công tắc bật/tắt riêng trong `config.json`.

Có ba chi tiết lịch trong code đóng băng khác với lịch của sàn: các phiên đầu tháng được đếm theo ngày làm việc trong
tuần, "phiên kế tiếp" cho lệnh mua qua đêm bỏ qua cuối tuần nhưng không bỏ qua ngày lễ, và chân đáo hạn luôn dùng thứ
Năm tuần thứ ba kể cả khi đó là ngày nghỉ (18/04/2024, 19/02/2026).

## 3.4 Gộp các sleeve

Gọi M, B, C là vị thế của ba sleeve, với trọng số w_M, w_B, w_C:

| Cách gộp | Vị thế | Số hợp đồng trên Plutus |
|---|---|---|
| Majority vote | sign(w_M·M + w_B·B + w_C·C) ∈ {−1, 0, +1} | N × vị thế |
| Equal-weight sum | w_M·M + w_B·B + w_C·C | bằng vị thế |

Với trọng số bằng nhau và N = 3, cả hai cách gộp đều tối đa 3 hợp đồng trên Plutus, nên được so sánh ở cùng quy mô.

## 3.5 Thời điểm và ràng buộc thị trường

- Tín hiệu tính tại giá đóng của nến T, khớp ở nến T+1.
- Luật ATC: nến 14:30 giữ nguyên vị thế của nến 14:00, nên không ra quyết định mới trong phiên ATC. Trong ensemble, luật
  này thay cho lệnh vào lúc 14:30 của Calendar, nên chân mua qua đêm của Calendar bắt đầu từ phiên hôm sau.
- Về 0 ngày đáo hạn: trong mỗi phiên đáo hạn, ensemble về 0 từ nến 14:00, nên không vị thế nào vắt qua lúc đổi hợp đồng.
- Basis khởi động lại ở mỗi hợp đồng mới và đứng ngoài trong phiên đáo hạn. Momentum không khởi động lại.

## 3.6 Danh sách tham số

| Sleeve | Ký hiệu | Ý nghĩa | Tên trong code | Nguồn |
|---|---|---|---|---|
| Momentum | β_0 … β_5 | Hệ số chặn và hệ số của 5 đặc trưng | `ridge_intercept`, `ridge_coef` | model.pt |
| Momentum | μ_j, s_j | Tâm và thang chuẩn hoá của từng đặc trưng | `ridge_centers`, `ridge_scales` | model.pt |
| Momentum | c | Ngưỡng cắt sau chuẩn hoá | | code |
| Momentum | n_ATR, n_SMA, n_A | Số nến của ATR, SMA và bất đối xứng | | code |
| Momentum | θ_M | Ngưỡng vào lệnh | `ridge_entry_threshold` | config |
| Momentum | h_M, H_M | Thời gian giữ tối thiểu / tối đa (nến) | `ridge_min_hold`, `ridge_max_hold` | config |
| Momentum | L_M | Cắt lỗ (điểm) | `ridge_stop_loss_pts` | config |
| Basis | W | Cửa sổ z-score (nến) | `shinji_window` | config |
| Basis | W_min | Số nến tối thiểu để tính z-score | | code |
| Basis | z_in, z_out | Ngưỡng z vào / thoát | `shinji_z_entry`, `shinji_z_exit` | config |
| Basis | h_B | Thời gian giữ tối thiểu (nến) | `shinji_min_hold` | config |
| Basis | L_B | Cắt lỗ (điểm) | `shinji_stop_loss` | config |
| Calendar | D_long | Các thứ mua trong tuần | `calendar_long_dows` | config |
| Calendar | k | Số phiên đầu tháng được mua | | code |
| Calendar | g_max | Gap mở cửa tối đa của thứ Hai (điểm) | `calendar_monday_max_gap` | config |
| Calendar | T_end | Giờ kết thúc chân trong phiên | `calendar_session_end` | config |
| Calendar | | Bật/tắt từng chân phụ | `calendar_use_*` | config |
| Ensemble | w_M, w_B, w_C | Trọng số của ba sleeve | `ensemble_weights` | model.pt |
| Ensemble | N | Số hợp đồng mỗi đơn vị vị thế của vote trên Plutus | `PLUTUS_CONTRACTS` | Makefile |
