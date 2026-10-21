# Bài tập: tự tính kết quả backtest của lab

Dữ liệu: [lab_exercise.csv](lab_exercise.csv). Đây là dữ liệu giả, 4 phiên, mỗi phiên rút gọn còn 4 nến (phiên thật có
10 nến). Số được chọn tròn để tính tay. Đáp án nằm ở [lab_exercise_answers.md](lab_exercise_answers.md), tính bằng đúng
engine lab trong `src/lab/backtest/`. Làm xong rồi hãy mở.

| # | Thời điểm (nhãn nến) | Close | Pos |
|---:|---|---:|---:|
| 0 | 05/01 09:00 | 1500 | 0 |
| 1 | 05/01 10:30 | 1503 | +1 |
| 2 | 05/01 13:00 | 1501 | +1 |
| 3 | 05/01 14:30 | 1506 | 0 |
| 4 | 06/01 09:00 | 1504 | 0 |
| 5 | 06/01 10:30 | 1500 | −1 |
| 6 | 06/01 13:00 | 1497 | −1 |
| 7 | 06/01 14:30 | 1499 | −1 |
| 8 | 07/01 09:00 | 1495 | +1 |
| 9 | 07/01 10:30 | 1496 | +1 |
| 10 | 07/01 13:00 | 1500 | 0 |
| 11 | 07/01 14:30 | 1502 | 0 |
| 12 | 08/01 09:00 | 1503 | 0 |
| 13 | 08/01 10:30 | 1501 | +1 |
| 14 | 08/01 13:00 | 1498 | +1 |
| 15 | 08/01 14:30 | 1499 | 0 |

`Pos` là vị thế chiến lược quyết định tại giá đóng của nến đó (đơn vị: hợp đồng).

## Luật tính (giống lab)

- `HeldPos[t] = Pos[t−1]`: vị thế thực sự cầm trong nến t là vị thế đã quyết định ở nến trước. Nến đầu tiên: 0.
- `Gross[t] = HeldPos[t] × (Close[t] − Close[t−1])`. Nến đầu tiên: 0.
- `Fee[t] = 0.4 × |Pos[t] − Pos[t−1]|` (phí 0,8 điểm mỗi vòng, chia đều cho lúc vào và lúc ra). Nến đầu tiên: so với 0.
- `Net[t] = Gross[t] − Fee[t]`.

## Câu hỏi

1. Điền bảng: `HeldPos`, `Gross`, `Fee`, `Net` cho cả 16 nến.
2. Tổng Gross, tổng Fee, tổng Net của cả 4 phiên.
3. Lãi lỗ của từng phiên, `D` (cộng `Net` của 4 nến trong phiên).
4. Sharpe sau phí: `mean(D) / std(D) × √252`, với `std` là độ lệch chuẩn mẫu (chia cho n − 1).
5. Max drawdown: cộng dồn `Net` theo từng nến, rồi tìm mức sụt lớn nhất tính từ một đỉnh trước đó.
6. Số lệnh: `Σ |Pos[t] − Pos[t−1]| / 2`.
7. Hit rate: một lệnh là một chuỗi nến liên tiếp có `HeldPos` cùng dấu khác 0. Bao nhiêu phần trăm số lệnh có tổng
   `Gross` dương?
8. Margin sau phí (bps): `tổng Net / Σ (Close[t] × |Pos[t] − Pos[t−1]|) × 10.000`.

## Câu hỏi suy nghĩ

- Ở nến 8 (07/01 09:00), vị thế đổi từ −1 sang +1. Phí bao nhiêu, vì sao? Nến đó lãi hay lỗ, và lãi lỗ đó thuộc về vị
  thế nào?
- Ở nến 1 (05/01 10:30), chiến lược quyết định mua, và giá đã tăng 3 điểm trong nến đó. Vì sao lab không tính 3 điểm
  này cho mình?
- Sharpe ở câu 4 rất cao. Vì sao không nên tin con số Sharpe tính từ 4 phiên?
