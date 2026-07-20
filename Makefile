.PHONY: install install-dev syntax lint format-check type-check security test test-live verify verify-offline status capabilities run paper

install:
	python -m pip install --upgrade pip setuptools wheel
	python -m pip install -r requirements.txt

install-dev:
	python -m pip install --upgrade pip setuptools wheel
	python -m pip install -r requirements-dev.txt

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
	python -m pytest -m "not live and not manual" --disable-socket -q

test-live:
	python -m pytest -m "live and not manual" -q

verify:
	python scripts/verify_repo.py

verify-offline:
	python scripts/verify_repo.py --skip-dependency-audit

status:
	python arb_bot.py status

capabilities:
	python arb_bot.py capabilities

run:
	python arb_bot.py run --mode shadow

paper:
	@echo "PAPER_MODE_UNAVAILABLE: scripts/paper_trader.py is quarantined; canonical paper mode is planned for PR-038." >&2
	@exit 4
