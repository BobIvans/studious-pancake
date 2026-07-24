# MPR-NEXT-01 — Product truth, debt closure map, CI and release hygiene cutover

This slice makes product/debt/release truth explicit without enabling live trading.

## Scope

- Add `src/resources/production_debt_closure_map.json` as the closure authority map for MPR-25..31 and PR-225/226/228.
- Keep offline validators from resolving production blockers without materialized runtime/release evidence.
- Verify active product contracts do not contain Jupiter `/swap/v1` paths and do contain `/swap/v2/build`.
- Remove committed runtime logs and failed diagnostics from the release artifact.
- Convert PR-190 diagnostics from branch-writing behavior to read-only artifact upload.
- Keep MPR-31 workflow aligned to Python 3.13.

## Safety boundary

This PR does not enable live trading, private-key reads, signing, transaction submission, Jito send, canary execution or production-ready status.

## Verification

```bash
python -m py_compile \
  src/mpr_next_01_product_truth_gate.py \
  scripts/verify_mpr_next_01_product_truth.py \
  tests/test_mpr_next_01_product_truth_ci_release_hygiene.py
PYTHONPATH=. python -m pytest -q tests/test_mpr_next_01_product_truth_ci_release_hygiene.py
python scripts/verify_mpr_next_01_product_truth.py --json
python scripts/production_debt_audit.py --json
```
