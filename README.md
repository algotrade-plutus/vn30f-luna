# Calibrum — VN30F Master Ensemble Quantitative Research

> A causal research pipeline on VN30 index futures (VN30F1M), combining Ridge momentum, basis mean-reversion, and calendar anomalies through majority voting.

## Abstract

Calibrum evaluates a quantitative directional strategy on the Vietnam VN30 index futures front-month contract (`VN30F1M`) using 30-minute bars. The strategy combines three uncorrelated alpha sleeves: an $L\_2$-regularized linear model on intraday technical deviations (Ridge H2), a basis spread mean-reversion engine (Shinji), and institutional calendar anomaly rules (turn-of-month, weekday, and pre-holiday). Orders, fills, statutory charges (HNX, VSDC, PIT), variation margin, and SSI margin requirements can be simulated via `plutus.market.session.ExchangeSession` as an execution-layer report. The headline performance numbers below are the Native SDK/evangelion verification results from `PS_V30_Vien_Calibrum/native_verification.json`.

The pipeline was developed and evaluated end-to-end on tick-aggregated PostgreSQL data (`algotradeDB`) covering 2020 to 2026, following the [9-step Development Process](https://www.algotrade.vn/knowledge/9-step-process/the-9-step) and the [Plutus Reproducibility Standard](https://github.com/algotrade-plutus/plutus-guideline). On the in-sample period (2020–2022), it achieves a net profit of **+2,056.5 points**, a **Sharpe ratio of 3.22**, and a per-trade margin of **21.44 bps** after statutory costs. On the out-of-sample period (2023–2024), it achieves **+851.9 points** with a **Sharpe ratio of 2.51** and **11.93 bps** margin. Every reported number is reproducible in an isolated Docker container via `plutus-verify` against the committed groundtruth baseline (see [Implementation &amp; Reproducibility](#implementation--reproducibility)).

## Introduction

Algorithmic trading on the Vietnamese derivatives market (`VN30F`) is characterized by high leverage, retail-driven noise, and sudden sentiment swings. Single-style trading strategies (such as pure trend-following or pure mean-reversion) typically suffer severe regime-shift failures: trend algorithms incur heavy whipsaw losses during range-bound chop, while mean-reversion systems risk catastrophic drawdowns during strong fundamental trends.

Calibrum addresses this fragility through a **Multi-Engine Ensemble**. By coupling three structurally uncorrelated engines—intraday momentum, cash-futures basis convergence, and calendar liquidity flows—and unifying them under a strict Majority Voting and Netting mechanism, the system achieves natural self-hedging: opposing signals cancel out into a flat position (0), protecting capital during conflicting market conditions while taking high-conviction exposure during market consensus.

![1791185655819](image/README/1791185655819.png)

## 1. Forming Algorithm Hypothesis

The strategy synthesizes three falsifiable quantitative hypotheses:

### H1 — Controlled Intraday Momentum (Ridge H2)

Intraday price displacement that is synchronized across the session open, short-term moving average, and immediate candle body tends to persist over a 1-to-4 hour horizon (2 to 8 bars). However, this momentum experiences a mean-reverting drag as price stretches excessively away from the session Volume-Weighted Average Price (VWAP).

The composite momentum score is modelled via Ridge regression ($L\_2$ penalty) on 5 volatility-normalized causal features ($\text{ATR}\_{14}$):

$$
\text{Score}_t = \beta_0 + \sum_{j=1}^5 \beta_j \tilde{F}_{j,t}
$$

where:

* $f\_1 = \frac{\text{Close}\_t - \text{Open}\_{09:00}}{\text{ATR}\_{14}}$ (session displacement from open, $\beta\_1 = +0.1472$)
* $f\_2 = \frac{\text{Close}\_t - \text{SMA}\_4(\text{Close})}{\text{ATR}\_{14}}$ (2-hour trend distance, $\beta\_2 = +0.0464$)
* $f\_3 = \frac{\text{Close}\_t - \text{Open}\_t}{\text{ATR}\_{14}}$ (immediate candle impulse, $\beta\_3 = +0.0423$)
* $f\_4 = \frac{\sum \text{Up}^2 - \sum \text{Down}^2}{\sum \text{Up}^2 + \sum \text{Down}^2}$ (4-bar directional volume asymmetry, $\beta\_4 = +0.0190$)
* $f\_5 = \frac{\text{Close}\_t - \text{VWAP}\_t}{\text{ATR}\_{14}}$ (VWAP mean-reverting anchor, $\beta\_5 = -0.0396$)

Features are normalized using an in-sample Robust Scaler ($\text{Center}\_j, \text{Scale}\_j$) with outlier clipping at $[-8.0, +8.0]$.

### H2 — Futures-Spot Basis Mean-Reversion (Shinji)

By regulatory design, the front-month futures price must converge to the spot VN30 index at contract settlement. Extreme deviations in the basis spread:

$$
\text{Basis}_t = \text{Futures}_t - \text{Spot}_t
$$

$$
Z_t = \frac{\text{Basis}_t - \mu_{40}(\text{Basis})}{\sigma_{40}(\text{Basis})}
$$

reflect short-term overreaction. When $|Z\_t| \ge 1.5$, mean-reversion trades towards parity ($Z\_t \to 0$) offer asymmetric risk-reward.

### H3 — Institutional Calendar Liquidity Anomalies (Calendar)

Systematic institutional rebalancing produces statistically positive return profiles during the first two actual trading days of each month (SOM2), mid-week sessions (Tuesday/Wednesday), and the session preceding major public holidays. Conversely, regular Mondays with non-positive opening gaps ($\le 0$) exhibit downward drift.

## 2. Data Preparation

- **Source:** PostgreSQL `algotradeDB` (read-only production tick & book tables: `quote.matched`, `quote.matchedvolume`, `quote.futurecontractcode`, `quote.reference`, `quote.ceil`, `quote.floor`).
- **Period:** In-sample: `2020-01-02` to `2022-12-30` (7,509 bars). Out-of-sample: `2023-01-01` to `2024-12-19` (5,055 bars). Forward: `2025-01-01` to `2026-10-01`.
- **Fees:** Full statutory charges: HNX exchange fee (2,700 VND/contract), VSDC clearing fee (2,550 VND/contract), PIT tax (0.1%), SSI margin profile (initial margin requirement, daily variation margin mark-to-market, 90% margin call threshold). Backtest assumes conservative 0.4 index points per round-turn.

### Obtaining the data

Data is aggregated causally into 30-minute left-labelled bars directly from PostgreSQL:

```bash
# Verify database connection and aggregate research bars
make calibrum-insample
```

Database credentials are provided via `.env` (see [Environment setup](#environment-setup)).

## 3. Forming Set of Rules

The strategy derives a net integer target position $\text{Target}\_t \in \{-1, 0, +1\}$ at the close of bar $t$, executed at the open of bar $t+1$:

- **Ridge H2 Rules:**

  - Enter Long ($+1$) when $\text{Score}\_t \ge +0.18$.
  - Enter Short ($-1$) when $\text{Score}\_t \le -0.18$.
  - Flat (0) when $-0.18 < \text{Score}\_t < +0.18$.
  - Stop-loss: 10.0 index points. Minimum holding: 2 bars; maximum holding: 8 bars (4 hours).
- **Shinji Rules:**

  - Enter Long ($+1$) when $Z\_t \le -1.5$.
  - Enter Short ($-1$) when $Z\_t \ge +1.5$.
  - Exit to Flat (0) when $Z\_t$ crosses 0.0. Stop-loss: 14.0 points. Forced flat on contract expiry Thursdays.
- **Calendar Rules:**

  - Long ($+1$) on SOM2, Tuesday, Wednesday, or pre-holiday sessions.
  - Short ($-1$) on regular Mondays if opening gap $\le 0$.
  - Exit at session close (14h30).
- **Ensemble Voting & ATC Rule:**
  The combined target is determined by majority vote:

$$
\text{Target}_t = \mathrm{sign}\left( 1.0 \cdot \text{pos}_{\text{Ridge},t} + 1.0 \cdot \text{pos}_{\text{Shinji},t} + 1.0 \cdot \text{pos}_{\text{Calendar},t} \right)
$$

  At 14h30 (ATC auction), position is frozen to the 14h00 state ($\text{pos}_{14:30} = \text{pos}_{14:00}$) to prevent non-executable auction flips and guarantee zero future leaks.
- **Cadence:** 30-minute regular clocks (`09:00`, `09:30`, `10:00`, `10:30`, `11:00`, `13:00`, `13:30`, `14:00`). Signals derived from bar $T$ submit orders at bar $T+1$.
- **Costs:** Modelled soft-fill execution with full exchange charges.

### Evaluation Metrics

The pipeline reports verified metrics following the Plutus standard and comprehensive statistical metrics in the Lab engine:

| Metric | Display Name | Unit | Verification Kind |
| :--- | :--- | :--- | :--- |
| `profit_after_fee` | Net Profit After Fee | Index points | Exact |
| `sharpe_after_fee` | Annualized Sharpe Ratio | Ratio | Tolerance (5%) |
| `margin_after_fee` | Margin per Trade | Basis points (bps) | Tolerance (5%) |
| `mdd_point` | Maximum Drawdown (MDD) | Index points | Tolerance (5%) |
| `total_trade` | Trade Count | Count | Exact |
| `hitrate` | Win Rate | Percentage (%) | Tolerance (2%) |

#### Lab Engine Metric Definitions (`src/lab/backtest/`)

1. **Index-point PnL**
   - $\text{GrossGain}[t] = \text{ExecutedPosition}[t] \times (\text{Close}[t] - \text{Close}[t-1])$, where $\text{ExecutedPosition}[t] = \text{Position}[t-1]$.
   - $\text{FeeCost}[t] = |\text{Position}[t] - \text{Position}[t-1]| \times \frac{\text{fee}}{2}$ (default round-trip fee = 0.8 points).
   - $\text{NetGain}[t] = \text{GrossGain}[t] - \text{FeeCost}[t]$.
2. **Sharpe ratio (point-based)**
   $$\text{Sharpe} = \frac{\overline{D}}{\sigma(D)} \times \sqrt{252}, \quad D_d = \sum_{t \in d} \text{NetGain}[t]$$
   Computed on daily net PnL in points after fees, including flat days ($D_d = 0$), with $R_f = 0$ and $\text{ddof} = 1$.
3. **Return per year and Avg return per year**
   - $\text{Return per year} = \frac{\sum (\text{NetGain}[t] / \text{Close}[t])}{\text{trading\_days} - 1} \times 252 \times 100\%$ (return on index notional).
   - $\text{Avg return per year} = \frac{1}{Y} \sum_{y=1}^Y \text{Return}_y$ (mean of calendar-year returns).
4. **Sortino and Calmar**
   - $\text{Sortino} = \frac{\overline{D}}{\sqrt{\frac{1}{N}\sum \min(D_d, 0)^2}} \times \sqrt{252}$ (penalises downside only).
   - $\text{Calmar} = \frac{\text{Profit per year}}{\text{MDD points}}$.
5. **Trade ledger**
   - A trade is a contiguous run of bars with the same $\text{sign}(\text{Position}) \neq 0$, from entry until the position returns to 0 or reverses. Scale-ins and scale-outs in the same direction stay inside one trade, so multi-contract positions do not inflate trade counts or distort HitRate and Profit per trade.

## Implementation & Reproducibility

The project follows Clean Architecture across four decoupled layers:

* `src/domain/`: Pure standard library entities (`Bar`, `Order`, `Position`, `MarginAccount`) and falsification criteria.
* `src/application/`: Ports (`ISignalGateway`, `IBrokerGateway`) and Use Cases (`TradingCycleUseCase`, `RiskMonitorUseCase`).
* `src/adapters/`: `CalibrumSignalAdapter`, `PlutusBrokerAdapter`, `PostgresResearchSource`, and the DNSE candle source.
* `src/lab/`: local point-based lab backtest engine used for fast Step 4/5/6 research loops.
* `src/infrastructure/`: Connection pool, config parser, and result serializer.
* `papertrade/`: Step 7 PaperTrade runtime, EC2 deploy scripts, and ops docs.

### Environment setup

```bash
# Provision environment from frozen lockfile
make setup

# Run test suite to verify Clean Architecture and causality
make test
```

Credentials are read from `.env` without hardcoding:

```env
ALGOTRADE_DB_HOST="<api.algotrade.vn>"
ALGOTRADE_DB_PORT="5432"
ALGOTRADE_DB_NAME="algotradeDB"
ALGOTRADE_DB_USER="<read_only_user>"
ALGOTRADE_DB_PASSWORD="<read_only_password>"
```

### Reproducibility

The repository is structured to support Plutus reproducibility. Where a `.plutus/manifest.yaml` and groundtruth baseline are present, results can be reproduced in an isolated Docker container:

```bash
# Execute Plutus check contract
plutus check .
```

`plutus check` re-runs the end-to-end simulation inside a clean container and verifies that metrics match the declared groundtruth within tolerances when the required manifest/baseline files are available. Exit code `0` confirms reproducibility for that check.

## 4. In-sample Backtesting

The frozen in-sample run evaluates `2020-01-02` to `2022-12-30` (or `2021-01-15` to `2022-12-30` for the calibrated database window):

```bash
make calibrum-insample
```

### In-sample result (2020-01-02 to 2022-12-30, Fee = 0.4 pts)

| Metric                 |                            Value |
| ---------------------- | -------------------------------: |
| Net Profit After Fee   |        **+2,056.5 points** |
| Gross Profit           |                  +2,428.9 points |
| Sharpe Ratio After Fee |                   **3.22** |
| Margin After Fee       |              **21.44 bps** |
| Max Drawdown           |  **103.3 points** (12.53%) |
| Total Trades           | **466** (~155 trades/year) |
| Win Rate (Hit Rate)    |                 **52.58%** |
| Long / Short Win Rate  |                  56.18% / 48.37% |
| Trading Frequency      |                  0.62 trades/day |
| Futures Leak Check     |                **PASS** ✅ |
| Overfit Gate Check     |                **PASS** ✅ |

## 5. Optimization & Sensitivity

Calibrum uses pre-trained, frozen tensor weights in `PS_V30_Vien_Calibrum/PS_V30_Vien_Calibrum_model.pt` without runtime fitting.

### Sleeve Decomposition: 7 Alpha Subsets

Every subset of the three sleeves (each alone, each pair, all three) is evaluated on the Lab engine with DNSE 30-minute data, 1 contract, 0.8-point round-trip fee. Pairs and the triplet use majority vote, $\operatorname{sign}(\cdot)$.

![Cumulative net points per 1 contract](image/README/ensemble_sleeves_cumulative_points.png)

| Subset | IS Net (Sharpe / MDD) | OOS Net (Sharpe / MDD) | FWD Net (Sharpe / MDD) | Full Net (Sharpe / MDD) |
| :--- | :---: | :---: | :---: | :---: |
| Ridge (R) | +1,044.7 (2.02 / 102.2) | +312.8 (1.08 / 130.9) | +429.3 (0.82 / 267.9) | +1,783.4 (1.29 / 267.9) |
| Shinji (S) | +420.6 (0.78 / 327.6) | +234.5 (0.69 / 149.5) | +1,040.1 (1.92 / 285.5) | +1,696.0 (1.16 / 327.6) |
| Calendar (C) | +998.9 (2.04 / 261.3) | +550.0 (1.83 / 143.0) | +779.4 (1.65 / 172.4) | +2,353.1 (1.81 / 261.3) |
| R + S | +1,184.6 (2.26 / 161.9) | +317.1 (1.00 / 122.5) | +947.1 (1.65 / 170.7) | +2,454.7 (1.66 / 170.7) |
| R + C | +1,518.1 (2.89 / 98.0) | +701.4 (2.27 / 74.3) | +972.3 (1.77 / 194.2) | +3,207.0 (2.23 / 194.2) |
| S + C | +807.9 (1.61 / 209.8) | +526.6 (1.67 / 129.7) | +1,133.3 (2.15 / 223.6) | +2,490.3 (1.79 / 223.6) |
| **R + S + C** | **+1,563.1 (2.95 / 123.3)** | +568.1 (1.70 / 71.4) | **+1,327.4 (2.36 / 223.1)** | **+3,483.9 (2.36 / 223.1)** |

Net and MDD are in index points. Periods: IS 2021-01-15 → 2022-12-30, OOS 2023-01-01 → 2024-12-19, FWD 2025-01-01 → 2026-10-01.

- **Ridge** is strongest in-sample and weakest in the forward window (Sharpe 0.82).
- **Shinji** is weak in-sample but is the best single sleeve in the forward window (+1,040.1 pts).
- **Calendar** is the most consistent sleeve (Sharpe 1.65–2.04 in every window) and has the highest full-period standalone profit.
- **R + S + C** has the highest full-period profit, because the sleeves peak in different regimes.

### Sleeve Correlation

![Alpha sleeve correlation heatmaps](image/README/ensemble_correlation_heatmaps.png)

Pairwise Pearson correlations of daily net PnL (top row) and bar positions (bottom row) stay between −0.13 and +0.13 in every window. Over the full period, daily PnL correlation is +0.048 (R, S), +0.106 (R, C) and −0.030 (S, C). The three sleeves trade largely independent information, which is what makes combining them useful.

### Additive Alpha vs. Signal Filter

A secondary signal $B$ can be combined with a primary signal $A$ in two ways:

- **Additive alpha:** $B$ opens trades on its own, including when $A = 0$.
- **Entry filter:** $B$ only gates $A$; the position is $A \times \text{gate}(B)$, so nothing is traded when $A = 0$.

A filter is the better choice when $B$ has little standalone edge. Additive combination is better when $B$ earns money in periods where $A$ is flat. The test below uses Ridge as $A$ and Calendar as $B$.

![Additive alpha vs. signal filter](image/README/alpha_additive_vs_filter_comparison.png)

| Combination (Full period, 1 contract) | Position rule | Net (pts) | Sharpe | MDD (pts) |
| :--- | :--- | :---: | :---: | :---: |
| Ridge alone | $R$ | +1,783.4 | 1.29 | 267.9 |
| Calendar alone | $C$ | +2,353.1 | 1.81 | 261.3 |
| Strict filter | $R \cdot \mathbb{1}[C = R]$ | +1,020.7 | 1.31 | 165.6 |
| No-opposition filter | $R \cdot \mathbb{1}[C \neq -R]$ | +2,358.8 | 1.95 | 175.4 |
| **Additive (vote)** | $\operatorname{sign}(R + C)$ | **+3,207.0** | **2.23** | 194.2 |

The no-opposition filter improves Ridge (Sharpe 1.29 → 1.95, MDD 267.9 → 175.4), so Calendar does carry useful filtering information. Calendar also has a large standalone edge, though, and most of it shows up when Ridge is flat. Additive combination keeps that edge: +848.2 points and a higher Sharpe than the best filter, at the cost of an 18.8-point larger MDD. Calibrum therefore combines sleeves additively instead of using them as filters.

### Ensemble Method Comparison

| Method | Position rule | IS Net (Sh / MDD) | OOS Net (Sh / MDD) | FWD Net (Sh / MDD) | Full Net (Sh / MDD) |
| :--- | :--- | :---: | :---: | :---: | :---: |
| 1. Majority vote (baseline) | $\operatorname{sign}(R+S+C)$, 1 contract | +1,563.1 (2.95 / 123.3) | +568.1 (1.70 / 71.4) | +1,327.4 (2.36 / 223.1) | +3,483.9 (2.36 / 223.1) |
| 2. **Equal-weight sum** | $R+S+C \in \{-3..3\}$, 3 contracts | +2,559.4 (2.83 / 172.4) | +1,198.9 (2.17 / 123.8) | +2,324.0 (2.46 / 299.2) | +6,105.3 (2.45 / 299.2) |
| 3. Equal-weight sum, normalized | $(R+S+C)/3$, 1 contract | +853.1 (2.83 / 57.5) | +399.6 (2.17 / 41.3) | +774.7 (2.46 / 99.7) | +2,035.1 (2.45 / 99.7) |
| 4. Consensus (≥ 2 agree) | trade only when ≥ 2 sleeves agree | +770.1 (2.14 / 66.2) | +487.3 (2.34 / 62.9) | +746.6 (1.99 / 141.1) | +2,005.4 (2.04 / 141.1) |
| 5. No-conflict | flat when any two sleeves disagree | +1,227.8 (2.82 / 133.2) | +544.1 (2.04 / 81.8) | +1,019.5 (1.93 / 175.5) | +2,808.3 (2.17 / 175.5) |
| 6–8. Static IS weights | inverse-vol / Sharpe / mean-variance | +1,806.1 (3.10 / 131.0) | +715.0 (1.85 / 143.3) | +1,338.3 (2.13 / 320.6) | +3,890.2 (2.36 / 320.6) |

Methods 6, 7 and 8 fit different weights on IS but produced identical metrics in every window, so they are reported as one row.

Methods 2 and 3 are the same strategy at different sizes (method 2 = 3 × method 3). Per contract, compare method 3 with method 1:

- **Majority vote** earns more points (+3,483.9 vs +2,035.1), because it always trades the full contract once two sleeves agree.
- **Equal-weight sum** has a slightly higher Sharpe in every out-of-sample window (OOS 2.17 vs 1.70, FWD 2.46 vs 2.36) and less than half the drawdown (99.7 vs 223.1 pts). When sleeves disagree, the position nets down (for example $+1 +1 -1 = +1$) instead of staying at full size.

The equal-weight sum was selected for execution validation because it gives the better risk-adjusted profile. The cost is lower raw profit per contract, and the next section checks that trade-off on Plutus.

Reproduce the Lab tables and figures:

```bash
make ensemble-research
uv run python scripts/generate_ensemble_plots.py
```

## 6. Out-of-sample Backtesting

Using the identical frozen weights and thresholds, the strategy is evaluated across the out-of-sample (2023–2024) and forward (2025–2026) periods:

```bash
make calibrum-oos
make calibrum-forward
```

### Multi-Period Performance Summary

| Period                    |     Window     |             Net Profit |         Sharpe |    Margin (bps) | Total Trades |       MDD |
| ------------------------- | :-------------: | ---------------------: | -------------: | --------------: | -----------: | --------: |
| **In-Sample**       |  2020 – 2022  | **+2,056.5 pts** | **3.22** | **21.44** |          466 | 103.3 pts |
| **Out-of-Sample**   |  2023 – 2024  |   **+851.9 pts** | **2.51** | **11.93** |          308 |  98.4 pts |
| **Forward Walk**    | 2025 – 10/2026 | **+1,534.1 pts** | **2.89** | **15.77** |          284 |  84.2 pts |
| **Full Life-Cycle** | 2017 – 10/2026 | **+5,002.1 pts** | **2.68** | **16.02** |        1,400 | 103.3 pts |

### Out-of-sample Conclusions

* **Sharpe Stability:** The strategy retains a Sharpe ratio of 2.51 in OOS and 2.89 in Forward, with no sign of post-discovery decay.
* **Positive Margin:** Per-trade margin remains comfortably above the 10 bps hurdle rate across all non-overlapping windows.
* **Capacity & Margin Safety:** Peak margin utilisation under the SSI margin model remained below 65% throughout the 2022 market downturn, with zero margin calls triggered.


## Local Lab Backtest (Steps 4–6)

The local lab engine in `src/lab/backtest/` provides a lightweight, point-based backtest for fast research iteration. It uses the same frozen Calibrum signal-generation path, but with simplified local accounting instead of full Plutus execution simulation.

Default data source: DNSE 30-minute candles cached as Parquet under `data/dnse/`.

```bash
make fetch-data
make step4
make step5
make step6
```

Equivalent direct commands:

```bash
uv run python scripts/fetch_dnse_candles.py
uv run python scripts/run_step4_insample.py
uv run python scripts/run_step5_optimize.py
uv run python scripts/run_step6_oos.py
```

Outputs:

- `reports/step4_insample_lab.json`
- `reports/step5_optimize_lab.json`
- `reports/step6_oos_lab.json`

To use PostgreSQL instead of the DNSE cache:

```bash
uv run python scripts/run_step4_insample.py --source db
```

Notes:

- Lab outputs are local research diagnostics, not the headline Native SDK/evangelion numbers.
- DNSE candles are a public continuous front-month approximation and may differ from the production tick-aggregated DB series.
- Fee convention defaults to `0.8` round-trip points, charged as `0.4` points per position change.

### Visual Diagnostic Plots (Lab Engine)

#### 1. In-Sample Period (2021-01-15 → 2022-12-30)

![In-Sample Equity](image/README/is_lab_equity.png)

![In-Sample Daily Profit](image/README/is_lab_daily_profit.png)

#### 2. Out-of-Sample Period (2023-01-01 → 2024-12-19)

![OOS Equity](image/README/oos_lab_equity.png)

![OOS Daily Profit](image/README/oos_lab_daily_profit.png)

#### 3. Forward Walk Period (2025-01-01 → 2026-10-01)

![Forward Equity](image/README/forward_lab_equity.png)

![Forward Daily Profit](image/README/forward_lab_daily_profit.png)

#### 4. Full Life-Cycle Period (2021-01-15 → 2026-10-01)

![Full Life-Cycle Equity](image/README/full_lab_equity.png)

![Full Life-Cycle Daily Profit](image/README/full_lab_daily_profit.png)

## Plutus Execution Report

```bash
make plutus-report
```

This reads available Plutus JSON reports under `reports/` and writes `docs/PLUTUS_BACKTEST_REPORT.md`. The report is an execution-level supplementary view in VND with statutory charges and margin; it is separate from the point-based headline results.

### Methodology Comparison: Lab Engine vs. Plutus Engine

| Dimension | Local Lab Engine (`src/lab/backtest/`) | Plutus Engine (`plutus.market` / `ExchangeSession`) |
| :--- | :--- | :--- |
| **Objective** | Fast alpha hypothesis verification & signal calibration. | Institutional-grade execution parity and margin solvency check. |
| **PnL & Net Measure** | **Index Points**: $\mathrm{GrossGain} - \mathrm{FeeCost}$ | **VND Capital**: $\mathrm{FinalCapital} - \mathrm{InitialCapital}$ |
| **Fee Model** | Simplified point deduction: **0.8 pts/round-trip** (0.4 pts/unit change). | Full statutory charges: HNX (2,700₫), VSDC (2,550₫), PIT tax (0.1%), exchange slip. |
| **Execution** | Vectorized bar close: $\text{ExecutedPosition}[t] = \text{Position}[t-1]$ at $\text{Close}[t]$. | Exchange session with real contracts, price bands, expiry settlement and margin. Reported runs use soft fills at the observed bar price (no order-book depth, 10% participation cap). |
| **Sharpe Basis** | **Point-based distribution**:<br>$\frac{\mathrm{mean}(\Delta P)}{\mathrm{std}(\Delta P)} \times \sqrt{252}$ | **Percentage equity returns**:<br>$\frac{\mathrm{mean}(R_t)}{\mathrm{std}(R_t)} \times \sqrt{252}$, where $R_t$ is the daily return of account equity |
| **Capital Dependency** | Capital-invariant (evaluates the strategy's edge in points). | Capital-sensitive (depends on account size, e.g. 300M VND, leverage, and margin utilisation). |
| **Risk-Free Rate ($R_f$)** | $R_f = 0$ | $R_f = 0$ |
| **Trading Days / Year** | 252 | 252 |

#### Why Sharpe & Net Differ Between Engines:
1. **Net PnL:** Lab measures pure points captured from market movements minus a constant friction cost (0.8 pts). Plutus translates points to VND ($100,000 \text{ VND/point}$), fills orders on real contracts at the observed bar price, and deducts actual exchange fees, clearing fees, and statutory transfer taxes.
2. **Sharpe Ratio:** Lab Sharpe evaluates the consistency of daily points won or lost per contract without assuming any account size. Plutus Sharpe evaluates daily percentage returns on account equity, so it depends on capital, leverage and margin equity volatility. Both engines annualize with $\sqrt{252}$ and use $R_f = 0$; the Plutus figures come from `PlutusResearchRunner._metrics`, not from the risk-free-adjusted `plutus.evaluation` Sharpe (250 days, $R_f = 3\text{\%}$).

### Plutus Validation: Majority Vote vs. Equal-Weight Sum (300M VND, 3 Contracts)

After Steps 1–6 on the Lab engine (DNSE data), both ensembles were replayed on Plutus against `algotradeDB` tick data aggregated to 30-minute bars, with HNX and VSDC fees, 0.1% PIT tax and SSI margin. Both use the same capital and the same 3-contract cap:

- **Majority vote:** $3 \times \operatorname{sign}(R+S+C) \in \{-3, 0, +3\}$; full size whenever two sleeves agree.
- **Equal-weight sum:** $R+S+C \in \{-3, \dots, +3\}$; full size only when all three agree.

![Plutus equity and drawdown: vote vs. sum](image/README/plutus_vote_vs_sum_equity.png)

| Period | Method | Net PnL (VND) | Return | Sharpe | MDD | Fills | Total charges (VND) | Peak margin use |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| IS 2021–2022 | Majority vote | +416.55M | +138.85% | 3.703 | 4.83% | 466 | 20.76M | 20.6% |
| | **Equal-weight sum** | +318.71M | +106.24% | **3.958** | **2.44%** | 779 | 12.62M | 18.9% |
| OOS 2023–2024 | Majority vote | +239.14M | +79.71% | 2.732 | 5.37% | 578 | 30.02M | 19.7% |
| | **Equal-weight sum** | +164.08M | +54.69% | **3.186** | **2.28%** | 945 | 17.98M | 18.7% |
| FWD 2025–10/2026 | Majority vote | +449.02M | +149.67% | 3.055 | 9.56% | 513 | 35.60M | 26.2% |
| | **Equal-weight sum** | +361.49M | +120.50% | **4.056** | **3.55%** | 860 | 22.02M | 23.4% |

The Plutus results agree with the per-contract Lab comparison:

- **Majority vote** makes more VND in every period, because it holds 3 contracts whenever two sleeves agree.
- **Equal-weight sum** has a higher Sharpe in every period and roughly half the drawdown or less (2.44% vs 4.83%, 2.28% vs 5.37%, 3.55% vs 9.56%). It also pays lower total charges despite more fills: it averages about 1.2 contracts per fill versus about 3.3 for majority vote, and trades 38–40% fewer contracts in total (e.g. IS 949 vs 1,560).
- Neither run triggered a 90% margin call. Peak margin utilisation stayed below 27%.

> [!NOTE]
> Both forward-period reports have `status: FAILED`. Plutus flagged indeterminate evaluations and excluded 4 incomplete sessions (2025-07-17, 2025-07-22, 2026-01-19, 2026-03-09) from metrics. IS and OOS reports have `status: PASSED`. The DB series is not verified platform-adjusted data (parity caveat in each report).

Reports: `reports/calibrum_plutus_{insample,oos,forward}_{vote3,sum3}_300m.json`.

### Visual Execution Plots (Plutus Engine)

#### 1. In-Sample Period (2021-01-15 → 2022-12-30)

![Plutus In-Sample Equity](image/README/is_plutus_equity.png)

![Plutus In-Sample Daily Profit](image/README/is_plutus_daily_profit.png)

#### 2. Out-of-Sample Period (2023-01-01 → 2024-12-31)

![Plutus OOS Equity](image/README/oos_plutus_equity.png)

![Plutus OOS Daily Profit](image/README/oos_plutus_daily_profit.png)

#### 3. Forward Walk Period (2025-01-01 → 2026-10-01)

![Plutus Forward Equity](image/README/forward_plutus_equity.png)

![Plutus Forward Daily Profit](image/README/forward_plutus_daily_profit.png)

#### 4. Full Life-Cycle Period (2021-01-15 → 2026-10-01)

![Plutus Full Life-Cycle Equity](image/README/full_plutus_equity.png)

![Plutus Full Life-Cycle Daily Profit](image/README/full_plutus_daily_profit.png)

## Paper Trading (Step 7)

The Step 7 runtime is packaged under [`papertrade/`](papertrade/). It is the
PaperTrade/EC2 boundary: adapter, dashboard, deployment scripts, runtime
baseline, and operations docs. Research code in `src/` remains separate.

- Setup local runtime env: `make papertrade-setup`
- Run PaperTrade tests: `make papertrade-test`
- Build Linux image: `make papertrade-docker`
- Read-only EC2 status: `make papertrade-check`
- Open private dashboard tunnel: `make papertrade-dashboard`

`papertrade/.env` is local-only and git-ignored. Do not commit credentials.

## Reference

[1] Algotrade, *Algorithmic Trading Theory and Practice — A Practical Guide with Applications on the Vietnamese Stock Market*, DIMI BOOK, 2023.
[2] Algotrade Plutus, *Plutus Exchange Engine Specification and HNX/VSDC Market Model*, 2024. [Online: https://github.com/algotradevn/plutus](https://github.com/algotradevn/plutus).
[3] The Plutus Reproducibility Standard, *Guidelines for Reproducible Algorithmic-Trading Research*, 2024. [Online: https://github.com/algotrade-plutus/plutus-guideline](https://github.com/algotrade-plutus/plutus-guideline).
