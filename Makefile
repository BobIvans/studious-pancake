.PHONY: run paper test clean recovery help

run:
	python arb_bot.py

paper:
	python scripts/paper_trader.py

test:
	python tests/test_runner.py

clean:
	python scripts/clean_state.py

recovery:
	python scripts/emergency_recover.py

help:
	@echo "Available targets:"
	@echo "  make run      - Start the main arbitrage bot"
	@echo "  make paper    - Start the paper trading simulator"
	@echo "  make test     - Run pytest and code syntax checks"
	@echo "  make clean    - Wipe database and log states"
	@echo "  make recovery - Run emergency rent and wSOL recovery"
