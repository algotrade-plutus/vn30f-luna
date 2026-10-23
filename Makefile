UV ?= uv
RUN = $(UV) run python scripts/run_calibrum_1m.py
START ?= 2026-08-10
END ?= 2026-08-14

.PHONY: setup fetch-data step5 step4 step6 benchmarks figures week test lint check

setup:
	git submodule update --init --recursive
	$(UV) sync --frozen

# DNSE 1-minute bars, with 5-minute bars to fill the sessions DNSE lacks at 1 minute.
fetch-data:
	$(UV) run python scripts/fetch_dnse_candles.py --start 2018-08-01 --end $$(date +%F) --resolution 1
	$(UV) run python scripts/fetch_dnse_candles.py --start 2018-08-01 --end $$(date +%F) --resolution 5

# Step 5 on in-sample only: Ridge lambda by cross-validation, Momentum threshold, Basis grid.
step5:
	$(RUN) momentum-cv
	$(RUN) momentum-q
	$(RUN) basis-grid

# Step 4: the seven combinations on in-sample with the starting parameters (needs the Ridge fit).
step4:
	$(RUN) in-sample-baseline

# Step 6: valid chooses the final combination; each out-of-sample window opens once, in order.
step6:
	$(RUN) valid
	$(RUN) oos1
	$(RUN) oos2

benchmarks:
	$(RUN) benchmarks

figures: benchmarks
	$(UV) run python scripts/plot_calibrum_1m.py
	$(UV) run python scripts/plot_calibrum_drawdown.py

week:
	$(UV) run python scripts/plot_calibrum_positions.py --start $(START) --end $(END)

test:
	./scripts/run_owned_tests.sh

lint:
	$(UV) run ruff check .

check: test lint
	$(UV) run python -m compileall -q src scripts tests

.PHONY: papertrade-setup papertrade-test papertrade-docker papertrade-check papertrade-dashboard

papertrade-setup:
	cd papertrade && ./scripts/bootstrap.sh

papertrade-test:
	cd papertrade && PYTHONPATH=. ./.venv/bin/python -m pytest tests -q

papertrade-docker:
	docker build --platform linux/amd64 --tag algotrade-paper:local ./papertrade

papertrade-check:
	./papertrade/scripts/check_live_alpha.sh

papertrade-dashboard:
	./papertrade/scripts/open_dashboard.sh
