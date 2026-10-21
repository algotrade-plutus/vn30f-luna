# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

`AGENTS.md` holds the binding project rules (layer dependency rules, `.env` handling, DB query rules, evidence-first workflow). Read it; this file summarizes and adds what you need to navigate the code.

Research philosophy is binding (AGENTS.md §6): before backtesting any new hypothesis, write a `PROTOCOL.md` with the `algotrade-hypothesis` skill (source of alpha, falsifying predictions, trial budget, data ranges); judge finished branches with its verdict mode. Principles: `.claude/skills/algotrade-hypothesis/philosophy.md`.

## Commands

Python 3.12, managed with `uv`. `plutus/` is a git submodule installed as an editable dependency (`algotrade-plutus`).

```bash
make setup                 # git submodule update --init --recursive && uv sync --frozen
make test                  # ./scripts/run_owned_tests.sh  (uv run --python 3.12 pytest tests -q)
make lint                  # uv run ruff check .   (only E9/F63/F7/F82; plutus/ excluded)
make check                 # test + lint + compileall of src/scripts/tests

# Single test (extra args are passed through to pytest)
./scripts/run_owned_tests.sh tests/test_lab_backtest.py::test_name
# Without uv: PYTHON=/path/to/python ./scripts/run_owned_tests.sh   (sets PYTHONPATH=.:plutus/src)
```

Research pipelines:

```bash
make calibrum-insample | calibrum-oos | calibrum-forward   # Plutus exchange backtest (scripts/run_calibrum_plutus.py, needs DB)
make fetch-data && make step4 step5 step6                   # local lab engine on DNSE Parquet cache (data/dnse/)
uv run python scripts/run_step4_insample.py --source db     # lab engine on Postgres instead of DNSE
make plutus-report                                          # reports/*.json -> docs/PLUTUS_BACKTEST_REPORT.md
make ensemble-research
```

`papertrade/` (Step 7 live/paper runtime) has its own venv and test suite: `make papertrade-setup`, `make papertrade-test`.

## Architecture

**Signal source of truth: `PS_V30_Vien_Calibrum/`.** This is the frozen strategy package (`PS_V30_Vien_Calibrum.py`, `config.json`, `PS_V30_Vien_Calibrum_model.pt`, `native_verification.json`). It is written for an external `AlphaBase` runtime and is not imported normally. `src/adapters/strategies/calibrum_signal_source.py` loads it via `importlib` with a stubbed base class, calls only its sleeve functions (Ridge H2, Shinji basis mean-reversion, Calendar), and records SHA-256 hashes of the artifacts against `native_verification.json`. Do not edit the frozen package to change behaviour; changes belong in the adapter (e.g. front-month roll adjustment and roll guards live there).

**Ensemble:** the three sleeves each produce a position in {-1,0,+1}, combined by majority vote (`sign` of the sum; a "sum" variant is also reported). Signals are computed on the close of left-labelled 30-minute bar T and executed at bar T+1 (`pre_shift_positions`). At 14:30 (ATC) the position is frozen to the 14:00 state. Causality and no lookahead are core invariants that the tests check.

**Two backtest engines consume the same signal stream:**
- `src/lab/backtest/`: local, vectorized, point-based engine for fast iteration. The per-bar `Position` stream is the source of truth. The trade ledger is derived afterwards for diagnostics only. Fee is 0.8 pts round-trip (0.4 per unit change), Sharpe uses daily points × √252 with R_f=0. Entry points are `evaluate(stream, BacktestConfig)`, and shared CLI glue lives in `scripts/lab_common.py`.
- `src/adapters/backtesting/plutus_research_runner.py`: replays targets against the real Plutus `ExchangeSession` (HNX/VSDC). Plutus owns admission, fills, fees, PIT, variation margin, expiry and margin status. Results are in VND with Sharpe on % returns, √250 and R_f=3%. Its numbers will differ from the lab engine by design (see the README "Methodology Comparison").

**Clean Architecture layers in `src/`** (dependency rule in AGENTS.md):
- `domain/` may use only the stdlib. `tests/test_clean_architecture.py` enforces this in a subprocess that fails if pandas, numpy, psycopg2, socket and similar modules get loaded. `domain/strategy/calendar_rules.py` holds the VN trading calendar (`VN_CLOSED_DAYS`, expiry Thursdays, pre-holiday) used by both the strategy and the Plutus runner.
- `application/` defines ports (`ISignalGateway`, `IBrokerGateway`, market data, state store) and use cases (`TradingCycleUseCase`, `RiskMonitorUseCase`).
- `adapters/` holds data sources (Postgres tick/depth/research bars, `PlutusBarSource`, DNSE candles), the Plutus broker adapter, the Plutus research runner, and the Calibrum signal adapter.
- `infrastructure/` contains the psycopg2 pool, env config (`os.getenv`, `.env`), and Plutus result serialization.
- `src/lab/` sits outside the 4 layers. It is research tooling and may use pandas/matplotlib.

Scripts import from the repo root as `src.…` (pytest sets `pythonpath = ["."]`, and scripts insert the workspace root into `sys.path`).

## Data

- Postgres `algotradeDB` (read-only) via `ALGOTRADE_DB_*` in `.env` (template: `.env.example`). Always bound queries with `WHERE datetime >= … AND datetime <= …` to hit the `(datetime, tickersymbol)` index.
- The DB exposes a raw front-month contract, not Calibrum's adjusted continuous series. DNSE candles are a public continuous approximation. Expect small discrepancies between sources.
- Generated outputs go to `reports/*.json`, `reports/figures/`, and `image/README/` (README plots via `scripts/generate_*_plots.py`).
- Reproducibility: `.plutus/` holds Plutus run artifacts. `plutus check .` re-runs in Docker against a declared baseline when a manifest is present.

## Branches

`main` holds the stable, verified baseline. `refactor/clean-architecture` is for the 4-layer architecture work.
