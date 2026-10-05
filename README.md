# Luna — VN30F Calendar and Momentum Research

> A causal research pipeline for the VN30 futures front-month contract, using
> calendar effects, a FOMO veto, and T+2 momentum fallback.

## Abstract

Luna researches a directional strategy for the Vietnam VN30 futures
front-month contract (`VN30F1M`). It reads tick, volume, contract-mapping and
published-band data from the read-only `algotradeDB` PostgreSQL database,
aggregates causal bars, and delegates orders, fills, statutory charges,
variation margin, expiry settlement, and margin safety to
`plutus.market.session.ExchangeSession`.

The strategy combines calendar signals with a FOMO gatekeeper and a momentum
fallback. Its purpose is to test whether these rules remain useful after
causal execution, trading charges, contract rolls, and margin constraints are
modelled. It is research and paper-trading infrastructure, not an investment
recommendation or proof of live-execution performance.

## 1. Research hypotheses

### H1 — Calendar effects

The first two *actual trading sessions* of a month (SOM2), Tuesday/Wednesday,
and the final session before an extended holiday may have a positive VN30F
return profile. Luna therefore targets a long position on qualifying calendar
sessions.

SOM2 is session-based, not calendar-day-based: weekends and named exchange
closures do not count. A Monday that belongs to SOM2 is not treated as a
regular Monday short.

### H2 — Monday gap short

On a regular Monday—neither SOM2 nor pre-holiday—a non-positive opening gap
relative to the prior session close can trigger a morning short. A positive
gap leaves the calendar sleeve flat.

### H3 — FOMO veto and momentum fallback

Luna avoids opening a calendar long after an overheated short-horizon rally.
The gatekeeper uses ATR-normalised distance from SMA120 together with 2-bar
and 5-bar log returns. When calendar rules are neutral, T+2 momentum supplies
the target position.

These are falsifiable hypotheses. A positive in-sample return alone is not
treated as evidence of production readiness.

## 2. Strategy rules and priority

| Component | Condition | Target | Priority |
|---|---|---:|---:|
| Calendar long | SOM2, Tuesday/Wednesday, or pre-holiday | `+1` | 1 |
| FOMO veto | Next calendar long is overheated | `0` | 1 |
| Monday short | Regular Monday and opening gap `<= 0` | `-1` | 2 |
| T+2 momentum | Calendar is neutral | `-1`, `0`, or `+1` | 3 |

Calendar targets take precedence over T+2. The pure domain implementation is
in [`src/domain/strategy/`](src/domain/strategy/); the five-minute replay of
the inspected EC2 schedule is in
[`luna_ec2_signal_source.py`](src/adapters/strategies/luna_ec2_signal_source.py).

## 3. Data and execution model

| Input | PostgreSQL source | Use |
|---|---|---|
| Matched price | `quote.matched` | OHLC construction and marks |
| Matched volume | `quote.matchedvolume` | Bar volume |
| Front-month mapping | `quote.futurecontractcode` | Point-in-time VN30F1M contract selection |
| Reference / ceiling / floor | `quote.reference`, `quote.ceil`, `quote.floor` | Exchange price bands |
| Optional depth | `quote.bidprice`/`bidsize`, `quote.askprice`/`asksize` | Depth-backed `book_walk` execution |

The default research path reads 30-minute bars from PostgreSQL and uses an
explicit soft-fill model when historical depth is not attached. This is
labelled `MODELLED_SOFT_NO_BOOK_DEPTH` in the output; it must not be presented
as observed market liquidity. The alternative `book_walk` path reconstructs
the visible ladder as-of the order timestamp and records its own diagnostics.

Signals see a completed, left-labelled bar only. The standard runner submits
the changed target at the next available bar, preventing same-close
look-ahead. The exchange session applies dated HNX/VSDC/PIT charges and a
named SSI margin profile; broker commission is zero until an explicit fee
schedule is supplied.

## 4. Evaluation protocol

| Stage | Command | Purpose |
|---|---|---|
| Data audit | `make data-audit` | Query and validate the requested PostgreSQL window |
| In-sample | `make step4` | Causal Plutus replay on the IS window |
| Sensitivity | `make step5` | 81-point local grid; diagnostic, not best-result selection |
| Out-of-sample | `make step6` | Evaluate the frozen profile on the OOS window |
| Tests | `make check` | Owned tests, lint, and compilation |

The frozen profile lives in
[`config/frozen_luna_v0.json`](config/frozen_luna_v0.json). Treat its reported
metrics as a dated baseline, not a timeless fact: the database can be repaired
or extended and the execution engine can evolve. Regenerate the relevant
report and record its provenance before publishing a result.

Generated `reports/` are intentionally ignored by Git. They are local
evidence for a particular database snapshot, execution mode, and parameter
set—not source code.

## 5. Repository layout

```text
src/
  domain/          pure entities and Luna rules; Python standard library only
  application/     ports and use cases
  adapters/        PostgreSQL, Plutus, EC2-schedule and backtest adapters
  infrastructure/  environment, database pool and result contracts
scripts/           reproducible research entry points
config/            frozen Luna parameter profile
tests/             Luna-owned tests
plutus/            pinned Git submodule for the exchange engine
papertrade/        Step 7 PaperTrade runtime, EC2 deploy scripts, and ops docs
```

Market data, local reports, working notes, `.env`, and the full Plutus source
history are deliberately excluded from the Luna Git history.

## 6. Setup

Requirements: Python 3.12, [`uv`](https://docs.astral.sh/uv/), Git, and
read-only access to `algotradeDB` for data-backed commands.

```bash
git clone --recurse-submodules https://github.com/Viendeptrai1/luna-vn30f.git
cd luna-vn30f
cp .env.example .env
# Fill ALGOTRADE_DB_* with read-only credentials.
make setup
make check
```

For an existing clone without the engine:

```bash
git submodule update --init --recursive
```

`make setup` installs the locked Luna environment and the pinned Plutus
submodule. It does not query the database. Database credentials are used only
by data-backed commands such as `make data-audit`, `make step4`, `make step5`,
and `make step6`.

## 7. Running research

```bash
make data-audit  # Validate the requested DB window and write local provenance.
make step4       # Run in-sample replay through Plutus.
make step5       # Run the 81-point local sensitivity grid.
make step6       # Run frozen out-of-sample replay.
make plot        # Plot a locally generated Plutus report.
```

The first command for a window can take minutes because it aggregates raw tick
and volume data in PostgreSQL. Reuse loaded bars for multiple parameter
variants where possible; do not rerun a full database aggregation merely to
change one strategy parameter.

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

## 8. Known limitations

- The standard 30-minute path has modelled soft fills when book depth is not
  supplied; it is not a live-fill claim.
- The repository uses an exchange-closure proxy where original VSDC settlement
  notices are unavailable.
- Front-month history may begin later than a requested research window; the
  runner records observed coverage separately rather than inventing backfill.
- A result must be interpreted together with its database observation window,
  execution evidence, charges, margin diagnostics, and incomplete-session
  policy.

## References

- Algotrade, *Algorithmic Trading Theory and Practice — A Practical Guide with
  Applications on the Vietnamese Stock Market*, DIMI BOOK, 2023.
- [Plutus exchange engine](https://github.com/algotradevn/plutus).
