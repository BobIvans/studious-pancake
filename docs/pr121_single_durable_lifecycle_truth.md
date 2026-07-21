# PR-121 — Single durable lifecycle truth readiness gate

This PR adds a review-only gate for the roadmap PR-121 boundary. It does not migrate live state, remove the JSONL runner journal, enable paper execution, or turn on a sender. The goal is to make the required single-store contract explicit and testable before a later migration patch changes runtime behavior.

## Why this exists

The deep audit identifies competing lifecycle truth surfaces: JSONL paper/shadow journal, SQLite durable lifecycle primitives, and legacy stores. PR-121 requires a single transactional store before real paper execution can be considered production-like.

## Contract added

`src/durability/single_truth.py` defines:

- `SingleTruthPackage`
- `SingleTruthReadiness`
- `evaluate_single_durable_lifecycle_truth(...)`
- `assert_single_durable_lifecycle_truth(...)`

A passing package means only:

```text
single-durable-lifecycle-truth-review-ready
```

It still returns:

```text
live_execution_allowed = false
paper_runtime_migration_enabled = false
```

## Required evidence

The gate requires:

- SQLite as the only authoritative lifecycle store.
- JSONL and legacy shadow stores not authoritative.
- Candidate, attempt, reservation, plan, compile, simulation, reconciliation, outcome and sender-state components.
- Atomic binding of state transition, reservation update, audit event and outbox event.
- Outbox claim, complete, fail, reschedule, backoff, jitter, max-attempt, dead-letter, poison quarantine and operator replay lifecycle.
- Backup through online SQLite backup, temporary destination, fsync of file and directory, atomic rename and signed manifest.
- Restore validation before overwrite, integrity check, schema/checksum checks and rollback plan.
- Failure injection for partial write, disk full, corrupt page, process kill, poison outbox item and concurrent runner.

## Non-goals

- No live trading.
- No sender import.
- No signer access.
- No RPC/Jito submission.
- No runtime migration.
- No deletion of the existing JSONL code path.

## Recommended verification

```bash
python -m pytest tests/test_pr121_single_durable_lifecycle_truth.py -q
python scripts/verify_repo.py --skip-dependency-audit
```
