# Đáp án bài tập lab

Tính bằng `evaluate(..., BacktestConfig(round_trip_fee_points=0.8))` trong `src/lab/backtest/`.

## 1. Bảng từng nến

| # | Close | Pos | HeldPos | ΔClose | Gross | \|ΔPos\| | Fee | Net | Net cộng dồn |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | 1500 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 1 | 1503 | +1 | 0 | +3 | 0 | 1 | 0.4 | −0.4 | −0.4 |
| 2 | 1501 | +1 | +1 | −2 | −2 | 0 | 0 | −2.0 | −2.4 |
| 3 | 1506 | 0 | +1 | +5 | +5 | 1 | 0.4 | +4.6 | +2.2 |
| 4 | 1504 | 0 | 0 | −2 | 0 | 0 | 0 | 0 | +2.2 |
| 5 | 1500 | −1 | 0 | −4 | 0 | 1 | 0.4 | −0.4 | +1.8 |
| 6 | 1497 | −1 | −1 | −3 | +3 | 0 | 0 | +3.0 | +4.8 |
| 7 | 1499 | −1 | −1 | +2 | −2 | 0 | 0 | −2.0 | +2.8 |
| 8 | 1495 | +1 | −1 | −4 | +4 | 2 | 0.8 | +3.2 | +6.0 |
| 9 | 1496 | +1 | +1 | +1 | +1 | 0 | 0 | +1.0 | +7.0 |
| 10 | 1500 | 0 | +1 | +4 | +4 | 1 | 0.4 | +3.6 | +10.6 |
| 11 | 1502 | 0 | 0 | +2 | 0 | 0 | 0 | 0 | +10.6 |
| 12 | 1503 | 0 | 0 | +1 | 0 | 0 | 0 | 0 | +10.6 |
| 13 | 1501 | +1 | 0 | −2 | 0 | 1 | 0.4 | −0.4 | +10.2 |
| 14 | 1498 | +1 | +1 | −3 | −3 | 0 | 0 | −3.0 | +7.2 |
| 15 | 1499 | 0 | +1 | +1 | +1 | 1 | 0.4 | +0.6 | +7.8 |

## 2 đến 8

| Câu | Đáp án |
|---|---|
| 2. Tổng Gross / Fee / Net | +11.0 / 3.2 / **+7.8** điểm |
| 3. D theo phiên | 05/01: +2.2 · 06/01: +0.6 · 07/01: +7.8 · 08/01: −2.8 |
| 4. Sharpe | mean = 1.95, std = 4.422, tỉ số = 0.441 → × √252 ≈ **7.00** |
| 5. Max drawdown | Đỉnh +10.6 (nến 10 đến 12), đáy +7.2 (nến 14) → **3.4** điểm |
| 6. Số lệnh | Σ\|ΔPos\| = 8 → **4** lệnh |
| 7. Hit rate | 4 lệnh, Gross: +3, +5, +5, −2 → **75%** |
| 8. Margin | Σ Close·\|ΔPos\| = 1503 + 1506 + 1500 + 2×1495 + 1500 + 1501 + 1499 = 11,999 → 7.8 / 11,999 × 10,000 ≈ **6.50 bps** |

Bốn lệnh ở câu 7 (tính theo `HeldPos`):

| Lệnh | Các nến cầm | Chiều | Gross |
|---|---|---|---:|
| 1 | 2 đến 3 | Mua | −2 + 5 = +3 |
| 2 | 6 đến 8 | Bán | +3 − 2 + 4 = +5 |
| 3 | 9 đến 10 | Mua | +1 + 4 = +5 |
| 4 | 14 đến 15 | Mua | −3 + 1 = −2 |

## Câu hỏi suy nghĩ

- Nến 8: vị thế từ −1 sang +1, thay đổi 2 đơn vị, nên phí 0,8: đóng lệnh bán (0,4) và mở lệnh mua (0,4). Nến đó lãi +4
  vì `HeldPos` vẫn là −1 trong suốt nến (giá giảm 4 điểm khi đang bán). Lãi này thuộc về lệnh bán cũ; lệnh mua mới chỉ
  bắt đầu tính từ nến 9.
- Nến 1: quyết định mua được đưa ra *tại giá đóng* của nến 1 (1503), tức sau khi giá đã tăng 3 điểm. Không thể mua ở
  giá 1500 để ăn khoản đó, vì lúc 1500 chưa có tín hiệu. Đây là lý do `HeldPos[t] = Pos[t−1]`: chống nhìn trước tương lai.
- Sharpe 7 đến từ chỉ 4 quan sát; độ lệch chuẩn của 4 số rất không ổn định, và nhân √252 phóng đại thêm. Cần hàng
  trăm phiên thì Sharpe mới có ý nghĩa. Cũng vì vậy mà backtest thật dùng 401 phiên in-sample.
