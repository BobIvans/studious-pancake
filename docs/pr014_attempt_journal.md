# PR-014 Durable Attempt Journal and Safe RPC/Jito Lifecycle

Migration version: `14`.

Canonical entry points:

- `src.execution.journal.SQLiteAttemptJournal` owns the durable SQLite/WAL attempt ledger, `(logical_opportunity_id, plan_hash, attempt_generation)` uniqueness, CAS transitions, append-only `attempt_events`, and startup recovery of intent records into `submission_uncertain`.
- `src.execution.lifecycle.TransactionLifecycleService` is the transport-neutral lifecycle boundary. It records deterministic signatures and submission intent before a sender can be called, and treats all sender returns as acknowledgements only.
- `src.execution.live_gate.LiveSubmissionGate` is hard-disabled for PR-014 and returns `LIVE_GATE_NOT_OPEN`; no environment variable opens it.
- `src.execution.reconciliation.classify_reconciliation` models reconciliation as the source of truth: signature, repayment, final-balance, slot and commitment evidence are required before success.

Pinned documentation facts used by tests/fixtures:

- Solana `sendTransaction`: relays a signed transaction; success is the first signature, not confirmation/landing; callers must set explicit encoding, preflight commitment, bounded retries, and min context slot when required.
- Solana `getSignatureStatuses`: recent status cache may return `null`; late/restart reconciliation uses `searchTransactionHistory=true`.
- Solana `getBlockHeight`: blockhash expiry is proven from block height and last valid block height, not wall-clock time alone.
- Solana `simulateTransaction`: repository simulation evidence is required before any future live send, including Jito because Jito single forces skip-preflight.
- Jito low-latency send: single `sendTransaction` returns a transaction signature in JSON `result`; the optional bundle id is in the `x-bundle-id` response header. `bundleOnly=true` is a query parameter. `sendBundle` returns a bundle id for 1-5 transactions. `getInflightBundleStatuses` accepts at most five ids and has a five-minute window; `Invalid`, `null`, timeout, or malformed responses are ambiguous until bundle/final signature/account reconciliation resolves them.

Legacy defects removed/guarded:

- The active journal is no longer restart-volatile; `InMemoryExecutionJournal` is only a compatibility shim over SQLite `:memory:`.
- Acknowledgement is never converted to `landed`.
- The same signed bytes are not retried via another sender by lifecycle code.
- Jito single no longer stores the JSON signature as a bundle id and no longer puts `bundleOnly` inside the JSON-RPC config object.
