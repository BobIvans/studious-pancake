# PR-188 — bounded Helius ingress and canonical event dedup

This PR hardens the active `src/providers/helius/delivery.py` boundary without
enabling strategy execution, signing, transaction submission or live funds.

## Active corrections

- Replaces `gzip.decompress()` with incremental `zlib.decompressobj()` output
  limits and compression-ratio enforcement.
- Performs a structural JSON preflight before `json.loads`, rejects duplicate
  object keys and non-finite numbers, and retains exact post-parse limits.
- Derives primary event identity from cluster, webhook/provider, transaction
  signature or provider-native event ID, and a stable event discriminator.
  Batch index and mutable full-payload hash are not part of primary identity.
- Separates new, exact duplicate, correction and conflict representations.
  Corrections are retained as evidence but do not enqueue strategy work twice.
- Enforces a monotonic delivery deadline through decode, parse and SQLite
  transaction ownership. Busy/locked storage returns retryable 503, never 200.
- Creates durable, idempotent backfill jobs when a slot gap is detected.
- Creates the SQLite directory and DB/WAL/SHM files with owner-only permissions.

## Safety invariants

- HTTP 200 follows a committed durable enqueue or an identified duplicate.
- A changed representation of the same chain event cannot create a second inbox
  item.
- The module remains sender-free and signer-free.
- No external provider credentials are used in CI.
- Live execution remains disabled.

## Verification

Focused tests cover changed payload, batch reordering, bounded gzip bombs,
duplicate JSON keys, non-finite values, durable backfill dedup, file modes,
monotonic deadline expiry and SQLite contention.

## Remaining PR-188 integration

A later composition change should attach this hardened plane to the actual
authenticated webhook server through a dedicated bounded writer task and expose
queue/backfill metrics. Public webhook exposure must remain disabled until that
composition and operational load tests are reviewed.
