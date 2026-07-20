# PR-057 — Capital engine and durable reservations integration

## Purpose

PR-057 connects the PR-032 integer capital engine to the PR-041 SQLite
lifecycle store without enabling live submission. The intent is to make native
SOL affordability decisions restart-aware before the later PR-058/059 planner
and paper-shadow runner wire the full vertical.

This PR deliberately remains a safe integration boundary. It does not fetch
live balances, build Jupiter instructions, sign transactions, send bundles, or
claim that the bot is paper-ready.

## Added boundary

`src/economics/durable_reservations.py` introduces:

- `WalletBalanceSnapshot` — a typed native SOL balance observation supplied by
  the caller after `getBalance`/equivalent read-only RPC.
- `DurableCapitalCoordinator` — subtracts active PR-041 durable reservations
  from the provided wallet snapshot before invoking `AtomicCapitalLedger`.
- `reserve(...)` — creates a PR-032 capital reservation and persists it as a
  PR-041 `DurableAttempt` + `durable_reservations` row.
- `release_pre_submission_reservation(...)` — uses PR-041 fencing leases to
  release only pre-submission abandoned reservations.
- `bounded_amount_search(...)` — deterministic helper for monotonic flash-loan
  amount bounds before a later compile/simulate loop.

## 0.015 SOL safety

The protected reserve remains enforced before any active durable reservation is
considered. With a wallet snapshot of `0.015 SOL` and the default 0.01 SOL
protected reserve, only 5,000,000 lamports are spendable before fees, rent,
tips and contingency. A candidate requiring 5,155,000 lamports is rejected as
`INSUFFICIENT_NATIVE_BALANCE`.

## Restart behavior

On startup/re-open, the coordinator calls
`DurableLifecycleStore.scan_startup_recovery()` and sums attempts with
`reservation_active=True`. Those lamports are subtracted from the wallet
snapshot before evaluating new candidates. This prevents a restarted process
from reusing SOL that is still reserved by an unfinished pre-submission
lifecycle attempt.

If an attempt is still pre-submission, the coordinator can release it through
`release_pre_submission_reservation(...)`. The release path acquires an
attempt-scoped fencing lease and then delegates to
`release_abandoned_reservation(...)`, preserving the PR-041 recovery rule that
submitted or ambiguous attempts cannot be auto-released.

## Explicit non-goals

- No live trading, signing, submission or Jito/RPC sender changes.
- No changes to MarginFi/Jupiter planner semantics.
- No claim that `flashloan-bot paper-shadow` now runs the full vertical.
- No replacement for PR-058 exact simulation or PR-059 durable runner work.

## Test coverage

`tests/test_pr057_durable_capital_reservations.py` covers:

- 0.015 SOL reserve protection.
- Lifecycle-bound active reservations.
- restart-aware active reservation subtraction.
- fenced pre-submission release and capital unlock.
- bounded amount search highest-admissible selection.
