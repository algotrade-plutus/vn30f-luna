# Calibrum packaging report

## Outcome

`PS_V30_Vien_Calibrum` is the standalone, single-file package of the frozen
Master Ensemble. The original Master folder was not modified.

Submission payload is exactly:

1. `PS_V30_Vien_Calibrum.py`
2. `config.json`
3. `PS_V30_Vien_Calibrum_model.pt`

Calibrum has no sibling-alpha imports, helper dependency or runtime training.
The small tensor-only checkpoint contains the frozen Ridge scaler/coefficients
and equal ensemble weights; it is loaded once in `__init__` via `working_path`.
`alpha_type` is `ml` because the Ridge sleeve contains trained coefficients.

## Exact parity

Compared with `PS_V30_Vien_Master_Ensemble` on native 2020–2022 data:

- rows: 7,509;
- Datetime parity: PASS;
- Close parity: PASS;
- Position mismatch: 0;
- maximum absolute Position difference: 0.

The ensemble operation is accurately described as
`sign(Ridge + Shinji + Calendar)`. Shinji deliberately retains the frozen
adjusted-futures/spot spread used by the Master; it was not silently changed to
raw futures basis.

## Native SDK verification

Executed in `evangelion-workspace-1` using the native SDK and `fee=0.4`:

| Metric | Result |
|---|---:|
| Net after fee | +2,056.5 points |
| Gross profit | +2,428.9 points |
| Sharpe after fee | 3.22 |
| Margin after fee | 21.44 bps |
| Max drawdown | 103.3 points |
| Trades | 466 |
| Hit rate | 52.58% |
| Generate time | 0.36 seconds |

All required checks passed:

- Margin >=15 bps;
- Sharpe >=1.5;
- Trades >=180;
- Futures Leak PASS;
- Overfit PASS;
- generate <20 seconds;
- official `evangelion check` PASS;
- isolated three-file import and construction PASS.

Canonical machine evidence is in `native_verification.json`.

## Native notebook

`Calibrum_Backtest.ipynb` follows the Aphelios notebook contract: exact FIT
stream from `paperTrade.check_overfit()`, one full `CalibrumAlpha.generate()`,
then native-only `backtest(fee=0.4)`, `Get_metrics()` and `Plot_PNL()` for each
window. It does not implement a local PnL engine.

Docker execution completed all 8 code cells without errors:

| Window | Net points | Sharpe | Margin | Trades |
|---|---:|---:|---:|---:|
| OOS 2023–2024 | +851.9 | 2.51 | 11.93 bps | 308 |
| Forward 2025–24/09/2026 | +1,534.1 | 2.89 | 15.77 bps | 284 |
| Full cycle 10/08/2017–24/09/2026 | +5,002.1 | 2.68 | 16.02 bps | 1,400 |

These already-open windows are presentation/evaluation evidence, not fresh
holdouts for further tuning. The notebook is not a submission file.

## Remaining pre-submit actions

- Replace the password placeholder in `config.json` locally without logging it.
- After that edit, start a fresh process and rerun `verify_calibrum.py` plus
  `evangelion check`; the current config hash will intentionally change.
- Submit as a new alpha, not update/overwrite Master Ensemble.

No remote submit, update or overwrite was performed in this packaging step.

## Final pre-submit audit after `Auto`

The final config uses `time_to_start=["Auto"]`. Re-running every local check
after this config change produced identical signals and metrics:

- config/name/source/class and all required fields: PASS;
- supported 30m feeds, 1,000 bars each: PASS;
- `alpha_type=ml`: PASS;
- model prefix, tensor-only payload and `working_path` loading: PASS;
- no sibling-alpha import and no runtime fit call: PASS;
- exact three-file manifest and isolated package construction: PASS;
- exact Master parity, native metrics, Futures Leak and Overfit: PASS;
- official `evangelion check`: PASS;
- local `evangelion live` stage/import/generate: PASS;
- local `evangelion fullbacktest` stage/import/generate: PASS;
- executed notebook: 8/8 code cells, no errors.

The only concrete submission blocker is the password placeholder in
`config.json`. Replace it privately, then run the verifier and official check in
a fresh process because the config hash changes. Global name uniqueness and
server acceptance can only be confirmed by the actual submit response.

## Known limitation

Calibrum now uses `time_to_start=["Auto"]`. Historical exact parity and vendor
gates do not prove how production expands that schedule or whether its current
30-minute row is complete. This remains a production trace question and must
not be advertised as resolved by the checker.
