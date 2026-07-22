# PR-200 — non-blocking durable I/O and deadline-aware backpressure

## Problem

The active Helius delivery plane performs synchronous `sqlite3` initialization,
connection acquisition, `BEGIN IMMEDIATE`, writes and commit work. When it is
called from an async HTTP/runtime coroutine, SQLite lock contention blocks the
entire event-loop thread even when the store eventually returns a retryable 503.
That stalls unrelated heartbeats, health checks, settlement polling and shutdown.

## Boundary introduced by this PR

`AsyncPersistenceWriter` owns blocking durable work on one dedicated thread and
presents a bounded async API. Each operation carries:

- a stable operation ID;
- an absolute monotonic deadline;
- a persistence priority/work class;
- an estimated memory size;
- an explicit committed/not-committed result.

The writer provides:

- bounded item and byte admission;
- reserved capacity for financial/lifecycle writes;
- priority ordering so observability/maintenance cannot overtake proof-critical
  writes;
- no blocking durable calls on the event-loop thread;
- known `NOT_SUBMITTED`, known `NOT_COMMITTED`, `COMMITTED`, and
  `UNKNOWN/await reconciliation` states;
- idempotent lookup by operation ID after caller timeout;
- writer/queue/latency/failure health metrics;
- shutdown that stops admission, preserves critical work and cancels optional
  queued work.

## Helius integration

`AsyncHeliusDeliveryPlane` constructs and invokes the existing
`HeliusDeliveryPlane` only inside the owned writer thread. SQLite initialization
and enqueue/commit are therefore both off-loop. The HTTP-facing caller gets an
async result and never acknowledges a delivery unless the underlying delivery
plane returned its durable HTTP 200 result.

If the caller deadline expires while a writer operation is still running, the
adapter returns retryable 503/unknown rather than guessing that the write failed.
The deterministic operation ID can then be queried for the final result. The
existing Helius delivery ID and canonical inbox dedup continue to make provider
retries safe.

The operation ID includes only server configuration identity, content encoding,
a coarse auth state (`missing`, `match`, `mismatch`) and the raw body digest. It
does not persist or fingerprint the authorization secret.

## Priority order

1. financial ledger / submission intent / settlement;
2. lifecycle state;
3. webhook durable enqueue;
4. alert outbox;
5. observability export;
6. maintenance.

Non-critical work cannot consume the configured critical reserve.

## Shutdown contract

1. stop new admission;
2. complete in-flight work;
3. preserve queued financial/lifecycle work;
4. mark optional queued work `NOT_SUBMITTED` when cancellation is enabled;
5. stop and join the writer thread;
6. expose `shutdown_clean` in health.

## Verification

Focused tests cover:

- a blocking writer operation while the asyncio heartbeat continues;
- timeout returning `UNKNOWN`, followed by deterministic reconciliation;
- optional queue flood preserving critical capacity and priority;
- shutdown preserving critical work and cancelling optional work;
- a real Helius SQLite exclusive lock while the event loop remains schedulable.

## Integration notes

New async ingress/runtime code should depend on `AsyncHeliusDeliveryPlane`, not
call `HeliusDeliveryPlane.accept_delivery()` directly from a coroutine. Other
SQLite products can use the same writer boundary with their own operation IDs,
priority classification and explicit commit result. PR-195 database-product
identity remains authoritative; this PR does not merge unrelated SQLite files.

This patch intentionally avoids editing the legacy webhook handler or other
shared composition roots while PR-198, PR-199 and PR-201 are developed in
parallel. Their authentication, archive and authorization boundaries remain
separate. A later composition-root cutover should install this async adapter as
the only coroutine-facing Helius durability surface.

## Non-goals

- no live trading, signing or submission is enabled;
- no database files are merged;
- no legacy Helius authentication or proxy semantics are changed (PR-199 owns
  that boundary);
- no observability archive format changes are made (PR-198 owns that boundary);
- no nonce/replay authorization changes are made (PR-201 owns that boundary).
