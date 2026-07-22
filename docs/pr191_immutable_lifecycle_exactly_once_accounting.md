# PR-191 — Immutable lifecycle transitions and exactly-once terminal accounting

## Mission

Remove mutable replay semantics from the active paper lifecycle/outbox and live
terminal accounting paths.

The reproduced failures were:

- replaying one PR-150 transition used `INSERT OR REPLACE` and reset a delivered
  outbox row from `1` to `0`;
- `record_actual_outcome()` could append the same finalized attempt/asset more
  than once.

## Active cutover

PR-191 installs compatibility cutovers during package import:

- `src.paper_shadow.structured_runtime.SQLitePaperLifecycleStore` resolves to
  `ImmutableSQLitePaperLifecycleStore`;
- `src.execution.live_control.LiveControlStore` resolves to
  `ImmutableLiveControlStore`;
- `src.execution.live_control.record_actual_outcome` resolves to the immutable
  PR-191 posting function.

The old tables remain readable for migration compatibility. No second lifecycle
or live-control database is introduced.

## Immutable lifecycle transitions

Each transition now has a SHA-256 payload identity covering:

- schema;
- transition/attempt/run/cycle identity;
- state and terminal reason;
- counters;
- readiness result;
- dependency reasons;
- complete safe details;
- creation time.

A duplicate transition ID or `(run_id, cycle)` behaves as follows:

- identical canonical payload: return the original commit;
- changed payload: raise `PR191_IMMUTABILITY_CONFLICT`;
- no row is replaced.

## Split outbox ownership

PR-191 creates:

```text
paper_lifecycle_outbox_event
paper_lifecycle_outbox_delivery
paper_lifecycle_outbox_attempt
```

`outbox_event` is immutable producer data. `outbox_delivery` is mutable
consumer-owned state. `outbox_attempt` is append-only attempt history.

Producer replay cannot change:

- acknowledgement;
- owner;
- fencing token;
- attempt count;
- lease;
- retry time;
- last error.

The legacy `paper_lifecycle_outbox.delivered` column is retained only as a
compatibility projection and is never reset by producer replay.

## Terminal financial identity

One terminal posting is identified by:

```text
attempt_id
attempt_generation
asset
finalized_signature
settlement_evidence_hash
accounting_operation
```

Exact duplicate posting returns the original outcome and outbox event.

A different payload under the same terminal identity:

1. records an immutable accounting conflict;
2. marks the original posting `frozen`;
3. freezes a matching budget reservation;
4. activates the durable journal-invariant latch;
5. raises `PR191_TERMINAL_ACCOUNTING_CONFLICT`.

Corrections create a new immutable posting with `supersedes_outcome_id`; the
original row is never updated.

## Atomic boundary

One SQLite transaction commits:

- terminal outcome;
- reservation terminal state;
- immutable terminal outbox event;
- initial delivery state;
- any divergence or loss latch.

Transport delivery remains at-least-once. Logical event and ledger posting are
exactly-once by stable identity.

## Safety

```text
INSERT OR REPLACE lifecycle writes = removed from active path
producer replay resets acknowledgement = false
duplicate terminal financial posting = false
conflicting terminal posting = fail closed
correction mutates original = false
live enabled by this PR = false
sender/signing/submission added = false
```

## Focused verification

```bash
python -m pytest tests/test_pr191_immutable_lifecycle_accounting.py -q
python -m compileall -q src tests
```

## Remaining integration

- External dispatchers should adopt the PR-191 lease/attempt APIs instead of
  updating the legacy boolean projection directly.
- Every terminal live call site should provide the real finalized signature and
  settlement evidence hash. The compatibility fallback derives deterministic
  identity for old callers but does not constitute release-grade settlement
  evidence.
- PR-193 remains responsible for explicit close/checkpoint ownership.
