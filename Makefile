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
