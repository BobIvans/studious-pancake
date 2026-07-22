# PR-128 compute-budget, loaded-account-data and fee-market finalization

PR-128 is a P0 transaction/economics hardening slice. It does not enable live
submission and does not change sender behavior.

## Roadmap finding

The second deep audit identifies that current execution can observe
`loadedAccountsDataSize` during simulation without proving an explicit final
`SetLoadedAccountsDataSizeLimit` instruction in the exact message. It also calls
out that compute budget and fee-market decisions must be part of final message
proof before permit/submission.

## This slice

This PR adds `src/execution/compute_budget_finalization.py`, an offline
fail-closed primitive that converts simulation and fee-market evidence into a
final compute-budget policy:

- CU limit = observed `unitsConsumed` plus bounded margin;
- loaded-account-data limit = observed `loadedAccountsDataSize` plus bounded
  margin;
- priority price selected from current `getRecentPrioritizationFees`-shaped
  evidence at or above `minContextSlot`;
- optional fee-price cap;
- total landing-cost cap = RPC network fee plus optional Jito tip;
- exactly one Compute Budget instruction per variant:
  - `SetComputeUnitLimit`;
  - `SetComputeUnitPrice`;
  - `SetLoadedAccountsDataSizeLimit`.

## Negative coverage

The regression tests reject:

- duplicate Compute Budget variants;
- missing `loadedAccountsDataSize`;
- missing or stale priority-fee evidence;
- priority price above policy cap;
- total landing cost above policy cap;
- final observation consuming more CU/data or a different fee than approved.

## Follow-up wiring

A later integration patch should wire this primitive into
`ExactSimulationFinalizer` so the final `CompiledTransaction` is rebuilt and
re-simulated after compute limit, CU price, loaded-data limit, tip or blockhash
changes. That follow-up must keep live submission disabled until PR-129/130/138
settlement work lands.
