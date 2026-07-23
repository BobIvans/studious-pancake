# MPR-CLOSE-23 — Hermetic Test, Build and Entrypoint Cutover

This change establishes one reproducible clean-environment verification path for the installed product. It addresses the roadmap requirement that build, test collection and command dispatch must not depend on a developer's source checkout or a pre-populated global environment.

## Canonical product boundary

- The supported product command remains `flashloan-bot` from the installed wheel.
- `arb_bot.py` remains a backward-compatible thin wrapper, not the verification or deployment root.
- Clean verification removes `PYTHONPATH` and `VIRTUAL_ENV` and enables `PYTHONNOUSERSITE`.
- The clean environment installs `.[dev]`, which includes runtime dependencies (`solders`, `aiolimiter`, `aiosqlite`) and build/test tooling (`build`, `pytest`).
- Live, Jito and Kamino liquidation surfaces remain disabled throughout verification.

## Commands

```bash
make package-smoke-clean
make test-collect-clean
make release-artifacts-clean
make verify-clean
```

Each target copies the repository without generated artifacts, creates a new virtual environment with `system_site_packages=False`, installs the project and dev profile, runs the selected checks, and finally proves that `flashloan-bot status --json` executes from the environment's installed console script.

## Safety boundary

This PR does not change `product_state`, enable live trading, load a keypair, invoke a sender, or treat source-checkout success as installed-package evidence. It also does not hide missing dependencies with broad import exception handling.

## Parallel-work boundary

The patch is intentionally limited to the hermetic driver, Make targets, focused tests, documentation and a focused workflow. It avoids active paper vertical, provider, settlement, signer and evidence modules owned by parallel MPR-CLOSE work.
