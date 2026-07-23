# PR-213 — Canonical Authority, CLI and Debt Ledger Reset

This document describes the first Pass 7 corrective slice for PR-213. The slice is
sender-free and does not enable live trading, signing, provider calls, simulation or
transaction submission.

## Pass 7 ownership

PR-213 owns the canonical public command, runtime authority and debt/source-of-truth
reset package. The Pass 7 audit assigns it findings F-261 through F-268:

- authority validator bootstrap failures from clean checkout;
- aggregate verification hidden import preconditions;
- mutable GitHub project-management state mixed into runtime authority;
- stale roadmap identity inside authority data;
- root launcher vs installed console target divergence;
- packaging tests that check source shape instead of CLI behavior;
- automation CLI dependency failures escaping the structured contract;
- duplicate PR documentation without a canonical registry.

## What this slice changes

1. `arb_bot.py` now delegates its executable `main` to `src.cli_pr189:main`, the
   same target used by the installed `flashloan-bot` console script. Legacy imports
   from `src.cli` remain re-exported for import compatibility only; `main` is no
   longer imported from the legacy module.
2. `scripts/validate_authority_map.py` bootstraps the repository root into
   `sys.path` before importing `src.authority_map`. The validator can now run from
   a clean checkout and arbitrary working directory without relying on `PYTHONPATH`.
3. `src.automation_cli_pr189` classifies dependency/import failures as the stable
   PR-189 `unavailable` verdict with exit code `DEPENDENCY_UNAVAILABLE`, not a raw
   traceback or generic internal error.
4. Focused tests assert clean-checkout authority validation, wrapper/console help
   parity and structured dependency-unavailable JSON.

## Verification

```bash
python -m py_compile \
  arb_bot.py \
  scripts/validate_authority_map.py \
  src/automation_cli_pr189.py \
  tests/test_pr213_canonical_authority_cli.py
python -m pytest -q \
  tests/test_pr025_packaging.py \
  tests/test_pr213_canonical_authority_cli.py
```

## Safety boundary

This PR does not change runtime trading behavior. It does not load private keys,
construct transactions, call RPC/provider/Jito/Helius/Jupiter/MarginFi/Kamino, or
claim paper/live readiness. It only aligns executable command ownership and makes
failure evidence more deterministic.

## Remaining PR-213 work

Later slices still need to separate immutable runtime authority from advisory
GitHub backlog data, introduce a canonical current/superseded PR documentation
registry and make aggregate verification run through the installed artifact rather
than checkout-local state.
