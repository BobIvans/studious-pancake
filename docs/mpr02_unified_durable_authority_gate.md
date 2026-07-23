# MPR-02 — Unified durable authority gate

This slice starts **MPR-02 — Unified durable authority: attempts, capital,
leases, outbox and recovery** from the V4 runtime-cutover roadmap.

MPR-02 is the durable authority boundary after MPR-01. It must replace proof
islands with one transactional authority for identity, attempt state, wallet
capital, leases/fences, outbox, evidence pointers and restart/recovery.

## Scope of this slice

This PR adds an offline acceptance-gate contract for already-materialized
MPR-02 evidence. It validates that a future runtime authority proves:

- one transactional authority, not multiple paper/runtime stores;
- renewable leases with claim generation, heartbeat, owner boot epoch and stale
  owner rejection;
- outbox states including `CLAIMED` lease recovery and bounded DLQ behavior;
- wallet-level serializable capital reservation and over-reservation rejection;
- append-only tamper-evident events and deterministic materialization;
- domain integrity checks over attempts, capital, leases, outbox and terminal
  hashes;
- atomic backup bundle, WAL/SHM-aware restore and rollback generation;
- structured-concurrency cancellation with durable terminal/incomplete state;
- fault-injection probes for the persistence boundaries called out by the audit.

## Non-goals

This PR does **not** enable or implement:

- live trading;
- signer or private-key access;
- sender/Jito/RPC submission;
- provider network calls;
- production database migration;
- real runtime writer cutover.

A clean report means only that the evidence is ready for durable runtime
integration review. It still reports:

```text
live_execution_allowed=false
signer_allowed=false
sender_allowed=false
```

## Verification

```bash
python -m py_compile \
  src/durability/mpr02_unified_authority_gate.py \
  tests/test_mpr02_unified_authority_gate.py
python -m pytest -q tests/test_mpr02_unified_authority_gate.py
```

The local focused check for this slice produced `9 passed` before opening the PR.
