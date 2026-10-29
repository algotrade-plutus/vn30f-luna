UV ?= uv
RUN = $(UV) run python scripts/run_calibrum_1m.py
START ?= 2026-08-10
END ?= 2026-08-14

.PHONY: setup fetch-data step5 step4 step6 paper benchmarks figures week test lint check

setup:
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

# Step 7: the Luna bot's paper account, recomputed from its fills; redraws the README chart.
paper:
	$(UV) run python scripts/paper_luna.py --chart image/README/paper_luna.png

benchmarks:
	$(RUN) benchmarks

figures: benchmarks
	$(UV) run python scripts/plot_calibrum_1m.py
	$(UV) run python scripts/plot_calibrum_drawdown.py
	$(UV) run python scripts/plot_momentum_scores.py
	$(UV) run python scripts/plot_episodes.py

week:
	$(UV) run python scripts/plot_calibrum_positions.py --start $(START) --end $(END)

test:
	./scripts/run_owned_tests.sh

lint:
	$(UV) run ruff check .

check: test lint
	$(UV) run python -m compileall -q src scripts tests

.PHONY: papertrade-test papertrade-deploy papertrade-status papertrade-stop papertrade-resume papertrade-dashboard

papertrade-test:
	$(UV) run --python 3.12 pytest tests/test_paper_runtime.py tests/test_calibrum_live.py tests/test_dashboard.py -q

papertrade-deploy:   # build the committed runtime on the EC2 and install it; the timer starts it
	bash papertrade/ops/push_build.sh

papertrade-status:
	bash papertrade/ops/calibrum_status.sh

papertrade-dashboard:   # read-only web view at http://localhost:18080 through an SSM tunnel
	bash papertrade/ops/calibrum_dashboard.sh

papertrade-stop:     # HALT new orders and stop the runner (positions stay open)
	bash papertrade/ops/calibrum_stop.sh

papertrade-resume:
	bash papertrade/ops/calibrum_resume.sh
