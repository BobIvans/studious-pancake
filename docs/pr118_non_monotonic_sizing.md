# PR-118: Non-monotonic exact sizing and typed cost ledger

PR-118 adds a safe economics boundary for route sizing without assuming that
`amount -> executable profitable` is monotonic.

This patch is intentionally offline and side-effect free. It does not fetch
quotes, build transactions, reserve capital, sign, submit, or enable live mode.
It prepares the sizing/economics contract that later PR-113/119/102 plumbing can
call after exact quote amount coupling is available.

## Why this exists

The old bounded amount search is a binary search intended for monotonic candidate
factories. Real aggregator routes are not monotonic: larger amounts can switch
routes, trigger account/CU/ALT thresholds, fail at one size and succeed at a
larger size, or change fee/rent behavior discontinuously.

PR-118 therefore evaluates explicit exact points and picks the best admissible
conservative net profit among the evaluated points. A rejection at one point does
not prune larger points.

## New module

`src/economics/non_monotonic_sizing.py` provides:

- `build_pr118_amount_grid(...)` for bounded grid construction;
- `evaluate_pr118_non_monotonic_sizing(...)` for exact point evaluation;
- `PR118SizingCandidateEvidence` for exact request/quote provenance;
- `PR118TypedCostLedger` for integer-only multi-asset costs;
- `PR118FlashRepaymentTerms` with the invariant:

```text
required_repayment = principal + flash_fee + protocol_rounding
```

## Safety properties

- No binary-search monotonicity assumption is used.
- Each candidate must prove that its `requested_flash_loan_lamports` equals the
  exact evaluated amount.
- Every sizing point keeps exact quote hashes and optional route ID.
- Optimization is by conservative net profit, not largest amount.
- The typed ledger stores principal, flash fee and rounding in one place to avoid
  protocol-fee double counting.
- Non-settlement asset costs fail closed unless a future verified conversion
  contract is added.
- Conversion into the legacy `CapitalCandidate` is limited to SOL/wSOL-style
  native settlement and sets `protocol_fee_lamports=0` because repayment already
  includes the flash fee.

## Non-goals

This PR does not wire provider discovery, Jupiter quota budgets, final rebuild,
MarginFi execution, paper composition, sender, or live submission. Those belong
to PR-113, PR-119 and the later real paper vertical.

## Suggested verification

```bash
python -m pytest tests/test_pr118_non_monotonic_sizing.py -q
python -m pytest tests/test_pr057_durable_capital_reservations.py tests/test_pr118_non_monotonic_sizing.py -q
python -m black --check src/economics/__init__.py src/economics/non_monotonic_sizing.py tests/test_pr118_non_monotonic_sizing.py
python scripts/verify_repo.py --skip-dependency-audit
```
