# PR-206 Durable Time, Semantic Idempotency and Replay-Verified State

PR-206 is a sender-free corrective boundary for findings F-209 through F-216.
It does not enable signing, submission, transport, canary, or live trading.

## Authority and compatibility

`src/pr206_durable_state.py` subclasses the historical PR-195 SQLite store and
continues writing the existing `pr195_*` lifecycle and reservation tables. It
does not create a competing lifecycle writer. Additive `pr206_*` tables bind:

- durable UTC expiry and retention deadlines;
- boot/process/monotonic reconciliation metadata;
- canonical request and exact prior-result digests;
- immutable-event head hashes and event counts;
- authoritative terminal reservation accounting.

Migration 206 records the exact PR-206 schema checksum, PR-195 parent migration,
parent schema checksum, and tool version. Any mismatch is a startup hard stop.

## Transaction boundary

Every admission, transition, reservation, and terminal release uses
`BEGIN IMMEDIATE`. The PR-195 materialized row, immutable event, PR-206 truth
row, and semantic idempotency result commit together. A failure in any sidecar
write rolls the whole operation back; there is no successful legacy write with
missing PR-206 evidence.

Caller idempotency keys are namespaced by operation kind, principal, generation,
and canonical request digest. Exact replays return the stored prior result.
Different requests deterministically raise a collision instead of returning a
foreign lifecycle or reservation.

## Durable time

UTC deadlines are durable across reboot. Monotonic deadlines are derived and
rebased for the current boot only. Startup fails closed on UTC rollback or a
same-boot monotonic/process-generation rollback. Expiry and dedupe compaction
use the durable UTC truth.

## Projection verification

Critical reads and transitions replay the immutable PR-195 event chain and
verify contiguous revisions, transition legality, evidence hashes, event hashes,
materialized state/revision/terminal flags, update identity, lifecycle-key
ownership, and the PR-206 event head/count.

The historical PR-195 boolean claim report is retained only for compatibility;
it always carries `PR206_AUTHORITATIVE_STORE_EVIDENCE_REQUIRED` and cannot
produce a promotion-ready verdict.

## Verification

```bash
python scripts/verify_pr206_durable_state.py --json
python -m pytest tests/test_pr206_durable_state.py -q
make pr206-durable-state
python scripts/verify_repo.py --skip-dependency-audit
```

The focused suite covers reboot, UTC rollback, semantic collisions, namespaced
wallet reservations, terminal fee conflicts, parent/current migration tamper,
projection tamper, immutable evidence, transactional fault rollback, and
concurrent lifecycle admission.

The implementation was integrated on top of `main` commit
`3277b495ee26cf2e4d08593898041183a714c768`. The latest-main merge, exact Black
check, authoritative verifier, required-control validation, authority-map
validation, and focused compatibility suite all completed successfully before
the review-ready CI run.

## Rollback boundary

The migration is additive and preserves all PR-195 rows and immutable events.
Rollback may stop using PR-206 APIs, but must not delete `pr206_*` evidence or
resume a writer that treats unbound legacy idempotency keys as successful
replays. Re-entry into PR-206 re-verifies both migration ledgers and all
materialized projections before accepting work.
