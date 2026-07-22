# MEGA-PR B3 — active provider receiver and rooted recovery

This slice turns the merged Helius delivery contract into an active
receiver → durable inbox → leased worker → rooted recovery → A3 handoff path.

## Canonical ownership

- `src.providers.helius.delivery` remains the authoritative delivery/inbox store.
- `src.providers.helius.receiver` is the bounded aiohttp receiver.
- `src.providers.helius.rooted_recovery` owns worker leases, fencing, retries,
  dead-letter state, rooted gap recovery and the transactional A3 handoff.
- Legacy `src.ingest.helius_webhook_handler` remains excluded and is not imported.

No second webhook database or in-memory dedup authority is introduced.

## Delivery changes

The existing delivery plane is hardened so that:

- gzip decompression is incremental and bounded by decoded output;
- one monotonic deadline covers stream collection, decoding and parsing;
- duplicate JSON keys and non-finite constants are rejected;
- events are canonically ordered before persistence;
- event identity no longer includes mutable batch position;
- a reordered delivery cannot enqueue another inbox row;
- canonical event JSON is stored for later independently verified replay;
- a detected gap does not advance the contiguous cursor.

The HTTP receiver reads compressed request chunks into a bounded buffer and
does no strategy work before the exact inbox transaction commits.

## Rooted recovery

`RootedRecoveryWorker` claims one inbox row through:

- worker identity;
- monotonically increasing fencing token;
- expiring lease;
- bounded attempt counter;
- retry delay;
- terminal dead-letter state.

An unresolved gap invokes a `RootedBackfillPort`. The gap is closed only when
the result is bound to the exact release and PolicyBundle, has current
rooted-RPC and chain-context hashes, covers the complete gap and is not expired.

The event then passes through an independent evidence verifier. The final A3
admission sink receives the active SQLite transaction, so the A3 admission row,
B3 handoff record and inbox terminal state commit atomically.

## Failure semantics

- no raw provider exception text is persisted;
- an expired worker lease can be reclaimed only with a new fencing token;
- a stale worker cannot commit;
- verification/backfill failures retry under policy;
- max-attempt failures enter durable dead letter;
- unresolved gaps cannot advance the cursor or reach A3;
- duplicate/reordered deliveries cannot generate duplicate opportunities.

## Safety invariants

```text
live_enabled = false
sender_reachable = false
signer_reachable = false
submission_enabled = false
ack_before_durable_enqueue = false
legacy_ingest_imported = false
```

## Focused verification

```bash
python -m pytest tests/test_mega_pr_b3_rooted_recovery.py -q
python -m pytest tests/test_b2_helius_delivery_plane.py -q
python scripts/verify_repo.py
```

## Remaining B3 work

This slice does not claim the whole workstream complete. Follow-up integration
still needs protected credentialed Jupiter V2 fixture production, rooted
MarginFi deployment/account/repayment evidence production, the final
independent evidence verifier implementation and the concrete A3 database sink.
