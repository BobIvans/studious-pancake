# MPR-10 — Lifecycle queue and bounded observability gate

This document describes the safe additive slice for V6 **MPR-10 —
Lifecycle-consistent queueing, bounded shutdown and bounded observability**.

The gate added by this PR is intentionally offline. It does not start the
runtime, consume provider traffic, submit transactions, load wallets or migrate
production state. It only makes the acceptance contract for F-297…F-303 explicit
and machine-checkable so that a later installed-runtime cutover cannot claim
MPR-10 readiness from incomplete or self-inconsistent evidence.

## Boundary

`src/mpr10_lifecycle_queue_observability.py` validates
`mpr10.lifecycle-queue-observability.v1` evidence.

The report always keeps these capabilities disabled:

- `live_capability_allowed() == False`
- `signer_capability_allowed() == False`
- `sender_capability_allowed() == False`

## What the evidence must prove

The gate requires:

- one lifecycle authority for queue admission, expiry, claim and terminal
  outcome;
- expiry that records a terminal result and releases or terminalizes the
  `PENDING` lifecycle identity;
- public expiry serialized with put/get queue mutation;
- consumer-side expiry bound to lifecycle terminalization before sink result;
- crash/restart replay preserving the same expiry terminal outcome;
- shutdown that stops admission, avoids timeout-then-unbounded-drain, and marks
  remaining work resumable or aborted within a bounded grace period;
- cancellation-safe terminalization and structured worker ownership;
- terminal tracker TTL/capacity, durable dedupe handoff and eviction metrics;
- windowed/streaming observability instead of full-history in-memory sorting;
- finite and bounded timing inputs, with explicit rejection coverage for NaN,
  infinities, negative delays and excessive delays.

## Finding map

| Finding | Gate requirement |
|---|---|
| F-297 | Expiry releases/terminalizes `PENDING` lifecycle identity |
| F-298 | Public expiry is lock-protected or single-owner serialized |
| F-299 | Consumer-side expiry terminalizes lifecycle before sink result |
| F-300 | Shutdown has no unbounded second drain after timeout |
| F-301 | Terminal tracker memory is bounded and durable dedupe-backed |
| F-302 | Observability aggregation is windowed/streamed and bounded |
| F-303 | Duration/ratio config rejects NaN, infinity and excessive values |

## Deliberate non-goals

This PR does not:

- replace the runtime queue implementation;
- migrate lifecycle state;
- run a real multi-day soak;
- introduce live trading;
- load a wallet or signer;
- call provider/RPC endpoints;
- alter Docker/Compose topology.

## Remaining full MPR-10 work

A later implementation must wire this contract into the installed composition
after the shared MPR-08/MPR-09 schemas are stable. The real runtime must move
queue transitions into the durable authority or make them atomic with lifecycle
state, run concurrent queue stress and shutdown chaos, and expose bounded
observability queries from production storage rather than self-declared evidence.
