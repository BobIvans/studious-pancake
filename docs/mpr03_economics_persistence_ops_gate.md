# MPR-03 — Finalized economics, persistence, observability and release evidence gate

This document describes the first safe acceptance-contract slice for **MPR-03 —
Finalized economics, unified persistence, observability and release evidence**.

The uploaded Mega PR pack assigns MPR-03 to the operational proof boundary:
every paper/shadow attempt must have final economics proof, durable lifecycle,
backup/recovery path, meaningful readiness/metrics and release artifact evidence.

This slice intentionally does **not** perform the physical cutover. It adds a
side-effect-free validator that later implementation commits must satisfy with
materialized evidence.

## Scope

Added module:

- `src/mpr03_economics_persistence_ops_gate.py`

Added focused tests:

- `tests/test_mpr03_economics_persistence_ops_gate.py`

The validator requires the following production-debt owners from the pack:

- `execution.finalized-settlement-binding`
- `evidence.finalized-economic-proof`
- `evidence.real-shadow-soak`
- `deployment.image-provenance`
- `operations.slo-readiness`
- `security.secret-incident-drill`

## Required evidence families

### 1. Upstream MPR dependency evidence

MPR-03 depends on MPR-01 and MPR-02. The gate requires both to be accepted and
bound to materialized SHA-256 report digests before MPR-03 can be ready.

### 2. Finalized economic proof

The gate requires integer/base-unit evidence that reconciles:

- quote economics;
- exact simulation result;
- capital / fee / rent / tip reservation;
- payer balance deltas;
- token account deltas;
- flashloan repayment math;
- fail-closed reason when finalized evidence is unavailable.

Gross spread cannot mark a paper attempt successful unless conservative net
economics are positive after all costs.

### 3. Unified persistence factory

The gate blocks unless direct SQLite / aiosqlite islands are removed or
quarantined behind the approved persistence factory. It requires central PRAGMA
policy, schema fingerprinting, migration guards and exactly-once terminal
lifecycle after crash/restart.

### 4. Backup and recovery

The required backup publication order is:

```text
temp_write -> file_fsync -> atomic_rename -> dir_fsync -> publish_generation_pointer
```

The gate also requires restore validation, rollback markers, previous generation
preservation and a fault matrix covering WAL, concurrent writers, torn manifest,
crash during cutover, failed restore validation and rollback generation.

### 5. Observability and readiness

Readiness must distinguish:

- safe idle;
- dependency blocked;
- degraded;
- shadow ready;
- release ready;
- live denied.

Metrics must cover provider freshness, queue depth, reconciliation lag,
database contention, reservation leakage, terminal counts, lineage counts, drift
probe age and backup/restore age with stable cardinality and secret redaction.

### 6. Shadow soak lineage

Sender-free shadow soak evidence must distinguish:

- synthetic fixture;
- recorded provider fixture;
- credentialed provider snapshot;
- finalized on-chain evidence.

Synthetic or recorded data cannot be counted as real release evidence.

### 7. Release manifest

`production_cutover_manifest` entries must either provide a real 64-character
hex SHA-256 digest or explicitly record a fail-closed missing-artifact state.
Placeholder hashes or silent success are rejected.

### 8. Secret incident drill

The gate requires materialized evidence for secret rotation, revocation and
diagnostic redaction drills.

## Safety boundary

This PR does **not**:

- enable live trading;
- load private keys;
- open signer IPC;
- submit transactions;
- call RPC/Jito/providers;
- run database migrations;
- build Docker images;
- execute real shadow soak;
- mutate deployment state.

A passing report still keeps:

```text
operational_paper_ready_allowed=false
live_execution_allowed=false
signer_allowed=false
sender_allowed=false
```

It only allows sender-free paper/shadow evidence review.

## Focused verification

```bash
PYTHONPATH=/mnt/data/mpr03_gate python -m py_compile \
  /mnt/data/mpr03_gate/src/mpr03_economics_persistence_ops_gate.py \
  /mnt/data/mpr03_gate/tests/test_mpr03_economics_persistence_ops_gate.py

PYTHONPATH=/mnt/data/mpr03_gate python -m pytest -q \
  /mnt/data/mpr03_gate/tests/test_mpr03_economics_persistence_ops_gate.py
# 17 passed
```

## Remaining full MPR-03 work

This acceptance gate must later be wired into the real runtime and release
pipeline:

1. replace direct SQLite and aiosqlite connection islands with the approved
   persistence factory;
2. bind every terminal paper/shadow outcome to finalized economic proof;
3. implement generation-based backup/restore and fault tests;
4. make readiness and metrics read real operational state;
5. add sender-free shadow soak lineage reports;
6. populate `config/production_cutover_manifest.json` with real computed
   digests or explicit fail-closed missing-artifact entries;
7. keep live denied until MPR-04/canary gates explicitly approve it.
