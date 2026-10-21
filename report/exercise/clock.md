# Đồng hồ của mô hình: lúc nào biết gì, tính gì, cầm gì

Tạo lại bảng bằng `uv run python scripts/explain_session_clock.py --date 2021-06-03` (lab, DNSE, majority vote).

## 1. Nhãn nến và giờ thật

Nến được gắn nhãn theo giờ **bắt đầu**. Giá Close của nến có ở giờ **kết thúc**:

| Nhãn nến | Khoảng thời gian | Close biết lúc |
|---|---|---|
| 09:00 | 09:00 đến 09:30 | 09:30 |
| 09:30 … 11:00 | 30 phút mỗi nến | nhãn + 30 phút |
| 11:30 | phút cuối trước giờ nghỉ trưa | 11:30 |
| 13:00 … 14:00 | 30 phút mỗi nến | nhãn + 30 phút |
| 14:30 | phiên ATC | 14:45 |

## 2. Việc mô hình làm ở mỗi lần nến đóng

```
nến t đóng
   │
   ├─ 1. Dữ liệu: thêm nến t (OHLCV hợp đồng) và giá đóng chỉ số VN30 mới nhất đã biết
   │
   ├─ 2. Momentum:   5 đặc trưng tính từ dữ liệu đến hết nến t → Score
   │              máy trạng thái: đang đứng ngoài? Score ≥ 0.18 → +1, ≤ −0.18 → −1
   │                              đang có lệnh? lỗ ≥ 10, Score đổi dấu sau 2 nến, hoặc giữ 8 nến → về 0
   │              → M ∈ {−1, 0, +1}
   │
   ├─ 3. Basis:   basis = Close hợp đồng − Close chỉ số; Z so với 40 nến gần nhất (của hợp đồng hiện tại)
   │              đứng ngoài? Z ≤ −1.5 → +1, Z ≥ +1.5 → −1;  đang có lệnh? cực trị ngược chiều → đảo, lỗ ≥ 14 → về 0
   │              → B ∈ {−1, 0, +1}
   │
   ├─ 4. Calendar: chỉ cần ngày (và gap mở cửa thứ Hai) → C ∈ {−1, 0, +1}
   │
   ├─ 5. Gộp:     vote = sign(M + B + C)   (sum = M + B + C)
   │              luật phiên: nến 14:30 chép vị thế của 14:00; ngày đáo hạn về 0 từ 14:00
   │              → Pos[t]
   │
   └─ 6. Lệnh:    mua hoặc bán |Pos[t] − Pos[t−1]| hợp đồng tại giá Close[t]
                  vị thế Pos[t] được cầm suốt nến t+1  →  HeldPos[t+1] = Pos[t]
```

Mỗi bước chỉ dùng dữ liệu đến hết nến t. Không bước nào nhìn vào nến t+1.

## 3. Một phiên thật: 03/06/2021

| Nến | Biết lúc | Close | Momentum score | M | Basis Z | B | C | M+B+C | Pos (vote) | Cầm trong 30 phút sau |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 02/06 14:00 | 14:30 | 1481.6 | −0.13 | 0 | −0.12 | 0 | 1 | 1 | **1** | 1 |
| 02/06 14:30 | 14:45 | 1481.8 | – | 0 | 0.04 | 0 | 0 | 0 | **1** | 1 (qua đêm) |
| 09:00 | 09:30 | 1487.4 | 0.04 | 0 | −0.49 | 0 | 0 | 0 | 0 | 0 |
| 09:30 | 10:00 | 1488.0 | 0.02 | 0 | 0.44 | 0 | 0 | 0 | 0 | 0 |
| 10:00 | 10:30 | 1492.6 | 0.11 | 0 | 0.94 | 0 | 0 | 0 | 0 | 0 |
| 10:30 | 11:00 | 1498.7 | **0.21** | **1** | −0.64 | 0 | 0 | 1 | **1** | 1 |
| 11:00 | 11:30 | 1495.6 | 0.09 | 1 | −0.63 | 0 | 0 | 1 | 1 | 1 |
| 11:30 | 11:30 | 1495.7 | – | 1 | −0.59 | 0 | 0 | 1 | 1 | 1 |
| 13:00 | 13:30 | 1506.4 | 0.33 | 1 | 0.36 | 0 | 0 | 1 | 1 | 1 |
| 13:30 | 14:00 | 1503.7 | 0.18 | 1 | −0.97 | 0 | 0 | 1 | 1 | 1 |
| 14:00 | 14:30 | 1507.2 | 0.26 | 1 | 0.41 | 0 | 0 | 1 | 1 | 1 |
| 14:30 | 14:45 | 1504.0 | – | 1 | −0.86 | 0 | 0 | 1 | 1 | 1 (qua đêm) |

"–": Momentum không tính Score ở nến 11:30 và 14:30.

## 4. Đọc bảng theo đồng hồ

- **14:30 ngày 02/06:** 02/06 là phiên thứ hai của tháng, nên Calendar mua cả phiên (C = 1, vote = 1). Lúc 14:00,
  Calendar vẫn +1. Ở nến 14:30, Calendar muốn về 0 vì 03/06 không phải ngày mua. Nhưng luật ATC chép vị thế 14:00 sang
  14:30, nên ensemble giữ +1 qua đêm.
- **09:30 ngày 03/06 (nến 09:00 đóng):** cả ba sleeve đều 0, vote về 0. Lệnh bán khớp ở 1487,4. Vị thế +1 giữ qua đêm
  được tính lãi 1487,4 − 1481,8 = +5,6, trừ phí 0,4.
- **11:00 (nến 10:30 đóng):** Score của Momentum lên 0,21, vượt ngưỡng 0,18, nên Momentum mua. Basis và Calendar đứng ngoài,
  M + B + C = 1, vote = 1. Lệnh mua khớp ở 1498,7, và vị thế bắt đầu tính lãi lỗ từ nến 11:00.
- **Từ 11:00 đến 14:00:** Score có lúc tụt về 0,09 hay 0,18, nhưng chưa đổi dấu (vẫn dương), nên Momentum giữ lệnh.
- **Basis cả phiên:** |Z| không lần nào chạm 1,5, nên Basis đứng ngoài.
- **14:45 (ATC):** vote giữ +1 qua đêm sang ngày 04/06.

Từ bảng này nhìn lại công thức lab: `Pos` là cột "Pos (vote)", và `HeldPos[t]` của nến t là "cầm trong 30 phút sau"
của dòng ngay phía trên.
