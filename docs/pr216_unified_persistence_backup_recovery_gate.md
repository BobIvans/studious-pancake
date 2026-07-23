# PR-216 — Unified Persistence, Backup and Recovery Platform

Pass 7 assigns PR-216 to the persistence and recovery debt cluster:

- F-289: SQLite topology is spread across many modules.
- F-290: SQLite PRAGMA policy is inconsistent.
- F-291: Multiple databases claim terminal truth.
- F-292: Backup manifest publication is non-atomic and lacks durability barriers.
- F-293: Restore closes the live store before safe cutover.
- F-294: Restore lacks rollback and directory-fsync protocol.
- F-295: Backup/restore tests only cover the happy path.

This slice adds an **offline fail-closed evidence gate**. It does not perform the
real persistence cutover yet and does not mutate live databases.

## Added module

`src/pr216_unified_persistence_backup_recovery_gate.py` defines
`pr216.unified-persistence-backup-recovery-gate.v1`.

The gate requires evidence for:

1. A single approved persistence platform/factory that owns every SQLite
   connection site.
2. A database/table catalog with owner and rebuild/authority semantics.
3. Centralized durable-critical/read-model/test PRAGMA profiles.
4. One transactional system of record for terminal truth.
5. Sequence-fenced and rebuildable projections/outbox consumers.
6. A declared recovery order covering all stores.
7. Generation-based backup publication using temp files, atomic rename/pointer
   publish and file/directory fsync.
8. Restore validation before cutover, preserving the old generation until a
   post-cutover healthcheck passes.
9. Rollback markers and proof that failed replace/reopen can recover without
   losing the old generation.
10. A deterministic fault matrix covering torn manifest write, ENOSPC,
    permission failure, corrupt WAL, failed replace, failed reopen and process
    kill before cutover.

A ready report still returns:

```text
live_execution_allowed=false
restore_mutation_allowed=false
database_connection_allowed=false
```

## Safety boundary

This PR does **not** enable or perform:

- live trading;
- transaction submission;
- direct SQLite connection opening;
- database backup;
- database restore;
- file replace/rename/fsync operations;
- runtime writer migration;
- durable authority cutover.

It is an acceptance contract and regression test surface for the real PR-216
implementation. A later cutover should make the current store/backup/restore
code produce this evidence from measured operations rather than caller-supplied
claims.

## Focused verification

Before opening the PR, the focused files were checked in a local sandbox:

```bash
PYTHONPATH=. python -m py_compile \
  src/pr216_unified_persistence_backup_recovery_gate.py \
  tests/test_pr216_unified_persistence_backup_recovery_gate.py

PYTHONPATH=. python -m pytest -q \
  tests/test_pr216_unified_persistence_backup_recovery_gate.py
# 14 passed
```

The sandbox emitted an unrelated artifact_tool spreadsheet warmup warning during
Python startup, but both commands returned exit code 0.

## Remaining full implementation

The follow-up production cutover should:

1. Introduce the real connection/transaction/PRAGMA factory.
2. Inventory and migrate all existing SQLite connect sites into that platform.
3. Select the transactional system of record and downgrade other stores to
   projections or fenced outbox consumers.
4. Replace existing backup/restore paths with generation-based publication,
   rollback and directory fsync.
5. Add fault-injection and subprocess crash tests around every publication and
   restore boundary.
6. Make repository verification fail when direct sqlite connections reappear
   outside the approved platform.
