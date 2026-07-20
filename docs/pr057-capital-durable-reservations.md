# PR-057 — Capital engine and durable reservation integration

This patch starts the PR-057 cutover without enabling live trading or depending on
parallel PR-052…056 branches.

## What changes

- Adds `DurableCapitalLedger`, a SQLite-backed native SOL reservation ledger.
- Preserves the PR-032 integer capital policy and fail-closed NO_TRADE reasons.
- Persists active reservation IDs so a restarted paper/shadow runner can recover
  reserved lamports instead of double-spending the same wallet balance.
- Adds a runtime opportunity adapter that maps detected opportunities into
  `CapitalCandidate` objects.
- Updates the supported application composition root to use the canonical capital
  precheck builder instead of the old gross-profit-only `ConfiguredCapitalPrecheck`.

## Safety boundaries

- No signing, simulation, transaction compilation, Jito submission, RPC sends or
  live trading are introduced here.
- The default application precheck rejects opportunities with
  `capital_wallet_snapshot_missing` until a real wallet balance snapshot is
  supplied by a later discovery/paper runner.
- Durable reservations are scoped by policy fingerprint, and only active
  reservations for the current policy count against available wallet lamports.
- Reservation release is idempotent.

## Verification target

```bash
python -m pytest tests/economics/test_pr057_durable_capital.py -q
python -m compileall -q src/economics src/application.py tests/economics
```

## Follow-up handoff

PR-058/059 should consume this boundary after the planner/compiler/simulation
vertical exists. At that point the runner should provide the actual RPC wallet
balance snapshot, pass a durable reservations DB path, and release or finalize
reservation IDs only after a durable paper outcome is written.
