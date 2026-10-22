# Protocol: Calibrum trên nến 1 phút, fit lại Momentum và tối ưu lại (22/10/2026)

Chốt 22/10/2026, trước khi chạy bất kỳ backtest nào của nhánh này. Sửa sau ngày này là lần thử mới.

Nhánh này dựng lại Calibrum trên dữ liệu mới (`config/research.toml`): nến 1 phút DNSE, lấp bằng nến 5 phút ở những
phiên thiếu, in-sample 01/06/2020 đến 31/12/2022. Ba sleeve giữ nguyên giả thuyết của protocol cũ
(`research/calibrum/ridge_h2`, `research/calibrum/shinji`) và của repo calendar-mtw-vn30f; thứ thay đổi là dữ liệu,
cách tính tiền, và các tham số được chọn lại theo hàm mục tiêu viết ở đây. Kết quả cũ không dùng để chọn gì trong nhánh
này.

## 1. Giả thuyết

Ba nguồn alpha có cơ chế khác nhau, mỗi nguồn lãi sau phí trên VN30F1M khi đứng riêng, và gộp lại thì lãi đều hơn từng
nguồn:

- **Calendar MTW:** VN30F1M yếu trong phiên thứ Hai và mạnh từ cuối phiên thứ Hai đến sáng thứ Năm.
- **Basis:** khi basis (VN30F1M − VN30) lệch khỏi trung bình W nến 30 phút từ z_in độ lệch chuẩn trở lên, basis co lại
  về trung bình trong vài phiên, và phần co lại lớn hơn phí một vòng.
- **Momentum:** khi giá đóng nến 30 phút đã lệch khỏi giá mở cửa 09:00, khỏi SMA4 và khỏi thân nến theo cùng một chiều,
  giá đi tiếp theo chiều đó trong 2 nến kế tiếp; lực đi tiếp yếu dần khi giá đã cách VWAP phiên quá xa.

## 2. Nguồn alpha và cơ chế

| Sleeve | Nguồn (ALGOTRADE) | Ai trả tiền | Khi nào mất |
|---|---|---|---|
| Calendar MTW | Kinh nghiệm giao dịch, thiên kiến hành vi | Người bán bắt buộc đầu tuần (ký quỹ, tin cuối tuần), người bắt đáy sớm thứ Hai | Chu kỳ thanh toán hoặc cách xử lý ký quỹ thay đổi |
| Basis | Mispricing, hiểu biết riêng về thị trường VN | Cá nhân mua đuổi, bán tháo hợp đồng đòn bẩy nhanh hơn rổ 30 cổ phiếu theo kịp | Cho bán khống, có ETF VN30 rẻ làm chân cơ sở, tổ chức arbitrage quy mô lớn |
| Momentum | Thiên kiến hành vi, đo bằng mô hình thống kê | Cá nhân vào lệnh trễ đuổi theo giá đã chạy từ đầu phiên | Tỷ trọng tổ chức và bot tăng; thị trường đi ngang hẹp kéo dài |

Chi tiết cơ chế giữ như protocol cũ của từng sleeve.

## 3. Luật đo được

### 3.1 Dữ liệu, khớp lệnh, tiền

- Nến gốc: `src/adapters/data/dnse_minute_bars.py`. Nến 10 phút và 30 phút gộp từ nến gốc; mã hợp đồng gần nhất gắn
  theo lịch đáo hạn.
- Giá: giá gốc của hợp đồng cho khớp lệnh, lãi lỗ, chi phí, ký quỹ, stop, Basis và Calendar MTW. Riêng đặc trưng
  Momentum dùng bản sao **điều chỉnh cộng**: ở mỗi lần đổi hợp đồng, toàn bộ lịch sử trước đó cộng thêm
  `Open(nến đầu hợp đồng mới) − Close(nến cuối hợp đồng cũ)`. Khoảng này gồm cả biến động qua đêm, vì DNSE chỉ có một
  chuỗi liên tục, không có hai hợp đồng chồng nhau.
- Khớp lệnh: tại giá close của nến ra tín hiệu (10 phút cho MTW, 30 phút cho Basis và Momentum). Stop xét và khớp tại
  close của mỗi nến gốc (1 phút; 5 phút ở các phiên lấp).
- Tài khoản: 100 triệu đồng cho mỗi hợp đồng, số hợp đồng cố định, không cộng dồn lãi.
- Chi phí: **0,4 điểm mỗi hợp đồng mỗi chiều** (40.000 đ), gộp mọi khoản. Phần phí nhà nước và sàn theo rulebook
  `vn-2020-2026` của Plutus chỉ khoảng 0,11 điểm năm 2020 và 0,16 điểm năm 2026 (phí HNX 2.700 đ, phí VSDC 2.550 đ,
  thuế TNCN 0,0005 × tỷ lệ ký quỹ × giá trị hợp đồng); phần còn lại trả cho hoa hồng môi giới, trượt giá khi khớp ở
  giá close, và phí VSDC tính theo ngày giữ lệnh trước 2022. Mức này bảo thủ có chủ đích, để việc chọn tham số không
  dựa vào giả định khớp lệnh đẹp.
- Ký quỹ: tỷ lệ ký quỹ ban đầu theo ngày hiệu lực lấy từ Plutus (`vsd_initial_margin`: 13% đến 14/12/2022, 17% từ
  15/12/2022), dùng để báo mức sử dụng ký quỹ.
- Luật phiên chung: nến 30 phút 14:30 (ATC) giữ vị thế của nến 14:00. Trong phiên đáo hạn, Basis và Momentum về 0 từ
  nến 14:00 và tính lại từ đầu ở hợp đồng mới. Phiên không có dữ liệu chỉ số thì Basis đứng ngoài. Phiên thiếu ở mọi
  khung thì không giao dịch, không lấp giá.

### 3.2 Momentum: mô hình Ridge fit lại

Tính trên 8 nến 30 phút thường (09:00, 09:30, 10:00, 10:30, 11:00, 13:00, 13:30, 14:00), chuỗi điều chỉnh cộng.
ATR14 là trung bình 14 true range đã `shift(1)`.

Đặc trưng tại nến t:

```text
x1 = (C_t − VWAP phiên_t) / ATR14_t          VWAP = Σ HLC3·V / Σ V từ 09:00
x2 = (C_t − Open 09:00 của phiên) / ATR14_t
x3 = (C_t − SMA4(C)_t) / ATR14_t
x4 = (Σ₄ up² − Σ₄ down²) / (Σ₄ up² + Σ₄ down²)   trên 4 thay đổi giá gần nhất
x5 = (C_t − O_t) / ATR14_t
```

Chuẩn hoá bằng median và IQR của in-sample, cắt ở ±8: `z_j = clip((x_j − med_j) / IQR_j, −8, 8)`.

Biến mục tiêu: lợi suất 2 nến thường kế tiếp, tính theo ATR:

```text
y_t = (C_{t+2} − C_t) / ATR14_t
```

Bỏ những mẫu mà t+2 nằm ở hợp đồng khác t.

**Hàm mục tiêu** (Ridge, β₀ không bị phạt):

```text
J(β₀, β) = (1/n) Σ_t (y_t − β₀ − z_tᵀβ)² + λ ‖β‖²
```

Nghiệm đóng: `β = (ZᵀZ/n + λI)⁻¹ Zᵀ(y − ȳ)/n` trên Z đã trừ trung bình, `β₀ = ȳ − z̄ᵀβ`.

Chọn λ bằng kiểm định chéo theo thời gian trong in-sample, không dùng valid:

- 4 fold mở rộng: kiểm định lần lượt trên 2021-H1, 2021-H2, 2022-H1, 2022-H2; phần fit của mỗi fold là mọi nến từ
  01/06/2020 tới trước fold đó, bỏ 2 nến cuối (purge) để target không chồng sang fold kiểm định.
- Median, IQR và β chỉ tính trên phần fit của fold.
- λ ∈ {0,01; 0,1; 1; 10; 100}. Chọn λ có MSE ngoài fold trung bình nhỏ nhất; chênh dưới 1% thì chọn λ lớn hơn (mô
  hình đơn giản hơn).
- Fit lại trên toàn bộ in-sample với λ đã chọn; median, IQR, β₀, β đóng băng từ đó.

Score: `s_t = β₀ + z_tᵀβ`.

Luật vị thế (giữ như code cũ, chỉ đổi ngưỡng và cách xét stop):

- Đứng ngoài: s ≥ θ thì Long, s ≤ −θ thì Short.
- Đang có vị thế: thoát khi đã giữ ít nhất 2 nến 30 phút và s đổi dấu; hoặc đã giữ 8 nến; hoặc lỗ chưa chốt ≥ 10 điểm
  tại close của một nến gốc bất kỳ.
- Ngưỡng: `θ = phân vị q của |s|` trên in-sample. Score mới có thang khác score cũ nên không dùng lại 0,18.
  q ∈ {0,70; 0,80; 0,90}, chọn q có Sharpe in-sample sau chi phí cao nhất của sleeve Momentum.

### 3.3 Basis: lưới cửa sổ × ngưỡng vào

```text
Basis_t = C_t(VN30F1M, giá gốc) − C_t(VN30)      VN30 ghép as-of, chỉ lấy giá đã biết
Z_t     = (Basis_t − mean_W) / (std_W + 1e-6)     cần ít nhất 15 nến
```

- Vào: Z ≤ −z_in thì Long, Z ≥ +z_in thì Short.
- Đang có vị thế, đã giữ ít nhất 2 nến: Z chạm cực trị ngược chiều thì đảo; |Z| ≤ 0 thì về 0 (giữ như code, thực tế
  gần như không kích hoạt).
- Stop: lỗ chưa chốt ≥ 14 điểm tại close của một nến gốc bất kỳ.
- Tính lại từ đầu ở mỗi hợp đồng mới, đứng ngoài trong phiên đáo hạn.

Lưới: W ∈ {20; 30; 40; 50; 60} × z_in ∈ {1,00; 1,25; 1,50; 1,75; 2,00}, 25 ô. Mục tiêu: Sharpe in-sample sau chi phí của
sleeve Basis. Chọn vùng, không chọn đỉnh: điểm của một ô là trung bình Sharpe của ô đó và các ô kề trong khung 3 × 3 (ở
biên lấy các ô có sẵn); chọn ô có điểm cao nhất.

### 3.4 Calendar MTW

Giữ nguyên alpha đã chọn ở repo calendar-mtw-vn30f: M3 + W0X1, IB 3 nến, cửa sổ bán thứ Hai tới 13:00, vào lệnh mua
14:20 phiên trước thứ Ba, thoát 10:00 phiên sau thứ Tư. Không tối ưu lại (0 lần thử mới); các lần thử của repo đó tính
vào tổng ở mục 6.

### 3.5 Gộp

7 tổ hợp: C, B, M, C+B, C+M, B+M, C+B+M. Gộp bằng vote: `sign(tổng vị thế các sleeve)`, 1 hợp đồng, 100 triệu đồng.
Cách gộp sum và vốn của nó để sau, không thuộc protocol này.

Chọn tổ hợp cuối: trong các tổ hợp dương sau chi phí ở valid, chọn tổ hợp có Sharpe in-sample cao nhất; chênh dưới 0,2 thì
chọn tổ hợp ít sleeve hơn.

### 3.6 Chỉ số

Lãi lỗ theo ngày bằng VND trên vốn cố định. Sharpe = trung bình / độ lệch chuẩn lợi suất ngày × √252, không trừ lãi suất
phi rủi ro. Kèm: lãi net, MDD (%), margin sau chi phí (bps trên giá trị giao dịch), số lệnh, hit rate, mức sử dụng ký
quỹ cao nhất (ký quỹ ban đầu theo ngày ÷ vốn), lãi theo năm.

## 4. Dự đoán bác bỏ

- B1 (Momentum): IC Spearman giữa s và y ngoài fold ≤ 0 ở ít nhất 2 trong 4 fold của λ đã chọn. Score không dự báo
  được chiều giá, giả thuyết Momentum sai.
- B2 (Momentum): IC trên valid 2023–2024 ≤ 0.
- B3 (Momentum): dấu hệ số của x2 (đuổi giá từ đầu phiên) không dương, hoặc của x1 (VWAP) không âm, trong fit cuối. Cơ
  chế ở mục 2 không còn là thứ mô hình học được.
- B4 (Basis): trong in-sample, trong các lần |Z| vượt z_in, tỷ lệ |Z| về dưới z_in / 2 trong vòng 8 nến không quá 50%.
- B5 (Basis): tách lãi lỗ từng lệnh thành phần do Δbasis và phần do Δchỉ số; tổng phần Δbasis trên in-sample ≤ 0. Sleeve
  lãi nhờ đoán hướng thị trường, không nhờ basis hồi.
- B6 (mọi sleeve): lãi sau chi phí trên valid 2023–2024 ≤ 0.

Sleeve dính bất kỳ dự đoán nào thì loại khỏi các tổ hợp ở bước chọn cuối.

## 5. Tiêu chí chấp nhận

Tổ hợp cuối, trên in-sample: Sharpe sau chi phí ≥ 1,5; margin sau chi phí ≥ 15 bps; ít nhất 180 lệnh; lãi ở cả ba khoảng
06–12/2020, 2021, 2022. Tham số chọn được phải nằm trong vùng ổn định: ở Basis, các ô kề đều lãi sau chi phí; ở
Momentum, cả ba giá trị q đều lãi sau chi phí. DSR (mục 6) ≥ 0,95.

## 6. Ngân sách lần thử

Lần thử mới của nhánh này, khoá trước:

| Lần thử | Số biến thể |
|---|---:|
| Momentum: λ | 5 |
| Momentum: q | 3 |
| Basis: W × z_in | 25 |
| Gộp: chọn 1 trong 7 tổ hợp | 7 |
| **Tổng mới** | **40** |

Tổng tích luỹ (cận dưới, vì lịch sử trước khi có repo không được ghi): Ridge 27, Basis 9, các phép thử bước 5 cũ của
Calibrum 6, Calendar MTW 334 (repo calendar-mtw-vn30f: 16 + 318), nhánh này 40. N ≥ 416. DSR tính với N = 416 và ghi rõ
là cận dưới.

## 7. Dữ liệu

| Khoảng | Ngày | Vai trò | Đã nhìn trước nhánh này |
|---|---|---|---|
| Khởi động | hợp đồng từ 13/08/2018, chỉ số từ 11/05/2020 | Chỉ để chỉ báo có đủ lịch sử | |
| In-sample | 01/06/2020 – 31/12/2022 | Fit Ridge, chọn λ, q, ô Basis | Nhiều |
| Valid | 01/01/2023 – 31/12/2024 | B2, B6, chọn tổ hợp cuối | ≥ 4 lần với Basis và Momentum cũ; 1 lần với MTW |
| OOS 1 | 01/01/2025 – 31/12/2025 | Mở một lần, sau khi mọi lựa chọn đã chốt | ≥ 4 lần (Basis, Momentum cũ, audit Finpros); 1 lần (MTW) |
| OOS 2 | 01/01/2026 – 21/10/2026 | Mở một lần, sau OOS 1 | ≥ 4 lần (Basis, Momentum cũ); 1 lần (MTW) |
| Khoá thật | từ 22/10/2026 | Paper trading / chấm cuối | 0 |

OOS 1 và OOS 2 là ngoài mẫu đối với **tham số mới** của nhánh này: không lựa chọn nào ở mục 3 nhìn vào chúng. Nhưng
người nghiên cứu đã thấy kết quả của các phiên bản trước trên hai khoảng này, nên report phải ghi rõ đây không phải dữ
liệu mù. Dữ liệu mù duy nhất bắt đầu từ 22/10/2026.

## 8. Quyết định đã chốt (22/10/2026)

1. Chi phí 0,4 điểm mỗi chiều gộp mọi khoản; không chạy mức chi phí khác.
2. Lưới λ, q, W × z_in như mục 3.2 và 3.3.
3. Luật chọn tổ hợp cuối như mục 3.5.
4. Tên giai đoạn: in-sample, valid, OOS 1, OOS 2.
