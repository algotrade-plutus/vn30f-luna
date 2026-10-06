# Backtest local

Package này là đường chấm điểm chuẩn cho research. Nó chạy trực tiếp bằng
Pandas/Matplotlib trên máy, hoàn toàn độc lập và không phụ thuộc runtime bên ngoài.

## Luồng dữ liệu

```text
OHLCV + model forecast
        ↓
execution policy → Position theo từng bar (-1/0/+1)
        ↓
validate_position_stream
        ↓
bar accounting → daily/weekly/monthly → metrics → diagnostic trade ledger
```

`Position` là nguồn sự thật. Trade ledger chỉ được suy ra sau backtest để chẩn
đoán; không dùng một bảng trade rời rạc làm nguồn PnL hoặc chọn candidate.

## Công thức chuẩn

- `ExecutedPosition[t] = Position[t-1]`
- `GrossGain[t] = ExecutedPosition[t] * (Close[t] - Close[t-1])`
- `FeeCost[t] = abs(Position[t] - Position[t-1]) * 0.4`
- `NetGain = GrossGain - FeeCost`
- `Sharpe = mean(daily point PnL) / std(daily point PnL, ddof=1) * sqrt(252)`
- `Margin = total points / sum(Close * abs(change in Position)) * 10,000`

Fee mặc định là `0.8` điểm cho một round trip, tương đương `0.4` điểm trên mỗi
đơn vị thay đổi position. Mọi phiên thị trường đều đi vào Sharpe, kể cả phiên có
PnL bằng 0.

## API chính

```python
import pandas as pd
from lab.backtest import evaluate

stream = pd.read_parquet("positions.parquet")
result = evaluate(stream[["Datetime", "Close", "Position"]])

print(result.metrics.as_dict())
result.plot_pnl().savefig("equity.png", dpi=160, bbox_inches="tight")
```

Để chạy từ terminal:

```bash
PYTHONPATH=. python -m lab.backtest.cli positions.parquet \
  --plot artifacts/equity.png \
  --json artifacts/metrics.json
```

Position phân số bị từ chối mặc định. Code legacy có thể chủ động bật
`BacktestConfig(require_discrete_position=False)`, nhưng alpha hiện tại chỉ dùng
`-1/0/+1`.

## Vận hành thuần local

Research, calibration, backtest, metric và plot đều chạy trực tiếp trên máy
local, phục vụ toàn bộ chu trình phát triển alpha.
