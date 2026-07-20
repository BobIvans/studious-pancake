# PR-041 — Durable lifecycle journal and crash recovery

## Purpose

PR-041 makes lifecycle truth survive process death. After restart the operator
and runtime can distinguish a candidate that was only planned or reserved, a
signed attempt with no durable submission intent, an attempt that may already
have been submitted and must never be resent automatically, and a reconciled or
otherwise terminal attempt.

The implementation is isolated in `src.durability`. It does not enable live
sending and does not replace unfinished PR-038 paper-runner wiring.

## Storage boundary

`DurableLifecycleStore` is explicitly **single-node SQLite**:

- WAL mode for file-backed databases;
- `synchronous=FULL`;
- foreign-key enforcement;
- optimistic revisions;
- ownership leases with monotonically increasing fencing tokens;
- one database transaction for state, reservation, audit event and outbox work.

A shared network filesystem, multi-host deployment or independent writer fleet
is unsupported. That topology requires a later Postgres implementation with the
same idempotency and fencing invariants.

## Atomic lifecycle contract

The canonical identity is:

```text
logical_opportunity_id + plan_hash + generation -> attempt_id
```

Creation atomically writes the attempt, optional durable capital reservation,
immutable redacted audit event sequence zero and corresponding outbox item.

Transitions require a live `attempt:<attempt_id>` lease, the exact fencing
token, expected optimistic revision, an allowed execution-state transition and
a unique idempotency key. Reusing an idempotency key returns the committed
result rather than creating a second event or trade.

## Submission safety

`record_submission_intent` accepts only a `SIGNED` attempt. The canonical
message hash has a partial unique index across all attempts. Once a submission
intent exists, startup recovery returns `reconcile_no_resubmit`; it never turns
an unknown outcome into an automatic retry.

RPC signature and Jito bundle ID are stored separately. Neither is treated as
settlement proof.

## Capital reservation recovery

PR-032 remains the decision-time capital gate. PR-041 persists the accepted
reservation ID and lamport amount beside the attempt.

On restart, pre-submission attempts may be resumed or have their reservation
explicitly released through `release_abandoned_reservation`. Submitted or
ambiguous attempts cannot use that automatic release path. This prevents
capital from being silently unlocked after a transaction may already have been
broadcast.

## Immutable redacted audit

Events are sanitized through the existing redactor before persistence. Bytes
and secret-shaped fields are not stored directly.

Events are protected by update/delete rejection triggers, unique sequence and
idempotency constraints, payload digests and a per-attempt SHA-256 chain.
`integrity_check()` runs SQLite quick/foreign-key checks and recomputes every
chain link.

## Outbox and retention

Outbox work is inserted in the same transaction as the lifecycle event. Workers
claim by topic with a fencing token. Completion is accepted only for the same
owner/token pair.

Retention may delete completed outbox work after recording a retention-ledger
entry. Immutable audit events are retained.

## Migration and rollback

Migration version is `41` and its SQL checksum is persisted. Forward migration
is idempotent. Empty-schema rollback is available for deployment tests. A
populated journal refuses destructive rollback; operators must restore a
pre-migration backup.

## Backup and restore drill

Run:

```bash
python scripts/pr041_backup_drill.py /path/to/lifecycle.db
```

The drill runs integrity checks, creates an online SQLite backup, computes its
SHA-256 checksum, restores into a temporary database, reruns integrity and row
counts, and prints machine-readable JSON. Checksum mismatch or corrupt restore
fails closed.

## Parallel PR compatibility

This patch does not modify PR-033 detector/snapshot files, PR-036 exact
simulation, future PR-037 reconciliation math, PR-038 paper-runner wiring,
PR-040 runtime control files, live sender or permit code. Those layers can
import `src.durability` once their contracts stabilize.

## Verification

```bash
python -m pytest tests/durability/test_pr041_durable_lifecycle.py -q
python -m compileall -q src/durability scripts/pr041_backup_drill.py
python scripts/verify_repo.py
```

Focused coverage includes idempotent creation, immutable redacted events,
state/revision checks, stale fencing rejection, duplicate submission
prevention, reservation recovery, outbox retention, migration rollback and
backup/restore.
