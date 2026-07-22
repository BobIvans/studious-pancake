# B2 — Helius delivery-plane durability

This PR implements the active Helius delivery-plane boundary requested by the production-ready workplan task B2.

It does **not** replace PR #160. PR #160 remains the Helius management-plane authority; this PR covers delivered webhook traffic after Helius calls the configured endpoint.

## What the new boundary does

`src.providers.helius.delivery.HeliusDeliveryPlane` validates the incoming delivery before any strategy work and persists a durable SQLite inbox before returning an HTTP-200-style acknowledgement.

The boundary provides:

- constant-time comparison of the delivered `Authorization` header against configured `authHeader`;
- no Authorization value, API key, query secret, raw URL or raw provider exception persisted by this module;
- compressed and decompressed request size limits;
- UTF-8, JSON depth, JSON node and event-count limits;
- transactional delivery and event inbox persistence before acknowledgement;
- persistent duplicate detection across restarts and multiple process instances using SQLite uniqueness;
- slot-gap detection that marks delivery evidence as requiring rooted RPC backfill;
- explicit failed-transaction policy: preserve, reject, or drop-with-audit;
- sender/live remains unreachable.

## Intended active integration point

The webhook ingress layer should parse the HTTP request into `headers` and `raw_body`, call:

```python
outcome = HeliusDeliveryPlane(config).accept_delivery(
    headers=request.headers,
    raw_body=await request.read(),
    webhook_id=resolved_webhook_id,
)
```

Then it should return `outcome.http_status` immediately and let downstream workers consume `helius_event_inbox` rather than doing strategy work inside the HTTP request.

## Non-goals

- No Helius management-client changes.
- No sender/signing/submission path.
- No live trading.
- No RPC backfill implementation in this PR; this PR records the durable `backfill_required` state for the follow-up rooted RPC worker.
- No strategy/opportunity execution inside the HTTP acknowledgement path.
