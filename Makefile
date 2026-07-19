.PHONY: install syntax test test-live verify paper

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

paper:
	PAPER_TRADING_ONLY=true LIVE_TRADING_ENABLED=false JITO_ENABLED=false KAMINO_LIQUIDATION_ENABLED=false \
	python scripts/paper_trader.py
