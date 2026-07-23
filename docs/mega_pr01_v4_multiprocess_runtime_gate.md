# MEGA-PR-01 V4 — multi-process paper-runtime repair gate

This checkpoint starts the V4 expansion of **MEGA-PR-01** after the earlier
canonical paper-runtime and V3 runtime-durability gates were merged.

It is an offline, sender-free acceptance contract. It does not open production
SQLite files, call providers, construct transactions, sign, submit, load private
keys, run migrations or declare the system operational-paper-ready.

## V4 scope covered

The V4 audit adds MEGA-PR-01 findings **IMPL-42…IMPL-57** and **IMPL-60**.
This gate makes those required invariants reviewable before the real runtime
hot paths are physically cut over.

### A. Authority and ownership

- Sensitive writes require synchronized trusted time.
- Degraded or unsynchronized time must close readiness.
- Every mutation is owner/fence-bound.
- Active foreign ownership is rejected.
- Takeover allocates a new fencing token.
- Terminal states are irreversible.
- Terminal result persistence and terminal visibility are atomic.
- Timeout, cancellation and lease loss use a separate recovery fence.
- Cycle sequence allocation and execution ownership are atomic.
- Lease TTL must exceed cycle deadline plus commit/rollback margin and must be
  renewable.

### B. Provider queue and evidence

- Inbox rows and provider handoffs require claim/lease/ACK/NACK/DLQ state.
- Poison work must have retry budget, backoff and permanent classification.
- The oldest poison item cannot block newer work forever.
- Original webhook/event age is bounded using trusted time domains.
- Stale historical events are rejected or routed to explicit backfill.
- RPC quorum observations are constructed inside admitted transport rather than
  accepted from caller labels.
- Raw provider bytes become immutable content-addressed evidence.

### C. Capital

- Available-capital check and reservation insertion are one atomic transaction.
- Aggregate active reservations cannot exceed the admitted spendable balance.
- Wallet snapshots are bound to payer, genesis, rooted slot, provider evidence
  and captured trusted time.
- Reservation identity is collision-free across release and reattempt.
- Cleanup failures freeze attempts for durable recovery instead of silently
  stranding capital.

### D. Batch runtime

- Attempt generation is one or greater everywhere.
- Generation zero is rejected at all boundaries.
- Each candidate has a per-item deadline and durable partial-progress checkpoint.
- Restart resumes only unfinished fenced items.
- A slow candidate cannot erase completed results.
- Multi-instance chaos must prove no duplicate cycle, no foreign-fence mutation,
  no over-reservation, no lost terminal result and bounded queue progress.

## Added files

- `src/mega_pr01_v4_multiprocess_runtime_gate.py`
- `tests/test_mega_pr01_v4_multiprocess_runtime_gate.py`
- `docs/mega_pr01_v4_multiprocess_runtime_gate.md`

## Focused verification

```bash
PYTHONPATH=. python -m py_compile \
  src/mega_pr01_v4_multiprocess_runtime_gate.py \
  tests/test_mega_pr01_v4_multiprocess_runtime_gate.py

PYTHONPATH=. python -m pytest -q \
  tests/test_mega_pr01_v4_multiprocess_runtime_gate.py
```

## Safety boundary

A passing report allows only review of the multi-process repair contract:

```text
multiprocess_repair_review_allowed=true
operational_paper_ready_allowed=false
live_execution_allowed=false
signer_allowed=false
sender_allowed=false
```

This means the PR is still not an operational paper promotion. The real
MEGA-PR-01 completion still requires wiring this contract into the runtime
authority, provider queue, capital reservation store and installed paper service,
then running the required multi-process chaos gate against the installed artifact.
