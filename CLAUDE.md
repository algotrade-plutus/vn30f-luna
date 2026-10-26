# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

`AGENTS.md` holds the binding project rules (layer dependency rules, secrets, evidence-first workflow). Read it; this file summarizes and adds what you need to navigate the code.

Research philosophy is binding (AGENTS.md §6): before backtesting any new hypothesis, write a `PROTOCOL.md` with the `algotrade-hypothesis` skill (source of alpha, falsifying predictions, trial budget, data ranges); judge finished branches with its verdict mode. Principles: `.claude/skills/algotrade-hypothesis/philosophy.md`.

## Commands

Python 3.12, managed with `uv`. Plutus (`algotrade-plutus`) is installed from GitHub at the commit pinned in `pyproject.toml` (read-only; no submodule).

```bash
make setup                 # uv sync --frozen
make fetch-data            # DNSE 1-minute and 5-minute VN30F1M and VN30 bars into data/dnse/
make step5 && make step4   # in-sample: Ridge CV, Momentum threshold, Basis grid; then the 7-combination baseline
make step6                 # valid chooses the final combination, then OOS 1 and OOS 2 (each opens once)
make paper                 # step 7: Luna paper results recomputed from research/paper-trading/luna_fills.csv
make figures               # buy-and-hold benchmarks and the equity charts
make week START=2026-08-10 END=2026-08-14   # one-week chart of sleeve and vote positions
make test                  # ./scripts/run_owned_tests.sh  (uv run --python 3.12 pytest tests -q)
make lint                  # uv run ruff check .   (only E9/F63/F7/F82)
make check                 # test + lint + compileall of src/scripts/tests
plutus check .             # plutus-verify: rebuild in Docker, rerun steps 2/5/4/6/7, compare with .plutus/manifest.yaml

# Single test (extra args are passed through to pytest)
./scripts/run_owned_tests.sh tests/test_calibrum_1m.py::test_name
```

`papertrade/` is the Step 7 paper runtime (`papertrade/calibrum/`: DNSE feed, live targets from `src/lab/calibrum_1m/live.py`, execution, broker), run by systemd on the AWS EC2. `make papertrade-test`, `make papertrade-deploy`, `make papertrade-status`; see `papertrade/README.md` and `papertrade/docs/REBUILD_NOTES.md`.

## Architecture

**Data.** `src/adapters/data/dnse_minute_bars.py` builds the research base from cached DNSE 1-minute bars, filling sessions DNSE lacks at 1 minute with its 5-minute bars (never forward-filled), adds the front-month contract code, and aggregates to 10-minute bars (Calendar MTW convention) and 30-minute bars (Basis, Momentum). Momentum features use an additive roll-adjusted copy (`roll_adjust_front_month`); everything else uses raw prices. Periods and costs live in `config/research.toml`.

**Sleeves** (`src/lab/calibrum_1m/`):
- Calendar MTW (`src/adapters/strategies/calendar_mtw_signal_source.py`): Monday short below the first-30-minute low, Tuesday–Wednesday long from Monday 14:20 to Thursday 10:00. Parameters come from the separate calendar-mtw-vn30f research.
- Basis (`basis.py`): z-score of futures minus VN30 over W 30-minute bars, restarted each contract.
- Momentum (`momentum.py`): Ridge regression on five ATR-scaled features (median/IQR scaling frozen on in-sample), target = 2-bar forward move / ATR14; trades when |score| ≥ θ.
- Combination: vote, `sign(C + B + M)`, one contract on 100 million VND.

**Engine.** `pipeline.py` places each decision on the minute grid at the close of its signal bar (`grid.py`), checks stops at every minute close, flattens on expiry sessions and on the last row of each contract, and scores with `src/lab/backtest` (0.4 points per side). Sharpe, Sortino, information ratio (against VN30F1M buy and hold), max and longest drawdown come from `plutus.evaluation.metrics` (√250, 3% risk-free rate and Sortino threshold, returns on account equity); the dated initial margin ratio from `plutus.market.margin`. Causality is a core invariant the tests check.

**Stages.** `scripts/run_calibrum_1m.py <stage>` runs one protocol step and loads data only up to the last day that step may see; outputs go to `reports/calibrum_1m/`. The `oos1` and `oos2` stages refuse to run out of order, and to run twice unless given `--rerun` (recomputes with the saved choices, for reporting).

**Clean Architecture layers in `src/`** (dependency rule in AGENTS.md): `domain/` may use only the stdlib (enforced by `tests/test_clean_architecture.py`); `application/` holds ports and use cases for the runtime; `adapters/` holds data, sleeve and broker adapters; `src/lab/` sits outside the layers and may use pandas.

Scripts import from the repo root as `src.…` (pytest sets `pythonpath = ["."]`, and scripts insert the workspace root into `sys.path`).

## Research record

`research/calibrum-1m/PROTOCOL.md` was locked before any run (section 9 records every amendment); `RESULTS.md` holds the in-sample, valid and out-of-sample tables. Report money in million VND, not index points.

## Branches

`main` holds the stable, verified baseline; work happens on feature branches.
