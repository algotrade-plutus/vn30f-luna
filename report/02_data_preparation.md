ok 

# 2. Chuẩn bị dữ liệu

## 2.1 Nguồn dữ liệu

|                       | Lab                                                                            | Plutus                                                                                                                |
| --------------------- | ------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------- |
| Nguồn                | API biểu đồ công khai của DNSE, lưu cache dạng Parquet                  | `algotradeDB` (PostgreSQL, chỉ đọc)                                                                              |
| Hợp đồng           | Chuỗi liên tục VN30F1M, nến OHLCV 30 phút                                 | Tick từ `quote.matched` và `quote.matchedvolume`, hợp đồng tháng gần lấy từ `quote.futurecontractcode` |
| Chỉ số              | VN30, nến OHLCV 30 phút                                                      | Tick VN30 từ `quote.matched`                                                                                       |
| Trường bổ sung     | Không có                                                                     | Mã hợp đồng, giá tham chiếu, giá trần và sàn mỗi phiên                                                    |
| Code                  | `src/adapters/data/dnse_candle_source.py`, `scripts/fetch_dnse_candles.py` | `src/adapters/data/postgres_research_source.py`                                                                     |
| Khoảng có dữ liệu | 04/01/2021 đến 01/10/2026                                                    | Nến đầu tiên ngày 01/06/2021                                                                                     |

Cơ sở dữ liệu bắt đầu muộn hơn DNSE: nến đầu tiên là ngày 01/06/2021. Vì vậy in-sample bắt đầu từ 01/06/2021 ở cả hai
engine, để kết quả lab và Plutus cùng phủ 401 phiên.

## 2.2 Nến

Mọi nến dài 30 phút và được gắn nhãn theo giờ bắt đầu: nến có nhãn 10:00 chạy từ 10:00 đến 10:30. Tín hiệu tính từ giá
đóng của một nến chỉ được khớp từ nến tiếp theo.

Các mốc nến của hợp đồng: 09:00, 09:30, 10:00, 10:30, 11:00, 11:30, 13:00, 13:30, 14:00, 14:30. Nến 14:30 là phiên khớp
lệnh định kỳ đóng cửa (ATC).

- DNSE: nến 11:30 có ở 1.071 trên khoảng 1.430 phiên; khi có, nó chứa phút cuối trước giờ nghỉ trưa. Đến giữa năm 2025,
  chuỗi chỉ số VN30 gắn nhãn nến đầu ngày là 09:15 (1.056 phiên): một nến ngắn từ lúc kết thúc phiên định kỳ mở cửa của
  HOSE đến 09:30. Từ giữa năm 2025 thì dùng 09:00. Hàm `align_to_bar_clock` gắn lại nhãn mọi nến DNSE theo giờ bắt đầu
  của khung 30 phút, nên nến chỉ số đầu ngày thành 09:00, giống nến hợp đồng và nến trong cơ sở dữ liệu. Cả hai đều đóng
  lúc 09:30, nên việc gắn lại nhãn không làm nhìn trước tương lai.
- Cơ sở dữ liệu: tick từ 09:00 đến 11:30 và từ 13:00 đến 14:45:59 được gom vào các khung 30 phút, nên tick của phiên ATC
  (14:30 đến 14:45) nằm trong nến 14:30. Open và Close là tick đầu và tick cuối của khung. "Khối lượng" của chỉ số là số
  tick, không phải khối lượng giao dịch thật; không sleeve nào dùng nó.

Ví dụ phiên 03/06/2021 trên cache DNSE, sau khi gắn lại nhãn và thêm mã hợp đồng (`load_research_frames("dnse", …)`).
Cột Basis không có trong dữ liệu, chỉ thêm vào để minh hoạ:

| Nến | Open | High | Low | Close | Khối lượng | Hợp đồng | Close VN30 | Basis |
|---|---:|---:|---:|---:|---:|---|---:|---:|
| 09:00 | 1486,5 | 1491,0 | 1486,3 | 1487,4 | 20.288 | VN30F2106 | 1486,53 | +0,87 |
| 09:30 | 1487,5 | 1489,6 | 1483,1 | 1488,0 | 16.898 | VN30F2106 | 1483,59 | +4,41 |
| 10:00 | 1488,0 | 1493,0 | 1487,5 | 1492,6 | 20.177 | VN30F2106 | 1486,21 | +6,39 |
| 10:30 | 1492,6 | 1498,7 | 1491,3 | 1498,7 | 25.264 | VN30F2106 | 1498,16 | +0,54 |
| 11:00 | 1498,5 | 1499,5 | 1491,4 | 1495,6 | 24.487 | VN30F2106 | 1495,10 | +0,50 |
| 11:30 | 1495,6 | 1495,7 | 1495,1 | 1495,7 | 41 | VN30F2106 | (không có nến) 1495,10 | +0,60 |
| 13:00 | 1495,6 | 1506,7 | 1495,6 | 1506,4 | 28.474 | VN30F2106 | 1502,43 | +3,97 |
| 13:30 | 1506,0 | 1506,3 | 1500,2 | 1503,7 | 22.102 | VN30F2106 | 1504,46 | −0,76 |
| 14:00 | 1503,8 | 1507,4 | 1501,2 | 1507,2 | 18.909 | VN30F2106 | 1503,17 | +4,03 |
| 14:30 | 1507,2 | 1510,6 | 1504,0 | 1504,0 | 4.634 | VN30F2106 | 1504,37 | −0,37 |

Chỉ số không có nến 11:30, nên nến 11:30 của hợp đồng được ghép với giá đóng chỉ số gần nhất đã biết (ghép as-of hướng
backward), không bao giờ với một giá của tương lai.

## 2.3 Từ nến đến vị thế và lãi lỗ

Mỗi lần một nến đóng, mô hình chỉ dùng dữ liệu đến hết nến đó:

```text
nến t đóng
   ├── nến VN30F1M đến t ─────────► Momentum (5 đặc trưng → Score) ─► M ∈ {−1, 0, +1}
   ├── Close VN30F1M − Close VN30 ─► Basis (Z trên 40 nến) ─────────► B ∈ {−1, 0, +1}
   └── ngày, gap mở cửa thứ Hai ──► Calendar ──────────────────────► C ∈ {−1, 0, +1}
                                                                        │
            M + B + C → luật phiên (ATC, ngày đáo hạn) → Pos[t] ◄────────┘
                                                          │
                                         khớp ở nến t+1 ◄─┘
```

Lab biến chuỗi vị thế thành lãi lỗ theo từng nến. Phiên 03/06/2021, ensemble vote, 1 hợp đồng, đơn vị điểm (dòng đầu
là nến cuối của phiên trước, chỉ để làm mốc). Các nến có dấu * dùng vị thế giả định để minh hoạ một lần đảo chiều và
một lần thoát lệnh; thực tế vote giữ +1 đến hết phiên và D = +10,1.

| Nến | Close | Pos | HoldPos | ΔClose | Gross | Phí | Net | Net cộng dồn |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 02/06 14:30 | 1481,8 | +1 | +1 | | | | | |
| 09:00 | 1487,4 | **0** | +1 | +5,6 | +5,6 | 0,4 | +5,2 | +5,2 |
| 09:30 | 1488,0 | 0 | 0 | +0,6 | 0,0 | | 0,0 | +5,2 |
| 10:00 | 1492,6 | 0 | 0 | +4,6 | 0,0 | | 0,0 | +5,2 |
| 10:30 | 1498,7 | **+1** | 0 | +6,1 | 0,0 | 0,4 | −0,4 | +4,8 |
| 11:00 | 1495,6 | +1 | +1 | −3,1 | −3,1 | | −3,1 | +1,7 |
| 11:30 | 1495,7 | +1 | +1 | +0,1 | +0,1 | | +0,1 | +1,8 |
| 13:00* | 1506,4 | **−1** | +1 | +10,7 | +10,7 | 0,8 | +9,9 | +11,7 |
| 13:30* | 1503,7 | −1 | −1 | −2,7 | +2,7 | | +2,7 | +14,4 |
| 14:00* | 1507,2 | **0** | −1 | +3,5 | −3,5 | 0,4 | −3,9 | +10,5 |
| 14:30* | 1504,0 | 0 | 0 | −3,2 | 0,0 | | 0,0 | **+10,5** |

- Pos: vị thế quyết định ở giá đóng của nến (cột `Position` trong `src/lab/backtest`).
- HoldPos = Pos của nến trước: vị thế thật sự cầm trong nến này (`ExecutedPosition`).
- Gross = HoldPos × ΔClose (`GrossGain`); Phí = 0,4 × |Pos − Pos nến trước| (`FeeCost`); Net = Gross − Phí (`NetGain`).
- Đảo chiều từ +1 sang −1 (nến 13:00) là 2 đơn vị thay đổi, nên phí 0,8; nến đó vẫn ăn phần tăng của lệnh mua.
- Tổng Net của phiên là D = +10,5 điểm (bản thật: +10,1), đầu vào của Sharpe trên lab (chương 4).
- Các metric khác cũng tính từ cột Net: margin = tổng Net ÷ Σ(Close × |ΔPos|) × 10⁴, ở đây 10,5 ÷ 7.506,1 × 10⁴ ≈
  14,0 bps; max drawdown là mức sụt lớn nhất của Net cộng dồn, ở đây 14,4 xuống 10,5, tức 3,9 điểm.

Luật của từng sleeve ở chương 3. Bảng từng nến của phiên 03/06/2021 theo đồng hồ (lúc nào biết gì, tính gì, cầm gì) ở
`report/exercise/clock.md`.

## 2.4 Kích thước mỗi giai đoạn

Cache DNSE:

| Giai đoạn   | Thời gian                  | Nến hợp đồng | Phiên hợp đồng | Nến chỉ số | Phiên chỉ số |
| ------------- | --------------------------- | ---------------: | -----------------: | ------------: | --------------: |
| In-sample     | 01/06/2021 đến 30/12/2022 |            4.009 |                401 |         3.581 |             399 |
| Out-of-sample | 01/01/2023 đến 19/12/2024 |            4.904 |                491 |         4.412 |             491 |
| Forward       | 01/01/2026 đến 01/10/2026 |            1.647 |                183 |         1.654 |             183 |

## 2.5 Đổi hợp đồng

VN30F1M là hợp đồng gần đáo hạn nhất. Nó đáo hạn vào thứ Năm tuần thứ ba của tháng (lùi về phiên trước nếu thứ Năm đó
là ngày nghỉ), và hợp đồng tháng sau trở thành hợp đồng tháng gần.

- Cơ sở dữ liệu: mỗi nến mang mã hợp đồng thật. Plutus giao dịch đúng hợp đồng đó và thanh toán khi đáo hạn.
- DNSE: chuỗi liên tục chuyển sang hợp đồng mới sau ngày đáo hạn mà không điều chỉnh giá, và không có mã hợp đồng. Gap
  qua đêm sau phiên đáo hạn trung bình 9,52 điểm, so với 4,45 điểm ở các đêm khác; thay đổi basis qua đêm trung bình
  10,57 điểm so với 4,54. Phần nhảy thêm là chênh lệch giá giữa hợp đồng cũ và hợp đồng mới, không phải biến động của
  thị trường.
- Hàm `add_front_month_contract` gán cho mỗi nến DNSE mã hợp đồng suy ra từ lịch của sàn (`front_month_contract` trong
  `src/domain/strategy/calendar_rules.py`). Đối chiếu với `quote.futurecontractcode` từ 01/06/2021 đến 01/10/2026: mã
  khớp ở mọi phiên giao dịch. Năm dòng lệch đều là ngày nghỉ của sàn (18/04/2024, 16/02 đến 19/02/2026); cơ sở dữ liệu
  có ghi một mã hợp đồng cho những ngày đó nhưng không có giao dịch.

Cả ba sleeve đều đọc giá gốc, không điều chỉnh giá khi đổi hợp đồng. Basis cần giá của đúng hợp đồng đang giao dịch để
tính basis, còn DNSE chỉ có một chuỗi giá, nên mọi cách điều chỉnh đều phải giả định đêm đổi hợp đồng thị trường đứng
yên. Thay vào đó, việc đổi hợp đồng được xử lý bằng luật trong adapter
(`src/adapters/strategies/calibrum_signal_source.py`), giống nhau ở cả hai engine vì nến DNSE giờ đã có mã hợp đồng:

- Roll guard: sleeve được bảo vệ sẽ khởi động lại lịch sử (ATR, cửa sổ trượt, trạng thái vị thế) ở mỗi hợp đồng mới, và
  đứng ngoài trong phiên đáo hạn. Basis có roll guard; Momentum thì không.
- Về 0 ngày đáo hạn: vị thế gộp bằng 0 từ nến 14:00 của mỗi phiên đáo hạn, nên lệnh đóng khớp trong phiên ATC và không
  vị thế nào vắt qua lúc đổi hợp đồng (chương 3).

## 2.6 Chi phí

|                 | Lab                                                                                              | Plutus                                                                                                                                                    |
| --------------- | ------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Phí sàn       | 0,8 điểm chỉ số mỗi vòng (0,4 mỗi đơn vị thay đổi vị thế), đã gồm mọi chi phí | HNX: 2.700 đồng mỗi hợp đồng                                                                                                                        |
| Phí bù trừ   |                                                                                                  | VSDC: 2.550 đồng mỗi hợp đồng                                                                                                                       |
| Thuế           |                                                                                                  | Thuế TNCN trên giao dịch chuyển nhượng phái sinh, tính trên giá trị giao dịch (ví dụ 9.640 đồng cho một lệnh khớp 148,3 triệu đồng) |
| Phí môi giới |                                                                                                  | Bằng 0                                                                                                                                                   |
| Cách khớp     | Giá đóng nến                                                                                 | Khớp mềm theo giá quan sát của nến, không dùng độ sâu sổ lệnh, tối đa 10% khối lượng nến                                               |

Phí Plutus lấy từ các khoản phí ghi trong `reports/calibrum_plutus_*_sum3_300m.json`. Một điểm chỉ số tương ứng
100.000 đồng mỗi hợp đồng.

## 2.7 Các vấn đề dữ liệu đã phát hiện

1. DNSE thiếu dữ liệu chỉ số ở một số phiên. Có 15 phiên hợp đồng trong cache không có nến VN30. Hai phiên nằm trong
   in-sample (14/07/2021, 23/07/2021); các phiên còn lại nằm trước in-sample (21/01 đến 04/02/2021) hoặc trong năm 2025
   không dùng. Basis ghép mỗi nến hợp đồng với giá đóng chỉ số gần nhất đã biết (`merge_asof`, hướng backward), nên ở
   những phiên đó nó sẽ tính basis với giá chỉ số của phiên trước. Giờ Basis chỉ chạy ở phiên có nến chỉ số và đứng
   ngoài ở các phiên còn lại; các phiên bị bỏ qua được ghi trong diagnostics (`shinji_sessions_without_spot`).
2. Giá chỉ số cũ ở nến 09:00. Vì nhãn 09:15 (mục 2.2), đến giữa năm 2025 nến hợp đồng 09:00 của mọi phiên bị ghép với
   giá đóng chỉ số lúc 14:30 của phiên trước, nên sáng nào Basis cũng thấy một basis đã cũ qua đêm. Đã sửa bằng
   `align_to_bar_clock`. Trên lab in-sample, riêng Basis đi từ +273,0 điểm (Sharpe 0,67) lên +689,4 điểm (Sharpe 1,68)
   chỉ nhờ sửa lỗi này.
3. Cú nhảy giá lúc đổi hợp đồng bị tính thành lãi lỗ trên lab. Trong lần chạy lab in-sample (01/06/2021 đến
   30/12/2022, không có roll guard), ensemble giữ vị thế sang nến đầu tiên sau đáo hạn ở 16 trên 19 đêm đáo hạn. Các nến
   đó góp −55,4 điểm lãi lỗ gộp đến từ việc đổi hợp đồng (mục 2.5), trên tổng +1.234,1 điểm net. Chỉ bật roll guard thì
   còn tệ hơn (19 trên 19 đêm, −100,7 điểm), vì luật ATC chép vị thế 14:00 sang nến 14:30, mà chân mua ngày đáo hạn của
   Calendar vẫn đang bật lúc 14:00. Với luật ensemble về 0 ngày đáo hạn, không vị thế nào vắt qua lúc đổi hợp đồng (0
   trên 19 đêm).
4. Nến DNSE có high và low không bao trùm open và close được `normalize_bars` sửa lại (high và low đặt bằng max và min
   của OHLC).
5. Plutus dựng lại biên độ giá cho 31 nến hợp đồng từ giá đóng quan sát gần nhất, vì thiếu biên độ công bố (`assumptions`
   trong report Plutus in-sample).
6. Nến chỉ số DNSE đối chiếu với tick VN30 trong cơ sở dữ liệu (`scripts/report_index_crosscheck.py`, 01/06/2021 đến
   01/10/2026). Nhiều nến chỉ số DNSE "phẳng" (Open = High = Low = Close, khối lượng gần 0): nến 11:00 ở 80% phiên năm
   2022 và 81% năm 2025, nến 09:00 ở 96% phiên năm 2026. Nến tương ứng trong cơ sở dữ liệu thì đầy đủ. Tuy vậy giá Close
   vẫn đúng: Close của DNSE trừ Close của cơ sở dữ liệu có trung vị tuyệt đối 0,21 điểm (2021), 0,13 (2022) và 0 từ 2023;
   98% số nến lệch dưới 1 điểm, không phiên nào có quá 4 nến lệch hơn 1 điểm. Basis chỉ dùng Close của chỉ số. Chạy
   Basis trên hợp đồng DNSE với chỉ số lấy từ cơ sở dữ liệu thay cho DNSE (lab, 1 hợp đồng):

   | Giai đoạn | Chỉ số DNSE | Chỉ số cơ sở dữ liệu | Vị thế giống nhau |
   |---|---|---|---:|
   | In-sample | +630,2 điểm, Sharpe 1,81 | +586,6 điểm, Sharpe 1,69 | 95,2% số nến |
   | OOS | +426,6, Sharpe 1,44 | +442,1, Sharpe 1,49 | 97,7% |
   | Forward | +412,3, Sharpe 2,01 | +412,3, Sharpe 2,01 | 100% |

   Khác biệt không nghiêng về một phía, nên nguồn chỉ số không đổi kết luận về Basis. Lab giữ chỉ số DNSE.

## 2.8 Quyết định trước khi chạy lại

- In-sample bắt đầu từ 01/06/2021 ở cả hai engine.
- Phiên thiếu chỉ số: Basis đứng ngoài.
- Nhãn nến chỉ số DNSE: gắn lại theo khung 30 phút.
- Mã hợp đồng DNSE: suy ra từ lịch của sàn.
- Đổi hợp đồng: roll guard cho Basis, cộng luật ensemble về 0 ngày đáo hạn, ở cả hai engine. Giá DNSE giữ nguyên gốc.
