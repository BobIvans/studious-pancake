# PR-195 durable lifecycle follow-up

This follow-up keeps the merged PR-195 boundary sender-free and strengthens the
durable lifecycle acceptance gates called out by the pass-3 production audit.

## Scope

`src/pr195_durable_lifecycle.py` adds a small SQLite/WAL authority for two
runtime-critical PR-195 invariants:

1. **Opportunity lifecycle/dedupe is durable and bounded.**
   - Admission creates a pending lifecycle key and immutable event in one
     `BEGIN IMMEDIATE` transaction.
   - Expiry moves the opportunity to `expired` and releases the key from
     `pending` to retained `terminal` in the same transaction.
   - Terminal dedupe has explicit retention and compaction, so repeated
     deterministic ids cannot be blocked forever and tracker cardinality is
     bounded.

2. **Wallet capital reservation is serializable.**
   - Reservation is guarded by the active wallet total inside the same SQLite
     writer transaction.
   - Idempotent replay returns the existing reservation without double counting.
   - Failure-fee accounting can release the active balance while preserving the
     charged fee on the terminal reservation row.

## Deliberate non-goals

This PR does not enable live trading, signing, transaction construction,
simulation, RPC/Jito send, external providers or production DB cutover. It is an
offline acceptance-gate slice that PR-198/PR-199 can later wire into the single
runtime composition root.

## Verification

```bash
python -m pytest -q tests/test_pr195_durable_lifecycle.py
python -m py_compile src/pr195_durable_lifecycle.py tests/test_pr195_durable_lifecycle.py
```

The tests cover:

- expiry releasing pending lifecycle state and permitting re-admission after
  retention/compaction;
- dedupe persistence across restart;
- idempotent admission replay;
- terminal compaction cardinality;
- wallet reservation overcommit rejection and idempotent replay;
- immutable opportunity event evidence.
