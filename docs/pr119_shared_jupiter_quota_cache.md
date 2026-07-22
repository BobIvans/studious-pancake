# PR-119 — Shared Jupiter quota/cache review gate

PR-119 adds a low-conflict, offline review gate for the Jupiter quota/cache
contract without enabling live trading or transaction submission.

## Scope

- Requires explicit Jupiter request purposes for discovery, exact amount
  coupling, refinement, final build, rebuild after blockhash/CU changes and
  finalization.
- Requires a protected finalization reserve so broad discovery cannot spend the
  whole Jupiter account budget before a proof-critical final build.
- Requires a shared quota authority keyed by API account identity.
- Requires redaction-safe exact request cache identity including request
  fingerprint, exact amount, taker, mode, purpose and schema pin.
- Requires cache reuse before quota spend.
- Requires numeric and HTTP-date `Retry-After` support and propagation into the
  quota boundary.
- Requires telemetry for purpose counts, cache hits, quota waits,
  finalization denial, HTTP 429 and stale discards.

## Safety boundary

This patch does not enable live mode, sender imports, signer access, RPC/Jito
submission, wallet mutation, MarginFi execution, paper outcome fabrication or
provider promotion. It creates a fail-closed contract that later runtime wiring
can satisfy.

## Why review-only

Parallel PRs are actively changing main. Keeping PR-119 as an additive review
boundary avoids rewriting active runtime discovery while PR-113/118/123/127 are
still pending.

## Follow-up boundaries

- PR-113 remains responsible for full exact amount-coupled route correctness.
- PR-118 remains responsible for non-monotonic sizing.
- PR-123 remains responsible for hardened HTTP transport.
- PR-127 remains responsible for provider-native expiry and full clock/slot
  freshness semantics.

## Suggested verification

```bash
python -m pytest tests/test_pr119_shared_jupiter_quota_cache.py -q \
  --disable-socket --allow-unix-socket
python scripts/verify_repo.py --skip-dependency-audit
```
