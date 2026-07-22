# MEGA-PR A3 — installed durable sender-free paper service

A3 starts the installed service cutover for the canonical sender-free paper
vertical. The workplan requires the merged A startup seam, exact-attempt
orchestrator and A2 projection to become the actual `flashloan-bot run --mode
paper` service rather than another disconnected evaluator.

The installed paper entrypoint now owns a transactional SQLite authority. The
legacy `paper-shadow` command remains available as an explicit diagnostic JSONL
runner, but JSONL is no longer the canonical authority for `run --mode paper`.

## Durable authority

Each service cycle is recorded in:

- `a3_paper_service_cycles`
- `a3_paper_service_outbox`

The cycle row binds run ID, monotonic sequence, owner, fencing token, lease
expiry, provider evidence hash, report hash, source surface and the
sender/submission/live safety flags. The outbox row is committed in the same
SQLite transaction as the cycle record.

## Default fail-closed behavior

A3 intentionally does not fabricate B3 provider evidence. The default service
writes one durable blocked cycle with:

```text
blocked_a3_b3_provider_evidence_missing
```

This is a valid service execution result, not a paper success. The CLI exits
with the existing blocked paper exit code and prints an
`INSTALLED_PAPER_SERVICE` summary.

## A2 projection seam

A reviewed B3-backed batch source can supply exact-attempt work and an A2
runtime-cycle port. The service persists normalized terminal states:

- `NO_TRADE`
- `BLOCKED`
- `SIMULATION_FAILED`
- `RECONCILED_PAPER_SUCCESS`
- `RECONCILED_PAPER_FAILURE`
- `INDETERMINATE`

A global cycle deadline is enforced. Runtime exceptions become indeterminate
records rather than fabricated success.

## Safety invariants

A3 does not enable or import a sender or signer. Reports carrying sender,
submission or live evidence cannot be represented as a normal successful paper
state. Live mode remains hard-denied by the existing product contract.

## Verification

The focused A3 tests cover:

- default B3-missing blocked persistence;
- ready exact-attempt projection persistence;
- unsafe sender/submission evidence becoming indeterminate;
- installed CLI ownership of paper mode.

Full GitHub repository verification remains the source of truth for formatting,
typing, security, package and regression gates.
