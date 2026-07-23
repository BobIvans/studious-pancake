# MPR-26 — Crash-consistent durable authority gate

This PR starts the V11 MPR-26 boundary as a deterministic, offline,
sender-free acceptance contract.

It targets the durable authority vertical described in the V11 roadmap:
attempt identity, capital reservation, leases, event log, projections, outbox
and recovery must become one crash-consistent economic authority before
continuous paper/shadow or any later live boundary can depend on them.

## Scope

The gate requires evidence for:

- one durable authority API for attempts, capital, leases, events, outbox,
  projections and recovery;
- explicit `BEGIN IMMEDIATE`/COMMIT/ROLLBACK or a serialized writer protocol;
- no autocommit multi-statement economic transitions;
- rowcount/CAS/fencing and committed-row reread before any side effect;
- canonical length-prefixed attempt/cycle/outbox identities;
- rejection of NUL collisions, bool-as-int, NaN, float money and malformed
  pubkeys;
- append-only event log as authoritative truth;
- replay equality for materialized rows and startup blocking on tampering;
- queued/claimed/delivered/dead-letter outbox FSM with renewable leases,
  fencing tokens, retry history, backoff and poison quarantine;
- secure DB/WAL/SHM/backup storage with 0700 parents, 0600 files,
  no-follow path handling, ownership/inode checks and atomic restore pointer;
- kill-at-every-boundary and two-process race evidence.

## Finding coverage

The contract covers V11 MPR-26's durable findings:

```text
F-374...F-389
```

It also encodes the V11 current-evidence blockers described for MPR-26:
fragmented SQLite stores, false autocommit atomicity, child/projection tamper
gaps and unsafe 0644 database files.

## Safety boundary

This PR does not:

- migrate production data;
- call providers or RPC;
- load secrets;
- open signer IPC;
- sign or submit transactions;
- enable live trading.

A passing report still returns:

```text
live_execution_allowed=false
signer_allowed=false
sender_allowed=false
provider_network_allowed=false
```

The only positive state is:

```text
ready-for-durable-cutover-review
```

That means the submitted evidence is internally coherent enough for MPR-26
review. It is not a claim that the actual runtime has already been migrated.

## CI repair note

During the PR #378 verification loop, the mandatory repository suite also
exercised the already-merged MEGA-PR-01 V6 Jupiter quota tests. This branch was
rebased onto current `main` and now carries only the MPR-26 gate plus the
minimal durable Jupiter quota transaction fix required by those tests.

## Local focused verification

```bash
python -m compileall -q \
  src/mpr26_crash_consistent_durable_authority_gate.py \
  tests/test_mpr26_crash_consistent_durable_authority_gate.py

PYTHONPATH=. python -m pytest -q \
  tests/test_mpr26_crash_consistent_durable_authority_gate.py \
  tests/test_mega_pr01_v6_runtime_data_plane_repair.py
```

## Remaining physical cutover work

Follow-up implementation must replace the live callers and stores with this
authority rather than keeping this module as a proof island. In particular:

1. migrate existing attempts/reservations/lifecycle/outbox writers;
2. retire independent terminal stores;
3. generate evidence from actual crash/race/restore harnesses;
4. make readiness consume replay-verified authority state;
5. keep signer, sender, RPC/Jito and live capability default-off until MPR-30
   and MPR-31 consume the signed evidence.
