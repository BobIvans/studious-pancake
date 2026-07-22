# PR-184 — Tamper-evident audit ledger and forensic integrity

## Scope of this slice

This change hardens the active `src.observability` SQLite path rather than adding
another isolated readiness descriptor.

The store now:

- assigns a persistent database epoch;
- links every event to the previous event in its aggregate with a deterministic
  SHA-256 chain digest;
- binds payload digest, denormalized columns, writer generation, release identity,
  PolicyBundle/config identity and database epoch into each chain entry;
- preserves an append-only public store API while allowing legacy forensic tests
  to inject direct SQLite tamper;
- creates and maintains SQLite, WAL and SHM files with owner-only `0600`
  permissions;
- rejects symlink, hardlink, wrong-owner and non-regular database files.

Offline replay now verifies:

1. strict JSON syntax, duplicate keys and finite values;
2. payload digest;
3. every duplicated payload/column field;
4. aggregate previous-hash continuity;
5. current row chain digest;
6. ordering and terminal-state regression.

## Threat model

This closes the reproduced rewrite where an attacker edits `payload_json`,
recomputes `payload_digest`, and edits `stage`. The stored chain digest no longer
matches and replay reports `CHAIN_DIGEST_DIVERGENCE`.

Deleting or reordering events produces `PREVIOUS_CHAIN_DIVERGENCE`. Direct SQLite
rewrites remain possible for forensic tooling and legacy adversarial tests, but
replay now detects them through payload/column and chain verification. Normal
application code has no update/delete ledger API.

## Compatibility

PR-132 migration identity remains version `17`; PR-184 is recorded separately as
migration `18`. Historical out-of-order ingestion remains supported, and the
aggregate chain is deterministically rebuilt by `(sequence_no, event_id)`.

## Safety boundary

This PR does not enable live trading, signing, submission, provider calls or
network access. It does not claim a remote signed checkpoint exists yet.

## Remaining PR-184 work

A later slice must add independently signed checkpoints, remote immutable
anchoring, writer authentication/fencing, forensic DB/WAL/SHM capture, and
restore-time anchor plus financial-ledger reconciliation.
