# PR-129 — Fork-bound blockhash and pre-simulation revalidation

## Goal

PR-129 starts the fork-bound blockhash and pre-submit revalidation work from the
second deep audit. This slice is intentionally limited to the exact simulation
boundary and does not enable live submission.

## What changed

- `ExactSimulationFinalizer` no longer treats `getBlockHeight <=
  lastValidBlockHeight` as sufficient blockhash proof.
- Before the provisional simulation and again before the final simulation it now
  calls `isBlockhashValid` with:
  - the exact blockhash embedded into the later compiled message;
  - the same commitment as the simulation policy;
  - the same `minContextSlot` derived from the plan.
- `ExactSimulationReport` now carries `BlockhashValidityEvidence` for both
  validation points.
- A blockhash that is still under `lastValidBlockHeight` but not valid on the
  selected fork fails closed with `BLOCKHASH_INVALID`.
- A stale `isBlockhashValid` context slot fails closed with
  `CONTEXT_SLOT_VIOLATION`.

## Non-goals for this slice

- No live sender or submission path.
- No signing.
- No transaction assembly outside the existing exact simulation boundary.
- No cross-RPC quorum proof; PR-136 owns endpoint independence and rooted fork
  quorum.
- No full ALT re-fetch implementation; this slice establishes the blockhash
  evidence contract that ALT revalidation will bind to.

## Safety property

A final exact simulation report cannot be produced unless the exact recent
blockhash has been checked by `isBlockhashValid` at the required commitment and
`minContextSlot` before both simulation passes.
