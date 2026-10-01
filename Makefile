UV ?= uv

.PHONY: setup data-audit step4 step5 step6 plot research test lint check

setup:
	git submodule update --init --recursive
	$(UV) sync --frozen

data-audit:
	$(UV) run python scripts/step2_prepare_data.py

step4:
	$(UV) run python scripts/run_step4_insample.py

step5:
	$(UV) run python scripts/run_step5_optimize.py

step6:
	$(UV) run python scripts/run_step6_outsample.py

plot:
	$(UV) run python scripts/plot_backtest.py

research: data-audit step4 step5 step6 plot

test:
	./scripts/run_owned_tests.sh

lint:
	$(UV) run ruff check .

check: test lint
	$(UV) run python -m compileall -q src scripts tests
