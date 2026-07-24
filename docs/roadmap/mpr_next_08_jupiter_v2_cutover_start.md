# MPR-NEXT-08 — Jupiter V2 product contract cutover + legacy endpoint quarantine

This branch starts the MPR-NEXT-08 review thread from the fourth-pass production-ready audit.

## Goal

Remove the product-truth conflict around Jupiter by making the active product/runtime contract agree on the current composable Jupiter Swap V2 build surface and by quarantining stale `/swap/v1` endpoint references.

## Source audit mapping

The fourth-pass audit identifies this work as `MPR-NEXT-08 — Product contract V2 cutover + legacy endpoint quarantine` with branch `mpr-next-08-jupiter-v2-product-contract-cutover`.

The same audit reports that both active product-contract mirrors still declare stale Jupiter V1 paths:

- `config/product_contract_pr195.json`
- `src/resources/product_contract_pr195.json`

The required fix is to remove V1 Jupiter paths from active product/runtime resources, make `/swap/v2/build` the only composable execution-discovery contract, and add a regression test that fails if `/swap/v1` appears in active product/runtime resources.

## Full implementation target

1. Replace Jupiter V1 paths in `config/product_contract_pr195.json` and `src/resources/product_contract_pr195.json` with `/swap/v2/build`.
2. Add a focused regression test that fails on active `/swap/v1` in product/runtime resources.
3. Move stale V1 endpoint references into explicit quarantine fixture files or delete them from active source.
4. Ensure `docs/external_contracts.yaml`, provider adapter, product contract and production external contracts agree on Jupiter V2.
5. Keep any historical V1 fixtures clearly marked as `legacy_quarantine` or `historical_reference_only`.

## Safety boundary

This PR must not enable:

- live trading;
- private-key loading;
- signer IPC;
- transaction submission;
- Jito send;
- production-ready claims.

## Draft status

This initial slice opens the review surface and records the exact MPR-NEXT-08 scope. Follow-up commits on this branch should mutate the product contracts and add the regression tests.

## Expected acceptance commands

```bash
grep -R "/swap/v1" config src/resources src/providers src/routing src/external_contracts.py src/external_contracts || true
PYTHONPATH=. python -m pytest -q \
  tests/test_pr196_external_protocol_conformance.py \
  tests/test_pr070_protocol_aware_conformance.py \
  tests/test_pr179_jupiter_strict_decoding.py
python scripts/production_debt_audit.py --json
```
