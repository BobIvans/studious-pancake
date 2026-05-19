.PHONY: acceptance check-env

check-env:
	@if [ ! -f .env ]; then \
		echo "Error: .env file not found. Copy from .env.example"; \
		exit 1; \
	fi
	@if ! grep -q "MARGINFI_ACCOUNT=" .env; then \
		echo "Error: MARGINFI_ACCOUNT not set in .env"; \
		exit 1; \
	fi
	@if ! grep -q "HELIUS_API_KEY=" .env; then \
		echo "Error: HELIUS_API_KEY not set in .env"; \
		exit 1; \
	fi

acceptance: check-env
	python scripts/acceptance_gate.py
