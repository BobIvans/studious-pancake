# PR-135 — Provider-conformant webhook authentication and durable dedup

This PR adds an isolated PR-135 ingestion contract for Helius/webhook events.

## Scope

The roadmap requires webhook ingestion to match the provider contract, avoid
claiming undocumented body HMAC verification, make retry handling idempotent
across restarts and instances, and provide a backfill/gap-recovery decision
surface.

## What this patch adds

- `src/webhook_ingest_pr135.py`
  - Helius `Authorization` header verification against the configured
    `authHeader` value using constant-time comparison.
  - Redacted auth hashing for evidence without leaking the header value.
  - Raw/enhanced Helius schema separation.
  - Deterministic durable event identity from provider, signature, slot,
    event index and canonical payload hash.
  - SQLite-backed durable enqueue/dedup table.
  - Immediate `200` enqueue result for first delivery and duplicate retries.
  - Failed-transaction preservation instead of hiding failed webhook payloads.
  - Slot-gap recovery decision.
  - Webhook configuration drift comparison for monitored addresses, auth
    header secret reference, active status, network and webhook type.

- `tests/test_pr135_webhook_auth_dedup.py`
  - Authorization match/mismatch fixtures.
  - No body-HMAC claim fixture.
  - Durable dedup across restart.
  - Immediate 200 enqueue semantics.
  - Raw versus enhanced schema separation.
  - Failed transaction preservation.
  - Gap recovery and config drift fixtures.

## Non-goals

- No live trading.
- No sender, signer, RPC, Jito, Helius network call or webhook server wiring.
- No migration of the existing active webhook handler.
- No tracked runtime webhook config deletion in this slice.

## Why additive

Parallel PRs are actively changing `main`. This patch avoids shared hot files
such as `scripts/verify_repo.py`, workflow files and active data-plane handlers.
The module is a reviewable PR-135 boundary that can be wired after the existing
lifecycle/observability layers settle.
