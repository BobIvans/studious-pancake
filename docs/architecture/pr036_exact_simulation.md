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

## PR-035 integration

PR-035 is already merged into `main` and remains the authority for v0/ALT and
recent-blockhash compilation hardening. PR-036 does not duplicate or weaken that
policy. It adds the next evidence boundary after planning/compilation: the final
simulation report and later permit/submission must identify the same serialized
message.

The public `validate_exact_submission_binding` hook accepts the permit message
hash and submission message hash. Any mismatch is fatal and invalidates the
simulation evidence. Future runtime wiring must preserve the PR-035 hardened
compilation result through this PR-036 binding instead of recompiling through a
less strict path.

## Verification

```bash
python -m black --check src/execution/exact_simulation.py tests/execution/test_exact_simulation_pr036.py
python -m mypy --config-file mypy.ini src/execution/exact_simulation.py
python -m pytest tests/execution/test_exact_simulation_pr036.py -q
python -m compileall -q src/execution tests/execution
python scripts/verify_repo.py
```
