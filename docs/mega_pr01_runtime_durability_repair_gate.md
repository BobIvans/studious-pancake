# MEGA-PR-01 V3 runtime durability repair gate

This document records the V3 expansion of **MEGA-PR-01 — Canonical Runtime, Durable Paper Core and Provider Data Plane**.

The V3 audit makes MEGA-PR-01 more than a wiring PR. It must close runtime correctness and durability defects around queue expiry, task supervision, bounded memory, shutdown, SQLite writer ownership, cross-boot time, semantic idempotency, canonical outbox delivery, webhook durability and RPC secret redaction.

## Covered findings

This slice adds an acceptance contract for `IMPL-25` through `IMPL-38`:

- atomic queue/tracker expiry and same-ID re-admission;
- structured supervision for detector, consumer, database writer and paper-cycle tasks;
- bounded tracker/result/report collections and retention metrics;
- one deadline-bounded shutdown owner;
- async/deadline provider intake and one bounded SQLite writer authority;
- cross-boot monotonic/UTC reconciliation;
- semantic idempotency command hashes and conflict rejection;
- verified migration identity/checksum and reservation recovery;
- canonical outbox claim/renew/ack/nack/retry/DLQ/compaction;
- chain-stable webhook identity, fencing, max-attempt DLQ and forensic bounds;
- secret-safe RPC endpoint modelling and path/query redaction tests.

## Added contract

`src/mega_pr01_runtime_durability_repair_gate.py` defines:

```text
mega-pr-01.runtime-durability-repair.v3
```

The evaluator is side-effect-free and deterministic. It does not open databases, start network clients, sign, send, submit, migrate production state or enable live execution.

A passing report allows only sender-free paper **merge review** for this slice:

```text
sender_free_paper_merge_review_allowed=true
operational_paper_ready_allowed=false
live_execution_allowed=false
signer_allowed=false
sender_allowed=false
```

## Paper merge gate

The V3 paper merge gate must include accelerated long-soak evidence proving:

- bounded cardinality;
- task-death readiness closure;
- `kill -9` recovery;
- webhook reorder/retry correctness;
- outbox exactly-once effects;
- no secret bytes in config/doctor/log/fingerprint artifacts.

## Focused verification

```bash
PYTHONPATH=. python -m py_compile \
  src/mega_pr01_runtime_durability_repair_gate.py \
  tests/test_mega_pr01_runtime_durability_repair_gate.py

PYTHONPATH=. python -m pytest -q \
  tests/test_mega_pr01_runtime_durability_repair_gate.py
```

Local sandbox result before committing this slice:

```text
11 passed
```

## Remaining implementation

This slice does not physically repair every runtime hot path. Later MEGA-PR-01 commits must wire this contract into the real queue/tracker/runtime/application/webhook/outbox/config code, run the accelerated long-soak against the installed artifact, and replace source-only assertions with materialized release evidence.
