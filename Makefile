UV ?= uv

.PHONY: setup calibrum-insample calibrum-oos calibrum-forward plot test lint check

setup:
	git submodule update --init --recursive
	$(UV) sync --frozen

# Plutus runs: 300M VND, 3-contract cap for every ensemble so methods compare fairly.
# vote trades 3 x sign(R+S+C); sum trades R+S+C in [-3, 3] (the runner multiplies sum by 3).
ENSEMBLE ?= vote
CAPITAL ?= 300000000
PLUTUS_CONTRACTS = $(if $(filter sum,$(ENSEMBLE)),1,3)
FORWARD_END ?= 2026-10-01
PLUTUS_RUN = $(UV) run python scripts/run_calibrum_plutus.py --ensemble-mode $(ENSEMBLE) \
	--capital $(CAPITAL) --contracts $(PLUTUS_CONTRACTS)

calibrum-insample:
	$(PLUTUS_RUN) --sample in_sample --start 2021-06-01 --end 2022-12-30 \
		--report reports/calibrum_plutus_insample_$(ENSEMBLE)3_300m.json

calibrum-oos:
	$(PLUTUS_RUN) --sample out_of_sample --start 2023-01-01 --end 2024-12-19 \
		--report reports/calibrum_plutus_oos_$(ENSEMBLE)3_300m.json

# 2025 is left out; forward starts in 2026 and is the last check before paper trading.
calibrum-forward:
	$(PLUTUS_RUN) --sample forward --start 2026-01-01 --end $(FORWARD_END) \
		--report reports/calibrum_plutus_forward_$(ENSEMBLE)3_300m.json

plot:
	$(UV) run python scripts/plot_calibrum_backtest.py

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

.PHONY: fetch-data step4 step5 step6 plutus-report

fetch-data:
	$(UV) run python scripts/fetch_dnse_candles.py

step4:
	$(UV) run python scripts/run_step4_insample.py --no-fetch --ensemble $(ENSEMBLE)

step5:
	$(UV) run python scripts/run_step5_selection.py

step6:
	$(UV) run python scripts/run_step6_oos.py --no-fetch --ensemble $(ENSEMBLE) --sample out_of_sample
	$(UV) run python scripts/run_step6_oos.py --no-fetch --ensemble $(ENSEMBLE) --sample forward

plutus-report:
	$(UV) run python scripts/generate_plutus_report.py

ensemble-research:
	$(UV) run python scripts/run_ensemble_research.py --no-fetch

