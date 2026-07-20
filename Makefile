.PHONY: install install-dev install-analytics lock syntax lint format-check type-check security test test-live verify verify-offline package-smoke image-smoke contracts-validate contracts-status contracts-drift status capabilities run container paper

install:
	python -m pip install --requirement requirements.txt
	python -m pip install --no-deps .

install-analytics:
	python -m pip install --requirement requirements-analytics.txt
	python -m pip install --no-deps .

install-dev:
	python -m pip install --requirement requirements-dev.txt
	python -m pip install --no-deps .

lock:
	python scripts/lock_requirements.py

syntax:
	python -m compileall -q arb_bot.py src scripts tests

lint:
	python -m flake8 arb_bot.py src scripts tests --select=E9,F63,F7,F82 --show-source --statistics

format-check:
	python scripts/quality_gate.py

type-check:
	python -m mypy --config-file mypy.ini

security:
	python scripts/quality_gate.py --with-dependency-audit

test:
	PAPER_TRADING_ONLY=true LIVE_TRADING_ENABLED=false JITO_ENABLED=false KAMINO_LIQUIDATION_ENABLED=false \
	python -m pytest -m "not live and not manual" --disable-socket --allow-unix-socket -q

test-live:
	python -m pytest -m "live and not manual" -q

verify:
	python scripts/verify_repo.py

verify-offline:
	python scripts/verify_repo.py --skip-dependency-audit

package-smoke:
	python scripts/package_smoke.py

image-smoke:
	bash scripts/image_smoke.sh

contracts-validate:
	flashloan-contracts validate

contracts-status:
	flashloan-contracts status

contracts-drift:
	flashloan-contracts drift

status:
	flashloan-bot status

capabilities:
	flashloan-bot capabilities

run:
	flashloan-bot run --mode shadow

container:
	flashloan-bot container

paper:
	@echo "PAPER_MODE_UNAVAILABLE: scripts/paper_trader.py is quarantined; canonical paper mode is planned for PR-038." >&2
	@exit 4
