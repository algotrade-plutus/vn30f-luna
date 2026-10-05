# PS_V30_Vien_Calibrum

Calibrum là bản standalone, single-file của `PS_V30_Vien_Master_Ensemble`:
Ridge H2 + Shinji + Calendar, kết hợp bằng `sign(ridge + shinji + calendar)`.

## Submission package

Chỉ nộp ba file:

- `PS_V30_Vien_Calibrum.py`
- `config.json`
- `PS_V30_Vien_Calibrum_model.pt`

Checkpoint `.pt` chỉ chứa tensor frozen của Ridge scaler/coefficients và ba
ensemble weights; được load một lần trong `__init__` qua `working_path`.

`verify_calibrum.py`, `native_verification.json` và README chỉ là bằng chứng
local, không thuộc submission package.

Notebook [`Calibrum_Backtest.ipynb`](Calibrum_Backtest.ipynb) dùng exact FIT
stream và các hàm native `backtest()`, `Get_metrics()`, `Plot_PNL()` để trình bày
OOS, forward và full cycle. Notebook cũng không thuộc submission package.

Notebook đã execute 8/8 code cells trong Docker, không có error:

- OOS 2023–2024: +851,9 điểm, Sharpe 2,51, Margin 11,93 bps.
- Forward 2025–24/09/2026: +1.534,1 điểm, Sharpe 2,89, Margin 15,77 bps.
- Full cycle 10/08/2017–24/09/2026: +5.002,1 điểm, Sharpe 2,68,
  Margin 16,02 bps.

`submit_calibrum.py` là runner local, không thuộc submission manifest. Chạy
`check` trước; chỉ action `submit`/`update` mới thay đổi remote.

## Quy trình xác minh

Chạy trong Docker Native SDK:

```bash
docker exec evangelion-workspace-1 bash -lc \
  'python alphas/PS_V30_Vien_Calibrum/verify_calibrum.py'
```

Verifier yêu cầu exact output parity với Master gốc, native backtest fee 0.4,
runtime dưới 20 giây, Margin/Sharpe/Trades gate, Futures Leak và Overfit PASS.

Kết quả native 2020–2022 đã xác minh:

- Exact Master parity: 0 position mismatch trên 7.509 rows.
- Net after fee: +2.056,5 điểm.
- Sharpe after fee: 3,22.
- Margin after fee: 21,44 bps.
- Trades: 466.
- Generate: khoảng 0,46 giây.
- Futures Leak và Overfit: PASS.

## Timing caveat

`time_to_start=["Auto"]` giao lịch gọi cho Master theo timeframe, nhưng exact
historical parity và vendor gates không chứng minh snapshot production chứa nến
30m hoàn chỉnh. Scheduler expansion và partial-bar payload vẫn là live-parity
risk cần production trace, không được mô tả thành bằng chứng live.
