# PR-154 durable data-plane reliability supervisor

PR-154 composes existing reliability controls into one durable admission boundary
for provider and webhook data.

## Provider path

Before provider evidence can reach strategy evaluation, the supervisor requires:

1. a non-expired candidate deadline;
2. available bounded queue capacity;
3. account-wide Jupiter quota reservation for the declared purpose;
4. rooted RPC quorum from independent correlation groups;
5. matching genesis, method, request hash, slot, payload and feature-set evidence;
6. a durable decision row and event-state record.

A failed quorum releases an unissued quota reservation. An admitted event records
the quota reservation ID, canonical slot, payload hash and RPC evidence hash.

## Webhook path

The supervisor uses the canonical Helius durable identity and stores only the
identity/payload hashes and decision metadata. It:

- rejects already admitted identities as duplicates;
- prevents queue overflow from silently dropping data;
- detects slot gaps against the last accepted webhook slot;
- records `gap_recovery_required` durably;
- allows the same event to be retried after rooted backfill closes the gap.

## Journal model

The SQLite journal separates append-only decisions from current event state.
This preserves every blocked/retried outcome while still enforcing durable dedup
for events that have already been admitted.

## Safety

- No provider HTTP call is made by the supervisor.
- No strategy, signer or sender is imported.
- No queue overflow is silently ignored.
- Quota is consumed only after independent rooted quorum succeeds.
- Blocked gap events can be replayed after explicit backfill.
