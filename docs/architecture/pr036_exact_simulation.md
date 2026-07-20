# PR-036 — Exact simulation and compute-budget finalization

## Boundary

The final execution decision must be based on the exact Solana v0 message later
bound to a permit and submission. A simulation of a different compute limit,
compute price, blockhash, instruction sequence, or account layout is not valid
evidence for that message.

This PR adds an isolated finalization boundary. It does not enable live trading,
add a signer or sender, or promote any provider capability.

## Algorithm

1. Require one commitment for blockhash, simulation, and fee quotation.
2. Check block height against `last_valid_block_height`.
3. Compile a provisional message with the configured high simulation CU limit.
4. Enforce wire-byte and resolved-account caps.
5. Simulate the exact provisional transaction with `replaceRecentBlockhash=false`.
6. Require a valid context slot, `unitsConsumed`, bounded loaded-account bytes,
   and exactly the targeted account snapshots.
7. Compute integer `ceil(units * margin_bps / 10_000)` and bound it by the
   configured minimum and CU cap.
8. Rebuild the entire message with the final limit and original CU price.
9. Re-check blockhash validity and simulate the exact rebuilt message.
10. Quote the fee for the exact final serialized message.
11. Persist message, response, and logs hashes plus slot/CU/fee context.

Any later byte mutation changes the SHA-256 message hash and invalidates the
report. Both permit and submission hashes must equal the final simulation hash.

## Fail-closed states

Retryable failures include RPC timeout, rate limiting, node lag, blockhash
expiry, account-in-use, malformed or unknown RPC success shapes, and a null fee
quote. Fatal failures include deterministic program rejection, compilation
failure, CU/wire/account limits, commitment mismatch, and message identity
mismatch. Neither category is converted to success.

## Targeted snapshots

Only the payer and immutable `TransactionPlan.monitored_accounts` are requested.
The finalizer does not expand the request to every instruction account. Requests
above the configured return-account limit are rejected before RPC, and the RPC
must return exactly one entry per requested address.

## Parallel integration

The branch starts directly from `main`. PR-036 depends conceptually on PR-035,
but does not copy an unmerged permit implementation. The public
`validate_exact_submission_binding` hook accepts a permit message hash and a
submission message hash. Earlier parallel roadmap PR files are not modified.

After preceding PRs merge, update this branch from `main` and rerun all checks.

## Verification

```bash
python -m pytest tests/execution/test_exact_simulation_pr036.py -q
python -m compileall -q src/execution tests/execution
python scripts/verify_repo.py
```
