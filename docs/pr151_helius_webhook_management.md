# PR-151 — Helius webhook management hardening

## Goal

Replace stale and permissive Helius management scripts with one strict management-plane contract. This PR is a concrete implementation slice of the production-debt work already merged in PR #159; it does not duplicate that audit.

## Contract corrections

- Management base URL is pinned to `https://api-mainnet.helius-rpc.com/v0`.
- Create/list/get/update/delete use explicit request timeouts.
- API keys are passed through the HTTP client's query-parameter mechanism and are never interpolated into a printable URL string.
- Management responses use canonical `webhookID`; legacy `webhookId` is rejected.
- Response bodies are size bounded and must decode as UTF-8 JSON.
- Create/update payloads are allowlisted; management metadata returned by GET is not echoed into PUT.
- Production creation requires a publicly reachable HTTPS delivery URL.
- Production creation requires `authHeader` for delivery authenticity.
- Written local config redacts the authentication header.
- Missing `WEBHOOK_URL` or `HELIUS_WEBHOOK_AUTH_HEADER` fails before network I/O.

## Remaining Helius debt

This PR does not complete the delivery plane. The supported runtime still needs:

- verification of the delivered authentication header;
- bounded request-body parsing;
- persistent delivery deduplication and replay windows;
- durable acknowledgement before HTTP 2xx;
- retry-aware idempotency;
- slot/root ordering and backfill after stream gaps;
- remote configuration drift checks;
- operational metrics and alerts.

## Safety boundary

- no live trading;
- no signer or private key;
- no transaction or Jito submission;
- no automatic webhook creation during application startup;
- no external call in tests;
- legacy Jito and execution modules remain quarantined.

## Focused verification

```bash
python -m py_compile \
  src/external_contracts/helius_webhooks.py \
  scripts/manage_webhooks.py \
  scripts/setup_helius_webhook.py \
  src/ingest/webhook_config.py \
  tests/test_pr151_helius_webhook_management.py

python -m pytest -q tests/test_pr151_helius_webhook_management.py
```
