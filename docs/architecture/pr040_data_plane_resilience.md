# PR-040 — RPC, WebSocket, oracle and webhook data-plane resilience

## Status and boundary

This change introduces a transport-neutral, fail-closed data consistency layer for roadmap PR-040. It does **not** open sockets, call an RPC endpoint, send a transaction, alter live policy, or promote a provider. Network adapters supply normalized evidence; this package decides whether that evidence is coherent enough to reach detectors, planners, simulation, or later readiness endpoints.

The public package is `src.data_plane` and its evidence schema is `pr040.data-plane-resilience.v1`. Evidence admission is deterministic and independent from transport scheduling, so a faster response cannot bypass consistency policy.

## Why the legacy path is not extended

`src/ingest/rpc_multiplexing.py` mixes DNS workarounds, WebSocket transport, processed-commitment subscriptions, first-response blockhash racing, event parsing, Jito-era hooks and shared mutable state. Extending it would make PR-040 impossible to test deterministically and would preserve the unsafe assumption that the first or most common response is authoritative.

PR-040 therefore leaves that module untouched and adds a narrow boundary that a future adapter can feed. Until such an adapter is wired through the supported composition root, legacy transport output is not production data-plane evidence.

## Contracts

### Multi-RPC consistency without blind majority voting

`RpcConsistencyGate` accepts normalized `RpcSample` values and requires:

- the configured genesis hash;
- the exact RPC method and canonical request hash;
- commitment at or above policy;
- `context.slot >= minContextSlot`;
- bounded wall-clock and monotonic age;
- bounded slot divergence across accepted endpoints;
- an exact payload match from the configured number of endpoints at the highest coherent slot.

Older slots are not votes. Conflicting payloads at the same highest slot are always indeterminate, even if one payload has a numerical majority. The selected endpoint is only a transport choice among exact matches and is chosen deterministically by latency and then endpoint id.

### WebSocket reconnect, resubscribe and gap recovery

`WebSocketSubscriptionSupervisor` stores desired subscriptions independently from provider-issued subscription ids. Every reconnect increments a generation, invalidates old ids and requires all desired subscriptions to be acknowledged again.

Notifications are rejected when they belong to an old connection generation, an unknown subscription or a lower slot. A gap larger than the configured bound marks the endpoint `gap_detected` and produces a polling-backfill requirement. Readiness stays false until the missing range is explicitly covered. Heartbeat expiry and bounded deterministic exponential backoff are modeled without sleeping or opening a socket.

### Bounded polling fallback and detector backpressure

`PollingFallbackController` limits simultaneous polls and per-key cadence. It contains no unbounded retry loop. `DetectorBackpressureGate` bounds candidates admitted downstream and makes duplicate acquisition idempotent.

### Oracle safety

`OracleConsistencyGate` uses integer mantissa/exponent values only. It checks:

- an allowlisted source;
- trading status;
- publish slot at or above the decision context;
- wall-clock and monotonic freshness;
- non-zero price;
- integer, conservatively rounded confidence basis points.

Unknown, halted, stale, future-dated, below-context or wide-confidence observations fail closed.

### Authenticated webhook replay protection

`AuthenticatedWebhookGuard` is provider-auth-scheme neutral. A provider adapter supplies a constant-time signature verifier and normalized delivery id/timestamp. The guard enforces body size, bounded age/future skew, authentication, replay TTL and a bounded delivery-id cache. `HmacSha256Verifier` is supplied for raw-body HMAC contracts such as the currently used Helius adapter, but the policy layer does not claim that every provider uses the same signature scheme.

No secret, signature or raw body is included in readiness/evidence hashes. Delivery ids are hashed before evidence serialization.

### Readiness evidence

Every decision has a deterministic SHA-256 evidence hash. `DataPlaneReadinessAggregator` combines RPC, WebSocket, oracle and detector-capacity state. RPC ambiguity, oracle rejection or unavailable WebSocket coverage makes readiness false rather than silently degrading into executable data.

PR-042 may expose this report through `/ready` and `/status`; PR-040 itself does not add an HTTP server.

## Official Solana contract references

Verified against the official Solana documentation on **2026-07-20**:

- `accountSubscribe` accepts an explicit commitment and delivers notifications with `result.context.slot`: https://solana.com/docs/rpc/websocket/accountsubscribe
- `getMultipleAccounts` accepts commitment and `minContextSlot` and returns an `RpcResponse` context plus values in request order: https://solana.com/docs/rpc/http/getmultipleaccounts
- `getLatestBlockhash` accepts commitment and `minContextSlot` and returns both a response context and `lastValidBlockHeight`: https://solana.com/docs/rpc/http/getlatestblockhash

These contracts justify retaining commitment, request identity, context slot and minimum-context evidence. They do **not** define a universal acceptable age, cross-provider slot delta, heartbeat interval or gap size. Those values remain conservative operator policy and must be reviewed from telemetry rather than presented as Solana protocol guarantees.

## Integration with parallel roadmap work

- **PR-026** supplies canonical cluster URLs, genesis hash and commitment.
- **PR-033** should adapt immutable market snapshots into canonical request/payload hashes and only invoke detectors after PR-040 admission.
- **PR-035/036** can reuse the same `minContextSlot`, clock and RPC evidence for ALT, blockhash and exact-simulation calls, but their files are not modified here.
- **PR-038** owns the full paper/shadow composition root.
- **PR-042** owns operational endpoints, metrics and alerts.

The package deliberately does not import any unmerged branch. Integration must preserve the reason codes and evidence hashes rather than weakening policy to make a source appear healthy.

## Focused verification

```bash
python -m pytest \
  tests/test_pr040_rpc_ws.py \
  tests/test_pr040_oracle_guards.py \
  tests/test_pr040_readiness_safety.py \
  -q --disable-socket
python -m compileall -q src/data_plane tests/test_pr040_*.py
python -m black --check src/data_plane tests/test_pr040_*.py
python -m flake8 src/data_plane tests/test_pr040_*.py \
  --count --select=E9,F63,F7,F82 --show-source --statistics
python scripts/verify_repo.py
```

The focused suite covers exact multi-RPC matching, same-slot conflicts, foreign and stale RPCs, commitment/context checks, reconnect generations, resubscription, heartbeat expiry, out-of-order and gap handling, bounded poll fallback, oracle age and confidence, authenticated webhook replay/size/timestamp checks, detector backpressure and fail-closed aggregate readiness.

## Non-goals

- choosing or purchasing RPC providers;
- opening HTTP/WebSocket connections;
- changing `src/ingest/rpc_multiplexing.py` or the Helius server in this PR;
- decoding protocol accounts or oracle bytes;
- creating market candidates (PR-033);
- compiling, simulating, signing or submitting transactions;
- durable event storage/recovery (PR-041);
- HTTP health/readiness and alerts (PR-042);
- enabling live mode.
