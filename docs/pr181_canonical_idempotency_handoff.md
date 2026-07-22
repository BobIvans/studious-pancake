# PR-181 — Canonical idempotency and crash-safe reservation handoff

This PR starts the active implementation of roadmap PR-181.

## Production defect

The current exact paper attempt accepts caller-supplied reserve, release and
final-fee idempotency strings. The lifecycle database uses a globally unique
string and duplicate lookup can return the current attempt before validating
operation, target state, payload digest or policy generation.

The successful exact-attempt path also returns
`READY_FOR_DURABLE_PAPER` while the active reservation still lacks a durable
next-stage owner/outbox transaction.

## Active boundary

`src/durability/canonical_idempotency.py` adds a SQLite-backed active boundary:

- canonical `OperationIdentity` binds domain, attempt, generation, operation,
  request payload hash and policy generation;
- exact duplicate replay returns the originally stored result;
- a different request for the same logical operation raises
  `IDEMPOTENCY_CONFLICT`;
- successful paper handoff writes operation result, reservation ownership,
  fencing lease and outbox in one transaction;
- reservations remain fenced during ambiguous recovery;
- lease expiry produces a deterministic reclaim action;
- maximum age produces manual review instead of unsafe auto-release;
- acknowledgement is owner/fencing-token bound.

`src/paper_shadow/crash_safe_attempt_pr181.py` wraps the existing exact-attempt
orchestrator. It replaces all three caller-provided key values with internally
derived operation identities before reserve/release/final-fee processing.

When the coordinator exposes the real `DurableLifecycleStore` SQLite
connection, the wrapper requires the successful exact-attempt path to commit
the PR-181 handoff before its result can be considered ready.

## Safety

- no signer;
- no sender;
- no transaction submission;
- no Jito/RPC network call;
- no live activation;
- submission ambiguity never auto-releases capital.

## Follow-up

A later migration should replace the legacy global idempotency columns in
`durable_events` and `durable_reservations` with composite canonical operation
identity, migrate retained records, and make PR-181 handoff recovery part of
the canonical runtime supervisor.
