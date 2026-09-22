# MPR-43 — Unified Persistence, Migration and Disaster-Consistent Recovery

This PR starts the MPR-43 delivery track as a focused, reviewable foundation.
It does **not** claim that all active runtime SQLite sites have already been
migrated. It creates the canonical authority and regression checks needed for
the physical cutover.

## Scope

Added `src/durability/mpr43_unified_persistence.py`, a standard-library-only
SQLite authority that provides:

- one migration registry with deterministic checksums;
- schema fingerprinting over `sqlite_master` plus migration state;
- explicit SQLite durability pragmas;
- one active writer-generation fence;
- append-only audit events;
- durable inbox and outbox rows committed in one transaction;
- integer-only economic ledger entries;
- backup creation and clean-host restore validation;
- a direct `sqlite3.connect` / `aiosqlite.connect` scanner with allowlist.

## Safety boundary

This PR does **not**:

- enable live trading;
- import Jito senders;
- read wallets or private keys;
- submit transactions;
- replace every existing DB call in the active runtime;
- mark production or paper readiness as complete.

## Verification

```bash
python -m py_compile \
  src/durability/mpr43_unified_persistence.py \
  scripts/verify_mpr43_unified_persistence.py \
  tests/test_mpr43_unified_persistence.py

PYTHONPATH=. python -m pytest -q tests/test_mpr43_unified_persistence.py
PYTHONPATH=. python scripts/verify_mpr43_unified_persistence.py --json
```

## Follow-up cutover required

The next MPR-43 slices should use this authority as the physical migration
target:

1. classify every active `sqlite3.connect` and `aiosqlite.connect`;
2. migrate runtime modules to typed repositories/unit-of-work APIs;
3. remove `INSERT OR REPLACE` from audit history;
4. bind economic reservation, inbox, outbox, settlement and audit writes to one
   transaction boundary;
5. add disk-full/corruption/migration-interruption injection tests;
6. turn backup/restore reports into release-bound artifacts.

## Acceptance covered by this slice

- migration checksums fail closed;
- schema fingerprint is stable;
- stale writer fences cannot mutate;
- audit history is append-only;
- inbox/outbox/audit commit atomically;
- ledger rejects float/NaN/bool-as-int money;
- backup restore rejects active writer generation;
- clean backup validates integrity and schema fingerprint;
- direct SQLite connect scanner is allowlist-based.
