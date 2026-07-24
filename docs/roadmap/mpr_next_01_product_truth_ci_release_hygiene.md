# MPR-NEXT-01 — Product truth, CI and release hygiene cutover

This PR is a clean retry of the MPR-NEXT-01 slice after the previous PR was closed.

## Scope

- Adds a reviewed production-debt closure map that links offline gates to blocker families.
- Adds a sender-free verifier for product-contract drift, committed diagnostics, workflow write access, workflow Python drift, and unpinned actions.
- Keeps product-contract files owned by current `main`; this retry intentionally does not edit `product_contract_pr195.json` because `main` already removed active `/swap/v1/*` paths and exposes `/swap/v2/build`.
- Converts PR-190 diagnostics from branch-writing evidence capture into a read-only diagnostic capture.
- Aligns MPR-31 focused workflow to Python 3.13.
- Removes committed runtime/diagnostic artifacts from source control.

## Safety boundary

This PR does not enable live trading, signing, sender imports, Jito submission, or production readiness. The closure map explicitly states that offline validators do not close blockers without materialized runtime and release evidence.

## Verification

```bash
python -m py_compile \
  src/mpr_next_01_product_truth_gate.py \
  scripts/verify_mpr_next_01_product_truth.py \
  tests/test_mpr_next_01_product_truth_ci_release_hygiene.py
python -m pytest -q tests/test_mpr_next_01_product_truth_ci_release_hygiene.py
python scripts/verify_mpr_next_01_product_truth.py --json
python scripts/production_debt_audit.py --json
```
