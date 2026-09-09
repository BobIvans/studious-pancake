# PR-195 durable lifecycle and recovery evidence gate

This PR starts a continuation slice for **PR-195 — Canonical Control Plane,
Idempotency and Durable Lifecycle**.

The uploaded pass-3 roadmap defines PR-195 as the durable control-plane boundary:
one transactional authority for opportunity, attempt, event, lease, latch,
reservation, permit metadata, outbox and recovery. This slice adds an offline
validator for the evidence that must exist before the runtime can claim that
PR-195 is complete.

## Scope in this slice

`src/production_lifecycle_pr195.py` validates a
`pr195.durable-lifecycle-recovery.v1` evidence document for:

- exactly one canonical lifecycle writer;
- JSONL and legacy stores removed from write authority;
- forward-only schema and startup refusal on unknown schema;
- explicit write transaction boundary, fsync policy, WAL contention settings and
  serialized connection ownership;
- one append-state-plus-event transition primitive;
- unique revision/event constraints and replay verification of materialized
  projections;
- durable idempotency keys, bounded terminal compaction and atomic release of
  `PENDING` on queue expiry;
- trusted monotonic leases, CAS renewal, fencing tokens and stale-owner
  rejection;
- wallet revision fencing and atomic attempt+reservation creation;
- durable-before-ACK outbox, fenced claims, nack/retry ceiling, DLQ and alerts;
- restore via a validated temporary sibling with previous-generation
  preservation and authenticated backup identity;
- required crash/fault drills for kill -9, duplicate opportunities, stale
  fencing tokens, disk-full/read-only DB, corrupt WAL and backup/restore.

## Safety boundary

This PR does **not** enable live trading, signing, submission, Jito/RPC sends,
capital movement, migrations against a real database, background workers or
runtime cutover. The new helpers return:

```text
live_capability_allowed() == False
signer_capability_allowed() == False
sender_capability_allowed() == False
```

The module is a deterministic offline acceptance gate only.

## Why this PR exists

The pass-3 audit identifies PR-195 as critical because lifecycle correctness
cannot be proven while opportunity dedupe, JSONL journal authority, SQLite
sequence allocation, leases, reservations, outbox and recovery remain split
across multiple stores or memory-only surfaces.

This slice does not replace the existing PR-195 foundation module. It adds a
reviewable acceptance gate that future wiring, migration and crash harness work
must satisfy.

## Verification

```bash
python -m pytest \
  tests/test_pr195_production_lifecycle.py \
  -q --disable-socket --allow-unix-socket

python -m compileall -q \
  src/production_lifecycle_pr195.py \
  tests/test_pr195_production_lifecycle.py
```

## Remaining PR-195 work

This is not a complete PR-195 implementation. Remaining work includes wiring
the canonical store into the runtime, removing JSONL/A3/legacy write authorities,
adding real DB migrations, running multi-process reservation stress tests,
executing kill/recovery fault injection against the real store and making the
sender-free runtime consume only this lifecycle authority.
