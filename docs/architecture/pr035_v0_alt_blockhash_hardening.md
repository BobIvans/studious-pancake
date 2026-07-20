# PR-035 — V0 compiler, ALT and blockhash hardening

## Status

This PR adds a context-bound hardening layer around the canonical Solders
compiler merged in PR-029. It does not add a planner, simulator, signer
boundary, sender, or live enablement.

The branch is intentionally based on the current `main` and does not import
open PR-028/031/032 work. PR-034 can later pass its typed `TransactionPlan`,
resolved lookup tables, and current RPC height/slot context into this compiler
without changing the PR-035 invariants.

## Supported flow

```text
immutable TransactionPlan
  -> blockhash viability check
  -> exact ordered ALT provenance check
  -> canonical MessageV0 compile
  -> wire/account/signer checks
  -> immutable compilation fingerprints
  -> revalidation before simulation or permit
```

## Invariants

1. `getLatestBlockhash` provenance is represented by `BlockhashContext`:
   blockhash, source slot, commitment, fetch time and
   `last_valid_block_height`.
2. Compilation requires an explicit `CompileRuntimeContext` with the observed
   block height, slot and timestamp.
3. A blockhash is rejected when it is stale, from a future slot, outside the
   allowed commitment set, or too close to its last valid block height.
4. Lookup tables must be supplied in exactly the order declared by the plan.
5. Every lookup table must:
   - be owned by the Address Lookup Table program;
   - be active (`deactivation_slot == u64::MAX`);
   - come from a slot satisfying both the plan and runtime context;
   - have been extended before the slot at which it was read;
   - preserve the exact address ordering returned by the Solders parser.
6. Required lookup addresses must be present. Unknown or inconsistent table
   content fails closed.
7. Compilation must produce a canonical `MessageV0` and a serialized
   transaction no larger than 1232 bytes.
8. The account-lock ceiling is an explicit local policy, not an assertion that
   every cluster/version has the same network ceiling.
9. Payer and signer order must remain identical to the plan.
10. The plan, instructions, lookup tables, blockhash context and message each
    receive deterministic SHA-256 fingerprints.
11. Any plan change after compilation invalidates the proof and requires a
    complete rebuild and later a new final simulation.

## Structured retry boundary

`V0HardeningError` exposes:

- `reason`: stable `V0CompileFailureReason`;
- `retryable`: whether a bounded route/profile retry may be attempted;
- redaction-safe diagnostics such as counts, slots and remaining block
  heights.

The compiler never performs retries. PR-031/034 schedulers may consume these
reasons, but must remain finite and may not relax the safety envelope.

## External contracts

Primary references checked for this PR:

- Solana transaction documentation: a serialized transaction has a maximum
  size of 1232 bytes.
- Solana `getLatestBlockhash`: returns both a recent blockhash and its last
  valid block height, and accepts `commitment` / `minContextSlot`.

These external facts are used as upper-level invariants. The local
`max_account_locks`, minimum remaining heights and maximum age are explicit
configuration policy and can only be tightened or intentionally reviewed.

## Tests

```bash
python -m pytest tests/execution/test_v0_hardening_pr035.py -q
python -m pytest tests/execution/test_transaction_lifecycle.py -q
python scripts/verify_repo.py
```

The focused tests cover deterministic V0 proof generation, stale/near-expiry
blockhashes, future slots, ALT order/context/deactivation, account-lock
classification and post-compile plan mutation.

## Non-goals

- no MarginFi/Jupiter instruction planning;
- no ALT RPC fetch transport;
- no compute-budget finalization or simulation;
- no fee calculation;
- no signing or submission changes;
- no live-mode promotion.
