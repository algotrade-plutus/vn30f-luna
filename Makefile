UV ?= uv

.PHONY: setup calibrum-insample calibrum-oos calibrum-forward plot test lint check

setup:
	git submodule update --init --recursive
	$(UV) sync --frozen

calibrum-insample:
	$(UV) run python scripts/run_calibrum_plutus.py --sample in_sample --start 2021-01-15 --end 2022-12-30

calibrum-oos:
	$(UV) run python scripts/run_calibrum_plutus.py --sample out_of_sample --start 2023-01-01 --end 2024-12-19

calibrum-forward:
	$(UV) run python scripts/run_calibrum_plutus.py --sample forward --start 2026-08-25 --end 2026-10-01

plot:
	$(UV) run python scripts/plot_calibrum_backtest.py

test:
	./scripts/run_owned_tests.sh

lint:
	$(UV) run ruff check .

check: test lint
	$(UV) run python -m compileall -q src scripts tests
