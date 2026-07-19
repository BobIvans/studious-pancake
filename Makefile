.PHONY: install syntax test test-live verify status capabilities run paper

install:
	python -m pip install --upgrade pip setuptools wheel
	python -m pip install -r requirements.txt

syntax:
	python -m compileall -q arb_bot.py src scripts tests

test:
	PAPER_TRADING_ONLY=true LIVE_TRADING_ENABLED=false JITO_ENABLED=false KAMINO_LIQUIDATION_ENABLED=false \
	python -m pytest -m "not live and not manual" --disable-socket -q

test-live:
	python -m pytest -m "live and not manual" -q

verify:
	python scripts/verify_repo.py

status:
	python arb_bot.py status

capabilities:
	python arb_bot.py capabilities

run:
	python arb_bot.py run --mode shadow

paper:
	@echo "PAPER_MODE_UNAVAILABLE: scripts/paper_trader.py is quarantined; canonical paper mode is planned for PR-038." >&2
	@exit 4
