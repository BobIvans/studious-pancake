# Roadmap PR-02 — Unified lifecycle and trusted-time authority

## Mission

PR-02 makes the public PR-041/PR-182 SQLite lifecycle database the only
transactional authority for sender-free paper intent and terminal effects.
It absorbs the active ownership seams introduced by PR-181, B3, A3, PR-187,
and PR-191 without enabling a signer, sender, transaction submission, or live
trading.

## Active cutover

`src/durability/unified_authority_pr02.py` extends the existing clock-safe
lifecycle connection. It does not open a second lifecycle database.

The authority owns:

- provider, paper-cycle, and exact-attempt intent before expensive work;
- release and PolicyBundle identity;
- owner, fencing token, boot identity, process generation, and dual expiry;
- immutable terminal records;
- atomic reservation terminalization and lifecycle event creation;
- one immutable outbox-event table with separate mutable delivery state and
  append-only delivery attempts;
- append-only dead-letter history;
- deterministic exact replay or explicit safe-indeterminacy recovery.

Database product identity, schema manifest, epoch compatibility, and migration
fencing are delegated to the already merged PR-195 authority. PR-02 does not
create a competing database-identity table.

`src/paper_shadow/durable_service_a3.py` now records a PR-02 intent before it
calls the batch source. A3 cycle/outbox tables remain only compatibility
projections written inside the same PR-02 terminal transaction.

## B3 transactional boundary

`UnifiedA3AdmissionSink` implements the existing B3 `A3AdmissionSinkPort`. It
accepts only the SQLite connection whose PR-195 `database_identity_pr195`
record matches the reviewed PR-02 product, schema family, and application
schema version. Therefore a Helius/B3 database cannot claim an atomic A3
handoff unless it is the same physical SQLite product.

Production composition must configure Helius delivery/rooted recovery and the
paper lifecycle authority to the same reviewed database path before installing
this sink. A different path fails closed with
`PR02_FOREIGN_TRANSACTION_CONNECTION`.

## Compatibility status

The following historical surfaces remain readable for migration and existing
operator tests, but they are not independent authorities:

- `a3_paper_service_cycles`;
- `a3_paper_service_outbox`;
- PR-041 durable attempts, reservations, events, and leases;
- PR-182 boot/time-domain side tables.

A3 projection rows and PR-02 canonical terminal/outbox rows are committed in
one SQLite transaction. The service no longer writes an isolated A3 database
product.

## Recovery rules

- exact terminal replay returns the original terminal/outbox identity;
- changed payload under the same intent fails with an immutability conflict;
- lost owner, fencing token, lease, release, PolicyBundle, boot, or process
  generation prevents terminal commit;
- cross-boot unfinished intent becomes `safe_indeterminacy_reconcile`;
- indeterminate attempts keep capital frozen rather than auto-releasing it;
- dead-letter records are append-only and cannot be replaced.

## Merge safety

The branch is rebased by merge onto the then-current `main` before verification.
Review and merge decisions must use the current GitHub merge-commit checks,
not an older green head from a previous base.

## Verification

Focused coverage is in `tests/test_pr02_unified_lifecycle_authority.py`:

- cycle intent exists before batch/provider work;
- terminal and outbox atomicity plus exact replay;
- boot-domain/fence failure with no partial terminal;
- lifecycle event, reservation state, terminal record, and outbox commit together;
- B3 sink rejection on a foreign SQLite connection;
- append-only dead-letter history;
- installed A3 compatibility projection backed by the PR-02 authority.

Repository-wide GitHub Actions remains the merge source of truth. Live,
signer, sender, Jito submission, and RPC submission remain disabled.
