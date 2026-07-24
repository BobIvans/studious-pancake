# MPR-NEXT-11 — Installed artifact + CI dependency parity hardening

This branch starts the MPR-NEXT-11 workstream from the fourth-pass production-ready audit.

## Goal

Make verification reproducible and package-bound without enabling live trading.

## Initial scope

This start slice is intentionally fail-closed and non-invasive. It establishes the review surface for:

- installed artifact verification self-bootstrap from source invocation;
- clean dependency/package smoke preconditions;
- installed console command parity checks;
- Python 3.13 workflow policy enforcement;
- keeping live, signer, sender, private-key and submission surfaces disabled.

## Follow-up implementation targets

1. Fix `scripts/verify_installed_artifact.py` so source invocation self-inserts the repository root into `sys.path` safely and deterministically.
2. Ensure `package_smoke.py` either installs required build/dev dependencies or runs only inside a documented install-dev flow.
3. Add a clean-venv smoke that installs `requirements.txt`, `requirements-dev.txt`, then the wheel.
4. Verify `flashloan-bot --help`, `status`, `capabilities`, `config doctor`, and `run --mode paper` from the installed console command.
5. Standardize production/release workflows on the supported Python 3.13 policy.

## Safety posture

This branch must not enable live trading, signing, private-key loading, transaction submission, Jito submission, or production-ready capability state.
